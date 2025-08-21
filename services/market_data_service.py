"""
Market data service for handling real-time streaming data.
Provides caching, transformation, and broadcasting capabilities.
"""

import threading
import time
from typing import Dict, List, Any, Optional, Callable, Set
from collections import defaultdict
from datetime import datetime
from utils.logging import get_logger
from .websocket_service import register_market_data_callback, get_websocket_connection

# Initialize logger
logger = get_logger(__name__)

class MarketDataService:
    """
    Singleton service for managing market data across the application.
    Handles caching, transformations, and broadcasting to multiple consumers.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self._initialized = True
        self.data_lock = threading.Lock()
        
        # Market data cache structure:
        # {
        #   'NSE:RELIANCE': {
        #     'ltp': {'value': 2500.50, 'timestamp': 1234567890},
        #     'quote': {'open': 2490, 'high': 2510, ...},
        #     'depth': {'buy': [...], 'sell': [...]},
        #     'last_update': 1234567890
        #   }
        # }
        self.market_data_cache = {}
        
        # Subscribers for real-time updates
        # {event_type: {callback_id: callback_function}}
        self.subscribers = defaultdict(dict)
        self.subscriber_id_counter = 0
        
        # User-specific data tracking
        # {user_id: {symbol_key: last_access_time}}
        self.user_access_tracking = defaultdict(dict)
        
        # Performance metrics
        self.metrics = {
            'total_updates': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'last_cleanup': time.time()
        }
        
        # Start cleanup thread
        self.cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self.cleanup_thread.start()
        
        logger.info("MarketDataService initialized")
    
    def process_market_data(self, data: Dict[str, Any]) -> None:
        """
        Process incoming market data from WebSocket
        
        Args:
            data: Market data dictionary from WebSocket
        """
        try:
            symbol = data.get('symbol')
            exchange = data.get('exchange')
            mode = data.get('mode')
            market_data = data.get('data', {})
            
            if not symbol or not exchange:
                return
                
            symbol_key = f"{exchange}:{symbol}"
            timestamp = int(time.time())
            
            with self.data_lock:
                # Initialize cache entry if needed
                if symbol_key not in self.market_data_cache:
                    self.market_data_cache[symbol_key] = {
                        'last_update': timestamp
                    }
                
                cache_entry = self.market_data_cache[symbol_key]
                
                # Update based on mode
                if mode == 1:  # LTP
                    cache_entry['ltp'] = {
                        'value': market_data.get('ltp', 0),
                        'timestamp': market_data.get('timestamp', timestamp),
                        'volume': market_data.get('volume', 0)
                    }
                elif mode == 2:  # Quote
                    cache_entry['quote'] = {
                        'open': market_data.get('open', 0),
                        'high': market_data.get('high', 0),
                        'low': market_data.get('low', 0),
                        'close': market_data.get('close', 0),
                        'ltp': market_data.get('ltp', 0),
                        'volume': market_data.get('volume', 0),
                        'timestamp': market_data.get('timestamp', timestamp)
                    }
                    # Also update LTP from quote
                    cache_entry['ltp'] = {
                        'value': market_data.get('ltp', 0),
                        'timestamp': market_data.get('timestamp', timestamp),
                        'volume': market_data.get('volume', 0)
                    }
                elif mode == 3:  # Depth
                    cache_entry['depth'] = {
                        'buy': market_data.get('depth', {}).get('buy', []),
                        'sell': market_data.get('depth', {}).get('sell', []),
                        'ltp': market_data.get('ltp', 0),
                        'timestamp': market_data.get('timestamp', timestamp)
                    }
                
                cache_entry['last_update'] = timestamp
                self.metrics['total_updates'] += 1
            
            # Broadcast to subscribers
            self._broadcast_update(symbol_key, mode, data)
            
        except Exception as e:
            logger.exception(f"Error processing market data: {e}")
    
    def get_ltp(self, symbol: str, exchange: str) -> Optional[Dict[str, Any]]:
        """
        Get latest LTP for a symbol
        
        Args:
            symbol: Trading symbol
            exchange: Exchange name
            
        Returns:
            LTP data dictionary or None
        """
        symbol_key = f"{exchange}:{symbol}"
        
        with self.data_lock:
            self.metrics['cache_hits'] += 1
            if symbol_key in self.market_data_cache:
                return self.market_data_cache[symbol_key].get('ltp')
            
        self.metrics['cache_misses'] += 1
        return None
    
    def get_quote(self, symbol: str, exchange: str) -> Optional[Dict[str, Any]]:
        """
        Get latest quote for a symbol
        
        Args:
            symbol: Trading symbol
            exchange: Exchange name
            
        Returns:
            Quote data dictionary or None
        """
        symbol_key = f"{exchange}:{symbol}"
        
        with self.data_lock:
            self.metrics['cache_hits'] += 1
            if symbol_key in self.market_data_cache:
                return self.market_data_cache[symbol_key].get('quote')
            
        self.metrics['cache_misses'] += 1
        return None
    
    def get_market_depth(self, symbol: str, exchange: str) -> Optional[Dict[str, Any]]:
        """
        Get market depth for a symbol
        
        Args:
            symbol: Trading symbol
            exchange: Exchange name
            
        Returns:
            Market depth data dictionary or None
        """
        symbol_key = f"{exchange}:{symbol}"
        
        with self.data_lock:
            self.metrics['cache_hits'] += 1
            if symbol_key in self.market_data_cache:
                return self.market_data_cache[symbol_key].get('depth')
            
        self.metrics['cache_misses'] += 1
        return None
    
    def get_all_data(self, symbol: str, exchange: str) -> Dict[str, Any]:
        """
        Get all available data for a symbol
        
        Args:
            symbol: Trading symbol
            exchange: Exchange name
            
        Returns:
            All market data for the symbol
        """
        symbol_key = f"{exchange}:{symbol}"
        
        with self.data_lock:
            if symbol_key in self.market_data_cache:
                return dict(self.market_data_cache[symbol_key])
            
        return {}
    
    def get_multiple_ltps(self, symbols: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Get LTPs for multiple symbols
        
        Args:
            symbols: List of symbol dictionaries with 'symbol' and 'exchange' keys
            
        Returns:
            Dictionary mapping symbol_key to LTP data
        """
        result = {}
        
        with self.data_lock:
            for symbol_info in symbols:
                symbol = symbol_info.get('symbol')
                exchange = symbol_info.get('exchange')
                if symbol and exchange:
                    symbol_key = f"{exchange}:{symbol}"
                    if symbol_key in self.market_data_cache:
                        ltp_data = self.market_data_cache[symbol_key].get('ltp')
                        if ltp_data:
                            result[symbol_key] = ltp_data
        
        return result
    
    def subscribe_to_updates(self, event_type: str, callback: Callable, filter_symbols: Optional[Set[str]] = None) -> int:
        """
        Subscribe to market data updates
        
        Args:
            event_type: Type of update ('ltp', 'quote', 'depth', 'all')
            callback: Function to call with updates
            filter_symbols: Optional set of symbol keys to filter updates
            
        Returns:
            Subscriber ID for unsubscribing
        """
        with self.data_lock:
            self.subscriber_id_counter += 1
            subscriber_id = self.subscriber_id_counter
            
            self.subscribers[event_type][subscriber_id] = {
                'callback': callback,
                'filter': filter_symbols
            }
            
        logger.info(f"Added subscriber {subscriber_id} for {event_type} updates")
        return subscriber_id
    
    def unsubscribe_from_updates(self, subscriber_id: int) -> bool:
        """
        Unsubscribe from market data updates
        
        Args:
            subscriber_id: ID returned from subscribe_to_updates
            
        Returns:
            True if unsubscribed successfully
        """
        with self.data_lock:
            for event_type in self.subscribers:
                if subscriber_id in self.subscribers[event_type]:
                    del self.subscribers[event_type][subscriber_id]
                    logger.info(f"Removed subscriber {subscriber_id}")
                    return True
        
        return False
    
    def register_user_callback(self, username: str) -> bool:
        """
        Register market data callback for a specific user
        
        Args:
            username: Username
            
        Returns:
            Success status
        """
        def user_callback(data):
            try:
                self.process_market_data(data)
            except Exception as e:
                logger.error(f"Error processing market data in callback: {e}")
        
        return register_market_data_callback(username, user_callback)
    
    def track_user_access(self, user_id: int, symbol: str, exchange: str) -> None:
        """
        Track user access to market data for analytics
        
        Args:
            user_id: User ID
            symbol: Trading symbol
            exchange: Exchange name
        """
        symbol_key = f"{exchange}:{symbol}"
        timestamp = int(time.time())
        
        with self.data_lock:
            self.user_access_tracking[user_id][symbol_key] = timestamp
    
    def get_cache_metrics(self) -> Dict[str, Any]:
        """Get performance metrics"""
        with self.data_lock:
            total_requests = self.metrics['cache_hits'] + self.metrics['cache_misses']
            hit_rate = (self.metrics['cache_hits'] / total_requests * 100) if total_requests > 0 else 0
            
            return {
                'total_symbols': len(self.market_data_cache),
                'total_updates': self.metrics['total_updates'],
                'cache_hits': self.metrics['cache_hits'],
                'cache_misses': self.metrics['cache_misses'],
                'hit_rate': round(hit_rate, 2),
                'total_subscribers': sum(len(subs) for subs in self.subscribers.values())
            }
    
    def clear_cache(self, symbol: Optional[str] = None, exchange: Optional[str] = None) -> None:
        """
        Clear market data cache
        
        Args:
            symbol: Specific symbol to clear (optional)
            exchange: Exchange for the symbol (optional)
        """
        with self.data_lock:
            if symbol and exchange:
                symbol_key = f"{exchange}:{symbol}"
                if symbol_key in self.market_data_cache:
                    del self.market_data_cache[symbol_key]
                    logger.info(f"Cleared cache for {symbol_key}")
            else:
                self.market_data_cache.clear()
                logger.info("Cleared entire market data cache")
    
    def _broadcast_update(self, symbol_key: str, mode: int, data: Dict[str, Any]) -> None:
        """
        Broadcast updates to subscribers
        
        Args:
            symbol_key: Symbol key (exchange:symbol)
            mode: Update mode (1=LTP, 2=Quote, 3=Depth)
            data: Full data to broadcast
        """
        mode_to_event = {1: 'ltp', 2: 'quote', 3: 'depth'}
        event_type = mode_to_event.get(mode, 'all')
        
        # Broadcast to specific event subscribers
        with self.data_lock:
            subscribers = list(self.subscribers[event_type].values())
            all_subscribers = list(self.subscribers['all'].values())
        
        for subscriber in subscribers + all_subscribers:
            try:
                # Check filter
                if subscriber['filter'] and symbol_key not in subscriber['filter']:
                    continue
                    
                # Call the callback
                subscriber['callback'](data)
            except Exception as e:
                logger.error(f"Error in subscriber callback: {e}")
    
    def _cleanup_loop(self) -> None:
        """Background thread to clean up stale data"""
        while True:
            try:
                time.sleep(300)  # Run every 5 minutes
                
                current_time = time.time()
                stale_threshold = 3600  # 1 hour
                
                with self.data_lock:
                    # Clean up stale market data
                    stale_symbols = []
                    for symbol_key, data in self.market_data_cache.items():
                        if current_time - data.get('last_update', 0) > stale_threshold:
                            stale_symbols.append(symbol_key)
                    
                    for symbol_key in stale_symbols:
                        del self.market_data_cache[symbol_key]
                    
                    # Clean up old user access tracking
                    for user_id in list(self.user_access_tracking.keys()):
                        user_data = self.user_access_tracking[user_id]
                        stale_accesses = [
                            symbol_key for symbol_key, last_access 
                            in user_data.items() 
                            if current_time - last_access > stale_threshold
                        ]
                        for symbol_key in stale_accesses:
                            del user_data[symbol_key]
                        
                        if not user_data:
                            del self.user_access_tracking[user_id]
                    
                    self.metrics['last_cleanup'] = current_time
                
                if stale_symbols:
                    logger.info(f"Cleaned up {len(stale_symbols)} stale market data entries")
                    
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")


# Global instance
_market_data_service = MarketDataService()

# Convenience functions
def get_market_data_service() -> MarketDataService:
    """Get the global MarketDataService instance"""
    return _market_data_service

def get_ltp(symbol: str, exchange: str) -> Optional[Dict[str, Any]]:
    """Get LTP for a symbol"""
    return _market_data_service.get_ltp(symbol, exchange)

def get_quote(symbol: str, exchange: str) -> Optional[Dict[str, Any]]:
    """Get quote for a symbol"""
    return _market_data_service.get_quote(symbol, exchange)

def get_market_depth(symbol: str, exchange: str) -> Optional[Dict[str, Any]]:
    """Get market depth for a symbol"""
    return _market_data_service.get_market_depth(symbol, exchange)

def subscribe_to_market_updates(event_type: str, callback: Callable, filter_symbols: Optional[Set[str]] = None) -> int:
    """Subscribe to market data updates"""
    return _market_data_service.subscribe_to_updates(event_type, callback, filter_symbols)

def unsubscribe_from_market_updates(subscriber_id: int) -> bool:
    """Unsubscribe from market data updates"""
    return _market_data_service.unsubscribe_from_updates(subscriber_id)