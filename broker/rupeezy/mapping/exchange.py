# broker/rupeezy/mapping/exchange.py
#
# OpenAlgo <-> Rupeezy Vortex exchange vocabulary, index naming, tickers and
# quantity units. Shared by the REST, master-contract and streaming layers.
#
# Vortex exchanges (master.csv `exchange` column, verified against the live
# file): NSE_EQ, BSE_EQ, NSE_FO, BSE_FO, MCX_FO. Indices live inside NSE_EQ /
# BSE_EQ with instrument_name EQIDX, so the OpenAlgo exchange is derived from
# (exchange, instrument_name), not from the exchange alone.
#
# Every Vortex REST/WS call takes a `ticker` of the form "<NSE|BSE|MCX>:<sym>"
# (e.g. NSE:RELIANCE, NSE:NIFTYIDX, MCX:CRUDEOIL28MARFUT). SymToken stores the
# part after the colon as `brsymbol` and the Vortex exchange as `brexchange`,
# so the ticker is rebuilt as f"{brexchange[:3]}:{brsymbol}".

# Vortex exchange -> OpenAlgo exchange for tradable (non-index) rows.
VORTEX_TO_OA_EXCHANGE = {
    "NSE_EQ": "NSE",
    "BSE_EQ": "BSE",
    "NSE_FO": "NFO",
    "BSE_FO": "BFO",
    "MCX_FO": "MCX",
}

# Vortex exchange -> OpenAlgo exchange for EQIDX rows.
VORTEX_INDEX_EXCHANGE = {
    "NSE_EQ": "NSE_INDEX",
    "BSE_EQ": "BSE_INDEX",
}

OA_TO_VORTEX_EXCHANGE = {
    "NSE": "NSE_EQ",
    "BSE": "BSE_EQ",
    "NFO": "NSE_FO",
    "BFO": "BSE_FO",
    "MCX": "MCX_FO",
    "NSE_INDEX": "NSE_EQ",
    "BSE_INDEX": "BSE_EQ",
}

# Vortex index `symbol` -> canonical OpenAlgo index symbol
# (docs/prompt/symbol-format.md). Keyed per exchange because NSE and BSE both
# publish INFRA / REALTY. Indices not listed keep the Vortex symbol.
NSE_INDEX_SYMBOLS = {
    "AUTO": "NIFTYAUTO",
    "BEESNAV": "HANGSENGBEESNAV",
    "COMMODITIES": "NIFTYCOMMODITIES",
    "CONSUMPTION": "NIFTYCONSUMPTION",
    "DIVOPPS": "NIFTYDIVOPPS50",
    "DIVPOINT": "NIFTY50DIVPOINT",
    "ENEGRY": "NIFTYENERGY",
    "FMCG": "NIFTYFMCG",
    "GROWTH": "NIFTYGROWSECT15",
    "INFRA": "NIFTYINFRA",
    "MEDIA": "NIFTYMEDIA",
    "METAL": "NIFTYMETAL",
    "MNC": "NIFTYMNC",
    "PHARMA": "NIFTYPHARMA",
    "REALTY": "NIFTYREALTY",
    "SERVICE": "NIFTYSERVSECTOR",
    "VALUE20": "NIFTY50VALUE20",
    "NIFGS10YRCLN": "NIFTYGS10YRCLN",
    "NIFGS1115YR": "NIFTYGS1115YR",
    "NIFGS15YRPLS": "NIFTYGS15YRPLUS",
    "NIFGSCOMPS": "NIFTYGSCOMPSITE",
    "NIFTY100EQL": "NIFTY100EQLWGT",
    "NIFTY100ESGSL": "NIFTY100ESGSECLDR",
    "NIFTY100LV30": "NIFTY100LOWVOL30",
    "NIFTY200MTM30": "NIFTY200MOMENTM30",
    "NIFTY200QT30": "NIFTY200QUALTY30",
    "NIFTY500MTCAP": "NIFTY500MULTICAP",
    "NIFTY50EQL": "NIFTY50EQLWGT",
    "NIFTYALOWVOL": "NIFTYALPHALOWVOL",
    "NIFTYCONDUR": "NIFTYCONSRDURBL",
    "NIFTYFINS2550": "NIFTYFINSRV2550",
    "NIFTYHELCARE": "NIFTYHEALTHCARE",
    "NIFTYLIQ15": "NIFTY100LIQ15",
    "NIFTYLMID250": "NIFTYLARGEMID250",
    "NIFTYMCAP150": "NIFTYMIDCAP150",
    "NIFTYMDSL400": "NIFTYMIDSML400",
    "NIFTYMIC250": "NIFTYMICROCAP250",
    "NIFTYMID100": "NIFTYMIDCAP100",
    "NIFTYMID50": "NIFTYMIDCAP50",
    "NIFTYMIDLQ15": "NIFTYMIDLIQ15",
    "NIFTYMLTINF": "NIFTYMULTIINFRA",
    "NIFTYMLTMFG": "NIFTYMULTIMFG",
    "NIFTYMSHLTH": "NIFTYMIDSMLHLTH",
    "NIFTYOIL&GAS": "NIFTYOILANDGAS",
    "NIFTYPR1X": "NIFTY50PR1XINV",
    "NIFTYPR2X": "NIFTY50PR2XLEV",
    "NIFTYQTY30": "NIFTYQUALITY30",
    "NIFTYSCAP250": "NIFTYSMLCAP250",
    "NIFTYSCAP50": "NIFTYSMLCAP50",
    "NIFTYSMALL": "NIFTYSMLCAP100",
    "NIFTYTATA25": "NIFTYTATA25CAP",
    "NIFTYTR1X": "NIFTY50TR1XINV",
    "NIFTYTR2X": "NIFTY50TR2XLEV",
}

BSE_INDEX_SYMBOLS = {
    "ALLCAP": "BSEALLCAP",
    "BHRT22": "BSEBHARAT22INDEX",
    "BSECD": "BSECONSUMERDURABLES",
    "BSECG": "BSECAPITALGOODS",
    "BSEFMC": "BSEFASTMOVINGCONSUMERGOODS",
    "BSEHC": "BSEHEALTHCARE",
    "BSEIT": "BSEINFORMATIONTECHNOLOGY",
    "BSEMETL": "BSEMETAL",
    "BSEPBI": "BSEPRIVATEBANKS",
    "CARBON": "BSECARBONEX",
    "CONDIS": "BSECONSUMERDISCRETIONARYGOODS&SERVICES",
    "DFRGRI": "BSEDIVERSIFIEDFINANCIALSREVENUEGROWTHINDEX",
    "DOL100": "BSEDOLLEX100",
    "DOL200": "BSEDOLLEX200",
    "DOL30": "BSEDOLLEX30",
    "ENERGY": "BSEENERGY",
    "ESG100": "BSE100ESG",
    "FINSER": "BSEFINANCIALSERVICES",
    "GREENX": "BSEGREENEX",
    "INDSTR": "BSEINDUSTRIALS",
    "INFRA": "BSEINDIAINFRASTRUCTUREINDEX",
    "LCTMCI": "BSE100LARGECAPTMCINDEX",
    "LMI250": "BSE250LARGEMIDCAPINDEX",
    "LRGCAP": "BSELARGECAP",
    "MFG": "BSEINDIAMANUFACTURING",
    "MID150": "BSE150MIDCAPINDEX",
    "MIDCAP": "BSEMIDCAP",
    "MIDSEL": "BSEMIDCAPSELECTINDEX",
    "MSL400": "BSE400MIDSMALLCAPINDEX",
    "OILGAS": "BSEOIL&GAS",
    "POWER": "BSEPOWER",
    "REALTY": "BSEREALTY",
    "SML250": "BSE250SMALLCAPINDEX",
    "SMLCAP": "BSESMALLCAP",
    "SMLSEL": "BSESMALLCAPSELECTINDEX",
    "SMEIPO": "BSESMEIPO",
    "SNSX50": "SENSEX50",
    "SNXT50": "BSESENSEXNEXT50",
    "TELCOM": "BSETELECOM",
    "UTILS": "BSEUTILITIES",
}

INDEX_SYMBOLS = {"NSE_INDEX": NSE_INDEX_SYMBOLS, "BSE_INDEX": BSE_INDEX_SYMBOLS}


def to_oa_index_symbol(vortex_symbol, oa_exchange):
    """Vortex index symbol (master `symbol` column) -> OpenAlgo index symbol."""
    return INDEX_SYMBOLS.get(oa_exchange, {}).get(vortex_symbol, vortex_symbol)


def build_ticker(brexchange, brsymbol):
    """SymToken (brexchange, brsymbol) -> Vortex ticker, e.g. ("NSE_FO", "NIFTY26OCTFUT")
    -> "NSE:NIFTY26OCTFUT"."""
    return f"{str(brexchange)[:3]}:{brsymbol}"


def split_ticker(ticker):
    """Vortex ticker -> brsymbol (the part after the exchange prefix)."""
    ticker = str(ticker or "")
    return ticker.split(":", 1)[1] if ":" in ticker else ticker


def oa_exchange_for(vortex_exchange):
    """Vortex exchange on a book row (NSE_EQ / NSE_FO / ...) -> OpenAlgo exchange.
    Book rows are never indices, so the tradable map is enough."""
    return VORTEX_TO_OA_EXCHANGE.get(str(vortex_exchange or "").upper(), vortex_exchange)


# --- Quantity units -----------------------------------------------------
#
# OpenAlgo's convention is units everywhere (CRUDEOIL lot 100 -> one lot is
# quantity 100), see broker/zerodha/mapping/mcx_contract_size.py.
#
# Vortex: "For NSE_FO, if you want to trade 2 lots and lot size is 50, you
# should pass 100. In all other exchanges, you should pass just the number of
# lots. For example, in MCX_FO ... pass just 5." Positions follow the same rule
# ("For NSE_CUR & MCX_FO actual quantity = quantity * lot_size * multiplier").
# Equity lot size is 1 so NSE_EQ/BSE_EQ are unaffected.
#
# TODO(rupeezy): BSE_FO is not named in that rule. It is treated like NSE_FO
# (units) because the exchange itself trades BSE derivatives in units; verify
# with one live SENSEX order before relying on it.
_LOT_DENOMINATED = {"MCX_FO"}


def to_vortex_quantity(quantity, brexchange, lotsize):
    """OpenAlgo units -> Vortex order quantity. Raises ValueError when an MCX
    quantity is not a whole number of lots (the same refusal other brokers give)."""
    quantity = int(quantity)
    if brexchange in _LOT_DENOMINATED:
        lot = int(lotsize or 1)
        if lot > 1:
            if quantity % lot:
                raise ValueError(f"Quantity {quantity} is not a multiple of the lot size {lot}.")
            return quantity // lot
    return quantity


def from_vortex_quantity(quantity, brexchange, lotsize):
    """Vortex book quantity -> OpenAlgo units."""
    try:
        quantity = int(float(quantity or 0))
    except (TypeError, ValueError):
        return 0
    if brexchange in _LOT_DENOMINATED:
        return quantity * int(lotsize or 1)
    return quantity
