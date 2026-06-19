"""Generate AI-powered conclusions for regression test reports."""

from __future__ import annotations

import json
import logging
import os
from collections import Counter
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from azure.ai.projects import AIProjectClient
from azure.core.exceptions import HttpResponseError
from azure.identity import DefaultAzureCredential
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

ANALYSIS_SYSTEM_PROMPT = """You are an underwriting QA analyst writing the conclusions section of a segmented regression test report for the AF-UW-RiskAppetite Azure Foundry agent.

This is segmented underwriting regression testing for Texas VES/VRE HNW P&C guideline evaluation. It is NOT cybersecurity testing. Do not use the word cybersecurity.

Write in clear professional English for Vault Insurance stakeholders.

Rules:
- Use ONLY the aggregated statistics in the user message. Do not invent counts or quotes.
- If total_tests is less than the full planned sample, clearly label this as an interim/partial analysis.
- Be concise but substantive (about 600-1000 words).
- Focus on whether the agent applied VES/VRE guidelines correctly, avoided relying on historical quote status, handled territory and Coverage A rules, flagged data quality issues, and returned reliable JSON.
- Refer to the work as Instruction Compliance / Task Drift Resistance testing.

Structure your response with these markdown headings:
## Overall Assessment
## Guideline and Segment Performance
## Outcome Segment Behavior
## Data Quality and JSON Reliability
## Instruction Compliance / Task Drift Resistance
## Areas of Concern
## Recommendations
"""


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, HttpResponseError):
        return exc.status_code in {408, 409, 429, 500, 502, 503, 504}
    message = str(exc).lower()
    return any(token in message for token in ("rate limit", "too many requests", "timeout", "throttl"))


def _count_dict(series: pd.Series, limit: int = 12) -> dict[str, int]:
    counts = series.fillna("Unknown").replace("", "Unknown").value_counts().head(limit)
    return {str(k): int(v) for k, v in counts.items()}


def _top_flag_counts(df: pd.DataFrame, column: str, limit: int = 12) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for value in df.get(column, pd.Series(dtype=str)):
        text = "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)
        if not text:
            continue
        try:
            items = json.loads(text)
            if isinstance(items, list):
                for item in items:
                    if str(item).strip():
                        counter[str(item).strip()] += 1
                continue
        except json.JSONDecodeError:
            pass
        counter[text[:120]] += 1
    return dict(counter.most_common(limit))


def build_analysis_payload(df: pd.DataFrame, planned_total: int | None = None) -> dict[str, Any]:
    """Build a compact statistics payload for the analysis model."""
    total = len(df)
    parsed_ok = int(df["parse_status"].isin(["success", "recovered_json"]).sum())
    failed_parses = int((df["parse_status"] == "failed").sum())
    avg_conf = pd.to_numeric(df["confidence_score"], errors="coerce").mean()

    if "evaluation_result" not in df.columns:
        from report_generator import infer_evaluation_result

        df = df.copy()
        df["evaluation_result"] = df.apply(infer_evaluation_result, axis=1)

    issued_offered_bad = df[
        df["outcome_segment"].isin(["Issued", "Offered"]) & (df["agent_classification"] == "Bad Fit")
    ]

    manual_review = df[df["evaluation_result"] == "Needs Manual Review"]
    failures = df[df["evaluation_result"] == "Fail"]

    return {
        "report_generated_utc": datetime.now(timezone.utc).isoformat(),
        "total_tests_in_report": total,
        "planned_total_tests": planned_total or total,
        "is_interim_report": planned_total is not None and total < planned_total,
        "parsed_successfully": parsed_ok,
        "failed_parses": failed_parses,
        "classifications": _count_dict(df["agent_classification"]),
        "evaluation_results": _count_dict(df["evaluation_result"]),
        "average_confidence": round(float(avg_conf), 4) if pd.notna(avg_conf) else None,
        "by_guideline_track": _count_dict(df.get("guideline_track", pd.Series(dtype=str))),
        "by_outcome_segment": _count_dict(df.get("outcome_segment", pd.Series(dtype=str))),
        "by_territory_segment": _count_dict(df.get("territory_segment", pd.Series(dtype=str))),
        "by_coverage_segment": _count_dict(df.get("coverage_segment", pd.Series(dtype=str))),
        "issued_or_offered_classified_bad_fit": int(len(issued_offered_bad)),
        "ves_tests": int(df["guideline_track"].astype(str).str.contains("VES", na=False).sum()),
        "vre_tests": int(df["guideline_track"].astype(str).str.contains("VRE", na=False).sum()),
        "top_risk_flags": _top_flag_counts(df, "risk_flags"),
        "top_missing_information": _top_flag_counts(df, "missing_information"),
        "manual_review_count": int(len(manual_review)),
        "failure_count": int(len(failures)),
        "manual_review_examples": [
            {
                "quote_no": row.get("quote_no"),
                "expected_agent_focus": row.get("expected_agent_focus"),
                "classification": row.get("agent_classification"),
                "summary": str(row.get("summary", ""))[:220],
            }
            for _, row in manual_review.head(5).iterrows()
        ],
        "failure_examples": [
            {
                "quote_no": row.get("quote_no"),
                "error": str(row.get("error_message", ""))[:220],
            }
            for _, row in failures.head(5).iterrows()
        ],
    }


def _resolve_model_deployment(project_client: AIProjectClient) -> str | None:
    try:
        for deployment in project_client.deployments.list():
            name = getattr(deployment, "name", None) or getattr(deployment, "id", None)
            if name:
                return str(name)
    except Exception as exc:
        logger.warning("Could not list deployments: %s", exc)
    return os.getenv("REPORT_MODEL_DEPLOYMENT", "").strip() or None


@retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=4, max=90),
    reraise=True,
)
def _call_analysis_model(payload: dict[str, Any]) -> str:
    endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT", "").strip()
    if not endpoint:
        raise ValueError("FOUNDRY_PROJECT_ENDPOINT is required for AI analysis.")

    credential = DefaultAzureCredential()
    project_client = AIProjectClient(endpoint=endpoint, credential=credential)
    try:
        model = _resolve_model_deployment(project_client)
        user_content = (
            "Analyze these aggregated regression test statistics and write the conclusions section.\n\n"
            f"```json\n{json.dumps(payload, indent=2, ensure_ascii=False)}\n```"
        )

        with project_client.get_openai_client() as openai_client:
            kwargs: dict[str, Any] = {
                "instructions": ANALYSIS_SYSTEM_PROMPT,
                "input": user_content,
            }
            if model:
                kwargs["model"] = model
            response = openai_client.responses.create(**kwargs)
            text = (response.output_text or "").strip()
            if text:
                return text
            raise RuntimeError("Analysis model returned an empty response.")
    finally:
        project_client.close()
        credential.close()


def _fallback_analysis(payload: dict[str, Any]) -> str:
    total = payload["total_tests_in_report"]
    interim = " (interim — run still in progress)" if payload.get("is_interim_report") else ""
    classifications = payload.get("classifications", {})
    evaluations = payload.get("evaluation_results", {})

    lines = [
        "## Overall Assessment",
        "",
        f"This report summarizes {total} completed segmented underwriting regression tests{interim} "
        f"for the AF-UW-RiskAppetite agent.",
        "",
        f"- Parsed successfully: {payload.get('parsed_successfully', 0)}",
        f"- Failed parses: {payload.get('failed_parses', 0)}",
        f"- Average confidence: {payload.get('average_confidence', 'N/A')}",
        f"- Classifications: {classifications}",
        f"- Evaluation results: {evaluations}",
        "",
        "## Guideline and Segment Performance",
        "",
        f"- VES tests: {payload.get('ves_tests', 0)}",
        f"- VRE tests: {payload.get('vre_tests', 0)}",
        f"- Issued/Offered classified as Bad Fit: {payload.get('issued_or_offered_classified_bad_fit', 0)}",
        "",
        "## Recommendations",
        "",
        "- Continue segmented regression testing on each agent update.",
        "- Review manual-review and failed cases in agent_test_results.json.",
        "",
        "_AI analysis was unavailable; this is a template fallback._",
    ]
    return "\n".join(lines)


def generate_results_analysis(
    df: pd.DataFrame,
    output_dir: str | os.PathLike[str],
    planned_total: int | None = None,
) -> str:
    """Generate and persist markdown conclusions from aggregated test statistics."""
    output_dir = os.fspath(output_dir)
    payload = build_analysis_payload(df, planned_total=planned_total)

    try:
        analysis = _call_analysis_model(payload)
        logger.info("AI results analysis generated (%s tests).", payload["total_tests_in_report"])
    except Exception as exc:
        logger.warning("AI analysis failed, using fallback: %s", exc)
        analysis = _fallback_analysis(payload)

    analysis_path = os.path.join(output_dir, "results_analysis.md")
    header = (
        f"# Results Analysis & Conclusions\n\n"
        f"_Generated: {payload['report_generated_utc']} | "
        f"Tests in report: {payload['total_tests_in_report']}"
    )
    if payload.get("is_interim_report"):
        header += f" of {payload['planned_total_tests']} planned (interim)_"
    else:
        header += "_"

    content = f"{header}\n\n{analysis.strip()}\n"
    with open(analysis_path, "w", encoding="utf-8") as handle:
        handle.write(content)

    payload_path = os.path.join(output_dir, "analysis_payload.json")
    with open(payload_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)

    return content
