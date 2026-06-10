# broker/arrow/mapping/exchange.py
#
# Central exchange-code translation between OpenAlgo and Arrow, plus index
# handling. All mappings below are verified against the live instrument
# master (https://edge.arrow.trade/all, ~221k rows) and the conventions in
# the platform's symtoken table (Zerodha reference implementation).
#
# Arrow's CSV identifies an instrument's market by the ExchSeg column:
#   NSECM / BSECM   cash equities
#   NSEFO / BSEFO   equity & index F&O
#   NSECD           NSE currency derivatives
#   NSECO           NSE commodities (OpenAlgo exchange NCO)
#   MCXFO           MCX commodities
#   NSEIDX / BSEIDX / MCXIDX   index-only quote rows
#
# Imported by:
#   - database/master_contract_db.py  (build SymToken rows)
#   - api/data.py                     (quotes / depth / history)
#   - streaming/*                     (token-based subscriptions)

# OpenAlgo index exchanges (quote-only).
OA_INDEX_EXCHANGES = {"NSE_INDEX", "BSE_INDEX", "MCX_INDEX"}

# Arrow ExchSeg -> OpenAlgo exchange. Verified against the live CSV.
ARROW_EXCHSEG_TO_OA = {
    "NSECM": "NSE",
    "BSECM": "BSE",
    "NSEFO": "NFO",
    "BSEFO": "BFO",
    "NSECD": "CDS",
    "BSECD": "BCD",  # not present in the live CSV today; mapped for safety
    "NSECO": "NCO",
    "MCXFO": "MCX",
    "NSEIDX": "NSE_INDEX",
    "BSEIDX": "BSE_INDEX",
    "MCXIDX": "MCX_INDEX",
}

# OpenAlgo exchange -> Arrow exchange code used by the /info/quote* endpoints.
# Verified against the live API: NSE/BSE/NFO/BFO pass through, MCX requires
# "MCXFO" (plain "MCX" is rejected despite being in the SDK enum), and all
# indices collapse to the single "INDEX" pseudo-exchange.
_OA_TO_ARROW_QUOTE = {
    "NSE": "NSE",
    "BSE": "BSE",
    "NFO": "NFO",
    "BFO": "BFO",
    "MCX": "MCXFO",
    "NSE_INDEX": "INDEX",
    "BSE_INDEX": "INDEX",
    "MCX_INDEX": "INDEX",
}

# Exchanges Arrow's quote REST API does NOT serve at all -- probed live with
# every plausible code (CDS/NCD/NSECD/CD/CUR, NCO/CO/NSECO/COM, futures and
# options symbols alike, all 400) and consistent with the official SDK whose
# Exchange enum has no currency/commodity members. Live data for these still
# flows over the websocket, which is token-based and exchange-agnostic.
QUOTE_UNSUPPORTED_EXCHANGES = {"CDS", "BCD", "NCO"}

# OpenAlgo exchange -> Arrow historical-API path segment (lowercase). Indices
# resolve to their parent cash exchange for the candle path.
# TODO(arrow): confirm the historical exchange path for indices (nse/bse vs index)
# and for NSE commodities (nco vs co).
_OA_TO_ARROW_HISTORY = {
    "NSE": "nse",
    "BSE": "bse",
    "NFO": "nfo",
    "BFO": "bfo",
    "MCX": "mcx",
    "CDS": "cds",
    "BCD": "bcd",
    "NCO": "nco",
    "NSE_INDEX": "nse",
    "BSE_INDEX": "bse",
    "MCX_INDEX": "mcx",
}

# --- index symbol mapping -------------------------------------------------
#
# Arrow index rows carry a display name in the CSV `Symbol` column
# ("Nifty 50", "BSE IT", "CrudeOil"). OpenAlgo standardizes these to the
# symbols documented in docs/prompt/symbol-format.md (same set the Zerodha
# reference implementation produces). Lookup keys are uppercased with
# whitespace removed; anything unmapped falls back to its cleaned name.

# NSE index display names (normalized) -> OpenAlgo symbol.
_NSE_INDEX_MAP = {
    # Major indices
    "NIFTY50": "NIFTY",
    "NIFTYNEXT50": "NIFTYNXT50",
    "NIFTYFINSERVICE": "FINNIFTY",
    "NIFTYBANK": "BANKNIFTY",
    "NIFTYMIDSELECT": "MIDCPNIFTY",
    "INDIAVIX": "INDIAVIX",
    "HANGSENGBEES-NAV": "HANGSENGBEESNAV",
    # Broad market
    "NIFTY100": "NIFTY100",
    "NIFTY200": "NIFTY200",
    "NIFTY500": "NIFTY500",
    # Sectoral
    "NIFTYALPHA50": "NIFTYALPHA50",
    "NIFTYAUTO": "NIFTYAUTO",
    "NIFTYCOMMODITIES": "NIFTYCOMMODITIES",
    "NIFTYCONSUMPTION": "NIFTYCONSUMPTION",
    "NIFTYCPSE": "NIFTYCPSE",
    "NIFTYDIVOPPS50": "NIFTYDIVOPPS50",
    "NIFTYENERGY": "NIFTYENERGY",
    "NIFTYFMCG": "NIFTYFMCG",
    "NIFTYGROWSECT15": "NIFTYGROWSECT15",
    "NIFTYINFRA": "NIFTYINFRA",
    "NIFTYIT": "NIFTYIT",
    "NIFTYMEDIA": "NIFTYMEDIA",
    "NIFTYMETAL": "NIFTYMETAL",
    "NIFTYMNC": "NIFTYMNC",
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

# BSE index short codes (normalized CSV `Symbol`) -> OpenAlgo symbol.
_BSE_INDEX_MAP = {
    "SENSEX": "SENSEX",
    "BANKEX": "BANKEX",
    "SENSEX50": "SENSEX50",
    "SNXT50": "BSESENSEXNEXT50",
    "BSE100": "BSE100",
    "BSE200": "BSE200",
    "BSE500": "BSE500",
    "MID150": "BSE150MIDCAPINDEX",
    "LMI250": "BSE250LARGEMIDCAPINDEX",
    "MSL400": "BSE400MIDSMALLCAPINDEX",
    "AUTO": "BSEAUTO",
    "BSECG": "BSECAPITALGOODS",
    "CARBON": "BSECARBONEX",
    "BSECD": "BSECONSUMERDURABLES",
    "CPSE": "BSECPSE",
    "DOL30": "BSEDOLLEX30",
    "DOL100": "BSEDOLLEX100",
    "DOL200": "BSEDOLLEX200",
    "ENERGYINDEX": "BSEENERGY",
    "BSEFMC": "BSEFASTMOVINGCONSUMERGOODS",
    "FIN": "BSEFINANCIALSERVICES",
    "GREENX": "BSEGREENEX",
    "BSEHC": "BSEHEALTHCARE",
    "INFRAINDEX": "BSEINDIAINFRASTRUCTUREINDEX",
    "INDSTR": "BSEINDUSTRIALS",
    "BSEIT": "BSEINFORMATIONTECHNOLOGY",
    "BSEIPO": "BSEIPO",
    "LRGCAP": "BSELARGECAP",
    "METALINDEX": "BSEMETAL",
    "MIDCAP": "BSEMIDCAP",
    "MIDSEL": "BSEMIDCAPSELECTINDEX",
    "OILGAS": "BSEOIL&GAS",
    "POWER": "BSEPOWER",
    "BSEPSU": "BSEPSU",
    "REALTY": "BSEREALTY",
    "SMLCAP": "BSESMALLCAP",
    "SMLSEL": "BSESMALLCAPSELECTINDEX",
    "SMEIPO": "BSESMEIPO",
    "TECK": "BSETECK",
    "TELCOM": "BSETELECOM",
}

# MCX iCOMDEX index names (normalized CSV `Symbol`) -> OpenAlgo symbol.
# The first eight match the documented MCX_INDEX set; the rest are
# single-commodity iCOMDEX feeds Arrow carries that have no documented
# OpenAlgo name yet, so they get a consistent MCX-prefixed symbol.
_MCX_INDEX_MAP = {
    "COMPOSITE": "MCXCOMPDEX",
    "BULLION": "MCXBULLDEX",
    "BASEMETAL": "MCXMETLDEX",
    "ENERGY": "MCXENERGY",
    "GOLD": "MCXGOLDEX",
    "SILVER": "MCXSILVDEX",
    "COPPER": "MCXCOPRDEX",
    "CRUDEOIL": "MCXCRUDEX",
    "ALUMINIUM": "MCXALUMINIUM",
    "LEAD": "MCXLEAD",
    "ZINC": "MCXZINC",
    "NATURALGAS": "MCXNATURALGAS",
}

_INDEX_MAPS = {
    "NSE_INDEX": _NSE_INDEX_MAP,
    "BSE_INDEX": _BSE_INDEX_MAP,
    "MCX_INDEX": _MCX_INDEX_MAP,
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

    The ExchSeg column (NSECM/NSEFO/NSEIDX/...) is authoritative. The
    Segment == INDEX fallback covers any index row with an unexpected
    ExchSeg by splitting on the parent Exchange column.
    """
    es = str(exchseg).upper() if exchseg else ""
    mapped = ARROW_EXCHSEG_TO_OA.get(es)
    if mapped:
        return mapped

    seg = str(segment).upper() if segment else ""
    parent = str(exchange).upper() if exchange else ""
    if "INDEX" in seg or "IDX" in es:
        if parent.startswith("BSE"):
            return "BSE_INDEX"
        if parent.startswith("MCX"):
            return "MCX_INDEX"
        return "NSE_INDEX"

    return ARROW_EXCHSEG_TO_OA.get(parent)


def classify_index_symbol(index_name, oa_exchange=None):
    """Given an Arrow index display name, return (oa_symbol, oa_exchange).

    When the caller already knows the index exchange (from ExchSeg), pass it
    in -- the name is then only used to standardize the symbol. Without an
    exchange (the /info/index-list endpoint returns bare {name, token}), BSE
    membership is inferred from the known BSE code list and everything else
    is treated as NSE.
    """
    key = _norm(index_name)

    if oa_exchange in _INDEX_MAPS:
        return _INDEX_MAPS[oa_exchange].get(key, key), oa_exchange

    if key in _BSE_INDEX_MAP:
        return _BSE_INDEX_MAP[key], "BSE_INDEX"
    return _NSE_INDEX_MAP.get(key, key), "NSE_INDEX"
