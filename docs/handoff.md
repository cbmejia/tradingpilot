# Session handoff

Written for a brand-new Claude Code session with zero conversation
history. Read this first, then the three docs it links to rather than
duplicates: [docs/architecture.md](architecture.md),
[docs/iterations.md](iterations.md), [docs/rubric.md](rubric.md), and
the root [README.md](../README.md).

## 1. Current state

- **Milestones 1–10.5 are complete**, including all three Milestone
  10.5 follow-up fixes (failure states on analysis/evaluation records;
  persisting the agent's categorical observations; storing market-data
  mode and the risk/reward ratio). Milestone 11 (UI, including the
  Tailwind migration) is next. Milestone 12 (testing) is after that.
- **Latest commit:** "Milestone 10.5 fix 3 - store market data mode and
  risk reward ratio".
- **Test count:** 197 tests, all passing (33 database + 25 API + 17
  capture + 19 market data + 25 agent + 32 evaluation + 36 guardrails +
  10 orchestrator). See the roadmap checklist at the bottom of
  [docs/iterations.md](iterations.md) for the full milestone list.
- **The orchestrator exists.** `backend/orchestrator.py`'s
  `run_pipeline()`, called via `POST /runs/{run_id}/analyze`, actually
  runs capture → market data → agent → evaluation → guardrails in order
  for one run and persists every step, synchronously, in a single
  request. `capture/`, `tools/market_data.py`, `agents/trade_agent.py`,
  `evals/trade_evaluator.py`, and `guardrails/rules.py` themselves are
  unchanged — still standalone, independently callable modules; the
  orchestrator only calls them in sequence.
- **`agent_analyses` and `evaluations` now carry `status`/
  `error_message`**, matching `captures`/`market_data`, and a `FAILED`
  row is a real row (never zeros, never a fabricated string) rather than
  something only visible in `audit_events`.
- **`agent_analyses` also now stores the five categorical fields**
  (`trend_direction`, `trend_quality`, `structure_quality`,
  `setup_quality`, `context_risk`) the v2 rubric actually scores from —
  so a completed run's component scores (e.g. `trend_score: 14`) can be
  traced back to the observation that produced them, not just trusted as
  a number. Enforced both at the database level (a `CHECK` constraint
  per field) and the application level (`database/crud.py` validates
  before writing) — see the "Milestone 10.5 fix" and "Milestone 10.5 fix
  2" entries in [docs/iterations.md](iterations.md) for the full
  reasoning on both this and the status/error_message fix.
- **The schema audit is clean.** Fix 2's audit across all eight tables
  found two gaps (`market_data` had no `mode` column, `evaluations` had
  no `risk_reward_ratio` column); fix 3 closed both. `market_data.mode`
  is now a real `NOT NULL` column, constrained to `LIVE`/`DEMO` at both
  the database level (`CHECK`) and the application level
  (`database/crud.py`). `evaluations.risk_reward_ratio` is now a nullable
  `Float`, populated on `SUCCESS`, `NULL` on `FAILED`, kept out of the
  original integer sum-rule `CHECK` constraint and enforced by its own
  independent nullability constraint instead. Every field every pipeline
  dataclass produces now has a corresponding column somewhere in
  `database/models.py` — see the "Milestone 10.5 fix 3" entry in
  [docs/iterations.md](iterations.md).
- See "How to run everything" below for the exact request sequence to
  exercise the pipeline by hand.

## 2. The non-negotiable invariants

These hold regardless of which milestone is being worked on. Each one
has a specific enforcement point in the code — if a change would
weaken any of these, stop and ask rather than proceeding.

- **(a) Never places, submits, or simulates a trade.** There is no
  broker/order-execution integration anywhere, and none is planned.
  The only terminal states a run can reach are `APPROVED`/`REJECTED` —
  both are just database writes. See "Non-negotiables" in
  [docs/architecture.md](architecture.md).
- **(b) The agent emits words and categories, never a score.**
  `agents/trade_agent.py`'s `_parse_response()` rejects the entire
  response if any field is a number where a word is expected, or an
  unrecognized category value. All scoring is
  `evals/trade_evaluator.py`, deterministic Python.
- **(c) `total_score` is always the sum of its five components.**
  Enforced twice: `evals/trade_evaluator.py`'s `evaluate()` has no
  `total_score` parameter, and the database itself has a `CHECK`
  constraint (`ck_evaluations_total_score_is_sum_of_components` in
  `database/models.py`) that rejects any row, however constructed,
  where that doesn't hold.
- **(d) Guardrails are deterministic and can only downgrade.**
  `guardrails/rules.py`'s `evaluate_guardrails()` produces exactly one
  of `BLOCKED` / `REQUIRES_REVIEW` / `READY_FOR_REVIEW` — there is no
  fourth state and no code path that auto-approves. Only a human,
  through `POST /runs/{run_id}/review`, can reach `APPROVED`.
- **(e) No silent LIVE→DEMO fallback.** `capture/manager.py`'s
  `CaptureManager` and `tools/market_data.py`'s `MarketDataManager`
  each pick exactly one provider and never substitute the other. A
  failed LIVE capture or fetch is a `FAILED` result, never quietly
  replaced by demo data.
- **(f) A DEMO-sourced run can never reach `READY_FOR_REVIEW`.** The
  `SYNTHETIC_DATA` guardrail rule forces `REQUIRES_REVIEW` if either
  the capture or market-data mode is `DEMO`, regardless of score —
  verified directly by a test in `tests/test_guardrails.py`.
- **(g) Market data is never fabricated.** `tools/market_data.py`
  returns `price=None` with `status=FAILED` on any failure — no
  invented, estimated, or carried-forward price, ever.
- **(h) All datetimes are timezone-aware UTC.** Enforced by
  `database/types.py`'s `TZDateTime`, a custom SQLAlchemy
  `TypeDecorator` applied to every datetime column, because SQLite
  otherwise silently drops timezone info on write.

## 3. Working agreement

- **One milestone at a time.** Do not start the next milestone
  without an explicit go-ahead, even if the current one's tests pass
  and the commit is made.
- **Run the entire test suite, not just new tests**, after every
  change — `pytest` from the repo root.
- **Explain in plain language.** The user is not an experienced
  developer — narrate what's being built and why before/while writing
  code, not just what the code does.
- **Update `docs/iterations.md`** with a new dated section at the end
  of every milestone (and `README.md` when setup/usage instructions
  change), before committing.
- **Commit at the end of each milestone**, one phase per commit,
  prefixed with the milestone, e.g. `"Milestone 10 - human approval
  and decision audit"`.
- When a "before Milestone N, fix a defect" request comes in, treat it
  as its own small task: fix, test, document, commit — then wait for
  the go-ahead on Milestone N itself.

## 4. Gotchas already hit

Brief pointers only — full detail is in the matching
[docs/iterations.md](iterations.md) entry.

- **SQLite drops timezone info on datetime round-trip.** Fixed with
  the `TZDateTime` column type (Milestone 3 hardening).
- **The v1 rubric scored prose length, not setup quality.** Four of
  five components were scored from paragraph length/keyword matching,
  so a verbose description of a mediocre setup scored the same as a
  concise description of a great one. Fixed by adding five
  fixed-category agent fields and rewriting the evaluator to read only
  those (Milestone 8 revision; see "What v1 got wrong" in
  [docs/rubric.md](rubric.md)).
- **The demo market-data fixture's fixed 2024 timestamp blocked every
  demo run.** `MARKET_DATA_FRESH` is a blocking rule, so an
  always-stale demo quote meant DEMO mode could never even reach
  `REQUIRES_REVIEW`, let alone be reviewed by a human. Fixed by
  generating the demo timestamp fresh at fetch time while keeping the
  price fixed; the freshness guardrail itself was deliberately left
  untouched (Milestone 9 fix).
- **A timing race in the fix's own new tests.** Computing `now` before
  calling a real DEMO provider (instead of after) occasionally made a
  correct "timestamp is in the future" rejection fire, but only when
  the full suite ran together. Fixed by computing `now` after the
  provider call, matching how a real caller does it.

## 5. How to run everything

Windows PowerShell, from the repo root:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r backend\requirements.txt
playwright install chromium
python -m database.init_db
pytest
uvicorn backend.main:app --reload
```

With the server running, open **http://127.0.0.1:8000/docs** for
interactive API docs. See the README for hand-run examples of each
standalone tool:

- [Chart capture (DEMO and LIVE)](../README.md#trying-the-chart-capture-tool-by-hand)
- [Market data (DEMO and LIVE)](../README.md#trying-the-market-data-tool-by-hand)
- [The agent](../README.md#trying-the-agent-by-hand)
- [Scoring an evaluation](../README.md#scoring-an-evaluation-by-hand)
- [Checking guardrails](../README.md#checking-guardrails-by-hand)
- [Running a full analysis pipeline, then approving/rejecting it, from `/docs`](../README.md#running-a-full-analysis-pipeline-by-hand)

## 6. What is not built yet

- **Milestone 11 — UI (including the Tailwind migration).** Milestone
  1 shipped a React/TypeScript dashboard shell with hand-rolled CSS
  and designed empty states, but no live data and no backend calls.
  This milestone wires the frontend to the real API — create a run,
  call `POST /runs/{id}/analyze`, poll/fetch it, show the
  screenshot/analysis/score/guardrail results, and the approve/reject
  controls — and migrates the shell's styling to Tailwind, which the
  stack has specified since Milestone 2 but was deliberately deferred
  to avoid churning the shell twice. The orchestrator this milestone
  needs (Milestone 10.5) is already done.
- **Milestone 12 — Testing.** What this covers beyond the substantial
  unit-test suite that already exists (197 tests across every backend
  module, including the orchestrator) isn't yet decided — likely
  candidates are frontend tests and an end-to-end pass, but that should
  be scoped as its own milestone discussion, not assumed here.
- **No known schema gaps remain.** The eight-table audit from Milestone
  10.5 fix 2 found two gaps; fix 3 closed both (see section 1 above).
  Nothing currently prevents Milestone 11 from building against the full
  `GET /runs/{id}` shape.
