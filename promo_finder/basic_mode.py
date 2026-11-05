"""Basic mode: find promo candidates with ordinary code, no API key needed.

It looks at every sensible pairing of an opening and an ending in an episode,
keeps the pairs that make a valid clip, and ranks them on transparent signals.

It has no real understanding of the story. It cannot tell whether a line is
shocking, only whether it has features shocking lines often have. Its labels
always say "signals", and they are never presented as an actual judgement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product

from .boundaries import MAX_DURATION, MIN_DURATION, Clip, build_clip, clip_summary
from .parser import Episode
from .ranking import BASIC_WEIGHTS, Scored, are_duplicates
from .signals import (
    ad_risk_warnings,
    continuity_signal,
    duration_signal,
    emotion_signal,
    ending_signal,
    hook_signal,
    key_moment_signal,
    meaningful_story_cues,
    spoiler_position_penalty,
    understanding_signal,
)

# Only the most promising openings and endings of each episode are paired.
TOP_HOOKS_PER_EPISODE = 20
TOP_ENDINGS_PER_EPISODE = 14
MAX_CLIPS_PER_EPISODE = 2
# Below this an episode offers nothing worth recommending. We do not force a pick.
MIN_SCORE_TO_KEEP = 60.0
# A promo needs a hook AND an ending. Adding scores together let a strong hook
# hide a weak ending, so each part must clear its own floor.
MIN_HOOK_PART = 50.0
MIN_ENDING_PART = 50.0
MIN_UNDERSTANDING_PART = 40.0  # Lower, because this clue only reads spoken words and misses what is shown.
BASIC_VERSION = "basic_v3"
# Openings and endings under these levels are not treated as real events.
MIN_HOOK_SIGNAL = 0.25
MIN_ENDING_SIGNAL = 0.25


@dataclass
class BasicEpisodeResult:
    episode: int
    pairs_tried: int = 0
    valid_clips: int = 0
    rejection_counts: dict[str, int] = field(default_factory=dict)
    kept: list[Scored] = field(default_factory=list)


def score_clip(episode: Episode, clip: Clip, last_episode: int, next_notes: str = "") -> Scored:
    hook = hook_signal(episode, episode.cue(clip.hook_cue_id), clip.start)
    ending = ending_signal(episode, episode.cue(clip.ending_cue_id), next_notes)
    key_moment = key_moment_signal(episode, clip)
    understanding = understanding_signal(episode, clip)
    emotion = emotion_signal(episode, clip)
    continuity = continuity_signal(episode, clip)
    duration = duration_signal(clip)
    parts = {
        "hook": round(hook.value * 100, 1),
        "ending": round(ending.value * 100, 1),
        "understanding": round(understanding.value * 100, 1),
        "key_moment": round(key_moment.value * 100, 1),
        "emotion": round(emotion.value * 100, 1),
        "continuity": round(continuity.value * 100, 1),
        "duration": round(duration.value * 100, 1),
    }
    penalty = spoiler_position_penalty(episode.number, last_episode)
    return Scored(
        clip,
        parts,
        {"late_story_position": penalty} if penalty else {},
        {
            "hook_reasons": hook.reasons,
            "ending_reasons": ending.reasons,
            "understanding_reasons": understanding.reasons,
            "emotion_reasons": emotion.reasons,
            "continuity_reasons": continuity.reasons,
            "key_moment_reasons": key_moment.reasons,
            "ad_warnings": ad_risk_warnings(episode, clip),
        },
        dict(BASIC_WEIGHTS),
    )


def candidates_for_episode(episode: Episode, last_episode: int, next_notes: str = "") -> BasicEpisodeResult:
    result = BasicEpisodeResult(episode.number)
    story = meaningful_story_cues(episode)

    hook_rated = [(hook_signal(episode, cue).value, cue) for cue in story]
    hook_rated = [pair for pair in hook_rated if pair[0] >= MIN_HOOK_SIGNAL]
    hook_rated.sort(key=lambda pair: (-pair[0], pair[1].cue_id))

    ending_rated = [(ending_signal(episode, cue, next_notes).value, cue) for cue in story]
    ending_rated = [pair for pair in ending_rated if pair[0] >= MIN_ENDING_SIGNAL]
    ending_rated.sort(key=lambda pair: (-pair[0], pair[1].cue_id))

    scored: list[Scored] = []
    for (_, hook), (_, ending) in product(hook_rated[:TOP_HOOKS_PER_EPISODE], ending_rated[:TOP_ENDINGS_PER_EPISODE]):
        # Skip pairs that are clearly out of range before doing the full check.
        if ending.end - hook.start > MAX_DURATION + 2 or ending.end - hook.start < MIN_DURATION - 4:
            result.rejection_counts["duration_out_of_range"] = result.rejection_counts.get("duration_out_of_range", 0) + 1
            result.pairs_tried += 1
            continue
        result.pairs_tried += 1
        built = build_clip(episode, hook, ending)
        if not built.ok:
            result.rejection_counts[built.reason] = result.rejection_counts.get(built.reason, 0) + 1
            continue
        result.valid_clips += 1
        scored.append(score_clip(episode, built.clip, last_episode, next_notes))

    # Take the best clips from this episode that are really different moments.
    picked: list[Scored] = []
    for item in sorted(scored, key=lambda entry: (-entry.base_score, entry.clip.key)):
        if len(picked) >= MAX_CLIPS_PER_EPISODE or item.base_score < MIN_SCORE_TO_KEEP:
            break
        if (item.parts["hook"] < MIN_HOOK_PART or item.parts["ending"] < MIN_ENDING_PART
                or item.parts["understanding"] < MIN_UNDERSTANDING_PART):
            result.rejection_counts["below_a_required_floor"] = result.rejection_counts.get("below_a_required_floor", 0) + 1
            continue
        if not any(are_duplicates(item.clip, other.clip)[0] for other in picked):
            picked.append(item)
    result.kept = picked
    return result


def describe(item: Scored) -> str:
    """One line reason built only from signals, so nothing here claims understanding."""
    hook_reason = item.payload.get("hook_reasons") or ["no strong opening signal"]
    ending_reason = item.payload.get("ending_reasons") or ["no strong ending signal"]
    return f"Signals only: opens with {hook_reason[0]}; ends with {ending_reason[0]}."


__all__ = ["candidates_for_episode", "score_clip", "describe", "clip_summary"]
