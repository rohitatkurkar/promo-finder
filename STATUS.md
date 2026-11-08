# Project status and roadmap

The one master status document. Update this file instead of starting new lists.

Last updated: 2026-11-08, after preparing the interface for Streamlit Community Cloud (branch `windows-audit`).

Decisions so far: provider is the **Groq free plan** (finder `openai/gpt-oss-120b`, evaluator `qwen/qwen3.8-27b`), with **Cloudflare Workers AI free** as a possible fallback. Budget is ₹0: no paid APIs, no payment method on any account. No key is configured and no screenplay text has been sent anywhere yet.

Labels: **Done and tested** · **Implemented but unverified** · **Experiment** · **Blocked** · **Not being built**

## 1. Where things are

| Path (from the outer project folder) | What it is | In Git? |
|---|---|---|
| `prototype/` | The foundation codebase. Own Git repo. Remote `origin` is `github.com/rohitatkurkar/promo-finder`. The first commit (`5485814`) was published earlier at `github.com/iteshm23/promo-finder`, kept as remote `iteshm23-original` | yes |
| `prototype/promo_finder/` | Package: `parser`, `boundaries`, `signals`, `basic_mode`, `ai_mode`, `prompts`, `masking`, `llm_client`, `ranking`, `schema`, `outputs`, `evaluation`, `worksheets`, `pipeline` | yes |
| `prototype/run.py` | Command line entry point | yes |
| `prototype/app.py` | Streamlit interface | yes |
| `prototype/tests/` | 10 test files | yes |
| `prototype/.venv/` | New Windows environment, Python 3.14.0 | ignored |
| `prototype/.venv-macos-original/` | The old macOS environment (Python 3.13.9, Anaconda, 415 MB), renamed and kept. Unusable on Windows. Safe to delete once no longer wanted | ignored |
| `inputs/` | The real 50 episode screenplay ZIP and the assignment PDF | outside the repo |
| `private/runs/basic_final`, `basic_final_repeat` | Archived Basic baseline. Untouched | outside the repo |
| `private/runs/earlier_versions/` | Basic v1 and v2 runs. Untouched | outside the repo |
| `private/runs/basic_windows_py314_2026-11-08` (+ `_repeat`) | New Windows reproduction runs | outside the repo |
| `private/runs/basic_windows_py311_2026-11-08` (+ `_repeat`) | New runs on Python 3.11, kept as evidence of the 0.01 score drift | outside the repo |
| `private/evaluation/`, `private/worksheets/`, `private/ai_prepared_reference/` | Earlier evaluation material. The reference set is AI prepared, not human | outside the repo |
| `submission/` | `Solution.pdf`, `prototype.zip`, `raw_outputs.zip`. Untouched | outside the repo |

There is no `.env` file, so no API key is configured.

## 2. Windows audit, 2026-11-08

### Environment
- **Done and tested.** New `.venv` on Python 3.14.0 from `requirements.txt` with no upgrades beyond its ranges. Exact versions in `requirements-lock-windows.txt` (45 packages).
- Python version choice: the README asks for 3.11 or newer, and the macOS environment was 3.13.9. Python 3.13 is not installed here. Python 3.11 runs all tests but changes two Basic scores by 0.01, because Python 3.12 changed how `sum()` adds decimals. Python 3.14 reproduces the archive exactly, so it is the project environment.
- `llama-cpp-python` and other native model packages: not used anywhere in this prototype. Only `pyarrow`, `numpy` and `pandas` (through Streamlit) have native parts, and all installed as ready made Windows wheels.

### Tests
- **Done and tested.** `.venv\Scripts\python.exe -m pytest`: **186 passed, 0 failed, 0 skipped, 0 warnings** in about 14 seconds after the audit. That is the original 185 plus 1 new regression test. After the outline fix (section 4a): **190 passed, 0 failed, 0 skipped.** After human review (section 4c): **211 passed, 0 failed, 0 skipped.** Before any change, the original 185 also all passed on Windows (Python 3.11.7, first environment tried).

### Basic baseline
- **Done and tested.** `run.py basic` on the real pack, twice, on Python 3.14:
  - 50 of 50 episodes, 3,727 cues (1,754 camera, 1,487 dialogue, 372 action, 114 sound), 0 cues without valid times, 21 data notes.
  - 9,382 pairs tried, 2,074 valid clips, 19 recommended, 0 verification errors, clips 21.8 to 60.0 seconds.
  - Byte identical to the archive: `promos.json`, `promos.csv`, `data_quality.json`, `top_twenty_human_review_sheet.csv`, all 50 `episodes/E*.json`.
  - Different only in processing time: `report.md`, `processing_summary.json`, `checkpoint.json` say 2.4 to 2.5 seconds here, 1.1 in the archive.
  - The two Windows runs are byte identical to each other.
- Note: `report.md` contains the processing time, so the archive's "byte identical repeat" for that file depended on both runs rounding to the same tenth of a second.

### Windows problems found and fixed
| Problem | Effect | Fix | Test |
|---|---|---|---|
| `Path.write_text` and `open("a")` write CRLF on Windows | JSON, Markdown, usage logs and model cache files differed from macOS on every line | `newline="\n"` on all 7 text writes in `outputs.py`, `evaluation.py`, `worksheets.py`, `llm_client.py` | New `test_text_outputs_use_lf_line_endings_on_every_platform`, failed before the fix |
| Folder input recorded file names with `\` | `data_quality.json` would differ by platform | `as_posix()` in `parser.load_pack` | Assertion added to `test_folder_input_works` |
| 10 test reads used the Windows default encoding (cp1252) | Would fail on any non ASCII output | `encoding="utf-8"` | Existing tests |
| Git `core.autocrlf=true` (Windows default) converts LF files to CRLF | Seen during the audit: 4 source files flipped to CRLF | New `.gitattributes`: LF for text, binary for ZIP and PDF | Checked: no CRLF in any source file |
| `tools/build_submission.py` and `tools/check_confidentiality.py` skipped only `.venv` | Would pack or scan the 415 MB `.venv-macos-original` | Skip any folder starting with `.venv`; the ZIP also skips `venv` and `llm_cache` | Test ZIP built to a temporary folder: 44 files, 129 KB, no environment files. Scan of `.` is clean |
| `.gitignore` gaps | Other `.env` files, model caches, model weights, renamed environments and OS clutter could be committed | Added `.env.*` (keeping `.env.example`), `.venv-*/`, `venv/`, `llm_cache/`, `*.gguf`, `._*`, `__MACOSX/`, `Thumbs.db`, `desktop.ini` | `git check-ignore` |

Also checked with no problem found: the screenplay ZIP holds 50 `.txt` files and no macOS metadata, all LF and UTF-8; the parser already skips `__MACOSX/` and dot files; no `.DS_Store` or `._*` files exist outside the old environment; no `subprocess`, `os.system` or shell calls in the package; all production reads give an explicit encoding; the project path contains spaces and everything works from it.

Streamlit: **Done and tested** on Windows. Started live, ran Basic on the sample show, and AI mode without a key showed "No model set for the finder role" and sent nothing. Downloads and file upload were not clicked.

### Not fixed, outside the repo (private, would overwrite archived files)
- `private/rebuild_submission.sh` is bash and calls `.venv/bin/python` (the macOS layout; Windows uses `.venv\Scripts\python.exe`). It rewrites `submission/`. Not run, not changed.
- `private/final_verification.py` reads JSON and CSV without an encoding (fails on Windows when text is not ASCII) and rewrites `private/FINAL_VERIFICATION.md`. Not run, not changed.
- `private/ai_prepared_reference/build_ai_reference.py` writes without an encoding.
- Duplicate copies of the screenplay ZIP and assignment PDF in the outer folder and in `inputs/` are identical by SHA-256. Left in place.

## 3. Commands (Windows, from `prototype\`)

```powershell
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe run.py basic --input "..\inputs\<pack>.zip" --out "..\private\runs\<new_name>"
Copy-Item .env.example .env        # then add the key in an editor, never in chat
.venv\Scripts\python.exe run.py check-provider
.venv\Scripts\python.exe run.py ai --input "..\inputs\<pack>.zip" --out "..\private\runs\<new_name>" --episodes 1 --cache-dir "..\private\runs\<new_name>\llm_cache"
.venv\Scripts\python.exe -m streamlit run app.py
```

Each command was taken from `run.py` and the README. Only `pytest`, `basic` and Streamlit have been run.

## 4. AI assisted mode

**Implemented but unverified.** No real model has ever run it.

How it works (read from the code):
1. **Finder** (one call per episode): sees the episode summary and every dialogue and action cue as `cue id | type | speaker | text`, with no times. Returns up to 5 hook and 5 ending cue IDs with a strength from 1 to 5.
2. **Python** checks every ID and quote, rejects invented times, pairs every hook with every ending through `build_clip`, and keeps up to 3 different clips per episode.
3. **Blind hook test**: the first 3 seconds, with names masked. A rating below 4 stops here.
4. **Blind cold viewer test**: the whole clip, masked. It must rate the ending 4 or more, not settle the conflict, and quote real lines.
5. **Finalist review**: spoiler risk, premise fit and ad risk, using the story outline.
6. Ranking, duplicate removal, the same verification against the screenplay as Basic.

One `LLMClient` speaks the OpenAI compatible chat API. Provider, model and key come from `.env` only. It has retries, rate pacing, a cache, a usage log with no prompt text, cost from listed prices, and resume after a stop.

Before the first real run, the user should know:
- **Blocked:** no `.env` and no key. The default models in `.env.example` (Groq, `openai/gpt-oss-120b` finder, `qwen/qwen3.8-27b` evaluator) have not been checked against the provider's current list or data terms.
- ~~A one episode run still sends all 50 episode loglines to the provider.~~ Fixed, see section 4a.
- Structured output is plain JSON mode (`response_format: json_object`). Valid cue IDs are not enforced by the provider; Python rejects bad ones afterwards.
- Raw replies are kept only in the cache, and only when they parsed. A reply that was not valid JSON is not saved anywhere. The cache defaults to `llm_cache` beside the run folder and is shared across runs, so pass `--cache-dir` inside the run folder to keep one run's replies together.
- The cache key ignores the API key and base URL path, but includes provider host, model, temperature, seed and output limit.
- The gates are strict: both hook and ending must be rated 4 of 5. On a weak or cautious model, few or no clips may pass.

## 4a. Finalist outline privacy fix (2026-11-08)

**Done and tested** (stand-in provider only, no real model).

- **Problem:** the finalist review always received all 50 episode summaries, even for a one episode trial, because `pipeline.py` built the outline from the whole pack.
- **Change:** `prompts.build_outline(episodes, up_to_episode)` now includes only Episode 1 up to `up_to_episode`. `ai_mode.review_finalists` builds it separately for each batch of up to 8 clips, up to the latest episode among that batch's clips. When later episodes are left out, the outline ends with a note saying it stops there and the story continues, so the reviewer does not read the last summary shown as the ending. `FINALIST_VERSION` is now `finalist_v2`, so run settings and caches record the change.
- **Effect:** an Episode 1 trial sends 1 summary instead of 50. A batch whose latest clip is from Episode N sends N summaries. A full 50 episode run still sends most summaries, because a batch reviewing late clips needs the story up to that point.
- **Trade-off:** the reviewer can no longer see a turn that later episodes reverse or pay off, so it cannot judge, for example, "this looks like a big reveal but is undone in Episode 40". A clip only contains events up to its own episode, so judging what it gives away about the story so far, and premise fit, is unaffected.
- **Wording not changed:** `FINALIST_SYSTEM` still says the reviewer knows "the full story outline". The closing note in the outline corrects this. Rewording the prompt was not approved, so it stays.
- **Tests:** 4 new tests in `tests/test_ai_pipeline.py`. They cover the outline function, an Episode 1 trial (only E1 sent), a later episode trial (Episode 2: E1 and E2 sent, E3 not), and separate batches (batch [E1, E3] gets E1 to E3, batch [E2] gets E1 and E2). All 4 failed before the change and pass after it.
- **Other stages unchanged, checked:** on the sample show with the stand-in provider, every finder, hook test and cold viewer request was byte identical before and after, and so were the final promos. The full run's finalist request was also identical, because its batch reached the last episode. Basic mode on the real pack is still byte identical to the archive (`promos.json`, `promos.csv`, `data_quality.json`).

## 4b. First real AI trial: Episode 1 on Groq (2026-11-08)

**Experiment.** Episode 1 only, with finder `openai/gpt-oss-120b` and evaluator `qwen/qwen3.8-27b`, on the free plan with Zero Data Retention on. Results are in `private/runs/ai_trial_E01_groq_2026-11-08/`, with a human review pack in `E01_HUMAN_REVIEW.md` there.

- 7 calls, no retries or failures, 8,828 tokens, about 10 seconds. Cost ₹0.
- 3 candidates; 2 passed every gate (P0001, P0002); 1 failed the hook test (3 of 5). 0 verification errors.
- Problems seen:
  - the finder never offered the episode's last 20 seconds as an ending;
  - the finder used its whole 2,000 token output budget;
  - every passing rating sat exactly at the 4 of 5 bar, so the ratings barely separate clips;
  - P0001 and P0002 share 18.9 seconds;
  - P0001 counts as a duplicate of Basic's Episode 1 pick under the system's own rule.
- Not yet reviewed by a person.

## 4c. Human review in the interface (2026-11-08)

**Done and tested** (automated tests, plus a check by hand in the running app on the invented sample show).

- **New `promo_finder/reviews.py`:**
  - Reviews are saved to `<runs folder>/human_reviews/human_reviews.jsonl`, one line per saved review, never edited. History is kept.
  - Each review is keyed by run folder name and `clip_key`. `promo_id` is kept for reading but follows rank, so it is not a stable key.
  - The latest review per run, clip and reviewer counts. Reviewer names ignore case and surrounding spaces.
  - A fingerprint of `promos.json` is saved with each review, so a run regenerated after review is flagged.
  - Ratings must be whole numbers 1 to 5, and the verdict must be yes, no or maybe. A damaged line is skipped and reported.
  - CSV and JSON exports join each review with the AI's rank, score and ratings.
- **`app.py`:**
  - a reviewer name box in the sidebar;
  - a Human review form under Clip details, filled in with your last answers;
  - a "Human review compared with AI" table and the export buttons;
  - blind review mode, which hides the rank, scores, ratings, explanations, first post choice and the run's files, and lists clips in story order with no promo IDs;
  - the transcript now has end times and delivery notes;
  - `PROMO_PACK_DIR` lets the app find a run's pack without uploading it again.
- **Not changed:** discovery, evaluation, ranking, prompts, the schema, and every run file. No API calls. `human_reviews/` is ignored by Git.
- **Tests:** 21 new. 17 in `tests/test_reviews.py`: save and reload, history, several reviewers, runs kept apart, 7 kinds of invalid input, damaged lines, run files byte identical after reviewing, rank order and AI figures, AI ratings read from an AI run, CSV and JSON exports, regenerated run flagged. 4 in `tests/test_app.py`: saving in the app with `promos.json` unchanged, missing answers refused, no form without a reviewer name, blind mode hiding the AI's judgement and files.
- **Checked by hand:** a review was saved in the running app, the stored line was correct, `promos.json` kept the same fingerprint, the comparison table and blind mode displayed correctly, and the test review was then removed.
- **Not yet built:** reviewing rejected candidates, which is needed to measure what the tool misses rather than only what it picks badly. Summaries of human ratings across runs.

Also noticed: on 2026-11-08 at 21:53 an AI run was started from the interface on the invented sample show (`outputs/ai_20261108_215309`). It made 13 calls (about 13,550 tokens) and stopped after the blind tests, with no promos written. No real screenplay was involved. It was left as it is.

## 4d. Ready for Streamlit Community Cloud (2026-11-08)

**Done and tested locally. Not yet deployed.**

- **Settings:** the interface reads AI settings from `.env` and then from Streamlit secrets, which win. `run_ai_pipeline` gained an optional `env_values` argument for this. Without it, the pipeline reads `.env` exactly as before. Discovery, evaluation, scoring and ranking are unchanged.
- **AI access control** (new `promo_finder/hosting.py`):
  - If `AI_ACCESS_PASSWORD` is set, AI mode needs it. The comparison is constant time.
  - If the key comes from secrets but no password is set, AI mode stays off.
  - A local `.env` with no password works as before.
  - Password-protected runs may process at most `AI_MAX_EPISODES` episodes (default 3), chosen in a new "Episodes to process" box.
- **Demo:** `demo_runs/basic_sample_show` is Basic mode on the invented sample show. It opens at once and is labelled as a precomputed demo.
- **Reviews:** now stored under the main runs folder for every run, including the demo. The page says hosted storage is temporary. Blind mode offers a review download with no AI figures and no promo IDs.
- **Config:**
  - `.streamlit/config.toml` no longer fixes `server.address`, so the host can serve the app. Local runs use `--server.address localhost`, as the README now says.
  - Added `.streamlit/secrets.toml.example` and an optional password note in `.env.example`.
  - The upload caption no longer claims files stay on this machine.
- **Tests:** 235 passed (24 new: 19 in `tests/test_hosting.py`, 5 in `tests/test_app.py`). The app tests point `PROMO_ENV_FILE` at a missing file, so they never read the real key or call a provider.
- **Fresh copy check:** the 60 files to publish were copied to a clean folder with no `.env`, and installed from `requirements.txt` into a new Python 3.11 environment. All 235 tests passed there, the app started, showed the demo and ran Basic mode.
- **Scans:** no keys in the publishable files or in the whole Git history, except the deliberately fake test key in `tests/test_llm_client.py`. No private paths ever committed. The confidentiality scan is clean.

## 5. Two segment promos

Existing pieces (`schema.py`):
- `Segment`: episode, start and end seconds and timestamps, start and end cue IDs, boundary adjustments. It checks its own times.
- `Promo.segments` holds 1 or 2 segments. A probe confirmed it rejects reversed or overlapping segments, segments from different episodes, and three segments. It checks the combined 20 to 60 seconds, with no minimum per segment.
- `verify_promo_against_screenplay` checks every segment's start and end cues against the screenplay.

Missing:
- No source hash or list of cue IDs per segment.
- Nothing checks that the hook cue opens segment 1 or that the cliffhanger cue sits in the last segment. A probe built a two segment promo with the cliffhanger in segment 1, and it passed both checks. `within_first_three_seconds` is a flag the caller sets, not something the schema works out.
- `boundaries.Clip` is one continuous range, and everything built on it assumes so: `build_clip`, Basic candidates, the finder pairing, masking (`blind_clip`), finalist review, duplicate checks (`are_duplicates`, time overlap), checkpoint files and `Clip.key`.
- Code that reads only `segments[0]`: `outputs.py` (CSV columns, report, first post choice), `app.py` (lines 146 to 173), `evaluation.promo_range`, `run.py judge-basic`, `pipeline.py` (episodes with no recommendation).
- No test builds a two segment promo.

**Not being built yet**, until the one episode AI trial is reviewed.

## 6. Where the handoff and the source disagree

- The handoff says 185 tests pass. True on Windows too. It is now 186 with the new test.
- The macOS environment had pandas 3.1.1, but `requirements.txt` allows only pandas below 3. The archived run did not match its own requirements file. The new environment follows the file (pandas 2.3.3). Basic mode does not use pandas, and the interface works.
- "Python 3.11 or newer" in the README is true for running the code, not for reproducing results. See section 2.
- Earlier notes mention a "Clean install on Python 3.11: 185 tests passed". Tests pass on 3.11, but output is not identical there.
- "Provider abstraction" is one OpenAI compatible client, not one adapter per provider. That is a design choice; it works only with providers that offer that API.
- The handoff says Basic took about 1.1 seconds. That is the archived figure. On this machine it takes 2.4 to 2.5 seconds.
- Every other figure in the handoff was confirmed from the files.

## 7. Next step

Human review of the Episode 1 trial, in the interface or with `E01_HUMAN_REVIEW.md`. Its findings decide the first changes to discovery or prompts. No further episodes are run until then.

## 8. Later (agreed scope, not started)

In order, each only after the step before it is reviewed: small AI batch and comparison with Basic → 10 episode pilot with independent human picks → two segment promos → human feedback in the interface → final evaluation report. Not being built: embeddings, fine tuning, more agents, Qwen 1.5B as judge, PromoScout's discovery engine, video work, promos across episodes, three segments.
