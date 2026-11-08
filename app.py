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

from pydantic import ValidationError

from promo_finder.boundaries import cues_in_range
from promo_finder.llm_client import LLMError
from promo_finder.parser import ACTION, CAMERA, DIALOGUE, ScreenplayPackError, format_timestamp, load_pack
from promo_finder.pipeline import DEFAULT_ENV, pack_title, run_ai_pipeline, run_basic_pipeline
from promo_finder.reviews import (
    append_review,
    comparison_rows,
    load_reviews,
    latest_reviews,
    new_review,
    review_by,
    review_store_path,
    rows_to_csv,
    rows_to_json,
)

ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = Path(os.environ.get("PROMO_OUTPUT_DIR", ROOT / "outputs"))
# Optional: a folder holding the screenplay packs, so a run's transcript can be shown without uploading the pack again.
PACK_DIR = os.environ.get("PROMO_PACK_DIR")
SAMPLE = ROOT / "sample_input" / "synthetic_show.zip"
KIND_ICON = {DIALOGUE: "Line", ACTION: "Action", CAMERA: "Shot"}
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


@st.cache_resource(show_spinner=False)
def cached_pack(path: str, modified: float):
    """Parse a pack once per file version, so moving between clips stays quick."""
    episodes, _ = load_pack(path)
    return {episode.number: episode for episode in episodes}


def clip_label(promo: dict, blind: bool) -> str:
    segment = promo["segments"][0]
    if blind:  # The promo ID and rank would reveal the AI's ordering.
        return f"Episode {segment['episode']}, {segment['start_timestamp']} to {segment['end_timestamp']}"
    return f"{promo['global_rank']}. {promo['promo_id']} (Episode {segment['episode']})"


def story_order(promo: dict) -> tuple:
    segment = promo["segments"][0]
    return segment["episode"], segment["start_seconds"]


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

    st.header("Human review")
    reviewer = st.text_input("Reviewer name or ID", key="reviewer", help="Saved with each review, so several people can review the same run.")
    blind = st.checkbox(
        "Blind review mode", key="blind_review",
        help="Hides the AI's rank, scores, ratings and explanations, and lists clips in story order, so they cannot sway your rating.",
    )

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
elif blind:
    st.info("Blind review mode is on. The AI's rank, scores, ratings and explanations are hidden, and clips are listed in story order.")
    st.subheader("Clips")
    table = pd.DataFrame([{
        "Episode": promo["segments"][0]["episode"],
        "Start": promo["segments"][0]["start_timestamp"],
        "End": promo["segments"][0]["end_timestamp"],
        "Seconds": round(promo["total_duration_seconds"], 1),
        "Opening line": promo["hook"]["evidence"],
        "Final line": promo["cliffhanger"]["evidence"],
    } for promo in sorted(promos, key=story_order)])
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
    labels = {clip_label(p, blind): p for p in ordered}
    selected = labels[st.selectbox("Choose a clip", list(labels))]
    segment = selected["segments"][0]
    if blind:
        st.markdown(f"**Episode {segment['episode']}, {segment['start_timestamp']} to {segment['end_timestamp']}** "
                    f"({selected['total_duration_seconds']:.1f}s). Read the full clip below before rating it.")
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

    # Find the run's pack: the one chosen in the sidebar, or a file of the same name in PROMO_PACK_DIR.
    input_name = Path(summary.get("input_file") or "").name
    pack_path = source_path if source_path is not None and source_path.name == input_name else None
    if pack_path is None and PACK_DIR and input_name and (Path(PACK_DIR) / input_name).is_file():
        pack_path = Path(PACK_DIR) / input_name
    with st.expander("See the screenplay for this clip", expanded=blind):
        if pack_path is None:
            st.caption("Select the same pack in the sidebar to see the cues here, or set PROMO_PACK_DIR to the folder that holds it.")
        else:
            try:
                episode = cached_pack(str(pack_path), pack_path.stat().st_mtime)[segment["episode"]]
                rows = [{
                    "Cue": cue.cue_id, "Start": format_timestamp(cue.start), "End": format_timestamp(cue.end),
                    "Type": KIND_ICON.get(cue.kind, cue.kind.title()), "Speaker": cue.speaker or "",
                    "Delivery": cue.delivery or "", "Text": cue.text,
                } for cue in cues_in_range(episode, segment["start_seconds"], segment["end_seconds"])]
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            except (ScreenplayPackError, KeyError):
                st.caption("Could not open the pack for this run.")

    # Human review. Saved apart from the run, so the AI's outputs are never changed.
    review_path = review_store_path(run_to_show.parent)
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
    if blind:
        st.caption("Turn off blind review mode to compare human and AI ratings and to export the reviews.")
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
