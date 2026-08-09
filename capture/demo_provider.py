# TradePilot AI — DEMO capture provider.
#
# In plain terms: this reads a real image file that's already sitting on
# disk in screenshots/demo/. It never touches the network, never
# generates an image on the fly, and if the exact symbol/timeframe you
# asked for doesn't have a fixture, it fails with a clear message instead
# of quietly handing back some other pair's chart.
#
# 7A Iteration 1 addendum: a real live-run pass surfaced a genuine gap the
# original single DEMO fixture never exposed. The committed EURUSD_1h.png
# is a deliberately abstract placeholder (a generic bar series plus a
# large "SAMPLE IMAGE" banner, per Milestone 5) -- fine for exercising the
# five categorical fields, which degrade gracefully on a vague image (the
# agent can always fall back to UNCLEAR), but a proposed trade level has
# nothing to degrade to: it needs an actual visible price structure to
# anchor a stop/target to. Two real LIVE runs against that fixture both
# came back with the agent explicitly declining to propose -- a correct
# read of that specific image, not a bug (confirmed by a live run against
# a real chart with visible structure, which DID propose). chart_variant
# adds a second, real, readable DEMO fixture (EURUSD_4h_readable.png, a
# genuine LIVE capture saved as a fixture) alongside the original --
# "unreadable_chart" (the default, unchanged from before this addendum)
# and "readable_chart". Nothing about the freshness behavior changes:
# captured_at is still generated fresh at call time below, regardless of
# which fixture file gets read -- freshness was never the fixture's
# problem, and it isn't touched here either.

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

CHART_VARIANT_UNREADABLE = "unreadable_chart"
CHART_VARIANT_READABLE = "readable_chart"
CHART_VARIANTS = (CHART_VARIANT_UNREADABLE, CHART_VARIANT_READABLE)


def demo_filename(symbol: str, timeframe: str, chart_variant: str = CHART_VARIANT_UNREADABLE) -> str:
    """The exact, deterministic filename a symbol/timeframe (+ variant)
    maps to. chart_variant="unreadable_chart" (the default) reproduces
    the original filename exactly, so every pre-existing fixture and test
    is unaffected by this parameter existing."""
    symbol = sanitize_component(symbol).upper()
    timeframe = sanitize_component(timeframe).lower()
    if chart_variant == CHART_VARIANT_READABLE:
        return f"{symbol}_{timeframe}_readable.png"
    return f"{symbol}_{timeframe}.png"


class DemoProvider(CaptureProvider):
    def __init__(self, fixtures_dir: Path = DEMO_DIR):
        self._fixtures_dir = fixtures_dir

    def capture(
        self, symbol: str, timeframe: str, chart_variant: str = CHART_VARIANT_UNREADABLE
    ) -> CaptureResult:
        """
        chart_variant is a DEMO-only extension beyond CaptureProvider's
        base interface (LiveProvider has no such concept -- a live
        capture is just whatever the real chart looks like). Defaults to
        the original single fixture, so every caller that doesn't pass it
        gets identical behavior to before this parameter existed.
        """
        if chart_variant not in CHART_VARIANTS:
            return CaptureResult(
                mode=CaptureMode.DEMO,
                symbol=symbol,
                timeframe=timeframe,
                screenshot_path=None,
                captured_at=None,
                status=CaptureStatus.FAILED,
                error_message=(
                    f"Unknown chart_variant {chart_variant!r}. Must be one of {CHART_VARIANTS}."
                ),
            )

        try:
            filename = demo_filename(symbol, timeframe, chart_variant)
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
                    f"No demo fixture for {symbol} {timeframe} (chart_variant={chart_variant!r}). "
                    f"Expected file at {path}. DEMO mode never substitutes a "
                    f"different pair's chart, or a different variant's."
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
