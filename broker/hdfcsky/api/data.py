# broker/hdfcsky/api/data.py
#
# HDFC Sky market data.
#
#   PUT /oapi/v1/fetch-ltp                      LTP snapshot (batch capable)
#   GET /oapi/charts-api/charts/v1/fetch-candle historical candles
#
# IMPORTANT -- what HDFC Sky's REST API does and does not offer:
#   The ONLY REST market-data endpoints are the LTP snapshot (last traded price
#   + previous close) and the chart-data candles. There is NO REST full-quote
#   or market-depth endpoint. Depth, open interest, total buy/sell quantity and
#   last-traded quantity are delivered exclusively over the protobuf WebSocket
#   feed (streaming/).
#
#   So this module composes what REST does give us:
#     get_quotes  -> LTP + previous close from /fetch-ltp, and open/high/low/
#                    volume from the current session's chart candle.
#     get_depth   -> the same fields with the five bid/ask levels zero-filled,
#                    since REST cannot supply them. Subscribe to the WebSocket
#                    feed in DEPTH mode (mode 3) for a real order book.
#     get_history -> chart-data candles, resampled for the intervals HDFC does
#                    not serve natively (it only has 1-minute and daily).

import time
from datetime import datetime, timedelta

import pandas as pd

from broker.hdfcsky.api.baseurl import base_params, get_hdfcsky_headers, get_root_url
from broker.hdfcsky.database.master_contract_db import SymToken, db_session
from broker.hdfcsky.mapping.exchange import (
    BFO_INDEX_UNDERLYINGS,
    NFO_INDEX_UNDERLYINGS,
    is_index_exchange,
    to_rest_exchange,
)
from database.token_db import get_br_symbol
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


class HDFCSkyAPIError(Exception):
    pass


# HDFC Sky's chart-data `seriesType` is the exchange's instrument series. The
# index-vs-stock distinction is driven by the underlying, which the master
# contract stores in SymToken.name.
_CDS_SERIES = {"FUT": "FUTCUR", "CE": "OPTCUR", "PE": "OPTCUR"}


def _series_type(row):
    """Derive the chart-data `seriesType` for a SymToken row."""
    exchange = row.exchange
    instrument = row.instrumenttype

    if exchange in ("NSE", "BSE") or is_index_exchange(exchange):
        # Cash / index: the series is the suffix on the broker trading symbol
        # ("RELIANCE-EQ" -> EQ, "RELIANCE-A" -> A). Indices have no series.
        if is_index_exchange(exchange):
            return "INDICES" if exchange == "NSE_INDEX" else "IDX"
        brsymbol = str(row.brsymbol or "")
        return brsymbol.rsplit("-", 1)[-1] if "-" in brsymbol else "EQ"

    if exchange == "NFO":
        index_leg = row.name in NFO_INDEX_UNDERLYINGS
        if instrument == "FUT":
            return "FUTIDX" if index_leg else "FUTSTK"
        return "OPTIDX" if index_leg else "OPTSTK"

    if exchange == "BFO":
        # BSE derivatives use the two-letter segment codes from the master:
        # IF/IO for index futures/options, SF/SO for stock futures/options.
        index_leg = row.name in BFO_INDEX_UNDERLYINGS
        if instrument == "FUT":
            return "IF" if index_leg else "SF"
        return "IO" if index_leg else "SO"

    if exchange == "MCX":
        return "FUTCOM" if instrument == "FUT" else "OPTFUT"

    if exchange == "CDS":
        return _CDS_SERIES.get(instrument, "OPTCUR")

    return "EQ"


class BrokerData:
    def __init__(self, auth_token):
        """HDFC Sky data handler. `auth_token` is the access token."""
        self.auth_token = auth_token

        # HDFC Sky serves only two native chart resolutions (chartType
        # MINUTES and DAY). Everything else is resampled from those, so users
        # still get the full OpenAlgo interval set. The value is the pair
        # (native chartType, pandas resample rule or None for pass-through).
        self._interval_spec = {
            "1m": ("MINUTES", None),
            "3m": ("MINUTES", "3min"),
            "5m": ("MINUTES", "5min"),
            "10m": ("MINUTES", "10min"),
            "15m": ("MINUTES", "15min"),
            "30m": ("MINUTES", "30min"),
            "1h": ("MINUTES", "60min"),
            "D": ("DAY", None),
            "W": ("DAY", "W-MON"),
            "M": ("DAY", "MS"),
        }
        # intervals_service reads the keys of this attribute.
        self.timeframe_map = {key: key for key in self._interval_spec}

    # --- helpers --------------------------------------------------------

    def _lookup(self, symbol, exchange):
        """Resolve an OpenAlgo (symbol, exchange) to its master-contract row."""
        br_symbol = get_br_symbol(symbol, exchange)
        with db_session() as session:
            row = (
                session.query(SymToken)
                .filter(SymToken.exchange == exchange, SymToken.brsymbol == br_symbol)
                .first()
            )
            if not row:
                raise HDFCSkyAPIError(f"Could not find instrument for {exchange}:{symbol}")
            session.expunge(row)
        return row

    # --- LTP ------------------------------------------------------------

    def _fetch_ltp(self, instruments):
        """PUT /oapi/v1/fetch-ltp for a batch of {exchange, token} dicts.

        Returns {(exchange, token_str): {"ltp": float, "prev_close": float}}.
        Never raises -- a failed batch yields {} so callers report per-leg
        errors instead of losing every quote.
        """
        if not instruments:
            return {}
        try:
            client = get_httpx_client()
            response = client.put(
                f"{get_root_url()}/oapi/v1/fetch-ltp",
                headers=get_hdfcsky_headers(self.auth_token, with_json=True),
                params=base_params(self.auth_token, client_id=False),
                json={"data": instruments},
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as e:
            logger.warning(f"HDFC Sky LTP request failed for {len(instruments)} instruments: {e}")
            return {}

        result = {}
        for row in payload.get("data") or []:
            key = (str(row.get("exchange", "")).upper(), str(row.get("token", "")))
            result[key] = {
                "ltp": float(row.get("ltp") or 0.0),
                "prev_close": float(row.get("prev_close") or 0.0),
            }
        return result

    def _ltp_for_row(self, row):
        exchange_code = to_rest_exchange(row.exchange)
        quotes = self._fetch_ltp([{"exchange": exchange_code, "token": str(row.token)}])
        return quotes.get((exchange_code, str(row.token)), {"ltp": 0.0, "prev_close": 0.0})

    # --- session OHLCV --------------------------------------------------

    def _session_ohlcv(self, row):
        """Open/high/low/volume for the current session from chart data.

        HDFC Sky has no REST full-quote endpoint, so the intraday bar for
        today is the only REST source for these. Returns zeros when the
        candle is unavailable (pre-open, holiday, or an unsupported segment)
        so a quote never fails purely because of the OHLC leg.
        """
        empty = {"open": 0.0, "high": 0.0, "low": 0.0, "close": 0.0, "volume": 0}
        try:
            today = datetime.now()
            candles = self._fetch_candles(
                row, "DAY", (today - timedelta(days=7)).strftime("%Y-%m-%d"),
                today.strftime("%Y-%m-%d"),
            )
            if not candles:
                return empty
            last = max(candles, key=lambda c: c[6])
            return {
                "open": float(last[0] or 0.0),
                "high": float(last[1] or 0.0),
                "low": float(last[2] or 0.0),
                "close": float(last[3] or 0.0),
                "volume": int(float(last[4] or 0)),
            }
        except Exception as e:
            logger.debug(f"Session OHLC unavailable for {row.exchange}:{row.symbol}: {e}")
            return empty

    # --- public API -----------------------------------------------------

    def get_quotes(self, symbol, exchange):
        """OpenAlgo quote dict.

        `ask`/`bid` are 0 and `oi` is 0: HDFC Sky's REST API exposes neither
        (both are WebSocket-only). Everything else is real.
        """
        try:
            row = self._lookup(symbol, exchange)
            ltp_data = self._ltp_for_row(row)
            ohlcv = self._session_ohlcv(row)

            return {
                "ask": 0.0,
                "bid": 0.0,
                "high": ohlcv["high"],
                "low": ohlcv["low"],
                "ltp": ltp_data["ltp"],
                "open": ohlcv["open"],
                "prev_close": ltp_data["prev_close"],
                "volume": ohlcv["volume"],
                "oi": 0,
            }
        except HDFCSkyAPIError:
            raise
        except Exception as e:
            logger.exception(f"Error fetching HDFC Sky quotes: {e}")
            raise HDFCSkyAPIError(f"Error fetching quotes: {e}") from e

    def get_depth(self, symbol, exchange):
        """OpenAlgo 5-level market depth.

        HDFC Sky publishes the order book ONLY over its WebSocket feed, so the
        five levels here are zero-filled. Subscribe in DEPTH mode (mode 3) via
        the streaming adapter for a live book.
        """
        try:
            quote = self.get_quotes(symbol, exchange)
            empty_levels = [{"price": 0.0, "quantity": 0} for _ in range(5)]
            return {
                "asks": list(empty_levels),
                "bids": list(empty_levels),
                "high": quote["high"],
                "low": quote["low"],
                "ltp": quote["ltp"],
                "ltq": 0,
                "oi": 0,
                "open": quote["open"],
                "prev_close": quote["prev_close"],
                "totalbuyqty": 0,
                "totalsellqty": 0,
                "volume": quote["volume"],
            }
        except HDFCSkyAPIError:
            raise
        except Exception as e:
            logger.exception(f"Error fetching HDFC Sky market depth: {e}")
            raise HDFCSkyAPIError(f"Error fetching market depth: {e}") from e

    def get_market_depth(self, symbol, exchange):
        """Alias for get_depth (parity with brokers that expose get_market_depth)."""
        return self.get_depth(symbol, exchange)

    # The /fetch-ltp endpoint takes a list, so multiquotes is one request per
    # chunk. The per-request cap is not documented; 100 matches the batch size
    # other Indian brokers accept and keeps request bodies small.
    # TODO(hdfcsky): binary-search the real cap against the live endpoint
    # (1 / 50 / 100 / 200 / 300) and raise this if the server allows more.
    _MULTIQUOTE_MAX_PER_REQUEST = 100
    _MULTIQUOTE_RATE_DELAY = 0.15
    _HISTORY_RATE_DELAY = 0.15

    @staticmethod
    def _leg_error(item, message):
        """One result entry flagging a single leg as failed, so callers (e.g.
        the sandbox engine) see exactly which symbols are missing rather than
        getting a silently short list."""
        return {"symbol": item.get("symbol"), "exchange": item.get("exchange"), "error": message}

    def get_multiquotes(self, symbols: list) -> list:
        """Quotes for many symbols, batched.

        Args:
            symbols: [{'symbol': 'SBIN', 'exchange': 'NSE'}, ...]
        Returns:
            One entry per requested leg: {'symbol', 'exchange', 'data'} or
            {'symbol', 'exchange', 'error'}.

        Only LTP and previous close are available in batch -- open/high/low/
        volume would need one chart request per symbol, which would defeat the
        purpose of a batch call, so they are reported as 0 here. Use
        get_quotes() for a single enriched quote.
        """
        results = []
        for start in range(0, len(symbols), self._MULTIQUOTE_MAX_PER_REQUEST):
            batch = symbols[start : start + self._MULTIQUOTE_MAX_PER_REQUEST]
            results.extend(self._process_quotes_batch(batch))
            if start + self._MULTIQUOTE_MAX_PER_REQUEST < len(symbols):
                time.sleep(self._MULTIQUOTE_RATE_DELAY)
        return results

    def _process_quotes_batch(self, symbols: list) -> list:
        instruments = []
        key_map = {}  # (exchange_code, token) -> original request item
        skipped = []

        for item in symbols:
            try:
                row = self._lookup(item["symbol"], item["exchange"])
            except Exception as e:
                logger.warning(f"Skipping {item.get('exchange')}:{item.get('symbol')}: {e}")
                skipped.append(self._leg_error(item, str(e)))
                continue
            exchange_code = to_rest_exchange(row.exchange)
            key = (exchange_code, str(row.token))
            instruments.append({"exchange": exchange_code, "token": str(row.token)})
            key_map[key] = item

        if not key_map:
            return skipped

        quotes = self._fetch_ltp(instruments)

        results = []
        for key, item in key_map.items():
            quote = quotes.get(key)
            if quote is None:
                results.append(self._leg_error(item, "No quote data available"))
                continue
            results.append(
                {
                    "symbol": item["symbol"],
                    "exchange": item["exchange"],
                    "data": {
                        "ask": 0.0,
                        "bid": 0.0,
                        "high": 0.0,
                        "low": 0.0,
                        "ltp": quote["ltp"],
                        "open": 0.0,
                        "prev_close": quote["prev_close"],
                        "volume": 0,
                        "oi": 0,
                    },
                }
            )
        return skipped + results

    # --- history --------------------------------------------------------

    def _fetch_candles(self, row, chart_type, start, end):
        """GET the chart-data candles for one instrument and date range.

        Returns the raw `results` rows: [open, high, low, close, volume, oi,
        "DD-MM-YYYY[ HH:MM:SS]"].
        """
        client = get_httpx_client()
        params = {
            **base_params(self.auth_token, client_id=False),
            # Cash instruments are addressed by their series-free symbol
            # (the docs' sample is symbol=RELIANCE + seriesType=EQ), which is
            # exactly the OpenAlgo symbol; derivatives use the full broker
            # trading symbol.
            "symbol": row.symbol if row.exchange in ("NSE", "BSE") else row.brsymbol,
            "exchange": to_rest_exchange(row.exchange),
            "chartType": chart_type,
            "seriesType": _series_type(row),
            "start": start,
            "end": end,
        }
        response = client.get(
            f"{get_root_url()}/oapi/charts-api/charts/v1/fetch-candle",
            headers=get_hdfcsky_headers(self.auth_token),
            params=params,
        )
        response.raise_for_status()
        payload = response.json()

        meta = payload.get("meta") or {}
        err = str(meta.get("err_code", "")).lower()
        if err and err not in ("success", "ok", "0"):
            raise HDFCSkyAPIError(
                meta.get("displayMessage") or f"Chart data request failed ({err})"
            )

        return (payload.get("data") or {}).get("results") or []

    @staticmethod
    def _resample(df, rule):
        """Aggregate candles to a coarser interval."""
        indexed = df.set_index(pd.to_datetime(df["timestamp"], unit="s"))
        agg = indexed.resample(rule, label="left", closed="left").agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
                "oi": "last",
            }
        )
        agg = agg.dropna(subset=["open"]).reset_index(names="timestamp")
        agg["timestamp"] = agg["timestamp"].astype("int64") // 10**9
        return agg

    def get_history(self, symbol, exchange, timeframe, from_date, to_date):
        """Historical candles -> DataFrame [timestamp, open, high, low, close,
        volume, oi] with `timestamp` in epoch seconds."""
        try:
            spec = self._interval_spec.get(timeframe)
            if not spec:
                raise HDFCSkyAPIError(
                    f"Unsupported timeframe: {timeframe}. "
                    f"Supported: {', '.join(self._interval_spec)}"
                )
            chart_type, resample_rule = spec

            row = self._lookup(symbol, exchange)
            start_date = pd.to_datetime(from_date)
            end_date = pd.to_datetime(to_date)

            # HDFC Sky does not document a per-request date-range cap; chunk
            # conservatively (long for daily, short for intraday).
            # TODO(hdfcsky): confirm the real per-request range limits live.
            chunk_days = 2000 if chart_type == "DAY" else 30

            rows = []
            current_start = start_date
            while current_start <= end_date:
                current_end = min(current_start + timedelta(days=chunk_days - 1), end_date)
                rows.extend(
                    self._fetch_candles(
                        row,
                        chart_type,
                        current_start.strftime("%Y-%m-%d"),
                        current_end.strftime("%Y-%m-%d"),
                    )
                )
                current_start = current_end + timedelta(days=1)
                if current_start <= end_date:
                    time.sleep(self._HISTORY_RATE_DELAY)

            base_cols = ["timestamp", "open", "high", "low", "close", "volume", "oi"]
            if not rows:
                return pd.DataFrame(columns=base_cols)

            df = pd.DataFrame(
                rows, columns=["open", "high", "low", "close", "volume", "oi", "timestamp"]
            )
            # HDFC Sky sends day-first strings ("22-10-2024" for daily,
            # "22-10-2024 09:15:00" for intraday) in IST, with no offset.
            stamps = pd.to_datetime(df["timestamp"], dayfirst=True, errors="coerce")
            df = df[stamps.notna()]
            stamps = stamps.dropna()

            # Mirror the Zerodha epoch convention so candles line up across
            # brokers: intraday is the true UTC epoch of the IST candle time,
            # while daily/weekly/monthly are shifted +5:30 so the candle
            # represents IST midnight.
            if chart_type == "DAY":
                stamps = stamps.dt.normalize() + pd.Timedelta(hours=5, minutes=30)
            else:
                stamps = stamps.dt.tz_localize("Asia/Kolkata").dt.tz_convert("UTC").dt.tz_localize(
                    None
                )
            df["timestamp"] = stamps.astype("int64") // 10**9

            for col in ("open", "high", "low", "close"):
                df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64")
            df["oi"] = pd.to_numeric(df["oi"], errors="coerce").fillna(0).astype("int64")

            df = (
                df.sort_values("timestamp")
                .drop_duplicates(subset=["timestamp"])
                .reset_index(drop=True)[base_cols]
            )

            if resample_rule:
                df = self._resample(df, resample_rule)[base_cols]
                df["volume"] = df["volume"].astype("int64")
                df["oi"] = df["oi"].fillna(0).astype("int64")

            return df.reset_index(drop=True)
        except HDFCSkyAPIError:
            raise
        except Exception as e:
            logger.exception(f"Error fetching HDFC Sky historical data: {e}")
            raise HDFCSkyAPIError(f"Error fetching historical data: {e}") from e
