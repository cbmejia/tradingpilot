# TradePilot AI — chart capture tool.
#
# Public API: CaptureManager (use this -- it reads CAPTURE_MODE and never
# falls back between providers), CaptureProvider (the interface),
# CaptureResult / CaptureMode / CaptureStatus (the result shape), and the
# two concrete providers for direct use in tests or scripts.

from capture.base import CaptureMode, CaptureProvider, CaptureResult, CaptureStatus
from capture.demo_provider import DemoProvider
from capture.live_provider import LiveProvider
from capture.manager import CaptureManager

__all__ = [
    "CaptureManager",
    "CaptureMode",
    "CaptureProvider",
    "CaptureResult",
    "CaptureStatus",
    "DemoProvider",
    "LiveProvider",
]
