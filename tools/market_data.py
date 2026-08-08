# TradePilot AI — market data tool.
#
# In plain terms: this answers one question — "what is the current price
# for this symbol?" — and it is only ever allowed to answer with a real
# number that actually came from somewhere, or with a clear failure.
#
# THE SINGLE MOST IMPORTANT RULE: if the source fails, is unreachable,
# times out, doesn't recognize the symbol, or sends back something that
# doesn't parse, this returns a FAILED result. It never invents,
# estimates, interpolates, guesses, or carries forward a price. A
# fabricated price would corrupt the agent, the evaluation, and the
# guardrails all at once, while still looking confident. There is no
# code path anywhere in this file that produces a number the source
# didn't actually send.
#
# Structured the same way as capture/: one interface (MarketDataProvider),
# a LIVE provider and a DEMO provider, and a manager that picks between
# them based on MARKET_DATA_MODE -- and never falls back from one to the
# other. Kept in this single file (rather than its own package, unlike
# capture/) since it's small enough not to need splitting up.

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

DEMO_FIXTURE_PATH = Path(__file__).resolve().parent / "demo_market_data.json"
DEFAULT_TIMEOUT_SECONDS = 10  # hard cap on the live HTTP request -- no infinite waits
ALPHA_VANTAGE_BASE_URL = "https://www.alphavantage.co/query"


class MarketDataMode(str, Enum):
    LIVE = "LIVE"
    DEMO = "DEMO"


class MarketDataStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


@dataclass(frozen=True)
class MarketQuote:
    """
    What every quote attempt returns, success or failure alike.

    For LIVE quotes, timestamp is the time the SOURCE says the quote is
    from -- never datetime.now() at fetch time -- so the freshness
    guardrail (Milestone 9) knows how old the DATA genuinely is, not how
    recently it was asked for.

    DEMO is a deliberate, documented exception: DemoMarketDataProvider
    sets timestamp to datetime.now(utc) at fetch time so a demo run is
    always fresh enough to be reviewable (see its docstring). The price
    stays fixed either way -- only a LIVE timestamp claims to be "when
    the source last quoted this," and `source` always says which kind of
    quote this is.
    """

    mode: MarketDataMode
    symbol: str
    price: Optional[float]
    timestamp: Optional[datetime]
    source: str
    status: MarketDataStatus
    error_message: Optional[str] = None


class MarketDataProvider(ABC):
    """One way of getting a quote: a live API call, or saved fixture data."""

    @abstractmethod
    def get_quote(self, symbol: str) -> MarketQuote:
        """Attempt to fetch the current quote for the given symbol."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# DEMO provider
# ---------------------------------------------------------------------------


class DemoMarketDataProvider(MarketDataProvider):
    """
    DELIBERATE DEMO AFFORDANCE: the price is fixed and deterministic
    (read from tools/demo_market_data.json, same value every call), but
    the quote TIMESTAMP is generated at fetch time (datetime.now(utc)),
    not read from the fixture. A demo run needs to be reviewable -- if
    the timestamp were pinned to a fixed date, it would age indefinitely
    and every demo quote would eventually (in practice, immediately) fail
    the MARKET_DATA_FRESH guardrail and BLOCK the run before a human ever
    saw it, even though SYNTHETIC_DATA already guarantees a demo run can
    never reach READY_FOR_REVIEW on its own. Freshness staying real and
    strict for LIVE data was non-negotiable, so the fix lives here, in
    the provider that's allowed to be generous about itself -- not in the
    guardrail, which stays exactly as strict for everyone.
    """

    def __init__(self, fixture_path: Path = DEMO_FIXTURE_PATH):
        self._fixture_path = fixture_path

    def get_quote(self, symbol: str) -> MarketQuote:
        symbol = symbol.strip().upper()
        if not symbol:
            return self._failed(symbol, "Symbol must not be empty.")

        try:
            with open(self._fixture_path, "r", encoding="utf-8") as f:
                fixtures = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            return self._failed(symbol, f"Could not read the demo fixture file: {exc}")

        entry = fixtures.get(symbol)
        if entry is None:
            return self._failed(
                symbol,
                f"No demo quote for {symbol}. DEMO mode never substitutes "
                f"another pair's price.",
            )

        try:
            price = float(entry["price"])
        except (KeyError, TypeError, ValueError) as exc:
            return self._failed(symbol, f"Demo fixture for {symbol} is malformed: {exc}")

        return MarketQuote(
            mode=MarketDataMode.DEMO,
            symbol=symbol,
            price=price,
            timestamp=datetime.now(timezone.utc),
            source="demo_fixture",
            status=MarketDataStatus.SUCCESS,
            error_message=None,
        )

    def _failed(self, symbol: str, message: str) -> MarketQuote:
        return MarketQuote(
            mode=MarketDataMode.DEMO,
            symbol=symbol,
            price=None,
            timestamp=None,
            source="demo_fixture",
            status=MarketDataStatus.FAILED,
            error_message=message,
        )


# ---------------------------------------------------------------------------
# LIVE provider
#
# Uses Alpha Vantage's CURRENCY_EXCHANGE_RATE endpoint. Free tier, no paid
# plan needed -- but it DOES require a free signup to get an API key:
# https://www.alphavantage.co/support/#api-key. The free key is
# rate-limited (a handful of requests per minute, a capped number per
# day), which is fine for this project's "developer's own manual use"
# scope. Chosen over a no-signup option (e.g. Frankfurter) because it
# reports an actual quote timestamp, not just a once-a-day reference rate
# -- this project needs to know how old a quote genuinely is.
# ---------------------------------------------------------------------------


def _split_pair(symbol: str) -> tuple[str, str]:
    symbol = symbol.strip().upper()
    if len(symbol) != 6 or not symbol.isalpha():
        raise ValueError(
            f"Symbol {symbol!r} is not a 6-letter currency pair (e.g. 'EURUSD')."
        )
    return symbol[:3], symbol[3:]


class LiveMarketDataProvider(MarketDataProvider):
    def __init__(
        self,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        base_url: Optional[str] = None,
    ):
        self._timeout_seconds = timeout_seconds
        self._base_url = base_url or os.getenv("MARKET_DATA_BASE_URL") or ALPHA_VANTAGE_BASE_URL

    def get_quote(self, symbol: str) -> MarketQuote:
        raw_symbol = symbol.strip().upper()

        try:
            from_ccy, to_ccy = _split_pair(raw_symbol)
        except ValueError as exc:
            return self._failed(raw_symbol, str(exc))

        api_key = os.getenv("MARKET_DATA_API_KEY")
        if not api_key:
            return self._failed(
                raw_symbol,
                "MARKET_DATA_API_KEY is not set in .env. Get a free key at "
                "https://www.alphavantage.co/support/#api-key.",
            )

        try:
            import requests
        except ImportError as exc:
            return self._failed(raw_symbol, f"The 'requests' package is not installed ({exc}).")

        try:
            response = requests.get(
                self._base_url,
                params={
                    "function": "CURRENCY_EXCHANGE_RATE",
                    "from_currency": from_ccy,
                    "to_currency": to_ccy,
                    "apikey": api_key,
                },
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.exceptions.Timeout as exc:
            return self._failed(
                raw_symbol,
                f"Market data request timed out after {self._timeout_seconds}s: {exc}",
            )
        except requests.exceptions.RequestException as exc:
            return self._failed(raw_symbol, f"Market data request failed: {exc}")
        except ValueError as exc:
            return self._failed(raw_symbol, f"Market data response was not valid JSON: {exc}")

        rate_block = payload.get("Realtime Currency Exchange Rate")
        if not isinstance(rate_block, dict):
            # Alpha Vantage returns HTTP 200 even for bad symbols, bad
            # keys, or rate limiting -- the actual problem shows up as one
            # of these keys instead of the expected quote block.
            problem = (
                payload.get("Error Message")
                or payload.get("Note")
                or payload.get("Information")
                or "the response did not contain a quote"
            )
            return self._failed(
                raw_symbol, f"Market data source returned no usable quote: {problem}"
            )

        try:
            price = float(rate_block["5. Exchange Rate"])
            last_refreshed = rate_block["6. Last Refreshed"]
            source_timezone = rate_block.get("7. Time Zone", "UTC")
            if source_timezone != "UTC":
                return self._failed(
                    raw_symbol,
                    f"Source reported time zone {source_timezone!r}, not UTC -- "
                    f"refusing to guess the offset.",
                )
            timestamp = datetime.strptime(last_refreshed, "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
        except (KeyError, TypeError, ValueError) as exc:
            return self._failed(raw_symbol, f"Market data response was malformed: {exc}")

        return MarketQuote(
            mode=MarketDataMode.LIVE,
            symbol=raw_symbol,
            price=price,
            timestamp=timestamp,
            source="alpha_vantage",
            status=MarketDataStatus.SUCCESS,
            error_message=None,
        )

    def _failed(self, symbol: str, message: str) -> MarketQuote:
        return MarketQuote(
            mode=MarketDataMode.LIVE,
            symbol=symbol,
            price=None,
            timestamp=None,
            source="alpha_vantage",
            status=MarketDataStatus.FAILED,
            error_message=message,
        )


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class MarketDataManager:
    def __init__(
        self,
        mode: Optional[str] = None,
        provider: Optional[MarketDataProvider] = None,
    ):
        """
        mode: "LIVE" or "DEMO" (case-insensitive). Defaults to the
        MARKET_DATA_MODE environment variable, then "demo" if unset.

        provider: an explicit MarketDataProvider to use instead of picking
        one automatically -- exists so tests can inject a fake provider
        without any real network access. Normal callers leave this None.
        """
        raw_mode = (mode if mode is not None else os.getenv("MARKET_DATA_MODE", "demo")).strip().upper()
        try:
            self._mode = MarketDataMode(raw_mode)
        except ValueError:
            raise ValueError(
                f"Unknown MARKET_DATA_MODE: {raw_mode!r}. Must be 'LIVE' or 'DEMO'."
            ) from None

        if provider is not None:
            self._provider: MarketDataProvider = provider
        elif self._mode is MarketDataMode.LIVE:
            self._provider = LiveMarketDataProvider()
        else:
            self._provider = DemoMarketDataProvider()

    @property
    def mode(self) -> MarketDataMode:
        return self._mode

    def get_quote(self, symbol: str) -> MarketQuote:
        result = self._provider.get_quote(symbol)

        if result.mode is not self._mode:
            # Same structural backstop as CaptureManager: a provider bug
            # can never silently mislabel a quote's true source.
            raise RuntimeError(
                f"Market data provider mismatch: MarketDataManager is running "
                f"in {self._mode.value} mode but got back a result labeled "
                f"{result.mode.value}. Refusing to return a mismatched result."
            )

        return result


def get_market_data(symbol: str, mode: Optional[str] = None) -> MarketQuote:
    """Convenience wrapper around MarketDataManager(mode).get_quote(symbol)."""
    return MarketDataManager(mode=mode).get_quote(symbol)
