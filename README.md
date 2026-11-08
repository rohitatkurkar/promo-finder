# Promo Finder

Reads a microdrama screenplay and recommends the moments to use as 20 to 60 second promo clips on Instagram, TikTok and YouTube. For each clip it gives the episode, exact start and end times, the hook, the cliffhanger, why it could work, and a place in a ranking.

It only finds moments. It does not edit video, add music or post anything.

## Status

| Part | State |
|---|---|
| Basic mode | Works. Run on a real 50 episode pack with verified output |
| AI assisted mode | Built and tested against a stand in server. **Never run on a real model, so its quality is unknown** |
| Human review | Not done. All ratings are blank |

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

The interface, which has upload, results, clip details and downloads:

```bash
streamlit run app.py
```

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
| `top_twenty_human_review_sheet.csv` | Blank sheet for a person's ratings |

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

- This repository holds no real screenplay content. `sample_input/` is an invented show.
- `.gitignore` excludes `.env`, `outputs/`, `inputs/`, `private/` and ZIP files other than the sample.
- Result files quote the screenplay, so keep them out of public places.
- Keys are read only from `.env`, and are removed from anything saved or printed.
- The interface only accepts connections from your own computer. Do not deploy it publicly with confidential scripts.
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
