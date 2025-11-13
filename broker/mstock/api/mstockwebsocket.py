import os
import json
import struct
import asyncio
import websockets
from typing import Dict, Optional
from utils.logging import get_logger

logger = get_logger(__name__)


class MstockWebSocket:
    """
    WebSocket client for mstock broker's market data API.
    Handles binary packet parsing as per mstock WebSocket protocol.
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
        self.api_key = os.getenv('BROKER_API_SECRET') or os.getenv('BROKER_API_KEY')
        self.ws_url = f"{self.WS_URL}?API_KEY={self.api_key}&ACCESS_TOKEN={self.auth_token}"
        logger.debug(f"WebSocket URL constructed (masked): wss://ws.mstock.trade?API_KEY=***&ACCESS_TOKEN=***")

    @staticmethod
    def parse_binary_packet(data: bytes) -> Optional[Dict]:
        """
        Parse mstock binary quote packet.
        The packet can be:
        - 379 bytes (just the quote packet without header)
        - 383+ bytes (4 byte header + 379 byte quote packet)

        Args:
            data: Binary data from WebSocket

        Returns:
            dict: Parsed quote data or None if parsing fails
        """
        try:
            # Check if data has the 4-byte header or is just the 379-byte packet
            if len(data) == 379:
                # Direct packet without header
                logger.debug(f"Parsing 379-byte packet (no header)")
                packet = data
            elif len(data) >= 383:
                # Parse header (4 bytes) + packet
                num_packets = struct.unpack('<H', data[0:2])[0]
                packet_size = struct.unpack('<H', data[2:4])[0]
                logger.debug(f"Header - Num packets: {num_packets}, Packet size: {packet_size}")
                # Parse quote packet starting from byte 4
                packet = data[4:4 + 379]
            else:
                logger.error(f"Invalid packet size: {len(data)} bytes (expected 379 or 383+)")
                return None

            # Parse quote structure based on mstock documentation
            quote = {
                'subscription_mode': packet[0],
                'exchange_type': packet[1],
                'token': packet[2:27].decode('utf-8').strip('\x00'),
                'sequence_number': struct.unpack('<Q', packet[27:35])[0],
                'exchange_timestamp': struct.unpack('<Q', packet[35:43])[0],
                'ltp': struct.unpack('<Q', packet[43:51])[0] / 100.0,
                'last_traded_qty': struct.unpack('<Q', packet[51:59])[0],
                'avg_price': struct.unpack('<Q', packet[59:67])[0] / 100.0,
                'volume': struct.unpack('<Q', packet[67:75])[0],
                'total_buy_qty': struct.unpack('<d', packet[75:83])[0],
                'total_sell_qty': struct.unpack('<d', packet[83:91])[0],
                'open': struct.unpack('<Q', packet[91:99])[0] / 100.0,
                'high': struct.unpack('<Q', packet[99:107])[0] / 100.0,
                'low': struct.unpack('<Q', packet[107:115])[0] / 100.0,
                'close': struct.unpack('<Q', packet[115:123])[0] / 100.0,
                'last_traded_timestamp': struct.unpack('<Q', packet[123:131])[0],
                'oi': struct.unpack('<Q', packet[131:139])[0],
                'oi_percent': struct.unpack('<Q', packet[139:147])[0] / 100.0,
                'upper_circuit': struct.unpack('<Q', packet[347:355])[0] / 100.0,
                'lower_circuit': struct.unpack('<Q', packet[355:363])[0] / 100.0,
                'week_52_high': struct.unpack('<Q', packet[363:371])[0] / 100.0,
                'week_52_low': struct.unpack('<Q', packet[371:379])[0] / 100.0,
            }

            # Parse market depth (bytes 147-347, 200 bytes total)
            depth_data = packet[147:347]
            quote['bids'] = []
            quote['asks'] = []

            # Parse 5 bid levels (each 20 bytes: 2+8+8+2)
            for i in range(5):
                bid_offset = i * 20
                try:
                    buy_sell_flag = struct.unpack('<H', depth_data[bid_offset:bid_offset + 2])[0]
                    qty = struct.unpack('<Q', depth_data[bid_offset + 2:bid_offset + 10])[0]
                    price = struct.unpack('<Q', depth_data[bid_offset + 10:bid_offset + 18])[0] / 100.0
                    num_orders = struct.unpack('<H', depth_data[bid_offset + 18:bid_offset + 20])[0]
                    quote['bids'].append({'price': price, 'quantity': qty, 'orders': num_orders})
                except Exception as e:
                    logger.debug(f"Error parsing bid level {i}: {str(e)}")
                    quote['bids'].append({'price': 0, 'quantity': 0, 'orders': 0})

            # Parse 5 ask levels (starting at byte 100 of depth data)
            for i in range(5):
                ask_offset = 100 + (i * 20)
                try:
                    buy_sell_flag = struct.unpack('<H', depth_data[ask_offset:ask_offset + 2])[0]
                    qty = struct.unpack('<Q', depth_data[ask_offset + 2:ask_offset + 10])[0]
                    price = struct.unpack('<Q', depth_data[ask_offset + 10:ask_offset + 18])[0] / 100.0
                    num_orders = struct.unpack('<H', depth_data[ask_offset + 18:ask_offset + 20])[0]
                    quote['asks'].append({'price': price, 'quantity': qty, 'orders': num_orders})
                except Exception as e:
                    logger.debug(f"Error parsing ask level {i}: {str(e)}")
                    quote['asks'].append({'price': 0, 'quantity': 0, 'orders': 0})

            return quote

        except Exception as e:
            logger.error(f"Error parsing binary packet: {str(e)}")
            return None

    async def fetch_quote_async(self, token: str, exchange_type: int, mode: int = 3) -> Optional[Dict]:
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
                    logger.debug(f"Login response received: {login_response if isinstance(login_response, str) else 'binary data'}")
                except asyncio.TimeoutError:
                    logger.warning("No login response received, proceeding with subscription")

                # Subscribe to token
                subscribe_msg = {
                    "action": 1,  # Subscribe
                    "params": {
                        "mode": mode,
                        "tokenList": [{
                            "exchangeType": exchange_type,
                            "tokens": [str(token)]
                        }]
                    }
                }
                await websocket.send(json.dumps(subscribe_msg))
                logger.debug(f"Subscribed to token {token} on exchange {exchange_type} with mode {mode}")

                # Wait for quote data (binary message)
                response = await asyncio.wait_for(websocket.recv(), timeout=5.0)

                if isinstance(response, bytes):
                    logger.debug(f"Received binary data of {len(response)} bytes")
                    quote = self.parse_binary_packet(response)
                    return quote
                else:
                    logger.error(f"Unexpected response type: {type(response)}, content: {response}")
                    return None

        except asyncio.TimeoutError:
            logger.error("Timeout waiting for quote data from WebSocket")
            return None
        except websockets.exceptions.InvalidStatusCode as e:
            logger.error(f"WebSocket connection rejected with status {e.status_code}: {str(e)}")
            logger.error(f"Check if API_KEY and ACCESS_TOKEN are valid")
            return None
        except Exception as e:
            logger.error(f"WebSocket error: {str(e)}")
            logger.error(f"Error type: {type(e).__name__}")
            return None

    def fetch_quote(self, token: str, exchange_type: int, mode: int = 3) -> Optional[Dict]:
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
