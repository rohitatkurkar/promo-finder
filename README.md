# Promo Finder

Reads a microdrama screenplay and recommends the moments to use as 20 to 60 second promo clips on Instagram, TikTok and YouTube. For each clip it gives the episode, exact start and end times, the hook, the cliffhanger, why it could work, and a place in a ranking.

It only finds moments. It does not edit video, add music or post anything.

## Status

| Part | State |
|---|---|
| Basic mode | Works. Run on a real 50 episode pack with verified output |
| AI assisted mode | Run on a real model (Groq) for Episode 1 only. Quality across the show is not yet known |
| Human review | The interface can record reviews (see "Human review" below). No real reviews have been entered yet |

## The rule behind the tool

**A language model never decides a timestamp.** Models point at cue IDs such as `E06_C0012`. Python looks up the real times in the screenplay, checks the clip, and rejects anything invalid. The finder model never even sees a timestamp, so it cannot invent one.

## Two modes

| | Basic | AI assisted |
|---|---|---|
| API key | Not needed | Needed |
| How it picks | Signals: an episode's final beat, the writers' notes and summary, acting notes, reactions, pace | A model reads each episode, and a different model judges the clips |
| Judges story quality | No | Yes, through blind tests |
| Label on results | "Basic selections" | "AI assisted selections" |

## Install

Python 3.11 or newer runs the code and the tests. **To reproduce the archived Basic results exactly, use Python 3.12 or newer.** Python 3.12 changed how `sum()` adds decimals, so on 3.11 two Basic scores come out 0.01 different (74.87 instead of 74.86, 61.19 instead of 61.2). The ranking is the same. The archived run was made on Python 3.13. `requirements-lock-windows.txt` lists the exact versions last tested, on Windows 11 with Python 3.14.0.

A virtual environment only works on the system that made it. Never copy `.venv` between macOS and Windows; make a new one.

macOS or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows (PowerShell). `py -3.14` picks the Python version; use any installed version from 3.12 up:

```powershell
py -3.14 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If PowerShell refuses to run `Activate.ps1`, skip activation and call the environment's Python directly, for example `.venv\Scripts\python.exe run.py ...` and `.venv\Scripts\python.exe -m pytest`. To copy the example settings on Windows, use `Copy-Item .env.example .env` instead of `cp`. Paths with spaces need quotes, for example `--input "..\inputs\My Show-scripts.zip"`.

Text results (JSON, Markdown, JSONL) are always written with LF line endings, so runs on Windows and macOS can be compared byte for byte. `.gitattributes` keeps source files in LF too.

## Run on a screenplay pack

A pack is a ZIP or folder of `.txt` episode files. To try it on a new show during an interview, point `--input` at the new ZIP. Nothing else changes.

Basic mode, no key needed:

```bash
python run.py basic --input sample_input/synthetic_show.zip --out outputs/basic_demo
```

AI assisted mode:

```bash
cp .env.example .env
python run.py check-provider
python run.py ai --input sample_input/synthetic_show.zip --out outputs/ai_demo
```

If a run stops, because of a rate limit for example, run the same command again. It continues from where it stopped.

The interface, which has upload, results, clip details, human review and downloads:

```bash
streamlit run app.py --server.address localhost
```

Then open http://localhost:8501. On Windows: `.venv\Scripts\python.exe -m streamlit run app.py --server.address localhost`. The `--server.address localhost` part keeps the app reachable only from your own computer, which matters when you upload confidential scripts.

The app opens on the **final AI run on all 50 episodes** (33 promos), bundled in `demo_runs/`. "Earlier runs" also offers the initial AI trial (Episode 1 only) and a Basic mode run on the invented sample show, then any runs saved on the computer running the app. `demo_runs/catalog.json` sets their labels, order and which one opens first.

Each bundled AI run holds only the files the interface reads, copied unchanged from the original run: `promos.json`, `processing_summary.json`, `promos.csv`, `report.md`, the blank review sheet, and the evaluations of the recommended clips. Model replies, logs, usage records, per-episode files, rejected candidates and the screenplay pack itself are left out. No run on a subset such as Episodes 10 to 20 exists, so none is shown.

Each bundled run also holds `transcripts.json`: for every recommended clip, the screenplay cues that play inside that clip (times, speaker, delivery note, dialogue, action and camera lines), copied unchanged from the parsed screenplay and keyed by the run and the clip's `clip_key`. "See the screenplay for this clip" shows them. Nothing outside the clips is copied. Rebuild them with `python tools/build_transcript_excerpts.py --pack PACK.zip --run demo_runs/RUN_FOLDER`; no model is called.

The sidebar has three parts: **Existing runs** (open a saved run; this only reads its results), **Human review** (reviewer name and blind mode, for the run that is open) and, folded away, **Run on a new screenplay pack** (upload or sample show, mode, Find promos).

Optional settings, set in the shell before starting:

| Setting | What it does |
|---|---|
| `PROMO_OUTPUT_DIR` | The folder of runs to list and save to. Default `outputs/` |
| `PROMO_PACK_DIR` | A folder holding the screenplay packs. The interface finds a run's pack there by file name, so its transcript shows without uploading the pack again |
| `PROMO_DEFAULT_RUN` | A run folder to open first, instead of the bundled final run |
| `PROMO_BLIND_REVIEW_DEFAULT` | `1` starts with blind review mode on |
| `PROMO_REVIEW_SET` | A JSON file with `run_id` and `clip_keys`. For that run, the clip list is limited to those clips (a checkbox turns this off), with Previous and Next buttons and a progress count |

AI assisted mode in the interface has an "Episodes to process" box (for example `1-3`). Empty means every episode in the pack; there is no episode limit, locally or hosted. Choosing AI assisted mode starts nothing; models are called only when Find promos is clicked. One AI run goes at a time per app: a second one is refused with a message (Basic mode is not affected), because every run shares one API key and its rate limits.

## Deploy on Streamlit Community Cloud

The app runs on Streamlit Community Cloud (free) from this repository, with `app.py` as the entry point and `requirements.txt` for its packages.

1. At https://share.streamlit.io sign in with GitHub and choose **Create app**, then **Deploy a public app from GitHub**.
2. Repository `rohitatkurkar/promo-finder`, branch `main`, main file `app.py`.
3. Under **Advanced settings**, choose Python **3.12**. Version 3.12 or newer reproduces the archived Basic results exactly.
4. In **Secrets**, paste the lines from `.streamlit/secrets.toml.example` with your own values. The Groq key goes only there, never into the repository.
5. Deploy.

How the hosted app behaves:

- **Basic mode, the demo, transcripts and human review** need no key.
- **AI assisted mode** is open to anyone with the link, with no password. Every AI run spends the owner's Groq free-tier quota, so strangers can use it up; when the quota or rate limit is reached, runs stop early and keep their progress. There is no episode limit, so one run on a large pack can use a large share of the quota. One AI run goes at a time. To close AI mode, remove the key from the secrets.
- **Storage is temporary.** Runs and reviews saved on the hosted app are wiped when it restarts, when it sleeps (after 12 hours without visitors) and on every redeploy, because Community Cloud restarts from a fresh copy of the repository. Download reviews with the export buttons to keep them.
- **Storage is shared.** Everyone using the hosted app sees the same saved runs and reviews. With blind review mode off, the comparison table shows every reviewer's ratings and comments, and runs other visitors made appear under "Earlier runs".
- **Uploads go to the host.** A ZIP uploaded to the hosted app is sent to Streamlit's servers, and in AI assisted mode to the model provider. Do not upload confidential scripts to a public app.

## Human review

Pick a run and a clip, read the full transcript under "See the screenplay for this clip", then rate it in the Human review form:

- Hook quality, cliffhanger quality, clarity and overall quality, each 1 to 5
- Would publish? Yes, No or Maybe
- Optional comments

Enter a reviewer name or ID in the sidebar first. Several people can review the same run; each person's latest review of a clip counts.

**Blind review mode** (sidebar) hides the AI's rank, scores, ratings, explanations and result files, and lists clips in story order, so they cannot sway the rating. Turn it off to see **Human review compared with AI**, a table with the AI's ratings beside the human ones, and to export the reviews as CSV or JSON.

Reviews are saved in `<runs folder>/human_reviews/human_reviews.jsonl`, one line per saved review, never edited. Each review records the run folder name, the promo's `clip_key` (the stable ID built from its hook and ending cues), its `promo_id`, the reviewer, the time, and a fingerprint of the run's `promos.json`, so a run regenerated after review is flagged. Reviews never change the run's files, the ranking, the prompts or the models, and make no API calls. They stay on the computer running the app and are ignored by Git. On a hosted app that storage is temporary, so export them.

## Change the model

Edit `.env`. Any provider with an OpenAI compatible API works with no code change, including Groq, Gemini, Anthropic, OpenRouter, Mistral and local Ollama.

```
LLM_BASE_URL=https://your-provider.example/v1
LLM_API_KEY=your-key
FINDER_MODEL=model-that-reads-episodes
EVALUATOR_MODEL=a-different-model-that-judges
```

You can also try a model for one run:

```bash
python run.py ai --input pack.zip --out outputs/test --finder-model some-model --evaluator-model another-model
```

## What a run produces

| File | What it is |
|---|---|
| `promos.json` | Every recommendation, in the validated format |
| `promos.csv` | The same recommendations as a spreadsheet |
| `report.md` | A readable ranking, with the first post recommendation |
| `processing_summary.json` | What was processed, what failed and why |
| `usage_summary.json` | Real model calls, tokens and cost (AI assisted mode) |
| `rejected_candidates.json` | Clips that failed a test, with the reasons |
| `top_twenty_human_review_sheet.csv` | Blank sheet for rating offline. Reviews entered in the interface are kept separately (see "Human review") |

## Check the output

```bash
pytest
python run.py compare-runs --first outputs/run_a --second outputs/run_b --out outputs/stability
python run.py judge-basic --input pack.zip --run outputs/basic_run
python run.py compare-modes --basic outputs/basic_run --ai outputs/ai_run --out outputs/comparison
python run.py worksheet --input pack.zip --out outputs/reference_kit
python run.py reference-check --reference filled_sheet.csv --run outputs/ai_run --out outputs/reference.json --reference-label "Human picks"
```

## Confidentiality

Screenplay packs may be confidential.

- The screenplay pack itself is not in this repository. `sample_input/` is an invented show.
- **The two bundled AI runs in `demo_runs/` quote the real screenplay**: the show title, the opening and final lines of each promo, character names, and the models' short descriptions of each clip. They were included on purpose, for the public demo. The confidentiality scan below reports them; that is expected.
- `.gitignore` excludes `.env`, `outputs/`, `inputs/`, `private/` and ZIP files other than the sample.
- Other result files quote the screenplay too, so keep them out of public places.
- Keys are read only from `.env`, or on a hosted app from its secrets, and are removed from anything saved or printed.
- Started with `--server.address localhost`, the interface only accepts connections from your own computer. A hosted copy is public: do not upload confidential scripts to it.
- Check a provider's data terms before sending it a confidential script. See `DESIGN_DECISIONS.md`.

Before publishing anything, run:

```bash
python tools/check_confidentiality.py --pack PATH_TO_PRIVATE_ZIP --check .
```

## Limits

- Scores compare clips with each other. They do not predict how an ad will perform.
- Nothing has been tested on a real audience. A person should review every clip.
- It reads scripts, so it cannot see how a scene was actually acted or shot.
- Version 1 finds single continuous clips. Joining moments is not built yet.
- It expects the screenplay format of this pack. Other formats are reported as problems, not guessed at.

More detail: `DESIGN_DECISIONS.md`, `TEST_REPORT.md`, `FAILURE_ANALYSIS.md`, `DEVLOG.md`.
