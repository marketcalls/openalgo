# broker/rupeezy/api/data.py
#
# Quotes, depth and history over the Vortex "Historical Data" API
# (https://vortex.rupeezy.in/docs/latest/historical/).
#
#   GET /data/quotes?q=<ticker>&q=<ticker>&mode=full   up to 1000 tickers, 1/sec
#   GET /data/history?ticker=&from=&to=&resolution=     epoch seconds, 1/sec
#
# Quote prices are rupees. The response is a map keyed by the ticker exactly
# as sent; tickers with no quote are omitted.

from datetime import datetime, timedelta, timezone

import pandas as pd

from broker.rupeezy.api.client import RupeezyAPIError, request_json
from broker.rupeezy.mapping.exchange import build_ticker
from database.token_db import get_symbol_info
from utils.logging import get_logger

logger = get_logger(__name__)

_IST = timezone(timedelta(hours=5, minutes=30))
_DAY_SECONDS = 86400
_IST_OFFSET_SECONDS = 19800

# Vortex accepts up to 1000 tickers per quote request.
_MAX_QUOTES_PER_REQUEST = 1000


def _f(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _i(value):
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _levels(side):
    """Vortex depth side -> 5 OpenAlgo levels. Empty levels arrive as {}."""
    out = []
    for i in range(5):
        level = side[i] if i < len(side) and isinstance(side[i], dict) else {}
        out.append({"price": _f(level.get("price")), "quantity": _i(level.get("quantity"))})
    return out


def _format_quote(q):
    depth = q.get("depth") or {}
    bids = _levels(depth.get("buy") or [])
    asks = _levels(depth.get("sell") or [])
    return {
        "ask": asks[0]["price"],
        "bid": bids[0]["price"],
        "high": _f(q.get("high_price")),
        "low": _f(q.get("low_price")),
        "ltp": _f(q.get("last_trade_price")),
        "open": _f(q.get("open_price")),
        "prev_close": _f(q.get("close_price")),
        "volume": _i(q.get("volume")),
        "oi": _i(q.get("open_interest")),
    }


class BrokerData:
    def __init__(self, auth_token):
        self.auth_token = auth_token
        # OpenAlgo interval -> Vortex resolution.
        self.timeframe_map = {
            "1m": "1",
            "2m": "2",
            "3m": "3",
            "5m": "5",
            "10m": "10",
            "15m": "15",
            "30m": "30",
            "45m": "45",
            "1h": "60",
            "2h": "120",
            "3h": "180",
            "4h": "240",
            "D": "1D",
            "W": "1W",
            "M": "1M",
        }

    # --- helpers --------------------------------------------------------

    @staticmethod
    def _ticker(symbol, exchange):
        info = get_symbol_info(symbol, exchange)
        if not info:
            raise RupeezyAPIError(f"Symbol {symbol} not found on {exchange}")
        return build_ticker(info.brexchange, info.brsymbol)

    def _fetch_quotes(self, tickers, mode="full"):
        """GET /data/quotes for up to 1000 tickers -> {ticker: quote}."""
        params = [("q", t) for t in tickers] + [("mode", mode)]
        payload = request_json("GET", "/data/quotes", self.auth_token, params=params)
        if payload.get("status") != "success":
            raise RupeezyAPIError(payload.get("message", "Quote request failed"))
        return payload.get("data") or {}

    def _single_quote(self, symbol, exchange):
        ticker = self._ticker(symbol, exchange)
        quote = self._fetch_quotes([ticker]).get(ticker)
        if not quote:
            raise RupeezyAPIError(f"No quote available for {exchange}:{symbol}")
        return quote

    # --- quotes ---------------------------------------------------------

    def get_quotes(self, symbol, exchange):
        try:
            return _format_quote(self._single_quote(symbol, exchange))
        except Exception as e:
            logger.exception(f"Error fetching Rupeezy quotes for {exchange}:{symbol}")
            raise RupeezyAPIError(f"Error fetching quotes: {e}") from e

    def get_depth(self, symbol, exchange):
        try:
            q = self._single_quote(symbol, exchange)
            depth = q.get("depth") or {}
            return {
                "asks": _levels(depth.get("sell") or []),
                "bids": _levels(depth.get("buy") or []),
                "high": _f(q.get("high_price")),
                "low": _f(q.get("low_price")),
                "ltp": _f(q.get("last_trade_price")),
                "ltq": _i(q.get("last_trade_quantity")),
                "oi": _i(q.get("open_interest")),
                "open": _f(q.get("open_price")),
                "prev_close": _f(q.get("close_price")),
                "totalbuyqty": _i(q.get("total_buy_quantity")),
                "totalsellqty": _i(q.get("total_sell_quantity")),
                "volume": _i(q.get("volume")),
            }
        except Exception as e:
            logger.exception(f"Error fetching Rupeezy depth for {exchange}:{symbol}")
            raise RupeezyAPIError(f"Error fetching market depth: {e}") from e

    def get_market_depth(self, symbol, exchange):
        return self.get_depth(symbol, exchange)

    def get_multiquotes(self, symbols: list) -> list:
        """Quotes for many symbols, one entry per requested leg.

        Args:
            symbols: [{"symbol": "SBIN", "exchange": "NSE"}, ...]
        Returns:
            [{"symbol", "exchange", "data": {...}}] or {"symbol", "exchange", "error"}
            for legs that could not be quoted.
        """
        results = []
        resolved = []  # (ticker, item)
        for item in symbols:
            try:
                resolved.append((self._ticker(item["symbol"], item["exchange"]), item))
            except Exception as e:
                results.append(
                    {
                        "symbol": item.get("symbol"),
                        "exchange": item.get("exchange"),
                        "error": str(e),
                    }
                )

        for i in range(0, len(resolved), _MAX_QUOTES_PER_REQUEST):
            batch = resolved[i : i + _MAX_QUOTES_PER_REQUEST]
            try:
                quotes = self._fetch_quotes(sorted({t for t, _ in batch}))
            except Exception as e:
                logger.warning(f"Rupeezy multiquote batch of {len(batch)} failed: {e}")
                quotes = {}
            for ticker, item in batch:
                quote = quotes.get(ticker)
                if quote is None:
                    results.append(
                        {
                            "symbol": item["symbol"],
                            "exchange": item["exchange"],
                            "error": "No quote data available",
                        }
                    )
                else:
                    results.append(
                        {
                            "symbol": item["symbol"],
                            "exchange": item["exchange"],
                            "data": _format_quote(quote),
                        }
                    )
        return results

    # --- history --------------------------------------------------------

    def get_history(self, symbol, exchange, timeframe, from_date, to_date):
        """Historical candles -> DataFrame [timestamp, open, high, low, close, volume, oi].

        Vortex returns epoch seconds already. Intraday candles are passed
        through; daily/weekly/monthly candles are normalized to 00:00 UTC of
        their IST trading date, matching the Zerodha convention, whether
        Vortex stamps them at IST or UTC midnight.
        """
        columns = ["timestamp", "open", "high", "low", "close", "volume", "oi"]
        try:
            resolution = self.timeframe_map.get(timeframe)
            if not resolution:
                raise RupeezyAPIError(f"Unsupported timeframe: {timeframe}")
            ticker = self._ticker(symbol, exchange)
            is_daily = timeframe in ("D", "W", "M")

            start = pd.to_datetime(from_date).date()
            end = pd.to_datetime(to_date).date()
            # TODO(rupeezy): per-request range caps are not documented; these
            # chunk sizes are conservative. Confirm against a live account.
            chunk_days = 1000 if is_daily else 30

            frames = []
            current = start
            while current <= end:
                chunk_end = min(current + timedelta(days=chunk_days - 1), end)
                frm = int(datetime.combine(current, datetime.min.time(), _IST).timestamp())
                to = int(datetime.combine(chunk_end, datetime.max.time(), _IST).timestamp())
                payload = request_json(
                    "GET",
                    "/data/history",
                    self.auth_token,
                    params={"ticker": ticker, "from": frm, "to": to, "resolution": resolution},
                )
                status = payload.get("s")
                if status == "ok" and payload.get("t"):
                    frames.append(
                        pd.DataFrame(
                            {
                                "timestamp": payload["t"],
                                "open": payload.get("o"),
                                "high": payload.get("h"),
                                "low": payload.get("l"),
                                "close": payload.get("c"),
                                "volume": payload.get("v"),
                            }
                        )
                    )
                elif status not in ("ok", "no_data"):
                    raise RupeezyAPIError(
                        payload.get("message")
                        or payload.get("errmsg")
                        or "Historical data request failed"
                    )
                current = chunk_end + timedelta(days=1)

            if not frames:
                return pd.DataFrame(columns=columns)

            df = pd.concat(frames, ignore_index=True)
            df["timestamp"] = df["timestamp"].astype("int64")
            if is_daily:
                ist_day = (df["timestamp"] + _IST_OFFSET_SECONDS) // _DAY_SECONDS
                df["timestamp"] = ist_day * _DAY_SECONDS
            for col in ("open", "high", "low", "close"):
                df[col] = df[col].astype(float)
            df["volume"] = df["volume"].fillna(0).astype("int64")
            df["oi"] = 0

            df = (
                df.sort_values("timestamp")
                .drop_duplicates(subset=["timestamp"])
                .reset_index(drop=True)
            )
            return df[columns]
        except Exception as e:
            logger.exception(f"Error fetching Rupeezy history for {exchange}:{symbol}")
            raise RupeezyAPIError(f"Error fetching historical data: {e}") from e
