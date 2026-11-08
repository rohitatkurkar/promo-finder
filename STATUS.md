# Project status and roadmap

The one master status document. Update this file instead of starting new lists.

Last updated: 2026-11-08, after the Windows audit (branch `windows-audit`, not yet committed).

Labels: **Done and tested** · **Implemented but unverified** · **Experiment** · **Blocked** · **Not being built**

## 1. Where things are

| Path (from the outer project folder) | What it is | In Git? |
|---|---|---|
| `prototype/` | The foundation codebase. Own Git repo, remote `github.com/iteshm23/promo-finder`, one commit `5485814` on `main` | yes |
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
- **Done and tested.** `.venv\Scripts\python.exe -m pytest`: **186 passed, 0 failed, 0 skipped, 0 warnings** in about 14 seconds. That is the original 185 plus 1 new regression test. Before any change, the original 185 also all passed on Windows (Python 3.11.7, first environment tried).

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
- A one episode run still sends **all 50 episode loglines** to the provider, because the finalist review's outline uses the whole pack (`pipeline.py`, `build_outline(episodes)`).
- Structured output is plain JSON mode (`response_format: json_object`). Valid cue IDs are not enforced by the provider; Python rejects bad ones afterwards.
- Raw replies are kept only in the cache, and only when they parsed. A reply that was not valid JSON is not saved anywhere. The cache defaults to `llm_cache` beside the run folder and is shared across runs, so pass `--cache-dir` inside the run folder to keep one run's replies together.
- The cache key ignores the API key and base URL path, but includes provider host, model, temperature, seed and output limit.
- The gates are strict: both hook and ending must be rated 4 of 5. On a weak or cautious model, few or no clips may pass.

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

Awaiting approval: choose and check a provider (data terms, model availability, JSON mode), create `.env` locally, run `check-provider`, then run AI mode on one episode only, into a new run folder with its own cache.

## 8. Later (agreed scope, not started)

In order, each only after the step before it is reviewed: small AI batch and comparison with Basic → 10 episode pilot with independent human picks → two segment promos → human feedback in the interface → final evaluation report. Not being built: embeddings, fine tuning, more agents, Qwen 1.5B as judge, PromoScout's discovery engine, video work, promos across episodes, three segments.
