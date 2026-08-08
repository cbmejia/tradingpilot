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
from typing import Optional

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


# Default minimum "spread" of pixel brightness a real chart screenshot
# should have. A blank page, a plain consent banner, or a solid-color
# render error all look like one flat color -- close to zero variance.
# An actual chart (candles, gridlines, text, axis labels) always has
# meaningfully more variance than this. Deliberately conservative -- it's
# meant to catch "obviously not a chart," not to judge chart quality.
DEFAULT_BLANK_STDDEV_THRESHOLD = 3.0


def screenshot_is_valid(
    path: Path, stddev_threshold: float = DEFAULT_BLANK_STDDEV_THRESHOLD
) -> tuple[bool, str]:
    """
    Checks a screenshot file isn't blank or near-uniform. Returns
    (True, "") if it looks like real content, or (False, reason) if not.

    Pillow is imported lazily here (not at module load) so DEMO mode --
    and anything that only imports this module for its constants -- never
    needs Pillow installed at all.
    """
    try:
        from PIL import Image, ImageStat
    except ImportError as exc:
        return False, f"Pillow is not installed, cannot validate the screenshot ({exc})"

    try:
        with Image.open(path) as image:
            grayscale = image.convert("L")
            stddev = ImageStat.Stat(grayscale).stddev[0]
    except Exception as exc:
        return False, f"Could not read the captured image: {exc}"

    if stddev < stddev_threshold:
        return False, (
            f"image appears blank or near-uniform (pixel brightness "
            f"stddev={stddev:.2f}, minimum required={stddev_threshold})"
        )

    return True, ""


class LiveProvider(CaptureProvider):
    def __init__(
        self,
        output_dir: Path = LIVE_DIR,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        chart_selector: str = "canvas",
    ):
        self._output_dir = output_dir
        self._timeout_ms = timeout_ms
        # The element that must appear before we trust the page has
        # actually rendered a chart, not just loaded a blank shell or a
        # cookie/consent banner. TradingView draws its chart on a
        # <canvas> element, which is a reasonable general default --
        # adjust this if TradingView's markup differs from what's
        # expected here (not verified against the live site in this
        # milestone).
        self._chart_selector = chart_selector

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
        path: Optional[Path] = None

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    page.set_default_timeout(self._timeout_ms)
                    page.goto(url, wait_until="load", timeout=self._timeout_ms)

                    try:
                        page.wait_for_selector(self._chart_selector, timeout=self._timeout_ms)
                    except Exception as exc:
                        return self._failed(
                            symbol,
                            timeframe,
                            f"Chart element ({self._chart_selector!r}) never appeared on "
                            f"the page -- likely a blank page, a consent banner, or a "
                            f"failed render: {exc}",
                        )

                    # Fixed, bounded pause for the chart canvas to finish
                    # drawing -- not an infinite wait, just enough for the
                    # JS chart widget to draw candles after it appears.
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

        is_valid, reason = screenshot_is_valid(path)
        if not is_valid:
            return self._failed(
                symbol,
                timeframe,
                f"Captured screenshot failed the validity check: {reason}. "
                f"The file was saved to {path} for inspection, but this capture "
                f"is not usable.",
            )

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
