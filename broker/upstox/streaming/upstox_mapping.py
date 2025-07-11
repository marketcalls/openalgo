# broker/upstox/streaming/upstox_mapping.py
from typing import Dict, Set
import logging

class UpstoxExchangeMapper:
    """Maps between OpenAlgo exchange codes and Upstox specific exchange types"""
    
    # Exchange type mapping for Upstox broker
    # Format: {OpenAlgo_Exchange: Upstox_Exchange_Code}
    EXCHANGE_TYPES = {
        # NSE Segments
        'NSE': 'NSE_EQ',      # NSE Cash Market
        'NFO': 'NSE_FO',      # NSE F&O
        'NSE_INDEX': 'NSE_INDEX',  # NSE Index
        'CDS': 'NSE_CD',      # NSE Currency Derivatives
        
        # BSE Segments
        'BSE': 'BSE_EQ',      # BSE Cash Market
        'BFO': 'BSE_FO',      # BSE F&O
        'BSE_INDEX': 'BSE_INDEX',  # BSE Index
        
        # MCX Segment
        'MCX': 'MCX_FO',      # MCX F&O
        
        # Broker specific codes
        'NSE_EQ': 'NSE_EQ',   # NSE Cash Market
        'NSE_FO': 'NSE_FO',   # NSE F&O
        'NSE_CD': 'NSE_CD',   # NSE Currency Derivatives
        'BSE_EQ': 'BSE_EQ',   # BSE Cash Market
        'BSE_FO': 'BSE_FO',   # BSE F&O
        'MCX_FO': 'MCX_FO'    # MCX F&O
    }
    
    # Reverse mapping for converting Upstox exchange codes to OpenAlgo format
    # Format: {Upstox_Exchange_Code: OpenAlgo_Exchange}
    REVERSE_EXCHANGE_TYPES = {
        'NSE_EQ': 'NSE',      # NSE Cash Market
        'NSE_FO': 'NFO',      # NSE F&O
        'NSE_CD': 'CDS',      # NSE Currency Derivatives
        'BSE_EQ': 'BSE',      # BSE Cash Market
        'BSE_FO': 'BFO',      # BSE F&O
        'MCX_FO': 'MCX',      # MCX F&O
        'NSE_INDEX': 'NSE_INDEX',  # NSE Index
        'BSE_INDEX': 'BSE_INDEX'   # BSE Index
    }
    
    @staticmethod
    def get_exchange_type(exchange):
        """
        Convert OpenAlgo exchange code to Upstox specific exchange type
        
        Args:
            exchange: Exchange code (e.g., 'NSE', 'BSE', 'NFO')
            
        Returns:
            str: Exchange type code for Upstox API
        """
        if exchange is None:
            logging.warning("Exchange is None, defaulting to NSE_EQ")
            return 'NSE_EQ'
            
        # Convert to string and uppercase
        exchange = str(exchange).upper().strip()
        
        # Try to find the exchange in our mapping
        exchange_code = UpstoxExchangeMapper.EXCHANGE_TYPES.get(exchange)
        
        if exchange_code is not None:
            logging.info(f"Mapped exchange '{exchange}' to code {exchange_code}")
            return exchange_code
            
        # If we get here, log a warning and default to NSE_EQ
        logging.warning(f"Unknown exchange '{exchange}', defaulting to NSE_EQ")
        return 'NSE_EQ'
    
    @staticmethod
    def get_openalgo_exchange(upstox_code):
        """
        Convert Upstox exchange code to OpenAlgo exchange code
        
        Args:
            upstox_code (str): Upstox exchange code
            
        Returns:
            str: OpenAlgo exchange code
        """
        return UpstoxExchangeMapper.REVERSE_EXCHANGE_TYPES.get(upstox_code, 'NSE')  # Default to NSE if not found

class UpstoxCapabilityRegistry:
    """Registry of Upstox capabilities and limits"""
    
    SUBSCRIPTION_LIMITS = {
        'standard': {
            'ltpc': {'individual': 5000, 'combined': 2000},
            'option_greeks': {'individual': 3000, 'combined': 2000},
            'full': {'individual': 2000, 'combined': 1500}
        },
        'plus': {
            'full_d30': {'individual': 50, 'combined': 1500}
        }
    }
    
    @classmethod
    def get_subscription_limit(cls, mode: str, account_type: str = 'standard') -> Dict:
        """Get subscription limits for a mode"""
        limits = cls.SUBSCRIPTION_LIMITS.get(account_type, {})
        return limits.get(mode, {'individual': 0, 'combined': 0})