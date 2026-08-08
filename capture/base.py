# TradePilot AI — the chart-capture interface every provider implements.
#
# In plain terms: this file defines the shape of "a chart was captured"
# (or wasn't). DemoProvider and LiveProvider both promise to return this
# same shape, so nothing that calls capture() ever needs to know which
# one actually ran.

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = REPO_ROOT / "screenshots" / "demo"
LIVE_DIR = REPO_ROOT / "screenshots" / "live"


class CaptureMode(str, Enum):
    LIVE = "LIVE"
    DEMO = "DEMO"


class CaptureStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


@dataclass(frozen=True)
class CaptureResult:
    """
    What every capture attempt returns, success or failure alike.

    captured_at is set only on success, and it's always the real moment
    the screenshot was actually taken -- recorded right here, not filled
    in later when this eventually gets written to the database. The
    future data-freshness guardrail (Milestone 9) depends on this being
    the true capture time, not a database-write time standing in for it.
    """

    mode: CaptureMode
    symbol: str
    timeframe: str
    screenshot_path: Optional[str]
    captured_at: Optional[datetime]
    status: CaptureStatus
    error_message: Optional[str] = None


class CaptureProvider(ABC):
    """One way of getting a chart screenshot: a live browser, or a saved fixture."""

    @abstractmethod
    def capture(self, symbol: str, timeframe: str) -> CaptureResult:
        """Attempt to capture a chart for the given symbol and timeframe."""
        raise NotImplementedError


def sanitize_component(value: str) -> str:
    """
    Turn a symbol or timeframe into something safe to use in a filename.

    Rejects anything that could escape the screenshots directory (path
    separators, "..") or is simply empty. Both providers run their inputs
    through this before touching the filesystem.
    """
    value = value.strip()
    if not value or "/" in value or "\\" in value or ".." in value:
        raise ValueError(f"Invalid symbol/timeframe for a filename: {value!r}")
    return value
