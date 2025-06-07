# c:\Users\Karthik\Downloads\openalgo-main\broker\flattrade\streaming\flattrade_adapter.py

import logging
import threading
import time
import os
from datetime import datetime
import json # For ZMQ publishing
from typing import Callable, Dict, Any, List, Optional

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from database.token_db import get_token # May need for instrument token resolution
# For direct DB query for session token:
from database.auth_db import Auth, decrypt_token, DATABASE_URL 
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session

from .flattrade_websocket import FlattradeWebSocketClient
from . import flattrade_mapping

logger = logging.getLogger(__name__)

class FlattradeStreamAdapter(BaseBrokerWebSocketAdapter):
    """
    Adapter for Flattrade WebSocket, providing a consistent interface
    for the OpenAlgo system.
    """
    # OpenAlgo common subscription modes
    MODE_LTP = 1
    MODE_QUOTE = 2
    MODE_FULL = 3
    MODE_ORDER_UPDATES = 4  # New mode for order updates
    
    # Mode mapping to Flattrade specific modes
    MODE_TO_FLATTRADE = {
        MODE_LTP: "touchline",
        MODE_QUOTE: "touchline",  # Quote maps to touchline in Flattrade
        MODE_FULL: "depth",
        MODE_ORDER_UPDATES: "order_updates"
    }

    def __init__(self):
        super().__init__() # Call parent constructor for ZMQ setup
        self.logger = logging.getLogger("FlattradeStreamAdapter") # Use self.logger from base or re-init
        self.ws_client: Optional[FlattradeWebSocketClient] = None
        self.user_id: Optional[str] = None
        self.account_id: Optional[str] = None # Flattrade specific
        self.api_key: Optional[str] = None # Flattrade specific API key part
        self.session_token: Optional[str] = None # Flattrade susertoken
        
        self.broker_name = "flattrade"
        # self.is_connected is inherited as self.connected from BaseBrokerWebSocketAdapter
        self.connection_acknowledged: bool = False # Specific to Flattrade's 'ck' message
        self.lock = threading.Lock() # For thread safety

        # Subscription tracking (similar to Zerodha's adapter)
        # {symbol_exchange_mode: (symbol, exchange, mode, flattrade_token_if_any) }
        self.subscribed_instruments: Dict[str, tuple] = {}
        # To map Flattrade's instrument tokens back to symbol/exchange if needed for publishing
        self.flattrade_token_to_details: Dict[str, tuple] = {}
        self.order_updates_subscribed: bool = False

        # Connection state
        self.is_active = False
        self._connection_acknowledged = False
        self._connection_lock = threading.Lock()
        self._pending_subscriptions = []  # Store pending subscriptions until connection is ready
        
        # Initialize callback attributes
        self.on_tick_callback = None
        self.on_order_update_callback = None
        self.on_adapter_connect_callback = None
        self.on_adapter_disconnect_callback = None
        self.on_adapter_error_callback = None
        
        # Initialize subscription tracking
        self._subscriptions = set()  # Track active subscriptions

        self.logger.info("FlattradeStreamAdapter initialized (inheriting from BaseBrokerWebSocketAdapter).")

    def initialize(self, broker_name: str, user_id: str, auth_data: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        self.logger.info(f"Initializing FlattradeStreamAdapter for user: {user_id}, broker: {broker_name}")
        if broker_name != self.broker_name:
            return {'status': 'error', 'message': f'Invalid broker name: {broker_name}'}

        # Flattrade's BROKER_API_KEY is 'client_id:::api_key'
        # We should use the client_id from BROKER_API_KEY as it's the correct Flattrade client ID
        try:
            full_broker_api_key = os.getenv('BROKER_API_KEY')
            if not full_broker_api_key or ':::' not in full_broker_api_key:
                msg = "BROKER_API_KEY for Flattrade is missing or malformed in .env file (expected 'client_id:::api_key')."
                self.logger.error(msg)
                return {'status': 'error', 'message': msg}
            
            # Extract client_id and api_key from BROKER_API_KEY
            env_client_id, self.api_key = full_broker_api_key.split(':::')
            
            # Always use the client_id from BROKER_API_KEY as it's the correct Flattrade client ID
            self.user_id = env_client_id
            self.logger.info(f"Using Flattrade client_id from BROKER_API_KEY: {self.user_id}")
            
            if env_client_id != user_id:
                self.logger.warning(f"Overriding provided user_id '{user_id}' with client_id from BROKER_API_KEY: '{env_client_id}'")
            
            # Fetch Flattrade session_token (susertoken) directly from DB
            engine = create_engine(DATABASE_URL) 
            SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
            db_session = scoped_session(SessionLocal)
            auth_entry = None
            try:
                # Always use the client_id from BROKER_API_KEY for Flattrade
                # Search for auth entry with the exact client_id
                auth_entry = db_session.query(Auth).filter(
                    Auth.name == self.user_id,  # user_id is the Flattrade client_id from BROKER_API_KEY
                    Auth.broker == self.broker_name,
                    Auth.is_revoked == False
                ).first()
                
                # If not found by client_id, try to find any active auth entry for this broker
                if not auth_entry:
                    auth_entry = db_session.query(Auth).filter(
                        Auth.broker == self.broker_name,
                        Auth.is_revoked == False
                    ).first()
                    
                    if auth_entry:
                        # Log a warning but don't update self.user_id - keep the one from BROKER_API_KEY
                        logger.warning(f"Found auth entry with user_id '{auth_entry.name}' in database, but using client_id '{self.user_id}' from BROKER_API_KEY")
                
                if auth_entry and auth_entry.auth:
                    self.session_token = decrypt_token(auth_entry.auth)
                    if not self.session_token:
                        raise ValueError("Failed to decrypt token.")
                        
                    # Set account_id to be the same as user_id if not already set
                    self.account_id = self.user_id
                    self.logger.info("Successfully fetched and decrypted Flattrade session token.")
                else:
                    raise ValueError("No valid Flattrade session token found in auth_db.")
            finally:
                db_session.remove()

            # For Flattrade, account_id is often the same as user_id (client_id)
            # Initialize WebSocket client with the session token and API key
            self.ws_client = FlattradeWebSocketClient(
                user_id=self.user_id,
                account_id=self.user_id,  # Use user_id as account_id for Flattrade
                session_token=self.session_token,
                api_key=self.api_key
            )
            logger.info(f"Initialized WebSocket client with user_id: {self.user_id}, account_id: {self.user_id}")
            
            self.ws_client.set_on_open_callback(self._on_ws_open)
            self.ws_client.set_on_message_callback(self._on_ws_message)
            self.ws_client.set_on_error_callback(self._on_ws_error)
            self.ws_client.set_on_close_callback(self._on_ws_close)

            self.logger.info("FlattradeWebSocketClient instance created and callbacks set.")
            return {'status': 'success', 'message': 'Adapter initialized successfully.'}
        except Exception as e:
            self.logger.error(f"Error initializing Flattrade adapter: {e}", exc_info=True)
            return {'status': 'error', 'message': str(e)}

    def connect(self) -> Dict[str, Any]:
        """
        Establishes a WebSocket connection to Flattrade.
        
        Returns:
            Dict[str, Any]: Status of the connection attempt
        """
        with self._connection_lock:
            if self.is_active:
                self.logger.warning("Adapter is already connected")
                return {'status': 'success', 'message': 'Already connected'}
                
            if not self.ws_client:
                msg = "WebSocket client not initialized"
                self.logger.error(msg)
                return {'status': 'error', 'message': msg}
            
            try:
                # Reset connection state
                self.is_active = False
                
                # Connect the WebSocket client
                if self.ws_client.connect():
                    self.is_active = True
                    self.logger.info("WebSocket connection established successfully")
                    return {'status': 'success', 'message': 'Connection established'}
                else:
                    self.logger.error("Failed to establish WebSocket connection")
                    return {'status': 'error', 'message': 'Failed to connect'}
                    
            except Exception as e:
                self.logger.error(f"Error connecting to Flattrade WebSocket: {e}", exc_info=True)
                self.is_active = False
                return {'status': 'error', 'message': str(e)}

    def disconnect(self) -> Dict[str, Any]:
        """
        Close the WebSocket connection.
        """
        with self._connection_lock:
            if not self.is_active:
                self.logger.warning("Adapter is not connected")
                return {'status': 'success', 'message': 'Not connected'}
                
            self.logger.info("Adapter attempting to disconnect...")
            
            if not self.ws_client:
                self.logger.warning("No WebSocket client to disconnect")
                return {'status': 'error', 'message': 'No WebSocket client'}
            
            try:
                self.ws_client.close()
                self.logger.info("WebSocket connection closed successfully")
                return {'status': 'success', 'message': 'Disconnected successfully'}
                
            except Exception as e:
                self.logger.error(f"Error during Flattrade disconnect: {e}", exc_info=True)
                return {'status': 'error', 'message': str(e)}
            
            finally:
                self.is_active = False

    # --- Subscription Methods ---
    def _get_token_from_database(self, symbol: str, exchange: str) -> str | None:
        """
        Fetches the token number from the database for the given symbol and exchange.
        
        Args:
            symbol: The trading symbol
            exchange: The exchange (e.g., 'MCX', 'NSE')
            
        Returns:
            str: The token number if found, None otherwise
        """
        try:
            from sqlalchemy import create_engine, text, or_
            from sqlalchemy.orm import sessionmaker
            import os
            from dotenv import load_dotenv
            
            # Load environment variables
            load_dotenv()
            
            # Get database URL from environment variables
            db_url = os.getenv('DATABASE_URL')
            if not db_url:
                self.logger.error("DATABASE_URL not found in environment variables")
                return None
                
            # Create database engine and session
            engine = create_engine(db_url)
            Session = sessionmaker(bind=engine)
            session = Session()
            
            try:
                # First try exact match on brsymbol and brexchange
                query = text("""
                    SELECT token, brsymbol, name, symbol 
                    FROM symtoken 
                    WHERE (brsymbol = :symbol OR symbol = :symbol)
                    AND brexchange = :exchange
                    LIMIT 1
                """)
                
                result = session.execute(
                    query,
                    {"symbol": symbol, "exchange": exchange}
                ).fetchone()
                
                if result:
                    token, brsymbol, name, db_symbol = result
                    self.logger.info(f"Found token {token} for {exchange}|{symbol} (brsymbol: {brsymbol}, name: {name}, symbol: {db_symbol})")
                    return str(token)
                
                # If not found, try a more flexible search
                self.logger.info(f"No exact match for {exchange}|{symbol}, trying flexible search...")
                
                # Try with LIKE for partial matches (useful for MCX symbols)
                query = text("""
                    SELECT token, brsymbol, name, symbol 
                    FROM symtoken 
                    WHERE (brsymbol LIKE :like_symbol OR name LIKE :like_symbol OR symbol LIKE :like_symbol)
                    AND brexchange = :exchange
                    ORDER BY LENGTH(brsymbol) ASC
                    LIMIT 1
                """)
                
                # Try different patterns for the symbol
                patterns = [
                    f"%{symbol}%",  # Contains
                    f"{symbol}%",    # Starts with
                    f"%{symbol}"      # Ends with
                ]
                
                for pattern in patterns:
                    result = session.execute(
                        query,
                        {"like_symbol": pattern, "exchange": exchange}
                    ).fetchone()
                    
                    if result:
                        token, brsymbol, name, db_symbol = result
                        self.logger.info(f"Found token {token} for {exchange}|{symbol} using pattern '{pattern}' (brsymbol: {brsymbol}, name: {name}, symbol: {db_symbol})")
                        return str(token)
                
                # If still not found, try to clean up the symbol (remove spaces, special chars, etc.)
                clean_symbol = symbol.replace(' ', '').replace('-', '').replace('_', '').upper()
                if clean_symbol != symbol:
                    self.logger.info(f"Trying with cleaned symbol: {clean_symbol}")
                    return self._get_token_from_database(clean_symbol, exchange)
                
                # Log all available symbols for debugging
                self.logger.warning(f"No token found for symbol {symbol} on exchange {exchange}. Available symbols:")
                symbols = session.execute(
                    text("SELECT DISTINCT brsymbol FROM symtoken WHERE brexchange = :exchange LIMIT 10"),
                    {"exchange": exchange}
                ).fetchall()
                
                for sym in symbols:
                    self.logger.warning(f"- {sym[0]}")
                
                return None
                
            except Exception as e:
                self.logger.error(f"Error querying database: {e}", exc_info=True)
                return None
                
            finally:
                session.close()
                    
        except Exception as e:
            self.logger.error(f"Error in _get_token_from_database: {e}", exc_info=True)
            return None

    def _resolve_symbol_to_flattrade_token(self, symbol_info: dict) -> str | None:
        """
        Resolves a symbol dictionary to a Flattrade-specific instrument token string.
        Flattrade (Shoonya) tokens are typically in the format: EXCHANGE|TOKEN
        
        For MCX and other derivatives, we need to fetch the token number from the database.
        For NSE/BSE cash, we can use the symbol directly.
        """
        exchange = symbol_info.get('exchange')
        symbol = symbol_info.get('symbol')  # Expected to be underlying for derivatives or trading symbol for cash

        if not exchange or not symbol:
            self.logger.error(f"Missing 'exchange' or 'symbol' in symbol_info: {symbol_info}")
            return None

        exchange = str(exchange).upper()
        symbol = str(symbol).upper()

        # Handle special 'ORDERS' subscription
        if symbol == "ORDERS" and exchange == "ORDERS":
            return "ORDERS_PSEUDO_TOKEN"  # Special marker, not a real Flattrade token

        if exchange in ["NSE", "BSE"]:
            # For cash segment, we need to look up the numeric token from the database
            # Format will be EXCHANGE|TOKEN (e.g., NSE|2885 for RELIANCE)
            token = self._get_token_from_database(symbol, exchange)
            if token:
                self.logger.info(f"Found token {token} for {exchange}|{symbol} in database")
                return f"{exchange}|{token}"
            else:
                self.logger.warning(f"Token not found for {exchange}|{symbol} in database, falling back to symbol")
                return f"{exchange}|{symbol}|EQ"  # Fallback to symbol if token not found
        elif exchange == "NFO":
            instrument_type = str(symbol_info.get('instrument_type', '')).upper()
            
            # Check if symbol itself is a full trading symbol (heuristic)
            if any(kw in symbol for kw in ['FUT', 'CE', 'PE']) and len(symbol) > 10:
                 self.logger.info(f"Symbol '{symbol}' for NFO appears to be a pre-formatted trading symbol. Using as is: {exchange}|{symbol}")
                 return f"{exchange}|{symbol}"

            expiry_date_str = symbol_info.get('expiry_date') # Expected format: 'YYYY-MM-DD'
            if not expiry_date_str:
                self.logger.error(f"Missing 'expiry_date' for NFO instrument: {symbol_info}")
                return None
            
            try:
                expiry_obj = datetime.strptime(str(expiry_date_str), "%Y-%m-%d")
            except ValueError as e:
                self.logger.error(f"Invalid 'expiry_date' format for {symbol_info}: {e}. Expected YYYY-MM-DD.")
                return None

            if 'FUT' in instrument_type:
                # Example format: NIFTYDDMMMYYF (e.g., NIFTY25JUL24F) - VERIFY THIS!
                # Shoonya docs suggest format like: BANKNIFTY28MAR24FUT
                # Let's try SYMBOL + DDMMMYY + F
                token_symbol_part = f"{symbol}{expiry_obj.strftime('%d%b%y').upper()}F"
                # Alternative based on some broker conventions: SYMBOLYYMMDD_F
                # token_symbol_part = f"{symbol}{expiry_obj.strftime('%y%m%d')}F"
                self.logger.info(f"Constructed NFO Futures token part: {token_symbol_part} for {symbol_info}. VERIFY FORMAT.")
                return f"{exchange}|{token_symbol_part}"
            elif 'OPT' in instrument_type or instrument_type in ['CE', 'PE']:
                option_type = str(symbol_info.get('option_type', '')).upper()
                if not option_type and instrument_type in ['CE', 'PE']:
                    option_type = instrument_type
                elif not option_type and (instrument_type.endswith('CE') or instrument_type.endswith('PE')):
                    option_type = instrument_type[-2:]
                
                strike_price_str = symbol_info.get('strike_price')

                if not option_type or not strike_price_str:
                    self.logger.error(f"Missing option details (option_type, strike_price) for NFO symbol: {symbol_info}")
                    return None
                
                if option_type not in ['CE', 'PE']:
                    self.logger.error(f"Invalid option_type '{option_type}' for NFO symbol: {symbol_info}. Must be 'CE' or 'PE'.")
                    return None
                
                try:
                    # Shoonya format: SYMBOLDDMMMYY[C/P]STRIKE (e.g. NIFTY25JUL24C23000)
                    # Strike price needs to be an integer or float without decimals for some, with for others.
                    # Assuming strike_price can be float, format as integer if whole.
                    strike_price = float(strike_price_str)
                    formatted_strike = str(int(strike_price)) if strike_price.is_integer() else str(strike_price)
                    
                    token_symbol_part = f"{symbol}{expiry_obj.strftime('%d%b%y').upper()}{option_type}{formatted_strike}"
                    self.logger.info(f"Constructed NFO Option token part: {token_symbol_part} for {symbol_info}. VERIFY FORMAT.")
                    return f"{exchange}|{token_symbol_part}"
                except ValueError as e:
                    self.logger.error(f"Invalid 'strike_price' format for {symbol_info}: {e}")
                    return None
            else:
                self.logger.warning(f"Unhandled instrument_type '{instrument_type}' for NFO. Defaulting to {exchange}|{symbol}. This is likely incorrect.")
                return f"{exchange}|{symbol}" # Fallback, likely incorrect
                return f"{exchange}#{symbol}" # Fallback, likely incorrect
        elif exchange in ["MCX", "CDS", "BFO", "NCO", "NDX"]:
            # For MCX and other derivatives, we need to get the token from the database
            token = self._get_token_from_database(symbol, exchange)
            if token:
                self.logger.info(f"Found token {token} for {exchange}|{symbol} in database")
                return f"{exchange}|{token}"
            else:
                self.logger.warning(f"Could not find token for {exchange}|{symbol} in database, falling back to symbol")
                return f"{exchange}|{symbol}"
        else:
            self.logger.error(f"Unsupported exchange: {exchange} for symbol {symbol}")
            return None

    def subscribe(self, symbol_or_info=None, exchange: str = None, mode: int = 2, depth_level: int = 1, account_id: str = None):
        """
        Subscribe to market data or order updates using OpenAlgo common modes.
        
        For market data:
        1. With a symbol_info dict: subscribe(symbol_info, mode, depth_level)
        2. With individual params: subscribe(symbol, exchange, mode, depth_level)
        
        For order updates:
        subscribe(mode=4, account_id='your_account_id')
        
        Args:
            symbol_or_info: Either a symbol string or a dict with symbol info (None for order updates)
            exchange: Exchange code (required if symbol_or_info is a string for market data)
            mode: Subscription mode (1=LTP, 2=Quote, 3=Full/Depth, 4=Order Updates)
            depth_level: Depth level for market depth (default: 1)
            account_id: Required for order updates (mode=4)
            
        Returns:
            Dict with status and message
        """
        # Handle order updates (mode 4)
        if mode == self.MODE_ORDER_UPDATES:
            # Use the account_id from the WebSocket client if not provided
            account_id = account_id or (self.ws_client.account_id if self.ws_client else None)
            
            if not account_id:
                error_msg = "account_id is required for order updates. Please provide it or ensure the WebSocket client is properly initialized."
                self.logger.error(error_msg)
                return {'status': 'error', 'message': error_msg}
                
            try:
                self.logger.info(f"Subscribing to order updates for account: {account_id}")
                self.ws_client.subscribe_order_updates(account_id)
                self._subscriptions.add(f"order_updates|{account_id}")
                msg = f"Successfully subscribed to order updates for account {account_id}"
                self.logger.info(msg)
                return {'status': 'success', 'message': msg}
            except Exception as e:
                error_msg = f"Failed to subscribe to order updates: {str(e)}"
                self.logger.error(error_msg, exc_info=True)
                return {'status': 'error', 'message': error_msg}
        
        # Handle market data subscriptions (modes 1-3)
        if not symbol_or_info:
            error_msg = "symbol_or_info is required for market data subscriptions"
            self.logger.error(error_msg)
            return {'status': 'error', 'message': error_msg}
            
        # Handle different parameter formats for market data
        if isinstance(symbol_or_info, dict):
            symbol_info = symbol_or_info
            mode = exchange if isinstance(exchange, int) else mode  # If exchange is passed as mode
        else:
            symbol_info = {"symbol": symbol_or_info, "exchange": exchange}
            
        # Validate market data mode
        if mode not in [1, 2, 3]:
            error_msg = f"Unsupported subscription mode: {mode}. Must be one of: 1 (LTP), 2 (Quote), 3 (Full/Depth), 4 (Order Updates)"
            self.logger.error(error_msg)
            return {'status': 'error', 'message': error_msg}
            
        # Map to Flattrade specific mode
        flattrade_mode = {1: "touchline", 2: "touchline", 3: "depth"}.get(mode, "touchline")
            
        # Resolve the symbol info
        symbol_info = self._resolve_symbol_info(symbol_or_info, exchange)
        
        if not self.ws_client:
            error_msg = "WebSocket client not initialized"
            self.logger.error(error_msg)
            return {'status': 'error', 'message': error_msg, 'symbol': symbol_info, 'mode': mode}
            
        # If not connected or connection not yet acknowledged, queue the subscription
        if not self.is_active or not self._connection_acknowledged:
            self.logger.info(f"Connection not ready. Queueing subscription for {symbol_info['symbol']} ({symbol_info['exchange']}) in {mode} mode")
            self._pending_subscriptions.append((symbol_info, mode, depth_level))
            return {'status': 'queued', 'message': 'Subscription queued, will be processed when connection is ready', 'symbol': symbol_info, 'mode': mode}

        with self.lock:
            # Check connection state
            if not hasattr(self, 'is_active') or not self.is_active:
                msg = "WebSocket client not connected. Call connect() first."
                self.logger.error(f"Subscribe failed: {msg} Symbol: {symbol_info}, Mode: {mode}")
                return {'status': 'error', 'message': msg}
                
            flattrade_token = self._resolve_symbol_to_flattrade_token(symbol_info)

            if not flattrade_token:
                msg = f"Failed to resolve symbol info to Flattrade token: {symbol_info}"
                self.logger.error(msg)
                return {'status': 'error', 'message': msg}

            # Handle order updates subscription
            if flattrade_token == "ORDERS_PSEUDO_TOKEN":
                if "ORDERS" not in self._subscriptions:
                    self.logger.info("Subscribing to order updates.")
                    self.ws_client.subscribe_order_updates()
                    self._subscriptions.add("ORDERS")
                    return {'status': 'success', 'message': 'Subscribed to order updates.'}
                else:
                    self.logger.info("Already subscribed to order updates.")
                    return {'status': 'success', 'message': 'Already subscribed to order updates.'}

            # Handle instrument subscriptions (touchline, depth)
            # Construct a unique key for _subscriptions that includes mode
            subscription_key = f"{flattrade_token}|{mode}"
            if subscription_key in self._subscriptions:
                msg = f"Already subscribed to {flattrade_token} with mode {mode}."
                self.logger.info(msg)
                return {'status': 'success', 'message': msg}

            try:
                if mode == 1 or mode == 2:
                    self.logger.info(f"Subscribing to touchline for {flattrade_token}")
                    self.ws_client.subscribe_touchline([flattrade_token])
                elif mode == 3:
                    self.logger.info(f"Subscribing to depth for {flattrade_token}")
                    self.ws_client.subscribe_depth([flattrade_token])
                else:
                    msg = f"Unsupported subscription mode: {mode}"
                    self.logger.error(msg)
                    return {'status': 'error', 'message': msg}
                
                # Store the original mode in the subscription key for tracking
                self._subscriptions.add(f"{flattrade_token}|{mode}")
                msg = f"Subscription request sent for {flattrade_token}, mode {mode}."
                self.logger.info(msg)
                return {'status': 'success', 'message': msg}
            except Exception as e:
                msg = f"Error subscribing to {flattrade_token}, mode {mode}: {e}"
                self.logger.error(msg, exc_info=True)
                return {'status': 'error', 'message': msg}

    def unsubscribe(self, symbol_or_info=None, exchange: str = None, mode: int = 2, account_id: str = None) -> Dict[str, Any]:
        """
        Unsubscribe from market data or order updates using OpenAlgo common modes.
        
        For market data:
        1. With a symbol_info dict: unsubscribe(symbol_info, mode)
        2. With individual params: unsubscribe(symbol, exchange, mode)
        
        For order updates:
        unsubscribe(mode=4, account_id='your_account_id')
        
        Args:
            symbol_or_info: Either a symbol string or a dict with symbol info (None for order updates)
            exchange: Exchange code (required if symbol_or_info is a string for market data)
            mode: Subscription mode (1=LTP, 2=Quote, 3=Full/Depth, 4=Order Updates)
            account_id: Required for unsubscribing from order updates (mode=4)
            
        Returns:
            Dict with status and message
        """
        # Handle order updates unsubscription (mode 4)
        if mode == self.MODE_ORDER_UPDATES:
            if not account_id:
                error_msg = "account_id is required for unsubscribing from order updates"
                self.logger.error(error_msg)
                return {'status': 'error', 'message': error_msg}
                
            try:
                self.ws_client.unsubscribe_order_updates(account_id)
                self._subscriptions.discard(f"order_updates|{account_id}")
                msg = f"Order update unsubscription requested for account {account_id}"
                self.logger.info(msg)
                return {'status': 'success', 'message': msg}
            except Exception as e:
                error_msg = f"Failed to unsubscribe from order updates: {str(e)}"
                self.logger.error(error_msg, exc_info=True)
                return {'status': 'error', 'message': error_msg}
        
        # Handle market data unsubscriptions (modes 1-3)
        if not symbol_or_info:
            error_msg = "symbol_or_info is required for market data unsubscriptions"
            self.logger.error(error_msg)
            return {'status': 'error', 'message': error_msg}
            
        # Handle different parameter formats for market data
        if isinstance(symbol_or_info, dict):
            symbol_info = symbol_or_info
            mode = exchange if isinstance(exchange, int) else mode  # If exchange is passed as mode
        else:
            symbol_info = {"symbol": symbol_or_info, "exchange": exchange}
            
        # Validate market data mode
        if mode not in [1, 2, 3]:
            error_msg = f"Unsupported unsubscription mode: {mode}. Must be one of: 1 (LTP), 2 (Quote), 3 (Full/Depth), 4 (Order Updates)"
            self.logger.error(error_msg)
            return {'status': 'error', 'message': error_msg}
            
        # Map to Flattrade specific mode
        flattrade_mode = {1: "touchline", 2: "touchline", 3: "depth"}.get(mode, "touchline")
            
        # Handle both calling patterns
        if isinstance(symbol_or_info, dict):
            symbol_info = symbol_or_info
        else:
            symbol_info = {
                'symbol': symbol_or_info,
                'exchange': exchange,
                'instrument_type': 'EQUITY'  # Default, can be overridden if needed
            }
            
        with self.lock:
            # Check connection state
            if not hasattr(self, 'is_active') or not self.is_active:
                msg = "WebSocket client not connected. Call connect() first."
                self.logger.error(f"Unsubscribe failed: {msg} Symbol: {symbol_info}, Mode: {mode}")
                return {'status': 'error', 'message': msg}
                
            if not self.ws_client:
                msg = "WebSocket client not initialized."
                self.logger.error(f"Unsubscribe failed: {msg} Symbol: {symbol_info}, Mode: {mode}")
                return {'status': 'error', 'message': msg}

            flattrade_token = self._resolve_symbol_to_flattrade_token(symbol_info)

            if not flattrade_token:
                msg = f"Failed to resolve symbol info to Flattrade token for unsubscribe: {symbol_info}"
                self.logger.error(msg)
                return {'status': 'error', 'message': msg}

            # Handle order updates unsubscription
            if flattrade_token == "ORDERS_PSEUDO_TOKEN":
                if "ORDERS" in self._subscriptions:
                    self.logger.info("Unsubscribing from order updates.")
                    self.ws_client.unsubscribe_order_updates()
                    self._subscriptions.remove("ORDERS")
                    return {'status': 'success', 'message': 'Unsubscribed from order updates.'}
                else:
                    self.logger.info("Not currently subscribed to order updates.")
                    return {'status': 'success', 'message': 'Not currently subscribed to order updates.'}

            # Handle instrument unsubscriptions
            # Check both the mapped mode and the original mode if this was a 'quote' subscription
            subscription_key = f"{flattrade_token}|{mode}"
            
            # Check if either the original or mapped subscription exists
            if subscription_key not in self._subscriptions:
                msg = f"Not currently subscribed to {flattrade_token} with mode {mode}."
                self.logger.info(msg)
                return {'status': 'success', 'message': msg}

            try:
                if mode == 1 or mode == 2:
                    self.logger.info(f"Unsubscribing from touchline for {flattrade_token}")
                    self.ws_client.unsubscribe_touchline([flattrade_token])
                elif mode == 3:
                    self.logger.info(f"Unsubscribing from depth for {flattrade_token}")
                    self.ws_client.unsubscribe_depth([flattrade_token])
                else:
                    msg = f"Unsupported unsubscription mode: {mode}"
                    self.logger.error(msg)
                    return {'status': 'error', 'message': msg}
                
                # Remove both original and mapped subscription keys if they exist
                if subscription_key in self._subscriptions:
                    self._subscriptions.remove(subscription_key)
                msg = f"Unsubscribed from {flattrade_token}, mode {mode}."
                msg = f"Unsubscribed from {flattrade_token}, mode {original_mode if 'original_mode' in locals() else mode}."
                self.logger.info(msg)
                return {'status': 'success', 'message': msg}
            except Exception as e:
                msg = f"Error unsubscribing from {flattrade_token}, mode {mode}: {e}"
                self.logger.error(msg, exc_info=True)
                return {'status': 'error', 'message': msg}

    def _resolve_symbol_info(self, symbol_or_info, exchange: str = None) -> Dict[str, str]:
        """
        Resolve symbol input to a standardized symbol info dictionary.
        
        Args:
            symbol_or_info: Either a symbol string or a dictionary containing symbol info
            exchange: Exchange code (required if symbol_or_info is a string)
            
        Returns:
            Dict[str, str]: Standardized symbol info with keys: symbol, exchange, instrument_type
        """
        if isinstance(symbol_or_info, dict):
            # Already in dictionary format, ensure required fields exist
            symbol_info = symbol_or_info.copy()
            if 'symbol' not in symbol_info:
                raise ValueError("Symbol dictionary must contain 'symbol' key")
            if 'exchange' not in symbol_info and exchange:
                symbol_info['exchange'] = exchange
            if 'instrument_type' not in symbol_info:
                # Default to EQUITY if not specified
                symbol_info['instrument_type'] = 'EQUITY'
            return symbol_info
        else:
            # Convert string symbol to standardized dict
            if not exchange:
                raise ValueError("Exchange must be provided when symbol is a string")
            return {
                'symbol': str(symbol_or_info),
                'exchange': exchange,
                'instrument_type': 'EQUITY'  # Default type
            }
            
    def _process_pending_subscriptions(self) -> None:
        """
        Process any subscriptions that were queued while the connection was being established.
        This method is called after the WebSocket connection is fully established and authenticated.
        """
        if not self._pending_subscriptions:
            return
            
        self.logger.info(f"Processing {len(self._pending_subscriptions)} pending subscriptions")
        
        # Process each queued subscription
        for symbol_info, mode, depth_level in self._pending_subscriptions:
            try:
                self.logger.info(f"Processing queued subscription: {symbol_info} in {mode} mode")
                result = self.subscribe(symbol_info, mode=mode, depth_level=depth_level)
                if result.get('status') != 'success':
                    self.logger.error(f"Failed to process queued subscription for {symbol_info}: {result.get('message')}")
            except Exception as e:
                self.logger.error(f"Error processing queued subscription {symbol_info}: {str(e)}", exc_info=True)
        
        # Clear the queue after processing
        self._pending_subscriptions.clear()
        self.logger.info("Finished processing pending subscriptions")
    
    # --- Internal WebSocket Event Handlers ---
    def _on_ws_open(self, ws_client_instance):
        """
        Callback when WebSocket connection is opened.
        """
        self.logger.info("Adapter: WebSocket connection opened by client.")
        # Reset connection state
        self._connection_acknowledged = False

    def _on_ws_message(self, ws_client_instance, message: Dict[str, Any]):
        """
        Callback when a message is received from the WebSocket.
        
        Args:
            ws_client_instance: The WebSocket client instance
            message: The received message as a dictionary
        """
        if not message or not isinstance(message, dict):
            self.logger.warning("Received invalid message (not a dict)")
            return
            
        self.logger.debug(f"Adapter received message: {message}")
        msg_type = message.get('t')
        
        try:
            # Handle connection acknowledgment
            if msg_type == 'ck':  # Connection acknowledgment
                self._handle_connection_acknowledgment(message)
            # Handle order update
            elif msg_type == 'om':
                self.logger.debug(f"Received order update: {message}")
                # Extract the order data from the 'o' field if it exists
                order_data = message.get('o', message)
                self._handle_order_message(order_data)
                
                # Also forward to order update callback if set
                if self.on_order_update_callback:
                    try:
                        self.on_order_update_callback(order_data)
                    except Exception as e:
                        self.logger.error(f"Error in on_order_update_callback: {e}", exc_info=True)
                        
            # Handle subscription acknowledgments
            elif msg_type == 'ok':
                self.logger.debug(f"Received subscription ack: {message}")
                self._handle_subscription_ack(message)
                
            # Handle unsubscription acknowledgments
            elif msg_type == 'uok':
                self.logger.debug(f"Received unsubscription ack: {message}")
                self._handle_unsubscription_ack(message)
                
            # Handle touchline data
            elif msg_type == 'tf':
                self.logger.debug(f"Received touchline feed: {message}")
                self._handle_touchline_feed(message)
                
            # Handle depth data
            elif msg_type == 'df':
                self.logger.debug(f"Received depth feed: {message}")
                self._handle_depth_feed(message)
                
            # Log unhandled message types
            else:
                self.logger.debug(f"Unhandled message type: {msg_type}, content: {message}")
                
        except Exception as e:
            self.logger.error(f"Error processing message: {e}", exc_info=True)
            if self.on_adapter_error_callback:
                self.on_adapter_error_callback(f"Error processing message: {e}")
    
    def _handle_connection_acknowledgment(self, message: Dict[str, Any]) -> None:
        """Handle connection acknowledgment messages."""
        status = message.get('s')
        if status == 'OK':
            self.logger.info("Adapter: Connection Acknowledged by server (ck OK). Adapter is fully connected.")
            self.connection_acknowledged = True
            self._connection_acknowledged = True
            self.is_active = True
            
            # Process any pending subscriptions
            self._process_pending_subscriptions()
            
            # Resubscribe to any instruments that were subscribed before reconnection
            self._resubscribe_all()
            
            # Notify that the adapter is now fully connected
            if self.on_adapter_connect_callback:
                try:
                    self.on_adapter_connect_callback()
                except Exception as e:
                    self.logger.error(f"Error in on_adapter_connect_callback: {e}", exc_info=True)
            
            # Publish connection status via ZMQ if available
            self._publish_connection_status(True)
            
        else:
            error_msg = f"Connection not acknowledged by server: {message}"
            self.logger.error(error_msg)
            if self.on_adapter_error_callback:
                self.on_adapter_error_callback(error_msg)
            
            # Publish connection error
            self._publish_error(error_msg)
    
    def _publish_connection_status(self, is_connected: bool) -> None:
        """Publish connection status to ZMQ and other channels."""
        try:
            # Publish to ZMQ publisher if available
            if hasattr(self, 'zmq_publisher') and self.zmq_publisher:
                self.zmq_publisher.publish('connection_status', {
                    'status': 'connected' if is_connected else 'disconnected',
                    'broker': 'flattrade',
                    'timestamp': datetime.now().isoformat()
                })
            
            # Also publish via socket if available
            if hasattr(self, 'socket') and self.socket:
                topic = f"{self.broker_name}.{self.user_id}.connection_status"
                data = {
                    'status': 'connected' if is_connected else 'disconnected',
                    'acknowledged': is_connected,
                    'timestamp': datetime.now().isoformat()
                }
                self.socket.send_multipart([
                    topic.encode('utf-8'),
                    json.dumps(data).encode('utf-8')
                ])
                self.logger.debug(f"Published connection status to ZMQ topic {topic}")
                
        except Exception as e:
            self.logger.error(f"Error publishing connection status: {e}", exc_info=True)
    
    def _publish_error(self, error_msg: str) -> None:
        """Publish error message to ZMQ and other channels."""
        try:
            # Publish to ZMQ publisher if available
            if hasattr(self, 'zmq_publisher') and self.zmq_publisher:
                self.zmq_publisher.publish('error', {
                    'error': error_msg,
                    'broker': 'flattrade',
                    'timestamp': datetime.now().isoformat()
                })
            
            # Also publish via socket if available
            if hasattr(self, 'socket') and self.socket:
                topic = f"{self.broker_name}.{self.user_id}.error"
                self.socket.send_multipart([
                    topic.encode('utf-8'),
                    json.dumps({'error': error_msg}).encode('utf-8')
                ])
                
        except Exception as e:
            self.logger.error(f"Error publishing error to ZMQ: {e}", exc_info=True)
    
    def _handle_order_update_message(self, message: Dict[str, Any]) -> None:
        """Handle order update messages."""
        # Process with the new handler
        self._handle_order_update(message)
        
        # Also handle with the old format for backward compatibility
        if self.on_order_update_callback:
            try:
                self.on_order_update_callback(message)
            except Exception as e:
                self.logger.error(f"Error in on_order_update_callback: {e}", exc_info=True)
                
        # Publish order update via ZMQ if available
        if hasattr(self, 'socket') and self.socket and hasattr(self, 'broker_name') and hasattr(self, 'user_id'):
            try:
                openalgo_order = flattrade_mapping.map_websocket_order_update_to_openalgo_order(message)
                if openalgo_order:
                    topic = f"{self.broker_name}.{self.user_id}.orders"
                    self.socket.send_string(f"{topic} {json.dumps(openalgo_order)}")
                    self.logger.debug(f"Published order update to ZMQ topic {topic}")
            except Exception as e:
                self.logger.error(f"Error processing/dispatching order update via ZMQ: {e}", exc_info=True)
    
    def _handle_order_update(self, message: Dict[str, Any]) -> None:
        """
        Handle order update messages from Flattrade WebSocket.
        
        Args:
            message: The order update message
        """
        try:
            order_data = message.get('o', {})
            if not order_data:
                self.logger.warning("Received empty order update message")
                return
                
            # Log the raw order update for debugging
            self.logger.debug(f"Processing order update: {order_data}")
            
            # Map Flattrade order fields to OpenAlgo standard format
            mapped_order = {
                'order_id': order_data.get('norenordno'),
                'exchange_order_id': order_data.get('exchordid'),
                'tradingsymbol': order_data.get('tsym'),
                'exchange': order_data.get('exch'),
                'transaction_type': order_data.get('trantype'),
                'order_type': order_data.get('prctyp'),
                'product': order_data.get('prd'),
                'status': order_data.get('status'),
                'price': order_data.get('prc'),
                'trigger_price': order_data.get('trgprc'),
                'quantity': order_data.get('qty'),
                'filled_quantity': order_data.get('fillshares', '0'),
                'average_price': order_data.get('avgprc'),
                'order_timestamp': order_data.get('norentm'),
                'exchange_timestamp': order_data.get('exch_tm'),
                'broker_timestamp': datetime.now().isoformat(),
                'message': order_data.get('rejreason', '').strip() or 'Success',
                'disclosed_quantity': order_data.get('dscqty', '0'),
                'parent_order_id': order_data.get('prctranstype')
            }
            
            # Call the order update callback if set
            if self.on_order_update_callback:
                try:
                    self.logger.debug(f"Forwarding order update to callback: {mapped_order}")
                    self.on_order_update_callback(mapped_order)
                except Exception as e:
                    self.logger.error(f"Error in on_order_update_callback: {e}", exc_info=True)
            
            # Publish to ZMQ if configured
            if self.zmq_publisher:
                try:
                    self.zmq_publisher.publish('order_updates', mapped_order)
                except Exception as e:
                    self.logger.error(f"Error publishing order update to ZMQ: {e}", exc_info=True)
            
            # Log successful processing
            self.logger.debug(f"Successfully processed order update for order ID: {mapped_order.get('order_id')}")
                    
        except Exception as e:
            self.logger.error(f"Error processing order update: {e}", exc_info=True)
    
    def _handle_subscription_ack(self, message: Dict[str, Any]) -> None:
        """Handle subscription acknowledgment messages"""
        try:
            # Extract subscription details
            sub_type = message.get('t')
            status = message.get('s')
            
            if status != 'OK':
                error_msg = f"Subscription failed: {message.get('message', 'Unknown error')}"
                self.logger.error(error_msg)
                if self.on_adapter_error_callback:
                    self.on_adapter_error_callback(error_msg)
                return
                
            # Log successful subscription
            if sub_type == 't':
                self.logger.info(f"Successfully subscribed to touchline: {message.get('k')}")
            elif sub_type == 'd':
                self.logger.info(f"Successfully subscribed to depth: {message.get('k')}")
            elif sub_type == 'o':
                self.logger.info(f"Successfully subscribed to order updates for account: {message.get('actid')}")
                
        except Exception as e:
            self.logger.error(f"Error processing subscription ack: {e}", exc_info=True)
    
    def _handle_unsubscription_ack(self, message: Dict[str, Any]) -> None:
        """Handle unsubscription acknowledgment messages"""
        try:
            # Extract unsubscription details
            sub_type = message.get('t')
            status = message.get('s')
            
            if status != 'OK':
                error_msg = f"Unsubscription failed: {message.get('message', 'Unknown error')}"
                self.logger.error(error_msg)
                if self.on_adapter_error_callback:
                    self.on_adapter_error_callback(error_msg)
                return
                
            # Log successful unsubscription
            if sub_type == 'ut':
                self.logger.info(f"Successfully unsubscribed from touchline: {message.get('k')}")
            elif sub_type == 'ud':
                self.logger.info(f"Successfully unsubscribed from depth: {message.get('k')}")
            elif sub_type == 'uo':
                self.logger.info(f"Successfully unsubscribed from order updates for account: {message.get('actid')}")
                
        except Exception as e:
            self.logger.error(f"Error processing unsubscription ack: {e}", exc_info=True)
    
    def _handle_touchline_feed(self, message: Dict[str, Any]) -> None:
        """Handle touchline feed messages"""
        try:
            # Extract tick data
            token = message.get('tk')
            tick_data = message.get('lp', {})
            
            if not token or not tick_data:
                return
            
            # Initialize mapped_tick with basic info
            mapped_tick = {
                'token': token,
                'broker_timestamp': datetime.now().isoformat()
            }
            
            # Handle case where tick_data is a string (just the last price)
            if isinstance(tick_data, (int, float, str)):
                mapped_tick['last_price'] = float(tick_data)
                # Try to get other fields from the message directly
                mapped_tick.update({
                    'last_traded_quantity': message.get('ltq'),
                    'average_traded_price': message.get('atp'),
                    'volume_traded': message.get('v'),
                    'total_buy_quantity': message.get('tbq'),
                    'total_sell_quantity': message.get('tsq'),
                    'open_price': message.get('o'),
                    'high_price': message.get('h'),
                    'low_price': message.get('l'),
                    'close_price': message.get('c'),
                    'exchange_timestamp': message.get('tt')
                })
            # Handle case where tick_data is a dictionary
            elif isinstance(tick_data, dict):
                mapped_tick.update({
                    'last_price': tick_data.get('lp'),
                    'last_traded_quantity': tick_data.get('ltq'),
                    'average_traded_price': tick_data.get('atp'),
                    'volume_traded': tick_data.get('v'),
                    'total_buy_quantity': tick_data.get('tbq'),
                    'total_sell_quantity': tick_data.get('tsq'),
                    'open_price': tick_data.get('o'),
                    'high_price': tick_data.get('h'),
                    'low_price': tick_data.get('l'),
                    'close_price': tick_data.get('c'),
                    'exchange_timestamp': tick_data.get('tt')
                })
            else:
                self.logger.warning(f"Unexpected tick_data type: {type(tick_data)}")
                return
            
            # Clean up None values
            mapped_tick = {k: v for k, v in mapped_tick.items() if v is not None}
            
            # Forward to callback if set
            if self.on_tick_callback:
                try:
                    self.on_tick_callback(mapped_tick)
                except Exception as e:
                    self.logger.error(f"Error in on_tick_callback: {e}", exc_info=True)
            
            # Publish to ZMQ if configured
            if hasattr(self, 'socket') and self.socket:
                try:
                    # Add broker name to the tick data
                    mapped_tick['broker'] = 'flattrade'
                    # Publish with topic 'flattrade.ticks' as first part of multipart message
                    self.socket.send_multipart([
                        b'flattrade.ticks',
                        json.dumps(mapped_tick).encode('utf-8')
                    ])
                except Exception as e:
                    self.logger.error(f"Error publishing tick to ZMQ: {e}", exc_info=True)
                    
        except Exception as e:
            self.logger.error(f"Error processing touchline feed: {e}", exc_info=True)
    
    def _handle_depth_feed(self, message: Dict[str, Any]) -> None:
        """Handle depth feed messages"""
        try:
            # Extract depth data
            token = message.get('tk')
            depth_data = message.get('depth', {})
            
            if not token or not depth_data:
                return
                
            # Map to standard depth format
            mapped_depth = {
                'token': token,
                'bids': [],
                'asks': [],
                'exchange_timestamp': depth_data.get('tt'),
                'broker_timestamp': datetime.now().isoformat()
            }
            
            # Process bids and asks
            for i in range(1, 6):
                bid_price = depth_data.get(f'bp{i}')
                bid_qty = depth_data.get(f'bq{i}')
                ask_price = depth_data.get(f'sp{i}')
                ask_qty = depth_data.get(f'sq{i}')
                
                if bid_price and bid_qty:
                    mapped_depth['bids'].append({
                        'price': bid_price,
                        'quantity': bid_qty,
                        'orders': 1  # Default value, as Flattrade doesn't provide this
                    })
                    
                if ask_price and ask_qty:
                    mapped_depth['asks'].append({
                        'price': ask_price,
                        'quantity': ask_qty,
                        'orders': 1  # Default value, as Flattrade doesn't provide this
                    })
            
            # Forward to callback if set (using tick callback for depth as well)
            if self.on_tick_callback:
                try:
                    self.on_tick_callback({
                        'token': token,
                        'depth': mapped_depth,
                        'broker_timestamp': datetime.now().isoformat()
                    })
                except Exception as e:
                    self.logger.error(f"Error in on_tick_callback for depth: {e}", exc_info=True)
            
            # Publish to ZMQ if configured
            if hasattr(self, 'socket') and self.socket:
                try:
                    # Add broker name to the depth data
                    mapped_depth['broker'] = 'flattrade'
                    # Publish with topic 'flattrade.depth' as first part of multipart message
                    self.socket.send_multipart([
                        b'flattrade.depth',
                        json.dumps(mapped_depth).encode('utf-8')
                    ])
                except Exception as e:
                    self.logger.error(f"Error publishing depth to ZMQ: {e}", exc_info=True)
                    
            # Publish connection status via ZMQ if socket is available
            if hasattr(self, 'socket') and self.socket and hasattr(self, 'broker_name') and hasattr(self, 'user_id'):
                try:
                    topic = f"{self.broker_name}.{self.user_id}.connection_status"
                    data = {'status': 'connected', 'acknowledged': True}
                    self.socket.send_multipart([
                        topic.encode('utf-8'),
                        json.dumps(data).encode('utf-8')
                    ])
                    self.logger.debug(f"Published connection status to ZMQ topic {topic}")
                except Exception as e:
                    self.logger.error(f"Error publishing connection status: {e}", exc_info=True)
                    
        except Exception as e:
            self.logger.error(f"Error processing depth feed: {e}", exc_info=True)
            
    def _handle_order_message(self, message: Dict[str, Any]) -> None:
        """Handle order update messages"""
        try:
            # Log the raw order update for debugging
            self.logger.debug(f"Processing order update: {message}")
            
            # Map Flattrade order fields to OpenAlgo standard format
            mapped_order = {
                'order_id': message.get('norenordno'),
                'exchange_order_id': message.get('exchordid'),
                'tradingsymbol': message.get('tsym'),
                'exchange': message.get('exch'),
                'transaction_type': message.get('trantype'),
                'order_type': message.get('prctyp'),
                'product': message.get('prd'),
                'status': message.get('status'),
                'price': message.get('prc'),
                'trigger_price': message.get('trgprc'),
                'quantity': message.get('qty'),
                'filled_quantity': message.get('fillshares'),
                'average_price': message.get('avgprc'),
                'order_timestamp': message.get('norentm'),
                'exchange_timestamp': message.get('exch_tm'),
                'message': message.get('rejreason') or message.get('rejreason'),
                'broker_timestamp': datetime.now().isoformat(),
                'raw_data': message  # Include raw message for reference
            }
            
            # Clean up None values
            mapped_order = {k: v for k, v in mapped_order.items() if v is not None}
            
            # Forward to order update callback if set
            if self.on_order_update_callback:
                try:
                    self.on_order_update_callback(mapped_order)
                except Exception as e:
                    self.logger.error(f"Error in on_order_update_callback: {e}", exc_info=True)
            
            # Publish to ZMQ if configured
            if hasattr(self, 'socket') and self.socket:
                try:
                    topic = f"{self.broker_name}.{self.user_id}.orders"
                    self.socket.send_string(f"{topic} {json.dumps(mapped_order)}")
                    self.logger.debug(f"Published order update to ZMQ topic {topic}")
                except Exception as e:
                    self.logger.error(f"Error publishing order update to ZMQ: {e}", exc_info=True)
            
            # Log successful processing
            self.logger.debug(f"Successfully processed order update for order ID: {mapped_order.get('order_id')}")
                
        except Exception as e:
            error_msg = f"Error processing order update: {e}"
            self.logger.error(error_msg, exc_info=True)
            if self.on_adapter_error_callback:
                self.on_adapter_error_callback(error_msg)
    
    def _handle_acknowledgment(self, message: Dict[str, Any]) -> None:
        """Handle acknowledgment messages"""
        ack_type = message.get('t', 'unknown')
        self.logger.info(f"Received ACK for {ack_type}: {message}")
        
        # Add specific logic for different acknowledgment types if needed
        if ack_type in [FlattradeWebSocketClient.TYPE_ORDER_UPDATE_ACK, 
                       FlattradeWebSocketClient.TYPE_SUBSCRIBE_ACK]:
            # Handle subscription success
            pass
        elif ack_type in [FlattradeWebSocketClient.TYPE_UNSUBSCRIBE_ORDER_UPDATE_ACK,
                         FlattradeWebSocketClient.TYPE_UNSUBSCRIBE_ACK]:
            # Handle unsubscription success
            pass

    def _on_ws_error(self, ws_client_instance, error):
        logger.error(f"Adapter: WebSocket error: {error}", exc_info=isinstance(error, Exception))
        self.connected = False # Update base class connected status
        self.connection_acknowledged = False
        # No direct on_adapter_error_callback; proxy manager handles/logs errors.
        # Publish an error event via ZMQ if desired
        # topic = f"{self.broker_name}.{self.user_id}.error"
        # self.socket.send_string(f"{topic} {json.dumps({'error_message': str(error)})}")
        # Consider if disconnect should be called or if FlattradeWebSocketClient handles it.
        # If it's a connection-breaking error, _on_ws_close will likely be called too.

    def _on_ws_close(self, ws_client_instance, status_code, reason):
        logger.info(f"Adapter: WebSocket connection closed. Status: {status_code}, Reason: {reason}")
        
        # Update connection state under lock and clear subscriptions
        was_connected = False
        with self._connection_lock:
            was_connected = self.is_active or self.connected
            self.is_active = False
            self.connected = False
            self.connection_acknowledged = False
            self.order_updates_subscribed = False
            
            # Clear subscription tracking
            self.subscribed_instruments.clear()
            self.flattrade_token_to_details.clear()
        
        # Only trigger callbacks if we were actually connected
        if was_connected:
            # Call the disconnect callback if set
            if self.on_adapter_disconnect_callback:
                self.on_adapter_disconnect_callback()
            
            # Publish disconnection status via ZMQ
            try:
                topic = f"{self.broker_name}.{self.user_id}.connection_status"
                data = {'status': 'disconnected', 'code': status_code, 'reason': reason}
                self.socket.send_multipart([
                    topic.encode('utf-8'),
                    json.dumps(data).encode('utf-8')
                ])
                logger.debug(f"Published disconnection status to ZMQ topic {topic}")
            except Exception as e:
                logger.error(f"Error publishing disconnection status: {e}", exc_info=True)
        
        logger.info("Adapter: WebSocket connection cleanup complete.")
        
        # Reset subscriptions state for clarity, actual resubscribe on next connect
        # self.subscribed_scrips.clear()
        # self.order_updates_subscribed = False

    def _resubscribe_all(self):
        """Internal method to re-apply known subscriptions after a reconnect."""
        if not self.ws_client or not self.connection_acknowledged:
            self.logger.warning("Adapter not ready for resubscription.")
            return

        self.logger.info("Attempting to resubscribe to all previously subscribed items...")
        
        # Market Data
        scrips_to_resubscribe_touchline = []
        scrips_to_resubscribe_depth = []

        with self.lock: # Iterate over a copy if modifying during iteration, but here we just read
            for scrip, modes in self.subscribed_instruments.items():
                if modes.get("touchline"):
                    scrips_to_resubscribe_touchline.append(scrip)
                if modes.get("depth"):
                    scrips_to_resubscribe_depth.append(scrip)
        
        if scrips_to_resubscribe_touchline:
            self.logger.info(f"Resubscribing to touchline for: {scrips_to_resubscribe_touchline}")
            self.ws_client.subscribe_touchline(scrips_to_resubscribe_touchline)
        
        if scrips_to_resubscribe_depth:
            self.logger.info(f"Resubscribing to depth for: {scrips_to_resubscribe_depth}")
            self.ws_client.subscribe_depth(scrips_to_resubscribe_depth)

        # Order Updates
        if self.order_updates_subscribed: # Check the flag
            self.logger.info("Resubscribing to order updates.")
            self.ws_client.subscribe_order_updates()
        
        self.logger.info("Resubscription process completed.")

    # --- Setters for application callbacks ---
    def set_on_tick_callback(self, callback: Callable[[Dict[str, Any]], None]):
        self.on_tick_callback = callback
    
    def set_on_order_update_callback(self, callback: Callable[[Dict[str, Any]], None]):
        self.on_order_update_callback = callback

    def set_on_adapter_connect_callback(self, callback: Callable[[], None]):
        self.on_adapter_connect_callback = callback

    def set_on_adapter_disconnect_callback(self, callback: Callable[[], None]):
        self.on_adapter_disconnect_callback = callback
        
    def set_on_adapter_error_callback(self, callback: Callable[[str], None]):
        self.on_adapter_error_callback = callback

# Example usage when run directly
if __name__ == "__main__":
    import sys
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler()
        ]
    )
    
    logger = logging.getLogger("FlattradeAdapterTest")
    
    # Create an instance of the adapter
    adapter = FlattradeStreamAdapter()
    
    # Define test callbacks
    def my_test_tick_handler(tick_data: Dict[str, Any]):
        logger.info(f"TICK: {tick_data}")
    
    def my_test_order_handler(order_data: Dict[str, Any]):
        logger.info(f"ORDER UPDATE: {order_data}")
    
    def my_adapter_connect_handler():
        logger.info("MAIN_TEST_CONNECT_HANDLER: Adapter connected and acknowledged by server!")
        logger.info("Attempting to subscribe to market data and order updates...")
        
        # Example subscription - adjust as needed
        symbol_info = {
            'symbol': 'NIFTY',
            'exchange': 'NSE_INDEX',
            'instrument_type': 'INDEX'
        }
        
        # Subscribe to market data
        sub_market_status = adapter.subscribe(symbol_info, mode="touchline")
        if sub_market_status.get('status') == 'success':
            logger.info(f"Market data subscription request sent.")
        else:
            logger.error(f"Market data subscription failed: {sub_market_status.get('message')}")
    
    def my_adapter_disconnect_handler():
        logger.info("MAIN_TEST_DISCONNECT_HANDLER: Adapter disconnected.")
    
    def my_adapter_error_handler(error_message: str):
        logger.error(f"MAIN_TEST_ERROR_HANDLER: Adapter reported error: {error_message}")
    
    # Set up callbacks
    adapter.set_on_tick_callback(my_test_tick_handler)
    adapter.set_on_order_update_callback(my_test_order_handler)
    adapter.set_on_adapter_connect_callback(my_adapter_connect_handler)
    adapter.set_on_adapter_disconnect_callback(my_adapter_disconnect_handler)
    adapter.set_on_adapter_error_callback(my_adapter_error_handler)
    
    # Initialize the adapter
    init_status = adapter.initialize(
        broker_name="flattrade",
        user_id=os.getenv("USER_ID"),
        auth_data={
            # Add any required auth data here
        }
    )
    
    if init_status.get('status') != 'success':
        logger.critical(f"Adapter initialization failed: {init_status.get('message')}")
        sys.exit(1)
    
    # Connect and run
    try:
        connect_status = adapter.connect()
        if connect_status.get('status') != 'success':
            logger.critical(f"Adapter connection failed: {connect_status.get('message')}")
            sys.exit(1)
        
        logger.info("Adapter connect() called. Waiting for events... Press Ctrl+C to exit.")
        
        while True:
            time.sleep(1)
    
    except KeyboardInterrupt:
        logger.info("Ctrl+C received. Shutting down...")
    except Exception as e:
        logger.critical(f"An unexpected error occurred: {e}", exc_info=True)
    finally:
        logger.info("Disconnecting adapter...")
        if hasattr(adapter, 'ws_client') and adapter.ws_client:
            disconnect_status = adapter.disconnect()
            if disconnect_status.get('status') == 'success':
                logger.info("Adapter disconnected successfully.")
            else:
                logger.error(f"Adapter disconnection failed: {disconnect_status.get('message')}")
        else:
            logger.warning("Adapter or ws_client not available for disconnection.")
        logger.info("Flattrade WebSocket Adapter test script finished.")

