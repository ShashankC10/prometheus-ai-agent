# 🔥 Prometheus AI Agent

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
│  Streamlit   │     │          LangChain ReAct Agent            │
│     UI       │────▶│  (Claude or Ollama as reasoning engine)   │
└──────────────┘     │                                           │
                     │  Tools:                                   │
                     │  ├─ PromQL Query    → Prometheus HTTP API │
                     │  ├─ Anomaly Detect  → Z-score analysis    │
                     │  ├─ Metric Explorer → Discover metrics    │
                     │  └─ Alert Rules     → Parse & explain     │
                     └───────────────────────────────────────────┘
                                      │
                     ┌────────────────▼────────────────┐
                     │        Prometheus (Docker)       │
                     │  ├─ node_exporter (system metrics)│
                     │  └─ fake-app (HTTP metrics)       │
                     └───────────────────────────────────┘
```

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
OLLAMA_MODEL=qwen3.5:397b-cloud
OLLAMA_BASE_URL=http://localhost:11434
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
│   ├── agent.py                 # LangChain ReAct agent + LLM provider selection
│   ├── prom_api.py              # Shared Prometheus HTTP client
│   ├── fake_metrics_app.py      # Synthetic metrics generator (Flask)
│   └── tools/
│       ├── __init__.py
│       ├── promql_query.py      # Execute PromQL queries
│       ├── anomaly_detection.py # Statistical anomaly detection
│       ├── metric_explorer.py   # Discover metrics and targets
│       └── alert_rules.py       # Read and explain alert rules
├── app.py                       # Streamlit UI
├── requirements.txt
├── .env.example
└── README.md
```

## Agent Tools

| Tool | Purpose |
|------|---------|
| `promql_query_tool` | Execute instant or range PromQL queries against the Prometheus API |
| `anomaly_detection_tool` | Fetch metric ranges and detect statistical anomalies via z-score |
| `metric_explorer_tool` | List available metrics, labels, and scrape targets |
| `alert_rules_tool` | Parse configured alert rules and check firing/pending alerts |

## Example Questions

- "What services is Prometheus monitoring?"
- "Show me the request rate for all endpoints over the last 30 minutes"
- "Are there any anomalies in error rates?"
- "What is the p95 latency for /api/search?"
- "Explain the HighCpuUsage alert rule"
- "Are any alerts firing right now?"
- "Correlate CPU, memory, and request latency to find the root cause"

## Tech Stack

- **Python 3.11+**
- **LangChain + LangGraph** — ReAct agent framework
- **Anthropic Claude** — cloud LLM option
- **Ollama** — local/self-hosted LLM option
- **Prometheus** — metrics collection
- **Streamlit** — web UI
- **Docker Compose** — infrastructure