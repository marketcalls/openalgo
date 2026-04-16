# sandbox/quote_provider.py
"""
Quote Provider Abstraction for Sandbox

Provides a unified interface for fetching quotes in sandbox mode.
Two implementations:
- LiveQuoteProvider: uses WebSocket/broker API (existing behavior)
- ReplayQuoteProvider: reads from DuckDB historical data at replay timestamp
"""

import time

from utils.logging import get_logger

logger = get_logger(__name__)


class QuoteProvider:
    """Abstract base for quote providers."""

    def get_ltp(self, symbol: str, exchange: str) -> float | None:
        """Get last traded price for a symbol."""
        raise NotImplementedError

    def get_quote(self, symbol: str, exchange: str) -> dict | None:
        """Get full quote for a symbol."""
        raise NotImplementedError

    def get_quotes_batch(self, symbols: list[tuple[str, str]]) -> dict:
        """
        Get quotes for multiple symbols.
        Returns dict mapping (symbol, exchange) -> quote dict.
        """
        raise NotImplementedError


class LiveQuoteProvider(QuoteProvider):
    """
    Live quote provider using WebSocket and broker API.
    Wraps existing quote fetching behavior from position_manager/execution_engine.
    """

    WEBSOCKET_DATA_MAX_AGE = 5  # seconds

    def get_ltp(self, symbol: str, exchange: str) -> float | None:
        quote = self.get_quote(symbol, exchange)
        if quote:
            return quote.get("ltp")
        return None

    def get_quote(self, symbol: str, exchange: str) -> dict | None:
        """Try WebSocket first, then REST API."""
        # Try WebSocket
        ws_quotes = self._fetch_from_websocket([(symbol, exchange)])
        quote = ws_quotes.get((symbol, exchange))
        if quote:
            return quote

        # Fallback to REST API
        return self._fetch_single_quote(symbol, exchange)

    def get_quotes_batch(self, symbols: list[tuple[str, str]]) -> dict:
        """Fetch quotes via WebSocket first, then multiquotes for missing."""
        if not symbols:
            return {}

        # Try WebSocket first
        quote_cache = self._fetch_from_websocket(symbols)

        # Find missing symbols
        missing = [s for s in symbols if s not in quote_cache or quote_cache[s] is None]

        if missing:
            # Fallback to multiquotes
            api_quotes = self._fetch_multiquotes(missing)
            quote_cache.update(api_quotes)

        return quote_cache

    def _fetch_from_websocket(self, symbols_list):
        """Fetch LTP from WebSocket (MarketDataService)."""
        quote_cache = {}
        try:
            from services.market_data_service import get_market_data_service

            market_data_service = get_market_data_service()
            current_time = time.time()

            for symbol, exchange in symbols_list:
                data = market_data_service.get_all_data(symbol, exchange)
                if data:
                    last_update = data.get("last_update", 0)
                    age = current_time - last_update
                    if age <= self.WEBSOCKET_DATA_MAX_AGE:
                        ltp_data = data.get("ltp", {})
                        ltp = ltp_data.get("value") if isinstance(ltp_data, dict) else None
                        if ltp and ltp > 0:
                            quote_cache[(symbol, exchange)] = {"ltp": ltp}
        except Exception as e:
            logger.debug(f"Error fetching from WebSocket: {e}")

        return quote_cache

    def _fetch_single_quote(self, symbol, exchange):
        """Fetch quote via REST API."""
        try:
            from database.auth_db import ApiKeys, decrypt_token
            from services.quotes_service import get_quotes

            api_key_obj = ApiKeys.query.first()
            if not api_key_obj:
                return None

            api_key = decrypt_token(api_key_obj.api_key_encrypted)
            success, response, status_code = get_quotes(
                symbol=symbol, exchange=exchange, api_key=api_key
            )

            if success and "data" in response:
                return response["data"]
            return None
        except Exception as e:
            logger.debug(f"Error fetching quote for {symbol}: {e}")
            return None

    def _fetch_multiquotes(self, symbols_list):
        """Fetch quotes via multiquotes REST API."""
        quote_cache = {}
        try:
            from database.auth_db import ApiKeys, decrypt_token
            from services.quotes_service import get_multiquotes

            api_key_obj = ApiKeys.query.first()
            if not api_key_obj:
                return quote_cache

            api_key = decrypt_token(api_key_obj.api_key_encrypted)
            symbols_payload = [
                {"symbol": symbol, "exchange": exchange}
                for symbol, exchange in symbols_list
            ]

            success, response, status_code = get_multiquotes(
                symbols=symbols_payload, api_key=api_key
            )

            if success and "results" in response:
                for result in response["results"]:
                    symbol = result.get("symbol")
                    exchange = result.get("exchange")
                    if "data" in result and result["data"]:
                        quote_cache[(symbol, exchange)] = result["data"]
        except Exception as e:
            logger.debug(f"Error in multiquotes fetch: {e}")

        return quote_cache


class ReplayQuoteProvider(QuoteProvider):
    """
    Replay quote provider that reads from DuckDB historical data.
    Uses data uploaded via bhavcopy/intraday ZIP imports.
    """

    def __init__(self, get_current_ts_fn):
        """
        Args:
            get_current_ts_fn: Callable that returns current replay timestamp (epoch seconds)
        """
        self._get_current_ts = get_current_ts_fn

    def get_ltp(self, symbol: str, exchange: str) -> float | None:
        quote = self.get_quote(symbol, exchange)
        if quote:
            return quote.get("ltp")
        return None

    def get_quote(self, symbol: str, exchange: str) -> dict | None:
        """Get quote from DuckDB at current replay timestamp."""
        from database.historify_db import get_replay_quote

        at_ts = self._get_current_ts()
        if at_ts is None:
            return None

        return get_replay_quote(symbol, exchange, at_ts)

    def get_quotes_batch(self, symbols: list[tuple[str, str]]) -> dict:
        """Get quotes for multiple symbols from DuckDB."""
        from database.historify_db import get_replay_quotes_batch

        at_ts = self._get_current_ts()
        if at_ts is None:
            return {}

        return get_replay_quotes_batch(symbols, at_ts)


def get_quote_provider() -> QuoteProvider:
    """
    Get the appropriate quote provider based on current mode.

    Decision logic:
    - If analyzer (paper) mode is OFF → LiveQuoteProvider always.
    - If analyzer mode is ON:
        - paper_price_source == "REPLAY" → ReplayQuoteProvider (uses DuckDB at current replay ts).
          If replay clock is not running / not configured, the provider will return None for quotes
          (orders remain pending) and a warning is logged.
        - paper_price_source == "LIVE" (default) → LiveQuoteProvider.
    """
    try:
        from database.settings_db import get_analyze_mode, get_paper_price_source

        if get_analyze_mode():
            source = get_paper_price_source()
            if source == "REPLAY":
                from services.replay_service import get_replay_session

                session = get_replay_session()
                if session.get("current_ts") is None:
                    logger.warning(
                        "paper_price_source=REPLAY but replay clock has no current_ts "
                        "(not configured or not started). Quotes will be unavailable until replay is started."
                    )
                return ReplayQuoteProvider(
                    get_current_ts_fn=lambda: get_replay_session().get("current_ts")
                )
    except Exception as e:
        logger.debug(f"Error checking quote provider mode: {e}")

    return LiveQuoteProvider()
