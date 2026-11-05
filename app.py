"""A simple interface for the promo finder. Start it with: streamlit run app.py"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path

import pandas as pd
import streamlit as st

from promo_finder.boundaries import cues_in_range
from promo_finder.llm_client import LLMError
from promo_finder.parser import ACTION, CAMERA, DIALOGUE, ScreenplayPackError, format_timestamp, load_pack
from promo_finder.pipeline import DEFAULT_ENV, pack_title, run_ai_pipeline, run_basic_pipeline

ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = Path(os.environ.get("PROMO_OUTPUT_DIR", ROOT / "outputs"))
SAMPLE = ROOT / "sample_input" / "synthetic_show.zip"
KIND_ICON = {DIALOGUE: "Line", ACTION: "Action", CAMERA: "Shot"}

st.set_page_config(page_title="Promo Finder", layout="wide")
st.title("Promo Finder")
st.caption("Reads a microdrama screenplay and recommends 20 to 60 second promo clips. All times come from the screenplay's own cues.")


def key_is_configured() -> bool:
    if not DEFAULT_ENV.exists():
        return False
    from dotenv import dotenv_values

    values = dotenv_values(DEFAULT_ENV)
    return bool(values.get("LLM_API_KEY") or (values.get("FINDER_API_KEY") and values.get("EVALUATOR_API_KEY")))


def existing_runs() -> list[Path]:
    if not OUTPUT_ROOT.exists():
        return []
    return sorted((p for p in OUTPUT_ROOT.iterdir() if (p / "promos.json").exists()), key=lambda p: p.stat().st_mtime, reverse=True)


with st.sidebar:
    st.header("1. Choose a screenplay pack")
    uploaded = st.file_uploader("Screenplay ZIP", type="zip")
    use_sample = st.checkbox("Use the built in invented sample show", value=uploaded is None)
    st.caption("Uploaded files stay on this machine and only go to a model provider in AI assisted mode.")

    st.header("2. Choose a mode")
    mode = st.radio("Selection method", ["Basic (no API key)", "AI assisted"], label_visibility="collapsed")
    fresh = False
    if mode == "AI assisted":
        if key_is_configured():
            st.success("An API key is set in .env")
        else:
            st.warning("No API key found. Copy .env.example to .env and add a key, or use Basic mode.")
        fresh = st.checkbox("Ask the models again instead of reusing saved answers")

    run_clicked = st.button("Find promos", type="primary", use_container_width=True)

    st.header("Earlier runs")
    runs = existing_runs()
    chosen_run = st.selectbox("Open a run", ["(latest)"] + [run.name for run in runs]) if runs else None

source_path = None
if uploaded is not None and not use_sample:
    holder = Path(tempfile.mkdtemp(prefix="promo_upload_"))
    source_path = holder / uploaded.name
    source_path.write_bytes(uploaded.getvalue())
elif use_sample and SAMPLE.exists():
    source_path = SAMPLE

if run_clicked:
    if source_path is None:
        st.error("Please upload a screenplay ZIP or use the sample show.")
    else:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        short_mode = "ai" if mode == "AI assisted" else "basic"
        run_dir = OUTPUT_ROOT / f"{short_mode}_{stamp}"
        bar = st.progress(0.0, text="Starting")

        def show_progress(done: int, total: int, label: str) -> None:
            bar.progress(min(done / max(total, 1), 1.0), text=label)

        try:
            if short_mode == "basic":
                summary = run_basic_pipeline(source_path, run_dir, on_progress=show_progress)
            else:
                summary = run_ai_pipeline(source_path, run_dir, use_cache=not fresh, cache_dir=OUTPUT_ROOT / "llm_cache", on_progress=show_progress)
            bar.empty()
            st.session_state["current_run"] = str(run_dir)
            if summary.get("stopped_because"):
                st.warning(f"The run stopped early: {summary['stopped_because']} Saved progress is kept.")
            elif summary.get("complete") is False:
                st.warning("The run finished with some failures. See the processing summary below.")
            else:
                st.success(f"Finished in {summary['processing_seconds']} seconds.")
        except ScreenplayPackError as error:
            bar.empty()
            st.error(f"Could not read this pack. {error}")
        except LLMError as error:
            bar.empty()
            if run_dir.exists():
                shutil.rmtree(run_dir, ignore_errors=True)
            st.error(f"AI assisted mode could not start. {error.detail}")

run_to_show = None
if chosen_run and chosen_run != "(latest)":
    run_to_show = OUTPUT_ROOT / chosen_run
elif st.session_state.get("current_run"):
    run_to_show = Path(st.session_state["current_run"])
elif runs:
    run_to_show = runs[0]

if run_to_show is None or not (run_to_show / "promos.json").exists():
    st.info("Choose a pack and click Find promos. The built in sample show works without any key.")
    st.stop()

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

    st.subheader("Clip details")
    labels = {f"{p['global_rank']}. {p['promo_id']} (Episode {p['segments'][0]['episode']})": p for p in promos}
    selected = labels[st.selectbox("Choose a clip", list(labels))]
    segment = selected["segments"][0]
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

    input_name = summary.get("input_file")
    pack_path = source_path if source_path is not None and source_path.name == input_name else None
    with st.expander("See the screenplay for this clip"):
        if pack_path is None:
            st.caption("Select the same pack in the sidebar to see the cues here.")
        else:
            try:
                episodes, _ = load_pack(pack_path)
                episode = next(e for e in episodes if e.number == segment["episode"])
                rows = [{
                    "Cue": cue.cue_id, "Time": format_timestamp(cue.start), "Type": KIND_ICON.get(cue.kind, cue.kind.title()),
                    "Speaker": cue.speaker or "", "Text": cue.text,
                } for cue in cues_in_range(episode, segment["start_seconds"], segment["end_seconds"])]
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            except (ScreenplayPackError, StopIteration):
                st.caption("Could not open the pack for this run.")

st.subheader("Downloads")
download_columns = st.columns(4)
for column, (name, label) in zip(download_columns, [
    ("promos.json", "JSON"), ("promos.csv", "CSV"), ("report.md", "Report"), ("top_twenty_human_review_sheet.csv", "Blank review sheet"),
]):
    path = run_to_show / name
    if path.exists():
        column.download_button(label, path.read_bytes(), file_name=name, use_container_width=True)

with st.expander("Processing summary"):
    st.json(summary)
