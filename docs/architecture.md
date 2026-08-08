# Architecture

TradePilot AI is an educational decision-support tool for discretionary forex
traders. It captures a chart, gathers market data, has an LLM agent analyze
the setup, scores that analysis against a fixed rubric, runs deterministic
safety checks, and asks a human to approve or reject the resulting
recommendation. **It never places a trade.** There is no broker/order-execution
integration anywhere in this codebase, and none is planned.

## Non-negotiables

These are structural, not configurable:

- **No execution.** Nothing in this system can send an order to a broker.
  The workflow's only possible terminal actions are "human approved" or
  "human rejected" — both are just database writes.
- **The agent never emits a number that reaches the UI unscored.** Claude
  produces qualitative, structured analysis (trend, structure, setup
  quality, uncertainty, rationale). It does not compute a score. All
  scoring is done by deterministic Python code in `evals/` that a human can
  read, test, and audit.
- **Guardrails are deterministic and run outside the LLM.** They check RR
  ratio, data freshness, input validity, and confidence in plain Python.
  They can only downgrade a recommendation toward "requires review" or
  "blocked" — never bypass or auto-approve.
- **Every run is fully audited.** Inputs, screenshot, market data snapshot,
  agent output, eval score, guardrail results, and the human's decision are
  all persisted. Nothing is computed and thrown away.
- **No fabricated data.** If a tool fails (capture fails, market data
  unavailable), the run is marked as errored and that is shown explicitly —
  never papered over with a placeholder value.

## Components

| Component | Path | Responsibility |
|---|---|---|
| Frontend | `frontend/` | React/TS/Tailwind UI. Talks only to the backend REST API. Renders the form, run status, screenshot, agent analysis, score, guardrail results, and the approve/reject controls. |
| Backend | `backend/` | FastAPI app. Owns the SQLite database. Route handlers stay thin and delegate to `backend/orchestrator.py`. |
| Orchestrator | `backend/orchestrator.py` | Runs the 12-step workflow below in order, persisting state as it goes. |
| Agent | `agents/trade_agent.py` | Wraps the Claude call. Input: screenshot + market data + trade params + prompt. Output: a validated, structured, qualitative analysis — never a score or dollar figure. |
| Prompts | `prompts/` | Versioned prompt text for the agent, kept out of Python so they can be iterated on independently. |
| Screenshot tool | `capture/` | Captures a timestamped chart image. See "Screenshot capture design" below. (Originally planned as `tools/tradingview_capture.py`; moved to its own `capture/` package in Milestone 5 — that file now just points here.) |
| Market data tool | `tools/market_data.py` | Fetches a structured market snapshot for the selected symbol. Same LIVE/DEMO split as the screenshot tool. |
| Economic calendar tool | `tools/economic_calendar.py` | Contextual input for later; not wired into the workflow yet. |
| Evaluation engine | `evals/trade_evaluator.py` | Pure, deterministic function: agent output + market data + trade params → a rubric score with a component breakdown. No LLM call inside it. |
| Guardrails | `guardrails/rules.py` | Deterministic checks (RR, freshness, input validity, confidence). Returns PASS / REQUIRES_REVIEW / BLOCKED with reasons. |
| Database | `database/` | SQLAlchemy models and session management for the audit trail. Schema is defined in Milestone 3 — this milestone only sets up the package. |
| Logs | `logs/` | Operational logs (step timing, tool errors). Separate from the audit trail, which lives in the database. |

## Workflow

The orchestrator runs these steps in order for every analysis run:

1. User selects a symbol (frontend).
2. User selects a timeframe (frontend).
3. User enters optional trade parameters — e.g. proposed entry/stop/target
   (frontend).
4. `capture_tradingview()` captures the chart and timestamps it.
5. `get_market_data()` retrieves a current market snapshot.
6. The agent observes the screenshot and the structured market data.
7. The agent analyzes trend, structure, setup quality, and its own
   uncertainty, and returns structured (non-numeric) output.
8. The evaluation engine scores the setup against a fixed rubric.
9. Guardrails check RR, data freshness, input validity, and confidence.
10. The system produces a recommendation, or marks the run as requiring
    review.
11. A human approves or rejects. This is the only way a run reaches a
    terminal state.
12. The complete run — every input and output from steps 1–11 — is stored
    as an immutable audit trail.

Steps 4–10 happen inside `backend/orchestrator.py`; nothing about this
sequence lives in route handlers or in the frontend.

## Screenshot capture design

`capture/base.py` defines a single interface both modes implement, so
whatever eventually calls it (the orchestrator, in a later milestone)
never needs to know which mode is active:

```
CaptureProvider.capture(symbol, timeframe) -> CaptureResult
```

`CaptureResult` always carries: `mode` (`LIVE`/`DEMO`), `symbol`,
`timeframe`, `screenshot_path`, `captured_at`, `status`
(`SUCCESS`/`FAILED`), and `error_message`. `captured_at` is recorded at
the exact moment the screenshot is taken — not when it's later written to
the database — because the data-freshness guardrail (Milestone 9)
measures a run's age from this timestamp.

- **LIVE mode** — `capture/live_provider.py`'s `LiveProvider`: drives a
  real headless Chromium browser via Playwright, navigates to the
  TradingView chart for the symbol/timeframe, waits for it to render (a
  fixed, bounded pause — never an infinite wait), and screenshots it to
  `screenshots/live/`. On any failure it returns a `FAILED` result with
  the real error — it never falls back to a demo image.
- **DEMO mode** — `capture/demo_provider.py`'s `DemoProvider`: returns a
  pre-committed fixture image from `screenshots/demo/`, matched
  deterministically by symbol and timeframe. No network access at all. If
  the exact symbol/timeframe asked for has no fixture, it fails clearly
  rather than substituting a different pair's chart.
- **`capture/manager.py`'s `CaptureManager`** picks exactly one provider
  based on `CAPTURE_MODE` and always uses that same one. There is no
  fallback logic anywhere between the two — if `CaptureManager` is
  running LIVE and the live capture fails, the result is a failed LIVE
  capture, never a substituted DEMO one. `CaptureManager` also double-checks
  that whatever a provider returns is actually labeled with the mode it's
  supposed to be running in, and raises rather than passing through a
  mismatched result — so a stored `Capture` row can never misrepresent
  its own source.

The active mode is selected by the `CAPTURE_MODE` environment variable
(`live` | `demo`, case-insensitive). `tools/market_data.py` mirrors this
pattern with `MARKET_DATA_MODE`. Building DEMO mode first (Milestone 5)
means the rest of the workflow (agent, eval, guardrails, approval, UI)
can be built and tested without a live browser or a market-data API key.

### A note on TradingView's terms of service

TradingView's terms of service restrict automated access to their site.
`LIVE` mode exists for the developer's own manual, low-request-volume use
— checking a real chart occasionally while working on this project — not
for bulk, repeated, or unattended automated capture. `DEMO` mode, backed
by the committed fixture images in `screenshots/demo/`, is the supported
path for demonstrations, grading, and any automated testing.

## Data flow (per run)

```
Frontend
  │  POST /runs {symbol, timeframe, params}
  ▼
Backend (FastAPI) ── creates Run row, status=pending
  │
  ▼
Orchestrator
  │  capture_tradingview()      → screenshot path + captured_at
  │  get_market_data()          → market snapshot
  │  trade_agent.analyze()      → structured qualitative analysis (Claude)
  │  trade_evaluator.score()    → deterministic rubric score
  │  guardrails.check()         → PASS / REQUIRES_REVIEW / BLOCKED + reasons
  │  → status=awaiting_approval (or error, if any step failed)
  ▼
Database ── every step's input/output persisted as it happens
  ▲
  │  GET /runs/{id}
Frontend ── shows screenshot, analysis, score, guardrail results
  │  POST /runs/{id}/decision {approved|rejected}
  ▼
Database ── run reaches terminal state
```

## Tech stack mapping

| Layer | Choice | Notes |
|---|---|---|
| Frontend | React + TypeScript + Tailwind | Milestone 1 scaffolded the UI shell with hand-rolled CSS. Tailwind is added when the UI milestone is built out, not before — no need to churn the shell twice. |
| Backend | Python + FastAPI | `backend/main.py` is the app entrypoint. |
| Database | SQLite via SQLAlchemy | File lives at `database/tradepilot.db`, gitignored. Exact schema: Milestone 3. |
| Screenshot automation | Playwright (LIVE) / local fixture (DEMO) | See above. |
| Agent | Claude (Anthropic API) | Model configured via `CLAUDE_MODEL` in `.env`; defaults to the latest Claude Sonnet. |

## What this milestone does NOT include

Database schema, backend API routes, the actual capture/market-data/agent/
eval/guardrail implementations, human approval endpoints, Tailwind UI, and
tests are all later milestones (3–12). This milestone is architecture and
folder structure only.
