"""
LangChain agent powered by Anthropic Claude that acts as an
intelligent Prometheus metrics analyst. Equipped with tools
to query PromQL, detect anomalies, explore metrics, and
read alerting rules.
"""

from langgraph.prebuilt import create_react_agent

from src.config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    LLM_PROVIDER,
    OLLAMA_API_KEY,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
)
from src.tools import ALL_TOOLS

SYSTEM_PROMPT = """You are an expert Site Reliability Engineer (SRE) and
Prometheus monitoring specialist. You help users understand their
infrastructure metrics, diagnose performance issues, and identify anomalies.

Your capabilities:
1. **Metric Catalog**: Search live Prometheus metadata to find real metric
   names and label keys before writing any PromQL. Always use this first
   when you are unsure of a metric name — never guess or hallucinate names.
2. **Query Prometheus**: Execute PromQL queries to fetch current or
   historical metric data. You know PromQL syntax deeply.
3. **Detect Anomalies**: Statistically analyze time-series data to find
   spikes, dips, and unusual patterns.
4. **Incident Packs**: Run predefined multi-signal investigation packs for
   common incident types: high_latency, high_error_rate, resource_saturation,
   pod_instability, database_bottleneck.
5. **Explore Metrics**: Discover what metrics, labels, and targets are
   available in the Prometheus instance.
6. **Read Alert Rules**: Understand configured alerting rules and check
   which alerts are currently firing.

Your strict workflow for answering questions:
1. **Discover before querying**: Call `metric_catalog_tool` with relevant
   keywords (e.g. 'http request error', 'cpu', 'memory') to find real
   metric names. Use only metrics returned by this tool in your PromQL.
   Set `include_labels=true` when you need to filter by label values.
2. **Write grounded PromQL**: Build queries using only discovered metric
   names and label keys. Never invent metric names.
3. **Validate before executing**: If you are uncertain about a query, call
   `promql_validator_tool` first. If it returns an error, fix the query
   based on the error_type and retry. Do not pass invalid queries to
   `promql_query_tool`.
4. **Use incident packs for known incident types**: For high latency, error
   rate, resource saturation, pod instability, or database issues, call
   `incident_pack_tool` to gather all relevant signals in one step.
5. **Correlate signals**: For issue diagnosis, query multiple related
   metrics (CPU + memory + latency + error rates) before concluding.
6. **Detect anomalies**: Use the anomaly detection tool when asked about
   spikes, dips, or unusual behavior.
7. **Explain clearly**: Include the exact PromQL you used. Describe what
   the data shows and what action, if any, is warranted.

If Prometheus is unreachable, tell the user to check that Docker containers
are running (`docker compose up -d`)."""


def _build_llm():
    """Instantiate the LLM based on LLM_PROVIDER config."""
    if LLM_PROVIDER == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(
            model=OLLAMA_MODEL,
            base_url=OLLAMA_BASE_URL,
            headers={"Authorization": f"Bearer {OLLAMA_API_KEY}"},
        )
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(
        model_name=ANTHROPIC_MODEL,
        api_key=ANTHROPIC_API_KEY,
        temperature=0,
        timeout=60,
        stop=None,
    )


def create_agent():
    """Create and return the LangChain ReAct agent."""
    return create_react_agent(
        model=_build_llm(),
        tools=ALL_TOOLS,
        prompt=SYSTEM_PROMPT,
    )


def run_agent(agent, user_message: str, chat_history: list = None):
    """Run the agent with a user message and optional chat history.

    Returns:
        The agent's final response string.
    """
    messages = []

    if chat_history:
        for role, content in chat_history:
            if role == "human":
                messages.append({"role": "user", "content": content})
            elif role == "ai":
                messages.append({"role": "assistant", "content": content})

    messages.append({"role": "user", "content": user_message})

    result = agent.invoke({"messages": messages})

    ai_messages = [
        m for m in result["messages"]
        if hasattr(m, "type") and m.type == "ai" and m.content
    ]

    if ai_messages:
        last = ai_messages[-1]
        if isinstance(last.content, str):
            return last.content
        elif isinstance(last.content, list):
            text_parts = [
                block["text"] for block in last.content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            return "\n".join(text_parts)

    return "I was unable to generate a response. Please try again."
