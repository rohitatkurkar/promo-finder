"""A simple interface for the promo finder. Start it with: streamlit run app.py"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from dotenv import dotenv_values
from pydantic import ValidationError

from promo_finder.boundaries import cues_in_range
from promo_finder.hosting import has_api_key, max_episodes, merge_settings, parse_episode_selection
from promo_finder.llm_client import LLMError
from promo_finder.parser import ACTION, CAMERA, DIALOGUE, ScreenplayPackError, format_timestamp, load_pack
from promo_finder.pipeline import DEFAULT_ENV, pack_title, run_ai_pipeline, run_basic_pipeline
from promo_finder.uploads import new_run_dir, store_upload
from promo_finder.reviews import (
    append_review,
    comparison_rows,
    load_reviews,
    latest_reviews,
    new_review,
    review_by,
    review_store_path,
    reviews_of,
    rows_to_csv,
    rows_to_json,
    step_clip,
)

ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = Path(os.environ.get("PROMO_OUTPUT_DIR", ROOT / "outputs"))
# Optional: a folder holding the screenplay packs, so a run's transcript can be shown without uploading the pack again.
PACK_DIR = os.environ.get("PROMO_PACK_DIR")
# The local settings file. Tests point this elsewhere so they never read a real key.
ENV_FILE = Path(os.environ.get("PROMO_ENV_FILE", DEFAULT_ENV))
# Precomputed results on the invented sample show, shipped with the app so it has something to show at once.
DEMO_ROOT = ROOT / "demo_runs"
YOUR_LATEST_RUN = "Your latest run"
# Optional settings for a local review session. All are off unless set in the shell before starting.
BLIND_BY_DEFAULT = os.environ.get("PROMO_BLIND_REVIEW_DEFAULT", "").strip().lower() in ("1", "true", "yes")
REVIEW_SET_FILE = os.environ.get("PROMO_REVIEW_SET")  # JSON with "run_id" and "clip_keys": the clips to review.
DEFAULT_RUN = os.environ.get("PROMO_DEFAULT_RUN")  # A run folder to open first instead of the bundled default.
SAMPLE = ROOT / "sample_input" / "synthetic_show.zip"
KIND_ICON = {DIALOGUE: "Line", ACTION: "Action", CAMERA: "Shot"}
# A bundled run may hold the screenplay cues of its own clips (made by tools/build_transcript_excerpts.py), not the whole pack.
EXCERPTS_FILE = "transcripts.json"
RATING_FIELDS = [
    ("hook_quality", "Hook quality"),
    ("cliffhanger_quality", "Cliffhanger quality"),
    ("clarity", "Clarity"),
    ("overall_quality", "Overall quality"),
]
VERDICTS = {"Yes": "yes", "No": "no", "Maybe": "maybe"}

st.set_page_config(page_title="Promo Finder", layout="wide")
st.title("Promo Finder")
st.caption("Reads a microdrama screenplay and recommends 20 to 60 second promo clips. All times come from the screenplay's own cues.")


def load_settings() -> tuple[dict, bool]:
    """AI settings from the local .env file, then Streamlit secrets. Returns (settings, key came from secrets)."""
    local = dotenv_values(ENV_FILE) if ENV_FILE.exists() else {}
    try:
        secrets = {name: st.secrets[name] for name in st.secrets}
    except Exception:  # No secrets configured, which is normal when running locally.
        secrets = {}
    return merge_settings(local, secrets), has_api_key(merge_settings({}, secrets))


def demo_catalog() -> dict:
    """Labels, order and default for the runs bundled in demo_runs/. Folders not listed still appear, after the listed ones."""
    path = DEMO_ROOT / "catalog.json"
    catalog = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    entries = {entry["folder"]: entry for entry in catalog.get("runs", [])}
    return {"default": catalog.get("default"), "entries": entries, "order": [entry["folder"] for entry in catalog.get("runs", [])]}


def shared_host() -> bool:
    """True on a hosted app, where every visitor shares one disk. Streamlit secrets mark it, as they exist only there;
    PROMO_SHARED_HOST=1 or 0 overrides."""
    override = os.environ.get("PROMO_SHARED_HOST", "").strip()
    if override in ("0", "1"):
        return override == "1"
    try:
        return len(st.secrets) > 0
    except Exception:  # No secrets file: a computer of its own.
        return False


def existing_runs(only: set[str] | None = None) -> list[tuple[str, Path]]:
    """The bundled demo runs in catalog order, then runs saved on this computer, newest first. Returns (label, folder).

    With `only`, saved runs are limited to those folder names: on a shared host, a visitor sees only their own runs.
    """
    found: list[tuple[str, Path]] = []
    if DEMO_ROOT.exists():
        catalog = demo_catalog()
        folders = [p for p in DEMO_ROOT.iterdir() if (p / "promos.json").exists()]
        rank = {name: position for position, name in enumerate(catalog["order"])}
        for p in sorted(folders, key=lambda p: (rank.get(p.name, len(rank)), p.name)):
            found.append((catalog["entries"].get(p.name, {}).get("label") or f"{p.name} (demo)", p))
    if OUTPUT_ROOT.exists():
        mine = sorted((p for p in OUTPUT_ROOT.iterdir() if (p / "promos.json").exists() and (only is None or p.name in only)),
                      key=lambda p: p.stat().st_mtime, reverse=True)
        found += [(f"{'Your run' if only is not None else 'Saved run'}: {p.name}", p) for p in mine]
    return found


@st.cache_resource(show_spinner=False)
def cached_pack(path: str, modified: float):
    """Parse a pack once per file version, so moving between clips stays quick."""
    episodes, _ = load_pack(path)
    return {episode.number: episode for episode in episodes}


@st.cache_data(show_spinner=False)
def load_excerpts(path: str, modified: float, run_id: str) -> dict:
    """Clip key to that clip's screenplay cues, from a run's transcripts.json. Empty if the file belongs to another run."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data.get("clips", {}) if data.get("run_id") == run_id else {}


def transcript_table(cues: list[dict]) -> pd.DataFrame:
    rows = [{
        "Cue": cue["cue_id"], "Start": format_timestamp(cue["start"]), "End": format_timestamp(cue["end"]),
        "Type": KIND_ICON.get(cue["kind"], str(cue["kind"]).title()), "Speaker": cue["speaker"] or "",
        "Delivery": cue["delivery"] or "", "Text": cue["text"],
    } for cue in cues]
    return pd.DataFrame(rows).set_index("Cue")


def start_new_run() -> None:
    st.session_state["run_requested"] = True


def resume_run() -> None:
    st.session_state["resume_requested"] = True


def load_review_set(run_id: str) -> list[str] | None:
    """The clip_keys of the review set for this run, if PROMO_REVIEW_SET names one. Otherwise None."""
    if not REVIEW_SET_FILE or not Path(REVIEW_SET_FILE).is_file():
        return None
    data = json.loads(Path(REVIEW_SET_FILE).read_text(encoding="utf-8"))
    keys = data.get("clip_keys")
    return list(keys) if data.get("run_id") == run_id and isinstance(keys, list) and keys else None


def clip_label(promo: dict, blind: bool) -> str:
    segment = promo["segments"][0]
    if blind:  # The promo ID and rank would reveal the AI's ordering.
        return f"Episode {segment['episode']}, {segment['start_timestamp']} to {segment['end_timestamp']}"
    return f"{promo['global_rank']}. {promo['promo_id']} (Episode {segment['episode']})"


def story_order(promo: dict) -> tuple:
    segment = promo["segments"][0]
    return segment["episode"], segment["start_seconds"]


# Set by the Find promos button's callback, which runs before the script, so the run list can offer the new run.
run_clicked = st.session_state.pop("run_requested", False)
resume_clicked = st.session_state.pop("resume_requested", False)
# Run folders this browser session made. On a shared host only these are listed, so visitors never see each other's runs.
my_runs: list[str] = st.session_state.setdefault("my_runs", [])
SHARED_HOST = shared_host()

with st.sidebar:
    # 1. Existing runs. Opening one only reads its saved results: nothing is processed and no model is called.
    st.header("Existing runs")
    runs = existing_runs(set(my_runs) if SHARED_HOST else None)
    run_paths = dict(runs)
    run_options = [label for label, _ in runs]
    if run_clicked or resume_clicked or st.session_state.get("current_run"):
        run_options = [YOUR_LATEST_RUN] + run_options
    if run_clicked or resume_clicked:
        st.session_state["open_run"] = YOUR_LATEST_RUN  # Show the run just made, not the default.
    default_folder = demo_catalog()["default"] if DEMO_ROOT.exists() else None
    default_label = next((label for label, path in runs if path.parent == DEMO_ROOT and path.name == default_folder), None)
    if DEFAULT_RUN:
        wanted = Path(DEFAULT_RUN).resolve()
        default_label = next((label for label, path in runs if path.resolve() == wanted), default_label)
    if st.session_state.get("open_run") not in run_options:
        st.session_state.pop("open_run", None)
    # The final run opens by default. A remembered choice is used as is (Streamlit warns if both are given).
    start = {} if "open_run" in st.session_state else {"index": run_options.index(default_label) if default_label in run_options else 0}
    chosen_run = st.selectbox("Open an existing run", run_options, key="open_run", **start) if run_options else None

    # 2. Human review of the run chosen above.
    st.divider()
    st.header("Human review")
    reviewer = st.text_input("Reviewer name or ID", key="reviewer", help="Saved with each review, so several people can review the same run.")
    blind = st.checkbox(
        "Blind review mode", key="blind_review", value=BLIND_BY_DEFAULT,
        help="Hides the AI's rank, scores, ratings and explanations, and lists clips in story order, so they cannot sway your rating.",
    )
    st.caption("Reviews apply to the currently selected run.")

    # 3. A new run: a separate activity, folded away.
    st.divider()
    with st.expander("Run on a new screenplay pack", expanded=False):
        uploaded = st.file_uploader("Screenplay ZIP", type="zip")
        use_sample = st.checkbox("Use the built in invented sample show", value=uploaded is None)
        st.caption("An uploaded file goes to the computer running this app (on a hosted app, the host's server), "
                   "and to a model provider only in AI assisted mode.")
        mode = st.radio("Selection method", ["Basic (no API key)", "AI assisted"])
        fresh = False
        settings, key_from_secrets = load_settings()
        # On a hosted app (key in the host's secrets) each AI run is limited in episodes, to protect the free model quota.
        limit = max_episodes(settings) if key_from_secrets else None
        episode_text = ""
        if mode == "AI assisted":
            if has_api_key(settings):
                st.success("An API key is configured.")
            else:
                st.warning("No API key found. Copy .env.example to .env and add a key, or use Basic mode.")
            st.caption("Choosing AI assisted mode starts nothing. Models are called only when you click Find promos.")
            episode_text = st.text_input(
                "Episodes to process", key="ai_episodes", placeholder="All" if limit is None else f"For example 1-{limit}",
                help="For example 1-3,5. Leave empty for every episode." + (f" This app allows at most {limit} per run." if limit else ""),
            )
            fresh = st.checkbox("Ask the models again instead of reusing saved answers")
        st.button("Find promos", type="primary", use_container_width=True, on_click=start_new_run)
        resume_slot = st.container()  # Filled after any run below, so it reflects how that run ended.

source_path = None
if uploaded is not None and not use_sample:
    # Saved once per content, in a folder that is cleaned up after a day, not once per page refresh.
    source_path = store_upload(uploaded.getvalue(), uploaded.name, tempfile.gettempdir())
elif use_sample and SAMPLE.exists():
    source_path = SAMPLE

selection = None
if run_clicked and mode == "AI assisted" and source_path is not None:
    # Checked before anything is sent: AI runs spend the owner's model quota.
    try:
        available = sorted(cached_pack(str(source_path), source_path.stat().st_mtime))
    except ScreenplayPackError as error:
        st.error(f"Could not read this pack. {error}")
        run_clicked = False
    else:
        selection, problem = parse_episode_selection(episode_text, available)
        if problem:
            st.error(f"AI assisted run not started. {problem}")
            run_clicked = False
        elif limit is not None and len(selection) > limit:
            st.error(f"AI assisted run not started. This app allows at most {limit} episode(s) per AI run, to stay within the "
                     f"free model quota. Choose episodes, for example 1-{limit}.")
            run_clicked = False

# A job is a new run, or the unfinished one being resumed. It is remembered until it completes, so a run that was
# interrupted (a click elsewhere, a rate limit) can be resumed in the same folder.
job = None
if resume_clicked:
    saved_job = st.session_state.get("resumable")
    if saved_job and Path(saved_job["source"]).exists():
        job = saved_job
    else:
        st.session_state.pop("resumable", None)
        st.error("The unfinished run cannot be resumed: its screenplay pack is no longer on this computer. Start a new run.")
elif run_clicked:
    if source_path is None:
        st.error("Please upload a screenplay ZIP or use the sample show.")
    else:
        short_mode = "ai" if mode == "AI assisted" else "basic"
        job = {"run_dir": str(new_run_dir(OUTPUT_ROOT, short_mode)), "mode": short_mode, "source": str(source_path),
               "episodes": sorted(selection) if selection else None, "fresh": fresh}

if job:
    run_dir = Path(job["run_dir"])
    st.session_state["resumable"] = job
    if run_dir.name not in my_runs:
        my_runs.append(run_dir.name)
    bar = st.progress(0.0, text="Starting")

    def show_progress(done: int, total: int, label: str) -> None:
        bar.progress(min(done / max(total, 1), 1.0), text=label)

    try:
        if job["mode"] == "basic":
            summary = run_basic_pipeline(job["source"], run_dir, on_progress=show_progress)
        else:
            summary = run_ai_pipeline(job["source"], run_dir, use_cache=not job["fresh"], cache_dir=OUTPUT_ROOT / "llm_cache",
                                      on_progress=show_progress, only_episodes=set(job["episodes"]) if job["episodes"] else None,
                                      env_values=settings)
        bar.empty()
        st.session_state["current_run"] = str(run_dir)
        if summary.get("stopped_because"):
            st.warning(f"The run stopped early: {summary['stopped_because']} Saved progress is kept: use Resume unfinished run "
                       "in the sidebar to continue it.")
        elif summary.get("complete") is False:
            st.warning("The run finished with some failures. See the processing summary below. Resume unfinished run retries them.")
        else:
            st.session_state.pop("resumable", None)
            st.success(f"Finished in {summary['processing_seconds']} seconds.")
    except ScreenplayPackError as error:
        bar.empty()
        st.session_state.pop("resumable", None)
        st.error(f"Could not read this pack. {error}")
    except LLMError as error:
        bar.empty()
        st.session_state.pop("resumable", None)
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)
        st.error(f"AI assisted mode could not start. {error.detail}")

unfinished = st.session_state.get("resumable")
if unfinished:
    with resume_slot:
        st.caption(f"Unfinished run: {Path(unfinished['run_dir']).name}. Resume continues it in the same folder and "
                   "skips the episodes already done.")
        st.button("Resume unfinished run", use_container_width=True, on_click=resume_run)

run_to_show = None
if chosen_run == YOUR_LATEST_RUN:
    if st.session_state.get("current_run"):
        run_to_show = Path(st.session_state["current_run"])
    elif default_label:  # Nothing was made (for example the run was refused), so show the default run.
        run_to_show = run_paths[default_label]
elif chosen_run:
    run_to_show = run_paths[chosen_run]

if run_to_show is None or not (run_to_show / "promos.json").exists():
    st.info("Open \"Run on a new screenplay pack\" in the sidebar, choose a pack and click Find promos. "
            "The built in sample show works without any key.")
    st.stop()

if run_to_show.parent == DEMO_ROOT:
    entry = demo_catalog()["entries"].get(run_to_show.name, {})
    message = entry.get("description") or "A precomputed run saved with the app."
    message += " To make your own run, open \"Run on a new screenplay pack\" in the sidebar and click Find promos."
    (st.success if entry.get("kind") == "final" else st.info)(message)

data = json.loads((run_to_show / "promos.json").read_text(encoding="utf-8"))
summary = json.loads((run_to_show / "processing_summary.json").read_text(encoding="utf-8"))
promos = data["promos"]
method = data["selection_method"]

st.header(f"Results: {data.get('title', '')}")
if method == "basic":
    st.warning("Basic selections. These come from simple signals. They have had no story judgement and no cold viewer test.")
else:
    st.info("AI assisted selections. Each clip passed a blind hook test and a blind cold viewer test. A person should still review them.")

columns = st.columns(4)
columns[0].metric("Episodes processed", f"{summary['episodes_processed']} of {summary['episodes_in_pack']}")
columns[1].metric("Recommended clips", len(promos))
columns[2].metric("Processing time", f"{summary['processing_seconds']} s")
columns[3].metric("Verification errors", len(summary.get("verification_errors", [])))

if summary.get("failed_episodes") or summary.get("episodes_pending_or_failed"):
    st.error(f"These episodes were not processed: {summary.get('episodes_pending_or_failed')}. Run again to retry them.")

if not promos:
    st.warning("No clip met the requirements. That can be the correct answer. See the summary for the reasons.")
elif blind:
    st.info("Blind review mode is on. The AI's rank, scores, ratings and explanations are hidden, and clips are listed in story order.")
    st.subheader("Clips")
    listed = sorted(promos, key=story_order)
    in_review_set = load_review_set(run_to_show.name)
    if in_review_set and st.session_state.get("only_review_set", True):
        listed = [promo for promo in listed if promo["clip_key"] in set(in_review_set)]
        st.caption(f"Showing the {len(listed)} clips in your review set.")
    table = pd.DataFrame([{
        "Episode": promo["segments"][0]["episode"],
        "Start": promo["segments"][0]["start_timestamp"],
        "End": promo["segments"][0]["end_timestamp"],
        "Seconds": round(promo["total_duration_seconds"], 1),
        "Opening line": promo["hook"]["evidence"],
        "Final line": promo["cliffhanger"]["evidence"],
    } for promo in listed])
    st.dataframe(table, use_container_width=True, hide_index=True)
else:
    first = next((promo for promo in promos if promo["first_post_recommendation"]), None)
    if first:
        segment = first["segments"][0]
        st.subheader("Post this first")
        st.success(
            f"**{first['promo_id']}: Episode {segment['episode']}, {segment['start_timestamp']} to {segment['end_timestamp']}** "
            f"({first['total_duration_seconds']:.1f}s). {first['first_post_reason']}"
        )

    st.subheader("Ranking")
    table = pd.DataFrame([{
        "Rank": promo["global_rank"],
        "ID": promo["promo_id"],
        "Episode": promo["segments"][0]["episode"],
        "Start": promo["segments"][0]["start_timestamp"],
        "End": promo["segments"][0]["end_timestamp"],
        "Seconds": round(promo["total_duration_seconds"], 1),
        "Opening line": promo["hook"]["evidence"],
        "Final line": promo["cliffhanger"]["evidence"],
        "Hook": promo["hook"]["strength"],
        "Ending": promo["cliffhanger"]["strength"],
        "Cold viewer": promo["cold_viewer_check"]["result"],
        "Score": promo["total_score"],
    } for promo in promos])
    st.dataframe(table, use_container_width=True, hide_index=True)

if promos:
    st.subheader("Clip details")
    ordered = sorted(promos, key=story_order) if blind else promos
    review_set = load_review_set(run_to_show.name)
    if review_set:
        missing = [key for key in review_set if key not in {p["clip_key"] for p in promos}]
        if missing:
            st.warning(f"{len(missing)} clip(s) in the review set are not in this run: {', '.join(missing)}")
        if st.checkbox(f"Only the clips in my review set ({len(review_set) - len(missing)})", value=True, key="only_review_set"):
            ordered = [p for p in ordered if p["clip_key"] in set(review_set)]
    labels = {clip_label(p, blind): p for p in ordered}
    options = list(labels)
    if st.session_state.get("clip_choice") not in options:
        st.session_state.pop("clip_choice", None)

    def step(delta: int) -> None:
        # Move from the clip shown in the last run, which always belongs to `options`. The selectbox's own value can be
        # stale: after blind mode changes the clip labels, the browser may send the old label back with the click.
        st.session_state["clip_choice"] = step_clip(options, st.session_state.get("clip_shown"), delta)

    nav = st.columns([1, 1, 3])
    nav[0].button("◀ Previous clip", on_click=step, args=(-1,), use_container_width=True)
    nav[1].button("Next clip ▶", on_click=step, args=(1,), use_container_width=True)
    selected = labels[st.selectbox("Choose a clip", options, key="clip_choice")]
    st.session_state["clip_shown"] = clip_label(selected, blind)
    nav[2].caption(f"Clip {options.index(clip_label(selected, blind)) + 1} of {len(options)}")
    segment = selected["segments"][0]
    if blind:
        st.markdown(f"**Episode {segment['episode']}, {segment['start_timestamp']} to {segment['end_timestamp']}** "
                    f"({selected['total_duration_seconds']:.1f}s). The full clip is under \"See the screenplay for this clip\" below.")
    else:
        left, right = st.columns([3, 2])
        with left:
            st.markdown(f"**Why it could work:** {selected['overall_explanation']}")
            st.markdown(f"**Hook** (`{selected['hook']['cue_ids'][0]}`, {selected['hook']['strength']}, starts {selected['hook']['seconds_from_clip_start']:.2f}s in)")
            st.markdown(f"> {selected['hook']['evidence']}")
            st.markdown(f"**Ending** (`{selected['cliffhanger']['cue_ids'][0]}`, {selected['cliffhanger']['strength']})")
            st.markdown(f"> {selected['cliffhanger']['evidence']}")
            st.markdown(f"**On its own:** {selected['independent_understanding_explanation']}")
            if selected["warnings"]:
                st.warning(" | ".join(selected["warnings"]))
            if segment["boundary_adjustments"]:
                st.caption("Boundary changes: " + " ".join(segment["boundary_adjustments"]))
        with right:
            st.markdown("**Score breakdown** (a comparison measure only, not a chance of success)")
            st.json(selected["score_breakdown"])
            check = selected["cold_viewer_check"]
            if check["result"] != "not_performed":
                st.markdown("**What the blind viewer understood**")
                st.write({"who": check["who_appears_involved"], "what": check["what_is_happening"], "conflict": check["main_conflict"], "wants to know": check["viewer_wants_to_know"]})

    # The clip's cues: from the run's bundled excerpts, else from its pack (the one chosen in the sidebar, or a file of the
    # same name in PROMO_PACK_DIR). Nothing is generated and no model is called.
    excerpts_path = run_to_show / EXCERPTS_FILE
    excerpt = None
    if excerpts_path.is_file():
        excerpt = load_excerpts(str(excerpts_path), excerpts_path.stat().st_mtime, run_to_show.name).get(selected["clip_key"])
    input_name = Path(summary.get("input_file") or "").name
    pack_path = source_path if source_path is not None and source_path.name == input_name else None
    if pack_path is None and PACK_DIR and input_name and (Path(PACK_DIR) / input_name).is_file():
        pack_path = Path(PACK_DIR) / input_name
    with st.expander("See the screenplay for this clip", expanded=False):
        if excerpt is not None:
            st.caption(f"Episode {segment['episode']}, {segment['start_timestamp']} to {segment['end_timestamp']}: every cue in this "
                       "clip, copied unchanged from the original screenplay. The rest of the screenplay is not published with the app.")
            # A plain table wraps every line in full, so the whole clip can be read without widening columns.
            st.table(transcript_table([cue for part in excerpt["segments"] for cue in part["cues"]]))
        elif pack_path is None and run_to_show.parent == DEMO_ROOT:
            st.caption("The screenplay for this run is not published with the app, so its full transcript cannot be shown. "
                       "The opening and final lines above come from the run's own results.")
        elif pack_path is None:
            st.caption("Select the same pack in the sidebar to see the cues here, or set PROMO_PACK_DIR to the folder that holds it.")
        else:
            try:
                episode = cached_pack(str(pack_path), pack_path.stat().st_mtime)[segment["episode"]]
                st.table(transcript_table([vars(cue) for cue in cues_in_range(episode, segment["start_seconds"], segment["end_seconds"])]))
            except (ScreenplayPackError, KeyError):
                st.caption("Could not open the pack for this run.")

    # Human review. Saved apart from the run, so the AI's outputs are never changed.
    review_path = review_store_path(OUTPUT_ROOT)
    records, problems = load_reviews(review_path)
    latest = latest_reviews(records, run_to_show.name)
    st.subheader("Human review")
    if problems:
        st.warning(f"{len(problems)} saved review line(s) could not be read and were skipped: " + " ".join(problems))
    if not reviewer.strip():
        st.info("Enter your reviewer name or ID in the sidebar to review this clip.")
    else:
        previous = review_by(latest, run_to_show.name, selected["clip_key"], reviewer)
        others = sum(1 for (run_id, clip_key, _), record in latest.items()
                     if clip_key == selected["clip_key"] and record.reviewer.strip().casefold() != reviewer.strip().casefold())
        if previous:
            st.caption(f"Your last review of this clip was saved {previous.saved_at[:19].replace('T', ' ')} UTC. Saving again replaces it; the earlier one stays in the history.")
        if others:
            st.caption(f"{others} other reviewer(s) have reviewed this clip. Their ratings are not shown here.")
        form_key = f"review|{run_to_show.name}|{selected['clip_key']}|{reviewer.strip().casefold()}"
        with st.form(form_key):
            choices = {}
            for field, label in RATING_FIELDS:
                prior = getattr(previous, field) if previous else None
                choices[field] = st.radio(f"{label} (1 to 5)", [1, 2, 3, 4, 5], index=None if prior is None else prior - 1,
                                          horizontal=True, key=f"{form_key}|{field}")
            prior_verdict = next((label for label, value in VERDICTS.items() if previous and previous.would_publish == value), None)
            verdict = st.radio("Would publish?", list(VERDICTS), index=None if prior_verdict is None else list(VERDICTS).index(prior_verdict),
                               horizontal=True, key=f"{form_key}|verdict")
            comments = st.text_area("Comments (optional)", value=previous.comments if previous else "", key=f"{form_key}|comments")
            submitted = st.form_submit_button("Save review", type="primary")
        if submitted:
            missing = [label for field, label in RATING_FIELDS if choices[field] is None] + (["Would publish?"] if verdict is None else [])
            if missing:
                st.error("Please answer every question before saving: " + ", ".join(missing) + ".")
            else:
                try:
                    record = new_review(run_to_show, selected, method, reviewer, would_publish=VERDICTS[verdict], comments=comments, **choices)
                except ValidationError as error:
                    st.error(f"The review could not be saved: {error.errors()[0]['msg']}")
                else:
                    append_review(review_path, record)
                    st.success(f"Review saved for {selected['promo_id'] if not blind else clip_label(selected, True)}.")
                    records, problems = load_reviews(review_path)
                    latest = latest_reviews(records, run_to_show.name)

    reviewed = {clip_key for (_, clip_key, _) in latest}
    st.caption(f"Reviewed in this run: {sum(1 for p in promos if p['clip_key'] in reviewed)} of {len(promos)} clips, "
               f"by {len({key[2] for key in latest})} reviewer(s). Reviews are stored in {review_path}.")
    if review_set and reviewer.strip():
        mine = {clip_key for (_, clip_key, who) in latest if who == reviewer.strip().casefold()}
        st.info(f"Review set progress: you have reviewed {len(mine & set(review_set))} of {len(review_set)} clips.")
    st.caption("Reviews are saved on the computer running this app. On a hosted app such as Streamlit Community Cloud that storage "
               "is temporary and is wiped when the app restarts or sleeps, so download your reviews to keep them.")
    if blind:
        st.caption("Turn off blind review mode to compare human and AI ratings. The download below holds your reviews only, no AI figures.")
        # Only this reviewer's reviews: other people's ratings must not reach a blind reviewer.
        own = reviews_of(latest, reviewer)
        st.download_button("My reviews (JSON)", json.dumps([record.model_dump(exclude={"promo_id"}) for record in own], indent=2, ensure_ascii=False),
                           file_name=f"human_reviews_{run_to_show.name}_blind.json", disabled=not own)
    else:
        st.subheader("Human review compared with AI")
        rows = comparison_rows(promos, run_to_show, method, latest)
        shown = pd.DataFrame([{
            "Rank": row["ai_rank"], "ID": row["promo_id"], "Episode": row["episode"], "Start": row["start_timestamp"],
            "AI score": row["ai_total_score"], "AI hook": row["ai_hook_rating"], "Human hook": row["hook_quality"],
            "AI ending": row["ai_ending_rating"], "Human cliffhanger": row["cliffhanger_quality"],
            "AI clarity": row["ai_clarity_rating"], "Human clarity": row["clarity"], "Human overall": row["overall_quality"],
            "Would publish": row["would_publish"], "Reviewer": row["reviewer"], "Comments": row["comments"],
            "Run changed since review": row["run_changed_since_review"],
        } for row in rows], dtype=object)
        # Shown as text: ratings stay "4", not "4.0", and "—" marks not rated or not reviewed yet.
        shown = shown.apply(lambda column: column.map(lambda value: "—" if value is None or value != value else str(value)))
        st.dataframe(shown, use_container_width=True, hide_index=True)
        st.caption("AI ratings come from the blind hook and cold viewer tests (1 to 5). The AI score is 0 to 100 and only ranks clips "
                   "against each other. Basic mode makes no ratings. Human ratings never change the AI's ranking.")
        reviewed_rows = [row for row in rows if row["reviewer"]]
        export_columns = st.columns(2)
        export_columns[0].download_button("Reviews CSV", rows_to_csv(reviewed_rows).encode("utf-8"),
                                          file_name=f"human_reviews_{run_to_show.name}.csv", use_container_width=True,
                                          disabled=not reviewed_rows)
        export_columns[1].download_button("Reviews JSON", rows_to_json(reviewed_rows).encode("utf-8"),
                                          file_name=f"human_reviews_{run_to_show.name}.json", use_container_width=True,
                                          disabled=not reviewed_rows)

st.subheader("Downloads")
if blind:
    st.caption("The run's files hold the AI's scores, so they are hidden in blind review mode.")
else:
    download_columns = st.columns(4)
    for column, (name, label) in zip(download_columns, [
        ("promos.json", "JSON"), ("promos.csv", "CSV"), ("report.md", "Report"), ("top_twenty_human_review_sheet.csv", "Blank review sheet"),
    ]):
        path = run_to_show / name
        if path.exists():
            column.download_button(label, path.read_bytes(), file_name=name, use_container_width=True)

with st.expander("Processing summary"):
    st.json(summary)
