"""Exchange, index and asset-type translation between OpenAlgo and Nuvama.

Nuvama keys every instrument by its ``exchangetoken`` from the contract file:
``<scripcode>_<EXCHANGE>`` for tradable instruments (``2885_NSE``,
``42692_NFO``) and a bare negative number for an index (``-29`` is Nifty 50).
That value is what orders send as ``sym``, what the quote and chart routes take
as ``{symbol}`` and what the streaming socket subscribes to. The master
contract stores it as ``token`` unchanged.
"""

import re

# OpenAlgo exchange -> the exchange code Nuvama's order routes take as `exc`.
OA_TO_NUVAMA_EXCHANGE = {
    "NSE": "NSE",
    "BSE": "BSE",
    "NFO": "NFO",
    "BFO": "BFO",
    "CDS": "CDS",
    "MCX": "MCX",
    "NCDEX": "NCDEX",
    "NSE_INDEX": "NSE",
    "BSE_INDEX": "BSE",
}

OA_INDEX_EXCHANGES = frozenset({"NSE_INDEX", "BSE_INDEX"})

# Nuvama's index names (contract file `tradingsymbol`) whose OpenAlgo symbol is
# not simply the name in capitals without spaces. The NSE derivative indices
# and the BSE short codes, against docs/prompt/symbol-format.md.
_NSE_INDEX_NAMES = {
    "Nifty 50": "NIFTY",
    "Nifty Bank": "BANKNIFTY",
    "Nifty Fin Service": "FINNIFTY",
    "NIFTY MID SELECT": "MIDCPNIFTY",
    "Nifty Next 50": "NIFTYNXT50",
}

_BSE_INDEX_NAMES = {
    "SNSX50": "SENSEX50",
    "AUTO": "BSEAUTO",
    "BSE CG": "BSECAPITALGOODS",
    "BSE CD": "BSECONSUMERDURABLES",
    "BSEFMC": "BSEFASTMOVINGCONSUMERGOODS",
    "BSE IT": "BSEINFORMATIONTECHNOLOGY",
    "METAL": "BSEMETAL",
    "MIDCAP": "BSEMIDCAP",
    "SMLCAP": "BSESMALLCAP",
    "OILGAS": "BSEOIL&GAS",
    "POWER": "BSEPOWER",
    "REALTY": "BSEREALTY",
    "TELCOM": "BSETELECOM",
    "INDSTR": "BSEINDUSTRIALS",
}


def oa_index_symbol(nuvama_name, nuvama_exchange):
    """OpenAlgo symbol for a Nuvama index row."""
    name = (nuvama_name or "").strip()
    table = _NSE_INDEX_NAMES if nuvama_exchange == "NSE" else _BSE_INDEX_NAMES
    if name in table:
        return table[name]
    return re.sub(r"\s+", "", name).upper()


def oa_index_exchange(nuvama_exchange):
    return "BSE_INDEX" if nuvama_exchange == "BSE" else "NSE_INDEX"


def nuvama_exchange(oa_exchange):
    return OA_TO_NUVAMA_EXCHANGE.get(oa_exchange, oa_exchange)


def to_oa_exchange(nuvama_exchange_code):
    """Nuvama `exc` in a book row -> OpenAlgo exchange (same codes for tradables)."""
    return (nuvama_exchange_code or "").upper()


def chart_asset_type(exchange, instrumenttype, is_index_underlying):
    """The chart route's `aTyp` for a symbol, from its OpenAlgo exchange and type.

    Nuvama's types: INDEX, EQUITY, FUTIDX, FUTSTK, OPTIDX, OPTSTK, FUTCUR,
    OPTCUR, FUTCOM, OPTFUT.
    """
    if exchange in OA_INDEX_EXCHANGES:
        return "INDEX"
    if exchange in ("NSE", "BSE"):
        return "EQUITY"
    is_option = instrumenttype in ("CE", "PE")
    if exchange == "CDS":
        return "OPTCUR" if is_option else "FUTCUR"
    if exchange in ("MCX", "NCDEX"):
        return "OPTFUT" if is_option else "FUTCOM"
    if is_option:
        return "OPTIDX" if is_index_underlying else "OPTSTK"
    return "FUTIDX" if is_index_underlying else "FUTSTK"


def chart_exchange(exchange):
    """The chart route's `{exc}`: indices chart under INDEX."""
    if exchange in OA_INDEX_EXCHANGES:
        return "INDEX"
    return exchange
