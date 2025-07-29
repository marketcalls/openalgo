from utils.logging import get_logger
import threading
import sys
import os
import json
import time
import uuid
from typing import Dict, Any, Optional
from collections import defaultdict
from broker.flattrade.streaming.flattrade_websocket import FlattradeWebSocket
from database.auth_db import get_auth_token
from database.token_db import get_token

sys.path.append(os.path.join(os.path.dirname(__file__), '../../../'))
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper
from .flattrade_mapping import FlattradeExchangeMapper, FlattradeCapabilityRegistry

class FlattradeWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Enhanced Flattrade WebSocket adapter with proper instance isolation and multi-client support"""

    def __init__(self):
        super().__init__()
        
        # Generate unique instance ID for complete isolation
        self.instance_id = str(uuid.uuid4())
        self.logger = get_logger(f"flattrade_websocket_adapter_{self.instance_id}")
        
        # Instance-specific state - completely isolated
        self._instance_state = {
            'ws_client': None,
            'user_id': None,
            'actid': None,
            'susertoken': None,
            'broker_name': "flattrade",
            'running': False,
            'connected': False,
            'subscriptions': {},  # {correlation_id: subscription_data}
            'token_symbol_map': {},  # {token: (symbol, exchange)}
            'market_data_cache': {},  # {token: latest_data}
            'active_subscriptions': {},  # {(symbol, exchange, mode): True/False}
            'connection_metadata': {
                'reconnect_attempts': 0,
                'max_reconnect_attempts': 5,
                'reconnect_delay': 2,
                'last_heartbeat': None
            }
        }
        
        # For backward compatibility, expose these as direct attributes
        self.subscriptions = self._instance_state['active_subscriptions']
        self.token_symbol_map = self._instance_state['token_symbol_map']
        self.connected = False
        self.running = False
        
        # Add this line to initialize snapshot storage
        self._market_snapshots = {}
        
        # Thread safety for this instance
        self._instance_lock = threading.RLock()
        self._reconnect_lock = threading.Lock()
        
        # Reconnection control flags
        self._reconnecting = False
        self._should_reconnect = True
        
        # Debug initialization
        self.logger.debug(f"Initialized Flattrade adapter instance: {self.instance_id}")
        self.debug_instance_state()

    def debug_instance_state(self):
        """Debug method to check instance state"""
        self.logger.debug(f"=== DEBUG INSTANCE STATE {self.instance_id} ===")
        self.logger.debug(f"token_symbol_map exists: {hasattr(self, 'token_symbol_map')}")
        self.logger.debug(f"subscriptions exists: {hasattr(self, 'subscriptions')}")
        self.logger.debug(f"_instance_state keys: {list(self._instance_state.keys())}")
        if hasattr(self, 'token_symbol_map'):
            self.logger.debug(f"token_symbol_map type: {type(self.token_symbol_map)}")
            self.logger.debug(f"token_symbol_map content: {self.token_symbol_map}")
        if hasattr(self, 'subscriptions'):
            self.logger.debug(f"subscriptions type: {type(self.subscriptions)}")
            self.logger.debug(f"subscriptions content: {self.subscriptions}")
        self.logger.debug(f"=== END DEBUG ===")

    def initialize(self, broker_name: str, user_id: str = None, auth_data: Optional[Dict[str, str]] = None) -> None:
        """Initialize connection with complete instance isolation"""
        with self._instance_lock:
            try:
                self._instance_state['broker_name'] = broker_name
                
                # Get credentials
                self._instance_state['user_id'] = os.getenv('BROKER_API_KEY', '').split(':::')[0]
                self._instance_state['actid'] = self._instance_state['user_id']
                
                if user_id:
                    self._instance_state['susertoken'] = get_auth_token(user_id)
                    
                if not self._instance_state['actid'] or not self._instance_state['susertoken']:
                    raise ValueError(f"Missing Flattrade credentials for instance {self.instance_id}")
                
                # Create isolated WebSocket client
                self._instance_state['ws_client'] = FlattradeWebSocket(
                    user_id=self._instance_state['user_id'],
                    actid=self._instance_state['actid'],
                    susertoken=self._instance_state['susertoken'],
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                    on_open=self._on_open
                )
                
                self.logger.debug(f"Instance {self.instance_id} initialized successfully")
                self.debug_instance_state()
                
            except Exception as e:
                self.logger.error(f"Failed to initialize instance {self.instance_id}: {e}")
                raise

    def connect(self) -> None:
        """Connect with enhanced error handling and state management"""
        with self._reconnect_lock:
            if not self._instance_state['ws_client']:
                raise RuntimeError(f"Instance {self.instance_id} not initialized")
            
            try:
                self._instance_state['running'] = True
                self._instance_state['connected'] = False
                self.running = True
                self._should_reconnect = True
                
                connected = self._instance_state['ws_client'].connect()
                if not connected:
                    self._instance_state['running'] = False
                    self.running = False
                    raise ConnectionError(f"Failed to connect instance {self.instance_id}")
                
                self._instance_state['connected'] = True
                self.connected = True
                self._instance_state['connection_metadata']['reconnect_attempts'] = 0
                self.logger.debug(f"Instance {self.instance_id} connected successfully")
                
            except Exception as e:
                self._instance_state['running'] = False
                self._instance_state['connected'] = False
                self.running = False
                self.connected = False
                self.logger.error(f"Connection failed for instance {self.instance_id}: {e}")
                raise

    def disconnect(self) -> None:
        """Clean disconnect with complete resource cleanup"""
        with self._instance_lock:
            self.logger.debug(f"Disconnecting instance {self.instance_id}")
            
            self._instance_state['running'] = False
            self.running = False
            self._should_reconnect = False
            
            # Cleanup WebSocket in background to avoid blocking
            if self._instance_state['ws_client']:
                def cleanup_websocket():
                    try:
                        self._instance_state['ws_client'].stop()
                    except Exception as e:
                        self.logger.error(f"Error stopping WebSocket for instance {self.instance_id}: {e}")
                    finally:
                        self._instance_state['ws_client'] = None
                
                # Run cleanup in background thread to avoid blocking
                threading.Thread(target=cleanup_websocket, daemon=True).start()
            
            # Cleanup ZeroMQ immediately
            self.cleanup_zmq()
            
            # Reset state immediately
            self._reset_instance_state()
            
            self.logger.debug(f"Instance {self.instance_id} disconnect initiated")

    def _reset_instance_state(self):
        """Reset all instance-specific state"""
        self._instance_state.update({
            'connected': False,
            'user_id': None,
            'actid': None,
            'susertoken': None,
            'subscriptions': {},
            'token_symbol_map': {},
            'market_data_cache': {},
            'active_subscriptions': {},
            'connection_metadata': {
                'reconnect_attempts': 0,
                'max_reconnect_attempts': 5,
                'reconnect_delay': 2,
                'last_heartbeat': None
            }
        })
        
        # Update direct attributes for backward compatibility
        self.subscriptions = self._instance_state['active_subscriptions']
        self.token_symbol_map = self._instance_state['token_symbol_map']
        self.connected = False
        self.running = False

    def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5) -> Dict[str, Any]:
        """Enhanced subscription with proper correlation tracking and multi-mode support"""
        with self._instance_lock:
            try:
                # Generate unique correlation ID for this instance
                correlation_id = f"{self.instance_id}_{symbol}_{exchange}_{mode}_{int(time.time())}"
                
                # Validate inputs
                if mode not in [1, 2, 3]:
                    return self._create_error_response(400, f"Invalid mode {mode}")
                
                # Get token information
                token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
                if not token_info:
                    return self._create_error_response(404, f"Token not found for {symbol}-{exchange}")
                
                token = token_info['token']
                brexchange = token_info['brexchange']
                flattrade_exchange = FlattradeExchangeMapper.to_flattrade_exchange(brexchange)
                scrip = f"{flattrade_exchange}|{token}"
                
                # Store subscription with correlation tracking
                subscription_data = {
                    'correlation_id': correlation_id,
                    'symbol': symbol,
                    'exchange': exchange,
                    'mode': mode,
                    'depth_level': depth_level,
                    'token': token,
                    'brexchange': brexchange,
                    'scrip': scrip,
                    'timestamp': time.time()
                }
                
                self._instance_state['subscriptions'][correlation_id] = subscription_data
                self._instance_state['token_symbol_map'][token] = (symbol, exchange)
                self._instance_state['active_subscriptions'][(symbol, exchange, mode)] = True
                
                # Update direct attributes for backward compatibility
                self.token_symbol_map[token] = (symbol, exchange)
                self.subscriptions[(symbol, exchange, mode)] = True
                
                # Subscribe via WebSocket
                if self._instance_state['connected'] and self._instance_state['ws_client']:
                    if mode in [1, 2]:
                        self._instance_state['ws_client'].subscribe_touchline(scrip)
                    elif mode == 3:
                        self._instance_state['ws_client'].subscribe_depth(scrip)
                
                self.logger.debug(f"Instance {self.instance_id} subscribed: {correlation_id}")
                self.logger.debug(f"[SUBSCRIPTION_DEBUG] Token {token} mapped to ({symbol}, {exchange})")
                
                return self._create_success_response(f"Subscribed {symbol}.{exchange} mode {mode}")
                
            except Exception as e:
                self.logger.error(f"Subscription failed for instance {self.instance_id}: {e}")
                return self._create_error_response(500, str(e))

    def unsubscribe(self, symbol: str, exchange: str, mode: int = 2) -> Dict[str, Any]:
        """Enhanced unsubscription with correlation cleanup"""
        with self._instance_lock:
            try:
                # Find matching subscription
                correlation_id = None
                for cid, sub in self._instance_state['subscriptions'].items():
                    if (sub['symbol'] == symbol and sub['exchange'] == exchange and sub['mode'] == mode):
                        correlation_id = cid
                        break
                
                if not correlation_id:
                    return self._create_error_response(404, f"No active subscription found")
                
                subscription_data = self._instance_state['subscriptions'][correlation_id]
                scrip = subscription_data['scrip']
                
                # Unsubscribe via WebSocket
                if self._instance_state['connected'] and self._instance_state['ws_client']:
                    if mode in [1, 2]:
                        self._instance_state['ws_client'].unsubscribe_touchline(scrip)
                    elif mode == 3:
                        self._instance_state['ws_client'].unsubscribe_depth(scrip)
                
                # Cleanup subscription data
                del self._instance_state['subscriptions'][correlation_id]
                self._instance_state['active_subscriptions'][(symbol, exchange, mode)] = False
                
                # Update direct attributes
                self.subscriptions[(symbol, exchange, mode)] = False
                
                # Remove token mapping if no other subscriptions use it
                token = subscription_data['token']
                if not any(sub['token'] == token for sub in self._instance_state['subscriptions'].values()):
                    self._instance_state['token_symbol_map'].pop(token, None)
                    self._instance_state['market_data_cache'].pop(token, None)
                    self.token_symbol_map.pop(token, None)
                
                self.logger.debug(f"Instance {self.instance_id} unsubscribed: {correlation_id}")
                return self._create_success_response(f"Unsubscribed {symbol}.{exchange} mode {mode}")
                
            except Exception as e:
                self.logger.error(f"Unsubscription failed for instance {self.instance_id}: {e}")
                return self._create_error_response(500, str(e))

    def _reconnect(self):
        """Enhanced reconnection with better state management"""
        with self._reconnect_lock:
            if not self._instance_state['running'] or not self._should_reconnect:
                self.logger.debug(f"Instance {self.instance_id} not running or shouldn't reconnect, skipping")
                return
            
            # Check if already reconnecting
            if self._reconnecting:
                self.logger.debug(f"Instance {self.instance_id} already reconnecting, skipping")
                return
            
            self._reconnecting = True
            
            try:
                metadata = self._instance_state['connection_metadata']
                if metadata['reconnect_attempts'] >= metadata['max_reconnect_attempts']:
                    self.logger.error(f"Max reconnect attempts reached for instance {self.instance_id}")
                    self._instance_state['running'] = False
                    self.running = False
                    return
                
                metadata['reconnect_attempts'] += 1
                delay = metadata['reconnect_delay'] * (2 ** (metadata['reconnect_attempts'] - 1))
                
                self.logger.warning(f"Instance {self.instance_id} reconnecting in {delay}s (attempt {metadata['reconnect_attempts']})")
                time.sleep(delay)
                
                # Ensure old client is completely stopped
                if self._instance_state['ws_client']:
                    try:
                        self._instance_state['ws_client'].stop()
                        time.sleep(1)  # Give it time to cleanup
                    except Exception as e:
                        self.logger.error(f"Error stopping old client for instance {self.instance_id}: {e}")
                
                # Recreate WebSocket client
                self._instance_state['ws_client'] = FlattradeWebSocket(
                    user_id=self._instance_state['user_id'],
                    actid=self._instance_state['actid'],
                    susertoken=self._instance_state['susertoken'],
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                    on_open=self._on_open
                )
                
                connected = self._instance_state['ws_client'].connect()
                if connected:
                    self._instance_state['connected'] = True
                    self.connected = True
                    metadata['reconnect_attempts'] = 0
                    self.logger.debug(f"Instance {self.instance_id} reconnected successfully")
                else:
                    self._instance_state['connected'] = False
                    self.connected = False
                    self.logger.error(f"Reconnection failed for instance {self.instance_id}")
                    
            except Exception as e:
                self._instance_state['connected'] = False
                self.connected = False
                self.logger.error(f"Reconnection failed for instance {self.instance_id}: {e}")
            finally:
                self._reconnecting = False

    def _resubscribe_all(self):
        """Resubscribe all active subscriptions after reconnect"""
        with self._instance_lock:
            subscriptions_by_mode = defaultdict(list)
            
            # Group subscriptions by mode
            for sub in self._instance_state['subscriptions'].values():
                subscriptions_by_mode[sub['mode']].append(sub['scrip'])
            
            # Resubscribe by mode
            for mode, scrips in subscriptions_by_mode.items():
                scrip_key = '#'.join(scrips)
                try:
                    if mode in [1, 2]:
                        self._instance_state['ws_client'].subscribe_touchline(scrip_key)
                    elif mode == 3:
                        self._instance_state['ws_client'].subscribe_depth(scrip_key)
                    
                    self.logger.debug(f"Instance {self.instance_id} resubscribed mode {mode}: {len(scrips)} subscriptions")
                except Exception as e:
                    self.logger.error(f"Resubscription failed for instance {self.instance_id} mode {mode}: {e}")

    def _on_open(self, ws):
        """WebSocket opened callback"""
        self.logger.debug(f"Instance {self.instance_id} WebSocket opened")
        try:
            self._resubscribe_all()
        except Exception as e:
            self.logger.error(f"Resubscription failed for instance {self.instance_id}: {e}")

    def _on_close(self, ws, close_status_code, close_msg):
        """WebSocket closed callback with better reconnection control"""
        self.logger.warning(f"Instance {self.instance_id} WebSocket closed: {close_status_code} - {close_msg}")
        self._instance_state['connected'] = False
        self.connected = False
        
        # Only reconnect if we're supposed to be running and not already reconnecting
        if (self._instance_state['running'] and self.running and self._should_reconnect and 
            not self._reconnecting):
            
            # Add a small delay to prevent immediate reconnection loops
            def delayed_reconnect():
                time.sleep(1)
                if self._instance_state['running'] and self.running and self._should_reconnect:
                    self._reconnect()
            
            threading.Thread(target=delayed_reconnect, daemon=True).start()

    def _on_error(self, ws, error):
        """WebSocket error callback with controlled reconnection"""
        self.logger.error(f"Instance {self.instance_id} WebSocket error: {error}")
        
        # Only trigger reconnection for actual connection errors, not during shutdown
        if (self._instance_state['running'] and self.running and self._should_reconnect and 
            not self._reconnecting):
            
            # Check if this is a connection-related error
            error_str = str(error).lower()
            if any(keyword in error_str for keyword in ['connection', 'remote host', 'network', 'timeout']):
                def delayed_reconnect():
                    time.sleep(2)  # Longer delay for errors
                    if self._instance_state['running'] and self.running and self._should_reconnect:
                        self._reconnect()
                
                threading.Thread(target=delayed_reconnect, daemon=True).start()

    def _on_message(self, ws, message):
        """Process incoming messages with proper snapshot management"""
        try:
            self.logger.debug(f"[RAW_MESSAGE] Instance {self.instance_id} received: {message}")
            
            data = json.loads(message)
            msg_type = data.get('t')
            
            if msg_type == 'ck':
                self.logger.debug(f"Instance {self.instance_id} auth ack: {data}")
                return
            
            # Check if this is a market data message
            if msg_type not in ('tf', 'tk', 'df', 'dk'):
                self.logger.debug(f"[UNKNOWN_MESSAGE] Instance {self.instance_id} unknown type {msg_type}: {data}")
                return
            
            token = data.get('tk')
            if not token:
                self.logger.warning(f"[NO_TOKEN] Instance {self.instance_id} message without token: {data}")
                return
            
            # Get token symbol mapping with fallback options
            token_symbol_map = getattr(self, 'token_symbol_map', {})
            if not token_symbol_map:
                token_symbol_map = self._instance_state.get('token_symbol_map', {})
            
            if token not in token_symbol_map:
                self.logger.warning(f"[UNSUBSCRIBED_TOKEN] Instance {self.instance_id} token {token} not in subscriptions")
                return
            
            symbol, exchange = token_symbol_map[token]
            self.logger.debug(f"[PROCESSING] Instance {self.instance_id} processing {msg_type} for {symbol}-{exchange} ({token})")
            
            # Find ALL active subscriptions for this symbol-exchange combination
            active_subscriptions = []
            subscriptions = getattr(self, 'subscriptions', {})
            if not subscriptions:
                subscriptions = self._instance_state.get('active_subscriptions', {})
            
            for (sym, exch, mode), active in subscriptions.items():
                if active and sym == symbol and exch == exchange:
                    active_subscriptions.append(mode)
            
            if not active_subscriptions:
                self.logger.warning(f"[NO_ACTIVE_SUBS] No active subscriptions found for {symbol}-{exchange}")
                return
            
            self.logger.debug(f"[MULTI_MODE] Processing {symbol}-{exchange} for modes: {active_subscriptions}")
            
            # **CRITICAL FIX: Handle snapshot management BEFORE processing modes**
            processed_data = self._update_market_snapshot(token, data, msg_type)
            
            # Process message for each active subscription mode
            for mode in active_subscriptions:
                self.logger.debug(f"[MODE_PROCESSING] {symbol}-{exchange} for mode {mode}")
                
                # Normalize data using the COMPLETE snapshot
                normalized_data = self._normalize_market_data(processed_data, msg_type, mode)
                normalized_data.update({
                    'symbol': symbol,
                    'exchange': exchange,
                    'timestamp': int(time.time() * 1000),
                    'instance_id': self.instance_id,
                    'token': token,
                    'message_type': msg_type
                })
                
                # Cache latest data
                cache_key = f"{token}_{mode}"
                self._instance_state['market_data_cache'][cache_key] = normalized_data
                
                # Determine topic based on subscription mode
                if mode == 3:
                    mode_str = 'DEPTH'
                elif mode == 2:
                    mode_str = 'QUOTE'
                else:  # mode == 1
                    mode_str = 'LTP'
                
                topic = f"{exchange}_{symbol}_{mode_str}"
                
                # **CRITICAL: Log what we're publishing for debugging**
                self.logger.debug(f"[PUBLISH] Mode {mode} -> Topic: {topic} | LTP: {normalized_data.get('ltp', 0)} | Open: {normalized_data.get('open', 0)}")
                
                # Publish market data
                self.publish_market_data(topic, normalized_data)
                
        except json.JSONDecodeError as e:
            self.logger.error(f"Instance {self.instance_id} JSON decode error: {e}, message: {message}")
        except Exception as e:
            self.logger.error(f"Instance {self.instance_id} message processing error: {e}", exc_info=True)

    def _update_market_snapshot(self, token: str, data: dict, msg_type: str) -> dict:
        """
        Unified snapshot management for all market data messages
        Maintains complete snapshots and merges incremental updates
        """
        # Initialize snapshot storage if not exists
        if not hasattr(self, '_market_snapshots'):
            self._market_snapshots = {}
        
        if msg_type in ('tk', 'dk'):
            # Acknowledgment messages - store complete snapshot
            self._market_snapshots[token] = data.copy()
            self.logger.debug(f"[SNAPSHOT] Stored complete snapshot for token {token} from {msg_type}")
            return data
        
        elif msg_type in ('tf', 'df'):
            # Incremental updates - merge with existing snapshot
            snapshot = self._market_snapshots.get(token, {})
            
            if not snapshot:
                # No existing snapshot - treat this update as acknowledgment
                self.logger.warning(f"[SNAPSHOT] No existing snapshot for token {token}, treating {msg_type} as acknowledgment")
                self._market_snapshots[token] = data.copy()
                return data
            
            # Merge incremental data with snapshot
            updated_fields = []
            for field, value in data.items():
                if field in ['t', 'e', 'tk']:  # Always update metadata
                    snapshot[field] = value
                    continue
                    
                # Only update if value is meaningful (not empty/zero for price fields)
                if self._is_meaningful_value(field, value):
                    snapshot[field] = value
                    updated_fields.append(field)
            
            # Update stored snapshot
            self._market_snapshots[token] = snapshot
            
            if updated_fields:
                self.logger.debug(f"[SNAPSHOT] Updated fields for token {token}: {updated_fields}")
            
            return snapshot
        
        else:
            # Unknown message type - return as is
            return data

    def _is_meaningful_value(self, field: str, value) -> bool:
        """Check if a field value is meaningful and should be updated"""
        if value is None or value == '' or value == '-':
            return False
        
        # Price fields - don't update if zero
        price_fields = ['lp', 'o', 'h', 'l', 'c', 'ap', 'bp1', 'bp2', 'bp3', 'bp4', 'bp5', 
                        'sp1', 'sp2', 'sp3', 'sp4', 'sp5', 'uc', 'lc']
        if field in price_fields:
            try:
                return float(value) != 0.0
            except (ValueError, TypeError):
                return False
        
        # Volume/quantity fields - allow zero as it's meaningful
        volume_fields = ['v', 'bq1', 'bq2', 'bq3', 'bq4', 'bq5', 
                        'sq1', 'sq2', 'sq3', 'sq4', 'sq5', 'oi', 'poi']
        if field in volume_fields:
            return True  # All volume values are meaningful, including 0
        
        # Percentage and other fields
        return True

    def _normalize_market_data(self, data: Dict[str, Any], msg_type: str, mode: int = None) -> Dict[str, Any]:
        """Simplified data normalization without complex snapshot logic"""
        def safe_float(value, default=0.0):
            if value is None or value == '' or value == '-':
                return default
            try:
                return float(value)
            except (ValueError, TypeError):
                return default
        
        def safe_int(value, default=0):
            if value is None or value == '' or value == '-':
                return default
            try:
                return int(float(value))
            except (ValueError, TypeError):
                return default
        
        # Base data
        result = {
            'last_price': safe_float(data.get('lp')),
            'ltp': safe_float(data.get('lp')),
            'volume': safe_int(data.get('v')),
            'open': safe_float(data.get('o')),
            'high': safe_float(data.get('h')),
            'low': safe_float(data.get('l')),
            'close': safe_float(data.get('c')),
            'percent_change': safe_float(data.get('pc')),
            'average_price': safe_float(data.get('ap')),
            'mode': 'DEPTH' if mode == 3 else ('QUOTE' if mode == 2 else 'LTP'),
            'message_type': msg_type
        }
        
        # Add quote-specific data for modes 2 and 3
        if mode in [2, 3]:
            result.update({
                'best_bid_price': safe_float(data.get('bp1')),
                'best_bid_qty': safe_int(data.get('bq1')),
                'best_ask_price': safe_float(data.get('sp1')),
                'best_ask_qty': safe_int(data.get('sq1')),
                'open_interest': safe_int(data.get('oi')),
                'prev_open_interest': safe_int(data.get('poi'))
            })
        
        # Add depth data for depth messages
        if mode == 3 and msg_type in ('df', 'dk'):
            result['depth'] = {
                'buy': [
                    {
                        'price': safe_float(data.get(f'bp{i}')),
                        'quantity': safe_int(data.get(f'bq{i}')),
                        'orders': safe_int(data.get(f'bo{i}'))
                    }
                    for i in range(1, 6)
                ],
                'sell': [
                    {
                        'price': safe_float(data.get(f'sp{i}')),
                        'quantity': safe_int(data.get(f'sq{i}')),
                        'orders': safe_int(data.get(f'so{i}'))
                    }
                    for i in range(1, 6)
                ]
            }
        
        return result

    def publish_market_data(self, topic, data):
        """Enhanced publish with better error handling"""
        try:
            # Ensure data is properly serializable
            if not isinstance(data, dict):
                self.logger.error(f"Data must be dict, got {type(data)}: {data}")
                return
            
            # Serialize data to JSON to check for issues
            try:
                json_data = json.dumps(data, default=str)
            except (TypeError, ValueError) as e:
                self.logger.error(f"Data serialization error: {e}, data: {data}")
                return
            
            # Send topic and data as separate parts
            if hasattr(self, 'zmq_socket') and self.zmq_socket:
                self.zmq_socket.send_multipart([
                    topic.encode('utf-8'),
                    json_data.encode('utf-8')
                ])
                self.logger.debug(f"Published to topic: {topic}")
            else:
                # Fallback to parent method
                super().publish_market_data(topic, data)
                
        except Exception as e:
            self.logger.error(f"Error publishing market data: {e}")

    def __del__(self):
        """Destructor ensures cleanup"""
        if hasattr(self, '_instance_state') and self._instance_state.get('running'):
            self.disconnect()
