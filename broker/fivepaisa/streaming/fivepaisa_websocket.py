import base64
import json
import ssl
import time
from typing import Dict, List, Optional
from urllib.parse import quote

import logzero
import websocket
from logzero import logger

from utils.logging import get_logger

# WebSocket hosts, keyed by the RedirectServer claim in the access-token JWT.
# 5Paisa shards the feed: order updates are only pushed on the host matching
# the token's RedirectServer (docs 08-order-tracking.md, "Web Socket Trade
# Confirmation"). Module-level so the order-update adapter can resolve the same
# URL without constructing a market-data client.
WEBSOCKET_URLS = {
    "A": "wss://aopenfeed.5paisa.com/feeds/api/chat",
    "B": "wss://bopenfeed.5paisa.com/feeds/api/chat",
    "C": "wss://openfeed.5paisa.com/feeds/api/chat",
    "default": "wss://openfeed.5paisa.com/Feeds/api/chat",
}


def decode_redirect_server(token: str) -> str:
    """Read the RedirectServer claim (A/B/C) out of a 5Paisa access-token JWT.

    Returns "default" when the token is not a decodable JWT or carries no
    RedirectServer claim.
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return "default"

        # Base64url payload, re-padded to a multiple of 4.
        payload = parts[1]
        padding = len(payload) % 4
        if padding:
            payload += "=" * (4 - padding)

        payload_data = json.loads(base64.urlsafe_b64decode(payload))
        return payload_data.get("RedirectServer", "default")
    except Exception:
        return "default"


def get_feed_url(redirect_server: str) -> str:
    """Map a RedirectServer value to its feed WebSocket URL."""
    return WEBSOCKET_URLS.get(redirect_server, WEBSOCKET_URLS["default"])


class FivePaisaWebSocket:
    """
    5Paisa WebSocket Client for market data streaming
    Based on 5Paisa API documentation
    """

    HEART_BEAT_INTERVAL = 10  # seconds (websocket ping interval)
    # Pong deadline; must be < HEART_BEAT_INTERVAL. Without it, a half-open
    # (dead-but-not-closed) TCP connection is never detected: run_forever blocks
    # forever, on_close never fires, the socket FD leaks and no reconnect occurs.
    PING_TIMEOUT = 5  # seconds

    # Subscription Methods
    MARKET_FEED = "MarketFeedV3"
    MARKET_DEPTH = "MarketDepthService"
    OI_FEED = "GetScripInfoForFuture"

    # Operations
    SUBSCRIBE = "Subscribe"
    UNSUBSCRIBE = "Unsubscribe"

    # Exchange codes
    EXCHANGE_MAP = {"NSE": "N", "BSE": "B", "MCX": "M"}

    # Exchange Type codes
    EXCHANGE_TYPE_MAP = {
        "C": "Cash",  # NSE/BSE Cash
        "D": "Derivatives",  # F&O
        "U": "Currency",  # Currency
    }

    wsapp = None

    def __init__(self, access_token: str, client_code: str):
        """
        Initialize the 5Paisa WebSocket client

        Parameters:
        -----------
        access_token: str
            Access token received from login API
        client_code: str
            Demat account client code of the client in plain text
        """
        self.access_token = access_token
        self.client_code = client_code
        self.connected = False

        # Setup logging
        self.logger = get_logger("fivepaisa_websocket")

        # Decode token to get redirect server
        self.redirect_server = self._decode_token(access_token)
        self.websocket_url = self._get_feed_url(self.redirect_server)

        if not self._sanity_check():
            self.logger.error(
                "Invalid initialization parameters. Provide valid values for access_token and client_code."
            )
            raise Exception("Provide valid values for access_token and client_code")

    def _sanity_check(self) -> bool:
        """Validate initialization parameters"""
        if not all([self.access_token, self.client_code]):
            return False
        return True

    def _decode_token(self, token: str) -> str:
        """
        Decode JWT token to extract RedirectServer parameter

        Parameters:
        -----------
        token: str
            JWT access token

        Returns:
        --------
        str: RedirectServer value (A, B, C, or default)
        """
        redirect_server = decode_redirect_server(token)
        if redirect_server == "default":
            self.logger.warning("Could not read RedirectServer from token, using default server")
        else:
            self.logger.debug(f"Decoded RedirectServer: {redirect_server}")
        return redirect_server

    def _get_feed_url(self, redirect_server: str) -> str:
        """
        Get the appropriate WebSocket URL based on redirect server

        Parameters:
        -----------
        redirect_server: str
            Redirect server identifier (A, B, C, or default)

        Returns:
        --------
        str: WebSocket URL
        """
        url = get_feed_url(redirect_server)
        self.logger.debug(f"Using WebSocket URL: {url}")
        return url

    def connect(self):
        """
        Establish WebSocket connection to 5Paisa server
        Connection URL format: wss://[server].5paisa.com/feeds/api/chat?Value1={{access_token}}|{{clientcode}}
        """
        connection_url = f"{self.websocket_url}?Value1={self.access_token}|{self.client_code}"
        self.logger.debug(f"Connecting to: {self.websocket_url}")
        self.logger.debug(f"Client Code: {self.client_code}")

        try:
            self.wsapp = websocket.WebSocketApp(
                connection_url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
            )

            # Run the WebSocket connection. ping_timeout enforces a pong deadline
            # so a half-open connection is detected and closed (freeing the FD and
            # triggering reconnect) instead of blocking run_forever indefinitely.
            self.wsapp.run_forever(
                sslopt={"cert_reqs": ssl.CERT_NONE},
                ping_interval=self.HEART_BEAT_INTERVAL,
                ping_timeout=self.PING_TIMEOUT,
            )

        except Exception as e:
            self.logger.error(f"Error during WebSocket connection: {e}")
            raise e

    def close_connection(self):
        """Close the WebSocket connection.

        Idempotent and exception-safe: callers (reconnect, token rebuild,
        adapter disconnect) may invoke this on an already-closed or partially
        initialized client. We always clear state and never propagate, so a
        failed close can't leak the handle or break the caller.
        """
        self.connected = False
        wsapp = self.wsapp
        if wsapp is None:
            return
        # Drop our reference first so a second call is a no-op even if close() blocks.
        self.wsapp = None
        try:
            wsapp.close()
        except Exception as e:
            self.logger.debug(f"Error closing 5Paisa WebSocket: {e}")

    def subscribe(self, method: str, scrip_data: list[dict]) -> None:
        """
        Subscribe to market data feed

        Parameters:
        -----------
        method: str
            Subscription method - MarketFeedV3, MarketDepthService, GetScripInfoForFuture
        scrip_data: List[Dict]
            List of scrip information
            Format: [{"Exch": "N", "ExchType": "C", "ScripCode": 1660}]
        """
        if not self.connected:
            self.logger.warning("WebSocket not connected. Cannot subscribe.")
            return

        try:
            request = {
                "Method": method,
                "Operation": self.SUBSCRIBE,
                "ClientCode": self.client_code,
                "MarketFeedData": scrip_data,
            }

            self.wsapp.send(json.dumps(request))
            self.logger.info(f"Subscribed to {method} with data: {scrip_data}")

        except Exception as e:
            self.logger.error(f"Error during subscription: {e}")
            raise e

    def unsubscribe(self, method: str, scrip_data: list[dict]) -> None:
        """
        Unsubscribe from market data feed

        Parameters:
        -----------
        method: str
            Subscription method - MarketFeedV3, MarketDepthService, GetScripInfoForFuture
        scrip_data: List[Dict]
            List of scrip information
            Format: [{"Exch": "N", "ExchType": "C", "ScripCode": 1660}]
        """
        if not self.connected:
            self.logger.warning("WebSocket not connected. Cannot unsubscribe.")
            return

        try:
            request = {
                "Method": method,
                "Operation": self.UNSUBSCRIBE,
                "ClientCode": self.client_code,
                "MarketFeedData": scrip_data,
            }

            self.wsapp.send(json.dumps(request))
            self.logger.info(f"Unsubscribed from {method} with data: {scrip_data}")

        except Exception as e:
            self.logger.error(f"Error during unsubscription: {e}")
            raise e

    def _on_open(self, wsapp):
        """Callback when WebSocket connection is opened"""
        self.logger.info("5Paisa WebSocket connection opened")
        self.connected = True
        self.on_open(wsapp)

    def _on_message(self, wsapp, message):
        """Callback for receiving messages from WebSocket"""
        try:
            # Parse JSON message
            data = json.loads(message)
            self.logger.debug(f"Received message: {data}")

            # Check if it's an array (market data) or single object
            if isinstance(data, list):
                for item in data:
                    self.on_data(wsapp, item)
            else:
                self.on_data(wsapp, data)

        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse message: {e}")
            self.on_message(wsapp, message)
        except Exception as e:
            self.logger.error(f"Error processing message: {e}")

    def _on_error(self, wsapp, error):
        """Callback for WebSocket errors"""
        self.logger.error(f"5Paisa WebSocket error: {error}")
        self.on_error(wsapp, error)

    def _on_close(self, wsapp, close_status_code=None, close_msg=None):
        """Callback when WebSocket connection is closed"""
        self.logger.info(
            f"5Paisa WebSocket connection closed. Code: {close_status_code}, Message: {close_msg}"
        )
        self.connected = False
        self.on_close(wsapp)

    # Callback methods to be overridden by user
    def on_open(self, wsapp):
        """Override this method to handle connection open event"""
        pass

    def on_data(self, wsapp, data: dict):
        """Override this method to handle market data"""
        pass

    def on_message(self, wsapp, message):
        """Override this method to handle raw messages"""
        pass

    def on_error(self, wsapp, error):
        """Override this method to handle errors"""
        pass

    def on_close(self, wsapp):
        """Override this method to handle connection close event"""
        pass
