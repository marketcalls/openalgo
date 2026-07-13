"""
Timeseries Service — Generic Multi-Symbol History Fetcher

A symbol-agnostic service that fetches intraday/historical candle data
for any list of symbols and returns aligned columnar arrays.

Design principles:
  - No knowledge of CE/PE/FUT or any option-specific logic.
  - Frontend drives all parameters (symbols, interval, date range).
  - Frontend is responsible for classification (CE/PE/FUT) and aggregation.
  - Any tool (Trending OI, Strike vs OI, etc.) can reuse this service.

Response format (get_multi_symbol_history):
    columns:     ["oi", "ltp", "volume"]   — fixed column order
    timestamps:  [epoch1, epoch2, ...]      — shared aligned time grid
    symbol_data: { "SYM": [[oi...], [ltp...], [vol...]] }  — per-symbol arrays

Chain data (get_timeseries_chain_data):
    Returns option chain symbols with metadata (type, strike) so the
    frontend can build its own classification before calling history.
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

from database.token_db_enhanced import fno_search_symbols
from services.history_service import get_history
from services.option_chain_service import get_option_chain
from utils.constants import BSE_INDEX_SYMBOLS, NSE_INDEX_SYMBOLS
from utils.logging import get_logger


def _get_options_exchange(exchange: str) -> str:
    """Map underlying exchange to options exchange."""
    exchange_upper = exchange.upper()
    if exchange_upper in ("NSE_INDEX", "NSE"):
        return "NFO"
    elif exchange_upper in ("BSE_INDEX", "BSE"):
        return "BFO"
    return exchange_upper


def _find_futures_symbol(
    underlying: str, exchange: str, expiry_date: str, api_key: str
) -> dict | None:
    """
    Find the futures contract matching the underlying and expiry.

    Returns dict with 'symbol' and 'exchange' keys, or None.
    """
    try:
        options_exchange = _get_options_exchange(exchange)

        # Convert DDMMMYY to DD-MMM-YY for database lookup
        expiry_formatted = f"{expiry_date[:2]}-{expiry_date[2:5]}-{expiry_date[5:]}".upper()

        # Search for futures contract matching this expiry
        futures = fno_search_symbols(
            underlying=underlying,
            exchange=options_exchange,
            instrumenttype="FUT",
            expiry=expiry_formatted,
            limit=1,
        )

        if not futures:
            # Try without expiry filter to get nearest futures
            futures = fno_search_symbols(
                underlying=underlying,
                exchange=options_exchange,
                instrumenttype="FUT",
                limit=10,
            )
            if not futures:
                logger.warning(f"No futures contracts found for {underlying} on {options_exchange}")
                return None

            # Sort by expiry to get nearest
            def parse_expiry(exp_str: str) -> datetime:
                try:
                    return datetime.strptime(exp_str, "%d-%b-%y")
                except (ValueError, TypeError):
                    return datetime.max

            futures.sort(key=lambda f: parse_expiry(f.get("expiry", "")))

        return {"symbol": futures[0]["symbol"], "exchange": futures[0]["exchange"]}
    except Exception as e:
        logger.warning(f"Error finding futures symbol: {e}")
        return None


def _fetch_symbol_history_batch(
    symbols: list[dict],
    interval: str,
    start_date: str,
    end_date: str,
    api_key: str,
) -> dict[str, list[dict]]:
    """
    Fetch history for multiple symbols in parallel with transient-error retry.

    Rate limiting is handled by history_service._enforce_rate_limit() — a global
    0.35s minimum interval between broker history calls.  No per-fetch delay is
    needed here; the existing rate limiter already paces at ~3 req/sec.

    Transient errors (429, 502-504, connection failures) are retried; 4xx errors
    and permanent failures fail fast to avoid waiting on invalid symbols.

    Args:
        symbols:    List of dicts, each with 'symbol' and 'exchange' keys.
                    Any extra keys (type, strike, etc.) are ignored here.
        interval:   Candle interval passed to broker ("1m", "3m", "5m", etc.)
        start_date: Start date in YYYY-MM-DD format
        end_date:   End date in YYYY-MM-DD format
        api_key:    OpenAlgo API key for broker authentication

    Returns:
        Dict mapping symbol name -> list of candle dicts:
        [ {"timestamp": int, "ltp": float, "oi": int, "volume": int}, ... ]
    """
    MAX_WORKERS = 5
    MAX_RETRIES = 2
    RETRY_BASE_DELAY = 1.5

    def _is_transient(status_code: int | None, exc: Exception | None) -> bool:
        if exc is not None:
            return isinstance(exc, (ConnectionError, TimeoutError, OSError))
        return status_code in (429, 502, 503, 504)

    def _fetch_one(symbol_info: dict) -> tuple[str, str, list[dict]]:
        symbol = symbol_info["symbol"]
        exchange = symbol_info["exchange"]

        for attempt in range(MAX_RETRIES + 1):
            try:
                success, resp, status_code = get_history(
                    symbol=symbol,
                    exchange=exchange,
                    interval=interval,
                    start_date=start_date,
                    end_date=end_date,
                    api_key=api_key,
                )
                if success and resp.get("data"):
                    data = [
                        {
                            "timestamp": c.get("timestamp"),
                            "ltp": c.get("close", 0),
                            "oi": c.get("oi", 0) or 0,
                            "volume": c.get("volume", 0) or 0,
                        }
                        for c in resp["data"]
                    ]
                    return symbol, exchange, data

                if attempt < MAX_RETRIES and _is_transient(status_code, None):
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        f"Transient error {symbol} (status={status_code}), "
                        f"retry {attempt + 1} after {delay}s"
                    )
                    time.sleep(delay)
                    continue

                if attempt >= MAX_RETRIES or not _is_transient(status_code, None):
                    if status_code not in (400, 404):
                        logger.warning(
                            f"Error fetching {symbol} (status={status_code})"
                        )
                return symbol, exchange, []
            except Exception as e:
                if attempt < MAX_RETRIES and _is_transient(None, e):
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        f"Transient exception {symbol}, "
                        f"retry {attempt + 1} after {delay}s: {e}"
                    )
                    time.sleep(delay)
                    continue
                logger.warning(f"Error fetching history for {symbol}: {e}")
                return symbol, exchange, []
        return symbol, exchange, []

    results: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        fut_map = {executor.submit(_fetch_one, s): s for s in symbols}
        for fut in as_completed(fut_map):
            try:
                sym, exch, data = fut.result()
                results[f"{sym}:{exch}"] = data
            except Exception as e:
                s = fut_map[fut]
                logger.warning(f"Unhandled error fetching {s.get('symbol')}: {e}")

    return results


def get_timeseries_chain_data(
    underlying: str,
    exchange: str,
    expiry_date: str,
    strike_count: int,
    api_key: str,
) -> tuple[bool, dict[str, Any], int]:
    """
    Get option chain with symbols for timeseries analysis.
    
    Returns the option chain with symbol information for frontend to request
    the specific symbols needed for timeseries data.
    
    Args:
        underlying: Underlying symbol (e.g., NIFTY, BANKNIFTY)
        exchange: Exchange (NSE_INDEX, BSE_INDEX)
        expiry_date: Expiry in DDMMMYY format
        strike_count: Number of strikes above/below ATM
        api_key: OpenAlgo API key
    
    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        # Get option chain
        success, chain_response, status_code = get_option_chain(
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry_date,
            strike_count=strike_count,
            api_key=api_key,
        )

        if not success:
            return False, chain_response, status_code

        options_exchange = _get_options_exchange(exchange)

        # Find futures symbol
        futures_info = _find_futures_symbol(underlying, exchange, expiry_date, api_key)

        # Extract symbols from chain
        symbols = []
        chain = chain_response.get("chain", [])
        lot_size = None

        for item in chain:
            ce = item.get("ce")
            pe = item.get("pe")

            if ce and ce.get("symbol"):
                symbols.append({
                    "symbol": ce["symbol"],
                    "exchange": options_exchange,
                    "type": "CE",
                    "strike": item["strike"],
                })
                if lot_size is None and ce.get("lotsize"):
                    lot_size = ce["lotsize"]

            if pe and pe.get("symbol"):
                symbols.append({
                    "symbol": pe["symbol"],
                    "exchange": options_exchange,
                    "type": "PE",
                    "strike": item["strike"],
                })
                if lot_size is None and pe.get("lotsize"):
                    lot_size = pe["lotsize"]

        return (
            True,
            {
                "status": "success",
                "underlying": chain_response.get("underlying", underlying),
                "underlying_ltp": chain_response.get("underlying_ltp"),
                "atm_strike": chain_response.get("atm_strike"),
                "lot_size": lot_size or 1,
                "expiry_date": expiry_date,
                "futures": futures_info,
                "symbols": symbols,
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error in get_timeseries_chain_data: {e}")
        return (
            False,
            {"status": "error", "message": "Error fetching chain data"},
            500,
        )


def get_multi_symbol_history(
    symbols: list[dict],
    interval: str,
    start_date: str,
    end_date: str,
    api_key: str,
) -> tuple[bool, dict[str, Any], int]:
    """
    Fetch history for a list of symbols and return aligned columnar data.

    This is the main public API for any tool that needs multi-symbol historical
    data.  It is completely symbol-agnostic — it does not know or care whether
    a symbol is a CE option, PE option, futures contract, equity, or index.

    Workflow:
        1. Fetch per-symbol candle history via _fetch_symbol_history_batch.
        2. Collect all unique timestamps across every symbol.
        3. Build a shared time grid and fill each symbol's data into
           fixed-length columnar arrays aligned to that grid.

    Request (from frontend / caller):
        symbols:    [ {"symbol": "NIFTY..CE", "exchange": "NFO"}, ... ]
        interval:   "1m" | "3m" | "5m" | "15m" | "1h"
        start_date: "YYYY-MM-DD"
        end_date:   "YYYY-MM-DD"
        api_key:    OpenAlgo API key

    Response:
        {
            "status":      "success",
            "columns":     ["oi", "ltp", "volume"],
            "timestamps":  [epoch1, epoch2, ...],
            "symbol_data": {
                "NIFTY..CE": [[oi0, oi1, ...], [ltp0, ...], [vol0, ...]],
                "NIFTY..PE": [[...], [...], [...]],
                ...
            }
        }

    Notes:
        - Column order in symbol_data arrays matches the "columns" array.
        - Timestamps are Unix epoch integers (sorted ascending).
        - Missing data points are filled with 0.
        - The caller (frontend) is responsible for building symbols_meta
          (CE/PE/FUT classification, strike prices, etc.) from chain data.

    Args:
        symbols:    List of dicts, each with 'symbol' and 'exchange' keys.
        interval:   Candle interval ("1m", "3m", "5m", "15m", "1h").
        start_date: Start date in YYYY-MM-DD format.
        end_date:   End date in YYYY-MM-DD format.
        api_key:    OpenAlgo API key for broker authentication.

    Returns:
        Tuple of (success: bool, response_data: dict, http_status: int)
    """
    try:
        if not symbols:
            return (
                False,
                {"status": "error", "message": "No symbols provided"},
                400,
            )

        # ── 1. Fetch raw candle data for every symbol ──
        history_data = _fetch_symbol_history_batch(
            symbols=symbols,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            api_key=api_key,
        )

        # ── 2. Build shared timestamp grid ──
        all_timestamps: set[int] = set()
        for sym_candles in history_data.values():
            for candle in sym_candles:
                ts = candle.get("timestamp")
                if ts is not None:
                    all_timestamps.add(ts)

        sorted_timestamps = sorted(all_timestamps)

        if not sorted_timestamps:
            return (
                True,
                {
                    "status": "success",
                    "columns": ["oi", "ltp", "volume"],
                    "timestamps": [],
                    "symbol_data": {},
                    "message": "No data available for the selected date range",
                },
                200,
            )

        # ── 3. Align per-symbol data into columnar arrays ──
        ts_index = {ts: idx for idx, ts in enumerate(sorted_timestamps)}
        num_ts = len(sorted_timestamps)

        symbol_data: dict[str, list[list]] = {}

        for sym_info in symbols:
            sym = sym_info["symbol"]

            # Column arrays: [oi_array, ltp_array, volume_array]
            oi_arr = [0] * num_ts
            ltp_arr = [0.0] * num_ts
            vol_arr = [0] * num_ts

            exch = sym_info["exchange"]
            lookup_key = f"{sym}:{exch}"

            for candle in history_data.get(lookup_key, []):
                ts = candle.get("timestamp")
                if ts is not None and ts in ts_index:
                    idx = ts_index[ts]
                    oi_arr[idx] = candle.get("oi", 0)
                    ltp_arr[idx] = candle.get("ltp", 0)
                    vol_arr[idx] = candle.get("volume", 0)

            symbol_data[lookup_key] = [oi_arr, ltp_arr, vol_arr]

        return (
            True,
            {
                "status": "success",
                "columns": ["oi", "ltp", "volume"],
                "timestamps": sorted_timestamps,
                "symbol_data": symbol_data,
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error in get_multi_symbol_history: {e}")
        return (
            False,
            {"status": "error", "message": "Error fetching symbol history"},
            500,
        )
