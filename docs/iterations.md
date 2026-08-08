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
6. Market-data tool
7. Agent loop
8. Evaluation
9. Guardrails
10. Human approval
11. UI (incl. Tailwind migration)
12. Testing
