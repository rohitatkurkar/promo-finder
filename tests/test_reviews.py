"""Human review storage: saving, history, several reviewers, validation, export, and leaving run outputs untouched."""

import csv
import hashlib
import io
import json

import pytest
from conftest import FakeProvider, write_env
from pydantic import ValidationError

from promo_finder.pipeline import run_ai_pipeline, run_basic_pipeline
from promo_finder.reviews import (
    EXPORT_COLUMNS,
    append_review,
    comparison_rows,
    latest_reviews,
    load_reviews,
    new_review,
    review_by,
    review_store_path,
    rows_to_csv,
    rows_to_json,
)

GOOD = {"hook_quality": 4, "cliffhanger_quality": 3, "clarity": 5, "overall_quality": 4, "would_publish": "maybe",
        "comments": "Strong opening, ending a little soft."}


@pytest.fixture
def basic_run(sample_zip, tmp_path):
    run_dir = tmp_path / "runs" / "basic_sample"
    run_basic_pipeline(sample_zip, run_dir)
    promos = json.loads((run_dir / "promos.json").read_text(encoding="utf-8"))["promos"]
    return run_dir, promos


def folder_fingerprint(folder):
    return {str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(folder.rglob("*")) if path.is_file()}


def save(run_dir, promo, reviewer="itesh", **changes):
    record = new_review(run_dir, promo, "basic", reviewer, **{**GOOD, **changes})
    append_review(review_store_path(run_dir.parent), record)
    return record


def test_review_is_saved_outside_the_run_folder_and_reloads(basic_run):
    run_dir, promos = basic_run
    record = save(run_dir, promos[0])
    path = review_store_path(run_dir.parent)
    assert path == run_dir.parent / "human_reviews" / "human_reviews.jsonl"
    assert not (path.parent / "promos.json").exists()  # The app's run list ignores this folder.
    assert b"\r\n" not in path.read_bytes()
    records, problems = load_reviews(path)
    assert problems == [] and records == [record]
    saved = records[0]
    assert (saved.run_id, saved.clip_key, saved.promo_id) == (run_dir.name, promos[0]["clip_key"], promos[0]["promo_id"])
    assert saved.episode == promos[0]["segments"][0]["episode"]
    assert saved.start_timestamp == promos[0]["segments"][0]["start_timestamp"]


def test_saving_again_replaces_the_review_but_keeps_the_history(basic_run):
    run_dir, promos = basic_run
    save(run_dir, promos[0], overall_quality=2)
    save(run_dir, promos[0], reviewer=" ITESH ", overall_quality=5)  # Same person, typed differently.
    records, _ = load_reviews(review_store_path(run_dir.parent))
    assert len(records) == 2
    latest = latest_reviews(records, run_dir.name)
    assert len(latest) == 1
    assert review_by(latest, run_dir.name, promos[0]["clip_key"], "itesh").overall_quality == 5


def test_two_reviewers_are_kept_apart(basic_run):
    run_dir, promos = basic_run
    save(run_dir, promos[0], reviewer="itesh", hook_quality=5)
    save(run_dir, promos[0], reviewer="editor_2", hook_quality=2)
    latest = latest_reviews(load_reviews(review_store_path(run_dir.parent))[0], run_dir.name)
    assert review_by(latest, run_dir.name, promos[0]["clip_key"], "itesh").hook_quality == 5
    assert review_by(latest, run_dir.name, promos[0]["clip_key"], "editor_2").hook_quality == 2
    rows = comparison_rows(promos, run_dir, "basic", latest, include_unreviewed=False)
    assert sorted(row["reviewer"] for row in rows) == ["editor_2", "itesh"]


def test_reviews_of_another_run_are_not_mixed_in(basic_run, sample_zip):
    run_dir, promos = basic_run
    other = run_dir.parent / "basic_other"
    run_basic_pipeline(sample_zip, other)
    save(other, promos[0])
    latest = latest_reviews(load_reviews(review_store_path(run_dir.parent))[0], run_dir.name)
    assert latest == {}


@pytest.mark.parametrize("changes", [
    {"hook_quality": 0}, {"clarity": 6}, {"overall_quality": True}, {"cliffhanger_quality": "3"}, {"hook_quality": 3.5},
    {"would_publish": "probably"}, {"reviewer": "   "},
])
def test_invalid_reviews_are_rejected(basic_run, changes):
    run_dir, promos = basic_run
    reviewer = changes.pop("reviewer", "itesh")
    with pytest.raises(ValidationError):
        new_review(run_dir, promos[0], "basic", reviewer, **{**GOOD, **changes})


def test_a_damaged_line_is_skipped_and_reported(basic_run):
    run_dir, promos = basic_run
    save(run_dir, promos[0])
    path = review_store_path(run_dir.parent)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("{not json\n")
        handle.write(json.dumps({"reviewer": "x", "hook_quality": 9}) + "\n")
    save(run_dir, promos[1])
    records, problems = load_reviews(path)
    assert len(records) == 2
    assert len(problems) == 2 and "Line 2" in problems[0] and "Line 3" in problems[1]


def test_reviewing_never_changes_the_run_outputs(basic_run):
    run_dir, promos = basic_run
    before = folder_fingerprint(run_dir)
    for promo in promos:
        save(run_dir, promo)
    latest = latest_reviews(load_reviews(review_store_path(run_dir.parent))[0], run_dir.name)
    rows = comparison_rows(promos, run_dir, "basic", latest)
    rows_to_csv(rows)
    rows_to_json(rows)
    assert folder_fingerprint(run_dir) == before
    stored = json.loads((run_dir / "promos.json").read_text(encoding="utf-8"))["promos"]
    assert all(promo["human_review"]["status"] == "not_reviewed" for promo in stored)


def test_comparison_lists_every_promo_in_rank_order_with_ai_figures(basic_run):
    run_dir, promos = basic_run
    save(run_dir, promos[1])
    rows = comparison_rows(promos, run_dir, "basic", latest_reviews(load_reviews(review_store_path(run_dir.parent))[0]))
    assert [row["promo_id"] for row in rows] == [promo["promo_id"] for promo in promos]
    assert [row["ai_rank"] for row in rows] == [promo["global_rank"] for promo in promos]
    assert [row["ai_total_score"] for row in rows] == [promo["total_score"] for promo in promos]
    assert rows[1]["overall_quality"] == GOOD["overall_quality"] and rows[0]["reviewer"] is None
    assert all(row["ai_hook_rating"] is None for row in rows)  # Basic mode makes no ratings.


def test_ai_ratings_are_read_from_the_ai_run(sample_zip, tmp_path):
    run_dir = tmp_path / "runs" / "ai_sample"
    run_ai_pipeline(sample_zip, run_dir, env_path=write_env(tmp_path / ".env"), cache_dir=tmp_path / "cache",
                    transport=FakeProvider(hook_rating=4, ending_rating=5), sleep=lambda _: None)
    promos = json.loads((run_dir / "promos.json").read_text(encoding="utf-8"))["promos"]
    assert promos
    rows = comparison_rows(promos, run_dir, "ai_assisted", {})
    assert all(row["ai_hook_rating"] == 4 and row["ai_ending_rating"] == 5 and row["ai_clarity_rating"] == 4 for row in rows)


def test_export_matches_the_saved_reviews(basic_run):
    run_dir, promos = basic_run
    save(run_dir, promos[0], comments='Has a comma, a "quote"\nand a new line.')
    save(run_dir, promos[1], reviewer="editor_2", would_publish="no")
    latest = latest_reviews(load_reviews(review_store_path(run_dir.parent))[0], run_dir.name)
    rows = comparison_rows(promos, run_dir, "basic", latest, include_unreviewed=False)
    from_csv = list(csv.DictReader(io.StringIO(rows_to_csv(rows))))
    from_json = json.loads(rows_to_json(rows))
    assert list(from_csv[0]) == EXPORT_COLUMNS and list(from_json[0]) == EXPORT_COLUMNS
    assert len(from_csv) == len(from_json) == 2
    assert from_csv[0]["comments"] == from_json[0]["comments"] == 'Has a comma, a "quote"\nand a new line.'
    assert [row["would_publish"] for row in from_json] == ["maybe", "no"]
    assert from_json[0]["hook_quality"] == 4 and from_csv[0]["hook_quality"] == "4"


def test_a_run_regenerated_after_review_is_flagged(basic_run):
    run_dir, promos = basic_run
    save(run_dir, promos[0])
    promos_file = run_dir / "promos.json"
    promos_file.write_text(promos_file.read_text(encoding="utf-8") + " ", encoding="utf-8")  # Simulates a rerun.
    latest = latest_reviews(load_reviews(review_store_path(run_dir.parent))[0], run_dir.name)
    rows = comparison_rows(promos, run_dir, "basic", latest, include_unreviewed=False)
    assert rows[0]["run_changed_since_review"] is True
