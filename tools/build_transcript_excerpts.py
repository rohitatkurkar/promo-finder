"""Save the screenplay cues of each recommended clip next to a bundled run, so the hosted app can show them.

Only the cues that play inside each promo's own clip are written, taken unchanged from the parsed screenplay.
The rest of the screenplay is not copied. No model is called.

    python tools/build_transcript_excerpts.py --pack PATH_TO_PACK.zip --run demo_runs/RUN_FOLDER
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from promo_finder.boundaries import cues_in_range  # noqa: E402
from promo_finder.parser import load_pack  # noqa: E402

FILE_NAME = "transcripts.json"


def build_excerpts(pack: Path, run_dir: Path) -> dict:
    data = json.loads((run_dir / "promos.json").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "processing_summary.json").read_text(encoding="utf-8"))
    expected = Path(summary.get("input_file") or "").name
    if expected and pack.name != expected:
        raise SystemExit(f"This run was made from '{expected}', not '{pack.name}'.")
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pack", required=True, type=Path)
    parser.add_argument("--run", required=True, type=Path)
    args = parser.parse_args()
    result = build_excerpts(args.pack, args.run)
    target = args.run / FILE_NAME
    # LF line endings, like every other result file, so the output is the same on every system.
    target.write_bytes((json.dumps(result, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
    cues = sum(len(s["cues"]) for clip in result["clips"].values() for s in clip["segments"])
    print(f"{target}: {len(result['clips'])} clips, {cues} cues, {target.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
