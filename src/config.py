import os
from dotenv import load_dotenv

load_dotenv()

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
ALERT_RULES_PATH = os.getenv("ALERT_RULES_PATH", "alerting/alert_rules.yml")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").lower()

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

# Ollama
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:397b-cloud")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "https://api.ollama.com")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")

if LLM_PROVIDER not in ("anthropic", "ollama"):
    raise RuntimeError(f"Unknown LLM_PROVIDER '{LLM_PROVIDER}'. Use 'anthropic' or 'ollama'.")

if LLM_PROVIDER == "anthropic" and not ANTHROPIC_API_KEY:
    raise RuntimeError(
        "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key, "
        "or set LLM_PROVIDER=ollama to use Ollama instead."
    )

if LLM_PROVIDER == "ollama" and not OLLAMA_API_KEY:
    raise RuntimeError(
        "OLLAMA_API_KEY is not set. Add your Ollama API key to .env."
    )
