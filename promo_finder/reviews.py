"""Human reviews of recommended promos, kept on this computer.

A person rates each promo after reading it. Reviews are stored apart from the run
they describe, so the AI's original outputs are never changed:

    <runs folder>/human_reviews/human_reviews.jsonl

One line is one saved review. Lines are only ever added, never edited, so the file
also keeps the history. When the same reviewer saves the same promo twice, the later
line is the current review.

A review is tied to a run by the run folder's name, and to a promo by its clip_key,
which is built from the hook and ending cue IDs. The promo_id (P0001, B0003...) is
kept for reading, but it is not a stable key, because it is given by rank. The run's
promos.json fingerprint is saved too, so a run regenerated after review is noticed.

Nothing here calls a model or feeds back into discovery, scoring or ranking.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

REVIEW_SCHEMA_VERSION = "review_v1"
REVIEW_FOLDER = "human_reviews"
REVIEW_FILE = "human_reviews.jsonl"

Rating = Annotated[int, Field(ge=1, le=5, strict=True)]
Verdict = Literal["yes", "no", "maybe"]

EXPORT_COLUMNS = [
    "run_id", "selection_method", "promo_id", "clip_key", "episode", "start_timestamp", "end_timestamp",
    "ai_rank", "ai_total_score", "ai_hook_rating", "ai_ending_rating", "ai_clarity_rating", "ai_first_post",
    "reviewer", "saved_at", "hook_quality", "cliffhanger_quality", "clarity", "overall_quality", "would_publish",
    "comments", "run_changed_since_review", "review_id",
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class HumanReviewRecord(BaseModel):
    """One person's review of one promo in one run."""

    schema_version: str = REVIEW_SCHEMA_VERSION
    review_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    saved_at: str = Field(default_factory=_now)
    reviewer: str = Field(min_length=1, max_length=80)
    run_id: str = Field(min_length=1)
    promos_sha256: str
    selection_method: str
    clip_key: str = Field(min_length=1)
    promo_id: str
    episode: int
    start_timestamp: str
    end_timestamp: str
    hook_quality: Rating
    cliffhanger_quality: Rating
    clarity: Rating
    overall_quality: Rating
    would_publish: Verdict
    comments: str = Field(default="", max_length=5000)

    @field_validator("reviewer", "comments", mode="before")
    @classmethod
    def _strip(cls, value):
        return value.strip() if isinstance(value, str) else value


def review_store_path(runs_folder: str | Path) -> Path:
    """Where the reviews for every run in this folder are kept."""
    return Path(runs_folder) / REVIEW_FOLDER / REVIEW_FILE


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def new_review(run_dir: str | Path, promo: dict, selection_method: str, reviewer: str, **ratings) -> HumanReviewRecord:
    """Build a review for a promo of this run. Raises ValidationError if a field is missing or out of range."""
    run_dir = Path(run_dir)
    segment = promo["segments"][0]
    return HumanReviewRecord(
        reviewer=reviewer,
        run_id=run_dir.name,
        promos_sha256=file_sha256(run_dir / "promos.json"),
        selection_method=selection_method,
        clip_key=promo["clip_key"],
        promo_id=promo["promo_id"],
        episode=segment["episode"],
        start_timestamp=segment["start_timestamp"],
        end_timestamp=segment["end_timestamp"],
        **ratings,
    )


def append_review(path: str | Path, record: HumanReviewRecord) -> None:
    """Add one review as a new line. Earlier lines are never rewritten."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record.model_dump(), ensure_ascii=False) + "\n")


def load_reviews(path: str | Path) -> tuple[list[HumanReviewRecord], list[str]]:
    """Read every saved review. A damaged line is skipped and reported, never fatal."""
    path = Path(path)
    records: list[HumanReviewRecord] = []
    problems: list[str] = []
    if not path.exists():
        return records, problems
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                records.append(HumanReviewRecord.model_validate(json.loads(line)))
            except json.JSONDecodeError:
                problems.append(f"Line {number} is not valid JSON and was skipped.")
            except ValidationError as error:
                fields = ", ".join(str(item["loc"][0]) for item in error.errors() if item.get("loc"))
                problems.append(f"Line {number} has invalid fields ({fields}) and was skipped.")
    return records, problems


def _reviewer_key(name: str) -> str:
    return name.strip().casefold()


def latest_reviews(records: list[HumanReviewRecord], run_id: str | None = None) -> dict[tuple[str, str, str], HumanReviewRecord]:
    """The current review per (run, clip, reviewer). Later lines replace earlier ones."""
    latest: dict[tuple[str, str, str], HumanReviewRecord] = {}
    for record in records:
        if run_id is None or record.run_id == run_id:
            latest[(record.run_id, record.clip_key, _reviewer_key(record.reviewer))] = record
    return latest


def step_clip(options: list[str], shown: str | None, delta: int) -> str:
    """The clip label `delta` places from the one shown, wrapping around. Starts from the first if `shown` is not listed."""
    position = options.index(shown) if shown in options else 0
    return options[(position + delta) % len(options)]


def review_by(latest: dict, run_id: str, clip_key: str, reviewer: str) -> HumanReviewRecord | None:
    return latest.get((run_id, clip_key, _reviewer_key(reviewer)))


def ai_values(promo: dict, run_dir: str | Path) -> dict:
    """The AI's own figures for a promo, read from the run's files and never changed."""
    clarity = None
    evaluation_path = Path(run_dir) / "evaluations" / f"{promo['clip_key']}.json"
    if evaluation_path.exists():
        clarity = json.loads(evaluation_path.read_text(encoding="utf-8")).get("clarity_rating")
    return {
        "ai_rank": promo["global_rank"],
        "ai_total_score": promo["total_score"],
        "ai_hook_rating": promo["hook"].get("rating_out_of_5"),
        "ai_ending_rating": promo["cliffhanger"].get("rating_out_of_5"),
        "ai_clarity_rating": clarity,
        "ai_first_post": bool(promo.get("first_post_recommendation")),
    }


def comparison_rows(promos: list[dict], run_dir: str | Path, selection_method: str,
                    latest: dict[tuple[str, str, str], HumanReviewRecord], include_unreviewed: bool = True) -> list[dict]:
    """One row per promo and reviewer, AI figures beside human ones, in the run's own rank order."""
    run_dir = Path(run_dir)
    run_id = run_dir.name
    current_hash = file_sha256(run_dir / "promos.json")
    by_clip: dict[str, list[HumanReviewRecord]] = {}
    for (record_run, clip_key, _), record in latest.items():
        if record_run == run_id:
            by_clip.setdefault(clip_key, []).append(record)
    rows: list[dict] = []
    for promo in promos:
        segment = promo["segments"][0]
        base = {
            "run_id": run_id, "selection_method": selection_method, "promo_id": promo["promo_id"],
            "clip_key": promo["clip_key"], "episode": segment["episode"],
            "start_timestamp": segment["start_timestamp"], "end_timestamp": segment["end_timestamp"],
            **ai_values(promo, run_dir),
        }
        reviews = sorted(by_clip.get(promo["clip_key"], []), key=lambda record: _reviewer_key(record.reviewer))
        for record in reviews:
            rows.append({**base, "reviewer": record.reviewer, "saved_at": record.saved_at,
                         "hook_quality": record.hook_quality, "cliffhanger_quality": record.cliffhanger_quality,
                         "clarity": record.clarity, "overall_quality": record.overall_quality,
                         "would_publish": record.would_publish, "comments": record.comments,
                         "run_changed_since_review": record.promos_sha256 != current_hash,
                         "review_id": record.review_id})
        if not reviews and include_unreviewed:
            rows.append({**base, **{name: None for name in EXPORT_COLUMNS if name not in base}})
    return rows


def rows_to_csv(rows: list[dict]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=EXPORT_COLUMNS, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({name: "" if row.get(name) is None else row.get(name) for name in EXPORT_COLUMNS})
    return buffer.getvalue()


def rows_to_json(rows: list[dict]) -> str:
    return json.dumps([{name: row.get(name) for name in EXPORT_COLUMNS} for row in rows], indent=2, ensure_ascii=False) + "\n"
