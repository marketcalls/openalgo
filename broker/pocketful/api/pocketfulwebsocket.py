import json
import struct
import threading
import time

import websocket

from broker.pocketful.api.packet_decoder import (
    decodeCompactMarketData,
    decodeDetailedMarketData,
    decodeOrderUpdate,
    decodeSnapquoteData,
    decodeTradeUpdate,
)
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


# Configure logging
logger = get_logger(__name__)

# Global variables for WebSocket communication
websock = None
ws_connected = False
# Guards the connection bookkeeping: websock, ws_connected's reuse check and
# _connect_attempt. It is never held across a wait. Connecting takes seconds
# (closing a stale socket, then up to five seconds for the broker to answer),
# and while one caller did that under this lock every other quote and depth
# request queued on it, holding its own thread for as long.
ws_connect_lock = threading.Lock()
snapquote_marketdata_response = {}
compact_marketdata_response = {}
detailed_marketdata_response = {}
order_update_response = {}
trade_update_response = {}
dtlmktdata_dict = {}
cmptmktdata_dict = {}
snpqtdata_dict = {}

# Instruments that in-flight requests have subscribed, counted per feed mode.
# data.py drives this one module-level socket from every quote and depth
# request, so two requests can hold the same instrument at once. Without the
# count, the first to finish unsubscribed it at the broker and wiped the shared
# stores, and the other waited out its timeout with no data. Only the last
# holder now unsubscribes, and only that instrument's data is dropped; when the
# mode has no holders left the stores are wiped as before.
_subscribers_lock = threading.Lock()
_subscribers = {}  # (mode, exchangeCode, instrumentToken) -> holders


class _ConnectAttempt:
    """One connection under way. Its owner connects; later callers wait for it."""

    def __init__(self):
        self.done = threading.Event()
        self.ok = False


# The connection being made right now, or None. Claimed and cleared under
# ws_connect_lock; the connecting itself happens outside it.
_connect_attempt = None

# How long a connection gets: a pause after closing a stale socket, then up to
# _CONNECT_POLLS checks _CONNECT_POLL_SECONDS apart for the broker to answer.
_STALE_CLOSE_PAUSE = 1.0
_CONNECT_POLLS = 10
_CONNECT_POLL_SECONDS = 0.5
# A caller waiting on another caller's connection gives up after this long.
# The owner always finishes well inside it; this only bounds a stuck close.
_JOIN_WAIT_SECONDS = 15.0

# Feed mode -> (per-instrument store, latest-message variable) in this module.
_MODE_STORES = {
    "marketdata": ("dtlmktdata_dict", "detailed_marketdata_response"),
    "compact_marketdata": ("cmptmktdata_dict", "compact_marketdata_response"),
    "full_snapquote": ("snpqtdata_dict", "snapquote_marketdata_response"),
}


def _subscriber_key(mode, payload):
    return (mode, str(payload["exchangeCode"]), str(payload["instrumentToken"]))


def _claim(mode, payloads):
    """Count one more holder for each instrument. Pair with _release."""
    with _subscribers_lock:
        for payload in payloads:
            key = _subscriber_key(mode, payload)
            _subscribers[key] = _subscribers.get(key, 0) + 1


def _release(mode, payloads):
    """Count one holder fewer for each instrument.

    Returns:
        (released, idle): the payloads nobody holds any more, which are the
        only ones to unsubscribe at the broker, and whether the mode now has
        no holders at all. An instrument that was never claimed is released,
        which is what every unsubscribe did before the count existed.
    """
    released = []
    with _subscribers_lock:
        for payload in payloads:
            key = _subscriber_key(mode, payload)
            holders = _subscribers.get(key, 0)
            if holders <= 1:
                _subscribers.pop(key, None)
                released.append(payload)
            else:
                _subscribers[key] = holders - 1
        idle = not any(key[0] == mode for key in _subscribers)
    return released, idle


def _clear_released(mode, released, idle):
    """Drop the data left by released instruments; everything once the mode is idle."""
    store_name, latest_name = _MODE_STORES[mode]
    module_state = globals()
    if idle:
        module_state[latest_name] = {}
        module_state[store_name] = {}
        return
    released_ids = {
        (str(payload["instrumentToken"]), str(payload["exchangeCode"])) for payload in released
    }
    store = module_state[store_name]
    for token, exchange_code in released_ids:
        store.pop(f"{token}_{exchange_code}", None)
    latest = module_state[latest_name]
    if isinstance(latest, dict) and latest:
        latest_id = (str(latest.get("instrument_token")), str(latest.get("exchange_code")))
        if latest_id in released_ids:
            module_state[latest_name] = {}


# WebSocket message handlers
def on_message(ws, message):
    try:
        # Try to parse as JSON first
        try:
            data = json.loads(message)
            if isinstance(data, dict) and "mode" in data:
                mode = data["mode"]
            else:
                # If no mode in JSON, try binary parsing
                mode = struct.unpack(">b", message[0:1])[0]
        except Exception:
            # If JSON parsing fails, assume binary
            mode = struct.unpack(">b", message[0:1])[0]

        # Process based on message mode
        if mode == 1:  # Detailed market data
            res = decodeDetailedMarketData(message)
            global detailed_marketdata_response, dtlmktdata_dict
            detailed_marketdata_response = res
            if bool(res):
                key = str(res["instrument_token"]) + "_" + str(res["exchange_code"])
                dtlmktdata_dict[key] = res

        elif mode == 2:  # Compact market data
            res = decodeCompactMarketData(message)
            global compact_marketdata_response, cmptmktdata_dict
            compact_marketdata_response = res
            if bool(res):
                key = str(res["instrument_token"]) + "_" + str(res["exchange_code"])
                cmptmktdata_dict[key] = res

        elif mode == 4:  # Snapquote data
            res = decodeSnapquoteData(message)
            global snapquote_marketdata_response, snpqtdata_dict
            snapquote_marketdata_response = res
            if bool(res):
                key = str(res["instrument_token"]) + "_" + str(res["exchange_code"])
                snpqtdata_dict[key] = res

        elif mode == 50:  # Order updates
            res = decodeOrderUpdate(message)
            global order_update_response
            order_update_response = res

        elif mode == 51:  # Trade updates
            res = decodeTradeUpdate(message)
            global trade_update_response
            trade_update_response = res

    except Exception as e:
        logger.error(f"Error processing WebSocket message: {str(e)}")


def on_error(ws, error):
    logger.error(f"WebSocket error: {str(error)}")
    global ws_connected
    ws_connected = False


def on_close(ws, close_status_code=None, close_msg=None):
    logger.info(f"WebSocket connection closed: code={close_status_code}, message={close_msg}")
    global ws_connected
    ws_connected = False


def on_open(ws):
    logger.info("WebSocket connection established")
    # Start heartbeat thread, one per socket. It stops once this socket is
    # replaced or closed (see heartbeat_thread), so a reconnect no longer
    # leaves the previous heartbeat looping for the life of the worker.
    if getattr(ws, "_openalgo_heartbeat", None) is None:
        hb_thread = threading.Thread(
            target=heartbeat_thread, args=(ws,), name="pocketful-hb", daemon=True
        )
        ws._openalgo_heartbeat = hb_thread
        hb_thread.start()
    global ws_connected
    ws_connected = True


def _is_current_socket(client_socket):
    """True while client_socket is still this module's socket and still running."""
    return websock is client_socket and getattr(client_socket, "keep_running", True) is not False


def heartbeat_thread(client_socket):
    """Send periodic heartbeats to keep the connection alive"""
    while _is_current_socket(client_socket):
        try:
            if (
                ws_connected
                and client_socket
                and client_socket.sock
                and client_socket.sock.connected
            ):
                client_socket.send(json.dumps({"a": "h"}))
                logger.debug("Heartbeat sent")
            else:
                logger.debug("Skipping heartbeat, socket not connected")
            time.sleep(15)  # Send heartbeat every 15 seconds (reduced from 20)
        except Exception as e:
            logger.error(f"Error in heartbeat: {str(e)}")
            time.sleep(5)  # Wait a bit before retrying on error
        time.sleep(8)
    logger.debug("Heartbeat stopped: its socket was replaced or closed")


def get_snapquotedata():
    """Get the latest snapquote data"""
    return snapquote_marketdata_response


def get_compact_marketdata():
    """Get the latest compact market data"""
    return compact_marketdata_response


def get_detailed_marketdata():
    """Get the latest detailed market data"""
    return detailed_marketdata_response


def get_order_update():
    """Get the latest order update"""
    return order_update_response


def get_trade_update():
    """Get the latest trade update"""
    return trade_update_response


def get_multiple_detailed_marketdata():
    """Get multiple detailed market data"""
    return dtlmktdata_dict


def get_multiple_compact_marketdata():
    """Get multiple compact market data"""
    return cmptmktdata_dict


def get_multiple_snapquotedata():
    """Get multiple snapquote data"""
    return snpqtdata_dict


def get_ws_connection_status():
    """Check if WebSocket is connected"""
    return ws_connected


class PocketfulSocket:
    base_url = "https://trade.pocketful.in"

    def __init__(self, client_id, access_token):
        self.headers = {"Content-type": "application/json"}
        self.access_token = access_token
        self.client_id = client_id

        # Generate WebSocket URL
        if "https" in self.base_url:
            url = self.base_url.replace("https", "wss")
        else:
            url = self.base_url.replace("http", "ws")
        self.websocket_url = url

    def print_access_token(self):
        return self.access_token

    def set_access_token(self, access_token):
        self.access_token = access_token

    def get_request(self, url, params):
        """Make GET request using shared httpx client"""
        client = get_httpx_client()
        headers = dict(self.headers)
        headers["Authorization"] = f"Bearer {self.access_token}"
        res = client.get(f"{self.base_url}{url}", params=params, headers=headers)
        return res.json()

    def post_request(self, url, data):
        """Make POST request using shared httpx client"""
        client = get_httpx_client()
        headers = dict(self.headers)
        headers["Authorization"] = f"Bearer {self.access_token}"
        res = client.post(f"{self.base_url}{url}", headers=headers, json=data)
        logger.info(f"POST Response: {res.status_code}")
        return res.json()

    def put_request(self, url, data):
        """Make PUT request using shared httpx client"""
        client = get_httpx_client()
        headers = dict(self.headers)
        headers["Authorization"] = f"Bearer {self.access_token}"
        res = client.put(f"{self.base_url}{url}", headers=headers, json=data)
        logger.info(f"PUT Response: {res.status_code}")
        return res.json()

    def delete_request(self, url, params):
        """Make DELETE request using shared httpx client"""
        client = get_httpx_client()
        headers = dict(self.headers)
        headers["Authorization"] = f"Bearer {self.access_token}"
        res = client.delete(f"{self.base_url}{url}", params=params, headers=headers)
        return res.json()

    def run_socket(self):
        """Connect the shared feed socket, or wait for the connection already under way.

        Only one caller connects at a time. The lock is held only to read and
        claim the connection state, never across the connecting: the caller
        that claims it closes any stale socket, opens the new one and waits for
        the broker to answer with the lock released, and a caller arriving
        meanwhile waits for that same connection instead of queueing on the
        lock behind it.

        A caller whose awaited connection failed tries once more, connecting
        itself or joining the next one, as it did when it queued on the lock and
        then found no connection. Returns True once connected.
        """
        global websock, _connect_attempt

        joined = None
        for _ in range(2):
            with ws_connect_lock:
                # Check if we already have a working connection
                if websock and ws_connected:
                    logger.info("WebSocket already connected, reusing existing connection")
                    return True

                attempt = _connect_attempt
                stale = None
                owner = attempt is None
                if owner:
                    attempt = _ConnectAttempt()
                    _connect_attempt = attempt
                    # A socket that is not connected is replaced. Taking it out
                    # of websock here also ends its heartbeat.
                    stale, websock = websock, None

            if owner:
                return self._connect_claimed(attempt, stale)

            if attempt is joined:
                # The connection this caller already waited for is still being
                # wound up; there is nothing new to wait for.
                break
            logger.info("WebSocket connection already under way, waiting for it")
            if attempt.done.wait(_JOIN_WAIT_SECONDS) and attempt.ok:
                return True
            joined = attempt

        logger.error("Failed to establish WebSocket connection")
        return False

    def _connect_claimed(self, attempt, stale):
        """Make the connection this caller claimed in run_socket. Never holds the lock to wait."""
        global websock, _connect_attempt

        ok = False
        try:
            # If we have a socket but it's not connected, close it properly
            if stale is not None:
                try:
                    logger.info("Closing stale WebSocket connection")
                    stale.close()
                    time.sleep(_STALE_CLOSE_PAUSE)  # Small delay to ensure socket closes
                except Exception as e:
                    logger.warning(f"Error closing stale connection: {str(e)}")

            try:
                client_id = self.client_id
                access_token = self.access_token
                websocket_url = self.websocket_url

                # Create WebSocket connection URL
                full_url = (
                    f"{websocket_url}/ws/v1/feeds?login_id={client_id}&access_token={access_token}"
                )
                logger.info(f"Connecting to WebSocket: {full_url}")

                # Connect to WebSocket
                client_socket = self._connect(full_url)
                with ws_connect_lock:
                    websock = client_socket

                # Start WebSocket in a thread
                ws_thread = threading.Thread(target=self._webs_start, args=(client_socket,))
                ws_thread.daemon = True
                ws_thread.start()

                # Wait for connection to establish, with the lock released
                counter = 0
                while counter < _CONNECT_POLLS:
                    status = get_ws_connection_status()
                    if status:
                        logger.info("WebSocket connection successful")
                        ok = True
                        return True
                    time.sleep(_CONNECT_POLL_SECONDS)  # Shorter interval checks
                    counter += 1

                logger.error("Failed to establish WebSocket connection (timeout)")
                return False

            except Exception as e:
                logger.error(f"WebSocket connection error: {str(e)}")
                return False
        finally:
            with ws_connect_lock:
                attempt.ok = ok
                if _connect_attempt is attempt:
                    _connect_attempt = None
            attempt.done.set()

    def _connect(self, url):
        """Create WebSocket connection"""
        websocket.enableTrace(False)
        ws = websocket.WebSocketApp(
            url, on_message=on_message, on_error=on_error, on_close=on_close
        )
        ws.on_open = on_open
        return ws

    def _webs_start(self, ws):
        """Start WebSocket connection"""
        ws.run_forever()

    def subscribe_detailed_marketdata(self, detailedmarketdata_payload):
        """Subscribe to detailed market data"""
        _claim("marketdata", [detailedmarketdata_payload])
        try:
            subscription_pkt = [
                [
                    detailedmarketdata_payload["exchangeCode"],
                    detailedmarketdata_payload["instrumentToken"],
                ]
            ]
            global websock
            sub_packet = {"a": "subscribe", "v": subscription_pkt, "m": "marketdata"}
            websock.send(json.dumps(sub_packet))
            logger.info(f"Subscribed to detailed market data: {detailedmarketdata_payload}")
            return True
        except Exception as e:
            logger.error(f"Error subscribing to detailed market data: {str(e)}")
            return False

    def read_detailed_marketdata(self):
        """Read the latest detailed market data"""
        data = get_detailed_marketdata()
        return data

    def unsubscribe_detailed_marketdata(self, detailedmarketdata_payload):
        """Unsubscribe from detailed market data.

        The released instrument's data is cleared whether or not the broker was
        told, as the compact and snapquote modes already do. A send that failed
        (the socket dropped, or another request holds the reconnect) used to
        leave the last packet behind as the latest one, and the next quote for
        that instrument was answered from it at once, as if it were fresh.
        """
        released, idle = _release("marketdata", [detailedmarketdata_payload])
        try:
            if released:
                unsubscription_pkt = [
                    [
                        detailedmarketdata_payload["exchangeCode"],
                        detailedmarketdata_payload["instrumentToken"],
                    ]
                ]
                global websock
                sub_packet = {"a": "unsubscribe", "v": unsubscription_pkt, "m": "marketdata"}
                websock.send(json.dumps(sub_packet))
            # Clear data
            _clear_released("marketdata", released, idle)
            logger.info(f"Unsubscribed from detailed market data: {detailedmarketdata_payload}")
            return True
        except Exception as e:
            logger.error(f"Error unsubscribing from detailed market data: {str(e)}")
            # Still clear data even on error
            _clear_released("marketdata", released, idle)
            return False

    def subscribe_compact_marketdata(self, compactmarketdata_payload):
        """Subscribe to compact market data with reconnection support"""
        global websock, ws_connected
        _claim("compact_marketdata", [compactmarketdata_payload])

        # Try to subscribe up to 3 times
        for attempt in range(3):
            try:
                # Check if we need to reconnect
                if (
                    not ws_connected
                    or not websock
                    or not hasattr(websock, "sock")
                    or not websock.sock
                    or not getattr(websock.sock, "connected", False)
                ):
                    logger.warning(
                        f"WebSocket not connected on attempt {attempt + 1}, reconnecting..."
                    )
                    self.run_socket()
                    time.sleep(1)  # Give it time to connect

                if not ws_connected:
                    logger.error("Failed to reconnect WebSocket")
                    continue  # Try again

                # Proceed with subscription
                subscription_pkt = [
                    [
                        compactmarketdata_payload["exchangeCode"],
                        compactmarketdata_payload["instrumentToken"],
                    ]
                ]
                sub_packet = {"a": "subscribe", "v": subscription_pkt, "m": "compact_marketdata"}
                websock.send(json.dumps(sub_packet))
                logger.info(f"Subscribed to compact market data: {compactmarketdata_payload}")
                return True

            except Exception as e:
                logger.error(
                    f"Error subscribing to compact market data (attempt {attempt + 1}): {str(e)}"
                )
                # Force reconnection on next attempt
                ws_connected = False
                time.sleep(0.5 * (attempt + 1))  # Increasing backoff

        # If we get here, all attempts failed
        return False

    def unsubscribe_compact_marketdata(self, compactmarketdata_payload):
        """Unsubscribe from compact market data with error handling"""
        global websock, ws_connected

        released, idle = _release("compact_marketdata", [compactmarketdata_payload])
        try:
            # Only attempt to unsubscribe if we have a connection
            if (
                not ws_connected
                or not websock
                or not hasattr(websock, "sock")
                or not websock.sock
                or not getattr(websock.sock, "connected", False)
            ):
                logger.warning(
                    "Cannot unsubscribe from compact market data, WebSocket not connected"
                )
                # Still clear data even if we can't unsubscribe
                _clear_released("compact_marketdata", released, idle)
                return False

            if released:
                unsubscription_pkt = [
                    [
                        compactmarketdata_payload["exchangeCode"],
                        compactmarketdata_payload["instrumentToken"],
                    ]
                ]
                sub_packet = {
                    "a": "unsubscribe",
                    "v": unsubscription_pkt,
                    "m": "compact_marketdata",
                }
                websock.send(json.dumps(sub_packet))

            # Clear data
            _clear_released("compact_marketdata", released, idle)

            logger.info(f"Unsubscribed from compact market data: {compactmarketdata_payload}")
            return True
        except Exception as e:
            logger.error(f"Error unsubscribing from compact market data: {str(e)}")
            # Still clear data even on error
            _clear_released("compact_marketdata", released, idle)
            return False

    def read_compact_marketdata(self):
        """Read the latest compact market data"""
        data = get_compact_marketdata()
        return data

    def subscribe_snapquote_data(self, snapquotedata_payload):
        """Subscribe to snapquote data with reconnection support"""
        global websock, ws_connected
        _claim("full_snapquote", [snapquotedata_payload])

        # Try to subscribe up to 3 times
        for attempt in range(3):
            try:
                # Check if we need to reconnect
                if (
                    not ws_connected
                    or not websock
                    or not websock.sock
                    or not websock.sock.connected
                ):
                    logger.warning(
                        f"WebSocket not connected on attempt {attempt + 1}, reconnecting..."
                    )
                    self.run_socket()
                    time.sleep(1)  # Give it time to connect

                if not ws_connected:
                    logger.error("Failed to reconnect WebSocket")
                    continue  # Try again

                # Proceed with subscription
                subscription_pkt = [
                    [
                        snapquotedata_payload["exchangeCode"],
                        snapquotedata_payload["instrumentToken"],
                    ]
                ]
                sub_packet = {
                    "a": "subscribe",
                    "v": subscription_pkt,
                    "m": "full_snapquote",  # Try full_snapquote instead of snapquote
                }
                websock.send(json.dumps(sub_packet))
                logger.info(f"Subscribed to snapquote data: {snapquotedata_payload}")
                return True

            except Exception as e:
                logger.error(
                    f"Error subscribing to snapquote data (attempt {attempt + 1}): {str(e)}"
                )
                # Force reconnection on next attempt
                ws_connected = False
                time.sleep(0.5 * (attempt + 1))  # Increasing backoff

        # If we get here, all attempts failed
        return False

    def unsubscribe_snapquote_data(self, snapquotedata_payload):
        """Unsubscribe from snapquote data with error handling"""
        global websock, ws_connected

        released, idle = _release("full_snapquote", [snapquotedata_payload])
        try:
            # Only attempt to unsubscribe if we have a connection
            if (
                not ws_connected
                or not websock
                or not hasattr(websock, "sock")
                or not websock.sock
                or not getattr(websock.sock, "connected", False)
            ):
                logger.warning("Cannot unsubscribe, WebSocket not connected")
                # Still clear data even if we can't unsubscribe
                _clear_released("full_snapquote", released, idle)
                return False

            if released:
                unsubscription_pkt = [
                    [
                        snapquotedata_payload["exchangeCode"],
                        snapquotedata_payload["instrumentToken"],
                    ]
                ]
                sub_packet = {
                    "a": "unsubscribe",
                    "v": unsubscription_pkt,
                    "m": "full_snapquote",  # Match subscription mode
                }
                websock.send(json.dumps(sub_packet))

            # Clear data
            _clear_released("full_snapquote", released, idle)

            logger.info(f"Unsubscribed from snapquote data: {snapquotedata_payload}")
            return True
        except Exception as e:
            logger.error(f"Error unsubscribing from snapquote data: {str(e)}")
            # Still clear data even on error
            _clear_released("full_snapquote", released, idle)
            return False

    def read_snapquote_data(self):
        """Read the latest snapquote data"""
        data = get_snapquotedata()
        return data

    def subscribe_order_update(self, orderupdate_payload):
        subscription_pkt = [orderupdate_payload["client_id"], "web"]
        th_order_update = threading.Thread(
            target=send_message, args=("OrderUpdateMessage", subscription_pkt)
        )
        th_order_update.start()

    def unsubscribe_order_update(self, orderupdate_payload):
        unsubscription_pkt = [orderupdate_payload["client_id"], "web"]
        th_order_update = threading.Thread(
            target=unsubscribe_update, args=("OrderUpdateMessage", unsubscription_pkt)
        )
        th_order_update.start()

    def read_order_update_data(self):
        data = get_order_update()
        return data

    def subscribe_trade_update(self, tradeupdate_payload):
        subscription_pkt = [tradeupdate_payload["client_id"], "web"]
        th_trade_update = threading.Thread(
            target=send_message, args=("TradeUpdateMessage", subscription_pkt)
        )
        th_trade_update.start()

    def unsubscribe_trade_update(self, tradeupdate_payload):
        unsubscription_pkt = [tradeupdate_payload["client_id"], "web"]
        th_trade_update = threading.Thread(
            target=unsubscribe_update, args=("OrderUpdateMessage", unsubscription_pkt)
        )
        th_trade_update.start()

    def read_trade_update_data(self):
        data = get_trade_update()
        return data

    def subscribe_multiple_detailed_marketdata(self, detailedmarketdata_payload):
        """Subscribe to multiple detailed market data"""
        _claim("marketdata", detailedmarketdata_payload)
        try:
            subscription_pkt = []
            for payload in detailedmarketdata_payload:
                pkt = [payload["exchangeCode"], payload["instrumentToken"]]
                subscription_pkt.append(pkt)

            global websock
            sub_packet = {"a": "subscribe", "v": subscription_pkt, "m": "marketdata"}
            websock.send(json.dumps(sub_packet))
            logger.info(
                f"Subscribed to multiple detailed market data: {detailedmarketdata_payload}"
            )
            return True
        except Exception as e:
            logger.error(f"Error subscribing to multiple detailed market data: {str(e)}")
            return False

    def unsubscribe_multiple_detailed_marketdata(self, detailedmarketdata_payload):
        """Unsubscribe from multiple detailed market data"""
        try:
            released, idle = _release("marketdata", detailedmarketdata_payload)
            unsubscription_pkt = []
            for payload in released:
                pkt = [payload["exchangeCode"], payload["instrumentToken"]]
                unsubscription_pkt.append(pkt)

            if unsubscription_pkt:
                global websock
                sub_packet = {"a": "unsubscribe", "v": unsubscription_pkt, "m": "marketdata"}
                websock.send(json.dumps(sub_packet))
            # Clear data
            _clear_released("marketdata", released, idle)
            logger.info(
                f"Unsubscribed from multiple detailed market data: {detailedmarketdata_payload}"
            )
            return True
        except Exception as e:
            logger.error(f"Error unsubscribing from multiple detailed market data: {str(e)}")
            return False

    def read_multiple_detailed_marketdata(self):
        """Read multiple detailed market data"""
        data = get_multiple_detailed_marketdata()
        return data

    def subscribe_multiple_compact_marketdata(self, compactmarketdata_payload):
        """Subscribe to multiple compact market data"""
        _claim("compact_marketdata", compactmarketdata_payload)
        try:
            subscription_pkt = []
            for payload in compactmarketdata_payload:
                pkt = [payload["exchangeCode"], payload["instrumentToken"]]
                subscription_pkt.append(pkt)

            global websock
            sub_packet = {"a": "subscribe", "v": subscription_pkt, "m": "compact_marketdata"}
            websock.send(json.dumps(sub_packet))
            logger.info(f"Subscribed to multiple compact market data: {compactmarketdata_payload}")
            return True
        except Exception as e:
            logger.error(f"Error subscribing to multiple compact market data: {str(e)}")
            return False

    def unsubscribe_multiple_compact_marketdata(self, compactmarketdata_payload):
        """Unsubscribe from multiple compact market data"""
        try:
            released, idle = _release("compact_marketdata", compactmarketdata_payload)
            unsubscription_pkt = []
            for payload in released:
                pkt = [payload["exchangeCode"], payload["instrumentToken"]]
                unsubscription_pkt.append(pkt)

            if unsubscription_pkt:
                global websock
                sub_packet = {
                    "a": "unsubscribe",
                    "v": unsubscription_pkt,
                    "m": "compact_marketdata",
                }
                websock.send(json.dumps(sub_packet))
            # Clear data
            _clear_released("compact_marketdata", released, idle)
            logger.info(
                f"Unsubscribed from multiple compact market data: {compactmarketdata_payload}"
            )
            return True
        except Exception as e:
            logger.error(f"Error unsubscribing from multiple compact market data: {str(e)}")
            return False

    def read_multiple_compact_marketdata(self):
        """Read multiple compact market data"""
        data = get_multiple_compact_marketdata()
        return data

    def subscribe_multiple_snapquote_data(self, snapquotedata_payload):
        """Subscribe to multiple snapquote data"""
        _claim("full_snapquote", snapquotedata_payload)
        try:
            subscription_pkt = []
            for payload in snapquotedata_payload:
                pkt = [payload["exchangeCode"], payload["instrumentToken"]]
                subscription_pkt.append(pkt)

            global websock
            sub_packet = {"a": "subscribe", "v": subscription_pkt, "m": "full_snapquote"}
            websock.send(json.dumps(sub_packet))
            logger.info(f"Subscribed to multiple snapquote data: {snapquotedata_payload}")
            return True
        except Exception as e:
            logger.error(f"Error subscribing to multiple snapquote data: {str(e)}")
            return False

    def unsubscribe_multiple_snapquote_data(self, snapquotedata_payload):
        """Unsubscribe from multiple snapquote data"""
        try:
            released, idle = _release("full_snapquote", snapquotedata_payload)
            unsubscription_pkt = []
            for payload in released:
                pkt = [payload["exchangeCode"], payload["instrumentToken"]]
                unsubscription_pkt.append(pkt)

            if unsubscription_pkt:
                global websock
                sub_packet = {"a": "unsubscribe", "v": unsubscription_pkt, "m": "full_snapquote"}
                websock.send(json.dumps(sub_packet))
            # Clear data
            _clear_released("full_snapquote", released, idle)
            logger.info(f"Unsubscribed from multiple snapquote data: {snapquotedata_payload}")
            return True
        except Exception as e:
            logger.error(f"Error unsubscribing from multiple snapquote data: {str(e)}")
            return False

    def read_multiple_snapquote_data(self):
        """Read multiple snapquote data"""
        data = get_multiple_snapquotedata()
        return data
