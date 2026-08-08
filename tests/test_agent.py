# TradePilot AI — tests for the agent loop (Milestone 7).
#
# No test in this file makes a real API call. Every Claude interaction is
# a fake client object with a `.messages.create(...)` method configured
# by the test -- either returning a fake response or raising a real
# anthropic SDK exception (constructed directly, not over the network).

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import anthropic
import httpx

from agents.trade_agent import (
    AgentAnalysisStatus,
    TradeAgent,
    TradeParams,
    analyze,
)
from capture.base import CaptureMode, CaptureResult, CaptureStatus
from tools.market_data import MarketDataMode, MarketDataStatus, MarketQuote

DEMO_SCREENSHOT = "screenshots/demo/EURUSD_1h.png"


def _successful_capture(**overrides) -> CaptureResult:
    defaults = dict(
        mode=CaptureMode.DEMO,
        symbol="EURUSD",
        timeframe="1h",
        screenshot_path=DEMO_SCREENSHOT,
        captured_at=datetime.now(timezone.utc),
        status=CaptureStatus.SUCCESS,
        error_message=None,
    )
    defaults.update(overrides)
    return CaptureResult(**defaults)


def _successful_market_data(**overrides) -> MarketQuote:
    defaults = dict(
        mode=MarketDataMode.DEMO,
        symbol="EURUSD",
        price=1.0921,
        timestamp=datetime.now(timezone.utc),
        source="demo_fixture",
        status=MarketDataStatus.SUCCESS,
        error_message=None,
    )
    defaults.update(overrides)
    return MarketQuote(**defaults)


def _fake_client(response_text: str = None, side_effect: Exception = None) -> MagicMock:
    client = MagicMock()
    if side_effect is not None:
        client.messages.create.side_effect = side_effect
    else:
        client.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="text", text=response_text)]
        )
    return client


WELL_FORMED_RESPONSE = json.dumps(
    {
        "analysis_text": "Price has been grinding higher against a rising trendline.",
        "trend_assessment": "uptrend",
        "structure_assessment": "higher highs and higher lows",
        "setup_assessment": "pullback toward the trendline, not yet confirmed",
        "uncertainty": "MEDIUM",
    }
)


# ---------------------------------------------------------------------------
# Input validation -- never call the API on bad inputs
# ---------------------------------------------------------------------------


def test_failed_capture_returns_failed_analysis_and_never_calls_the_api():
    client = _fake_client(WELL_FORMED_RESPONSE)
    bad_capture = _successful_capture(
        status=CaptureStatus.FAILED,
        screenshot_path=None,
        captured_at=None,
        error_message="No demo fixture for EURUSD 1h",
    )

    result = TradeAgent(client=client).analyze(bad_capture, _successful_market_data())

    assert result.status == AgentAnalysisStatus.FAILED
    assert result.analysis_text is None
    assert result.uncertainty is None
    assert "No chart to analyze" in result.error_message
    client.messages.create.assert_not_called()


def test_failed_market_data_returns_failed_analysis_and_never_calls_the_api():
    client = _fake_client(WELL_FORMED_RESPONSE)
    bad_market_data = _successful_market_data(
        status=MarketDataStatus.FAILED,
        price=None,
        timestamp=None,
        error_message="MARKET_DATA_API_KEY is not set",
    )

    result = TradeAgent(client=client).analyze(_successful_capture(), bad_market_data)

    assert result.status == AgentAnalysisStatus.FAILED
    assert result.analysis_text is None
    assert "No market data to analyze" in result.error_message
    client.messages.create.assert_not_called()


# ---------------------------------------------------------------------------
# Well-formed responses map correctly
# ---------------------------------------------------------------------------


def test_well_formed_response_maps_into_analysis_fields():
    client = _fake_client(WELL_FORMED_RESPONSE)

    result = TradeAgent(client=client).analyze(_successful_capture(), _successful_market_data())

    assert result.status == AgentAnalysisStatus.SUCCESS
    assert result.error_message is None
    assert result.trend_assessment == "uptrend"
    assert result.structure_assessment == "higher highs and higher lows"
    assert "pullback" in result.setup_assessment
    assert result.uncertainty == "MEDIUM"
    assert "grinding higher" in result.analysis_text


def test_response_wrapped_in_markdown_fence_is_still_parsed():
    fenced = f"```json\n{WELL_FORMED_RESPONSE}\n```"
    client = _fake_client(fenced)

    result = TradeAgent(client=client).analyze(_successful_capture(), _successful_market_data())

    assert result.status == AgentAnalysisStatus.SUCCESS
    assert result.trend_assessment == "uptrend"


def test_uncertainty_is_normalized_to_uppercase():
    response = WELL_FORMED_RESPONSE.replace('"MEDIUM"', '"medium"')
    client = _fake_client(response)

    result = TradeAgent(client=client).analyze(_successful_capture(), _successful_market_data())

    assert result.status == AgentAnalysisStatus.SUCCESS
    assert result.uncertainty == "MEDIUM"


def test_high_uncertainty_is_accepted_as_a_valid_honest_answer():
    response = json.dumps(
        {
            "analysis_text": "The chart is too ambiguous to read confidently.",
            "trend_assessment": "unclear -- no consistent direction visible",
            "structure_assessment": "insufficient information",
            "setup_assessment": "no readable setup",
            "uncertainty": "HIGH",
        }
    )
    client = _fake_client(response)

    result = TradeAgent(client=client).analyze(_successful_capture(), _successful_market_data())

    assert result.status == AgentAnalysisStatus.SUCCESS
    assert result.uncertainty == "HIGH"


# ---------------------------------------------------------------------------
# THE HARD BOUNDARY -- a numeric score is rejected, not passed through
# ---------------------------------------------------------------------------


def test_response_with_extra_numeric_score_field_is_rejected():
    payload = json.loads(WELL_FORMED_RESPONSE)
    payload["confidence_score"] = 87
    client = _fake_client(json.dumps(payload))

    result = TradeAgent(client=client).analyze(_successful_capture(), _successful_market_data())

    assert result.status == AgentAnalysisStatus.FAILED
    # The score must never reach the stored analysis fields -- everything
    # is None on a rejected response, not a partially-trusted result.
    assert result.analysis_text is None
    assert result.trend_assessment is None
    assert result.structure_assessment is None
    assert result.setup_assessment is None
    assert result.uncertainty is None
    assert "87" not in (result.error_message or "").replace("confidence_score", "")
    assert "numeric" in result.error_message.lower()


def test_response_with_numeric_uncertainty_is_rejected():
    payload = json.loads(WELL_FORMED_RESPONSE)
    payload["uncertainty"] = 85
    client = _fake_client(json.dumps(payload))

    result = TradeAgent(client=client).analyze(_successful_capture(), _successful_market_data())

    assert result.status == AgentAnalysisStatus.FAILED
    assert result.uncertainty is None


def test_response_with_numeric_trend_assessment_is_rejected():
    payload = json.loads(WELL_FORMED_RESPONSE)
    payload["trend_assessment"] = 7
    client = _fake_client(json.dumps(payload))

    result = TradeAgent(client=client).analyze(_successful_capture(), _successful_market_data())

    assert result.status == AgentAnalysisStatus.FAILED
    assert result.trend_assessment is None


def test_response_with_percentage_style_uncertainty_is_rejected():
    payload = json.loads(WELL_FORMED_RESPONSE)
    payload["uncertainty"] = "15%"
    client = _fake_client(json.dumps(payload))

    result = TradeAgent(client=client).analyze(_successful_capture(), _successful_market_data())

    assert result.status == AgentAnalysisStatus.FAILED


# ---------------------------------------------------------------------------
# Malformed responses fail, they are never fabricated into something usable
# ---------------------------------------------------------------------------


def test_response_that_is_not_json_returns_failed():
    client = _fake_client("Sure! The chart looks bullish to me.")

    result = TradeAgent(client=client).analyze(_successful_capture(), _successful_market_data())

    assert result.status == AgentAnalysisStatus.FAILED
    assert result.analysis_text is None


def test_response_missing_a_required_field_returns_failed():
    payload = json.loads(WELL_FORMED_RESPONSE)
    del payload["setup_assessment"]
    client = _fake_client(json.dumps(payload))

    result = TradeAgent(client=client).analyze(_successful_capture(), _successful_market_data())

    assert result.status == AgentAnalysisStatus.FAILED
    assert "setup_assessment" in result.error_message


def test_response_with_invalid_uncertainty_word_returns_failed():
    payload = json.loads(WELL_FORMED_RESPONSE)
    payload["uncertainty"] = "SORT_OF"
    client = _fake_client(json.dumps(payload))

    result = TradeAgent(client=client).analyze(_successful_capture(), _successful_market_data())

    assert result.status == AgentAnalysisStatus.FAILED


# ---------------------------------------------------------------------------
# API errors -- real error message, never a fabricated analysis
# ---------------------------------------------------------------------------


def test_api_timeout_returns_failed_with_error_message():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    client = _fake_client(side_effect=anthropic.APITimeoutError(request=request))

    result = TradeAgent(client=client).analyze(_successful_capture(), _successful_market_data())

    assert result.status == AgentAnalysisStatus.FAILED
    assert result.analysis_text is None
    assert "timed out" in result.error_message.lower()


def test_generic_api_error_returns_failed_with_error_message():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    client = _fake_client(
        side_effect=anthropic.APIConnectionError(message="connection reset", request=request)
    )

    result = TradeAgent(client=client).analyze(_successful_capture(), _successful_market_data())

    assert result.status == AgentAnalysisStatus.FAILED
    assert "connection reset" in result.error_message


def test_missing_api_key_returns_failed_without_calling_anything(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = TradeAgent().analyze(_successful_capture(), _successful_market_data())

    assert result.status == AgentAnalysisStatus.FAILED
    assert "ANTHROPIC_API_KEY" in result.error_message


# ---------------------------------------------------------------------------
# Timestamp
# ---------------------------------------------------------------------------


def test_timestamp_is_timezone_aware_utc_on_success():
    client = _fake_client(WELL_FORMED_RESPONSE)

    result = TradeAgent(client=client).analyze(_successful_capture(), _successful_market_data())

    assert result.timestamp is not None
    assert result.timestamp.tzinfo is not None
    assert result.timestamp.utcoffset() == timedelta(0)


def test_timestamp_is_none_on_failure():
    bad_capture = _successful_capture(status=CaptureStatus.FAILED, screenshot_path=None)

    result = TradeAgent().analyze(bad_capture, _successful_market_data())

    assert result.status == AgentAnalysisStatus.FAILED
    assert result.timestamp is None


# ---------------------------------------------------------------------------
# Never phrases anything as an instruction to trade (prompt-level contract,
# checked here by confirming the rendered prompt sent to Claude carries the
# constraint -- the actual enforcement is Claude's, per the system prompt)
# ---------------------------------------------------------------------------


def test_analysis_and_system_prompts_forbid_trade_instructions_and_scores():
    from agents.trade_agent import ANALYSIS_PROMPT_PATH, SYSTEM_PROMPT_PATH

    system_text = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").lower()
    analysis_text = ANALYSIS_PROMPT_PATH.read_text(encoding="utf-8").lower()

    assert "never recommend" in system_text or "never say" in system_text
    assert "score" in system_text and "score" in analysis_text
    assert "uncertainty" in system_text


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def test_module_level_analyze_function_delegates_correctly():
    """
    Calls the actual module-level analyze() (not TradeAgent directly).
    Uses a failed capture so this stays deterministic and network-free
    regardless of whether ANTHROPIC_API_KEY happens to be set -- the
    input-validation short-circuit is hit before any client is built.
    """
    bad_capture = _successful_capture(status=CaptureStatus.FAILED, screenshot_path=None)

    result = analyze(bad_capture, _successful_market_data(), TradeParams(direction="long"))

    assert result.status == AgentAnalysisStatus.FAILED
    assert "No chart to analyze" in result.error_message
