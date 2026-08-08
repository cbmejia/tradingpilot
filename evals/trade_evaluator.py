# TradePilot AI — the evaluation engine: turns qualitative analysis into a
# deterministic rubric score.
#
# In plain terms: this is the ONLY place in the whole app that produces a
# number representing how good a setup looks. It reads the agent's fixed
# CATEGORY fields (never its prose, never a number from the agent -- there
# isn't one) and the user's trade parameters, and computes five component
# scores (0-100 total, 20 points each) using fixed, explicit, written-down
# rules. Nothing here calls an AI. Nothing here is random. Given the same
# inputs, this always produces the same output -- that's what makes a
# score in this app auditable.
#
# v2 note (this is a revision of the original Milestone 8 rubric): v1
# scored four of the five components from the agent's PROSE -- substantive
# text (>=15 chars, no "can't tell" phrases) scored 20. That rewarded
# verbosity, not setup quality: a poor setup described fluently scored
# full marks. v2 scores those same four components from the agent's
# ENUMERATED category fields instead (trend_direction/trend_quality/
# structure_quality/setup_quality/context_risk) -- fixed words from a
# small allowed set, never string length, never keyword matching on
# prose. The prose fields still exist on AgentAnalysisResult, for the
# human reviewer to read; nothing in this file reads them anymore.
#
# THE RUBRIC, in one paragraph: four components (Trend, Structure, Entry,
# Timing/Context) each read one or two of the agent's category fields and
# score them via a fixed lookup table -- see docs/rubric.md for the exact
# table. The fifth component, Risk/Reward, is computed ARITHMETICALLY
# from the user's entry/stop/target -- it never reads anything the agent
# said. The agent's uncertainty (LOW/MEDIUM/HIGH) then caps each of the
# four subjective components (not Risk/Reward) at 20/14/8 respectively,
# and total_score is always the sum of the five (already-capped)
# components -- the same formula the database's CHECK constraint enforces.

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from agents.trade_agent import AgentAnalysisResult, AgentAnalysisStatus, TradeParams

# --- Rubric constants -- change these here, and update docs/rubric.md too ---

RR_STRONG_THRESHOLD = 2.0  # reward is at least double the risk
RR_MARGINAL_THRESHOLD = 1.0  # reward at least equals risk

# Trend combines two category fields: direction is a gate (no real trend
# if SIDEWAYS or UNCLEAR), quality sets the score within a real trend.
TREND_QUALITY_SCORES = {"STRONG": 20, "MODERATE": 10, "WEAK": 0}

STRUCTURE_QUALITY_SCORES = {"CLEAN": 20, "MIXED": 10, "CHOPPY": 0}

SETUP_QUALITY_SCORES = {"TEXTBOOK": 20, "ACCEPTABLE": 15, "MARGINAL": 5, "NONE": 0}

# context_risk is inverted from the others: LOW risk is favorable (scores
# high), ELEVATED risk is unfavorable (scores low).
CONTEXT_RISK_SCORES = {"LOW": 20, "MODERATE": 10, "ELEVATED": 0}

# Uncertainty caps applied to the four SUBJECTIVE components only, after
# each is scored and before they're summed. LOW's cap of 20 is a no-op
# in practice (raw subjective scores never exceed 20 anyway) -- it's
# written as a real cap rather than a special "no cap" case so all three
# levels go through the exact same min(raw_score, cap) logic.
UNCERTAINTY_CAPS = {
    "LOW": 20,
    "MEDIUM": 14,
    "HIGH": 8,
}


class EvaluationStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


@dataclass(frozen=True)
class EvaluationResult:
    """
    What every evaluation attempt returns, success or failure alike.

    total_score is always trend_score + structure_score + entry_score +
    risk_reward_score + timing_context_score -- the exact formula the
    database's CHECK constraint (ck_evaluations_total_score_is_sum_of_
    components) enforces. There is no path, anywhere, that sets
    total_score independently.

    risk_reward_ratio is the raw computed number (e.g. 2.5), included for
    transparency and for the Milestone 9 guardrail (which needs the actual
    ratio, not just its 0/10/20 score band). It is not a database column;
    it never gets stored, only returned here.
    """

    status: EvaluationStatus
    trend_score: Optional[int]
    structure_score: Optional[int]
    entry_score: Optional[int]
    risk_reward_score: Optional[int]
    timing_context_score: Optional[int]
    total_score: Optional[int]
    risk_reward_ratio: Optional[float]
    error_message: Optional[str] = None


def _score_trend(trend_direction: Optional[str], trend_quality: Optional[str]) -> int:
    """
    Trend is the one component read from two category fields together:
    direction gates whether there's a trend worth scoring at all, quality
    sets the score within it.

    - SIDEWAYS direction, or either field UNCLEAR -> 0 (no directional
      trend to credit, or the agent couldn't tell).
    - UP or DOWN direction -> STRONG=20, MODERATE=10, WEAK=0.
    """
    if trend_direction is None or trend_quality is None:
        raise ValueError("trend_direction and trend_quality are both required")

    direction = trend_direction.strip().upper()
    quality = trend_quality.strip().upper()

    if direction not in ("UP", "DOWN", "SIDEWAYS", "UNCLEAR"):
        raise ValueError(f"unrecognized trend_direction: {trend_direction!r}")
    if quality not in ("STRONG", "MODERATE", "WEAK", "UNCLEAR"):
        raise ValueError(f"unrecognized trend_quality: {trend_quality!r}")

    if direction in ("SIDEWAYS", "UNCLEAR") or quality == "UNCLEAR":
        return 0

    return TREND_QUALITY_SCORES[quality]


def _score_from_map(value: Optional[str], score_map: dict, field_name: str) -> int:
    """
    Shared lookup for the three single-field categorical components
    (Structure/Entry/Timing-Context). UNCLEAR always scores 0. Any value
    outside score_map (and not UNCLEAR) is a hard error, not a guess.
    """
    if value is None:
        raise ValueError(f"{field_name} is required")

    normalized = value.strip().upper()
    if normalized == "UNCLEAR":
        return 0
    if normalized not in score_map:
        raise ValueError(f"unrecognized {field_name}: {value!r}")

    return score_map[normalized]


def _score_risk_reward(rr_ratio: float) -> int:
    """
    Deterministic 3-band score for the arithmetically-computed RR ratio.

    - 20 if RR >= 2.0 (reward at least double the risk -- strong)
    - 10 if 1.0 <= RR < 2.0 (reward at least equals risk -- marginal)
    - 0  if RR < 1.0 (risking more than the potential reward -- poor)
    """
    if rr_ratio >= RR_STRONG_THRESHOLD:
        return 20
    if rr_ratio >= RR_MARGINAL_THRESHOLD:
        return 10
    return 0


def _compute_risk_reward(
    direction: Optional[str],
    entry: Optional[float],
    stop: Optional[float],
    target: Optional[float],
) -> tuple[Optional[float], Optional[str]]:
    """
    Computes RR = reward distance / risk distance, honoring direction.

    Returns (ratio, None) on success, or (None, reason) if the inputs are
    missing or incoherent. Never returns a guessed ratio -- every failure
    path returns None for the ratio.
    """
    missing = [
        name
        for name, value in (
            ("direction", direction),
            ("entry", entry),
            ("stop", stop),
            ("target", target),
        )
        if value is None
    ]
    if missing:
        return None, f"missing trade parameter(s): {', '.join(missing)}"

    direction_normalized = str(direction).strip().lower()
    if direction_normalized not in ("long", "short"):
        return None, f"direction must be 'long' or 'short', got {direction!r}"

    if direction_normalized == "long":
        risk_distance = entry - stop
        reward_distance = target - entry
    else:  # short
        risk_distance = stop - entry
        reward_distance = entry - target

    if risk_distance == 0:
        return None, f"entry and stop are equal ({entry}) -- risk distance is zero"
    if risk_distance < 0:
        return None, (
            f"stop is on the wrong side of entry for a {direction_normalized} trade "
            f"(entry={entry}, stop={stop})"
        )
    if reward_distance <= 0:
        return None, (
            f"target is on the wrong side of entry (or equal to it) for a "
            f"{direction_normalized} trade (entry={entry}, target={target})"
        )

    return reward_distance / risk_distance, None


def _failed(message: str) -> EvaluationResult:
    return EvaluationResult(
        status=EvaluationStatus.FAILED,
        trend_score=None,
        structure_score=None,
        entry_score=None,
        risk_reward_score=None,
        timing_context_score=None,
        total_score=None,
        risk_reward_ratio=None,
        error_message=message,
    )


def evaluate(
    agent_analysis: AgentAnalysisResult,
    trade_params: Optional[TradeParams] = None,
) -> EvaluationResult:
    """
    Scores one agent analysis against the fixed rubric. Pure and
    deterministic: no AI call, no randomness, no clock-dependent
    behavior. Same inputs always produce the same EvaluationResult.
    """
    trade_params = trade_params or TradeParams()

    if agent_analysis.status != AgentAnalysisStatus.SUCCESS:
        detail = f": {agent_analysis.error_message}" if agent_analysis.error_message else "."
        return _failed(
            f"No agent analysis to evaluate -- analysis status is "
            f"{agent_analysis.status.value}{detail}"
        )

    rr_ratio, rr_error = _compute_risk_reward(
        trade_params.direction, trade_params.entry, trade_params.stop, trade_params.target
    )
    if rr_error is not None:
        return _failed(f"Cannot compute risk/reward: {rr_error}")

    try:
        trend_score_raw = _score_trend(agent_analysis.trend_direction, agent_analysis.trend_quality)
        structure_score_raw = _score_from_map(
            agent_analysis.structure_quality, STRUCTURE_QUALITY_SCORES, "structure_quality"
        )
        entry_score_raw = _score_from_map(
            agent_analysis.setup_quality, SETUP_QUALITY_SCORES, "setup_quality"
        )
        timing_context_score_raw = _score_from_map(
            agent_analysis.context_risk, CONTEXT_RISK_SCORES, "context_risk"
        )
    except ValueError as exc:
        return _failed(f"Cannot score agent analysis: {exc}")

    cap = UNCERTAINTY_CAPS[agent_analysis.uncertainty]

    trend_score = min(trend_score_raw, cap)
    structure_score = min(structure_score_raw, cap)
    entry_score = min(entry_score_raw, cap)
    timing_context_score = min(timing_context_score_raw, cap)

    # Risk/Reward is EXEMPT from the uncertainty cap -- it's a fact about
    # the numbers, not a reading of the chart, so the agent's uncertainty
    # about the chart has no bearing on it.
    risk_reward_score = _score_risk_reward(rr_ratio)

    total_score = (
        trend_score + structure_score + entry_score + risk_reward_score + timing_context_score
    )

    return EvaluationResult(
        status=EvaluationStatus.SUCCESS,
        trend_score=trend_score,
        structure_score=structure_score,
        entry_score=entry_score,
        risk_reward_score=risk_reward_score,
        timing_context_score=timing_context_score,
        total_score=total_score,
        risk_reward_ratio=rr_ratio,
        error_message=None,
    )
