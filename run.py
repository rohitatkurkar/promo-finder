"""Command line for the promo finder. Run `python run.py --help` to see every command."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from promo_finder.boundaries import build_clip
from promo_finder.evaluation import (
    compare_modes,
    compare_runs,
    load_promos,
    load_reference,
    reference_coverage,
    write_comparison_markdown,
)
from promo_finder.llm_client import LLMClient, LLMError, load_model_config
from promo_finder.outputs import data_quality_report, write_json
from promo_finder.parser import ScreenplayPackError, load_pack
from promo_finder.pipeline import DEFAULT_ENV, judge_clips, run_ai_pipeline, run_basic_pipeline
from promo_finder.worksheets import write_reference_kit


def print_progress(done: int, total: int, label: str) -> None:
    print(f"[{done}/{total}] {label}", flush=True)


def parse_episodes(text: str | None) -> set[int] | None:
    """Turn '1-5,9' into {1, 2, 3, 4, 5, 9}."""
    if not text:
        return None
    numbers: set[int] = set()
    for part in text.split(","):
        if "-" in part:
            low, high = part.split("-")
            numbers.update(range(int(low), int(high) + 1))
        else:
            numbers.add(int(part))
    return numbers


def command_inspect(args) -> int:
    episodes, pack_issues = load_pack(args.input)
    report = data_quality_report(episodes, pack_issues)
    if args.out:
        write_json(Path(args.out) / "data_quality.json", report)
    brief = {key: value for key, value in report.items() if key not in ("issues",)}
    print(json.dumps(brief, indent=2))
    return 0


def command_worksheet(args) -> int:
    episodes, _ = load_pack(args.input)
    for path in write_reference_kit(episodes, args.out):
        print(f"wrote {path}")
    return 0


def command_basic(args) -> int:
    summary = run_basic_pipeline(args.input, args.out, on_progress=print_progress if args.verbose else None)
    print(f"Basic run finished in {summary['processing_seconds']}s.")
    print(f"Episodes processed: {summary['episodes_processed']} of {summary['episodes_in_pack']}")
    print(f"Recommended clips: {summary['recommended_clips']}")
    print(f"Verification errors: {len(summary['verification_errors'])}")
    print(f"Results are in {args.out}")
    return 1 if summary["verification_errors"] else 0


def command_ai(args) -> int:
    try:
        summary = run_ai_pipeline(
            args.input, args.out, env_path=args.env, use_cache=not args.no_cache, cache_dir=args.cache_dir,
            finder_model=args.finder_model, evaluator_model=args.evaluator_model,
            only_episodes=parse_episodes(args.episodes), on_progress=print_progress,
        )
    except LLMError as error:
        print(f"AI assisted mode could not start. {error.detail}", file=sys.stderr)
        return 2
    print(f"Episodes processed: {summary['episodes_processed']} of {summary['episodes_selected']} selected")
    print(f"Candidates judged: {summary['candidates_evaluated']}, passed all gates: {summary['passed_all_gates']}")
    print(f"Recommended clips: {summary['recommended_clips']}")
    print(f"Model calls: {summary['usage_totals']}")
    print(f"Verification errors: {len(summary['verification_errors'])}")
    if summary["stopped_because"]:
        print(f"STOPPED: {summary['stopped_because']}")
        print("Run the same command again to continue from where it stopped.")
        return 3
    if not summary["complete"]:
        print(f"INCOMPLETE. Failed episodes: {list(summary['failed_episodes'])}, failed evaluations: {list(summary['failed_evaluations'])}")
        return 3
    print(f"Results are in {args.out}")
    return 1 if summary["verification_errors"] else 0


def command_check(args) -> int:
    from dotenv import dotenv_values

    env = {key: value for key, value in dotenv_values(args.env or DEFAULT_ENV).items() if value is not None}
    status = 0
    for role in ("finder", "evaluator"):
        config = load_model_config(role, env)
        try:
            result = LLMClient(config).check()
        except LLMError as error:
            print(f"{role}: NOT READY. {error.detail}")
            status = 2
            continue
        print(f"{role}: provider={config.provider} model={config.model} ok={result['ok']} {result.get('problem', '')}")
        if not result["ok"]:
            status = 2
            if result.get("available_models"):
                print("  Models available with this key: " + ", ".join(result["available_models"][:30]))
    return status


def command_judge_basic(args) -> int:
    """Put Basic mode's top clips through the same blind tests. Basic's own files stay unchanged."""
    episodes, _ = load_pack(args.input)
    by_number = {episode.number: episode for episode in episodes}
    clips = []
    for promo in load_promos(args.run)[:args.top]:
        episode = by_number[promo["segments"][0]["episode"]]
        built = build_clip(episode, episode.cue(promo["hook"]["cue_ids"][0]), episode.cue(promo["cliffhanger"]["cue_ids"][0]))
        if built.ok:
            clips.append((built.clip, episode))
    try:
        results = judge_clips(clips, episodes, Path(args.run) / "blind_judgement_of_top_clips.json", env_path=args.env, cache_dir=args.cache_dir)
    except LLMError as error:
        print(f"Could not finish judging. {error.detail}", file=sys.stderr)
        return 3
    print(f"Judged {len(results)} clips. Saved in {args.run}/blind_judgement_of_top_clips.json")
    return 0


def command_compare_modes(args) -> int:
    references, label = None, ""
    if args.reference:
        references, problems = load_reference(args.reference)
        label = args.reference_label or Path(args.reference).name
        if problems:
            print(f"{len(problems)} reference rows could not be used: {problems}")
    result = compare_modes(args.basic, args.ai, Path(args.basic) / "blind_judgement_of_top_clips.json", references=references, reference_label=label)
    write_json(Path(args.out) / "mode_comparison.json", result)
    write_comparison_markdown(Path(args.out) / "mode_comparison.md", "Basic and AI assisted comparison", result)
    print(json.dumps({key: value for key, value in result.items() if key != "reference_coverage"}, indent=2))
    return 0


def command_compare_runs(args) -> int:
    result = compare_runs(args.first, args.second)
    write_json(Path(args.out) / "stability_report.json", result)
    write_comparison_markdown(Path(args.out) / "stability_report.md", "Stability of two AI assisted runs", result)
    print(json.dumps(result, indent=2))
    return 0


def command_reference_check(args) -> int:
    references, problems = load_reference(args.reference)
    if len(references) < 8:
        print(f"Only {len(references)} usable rows. The exercise asks for at least 8, so this is not a complete reference set.")
    coverage = reference_coverage(references, load_promos(args.run))
    coverage["unusable_rows"] = problems
    coverage["reference_set"] = args.reference_label or Path(args.reference).name
    write_json(Path(args.out), coverage)
    print(json.dumps({key: value for key, value in coverage.items() if key != "details"}, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Find promo clips in a microdrama screenplay pack.")
    commands = parser.add_subparsers(dest="command", required=True)

    inspect = commands.add_parser("inspect", help="Report what is in a pack and any data problems")
    inspect.add_argument("--input", required=True)
    inspect.add_argument("--out")
    inspect.set_defaults(handler=command_inspect)

    worksheet = commands.add_parser("worksheet", help="Create the blank manual reference kit")
    worksheet.add_argument("--input", required=True)
    worksheet.add_argument("--out", required=True)
    worksheet.set_defaults(handler=command_worksheet)

    basic = commands.add_parser("basic", help="Run Basic mode. Needs no API key.")
    basic.add_argument("--input", required=True)
    basic.add_argument("--out", required=True)
    basic.add_argument("--verbose", action="store_true")
    basic.set_defaults(handler=command_basic)

    ai = commands.add_parser("ai", help="Run AI assisted mode. Needs a key in .env.")
    ai.add_argument("--input", required=True)
    ai.add_argument("--out", required=True)
    ai.add_argument("--env", help="Path to the .env file")
    ai.add_argument("--no-cache", action="store_true", help="Ask the models again instead of reusing saved answers")
    ai.add_argument("--cache-dir")
    ai.add_argument("--finder-model", help="Use this finder model instead of the one in .env")
    ai.add_argument("--evaluator-model", help="Use this evaluator model instead of the one in .env")
    ai.add_argument("--episodes", help="Only these episodes, for example 1-5,9")
    ai.set_defaults(handler=command_ai)

    check = commands.add_parser("check-provider", help="Test the key and model names. Sends no screenplay text.")
    check.add_argument("--env")
    check.set_defaults(handler=command_check)

    judge = commands.add_parser("judge-basic", help="Run the blind tests on Basic mode's top clips")
    judge.add_argument("--input", required=True)
    judge.add_argument("--run", required=True, help="The Basic run folder")
    judge.add_argument("--top", type=int, default=10)
    judge.add_argument("--env")
    judge.add_argument("--cache-dir")
    judge.set_defaults(handler=command_judge_basic)

    modes = commands.add_parser("compare-modes", help="Compare Basic and AI assisted results")
    modes.add_argument("--basic", required=True)
    modes.add_argument("--ai", required=True)
    modes.add_argument("--out", required=True)
    modes.add_argument("--reference", help="A filled reference sheet")
    modes.add_argument("--reference-label", help="Say whose picks these are")
    modes.set_defaults(handler=command_compare_modes)

    runs = commands.add_parser("compare-runs", help="Stability: compare two runs of the same settings")
    runs.add_argument("--first", required=True)
    runs.add_argument("--second", required=True)
    runs.add_argument("--out", required=True)
    runs.set_defaults(handler=command_compare_runs)

    reference = commands.add_parser("reference-check", help="Compare a filled reference sheet with a run")
    reference.add_argument("--reference", required=True)
    reference.add_argument("--run", required=True)
    reference.add_argument("--out", required=True, help="Path of the JSON file to write")
    reference.add_argument("--reference-label", help="Say whose picks these are")
    reference.set_defaults(handler=command_reference_check)

    args = parser.parse_args()
    try:
        return args.handler(args)
    except ScreenplayPackError as error:
        print(f"Could not read the screenplay pack. {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
