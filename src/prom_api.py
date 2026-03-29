"""
Shared Prometheus HTTP API client.
Centralises all HTTP calls to Prometheus so tools don't duplicate this logic.
"""

from datetime import datetime, timedelta, timezone

import requests

from src.config import PROMETHEUS_URL


def query_instant(promql: str) -> dict:
    """Execute an instant PromQL query and return the parsed JSON response."""
    resp = requests.get(
        f"{PROMETHEUS_URL}/api/v1/query",
        params={"query": promql},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def query_range(promql: str, start: str, end: str, step: str = "60s") -> dict:
    """Execute a range PromQL query and return the parsed JSON response."""
    resp = requests.get(
        f"{PROMETHEUS_URL}/api/v1/query_range",
        params={"query": promql, "start": start, "end": end, "step": step},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_range(promql: str, duration_minutes: int, step: str = "60s") -> list:
    """Fetch a time range of results for a PromQL expression.

    Args:
        promql: PromQL expression to evaluate.
        duration_minutes: How many minutes of history to fetch (ending now).
        step: Query resolution step, e.g. '60s'.

    Returns:
        List of result series dicts from the Prometheus range query.
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=duration_minutes)
    return (
        query_range(promql, start.isoformat(), end.isoformat(), step)
        .get("data", {})
        .get("result", [])
    )