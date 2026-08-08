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
10. Human approval
11. UI (incl. Tailwind migration)
12. Testing
