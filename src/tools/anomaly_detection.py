"""
Tool that fetches a metric range from Prometheus and performs
statistical anomaly detection (z-score based) on the time series.
"""

import json
from datetime import datetime, timezone

import numpy as np
import requests
from langchain_core.tools import tool

from src import prom_api


@tool
def anomaly_detection_tool(
    promql: str,
    duration_minutes: int = 60,
    z_threshold: float = 2.0,
    step: str = "60s",
) -> str:
    """Analyze a Prometheus metric for anomalies using statistical methods.

    Fetches a time range of data for the given PromQL expression and
    identifies data points that deviate significantly from the mean
    (z-score analysis). Also computes basic statistics and trend direction.

    Use this tool when asked to detect spikes, anomalies, or unusual
    behavior in any metric.

    Args:
        promql: PromQL expression returning a time series.
            Example: 'rate(http_requests_total{status=~\"5..\"}[5m])'
        duration_minutes: How many minutes of history to analyze. Default 60.
        z_threshold: Z-score threshold for flagging anomalies. Default 2.0.
        step: Query resolution step. Default '60s'.

    Returns:
        JSON string with statistics, anomalies, and trend analysis.
    """
    try:
        results = prom_api.fetch_range(promql, duration_minutes, step)

        if not results:
            return json.dumps({"error": "No data returned for the given query."})

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

            # Z-score anomaly detection
            if std == 0:
                analysis.append({
                    "metric": metric_labels,
                    "data_points": len(data_points),
                    "statistics": {
                        "mean": round(mean, 6),
                        "std_dev": 0.0,
                        "min": round(minimum, 6),
                        "max": round(maximum, 6),
                    },
                    "trend": "stable",
                    "change_percent": 0.0,
                    "anomaly_count": 0,
                    "anomalies": [],
                    "note": "Metric is constant — no anomalies possible.",
                })
                continue

            z_scores = (arr - mean) / std
            anomalies = []
            for i, z in enumerate(z_scores):
                if abs(z) > z_threshold:
                    anomalies.append({
                        "timestamp": datetime.fromtimestamp(
                            timestamps[i], tz=timezone.utc
                        ).isoformat(),
                        "value": data_points[i],
                        "z_score": round(float(z), 2),
                        "direction": "spike" if z > 0 else "dip",
                    })

            # Simple trend: compare first third vs last third
            third = max(len(data_points) // 3, 1)
            first_avg = float(np.mean(arr[:third]))
            last_avg = float(np.mean(arr[-third:]))
            change_pct = ((last_avg - first_avg) / first_avg * 100) if first_avg != 0 else 0.0

            if change_pct > 10:
                trend = "increasing"
            elif change_pct < -10:
                trend = "decreasing"
            else:
                trend = "stable"

            analysis.append({
                "metric": metric_labels,
                "data_points": len(data_points),
                "statistics": {
                    "mean": round(mean, 6),
                    "std_dev": round(std, 6),
                    "min": round(minimum, 6),
                    "max": round(maximum, 6),
                },
                "trend": trend,
                "change_percent": round(change_pct, 2),
                "anomaly_count": len(anomalies),
                "anomalies": anomalies[:20],  # cap for context size
            })

        return json.dumps({"analysis": analysis}, indent=2, default=str)

    except requests.exceptions.ConnectionError:
        return json.dumps({"error": "Cannot connect to Prometheus. Is it running?"})
    except Exception as e:
        return json.dumps({"error": str(e)})