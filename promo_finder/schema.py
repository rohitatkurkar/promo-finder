"""The output format for a promo, and the checks that keep it honest.

Two levels of checking:
1. Pydantic checks the shape and basic rules of each promo.
2. verify_promo_against_screenplay() goes back to the parsed screenplay and proves
   that every time, cue ID and quotation really exists there. Nothing is trusted
   just because it appears in a results file.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .boundaries import HOOK_WINDOW, MAX_DURATION, MIN_DURATION
from .parser import Episode, format_timestamp

SCHEMA_VERSION = "1.0"
Strength = Literal["strong", "medium", "weak", "not_rated"]
Method = Literal["basic", "ai_assisted"]


class Segment(BaseModel):
    episode: int
    start_seconds: float
    end_seconds: float
    start_timestamp: str
    end_timestamp: str
    start_cue_id: str
    end_cue_id: str
    boundary_adjustments: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _times_make_sense(self):
        if self.end_seconds <= self.start_seconds:
            raise ValueError("Segment ends before it starts")
        if self.start_timestamp != format_timestamp(self.start_seconds):
            raise ValueError("start_timestamp does not match start_seconds")
        if self.end_timestamp != format_timestamp(self.end_seconds):
            raise ValueError("end_timestamp does not match end_seconds")
        return self


class Hook(BaseModel):
    cue_ids: list[str]
    evidence: str
    strength: Strength
    rating_out_of_5: float | None = None
    rated_by: str
    within_first_three_seconds: bool
    seconds_from_clip_start: float
    reason: str = ""


class Cliffhanger(BaseModel):
    cue_ids: list[str]
    evidence: str
    strength: Strength
    rating_out_of_5: float | None = None
    rated_by: str
    resolves_conflict: bool | None = None
    reason: str = ""


class ColdViewerCheck(BaseModel):
    """What a viewer who knows nothing could understand from the clip alone."""

    result: Literal["pass", "fail", "not_performed"]
    main_conflict_understood: bool | None = None
    unresolved_question_understood: bool | None = None
    who_appears_involved: str = ""
    what_is_happening: str = ""
    main_conflict: str = ""
    viewer_wants_to_know: str = ""
    verified_evidence_lines: list[str] = Field(default_factory=list)
    unverified_evidence_lines: list[str] = Field(default_factory=list)
    missing_context: str = ""


class HumanReview(BaseModel):
    status: Literal["not_reviewed", "reviewed"] = "not_reviewed"
    rating: float | None = None
    reviewer: str | None = None


class Promo(BaseModel):
    schema_version: str = SCHEMA_VERSION
    promo_id: str
    clip_key: str
    global_rank: int = Field(ge=1)
    first_post_recommendation: bool = False
    first_post_reason: str = ""
    segments: list[Segment] = Field(min_length=1, max_length=2)
    total_duration_seconds: float
    hook: Hook
    cliffhanger: Cliffhanger
    cold_viewer_check: ColdViewerCheck
    independent_understanding_explanation: str
    score_breakdown: dict[str, float]
    total_score: float = Field(ge=0, le=100)
    overall_explanation: str
    spoiler_risk: Literal["low", "medium", "high", "unknown"] = "unknown"
    warnings: list[str] = Field(default_factory=list)
    selection_method: Method
    human_review: HumanReview = Field(default_factory=HumanReview)

    @model_validator(mode="after")
    def _rules(self):
        total = sum(s.end_seconds - s.start_seconds for s in self.segments)
        if abs(total - self.total_duration_seconds) > 0.02:
            raise ValueError("total_duration_seconds does not match the segments")
        if not MIN_DURATION - 1e-6 <= total <= MAX_DURATION + 1e-6:
            raise ValueError(f"Duration {total:.2f}s is outside {MIN_DURATION:.0f} to {MAX_DURATION:.0f} seconds")
        if not self.hook.within_first_three_seconds or self.hook.seconds_from_clip_start > HOOK_WINDOW + 1e-6:
            raise ValueError("Hook does not begin within the first three seconds")
        for first, second in zip(self.segments, self.segments[1:]):
            if first.episode != second.episode:
                raise ValueError("Version 1 does not combine different episodes")
            if second.start_seconds < first.end_seconds:
                raise ValueError("Segments are out of story order")
        if self.human_review.status == "not_reviewed" and self.human_review.rating is not None:
            raise ValueError("A rating cannot exist before a human review")
        return self


def verify_promo_against_screenplay(promo: Promo, episodes: dict[int, Episode]) -> list[str]:
    """Return every way this promo disagrees with the original screenplay. Empty means clean."""
    errors: list[str] = []
    label = promo.promo_id
    for segment in promo.segments:
        episode = episodes.get(segment.episode)
        if episode is None:
            errors.append(f"{label}: episode {segment.episode} is not in the pack")
            continue
        cues = {cue.cue_id: cue for cue in episode.cues}
        start_cue = cues.get(segment.start_cue_id)
        end_cue = cues.get(segment.end_cue_id)
        if start_cue is None:
            errors.append(f"{label}: start cue {segment.start_cue_id} does not exist")
        elif start_cue.start != segment.start_seconds:
            errors.append(f"{label}: start {segment.start_seconds} is not the start of {segment.start_cue_id}")
        if end_cue is None:
            errors.append(f"{label}: end cue {segment.end_cue_id} does not exist")
        elif end_cue.end != segment.end_seconds:
            errors.append(f"{label}: end {segment.end_seconds} is not the end of {segment.end_cue_id}")

    first_episode = episodes.get(promo.segments[0].episode)
    if first_episode is None:
        return errors
    cues = {cue.cue_id: cue for cue in first_episode.cues}
    for section, cue_ids, evidence in (
        ("hook", promo.hook.cue_ids, promo.hook.evidence),
        ("cliffhanger", promo.cliffhanger.cue_ids, promo.cliffhanger.evidence),
    ):
        if not cue_ids:
            errors.append(f"{label}: {section} has no cue IDs")
        for cue_id in cue_ids:
            if cue_id not in cues:
                errors.append(f"{label}: {section} cue {cue_id} does not exist")
        expected = " ".join(cues[cue_id].text for cue_id in cue_ids if cue_id in cues)
        if evidence != expected:
            errors.append(f"{label}: {section} evidence is not the exact screenplay text of its cues")
    return errors
