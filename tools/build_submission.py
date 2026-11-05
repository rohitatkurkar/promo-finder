"""Build the prototype ZIP and the raw outputs ZIP.

The prototype ZIP refuses to build if the confidentiality scan finds anything.
The raw outputs ZIP contains screenplay quotations, so share it privately only.
Raw files are copied exactly as they were produced.
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from check_confidentiality import scan  # noqa: E402

EXCLUDED_FOLDERS = {".venv", "__pycache__", ".pytest_cache", ".git", "outputs", "inputs", "private", ".claude"}
# The candidate's own interview notes stay out by default, because the people reading this ZIP are the interviewers.
PRIVATE_NOTES = {"INTERVIEW_PREP.md", "WALKTHROUGH_SCRIPT.md"}
EXCLUDED_FILES = {".env", ".DS_Store", "secrets.toml"}
# These hold the screenplay or raw model text, so they never leave the computer.
RAW_EXCLUDED_FILES = {"screenplay_with_cue_ids.html", "episode_index.csv", ".DS_Store"}
RAW_EXCLUDED_FOLDERS = {"llm_cache"}


def build_prototype(target: Path, pack: Path, include_private_notes: bool = False) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    left_out = EXCLUDED_FILES if include_private_notes else EXCLUDED_FILES | PRIVATE_NOTES
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(ROOT.rglob("*")):
            relative = path.relative_to(ROOT)
            if not path.is_file() or path.name in left_out or set(relative.parts) & EXCLUDED_FOLDERS:
                continue
            if path.suffix == ".zip" and relative != Path("sample_input/synthetic_show.zip"):
                continue
            archive.write(path, Path("promo_finder_prototype") / relative)
    problems = scan(pack, target)
    if problems:
        target.unlink()
        print("REFUSED: the prototype ZIP would leak confidential text:")
        for problem in problems:
            print(" -", problem)
        raise SystemExit(1)
    print(f"Prototype ZIP is clean: {target} ({target.stat().st_size // 1024} KB)")


def build_raw_outputs(target: Path, folders: list[Path]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for folder in folders:
            if folder.is_file():
                archive.write(folder, Path("raw_outputs") / folder.name)
                count += 1
                continue
            for path in sorted(folder.rglob("*")):
                relative = path.relative_to(folder)
                if not path.is_file() or path.name in RAW_EXCLUDED_FILES or set(relative.parts) & RAW_EXCLUDED_FOLDERS:
                    continue
                archive.write(path, Path("raw_outputs") / folder.name / relative)
                count += 1
    print(f"Raw outputs ZIP: {target} with {count} files. It quotes the screenplay, so share it privately only.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", required=True, help="The private screenplay ZIP, used only to scan for leaks")
    parser.add_argument("--out", required=True)
    parser.add_argument("--raw", nargs="*", default=[], help="Run folders and files to include in the raw outputs ZIP")
    parser.add_argument("--include-private-notes", action="store_true", help="Also put INTERVIEW_PREP.md and WALKTHROUGH_SCRIPT.md in the prototype ZIP")
    args = parser.parse_args()
    out = Path(args.out)
    build_prototype(out / "prototype.zip", Path(args.pack), args.include_private_notes)
    if args.raw:
        build_raw_outputs(out / "raw_outputs.zip", [Path(item) for item in args.raw])
    return 0


if __name__ == "__main__":
    sys.exit(main())
