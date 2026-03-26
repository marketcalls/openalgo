"""
Mudrex symbol resolution helpers.

Accept OpenAlgo crypto symbols coming from either exchange family code
(`CRYPTO_FUT` preferred, `CRYPTO` tolerated) and resolve to Mudrex/Bybit native
symbol used in REST and WS calls.
"""

from database.token_db import get_br_symbol


def resolve_mudrex_brsymbol(symbol: str, exchange: str | None) -> str:
    """
    Resolve canonical OpenAlgo symbol to Mudrex native symbol.

    Fallback strategy:
    1) lookup with provided exchange
    2) lookup with CRYPTO_FUT
    3) lookup with CRYPTO
    4) if canonical perpetual ends with FUT, strip FUT suffix
    5) return raw input as last resort
    """
    ex = (exchange or "").upper()
    sym = (symbol or "").strip()

    seen: set[str] = set()
    for candidate_ex in (ex, "CRYPTO_FUT", "CRYPTO"):
        if not candidate_ex or candidate_ex in seen:
            continue
        seen.add(candidate_ex)
        br = get_br_symbol(sym, candidate_ex)
        if br:
            return br

    upper_sym = sym.upper()
    if upper_sym.endswith("FUT") and len(upper_sym) > 3:
        return upper_sym[:-3]
    return sym
