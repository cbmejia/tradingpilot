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
- `tools/` — `market_data.py` (`MarketDataProvider`/`DemoMarketDataProvider`/`LiveMarketDataProvider`/`MarketDataManager`, same pattern as `capture/`) and economic calendar (chart capture lives in `capture/` — see above)
- `evals/` — deterministic rubric scoring of the agent's analysis
- `guardrails/` — eleven deterministic checks (RR, freshness, validity, uncertainty, synthetic-data) that can only downgrade a run toward `REQUIRES_REVIEW` or `BLOCKED`, never approve one
- `database/` — SQLAlchemy models and persistence for the full audit trail
- `prompts/` — versioned markdown prompt templates
- `screenshots/` — captured chart images (`live/` and `demo/`)
- `logs/` — runtime logs
- `docs/` — architecture, the evaluation rubric ([rubric.md](docs/rubric.md)), testing, and iteration notes
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

## Trying the market data tool by hand

DEMO mode needs nothing beyond the steps above and never touches the
network:

```bash
python -c "from tools.market_data import get_market_data; r = get_market_data('EURUSD', mode='demo'); print(r)"
```

LIVE mode needs a free Alpha Vantage API key (free signup required, no
paid plan): get one at https://www.alphavantage.co/support/#api-key, put
it in `.env` as `MARKET_DATA_API_KEY=your-key-here`, then:

```bash
python -c "from tools.market_data import get_market_data; r = get_market_data('EURUSD', mode='live'); print(r)"
```

Without a key set, this fails cleanly (status `FAILED`, `price=None`,
and a message telling you where to get one) rather than making a request
at all.

## Trying the agent by hand

Needs a real Anthropic API key (get one at
https://console.anthropic.com/settings/keys), set in `.env` as
`ANTHROPIC_API_KEY=your-key-here`. Everything else can stay in DEMO mode
— this uses the committed demo chart and demo price data:

```bash
python -c "
from capture.manager import CaptureManager
from tools.market_data import MarketDataManager
from agents.trade_agent import TradeAgent

capture_result = CaptureManager(mode='demo').capture('EURUSD', '1h')
market_data_result = MarketDataManager(mode='demo').get_quote('EURUSD')
result = TradeAgent().analyze(capture_result, market_data_result)
print(result)
"
```

Without a key set, this fails cleanly (status `FAILED`, every analysis
field `None`, and a message pointing at the Anthropic console) rather
than fabricating an analysis.

## Scoring an evaluation by hand

Pure computation — no network, no API key needed at all:

```bash
python -c "
from datetime import datetime, timezone
from agents.trade_agent import AgentAnalysisResult, AgentAnalysisStatus, TradeParams
from evals.trade_evaluator import evaluate

analysis = AgentAnalysisResult(
    status=AgentAnalysisStatus.SUCCESS,
    analysis_text='Price has been grinding higher against a rising trendline with clean structure.',
    trend_assessment='Uptrend with a clear series of higher highs and higher lows.',
    structure_assessment='Stair-step structure, minimal overlap between recent candles.',
    setup_assessment='Pullback to the trendline, holding as support, a readable entry point.',
    uncertainty='MEDIUM',
    trend_direction='UP',
    trend_quality='STRONG',
    structure_quality='CLEAN',
    setup_quality='ACCEPTABLE',
    context_risk='LOW',
    timestamp=datetime.now(timezone.utc),
    error_message=None,
)
params = TradeParams(direction='long', entry=1.0950, stop=1.0900, target=1.1050)
print(evaluate(analysis, params))
"
```

See [docs/rubric.md](docs/rubric.md) for the full scoring table and the
same example worked out by hand.

## Checking guardrails by hand

Also pure computation — no network, no API key needed. This builds a
`BLOCKED` example (a 2-hour-old chart capture) and prints every rule's
pass/fail result, not just the final outcome:

```bash
python -c "
from datetime import datetime, timedelta, timezone
from capture.base import CaptureMode, CaptureResult, CaptureStatus
from tools.market_data import MarketDataMode, MarketDataStatus, MarketQuote
from agents.trade_agent import AgentAnalysisResult, AgentAnalysisStatus, TradeParams
from evals.trade_evaluator import evaluate
from guardrails.rules import evaluate_guardrails

now = datetime.now(timezone.utc)
capture = CaptureResult(
    mode=CaptureMode.LIVE, symbol='EURUSD', timeframe='1h',
    screenshot_path='screenshots/live/EURUSD_1h_old.png',
    captured_at=now - timedelta(hours=2), status=CaptureStatus.SUCCESS, error_message=None,
)
market_data = MarketQuote(
    mode=MarketDataMode.LIVE, symbol='EURUSD', price=1.0950,
    timestamp=now - timedelta(seconds=10), source='alpha_vantage',
    status=MarketDataStatus.SUCCESS, error_message=None,
)
analysis = AgentAnalysisResult(
    status=AgentAnalysisStatus.SUCCESS,
    analysis_text='Uptrend.', trend_assessment='Up.', structure_assessment='Clean.', setup_assessment='Good.',
    uncertainty='LOW', trend_direction='UP', trend_quality='STRONG', structure_quality='CLEAN',
    setup_quality='TEXTBOOK', context_risk='LOW', timestamp=now, error_message=None,
)
params = TradeParams(direction='long', entry=1.0950, stop=1.0900, target=1.1050)
evaluation = evaluate(analysis, params)

report = evaluate_guardrails(capture, market_data, analysis, evaluation, params, now=now)
print('outcome:', report.outcome)
for c in report.checks:
    print(f'  {c.name}: {\"PASS\" if c.passed else \"FAIL\"} -- {c.reason}')
"
```

Change `captured_at=now - timedelta(hours=2)` to
`captured_at=now - timedelta(seconds=15)` to see the same run reach
`READY_FOR_REVIEW` instead. See the Milestone 9 entry in
[docs/iterations.md](docs/iterations.md) for the full table of all
eleven rules, their thresholds, and what each one does on failure.

## Running a full analysis pipeline by hand

Start the server (see above) and open **http://127.0.0.1:8000/docs**.
This is the real end-to-end path — `POST /runs/{run_id}/analyze`
(Milestone 10.5) actually runs capture → market data → agent →
evaluation → guardrails and persists every step, synchronously, so the
response already reflects the finished run.

1. Expand **`POST /runs`** → **Try it out** → paste:
   ```json
   {"symbol": "EURUSD", "timeframe": "1h", "direction": "long", "entry": 1.0950, "stop": 1.0900, "target": 1.1050}
   ```
   → **Execute**. Copy the `id` from the response.
2. Expand **`POST /runs/{run_id}/analyze`** → **Try it out** → paste the
   `id` into `run_id` → **Execute** (no request body — this endpoint
   takes none). With `CAPTURE_MODE=demo` and `MARKET_DATA_MODE=demo` (the
   defaults in `.env.example`), this uses the committed demo chart and
   demo price, no network calls for either. If `ANTHROPIC_API_KEY` is set
   in `.env`, this makes one real Claude call; if it's unset, the agent
   stage fails cleanly (see "Trying the agent by hand" above) and the run
   still completes, `BLOCKED` at `ANALYSIS_SUCCEEDED`, with the real
   reason recorded directly on the `analyses[0]` record (`status:
   "FAILED"`, `error_message: "..."`, every qualitative field `null`,
   including `trend_direction`/`trend_quality`/`structure_quality`/
   `setup_quality`/`context_risk`) — not only in the audit trail.
   `evaluations[0]` shows the same shape (`status: "FAILED"`, every score
   field `null`, never zero, including `risk_reward_ratio`). On a
   successful analysis, `analyses[0]` carries those same five categorical
   fields populated (e.g. `trend_direction: "UP"`, `trend_quality:
   "STRONG"`) so you can trace `evaluations[0]`'s `trend_score`/
   `structure_score`/`entry_score`/`timing_context_score` back to the
   actual observation each one came from, and `evaluations[0]`'s
   `risk_reward_ratio` (e.g. `2.0`) gives the same traceability for
   `risk_reward_score`'s banded 0/10/20. `market_data[0]` always carries
   `mode` (`"LIVE"`/`"DEMO"`) directly, not just inferable from `source`.
   Either way you'll get `200` back with the finished run: captures,
   market data, analysis, evaluation, all eleven guardrail results, and
   `guardrail_outcome`.
3. Expand **`GET /runs/{run_id}`** → **Try it out** → same `run_id` →
   **Execute** to see the same thing again, plus the full `audit_events`
   trail in order (`analysis_started`, `capture_started`/
   `capture_finished`, ... `analysis_finished`).
4. Expand **`POST /runs/{run_id}/review`** → **Try it out** → same
   `run_id`, request body:
   ```json
   {"decision": "REJECTED", "comment": "Trying it out."}
   ```
   → **Execute** — always succeeds, on any run, in any state. To approve
   instead, the outcome from step 2 must not be `BLOCKED`; a DEMO run can
   never be approved either way, since `SYNTHETIC_DATA` always forces
   `REQUIRES_REVIEW` for DEMO-sourced data (see
   [docs/architecture.md](docs/architecture.md)) — `REQUIRES_REVIEW` can
   still be approved, only `BLOCKED` cannot.
5. Try step 2 (`/analyze`) or step 4 (`/review`) a second time on the same
   `run_id` and you'll get `409` both times — an analysis, like a
   decision, is final and never silently re-run or overwritten.

## Status

Milestone 10.5 of 12: orchestrator wires the 12-step pipeline, plus three
follow-up fixes — a failed agent analysis or evaluation is stored as a
proper row (`status`/`error_message`, matching `captures`/`market_data`)
instead of only being described in the audit trail; a successful
analysis stores the five categorical fields the rubric actually scores
from; and `market_data.mode` plus `evaluations.risk_reward_ratio` close
out the schema audit, so every component score and every LIVE/DEMO claim
now traces back to a real stored value, not an inference. See
[docs/iterations.md](docs/iterations.md).
