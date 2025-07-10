# broker/upstox/streaming/upstox_client.py
import asyncio
import json
import ssl
import websockets
import logging
import uuid
from typing import Dict, Any, Optional, List, Callable, Coroutine
from google.protobuf.json_format import MessageToDict
import requests

from . import MarketDataFeedV3_pb2
from .MarketDataFeedV3_pb2 import FeedResponse

class UpstoxWebSocketClient:
    """
    Upstox V3 WebSocket client implementation.
    Consistent with other broker websocket clients (callback dict, logging, reconnect, etc).
    """
    API_URL = "https://api.upstox.com/v3"
    AUTH_ENDPOINT = f"{API_URL}/feed/market-data-feed/authorize"

    def __init__(self, auth_token: str):
        self.auth_token: str = auth_token
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.logger = logging.getLogger("upstox_websocket")
        self._subscriptions: set = set()
        self.running: bool = False
        self.ws_task: Optional[asyncio.Task] = None
        self.callbacks: Dict[str, Optional[Callable]] = {
            "on_connect": None,
            "on_message": None,
            "on_error": None,
            "on_close": None
        }
        self._reconnect_attempts: int = 0
        self._max_reconnect_attempts: int = 5
        self._reconnect_delay: int = 2  # seconds, exponential backoff

    def _get_ws_auth(self) -> Dict[str, Any]:
        """
        Get WebSocket authorization from Upstox REST endpoint.
        Returns:
            dict: Auth response containing authorized_redirect_uri
        """
        if not self.auth_token or not isinstance(self.auth_token, str) or len(self.auth_token) < 10:
            self.logger.error("No valid access token provided. Cannot authorize WebSocket.")
            return {}
        try:
            headers = {
                'Accept': 'application/json',
                'Authorization': f'Bearer {self.auth_token}'
            }
            self.logger.debug(f"Requesting WS authorization with headers: {headers}")
            response = requests.get(self.AUTH_ENDPOINT, headers=headers)
            self.logger.debug(f"REST /authorize status: {response.status_code}")
            self.logger.debug(f"REST /authorize response: {response.text}")
            response.raise_for_status()
            resp_json = response.json()
            ws_uri = resp_json.get('data', {}).get('authorized_redirect_uri')
            self.logger.info(f"Upstox authorized_redirect_uri: {ws_uri}")
            return resp_json
        except Exception as e:
            self.logger.error(f"Auth error: {e}")
            return {}

    async def connect(self) -> bool:
        """
        Establish WebSocket connection with reconnection logic.
        Calls on_connect callback on success.
        Returns:
            bool: True if connection successful, False otherwise
        """
        attempt = 0
        while attempt < self._max_reconnect_attempts:
            try:
                if not self.auth_token or not isinstance(self.auth_token, str) or len(self.auth_token) < 10:
                    self.logger.error("No valid access token provided. Cannot connect to WebSocket.")
                    if self.callbacks["on_error"]:
                        await self.callbacks["on_error"]("No valid access token provided.")
                    return False
                auth_response = self._get_ws_auth()
                if not auth_response:
                    self.logger.error("Failed to get WebSocket authorization")
                    if self.callbacks["on_error"]:
                        await self.callbacks["on_error"]("Failed to get WebSocket authorization")
                    return False
                ws_url = auth_response.get("data", {}).get("authorized_redirect_uri")
                if not ws_url:
                    self.logger.error("No WebSocket URL in auth response")
                    if self.callbacks["on_error"]:
                        await self.callbacks["on_error"]("No WebSocket URL in auth response")
                    return False
                # Create SSL context
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
                self.logger.info(f"Connecting to Upstox WebSocket: {ws_url}")
                self.websocket = await websockets.connect(
                    ws_url,
                    ssl=ssl_context,
                    ping_interval=None,
                    ping_timeout=None
                )
                self.logger.info("Connected to Upstox WebSocket")
                # Start message handler
                self.running = True
                self.ws_task = asyncio.create_task(self._message_handler())
                # Only call on_connect if it exists and is not None
                if self.callbacks.get("on_connect"):
                    await self.callbacks["on_connect"]()
                return True
            except Exception as e:
                attempt += 1
                self.logger.warning(f"WebSocket connection attempt {attempt} failed: {e}")
                if attempt >= self._max_reconnect_attempts:
                    self.logger.error("Max reconnect attempts reached. Giving up.")
                    if self.callbacks["on_error"]:
                        await self.callbacks["on_error"](str(e))
                    return False
                delay = min(self._reconnect_delay * (2 ** (attempt - 1)), 30)
                self.logger.info(f"Reconnecting in {delay} seconds...")
                await asyncio.sleep(delay)
        return False

    async def subscribe(self, instrument_keys: List[str], mode: str = "ltpc") -> bool:
        """
        Subscribe to market data for given instrument keys and mode.
        Args:
            instrument_keys (List[str]): List of instrument keys
            mode (str): Subscription mode (ltpc, full, etc.)
        Returns:
            bool: True if subscription request sent, False otherwise
        """
        try:
            if not self.websocket:
                self.logger.error("WebSocket not connected")
                return False
            message = {
                "guid": str(uuid.uuid4()).replace("-", "")[:20],
                "method": "sub",
                "data": {
                    "mode": mode,
                    "instrumentKeys": instrument_keys
                }
            }
            self._log_ws_message("OUT", message)
            # Always send as binary (Upstox V3 requirement)
            await self.websocket.send(json.dumps(message).encode('utf-8'))
            self._subscriptions.update(instrument_keys)
            self.logger.info(f"Subscribed to {instrument_keys} in mode {mode}")
            return True
        except Exception as e:
            self.logger.error(f"Subscribe error: {e}")
            if self.callbacks["on_error"]:
                await self.callbacks["on_error"](f"Subscribe error: {e}")
            return False

    async def unsubscribe(self, instrument_keys: List[str]) -> bool:
        """
        Unsubscribe from market data for given instrument keys.
        Args:
            instrument_keys (List[str]): List of instrument keys
        Returns:
            bool: True if unsubscribe request sent, False otherwise
        """
        try:
            if not self.websocket:
                self.logger.error("WebSocket not connected")
                return False
            message = {
                "guid": str(uuid.uuid4()).replace("-", "")[:20],
                "method": "unsub",
                "data": {
                    "instrumentKeys": instrument_keys
                }
            }
            self._log_ws_message("OUT", message)
            await self.websocket.send(json.dumps(message).encode('utf-8'))
            self._subscriptions.difference_update(instrument_keys)
            self.logger.info(f"Unsubscribed from {instrument_keys}")
            return True
        except Exception as e:
            self.logger.error(f"Unsubscribe error: {e}")
            if self.callbacks["on_error"]:
                await self.callbacks["on_error"](f"Unsubscribe error: {e}")
            return False

    def _decode_protobuf_to_dict(self, buffer: bytes) -> dict:
        """
        Decode protobuf FeedResponse to dict.
        Args:
            buffer (bytes): Protobuf-encoded message
        Returns:
            dict: Decoded message
        """
        feed_response = MarketDataFeedV3_pb2.FeedResponse()
        feed_response.ParseFromString(buffer)
        return MessageToDict(feed_response)

    async def _message_handler(self) -> None:
        """
        Handle incoming WebSocket messages.
        Incoming binary messages are decoded as protobuf; text messages are parsed as JSON.
        Calls on_message/on_error/on_close callbacks as appropriate.
        """
        try:
            while self.running and self.websocket:
                try:
                    message = await self.websocket.recv()
                    if isinstance(message, bytes):
                        self._log_binary_message("IN", message)
                        data = self._decode_protobuf_to_dict(message)
                        self.logger.debug(f"[CLIENT RAW DECODED] {json.dumps(data, indent=2)}")
                        if self.callbacks["on_message"]:
                            await self.callbacks["on_message"](data)
                    else:
                        try:
                            self._log_ws_message("IN", json.loads(message))
                            data = json.loads(message)
                            method = data.get("method")
                            status = data.get("status")
                            error = data.get("error")
                            if status == "failed" and error:
                                if self.callbacks["on_error"]:
                                    await self.callbacks["on_error"](f"{method.capitalize()} failed: {error}")
                        except Exception as e:
                            self.logger.error(f"Failed to parse text message: {e}")
                except websockets.exceptions.ConnectionClosed:
                    self.logger.info("WebSocket connection closed")
                    if self.callbacks["on_close"]:
                        await self.callbacks["on_close"]()
                    break
        except Exception as e:
            self.logger.error(f"Message handler error: {e}")
            if self.callbacks["on_error"]:
                await self.callbacks["on_error"](str(e))

    def _log_ws_message(self, direction: str, message: Dict[str, Any]) -> None:
        """Log WebSocket text message"""
        self.logger.debug(f"WebSocket {direction}: {json.dumps(message, indent=2)}")

    def _log_binary_message(self, direction: str, message: bytes) -> None:
        """Log WebSocket binary message"""
        hex_preview = ' '.join(f'{b:02x}' for b in message[:16])
        self.logger.debug(f"WebSocket {direction}: Binary message of length {len(message)}, first 16 bytes: {hex_preview}")

    async def disconnect(self) -> None:
        """
        Disconnect from WebSocket, cancel message handler, cleanup, and call on_close callback.
        """
        self.running = False
        if self.ws_task:
            self.ws_task.cancel()
            try:
                await self.ws_task
            except asyncio.CancelledError:
                pass
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
        self.logger.info("Disconnected from WebSocket")
        if self.callbacks["on_close"]:
            await self.callbacks["on_close"]()