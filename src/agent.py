"""
LangChain agent powered by Anthropic Claude that acts as an
intelligent Prometheus metrics analyst. Equipped with tools
to query PromQL, detect anomalies, explore metrics, and
read alerting rules.
"""

from langchain.agents import create_agent

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
1. **Query Prometheus**: Execute PromQL queries to fetch current or 
   historical metric data. You know PromQL syntax deeply.
2. **Detect Anomalies**: Statistically analyze time-series data to find 
   spikes, dips, and unusual patterns.
3. **Explore Metrics**: Discover what metrics, labels, and targets are 
   available in the Prometheus instance.
4. **Read Alert Rules**: Understand configured alerting rules and check 
   which alerts are currently firing.

Your workflow for answering questions:
- First, explore available metrics if you are unsure what data exists.
- Write precise PromQL queries based on the user's question.
- When asked about issues or anomalies, use the anomaly detection tool 
  and correlate across multiple metrics (e.g., CPU + memory + request 
  latency + error rates) to identify root causes.
- Provide clear, actionable explanations. Avoid jargon when possible, 
  but include the exact PromQL you used so the user can reproduce.
- When explaining alerts, describe what the rule monitors, what 
  threshold triggers it, and what the operational impact could be.

Always think step-by-step and use multiple tools when needed to give 
a thorough answer. If Prometheus is unreachable, tell the user to 
check that the Docker containers are running."""


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


def spinup_agent():
    """Create and return the LangChain ReAct agent."""
    agent = create_agent(
        model=_build_llm(),
        tools=ALL_TOOLS,
        system_prompt=SYSTEM_PROMPT,
    )
    return agent


def run_agent(agent, user_message: str, chat_history: list = None):
    """Run the agent with a user message and optional chat history.

    Args:
        agent: The LangChain agent instance.
        user_message: The user's question or command.
        chat_history: List of previous (role, content) message tuples.

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

    # Extract the final AI message
    ai_messages = [
        m for m in result["messages"]
        if hasattr(m, "type") and m.type == "ai" and m.content
    ]

    if ai_messages:
        last = ai_messages[-1]
        if isinstance(last.content, str):
            return last.content
        elif isinstance(last.content, list):
            # Handle mixed content blocks
            text_parts = [
                block["text"] for block in last.content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            return "\n".join(text_parts)

    return "I was unable to generate a response. Please try again."
