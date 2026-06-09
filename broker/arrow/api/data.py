# broker/arrow/api/data.py

import time
from datetime import timedelta

import pandas as pd

from broker.arrow.api.baseurl import HISTORICAL_URL, ROOT_URL, get_arrow_headers
from broker.arrow.database.master_contract_db import SymToken, db_session
from broker.arrow.mapping.exchange import (
    to_arrow_history_exchange,
    to_arrow_quote_exchange,
)
from database.token_db import get_br_symbol
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# Arrow returns prices as exchange-native scaled integers (NSE = paise = x100).
# Divide by this to get rupee prices. Volume / OI / quantities are NOT scaled.
# TODO(arrow): confirm the scale is uniformly 100 across MCX / currency / BSE.
PRICE_SCALE = 100.0


def _scale(value):
    try:
        return float(value) / PRICE_SCALE
    except (TypeError, ValueError):
        return 0.0


class ArrowAPIError(Exception):
    pass


class BrokerData:
    def __init__(self, auth_token):
        """Arrow data handler. `auth_token` is the JWT access token."""
        self.auth_token = auth_token

        # OpenAlgo timeframe -> Arrow interval string. Keys are what
        # intervals_service exposes to users.
        self.timeframe_map = {
            "1m": "min",
            "3m": "3min",
            "5m": "5min",
            "10m": "10min",
            "15m": "15min",
            "30m": "30min",
            "1h": "hour",
            "2h": "2hours",
            "3h": "3hours",
            "4h": "4hours",
            "D": "day",
            "W": "week",
            "M": "month",
        }

    # --- helpers --------------------------------------------------------

    def _lookup(self, symbol, exchange):
        """Resolve an OpenAlgo (symbol, exchange) to the Arrow instrument.

        Returns (br_symbol, token, arrow_quote_exchange).
        """
        br_symbol = get_br_symbol(symbol, exchange)
        with db_session() as session:
            row = (
                session.query(SymToken)
                .filter(SymToken.exchange == exchange, SymToken.brsymbol == br_symbol)
                .first()
            )
            if not row:
                raise ArrowAPIError(f"Could not find instrument for {exchange}:{symbol}")
            token = row.token
        return br_symbol, token, to_arrow_quote_exchange(exchange)

    def _quote(self, mode, br_symbol, arrow_exchange):
        """POST /info/quote/{mode} for a single instrument; returns data dict."""
        client = get_httpx_client()
        headers = get_arrow_headers(self.auth_token, with_json=True)
        body = {"exchange": arrow_exchange, "symbol": br_symbol}
        response = client.post(f"{ROOT_URL}/info/quote/{mode}", headers=headers, json=body)
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") not in ("success", None):
            raise ArrowAPIError(payload.get("message", "Quote request failed"))
        return payload.get("data", {})

    # --- public API -----------------------------------------------------

    def get_quotes(self, symbol, exchange):
        """Return the OpenAlgo quote dict. Uses Arrow `full` mode so bid/ask are
        available. Works for NSE_INDEX/BSE_INDEX (exchange -> INDEX)."""
        try:
            br_symbol, _token, arrow_exchange = self._lookup(symbol, exchange)
            q = self._quote("full", br_symbol, arrow_exchange)

            bids = q.get("bids") or [{}]
            asks = q.get("asks") or [{}]
            return {
                "ask": _scale(asks[0].get("price", 0)),
                "bid": _scale(bids[0].get("price", 0)),
                "high": _scale(q.get("high", 0)),
                "low": _scale(q.get("low", 0)),
                "ltp": _scale(q.get("ltp", 0)),
                "open": _scale(q.get("open", 0)),
                "prev_close": _scale(q.get("close", 0)),
                "volume": q.get("volume", 0),
                "oi": q.get("oi", 0),
            }
        except Exception as e:
            logger.exception(f"Error fetching Arrow quotes: {e}")
            raise ArrowAPIError(f"Error fetching quotes: {e}") from e

    def get_depth(self, symbol, exchange):
        """Return OpenAlgo 5-level market depth. Indices supported via INDEX."""
        try:
            br_symbol, _token, arrow_exchange = self._lookup(symbol, exchange)
            q = self._quote("full", br_symbol, arrow_exchange)

            raw_bids = q.get("bids") or []
            raw_asks = q.get("asks") or []

            def _levels(levels):
                out = []
                for i in range(5):
                    if i < len(levels):
                        out.append(
                            {
                                "price": _scale(levels[i].get("price", 0)),
                                "quantity": levels[i].get("quantity", 0),
                            }
                        )
                    else:
                        out.append({"price": 0, "quantity": 0})
                return out

            return {
                "asks": _levels(raw_asks),
                "bids": _levels(raw_bids),
                "high": _scale(q.get("high", 0)),
                "low": _scale(q.get("low", 0)),
                "ltp": _scale(q.get("ltp", 0)),
                "ltq": q.get("ltq", 0),
                "oi": q.get("oi", 0),
                "open": _scale(q.get("open", 0)),
                "prev_close": _scale(q.get("close", 0)),
                "totalbuyqty": q.get("totalBuyQty", 0),
                "totalsellqty": q.get("totalSellQty", 0),
                "volume": q.get("volume", 0),
            }
        except Exception as e:
            logger.exception(f"Error fetching Arrow market depth: {e}")
            raise ArrowAPIError(f"Error fetching market depth: {e}") from e

    def get_market_depth(self, symbol, exchange):
        """Alias for get_depth (parity with brokers that expose get_market_depth)."""
        return self.get_depth(symbol, exchange)

    # Arrow rate limit: 10 req/sec per endpoint group (docs/15-rate-limits).
    # Batch large symbol sets and throttle between batches, mirroring the
    # zerodha/upstox handlers (which use 500/batch + a per-batch delay).
    # TODO(arrow): confirm the max instruments allowed per /info/quotes request.
    _MULTIQUOTE_BATCH_SIZE = 500
    _MULTIQUOTE_RATE_DELAY = 0.2   # keeps batches under Arrow's 10 req/sec
    _HISTORY_RATE_DELAY = 0.15     # throttle between historical date-chunks

    def get_multiquotes(self, symbols):
        """Batch quotes via /info/quotes/full. `symbols` is a list of
        {symbol, exchange}. Large sets are split into batches with a delay so we
        stay within Arrow's per-endpoint rate limit."""
        try:
            results = []
            n = len(symbols)
            for i in range(0, n, self._MULTIQUOTE_BATCH_SIZE):
                batch = symbols[i:i + self._MULTIQUOTE_BATCH_SIZE]
                results.extend(self._process_quotes_batch(batch))
                if i + self._MULTIQUOTE_BATCH_SIZE < n:
                    time.sleep(self._MULTIQUOTE_RATE_DELAY)
            return results
        except Exception as e:
            logger.exception(f"Error fetching Arrow multiquotes: {e}")
            raise ArrowAPIError(f"Error fetching multiquotes: {e}") from e

    def _process_quotes_batch(self, symbols):
        """Fetch one batch of quotes. Response order is not guaranteed, so match
        results to requests by the returned token."""
        client = get_httpx_client()
        headers = get_arrow_headers(self.auth_token, with_json=True)

        body = []
        token_map = {}  # token(str) -> original {symbol, exchange}
        for item in symbols:
            try:
                br_symbol, token, arrow_exchange = self._lookup(
                    item["symbol"], item["exchange"]
                )
            except Exception:
                continue
            body.append({"exchange": arrow_exchange, "symbol": br_symbol})
            token_map[str(token)] = item

        if not body:
            return []

        response = client.post(f"{ROOT_URL}/info/quotes/full", headers=headers, json=body)
        response.raise_for_status()
        data = response.json().get("data", [])

        results = []
        for q in data:
            original = token_map.get(str(q.get("token")))
            if not original:
                continue
            bids = q.get("bids") or [{}]
            asks = q.get("asks") or [{}]
            results.append(
                {
                    "symbol": original["symbol"],
                    "exchange": original["exchange"],
                    "data": {
                        "ask": _scale(asks[0].get("price", 0)),
                        "bid": _scale(bids[0].get("price", 0)),
                        "high": _scale(q.get("high", 0)),
                        "low": _scale(q.get("low", 0)),
                        "ltp": _scale(q.get("ltp", 0)),
                        "open": _scale(q.get("open", 0)),
                        "prev_close": _scale(q.get("close", 0)),
                        "volume": q.get("volume", 0),
                        "oi": q.get("oi", 0),
                    },
                }
            )
        return results

    def get_history(self, symbol, exchange, timeframe, from_date, to_date):
        """Historical candles -> OpenAlgo DataFrame (timestamp, open, high, low,
        close, volume, oi). Token-based; works for indices (NSE_INDEX/BSE_INDEX
        -> nse/bse path)."""
        try:
            interval = self.timeframe_map.get(timeframe)
            if not interval:
                raise ArrowAPIError(f"Unsupported timeframe: {timeframe}")

            _br_symbol, token, _ = self._lookup(symbol, exchange)
            arrow_exchange = to_arrow_history_exchange(exchange)

            # OI is only available on NFO/BFO derivatives.
            want_oi = exchange in ("NFO", "BFO")

            client = get_httpx_client()
            headers = get_arrow_headers(self.auth_token)

            start_date = pd.to_datetime(from_date)
            end_date = pd.to_datetime(to_date)

            # Arrow enforces a per-interval max range (undocumented). Chunk
            # conservatively: long for daily+, short for intraday.
            # TODO(arrow): confirm exact per-interval date-range caps.
            chunk_days = 2000 if interval in ("day", "week", "month") else 60

            frames = []
            current_start = start_date
            while current_start <= end_date:
                current_end = min(current_start + timedelta(days=chunk_days - 1), end_date)
                from_str = current_start.strftime("%Y-%m-%dT00:00:00")
                to_str = current_end.strftime("%Y-%m-%dT23:59:59")

                url = f"{HISTORICAL_URL}/candle/{arrow_exchange}/{token}/{interval}"
                params = {"from": from_str, "to": to_str}
                if want_oi:
                    params["oi"] = 1

                response = client.get(url, headers=headers, params=params)
                response.raise_for_status()
                candles = response.json()

                # Error responses are a dict envelope; success is a bare list.
                if isinstance(candles, dict):
                    raise ArrowAPIError(candles.get("message", "Historical request failed"))

                if candles:
                    cols = ["timestamp", "open", "high", "low", "close", "volume"]
                    if want_oi and len(candles[0]) > 6:
                        cols.append("oi")
                    frames.append(pd.DataFrame(candles, columns=cols))

                current_start = current_end + timedelta(days=1)
                # Throttle between date-chunks to stay within Arrow's 10 req/sec
                # historical-data rate limit.
                if current_start <= end_date:
                    time.sleep(self._HISTORY_RATE_DELAY)

            base_cols = ["timestamp", "open", "high", "low", "close", "volume", "oi"]
            if not frames:
                return pd.DataFrame(columns=base_cols)

            df = pd.concat(frames, ignore_index=True)
            if "oi" not in df.columns:
                df["oi"] = 0

            # Arrow returns ISO 8601 timestamps with the +0530 offset for BOTH
            # intraday and daily candles. Mirror the zerodha convention so the
            # epoch is consistent across brokers:
            #   - intraday (min/hour): true UTC epoch of the IST candle time
            #   - daily/weekly/monthly: shift +5:30 so the candle represents IST
            #     midnight (date-granularity), matching zerodha's daily handling
            df["timestamp"] = pd.to_datetime(df["timestamp"], format="ISO8601")
            if timeframe in ("D", "W", "M"):
                df["timestamp"] = df["timestamp"] + pd.Timedelta(hours=5, minutes=30)
            df["timestamp"] = df["timestamp"].astype("int64") // 10**9

            # De-scale OHLC (x100); volume / oi are raw.
            for col in ("open", "high", "low", "close"):
                df[col] = df[col].astype(float) / PRICE_SCALE
            df["volume"] = df["volume"].astype("int64")
            df["oi"] = df["oi"].fillna(0).astype("int64")

            df = (
                df.sort_values("timestamp")
                .drop_duplicates(subset=["timestamp"])
                .reset_index(drop=True)
            )
            return df[base_cols]
        except Exception as e:
            logger.exception(f"Error fetching Arrow historical data: {e}")
            raise ArrowAPIError(f"Error fetching historical data: {e}") from e
