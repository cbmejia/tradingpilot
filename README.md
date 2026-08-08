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

## Approving or rejecting a run from `/docs`

Start the server (see above) and open **http://127.0.0.1:8000/docs**.

**Reject a run — works right now, no setup needed:**

1. Expand **`POST /runs`** → **Try it out** → paste:
   ```json
   {"symbol": "EURUSD", "timeframe": "1h", "direction": "long", "entry": 1.0950, "stop": 1.0900, "target": 1.1050}
   ```
   → **Execute**. Copy the `id` from the response.
2. Expand **`POST /runs/{run_id}/review`** → **Try it out** → paste the
   `id` into `run_id`, and in the request body:
   ```json
   {"decision": "REJECTED", "comment": "Trying it out."}
   ```
   → **Execute**. You'll get `200` back with the recorded decision.
3. Expand **`GET /runs/{run_id}`** → **Try it out** → same `run_id` →
   **Execute**. You should see: `status: "REJECTED"`, `completed_at` now
   set, `human_review` populated with your decision and comment, and a
   new `audit_events` entry with `event_type: "human_review_recorded"`.

**Approve a run** needs one extra step first, honestly: there's no
orchestrator yet (Milestones 5–9 built the capture/agent/eval/guardrail
tools standalone, not wired together — see `docs/architecture.md`), so a
run created through `POST /runs` has no guardrail results, and a run with
no guardrail results is treated the same as `BLOCKED` — you'll get a
`409` if you try to approve one directly. To actually see an approval
succeed, seed passing guardrail results for a run first (standing in for
what a future orchestrator will do automatically):

```bash
python -c "
from database.database import SessionLocal
from database import crud

RUN_ID = 'paste-a-real-run-id-here'
session = SessionLocal()
for name in ['CAPTURE_SUCCEEDED','CAPTURE_FRESH','MARKET_DATA_SUCCEEDED','MARKET_DATA_FRESH',
             'ANALYSIS_SUCCEEDED','EVALUATION_SUCCEEDED','RISK_REWARD_MINIMUM',
             'TRADE_PARAMS_VALID','UNCERTAINTY_ACCEPTABLE','SCORE_THRESHOLD','SYNTHETIC_DATA']:
    crud.add_guardrail_result(session, run_id=RUN_ID, guardrail_name=name, passed=True, reason='manual seed')
session.close()
print('seeded')
"
```

Then repeat step 3 above (`GET /runs/{run_id}`) to confirm
`guardrail_outcome: "READY_FOR_REVIEW"`, and step 2 with
`{"decision": "APPROVED", "comment": "..."}` — this time it succeeds.
Try either decision a second time on the same run and you'll get a `409`
— a decision is final, and the original is never overwritten.

## Status

Milestone 10 of 12: human approval and decision audit. See
[docs/iterations.md](docs/iterations.md).
