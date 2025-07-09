import logging

class IbullsExchangeMapper:
    """Maps between OpenAlgo exchange codes and Ibulls XTS specific exchange types"""
    
    # Exchange type mapping for Ibulls XTS broker
    # Format: {OpenAlgo_Exchange: iBulls_Exchange_Code}
    # Based on Ibulls API documentation:
    # "NSECM": 1, "NSEFO": 2, "NSECD": 3, "BSECM": 11, "BSEFO": 12, "MCXFO": 51
    EXCHANGE_TYPES = {
        # NSE Segments
        'NSE': 1,        # NSECM - NSE Cash Market
        'NFO': 2,        # NSEFO - NSE F&O
        'NSE_INDEX': 1,  # NSE Index
        'CDS': 3,        # NSECD - NSE Currency Derivatives
        
        # BSE Segments
        'BSE': 11,       # BSECM - BSE Cash Market
        'BFO': 12,       # BSEFO - BSE F&O
        'BSE_INDEX': 11, # BSE Index
        
        # MCX Segment
        'MCX': 51,       # MCXFO - MCX F&O
        
        # Broker specific codes
        'NSECM': 1,      # NSE Cash Market
        'NSEFO': 2,      # NSE F&O
        'NSECD': 3,      # NSE Currency Derivatives
        'BSECM': 11,     # BSE Cash Market
        'BSEFO': 12,     # BSE F&O
        'MCXFO': 51      # MCX F&O
    }
    
    # Reverse mapping for converting iBulls exchange codes to OpenAlgo format
    # Format: {iBulls_Exchange_Code: OpenAlgo_Exchange}
    REVERSE_EXCHANGE_TYPES = {
        1: 'NSE',       # NSECM
        2: 'NFO',       # NSEFO
        3: 'CDS',       # NSECD
        11: 'BSE',      # BSECM
        12: 'BFO',      # BSEFO
        51: 'MCX'       # MCXFO
    }
    
    @staticmethod
    def get_exchange_type(exchange):
        """
        Convert OpenAlgo exchange code to Ibulls XTS specific exchange type
        
        Args:
            exchange: Exchange code (e.g., 'NSE', 'BSE', 'NSEFO')
            
        Returns:
            int: Exchange type code for Ibulls XTS API
        """
        if exchange is None:
            logging.warning("Exchange is None, defaulting to NSE (1)")
            return 1
            
        # Convert to string and uppercase
        exchange = str(exchange).upper().strip()
        
        # Comprehensive mapping including all possible exchange codes
        # Mapping based on Ibulls API documentation:
        # "NSECM": 1, "NSEFO": 2, "NSECD": 3, "BSECM": 11, "BSEFO": 12, "MCXFO": 51
        all_exchange_mappings = {
            # OpenAlgo standard codes
            'NSE': 1,        # NSE Cash Market
            'NFO': 2,        # NSE F&O
            'CDS': 3,        # NSE Currency Derivatives
            'BSE': 11,       # BSE Cash Market
            'BFO': 12,       # BSE F&O
            'MCX': 51,       # MCX F&O
            
            # Broker specific codes (from API docs)
            'NSECM': 1,      # NSE Cash Market
            'NSEFO': 2,      # NSE F&O
            'NSECD': 3,      # NSE Currency Derivatives
            'BSECM': 11,     # BSE Cash Market
            'BSEFO': 12,     # BSE F&O
            'MCXFO': 51,     # MCX F&O
            
            # Additional mappings for index segments
            'NSE_INDEX': 1,  # NSE Index
            'BSE_INDEX': 11, # BSE Index
            
            # Numeric string mappings (in case exchange comes as string number)
            '1': 1,          # NSECM
            '2': 2,          # NSEFO
            '3': 3,          # NSECD
            '11': 11,        # BSECM
            '12': 12,        # BSEFO
            '51': 51         # MCXFO
        }
        
        # Try to find the exchange in our mapping
        exchange_code = all_exchange_mappings.get(exchange)
        
        if exchange_code is not None:
            logging.info(f"Mapped exchange '{exchange}' to code {exchange_code}")
            return exchange_code
            
        # If we get here, log a warning and default to NSE
        logging.warning(f"Unknown exchange '{exchange}', defaulting to NSE (1)")
        return 1
    
    @staticmethod
    def get_openalgo_exchange(ibulls_code):
        """
        Convert Ibulls XTS exchange code to OpenAlgo exchange code
        
        Args:
            ibulls_code (int): iBulls exchange code
            
        Returns:
            str: OpenAlgo exchange code
        """
        return IbullsExchangeMapper.REVERSE_EXCHANGE_TYPES.get(ibulls_code, 'NSE')  # Default to NSE if not found


class IbullsCapabilityRegistry:
    """
    Registry of Ibulls XTS broker's capabilities including supported exchanges, 
    subscription modes, and market depth levels
    """
    
    # Ibulls XTS broker capabilities
    exchanges = ['NSE', 'NFO', 'CDS', 'BSE', 'BFO', 'MCX']
    subscription_modes = [1, 2, 3]  # 1: LTP, 2: Quote, 3: Depth
    depth_support = {
        'NSE': [5, 20],   # NSE supports 5 and 20 levels
        'NFO': [5, 20],   # NFO supports 5 and 20 levels
        'CDS': [5],       # Currency derivatives supports 5 levels
        'BSE': [5],       # BSE supports only 5 levels
        'BFO': [5],       # BSE F&O supports only 5 levels
        'MCX': [5]        # MCX supports 5 levels
    }
    
    @classmethod
    def get_supported_depth_levels(cls, exchange):
        """
        Get supported depth levels for an exchange
        
        Args:
            exchange (str): Exchange code (e.g., 'NSE', 'BSE')
            
        Returns:
            list: List of supported depth levels (e.g., [5, 20])
        """
        return cls.depth_support.get(exchange, [5])
    
    @classmethod
    def is_depth_level_supported(cls, exchange, depth_level):
        """
        Check if a depth level is supported for the given exchange
        
        Args:
            exchange (str): Exchange code
            depth_level (int): Requested depth level
            
        Returns:
            bool: True if supported, False otherwise
        """
        supported_depths = cls.get_supported_depth_levels(exchange)
        return depth_level in supported_depths
    
    @classmethod
    def get_fallback_depth_level(cls, exchange, requested_depth):
        """
        Get the best available depth level as a fallback
        
        Args:
            exchange (str): Exchange code
            requested_depth (int): Requested depth level
            
        Returns:
            int: Highest supported depth level that is ≤ requested depth
        """
        supported_depths = cls.get_supported_depth_levels(exchange)
        # Find the highest supported depth that's less than or equal to requested depth
        fallbacks = [d for d in supported_depths if d <= requested_depth]
        if fallbacks:
            return max(fallbacks)
        return 5  # Default to basic depth