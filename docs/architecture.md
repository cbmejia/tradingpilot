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
| Evaluation engine | `evals/trade_evaluator.py` | Pure, deterministic function: agent output + trade params → a rubric score with a component breakdown. No LLM call inside it. See "Evaluation engine design" below and [docs/rubric.md](rubric.md) for the full rubric. |
| Guardrails | `guardrails/rules.py` | Eleven deterministic checks (RR, freshness, input validity, uncertainty, synthetic-data). Returns `BLOCKED` / `REQUIRES_REVIEW` / `READY_FOR_REVIEW` with a reason per check. See "Guardrails design" below. |
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

## Market data tool design

`tools/market_data.py` follows the identical pattern: one interface
(`MarketDataProvider.get_quote(symbol) -> MarketQuote`), a `LIVE`
provider and a `DEMO` provider, and a `MarketDataManager` that picks
between them via `MARKET_DATA_MODE` and never falls back from one to the
other. `MarketQuote` carries `price` and `timestamp`.

**The single rule this tool cannot break:** if the source is unreachable,
times out, doesn't recognize the symbol, or sends back something that
doesn't parse, the result is `FAILED` with `price=None`. Nothing here
ever invents, estimates, interpolates, or carries forward a price — a
fabricated number would corrupt the agent, the evaluation, and the
guardrails simultaneously, while still looking legitimate.

- **LIVE mode** — `LiveMarketDataProvider`: calls Alpha Vantage's
  `CURRENCY_EXCHANGE_RATE` endpoint. Free tier, no paid plan, but does
  require a free signup for an API key (`MARKET_DATA_API_KEY` in `.env`).
  Chosen over no-signup alternatives (e.g. Frankfurter) because it
  reports an actual quote timestamp rather than a once-daily reference
  rate. `timestamp` is always the time the *source* says the quote is
  from, never the time the tool happened to ask for it, because the
  data-freshness guardrail (Milestone 9) needs to know how old the data
  genuinely is.
- **DEMO mode** — `DemoMarketDataProvider`: reads a fixed, deterministic
  `price` from `tools/demo_market_data.json` (same value every call),
  marked with `source="demo_fixture"`. No network access. An
  unrecognized symbol fails clearly rather than substituting another
  pair's price. **`timestamp` is a deliberate exception to the
  "source time, never fetch time" rule above:** it's generated fresh
  (`datetime.now(utc)`) on every call, not read from the fixture. A
  Milestone 9 hardening pass found that a fixed historical timestamp
  made every demo quote instantly stale, so `MARKET_DATA_FRESH` blocked
  every demo run before a human ever saw it — even though `SYNTHETIC_DATA`
  already guarantees a demo run can never reach `READY_FOR_REVIEW`
  on its own. The freshness guardrail was not weakened to fix this; only
  the demo provider changed. See the "Milestone 9 fix" entry in
  `docs/iterations.md`.

## Agent design

`agents/trade_agent.py`'s `TradeAgent.analyze(capture_result,
market_data_result, trade_params)` sends the screenshot and market data
snapshot to Claude and returns an `AgentAnalysisResult` — a `status`
(`SUCCESS`/`FAILED`), a timezone-aware UTC `timestamp`, `error_message`,
free-form prose (`analysis_text`, `trend_assessment`,
`structure_assessment`, `setup_assessment`, for a human reviewer to
read), an overall `uncertainty` (`LOW`/`MEDIUM`/`HIGH`), and five
fixed-category fields — `trend_direction`, `trend_quality`,
`structure_quality`, `setup_quality`, `context_risk` — each one word
from a small, closed, documented set (always including `UNCLEAR`). The
category fields are what `evals/trade_evaluator.py` actually scores from
— added in a Milestone 8 revision after the original prose-only rubric
turned out to reward verbosity over setup quality (see
`docs/rubric.md`).

**The hard boundary:** the agent produces words — prose or a category
label — never numbers that could function as a score. `_parse_response()`
requires Claude's reply to match the expected JSON shape exactly: every
prose field must actually be text, `uncertainty` must be one of
`LOW`/`MEDIUM`/`HIGH`, every category field must be one of its own
documented allowed values (never coerced if it isn't — an unrecognized
category word fails the response, it is not mapped to `UNCLEAR` on the
agent's behalf), and any extra field carrying a number is treated as an
attempted score. Any violation rejects the *entire* response as `FAILED`
rather than stripping the bad part and keeping the rest — a model
response that broke one rule isn't trusted to have followed the others
correctly. All scoring is `evals/trade_evaluator.py`, in plain
deterministic Python, computed from the category fields only.

Before any API call, `analyze()` checks both inputs are actually
`SUCCESS` — a failed capture or a failed market-data fetch returns a
`FAILED` analysis immediately, with no Claude request made at all (this
both saves money and stops the agent from reasoning about data that was
never actually retrieved).

The prompts (`prompts/system_prompt.md`, `prompts/analysis_prompt.md`)
explicitly instruct the model to prefer `HIGH` uncertainty and honest
"can't tell" language over a confident-sounding guess, and to never
phrase anything as an instruction to buy, sell, or otherwise place a
trade — consistent with this app never executing trades under any
circumstances.

## Evaluation engine design

`evals/trade_evaluator.py`'s `evaluate(agent_analysis, trade_params) ->
EvaluationResult` is a pure function: no AI call, no randomness, no
clock-dependent behavior. Same inputs always produce the same five
component scores and the same total. The full rubric — exactly what each
component reads and what earns 20 vs. 10 vs. 0 — is written out in
[docs/rubric.md](rubric.md); the short version:

- **Trend, Structure, Entry, Timing/Context** each read one or two of
  the agent's fixed-category fields (`trend_direction`+`trend_quality`,
  `structure_quality`, `setup_quality`, `context_risk` respectively) —
  words chosen from a small closed set, never prose. (Revised from an
  earlier version that scored these from prose length and keyword
  matching, which measured verbosity, not setup quality — see
  `docs/rubric.md`'s "What v1 got wrong.") The agent's prose fields
  (`analysis_text`, `trend_assessment`, `structure_assessment`,
  `setup_assessment`) still exist for a human reviewer to read; nothing
  in the evaluator reads them.
- **Risk/Reward** is computed arithmetically from the user's
  entry/stop/target — it never reads the agent's words at all. Missing
  or incoherent trade parameters (stop on the wrong side, zero risk
  distance) return a `FAILED` evaluation rather than a guessed ratio.
- The agent's `uncertainty` caps the four *subjective* components (not
  Risk/Reward) at 20/14/8 for LOW/MEDIUM/HIGH, applied per-component
  before summing — never as a post-hoc adjustment to the total, since
  the database's `CHECK` constraint requires `total_score` to exactly
  equal the sum of the five components.
- If the agent analysis itself failed, the evaluator returns a `FAILED`
  evaluation immediately and scores nothing.

This engine only scores — it does not decide pass/fail. Thresholds for
what score (combined with data freshness, RR minimums, and confidence)
is good enough to recommend are Milestone 9's guardrails, not this file.

## Guardrails design

`guardrails/rules.py`'s `evaluate_guardrails(capture_result,
market_data_result, agent_analysis, evaluation_result, trade_params) ->
GuardrailReport` runs eleven independent, deterministic checks — no AI
call, no randomness — every time, never short-circuiting on an earlier
failure, so the audit trail always shows the complete picture. Full
table of every rule, its threshold, and what happens when it fails is in
the Milestone 9 entry of [docs/iterations.md](iterations.md).

**Guardrails can only downgrade.** The eleven rules split into two
groups: seven "blocking" rules (capture/market-data/analysis/evaluation
each succeeding and being fresh, plus trade params being coherent) where
any failure means there's nothing meaningful to show a human at all —
those force `BLOCKED`. Four "review-forcing" rules (risk/reward meeting
its minimum, uncertainty not being `HIGH`, the score meeting its
minimum, and the data not being synthetic) where a failure means the
pipeline worked but the result isn't good, certain, or real enough to
skip a human's judgment — those force `REQUIRES_REVIEW`. If nothing
fails, the outcome is `READY_FOR_REVIEW`. There is no fourth state and
no code path that produces one — nothing in this system approves a run
without a human; that's Milestone 10.

**The `SYNTHETIC_DATA` rule is absolute.** If either the chart capture or
the market data came from DEMO mode, the run can never reach
`READY_FOR_REVIEW` — not even with a perfect 100 score and every other
rule passing (verified directly by a test). A run built on sample data
must never be presentable as a validated live one.

**Freshness is the one place "deterministic" includes a clock reading,
on purpose** — `CAPTURE_FRESH` and `MARKET_DATA_FRESH` compare
timezone-aware UTC timestamps (`captured_at`, and the market quote's
*source* timestamp, never a fetch time) against a `now` parameter that
defaults to the real clock but can be pinned by tests, so "same inputs,
same verdict" still holds exactly — the clock reading is an explicit
input, not an implicit ambient one.

All four thresholds (`CAPTURE_MAX_AGE_SECONDS`, `MARKET_DATA_MAX_AGE_
SECONDS`, `MIN_RISK_REWARD`, `MIN_TOTAL_SCORE`) come from `.env`, with
`MIN_TOTAL_SCORE`'s default (60) chosen deliberately between the
MEDIUM-uncertainty ceiling (76) and the HIGH-uncertainty ceiling (52) —
see the Milestone 9 entry in `docs/iterations.md` for the full reasoning.

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
