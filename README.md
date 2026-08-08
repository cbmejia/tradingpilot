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
- `capture/` — chart capture tool: `CaptureProvider` interface, `DemoProvider` (offline fixtures), `LiveProvider` (Playwright), `CaptureManager` (picks one, never falls back)
- `tools/` — market data, economic calendar (chart capture lives in `capture/` — see above)
- `evals/` — deterministic rubric scoring of the agent's analysis
- `guardrails/` — hard safety rules (RR, freshness, validity, confidence) the agent may never bypass
- `database/` — SQLAlchemy models and persistence for the full audit trail
- `prompts/` — versioned markdown prompt templates
- `screenshots/` — captured chart images (`live/` and `demo/`)
- `logs/` — runtime logs
- `docs/` — architecture, testing, and iteration notes
- `tests/` — automated tests

## Running the backend

```bash
cd backend  # not required, just for context -- run these from the repo root
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload
```

Open **http://127.0.0.1:8000/docs** for interactive API docs (Swagger UI) —
you can create and fetch runs directly from the browser. Run `pytest` from
the repo root to run the test suite.

## Trying the chart capture tool by hand

DEMO mode needs nothing beyond the steps above and never touches the
network:

```bash
python -c "from capture import CaptureManager; r = CaptureManager(mode='demo').capture('EURUSD', '1h'); print(r)"
```

The image it points to is already committed at
`screenshots/demo/EURUSD_1h.png` — open it directly to see it.

LIVE mode additionally needs Playwright's browser binary (a real
download, not run automatically by this project):

```bash
playwright install chromium
python -c "from capture import CaptureManager; r = CaptureManager(mode='live').capture('EURUSD', '1h'); print(r)"
```

A successful LIVE capture is saved to `screenshots/live/` with a filename
like `EURUSD_1h_20260101T120000Z.png` (that folder is gitignored — LIVE
captures are local-only, never committed). Read TradingView's terms of
service before using LIVE mode: it's meant for your own manual,
low-volume use, not automated bulk capture — see
[docs/architecture.md](docs/architecture.md).

## Status

Milestone 5 of 12: chart capture tool (LIVE and DEMO providers). See
[docs/iterations.md](docs/iterations.md).
