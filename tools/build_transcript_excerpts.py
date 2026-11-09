"""Save the screenplay cues of each recommended clip next to a bundled run, so the hosted app can show them.

Only the cues that play inside each promo's own clip are written, taken unchanged from the parsed screenplay.
The rest of the screenplay is not copied. No model is called. The work is done by promo_finder/excerpts.py,
which the app also uses for every new run.

    python tools/build_transcript_excerpts.py --pack PATH_TO_PACK.zip --run demo_runs/RUN_FOLDER
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from promo_finder.excerpts import FILE_NAME, build_excerpts, write_excerpts  # noqa: E402,F401


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pack", required=True, type=Path)
    parser.add_argument("--run", required=True, type=Path)
    args = parser.parse_args()
    try:
        target = write_excerpts(args.pack, args.run)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    print(f"{target}: {target.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
