"""Settings for running the interface on this computer or on a host such as Streamlit Community Cloud.

AI settings come from the local .env file and, when present, from Streamlit secrets, which win.
On a hosted app the key lives only in the host's secrets store, never in the repository.

AI mode is open to every visitor and spends the owner's free model quota, so on a hosted app
each AI run is limited to AI_MAX_EPISODES episodes.
"""

from __future__ import annotations

from collections.abc import Mapping

MAX_EPISODES = "AI_MAX_EPISODES"
DEFAULT_MAX_EPISODES = 3
KEY_NAMES = ("LLM_API_KEY", "FINDER_API_KEY", "EVALUATOR_API_KEY")


def merge_settings(dotenv: Mapping, secrets: Mapping) -> dict[str, str]:
    """Plain values from .env, then from secrets. Secret sections (tables) are ignored."""
    merged: dict[str, str] = {}
    for source in (dotenv, secrets):
        for name, value in source.items():
            if value is None or isinstance(value, (Mapping, list, tuple)):
                continue
            text = str(value).strip()
            if text:
                merged[str(name)] = text
    return merged


def has_api_key(settings: Mapping) -> bool:
    return bool(settings.get("LLM_API_KEY") or (settings.get("FINDER_API_KEY") and settings.get("EVALUATOR_API_KEY")))


def max_episodes(settings: Mapping) -> int:
    try:
        value = int(settings.get(MAX_EPISODES, DEFAULT_MAX_EPISODES))
    except (TypeError, ValueError):
        return DEFAULT_MAX_EPISODES
    return max(1, value)


def parse_episode_selection(text: str, available: list[int]) -> tuple[set[int] | None, str]:
    """Turn '1-3,5' into {1, 2, 3, 5}. Empty means every episode. Returns (episodes, problem)."""
    text = (text or "").strip()
    if not text:
        return set(available), ""
    chosen: set[int] = set()
    try:
        for part in text.replace(" ", "").split(","):
            if "-" in part:
                low, high = (int(number) for number in part.split("-", 1))
                if low > high:
                    return None, f"'{part}' runs backwards."
                chosen.update(range(low, high + 1))
            elif part:
                chosen.add(int(part))
    except ValueError:
        return None, "Write episodes like 1-3,5."
    missing = sorted(chosen - set(available))
    if missing:
        return None, f"Not in this pack: episode(s) {missing}."
    if not chosen:
        return None, "No episodes chosen."
    return chosen, ""
