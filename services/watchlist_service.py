# services/watchlist_service.py
"""
Turning a pasted list of symbols into watchlist rows.

A trader building a list pastes it from wherever they keep it: a spreadsheet
column, a note, an export from another charting platform. So the input is
loose text, and every name in it has to be resolved to an instrument the
connected broker actually has before it is stored. A row the broker does not
know would sit in the list forever showing a dash.

Resolution is an exact match against the broker's master contract, one lookup
for the whole paste (see ``_known_pairs``). Nothing is matched by
prefix or similarity: adding the wrong instrument silently is worse than
reporting the name as not found.
"""

import re

from sqlalchemy import tuple_

from database.symbol import SymToken
from database.token_db_enhanced import get_cache
from utils.logging import get_logger

logger = get_logger(__name__)

#: Bounds the work one paste can cause. Well above a list's own cap of 250, so
#: a paste with duplicates or unknown names is never cut short in practice.
MAX_TOKENS = 500

#: Bounds the text itself, before it is split.
MAX_TEXT_LENGTH = 20000

#: Where a name with no exchange is looked for, in order. Cash before index,
#: so RELIANCE is the stock; NIFTY is not a stock on either exchange and falls
#: through to the index. Derivatives last: their names are long and specific,
#: so they never collide with a cash name.
BARE_ORDER = (
    "NSE",
    "BSE",
    "NSE_INDEX",
    "BSE_INDEX",
    "NFO",
    "BFO",
    "MCX",
    "CDS",
    "BCD",
    "NCDEX",
    "NCO",
    "MCX_INDEX",
    "CDS_INDEX",
    "GLOBAL_INDEX",
    "CRYPTO",
)

#: An exchange prefix also tries its index exchange. Other charting platforms
#: write an index as `NSE:NIFTY`, which OpenAlgo files under NSE_INDEX.
PREFIX_FALLBACK = {
    "NSE": ("NSE", "NSE_INDEX"),
    "BSE": ("BSE", "BSE_INDEX"),
    "MCX": ("MCX", "MCX_INDEX"),
    "CDS": ("CDS", "CDS_INDEX"),
}

#: Commas, semicolons, and any whitespace including new lines and tabs.
_SEPARATORS = re.compile(r"[,;\s]+")

_EXCHANGE_CODE = re.compile(r"[A-Z_]+")

#: Pairs per query when the master contract is read from the database. Two
#: bound parameters each, well inside SQLite's limit on bound variables.
_DB_BATCH = 400


def parse_symbol_list(text: str) -> list[str]:
    """Split pasted text into distinct names, upper-cased, in the order given.

    Section markers written as ``###NAME`` are dropped: a watchlist has no
    sections yet, and reporting them as unknown symbols would be noise.
    Surrounding quotes are stripped, since a spreadsheet copy often carries
    them.
    """
    if not text:
        return []
    tokens: list[str] = []
    seen: set[str] = set()
    for raw in _SEPARATORS.split(text[:MAX_TEXT_LENGTH]):
        token = raw.strip().strip("'\"").upper()
        if not token or token.startswith("#") or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
        if len(tokens) >= MAX_TOKENS:
            break
    return tokens


def _spellings(symbol: str) -> list[str]:
    """The name as written, then the forms other platforms spell differently.

    An underscore is how some platforms write the hyphen and ampersand that
    OpenAlgo symbols carry (``BAJAJ_AUTO`` for BAJAJ-AUTO, ``M_M`` for M&M).
    No OpenAlgo symbol contains an underscore, so trying both is safe.
    """
    if "_" not in symbol:
        return [symbol]
    return [symbol, symbol.replace("_", "-"), symbol.replace("_", "&")]


def _candidates(token: str) -> list[tuple[str, str]]:
    """Every (symbol, exchange) pair a token could mean, most likely first."""
    if ":" in token:
        exchange, _, symbol = token.partition(":")
        # An exchange code is letters and underscores. `A:B:C` or `1:X` is not
        # a prefix, and looking it up would only ever miss.
        if not _EXCHANGE_CODE.fullmatch(exchange):
            return []
        exchanges = PREFIX_FALLBACK.get(exchange, (exchange,))
    else:
        symbol = token
        exchanges = BARE_ORDER
    if not symbol:
        return []
    return [(name, exchange) for exchange in exchanges for name in _spellings(symbol)]


def _known_pairs(pairs: list[tuple[str, str]]) -> set[tuple[str, str]]:
    """The (symbol, exchange) pairs the broker's master contract contains.

    From the in-memory symbol cache when it is loaded, which is every lookup
    after a broker login. Otherwise from the database in batches: the cache's
    own fallback is one query per pair, and a paste is checked against every
    exchange a name might be on, so even a short list would be hundreds of
    queries on the single worker.
    """
    snap = get_cache().valid_snapshot()
    if snap is not None:
        index = snap.by_symbol_exchange
        return {pair for pair in pairs if pair in index}

    known: set[tuple[str, str]] = set()
    for start in range(0, len(pairs), _DB_BATCH):
        batch = pairs[start : start + _DB_BATCH]
        rows = (
            SymToken.query.with_entities(SymToken.symbol, SymToken.exchange)
            .filter(tuple_(SymToken.symbol, SymToken.exchange).in_(batch))
            .all()
        )
        known.update((row.symbol, row.exchange) for row in rows)
    return known


def resolve_symbols(tokens: list[str]) -> tuple[list[dict], list[str]]:
    """Resolve names to instruments the broker has.

    Returns ``(found, not_found)``: ``found`` is a list of ``{"symbol",
    "exchange"}`` in input order, ``not_found`` the tokens as the user wrote
    them. Two tokens that resolve to the same instrument (``INFY`` and
    ``NSE:INFY``) are returned once.
    """
    plans = [(token, _candidates(token)) for token in tokens]
    pairs = list(dict.fromkeys(pair for _, candidates in plans for pair in candidates))
    if not pairs:
        return [], list(tokens)

    try:
        known = _known_pairs(pairs)
    except Exception:
        logger.exception("Could not look up %d pasted symbols", len(pairs))
        return [], list(tokens)

    found: list[dict] = []
    not_found: list[str] = []
    seen: set[tuple[str, str]] = set()
    for token, candidates in plans:
        match = next((pair for pair in candidates if pair in known), None)
        if match is None:
            not_found.append(token)
        elif match not in seen:
            seen.add(match)
            found.append({"symbol": match[0], "exchange": match[1]})
    return found, not_found
