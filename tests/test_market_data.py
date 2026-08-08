# TradePilot AI — tests for the market data tool (Milestone 6).
#
# No test in this file makes a real network request. DEMO tests only read
# the local fixture file. LIVE tests mock requests.get directly, so
# nothing here ever contacts Alpha Vantage or any other real API.

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
import requests

from tools.market_data import (
    DemoMarketDataProvider,
    LiveMarketDataProvider,
    MarketDataManager,
    MarketDataMode,
    MarketDataProvider,
    MarketDataStatus,
    MarketQuote,
    get_market_data,
)


# ---------------------------------------------------------------------------
# DemoMarketDataProvider
# ---------------------------------------------------------------------------


def test_demo_fetch_succeeds_for_known_symbol():
    result = DemoMarketDataProvider().get_quote("EURUSD")

    assert result.mode == MarketDataMode.DEMO
    assert result.status == MarketDataStatus.SUCCESS
    assert result.symbol == "EURUSD"
    assert result.price == 1.0921
    assert result.source == "demo_fixture"
    assert result.error_message is None


def test_demo_fetch_price_is_deterministic_across_calls():
    """
    The price is fixed/deterministic -- same value every call. The
    timestamp deliberately is NOT: it's generated fresh at fetch time
    (see DemoMarketDataProvider's docstring) so a demo run stays
    reviewable instead of aging into a stale, BLOCKED one.
    """
    first = DemoMarketDataProvider().get_quote("EURUSD")
    second = DemoMarketDataProvider().get_quote("EURUSD")

    assert first.price == second.price == 1.0921


def test_demo_fetch_timestamp_is_generated_fresh_at_fetch_time():
    before = datetime.now(timezone.utc)
    result = DemoMarketDataProvider().get_quote("EURUSD")
    after = datetime.now(timezone.utc)

    assert before <= result.timestamp <= after


def test_demo_fetch_unknown_symbol_fails_cleanly_without_substituting_a_price():
    result = DemoMarketDataProvider().get_quote("ZZZINVALID")

    assert result.mode == MarketDataMode.DEMO
    assert result.status == MarketDataStatus.FAILED
    assert result.price is None
    assert result.timestamp is None
    assert "ZZZINVALID" in result.error_message


def test_demo_quote_timestamp_is_timezone_aware_utc():
    result = DemoMarketDataProvider().get_quote("GBPUSD")

    assert result.timestamp is not None
    assert result.timestamp.tzinfo is not None
    assert result.timestamp.utcoffset() == timedelta(0)


def test_demo_source_is_clearly_marked_as_sample_data():
    result = DemoMarketDataProvider().get_quote("EURUSD")

    assert result.source == "demo_fixture"


# ---------------------------------------------------------------------------
# MarketDataManager
# ---------------------------------------------------------------------------


def test_manager_demo_mode_returns_a_demo_result():
    manager = MarketDataManager(mode="demo")

    result = manager.get_quote("EURUSD")

    assert manager.mode == MarketDataMode.DEMO
    assert result.mode == MarketDataMode.DEMO
    assert result.status == MarketDataStatus.SUCCESS


def test_manager_rejects_unknown_mode():
    with pytest.raises(ValueError):
        MarketDataManager(mode="banana")


class _FakeFailingLiveProvider(MarketDataProvider):
    """Simulates a real LIVE provider that failed -- no network involved."""

    def get_quote(self, symbol: str) -> MarketQuote:
        return MarketQuote(
            mode=MarketDataMode.LIVE,
            symbol=symbol,
            price=None,
            timestamp=None,
            source="alpha_vantage",
            status=MarketDataStatus.FAILED,
            error_message="Market data request timed out after 10s",
        )


def test_manager_live_failure_never_returns_demo_data():
    manager = MarketDataManager(mode="live", provider=_FakeFailingLiveProvider())

    result = manager.get_quote("EURUSD")

    assert result.mode == MarketDataMode.LIVE
    assert result.status == MarketDataStatus.FAILED
    assert result.price is None
    assert "timed out" in result.error_message
    # The failure must not be quietly replaced with demo fixture data.
    demo_price = DemoMarketDataProvider().get_quote("EURUSD").price
    assert result.price != demo_price


class _MislabelingProvider(MarketDataProvider):
    def get_quote(self, symbol: str) -> MarketQuote:
        return MarketQuote(
            mode=MarketDataMode.DEMO,  # wrong on purpose
            symbol=symbol,
            price=1.0921,
            timestamp=datetime.now(timezone.utc),
            source="demo_fixture",
            status=MarketDataStatus.SUCCESS,
        )


def test_manager_raises_if_a_provider_mislabels_its_result():
    manager = MarketDataManager(mode="live", provider=_MislabelingProvider())

    with pytest.raises(RuntimeError):
        manager.get_quote("EURUSD")


# ---------------------------------------------------------------------------
# LiveMarketDataProvider (mocked -- never touches the network)
# ---------------------------------------------------------------------------


def _successful_alpha_vantage_response(
    rate: str = "1.08670000",
    last_refreshed: str = "2024-01-15 20:14:05",
    time_zone: str = "UTC",
) -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "Realtime Currency Exchange Rate": {
            "1. From_Currency Code": "EUR",
            "3. To_Currency Code": "USD",
            "5. Exchange Rate": rate,
            "6. Last Refreshed": last_refreshed,
            "7. Time Zone": time_zone,
        }
    }
    return response


def test_live_fetch_missing_api_key_fails_without_any_request(monkeypatch):
    monkeypatch.delenv("MARKET_DATA_API_KEY", raising=False)

    with patch("requests.get") as mock_get:
        result = LiveMarketDataProvider().get_quote("EURUSD")

    assert result.status == MarketDataStatus.FAILED
    assert result.price is None
    assert "MARKET_DATA_API_KEY" in result.error_message
    mock_get.assert_not_called()


def test_live_fetch_timeout_returns_failed_with_no_price(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_API_KEY", "test-key")

    with patch("requests.get") as mock_get:
        mock_get.side_effect = requests.exceptions.Timeout("timed out waiting for a response")

        result = LiveMarketDataProvider().get_quote("EURUSD")

    assert result.mode == MarketDataMode.LIVE
    assert result.status == MarketDataStatus.FAILED
    assert result.price is None
    assert result.timestamp is None
    assert "timed out" in result.error_message.lower()


def test_live_fetch_malformed_response_returns_failed_not_a_guess(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_API_KEY", "test-key")

    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"unexpected": "shape"}

    with patch("requests.get", return_value=response):
        result = LiveMarketDataProvider().get_quote("EURUSD")

    assert result.status == MarketDataStatus.FAILED
    assert result.price is None


def test_live_fetch_bad_exchange_rate_value_returns_failed_not_a_guess(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_API_KEY", "test-key")

    response = _successful_alpha_vantage_response(rate="not-a-number")

    with patch("requests.get", return_value=response):
        result = LiveMarketDataProvider().get_quote("EURUSD")

    assert result.status == MarketDataStatus.FAILED
    assert result.price is None


def test_live_fetch_unknown_symbol_returns_failed(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_API_KEY", "test-key")

    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "Error Message": "Invalid API call. Please retry or visit the documentation."
    }

    with patch("requests.get", return_value=response):
        # 6 letters -- passes the shape check, so this actually reaches
        # the (mocked) source and exercises its "unknown symbol" response.
        result = LiveMarketDataProvider().get_quote("ZZZXXX")

    assert result.status == MarketDataStatus.FAILED
    assert result.price is None
    assert "Invalid API call" in result.error_message


def test_live_fetch_rejects_non_utc_source_timezone(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_API_KEY", "test-key")

    response = _successful_alpha_vantage_response(time_zone="America/New_York")

    with patch("requests.get", return_value=response):
        result = LiveMarketDataProvider().get_quote("EURUSD")

    assert result.status == MarketDataStatus.FAILED
    assert result.price is None


def test_live_fetch_success_returns_source_quote_time_not_fetch_time(monkeypatch):
    """
    The whole point of storing the source's timestamp: it must be the
    time Alpha Vantage says the quote is from, not datetime.now() at
    fetch time. Using a fixed historical value here proves that -- if the
    code used "now" instead, this would fail immediately.
    """
    monkeypatch.setenv("MARKET_DATA_API_KEY", "test-key")

    response = _successful_alpha_vantage_response(
        rate="1.23450000", last_refreshed="2020-06-01 09:30:00"
    )

    with patch("requests.get", return_value=response):
        result = LiveMarketDataProvider().get_quote("EURUSD")

    assert result.mode == MarketDataMode.LIVE
    assert result.status == MarketDataStatus.SUCCESS
    assert result.price == 1.2345
    assert result.source == "alpha_vantage"
    assert result.timestamp == datetime(2020, 6, 1, 9, 30, 0, tzinfo=timezone.utc)
    assert result.timestamp.tzinfo is not None


def test_live_fetch_rejects_invalid_symbol_shape():
    result = LiveMarketDataProvider().get_quote("NOTAPAIR")

    assert result.status == MarketDataStatus.FAILED
    assert result.price is None


# ---------------------------------------------------------------------------
# get_market_data() convenience function
# ---------------------------------------------------------------------------


def test_get_market_data_convenience_function_uses_demo_mode():
    result = get_market_data("EURUSD", mode="demo")

    assert result.mode == MarketDataMode.DEMO
    assert result.status == MarketDataStatus.SUCCESS
