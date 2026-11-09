"""Shared test helpers. All screenplay text in the tests is invented."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "sample_input"))

from make_sample import build, episode_text  # noqa: E402

from promo_finder.parser import parse_episode_text  # noqa: E402
from promo_finder.prompts import COLD_VIEWER_SYSTEM, FINALIST_SYSTEM, FINDER_SYSTEM, HOOK_SYSTEM  # noqa: E402


@pytest.fixture
def sample_zip(tmp_path):
    return build(tmp_path / "The Lighthouse Debt-scripts.zip")


def make_episode(cues, number=1, end=None, heading="INT. ROOM - DAY", logline="Secret logline text.", notes="Secret continuity text."):
    """Build a parsed episode from (label, start, end, text) rows."""
    scene_end = end if end is not None else max(row[2] for row in cues)
    text = episode_text(number, logline, notes, [(heading, 0.0, scene_end, cues)])
    return parse_episode_text(text, f"episode-{number:03d}.txt")


def dialogue_rows(start, count, seconds=3.0, speaker="ANNA (Furious)", other="BEN (Cold)"):
    """Alternating dialogue lines, with a meaningful sentence on each."""
    rows = []
    moment = start
    for index in range(count):
        label = speaker if index % 2 == 0 else other
        rows.append((label, moment, moment + seconds - 0.2, f"You betrayed this family on day number {index + 1}!"))
        moment += seconds
    return rows


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=None, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload or {})
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def ok_reply(content, input_tokens=100, output_tokens=50):
    return FakeResponse(200, {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": input_tokens, "completion_tokens": output_tokens},
    })


class FakeProvider:
    """Stands in for a real API. Records every request so tests can inspect prompts."""

    def __init__(self, hook_rating=4, ending_rating=4, fail_finder_episodes=(), understood=True):
        self.requests = []
        self.hook_rating = hook_rating
        self.ending_rating = ending_rating
        self.fail_finder_episodes = set(fail_finder_episodes)
        self.understood = understood

    def __call__(self, url, headers=None, json=None, timeout=None):  # noqa: A002
        self.requests.append({"url": url, "headers": headers, "body": json})
        system = json["messages"][0]["content"]
        user = json["messages"][1]["content"]
        if system == FINDER_SYSTEM:
            return self._finder(user)
        if system == HOOK_SYSTEM:
            return ok_reply(_dump({"what_grabs_attention": "An accusation lands at once.", "what_is_missing": "nothing", "rating": self.hook_rating}))
        if system == COLD_VIEWER_SYSTEM:
            quoted = re.findall(r'SPEAKER [A-Z](?: \([^)]*\))?: "(.*)"', user)
            return ok_reply(_dump({
                "who_appears_involved": "Two people in conflict",
                "what_is_happening": "One person accuses the other",
                "main_conflict": "An accusation of betrayal" if self.understood else "unclear",
                "wants_to_know_next": "What the accused person does next" if self.understood else "unclear",
                "evidence_lines": quoted[:1],
                "missing_context": "nothing",
                "conflict_understood": self.understood,
                "question_understood": self.understood,
                "clarity_rating": 4,
                "ending_rating": self.ending_rating,
                "ending_resolves_conflict": False,
                "emotional_impact": 4,
                "plays_as_one_moment": 4,
            }))
        if system == FINALIST_SYSTEM:
            keys = re.findall(r"clip_key: (\S+)", user)
            return ok_reply(_dump({"clips": [{
                "clip_key": key, "spoiler_risk": "low", "what_it_gives_away": "little", "premise_fit": 5,
                "premise_reason": "states the central conflict", "ad_platform_risk": "low", "ad_platform_reason": "none",
            } for key in keys]}))
        raise AssertionError("Unexpected prompt")

    def _finder(self, user):
        number = int(re.search(r"EPISODE: (\d+)", user).group(1))
        if number in self.fail_finder_episodes:
            return FakeResponse(500, text="server error")
        rows = re.findall(r"^(E\d+_C\d+) \| (LINE|ACTION) \| ([^|]*) \| (.*)$", user, flags=re.MULTILINE)
        hooks = [row for row in rows if row[1] == "LINE" and "!" in row[3]][:3] or rows[:1]
        endings = [row for row in rows if row[1] == "LINE"][-3:]
        return ok_reply(_dump({
            "hook_events": [{"cue_id": row[0], "quote": row[3][:15], "event": "shock", "why": "stops the scroll", "strength": 4} for row in hooks],
            "ending_events": [{"cue_id": row[0], "quote": row[3][:15], "event": "open", "open_question": "what next", "strength": 4} for row in endings],
        }))


def _dump(value):
    return json.dumps(value)


def write_env(path, api_key="test-key-abc123456789", finder="finder-model", evaluator="evaluator-model"):
    path.write_text(
        f"LLM_BASE_URL=https://api.example.test/v1\nLLM_API_KEY={api_key}\nFINDER_MODEL={finder}\nEVALUATOR_MODEL={evaluator}\n"
        "LLM_REQUESTS_PER_MINUTE=0\nLLM_TOKENS_PER_MINUTE=0\nLLM_PRICE_INPUT_PER_MILLION=0.1\nLLM_PRICE_OUTPUT_PER_MILLION=0.2\n",
        encoding="utf-8",
    )
    return path


SUPABASE_TEST_URL = "https://project.supabase.test"
SUPABASE_TEST_KEY = "sb_secret_TEST_ONLY_not_a_real_key_0123456789"


class FakeSupabase:
    """Just enough of Supabase's REST API for the reviews table: insert (optionally skipping duplicates) and filtered
    select. Set `down` to make every call fail like a network outage. No network is used."""

    def __init__(self):
        self.rows: list[dict] = []
        self.calls: list[dict] = []
        self.down = False
        self.status: int | None = None  # Answer every call with this HTTP status instead.

    def __call__(self, method, url, params=None, json=None, headers=None, timeout=None):  # noqa: A002
        import uuid

        import requests
        self.calls.append({"method": method, "url": url, "params": params, "json": json, "headers": headers})
        if self.down:
            raise requests.ConnectionError("connection refused")
        if self.status:
            return FakeResponse(self.status, text="error")
        assert url.startswith(f"{SUPABASE_TEST_URL}/rest/v1/reviews")
        if method == "POST":
            stored = {row["review_id"] for row in self.rows}
            for row in json:
                row = dict(row, review_id=str(uuid.UUID(row["review_id"])))
                if row["review_id"] in stored:
                    if (params or {}).get("on_conflict") == "review_id":
                        continue
                    return FakeResponse(409, text="duplicate key")
                self.rows.append(row)
                stored.add(row["review_id"])
            return FakeResponse(201, text="")
        filters = {key: value[3:] for key, value in (params or {}).items() if str(value).startswith("eq.")}
        found = [row for row in self.rows if all(str(row.get(key)) == value for key, value in filters.items())]
        return FakeResponse(200, payload=sorted(found, key=lambda row: row["saved_at"]))
