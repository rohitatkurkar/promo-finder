"""Run AI assisted mode over real HTTP against a small local server.

Other tests swap out the network call. This one uses the real request code, so it
would catch wrong URLs, headers or request bodies. The server is still a stand in:
it follows the API's format but is not a language model, so this proves the plumbing
and says nothing about how good a real model's judgement would be.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from conftest import FakeProvider

from promo_finder.evaluation import load_promos
from promo_finder.llm_client import LLMClient, LLMError, ModelConfig
from promo_finder.pipeline import run_ai_pipeline

MODELS = ["finder-model", "evaluator-model"]


class StandIn(BaseHTTPRequestHandler):
    provider = FakeProvider()
    required_key = None
    received = []

    def log_message(self, *args):
        pass

    def _send(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorised(self):
        return not self.required_key or self.headers.get("Authorization") == f"Bearer {self.required_key}"

    def do_GET(self):
        if not self._authorised():
            return self._send(401, {"error": {"message": "invalid api key"}})
        if self.path == "/v1/models":
            return self._send(200, {"data": [{"id": name} for name in MODELS]})
        return self._send(404, {"error": {"message": "not found"}})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        StandIn.received.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        if not self._authorised():
            return self._send(401, {"error": {"message": "invalid api key"}})
        if self.path != "/v1/chat/completions":
            return self._send(404, {"error": {"message": "not found"}})
        if body["model"] not in MODELS:
            return self._send(404, {"error": {"message": "model does not exist"}})
        reply = StandIn.provider("", headers={}, json=body)
        return self._send(reply.status_code, reply._payload if reply._payload is not None else {"error": {"message": reply.text}})


@pytest.fixture
def stand_in():
    StandIn.provider = FakeProvider()
    StandIn.required_key = None
    StandIn.received = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), StandIn)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    server.shutdown()
    server.server_close()


def env_file(tmp_path, base_url, key="local-test-key"):
    path = tmp_path / ".env"
    path.write_text(
        f"LLM_BASE_URL={base_url}\nLLM_API_KEY={key}\nFINDER_MODEL=finder-model\nEVALUATOR_MODEL=evaluator-model\n"
        "LLM_REQUESTS_PER_MINUTE=0\nLLM_TOKENS_PER_MINUTE=0\n",
        encoding="utf-8",
    )
    return path


def test_full_ai_run_over_real_http(sample_zip, tmp_path, stand_in):
    StandIn.required_key = "local-test-key"
    summary = run_ai_pipeline(sample_zip, tmp_path / "run", env_path=env_file(tmp_path, stand_in), cache_dir=tmp_path / "cache")
    assert summary["complete"] and summary["verification_errors"] == [] and summary["recommended_clips"] >= 1
    assert summary["usage_totals"]["model_calls"] == len(StandIn.received)
    assert summary["usage_totals"]["total_tokens"] > 0
    assert all(request["path"] == "/v1/chat/completions" for request in StandIn.received)
    assert all(request["auth"] == "Bearer local-test-key" for request in StandIn.received)
    first = StandIn.received[0]["body"]
    assert first["temperature"] == 0 and first["response_format"] == {"type": "json_object"}
    assert {request["body"]["model"] for request in StandIn.received} == set(MODELS)
    assert load_promos(tmp_path / "run")


def test_wrong_key_over_real_http_is_reported_clearly(sample_zip, tmp_path, stand_in):
    StandIn.required_key = "the-right-key"
    summary = run_ai_pipeline(sample_zip, tmp_path / "run", env_path=env_file(tmp_path, stand_in, "the-wrong-key"), cache_dir=tmp_path / "cache")
    assert summary["complete"] is False and "auth" in summary["stopped_because"]
    assert "the-wrong-key" not in (tmp_path / "run" / "processing_summary.json").read_text()


def test_unknown_model_over_real_http_is_reported_clearly(sample_zip, tmp_path, stand_in):
    summary = run_ai_pipeline(sample_zip, tmp_path / "run", env_path=env_file(tmp_path, stand_in), cache_dir=tmp_path / "cache", finder_model="no-such-model")
    assert summary["complete"] is False and "model_not_found" in summary["stopped_because"]


def test_provider_check_over_real_http(stand_in):
    good = LLMClient(ModelConfig("finder", stand_in, "finder-model", "k")).check()
    assert good["ok"] is True
    missing = LLMClient(ModelConfig("finder", stand_in, "no-such-model", "k")).check()
    assert missing["ok"] is False and "finder-model" in missing["available_models"]


def test_provider_check_with_a_wrong_key(stand_in):
    StandIn.required_key = "the-right-key"
    result = LLMClient(ModelConfig("finder", stand_in, "finder-model", "wrong")).check()
    assert result["ok"] is False and "rejected the API key" in result["problem"]


def test_server_that_is_down_gives_a_clear_network_error():
    client = LLMClient(ModelConfig("finder", "http://127.0.0.1:9/v1", "m", "k", requests_per_minute=0, tokens_per_minute=0), sleep=lambda _: None, max_retries=1)
    with pytest.raises(LLMError) as error:
        client.chat_json("s", "u", "p", "v1")
    assert error.value.kind == "network"
