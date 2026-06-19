"""Build compact prompts for the Risk Appetite Foundry agent."""

from __future__ import annotations

import json
from typing import Any

AGENT_PROMPT_TEMPLATE = """You are an expert High Net Worth Property & Casualty insurance underwriting assistant.

Assess the following Metal homeowners submission and classify it into:

* Good Fit
* Moderate Fit
* Bad Fit

Use the underwriting/risk appetite guidelines available to you. Do not assume facts not present. If information is missing, explicitly list it.

Submission data:
{submission_json}

Return ONLY valid JSON with this structure:
{{
"classification": "Good Fit | Moderate Fit | Bad Fit",
"confidence_score": 0.0,
"summary": "Brief explanation",
"key_positive_factors": [],
"risk_flags": [],
"hnw_specific_risks": [],
"guideline_references": [],
"missing_information": [],
"next_best_questions": [],
"submission_completeness_observations": []
}}

Important:
* Do not include markdown.
* Do not include text outside JSON.
* Do not invent missing values.
* Treat the JSON as a single submission/quote.
* Use the risk appetite documents and guidelines available to the agent.
* Pay attention to state, county, distance to coast, Coverage A, TIV, deductibles, protection class, alarms, sprinklers, prior losses, construction, roof, and CAT exposure.
"""


def build_agent_prompt(submission_summary: dict[str, Any]) -> str:
    """Build the user prompt sent to the Foundry agent."""
    compact = {
        "submission": submission_summary.get("submission", {}),
        "missing_key_fields": submission_summary.get("missing_key_fields", []),
        "forms": submission_summary.get("forms", []),
        "collection_classes": submission_summary.get("collection_classes", []),
        "raw_counts": submission_summary.get("raw_counts", {}),
    }
    submission_json = json.dumps(compact, indent=2, ensure_ascii=False, default=str)
    return AGENT_PROMPT_TEMPLATE.format(submission_json=submission_json)
