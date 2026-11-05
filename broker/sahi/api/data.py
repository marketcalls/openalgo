"""Sahi market data: quotes, depth, history and batch quotes.

Endpoints (broker-api-docs/sahi-api-docs, Market data). Instruments are named
by Sahi's ``instrument_id``, stored as ``token`` in the master contract:

    GET /v1/marketdata/quotes?i=..   up to 100 ids; LTP, volume, OI, DPR band
                                     and 5 or 20 depth levels, prices in paise
    GET /v1/marketdata/candles       one id; 1m 3m 5m 15m 30m 1h 1d; at most
                                     2500 candles, clipped at the START of the
                                     range (page backward with has_more)
    GET /v1/marketdata/optionchain   one underlying + expiry; every strike's
                                     CE and PE with LTP, previous close, OI,
                                     volume and top of book

Sahi's quote carries no open, high, low or previous close. ``get_quotes`` and
``get_depth`` read them from the daily candles (today's candle is included
while the market is open). Batch quotes for options come from the option chain
endpoint, which does carry the previous close, and everything else from the
quotes endpoint; open, high and low are not available in a batch.
"""

from datetime import datetime, time, timedelta, timezone

import pandas as pd

from broker.sahi.api.baseurl import get_headers, get_url
from broker.sahi.api.rate_limiter import sahi_request
from broker.sahi.mapping.transform_data import from_paise
from database.token_db import get_symbol_info, get_token
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
QUOTE_BATCH_SIZE = 100
MAX_CANDLES = 2500
# Bound on backward pages for one history request: 2500 candles a page covers
# about 27 sessions of 1-minute data, so 200 pages is over 20 years of days.
MAX_HISTORY_PAGES = 200
HISTORY_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume", "oi"]


class SahiDataError(Exception):
    """A market-data failure with a message a trader can act on."""


def _get(path, auth, category, params):
    client = get_httpx_client()
    response = sahi_request(
        client, "GET", get_url(path), category, headers=get_headers(auth), params=params, timeout=30
    )
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code != 200:
        message = body.get("message") if isinstance(body, dict) else None
        logger.error(f"Sahi {path} returned HTTP {response.status_code}: {body}")
        if response.status_code == 401:
            raise SahiDataError("Your Sahi session has expired. Log in to OpenAlgo again.")
        if response.status_code == 403:
            raise SahiDataError(
                "Your Sahi API key does not include market data. Create a key with market data access."
            )
        raise SahiDataError(
            message or f"Sahi could not return market data (HTTP {response.status_code})."
        )
    return body


def _instrument_id(symbol, exchange):
    token = get_token(symbol, exchange)
    if not token:
        raise SahiDataError(f"{symbol} was not found on {exchange} in the Sahi master contract.")
    return int(token)


def _levels(levels, count=5):
    """Depth levels in rupees, truncated and padded to ``count``."""
    out = [
        {"price": from_paise(level.get("price")), "quantity": int(level.get("qty") or 0)}
        for level in (levels or [])[:count]
    ]
    while len(out) < count:
        out.append({"price": 0, "quantity": 0})
    return out


def _ist_today():
    return datetime.now(IST).date()


class BrokerData:
    def __init__(self, auth_token):
        self.auth_token = auth_token
        self.timeframe_map = {
            "1m": "1m",
            "3m": "3m",
            "5m": "5m",
            "15m": "15m",
            "30m": "30m",
            "1h": "1h",
            "D": "1d",
        }

    # ---- quotes and depth -------------------------------------------------

    def _quotes(self, instrument_ids):
        """Raw quote dicts by instrument id (missing instruments omitted)."""
        out = {}
        for start in range(0, len(instrument_ids), QUOTE_BATCH_SIZE):
            batch = instrument_ids[start : start + QUOTE_BATCH_SIZE]
            body = _get("/v1/marketdata/quotes", self.auth_token, "quotes", {"i": batch})
            for key, value in (body.get("data") or {}).items():
                if isinstance(value, dict):
                    out[int(key)] = value
        return out

    def _daily_ohlc(self, instrument_id):
        """(open, high, low, prev_close) in rupees from the daily candles.

        Today's in-progress candle is included while the market is open. When
        the latest candle is not today's (before the open, on a holiday) the
        day's open, high and low are unknown and returned as 0, and the latest
        close is the previous close.
        """
        now_ms = int(datetime.now(IST).timestamp() * 1000)
        params = {
            "instrument_id": instrument_id,
            "size": "1d",
            "from": now_ms - 15 * 86400 * 1000,
            "to": now_ms,
            "include_partial": "true",
        }
        try:
            candles = (
                _get("/v1/marketdata/candles", self.auth_token, "candles", params).get("candles")
                or []
            )
        except SahiDataError:
            logger.warning(f"Daily candles unavailable for Sahi instrument {instrument_id}")
            return 0.0, 0.0, 0.0, 0.0
        if not candles:
            return 0.0, 0.0, 0.0, 0.0
        last = candles[-1]
        last_day = datetime.fromtimestamp(last[0] / 1000, tz=IST).date()
        if last_day == _ist_today():
            prev_close = from_paise(candles[-2][4]) if len(candles) > 1 else 0.0
            return from_paise(last[1]), from_paise(last[2]), from_paise(last[3]), prev_close
        return 0.0, 0.0, 0.0, from_paise(last[4])

    def _quote_dict(self, quote, ohlc=(0.0, 0.0, 0.0, 0.0)):
        best_buys = quote.get("best_buys") or []
        best_sells = quote.get("best_sells") or []
        open_, high, low, prev_close = ohlc
        return {
            "ask": from_paise(best_sells[0]["price"]) if best_sells else 0,
            "bid": from_paise(best_buys[0]["price"]) if best_buys else 0,
            "high": high,
            "low": low,
            "ltp": from_paise(quote.get("last_trade_price")),
            "open": open_,
            "prev_close": prev_close,
            "volume": int(quote.get("volume_today") or 0),
            "oi": int(quote.get("open_interest") or 0),
        }

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        instrument_id = _instrument_id(symbol, exchange)
        quote = self._quotes([instrument_id]).get(instrument_id)
        if not quote:
            raise SahiDataError(f"Sahi returned no quote for {symbol} on {exchange}.")
        return self._quote_dict(quote, self._daily_ohlc(instrument_id))

    def get_depth(self, symbol: str, exchange: str) -> dict:
        instrument_id = _instrument_id(symbol, exchange)
        quote = self._quotes([instrument_id]).get(instrument_id)
        if not quote:
            raise SahiDataError(f"Sahi returned no depth for {symbol} on {exchange}.")
        open_, high, low, prev_close = self._daily_ohlc(instrument_id)
        best_buys = quote.get("best_buys") or []
        best_sells = quote.get("best_sells") or []
        return {
            "asks": _levels(best_sells),
            "bids": _levels(best_buys),
            "high": high,
            "low": low,
            "ltp": from_paise(quote.get("last_trade_price")),
            "ltq": 0,
            "oi": int(quote.get("open_interest") or 0),
            "open": open_,
            "prev_close": prev_close,
            "totalbuyqty": sum(int(level.get("qty") or 0) for level in best_buys),
            "totalsellqty": sum(int(level.get("qty") or 0) for level in best_sells),
            "volume": int(quote.get("volume_today") or 0),
        }

    def get_market_depth(self, symbol: str, exchange: str) -> dict:
        return self.get_depth(symbol, exchange)

    # ---- batch quotes -----------------------------------------------------

    def _option_chain_quotes(self, options):
        """Quotes for option symbols from the option chain endpoint.

        Args:
            options: {instrument_id: SymbolData} for CE/PE contracts.

        Returns:
            {instrument_id: quote dict}. Contracts whose chain could not be
            read are left out, for the quotes endpoint to fill.
        """
        groups = {}
        for instrument_id, info in options.items():
            index_exchange = "NSE_INDEX" if info.exchange == "NFO" else "BSE_INDEX"
            cash_exchange = "NSE" if info.exchange == "NFO" else "BSE"
            underlying_id = get_token(info.name, index_exchange) or get_token(
                info.name, cash_exchange
            )
            if not underlying_id or not info.expiry:
                continue
            expiry = datetime.strptime(info.expiry, "%d-%b-%y").strftime("%Y-%m-%d")
            groups.setdefault((int(underlying_id), expiry), set()).add(instrument_id)

        out = {}
        for (underlying_id, expiry), wanted in groups.items():
            try:
                chain = _get(
                    "/v1/marketdata/optionchain",
                    self.auth_token,
                    "optionchain",
                    {"underlying_id": underlying_id, "expiry": expiry},
                )
            except SahiDataError:
                logger.warning(
                    f"Sahi option chain {underlying_id} {expiry} unavailable; using quotes"
                )
                continue
            for row in chain.get("strikes") or []:
                for leg in (row.get("ce"), row.get("pe")):
                    if not leg or leg.get("instrument_id") not in wanted:
                        continue
                    out[leg["instrument_id"]] = {
                        "ask": from_paise(leg.get("top_ask_price")),
                        "bid": from_paise(leg.get("top_bid_price")),
                        "high": 0.0,
                        "low": 0.0,
                        "ltp": from_paise(leg.get("last_trade_price")),
                        "open": 0.0,
                        "prev_close": from_paise(leg.get("prev_close_price")),
                        "volume": int(leg.get("volume_today") or 0),
                        "oi": int(leg.get("open_interest") or 0),
                    }
        return out

    def get_multiquotes(self, symbols: list) -> list:
        """Quotes for many symbols: [{'symbol', 'exchange', 'data'} | {..., 'error'}]."""
        resolved = []
        results = []
        for item in symbols:
            symbol, exchange = item.get("symbol"), item.get("exchange")
            info = get_symbol_info(symbol, exchange)
            if not info or not info.token:
                results.append(
                    {"symbol": symbol, "exchange": exchange, "error": "Symbol not found"}
                )
                continue
            resolved.append((symbol, exchange, int(info.token), info))

        options = {iid: info for _, _, iid, info in resolved if info.instrumenttype in ("CE", "PE")}
        quotes = self._option_chain_quotes(options) if options else {}

        remaining = sorted({iid for _, _, iid, _ in resolved if iid not in quotes})
        if remaining:
            for iid, raw in self._quotes(remaining).items():
                quotes[iid] = self._quote_dict(raw)

        for symbol, exchange, iid, _ in resolved:
            if iid in quotes:
                results.append({"symbol": symbol, "exchange": exchange, "data": quotes[iid]})
            else:
                results.append(
                    {"symbol": symbol, "exchange": exchange, "error": "No quote returned by Sahi"}
                )
        return results

    # ---- history ----------------------------------------------------------

    def get_history(
        self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """Candles as a DataFrame [timestamp, open, high, low, close, volume, oi].

        Intraday timestamps are the true epoch seconds of the candle's IST open
        time; daily candles are stamped at 00:00 UTC of their IST date, the
        OpenAlgo convention.
        """
        size = self.timeframe_map.get(interval)
        if not size:
            raise SahiDataError(
                f"Interval {interval} is not supported by Sahi. Use one of: {', '.join(self.timeframe_map)}."
            )
        instrument_id = _instrument_id(symbol, exchange)

        start = pd.to_datetime(start_date).date()
        end = pd.to_datetime(end_date).date()
        from_ms = int(datetime.combine(start, time(0, 0), tzinfo=IST).timestamp() * 1000)
        to_ms = int(datetime.combine(end, time(23, 59, 59), tzinfo=IST).timestamp() * 1000)
        now_ms = int(datetime.now(IST).timestamp() * 1000)
        to_ms = min(to_ms, now_ms)

        info = get_symbol_info(symbol, exchange)
        want_oi = bool(info and info.instrumenttype in ("FUT", "CE", "PE"))

        rows = []
        pages = 0
        cursor = to_ms
        # Only the first (latest) page can hold the in-progress candle.
        include_partial = end >= _ist_today()
        while cursor >= from_ms:
            params = {"instrument_id": instrument_id, "size": size, "from": from_ms, "to": cursor}
            if include_partial:
                params["include_partial"] = "true"
                include_partial = False
            if want_oi:
                params["oi"] = "true"
            body = _get("/v1/marketdata/candles", self.auth_token, "candles", params)
            candles = body.get("candles") or []
            rows = candles + rows
            pages += 1
            if not body.get("has_more") or not candles:
                break
            if pages >= MAX_HISTORY_PAGES:
                raise SahiDataError(
                    "The requested history is too long to fetch in one request. Ask for a shorter range."
                )
            cursor = candles[0][0] - 1

        if not rows:
            return pd.DataFrame(columns=HISTORY_COLUMNS)

        df = pd.DataFrame(
            [r[:6] + [r[6] if len(r) > 6 else 0] for r in rows],
            columns=["ts", "open", "high", "low", "close", "volume", "oi"],
        )
        for column in ("open", "high", "low", "close"):
            df[column] = df[column] / 100.0
        if size == "1d":
            # IST calendar date of the candle, stamped at 00:00 UTC.
            dates = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.tz_convert(IST).dt.date
            df["timestamp"] = pd.to_datetime(dates).astype("int64") // 10**9
        else:
            df["timestamp"] = df["ts"] // 1000
        df["volume"] = df["volume"].astype("int64")
        df["oi"] = df["oi"].astype("int64")
        df = (
            df[HISTORY_COLUMNS]
            .sort_values("timestamp")
            .drop_duplicates(subset=["timestamp"], keep="last")
        )
        return df.reset_index(drop=True)
