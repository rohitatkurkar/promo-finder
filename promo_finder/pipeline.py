"""Run a whole show from start to finish, saving progress along the way.

If a run stops at Episode 24, running the same command again continues from
Episode 25. An episode is only processed again if its text or the model settings
have changed.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import asdict
from pathlib import Path

from dotenv import dotenv_values

from .ai_mode import (
    LLMError,
    evaluate_clip,
    find_moments,
    gate_failures,
    pair_events,
    review_finalists,
    score_evaluated_clip,
    select_candidates,
)
from .basic_mode import BASIC_VERSION, MIN_SCORE_TO_KEEP, BasicEpisodeResult, candidates_for_episode
from .boundaries import Clip
from .llm_client import FATAL_KINDS, LLMClient, UsageLedger, load_model_config
from .masking import collect_labels, pack_name_words
from .outputs import (
    choose_first_post_ai,
    choose_first_post_basic,
    data_quality_report,
    promo_from_ai,
    promo_from_basic,
    verify_all,
    write_json,
    write_promos_csv,
    write_report,
)
from .parser import Episode, load_pack
from .prompts import (
    COLD_VIEWER_VERSION,
    FINALIST_VERSION,
    FINDER_VERSION,
    HOOK_VERSION,
)
from .ranking import Scored, rank_with_variety, remove_duplicates
from .worksheets import write_review_sheet

DEFAULT_ENV = Path(__file__).resolve().parent.parent / ".env"


def pack_title(path: str | Path) -> str:
    """Work out the show's name from the ZIP or folder name."""
    name = Path(path).stem
    name = re.sub(r"[-_ ]*scripts?.*$", "", name, flags=re.IGNORECASE).strip(" -_")
    return name or Path(path).stem


def _load_state(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


class ActiveTimer:
    """Adds up real working time across resumed runs, not the gaps between them."""

    def __init__(self, state: dict):
        self.state = state
        self.started = time.monotonic()
        self.previous = float(state.get("processing_seconds", 0.0))

    @property
    def total(self) -> float:
        return round(self.previous + (time.monotonic() - self.started), 1)


def _clip_from_dict(data: dict) -> Clip:
    return Clip(**data)


def _scored_to_dict(item: Scored) -> dict:
    return {"clip": asdict(item.clip), "parts": item.parts, "penalties": item.penalties, "payload": item.payload, "weights": item.weights}


def _scored_from_dict(data: dict) -> Scored:
    return Scored(_clip_from_dict(data["clip"]), data["parts"], data["penalties"], data["payload"], data["weights"])


def run_basic_pipeline(input_path: str | Path, out_dir: str | Path, on_progress=None) -> dict:
    """Basic mode needs no API key. Results are saved after every episode."""
    run_dir = Path(out_dir)
    (run_dir / "episodes").mkdir(parents=True, exist_ok=True)
    state_path = run_dir / "checkpoint.json"
    state = _load_state(state_path)
    timer = ActiveTimer(state)

    episodes, pack_issues = load_pack(input_path)
    by_number = {episode.number: episode for episode in episodes}
    last_episode = max(by_number)
    write_json(run_dir / "data_quality.json", data_quality_report(episodes, pack_issues))

    if state.get("engine_version") != BASIC_VERSION:
        state["episodes"] = {}  # Saved work from an older version of the signals no longer applies.
    state["engine_version"] = BASIC_VERSION
    done = state.setdefault("episodes", {})
    numbers = [episode.number for episode in episodes]
    notes_of_next = {number: by_number[following].continuity_notes for number, following in zip(numbers, numbers[1:])}
    results: list[BasicEpisodeResult] = []
    resumed = 0
    for position, episode in enumerate(episodes, start=1):
        saved_path = run_dir / "episodes" / f"E{episode.number:02d}.json"
        record = done.get(str(episode.number))
        if record and record.get("hash") == episode.content_hash and saved_path.exists():
            saved = json.loads(saved_path.read_text(encoding="utf-8"))
            results.append(BasicEpisodeResult(saved["episode"], saved["pairs_tried"], saved["valid_clips"],
                                              saved["rejection_counts"], [_scored_from_dict(k) for k in saved["kept"]]))
            resumed += 1
        else:
            result = candidates_for_episode(episode, last_episode, notes_of_next.get(episode.number, ""))
            results.append(result)
            write_json(saved_path, {
                "episode": result.episode, "pairs_tried": result.pairs_tried, "valid_clips": result.valid_clips,
                "rejection_counts": result.rejection_counts, "kept": [_scored_to_dict(item) for item in result.kept],
            })
            done[str(episode.number)] = {"hash": episode.content_hash, "status": "done"}
            state["processing_seconds"] = timer.total
            write_json(state_path, state)
        if on_progress:
            on_progress(position, len(episodes), f"Episode {episode.number}")

    pool = [item for result in results for item in result.kept]
    kept, removed = remove_duplicates(pool)
    ranked = rank_with_variety(kept)
    # Only clips still above the bar after the variety penalty are recommended. No fixed count is forced.
    above_bar = [entry for entry in ranked if entry[2] >= MIN_SCORE_TO_KEEP]
    promos = [promo_from_basic(item, rank, penalty, final, by_number[item.clip.episode])
              for rank, (item, penalty, final) in enumerate(above_bar, start=1)]
    choose_first_post_basic(promos, by_number, pack_title(input_path))

    errors = verify_all(promos, by_number)
    state["processing_seconds"] = timer.total
    write_json(state_path, state)
    summary = {
        "mode": "basic",
        "engine_version": BASIC_VERSION,
        "title": pack_title(input_path),
        "input_file": Path(input_path).name,
        "episodes_in_pack": len(episodes),
        "episodes_processed": len(results),
        "episodes_resumed_from_checkpoint": resumed,
        "episodes_with_no_recommendation": sorted(set(by_number) - {promo.segments[0].episode for promo in promos}),
        "pairs_tried": sum(r.pairs_tried for r in results),
        "valid_clips_before_selection": sum(r.valid_clips for r in results),
        "rejection_counts": _sum_counts(r.rejection_counts for r in results),
        "clips_below_the_bar_after_variety_penalty": len(ranked) - len(above_bar),
        "recommended_clips": len(promos),
        "duplicates_removed": [asdict(entry) for entry in removed],
        "verification_errors": errors,
        "processing_seconds": timer.total,
    }
    _write_outputs(run_dir, summary["title"], promos, summary)
    return summary


def _sum_counts(dicts) -> dict:
    total: dict[str, int] = {}
    for entry in dicts:
        for name, count in entry.items():
            total[name] = total.get(name, 0) + count
    return total


def _write_outputs(run_dir: Path, title: str, promos: list, summary: dict) -> None:
    write_json(run_dir / "promos.json", {
        "schema_version": "1.0",
        "selection_method": summary["mode"],
        "title": title,
        "promos": [promo.model_dump() for promo in promos],
    })
    write_promos_csv(run_dir / "promos.csv", promos)
    write_report(run_dir / "report.md", title, promos, summary)
    write_json(run_dir / "processing_summary.json", summary)
    write_review_sheet(run_dir / "top_twenty_human_review_sheet.csv")


def load_clients(run_dir: Path, env_path: str | Path | None, use_cache: bool, cache_dir: str | Path | None,
                 finder_model: str | None = None, evaluator_model: str | None = None,
                 transport=None, sleep=None) -> tuple[LLMClient, LLMClient, UsageLedger]:
    """Keys come only from the .env file, never from the wider shell environment."""
    env = {key: value for key, value in dotenv_values(env_path or DEFAULT_ENV).items() if value is not None}
    finder_config = load_model_config("finder", env, finder_model)
    evaluator_config = load_model_config("evaluator", env, evaluator_model)
    ledger = UsageLedger(run_dir / "usage.jsonl")
    ledger.load_existing()
    cache = Path(cache_dir) if cache_dir else run_dir.parent / "llm_cache"
    extra = {}
    if transport is not None:
        extra["transport"] = transport
    if sleep is not None:
        extra["sleep"] = sleep
    return (
        LLMClient(finder_config, cache, ledger, use_cache=use_cache, **extra),
        LLMClient(evaluator_config, cache, ledger, use_cache=use_cache, **extra),
        ledger,
    )


def run_ai_pipeline(
    input_path: str | Path,
    out_dir: str | Path,
    env_path: str | Path | None = None,
    use_cache: bool = True,
    cache_dir: str | Path | None = None,
    finder_model: str | None = None,
    evaluator_model: str | None = None,
    only_episodes: set[int] | None = None,
    transport=None,
    sleep=None,
    on_progress=None,
) -> dict:
    """AI assisted mode. Raises nothing for a single bad episode: it records the failure and continues."""
    run_dir = Path(out_dir)
    for folder in ("episodes", "evaluations"):
        (run_dir / folder).mkdir(parents=True, exist_ok=True)
    state_path = run_dir / "checkpoint.json"
    state = _load_state(state_path)
    timer = ActiveTimer(state)

    episodes, pack_issues = load_pack(input_path)
    by_number = {episode.number: episode for episode in episodes}
    write_json(run_dir / "data_quality.json", data_quality_report(episodes, pack_issues))
    title = pack_title(input_path)
    selected = [episode for episode in episodes if not only_episodes or episode.number in only_episodes]

    finder, evaluator, ledger = load_clients(run_dir, env_path, use_cache, cache_dir, finder_model, evaluator_model, transport, sleep)
    finder._check_ready()
    evaluator._check_ready()

    settings_key = json.dumps({
        "finder": finder.config.settings_fingerprint(), "evaluator": evaluator.config.settings_fingerprint(),
        "versions": [FINDER_VERSION, HOOK_VERSION, COLD_VIEWER_VERSION, FINALIST_VERSION],
    }, sort_keys=True)
    if state.get("settings_key") not in (None, settings_key):
        # New model or prompt: old progress in this folder no longer applies.
        state = {"processing_seconds": state.get("processing_seconds", 0.0)}
        for folder in ("episodes", "evaluations"):
            shutil.rmtree(run_dir / folder, ignore_errors=True)
            (run_dir / folder).mkdir(parents=True, exist_ok=True)
        (run_dir / "finalist_review.json").unlink(missing_ok=True)
    state["settings_key"] = settings_key
    write_json(run_dir / "run_config.json", {
        "title": title,
        "input_file": Path(input_path).name,
        "finder": finder.config.settings_fingerprint(),
        "evaluator": evaluator.config.settings_fingerprint(),
        "prompt_versions": {"finder": FINDER_VERSION, "hook_test": HOOK_VERSION, "cold_viewer": COLD_VIEWER_VERSION, "finalist": FINALIST_VERSION},
        "cache_used": use_cache,
        "same_model_for_finding_and_judging": finder.config.model == evaluator.config.model,
        "note": "Evaluations may favour the finder's picks when both roles use one model."
        if finder.config.model == evaluator.config.model else "Finder and evaluator use different models.",
    })

    finder_state = state.setdefault("finder", {})
    evaluation_state = state.setdefault("evaluations", {})
    stopped_because = None
    consecutive_network_failures = 0

    # Step 1: find moments, one episode at a time, saving after each.
    for position, episode in enumerate(selected, start=1):
        record = finder_state.get(str(episode.number))
        saved_path = run_dir / "episodes" / f"E{episode.number:02d}.json"
        if record and record.get("status") == "done" and record.get("hash") == episode.content_hash and saved_path.exists():
            continue
        if on_progress:
            on_progress(position, len(selected), f"Finder: episode {episode.number}")
        try:
            outcome = find_moments(episode, title, finder)
        except LLMError as error:
            finder_state[str(episode.number)] = {"status": "failed", "hash": episode.content_hash,
                                                  "error_kind": error.kind, "error": finder.redact(error.detail)}
            state["processing_seconds"] = timer.total
            write_json(state_path, state)
            if error.kind in FATAL_KINDS:
                stopped_because = f"Finder stopped at episode {episode.number}: {error.kind}. {finder.redact(error.detail)}"
                break
            consecutive_network_failures = consecutive_network_failures + 1 if error.kind in ("network", "server") else 0
            if consecutive_network_failures >= 3:
                stopped_because = f"Three episodes in a row failed with {error.kind}. Stopped at episode {episode.number}."
                break
            continue
        consecutive_network_failures = 0
        valid, rejected = pair_events(episode, outcome)
        candidates = select_candidates(valid)
        write_json(saved_path, {
            "episode": episode.number,
            "hook_events": [asdict(event) for event in outcome.hooks],
            "ending_events": [asdict(event) for event in outcome.endings],
            "model_issues": [asdict(issue) for issue in outcome.issues],
            "valid_pairs": len(valid),
            "rejected_pairs": [asdict(pair) for pair in rejected],
            "candidates": [asdict(clip) for clip in candidates],
        })
        finder_state[str(episode.number)] = {"status": "done", "hash": episode.content_hash}
        state["processing_seconds"] = timer.total
        write_json(state_path, state)

    # Step 2: blind tests on every candidate that has not been judged yet.
    candidates: list[tuple[Clip, Episode]] = []
    for episode in selected:
        saved_path = run_dir / "episodes" / f"E{episode.number:02d}.json"
        if saved_path.exists() and finder_state.get(str(episode.number), {}).get("status") == "done":
            saved = json.loads(saved_path.read_text(encoding="utf-8"))
            candidates += [(_clip_from_dict(data), episode) for data in saved["candidates"]]

    labels = collect_labels(episodes)
    names = pack_name_words(episodes)
    if stopped_because is None:
        for position, (clip, episode) in enumerate(candidates, start=1):
            evaluation_path = run_dir / "evaluations" / f"{clip.key}.json"
            if evaluation_state.get(clip.key, {}).get("status") == "done" and evaluation_path.exists():
                continue
            if on_progress:
                on_progress(position, len(candidates), f"Blind tests: {clip.key}")
            try:
                evaluation = evaluate_clip(clip, episode, labels, names, evaluator, stop_after_weak_hook=True)
            except LLMError as error:
                evaluation_state[clip.key] = {"status": "failed", "error_kind": error.kind, "error": evaluator.redact(error.detail)}
                state["processing_seconds"] = timer.total
                write_json(state_path, state)
                if error.kind in FATAL_KINDS:
                    stopped_because = f"Blind tests stopped at {clip.key}: {error.kind}. {evaluator.redact(error.detail)}"
                    break
                continue
            evaluation["gate_failures"] = gate_failures(evaluation)
            write_json(evaluation_path, evaluation)
            evaluation_state[clip.key] = {"status": "done"}
            state["processing_seconds"] = timer.total
            write_json(state_path, state)

    evaluations: dict[str, dict] = {}
    for clip, _ in candidates:
        evaluation_path = run_dir / "evaluations" / f"{clip.key}.json"
        if evaluation_path.exists():
            evaluations[clip.key] = json.loads(evaluation_path.read_text(encoding="utf-8"))

    passing = [(clip, episode) for clip, episode in candidates
               if clip.key in evaluations and not evaluations[clip.key]["gate_failures"]]

    # Step 3: finalists get the only check that is allowed to see the story outline.
    finalist_reviews: dict[str, dict] = {}
    finalist_issues: list[dict] = []
    finalist_path = run_dir / "finalist_review.json"
    passing_keys = sorted(clip.key for clip, _ in passing)
    saved_review = json.loads(finalist_path.read_text(encoding="utf-8")) if finalist_path.exists() else None
    if saved_review and saved_review.get("clip_keys") == passing_keys:
        finalist_reviews, finalist_issues = saved_review["reviews"], saved_review["issues"]
    elif stopped_because is None and passing:
        script_hash = "".join(sorted(episode.content_hash[:8] for episode in episodes))
        try:
            finalist_reviews, finalist_issues = review_finalists(passing, title, episodes, evaluator, script_hash)
            write_json(finalist_path, {"clip_keys": passing_keys, "reviews": finalist_reviews, "issues": finalist_issues})
        except LLMError as error:
            finalist_issues = [{"where": "finalist_review", "kind": error.kind, "detail": evaluator.redact(error.detail)}]
            if error.kind in FATAL_KINDS:
                stopped_because = f"Finalist review stopped: {error.kind}. {evaluator.redact(error.detail)}"

    scored = [score_evaluated_clip(clip, episode, evaluations[clip.key], finalist_reviews.get(clip.key))
              for clip, episode in passing]
    kept, removed = remove_duplicates(scored)
    ranked = rank_with_variety(kept)
    promos = [promo_from_ai(item, rank, penalty, final, by_number[item.clip.episode])
              for rank, (item, penalty, final) in enumerate(ranked, start=1)]
    choose_first_post_ai(promos, finalist_reviews)

    errors = verify_all(promos, by_number)
    failed_episodes = {number: record for number, record in finder_state.items() if record.get("status") == "failed"}
    failed_evaluations = {key: record for key, record in evaluation_state.items() if record.get("status") == "failed"}
    pending = [episode.number for episode in selected if finder_state.get(str(episode.number), {}).get("status") != "done"]
    rejected_candidates = [
        {"clip": asdict(clip), "gate_failures": evaluations[clip.key]["gate_failures"], "evaluation": evaluations[clip.key]}
        for clip, _ in candidates if clip.key in evaluations and evaluations[clip.key]["gate_failures"]
    ]
    write_json(run_dir / "rejected_candidates.json", rejected_candidates)

    model_issues: list[dict] = list(finalist_issues)
    rejection_counts: dict[str, int] = {}
    for episode in selected:
        saved_path = run_dir / "episodes" / f"E{episode.number:02d}.json"
        if saved_path.exists():
            saved = json.loads(saved_path.read_text(encoding="utf-8"))
            model_issues += saved["model_issues"]
            for pair in saved["rejected_pairs"]:
                rejection_counts[pair["reason"]] = rejection_counts.get(pair["reason"], 0) + 1
    for evaluation in evaluations.values():
        model_issues += evaluation.get("issues", [])
    write_json(run_dir / "model_issues.json", model_issues)

    gate_counts: dict[str, int] = {}
    for item in rejected_candidates:
        for failure in item["gate_failures"]:
            name = re.sub(r"_rated_\d_of_5_not_strong", "_not_strong", failure)
            gate_counts[name] = gate_counts.get(name, 0) + 1

    state["processing_seconds"] = timer.total
    write_json(state_path, state)
    usage = ledger.summary({"finder": finder.config, "evaluator": evaluator.config})
    write_json(run_dir / "usage_summary.json", usage)

    summary = {
        "mode": "ai_assisted",
        "title": title,
        "input_file": Path(input_path).name,
        "complete": stopped_because is None and not pending and not failed_evaluations,
        "stopped_because": stopped_because,
        "episodes_in_pack": len(episodes),
        "episodes_selected": len(selected),
        "episodes_processed": len(selected) - len(pending),
        "episodes_pending_or_failed": pending,
        "failed_episodes": failed_episodes,
        "failed_evaluations": failed_evaluations,
        "candidates_evaluated": len(evaluations),
        "passed_all_gates": len(passing),
        "gate_failure_counts": gate_counts,
        "rejected_pair_counts": rejection_counts,
        "model_issue_counts": _sum_counts([{issue.get("kind", "unknown"): 1} for issue in model_issues]),
        "recommended_clips": len(promos),
        "duplicates_removed": [asdict(entry) for entry in removed],
        "verification_errors": errors,
        "processing_seconds": timer.total,
        "usage_totals": usage["totals"],
    }
    _write_outputs(run_dir, title, promos, summary)
    return summary


def judge_clips(
    clips: list[tuple[Clip, Episode]],
    episodes: list[Episode],
    out_path: str | Path,
    env_path: str | Path | None = None,
    use_cache: bool = True,
    cache_dir: str | Path | None = None,
    transport=None,
    sleep=None,
) -> dict:
    """Run the same blind tests on any clips, such as Basic mode's top ten.

    This writes a separate file, so Basic mode's raw output is never changed.
    The evaluator is not told where a clip came from.
    """
    out_path = Path(out_path)
    run_dir = out_path.parent
    env = {key: value for key, value in dotenv_values(env_path or DEFAULT_ENV).items() if value is not None}
    config = load_model_config("evaluator", env)
    ledger = UsageLedger(run_dir / "judge_usage.jsonl")
    ledger.load_existing()
    extra = {}
    if transport is not None:
        extra["transport"] = transport
    if sleep is not None:
        extra["sleep"] = sleep
    evaluator = LLMClient(config, Path(cache_dir) if cache_dir else run_dir.parent / "llm_cache", ledger, use_cache=use_cache, **extra)
    labels = collect_labels(episodes)
    names = pack_name_words(episodes)
    results: dict[str, dict] = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    for clip, episode in clips:
        if clip.key in results:
            continue
        evaluation = evaluate_clip(clip, episode, labels, names, evaluator)
        evaluation["gate_failures"] = gate_failures(evaluation)
        results[clip.key] = evaluation
        write_json(out_path, results)
    return results
