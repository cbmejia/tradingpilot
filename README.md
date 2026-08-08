# TradePilot AI

TradePilot AI is an **educational decision-support tool** for discretionary
forex traders. It captures a TradingView chart, pulls current market data,
has an LLM agent analyze the setup, scores that analysis against a fixed
rubric, runs deterministic safety checks, and asks a human to approve or
reject the resulting recommendation.

**TradePilot AI never places a trade.** There is no broker or order-execution
integration anywhere in this codebase. See [docs/architecture.md](docs/architecture.md)
for the full design, including why the agent never touches a dollar amount
or a score directly.

This project is being built incrementally, one milestone at a time. See
[docs/iterations.md](docs/iterations.md) for what's been built so far and
what's next.

## Structure

- `frontend/` — React + TypeScript UI (Tailwind added when the UI milestone lands)
- `backend/` — FastAPI app: routes, orchestrator, request/response schemas
- `agents/` — the trading agent (wraps the Claude call) and its prompt logic
- `tools/` — chart capture (Playwright, live/demo), market data, economic calendar
- `evals/` — deterministic rubric scoring of the agent's analysis
- `guardrails/` — hard safety rules (RR, freshness, validity, confidence) the agent may never bypass
- `database/` — SQLAlchemy models and persistence for the full audit trail
- `prompts/` — versioned markdown prompt templates
- `screenshots/` — captured chart images (`live/` and `demo/`)
- `logs/` — runtime logs
- `docs/` — architecture, testing, and iteration notes
- `tests/` — automated tests

## Status

Milestone 3 of 12: database schema and audit trail. See
[docs/iterations.md](docs/iterations.md).
