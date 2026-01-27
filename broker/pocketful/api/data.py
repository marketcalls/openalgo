import json
import logging
import os
import time
import urllib.parse
from datetime import datetime, timedelta

import httpx
import pandas as pd

from broker.pocketful.api.pocketfulwebsocket import (
    PocketfulSocket,
    get_snapquotedata,
    get_ws_connection_status,
)
from broker.pocketful.database.master_contract_db import SymToken, db_session
from database.token_db import get_br_symbol, get_oa_symbol
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


# Configure logging
logger = get_logger(__name__)


class PocketfulPermissionError(Exception):
    """Custom exception for Pocketful API permission errors"""

    pass


class PocketfulAPIError(Exception):
    """Custom exception for other Pocketful API errors"""

    pass


def get_api_response(endpoint, auth, method="GET", payload=""):
    AUTH_TOKEN = auth
    base_url = "https://api.pocketful.in"
    headers = {"Authorization": f"Bearer {AUTH_TOKEN}", "Content-Type": "application/json"}

    try:
        # Log the complete request details for debugging
        logger.info("=== API Request Details ===")
        logger.info(f"URL: {base_url}{endpoint}")
        logger.info(f"Method: {method}")
        logger.info(f"Headers: {json.dumps(headers, indent=2)}")
        if payload:
            logger.info(f"Payload: {payload}")

        # Get the shared httpx client
        client = get_httpx_client()
        url = f"{base_url}{endpoint}"

        # Make request based on method
        if method == "GET":
            res = client.get(url, headers=headers)
        elif method == "POST":
            res = client.post(url, headers=headers, content=payload)
        elif method == "PUT":
            res = client.put(url, headers=headers, content=payload)
        elif method == "DELETE":
            res = client.delete(url, headers=headers)
        else:
            res = client.request(method, url, headers=headers, content=payload)

        response = res.json()

        # Log the complete response
        logger.info("=== API Response Details ===")
        logger.info(f"Status Code: {res.status_code}")
        logger.info(f"Response Headers: {dict(res.headers)}")
        logger.info(f"Response Body: {json.dumps(response, indent=2)}")

        # Check for permission errors
        if response.get("status") == "error":
            error_type = response.get("error_type")
            error_message = response.get("message", "Unknown error")

            if error_type == "PermissionException" or "permission" in error_message.lower():
                raise PocketfulPermissionError(f"API Permission denied: {error_message}.")
            else:
                raise PocketfulAPIError(f"API Error: {error_message}")

        return response
    except PocketfulPermissionError:
        raise
    except PocketfulAPIError:
        raise
    except Exception as e:
        logger.error(f"API request failed: {str(e)}")
        raise PocketfulAPIError(f"API request failed: {str(e)}")


class BrokerData:
    def __init__(self, auth_token):
        """Initialize Pocketful data handler with authentication token"""
        self.auth_token = auth_token
        self.client_id = None  # Will be fetched when needed
        self.ws_connection = None
        self.ws_connected = False
        self.last_depth = {}

        # Exchange code mapping for Pocketful WebSocket
        self.exchange_map = {"NSE": 1, "NFO": 2, "CDS": 3, "MCX": 4, "BSE": 6, "BFO": 7}

        # POCKETFUL does not support historical data API
        # Empty timeframe map since historical data is not supported
        self.timeframe_map = {}

        # Market timing configuration for different exchanges
        self.market_timings = {
            "NSE": {"start": "09:15:00", "end": "15:30:00"},
            "BSE": {"start": "09:15:00", "end": "15:30:00"},
            "NFO": {"start": "09:15:00", "end": "15:30:00"},
            "CDS": {"start": "09:00:00", "end": "17:00:00"},
            "BCD": {"start": "09:00:00", "end": "17:00:00"},
            "MCX": {"start": "09:00:00", "end": "23:30:00"},
        }

        # Default market timings if exchange not found
        self.default_market_timings = {"start": "00:00:00", "end": "23:59:59"}

    def get_market_timings(self, exchange: str) -> dict:
        """Get market start and end times for given exchange"""
        return self.market_timings.get(exchange, self.default_market_timings)

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """
        Get real-time quotes for given symbol using Compact Market Data WebSocket
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Quote data with required fields
        """
        try:
            # Get quotes using WebSocket compact market data - no fallbacks
            return self._get_quotes_compact(symbol, exchange)
        except PocketfulPermissionError as e:
            logger.error(f"Permission error fetching quotes: {str(e)}")
            raise
        except (PocketfulAPIError, Exception) as e:
            logger.error(f"Error fetching quotes: {str(e)}")
            raise PocketfulAPIError(f"Error fetching quotes: {str(e)}")

    def _get_quotes_from_depth(self, symbol: str, exchange: str) -> dict:
        """
        Get quotes from market depth data (fallback method)
        """
        # Use the market depth method which already has its own fallbacks
        depth = self.get_market_depth(symbol, exchange)

        # Extract basic quote information from the depth data
        return {
            "ask": depth["asks"][0]["price"] if depth["asks"] else 0,
            "bid": depth["bids"][0]["price"] if depth["bids"] else 0,
            "high": depth.get("high", 0),
            "low": depth.get("low", 0),
            "ltp": depth.get("ltp", 0),
            "open": depth.get("open", 0),
            "prev_close": depth.get("prev_close", 0),
            "volume": depth.get("volume", 0),
        }

    def _get_quotes_compact(self, symbol: str, exchange: str) -> dict:
        """
        Get quotes using detailed market data WebSocket (provides open/close/volume)
        """
        # Ensure WebSocket connection is established
        if not self._ensure_websocket_connection():
            raise PocketfulAPIError("WebSocket connection not established")

        # Convert symbol to broker format and get instrument token
        br_symbol = get_br_symbol(symbol, exchange)
        logger.info(f"Fetching quotes using detailed market data for {exchange}:{br_symbol}")

        # Get token from database
        with db_session() as session:
            symbol_info = (
                session.query(SymToken)
                .filter(SymToken.exchange == exchange, SymToken.brsymbol == br_symbol)
                .first()
            )

            if not symbol_info:
                raise PocketfulAPIError(f"Could not find token for {exchange}:{br_symbol}")

            # Get the instrument token from the database
            instrument_token = int(symbol_info.token)

        # Map exchange to Pocketful exchange code
        if exchange == "NSE_INDEX":
            exchange_code = self.exchange_map.get("NSE", 1)
        elif exchange == "BSE_INDEX":
            exchange_code = self.exchange_map.get("BSE", 6)
        else:
            exchange_code = self.exchange_map.get(exchange, 1)

        # Log the instrument details
        logger.info(f"Using exchange_code={exchange_code}, instrument_token={instrument_token}")

        # Subscribe to detailed market data (includes open/close/volume)
        detailed_payload = {"exchangeCode": exchange_code, "instrumentToken": instrument_token}
        subscription_result = self.ws_connection.subscribe_detailed_marketdata(detailed_payload)
        logger.info(f"Detailed market data subscription result: {subscription_result}")

        # Use try/finally to ensure unsubscribe is always called
        detailed_data = None
        try:
            # Wait for data to be received
            attempts = 0
            max_attempts = 10

            while attempts < max_attempts:
                time.sleep(1.0)
                detailed_data = self.ws_connection.read_detailed_marketdata()
                logger.info(f"Attempt {attempts + 1}: Received detailed data: {detailed_data}")

                # Check if we have valid data for our instrument
                if detailed_data and isinstance(detailed_data, dict):
                    token_in_data = detailed_data.get("instrument_token") or detailed_data.get(
                        "instrumentToken"
                    )
                    if token_in_data and str(token_in_data) == str(instrument_token):
                        logger.info(f"Received valid detailed data for {exchange}:{br_symbol}")
                        break

                attempts += 1
        finally:
            # Always unsubscribe, even if an exception occurs
            self.ws_connection.unsubscribe_detailed_marketdata(detailed_payload)

        # If no valid data received, raise exception
        if not detailed_data or not isinstance(detailed_data, dict):
            raise PocketfulAPIError(f"No detailed market data received for {exchange}:{br_symbol}")

        # Extract and format quote data from detailed market data
        # Note: Price values are multiplied by 100
        last_traded_price = (
            detailed_data.get("last_traded_price", 0) / 100
            if detailed_data.get("last_traded_price")
            else 0
        )
        bid_price = (
            detailed_data.get("best_bid_price", 0) / 100
            if detailed_data.get("best_bid_price")
            else 0
        )
        ask_price = (
            detailed_data.get("best_ask_price", 0) / 100
            if detailed_data.get("best_ask_price")
            else 0
        )
        high_price = (
            detailed_data.get("high_price", 0) / 100 if detailed_data.get("high_price") else 0
        )
        low_price = detailed_data.get("low_price", 0) / 100 if detailed_data.get("low_price") else 0
        open_price = (
            detailed_data.get("open_price", 0) / 100 if detailed_data.get("open_price") else 0
        )
        close_price = (
            detailed_data.get("close_price", 0) / 100 if detailed_data.get("close_price") else 0
        )
        volume = detailed_data.get("trade_volume", 0)

        # Calculate change from LTP and previous close
        change = last_traded_price - close_price if close_price else 0

        # Return formatted quote data
        return {
            "ask": ask_price,
            "bid": bid_price,
            "high": high_price,
            "low": low_price,
            "ltp": last_traded_price,
            "open": open_price,
            "prev_close": close_price,
            "volume": volume,
            "oi": detailed_data.get("currentOpenInterest", 0),
            "change": change,
        }

    def get_history(
        self, symbol: str, exchange: str, timeframe: str, from_date: str, to_date: str
    ) -> pd.DataFrame:
        """
        Get historical data for given symbol and timeframe
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
            timeframe: Timeframe (e.g., 1m, 5m, 15m, 60m, D)
            from_date: Start date in format YYYY-MM-DD
            to_date: End date in format YYYY-MM-DD
        Returns:
            pd.DataFrame: Historical data with OHLCV
        """
        logger.warning("Historical data API is no longer supported by Pocketful")
        # Return empty DataFrame with message
        return pd.DataFrame(
            {"message": "Pocketful does not support historical data API", "status": "success"},
            index=[0],
        )

    def get_intervals(self) -> list:
        """Get available intervals/timeframes for historical data

        Returns:
            list: List of available intervals
        """
        logger.warning("Historical data API is no longer supported by Pocketful")
        # Return empty list with success status
        return [{"message": "Pocketful does not support historical data API", "status": "success"}]

    def _get_client_id(self):
        """
        Get client_id from Pocketful API
        Returns:
            str: Client ID for the authenticated user
        """
        if not self.client_id:
            try:
                # Fetch client_id from trading_info endpoint
                logger.info("Fetching client_id from trading_info endpoint")

                # Get the shared httpx client
                client = get_httpx_client()
                headers = {
                    "Authorization": f"Bearer {self.auth_token}",
                    "Content-Type": "application/json",
                }

                response = client.get(
                    "https://trade.pocketful.in/api/v1/user/trading_info", headers=headers
                )
                info_response = response.json()

                if info_response.get("status") == "success":
                    self.client_id = info_response.get("data", {}).get("client_id")
                    logger.info(f"Got client_id from API: {self.client_id}")
                else:
                    raise PocketfulAPIError(
                        f"Failed to fetch client_id: {info_response.get('message', 'Unknown error')}"
                    )
            except httpx.HTTPError as e:
                logger.error(f"Error fetching client_id: {str(e)}")
                raise PocketfulAPIError(f"Error fetching client_id: {str(e)}")
            except Exception as e:
                logger.error(f"Error fetching client_id: {str(e)}")
                raise PocketfulAPIError(f"Error fetching client_id: {str(e)}")

        return self.client_id

    def _ensure_websocket_connection(self):
        """
        Ensure WebSocket connection is established
        Returns:
            bool: True if connection is successful, False otherwise
        """
        if self.ws_connection is None:
            logger.info("Initializing WebSocket connection")
            # Get client_id first
            client_id = self._get_client_id()
            if not client_id:
                logger.error("Failed to get client_id for WebSocket connection")
                raise PocketfulAPIError("Failed to get client_id for WebSocket connection")

            try:
                self.ws_connection = PocketfulSocket(self.client_id, self.auth_token)
                self.ws_connected = self.ws_connection.run_socket()

                if not self.ws_connected:
                    logger.error("Failed to establish WebSocket connection")
                    raise PocketfulAPIError("Failed to establish WebSocket connection")

                logger.info("WebSocket connection established successfully")
                return True
            except Exception as e:
                logger.error(f"Error establishing WebSocket connection: {str(e)}")
                raise PocketfulAPIError(f"Error establishing WebSocket connection: {str(e)}")
        return self.ws_connected

    def get_market_depth(self, symbol: str, exchange: str) -> dict:
        """
        Get market depth for given symbol using WebSocket
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Market depth data
        """
        try:
            # Get market depth using WebSocket - no fallback to mock data
            return self._get_market_depth_websocket(symbol, exchange)
        except PocketfulPermissionError as e:
            logger.error(f"Permission error fetching market depth: {str(e)}")
            raise
        except (PocketfulAPIError, Exception) as e:
            logger.error(f"Error fetching market depth: {str(e)}")
            raise PocketfulAPIError(f"Error fetching market depth: {str(e)}")

    def _get_mock_market_depth(self, symbol: str, exchange: str) -> dict:
        """
        Generate mock market depth data with proper structure
        This is a fallback when WebSocket fails
        """
        logger.warning(f"Generating mock market depth data for {exchange}:{symbol}")

        # Try to get approximate price data from compact market data
        approx_price = 100.0  # Default starting price
        try:
            # Try to get a more realistic price from compact market data
            compact_data = self._get_quotes_compact_noexcept(symbol, exchange)
            if compact_data and "ltp" in compact_data and compact_data["ltp"] > 0:
                approx_price = compact_data["ltp"]
                logger.info(
                    f"Using approximate price of {approx_price} from compact data for mock depth"
                )
        except Exception:
            pass  # Ignore errors, just use default

        # Create structured mock data matching Pocketful format with realistic prices
        mock_data = {
            "asks": [
                {"price": approx_price, "quantity": 100, "orders": 1},
                {"price": approx_price + (approx_price * 0.005), "quantity": 200, "orders": 2},
                {"price": approx_price + (approx_price * 0.010), "quantity": 300, "orders": 3},
                {"price": approx_price + (approx_price * 0.015), "quantity": 400, "orders": 4},
                {"price": approx_price + (approx_price * 0.020), "quantity": 500, "orders": 5},
            ],
            "bids": [
                {"price": approx_price - (approx_price * 0.005), "quantity": 100, "orders": 1},
                {"price": approx_price - (approx_price * 0.010), "quantity": 200, "orders": 2},
                {"price": approx_price - (approx_price * 0.015), "quantity": 300, "orders": 3},
                {"price": approx_price - (approx_price * 0.020), "quantity": 400, "orders": 4},
                {"price": approx_price - (approx_price * 0.025), "quantity": 500, "orders": 5},
            ],
            "high": approx_price + (approx_price * 0.025),
            "low": approx_price - (approx_price * 0.03),
            "ltp": approx_price,
            "ltq": 10,
            "oi": 0,
            "open": approx_price - (approx_price * 0.01),
            "prev_close": approx_price - (approx_price * 0.015),
            "totalbuyqty": 1500,
            "totalsellqty": 1500,
            "volume": 5000,
            "instrument_token": 0,  # Placeholder
        }

        return mock_data

    def _get_market_depth_websocket(self, symbol: str, exchange: str) -> dict:
        """
        Get market depth using WebSocket implementation
        Internal method called by get_market_depth
        """
        try:
            # Ensure WebSocket connection is established
            if not self._ensure_websocket_connection():
                raise PocketfulAPIError("WebSocket connection not established")

            # Convert symbol to broker format and get instrument token
            br_symbol = get_br_symbol(symbol, exchange)
            logger.info(f"Fetching market depth for {exchange}:{br_symbol}")

            # Get token from database
            with db_session() as session:
                symbol_info = (
                    session.query(SymToken)
                    .filter(SymToken.exchange == exchange, SymToken.brsymbol == br_symbol)
                    .first()
                )

                if not symbol_info:
                    raise Exception(f"Could not find token for {exchange}:{br_symbol}")

                # Get the instrument token from the database
                instrument_token = int(symbol_info.token)

            # Map exchange to Pocketful exchange code
            if exchange == "NSE_INDEX":
                exchange_code = self.exchange_map.get("NSE", 1)
            elif exchange == "BSE_INDEX":
                exchange_code = self.exchange_map.get("BSE", 6)
            else:
                exchange_code = self.exchange_map.get(exchange, 1)

            # Log the instrument details
            logger.info(f"Using exchange_code={exchange_code}, instrument_token={instrument_token}")

            # Subscribe to snapquote data
            snapquote_payload = {"exchangeCode": exchange_code, "instrumentToken": instrument_token}
            subscription_result = self.ws_connection.subscribe_snapquote_data(snapquote_payload)
            logger.info(f"Subscription result: {subscription_result}")

            # Wait for data to be received with increased timeout
            attempts = 0
            max_attempts = 15  # Increased attempts further
            snapquote_data = None

            # Set debug logging to see all messages
            logging.getLogger("broker.pocketful.api.packet_decoder").setLevel(logging.DEBUG)
            logging.getLogger("broker.pocketful.api.pocketfulwebsocket").setLevel(logging.DEBUG)

            # Send a dummy heartbeat to ensure connection is active
            if hasattr(self.ws_connection, "_send_heartbeat"):
                self.ws_connection._send_heartbeat()

            logger.info(f"Waiting for snapquote data for instrument {instrument_token}")

            # Try a different approach - multiple shorter waits instead of longer ones
            while attempts < max_attempts:
                time.sleep(1.0)  # Standard wait time
                snapquote_data = self.ws_connection.read_snapquote_data()
                logger.info(f"Attempt {attempts + 1}: Received data: {snapquote_data}")

                # If we get any data at all, dump the raw data to help with debugging
                if isinstance(snapquote_data, dict) and snapquote_data:
                    logger.info(f"Received some data on attempt {attempts + 1}: {snapquote_data}")

                # More flexible check for valid data
                if snapquote_data and isinstance(snapquote_data, dict):
                    # Try different keys that might be present
                    token_in_data = snapquote_data.get("instrument_token") or snapquote_data.get(
                        "instrumentToken"
                    )
                    if token_in_data:
                        logger.info(
                            f"Received data with token {token_in_data} (looking for {instrument_token})"
                        )

                        # More flexible token matching
                        if str(token_in_data) == str(instrument_token):
                            logger.info(
                                f"Received valid market depth data for {exchange}:{br_symbol}"
                            )
                            break
                        else:
                            logger.debug(f"Received data for different instrument: {token_in_data}")
                    else:
                        # If no token is found, log the full response
                        logger.info(f"Received response without token field: {snapquote_data}")

                attempts += 1

            # Unsubscribe after receiving data
            self.ws_connection.unsubscribe_snapquote_data(snapquote_payload)

            # If no valid data received, try to use cached data or raise error
            if (
                not snapquote_data
                or not isinstance(snapquote_data, dict)
                or "instrument_token" not in snapquote_data
            ):
                logger.warning(f"No market depth data received for {exchange}:{br_symbol}")
                # Return last known depth if available
                if self.last_depth.get(f"{exchange}:{br_symbol}"):
                    logger.info(f"Using cached market depth data for {exchange}:{br_symbol}")
                    return self.last_depth.get(f"{exchange}:{br_symbol}")
                raise Exception(f"No market depth data received for {exchange}:{br_symbol}")

            # Store the data for reference (in case subsequent calls fail)
            self.last_depth[f"{exchange}:{br_symbol}"] = snapquote_data

            # Process snapquote data
            # Note: Pocketful price values are multiplied by 100, need to convert back

            # Format asks and bids
            asks = []
            bids = []

            # Process ask prices and quantities
            ask_prices = snapquote_data.get("askPrices", [])
            ask_qtys = snapquote_data.get("askQtys", [])
            sellers = snapquote_data.get("sellers", [])

            for i in range(min(5, len(ask_prices))):
                asks.append(
                    {
                        "price": ask_prices[i] / 100
                        if ask_prices[i]
                        else 0,  # Convert price back to standard format
                        "quantity": ask_qtys[i] if i < len(ask_qtys) else 0,
                        "orders": sellers[i] if i < len(sellers) else 0,
                    }
                )

            # Add empty entries if fewer than 5 provided
            while len(asks) < 5:
                asks.append({"price": 0, "quantity": 0, "orders": 0})

            # Process bid prices and quantities
            bid_prices = snapquote_data.get("bidPrices", [])
            bid_qtys = snapquote_data.get("bidQtys", [])
            buyers = snapquote_data.get("buyers", [])

            for i in range(min(5, len(bid_prices))):
                bids.append(
                    {
                        "price": bid_prices[i] / 100
                        if bid_prices[i]
                        else 0,  # Convert price back to standard format
                        "quantity": bid_qtys[i] if i < len(bid_qtys) else 0,
                        "orders": buyers[i] if i < len(buyers) else 0,
                    }
                )

            # Add empty entries if fewer than 5 provided
            while len(bids) < 5:
                bids.append({"price": 0, "quantity": 0, "orders": 0})

            # Return formatted market depth data
            return {
                "asks": asks,
                "bids": bids,
                "high": snapquote_data.get("high", 0) / 100 if snapquote_data.get("high") else 0,
                "low": snapquote_data.get("low", 0) / 100 if snapquote_data.get("low") else 0,
                "ltp": snapquote_data.get("averageTradePrice", 0) / 100
                if snapquote_data.get("averageTradePrice")
                else 0,
                "ltq": 0,  # Pocketful doesn't provide last traded quantity in snapquote
                "oi": 0,  # Pocketful doesn't provide open interest in snapquote
                "open": snapquote_data.get("open", 0) / 100 if snapquote_data.get("open") else 0,
                "prev_close": snapquote_data.get("close", 0) / 100
                if snapquote_data.get("close")
                else 0,
                "totalbuyqty": snapquote_data.get("totalBuyQty", 0),
                "totalsellqty": snapquote_data.get("totalSellQty", 0),
                "volume": snapquote_data.get("volume", 0),
            }

        except PocketfulPermissionError as e:
            logger.error(f"Permission error fetching market depth: {str(e)}")
            raise
        except (PocketfulAPIError, Exception) as e:
            logger.error(f"Error fetching market depth: {str(e)}")
            raise PocketfulAPIError(f"Error fetching market depth: {str(e)}")

    def _get_quotes_compact_noexcept(self, symbol: str, exchange: str) -> dict:
        """
        Get quotes using compact market data, but don't raise exceptions
        This is a helper method to safely get quote data for other functions
        """
        try:
            return self._get_quotes_compact(symbol, exchange)
        except Exception as e:
            logger.debug(f"Non-critical error getting compact data: {str(e)}")
            return {}

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """Alias for get_market_depth to maintain compatibility with common API"""
        return self.get_market_depth(symbol, exchange)

    def get_multiquotes(self, symbols: list) -> list:
        """
        Get real-time quotes for multiple symbols using WebSocket
        Pocketful WebSocket supports subscribing to multiple instruments

        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys
                     Example: [{'symbol': 'SBIN', 'exchange': 'NSE'}, ...]
        Returns:
            list: List of quote data for each symbol with format:
                  [{'symbol': 'SBIN', 'exchange': 'NSE', 'data': {...}}, ...]
        """
        try:
            # Pocketful WebSocket can handle multiple instruments
            # Using batch size of 50 for practical response times
            BATCH_SIZE = 50

            if len(symbols) > BATCH_SIZE:
                logger.debug(f"Processing {len(symbols)} symbols in batches of {BATCH_SIZE}")
                all_results = []

                for i in range(0, len(symbols), BATCH_SIZE):
                    batch = symbols[i : i + BATCH_SIZE]
                    logger.info(
                        f"Processing batch {i // BATCH_SIZE + 1}: symbols {i + 1} to {min(i + BATCH_SIZE, len(symbols))}"
                    )

                    batch_results = self._process_multiquotes_batch(batch)
                    all_results.extend(batch_results)

                logger.debug(f"Successfully processed {len(all_results)} quotes")
                return all_results
            else:
                return self._process_multiquotes_batch(symbols)

        except Exception as e:
            logger.exception("Error fetching multiquotes")
            raise PocketfulAPIError(f"Error fetching multiquotes: {e}") from e

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
        instruments_to_subscribe = []
        symbol_map = {}  # Map instrument_token to original symbol/exchange

        # Ensure WebSocket connection is established
        try:
            if not self._ensure_websocket_connection():
                raise PocketfulAPIError("WebSocket connection not established")
        except Exception as e:
            logger.error(f"Failed to establish WebSocket connection: {str(e)}")
            # Return all symbols as errors
            for item in symbols:
                results.append(
                    {
                        "symbol": item["symbol"],
                        "exchange": item["exchange"],
                        "error": f"WebSocket connection failed: {str(e)}",
                    }
                )
            return results

        # Step 1: Prepare all instruments
        for item in symbols:
            symbol = item["symbol"]
            exchange = item["exchange"]

            try:
                br_symbol = get_br_symbol(symbol, exchange)

                # Get token from database
                with db_session() as session:
                    symbol_info = (
                        session.query(SymToken)
                        .filter(SymToken.exchange == exchange, SymToken.brsymbol == br_symbol)
                        .first()
                    )

                    if not symbol_info:
                        logger.warning(
                            f"Skipping symbol {symbol} on {exchange}: could not find token"
                        )
                        skipped_symbols.append(
                            {
                                "symbol": symbol,
                                "exchange": exchange,
                                "error": "Could not resolve token",
                            }
                        )
                        continue

                    instrument_token = int(symbol_info.token)

                # Map exchange to Pocketful exchange code
                if exchange == "NSE_INDEX":
                    exchange_code = self.exchange_map.get("NSE", 1)
                elif exchange == "BSE_INDEX":
                    exchange_code = self.exchange_map.get("BSE", 6)
                else:
                    exchange_code = self.exchange_map.get(exchange, 1)

                # Store instrument details for subscription
                instruments_to_subscribe.append(
                    {"exchangeCode": exchange_code, "instrumentToken": instrument_token}
                )

                # Store mapping for response processing
                symbol_map[str(instrument_token)] = {
                    "symbol": symbol,
                    "exchange": exchange,
                    "br_symbol": br_symbol,
                    "token": instrument_token,
                    "exchange_code": exchange_code,
                }

            except Exception as e:
                logger.warning(f"Skipping symbol {symbol} on {exchange}: {str(e)}")
                skipped_symbols.append({"symbol": symbol, "exchange": exchange, "error": str(e)})
                continue

        if not instruments_to_subscribe:
            logger.warning("No valid symbols to fetch quotes for")
            return skipped_symbols

        # Step 2: Subscribe to all instruments at once
        logger.info(f"Subscribing to {len(instruments_to_subscribe)} symbols via WebSocket")

        for instrument in instruments_to_subscribe:
            try:
                self.ws_connection.subscribe_detailed_marketdata(instrument)
            except Exception as e:
                logger.warning(f"Failed to subscribe to instrument {instrument}: {str(e)}")

        # Step 3: Collect data while waiting - read continuously to capture all instruments
        received_data = {}
        num_instruments = len(instruments_to_subscribe)
        max_wait_time = min(
            max(num_instruments * 0.5, 3), 15
        )  # Between 3-15 seconds based on instrument count
        start_time = time.time()

        logger.debug(
            f"Collecting data for up to {max_wait_time:.1f}s for {num_instruments} instruments..."
        )

        # Read continuously until we have all data or timeout
        while time.time() - start_time < max_wait_time:
            detailed_data = self.ws_connection.read_detailed_marketdata()

            if detailed_data and isinstance(detailed_data, dict):
                token_in_data = detailed_data.get("instrument_token") or detailed_data.get(
                    "instrumentToken"
                )
                if token_in_data and str(token_in_data) in symbol_map:
                    received_data[str(token_in_data)] = detailed_data
                    logger.debug(
                        f"Received data for token {token_in_data} ({len(received_data)}/{num_instruments})"
                    )

            # Exit early if we have all data
            if len(received_data) >= num_instruments:
                logger.debug(f"All {num_instruments} instruments received, exiting early")
                break

            # Small delay between reads to avoid busy loop
            time.sleep(0.05)

        logger.debug(
            f"Data collection completed: {len(received_data)}/{num_instruments} instruments received"
        )

        # Step 5: Build results from received data
        for token_str, info in symbol_map.items():
            detailed_data = received_data.get(token_str)

            if detailed_data:
                # Extract and format quote data from detailed market data
                # Note: Price values are multiplied by 100
                last_traded_price = (
                    detailed_data.get("last_traded_price", 0) / 100
                    if detailed_data.get("last_traded_price")
                    else 0
                )
                bid_price = (
                    detailed_data.get("best_bid_price", 0) / 100
                    if detailed_data.get("best_bid_price")
                    else 0
                )
                ask_price = (
                    detailed_data.get("best_ask_price", 0) / 100
                    if detailed_data.get("best_ask_price")
                    else 0
                )
                high_price = (
                    detailed_data.get("high_price", 0) / 100
                    if detailed_data.get("high_price")
                    else 0
                )
                low_price = (
                    detailed_data.get("low_price", 0) / 100 if detailed_data.get("low_price") else 0
                )
                open_price = (
                    detailed_data.get("open_price", 0) / 100
                    if detailed_data.get("open_price")
                    else 0
                )
                close_price = (
                    detailed_data.get("close_price", 0) / 100
                    if detailed_data.get("close_price")
                    else 0
                )
                volume = detailed_data.get("trade_volume", 0)

                results.append(
                    {
                        "symbol": info["symbol"],
                        "exchange": info["exchange"],
                        "data": {
                            "bid": bid_price,
                            "ask": ask_price,
                            "open": open_price,
                            "high": high_price,
                            "low": low_price,
                            "ltp": last_traded_price,
                            "prev_close": close_price,
                            "volume": volume,
                            "oi": detailed_data.get("currentOpenInterest", 0),
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

        # Step 6: Unsubscribe after getting data
        logger.info(f"Unsubscribing from {len(instruments_to_subscribe)} symbols")
        for instrument in instruments_to_subscribe:
            try:
                self.ws_connection.unsubscribe_detailed_marketdata(instrument)
            except Exception as e:
                logger.warning(f"Failed to unsubscribe from instrument {instrument}: {str(e)}")

        logger.info(
            f"Retrieved quotes for {len([r for r in results if 'data' in r])}/{len(symbol_map)} symbols"
        )
        return skipped_symbols + results
