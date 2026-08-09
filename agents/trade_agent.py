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

    # THE HARD BOUNDARY: any extra field carrying a number is treated as
    # an attempted score and rejects the whole response. An extra field
    # is also rejected purely by NAME if it looks like a smuggled
    # probability/confidence/percentage/likelihood/odds, regardless of
    # whether its value happens to be numeric yet -- "confidence": "high"
    # is exactly as much a violation as "confidence_score": 87, and this
    # is what makes that a code-enforced rule rather than a prompt request.
    extra_keys = set(data.keys()) - EXPECTED_FIELDS
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


class TradeAgent:
    def __init__(
        self,
        model: Optional[str] = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        client: Optional[object] = None,
    ):
        """
        model: Claude model id. Defaults to the CLAUDE_MODEL environment
        variable, then "claude-sonnet-5" if unset.

        max_tokens: hard cap on the API response's output tokens. Stored
        (not just passed inline to the API call) so a truncated response
        can report the exact limit it hit.

        client: an object with a `.messages.create(...)` method matching
        anthropic.Anthropic's interface. Exists so tests can inject a
        fake client without any real API key or network access. Normal
        callers leave this None.
        """
        self._model = model or os.getenv("CLAUDE_MODEL", "claude-sonnet-5")
        self._timeout_seconds = timeout_seconds
        self._max_tokens = max_tokens
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
