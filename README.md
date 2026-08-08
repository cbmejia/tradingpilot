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
- `guardrails/` — hard safety rules (RR, freshness, validity, confidence) the agent may never bypass
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
    timestamp=datetime.now(timezone.utc),
    error_message=None,
)
params = TradeParams(direction='long', entry=1.0950, stop=1.0900, target=1.1050)
print(evaluate(analysis, params))
"
```

See [docs/rubric.md](docs/rubric.md) for the full scoring table and the
same example worked out by hand.

## Status

Milestone 8 of 12: deterministic evaluation engine. See
[docs/iterations.md](docs/iterations.md).
