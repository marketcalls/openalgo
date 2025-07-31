from utils.logging import get_logger
from database.token_db import get_token, get_brexchange
from database.symbol import SymToken

class ExchangeMapper:
    """Base class for mapping OpenAlgo exchange codes to broker-specific exchange types"""
    
    @staticmethod
    def get_exchange_type(exchange, broker):
        """
        Convert exchange code to broker-specific exchange type
        
        This is a base implementation that should be overridden by broker-specific mappers.
        
        Args:
            exchange (str): Exchange code (e.g., 'NSE', 'BSE')
            broker (str): Broker name
            
        Returns:
            int: Broker-specific exchange type
        """
        # This method should be implemented by broker-specific exchange mappers
        # Default to a common value (1 typically represents NSE in most brokers)
        return 1


class SymbolMapper:
    """Maps OpenAlgo symbols to broker-specific tokens"""
    
    logger = get_logger("symbol_mapper")
    
    @staticmethod
    def get_token_from_symbol(symbol, exchange):
        """
        Convert user-friendly symbol to broker-specific token
        
        Args:
            symbol (str): Trading symbol (e.g., 'RELIANCE')
            exchange (str): Exchange code (e.g., 'NSE', 'BSE')
            
        Returns:
            dict: Token data with 'token' and 'brexchange' or None if not found
        """
        try:
            # Get token from database
            token = get_token(symbol, exchange)
            brexchange = get_brexchange(symbol, exchange)
            
            if not token or not brexchange:
                SymbolMapper.logger.error(f"Symbol not found: {symbol}-{exchange}")
                return None
                
            return {
                'token': token,
                'brexchange': brexchange
            }
        except Exception as e:
            SymbolMapper.logger.exception(f"Error retrieving symbol: {e}")
            return None


class BrokerCapabilityRegistry:
    """
    Base class for broker capability registries
    
    This class defines the interface for broker-specific capability registries.
    Each broker should implement its own capability registry that can be queried
    for supported features.
    """
    
    @classmethod
    def get_supported_depth_levels(cls, broker, exchange):
        """
        Get supported depth levels for a broker and exchange
        
        Args:
            broker (str): Broker name
            exchange (str): Exchange code
            
        Returns:
            list: List of supported depth levels
        """
        # This method should be implemented by broker-specific capability registries
        # By default, assume support for the standard 5-level depth
        return [5]
    
    @classmethod
    def is_depth_level_supported(cls, broker, exchange, depth_level):
        """
        Check if a depth level is supported for the given broker and exchange
        
        Args:
            broker (str): Broker name
            exchange (str): Exchange code
            depth_level (int): Requested depth level
            
        Returns:
            bool: True if supported, False otherwise
        """
        supported_depths = cls.get_supported_depth_levels(broker, exchange)
        return depth_level in supported_depths
    
    @classmethod
    def get_fallback_depth_level(cls, broker, exchange, requested_depth):
        """
        Get the best available depth level as a fallback
        
        Args:
            broker (str): Broker name
            exchange (str): Exchange code
            requested_depth (int): Requested depth level
            
        Returns:
            int: Highest supported depth level that is ≤ requested depth
        """
        supported_depths = cls.get_supported_depth_levels(broker, exchange)
        # Find the highest supported depth that's less than or equal to requested depth
        fallbacks = [d for d in supported_depths if d <= requested_depth]
        if fallbacks:
            return max(fallbacks)
        return 5  # Default to basic depth
