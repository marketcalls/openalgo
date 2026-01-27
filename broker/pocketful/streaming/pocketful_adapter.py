import json
import logging
import os
import struct
import sys
import threading
import time
from typing import Any, Dict, List, Optional

import websocket

from database.auth_db import get_auth_token
from database.token_db import get_token

# Add parent directory to path to allow imports
sys.path.append(os.path.join(os.path.dirname(__file__), "../../../"))

from broker.pocketful.api.packet_decoder import (
    decodeCompactMarketData,
    decodeDetailedMarketData,
    decodeSnapquoteData,
)
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper

from .pocketful_mapping import PocketfulCapabilityRegistry, PocketfulExchangeMapper


class PocketfulWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Pocketful-specific implementation of the WebSocket adapter"""

    BASE_URL = "wss://trade.pocketful.in"

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("pocketful_websocket")
        self.ws_client = None
        self.user_id = None
        self.broker_name = "pocketful"
        self.access_token = None
        self.reconnect_delay = 5  # Initial delay in seconds
        self.max_reconnect_delay = 60  # Maximum delay in seconds
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.running = False
        self.lock = threading.Lock()
        self.heartbeat_thread = None

    def initialize(
        self, broker_name: str, user_id: str, auth_data: dict[str, str] | None = None
    ) -> None:
        """
        Initialize connection with Pocketful WebSocket API

        Args:
            broker_name: Name of the broker (always 'pocketful' in this case)
            user_id: Client ID/user ID
            auth_data: If provided, use these credentials instead of fetching from DB

        Raises:
            ValueError: If required authentication tokens are not found
        """
        self.user_id = user_id
        self.broker_name = broker_name

        # Get tokens from database if not provided
        if not auth_data:
            # Fetch authentication tokens from database
            auth_token = get_auth_token(user_id)

            if not auth_token:
                self.logger.error(f"No authentication token found for user {user_id}")
                raise ValueError(f"No authentication token found for user {user_id}")

            self.access_token = auth_token
        else:
            # Use provided tokens
            self.access_token = auth_data.get("auth_token") or auth_data.get("access_token")

            if not self.access_token:
                self.logger.error("Missing required authentication data")
                raise ValueError("Missing required authentication data")

        self.running = True
        self.logger.info(f"Pocketful WebSocket adapter initialized for user {user_id}")

    def connect(self) -> None:
        """Establish connection to Pocketful WebSocket"""
        if not self.access_token:
            self.logger.error("WebSocket client not initialized. Call initialize() first.")
            return

        threading.Thread(target=self._connect_with_retry, daemon=True).start()

    def _connect_with_retry(self) -> None:
        """Connect to Pocketful WebSocket with retry logic"""
        while self.running and self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                self.logger.info(
                    f"Connecting to Pocketful WebSocket (attempt {self.reconnect_attempts + 1})"
                )

                # Build WebSocket URL
                ws_url = f"{self.BASE_URL}/ws/v1/feeds?login_id={self.user_id}&access_token={self.access_token}"

                # Create WebSocket connection
                self.ws_client = websocket.WebSocketApp(
                    ws_url,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                    on_open=self._on_open,
                )

                # Run WebSocket connection
                self.ws_client.run_forever()

                # If we get here, the connection was closed
                if not self.running:
                    break

                self.reconnect_attempts += 1
                delay = min(
                    self.reconnect_delay * (2**self.reconnect_attempts), self.max_reconnect_delay
                )
                self.logger.warning(f"Connection lost. Retrying in {delay} seconds...")
                time.sleep(delay)

            except Exception as e:
                self.reconnect_attempts += 1
                delay = min(
                    self.reconnect_delay * (2**self.reconnect_attempts), self.max_reconnect_delay
                )
                self.logger.error(f"Connection failed: {e}. Retrying in {delay} seconds...")
                time.sleep(delay)

        if self.reconnect_attempts >= self.max_reconnect_attempts:
            self.logger.error("Max reconnection attempts reached. Giving up.")

    def disconnect(self) -> None:
        """Disconnect from Pocketful WebSocket"""
        self.running = False
        if hasattr(self, "ws_client") and self.ws_client:
            self.ws_client.close()

        # Clean up ZeroMQ resources
        self.cleanup_zmq()

    def subscribe(
        self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5
    ) -> dict[str, Any]:
        """
        Subscribe to market data with Pocketful-specific implementation

        Args:
            symbol: Trading symbol (e.g., 'RELIANCE')
            exchange: Exchange code (e.g., 'NSE', 'BSE', 'NFO')
            mode: Subscription mode - 1:LTP, 2:Quote, 3:Snap Quote (Depth)
            depth_level: Market depth level (5)

        Returns:
            Dict: Response with status and error message if applicable
        """
        # Map OpenAlgo mode to Pocketful mode
        # OpenAlgo: 1=LTP, 2=Quote, 3=Depth
        # Pocketful: 1=Detailed, 2=Compact, 4=Snapquote
        pocketful_mode_map = {
            1: 2,  # LTP -> Compact
            2: 1,  # Quote -> Detailed
            3: 4,  # Depth -> Snapquote
        }
        pocketful_mode = pocketful_mode_map.get(mode, 2)

        # Validate mode
        if mode not in [1, 2, 3]:
            return self._create_error_response(
                "INVALID_MODE", f"Invalid mode {mode}. Must be 1 (LTP), 2 (Quote), or 3 (Depth)"
            )

        # If depth mode, check if supported depth level
        if mode == 3 and depth_level not in [5]:
            return self._create_error_response(
                "INVALID_DEPTH", f"Invalid depth level {depth_level}. Must be 5"
            )

        # Map symbol to token using symbol mapper
        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if not token_info:
            return self._create_error_response(
                "SYMBOL_NOT_FOUND", f"Symbol {symbol} not found for exchange {exchange}"
            )

        token = token_info["token"]
        brexchange = token_info["brexchange"]

        # Check if the requested depth level is supported for this exchange
        is_fallback = False
        actual_depth = depth_level

        if mode == 3:  # Depth mode
            if not PocketfulCapabilityRegistry.is_depth_level_supported(exchange, depth_level):
                actual_depth = PocketfulCapabilityRegistry.get_fallback_depth_level(
                    exchange, depth_level
                )
                is_fallback = True
                self.logger.info(
                    f"Depth level {depth_level} not supported for {exchange}, using {actual_depth} instead"
                )

        # Get exchange code for Pocketful
        exchange_code = PocketfulExchangeMapper.get_exchange_code(brexchange)

        # Generate unique correlation ID
        correlation_id = f"{symbol}_{exchange}_{mode}"
        if mode == 3:
            correlation_id = f"{correlation_id}_{depth_level}"

        # Store subscription for reconnection
        with self.lock:
            self.subscriptions[correlation_id] = {
                "symbol": symbol,
                "exchange": exchange,
                "brexchange": brexchange,
                "token": token,
                "mode": mode,
                "pocketful_mode": pocketful_mode,
                "exchange_code": exchange_code,
                "depth_level": depth_level,
                "actual_depth": actual_depth,
                "is_fallback": is_fallback,
            }

        # Subscribe if connected
        if self.connected and self.ws_client:
            try:
                self._send_subscription(exchange_code, token, pocketful_mode)
            except Exception as e:
                self.logger.error(f"Error subscribing to {symbol}.{exchange}: {e}")
                return self._create_error_response("SUBSCRIPTION_ERROR", str(e))

        # Return success with capability info
        return self._create_success_response(
            "Subscription requested"
            if not is_fallback
            else f"Using depth level {actual_depth} instead of requested {depth_level}",
            symbol=symbol,
            exchange=exchange,
            mode=mode,
            requested_depth=depth_level,
            actual_depth=actual_depth,
            is_fallback=is_fallback,
        )

    def unsubscribe(self, symbol: str, exchange: str, mode: int = 2) -> dict[str, Any]:
        """
        Unsubscribe from market data

        Args:
            symbol: Trading symbol
            exchange: Exchange code
            mode: Subscription mode

        Returns:
            Dict: Response with status
        """
        # Map symbol to token
        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if not token_info:
            return self._create_error_response(
                "SYMBOL_NOT_FOUND", f"Symbol {symbol} not found for exchange {exchange}"
            )

        token = token_info["token"]
        brexchange = token_info["brexchange"]
        exchange_code = PocketfulExchangeMapper.get_exchange_code(brexchange)

        # Map mode
        pocketful_mode_map = {1: 2, 2: 1, 3: 4}
        pocketful_mode = pocketful_mode_map.get(mode, 2)

        # Generate correlation ID
        correlation_id = f"{symbol}_{exchange}_{mode}"

        # Remove from subscriptions
        with self.lock:
            if correlation_id in self.subscriptions:
                del self.subscriptions[correlation_id]

        # Unsubscribe if connected
        if self.connected and self.ws_client:
            try:
                self._send_unsubscription(exchange_code, token, pocketful_mode)
            except Exception as e:
                self.logger.error(f"Error unsubscribing from {symbol}.{exchange}: {e}")
                return self._create_error_response("UNSUBSCRIPTION_ERROR", str(e))

        return self._create_success_response(
            f"Unsubscribed from {symbol}.{exchange}", symbol=symbol, exchange=exchange, mode=mode
        )

    def _send_subscription(self, exchange_code: int, token: str, mode: int) -> None:
        """Send subscription packet to Pocketful WebSocket"""
        subscription_pkt = [[exchange_code, int(token)]]

        # Determine market data type based on mode
        if mode == 1:
            market_type = "marketdata"
        elif mode == 2:
            market_type = "compact_marketdata"
        else:  # mode == 4
            market_type = "full_snapquote"

        sub_packet = {"a": "subscribe", "v": subscription_pkt, "m": market_type}
        self.ws_client.send(json.dumps(sub_packet))
        self.logger.info(f"Sent subscription: {sub_packet}")

    def _send_unsubscription(self, exchange_code: int, token: str, mode: int) -> None:
        """Send unsubscription packet to Pocketful WebSocket"""
        unsubscription_pkt = [[exchange_code, int(token)]]

        # Determine market data type based on mode
        if mode == 1:
            market_type = "marketdata"
        elif mode == 2:
            market_type = "compact_marketdata"
        else:  # mode == 4
            market_type = "full_snapquote"

        unsub_packet = {"a": "unsubscribe", "v": unsubscription_pkt, "m": market_type}
        self.ws_client.send(json.dumps(unsub_packet))
        self.logger.info(f"Sent unsubscription: {unsub_packet}")

    def _on_open(self, ws) -> None:
        """Callback when connection is established"""
        self.logger.info("Connected to Pocketful WebSocket")
        self.connected = True
        self.reconnect_attempts = 0

        # Start heartbeat thread
        self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self.heartbeat_thread.start()

        # Resubscribe to existing subscriptions if reconnecting
        with self.lock:
            for correlation_id, sub in self.subscriptions.items():
                try:
                    self._send_subscription(
                        sub["exchange_code"], sub["token"], sub["pocketful_mode"]
                    )
                    self.logger.info(f"Resubscribed to {sub['symbol']}.{sub['exchange']}")
                except Exception as e:
                    self.logger.error(
                        f"Error resubscribing to {sub['symbol']}.{sub['exchange']}: {e}"
                    )

    def _on_error(self, ws, error) -> None:
        """Callback for WebSocket errors"""
        self.logger.error(f"Pocketful WebSocket error: {error}")

    def _on_close(self, ws, close_status_code=None, close_msg=None) -> None:
        """Callback when connection is closed"""
        self.logger.info(
            f"Pocketful WebSocket connection closed: code={close_status_code}, message={close_msg}"
        )
        self.connected = False

    def _on_message(self, ws, message) -> None:
        """Callback for messages from the WebSocket"""
        try:
            # Try to parse as JSON first
            try:
                data = json.loads(message)
                if isinstance(data, dict) and "mode" in data:
                    mode = data["mode"]
                else:
                    # If no mode in JSON, try binary parsing
                    mode = struct.unpack(">b", message[0:1])[0]
            except:
                # If JSON parsing fails, assume binary
                mode = struct.unpack(">b", message[0:1])[0]

            # Process based on message mode
            if mode == 1:  # Detailed market data
                self._handle_detailed_data(message)
            elif mode == 2:  # Compact market data
                self._handle_compact_data(message)
            elif mode == 4:  # Snapquote data
                self._handle_snapquote_data(message)

        except Exception as e:
            self.logger.error(f"Error processing WebSocket message: {str(e)}")

    def _handle_detailed_data(self, message) -> None:
        """Handle detailed market data (mode 1)"""
        try:
            res = decodeDetailedMarketData(message)
            if not res:
                return

            token = str(res.get("instrument_token"))
            exchange_code = res.get("exchange_code")

            # Find matching subscription
            subscription = self._find_subscription(token, exchange_code)
            if not subscription:
                return

            symbol = subscription["symbol"]
            exchange = subscription["exchange"]
            mode = subscription["mode"]

            # Create topic for ZeroMQ
            mode_str = {1: "LTP", 2: "QUOTE", 3: "DEPTH"}[mode]
            topic = f"{exchange}_{symbol}_{mode_str}"

            # Normalize data
            market_data = {
                "ltp": res.get("last_traded_price", 0) / 100,
                "ltt": res.get("last_traded_time", 0),
                "volume": res.get("trade_volume", 0),
                "open": res.get("open_price", 0) / 100,
                "high": res.get("high_price", 0) / 100,
                "low": res.get("low_price", 0) / 100,
                "close": res.get("close_price", 0) / 100,
                "last_trade_quantity": res.get("last_traded_quantity", 0),
                "average_price": res.get("average_trade_price", 0) / 100,
                "total_buy_quantity": res.get("total_buy_quantity", 0),
                "total_sell_quantity": res.get("total_sell_quantity", 0),
                "oi": res.get("currentOpenInterest", 0),
                "symbol": symbol,
                "exchange": exchange,
                "mode": mode,
                "timestamp": int(time.time() * 1000),
            }

            # Publish to ZeroMQ
            self.publish_market_data(topic, market_data)

        except Exception as e:
            self.logger.error(f"Error handling detailed data: {e}")

    def _handle_compact_data(self, message) -> None:
        """Handle compact market data (mode 2)"""
        try:
            res = decodeCompactMarketData(message)
            if not res:
                return

            token = str(res.get("instrument_token"))
            exchange_code = res.get("exchange_code")

            # Find matching subscription
            subscription = self._find_subscription(token, exchange_code)
            if not subscription:
                return

            symbol = subscription["symbol"]
            exchange = subscription["exchange"]
            mode = subscription["mode"]

            # Create topic for ZeroMQ
            mode_str = {1: "LTP", 2: "QUOTE", 3: "DEPTH"}[mode]
            topic = f"{exchange}_{symbol}_{mode_str}"

            # Normalize data
            market_data = {
                "ltp": res.get("last_traded_price", 0) / 100,
                "ltt": res.get("last_traded_time", 0),
                "change": res.get("change", 0) / 100,
                "oi": res.get("currentOpenInterest", 0),
                "bid_price": res.get("bidPrice", 0) / 100,
                "ask_price": res.get("askPrice", 0) / 100,
                "symbol": symbol,
                "exchange": exchange,
                "mode": mode,
                "timestamp": int(time.time() * 1000),
            }

            # Publish to ZeroMQ
            self.publish_market_data(topic, market_data)

        except Exception as e:
            self.logger.error(f"Error handling compact data: {e}")

    def _handle_snapquote_data(self, message) -> None:
        """Handle snapquote data (mode 4) - includes depth"""
        try:
            res = decodeSnapquoteData(message)
            if not res:
                return

            token = str(res.get("instrument_token"))
            exchange_code = res.get("exchange_code")

            # Find matching subscription
            subscription = self._find_subscription(token, exchange_code)
            if not subscription:
                return

            symbol = subscription["symbol"]
            exchange = subscription["exchange"]
            mode = subscription["mode"]

            # Create topic for ZeroMQ
            mode_str = {1: "LTP", 2: "QUOTE", 3: "DEPTH"}[mode]
            topic = f"{exchange}_{symbol}_{mode_str}"

            # Normalize data
            market_data = {
                "ltp": res.get("averageTradePrice", 0) / 100,
                "open": res.get("open", 0) / 100,
                "high": res.get("high", 0) / 100,
                "low": res.get("low", 0) / 100,
                "close": res.get("close", 0) / 100,
                "volume": res.get("volume", 0),
                "total_buy_quantity": res.get("totalBuyQty", 0),
                "total_sell_quantity": res.get("totalSellQty", 0),
                "symbol": symbol,
                "exchange": exchange,
                "mode": mode,
                "timestamp": int(time.time() * 1000),
            }

            # Add depth data
            if "bidPrices" in res and "askPrices" in res:
                market_data["depth"] = {
                    "buy": self._extract_depth_buy(res),
                    "sell": self._extract_depth_sell(res),
                }

            # Publish to ZeroMQ
            self.publish_market_data(topic, market_data)

        except Exception as e:
            self.logger.error(f"Error handling snapquote data: {e}")

    def _extract_depth_buy(self, data: dict) -> list[dict[str, Any]]:
        """Extract buy side depth data from Pocketful snapquote"""
        depth = []
        bid_prices = data.get("bidPrices", [])
        bid_qtys = data.get("bidQtys", [])
        buyers = data.get("buyers", [])

        for i in range(min(5, len(bid_prices))):
            depth.append(
                {
                    "price": bid_prices[i] / 100 if i < len(bid_prices) else 0,
                    "quantity": bid_qtys[i] if i < len(bid_qtys) else 0,
                    "orders": buyers[i] if i < len(buyers) else 0,
                }
            )

        return depth

    def _extract_depth_sell(self, data: dict) -> list[dict[str, Any]]:
        """Extract sell side depth data from Pocketful snapquote"""
        depth = []
        ask_prices = data.get("askPrices", [])
        ask_qtys = data.get("askQtys", [])
        sellers = data.get("sellers", [])

        for i in range(min(5, len(ask_prices))):
            depth.append(
                {
                    "price": ask_prices[i] / 100 if i < len(ask_prices) else 0,
                    "quantity": ask_qtys[i] if i < len(ask_qtys) else 0,
                    "orders": sellers[i] if i < len(sellers) else 0,
                }
            )

        return depth

    def _find_subscription(self, token: str, exchange_code: int) -> dict | None:
        """Find a subscription matching the token and exchange code"""
        with self.lock:
            for sub in self.subscriptions.values():
                if str(sub["token"]) == str(token) and sub["exchange_code"] == exchange_code:
                    return sub
        return None

    def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats to keep connection alive"""
        while self.running and self.connected:
            try:
                if self.ws_client and self.connected:
                    self.ws_client.send(json.dumps({"a": "h"}))
                    self.logger.debug("Heartbeat sent")
            except Exception as e:
                self.logger.error(f"Error sending heartbeat: {e}")
            time.sleep(15)  # Send heartbeat every 15 seconds
