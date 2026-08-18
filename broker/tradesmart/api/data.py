import json
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import pandas as pd

from broker.tradesmart.api.baseurl import parse_auth, post, resolve_uid
from broker.tradesmart.api.rate_limiter import (
    MAX_RETRIES,
    TRADESMART_MAX_PER_SECOND,
    apply_rate_limit,
    is_rate_limit_error,
    retry_delay,
)
from database.token_db import get_br_symbol, get_token
from utils.logging import get_logger

logger = get_logger(__name__)


def _as_float(value, default=0.0):
    """Noren numbers arrive as strings, and as ``''`` or absent when unset."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value, default=0):
    """Integer form of :func:`_as_float`; volumes and OI still arrive as '123.0'."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _normalize_data_exchange(exchange):
    """Map OpenAlgo index pseudo-exchanges to their parent cash exchange for data."""
    if exchange == "NSE_INDEX":
        return "NSE"
    if exchange == "BSE_INDEX":
        return "BSE"
    return exchange


def _get_api_response(endpoint, auth, payload, retry_count=0):
    """Rate-limited POST returning parsed JSON (dict or list).

    Paced by the shared per-user gate (see broker.tradesmart.api.rate_limiter):
    every endpoint bills against the same 10/sec + 120/min budget.

    Retries with exponential backoff when TradeSmart reports a rate-limit hit,
    so a burst of quote requests (e.g. a 90+ symbol option chain or the OI
    tracker) degrades to slower-but-successful instead of failing the batch.
    """
    apply_rate_limit(endpoint)
    payload.setdefault("uid", resolve_uid(auth))
    response = post(endpoint, payload, auth)
    parsed = json.loads(response.text)

    if is_rate_limit_error(parsed) and retry_count < MAX_RETRIES:
        delay = retry_delay(retry_count)
        logger.warning(
            f"TradeSmart rate limit hit on {endpoint} ({parsed.get('emsg')}). "
            f"Retrying in {delay}s (attempt {retry_count + 1}/{MAX_RETRIES})"
        )
        time.sleep(delay)
        return _get_api_response(endpoint, auth, payload, retry_count + 1)

    return parsed


# ---------------------------------------------------------------------------
# WebSocket-backed bulk quotes
#
# Why this exists:
# TradeSmart caps REST at 10 requests/sec and 120/min *per user* (see
# ``broker.tradesmart.api.rate_limiter``), and Noren exposes no batch-quote
# endpoint -- ``/GetQuotes`` takes exactly one token. An option chain of 41
# strikes is 82 legs, so the REST path costs 82 calls: about 10 seconds against
# the per-second gate, and 164 calls/minute against a 110/minute budget once the
# UI refreshes every 30 seconds. It cannot be tuned into working; there is no
# pacing of 82 calls that fits a 120/minute ceiling twice a minute.
#
# The streaming API has no such problem. One subscribe message carries every
# token::
#
#     {"t": "d", "k": "NFO|54321#NFO|54322#..."}
#
# and the broker answers with a ``dk`` acknowledgement per token containing the
# full snapshot -- ltp, OHLC, volume, OI and five levels of depth. That is the
# whole chain in a single round trip, and it costs nothing against the REST
# budget. The docs note that "touchline and depth messages after the first
# acknowledgement may contain only the changed fields", which is why updates are
# merged into the snapshot rather than replacing it.
#
# Depth (``t=d``) rather than touchline (``t=t``) because the option chain needs
# bid/ask and quantities, which touchline does not carry. The browser's own
# option-chain subscription uses Depth mode for the same reason.
#
# Connection model:
# The socket lives in a module-level registry, NOT on the BrokerData instance:
# ``services/quotes_service.py`` and ``services/option_chain_service.py`` build a
# fresh ``BrokerData(auth_token)`` for every request, so an instance attribute is
# empty on arrival and the connection would be rebuilt and re-authenticated on
# every call. This mirrors ``broker.aliceblue.api.data``, which hit exactly that
# problem.
#
# Keyed by bearer token so a re-login gets a fresh socket instead of reusing one
# authenticated with a dead token. OpenAlgo is single-user and single-broker per
# instance, so any key other than the current one is stale by definition and is
# closed when a new one appears -- that keeps the registry at one live socket
# without needing a logout hook.
#
# Opening a second Noren session is safe here: TradeSmart already runs two
# concurrently in production, the market-data adapter
# (``broker/tradesmart/streaming/tradesmart_adapter.py``) and the order-update
# adapter (``tradesmart_order_adapter.py``), which the latter documents as
# deliberately "its own connection rather than" a shared one.
#
# Subscriptions are left open after a fetch so the next poll is served from the
# warm snapshot cache instead of another round trip, bounded by
# ``MAX_SUBSCRIBED_SCRIPS`` with least-recently-used eviction.
# ---------------------------------------------------------------------------

#: Resolved on first use by :func:`_websocket_cls`. Tests substitute a double
#: by setting this directly.
TradeSmartWebSocket = None


def _websocket_cls():
    """The Noren websocket client, imported lazily.

    Not a module-scope import for two reasons. ``broker.tradesmart.streaming``
    imports the market-data adapter in its ``__init__``, that adapter imports
    ``websocket_proxy``, and ``websocket_proxy.__init__`` imports the adapter
    back -- so entering the streaming package first raises ImportError on the
    half-built module. Importing ``websocket_proxy`` first resolves the cycle
    the same way the running app does.

    Deferring it also keeps the whole proxy stack out of the import path of
    ``broker.tradesmart.api.data``, which every quote request loads and which
    otherwise has no reason to pull in the streaming server.
    """
    global TradeSmartWebSocket
    if TradeSmartWebSocket is None:
        import websocket_proxy  # noqa: F401  (import for cycle ordering only)
        from broker.tradesmart.streaming.tradesmart_websocket import (
            TradeSmartWebSocket as _cls,
        )

        TradeSmartWebSocket = _cls
    return TradeSmartWebSocket


#: Upper bound on scrips held subscribed on the shared socket. An option chain
#: is ~82 legs, so this absorbs several underlyings and expiries before
#: evicting. Well under the 1000/connection ceiling the proxy assumes.
MAX_SUBSCRIBED_SCRIPS = 500

#: How long to wait for the acknowledgements of a freshly subscribed batch.
#: Already-subscribed scrips are served from cache and do not wait at all.
SNAPSHOT_TIMEOUT = 4.0

_POLL_INTERVAL = 0.02

#: Noren message types carrying market data: depth/touchline acknowledgements
#: (full snapshot) and their subsequent feeds (changed fields only).
_DATA_MESSAGE_TYPES = frozenset({"dk", "df", "tk", "tf"})

_REGISTRY: dict[str, "_QuoteStream"] = {}
_REGISTRY_LOCK = threading.Lock()


def scrip_key(exchange: str, token: str) -> str:
    """Noren subscription key for one instrument, ``EXCHANGE|TOKEN``."""
    return f"{exchange}|{token}"


class _QuoteStream:
    """One authenticated Noren socket plus the snapshot cache it feeds.

    Thread-safe: the websocket reader thread writes snapshots while request
    threads read them.
    """

    def __init__(self, uid: str, bearer: str):
        self._uid = uid
        self._bearer = bearer
        self._lock = threading.RLock()
        self._snapshots: dict[str, dict] = {}
        # scrip -> last time it was asked for; ordered oldest-first for eviction.
        self._subscribed: OrderedDict[str, float] = OrderedDict()
        self._ws: TradeSmartWebSocket | None = None

    # -- connection ------------------------------------------------------

    def _ensure_connected(self) -> bool:
        """Connect if needed. Returns whether a live socket is available."""
        with self._lock:
            if self._ws is not None and self._ws.is_connected():
                return True

            # Drop whatever was there before replacing it, so a dead socket and
            # its reader/heartbeat threads are not left behind.
            self._close_locked()

            ws = _websocket_cls()(
                user_id=self._uid,
                actid=self._uid,
                accesstoken=self._bearer,
                on_message=self._on_message,
            )
            if not ws.connect():
                logger.warning("TradeSmart quote stream failed to connect")
                try:
                    ws.stop()
                except Exception as exc:
                    logger.warning(f"Error stopping unconnected quote stream: {exc}")
                return False

            self._ws = ws
            # A new socket has none of the old subscriptions, and the cached
            # snapshots behind them are no longer being refreshed.
            self._subscribed.clear()
            self._snapshots.clear()
            logger.info("TradeSmart quote stream connected")
            return True

    def _close_locked(self) -> None:
        """Stop the socket and forget its state. Caller holds the lock."""
        ws, self._ws = self._ws, None
        self._subscribed.clear()
        self._snapshots.clear()
        if ws is None:
            return
        try:
            ws.stop()
        except Exception as exc:
            logger.warning(f"Error closing TradeSmart quote stream: {exc}")

    def stop(self) -> None:
        with self._lock:
            self._close_locked()

    # -- feed ------------------------------------------------------------

    def _on_message(self, _ws, message: str) -> None:
        """Merge one feed message into the snapshot cache.

        Noren sends the complete record on the first acknowledgement and only
        changed fields afterwards, so fields are merged rather than replaced --
        a delta carrying just ``lp`` must not erase OI and depth.
        """
        try:
            data = json.loads(message)
        except (json.JSONDecodeError, TypeError):
            return

        if data.get("t") not in _DATA_MESSAGE_TYPES:
            return

        exchange = data.get("e")
        token = data.get("tk")
        if not exchange or not token:
            return

        key = scrip_key(exchange, token)
        with self._lock:
            # Only track what we currently hold a subscription for. Eviction
            # walks _subscribed, so a snapshot keyed outside it could never be
            # reclaimed: an unsubscribe the broker rejected, or ticks still in
            # flight for a scrip just given back, would grow this dict for the
            # life of the worker. _subscribed is written before the subscribe
            # message goes out, so acknowledgements are never dropped as
            # untracked.
            if key not in self._subscribed:
                return

            snapshot = self._snapshots.get(key)
            if snapshot is None:
                self._snapshots[key] = dict(data)
            else:
                snapshot.update(data)

    # -- subscription ----------------------------------------------------

    def _evict_locked(self, keep: set[str]) -> None:
        """Unsubscribe least-recently-used scrips until back under the cap.

        ``keep`` is the current request's scrips, which are never evicted.
        """
        stale = []
        while len(self._subscribed) > MAX_SUBSCRIBED_SCRIPS:
            for key in list(self._subscribed):
                if key not in keep:
                    del self._subscribed[key]
                    self._snapshots.pop(key, None)
                    stale.append(key)
                    break
            else:
                # Everything left belongs to this request; nothing to give back.
                break

        if stale and self._ws is not None:
            try:
                self._ws.unsubscribe_depth("#".join(stale))
            except Exception as exc:
                logger.warning(f"Error unsubscribing {len(stale)} stale scrips: {exc}")

    def snapshots(self, scrips: list[str], timeout: float = SNAPSHOT_TIMEOUT) -> dict[str, dict]:
        """Return the latest snapshot for each of ``scrips``.

        Subscribes anything not already subscribed, then waits until every
        requested scrip has data or ``timeout`` elapses. Returns whatever
        arrived -- partial results are useful, the caller backfills the rest.
        Returns ``{}`` when no socket could be established, which is the
        caller's signal to fall back to REST.
        """
        if not scrips:
            return {}

        if not self._ensure_connected():
            return {}

        requested = set(scrips)
        now = time.monotonic()

        with self._lock:
            fresh = [key for key in scrips if key not in self._subscribed]
            for key in scrips:
                self._subscribed[key] = now
                self._subscribed.move_to_end(key)
            self._evict_locked(requested)
            ws = self._ws

        if fresh and ws is not None:
            # One message for the whole batch; this is the entire point.
            if not ws.subscribe_depth("#".join(fresh)):
                logger.warning(f"TradeSmart depth subscribe failed for {len(fresh)} scrips")
                with self._lock:
                    for key in fresh:
                        self._subscribed.pop(key, None)
                return {}
            logger.info(f"TradeSmart quote stream subscribed {len(fresh)} new scrips")

        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                missing = [key for key in scrips if key not in self._snapshots]
            if not missing or time.monotonic() >= deadline:
                break
            time.sleep(_POLL_INTERVAL)

        with self._lock:
            found = {key: dict(self._snapshots[key]) for key in scrips if key in self._snapshots}

        if len(found) < len(scrips):
            logger.info(
                f"TradeSmart quote stream returned {len(found)}/{len(scrips)} snapshots; "
                "remainder falls back to REST"
            )
        return found


def get_quote_stream(auth_token: str) -> _QuoteStream | None:
    """The pooled stream for ``auth_token``, creating it if needed.

    Returns None when the token carries no usable credentials.
    """
    uid = resolve_uid(auth_token)
    _, bearer = parse_auth(auth_token)
    if not uid or not bearer:
        logger.warning("Cannot start TradeSmart quote stream: missing uid or access token")
        return None

    with _REGISTRY_LOCK:
        existing = _REGISTRY.get(bearer)
        if existing is not None:
            return existing

        # Single-user, single-broker instance: any other key is a token this
        # process has already replaced, so close it instead of leaking its
        # socket and threads until shutdown.
        stale = list(_REGISTRY.values())
        _REGISTRY.clear()
        stream = _QuoteStream(uid, bearer)
        _REGISTRY[bearer] = stream

    for old in stale:
        old.stop()

    return stream


def close_all_streams() -> None:
    """Disconnect and drop every pooled quote stream.

    For shutdown and for logout, where the session behind these connections is
    about to be revoked. Without it the sockets and their reader and heartbeat
    threads would outlive the session that authenticated them.
    """
    with _REGISTRY_LOCK:
        streams = list(_REGISTRY.values())
        _REGISTRY.clear()
    for stream in streams:
        stream.stop()


class BrokerData:
    def __init__(self, auth_token):
        """Initialize TradeSmart data handler with an access token."""
        self.auth_token = auth_token
        # OpenAlgo interval -> TradeSmart TPSeries interval (minutes). 'D' -> EOD.
        self.timeframe_map = {
            "1m": "1",
            "3m": "3",
            "5m": "5",
            "10m": "10",
            "15m": "15",
            "30m": "30",
            "1h": "60",
            "2h": "120",
            "D": "D",
        }

    def _quote_dict(self, response):
        """Build the OpenAlgo quote dict from a Noren market-data record.

        Serves both ``/GetQuotes`` responses and streaming depth snapshots --
        they share Noren's field names. Values are coerced defensively because
        the feed sends numbers as strings and omits or blanks fields that have
        no value yet on an illiquid strike.
        """
        return {
            "bid": _as_float(response.get("bp1")),
            "ask": _as_float(response.get("sp1")),
            "bid_qty": _as_int(response.get("bq1")),
            "ask_qty": _as_int(response.get("sq1")),
            "open": _as_float(response.get("o")),
            "high": _as_float(response.get("h")),
            "low": _as_float(response.get("l")),
            "ltp": _as_float(response.get("lp")),
            "prev_close": _as_float(response.get("c")) if "c" in response else 0,
            "volume": _as_int(response.get("v")),
            "oi": _as_int(response.get("oi")),
            "tick_size": _as_float(response.get("ti")) if response.get("ti") else None,
        }

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """Get a quote snapshot for a single symbol."""
        try:
            token = get_token(symbol, exchange)
            api_exchange = _normalize_data_exchange(exchange)

            payload = {"exch": api_exchange, "token": token}
            response = _get_api_response("/GetQuotes", self.auth_token, payload)

            if response.get("stat") != "Ok":
                raise Exception(
                    f"Error from TradeSmart API: {response.get('emsg', 'Unknown error')}"
                )
            return self._quote_dict(response)
        except Exception as e:
            raise Exception(f"Error fetching quotes: {str(e)}") from e

    def get_multiquotes(self, symbols: list) -> list:
        """Get quotes for many symbols.

        Served from the streaming feed, not REST. TradeSmart has no batch-quote
        endpoint and caps REST at 10 req/sec + 120/min per user, so an 82-leg
        option chain costs 82 calls -- roughly 10s, and 164 calls/minute once
        the UI refreshes every 30s, which no pacing can fit under a 120/minute
        ceiling. One Noren depth subscription carries every token in a single
        message and answers with a full snapshot per token, off the REST budget
        entirely (see the WebSocket-backed bulk quotes section above).

        Anything the feed does not supply -- no socket, a subscribe failure, or
        scrips whose acknowledgement did not arrive in time -- falls back to the
        REST fan-out, so this degrades to the previous behaviour rather than
        returning holes.

        Returns ``[{'symbol','exchange','data'|'error'}, ...]``.
        """
        if not symbols:
            return []

        prepared = []
        results = []
        for item in symbols:
            symbol = item["symbol"]
            exchange = item["exchange"]
            token = get_token(symbol, exchange)
            if not token:
                results.append(
                    {"symbol": symbol, "exchange": exchange, "error": "Token not resolved"}
                )
                continue
            prepared.append(
                {
                    "symbol": symbol,
                    "exchange": exchange,
                    "api_exchange": _normalize_data_exchange(exchange),
                    "token": token,
                }
            )

        if not prepared:
            return results

        pending = self._extend_from_stream(prepared, results)
        if not pending:
            return results

        logger.info(f"Fetching {len(pending)} TradeSmart quotes over REST")
        with ThreadPoolExecutor(max_workers=TRADESMART_MAX_PER_SECOND) as executor:
            future_map = {executor.submit(self._fetch_single_quote, item): item for item in pending}
            for future in as_completed(future_map):
                item = future_map[future]
                try:
                    results.append(future.result())
                except Exception as e:
                    results.append(
                        {"symbol": item["symbol"], "exchange": item["exchange"], "error": str(e)}
                    )

        return results

    def _extend_from_stream(self, prepared: list, results: list) -> list:
        """Append every quote the feed can serve to ``results``.

        Returns the items it could not serve, for the REST fallback. A failure
        anywhere here is not fatal: the whole batch simply stays pending.
        """
        try:
            stream = get_quote_stream(self.auth_token)
            if stream is None:
                return prepared

            keyed = {scrip_key(item["api_exchange"], item["token"]): item for item in prepared}
            snapshots = stream.snapshots(list(keyed))
        except Exception as e:
            # Never let a streaming problem fail a quote request that REST can
            # still answer.
            logger.warning(f"TradeSmart quote stream unavailable, using REST: {e}")
            return prepared

        pending = []
        for key, item in keyed.items():
            snapshot = snapshots.get(key)
            if snapshot is None:
                pending.append(item)
                continue
            results.append(
                {
                    "symbol": item["symbol"],
                    "exchange": item["exchange"],
                    # Feed and GetQuotes share Noren's field names (lp, bp1,
                    # sp1, o, h, l, c, v, oi), so the same mapper serves both.
                    "data": self._quote_dict(snapshot),
                }
            )
        return pending

    def _fetch_single_quote(self, item: dict) -> dict:
        """Fetch one quote (used by the multiquotes thread pool)."""
        try:
            payload = {"exch": item["api_exchange"], "token": item["token"]}
            response = _get_api_response("/GetQuotes", self.auth_token, payload)
            if response.get("stat") != "Ok":
                return {
                    "symbol": item["symbol"],
                    "exchange": item["exchange"],
                    "error": response.get("emsg", "Unknown error"),
                }
            return {
                "symbol": item["symbol"],
                "exchange": item["exchange"],
                "data": self._quote_dict(response),
            }
        except Exception as e:
            return {"symbol": item["symbol"], "exchange": item["exchange"], "error": str(e)}

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """Get 5-level market depth for a single symbol."""
        try:
            token = get_token(symbol, exchange)
            api_exchange = _normalize_data_exchange(exchange)

            payload = {"exch": api_exchange, "token": token}
            response = _get_api_response("/GetQuotes", self.auth_token, payload)

            if response.get("stat") != "Ok":
                raise Exception(
                    f"Error from TradeSmart API: {response.get('emsg', 'Unknown error')}"
                )

            bids = []
            asks = []
            for i in range(1, 6):
                bids.append(
                    {
                        "price": float(response.get(f"bp{i}", 0)),
                        "quantity": int(float(response.get(f"bq{i}", 0))),
                        "orders": int(float(response.get(f"bo{i}", 0))),
                    }
                )
                asks.append(
                    {
                        "price": float(response.get(f"sp{i}", 0)),
                        "quantity": int(float(response.get(f"sq{i}", 0))),
                        "orders": int(float(response.get(f"so{i}", 0))),
                    }
                )

            return {
                "bids": bids,
                "asks": asks,
                "totalbuyqty": sum(bid["quantity"] for bid in bids),
                "totalsellqty": sum(ask["quantity"] for ask in asks),
                "high": float(response.get("h", 0)),
                "low": float(response.get("l", 0)),
                "ltp": float(response.get("lp", 0)),
                "ltq": int(float(response.get("ltq", 0))),
                "open": float(response.get("o", 0)),
                "prev_close": float(response.get("c", 0)) if "c" in response else 0,
                "volume": int(float(response.get("v", 0))),
                "oi": int(float(response.get("oi", 0))),
            }
        except Exception as e:
            raise Exception(f"Error fetching market depth: {str(e)}") from e

    # Alias required by some services
    get_market_depth = get_depth

    def get_history(
        self, symbol: str, exchange: str, interval: str, start_date, end_date
    ) -> pd.DataFrame:
        """Get historical candles.

        Daily uses /EODChartData (sym = EXCH:BRSYMBOL); intraday uses /TPSeries.
        Returns a DataFrame [timestamp, open, high, low, close, volume, oi] with
        ``timestamp`` in epoch seconds.
        """
        try:
            if interval not in self.timeframe_map:
                supported = list(self.timeframe_map.keys())
                raise Exception(
                    f"Unsupported interval '{interval}'. Supported: {', '.join(supported)}"
                )

            br_symbol = get_br_symbol(symbol, exchange)
            token = get_token(symbol, exchange)
            api_exchange = _normalize_data_exchange(exchange)

            start_date_str = (
                start_date.strftime("%Y-%m-%d")
                if hasattr(start_date, "strftime")
                else str(start_date)
            )
            end_date_str = (
                end_date.strftime("%Y-%m-%d") if hasattr(end_date, "strftime") else str(end_date)
            )

            start_ts = int(
                datetime.strptime(start_date_str + " 00:00:00", "%Y-%m-%d %H:%M:%S").timestamp()
            )
            end_ts = int(
                datetime.strptime(end_date_str + " 23:59:59", "%Y-%m-%d %H:%M:%S").timestamp()
            )

            if interval == "D":
                payload = {
                    "sym": f"{api_exchange}:{br_symbol}",
                    "from": str(start_ts),
                    "to": str(end_ts),
                }
                apply_rate_limit("/EODChartData")
                try:
                    response = json.loads(post("/EODChartData", payload, self.auth_token).text)
                except Exception as e:
                    logger.error(f"EOD request error: {e}")
                    response = []
            else:
                payload = {
                    "uid": resolve_uid(self.auth_token),
                    "exch": api_exchange,
                    "token": token,
                    "st": str(start_ts),
                    "et": str(end_ts),
                    "intrv": self.timeframe_map[interval],
                }
                apply_rate_limit("/TPSeries")
                response = json.loads(post("/TPSeries", payload, self.auth_token).text)

            if isinstance(response, dict):
                if response.get("stat") == "Not_Ok":
                    emsg = response.get("emsg", "Unknown error")
                    # "no data" is a benign empty result, not an error. TradeSmart's
                    # Noren backend serves no historical series for the CDS currency
                    # segment, and illiquid contracts can have no trades in the window.
                    # Return an empty frame so the caller renders an empty/live chart
                    # instead of surfacing a 500 and logging a traceback every cycle.
                    if "no data" in emsg.lower():
                        return pd.DataFrame(
                            columns=["close", "high", "low", "open", "timestamp", "volume", "oi"]
                        )
                    raise Exception(f"Error from TradeSmart API: {emsg}")
            elif not isinstance(response, list):
                raise Exception("Invalid response format from TradeSmart API")

            data = []
            for candle in response:
                if isinstance(candle, str):
                    candle = json.loads(candle)
                try:
                    if interval == "D":
                        timestamp = int(candle.get("ssboe", 0))
                    else:
                        try:
                            timestamp = int(
                                datetime.strptime(candle["time"], "%d-%m-%Y %H:%M:%S").timestamp()
                            )
                        except (ValueError, KeyError):
                            # Fall back to the epoch field if present
                            if candle.get("ssboe"):
                                timestamp = int(candle["ssboe"])
                            else:
                                continue
                        if (
                            float(candle.get("into", 0)) == 0
                            and float(candle.get("inth", 0)) == 0
                            and float(candle.get("intl", 0)) == 0
                            and float(candle.get("intc", 0)) == 0
                        ):
                            continue

                    data.append(
                        {
                            "timestamp": timestamp,
                            "open": float(candle.get("into", 0)),
                            "high": float(candle.get("inth", 0)),
                            "low": float(candle.get("intl", 0)),
                            "close": float(candle.get("intc", 0)),
                            "volume": int(float(candle.get("intv", 0))),
                            "oi": int(float(candle.get("oi", 0))),
                        }
                    )
                except (KeyError, ValueError) as e:
                    logger.error(f"Error parsing candle: {e}, Candle: {candle}")
                    continue

            df = pd.DataFrame(data)
            if df.empty:
                df = pd.DataFrame(
                    columns=["timestamp", "open", "high", "low", "close", "volume", "oi"]
                )

            # For daily data, append today's candle from quotes if missing. Use an
            # IST-midnight epoch (+5:30) to match the cross-broker daily convention.
            if interval == "D":
                utc_today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                ist_today = utc_today + timedelta(hours=5, minutes=30)
                today_ts = int(ist_today.timestamp())

                if start_ts <= today_ts <= end_ts and (
                    df.empty or df["timestamp"].max() < today_ts
                ):
                    try:
                        quotes = self.get_quotes(symbol, exchange)
                        if quotes:
                            today_data = {
                                "timestamp": today_ts,
                                "open": float(quotes.get("open", 0)),
                                "high": float(quotes.get("high", 0)),
                                "low": float(quotes.get("low", 0)),
                                "close": float(quotes.get("ltp", 0)),
                                "volume": int(float(quotes.get("volume", 0))),
                                "oi": 0,
                            }
                            df = pd.concat([df, pd.DataFrame([today_data])], ignore_index=True)
                    except Exception as e:
                        logger.info(f"Error fetching today's candle from quotes: {e}")

            df = df.sort_values("timestamp")
            df = df[["close", "high", "low", "open", "timestamp", "volume", "oi"]]
            return df

        except Exception as e:
            raise Exception(f"Error fetching historical data: {str(e)}") from e

    def get_intervals(self) -> list:
        """Return supported interval keys."""
        return list(self.timeframe_map.keys())
