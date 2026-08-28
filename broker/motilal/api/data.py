import json
import os
import threading
import time

import pandas as pd

from database.token_db import get_br_symbol, get_token
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

from .baseurl import get_base_url, get_common_headers, get_url
from .baseurl import get_client_code as baseurl_client_code

logger = get_logger(__name__)

# Live market-data WebSocket per broker session, shared across BrokerData
# instances. It has to live at module scope because quotes_service/depth_service
# build a new BrokerData for every request, so an instance attribute is always
# empty: every depth and multiquote call opened a brand new socket, and nothing
# ever closed it (the handlers only unregister scrips, which does not close the
# connection). Each abandoned client kept its reader thread alive - the thread
# holds a reference to the client, so it never even became garbage - and its
# on_close handler kept scheduling reconnects, so file descriptors and threads
# grew with request volume rather than with users.
#
# Keyed by auth token, so a re-login makes a new entry instead of reusing a
# socket authenticated with a dead token (Motilal expires the AuthToken daily at
# 6 AM). Bounded by definition: OpenAlgo is single-user, single-broker per
# instance. Mirrors broker/aliceblue/api/data.py.
_WS_REGISTRY: dict = {}
_WS_REGISTRY_LOCK = threading.Lock()


def close_all_websockets():
    """Disconnect and drop every pooled market-data socket.

    For shutdown and for logout, where the session behind these connections is
    about to be revoked. Without it the sockets and their reader threads would
    outlive the session that authenticated them.
    """
    with _WS_REGISTRY_LOCK:
        sockets = list(_WS_REGISTRY.values())
        _WS_REGISTRY.clear()

    for sock in sockets:
        try:
            sock.disconnect()
        except Exception as exc:
            logger.warning(f"Error closing pooled Motilal WebSocket: {exc}")

    if sockets:
        logger.info(f"Closed {len(sockets)} pooled Motilal market data WebSocket(s)")


# OpenAlgo pseudo-exchanges that hold index instruments. The token stored for
# these is an Index Code from the index master (26000/26009/999912), NOT a
# scrip code, so they must never be sent to the scrip LTP endpoint.
INDEX_EXCHANGES = ("NSE_INDEX", "BSE_INDEX", "MCX_INDEX")

# Index Code -> real exchange accepted by getindexltpdata / IndexRegister.
# doc 42-index-ltp.md and doc 33-websocket-broadcast.md both allow NSE and BSE only.
INDEX_EXCHANGE_MAP = {"NSE_INDEX": "NSE", "BSE_INDEX": "BSE"}


# Dealer-only ``clientcode``. doc 26-price-ltp.md / doc 42-index-ltp.md mark it
# "Mandatory in case of Dealer"; the sample body says "In case of dealer else not
# required". A plain client login that sends it is rejected with MO2031 ("Client
# and Vendor Cannot Enter UserId"), while a dealer that omits it gets MO1062
# ("Please Provide Client Code In Input Parameter"). Nothing in the login
# response identifies the account type, so start without it (the common case)
# and latch dealer mode the first time MO1062 comes back.
_dealer_mode = False

# Which spelling of the exchange field getindexltpdata actually accepts. doc 42's
# parameter table and its own sample body disagree; None means "not yet learned".
_index_exchange_field = None


def _latch_dealer_mode(response):
    """Return True when a failed response means "resend this with clientcode"."""
    global _dealer_mode
    if _dealer_mode:
        return False

    errorcode = str(response.get("errorcode", "")).strip().upper()
    message = str(response.get("message", "")).lower()
    if errorcode == "MO1062" or ("client code" in message and "provide" in message):
        _dealer_mode = True
        logger.info(
            "Motilal: dealer login detected (%s); sending clientcode on subsequent requests",
            errorcode or "message match",
        )
        return True
    return False


def post_with_optional_client_code(url, auth_token, payload):
    """POST a report request, adding ``clientcode`` only for dealer logins."""
    body = dict(payload)

    if _dealer_mode:
        client_code = get_client_code()
        if client_code:
            body["clientcode"] = client_code

    response = get_api_response(url, auth_token, "POST", body)

    if response.get("status") != "SUCCESS" and _latch_dealer_mode(response):
        client_code = get_client_code()
        if not client_code:
            logger.error(
                "Motilal reports a dealer login but no client code is stored. "
                "Log in again so the client code is saved."
            )
            return response
        body["clientcode"] = client_code
        logger.debug("Retrying %s with clientcode for dealer login", url)
        response = get_api_response(url, auth_token, "POST", body)

    return response


def get_client_code():
    """Motilal client code, if known.

    doc 26-price-ltp.md / doc 42-index-ltp.md: ``clientcode`` is mandatory for
    dealer logins (omitting it fails with MO1062). It is the trading login ID
    captured at login (see ``baseurl.get_client_code``), NOT an env variable -
    ``BROKER_API_KEY``/``BROKER_API_SECRET`` are the app's API key and secret,
    as for every other OpenAlgo broker.
    """
    return baseurl_client_code()


def get_api_response(endpoint, auth, method="GET", payload=""):
    """Helper function to make API calls to Motilal Oswal.

    Args:
        endpoint: absolute URL (use ``get_url(<key>)`` from baseurl) or a path
            that is resolved against ``get_base_url()``.
    """
    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    # doc 05-header-parameters.md: vendorinfo is mandatory (MO2012) and
    # browsername/browserversion are mandatory for SourceId=WEB. Build the whole
    # set from the shared helper so this module cannot drift from the rest of
    # the plugin.
    headers = get_common_headers(auth)

    if isinstance(payload, dict):
        payload = json.dumps(payload)

    url = endpoint if endpoint.startswith("http") else f"{get_base_url()}{endpoint}"

    try:
        if method == "GET":
            response = client.get(url, headers=headers)
        elif method == "POST":
            response = client.post(url, headers=headers, content=payload)
        else:
            response = client.request(method, url, headers=headers, content=payload)

        # Add status attribute for compatibility with the existing codebase
        response.status = response.status_code

        if response.status_code == 403:
            logger.debug(f"API returned 403 Forbidden. Header fields: {list(headers)}")
            logger.debug(f"Response text: {response.text}")
            raise Exception("Authentication failed. Please check your API key and auth token.")

        return json.loads(response.text)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse response. Status code: {response.status_code}")
        logger.debug(f"Response text: {response.text}")
        raise Exception(f"Failed to parse API response (status {response.status_code})")


def _best_bid_ask(websocket, motilal_exchange, token):
    """Return ``(best_bid, best_ask)`` in rupees from the depth store.

    Motilal's broadcast feed publishes bid/ask only in the MarketDepth packet
    (doc 33-websocket-broadcast.md), which the client keeps separately from the
    LTP/OHLC quote store. Reading ``quote["bid"]`` therefore always yielded 0.
    Returns ``(0.0, 0.0)`` when no depth has arrived yet.
    """
    try:
        depth = websocket.get_market_depth(motilal_exchange, token)
    except Exception:
        return 0.0, 0.0

    if not depth:
        return 0.0, 0.0

    def _first_price(levels):
        for level in levels or []:
            if level and level.get("price"):
                return float(level["price"])
        return 0.0

    return _first_price(depth.get("bids")), _first_price(depth.get("asks"))


class BrokerData:
    def __init__(self, auth_token):
        """Initialize Motilal Oswal data handler with authentication token"""
        self.auth_token = auth_token
        self._websocket = None
        # Motilal publishes no historical OHLC API, so no date range can be
        # served. The ONE candle that is available is today's daily bar, which
        # getltpdata returns live (open/high/low/volume + ltp as the running
        # close) - see get_history. Advertising "D" keeps /trading's timeframe
        # menu populated and today's chart alive; every other interval raises.
        self.timeframe_map = {"D": "D"}

    def _detect_index_exchange(self, symbol: str) -> str:
        """
        Detect the specific index exchange (NSE_INDEX, BSE_INDEX, or MCX_INDEX) for an index symbol.

        Args:
            symbol: Index symbol (e.g., NIFTY, SENSEX, BANKEX)

        Returns:
            Specific index exchange (NSE_INDEX, BSE_INDEX, or MCX_INDEX)
        """
        # Common NSE indices
        nse_indices = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"]

        # Common BSE indices
        bse_indices = ["SENSEX", "BANKEX", "SENSEX50"]

        # Common MCX indices
        mcx_indices = ["MCXMETLDEX", "MCXENRGDEX"]

        symbol_upper = symbol.upper()

        # Check if it's a known NSE index
        if any(idx in symbol_upper for idx in nse_indices):
            return "NSE_INDEX"

        # Check if it's a known BSE index
        if any(idx in symbol_upper for idx in bse_indices):
            return "BSE_INDEX"

        # Check if it's a known MCX index
        if any(idx in symbol_upper for idx in mcx_indices):
            return "MCX_INDEX"

        # Try database lookup
        try:
            from database.auth_db import db_session
            from database.symbol import SymToken

            with db_session() as session:
                results = session.query(SymToken).filter(SymToken.symbol == symbol).all()

                for result in results:
                    if result.instrumenttype and "INDEX" in result.instrumenttype.upper():
                        logger.debug(
                            f"Found index in database: {symbol} -> {result.instrumenttype}"
                        )
                        return result.instrumenttype
        except Exception as e:
            logger.error(f"Error looking up index in database: {str(e)}")

        # Default to NSE_INDEX for unknown indices
        logger.warning(
            f"Could not determine specific index exchange for {symbol}, defaulting to NSE_INDEX"
        )
        return "NSE_INDEX"

    def _auto_detect_exchange(self, symbol: str) -> str:
        """
        Auto-detect exchange for a symbol by looking up its instrumenttype in database.
        Returns the appropriate exchange based on instrumenttype.
        """
        try:
            # Import here to avoid circular imports
            from database.auth_db import db_session
            from database.symbol import SymToken

            # Query database for the symbol
            with db_session() as session:
                # First try to find any matching symbol
                results = session.query(SymToken).filter(SymToken.symbol == symbol).all()

                if results:
                    for result in results:
                        # Check instrumenttype to determine exchange
                        if result.instrumenttype:
                            instrument_type = result.instrumenttype.upper()
                            # If instrumenttype contains INDEX, use it as exchange
                            if "INDEX" in instrument_type:
                                # instrumenttype like NSE_INDEX, BSE_INDEX, MCX_INDEX
                                return result.instrumenttype
                            else:
                                # For other types, use the exchange field
                                return result.exchange

                    # If no instrumenttype, return the exchange of first match
                    return results[0].exchange

                # If not found, make educated guess based on symbol pattern
                if (
                    "GOLD" in symbol.upper()
                    or "SILVER" in symbol.upper()
                    or "CRUDE" in symbol.upper()
                ):
                    return "MCX"  # Commodity symbols
                elif symbol.endswith("FUT"):
                    return "NFO"
                elif symbol.endswith("CE") or symbol.endswith("PE"):
                    return "NFO"
                elif "USDINR" in symbol.upper() or "EURINR" in symbol.upper():
                    return "CDS"
                else:
                    return "NSE"  # Default to NSE

        except Exception as e:
            logger.error(f"Error in auto-detecting exchange: {str(e)}")
            return "NSE"  # Default fallback

    def get_websocket(self, force_new=False):
        """
        Get the pooled market-data WebSocket for this session, or create it.

        The live connection lives in the module-level ``_WS_REGISTRY``, NOT on
        ``self``: the services construct a fresh BrokerData per request, so an
        instance attribute could never hit and every depth/multiquote call built
        - and then leaked - a whole new socket. See the registry comment above.

        Args:
            force_new: Discard the pooled connection and build a fresh one.

        Returns:
            MotilalWebSocket, or None when a connection could not be established
            (both call sites already treat None as "no socket").
        """
        if not self.auth_token:
            logger.error("No auth token available; cannot open the market data WebSocket")
            return None

        if not force_new:
            with _WS_REGISTRY_LOCK:
                cached = _WS_REGISTRY.get(self.auth_token)
            if cached is not None and cached.is_connected:
                logger.debug("Reusing pooled Motilal WebSocket connection")
                self._websocket = cached
                return cached

        # Drop whatever was registered for this session before replacing it, so
        # a stale socket and its threads are not left behind.
        with _WS_REGISTRY_LOCK:
            stale = _WS_REGISTRY.pop(self.auth_token, None)
        if stale is not None:
            try:
                stale.disconnect()
            except Exception as e:
                logger.warning(f"Error closing existing WebSocket: {e}")

        # App API key from the environment; the client code comes from the login
        # (BROKER_API_KEY/BROKER_API_SECRET are the app key/secret, as for every
        # other OpenAlgo broker).
        client_id = get_client_code() or ""
        api_key = os.getenv("BROKER_API_KEY", "")

        from .motilal_websocket import MotilalWebSocket

        logger.info("Creating new Motilal market data WebSocket connection")
        ws = MotilalWebSocket(client_id, self.auth_token, api_key)
        ws.connect()

        # Poll at 50ms rather than 500ms: the coarse tick rounded every connect
        # up to half a second even when the handshake finished immediately.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not ws.is_connected:
            time.sleep(0.05)

        if not ws.is_connected:
            logger.error("Motilal WebSocket did not connect within 10s")
            try:
                ws.disconnect()
            except Exception:
                pass
            return None

        # Register this session, or fall in behind whatever another thread
        # registered while we were connecting.
        #
        # The socket has to be built OUTSIDE the registry lock (connecting takes
        # ~250ms and holding the lock would serialise every caller), so two
        # requests that miss the cache together - the normal cold start, e.g. an
        # option-chain and a depth call arriving at once - each build one. Only
        # one can be registered; the other must be CLOSED, not dropped on the
        # floor, or it becomes exactly the leak this registry was added to fix.
        # The incumbent wins, because other requests may already be registering
        # scrips on it.
        #
        # Sockets under other keys are evicted too: OpenAlgo is single-user /
        # single-broker, so a second auth token means the token rolled over
        # (Motilal expires it daily at 6 AM) and that socket is authenticated
        # with a dead one.
        loser = None
        to_close = []
        with _WS_REGISTRY_LOCK:
            incumbent = _WS_REGISTRY.get(self.auth_token)
            if incumbent is not None and incumbent is not ws and incumbent.is_connected:
                loser, ws = ws, incumbent
            else:
                if incumbent is not None and incumbent is not ws:
                    to_close.append(incumbent)  # dead entry we are replacing
                for key in [k for k in _WS_REGISTRY if k != self.auth_token]:
                    to_close.append(_WS_REGISTRY.pop(key))
                _WS_REGISTRY[self.auth_token] = ws

        if loser is not None:
            logger.debug(
                "Another thread registered a Motilal WebSocket first; closing the duplicate"
            )
            try:
                loser.disconnect()
            except Exception as exc:
                logger.warning(f"Error closing duplicate WebSocket: {exc}")

        for sock in to_close:
            logger.info("Closing a superseded Motilal WebSocket")
            try:
                sock.disconnect()
            except Exception as exc:
                logger.warning(f"Error closing superseded WebSocket: {exc}")

        self._websocket = ws  # kept for callers that still read the attribute

        logger.info("Motilal WebSocket connection established")
        return ws

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """
        Get real-time quotes for given symbol from Motilal Oswal.

        Args:
            symbol: Trading symbol (OpenAlgo format)
            exchange: Exchange (NSE, BSE, NFO, BFO, CDS, MCX)

        Returns:
            dict: Quote data with required fields
            {
                'bid': float,
                'ask': float,
                'open': float,
                'high': float,
                'low': float,
                'ltp': float,
                'prev_close': float,
                'volume': int,
                'oi': int
            }
        """
        try:
            # Handle generic 'INDEX' exchange the same way get_depth does, so both
            # entry points resolve index symbols consistently.
            if exchange == "INDEX":
                exchange = self._detect_index_exchange(symbol)
                logger.debug(f"Converted generic INDEX to {exchange} for {symbol}")

            # Indices have their own endpoint with a different payload, response
            # shape and price scale - never route them to getltpdata.
            if exchange in INDEX_EXCHANGES:
                return self._get_index_quotes(symbol, exchange)

            # Get token for the symbol
            token = get_token(symbol, exchange)

            if not token:
                raise Exception(f"Token not found for symbol: {symbol}, exchange: {exchange}")

            # Map OpenAlgo exchange to Motilal exchange
            from broker.motilal.mapping.transform_data import map_exchange

            motilal_exchange = map_exchange(exchange)

            # Prepare payload for Motilal's LTP API (doc 26-price-ltp.md)
            payload = {"exchange": motilal_exchange, "scripcode": int(token)}

            logger.debug(f"Fetching quotes for {symbol} ({token}) on {motilal_exchange}")

            # Make API call using the helper function (v3 per doc 26-price-ltp.md).
            # clientcode is added only for dealer logins - a client login that
            # sends it is rejected with MO2031.
            response = post_with_optional_client_code(
                get_url("getltpdata"), self.auth_token, payload
            )

            # Check response status
            if response.get("status") != "SUCCESS":
                raise Exception(
                    f"Error from Motilal API: {response.get('message', 'Unknown error')}, errorcode: {response.get('errorcode', '')}"
                )

            # Extract quote data from response
            data = response.get("data", {})
            if not data:
                raise Exception("No quote data received from Motilal API")

            # IMPORTANT: getltpdata returns values in paisa, convert to rupees.
            # doc 26-price-ltp.md states explicitly: "The values of open, high, low,
            # close and ltp are in paisa". The note does NOT mention bid/ask, but the
            # doc's own sample ("ask": 3239, "bid": 3230 alongside "ltp": 3224) makes
            # paisa the only consistent reading, so they are scaled the same way.
            # Handle the case where values might be 0 or None
            def convert_paisa_to_rupees(value):
                """Convert paisa to rupees, handling None and 0 values"""
                if value is None or value == 0:
                    return 0.0
                return float(value) / 100.0

            # Return quote in OpenAlgo common format
            return {
                "bid": convert_paisa_to_rupees(data.get("bid", 0)),
                "ask": convert_paisa_to_rupees(data.get("ask", 0)),
                "open": convert_paisa_to_rupees(data.get("open", 0)),
                "high": convert_paisa_to_rupees(data.get("high", 0)),
                "low": convert_paisa_to_rupees(data.get("low", 0)),
                "ltp": convert_paisa_to_rupees(data.get("ltp", 0)),
                "prev_close": convert_paisa_to_rupees(
                    data.get("close", 0)
                ),  # Motilal uses 'close' for previous close
                "volume": int(data.get("volume", 0)),
                "oi": 0,  # Motilal LTP API doesn't provide OI data
            }

        except Exception as e:
            logger.error(f"Error fetching quotes for {symbol} on {exchange}: {str(e)}")
            raise Exception(f"Error fetching quotes: {str(e)}")

    def _get_index_quotes(self, symbol: str, exchange: str) -> dict:
        """
        Get index quotes via Motilal's dedicated index LTP API (doc 42-index-ltp.md).

        This endpoint differs from getltpdata in three ways that matter:
          * ``data`` is a LIST, not an object;
          * prices are already in RUPEES (sample: "open": 17451.25) - no /100;
          * only open/high/low/close/ltp are returned - no volume/bid/ask/oi.

        Args:
            symbol: Index symbol (OpenAlgo format, e.g. NIFTY)
            exchange: NSE_INDEX / BSE_INDEX (MCX_INDEX is unsupported)

        Returns:
            dict: Quote data in the OpenAlgo common format
        """
        motilal_exchange = INDEX_EXCHANGE_MAP.get(exchange)
        if not motilal_exchange:
            # doc 42-index-ltp.md: exchange is documented as "NSE,BSE" only. Fail
            # loudly rather than returning a zero-filled quote for MCX indices.
            raise Exception(
                f"Index quotes are not supported for {exchange} ({symbol}): Motilal's "
                "getindexltpdata API accepts NSE and BSE indices only"
            )

        # The token stored for an index row is the Index Code from the index
        # master CSV (e.g. 26000 NIFTY, 26009 BANKNIFTY, 999912 SENSEX).
        index_code = get_token(symbol, exchange)
        if not index_code:
            raise Exception(f"Index code not found for symbol: {symbol}, exchange: {exchange}")

        logger.debug(f"Fetching index quotes for {symbol} ({index_code}) on {motilal_exchange}")

        # doc 42-index-ltp.md contradicts itself on this field: its parameter
        # table names it "exchangename" (mandatory) while its own sample body
        # sends "exchange". The table is correct - sending "exchange" is rejected
        # with MO1051 Invalid Exchange Input Parameter - and the sibling index
        # API (doc 40) uses "exchangename" in both its table and its sample. The
        # other spelling is still tried once, as insurance against the doc
        # contradiction, and whichever works is remembered for the process.
        global _index_exchange_field
        candidates = [_index_exchange_field] if _index_exchange_field else ["exchangename", "exchange"]

        response = {}
        for field in candidates:
            payload = {field: motilal_exchange, "scripcode": str(index_code)}

            # clientcode only for dealer logins (MO2031 otherwise).
            response = post_with_optional_client_code(
                get_url("getindexltpdata"), self.auth_token, payload
            )

            if response.get("status") == "SUCCESS":
                if _index_exchange_field != field:
                    _index_exchange_field = field
                    logger.info("Motilal getindexltpdata accepts the %r field", field)
                break

            # Only an exchange-field rejection is worth retrying with the other
            # spelling; any other error is real and must surface as-is.
            if str(response.get("errorcode", "")).strip().upper() != "MO1051":
                break

        if response.get("status") != "SUCCESS":
            raise Exception(
                f"Error from Motilal index LTP API: {response.get('message', 'Unknown error')}, "
                f"errorcode: {response.get('errorcode', '')}"
            )

        # data is a LIST of index rows; pick the one matching our index code.
        rows = response.get("data") or []
        if isinstance(rows, dict):  # defensive: tolerate an object response
            rows = [rows]
        if not rows:
            raise Exception(f"No index quote data received from Motilal API for {symbol}")

        row = next(
            (r for r in rows if str(r.get("scripcode", "")) == str(index_code)),
            rows[0],
        )

        def to_float(value):
            try:
                return float(value or 0)
            except (TypeError, ValueError):
                return 0.0

        # No division by 100 here: doc 42's sample values are already in rupees.
        return {
            "bid": 0.0,  # not returned by getindexltpdata
            "ask": 0.0,  # not returned by getindexltpdata
            "open": to_float(row.get("open")),
            "high": to_float(row.get("high")),
            "low": to_float(row.get("low")),
            "ltp": to_float(row.get("ltp")),
            "prev_close": to_float(row.get("close")),
            "volume": 0,  # not returned by getindexltpdata
            "oi": 0,  # not applicable to indices
        }

    def get_multiquotes(self, symbols: list) -> list:
        """
        Get real-time quotes for multiple symbols using WebSocket
        Motilal WebSocket supports subscribing to multiple instruments

        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys
                     Example: [{'symbol': 'SBIN', 'exchange': 'NSE'}, ...]
        Returns:
            list: List of quote data for each symbol with format:
                  [{'symbol': 'SBIN', 'exchange': 'NSE', 'data': {...}}, ...]
        """
        try:
            # Motilal WebSocket can handle multiple instruments
            # Using batch size of 100 for practical response times
            BATCH_SIZE = 100
            RATE_LIMIT_DELAY = 0.1  # Delay between batches in seconds

            if len(symbols) > BATCH_SIZE:
                logger.info(f"Processing {len(symbols)} symbols in batches of {BATCH_SIZE}")
                all_results = []

                for i in range(0, len(symbols), BATCH_SIZE):
                    batch = symbols[i : i + BATCH_SIZE]
                    logger.debug(
                        f"Processing batch {i // BATCH_SIZE + 1}: symbols {i + 1} to {min(i + BATCH_SIZE, len(symbols))}"
                    )

                    batch_results = self._process_multiquotes_batch(batch)
                    all_results.extend(batch_results)

                    # Rate limit delay between batches
                    time.sleep(RATE_LIMIT_DELAY)

                logger.info(f"Successfully processed {len(all_results)} quotes")
                return all_results
            else:
                return self._process_multiquotes_batch(symbols)

        except Exception as e:
            logger.exception("Error fetching multiquotes")
            raise Exception(f"Error fetching multiquotes: {e}")

    def _process_multiquotes_batch(self, symbols: list) -> list:
        """
        Process a batch of symbols using WebSocket subscription
        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys
        Returns:
            list: List of quote data for the batch
        """
        results = []
        skipped_symbols = []
        registered_scrips = []  # Track registered scrips for unregistration
        registered_indices = []  # Track registered index exchanges for unregistration
        symbol_map = {}  # Map exchange:token to original symbol/exchange
        index_map = {}  # Map exchange:index_code to original symbol/exchange

        # Get WebSocket connection
        websocket = self.get_websocket()

        if not websocket or not websocket.is_connected:
            logger.warning("WebSocket not connected, reconnecting...")
            websocket = self.get_websocket(force_new=True)

        if not websocket or not websocket.is_connected:
            logger.error("Could not establish WebSocket connection")
            raise ConnectionError("WebSocket connection unavailable")

        # Step 1: Prepare and register all instruments
        for item in symbols:
            symbol = item.get("symbol")
            exchange = item.get("exchange")

            if not symbol or not exchange:
                logger.warning(f"Skipping entry due to missing symbol/exchange: {item}")
                skipped_symbols.append(
                    {
                        "symbol": symbol,
                        "exchange": exchange,
                        "data": None,
                        "error": "Missing required symbol or exchange",
                    }
                )
                continue

            try:
                # Resolve the generic 'INDEX' exchange the same way get_quotes/get_depth do
                if exchange == "INDEX":
                    exchange = self._detect_index_exchange(symbol)

                # Get token for this symbol
                token = get_token(symbol, exchange)
                if not token:
                    logger.warning(
                        f"Skipping symbol {symbol} on {exchange}: could not resolve token"
                    )
                    skipped_symbols.append(
                        {
                            "symbol": symbol,
                            "exchange": exchange,
                            "data": None,
                            "error": "Could not resolve token",
                        }
                    )
                    continue

                # Indices use a completely separate registration API
                # (doc 33-websocket-broadcast.md: Mofsl.IndexRegister("NSE")).
                # Registering them as scrips silently never delivers data.
                if exchange in INDEX_EXCHANGES:
                    index_exchange = INDEX_EXCHANGE_MAP.get(exchange)
                    if not index_exchange:
                        logger.warning(f"Index streaming not supported for {exchange}: {symbol}")
                        skipped_symbols.append(
                            {
                                "symbol": symbol,
                                "exchange": exchange,
                                "data": None,
                                "error": "IndexRegister supports NSE and BSE indices only",
                            }
                        )
                        continue

                    if index_exchange in registered_indices or websocket.register_index(
                        index_exchange
                    ):
                        if index_exchange not in registered_indices:
                            registered_indices.append(index_exchange)
                        index_map[f"{index_exchange}:{token}"] = {
                            "symbol": symbol,
                            "exchange": exchange,
                            "token": token,
                        }
                    else:
                        logger.warning(f"Failed to register index {symbol} on {exchange}")
                        skipped_symbols.append(
                            {
                                "symbol": symbol,
                                "exchange": exchange,
                                "data": None,
                                "error": "Index registration failed",
                            }
                        )
                    continue

                api_exchange = exchange

                # Map OpenAlgo exchange to Motilal exchange
                from broker.motilal.mapping.transform_data import map_exchange

                motilal_exchange = map_exchange(api_exchange)

                # Determine exchange type (CASH or DERIVATIVES)
                exchange_type = (
                    "DERIVATIVES" if api_exchange in ["NFO", "BFO", "CDS", "MCX"] else "CASH"
                )

                # Get broker symbol
                br_symbol = get_br_symbol(symbol, exchange) or symbol

                # Register scrip for market data
                success = websocket.register_scrip(
                    motilal_exchange, exchange_type, int(token), br_symbol
                )

                if success:
                    registered_scrips.append(
                        {
                            "motilal_exchange": motilal_exchange,
                            "exchange_type": exchange_type,
                            "token": int(token),
                        }
                    )

                    # Store mapping for response processing
                    key = f"{motilal_exchange}:{token}"
                    symbol_map[key] = {"symbol": symbol, "exchange": exchange, "token": token}
                else:
                    logger.warning(f"Failed to register {symbol} on {exchange}")
                    skipped_symbols.append(
                        {
                            "symbol": symbol,
                            "exchange": exchange,
                            "data": None,
                            "error": "Registration failed",
                        }
                    )

            except Exception as e:
                logger.warning(f"Skipping symbol {symbol} on {exchange}: {str(e)}")
                skipped_symbols.append(
                    {"symbol": symbol, "exchange": exchange, "data": None, "error": str(e)}
                )
                continue

        if not registered_scrips and not index_map:
            logger.warning("No valid symbols to fetch quotes for")
            return skipped_symbols

        # Step 2: Wait for data to arrive
        pending = len(registered_scrips) + len(index_map)
        wait_time = min(max(pending * 0.1, 2), 5)  # Between 2-5 seconds
        logger.debug(f"Waiting {wait_time:.1f}s for quote data...")
        time.sleep(wait_time)

        # Step 3: Collect results from WebSocket
        for key, info in symbol_map.items():
            motilal_exchange, token = key.split(":")

            quote = websocket.get_quote(motilal_exchange, token)

            if quote:
                # bid/ask are never written into the quote store -- the broadcast
                # feed carries them only in the MarketDepth packet (doc 33), which
                # the client keeps in its depth store. Read the best level from
                # there instead of quote.get("bid"), which was always 0.
                best_bid, best_ask = _best_bid_ask(websocket, motilal_exchange, token)
                results.append(
                    {
                        "symbol": info["symbol"],
                        "exchange": info["exchange"],
                        "data": {
                            "bid": best_bid,
                            "ask": best_ask,
                            "open": float(quote.get("open", 0)),
                            "high": float(quote.get("high", 0)),
                            "low": float(quote.get("low", 0)),
                            "ltp": float(quote.get("ltp", 0)),
                            "prev_close": float(quote.get("prev_close", 0)),
                            "volume": int(quote.get("volume", 0)),
                            "oi": int(quote.get("open_interest", 0)),
                        },
                    }
                )
            else:
                results.append(
                    {
                        "symbol": info["symbol"],
                        "exchange": info["exchange"],
                        "error": "No data received",
                    }
                )

        # Step 3b: Collect index results (registered via IndexRegister, not Register)
        for key, info in index_map.items():
            index_exchange, index_code = key.split(":")

            index_data = websocket.get_index(index_exchange, index_code)
            quote = websocket.get_quote(index_exchange, index_code) or {}

            ltp = 0.0
            if index_data and index_data.get("rate"):
                ltp = float(index_data.get("rate", 0))
            elif quote.get("ltp"):
                ltp = float(quote.get("ltp", 0))

            if ltp or quote:
                results.append(
                    {
                        "symbol": info["symbol"],
                        "exchange": info["exchange"],
                        "data": {
                            # The index broadcast carries a value only - no book,
                            # no traded volume and no open interest.
                            "bid": 0.0,
                            "ask": 0.0,
                            "open": float(quote.get("open", 0)),
                            "high": float(quote.get("high", 0)),
                            "low": float(quote.get("low", 0)),
                            "ltp": ltp,
                            "prev_close": float(quote.get("prev_close", 0)),
                            "volume": 0,
                            "oi": 0,
                        },
                    }
                )
            else:
                results.append(
                    {
                        "symbol": info["symbol"],
                        "exchange": info["exchange"],
                        "error": "No data received",
                    }
                )

        # Step 4: Unregister all scrips after getting data
        logger.info(f"Unregistering {len(registered_scrips)} scrips")
        for scrip in registered_scrips:
            try:
                websocket.unregister_scrip(
                    scrip["motilal_exchange"], scrip["exchange_type"], scrip["token"]
                )
            except Exception as e:
                logger.warning(f"Error unregistering scrip: {e}")

        for index_exchange in registered_indices:
            try:
                websocket.unregister_index(index_exchange)
            except Exception as e:
                logger.warning(f"Error unregistering index {index_exchange}: {e}")

        expected = len(symbol_map) + len(index_map)
        logger.info(
            f"Retrieved quotes for {len([r for r in results if 'data' in r])}/{expected} symbols"
        )
        return skipped_symbols + results

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """
        Get market depth for given symbol from Motilal Oswal using WebSocket.
        This follows the OpenAlgo standard structure matching Angel and other brokers.

        Args:
            symbol: Trading symbol (e.g., SBIN, NIFTY)
            exchange: Exchange (e.g., NSE, BSE, NFO, NSE_INDEX)

        Returns:
            dict: Market depth data in OpenAlgo standard format
        """
        logger.info(f"Getting market depth for: {symbol} on {exchange}")

        # Handle generic 'INDEX' exchange by detecting specific index exchange
        if exchange == "INDEX":
            exchange = self._detect_index_exchange(symbol)
            logger.debug(f"Converted generic INDEX to {exchange} for {symbol}")

        # Get WebSocket connection with retry logic
        websocket = None
        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            try:
                websocket = self.get_websocket()

                if websocket and websocket.is_connected:
                    logger.debug(f"WebSocket connected on attempt {retry_count + 1}")
                    break

                logger.warning(f"WebSocket not connected on attempt {retry_count + 1}, retrying...")

                # Force new connection on retry
                websocket = self.get_websocket(force_new=True)

                # Wait a bit longer for connection to establish
                time.sleep(2)

                if websocket and websocket.is_connected:
                    logger.debug(f"WebSocket connected after retry {retry_count + 1}")
                    break

                retry_count += 1

            except Exception as e:
                logger.error(f"WebSocket connection attempt {retry_count + 1} failed: {str(e)}")
                retry_count += 1
                time.sleep(1)

        if not websocket or not websocket.is_connected:
            # A zero-filled block is indistinguishable from a real quote, so fail
            # loudly the way broker/angel/api/data.py does.
            raise Exception(
                f"Error fetching market depth: could not establish WebSocket connection "
                f"after {max_retries} attempts"
            )

        try:
            # Get token for this symbol
            token = get_token(symbol, exchange)

            if not token:
                raise Exception(f"Token not found for symbol: {symbol}, exchange: {exchange}")

            # Indices are registered through a separate broadcast API and carry no
            # order book, so they take a dedicated path.
            if exchange in INDEX_EXCHANGES:
                return self._get_index_depth(websocket, symbol, exchange, token)

            # Get broker symbol if different
            br_symbol = get_br_symbol(symbol, exchange) or symbol

            api_exchange = exchange

            # Map OpenAlgo exchange to Motilal exchange
            from broker.motilal.mapping.transform_data import map_exchange

            motilal_exchange = map_exchange(api_exchange)

            # Determine exchange type (CASH or DERIVATIVES)
            exchange_type = (
                "DERIVATIVES" if api_exchange in ["NFO", "BFO", "CDS", "MCX"] else "CASH"
            )

            logger.info(f"Subscribing to market depth for {exchange}:{symbol} with token {token}")

            # Subscribe to market depth
            success = websocket.register_scrip(
                motilal_exchange, exchange_type, int(token), br_symbol
            )

            if not success:
                raise Exception(f"Failed to subscribe to market depth for {symbol} on {exchange}")

            # Wait for depth data to arrive
            # NOTE: Motilal's WebSocket broadcast feed typically only provides depth level 1 (best bid/ask)
            # Levels 2-5 may not be sent via WebSocket depending on subscription type
            logger.debug(f"Waiting for WebSocket depth data for {exchange}:{symbol}")
            logger.warning("Motilal may only provide depth level 1 (best bid/ask) via WebSocket")

            # Wait for depth data to arrive (increased time for potential multiple levels)
            time.sleep(3.0)

            # Retrieve depth (may contain 1-5 levels depending on broker feed)
            depth = websocket.get_market_depth(motilal_exchange, token)

            # Log what we actually received
            if depth:
                bids_count = len([b for b in depth.get("bids", []) if b and b.get("price", 0) > 0])
                asks_count = len([a for a in depth.get("asks", []) if a and a.get("price", 0) > 0])
                logger.debug(
                    f"Received {bids_count} bid levels and {asks_count} ask levels for {symbol}"
                )
            else:
                logger.warning(f"No depth data received for {symbol}")

            # Also try to get quote data (OHLC, LTP, volume) for this symbol
            quote = websocket.get_quote(motilal_exchange, token)

            # Unsubscribe after getting the data to stop continuous streaming
            logger.info(f"Unsubscribing from depth for {exchange}:{symbol} after retrieving data")
            websocket.unregister_scrip(motilal_exchange, exchange_type, int(token))

            # Create a normalized depth structure in the OpenAlgo format
            # If depth is not available (e.g., for indices), use empty lists
            if depth:
                bids = depth.get("bids", [])
                asks = depth.get("asks", [])
            else:
                logger.warning(
                    f"No market depth data available for {symbol} on {exchange}, using empty depth"
                )
                bids = []
                asks = []

            # Open interest arrives in its own broadcast packet
            # (doc 33: {'Open Interest': .., 'Open Interest High': .., ..}) which the
            # WebSocket collects into last_oi; the LTP packet also carries
            # 'LTP_Open Interest'. Prefer the dedicated packet, fall back to the quote.
            oi_data = websocket.get_open_interest(motilal_exchange, token) or {}

            # Extract quote data if available
            quote = quote or {}
            ltp = quote.get("ltp", 0)
            oi = int(oi_data.get("open_interest", 0) or quote.get("open_interest", 0) or 0)
            # doc 33 LTP packet: 'LTP_Qty' is the last traded quantity.
            ltq = int(quote.get("ltp_qty", 0) or 0)
            high = quote.get("high", 0) if quote else 0
            low = quote.get("low", 0) if quote else 0
            open_price = quote.get("open", 0) if quote else 0
            prev_close = quote.get("prev_close", 0) if quote else 0
            volume = quote.get("volume", 0) if quote else 0

            # Format bids and asks - ensure exactly 5 entries each (matching Angel format)
            formatted_bids = []
            formatted_asks = []

            # Process buy orders (ensure 5 entries)
            for i in range(5):
                if i < len(bids) and bids[i] is not None:
                    formatted_bids.append(
                        {"price": bids[i].get("price", 0), "quantity": bids[i].get("quantity", 0)}
                    )
                else:
                    formatted_bids.append({"price": 0, "quantity": 0})

            # Process sell orders (ensure 5 entries)
            for i in range(5):
                if i < len(asks) and asks[i] is not None:
                    formatted_asks.append(
                        {"price": asks[i].get("price", 0), "quantity": asks[i].get("quantity", 0)}
                    )
                else:
                    formatted_asks.append({"price": 0, "quantity": 0})

            # Exchange-wide total buy/sell quantities are NOT published by any
            # documented Motilal REST endpoint or broadcast packet (doc 26 has no
            # such field; doc 33's depth packet carries only per-level
            # BidQty/OfferQty). Summing the <=5 received levels would pass a
            # partial book off as the exchange total, so report 0 instead.
            total_buy_qty = 0
            total_sell_qty = 0

            # Return in Angel's OpenAlgo standard format (matching lines 524-537 of angel/api/data.py)
            return {
                "bids": formatted_bids,
                "asks": formatted_asks,
                "high": high,
                "low": low,
                "ltp": ltp,
                "ltq": ltq,
                "open": open_price,
                "prev_close": prev_close,
                "volume": volume,
                "oi": oi,
                "totalbuyqty": total_buy_qty,
                "totalsellqty": total_sell_qty,
            }

        except Exception as e:
            logger.error(f"Error fetching market depth for {symbol} on {exchange}: {str(e)}")
            # Never return a zero-filled block: it is indistinguishable from a real
            # quote. Match broker/angel/api/data.py and surface the failure.
            raise Exception(f"Error fetching market depth: {str(e)}")

    def _get_index_depth(self, websocket, symbol: str, exchange: str, token) -> dict:
        """
        Get a depth-shaped block for an index symbol.

        Indices have no order book. They are registered through the separate
        IndexRegister API (doc 33-websocket-broadcast.md: ``Mofsl.IndexRegister("NSE")``),
        not through Register, which is why registering them as scrips never
        delivered any data.

        Args:
            websocket: connected MotilalWebSocket
            symbol: index symbol (OpenAlgo format)
            exchange: NSE_INDEX / BSE_INDEX (MCX_INDEX is unsupported)
            token: Index Code from the index master

        Returns:
            dict: Market depth structure with empty book and index OHLC/LTP
        """
        index_exchange = INDEX_EXCHANGE_MAP.get(exchange)
        if not index_exchange:
            # doc 33: IndexRegister takes "BSE or NSE" only.
            raise Exception(
                f"Error fetching market depth: index streaming is not supported for "
                f"{exchange} ({symbol}); Motilal registers NSE and BSE indices only"
            )

        logger.info(f"Registering index {index_exchange} for {symbol} (index code {token})")

        if not websocket.register_index(index_exchange):
            raise Exception(
                f"Error fetching market depth: failed to register index {index_exchange} "
                f"for {symbol}"
            )

        try:
            time.sleep(3.0)

            index_data = websocket.get_index(index_exchange, token) or {}
            quote = websocket.get_quote(index_exchange, token) or {}

            ltp = float(index_data.get("rate", 0) or quote.get("ltp", 0) or 0)
            if not ltp:
                raise Exception(
                    f"Error fetching market depth: no index data received for {symbol} "
                    f"on {exchange}"
                )

            return {
                # Indices have no order book, no traded quantity and no OI.
                "bids": [{"price": 0, "quantity": 0} for _ in range(5)],
                "asks": [{"price": 0, "quantity": 0} for _ in range(5)],
                "high": float(quote.get("high", 0) or 0),
                "low": float(quote.get("low", 0) or 0),
                "ltp": ltp,
                "ltq": 0,
                "open": float(quote.get("open", 0) or 0),
                "prev_close": float(quote.get("prev_close", 0) or 0),
                "volume": 0,
                "oi": 0,
                # Motilal does not publish exchange-wide totals (see get_depth).
                "totalbuyqty": 0,
                "totalsellqty": 0,
            }
        finally:
            try:
                websocket.unregister_index(index_exchange)
            except Exception as e:
                logger.warning(f"Error unregistering index {index_exchange}: {e}")

    #: Interval tokens that mean "one daily candle" (case-insensitive).
    DAILY_INTERVALS = {"D", "1D", "DAY", "DAILY"}

    def _today_ist(self):
        """Today's date in IST - the exchange calendar Motilal trades on."""
        from datetime import datetime, timedelta, timezone

        return datetime.now(timezone(timedelta(hours=5, minutes=30))).date()

    def _today_bar(self, symbol: str, exchange: str) -> dict | None:
        """Today's daily candle from the live LTP snapshot, or None.

        doc 26-price-ltp.md returns the *current day's* open/high/low/volume
        with ltp as the running close (Motilal's own "close" field is the
        PREVIOUS close, which is why get_quotes maps it to prev_close). Index
        symbols come from getindexltpdata through the same get_quotes entry
        point, so both instrument kinds work here.
        """
        quote = self.get_quotes(symbol, exchange)
        if not quote:
            return None

        close = float(quote.get("ltp") or 0)
        open_ = float(quote.get("open") or 0)
        high = float(quote.get("high") or 0)
        low = float(quote.get("low") or 0)

        # A snapshot with no traded price is not a candle - pre-open, a halted
        # scrip or a bad token. Returning a zero bar would draw a fake candle.
        if close <= 0 and open_ <= 0:
            return None

        # Guard against a snapshot taken before high/low populate.
        high = max(high, open_, close)
        low = min(x for x in (low, open_, close) if x > 0) if any(
            x > 0 for x in (low, open_, close)
        ) else 0.0

        from datetime import datetime, timezone

        today = self._today_ist()
        # Daily bars are stamped at midnight UTC of the calendar date, matching
        # the convention the other brokers' get_history normalises to
        # (e.g. broker/zerodha/api/data.py's daily branch).
        timestamp = int(
            datetime(today.year, today.month, today.day, tzinfo=timezone.utc).timestamp()
        )

        return {
            "timestamp": timestamp,
            "open": open_ or close,
            "high": high,
            "low": low or close,
            "close": close,
            "volume": int(quote.get("volume") or 0),
            "oi": int(quote.get("oi") or 0),
        }

    def get_history(
        self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        Only TODAY's daily candle is available from the Motilal Oswal API.

        There is no historical endpoint: the only OHLC surface Motilal documents
        is the EOD API (doc 38-eod-api.md / 39-eod-csv.md), which takes only
        ``exchangename``, dumps one row per scrip for a single day, and offers no
        symbol filter, no date range and no intraday option. Past days and every
        intraday interval are therefore impossible.

        What IS available is today: doc 26-price-ltp.md returns the current day's
        open/high/low/volume with ltp as the running close. That is served here
        as a one-row daily series so the trading terminal can draw and keep
        updating today's candle instead of failing outright. Each refetch (the
        terminal reconciles periodically) re-reads the live snapshot, so the bar
        tracks the session.

        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
            interval: Only daily ("D") is supported
            start_date: Start date in format YYYY-MM-DD
            end_date: End date in format YYYY-MM-DD

        Returns:
            A one-row DataFrame for today when the requested range includes
            today, otherwise an empty DataFrame (no data in that range).

        Raises:
            Exception: for any interval other than daily - returning an empty
                frame there would make the API report success with zero candles
                for an interval that can never be served.
        """
        columns = ["timestamp", "open", "high", "low", "close", "volume", "oi"]

        if str(interval or "").strip().upper() not in self.DAILY_INTERVALS:
            logger.error(
                f"Historical data requested for {symbol} on {exchange} ({interval}) but "
                "the Motilal Oswal API provides no intraday history"
            )
            raise Exception(
                f"Interval '{interval}' is not supported by the Motilal Oswal API: it "
                "publishes no historical or intraday OHLC endpoint. Only 'D' is "
                "available, and only for the current trading day."
            )

        today = self._today_ist()

        # Only today can be served; anything else is outside what Motilal has.
        from datetime import datetime

        def _as_date(value, fallback):
            try:
                return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
            except (TypeError, ValueError):
                return fallback

        start = _as_date(start_date, today)
        end = _as_date(end_date, today)

        if not (start <= today <= end):
            logger.warning(
                f"Motilal has no history before today: requested {start} to {end} for "
                f"{symbol} on {exchange}, returning no candles"
            )
            return pd.DataFrame(columns=columns)

        bar = self._today_bar(symbol, exchange)
        if bar is None:
            logger.warning(f"No live snapshot available for {symbol} on {exchange} yet")
            return pd.DataFrame(columns=columns)

        logger.info(
            f"Serving today's daily candle for {symbol} on {exchange} from the live "
            f"LTP snapshot (Motilal has no historical API)"
        )
        return pd.DataFrame([bar], columns=columns)

    def get_supported_intervals(self) -> dict:
        """Daily only, and only for the current day - see get_history.

        Motilal publishes no historical OHLC endpoint, so no intraday interval
        and no past date can be served. Today's daily candle comes from the live
        LTP snapshot. Kept consistent with `timeframe_map`, which is what
        `intervals_service` actually reads.
        """
        return {
            "seconds": [],
            "minutes": [],
            "hours": [],
            "days": sorted(k for k in self.timeframe_map if k == "D"),
            "weeks": [],
            "months": [],
        }
