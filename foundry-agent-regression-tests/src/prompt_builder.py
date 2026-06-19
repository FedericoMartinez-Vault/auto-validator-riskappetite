"""Build agent prompts from segmented underwriting CSV rows."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

BASE_PROMPT = """
Evaluate the following Texas HNW P&C quote submission using only the underwriting guidelines in the knowledge source.

Important:
- Select the correct guideline document based on underwriting company and program type.
- Use quote_status and close_reason_desc only as historical context, not as underwriting truth.
- Do not infer missing fields.
- Do not classify as Good Fit only because the historical status is Issued or Offered.
- Return strict JSON only.
- Do not include markdown, file citations, citation markers, bracket artifacts, or text outside the JSON.
- If there is a data quality issue, missing company/program, missing location, zero Coverage A, missing Coverage A, or inconsistent fields, explicitly flag it.
""".strip()

PROMPT_EXCLUDE_COLUMNS = {
    "expected_agent_focus",
    "micro_segment_rank",
    "outcome_track_rank",
    "guideline_track",
}


def _normalize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if stripped == "" or stripped.upper() == "NULL":
            return None
        return stripped
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def row_to_submission_dict(row: pd.Series) -> dict[str, Any]:
    """Serialize a CSV row for the agent prompt, excluding evaluation-only columns."""
    submission: dict[str, Any] = {}
    for column, value in row.items():
        if column in PROMPT_EXCLUDE_COLUMNS:
            continue
        submission[column] = _normalize_value(value)
    return submission


def build_prompt(row: pd.Series) -> str:
    """Build the full user prompt for a single underwriting test row."""
    submission = row_to_submission_dict(row)
    row_json = json.dumps(submission, indent=2, ensure_ascii=False)
    return f"{BASE_PROMPT}\n\nSubmission:\n{row_json}"


def extract_evaluation_fields(row: pd.Series) -> dict[str, Any]:
    """Extract local evaluation metadata preserved in output files only."""
    fields = [
        "quote_no",
        "guideline_track",
        "outcome_segment",
        "close_reason_segment",
        "territory_segment",
        "coverage_segment",
        "tiv_segment",
        "loss_segment",
        "alarm_segment",
        "sprinkler_segment",
        "gated_segment",
        "protection_class_segment",
        "fire_protection_segment",
        "expected_agent_focus",
        "quote_status",
        "close_reason_desc",
    ]
    return {field: _normalize_value(row.get(field)) for field in fields}
