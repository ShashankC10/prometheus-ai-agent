"""
Incident investigation packs — predefined multi-signal workflows for common
infrastructure incident types.

Each pack gathers multiple correlated Prometheus signals before handing them
to the synthesiser, producing a richer investigation than a single query.

Packs available:
- high_latency       : latency percentiles + request rate + error rate
- high_error_rate    : 5xx/4xx rates + error ratio + affected endpoints
- pod_instability    : container restarts + OOM kills + CPU throttling
- database_bottleneck: query duration + connection pool + slow queries
- resource_saturation: CPU + memory + disk + network across all instances
"""

import json

import requests
from langchain_core.tools import tool

from src import prom_api
from src.tools.promql_validator import validate_promql


PACK_DEFINITIONS = {
    "high_latency": {
        "description": "Investigates high response latency across services",
        "signals": [
            {
                "name": "p99_latency",
                "promql": 'histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))',
                "query_type": "range",
                "duration_minutes": 30,
            },
            {
                "name": "p95_latency",
                "promql": 'histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))',
                "query_type": "range",
                "duration_minutes": 30,
            },
            {
                "name": "request_rate",
                "promql": 'sum(rate(http_requests_total[5m]))',
                "query_type": "range",
                "duration_minutes": 30,
            },
            {
                "name": "error_rate",
                "promql": 'sum(rate(http_requests_total{status=~"5.."}[5m]))',
                "query_type": "instant",
                "duration_minutes": 5,
            },
        ],
    },
    "high_error_rate": {
        "description": "Investigates elevated HTTP error rates",
        "signals": [
            {
                "name": "5xx_rate",
                "promql": 'sum by (endpoint) (rate(http_requests_total{status=~"5.."}[5m]))',
                "query_type": "range",
                "duration_minutes": 30,
            },
            {
                "name": "4xx_rate",
                "promql": 'sum by (endpoint) (rate(http_requests_total{status=~"4.."}[5m]))',
                "query_type": "range",
                "duration_minutes": 30,
            },
            {
                "name": "error_ratio",
                "promql": (
                    'sum(rate(http_requests_total{status=~"5.."}[5m])) / '
                    'sum(rate(http_requests_total[5m]))'
                ),
                "query_type": "instant",
                "duration_minutes": 5,
            },
            {
                "name": "top_error_endpoints",
                "promql": 'topk(5, sum by (endpoint) (rate(http_requests_total{status=~"5.."}[5m])))',
                "query_type": "instant",
                "duration_minutes": 5,
            },
        ],
    },
    "resource_saturation": {
        "description": "Checks CPU, memory, and disk utilisation across all instances",
        "signals": [
            {
                "name": "cpu_usage_pct",
                "promql": (
                    '100 - (avg by(instance) '
                    '(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)'
                ),
                "query_type": "range",
                "duration_minutes": 60,
            },
            {
                "name": "memory_used_pct",
                "promql": (
                    '100 * (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes))'
                ),
                "query_type": "range",
                "duration_minutes": 60,
            },
            {
                "name": "disk_used_pct",
                "promql": (
                    '100 - (node_filesystem_avail_bytes{mountpoint="/"} / '
                    'node_filesystem_size_bytes{mountpoint="/"} * 100)'
                ),
                "query_type": "instant",
                "duration_minutes": 5,
            },
        ],
    },
    "pod_instability": {
        "description": "Investigates container/pod restarts, OOM kills, and throttling",
        "signals": [
            {
                "name": "container_restarts",
                "promql": 'sum by (container) (increase(kube_pod_container_status_restarts_total[30m]))',
                "query_type": "instant",
                "duration_minutes": 30,
            },
            {
                "name": "oom_kills",
                "promql": 'sum by (container) (kube_pod_container_status_last_terminated_reason{reason="OOMKilled"})',
                "query_type": "instant",
                "duration_minutes": 5,
            },
            {
                "name": "cpu_throttling",
                "promql": (
                    'sum by (container) (rate(container_cpu_cfs_throttled_periods_total[5m])) / '
                    'sum by (container) (rate(container_cpu_cfs_periods_total[5m]))'
                ),
                "query_type": "range",
                "duration_minutes": 30,
            },
        ],
    },
    "database_bottleneck": {
        "description": "Investigates database query latency and connection saturation",
        "signals": [
            {
                "name": "query_duration_p99",
                "promql": 'histogram_quantile(0.99, rate(mysql_query_duration_seconds_bucket[5m]))',
                "query_type": "range",
                "duration_minutes": 30,
            },
            {
                "name": "connections_used",
                "promql": 'mysql_global_status_threads_connected',
                "query_type": "range",
                "duration_minutes": 30,
            },
            {
                "name": "slow_queries",
                "promql": 'rate(mysql_global_status_slow_queries[5m])',
                "query_type": "range",
                "duration_minutes": 30,
            },
        ],
    },
}


def _run_signal(signal: dict) -> dict:
    """Execute one signal query and return structured result."""
    promql = signal["promql"]
    validation = validate_promql(promql)

    if not validation["valid"]:
        return {
            "name": signal["name"],
            "promql": promql,
            "status": "invalid",
            "error": validation["error_message"],
            "result": None,
        }

    try:
        if signal["query_type"] == "range":
            result = prom_api.fetch_range(
                promql,
                signal.get("duration_minutes", 30),
                "60s",
            )
        else:
            raw = prom_api.query_instant(promql)
            result = raw.get("data", {}).get("result", [])

        return {
            "name": signal["name"],
            "promql": promql,
            "status": "success",
            "error": None,
            "result": result[:10],  # cap for context
        }
    except Exception as e:
        return {
            "name": signal["name"],
            "promql": promql,
            "status": "error",
            "error": str(e),
            "result": None,
        }


@tool
def incident_pack_tool(pack_name: str) -> str:
    """Run a predefined multi-signal incident investigation pack.

    Packs gather multiple correlated signals in one call, providing richer
    evidence than individual queries. Use these when investigating a specific
    incident type.

    Available packs:
    - high_latency       : latency percentiles + request rate + error rate
    - high_error_rate    : 5xx/4xx rates + error ratio + top affected endpoints
    - resource_saturation: CPU + memory + disk across all instances
    - pod_instability    : container restarts + OOM kills + CPU throttling
    - database_bottleneck: query duration + connection pool + slow queries

    Args:
        pack_name: One of the pack names listed above.

    Returns:
        JSON with each signal's query result, validation status, and a summary
        of which signals succeeded and what data was gathered.
    """
    if pack_name not in PACK_DEFINITIONS:
        available = list(PACK_DEFINITIONS.keys())
        return json.dumps({"error": f"Unknown pack '{pack_name}'. Available: {available}"})

    pack = PACK_DEFINITIONS[pack_name]
    signal_results = [_run_signal(s) for s in pack["signals"]]

    succeeded = sum(1 for s in signal_results if s["status"] == "success")
    failed = len(signal_results) - succeeded

    return json.dumps(
        {
            "pack": pack_name,
            "description": pack["description"],
            "signals_total": len(signal_results),
            "signals_succeeded": succeeded,
            "signals_failed": failed,
            "results": signal_results,
        },
        indent=2,
        default=str,
    )
