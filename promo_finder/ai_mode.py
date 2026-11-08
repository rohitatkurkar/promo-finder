"""AI assisted mode: models judge the story, code stays in charge of the facts.

The order of work:
1. The FINDER reads an episode and returns hook and ending cue IDs.
2. Code checks those IDs are real and builds clips from the screenplay's own times.
3. A different model runs two blind tests on each clip:
   the HOOK TEST sees only the first three seconds,
   the COLD VIEWER sees only the clip with names hidden.
4. A clip is recommended only if it passes every gate in gate_failures().
5. Finalists get a spoiler and premise check using the story outline.

Model replies are treated as untrusted input. Anything invented is dropped and recorded.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from itertools import product

from .boundaries import (
    Clip,
    build_clip,
    cues_in_range,
    is_continuation,
    previous_dialogue,
)
from .llm_client import FATAL_KINDS, LLMClient, LLMError
from .masking import blind_clip, blind_first_three_seconds, quote_is_in
from .parser import DIALOGUE, STORY_KINDS, Episode
from .prompts import (
    COLD_VIEWER_SYSTEM,
    COLD_VIEWER_VERSION,
    FINALIST_SYSTEM,
    FINALIST_VERSION,
    FINDER_SYSTEM,
    FINDER_VERSION,
    HOOK_SYSTEM,
    HOOK_VERSION,
    build_cold_viewer_prompt,
    build_finalist_prompt,
    build_finder_prompt,
    build_hook_prompt,
    build_outline,
)
from .ranking import SPOILER_PENALTY, Scored, are_duplicates
from .signals import continuity_signal, duration_signal

MAX_CANDIDATES_PER_EPISODE = 3
STRONG_RATING = 4
FINALIST_BATCH = 8

TIMESTAMP_TEXT = re.compile(r"\b\d{1,2}:\d{2}(?:\.\d+)?\b")
TIME_KEYS = {"start", "end", "time", "timestamp", "start_time", "end_time", "start_seconds", "end_seconds", "duration"}
UNCLEAR = {"", "unclear", "unknown", "none", "n/a", "not clear", "cannot tell"}


@dataclass
class ModelIssue:
    where: str
    kind: str
    detail: str


@dataclass
class FinderEvent:
    cue_id: str
    strength: int
    description: str
    reason: str
    verified_quote: bool


@dataclass
class FinderOutcome:
    episode: int
    hooks: list[FinderEvent] = field(default_factory=list)
    endings: list[FinderEvent] = field(default_factory=list)
    issues: list[ModelIssue] = field(default_factory=list)


@dataclass
class RejectedPair:
    hook_cue_id: str
    ending_cue_id: str
    reason: str
    detail: str


def parse_rating(value, name: str, where: str, issues: list[ModelIssue], low: int = 1, high: int = 5) -> int | None:
    """Accept only a number in the permitted range. Anything else is recorded and discarded."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        issues.append(ModelIssue(where, "rating_not_a_number", f"{name}={value!r}"))
        return None
    if not low <= value <= high:
        issues.append(ModelIssue(where, "rating_out_of_range", f"{name}={value!r} is not between {low} and {high}"))
        return None
    return int(round(value))


def _find_invented_times(value, where: str, issues: list[ModelIssue], path: str = "") -> None:
    """The model was told not to give times. If it does, note it. They are never used anyway."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in TIME_KEYS:
                issues.append(ModelIssue(where, "invented_timestamp", f"Ignored field {path}{key}={item!r}"))
            _find_invented_times(item, where, issues, f"{path}{key}.")
    elif isinstance(value, list):
        for item in value:
            _find_invented_times(item, where, issues, path)
    elif isinstance(value, str) and TIMESTAMP_TEXT.search(value):
        issues.append(ModelIssue(where, "invented_timestamp", f"Time written in text at {path.rstrip('.')}"))


def validate_finder_reply(reply: dict, episode: Episode) -> FinderOutcome:
    """Keep only events that point at real, usable cues in this episode."""
    outcome = FinderOutcome(episode.number)
    where = f"finder E{episode.number:02d}"
    cues = {cue.cue_id: cue for cue in episode.cues}
    _find_invented_times(reply, where, outcome.issues)

    for field_name, target, reason_key in (
        ("hook_events", outcome.hooks, "why"),
        ("ending_events", outcome.endings, "open_question"),
    ):
        events = reply.get(field_name)
        if events is None:
            outcome.issues.append(ModelIssue(where, "missing_field", field_name))
            continue
        if not isinstance(events, list):
            outcome.issues.append(ModelIssue(where, "wrong_type", f"{field_name} is not a list"))
            continue
        seen: set[str] = set()
        for event in events:
            if not isinstance(event, dict):
                outcome.issues.append(ModelIssue(where, "wrong_type", f"{field_name} holds a non object"))
                continue
            cue_id = str(event.get("cue_id", "")).strip()
            cue = cues.get(cue_id)
            if cue is None:
                outcome.issues.append(ModelIssue(where, "unknown_cue_id", f"{field_name}: {cue_id!r} does not exist in this episode"))
                continue
            if cue.kind not in STORY_KINDS:
                outcome.issues.append(ModelIssue(where, "non_story_cue", f"{field_name}: {cue_id} is a {cue.kind} cue"))
                continue
            if cue_id in seen:
                continue
            seen.add(cue_id)
            strength = parse_rating(event.get("strength"), f"{cue_id}.strength", where, outcome.issues)
            if strength is None:
                continue
            quote = str(event.get("quote", "")).strip()
            verified = bool(quote) and quote_is_in(quote, cue.text)
            if quote and not verified:
                # The cue is real but this text is not in it, so the text is thrown away.
                outcome.issues.append(ModelIssue(where, "invented_quote", f"{cue_id}: quote does not match the screenplay. Text discarded."))
            target.append(FinderEvent(cue_id, strength, str(event.get("event", ""))[:200],
                                      str(event.get(reason_key, ""))[:300], verified))
    return outcome


def _sentence_start(episode: Episode, cue):
    """Walk back to where the speaker began a sentence split across several lines."""
    current = cue
    while is_continuation(current):
        previous = previous_dialogue(episode, current)
        if previous is None or previous.speaker != current.speaker:
            break
        current = previous
    return current


def pair_events(episode: Episode, outcome: FinderOutcome) -> tuple[list[tuple[Clip, int]], list[RejectedPair]]:
    """Try every hook with every ending. Keep valid clips and record why others failed."""
    valid: list[tuple[Clip, int]] = []
    rejected: list[RejectedPair] = []
    for hook_event, ending_event in product(outcome.hooks, outcome.endings):
        hook = episode.cue(hook_event.cue_id)
        ending = episode.cue(ending_event.cue_id)
        built = build_clip(episode, hook, ending)
        if not built.ok and built.reason == "hook_starts_mid_sentence":
            sentence_start = _sentence_start(episode, hook)
            if sentence_start.cue_id != hook.cue_id:
                built = build_clip(episode, sentence_start, ending)
                if built.ok:
                    built.clip.adjustments.append(
                        f"Hook moved from {hook.cue_id} to {sentence_start.cue_id}, where the sentence begins."
                    )
        if built.ok:
            valid.append((built.clip, hook_event.strength + ending_event.strength))
        else:
            rejected.append(RejectedPair(hook_event.cue_id, ending_event.cue_id, built.reason, built.detail))
    return valid, rejected


def select_candidates(valid: list[tuple[Clip, int]], limit: int = MAX_CANDIDATES_PER_EPISODE) -> list[Clip]:
    """Take the finder's most confident clips that are really different moments."""
    chosen: list[Clip] = []
    for clip, _ in sorted(valid, key=lambda pair: (-pair[1], pair[0].key)):
        if len(chosen) >= limit:
            break
        if not any(are_duplicates(clip, other)[0] for other in chosen):
            chosen.append(clip)
    return chosen


def find_moments(episode: Episode, title: str, client: LLMClient) -> FinderOutcome:
    result = client.chat_json(
        FINDER_SYSTEM, build_finder_prompt(episode, title), "finder", FINDER_VERSION, episode.content_hash,
    )
    return validate_finder_reply(result.data, episode)


def _text_field(reply: dict, name: str) -> str:
    value = reply.get(name, "")
    return value.strip() if isinstance(value, str) else ""


def _bool_field(reply: dict, name: str, where: str, issues: list[ModelIssue]) -> bool | None:
    value = reply.get(name)
    if isinstance(value, bool):
        return value
    issues.append(ModelIssue(where, "not_true_or_false", f"{name}={value!r}"))
    return None


def evaluate_clip(clip: Clip, episode: Episode, labels: set[str], names: set[str], client: LLMClient,
                  stop_after_weak_hook: bool = False) -> dict:
    """Run both blind tests. No logline, finder reason or score is ever sent.

    A clip with a weak hook cannot pass, so stop_after_weak_hook saves the longer
    cold viewer call. Comparisons between modes run both tests on every clip.
    """
    where = f"evaluator {clip.key}"
    issues: list[ModelIssue] = []

    first_seconds = blind_first_three_seconds(episode, clip.start, labels, names)
    hook_reply = client.chat_json(
        HOOK_SYSTEM, build_hook_prompt(first_seconds.text), "hook_test", HOOK_VERSION, episode.content_hash,
    ).data
    hook_rating = parse_rating(hook_reply.get("rating"), "hook rating", where, issues)
    if stop_after_weak_hook and hook_rating is not None and hook_rating < STRONG_RATING:
        return {
            "clip_key": clip.key,
            "hook_rating": hook_rating,
            "what_grabs_attention": _text_field(hook_reply, "what_grabs_attention"),
            "what_is_missing": _text_field(hook_reply, "what_is_missing"),
            "cold_viewer_skipped": True,
            "issues": [asdict(issue) for issue in issues],
        }

    whole_clip = blind_clip(episode, clip.start, clip.end, labels, names)
    cold_reply = client.chat_json(
        COLD_VIEWER_SYSTEM, build_cold_viewer_prompt(whole_clip.text), "cold_viewer", COLD_VIEWER_VERSION, episode.content_hash,
    ).data

    verified: list[str] = []
    unverified: list[str] = []
    lines = cold_reply.get("evidence_lines")
    if isinstance(lines, list):
        for line in lines:
            if isinstance(line, str) and line.strip():
                (verified if quote_is_in(line, whole_clip.text) else unverified).append(line.strip())
    if unverified:
        issues.append(ModelIssue(where, "invented_evidence", f"{len(unverified)} evidence line(s) are not in the clip"))

    return {
        "clip_key": clip.key,
        "hook_rating": hook_rating,
        "what_grabs_attention": _text_field(hook_reply, "what_grabs_attention"),
        "what_is_missing": _text_field(hook_reply, "what_is_missing"),
        "who_appears_involved": _text_field(cold_reply, "who_appears_involved"),
        "what_is_happening": _text_field(cold_reply, "what_is_happening"),
        "main_conflict": _text_field(cold_reply, "main_conflict"),
        "wants_to_know_next": _text_field(cold_reply, "wants_to_know_next"),
        "missing_context": _text_field(cold_reply, "missing_context"),
        "verified_evidence": verified,
        "unverified_evidence": unverified,
        "conflict_understood": _bool_field(cold_reply, "conflict_understood", where, issues),
        "question_understood": _bool_field(cold_reply, "question_understood", where, issues),
        "clarity_rating": parse_rating(cold_reply.get("clarity_rating"), "clarity_rating", where, issues),
        "ending_rating": parse_rating(cold_reply.get("ending_rating"), "ending_rating", where, issues),
        "ending_resolves_conflict": _bool_field(cold_reply, "ending_resolves_conflict", where, issues),
        "emotional_impact": parse_rating(cold_reply.get("emotional_impact"), "emotional_impact", where, issues),
        "plays_as_one_moment": parse_rating(cold_reply.get("plays_as_one_moment"), "plays_as_one_moment", where, issues),
        "issues": [asdict(issue) for issue in issues],
    }


def cold_viewer_passes(evaluation: dict) -> bool:
    """The clip must make the conflict and the open question clear, with real evidence."""
    return (
        evaluation.get("conflict_understood") is True
        and evaluation.get("question_understood") is True
        and evaluation.get("main_conflict", "").lower().strip(" .") not in UNCLEAR
        and evaluation.get("wants_to_know_next", "").lower().strip(" .") not in UNCLEAR
        and len(evaluation.get("verified_evidence", [])) >= 1
    )


def gate_failures(evaluation: dict) -> list[str]:
    """Reasons this clip cannot be recommended. Empty means it passed every gate."""
    failures: list[str] = []
    hook = evaluation.get("hook_rating")
    if hook is None:
        failures.append("hook_not_rated")
    elif hook < STRONG_RATING:
        failures.append(f"hook_rated_{hook}_of_5_not_strong")
    if evaluation.get("cold_viewer_skipped"):
        return failures  # Only the hook was tested, so nothing else can be said about this clip.
    ending = evaluation.get("ending_rating")
    if ending is None:
        failures.append("ending_not_rated")
    elif ending < STRONG_RATING:
        failures.append(f"ending_rated_{ending}_of_5_not_strong")
    if evaluation.get("ending_resolves_conflict") is True:
        failures.append("ending_resolves_the_conflict")
    if not cold_viewer_passes(evaluation):
        failures.append("cold_viewer_failed")
    return failures


def _to_percent(rating: int | None) -> float:
    return 0.0 if rating is None else round((rating - 1) / 4 * 100, 1)


def score_evaluated_clip(clip: Clip, episode: Episode, evaluation: dict, finalist: dict | None) -> Scored:
    moment = _to_percent(evaluation.get("plays_as_one_moment"))
    continuity = round(0.5 * moment + 0.5 * continuity_signal(episode, clip).value * 100, 1)
    parts = {
        "hook": _to_percent(evaluation.get("hook_rating")),
        "ending": _to_percent(evaluation.get("ending_rating")),
        "understanding": _to_percent(evaluation.get("clarity_rating")),
        "emotion": _to_percent(evaluation.get("emotional_impact")),
        "continuity": continuity,
        "duration": round(duration_signal(clip).value * 100, 1),
    }
    spoiler = (finalist or {}).get("spoiler_risk", "unknown")
    penalty = SPOILER_PENALTY.get(spoiler, 0.0)
    return Scored(clip, parts, {"spoiler_risk": penalty} if penalty else {},
                  {"evaluation": evaluation, "finalist": finalist or {}})


def review_finalists(
    clips: list[tuple[Clip, Episode]], title: str, episodes: list[Episode], client: LLMClient, script_hash: str
) -> tuple[dict[str, dict], list[dict]]:
    """Spoiler, premise and ad risk review, using the story outline.

    Each batch sees summaries only up to the latest episode among its own clips.
    """
    reviews: dict[str, dict] = {}
    issues: list[ModelIssue] = []
    for position in range(0, len(clips), FINALIST_BATCH):
        batch = clips[position:position + FINALIST_BATCH]
        outline = build_outline(episodes, max(clip.episode for clip, _ in batch))
        blocks = []
        for clip, episode in batch:
            lines = [f"{cue.text}" for cue in cues_in_range(episode, clip.start, clip.end) if cue.kind == DIALOGUE]
            blocks.append(f"clip_key: {clip.key} | Episode {clip.episode}\n" + " / ".join(lines))
        try:
            reply = client.chat_json(
                FINALIST_SYSTEM, build_finalist_prompt(title, outline, "\n\n".join(blocks)),
                "finalist_review", FINALIST_VERSION, script_hash,
            ).data
        except LLMError as error:
            if error.kind in FATAL_KINDS:
                raise
            # One failed batch should not lose the others. These clips will say "unknown".
            issues.append(ModelIssue("finalist_review", error.kind, client.redact(error.detail)[:200]))
            continue
        keys = {clip.key for clip, _ in batch}
        entries = reply.get("clips")
        if not isinstance(entries, list):
            issues.append(ModelIssue("finalist_review", "wrong_type", "clips is not a list"))
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("clip_key", ""))
            if key not in keys:
                issues.append(ModelIssue("finalist_review", "unknown_clip_key", key))
                continue
            spoiler = entry.get("spoiler_risk")
            if spoiler not in ("low", "medium", "high"):
                issues.append(ModelIssue("finalist_review", "bad_value", f"{key} spoiler_risk={spoiler!r}"))
                spoiler = "unknown"
            ad_risk = entry.get("ad_platform_risk")
            if ad_risk not in ("low", "medium", "high"):
                issues.append(ModelIssue("finalist_review", "bad_value", f"{key} ad_platform_risk={ad_risk!r}"))
                ad_risk = "unknown"
            reviews[key] = {
                "spoiler_risk": spoiler,
                "what_it_gives_away": _text_field(entry, "what_it_gives_away"),
                "premise_fit": parse_rating(entry.get("premise_fit"), f"{key}.premise_fit", "finalist_review", issues),
                "premise_reason": _text_field(entry, "premise_reason"),
                "ad_platform_risk": ad_risk,
                "ad_platform_reason": _text_field(entry, "ad_platform_reason"),
            }
    return reviews, [asdict(issue) for issue in issues]


__all__ = [
    "LLMError", "ModelIssue", "FinderOutcome", "RejectedPair", "validate_finder_reply", "pair_events",
    "select_candidates", "find_moments", "evaluate_clip", "gate_failures", "cold_viewer_passes",
    "score_evaluated_clip", "review_finalists", "parse_rating",
]
