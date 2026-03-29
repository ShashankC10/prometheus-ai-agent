"""
Tool that executes PromQL queries against the Prometheus HTTP API.
Supports both instant and range queries.
"""

import json

import requests
from langchain_core.tools import tool

from src import prom_api


@tool
def promql_query_tool(
    promql: str,
    query_type: str = "instant",
    duration_minutes: int = 60,
    step: str = "60s",
) -> str:
    """Execute a PromQL query against Prometheus and return the results.

    Use this tool to fetch metrics data. You can run instant queries for
    current values or range queries for historical data.

    Args:
        promql: The PromQL expression to evaluate.
            Examples:
            - 'up' (check which targets are up)
            - 'rate(http_requests_total[5m])' (request rate)
            - 'histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))' (p95 latency)
            - '100 - (avg by(instance)(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)' (CPU %)
        query_type: 'instant' for current value, 'range' for time series data.
        duration_minutes: For range queries, how many minutes of history to fetch. Default 60.
        step: For range queries, the resolution step. Default '60s'.

    Returns:
        JSON string with query results.
    """
    try:
        if query_type == "range":
            data = prom_api.query_range(
                promql,
                *_range_bounds(duration_minutes),
                step,
            )
        else:
            data = prom_api.query_instant(promql)

        result = data.get("data", {})
        result_type = result.get("resultType", "unknown")
        results = result.get("result", [])

        # Truncate very large result sets to keep context manageable
        truncated = len(results) > 50
        if truncated:
            results = results[:50]

        output = {
            "status": data.get("status"),
            "result_type": result_type,
            "result_count": len(results),
            "truncated": truncated,
            "results": results,
        }
        return json.dumps(output, indent=2, default=str)

    except requests.exceptions.ConnectionError:
        return json.dumps({"error": "Cannot connect to Prometheus. Is it running?"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def _range_bounds(duration_minutes: int) -> tuple[str, str]:
    """Return (start, end) ISO-8601 strings for a range ending now."""
    from datetime import datetime, timedelta, timezone
    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=duration_minutes)
    return start.isoformat(), end.isoformat()
