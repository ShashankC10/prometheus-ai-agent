"""
Fake application that exposes Prometheus metrics simulating a web service.
Generates realistic HTTP request metrics with occasional anomaly spikes
for the AI agent to detect and analyze.
"""

import random
import threading
import time

from flask import Flask, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

app = Flask(__name__)

# ── Metrics ──────────────────────────────────────────────────────────
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

active_connections = Gauge(
    "active_connections",
    "Number of active connections",
)

db_query_duration_seconds = Histogram(
    "db_query_duration_seconds",
    "Database query duration in seconds",
    ["query_type"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
)

queue_depth = Gauge(
    "task_queue_depth",
    "Number of tasks in the processing queue",
)

# ── Simulation ───────────────────────────────────────────────────────
ENDPOINTS = ["/api/users", "/api/orders", "/api/products", "/api/search", "/api/health"]
METHODS = ["GET", "POST"]


class _AnomalyState:
    """Thread-safe holder for the current anomaly simulation state."""

    def __init__(self):
        self._lock = threading.Lock()
        self._active = False
        self._anomaly_type: str | None = None

    def read(self) -> tuple[bool, str | None]:
        with self._lock:
            return self._active, self._anomaly_type

    def toggle(self, new_type: str) -> None:
        with self._lock:
            self._active = not self._active
            self._anomaly_type = new_type


_state = _AnomalyState()


def simulate_traffic() -> None:
    """Background thread that generates fake metric data."""
    tick = 0

    while True:
        tick += 1

        # Toggle anomaly every ~120-300 seconds
        if tick % random.randint(120, 300) == 0:
            _state.toggle(random.choice(["latency", "errors", "connections"]))

        anomaly_active, anomaly_type = _state.read()

        # Generate 1-5 fake requests per tick
        for _ in range(random.randint(1, 5)):
            method = random.choice(METHODS)
            endpoint = random.choice(ENDPOINTS)

            # Determine status code
            if anomaly_active and anomaly_type == "errors" and endpoint != "/api/health":
                status = random.choices(
                    ["200", "500", "502", "503"],
                    weights=[60, 20, 10, 10],
                )[0]
            else:
                status = random.choices(
                    ["200", "201", "400", "404", "500"],
                    weights=[85, 5, 5, 4, 1],
                )[0]

            http_requests_total.labels(
                method=method, endpoint=endpoint, status=status
            ).inc()

            # Determine latency
            if anomaly_active and anomaly_type == "latency" and endpoint == "/api/search":
                duration = random.uniform(1.5, 8.0)  # spike on search
            else:
                duration = random.uniform(0.005, 0.3)

            http_request_duration_seconds.labels(
                method=method, endpoint=endpoint
            ).observe(duration)

            # DB queries
            query_type = random.choice(["select", "insert", "update"])
            db_dur = (
                random.uniform(0.1, 2.0)
                if anomaly_active and anomaly_type == "latency"
                else random.uniform(0.002, 0.05)
            )
            db_query_duration_seconds.labels(query_type=query_type).observe(db_dur)

        # Active connections
        active_connections.set(
            random.randint(200, 500)
            if anomaly_active and anomaly_type == "connections"
            else random.randint(10, 60)
        )

        # Queue depth
        queue_depth.set(
            random.randint(50, 300) if anomaly_active else random.randint(0, 15)
        )

        time.sleep(1)


@app.route("/metrics")
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


@app.route("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    t = threading.Thread(target=simulate_traffic, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=8000)