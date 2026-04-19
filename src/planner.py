"""
Multi-step investigation planner for the Prometheus AI Agent.

Replaces the flat ReAct loop with an explicit LangGraph StateGraph that:
1. Classifies the question type (router)
2. Optionally discovers relevant metrics (metric grounding)
3. Builds and validates PromQL
4. Runs queries and/or anomaly detection
5. Synthesizes an evidence-backed answer

Question categories:
  - metric_lookup        : simple current-value queries
  - error_triage         : error rate / 5xx investigation
  - latency_analysis     : p95/p99, histogram analysis
  - anomaly_investigation: spike/dip/trend detection
  - alert_explanation    : alert rules and firing alerts
  - resource_saturation  : CPU / memory / disk
  - incident_investigation: multi-signal correlation
"""

from __future__ import annotations

import json
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from src.config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    LLM_PROVIDER,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
)
from src.tools import ALL_TOOLS
from src.tools.metric_catalog import metric_catalog_tool
from src.tools.promql_query import promql_query_tool
from src.tools.promql_validator import promql_validator_tool
from src.tools.anomaly_detection import anomaly_detection_tool
from src.tools.alert_rules import alert_rules_tool
from src.tools.metric_explorer import metric_explorer_tool
from src.tools.incident_packs import incident_pack_tool, PACK_DEFINITIONS
from src.tools.runbook import runbook_tool
from src.tools.topology import topology_tool
from src.structured_output import build_structured_result

QUESTION_CATEGORIES = Literal[
    "metric_lookup",
    "error_triage",
    "latency_analysis",
    "anomaly_investigation",
    "alert_explanation",
    "resource_saturation",
    "incident_investigation",
]

_TOOL_MAP = {t.name: t for t in ALL_TOOLS}


# ── State ─────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    question: str
    category: str | None
    discovered_metrics: list[str]
    queries_run: list[dict]
    anomalies_found: list[dict]
    alert_context: dict | None
    incident_pack_results: list[dict]
    runbook_context: dict | None
    topology_context: dict | None
    tool_trace: list[str]
    final_answer: str | None
    structured_result: dict | None


# ── LLM factory ──────────────────────────────────────────────────────

def _build_llm():
    if LLM_PROVIDER == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(model=OLLAMA_MODEL, base_url=OLLAMA_BASE_URL)
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(
        model=ANTHROPIC_MODEL,
        api_key=ANTHROPIC_API_KEY,
        temperature=0,
        max_tokens=4096,
    )


_llm = None


def get_llm():
    global _llm
    if _llm is None:
        _llm = _build_llm()
    return _llm


# ── Node: classify question ───────────────────────────────────────────

_CLASSIFY_PROMPT = """Classify the following monitoring question into exactly one category.
Reply with ONLY the category name, nothing else.

Categories:
- metric_lookup: simple current value or rate queries, listing services or targets
- error_triage: investigating error rates, 4xx/5xx counts, failure reasons
- latency_analysis: p95/p99 latency, histogram analysis, response time
- anomaly_investigation: detecting spikes, dips, unusual patterns, trends
- alert_explanation: explaining alert rules, checking which alerts are firing
- resource_saturation: CPU, memory, disk, network utilisation
- incident_investigation: multi-signal correlation, diagnosing a broader issue

Question: {question}"""


def classify_node(state: AgentState) -> AgentState:
    question = state["question"]
    response = get_llm().invoke(
        [HumanMessage(content=_CLASSIFY_PROMPT.format(question=question))]
    )
    category = response.content.strip().lower()
    valid = {
        "metric_lookup", "error_triage", "latency_analysis",
        "anomaly_investigation", "alert_explanation",
        "resource_saturation", "incident_investigation",
    }
    if category not in valid:
        category = "metric_lookup"
    return {**state, "category": category, "tool_trace": [f"classify → {category}"]}


# ── Node: metric discovery ────────────────────────────────────────────

_KEYWORDS_PROMPT = """Given this monitoring question, list 3-6 keywords to search for
relevant Prometheus metric names. Reply with ONLY space-separated keywords.

Question: {question}"""

_SKIP_DISCOVERY = {"alert_explanation"}


def discovery_node(state: AgentState) -> AgentState:
    if state["category"] in _SKIP_DISCOVERY:
        return state

    question = state["question"]
    response = get_llm().invoke(
        [HumanMessage(content=_KEYWORDS_PROMPT.format(question=question))]
    )
    keywords = response.content.strip()

    result_json = metric_catalog_tool.invoke(
        {"keywords": keywords, "include_labels": False}
    )
    result = json.loads(result_json)
    candidates = [c["metric"] for c in result.get("candidates", [])][:10]

    trace = state["tool_trace"] + [
        f"metric_catalog({keywords!r}) → {len(candidates)} candidates"
    ]
    return {**state, "discovered_metrics": candidates, "tool_trace": trace}


# ── Node: query execution ─────────────────────────────────────────────

_QUERY_PROMPT = """You are a Prometheus expert. Given the user question and a list of
available metrics, write 1-3 PromQL queries that best answer the question.

Available metrics (use ONLY these):
{metrics}

User question: {question}
Category: {category}

Reply with a JSON array of objects, each with:
  "promql": the PromQL expression
  "query_type": "instant" or "range"
  "duration_minutes": integer (for range queries, e.g. 60)
  "step": string (e.g. "60s")
  "purpose": one sentence describing what this query measures

Reply with ONLY valid JSON. No explanation, no markdown."""


def query_node(state: AgentState) -> AgentState:
    if state["category"] == "alert_explanation":
        return state

    metrics_str = "\n".join(f"- {m}" for m in state["discovered_metrics"]) or "No catalog results — use your best judgment."

    prompt = _QUERY_PROMPT.format(
        metrics=metrics_str,
        question=state["question"],
        category=state["category"],
    )
    response = get_llm().invoke([HumanMessage(content=prompt)])

    try:
        raw = response.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        queries = json.loads(raw)
    except Exception:
        queries = []

    executed = []
    trace = state["tool_trace"][:]

    for q in queries[:3]:
        promql = q.get("promql", "")
        query_type = q.get("query_type", "instant")
        duration = q.get("duration_minutes", 60)
        step = q.get("step", "60s")
        purpose = q.get("purpose", "")

        # Validate first
        val_json = promql_validator_tool.invoke(
            {"promql": promql, "duration_minutes": duration, "step": step}
        )
        val = json.loads(val_json)
        trace.append(f"validate({promql[:60]}) → valid={val['validation']['valid']}")

        if not val["validation"]["valid"]:
            executed.append({
                "promql": promql,
                "purpose": purpose,
                "error": val["validation"]["error_message"],
                "result": None,
            })
            continue

        safe = val["safe_params"]
        result_json = promql_query_tool.invoke({
            "promql": promql,
            "query_type": query_type,
            "duration_minutes": safe["duration_minutes"],
            "step": safe["step"],
        })
        trace.append(f"query({promql[:60]}) → executed")
        executed.append({
            "promql": promql,
            "purpose": purpose,
            "error": None,
            "result": json.loads(result_json),
        })

    return {**state, "queries_run": executed, "tool_trace": trace}


# ── Node: incident pack ───────────────────────────────────────────────

# Map question categories to the most relevant incident pack
_CATEGORY_TO_PACK = {
    "high_error_rate": "high_error_rate",
    "error_triage": "high_error_rate",
    "latency_analysis": "high_latency",
    "resource_saturation": "resource_saturation",
    "incident_investigation": None,  # pick dynamically
}

_PACK_KEYWORDS = {
    "high_latency": ["latency", "slow", "response time", "p95", "p99"],
    "high_error_rate": ["error", "5xx", "fail", "500"],
    "resource_saturation": ["cpu", "memory", "disk", "ram", "saturation"],
    "pod_instability": ["pod", "container", "restart", "oom", "crash"],
    "database_bottleneck": ["database", "db", "query", "sql", "connection"],
}


def _select_pack(question: str) -> str | None:
    q = question.lower()
    for pack, kws in _PACK_KEYWORDS.items():
        if any(kw in q for kw in kws):
            return pack
    return None


def incident_pack_node(state: AgentState) -> AgentState:
    category = state["category"]
    if category not in {"incident_investigation", "error_triage", "latency_analysis", "resource_saturation"}:
        return state

    pack_name = _CATEGORY_TO_PACK.get(category) or _select_pack(state["question"])
    if not pack_name or pack_name not in PACK_DEFINITIONS:
        return state

    trace = state["tool_trace"][:]
    result_json = incident_pack_tool.invoke({"pack_name": pack_name})
    result = json.loads(result_json)
    trace.append(
        f"incident_pack({pack_name}) → {result.get('signals_succeeded', 0)}/{result.get('signals_total', 0)} signals"
    )

    # Merge pack signal results into queries_run so synthesiser sees them
    pack_queries = []
    for sig in result.get("results", []):
        if sig["status"] == "success" and sig["result"]:
            pack_queries.append({
                "promql": sig["promql"],
                "purpose": sig["name"],
                "error": None,
                "result": {"results": sig["result"]},
            })

    merged_queries = state["queries_run"] + pack_queries
    return {
        **state,
        "incident_pack_results": [result],
        "queries_run": merged_queries,
        "tool_trace": trace,
    }


# ── Node: anomaly detection ───────────────────────────────────────────

_ANOMALY_CATEGORIES = {"anomaly_investigation", "incident_investigation"}


def anomaly_node(state: AgentState) -> AgentState:
    if state["category"] not in _ANOMALY_CATEGORIES:
        return state

    anomalies = []
    trace = state["tool_trace"][:]

    metrics_to_check = state["discovered_metrics"][:3] or [
        q["promql"] for q in state["queries_run"] if not q["error"]
    ][:3]

    for metric in metrics_to_check:
        result_json = anomaly_detection_tool.invoke(
            {"promql": metric, "duration_minutes": 60, "z_threshold": 2.0}
        )
        result = json.loads(result_json)
        analysis = result.get("analysis", [])
        for series in analysis:
            if series.get("anomaly_count", 0) > 0:
                anomalies.append(series)
        trace.append(
            f"anomaly_detection({metric[:50]}) → {sum(s.get('anomaly_count',0) for s in analysis)} anomalies"
        )

    return {**state, "anomalies_found": anomalies, "tool_trace": trace}


# ── Node: alert context ───────────────────────────────────────────────

_ALERT_CATEGORIES = {"alert_explanation", "incident_investigation"}


def alert_node(state: AgentState) -> AgentState:
    if state["category"] not in _ALERT_CATEGORIES:
        return state

    trace = state["tool_trace"][:]
    rules_json = alert_rules_tool.invoke({"action": "list"})
    firing_json = alert_rules_tool.invoke({"action": "firing"})
    trace.append("alert_rules(list) + alert_rules(firing)")

    alert_context = {
        "rules": json.loads(rules_json),
        "firing": json.loads(firing_json),
    }
    return {**state, "alert_context": alert_context, "tool_trace": trace}


# ── Node: runbook grounding ───────────────────────────────────────────

def runbook_node(state: AgentState) -> AgentState:
    """Fetch relevant runbooks based on firing alerts or question category."""
    trace = state["tool_trace"][:]
    runbook_context: dict = {}

    # If alerts are firing, fetch runbooks for each
    firing = []
    if state["alert_context"]:
        firing = state["alert_context"].get("firing", {}).get("firing", [])

    fetched = []
    for alert in firing[:3]:
        alert_name = alert.get("alert_name", "")
        if alert_name:
            result_json = runbook_tool.invoke({"action": "get", "query": alert_name})
            result = json.loads(result_json)
            if "runbooks" in result:
                fetched.extend(result["runbooks"])

    # If no firing alerts, try to match by category/question keyword
    if not fetched:
        keyword_map = {
            "error_triage": "error rate",
            "latency_analysis": "latency",
            "resource_saturation": "cpu memory disk",
            "anomaly_investigation": "",
            "incident_investigation": "",
        }
        keyword = keyword_map.get(state["category"] or "", "")
        if keyword:
            for kw in keyword.split():
                result_json = runbook_tool.invoke({"action": "get", "query": kw})
                result = json.loads(result_json)
                for rb in result.get("runbooks", []):
                    if rb not in fetched:
                        fetched.append(rb)

    if fetched:
        runbook_context = {"runbooks": fetched}
        trace.append(f"runbook(get) → {len(fetched)} runbook(s) loaded")

    return {**state, "runbook_context": runbook_context, "tool_trace": trace}


# ── Node: topology context ────────────────────────────────────────────

def topology_node(state: AgentState) -> AgentState:
    """Enrich investigation with service dependency context."""
    trace = state["tool_trace"][:]
    topology_context: dict = {}

    # Map discovered metrics to owning services
    services_involved: set[str] = set()
    for metric in state["discovered_metrics"][:5]:
        # Strip PromQL functions to get bare metric name
        import re
        bare = re.findall(r"\b([a-z_][a-z0-9_]{4,})\b", metric)
        for name in bare:
            result_json = topology_tool.invoke({"action": "metric_owner", "metric_name": name})
            result = json.loads(result_json)
            owner = result.get("owner_service")
            if owner:
                services_involved.add(owner)

    # Get dependency info for each involved service
    service_details = []
    for svc in services_involved:
        result_json = topology_tool.invoke({"action": "dependencies", "service_name": svc})
        result = json.loads(result_json)
        if "service" in result:
            service_details.append(result)

    if service_details:
        topology_context = {
            "services_involved": list(services_involved),
            "dependencies": service_details,
        }
        trace.append(f"topology → {len(services_involved)} service(s) identified")

    return {**state, "topology_context": topology_context, "tool_trace": trace}


# ── Node: synthesise answer ───────────────────────────────────────────

_SYNTHESISE_PROMPT = """You are an expert SRE. Synthesize the investigation evidence below
into a clear, concise answer for the user. Include:
- Direct answer to the question
- Exact PromQL queries used (so the user can reproduce)
- Evidence summary (what the data shows)
- Any anomalies detected
- If runbooks are available, include the relevant diagnostic steps and remediation actions
- If topology context is available, mention which services are affected and their dependencies
- Recommended actions if issues are found

Investigation evidence:
Category: {category}
Discovered metrics: {metrics}
Queries run: {queries}
Anomalies: {anomalies}
Alert context: {alerts}
Runbook context: {runbooks}
Service topology: {topology}
Tool trace: {trace}

User question: {question}"""


def synthesise_node(state: AgentState) -> AgentState:
    structured = build_structured_result(
        category=state["category"] or "unknown",
        queries_run=state["queries_run"],
        anomalies_found=state["anomalies_found"],
        alert_context=state["alert_context"],
        discovered_metrics=state["discovered_metrics"],
        tool_trace=state["tool_trace"],
        llm=get_llm(),
    )

    prompt = _SYNTHESISE_PROMPT.format(
        category=state["category"],
        metrics=json.dumps(state["discovered_metrics"]),
        queries=json.dumps(state["queries_run"], default=str),
        anomalies=json.dumps(state["anomalies_found"], default=str),
        alerts=json.dumps(state["alert_context"], default=str),
        runbooks=json.dumps(state.get("runbook_context"), default=str),
        topology=json.dumps(state.get("topology_context"), default=str),
        trace=json.dumps(state["tool_trace"]),
        question=state["question"],
    )
    response = get_llm().invoke([HumanMessage(content=prompt)])
    answer = response.content

    messages = state["messages"] + [AIMessage(content=answer)]
    return {
        **state,
        "final_answer": answer,
        "structured_result": structured.model_dump(),
        "messages": messages,
    }


# ── Graph assembly ────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    g = StateGraph(AgentState)

    g.add_node("classify", classify_node)
    g.add_node("discovery", discovery_node)
    g.add_node("query", query_node)
    g.add_node("incident_pack", incident_pack_node)
    g.add_node("anomaly", anomaly_node)
    g.add_node("alert", alert_node)
    g.add_node("runbook", runbook_node)
    g.add_node("topology", topology_node)
    g.add_node("synthesise", synthesise_node)

    g.set_entry_point("classify")
    g.add_edge("classify", "discovery")
    g.add_edge("discovery", "query")
    g.add_edge("query", "incident_pack")
    g.add_edge("incident_pack", "anomaly")
    g.add_edge("anomaly", "alert")
    g.add_edge("alert", "runbook")
    g.add_edge("runbook", "topology")
    g.add_edge("topology", "synthesise")
    g.add_edge("synthesise", END)

    return g.compile()


_GRAPH = None


def get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH


def run_planner(
    user_message: str, chat_history: list | None = None
) -> tuple[str, list[str], dict | None]:
    """Run the multi-step planner. Returns (answer, tool_trace, structured_result)."""
    messages = []
    if chat_history:
        for role, content in chat_history:
            if role == "human":
                messages.append(HumanMessage(content=content))
            elif role == "ai":
                messages.append(AIMessage(content=content))
    messages.append(HumanMessage(content=user_message))

    initial_state: AgentState = {
        "messages": messages,
        "question": user_message,
        "category": None,
        "discovered_metrics": [],
        "queries_run": [],
        "anomalies_found": [],
        "alert_context": None,
        "incident_pack_results": [],
        "runbook_context": None,
        "topology_context": None,
        "tool_trace": [],
        "final_answer": None,
        "structured_result": None,
    }

    result = get_graph().invoke(initial_state)
    answer = result.get("final_answer") or "I was unable to generate a response."
    trace = result.get("tool_trace", [])
    structured = result.get("structured_result")
    return answer, trace, structured
