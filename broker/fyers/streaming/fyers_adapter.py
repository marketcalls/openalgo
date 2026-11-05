"""
Fyers WebSocket Adapter for OpenAlgo
Handles WebSocket streaming for all exchanges: NSE, NFO, BSE, BFO, MCX
Uses HSM binary protocol for real-time data
"""

import threading
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any, Dict, List, Optional

from database.token_db import get_br_symbol
from utils.logging import get_logger

from .fyers_hsm_websocket import FyersHSMWebSocket
from .fyers_mapping import FyersDataMapper
from .fyers_token_converter import FyersTokenConverter


# Quote fields a depth message borrows from the symbol feed, each with the raw
# HSM field it comes from. A Fyers depth (dp) frame carries only the five
# levels, so these are copied from the latest symbol-feed (sf/if) state of the
# same scrip; a field is copied only when Fyers actually sent its source.
_QUOTE_FIELDS_FOR_DEPTH = {
    "ltp": ("ltp",),
    "open": ("open_price",),
    "high": ("high_price",),
    "low": ("low_price",),
    "close": ("prev_close_price",),
    "volume": ("vol_traded_today",),
    "oi": ("OI",),
    "avg_trade_price": ("avg_trade_price",),
    "average_price": ("avg_trade_price",),
    "last_trade_quantity": ("last_traded_qty",),
    "last_quantity": ("last_traded_qty",),
    "last_traded_time": ("last_traded_time",),
    "last_trade_time": ("last_traded_time",),
    "exchange_time": ("exch_feed_time",),
    "total_buy_quantity": ("tot_buy_qty",),
    "total_sell_quantity": ("tot_sell_qty",),
    "upper_circuit": ("upper_ckt",),
    "lower_circuit": ("lower_ckt",),
    "change": ("ltp", "prev_close_price"),
    "change_percent": ("ltp", "prev_close_price"),
    "percent_change": ("ltp", "prev_close_price"),
}


class FyersAdapter:
    """
    Fyers WebSocket adapter for OpenAlgo streaming service
    Follows OpenAlgo adapter pattern similar to Angel, Zerodha etc.
    """

    def __init__(self, access_token: str, userid: str):
        """
        Initialize Fyers adapter

        Args:
            access_token: Fyers access token
            userid: User ID
        """
        self.access_token = access_token
        self.userid = userid
        self.logger = get_logger("fyers_adapter")

        # Initialize components
        self.token_converter = FyersTokenConverter(access_token)
        self.data_mapper = FyersDataMapper()
        self.ws_client = None

        # Subscription tracking
        self.active_subscriptions = {}  # symbol -> subscription_info
        self.subscription_callbacks = {}  # data_type -> callback
        self.symbol_to_hsm = {}  # symbol -> hsm_token mapping
        self.hsm_to_symbol = {}  # hsm_token -> symbol mapping (reverse lookup)

        # Connection state
        self.connected = False
        self.connecting = False
        # Last error from connect(), exposed so the outer adapter can surface
        # the underlying auth/network failure rather than a generic message
        # (issue #1419). Reset on each connect() attempt.
        self.last_error: str | None = None

        # Threading
        self.lock = threading.Lock()

        # Real LTP per symbol, borrowed by depth messages (which carry none)
        self.last_ltp = {}  # "EXCHANGE:SYMBOL" -> last traded price from the sf/if feed

        # Latest quote fields per scrip from the sf/if feed, merged into every
        # depth message so a DEPTH tick carries the quote too
        self.latest_quote = {}  # "EXCHANGE:SYMBOL" -> {openalgo key: value}
        # Depth published before the scrip's first sf snapshot, sent again once
        # that snapshot arrives so the quote fields are not missing until the
        # next book change
        self.depth_awaiting_quote = {}  # "EXCHANGE:SYMBOL" -> depth payload

        # self.logger.info(f"Fyers adapter initialized for user: {userid}")

    def connect(self) -> bool:
        """
        Connect to Fyers HSM WebSocket

        On failure, ``self.last_error`` is populated with the underlying error
        message so callers can surface it (issue #1419 — ConnectionPool needs
        the real auth keyword to trigger token refresh, not a generic bool).

        Returns:
            True if connection successful, False otherwise
        """
        if self.connected:
            self.logger.warning("Already connected to Fyers WebSocket")
            return True

        if self.connecting:
            self.logger.warning("Connection already in progress")
            self.last_error = "Connection already in progress"
            return False

        try:
            self.connecting = True
            self.last_error = None
            self.logger.info("Connecting to Fyers HSM WebSocket...")

            # Initialize WebSocket client. Pass user_id so the client can
            # re-read a fresh access token from the database on reconnect
            # (tokens roll over daily at ~3 AM IST).
            self.ws_client = FyersHSMWebSocket(
                access_token=self.access_token, log_path="", user_id=self.userid
            )

            # Set callbacks
            self.ws_client.set_callbacks(
                on_message=self._on_message,
                on_error=self._on_error,
                on_open=self._on_open,
                on_close=self._on_close,
            )

            # Connect
            self.ws_client.connect()

            # Wait for authentication
            timeout = 15
            start_time = time.time()
            while not self.ws_client.is_connected() and time.time() - start_time < timeout:
                time.sleep(0.1)

            if self.ws_client.is_connected():
                self.connected = True
                self.logger.info("Connected to Fyers HSM WebSocket")
                return True
            else:
                self.last_error = "Failed to authenticate with Fyers HSM WebSocket (timeout)"
                self.logger.error(f"{self.last_error}")
                return False

        except Exception as e:
            self.last_error = str(e)
            self.logger.error(f"Connection error: {e}")
            return False
        finally:
            self.connecting = False

    def disconnect(self, clear_mappings=True):
        """
        Disconnect from Fyers WebSocket

        Args:
            clear_mappings: If True, clear all mappings. If False, preserve them for reconnection.
        """
        try:
            self.connected = False
            if self.ws_client:
                self.ws_client.disconnect()
                self.ws_client = None

            # Only clear mappings if requested (for complete disconnect)
            if clear_mappings:
                self.active_subscriptions.clear()
                self.symbol_to_hsm.clear()
                self.hsm_to_symbol.clear()  # Clear reverse mapping too
                self.subscription_callbacks.clear()  # Clear callbacks
                self._clear_quote_state()
                self.logger.info("Disconnected from Fyers WebSocket (cleared all mappings)")
            else:
                # Keep mappings but clear active subscriptions for reconnection
                self.active_subscriptions.clear()
                self.subscription_callbacks.clear()
                self._clear_quote_state()
                # self.logger.info(f"Disconnected from Fyers WebSocket (preserved {len(self.hsm_to_symbol)} mappings)")

        except Exception as e:
            self.logger.error(f"Error during disconnect: {e}")

    def subscribe_symbols(self, symbols: list[dict[str, str]], data_type: str, callback: Callable):
        """
        Subscribe to symbols for market data

        Args:
            symbols: List of symbol dicts with 'exchange' and 'symbol' keys
            data_type: Type of data ("SymbolUpdate", "DepthUpdate")
            callback: Callback function to receive data
        """
        if not self.connected:
            self.logger.error("Not connected to Fyers WebSocket")
            return False

        try:
            with self.lock:
                self.logger.debug("\n" + "=" * 60)
                self.logger.debug(f"SUBSCRIBING TO {len(symbols)} SYMBOLS")
                self.logger.debug(f"Data type: {data_type}")
                self.logger.debug(f"Symbols to subscribe: {symbols}")
                self.logger.debug("=" * 60)

                # Store callback per symbol to prevent data mixing
                # Use a unique key for each symbol and data type combination
                for symbol_info in symbols:
                    exchange = symbol_info.get("exchange", "NSE")
                    symbol = symbol_info.get("symbol", "")
                    if symbol:
                        full_symbol = f"{exchange}:{symbol}"
                        callback_key = f"{data_type}_{full_symbol}"
                        # Store callback per symbol to ensure proper data routing
                        self.subscription_callbacks[callback_key] = callback
                        self.logger.debug(f"Stored callback for {callback_key}")

                # Store subscription info for tracking
                valid_symbols = []
                for symbol_info in symbols:
                    exchange = symbol_info.get("exchange", "NSE")
                    symbol = symbol_info.get("symbol", "")

                    if not symbol:
                        continue

                    valid_symbols.append({"exchange": exchange, "symbol": symbol})

                    # Store subscription info
                    full_symbol = f"{exchange}:{symbol}"
                    self.active_subscriptions[full_symbol] = {
                        "exchange": exchange,
                        "symbol": symbol,
                        "data_type": data_type,
                        "subscribed_at": time.time(),
                    }

                if not valid_symbols:
                    self.logger.warning("No valid symbols to subscribe")
                    return False

                self.logger.debug(
                    f"Converting {len(valid_symbols)} OpenAlgo symbols to HSM format using database lookup..."
                )

                # Convert OpenAlgo symbols directly to HSM tokens using database lookup
                hsm_tokens, token_mappings, invalid_symbols = (
                    self.token_converter.convert_openalgo_symbols_to_hsm(valid_symbols, data_type)
                )

                if invalid_symbols:
                    self.logger.warning(f"Invalid symbols: {invalid_symbols}")

                if not hsm_tokens:
                    self.logger.error("No valid HSM tokens generated")
                    return False

                # Build the HSM<->OpenAlgo mapping by JOINING through brsymbol.
                #
                # The previous implementation paired hsm_tokens[i] with
                # valid_symbols[i] positionally, on the assumption that Fyers'
                # /data/symbol-token API preserves input order in its
                # `validSymbol` response. It DOES NOT reliably preserve order
                # — especially when index + options are mixed in one call —
                # so the pairing got scrambled. The visible symptom: NIFTY
                # spot LTP showed an option's premium, far-OTM strikes showed
                # NIFTY's bid/ask, and CE/PE rows appeared swapped.
                #
                # `token_mappings` is correctly keyed per-token (hsm_token ->
                # brsymbol). Building a brsymbol -> (exchange, symbol) reverse
                # map from valid_symbols lets us recover the correct OpenAlgo
                # identity for each HSM token regardless of API ordering.
                self.logger.debug(f"Creating HSM mappings for {len(hsm_tokens)} tokens...")

                brsymbol_to_openalgo: dict[str, tuple[str, str]] = {}
                for s in valid_symbols:
                    br = get_br_symbol(s["symbol"], s["exchange"])
                    if br:
                        brsymbol_to_openalgo[br] = (s["exchange"], s["symbol"])

                mapped_count = 0
                for hsm_token in hsm_tokens:
                    brsym = token_mappings.get(hsm_token)
                    if not brsym:
                        self.logger.warning(
                            f"No brsymbol in token_mappings for HSM token {hsm_token}"
                        )
                        continue
                    pair = brsymbol_to_openalgo.get(brsym)
                    if not pair:
                        self.logger.warning(f"brsymbol {brsym} did not match any input symbol")
                        continue
                    exch, sym = pair
                    full_symbol = f"{exch}:{sym}"
                    self.symbol_to_hsm[full_symbol] = hsm_token
                    self.hsm_to_symbol[hsm_token] = full_symbol
                    mapped_count += 1
                    self.logger.debug(f"Mapped {full_symbol} <-> {hsm_token} (brsymbol: {brsym})")

                # Sanity check: every input symbol should have ended up mapped.
                unmapped_subs = [
                    f"{s['exchange']}:{s['symbol']}"
                    for s in valid_symbols
                    if f"{s['exchange']}:{s['symbol']}" not in self.symbol_to_hsm
                ]
                for fs in unmapped_subs:
                    self.logger.warning(f"Unmapped subscription: {fs}")

                # A depth (dp) topic carries only the five book levels: no LTP,
                # OHLC, volume or traded quantities. Subscribe the same scrip's
                # symbol feed (sf) with it, so every depth message can carry the
                # quote. The sf topic is the dp topic with the feed prefix
                # changed, exactly as the token converter builds both. Index
                # depth already rides the index feed (if), which is the quote.
                if data_type == "DepthUpdate":
                    for hsm_token in list(hsm_tokens):
                        if not hsm_token.startswith("dp|"):
                            continue
                        full_symbol = self.hsm_to_symbol.get(hsm_token)
                        if not full_symbol:
                            continue
                        sf_token = "sf|" + hsm_token[3:]
                        if sf_token not in hsm_tokens:
                            hsm_tokens.append(sf_token)
                        token_mappings[sf_token] = token_mappings[hsm_token]
                        self.hsm_to_symbol[sf_token] = full_symbol
                        self.logger.debug(f"Depth {full_symbol} also subscribes {sf_token}")

                # Final verification
                self.logger.debug("\nMapping Summary:")
                self.logger.debug(f"   Active subscriptions: {len(self.active_subscriptions)}")
                self.logger.debug(f"   HSM tokens generated: {len(hsm_tokens)}")
                self.logger.debug(f"   Mappings created: {len(self.hsm_to_symbol)}")
                self.logger.debug(f"   Forward mappings (symbol->hsm): {self.symbol_to_hsm}")
                self.logger.debug(f"   Reverse mappings (hsm->symbol): {self.hsm_to_symbol}")

                self.logger.debug(f"\nSubscribing to {len(hsm_tokens)} HSM tokens...")
                for token in hsm_tokens:
                    self.logger.debug(f" {token}")

                # Subscribe to HSM WebSocket with all tokens at once
                self.ws_client.subscribe_symbols(hsm_tokens, token_mappings)

                # self.logger.info(f"\nSuccessfully sent subscription for {len(hsm_tokens)} HSM tokens")
                # self.logger.info(f"Expected data for {len(self.active_subscriptions)} symbols")
                # self.logger.info("="*60 + "\n")
                return True

        except Exception as e:
            self.logger.error(f"Subscription error: {e}")
            return False

    def subscribe_ltp(self, symbols: list[dict[str, str]], callback: Callable):
        """Subscribe to LTP data"""
        return self.subscribe_symbols(symbols, "SymbolUpdate", callback)

    def subscribe_quote(self, symbols: list[dict[str, str]], callback: Callable):
        """Subscribe to Quote data"""
        return self.subscribe_symbols(symbols, "SymbolUpdate", callback)

    def subscribe_depth(self, symbols: list[dict[str, str]], callback: Callable):
        """Subscribe to Depth data"""
        return self.subscribe_symbols(symbols, "DepthUpdate", callback)

    def get_last_ltp(self, exchange: str, symbol: str) -> float | None:
        """Last traded price seen on the sf/if feed, or None if not subscribed there"""
        return self.last_ltp.get(f"{exchange}:{symbol}")

    def get_latest_quote(self, exchange: str, symbol: str) -> dict | None:
        """Quote fields from the latest sf/if message for a scrip, or None.

        Only fields Fyers actually sent are present, so a caller merging them
        into a depth message never publishes a placeholder.
        """
        latest_quote, _ = self._quote_state()
        fields = latest_quote.get(f"{exchange}:{symbol}")
        return dict(fields) if fields else None

    def forget_quote(self, exchange: str, symbol: str) -> None:
        """Drop the stored quote of a scrip nothing reads any more."""
        full_symbol = f"{exchange}:{symbol}"
        latest_quote, awaiting = self._quote_state()
        latest_quote.pop(full_symbol, None)
        awaiting.pop(full_symbol, None)
        self.last_ltp.pop(full_symbol, None)

    def _quote_state(self) -> tuple[dict, dict]:
        """The latest-quote and awaiting-depth maps, created on first use."""
        if getattr(self, "latest_quote", None) is None:
            self.latest_quote = {}
        if getattr(self, "depth_awaiting_quote", None) is None:
            self.depth_awaiting_quote = {}
        return self.latest_quote, self.depth_awaiting_quote

    def _clear_quote_state(self) -> None:
        self.last_ltp.clear()
        latest_quote, awaiting = self._quote_state()
        latest_quote.clear()
        awaiting.clear()

    @staticmethod
    def _quote_fields_for_depth(fyers_data: dict[str, Any], quote_data: dict[str, Any]) -> dict:
        """
        The quote fields a depth message borrows, taken from one sf/if message.

        Only fields whose raw HSM source Fyers actually sent are kept, so a
        field the feed never carried (an index has no volume) is left out of
        the depth message instead of being published as zero.
        """
        return {
            key: quote_data[key]
            for key, sources in _QUOTE_FIELDS_FOR_DEPTH.items()
            if key in quote_data and all(src in fyers_data for src in sources)
        }

    def unsubscribe_symbols(self, symbols: list[dict[str, str]]):
        """
        Unsubscribe from symbols
        Note: HSM protocol doesn't support individual unsubscription easily
        This would require reconnection for full unsubscribe
        """
        self.logger.warning("HSM protocol doesn't support selective unsubscription")
        self.logger.info("To unsubscribe, disconnect and reconnect with new symbol list")

    def _on_open(self):
        """Handle WebSocket connection open"""
        self.logger.info("Fyers WebSocket connection opened")

    def _on_close(self):
        """Handle WebSocket connection close"""
        self.connected = False
        self.logger.info("Fyers WebSocket connection closed")

    def _on_error(self, error):
        """Handle WebSocket error"""
        self.logger.error(f"Fyers WebSocket error: {error}")

    def _on_message(self, fyers_data: dict[str, Any]):
        """
        Handle incoming market data from Fyers

        Args:
            fyers_data: Raw data from Fyers HSM WebSocket
        """
        try:
            if not fyers_data:
                return

            fyers_type = fyers_data.get("type", "sf")
            update_type = fyers_data.get("update_type", "snapshot")

            # Map to OpenAlgo format first to get symbol info
            mapped_data = self.data_mapper.map_fyers_data(fyers_data, "Quote")
            if not mapped_data:
                return

            # Route by the HSM topic only. Every topic this adapter subscribes
            # is mapped to its OpenAlgo symbol when it is subscribed, joined
            # through brsymbol. The old fallbacks (symbol-name substrings, a
            # "NIFTY ... FUT" pattern, "the only subscription") could hand one
            # scrip's tick to another symbol, so an unmapped tick is dropped.
            hsm_token = fyers_data.get("hsm_token")
            full_symbol = self.hsm_to_symbol.get(hsm_token) if hsm_token else None
            matched_subscription = (
                self.active_subscriptions.get(full_symbol) if full_symbol else None
            )
            if not matched_subscription:
                self.logger.debug(
                    f"Dropping tick for unmapped HSM topic {hsm_token} "
                    f"(symbol {fyers_data.get('symbol', 'N/A')})"
                )
                return

            full_symbol = f"{matched_subscription['exchange']}:{matched_subscription['symbol']}"

            # Stocks have two HSM streams, `sf` (quote) and `dp` (depth). A
            # depth subscription subscribes both, and every depth message
            # carries the latest quote fields from `sf`. Indices have a single
            # feed (`if`) which is fanned out to Quote and Depth subscribers
            # alike (issue #1093).
            quote_cb = self.subscription_callbacks.get(f"SymbolUpdate_{full_symbol}")
            depth_cb = self.subscription_callbacks.get(f"DepthUpdate_{full_symbol}")
            latest_quote, depth_awaiting_quote = self._quote_state()

            if fyers_type in ("sf", "if"):
                # Remember the real last traded price and quote fields. A depth
                # message carries none, so it borrows them from here.
                if mapped_data.get("ltp"):
                    self.last_ltp[full_symbol] = mapped_data["ltp"]
                latest_quote[full_symbol] = self._quote_fields_for_depth(fyers_data, mapped_data)

            dispatches: list[tuple[Callable, str]] = []
            if fyers_type == "dp":
                if depth_cb:
                    dispatches.append((depth_cb, "Depth"))
            elif fyers_type == "if":
                if quote_cb:
                    dispatches.append((quote_cb, "Quote"))
                if depth_cb:
                    dispatches.append((depth_cb, "Depth"))
            else:
                if quote_cb:
                    dispatches.append((quote_cb, "Quote"))
                # A depth sent before the first quote of this scrip went out
                # without the quote fields; send it once more, now complete.
                pending_depth = depth_awaiting_quote.pop(full_symbol, None)
                if depth_cb and pending_depth is not None:
                    dispatches.append((depth_cb, "PendingDepth"))

            if not dispatches:
                return

            # No LTP-based de-duplication here: the HSM client sends one
            # message per changed scrip, and an update that moves only bid,
            # ask or volume still has to reach subscribers (issue #2318).
            now = int(time.time())

            for cb, openalgo_data_type in dispatches:
                if openalgo_data_type == "PendingDepth":
                    side_data = pending_depth
                    openalgo_data_type = "Depth"
                elif openalgo_data_type == "Depth":
                    side_data = self.data_mapper.map_fyers_data(fyers_data, "Depth")
                    if not side_data:
                        continue
                else:
                    side_data = dict(mapped_data)

                if openalgo_data_type == "Depth":
                    # Real quote fields only, from the symbol feed. Before its
                    # first message they are left out rather than invented.
                    side_data.pop("ltp", None)
                    quote_fields = latest_quote.get(full_symbol)
                    if quote_fields:
                        side_data.update(quote_fields)
                    elif fyers_type == "dp":
                        depth_awaiting_quote[full_symbol] = dict(side_data)

                side_data["symbol"] = matched_subscription["symbol"]
                side_data["exchange"] = matched_subscription["exchange"]
                side_data["update_type"] = update_type
                side_data["timestamp"] = now

                if openalgo_data_type == "Depth":
                    depth = side_data.get("depth", {})
                    buy_levels = depth.get("buy", [])
                    sell_levels = depth.get("sell", [])
                    bid1 = buy_levels[0]["price"] if buy_levels else "N/A"
                    ask1 = sell_levels[0]["price"] if sell_levels else "N/A"
                    self.logger.debug(f"{full_symbol} depth: Bid={bid1}, Ask={ask1}")
                else:
                    self.logger.debug(f"{full_symbol} data: LTP={side_data.get('ltp', 0)}")

                cb(side_data)

        except Exception:
            self.logger.exception("Error processing Fyers market data message")

    def get_connection_status(self) -> dict[str, Any]:
        """
        Get connection status information

        Returns:
            Dict with connection status details
        """
        return {
            "connected": self.connected,
            "authenticated": self.ws_client.is_connected() if self.ws_client else False,
            "active_subscriptions": len(self.active_subscriptions),
            "websocket_url": FyersHSMWebSocket.HSM_URL,
            "protocol": "HSM Binary",
            "user_id": self.userid,
        }

    def get_subscriptions(self) -> dict[str, Any]:
        """
        Get current subscriptions

        Returns:
            Dict with subscription details
        """
        return {
            "total_subscriptions": len(self.active_subscriptions),
            "subscriptions": dict(self.active_subscriptions),
            "hsm_mappings": dict(self.symbol_to_hsm),
        }

    def is_connected(self) -> bool:
        """Check if adapter is connected and ready"""
        return self.connected and (self.ws_client.is_connected() if self.ws_client else False)

    def __del__(self):
        """
        Destructor to ensure proper cleanup when FyersAdapter is destroyed.
        This is critical for preventing FD leaks when objects are garbage collected.
        """
        try:
            if hasattr(self, "logger"):
                self.logger.debug("FyersAdapter destructor called")
            self.disconnect(clear_mappings=True)
        except Exception as e:
            # Fallback logging if self.logger is not available
            logger = get_logger("fyers_adapter")
            logger.error(f"Error in FyersAdapter destructor: {e}")

    def force_cleanup(self):
        """
        Force cleanup all resources (for emergency cleanup)
        """
        try:
            # Force stop all operations
            self.connected = False
            self.connecting = False

            # Force clear data structures
            if hasattr(self, "active_subscriptions"):
                self.active_subscriptions.clear()
            if hasattr(self, "subscription_callbacks"):
                self.subscription_callbacks.clear()
            if hasattr(self, "symbol_to_hsm"):
                self.symbol_to_hsm.clear()
            if hasattr(self, "hsm_to_symbol"):
                self.hsm_to_symbol.clear()
            if hasattr(self, "last_ltp"):
                self.last_ltp.clear()
            if getattr(self, "latest_quote", None):
                self.latest_quote.clear()
            if getattr(self, "depth_awaiting_quote", None):
                self.depth_awaiting_quote.clear()

            # Force cleanup WebSocket client
            if hasattr(self, "ws_client") and self.ws_client:
                try:
                    if hasattr(self.ws_client, "force_cleanup"):
                        self.ws_client.force_cleanup()
                    else:
                        self.ws_client.disconnect()
                except Exception:
                    pass
                self.ws_client = None

        except Exception:
            pass  # Suppress all errors in force cleanup
