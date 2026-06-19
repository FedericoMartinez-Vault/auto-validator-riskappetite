"""Parse agent JSON responses into structured test result fields."""

from __future__ import annotations

import json
import re
from typing import Any


def _list_to_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _extract_json_object(text: str) -> tuple[dict[str, Any] | None, str]:
    """Try to parse JSON from raw agent text, recovering fenced blocks if needed."""
    stripped = text.strip()
    if not stripped:
        return None, "failed"

    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed, "success"
    except json.JSONDecodeError:
        pass

    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", stripped, re.IGNORECASE)
    if fence_match:
        try:
            parsed = json.loads(fence_match.group(1).strip())
            if isinstance(parsed, dict):
                return parsed, "recovered_json"
        except json.JSONDecodeError:
            pass

    start = stripped.find("{")
    while start != -1:
        depth = 0
        for index in range(start, len(stripped)):
            char = stripped[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidate = stripped[start : index + 1]
                    try:
                        parsed = json.loads(candidate)
                        if isinstance(parsed, dict):
                            return parsed, "recovered_json"
                    except json.JSONDecodeError:
                        break
        start = stripped.find("{", start + 1)

    return None, "failed"


def parse_agent_response(raw_response: str) -> dict[str, Any]:
    """Parse classification fields from an agent response."""
    parsed, parse_status = _extract_json_object(raw_response)

    if parsed is None:
        return {
            "agent_classification": "",
            "confidence_score": None,
            "summary": "",
            "key_positive_factors": "",
            "risk_flags": "",
            "hnw_specific_risks": "",
            "missing_information": "",
            "raw_response": raw_response,
            "parse_status": parse_status,
            "error_message": "Unable to parse JSON from agent response.",
        }

    return {
        "agent_classification": str(parsed.get("classification", "") or ""),
        "confidence_score": parsed.get("confidence_score"),
        "summary": str(parsed.get("summary", "") or ""),
        "key_positive_factors": _list_to_string(parsed.get("key_positive_factors")),
        "risk_flags": _list_to_string(parsed.get("risk_flags")),
        "hnw_specific_risks": _list_to_string(parsed.get("hnw_specific_risks")),
        "missing_information": _list_to_string(parsed.get("missing_information")),
        "raw_response": raw_response,
        "parse_status": parse_status,
        "error_message": "",
    }
