"""The screenplay cues of each recommended clip, saved next to a run as transcripts.json.

Only the cues that play inside each promo's own clip are written, taken unchanged from the parsed
screenplay. The rest of the screenplay is not copied. With this file a run can show each clip's
screenplay without the pack, for example after it is reopened from the database. No model is called.
"""

from __future__ import annotations

import json
from pathlib import Path

from .boundaries import cues_in_range
from .parser import load_pack

FILE_NAME = "transcripts.json"


def build_excerpts(pack: str | Path, run_dir: str | Path) -> dict:
    pack, run_dir = Path(pack), Path(run_dir)
    data = json.loads((run_dir / "promos.json").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "processing_summary.json").read_text(encoding="utf-8"))
    expected = Path(summary.get("input_file") or "").name
    if expected and pack.name != expected:
        raise ValueError(f"This run was made from '{expected}', not '{pack.name}'.")
    episodes = {episode.number: episode for episode in load_pack(pack)[0]}
    clips = {}
    for promo in data["promos"]:
        segments = []
        for segment in promo["segments"]:
            cues = cues_in_range(episodes[segment["episode"]], segment["start_seconds"], segment["end_seconds"])
            segments.append({
                "episode": segment["episode"],
                "start_seconds": segment["start_seconds"],
                "end_seconds": segment["end_seconds"],
                "cues": [{
                    "cue_id": cue.cue_id, "start": cue.start, "end": cue.end, "kind": cue.kind,
                    "speaker": cue.speaker, "delivery": cue.delivery, "text": cue.text,
                } for cue in cues],
            })
        clips[promo["clip_key"]] = {"promo_id": promo["promo_id"], "segments": segments}
    return {
        "schema_version": 1,
        "run_id": run_dir.name,
        "input_file": expected or pack.name,
        "note": "Screenplay cues inside each recommended clip only, copied unchanged from the parsed screenplay.",
        "clips": clips,
    }


def write_excerpts(pack: str | Path, run_dir: str | Path) -> Path:
    """Build and save transcripts.json in the run folder (LF line endings, like every other result file)."""
    target = Path(run_dir) / FILE_NAME
    result = build_excerpts(pack, run_dir)
    target.write_bytes((json.dumps(result, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
    return target
