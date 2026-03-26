"""
Mudrex market data provider.

Quote data comes from the Mudrex REST API (GET /futures/{symbol}?is_symbol).
Order-book depth and OHLCV klines come from the Bybit public v5 API because
Mudrex does not expose these endpoints directly.  Mudrex and Bybit share the
same symbol naming convention (e.g. BTCUSDT, ETHUSDT).

NOTE: Bybit prices may differ slightly from Mudrex execution prices.
"""

import os
from datetime import datetime, timezone

import pandas as pd

from broker.mudrex.api.mudrex_http import mudrex_request
from database.token_db import get_br_symbol
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

BYBIT_BASE = "https://api.bybit.com"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _f(value, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (ValueError, TypeError):
        return default


def _i(value, default: int = 0) -> int:
    try:
        return int(float(value)) if value is not None else default
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Bybit helpers (public, no auth)
# ---------------------------------------------------------------------------

def _bybit_get(path: str, params: dict | None = None, timeout: float = 15.0) -> dict:
    """Send a GET to Bybit's public v5 API and return parsed JSON."""
    client = get_httpx_client()
    url = BYBIT_BASE + path
    try:
        resp = client.get(url, params=params, timeout=timeout)
        if resp.status_code != 200:
            logger.error(f"[Bybit] HTTP {resp.status_code}: {resp.text[:300]}")
            return {}
        return resp.json()
    except Exception as exc:
        logger.error(f"[Bybit] Request error: {exc}")
        return {}


# ---------------------------------------------------------------------------
# BrokerData class (matches interface expected by services layer)
# ---------------------------------------------------------------------------

class BrokerData:
    """Mudrex market data handler."""

    TIMEFRAME_MAP = {
        "1m":  "1",
        "3m":  "3",
        "5m":  "5",
        "15m": "15",
        "30m": "30",
        "1h":  "60",
        "2h":  "120",
        "4h":  "240",
        "6h":  "360",
        "12h": "720",
        "1d":  "D",
        "D":   "D",
        "1w":  "W",
        "W":   "W",
        "1M":  "M",
        "M":   "M",
    }

    CHUNK_DAYS = {
        "1m":  1,
        "3m":  3,
        "5m":  6,
        "15m": 20,
        "30m": 40,
        "1h":  60,
        "2h":  90,
        "4h":  90,
        "6h":  90,
        "12h": 90,
        "1d":  0,
        "D":   0,
        "1w":  0,
        "W":   0,
        "1M":  0,
        "M":   0,
    }

    def __init__(self, auth_token: str):
        self.auth_token = auth_token
        self.timeframe_map = self.TIMEFRAME_MAP

    # ── get_quotes ─────────────────────────────────────────────────────────

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """Fetch real-time quote from Mudrex GET /futures/{symbol}?is_symbol.

        Maps:
            ltp        ← price
            open       ← last_day_price (approx — Mudrex has no intraday open)
            high       ← 1d_high
            low        ← 1d_low
            volume     ← 1d_volume (or volume)
            prev_close ← last_day_price
        """
        br_symbol = get_br_symbol(symbol, exchange) or symbol
        logger.info(f"[Mudrex] get_quotes: {symbol} → {br_symbol}")

        data = mudrex_request(
            f"/futures/{br_symbol}?is_symbol", method="GET", auth=self.auth_token
        )

        if not data.get("success"):
            raise Exception(f"Failed to fetch quote for {br_symbol}: {data}")

        d = data.get("data", {})
        return {
            "ltp":        _f(d.get("price")),
            "open":       _f(d.get("last_day_price")),
            "high":       _f(d.get("1d_high")),
            "low":        _f(d.get("1d_low")),
            "volume":     _i(d.get("1d_volume") or d.get("volume")),
            "prev_close": _f(d.get("last_day_price")),
            "oi":         0.0,
            "bid":        0.0,
            "ask":        0.0,
        }

    # ── get_depth (Bybit) ─────────────────────────────────────────────────

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """Fetch 5-level order book from Bybit public API.

        Bybit endpoint: GET /v5/market/orderbook?category=linear&symbol={}&limit=5
        """
        br_symbol = get_br_symbol(symbol, exchange) or symbol
        logger.info(f"[Mudrex] get_depth via Bybit: {symbol} → {br_symbol}")

        resp = _bybit_get("/v5/market/orderbook", params={
            "category": "linear",
            "symbol": br_symbol,
            "limit": "5",
        })

        result_data = resp.get("result", {})
        raw_bids = result_data.get("b", [])
        raw_asks = result_data.get("a", [])

        def _parse_levels(levels):
            out = []
            for lvl in levels[:5]:
                out.append({"price": _f(lvl[0]), "quantity": _f(lvl[1])})
            while len(out) < 5:
                out.append({"price": 0.0, "quantity": 0})
            return out

        bids = _parse_levels(raw_bids)
        asks = _parse_levels(raw_asks)

        # Try to get LTP from Mudrex for consistency
        try:
            quotes = self.get_quotes(symbol, exchange)
            ltp = quotes.get("ltp", 0.0)
            volume = quotes.get("volume", 0)
            open_p = quotes.get("open", 0.0)
            high_p = quotes.get("high", 0.0)
            low_p = quotes.get("low", 0.0)
            prev_close = quotes.get("prev_close", 0.0)
        except Exception:
            ltp = open_p = high_p = low_p = prev_close = 0.0
            volume = 0

        return {
            "bids": bids,
            "asks": asks,
            "ltp": ltp,
            "ltq": 0,
            "volume": volume,
            "open": open_p,
            "high": high_p,
            "low": low_p,
            "prev_close": prev_close,
            "oi": 0.0,
            "totalbuyqty": sum(b["quantity"] for b in bids),
            "totalsellqty": sum(a["quantity"] for a in asks),
        }

    # ── get_history (Bybit klines) ────────────────────────────────────────

    def get_history(
        self,
        symbol: str,
        exchange: str,
        interval: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """Fetch OHLCV from Bybit /v5/market/kline, chunked by date range.

        Bybit returns newest-first; we reverse to ascending order.
        """
        br_symbol = get_br_symbol(symbol, exchange) or symbol
        bybit_interval = self.TIMEFRAME_MAP.get(interval)
        if bybit_interval is None:
            raise ValueError(f"Unsupported interval: {interval}")

        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc
        )

        start_ms = int(start_dt.timestamp() * 1000)
        end_ms = int(end_dt.timestamp() * 1000)

        all_candles: list[dict] = []
        chunk_days = self.CHUNK_DAYS.get(interval, 0)

        if chunk_days <= 0:
            all_candles = self._fetch_kline_range_paginated(
                br_symbol, bybit_interval, start_ms, end_ms
            )
        else:
            chunk_ms = chunk_days * 86400 * 1000
            cursor = start_ms
            while cursor < end_ms:
                chunk_end = min(cursor + chunk_ms, end_ms)
                batch = self._fetch_kline_range_paginated(
                    br_symbol, bybit_interval, cursor, chunk_end
                )
                all_candles.extend(batch)
                cursor = chunk_end + 1

        if not all_candles:
            return pd.DataFrame(
                columns=["timestamp", "open", "high", "low", "close", "volume", "oi"]
            )

        df = pd.DataFrame(all_candles)
        df = (
            df.sort_values("timestamp")
            .drop_duplicates(subset=["timestamp"])
            .reset_index(drop=True)
        )
        df["oi"] = 0
        # Match Delta / history_service contract: include epoch-ms ``timestamp`` for joins/resampling
        return df[["timestamp", "open", "high", "low", "close", "volume", "oi"]]

    _MAX_KLINE_PER_REQUEST = 200
    _MAX_KLINE_PAGES = 500  # safety cap (~100k bars per range)

    def _fetch_kline_range_paginated(
        self, symbol: str, interval: str, start_ms: int, end_ms: int
    ) -> list[dict]:
        """Fetch all klines in ``[start_ms, end_ms]`` from Bybit.

        Bybit caps each request at 200 candles; responses are newest-first.
        Paginate by moving ``end`` backward until the oldest candle reaches
        ``start_ms`` or the API returns no further rows.
        """
        all_candles: list[dict] = []
        cur_end = end_ms

        for _page in range(self._MAX_KLINE_PAGES):
            resp = _bybit_get(
                "/v5/market/kline",
                params={
                    "category": "linear",
                    "symbol": symbol,
                    "interval": interval,
                    "start": str(start_ms),
                    "end": str(cur_end),
                    "limit": str(self._MAX_KLINE_PER_REQUEST),
                },
            )

            result = resp.get("result", {})
            raw_list = result.get("list", [])
            if not raw_list:
                break

            page_candles: list[dict] = []
            for item in raw_list:
                if len(item) < 6:
                    continue
                ts = int(item[0])
                if ts < start_ms or ts > end_ms:
                    continue
                page_candles.append({
                    "timestamp": ts,
                    "open":   _f(item[1]),
                    "high":   _f(item[2]),
                    "low":    _f(item[3]),
                    "close":  _f(item[4]),
                    "volume": _f(item[5]),
                })

            if not page_candles:
                break

            all_candles.extend(page_candles)
            min_ts = min(c["timestamp"] for c in page_candles)

            if min_ts <= start_ms:
                break
            if len(raw_list) < self._MAX_KLINE_PER_REQUEST:
                break

            cur_end = min_ts - 1
            if cur_end < start_ms:
                break

        return all_candles

    # ── get_option_chain ──────────────────────────────────────────────────

    def get_option_chain(self, symbol: str, exchange: str, expiry: str | None = None) -> dict:
        """Mudrex is futures-only; option chains are not supported."""
        raise NotImplementedError(
            "Option chain not supported on Mudrex. Mudrex is a crypto futures exchange."
        )
