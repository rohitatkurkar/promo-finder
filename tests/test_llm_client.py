"""Model failures must be handled safely, and keys must never leak."""

import json

import pytest
import requests
from conftest import FakeResponse, ok_reply

from promo_finder.llm_client import LLMClient, LLMError, ModelConfig, UsageLedger, extract_json, load_model_config

KEY = "gsk_realLookingSecretKey1234567890"


def config(**changes):
    values = dict(role="finder", base_url="https://api.example.test/v1", model="model-a", api_key=KEY,
                  requests_per_minute=0, tokens_per_minute=0)
    values.update(changes)
    return ModelConfig(**values)


def client(transport, tmp_path=None, **changes):
    return LLMClient(config(**changes), cache_dir=tmp_path, transport=transport, sleep=lambda _: None,
                     ledger=UsageLedger(tmp_path / "usage.jsonl" if tmp_path else None))


class Script:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = 0

    def __call__(self, url, headers=None, json=None, timeout=None):  # noqa: A002
        self.calls += 1
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def test_missing_key_is_a_clear_error_and_sends_nothing():
    script = Script()
    with pytest.raises(LLMError) as error:
        LLMClient(config(api_key=""), transport=script).chat_json("s", "u", "p", "v1")
    assert error.value.kind == "missing_key"
    assert ".env" in error.value.detail
    assert script.calls == 0


def test_local_model_needs_no_key():
    script = Script(ok_reply('{"a": 1}'))
    result = LLMClient(config(api_key="", base_url="http://localhost:11434/v1"), transport=script, sleep=lambda _: None).chat_json("s", "u", "p", "v1")
    assert result.data == {"a": 1}


def test_invalid_key_stops_immediately_without_retrying():
    script = Script(FakeResponse(401, text="invalid api key"))
    with pytest.raises(LLMError) as error:
        client(script).chat_json("s", "u", "p", "v1")
    assert error.value.kind == "auth" and script.calls == 1


def test_rate_limit_waits_and_retries():
    waits = []
    script = Script(FakeResponse(429, text="slow down", headers={"Retry-After": "3"}), ok_reply('{"a": 1}'))
    model = LLMClient(config(), transport=script, sleep=waits.append)
    assert model.chat_json("s", "u", "p", "v1").data == {"a": 1}
    assert waits and waits[0] >= 3


def test_long_rate_limit_stops_so_the_run_can_resume_later():
    script = Script(FakeResponse(429, text="Rate limit reached. Please try again in 45m12.5s."))
    with pytest.raises(LLMError) as error:
        client(script).chat_json("s", "u", "p", "v1")
    assert error.value.kind == "rate_limit_exhausted" and script.calls == 1


def test_repeated_rate_limit_gives_up_after_limited_retries():
    script = Script(*[FakeResponse(429, text="slow down", headers={"Retry-After": "1"}) for _ in range(10)])
    with pytest.raises(LLMError) as error:
        client(script).chat_json("s", "u", "p", "v1")
    assert error.value.kind == "rate_limit_exhausted"
    assert script.calls <= 5


def test_network_failure_retries_then_reports():
    script = Script(*[requests.ConnectionError("no route") for _ in range(10)])
    with pytest.raises(LLMError) as error:
        client(script).chat_json("s", "u", "p", "v1")
    assert error.value.kind == "network" and script.calls == 5


def test_network_failure_recovers():
    script = Script(requests.Timeout("slow"), ok_reply('{"a": 2}'))
    assert client(script).chat_json("s", "u", "p", "v1").data == {"a": 2}


def test_server_error_retries_then_recovers():
    script = Script(FakeResponse(503, text="busy"), ok_reply('{"a": 3}'))
    assert client(script).chat_json("s", "u", "p", "v1").data == {"a": 3}


def test_unknown_model_is_reported():
    script = Script(FakeResponse(404, text="model not found"))
    with pytest.raises(LLMError) as error:
        client(script).chat_json("s", "u", "p", "v1")
    assert error.value.kind == "model_not_found"


def test_empty_response_retries_once_then_fails():
    script = Script(ok_reply(""), ok_reply(""))
    with pytest.raises(LLMError) as error:
        client(script).chat_json("s", "u", "p", "v1")
    assert error.value.kind == "empty_response" and script.calls == 2


def test_invalid_json_gets_one_retry_with_a_reminder():
    seen = []

    def transport(url, headers=None, json=None, timeout=None):  # noqa: A002
        seen.append(json["messages"][1]["content"])
        return ok_reply("not json at all") if len(seen) == 1 else ok_reply('{"ok": true}')

    result = LLMClient(config(), transport=transport, sleep=lambda _: None).chat_json("s", "u", "p", "v1")
    assert result.data == {"ok": True} and "not valid JSON" in seen[1]


def test_invalid_json_twice_fails_clearly():
    script = Script(ok_reply("nope"), ok_reply("still nope"))
    with pytest.raises(LLMError) as error:
        client(script).chat_json("s", "u", "p", "v1")
    assert error.value.kind == "invalid_json"


def test_provider_json_failure_is_retried():
    script = Script(FakeResponse(400, text='{"error":{"code":"json_validate_failed"}}'), ok_reply('{"a": 4}'))
    assert client(script).chat_json("s", "u", "p", "v1").data == {"a": 4}


def test_provider_that_rejects_json_mode_or_seed_still_works():
    script = Script(FakeResponse(400, text="response_format is not supported"), FakeResponse(400, text="seed is not supported"), ok_reply('{"a": 5}'))
    assert client(script).chat_json("s", "u", "p", "v1").data == {"a": 5}


def test_extract_json_handles_thinking_blocks_and_code_fences():
    assert extract_json('<think>hmm {"no": 1}</think>{"a": 1}') == {"a": 1}
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! Here it is: {"a": {"b": "}"}} Thanks!') == {"a": {"b": "}"}}


def test_extract_json_rejects_a_list_and_a_cut_off_reply():
    with pytest.raises(LLMError):
        extract_json("[1, 2]")
    with pytest.raises(LLMError):
        extract_json('{"a": 1')


def test_cache_returns_saved_answer_and_records_it(tmp_path):
    script = Script(ok_reply('{"a": 1}'))
    model = client(script, tmp_path)
    assert model.chat_json("s", "u", "p", "v1").cached is False
    again = model.chat_json("s", "u", "p", "v1")
    assert again.cached is True and again.data == {"a": 1} and script.calls == 1
    totals = model.ledger.summary()["totals"]
    assert totals["model_calls"] == 1 and totals["cached_calls"] == 1


def test_cache_misses_when_prompt_version_script_or_model_changes(tmp_path):
    script = Script(*[ok_reply('{"a": 1}') for _ in range(4)])
    client(script, tmp_path).chat_json("s", "u", "p", "v1", "hash1")
    client(script, tmp_path).chat_json("s", "u", "p", "v2", "hash1")
    client(script, tmp_path).chat_json("s", "u", "p", "v1", "hash2")
    client(script, tmp_path, model="model-b").chat_json("s", "u", "p", "v1", "hash1")
    assert script.calls == 4


def test_no_cache_flag_asks_again(tmp_path):
    script = Script(ok_reply('{"a": 1}'), ok_reply('{"a": 2}'))
    client(script, tmp_path).chat_json("s", "u", "p", "v1")
    fresh = LLMClient(config(), cache_dir=tmp_path, transport=script, sleep=lambda _: None, use_cache=False)
    assert fresh.chat_json("s", "u", "p", "v1").data == {"a": 2}


def test_temperature_zero_is_sent():
    bodies = []

    def transport(url, headers=None, json=None, timeout=None):  # noqa: A002
        bodies.append(json)
        return ok_reply('{"a": 1}')

    LLMClient(config(), transport=transport).chat_json("s", "u", "p", "v1")
    assert bodies[0]["temperature"] == 0.0


def test_usage_counts_failures_and_calculates_cost(tmp_path):
    script = Script(ok_reply('{"a": 1}', 1000, 500), FakeResponse(401, text="no"))
    model = client(script, tmp_path, price_input_per_million=1.0, price_output_per_million=2.0)
    model.chat_json("s", "u", "p", "v1")
    with pytest.raises(LLMError):
        model.chat_json("s", "other", "p", "v1")
    summary = model.ledger.summary({"finder": model.config})
    assert summary["totals"]["model_calls"] == 2 and summary["totals"]["failed_calls"] == 1
    assert summary["totals"]["total_tokens"] == 1500
    assert summary["cost_at_listed_paid_price_usd"] == pytest.approx(0.002)


def test_provider_without_token_usage_is_counted_honestly(tmp_path):
    script = Script(FakeResponse(200, {"choices": [{"message": {"content": '{"a": 1}'}}]}))
    model = client(script, tmp_path)
    model.chat_json("s", "u", "p", "v1")
    entry = model.ledger.summary()["by_role"]["finder"]
    assert entry["calls_without_token_usage"] == 1 and entry["total_tokens"] == 0


def test_key_never_appears_in_errors_ledger_cache_or_repr(tmp_path):
    script = Script(FakeResponse(400, text=f"bad request for key {KEY}"), ok_reply('{"a": 1}'))
    model = client(script, tmp_path)
    with pytest.raises(LLMError) as error:
        model.chat_json("s", "u", "p", "v1")
    assert KEY not in str(error.value)
    model.chat_json("s", "other", "p", "v1")
    assert KEY not in repr(model.config)
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert KEY not in path.read_text(encoding="utf-8")


def test_config_lets_a_role_override_shared_settings():
    env = {"LLM_API_KEY": "shared", "LLM_MODEL": "shared-model", "EVALUATOR_MODEL": "judge-model", "EVALUATOR_API_KEY": "judge-key"}
    assert load_model_config("finder", env).model == "shared-model"
    assert load_model_config("evaluator", env).model == "judge-model"
    assert load_model_config("evaluator", env).api_key == "judge-key"
    assert load_model_config("finder", env, "cli-model").model == "cli-model"


def test_cut_off_reply_is_asked_again_with_more_room():
    seen = []

    def transport(url, headers=None, json=None, timeout=None):  # noqa: A002
        seen.append(json["max_tokens"])
        if len(seen) == 1:
            return FakeResponse(200, {"choices": [{"message": {"content": '{"a": [1, 2'}, "finish_reason": "length"}],
                                      "usage": {"prompt_tokens": 10, "completion_tokens": 2000}})
        return ok_reply('{"a": [1, 2]}')

    result = LLMClient(config(max_output_tokens=2000), transport=transport, sleep=lambda _: None).chat_json("s", "u", "p", "v1")
    assert result.data == {"a": [1, 2]}
    assert seen == [2000, 4000]


def test_cut_off_reply_that_still_parses_is_asked_again_with_more_room():
    """A reasoning model can use up its output limit and close the JSON early, dropping whole fields."""
    seen = []

    def transport(url, headers=None, json=None, timeout=None):  # noqa: A002
        seen.append(json["max_tokens"])
        if len(seen) == 1:
            return FakeResponse(200, {"choices": [{"message": {"content": '{"hook_events": []}'}, "finish_reason": "length"}],
                                      "usage": {"prompt_tokens": 10, "completion_tokens": 2000}})
        return FakeResponse(200, {"choices": [{"message": {"content": '{"hook_events": [], "ending_events": []}'}, "finish_reason": "stop"}],
                                  "usage": {"prompt_tokens": 10, "completion_tokens": 2600}})

    ledger = UsageLedger()
    result = LLMClient(config(max_output_tokens=2000), ledger=ledger, transport=transport, sleep=lambda _: None).chat_json("s", "u", "p", "v1")
    assert result.data == {"hook_events": [], "ending_events": []}
    assert seen == [2000, 4000]
    assert [record["status"] for record in ledger.records] == ["failed", "ok"]
    assert ledger.records[0]["error_kind"] == "cut_off" and ledger.records[0]["output_tokens"] == 2000
    assert ledger.records[1]["finish_reason"] == "stop"
    assert ledger.summary()["totals"]["output_tokens"] == 4600  # The discarded attempt's tokens are still counted.


def test_cut_off_twice_keeps_the_second_reply_and_records_why():
    seen = []

    def transport(url, headers=None, json=None, timeout=None):  # noqa: A002
        seen.append(json["max_tokens"])
        return FakeResponse(200, {"choices": [{"message": {"content": '{"hook_events": []}'}, "finish_reason": "length"}],
                                  "usage": {"prompt_tokens": 10, "completion_tokens": json["max_tokens"]}})

    ledger = UsageLedger()
    result = LLMClient(config(max_output_tokens=2000), ledger=ledger, transport=transport, sleep=lambda _: None).chat_json("s", "u", "p", "v1")
    assert result.data == {"hook_events": []}
    assert seen == [2000, 4000]  # Only one extra attempt, so quota use stays bounded.
    assert ledger.records[-1]["status"] == "ok" and ledger.records[-1]["finish_reason"] == "length"


def test_a_complete_reply_is_not_asked_again():
    seen = []

    def transport(url, headers=None, json=None, timeout=None):  # noqa: A002
        seen.append(json["max_tokens"])
        return FakeResponse(200, {"choices": [{"message": {"content": '{"a": 1}'}, "finish_reason": "stop"}],
                                  "usage": {"prompt_tokens": 10, "completion_tokens": 1999}})

    LLMClient(config(max_output_tokens=2000), transport=transport, sleep=lambda _: None).chat_json("s", "u", "p", "v1")
    assert seen == [2000]
