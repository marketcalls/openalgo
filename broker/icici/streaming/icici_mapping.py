"""
Mapping utilities for ICICI Breeze broker integration.
Provides exchange code mappings between OpenAlgo and Breeze formats.
"""

from typing import Dict

# OpenAlgo -> Breeze exchange mapping
OPENALGO_TO_BREEZE_EXCHANGE = {
    "NSE": "NSE",
    "BSE": "BSE",
    "NFO": "NSE",   # Breeze uses NSE for F&O
    "BFO": "BSE",   # Breeze uses BSE for BFO
    "CDS": "NSE",   # Not directly supported; placeholder
    "BCD": "BSE",   # Not directly supported; placeholder
    "MCX": "MCX",   # Breeze doesn't currently support MCX
    "NSE_INDEX": "NSE",
    "BSE_INDEX": "BSE"
}

# Breeze -> OpenAlgo exchange mapping
BREEZE_TO_OPENALGO_EXCHANGE = {v: k for k, v in OPENALGO_TO_BREEZE_EXCHANGE.items()}


def get_breeze_exchange(openalgo_exchange: str) -> str:
    """
    Convert OpenAlgo exchange code to Breeze format.
    
    Args:
        openalgo_exchange (str): OpenAlgo exchange code
        
    Returns:
        str: Breeze-compatible exchange code
    """
    return OPENALGO_TO_BREEZE_EXCHANGE.get(openalgo_exchange, openalgo_exchange)


def get_openalgo_exchange(breeze_exchange: str) -> str:
    """
    Convert Breeze exchange code back to OpenAlgo format.
    
    Args:
        breeze_exchange (str): Breeze exchange code
        
    Returns:
        str: OpenAlgo exchange code
    """
    return BREEZE_TO_OPENALGO_EXCHANGE.get(breeze_exchange, breeze_exchange)
