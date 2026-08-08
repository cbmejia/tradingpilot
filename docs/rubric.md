# Evaluation rubric

This is the exact, deterministic rubric `evals/trade_evaluator.py`
implements. No AI is involved in scoring — every rule below is plain
Python you can read top to bottom.

## The five components (20 points each, 100 total)

| Component | Reads | 20 points | 10 points | 0 points |
|---|---|---|---|---|
| **Trend** | Agent's `trend_assessment` | Substantive (≥15 characters) and contains no "can't tell" language | Non-empty but shorter than 15 characters | Empty, or contains a negative/absence phrase (e.g. "unclear", "no clear", "ambiguous") |
| **Structure** | Agent's `structure_assessment` | Same rule as Trend | Same rule as Trend | Same rule as Trend |
| **Entry** | Agent's `setup_assessment` | Same rule as Trend | Same rule as Trend | Same rule as Trend |
| **Risk/Reward** | User's entry/stop/target — **arithmetic, not the agent's words** | RR ≥ 2.0 (reward at least double the risk) | 1.0 ≤ RR < 2.0 (reward at least equals risk) | RR < 1.0 (risking more than the potential reward) |
| **Timing/Context** | Agent's `analysis_text` | Same rule as Trend | Same rule as Trend | Same rule as Trend |

**Trend, Structure, Entry, and Timing/Context** are scored by the exact
same rule, applied to four different fields: does the text say something
substantive, something thin, or does it explicitly admit it couldn't
tell? The full list of "negative/absence" phrases that trigger 0 points
lives in `NEGATIVE_PHRASES` in `evals/trade_evaluator.py` — things like
"no clear", "not readable", "insufficient information", "ambiguous",
"can't determine". The 15-character substantive/thin threshold is
`MIN_SUBSTANTIVE_LENGTH` in the same file.

**Risk/Reward is different on purpose.** It never reads anything the
agent said — it's computed from the user's own entry/stop/target numbers:

```
LONG:  RR = (target − entry) / (entry − stop)
SHORT: RR = (entry − target) / (stop − entry)
```

If entry, stop, target, or direction is missing, or the numbers are
incoherent for the stated direction (stop on the wrong side, target on
the wrong side, zero risk distance), the evaluator does not guess a
score — it returns a **failed evaluation** with a plain-English reason
instead. A silently invented RR would defeat the Milestone 9 freshness/
risk guardrail, which depends on this number being real.

## Uncertainty caps

The agent's `uncertainty` (LOW/MEDIUM/HIGH) caps the four **subjective**
components — Trend, Structure, Entry, Timing/Context — after each is
scored 0/10/20, and before they're summed:

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

These are the ceilings a perfect analysis can reach at each uncertainty
level — worth knowing before choosing Milestone 9's guardrail thresholds:

| Uncertainty | Subjective ceiling | + Risk/Reward | = Total ceiling |
|---|---|---|---|
| LOW | 4 × 20 = 80 | + 20 | **100** |
| MEDIUM | 4 × 14 = 56 | + 20 | **76** |
| HIGH | 4 × 8 = 32 | + 20 | **52** |

A `HIGH`-uncertainty analysis can never score above 52, no matter how
good the chart looks to the agent — which is exactly the point: the
agent said it wasn't sure, so the score can't pretend otherwise.

## Worked example

Agent analysis: `uncertainty = "MEDIUM"`, all four text fields
substantive and non-negative (each would score 20 raw, capped to 14).
Trade params: LONG, entry 1.0950, stop 1.0900, target 1.1050.

```
risk distance  = 1.0950 - 1.0900 = 0.0050
reward distance = 1.1050 - 1.0950 = 0.0100
RR = 0.0100 / 0.0050 = 2.0   -> Risk/Reward = 20 (>= 2.0, not capped)

Trend            = min(20, 14) = 14
Structure        = min(20, 14) = 14
Entry            = min(20, 14) = 14
Timing/Context   = min(20, 14) = 14
Risk/Reward      =              20
                                ---
Total                          = 76
```
