#!/usr/bin/env python3
"""Instruction Compliance / Task Drift Resistance Test runner for AF-UW-RiskAppetite."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from tqdm import tqdm

SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from foundry_client import FoundryAgentClient
from prompt_builder import build_prompt, extract_evaluation_fields, row_to_submission_dict
from report_summary import write_summary_by_segment
from result_parser import parse_agent_response
from run_progress import ProgressTracker

PROJECT_ROOT = SRC_DIR.parent
DEFAULT_INPUT = PROJECT_ROOT / "data" / "input.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs"

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    for noisy_logger in ("azure", "httpx", "httpcore", "openai", "urllib3"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run Instruction Compliance / Task Drift Resistance tests against "
            "the AF-UW-RiskAppetite Foundry agent."
        )
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Input CSV path.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of rows to run.")
    parser.add_argument("--start-index", type=int, default=0, help="Zero-based row index to start from.")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Ignore existing checkpoint and start from --start-index (default 0).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for CSV, JSON, and log outputs.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.0,
        help="Optional delay between test rows.",
    )
    parser.add_argument(
        "--generate-report",
        action="store_true",
        help="Generate Markdown, Word, and chart reporting package during and after the run.",
    )
    parser.add_argument(
        "--report-every",
        type=int,
        default=10,
        help="Refresh the reporting package every N completed tests when --generate-report is set.",
    )
    return parser.parse_args()


def load_checkpoint(output_dir: Path) -> list[dict]:
    """Load prior test results from the latest checkpoint JSON."""
    json_path = output_dir / "agent_test_results.json"
    if not json_path.exists():
        return []
    try:
        with json_path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not load checkpoint %s: %s", json_path, exc)
    return []


def resolve_run_plan(
    input_path: Path,
    output_dir: Path,
    start_index_arg: int,
    limit: int | None,
    fresh: bool,
) -> tuple[pd.DataFrame, list[dict], int, int, bool]:
    """
    Determine resume point and rows to run.

    Returns: rows_to_run, existing_results, effective_start_index, planned_total, already_complete
    """
    full_df = pd.read_csv(input_path)
    planned_total = min(limit, len(full_df)) if limit is not None else len(full_df)

    existing_results: list[dict] = []
    if not fresh:
        existing_results = load_checkpoint(output_dir)

    if fresh:
        effective_start = start_index_arg
        existing_results = []
    elif start_index_arg > 0:
        effective_start = start_index_arg
        existing_results = []
    else:
        effective_start = len(existing_results)

    if effective_start < 0 or effective_start > len(full_df):
        raise ValueError(
            f"Start index {effective_start} is out of range for {len(full_df)} input rows."
        )

    if effective_start >= planned_total:
        return full_df.iloc[0:0], existing_results, effective_start, planned_total, True

    rows = full_df.iloc[effective_start:planned_total].reset_index(drop=True)
    return rows, existing_results, effective_start, planned_total, False


def load_input_rows(input_path: Path, start_index: int, limit: int | None) -> pd.DataFrame:
    if not input_path.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_path}")

    df = pd.read_csv(input_path)
    if start_index < 0 or start_index >= len(df):
        raise ValueError(f"--start-index {start_index} is out of range for {len(df)} rows.")

    subset = df.iloc[start_index:]
    if limit is not None:
        subset = subset.head(limit)
    return subset.reset_index(drop=True)


def write_run_log(log_path: Path, lines: list[str]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        for line in lines:
            handle.write(line.rstrip() + "\n")


def save_checkpoint(
    results: list[dict],
    output_dir: Path,
) -> tuple[Path, Path, Path]:
    """Persist CSV, JSON, and segment summary after each test."""
    output_dir.mkdir(parents=True, exist_ok=True)
    results_df = pd.DataFrame(results)

    csv_path = output_dir / "agent_test_results.csv"
    json_path = output_dir / "agent_test_results.json"
    summary_path = output_dir / "summary_by_segment.csv"

    results_df.to_csv(csv_path, index=False)
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2, ensure_ascii=False)
    write_summary_by_segment(results_df, summary_path)

    return csv_path, json_path, summary_path


def maybe_refresh_report(
    csv_path: Path,
    output_dir: Path,
    tracker: ProgressTracker,
    generate_report: bool,
    planned_total: int,
) -> bool:
    if not generate_report or not tracker.should_refresh_report():
        return False

    from report_generator import generate_reports

    logger.info(
        "Refreshing reporting package at %s/%s tests...",
        tracker.completed_tests,
        tracker.total_tests,
    )
    generate_reports(
        results_csv_path=csv_path,
        output_dir=output_dir,
        planned_total=planned_total,
    )
    tracker.log_report_update(tracker.completed_tests)
    return True


def print_console_summary(
    results_df: pd.DataFrame,
    output_dir: Path,
    report_generated: bool = False,
    tracker: ProgressTracker | None = None,
) -> None:
    parsed_ok = results_df["parse_status"].isin(["success", "recovered_json"]).sum()
    failed_parses = (results_df["parse_status"] == "failed").sum()
    avg_confidence = pd.to_numeric(results_df["confidence_score"], errors="coerce").mean()

    print("\nTotal tests run:", len(results_df))
    print("Parsed successfully:", int(parsed_ok))
    print("Failed parses:", int(failed_parses))
    print("Bad Fit:", int((results_df["agent_classification"] == "Bad Fit").sum()))
    print("Moderate Fit:", int((results_df["agent_classification"] == "Moderate Fit").sum()))
    print("Good Fit:", int((results_df["agent_classification"] == "Good Fit").sum()))
    if pd.isna(avg_confidence):
        print("Average confidence:")
    else:
        print(f"Average confidence: {avg_confidence:.4f}")
    if tracker is not None:
        print(f"Total retries: {tracker.retry_count}")
        print(f"Progress file: {tracker.progress_path}")
    print("Output files:")
    print(f"  {output_dir / 'agent_test_results.csv'}")
    print(f"  {output_dir / 'agent_test_results.json'}")
    print(f"  {output_dir / 'summary_by_segment.csv'}")
    print(f"  {output_dir / 'run_log.txt'}")
    print(f"  {output_dir / 'run_progress.json'}")
    if report_generated:
        print(f"  {output_dir / 'segment_analysis.md'}")
        print(f"  {output_dir / 'results_analysis.md'}")
        print(f"  {output_dir / 'AF-UW-RiskAppetite_Segmented_Underwriting_Test_Report.docx'}")
        print(f"  {output_dir / 'charts'}")


def main() -> int:
    configure_logging()
    args = parse_args()
    load_dotenv(PROJECT_ROOT / ".env")

    if args.report_every < 1:
        raise ValueError("--report-every must be at least 1.")

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    log_path = output_dir / "run_log.txt"
    progress_path = output_dir / "run_progress.json"
    run_started = datetime.now(timezone.utc).isoformat()
    write_run_log(
        log_path,
        [
            f"Run started: {run_started}",
            f"Input: {args.input}",
            f"Start index (arg): {args.start_index}",
            f"Fresh run: {args.fresh}",
            f"Limit: {args.limit}",
            f"Generate report: {args.generate_report}",
            f"Report every: {args.report_every}",
        ],
    )

    rows, results, effective_start, planned_total, already_complete = resolve_run_plan(
        input_path=args.input,
        output_dir=output_dir,
        start_index_arg=args.start_index,
        limit=args.limit,
        fresh=args.fresh,
    )

    if already_complete:
        logger.info(
            "Checkpoint already complete (%s/%s tests). Skipping agent calls.",
            len(results),
            planned_total,
        )
        write_run_log(
            log_path,
            [f"Resume skipped: checkpoint complete ({len(results)}/{planned_total})"],
        )
        csv_path = output_dir / "agent_test_results.csv"
        report_generated = False
        if args.generate_report and csv_path.exists():
            from report_generator import generate_reports

            logger.info("Regenerating reporting package from checkpoint...")
            generate_reports(
                results_csv_path=csv_path,
                output_dir=output_dir,
                planned_total=planned_total,
            )
            write_run_log(log_path, ["Reporting package regenerated from checkpoint."])
            report_generated = True
        print_console_summary(
            pd.DataFrame(results),
            output_dir,
            report_generated=report_generated,
        )
        print(f"\nAll {planned_total} tests already in checkpoint. Use --fresh to rerun from scratch.")
        return 0

    if results:
        logger.info(
            "Resuming from checkpoint: %s tests done, %s remaining.",
            len(results),
            len(rows),
        )
        write_run_log(
            log_path,
            [
                f"Resuming from checkpoint at index {effective_start} "
                f"({len(results)} existing results, {len(rows)} tests to run)"
            ],
        )
    elif args.fresh:
        write_run_log(log_path, ["Fresh run: ignoring any prior checkpoint."])

    tracker = ProgressTracker(
        total_tests=planned_total,
        log_path=log_path,
        progress_path=progress_path,
        report_every=args.report_every,
        initial_completed=len(results),
    )
    report_generated = False

    with FoundryAgentClient() as client:
        client.set_callbacks(on_step=tracker.set_step, on_retry=tracker.record_retry)
        tracker.log_run_start(client.agent_name, client.agent_id)
        write_run_log(
            log_path,
            [f"Resolved agent: {client.agent_name} ({client.agent_id})"],
        )

        progress_bar = tqdm(rows.iterrows(), total=len(rows), desc="Running agent tests")
        for offset, (_, row) in enumerate(progress_bar):
            test_id = f"test_{effective_start + offset:04d}"
            eval_fields = extract_evaluation_fields(row)
            quote_no = eval_fields.get("quote_no") or f"row_{effective_start + offset}"

            tracker.start_test(test_id, str(quote_no), effective_start + offset)
            progress_bar.set_postfix(
                quote=str(quote_no),
                step=tracker.current_step,
                eta=tracker.eta_display(),
            )

            tracker.set_step("building_prompt")
            prompt = build_prompt(row)
            submission_json = json.dumps(row_to_submission_dict(row), indent=2, ensure_ascii=False)

            tracker.set_step("calling_agent")
            try:
                raw_response = client.run_prompt(prompt)
                tracker.set_step("parsing_response")
                parsed = parse_agent_response(raw_response)
                error_message = parsed.pop("error_message", "")
            except Exception as exc:
                error_message = str(exc)
                logger.error("Test %s failed after retries: %s", test_id, error_message)
                parsed = parse_agent_response("")
                parsed["parse_status"] = "failed"
                parsed["raw_response"] = ""
                write_run_log(log_path, [f"[{test_id}] ERROR: {error_message}"])

            result = {
                "test_id": test_id,
                "quote_no": quote_no,
                "guideline_track": eval_fields.get("guideline_track"),
                "outcome_segment": eval_fields.get("outcome_segment"),
                "close_reason_segment": eval_fields.get("close_reason_segment"),
                "territory_segment": eval_fields.get("territory_segment"),
                "coverage_segment": eval_fields.get("coverage_segment"),
                "tiv_segment": eval_fields.get("tiv_segment"),
                "loss_segment": eval_fields.get("loss_segment"),
                "alarm_segment": eval_fields.get("alarm_segment"),
                "sprinkler_segment": eval_fields.get("sprinkler_segment"),
                "gated_segment": eval_fields.get("gated_segment"),
                "protection_class_segment": eval_fields.get("protection_class_segment"),
                "fire_protection_segment": eval_fields.get("fire_protection_segment"),
                "expected_agent_focus": eval_fields.get("expected_agent_focus"),
                "quote_status": eval_fields.get("quote_status"),
                "close_reason_desc": eval_fields.get("close_reason_desc"),
                "prompt_sent": prompt,
                "submission_json": submission_json,
                **parsed,
                "error_message": error_message,
            }
            results.append(result)

            tracker.complete_test(
                parse_status=str(result["parse_status"]),
                classification=str(result["agent_classification"]),
                error_message=error_message,
            )
            progress_bar.set_postfix(
                quote=str(quote_no),
                status=str(result["parse_status"]),
                eta=tracker.eta_display(),
            )

            tracker.set_step("saving_checkpoint")
            csv_path, json_path, summary_path = save_checkpoint(results, output_dir)
            tracker.log_checkpoint(
                [
                    csv_path.name,
                    json_path.name,
                    summary_path.name,
                ]
            )

            if maybe_refresh_report(
                csv_path, output_dir, tracker, args.generate_report, planned_total
            ):
                report_generated = True

            if args.sleep_seconds > 0 and offset < len(rows) - 1:
                tracker.set_step(f"sleeping_{args.sleep_seconds}s")
                time.sleep(args.sleep_seconds)

    tracker.log_run_complete()
    write_run_log(log_path, [f"Run completed: {datetime.now(timezone.utc).isoformat()}"])

    results_df = pd.DataFrame(results)
    csv_path = output_dir / "agent_test_results.csv"

    if args.generate_report:
        from report_generator import generate_reports

        logger.info("Generating final reporting package...")
        generate_reports(
            results_csv_path=csv_path,
            output_dir=output_dir,
            planned_total=planned_total,
        )
        write_run_log(log_path, ["Final reporting package generated."])
        report_generated = True

    print_console_summary(
        results_df,
        output_dir,
        report_generated=report_generated,
        tracker=tracker,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
