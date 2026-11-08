"""Check that no confidential screenplay text is in the files about to be published.

Run this before sharing anything:
    python tools/check_confidentiality.py --pack PATH_TO_ZIP --check FOLDER_OR_ZIP

It looks for any dialogue or action line from the pack, any episode logline, the
show's title, and character names. It exits with an error if it finds a match.
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from promo_finder.masking import pack_name_words  # noqa: E402
from promo_finder.parser import load_pack  # noqa: E402
from promo_finder.pipeline import pack_title  # noqa: E402

MIN_WORDS_IN_LINE = 5
TEXT_SUFFIXES = {".py", ".md", ".txt", ".csv", ".json", ".toml", ".ini", ".example", ".html", ".yml", ".yaml", ""}
# outputs/ holds local results and is never published. Scan the final ZIP as well.
SKIP_FOLDERS = {".venv", "__pycache__", ".pytest_cache", ".git", "outputs"}


def normalise(text: str) -> str:
    # Keep everything. word_list() drops [bracketed] text, which would hide Python lists from this scan.
    return " ".join(re.findall(r"[a-z']+", text.lower()))


def read_targets(path: Path) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if path.is_file() and path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if name.endswith("/"):
                    continue
                suffix = Path(name).suffix.lower()
                if suffix == ".zip":
                    found.append((name, ""))
                elif suffix in TEXT_SUFFIXES:
                    found.append((name, archive.read(name).decode("utf-8", errors="ignore")))
        return found
    for file_path in sorted(path.rglob("*")):
        if not file_path.is_file() or any(part in SKIP_FOLDERS or part.startswith(".venv") for part in file_path.parts):
            continue
        if file_path.suffix.lower() in TEXT_SUFFIXES:
            found.append((str(file_path.relative_to(path)), file_path.read_text(encoding="utf-8", errors="ignore")))
    return found


def scan(pack: Path, target: Path) -> list[str]:
    episodes, _ = load_pack(pack)
    lines = set()
    for episode in episodes:
        for cue in episode.cues:
            if cue.kind in ("dialogue", "action"):
                clean = normalise(cue.text)
                if len(clean.split()) >= MIN_WORDS_IN_LINE:
                    lines.add(clean)
        if episode.logline:
            lines.add(normalise(episode.logline))
    names = pack_name_words(episodes)
    name_pattern = re.compile(r"\b(" + "|".join(sorted(map(re.escape, names))) + r")\b", re.IGNORECASE)
    title = normalise(pack_title(pack))

    problems: list[str] = []
    for name, text in read_targets(target):
        clean = normalise(text)
        if title and title in clean:
            problems.append(f"{name}: contains the show's title")
        hits = [line for line in lines if line in clean]
        if hits:
            problems.append(f"{name}: contains {len(hits)} screenplay line(s), for example: {hits[0][:50]}...")
        name_hits = sorted({match.lower() for match in name_pattern.findall(text)})
        if name_hits:
            problems.append(f"{name}: contains character name(s): {', '.join(name_hits[:8])}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", required=True)
    parser.add_argument("--check", required=True)
    args = parser.parse_args()
    problems = scan(Path(args.pack), Path(args.check))
    if problems:
        print("CONFIDENTIALITY PROBLEMS FOUND:")
        for problem in problems:
            print(" -", problem)
        return 1
    print(f"Clean: no screenplay text, title or character names found in {args.check}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
