"""
Firstock-specific exchange mapping and capability registry
"""

class FirstockExchangeMapper:
    """Maps between standard exchange codes and Firstock-specific codes"""
    
    # Mapping from standard codes to Firstock exchange codes
    EXCHANGE_MAP = {
        'NSE': 'NSE',
        'BSE': 'BSE',
        'NFO': 'NFO',
        'CDS': 'CDS',
        'MCX': 'MCX',
        'BFO': 'BFO',
        'NSE_INDEX': 'NSE'  # NSE indices use NSE exchange in Firstock
    }
    
    # Reverse mapping
    REVERSE_MAP = {v: k for k, v in EXCHANGE_MAP.items()}
    
    @classmethod
    def get_firstock_exchange(cls, standard_exchange: str) -> str:
        """
        Convert standard exchange code to Firstock-specific code
        
        Args:
            standard_exchange: Standard exchange code (e.g., 'NSE')
            
        Returns:
            str: Firstock exchange code
        """
        return cls.EXCHANGE_MAP.get(standard_exchange, standard_exchange)
    
    @classmethod
    def get_standard_exchange(cls, firstock_exchange: str) -> str:
        """
        Convert Firstock exchange code to standard code
        
        Args:
            firstock_exchange: Firstock exchange code
            
        Returns:
            str: Standard exchange code
        """
        return cls.REVERSE_MAP.get(firstock_exchange, firstock_exchange)