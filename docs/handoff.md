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
- **Latest committed and pushed state:** `a7c085c` "docs: record the
  proposed-RR variation finding and confirm chart_variant is inert in
  LIVE mode" — a docs-only follow-up to the Iteration 1 commit. Both
  `b869f07` (the Iteration 1 UI/live-verification/fixture commit, tagged
  `7a-iteration-1`) and `a7c085c` are pushed; `origin/7a-iterations`
  points at `a7c085c`.
- **7A Iteration 1 is complete, tagged `7a-iteration-1` at `b869f07`
  (pushed), including the UI and live verification.** Agent-proposed
  trade levels (`agent_proposals` table, coherence checking in
  `backend/orchestrator.py` reusing `evals/trade_evaluator.py`'s
  `compute_risk_reward()`, `POST /runs/{run_id}/accept-proposal`) are
  built, tested, and verified against a **real Claude call** — not just a
  hand-seeded DEMO row. See `## 7A Iteration 1 — agent-proposed trade
  levels, never self-scored` and its `## 7A Iteration 1 addendum` in
  [docs/iterations.md](iterations.md) for the full history, including:
  two hardening requirements added before the build started (code-level
  rejection of any probability/confidence/percentage/likelihood/odds-named
  field regardless of type, and explicit rejection of both directions of
  a `proposal_has_proposal`/levels mismatch — read before touching
  `agents/trade_agent.py`'s `_parse_response()` again); a real finding
  that the original abstract DEMO fixture (`EURUSD_1h.png`) can never
  demonstrate a populated proposal (confirmed live, twice) and the fix —
  `chart_variant`, a second real DEMO fixture (`EURUSD_4h_readable.png`,
  an actual captured chart) with a properly paired quote, not a prompt
  change; and the frontend proposal panel, side-by-side display, and
  accept-and-navigate flow, all built and tested — **nothing about the UI
  is deferred anymore.**
- **7A Iteration 2 (multi-timeframe capture + cross-timeframe agreement
  guardrail) is approved, with three required changes, and is partway
  built.** See "The 7A plan" below for the full approved scope. **As of
  this doc update, the backend exists only in an uncommitted working
  tree** — schema/migration, the confirmation agent call, orchestrator
  wiring, the twelfth guardrail, and 335 passing backend tests are done;
  the frontend UI, the `docs/iterations.md` entry, the commit, and the
  `7a-iteration-2` tag are still outstanding, and one fixture-verification
  question is still unresolved (see below). **A fresh session should run
  `pytest` from the repo root first** to see whether that uncommitted
  work is still present before assuming Iteration 2 hasn't started — do
  not re-implement what's already there.
- **The four evidence runs — do not delete, do not reset the dev
  database.** Preserved in `database/tradepilot.db` (not committed —
  gitignored, as always) specifically because they're the only record
  behind two Iteration 1 findings: the proposed-RR-varies-with-context
  observation and the leak-path proof (agent proposal math never reaching
  the run's own score). Full detail in
  [docs/iterations.md](iterations.md)'s Iteration 1 addendum and the RR
  finding entry — not repeated here, just identified so nothing gets
  reset by accident:
  - `80da6bc6...` — DEMO abstract fixture, no user levels, agent declined.
  - `832f6885...` — DEMO abstract fixture, user levels supplied, agent declined.
  - `ed4e50b2...` — LIVE EURUSD 4h, user levels `RR=2.0`, agent's own
    proposal (different numbers) also came out to `RR=2.0`.
  - `cd25a285...` — hybrid (LIVE capture + real Claude call + DEMO
    quote), no user levels, agent proposed `RR≈1.83`; the run's own
    `evaluations.risk_reward_ratio` and `risk_reward_score` are both
    `NULL` — the leak-path proof, live.
- **Test counts:** 292 backend + 44 frontend as of the last **committed**
  state (`a7c085c`). The uncommitted Iteration 2 backend work brings the
  backend suite to 335 locally — not yet reflected in a commit or in
  `docs/iterations.md`; treat both counts as provisional until Iteration
  2 actually lands.
- **Alpha Vantage's free-tier daily quota (25 requests) was exhausted
  during Iteration 1's live verification** and its status is still
  unknown — no visibility into the exact remaining count or reset time
  beyond the API's own error text; check the Alpha Vantage account
  dashboard before spending more LIVE market-data calls. `.env` is
  restored to `CAPTURE_MODE=demo`/`MARKET_DATA_MODE=demo`. **The
  recording needs zero LIVE calls**: `demo_chart_variant=readable_chart`
  reproduces the full proposal flow deterministically in DEMO mode — see
  above.

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
   — which creates a brand-new run — and is shown for comparison in the
   UI (`AgentProposalPanel`, side by side with the user's own levels when
   both exist). See "The 7A-specific invariant" below; this is the entire
   reason the iteration is designed the way it is. **Complete — backend
   and UI both built, tested (292 backend tests up from 224, 44 frontend
   tests up from 32), and verified against a real Claude call** (twice
   against a real chart with visible structure — both times it proposed —
   and twice against the original abstract DEMO fixture — both times it
   correctly declined; see docs/iterations.md's addendum for the full
   live-run evidence). Tagged `7a-iteration-1`.
2. **Iteration 2 — multi-timeframe capture + cross-timeframe agreement
   guardrail.** Design approved. **Status: backend implemented in an
   uncommitted working tree (335 backend tests passing at the time of
   this doc update) — frontend UI, the `docs/iterations.md` entry,
   commit, and the `7a-iteration-2` tag are still outstanding.** Every
   6C and 7A Iteration 1 invariant (section 4 below) is unchanged by this
   scope — confirmed structurally (no new scoring path, guardrails still
   only ever downgrade, no new fallback logic), not just asserted.

   **Approved scope:**
   - Two timeframes via a fixed ladder
     (`1m→5m→15m→30m→1h→4h→1d→1w`) — the confirmation timeframe is
     always the next rung up the primary. Top of the ladder means no
     confirmation timeframe exists at all — N/A, not a failure.
   - `Capture.timeframe_role` (`"PRIMARY"`/`"CONFIRMATION"`) distinguishes
     a run's up-to-two captures; no new table needed for that part (a new
     `confirmation_analyses` table *was* added, for the confirmation
     call's own result, analogous to `agent_analyses`).
   - Agreement is derived by the orchestrator, never stated by the
     agent — the confirmation call only ever reports its own
     `trend_direction`/`trend_quality` for the confirmation chart;
     `guardrails/rules.py` decides whether that agrees with the primary
     read. Fails closed (never reports agreement) whenever it genuinely
     can't be confirmed: either side `SIDEWAYS`/`UNCLEAR`, a failed
     confirmation capture, or a failed confirmation analysis.
   - A twelfth guardrail, `CROSS_TIMEFRAME_AGREEMENT`, in
     `REVIEW_FORCING_RULES` — review-forcing, never blocking, the same
     category as `UNCERTAINTY_ACCEPTABLE`/`SYNTHETIC_DATA`.
   - `evals/trade_evaluator.py` is untouched — the two new confirmation
     fields are never scored, only ever read by the new guardrail.
   - No proposal-specific wiring — accepting a proposal (Iteration 1)
     works exactly as before.
   - **The UI is being built this iteration, not deferred** — a
     deliberate correction from how Iteration 1 initially treated its
     own UI before that was pushed back on.

   **Three required changes to the design, given explicitly before
   implementation started:**
   1. **Two separate agent calls, one image each — never one call with
      two images.** `TradeAgent.analyze()` (primary) stays byte-identical
      to the single-timeframe path — proven by a dedicated test
      comparing its exact prompt text and image-block count.
      `analyze_confirmation()` is a second, independent Claude call with
      its own minimal prompt, returning only
      `confirmation_visible_timeframe`/`confirmation_trend_direction`/
      `confirmation_trend_quality`. Reason: Iteration 1's own live-run
      evidence showed agent output varies with what it's shown (see the
      evidence runs above) — conditioning the primary's five *scored*
      categories on a second image would silently change what those
      categories mean, breaking 6C comparability and Iteration 4's
      reproducibility baseline before it's even built.
      `MarketDataManager.get_quote()` stays at exactly one call per run
      (Alpha Vantage is the constrained resource here, not Anthropic) —
      also proven by a dedicated test.
   2. **Detect an identical confirmation capture.** A SHA-256 hash
      comparison of both capture images, computed in the orchestrator
      (not `guardrails/rules.py`, which stays a pure function over
      explicit inputs, the same principle `CAPTURE_FRESH`/
      `MARKET_DATA_FRESH` already apply to `now`) — an identical hash
      means the TradingView timeframe switch may not have taken effect,
      and `CROSS_TIMEFRAME_AGREEMENT` fails closed. Separately, the
      confirmation call echoes back the timeframe label it can actually
      read off the chart; the orchestrator compares it
      (case/whitespace-insensitive) against the timeframe it actually
      requested — a mismatch is also treated as a failed confirmation
      capture. Both proven with dedicated tests, including one that
      feeds the identical image to both capture calls and confirms the
      run does not report agreement.
   3. **The migration must not destroy the evidence runs.**
      `Capture.timeframe_role` was added to the real dev database via a
      raw `ALTER TABLE` against the live file (backed up first as
      `database/tradepilot.db.pre-iteration2-backup`), **not** the usual
      delete-and-recreate — existing rows were explicitly backfilled to
      `"PRIMARY"`. All four evidence runs above were re-queried through
      the ORM immediately after the migration, and again after every
      subsequent schema change, and confirmed to still have their
      proposals and evaluations intact throughout.

   **Also required before committing the new DEMO fixture, not yet
   resolved:** verify that a fresh `EURUSD_1h_readable` capture actually
   agrees with the already-committed `EURUSD_4h_readable.png` rather than
   assuming it — the same "verify, don't assume" lesson as the original
   abstract-fixture finding. **Done once, inconclusive:** a fresh LIVE
   1h capture came back `trend_direction=UNCLEAR` against the existing 4h
   fixture — fail-closed, neither agreement nor disagreement, plausibly a
   real closed-weekend-market artifact rather than a bug. Not yet
   decided: retry the capture, keep this result as the (also legitimate)
   fail-closed demo path, or try a different symbol/timeframe pair. A
   fresh session should ask before committing any `EURUSD_1h_readable.png`
   fixture rather than assuming an answer.
3. **Iteration 3 — economic calendar tool + event-proximity block.**
   Wires up `tools/economic_calendar.py` — scaffolded since the early
   milestones, mentioned in [docs/architecture.md](architecture.md) as
   "contextual input for later," never actually called by anything — into
   a new guardrail that blocks or forces review near a scheduled event.
   Not yet designed.
4. **Iteration 4 (if time) — eval harness measuring agent reproducibility
   across repeated runs on a golden set.** Not yet designed. Has a
   concrete motivating question now, from real live-run evidence: does
   proposed RR cluster on the user-supplied value when one is present,
   across many repeated runs on the same chart? See "An empirical
   observation: proposed RR varies with what the agent was shown" in
   [docs/iterations.md](iterations.md)'s Iteration 1 addendum —
   `ed4e50b2...`'s proposal matched the user's own `RR=2.0` on different
   numbers, `cd25a285...`'s (no user levels) came out to `RR≈1.83`.
   `n=2` settles nothing; this is the question a golden-set harness
   would actually answer.

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
  renders this** (`frontend/src/components/AgentProposalPanel.tsx`,
  wired into `RunDetailView.tsx`): a dashed, visually distinct panel
  labelled "unscored," side by side with the user's own levels when both
  exist, the proposal's own risk/reward ratio labelled "informational
  only — not part of the score," and a plain decline notice (with the
  agent's own stated reasoning, when available) rather than an empty
  panel when the agent declines.
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
