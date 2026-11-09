"""Copy reviews from a local human_reviews.jsonl file into the app's Supabase database.

The reviews are filed under one private link code, so they show up in the hosted app for whoever
opens the app with that link (https://<app>/?k=CODE). The local file is only read, never changed.
Running it twice is harmless: reviews already in the database are skipped.

Without --yes it only reports what it would send. Supabase settings are read from the environment
or from .streamlit/secrets.toml (SUPABASE_URL, SUPABASE_SECRET_KEY); the key is never printed.

    python tools/import_reviews_to_supabase.py --reviews ../private/runs/human_reviews/human_reviews.jsonl --new-link
    python tools/import_reviews_to_supabase.py --reviews ... --link-code CODE --yes
"""

from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from promo_finder.cloud import CloudError, SupabaseClient, supabase_config  # noqa: E402
from promo_finder.reviews import load_reviews  # noqa: E402
from promo_finder.stores import TABLE, _to_row  # noqa: E402


def read_settings() -> dict:
    settings = {}
    secrets_file = ROOT / ".streamlit" / "secrets.toml"
    if secrets_file.is_file():
        settings.update(tomllib.loads(secrets_file.read_text(encoding="utf-8")))
    for name in ("SUPABASE_URL", "SUPABASE_SECRET_KEY"):
        if os.environ.get(name):
            settings[name] = os.environ[name]
    return settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reviews", required=True, type=Path, help="A human_reviews.jsonl file")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--link-code", help="File the reviews under this private link code")
    group.add_argument("--new-link", action="store_true", help="Make a new private link code")
    parser.add_argument("--yes", action="store_true", help="Send them. Without it, nothing is sent.")
    args = parser.parse_args()

    records, problems = load_reviews(args.reviews)
    for problem in problems:
        print("Skipped:", problem)
    code = args.link_code or secrets.token_urlsafe(16)
    reviewer_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
    rows = [_to_row(record.model_copy(update={"reviewer_hash": record.reviewer_hash or reviewer_hash})) for record in records]
    runs = sorted({row["run_id"] for row in rows})
    print(f"{len(rows)} review(s) of run(s) {runs}, filed under link code {code}")
    print(f"Open them in the hosted app with ?k={code} at the end of its address.")
    if not args.yes:
        print("Nothing sent. Add --yes to send them.")
        return 0
    config = supabase_config(read_settings())
    if config is None:
        print("SUPABASE_URL and SUPABASE_SECRET_KEY are not set.")
        return 1
    try:
        SupabaseClient(config).insert(TABLE, rows, ignore_duplicates_on="review_id")
    except CloudError as error:
        print(f"Not sent: {error.kind}. {error.detail}")
        return 1
    print("Sent. Reviews already in the database were skipped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
