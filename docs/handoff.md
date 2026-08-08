# Session handoff

Written for a brand-new Claude Code session with zero conversation
history. Read this first, then the docs it links to rather than
duplicates: [docs/architecture.md](architecture.md),
[docs/iterations.md](iterations.md), [docs/rubric.md](rubric.md),
[docs/failure_modes.md](failure_modes.md), and the root
[README.md](../README.md).

## 1. Current state

- **All twelve planned milestones are complete.** This is the "6C
  baseline" — see the annotated git tag `6c-baseline` for exactly this
  state, and the command to return to it, in
  [docs/iterations.md](iterations.md)'s Milestone 12 entry. There is no
  Milestone 13 planned; anything from here is new work, not finishing
  the original plan.
- **Latest commit:** "Milestone 12 - documented failure modes and final
  verification".
- **Test count:** 218 backend tests + 32 frontend tests, all passing.
  Backend: 24 database + 32 API + 17 capture + 19 market data + 25 agent
  + 32 evaluation + 36 guardrails + 10 orchestrator + 14 failure
  scenarios. Frontend: 32 tests across 9 files (Vitest + React Testing
  Library), none making a real network call. See the roadmap checklist
  at the bottom of [docs/iterations.md](iterations.md) for the full
  milestone list.
- **Read [docs/failure_modes.md](failure_modes.md) before touching
  anything safety-related.** Eleven scenarios, each a real reproducible
  run, proving every guardrail actually stops a bad run — not just
  asserted in a unit test. It also documents `force_scenario`
  (`POST /runs/{run_id}/analyze?force_scenario=...`), a testing-only
  mechanism gated behind `TESTING_CONTROLS_ENABLED` (off by default in
  `.env`) that deliberately forces one pipeline stage to a synthetic
  result so a guardrail can be demonstrated on demand. If you're asked
  to add a new failure scenario or guardrail, this is the pattern to
  extend, not a new one-off.
- **The frontend is wired to the real backend.** Submit a symbol in the
  UI → it creates a run, runs the real pipeline, and shows the real
  result: chart image, market quote, agent prose and categories, every
  score next to the evidence that produced it, all eleven guardrail
  results, and working approve/reject. Nothing in the UI computes a
  number itself. See the "Milestone 11" entry in
  [docs/iterations.md](iterations.md) for the full breakdown, including
  the one backend prerequisite it needed (`GET /runs/{run_id}/screenshot`
  — the only way a browser can display a chart image that lives on the
  backend's own filesystem).
- **The orchestrator exists.** `backend/orchestrator.py`'s
  `run_pipeline()`, called via `POST /runs/{run_id}/analyze`, actually
  runs capture → market data → agent → evaluation → guardrails in order
  for one run and persists every step, synchronously, in a single
  request. `capture/`, `tools/market_data.py`, `agents/trade_agent.py`,
  `evals/trade_evaluator.py`, and `guardrails/rules.py` themselves are
  unchanged — still standalone, independently callable modules; the
  orchestrator only calls them in sequence.
- **The schema is complete.** `agent_analyses` and `evaluations` both
  carry `status`/`error_message` (a `FAILED` row is a real row, never
  zeros, never a fabricated string); `agent_analyses` stores the five
  categorical fields the rubric scores from; `market_data.mode` and
  `evaluations.risk_reward_ratio` closed the last two gaps found by the
  Milestone 10.5 fix 2 audit. Every field every pipeline dataclass
  produces now has a corresponding column — see the three "Milestone
  10.5 fix" entries in [docs/iterations.md](iterations.md).
- **A final, code-verified review (not just asserted) closed Milestone
  12** — no trade-execution code path exists anywhere (grepped, zero
  matches), no code path reaches `APPROVED` without a real human
  `POST /runs/{id}/review` request, the evaluator never reads the
  agent's prose (only its seven categorical/status fields), and no
  silent fallback or fabricated value was found anywhere in the
  pipeline. Two honestly-named weak points: **no authentication or rate
  limiting on the API** (fine on `localhost`, a real problem the moment
  this is reachable from anywhere else — spammable, and each analyze
  call can cost real money), and **LIVE mode is comparatively unproven**
  (real TradingView scraping and real Alpha Vantage calls are
  unit-tested with mocks but were never run against the real internet
  in this project). See the Milestone 12 entry in
  [docs/iterations.md](iterations.md) for the full verification.
- See "How to run everything" below for the exact commands to start both
  servers and exercise the app.

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

Windows PowerShell, from the repo root. **Two servers, two terminals:**

Terminal 1 — backend:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r backend\requirements.txt
playwright install chromium
python -m database.init_db
pytest
uvicorn backend.main:app --reload
```

Terminal 2 — frontend:

```powershell
cd frontend
npm install
npm test
npm run dev
```

Open **http://localhost:5173** for the real app, and
**http://127.0.0.1:8000/docs** for interactive API docs (Swagger UI) if
you want to call the backend directly instead. See the README for
hand-run examples of each standalone tool, and for the exact
click-by-click steps to run one DEMO analysis end to end in the UI:

- [Chart capture (DEMO and LIVE)](../README.md#trying-the-chart-capture-tool-by-hand)
- [Market data (DEMO and LIVE)](../README.md#trying-the-market-data-tool-by-hand)
- [The agent](../README.md#trying-the-agent-by-hand)
- [Scoring an evaluation](../README.md#scoring-an-evaluation-by-hand)
- [Checking guardrails](../README.md#checking-guardrails-by-hand)
- [Running a full analysis pipeline, then approving/rejecting it, from `/docs`](../README.md#running-a-full-analysis-pipeline-by-hand)
- [Running one DEMO analysis end to end in the UI](../README.md#running-a-demo-analysis-in-the-ui)
- [Reproducing any of the eleven documented failure scenarios](../docs/failure_modes.md)

## 6. What's not built, and what's genuinely still weak

The 6C plan is complete — this section is no longer "what's next," it's
"what was deliberately left out, and where this project is honestly
weakest." Both are worth reading before assuming a gap needs fixing;
some of these are documented tradeoffs, not oversights.

- **No authentication or rate limiting on the API.** Named plainly as
  the weakest part of this project in the Milestone 12 final review.
  Fine for a single developer on `localhost` (how this has been built
  and run throughout); a real risk — spammable, and `POST
  /runs/{id}/analyze` can cost real money per call — the moment this is
  ever reachable from anywhere else. If a future request is "expose
  this beyond localhost" or "add multi-user support," this is the first
  thing that needs solving, not an afterthought.
- **LIVE mode is comparatively unproven.** Named as the second weakest
  part. Real TradingView scraping (`capture/live_provider.py`) and real
  Alpha Vantage calls (`tools/market_data.py`) are unit-tested with
  mocks but have never been run against the real internet in this
  project — every guardrail proof, every manual verification, and all
  of Milestone 12's failure-scenario evidence is DEMO-mode. Not
  architecturally unsafe (a real failure there would still show up as
  an honest `FAILED` result, per every invariant this project enforces)
  — just genuinely untested against reality.
- **Known, deliberate scope limits from Milestone 11** (not gaps,
  documented tradeoffs — see that entry in
  [docs/iterations.md](iterations.md) for the reasoning): the run list
  is capped at the 10 most recent runs with no pagination controls in
  the UI yet (the API already supports paging); a run open in one
  browser tab doesn't auto-refresh if changed elsewhere; the DEMO label
  and outcome shown in the run list come from `Run.status` plus one
  `GET /runs/{id}` per visible row rather than a dedicated field on
  `RunSummary` — fine at the current list size, worth revisiting with a
  backend change if the list ever needs to show many more rows; a
  LIVE-mode UI walkthrough wasn't exercised (needs a real browser
  capture and an Alpha Vantage key).
- **No known schema gaps remain.** The eight-table audit from Milestone
  10.5 fix 2 found two gaps; fix 3 closed both. Every field every
  pipeline dataclass produces now has a corresponding column.
- **`tools/economic_calendar.py` exists but was never wired into the
  workflow** (mentioned in `docs/architecture.md` as "contextual input
  for later"). Untouched since it was scaffolded — not part of the 12
  milestones, not started.
