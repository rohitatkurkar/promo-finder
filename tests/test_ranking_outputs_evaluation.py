"""Ranking, duplicate removal, JSON and CSV output, tamper detection and comparisons."""

import csv
import json

import pytest
from conftest import dialogue_rows, make_episode
from pydantic import ValidationError

from promo_finder.boundaries import Clip
from promo_finder.evaluation import load_promos, load_reference, mean_best_iou, reference_coverage
from promo_finder.outputs import verify_all, write_promos_csv
from promo_finder.parser import format_timestamp, load_pack
from promo_finder.pipeline import pack_title, run_basic_pipeline
from promo_finder.ranking import Scored, rank_with_variety, remove_duplicates, strength_from_rating
from promo_finder.schema import Promo, verify_promo_against_screenplay
from promo_finder.worksheets import read_reference_sheet, write_reference_kit, write_review_sheet


def scored(episode, start, end, hook="E01_C0001", ending="E01_C0010", value=80):
    clip = Clip(episode, start, end, hook, ending, hook, ending, 0.0)
    return Scored(clip, {name: value for name in ("hook", "ending", "understanding", "emotion", "continuity", "duration")})


def test_duplicates_keep_the_stronger_clip_and_record_the_removal():
    weak = scored(1, 0, 30, "E01_C0001", "E01_C0010", 60)
    strong = scored(1, 2, 32, "E01_C0002", "E01_C0011", 90)
    kept, removed = remove_duplicates([weak, strong])
    assert kept == [strong]
    assert removed[0].clip_key == weak.clip.key and removed[0].kept_key == strong.clip.key


def test_different_moments_in_one_episode_both_survive():
    kept, removed = remove_duplicates([scored(1, 0, 30, "E01_C0001", "E01_C0010"), scored(1, 60, 90, "E01_C0020", "E01_C0030")])
    assert len(kept) == 2 and removed == []


def test_same_hook_or_same_ending_counts_as_duplicate():
    assert len(remove_duplicates([scored(1, 0, 25, "E01_C0001", "E01_C0010"), scored(1, 0, 55, "E01_C0001", "E01_C0030")])[0]) == 1
    assert len(remove_duplicates([scored(1, 0, 55, "E01_C0001", "E01_C0030"), scored(1, 30, 55, "E01_C0009", "E01_C0030")])[0]) == 1


def test_same_times_in_different_episodes_are_not_duplicates():
    assert len(remove_duplicates([scored(1, 0, 30), scored(2, 0, 30, "E02_C0001", "E02_C0010")])[0]) == 2


def test_ranking_prefers_variety_over_one_stretch_of_story():
    ranked = rank_with_variety([
        scored(1, 0, 30, "E01_C0001", "E01_C0010", 90),
        scored(1, 60, 90, "E01_C0020", "E01_C0030", 88),
        scored(9, 0, 30, "E09_C0001", "E09_C0010", 85),
    ])
    assert [item[0].clip.episode for item in ranked] == [1, 9, 1]
    assert ranked[2][1] > 0


def test_strength_labels_only_call_four_and_up_strong():
    assert strength_from_rating(5) == strength_from_rating(4) == "strong"
    assert strength_from_rating(3) == "medium"
    assert strength_from_rating(2) == "weak"
    assert strength_from_rating(None) == "not_rated"


# Whole Basic run, JSON and CSV.

def test_basic_run_is_labelled_clearly_and_makes_no_false_claims(sample_zip, tmp_path):
    summary = run_basic_pipeline(sample_zip, tmp_path / "basic")
    assert summary["episodes_processed"] == 3 and summary["verification_errors"] == []
    promos = load_promos(tmp_path / "basic")
    assert promos
    for promo in promos:
        Promo(**promo)
        assert promo["selection_method"] == "basic"
        assert promo["hook"]["strength"] == "not_rated"
        assert promo["cold_viewer_check"]["result"] == "not_performed"
        assert promo["overall_explanation"].startswith("Signals only")
        assert 20 <= promo["total_duration_seconds"] <= 60
    report = (tmp_path / "basic" / "report.md").read_text()
    assert "Basic selections" in report and "not had any story judgement" in report


def test_basic_ignores_clip_with_a_cliffhanger_sound_only(sample_zip, tmp_path):
    run_basic_pipeline(sample_zip, tmp_path / "basic")
    for promo in load_promos(tmp_path / "basic"):
        assert "cliffhanger" not in promo["cliffhanger"]["evidence"].lower()


def test_resume_reuses_saved_episodes(sample_zip, tmp_path):
    run_basic_pipeline(sample_zip, tmp_path / "basic")
    first = (tmp_path / "basic" / "promos.json").read_text()
    summary = run_basic_pipeline(sample_zip, tmp_path / "basic")
    assert summary["episodes_resumed_from_checkpoint"] == 3
    assert (tmp_path / "basic" / "promos.json").read_text() == first


def test_resume_after_a_stop_midway(sample_zip, tmp_path):
    run_basic_pipeline(sample_zip, tmp_path / "basic")
    checkpoint = tmp_path / "basic" / "checkpoint.json"
    state = json.loads(checkpoint.read_text())
    del state["episodes"]["3"]
    checkpoint.write_text(json.dumps(state))
    summary = run_basic_pipeline(sample_zip, tmp_path / "basic")
    assert summary["episodes_resumed_from_checkpoint"] == 2 and summary["episodes_processed"] == 3


def test_csv_matches_json(sample_zip, tmp_path):
    run_basic_pipeline(sample_zip, tmp_path / "basic")
    promos = load_promos(tmp_path / "basic")
    with (tmp_path / "basic" / "promos.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == len(promos)
    for row, promo in zip(rows, promos):
        assert int(row["global_rank"]) == promo["global_rank"]
        assert row["start_timestamp"] == promo["segments"][0]["start_timestamp"]
        assert row["hook_text"] == promo["hook"]["evidence"]
        assert row["human_review_status"] == "not_reviewed"


def test_csv_can_be_written_with_no_promos(tmp_path):
    write_promos_csv(tmp_path / "none.csv", [])
    assert (tmp_path / "none.csv").read_text().startswith("global_rank")


# Schema and tamper detection.

@pytest.fixture
def promo_and_episodes(sample_zip, tmp_path):
    run_basic_pipeline(sample_zip, tmp_path / "basic")
    episodes, _ = load_pack(sample_zip)
    return load_promos(tmp_path / "basic")[0], {e.number: e for e in episodes}


def test_clean_promo_passes_verification(promo_and_episodes):
    data, episodes = promo_and_episodes
    assert verify_promo_against_screenplay(Promo(**data), episodes) == []


def test_changed_time_is_caught(promo_and_episodes):
    data, episodes = promo_and_episodes
    segment = data["segments"][0]
    segment["start_seconds"] += 0.5
    segment["start_timestamp"] = format_timestamp(segment["start_seconds"])
    data["total_duration_seconds"] = round(segment["end_seconds"] - segment["start_seconds"], 3)
    assert any("is not the start of" in e for e in verify_promo_against_screenplay(Promo(**data), episodes))


def test_changed_quotation_is_caught(promo_and_episodes):
    data, episodes = promo_and_episodes
    data["hook"]["evidence"] = "A line the screenplay never contained."
    assert any("not the exact screenplay text" in e for e in verify_promo_against_screenplay(Promo(**data), episodes))


def test_unknown_cue_is_caught(promo_and_episodes):
    data, episodes = promo_and_episodes
    data["segments"][0]["start_cue_id"] = "E01_C9999"
    data["hook"]["cue_ids"] = ["E01_C9998"]
    errors = verify_promo_against_screenplay(Promo(**data), episodes)
    assert any("does not exist" in e for e in errors)


def test_schema_rejects_bad_promos(promo_and_episodes):
    base, _ = promo_and_episodes

    def changed(**edits):
        data = json.loads(json.dumps(base))
        for name, value in edits.items():
            data[name] = value
        return data

    with pytest.raises(ValidationError, match="total_duration"):
        Promo(**changed(total_duration_seconds=1.0))
    short = json.loads(json.dumps(base))
    short["segments"][0]["end_seconds"] = short["segments"][0]["start_seconds"] + 10
    short["segments"][0]["end_timestamp"] = format_timestamp(short["segments"][0]["end_seconds"])
    short["total_duration_seconds"] = 10.0
    with pytest.raises(ValidationError, match="outside"):
        Promo(**short)
    with pytest.raises(ValidationError):
        Promo(**changed(selection_method="magic"))
    with pytest.raises(ValidationError):
        Promo(**changed(total_score=250))
    late_hook = json.loads(json.dumps(base))
    late_hook["hook"]["within_first_three_seconds"] = False
    with pytest.raises(ValidationError, match="three seconds"):
        Promo(**late_hook)
    rated = json.loads(json.dumps(base))
    rated["human_review"]["rating"] = 5
    with pytest.raises(ValidationError, match="before a human review"):
        Promo(**rated)


def test_verify_all_collects_every_error(promo_and_episodes):
    data, episodes = promo_and_episodes
    data["hook"]["evidence"] = "changed"
    assert verify_all([Promo(**data), Promo(**data)], episodes)


# Worksheets stay blank and independent.

def test_reference_kit_is_blank_and_holds_no_candidates(sample_zip, tmp_path):
    episodes, _ = load_pack(sample_zip)
    write_reference_kit(episodes, tmp_path / "kit")
    assert read_reference_sheet(tmp_path / "kit" / "manual_reference_worksheet.csv") == []
    joined = "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "kit").iterdir())
    for word in ("total_score", "global_rank", "recommend"):
        assert word not in joined


def test_kit_never_overwrites_a_filled_worksheet(sample_zip, tmp_path):
    episodes, _ = load_pack(sample_zip)
    write_reference_kit(episodes, tmp_path / "kit")
    sheet = tmp_path / "kit" / "manual_reference_worksheet.csv"
    sheet.write_text("reference_id,episode,start_time,end_time\nH01,3,00:01.00,00:30.00\n", encoding="utf-8")
    write_reference_kit(episodes, tmp_path / "kit")
    assert "H01,3" in sheet.read_text(encoding="utf-8")


def test_review_sheet_ratings_start_empty(tmp_path):
    path = write_review_sheet(tmp_path / "review.csv")
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert len(rows) == 20
    assert all(not row["would_post_yes_no"] and not row["reviewer"] for row in rows)


# Comparisons.

def reference_row(episode, start, end, name="H01"):
    return {"reference_id": name, "episode": episode, "start": start, "end": end}


def promo_row(rank, episode, start, end):
    return {"promo_id": f"P{rank}", "global_rank": rank, "clip_key": f"k{rank}", "total_score": 50,
            "segments": [{"episode": episode, "start_seconds": start, "end_seconds": end}]}


def test_reference_coverage_verdicts():
    result = reference_coverage(
        [reference_row(1, 0, 40), reference_row(1, 100, 140, "H02"), reference_row(2, 0, 30, "H03"), reference_row(5, 0, 30, "H04")],
        [promo_row(1, 1, 5, 45), promo_row(2, 1, 125, 155), promo_row(3, 2, 200, 230)],
    )
    verdicts = {d["reference_id"]: d["verdict"] for d in result["details"]}
    assert verdicts == {"H01": "match", "H02": "same_area", "H03": "missed", "H04": "missed"}
    assert result["recall"] == 0.25 and result["matched_in_top_10"] == 1


def test_reference_sheet_reports_bad_rows(tmp_path):
    path = tmp_path / "sheet.csv"
    path.write_text(
        "reference_id,episode,start_time,end_time\nH01,3,00:01.00,00:30.00\nH02,3,00:40.00,00:10.00\nH03,x,00:01.00,00:30.00\nH04,,,\n",
        encoding="utf-8",
    )
    usable, problems = load_reference(path)
    assert [row["reference_id"] for row in usable] == ["H01"]
    assert len(problems) == 2


def test_mean_best_iou_handles_empty_lists():
    assert mean_best_iou([], [promo_row(1, 1, 0, 30)]) is None
    assert mean_best_iou([promo_row(1, 1, 0, 30)], []) == 0.0


def test_show_title_is_read_from_file_name():
    assert pack_title("/x/My Show. Part Two-scripts (2) (1).zip") == "My Show. Part Two"
    assert pack_title("/x/plain_name.zip") == "plain_name"


def test_short_clip_inside_a_longer_one_counts_as_a_duplicate():
    # Shared time is 28 of 60 covered (0.47, below the 0.5 rule), but 28 of the shorter clip's 30 seconds.
    longer = scored(1, 26, 84, "E01_C0016", "E01_C0054", 80)
    shorter = scored(1, 56, 86, "E01_C0039", "E01_C0055", 60)
    kept, removed = remove_duplicates([longer, shorter])
    assert kept == [longer]
    assert "inside the longer one" in removed[0].reason
