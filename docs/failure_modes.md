# Failure modes

TradePilot AI's entire purpose is to help a human decide whether a trade
setup is worth their attention — never to decide *for* them, and never to
show them a result that's dressed up as more trustworthy than it actually
is. A demo that only shows a clean, successful run proves none of that.
This document is the other half: eleven scenarios, each one a real,
reproducible run through the actual pipeline, each one showing a specific
safety mechanism actually doing its job.

You do not need to read any code to follow this document. Each scenario
says exactly what to click or type, exactly what the system does, which
guardrail is responsible, what you'll see on screen, and why that's the
correct behavior — not just "what happens," but why a different behavior
would be worse.

## How to reproduce these yourself

Four of the eleven scenarios (6, 7, 10, 11) happen through completely
normal use of the app — real form input, real button clicks, nothing
special. The other seven (1–5, 8, 9) can't be produced through input
alone, because they depend on things this app deliberately doesn't let
you control from a form: exact timing, or what a live AI model happens to
say. For those seven, TradePilot AI has a **testing affordance**: a
dropdown in the Analyze panel labeled *"Testing only — force a failure
scenario."*

**What it is.** A `force_scenario` option on `POST /runs/{run_id}/analyze`
that deliberately substitutes a synthetic result for exactly one pipeline
stage — a `FAILED` capture, an artificially aged timestamp on an
otherwise-real successful capture, a `FAILED` agent analysis, or a
synthetic-but-realistic agent analysis with `HIGH` uncertainty or perfect
categories. It never fabricates a score or a guardrail verdict — the
evaluator and the guardrails always run for real, on whatever the stage
produced, real or forced.

**Why this design, and not something else.** Three choices, each made
deliberately:

- **A backend flag, gated behind an environment variable that defaults to
  off (`TESTING_CONTROLS_ENABLED`).** Set it to `true` in `.env` and
  restart the backend to use the dropdown at all; leave it unset (or
  `false`, the default) and the dropdown still appears in the UI, but the
  backend refuses every request that uses it with a `403`. This means the
  mechanism cannot affect a real run's honesty by accident — it takes a
  deliberate, out-of-band decision by whoever runs the backend, not
  something a stray click or a copied URL could trigger.
- **Every forced run says so, loudly, in multiple places.** The very
  first thing `run_pipeline()` writes for a forced run is an audit event
  saying so in plain English. The detail view shows a dashed amber
  banner reading *"Testing run — not a real analysis"* the moment that
  event is present. Every synthetic value's own text starts with
  `TESTING:`. There is no path to seeing a forced run's result without
  also seeing that it was forced.
- **Only ever fabricates a stage's *input*, never its output.** A forced
  "perfect score" run still has its 100 computed for real by
  `evals/trade_evaluator.py` from synthetic-but-realistic category words
  — never a hardcoded 100. This is what makes scenario 9 an actual proof
  that `SYNTHETIC_DATA` catches a perfect score, rather than a claim that
  it would.

To turn it on yourself: add `TESTING_CONTROLS_ENABLED=true` to `.env`,
restart the backend (`uvicorn backend.main:app --reload`), open the app,
and the dropdown in the Analyze panel will do something. Set it back to
`false` (or remove the line) when you're done — it's not something to
leave on.

---

## Scenario 1 — Capture fails

**What I do:** In the Analyze panel, leave Symbol/Timeframe at their
defaults, choose **"Capture fails"** from the testing dropdown, and click
**Analyze**.

**What the system does:** `backend/orchestrator.py` never calls the real
`CaptureManager` for this run — it substitutes a `FAILED` `CaptureResult`
whose error message says plainly it was forced. Because capture failed,
the agent is never called (confirmed directly in the automated test via
a mock: `mock_agent.analyze.assert_not_called()`). Market data is still
fetched for real, since it doesn't depend on capture succeeding. All
eleven guardrail checks still run and are all recorded.

**Which guardrail fires:** `CAPTURE_SUCCEEDED` — a **blocking** rule.
Real output: `"Chart capture did not succeed (status=FAILED): TESTING:
capture deliberately forced to fail..."`.

**What the UI shows:** The Chart capture card shows *"Chart capture
failed"* with the real message, in place of the image — never a broken
image icon, never an empty box. The Agent analysis and Evaluation cards
both show *"Status: FAILED"* with their own real messages (the agent was
never even asked). The overall status badge reads **BLOCKED**. All
eleven guardrail rows are present and readable.

**Why this is correct:** There's no chart to show a human, so there's
nothing to evaluate and nothing worth a human's time reviewing yet.
Calling the agent anyway would mean asking it to describe a chart that
was never actually captured — exactly the "no fabricated data" rule this
whole app is built around. `BLOCKED` is the only honest outcome.

---

## Scenario 2 — Capture stale

**What I do:** Choose **"Capture stale"** from the dropdown, click
**Analyze**.

**What the system does:** The *real* `CaptureManager` runs and succeeds
— a genuine screenshot, a genuine timestamp. The orchestrator then
overrides that timestamp to two hours in the past before persisting it
(comfortably older than the default 300-second limit). Market data,
agent analysis, and evaluation all run normally and succeed for real.

**Which guardrail fires:** `CAPTURE_FRESH` — blocking. Real output from
a run I just executed: `"Chart is 7200s old, older than the 300s limit
(captured_at=2026-08-08T04:35:33.014780+00:00)."` — while
`CAPTURE_SUCCEEDED` itself still **passes**, since the capture really did
succeed.

**What the UI shows:** The chart image renders normally (it's a real,
valid image) and the analysis and evaluation sections show real content
— a total score of 76 in the run I captured this from. But the overall
status is still **BLOCKED**, and the Guardrails card shows
`CAPTURE_FRESH` failed while everything else passed.

**Why this is correct:** This is the scenario that proves freshness is
checked *independently* of success. A pipeline can work perfectly and
still be untrustworthy if the input is old — a chart from two hours ago
might not reflect the market anymore. The guardrail exists specifically
to catch "everything worked, but the input is stale," a failure mode
that "did the capture succeed?" alone would never catch.

---

## Scenario 3 — Market data fails

**What I do:** Choose **"Market data fails"**, click **Analyze**.

**What the system does:** Capture runs for real and succeeds. Market
data is substituted with a `FAILED` `MarketQuote` — `price=None`,
`timestamp=None`. Because market data failed, the agent is never called
(same rule as scenario 1, the other direction). Guardrails still run
completely.

**Which guardrail fires:** `MARKET_DATA_SUCCEEDED` — blocking. Real
output: `"Market data fetch did not succeed (status=FAILED): TESTING:
market data fetch deliberately forced to fail..."`.

**What the UI shows:** The Market snapshot card shows *"Market data
fetch failed"* with the real message — critically, **no price is shown
at all**, not a zero, not a dash standing in for a number, nothing that
could be mistaken for a real quote. Status: **BLOCKED**.

**Why this is correct:** `tools/market_data.py`'s one absolute rule is
that a failure returns `price=None`, never an invented, estimated, or
carried-forward number — because a fabricated price would corrupt the
agent, the evaluation, and the guardrails simultaneously while still
looking legitimate. This scenario is the guardrail layer proving that
rule actually holds all the way through to the screen a human sees.

---

## Scenario 4 — Market data stale

**What I do:** Choose **"Market data stale"**, click **Analyze**.

**What the system does:** The mirror of scenario 2: a real, successful
quote fetch, with its timestamp overridden to two hours old before being
saved. Capture, agent, and evaluation all succeed for real.

**Which guardrail fires:** `MARKET_DATA_FRESH` — blocking. Real output:
`"Quote is 7200s old, older than the 900s limit (source
timestamp=2026-08-08T04:35:34.291161+00:00)."`, while
`MARKET_DATA_SUCCEEDED` passes.

**What the UI shows:** A real price, a real chart, a real analysis and
score — and still **BLOCKED**, with `MARKET_DATA_FRESH` the specific
failing row.

**Why this is correct:** Same reasoning as scenario 2, for the other
half of the pipeline's real-world inputs. A price that was accurate 15
minutes ago (the default `MARKET_DATA_MAX_AGE_SECONDS` limit) may not be
accurate now — markets move. Freshness is checked on the *source's own
reported time*, never on when the tool happened to be asked, specifically
so this guardrail measures how old the data genuinely is.

---

## Scenario 5 — Agent fails

**What I do:** Choose **"Agent fails"**, click **Analyze**.

**What the system does:** Capture and market data both run for real and
succeed. The agent stage is substituted with a `FAILED`
`AgentAnalysisResult` — no real Claude request is made. Because the
agent failed, evaluation is skipped entirely (there's nothing to score).

**Which guardrail fires:** `ANALYSIS_SUCCEEDED` — blocking. Real output:
`"Agent analysis did not succeed (status=FAILED): TESTING: agent
deliberately forced to fail... No Claude request was made."`.
`EVALUATION_SUCCEEDED` fails too, as a direct consequence.

**What the UI shows:** The chart and market snapshot render normally.
The Agent analysis card shows *"Status: FAILED"* with the real message,
no categorical fields, no prose. The Evaluation card shows *"Status:
FAILED"* too — **not a zero, not any number at all**: `total_score`,
every component score, and `risk_reward_ratio` are all `null` in the raw
API response. Status: **BLOCKED**.

**Why this is correct:** This is the most direct proof of the boundary
this whole app is built around: if there's no analysis, there is
categorically nothing to score, and the evaluator (`evals/
trade_evaluator.py`) checks the agent's status *before* doing anything
else and returns immediately if it isn't `SUCCESS`. A missing score is
represented as `null`, never as `0` — `0` is itself a real, meaningful
score (a poor setup can genuinely earn one), and storing it here would
make a "the agent never even ran" run indistinguishable from a
genuinely-scored zero.

---

## Scenario 6 — Risk/reward below minimum

**What I do:** No dropdown needed — this is ordinary input. Symbol
`EURUSD`, Direction `long`, Entry `1.0950`, Stop `1.0900`, Target
`1.0960` (reward distance 0.0010 against risk distance 0.0050 — RR =
0.2). Click **Analyze**.

**What the system does:** Everything runs for real and succeeds,
including the agent (a real Claude call, or you can pair this with the
"Perfect demo score" dropdown option to make the result deterministic
and free — either way the RR math is identical, since it comes from your
typed numbers, never the agent). `evals/trade_evaluator.py` computes RR
arithmetically from entry/stop/target — it never reads anything the
agent said.

**Which guardrail fires:** `RISK_REWARD_MINIMUM` — a **review-forcing**
rule, not blocking. Real output: `"Risk/reward ratio 0.20 is below the
minimum of 1.00."` In the run that produced this evidence, the four
subjective components still scored a genuine 80/80 (perfect categories,
`LOW` uncertainty) — the risk/reward component alone scored 0, for a
total of 80.

**What the UI shows:** A complete, real analysis and score — 80/100 in
this case, `risk_reward_score` showing `0` right next to `ratio 0.20`, so
the connection between the number and the reason is visible on the
score row itself. Status: **REQUIRES_REVIEW**, not `BLOCKED`.

**Why this is correct:** The pipeline worked. The chart was readable,
the analysis was real, the math is real. The setup itself is just bad —
risking five times what you could gain. That's exactly what
"review-forcing" rules are for: the difference between "there's nothing
here to show a human" (`BLOCKED`) and "here's a real result, but it
isn't good enough to skip a human's judgment" (`REQUIRES_REVIEW`).

---

## Scenario 7 — Incoherent trade params

**What I do:** Ordinary input again. Direction `long`, Entry `1.0950`,
**Stop `1.1000`** (above entry — the wrong side for a long trade), Target
`1.1050`. Click **Analyze**.

**What the system does:** `compute_risk_reward()` (the same function
both the evaluator and the `TRADE_PARAMS_VALID` guardrail call, so the
two can never quietly disagree) detects the stop is on the wrong side of
entry for a long trade and returns an error instead of a ratio. The
evaluator sees this and returns a `FAILED` evaluation immediately,
without scoring anything else.

**Which guardrail fires:** Two, actually — `TRADE_PARAMS_VALID`
(blocking): `"Trade parameters are not valid: stop is on the wrong side
of entry for a long trade (entry=1.095, stop=1.1)"`, and
`EVALUATION_SUCCEEDED` (also blocking, since the evaluation itself
failed) with the identical underlying reason.

**What the UI shows:** Chart and market data render normally, and — if
you pair this with a forced agent scenario — the agent's categories show
too. But the Evaluation card shows *"Status: FAILED"* with that exact
message: **not a guessed ratio, not a 0, not a blank total** — `null`
scores across the board. Status: **BLOCKED**.

**Why this is correct:** A stop on the wrong side of entry isn't a bad
trade, it's a nonsensical one — there's no real risk/reward number to
compute at all, only an error to report. Guessing a ratio (even a
conservative one) here would be indistinguishable from a real,
computed number once it reached the screen — exactly the kind of
silent fabrication this rubric is built to avoid. Failing loudly and
specifically is the only honest option.

---

## Scenario 8 — High agent uncertainty

**What I do:** Fill in a genuinely good trade setup (Entry `1.0950`,
Stop `1.0900`, Target `1.1050`, RR 2.0), choose **"High agent
uncertainty"** from the dropdown, click **Analyze**.

**What the system does:** The agent stage is substituted with a
synthetic `SUCCESS` result carrying the *best* possible categorical
values (`STRONG`/`CLEAN`/`ACCEPTABLE`/`LOW` risk) but `uncertainty:
HIGH`. `evals/trade_evaluator.py` applies `UNCERTAINTY_CAPS` — `HIGH`
caps each of the four subjective components at 8 points (out of a raw
20), no matter how good the underlying category. Risk/Reward is exempt
from the cap (it's arithmetic, not a reading of the chart), so it still
scores its full 20.

**Which guardrail fires:** `UNCERTAINTY_ACCEPTABLE` — review-forcing.
Real output: `"Agent uncertainty is HIGH; a human must review this
run."` In the run that produced this evidence, the total score landed
at exactly 52 — `docs/rubric.md`'s documented HIGH-uncertainty ceiling,
reached here with the best possible categories, proving 52 really is the
maximum, not just a number in a table.

**What the UI shows:** A real 52/100 total, `SCORE_THRESHOLD` *also*
shown failing (52 is below the default minimum of 60) alongside
`UNCERTAINTY_ACCEPTABLE` — two independent reasons pointing the same
direction. Status: **REQUIRES_REVIEW**, never `READY_FOR_REVIEW`.

**Why this is correct:** The agent itself is telling you it isn't sure
what it's looking at. A high score built on top of "I'm not sure" would
be actively misleading — the whole point of asking the agent to report
its own uncertainty (and instructing it, in `prompts/system_prompt.md`,
to prefer honest "I can't tell" language over a confident-sounding
guess) is so the score can't pretend to a confidence the agent doesn't
have.

---

## Scenario 9 — Demo run with a perfect score

**What I do:** The same good trade setup as scenario 8, choose
**"Perfect demo score"** from the dropdown, click **Analyze**.

**What the system does:** The agent stage is substituted with a
synthetic `SUCCESS` result carrying the single best value for every
category (`STRONG`/`CLEAN`/`TEXTBOOK`/`LOW` risk, `LOW` uncertainty — no
cap applied at all). With a coherent RR-2.0 trade setup, the *real*
evaluator computes a genuine 100/100: 4 × 20 for the subjective
components, 20 for risk/reward. This total is not hardcoded anywhere —
it's the actual output of `evals/trade_evaluator.py` given this input,
confirmed in the automated test and in the real run this evidence came
from.

**Which guardrail fires:** `SYNTHETIC_DATA` — review-forcing, and the
**only** rule failing in this scenario; every other one of the eleven
passes, including `SCORE_THRESHOLD` at a perfect 100. Real output:
`"Run uses DEMO/sample data (chart capture, market data). A run built on
sample data must always require human review and must never be
presentable as a validated live one."`

**What the UI shows:** A genuinely perfect scorecard — 100/100, every
guardrail green except one — and still **REQUIRES_REVIEW**, never
**READY_FOR_REVIEW**. The DEMO badge appears everywhere data from this
run appears: the chart panel, the market panel, the review panel, and
the run list.

**Why this is correct:** This is the single most important scenario in
this document, because it's the one where every *other* signal says
"this is great" and the system still refuses to call it validated. DEMO
mode exists so the rest of this app can be built and tested without a
live browser or a market-data API key — but a run built on sample data
must never be presentable as equivalent to a real, live-validated one,
no matter how good it looks. `SYNTHETIC_DATA` is checked completely
independently of the score (it only reads `capture_result.mode` and
`market_data_result.mode`) specifically so a good score can never buy
its way past it.

---

## Scenario 10 — Approving a BLOCKED run

**What I do:** Take the `BLOCKED` run from scenario 1 (or any `BLOCKED`
run). In the UI, look at the Human review card. Separately, to prove the
API itself enforces this and not just the UI: `curl -X POST
http://127.0.0.1:8000/runs/{run_id}/review -d '{"decision":
"APPROVED"}'`.

**What the system does:** `backend/api/routes_runs.py`'s review endpoint
computes the run's guardrail outcome from its stored `GuardrailResult`
rows before doing anything else. If the outcome is `BLOCKED` (or
missing entirely), the request is refused before a `HumanReview` row is
ever written.

**Which guardrail fires:** None directly — this is the review endpoint
enforcing the *outcome* a guardrail pass already produced. Real API
response: `409 Conflict`, `"Run ... cannot be approved: the guardrails
blocked this run. Only REJECTED is permitted."`

**What the UI shows:** The **Approve** button is disabled *before you
even try* — greyed out, with the exact reason printed above it:
*"Guardrails BLOCKED this run — see the guardrail results below for the
failing rule. Only REJECT is available."* **Reject**, in contrast, is
always enabled and works normally on this same run.

**Why this is correct:** `BLOCKED` means the pipeline itself didn't
produce anything usable — there's nothing here for a human to
meaningfully accept. `REJECTED` staying available regardless is
deliberate too: there's always something worth recording about a human
declining a setup, even a broken one, and rejecting requires no
evidence the pipeline worked.

---

## Scenario 11 — Deciding twice

**What I do:** Take any run that already has a decision (reject the
scenario 1 run from scenario 10, for instance). Try to approve or reject
it again — in the UI, the buttons are already disabled and the recorded
decision is shown instead. To prove the API enforces this too: `curl -X
POST http://127.0.0.1:8000/runs/{run_id}/review -d '{"decision":
"APPROVED"}'` a second time.

**What the system does:** The review endpoint checks
`run.human_review is not None` *before anything else* — before even
checking whether the new decision would have been valid. If a decision
already exists, the request is refused immediately.

**Which guardrail fires:** None — `HumanReview.run_id` is a unique
database column, and this is the endpoint respecting that. Real API
response: `409 Conflict`, `"Run ... already has a decision (REJECTED,
recorded at ...). A decision is final."`

**What the UI shows:** Both **Approve** and **Reject** are disabled, and
the original decision — its outcome, its timestamp, its comment — is
shown in their place. Nothing about the original decision changes,
confirmed directly: `GET /runs/{run_id}` after the refused second
attempt still shows the exact original decision and comment.

**Why this is correct:** A human's judgment about a trade setup is
exactly the kind of thing that should never be silently overwritten — if
a decision could be quietly changed later, the audit trail would no
longer be a reliable record of what was actually decided and when. If a
reviewer genuinely changes their mind, that's a new decision about a new
analysis, not an edit to the old one.

---

## Automated tests

Every scenario above also exists as an automated, end-to-end test in
`tests/test_failure_scenarios.py` — real `DemoProvider`/
`DemoMarketDataProvider` fixtures, the real orchestrator, the real
guardrails, run through the real API (`TestClient`), not isolated unit
tests with hand-built fixtures. Two additional tests cover the
mechanism itself: `force_scenario` is refused with `403` when
`TESTING_CONTROLS_ENABLED` is off (the default), and an unrecognized
`force_scenario` value is refused with `422`. A further test confirms an
ordinary analysis with no `force_scenario` at all is completely
unaffected by the mechanism existing. See `docs/iterations.md`'s
Milestone 12 entry for the full test list and results.
