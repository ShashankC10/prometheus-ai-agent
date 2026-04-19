"""
Streamlit UI for the Prometheus AI Agent.
Provides a chat interface for querying infrastructure metrics
with natural language.
"""

import requests
import streamlit as st

from src.agent import create_agent, run_agent
from src.planner import run_planner
from src.config import LLM_PROVIDER, OLLAMA_MODEL, ANTHROPIC_MODEL

# ── Page config ──────────────────────────────────────────────────────
st.set_page_config(
    page_title="Prometheus AI Agent",
    page_icon="🔥",
    layout="wide",
)

# ── Custom CSS ───────────────────────────────────────────────────────
st.markdown("""
<style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        margin-bottom: 0;
    }
    .sub-header {
        font-size: 1.1rem;
        color: #888;
        margin-top: -10px;
        margin-bottom: 20px;
    }
    .stChatMessage {
        border-radius: 12px;
    }
    .example-btn {
        margin: 2px;
    }
</style>
""", unsafe_allow_html=True)

# ── Header ───────────────────────────────────────────────────────────
st.markdown('<p class="main-header">🔥 Prometheus AI Agent</p>', unsafe_allow_html=True)
st.markdown(
    '<p class="sub-header">Ask questions about your infrastructure metrics in plain English</p>',
    unsafe_allow_html=True,
)


# ── Agent (shared across all sessions via cache_resource) ────────────
@st.cache_resource(show_spinner="Initializing agent...")
def get_agent():
    return create_agent()


# ── Sidebar ──────────────────────────────────────────────────────────
with st.sidebar:
    st.header("About")
    st.markdown(
        "This agent connects to your Prometheus instance and uses "
        "LangChain + Claude to analyze metrics, detect anomalies, "
        "and explain alerting rules."
    )

    st.divider()
    st.header("Quick Start")
    st.code("docker compose up -d", language="bash")
    st.caption("Make sure Prometheus is running on localhost:9090")

    st.divider()
    st.header("LLM")
    if LLM_PROVIDER == "ollama":
        st.info(f"Ollama · `{OLLAMA_MODEL}`")
    else:
        st.info(f"Anthropic · `{ANTHROPIC_MODEL}`")

    st.divider()
    st.header("Mode")
    use_planner = st.toggle("Multi-step planner", value=True,
                            help="Use the multi-step investigation planner (recommended). Disable to fall back to the simple ReAct agent.")

    st.divider()
    st.header("Status")
    try:
        r = requests.get("http://localhost:9090/api/v1/status/config", timeout=3)
        if r.status_code == 200:
            st.success("Prometheus: Connected")
        else:
            st.error("Prometheus: Error")
    except Exception:
        st.error("Prometheus: Not reachable")

    st.divider()
    if st.button("Clear Chat", use_container_width=True):
        st.session_state.messages = []
        st.session_state.chat_history = []
        st.rerun()

# ── Session state ────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "use_planner" not in st.session_state:
    st.session_state.use_planner = True

# ── Example questions ────────────────────────────────────────────────
EXAMPLES = [
    "What services is Prometheus monitoring right now?",
    "What is the current request rate across all endpoints?",
    "Are there any anomalies in HTTP error rates over the last hour?",
    "Explain all configured alert rules in plain language.",
    "Are any alerts currently firing?",
    "What is the p95 latency for the /api/search endpoint?",
    "Correlate CPU, memory, and request latency to diagnose issues.",
    "Show me the top endpoints by error rate.",
]

if not st.session_state.messages:
    st.markdown("#### Try asking:")
    cols = st.columns(2)
    for i, example in enumerate(EXAMPLES):
        col = cols[i % 2]
        if col.button(example, key=f"ex_{i}", use_container_width=True):
            st.session_state.pending_example = example
            st.rerun()

# Handle pending example
if "pending_example" in st.session_state:
    example = st.session_state.pop("pending_example")
    st.session_state.messages.append({"role": "user", "content": example})

# ── Chat display ─────────────────────────────────────────────────────
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ── Chat input ───────────────────────────────────────────────────────
if prompt := st.chat_input("Ask about your metrics..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

# ── Agent response ───────────────────────────────────────────────────
if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
    user_msg = st.session_state.messages[-1]["content"]

    with st.chat_message("assistant"):
        with st.spinner("Analyzing metrics..."):
            try:
                if use_planner:
                    response, tool_trace, structured = run_planner(
                        user_msg,
                        st.session_state.chat_history,
                    )
                else:
                    response = run_agent(
                        get_agent(),
                        user_msg,
                        st.session_state.chat_history,
                    )
                    tool_trace = []
                    structured = None
            except Exception as e:
                response = (
                    f"An error occurred: {str(e)}\n\n"
                    "Make sure Prometheus is running (`docker compose up -d`) "
                    "and your `ANTHROPIC_API_KEY` is set in the `.env` file."
                )
                tool_trace = []
                structured = None

        st.markdown(response)

        if structured:
            with st.expander("Structured result", expanded=False):
                cols = st.columns(3)
                cols[0].metric("Category", structured.get("issue_category", "—"))
                cols[1].metric("Confidence", structured.get("confidence", "—"))
                cols[2].metric("Anomalies", sum(
                    a.get("anomaly_count", 0)
                    for a in structured.get("anomalies_found", [])
                ))
                if structured.get("evidence_metrics"):
                    st.markdown("**Evidence metrics:** " + ", ".join(
                        f"`{m}`" for m in structured["evidence_metrics"]
                    ))
                if structured.get("recommended_actions"):
                    st.markdown("**Recommended actions:**")
                    for action in structured["recommended_actions"]:
                        st.markdown(f"- {action}")

        if tool_trace:
            with st.expander("Investigation trace", expanded=False):
                for step in tool_trace:
                    st.code(step, language=None)

    st.session_state.messages.append({"role": "assistant", "content": response})
    st.session_state.chat_history.append(("human", user_msg))
    st.session_state.chat_history.append(("ai", response))