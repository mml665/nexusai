"""
Prometheus metrics for all services.

Exposes /metrics endpoint and provides request tracking middleware.
"""

import time
from typing import Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse


# ── Lightweight metrics (no prometheus_client dependency) ──
# We expose metrics in Prometheus text exposition format.
# This avoids adding prometheus-client as a dependency.

class Counter:
    def __init__(self, name: str, help_text: str, labels: tuple = ()):
        self.name = name
        self.help = help_text
        self.labels = labels
        self._values: dict[tuple, float] = {}

    def inc(self, amount: float = 1.0, **labels):
        key = tuple(labels.get(l, "") for l in self.labels)
        self._values[key] = self._values.get(key, 0.0) + amount

    def expose(self) -> str:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} counter"]
        for key, val in sorted(self._values.items()):
            if self.labels:
                label_str = ",".join(f'{l}="{v}"' for l, v in zip(self.labels, key))
                lines.append(f'{self.name}{{{label_str}}} {val}')
            else:
                lines.append(f"{self.name} {val}")
        return "\n".join(lines)


class Histogram:
    def __init__(self, name: str, help_text: str, buckets: tuple = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0), labels: tuple = ()):
        self.name = name
        self.help = help_text
        self.buckets = buckets
        self.labels = labels
        self._counts: dict[tuple, list[int]] = {}
        self._sums: dict[tuple, float] = {}
        self._totals: dict[tuple, int] = {}

    def observe(self, value: float, **labels):
        key = tuple(labels.get(l, "") for l in self.labels)
        if key not in self._counts:
            self._counts[key] = [0] * len(self.buckets)
            self._sums[key] = 0.0
            self._totals[key] = 0
        for i, b in enumerate(self.buckets):
            if value <= b:
                self._counts[key][i] += 1
        self._sums[key] += value
        self._totals[key] += 1

    def expose(self) -> str:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} histogram"]
        for key, counts in sorted(self._counts.items()):
            label_parts = []
            if self.labels:
                label_parts = [f'{l}="{v}"' for l, v in zip(self.labels, key)]
            for i, b in enumerate(self.buckets):
                labels_str = ",".join(label_parts + [f'le="{b}"'])
                lines.append(f'{self.name}_bucket{{{labels_str}}} {counts[i]}')
            # +Inf bucket
            labels_str = ",".join(label_parts + ['le="+Inf"'])
            lines.append(f'{self.name}_bucket{{{labels_str}}} {self._totals[key]}')
            labels_str = ",".join(label_parts)
            lines.append(f'{self.name}_sum{{{labels_str}}} {self._sums[key]}')
            lines.append(f'{self.name}_count{{{labels_str}}} {self._totals[key]}')
        return "\n".join(lines)


# ── Global metrics instances ──

http_requests_total = Counter(
    "nexusai_http_requests_total",
    "Total HTTP requests",
    labels=("method", "endpoint", "status"),
)

http_request_duration_seconds = Histogram(
    "nexusai_http_request_duration_seconds",
    "HTTP request duration in seconds",
    labels=("method", "endpoint"),
)

# Business metrics
sensor_readings_processed = Counter(
    "nexusai_sensor_readings_total",
    "Total sensor readings processed",
)

anomalies_detected_total = Counter(
    "nexusai_anomalies_detected_total",
    "Total anomalies detected",
    labels=("severity",),
)

llm_calls_total = Counter(
    "nexusai_llm_calls_total",
    "Total LLM API calls",
    labels=("status",),  # success / failure / fallback
)

active_alerts_gauge = Counter(
    "nexusai_active_alerts",
    "Current active alerts (triggered status)",
)


# ── Setup function ──

_all_metrics = [
    http_requests_total,
    http_request_duration_seconds,
    sensor_readings_processed,
    anomalies_detected_total,
    llm_calls_total,
    active_alerts_gauge,
]


def setup_metrics(app: FastAPI, service_name: str = ""):
    """
    Add /metrics endpoint and request tracking middleware to a FastAPI app.
    """

    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        duration = time.time() - start

        # Skip metrics endpoint itself
        if request.url.path != "/metrics":
            endpoint = request.url.path
            # Normalize IDs
            for seg in endpoint.split("/"):
                if seg.isdigit():
                    endpoint = endpoint.replace(seg, ":id")

            http_requests_total.inc(
                method=request.method,
                endpoint=endpoint,
                status=str(response.status_code),
            )
            http_request_duration_seconds.observe(
                duration,
                method=request.method,
                endpoint=endpoint,
            )

        return response

    @app.get("/metrics", response_class=PlainTextResponse)
    async def metrics_endpoint():
        lines = []
        for m in _all_metrics:
            exposed = m.expose()
            if exposed:
                lines.append(exposed)
        return "\n".join(lines) + "\n"
