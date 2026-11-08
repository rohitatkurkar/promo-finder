"""Files a person fills in by hand. Nothing here reads any candidate or score.

These are created before candidates exist so the human reference set stays
independent of what the tool recommends.
"""

from __future__ import annotations

import csv
import html
from pathlib import Path

from .parser import ACTION, CAMERA, DIALOGUE, SOUND, Episode, format_timestamp

REFERENCE_COLUMNS = [
    "reference_id", "episode", "start_time", "end_time", "hook_cue_id",
    "ending_cue_id", "why_i_selected_it", "reviewer",
]

REVIEW_COLUMNS = [
    "global_rank", "promo_id", "episode", "start_timestamp", "end_timestamp",
    "would_stop_scrolling_1_to_5", "wants_to_know_next_1_to_5",
    "understood_without_the_show_1_to_5", "would_post_yes_no", "notes", "reviewer",
]

GUIDE = """# Manual reference exercise

Please do this BEFORE opening any results folder. Its value depends on your
picks being independent of the tool. Skip it if you must, but then the reports
cannot claim an independent human comparison.

## What to do

1. Note your start time. The minutes you spend here also become the "manual
   discovery time" in the time saved comparison.
2. Open `screenplay_with_cue_ids.html` in a browser. It shows every episode with
   cue IDs and timestamps, in the original order, with no ratings of any kind.
3. Use `episode_index.csv` to move around. It holds neutral facts only.
4. Pick at least 8 moments that you would actually post as promos.
5. Fill in one row of `manual_reference_worksheet.csv` for each moment.
6. Save the file, and write your total minutes in `time_saved_worksheet.csv`.

## What makes a valid pick

- 20 to 60 seconds long, as one continuous stretch from one episode.
- Something grabs a scrolling viewer in the first 3 seconds.
- It stops at an unresolved moment, so the viewer needs to know what is next.
- Someone who has never seen the show can follow it.

## How to fill in a row

| Column | Example format | Meaning |
|---|---|---|
| reference_id | H01 | Your own numbering, H01 to H08 and beyond |
| episode | 7 | Episode number |
| start_time | 00:18.90 | Time the clip starts, in the screenplay's format |
| end_time | 01:04.80 | Time the clip ends |
| hook_cue_id | E07_C0012 | The cue that grabs attention |
| ending_cue_id | E07_C0031 | The cue where the viewer is left hanging |
| why_i_selected_it | one short line | Your own reason |
| reviewer | your name | Who made this pick |

Pick from across the show, or from one stretch if that is where the best moments
are. There is no target spread, and no right number above 8.
"""


def write_reference_kit(episodes: list[Episode], out_dir: str | Path, blank_rows: int = 12) -> list[Path]:
    """Create the blank worksheet, episode index, cue browser and guide.

    An existing worksheet is never overwritten, because it may hold human picks.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    worksheet = out / "manual_reference_worksheet.csv"
    if not worksheet.exists():
        with worksheet.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(REFERENCE_COLUMNS)
            for number in range(1, blank_rows + 1):
                writer.writerow([f"H{number:02d}"] + [""] * (len(REFERENCE_COLUMNS) - 1))
        written.append(worksheet)

    time_sheet = out / "time_saved_worksheet.csv"
    if not time_sheet.exists():
        with time_sheet.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["measure", "minutes", "how_it_was_measured", "recorded_by"])
            for measure in (
                "manual_discovery_time_for_this_show",
                "tool_processing_time",
                "editor_time_reviewing_tool_output",
            ):
                writer.writerow([measure, "", "", ""])
        written.append(time_sheet)

    index_path = out / "episode_index.csv"
    with index_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["episode", "duration", "scenes", "dialogue_lines", "action_cues", "first_cue_id", "last_cue_id", "logline"])
        for episode in episodes:
            writer.writerow([
                episode.number,
                format_timestamp(episode.duration),
                len(episode.scenes),
                sum(1 for cue in episode.cues if cue.kind == DIALOGUE),
                sum(1 for cue in episode.cues if cue.kind == ACTION),
                episode.cues[0].cue_id if episode.cues else "",
                episode.cues[-1].cue_id if episode.cues else "",
                episode.logline,
            ])
    written.append(index_path)

    guide_path = out / "REFERENCE_GUIDE.md"
    guide_path.write_text(GUIDE, encoding="utf-8", newline="\n")
    written.append(guide_path)

    browser_path = out / "screenplay_with_cue_ids.html"
    browser_path.write_text(render_cue_browser(episodes), encoding="utf-8", newline="\n")
    written.append(browser_path)
    return written


def write_review_sheet(path: str | Path, rows: int = 20) -> Path:
    """Blank top twenty sheet. Ratings stay empty until a person fills them in."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(REVIEW_COLUMNS)
        for rank in range(1, rows + 1):
            writer.writerow([rank] + [""] * (len(REVIEW_COLUMNS) - 1))
    return target


def render_cue_browser(episodes: list[Episode]) -> str:
    """One static page showing all cues in screenplay order, with no judgement added."""
    kind_class = {DIALOGUE: "dialogue", ACTION: "action", CAMERA: "camera", SOUND: "sound"}
    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Screenplay with cue IDs</title><style>"
        "body{font:15px/1.5 -apple-system,Segoe UI,sans-serif;margin:0;background:#fff;color:#1c1c1c}"
        "header{position:sticky;top:0;background:#f4f4f2;padding:10px 16px;border-bottom:1px solid #ddd;z-index:2}"
        "main{max-width:920px;margin:0 auto;padding:16px}"
        "h2{margin:32px 0 4px}h3{margin:18px 0 6px;font-size:14px;color:#555}"
        ".logline{color:#555;margin:0 0 8px}"
        ".cue{display:grid;grid-template-columns:96px 130px 1fr;gap:10px;padding:3px 0;border-bottom:1px solid #f0f0f0}"
        ".id{font:12px ui-monospace,Menlo,monospace;color:#666}.time{font:12px ui-monospace,Menlo,monospace}"
        ".speaker{font-weight:600}.action{background:#fafaf5}.camera,.sound{color:#888;font-size:13px}"
        "body.hide-shots .camera,body.hide-shots .sound{display:none}"
        "nav a{margin-right:6px;font-size:13px}label{margin-right:16px}"
        "@media (max-width:640px){.cue{grid-template-columns:1fr}}"
        "</style></head><body><header>"
        "<label><input type='checkbox' onchange=\"document.body.classList.toggle('hide-shots',this.checked)\"> "
        "Hide camera and sound cues</label><nav>"
    ]
    parts += [f"<a href='#ep{e.number}'>{e.number}</a>" for e in episodes]
    parts.append("</nav></header><main>")
    for episode in episodes:
        parts.append(f"<h2 id='ep{episode.number}'>Episode {episode.number}</h2>")
        parts.append(f"<p class='logline'>{html.escape(episode.logline)}</p>")
        current_scene = object()
        scenes = {scene.number: scene for scene in episode.scenes}
        for cue in episode.cues:
            if cue.scene != current_scene:
                current_scene = cue.scene
                scene = scenes.get(cue.scene)
                heading = scene.heading if scene and scene.heading else "Unknown scene"
                parts.append(f"<h3>Scene {cue.scene}: {html.escape(heading)}</h3>")
            start = format_timestamp(cue.start) if cue.start is not None else "??"
            end = format_timestamp(cue.end) if cue.end is not None else "??"
            if cue.kind == DIALOGUE:
                note = f" <em>({html.escape(cue.delivery)})</em>" if cue.delivery else ""
                body = f"<span class='speaker'>{html.escape(cue.speaker or '')}</span>{note}: {html.escape(cue.text)}"
            else:
                body = f"<b>{cue.kind.upper()}</b>: {html.escape(cue.text)}"
            parts.append(
                f"<div class='cue {kind_class.get(cue.kind, '')}'><span class='id'>{cue.cue_id}</span>"
                f"<span class='time'>{start} to {end}</span><span>{body}</span></div>"
            )
    parts.append("</main></body></html>")
    return "".join(parts)


def read_reference_sheet(path: str | Path) -> list[dict]:
    """Read filled rows only. A row counts when it has an episode, start and end."""
    rows = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if (row.get("episode") or "").strip() and (row.get("start_time") or "").strip() and (row.get("end_time") or "").strip():
                rows.append(row)
    return rows
