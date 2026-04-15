"""
Common NSE_INDEX / BSE_INDEX symbol normalization for OpenAlgo.

Each broker delivers index names in its own house style (e.g. Motilal sends
"NIFTY 50", Zerodha sends "NIFTY 50", some send "NIFTYNEXT50"). OpenAlgo needs
a single canonical form per symbol_Openalgo.md so APIs, the SymToken DB, and
the UI all agree. This module is the single place that mapping lives.

Behaviour:
- For NSE_INDEX, the broker symbol is upper-cased and whitespace-stripped,
  then looked up in NSE_INDEX_ALIASES. If still not canonical, it is returned
  as-is (unlisted symbols pass through unchanged, per OpenAlgo policy).
- For BSE_INDEX, the broker symbol is matched against BSE_INDEX_ALIASES first
  (BSE house-style names contain spaces and abbreviations that can't be auto-
  derived, e.g. "BSE CAPGOOD" -> "BSECAPITALGOODS"). Unmatched symbols pass
  through unchanged.

Add a new alias entry whenever a broker is found to deliver a name that
doesn't normalize to its canonical OpenAlgo symbol via the simple upper+strip
rule. Aliases are keys; canonical OpenAlgo symbols are values.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Canonical NSE_INDEX symbols (OpenAlgo standard, per symbol_Openalgo.md)
# ---------------------------------------------------------------------------
OPENALGO_NSE_INDEX_SYMBOLS: frozenset[str] = frozenset(
    {
        "NIFTY",
        "NIFTYNXT50",
        "FINNIFTY",
        "BANKNIFTY",
        "MIDCPNIFTY",
        "INDIAVIX",
        "HANGSENGBEESNAV",
        "NIFTY100",
        "NIFTY200",
        "NIFTY500",
        "NIFTYALPHA50",
        "NIFTYAUTO",
        "NIFTYCOMMODITIES",
        "NIFTYCONSUMPTION",
        "NIFTYCPSE",
        "NIFTYDIVOPPS50",
        "NIFTYENERGY",
        "NIFTYFMCG",
        "NIFTYGROWSECT15",
        "NIFTYGS10YR",
        "NIFTYGS10YRCLN",
        "NIFTYGS1115YR",
        "NIFTYGS15YRPLUS",
        "NIFTYGS48YR",
        "NIFTYGS813YR",
        "NIFTYGSCOMPSITE",
        "NIFTYINFRA",
        "NIFTYIT",
        "NIFTYMEDIA",
        "NIFTYMETAL",
        "NIFTYMIDLIQ15",
        "NIFTYMIDCAP100",
        "NIFTYMIDCAP150",
        "NIFTYMIDCAP50",
        "NIFTYMIDSML400",
        "NIFTYMNC",
        "NIFTYPHARMA",
        "NIFTYPSE",
        "NIFTYPSUBANK",
        "NIFTYPVTBANK",
        "NIFTYREALTY",
        "NIFTYSERVSECTOR",
        "NIFTYSMLCAP100",
        "NIFTYSMLCAP250",
        "NIFTYSMLCAP50",
        "NIFTY100EQLWGT",
        "NIFTY100LIQ15",
        "NIFTY100LOWVOL30",
        "NIFTY100QUALTY30",
        "NIFTY200QUALTY30",
        "NIFTY50DIVPOINT",
        "NIFTY50EQLWGT",
        "NIFTY50PR1XINV",
        "NIFTY50PR2XLEV",
        "NIFTY50TR1XINV",
        "NIFTY50TR2XLEV",
        "NIFTY50VALUE20",
    }
)

# Broker-house-style NSE index name -> OpenAlgo canonical symbol. Keys are
# always upper-cased and whitespace-stripped before lookup, so add keys here
# in that form.
NSE_INDEX_ALIASES: dict[str, str] = {
    # Index of indices vs. the underlying NIFTY itself
    "NIFTY50": "NIFTY",
    "NIFTYNEXT50": "NIFTYNXT50",
    "NIFTYFINSERVICE": "FINNIFTY",
    "NIFTYFINSERV": "FINNIFTY",
    "NIFTYBANK": "BANKNIFTY",
    "NIFTYMIDSELECT": "MIDCPNIFTY",
    "NIFTYMIDCAPSELECT": "MIDCPNIFTY",
    "INDIAVIX": "INDIAVIX",
}

# ---------------------------------------------------------------------------
# Canonical BSE_INDEX symbols (OpenAlgo standard, per symbol_Openalgo.md)
# ---------------------------------------------------------------------------
OPENALGO_BSE_INDEX_SYMBOLS: frozenset[str] = frozenset(
    {
        "SENSEX",
        "BANKEX",
        "SENSEX50",
        "BSE100",
        "BSE150MIDCAPINDEX",
        "BSE200",
        "BSE250LARGEMIDCAPINDEX",
        "BSE400MIDSMALLCAPINDEX",
        "BSE500",
        "BSEAUTO",
        "BSECAPITALGOODS",
        "BSECARBONEX",
        "BSECONSUMERDURABLES",
        "BSECPSE",
        "BSEDOLLEX100",
        "BSEDOLLEX200",
        "BSEDOLLEX30",
        "BSEENERGY",
        "BSEFASTMOVINGCONSUMERGOODS",
        "BSEFINANCIALSERVICES",
        "BSEGREENEX",
        "BSEHEALTHCARE",
        "BSEINDIAINFRASTRUCTUREINDEX",
        "BSEINDUSTRIALS",
        "BSEINFORMATIONTECHNOLOGY",
        "BSEIPO",
        "BSELARGECAP",
        "BSEMETAL",
        "BSEMIDCAP",
        "BSEMIDCAPSELECTINDEX",
        "BSEOIL&GAS",
        "BSEPOWER",
        "BSEPSU",
        "BSEREALTY",
        "BSESENSEXNEXT50",
        "BSESMALLCAP",
        "BSESMALLCAPSELECTINDEX",
        "BSESMEIPO",
        "BSETECK",
        "BSETELECOM",
    }
)

# Broker-house-style BSE index name -> OpenAlgo canonical symbol. Keys are
# matched against the raw broker symbol (case-insensitive, whitespace
# preserved) so add the exact string the broker delivers.
BSE_INDEX_ALIASES: dict[str, str] = {
    "BSE SENSEX": "SENSEX",
    "BSE BANKEX": "BANKEX",
    "SNSX50": "SENSEX50",
    "BSE 100": "BSE100",
    "BSE 150 MIDCAP": "BSE150MIDCAPINDEX",
    "BSE 200": "BSE200",
    "BSE 250 LARGEMIDCAP": "BSE250LARGEMIDCAPINDEX",
    "BSE 400 MIDSMALLCAP": "BSE400MIDSMALLCAPINDEX",
    "BSE 500": "BSE500",
    "BSE AUTO": "BSEAUTO",
    "BSE CAPGOOD": "BSECAPITALGOODS",
    "BSE CARBON": "BSECARBONEX",
    "BSE CONSDUR": "BSECONSUMERDURABLES",
    "BSE CPSE": "BSECPSE",
    "BSE DOLLEX 100": "BSEDOLLEX100",
    "BSE DOLLEX 200": "BSEDOLLEX200",
    "BSE DOLLEX 30": "BSEDOLLEX30",
    "BSE ENERGY": "BSEENERGY",
    "BSE FMCG": "BSEFASTMOVINGCONSUMERGOODS",
    "BSE FINANCIAL SERVICES": "BSEFINANCIALSERVICES",
    "BSE GREENEX": "BSEGREENEX",
    "BSE HEALTHCARE": "BSEHEALTHCARE",
    "BSE INFRA": "BSEINDIAINFRASTRUCTUREINDEX",
    "BSE INDUSTRIALS": "BSEINDUSTRIALS",
    "BSE IT": "BSEINFORMATIONTECHNOLOGY",
    "BSE IPO": "BSEIPO",
    "BSE LARGECAP": "BSELARGECAP",
    "BSE METAL": "BSEMETAL",
    "BSE MIDCAP": "BSEMIDCAP",
    "BSE MIDCAP SELECT": "BSEMIDCAPSELECTINDEX",
    "BSE OIL&GAS": "BSEOIL&GAS",
    "BSE POWER": "BSEPOWER",
    "BSE PSU": "BSEPSU",
    "BSE REALTY": "BSEREALTY",
    "SNXT50": "BSESENSEXNEXT50",
    "BSE SMALLCAP": "BSESMALLCAP",
    "BSE SMALLCAP SELECT": "BSESMALLCAPSELECTINDEX",
    "BSE SME IPO": "BSESMEIPO",
    "BSE TECK": "BSETECK",
    "BSE TELECOM": "BSETELECOM",
}

# Pre-built upper-cased alias view for BSE so callers can do a single
# case-insensitive lookup without recomputing on every row.
_BSE_INDEX_ALIASES_UPPER: dict[str, str] = {
    k.upper(): v for k, v in BSE_INDEX_ALIASES.items()
}

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_nse_index_symbol(broker_symbol: str) -> str:
    """
    Map a broker-supplied NSE index name to its OpenAlgo canonical form.

    Algorithm:
      1. Upper-case + strip whitespace.
      2. Look up in NSE_INDEX_ALIASES.
      3. Otherwise return the upper-cased/stripped form (passes through
         canonical names like "NIFTYIT" unchanged, and unlisted indices
         remain whatever the broker sent — minus whitespace/case).
    """
    if not broker_symbol:
        return broker_symbol
    cleaned = _WHITESPACE_RE.sub("", str(broker_symbol).upper())
    return NSE_INDEX_ALIASES.get(cleaned, cleaned)


def normalize_bse_index_symbol(broker_symbol: str) -> str:
    """
    Map a broker-supplied BSE index name to its OpenAlgo canonical form.

    Algorithm:
      1. Look the raw broker symbol up in BSE_INDEX_ALIASES (case-insensitive,
         whitespace preserved). BSE house-style names contain spaces and
         abbreviations that can't be auto-derived, e.g. "BSE CAPGOOD" ->
         "BSECAPITALGOODS", so the alias map must run first.
      2. If no alias matches, fall back to upper-case + strip whitespace so
         unlisted indices still come out in canonical OpenAlgo form
         ("BSE 1000" -> "BSE1000") instead of leaking the broker's spacing.
    """
    if not broker_symbol:
        return broker_symbol
    raw = str(broker_symbol)
    aliased = _BSE_INDEX_ALIASES_UPPER.get(raw.upper())
    if aliased is not None:
        return aliased
    return _WHITESPACE_RE.sub("", raw.upper())


def normalize_index_symbol(broker_symbol: str, exchange: str) -> str:
    """
    Single entry point dispatching on exchange. Brokers can call this from
    their master_contract loaders without caring about NSE vs BSE rules.
    """
    if exchange == "NSE_INDEX":
        return normalize_nse_index_symbol(broker_symbol)
    if exchange == "BSE_INDEX":
        return normalize_bse_index_symbol(broker_symbol)
    return broker_symbol
