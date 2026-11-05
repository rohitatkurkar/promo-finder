"""Scoring weights, duplicate removal and the global ranking.

The score only compares clips against each other. It is not the probability of
an ad succeeding, and nothing in this project has measured ad performance.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .boundaries import Clip, intersection_over_union

# The brief names three things a promo must do, so those carry 80 percent.
# Hook and ending are equal because each one alone is wasted without the other:
# nobody sees a great ending if they scrolled past, and a great hook with a flat
# ending never sends anyone to the show. Understanding is slightly lower only
# because it is also a pass or fail gate in AI assisted mode.
WEIGHTS = {
    "hook": 0.30,
    "ending": 0.30,
    "understanding": 0.20,
    "emotion": 0.10,
    "continuity": 0.05,
    "duration": 0.05,
}

# Basic mode cannot judge a story, so it also asks how much of the writer's own episode
# summary a clip covers. Its parts are clues, not judgements, so no single clue dominates.
BASIC_WEIGHTS = {
    "hook": 0.25,
    "ending": 0.25,
    "understanding": 0.15,
    "key_moment": 0.10,
    "emotion": 0.10,
    "continuity": 0.05,
    "duration": 0.10,
}

SPOILER_PENALTY = {"low": 0.0, "medium": 5.0, "high": 15.0, "unknown": 0.0}

# Two clips count as "the same promo" when they share most of their time.
DUPLICATE_IOU = 0.5
# A short clip sitting almost entirely inside a longer one is also the same promo,
# even though their shared time looks small next to the longer clip's length.
DUPLICATE_CONTAINED = 0.7

# Posting several clips from one stretch of story is repetitive, so each clip
# already chosen lowers later clips from the same or the next episode.
SAME_EPISODE_PENALTY = 8.0
ADJACENT_EPISODE_PENALTY = 4.0
MAX_REPETITION_PENALTY = 12.0


@dataclass
class Scored:
    clip: Clip
    parts: dict[str, float]  # Each part runs from 0 to 100.
    penalties: dict[str, float] = field(default_factory=dict)
    payload: dict = field(default_factory=dict)
    weights: dict[str, float] = field(default_factory=lambda: dict(WEIGHTS))

    @property
    def base_score(self) -> float:
        total = sum(self.weights[name] * self.parts[name] for name in self.weights)
        return round(total - sum(self.penalties.values()), 2)


@dataclass
class Removed:
    clip_key: str
    kept_key: str
    reason: str


def are_duplicates(a: Clip, b: Clip) -> tuple[bool, str]:
    if a.episode != b.episode:
        return False, ""
    if a.hook_cue_id == b.hook_cue_id and a.ending_cue_id == b.ending_cue_id:
        return True, "same hook and same ending"
    iou = intersection_over_union(a.start, a.end, b.start, b.end)
    if iou >= DUPLICATE_IOU:
        return True, f"{iou:.2f} of their combined time is shared"
    shared = max(0.0, min(a.end, b.end) - max(a.start, b.start))
    shorter = min(a.duration, b.duration)
    if shorter > 0 and shared / shorter >= DUPLICATE_CONTAINED:
        return True, f"{shared / shorter:.2f} of the shorter clip sits inside the longer one"
    if a.hook_cue_id == b.hook_cue_id:
        return True, "same hook cue"
    if a.ending_cue_id == b.ending_cue_id:
        return True, "same ending cue"
    return False, ""


def remove_duplicates(items: list[Scored]) -> tuple[list[Scored], list[Removed]]:
    """Keep the stronger clip of each near identical pair and record the removal."""
    kept: list[Scored] = []
    removed: list[Removed] = []
    for item in sorted(items, key=lambda scored: (-scored.base_score, scored.clip.key)):
        for existing in kept:
            duplicate, why = are_duplicates(item.clip, existing.clip)
            if duplicate:
                removed.append(Removed(item.clip.key, existing.clip.key, why))
                break
        else:
            kept.append(item)
    return kept, removed


def rank_with_variety(items: list[Scored]) -> list[tuple[Scored, float, float]]:
    """Pick the best clip, lower its close neighbours, then pick the next best.

    Returns (item, repetition penalty applied, final score) in ranked order.
    """
    remaining = list(items)
    chosen: list[Scored] = []
    ranked: list[tuple[Scored, float, float]] = []
    while remaining:
        best = None
        best_final = -1e9
        best_penalty = 0.0
        for item in sorted(remaining, key=lambda scored: scored.clip.key):
            penalty = 0.0
            for picked in chosen:
                gap = abs(picked.clip.episode - item.clip.episode)
                if gap == 0:
                    penalty += SAME_EPISODE_PENALTY
                elif gap == 1:
                    penalty += ADJACENT_EPISODE_PENALTY
            penalty = min(penalty, MAX_REPETITION_PENALTY)
            final = item.base_score - penalty
            if final > best_final:
                best, best_final, best_penalty = item, final, penalty
        ranked.append((best, best_penalty, round(best_final, 2)))
        chosen.append(best)
        remaining.remove(best)
    return ranked


def strength_from_rating(rating: float | None) -> str:
    """Turn a 1 to 5 rating into a label. Only 4 and above counts as strong."""
    if rating is None:
        return "not_rated"
    if rating >= 4:
        return "strong"
    if rating >= 3:
        return "medium"
    return "weak"
