# broker/upstox/api/expired_data.py
"""
Upstox Expired Instruments API Client

Provides synchronous access to Upstox's /expired-instruments/ API endpoints
for fetching historical data of expired F&O contracts.

Requires Upstox Plus Plan for access to expired contract data.
"""

import time
import threading
from collections import deque
from typing import Any

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# Base URL for Upstox v2 API (expired instruments endpoint is on v2)
UPSTOX_BASE_URL = "https://api.upstox.com/v2"

# Instrument key mapping: OpenAlgo underlying symbol → Upstox instrument_key
UPSTOX_INSTRUMENT_KEYS: dict[str, str] = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "FINNIFTY": "NSE_INDEX|Nifty Financial Services",
    "MIDCPNIFTY": "NSE_INDEX|Nifty Midcap Select",
    "NIFTYNXT50": "NSE_INDEX|Nifty Next 50",
    "SENSEX": "BSE_INDEX|SENSEX",
    "BANKEX": "BSE_INDEX|BANKEX",
    "SENSEX50": "BSE_INDEX|SENSEX50",
}

# Exchange for each underlying
UNDERLYING_EXCHANGE: dict[str, str] = {
    "NIFTY": "NFO",
    "BANKNIFTY": "NFO",
    "FINNIFTY": "NFO",
    "MIDCPNIFTY": "NFO",
    "NIFTYNXT50": "NFO",
    "SENSEX": "BFO",
    "BANKEX": "BFO",
    "SENSEX50": "BFO",
}

# Supported underlyings for the UI
SUPPORTED_UNDERLYINGS = list(UPSTOX_INSTRUMENT_KEYS.keys())


def resolve_underlying_key(underlying: str) -> tuple[str, str] | None:
    """Resolve an underlying name to (upstox_instrument_key, exchange).

    Checks hardcoded indices first (fast path), then queries the SymToken
    master contracts table for equity underlyings.

    Returns:
        (upstox_key, exchange) tuple, or None if the underlying cannot be resolved.
    """
    if underlying in UPSTOX_INSTRUMENT_KEYS:
        return UPSTOX_INSTRUMENT_KEYS[underlying], UNDERLYING_EXCHANGE[underlying]

    # Dynamic lookup: resolve stock equity instrument key from master contracts DB
    try:
        from database.token_db import get_token

        token = get_token(underlying, "NSE")
        if token:
            return token, "NFO"
    except Exception:
        pass

    return None


class _SyncUpstoxRateLimiter:
    """
    Thread-safe sliding-window rate limiter for Upstox API.

    Enforces conservative limits with safety margin below Upstox's documented caps:
    - 45 req/sec  (limit: 50)
    - 450 req/min (limit: 500)
    - 1800 req/30min (limit: 2000)
    """

    def __init__(
        self,
        max_per_second: int = 45,
        max_per_minute: int = 450,
        max_per_30min: int = 1800,
    ) -> None:
        self._limits = {
            "second": (max_per_second, 1.0),
            "minute": (max_per_minute, 60.0),
            "half_hour": (max_per_30min, 1800.0),
        }
        self._windows: dict[str, deque] = {
            "second": deque(),
            "minute": deque(),
            "half_hour": deque(),
        }
        self._lock = threading.Lock()
        self._backoff_factor = 1.0
        self._error_count = 0

    def acquire(self) -> None:
        """Block until a rate-limit slot is available."""
        while True:
            with self._lock:
                now = time.monotonic()

                # Evict timestamps outside each window
                for name, (_, duration) in self._limits.items():
                    window = self._windows[name]
                    while window and now - window[0] > duration:
                        window.popleft()

                # Determine required wait across all windows
                wait_time = 0.0
                for name, (limit, duration) in self._limits.items():
                    window = self._windows[name]
                    effective_limit = int(limit / self._backoff_factor)
                    if len(window) >= effective_limit:
                        oldest = window[0]
                        wait_needed = duration - (now - oldest) + 0.01
                        wait_time = max(wait_time, wait_needed)

                if wait_time <= 0:
                    # Slot available — record this request and return
                    now = time.monotonic()
                    for window in self._windows.values():
                        window.append(now)
                    return

            # Sleep OUTSIDE the lock so other threads are not blocked
            logger.debug(f"Rate limit: waiting {wait_time:.2f}s")
            time.sleep(wait_time)

    def on_response(self, status_code: int, retry_after: int = 60) -> None:
        """Adjust backoff factor based on API response status."""
        do_sleep = False
        with self._lock:
            if status_code == 429:
                self._error_count += 1
                self._backoff_factor = min(2.0, 1.0 + self._error_count * 0.1)
                logger.warning(f"Rate limit hit (429), backing off {retry_after}s")
                do_sleep = True
            elif status_code < 400 and self._error_count > 0:
                self._error_count -= 1
                self._backoff_factor = max(1.0, self._backoff_factor - 0.05)
        # Sleep OUTSIDE the lock so other threads are not blocked
        if do_sleep:
            time.sleep(retry_after)


# Module-level shared rate limiter instance
_rate_limiter = _SyncUpstoxRateLimiter()


class UpstoxExpiredDataClient:
    """
    Synchronous HTTP client for Upstox expired instruments API.

    Uses OpenAlgo's shared httpx connection pool and the module-level
    rate limiter so all threads share the same limit budget.

    Args:
        auth_token: Valid Upstox Bearer auth token from OpenAlgo's auth DB.
    """

    def __init__(self, auth_token: str) -> None:
        self.auth_token = auth_token
        self._client = get_httpx_client()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.auth_token}",
            "Accept": "application/json",
        }

    def _get(self, path: str, params: dict[str, str] | None = None) -> Any:
        """
        Make a rate-limited GET request to the Upstox v2 API.

        Args:
            path: API path (e.g., "/expired-instruments/expiries")
            params: Query parameters

        Returns:
            Parsed JSON response or None on failure
        """
        url = f"{UPSTOX_BASE_URL}{path}"
        _rate_limiter.acquire()
        try:
            response = self._client.get(url, headers=self._headers(), params=params)
            _rate_limiter.on_response(response.status_code)
            if response.status_code == 200:
                return response.json()
            logger.error(
                f"Upstox API error {response.status_code} for {path}: "
                f"{response.text[:200]}"
            )
            return None
        except Exception as e:
            logger.exception(f"Request failed for {path}: {e}")
            return None

    def get_expiries(self, instrument_key: str) -> list[str]:
        """
        Fetch all available expiry dates for an instrument.

        Args:
            instrument_key: Upstox instrument key (e.g., "NSE_INDEX|Nifty 50")

        Returns:
            List of expiry dates in YYYY-MM-DD format, empty list on failure.
        """
        logger.info(f"Fetching expiries for {instrument_key}")
        data = self._get(
            "/expired-instruments/expiries",
            params={"instrument_key": instrument_key},
        )
        if data is None:
            return []
        expiries = data.get("data", [])
        logger.info(f"Found {len(expiries)} expiries for {instrument_key}")
        return expiries

    def get_option_contracts(
        self, instrument_key: str, expiry_date: str
    ) -> list[dict[str, Any]]:
        """
        Fetch expired option contracts (CE and PE) for a given expiry.

        Args:
            instrument_key: Upstox instrument key
            expiry_date: Expiry date in YYYY-MM-DD format

        Returns:
            List of contract dicts from Upstox API.
        """
        logger.info(f"Fetching option contracts for {instrument_key} expiry {expiry_date}")
        data = self._get(
            "/expired-instruments/option/contract",
            params={"instrument_key": instrument_key, "expiry_date": expiry_date},
        )
        if data is None:
            return []
        contracts = data.get("data", [])
        logger.info(f"Found {len(contracts)} option contracts")
        return contracts

    def get_future_contracts(
        self, instrument_key: str, expiry_date: str
    ) -> list[dict[str, Any]]:
        """
        Fetch expired futures contracts for a given expiry.

        Args:
            instrument_key: Upstox instrument key
            expiry_date: Expiry date in YYYY-MM-DD format

        Returns:
            List of contract dicts from Upstox API.
        """
        logger.info(f"Fetching future contracts for {instrument_key} expiry {expiry_date}")
        data = self._get(
            "/expired-instruments/future/contract",
            params={"instrument_key": instrument_key, "expiry_date": expiry_date},
        )
        if data is None:
            return []
        contracts = data.get("data", [])
        logger.info(f"Found {len(contracts)} future contracts")
        return contracts

    def get_historical_data(
        self,
        expired_instrument_key: str,
        from_date: str,
        to_date: str,
        interval: str = "1minute",
    ) -> list[list]:
        """
        Fetch 1-minute OHLCV candles for an expired contract.

        Args:
            expired_instrument_key: Broker key (e.g., "NSE_FO|71706|28-08-2025")
            from_date: Start date in YYYY-MM-DD format
            to_date: End date in YYYY-MM-DD format
            interval: Candle interval (default: "1minute")

        Returns:
            List of candles: [[timestamp, open, high, low, close, volume, oi], ...]
        """
        path = (
            f"/expired-instruments/historical-candle"
            f"/{expired_instrument_key}/{interval}/{to_date}/{from_date}"
        )
        logger.debug(f"Fetching history for {expired_instrument_key} {from_date}→{to_date}")
        data = self._get(path)
        if data is None:
            return []
        candles = data.get("data", {}).get("candles", [])
        logger.debug(f"Received {len(candles)} candles for {expired_instrument_key}")
        return candles
