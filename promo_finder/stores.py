"""Where human reviews and finished runs are kept: files on this computer, or Supabase on a hosted app.

Both stores give the interface the same two calls, load and save, so the review screen does not
care which one is in use.

The Supabase store never loses a review to an outage. If the database cannot be reached, the review
goes to a local "to send" file (the outbox) and is sent on the next save or page load. Each review
has its own review_id and the database skips one it already has, so sending twice is harmless.
The outbox lives on the app's disk, which a hosted app loses on restart, so the page says so.
"""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from .cloud import CloudError, SupabaseClient
from .reviews import HumanReviewRecord, append_review, load_reviews

TABLE = "reviews"


@dataclass
class SaveResult:
    in_cloud: bool  # False: kept in the local outbox for now (Supabase store), or saved to the file (file store).
    message: str = ""


class FileReviewStore:
    """The original behaviour: one append-only JSONL file next to the runs."""

    cloud = False

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.location = str(self.path)

    def load(self, run_id: str, reviewer_hash: str | None = None) -> tuple[list[HumanReviewRecord], list[str]]:
        records, problems = load_reviews(self.path)
        return [record for record in records if record.run_id == run_id], problems

    def save(self, record: HumanReviewRecord) -> SaveResult:
        append_review(self.path, record)
        return SaveResult(in_cloud=False)


def _to_row(record: HumanReviewRecord) -> dict:
    row = record.model_dump()
    row["reviewer_name"] = row.pop("reviewer")
    return row


def _from_row(row: dict) -> HumanReviewRecord:
    data = dict(row)
    data["reviewer"] = data.pop("reviewer_name")
    data["review_id"] = uuid.UUID(str(data["review_id"])).hex  # The database adds dashes; the app writes none.
    return HumanReviewRecord.model_validate(data)


class SupabaseReviewStore:
    cloud = True
    location = "this app's Supabase database"

    def __init__(self, client: SupabaseClient, outbox_path: str | Path):
        self.client = client
        self.outbox_path = Path(outbox_path)

    # The outbox: reviews saved while the database was unreachable.

    def _pending(self) -> list[HumanReviewRecord]:
        records, _ = load_reviews(self.outbox_path)
        return records

    def _rewrite_outbox(self, records: list[HumanReviewRecord]) -> None:
        if not records:
            self.outbox_path.unlink(missing_ok=True)
            return
        temporary = self.outbox_path.with_name(f"{self.outbox_path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text("".join(json.dumps(record.model_dump(), ensure_ascii=False) + "\n" for record in records),
                             encoding="utf-8", newline="\n")
        temporary.replace(self.outbox_path)

    def flush(self) -> str:
        """Send every queued review. Returns a problem to show, or "" when the outbox is empty."""
        pending = self._pending()
        if not pending:
            return ""
        try:
            self.client.insert(TABLE, [_to_row(record) for record in pending], ignore_duplicates_on="review_id")
        except CloudError as error:
            return (f"{len(pending)} review(s) are kept on this server until the database can be reached "
                    f"({error.kind}). A restart of a hosted app would lose them, so download your reviews to be safe.")
        self._rewrite_outbox([])
        return ""

    def load(self, run_id: str, reviewer_hash: str | None = None) -> tuple[list[HumanReviewRecord], list[str]]:
        """This reviewer's reviews of this run only, oldest first, including any still waiting in the outbox."""
        problems = [problem for problem in [self.flush()] if problem]
        if not reviewer_hash:
            return [], problems
        pending = [record for record in self._pending() if record.run_id == run_id and record.reviewer_hash == reviewer_hash]
        try:
            rows = self.client.select(TABLE, {"run_id": run_id, "reviewer_hash": reviewer_hash}, order="saved_at.asc")
        except CloudError as error:
            problems.append(f"Saved reviews could not be loaded from the database right now ({error.kind}). "
                            "Only reviews kept on this server are shown.")
            return pending, problems
        records: list[HumanReviewRecord] = []
        for row in rows:
            try:
                records.append(_from_row(row))
            except (ValidationError, KeyError, ValueError):
                problems.append(f"A saved review ({row.get('review_id', '?')}) could not be read and was skipped.")
        stored = {record.review_id for record in records}
        return records + [record for record in pending if record.review_id not in stored], problems

    def save(self, record: HumanReviewRecord) -> SaveResult:
        if not record.reviewer_hash:
            raise ValueError("A review saved to the database needs the reviewer's link hash.")
        self.flush()  # Older queued reviews go first, so the newest one stays the latest.
        try:
            self.client.insert(TABLE, [_to_row(record)], ignore_duplicates_on="review_id")
            return SaveResult(in_cloud=True)
        except CloudError as error:
            append_review(self.outbox_path, record)
            return SaveResult(in_cloud=False, message=(
                f"The database could not be reached ({error.kind}), so this review is kept on this server for now and "
                "will be sent automatically on your next save or page load. A restart of a hosted app would lose it, "
                "so download your reviews to be safe."))


# Runs. A finished run's files go to the private bucket under <owner_hash>/<run_id>/, then one row is added to the
# runs table. The row comes last, so a row always means a complete copy. Runs are listed and opened only by owner.

RUNS_TABLE = "runs"
BUCKET = "promo-data"
# The files the interface reads to show a run (the same set the bundled runs keep), plus each recommended clip's
# evaluation, which holds the AI's clarity rating.
RUN_FILES = ["promos.json", "processing_summary.json", "promos.csv", "report.md", "top_twenty_human_review_sheet.csv",
             "transcripts.json"]
CONTENT_TYPES = {".json": "application/json", ".csv": "text/csv", ".md": "text/markdown"}


def run_files(run_dir: str | Path) -> list[str]:
    """The files of a finished run worth keeping, as paths relative to the run folder."""
    run_dir = Path(run_dir)
    names = [name for name in RUN_FILES if (run_dir / name).is_file()]
    promos = json.loads((run_dir / "promos.json").read_text(encoding="utf-8"))["promos"]
    names += [f"evaluations/{promo['clip_key']}.json" for promo in promos
              if (run_dir / "evaluations" / f"{promo['clip_key']}.json").is_file()]
    return names


class SupabaseRunStore:
    def __init__(self, client: SupabaseClient, bucket: str = BUCKET):
        self.client = client
        self.bucket = bucket

    def save(self, run_dir: str | Path, owner_hash: str) -> SaveResult:
        """Copy a finished run to the database. Safe to repeat: files are replaced and the row is added once."""
        run_dir = Path(run_dir)
        names = run_files(run_dir)
        summary = json.loads((run_dir / "processing_summary.json").read_text(encoding="utf-8"))
        try:
            for name in names:
                self.client.upload(self.bucket, f"{owner_hash}/{run_dir.name}/{name}", (run_dir / name).read_bytes(),
                                   CONTENT_TYPES.get(Path(name).suffix, "application/octet-stream"))
            self.client.insert(RUNS_TABLE, [{
                "id": run_dir.name,
                "owner_hash": owner_hash,
                "mode": summary.get("mode", "basic"),
                "title": summary.get("title", ""),
                "input_file": summary.get("input_file", ""),
                "complete": summary.get("complete", True) is not False and not summary.get("stopped_because"),
                "stopped_because": summary.get("stopped_because"),
                "episodes_in_pack": summary.get("episodes_in_pack"),
                "episodes_processed": summary.get("episodes_processed"),
                "recommended_clips": summary.get("recommended_clips"),
                "processing_seconds": summary.get("processing_seconds"),
                "files": names,
            }], ignore_duplicates_on="id")
        except CloudError as error:
            return SaveResult(in_cloud=False, message=f"{error.kind}: {error.detail}")
        return SaveResult(in_cloud=True)

    def list(self, owner_hash: str) -> list[dict]:
        """This owner's saved runs, newest first. Raises CloudError when the database cannot be reached."""
        rows = self.client.select(RUNS_TABLE, {"owner_hash": owner_hash}, order="created_at.desc")
        return [row for row in rows if row.get("owner_hash") == owner_hash]

    def download(self, row: dict, owner_hash: str, destination: str | Path) -> Path:
        """Fetch a saved run into destination (named after the run, so reviews keep pointing at it).

        Only the owner's own run is fetched. Files are gathered in a side folder and moved into place at the end,
        so a failed download never looks like a complete run. Raises CloudError or PermissionError.
        """
        if row.get("owner_hash") != owner_hash:
            raise PermissionError("This run belongs to another private link.")
        destination = Path(destination)
        if (destination / "promos.json").is_file():
            return destination
        staging = destination.with_name(f"{destination.name}.{uuid.uuid4().hex}.partial")
        try:
            for name in row["files"]:
                if Path(name).is_absolute() or ".." in Path(name).parts:
                    continue  # Never write outside the run folder, whatever the row says.
                target = staging / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(self.client.download(self.bucket, f"{owner_hash}/{row['id']}/{name}"))
            if not (staging / "promos.json").is_file():
                raise CloudError("rejected", "The saved run has no promos.json.")
            if destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
            staging.replace(destination)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return destination
