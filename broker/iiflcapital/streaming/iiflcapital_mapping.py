"""
Helpers for translating between OpenAlgo's market-data conventions and the
IIFL Capital feed's segment/topic conventions.

The contract-master loader (broker/iiflcapital/database/master_contract_db.py)
already stores the IIFL segment in the `brexchange` column of `SymToken`:

    OpenAlgo exchange  →  brexchange
    -----------------     ----------
    NSE                  NSEEQ
    BSE                  BSEEQ
    NFO                  NSEFO
    BFO                  BSEFO
    CDS                  NSECURR
    BCD                  BSECURR
    MCX                  NSECOMM | MCXCOMM | NCDEXCOMM
    NSE_INDEX            NSEEQ        (CSV column stored verbatim)
    BSE_INDEX            BSEEQ        (CSV column stored verbatim)

The IIFL MQTT topic suffix is just `{brexchange.lower()}/{token}` — see
bridgePy/connector.py subscribe_feed/subscribe_index docstrings.
"""

from __future__ import annotations

# OpenAlgo exchanges that are routed to the index MQTT topic prefix
# (prod/marketfeed/index/v1/...) rather than the market feed prefix.
INDEX_EXCHANGES: frozenset[str] = frozenset(
    {"NSE_INDEX", "BSE_INDEX", "MCX_INDEX", "GLOBAL_INDEX"}
)

# OpenAlgo exchanges that support open-interest data. Anything outside this
# set has no OI stream — saves a wasted SUBSCRIBE frame.
OI_ELIGIBLE_EXCHANGES: frozenset[str] = frozenset({"NFO", "BFO", "CDS", "BCD", "MCX"})


def is_index_exchange(exchange: str) -> bool:
    return exchange in INDEX_EXCHANGES


def supports_open_interest(exchange: str) -> bool:
    return exchange in OI_ELIGIBLE_EXCHANGES


def normalize_segment(brexchange: str | None) -> str:
    """Lower-case the brexchange string for use in MQTT topic suffixes."""
    if not brexchange:
        return ""
    return brexchange.strip().lower()
