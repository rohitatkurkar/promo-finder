"""Turn ranked clips into validated promos and write the result files."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .basic_mode import describe
from .boundaries import Clip, cues_in_range
from .parser import Episode, format_timestamp, issue_to_dict
from .parser import DIALOGUE
from .ranking import Scored, strength_from_rating
from .signals import content_stems
from .schema import (
    Cliffhanger,
    ColdViewerCheck,
    Hook,
    Promo,
    Segment,
    verify_promo_against_screenplay,
)

CSV_COLUMNS = [
    "global_rank", "promo_id", "selection_method", "first_post", "episode", "start_timestamp", "end_timestamp",
    "duration_seconds", "start_cue_id", "end_cue_id", "hook_cue_id", "hook_text", "hook_strength",
    "ending_cue_id", "ending_text", "ending_strength", "cold_viewer_result", "spoiler_risk", "total_score",
    "why_it_works", "warnings", "human_review_status",
]


def _segment(clip: Clip) -> Segment:
    return Segment(
        episode=clip.episode,
        start_seconds=clip.start,
        end_seconds=clip.end,
        start_timestamp=format_timestamp(clip.start),
        end_timestamp=format_timestamp(clip.end),
        start_cue_id=clip.start_cue_id,
        end_cue_id=clip.end_cue_id,
        boundary_adjustments=list(clip.adjustments),
    )


def promo_from_basic(item: Scored, rank: int, repetition: float, final: float, episode: Episode) -> Promo:
    clip = item.clip
    hook_cue = episode.cue(clip.hook_cue_id)
    ending_cue = episode.cue(clip.ending_cue_id)
    breakdown = {**item.parts, **{f"penalty_{name}": -value for name, value in item.penalties.items()}}
    if repetition:
        breakdown["penalty_repetition"] = -repetition
    return Promo(
        promo_id=f"B{rank:04d}",
        clip_key=clip.key,
        global_rank=rank,
        segments=[_segment(clip)],
        total_duration_seconds=clip.duration,
        hook=Hook(
            cue_ids=[clip.hook_cue_id], evidence=hook_cue.text, strength="not_rated",
            rated_by="none: basic mode uses signals and makes no judgement",
            within_first_three_seconds=True, seconds_from_clip_start=clip.hook_offset,
            reason="; ".join(item.payload.get("hook_reasons", [])),
        ),
        cliffhanger=Cliffhanger(
            cue_ids=[clip.ending_cue_id], evidence=ending_cue.text, strength="not_rated",
            rated_by="none: basic mode uses signals and makes no judgement",
            reason="; ".join(item.payload.get("ending_reasons", [])),
        ),
        cold_viewer_check=ColdViewerCheck(result="not_performed"),
        independent_understanding_explanation=(
            "Not tested. Word based estimate only: " + ("; ".join(item.payload.get("understanding_reasons", [])) or "no clear signal")
        ),
        score_breakdown=breakdown,
        total_score=max(0.0, min(100.0, final)),
        overall_explanation=describe(item),
        spoiler_risk="unknown",
        warnings=list(clip.warnings) + list(item.payload.get("ad_warnings", [])),
        selection_method="basic",
    )


def promo_from_ai(item: Scored, rank: int, repetition: float, final: float, episode: Episode) -> Promo:
    clip = item.clip
    evaluation = item.payload["evaluation"]
    finalist = item.payload.get("finalist") or {}
    hook_cue = episode.cue(clip.hook_cue_id)
    ending_cue = episode.cue(clip.ending_cue_id)
    breakdown = {**item.parts, **{f"penalty_{name}": -value for name, value in item.penalties.items()}}
    if repetition:
        breakdown["penalty_repetition"] = -repetition
    warnings = list(clip.warnings)
    if finalist.get("ad_platform_risk") in ("medium", "high"):
        warnings.append(f"Ad platform risk {finalist['ad_platform_risk']}: {finalist.get('ad_platform_reason', '')}")
    if finalist.get("spoiler_risk") in ("medium", "high"):
        warnings.append(f"Spoiler risk {finalist['spoiler_risk']}: {finalist.get('what_it_gives_away', '')}")
    if not finalist:
        warnings.append("Finalist review did not return a result for this clip, so spoiler risk is unknown.")
    understanding = f"Blind viewer's reading of the conflict: {evaluation.get('main_conflict', '')}"
    missing = evaluation.get("missing_context", "")
    if missing and missing.lower().strip(" .") != "nothing":
        understanding += f" What could still confuse them: {missing}"
    return Promo(
        promo_id=f"P{rank:04d}",
        clip_key=clip.key,
        global_rank=rank,
        segments=[_segment(clip)],
        total_duration_seconds=clip.duration,
        hook=Hook(
            cue_ids=[clip.hook_cue_id], evidence=hook_cue.text,
            strength=strength_from_rating(evaluation.get("hook_rating")),
            rating_out_of_5=evaluation.get("hook_rating"), rated_by="blind hook test",
            within_first_three_seconds=True, seconds_from_clip_start=clip.hook_offset,
            reason=evaluation.get("what_grabs_attention", ""),
        ),
        cliffhanger=Cliffhanger(
            cue_ids=[clip.ending_cue_id], evidence=ending_cue.text,
            strength=strength_from_rating(evaluation.get("ending_rating")),
            rating_out_of_5=evaluation.get("ending_rating"), rated_by="blind cold viewer",
            resolves_conflict=evaluation.get("ending_resolves_conflict"),
            reason=evaluation.get("wants_to_know_next", ""),
        ),
        cold_viewer_check=ColdViewerCheck(
            result="pass",
            main_conflict_understood=evaluation.get("conflict_understood"),
            unresolved_question_understood=evaluation.get("question_understood"),
            who_appears_involved=evaluation.get("who_appears_involved", ""),
            what_is_happening=evaluation.get("what_is_happening", ""),
            main_conflict=evaluation.get("main_conflict", ""),
            viewer_wants_to_know=evaluation.get("wants_to_know_next", ""),
            verified_evidence_lines=evaluation.get("verified_evidence", []),
            unverified_evidence_lines=evaluation.get("unverified_evidence", []),
            missing_context=missing,
        ),
        independent_understanding_explanation=understanding,
        score_breakdown=breakdown,
        total_score=max(0.0, min(100.0, final)),
        overall_explanation=f"{evaluation.get('what_grabs_attention', '')} Leaves open: {evaluation.get('wants_to_know_next', '')}",
        spoiler_risk=finalist.get("spoiler_risk", "unknown"),
        warnings=warnings,
        selection_method="ai_assisted",
    )


def choose_first_post_basic(promos: list[Promo], episodes: dict[int, Episode], title: str) -> None:
    """Basic mode cannot read for premise, so it uses two clues: early in the story, and echoing the title.

    Early carries the most weight. A viewer who clicks a promo starts at Episode 1, so a
    clip from the opening episodes delivers what it promised straight away.
    """
    if not promos:
        return
    last_episode = max(episodes)
    title_stems = content_stems(title)

    def spoken_title_words(promo: Promo) -> set[str]:
        segment = promo.segments[0]
        lines = cues_in_range(episodes[segment.episode], segment.start_seconds, segment.end_seconds)
        return title_stems & content_stems(" ".join(cue.text for cue in lines if cue.kind == DIALOGUE))

    def value(promo: Promo) -> float:
        position = (promo.segments[0].episode - 1) / max(last_episode - 1, 1)
        early = 25 if position <= 0.1 else 10 if position <= 0.2 else 0
        return promo.total_score + early + min(15, 5 * len(spoken_title_words(promo)))

    pick = max(promos, key=value)
    pick.first_post_recommendation = True
    echoed = len(spoken_title_words(pick))
    pick.first_post_reason = (
        f"Signals only: the highest score after favouring early episodes and clips whose dialogue echoes the show's title "
        f"({echoed} title word(s) spoken here), because those clues suggest the show's premise. Basic mode cannot confirm "
        "that this clip actually introduces the premise, so a person must check it."
    )


def choose_first_post_ai(promos: list[Promo], finalists: dict[str, dict]) -> None:
    """Pick the strongest clip that also works as an introduction to the show."""
    if not promos:
        return
    good_intro = [p for p in promos if p.spoiler_risk == "low" and (finalists.get(p.clip_key, {}).get("premise_fit") or 0) >= 4]
    if good_intro:
        pick = good_intro[0]
        review = finalists[pick.clip_key]
        pick.first_post_reason = (
            f"Highest ranked clip that also introduces the show: rated {review['premise_fit']} of 5 for premise fit with "
            f"low spoiler risk. {review.get('premise_reason', '')} A stronger shock that needs earlier episodes "
            "can come later, once viewers know the premise."
        )
    else:
        scored = sorted(promos, key=lambda p: (-(finalists.get(p.clip_key, {}).get("premise_fit") or 0), p.global_rank))
        pick = scored[0]
        pick.first_post_reason = (
            "No clip was rated both a good introduction and low spoiler risk, so this is the best available premise fit. "
            "A person should check it before posting."
        )
        pick.warnings.append("First post recommendation is weak: no clip met the premise and spoiler test.")
    pick.first_post_recommendation = True


def verify_all(promos: list[Promo], episodes: dict[int, Episode]) -> list[str]:
    errors: list[str] = []
    for promo in promos:
        errors.extend(verify_promo_against_screenplay(promo, episodes))
    return errors


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8", newline="\n")
    temporary.replace(path)  # Replacing in one step means a crash cannot leave half a file.


def write_promos_csv(path: Path, promos: list[Promo]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for promo in promos:
            segment = promo.segments[0]
            writer.writerow({
                "global_rank": promo.global_rank,
                "promo_id": promo.promo_id,
                "selection_method": promo.selection_method,
                "first_post": "yes" if promo.first_post_recommendation else "",
                "episode": segment.episode,
                "start_timestamp": segment.start_timestamp,
                "end_timestamp": segment.end_timestamp,
                "duration_seconds": promo.total_duration_seconds,
                "start_cue_id": segment.start_cue_id,
                "end_cue_id": segment.end_cue_id,
                "hook_cue_id": ";".join(promo.hook.cue_ids),
                "hook_text": promo.hook.evidence,
                "hook_strength": promo.hook.strength,
                "ending_cue_id": ";".join(promo.cliffhanger.cue_ids),
                "ending_text": promo.cliffhanger.evidence,
                "ending_strength": promo.cliffhanger.strength,
                "cold_viewer_result": promo.cold_viewer_check.result,
                "spoiler_risk": promo.spoiler_risk,
                "total_score": promo.total_score,
                "why_it_works": promo.overall_explanation,
                "warnings": " | ".join(promo.warnings),
                "human_review_status": promo.human_review.status,
            })


def write_report(path: Path, title: str, promos: list[Promo], summary: dict) -> None:
    method = summary.get("mode", "")
    lines = [f"# Promo recommendations: {title}", ""]
    if method == "basic":
        lines += [
            "**Basic selections.** These come from ordinary code using simple signals. They have not had any story "
            "judgement, no cold viewer test, and no hook or ending rating. Treat them as a starting list for an editor.",
            "",
        ]
    else:
        lines += [
            "**AI assisted selections.** Every clip passed a blind hook test and a blind cold viewer test. Models judged "
            "the story. All times and quotations come from the screenplay through code.",
            "",
        ]
    lines += [
        "A score only compares clips with each other. It is not a chance of an ad succeeding. No clip here has been "
        "tested on a real audience, and human review is still open on every clip.",
        "",
        f"- Episodes processed: {summary.get('episodes_processed')} of {summary.get('episodes_in_pack')}",
        f"- Recommended clips: {len(promos)}",
        f"- Processing time: {summary.get('processing_seconds')} seconds",
        "",
    ]
    first = next((promo for promo in promos if promo.first_post_recommendation), None)
    if first:
        segment = first.segments[0]
        lines += [
            "## Post this first", "",
            f"**{first.promo_id}, Episode {segment.episode}, {segment.start_timestamp} to {segment.end_timestamp}** "
            f"({first.total_duration_seconds:.1f}s)", "",
            first.first_post_reason, "",
        ]
    lines += ["## Ranking", ""]
    for promo in promos:
        segment = promo.segments[0]
        lines += [
            f"### {promo.global_rank}. {promo.promo_id}: Episode {segment.episode}, "
            f"{segment.start_timestamp} to {segment.end_timestamp} ({promo.total_duration_seconds:.1f}s)",
            "",
            f"- Score: {promo.total_score}",
            f"- Hook ({promo.hook.strength}), {promo.hook.cue_ids[0]}: \"{promo.hook.evidence}\"",
            f"- Ending ({promo.cliffhanger.strength}), {promo.cliffhanger.cue_ids[0]}: \"{promo.cliffhanger.evidence}\"",
            f"- Why it could work: {promo.overall_explanation}",
            f"- On its own: {promo.independent_understanding_explanation}",
        ]
        if promo.warnings:
            lines.append("- Warnings: " + " | ".join(promo.warnings))
        if segment.boundary_adjustments:
            lines.append("- Boundary changes: " + " ".join(segment.boundary_adjustments))
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def data_quality_report(episodes: list[Episode], pack_issues: list) -> dict:
    """Everything odd found in the pack. Each entry says where and why."""
    issues = [issue_to_dict(issue) for episode in episodes for issue in episode.issues]
    issues += [issue_to_dict(issue) for issue in pack_issues]
    counts: dict[str, int] = {}
    for issue in issues:
        counts[issue["issue_type"]] = counts.get(issue["issue_type"], 0) + 1
    kinds: dict[str, int] = {}
    for episode in episodes:
        for cue in episode.cues:
            kinds[cue.kind] = kinds.get(cue.kind, 0) + 1
    return {
        "episodes": len(episodes),
        "episode_numbers": [episode.number for episode in episodes],
        "scenes": sum(len(episode.scenes) for episode in episodes),
        "cues_total": sum(kinds.values()),
        "cues_by_kind": kinds,
        "cues_without_valid_time": sum(1 for e in episodes for c in e.cues if not c.has_valid_time),
        "total_runtime_minutes": round(sum(e.duration for e in episodes) / 60, 1),
        "shortest_episode_seconds": min((e.duration for e in episodes), default=0),
        "longest_episode_seconds": max((e.duration for e in episodes), default=0),
        "label_style_differences": {e.number: e.label_style for e in episodes if e.label_style != "titlecase"},
        "issue_counts": counts,
        "issues": issues,
    }
