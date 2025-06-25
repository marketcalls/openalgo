"""
Mapping utilities for Dhan broker integration.
Provides exchange code mappings between OpenAlgo and Dhan formats.
"""
from typing import Dict

# Exchange code mappings
# OpenAlgo exchange code -> Dhan exchange code
OPENALGO_TO_DHAN_EXCHANGE = {
    "NSE": "NSE_EQ",
    "BSE": "BSE_EQ",
    "NFO": "NSE_FNO",
    "BFO": "BSE_FNO",
    "CDS": "NSE_CURRENCY",
    "BCD": "BSE_CURRENCY",
    "MCX": "MCX_COMM",
    "NSE_INDEX": "IDX_I",
    "BSE_INDEX": "IDX_I"
}

# Dhan exchange code -> OpenAlgo exchange code
DHAN_TO_OPENALGO_EXCHANGE = {v: k for k, v in OPENALGO_TO_DHAN_EXCHANGE.items()}

def get_dhan_exchange(openalgo_exchange: str) -> str:
    """
    Convert OpenAlgo exchange code to Dhan exchange code.
    
    Args:
        openalgo_exchange (str): Exchange code in OpenAlgo format
        
    Returns:
        str: Exchange code in Dhan format
    """
    return OPENALGO_TO_DHAN_EXCHANGE.get(openalgo_exchange, openalgo_exchange)
    
def get_openalgo_exchange(dhan_exchange: str) -> str:
    """
    Convert Dhan exchange code to OpenAlgo exchange code.
    
    Args:
        dhan_exchange (str): Exchange code in Dhan format
        
    Returns:
        str: Exchange code in OpenAlgo format
    """
    return DHAN_TO_OPENALGO_EXCHANGE.get(dhan_exchange, dhan_exchange)
