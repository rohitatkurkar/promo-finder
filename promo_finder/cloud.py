"""A small client for the parts of Supabase the app uses: rows in Postgres, through its REST API.

Runs only on the server. The secret key comes from Streamlit secrets (or .streamlit/secrets.toml
locally), is sent only to the Supabase project, and is removed from every error message.
Every call has a short timeout and a couple of retries, so an outage costs seconds, not minutes,
and the caller decides what to do about it.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

URL_SETTING = "SUPABASE_URL"
KEY_SETTING = "SUPABASE_SECRET_KEY"


class CloudError(Exception):
    def __init__(self, kind: str, detail: str):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind  # "network", "server", "auth", "rejected"
        self.detail = detail


@dataclass(frozen=True)
class SupabaseConfig:
    url: str
    key: str
    timeout_seconds: float = 10.0

    def __repr__(self) -> str:  # Never print the key.
        return f"SupabaseConfig(url={self.url!r}, key=<hidden>)"


def supabase_config(settings: Mapping) -> SupabaseConfig | None:
    """The project settings, or None when Supabase is not configured (the app then keeps files on disk)."""
    url = str(settings.get(URL_SETTING) or "").strip().rstrip("/")
    key = str(settings.get(KEY_SETTING) or "").strip()
    if not url or not key:
        return None
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"{URL_SETTING} must be an https address, like https://<project>.supabase.co")
    return SupabaseConfig(url=url, key=key)


def default_transport(method: str, url: str, **kwargs):
    return requests.request(method, url, **kwargs)


class SupabaseClient:
    def __init__(self, config: SupabaseConfig, transport=None, sleep=time.sleep, retries: int = 2):
        self.config = config
        # Looked up at call time, so tests can swap the module's default_transport.
        self._transport = transport
        self.sleep = sleep
        self.retries = retries

    def redact(self, text: str) -> str:
        return text.replace(self.config.key, "<hidden>") if self.config.key else text

    def _headers(self, extra: dict | None = None) -> dict:
        headers = {"apikey": self.config.key, "Content-Type": "application/json"}
        if not self.config.key.startswith("sb_"):
            # A legacy service_role key is a JWT and must also be sent as a bearer token. New sb_secret_ keys must not.
            headers["Authorization"] = f"Bearer {self.config.key}"
        headers.update(extra or {})
        return headers

    def _request(self, method: str, path: str, *, params=None, json=None, headers=None):
        transport = self._transport or default_transport
        url = f"{self.config.url}{path}"
        last: CloudError | None = None
        for attempt in range(self.retries + 1):
            if attempt:
                self.sleep(0.5 * 2 ** (attempt - 1))
            try:
                response = transport(method, url, params=params, json=json, headers=self._headers(headers),
                                     timeout=self.config.timeout_seconds)
            except requests.RequestException as error:
                last = CloudError("network", self.redact(f"{type(error).__name__}: {error}")[:300])
                continue
            status = response.status_code
            if status < 300:
                return response
            text = self.redact(getattr(response, "text", "") or "")[:300]
            if status in (401, 403):
                raise CloudError("auth", f"Supabase refused the key (HTTP {status}). Check SUPABASE_SECRET_KEY. {text}")
            if status == 429 or status >= 500:
                last = CloudError("server", f"HTTP {status}. {text}")
                continue
            raise CloudError("rejected", f"HTTP {status}. {text}")
        raise last or CloudError("network", "No response")

    def insert(self, table: str, rows: list[dict], ignore_duplicates_on: str | None = None) -> None:
        """Add rows. With ignore_duplicates_on (a unique column), rows already stored are skipped, so a retry is safe."""
        prefer = "return=minimal"
        params = None
        if ignore_duplicates_on:
            prefer = "resolution=ignore-duplicates,return=minimal"
            params = {"on_conflict": ignore_duplicates_on}
        self._request("POST", f"/rest/v1/{table}", params=params, json=rows, headers={"Prefer": prefer})

    def select(self, table: str, equals: Mapping[str, str], order: str | None = None, limit: int = 1000) -> list[dict]:
        """Rows whose columns equal the given values."""
        params = {"select": "*", "limit": str(limit)}
        params.update({column: f"eq.{value}" for column, value in equals.items()})
        if order:
            params["order"] = order
        return self._request("GET", f"/rest/v1/{table}", params=params).json()
