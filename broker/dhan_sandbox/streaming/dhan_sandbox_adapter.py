import json
import logging
import random
import threading
import time
import re
import hashlib
from typing import Any, Dict

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter

logger = logging.getLogger("dhan_sandbox_websocket")


class Dhan_sandboxWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """
    Mock WebSocket adapter for Dhan Sandbox.
    Since Dhan Sandbox does not provide a real WebSocket endpoint, 
    this adapter simulates real-time market data by generating 
    synthetic but contract-driven ticks for subscribed symbols.
    """

    def __init__(self):
        super().__init__()
        self.broker_name = "dhan_sandbox"
        self.user_id = None
        self.running = False
        self._mock_thread = None
        self.lock = threading.Lock()
        
        # State to keep track of current mock LTP for each symbol
        # so it fluctuates naturally instead of jumping wildly
        self._current_prices = {}
        self._spot_hint_cache: dict[str, float] = {}

    def _stable_noise(self, seed_key: str, low: float, high: float) -> float:
        """Deterministic pseudo-random value in [low, high]."""
        digest = hashlib.sha256(seed_key.encode("utf-8")).hexdigest()
        ratio = int(digest[:8], 16) / 0xFFFFFFFF
        return low + ((high - low) * ratio)

    def _parse_option_contract(self, symbol: str):
        """Parse OpenAlgo option symbol and return (underlying, strike, option_type)."""
        match = re.match(
            r"^([A-Z]+)\d{2}(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}([\d.]+)(CE|PE)$",
            symbol.upper(),
        )
        if not match:
            return None
        underlying, strike_raw, option_type = match.groups()
        try:
            strike = float(strike_raw)
        except (TypeError, ValueError):
            return None
        return underlying, strike, option_type

    def _estimate_spot_from_contracts(self, underlying: str) -> float | None:
        """Estimate underlying spot from available F&O strikes."""
        key = (underlying or "").upper()
        if not key:
            return None
        if key in self._spot_hint_cache:
            return self._spot_hint_cache[key]

        try:
            from database.token_db_enhanced import fno_search_symbols
        except Exception:
            return None

        strikes = []
        for ex in ("NFO", "BFO", "MCX", "CDS"):
            try:
                rows = fno_search_symbols(
                    exchange=ex,
                    underlying=key,
                    instrumenttype="CE",
                    limit=300,
                )
            except Exception:
                rows = []

            for row in rows:
                try:
                    strike = float(row.get("strike"))
                except (TypeError, ValueError):
                    continue
                if strike > 0:
                    strikes.append(strike)

            if len(strikes) >= 30:
                break

        if not strikes:
            return None

        strikes.sort()
        median_strike = strikes[len(strikes) // 2]
        self._spot_hint_cache[key] = median_strike
        return median_strike

    def _derive_reference_price(self, symbol: str) -> float:
        """Derive a non-hardcoded initial reference price for a symbol."""
        symbol_upper = symbol.upper()

        parsed = self._parse_option_contract(symbol_upper)
        if parsed:
            underlying, strike, option_type = parsed
            base_spot = self._estimate_spot_from_contracts(underlying) or strike
            intrinsic = max(0.0, base_spot - strike) if option_type == "CE" else max(0.0, strike - base_spot)
            dist_pct = abs(base_spot - strike) / max(base_spot, 1.0)
            time_value = max(0.5, (base_spot * 0.006) * max(0.08, 1.0 - (dist_pct * 8.0)))
            premium = intrinsic + time_value
            premium += self._stable_noise(symbol_upper + "|init", -0.03, 0.03) * max(premium, 1.0)
            return max(0.05, premium)

        spot = self._estimate_spot_from_contracts(symbol_upper)
        if spot and spot > 0:
            return spot

        # Generic deterministic fallback when no contract metadata is available.
        return max(20.0, self._stable_noise(symbol_upper + "|fallback", 80.0, 1200.0))

    def initialize(self, broker_name: str, user_id: str, auth_data: dict = None) -> None:
        """
        Initialize the mock adapter. No real auth needed for the mock.
        """
        self.user_id = user_id
        self.broker_name = broker_name
        logger.info(f"Initialized Mock WebSocket for dhan_sandbox, user: {user_id}")

    def connect(self) -> None:
        """
        Start the mock data generation thread.
        """
        with self.lock:
            if self.running:
                logger.debug("Mock WebSocket is already running")
                return

            self.running = True
            self.connected = True
            
            # Start background thread to push mock market data
            self._mock_thread = threading.Thread(
                target=self._mock_streaming_loop, 
                daemon=True,
                name="DhanSandboxMockWS"
            )
            self._mock_thread.start()
            
            logger.info("Mock WebSocket connected and streaming thread started")

    def disconnect(self) -> None:
        """
        Stop the mock data generation thread.
        """
        with self.lock:
            self.running = False
            self.connected = False
            
            # Note: The background daemon thread will naturally exit 
            # when self.running becomes False without needing join()
            self._mock_thread = None
            logger.info("Mock WebSocket disconnected")
            
    def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5) -> Dict[str, Any]:
        """
        Subscribe to market data for a symbol.
        """
        with self.lock:
            sub_key = f"{exchange}_{symbol}"
            
            # Store subscription info (mimicking base behavior)
            self.subscriptions[sub_key] = {
                "symbol": symbol,
                "exchange": exchange,
                "mode": mode,
                "depth_level": depth_level
            }
            
            # Initialize a starting price if we haven't seen this symbol yet
            if sub_key not in self._current_prices:
                self._current_prices[sub_key] = self._derive_reference_price(symbol)
                
            logger.info(f"Mock Subscribed to {symbol} (Exchange: {exchange}, Mode: {mode})")
            
            # Standard response format
            return {
                "status": "success",
                "message": f"Subscribed to {symbol}",
                "broker": self.broker_name,
                "exchange": exchange,
                "supported_depth": 5, 
                "fallback_depth": 5
            }

    def unsubscribe(self, symbol: str, exchange: str, mode: int = None) -> Dict[str, Any]:
        """
        Unsubscribe from market data for a symbol.
        """
        with self.lock:
            sub_key = f"{exchange}_{symbol}"
            
            if sub_key in self.subscriptions:
                del self.subscriptions[sub_key]
                logger.info(f"Mock Unsubscribed from {symbol} ({exchange})")
                
            return {
                "status": "success",
                "message": f"Unsubscribed from {symbol}"
            }

    def _mock_streaming_loop(self):
        """
        Background thread that generates and publishes mock market data 
        for all subscribed symbols every second.
        """
        while self.running:
            try:
                # Iterate over a copy to avoid dictionary changed size during iteration
                with self.lock:
                    subs = list(self.subscriptions.values())
                
                now_ms = int(time.time() * 1000)
                
                for sub in subs:
                    symbol = sub["symbol"]
                    exchange = sub["exchange"]
                    mode = sub["mode"]
                    sub_key = f"{exchange}_{symbol}"

                    current_price = self._current_prices.get(
                        sub_key,
                        self._derive_reference_price(symbol),
                    )
                    parsed = self._parse_option_contract(symbol)

                    if parsed:
                        underlying, strike, option_type = parsed
                        base_spot = self._estimate_spot_from_contracts(underlying) or strike
                        intrinsic = max(0.0, base_spot - strike) if option_type == "CE" else max(0.0, strike - base_spot)
                        dist_pct = abs(base_spot - strike) / max(base_spot, 1.0)
                        fair_time_value = max(
                            0.5,
                            (base_spot * 0.006) * max(0.08, 1.0 - (dist_pct * 8.0)),
                        )
                        fair_price = intrinsic + fair_time_value
                        drift = (fair_price - current_price) * 0.18
                        step = drift + random.uniform(
                            -max(fair_price * 0.02, 0.2),
                            max(fair_price * 0.02, 0.2),
                        )
                        new_price = max(0.05, current_price + step)
                    else:
                        step = random.uniform(
                            -max(current_price * 0.0025, 0.05),
                            max(current_price * 0.0025, 0.05),
                        )
                        new_price = max(0.05, current_price + step)
                        
                    self._current_prices[sub_key] = new_price
                    
                    # Create mock data object matching OpenAlgo normalized format
                    market_data = {
                        "symbol": symbol,
                        "exchange": exchange,
                        "mode": mode,
                        "timestamp": now_ms,
                        "ltp": round(new_price, 2),
                        "ltt": now_ms,
                    }
                    
                    # Add extra fields for quote/depth modes
                    if mode >= 2:
                        market_data.update({
                            "volume": random.randint(1000, 50000),
                            "oi": random.randint(10000, 500000),
                            "open": round(new_price * 0.95, 2),
                            "high": round(new_price * 1.05, 2),
                            "low": round(new_price * 0.90, 2),
                            "close": round(new_price * 0.98, 2),
                            "last_trade_quantity": random.randint(1, 100),
                            "average_price": round(new_price, 2),
                            "total_buy_quantity": random.randint(5000, 100000),
                            "total_sell_quantity": random.randint(5000, 100000)
                        })
                    
                    # Add depth for depth mode
                    if mode >= 3:
                        market_data["depth"] = {
                            "buy": [
                                {"price": round(new_price - (0.05 * i), 2), "quantity": random.randint(10, 500), "orders": random.randint(1, 10)} for i in range(1, 6)
                            ],
                            "sell": [
                                {"price": round(new_price + (0.05 * i), 2), "quantity": random.randint(10, 500), "orders": random.randint(1, 10)} for i in range(1, 6)
                            ]
                        }
                    
                    # Generate topic matching broker format
                    mode_str = {1: "LTP", 2: "QUOTE", 3: "DEPTH", 4: "DEPTH", 5: "DEPTH"}.get(mode, "QUOTE")
                    topic = f"{exchange}_{symbol}_{mode_str}"
                    
                    # Publish data using BaseBrokerWebSocketAdapter method
                    self.publish_market_data(topic, market_data)
                    
            except Exception as e:
                logger.error(f"Error in mock streaming loop: {e}", exc_info=True)
                
            # Sleep 1 second before generating next tick
            time.sleep(1.0)
