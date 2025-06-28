import asyncio
import threading
import logging
from typing import Callable, Optional, List, Dict, Any

from breeze_connect import BreezeConnect

logger = logging.getLogger("icici_websocket")


class ICICIWebSocket:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        session_token: str,
        on_ticks: Optional[Callable[[List[Dict[str, Any]]], None]] = None,
        on_connect: Optional[Callable[[], None]] = None,
        on_disconnect: Optional[Callable[[], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.session_token = session_token

        self.on_ticks = on_ticks or (lambda ticks: None)
        self.on_connect = on_connect or (lambda: None)
        self.on_disconnect = on_disconnect or (lambda: None)
        self.on_error = on_error or (lambda e: None)

        self.loop = None
        self.thread = None
        self.breeze = BreezeConnect(api_key=self.api_key)

        # Connection state
        self.connected = False
        self.running = False

    def start(self):
        """Start the Breeze WebSocket in a new thread and event loop."""
        if self.running:
            logger.warning("WebSocket is already running.")
            return

        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.running = True
        self.thread.start()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._connect())

    async def _connect(self):
        try:
            # Generate session and set token
            self.breeze.generate_session(api_secret=self.api_secret)
            self.breeze.set_session_token(self.session_token)

            logger.info("Connecting to ICICI WebSocket...")
            self.breeze.ws_connect(
                on_ticks=self._on_message,
                on_error=self._on_error,
                on_open=self._on_open,
                on_close=self._on_close
            )
        except Exception as e:
            logger.exception("WebSocket connection error.")
            self._on_error(e)

    def _on_open(self):
        logger.info("WebSocket connected.")
        self.connected = True
        self.on_connect()

    def _on_close(self):
        logger.warning("WebSocket disconnected.")
        self.connected = False
        self.on_disconnect()

    def _on_error(self, error: Exception):
        logger.error(f"WebSocket error: {error}")
        self.connected = False
        self.on_error(error)

    def _on_message(self, message: Dict[str, Any]):
        try:
            logger.debug(f"Received tick: {message}")
            self.on_ticks([message])
        except Exception as e:
            logger.exception("Error in tick handler")
            self._on_error(e)

    def subscribe(
        self,
        stock_code: str,
        exchange_code: str,
        product_type: str,
        expiry_date: Optional[str] = None,
        strike_price: Optional[float] = None,
        right: Optional[str] = None
    ):
        """Subscribe to an instrument feed."""
        try:
            self.breeze.subscribe_feeds(
                stock_code=stock_code,
                exchange_code=exchange_code,
                product_type=product_type,
                expiry_date=expiry_date,
                strike_price=strike_price,
                right=right
            )
            logger.info(f"Subscribed to {stock_code} on {exchange_code}")
        except Exception as e:
            logger.exception("Subscription failed.")
            self._on_error(e)

    def unsubscribe(
        self,
        stock_code: str,
        exchange_code: str,
        product_type: str,
        expiry_date: Optional[str] = None,
        strike_price: Optional[float] = None,
        right: Optional[str] = None
    ):
        """Unsubscribe from a feed."""
        try:
            self.breeze.unsubscribe_feeds(
                stock_code=stock_code,
                exchange_code=exchange_code,
                product_type=product_type,
                expiry_date=expiry_date,
                strike_price=strike_price,
                right=right
            )
            logger.info(f"Unsubscribed from {stock_code} on {exchange_code}")
        except Exception as e:
            logger.exception("Unsubscription failed.")
            self._on_error(e)

    def stop(self):
        """Stop the WebSocket connection."""
        if self.breeze:
            try:
                self.breeze.ws_disconnect()
                logger.info("WebSocket disconnected cleanly.")
            except Exception as e:
                logger.warning(f"Error during disconnect: {e}")
        self.running = False
        self.connected = False
