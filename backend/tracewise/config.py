import os

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://tracewise:tracewise@localhost:5432/tracewise")
INGEST_KEY = os.environ.get("TW_INGEST_KEY", "")
DEPLOYER_URL = os.environ.get("DEPLOYER_URL", "http://shopfront:7000")
SHOPFRONT_REPO = os.environ.get("SHOPFRONT_REPO", "/repos/shopfront")

MODEL = os.environ.get("TW_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("TW_EFFORT", "medium")
# Per-million-token prices for cost tracking (Opus 5.5).
PRICE_IN = float(os.environ.get("TW_PRICE_IN", "4.0"))
PRICE_OUT = float(os.environ.get("TW_PRICE_OUT", "20.0"))

# Guardrails for one incident.
MAX_TURNS = int(os.environ.get("TW_MAX_TURNS", "40"))
MAX_COST_USD = float(os.environ.get("TW_MAX_COST_USD", "3.0"))
MAX_ACTIONS = int(os.environ.get("TW_MAX_ACTIONS", "4"))
LEASE_SECONDS = 90

AGENT_ENABLED = os.environ.get("TW_AGENT_ENABLED", "true").lower() == "true"
NEATLOGS_API_KEY = os.environ.get("NEATLOGS_API_KEY", "")

# Deploy a coding agent's fix automatically once its tests pass (otherwise it waits for review).
AUTO_DEPLOY_FIXES = os.environ.get("TW_AUTO_DEPLOY_FIXES", "false").lower() == "true"
