from utils.logging import get_logger

logger = get_logger(__name__)

def get_br_symbol(symbol, exchange):
    """Convert OpenAlgo symbol to DefinedGe Securities symbol format"""
    try:
        # DefinedGe uses similar symbol format to NSE/BSE
        # For equity symbols, remove -EQ suffix if present
        if exchange in ['NSE', 'BSE'] and symbol.endswith('-EQ'):
            return symbol[:-3]

        # For derivatives, DefinedGe uses standard format
        return symbol

    except Exception as e:
        logger.error(f"Error converting symbol {symbol}: {e}")
        return symbol

def get_oa_symbol(symbol, exchange):
    """Convert DefinedGe Securities symbol to OpenAlgo symbol format"""
    try:
        # For equity symbols on NSE, add -EQ suffix
        if exchange == 'NSE' and not any(x in symbol for x in ['FUT', 'CE', 'PE']):
            return f"{symbol}-EQ"

        # For other exchanges and derivatives, return as is
        return symbol

    except Exception as e:
        logger.error(f"Error converting symbol {symbol}: {e}")
        return symbol
