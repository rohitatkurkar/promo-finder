"""Talk to any language model that offers an OpenAI compatible API.

Groq, Gemini, Anthropic, OpenRouter, Mistral, Cerebras and local Ollama all offer
this API shape, so changing provider only means changing three lines in `.env`.
That is why this is one small file and not a separate adapter per provider.

Keys are read from `.env` only, and are scrubbed from anything we store or print.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import requests

TRANSIENT_STATUS = {408, 409, 425, 500, 502, 503, 504, 520, 522, 524}
THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
RETRY_AFTER_TEXT = re.compile(r"try again in (?:(\d+)m)?\s*([\d.]+)\s*(ms|s)", re.IGNORECASE)


class LLMError(Exception):
    """A model call that failed after any retries. `kind` says what to do about it."""

    def __init__(self, kind: str, detail: str):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


# Without these the run cannot continue, so the pipeline stops and explains why.
FATAL_KINDS = {"missing_key", "auth", "rate_limit_exhausted", "model_not_found"}


@dataclass
class ModelConfig:
    role: str
    base_url: str
    model: str
    api_key: str = ""
    temperature: float = 0.0
    seed: int | None = 7
    max_output_tokens: int = 2000
    timeout_seconds: float = 90.0
    requests_per_minute: int = 25
    tokens_per_minute: int = 7000
    price_input_per_million: float | None = None
    price_output_per_million: float | None = None

    @property
    def provider(self) -> str:
        return urlparse(self.base_url).netloc or self.base_url

    @property
    def is_local(self) -> bool:
        return self.provider.split(":")[0] in ("localhost", "127.0.0.1")

    def settings_fingerprint(self) -> dict:
        """Settings that change a model's answer. The key is deliberately left out."""
        return {
            "provider": self.provider,
            "model": self.model,
            "temperature": self.temperature,
            "seed": self.seed,
            "max_output_tokens": self.max_output_tokens,
        }

    def __repr__(self) -> str:
        return f"ModelConfig(role={self.role!r}, provider={self.provider!r}, model={self.model!r}, api_key='***')"


def load_model_config(role: str, environ: dict | None = None, model_override: str | None = None) -> ModelConfig:
    """Read one role's settings. FINDER_MODEL wins over the shared LLM_MODEL, and so on."""
    env = os.environ if environ is None else environ
    prefix = role.upper()

    def read(name: str, default: str = "") -> str:
        return (env.get(f"{prefix}_{name}") or env.get(f"LLM_{name}") or default).strip()

    def read_float(name: str) -> float | None:
        value = read(name)
        try:
            return float(value) if value else None
        except ValueError:
            return None

    return ModelConfig(
        role=role,
        base_url=read("BASE_URL", "https://api.groq.com/openai/v1").rstrip("/"),
        model=model_override or read("MODEL"),
        api_key=read("API_KEY"),
        temperature=float(read("TEMPERATURE", "0") or 0),
        seed=int(read("SEED", "7") or 7),
        max_output_tokens=int(read("MAX_OUTPUT_TOKENS", "2000") or 2000),
        requests_per_minute=int(read("REQUESTS_PER_MINUTE", "25") or 25),
        tokens_per_minute=int(read("TOKENS_PER_MINUTE", "7000") or 7000),
        price_input_per_million=read_float("PRICE_INPUT_PER_MILLION"),
        price_output_per_million=read_float("PRICE_OUTPUT_PER_MILLION"),
    )


@dataclass
class LLMResult:
    data: dict
    raw_text: str
    cached: bool
    input_tokens: int | None
    output_tokens: int | None
    attempts: int


@dataclass
class UsageLedger:
    """A record of every model call, with no prompts and no keys."""

    path: Path | None = None
    records: list[dict] = field(default_factory=list)

    def add(self, record: dict) -> None:
        self.records.append(record)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(record) + "\n")

    def load_existing(self) -> None:
        if self.path is not None and self.path.exists():
            with self.path.open(encoding="utf-8") as handle:
                self.records = [json.loads(line) for line in handle if line.strip()]

    def summary(self, configs: dict[str, ModelConfig] | None = None) -> dict:
        configs = configs or {}
        by_role: dict[str, dict] = {}
        for record in self.records:
            entry = by_role.setdefault(record["role"], {
                "provider": record.get("provider"),
                "model": record.get("model"),
                "prompt_versions": set(),
                "model_calls": 0,
                "cached_calls": 0,
                "failed_calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "calls_without_token_usage": 0,
                "seconds_in_calls": 0.0,
            })
            entry["prompt_versions"].add(f"{record.get('prompt_id')}:{record.get('prompt_version')}")
            if record.get("cached"):
                entry["cached_calls"] += 1
                continue
            entry["model_calls"] += 1
            entry["seconds_in_calls"] += record.get("latency_seconds", 0.0)
            if record.get("status") != "ok":
                entry["failed_calls"] += 1
            if record.get("input_tokens") is None:
                if record.get("status") == "ok":
                    entry["calls_without_token_usage"] += 1
            else:
                entry["input_tokens"] += record["input_tokens"]
                entry["output_tokens"] += record.get("output_tokens") or 0
                entry["total_tokens"] += record["input_tokens"] + (record.get("output_tokens") or 0)

        totals = {"model_calls": 0, "cached_calls": 0, "failed_calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        cost_total = 0.0
        cost_known = True
        for role, entry in by_role.items():
            entry["prompt_versions"] = sorted(entry["prompt_versions"])
            entry["seconds_in_calls"] = round(entry["seconds_in_calls"], 1)
            for name in totals:
                totals[name] += entry[name]
            config = configs.get(role)
            if config and config.price_input_per_million is not None and config.price_output_per_million is not None:
                cost = (entry["input_tokens"] * config.price_input_per_million
                        + entry["output_tokens"] * config.price_output_per_million) / 1_000_000
                entry["cost_at_listed_paid_price_usd"] = round(cost, 5)
                cost_total += cost
            else:
                entry["cost_at_listed_paid_price_usd"] = None
                cost_known = False
        return {
            "by_role": by_role,
            "totals": totals,
            "cost_at_listed_paid_price_usd": round(cost_total, 5) if (cost_known and by_role) else None,
        }


def extract_json(text: str) -> dict:
    """Pull the JSON object out of a model reply, ignoring thinking blocks and code fences."""
    cleaned = THINK_BLOCK.sub("", text or "").strip()
    if not cleaned:
        raise LLMError("empty_response", "The model returned no usable text")
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", cleaned).strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        if start < 0:
            raise LLMError("invalid_json", "No JSON object in the reply") from None
        depth = 0
        in_string = False
        escaped = False
        for position in range(start, len(cleaned)):
            char = cleaned[position]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
            elif char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        value = json.loads(cleaned[start:position + 1])
                    except json.JSONDecodeError as error:
                        raise LLMError("invalid_json", f"Could not parse the reply: {error}") from error
                    break
        else:
            raise LLMError("invalid_json", "The JSON object in the reply is not complete")
    if not isinstance(value, dict):
        raise LLMError("invalid_json", "The reply is JSON but not an object")
    return value


class LLMClient:
    def __init__(
        self,
        config: ModelConfig,
        cache_dir: str | Path | None = None,
        ledger: UsageLedger | None = None,
        use_cache: bool = True,
        transport=requests.post,
        sleep=time.sleep,
        clock=time.monotonic,
        max_retries: int = 4,
        max_wait_seconds: float = 90.0,
    ):
        self.config = config
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.ledger = ledger or UsageLedger()
        self.use_cache = use_cache
        self.transport = transport
        self.sleep = sleep
        self.clock = clock
        self.max_retries = max_retries
        self.max_wait_seconds = max_wait_seconds
        self._recent_requests: deque[float] = deque()
        self._recent_tokens: deque[tuple[float, int]] = deque()
        self._send_seed = config.seed is not None
        self._send_json_mode = True

    def redact(self, text: str) -> str:
        """Remove the key from any text before it is stored or shown."""
        text = str(text)
        if self.config.api_key:
            text = text.replace(self.config.api_key, "***")
        return re.sub(r"(gsk|sk|xai|AIza)[-_][A-Za-z0-9_\-]{10,}", "***", text)

    def _check_ready(self) -> None:
        if not self.config.model:
            raise LLMError("missing_model", f"No model set for the {self.config.role} role. Copy .env.example to .env and fill it in. Basic mode works without one.")
        if not self.config.api_key and not self.config.is_local:
            raise LLMError(
                "missing_key",
                f"No API key for the {self.config.role} role. Copy .env.example to .env and add your key. "
                "Basic mode works without one.",
            )

    def _cache_path(self, key: str) -> Path | None:
        return self.cache_dir / f"{key}.json" if self.cache_dir else None

    def _pace(self, estimated_tokens: int) -> None:
        """Stay under the provider's per minute limits instead of hitting them."""
        now = self.clock()
        while self._recent_requests and now - self._recent_requests[0] > 60:
            self._recent_requests.popleft()
        while self._recent_tokens and now - self._recent_tokens[0][0] > 60:
            self._recent_tokens.popleft()
        wait = 0.0
        if self.config.requests_per_minute and len(self._recent_requests) >= self.config.requests_per_minute:
            wait = max(wait, 60 - (now - self._recent_requests[0]))
        used = sum(tokens for _, tokens in self._recent_tokens)
        if self.config.tokens_per_minute and used + estimated_tokens > self.config.tokens_per_minute and self._recent_tokens:
            needed = used + estimated_tokens - self.config.tokens_per_minute
            freed = 0
            for moment, tokens in self._recent_tokens:
                freed += tokens
                if freed >= needed:
                    wait = max(wait, 60 - (now - moment))
                    break
            else:
                wait = max(wait, 60 - (now - self._recent_tokens[-1][0]))
        if wait > 0:
            self.sleep(wait + 0.2)

    def _retry_delay(self, attempt: int, response=None) -> float:
        delay = 0.0
        if response is not None:
            header = response.headers.get("Retry-After") if hasattr(response, "headers") else None
            try:
                delay = float(header) if header else 0.0
            except ValueError:
                delay = 0.0
            if not delay:
                match = RETRY_AFTER_TEXT.search(getattr(response, "text", "") or "")
                if match:
                    minutes = int(match.group(1) or 0)
                    value = float(match.group(2))
                    delay = minutes * 60 + (value / 1000 if match.group(3).lower() == "ms" else value)
        return max(delay, 2.0 ** attempt)

    def chat_json(self, system: str, user: str, prompt_id: str, prompt_version: str, script_hash: str = "") -> LLMResult:
        """Send one prompt and return parsed JSON. Answers are cached and calls are recorded."""
        self._check_ready()
        key = hashlib.sha256(json.dumps({
            "settings": self.config.settings_fingerprint(),
            "prompt_id": prompt_id,
            "prompt_version": prompt_version,
            "script_hash": script_hash,
            "system": system,
            "user": user,
        }, sort_keys=True).encode("utf-8")).hexdigest()

        base_record = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "role": self.config.role,
            "provider": self.config.provider,
            "model": self.config.model,
            "prompt_id": prompt_id,
            "prompt_version": prompt_version,
        }

        cache_path = self._cache_path(key)
        if self.use_cache and cache_path is not None and cache_path.exists():
            saved = json.loads(cache_path.read_text(encoding="utf-8"))
            self.ledger.add({**base_record, "cached": True, "status": "ok", "input_tokens": saved.get("input_tokens"),
                             "output_tokens": saved.get("output_tokens"), "latency_seconds": 0.0, "attempts": 0})
            return LLMResult(saved["data"], saved["raw_text"], True, saved.get("input_tokens"), saved.get("output_tokens"), 0)

        started = self.clock()
        attempts = 0
        json_retry_used = False
        length_retry_used = False
        output_limit = self.config.max_output_tokens
        extra_note = ""
        last_error: LLMError | None = None

        while attempts <= self.max_retries:
            attempts += 1
            messages = [{"role": "system", "content": system}, {"role": "user", "content": user + extra_note}]
            body = {
                "model": self.config.model,
                "messages": messages,
                "temperature": self.config.temperature,
                "max_tokens": output_limit,
            }
            if self._send_seed:
                body["seed"] = self.config.seed
            if self._send_json_mode:
                body["response_format"] = {"type": "json_object"}

            estimated = (len(system) + len(user)) // 4 + min(self.config.max_output_tokens, 700)
            self._pace(estimated)
            self._recent_requests.append(self.clock())
            headers = {"Content-Type": "application/json"}
            if self.config.api_key:
                headers["Authorization"] = f"Bearer {self.config.api_key}"

            try:
                response = self.transport(
                    f"{self.config.base_url}/chat/completions",
                    headers=headers, json=body, timeout=self.config.timeout_seconds,
                )
            except requests.RequestException as error:
                last_error = LLMError("network", self.redact(f"{type(error).__name__}: {error}")[:300])
                if attempts > self.max_retries:
                    break
                self.sleep(min(self._retry_delay(attempts), self.max_wait_seconds))
                continue

            status = response.status_code
            if status in (401, 403):
                last_error = LLMError("auth", f"The provider rejected the API key (HTTP {status}). Check the key in .env.")
                break
            if status == 404:
                last_error = LLMError("model_not_found", self.redact(f"HTTP 404 for model {self.config.model}. {response.text[:200]}"))
                break
            if status == 429:
                delay = self._retry_delay(attempts, response)
                last_error = LLMError("rate_limit", self.redact(f"HTTP 429. {response.text[:300]}"))
                if delay > self.max_wait_seconds or attempts > self.max_retries:
                    # A wait this long means a daily limit. Stop now and resume later.
                    last_error = LLMError("rate_limit_exhausted", self.redact(
                        f"Rate limit reached, provider asked to wait {delay:.0f}s. Run the same command later to resume. "
                        f"{response.text[:200]}"))
                    break
                self.sleep(delay)
                continue
            if status == 400:
                text = response.text or ""
                lowered = text.lower()
                if "json_validate_failed" in lowered and "max completion tokens" in lowered and not length_retry_used:
                    # Groq's JSON mode reports running out of output room as an error instead of a cut-off reply.
                    self.ledger.add({**base_record, "cached": False, "status": "failed", "error_kind": "cut_off",
                                     "error_detail": "Provider ran out of output room before the JSON was complete; asked again with more room",
                                     "input_tokens": None, "output_tokens": None,
                                     "latency_seconds": round(self.clock() - started, 2), "attempts": attempts})
                    last_error = LLMError("cut_off", "The reply ran out of output room twice")
                    length_retry_used = True
                    output_limit = self.config.max_output_tokens * 2
                    continue
                if "json_validate_failed" in lowered and not json_retry_used:
                    json_retry_used = True
                    last_error = LLMError("invalid_json", "Provider could not produce valid JSON")
                    extra_note = "\n\nYour previous reply was not valid JSON. Reply with only one JSON object."
                    continue
                if "response_format" in lowered and self._send_json_mode:
                    self._send_json_mode = False
                    continue
                if "seed" in lowered and self._send_seed:
                    self._send_seed = False
                    continue
                last_error = LLMError("bad_request", self.redact(f"HTTP 400. {text[:300]}"))
                break
            if status in TRANSIENT_STATUS or status >= 500:
                last_error = LLMError("server", self.redact(f"HTTP {status}. {response.text[:200]}"))
                if attempts > self.max_retries:
                    break
                self.sleep(min(self._retry_delay(attempts, response), self.max_wait_seconds))
                continue
            if status >= 300:
                last_error = LLMError("http_error", self.redact(f"HTTP {status}. {response.text[:200]}"))
                break

            try:
                payload = response.json()
                text = payload["choices"][0]["message"].get("content") or ""
            except (ValueError, KeyError, IndexError, TypeError) as error:
                last_error = LLMError("malformed_response", self.redact(f"{type(error).__name__}: {error}")[:200])
                if json_retry_used:
                    break
                json_retry_used = True
                continue

            finish_reason = payload["choices"][0].get("finish_reason")
            usage = payload.get("usage") or {}
            input_tokens = usage.get("prompt_tokens")
            output_tokens = usage.get("completion_tokens")
            self._recent_tokens.append((self.clock(), (input_tokens or estimated) + (output_tokens or 0)))

            try:
                data = extract_json(text)
            except LLMError as error:
                self.ledger.add({**base_record, "cached": False, "status": "failed", "error_kind": error.kind,
                                 "error_detail": self.redact(error.detail)[:200], "input_tokens": input_tokens,
                                 "output_tokens": output_tokens, "latency_seconds": round(self.clock() - started, 2),
                                 "attempts": attempts})
                last_error = error
                if finish_reason == "length" and not length_retry_used:
                    # The reply ran out of room, which is common with models that reason first.
                    length_retry_used = True
                    output_limit = self.config.max_output_tokens * 2
                    continue
                if json_retry_used:
                    raise LLMError(error.kind, error.detail) from None
                json_retry_used = True
                extra_note = "\n\nYour previous reply was not valid JSON. Reply with only one JSON object."
                continue

            if finish_reason == "length" and not length_retry_used:
                # The reply hit the output limit but still parsed. A model that reasons first can run out of
                # room and close the JSON early, dropping whole fields, so ask once more with double the room.
                self.ledger.add({**base_record, "cached": False, "status": "failed", "error_kind": "cut_off",
                                 "error_detail": "Reply reached the output limit; asked again with more room",
                                 "finish_reason": finish_reason, "input_tokens": input_tokens,
                                 "output_tokens": output_tokens, "latency_seconds": round(self.clock() - started, 2),
                                 "attempts": attempts})
                length_retry_used = True
                output_limit = self.config.max_output_tokens * 2
                continue

            elapsed = round(self.clock() - started, 2)
            self.ledger.add({**base_record, "cached": False, "status": "ok", "input_tokens": input_tokens,
                             "output_tokens": output_tokens, "latency_seconds": elapsed, "attempts": attempts,
                             "finish_reason": finish_reason})
            if self.use_cache and cache_path is not None:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps({"data": data, "raw_text": text, "input_tokens": input_tokens,
                                                  "output_tokens": output_tokens}, ensure_ascii=False), encoding="utf-8", newline="\n")
            return LLMResult(data, text, False, input_tokens, output_tokens, attempts)

        error = last_error or LLMError("unknown", "The call failed for an unknown reason")
        self.ledger.add({**base_record, "cached": False, "status": "failed", "error_kind": error.kind,
                         "error_detail": self.redact(error.detail)[:300], "input_tokens": None, "output_tokens": None,
                         "latency_seconds": round(self.clock() - started, 2), "attempts": attempts})
        raise LLMError(error.kind, self.redact(error.detail))

    def check(self) -> dict:
        """Confirm the key works and the model exists, without sending any screenplay text."""
        self._check_ready()
        headers = {"Authorization": f"Bearer {self.config.api_key}"} if self.config.api_key else {}
        try:
            response = requests.get(f"{self.config.base_url}/models", headers=headers, timeout=30)
        except requests.RequestException as error:
            return {"ok": False, "problem": self.redact(f"network: {error}")[:200]}
        if response.status_code in (401, 403):
            return {"ok": False, "problem": f"The provider rejected the API key (HTTP {response.status_code})."}
        if response.status_code >= 300:
            return {"ok": False, "problem": f"HTTP {response.status_code} from the models list."}
        try:
            names = sorted(item.get("id", "") for item in response.json().get("data", []))
        except ValueError:
            return {"ok": False, "problem": "Could not read the models list."}
        return {"ok": self.config.model in names, "model": self.config.model, "provider": self.config.provider,
                "problem": "" if self.config.model in names else "Model is not in this provider's list.",
                "available_models": names}
