"""
Tool that fetches a metric range from Prometheus and performs
multi-method anomaly detection on the time series.

Detection methods (applied in order):
1. Rolling-window MAD (Median Absolute Deviation) — robust to outliers,
   better than global z-score for non-stationary metrics.
2. Global z-score — retained as a secondary signal for comparison.
3. Sustained degradation — detects step-changes and persistent regressions
   by comparing rolling window means.
4. Change-point detection — identifies sudden level shifts in the series.

Anomaly types classified:
- spike        : single transient high value
- dip          : single transient low value
- sustained_high  : consecutive above-baseline values
- sustained_low   : consecutive below-baseline values
- step_change  : abrupt level shift detected by change-point analysis
"""

import json
from datetime import datetime, timezone

import numpy as np
import requests
from langchain_core.tools import tool

from src import prom_api


# ── Core detection functions ──────────────────────────────────────────

def _rolling_mad_anomalies(
    arr: np.ndarray,
    timestamps: list[float],
    window: int,
    threshold: float,
) -> list[dict]:
    """Detect anomalies using a rolling-window MAD baseline."""
    anomalies = []
    for i in range(window, len(arr)):
        window_slice = arr[i - window: i]
        median = float(np.median(window_slice))
        mad = float(np.median(np.abs(window_slice - median)))
        # MAD-based modified z-score (Iglewicz & Hoaglin 1993)
        # Constant 0.6745 normalises MAD to std-dev equivalent
        if mad == 0:
            continue
        modified_z = 0.6745 * (arr[i] - median) / mad
        if abs(modified_z) > threshold:
            anomalies.append({
                "timestamp": datetime.fromtimestamp(
                    timestamps[i], tz=timezone.utc
                ).isoformat(),
                "value": round(float(arr[i]), 6),
                "modified_z_score": round(float(modified_z), 2),
                "baseline_median": round(median, 6),
                "direction": "spike" if modified_z > 0 else "dip",
                "method": "rolling_mad",
            })
    return anomalies


def _global_zscore_anomalies(
    arr: np.ndarray,
    timestamps: list[float],
    mean: float,
    std: float,
    threshold: float,
) -> list[dict]:
    """Detect anomalies using the global z-score (baseline method)."""
    anomalies = []
    z_scores = (arr - mean) / std
    for i, z in enumerate(z_scores):
        if abs(z) > threshold:
            anomalies.append({
                "timestamp": datetime.fromtimestamp(
                    timestamps[i], tz=timezone.utc
                ).isoformat(),
                "value": round(float(arr[i]), 6),
                "z_score": round(float(z), 2),
                "direction": "spike" if z > 0 else "dip",
                "method": "global_zscore",
            })
    return anomalies


def _classify_sustained(arr: np.ndarray, window: int, threshold_pct: float) -> dict | None:
    """
    Detect if the last `window` points are consistently above or below the
    first-half baseline by more than `threshold_pct` percent.
    Returns a classification dict or None.
    """
    if len(arr) < window * 2:
        return None
    baseline = float(np.median(arr[: len(arr) // 2]))
    recent = float(np.median(arr[-window:]))
    if baseline == 0:
        return None
    change_pct = (recent - baseline) / abs(baseline) * 100
    if change_pct > threshold_pct:
        return {"type": "sustained_high", "change_percent": round(change_pct, 2)}
    if change_pct < -threshold_pct:
        return {"type": "sustained_low", "change_percent": round(change_pct, 2)}
    return None


def _detect_change_point(arr: np.ndarray) -> dict | None:
    """
    Simple CUSUM-based change-point detection.
    Returns the index and magnitude of the most significant level shift, or None.
    """
    if len(arr) < 10:
        return None
    best_score = 0.0
    best_idx = None
    global_mean = float(np.mean(arr))
    for i in range(3, len(arr) - 3):
        left_mean = float(np.mean(arr[:i]))
        right_mean = float(np.mean(arr[i:]))
        score = abs(right_mean - left_mean)
        if score > best_score:
            best_score = score
            best_idx = i
    if best_idx is None:
        return None
    # Only flag if the shift is > 20% of the global mean
    if global_mean == 0 or (best_score / abs(global_mean)) < 0.20:
        return None
    return {
        "index": best_idx,
        "magnitude": round(best_score, 6),
        "left_mean": round(float(np.mean(arr[:best_idx])), 6),
        "right_mean": round(float(np.mean(arr[best_idx:])), 6),
    }


def _trend(arr: np.ndarray) -> tuple[str, float]:
    """Compare first third vs last third to determine trend direction."""
    third = max(len(arr) // 3, 1)
    first_avg = float(np.mean(arr[:third]))
    last_avg = float(np.mean(arr[-third:]))
    change_pct = ((last_avg - first_avg) / first_avg * 100) if first_avg != 0 else 0.0
    if change_pct > 10:
        return "increasing", round(change_pct, 2)
    if change_pct < -10:
        return "decreasing", round(change_pct, 2)
    return "stable", round(change_pct, 2)


def _deduplicate_anomalies(primary: list[dict], secondary: list[dict]) -> list[dict]:
    """Return primary list, adding secondary entries not already covered by timestamp."""
    primary_ts = {a["timestamp"] for a in primary}
    extras = [a for a in secondary if a["timestamp"] not in primary_ts]
    return primary + extras


# ── Tool ──────────────────────────────────────────────────────────────

@tool
def anomaly_detection_tool(
    promql: str,
    duration_minutes: int = 60,
    z_threshold: float = 2.0,
    step: str = "60s",
) -> str:
    """Analyze a Prometheus metric for anomalies using multi-method statistical detection.

    Applies rolling-window MAD (robust baseline), global z-score (comparison),
    sustained degradation detection, and change-point analysis. Each anomaly is
    classified by type: spike, dip, sustained_high, sustained_low, or step_change.

    Use this tool when asked to detect spikes, anomalies, or unusual behavior.

    Args:
        promql: PromQL expression returning a time series.
            Example: 'rate(http_requests_total{status=~\"5..\"}[5m])'
        duration_minutes: How many minutes of history to analyze. Default 60.
        z_threshold: Detection sensitivity threshold (lower = more sensitive). Default 2.0.
        step: Query resolution step. Default '60s'.

    Returns:
        JSON string with statistics, multi-method anomaly results, trend, and
        change-point analysis.
    """
    try:
        results = prom_api.fetch_range(promql, duration_minutes, step)

        if not results:
            return json.dumps({"error": "No data returned for the given query."})

        window = max(5, min(20, len(results[0].get("values", [])) // 4)) if results else 10

        analysis = []
        for series in results:
            metric_labels = series.get("metric", {})
            values = series.get("values", [])

            if len(values) < 3:
                analysis.append({
                    "metric": metric_labels,
                    "error": "Not enough data points for analysis",
                })
                continue

            timestamps = [float(v[0]) for v in values]
            data_points = [float(v[1]) for v in values]
            arr = np.array(data_points)

            mean = float(np.mean(arr))
            std = float(np.std(arr))
            minimum = float(np.min(arr))
            maximum = float(np.max(arr))
            median = float(np.median(arr))

            if std == 0:
                analysis.append({
                    "metric": metric_labels,
                    "data_points": len(data_points),
                    "statistics": {"mean": round(mean, 6), "std_dev": 0.0,
                                   "min": round(minimum, 6), "max": round(maximum, 6),
                                   "median": round(median, 6)},
                    "trend": "stable",
                    "change_percent": 0.0,
                    "anomaly_count": 0,
                    "anomalies": [],
                    "sustained": None,
                    "change_point": None,
                    "note": "Metric is constant — no anomalies possible.",
                })
                continue

            # Rolling MAD (primary)
            mad_anomalies = _rolling_mad_anomalies(arr, timestamps, window, z_threshold)
            # Global z-score (secondary, for comparison)
            zscore_anomalies = _global_zscore_anomalies(arr, timestamps, mean, std, z_threshold)
            # Merge, keeping primary MAD results dominant
            all_anomalies = _deduplicate_anomalies(mad_anomalies, zscore_anomalies)

            trend_dir, change_pct = _trend(arr)
            sustained = _classify_sustained(arr, window=window, threshold_pct=15.0)
            change_point = _detect_change_point(arr)

            # If change_point detected, add a synthetic anomaly entry
            if change_point:
                cp_idx = change_point["index"]
                if 0 <= cp_idx < len(timestamps):
                    all_anomalies.append({
                        "timestamp": datetime.fromtimestamp(
                            timestamps[cp_idx], tz=timezone.utc
                        ).isoformat(),
                        "value": round(float(arr[cp_idx]), 6),
                        "direction": "step_change",
                        "method": "change_point",
                        "magnitude": change_point["magnitude"],
                    })

            analysis.append({
                "metric": metric_labels,
                "data_points": len(data_points),
                "statistics": {
                    "mean": round(mean, 6),
                    "std_dev": round(std, 6),
                    "median": round(median, 6),
                    "min": round(minimum, 6),
                    "max": round(maximum, 6),
                },
                "trend": trend_dir,
                "change_percent": change_pct,
                "anomaly_count": len(all_anomalies),
                "anomalies": all_anomalies[:20],
                "sustained": sustained,
                "change_point": change_point,
            })

        return json.dumps({"analysis": analysis}, indent=2, default=str)

    except requests.exceptions.ConnectionError:
        return json.dumps({"error": "Cannot connect to Prometheus. Is it running?"})
    except Exception as e:
        return json.dumps({"error": str(e)})
