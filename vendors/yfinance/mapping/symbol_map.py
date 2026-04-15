from vendors.base_vendor import VendorSymbolError

_SUFFIX_BY_EXCHANGE = {"NSE": ".NS", "BSE": ".BO"}
_EXCHANGE_BY_SUFFIX = {".NS": "NSE", ".BO": "BSE"}

_INDEX_TO_YF = {
    ("NIFTY", "NSE_INDEX"): "^NSEI",
    ("BANKNIFTY", "NSE_INDEX"): "^NSEBANK",
    ("FINNIFTY", "NSE_INDEX"): "^CNXFIN",
    ("MIDCPNIFTY", "NSE_INDEX"): "^NSEMDCP50",
    ("NIFTYNXT50", "NSE_INDEX"): "^NSMIDCP",
    ("INDIAVIX", "NSE_INDEX"): "^INDIAVIX",
    ("SENSEX", "BSE_INDEX"): "^BSESN",
    ("BANKEX", "BSE_INDEX"): "^BSEBANK",
    ("SENSEX50", "BSE_INDEX"): "^BSESN50",
}
_YF_TO_INDEX = {v: k for k, v in _INDEX_TO_YF.items()}

SUPPORTED_EXCHANGES = {"NSE", "BSE", "NSE_INDEX", "BSE_INDEX"}


def to_vendor(symbol: str, exchange: str) -> str:
    """Translate an OpenAlgo (symbol, exchange) pair to a yfinance ticker."""
    symbol_u = (symbol or "").upper()
    exchange_u = (exchange or "").upper()

    if exchange_u not in SUPPORTED_EXCHANGES:
        raise VendorSymbolError(
            f"yfinance vendor does not support exchange '{exchange}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXCHANGES))}"
        )

    key = (symbol_u, exchange_u)
    if key in _INDEX_TO_YF:
        return _INDEX_TO_YF[key]

    suffix = _SUFFIX_BY_EXCHANGE.get(exchange_u)
    if suffix is None:
        raise VendorSymbolError(
            f"yfinance vendor has no ticker mapping for {symbol} on {exchange}"
        )
    return f"{symbol_u}{suffix}"


def to_openalgo(vendor_ticker: str) -> tuple[str, str]:
    """Translate a yfinance ticker back to OpenAlgo (symbol, exchange)."""
    if not vendor_ticker:
        raise VendorSymbolError("Empty yfinance ticker cannot be mapped")

    if vendor_ticker in _YF_TO_INDEX:
        return _YF_TO_INDEX[vendor_ticker]

    for suffix, exchange in _EXCHANGE_BY_SUFFIX.items():
        if vendor_ticker.endswith(suffix):
            return vendor_ticker[: -len(suffix)], exchange

    raise VendorSymbolError(
        f"Cannot map yfinance ticker '{vendor_ticker}' to an OpenAlgo symbol"
    )
