"""
Tool that discovers available metrics, labels, and targets
from the Prometheus API. Useful for the agent to understand
what data is available before writing queries.
"""

import json
import requests
from langchain_core.tools import tool

from src.config import PROMETHEUS_URL


@tool
def metric_explorer_tool(action: str, metric_name: str = "") -> str:
    """Explore available Prometheus metrics, labels, and scrape targets.

    Use this tool to discover what metrics exist, what labels they have,
    and which targets Prometheus is scraping. Call this before writing
    PromQL queries to understand the available data.

    Args:
        action: One of:
            - 'list_metrics': List all available metric names.
            - 'metric_info': Get metadata (type, help text) for a specific metric.
            - 'label_values': Get all label names and values for a specific metric.
            - 'targets': List all scrape targets and their health status.
        metric_name: Required for 'metric_info' and 'label_values' actions.

    Returns:
        JSON string with the requested information.
    """
    try:
        if action == "list_metrics":
            resp = requests.get(f"{PROMETHEUS_URL}/api/v1/label/__name__/values", timeout=10)
            resp.raise_for_status()
            metrics = resp.json().get("data", [])
            # Filter out internal go/prometheus metrics for cleaner output
            app_metrics = [
                m for m in metrics
                if not m.startswith(("go_", "promhttp_", "prometheus_"))
            ]
            return json.dumps({
                "total_metrics": len(metrics),
                "application_metrics": app_metrics,
                "internal_metrics_hidden": len(metrics) - len(app_metrics),
            }, indent=2)

        elif action == "metric_info":
            if not metric_name:
                return json.dumps({"error": "metric_name is required for 'metric_info'"})
            resp = requests.get(
                f"{PROMETHEUS_URL}/api/v1/metadata",
                params={"metric": metric_name},
                timeout=10,
            )
            resp.raise_for_status()
            metadata = resp.json().get("data", {}).get(metric_name, [])
            return json.dumps({
                "metric": metric_name,
                "metadata": metadata,
            }, indent=2)

        elif action == "label_values":
            if not metric_name:
                return json.dumps({"error": "metric_name is required for 'label_values'"})
            # Get series for this metric to extract labels
            resp = requests.get(
                f"{PROMETHEUS_URL}/api/v1/series",
                params={"match[]": metric_name},
                timeout=10,
            )
            resp.raise_for_status()
            series = resp.json().get("data", [])
            # Aggregate unique label keys and their values
            label_map = {}
            for s in series:
                for k, v in s.items():
                    if k == "__name__":
                        continue
                    label_map.setdefault(k, set()).add(v)
            label_info = {k: sorted(list(v)) for k, v in label_map.items()}
            return json.dumps({
                "metric": metric_name,
                "series_count": len(series),
                "labels": label_info,
            }, indent=2)

        elif action == "targets":
            resp = requests.get(f"{PROMETHEUS_URL}/api/v1/targets", timeout=10)
            resp.raise_for_status()
            active = resp.json().get("data", {}).get("activeTargets", [])
            targets = []
            for t in active:
                targets.append({
                    "job": t.get("labels", {}).get("job"),
                    "instance": t.get("labels", {}).get("instance"),
                    "health": t.get("health"),
                    "last_scrape": t.get("lastScrape"),
                    "scrape_duration": t.get("lastScrapeDuration"),
                })
            return json.dumps({"targets": targets}, indent=2)

        else:
            return json.dumps({"error": f"Unknown action '{action}'. Use list_metrics, metric_info, label_values, or targets."})

    except requests.exceptions.ConnectionError:
        return json.dumps({"error": "Cannot connect to Prometheus. Is it running?"})
    except Exception as e:
        return json.dumps({"error": str(e)})
