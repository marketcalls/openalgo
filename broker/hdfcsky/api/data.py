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
from broker.hdfcsky.mapping.transform_data import (
    BFO_INDEX_UNDERLYINGS,
    NFO_INDEX_UNDERLYINGS,
    is_index_exchange,
    to_ltp_exchange,
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

        # HDFC Sky serves only two native chart resolutions (chartType MINUTE
        # and DAY). Everything else is resampled from those, so users still get
        # the full OpenAlgo interval set. The value is the pair (native
        # chartType, pandas resample rule or None for pass-through).
        #
        # chartType is MINUTE, singular. The docs' query-param table says
        # "MINUTES/DAY" but that is wrong - the plural is rejected with
        # 400 "Client error, please check params". The docs' own curl sample
        # uses the singular.
        self._interval_spec = {
            "1m": ("MINUTE", None),
            "3m": ("MINUTE", "3min"),
            "5m": ("MINUTE", "5min"),
            "10m": ("MINUTE", "10min"),
            "15m": ("MINUTE", "15min"),
            "30m": ("MINUTE", "30min"),
            "1h": ("MINUTE", "60min"),
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
            for attempt in range(self._HISTORY_MAX_ATTEMPTS):
                response = client.put(
                    f"{get_root_url()}/oapi/v1/fetch-ltp",
                    headers=get_hdfcsky_headers(self.auth_token, with_json=True),
                    params=base_params(self.auth_token, client_id=False),
                    json={"data": instruments},
                )
                # A rate-limited batch must be retried, not dropped: returning
                # {} here surfaces as an LTP of 0.0, which silently corrupts
                # anything derived from it (option greeks, synthetic futures).
                if response.status_code == 429 and attempt < self._HISTORY_MAX_ATTEMPTS - 1:
                    delay = self._HISTORY_RETRY_BACKOFF * (2**attempt)
                    logger.warning(
                        f"HDFC Sky LTP rate-limited for {len(instruments)} instruments, "
                        f"retrying in {delay:.1f}s"
                    )
                    time.sleep(delay)
                    continue
                break

            # Check the status by hand: raise_for_status()'s message embeds the
            # request URL, which carries the API key as a query parameter.
            if response.status_code != 200:
                logger.warning(
                    f"HDFC Sky LTP request failed for {len(instruments)} instruments "
                    f"(HTTP {response.status_code}): {response.text[:200]!r}"
                )
                return {}
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
        # fetch-ltp addresses indices by NSE_INDEX / BSE_INDEX, not by their
        # parent cash exchange - see to_ltp_exchange.
        exchange_code = to_ltp_exchange(row.exchange)
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
    # The chart service answers 429 "merchantKeyRateLimit" under bursts, so
    # retry with exponential backoff (0.5s, 1s, 2s) before giving up.
    _HISTORY_MAX_ATTEMPTS = 4
    _HISTORY_RETRY_BACKOFF = 0.5
    # Outer chunk-level retry budget: a transient failure must never advance
    # past a chunk and leave a silent gap in a long download.
    _HISTORY_CHUNK_ATTEMPTS = 4

    # (exchange, symbol) -> the chart-data symbol form that actually returns
    # candles. Only indices are ambiguous; see _chart_symbols. Shared across
    # instances because it is a property of the broker, not of a session.
    _CHART_SYMBOL_CACHE = {}

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
            exchange_code = to_ltp_exchange(row.exchange)
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

    @staticmethod
    def _chart_symbols(row):
        """Ordered chart-data `symbol` candidates for a master-contract row.

        The chart service keeps its own symbol vocabulary, which is NOT the
        master contract's:
          - Cash uses the series-free symbol - "SBIN", not "SBIN-EQ". The
            broker form returns an empty result set rather than an error.
          - Derivatives use the broker trading symbol - "NIFTY26AUGFUT".
          - Indices are inconsistent. The headline ones want the compact
            OpenAlgo symbol ("NIFTY", "BANKNIFTY"; "NIFTY 50" yields nothing),
            while the long tail wants the uppercased broker name ("NIFTY AUTO",
            "INDIA VIX"; the space-free "NIFTYAUTO" yields nothing). Neither
            form covers both, so both are offered and the caller keeps whichever
            actually returns candles.
        """
        if is_index_exchange(row.exchange):
            broker_form = str(row.brsymbol or "").upper()
            candidates = [row.symbol]
            if broker_form and broker_form != row.symbol:
                candidates.append(broker_form)
            return candidates
        if row.exchange in ("NSE", "BSE"):
            return [row.symbol]
        return [row.brsymbol]

    def _fetch_candles(self, row, chart_type, start, end, symbol=None):
        """GET the chart-data candles for one instrument and date range.

        Returns the raw `results` rows. The live API sends EIGHT columns, one
        more than the documented sample:
            [open, high, low, close, volume, oi, "DD-MM-YYYY[ HH:MM]", cum_vol]
        The trailing column is the running cumulative volume for the current
        trading day (zero on every earlier day), which OpenAlgo does not carry,
        so callers keep only the leading seven.

        Rows are NOT returned in chronological order - the caller must sort.
        """
        client = get_httpx_client()
        chart_symbol = symbol or self._chart_symbols(row)[0]
        params = {
            **base_params(self.auth_token, client_id=False),
            "symbol": chart_symbol,
            "exchange": to_rest_exchange(row.exchange),
            "chartType": chart_type,
            "seriesType": _series_type(row),
            "start": start,
            "end": end,
        }
        label = f"{row.exchange}:{row.symbol} ({chart_symbol}) {chart_type} {start}..{end}"

        for attempt in range(self._HISTORY_MAX_ATTEMPTS):
            response = client.get(
                f"{get_root_url()}/oapi/charts-api/charts/v1/fetch-candle",
                headers=get_hdfcsky_headers(self.auth_token),
                params=params,
            )
            # The chart service rate-limits per API key with
            # 429 {"error": "merchantKeyRateLimit - too many requests"}.
            # Back off and retry rather than failing a multi-chunk request.
            if response.status_code == 429 and attempt < self._HISTORY_MAX_ATTEMPTS - 1:
                delay = self._HISTORY_RETRY_BACKOFF * (2**attempt)
                logger.warning(f"HDFC Sky chart data rate-limited, retrying in {delay:.1f}s: {label}")
                time.sleep(delay)
                continue
            break

        try:
            payload = response.json()
        except ValueError:
            payload = {}

        # Never surface the raw httpx error: its message embeds the request URL,
        # which carries the API key in a query parameter.
        if response.status_code != 200:
            detail = (payload.get("meta") or {}).get("displayMessage") or payload.get("error")
            raise HDFCSkyAPIError(
                f"Chart data request failed (HTTP {response.status_code}"
                f"{': ' + str(detail) if detail else ''}) for {label}"
            )

        meta = payload.get("meta") or {}
        err = str(meta.get("err_code", "")).lower()
        if err and err not in ("success", "ok", "0"):
            raise HDFCSkyAPIError(
                meta.get("displayMessage") or f"Chart data request failed ({err}) for {label}"
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

            # Normalize the requested window the same way the Angel handler
            # does: the start covers the whole day, and an end date of today is
            # clamped to now rather than to a future 23:59.
            start_date = pd.to_datetime(from_date).replace(hour=0, minute=0)
            end_date = pd.to_datetime(to_date)
            now = pd.Timestamp.now()
            if end_date.date() == now.date():
                end_date = now.replace(second=0, microsecond=0)
            else:
                end_date = end_date.replace(hour=23, minute=59)

            # Per-request date-range caps, measured against the live API: a
            # span wider than these is rejected with 400 "Allowed Date range
            # exceeded". DAY accepts up to 2000 days, MINUTE up to 31. Every
            # intraday timeframe is resampled from MINUTE, so they all share
            # the 31-day cap.
            chunk_days = 2000 if chart_type == "DAY" else 31

            # Indices offer two possible chart symbols (see _chart_symbols).
            # Resolve which one this instrument answers to on the first chunk
            # that returns candles, then reuse it: a wrong form is not an
            # error, it just returns nothing. The resolved form is cached for
            # the process lifetime so repeat calls never pay for the probe.
            chart_symbol = self._CHART_SYMBOL_CACHE.get((row.exchange, row.symbol))

            rows = []
            chunk_count = 0
            failed_chunks = 0
            last_error = None
            current_start = start_date
            while current_start <= end_date:
                chunk_count += 1
                current_end = min(current_start + timedelta(days=chunk_days - 1), end_date)
                chunk_start = current_start.strftime("%Y-%m-%d")
                chunk_end = current_end.strftime("%Y-%m-%d")
                candidates = [chart_symbol] if chart_symbol else self._chart_symbols(row)

                # Fetch this chunk with chunk-level retries. A transient
                # failure must NEVER cause us to skip a window - doing so
                # would punch a silent gap into a long 1-minute download.
                # _fetch_candles already retries 429 internally; this is the
                # outer safety net that keeps re-trying the SAME chunk rather
                # than advancing past it. `chunk` stays None only if every
                # attempt failed (-> loud gap warning); an empty list means the
                # chunk legitimately has no candles (weekend / holiday /
                # pre-listing / unresolved index form) and is fine to skip.
                chunk = None
                for attempt in range(self._HISTORY_CHUNK_ATTEMPTS):
                    try:
                        for candidate in candidates:
                            fetched = self._fetch_candles(
                                row, chart_type, chunk_start, chunk_end, candidate
                            )
                            if fetched:
                                if chart_symbol != candidate:
                                    chart_symbol = candidate
                                    self._CHART_SYMBOL_CACHE[(row.exchange, row.symbol)] = candidate
                                chunk = fetched
                                break
                            chunk = []
                            if len(candidates) > 1:
                                time.sleep(self._HISTORY_RATE_DELAY)
                        break
                    except Exception as chunk_error:
                        last_error = chunk_error
                        if attempt < self._HISTORY_CHUNK_ATTEMPTS - 1:
                            backoff = self._HISTORY_RETRY_BACKOFF * (2**attempt)
                            logger.warning(
                                f"Error on candle chunk {chunk_start} to {chunk_end} for "
                                f"{exchange}:{symbol}; retrying chunk "
                                f"({attempt + 1}/{self._HISTORY_CHUNK_ATTEMPTS}) "
                                f"in {backoff:.1f}s: {chunk_error}"
                            )
                            time.sleep(backoff)
                            continue
                        logger.error(
                            f"Error fetching candle chunk {chunk_start} to {chunk_end} "
                            f"for {exchange}:{symbol}: {chunk_error}"
                        )

                if chunk:
                    rows.extend(chunk)
                elif chunk is None:
                    # Every attempt failed - surface a loud, actionable warning
                    # instead of silently leaving a hole in the series.
                    failed_chunks += 1
                    logger.warning(
                        f"POSSIBLE GAP: could not fetch candle chunk {chunk_start} to "
                        f"{chunk_end} for {exchange}:{symbol} after "
                        f"{self._HISTORY_CHUNK_ATTEMPTS} attempts"
                    )

                current_start = current_end + timedelta(days=1)
                if current_start <= end_date:
                    time.sleep(self._HISTORY_RATE_DELAY)

            base_cols = ["timestamp", "open", "high", "low", "close", "volume", "oi"]

            # A partial download degrades to a gap warning above, but if EVERY
            # chunk failed there is no data at all - surface the underlying
            # error rather than an empty frame that looks like "no candles".
            if not rows and chunk_count and failed_chunks == chunk_count:
                raise HDFCSkyAPIError(
                    f"Could not fetch any candles for {exchange}:{symbol}: {last_error}"
                )

            if not rows:
                return pd.DataFrame(columns=base_cols)

            # Keep only the seven leading columns: the live API appends a
            # cumulative-volume column that the documented sample does not
            # show, and a raw DataFrame() would fail on the width mismatch.
            # Rows narrower than seven columns are dropped as malformed.
            rows = [row[:7] for row in rows if len(row) >= 7]
            if not rows:
                return pd.DataFrame(columns=base_cols)

            df = pd.DataFrame(
                rows, columns=["open", "high", "low", "close", "volume", "oi", "timestamp"]
            )
            # HDFC Sky sends day-first strings ("22-10-2024" for daily,
            # "22-10-2024 09:15" for intraday) in IST, with no offset.
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
