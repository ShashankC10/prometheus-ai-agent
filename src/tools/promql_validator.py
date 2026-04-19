"""
PromQL validation and safe-query enforcement.

Validates a PromQL expression against Prometheus before full execution,
classifies failures, and enforces safety limits on range/step parameters.
"""

import json
import re

import requests
from langchain_core.tools import tool

from src.config import PROMETHEUS_URL

# Safety caps
MAX_RANGE_MINUTES = 1440  # 24 hours
MAX_STEP_SECONDS = 3600   # 1 hour minimum resolution
MIN_STEP_SECONDS = 10     # prevent sub-10s steps that hammer Prometheus
QUERY_TIMEOUT_SECONDS = 30


def _classify_error(error_msg: str) -> str:
    msg = error_msg.lower()
    if "parse error" in msg or "syntax error" in msg or "unexpected" in msg:
        return "syntax_error"
    if "unknown metric" in msg or "undefined" in msg:
        return "unknown_metric"
    if "invalid label" in msg or "label" in msg:
        return "invalid_label"
    if "timeout" in msg or "context deadline" in msg:
        return "timeout"
    if "bad_data" in msg:
        return "bad_data"
    return "unknown_error"


def _parse_step_seconds(step: str) -> int:
    """Convert a step string like '60s', '5m', '1h' to seconds."""
    match = re.fullmatch(r"(\d+)(s|m|h|d)?", step.strip())
    if not match:
        return 60
    value, unit = int(match.group(1)), (match.group(2) or "s")
    return value * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


def validate_promql(promql: str) -> dict:
    """
    Dry-run a PromQL expression using Prometheus's instant query endpoint.
    Returns a dict with keys: valid (bool), error_type, error_message, result_type.
    """
    try:
        resp = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": promql, "timeout": f"{QUERY_TIMEOUT_SECONDS}s"},
            timeout=QUERY_TIMEOUT_SECONDS + 5,
        )
        body = resp.json()

        if body.get("status") == "success":
            result = body.get("data", {})
            results = result.get("result", [])
            return {
                "valid": True,
                "error_type": None,
                "error_message": None,
                "result_type": result.get("resultType"),
                "empty_result": len(results) == 0,
            }
        else:
            error_msg = body.get("error", "unknown error")
            return {
                "valid": False,
                "error_type": _classify_error(error_msg),
                "error_message": error_msg,
                "result_type": None,
                "empty_result": None,
            }
    except requests.exceptions.ConnectionError:
        return {
            "valid": False,
            "error_type": "connection_error",
            "error_message": "Cannot connect to Prometheus.",
            "result_type": None,
            "empty_result": None,
        }
    except Exception as e:
        return {
            "valid": False,
            "error_type": "unknown_error",
            "error_message": str(e),
            "result_type": None,
            "empty_result": None,
        }


def enforce_safe_params(
    duration_minutes: int, step: str
) -> tuple[int, str, list[str]]:
    """
    Clamp duration and step to safe values.
    Returns (safe_duration_minutes, safe_step, warnings).
    """
    warnings = []
    safe_duration = duration_minutes
    safe_step = step

    if duration_minutes > MAX_RANGE_MINUTES:
        safe_duration = MAX_RANGE_MINUTES
        warnings.append(
            f"duration capped from {duration_minutes}m to {MAX_RANGE_MINUTES}m"
        )

    step_secs = _parse_step_seconds(step)
    if step_secs < MIN_STEP_SECONDS:
        safe_step = f"{MIN_STEP_SECONDS}s"
        warnings.append(f"step raised from {step} to {safe_step} (minimum)")
    elif step_secs > MAX_STEP_SECONDS:
        safe_step = f"{MAX_STEP_SECONDS}s"
        warnings.append(f"step lowered from {step} to {safe_step} (maximum)")

    return safe_duration, safe_step, warnings


@tool
def promql_validator_tool(promql: str, duration_minutes: int = 60, step: str = "60s") -> str:
    """Validate a PromQL expression and check query parameter safety before running it.

    Use this tool BEFORE executing a PromQL query when you are not confident
    the expression is correct. It performs a dry-run against Prometheus and
    classifies any errors so you can fix them.

    Error types returned:
    - syntax_error: PromQL parse/syntax issue — fix the expression
    - unknown_metric: Metric name not found — use metric_catalog_tool to find real names
    - invalid_label: Label name or value issue — check label_values via metric_catalog_tool
    - timeout: Query too expensive — increase step or reduce duration
    - empty_result: Query is valid but returns no data — metric may have no recent values
    - connection_error: Prometheus is unreachable

    Args:
        promql: The PromQL expression to validate.
        duration_minutes: Intended range duration — checked against safety limits.
        step: Intended step resolution — checked against safety limits.

    Returns:
        JSON with validation result, error classification, and any safety warnings.
    """
    validation = validate_promql(promql)
    safe_duration, safe_step, param_warnings = enforce_safe_params(duration_minutes, step)

    return json.dumps(
        {
            "promql": promql,
            "validation": validation,
            "safe_params": {
                "duration_minutes": safe_duration,
                "step": safe_step,
                "warnings": param_warnings,
            },
        },
        indent=2,
    )