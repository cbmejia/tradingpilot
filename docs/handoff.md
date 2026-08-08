# Session handoff

Written for a brand-new Claude Code session with zero conversation
history. Read this first, then the three docs it links to rather than
duplicates: [docs/architecture.md](architecture.md),
[docs/iterations.md](iterations.md), [docs/rubric.md](rubric.md), and
the root [README.md](../README.md).

## 1. Current state

- **Milestones 1–10 are complete.** Milestone 11 (UI, including the
  Tailwind migration) is next. Milestone 12 (testing) is after that.
- **Latest commit:** `ad631e9524c995b3e4882278388f4b5cbe5219d5` —
  "Milestone 10 - human approval and decision audit".
- **Test count:** 173 tests, all passing (19 database + 25 API + 17
  capture + 19 market data + 25 agent + 32 evaluation + 36 guardrails).
  See the roadmap checklist at the bottom of
  [docs/iterations.md](iterations.md) for the full milestone list.
- Nothing is wired into an orchestrator yet. `capture/`, `tools/
  market_data.py`, `agents/trade_agent.py`, `evals/trade_evaluator.py`,
  and `guardrails/rules.py` are all standalone, independently callable
  modules — that's deliberate, not unfinished. See "How to run
  everything" below for how to exercise each one by hand.

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
- [Approving or rejecting a run from `/docs`](../README.md#approving-or-rejecting-a-run-from-docs)

## 6. What is not built yet

- **Milestone 11 — UI (including the Tailwind migration).** Milestone
  1 shipped a React/TypeScript dashboard shell with hand-rolled CSS
  and designed empty states, but no live data and no backend calls.
  This milestone wires the frontend to the real API (create a run,
  poll/fetch it, show the screenshot/analysis/score/guardrail results,
  and the approve/reject controls) and migrates the shell's styling to
  Tailwind, which the stack has specified since Milestone 2 but was
  deliberately deferred to avoid churning the shell twice.
- **Milestone 12 — Testing.** What this covers beyond the substantial
  unit-test suite that already exists (173 tests across every backend
  module) isn't yet decided — likely candidates are frontend tests and
  an end-to-end pass, but that should be scoped as its own milestone
  discussion, not assumed here.
- **No orchestrator exists.** `backend/orchestrator.py` is a
  placeholder (Milestone 2). Nothing currently chains
  capture → market data → agent → evaluation → guardrails into one
  automatic pipeline; every run created through `POST /runs` today has
  to have its guardrail results seeded by hand to be approvable (see
  the README's approval walkthrough). Whether building the
  orchestrator is folded into Milestone 11 or treated as its own step
  hasn't been decided — flag it for discussion before assuming either
  way.
