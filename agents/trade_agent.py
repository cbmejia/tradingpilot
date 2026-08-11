# TradePilot AI — the trading agent: wraps the Claude call.
#
# In plain terms: this takes a chart screenshot and a market data quote,
# shows both to Claude, and turns Claude's reply into a structured
# analysis -- free-form prose for a human to read, PLUS a small set of
# enumerated categories (e.g. is the trend UP/DOWN/SIDEWAYS) that the
# evaluation engine actually scores from. Neither is ever a number.
#
# THE HARD BOUNDARY: the agent produces WORDS -- prose or a fixed-set
# category label -- never numbers that could function as a score. It
# never outputs a total score, a component score, a percentage
# confidence, or a 0-100 rating -- the evaluation engine (Milestone 8)
# computes every number itself, from these qualitative fields, in plain
# deterministic Python. If Claude's response contains anything numeric
# where a score could hide -- an extra numeric field, a non-text value in
# a text field -- or any category value outside its documented allowed
# set, this rejects the ENTIRE response as FAILED rather than trying to
# salvage the "clean" parts or coercing a bad value to something valid. A
# model that ignored these rules once can't be trusted to have followed
# the others correctly in the same response.
#
# v2 note (post-Milestone-8 revision): the five category fields
# (trend_direction, trend_quality, structure_quality, setup_quality,
# context_risk) were added because the original rubric scored the four
# subjective components from prose length and keyword matching -- which
# scores verbosity, not setup quality. The prose fields
# (analysis_text/trend_assessment/structure_assessment/setup_assessment)
# stay for the human reviewer to read; they no longer drive any score.
#
# 7A Iteration 1 note: proposal_entry/proposal_stop/proposal_target are a
# narrow, explicit numeric carve-out -- the ONLY three field names this
# module ever accepts a real number from. That carve-out is enforced here,
# not just requested in the prompt: proposal_has_proposal must be a real
# JSON boolean (never 0/1/"true"/"yes"), the three numeric fields and
# proposal_direction must be null when proposal_has_proposal is false and
# fully populated (and coherent-looking types) when it's true -- any other
# combination rejects the whole response, same as every other malformed
# shape. A response carrying any field whose NAME looks like a smuggled
# probability/confidence/percentage/likelihood/odds is rejected outright,
# whatever its value type -- see SCORE_LIKE_KEYWORDS below. None of this
# widens what evals/trade_evaluator.py reads; see docs/handoff.md's "The
# 7A-specific invariant" for why the carve-out has to stay this narrow.
#
# 7A Iteration 2 note: TradeAgent.analyze_confirmation() is a SEPARATE
# Claude call from analyze() -- one image (a second, higher timeframe,
# for cross-timeframe context), a dedicated minimal prompt, and only three
# fields back (confirmation_visible_timeframe/confirmation_trend_direction/
# confirmation_trend_quality). Deliberately NOT folded into analyze() as a
# second image in the same call: Iteration 1's own live-run evidence found
# the agent's categorical output varies with what it's shown (see
# docs/iterations.md's Iteration 1 addendum -- proposed RR differed
# between a run with user-supplied levels and one without). Conditioning
# analyze()'s five SCORED categories on a second image would change what
# those categories mean, silently, breaking 6C's own comparability and
# removing Iteration 4's reproducibility baseline before it's even built.
# analyze() itself -- its prompt, its image count, its fields -- is
# completely untouched by this addition; see
# test_primary_call_payload_is_unchanged_by_the_existence_of_analyze_confirmation
# in tests/test_agent.py for the proof.

from __future__ import annotations

import base64
import json
import mimetypes
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

import anthropic
from dotenv import load_dotenv

from capture.base import CaptureResult, CaptureStatus
from tools.market_data import MarketDataStatus, MarketQuote

load_dotenv()

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
SYSTEM_PROMPT_PATH = PROMPTS_DIR / "system_prompt.md"
ANALYSIS_PROMPT_PATH = PROMPTS_DIR / "analysis_prompt.md"
# 7A Iteration 2 -- the confirmation call's own prompt files, entirely
# separate from the two above. analyze() never reads these; analyze_
# confirmation() never reads SYSTEM_PROMPT_PATH/ANALYSIS_PROMPT_PATH.
CONFIRMATION_SYSTEM_PROMPT_PATH = PROMPTS_DIR / "confirmation_system_prompt.md"
CONFIRMATION_ANALYSIS_PROMPT_PATH = PROMPTS_DIR / "confirmation_analysis_prompt.md"

DEFAULT_TIMEOUT_SECONDS = 60.0  # hard cap on the Claude API call -- no infinite wait

# Sized for the actual response shape: four prose fields (each bounded to
# a few sentences by prompts/analysis_prompt.md -- the categorical fields
# are what's scored, not prose length, so there's no reason for these to
# run long), five one-word categorical fields, uncertainty, and JSON
# structure/field-name overhead. A typical well-formed response is
# roughly 400-800 tokens; 2048 leaves a comfortable margin above that
# without inviting runaway generation. Raised from 1024 after a real LIVE
# run was truncated mid-string at ~1241 characters (stop_reason=
# "max_tokens") -- see docs/iterations.md's "fix: agent response
# truncation on live runs" entry for the diagnosis.
DEFAULT_MAX_TOKENS = 2048

# 7A Iteration 2 -- sized for the confirmation call's own tiny response
# shape: one short free-text field plus two one-word categories, no prose
# at all. Deliberately its own, much smaller, constant -- not reused from
# DEFAULT_MAX_TOKENS above, since that value was sized for a completely
# different (much larger) response shape.
CONFIRMATION_DEFAULT_MAX_TOKENS = 256

TEXT_FIELDS = (
    "analysis_text",
    "trend_assessment",
    "structure_assessment",
    "setup_assessment",
)
ALLOWED_UNCERTAINTY = {"LOW", "MEDIUM", "HIGH"}

# The categorical fields the evaluation engine actually scores from (see
# evals/trade_evaluator.py). Each maps to its own fixed, small allowed
# set -- UNCLEAR is always one of the options, on purpose, so the agent
# always has a way to say "I can't tell" for that specific category
# rather than guessing.
CATEGORICAL_FIELDS = {
    "trend_direction": {"UP", "DOWN", "SIDEWAYS", "UNCLEAR"},
    "trend_quality": {"STRONG", "MODERATE", "WEAK", "UNCLEAR"},
    "structure_quality": {"CLEAN", "MIXED", "CHOPPY", "UNCLEAR"},
    "setup_quality": {"TEXTBOOK", "ACCEPTABLE", "MARGINAL", "NONE", "UNCLEAR"},
    "context_risk": {"LOW", "MODERATE", "ELEVATED", "UNCLEAR"},
}

# 7A Iteration 1 -- the agent's proposed trade levels. proposal_has_proposal
# is the only field that decides whether the other four are expected to be
# populated or null; see _parse_response()'s "proposal shape" section for
# the exact both-directions rejection this enables (a malformed response,
# never coerced into whichever state looks closest).
PROPOSAL_HAS_PROPOSAL_FIELD = "proposal_has_proposal"
PROPOSAL_DIRECTION_FIELD = "proposal_direction"
PROPOSAL_NUMERIC_FIELDS = ("proposal_entry", "proposal_stop", "proposal_target")
ALLOWED_PROPOSAL_DIRECTIONS = {"LONG", "SHORT"}
PROPOSAL_FIELDS = {PROPOSAL_HAS_PROPOSAL_FIELD, PROPOSAL_DIRECTION_FIELD} | set(PROPOSAL_NUMERIC_FIELDS)

# Any EXTRA field (not one of the fields this module already expects)
# whose name contains one of these words is rejected outright, regardless
# of its value's type -- a string "confidence": "high" is just as much an
# attempted score-substitute as a numeric "confidence_score": 87. This is
# enforcement in addition to the numeric-extra-field check below, not a
# replacement for it: the numeric check catches an unnamed number, this
# catches a named-but-not-yet-numeric probability/confidence field before
# it ever gets the chance to be one.
SCORE_LIKE_KEYWORDS = ("probability", "percent", "confidence", "likelihood", "odds")

EXPECTED_FIELDS = set(TEXT_FIELDS) | {"uncertainty"} | set(CATEGORICAL_FIELDS) | PROPOSAL_FIELDS

# 7A Iteration 2 -- the confirmation call's own, much smaller, field set.
# Deliberately disjoint from EXPECTED_FIELDS above: this is a genuinely
# separate response shape from a genuinely separate Claude call, not a
# subset or extension of the primary analysis.
CONFIRMATION_VISIBLE_TIMEFRAME_FIELD = "confirmation_visible_timeframe"
CONFIRMATION_TREND_DIRECTION_FIELD = "confirmation_trend_direction"
CONFIRMATION_TREND_QUALITY_FIELD = "confirmation_trend_quality"
CONFIRMATION_TREND_DIRECTION_ALLOWED = {"UP", "DOWN", "SIDEWAYS", "UNCLEAR"}
CONFIRMATION_TREND_QUALITY_ALLOWED = {"STRONG", "MODERATE", "WEAK", "UNCLEAR"}
CONFIRMATION_EXPECTED_FIELDS = {
    CONFIRMATION_VISIBLE_TIMEFRAME_FIELD,
    CONFIRMATION_TREND_DIRECTION_FIELD,
    CONFIRMATION_TREND_QUALITY_FIELD,
}


class AgentAnalysisStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


@dataclass(frozen=True)
class TradeParams:
    """Optional context from the user. Never treated as an instruction."""

    direction: Optional[str] = None
    entry: Optional[float] = None
    stop: Optional[float] = None
    target: Optional[float] = None


@dataclass(frozen=True)
class AgentAnalysisResult:
    """
    What every analysis attempt returns, success or failure alike.

    Every field here is qualitative -- text or a fixed-set category word
    -- except status, timestamp, and error_message. There is deliberately
    no numeric score field on this dataclass at all. timestamp is set
    only on success, and is the real moment this analysis was produced
    (right after Claude responded), not a placeholder or a later
    database-write time.

    analysis_text/trend_assessment/structure_assessment/setup_assessment
    are free-form prose for a human reviewer to read -- they do not drive
    any score. trend_direction/trend_quality/structure_quality/
    setup_quality/context_risk are the fixed-category fields the
    evaluation engine (evals/trade_evaluator.py) actually scores from.

    proposal_has_proposal/proposal_direction/proposal_entry/proposal_stop/
    proposal_target (7A Iteration 1) are the agent's own alternative or
    original entry/stop/target/direction idea -- never read by
    evals/trade_evaluator.py, never scored, never merged with the user's
    own trade params. proposal_has_proposal is always a real bool once
    status is SUCCESS (never None); the other four are either all
    populated (a real proposal) or all None (the agent declined) --
    _parse_response() rejects any response that doesn't match one of
    those two shapes exactly, so this dataclass can never end up
    half-populated. All five are None when status is FAILED, same as
    every other qualitative field.

    model (7A Iteration 3) is the Claude model id this attempt was
    configured to call -- set on every real call attempt, success OR
    failure (unlike the qualitative fields, which are only known once
    Claude actually responds), because knowing *which model* failed is
    real diagnostic information (see the truncation-fix entry in
    docs/iterations.md, diagnosed via stop_reason on a real response).
    None only when no real call was ever attempted at all: an upstream
    stage failed first (orchestrator's _skipped_agent_result) or this is
    a synthetic testing result (orchestrator's _forced_agent_result) --
    never a guess standing in for "we don't know."
    """

    status: AgentAnalysisStatus
    analysis_text: Optional[str]
    trend_assessment: Optional[str]
    structure_assessment: Optional[str]
    setup_assessment: Optional[str]
    uncertainty: Optional[str]  # "LOW" | "MEDIUM" | "HIGH"
    trend_direction: Optional[str]  # "UP" | "DOWN" | "SIDEWAYS" | "UNCLEAR"
    trend_quality: Optional[str]  # "STRONG" | "MODERATE" | "WEAK" | "UNCLEAR"
    structure_quality: Optional[str]  # "CLEAN" | "MIXED" | "CHOPPY" | "UNCLEAR"
    setup_quality: Optional[str]  # "TEXTBOOK" | "ACCEPTABLE" | "MARGINAL" | "NONE" | "UNCLEAR"
    context_risk: Optional[str]  # "LOW" | "MODERATE" | "ELEVATED" | "UNCLEAR"
    proposal_has_proposal: Optional[bool]  # None only when status is FAILED
    proposal_direction: Optional[str]  # "LONG" | "SHORT", or None
    proposal_entry: Optional[float]
    proposal_stop: Optional[float]
    proposal_target: Optional[float]
    model: Optional[str]  # 7A Iteration 3 -- the Claude model id, see docstring above
    timestamp: Optional[datetime]
    error_message: Optional[str] = None


class ConfirmationAnalysisStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ConfirmationAnalysisResult:
    """
    What every confirmation-call attempt returns, success or failure
    alike (7A Iteration 2). Deliberately not a variant of
    AgentAnalysisResult -- it's a genuinely different, much smaller
    response shape from a genuinely separate Claude call.

    visible_timeframe is the model's own transcription of whatever
    timeframe label it actually saw on the chart -- backend/orchestrator.py
    (not this module) checks it against the timeframe that was actually
    requested, since this module has no way to know that. trend_direction/
    trend_quality use the identical allowed sets as AgentAnalysisResult's
    own trend_direction/trend_quality, but are never read by
    evals/trade_evaluator.py -- only by the CROSS_TIMEFRAME_AGREEMENT
    guardrail, which backend/orchestrator.py derives deterministically
    from these two fields; the agent never states "agreement" itself.

    model (7A Iteration 3): same meaning and same None-only-when-no-real-
    call-was-attempted rule as AgentAnalysisResult.model above.
    """

    status: ConfirmationAnalysisStatus
    visible_timeframe: Optional[str]
    trend_direction: Optional[str]  # "UP" | "DOWN" | "SIDEWAYS" | "UNCLEAR"
    trend_quality: Optional[str]  # "STRONG" | "MODERATE" | "WEAK" | "UNCLEAR"
    model: Optional[str]  # 7A Iteration 3 -- the Claude model id
    timestamp: Optional[datetime]
    error_message: Optional[str] = None


def _load_image_as_base64(path: str) -> tuple[str, str]:
    file_path = Path(path)
    data = file_path.read_bytes()
    media_type = mimetypes.guess_type(file_path.name)[0] or "image/png"
    return base64.b64encode(data).decode("ascii"), media_type


def _format_param(value: Optional[object]) -> str:
    return "not provided" if value is None else str(value)


def _render_analysis_prompt(
    template: str,
    capture_result: CaptureResult,
    market_data_result: MarketQuote,
    trade_params: TradeParams,
) -> str:
    quote_timestamp = (
        market_data_result.timestamp.isoformat() if market_data_result.timestamp else "unknown"
    )
    return template.format(
        symbol=market_data_result.symbol,
        timeframe=capture_result.timeframe,
        price=market_data_result.price,
        quote_timestamp=quote_timestamp,
        source=market_data_result.source,
        direction=_format_param(trade_params.direction),
        entry=_format_param(trade_params.entry),
        stop=_format_param(trade_params.stop),
        target=_format_param(trade_params.target),
    )


def _extract_text(response) -> str:
    parts = []
    for block in getattr(response, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def _strip_markdown_fence(raw_text: str) -> str:
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]  # drop the opening ``` or ```json line
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _reject_suspicious_extra_fields(data: dict, expected_fields: set[str]) -> None:
    """
    THE HARD BOUNDARY, shared by every response parser in this module
    (_parse_response for the primary call, _parse_confirmation_response
    for 7A Iteration 2's confirmation call): any extra field (not in
    expected_fields) carrying a number is treated as an attempted score
    and rejects the whole response. An extra field is also rejected
    purely by NAME if it looks like a smuggled probability/confidence/
    percentage/likelihood/odds, regardless of whether its value happens
    to be numeric yet -- "confidence": "high" is exactly as much a
    violation as "confidence_score": 87, and this is what makes that a
    code-enforced rule rather than a prompt request. Factored out into
    one function specifically so this security-critical check can never
    drift between the two response shapes -- both call sites get exactly
    the same rule, always.
    """
    extra_keys = set(data.keys()) - expected_fields
    numeric_extras = [
        key
        for key in extra_keys
        if isinstance(data[key], (int, float)) and not isinstance(data[key], bool)
    ]
    score_like_extras = [
        key for key in extra_keys if any(keyword in key.lower() for keyword in SCORE_LIKE_KEYWORDS)
    ]
    suspicious_extras = sorted(set(numeric_extras) | set(score_like_extras))
    if suspicious_extras:
        raise ValueError(
            f"response included numeric field(s) or field(s) named like a smuggled score, "
            f"rating, probability, or confidence value: {suspicious_extras} -- the agent "
            f"never accepts a score, rating, or confidence number (or word) from the model, "
            f"under any field name"
        )


def _parse_response(raw_text: str) -> dict:
    """
    Parses and validates Claude's reply against the expected qualitative
    shape. Raises ValueError for anything malformed OR anything numeric
    that could function as a score -- both are treated the same way by
    the caller: the whole response is rejected, not partially trusted.
    """
    text = _strip_markdown_fence(raw_text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"response was not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"response JSON was a {type(data).__name__}, not an object")

    missing = EXPECTED_FIELDS - data.keys()
    if missing:
        raise ValueError(f"response is missing required field(s): {sorted(missing)}")

    _reject_suspicious_extra_fields(data, EXPECTED_FIELDS)

    text_fields: dict[str, str] = {}
    for key in TEXT_FIELDS:
        value = data[key]
        if not isinstance(value, str):
            raise ValueError(f"'{key}' must be text, got {type(value).__name__}")
        text_fields[key] = value.strip()

    uncertainty_raw = data["uncertainty"]
    if not isinstance(uncertainty_raw, str):
        raise ValueError(
            f"'uncertainty' must be one of {sorted(ALLOWED_UNCERTAINTY)}, "
            f"got a {type(uncertainty_raw).__name__} instead of text"
        )
    uncertainty = uncertainty_raw.strip().upper()
    if uncertainty not in ALLOWED_UNCERTAINTY:
        raise ValueError(
            f"'uncertainty' must be one of {sorted(ALLOWED_UNCERTAINTY)}, got {uncertainty_raw!r}"
        )

    # The category fields the evaluation engine scores from. A value
    # outside the documented allowed set is rejected outright -- never
    # coerced to something valid (e.g. an unrecognized word is NOT
    # silently mapped to UNCLEAR; that would be guessing on the model's
    # behalf, which is exactly what this project avoids everywhere else).
    categorical_fields: dict[str, str] = {}
    for key, allowed_values in CATEGORICAL_FIELDS.items():
        value = data[key]
        if not isinstance(value, str):
            raise ValueError(f"'{key}' must be text, got {type(value).__name__}")
        normalized = value.strip().upper()
        if normalized not in allowed_values:
            raise ValueError(f"'{key}' must be one of {sorted(allowed_values)}, got {value!r}")
        categorical_fields[key] = normalized

    # --- 7A Iteration 1: the proposal shape ---
    #
    # proposal_has_proposal must be a real JSON boolean -- isinstance(x,
    # bool) rather than a truthiness check, because Python's bool is a
    # subclass of int (isinstance(1, bool) is False, but a truthiness
    # check would treat 1 the same as True). This is what makes 0, 1,
    # "true", and "yes" all rejected rather than silently accepted as
    # boolean-ish.
    has_proposal_raw = data[PROPOSAL_HAS_PROPOSAL_FIELD]
    if not isinstance(has_proposal_raw, bool):
        raise ValueError(
            f"'{PROPOSAL_HAS_PROPOSAL_FIELD}' must be a JSON boolean (true or false), got "
            f"a {type(has_proposal_raw).__name__}: {has_proposal_raw!r}"
        )

    direction_raw = data[PROPOSAL_DIRECTION_FIELD]
    numeric_raw = {key: data[key] for key in PROPOSAL_NUMERIC_FIELDS}

    if has_proposal_raw:
        # A real proposal: direction and all three numeric fields must be
        # present and correctly typed. Never coerced -- a null level, a
        # numeric-looking string, or an out-of-set direction here rejects
        # the whole response, the same "reject, don't guess" rule every
        # other field in this function follows.
        if not isinstance(direction_raw, str):
            raise ValueError(
                f"'{PROPOSAL_DIRECTION_FIELD}' must be text when {PROPOSAL_HAS_PROPOSAL_FIELD} "
                f"is true, got {type(direction_raw).__name__}"
            )
        direction_normalized = direction_raw.strip().upper()
        if direction_normalized not in ALLOWED_PROPOSAL_DIRECTIONS:
            raise ValueError(
                f"'{PROPOSAL_DIRECTION_FIELD}' must be one of "
                f"{sorted(ALLOWED_PROPOSAL_DIRECTIONS)}, got {direction_raw!r}"
            )
        proposal_numeric: dict[str, float] = {}
        for key, value in numeric_raw.items():
            if value is None:
                raise ValueError(
                    f"'{key}' must be a number when {PROPOSAL_HAS_PROPOSAL_FIELD} is true, "
                    f"got null"
                )
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(
                    f"'{key}' must be a number when {PROPOSAL_HAS_PROPOSAL_FIELD} is true, "
                    f"got {type(value).__name__}"
                )
            proposal_numeric[key] = float(value)
        proposal_fields = {
            "proposal_has_proposal": True,
            "proposal_direction": direction_normalized,
            "proposal_entry": proposal_numeric["proposal_entry"],
            "proposal_stop": proposal_numeric["proposal_stop"],
            "proposal_target": proposal_numeric["proposal_target"],
        }
    else:
        # A decline: this is a real, valid answer (not an error, and not
        # the same as omitting the fields) -- but direction and all three
        # numeric fields must be null. A response that says "no proposal"
        # while still carrying levels is malformed, not a proposal in
        # disguise -- rejected outright, never silently trusted as either
        # state.
        if direction_raw is not None:
            raise ValueError(
                f"'{PROPOSAL_DIRECTION_FIELD}' must be null when "
                f"{PROPOSAL_HAS_PROPOSAL_FIELD} is false, got {direction_raw!r}"
            )
        for key, value in numeric_raw.items():
            if value is not None:
                raise ValueError(
                    f"'{key}' must be null when {PROPOSAL_HAS_PROPOSAL_FIELD} is false, "
                    f"got {value!r}"
                )
        proposal_fields = {
            "proposal_has_proposal": False,
            "proposal_direction": None,
            "proposal_entry": None,
            "proposal_stop": None,
            "proposal_target": None,
        }

    return {**text_fields, "uncertainty": uncertainty, **categorical_fields, **proposal_fields}


def _parse_confirmation_response(raw_text: str) -> dict:
    """
    7A Iteration 2. Parses and validates the confirmation call's minimal
    reply -- the same hard-boundary rules as _parse_response() (reject,
    never coerce; no numbers anywhere; no smuggled score/probability
    field, via the shared _reject_suspicious_extra_fields()), scoped to
    the three fields this call ever asks for.

    confirmation_visible_timeframe is free text -- the model transcribes
    whatever timeframe label it actually sees on the chart. This function
    only validates that it's present and non-empty text; it has no way to
    know what timeframe was actually requested, so checking it against
    that is backend/orchestrator.py's job, not this one's.
    """
    text = _strip_markdown_fence(raw_text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"response was not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"response JSON was a {type(data).__name__}, not an object")

    missing = CONFIRMATION_EXPECTED_FIELDS - data.keys()
    if missing:
        raise ValueError(f"response is missing required field(s): {sorted(missing)}")

    _reject_suspicious_extra_fields(data, CONFIRMATION_EXPECTED_FIELDS)

    visible_timeframe_raw = data[CONFIRMATION_VISIBLE_TIMEFRAME_FIELD]
    if not isinstance(visible_timeframe_raw, str):
        raise ValueError(
            f"'{CONFIRMATION_VISIBLE_TIMEFRAME_FIELD}' must be text, got "
            f"{type(visible_timeframe_raw).__name__}"
        )
    visible_timeframe = visible_timeframe_raw.strip()
    if not visible_timeframe:
        raise ValueError(f"'{CONFIRMATION_VISIBLE_TIMEFRAME_FIELD}' must not be empty")

    direction_raw = data[CONFIRMATION_TREND_DIRECTION_FIELD]
    if not isinstance(direction_raw, str):
        raise ValueError(
            f"'{CONFIRMATION_TREND_DIRECTION_FIELD}' must be text, got {type(direction_raw).__name__}"
        )
    direction = direction_raw.strip().upper()
    if direction not in CONFIRMATION_TREND_DIRECTION_ALLOWED:
        raise ValueError(
            f"'{CONFIRMATION_TREND_DIRECTION_FIELD}' must be one of "
            f"{sorted(CONFIRMATION_TREND_DIRECTION_ALLOWED)}, got {direction_raw!r}"
        )

    quality_raw = data[CONFIRMATION_TREND_QUALITY_FIELD]
    if not isinstance(quality_raw, str):
        raise ValueError(
            f"'{CONFIRMATION_TREND_QUALITY_FIELD}' must be text, got {type(quality_raw).__name__}"
        )
    quality = quality_raw.strip().upper()
    if quality not in CONFIRMATION_TREND_QUALITY_ALLOWED:
        raise ValueError(
            f"'{CONFIRMATION_TREND_QUALITY_FIELD}' must be one of "
            f"{sorted(CONFIRMATION_TREND_QUALITY_ALLOWED)}, got {quality_raw!r}"
        )

    return {
        CONFIRMATION_VISIBLE_TIMEFRAME_FIELD: visible_timeframe,
        CONFIRMATION_TREND_DIRECTION_FIELD: direction,
        CONFIRMATION_TREND_QUALITY_FIELD: quality,
    }


class TradeAgent:
    def __init__(
        self,
        model: Optional[str] = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        confirmation_max_tokens: int = CONFIRMATION_DEFAULT_MAX_TOKENS,
        client: Optional[object] = None,
    ):
        """
        model: Claude model id. Defaults to the CLAUDE_MODEL environment
        variable, then "claude-sonnet-5" if unset. Shared by analyze() and
        analyze_confirmation() -- both calls use the same configured model.

        max_tokens: hard cap on analyze()'s own API response's output
        tokens. Stored (not just passed inline to the API call) so a
        truncated response can report the exact limit it hit.

        confirmation_max_tokens (7A Iteration 2): the same idea, sized for
        analyze_confirmation()'s own much smaller response shape -- a
        separate value on purpose, since the two calls have genuinely
        different response sizes.

        client: an object with a `.messages.create(...)` method matching
        anthropic.Anthropic's interface. Exists so tests can inject a
        fake client without any real API key or network access. Normal
        callers leave this None. Shared by both calls -- one TradeAgent
        instance makes both, reusing the same underlying credentials.
        """
        self._model = model or os.getenv("CLAUDE_MODEL", "claude-sonnet-5")
        self._timeout_seconds = timeout_seconds
        self._max_tokens = max_tokens
        self._confirmation_max_tokens = confirmation_max_tokens
        self._client = client

    def analyze(
        self,
        capture_result: CaptureResult,
        market_data_result: MarketQuote,
        trade_params: Optional[TradeParams] = None,
    ) -> AgentAnalysisResult:
        trade_params = trade_params or TradeParams()

        # 1. Input validation -- before any API call, so a bad capture or
        # a bad market data fetch never costs a Claude request, and the
        # agent never reasons about data that doesn't actually exist.
        if capture_result.status != CaptureStatus.SUCCESS:
            detail = f": {capture_result.error_message}" if capture_result.error_message else "."
            return self._failed(f"No chart to analyze -- capture status is {capture_result.status.value}{detail}")

        if market_data_result.status != MarketDataStatus.SUCCESS:
            detail = f": {market_data_result.error_message}" if market_data_result.error_message else "."
            return self._failed(
                f"No market data to analyze -- market data status is {market_data_result.status.value}{detail}"
            )

        try:
            image_b64, media_type = _load_image_as_base64(capture_result.screenshot_path)
        except OSError as exc:
            return self._failed(f"Could not read the screenshot file: {exc}")

        try:
            system_prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
            analysis_template = ANALYSIS_PROMPT_PATH.read_text(encoding="utf-8")
        except OSError as exc:
            return self._failed(f"Could not read the prompt files: {exc}")

        user_prompt = _render_analysis_prompt(
            analysis_template, capture_result, market_data_result, trade_params
        )

        if self._client is not None:
            client = self._client
        else:
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                return self._failed(
                    "ANTHROPIC_API_KEY is not set in .env. Get one at "
                    "https://console.anthropic.com/settings/keys."
                )
            client = anthropic.Anthropic(api_key=api_key)

        try:
            response = client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system_prompt,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": image_b64,
                                },
                            },
                            {"type": "text", "text": user_prompt},
                        ],
                    }
                ],
                timeout=self._timeout_seconds,
            )
        except anthropic.APITimeoutError as exc:
            return self._failed(
                f"Claude API request timed out after {self._timeout_seconds}s: {exc}"
            )
        except anthropic.APIError as exc:
            # Covers rate limits and every other API-side error -- the
            # real message is preserved, never replaced with a guess.
            return self._failed(f"Claude API request failed: {exc}")

        raw_text = _extract_text(response)

        # Checked BEFORE attempting to parse, and reported as its own
        # distinct failure -- a response cut off mid-write by the
        # max_tokens limit is not the same problem as a genuinely
        # malformed response, and treating the two identically ("response
        # was not valid JSON") sends anyone debugging a real truncation
        # looking at the wrong thing, exactly as it did for a real LIVE
        # run before this check existed.
        if getattr(response, "stop_reason", None) == "max_tokens":
            return self._failed(
                f"Claude's response was truncated: generation stopped because it hit "
                f"the max_tokens limit ({self._max_tokens}) before finishing "
                f"(stop_reason='max_tokens'), not because of a parsing problem. The "
                f"response was cut off after {len(raw_text)} characters. Raise "
                f"max_tokens (agents/trade_agent.py's DEFAULT_MAX_TOKENS) if this "
                f"keeps happening."
            )

        try:
            parsed = _parse_response(raw_text)
        except ValueError as exc:
            return self._failed(f"Claude's response could not be used: {exc}")

        return AgentAnalysisResult(
            status=AgentAnalysisStatus.SUCCESS,
            analysis_text=parsed["analysis_text"],
            trend_assessment=parsed["trend_assessment"],
            structure_assessment=parsed["structure_assessment"],
            setup_assessment=parsed["setup_assessment"],
            uncertainty=parsed["uncertainty"],
            trend_direction=parsed["trend_direction"],
            trend_quality=parsed["trend_quality"],
            structure_quality=parsed["structure_quality"],
            setup_quality=parsed["setup_quality"],
            context_risk=parsed["context_risk"],
            proposal_has_proposal=parsed["proposal_has_proposal"],
            proposal_direction=parsed["proposal_direction"],
            proposal_entry=parsed["proposal_entry"],
            proposal_stop=parsed["proposal_stop"],
            proposal_target=parsed["proposal_target"],
            model=self._model,
            timestamp=datetime.now(timezone.utc),
            error_message=None,
        )

    def _failed(self, message: str) -> AgentAnalysisResult:
        return AgentAnalysisResult(
            status=AgentAnalysisStatus.FAILED,
            analysis_text=None,
            trend_assessment=None,
            structure_assessment=None,
            setup_assessment=None,
            uncertainty=None,
            trend_direction=None,
            trend_quality=None,
            structure_quality=None,
            setup_quality=None,
            context_risk=None,
            proposal_has_proposal=None,
            proposal_direction=None,
            proposal_entry=None,
            proposal_stop=None,
            proposal_target=None,
            # self._model is known even on failure (it's resolved in
            # __init__, before any call is attempted) -- recorded here on
            # purpose, see the dataclass docstring.
            model=self._model,
            timestamp=None,
            error_message=message,
        )

    def analyze_confirmation(self, capture_result: CaptureResult) -> ConfirmationAnalysisResult:
        """
        7A Iteration 2. A SEPARATE Claude call from analyze() -- see the
        module docstring's Iteration 2 note for why this is a second call
        rather than a second image folded into analyze()'s own call.
        Never touches analyze()'s prompt files, image, or fields.

        If this call fails for any reason (bad capture, API error,
        truncation, malformed response), it fails closed and returns a
        FAILED ConfirmationAnalysisResult -- it never retries into
        analyze(), and analyze() is never called as a fallback.
        """
        if capture_result.status != CaptureStatus.SUCCESS:
            detail = f": {capture_result.error_message}" if capture_result.error_message else "."
            return self._failed_confirmation(
                f"No confirmation chart to analyze -- capture status is "
                f"{capture_result.status.value}{detail}"
            )

        try:
            image_b64, media_type = _load_image_as_base64(capture_result.screenshot_path)
        except OSError as exc:
            return self._failed_confirmation(f"Could not read the confirmation screenshot file: {exc}")

        try:
            system_prompt = CONFIRMATION_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
            analysis_template = CONFIRMATION_ANALYSIS_PROMPT_PATH.read_text(encoding="utf-8")
        except OSError as exc:
            return self._failed_confirmation(f"Could not read the confirmation prompt files: {exc}")

        user_prompt = analysis_template.format(
            symbol=capture_result.symbol, timeframe=capture_result.timeframe
        )

        if self._client is not None:
            client = self._client
        else:
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                return self._failed_confirmation(
                    "ANTHROPIC_API_KEY is not set in .env. Get one at "
                    "https://console.anthropic.com/settings/keys."
                )
            client = anthropic.Anthropic(api_key=api_key)

        try:
            response = client.messages.create(
                model=self._model,
                max_tokens=self._confirmation_max_tokens,
                system=system_prompt,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": image_b64,
                                },
                            },
                            {"type": "text", "text": user_prompt},
                        ],
                    }
                ],
                timeout=self._timeout_seconds,
            )
        except anthropic.APITimeoutError as exc:
            return self._failed_confirmation(
                f"Confirmation Claude API request timed out after {self._timeout_seconds}s: {exc}"
            )
        except anthropic.APIError as exc:
            return self._failed_confirmation(f"Confirmation Claude API request failed: {exc}")

        raw_text = _extract_text(response)

        if getattr(response, "stop_reason", None) == "max_tokens":
            return self._failed_confirmation(
                f"Confirmation response was truncated: generation stopped because it hit "
                f"the max_tokens limit ({self._confirmation_max_tokens}) before finishing "
                f"(stop_reason='max_tokens')."
            )

        try:
            parsed = _parse_confirmation_response(raw_text)
        except ValueError as exc:
            return self._failed_confirmation(f"Confirmation response could not be used: {exc}")

        return ConfirmationAnalysisResult(
            status=ConfirmationAnalysisStatus.SUCCESS,
            visible_timeframe=parsed[CONFIRMATION_VISIBLE_TIMEFRAME_FIELD],
            trend_direction=parsed[CONFIRMATION_TREND_DIRECTION_FIELD],
            trend_quality=parsed[CONFIRMATION_TREND_QUALITY_FIELD],
            model=self._model,
            timestamp=datetime.now(timezone.utc),
            error_message=None,
        )

    def _failed_confirmation(self, message: str) -> ConfirmationAnalysisResult:
        return ConfirmationAnalysisResult(
            status=ConfirmationAnalysisStatus.FAILED,
            visible_timeframe=None,
            trend_direction=None,
            trend_quality=None,
            # Same reasoning as _failed() above: known even on failure.
            model=self._model,
            timestamp=None,
            error_message=message,
        )


def analyze(
    capture_result: CaptureResult,
    market_data_result: MarketQuote,
    trade_params: Optional[TradeParams] = None,
    model: Optional[str] = None,
) -> AgentAnalysisResult:
    """Convenience wrapper around TradeAgent(model).analyze(...)."""
    return TradeAgent(model=model).analyze(capture_result, market_data_result, trade_params)
