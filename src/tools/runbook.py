"""
Tool that loads operational runbooks and alert-rule context so the agent
can ground its answers in predefined diagnostic procedures.

This makes the agent's recommendations operationally useful rather than
generic — each answer maps to the team's established response playbook.
"""

import json
import os
from pathlib import Path

import yaml
from langchain_core.tools import tool

RUNBOOKS_PATH = os.getenv("RUNBOOKS_PATH", "runbooks/runbooks.yml")


def _load_runbooks() -> list[dict]:
    path = Path(RUNBOOKS_PATH)
    if not path.exists():
        return []
    with open(path) as f:
        data = yaml.safe_load(f)
    return data.get("runbooks", [])


def _match_runbook(runbooks: list[dict], query: str) -> list[dict]:
    """Return runbooks whose alert name or title matches the query (case-insensitive)."""
    q = query.lower()
    matched = [
        rb for rb in runbooks
        if q in rb.get("alert", "").lower()
        or q in rb.get("title", "").lower()
        or any(q in cause.lower() for cause in rb.get("likely_causes", []))
        or any(q in m.lower() for m in rb.get("relevant_metrics", []))
    ]
    return matched


@tool
def runbook_tool(action: str, query: str = "") -> str:
    """Access operational runbooks for alert investigation and remediation guidance.

    Use this tool when:
    - An alert is firing and you need the diagnostic steps for it
    - The user asks what to do about a specific issue (high CPU, error rate, etc.)
    - You want to enrich your answer with operationally-grounded remediation steps

    Args:
        action: One of:
            - 'list': List all available runbooks (alert names and titles).
            - 'get': Get the full runbook for a specific alert or issue.
                     Set `query` to the alert name (e.g. 'HighCpuUsage') or
                     issue keyword (e.g. 'latency', 'memory', 'error rate').
            - 'relevant_metrics': Return the metrics relevant to a given issue type.
        query: Alert name or keyword for 'get' and 'relevant_metrics' actions.

    Returns:
        JSON with the matching runbook(s) including diagnostic steps, likely
        causes, relevant metrics, and remediation actions.
    """
    try:
        runbooks = _load_runbooks()

        if not runbooks:
            return json.dumps({"error": f"No runbooks found at {RUNBOOKS_PATH}"})

        if action == "list":
            summary = [
                {
                    "alert": rb.get("alert"),
                    "title": rb.get("title"),
                    "severity": rb.get("severity"),
                    "threshold": rb.get("threshold"),
                }
                for rb in runbooks
            ]
            return json.dumps({"runbooks": summary}, indent=2)

        elif action == "get":
            if not query:
                return json.dumps({"error": "'query' is required for action='get'"})
            matched = _match_runbook(runbooks, query)
            if not matched:
                available = [rb.get("alert") for rb in runbooks]
                return json.dumps({
                    "error": f"No runbook found for '{query}'",
                    "available_alerts": available,
                })
            return json.dumps({"runbooks": matched}, indent=2)

        elif action == "relevant_metrics":
            if not query:
                return json.dumps({"error": "'query' is required for action='relevant_metrics'"})
            matched = _match_runbook(runbooks, query)
            metrics: set[str] = set()
            for rb in matched:
                metrics.update(rb.get("relevant_metrics", []))
            return json.dumps({
                "query": query,
                "relevant_metrics": sorted(metrics),
                "from_runbooks": [rb.get("alert") for rb in matched],
            }, indent=2)

        else:
            return json.dumps({"error": f"Unknown action '{action}'. Use 'list', 'get', or 'relevant_metrics'."})

    except Exception as e:
        return json.dumps({"error": str(e)})
