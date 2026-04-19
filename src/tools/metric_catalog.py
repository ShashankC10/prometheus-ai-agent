"""
Tool that builds a live metric catalog from Prometheus metadata.
Used to ground PromQL generation in discovered metric names and labels,
preventing the agent from hallucinating metric names that don't exist.
"""

import json
from difflib import SequenceMatcher

import requests
from langchain_core.tools import tool

from src.config import PROMETHEUS_URL


def _all_metric_names() -> list[str]:
    resp = requests.get(
        f"{PROMETHEUS_URL}/api/v1/label/__name__/values", timeout=10
    )
    resp.raise_for_status()
    return resp.json().get("data", [])


def _metric_labels(metric_name: str) -> dict:
    resp = requests.get(
        f"{PROMETHEUS_URL}/api/v1/series",
        params={"match[]": metric_name},
        timeout=10,
    )
    resp.raise_for_status()
    series = resp.json().get("data", [])
    label_map: dict[str, set] = {}
    for s in series:
        for k, v in s.items():
            if k == "__name__":
                continue
            label_map.setdefault(k, set()).add(v)
    return {k: sorted(v) for k, v in label_map.items()}


def _score(metric: str, keywords: list[str]) -> float:
    """Return a relevance score for a metric name against a list of keywords."""
    metric_lower = metric.lower()
    score = 0.0
    for kw in keywords:
        kw_lower = kw.lower()
        if kw_lower in metric_lower:
            score += 1.0
        else:
            score += SequenceMatcher(None, kw_lower, metric_lower).ratio() * 0.3
    return score


@tool
def metric_catalog_tool(keywords: str, include_labels: bool = False) -> str:
    """Search the live Prometheus metric catalog for metrics relevant to a question.

    Call this BEFORE writing any PromQL to discover real metric names and
    label keys. This prevents hallucinated metric names.

    Args:
        keywords: Space-separated keywords describing the metric you need.
            Examples: 'http request rate', 'cpu usage', 'memory', 'error 5xx'
        include_labels: If True, also fetch label keys and example values for
            the top matches. Slower but gives full context for query building.

    Returns:
        JSON with ranked candidate metrics and, optionally, their labels.
    """
    try:
        all_metrics = _all_metric_names()
        kw_list = [k for k in keywords.split() if k]

        scored = sorted(
            ((m, _score(m, kw_list)) for m in all_metrics),
            key=lambda x: x[1],
            reverse=True,
        )

        # Keep top 20 with score > 0
        top = [(m, s) for m, s in scored if s > 0][:20]

        candidates = []
        for metric, score in top:
            entry: dict = {"metric": metric, "relevance_score": round(score, 2)}
            if include_labels:
                try:
                    entry["labels"] = _metric_labels(metric)
                except Exception:
                    entry["labels"] = {}
            candidates.append(entry)

        return json.dumps(
            {
                "keywords": kw_list,
                "total_metrics_searched": len(all_metrics),
                "candidates": candidates,
            },
            indent=2,
        )

    except requests.exceptions.ConnectionError:
        return json.dumps({"error": "Cannot connect to Prometheus. Is it running?"})
    except Exception as e:
        return json.dumps({"error": str(e)})
