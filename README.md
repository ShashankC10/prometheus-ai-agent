# Prometheus AI Agent

An LLM-powered infrastructure monitoring agent that queries Prometheus metrics, detects anomalies, and provides root-cause analysis in natural language. Built with LangChain, LangGraph, and Streamlit. Supports both Anthropic Claude and local models via Ollama.

## What It Does

Ask questions about your infrastructure in plain English:

- *"What caused the spike in 5xx errors in the last hour?"*
- *"Is there anything unusual with CPU or memory right now?"*
- *"Explain all my alerting rules in simple terms."*
- *"Correlate request latency with database query times."*

The agent translates your questions into PromQL, fetches data from Prometheus, runs statistical anomaly detection, and produces a clear incident-style summary.

## Architecture

```
┌──────────────┐     ┌───────────────────────────────────────────┐
│  Streamlit   │     │          LangGraph ReAct Agent            │
│     UI       │────▶│  (Claude or Ollama as reasoning engine)   │
└──────────────┘     │                                           │
                     │  Tools:                                   │
                     │  ├─ Metric Catalog   → Discover metrics   │
                     │  ├─ PromQL Validator → Validate queries   │
                     │  ├─ PromQL Query     → Prometheus API     │
                     │  ├─ Anomaly Detect   → MAD + z-score      │
                     │  ├─ Incident Packs   → Multi-signal       │
                     │  ├─ Metric Explorer  → Targets & labels   │
                     │  └─ Alert Rules      → Parse & explain    │
                     └───────────────────────────────────────────┘
                                      │
                     ┌────────────────▼────────────────┐
                     │        Prometheus (Docker)       │
                     │  ├─ node_exporter (system metrics)│
                     │  └─ fake-app (HTTP metrics)       │
                     └───────────────────────────────────┘
```

## Evaluation Results

Benchmark: 20 questions across 7 categories, run against a live Prometheus instance (524 metrics, node-exporter + fake HTTP app).

| Metric | Result |
|--------|--------|
| Total cases | 20 |
| Errors | 0 |
| PASS rate | 10 / 20 (50%) |
| Avg metric family coverage | **97%** |
| PromQL execution success rate | **90%** |

**By category:**

| Category | Cases | Coverage | Exec Rate |
|----------|-------|----------|-----------|
| metric_lookup | 4 | 100% | 100% |
| alert_explanation | 2 | 100% | — |
| anomaly_investigation | 4 | 100% | 83% |
| error_triage | 4 | 100% | 100% |
| latency_analysis | 2 | 100% | 100% |
| resource_saturation | 3 | 100% | 67% |
| incident_investigation | 1 | 100% | 100% |

WARN cases are flagged by the eval harness for label-name tokens (`status`, `instance`) appearing in PromQL expressions — these are valid label selectors, not hallucinations. All queries that executed against Prometheus returned a `success` status.

Run evals yourself:
```bash
python evals/run_evals.py
# Filter by category:
python evals/run_evals.py --category anomaly_investigation
# Run specific cases:
python evals/run_evals.py --ids q001,q006,q013
```

Results are saved to `evals/results.json`.

## Quick Start

### 1. Clone and configure

```bash
git clone <your-repo-url>
cd prometheus-ai-agent

cp .env.example .env
# Edit .env — see Configuration section below
```

### 2. Start Prometheus stack

```bash
docker compose up -d
```

This starts:
- **Prometheus** on `localhost:9090`
- **Node Exporter** on `localhost:9100` (system metrics)
- **Fake App** on `localhost:8000` (simulated HTTP metrics with periodic anomalies)

### 3. Install Python dependencies

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 4. Run the app

```bash
streamlit run app.py
```

Open `http://localhost:8501` in your browser.

## Configuration

All settings are loaded from `.env`. Copy `.env.example` to get started.

### LLM Provider

The agent supports two LLM backends, controlled by `LLM_PROVIDER`:

**Option A — Anthropic Claude (default)**
```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-api-key-here
ANTHROPIC_MODEL=claude-sonnet-4-20250514
```

**Option B — Ollama (local or cloud-hosted)**
```env
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen3:30b
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_API_KEY=your-ollama-key   # required for cloud endpoints
```

Any model served by Ollama with `tools` capability works. Larger models produce more accurate PromQL and better multi-step reasoning.

### Prometheus

```env
PROMETHEUS_URL=http://localhost:9090   # default
ALERT_RULES_PATH=alerting/alert_rules.yml
```

## Project Structure

```
prometheus-ai-agent/
├── docker-compose.yml           # Prometheus + exporters
├── prometheus/
│   └── prometheus.yml           # Scrape configuration
├── alerting/
│   └── alert_rules.yml          # Sample alerting rules
├── src/
│   ├── config.py                # Environment variable loading & validation
│   ├── agent.py                 # LangGraph ReAct agent + LLM provider selection
│   ├── planner.py               # Multi-step StateGraph investigation planner
│   ├── prom_api.py              # Shared Prometheus HTTP client
│   ├── structured_output.py     # Pydantic output schemas
│   ├── fake_metrics_app.py      # Synthetic metrics generator (Flask)
│   └── tools/
│       ├── promql_query.py      # Execute PromQL queries
│       ├── anomaly_detection.py # Multi-method anomaly detection (MAD + z-score)
│       ├── metric_catalog.py    # Search live Prometheus metadata
│       ├── promql_validator.py  # Validate PromQL before execution
│       ├── incident_packs.py    # Multi-signal investigation packs
│       ├── metric_explorer.py   # Discover metrics and targets
│       └── alert_rules.py       # Read and explain alert rules
├── evals/
│   ├── benchmark.json           # 20-question benchmark suite
│   ├── run_evals.py             # Eval runner + scoring
│   └── results.json             # Latest eval output
├── app.py                       # Streamlit UI
├── requirements.txt
└── .env.example
```

## Agent Tools

| Tool | Purpose |
|------|---------|
| `metric_catalog_tool` | Search live Prometheus metadata to find real metric names before writing PromQL |
| `promql_validator_tool` | Validate a PromQL expression before executing it |
| `promql_query_tool` | Execute instant or range PromQL queries against the Prometheus API |
| `anomaly_detection_tool` | Fetch metric ranges and detect anomalies via rolling MAD + z-score + change-point |
| `incident_pack_tool` | Run a multi-signal investigation pack (high_latency, high_error_rate, resource_saturation, etc.) |
| `metric_explorer_tool` | List available metrics, label values, and scrape targets |
| `alert_rules_tool` | Parse configured alert rules and check firing/pending alerts |

## Example Questions

- "What services is Prometheus monitoring?"
- "Show me the request rate for all endpoints over the last 30 minutes"
- "Are there any anomalies in error rates?"
- "What is the p95 latency for /api/search?"
- "Explain the HighCpuUsage alert rule"
- "Are any alerts firing right now?"
- "Correlate CPU, memory, and request latency to find the root cause"
- "Is there a memory leak? Show memory usage trend over the last hour."
- "Show disk usage on all instances"
- "What is the top 5 endpoints by error rate?"

## Tech Stack

- **Python 3.11+**
- **LangChain + LangGraph** — ReAct agent and StateGraph planner
- **Anthropic Claude** — cloud LLM option
- **Ollama** — local/self-hosted LLM option
- **Prometheus** — metrics collection
- **Streamlit** — web UI
- **Docker Compose** — infrastructure
