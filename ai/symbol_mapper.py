"""Convert between OpenAlgo and yfinance symbol formats.

OpenAlgo: symbol='RELIANCE', exchange='NSE' (separate params)
yfinance: 'RELIANCE.NS' (suffixed)
"""

_EXCHANGE_TO_SUFFIX = {
    "NSE": ".NS",
    "BSE": ".BO",
    "NFO": ".NS",
    "MCX": ".NS",
    "CDS": ".NS",
    "BFO": ".BO",
    "BCD": ".BO",
    "NCDEX": ".NS",
}

_SUFFIX_TO_EXCHANGE = {
    ".NS": "NSE",
    ".BO": "BSE",
}


def to_yfinance(symbol: str, exchange: str = "NSE") -> str:
    """Convert OpenAlgo symbol + exchange to yfinance format."""
    suffix = _EXCHANGE_TO_SUFFIX.get(exchange.upper(), ".NS")
    return f"{symbol.upper()}{suffix}"


def to_openalgo(yf_symbol: str) -> tuple[str, str]:
    """Convert yfinance symbol to (symbol, exchange) tuple."""
    for suffix, exchange in _SUFFIX_TO_EXCHANGE.items():
        if yf_symbol.upper().endswith(suffix):
            return yf_symbol[: -len(suffix)].upper(), exchange
    return yf_symbol.upper(), "NSE"


def parse_openalgo_symbol(raw: str) -> tuple[str, str]:
    """Parse 'NSE:RELIANCE' or 'RELIANCE' into (symbol, exchange)."""
    if ":" in raw:
        exchange, symbol = raw.split(":", 1)
        return symbol.strip().upper(), exchange.strip().upper()
    return raw.strip().upper(), "NSE"
