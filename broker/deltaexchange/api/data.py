# api/data.py
# Delta Exchange market data — Quotes, Depth, History
#
# Public endpoints (no auth required):
#   GET /v2/tickers/{symbol}              → quotes / depth OHLCV
#   GET /v2/l2orderbook/{product_id}      → 5-level order book
#   GET /v2/history/candles               → OHLCV candles
#
# Reference: https://docs.delta.exchange

import os
from datetime import datetime, timedelta

import pandas as pd

from broker.deltaexchange.api.baseurl import BASE_URL
from database.token_db import get_token
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def _f(value, default=0.0):
    """Safe float cast."""
    try:
        return float(value) if value is not None else default
    except (ValueError, TypeError):
        return default


def _i(value, default=0):
    """Safe int cast."""
    try:
        return int(float(value)) if value is not None else default
    except (ValueError, TypeError):
        return default


def _get_ticker(symbol: str) -> dict:
    """
    Fetch ticker for a single symbol via GET /v2/tickers/{symbol}.
    Returns the 'result' dict, or raises on failure.
    The result is a DICT (not a list) for the single-symbol endpoint.
    """
    url = f"{BASE_URL}/v2/tickers/{symbol}"
    client = get_httpx_client()
    resp = client.get(url, headers={"Accept": "application/json"}, timeout=15.0)

    if resp.status_code != 200:
        raise Exception(f"Ticker HTTP {resp.status_code} for {symbol}: {resp.text[:200]}")

    data = resp.json()
    if not data.get("success", False):
        raise Exception(f"Ticker API error for {symbol}: {data.get('error', data)}")

    result = data.get("result", {})
    # Guard: single-symbol endpoint must return a dict
    if not isinstance(result, dict):
        raise Exception(
            f"Unexpected ticker result type for {symbol}: "
            f"expected dict, got {type(result).__name__}"
        )
    return result


def _get_l2orderbook(product_id: int) -> dict:
    """
    Fetch 5-level order book via GET /v2/l2orderbook/{product_id}.

    Expected response shape:
        {
          "success": true,
          "result": {
            "buy":  [{"price": "67000.00", "size": 1500, "depth": 1}, ...],
            "sell": [{"price": "67001.00", "size":  800, "depth": 1}, ...]
          }
        }

    Returns the 'result' dict (with 'buy'/'sell' lists), or raises on failure.
    """
    url = f"{BASE_URL}/v2/l2orderbook/{product_id}"
    client = get_httpx_client()
    resp = client.get(url, headers={"Accept": "application/json"}, timeout=15.0)

    if resp.status_code != 200:
        raise Exception(
            f"L2 orderbook HTTP {resp.status_code} for product_id={product_id}: "
            f"{resp.text[:200]}"
        )

    data = resp.json()
    if not data.get("success", False):
        raise Exception(
            f"L2 orderbook API error for product_id={product_id}: {data.get('error', data)}"
        )

    result = data.get("result", {})
    if not isinstance(result, dict):
        raise Exception(
            f"Unexpected l2orderbook result type: expected dict, got {type(result).__name__}"
        )
    return result


class BrokerData:
    """
    Delta Exchange market data provider.

    All public endpoints are called without authentication headers.
    The auth_token is stored but only used if a future authenticated
    data endpoint is needed (e.g. personal trade history).
    """

    # Delta Exchange supported candle resolutions mapped from OpenAlgo interval codes.
    # The API caps responses to ~4,000 candles (most recent) per request regardless
    # of the requested range. CHUNK_DAYS below are sized accordingly.
    TIMEFRAME_MAP = {
        "1m":  "1m",
        "3m":  "3m",
        "5m":  "5m",
        "15m": "15m",
        "30m": "30m",
        "1h":  "1h",
        "2h":  "2h",
        "4h":  "4h",
        "6h":  "6h",
        "1d":  "1d",
        "D":   "1d",   # alias
        "1w":  "1w",
        "W":   "1w",   # alias
    }

    def __init__(self, auth_token: str):
        """Initialise with the api_key stored in the OpenAlgo auth DB."""
        self.auth_token = auth_token
        # Keep timeframe_map as an instance attribute for get_intervals() compatibility
        self.timeframe_map = self.TIMEFRAME_MAP

    # ──────────────────────────────────────────────────────────────────────────
    # get_quotes
    # ──────────────────────────────────────────────────────────────────────────

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """
        Fetch real-time quote for a single contract.

        Calls: GET /v2/tickers/{brsymbol}

        Field mapping (ticker result → OpenAlgo):
            ltp        ← mark_price          (string → float)
            open       ← open                (number)
            high       ← high                (number)
            low        ← low                 (number)
            volume     ← volume              (number)
            prev_close ← close               (number, prior session close)
            oi         ← oi                  (string → float)
            bid        ← quotes.best_bid     (string → float)
            ask        ← quotes.best_ask     (string → float)

        Returns:
            dict with ltp, open, high, low, volume, prev_close, oi, bid, ask
        """
        try:
            br_symbol = self._get_br_symbol(symbol, exchange)
            logger.info(f"[DeltaExchange] get_quotes: {symbol} → {br_symbol}")

            ticker = _get_ticker(br_symbol)
            quotes = ticker.get("quotes") or {}

            result = {
                "ltp":        _f(ticker.get("mark_price", 0)),
                "open":       _f(ticker.get("open", 0)),
                "high":       _f(ticker.get("high", 0)),
                "low":        _f(ticker.get("low", 0)),
                "volume":     _i(ticker.get("volume", 0)),
                "prev_close": _f(ticker.get("close", 0)),
                "oi":         _f(ticker.get("oi", 0)),
                "bid":        _f(quotes.get("best_bid", 0)),
                "ask":        _f(quotes.get("best_ask", 0)),
            }

            logger.debug(f"[DeltaExchange] Quotes for {br_symbol}: ltp={result['ltp']}")
            return result

        except Exception as e:
            logger.error(f"[DeltaExchange] get_quotes error for {symbol}: {e}")
            raise Exception(f"Error fetching quotes for {symbol}: {e}")

    # ──────────────────────────────────────────────────────────────────────────
    # get_depth
    # ──────────────────────────────────────────────────────────────────────────

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """
        Fetch 5-level market depth for a single contract.

        Two API calls:
          1. GET /v2/tickers/{brsymbol}          → OHLCV + LTP + OI
          2. GET /v2/l2orderbook/{product_id}    → 5-level bids and asks

        L2 orderbook 'buy'/'sell' are already sorted best-first by the exchange;
        we take up to 5 levels from each side.

        L2 orderbook item: {"price": "67000.00", "size": 1500, "depth": 1}

        Returns dict with:
            bids, asks          – list of 5 × {"price": float, "quantity": int}
            ltp, ltq            – last trade price / qty (ltq = 0, not in ticker)
            volume, open, high, low, prev_close, oi
            totalbuyqty, totalsellqty
        """
        try:
            br_symbol = self._get_br_symbol(symbol, exchange)
            logger.info(f"[DeltaExchange] get_depth: {symbol} → {br_symbol}")

            # ── call 1: ticker ─────────────────────────────────────────────
            ticker = _get_ticker(br_symbol)
            product_id = _i(ticker.get("product_id", 0))

            ltp        = _f(ticker.get("mark_price", 0))
            open_p     = _f(ticker.get("open", 0))
            high_p     = _f(ticker.get("high", 0))
            low_p      = _f(ticker.get("low", 0))
            prev_close = _f(ticker.get("close", 0))
            volume     = _i(ticker.get("volume", 0))
            oi         = _f(ticker.get("oi", 0))

            # Empty depth template (used as fallback if l2 call fails)
            empty_side = [{"price": 0.0, "quantity": 0} for _ in range(5)]

            if not product_id:
                logger.warning(
                    f"[DeltaExchange] No product_id in ticker for {br_symbol}; "
                    f"returning empty depth"
                )
                return {
                    "bids": empty_side,
                    "asks": empty_side,
                    "ltp": ltp, "ltq": 0,
                    "volume": volume, "open": open_p, "high": high_p,
                    "low": low_p, "prev_close": prev_close, "oi": oi,
                    "totalbuyqty": 0, "totalsellqty": 0,
                }

            # ── call 2: l2 orderbook ────────────────────────────────────────
            try:
                book = _get_l2orderbook(product_id)
                buy_levels  = book.get("buy",  []) or []
                sell_levels = book.get("sell", []) or []

                def _parse_level(level_list, n=5):
                    out = []
                    for lvl in level_list[:n]:
                        out.append({
                            "price":    _f(lvl.get("price", 0)),
                            "quantity": _i(lvl.get("size",  0)),
                        })
                    # Pad to exactly n levels
                    while len(out) < n:
                        out.append({"price": 0.0, "quantity": 0})
                    return out

                bids = _parse_level(buy_levels)
                asks = _parse_level(sell_levels)

                totalbuyqty  = sum(lvl["quantity"] for lvl in bids)
                totalsellqty = sum(lvl["quantity"] for lvl in asks)

            except Exception as book_err:
                logger.warning(
                    f"[DeltaExchange] L2 orderbook failed for product_id={product_id}: "
                    f"{book_err} — returning empty depth"
                )
                bids = asks = empty_side
                totalbuyqty = totalsellqty = 0

            result = {
                "bids": bids,
                "asks": asks,
                "ltp":          ltp,
                "ltq":          0,      # last traded qty not in ticker response
                "volume":       volume,
                "open":         open_p,
                "high":         high_p,
                "low":          low_p,
                "prev_close":   prev_close,
                "oi":           oi,
                "totalbuyqty":  totalbuyqty,
                "totalsellqty": totalsellqty,
            }

            logger.debug(
                f"[DeltaExchange] Depth for {br_symbol}: "
                f"ltp={ltp} bids[0]={bids[0]} asks[0]={asks[0]}"
            )
            return result

        except Exception as e:
            logger.error(f"[DeltaExchange] get_depth error for {symbol}: {e}")
            raise Exception(f"Error fetching market depth for {symbol}: {e}")

    # ──────────────────────────────────────────────────────────────────────────
    # get_history
    # ──────────────────────────────────────────────────────────────────────────

    # Delta Exchange caps candles returned per request to 2,000 (most recent).
    # Chunk sizes are derived as: floor(2000 / candles_per_day) with a safety margin.
    #   1m:  1440/day → cap=1.39d → 1 day
    #   3m:   480/day → cap=4.2d  → 3 days
    #   5m:   288/day → cap=6.9d  → 6 days
    #   15m:   96/day → cap=20.8d → 20 days
    #   30m:   48/day → cap=41.7d → 40 days
    #   1h+:   24/day → cap=83d+  → 60 days
    #   1d/1w: unlimited          → 0 (no chunking)
    CHUNK_DAYS = {
        "1m":  1,
        "3m":  7,
        "5m":  12,
        "15m": 30,
        "30m": 60,
        "1h":  90,
        "2h":  90,
        "4h":  90,
        "6h":  90,
        "1d":  0,   # 0 = no chunking
        "1w":  0,
    }

    def get_history(
        self,
        symbol: str,
        exchange: str,
        interval: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV candles from Delta Exchange, chunking the date range as
        needed to work around the API's per-request candle cap.

        Endpoint: GET /v2/history/candles
        Params:
            symbol      – contract symbol (br_symbol, e.g. "BTCUSD")
            resolution  – Delta candle resolution (e.g. "1m", "1h", "1d")
            start       – Unix epoch seconds (start of first candle)
            end         – Unix epoch seconds (end of last candle)

        Response shape (array-of-arrays):
            {
              "success": true,
              "result": [
                [timestamp_seconds, open, high, low, close, volume],
                ...
              ]
            }

        Delta may also return named dicts; both formats are handled.

        Returns:
            pd.DataFrame with columns [timestamp, open, high, low, close, volume, oi]
            Sorted ascending, duplicates removed.
        """
        try:
            if interval not in self.TIMEFRAME_MAP:
                supported = list(self.TIMEFRAME_MAP.keys())
                raise Exception(
                    f"Unsupported interval '{interval}'. "
                    f"Supported: {', '.join(supported)}"
                )

            resolution = self.TIMEFRAME_MAP[interval]
            br_symbol  = self._get_br_symbol(symbol, exchange)

            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt   = datetime.strptime(end_date,   "%Y-%m-%d")

            # Build list of (chunk_start_str, chunk_end_str) date pairs
            chunk_days = self.CHUNK_DAYS.get(resolution, 30)
            if chunk_days == 0:
                # No chunking needed for daily/weekly
                chunks = [(start_date, end_date)]
            else:
                chunks = []
                cursor = start_dt
                while cursor <= end_dt:
                    chunk_end = min(cursor + timedelta(days=chunk_days - 1), end_dt)
                    chunks.append((
                        cursor.strftime("%Y-%m-%d"),
                        chunk_end.strftime("%Y-%m-%d"),
                    ))
                    cursor = chunk_end + timedelta(days=1)

            logger.info(
                f"[DeltaExchange] get_history: {br_symbol} {resolution} "
                f"{start_date} → {end_date} ({len(chunks)} chunk(s))"
            )

            all_candles = []
            url    = f"{BASE_URL}/v2/history/candles"
            client = get_httpx_client()

            for chunk_start, chunk_end in chunks:
                start_ts = self._to_epoch(chunk_start, end_of_day=False)
                end_ts   = self._to_epoch(chunk_end,   end_of_day=True)

                params = {
                    "symbol":     br_symbol,
                    "resolution": resolution,
                    "start":      str(start_ts),
                    "end":        str(end_ts),
                }

                logger.debug(
                    f"[DeltaExchange] Chunk {chunk_start} → {chunk_end} "
                    f"({start_ts} → {end_ts})"
                )

                resp = client.get(
                    url,
                    params=params,
                    headers={"Accept": "application/json"},
                    timeout=30.0,
                )

                if resp.status_code != 200:
                    raise Exception(
                        f"History HTTP {resp.status_code} for {br_symbol}: {resp.text[:200]}"
                    )

                data = resp.json()
                if not data.get("success", False):
                    raise Exception(
                        f"History API error for {br_symbol}: {data.get('error', data)}"
                    )

                raw_candles = data.get("result", [])
                if not isinstance(raw_candles, list):
                    raise Exception(
                        f"Unexpected history result type: {type(raw_candles).__name__}"
                    )

                for candle in raw_candles:
                    try:
                        if isinstance(candle, list) and len(candle) >= 6:
                            # Array format: [timestamp, open, high, low, close, volume]
                            all_candles.append({
                                "timestamp": int(candle[0]),
                                "open":      _f(candle[1]),
                                "high":      _f(candle[2]),
                                "low":       _f(candle[3]),
                                "close":     _f(candle[4]),
                                "volume":    _i(candle[5]),
                                "oi":        _i(candle[6]) if len(candle) > 6 else 0,
                            })
                        elif isinstance(candle, dict):
                            # Named-field format (defensive fallback)
                            ts = candle.get("time", candle.get("timestamp", candle.get("t", 0)))
                            all_candles.append({
                                "timestamp": int(ts),
                                "open":      _f(candle.get("open",   candle.get("o", 0))),
                                "high":      _f(candle.get("high",   candle.get("h", 0))),
                                "low":       _f(candle.get("low",    candle.get("l", 0))),
                                "close":     _f(candle.get("close",  candle.get("c", 0))),
                                "volume":    _i(candle.get("volume", candle.get("v", 0))),
                                "oi":        _i(candle.get("oi", 0)),
                            })
                        else:
                            logger.warning(f"Unknown candle format: {candle}")
                    except Exception as candle_err:
                        logger.error(f"Error parsing candle {candle}: {candle_err}")
                        continue

                logger.debug(
                    f"[DeltaExchange] Chunk {chunk_start} → {chunk_end}: "
                    f"{len(raw_candles)} candles received"
                )

            if all_candles:
                df = pd.DataFrame(all_candles)
                df = (
                    df.sort_values("timestamp")
                    .drop_duplicates(subset=["timestamp"])
                    .reset_index(drop=True)
                )
                logger.info(
                    f"[DeltaExchange] History: {len(df)} candles for "
                    f"{br_symbol} @ {resolution} across {len(chunks)} chunk(s)"
                )
            else:
                df = pd.DataFrame(
                    columns=["timestamp", "open", "high", "low", "close", "volume", "oi"]
                )
                logger.warning(
                    f"[DeltaExchange] No candles returned for {br_symbol} @ {resolution}"
                )

            return df

        except Exception as e:
            logger.error(f"[DeltaExchange] get_history error for {symbol}: {e}")
            raise Exception(f"Error fetching historical data for {symbol}: {e}")

    # ──────────────────────────────────────────────────────────────────────────    # get_option_chain
    # ─────────────────────────────────────────────────────────────────────────────

    def get_option_chain(
        self,
        underlying: str,
        exchange: str = "CRYPTO",
        expiry: str | None = None,
    ) -> list[dict]:
        """
        Return all call and put options for a given underlying from the master
        contract DB, optionally filtered by expiry.

        This is a DB-only method (no REST call) and therefore works even when
        the market is closed.  Run ``master_contract_download()`` first to
        populate the DB.

        Args:
            underlying: The underlying symbol prefix, e.g. ``"BTC"``, ``"ETH"``.
                        Matched as a case-insensitive prefix of the canonical symbol.
            exchange:   OpenAlgo exchange code.  ``"CRYPTO"`` for all Delta
                        Exchange India listed options.
            expiry:     Optional expiry filter in ``"DD-MON-YY"`` format as
                        stored by the master DB, e.g. ``"28-FEB-25"``.
                        When ``None`` all expiries are returned.

        Returns:
            List of dicts with keys:
                symbol, brsymbol, token, instrumenttype (CE / PE),
                expiry, strike, lotsize, tick_size
            Sorted by (instrumenttype, expiry, strike).
        """
        from broker.deltaexchange.database.master_contract_db import SymToken

        try:
            query = SymToken.query.filter(
                SymToken.exchange == exchange,
                SymToken.instrumenttype.in_(["CE", "PE"]),
                SymToken.symbol.ilike(f"{underlying}%"),
            )
            if expiry:
                query = query.filter(SymToken.expiry == expiry.upper())

            rows = query.all()

            result = [
                {
                    "symbol":         r.symbol,
                    "brsymbol":       r.brsymbol,
                    "token":          r.token,
                    "instrumenttype": r.instrumenttype,
                    "expiry":         r.expiry,
                    "strike":         r.strike,
                    "lotsize":        r.lotsize,
                    "tick_size":      r.tick_size,
                }
                for r in rows
            ]

            # Sort: CE before PE, then chronologically by expiry, then by strike price.
            # Raw DD-MON-YY strings cannot be sorted alphabetically (month abbreviations
            # are not in calendar order: APR < AUG < ... < SEP); parse to date instead.
            def _expiry_sort_key(expiry_str):
                try:
                    return datetime.strptime(expiry_str, "%d-%b-%y").date()
                except (ValueError, TypeError):
                    return datetime.max.date()

            result.sort(key=lambda x: (x["instrumenttype"], _expiry_sort_key(x["expiry"]), x["strike"]))

            logger.info(
                f"[DeltaExchange] get_option_chain: {len(result)} strikes for "
                f"{underlying} @ {exchange}"
                + (f" expiry={expiry}" if expiry else "")
            )
            return result

        except Exception as exc:
            logger.error(f"[DeltaExchange] get_option_chain error: {exc}")
            return []

    # ─────────────────────────────────────────────────────────────────────────────    # get_intervals
    # ──────────────────────────────────────────────────────────────────────────

    def get_intervals(self) -> list:
        """
        Return the list of supported OpenAlgo interval codes for Delta Exchange.
        """
        return list(self.TIMEFRAME_MAP.keys())

    # ──────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _get_br_symbol(self, symbol: str, exchange: str) -> str:
        """
        Resolve OpenAlgo symbol → Delta Exchange contract symbol (brsymbol).

        On Delta Exchange, brsymbol == symbol for most contracts  (e.g. "BTCUSD").
        Falls back to the symbol itself if not found in the master contract DB.
        """
        from database.token_db import get_br_symbol
        br = get_br_symbol(symbol, exchange)
        if not br:
            logger.warning(
                f"[DeltaExchange] brsymbol not found for {symbol}/{exchange}, "
                f"using symbol as-is"
            )
            return symbol
        return br

    @staticmethod
    def _to_epoch(date_str: str, end_of_day: bool = False) -> int:
        """
        Convert a YYYY-MM-DD date string to a Unix epoch (seconds, UTC).
        Uses UTC midnight for start, UTC 23:59:59 for end.
        """
        import calendar
        fmt = "%Y-%m-%d %H:%M:%S"
        if end_of_day:
            dt = datetime.strptime(f"{date_str} 23:59:59", fmt)
        else:
            dt = datetime.strptime(f"{date_str} 00:00:00", fmt)
        # calendar.timegm interprets the struct_time as UTC regardless of local timezone
        return calendar.timegm(dt.timetuple())
