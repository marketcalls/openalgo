# broker/hdfcsecurities/api/data.py
#
# HDFC Securities InvestRight market data.
#
#   PUT /oapi/v1/fetch-ltp   LTP + previous close snapshot (batch capable)
#
# IMPORTANT -- what InvestRight's REST API does and does not offer:
#   /fetch-ltp is the ONLY REST market-data endpoint. It returns exactly two
#   fields, `ltp` and `prev_close`. There is no REST quote, OHLC, depth, open
#   interest or historical-candle endpoint -- route probing found none, and the
#   docs state outright that "for OHLC, volume, market depth, OI and Greeks use
#   the WebSocket feed".
#
#   So this module composes what REST gives us and fills the rest from a
#   short-lived WebSocket snapshot:
#     get_quotes      -> LTP + previous close from REST, and open/high/low/
#                        volume/OI/best bid+ask from a feed snapshot.
#     get_multiquotes -> LTP batch from REST, plus OI for derivative legs from
#                        a single feed snapshot covering the whole batch.
#     get_depth       -> the same snapshot's five bid/ask levels, last-traded
#                        qty, total buy/sell qty and OI; zero-fills on timeout
#                        so a quote never fails purely because the feed was slow.
#     get_history     -> NOT AVAILABLE. InvestRight publishes no historical or
#                        intraday candle API of any kind, so this raises with an
#                        explicit message rather than fabricating candles from
#                        live ticks.

import sys
import threading
import time

from broker.hdfcsecurities.api.baseurl import (
    base_params,
    get_hdfcsecurities_headers,
    get_root_url,
)
from broker.hdfcsecurities.database.master_contract_db import SymToken, db_session
from broker.hdfcsecurities.mapping.transform_data import to_ltp_exchange, ws_scrip_id
from database.token_db import get_br_symbol
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# The snapshot's WebSocket callback fires on a REAL OS thread (the feed client
# uses eventlet-original threads), so the dict it writes must be guarded with a
# REAL lock -- a green (monkey-patched) lock shared across the real/green
# boundary can deadlock under eventlet. Mirror the streaming client.
if "eventlet" in sys.modules:
    import eventlet

    _real_threading = eventlet.patcher.original("threading")
else:
    _real_threading = threading


class HDFCSecuritiesAPIError(Exception):
    pass


class BrokerData:
    def __init__(self, auth_token):
        """InvestRight data handler. `auth_token` is the access token."""
        self.auth_token = auth_token
        # InvestRight has no historical-data API at all, so no interval is
        # serviceable. The map is left empty (rather than omitted) so
        # intervals_service can report "none supported" instead of raising.
        self.timeframe_map = {}

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
                raise HDFCSecuritiesAPIError(f"Could not find instrument for {exchange}:{symbol}")
            session.expunge(row)
        return row

    # --- LTP ------------------------------------------------------------

    _LTP_MAX_ATTEMPTS = 4
    _LTP_RETRY_BACKOFF = 0.5
    # /fetch-ltp takes a list, so a multiquote is one request per chunk. The
    # sibling InvestRight/Sky gateway rejects batches above 10 wholesale with
    # HTTP 400, which would silently zero a whole option-chain page, so stay at
    # 10 even though InvestRight does not document the cap.
    _MULTIQUOTE_MAX_PER_REQUEST = 10
    _MULTIQUOTE_RATE_DELAY = 0.15

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
            for attempt in range(self._LTP_MAX_ATTEMPTS):
                response = client.put(
                    f"{get_root_url()}/oapi/v1/fetch-ltp",
                    headers=get_hdfcsecurities_headers(self.auth_token, with_json=True),
                    params=base_params(),
                    json={"data": instruments},
                )
                # A rate-limited batch must be retried, not dropped: returning
                # {} here surfaces as an LTP of 0.0, which silently corrupts
                # anything derived from it (option greeks, synthetic futures).
                if response.status_code == 429 and attempt < self._LTP_MAX_ATTEMPTS - 1:
                    delay = self._LTP_RETRY_BACKOFF * (2**attempt)
                    logger.warning(
                        f"HDFC Securities LTP rate-limited for {len(instruments)} "
                        f"instruments, retrying in {delay:.1f}s"
                    )
                    time.sleep(delay)
                    continue
                break

            # Check the status by hand: raise_for_status()'s message embeds the
            # request URL, which carries the API key as a query parameter.
            if response.status_code != 200:
                logger.warning(
                    f"HDFC Securities LTP request failed for {len(instruments)} instruments "
                    f"(HTTP {response.status_code}): {response.text[:200]!r}"
                )
                return {}
            payload = response.json()
        except Exception as e:
            logger.warning(
                f"HDFC Securities LTP request failed for {len(instruments)} instruments: {e}"
            )
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

    # --- WebSocket snapshots --------------------------------------------

    # OpenAlgo exchanges whose instruments carry open interest.
    _OI_EXCHANGES = frozenset({"NFO", "BFO", "CDS", "MCX"})
    # Transient feed-snapshot budget: how long to wait for the handshake and how
    # long to hold the socket open collecting packets. Collection early-exits as
    # soon as every requested token satisfies the caller's completeness test,
    # so the full window only elapses when the feed is genuinely quiet.
    _SNAPSHOT_CONNECT_TIMEOUT = 8.0
    _SNAPSHOT_COLLECT_WINDOW = 3.0

    def _collect_feed_snapshot(self, instruments, is_complete):
        """Collect one market-data packet per instrument from the WebSocket feed.

        InvestRight serves OHLC, volume, depth, OI, last-traded-qty and total
        buy/sell qty only over the market-data WebSocket, so REST-facing methods
        that need them open a short-lived feed connection, subscribe the batch,
        keep the most complete tick seen per token, and close the socket.

        Args:
            instruments: [(oa_exchange, token), ...].
            is_complete: predicate on a tick; a token stops updating once one of
                its ticks satisfies it, and the collection ends early when every
                requested token is complete.
        Returns {token_str: tick}. Never raises and always closes the socket --
        on any failure it returns whatever it gathered (possibly empty) so the
        REST-derived fields still flow.
        """
        if not instruments:
            return {}
        # Lazy import keeps the streaming stack out of the plain REST paths.
        from broker.hdfcsecurities.streaming.hdfcsecurities_websocket import (
            HDFCSecuritiesWebSocket,
        )

        scrip_ids = [ws_scrip_id(oa_exchange, tok) for oa_exchange, tok in instruments]
        wanted = {str(tok) for _, tok in instruments}
        snapshot = {}
        # The callback runs on the feed client's real OS thread; guard the dict
        # with a real lock (see the _real_threading note at module top).
        lock = _real_threading.Lock()

        def on_ticks(ticks):
            with lock:
                for tick in ticks:
                    tok = str(tick.get("token"))
                    if tok not in wanted:
                        continue
                    # Merge successive packets per token: depth rides on the MBP
                    # packet while OI can arrive on a separate one, so accumulate
                    # fields and never let a later partial frame zero out a value
                    # an earlier one already filled.
                    merged = snapshot.setdefault(tok, {})
                    for key, value in tick.items():
                        if not value and merged.get(key):
                            continue
                        merged[key] = value

        ws = HDFCSecuritiesWebSocket(access_token=self.auth_token, on_ticks=on_ticks)
        try:
            ws.start()
            if not ws.wait_for_connection(timeout=self._SNAPSHOT_CONNECT_TIMEOUT):
                logger.warning("HDFC Securities feed snapshot: did not connect")
                return {}
            ws.subscribe_scrips(scrip_ids, subscription_type="ALL")
            deadline = time.monotonic() + self._SNAPSHOT_COLLECT_WINDOW
            while time.monotonic() < deadline:
                with lock:
                    done = all(t in snapshot and is_complete(snapshot[t]) for t in wanted)
                if done:
                    break
                time.sleep(0.1)
        except Exception as e:
            logger.warning(f"HDFC Securities feed snapshot failed: {e}")
        finally:
            ws.stop()

        with lock:
            return dict(snapshot)

    def _fetch_quote_snapshot(self, oa_exchange, token):
        """OHLC / volume / depth / OI for one instrument, or {} on timeout."""
        need_oi = oa_exchange in self._OI_EXCHANGES

        def is_complete(tick):
            if need_oi and not tick.get("oi"):
                return False
            return bool(tick.get("depth")) or bool(tick.get("ltp"))

        return self._collect_feed_snapshot([(oa_exchange, token)], is_complete=is_complete).get(
            str(token), {}
        )

    def _fetch_oi_snapshot(self, instruments):
        """Open interest for derivative legs, {token_str: oi}. See
        _collect_feed_snapshot; empty for any leg that never reported OI."""
        snapshot = self._collect_feed_snapshot(
            instruments, is_complete=lambda tick: bool(tick.get("oi"))
        )
        oi_by_token = {tok: tick["oi"] for tok, tick in snapshot.items() if tick.get("oi")}
        if instruments and len(oi_by_token) < len(instruments):
            logger.info(
                f"HDFC Securities OI snapshot: OI for {len(oi_by_token)}/"
                f"{len(instruments)} instruments"
            )
        return oi_by_token

    @staticmethod
    def _depth_levels(levels):
        """Normalize a WebSocket depth side to exactly five {price, quantity}."""
        out = [
            {
                "price": float(level.get("price", 0) or 0),
                "quantity": int(level.get("quantity", 0) or 0),
            }
            for level in (levels or [])[:5]
        ]
        while len(out) < 5:
            out.append({"price": 0.0, "quantity": 0})
        return out

    @staticmethod
    def _best(levels):
        """Best price on one side of the book, or 0.0 when it is empty."""
        for level in levels or []:
            price = float(level.get("price", 0) or 0)
            if price:
                return price
        return 0.0

    # --- public API -----------------------------------------------------

    def get_quotes(self, symbol, exchange):
        """OpenAlgo quote dict.

        LTP and previous close come from REST, which is authoritative and always
        available. Open/high/low/volume/OI and the best bid+ask come from a
        short feed snapshot and degrade to 0 if the feed does not answer in
        time, so a quote never fails purely because the socket was slow.
        """
        try:
            row = self._lookup(symbol, exchange)
            ltp_data = self._ltp_for_row(row)
            tick = self._fetch_quote_snapshot(row.exchange, str(row.token))
            book = tick.get("depth") or {}

            return {
                "ask": self._best(book.get("sell")),
                "bid": self._best(book.get("buy")),
                "high": float(tick.get("high", 0) or 0),
                "low": float(tick.get("low", 0) or 0),
                # Prefer the REST LTP; fall back to the feed's when the REST
                # snapshot omitted the instrument.
                "ltp": ltp_data["ltp"] or float(tick.get("ltp", 0) or 0),
                "open": float(tick.get("open", 0) or 0),
                "prev_close": ltp_data["prev_close"] or float(tick.get("close", 0) or 0),
                "volume": int(tick.get("volume", 0) or 0),
                "oi": int(tick.get("oi", 0) or 0),
            }
        except HDFCSecuritiesAPIError:
            raise
        except Exception as e:
            logger.exception(f"Error fetching HDFC Securities quotes: {e}")
            raise HDFCSecuritiesAPIError(f"Error fetching quotes: {e}") from e

    def get_depth(self, symbol, exchange):
        """OpenAlgo 5-level market depth.

        There is no REST depth endpoint, so the whole book plus last-traded qty,
        total buy/sell qty and OI come from one feed snapshot; LTP and previous
        close still come from REST. The book zero-fills if the snapshot times
        out, so depth never fails outright.
        """
        try:
            row = self._lookup(symbol, exchange)
            ltp_data = self._ltp_for_row(row)
            tick = self._fetch_quote_snapshot(row.exchange, str(row.token))
            book = tick.get("depth") or {}

            return {
                "asks": self._depth_levels(book.get("sell")),
                "bids": self._depth_levels(book.get("buy")),
                "high": float(tick.get("high", 0) or 0),
                "low": float(tick.get("low", 0) or 0),
                "ltp": ltp_data["ltp"] or float(tick.get("ltp", 0) or 0),
                "ltq": int(tick.get("ltq", 0) or 0),
                "oi": int(tick.get("oi", 0) or 0),
                "open": float(tick.get("open", 0) or 0),
                "prev_close": ltp_data["prev_close"] or float(tick.get("close", 0) or 0),
                "totalbuyqty": int(tick.get("total_buy_quantity", 0) or 0),
                "totalsellqty": int(tick.get("total_sell_quantity", 0) or 0),
                "volume": int(tick.get("volume", 0) or 0),
            }
        except HDFCSecuritiesAPIError:
            raise
        except Exception as e:
            logger.exception(f"Error fetching HDFC Securities market depth: {e}")
            raise HDFCSecuritiesAPIError(f"Error fetching market depth: {e}") from e

    def get_market_depth(self, symbol, exchange):
        """Alias for get_depth (parity with brokers that expose get_market_depth)."""
        return self.get_depth(symbol, exchange)

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

        LTP and previous close come from the REST batch. open/high/low/volume
        stay 0 -- filling them would mean holding the feed open until every leg
        has reported a full MBP packet, which an option chain cannot afford; use
        get_quotes() for a single enriched quote. Open interest IS filled, from
        one feed snapshot covering every derivative leg at once, because the
        option tools depend on it.
        """
        # Resolve every leg to its master-contract row once -- both the LTP
        # batch and the OI snapshot need the token, and _lookup is the only DB
        # hit per symbol.
        resolved = []  # (item, oa_exchange, token, ltp_exchange_code)
        skipped = []
        for item in symbols:
            try:
                row = self._lookup(item["symbol"], item["exchange"])
            except Exception as e:
                logger.warning(f"Skipping {item.get('exchange')}:{item.get('symbol')}: {e}")
                skipped.append(self._leg_error(item, str(e)))
                continue
            resolved.append((item, row.exchange, str(row.token), to_ltp_exchange(row.exchange)))

        if not resolved:
            return skipped

        ltp = {}
        instruments = [{"exchange": lx, "token": tok} for _, _, tok, lx in resolved]
        for start in range(0, len(instruments), self._MULTIQUOTE_MAX_PER_REQUEST):
            batch = instruments[start : start + self._MULTIQUOTE_MAX_PER_REQUEST]
            ltp.update(self._fetch_ltp(batch))
            if start + self._MULTIQUOTE_MAX_PER_REQUEST < len(instruments):
                time.sleep(self._MULTIQUOTE_RATE_DELAY)

        oi_targets = [(oax, tok) for _, oax, tok, _ in resolved if oax in self._OI_EXCHANGES]
        oi_by_token = self._fetch_oi_snapshot(oi_targets)

        results = list(skipped)
        for item, _, tok, ltp_code in resolved:
            quote = ltp.get((ltp_code, tok))
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
                        "oi": oi_by_token.get(tok, 0),
                    },
                }
            )
        return results

    # --- history --------------------------------------------------------

    _NO_HISTORY_MESSAGE = (
        "HDFC Securities InvestRight does not publish a historical or intraday "
        "candle API -- /fetch-ltp is its only REST market-data endpoint, and "
        "everything else (OHLC, depth, OI) is live-only over the WebSocket "
        "feed. Use OpenAlgo's Historify store or another data provider for "
        "historical candles on this broker."
    )

    def get_history(self, symbol, exchange, timeframe, from_date, to_date):
        """Not available on InvestRight.

        Raises rather than returning an empty DataFrame: an empty frame reads as
        "no trades in that window" to every caller downstream (backtests,
        indicators, charts), which would silently produce wrong results instead
        of a visible, actionable failure.
        """
        raise HDFCSecuritiesAPIError(self._NO_HISTORY_MESSAGE)

    def get_intervals(self):
        """Supported history intervals: none. See get_history."""
        return []
