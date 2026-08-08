# TradePilot AI — tests for the chart capture tool (Milestone 5).
#
# No test in this file makes a real network request. DEMO tests only read
# local fixture files. LIVE tests either use a fake CaptureProvider or
# mock playwright.sync_api.sync_playwright itself, so nothing here ever
# launches a real browser or contacts TradingView.

from datetime import timedelta
from unittest.mock import patch

import pytest

from capture.base import CaptureMode, CaptureProvider, CaptureResult, CaptureStatus
from capture.demo_provider import DemoProvider, demo_filename
from capture.live_provider import LiveProvider
from capture.manager import CaptureManager


# ---------------------------------------------------------------------------
# DemoProvider
# ---------------------------------------------------------------------------


def test_demo_capture_succeeds_for_known_fixture():
    result = DemoProvider().capture("EURUSD", "1h")

    assert result.mode == CaptureMode.DEMO
    assert result.status == CaptureStatus.SUCCESS
    assert result.error_message is None
    assert result.screenshot_path is not None
    assert result.screenshot_path.endswith(demo_filename("EURUSD", "1h"))


def test_demo_capture_screenshot_path_actually_exists_on_disk():
    result = DemoProvider().capture("GBPUSD", "4h")

    from pathlib import Path

    assert Path(result.screenshot_path).is_file()


def test_demo_capture_is_deterministic():
    first = DemoProvider().capture("EURUSD", "1h")
    second = DemoProvider().capture("EURUSD", "1h")

    assert first.screenshot_path == second.screenshot_path


def test_demo_capture_unknown_symbol_fails_cleanly_without_substituting_a_chart():
    result = DemoProvider().capture("ZZZINVALID", "1h")

    assert result.mode == CaptureMode.DEMO
    assert result.status == CaptureStatus.FAILED
    assert result.screenshot_path is None
    assert result.captured_at is None
    assert "ZZZINVALID" in result.error_message
    assert "1h" in result.error_message


def test_demo_capture_rejects_path_traversal_attempt():
    result = DemoProvider().capture("../../etc", "1h")

    assert result.status == CaptureStatus.FAILED
    assert result.screenshot_path is None


def test_demo_captured_at_is_timezone_aware_utc():
    result = DemoProvider().capture("EURUSD", "1h")

    assert result.captured_at is not None
    assert result.captured_at.tzinfo is not None
    assert result.captured_at.utcoffset() == timedelta(0)


# ---------------------------------------------------------------------------
# CaptureManager
# ---------------------------------------------------------------------------


def test_capture_manager_demo_mode_returns_a_demo_result():
    manager = CaptureManager(mode="demo")

    result = manager.capture("EURUSD", "1h")

    assert manager.mode == CaptureMode.DEMO
    assert result.mode == CaptureMode.DEMO
    assert result.status == CaptureStatus.SUCCESS


def test_capture_manager_mode_is_case_insensitive():
    manager = CaptureManager(mode="Demo")

    assert manager.mode == CaptureMode.DEMO


def test_capture_manager_rejects_unknown_mode():
    with pytest.raises(ValueError):
        CaptureManager(mode="banana")


class _FakeFailingLiveProvider(CaptureProvider):
    """Simulates a real LIVE provider that failed -- no network involved."""

    def capture(self, symbol: str, timeframe: str) -> CaptureResult:
        return CaptureResult(
            mode=CaptureMode.LIVE,
            symbol=symbol,
            timeframe=timeframe,
            screenshot_path=None,
            captured_at=None,
            status=CaptureStatus.FAILED,
            error_message="TradingView page did not load in time",
        )


def test_capture_manager_live_failure_returns_failed_and_never_a_demo_image():
    manager = CaptureManager(mode="live", provider=_FakeFailingLiveProvider())

    result = manager.capture("EURUSD", "1h")

    assert result.mode == CaptureMode.LIVE
    assert result.status == CaptureStatus.FAILED
    assert result.screenshot_path is None
    assert "did not load" in result.error_message
    # The failure must not be quietly replaced with demo fixture data.
    assert result.screenshot_path != DemoProvider().capture("EURUSD", "1h").screenshot_path


class _MislabelingProvider(CaptureProvider):
    """A provider that (incorrectly) labels its result with the wrong mode."""

    def capture(self, symbol: str, timeframe: str) -> CaptureResult:
        return CaptureResult(
            mode=CaptureMode.DEMO,  # wrong on purpose -- manager thinks it's running LIVE
            symbol=symbol,
            timeframe=timeframe,
            screenshot_path="screenshots/demo/EURUSD_1h.png",
            captured_at=None,
            status=CaptureStatus.SUCCESS,
        )


def test_capture_manager_raises_if_a_provider_mislabels_its_result():
    """
    This is the structural backstop for "never silently fall back from
    LIVE to DEMO": even if a provider were buggy and returned a
    mismatched mode, the manager refuses to pass it through.
    """
    manager = CaptureManager(mode="live", provider=_MislabelingProvider())

    with pytest.raises(RuntimeError):
        manager.capture("EURUSD", "1h")


# ---------------------------------------------------------------------------
# LiveProvider (mocked -- never touches the network)
# ---------------------------------------------------------------------------


def test_live_provider_failure_returns_failed_with_real_error_no_network():
    with patch("playwright.sync_api.sync_playwright") as mock_sync_playwright:
        mock_sync_playwright.side_effect = RuntimeError(
            "mocked: no browser binary available in this test environment"
        )

        result = LiveProvider().capture("EURUSD", "1h")

    assert result.mode == CaptureMode.LIVE
    assert result.status == CaptureStatus.FAILED
    assert result.screenshot_path is None
    assert result.captured_at is None
    assert "mocked: no browser binary" in result.error_message


def test_live_provider_result_mode_is_always_live_even_on_failure():
    with patch("playwright.sync_api.sync_playwright") as mock_sync_playwright:
        mock_sync_playwright.side_effect = RuntimeError("boom")

        result = LiveProvider().capture("GBPUSD", "4h")

    assert result.mode == CaptureMode.LIVE
