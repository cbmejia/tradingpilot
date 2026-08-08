# TradePilot AI — backend configuration.
#
# In plain terms: this is the one place that reads settings from the
# environment (populated from .env — see .env.example). Nothing else in
# the backend should call os.getenv() directly; it imports from here
# instead. No secrets or API keys are hardcoded or invented — if one
# isn't set in .env, it's simply None.

import os

from dotenv import load_dotenv

load_dotenv()

BACKEND_HOST = os.getenv("BACKEND_HOST", "0.0.0.0")
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))

# Browser origins allowed to call this API. Fixed to the two frontend dev
# server ports used in this project (see .claude/launch.json).
CORS_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:5174",
]

CAPTURE_MODE = os.getenv("CAPTURE_MODE", "demo")
MARKET_DATA_MODE = os.getenv("MARKET_DATA_MODE", "demo")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")  # None if unset -- never invented

# Guardrail thresholds (guardrails/rules.py reads these itself, from the
# same env vars, to stay isolated/standalone -- declared here too just so
# every configurable value in the app is visible in one place).
CAPTURE_MAX_AGE_SECONDS = float(os.getenv("CAPTURE_MAX_AGE_SECONDS", "300"))
MARKET_DATA_MAX_AGE_SECONDS = float(os.getenv("MARKET_DATA_MAX_AGE_SECONDS", "900"))
MIN_RISK_REWARD = float(os.getenv("MIN_RISK_REWARD", "1.0"))
MIN_TOTAL_SCORE = int(os.getenv("MIN_TOTAL_SCORE", "60"))
