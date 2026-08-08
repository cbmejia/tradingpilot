# TradePilot AI — LIVE capture provider: drives a real headless browser.
#
# In plain terms: this opens an invisible Chromium browser, navigates to
# a TradingView chart, and screenshots it. If anything goes wrong -- the
# page times out, Playwright isn't installed, TradingView is unreachable
# -- this returns a FAILED result with the real error message. It never
# falls back to a demo image. There is no code path here that calls
# DemoProvider at all.
#
# IMPORTANT: TradingView's terms of service restrict automated access to
# their site. This provider is intended for the developer's own manual
# use at low request volume -- not for bulk or repeated automated
# capture. See docs/architecture.md for the full note. DEMO mode is the
# supported path for demonstrations and grading.

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from capture.base import (
    LIVE_DIR,
    CaptureMode,
    CaptureProvider,
    CaptureResult,
    CaptureStatus,
    sanitize_component,
)

load_dotenv()

DEFAULT_TIMEOUT_MS = 20_000  # hard cap -- goto() and the page wait both respect this

# TradingView's chart URL takes a numeric-minutes interval for intraday
# timeframes, or "D"/"W" for daily/weekly. Adjust if TradingView's URL
# scheme or your preferred symbol prefix (e.g. "FX:", "OANDA:") differs --
# this wasn't tested against the live site as part of this milestone.
_TIMEFRAME_TO_TV_INTERVAL = {
    "1m": "1",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "4h": "240",
    "1d": "D",
    "1w": "W",
}


def build_tradingview_url(symbol: str, timeframe: str) -> str:
    interval = _TIMEFRAME_TO_TV_INTERVAL.get(timeframe, "60")
    return f"https://www.tradingview.com/chart/?symbol={symbol}&interval={interval}"


def live_filename(symbol: str, timeframe: str, captured_at: datetime) -> str:
    symbol = sanitize_component(symbol).upper()
    timeframe = sanitize_component(timeframe).lower()
    stamp = captured_at.strftime("%Y%m%dT%H%M%SZ")
    return f"{symbol}_{timeframe}_{stamp}.png"


class LiveProvider(CaptureProvider):
    def __init__(self, output_dir: Path = LIVE_DIR, timeout_ms: int = DEFAULT_TIMEOUT_MS):
        self._output_dir = output_dir
        self._timeout_ms = timeout_ms

    def capture(self, symbol: str, timeframe: str) -> CaptureResult:
        try:
            symbol = sanitize_component(symbol)
            timeframe = sanitize_component(timeframe)
        except ValueError as exc:
            return self._failed(symbol, timeframe, str(exc))

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            return self._failed(
                symbol,
                timeframe,
                f"Playwright is not installed ({exc}). Run: playwright install chromium",
            )

        url = build_tradingview_url(symbol, timeframe)

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    page.set_default_timeout(self._timeout_ms)
                    page.goto(url, wait_until="load", timeout=self._timeout_ms)
                    # Fixed, bounded pause for the chart canvas to render --
                    # not an infinite wait, just enough for the JS chart
                    # widget to draw candles after the page loads.
                    page.wait_for_timeout(2000)

                    self._output_dir.mkdir(parents=True, exist_ok=True)
                    captured_at = datetime.now(timezone.utc)
                    filename = live_filename(symbol, timeframe, captured_at)
                    path = self._output_dir / filename
                    page.screenshot(path=str(path))
                finally:
                    browser.close()
        except Exception as exc:
            return self._failed(symbol, timeframe, f"Live capture failed: {exc}")

        return CaptureResult(
            mode=CaptureMode.LIVE,
            symbol=symbol,
            timeframe=timeframe,
            screenshot_path=str(path),
            captured_at=captured_at,
            status=CaptureStatus.SUCCESS,
            error_message=None,
        )

    def _failed(self, symbol: str, timeframe: str, message: str) -> CaptureResult:
        return CaptureResult(
            mode=CaptureMode.LIVE,
            symbol=symbol,
            timeframe=timeframe,
            screenshot_path=None,
            captured_at=None,
            status=CaptureStatus.FAILED,
            error_message=message,
        )
