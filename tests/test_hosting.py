"""Hosted settings: .env plus Streamlit secrets, and the episode limit."""

import json

import pytest
from conftest import FakeProvider

from promo_finder.hosting import (
    DEFAULT_MAX_EPISODES,
    has_api_key,
    max_episodes,
    merge_settings,
    parse_episode_selection,
)
from promo_finder.pipeline import run_ai_pipeline


def test_secrets_win_over_the_local_file_and_sections_are_ignored():
    merged = merge_settings(
        {"LLM_API_KEY": "local-key", "FINDER_MODEL": "local-model", "EMPTY": "", "NONE": None},
        {"LLM_API_KEY": "secret-key", "AI_MAX_EPISODES": 2, "connections": {"db": "x"}},
    )
    assert merged == {"LLM_API_KEY": "secret-key", "FINDER_MODEL": "local-model", "AI_MAX_EPISODES": "2"}


def test_api_key_detection():
    assert has_api_key({"LLM_API_KEY": "k"})
    assert has_api_key({"FINDER_API_KEY": "a", "EVALUATOR_API_KEY": "b"})
    assert not has_api_key({"FINDER_API_KEY": "a"})
    assert not has_api_key({})


@pytest.mark.parametrize("value, expected", [(None, DEFAULT_MAX_EPISODES), ("5", 5), ("0", 1), ("lots", DEFAULT_MAX_EPISODES)])
def test_episode_limit(value, expected):
    settings = {} if value is None else {"AI_MAX_EPISODES": value}
    assert max_episodes(settings) == expected


@pytest.mark.parametrize("text, expected", [
    ("", {1, 2, 3}), ("2", {2}), ("1-3", {1, 2, 3}), (" 1, 3 ", {1, 3}), ("1-2,3", {1, 2, 3}),
])
def test_episode_selection(text, expected):
    assert parse_episode_selection(text, [1, 2, 3]) == (expected, "")


@pytest.mark.parametrize("text, problem", [("4", "Not in this pack"), ("3-1", "backwards"), ("one", "Write episodes"), (",", "No episodes")])
def test_bad_episode_selection(text, problem):
    chosen, message = parse_episode_selection(text, [1, 2, 3])
    assert chosen is None and problem in message


def test_ai_pipeline_can_take_settings_without_a_env_file(sample_zip, tmp_path):
    provider = FakeProvider()
    settings = {"LLM_BASE_URL": "https://api.example.test/v1", "LLM_API_KEY": "secret-test-key-1234567890",
                "FINDER_MODEL": "finder-model", "EVALUATOR_MODEL": "evaluator-model",
                "LLM_REQUESTS_PER_MINUTE": "0", "LLM_TOKENS_PER_MINUTE": "0"}
    summary = run_ai_pipeline(sample_zip, tmp_path / "run", env_path=tmp_path / "missing.env", cache_dir=tmp_path / "cache",
                              transport=provider, sleep=lambda _: None, only_episodes={1}, env_values=settings)
    assert summary["episodes_processed"] == 1 and summary["complete"]
    assert provider.requests and all(r["headers"]["Authorization"] == "Bearer secret-test-key-1234567890" for r in provider.requests)
    config = json.loads((tmp_path / "run" / "run_config.json").read_text(encoding="utf-8"))
    assert config["finder"]["model"] == "finder-model"
    assert "secret-test-key" not in (tmp_path / "run" / "processing_summary.json").read_text(encoding="utf-8")
