import asyncio
import json
import os
import struct
from typing import Dict, Optional

import websockets

from utils.logging import get_logger

logger = get_logger(__name__)


class MstockWebSocket:
    """
    WebSocket client for mstock broker's market data API.
    Handles binary packet parsing as per mstock WebSocket protocol.
    Supports both one-off fetches and persistent streaming connections.
    """

    WS_URL = "wss://ws.mstock.trade"

    def __init__(self, auth_token: str):
        """
        Initialize the mstock WebSocket client.

        Args:
            auth_token (str): JWT authentication token
        """
        self.auth_token = auth_token
        # Try BROKER_API_SECRET first (used in REST API), fallback to BROKER_API_KEY
        self.api_key = os.getenv("BROKER_API_SECRET") or os.getenv("BROKER_API_KEY")
        self.ws_url = f"{self.WS_URL}?API_KEY={self.api_key}&ACCESS_TOKEN={self.auth_token}"
        logger.debug(
            "WebSocket URL constructed (masked): wss://ws.mstock.trade?API_KEY=***&ACCESS_TOKEN=***"
        )

        # Streaming mode variables
        self.websocket = None
        self.running = False
        self.data_callback = None
        self.subscriptions = {}  # Track subscriptions: {correlation_id: {symbol, exchange, token, mode}}

    @staticmethod
    def parse_binary_packet(data: bytes) -> dict | None:
        """
        Parse mstock binary quote packet.
        The packet can be:
        - 51 bytes (LTP mode - mode 1)
        - 123 bytes (Quote mode - mode 2)
        - 379 bytes (Full quote packet - mode 3)
        - 383+ bytes (4 byte header + quote packet)

        Args:
            data: Binary data from WebSocket

        Returns:
            dict: Parsed quote data or None if parsing fails
        """
        try:
            # Handle LTP mode packet (51 bytes)
            if len(data) == 51:
                logger.debug("Parsing 51-byte LTP packet (mode 1)")
                # Parse LTP packet structure:
                # Byte 0: subscription mode
                # Byte 1: exchange type
                # Bytes 2-26: token (25 bytes)
                # Bytes 27-34: sequence number (8 bytes long)
                # Bytes 35-42: exchange timestamp (8 bytes long)
                # Bytes 43-50: LTP (8 bytes long)
                quote = {
                    "subscription_mode": data[0],
                    "exchange_type": data[1],
                    "token": data[2:27].decode("utf-8").strip("\x00"),
                    "sequence_number": struct.unpack("<Q", data[27:35])[0],
                    "exchange_timestamp": struct.unpack("<Q", data[35:43])[0],
                    "ltp": struct.unpack("<Q", data[43:51])[0] / 100.0,
                    # Set defaults for other fields not in LTP mode
                    "last_traded_qty": 0,
                    "avg_price": 0,
                    "volume": 0,
                    "total_buy_qty": 0,
                    "total_sell_qty": 0,
                    "open": 0,
                    "high": 0,
                    "low": 0,
                    "close": 0,
                    "last_traded_timestamp": 0,
                    "oi": 0,
                    "oi_percent": 0,
                    "upper_circuit": 0,
                    "lower_circuit": 0,
                    "week_52_high": 0,
                    "week_52_low": 0,
                    "bids": [],
                    "asks": [],
                }
                return quote

            # Handle Quote mode packet (123 bytes)
            elif len(data) == 123:
                logger.debug("Parsing 123-byte Quote packet (mode 2)")
                # Parse Quote packet structure (mode 2):
                # Byte 0: subscription mode
                # Byte 1: exchange type
                # Bytes 2-26: token (25 bytes)
                # Bytes 27-34: sequence number (8 bytes long)
                # Bytes 35-42: exchange timestamp (8 bytes long)
                # Bytes 43-50: LTP (8 bytes long)
                # Bytes 51-58: last traded qty (8 bytes long)
                # Bytes 59-66: avg price (8 bytes long)
                # Bytes 67-74: volume (8 bytes long)
                # Bytes 75-82: total buy qty (8 bytes double)
                # Bytes 83-90: total sell qty (8 bytes double)
                # Bytes 91-98: open (8 bytes long)
                # Bytes 99-106: high (8 bytes long)
                # Bytes 107-114: low (8 bytes long)
                # Bytes 115-122: close (8 bytes long)
                quote = {
                    "subscription_mode": data[0],
                    "exchange_type": data[1],
                    "token": data[2:27].decode("utf-8").strip("\x00"),
                    "sequence_number": struct.unpack("<Q", data[27:35])[0],
                    "exchange_timestamp": struct.unpack("<Q", data[35:43])[0],
                    "ltp": struct.unpack("<Q", data[43:51])[0] / 100.0,
                    "last_traded_qty": struct.unpack("<Q", data[51:59])[0],
                    "avg_price": struct.unpack("<Q", data[59:67])[0] / 100.0,
                    "volume": struct.unpack("<Q", data[67:75])[0],
                    "total_buy_qty": struct.unpack("<d", data[75:83])[0],
                    "total_sell_qty": struct.unpack("<d", data[83:91])[0],
                    "open": struct.unpack("<Q", data[91:99])[0] / 100.0,
                    "high": struct.unpack("<Q", data[99:107])[0] / 100.0,
                    "low": struct.unpack("<Q", data[107:115])[0] / 100.0,
                    "close": struct.unpack("<Q", data[115:123])[0] / 100.0,
                    # Set defaults for fields not in Quote mode
                    "last_traded_timestamp": 0,
                    "oi": 0,
                    "oi_percent": 0,
                    "upper_circuit": 0,
                    "lower_circuit": 0,
                    "week_52_high": 0,
                    "week_52_low": 0,
                    "bids": [],
                    "asks": [],
                }
                return quote

            # Check if data has the 4-byte header or is just the 379-byte packet
            elif len(data) == 379:
                # Direct packet without header
                logger.debug("Parsing 379-byte packet (no header)")
                packet = data
            elif len(data) >= 383:
                # Parse header (4 bytes) + packet
                num_packets = struct.unpack("<H", data[0:2])[0]
                packet_size = struct.unpack("<H", data[2:4])[0]
                logger.debug(f"Header - Num packets: {num_packets}, Packet size: {packet_size}")
                # Parse quote packet starting from byte 4
                packet = data[4 : 4 + 379]
            else:
                logger.error(
                    f"Invalid packet size: {len(data)} bytes (expected 51, 123, 379 or 383+)"
                )
                return None

            # Parse quote structure based on mstock documentation
            quote = {
                "subscription_mode": packet[0],
                "exchange_type": packet[1],
                "token": packet[2:27].decode("utf-8").strip("\x00"),
                "sequence_number": struct.unpack("<Q", packet[27:35])[0],
                "exchange_timestamp": struct.unpack("<Q", packet[35:43])[0],
                "ltp": struct.unpack("<Q", packet[43:51])[0] / 100.0,
                "last_traded_qty": struct.unpack("<Q", packet[51:59])[0],
                "avg_price": struct.unpack("<Q", packet[59:67])[0] / 100.0,
                "volume": struct.unpack("<Q", packet[67:75])[0],
                "total_buy_qty": struct.unpack("<d", packet[75:83])[0],
                "total_sell_qty": struct.unpack("<d", packet[83:91])[0],
                "open": struct.unpack("<Q", packet[91:99])[0] / 100.0,
                "high": struct.unpack("<Q", packet[99:107])[0] / 100.0,
                "low": struct.unpack("<Q", packet[107:115])[0] / 100.0,
                "close": struct.unpack("<Q", packet[115:123])[0] / 100.0,
                "last_traded_timestamp": struct.unpack("<Q", packet[123:131])[0],
                "oi": struct.unpack("<Q", packet[131:139])[0],
                "oi_percent": struct.unpack("<Q", packet[139:147])[0] / 100.0,
                "upper_circuit": struct.unpack("<Q", packet[347:355])[0] / 100.0,
                "lower_circuit": struct.unpack("<Q", packet[355:363])[0] / 100.0,
                "week_52_high": struct.unpack("<Q", packet[363:371])[0] / 100.0,
                "week_52_low": struct.unpack("<Q", packet[371:379])[0] / 100.0,
            }

            # Parse market depth (bytes 147-347, 200 bytes total)
            depth_data = packet[147:347]
            quote["bids"] = []
            quote["asks"] = []

            # Parse 5 bid levels (each 20 bytes: 2+8+8+2)
            for i in range(5):
                bid_offset = i * 20
                try:
                    buy_sell_flag = struct.unpack("<H", depth_data[bid_offset : bid_offset + 2])[0]
                    qty = struct.unpack("<Q", depth_data[bid_offset + 2 : bid_offset + 10])[0]
                    price = (
                        struct.unpack("<Q", depth_data[bid_offset + 10 : bid_offset + 18])[0]
                        / 100.0
                    )
                    num_orders = struct.unpack("<H", depth_data[bid_offset + 18 : bid_offset + 20])[
                        0
                    ]
                    quote["bids"].append({"price": price, "quantity": qty, "orders": num_orders})
                except Exception as e:
                    logger.debug(f"Error parsing bid level {i}: {str(e)}")
                    quote["bids"].append({"price": 0, "quantity": 0, "orders": 0})

            # Parse 5 ask levels (starting at byte 100 of depth data)
            for i in range(5):
                ask_offset = 100 + (i * 20)
                try:
                    buy_sell_flag = struct.unpack("<H", depth_data[ask_offset : ask_offset + 2])[0]
                    qty = struct.unpack("<Q", depth_data[ask_offset + 2 : ask_offset + 10])[0]
                    price = (
                        struct.unpack("<Q", depth_data[ask_offset + 10 : ask_offset + 18])[0]
                        / 100.0
                    )
                    num_orders = struct.unpack("<H", depth_data[ask_offset + 18 : ask_offset + 20])[
                        0
                    ]
                    quote["asks"].append({"price": price, "quantity": qty, "orders": num_orders})
                except Exception as e:
                    logger.debug(f"Error parsing ask level {i}: {str(e)}")
                    quote["asks"].append({"price": 0, "quantity": 0, "orders": 0})

            return quote

        except Exception as e:
            logger.error(f"Error parsing binary packet: {str(e)}")
            return None

    async def fetch_quote_async(self, token: str, exchange_type: int, mode: int = 3) -> dict | None:
        """
        Fetch quote data from mstock WebSocket asynchronously.

        Args:
            token: Symbol token
            exchange_type: 1=NSECM, 2=NSEFO, 3=BSECM, 4=BSEFO, 13=NSECD
            mode: 1=LTP, 2=Quote, 3=Snap Quote (default)

        Returns:
            dict: Parsed quote data or None
        """
        try:
            logger.debug(f"Attempting WebSocket connection to: {self.ws_url[:50]}...")
            async with websockets.connect(self.ws_url, ping_interval=None) as websocket:
                logger.debug("WebSocket connection established successfully")

                # Send LOGIN message
                login_msg = f"LOGIN:{self.auth_token}"
                await websocket.send(login_msg)
                logger.debug("Sent LOGIN message to mstock WebSocket")

                # Wait for login response
                try:
                    login_response = await asyncio.wait_for(websocket.recv(), timeout=3.0)
                    logger.debug(
                        f"Login response received: {login_response if isinstance(login_response, str) else 'binary data'}"
                    )
                except TimeoutError:
                    logger.warning("No login response received, proceeding with subscription")

                # Subscribe to token
                subscribe_msg = {
                    "action": 1,  # Subscribe
                    "params": {
                        "mode": mode,
                        "tokenList": [{"exchangeType": exchange_type, "tokens": [str(token)]}],
                    },
                }
                await websocket.send(json.dumps(subscribe_msg))
                logger.debug(
                    f"Subscribed to token {token} on exchange {exchange_type} with mode {mode}"
                )

                # Wait for responses - may get acknowledgment first, then quote data
                max_attempts = 2  # Reduced from 3
                for attempt in range(max_attempts):
                    try:
                        response = await asyncio.wait_for(
                            websocket.recv(), timeout=2.0
                        )  # Reduced from 5.0

                        if isinstance(response, bytes):
                            logger.debug(f"Received binary data of {len(response)} bytes")

                            # Check if this is a quote packet (51, 123, 379, or 383+ bytes)
                            if (
                                len(response) == 51
                                or len(response) == 123
                                or len(response) == 379
                                or len(response) >= 383
                            ):
                                quote = self.parse_binary_packet(response)
                                if quote:
                                    return quote
                                else:
                                    logger.warning(
                                        "Failed to parse binary packet, waiting for next message..."
                                    )
                            else:
                                logger.debug(
                                    f"Received non-quote binary data ({len(response)} bytes), waiting for quote data..."
                                )
                        elif isinstance(response, str):
                            # String response - likely JSON acknowledgment
                            logger.debug(f"Received string response: {response}")
                            try:
                                response_data = json.loads(response)
                                logger.debug(f"Parsed JSON response: {response_data}")
                            except:
                                logger.debug(f"Non-JSON string response: {response}")
                            # Continue to wait for binary quote data
                        else:
                            logger.warning(f"Unexpected response type: {type(response)}")

                    except TimeoutError:
                        logger.debug(
                            f"Timeout waiting for response (attempt {attempt + 1}/{max_attempts})"
                        )
                        if attempt == max_attempts - 1:
                            logger.info(
                                "No quote data received (market may be closed or symbol unavailable)"
                            )
                            return None

                # If we get here, we didn't receive valid quote data
                logger.debug("No valid quote data received after all attempts")
                return None

        except TimeoutError:
            logger.error("Timeout waiting for quote data from WebSocket")
            return None
        except websockets.exceptions.InvalidStatusCode as e:
            logger.error(f"WebSocket connection rejected with status {e.status_code}: {str(e)}")
            logger.error("Check if API_KEY and ACCESS_TOKEN are valid")
            return None
        except Exception as e:
            logger.error(f"WebSocket error: {str(e)}")
            logger.error(f"Error type: {type(e).__name__}")
            return None

    def fetch_quote(self, token: str, exchange_type: int, mode: int = 3) -> dict | None:
        """
        Synchronous wrapper for fetching mstock quote.

        Args:
            token: Symbol token
            exchange_type: Exchange type code
            mode: Quote mode (1=LTP, 2=Quote, 3=Snap Quote)

        Returns:
            dict: Parsed quote data
        """
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(self.fetch_quote_async(token, exchange_type, mode))

    # ==================== Streaming Mode Methods ====================

    async def connect_stream_async(self, data_callback):
        """
        Establish persistent WebSocket connection for streaming data.

        Args:
            data_callback: Callback function(quote_data) called when data is received
        """
        self.data_callback = data_callback
        self.running = True

        try:
            logger.info("Connecting to mstock WebSocket in streaming mode...")
            async with websockets.connect(
                self.ws_url, ping_interval=20, ping_timeout=10
            ) as websocket:
                self.websocket = websocket
                logger.info("WebSocket connection established in streaming mode")

                # Send LOGIN message
                login_msg = f"LOGIN:{self.auth_token}"
                await websocket.send(login_msg)
                logger.debug("Sent LOGIN message")

                # Wait for login response (or timeout)
                try:
                    login_response = await asyncio.wait_for(websocket.recv(), timeout=3.0)
                    logger.debug(
                        f"Login response: {login_response if isinstance(login_response, str) else 'binary'}"
                    )
                except TimeoutError:
                    logger.debug("No login response, proceeding...")

                # Start receiving messages
                while self.running:
                    try:
                        # Use timeout to make shutdown more responsive
                        message = await asyncio.wait_for(websocket.recv(), timeout=5.0)

                        if isinstance(message, bytes):
                            # Parse binary packet
                            if len(message) in [51, 123, 379] or len(message) >= 383:
                                quote_data = self.parse_binary_packet(message)
                                if quote_data and self.data_callback:
                                    # Call the callback with parsed data
                                    self.data_callback(quote_data)
                        elif isinstance(message, str):
                            # JSON response (acknowledgment, etc.)
                            logger.debug(f"Received string message: {message}")

                    except TimeoutError:
                        # Check running flag on timeout to allow responsive shutdown
                        continue
                    except websockets.exceptions.ConnectionClosed:
                        logger.warning("WebSocket connection closed")
                        break

        except Exception as e:
            logger.error(f"Streaming WebSocket error: {str(e)}")
        finally:
            self.running = False
            self.websocket = None
            logger.info("Streaming WebSocket disconnected")

    def connect_stream(self, data_callback):
        """
        Synchronous wrapper for connecting in streaming mode.

        Args:
            data_callback: Callback function(quote_data) called when data is received
        """
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(self.connect_stream_async(data_callback))

    async def subscribe_stream_async(
        self, correlation_id: str, token: str, exchange_type: int, mode: int
    ):
        """
        Subscribe to a symbol on the persistent WebSocket connection.

        Args:
            correlation_id: Unique ID for this subscription
            token: Symbol token
            exchange_type: Exchange type code
            mode: Subscription mode
        """
        if not self.websocket or not self.running:
            logger.error("WebSocket not connected. Call connect_stream() first.")
            return False

        try:
            subscribe_msg = {
                "action": 1,  # Subscribe
                "params": {
                    "mode": mode,
                    "tokenList": [{"exchangeType": exchange_type, "tokens": [str(token)]}],
                },
            }

            await self.websocket.send(json.dumps(subscribe_msg))
            logger.info(f"Subscribed to token {token} on exchange {exchange_type} with mode {mode}")

            # Store subscription
            self.subscriptions[correlation_id] = {
                "token": token,
                "exchange_type": exchange_type,
                "mode": mode,
            }

            return True

        except Exception as e:
            logger.error(f"Error subscribing: {str(e)}")
            return False

    async def unsubscribe_stream_async(self, correlation_id: str):
        """
        Unsubscribe from a symbol on the persistent WebSocket connection.

        Args:
            correlation_id: Unique ID of the subscription to remove
        """
        if not self.websocket or not self.running:
            return False

        try:
            if correlation_id not in self.subscriptions:
                return False

            sub = self.subscriptions[correlation_id]

            unsubscribe_msg = {
                "action": 0,  # Unsubscribe
                "params": {
                    "mode": sub["mode"],
                    "tokenList": [
                        {"exchangeType": sub["exchange_type"], "tokens": [str(sub["token"])]}
                    ],
                },
            }

            await self.websocket.send(json.dumps(unsubscribe_msg))
            logger.info(f"Unsubscribed from token {sub['token']}")

            # Remove subscription
            del self.subscriptions[correlation_id]

            return True

        except Exception as e:
            logger.error(f"Error unsubscribing: {str(e)}")
            return False

    def disconnect_stream(self):
        """Disconnect the persistent WebSocket connection"""
        self.running = False
        # Don't try to close websocket from different thread/event loop
        # Setting running=False will cause the streaming loop to exit cleanly
        logger.info("Streaming mode disconnected")
