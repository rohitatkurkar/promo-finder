# Promo Finder: Interview Operating Guide

A practical guide to running, explaining and changing this project on your own Windows computer, without help.

Everything here describes the code as it is at commit `a9b6b2b` (Supabase phase 2). Where something is **not built**, the guide says so. Commands are for **Windows PowerShell**.

Contents:
A. Understanding the project ·
B. Opening the project ·
C. Running the app ·
D. Uploading a new dataset ·
E. API keys and models ·
F. Switching to Claude (future) ·
G. Supabase and persistence ·
H. Common tasks and troubleshooting ·
I. Cheat sheet

---

## A. Understanding the project

### What it does

Promo Finder reads a **microdrama screenplay pack** (a ZIP of episode `.txt` files) and recommends **20 to 60 second promo clips** for Instagram, TikTok and YouTube. For each clip it gives the episode, exact start and end times, the opening hook line, the closing cliffhanger line, why it could work, and a rank.

It only **finds** moments. It does not edit video, add music or publish anything.

**The rule behind the whole design:** a language model never decides a timestamp. Models only point at **cue IDs** such as `E06_C0012`. Python looks up the real times in the screenplay, builds the clip and rejects anything invalid.

### Overall architecture

```
Screenplay ZIP
   │
   ▼
parser.py ──────── reads every .txt, gives each timed block (cue) a permanent ID like E06_C0012,
   │                records every data problem (never silently drops anything)
   ▼
┌──────────────────── Basic mode (no key) ────────────────────┐   ┌──────────── AI assisted mode (Groq) ────────────┐
│ basic_mode.py + signals.py: every sensible hook × ending      │   │ ai_mode.py:                                       │
│ pair scored on simple text signals                            │   │  1. FINDER model points at hook and ending cue IDs│
└───────────────────────────────────────────────────────────────┘   │  2. code builds the clips (boundaries.py)         │
   │                                                                │  3. EVALUATOR model: blind hook test (first 3 s)  │
   │                                                                │     and cold-viewer test (names masked)           │
   │                                                                │  4. gates; 5. finalist spoiler / premise review   │
   │                                                                └───────────────────────────────────────────────────┘
   ▼                                                                   │
boundaries.py ── every clip: 20–60 s, hook in the first 3 s, cuts snapped to clean line ends
ranking.py ───── scores, spoiler penalty, duplicate removal, variety across episodes
schema.py ────── checks every time, cue ID and quotation against the parsed screenplay (verification)
outputs.py ───── promos.json, promos.csv, report.md, processing_summary.json, ...
excerpts.py ──── transcripts.json: the screenplay cues of each recommended clip
   │
   ▼
app.py (Streamlit) ── results, clip details, screenplay excerpts, human review, downloads
stores.py + cloud.py ── reviews and finished runs saved to files, or to Supabase on the hosted app
```

`pipeline.py` runs everything in order and saves progress after every episode (`checkpoint.json`), so a stopped command-line run continues where it stopped.

### How a ZIP flows through the system

1. **Parsing** (`parser.load_pack`): checks the ZIP's size limits, reads each `.txt`, works out the episode number, splits the text into scenes and cues, and gives each cue an ID (`E01_C0027`). Problems are recorded as issues (written to `data_quality.json`).
2. **Candidate discovery:**
   - **Basic:** `basic_mode.py` takes the strongest openings and endings in each episode by `signals.py` clues (position in the episode, acting notes, pace, reactions, keywords with caps), tries every pair, and keeps clips scoring at least 60. At most 2 clips per episode.
   - **AI:** the finder model reads one episode (without timestamps) and returns up to five hook and five ending cue IDs. Code pairs them into clips. At most 3 candidates per episode.
3. **Clip building** (`boundaries.py`): a pair becomes a clip only if it lasts 20–60 seconds, the hook falls within the first 3 seconds, and the cuts land on clean line ends. Otherwise the reason is recorded.
4. **AI evaluation** (AI mode only, `ai_mode.py`): a different model runs
   - the **hook test**: sees only the first 3 seconds; rates the hook 1–5;
   - the **cold-viewer test** (only if the hook is 4 or 5): sees the clip with speaker names masked (`masking.py`); rates clarity, ending pull and more, and says whether the ending settles the conflict.

   A clip is recommended only if it passes every gate: hook ≥ 4, ending ≥ 4, the ending does not resolve the conflict, and the cold viewer understood it. Finalists then get a spoiler, premise-fit and ad-risk review in batches of 8, seeing story summaries only up to the latest episode in the batch.
5. **Ranking** (`ranking.py`): weighted score; spoiler penalty (medium 5, high 15); duplicate removal; variety penalty for several clips from the same or a neighbouring episode (8 and 4 points, at most 12).
6. **Verification** (`schema.py`, `outputs.verify_all`): every promo's times, cue IDs and quotes are re-checked against the parsed screenplay. The count of errors is shown as "Verification errors".
7. **Output** (`outputs.py`, `excerpts.py`): result files in the run folder (list in section D).

### What each important file does

| File | Job |
|---|---|
| `app.py` | The Streamlit interface: run list, new runs, results, clip details, screenplay excerpts, human review, downloads |
| `run.py` | Command line: `inspect`, `basic`, `ai`, `check-provider`, `worksheet`, `judge-basic`, `compare-modes`, `compare-runs`, `reference-check` |
| `promo_finder/parser.py` | Reads the screenplay format into episodes, scenes and cues; records data problems; ZIP size limits |
| `promo_finder/pipeline.py` | Runs Basic or AI mode end to end, with checkpoints and resume |
| `promo_finder/basic_mode.py`, `signals.py` | Basic mode's candidate search and its text signals |
| `promo_finder/ai_mode.py` | Finder, hook test, cold-viewer test, gates, finalist review |
| `promo_finder/prompts.py` | Every model prompt, each with a version (a new version means the saved replies are not reused) |
| `promo_finder/llm_client.py` | The one client that talks to the model provider (OpenAI-compatible API, e.g. Groq): pacing, retries, saved replies, usage log |
| `promo_finder/boundaries.py` | Turns a hook cue and an ending cue into a real clip, or rejects it with a reason |
| `promo_finder/masking.py` | Hides speaker names for the cold-viewer test |
| `promo_finder/ranking.py` | Scoring weights, spoiler penalty, duplicates, variety ranking |
| `promo_finder/schema.py` | The promo format and its verification against the screenplay |
| `promo_finder/outputs.py` | Builds promos and writes JSON, CSV, report, data-quality report |
| `promo_finder/excerpts.py` | Writes `transcripts.json` (screenplay of each recommended clip) |
| `promo_finder/reviews.py` | The human-review record, history rules, comparison table, exports |
| `promo_finder/stores.py` | Review store and run store: files locally, Supabase when configured |
| `promo_finder/cloud.py` | Small Supabase client (database rows and private file storage) |
| `promo_finder/hosting.py` | Merges `.env` and Streamlit secrets; API-key check; episode selection; one-AI-run-at-a-time lock |
| `promo_finder/uploads.py` | Stores uploaded ZIPs once per content; unique run folder names |
| `promo_finder/evaluation.py`, `worksheets.py` | Comparison tools and blank reference sheets used by the command line |
| `demo_runs/` | The three bundled runs the app opens with (final 50-episode AI run, Episode 1 trial, sample show) |
| `sample_input/synthetic_show.zip` | A tiny **invented** 3-episode show, safe to use anywhere |
| `supabase/migrations/` | `0001_reviews.sql` and `0002_runs.sql`, run once in Supabase |
| `tools/` | `check_confidentiality.py`, `build_transcript_excerpts.py`, `import_reviews_to_supabase.py`, `build_submission.py` |
| `tests/` | The automated tests (`pytest`) |

### Basic mode vs AI mode

| | Basic | AI assisted |
|---|---|---|
| API key | Not needed | Needed (Groq by default) |
| How it picks | Text signals over every hook × ending pair | Finder model proposes cues; a different evaluator model judges |
| Story judgement | None (labelled "Basic selections") | Blind hook test and cold-viewer test (labelled "AI assisted selections") |
| Speed | Seconds | Minutes (about 10 minutes for 10 episodes, about 44 minutes for 50 from scratch) |
| Choose episodes | No, always the whole pack | Yes, "Episodes to process" (for example `1-3,5`) |
| Cost | Free | Uses the provider's quota |

### What Supabase is responsible for

Only when `SUPABASE_URL` and `SUPABASE_SECRET_KEY` are set (on the hosted app they are):
- **Human reviews** (table `reviews`), kept under each visitor's private link.
- **Finished runs**: their files in the private bucket `promo-data`, plus one row in table `runs`.

Supabase does **not** run the pipeline, store the model-reply cache, or resume interrupted runs.

### What is stored where

| Data | Local app (no Supabase settings) | Hosted app (Supabase configured) |
|---|---|---|
| Run results | `prototype\outputs\<run folder>\` | The app's temporary disk, **plus** Supabase Storage once finished |
| Reviews | `prototype\outputs\human_reviews\human_reviews.jsonl` | Supabase table `reviews` |
| Saved model replies | `prototype\outputs\llm_cache\` | The app's temporary disk only |
| Uploaded ZIP | `%TEMP%\promo_upload_<hash>\` (deleted after a day unused) | The host's temporary disk |
| Bundled demo runs | `prototype\demo_runs\` (in Git) | Same, from Git |
| Settings and keys | `prototype\.env` (never committed) | Streamlit Cloud → Settings → Secrets |

`outputs/` can be moved with the `PROMO_OUTPUT_DIR` setting (section C).

---

## B. Opening the project locally on Windows

The project lives in `D:\0 Kuku FM\KUKU FM`. The Git repository and the app are in its `prototype` subfolder. The virtual environment is `prototype\.venv`, made with **Python 3.14.0**.

### 1. Open the project folder

```powershell
cd "D:\0 Kuku FM\KUKU FM\prototype"
```

The quotes are needed because the path has spaces.

### 2. Activate the virtual environment

```powershell
.venv\Scripts\Activate.ps1
```

If PowerShell refuses ("running scripts is disabled on this system"), you have two options:
- **Simplest:** skip activation and call the environment's Python directly every time, for example `.venv\Scripts\python.exe run.py --help`. Everything in this guide works that way: replace `python` with `.venv\Scripts\python.exe`.
- Or allow scripts **for this PowerShell window only**, then activate:
  ```powershell
  Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
  ```

### 3. How to tell it is active

- The prompt starts with `(.venv)`.
- This prints a path ending in `prototype\.venv\Scripts\python.exe`:
  ```powershell
  (Get-Command python).Source
  ```

### 4. Leave the virtual environment

```powershell
deactivate
```

### 5. If `.venv` does not exist

Create it with Python 3.12 or newer (3.12+ reproduces the archived Basic scores exactly; 3.14 was used):

```powershell
py -3.14 -m venv .venv
```

`py --list` shows which Python versions are installed. Never copy a `.venv` from another computer; make a new one.

### 6. Install the requirements

```powershell
python -m pip install -r requirements.txt
```

`requirements.txt` lists: `requests`, `pydantic`, `python-dotenv`, `streamlit`, `pytest`, `pandas`.

### 7. Check versions

```powershell
python --version
python -m pip show streamlit pydantic pandas requests python-dotenv pytest
```

Versions last checked: Python 3.14.0, streamlit 1.67.0, pydantic 2.14.3, pandas 2.3.3, requests 2.34.2, python-dotenv 1.2.4, pytest 9.2.0. `requirements-lock-windows.txt` records exact tested versions.

---

## C. Running the local Streamlit application

### Launch

From `prototype`, with the venv active:

```powershell
python -m streamlit run app.py --server.address localhost
```

`--server.address localhost` keeps the app reachable only from your own computer, which matters when you upload a confidential screenplay.

### Find the URL and open it

The terminal prints `Local URL: http://localhost:8501`. Streamlit usually opens the browser itself; if not, paste that address into the browser.

### Stop the server

Click the PowerShell window and press **Ctrl+C**.

### Port already in use

If the terminal says the port is in use, or the app opens an old version:

```powershell
Get-NetTCPConnection -LocalPort 8501 -State Listen
```

This shows the `OwningProcess` number. To see what it is:

```powershell
Get-Process -Id <OwningProcess number>
```

Either stop that program yourself (Ctrl+C in its window), or start this app on another port:

```powershell
python -m streamlit run app.py --server.address localhost --server.port 8502
```

### Reading terminal messages

| Message | Meaning |
|---|---|
| `Please replace use_container_width with width` | A harmless Streamlit deprecation notice. Ignore it. |
| `ModuleNotFoundError: No module named ...` | The venv is not active, or requirements are not installed (section H). |
| A red error box in the browser with a `Traceback` | A real error. The last line names it; the line with `app.py` or `promo_finder\...` shows where. |
| `Could not read this pack. ...` (in the page) | The ZIP itself was rejected (section D troubleshooting). |
| `AI assisted mode could not start. ...` | Settings problem before any episode: missing model or key, or a refused key. |

### Optional local settings

Set them in the same PowerShell window **before** starting the app (they last until the window is closed):

| Setting | What it does |
|---|---|
| `$env:PROMO_OUTPUT_DIR = "D:\some\folder"` | Folder for runs and reviews (default `prototype\outputs`) |
| `$env:PROMO_PACK_DIR = "D:\0 Kuku FM\KUKU FM\inputs"` | Folder of screenplay packs, so a run's full screenplay shows without re-uploading |
| `$env:PROMO_DEFAULT_RUN = "<run folder>"` | Open this run first |
| `$env:PROMO_BLIND_REVIEW_DEFAULT = "1"` | Start with blind review mode on |
| `$env:PROMO_REVIEW_SET = "<file>.json"` | Limit one run's clip list to a review set (`run_id` and `clip_keys`) |
| `$env:PROMO_SHARED_HOST = "1"` or `"0"` | Force the "shared host" behaviour on or off (see section G) |

---

## D. Uploading a completely new dataset

### The ZIP format the parser expects

A ZIP of `.txt` files (folders inside are fine). Each file is one episode:

```
EPISODE NUMBER: Episode 1
EPISODE LOGLINE: One line about the episode.
CONTINUITY NOTES: Notes about what came before.

--- SCRIPT START ---

SCENE 01
Scene heading: INT. COURTHOUSE - DAY
Scene start: 00:00.00
Scene end: 01:02.00

Actions and dialogue:

**CAMERA:**
Start: (00:00.00) | End: (00:02.00)
Wide shot of a crowded courthouse.

**PROSECUTOR (Cold, Accusing):**
Start: (00:02.00) | End: (00:04.50)
"You let your own brother drown!"

--- SCRIPT END ---
```

The rules, from `parser.py`:
- **Episode number:** from the `EPISODE NUMBER:` line; otherwise from the file name (`episode-001`, `episode_1`, `episode 1`). If they disagree, the header wins and an issue is recorded. A file with no number anywhere is skipped and reported.
- **Cue label:** a line `**LABEL:**`. `CAMERA`, `ACTION` and labels starting with `SOUND` are those kinds; anything else is dialogue spoken by that name. Text in brackets is a delivery note (`(Cold, Accusing)`); `(V.O.)` and `(O.S.)` mark voice-over and off-screen.
- **Cue time:** the line `Start: (MM:SS.ss) | End: (MM:SS.ss)`. Minutes can be 1–3 digits; seconds must be under 60.
- `SCENE heading/start/end` lines may be in Title Case or UPPER CASE.
- Anything not understood is recorded as an `unrecognised_line` issue, never silently dropped.

**Pack limits** (checked before anything is unpacked): at most **500 files**, **2 MB per file** and **50 MB in total** unpacked. The uploader accepts files up to 200 MB. Non-`.txt` files are listed as `ignored_non_txt_file`; macOS `__MACOSX/` and hidden files are ignored. If two files have the same episode number, the first is kept (`duplicate_episode`). A file that is not UTF-8 is read as Latin-1 and reported (`not_utf8`).

### 1. Receive the ZIP

Save it somewhere you can find, for example `D:\0 Kuku FM\KUKU FM\inputs\new_pack.zip`. Treat it as confidential: keep it out of the `prototype` folder and out of Git (`*.zip` is ignored anyway, except the sample).

### 2. Check its structure before uploading

List the files inside:

```powershell
python -c "import zipfile,sys; print(*zipfile.ZipFile(sys.argv[1]).namelist(), sep='\n')" "D:\path\to\new_pack.zip"
```

Then let the parser report what it finds and every data problem (this sends nothing anywhere):

```powershell
python run.py inspect --input "D:\path\to\new_pack.zip"
```

It prints the episode count and numbers, cues by kind, cues without valid times, runtime and `issue_counts`. To save the full list of issues, add `--out "D:\some\folder"`; it writes `data_quality.json` there.

### 3. Understand the data-quality warnings

| Issue | Meaning | Usually OK? |
|---|---|---|
| `missing_episodes` | A gap in episode numbers (expected for a partial pack) | Yes |
| `missing_header_field` | No `EPISODE LOGLINE` or `CONTINUITY NOTES` | Yes, but the finalist review has less context |
| `missing_script_marker` | No `--- SCRIPT START` / `END` line | Yes |
| `unrecognised_line` | A line the format doesn't define | Check a few |
| `episode_number_mismatch` | Header and file name disagree (header used) | Check |
| `missing_episode_number` | No number in the header (file name used), or nowhere (file skipped) | Check |
| `invalid_scene_time`, `incomplete_scene`, `no_scenes`, `no_cues` | Scene problems | Check |
| `cue_before_scene_start`, `cue_after_scene_end`, `repeated_cue` | Timing oddities | Usually fine |
| `duplicate_episode`, `unusable_episode`, `ignored_non_txt_file`, `not_utf8` | Pack-level problems | Check |

Cues with a missing or invalid time can never become a hook or ending.

In the app, the data-quality report is saved in the run folder (`data_quality.json`); the page itself shows the **Processing summary** at the bottom. Use `run.py inspect` for a quick readable check.

### 4. Upload it in Streamlit

1. Start the app (section C).
2. In the sidebar, open **Run on a new screenplay pack**.
3. **Screenplay ZIP → Browse files**, choose the ZIP. The **Use the built in invented sample show** box unticks itself.

### 5. Run Basic mode

Under **Selection method** choose **Basic (no API key)** and click **Find promos**. It takes seconds. The new run opens as **Your latest run**.

### 6. Run AI mode

Choose **AI assisted**. You should see **An API key is configured** (if not, see section E). Choosing the mode starts nothing; models are called only when you click **Find promos**.

A progress bar shows `Finder: episode N`, then `Blind tests: ...`. Expect roughly a minute per episode. Only one AI run can go at a time on one app; a second gets a message, while Basic still works.

If the run stops early (for example a rate limit), the page says so and offers **Resume unfinished run** under the new-run section. It continues in the same folder and skips finished episodes, **in the same browser session only**.

### 7. Choose specific episodes (AI mode only)

Type in **Episodes to process**, for example `1-3` or `1,4,7` or `2-5,9`. Empty means every episode. Numbers not in the pack are refused with `Not in this pack: episode(s) [...]`. Basic mode always processes the whole pack.

**Ask the models again instead of reusing saved answers** ignores saved replies (costs more quota).

### 8. Inspect recommendations and transcripts

- **Top of results:** episodes processed, recommended clips, processing time, verification errors (should be 0).
- **Post this first** and the **Ranking** table (hidden in blind mode).
- **Clip details:** choose a clip, or use **◀ Previous clip** / **Next clip ▶**. You see why it could work, the hook and ending cues, the score breakdown, and what the blind viewer understood.
- **See the screenplay for this clip:** every cue in the clip with times, speaker, delivery note and text. For a new run this comes from its `transcripts.json`.
- **Downloads:** JSON, CSV, Report, Blank review sheet (hidden in blind mode).
- **Processing summary** (bottom): counts, gate failures, failed episodes, usage.

### 9. Save and reopen results

- **Locally (no Supabase):** each run is a folder in `prototype\outputs\`. After a refresh it appears in **Existing runs** as `Saved run: <folder name>`.
- **With Supabase (hosted app):** a **finished** run is uploaded automatically: you see **Saved to the app's database under your private link**. After a refresh it appears as `Saved run: <title> · Basic/AI assisted · <date> UTC · <id>`. If saving fails, the page says **NOT saved** and offers **Save these results again**.

The run folder holds: `promos.json`, `promos.csv`, `report.md`, `processing_summary.json`, `data_quality.json`, `top_twenty_human_review_sheet.csv`, `transcripts.json`, `checkpoint.json`, `episodes\`; AI runs also `run_config.json`, `evaluations\`, `rejected_candidates.json`, `model_issues.json`, `finalist_review.json`, `usage.jsonl`, `usage_summary.json`.

### 10. Submit human reviews

1. In the sidebar under **Human review**, type a **Reviewer name or ID**.
2. Optional: tick **Blind review mode** (hides AI rank, scores and explanations; lists clips in story order).
3. Pick a clip, read it (open **See the screenplay for this clip**), then rate **Hook quality**, **Cliffhanger quality**, **Clarity**, **Overall quality** (1–5) and **Would publish?** (Yes / No / Maybe), add optional comments, click **Save review**.
4. Saving the same clip again replaces your current review; the old one stays in the history.
5. With blind mode off, **Human review compared with AI** shows human and AI ratings side by side, with **Reviews CSV** and **Reviews JSON** exports. In blind mode, **My reviews (JSON)** downloads only your own reviews.

Reviews never change the run's files, the ranking or the models.

### Troubleshooting a new dataset

| Problem | What to do |
|---|---|
| `Could not read this pack. Not a valid ZIP file` | The file is not a real ZIP. Re-zip the `.txt` files. |
| `No screenplay .txt files found` | The ZIP has no `.txt` files (for example `.docx` or `.pdf`). Ask for text files. |
| `Files were found but none could be used as an episode` | No file has an episode number in its header or name. |
| `The ZIP holds N files` / `... bytes unpacked` | Over the pack limits. Split the pack. |
| Many `unrecognised_line` issues, few cues | The format differs from section D. Look at one file and compare with the example. |
| `missing_episodes` | A gap in numbering; processing continues. |
| A run shows 0 promos | Can be a correct answer: no pair fitted 20–60 s or passed the gates. See **Processing summary**. |
| AI run "stopped early" | Usually a rate limit. Use **Resume unfinished run**, or wait and run again. |
| Some episodes listed under "These episodes were not processed" | They failed (see the summary); resume or run again. |

---

## E. API keys and LLM configuration

### Where settings live

| Where | Used by | In Git? |
|---|---|---|
| `prototype\.env` | The local app **and** the command line (`run.py ai`, `check-provider`) | No (`.gitignore`) |
| `prototype\.streamlit\secrets.toml` (optional, local) | The local app only | No (`.gitignore`) |
| Streamlit Cloud → app → Settings → Secrets | The hosted app | No |

The app reads `.env` first, then Streamlit secrets, which **win**. The pipeline never reads keys from shell environment variables. Start from `.env.example` and `.streamlit/secrets.toml.example`:

```powershell
Copy-Item .env.example .env
notepad .env
```

### The settings (from `llm_client.load_model_config`)

Each setting is read as `FINDER_<NAME>` or `EVALUATOR_<NAME>` first, then the shared `LLM_<NAME>`:

| Name | Default | Meaning |
|---|---|---|
| `BASE_URL` | `https://api.groq.com/openai/v1` | Provider address (OpenAI-compatible) |
| `API_KEY` | — | The key |
| `MODEL` | — | Model name (required) |
| `TEMPERATURE` | `0` | Randomness |
| `SEED` | `7` | Fixed seed, if the provider supports it |
| `MAX_OUTPUT_TOKENS` | `2000` | Output room per reply (doubled once automatically if a reply is cut off) |
| `REQUESTS_PER_MINUTE` | `25` | The client paces itself under this |
| `TOKENS_PER_MINUTE` | `7000` | The client paces itself under this |
| `PRICE_INPUT_PER_MILLION`, `PRICE_OUTPUT_PER_MILLION` | — | Only for the cost estimate in `usage_summary.json` |

The current project uses Groq with finder `openai/gpt-oss-120b` and evaluator `qwen/qwen3.8-27b`.

### Change a model

Edit `.env` (local) or Secrets (hosted):

```
FINDER_MODEL=openai/gpt-oss-120b
EVALUATOR_MODEL=qwen/qwen3.8-27b
```

Locally, refresh the page (restart the app if unsure). For one command-line run only:

```powershell
python run.py ai --input sample_input\synthetic_show.zip --out outputs\ai_test --finder-model <model> --evaluator-model <model>
```

Changing a model makes the saved replies not match, so the models are asked again. Reusing the same `--out` folder with different models starts that folder's progress afresh.

### Different provider or key per role

```
FINDER_BASE_URL=https://api.groq.com/openai/v1
FINDER_API_KEY=<finder key>
FINDER_MODEL=<finder model>
EVALUATOR_BASE_URL=<another OpenAI-compatible address>
EVALUATOR_API_KEY=<evaluator key>
EVALUATOR_MODEL=<evaluator model>
```

The app's "An API key is configured" check accepts `LLM_API_KEY`, or both `FINDER_API_KEY` and `EVALUATOR_API_KEY`.

### Check that a key and models work

```powershell
python run.py check-provider
```

It asks each role's provider for its model list (no screenplay text is sent) and prints, per role, `provider=... model=... ok=True/False`. If the model is wrong, it lists models your key can use. It reads `.env` (or `--env <file>`), not `secrets.toml`.

### Never expose keys

- Never paste a key into chat, a commit message, a screenshot or a shared screen. Don't run `Get-Content .env` while screen sharing.
- Confirm Git ignores the files: `git check-ignore -v .env .streamlit/secrets.toml` should print a rule for each.
- Run `git status` before every commit. `.env` and `secrets.toml` must never appear.
- The client removes the key from error messages and logs (`redact`), but don't rely on that alone.
- If a key leaks: revoke it in the provider's console, create a new one, update `.env` / Secrets.

---

## F. Switching to Anthropic Claude Sonnet

### 1. What works with the CURRENT code

- Any **OpenAI-compatible** provider works by changing `BASE_URL`, `API_KEY` and `MODEL`: Groq, OpenAI, Gemini's OpenAI endpoint, Ollama locally, and others. Finder and evaluator can use different providers.
- **Claude is not supported.** Pointing `FINDER_BASE_URL` at Anthropic is not a working option: the client always sends `temperature` (0) and a `seed`, and Claude Sonnet 5.5 rejects a non-default temperature, so every call would fail. The client also reads the OpenAI reply shape (`choices[0].message.content`), which Claude's API does not use.

### 2. What would have to change (from the code audit)

All changes stay inside the client and its settings. **`pipeline.py`, the prompts, discovery, scoring, ranking and verification stay unchanged**, because they only use `LLMClient.chat_json`, which returns a dictionary.

1. **Dependency:** add the official `anthropic` package to `requirements.txt` (pinned).
2. **Provider setting:** a new `{ROLE}_PROVIDER` / `LLM_PROVIDER` read in `load_model_config` (`openai_compatible` by default, so Groq keeps working; `anthropic` new).
3. **Anthropic adapter in `llm_client.py`:** call `client.messages.create(...)` with the system text separately, the model `claude-sonnet-5-5`, **no temperature and no seed**, and the SDK's own retries set to 0 so the existing retry loop stays in charge.
4. **Response parsing:** Claude returns a list of content blocks (thinking blocks, then text). Join the `text` blocks only and pass them to the existing `extract_json`.
5. **Stop reasons:** `max_tokens` maps to today's "cut off" retry; `refusal` becomes a recorded, non-retried failure for that item.
6. **Usage mapping:** Claude's `input_tokens` / `output_tokens` instead of `prompt_tokens` / `completion_tokens`.
7. **Error mapping:** SDK errors to the existing kinds (`auth`, `model_not_found`, `rate_limit`, `server` including 529 overloaded, `network`, `bad_request`).
8. **Cache key:** add the provider type and any new setting (such as effort) to `settings_fingerprint`, so saved replies are never wrongly reused.
9. **Output room:** thinking counts against the output limit, so a Claude role needs a larger `MAX_OUTPUT_TOKENS` (for example 8,000–16,000).
10. **Small updates outside the client:** `hosting.has_api_key` (recognise Claude keys) and `run.py check-provider` (Claude's model lookup).
11. **Tests** with a fake Anthropic client (no network), and the existing Groq tests unchanged.

Also important: Claude is **paid per token** (the project's budget was ₹0), and sending a confidential screenplay to a new provider needs its data terms checked.

### FUTURE CONFIGURATION (does NOT work until Anthropic support is implemented)

```
# FUTURE - not supported by the current code
FINDER_PROVIDER=anthropic
FINDER_MODEL=claude-sonnet-5-5
FINDER_API_KEY=<anthropic key>
FINDER_MAX_OUTPUT_TOKENS=16000

EVALUATOR_PROVIDER=openai_compatible
EVALUATOR_BASE_URL=https://api.groq.com/openai/v1
EVALUATOR_API_KEY=<groq key>
EVALUATOR_MODEL=qwen/qwen3.8-27b
```

`FINDER_PROVIDER` / `EVALUATOR_PROVIDER` do not exist today; today the app would ignore them.

### If asked to implement it in an interview

1. Say the plan out loud: one adapter behind `LLMClient`, pipeline untouched, Groq stays the default.
2. Create a branch: `git switch -c anthropic-adapter`.
3. Add `anthropic` to `requirements.txt` and install it (`python -m pip install -r requirements.txt`).
4. In `llm_client.py`: add the provider field to `ModelConfig` and `load_model_config`; split the request part of `chat_json` into an OpenAI-compatible path (today's code) and an Anthropic path, both returning text, stop reason, input and output tokens; keep caching, pacing, retries, JSON parsing and the usage log shared.
5. Add the provider to `settings_fingerprint`.
6. Write tests with a fake Anthropic client; run `python -m pytest`.
7. Only then, with the interviewer's agreement, a small real test: one episode of the invented sample show (`--episodes 1`), which costs money.

---

## G. Supabase and persistence

### Turning it on

Supabase is used only when both `SUPABASE_URL` and `SUPABASE_SECRET_KEY` are set (Streamlit Secrets on the hosted app; optionally `.streamlit\secrets.toml` locally). Use a **secret** key (`sb_secret_...`), never the publishable one. Without them, everything works on local files.

**Migrations** that must have been run once in the Supabase SQL Editor (both only create things, never delete):
- `supabase/migrations/0001_reviews.sql`: table `reviews`, view `latest_reviews`, Row Level Security on with no policies.
- `supabase/migrations/0002_runs.sql`: table `runs`, private bucket `promo-data`.

Security: Row Level Security with no policies means the public key can do nothing. Only the app's server, with the secret key from Secrets, reaches the database. The key is never sent to the browser and is removed from error messages.

### The private owner link

- On first visit the app adds a random code to the address: `?k=...`. It survives a refresh; bookmarking the page brings your reviews and runs back on any device.
- The sidebar box **Open a saved link** accepts a full link or just the code.
- Only the code's SHA-256 hash is stored. **Anyone with the link can see and add to that link's reviews and runs**, like a shared document link.

### How reviews are saved

- Each save adds a new row to `reviews` with your name and your link's hash. The newest row per run, clip and link counts.
- Each visitor only ever loads their own reviews. You (the owner) see everyone's in the Supabase dashboard: Table Editor → `reviews` or `latest_reviews` → export CSV.
- If Supabase can't be reached, the review is kept on the app's disk (`pending_cloud_reviews.jsonl`) and sent on your next save or page load, never twice. The page warns you: a restart before then would lose it.

### How completed runs are saved

- When a run **finishes**, the app writes `transcripts.json`, uploads the files needed to show the run again (results, report, CSVs, excerpts, recommended clips' evaluations) to `promo-data/<link hash>/<run id>/`, and **then** adds a row to `runs`.
- A run that stopped early or had failures is **not** saved.
- If saving fails: **NOT saved to the database** plus a **Save these results again** button.

### Retrieving saved runs

After a refresh or restart, your runs appear in **Existing runs** below the bundled runs as `Saved run: ...`. Opening one after a restart downloads a copy into `outputs\cloud_runs\<run id>\`. Runs are listed and downloaded only for your link's hash; the app never takes a run ID from the address.

On a host with any Streamlit secrets, the run list also hides runs other visitors made in their sessions (shared-host behaviour).

### When Supabase is unavailable

- The pipeline never depends on Supabase; runs still finish locally.
- Reviews queue locally as above.
- The run list shows **Your saved runs could not be loaded right now**; the bundled runs still open.
- A free Supabase project **pauses after a week without activity**; restore it in the dashboard.

### NOT implemented

- Resuming an interrupted run after a restart (Resume works only within the same browser session).
- Saving unfinished runs.
- Automatic backups (the free tier has none): export the tables yourself.
- Quotas, storage monitoring, automatic clean-up of saved runs.
- Real user accounts (the private link is the only identity).
- Claude / Anthropic support (section F).

### Checking Supabase connectivity

- **Hosted app:** the sidebar shows the private-link text and **Open a saved link**, and under Human review the caption says reviews are stored in **this app's Supabase database**. Save a review, refresh, and check it is still there and in the Table Editor.
- **Locally:** create `.streamlit\secrets.toml` with the two settings (see `.streamlit\secrets.toml.example`), start the app and check the same captions. A database problem shows as a warning in the sidebar or under Human review. Note: with any secrets present, the app behaves as a shared host (section C).

---

## H. Common interview tasks and troubleshooting

### Small Basic test (no key, a few seconds)

In the app: **Run on a new screenplay pack** → keep **Use the built in invented sample show** → **Basic** → **Find promos**. Expect `3 of 3` episodes and `0` verification errors.

Command line:

```powershell
python run.py basic --input sample_input\synthetic_show.zip --out outputs\basic_test
```

### Small AI test (uses quota)

App: same as above with **AI assisted** and Episodes to process `1`.

Command line:

```powershell
python run.py ai --input sample_input\synthetic_show.zip --out outputs\ai_test --episodes 1
```

If it stops, run the **same command again**: it continues from the checkpoint.

### Change a model

Edit `FINDER_MODEL` / `EVALUATOR_MODEL` in `.env`, then `python run.py check-provider`, then a small AI test.

### Authentication errors

`The provider rejected the API key (HTTP 401)` or `NOT READY. No API key`:
1. `python run.py check-provider`.
2. Check `.env` has `LLM_API_KEY=` (or both role keys), with no quotes or spaces around the key.
3. Hosted app: check Streamlit Cloud → Settings → Secrets, then reboot the app.
4. If needed, create a new key in the provider console.

### Rate limits

- Short waits are handled automatically (the client waits and retries).
- `Rate limit reached, provider asked to wait ...s` means a long or daily limit: the run stops with `stopped_because` and keeps its progress. Wait, then **Resume unfinished run** (same session) or rerun the same CLI command.
- Lower `LLM_REQUESTS_PER_MINUTE` / `LLM_TOKENS_PER_MINUTE` in `.env` to pace more gently.

### Missing Python packages

```powershell
(Get-Command python).Source
python -m pip install -r requirements.txt
```

The first line should point into `.venv`; if not, activate it (section B).

### ZIP parsing problems

```powershell
python run.py inspect --input "D:\path\to\pack.zip" --out "D:\path\to\inspect_out"
```

Then read `inspect_out\data_quality.json` and compare one episode file with the format in section D.

### Run the automated tests

```powershell
python -m pytest
```

About 300 tests, about a minute; they use no network. One file: `python -m pytest tests\test_parser.py`. One test by name: `python -m pytest -k "resume"`.

### Check confidentiality before publishing anything

```powershell
python tools\check_confidentiality.py --pack "D:\path\to\pack.zip" --check .
```

The bundled demo runs quote the real show on purpose, so the scan reports them.

### Git: check status and commit safely

The repository is the `prototype` folder. The working branch is `windows-audit`, which tracks GitHub's `main`.

```powershell
git status
git diff
git add <file1> <file2>
git commit -m "Short description of the change"
```

- Add files by name; avoid `git add .` so nothing private slips in.
- Check `git status` shows no `.env`, `secrets.toml`, `outputs\` or ZIPs.
- Pushing redeploys the live app: `git push origin windows-audit:main`. Only push when you mean to.

---

## I. Interview cheat sheet

**Open and run**

```powershell
cd "D:\0 Kuku FM\KUKU FM\prototype"
.venv\Scripts\Activate.ps1
python -m streamlit run app.py --server.address localhost
```

Open `http://localhost:8501` · stop with **Ctrl+C** · port busy: add `--server.port 8502`.

**Commands**

| Task | Command |
|---|---|
| Inspect a pack | `python run.py inspect --input pack.zip` |
| Basic run | `python run.py basic --input pack.zip --out outputs\basic_x` |
| AI run (some episodes) | `python run.py ai --input pack.zip --out outputs\ai_x --episodes 1-3` |
| Check key and models | `python run.py check-provider` |
| All commands | `python run.py --help` |
| Tests | `python -m pytest` |
| Git state | `git status` |

**New dataset in the app:** sidebar → **Run on a new screenplay pack** → upload ZIP → Basic or AI (episodes `1-3`) → **Find promos** → clip details → **See the screenplay for this clip** → Human review.

**Switch a model:** edit `FINDER_MODEL` / `EVALUATOR_MODEL` in `.env` (hosted: Secrets) → `python run.py check-provider`.

**Important files:** `app.py`, `run.py`, `promo_finder\pipeline.py`, `parser.py`, `ai_mode.py`, `basic_mode.py`, `boundaries.py`, `ranking.py`, `schema.py`, `llm_client.py`, `prompts.py`, `stores.py`, `cloud.py`, `.env`, `supabase\migrations\`.

**Environment variables:** `LLM_BASE_URL`, `LLM_API_KEY`, `FINDER_MODEL`, `EVALUATOR_MODEL`, `FINDER_*` / `EVALUATOR_*` overrides, `LLM_REQUESTS_PER_MINUTE`, `LLM_TOKENS_PER_MINUTE`, `LLM_MAX_OUTPUT_TOKENS`, `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `PROMO_OUTPUT_DIR`, `PROMO_PACK_DIR`.

**Architecture in 60 seconds:**

> "Promo Finder takes a ZIP of screenplay episodes and recommends 20 to 60 second promo clips. The parser turns each episode into timed cues with permanent IDs, and records every data problem. In AI mode, a finder model reads an episode and only points at cue IDs for hooks and endings; it never sees or invents a timestamp. Python builds the clips from the screenplay's own times, enforcing 20 to 60 seconds and a hook in the first three seconds. A second model judges each clip blind: a hook test on the first three seconds, and a cold-viewer test with names masked. Only clips that pass every gate are ranked, with spoiler and variety penalties, and every time and quote is verified against the screenplay before output. Basic mode does the same without any model, using text signals. The Streamlit app shows the results with each clip's screenplay, collects human reviews, and on the hosted version saves reviews and finished runs to Supabase under a private link."
