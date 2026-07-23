# broker/hdfcsky/mapping/exchange.py
#
# Exchange-code translation between OpenAlgo and HDFC Sky, plus index-symbol
# standardization.
#
# Everything below is verified against the live Security Master
# (https://hdfcsky.com/api/v1/contract/Compact?info=download -> CompactScrip.csv,
# ~182k rows). The CSV's `exchange` column already uses OpenAlgo-compatible
# codes (NSE / BSE / NFO / BFO / CDS / MCX); the only split OpenAlgo needs is
# pulling indices out into NSE_INDEX / BSE_INDEX, which the CSV flags via the
# `segment` column (NSE -> "INDICES", BSE -> "IDX").
#
# Imported by:
#   - database/master_contract_db.py  (build SymToken rows)
#   - api/data.py                     (LTP / chart-data calls)
#   - api/order_api.py                (order payloads)
#   - streaming/*                     (scripId prefixes)

# OpenAlgo index exchanges (quote-only).
OA_INDEX_EXCHANGES = {"NSE_INDEX", "BSE_INDEX"}

# CSV `segment` value that marks an index row, keyed by the CSV `exchange`.
INDEX_SEGMENTS = {"NSE": "INDICES", "BSE": "IDX"}

# OpenAlgo exchange -> the code HDFC Sky's REST endpoints (orders, positions,
# LTP, chart data) expect. Indices resolve to their parent cash exchange.
_OA_TO_HDFCSKY_REST = {
    "NSE": "NSE",
    "BSE": "BSE",
    "NFO": "NFO",
    "BFO": "BFO",
    "CDS": "CDS",
    "MCX": "MCX",
    "NSE_INDEX": "NSE",
    "BSE_INDEX": "BSE",
}

# HDFC Sky REST exchange code -> OpenAlgo exchange (normalizing responses).
# Note this is intentionally NOT the inverse of the map above: an order-book
# row on "NSE" is a cash instrument, never an index.
_HDFCSKY_REST_TO_OA = {
    "NSE": "NSE",
    "BSE": "BSE",
    "NFO": "NFO",
    "BFO": "BFO",
    "CDS": "CDS",
    "NCD": "CDS",
    "MCX": "MCX",
}

# WebSocket scripId prefix per OpenAlgo exchange. Straight from the docs'
# "Prefix for each Exchange and segment" table: the feed keys instruments as
# "<PREFIX>_<TOKEN>" and uses dedicated *_INDEX prefixes for index feeds.
_OA_TO_WS_PREFIX = {
    "NSE": "NSE",
    "BSE": "BSE",
    "NFO": "NFO",
    "BFO": "BFO",
    "CDS": "NCD",
    "MCX": "MCX",
    "NSE_INDEX": "NSE_INDEX",
    "BSE_INDEX": "BSE_INDEX",
}

_WS_PREFIX_TO_OA = {v: k for k, v in _OA_TO_WS_PREFIX.items()}


def to_rest_exchange(oa_exchange):
    """OpenAlgo exchange -> HDFC Sky REST exchange code."""
    return _OA_TO_HDFCSKY_REST.get(oa_exchange, oa_exchange)


def to_oa_exchange(hdfcsky_exchange):
    """HDFC Sky REST exchange code -> OpenAlgo exchange."""
    return _HDFCSKY_REST_TO_OA.get(str(hdfcsky_exchange).upper(), hdfcsky_exchange)


def to_ws_prefix(oa_exchange):
    """OpenAlgo exchange -> WebSocket scripId prefix."""
    return _OA_TO_WS_PREFIX.get(oa_exchange, oa_exchange)


def ws_scrip_id(oa_exchange, token):
    """Build the WebSocket scripId, e.g. ('NSE_INDEX', 26000) -> 'NSE_INDEX_26000'."""
    return f"{to_ws_prefix(oa_exchange)}_{token}"


def from_ws_scrip_id(scrip_id):
    """Split a scripId back into (oa_exchange, token). Returns (None, None)
    when the prefix is unknown."""
    text = str(scrip_id)
    # Longest prefix first so "NSE_INDEX" wins over "NSE".
    for prefix in sorted(_WS_PREFIX_TO_OA, key=len, reverse=True):
        if text.startswith(prefix + "_"):
            return _WS_PREFIX_TO_OA[prefix], text[len(prefix) + 1 :]
    return None, None


def is_index_exchange(oa_exchange):
    return oa_exchange in OA_INDEX_EXCHANGES


# --- index symbol mapping -------------------------------------------------
#
# HDFC Sky ships index rows with human display names on NSE ("Nifty 50",
# "Nifty Bank") and short codes on BSE ("SENSEX", "SNSX50", "BSE HC").
# OpenAlgo standardizes both to the symbols documented in
# docs/prompt/symbol-format.md -- the same set the Zerodha reference
# implementation produces, so option tools that start from an index LTP
# (option chain, IV smile, max pain, GEX, OI tracker) resolve identically
# across brokers.
#
# Lookup keys are uppercased with all whitespace removed. Anything not listed
# falls back to its cleaned (uppercased, space-stripped) name, which keeps new
# indices addressable the moment HDFC adds them.

_NSE_INDEX_MAP = {
    # Derivative underlyings -- these five MUST match the NFO `name` column
    # so the options tools can join index spot to its option chain.
    "NIFTY50": "NIFTY",
    "NIFTYBANK": "BANKNIFTY",
    "NIFTYFINSERVICE": "FINNIFTY",
    "NIFTYMIDSELECT": "MIDCPNIFTY",
    "NIFTYNEXT50": "NIFTYNXT50",
    "INDIAVIX": "INDIAVIX",
    # Broad market
    "NIFTY100": "NIFTY100",
    "NIFTY200": "NIFTY200",
    "NIFTY500": "NIFTY500",
    # Sectoral
    "NIFTYALPHA50": "NIFTYALPHA50",
    "NIFTYAUTO": "NIFTYAUTO",
    "NIFTYCHEMICALS": "NIFTYCHEMICALS",
    "NIFTYCOMMODITIES": "NIFTYCOMMODITIES",
    "NIFTYCONSUMPTION": "NIFTYCONSUMPTION",
    "NIFTYCPSE": "NIFTYCPSE",
    "NIFTYDIVOPPS50": "NIFTYDIVOPPS50",
    "NIFTYENERGY": "NIFTYENERGY",
    "NIFTYFMCG": "NIFTYFMCG",
    "NIFTYGROWSECT15": "NIFTYGROWSECT15",
    "NIFTYHEALTHCARE": "NIFTYHEALTHCARE",
    "NIFTYINFRA": "NIFTYINFRA",
    "NIFTYIT": "NIFTYIT",
    "NIFTYMEDIA": "NIFTYMEDIA",
    "NIFTYMETAL": "NIFTYMETAL",
    "NIFTYMNC": "NIFTYMNC",
    "NIFTYOILANDGAS": "NIFTYOILANDGAS",
    "NIFTYPHARMA": "NIFTYPHARMA",
    "NIFTYPSE": "NIFTYPSE",
    "NIFTYPSUBANK": "NIFTYPSUBANK",
    "NIFTYPVTBANK": "NIFTYPVTBANK",
    "NIFTYREALTY": "NIFTYREALTY",
    "NIFTYSERVSECTOR": "NIFTYSERVSECTOR",
    # Market cap
    "NIFTYMIDLIQ15": "NIFTYMIDLIQ15",
    "NIFTYMIDCAP50": "NIFTYMIDCAP50",
    "NIFTYMIDCAP100": "NIFTYMIDCAP100",
    "NIFTYMIDCAP150": "NIFTYMIDCAP150",
    "NIFTYMIDSML400": "NIFTYMIDSML400",
    "NIFTYSMLCAP50": "NIFTYSMLCAP50",
    "NIFTYSMLCAP100": "NIFTYSMLCAP100",
    "NIFTYSMLCAP250": "NIFTYSMLCAP250",
    # Strategy
    "NIFTY100EQLWGT": "NIFTY100EQLWGT",
    "NIFTY100LIQ15": "NIFTY100LIQ15",
    "NIFTY100LOWVOL30": "NIFTY100LOWVOL30",
    "NIFTY100QUALTY30": "NIFTY100QUALTY30",
    "NIFTY200QUALTY30": "NIFTY200QUALTY30",
    "NIFTY50DIVPOINT": "NIFTY50DIVPOINT",
    "NIFTY50EQLWGT": "NIFTY50EQLWGT",
    "NIFTY50PR1XINV": "NIFTY50PR1XINV",
    "NIFTY50PR2XLEV": "NIFTY50PR2XLEV",
    "NIFTY50TR1XINV": "NIFTY50TR1XINV",
    "NIFTY50TR2XLEV": "NIFTY50TR2XLEV",
    "NIFTY50VALUE20": "NIFTY50VALUE20",
    # Government securities
    "NIFTYGS10YR": "NIFTYGS10YR",
    "NIFTYGS10YRCLN": "NIFTYGS10YRCLN",
    "NIFTYGS1115YR": "NIFTYGS1115YR",
    "NIFTYGS15YRPLUS": "NIFTYGS15YRPLUS",
    "NIFTYGS48YR": "NIFTYGS48YR",
    "NIFTYGS813YR": "NIFTYGS813YR",
    "NIFTYGSCOMPSITE": "NIFTYGSCOMPSITE",
}

# BSE short codes (the CSV's `trading_symbol` for IDX rows) -> OpenAlgo symbol.
_BSE_INDEX_MAP = {
    "SENSEX": "SENSEX",
    "BANKEX": "BANKEX",
    "SNSX50": "SENSEX50",
    "SNXT50": "BSESENSEXNEXT50",
    "BSE100": "BSE100",
    "BSE200": "BSE200",
    "BSE500": "BSE500",
    "MID150": "BSE150MIDCAPINDEX",
    "LMI250": "BSE250LARGEMIDCAPINDEX",
    "MSL400": "BSE400MIDSMALLCAPINDEX",
    "AUTO": "BSEAUTO",
    "BSECG": "BSECAPITALGOODS",
    "BSECD": "BSECONSUMERDURABLES",
    "CPSE": "BSECPSE",
    "ENERGY": "BSEENERGY",
    "BSEFMC": "BSEFASTMOVINGCONSUMERGOODS",
    "FINSER": "BSEFINANCIALSERVICES",
    "BSEHC": "BSEHEALTHCARE",
    "INFRA": "BSEINDIAINFRASTRUCTUREINDEX",
    "INDSTR": "BSEINDUSTRIALS",
    "BSEIT": "BSEINFORMATIONTECHNOLOGY",
    "BSEIPO": "BSEIPO",
    "METAL": "BSEMETAL",
    "MIDSEL": "BSEMIDCAPSELECTINDEX",
    "OILGAS": "BSEOIL&GAS",
    "POWER": "BSEPOWER",
    "BSEPSU": "BSEPSU",
    "REALTY": "BSEREALTY",
    "SMLSEL": "BSESMALLCAPSELECTINDEX",
    "SMEIPO": "BSESMEIPO",
    "TECK": "BSETECK",
    "TELCOM": "BSETELECOM",
    "UTILS": "BSEUTILITIES",
    "ESG100": "ESG100",
    "BHRT22": "BHRT22",
    "FOCIT": "FOCIT",
}

_INDEX_MAPS = {"NSE_INDEX": _NSE_INDEX_MAP, "BSE_INDEX": _BSE_INDEX_MAP}


def _norm(name):
    return "".join(str(name).upper().split())


def classify_index_symbol(display_name, oa_exchange):
    """HDFC Sky index display name -> the OpenAlgo index symbol.

    Unmapped names fall back to their normalized (uppercase, space-free) form
    so newly listed indices are still addressable.
    """
    key = _norm(display_name)
    return _INDEX_MAPS.get(oa_exchange, {}).get(key, key)


# --- index derivative underlyings ----------------------------------------
#
# Needed by the chart-data API, whose `seriesType` distinguishes index from
# stock derivatives (FUTIDX vs FUTSTK on NFO, IF/IO vs SF/SO on BFO). Taken
# from the live master: these are exactly the `company_name` values carried by
# NFO OPTIDX/FUTIDX and BFO IF/IO rows.
NFO_INDEX_UNDERLYINGS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}
BFO_INDEX_UNDERLYINGS = {"SENSEX", "SENSEX50", "BANKEX", "FOCIT"}
