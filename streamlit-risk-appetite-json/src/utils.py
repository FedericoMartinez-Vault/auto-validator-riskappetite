"""Shared helpers for the Streamlit risk appetite app."""

from __future__ import annotations

import json
import re
from typing import Any


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        stripped = value.strip()
        return stripped == "" or stripped.upper() in {"NULL", "NONE", "N/A"}
    return False


def safe_json_dumps(data: Any, *, indent: int = 2) -> str:
    return json.dumps(data, indent=indent, ensure_ascii=False, default=str)


def extract_json_object(text: str) -> tuple[dict[str, Any] | None, str]:
    """Parse agent response text into a JSON object."""
    stripped = text.strip()
    if not stripped:
        return None, "empty"

    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed, "success"
    except json.JSONDecodeError:
        pass

    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", stripped, re.IGNORECASE)
    if fence:
        try:
            parsed = json.loads(fence.group(1).strip())
            if isinstance(parsed, dict):
                return parsed, "recovered_json"
        except json.JSONDecodeError:
            pass

    start = stripped.find("{")
    while start != -1:
        depth = 0
        for index, char in enumerate(stripped[start:], start=start):
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


def classification_color(classification: str) -> str:
    normalized = (classification or "").strip().lower()
    if normalized == "good fit":
        return "#1B7F3A"
    if normalized == "moderate fit":
        return "#C47A00"
    if normalized == "bad fit":
        return "#B42318"
    return "#4B5563"
