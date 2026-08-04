"""
Nubra instrument resolution (Nubra -> OpenAlgo).

Nubra's exchange vocabulary has exactly three values -- NSE, BSE and MCX. It has
no NFO or BFO: an NSE option comes back as ``exchange: "NSE"`` with
``derivativeType: "OPT"``, while the master contract stores that same row as
``exchange='NFO', brexchange='NSE'``.

Everything keyed on the OpenAlgo exchange therefore misses unless that is folded
back first -- ``get_symbol``, ``get_oa_symbol`` and ``get_token`` are all keyed
on the OpenAlgo exchange, and so is the ``pos_exchange == exchange`` comparison
in the smart-order path.

The fold is not asserted, it is **confirmed**: Nubra's cash exchange plus
``derivativeType`` only decides which OpenAlgo exchanges are worth trying, and
the answer returned is the one the master contract actually matched. When no
row matches, the resolver returns ``(None, None)`` so the caller can say so
rather than substituting a plausible-looking guess.

The opposite direction (OpenAlgo -> Nubra, used when subscribing to the market
feed) lives in ``streaming/nubra_mapping.py``.
"""

from database.token_db import get_oa_symbol, get_symbol

# Nubra cash exchange -> the OpenAlgo derivatives exchange its F&O rows live
# under. MCX is absent on purpose: Nubra reports commodity futures and options
# as "MCX", which is already the OpenAlgo exchange for them.
_DERIVATIVE_EXCHANGE = {
    "NSE": "NFO",
    "BSE": "BFO",
}

# ``derivativeType`` values that mean "this is an F&O contract". Cash rows carry
# "STOCK"; index rows never appear on the order or position paths.
_DERIVATIVE_TYPES = ("OPT", "FUT")


def to_openalgo_exchange(exchange, derivative_type=None):
    """
    Fold a Nubra (exchange, derivativeType) pair into the OpenAlgo exchange.

    This is the unconfirmed form, for callers that only need a label. Prefer
    ``resolve_instrument()`` wherever the result is used as a lookup key.
    """
    nubra_exchange = str(exchange or "").upper()
    if str(derivative_type or "").upper() in _DERIVATIVE_TYPES:
        return _DERIVATIVE_EXCHANGE.get(nubra_exchange, nubra_exchange)
    return nubra_exchange


def candidate_exchanges(exchange, derivative_type=None):
    """
    OpenAlgo exchanges worth probing for a Nubra row, most likely first.

    A known ``derivativeType`` narrows this to exactly one candidate. When it is
    missing or unrecognised, both the derivatives and the cash exchange are
    offered so resolution still succeeds off the master contract instead of
    depending on a field Nubra may not have sent.
    """
    nubra_exchange = str(exchange or "").upper()
    if not nubra_exchange:
        return ()

    derivative = _DERIVATIVE_EXCHANGE.get(nubra_exchange)
    dtype = str(derivative_type or "").upper()

    if dtype in _DERIVATIVE_TYPES:
        return (derivative,) if derivative else (nubra_exchange,)
    if dtype:
        # A recognised non-derivative type ("STOCK") is authoritative.
        return (nubra_exchange,)
    return (derivative, nubra_exchange) if derivative else (nubra_exchange,)


def resolve_instrument(exchange, derivative_type=None, ref_id=None, broker_symbol=None):
    """
    Resolve a Nubra instrument to (OpenAlgo symbol, OpenAlgo exchange).

    Both values come from the master contract row that matched, so the exchange
    is confirmed rather than inferred. ``ref_id`` is tried first because that is
    what Nubra stores in ``symtoken.token``; the broker symbol is the second
    key, matching the brsymbol-keyed lookup.

    Returns:
        ``(symbol, exchange)``, or ``(None, None)`` when nothing matched.
    """
    ref_id = str(ref_id or "").strip()
    broker_symbol = str(broker_symbol or "").strip()

    for candidate in candidate_exchanges(exchange, derivative_type):
        if ref_id:
            symbol = get_symbol(ref_id, candidate)
            if symbol:
                return symbol, candidate
        if broker_symbol:
            symbol = get_oa_symbol(broker_symbol, candidate)
            if symbol:
                return symbol, candidate

    return None, None


def derivative_type_of(row):
    """
    Read ``derivativeType`` from a V3 order, position or refData object.

    Order rows carry it on ``refData`` (and on ``legs[0].refData`` for strategy
    orders and for the single orders Nubra returns as ``isMulti: true``), while
    position rows carry it at the top level.
    """
    if not isinstance(row, dict):
        return ""

    for candidate in (row, row.get("refData")):
        if isinstance(candidate, dict) and candidate.get("derivativeType"):
            return str(candidate["derivativeType"])

    legs = row.get("legs")
    if isinstance(legs, list) and legs and isinstance(legs[0], dict):
        leg_ref_data = legs[0].get("refData")
        if isinstance(leg_ref_data, dict) and leg_ref_data.get("derivativeType"):
            return str(leg_ref_data["derivativeType"])

    return ""


def nubra_exchange_of(row):
    """Nubra exchange for a V3 order or position row, top level or refData."""
    if not isinstance(row, dict):
        return ""

    exchange = row.get("exchange")
    if not exchange:
        for source in (row.get("refData"), *(row.get("legs") or [])[:1]):
            if isinstance(source, dict):
                exchange = source.get("exchange") or (source.get("refData") or {}).get("exchange")
                if exchange:
                    break

    return str(exchange or "")
