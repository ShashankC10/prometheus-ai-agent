"""
Tool that reads Prometheus alerting rules from the rules file
and from the Prometheus API, returning structured information
the agent can use to explain alerts in plain language.
"""

import json
import requests
import yaml
from langchain_core.tools import tool

from src.config import PROMETHEUS_URL, ALERT_RULES_PATH


@tool
def alert_rules_tool(action: str = "list") -> str:
    """Read and explain Prometheus alerting rules and current alert status.

    Use this tool to understand what alerts are configured, what
    conditions trigger them, and whether any alerts are currently firing.

    Args:
        action: One of:
            - 'list': List all configured alerting rules with their
              expressions, thresholds, and annotations.
            - 'firing': Show currently firing or pending alerts from
              the Prometheus API.

    Returns:
        JSON string with alert rule details or current alert status.
    """
    try:
        if action == "list":
            try:
                with open(ALERT_RULES_PATH, "r") as f:
                    rules_config = yaml.safe_load(f)
            except FileNotFoundError:
                return json.dumps({"error": f"Alert rules file not found at {ALERT_RULES_PATH}"})

            rules_output = []
            for group in rules_config.get("groups", []):
                group_name = group.get("name", "unknown")
                for rule in group.get("rules", []):
                    rules_output.append({
                        "group": group_name,
                        "alert_name": rule.get("alert"),
                        "expression": rule.get("expr"),
                        "for_duration": rule.get("for", "0s"),
                        "severity": rule.get("labels", {}).get("severity", "unknown"),
                        "summary": rule.get("annotations", {}).get("summary", ""),
                        "description": rule.get("annotations", {}).get("description", ""),
                    })

            return json.dumps({"rules": rules_output}, indent=2)

        elif action == "firing":
            resp = requests.get(f"{PROMETHEUS_URL}/api/v1/alerts", timeout=10)
            resp.raise_for_status()
            alerts = resp.json().get("data", {}).get("alerts", [])

            alert_list = []
            for a in alerts:
                alert_list.append({
                    "alert_name": a.get("labels", {}).get("alertname"),
                    "state": a.get("state"),
                    "severity": a.get("labels", {}).get("severity"),
                    "instance": a.get("labels", {}).get("instance", ""),
                    "summary": a.get("annotations", {}).get("summary", ""),
                    "description": a.get("annotations", {}).get("description", ""),
                    "active_since": a.get("activeAt", ""),
                })

            return json.dumps({
                "total_alerts": len(alert_list),
                "firing": [a for a in alert_list if a["state"] == "firing"],
                "pending": [a for a in alert_list if a["state"] == "pending"],
            }, indent=2)

        else:
            return json.dumps({"error": f"Unknown action '{action}'. Use 'list' or 'firing'."})

    except requests.exceptions.ConnectionError:
        return json.dumps({"error": "Cannot connect to Prometheus. Is it running?"})
    except Exception as e:
        return json.dumps({"error": str(e)})
