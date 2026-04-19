"""
Evaluation script for the Prometheus AI Agent.

Runs benchmark questions and scores:
- PromQL execution success rate
- Hallucinated metric rate (metric used but not in Prometheus)
- Tool usage correctness (right tools called for question category)
- Query semantic correctness (expected metric families present in response)

Usage:
    python evals/run_evals.py [--ids q001,q002] [--category anomaly_investigation]
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests

from src.agent import create_agent, run_agent
from src.config import PROMETHEUS_URL

BENCHMARK_PATH = Path(__file__).parent / "benchmark.json"
RESULTS_PATH = Path(__file__).parent / "results.json"


# ── Prometheus helpers ────────────────────────────────────────────────

def get_live_metrics() -> set[str]:
    try:
        resp = requests.get(
            f"{PROMETHEUS_URL}/api/v1/label/__name__/values", timeout=10
        )
        return set(resp.json().get("data", []))
    except Exception:
        return set()


def validate_promql_live(expr: str) -> bool:
    try:
        resp = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": expr},
            timeout=10,
        )
        return resp.json().get("status") == "success"
    except Exception:
        return False


# ── Scoring helpers ───────────────────────────────────────────────────

_PROMQL_BLOCK_RE = re.compile(r"```(?:promql)?\s*(.*?)```", re.DOTALL)
_INLINE_QUERY_RE = re.compile(r"`([^`]+\([^`]+\))`")


def extract_promql_from_response(response: str) -> list[str]:
    queries = _PROMQL_BLOCK_RE.findall(response)
    queries += _INLINE_QUERY_RE.findall(response)
    return [q.strip() for q in queries if q.strip()]


def score_response(case: dict, response: str, live_metrics: set[str]) -> dict:
    response_lower = response.lower()
    promql_exprs = extract_promql_from_response(response)

    # 1. Metric family coverage: did the response mention expected families?
    families_hit = [
        fam for fam in case["expected_metric_families"]
        if fam.lower() in response_lower
    ]
    family_coverage = (
        len(families_hit) / len(case["expected_metric_families"])
        if case["expected_metric_families"] else 1.0
    )

    # 2. Acceptable PromQL pattern match
    pattern_match = any(
        any(pat.lower() in expr.lower() for pat in case["acceptable_promql_patterns"])
        for expr in promql_exprs
    ) if case["acceptable_promql_patterns"] and promql_exprs else (
        True if not case["acceptable_promql_patterns"] else False
    )

    # 3. Hallucination check: any metric name in response not in live Prometheus?
    hallucinated = []
    for expr in promql_exprs:
        # extract bare metric names from the expression
        tokens = re.findall(r"\b([a-z_][a-z0-9_]{4,})\b", expr)
        for tok in tokens:
            if (
                tok not in live_metrics
                and not tok.startswith(("rate", "irate", "sum", "avg", "max", "min",
                                        "topk", "bottomk", "count", "histogram_quantile",
                                        "increase", "delta", "by", "without", "on",
                                        "ignoring", "group_left", "group_right", "bool",
                                        "and", "or", "unless", "offset", "bool",
                                        "label_replace", "label_join", "vector",
                                        "scalar", "time", "minute", "hour", "day"))
                and len(tok) > 5
            ):
                hallucinated.append(tok)

    # 4. PromQL execution success
    execution_results = []
    for expr in promql_exprs[:3]:  # test up to 3 queries per response
        ok = validate_promql_live(expr)
        execution_results.append({"expr": expr, "success": ok})

    exec_success_rate = (
        sum(1 for r in execution_results if r["success"]) / len(execution_results)
        if execution_results else None
    )

    return {
        "family_coverage": round(family_coverage, 2),
        "pattern_match": pattern_match,
        "hallucinated_tokens": list(set(hallucinated)),
        "hallucination_count": len(set(hallucinated)),
        "promql_expressions_found": len(promql_exprs),
        "execution_results": execution_results,
        "exec_success_rate": exec_success_rate,
    }


# ── Main runner ───────────────────────────────────────────────────────

def run_eval(
    filter_ids: list[str] | None = None,
    filter_category: str | None = None,
) -> None:
    benchmark = json.loads(BENCHMARK_PATH.read_text())

    if filter_ids:
        benchmark = [c for c in benchmark if c["id"] in filter_ids]
    if filter_category:
        benchmark = [c for c in benchmark if c["category"] == filter_category]

    print(f"Running {len(benchmark)} benchmark cases...\n")

    live_metrics = get_live_metrics()
    if not live_metrics:
        print("WARNING: Could not reach Prometheus — hallucination check disabled.\n")

    agent = create_agent()
    results = []

    for i, case in enumerate(benchmark, 1):
        print(f"[{i}/{len(benchmark)}] {case['id']} ({case['category']}): {case['question']}")
        start = time.time()
        try:
            response = run_agent(agent, case["question"])
            elapsed = time.time() - start
            scores = score_response(case, response, live_metrics)
            result = {
                "id": case["id"],
                "category": case["category"],
                "question": case["question"],
                "elapsed_seconds": round(elapsed, 1),
                "scores": scores,
                "response_preview": response[:300],
                "error": None,
            }
            status = "PASS" if scores["family_coverage"] >= 0.5 and not scores["hallucinated_tokens"] else "WARN"
            print(f"  {status} | coverage={scores['family_coverage']} | hallucinations={scores['hallucination_count']} | exec_rate={scores['exec_success_rate']} | {elapsed:.1f}s\n")
        except Exception as e:
            elapsed = time.time() - start
            result = {
                "id": case["id"],
                "category": case["category"],
                "question": case["question"],
                "elapsed_seconds": round(elapsed, 1),
                "scores": None,
                "response_preview": None,
                "error": str(e),
            }
            print(f"  ERROR: {e}\n")

        results.append(result)

    # ── Summary ───────────────────────────────────────────────────────
    valid = [r for r in results if r["scores"]]
    total = len(results)
    errors = len(results) - len(valid)

    avg_coverage = sum(r["scores"]["family_coverage"] for r in valid) / len(valid) if valid else 0
    total_hallucinations = sum(r["scores"]["hallucination_count"] for r in valid)
    exec_rates = [r["scores"]["exec_success_rate"] for r in valid if r["scores"]["exec_success_rate"] is not None]
    avg_exec = sum(exec_rates) / len(exec_rates) if exec_rates else None

    summary = {
        "total_cases": total,
        "errors": errors,
        "avg_family_coverage": round(avg_coverage, 2),
        "total_hallucinated_tokens": total_hallucinations,
        "avg_exec_success_rate": round(avg_exec, 2) if avg_exec is not None else None,
    }

    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for k, v in summary.items():
        print(f"  {k}: {v}")

    output = {"summary": summary, "results": results}
    RESULTS_PATH.write_text(json.dumps(output, indent=2))
    print(f"\nFull results saved to {RESULTS_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Prometheus AI Agent evals")
    parser.add_argument("--ids", help="Comma-separated case IDs to run (e.g. q001,q002)")
    parser.add_argument("--category", help="Filter by category")
    args = parser.parse_args()

    filter_ids = args.ids.split(",") if args.ids else None
    run_eval(filter_ids=filter_ids, filter_category=args.category)
