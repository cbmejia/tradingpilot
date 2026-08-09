# Session handoff

Written for a brand-new Claude Code session with zero conversation
history. Read this first, then the docs it links to rather than
duplicates: [docs/architecture.md](architecture.md),
[docs/iterations.md](iterations.md), [docs/rubric.md](rubric.md),
[docs/failure_modes.md](failure_modes.md), and the root
[README.md](../README.md).

## 1. Current state

- **6C is complete and tagged `6c-baseline`.** All twelve originally
  planned milestones — see the annotated tag, and the command to return
  to exactly that state, in [docs/iterations.md](iterations.md)'s
  Milestone 12 entry and its Roadmap checklist at the bottom.
- **One post-baseline defect fix landed after the tag:** a live-run
  agent-response truncation bug (`max_tokens` raised 1024→2048 and made
  configurable, the prompt tightened to stop inviting unbounded prose).
  See the `## fix: agent response truncation on live runs` entry in
  [docs/iterations.md](iterations.md) for the full diagnosis and fix —
  it deliberately added no retry-on-truncation logic and no partial-JSON
  recovery; a malformed response is still a `FAILED` analysis.
- **Latest commit:** `585f625` "chore: dry run sweep script for demo
  prep" (an operational script, `dry-run.ps1`, not a milestone or an
  iteration — no doc entry needed for it).
- **7A Iteration 1 is complete.** Agent-proposed trade levels
  (`agent_proposals` table, coherence checking in `backend/orchestrator.py`
  reusing `evals/trade_evaluator.py`'s `compute_risk_reward()`,
  `POST /runs/{run_id}/accept-proposal`) are built, tested, and manually
  verified against a real running server. See the `## 7A Iteration 1 —
  agent-proposed trade levels, never self-scored` entry in
  [docs/iterations.md](iterations.md) for the full design, including two
  hardening requirements added before the build started (code-level
  rejection of any probability/confidence/percentage/likelihood/odds-named
  field regardless of type, and explicit rejection of both directions of
  a `proposal_has_proposal`/levels mismatch) — read that entry before
  touching `agents/trade_agent.py`'s `_parse_response()` again, since both
  requirements are about the enforcement being in code, not just the
  prompt. **The frontend has no UI for proposals yet** — deliberately
  deferred, same pattern 6C used for every pipeline tool before Milestone
  11 wired the UI up; not scheduled.
- **7A Iteration 2 (multi-timeframe capture + cross-timeframe agreement
  guardrail) has not started.** Awaiting a go-ahead per the "one iteration
  at a time" working agreement below. Iterations 3–4 haven't been
  designed at all yet.
- **Test counts as of 7A Iteration 1 (last real run):** 271 backend tests
  + 32 frontend tests, all passing. Backend: 46 database + 32 API + 17
  capture + 19 market data + 53 agent + 34 evaluation + 36 guardrails +
  20 orchestrator + 14 failure scenarios. These will grow once 7A
  Iteration 2 lands — treat this count as stale the moment more 7A code
  exists.

## 2. The 7A plan

Four iterations, in order, agreed before any 7A code was written. **Do
not start iteration N+1 without an explicit go-ahead**, exactly the same
"one milestone at a time" rule 6C ran under (see "Working agreement"
below) — it applies to 7A iterations the same way it applied to 6C
milestones.

1. **Iteration 1 — agent-proposed trade levels, never self-scored.** The
   agent proposes an entry/stop/target/direction: an *alternative* when
   the user supplied their own levels, or its own idea when the user
   supplied none. The proposal is stored separately from anything
   `evals/trade_evaluator.py` reads, only becomes real scored input when a
   human explicitly accepts it via `POST /runs/{run_id}/accept-proposal`
   — which creates a brand-new run — and is *not yet* shown for
   comparison in the UI (deliberately deferred; see below). See "The
   7A-specific invariant" below; this is the entire reason the iteration
   is designed the way it is. **Complete — backend built, tested (271
   backend tests, up from 224), and manually verified against a real
   running server. Tagged `7a-iteration-1`.**
2. **Iteration 2 — multi-timeframe capture + cross-timeframe agreement
   guardrail.** Not yet designed.
3. **Iteration 3 — economic calendar tool + event-proximity block.**
   Wires up `tools/economic_calendar.py` — scaffolded since the early
   milestones, mentioned in [docs/architecture.md](architecture.md) as
   "contextual input for later," never actually called by anything — into
   a new guardrail that blocks or forces review near a scheduled event.
   Not yet designed.
4. **Iteration 4 (if time) — eval harness measuring agent reproducibility
   across repeated runs on a golden set.** Not yet designed.

## 3. The 7A-specific invariant

**Agent-proposed entry/stop/target are never automatically scored.**

`risk_reward_score` is the one rubric component computed purely from
arithmetic on real numbers (see [docs/rubric.md](rubric.md)) — every
other component is capped by the agent's own stated uncertainty, but
Risk/Reward is exempt, because it's a fact about numbers the user typed
in, not a reading of an ambiguous chart. That exemption only holds because
the agent has zero influence over which numbers go into that arithmetic
today.

The moment the agent is allowed to propose entry/stop/target *and* have
those numbers scored automatically, that stops being true: the agent
could simply propose levels arithmetically engineered to `RR = 2.0` (or
higher) and guarantee itself the full 20 points on the one component
uncertainty can't touch — turning the one genuinely agent-proof number in
the whole rubric into the easiest one to game.

So: a proposal is data, not input to scoring, until a human says
otherwise. Concretely —

- Proposed levels are stored in their own place (`agent_proposals`, not
  `agent_analyses`, not `evaluations`), never read by
  `evals/trade_evaluator.py` at all. A test proves this directly — the
  evaluator's behavior on a run with a stored proposal must be identical
  to its behavior on a run with none.
- Proposed levels are available via `GET /runs/{run_id}` (the `proposal`
  field, alongside the user's own levels on the same response) for a
  human to compare — never merged into the same score. **The frontend
  doesn't render this yet** — `GET /runs/{run_id}` returning it is done;
  a UI panel showing it side-by-side with the user's own levels is
  deliberately deferred, the same "build the tool standalone before
  wiring the UI" pattern 6C used throughout. Not scheduled.
- The *only* way a proposal becomes something that gets scored is a
  human explicitly accepting it, and accepting it doesn't score the
  original run — it creates a **new** run, with the accepted levels
  stored as ordinary user-supplied `Run.entry/stop/target`, indistinguishable
  from a run someone typed in by hand. The audit trail on both runs
  records that a human made that choice.
- Coherence checking (stop on the correct side, non-zero risk distance)
  happens exactly once, in `backend/orchestrator.py`, reusing
  `evals/trade_evaluator.py`'s `compute_risk_reward()` — the same
  function `guardrails/rules.py` already reuses for the user's own
  params, not a second implementation. It cannot live in
  `agents/trade_agent.py` (would create a circular import with `evals/`)
  or in `database/crud.py` (would break the standing "database/ stays a
  leaf module" rule — see the comment on `AGENT_CATEGORICAL_FIELDS` in
  `database/models.py`).

## 4. The non-negotiable invariants

These hold regardless of which milestone or iteration is being worked
on — 6C's and 7A's alike. Each one has a specific enforcement point in
the code — if a change would weaken any of these, stop and ask rather
than proceeding.

- **(a) Never places, submits, or simulates a trade.** There is no
  broker/order-execution integration anywhere, and none is planned.
  The only terminal states a run can reach are `APPROVED`/`REJECTED` —
  both are just database writes. See "Non-negotiables" in
  [docs/architecture.md](architecture.md).
- **(b) The agent emits words and categories, never a score.**
  `agents/trade_agent.py`'s `_parse_response()` rejects the entire
  response if any field is a number where a word is expected, or an
  unrecognized category value. All scoring is
  `evals/trade_evaluator.py`, deterministic Python. (7A Iteration 1 adds
  a narrow, explicit carve-out for exactly three field names —
  `proposal_entry`/`proposal_stop`/`proposal_target` — so the agent can
  state a proposed price level; see "The 7A-specific invariant" above
  for why that carve-out can never become a scoring path.)
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

## 5. Working agreement

- **One milestone (or 7A iteration) at a time.** Do not start the next
  one without an explicit go-ahead, even if the current one's tests pass
  and the commit is made.
- **Run the entire test suite, not just new tests**, after every
  change — `pytest` from the repo root.
- **Explain in plain language.** The user is not an experienced
  developer — narrate what's being built and why before/while writing
  code, not just what the code does.
- **Update `docs/iterations.md`** with a new dated section at the end
  of every milestone/iteration (and `README.md` when setup/usage
  instructions change), before committing. For 7A specifically, each
  entry must record not just what changed but **why** — the design
  tension and how it was resolved — since this is graded capstone
  evidence, not just a changelog.
- **Commit at the end of each milestone/iteration**, one phase per
  commit, prefixed accordingly, e.g. `"Milestone 10 - human approval and
  decision audit"` or `"7A Iteration 1 - agent-proposed trade levels,
  never self-scored"`.
- **Tag at the end of each 7A iteration**, the same pattern
  `6c-baseline` used for the whole of 6C: an annotated git tag per
  iteration (`7a-iteration-1`, `7a-iteration-2`, ...), created after the
  commit and after `docs/iterations.md` is updated, not before.
- When a "before the next milestone/iteration, fix a defect" request
  comes in, treat it as its own small task: fix, test, document, commit
  — then wait for the go-ahead on the next milestone/iteration itself.

## 6. Gotchas already hit

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
- **A live-run agent response was truncated mid-JSON.** The real cause
  was `max_tokens=1024` combined with a prompt that never told the model
  its prose could be short — not a parsing bug. Diagnosed via
  `response.stop_reason == "max_tokens"`, checked before parsing is even
  attempted. Fixed by raising `max_tokens` and tightening the prompt;
  deliberately did **not** add retry-on-truncation or partial-JSON
  recovery — a malformed response stays a `FAILED` analysis (see the
  `## fix: agent response truncation on live runs` entry in
  [docs/iterations.md](iterations.md)).

## 7. How to run everything

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

## 8. What's not built, and what's genuinely still weak

The 6C plan is complete — this section is no longer "what's next for
6C," it's "what was deliberately left out of 6C, and where the project
is honestly weakest going into 7A." Both are worth reading before
assuming a gap needs fixing; some of these are documented tradeoffs, not
oversights. (7A's own open items are tracked in "The 7A plan" above, not
here.)

- **No authentication or rate limiting on the API.** Named plainly as
  the weakest part of the project in the Milestone 12 final review.
  Fine for a single developer on `localhost` (how this has been built
  and run throughout); a real risk — spammable, and `POST
  /runs/{id}/analyze` can cost real money per call — the moment this is
  ever reachable from anywhere else. If a future request is "expose
  this beyond localhost" or "add multi-user support," this is the first
  thing that needs solving, not an afterthought.
- **LIVE mode is comparatively unproven at scale.** Named as the second
  weakest part at the Milestone 12 review. A real LIVE run has since been
  exercised end to end (see the truncation-fix entry above), but that was
  one manual run, not a sustained or automated one — real TradingView
  scraping (`capture/live_provider.py`) and real Alpha Vantage calls
  (`tools/market_data.py`) are still primarily unit-tested with mocks.
  Not architecturally unsafe (a real failure there still shows up as an
  honest `FAILED` result, per every invariant this project enforces) —
  just genuinely light on real-world mileage.
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
- **No known schema gaps remain from 6C.** The eight-table audit from
  Milestone 10.5 fix 2 found two gaps; fix 3 closed both. Every field
  every 6C pipeline dataclass produces has a corresponding column. (7A
  Iteration 1 will add a new table, `agent_proposals` — that's new
  surface area, not a gap in the old one.)
- **`tools/economic_calendar.py` exists but was never wired into the
  workflow.** Untouched since it was scaffolded in an early milestone —
  this is now explicitly **7A Iteration 3**, not an open-ended gap.
