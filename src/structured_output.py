"""
Structured output formatter for investigation results.

Returns a typed dict that is both machine-readable (for evals/tests)
and rendered in the Streamlit UI.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field


class AnomalySummary(BaseModel):
    metric: str
    anomaly_count: int
    trend: str
    direction: str | None = None


class InvestigationResult(BaseModel):
    issue_category: str = Field(description="Category of the issue found, e.g. 'high_error_rate'")
    suspected_service: str | None = Field(default=None, description="Service name if identifiable")
    evidence_metrics: list[str] = Field(default_factory=list, description="Metric names used as evidence")
    confidence: Literal["high", "medium", "low"] = Field(default="medium")
    anomalies_found: list[AnomalySummary] = Field(default_factory=list)
    promql_used: list[str] = Field(default_factory=list, description="PromQL queries executed")
    summary: str = Field(description="Plain-language summary of findings")
    recommended_actions: list[str] = Field(default_factory=list)
    tool_trace: list[str] = Field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [
            f"**Issue:** {self.issue_category}",
            f"**Confidence:** {self.confidence}",
        ]
        if self.suspected_service:
            lines.append(f"**Suspected service:** {self.suspected_service}")
        lines.append(f"\n{self.summary}")
        if self.evidence_metrics:
            lines.append("\n**Evidence metrics:**")
            lines += [f"- `{m}`" for m in self.evidence_metrics]
        if self.promql_used:
            lines.append("\n**Queries used:**")
            lines += [f"```promql\n{q}\n```" for q in self.promql_used]
        if self.anomalies_found:
            lines.append("\n**Anomalies detected:**")
            for a in self.anomalies_found:
                lines.append(f"- `{a.metric}`: {a.anomaly_count} anomaly points, trend={a.trend}")
        if self.recommended_actions:
            lines.append("\n**Recommended actions:**")
            lines += [f"- {a}" for a in self.recommended_actions]
        return "\n".join(lines)


_STRUCTURED_PROMPT = """Based on the investigation evidence below, produce a structured JSON result.

Evidence:
{evidence}

Return ONLY a valid JSON object with these keys:
  issue_category: string (e.g. "high_error_rate", "cpu_saturation", "normal", "latency_spike")
  suspected_service: string or null
  evidence_metrics: array of metric name strings
  confidence: "high", "medium", or "low"
  anomalies_found: array of objects {{metric, anomaly_count, trend, direction}}
  promql_used: array of PromQL expression strings
  summary: plain-language paragraph (2-4 sentences)
  recommended_actions: array of action strings (empty if no issues)

No markdown, no explanation, only JSON."""


def build_structured_result(
    category: str,
    queries_run: list[dict],
    anomalies_found: list[dict],
    alert_context: dict | None,
    discovered_metrics: list[str],
    tool_trace: list[str],
    llm,
) -> InvestigationResult:
    from langchain_core.messages import HumanMessage

    evidence = {
        "category": category,
        "discovered_metrics": discovered_metrics,
        "queries_run": queries_run,
        "anomalies_found": anomalies_found,
        "alert_context": alert_context,
    }
    response = llm.invoke(
        [HumanMessage(content=_STRUCTURED_PROMPT.format(
            evidence=json.dumps(evidence, default=str)[:6000]
        ))]
    )
    raw = response.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        data = json.loads(raw)
        data["tool_trace"] = tool_trace
        # Normalise anomalies_found field to match AnomalySummary
        normalised = []
        for a in data.get("anomalies_found", []):
            if isinstance(a.get("metric"), dict):
                a["metric"] = json.dumps(a["metric"])
            normalised.append(a)
        data["anomalies_found"] = normalised
        return InvestigationResult(**data)
    except Exception:
        return InvestigationResult(
            issue_category="unknown",
            confidence="low",
            summary="Could not parse structured output.",
            tool_trace=tool_trace,
        )
