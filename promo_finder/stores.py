"""Where human reviews are kept: a file on this computer, or the Supabase database on a hosted app.

Both stores give the interface the same two calls, load and save, so the review screen does not
care which one is in use.

The Supabase store never loses a review to an outage. If the database cannot be reached, the review
goes to a local "to send" file (the outbox) and is sent on the next save or page load. Each review
has its own review_id and the database skips one it already has, so sending twice is harmless.
The outbox lives on the app's disk, which a hosted app loses on restart, so the page says so.
"""

from __future__ import annotations

import json
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
