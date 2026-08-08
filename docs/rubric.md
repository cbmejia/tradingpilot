# Evaluation rubric (v2)

This is the exact, deterministic rubric `evals/trade_evaluator.py`
implements. No AI is involved in scoring — every rule below is plain
Python you can read top to bottom.

**Revision note:** the original (v1) rubric scored four of the five
components from the agent's prose — a substantive-sounding paragraph
scored full marks regardless of what it actually said. v2 replaces that
with fixed category words the agent chooses from (never free text), so
the score reflects what the agent actually observed, not how much it
wrote. See "What v1 got wrong" at the bottom.

## The five components (20 points each, 100 total)

| Component | Reads | 20 points | 15 points | 10 points | 5 points | 0 points |
|---|---|---|---|---|---|---|
| **Trend** | `trend_direction` + `trend_quality` | UP/DOWN + STRONG | — | UP/DOWN + MODERATE | — | UP/DOWN + WEAK, **or** SIDEWAYS, **or** either field UNCLEAR |
| **Structure** | `structure_quality` | CLEAN | — | MIXED | — | CHOPPY, or UNCLEAR |
| **Entry** | `setup_quality` | TEXTBOOK | ACCEPTABLE | — | MARGINAL | NONE, or UNCLEAR |
| **Risk/Reward** | entry/stop/target — **arithmetic, not the agent's words** | RR ≥ 2.0 | — | 1.0 ≤ RR < 2.0 | — | RR < 1.0 |
| **Timing/Context** | `context_risk` | LOW | — | MODERATE | — | ELEVATED, or UNCLEAR |

## Component detail

**Trend** reads two category fields together, because neither one alone
is enough: `trend_direction` (`UP` / `DOWN` / `SIDEWAYS` / `UNCLEAR`)
says *whether* there's a direction at all, and `trend_quality`
(`STRONG` / `MODERATE` / `WEAK` / `UNCLEAR`) says *how strong* it is.
`SIDEWAYS` means there's no trend to credit — score 0 no matter what
quality claims. Otherwise:

| trend_quality | Score |
|---|---|
| STRONG | 20 |
| MODERATE | 10 |
| WEAK | 0 |

**Structure** reads `structure_quality` (`CLEAN` / `MIXED` / `CHOPPY` /
`UNCLEAR`):

| structure_quality | Score |
|---|---|
| CLEAN | 20 |
| MIXED | 10 |
| CHOPPY | 0 |

**Entry** reads `setup_quality` (`TEXTBOOK` / `ACCEPTABLE` / `MARGINAL` /
`NONE` / `UNCLEAR`) — the one field with five options instead of three,
so it gets a finer-grained scale:

| setup_quality | Score |
|---|---|
| TEXTBOOK | 20 |
| ACCEPTABLE | 15 |
| MARGINAL | 5 |
| NONE | 0 |

**Risk/Reward** is different on purpose — the only component that never
reads anything the agent said. It's computed from the user's own
entry/stop/target numbers:

```
LONG:  RR = (target − entry) / (entry − stop)
SHORT: RR = (entry − target) / (stop − entry)
```

| RR | Score |
|---|---|
| ≥ 2.0 | 20 |
| 1.0 – 1.99 | 10 |
| < 1.0 | 0 |

If entry, stop, target, or direction is missing, or the numbers are
incoherent for the stated direction (stop on the wrong side, target on
the wrong side, zero risk distance), the evaluator does not guess a
score — it returns a **failed evaluation** with a plain-English reason
instead. A silently invented RR would defeat the Milestone 9 guardrail,
which depends on this number being real.

**Timing/Context** reads `context_risk` (`LOW` / `MODERATE` / `ELEVATED`
/ `UNCLEAR`) — **note the direction is inverted** from every other
component: here, the *safest-sounding* word scores highest, because
`context_risk` describes risk, not quality.

| context_risk | Score |
|---|---|
| LOW | 20 |
| MODERATE | 10 |
| ELEVATED | 0 |

**`UNCLEAR` always scores 0** for whichever component it appears in —
the agent saying "I can't tell" is never worth partial credit, and it's
never treated as an error either; it's simply a 0 for that one component.
An **out-of-set value** (anything not in a field's documented list) is
different — the agent layer rejects the entire analysis before it ever
reaches the evaluator, and if one somehow did reach the evaluator anyway,
it returns a failed evaluation rather than guessing.

## Uncertainty caps

The agent's overall `uncertainty` (LOW/MEDIUM/HIGH) caps the four
**subjective** components — Trend, Structure, Entry, Timing/Context —
after each is scored, and before they're summed:

| Uncertainty | Cap per subjective component |
|---|---|
| LOW | 20 (no real cap — 20 is already the max a component can score) |
| MEDIUM | 14 |
| HIGH | 8 |

**Risk/Reward is exempt from this cap.** It's a fact about numbers the
user typed in, not a reading of an ambiguous chart — the agent being
unsure what it saw has no bearing on whether the trade's risk/reward
math checks out. So Risk/Reward can still score its full 0/10/20
regardless of uncertainty.

Caps are applied **per component, before summing** — never to the
finished total. The database's `CHECK` constraint on the `evaluations`
table requires `total_score` to exactly equal the sum of the five
component columns; adjusting the total after the fact would violate that
constraint (and would also just be a different, less honest number).

## Maximum achievable totals

Unchanged from v1 — the cap values (20/14/8) and the five-component
structure are the same; only *what* feeds each subjective component
changed.

| Uncertainty | Subjective ceiling | + Risk/Reward | = Total ceiling |
|---|---|---|---|
| LOW | 4 × 20 = 80 | + 20 | **100** |
| MEDIUM | 4 × 14 = 56 | + 20 | **76** |
| HIGH | 4 × 8 = 32 | + 20 | **52** |

A `HIGH`-uncertainty analysis can never score above 52, no matter how
good the categories look — which is exactly the point: the agent said it
wasn't sure, so the score can't pretend otherwise.

## Worked example

Agent analysis: `uncertainty = "MEDIUM"`, `trend_direction = "UP"`,
`trend_quality = "STRONG"`, `structure_quality = "CLEAN"`,
`setup_quality = "ACCEPTABLE"`, `context_risk = "LOW"`.
Trade params: LONG, entry 1.0950, stop 1.0900, target 1.1050.

```
risk distance   = 1.0950 - 1.0900 = 0.0050
reward distance = 1.1050 - 1.0950 = 0.0100
RR = 0.0100 / 0.0050 = 2.0   -> Risk/Reward = 20 (>= 2.0, not capped)

Trend (UP + STRONG)          = min(20, 14) = 14
Structure (CLEAN)            = min(20, 14) = 14
Entry (ACCEPTABLE)           = min(15, 14) = 14
Timing/Context (LOW risk)    = min(20, 14) = 14
Risk/Reward                  =              20
                                            ---
Total                                      = 76
```

(Note: Entry's raw score here is 15 for `ACCEPTABLE`, which the MEDIUM
cap of 14 still reduces by one point — the cap applies after the
category lookup, same as every other subjective component.)

## What v1 got wrong

v1 scored Trend, Structure, Entry, and Timing/Context from the agent's
*prose*: substantive text (≥15 characters, no "can't tell" phrasing)
scored 20, thin text scored 10, empty or negative-phrase text scored 0.
That measured **verbosity**, not the setup's actual quality — a mediocre
setup described in a long, confident-sounding paragraph scored exactly
the same as a genuinely excellent one described just as fluently. Only
Risk/Reward was ever genuinely scored, because it's real arithmetic; the
other 80 of 100 possible points were, in effect, measuring how much the
model chose to write. Guardrail thresholds (Milestone 9) built on top of
that score would have been gating on text length, not on anything about
the trade.

v2 fixes this by having the agent additionally emit five fixed-category
fields (`trend_direction`, `trend_quality`, `structure_quality`,
`setup_quality`, `context_risk`) — words chosen from a small, closed set,
validated and rejected outright if the model returns anything else. The
evaluator now reads *only* these categories for scoring; the prose fields
still exist for a human reviewer to read, but no longer influence the
score in any way. A two-sentence analysis and a two-paragraph analysis
with identical categories now score identically — confirmed by a test.
