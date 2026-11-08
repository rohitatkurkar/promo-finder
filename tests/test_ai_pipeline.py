"""AI assisted mode from end to end, using a fake provider so no key or network is needed."""

import json
import re

import pytest
from conftest import FakeProvider, dialogue_rows, make_episode, write_env

from promo_finder.ai_mode import (
    FinderOutcome, cold_viewer_passes, evaluate_clip, gate_failures, pair_events, parse_rating,
    select_candidates, validate_finder_reply,
)
from promo_finder.boundaries import build_clip
from promo_finder.evaluation import compare_runs, load_promos
from promo_finder.llm_client import LLMClient, LLMError, ModelConfig
from promo_finder.parser import load_pack
from promo_finder.pipeline import judge_clips, run_ai_pipeline
from promo_finder.prompts import COLD_VIEWER_SYSTEM, FINDER_SYSTEM, HOOK_SYSTEM, build_finder_prompt

SECRET_KEY = "test-key-abc123456789"


def run(sample_zip, tmp_path, provider, folder="run", **options):
    env = write_env(tmp_path / ".env", SECRET_KEY)
    return run_ai_pipeline(sample_zip, tmp_path / folder, env_path=env, cache_dir=tmp_path / "cache", transport=provider, sleep=lambda _: None, **options)


def good_evaluation(**changes):
    values = {"hook_rating": 4, "ending_rating": 4, "ending_resolves_conflict": False, "conflict_understood": True,
              "question_understood": True, "main_conflict": "A betrayal", "wants_to_know_next": "What next",
              "verified_evidence": ["a line"]}
    values.update(changes)
    return values


def episode_for_validation():
    return make_episode([("CAMERA", 0.0, 2.0, "Wide shot.")] + dialogue_rows(0.0, 14))


# Checks on what the finder returns.

def test_unknown_cue_ids_are_rejected_and_recorded():
    episode = episode_for_validation()
    outcome = validate_finder_reply({"hook_events": [{"cue_id": "E01_C9999", "strength": 4}], "ending_events": []}, episode)
    assert outcome.hooks == []
    assert any(issue.kind == "unknown_cue_id" for issue in outcome.issues)


def test_cue_from_another_episode_is_rejected():
    episode = episode_for_validation()
    outcome = validate_finder_reply({"hook_events": [{"cue_id": "E77_C0002", "strength": 4}], "ending_events": []}, episode)
    assert outcome.hooks == []


def test_camera_cue_selected_by_model_is_rejected():
    episode = episode_for_validation()
    outcome = validate_finder_reply({"hook_events": [{"cue_id": "E01_C0001", "strength": 5}], "ending_events": []}, episode)
    assert outcome.hooks == [] and any(issue.kind == "non_story_cue" for issue in outcome.issues)


def test_invented_dialogue_is_discarded_and_only_the_screenplay_is_used():
    episode = episode_for_validation()
    reply = {"hook_events": [{"cue_id": "E01_C0002", "quote": "I am your long lost twin!", "strength": 4}], "ending_events": []}
    outcome = validate_finder_reply(reply, episode)
    assert any(issue.kind == "invented_quote" for issue in outcome.issues)
    assert outcome.hooks[0].verified_quote is False
    assert "twin" not in json.dumps(outcome.hooks[0].__dict__)


def test_invented_timestamps_are_recorded_and_never_used():
    episode = episode_for_validation()
    reply = {
        "hook_events": [{"cue_id": "E01_C0002", "strength": 4, "start_time": "00:01.00", "why": "at 00:05.00 it lands"}],
        "ending_events": [{"cue_id": "E01_C0013", "strength": 4, "end": 999.0}],
    }
    outcome = validate_finder_reply(reply, episode)
    assert sum(issue.kind == "invented_timestamp" for issue in outcome.issues) >= 3
    valid, _ = pair_events(episode, outcome)
    clip = valid[0][0]
    assert clip.end != 999.0
    assert episode.cue(clip.end_cue_id).end == clip.end


def test_scores_outside_the_range_are_rejected():
    issues = []
    for bad in (0, 6, 11, -1, "high", None, True):
        assert parse_rating(bad, "x", "here", issues) is None
    assert len(issues) == 7
    assert parse_rating(5, "x", "here", issues) == 5
    episode = episode_for_validation()
    outcome = validate_finder_reply({"hook_events": [{"cue_id": "E01_C0002", "strength": 99}], "ending_events": []}, episode)
    assert outcome.hooks == []


def test_wrong_reply_shape_is_recorded():
    episode = episode_for_validation()
    outcome = validate_finder_reply({"hook_events": "oops"}, episode)
    kinds = {issue.kind for issue in outcome.issues}
    assert "wrong_type" in kinds and "missing_field" in kinds


def test_hook_on_a_continuation_line_moves_to_where_the_sentence_starts():
    rows = dialogue_rows(0.0, 2) + [("ANNA (Cold)", 6.0, 8.0, "I said..."), ("ANNA (Cold)", 8.0, 10.0, "...let her go.")] + dialogue_rows(10.0, 12)
    episode = make_episode(rows)
    outcome = validate_finder_reply({
        "hook_events": [{"cue_id": episode.cues[3].cue_id, "strength": 4}],
        "ending_events": [{"cue_id": episode.cues[13].cue_id, "strength": 4}],
    }, episode)
    valid, rejected = pair_events(episode, outcome)
    assert not rejected
    assert valid[0][0].hook_cue_id == episode.cues[2].cue_id
    assert any("where the sentence begins" in note for note in valid[0][0].adjustments)


def test_invalid_pairs_are_kept_as_recorded_rejections():
    episode = make_episode(dialogue_rows(0.0, 40))
    outcome = FinderOutcome(1)
    outcome = validate_finder_reply({
        "hook_events": [{"cue_id": episode.cues[0].cue_id, "strength": 4}],
        "ending_events": [{"cue_id": episode.cues[2].cue_id, "strength": 4}, {"cue_id": episode.cues[35].cue_id, "strength": 4}],
    }, episode)
    valid, rejected = pair_events(episode, outcome)
    assert valid == []
    assert {pair.reason for pair in rejected} == {"too_short", "too_long"}


def test_near_identical_candidates_are_not_both_selected():
    episode = make_episode(dialogue_rows(0.0, 30))
    first = build_clip(episode, episode.cues[0], episode.cues[12]).clip
    second = build_clip(episode, episode.cues[1], episode.cues[12]).clip
    third = build_clip(episode, episode.cues[14], episode.cues[27]).clip
    chosen = select_candidates([(first, 8), (second, 7), (third, 6)])
    assert first in chosen and third in chosen and second not in chosen


# Gates.

def test_a_good_clip_passes_every_gate():
    assert gate_failures(good_evaluation()) == []


@pytest.mark.parametrize("change,expected", [
    ({"hook_rating": 3}, "hook_rated_3_of_5_not_strong"),
    ({"hook_rating": None}, "hook_not_rated"),
    ({"ending_rating": 3}, "ending_rated_3_of_5_not_strong"),
    ({"ending_rating": None}, "ending_not_rated"),
    ({"ending_resolves_conflict": True}, "ending_resolves_the_conflict"),
    ({"conflict_understood": False}, "cold_viewer_failed"),
    ({"question_understood": False}, "cold_viewer_failed"),
    ({"main_conflict": "Unclear."}, "cold_viewer_failed"),
    ({"wants_to_know_next": "unclear"}, "cold_viewer_failed"),
    ({"verified_evidence": []}, "cold_viewer_failed"),
])
def test_each_gate_fails_on_its_own(change, expected):
    assert expected in gate_failures(good_evaluation(**change))


def test_cold_viewer_needs_real_evidence_not_invented_lines():
    assert not cold_viewer_passes(good_evaluation(verified_evidence=[], unverified_evidence=["made up"]))


# What each role is allowed to see.

def test_finder_prompt_holds_no_timestamps(sample_zip):
    episodes, _ = load_pack(sample_zip)
    for episode in episodes:
        assert not re.search(r"\d\d:\d\d\.\d\d", build_finder_prompt(episode, "A Show"))


def test_blind_prompts_never_see_loglines_notes_labels_or_finder_reasons(sample_zip, tmp_path):
    provider = FakeProvider()
    run(sample_zip, tmp_path, provider)
    episodes, _ = load_pack(sample_zip)
    blind = [r for r in provider.requests if r["body"]["messages"][0]["content"] in (HOOK_SYSTEM, COLD_VIEWER_SYSTEM)]
    assert blind
    text = " ".join(r["body"]["messages"][1]["content"] for r in blind)
    for episode in episodes:
        assert episode.logline not in text
        assert episode.continuity_notes not in text
    assert "stops the scroll" not in text  # The finder's reason.
    assert "The Lighthouse Debt" not in text  # The show's title.
    assert "PROSECUTOR" not in text and "HOODED MAN" not in text and "MARA" not in text  # Script labels.
    assert not re.search(r"\d\d:\d\d\.\d\d", text)


def test_hook_test_only_sees_the_first_three_seconds(sample_zip, tmp_path):
    provider = FakeProvider()
    run(sample_zip, tmp_path, provider)
    full = [r["body"]["messages"][1]["content"] for r in provider.requests if r["body"]["messages"][0]["content"] == COLD_VIEWER_SYSTEM]
    short = [r["body"]["messages"][1]["content"] for r in provider.requests if r["body"]["messages"][0]["content"] == HOOK_SYSTEM]
    assert short and sum(map(len, short)) / len(short) < sum(map(len, full)) / len(full)


# Whole runs.

def test_full_run_produces_valid_traceable_outputs(sample_zip, tmp_path):
    summary = run(sample_zip, tmp_path, FakeProvider())
    assert summary["complete"] and summary["verification_errors"] == []
    assert summary["episodes_processed"] == 3 and summary["recommended_clips"] >= 1
    promos = load_promos(tmp_path / "run")
    assert all(p["selection_method"] == "ai_assisted" for p in promos)
    assert all(20 <= p["total_duration_seconds"] <= 60 for p in promos)
    assert all(p["hook"]["strength"] == "strong" for p in promos)
    assert all(p["cold_viewer_check"]["result"] == "pass" for p in promos)
    assert all(p["human_review"] == {"status": "not_reviewed", "rating": None, "reviewer": None} for p in promos)
    assert sum(p["first_post_recommendation"] for p in promos) == 1
    assert [p["global_rank"] for p in promos] == list(range(1, len(promos) + 1))
    for name in ("promos.csv", "report.md", "processing_summary.json", "usage_summary.json", "top_twenty_human_review_sheet.csv", "run_config.json"):
        assert (tmp_path / "run" / name).exists()


def test_weak_hooks_are_not_recommended_even_when_all_else_is_good(sample_zip, tmp_path):
    summary = run(sample_zip, tmp_path, FakeProvider(hook_rating=3))
    assert summary["recommended_clips"] == 0
    assert summary["gate_failure_counts"]["hook_not_strong"] >= 1
    assert json.loads((tmp_path / "run" / "rejected_candidates.json").read_text(encoding="utf-8"))


def test_weak_hook_skips_the_longer_cold_viewer_call(sample_zip, tmp_path):
    provider = FakeProvider(hook_rating=2)
    run(sample_zip, tmp_path, provider)
    assert not [r for r in provider.requests if r["body"]["messages"][0]["content"] == COLD_VIEWER_SYSTEM]
    saved = json.loads((tmp_path / "run" / "rejected_candidates.json").read_text(encoding="utf-8"))
    assert all(item["evaluation"]["cold_viewer_skipped"] for item in saved)
    assert all(item["gate_failures"] == ["hook_rated_2_of_5_not_strong"] for item in saved)


def test_cold_viewer_failure_blocks_recommendation(sample_zip, tmp_path):
    summary = run(sample_zip, tmp_path, FakeProvider(understood=False))
    assert summary["recommended_clips"] == 0 and summary["gate_failure_counts"]["cold_viewer_failed"] >= 1


def test_missing_key_stops_with_clear_message(sample_zip, tmp_path):
    env = write_env(tmp_path / ".env", "")
    provider = FakeProvider()
    with pytest.raises(LLMError) as error:
        run_ai_pipeline(sample_zip, tmp_path / "run", env_path=env, transport=provider, sleep=lambda _: None)
    assert error.value.kind == "missing_key" and provider.requests == []


def test_shell_environment_key_is_not_used(sample_zip, tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "from-the-shell-not-the-env-file")
    env = write_env(tmp_path / ".env", "")
    with pytest.raises(LLMError):
        run_ai_pipeline(sample_zip, tmp_path / "run", env_path=env, transport=FakeProvider(), sleep=lambda _: None)


def test_failed_episode_is_reported_and_never_silently_skipped(sample_zip, tmp_path):
    summary = run(sample_zip, tmp_path, FakeProvider(fail_finder_episodes={2}))
    assert summary["complete"] is False
    assert summary["episodes_pending_or_failed"] == [2]
    assert summary["failed_episodes"]["2"]["error_kind"] == "server"
    assert summary["episodes_processed"] == 2


def test_resume_only_processes_what_is_left(sample_zip, tmp_path):
    first = FakeProvider(fail_finder_episodes={2})
    run(sample_zip, tmp_path, first)
    second = FakeProvider()
    summary = run(sample_zip, tmp_path, second)
    assert summary["complete"] and summary["episodes_processed"] == 3
    finder_calls = [r for r in second.requests if r["body"]["messages"][0]["content"] == FINDER_SYSTEM]
    assert len(finder_calls) == 1
    assert "EPISODE: 2" in finder_calls[0]["body"]["messages"][1]["content"]


def test_finished_run_makes_no_new_finder_or_blind_calls_when_run_again(sample_zip, tmp_path):
    run(sample_zip, tmp_path, FakeProvider())
    again = FakeProvider()
    run(sample_zip, tmp_path, again)
    assert [r for r in again.requests if r["body"]["messages"][0]["content"] in (FINDER_SYSTEM, HOOK_SYSTEM, COLD_VIEWER_SYSTEM)] == []


def test_changed_screenplay_is_processed_again(tmp_path):
    import zipfile

    from make_sample import EPISODE_1, EPISODE_3, episode_text

    def pack(path, logline):
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("episode-001.txt", episode_text(1, "Log one", "n", EPISODE_1))
            archive.writestr("episode-002.txt", episode_text(2, logline, "n", EPISODE_3))
        return path

    env = write_env(tmp_path / ".env", SECRET_KEY)
    first = FakeProvider()
    run_ai_pipeline(pack(tmp_path / "a.zip", "Version A"), tmp_path / "run", env_path=env, cache_dir=tmp_path / "cache", transport=first, sleep=lambda _: None)
    second = FakeProvider()
    run_ai_pipeline(pack(tmp_path / "a.zip", "Version B"), tmp_path / "run", env_path=env, cache_dir=tmp_path / "cache", transport=second, sleep=lambda _: None)
    finder_calls = [r for r in second.requests if r["body"]["messages"][0]["content"] == FINDER_SYSTEM]
    assert len(finder_calls) == 1 and "EPISODE: 2" in finder_calls[0]["body"]["messages"][1]["content"]


def test_changing_the_model_restarts_progress(sample_zip, tmp_path):
    run(sample_zip, tmp_path, FakeProvider())
    second = FakeProvider()
    summary = run(sample_zip, tmp_path, second, finder_model="another-model")
    assert [r for r in second.requests if r["body"]["messages"][0]["content"] == FINDER_SYSTEM]
    assert json.loads((tmp_path / "run" / "run_config.json").read_text(encoding="utf-8"))["finder"]["model"] == "another-model"
    assert summary["complete"]


def test_rate_limit_stops_the_run_and_resume_finishes_it(sample_zip, tmp_path):
    from conftest import FakeResponse

    calls = {"n": 0}
    inner = FakeProvider()

    def limited(url, headers=None, json=None, timeout=None):  # noqa: A002
        calls["n"] += 1
        if calls["n"] == 2:
            return FakeResponse(429, text="Rate limit reached. Please try again in 45m0s.")
        return inner(url, headers=headers, json=json, timeout=timeout)

    summary = run(sample_zip, tmp_path, limited)
    assert summary["complete"] is False and "rate_limit_exhausted" in summary["stopped_because"]
    assert run(sample_zip, tmp_path, FakeProvider())["complete"]


def test_no_key_is_written_anywhere_in_a_run(sample_zip, tmp_path):
    run(sample_zip, tmp_path, FakeProvider())
    for path in (tmp_path / "run").rglob("*"):
        if path.is_file():
            assert SECRET_KEY not in path.read_text(encoding="utf-8", errors="ignore"), path


def test_same_model_for_both_roles_is_flagged(sample_zip, tmp_path):
    env = write_env(tmp_path / ".env", SECRET_KEY, finder="one-model", evaluator="one-model")
    run_ai_pipeline(sample_zip, tmp_path / "run", env_path=env, cache_dir=tmp_path / "cache", transport=FakeProvider(), sleep=lambda _: None)
    config = json.loads((tmp_path / "run" / "run_config.json").read_text(encoding="utf-8"))
    assert config["same_model_for_finding_and_judging"] is True and "favour" in config["note"]


def test_stability_report_detects_a_different_ranking(sample_zip, tmp_path):
    run(sample_zip, tmp_path, FakeProvider(), folder="one")
    run(sample_zip, tmp_path, FakeProvider(), folder="two", use_cache=False)
    same = compare_runs(tmp_path / "one", tmp_path / "two")
    assert same["recommended_id_overlap_jaccard"] == 1.0 and same["run_2_used_fresh_requests"] is True
    assert same["same_first_post"] is True

    run(sample_zip, tmp_path, FakeProvider(hook_rating=2), folder="three", use_cache=False)
    different = compare_runs(tmp_path / "one", tmp_path / "three")
    assert different["recommended_run_2"] == 0
    assert different["recommended_id_overlap_jaccard"] == 0.0
    assert len(different["clips_whose_pass_or_fail_changed"]) >= 1


def test_judging_other_clips_leaves_their_run_untouched(sample_zip, tmp_path):
    from promo_finder.pipeline import run_basic_pipeline

    run_basic_pipeline(sample_zip, tmp_path / "basic")
    before = (tmp_path / "basic" / "promos.json").read_bytes()
    episodes, _ = load_pack(sample_zip)
    by_number = {e.number: e for e in episodes}
    clips = []
    for promo in load_promos(tmp_path / "basic"):
        episode = by_number[promo["segments"][0]["episode"]]
        clips.append((build_clip(episode, episode.cue(promo["hook"]["cue_ids"][0]), episode.cue(promo["cliffhanger"]["cue_ids"][0])).clip, episode))
    env = write_env(tmp_path / ".env", SECRET_KEY)
    results = judge_clips(clips, episodes, tmp_path / "basic" / "judged.json", env_path=env, cache_dir=tmp_path / "cache", transport=FakeProvider(), sleep=lambda _: None)
    assert len(results) == len(clips)
    assert (tmp_path / "basic" / "promos.json").read_bytes() == before


def test_evaluate_clip_rejects_invented_evidence():
    episode = make_episode(dialogue_rows(0.0, 12))
    clip = build_clip(episode, episode.cues[0], episode.cues[10]).clip

    class Reply:
        status_code = 200
        headers = {}
        text = ""

        def __init__(self, data):
            self.data = data

        def json(self):
            return {"choices": [{"message": {"content": json.dumps(self.data)}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    def transport(url, headers=None, json=None, timeout=None):  # noqa: A002
        if json["messages"][0]["content"] == HOOK_SYSTEM:
            return Reply({"what_grabs_attention": "x", "what_is_missing": "y", "rating": 5})
        return Reply({"who_appears_involved": "x", "what_is_happening": "x", "main_conflict": "She is his secret wife",
                      "wants_to_know_next": "x", "evidence_lines": ["She is his secret wife, as everyone knows."],
                      "missing_context": "nothing", "conflict_understood": True, "question_understood": True,
                      "clarity_rating": 5, "ending_rating": 5, "ending_resolves_conflict": False,
                      "emotional_impact": 5, "plays_as_one_moment": 5})

    client = LLMClient(ModelConfig("evaluator", "https://x.test/v1", "m", "k", requests_per_minute=0, tokens_per_minute=0), transport=transport)
    evaluation = evaluate_clip(clip, episode, set(), set(), client)
    assert evaluation["verified_evidence"] == []
    assert any(issue["kind"] == "invented_evidence" for issue in evaluation["issues"])
    assert "cold_viewer_failed" in gate_failures(evaluation)


# The finalist review sees episode summaries only up to the latest episode it is reviewing.

def _finalist_prompts(provider):
    from promo_finder.prompts import FINALIST_SYSTEM
    return [request["body"]["messages"][1]["content"] for request in provider.requests
            if request["body"]["messages"][0]["content"] == FINALIST_SYSTEM]


def _outline_episodes(prompt):
    return [int(number) for number in re.findall(r"^E(\d+): ", prompt, flags=re.MULTILINE)]


def test_build_outline_stops_at_the_requested_episode(sample_zip):
    from promo_finder.prompts import build_outline
    episodes, _ = load_pack(sample_zip)
    first = build_outline(episodes, 1)
    assert _outline_episodes(first) == [1]
    assert episodes[1].logline not in first and episodes[2].logline not in first
    assert "stops at Episode 1" in first
    whole = build_outline(episodes, 3)
    assert _outline_episodes(whole) == [1, 2, 3]
    assert "stops at" not in whole  # Nothing was left out, so no note.


def test_episode_one_trial_sends_only_the_first_summary(sample_zip, tmp_path):
    provider = FakeProvider()
    summary = run(sample_zip, tmp_path, provider, only_episodes={1})
    episodes, _ = load_pack(sample_zip)
    prompts = _finalist_prompts(provider)
    assert summary["passed_all_gates"] > 0 and prompts
    for prompt in prompts:
        assert _outline_episodes(prompt) == [1]
        assert episodes[1].logline not in prompt and episodes[2].logline not in prompt


def test_later_episode_trial_sends_summaries_up_to_that_episode_only(sample_zip, tmp_path):
    provider = FakeProvider()
    run(sample_zip, tmp_path, provider, only_episodes={2})
    episodes, _ = load_pack(sample_zip)
    prompts = _finalist_prompts(provider)
    assert prompts
    for prompt in prompts:
        assert _outline_episodes(prompt) == [1, 2]
        assert episodes[2].logline not in prompt
        assert "stops at Episode 2" in prompt


def test_each_finalist_batch_sees_summaries_up_to_its_own_latest_episode(sample_zip, monkeypatch):
    from promo_finder import ai_mode
    from promo_finder.boundaries import Clip
    episodes, _ = load_pack(sample_zip)
    by_number = {episode.number: episode for episode in episodes}
    clips = [(Clip(number, 0.0, 30.0, f"E{number:02d}_C0001", f"E{number:02d}_C0009", f"E{number:02d}_C0001",
                   f"E{number:02d}_C0009", 0.0), by_number[number]) for number in (1, 3, 2)]
    monkeypatch.setattr(ai_mode, "FINALIST_BATCH", 2)  # Batches: [E1, E3] then [E2].
    provider = FakeProvider()
    client = LLMClient(ModelConfig("evaluator", "https://x.test/v1", "m", "k", requests_per_minute=0, tokens_per_minute=0),
                       transport=provider, sleep=lambda _: None)
    reviews, issues = ai_mode.review_finalists(clips, "Show", episodes, client, "hash")
    prompts = _finalist_prompts(provider)
    assert [_outline_episodes(prompt) for prompt in prompts] == [[1, 2, 3], [1, 2]]
    assert episodes[2].logline not in prompts[1]
    assert set(reviews) == {clip.key for clip, _ in clips} and issues == []
