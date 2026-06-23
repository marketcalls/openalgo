# broker/arrow/api/data.py

import time
from datetime import timedelta

import httpx
import pandas as pd

from broker.arrow.api.baseurl import HISTORICAL_URL, ROOT_URL, get_arrow_headers
from broker.arrow.database.master_contract_db import SymToken, db_session
from broker.arrow.mapping.exchange import (
    QUOTE_UNSUPPORTED_EXCHANGES,
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


# Arrow's INDEX quote endpoint uses its own symbol vocabulary (probed live):
#   - the 5 NSE derivative indices answer ONLY to their underlying name
#     (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50 -- "NIFTY 50",
#     "NIFTY BANK" etc. are rejected),
#   - everything else answers to the UPPERCASED master-contract display name
#     ("NIFTY IT", "INDIA VIX", "HANGSENG BEES-NAV", BSE codes like "SMLCAP"),
#   - MCX iCOMDEX indices are not served by this endpoint at all (their data
#     still streams over the websocket by token).
# We therefore try candidates per index and cache the verified name by token.
_INDEX_QUOTE_NAMES: dict[str, str] = {}  # token -> verified quote symbol
_INDEX_QUOTE_UNSUPPORTED: set[str] = set()  # tokens rejected for every candidate


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

    def _quote_index(self, mode, symbol, br_symbol, token):
        """Quote an index, resolving Arrow's INDEX-exchange symbol vocabulary.

        Tries the OpenAlgo symbol, then the uppercased display name, then the
        raw display name; caches whichever the API accepts (keyed by token) so
        the fallback costs extra requests only on first use.
        """
        token = str(token)
        cached = _INDEX_QUOTE_NAMES.get(token)
        if cached:
            return self._quote(mode, cached, "INDEX")
        if token in _INDEX_QUOTE_UNSUPPORTED:
            raise ArrowAPIError(
                f"Arrow's quote API does not serve index {symbol} (websocket streaming still works)"
            )

        candidates = []
        for cand in (symbol, str(br_symbol).upper(), str(br_symbol)):
            if cand and cand not in candidates:
                candidates.append(cand)

        last_err = None
        for cand in candidates:
            try:
                data = self._quote(mode, cand, "INDEX")
                _INDEX_QUOTE_NAMES[token] = cand
                return data
            except httpx.HTTPStatusError as e:
                if e.response is not None and e.response.status_code == 400:
                    last_err = e
                    continue
                raise

        _INDEX_QUOTE_UNSUPPORTED.add(token)
        raise ArrowAPIError(
            f"Arrow's quote API rejected every symbol candidate for index {symbol} ({candidates})"
        ) from last_err

    def _fetch_quote(self, mode, symbol, exchange):
        """Lookup + quote with index-aware symbol resolution."""
        if exchange in QUOTE_UNSUPPORTED_EXCHANGES:
            raise ArrowAPIError(
                f"Arrow's quote API does not serve the {exchange} exchange "
                "(verified live; the official SDK has no code for it either). "
                "Use websocket streaming for live prices on this exchange."
            )
        br_symbol, token, arrow_exchange = self._lookup(symbol, exchange)
        if arrow_exchange == "INDEX":
            return self._quote_index(mode, symbol, br_symbol, token)
        return self._quote(mode, br_symbol, arrow_exchange)

    def _resolve_index_quote_name(self, symbol, br_symbol, token):
        """Return the verified Arrow quote name for an index, probing (and
        caching) it via a cheap ltp request if not yet known. None if Arrow's
        quote API does not serve this index (e.g. MCX iCOMDEX)."""
        token = str(token)
        if token in _INDEX_QUOTE_NAMES:
            return _INDEX_QUOTE_NAMES[token]
        if token in _INDEX_QUOTE_UNSUPPORTED:
            return None
        try:
            self._quote_index("ltp", symbol, br_symbol, token)
            return _INDEX_QUOTE_NAMES.get(token)
        except ArrowAPIError:
            return None

    # --- public API -----------------------------------------------------

    def get_quotes(self, symbol, exchange):
        """Return the OpenAlgo quote dict. Uses Arrow `full` mode so bid/ask are
        available. Works for NSE_INDEX/BSE_INDEX (exchange -> INDEX)."""
        try:
            q = self._fetch_quote("full", symbol, exchange)

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
            q = self._fetch_quote("full", symbol, exchange)

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

    # Two independent Arrow limits govern multiquotes:
    #   1. /info/quotes accepts AT MOST 100 instruments per request -- a hard
    #      server cap, verified live (100 -> 200 OK, 101 -> 500 error). NOT
    #      tunable; raising it breaks every batch.
    #   2. Market Data rate limit: 10 req/sec (docs/rate-limits).
    # There is NO cap on the total symbol count: any size set (500+) is
    # looped in 100-instrument requests, throttled under 10 req/sec
    # (500 symbols = 5 requests, ~0.8s total).
    _MULTIQUOTE_MAX_PER_REQUEST = 100
    _MULTIQUOTE_RATE_DELAY = 0.15  # ~6-7 req/sec, safely under Arrow's 10/sec
    _HISTORY_RATE_DELAY = 0.15  # throttle between historical date-chunks

    @staticmethod
    def _leg_error(item, message):
        """One result entry flagging a single leg as failed. Mirrors the Angel /
        Zerodha multiquotes contract: every requested leg is accounted for, so
        callers (e.g. the sandbox engine) can see exactly which symbols are
        missing rather than getting a silently short list."""
        return {"symbol": item.get("symbol"), "exchange": item.get("exchange"), "error": message}

    @staticmethod
    def _format_quote(q):
        """Arrow FULL-quote payload -> OpenAlgo quote dict (same shape as get_quotes)."""
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

    def get_multiquotes(self, symbols: list) -> list:
        """Get real-time quotes for multiple symbols with automatic batching.

        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys
                     Example: [{'symbol': 'SBIN', 'exchange': 'NSE'}, ...]
        Returns:
            list: One entry per requested leg --
                  [{'symbol': 'SBIN', 'exchange': 'NSE', 'data': {...}}, ...]
                  or {'symbol', 'exchange', 'error'} for legs that fail. A
                  failing batch never sinks the rest (a 500 on one batch used to
                  discard every other quote and stall sandbox fills/square-off).
        """
        try:
            all_results = []
            n = len(symbols)
            for i in range(0, n, self._MULTIQUOTE_MAX_PER_REQUEST):
                batch = symbols[i : i + self._MULTIQUOTE_MAX_PER_REQUEST]
                all_results.extend(self._process_quotes_batch(batch))
                # Rate limit delay between batches
                if i + self._MULTIQUOTE_MAX_PER_REQUEST < n:
                    time.sleep(self._MULTIQUOTE_RATE_DELAY)
            return all_results
        except Exception as e:
            logger.exception("Error fetching multiquotes")
            raise ArrowAPIError(f"Error fetching multiquotes: {e}") from e

    def _process_quotes_batch(self, symbols: list) -> list:
        """Process a single batch of symbols (internal method).

        Builds the request body + token map, fetches quotes, then builds results
        from the token map so every requested leg is accounted for -- skipped and
        missing legs become error entries rather than silently disappearing
        (matches Angel/Zerodha)."""
        body = []
        token_map = {}  # token(str) -> original {symbol, exchange}
        skipped_symbols = []  # legs we can't resolve / can't send

        for item in symbols:
            symbol = item["symbol"]
            exchange = item["exchange"]

            if exchange in QUOTE_UNSUPPORTED_EXCHANGES:
                # CDS/BCD/NCO would 400 the entire batch; report, don't send.
                logger.warning(f"Skipping {symbol} on {exchange}: exchange not supported by Arrow quotes")
                skipped_symbols.append(self._leg_error(item, "Exchange not supported by Arrow quotes"))
                continue

            try:
                br_symbol, token, arrow_exchange = self._lookup(symbol, exchange)
            except Exception as e:
                logger.warning(f"Skipping {symbol} on {exchange}: {e}")
                skipped_symbols.append(self._leg_error(item, str(e)))
                continue

            if arrow_exchange == "INDEX":
                # A single bad symbol 400s the whole batch, so resolve the
                # index's quote name first (cached after the first probe).
                name = self._resolve_index_quote_name(symbol, br_symbol, token)
                if not name:
                    skipped_symbols.append(self._leg_error(item, "Index not served by Arrow quote API"))
                    continue
                body.append({"exchange": "INDEX", "symbol": name})
            else:
                body.append({"exchange": arrow_exchange, "symbol": br_symbol})
            token_map[str(token)] = item

        # Return skipped symbols if no valid instruments
        if not token_map:
            return skipped_symbols

        # Fetch quotes and index the response by token
        quotes_by_token = self._fetch_quotes(body)

        # Build results from token_map so missing legs are reported, not dropped
        results = []
        for token_str, original in token_map.items():
            quote = quotes_by_token.get(token_str)
            if quote is None:
                results.append(self._leg_error(original, "No quote data available"))
                continue
            results.append(
                {"symbol": original["symbol"], "exchange": original["exchange"], "data": self._format_quote(quote)}
            )

        # Include skipped symbols in results
        return skipped_symbols + results

    def _fetch_quotes(self, body: list) -> dict:
        """POST the request body to /info/quotes/full and index the response by
        token. Returns {token(str): quote_dict}, or {} on failure -- never
        raises, so callers turn missing tokens into per-leg errors.

        On an HTTP error the server's own response body is logged: it's the only
        thing that explains a 500/400 (a mis-mapped symbol, e.g. an NSE equity
        sent without its '-EQ' series suffix, surfaces here as "unable to get
        quotes"), and the request sample distinguishes that from an Arrow-side
        outage."""
        try:
            client = get_httpx_client()
            headers = get_arrow_headers(self.auth_token, with_json=True)
            response = client.post(f"{ROOT_URL}/info/quotes/full", headers=headers, json=body)
            response.raise_for_status()
            data = response.json().get("data", [])
            return {str(q.get("token")): q for q in data}
        except httpx.HTTPStatusError as e:
            detail = (e.response.text or "").strip().replace("\n", " ")[:300]
            logger.warning(
                f"Arrow quotes {e.response.status_code} for {len(body)} instruments. "
                f"Response: {detail}. Sample request: {body[:3]}"
            )
        except Exception as e:
            logger.warning(f"Arrow quotes request failed for {len(body)} instruments: {e}")
        return {}

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
