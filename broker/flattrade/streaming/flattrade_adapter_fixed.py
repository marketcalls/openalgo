# c:\Users\Karthik\Downloads\openalgo-main\broker\flattrade\streaming\flattrade_adapter.py

import logging
import os
import sys
import threading
import time
from datetime import datetime
import json  # For ZMQ publishing
from typing import Callable, Dict, Any, List, Optional, Union, Tuple, Set

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from database.token_db import get_token  # May need for instrument token resolution
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
    # Define constants for subscription types if needed, e.g.
    MODE_TOUCHLINE = "touchline"
    MODE_DEPTH = "depth"

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

    def subscribe(self, symbol_or_info, exchange: str = None, mode = "touchline", depth_level: int = 1):
        """
        Subscribe to market data.
        
        Can be called in two ways:
        1. With a symbol_info dict: subscribe(symbol_info, mode, depth_level)
        2. With individual params: subscribe(symbol, exchange, mode, depth_level)
        
        Args:
            symbol_or_info: Either a symbol string or a dict with symbol info
            exchange: Exchange code (required if symbol_or_info is a string)
            mode: Subscription mode (1 or "touchline" for LTP, 2 or "quote" for full quote, 3 or "depth" for market depth)
            depth_level: Depth level (default: 1, not used for Flattrade)
        """
        # Map numeric modes to string modes for backward compatibility
        if mode == 1 or mode == "1":
            mode = "touchline"
        elif mode == 2 or mode == "2":
            mode = "quote"
        elif mode == 3 or mode == "3":
            mode = "depth"
        elif mode == 4 or mode == "4":
            mode = "depth"  # For backward compatibility with some systems that use 4 for depth
            
        # Validate mode - Flattrade supports 'touchline' (t) and 'depth' (d) modes
        if mode not in ["touchline", "quote", "depth"]:
            error_msg = f"Unsupported subscription mode: {mode}. Must be one of: 'touchline', 'quote', 'depth'"
            self.logger.error(error_msg)
            return {'status': 'error', 'message': error_msg}
        
        # Map 'quote' mode to 'touchline' as Flattrade doesn't have a separate quote mode
        # The touchline mode provides LTP and other basic quote data
        flattrade_mode = "touchline" if mode in ["touchline", "quote"] else "depth"
            
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
            return {
                'type': 'subscribe', 
                'status': 'queued', 
                'message': 'Subscription queued, will be processed when connection is ready', 
                'symbol': symbol_info, 
                'mode': mode,
                'broker': 'flattrade'
            }

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
                    return {
                        'type': 'subscribe',
                        'status': 'success', 
                        'message': 'Subscribed to order updates.',
                        'broker': 'flattrade'
                    }
                else:
                    self.logger.info("Already subscribed to order updates.")
                    return {
                        'type': 'subscribe',
                        'status': 'success', 
                        'message': 'Already subscribed to order updates.',
                        'broker': 'flattrade'
                    }

            # Handle instrument subscriptions (touchline, depth)
            # Construct a unique key for _subscriptions that includes mode
            subscription_key = f"{flattrade_token}|{flattrade_mode}"
            if subscription_key in self._subscriptions:
                msg = f"Already subscribed to {flattrade_token} with mode {flattrade_mode}."
                self.logger.info(msg)
                return {
                    'type': 'subscribe',
                    'status': 'success', 
                    'message': msg,
                    'broker': 'flattrade'
                }

            try:
                if flattrade_mode == "touchline":
                    self.logger.info(f"Subscribing to touchline for {flattrade_token}")
                    self.ws_client.subscribe_touchline([flattrade_token])
                elif flattrade_mode == "depth":
                    self.logger.info(f"Subscribing to depth for {flattrade_token}")
                    self.ws_client.subscribe_depth([flattrade_token])
                else:
                    msg = f"Unsupported subscription mode: {flattrade_mode}"
                    self.logger.error(msg)
                    return {
                        'type': 'subscribe',
                        'status': 'error', 
                        'message': msg,
                        'broker': 'flattrade'
                    }
                
                # Store the original mode in the subscription for reference
                self._subscriptions.add(subscription_key)
                # Also store the mapping from original mode to Flattrade mode
                self._subscriptions.add(f"{flattrade_token}|{mode}")
                
                msg = f"Subscription request sent for {flattrade_token}, mode {flattrade_mode}."
                self.logger.info(msg)
                
                # Return a response that matches the expected format
                return {
                    'type': 'subscribe',
                    'status': 'partial',
                    'subscriptions': [{
                        'symbol': symbol_info.get('symbol'),
                        'exchange': symbol_info.get('exchange'),
                        'status': 'success',
                        'message': f'Subscribed to {flattrade_mode} mode',
                        'broker': 'flattrade'
                    }],
                    'message': 'Subscription processing complete',
                    'broker': 'flattrade'
                }
                
            except Exception as e:
                msg = f"Error subscribing to {flattrade_token}, mode {flattrade_mode}: {e}"
                self.logger.error(msg, exc_info=True)
                return {
                    'type': 'subscribe',
                    'status': 'error',
                    'message': msg,
                    'broker': 'flattrade'
                }

    def unsubscribe(self, symbol_or_info, exchange: str = None, mode = "touchline") -> Dict[str, Any]:
        """
        Unsubscribe from market data.
        
        Can be called in two ways:
        1. With a symbol_info dict: unsubscribe(symbol_info, mode)
        2. With individual params: unsubscribe(symbol, exchange, mode)
        
        Args:
            symbol_or_info: Either a symbol string or a dict with symbol info
            exchange: Exchange code (required if symbol_or_info is a string)
            mode: Subscription mode (1 or "touchline" for LTP, 2 or "quote" for full quote, 3 or "depth" for market depth)
            
        Returns:
            Dict[str, Any]: Status of the unsubscription request
        """
        # Map numeric modes to string modes for backward compatibility
        if mode == 1 or mode == "1":
            mode = "touchline"
        elif mode == 2 or mode == "2":
            mode = "quote"
        elif mode == 3 or mode == "3":
            mode = "depth"
        elif mode == 4 or mode == "4":
            mode = "depth"  # For backward compatibility with some systems that use 4 for depth
            
        # Validate mode - Flattrade supports 'touchline' (t) and 'depth' (d) modes
        if mode not in ["touchline", "quote", "depth"]:
            error_msg = f"Unsupported unsubscription mode: {mode}. Must be one of: 'touchline', 'quote', 'depth'"
            self.logger.error(error_msg)
            return {'status': 'error', 'message': error_msg}
            
        # Map 'quote' mode to 'touchline' as Flattrade doesn't have a separate quote mode
        flattrade_mode = "touchline" if mode in ["touchline", "quote"] else "depth"
            
        # Handle both calling patterns
        if isinstance(symbol_or_info, dict):
            symbol_info = symbol_or_info
        else:
            symbol = symbol_or_info
            symbol_info = {
                'symbol': symbol,
                'exchange': exchange or 'NSE',  # Default to NSE if not provided
                'instrument_type': 'EQUITY'  # Default, can be overridden if needed
            }
            
        with self.lock:
            # Check connection state
            if not hasattr(self, 'is_active') or not self.is_active:
                msg = "WebSocket client not connected. Call connect() first."
                self.logger.error(f"Unsubscribe failed: {msg} Symbol: {symbol_info}, Mode: {mode}")
                return {
                    'type': 'unsubscribe',
                    'status': 'error', 
                    'message': msg,
                    'symbol': symbol_info,
                    'mode': mode,
                    'broker': 'flattrade'
                }
                
            if not self.ws_client:
                msg = "WebSocket client not initialized."
                self.logger.error(f"Unsubscribe failed: {msg} Symbol: {symbol_info}, Mode: {mode}")
                return {
                    'type': 'unsubscribe',
                    'status': 'error', 
                    'message': msg,
                    'symbol': symbol_info,
                    'mode': mode,
                    'broker': 'flattrade'
                }

            flattrade_token = self._resolve_symbol_to_flattrade_token(symbol_info)

            if not flattrade_token:
                msg = f"Failed to resolve symbol info to Flattrade token for unsubscribe: {symbol_info}"
                self.logger.error(msg)
                return {
                    'type': 'unsubscribe',
                    'status': 'error', 
                    'message': msg,
                    'symbol': symbol_info,
                    'mode': mode,
                    'broker': 'flattrade'
                }

            # Handle order updates unsubscription
            if flattrade_token == "ORDERS_PSEUDO_TOKEN":
                if "ORDERS" in self._subscriptions:
                    self.logger.info("Unsubscribing from order updates.")
                    self.ws_client.unsubscribe_order_updates()
                    self._subscriptions.remove("ORDERS")
                    return {
                        'type': 'unsubscribe',
                        'status': 'success', 
                        'message': 'Unsubscribed from order updates.',
                        'broker': 'flattrade'
                    }
                else:
                    self.logger.info("Not currently subscribed to order updates.")
                    return {
                        'type': 'unsubscribe',
                        'status': 'success', 
                        'message': 'Not currently subscribed to order updates.',
                        'broker': 'flattrade'
                    }

            # Handle instrument unsubscriptions
            # Check both the original mode and the mapped Flattrade mode
            subscription_key = f"{flattrade_token}|{flattrade_mode}"
            original_subscription_key = f"{flattrade_token}|{mode}"
            
            if subscription_key not in self._subscriptions and original_subscription_key not in self._subscriptions:
                msg = f"Not currently subscribed to {flattrade_token} with mode {mode} (or mapped mode {flattrade_mode})."
                self.logger.info(msg)
                return {
                    'type': 'unsubscribe',
                    'status': 'success', 
                    'message': msg,
                    'symbol': symbol_info,
                    'mode': mode,
                    'broker': 'flattrade'
                }

            try:
                if flattrade_mode == "touchline":
                    self.logger.info(f"Unsubscribing from touchline for {flattrade_token}")
                    self.ws_client.unsubscribe_touchline([flattrade_token])
                elif flattrade_mode == "depth":
                    self.logger.info(f"Unsubscribing from depth for {flattrade_token}")
                    self.ws_client.unsubscribe_depth([flattrade_token])
                else:
                    msg = f"Unsupported unsubscription mode: {flattrade_mode}"
                    self.logger.error(msg)
                    return {
                        'type': 'unsubscribe',
                        'status': 'error', 
                        'message': msg,
                        'symbol': symbol_info,
                        'mode': mode,
                        'broker': 'flattrade'
                    }
                
                # Remove both the original and mapped subscription keys if they exist
                if subscription_key in self._subscriptions:
                    self._subscriptions.remove(subscription_key)
                if original_subscription_key in self._subscriptions:
                    self._subscriptions.remove(original_subscription_key)
                
                msg = f"Unsubscribed from {flattrade_token}, mode {flattrade_mode}."
                self.logger.info(msg)
                
                return {
                    'type': 'unsubscribe',
                    'status': 'success',
                    'subscriptions': [{
                        'symbol': symbol_info.get('symbol'),
                        'exchange': symbol_info.get('exchange'),
                        'status': 'success',
                        'message': f'Unsubscribed from {flattrade_mode} mode',
                        'broker': 'flattrade'
                    }],
                    'message': 'Unsubscription processing complete',
                    'broker': 'flattrade'
                }
                
            except Exception as e:
                msg = f"Error unsubscribing from {flattrade_token}, mode {flattrade_mode}: {e}"
                self.logger.error(msg, exc_info=True)
                return {
                    'type': 'unsubscribe',
                    'status': 'error',
                    'message': msg,
                    'symbol': symbol_info,
                    'mode': mode,
                    'broker': 'flattrade'
                }
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
        """Process any subscriptions that were queued while the connection was being established.

        This method is called after the WebSocket connection is fully established and authenticated.
        """
        if not hasattr(self, '_pending_subscriptions') or not self._pending_subscriptions:
            return
            
        self.logger.info(
            "Processing %d pending subscriptions",
            len(self._pending_subscriptions)
        )
        
        # Process each queued subscription
        for subscription in self._pending_subscriptions:
            try:
                symbol_info, mode, depth_level = subscription
                self.logger.info(
                    "Processing queued subscription: %s in %s mode",
                    symbol_info, mode
                )
                result = self.subscribe(symbol_info, mode=mode, depth_level=depth_level)
                if result.get('status') != 'success':
                    self.logger.error(
                        "Failed to process queued subscription for %s: %s",
                        symbol_info, result.get('message')
                    )
            except Exception as e:
                self.logger.error(
                    "Error processing queued subscription %s: %s",
                    str(subscription), str(e),
                    exc_info=True
                )
        
        # Clear the queue after processing
        self._pending_subscriptions.clear()
        self.logger.info("Finished processing pending subscriptions")
    
    # --- Internal WebSocket Event Handlers ---
    def _on_ws_open(self, ws_client_instance: Any) -> None:
        """Callback when WebSocket connection is opened.

        Args:
            ws_client_instance: The WebSocket client instance that was opened.
        """
        self.logger.info("Adapter: WebSocket connection opened by client.")
        # Reset connection state
        self._connection_acknowledged = False
        self.connected = True

    def _on_ws_message(self, ws_client_instance: Any, message: Dict[str, Any]) -> None:
        """Handle incoming WebSocket messages.
        
        Args:
            ws_client_instance: The WebSocket client instance that received the message
            message: The received message as a dictionary
        """
        self.logger.debug("Adapter received message: %s", message)
        msg_type = message.get('t')
        
        # Handle connection acknowledgment
        if msg_type == 'ck':  # Connection acknowledgment
            status = message.get('s')
            if status == 'OK':
                self.logger.info(
                    'Adapter: Connection Acknowledged by server (ck OK). '
                    'Adapter is fully connected.'
                )
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
                        self.logger.error(
                            'Error in on_adapter_connect_callback: %s',
                            str(e),
                            exc_info=True
                        )
                
                # Publish connection status via ZMQ
                try:
                    topic = f"{self.broker_name}.{self.user_id}.connection_status"
                    data = {'status': 'connected', 'acknowledged': True}
                    self.socket.send_multipart([
                        topic.encode('utf-8'),
                        json.dumps(data).encode('utf-8')
                    ])
                    self.logger.debug(
                        'Published connection status to ZMQ topic %s',
                        topic
                    )
                except Exception as e:
                    self.logger.error(
                        'Error publishing connection status: %s',
                        str(e),
                        exc_info=True
                    )
            else:
                error_msg = message.get('emsg', 'No error message')
                self.logger.error(
                    'Adapter: Connection failed with status %s: %s',
                    status,
                    error_msg
                )
                self._connection_acknowledged = False
                self.is_active = False
                if self.on_adapter_error_callback:
                    self.on_adapter_error_callback(
                        f'Connection failed: {error_msg}'
                    )
        
        # Handle tick data
        elif msg_type == 'tk':  # Tick data
            if self.on_tick_callback:
                try:
                    self.on_tick_callback(message)
                except Exception as e:
                    self.logger.error(
                        'Error in on_tick_callback: %s',
                        str(e),
                        exc_info=True
                    )
        
        # Handle order updates
                try:
                    self.on_tick_callback(openalgo_tick)
                except Exception as e:
                    self.logger.error(
                        'Error in on_tick_callback: %s',
                        str(e),
                        exc_info=True
                    )
                else:
                    self.logger.warning(
                        'Mapped depth data missing symbol/exchange, cannot publish: %s',
                        openalgo_depth_data
                    )
                    
            except Exception as e:
                self.logger.error(
                    'Error processing depth update: %s',
                    str(e),
                    exc_info=True
                )
            
            try:
                if self.on_tick_callback and openalgo_tick:
                    self.on_tick_callback(openalgo_tick)
                elif openalgo_tick:
                    self.logger.warning(
                        'Mapped tick missing symbol/exchange, cannot publish: %s',
                        openalgo_tick
                    )
            except Exception as e:
                self.logger.error(
                    'Error processing touchline message: %s',
                    str(e),
                    exc_info=True
                )
        """Handle WebSocket error events.
        
        Args:
            ws_client_instance: The WebSocket client instance that encountered the error
            error: The exception that was raised
        """
        self.logger.error(
            "Adapter: WebSocket error: %s",
            str(error),
            exc_info=True
        )
        self.connected = False  # Update base class connected status
        self.connection_acknowledged = False
        
        # Notify error callback if set
        if self.on_adapter_error_callback:
            try:
                self.on_adapter_error_callback(str(error))
            except Exception as e:
                logger.error(
                    "Error in on_adapter_error_callback: %s",
                    e,
                    exc_info=True
                )
        # Publish an error event via ZMQ if desired
        # topic = f"{self.broker_name}.{self.user_id}.error"
        # self.socket.send_string(f"{topic} {json.dumps({'error_message': str(error)})}")
        # Consider if disconnect should be called or if FlattradeWebSocketClient handles it.
        # If it's a connection-breaking error, _on_ws_close will likely be called too.

    def _on_ws_close(self, ws_client_instance: Any, status_code: int, reason: str) -> None:
        """Handle WebSocket connection close event.
        
        Args:
            ws_client_instance: The WebSocket client instance that was closed
            status_code: The close status code
            reason: The reason for the close
        """
        logger.info(
            "Adapter: WebSocket connection closed. Status: %s, Reason: %s",
            status_code,
            reason
        )
        
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
                self.logger.debug(
                    "Published disconnection status to ZMQ topic %s",
                    topic
                )
            except Exception as e:
                self.logger.error(
                    "Error publishing disconnection status: %s",
                    str(e),
                    exc_info=True
                )
        
        self.logger.info("Adapter: WebSocket connection cleanup complete.")

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
            self.logger.info(
                "Resubscribing to touchline for: %s",
                scrips_to_resubscribe_touchline
            )
            self.ws_client.subscribe_touchline(scrips_to_resubscribe_touchline)
        
        if scrips_to_resubscribe_depth:
            self.logger.info(
                "Resubscribing to depth for: %s",
                scrips_to_resubscribe_depth
            )
            self.ws_client.subscribe_depth(scrips_to_resubscribe_depth)

        # Order Updates
        if self.order_updates_subscribed: # Check the flag
            self.logger.info("Resubscribing to order updates.")
            self.ws_client.subscribe_order_updates()
        
        self.logger.info("Resubscription process completed.")

    # --- Setters for application callbacks ---
    def set_on_tick_callback(self, callback):
        """Set the callback for tick data.
        
        Args:
            callback: A function that takes a dictionary parameter and returns None
        """
        self.on_tick_callback = callback
    
    def set_on_order_update_callback(self, callback):
        """Set the callback for order updates.
        
        Args:
            callback: A function that takes a dictionary parameter and returns None
        """
        self.on_order_update_callback = callback

    def set_on_adapter_connect_callback(self, callback):
        """Set the callback for adapter connection events.
        
        Args:
            callback: A function that takes no parameters and returns None
        """
        self.on_adapter_connect_callback = callback

    def set_on_adapter_disconnect_callback(self, callback):
        """Set the callback for adapter disconnection events.
        
        Args:
            callback: A function that takes no parameters and returns None
        """
        self.on_adapter_disconnect_callback = callback
        
    def set_on_adapter_error_callback(self, callback):
        """Set the callback for adapter errors.
        
        Args:
            callback: A function that takes a string parameter (error message) and returns None
        """
        self.on_adapter_error_callback = callback

# Example usage when run directly
if __name__ == "__main__":
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
    def my_test_tick_handler(tick_data: Dict[str, Any]) -> None:
        """Handle incoming tick data.
        
        Args:
            tick_data: Dictionary containing tick data
        """
        logger.info("TICK: %s", tick_data)
    
    def my_test_order_handler(order_data: Dict[str, Any]) -> None:
        """Handle order update events.
        
        Args:
            order_data: Dictionary containing order update data
        """
        logger.info("ORDER UPDATE: %s", order_data)
    
    def my_adapter_connect_handler() -> None:
        """Handle successful adapter connection."""
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
            logger.info("Market data subscription request sent.")
        else:
            logger.error("Market data subscription failed: %s", sub_market_status.get('message'))
    
    def my_adapter_disconnect_handler() -> None:
        """Handle adapter disconnection."""
        logger.info("MAIN_TEST_DISCONNECT_HANDLER: Adapter disconnected.")
    
    def my_adapter_error_handler(error_message: str) -> None:
        """Handle adapter errors.
        
        Args:
            error_message: Error message from the adapter
        """
        logger.error(
            "MAIN_TEST_ERROR_HANDLER: Adapter reported error: %s",
            error_message
        )
    
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
        logger.critical(
            "Adapter initialization failed: %s",
            init_status.get('message')
        )
        sys.exit(1)
    
    # Connect and run
    try:
        connect_status = adapter.connect()
        if connect_status.get('status') != 'success':
            logger.critical(
                "Adapter connection failed: %s",
                connect_status.get('message')
            )
            sys.exit(1)
        
        logger.info("Adapter connect() called. Waiting for events... Press Ctrl+C to exit.")
        
        while True:
            time.sleep(1)
    
    except KeyboardInterrupt:
        logger.info("Ctrl+C received. Shutting down...")
    except Exception as e:
        logger.critical(
            "An unexpected error occurred: %s",
            str(e),
            exc_info=True
        )
    finally:
        logger.info("Disconnecting adapter...")
        if hasattr(adapter, 'ws_client') and adapter.ws_client:
            disconnect_status = adapter.disconnect()
            if disconnect_status.get('status') == 'success':
                logger.info("Adapter disconnected successfully.")
            else:
                logger.error(
                    "Adapter disconnection failed: %s"
                    % disconnect_status.get('message')
                )
        else:
            logger.warning("Adapter or ws_client not available for disconnection.")
        logger.info("Flattrade WebSocket Adapter test script finished.")

# End of file
