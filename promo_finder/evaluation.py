"""Measure how good the output is, using more than "did it make a file".

Everything here reads saved run folders, so raw outputs are never altered.
These are small exploratory comparisons. They are not proof of ad performance.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .boundaries import intersection_over_union
from .parser import parse_timestamp
from .worksheets import read_reference_sheet

# 0.5 means the two clips share at least half of the total time they cover. A person
# and a tool often start a line or two apart on the same moment, so requiring near
# exact agreement would count real agreement as a miss. A 40 second reference and a
# 45 second clip sharing 30 seconds scores 30 / 55 = 0.55, which we call a match.
MATCH_IOU = 0.5
# Below 0.5 but at least this much means "same part of the scene, different cut".
SAME_AREA_IOU = 0.25


def load_promos(run_dir: str | Path) -> list[dict]:
    return json.loads((Path(run_dir) / "promos.json").read_text(encoding="utf-8"))["promos"]


def promo_range(promo: dict) -> tuple[int, float, float]:
    segment = promo["segments"][0]
    return segment["episode"], segment["start_seconds"], segment["end_seconds"]


def load_reference(path: str | Path) -> tuple[list[dict], list[dict]]:
    """Return (usable rows, rows with problems). Bad rows are reported, not dropped silently."""
    usable, problems = [], []
    for row in read_reference_sheet(path):
        start = parse_timestamp(row["start_time"])
        end = parse_timestamp(row["end_time"])
        try:
            episode = int(str(row["episode"]).strip())
        except ValueError:
            problems.append({"row": row, "problem": "episode is not a number"})
            continue
        if start is None or end is None or end <= start:
            problems.append({"row": row, "problem": "times are missing or invalid"})
            continue
        usable.append({**row, "episode": episode, "start": start, "end": end})
    return usable, problems


def best_match(reference: dict, promos: list[dict]) -> tuple[float, dict | None]:
    best_iou, best = 0.0, None
    for promo in promos:
        episode, start, end = promo_range(promo)
        if episode != reference["episode"]:
            continue
        iou = intersection_over_union(reference["start"], reference["end"], start, end)
        if iou > best_iou:
            best_iou, best = iou, promo
    return best_iou, best


def reference_coverage(references: list[dict], promos: list[dict]) -> dict:
    """For each reference clip, how close does the tool's list get, and at what rank?"""
    details = []
    for reference in references:
        iou, promo = best_match(reference, promos)
        details.append({
            "reference_id": reference.get("reference_id"),
            "episode": reference["episode"],
            "best_iou": round(iou, 3),
            "best_promo_id": promo["promo_id"] if promo else None,
            "best_promo_rank": promo["global_rank"] if promo else None,
            "verdict": "match" if iou >= MATCH_IOU else "same_area" if iou >= SAME_AREA_IOU else "missed",
        })
    total = len(references)
    matches = [d for d in details if d["verdict"] == "match"]
    return {
        "reference_clips": total,
        "match_threshold_iou": MATCH_IOU,
        "matched": len(matches),
        "matched_in_top_10": sum(1 for d in matches if d["best_promo_rank"] <= 10),
        "matched_in_top_20": sum(1 for d in matches if d["best_promo_rank"] <= 20),
        "same_area_only": sum(1 for d in details if d["verdict"] == "same_area"),
        "missed": sum(1 for d in details if d["verdict"] == "missed"),
        "recall": round(len(matches) / total, 3) if total else None,
        "details": details,
    }


def _jaccard(first: set, second: set) -> float | None:
    union = first | second
    return round(len(first & second) / len(union), 3) if union else None


def mean_best_iou(first: list[dict], second: list[dict]) -> float | None:
    """How much of list one is covered by similar time ranges in list two."""
    if not first:
        return None
    total = 0.0
    for promo in first:
        episode, start, end = promo_range(promo)
        best = 0.0
        for other in second:
            other_episode, other_start, other_end = promo_range(other)
            if other_episode == episode:
                best = max(best, intersection_over_union(start, end, other_start, other_end))
        total += best
    return round(total / len(first), 3)


def count_time_overlap_matches(first: list[dict], second: list[dict]) -> int:
    count = 0
    for promo in first:
        episode, start, end = promo_range(promo)
        if any(
            promo_range(other)[0] == episode
            and intersection_over_union(start, end, promo_range(other)[1], promo_range(other)[2]) >= MATCH_IOU
            for other in second
        ):
            count += 1
    return count


def _spearman(pairs: list[tuple[int, int]]) -> float | None:
    """Rank agreement from -1 to 1 for clips present in both lists."""
    size = len(pairs)
    if size < 2:
        return None
    first_rank = {value: rank for rank, value in enumerate(sorted(pair[0] for pair in pairs))}
    second_rank = {value: rank for rank, value in enumerate(sorted(pair[1] for pair in pairs))}
    total = sum((first_rank[a] - second_rank[b]) ** 2 for a, b in pairs)
    return round(1 - 6 * total / (size * (size ** 2 - 1)), 3)


def compare_runs(first_dir: str | Path, second_dir: str | Path) -> dict:
    """Stability: how much changes between two runs of the same settings?"""
    first_dir, second_dir = Path(first_dir), Path(second_dir)
    first, second = load_promos(first_dir), load_promos(second_dir)
    first_keys = {promo["clip_key"]: promo for promo in first}
    second_keys = {promo["clip_key"]: promo for promo in second}
    shared = sorted(set(first_keys) & set(second_keys))

    def candidates(run: Path) -> set[str]:
        folder = run / "evaluations"
        return {path.stem for path in folder.glob("*.json")} if folder.exists() else set()

    def config(run: Path) -> dict:
        path = run / "run_config.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    first_candidates, second_candidates = candidates(first_dir), candidates(second_dir)
    both_judged = sorted(first_candidates & second_candidates)
    rating_changes = {"hook_rating": [], "ending_rating": [], "clarity_rating": []}
    gate_flips = []
    for key in both_judged:
        one = json.loads((first_dir / "evaluations" / f"{key}.json").read_text(encoding="utf-8"))
        two = json.loads((second_dir / "evaluations" / f"{key}.json").read_text(encoding="utf-8"))
        for name in rating_changes:
            if one.get(name) is not None and two.get(name) is not None:
                rating_changes[name].append(abs(one[name] - two[name]))
        if bool(one.get("gate_failures")) != bool(two.get("gate_failures")):
            gate_flips.append(key)

    first_config, second_config = config(first_dir), config(second_dir)
    return {
        "run_1": first_dir.name,
        "run_2": second_dir.name,
        "run_2_used_fresh_requests": second_config.get("cache_used") is False,
        "same_models": first_config.get("finder") == second_config.get("finder")
        and first_config.get("evaluator") == second_config.get("evaluator"),
        "candidates_run_1": len(first_candidates),
        "candidates_run_2": len(second_candidates),
        "candidate_id_overlap_jaccard": _jaccard(first_candidates, second_candidates),
        "recommended_run_1": len(first),
        "recommended_run_2": len(second),
        "recommended_id_overlap_jaccard": _jaccard(set(first_keys), set(second_keys)),
        "recommended_identical_cue_pairs": len(shared),
        "time_range_similarity_run1_in_run2": mean_best_iou(first, second),
        "time_range_similarity_run2_in_run1": mean_best_iou(second, first),
        "top_10_shared_exact": len({p["clip_key"] for p in first[:10]} & {p["clip_key"] for p in second[:10]}),
        "top_10_shared_by_time_overlap": count_time_overlap_matches(first[:10], second[:10]),
        "same_first_post": _first_post_key(first) == _first_post_key(second),
        "rank_agreement_spearman_on_shared": _spearman([(first_keys[k]["global_rank"], second_keys[k]["global_rank"]) for k in shared]),
        "mean_rank_change_on_shared": round(sum(abs(first_keys[k]["global_rank"] - second_keys[k]["global_rank"]) for k in shared) / len(shared), 2) if shared else None,
        "mean_score_change_on_shared": round(sum(abs(first_keys[k]["total_score"] - second_keys[k]["total_score"]) for k in shared) / len(shared), 2) if shared else None,
        "clips_judged_in_both_runs": len(both_judged),
        "mean_rating_change_on_clips_judged_twice": {
            name: round(sum(values) / len(values), 3) if values else None for name, values in rating_changes.items()
        },
        "clips_whose_pass_or_fail_changed": gate_flips,
    }


def _first_post_key(promos: list[dict]) -> str | None:
    return next((p["clip_key"] for p in promos if p.get("first_post_recommendation")), None)


def _rating_summary(evaluations: list[dict]) -> dict:
    count = len(evaluations)
    if not count:
        return {"clips_judged": 0}

    def share(test) -> float:
        return round(sum(1 for evaluation in evaluations if test(evaluation)) / count, 3)

    def mean(name: str) -> float | None:
        values = [evaluation[name] for evaluation in evaluations if evaluation.get(name) is not None]
        return round(sum(values) / len(values), 2) if values else None

    return {
        "clips_judged": count,
        "mean_hook_rating": mean("hook_rating"),
        "mean_ending_rating": mean("ending_rating"),
        "mean_clarity_rating": mean("clarity_rating"),
        "share_hook_strong": share(lambda e: (e.get("hook_rating") or 0) >= 4),
        "share_ending_strong": share(lambda e: (e.get("ending_rating") or 0) >= 4),
        "share_cold_viewer_conflict_understood": share(lambda e: e.get("conflict_understood") is True),
        "share_passing_all_gates": share(lambda e: not e.get("gate_failures")),
    }


def compare_modes(basic_dir: str | Path, ai_dir: str | Path, basic_judged_path: str | Path | None, ai_top: int = 10,
                  references: list[dict] | None = None, reference_label: str = "") -> dict:
    """Run both modes' top clips through the same blind judge and compare them."""
    basic_dir, ai_dir = Path(basic_dir), Path(ai_dir)
    basic, ai = load_promos(basic_dir), load_promos(ai_dir)

    def summary(run: Path) -> dict:
        return json.loads((run / "processing_summary.json").read_text(encoding="utf-8"))

    ai_top_evaluations = []
    for promo in ai[:ai_top]:
        path = ai_dir / "evaluations" / f"{promo['clip_key']}.json"
        if path.exists():
            ai_top_evaluations.append(json.loads(path.read_text(encoding="utf-8")))

    basic_judged = None
    if basic_judged_path and Path(basic_judged_path).exists():
        judged = json.loads(Path(basic_judged_path).read_text(encoding="utf-8"))
        basic_judged = [judged[p["clip_key"]] for p in basic[:ai_top] if p["clip_key"] in judged]

    result = {
        "note": "Both lists were judged by the same blind tests, which are not told where a clip came from.",
        "clips_recommended": {"basic": len(basic), "ai_assisted": len(ai)},
        "top_10_episodes": {
            "basic": [promo_range(p)[0] for p in basic[:10]],
            "ai_assisted": [promo_range(p)[0] for p in ai[:10]],
        },
        "top_10_exact_same_cue_pairs": len({p["clip_key"] for p in basic[:10]} & {p["clip_key"] for p in ai[:10]}),
        "top_10_similar_by_time_overlap": count_time_overlap_matches(basic[:10], ai[:10]),
        "time_range_similarity_basic_in_ai": mean_best_iou(basic[:10], ai),
        "time_range_similarity_ai_in_basic": mean_best_iou(ai[:10], basic),
        "duplicates_removed": {
            "basic": len(summary(basic_dir).get("duplicates_removed", [])),
            "ai_assisted": len(summary(ai_dir).get("duplicates_removed", [])),
        },
        "processing_seconds": {
            "basic": summary(basic_dir).get("processing_seconds"),
            "ai_assisted": summary(ai_dir).get("processing_seconds"),
        },
        "blind_ratings_of_top_clips": {
            "basic_top_10": _rating_summary(basic_judged) if basic_judged is not None else "not judged yet",
            "ai_assisted_top_10": _rating_summary(ai_top_evaluations),
        },
    }
    if references is not None:
        result["reference_coverage"] = {
            "reference_set": reference_label,
            "basic": reference_coverage(references, basic),
            "ai_assisted": reference_coverage(references, ai),
        }
    return result


def write_comparison_markdown(path: str | Path, title: str, data: dict) -> None:
    lines = [f"# {title}", "", "```json", json.dumps(data, indent=2, ensure_ascii=False), "```", ""]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def write_csv_rows(path: str | Path, rows: list[dict]) -> None:
    if not rows:
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
