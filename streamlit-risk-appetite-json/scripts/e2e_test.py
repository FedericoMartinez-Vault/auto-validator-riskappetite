"""End-to-end smoke test: parse sample Metal JSON and call Foundry agent."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src.foundry_agent_client import FoundryAgentClient
from src.metal_parser import build_submission_summary, load_json
from src.prompt_builder import build_agent_prompt


def main() -> int:
    sample = ROOT.parent / "Homeowners_FL (3).json"
    if not sample.exists():
        print(f"FAIL: sample JSON not found at {sample}")
        return 1

    print("1. Parsing Metal JSON...")
    data = load_json(str(sample))
    summary = build_submission_summary(data)
    submission = summary["submission"]
    assert submission.get("state"), "Expected state in submission"
    print(f"   OK: state={submission.get('state')}, coverage_a={submission.get('coverage_a')}")
    print(f"   OK: objects={summary['raw_counts']['number_of_objects']}, forms={summary['raw_counts']['number_of_forms']}")

    prompt = build_agent_prompt(summary)
    assert "Submission data:" in prompt
    print(f"   OK: prompt length={len(prompt)} chars")

    print("2. Connecting to Foundry...")
    try:
        with FoundryAgentClient() as client:
            agent = client.find_agent()
            print(f"   OK: agent={agent['name']} id={agent['id'][:12]}...")
            print("3. Running agent (may take 30-90s)...")
            result = client.run_agent(prompt)
    except Exception as exc:
        print(f"FAIL: Foundry error: {type(exc).__name__}: {exc}")
        return 1

    if result.get("status") == "error":
        print(f"FAIL: agent status error: {result.get('raw_text', '')[:200]}")
        return 1

    parsed = result.get("parsed_json")
    if parsed and parsed.get("classification"):
        print(f"   OK: classification={parsed.get('classification')}")
        print(f"   OK: confidence={parsed.get('confidence_score')}")
        print("E2E PASSED")
        return 0

    print(f"WARN: JSON parse status={result.get('parse_status')}; raw length={len(result.get('raw_text', ''))}")
    if result.get("raw_text"):
        print("E2E PASSED (agent responded; JSON parse may need review)")
        return 0
    print("FAIL: empty agent response")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
