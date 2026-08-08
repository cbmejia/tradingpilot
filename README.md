# TradePilot AI

TradePilot AI is an agent-based trading assistant. It captures TradingView
chart screenshots, pulls market data and economic calendar events, and uses
an LLM-driven agent — bounded by explicit guardrails and scored by evals —
to analyze trade setups.

This project is being built incrementally. Right now, only the project
structure exists: directories and placeholder files. No application logic,
frontend scaffold, or dependencies have been installed yet. Each part
(tools, agents, guardrails, evals, database, backend, frontend) will be
implemented and tested phase by phase.

## Structure

- `frontend/` — React frontend (not scaffolded yet)
- `backend/` — API server coordinating agents, tools, and the database
- `agents/` — the core trading agent and its prompt logic
- `tools/` — chart capture, market data, and economic calendar integrations
- `evals/` — evaluation/scoring of agent trade decisions
- `guardrails/` — hard safety rules the agent may never violate
- `database/` — models and persistence
- `prompts/` — versioned markdown prompt templates
- `screenshots/` — captured chart images (live and demo)
- `logs/` — runtime logs
- `docs/` — architecture, testing, and iteration notes
- `tests/` — automated tests

## Status

Structure only. No application logic yet.
