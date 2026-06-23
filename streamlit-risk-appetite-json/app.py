"""Streamlit UI for Metal JSON intake and Risk Appetite agent analysis."""

from __future__ import annotations

import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.foundry_agent_client import FoundryAgentClient
from src.metal_parser import build_submission_summary, load_json
from src.prompt_builder import build_agent_prompt
from src.utils import safe_json_dumps

load_dotenv(ROOT / ".env")

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="Risk Appetite Agent",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    [data-testid="stSidebar"] { display: none; }
    .foundry-status { font-size: 0.9rem; color: #047857; font-weight: 600; }
    .foundry-error { font-size: 0.9rem; color: #b91c1c; font-weight: 600; }
    </style>
    """,
    unsafe_allow_html=True,
)

UPLOAD_KEY = "metal_json_upload"


def _file_key(uploaded) -> str:
    return f"{uploaded.name}:{uploaded.size}"


@st.cache_resource(show_spinner=False)
def get_foundry_client() -> FoundryAgentClient:
    client = FoundryAgentClient()
    client.find_agent()
    return client


def _run_agent(client: FoundryAgentClient, prompt: str, elapsed_slot) -> tuple[dict, float]:
    start = time.time()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(client.run_agent, prompt)
        while not future.done():
            elapsed = time.time() - start
            elapsed_slot.caption(f"Time elapsed: {elapsed:.0f}s")
            time.sleep(0.5)
        result = future.result()
    elapsed = time.time() - start
    elapsed_slot.caption(f"Time elapsed: {elapsed:.0f}s")
    return result, elapsed


def main() -> None:
    if "trigger_retry" not in st.session_state:
        st.session_state.trigger_retry = False

    client = None
    agent_name = "unknown"
    status_col, _ = st.columns([1, 3])
    with status_col:
        try:
            client = get_foundry_client()
            agent_name = client.agent_name or "unknown"
            st.markdown(
                f'<p class="foundry-status">Foundry connected · {agent_name}</p>',
                unsafe_allow_html=True,
            )
        except Exception as exc:
            st.markdown(
                f'<p class="foundry-error">Foundry not connected: {exc}</p>',
                unsafe_allow_html=True,
            )

    uploaded = st.file_uploader("Upload JSON", type=["json"], key=UPLOAD_KEY)

    if uploaded is None:
        return

    file_key = _file_key(uploaded)
    if st.session_state.get("result_file_key") != file_key:
        st.session_state.pop("agent_result", None)
        st.session_state.pop("analysis_error", None)
        st.session_state.pop("analysis_elapsed", None)
        st.session_state.trigger_retry = True

    try:
        summary = build_submission_summary(load_json(uploaded))
    except Exception as exc:
        st.error(f"Invalid JSON: {exc}")
        return

    prompt = build_agent_prompt(summary)

    with st.expander("Agent prompt", expanded=False):
        st.code(prompt, language="text")

    should_run = st.session_state.trigger_retry or not st.session_state.get("agent_result")
    elapsed_slot = st.empty()
    if should_run and client is not None:
        st.session_state.trigger_retry = False
        with st.spinner("Running agent…"):
            try:
                result, elapsed = _run_agent(client, prompt, elapsed_slot)
                if result.get("status") == "error":
                    st.session_state["analysis_error"] = result.get("raw_text") or "Agent error."
                elif not (result.get("parsed_json") or result.get("raw_text", "").strip()):
                    st.session_state["analysis_error"] = "Empty agent response."
                else:
                    st.session_state.pop("analysis_error", None)
                    st.session_state["agent_result"] = result
                    st.session_state["result_file_key"] = file_key
                    st.session_state["analysis_elapsed"] = elapsed
            except Exception as exc:
                st.session_state["analysis_error"] = f"{type(exc).__name__}: {exc}"
    elif st.session_state.get("analysis_elapsed") is not None:
        elapsed_slot.caption(f"Time elapsed: {st.session_state['analysis_elapsed']:.0f}s")

    if st.session_state.get("analysis_error"):
        st.error(st.session_state["analysis_error"])
        if "rate_limit_exceeded" in st.session_state["analysis_error"] or "429" in st.session_state["analysis_error"]:
            st.caption("Rate limited. Wait 1–2 minutes and retry.")
        if st.button("Retry", type="primary", key="retry_btn"):
            st.session_state.trigger_retry = True
            st.session_state.pop("analysis_error", None)
            st.rerun()
        return

    result = st.session_state.get("agent_result")
    if not result:
        return

    parsed = result.get("parsed_json")
    output_text = safe_json_dumps(parsed) if parsed else (result.get("raw_text") or "")

    with st.expander("Agent output", expanded=True):
        if parsed:
            classification = parsed.get("classification", "Unknown")
            confidence = parsed.get("confidence_score")
            summary_text = parsed.get("summary", "")
            header = f"Classification: {classification}"
            if confidence is not None:
                try:
                    header += f" · Confidence: {float(confidence):.0%}"
                except (TypeError, ValueError):
                    header += f" · Confidence: {confidence}"
            st.markdown(f"**{header}**")
            if summary_text:
                st.write(summary_text)
            st.code(output_text, language="json")
        else:
            st.code(result.get("raw_text", ""), language="text")


if __name__ == "__main__":
    main()
