"""Review stores: Supabase with an outbox for outages, and the original file store."""

import hashlib
import json

import pytest

from promo_finder.cloud import SupabaseClient, SupabaseConfig
from promo_finder.pipeline import run_basic_pipeline
from promo_finder.reviews import HumanReviewRecord, latest_reviews, new_review, review_by
from promo_finder.stores import FileReviewStore, SupabaseReviewStore
from conftest import ROOT, SUPABASE_TEST_KEY, SUPABASE_TEST_URL, FakeSupabase

ROOT_DEMO = ROOT / "demo_runs"

MINE = hashlib.sha256(b"my-private-link-code-0001").hexdigest()
THEIRS = hashlib.sha256(b"their-private-link-code-02").hexdigest()


@pytest.fixture
def basic_run(sample_zip, tmp_path):
    run_dir = tmp_path / "runs" / "basic_run"
    run_basic_pipeline(sample_zip, run_dir)
    return run_dir, json.loads((run_dir / "promos.json").read_text(encoding="utf-8"))["promos"]


@pytest.fixture
def cloud(tmp_path):
    fake = FakeSupabase()
    client = SupabaseClient(SupabaseConfig(SUPABASE_TEST_URL, SUPABASE_TEST_KEY), transport=fake, sleep=lambda _: None)
    return fake, SupabaseReviewStore(client, tmp_path / "outbox" / "pending.jsonl")


def review(run_dir, promo, reviewer_hash=MINE, name="Rohit", overall=4):
    return new_review(run_dir, promo, "basic", name, reviewer_hash=reviewer_hash, hook_quality=4, cliffhanger_quality=3,
                      clarity=5, overall_quality=overall, would_publish="yes", comments="Tense.")


def test_a_review_is_saved_and_only_its_reviewer_sees_it(basic_run, cloud):
    run_dir, promos = basic_run
    fake, store = cloud
    assert store.save(review(run_dir, promos[0])).in_cloud
    assert fake.rows[0]["reviewer_name"] == "Rohit" and fake.rows[0]["reviewer_hash"] == MINE
    mine, problems = store.load(run_dir.name, MINE)
    assert problems == [] and len(mine) == 1 and mine[0].comments == "Tense."
    assert store.load(run_dir.name, THEIRS)[0] == []
    assert store.load(run_dir.name, None)[0] == []
    assert store.load("another_run", MINE)[0] == []


def test_the_same_name_with_two_links_stays_two_reviewers(basic_run, cloud):
    run_dir, promos = basic_run
    _, store = cloud
    store.save(review(run_dir, promos[0], MINE, overall=5))
    store.save(review(run_dir, promos[0], THEIRS, overall=1))
    mine = latest_reviews(store.load(run_dir.name, MINE)[0], run_dir.name)
    assert review_by(mine, run_dir.name, promos[0]["clip_key"], MINE).overall_quality == 5


def test_saving_again_makes_the_newest_review_current(basic_run, cloud):
    run_dir, promos = basic_run
    _, store = cloud
    store.save(review(run_dir, promos[0], overall=2))
    store.save(review(run_dir, promos[0], overall=5))
    records = store.load(run_dir.name, MINE)[0]
    assert len(records) == 2
    assert review_by(latest_reviews(records, run_dir.name), run_dir.name, promos[0]["clip_key"], MINE).overall_quality == 5


def test_an_outage_keeps_the_review_and_sends_it_later_once(basic_run, cloud):
    run_dir, promos = basic_run
    fake, store = cloud
    fake.down = True
    result = store.save(review(run_dir, promos[0]))
    assert not result.in_cloud and "could not be reached" in result.message
    assert fake.rows == [] and store.outbox_path.exists()
    records, problems = store.load(run_dir.name, MINE)  # Still down: the queued review is shown, with a note.
    assert len(records) == 1 and any("kept on this server" in problem for problem in problems)
    fake.down = False
    records, problems = store.load(run_dir.name, MINE)  # Back: sent, outbox emptied.
    assert problems == [] and len(records) == 1 and len(fake.rows) == 1 and not store.outbox_path.exists()
    store.flush()
    store.save(review(run_dir, promos[1]))
    assert len(fake.rows) == 2  # Nothing sent twice.


def test_a_review_id_comes_back_as_written(basic_run, cloud):
    run_dir, promos = basic_run
    _, store = cloud
    record = review(run_dir, promos[0])
    store.save(record)
    assert "-" in store.client.select("reviews", {"run_id": run_dir.name})[0]["review_id"]  # The database form.
    assert store.load(run_dir.name, MINE)[0][0].review_id == record.review_id


def test_a_database_review_needs_a_link_hash(basic_run, cloud):
    run_dir, promos = basic_run
    with pytest.raises(ValueError):
        cloud[1].save(review(run_dir, promos[0], reviewer_hash=None))


def test_the_file_store_keeps_its_old_behaviour(basic_run, tmp_path):
    run_dir, promos = basic_run
    store = FileReviewStore(tmp_path / "reviews.jsonl")
    store.save(review(run_dir, promos[0], reviewer_hash=None, name="itesh"))
    records, problems = store.load(run_dir.name)
    assert problems == [] and records[0].reviewer == "itesh" and records[0].reviewer_hash is None
    assert review_by(latest_reviews(records, run_dir.name), run_dir.name, promos[0]["clip_key"], " ITESH ") is not None


def test_a_review_from_before_link_hashes_still_loads():
    old = {"schema_version": "review_v1", "review_id": "a" * 32, "saved_at": "2026-11-09T10:00:00Z", "reviewer": "Rohit",
           "run_id": "r", "promos_sha256": "x", "selection_method": "ai_assisted", "clip_key": "E01_C1__C2", "promo_id": "P0001",
           "episode": 1, "start_timestamp": "00:01.00", "end_timestamp": "00:30.00", "hook_quality": 4,
           "cliffhanger_quality": 4, "clarity": 4, "overall_quality": 4, "would_publish": "yes", "comments": ""}
    assert HumanReviewRecord.model_validate(old).reviewer_hash is None
    with pytest.raises(ValueError):
        HumanReviewRecord.model_validate(dict(old, reviewer_hash="not-a-hash"))


# Runs kept in Supabase.

from promo_finder.cloud import CloudError  # noqa: E402
from promo_finder.excerpts import write_excerpts  # noqa: E402
from promo_finder.stores import SupabaseRunStore, run_files  # noqa: E402


@pytest.fixture
def run_store(cloud):
    fake, review_store = cloud
    return fake, SupabaseRunStore(review_store.client)


@pytest.fixture
def finished_run(basic_run, sample_zip):
    run_dir, promos = basic_run
    write_excerpts(sample_zip, run_dir)
    return run_dir, promos


def _files(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


def test_a_finished_run_is_stored_under_its_owner_and_comes_back_identical(finished_run, run_store, tmp_path):
    run_dir, _ = finished_run
    fake, store = run_store
    assert store.save(run_dir, MINE).in_cloud
    names = run_files(run_dir)
    assert "transcripts.json" in names and "promos.json" in names and "checkpoint.json" not in names
    assert set(fake.objects) == {f"promo-data/{MINE}/{run_dir.name}/{name}" for name in names}
    row = fake.tables["runs"][0]
    assert row["id"] == run_dir.name and row["owner_hash"] == MINE and row["mode"] == "basic" and row["files"] == names
    copy = store.download(store.list(MINE)[0], MINE, tmp_path / "copies" / run_dir.name)
    assert copy.name == run_dir.name  # Reviews refer to runs by this name.
    original = _files(run_dir)
    assert _files(copy) == {name: original[name] for name in names}


def test_another_link_cannot_list_or_open_a_run(finished_run, run_store, tmp_path):
    run_dir, _ = finished_run
    _, store = run_store
    store.save(run_dir, MINE)
    assert store.list(THEIRS) == []
    with pytest.raises(PermissionError):
        store.download(store.list(MINE)[0], THEIRS, tmp_path / "theirs" / run_dir.name)
    assert not (tmp_path / "theirs").exists()


def test_a_failed_save_adds_no_row_and_a_retry_completes_it(finished_run, run_store):
    run_dir, _ = finished_run
    fake, store = run_store
    fake.fail_on = "/storage/"
    result = store.save(run_dir, MINE)
    assert not result.in_cloud and "network" in result.message and fake.tables["runs"] == []
    fake.fail_on = None
    assert store.save(run_dir, MINE).in_cloud and store.save(run_dir, MINE).in_cloud
    assert len(fake.tables["runs"]) == 1  # Saving twice keeps one row.


def test_a_failed_download_leaves_no_half_run(finished_run, run_store, tmp_path):
    run_dir, _ = finished_run
    fake, store = run_store
    store.save(run_dir, MINE)
    row = store.list(MINE)[0]
    fake.fail_on = "/report.md"
    with pytest.raises(CloudError):
        store.download(row, MINE, tmp_path / "copies" / run_dir.name)
    assert not (tmp_path / "copies" / run_dir.name).exists()
    assert list((tmp_path / "copies").iterdir()) == []  # No leftover side folder either.


def test_a_file_name_cannot_point_outside_the_run_folder(finished_run, run_store, tmp_path):
    run_dir, _ = finished_run
    _, store = run_store
    store.save(run_dir, MINE)
    row = dict(store.list(MINE)[0])
    row["files"] = row["files"] + ["../escaped.json"]
    store.download(row, MINE, tmp_path / "copies" / run_dir.name)
    assert not (tmp_path / "copies" / "escaped.json").exists()


def test_an_ai_run_keeps_the_evaluations_of_its_recommended_clips_only(tmp_path):
    folder = ROOT_DEMO / "ai_trial_E01_groq_2026-11-08"
    names = run_files(folder)
    promos = json.loads((folder / "promos.json").read_text(encoding="utf-8"))["promos"]
    assert {name for name in names if name.startswith("evaluations/")} == {f"evaluations/{p['clip_key']}.json" for p in promos}
