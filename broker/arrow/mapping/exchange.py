# broker/arrow/mapping/exchange.py
#
# Central exchange-code translation between OpenAlgo and Arrow, plus index
# handling. Arrow collapses ALL indices (NSE and BSE) into a single `INDEX`
# pseudo-exchange for quotes, while OpenAlgo splits them into NSE_INDEX and
# BSE_INDEX. The master contract classifies each index to the right OpenAlgo
# exchange; the data/streaming layers translate back to Arrow on every call.
#
# Imported by:
#   - database/master_contract_db.py  (build SymToken rows)
#   - api/data.py                     (quotes / depth / history)
#   - streaming/*                     (token-based subscriptions)

# OpenAlgo index exchanges.
OA_INDEX_EXCHANGES = {"NSE_INDEX", "BSE_INDEX"}

# OpenAlgo exchange -> Arrow exchange code used by the /info/quote* endpoints.
# Indices both map to Arrow's single "INDEX" pseudo-exchange.
_OA_TO_ARROW_QUOTE = {
    "NSE": "NSE",
    "BSE": "BSE",
    "NFO": "NFO",
    "BFO": "BFO",
    "MCX": "MCX",
    "CDS": "NCD",   # TODO(arrow): confirm NSE currency code (NCD) for quotes.
    "BCD": "BCD",   # TODO(arrow): confirm BSE currency code for quotes.
    "NSE_INDEX": "INDEX",
    "BSE_INDEX": "INDEX",
}

# OpenAlgo exchange -> Arrow historical-API path segment (lowercase). Indices
# resolve to their parent cash exchange for the candle path.
# TODO(arrow): confirm the historical exchange path for indices (nse/bse vs index).
_OA_TO_ARROW_HISTORY = {
    "NSE": "nse",
    "BSE": "bse",
    "NFO": "nfo",
    "BFO": "bfo",
    "MCX": "mcx",
    "CDS": "cds",
    "BCD": "bcd",
    "NSE_INDEX": "nse",
    "BSE_INDEX": "bse",
}

# Arrow ExchSeg/Exchange (raw) -> OpenAlgo exchange (for NON-index instruments).
_ARROW_TO_OA = {
    "NSE": "NSE",
    "BSE": "BSE",
    "NFO": "NFO",
    "BFO": "BFO",
    "MCX": "MCX",
    "NCD": "CDS",
    "BCD": "BCD",
    "CDS": "CDS",
}

# Index display-name (uppercased, spaces collapsed) -> OpenAlgo index symbol.
# Arrow's /info/index-list returns title-case names like "Nifty 50".
# Anything not listed falls back to its uppercased no-space name.
INDEX_NAME_TO_OA_SYMBOL = {
    "NIFTY50": "NIFTY",
    "NIFTY": "NIFTY",
    "NIFTYNEXT50": "NIFTYNXT50",
    "NIFTYFINSERVICE": "FINNIFTY",
    "NIFTYFINANCIALSERVICES": "FINNIFTY",
    "NIFTYBANK": "BANKNIFTY",
    "BANKNIFTY": "BANKNIFTY",
    "NIFTYMIDSELECT": "MIDCPNIFTY",
    "NIFTYMIDCAPSELECT": "MIDCPNIFTY",
    "INDIAVIX": "INDIAVIX",
    # BSE
    "SENSEX": "SENSEX",
    "BANKEX": "BANKEX",
    "SENSEX50": "SENSEX50",
}

# Index names (uppercased, no spaces) that belong to BSE. Everything else is
# treated as an NSE index. Extend as Arrow's index-list is observed live.
_BSE_INDEX_NAMES = {
    "SENSEX",
    "BANKEX",
    "SENSEX50",
    "BSE100",
    "BSE200",
    "BSE500",
    "BSEMIDCAP",
    "BSESMALLCAP",
}


def _norm(name):
    return "".join(str(name).upper().split())


def to_arrow_quote_exchange(oa_exchange):
    """OpenAlgo exchange -> Arrow quote exchange (indices -> INDEX)."""
    return _OA_TO_ARROW_QUOTE.get(oa_exchange, oa_exchange)


def to_arrow_history_exchange(oa_exchange):
    """OpenAlgo exchange -> Arrow historical path segment (lowercase)."""
    return _OA_TO_ARROW_HISTORY.get(oa_exchange, str(oa_exchange).lower())


def is_index_exchange(oa_exchange):
    return oa_exchange in OA_INDEX_EXCHANGES


def arrow_exchange_to_oa(exchseg, segment=None, exchange=None):
    """Map an Arrow instrument's raw exchange fields to an OpenAlgo exchange.

    Index rows (Segment/Series == INDEX, or ExchSeg == INDEX) are split into
    NSE_INDEX / BSE_INDEX by their parent exchange.
    """
    seg = str(segment).upper() if segment else ""
    es = str(exchseg).upper() if exchseg else ""
    parent = str(exchange).upper() if exchange else es

    is_index = "INDEX" in seg or es == "INDEX" or seg in ("IDX", "INDICES")
    if is_index:
        if parent.startswith("BSE"):
            return "BSE_INDEX"
        return "NSE_INDEX"

    return _ARROW_TO_OA.get(es) or _ARROW_TO_OA.get(parent)


def classify_index_symbol(index_name):
    """Given an Arrow index display name, return (oa_symbol, oa_exchange)."""
    key = _norm(index_name)
    oa_symbol = INDEX_NAME_TO_OA_SYMBOL.get(key, key)
    oa_exchange = "BSE_INDEX" if key in _BSE_INDEX_NAMES else "NSE_INDEX"
    return oa_symbol, oa_exchange
