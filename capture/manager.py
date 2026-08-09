# TradePilot AI — picks LIVE or DEMO based on CAPTURE_MODE, and never
# lets one silently stand in for the other.
#
# In plain terms: this is the only thing the rest of the app should call.
# It reads CAPTURE_MODE once, picks exactly one provider, and always uses
# that same provider for every capture() call. If that provider fails,
# the result says so -- it is never quietly swapped for a demo image.
# There is no try/fallback logic anywhere in this file, on purpose.

from __future__ import annotations

import os
from typing import Optional

from dotenv import load_dotenv

from capture.base import CaptureMode, CaptureProvider, CaptureResult
from capture.demo_provider import DemoProvider
from capture.live_provider import LiveProvider

load_dotenv()


class CaptureManager:
    def __init__(
        self,
        mode: Optional[str] = None,
        provider: Optional[CaptureProvider] = None,
    ):
        """
        mode: "LIVE" or "DEMO" (case-insensitive). Defaults to the
        CAPTURE_MODE environment variable, then "demo" if that's unset.

        provider: an explicit CaptureProvider to use instead of picking
        one automatically. Exists so tests can inject a fake provider
        without needing real Playwright or network access -- normal
        callers should leave this as None.
        """
        raw_mode = (mode if mode is not None else os.getenv("CAPTURE_MODE", "demo")).strip().upper()
        try:
            self._mode = CaptureMode(raw_mode)
        except ValueError:
            raise ValueError(
                f"Unknown CAPTURE_MODE: {raw_mode!r}. Must be 'LIVE' or 'DEMO'."
            ) from None

        if provider is not None:
            self._provider: CaptureProvider = provider
        elif self._mode is CaptureMode.LIVE:
            self._provider = LiveProvider()
        else:
            self._provider = DemoProvider()

    @property
    def mode(self) -> CaptureMode:
        return self._mode

    def capture(
        self, symbol: str, timeframe: str, chart_variant: Optional[str] = None
    ) -> CaptureResult:
        """
        chart_variant (7A Iteration 1): forwarded to DemoProvider only --
        LiveProvider has no such concept, so it's simply not passed when
        running LIVE. None (the default, and the only value every caller
        before this addendum ever used) reproduces the exact prior
        behavior.
        """
        if chart_variant is not None and isinstance(self._provider, DemoProvider):
            result = self._provider.capture(symbol, timeframe, chart_variant=chart_variant)
        else:
            result = self._provider.capture(symbol, timeframe)

        if result.mode is not self._mode:
            # Structurally, this should never happen -- each provider only
            # ever labels its own results with its own mode, and this
            # class never calls more than one provider. This check exists
            # so a bug can never silently mislabel a capture's true
            # source in the audit trail.
            raise RuntimeError(
                f"Capture provider mismatch: CaptureManager is running in "
                f"{self._mode.value} mode but got back a result labeled "
                f"{result.mode.value}. Refusing to return a mismatched result."
            )

        return result
