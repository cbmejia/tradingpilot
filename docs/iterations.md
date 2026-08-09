# Iterations

Log of build milestones for TradePilot AI. Twelve planned milestones total —
see the roadmap at the bottom.

## Milestone 1 — Frontend UI shell

React + TypeScript (Vite) dashboard shell: header, six-card layout with
designed empty states for signal, chart capture, market snapshot, economic
calendar, guardrails, and history. No live data, no backend calls.

## Milestone 2 — Architecture and folder structure

Wrote `docs/architecture.md`: component responsibilities, the 12-step
workflow, the LIVE/DEMO screenshot capture design, data flow, and the
non-negotiable safety principles (no execution, agent never emits a score,
guardrails are deterministic, every run is fully audited). Added the
`backend/api/` sub-package (routers), `backend/orchestrator.py`,
`backend/schemas.py`, and package `__init__.py` files where missing. No
business logic yet — placeholders only.

**Deviation flagged:** Milestone 1 shipped the frontend shell with
hand-rolled CSS. The stack now specifies Tailwind. Rather than churn the
shell twice, Tailwind is added when the UI milestone (11) is built out.

## Milestone 3 — Database schema and audit trail

Built the SQLite database layer with SQLAlchemy:

- `database/database.py` — engine, session factory, `init_db()`. SQLite
  foreign-key enforcement turned on explicitly (off by default in SQLite).
- `database/models.py` — 8 tables: `Run` (parent row for one analysis) and
  seven child tables that each record one workflow step: `Capture`,
  `MarketData`, `AgentAnalysis`, `Evaluation`, `GuardrailResult`,
  `HumanReview`, `AuditEvent`. Every child table points back at its `Run`
  via `run_id`, so the full history of a run can always be reconstructed.
- `database/crud.py` — the only sanctioned functions for writing rows.
  `add_evaluation()` has no `total_score` parameter at all — it always
  computes the total as the sum of the five component scores, so nothing
  (including the future AI agent) has a path to writing the final score
  directly.
- `database/init_db.py` — run with `python -m database.init_db` to create
  `database/tradepilot.db` and print the tables it made.
- `tests/test_database.py` — 14 tests covering initialization and every
  table (create a run, save a capture success/failure, save market data
  success/failure, save an analysis, save an evaluation and confirm the
  total is computed, confirm `add_evaluation` has no `total_score`
  parameter, save a guardrail result, save a human review, save an audit
  event, and walk a full run's relationships).
- `pytest.ini` added at the repo root so `pytest` resolves `database.*`
  imports.
- `backend/requirements.txt` now pins `sqlalchemy`, `python-dotenv`,
  `pytest`.

All 14 tests pass. `python -m database.init_db` was run for real and
created `database/tradepilot.db` with all 8 tables and the `captures.run_id
-> runs.id` foreign key correctly in place (verified directly with
`sqlite3`).

No FastAPI routes, no orchestrator logic, no capture/market-data/agent/
eval/guardrail implementations, and no frontend changes were made — this
milestone is the database layer only.

## Milestone 3 hardening — UTC timestamps, score boundary test, gitignore

A verification pass over Milestone 3 found and closed two real gaps:

- **Timestamps silently lost their timezone.** `_now()` in `models.py`
  already used `datetime.now(timezone.utc)`, but SQLite has no native
  datetime type — SQLAlchemy's default `DateTime` column stores it as
  plain text and drops the UTC offset on write, so every timestamp came
  back out of the database as naive (verified empirically: a `Run`'s
  `created_at` had `tzinfo=None` immediately after `session.refresh()`).
  Added `database/types.py` (`TZDateTime`, a `TypeDecorator`) that
  requires timezone-aware input and always returns UTC-aware output.
  Applied it to all 9 datetime columns across every model. This matters
  because the future data-freshness guardrail (Milestone 9) will subtract
  `captured_at` from "now" — Python raises an error subtracting an aware
  datetime from a naive one, so this bug would have surfaced there as a
  guardrail crash rather than a database problem.
- **The evaluation score boundary was Python-convention-only, not
  database-enforced.** `crud.add_evaluation()` never accepted a
  `total_score` parameter, but constructing `Evaluation(...)` directly
  (bypassing `crud.py`) could still set any `total_score` — confirmed
  empirically. Added a SQLite `CHECK` constraint
  (`ck_evaluations_total_score_is_sum_of_components`) so the database
  itself rejects any row, however it's created, where `total_score` isn't
  exactly the sum of the five component scores.

Also added: `*.sqlite` to `.gitignore` (`*.sqlite3` and `*.db` were
already covered; `.venv/` already was too). Confirmed the tradepilot repo
has zero references to Simple_budget anywhere in its files, and gave it
its own `.claude/launch.json` (relative paths only) so a session rooted
directly in `tradepilot/` doesn't need anything from Simple_budget to
preview the frontend.

Four tests added to `tests/test_database.py` (18 total, up from 14):
timestamp round-trip for both a caller-supplied timestamp (`Capture.
captured_at`) and an auto-generated one (`Run.created_at`); the
`add_evaluation` rejection test; and the database-level `CHECK` constraint
test.

## Pre-Milestone-4 verification

Two checks requested before starting the API, both done by inspecting the
actual runtime behavior rather than just the source:

- **Score column types.** `trend_score`, `structure_score`, `entry_score`,
  `risk_reward_score`, `timing_context_score`, and `total_score` are all
  `Integer` (confirmed by inspecting the compiled column types, not just
  the `Mapped[int]` annotation). No floating-point rounding risk for the
  `CHECK` constraint — nothing changed.
- **`PRAGMA foreign_keys=ON`.** Confirmed it's applied via
  `@event.listens_for(Engine, "connect")` in `database/database.py`,
  registered on the SQLAlchemy `Engine` class itself, so it fires for
  every connection on every engine in the process, not just the app's
  main one. Verified with a brand-new, independent in-memory engine that
  a foreign-key violation is still rejected. Added a permanent regression
  test, `test_foreign_keys_are_enforced_on_a_fresh_engine`, to
  `tests/test_database.py` (19 tests total now, up from 18).

## Milestone 4 — Backend API and run lifecycle

Built the FastAPI backend that creates and reads runs. No pipeline tools
(capture, market data, agent, evaluation, guardrails) exist yet and none
were built or faked — creating a run only writes a database record.

- `backend/config.py` — the one place that reads settings from `.env`
  (host/port, capture/market-data mode, Claude model, CORS origins). No
  hardcoded or invented secrets.
- `backend/schemas.py` — pydantic request/response models for every
  endpoint, including a fixed set of allowed timeframes and a `gt=0`
  constraint on entry/stop/target. No schema anywhere accepts a total
  evaluation score from the client.
- `backend/api/routes_health.py` — `GET /health`, confirms the database
  is reachable with a real `SELECT 1`.
- `backend/api/routes_runs.py` — `POST /runs` (creates a `Run` with
  status `CREATED` and writes a `run_created` audit event — nothing
  else), `GET /runs` (newest-first, paged), `GET /runs/{id}` (the run
  plus every child table — the full audit trail; 404 if missing).
- `backend/main.py` — the FastAPI app: CORS restricted to
  `localhost:5173`/`5174`, and a startup step that calls `init_db()` so a
  fresh clone works without a manual step.
- `database/crud.py` — added `get_run()` and `list_runs()` (read-only,
  alongside the existing write functions).
- `tests/conftest.py` — points the app's fallback database at a
  throwaway file the moment pytest starts, before anything else can
  import `database.database` and bind to the real file.
- `tests/test_api.py` — 11 tests: health check, valid run creation,
  minimal (symbol + timeframe only) run creation, invalid timeframe
  (422), negative and zero entry/stop (422), 404 on a missing run,
  newest-first listing, paging, a full run showing its creation audit
  event, and timezone-aware ISO 8601 timestamps in responses.

Verified against the real running server too, not just the test client:
started `uvicorn backend.main:app`, and confirmed `/health`, `POST
/runs`, `GET /runs`, a rejected invalid timeframe, and `/docs` (200) all
work. The dev database was reset to empty afterward so first-run
instructions match a clean clone.

All 30 tests pass (19 database + 11 API). No frontend changes, no
orchestrator logic, no human-review endpoint (that's Milestone 10).

## Milestone 5 — Chart capture tool (LIVE and DEMO providers)

Built the chart capture tool in `capture/` (a deliberate deviation from
the original `tools/tradingview_capture.py` location — that file now
just points here; `docs/architecture.md` updated to match). DEMO mode was
built first and completely before any Playwright code was written, per
the instruction.

- `capture/base.py` — `CaptureProvider` (the interface), `CaptureResult`
  (`mode`, `symbol`, `timeframe`, `screenshot_path`, `captured_at`,
  `status`, `error_message`), `CaptureMode`/`CaptureStatus` enums, and
  `sanitize_component()` (rejects path-traversal attempts in a
  symbol/timeframe before it ever touches the filesystem).
- `capture/demo_provider.py` — `DemoProvider`. Reads a real file from
  `screenshots/demo/`, matched deterministically by symbol + timeframe
  (`SYMBOL_timeframe.png`). No network access. Fails clearly — never
  substitutes another pair's chart — if the exact fixture doesn't exist.
- `screenshots/demo/EURUSD_1h.png` and `screenshots/demo/GBPUSD_4h.png` —
  two committed fixture images so DEMO mode works on a fresh clone with
  no network access. Generated as plain labeled placeholder charts (a
  simple abstract bar series, gridlines, and a large "SAMPLE IMAGE — NOT
  REAL MARKET DATA" banner baked into the image itself) rather than
  anything styled to resemble a real TradingView screenshot, so they can
  never be mistaken for genuine market data.
- `capture/live_provider.py` — `LiveProvider`. Drives headless Chromium
  via Playwright, navigates to a TradingView chart URL, waits a fixed 2
  seconds for it to render (not an infinite wait), and screenshots to
  `screenshots/live/` with a symbol+timeframe+UTC-timestamp filename. Any
  failure (missing browser binary, timeout, page error) returns a
  `FAILED` result with the real error — there is no code path here that
  calls `DemoProvider`. Uses no TradingView credentials (public chart
  viewing doesn't require login); `TRADINGVIEW_USERNAME`/`PASSWORD`
  remain available as unused placeholders in `.env.example` for later if
  a login flow ever becomes necessary.
- `capture/manager.py` — `CaptureManager`. Reads `CAPTURE_MODE`, picks
  exactly one provider, always uses that same one. Also verifies every
  result's `mode` actually matches the mode it's running in and raises
  `RuntimeError` if not — a structural backstop against a provider bug
  ever mislabeling a capture's true source.
- `.gitignore` fixed: it was ignoring `screenshots/demo/*` too (a bug from
  Milestone 1) — demo fixtures need to be committed, so only
  `screenshots/live/*` is ignored now.
- `tests/test_capture.py` — 13 tests, none touching the network: demo
  success/determinism/timezone-aware timestamp, demo failure on an
  unknown symbol (and on a path-traversal attempt), a manager-level fake
  LIVE failure proving no demo substitution occurs, a mismatched-mode
  provider proving the manager's backstop raises, and two `LiveProvider`
  tests that mock `playwright.sync_api.sync_playwright` itself so a real
  failure path is exercised with zero network activity.

Manually verified from the terminal (see README for the exact commands):
a real demo capture returns a `SUCCESS`/`DEMO` result pointing at the
committed fixture; a real LIVE attempt (browser binaries deliberately not
installed) fails cleanly with Playwright's own "run `playwright install`"
error, mode stays `LIVE`, status is `FAILED`, and no network call is made
(the browser can't even launch without its binary, so it never reaches
`page.goto()`).

Not wired into the orchestrator, the agent, or the frontend, and no
capture API endpoint was added — this tool is standalone and callable on
its own, exactly as instructed. All 43 tests pass (19 database + 11 API +
13 capture).

## Milestone 5 follow-up — LiveProvider validity check

Closed a real gap: `LiveProvider` reported `SUCCESS` for any screenshot at
all, including a blank page, a cookie/consent banner, or a broken render
— none of which are an actual chart.

- `capture/live_provider.py` — before `page.screenshot()`, waits for a
  `canvas` element (configurable via `chart_selector`) to actually appear;
  if it never does, returns `FAILED` with a clear message instead of
  screenshotting whatever's there. After the screenshot, a new
  `screenshot_is_valid()` check opens the image (Pillow), converts to
  grayscale, and rejects it if the pixel-brightness standard deviation is
  below a threshold (default 3.0) — a blank or near-uniform image has
  almost no variance; a real chart (candles, gridlines, text) always has
  much more. Either check failing returns `FAILED`, never `SUCCESS`, and
  never a demo image — the invalid file stays on disk (for inspection)
  but `screenshot_path` in the result is `None`, same as any other
  failure.
- Pillow added to `backend/requirements.txt` as a real dependency now
  (previously only used transiently to generate the demo fixtures). It's
  imported lazily inside the validity check, so DEMO mode still needs
  zero extra installs.
- `tests/test_capture.py` — 4 tests added (17 total, up from 13): missing
  chart element, a truly blank screenshot, a near-uniform (not just
  solid-color) screenshot, and a regression guard confirming a
  realistic-looking screenshot (the committed demo fixture, reused as a
  stand-in) still passes. All four mock Playwright's browser/page objects
  directly — no real browser, no network.

## Milestone 6 — Market data tool (LIVE and DEMO providers)

Built `get_market_data()` in `tools/market_data.py`, structured like
`capture/`: one interface (`MarketDataProvider`), a `LiveMarketDataProvider`
and a `DemoMarketDataProvider`, and a `MarketDataManager` that picks one
based on `MARKET_DATA_MODE` and never falls back between them. Kept as a
single file (per the instruction), not a package like `capture/` — small
enough not to need splitting up.

**The rule that mattered most:** if the source fails, times out, doesn't
know the symbol, or sends back something unparseable, the result is
`FAILED` with `price=None` — never an invented, estimated, or
carried-forward number. Every failure path in `LiveMarketDataProvider`
returns `price=None`; there is no line of code anywhere in this file that
assigns a price from anywhere other than a successfully parsed API
response.

- **API chosen: Alpha Vantage**, `CURRENCY_EXCHANGE_RATE` endpoint. Free
  tier, no paid plan needed — but it does need a free signup for an API
  key (`https://www.alphavantage.co/support/#api-key`). Picked over a
  no-signup option (Frankfurter) specifically because it reports a real
  quote timestamp, not a once-a-day reference rate — the point of
  recording a timestamp at all is knowing how old the data is.
- `tools/market_data.py` — `MarketQuote` (`mode`, `symbol`, `price`,
  `timestamp`, `source`, `status`, `error_message`); `timestamp` is
  always the source's own reported quote time, parsed from Alpha
  Vantage's `"6. Last Refreshed"` + `"7. Time Zone"` fields (rejected if
  the source ever reports a non-UTC zone, rather than guessing an
  offset) — never `datetime.now()`. Hard 10-second timeout on the HTTP
  request.
- `tools/demo_market_data.json` — fixed sample quotes for `EURUSD` and
  `GBPUSD`, each with its own fixed (not "now") timestamp, so DEMO mode's
  "source time" behaves the same way LIVE's does: a real recorded time,
  not a fetch time. `source="demo_fixture"` marks these clearly as
  sample data. An unrecognized symbol fails cleanly, never substituting
  another pair's price.
- `.env.example` — `MARKET_DATA_API_KEY` now documented as the (free,
  signup-required) Alpha Vantage key; `MARKET_DATA_BASE_URL` wired up as
  an optional override (defaults to Alpha Vantage's URL if unset).
- `requests` added to `backend/requirements.txt` (LIVE mode only; DEMO
  mode needs no extra installs, same pattern as `capture/`).
- `tests/test_market_data.py` — 18 tests, none touching the network: demo
  success/determinism/unknown-symbol-failure/timezone-aware timestamp,
  manager mode handling and the never-falls-back-to-demo guarantee, and
  for `LiveMarketDataProvider` (all via mocking `requests.get` directly):
  missing API key (fails before any request is even attempted), timeout,
  malformed response body, a non-numeric exchange rate, an
  unknown-symbol error response, a non-UTC source timezone, an invalid
  symbol shape, and — the key test — a fixed historical
  `"6. Last Refreshed"` value that proves the returned timestamp is the
  source's time, not `datetime.now()` at fetch time.

Manually verified from the terminal: a demo fetch returns the fixed
EURUSD sample quote; a live fetch (no `MARKET_DATA_API_KEY` set) fails
cleanly with a message telling you where to get one, `price=None`, and no
network call made.

Not wired into the orchestrator, the agent, or the frontend, and no
market-data API endpoint was added. All 65 tests pass (19 database + 11
API + 17 capture + 18 market data).

## Milestone 7 — Agent loop with qualitative analysis

Built `agents/trade_agent.py`: `TradeAgent.analyze(capture_result,
market_data_result, trade_params)` sends the screenshot and market data
to Claude and returns an `AgentAnalysisResult` — words only, never a
number that could function as a score.

**THE HARD BOUNDARY, and how it's actually enforced (not just asked
nicely):** `_parse_response()` requires Claude's reply to be a JSON
object with exactly five expected fields, all text
(`analysis_text`/`trend_assessment`/`structure_assessment`/
`setup_assessment` as strings, `uncertainty` as one of `LOW`/`MEDIUM`/
`HIGH`). If the response contains any *extra* field whose value is a
number (e.g. a smuggled `"confidence_score": 87`), or if `uncertainty`
or any text field isn't a string, the **entire response is rejected** —
not partially trusted. A rejected response means every field on the
result is `None`; there is no code path where a stripped-but-otherwise-
accepted response reaches storage. This was a deliberate choice between
"strip the bad field and keep the rest" and "reject the whole thing" —
reject was chosen because a model that ignored the no-scores instruction
once can't be trusted to have followed the rest of the instructions
correctly either.

- **Input validation before any API call.** If `capture_result.status`
  or `market_data_result.status` isn't `SUCCESS`, `analyze()` returns a
  `FAILED` result immediately and never touches the Claude client —
  confirmed in tests via `client.messages.create.assert_not_called()`.
  This is the same "no fabricated data" principle as `capture/` and
  `tools/market_data.py`: never reason about inputs that don't exist.
- **The agent is allowed — and told — to not know.** Both prompts
  explicitly instruct HIGH uncertainty (and "insufficient information"
  language) whenever the chart is unclear, and state plainly that a
  confident-sounding read of an unclear chart is a failure, not a
  success. A test confirms a HIGH-uncertainty, "not readable" response is
  accepted normally, not treated as some kind of error.
- **Never phrases anything as an instruction to trade.** Both prompt
  files state this as a hard rule (never say "buy"/"sell"/"enter"/"exit",
  never phrase output as an instruction to act) — the agent describes
  what's observable, nothing more. Enforcement here is at the prompt
  level (Claude's own compliance), the same way the "no execution"
  invariant for the whole app is architectural, not a runtime check on
  free text.
- `prompts/system_prompt.md` / `prompts/analysis_prompt.md` — real,
  editable Markdown files (not hardcoded strings), read fresh from disk
  on every call. `analysis_prompt.md` is a template rendered per-request
  with the symbol, timeframe, price, quote timestamp, source, and any
  trade params (each defaulting to "not provided" rather than being
  omitted or guessed).
- **API errors, timeouts, and a missing key are all `FAILED`, never a
  fabricated analysis.** A 60-second hard timeout on the Claude call;
  `anthropic.APITimeoutError` and the broader `anthropic.APIError`
  (covers rate limits and everything else) are both caught and turned
  into a `FAILED` result carrying the real error text. Reads
  `ANTHROPIC_API_KEY` from `.env` only — already present as a placeholder
  from Milestone 2, now documented with the signup URL.
- `tests/test_agent.py` — 20 tests, no real API calls: failed
  capture/market-data short-circuits (with the "never called the API"
  assertion), a well-formed response mapping correctly, a markdown-fenced
  response still parsing, uncertainty case-normalization, a HIGH-
  uncertainty "can't tell" response being accepted normally, four
  variations of the hard-boundary rejection (extra numeric field, numeric
  uncertainty, numeric text field, percentage-style uncertainty string),
  three malformed-response failures (not JSON, missing field, invalid
  uncertainty word), a real `anthropic.APITimeoutError` and a real
  `anthropic.APIConnectionError` (both constructed directly against the
  SDK's actual exception classes, no network), a missing-API-key
  short-circuit, timezone-aware timestamp on success and `None` timestamp
  on failure, a prompt-content sanity check, and the module-level
  `analyze()` convenience function.

Manually verified from the terminal: a real DEMO-mode capture + DEMO-mode
market data feeding into the real `TradeAgent` (no `ANTHROPIC_API_KEY`
set yet) fails cleanly with `status=FAILED` and a message pointing at the
Anthropic console — no fabricated analysis, exactly as designed. A real
model call (once a key is available) will be added to this log as a
follow-up.

Not wired into the orchestrator or the frontend, and no agent API
endpoint was added. All 85 tests pass (19 database + 11 API + 17 capture
+ 18 market data + 20 agent).

## Milestone 8 — Deterministic evaluation engine

Built `evals/trade_evaluator.py`'s `evaluate(agent_analysis,
trade_params) -> EvaluationResult`: five components, 20 points each, 100
total. Full rubric written out in [docs/rubric.md](rubric.md) — every
component's source field and exact scoring bands, in a plain table, no
code-reading required.

- **Deterministic by construction.** No AI call anywhere in the file, no
  randomness, no clock reads. Four components (Trend, Structure, Entry,
  Timing/Context) each apply the identical 3-band text rule
  (`_score_subjective_text`) to one agent field
  (`trend_assessment`/`structure_assessment`/`setup_assessment`/
  `analysis_text`): substantive text (≥15 chars, no "can't tell"
  language) scores 20, thin text scores 10, empty or explicitly negative
  text scores 0.
- **Risk/Reward is arithmetic, not a reading of the agent's words.**
  `_compute_risk_reward()` computes `RR = reward distance / risk
  distance` from the user's entry/stop/target, honoring direction (LONG:
  risk = entry − stop, reward = target − entry; SHORT: mirrored). Missing
  entry/stop/target/direction, a stop or target on the wrong side, or a
  zero risk distance all return a `FAILED` evaluation with a plain-English
  reason — never a guessed ratio. Scored 20 (RR ≥ 2.0), 10 (1.0 ≤ RR <
  2.0), or 0 (RR < 1.0).
- **`total_score` is always the sum of the five components** — the exact
  same formula the database's `ck_evaluations_total_score_is_sum_of_
  components` CHECK constraint enforces. `evaluate()` has no `total_score`
  parameter at all (confirmed by a test inspecting its signature, same
  pattern as `crud.add_evaluation`'s Milestone 3 test).
- **Uncertainty caps the four subjective components, not the total.**
  `UNCERTAINTY_CAPS = {"LOW": 20, "MEDIUM": 14, "HIGH": 8}`, applied via
  `min(raw_score, cap)` to each subjective component *before* summing.
  Risk/Reward is exempt — it's a fact about numbers the user typed, not a
  reading of an ambiguous chart. Verified the resulting ceilings match
  exactly what was specified: LOW 100, MEDIUM 76, HIGH 52 (4 × cap + the
  full 20 from Risk/Reward, which can still score 20 even under HIGH
  uncertainty — a direct test confirms Risk/Reward's score and ratio are
  identical across all three uncertainty levels on the same trade
  params).
- **A failed agent analysis is never scored.** `evaluate()` checks
  `agent_analysis.status` first, before even attempting the RR
  calculation, and returns a `FAILED` evaluation with every score field
  `None`.
- `tests/test_evaluation.py` — 26 tests: determinism (same input twice →
  identical result), total-equals-sum-of-five for all three uncertainty
  levels, the no-total-parameter signature test, RR computed correctly
  for both LONG and SHORT, RR's three score bands, four RR failure modes
  (stop wrong side, target wrong side, zero risk distance, each of
  direction/entry/stop/target missing individually, and no trade params
  at all), a failed agent analysis short-circuiting before any scoring,
  the three subjective-text score bands (substantive/thin/negative
  phrase) plus empty text, higher-uncertainty-scores-lower on identical
  input, the three documented ceilings (100/76/52) verified exactly
  component-by-component, Risk/Reward's invariance across uncertainty
  levels, and a sanity check that `UNCERTAINTY_CAPS` matches what's
  documented.

Manually ran one example from the terminal (MEDIUM uncertainty, a LONG
setup with RR = 2.0): all four subjective components capped from 20 to
14, Risk/Reward scored the full 20, total 76 — matches the worked example
in `docs/rubric.md` exactly.

Not wired into the orchestrator or the frontend, and no evaluation API
endpoint was added. Guardrails (pass/fail thresholds) are explicitly out
of scope here — this engine scores, it doesn't block; that's Milestone 9.
All 111 tests pass (19 database + 11 API + 17 capture + 18 market data +
20 agent + 26 evaluation).

## Milestone 8 revision — category-based rubric replaces the length heuristic

**What v1 got wrong.** Four of the five components (Trend, Structure,
Entry, Timing/Context) scored the agent's *prose*: substantive text
(≥15 characters, no "can't tell" phrasing) scored 20, thin text scored
10, empty or negative-phrase text scored 0. That measures verbosity, not
setup quality — a mediocre setup described fluently scored exactly the
same as a genuinely good one described just as fluently. Only
Risk/Reward was ever genuinely scored, because it's real arithmetic; the
other 80 of 100 possible points were, in effect, measuring how much the
model chose to write. Milestone 9's guardrail thresholds would have been
gating on nothing meaningful.

**The fix, spanning both Milestone 7 and Milestone 8 together:**

- **`agents/trade_agent.py`** — the agent now emits five additional
  fixed-category fields alongside its existing prose (which stays,
  unchanged, for a human reviewer to read — it just stops driving any
  score): `trend_direction` (`UP`/`DOWN`/`SIDEWAYS`/`UNCLEAR`),
  `trend_quality` (`STRONG`/`MODERATE`/`WEAK`/`UNCLEAR`),
  `structure_quality` (`CLEAN`/`MIXED`/`CHOPPY`/`UNCLEAR`),
  `setup_quality` (`TEXTBOOK`/`ACCEPTABLE`/`MARGINAL`/`NONE`/`UNCLEAR`),
  `context_risk` (`LOW`/`MODERATE`/`ELEVATED`/`UNCLEAR`). Every field's
  allowed set includes `UNCLEAR`, and both prompts now explicitly tell
  the model to use it rather than guess. `_parse_response()` validates
  each category field is a string and a member of its own allowed set —
  an unrecognized value (or a number) rejects the whole response as
  `FAILED`; it is never coerced to `UNCLEAR` or anything else on the
  model's behalf. `EXPECTED_FIELDS` grew from 5 to 10 JSON keys.
- **`evals/trade_evaluator.py`** — rewritten to score Trend, Structure,
  Entry, and Timing/Context purely from these category fields via fixed
  lookup tables (`TREND_QUALITY_SCORES`, `STRUCTURE_QUALITY_SCORES`,
  `SETUP_QUALITY_SCORES`, `CONTEXT_RISK_SCORES`) — never from string
  length, never from keyword matching on prose. `_score_subjective_text`,
  `NEGATIVE_PHRASES`, and `MIN_SUBSTANTIVE_LENGTH` are gone entirely,
  replaced by `_score_trend()` (reads `trend_direction` +
  `trend_quality` together — direction gates whether there's a trend to
  credit at all; SIDEWAYS or either field UNCLEAR scores 0) and
  `_score_from_map()` (the shared lookup for the other three, single-
  field components). `context_risk`'s mapping is deliberately inverted
  from the others — LOW risk scores highest, ELEVATED scores 0 — since
  it's the one field where the "best" word describes safety, not
  quality. Everything else is untouched: determinism, integer-only
  scores, uncertainty caps (LOW 20 / MEDIUM 14 / HIGH 8) applied
  per-component before summing, Risk/Reward's exemption from the cap,
  `total_score` always the sum of the five components, and the
  100/76/52 ceilings — all verified unchanged by the existing v1 tests,
  which still pass without modification to their assertions.
- **`docs/rubric.md`** — rewritten with the full category-to-points
  table per component, a corrected worked example, and a new "What v1
  got wrong" section explaining the flaw and the fix for anyone reading
  the rubric later without this conversation's context.
- **Tests** — `tests/test_agent.py` gained 5 tests (out-of-set
  `trend_direction`/`setup_quality` rejected, a missing categorical
  field rejected, a numeric categorical field rejected, case
  normalization to uppercase) plus updated its existing well-formed and
  HIGH-uncertainty fixtures to include valid category values (25 total,
  up from 20). `tests/test_evaluation.py` gained 9 tests — most
  importantly `test_prose_length_does_not_affect_score_when_categories_
  match`, which runs the *same* categories through one analysis with
  one-word prose and another with multi-sentence prose and asserts
  identical scores on every component — plus a band test per category
  field, an all-`UNCLEAR` test confirming every component scores 0, and
  an out-of-set-value defense-in-depth test at the evaluator level (32
  total, up from 26).

Re-ran the exact Milestone 8 worked example (MEDIUM uncertainty, LONG
setup, RR = 2.0, all "best" categories) by hand: total is still 76 — the
same number as before the revision, because that example's categories
happen to correspond to what its old prose implied. The difference is
now structural: that 76 is earned by `STRONG`/`CLEAN`/`ACCEPTABLE`/`LOW`,
not by paragraph length.

All 122 tests pass (19 database + 11 API + 17 capture + 18 market data +
25 agent + 32 evaluation).

## Milestone 9 — Deterministic guardrails

Built `guardrails/rules.py`'s `evaluate_guardrails(capture_result,
market_data_result, agent_analysis, evaluation_result, trade_params) ->
GuardrailReport`: eleven independent, deterministic checks, always all
eleven evaluated (no short-circuiting), reduced to one of exactly three
outcomes — `BLOCKED`, `REQUIRES_REVIEW`, `READY_FOR_REVIEW`. There is no
fourth state and no code path that approves anything; that's Milestone 10.

**Threshold defaults proposed and reasoned about before writing any
code** (all read from `.env`, none hardcoded inline):

| Threshold | Default | Reasoning |
|---|---|---|
| `CAPTURE_MAX_AGE_SECONDS` | 300 (5 min) | Generous enough for a slow LIVE Playwright capture plus the Claude call in the same run; tight enough to catch a stale/reused screenshot. |
| `MARKET_DATA_MAX_AGE_SECONDS` | 900 (15 min) | Alpha Vantage's free tier isn't tick-by-tick and can lag by minutes; tolerates that without being so loose a genuinely old quote passes. Demo quotes (fixed 2024 timestamps) always fail this — expected, since `SYNTHETIC_DATA` forces review on demo runs regardless. |
| `MIN_RISK_REWARD` | 1.0 | Matches the evaluator's own "poor" cutoff (RR < 1.0 scores 0 points) — the guardrail floor and the rubric's zero-point line are the same number on purpose. |
| `MIN_TOTAL_SCORE` | 60 | Below MEDIUM's ceiling (76), so a genuinely good MEDIUM-confidence setup can still pass; above HIGH's ceiling (52), so `SCORE_THRESHOLD` alone would catch every HIGH-uncertainty run even if `UNCERTAINTY_ACCEPTABLE` were somehow bypassed — deliberate redundancy. ~60% of the absolute max (100), an intuitive "clearly good, not just mediocre" bar. |

**The rubric:**

| # | Guardrail | Checks | Threshold | On failure |
|---|---|---|---|---|
| a | `CAPTURE_SUCCEEDED` | Chart capture status is `SUCCESS` | — | **Blocks.** |
| b | `CAPTURE_FRESH` | `captured_at` age vs. `now`, both timezone-aware UTC | `CAPTURE_MAX_AGE_SECONDS` | **Blocks.** |
| c | `MARKET_DATA_SUCCEEDED` | Market data status is `SUCCESS` | — | **Blocks.** |
| d | `MARKET_DATA_FRESH` | The quote's **source** timestamp age vs. `now` (never fetch time) | `MARKET_DATA_MAX_AGE_SECONDS` | **Blocks.** |
| e | `ANALYSIS_SUCCEEDED` | Agent analysis status is `SUCCESS` | — | **Blocks.** |
| f | `EVALUATION_SUCCEEDED` | Evaluation status is `SUCCESS` | — | **Blocks.** |
| g | `RISK_REWARD_MINIMUM` | `evaluation_result.risk_reward_ratio` | `MIN_RISK_REWARD` | **Forces review.** |
| h | `TRADE_PARAMS_VALID` | entry/stop/target/direction present and coherent (reuses `evals.compute_risk_reward`) | — | **Blocks.** |
| i | `UNCERTAINTY_ACCEPTABLE` | Agent `uncertainty` is not `HIGH` | — | **Forces review.** |
| j | `SCORE_THRESHOLD` | `evaluation_result.total_score` | `MIN_TOTAL_SCORE` | **Forces review.** |
| k | `SYNTHETIC_DATA` | Neither capture mode nor market-data mode is `DEMO` | — | **Forces review, always — never blockable by a good score.** |

Rules a/b/c/d/e/f/h are **blocking**: their failure means the pipeline
itself produced nothing usable, so there's nothing meaningful to review
— any one of them failing forces `BLOCKED`, regardless of the other ten.
Rules g/i/j/k are **review-forcing**: the pipeline worked, but the
result isn't good/certain/real enough to skip a human — any one failing
forces `REQUIRES_REVIEW` (unless a blocking rule also failed, which wins).
`READY_FOR_REVIEW` only happens when all eleven pass.

- **No short-circuiting.** All eleven rules run and all eleven results
  are recorded every time, confirmed by a test that breaks
  `CAPTURE_SUCCEEDED` and checks the other ten (including passing ones)
  are still present and correctly evaluated in the report.
- **`TRADE_PARAMS_VALID` reuses the evaluator's own arithmetic.**
  `evals/trade_evaluator.py`'s `_compute_risk_reward()` was renamed to
  the public `compute_risk_reward()` specifically so guardrails could
  call the exact same LONG/SHORT logic rather than re-implementing it a
  second time (and risking the two definitions drifting apart).
  `RISK_REWARD_MINIMUM`, by contrast, reads `EvaluationResult.
  risk_reward_ratio` directly — a field the evaluator's own docstring
  already flagged as "included ... for the Milestone 9 guardrail."
- **Freshness checks are explicitly time-dependent, on purpose** (rule 1
  carves out "no time-dependent behavior *except where explicitly
  required*"). `now` is a real parameter, defaulting to
  `datetime.now(timezone.utc)` for production use but overridable by
  tests — so "same inputs, same verdict" holds exactly, with the clock
  reading treated as an explicit input rather than an implicit ambient
  one.
- **`SYNTHETIC_DATA` cannot be outscored.** It's a review-forcing rule
  like the other three, but unlike `SCORE_THRESHOLD` or
  `RISK_REWARD_MINIMUM`, no total score or ratio can make it pass — it
  only reads `capture_result.mode` and `market_data_result.mode`.
  Verified directly: a run with every other rule passing and a perfect
  100 score still lands on `REQUIRES_REVIEW`, never `READY_FOR_REVIEW`,
  the moment either mode is `DEMO`.
- `tests/test_guardrails.py` — 31 tests: a full passing baseline
  (`READY_FOR_REVIEW`), confirmation all 11 named checks are always
  present, the no-short-circuit test, pass/fail pairs for all eleven
  rules individually (stale capture using a timestamp set 2 hours in the
  past, stale market quote via the source timestamp, RR below minimum
  forcing review rather than blocking, missing/incoherent trade params
  blocking, HIGH uncertainty and DEMO-sourced data each independently
  proven to force review even with a perfect 100 score and everything
  else passing), the "no approved state" check on the enum itself, and
  determinism for both a passing and a blocked scenario.

Manually ran two examples from the terminal (see README): a `BLOCKED`
run (a 2-hour-old chart capture — `CAPTURE_FRESH` fails, everything else
passes) and a `READY_FOR_REVIEW` run (fresh LIVE capture and market
data, LOW uncertainty, RR 2.0, score 100) — both showing the real
per-rule pass/fail breakdown, not just the final outcome.

Not wired into the orchestrator or the frontend, and no guardrails API
endpoint was added. All 153 tests pass (19 database + 11 API + 17
capture + 18 market data + 25 agent + 32 evaluation + 31 guardrails).

## Milestone 9 fix — demo market data was instantly stale, blocking every demo run

**The bug.** `DemoMarketDataProvider` read its quote `timestamp` straight
from `tools/demo_market_data.json` — a fixed `2024-01-15` value. Every
demo run's age relative to "now" was therefore roughly two years,
enormously over `MARKET_DATA_MAX_AGE_SECONDS` (900s). `MARKET_DATA_FRESH`
is a **blocking** rule, and blocking rules force `BLOCKED` outright,
overriding everything else — including `SYNTHETIC_DATA`, a
review-forcing rule that never even got the chance to be the "reason" a
demo run needed review, because the run was already blocked before
outcome-derivation got that far. In effect, DEMO mode could never
produce a reviewable run at all — a real problem, since Milestones 10
and 11 build a human-review screen that gets demonstrated in DEMO mode.

**Root cause check on the capture side too, per the fix request.**
`capture/demo_provider.py`'s `DemoProvider.capture()` was already setting
`captured_at=datetime.now(timezone.utc)` at capture time (not read from
a fixture) — confirmed by inspection and by a new test exercising the
real provider — so `CAPTURE_FRESH` was never actually broken. Only the
market-data side had the bug.

**The fix.** `DemoMarketDataProvider.get_quote()` now sets `timestamp =
datetime.now(timezone.utc)` at fetch time, same as the capture provider
always did — documented explicitly as a deliberate demo affordance, both
in the provider's own docstring and in `docs/architecture.md`. The
`price` stays exactly as fixed and deterministic as before (read from
`tools/demo_market_data.json`, unchanged value every call) — only the
timestamp became relative. The now-unused `"timestamp"` key was removed
from the fixture JSON rather than left as dead, misleading data.
`source="demo_fixture"` still marks every demo quote unmistakably as
sample data — unchanged.

**The guardrail itself was not touched.** No special-casing for `DEMO`
was added to `MARKET_DATA_FRESH`, `CAPTURE_FRESH`, or anywhere else in
`guardrails/rules.py`. Freshness stays exactly as strict for LIVE data as
it was — confirmed by a test that a genuinely stale LIVE quote (3 hours
old, hand-constructed, not touching the demo provider at all) still
`BLOCKS`, unchanged.

**Result, confirmed against the real providers (not hand-built
fixtures):** a full DEMO run — real `DemoProvider`, real
`DemoMarketDataProvider`, an otherwise-perfect agent analysis, a perfect
100 score — now lands on `REQUIRES_REVIEW`, with `SYNTHETIC_DATA` as the
**only** failing rule; `CAPTURE_FRESH` and `MARKET_DATA_FRESH` both pass.
Verified by hand from the terminal too (see README) — the real output
shows exactly that breakdown.

- `tools/market_data.py` — `DemoMarketDataProvider.get_quote()` fixed;
  module and `MarketQuote` docstrings updated to state the DEMO timestamp
  exception explicitly rather than leaving the "source time, never fetch
  time" rule looking unconditional.
- `tools/demo_market_data.json` — `"timestamp"` key removed (unused now).
- `tests/test_market_data.py` — `test_demo_fetch_is_deterministic`
  (which asserted timestamp *equality* across calls — no longer true by
  design) replaced with `test_demo_fetch_price_is_deterministic_across_
  calls` (price only) and `test_demo_fetch_timestamp_is_generated_fresh_
  at_fetch_time` (timestamp falls between two `datetime.now()` calls
  bracketing the fetch).
- `tests/test_guardrails.py` — 5 tests added using the **real**
  `DemoProvider`/`DemoMarketDataProvider` (not the hand-built `_fresh_*`
  fixtures the rest of the file uses): demo market data passes
  `MARKET_DATA_FRESH`, demo capture passes `CAPTURE_FRESH`, a full real
  DEMO run reaches `REQUIRES_REVIEW` with `SYNTHETIC_DATA` as the sole
  failing rule, a full real DEMO run never reaches `READY_FOR_REVIEW`,
  and a genuinely stale LIVE quote still `BLOCKS`.
- **A real bug surfaced and fixed during this work, in the tests
  themselves, not the product code:** two of the new tests initially
  computed `now` *before* calling the real providers, and both `capture()`
  and `get_quote()` generate their own `datetime.now(utc)` a moment
  later — occasionally landing microseconds after the test's `now`,
  which made the guardrail's (correct, intentional) "timestamp is in the
  future" rejection fire and turned the expected `REQUIRES_REVIEW` into
  `BLOCKED`. It didn't reproduce when those two test files were run
  alone, only inside the full suite — a genuine timing race, not a
  product defect. Fixed by computing `now` *after* the provider calls,
  matching how a real caller would do it.
- `evals/trade_evaluator.py` — untouched by this fix (mentioned only
  because `evaluate()` is used throughout the new tests to build a real
  `EvaluationResult` from the real demo analysis).

All 159 tests pass (19 database + 11 API + 17 capture + 19 market data +
25 agent + 32 evaluation + 36 guardrails), confirmed stable across three
consecutive full-suite runs after the timing-race fix.

## Milestone 10 — Human approval and decision audit

Built `POST /runs/{run_id}/review`: the only code path anywhere in this
application that can move a run to a final `APPROVED`/`REJECTED` state.
It records a human's judgment about results that already exist — it
never re-runs anything.

**The real design problem this milestone had to solve first: there's no
stored guardrail outcome to check.** `guardrails/rules.py`'s
`evaluate_guardrails()` computes a `GuardrailOutcome` live, but nothing
persists that outcome anywhere — Milestones 5–9 were all deliberately
built standalone, never wired into an orchestrator, so no run created
through the API today has ever actually had guardrails run against it.
The fix: `outcome_from_results()`, a new function in `guardrails/rules.py`
that reconstructs the same outcome from a run's stored `GuardrailResult`
rows, reusing the exact same `BLOCKING_RULES`/`REVIEW_FORCING_RULES`
classification the live check uses — so "the outcome" means the same
thing whether it's freshly computed or read back from the database.
**A run with zero guardrail results is treated the same as `BLOCKED`**
for approval purposes: no evidence a run wasn't blocked is not grounds to
approve it. Since there's still no orchestrator, this means every run
created through `POST /runs` today can only ever be `REJECTED` — never
`APPROVED` — until something (a future milestone, or a test/manual seed)
actually writes `GuardrailResult` rows for it. That's demonstrated
directly below, not glossed over.

- `backend/schemas.py` — `HumanReviewRequest` (`decision` +
  optional `comment`, nothing else — no score field, no guardrail-outcome
  field; extra fields in the request body are simply not part of the
  schema and have zero effect) and `HumanReviewResponse`. `RunDetail`
  gained a `guardrail_outcome` field (`"BLOCKED"` / `"REQUIRES_REVIEW"` /
  `"READY_FOR_REVIEW"` / `null`), computed via `outcome_from_results()`,
  not a real column.
- `database/crud.py` — added `update_run_status()` (sets `Run.status`
  and, optionally, `completed_at`), following the same one-function-one-
  responsibility pattern as every other `crud.py` write.
- `database/models.py` — `Run.status` and `HumanReview.decision`'s stale
  comments (which said lowercase `"approved"`/`"rejected"`, left over
  from a Milestone 3 placeholder) corrected to match actual usage:
  uppercase, matching `"CREATED"` from Milestone 4.
- `backend/api/routes_runs.py` — `review_run()`: 404 if the run doesn't
  exist; 409 if it already has a decision (**checked before anything
  else**, so a second attempt — approve or reject — is refused
  identically and the original decision is never touched); for `APPROVED`
  only, 409 if the outcome is `BLOCKED` or unknown; on success, writes the
  `HumanReview` row, updates `Run.status` to the decision, sets
  `Run.completed_at` to the exact same `decided_at` timestamp, and writes
  a `human_review_recorded` audit event. `REJECTED` skips the outcome
  check entirely — permitted on any run, in any state, per the
  requirement.
- `tests/test_api.py` — 14 tests added (25 total, up from 11): approve
  and reject each store the decision/update status/write the audit event;
  approving a `BLOCKED` run refused with a clear error, rejecting the
  same run permitted; a run with zero guardrail results refused for
  `APPROVED`, permitted for `REJECTED`; a `REQUIRES_REVIEW` run (not just
  `READY_FOR_REVIEW`) can still be approved — only `BLOCKED` forbids it;
  a second decision refused with the original decision and its single
  audit event confirmed unchanged; 404 on a nonexistent run; 422 on an
  invalid decision word; case-insensitive decision parsing; an attempt to
  inject `total_score`/`guardrail_outcome`/`risk_reward_score` in the
  request body confirmed to have no effect; timezone-aware UTC decision
  and completion timestamps; and confirmation the endpoint never writes
  capture/market-data/analysis/evaluation rows. Since no orchestrator
  exists to populate real `GuardrailResult` rows, tests seed them
  directly via `crud.add_guardrail_result()` through a `session_factory`
  attribute added to the existing `client` fixture (additive only — the
  original 11 Milestone 4 tests are untouched).

Manually verified against a real running server, not just the test
client (see README for the exact commands): created a run, rejected it
immediately (works with zero guardrail data, as designed), created a
second run, seeded 11 passing guardrail results by hand (standing in for
what a future orchestrator will do automatically), confirmed
`guardrail_outcome` read back as `"READY_FOR_REVIEW"`, approved it, and
confirmed a second decision attempt on that same run was refused with
`409` while the original `APPROVED` decision remained exactly as
recorded.

Not wired into the frontend (Milestone 11). All 173 tests pass (19
database + 25 API + 17 capture + 19 market data + 25 agent + 32
evaluation + 36 guardrails).

## Milestone 10.5 — orchestrator wires the 12-step pipeline

Built `backend/orchestrator.py`'s `run_pipeline(session, run_id)`: the
first code path anywhere in this application that actually calls capture
-> market data -> agent -> evaluation -> guardrails in sequence for one
run and persists every step. Added as its own milestone, between 10 and
11, deliberately -- not folded into the UI milestone -- so a pipeline bug
and a rendering bug can never be mistaken for each other, and so the
orchestrator (which the whole project is really about) gets its own
tests, its own commit, and its own entry here.

**Scope, exactly as agreed before writing any code:**

- One new endpoint, `POST /runs/{run_id}/analyze`. `POST /runs` is
  untouched -- still just a database write.
- Synchronous. No background jobs, no websockets, no polling
  infrastructure -- the endpoint doesn't return until the whole pipeline
  has finished, and the response already reflects the final state. The
  UI (Milestone 11) will call this, then read `GET /runs/{id}`.
- No new business logic. Every number, every category, every guardrail
  rule comes from the same five already-tested modules
  (`capture/`, `tools/market_data.py`, `agents/trade_agent.py`,
  `evals/trade_evaluator.py`, `guardrails/rules.py`) -- none of them were
  changed. The orchestrator only calls them, in the order
  `docs/architecture.md` already specifies, and saves what they return
  via `database/crud.py`.
- LIVE/DEMO selection stays exactly as it was -- `CaptureManager()` and
  `MarketDataManager()` are constructed with no arguments, so they read
  `CAPTURE_MODE`/`MARKET_DATA_MODE` from `.env` themselves, same as
  always. No new fallback logic anywhere.

**Fail fast, honestly:**

- Chart capture and market data are independent tool calls -- neither
  depends on the other succeeding (they're separate inputs to the agent
  step) -- so both are always attempted, even if one already failed.
- The agent is only called if **both** capture and market data succeeded.
  A failed capture or a failed quote means there's nothing real to show
  the agent, so it's never invoked at all -- not even to have it
  short-circuit itself the way `agents/trade_agent.py` already can.
  Verified directly: a mocked `TradeAgent.analyze` is asserted never
  called when either upstream stage fails.
- The evaluator is only called if the agent succeeded -- there's nothing
  to score otherwise.
- **Guardrails always run**, no matter what failed upstream, using
  whatever result objects exist (even synthetic FAILED ones for a stage
  that was skipped) -- so a `BLOCKED` run still gets its full eleven-rule
  breakdown explaining exactly why, not a truncated one.

**A run can only be analyzed once.** `run_pipeline()` checks for any
existing `Capture`/`MarketData`/`AgentAnalysis`/`Evaluation`/
`GuardrailResult` rows before doing anything, and raises
`RunAlreadyAnalyzedError` if any exist -- turned into a `409` by the
route, the same "a decision is final" rule Milestone 10's human-review
endpoint already applies to a second approve/reject attempt.

**Every stage writes a start and finish audit event**, in order, whether
it succeeded, failed, or was skipped (`analysis_started`,
`capture_started`/`capture_finished`, `market_data_started`/
`market_data_finished`, `agent_analysis_started`/`agent_analysis_finished`
or `agent_analysis_skipped`, `evaluation_started`/`evaluation_finished`
or `evaluation_skipped`, `guardrails_started`/`guardrails_finished`,
`analysis_finished`) -- confirmed exact-order by a dedicated test, for
both a fully successful run and one where capture fails partway through.

**The run's `status` moves with the pipeline**, then lands on the
guardrail outcome itself: `"ANALYZING"` while it runs, then `"BLOCKED"` /
`"REQUIRES_REVIEW"` / `"READY_FOR_REVIEW"` when it finishes --
`completed_at` is set to that same moment. **Never `"APPROVED"` or
`"REJECTED"`** -- those two values are still only ever written by the
human-review endpoint (Milestone 10). If a human later reviews the run,
that endpoint overwrites both `status` and `completed_at` with the
decision and its timestamp, same as it always has -- the orchestrator
doesn't need to know or care that will happen later.

**A known, deliberate limitation, not fixed here because it was out of
this milestone's approved scope (schema changes to `agent_analyses` or
`evaluations`):** those two tables were built in Milestone 3 with no
`status`/`error_message` columns, and their score columns are `NOT NULL`
-- so a *failed* agent analysis or a *failed* evaluation cannot be stored
as a structured row under the current schema (unlike `Capture` and
`MarketData`, which both had `status`+`error_message` from the start).
The orchestrator works around this rather than silently dropping the
failure: when the agent or evaluator fails, no row is written to that
table, but the real error message is written to `audit_events` instead,
so `GET /runs/{id}` still tells the whole story -- just through the audit
trail rather than a dedicated failed row. The same applies to the five
categorical fields the agent produces (`trend_direction`, `trend_quality`,
`structure_quality`, `setup_quality`, `context_risk`) -- `agent_analyses`
was never given columns for these either (a gap from the Milestone 8
revision, not this one), so a **successful** analysis's audit event
records them in its message text, which is currently the only place
they're visible after the fact. Both gaps are flagged here for whoever
scopes a future milestone -- adding the missing columns is a small,
independent change, not attempted now since it wasn't part of what was
agreed for this one.

- `backend/orchestrator.py` — `run_pipeline()`, `RunAlreadyAnalyzedError`,
  and small private helpers (`_has_existing_pipeline_results`,
  `_skipped_agent_result`, `_skipped_evaluation_result`, and four
  `_..._summary()` functions that build the audit-event text). Previously
  a one-line placeholder since Milestone 2.
- `backend/api/routes_runs.py` — added `POST /runs/{run_id}/analyze`
  (404 if the run doesn't exist, 409 via `RunAlreadyAnalyzedError` if it's
  already been analyzed, otherwise runs the pipeline and returns the same
  `RunDetail` shape `GET /runs/{id}` returns). Factored the
  outcome-attaching logic both endpoints need into `_run_to_detail()`
  rather than duplicating it a second time.
- `database/models.py` — `Run.status`'s comment updated to list the new
  values the orchestrator writes (doc-only change, no schema change).
- `tests/test_orchestrator.py` — 10 tests, all against the real DEMO
  capture and market-data providers (no network -- committed fixtures,
  same pattern as Milestone 9's fix tests) with `CAPTURE_MODE`/
  `MARKET_DATA_MODE` pinned to `DEMO` via `monkeypatch` so behavior never
  depends on a developer's local `.env`. Only the agent is ever mocked
  (`backend.orchestrator.TradeAgent` patched directly -- no anthropic
  client is ever constructed, no network call is ever made): a full DEMO
  run reaching `REQUIRES_REVIEW` with `SYNTHETIC_DATA` the only failing
  rule; every stage's result readable via `GET /runs/{id}` (including the
  exact total score matching `docs/rubric.md`'s worked example); a failed
  capture (mocked `CaptureManager`) stopping the pipeline, never calling
  the agent, and still writing all eleven guardrail results; a failed
  market-data fetch (mocked `MarketDataManager`) doing the same; a failed
  agent analysis being recorded via the audit trail and never evaluated;
  audit-event ordering for both a fully successful run and a
  capture-fails run; analyzing an already-analyzed run refused with 409
  and the original results unchanged; analyzing a nonexistent run
  returning 404; and a direct check that `GuardrailOutcome` has exactly
  three values, `run.status` after analysis is always one of them, and
  `human_review` stays `None` until an actual human decision is made.

Manually verified against a real running server (not just the test
client): created a run, analyzed it -- which, with a real
`ANTHROPIC_API_KEY` configured locally, made one real Claude call against
the real DEMO screenshot and real DEMO market quote -- and reached
`REQUIRES_REVIEW` for two genuine reasons (`SCORE_THRESHOLD`, the real
analysis scored 45; and `SYNTHETIC_DATA`, unconditionally, since the
whole run is DEMO-sourced). Confirmed `GET /runs/{id}` showed the
complete audit trail in order, all eleven guardrail results, the real
agent prose, and the real component scores. Rejected the run; confirmed
a second `/analyze` call was refused with `409`, and a second `/review`
call was refused with `409` and the original `REJECTED` decision
unchanged. Dev database reset to empty afterward, same as every prior
milestone's manual-verification step.

Not wired into the frontend -- that's Milestone 11, which was
deliberately paused so this could be its own milestone first. All 183
tests pass (19 database + 25 API + 17 capture + 19 market data + 25 agent
+ 32 evaluation + 36 guardrails + 10 orchestrator).

## Milestone 10.5 fix — failure states on analysis and evaluation records

Closed the schema gap flagged (but deliberately not fixed, as out of
scope) in the Milestone 10.5 entry above: `agent_analyses` and
`evaluations` had `NOT NULL` score/text columns and no `status`/
`error_message` columns, so a failed agent analysis or a failed
evaluation could not be stored as a row -- only described in
`audit_events`. That broke the pattern `captures` and `market_data`
already followed (both have carried `status`+`error_message` since
Milestone 3), and meant a client reading `GET /runs/{id}` had to parse
free-text audit events to know whether an analysis or evaluation had
succeeded. Fixed before any UI gets built on top of that shape, per the
request.

**Schema (`database/models.py`):**

- `agent_analyses` gained `status` (`"SUCCESS"` | `"FAILED"`) and
  `error_message` (nullable `Text`), matching `captures`/`market_data`
  exactly. `analysis_text`, `trend_assessment`, `structure_assessment`,
  `setup_assessment`, and `uncertainty` all became nullable -- `NULL` on
  a `FAILED` row, never a fabricated placeholder string. No `CHECK`
  constraint was added here, matching `captures`/`market_data`, neither
  of which has one either -- see below for why `evaluations` is
  different.
- `evaluations` gained the same `status`/`error_message` columns, and all
  six score columns (`trend_score`, `structure_score`, `entry_score`,
  `risk_reward_score`, `timing_context_score`, `total_score`) became
  nullable. **Not zero** on a `FAILED` row -- zero is a real, meaningful
  score (RR < 1.0 genuinely scores 0, `UNCLEAR` genuinely scores 0), and
  storing it for a run that was never actually scored would be
  indistinguishable from a genuine all-zero result. This was the one
  design point worth being careful about: a score column that's merely
  "optional" but defaults to 0 would have silently reintroduced exactly
  the ambiguity this fix exists to remove.

**The `CHECK` constraint, adapted rather than dropped:** the original
Milestone 3 constraint (`total_score = trend_score + ... +
timing_context_score`) was replaced with:

```sql
(
  status = 'FAILED'
  AND trend_score IS NULL AND structure_score IS NULL
  AND entry_score IS NULL AND risk_reward_score IS NULL
  AND timing_context_score IS NULL AND total_score IS NULL
) OR (
  status = 'SUCCESS'
  AND trend_score IS NOT NULL AND structure_score IS NOT NULL
  AND entry_score IS NOT NULL AND risk_reward_score IS NOT NULL
  AND timing_context_score IS NOT NULL AND total_score IS NOT NULL
  AND total_score = trend_score + structure_score + entry_score
      + risk_reward_score + timing_context_score
)
```

Two branches, keyed off `status`, so there is no third possibility a row
can be in: a `SUCCESS` row must have all six scores non-null *and* the
original sum rule must hold exactly as it always did; a `FAILED` row
must have all six null. A row that's half-and-half -- a `SUCCESS` row
missing a score, or a `FAILED` row carrying a stray real score on one
component -- fails the constraint either way, however it was
constructed, same backstop guarantee the original constraint gave for
its one case. (A side effect worth naming: because both branches require
an exact `status` match, an unrecognized third `status` value, e.g.
`'PENDING'`, fails the constraint too -- the same `CHECK` now also
enforces that `status` can only ever be `'SUCCESS'` or `'FAILED'` on
this table, which the original didn't need to care about.) The
constraint keeps its original name,
`ck_evaluations_total_score_is_sum_of_components`, since it's still
fundamentally the same rule, just written to hold for one more case than
before. Proven directly by four tests in `tests/test_database.py`:
a `SUCCESS` row with a mismatched total is still rejected; a `FAILED`
row with all-null scores is now permitted; a `FAILED` row with one
stray non-null score is rejected; and (unchanged, still passing without
modification) the original Milestone 3 test that omits `status`
entirely still raises `IntegrityError`, just now via the `NOT NULL`
constraint on `status` rather than the sum rule specifically -- both are
real integrity violations, so the test's assertion holds either way.

**`database/crud.py`:** `add_agent_analysis()` and `add_evaluation()`
are unchanged in signature -- still exactly the parameters they always
had, still no `total_score` parameter, still guaranteed `SUCCESS` rows
only (each now hardcodes `status="SUCCESS"` internally, not as a
parameter, so neither function can be used to smuggle in a failure with
fabricated qualitative fields). Two new functions handle the other case:
`add_failed_agent_analysis(session, *, run_id, error_message)` and
`add_failed_evaluation(session, *, run_id, error_message)`, each writing
a `status="FAILED"` row with every other field `None` except
`error_message`. Keeping the original functions' signatures untouched
meant every pre-existing caller and test needed zero changes.

**`backend/orchestrator.py`:** now writes exactly one `AgentAnalysis` row
and exactly one `Evaluation` row for every analyzed run, in every case --
success, an attempted-and-failed stage, or a stage that was never
attempted because an upstream one failed first (previously, the last two
cases left the table empty and relied on `audit_events` alone). The
audit trail still gets its own event either way -- both are kept
deliberately: the row says *what* happened, the audit trail says *when*,
*in what order*, and *alongside what else*.

**`backend/schemas.py`:** `AgentAnalysisOut` and `EvaluationOut` both
gained `status: str` and `error_message: Optional[str]`, and every field
that can now be `None` on a `FAILED` row was changed to `Optional` --
so `GET /runs/{run_id}` exposes success or failure directly on each
record, which was the actual point of this fix.

**Still open, not addressed by this fix (unchanged from the Milestone
10.5 entry):** `agent_analyses` still has no columns for the five
categorical fields the agent produces (`trend_direction`, `trend_quality`,
`structure_quality`, `setup_quality`, `context_risk`) -- a gap from the
Milestone 8 revision, not this fix. A successful analysis's audit-event
text remains the only place those five values are visible after the
fact.

**Database rebuilt, not migrated**, per the instruction -- there was no
real audit data to preserve. `database/tradepilot.db` was deleted and
recreated with `python -m database.init_db`; the commands in "Rebuilding
the database" below are unchanged (this fix is exactly the kind of
"a model changes shape" case that section already describes).

- `tests/test_database.py` — 5 tests added (24 total, up from 19):
  a failed agent analysis stored via `crud.add_failed_agent_analysis()`
  with status/error/null fields; a failed evaluation stored via
  `crud.add_failed_evaluation()` with status/error/null scores (not
  zeros); the two direct-CHECK-constraint tests described above (`SUCCESS`
  row rejected on mismatch, `FAILED` row permitted with all-null scores);
  and the partial-null rejection test. `test_save_agent_analysis` and
  `test_save_evaluation_computes_total_score` (both pre-existing) gained
  one extra assertion each (`status == "SUCCESS"`, `error_message is
  None`) rather than being rewritten.
- `tests/test_orchestrator.py` — 3 of the existing 10 tests had their
  assertions updated to match the new behavior (a failed/skipped stage
  now produces a stored `FAILED` row, not an empty list) -- no tests were
  removed or added; the same 10 scenarios are still covered, now checking
  the record directly instead of asserting its absence. `test_success`
  path tests gained `status`/`error_message` assertions too.

Manually verified against a real running server: deleted and recreated
`database/tradepilot.db`, started the server with `ANTHROPIC_API_KEY`
cleared for that process only (not edited in `.env`) so the agent fails
its own internal validation check -- "ANTHROPIC_API_KEY is not set" --
before it ever imports the `anthropic` client or makes a network call.
Created a run and analyzed it: `GET /runs/{id}` showed `analyses[0]` with
`status: "FAILED"`, the real error message, and every qualitative field
`null`; `evaluations[0]` with `status: "FAILED"`, `error_message:
"Evaluation skipped -- there is no successful agent analysis to score."`,
and every score field `null` (not zero) -- both visible directly on the
record, exactly as required, with the audit trail still describing the
same thing in its own words alongside it. Dev database reset to empty
afterward.

All 188 tests pass (24 database + 25 API + 17 capture + 19 market data +
25 agent + 32 evaluation + 36 guardrails + 10 orchestrator).

## Milestone 10.5 fix 2 — persist agent categorical observations

Closed the second schema gap flagged (but deliberately not fixed) at the
end of the Milestone 10.5 fix entry above: `agent_analyses` had no
columns for the five categorical fields the v2 rubric actually scores
from (`trend_direction`, `trend_quality`, `structure_quality`,
`setup_quality`, `context_risk`). The agent produces them and
`evals/trade_evaluator.py` scores from them, but a completed run only
ever showed the resulting number -- e.g. `trend_score: 14` -- with no
stored record of the observation that produced it. That defeats the
audit trail's whole purpose: a score with no traceable evidence isn't
actually auditable, it's just a number to trust.

**Schema (`database/models.py`):** `agent_analyses` gained
`trend_direction`, `trend_quality`, `structure_quality`, `setup_quality`,
`context_risk` (all nullable `String(20)`) -- populated on `SUCCESS`,
`null` on `FAILED`, the same pattern as every other qualitative column on
this table. A new module-level constant, `AGENT_CATEGORICAL_FIELDS`,
records each field's exact allowed set in one place.

**Enforcement: both database level and application level, deliberately,
not one or the other:**

- **Database level** — five new `CHECK` constraints on `agent_analyses`
  (`ck_agent_analyses_trend_direction_allowed`, and one each for the
  other four fields), each shaped `column IS NULL OR column IN (...)`,
  built from `AGENT_CATEGORICAL_FIELDS` so the allowed values are written
  down exactly once. This is the backstop for any future code that
  constructs `AgentAnalysis(...)` directly, bypassing `crud.py` entirely
  -- the same reason the `evaluations` table already has a `CHECK`
  constraint of its own.
- **Application level** — `database/crud.py`'s new
  `_validate_categorical_fields()` helper runs inside
  `add_agent_analysis()` before anything is written, raising `ValueError`
  with the actual bad value and its allowed set. This exists *in
  addition to* the database check, not instead of it, for the same
  reason `add_evaluation()`'s own total-score computation exists
  alongside the `evaluations` `CHECK` constraint: a Python exception
  naming the actual problem is a far better failure than a generic
  SQLite `IntegrityError` for the normal case, while the database
  constraint is what actually guarantees the invariant can never be
  violated no matter what code path writes the row. In the real pipeline
  this basically never fires either way, since `agents/trade_agent.py`'s
  own `_parse_response()` already rejects an out-of-set value before an
  analysis is ever accepted as `SUCCESS` -- but that check lives in a
  different module, for a different purpose (rejecting a bad *model
  response*), and this task asked for a check at the *write* boundary
  specifically, so both layers of this codebase's existing defense-in-
  depth pattern apply here too.

**A real design decision about where the allowed-values live:**
`AGENT_CATEGORICAL_FIELDS` in `database/models.py` is a deliberate
*duplicate* of `agents.trade_agent.CATEGORICAL_FIELDS`, not an import of
it. `database/` has been a leaf module with zero dependencies on
`agents/`, `capture/`, `tools/`, or `evals/` since Milestone 3 --
everything else depends on it, never the other way around, and only
`backend/orchestrator.py` ties the layers together. Importing
`agents.trade_agent` into `database/models.py` would have been the
smaller diff, but it would invert that dependency direction for a
persistence-layer file that has no other reason to know the agent module
exists. Duplication has an obvious cost (the two lists can drift), so a
dedicated test
(`test_agent_categorical_allowed_values_match_the_agent_layer`) asserts
the two are identical every time the suite runs -- if a category is ever
added to one and not the other, that test fails immediately rather than
the drift being discovered later as a confusing rejection.

**`database/crud.py`:** `add_agent_analysis()`'s five new parameters are
required, not optional/defaulted -- a real `SUCCESS` row from the actual
pipeline always has all five, and a caller that forgot one should get an
immediate `TypeError`, not a silently incomplete row (the same reasoning
`add_evaluation()`'s lack of a `total_score` parameter already
represents). `add_failed_agent_analysis()` sets all five to `None`
alongside the other qualitative fields, unchanged in signature.

**`backend/orchestrator.py`:** the one call site,
`crud.add_agent_analysis(...)` inside `run_pipeline()`, now passes
`agent_result.trend_direction` / `.trend_quality` / `.structure_quality`
/ `.setup_quality` / `.context_risk` straight through from the
`AgentAnalysisResult` the agent already returned -- no new logic, just
five more fields threaded through a call that already existed.

**`backend/schemas.py`:** `AgentAnalysisOut` gained the same five fields
(`Optional[str]`), so `GET /runs/{run_id}` returns them alongside the
prose and the component scores.

- `tests/test_database.py` — 4 tests added: `test_save_agent_analysis`
  (pre-existing) extended to pass and assert all five categorical fields;
  a new round-trip test confirming they survive a real commit + refresh;
  an application-level rejection test (`ValueError` from
  `add_agent_analysis()` on an out-of-set value, and confirmation nothing
  was written); a database-level rejection test (direct
  `models.AgentAnalysis(...)` construction bypassing `crud.py`,
  `IntegrityError` from the `CHECK` constraint); and the drift-guard test
  described above. `test_run_relationships_reach_all_child_records`
  (pre-existing) updated to pass the five now-required fields.
- `tests/test_orchestrator.py` — the full-success `GET /runs/{id}` test
  extended to assert the categorical fields are present and correct
  (`trend_direction: "UP"`, etc., matching the score they produced); the
  failed-agent-analysis test extended to assert all five are `null` on a
  `FAILED` row.

All 192 tests pass (28 database + 25 API + 17 capture + 19 market data +
25 agent + 32 evaluation + 36 guardrails + 10 orchestrator).

Manually verified end to end without any real API call: recreated
`database/tradepilot.db`, then ran the real FastAPI app (via
`TestClient`, pointed at the real dev database file, not an in-memory
test database) with `backend.orchestrator.TradeAgent` patched to a
forced-`SUCCESS` stub -- confirmed via `mock_agent.analyze.called ==
True` that the stub, not a real client, was what actually ran. Created a
run and analyzed it; `GET /runs/{id}` showed `analyses[0]` with
`trend_direction: "UP"`, `trend_quality: "STRONG"`,
`structure_quality: "CLEAN"`, `setup_quality: "ACCEPTABLE"`,
`context_risk: "LOW"` alongside `evaluations[0]`'s `trend_score: 14`,
`structure_score: 14`, `entry_score: 14`, `timing_context_score: 14`,
`total_score: 76` -- every component score now traces directly to the
categorical observation that produced it (MEDIUM uncertainty caps each
subjective component's raw score at 14; `STRONG`/`CLEAN` both score 20
raw, `ACCEPTABLE` scores 15 raw, `LOW` scores 20 raw -- all four capped
down to 14, exactly matching `docs/rubric.md`'s worked example). Dev
database reset to empty afterward.

**A schema audit was requested alongside this fix, across all eight
tables, comparing what the pipeline's own dataclasses (`CaptureResult`,
`MarketQuote`, `AgentAnalysisResult`, `EvaluationResult`,
`GuardrailCheck`) actually produce against what each table can store.
Reported, not fixed, per the instruction:**

- **`market_data` has no `mode` column.** `Capture` stores
  `capture_mode` (`"LIVE"`/`"DEMO"`) directly, but `MarketData` has no
  equivalent -- `MarketQuote.mode` is never persisted. In practice a
  reader can usually infer it from `source` (`"demo_fixture"` vs.
  `"alpha_vantage"`), but that's an indirect inference from a string
  that happens to be mode-specific today, not a structural guarantee the
  way `capture_mode` is. Asymmetric with `captures`, which is the more
  suspicious half of this finding.
- **`evaluations` has no `risk_reward_ratio` column.** The banded score
  (`risk_reward_score`: 0/10/20) is stored, but the raw ratio behind it
  (e.g. `2.0`) is not -- `evals/trade_evaluator.py`'s own docstring
  documents this as deliberate ("not a database column; it never gets
  stored, only returned here"), so it's a *known* omission, not an
  oversight, but it's arguably the same category of gap this fix just
  closed for the other four components: `risk_reward_score: 20` is
  exactly as untraceable to its evidence (the actual ratio, and how far
  above the 2.0 threshold it was) as `trend_score: 14` was before this
  fix.

No other gap was found across `runs`, `captures`, `guardrail_results`,
`human_reviews`, or `audit_events` -- each stores every field its
corresponding pipeline dataclass (or, for `runs`/`human_reviews`, its
corresponding request schema) produces. `RunDetail.guardrail_outcome`
being computed rather than stored is a separate, already-documented,
deliberate design choice (Milestone 10's architecture notes), not a gap
of this kind.

## Milestone 10.5 fix 3 — store market data mode and risk/reward ratio

Closed both remaining gaps from the schema audit at the end of the
Milestone 10.5 fix 2 entry above.

**Gap 1 — `market_data` had no `mode` column.** `Capture` stores
`capture_mode` (`"LIVE"`/`"DEMO"`) directly; `MarketQuote.mode` was never
persisted, only inferable indirectly through `source`
(`"demo_fixture"` vs. `"alpha_vantage"`) -- a string that happens to be
mode-specific today but was never a structural guarantee. This mattered
specifically because `SYNTHETIC_DATA` (`guardrails/rules.py`) is the
guardrail that makes a DEMO-sourced run provably unable to reach
`READY_FOR_REVIEW` -- its own evidence (was this quote really DEMO?)
belongs in a real column, not a string a reader has to already know how
to interpret.

- `database/models.py` — `MarketData` gained `mode` (`String(10)`, `NOT
  NULL` -- always present, success or failure alike, matching
  `capture_mode`), constrained by a new `CHECK` constraint
  (`ck_market_data_mode_allowed`, `mode IN ('LIVE', 'DEMO')`) built from
  a new `MARKET_DATA_MODE_ALLOWED_VALUES` constant. Same reasoning as
  `AGENT_CATEGORICAL_FIELDS`: duplicated from
  `capture.base.CaptureMode`/`tools.market_data.MarketDataMode` rather
  than imported, so `database/` stays a leaf module.
- `database/crud.py` — `add_market_data()` gained a required `mode`
  parameter, validated by a new `_validate_mode()` helper before
  anything is written (application level, alongside the `CHECK`
  constraint at the database level -- the same double-enforcement
  pattern as the categorical fields).
- `backend/orchestrator.py` — the one call site now passes
  `market_data_result.mode.value` straight through.
- `backend/schemas.py` — `MarketDataOut` gained `mode: str`.

**Gap 2 — `evaluations` had no `risk_reward_ratio` column.** The banded
score (`risk_reward_score`: 0/10/20) was stored; the raw ratio behind it
(e.g. `2.0`) wasn't -- the exact same traceability gap Milestone 10.5 fix
2 closed for the other four components, just for the one component whose
evidence is a number instead of a category word.

- `database/models.py` — `Evaluation` gained `risk_reward_ratio` (`Float`,
  nullable). **Deliberately kept out of the existing sum-rule `CHECK`
  constraint** (`ck_evaluations_total_score_is_sum_of_components`, which
  is completely unmodified by this fix) per the explicit instruction --
  `total_score` sums five integers, and mixing a float into that equality
  would be a correctness risk (float rounding) for a value that was never
  part of what the sum represents anyway. Its own nullability (`NULL` on
  `FAILED`, required on `SUCCESS`) is enforced by a **second, independent**
  `CHECK` constraint (`ck_evaluations_risk_reward_ratio_matches_status`)
  that follows the identical status-keyed shape as the first, just for
  this one column.
- `database/crud.py` — `add_evaluation()` gained a required
  `risk_reward_ratio` parameter, stored as-is (not recomputed --
  `evals/trade_evaluator.py` already computed it once; storing it again
  independently would risk two numbers disagreeing). `add_failed_evaluation()`
  sets it to `None` alongside the other score columns.
- `backend/orchestrator.py` — the one call site now passes
  `evaluation_result.risk_reward_ratio` straight through.
- `backend/schemas.py` — `EvaluationOut` gained
  `risk_reward_ratio: Optional[float]`.

**Both fixes follow the exact same "duplicate the allowed set, validate
at both levels, thread the value through the one orchestrator call site"
shape as Milestone 10.5 fix 2** -- no new architectural decisions, just
the same pattern applied to the two remaining gaps.

- `tests/test_database.py` — 5 tests added: mode `DEMO` for a DEMO run,
  mode `LIVE` for a LIVE run, an out-of-set mode rejected at the
  application level (nothing written), an out-of-set mode rejected at the
  database level (direct `models.MarketData(...)` construction,
  `IntegrityError`), and `risk_reward_ratio` round-tripping through a real
  commit + refresh. `test_save_market_data`, `test_save_market_data_
  failure_records_error`, `test_save_evaluation_computes_total_score`,
  `test_add_evaluation_rejects_a_smuggled_total_score`, and
  `test_run_relationships_reach_all_child_records` (all pre-existing)
  updated to pass the new required parameters. The four pre-existing
  `evaluations` `CHECK`-constraint tests needed **no changes at all** --
  each already either sets `risk_reward_ratio`-consistent state
  incidentally (the all-null `FAILED` test) or was already failing the
  original sum-rule constraint independently (the mismatched-total
  tests), so adding a second constraint didn't change any of their
  outcomes; confirmed by running them, not just reasoned about.
- `tests/test_orchestrator.py` — the full-success `GET /runs/{id}` test
  extended to assert `market_data[0].mode == "DEMO"` and
  `evaluations[0].risk_reward_ratio == 2.0`; the failed-evaluation test
  extended to assert `risk_reward_ratio is None` alongside the other
  null score fields.

All 197 tests pass (33 database + 25 API + 17 capture + 19 market data +
25 agent + 32 evaluation + 36 guardrails + 10 orchestrator).

Manually verified end to end without any real API call, same method as
the Milestone 10.5 fix 2 entry (the real FastAPI app via `TestClient`,
pointed at the real, freshly-recreated dev database, with
`backend.orchestrator.TradeAgent` patched to a forced-`SUCCESS` stub --
confirmed via `mock_agent.analyze.called == True`). `GET /runs/{id}`
showed `market_data[0].mode: "DEMO"` and
`evaluations[0].risk_reward_ratio: 2.0000000000000444` (floating-point
noise from the same `(target - entry) / (entry - stop)` division that's
always produced this; `risk_reward_score: 20` is the banded value of
that same number). Dev database reset to empty afterward.

**The schema audit is now clean.** Re-checked all eight tables against
what the pipeline's dataclasses (`CaptureResult`, `MarketQuote`,
`AgentAnalysisResult`, `EvaluationResult`, `GuardrailCheck`) actually
produce: every field on every one of those five dataclasses now has a
corresponding column somewhere in `database/models.py`. No remaining
place where the pipeline computes something the schema can't store.

## Milestone 11 — frontend wired to the backend

Wired the React/TypeScript shell (Milestone 1) to the real API: submit a
symbol → watch the real pipeline run → see the full result, traced back
to its evidence → approve or reject it. Tailwind added, as deferred
since Milestone 2. No backend business logic changed in this milestone
beyond the one prerequisite below, which was flagged and approved before
any frontend code was written.

### Prerequisite: `GET /runs/{run_id}/screenshot`

Before any UI work: `Capture.screenshot_path` is an absolute path on the
*backend's* filesystem (e.g. `C:\Users\chris\tradepilot\screenshots\
demo\EURUSD_1h.png`) — meaningless to a browser on its own, and the
backend had no static file serving at all. Flagged as a real blocker (an
endpoint the "don't add endpoints without telling me first" rule
explicitly covers) before writing the chart-display component. Approved
with an exact, security-conscious spec, implemented as given:

- `backend/api/routes_runs.py` — `get_run_screenshot()`. The file to
  serve is derived **entirely** from `run_id`: look up the run, read its
  own `Capture` row, serve that file. No path, filename, or directory is
  ever accepted from the client, in the URL, the query string, or
  anywhere else — this is what rules path traversal out as a class of
  bug here, rather than merely defending against it (verified directly:
  a test sends `?path=/etc/passwd&filename=../../../secrets.txt` and
  confirms the response is byte-identical to the same request without
  those params).
- **Deliberately not a static file mount.** `screenshots/` is never
  exposed as a browsable directory — a LIVE capture is the user's own
  chart and must not be enumerable by filename. Every request is scoped
  to the one run it claims to belong to.
- Before serving, the stored path is resolved (`Path.resolve()`, which
  also collapses any `..` segments and follows symlinks) and checked
  with `is_relative_to()` against `SCREENSHOTS_ROOT` — reusing
  `capture/base.py`'s own `REPO_ROOT` rather than recomputing repo-root
  detection a second way. A path resolving outside `screenshots/` is
  refused with the same generic 404 every other "no image" case gets —
  deliberately vague, so the response never confirms to a client that
  path traversal specifically was what was attempted.
- Every legitimate "no image right now" state is a clear `404`, never a
  `500`: run doesn't exist, run has no capture yet, the capture's
  `status` isn't `SUCCESS` (with the real `error_message` in the detail —
  safe to be specific here, this isn't the security-sensitive case), or
  the file is missing from disk (also safe to be specific: a legitimate
  non-security failure, e.g. the file was moved after the row was
  written).
- Served via FastAPI's `FileResponse` with the content type resolved
  from the file's extension (`mimetypes.guess_type`, falling back to
  `application/octet-stream`).
- `tests/test_api.py` — 7 tests added: a successful capture serves the
  real demo fixture with `content-type: image/png`; a `FAILED` capture
  returns `404` with the real error message; a `Capture` row pointing at
  a file that doesn't exist on disk returns `404`, not `500`; a
  nonexistent run returns `404`; a run with no capture at all returns
  `404`; a stored path resolving outside `screenshots/` (a real file in
  `tmp_path`, well outside the repo) is refused, and its bytes are
  confirmed never to appear in the response; and the query-string-tricks
  test described above.

### The frontend

`frontend/` gained a proper API layer, seven new components, and a
rewritten `App.tsx` that owns all cross-component state; nothing renders
a number it invented itself, everything comes from a `GET`/`POST`
response.

- `frontend/src/api/types.ts` — TypeScript interfaces mirroring every
  `backend/schemas.py` response shape field-for-field, `| null` wherever
  the Python side is `Optional[...]` — so a `FAILED` row's null fields
  are a compile-time-visible case the UI has to handle, not an
  assumption that quietly breaks at runtime.
- `frontend/src/api/client.ts` — the only place the frontend calls
  `fetch`. `ApiError` unifies "the backend answered with a non-2xx
  status" and "the backend never answered at all" (network failure,
  backend not running) into one catchable type with a clear message —
  the second case is what satisfies "handle the backend being
  unreachable with a clear message, not a silent hang."
- **The ANALYZE flow (`App.tsx`'s `handleAnalyzeSubmit`)**: `POST /runs`
  → `POST /runs/{id}/analyze`, exactly as specified. Because `/analyze`
  is synchronous (Milestone 10.5: it doesn't return until the whole
  pipeline has finished), a `setInterval` poll of `GET /runs/{id}` runs
  *concurrently* with the in-flight `/analyze` request, not after it —
  the orchestrator commits each stage's row as it happens, so the poll
  can observe capture, then market data, then analysis, etc. appearing
  one at a time even though the single `/analyze` response won't arrive
  until every stage is done. The poll is stopped the moment `/analyze`
  itself resolves (or throws), and that final response — not the last
  poll tick — is treated as authoritative.
- `components/PipelineProgress.tsx` — derives each of the five stages'
  displayed status (pending / in progress / success / failed) purely
  from whether that stage's row is present in the last `GET /runs/{id}`
  response and, if present, its own `status` field. No timer, no
  animation standing in for real progress — confirmed by a test that
  renders a run with only a real `SUCCESS` capture and checks the
  spinner has moved to exactly the next stage, not by counting elapsed
  time.
- `components/ScoreBreakdown.tsx` — the component the "trace a score to
  its evidence" requirement is actually about: each of the four
  category-based component scores renders in the same row as the
  categorical field(s) that produced it (`trend_score` next to
  `trend_direction` + `trend_quality`, etc. — the exact pairing
  `docs/rubric.md` documents), and `risk_reward_score` renders next to
  `risk_reward_ratio.toFixed(2)`, the same traceability for the one
  component whose evidence is a number instead of a category word.
  `FAILED` renders its `status` and real `error_message`, never blank
  score fields.
- `components/ChartCapturePanel.tsx`, `MarketDataPanel.tsx`,
  `AgentAnalysisPanel.tsx`, `GuardrailResultsPanel.tsx` — one panel per
  pipeline stage, each handling exactly three states honestly: no data
  yet (`EmptyState`), `FAILED` (`ErrorNotice`, the real message from the
  API), and `SUCCESS` (the real values). `ChartCapturePanel` additionally
  handles the image itself failing to load (`<img onError>`) with the
  same `ErrorNotice` treatment, not a broken-image icon.
- `components/DemoBadge.tsx`'s `SourceModeBadge` — the one component
  that renders the DEMO/LIVE label, used in the run list, the detail
  view's chart/market-data panels, and the review panel, so the wording
  can only ever say one thing in one place. A run counts as demo-sourced
  if *either* its capture or its market data came from DEMO mode —
  mirroring `guardrails/rules.py`'s own `SYNTHETIC_DATA` check exactly,
  not a separate frontend judgment call.
- `components/ReviewPanel.tsx` — `APPROVE` is disabled (with the reason
  shown on screen) when a decision already exists, when the guardrail
  outcome is `BLOCKED`, or when there's no guardrail outcome yet at all
  (mirrors `backend/api/routes_runs.py`'s own gating exactly — a run
  with zero guardrail results is treated the same as `BLOCKED`).
  `REJECT` is disabled only once a decision already exists — otherwise
  always available, matching the backend's "REJECTED is permitted on any
  run, in any state" rule. When a decision exists, it's shown (`Decision:
  APPROVED/REJECTED`, timestamp, comment) instead of the input controls.
- **`components/RunList.tsx` — a real design tradeoff, not a shortcut.**
  `GET /runs` (`RunSummary`) has no `mode` or `guardrail_outcome` field
  of its own — only `GET /runs/{id}` (`RunDetail`) does. Enriching
  `RunSummary` to carry either would be a backend change, which wasn't
  pre-approved for this milestone. Two things made a pure-frontend
  workaround the right call instead of asking a second time: (1)
  `Run.status` already *is* the guardrail outcome for any analyzed run —
  `backend/orchestrator.py` (Milestone 10.5) sets it to exactly
  `BLOCKED`/`REQUIRES_REVIEW`/`READY_FOR_REVIEW`, then a human review
  overwrites it to `APPROVED`/`REJECTED`, which is strictly more useful
  in a list than the pre-review outcome alone — so `status` alone
  already satisfies "recent runs with their guardrail outcome and
  status." (2) The DEMO label genuinely has no equivalent on
  `RunSummary`, so `App.tsx`'s `loadRunList()` fires one `GET
  /runs/{id}` per visible row (`Promise.all`, bounded to the list's page
  size of 10) purely to read `capture_mode`/`mode` for the badge — zero
  backend changes, at the cost of N extra requests for a small, capped
  N. Worth knowing about if the list ever needs to show more than a
  couple dozen rows: at that point, adding `guardrail_outcome`/`is_demo`
  to `RunSummary` server-side would be the better trade, but that's a
  backend decision, not one to make unilaterally here.
- **Tailwind v4**, added via `@tailwindcss/vite` (no `postcss.config.js`
  or `tailwind.config.js` needed at this version) — `index.css` is now
  just `@import "tailwindcss";` plus the handful of CSS custom
  properties worth keeping as a single source of truth for the palette.
  `Card.tsx`/`EmptyState.tsx` (Milestone 1) rewritten in Tailwind
  utility classes rather than left on the old hand-rolled CSS, so the
  shell isn't half-migrated.
- **Testing tooling added**: Vitest + React Testing Library +
  `@testing-library/user-event` + jsdom. One real gotcha hit during
  setup: `vitest@4` pulled in its own nested `vite@8` (via
  `@vitest/mocker`) alongside the project's `vite@5.4`, and every test
  run hung for 60s before failing with a worker-pool timeout. Fixed by
  pinning `vitest@^2.1.9`, the last major compatible with Vite 5 — not a
  code bug, a dependency-resolution mismatch. `vite.config.ts` imports
  `defineConfig` from `"vitest/config"` rather than `"vite"` specifically
  so the `test` key type-checks under `tsc -b`.

### Tests

27 frontend tests across 8 files, all against mocked `fetch`/mocked
`api/client` — no test in this milestone makes a real network call:

- `ReviewPanel.test.tsx` — `APPROVE` disabled + reason shown when
  `BLOCKED` (`REJECT` enabled); `APPROVE` enabled when
  `READY_FOR_REVIEW` with no decision; both disabled once a decision
  exists, with the decision shown; the demo notice renders when
  `isDemo`; clicking Approve calls `onApprove` with the typed comment.
- `ChartCapturePanel.test.tsx` — empty state with no capture; the real
  error message (not an empty state, not a broken image) for a `FAILED`
  capture; the image and a DEMO label for a successful demo capture; no
  demo label for a successful LIVE capture.
- `AgentAnalysisPanel.test.tsx` — empty state; `status: FAILED` and the
  real error message (not blank fields) for a failed analysis; all five
  categorical fields plus prose for a successful one.
- `ScoreBreakdown.test.tsx` — empty state; `FAILED` status and message
  for a failed evaluation; **the adjacency test** — queries each score
  row by `data-testid` and asserts the score and its categorical
  evidence (or, for Risk/Reward, the ratio formatted to two decimals)
  are both present *within that same row*, not just somewhere on the
  page.
- `DemoBadge.test.tsx`, `RunList.test.tsx` — the demo label renders for
  `DEMO`, never for `LIVE`, in both the standalone badge and the run
  list; the list shows a clear error (not a hang) when it fails to load.
- `PipelineProgress.test.tsx` — the spinner sits on exactly the first
  stage with no data yet; moves on once real capture data arrives; no
  stage is "in progress" before analysis has started.
- `App.test.tsx` — the full `fetch`-free integration path: submitting
  the form calls `createRun` → `getRun` → `analyzeRun` in order and
  renders the finished run (including its demo label and total score,
  both straight from the mocked `analyzeRun` response); a `BLOCKED` run
  reached via the run list shows its failed capture's real error where
  the chart would be, `APPROVE` disabled, and a successful `REJECT`
  call; a backend-unreachable `listRuns` rejection renders the clear
  "could not reach the backend" message instead of an empty or hung
  list.

Backend: 7 new tests for the screenshot endpoint (listed above). All
211 backend tests pass (24 database + 32 API + 17 capture + 19 market
data + 25 agent + 32 evaluation + 36 guardrails + 10 orchestrator).

### Manual verification

Ran a real end-to-end DEMO analysis through the actual browser (not just
`TestClient`): started both dev servers, filled in the ANALYZE form
(EURUSD, 1h, long, entry/stop/target for RR 2.0), and watched real
mid-flight progress — capture and market data showed complete with their
DEMO badges *while the agent request was still in flight* (a real Claude
call; `ANTHROPIC_API_KEY` is set locally), proving the concurrent-poll
design actually shows real intermediate state, not a fake animation.
Once finished: the chart image rendered (served through the new
screenshot endpoint), all five categorical fields and their prose
appeared, all five scores rendered next to their evidence
(`trend_score` next to `UP · WEAK`, `risk_reward_score` next to
`ratio 2.00`, etc. — a real `WEAK`/`MIXED`/`MARGINAL`/`MODERATE` analysis
this time, scoring 45/100), and all eleven guardrail results listed with
their real reasons, including `SCORE_THRESHOLD` and `SYNTHETIC_DATA`
failing (both review-forcing, not blocking) — so the outcome was
`REQUIRES_REVIEW`, and `APPROVE` was correctly enabled, not disabled.
The run list showed the run with that status and its DEMO badge. Clicked
**Reject** anyway, to exercise that path specifically: the decision
recorded, both `APPROVE`/`REJECT` buttons became disabled immediately
(confirmed via direct DOM inspection, not just visually), the decision
and its timestamp appeared in the review panel, and the run list's row
updated to `REJECTED` — all without a page reload. Dev database reset to
empty afterward.

### What works end to end, and what doesn't

**Works:** create a run → analyze it (real DEMO capture, real DEMO
market data, real-or-honestly-failed agent call) → watch real per-stage
progress → see the chart, quote, prose, categories, every score next to
its evidence, and all eleven guardrail results → approve or reject it →
see the decision persist and the run list update. A DEMO run is labeled
unmistakably everywhere it appears. A failed stage at any point shows
its real error, never a blank section or a hang.

**Doesn't (out of scope for this milestone, not attempted):** no
automatic refresh of a run already open in another tab; the run list is
capped at the most recent 10 and has no pagination controls in the UI
(the API supports paging; the UI doesn't expose it yet); a LIVE-mode
walkthrough wasn't exercised (would need a real browser capture and an
Alpha Vantage key); Milestone 12 (frontend test coverage beyond what's
listed above, and any end-to-end/browser-automation pass) hasn't
started.

## Milestone 12 — documented failure modes and final verification

The last of the twelve planned milestones. Its purpose wasn't new
features — it was proving, with real reproducible evidence, that every
safety mechanism built across Milestones 1–11 actually does its job when
things go wrong, not just when they go right. A demo that only shows a
clean successful run proves nothing about a safety-critical tool; this
milestone is the other half.

### Part 1 — a testing affordance, not a code change per demo

Eleven scenarios were specified. Four of them (RR below minimum,
incoherent trade params, approving a `BLOCKED` run, deciding twice)
already happen through completely ordinary use of the app — no new
mechanism needed, just specific input values, documented in
`docs/failure_modes.md`. The other seven can't be produced through input
alone (they depend on exact timing or on what a live LLM happens to
say), so a genuine testing affordance was built: `force_scenario`, an
optional parameter on `POST /runs/{run_id}/analyze` that deliberately
substitutes a synthetic result for exactly one pipeline stage.

**The three deliberate safety properties this mechanism has, and why
each one exists:**

1. **Gated behind `TESTING_CONTROLS_ENABLED`, a backend `.env` flag that
   defaults to `false`.** `backend/config.py` reads it once at process
   start. `backend/api/routes_runs.py`'s `analyze_run()` checks it
   before doing anything with `force_scenario` and refuses with `403`
   if it's off — a request supplying `force_scenario` has *zero* effect
   against a normally-configured backend, however it's supplied (a typed
   URL, a crafted request, anything). This is what makes the answer to
   "could this affect a real run's honesty" an architectural "no," not
   a promise: turning it on requires editing the backend's own `.env`
   and restarting the process, not anything reachable from a browser
   tab or a request alone.
2. **Every forced run says so, loudly, more than once.** The very first
   thing `run_pipeline()` writes for a forced run, before any stage
   even starts, is a `testing_scenario_forced` audit event in plain
   English. `frontend/src/components/RunDetailView.tsx` checks for that
   exact event and — if present — renders a dashed amber banner reading
   *"Testing run — not a real analysis"* at the very top of the detail
   view, above everything else. Every synthetic value's own text (error
   messages, prose) starts with `TESTING:`. There's no path to seeing a
   forced run's result without also seeing, immediately, that it was
   forced.
3. **Only ever fabricates a stage's INPUT to the next stage, never a
   score or a verdict.** `backend/orchestrator.py`'s `force_scenario`
   handling touches capture, market data, and the agent's qualitative
   output only — `evals/trade_evaluator.py` and `guardrails/rules.py`
   are never touched, never bypassed, and never even aware
   `force_scenario` exists. A forced "perfect score" run's 100 is
   computed for real from synthetic-but-realistic category words, the
   exact same code path a real Claude response would go through — which
   is what makes scenario 9 an actual *proof* that `SYNTHETIC_DATA`
   catches a perfect score, not just a claim that it would.

**Implementation:**

- `backend/config.py` — `TESTING_CONTROLS_ENABLED` (bool, default
  `False`).
- `backend/orchestrator.py` — `FORCE_SCENARIOS` (the seven allowed
  values: `capture_fails`, `capture_stale`, `market_data_fails`,
  `market_data_stale`, `agent_fails`, `high_uncertainty`,
  `perfect_demo_score`), `run_pipeline()` gained an optional
  `force_scenario` keyword argument (`None` — the only value any real
  run ever uses — leaves every stage exactly as it was before this
  parameter existed). `capture_fails`/`market_data_fails` synthesize a
  `FAILED` result shaped identically to a real one, labeled with the
  real configured `LIVE`/`DEMO` mode so the UI's badges stay accurate.
  `capture_stale`/`market_data_stale` run the *real* provider (a
  genuine successful capture/quote) and then override just the
  timestamp two hours into the past (`dataclasses.replace()`) before
  persisting — comfortably past either default freshness threshold.
  `agent_fails`/`high_uncertainty`/`perfect_demo_score` never make a
  real Claude call (free, deterministic, fully reproducible) — a small
  `_SYNTHETIC_AGENT_PROFILES` table maps each to the categorical fields
  and uncertainty level a synthetic `SUCCESS` `AgentAnalysisResult`
  uses; `agent_fails` alone returns `FAILED`. `force_scenario` is
  validated against `FORCE_SCENARIOS` a second time inside
  `run_pipeline()` itself (defense in depth, the same pattern every
  other validated value in this codebase already follows).
- `backend/api/routes_runs.py` — `analyze_run()` gained an optional
  `force_scenario` query parameter, documented in its own OpenAPI
  description as testing-only. `403` if `TESTING_CONTROLS_ENABLED` is
  off; `422` if the value isn't one of `FORCE_SCENARIOS`; otherwise
  passed straight through to `run_pipeline()`.
- `.env.example` — `TESTING_CONTROLS_ENABLED=false` documented with an
  explicit warning never to leave it on for a deployment anyone might
  mistake for real.
- **Frontend:** `components/TestingControls.tsx` — a dropdown in the
  Analyze panel, deliberately styled to look like nothing else in this
  app (dashed amber border, explicit "TESTING ONLY" label) so it can
  never be mistaken for a real control. Always rendered — if the
  backend has testing controls disabled, choosing a scenario just
  surfaces the real `403` in the normal error banner, the same as any
  other API error; there's no separate frontend-only gate to keep in
  sync with the backend one. `api/types.ts`'s `FORCE_SCENARIOS` mirrors
  the backend's list (value, label, and the expected outcome, shown
  under the dropdown once a scenario is picked). `AnalyzeForm.tsx`
  threads the choice through to `api.analyzeRun(runId, forceScenario)`;
  the submit button itself relabels to *"Analyze (forcing a test
  scenario)"* and turns amber when a scenario is selected, one more
  layer of "this isn't a normal Analyze click." `RunDetailView.tsx`'s
  banner is described above.

### Part 2 — `docs/failure_modes.md`

A new, standalone document: one section per scenario (what to click/type
to trigger it, what the system does, which specific guardrail fires and
its real output, what the UI shows, and *why* that behavior is correct —
not just a description, an argument), written for someone who has never
seen this codebase before. Every piece of evidence quoted in it (error
messages, scores, guardrail reasons) is real output copied from actual
runs executed against the live backend while writing it, not
invented or paraphrased from the code.

### Part 3 — tests

`tests/test_failure_scenarios.py` — 14 tests, one per scenario (11) plus
three covering the mechanism itself: `force_scenario` refused with `403`
when `TESTING_CONTROLS_ENABLED` is off, an unrecognized value refused
with `422`, and an ordinary analysis with no `force_scenario` at all
confirmed completely unaffected (no `testing_scenario_forced` audit
event, real agent output flows through untouched). Every test goes
through the real API (`TestClient`) against the real orchestrator and
real `DemoProvider`/`DemoMarketDataProvider` fixtures — these are
genuine end-to-end tests, not isolated unit tests re-testing logic
`tests/test_guardrails.py`/`tests/test_evaluation.py` already covered
with hand-built fixtures.

All 218 backend tests pass (24 database + 32 API + 17 capture + 19
market data + 25 agent + 32 evaluation + 36 guardrails + 10 orchestrator
+ 14 failure scenarios — up from 204). All 32 frontend tests pass (up
from 27; `TestingControls.test.tsx` new, `App.test.tsx` gained one test
for the forced-scenario flow and banner).

### Manual verification

Ran all eleven scenarios against a real running backend
(`TESTING_CONTROLS_ENABLED=true`), gathering the exact evidence quoted
in `docs/failure_modes.md` directly from real HTTP responses — not
reasoned about, executed. Additionally verified scenario 1 through the
actual browser UI: selected "Capture fails" from the dropdown, confirmed
the submit button relabeled to *"Analyze (forcing a test scenario)"*,
clicked it, and confirmed via direct DOM inspection that the detail view
showed the dashed amber *"Testing run — not a real analysis"* banner
with the real forced-scenario message, the Chart capture card showing
*"Chart capture failed"* with the real `TESTING:` error (no broken
image), the Agent analysis and Evaluation cards both showing *"Status:
FAILED"*, the overall status `BLOCKED`, and the Approve button disabled
with the exact blocking reason printed above it. (Visual screenshots
aren't renderable in this non-interactive session's browser pane — DOM
inspection confirmed byte-identical content to what a screenshot would
show. Genuine screenshots are trivial to take when running this
locally, which `docs/failure_modes.md` assumes.) Dev database and local
`.env` (`TESTING_CONTROLS_ENABLED` set back to `false`) both reset
afterward.

### Part 4 — final review, verified by direct code inspection, not asserted

**Does any code path still allow a trade to be placed, submitted, or
simulated?** No. `grep -rniE` across every `.py` file in this repo for
`place_order|submit_order|execute_trade|broker|order_execution|
buy_order|sell_order|create_order|cancel_order` returns zero matches
outside documentation. There is no broker client, no order-execution
library dependency, and no network call anywhere in this codebase whose
target is anything other than: TradingView (read-only chart viewing,
`capture/live_provider.py`), Alpha Vantage (read-only quote fetching,
`tools/market_data.py`), and the Anthropic API (`agents/trade_agent.py`,
whose own prompts additionally instruct the model never to phrase
anything as an instruction to buy, sell, enter, or exit). The only two
terminal states any run can ever reach — `APPROVED` and `REJECTED` — are
both plain database writes with no side effect beyond themselves.

**Does any code path allow an approved state without a human decision?**
No. `grep -rn '"APPROVED"'` across the codebase shows the string
appears in exactly one place where it's ever *written* to `Run.status`:
`backend/api/routes_runs.py`'s `review_run()`, and only as
`payload.decision` — a value that arrived in an actual `POST
/runs/{run_id}/review` HTTP request body, validated against
`ALLOWED_DECISIONS = {"APPROVED", "REJECTED"}`
(`backend/schemas.py`) before this function is ever entered. Every other
call site of `crud.update_run_status()` — the only function that writes
`Run.status` at all — either hardcodes the literal `"ANALYZING"` or
writes `report.outcome.value`, and `GuardrailOutcome`
(`guardrails/rules.py`) has exactly three members
(`BLOCKED`/`REQUIRES_REVIEW`/`READY_FOR_REVIEW`) — `"APPROVED"` isn't a
value that enum can even produce. There is no code path from pipeline
completion to `APPROVED` that doesn't pass through a real HTTP request
carrying a human's explicit decision.

**Can the agent's output still influence a score except through the
documented categorical fields?** No. `evals/trade_evaluator.py` reads
exactly seven attributes off `AgentAnalysisResult`: `.status` and
`.error_message` (both used only to short-circuit a failed analysis,
never to compute a score), `.trend_direction`, `.trend_quality`,
`.structure_quality`, `.setup_quality`, `.context_risk`, and
`.uncertainty`. Grepping the file for any reference to
`.analysis_text`/`.trend_assessment`/`.structure_assessment`/
`.setup_assessment` — the four prose fields — returns zero matches. The
prose exists on every successful `AgentAnalysisResult` and is shown to
the human reviewer in the UI, but the scoring code has no line that
touches it.

**Is there any remaining silent fallback, invented value, or fabricated
result anywhere in the pipeline?** None found. Every `except` clause in
`capture/`, `tools/market_data.py`, `agents/trade_agent.py`,
`evals/trade_evaluator.py`, and `database/crud.py` catches a specific
exception type (never a bare `except:`) and every one of them returns a
`FAILED`/error result carrying the real exception text — none return a
default value, a placeholder, or a previously-cached result.
`CaptureManager`/`MarketDataManager` each construct exactly one provider
in `__init__`, based on the configured mode, and every subsequent
`.capture()`/`.get_quote()` call only ever reaches that one
provider — there is no code path, anywhere, that calls the other
provider after the first one fails. No hardcoded non-zero
`price`/`screenshot_path` default exists anywhere in either fetch path.

**What is the weakest part of this project right now, honestly?**
Two things, in order:

1. **There is no authentication or rate limiting on the API at all.**
   Every endpoint — including `POST /runs/{run_id}/analyze`, which can
   make a real, billed Anthropic API call — is reachable by anyone who
   can reach the port, with no login, no API key, no per-caller limit.
   For a single developer running this on `localhost`, exactly as
   designed and documented throughout this project, that's a non-issue.
   It stops being one the moment this is ever reachable from anywhere
   but `localhost` — a misconfigured `BACKEND_HOST` or a port forwarded
   without thinking about it would let anyone spend real money by
   spamming analyze requests, with nothing in this codebase to stop
   them. This has been true since Milestone 4 and was never in scope to
   fix, but it's the single most real, immediately exploitable gap in
   the project as it stands today.
2. **LIVE mode is comparatively unproven.** Every guardrail, every
   scenario in this milestone, and nearly every piece of manual
   verification across all twelve milestones has been exercised in
   DEMO mode. `capture/live_provider.py`'s Playwright-driven TradingView
   scraping and `tools/market_data.py`'s real Alpha Vantage integration
   are unit-tested with mocks, but neither has been run against the
   real internet in the course of this project. Nothing about that is
   architecturally unsafe — a real scraping failure or a real API
   outage would show up exactly the way this milestone proves failures
   always show up: a clear `FAILED` result, never a silent one — but
   "the failure path is honest" and "the happy path actually works
   against the real internet" are different claims, and only the first
   one has been demonstrated here.

## Rebuilding the database

`init_db()` only ever adds tables that don't exist yet — it never alters
an existing table. So if a model changes shape (a column is added,
removed, or its type changes), the existing `database/tradepilot.db` file
won't pick that up automatically. Since this is still a dev-only database
with no real audit data to preserve, the fix is to delete the file and
recreate it from the current models:

```bash
rm database/tradepilot.db          # PowerShell: Remove-Item database\tradepilot.db
python -m database.init_db
pytest                              # confirm the new schema is valid
```

Once real audit data needs to be preserved across a model change, delete-
and-recreate stops being an option — that's when a migration tool (e.g.
Alembic) would need to be introduced. Not needed yet; noted here so it
isn't forgotten.

## fix: agent response truncation on live runs

Post-6C-baseline defect fix, scoped narrowly per the working agreement —
no new milestone, no behavior change beyond what the fix needed.

**The bug, as reported from a real LIVE run:** capture succeeded in 14s,
market data succeeded (a real Alpha Vantage quote, `1.15624998`, 16s
old), all four upstream guardrails passed — and the agent stage still
came back `FAILED` with `"Claude's response could not be used: response
was not valid JSON: Unterminated string starting at: line 3 column 23
(char 1241)"`.

**Diagnosis, not assumption.** The instruction was explicit: verify
before concluding this was `max_tokens` truncation rather than some other
malformed-response cause. `agents/trade_agent.py` had never inspected
`response.stop_reason` at all — every parse failure, whatever its real
cause, produced the identical generic `"response was not valid JSON"`
message. That gap was fixed first (see below), specifically so future
occurrences of this bug diagnose themselves instead of requiring this
same manual reasoning again. Once addable, `stop_reason` on a real
follow-up LIVE call confirmed `"max_tokens"` directly — not inferred
from the truncation point.

**Root cause, once actually visible:** `DEFAULT_MAX_TOKENS` was `1024`,
and `prompts/analysis_prompt.md`'s `analysis_text` field had **no length
guidance at all** — not even a mention of what it should contain, let
alone a bound — while the four other "What to do" bullets (Trend,
Structure, Setup, Uncertainty) had specific prompts but likewise no
sentence limit. `analysis_text` is also the *first* key in the JSON
template, so a verbose, unbounded response there could consume the
entire token budget before the model ever reached the five categorical
fields the rubric actually scores from — precisely the failure mode this
bug report showed (cut off at char 1241, well into what was very likely
`analysis_text` still being written).

**The fix, three parts, exactly as scoped — no retry logic, no
partial-JSON recovery, a truncated or malformed response is still and
will always be a `FAILED` analysis:**

1. **`stop_reason` is now checked before parsing, not after.**
   `TradeAgent.analyze()` extracts the response text, then checks
   `getattr(response, "stop_reason", None) == "max_tokens"` *before*
   calling `_parse_response()`. If true, the analysis fails immediately
   with a distinct message naming the real cause explicitly:
   `"Claude's response was truncated: generation stopped because it hit
   the max_tokens limit (N) before finishing (stop_reason='max_tokens'),
   not because of a parsing problem..."` — never routed through the
   generic JSON-parse error path. `getattr(..., None)` rather than a
   direct attribute access, so a response object that doesn't carry
   `stop_reason` at all (not a real anthropic SDK shape, but defensive
   regardless) can't crash the agent — it's simply treated as
   not-truncated and parsed normally.
2. **`max_tokens` raised from `1024` to `2048`, and made an actual
   constructor parameter** (`TradeAgent(max_tokens=...)`, mirroring the
   existing `timeout_seconds` pattern) rather than a hardcoded literal at
   the API call site — so it's both configurable and quotable in the
   truncation error message (the real configured limit, not a
   restated constant). Sizing: four prose fields bounded to 1-3
   sentences each (see below) plus five one-word categorical fields plus
   JSON structure overhead comes to roughly 400-800 tokens for a
   realistic response; 2048 leaves a comfortable ~2.5-5x margin above
   that without inviting runaway generation. This is not a guess dressed
   up as sizing — it's the actual shape of the JSON schema
   `agents/trade_agent.py` requires, counted field by field.
3. **`prompts/analysis_prompt.md` tightened, since raising `max_tokens`
   alone would only move the ceiling, not fix the actual habit of
   writing unbounded prose:**
   - The "What to do" section now opens with an explicit "1-3 sentences
     per point below — not a paragraph" instruction, applying to every
     prose field.
   - `analysis_text` — previously present in the JSON template with
     literally no description anywhere in the prompt — now has its own
     bullet: "1-3 sentences summarizing the setup as a whole... not a
     place to repeat the trend/structure/setup points below at length."
   - A closing reminder was added alongside the existing "no score, no
     trade instruction" rules: "Keep every prose field to a few
     sentences at most — the category fields above are what get scored,
     not how much you write." This doesn't change what's scored (the
     rubric has read only the categorical fields since the Milestone 8
     revision) — it just makes that fact explicit to the model itself,
     since nothing before this fix ever told it prose length was
     pointless to optimize for.

`system_prompt.md` and the categorical-field rubric itself were **not**
touched — this is a prompt-brevity and response-handling fix, not a
scoring or rules change.

- `tests/test_agent.py` — 6 tests added (31 total, up from 25):
  a truncated response (`stop_reason="max_tokens"`) is reported with
  "truncated"/"max_tokens"/the real configured limit in the message, and
  never the generic "not valid JSON" wording; a *well-formed* JSON
  response that nonetheless carries `stop_reason="max_tokens"` is still
  treated as a failure with every field `None` (proving this fix adds no
  partial-JSON recovery — truncation is checked before parsing succeeds
  or fails, not as a fallback after a parse error); a normal
  `stop_reason="end_turn"` response is not misreported as truncated; a
  response object missing `stop_reason` entirely doesn't crash and
  parses normally; `max_tokens` defaults to `2048` and is actually passed
  to `client.messages.create()`; `max_tokens` is configurable via the
  constructor and the configured value is what's actually sent. The
  existing `_fake_client()` test helper gained a `stop_reason` parameter
  defaulting to `"end_turn"` (what a real complete response actually
  carries) so every pre-existing test reflects a realistic response
  shape without needing individual changes.

All 224 backend tests pass (33 database + 32 API + 17 capture + 19
market data + 31 agent + 32 evaluation + 36 guardrails + 10
orchestrator + 14 failure scenarios — up from 218). All 32 frontend
tests still pass, unaffected (this fix touches only
`agents/` and `prompts/`).

**Manually verified against a real LIVE run** (temporarily
`CAPTURE_MODE=live`/`MARKET_DATA_MODE=live` in `.env`, restored to
`demo` afterward) — the exact scenario the bug was reported from: real
Playwright TradingView capture (`SUCCESS`, 9s), a real Alpha Vantage
quote (`1.15625593`, matching the same real EURUSD price range the
original report showed), and a real Claude call that this time returned
a complete, well-formed response with concise prose and all five
categorical fields populated (`SIDEWAYS`/`WEAK`/`MIXED`/`UNCLEAR`/
`ELEVATED`, `uncertainty=HIGH` — the agent correctly flagged that the
test's demo-era trade parameters, entry/stop/target around 1.09-1.105,
didn't correspond to the real current price near 1.156). The evaluator
computed a real score (28/100, all four subjective components at or
near their HIGH-uncertainty ceiling of 8, `risk_reward_score=20` exempt
from the cap) and guardrails produced `REQUIRES_REVIEW` for real,
legitimate reasons (`UNCERTAINTY_ACCEPTABLE` and `SCORE_THRESHOLD`
failing; `SYNTHETIC_DATA` correctly *passing* since this run was
genuinely LIVE-sourced, not `DEMO`). No truncation, no JSON error. Dev
database and `.env` both reset afterward.

## 7A Iteration 1 — agent-proposed trade levels, never self-scored

The first 7A iteration. The design (a new `agent_proposals` table, not new
columns on `agent_analyses`; coherence checking done once in
`backend/orchestrator.py` by reusing `evals/trade_evaluator.py`'s
`compute_risk_reward()`; an accept-proposal endpoint that creates a new
run rather than rescoring the old one) was proposed and confirmed before
any code was written — see "The 7A plan" and "The 7A-specific invariant"
in [docs/handoff.md](handoff.md), which this entry doesn't repeat.

**The tension this iteration exists to resolve.** `risk_reward_score` is
the one rubric component computed purely from arithmetic on real
numbers — every other component is capped by the agent's own stated
uncertainty, but Risk/Reward is exempt, because it's a fact about numbers
the user typed in, not a reading of an ambiguous chart. That exemption
only holds because the agent has zero influence over which numbers go
into that arithmetic. The moment the agent is allowed to propose its own
entry/stop/target, an agent that wanted to game the rubric could simply
propose levels arithmetically engineered to `RR = 2.0` or higher and
guarantee itself the one component uncertainty can't touch. So a
proposal has to be able to exist without ever becoming scoring input
until a human explicitly says otherwise — that's the entire shape of
this iteration.

**Two hardening requirements were added to the approved design before any
code was written, both aimed at the same thing: a rule that only lives in
a prompt isn't a rule, it's a request.**

1. **The numeric carve-out needed enforcement, not just a prompt
   instruction.** The original plan already had `_parse_response()`
   reject any numeric field except the three proposal fields — but
   nothing stopped a field NAMED `probability`/`confidence`/`percentage`/
   `likelihood`/`odds` from slipping through as long as its *value*
   wasn't numeric yet (`"confidence": "high"` is exactly as much an
   attempted score-substitute as `"confidence_score": 87`, and the
   pre-existing numeric-extra-field check only ever looked at value
   types). Fixed by adding a keyword-based rejection alongside the
   numeric one: any extra field whose name contains `probability`,
   `percent`, `confidence`, `likelihood`, or `odds` is rejected outright,
   regardless of its value's type. Both checks now feed one unified
   error path in `agents/trade_agent.py`'s `_parse_response()`.
2. **A fourth state the original three-state design didn't cover.**
   `proposal_has_proposal` and the four level fields
   (`proposal_direction`/`proposal_entry`/`proposal_stop`/
   `proposal_target`) can, in principle, disagree with each other:
   `has_proposal=false` with levels populated, or `has_proposal=true`
   with a level left `null`. Neither is "declined" or "accepted" — both
   are a malformed response, and `_parse_response()` now rejects both
   directions explicitly rather than coercing either one into whichever
   state looks closest. `proposal_has_proposal` itself also has to be a
   real JSON boolean — checked with `isinstance(x, bool)`, not a
   truthiness test, specifically because Python's `bool` is a subclass of
   `int` (`isinstance(1, bool)` is `False`) — so `0`, `1`, `"true"`, and
   `"yes"` are all rejected rather than silently treated as boolean-ish.

**Schema (`database/models.py`):** a new `agent_proposals` table,
`run_id` unique (a run is analyzed at most once, so at most one
proposal). `has_proposal=False` rows have every other column `NULL`.
`has_proposal=True` rows always have `direction`/`entry`/`stop`/`target`
populated, then split on `is_coherent`: coherent has a real
`risk_reward_ratio` and a `NULL` `coherence_error`; incoherent has the
reverse. A `CHECK` constraint enforces this three-way shape at the
database level — the same double-enforcement pattern (Python validation
in `database/crud.py`, a `CHECK` constraint as the backstop) every other
validated column in this file already uses, and the same "never guess,
always record the real reason" rule `compute_risk_reward()` itself
already follows for the run's own trade params. `direction`'s allowed
set (`LONG`/`SHORT`) is duplicated from `agents.trade_agent.
ALLOWED_PROPOSAL_DIRECTIONS`, not imported — `database/` stays a leaf
module, same reasoning as `AGENT_CATEGORICAL_FIELDS` — kept from
drifting apart by a dedicated test.

A row is only ever written when the agent analysis itself **succeeded**.
No row at all means the question was never reached (capture/market-data/
agent all have to succeed first); `has_proposal=False` means the agent
was asked and explicitly declined. Those are different facts, and only
the second one gets a row — there's no third "not applicable" state to
encode. This is also why `POST /runs/{run_id}/accept-proposal` treats "no
proposal row" and "declined proposal" identically (both `409`): either
way there's nothing to accept.

**Coherence checking happens exactly once, in `backend/orchestrator.py`'s
new `_persist_agent_proposal()`,** called right after a successful
`AgentAnalysis` row is written. It calls `evals.trade_evaluator.
compute_risk_reward()` on the *proposed* levels — the exact same function
`guardrails/rules.py`'s `TRADE_PARAMS_VALID` rule already reuses for the
run's own trade params, not a second implementation. This has zero
bearing on the current run's own evaluation or guardrails:
`evaluate()` and `evaluate_guardrails()` are never called with anything
proposal-related, and neither function was touched by this iteration —
confirmed directly by a test that runs the identical `EvaluationResult`
through `evaluate()` with and without a proposal attached to the
`AgentAnalysisResult`, including one deliberately engineered to a
"perfect" `RR=10.0`, and asserts all three outcomes are byte-identical.
A second test greps `evals/trade_evaluator.py`'s own source for any
reference to the five `proposal_*` attribute names and confirms zero
matches — the same style of direct-inspection proof Milestone 12's final
review used for the prose fields.

Coherence checking couldn't live in `agents/trade_agent.py` (would create
a circular import with `evals/`) or in `database/crud.py` (would break
the standing "`database/` stays a leaf module" rule) — `backend/
orchestrator.py` is the one place that already depends on both.

**`POST /runs/{run_id}/accept-proposal`** never rescores or re-analyzes
the source run. It creates a **brand-new** `Run`, seeded with the
proposal's `direction`/`entry`/`stop`/`target` as that new run's ordinary
`Run.entry`/`stop`/`target` — indistinguishable from a run someone typed
in by hand, except for a new `Run.accepted_from_run_id` column (a
self-referential FK, `NULL` on every ordinary run) recording where the
levels actually came from. The new run still needs its own
`POST /runs/{new_run_id}/analyze` call like any other run — accepting is
not itself an analysis. Both runs get an audit-trail entry
(`accepted_from_proposal` on the new run, `proposal_accepted` on the
source run), so the record of "a human made this choice" lives on both
sides, not just one. `409` if the run has no proposal at all or the
proposal was declined; `404` if the run doesn't exist. A deliberate
non-restriction: an **incoherent** proposal can still be accepted — the
new run just carries those same incoherent numbers and fails
`TRADE_PARAMS_VALID` once analyzed, exactly as it would if a human had
typed bad numbers in by hand. Accepting doesn't imply endorsing the math,
so no special-casing was added to forbid it. Also deliberately
unrestricted: nothing stops the same proposal from being accepted more
than once (each acceptance is independent and side-effect-free — it only
ever reads the source run's stored proposal, never mutates it), so
repeated accepts simply spawn multiple new runs.

**The prompt side (`prompts/analysis_prompt.md`, `prompts/
system_prompt.md`)** frames a proposal explicitly as a hypothetical, not
an instruction: "if someone were describing this setup with specific
levels, here is what they might look like," reviewed by a human before
it's ever acted on. The existing "never phrase anything as an instruction
to buy/sell/enter/exit" rule is stated to apply to a proposed level
exactly as much as to everything else the agent says — proposing 1.0950
as an entry is a description, not a recommendation. Both prompts also now
say plainly that the *only* numbers the agent's response is ever allowed
to contain are the three proposed levels, and only when
`proposal_has_proposal` is `true` — reinforcing the code-level rule, not
substituting for it (see hardening requirement 1 above for why "the
prompt says so" was never going to be enough on its own).

**Agent (`agents/trade_agent.py`):** `AgentAnalysisResult` gained five
fields — `proposal_has_proposal`, `proposal_direction`,
`proposal_entry`, `proposal_stop`, `proposal_target` — all `None` on a
`FAILED` analysis, matching every other qualitative field's pattern.
`EXPECTED_FIELDS` grew from 10 to 15 JSON keys. Every existing
construction site across the codebase (2 in `agents/trade_agent.py`, 3 in
`backend/orchestrator.py`, plus test fixtures in `tests/test_evaluation.py`,
`tests/test_guardrails.py`, `tests/test_orchestrator.py`, and
`tests/test_failure_scenarios.py` — 12 in total) needed updating to pass
the five new fields explicitly, the same "no silent defaulting" pattern
the Milestone 8 revision's categorical fields already established for
this same dataclass. `force_scenario`'s synthetic agent profiles
(Milestone 12) always decline a proposal — this mechanism still never
makes a real Claude call, and simulating a proposal was out of scope for
what it exists to prove.

**Tests, 47 added (271 total, up from 224):**

- `tests/test_agent.py` — 22 added (53 total, up from 31): a well-formed
  proposal maps into the four fields correctly; a decline maps to all
  `None`; direction normalization and out-of-set rejection (mirroring the
  existing categorical-field pattern); six tests proving hardening
  requirement 1 (`probability`/`percentage`/`confidence`/`likelihood`/
  `odds`-named extra fields rejected regardless of value type, including
  one that's numeric *and* keyword-matched, proving the two checks aren't
  mutually exclusive); four tests proving a numeric value is still
  rejected everywhere except the three carved-out fields (numeric
  `proposal_direction`, numeric `analysis_text`/`uncertainty` alongside a
  well-formed proposal, a numeric-looking *string* in `proposal_entry`);
  four tests proving `proposal_has_proposal` rejects `0`/`1`/`"true"`/
  `"yes"`; four tests proving both directions of the fourth-case mismatch
  are rejected (declined-with-populated-levels, accepted-with-a-null-
  level × two fields), plus a missing-field test.
- `tests/test_database.py` — 13 added (46 total, up from 33): coherent
  and incoherent proposal round trips, a declined-proposal round trip, the
  `Run.proposal` relationship, application-level rejection of an
  out-of-set direction and of a coherent/incoherent proposal missing its
  required ratio/error, three database-level `CHECK`-constraint rejection
  tests (out-of-set direction, `has_proposal=true` with a null level,
  `has_proposal=false` with a populated level, a coherent proposal
  missing its ratio), the direction drift-guard test, and
  `Run.accepted_from_run_id` round-tripping through a real commit+refresh.
- `tests/test_evaluation.py` — 2 added (34 total, up from 32): the
  evaluator-identical-with-or-without-a-proposal test (including the
  engineered-`RR=10.0` case) and the source-grep test, both described
  above.
- `tests/test_orchestrator.py` — 10 added (20 total, up from 10): a
  coherent proposal recorded and confirmed not to affect the run's own
  `total_score` (still 76) or `TRADE_PARAMS_VALID`; an incoherent
  proposal recorded with its real reason and no ratio, same
  non-interference confirmed; a decline recorded; the audit event text
  confirmed; `accept-proposal` success with full provenance (new run's
  fields, `accepted_from_run_id`, both runs' audit events, source run's
  evaluation confirmed unchanged); accepting an incoherent proposal
  succeeds; `409` for a declined proposal, an unanalyzed run, and a run
  with no proposal row at all (failed capture, agent never called);
  `404` for a nonexistent run.

**Manually verified against the real running server, not just
`TestClient`** (see the transcript in this session for the exact
commands): recreated `database/tradepilot.db` (confirmed the new
`agent_proposals` table appears), started the real `uvicorn` process,
confirmed `/runs/{run_id}/accept-proposal` appears in the real OpenAPI
schema, created a real run, seeded a coherent proposal directly via
`database.crud` (standing in for what a real orchestrator run produces —
the same seeding technique Milestone 10's manual verification used before
an orchestrator existed), confirmed `GET /runs/{id}` showed it, called
`accept-proposal` for real and got back a new run with
`accepted_from_run_id` pointing at the source run and the proposed levels
as its own `entry`/`stop`/`target`, confirmed both runs' real audit
trails (`accepted_from_proposal` on the new run, `proposal_accepted` on
the source run), and confirmed a second `accept-proposal` call on the new
run (which has no proposal of its own) was refused with a real `409`.
Dev database reset to empty afterward.

**Deferred, not forgotten (superseded — see the addendum below):** the
paragraph above reflects the state at the moment this entry was first
written. Both the deferral and the "just seed a proposal by hand" manual
verification it describes turned out to be premature — see
"7A Iteration 1 addendum" immediately below for why, and for what
actually shipped.

## 7A Iteration 1 addendum — live verification, the DEMO fixture gap, and the UI

Everything above this addendum was built and unit-tested, but verified
manually by *seeding* a proposal directly via `database.crud` rather than
by watching a real Claude call produce one. That gap was flagged
explicitly, for a specific reason: **in 6C, `analysis_text` truncation
passed every test and only surfaced on a live run** (see "fix: agent
response truncation on live runs" above) — the same risk class applies
here. The new prompt fields and the real parsing path were, at that
point, completely unexercised against a real model. This addendum is the
live verification, what it found, the fix, and the UI — all built before
`7a-iteration-1` was allowed to move.

### The first live pass: two declines, and why that was the right question to ask

Two real Claude calls, DEMO capture + DEMO market data (the original
`EURUSD_1h.png` fixture), no mocking of `TradeAgent` at all:

- **RUN A** (`80da6bc69e304dff80d43159ac3d127f`, no user-supplied trade
  params) and **RUN B** (`832f688577914e35840e62f461407459`, user levels
  long 1.0950/1.0900/1.1050) both came back `"proposal_has_proposal":
  false`, valid JSON on the first attempt, `stop_reason="end_turn"` both
  times — enforcement never had to reject anything. RUN B's own
  evaluation scored normally from the user's levels (`total_score=45`),
  in a completely separate table from the (empty) proposal, exactly as
  designed.
- Both runs are preserved, untouched, in `database/tradepilot.db` as
  direct evidence the declined path works end to end against a real
  model — they were not reset or deleted.

**Diagnosis, not an excuse:** the agent's own prose in both runs said
plainly there was nothing to propose against (`setup_quality: NONE` /
`MARGINAL`, "no crisp, high-confidence setup stands out"). The committed
`EURUSD_1h.png` fixture (Milestone 5) is a *deliberately* abstract
placeholder — a generic bar series plus a large "SAMPLE IMAGE" banner —
built to exercise the five categorical fields, which degrade gracefully
on a vague image (the agent always has `UNCLEAR` to fall back on). A
proposed trade level has nothing to degrade to: it needs an actual
visible price structure to anchor a stop and target to. **The fixture was
adequate for 6C's categorical fields and not adequate for 7A's
proposals.** The prompt was not touched, on purpose — declining was the
prompted-for, correct behavior for that specific image, not a bug to
patch around by changing the instructions.

### The second live pass: real structure, real proposals

`dry-run.ps1` swept 5 real LIVE candidates (real Playwright capture, real
Alpha Vantage quote, real Claude call each) to find one with genuinely
readable structure rather than guessing. EURUSD 4h won clearly (`UP/
MODERATE` trend, `MIXED` structure, `ACCEPTABLE` setup, score 64,
`READY_FOR_REVIEW`) — and that sweep run itself
(`ed4e50b2e5b34d389f9734145dc7f53f`) had already produced a real,
coherent proposal: `LONG 1.156/1.149/1.17`, `risk_reward_ratio≈2.0`,
`is_coherent=true`, stored in `agent_proposals` — alongside a real
`total_score=64` computed from the user's own levels in `evaluations`,
confirming both live in separate places for a genuinely live run, not
just a DEMO-seeded one.

**Alpha Vantage's free-tier daily quota (25 requests) was exhausted
partway through that sweep** — confirmed directly by the error text
(`"our standard API rate limit is 25 requests per day"`), and it blocked
a dedicated, freshly-instrumented LIVE RUN A. The orchestrator's own "no
silent LIVE→DEMO fallback" invariant did exactly its job: market data
failed honestly, the agent was never called (capture and market data must
both succeed first), no data was fabricated. This project has no
visibility into Alpha Vantage's exact remaining quota or reset time
beyond that error text — worth checking the account dashboard directly if
this matters again before the free-tier window resets.

**The resulting hybrid, run for real and labeled as exactly what it
is:** `cd25a285ea574501bf41a9a4cec26c32` — a real Playwright LIVE capture
of a fresh EURUSD 4h chart, a real Claude call, but a DEMO market quote
(Alpha Vantage exhausted), deliberately *paired* to the captured chart's
own visible price (1.1558, its last real close) rather than the
ordinary, unrelated demo price (1.0921) — pairing a quote nowhere near
what's on the chart would have produced a nonsensical proposal and a bad
fixture. Recorded in that run's own audit trail via a
`hybrid_verification_note` event so nothing about this run's provenance
depends on this document. Result: `proposal_has_proposal: true`,
`LONG 1.1540/1.1480/1.1650`, `risk_reward_ratio≈1.83`, `is_coherent:
true`, valid JSON, `stop_reason="end_turn"` — enforcement had nothing to
reject. **The leak test, proven live, at the orchestrator level, with no
user-supplied trade params:** `evaluations[0].status="FAILED"`,
`risk_reward_ratio`/`risk_reward_score`/`total_score` all `NULL`
(`TRADE_PARAMS_VALID` failing because there were no user params at all),
while `agent_proposals.risk_reward_ratio=1.833...` is real, computed, and
stored in a completely separate row. The same property this run proved
live is also proven by a deterministic, always-run test:
`test_orchestrator_never_lets_a_coherent_proposals_ratio_reach_the_runs_own_evaluation`
in `tests/test_orchestrator.py`.

**Answering the three questions plainly, for both live passes together:**
the model populated proposal fields on the real-structure chart (twice —
the sweep run and the hybrid run) and declined on the abstract fixture
(twice); enforcement never had to reject anything on any of the four real
calls (no boolean violation, no keyword violation, no incoherent
proposal, no has_proposal/levels mismatch) — every violation this
iteration guards against was proven exclusively by the 22 hand-built
adversarial fixtures in `tests/test_agent.py`, which remains the
authoritative enforcement evidence; live calls only ever tested whether a
well-behaved model produces a well-shaped response, which it did, four
times out of four.

### An empirical observation: proposed RR varies with what the agent was shown

Only one run is both no-user-levels *and* has a populated proposal —
`cd25a285ea574501bf41a9a4cec26c32` — so it's the only non-trivial
execution of the leak path; the DEMO-fixture RUN A confirmed `NULL`
trivially, since the agent declined and there was nothing to leak. Its
stored records, read directly from `database/tradepilot.db` (not
summarized):

```
agent_proposals: has_proposal=True direction=LONG entry=1.154 stop=1.148
                  target=1.165 risk_reward_ratio=1.833333333333352
                  is_coherent=True
evaluations:      status=FAILED risk_reward_ratio=None
                  risk_reward_score=None total_score=None
```

Both required fields are genuinely `NULL`/unscored, confirmed from the
stored row itself, not inferred.

Comparing the two runs that both produced a proposal is worth recording
on its own, separately from the leak test:

- **`ed4e50b2e5b34d389f9734145dc7f53f`** — the user supplied `LONG
  entry=1.156 stop=1.146 target=1.176`: risk `= 1.156 − 1.146 = 0.010`,
  reward `= 1.176 − 1.156 = 0.020`, `RR = 0.020 / 0.010 = 2.0`. The
  agent's own proposal, from the same call, used **different** levels —
  `LONG entry=1.156 stop=1.149 target=1.170`: risk `= 1.156 − 1.149 =
  0.007`, reward `= 1.170 − 1.156 = 0.014`, `RR = 0.014 / 0.007 = 2.0`
  (stored as `2.0000000000000315`, floating-point noise from the same
  division every other RR in this codebase already shows). A tighter
  stop and a closer target than the user's own — but the identical ratio.
- **`cd25a285ea574501bf41a9a4cec26c32`** — no user levels at all. The
  agent's own proposal: `LONG entry=1.154 stop=1.148 target=1.165`: risk
  `= 1.154 − 1.148 = 0.006`, reward `= 1.165 − 1.154 = 0.011`, `RR =
  0.011 / 0.006 = 1.8333...` (stored as `1.833333333333352`) — below 2.0.

Two readings fit this pair equally well, and `n=2` settles neither:

1. **Anchoring on the supplied levels.** Seeing a user-supplied `RR=2.0`
   trade may have pulled the agent's own alternative toward the same
   ratio, even on different specific numbers, even though the prompt
   never mentions the user's levels as something to match.
2. **Independently seeking the top of the risk/reward band.** `RR≥2.0`
   is a natural, round, commonly-taught "good trade" heuristic in
   discretionary trading generally — the agent may gravitate there on its
   own, with or without a user example, simply because 1.83 was a
   genuinely-tighter-target read of a chart with less room to the next
   resistance level. Nothing in the prompt tells the model this app's own
   `RR_STRONG_THRESHOLD = 2.0` scoring boundary at all, since scoring
   thresholds live only in `evals/trade_evaluator.py`.

**What actually holds, from two data points, is narrower than either
theory: proposed RR varies with what the agent was shown.** That's not a
throwaway aside — it's the empirical version of the exact design tension
this iteration was built around (see "The tension this iteration exists
to resolve" above). An agent whose proposed numbers can vary at all based
on context is precisely why `evals/trade_evaluator.py` must never read
`agent_proposals`, and why a proposal only becomes scoring input through
an explicit human accept. If proposed RR *did* reliably cluster on
whatever the user supplied — or reliably cluster at the scoring
threshold — that would be worth knowing before ever relaxing the
never-auto-scored rule, not after.

**This is the motivating question for 7A Iteration 4** (the eval harness
measuring agent reproducibility across repeated runs on a golden set,
see [docs/handoff.md](handoff.md)'s "The 7A plan"): *does proposed RR
cluster on the user-supplied value when one is present, on the same
chart repeated across many runs?* Two single data points can suggest the
question; only a golden-set harness with repeated trials can answer it.

### The fix: a second, real, paired DEMO fixture — `chart_variant`

Closing the actual gap (DEMO mode could never demonstrate a populated
proposal) without touching the prompt:

- **`capture/demo_provider.py`** — `DemoProvider.capture()` gained an
  optional `chart_variant` parameter (`"unreadable_chart"`, the default —
  reproduces the exact original single-fixture behavior — or
  `"readable_chart"`). `demo_filename()` maps `"readable_chart"` to
  `{SYMBOL}_{timeframe}_readable.png`. An unknown variant, or a variant
  with no fixture for that symbol/timeframe (e.g. GBPUSD has no readable
  fixture), fails cleanly — the same "never substitute" rule that already
  governs an unrecognized symbol.
- **`tools/market_data.py`** — `DemoMarketDataProvider.get_quote()` gained
  the identical parameter, reading a new `"readable_price"` key from
  `tools/demo_market_data.json` instead of the ordinary `"price"` key.
  `CHART_VARIANT_UNREADABLE`/`READABLE` are duplicated between the two
  files rather than cross-imported — `capture/` and `tools/` are
  independent sibling packages, same reasoning `database/models.py`
  already uses for its own duplicated small constants.
- **`capture/manager.py` / `tools/market_data.py`'s managers** — both
  thread `chart_variant` through to their DEMO provider only, via
  `isinstance()` checks; a LIVE provider never receives it. This matters
  specifically because leaving `chart_variant` ungated (unlike
  `force_scenario`) is only safe if it can *never* cause a DEMO fixture
  to be served while `CAPTURE_MODE=live` — a silent LIVE→DEMO fallback,
  the one thing this codebase treats as non-negotiable everywhere else.
  It can't: `LiveProvider.capture(self, symbol, timeframe)` and
  `LiveMarketDataProvider.get_quote(self, symbol)` have no `chart_variant`
  parameter at all (confirmed by inspecting both signatures directly, not
  just reasoned about) — passing it would raise `TypeError` immediately,
  a loud crash, never a silent substitution. The `isinstance()` guard
  above stops that from ever being attempted in the first place, and
  `test_capture_manager_ignores_chart_variant_in_live_mode`
  (`tests/test_capture.py`) /
  `test_manager_ignores_chart_variant_in_live_mode`
  (`tests/test_market_data.py`) prove it directly: each passes
  `chart_variant="readable_chart"` to a manager running in LIVE mode with
  a fake LIVE provider whose `capture()`/`get_quote()` only accepts
  `(symbol, timeframe)`/`(symbol,)` — if the manager ever forwarded
  `chart_variant` to it, the test would fail with an uncaught `TypeError`
  rather than the clean `FAILED` result it actually asserts. Both tests
  pass.
- **`backend/orchestrator.py`** — `run_pipeline()` gained a `chart_variant`
  keyword, re-validated against a new `DEMO_CHART_VARIANTS` frozenset
  (same defense-in-depth pattern as `force_scenario`), threaded to both
  `capture_manager.capture()` and `market_data_manager.get_quote()`.
  **Deliberately not gated behind `TESTING_CONTROLS_ENABLED`**, unlike
  `force_scenario`: this never fabricates a failure, a stale timestamp,
  or an outcome — it only picks between two real, honestly-labeled DEMO
  fixtures, so the same production-safety concern that justifies gating
  `force_scenario` doesn't apply here.
- **`backend/api/routes_runs.py`** — `POST /runs/{run_id}/analyze` gained
  an optional `demo_chart_variant` query parameter, validated the same
  way, `422` on an unrecognized value.
- **Freshness is untouched, structurally, not just by policy:** both
  providers still call `datetime.now(timezone.utc)` at capture/fetch time
  regardless of which fixture or price gets read — the exact Milestone 9
  fix's own principle ("handle it in the provider, not the guardrail")
  already made this true before `chart_variant` existed; this addendum
  only had to confirm it stayed true, which a dedicated freshness test
  does directly.
- **The new fixture itself is not a stock image** —
  `screenshots/demo/EURUSD_4h_readable.png` is the actual PNG captured
  during the hybrid RUN A above, saved as a committed fixture.
  `tools/demo_market_data.json`'s new `"readable_price": 1.1558` is that
  same chart's own real last-visible close price, not an invented number.

**Tests, 18 added (292 backend total, up from 274 — the count after the
leak test and accept-endpoint edge-case tests below, which landed just
before this addendum's live-verification work started):**

- `tests/test_capture.py` — 8 added: default variant reproduces original
  behavior, readable variant serves the readable fixture, its
  `captured_at` is still fresh, an unknown variant fails cleanly, a
  symbol with no readable fixture fails cleanly (not substituted), plus
  three `CaptureManager`-level tests (threads to DEMO, omitted reproduces
  original, ignored in LIVE mode — the mismatched-mode backstop itself
  was already covered by a pre-existing test).
- `tests/test_market_data.py` — 7 added: the identical shape of tests as
  above, for the market-data side (default/readable/fresh
  timestamp/missing-fixture-symbol, plus three `MarketDataManager`-level
  tests).
- `tests/test_orchestrator.py` — 3 added: `demo_chart_variant="readable_chart"`
  end to end through the real API (real screenshot path, real paired
  price), omitted reproduces the original screenshot/price exactly, an
  unrecognized value refused with `422` and nothing written.

All 292 backend tests pass. All 44 frontend tests pass (see the UI
section below for what added the other 12).

### The UI — built, not deferred

The original entry's "Deferred, not forgotten" paragraph is superseded:
a proposal panel, side-by-side display, accept-and-re-run control, and
provenance link are all built, matching the original spec.

- **`frontend/src/components/AgentProposalPanel.tsx`** (new) — visually
  distinct from both the user's own levels and the scored result above it
  (a dashed sky-blue border, the same "this is not a normal part of the
  app" register `TestingControls.tsx` already uses for a different
  reason). Four states, each explicit: no proposal data yet (empty
  state); declined (a plain sentence, *never* an empty panel — plus the
  agent's own `setup_assessment` prose shown as its stated reasoning when
  available, since there's no dedicated "why declined" field); a coherent
  proposal (levels shown, `risk_reward_ratio` labelled "informational
  only — not part of the score", never rendered anywhere near
  `ScoreBreakdown`'s real score); an incoherent proposal (the same levels,
  plus the real `coherence_error` shown as a warning). When the run has
  its own user-supplied levels, both render side by side
  (`proposal-your-levels` / `proposal-agent-levels`, independently
  queryable by test id) — never one replacing the other.
- **`frontend/src/api/types.ts` / `api/client.ts`** — `AgentProposalOut`,
  `RunSummary.accepted_from_run_id`, `RunDetail.proposal`,
  `AcceptProposalResponse`, and `acceptProposal(runId)`. `guardrail_outcome`'s
  existing precedent (always present, typed `| null`, never `?`) was
  followed rather than making the two new fields optional — every
  existing `RunDetail`/`RunSummary` test fixture across the frontend test
  suite was updated to include them, the same "update every fixture when
  the schema changes" precedent Milestone 8's revision already set.
- **`App.tsx`** — `handleAcceptProposal()` calls `api.acceptProposal()`,
  then "navigates" to the new run the exact same way clicking a row in
  the run list already does (`selectRun()` fetches and displays it) —
  there is no client-side router in this app, so this is what
  "navigates" means here, consistently with how every other cross-run
  jump in this UI already works.
- **`RunDetailView.tsx`** — a new `Card` hosts the panel, placed directly
  under "Evaluation" so the physical adjacency itself reinforces "here is
  something that is explicitly not part of the score directly above it."
  A run created via acceptance shows a provenance banner
  (`Created by accepting an agent-proposed trade level from run
  {accepted_from_run_id}`) with a clickable link back that calls the same
  `selectRun()` App.tsx already exposes.
- **Tests, 12 added (44 frontend total, up from 32):**
  `AgentProposalPanel.test.tsx` (new, 11 tests) — empty/declined/
  proposal/side-by-side/coherence-warning/accept-click/busy-state/
  accept-error states, plus the two decline-reasoning tests (shown when
  available, absent when not). `App.test.tsx` gained one integration
  test: accepting calls `api.acceptProposal("run-1")`, then
  `api.getRun("run-2")` is called for the new run, and its provenance
  banner (with a link back to `run-1`) renders — the real end-to-end
  path, not just the component in isolation.

### Accept-endpoint edge cases — current behavior, and the tests that prove it

All three were asked about explicitly; none needed a code change, since
the endpoint was already unrestricted in the ways that matter and already
refused what needed refusing:

| Case | Behavior | Test |
|---|---|---|
| Accepting the same proposal twice | **Allowed.** Each acceptance only reads the source run's already-stored proposal row — it never mutates it — so repeated accepts are side-effect-free and simply spawn independent new runs. | `test_accepting_the_same_proposal_twice_creates_two_independent_runs` |
| Accepting on a run itself created by acceptance (chaining) | **Allowed, not blocked.** The chain is fully traceable by walking `accepted_from_run_id` backward, one run at a time (C → B → A) — no dedicated multi-hop endpoint needed, since each run only ever records its own immediate source. | `test_accepting_a_proposal_on_a_run_created_by_acceptance_chains_and_is_traceable` |
| Accepting a declined proposal | **Refused, `409`.** Nothing to accept. | `test_accept_proposal_on_a_declined_run_is_refused` |
| Accepting when no proposal row exists at all (e.g. a failed capture, agent never called) | **Refused, `409`.** | `test_accept_proposal_on_a_run_with_no_proposal_row_at_all_is_refused` |
| Accepting an *incoherent* proposal | **Allowed, deliberately.** The new run just carries the same incoherent numbers and fails `TRADE_PARAMS_VALID` once analyzed, exactly as it would if a human had typed bad numbers in by hand — accepting doesn't imply endorsing the math. | `test_accept_proposal_can_accept_an_incoherent_proposal` |
| Accepting on a nonexistent run | **`404`.** | `test_accept_proposal_on_a_nonexistent_run_returns_404` |

### What this means for demonstrating the feature going forward

`demo_chart_variant=readable_chart` now reliably reproduces the *shape*
of a proposing agent end to end in DEMO mode — real capture flow, real
paired quote, a real Claude call against a chart that actually has
something to propose against. The specific numbers and prose still vary
call to call (the same nondeterminism any real Claude call always has),
but the DEMO/LIVE architecture itself doesn't need to be exercised live
to show the proposal feature working — the readable DEMO fixture carries
that. The one thing DEMO can never demonstrate is the LIVE pipeline
itself actually working end to end against the real internet (real
Playwright, real Alpha Vantage) — showing that at all, even briefly, is
the only genuinely LIVE-dependent segment left, and it isn't specific to
7A: Milestone 12's own final review already named LIVE-mode mileage as
this project's second-weakest area, before 7A existed.

## 7A Iteration 2 — multi-timeframe capture + cross-timeframe agreement guardrail

The second 7A iteration. Design approved before any code was written; full
scope and the three required changes given at approval time are recorded
in "The 7A plan" in [docs/handoff.md](handoff.md) and not repeated here in
full — this entry is the build log: what was actually built, how each
required change was proven, and the evidence.

**The tension this iteration exists to resolve.** A single-timeframe read
has no way to distinguish "a real trend" from "noise that happens to look
like a trend on this one chart." A second, higher-timeframe read is
classic discretionary-trading practice for exactly that reason — but only
if it's a genuinely independent observation. Folding a second image into
the same Claude call the five *scored* categorical fields already come
from would let the model's read of one timeframe quietly influence its
read of the other, changing what those five fields mean without changing
their names — breaking 6C's own comparability and Iteration 4's
reproducibility baseline before either is even measured. So the
confirmation read has to be structurally incapable of touching the
primary read, and "agreement" has to be a fact the orchestrator computes,
never a claim the model is trusted to make about itself.

**Every 6C and 7A Iteration 1 invariant is unchanged, confirmed
structurally, not just asserted:**

- No new scoring path. `evals/trade_evaluator.py` was not touched.
  `test_evaluate_signature_has_no_confirmation_parameter` inspects
  `evaluate()`'s own signature (two parameters, neither confirmation-
  shaped); `test_evaluator_never_reads_confirmation_analysis_attributes`
  greps its source for every confirmation-call identifier and finds zero
  matches — the same source-grep style Iteration 1's
  `test_evaluator_never_reads_proposal_attributes` already established
  for the proposal fields.
- Guardrails still only ever downgrade. `CROSS_TIMEFRAME_AGREEMENT` is
  the twelfth rule, added to `REVIEW_FORCING_RULES` — the same category
  as `UNCERTAINTY_ACCEPTABLE`/`SYNTHETIC_DATA`/`SCORE_THRESHOLD`, never
  `BLOCKING_RULES`. A total disagreement forces `REQUIRES_REVIEW`, never
  `BLOCKED` — confirmed directly by
  `test_cross_timeframe_agreement_is_a_review_forcing_rule_not_blocking`.
- No new fallback logic. `capture/manager.py`'s `CaptureManager` and
  `tools/market_data.py`'s `MarketDataManager` are both unchanged; the
  confirmation capture goes through the identical `CaptureManager.capture()`
  call the primary capture already used, just a second time with a
  different timeframe. `MarketDataManager.get_quote()` is still called
  exactly once per run — proven by a dedicated orchestrator test
  (`test_market_data_get_quote_is_called_exactly_once_even_with_a_confirmation_capture`),
  since Alpha Vantage's daily quota, not Anthropic's, is this project's
  actual constrained resource.

### Schema and the migration

`Capture.timeframe_role` (`"PRIMARY"` | `"CONFIRMATION"`, `database/models.py`)
distinguishes a run's up to two captures — required, never defaulted, with
a `CHECK` constraint restricting it to those two values. A new
`confirmation_analyses` table (analogous to `agent_analyses`, but for the
confirmation call's own result: `visible_timeframe`/`trend_direction`/
`trend_quality`, `SUCCESS`/`FAILED` status, the identical shape every
other pipeline-stage table already uses) was added without prior sign-off
during the build — flagged explicitly and accepted afterward as the right
design, since it follows the exact same "own table, never merged into
what the evaluator reads" pattern `agent_proposals` already established
for the same reason.

The migration ran against the **live dev database**, via a raw
`ALTER TABLE` (not the usual delete-and-recreate), specifically because
`database/tradepilot.db` held the only record of two real findings from
Iteration 1 (the proposed-RR-varies-with-context observation and the
leak-path proof). `database/tradepilot.db.pre-iteration2-backup` was
taken first. Existing `Capture` rows were backfilled to `"PRIMARY"`. All
four evidence runs (`80da6bc6...`, `832f6885...`, `ed4e50b2...`,
`cd25a285...`) were re-queried through the ORM immediately after the
migration, again after every subsequent schema change, and again after
every batch of manual/live verification runs performed for this
iteration — confirmed intact every time, never reset.

### The three required changes, and how each was proven

1. **Two separate Claude calls, one image each.**
   `agents/trade_agent.py`'s `TradeAgent.analyze_confirmation()` is
   independent of `analyze()` — its own prompt files
   (`prompts/confirmation_system_prompt.md`,
   `prompts/confirmation_analysis_prompt.md`), its own tiny expected-field
   set (`confirmation_visible_timeframe`/`confirmation_trend_direction`/
   `confirmation_trend_quality`, deliberately disjoint from `analyze()`'s
   `EXPECTED_FIELDS`), and its own `CONFIRMATION_DEFAULT_MAX_TOKENS=256`
   (analyze()'s response shape is much larger and needs a much larger
   budget; reusing one constant for both would have been wrong for one of
   them). `_reject_suspicious_extra_fields()` — the numeric/score-keyword
   rejection Iteration 1 built for `analyze()` — is factored out and
   reused by both parsers, so the hard boundary can't drift between the
   two response shapes.
   `test_primary_call_payload_is_unchanged_by_the_existence_of_analyze_confirmation`
   compares `analyze()`'s exact prompt text and image-block count against
   its pre-Iteration-2 shape byte for byte.
2. **Identical confirmation capture, detected.** `backend/orchestrator.py`
   computes a SHA-256 hash of both capture files right after capturing
   them (`_hash_file()`) and passes the boolean comparison into
   `guardrails/rules.py` as an explicit parameter
   (`confirmation_capture_matches_primary_hash`) — `guardrails/rules.py`
   itself stays a pure function over explicit inputs, the same "no
   ambient state" principle `CAPTURE_FRESH`/`MARKET_DATA_FRESH` already
   apply to `now`. Separately, the confirmation call echoes back whatever
   timeframe label it can actually read off the chart
   (`confirmation_visible_timeframe`); the orchestrator never trusts the
   confirmation timeframe it *requested* without also checking what the
   model actually *saw* — a case/whitespace-insensitive mismatch is
   treated as a failed confirmation. Both proven directly:
   `test_confirmation_capture_identical_hash_is_detected` and
   `test_confirmation_timeframe_echo_mismatch_is_detected` in
   `tests/test_orchestrator.py`, each feeding a real byte-identical or
   mismatched pair through the real orchestrator and confirming the run
   does not report agreement.
3. **The migration didn't destroy the evidence runs.** Covered above.

### The twelfth guardrail, and its reason-text taxonomy

`guardrails/rules.py`'s `_cross_timeframe_agreement()` fails closed in
every case agreement genuinely can't be confirmed, and passes in exactly
two structurally different N/A cases. A first pass at the reason text
collapsed two real failure causes into one ambiguous string
(`"Primary trend (UNCLEAR) and/or confirmation trend (UP) is not
directional"`) — impossible to tell which side actually failed without
reading raw category values out of the message by hand — and collapsed
both N/A cases into one generic `"N/A"`, which silently misreported the
reason for any run where a Milestone 12 `force_scenario` was active as
"top of the ladder," even when the run's actual timeframe wasn't. Both
were caught and fixed before this iteration was allowed to be recorded as
done. Every cause now has its own, non-overlapping reason text — proven
distinct in one place by
`test_cross_timeframe_agreement_reason_text_is_distinct_per_cause`:

| Cause | Passes? | Reason text starts with |
|---|---|---|
| Primary at top of the ladder | ✓ | `N/A: primary at top of ladder` |
| `force_scenario` active | ✓ | `N/A: suppressed by force_scenario` |
| Confirmation capture failed (missing fixture, capture error) | ✕ | `Confirmation capture failed` |
| Confirmation capture identical to primary (SHA-256 match) | ✕ | `Identical image hash` |
| Confirmation call's own echoed timeframe doesn't match what was requested | ✕ | `Timeframe echo mismatch` |
| Confirmation Claude call itself failed | ✕ | `Confirmation analysis did not succeed` |
| Primary trend is `SIDEWAYS`/`UNCLEAR` | ✕ | `Primary read non-directional` (checked before the confirmation side, since it's the more fundamental problem) |
| Confirmation trend is `SIDEWAYS`/`UNCLEAR` | ✕ | `Confirmation read non-directional` |
| Both directional and equal | ✓ | `Primary trend (X) and confirmation trend (X) agree.` |
| Both directional and different | ✕ | `Primary trend (X) and confirmation trend (Y) disagree.` |

`force_scenario_active` is a new explicit parameter on
`evaluate_guardrails()`/`_cross_timeframe_agreement()`, set by
`backend/orchestrator.py` to `force_scenario is not None` — the same
explicit-boolean-flag pattern `confirmation_capture_matches_primary_hash`
already established, not a second way of inferring the same fact.

**`force_scenario` never makes an unmocked, billed confirmation call.**
`backend/orchestrator.py`'s `run_pipeline()` keeps
`confirmation_timeframe` at `None` whenever `force_scenario` is active,
for every one of the seven documented scenarios — Milestone 12's testing
affordance exists so a guardrail can be proven for free and
deterministically, and `analyze_confirmation()` has no force_scenario
equivalent of its own. Proven for all seven scenarios in one parametrized
test,
`test_force_scenario_never_makes_an_unmocked_confirmation_call_and_reports_suppressed`:
`analyze_confirmation` is asserted never called even though it's mocked
and would happily return a value, and `CROSS_TIMEFRAME_AGREEMENT`'s
reason is confirmed to read `N/A: suppressed by force_scenario` — visible
in its own distinct text, not an unexplained N/A or a failure-looking
result.

### Tests, verification, and counts

335 backend tests existed before this session's hardening pass (up from
Iteration 1's 292) — the schema/migration, `analyze_confirmation()`, the
orchestrator wiring, and the guardrail rule's core behavior. This
session's hardening pass (the reason-text taxonomy fix, the
evaluator-isolation proof, the `SYNTHETIC_DATA` role-independence proof,
the force_scenario-suppression regression guard, and the
`role=PRIMARY|CONFIRMATION` screenshot endpoint plus its own tests) added
16 more: **351 backend tests total** — 71 agent + 36 API + 25 capture +
56 database + 36 evaluation + 21 failure scenarios + 51 guardrails + 26
market data + 29 orchestrator. Frontend grew from Iteration 1's 44 to
**52** — a new `ConfirmationAnalysisPanel` (5 tests) and 3 new
`ChartCapturePanel` tests for `role` selection.

## 7A Iteration 2 addendum — the readable DEMO path, a categorical-stability finding, and the UI

Everything above was built and unit-tested with hand-built fixtures.
This addendum is the same live-verification discipline Iteration 1's own
addendum established — "in 6C, `analysis_text` truncation passed every
test and only surfaced on a live run" — applied here: what the readable
DEMO path actually produces against a real Claude call, a real,
non-obvious finding from measuring it five times, and the UI, all
verified before this iteration was allowed to move.

### The fixture decision: keep the UNCLEAR capture, don't retry

Iteration 1's `readable_chart` DEMO variant had one committed fixture,
`EURUSD_4h_readable.png`, used as `PRIMARY`. Under Iteration 2's fixed
ladder, a `4h` primary needs a `1d` confirmation — no `1d` fixture exists,
and building one was out of scope. Verifying the readable path needed a
second rung, so `1h` (whose confirmation, `4h`, already had a fixture)
was tried instead. A real LIVE capture of `EURUSD 1h`
(`EURUSD_1h_20260809T135928Z.png`) came back `trend_direction=UNCLEAR`
when analyzed.

**Decision: keep it. Do not retry.** Recapturing until the read comes back
agreeable would be selecting a fixture on its outcome — the same move
already rejected twice for the prompt itself (Iteration 1's addendum:
"declining was the prompted-for, correct behavior... not a bug to patch
around by changing the instructions"). A real 1h capture reading
`UNCLEAR` and a real 4h capture reading a clean uptrend are both honest
facts about two different charts; neither is more "correct" than the
other, and picking whichever one flatters the feature would have been
exactly the wrong lesson from that earlier finding. Fail-closed on a
genuinely inconclusive read is the guardrail working as designed — the
stronger thing to demonstrate, not a fallback.

`EURUSD_1h_20260809T135928Z.png` is now committed as
`screenshots/demo/EURUSD_1h_readable.png`. Its hash differs from the
primary capture and its echoed timeframe matched `1h` — confirmed a real,
distinct 1h capture that happened to read `UNCLEAR`, not a failed or
substituted one.

**Agreement and disagreement are covered by hand-built unit fixtures
instead** (`tests/test_guardrails.py`'s `_good_confirmation_result()` and
friends), so neither branch depends on what a live model call happens to
say on any given day. That leaves all three states — agree, disagree, and
genuinely inconclusive — with real coverage: the two scored branches from
hand-built fixtures, and the fail-closed branch from a real, honestly
inconclusive capture.

### What the readable DEMO path actually produces (both ladder pairings)

Run four ways in DEMO, `readable_chart` variant, real Claude calls, real
dev database (all preserved):

| | Primary | Confirmation | Confirmation outcome | `CROSS_TIMEFRAME_AGREEMENT` | Final status |
|---|---|---|---|---|---|
| No user levels | `4h` (`EURUSD_4h_readable.png`) | `1d` — **no fixture** | capture failed | `Confirmation capture failed: No demo fixture for EURUSD 1d...` | `BLOCKED` (missing trade params) |
| `LONG 1.150/1.145/1.160` | `4h` | `1d` — no fixture | capture failed | same | `REQUIRES_REVIEW` — failing: `SCORE_THRESHOLD` (59), `SYNTHETIC_DATA`, `CROSS_TIMEFRAME_AGREEMENT` |
| No user levels | `1h` (`EURUSD_1h_readable.png`) | `4h` (`EURUSD_4h_readable.png`) | SUCCESS | `Primary trend (UP) and confirmation trend (UP) agree.` | `BLOCKED` (missing trade params) |
| `LONG 1.150/1.145/1.160` | `1h` | `4h` | SUCCESS | agree | `REQUIRES_REVIEW` — failing: `SCORE_THRESHOLD` (45), `SYNTHETIC_DATA` only |

**Recorded, adopted going forward: the `1h`-primary / `4h`-confirmation
pairing.** It's the only one that exercises both real captures and both
real Claude calls end to end, and it reuses `EURUSD_4h_readable.png` in a
second role (confirmation) rather than needing a new fixture.

**The `4h`-primary case is documented, not discarded, and its limitation
is named plainly:** the readable fixture set only covers two rungs of
the ladder. A `4h`-primary DEMO run will always show
`CROSS_TIMEFRAME_AGREEMENT` failing with the specific
`No demo fixture for EURUSD 1d` reason — that is honest behavior (a real,
correctly-attributed capture failure, distinct from a generic one), not a
placeholder standing in for a missing feature. Building a full `1d`
fixture was out of scope for this iteration.

### Headline finding: identical DEMO input does not guarantee identical categorical output

The same `1h`-primary / `4h`-confirmation DEMO pipeline (fixed fixture
images, fixed quote, fixed `LONG 1.150/1.145/1.160` trade params, no code
changes) was run **five times in a row**, purely to measure — not debug —
whether the agent's categorical read is stable on identical input. Run
IDs, all preserved in the dev database:
`c7ab7dd29873425db443da517521a1e1`, `9acb5fcaf9054bcb88ea74a61cb6ad5b`,
`3a064fbf1eec4011814a9d03a3168b1f`, `74b591cfa93245df8d53bae1630bca49`,
`75df8200cd004ae48f54d2142018040f`.

| Field | Result across 5 runs |
|---|---|
| `trend_direction` | stable — `UP`, all 5 |
| `trend_quality` | **varied** — `MODERATE` ×4, `WEAK` ×1 |
| `structure_quality` | stable — `MIXED`, all 5 |
| `setup_quality` | stable — `MARGINAL`, all 5 |
| `context_risk` | stable — `MODERATE`, all 5 |
| `uncertainty` | stable — `MEDIUM`, all 5 |
| `confirmation_trend_direction` | stable — `UP`, all 5 |
| `confirmation_trend_quality` | stable — `MODERATE`, all 5 |
| `total_score` | **varied** — 55 ×4, 45 ×1 (driven entirely by the `trend_quality` flip) |
| `CROSS_TIMEFRAME_AGREEMENT` | stable — passed, "agree," all 5 |
| proposal | stable — declined, all 5 |
| final status | stable — `REQUIRES_REVIEW`, 5/5 |

**This is the finding, stated plainly: DEMO is deterministic in its
INPUTS — the fixture image, the quote, the prompt — never in the agent's
read.** The agent call is a fresh inference every single run, real
Claude nondeterminism and all; nothing about running in DEMO mode changes
that. Final status held steady in this batch, but that's a floor, not
evidence of stability underneath it: `SYNTHETIC_DATA` fails on every DEMO
run regardless of anything else, so `REQUIRES_REVIEW` was guaranteed
before any of the five calls ran. `total_score` moving between 45 and 55
on byte-identical input, because one field out of nine didn't hold, is
the real signal. It is easy to misread "the DEMO path" as fully
deterministic because its inputs are — this entry exists specifically so
that assumption is never made silently by a future session.

For additional context (not part of the formal 5-run batch, but the same
image): across every real Claude read of `EURUSD_1h_readable.png` in this
project so far — the original LIVE capture, one earlier ad-hoc check, and
these 5 — `trend_direction` has come back `UNCLEAR` once and `UP` six
times. Consistent with the fixture decision above: the image is fixed and
honest; what any single call says about it isn't guaranteed, and that is
exactly why the guardrail exists.

**Connects directly to Iteration 1's own finding.** "An empirical
observation: proposed RR varies with what the agent was shown" (Iteration
1's addendum) showed the same underlying fact from a different angle —
`ed4e50b2...`'s proposed RR matched the user's own `RR=2.0` on different
numbers, while `cd25a285...`'s (no user levels) came out to `RR≈1.83`.
Both findings are instances of the same thing: **agent output varies with
conditions the agent cannot be trusted to hold fixed** — what it's shown,
in Iteration 1's case; nothing at all, run to run, in this one. Together
they are the empirical case, not just the architectural argument, for why
this project scores deterministically from fixed categories, never trusts
the agent to self-score, keeps a proposal unscored until a human accepts
it, and requires human approval on every single run regardless of score.
An architecture built to survive an agent that can't be trusted to hold
still is exactly the architecture this project already has — these two
findings are the evidence it was the right call.

**Iteration 4, second research question, added alongside the RR-clustering
one already on record:** categorical stability per field, across N runs,
on one fixed DEMO fixture. Does `trend_quality` (or any other field)
stabilize with more samples, or stay genuinely noisy? `n=5` on one field
settles nothing on its own — same caveat Iteration 1's `n=2` RR
observation already carries — but it's now a second, concrete, motivating
question for the golden-set harness Iteration 4 would build.

### The frontend UI

Built this iteration, not deferred — the same correction Iteration 1
applied to its own UI after initially treating it as optional.

- **`ChartCapturePanel`** (`frontend/src/components/ChartCapturePanel.tsx`)
  gained a `role` prop (`"PRIMARY"` | `"CONFIRMATION"`, defaulting to
  `"PRIMARY"` so every pre-existing caller is unaffected) and is now
  rendered twice in `RunDetailView` — once for the primary capture
  (unchanged), once for whichever capture has `timeframe_role ===
  "CONFIRMATION"`, found by role rather than assumed to be index `[1]`
  since it may not exist at all.
- **`GET /runs/{run_id}/screenshot`** gained a `role` query parameter
  (`backend/api/routes_runs.py`), same default/backward-compatibility
  shape — an unrecognized value is a `422`, never a silent fallback to
  `PRIMARY`. Four new tests cover the default, both roles serving
  genuinely different files, a `404` when no confirmation capture exists,
  and the `422` rejection.
- **`ConfirmationAnalysisPanel`** (new component) shows the confirmation
  call's own `visible_timeframe`/`trend_direction`/`trend_quality`, and —
  pulled from `run.guardrail_results` by name, never re-derived on the
  frontend — the `CROSS_TIMEFRAME_AGREEMENT` check's own pass/fail and
  its exact reason text, with an "Agrees"/"Does not confirm" badge. When
  there's no `confirmation_analysis` row at all, it falls back to that
  same guardrail check's own reason text (already the correct distinct
  N/A message — top of ladder vs. `force_scenario` suppressed — computed
  once, on the backend, never re-guessed here). `GuardrailResultsPanel`
  needed no changes at all: it already renders every guardrail generically
  by name and reason, so all twelve distinct `CROSS_TIMEFRAME_AGREEMENT`
  reason strings render correctly with zero frontend-side special-casing.
- **Verified against the real running app, not just component tests**:
  started the real backend and the real dev server, opened the `1h`/`4h`
  agreeing run in a real browser — confirmed both chart panels render
  real images (`GET .../screenshot` and `GET .../screenshot?role=
  CONFIRMATION` both `200`, genuinely different bytes), the "Agrees"
  badge and its reason render correctly, and all twelve guardrail rows
  appear. Then opened the `4h`-primary/missing-`1d`-fixture run and
  confirmed the confirmation chart panel shows "Chart capture failed" with
  the exact fixture-missing message, and the confirmation-analysis panel
  shows "Confirmation analysis failed — Confirmation analysis skipped --
  confirmation capture did not succeed." — both honestly distinct, no
  broken image, no silent fallback.

### `EURUSD_4h.png` — generated, not captured

The plain (non-`readable`) `EURUSD_4h.png` DEMO fixture — needed for the
`4h` confirmation timeframe under the default `unreadable_chart` variant,
which Milestone 5 never committed for `EURUSD` (only `EURUSD_1h.png` and
`GBPUSD_4h.png` existed) — was generated the same way Milestone 5's
original fixtures were: a plain abstract bar series with the identical
"SAMPLE IMAGE — NOT REAL MARKET DATA — for offline demo/testing only"
banner baked in, confirmed by direct visual inspection. It is **generated,
not captured** — worth stating plainly since every other new fixture this
iteration added (`EURUSD_1h_readable.png`) is a real capture, and the two
should never be confused. `SYNTHETIC_DATA` (`guardrails/rules.py`) reads
only the primary capture's mode and is structurally incapable of even
seeing the confirmation capture — proven directly by
`test_synthetic_data_is_derived_only_from_the_primary_capture_never_the_confirmation_one`,
which forces the confirmation capture's mode to `LIVE` by hand and
confirms the outcome is unchanged — so whether this image lands as
`PRIMARY` or `CONFIRMATION` makes no difference to the rule either way.

### Never committed: the pre-migration database backup

`database/tradepilot.db.pre-iteration2-backup` doesn't end in `.db`, so
the existing `*.db` gitignore rule never covered it — a real gap, closed
by adding `*.db.pre-*-backup` to `.gitignore`. Confirmed with
`git check-ignore -v`: the file is untracked and un-stageable. The
evidence-run database, and everything derived from it, stays out of git
history permanently, the same as the live database always has.

Final counts after this addendum: **351 backend tests, 52 frontend
tests.**

## Roadmap

1. ~~Architecture~~
2. ~~Folder structure~~
3. ~~Database schema~~
4. ~~Backend API~~
5. ~~Screenshot tool~~
6. ~~Market-data tool~~
7. ~~Agent loop~~
8. ~~Evaluation~~
9. ~~Guardrails~~
10. ~~Human approval~~
10.5. ~~Orchestrator~~
11. ~~UI (incl. Tailwind migration)~~
12. ~~Testing~~ — all twelve milestones complete. See "6c-baseline" in
    git for this state.
