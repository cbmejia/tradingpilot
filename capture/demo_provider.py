# TradePilot AI — DEMO capture provider.
#
# In plain terms: this reads a real image file that's already sitting on
# disk in screenshots/demo/. It never touches the network, never
# generates an image on the fly, and if the exact symbol/timeframe you
# asked for doesn't have a fixture, it fails with a clear message instead
# of quietly handing back some other pair's chart.

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from capture.base import (
    DEMO_DIR,
    CaptureMode,
    CaptureProvider,
    CaptureResult,
    CaptureStatus,
    sanitize_component,
)


def demo_filename(symbol: str, timeframe: str) -> str:
    """The exact, deterministic filename a symbol/timeframe maps to."""
    symbol = sanitize_component(symbol).upper()
    timeframe = sanitize_component(timeframe).lower()
    return f"{symbol}_{timeframe}.png"


class DemoProvider(CaptureProvider):
    def __init__(self, fixtures_dir: Path = DEMO_DIR):
        self._fixtures_dir = fixtures_dir

    def capture(self, symbol: str, timeframe: str) -> CaptureResult:
        try:
            filename = demo_filename(symbol, timeframe)
        except ValueError as exc:
            return CaptureResult(
                mode=CaptureMode.DEMO,
                symbol=symbol,
                timeframe=timeframe,
                screenshot_path=None,
                captured_at=None,
                status=CaptureStatus.FAILED,
                error_message=str(exc),
            )

        path = self._fixtures_dir / filename
        if not path.is_file():
            return CaptureResult(
                mode=CaptureMode.DEMO,
                symbol=symbol,
                timeframe=timeframe,
                screenshot_path=None,
                captured_at=None,
                status=CaptureStatus.FAILED,
                error_message=(
                    f"No demo fixture for {symbol} {timeframe}. Expected "
                    f"file at {path}. DEMO mode never substitutes a "
                    f"different pair's chart."
                ),
            )

        return CaptureResult(
            mode=CaptureMode.DEMO,
            symbol=symbol,
            timeframe=timeframe,
            screenshot_path=str(path),
            captured_at=datetime.now(timezone.utc),
            status=CaptureStatus.SUCCESS,
            error_message=None,
        )
