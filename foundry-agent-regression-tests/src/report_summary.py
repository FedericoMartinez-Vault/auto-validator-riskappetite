"""Build segment-level summaries from agent regression test results."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def build_summary_by_segment(results_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate parse and classification metrics by outcome and territory segments."""
    if results_df.empty:
        return pd.DataFrame(
            columns=[
                "outcome_segment",
                "territory_segment",
                "tests_run",
                "parsed_successfully",
                "failed_parses",
                "bad_fit",
                "moderate_fit",
                "good_fit",
                "average_confidence",
            ]
        )

    working = results_df.copy()
    working["parsed_ok"] = working["parse_status"].isin(["success", "recovered_json"])
    working["confidence_score"] = pd.to_numeric(working["confidence_score"], errors="coerce")

    grouped = (
        working.groupby(["outcome_segment", "territory_segment"], dropna=False)
        .agg(
            tests_run=("test_id", "count"),
            parsed_successfully=("parsed_ok", "sum"),
            failed_parses=("parse_status", lambda s: (s == "failed").sum()),
            bad_fit=("agent_classification", lambda s: (s == "Bad Fit").sum()),
            moderate_fit=("agent_classification", lambda s: (s == "Moderate Fit").sum()),
            good_fit=("agent_classification", lambda s: (s == "Good Fit").sum()),
            average_confidence=("confidence_score", "mean"),
        )
        .reset_index()
    )
    grouped["average_confidence"] = grouped["average_confidence"].round(4)
    return grouped


def write_summary_by_segment(results_df: pd.DataFrame, output_path: Path) -> pd.DataFrame:
    summary_df = build_summary_by_segment(results_df)
    summary_df.to_csv(output_path, index=False)
    return summary_df
