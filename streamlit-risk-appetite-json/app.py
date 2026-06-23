"""Streamlit UI for Metal JSON intake and Risk Appetite agent analysis."""

from __future__ import annotations

import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.foundry_agent_client import FoundryAgentClient
from src.metal_parser import build_submission_summary, load_json
from src.prompt_builder import build_agent_prompt
from src.utils import classification_color, safe_json_dumps

load_dotenv(ROOT / ".env")

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="Risk Appetite Agent – Metal JSON Intake",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

CUSTOM_CSS = """
<style>
    .app-header {
        padding: 1rem 1.25rem;
        border-radius: 12px;
        background: linear-gradient(135deg, #0f2b46 0%, #1a4d7a 100%);
        color: white;
        margin-bottom: 1.25rem;
    }
    .app-header h1 { color: white !important; margin-bottom: 0.25rem; }
    .app-header p { color: #dbeafe; margin: 0; }
    .step-row { display: flex; gap: 0.5rem; flex-wrap: wrap; margin: 0.75rem 0 1rem 0; }
    .step-pill {
        padding: 0.35rem 0.85rem;
        border-radius: 999px;
        font-size: 0.85rem;
        font-weight: 600;
        border: 1px solid #e2e8f0;
        background: #f8fafc;
        color: #64748b;
    }
    .step-pill.done { background: #ecfdf5; border-color: #6ee7b7; color: #047857; }
    .step-pill.active {
        background: #eff6ff;
        border-color: #60a5fa;
        color: #1d4ed8;
        animation: pulse 1.5s ease-in-out infinite;
    }
    .step-pill.results-active {
        background: #fef3c7;
        border-color: #f59e0b;
        color: #b45309;
        animation: pulse 1.5s ease-in-out infinite;
        box-shadow: 0 0 12px rgba(245, 158, 11, 0.45);
    }
    @keyframes pulse {
        0%, 100% { box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.35); }
        50% { box-shadow: 0 0 0 6px rgba(59, 130, 246, 0); }
    }
    .processing-box {
        padding: 1rem 1.25rem;
        border-radius: 12px;
        border: 2px solid #3b82f6;
        background: linear-gradient(90deg, #eff6ff 0%, #f0f9ff 100%);
        margin-bottom: 1.25rem;
    }
    .metric-card {
        padding: 0.85rem 1rem;
        border-radius: 10px;
        border: 1px solid #e2e8f0;
        background: #ffffff;
        min-height: 88px;
    }
    .metric-card .label { font-size: 0.8rem; color: #64748b; margin-bottom: 0.25rem; }
    .metric-card .value { font-size: 1.25rem; font-weight: 700; color: #0f172a; }
    .result-panel {
        padding: 1.25rem;
        border-radius: 12px;
        border: 1px solid #e2e8f0;
        background: #fafafa;
        margin-top: 0.5rem;
    }
    .list-block { margin-bottom: 1rem; }
    .list-block h4 { margin-bottom: 0.35rem; font-size: 1rem; }
    .upload-hero {
        padding: 2rem 1.5rem;
        border-radius: 14px;
        border: 2px dashed #93c5fd;
        background: linear-gradient(180deg, #f8fbff 0%, #eff6ff 100%);
        margin-bottom: 1.5rem;
        text-align: center;
    }
    .upload-hero h2 {
        margin: 0 0 0.35rem 0;
        color: #0f2b46;
        font-size: 1.5rem;
    }
    .upload-hero p {
        margin: 0 0 1rem 0;
        color: #64748b;
        font-size: 0.95rem;
    }
    .error-box {
        padding: 1rem 1.25rem;
        border-radius: 12px;
        border: 2px solid #f87171;
        background: #fef2f2;
        margin-bottom: 1.25rem;
    }
    .error-box strong { color: #b91c1c; }
</style>
"""

UPLOAD_KEY = "metal_json_upload"

CLASSIFICATION_BADGE = """
<div style="
    display:inline-block;
    padding:0.65rem 1.5rem;
    border-radius:999px;
    background:{color};
    color:white;
    font-size:1.75rem;
    font-weight:700;
    margin-bottom:0.75rem;
    box-shadow: 0 4px 14px rgba(0,0,0,0.15);
">{icon} {classification}</div>
"""

CLASSIFICATION_ICONS = {
    "good fit": "✅",
    "moderate fit": "🟠",
    "bad fit": "⛔",
}

METRIC_ICONS = {
    "Program": "📋",
    "State / County": "📍",
    "Coverage A": "🏠",
    "TIV": "💰",
    "Distance to Coast": "🌊",
    "Occupancy": "🔑",
    "Protection Class": "🛡️",
    "AOP Deductible": "📉",
    "Hurricane Deductible": "🌀",
}


def _format_value(value) -> str:
    if value is None or value == "":
        return "—"
    return str(value)


def _file_key(uploaded) -> str:
    return f"{uploaded.name}:{uploaded.size}"


def _render_metric_card(label: str, value: str) -> None:
    icon = METRIC_ICONS.get(label, "•")
    st.markdown(
        f'<div class="metric-card">'
        f'<div class="label">{icon} {label}</div>'
        f'<div class="value">{value}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )


def _render_list(icon: str, title: str, items: list, *, empty_text: str = "None listed.") -> None:
    st.markdown(f'<div class="list-block"><h4>{icon} {title}</h4>', unsafe_allow_html=True)
    if items:
        for item in items:
            st.markdown(f"- {item}")
    else:
        st.caption(empty_text)
    st.markdown("</div>", unsafe_allow_html=True)


def _step_css(step_id: str, *, uploaded: bool, has_summary: bool, analyzing: bool, has_result: bool) -> str:
    if step_id == "1":
        return "step-pill done" if uploaded else "step-pill"
    if step_id == "2":
        if has_summary and (analyzing or has_result):
            return "step-pill done"
        if has_summary:
            return "step-pill active"
        return "step-pill"
    if step_id == "3":
        if has_result:
            return "step-pill done"
        if analyzing:
            return "step-pill active"
        return "step-pill"
    if step_id == "4":
        if has_result and not analyzing:
            return "step-pill results-active"
        return "step-pill"
    return "step-pill"


def _render_steps(*, uploaded: bool, has_summary: bool, analyzing: bool, has_result: bool) -> None:
    labels = [
        ("1", "📤 Upload JSON"),
        ("2", "📊 Review submission"),
        ("3", "🤖 Agent analysis"),
        ("4", "✅ Results"),
    ]
    pills = []
    for step_id, label in labels:
        css = _step_css(
            step_id,
            uploaded=uploaded,
            has_summary=has_summary,
            analyzing=analyzing,
            has_result=has_result,
        )
        pills.append(f'<span class="{css}">{label}</span>')
    st.markdown(f'<div class="step-row">{"".join(pills)}</div>', unsafe_allow_html=True)


def _scroll_to_results() -> None:
    components.html(
        """
        <script>
            const doc = window.parent.document;
            const target = doc.getElementById("agent-results-anchor");
            if (target) {
                setTimeout(() => {
                    target.scrollIntoView({ behavior: "smooth", block: "start" });
                }, 400);
            }
        </script>
        """,
        height=0,
    )


def _render_upload_hero(*, client_ready: bool) -> tuple:
    """Primary upload zone on the landing page. Returns (uploaded_file, analyze_clicked)."""
    st.markdown(
        """
        <div class="upload-hero">
            <h2>📤 Upload Metal homeowners JSON</h2>
            <p>Drag &amp; drop or browse to start the risk appetite review</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    uploaded = st.file_uploader(
        "Choose a JSON file",
        type=["json"],
        key=UPLOAD_KEY,
        label_visibility="collapsed",
        help="Export a homeowners quote from Metal as JSON.",
    )
    analyze_clicked = False
    if uploaded is not None:
        st.success(f"📄 **{uploaded.name}** loaded — review the summary below, then analyze.")
        btn_cols = st.columns([1, 1, 2])
        with btn_cols[0]:
            analyze_clicked = st.button(
                "🔍 Analyze Submission",
                type="primary",
                use_container_width=True,
                disabled=not client_ready,
                key="analyze_main",
            )
        with btn_cols[1]:
            if st.button("🗑️ Remove file", use_container_width=True, key="clear_upload"):
                st.session_state.pop(UPLOAD_KEY, None)
                st.session_state.pop("agent_result", None)
                st.session_state.pop("result_file_key", None)
                st.rerun()
    return uploaded, analyze_clicked


def _render_header(agent_name: str) -> None:
    st.markdown(
        f"""
        <div class="app-header">
            <h1>🏠 Risk Appetite Agent</h1>
            <p>Metal JSON intake · HNW P&amp;C underwriting · Agent: <strong>{agent_name}</strong></p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _processing_banner_html(elapsed: float, agent_name: str) -> str:
    return f"""
        <div class="processing-box">
            <strong>🔄 Analysis in progress</strong><br>
            Sending submission to <em>{agent_name}</em> and waiting for underwriting assessment…
            <br><small>Elapsed: <strong>{elapsed:.0f}s</strong> · Typical response: 30–90s</small>
        </div>
        """


def _render_processing_banner(elapsed: float, agent_name: str) -> None:
    st.markdown(_processing_banner_html(elapsed, agent_name), unsafe_allow_html=True)


def _render_analysis_error(message: str) -> bool:
    """Show error panel with retry button. Returns True if retry was clicked."""
    st.markdown(
        """
        <div class="error-box">
            <strong>❌ Analysis failed</strong><br>
            <small>Check your connection, Foundry status, and try again.</small>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if "rate_limit_exceeded" in message or "Error code: 429" in message:
        st.warning(
            "The model deployment is temporarily rate-limited (HTTP 429). "
            "Wait 1–2 minutes, then click **Retry analysis**."
        )
    st.code(message, language="text")
    return st.button("🔄 Retry analysis", type="primary", key="retry_analysis_btn")


def _run_agent_with_live_timer(
    client: FoundryAgentClient,
    prompt: str,
    agent_name: str,
    banner_slot,
    progress_bar,
) -> tuple[dict, float]:
    """Run the agent in a background thread and refresh elapsed time while waiting."""
    start = time.time()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(client.run_agent, prompt)
        while not future.done():
            elapsed = time.time() - start
            banner_slot.markdown(_processing_banner_html(elapsed, agent_name), unsafe_allow_html=True)
            pct = min(90, 25 + int(elapsed / 90 * 65))
            progress_bar.progress(pct, text=f"Waiting for agent response… {elapsed:.0f}s elapsed")
            time.sleep(0.5)

        result = future.result()

    elapsed = time.time() - start
    banner_slot.markdown(_processing_banner_html(elapsed, agent_name), unsafe_allow_html=True)
    return result, elapsed


def _render_agent_result(parsed: dict, result: dict, *, show_raw: bool) -> None:
    classification = parsed.get("classification", "Unknown")
    normalized = (classification or "").strip().lower()
    icon = CLASSIFICATION_ICONS.get(normalized, "❔")
    color = classification_color(classification)

    st.markdown('<div id="agent-results-anchor"></div>', unsafe_allow_html=True)
    st.markdown("### 🎯 Agent Assessment")
    st.markdown(
        f'<div class="result-panel">',
        unsafe_allow_html=True,
    )
    st.markdown(
        CLASSIFICATION_BADGE.format(color=color, classification=classification, icon=icon),
        unsafe_allow_html=True,
    )

    confidence = parsed.get("confidence_score")
    conf_cols = st.columns([1, 2])
    with conf_cols[0]:
        if confidence is not None:
            try:
                st.metric("🎯 Confidence", f"{float(confidence):.0%}")
            except (TypeError, ValueError):
                st.metric("🎯 Confidence", str(confidence))
    with conf_cols[1]:
        if parsed.get("summary"):
            st.info(f"**Summary:** {parsed['summary']}")

    left, right = st.columns(2)
    with left:
        _render_list("✅", "Key positive factors", parsed.get("key_positive_factors", []))
        _render_list("🚩", "Risk flags", parsed.get("risk_flags", []))
        _render_list("💎", "HNW-specific risks", parsed.get("hnw_specific_risks", []))
    with right:
        _render_list("❓", "Missing information", parsed.get("missing_information", []))
        _render_list("💬", "Next best questions", parsed.get("next_best_questions", []))
        _render_list("📚", "Guideline references", parsed.get("guideline_references", []))

    completeness = parsed.get("submission_completeness_observations", [])
    if completeness:
        _render_list("📝", "Submission completeness", completeness)

    if not parsed:
        st.warning(
            f"Could not parse JSON from agent response ({result.get('parse_status', 'failed')}). "
            "See raw response below."
        )

    if show_raw:
        with st.expander("🔍 Raw agent response", expanded=not parsed):
            st.code(result.get("raw_text", ""), language="text")

    st.markdown("</div>", unsafe_allow_html=True)


@st.cache_resource(show_spinner="🔌 Connecting to Foundry…")
def get_foundry_client() -> FoundryAgentClient:
    client = FoundryAgentClient()
    client.find_agent()
    return client


def main() -> None:
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    st.session_state.pop("retry_analysis", None)

    if "trigger_retry" not in st.session_state:
        st.session_state.trigger_retry = False

    client = None
    agent_name = st.session_state.get("agent_name", "Not connected")
    agent_id = st.session_state.get("agent_id", "")

    with st.sidebar:
        st.markdown("### ⚙️ Configuration")
        try:
            client = get_foundry_client()
            agent_name = client.agent_name or "Unknown"
            agent_id = client.agent_id or ""
            st.session_state["foundry_endpoint"] = client.project_endpoint
            st.session_state["agent_name"] = agent_name
            st.session_state["agent_id"] = agent_id
            st.success("☁️ Foundry connected")
            st.text_input("🔗 Project endpoint", value=client.project_endpoint, disabled=True)
            st.text_input("🤖 Agent", value=agent_name, disabled=True)
            if agent_id:
                st.caption(f"ID: {agent_id[:16]}…")
        except Exception as exc:
            st.error(f"❌ Foundry setup error: {exc}")

        st.divider()
        st.markdown("### 📤 Submission")
        uploaded = st.session_state.get(UPLOAD_KEY)
        if uploaded is not None:
            st.success(f"📄 {uploaded.name}")
            st.caption(f"{uploaded.size / 1024:.1f} KB")
        else:
            st.caption("Upload a JSON file on the main page to begin.")
        analyze_sidebar = st.button(
            "🔍 Analyze Submission",
            type="primary",
            use_container_width=True,
            disabled=uploaded is None or client is None,
            key="analyze_sidebar",
        )
        st.divider()
        show_extracted = st.toggle("🗂️ Show extracted fields", value=False)
        show_raw = st.toggle("🔍 Show raw agent response", value=False)
        if st.session_state.get("agent_result") or st.session_state.get("analysis_error"):
            if st.button("🗑️ Clear results", use_container_width=True):
                st.session_state.pop("agent_result", None)
                st.session_state.pop("result_file_key", None)
                st.session_state.pop("analysis_error", None)
                st.rerun()

    uploaded, analyze_main = _render_upload_hero(client_ready=client is not None)
    _render_header(agent_name)
    analyze = analyze_sidebar or analyze_main or st.session_state.trigger_retry

    if uploaded is None:
        _render_steps(uploaded=False, has_summary=False, analyzing=False, has_result=False)
        return

    file_key = _file_key(uploaded)
    if st.session_state.get("result_file_key") != file_key:
        st.session_state.pop("agent_result", None)

    try:
        raw_data = load_json(uploaded)
        summary = build_submission_summary(raw_data)
    except Exception as exc:
        st.error(f"❌ Failed to parse JSON: {exc}")
        return

    submission = summary["submission"]
    counts = summary["raw_counts"]
    prompt = build_agent_prompt(summary)
    has_cached_result = bool(st.session_state.get("agent_result"))
    steps_slot = st.empty()

    def _show_steps(*, analyzing: bool, has_result: bool) -> None:
        with steps_slot.container():
            _render_steps(
                uploaded=True,
                has_summary=True,
                analyzing=analyzing,
                has_result=has_result,
            )

    if analyze:
        if client is None:
            st.session_state["analysis_error"] = "Foundry client is not connected. Check configuration in the sidebar."
            st.session_state.trigger_retry = False
            st.rerun()

        is_analyzing = True
        st.session_state.trigger_retry = False
        st.session_state.pop("analysis_error", None)
        _show_steps(analyzing=True, has_result=False)

        banner_slot = st.empty()
        banner_slot.markdown(_processing_banner_html(0, agent_name), unsafe_allow_html=True)

        status = st.status("🤖 Running Risk Appetite agent…", expanded=True)
        with status:
            st.write("📋 Submission parsed and normalized")
            time.sleep(0.2)
            st.write(f"📤 Sending prompt to **{agent_name}** ({len(prompt):,} chars)")
            progress = st.progress(0, text="Connecting to Foundry…")
            progress.progress(10, text="Connecting to Foundry…")

            try:
                result, elapsed = _run_agent_with_live_timer(
                    client, prompt, agent_name, banner_slot, progress
                )
                progress.progress(95, text="Parsing agent response…")
                time.sleep(0.15)
                progress.progress(100, text=f"Complete — {elapsed:.0f}s")

                if result.get("status") == "error":
                    st.session_state["analysis_error"] = result.get("raw_text") or "The agent returned an error."
                    status.update(label="❌ Analysis failed", state="error", expanded=True)
                    banner_slot.empty()
                    _show_steps(analyzing=False, has_result=False)
                elif not (result.get("parsed_json") or result.get("raw_text", "").strip()):
                    st.session_state["analysis_error"] = "The agent returned an empty response."
                    status.update(label="❌ Empty response", state="error", expanded=True)
                    banner_slot.empty()
                    _show_steps(analyzing=False, has_result=False)
                else:
                    st.session_state.pop("analysis_error", None)
                    st.session_state["agent_result"] = result
                    st.session_state["result_file_key"] = file_key
                    st.session_state["scroll_to_results"] = True
                    status.update(label=f"✅ Analysis complete ({elapsed:.0f}s)", state="complete", expanded=False)
                    banner_slot.empty()
                    _show_steps(analyzing=False, has_result=True)
                    st.toast(f"Analysis complete — {elapsed:.0f}s", icon="✅")

            except Exception as exc:
                error_msg = f"{type(exc).__name__}: {exc}"
                st.session_state["analysis_error"] = error_msg
                status.update(label="❌ Analysis failed", state="error", expanded=True)
                banner_slot.empty()
                _show_steps(analyzing=False, has_result=False)
    else:
        _show_steps(analyzing=False, has_result=has_cached_result)

    if st.session_state.get("analysis_error"):
        if _render_analysis_error(st.session_state["analysis_error"]):
            st.session_state.trigger_retry = True
            st.rerun()

    st.markdown("### 📊 Submission Summary")
    st.caption(f"📄 **{uploaded.name}** · {counts.get('number_of_objects', 0)} objects · {counts.get('number_of_non_null_fields', 0)} fields")

    cols = st.columns(3)
    cards = [
        ("Program", _format_value(submission.get("program"))),
        ("State / County", f"{_format_value(submission.get('state'))} / {_format_value(submission.get('county'))}"),
        ("Coverage A", _format_value(submission.get("coverage_a"))),
        ("TIV", _format_value(submission.get("tiv"))),
        ("Distance to Coast", _format_value(submission.get("distance_to_coast"))),
        ("Occupancy", _format_value(submission.get("occupancy"))),
        ("Protection Class", _format_value(submission.get("protection_class"))),
        ("AOP Deductible", _format_value(submission.get("aop_deductible"))),
        ("Hurricane Deductible", _format_value(submission.get("hurricane_deductible"))),
    ]
    for index, (label, value) in enumerate(cards):
        with cols[index % 3]:
            _render_metric_card(label, value)

    missing = summary.get("missing_key_fields", [])
    if missing:
        st.warning(f"⚠️ Missing key fields ({len(missing)}): {', '.join(missing)}")
    else:
        st.success("✅ All key submission fields are populated.")

    meta_cols = st.columns(2)
    with meta_cols[0]:
        st.metric("🗂️ Non-null fields", counts.get("number_of_non_null_fields", 0))
    with meta_cols[1]:
        st.metric("📑 Forms", counts.get("number_of_forms", 0))

    if show_extracted:
        with st.expander("🗂️ Extracted fields by object", expanded=True):
            st.json(summary.get("all_non_null_fields_by_object", {}))

    with st.expander("📝 Prompt sent to agent"):
        st.code(prompt, language="text")
    with st.expander("🧩 Extracted normalized JSON"):
        st.code(safe_json_dumps(summary), language="json")

    if not analyze and not has_cached_result:
        if not st.session_state.get("analysis_error"):
            st.info("🔍 Click **Analyze Submission** above or in the sidebar when ready.")
        return

    result = st.session_state.get("agent_result")
    if not result:
        return

    parsed = result.get("parsed_json") or {}
    _render_agent_result(parsed, result, show_raw=show_raw)

    if st.session_state.pop("scroll_to_results", False):
        _scroll_to_results()


if __name__ == "__main__":
    main()
