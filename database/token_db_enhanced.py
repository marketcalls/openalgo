"""
Enhanced Token DB with Full Memory Caching for 100,000+ symbols
Optimized for zero-config deployment with configurable session reset time (SESSION_EXPIRY_TIME)
"""

import heapq
import re
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pytz

from utils.constants import CRYPTO_EXCHANGES, FNO_EXCHANGES
from utils.logging import get_logger

logger = get_logger(__name__)

# Regex pattern to extract underlying from OpenAlgo symbol format
# Format: [BaseSymbol][DDMMMYY][StrikePrice][CE/PE] or [BaseSymbol][DDMMMYY]FUT
# Examples: NIFTY28MAR2420800CE, BANKNIFTY24APR24FUT, CRUDEOIL17APR246750CE
_UNDERLYING_PATTERN = re.compile(
    r"^(.+?)"  # Underlying (non-greedy capture)
    r"(\d{2}(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2})"  # Date: DDMMMYY
    r"(?:\d+(?:\.\d+)?)?(?:FUT|CE|PE)?$",  # Optional strike + FUT/CE/PE
    re.IGNORECASE,
)

# Regex to extract underlying from canonical CRYPTO symbols that follow the
# Indian F&O-style format (no dashes): BTC28FEB2580000CE / BTC28FEB25FUT
# The underlying is the run of leading alpha characters before the first digit.
# Perpetuals (BTCUSDT) have no embedded digit — handled separately via suffix stripping.
# Anchored to expiry date pattern (DDMMMYY) so numeric-prefix underlyings like
# 1INCH28FEB25FUT are handled correctly. Non-greedy capture stops at first DDMMMYY match.
_CRYPTO_UNDERLYING_PATTERN = re.compile(
    r"^([A-Z0-9]+?)(?=\d{2}[A-Z]{3}\d{2})",
    re.IGNORECASE,
)


def extract_underlying_from_symbol(symbol: str, exchange: str) -> str | None:
    """
    Extract underlying name from OpenAlgo symbol format.

    OpenAlgo symbol formats:
    - Indian FNO / CRYPTO options+futures:
        [BaseSymbol][DDMMMYY][Strike][CE/PE]  e.g. NIFTY28MAR2420800CE  → NIFTY
        [BaseSymbol][DDMMMYY]FUT              e.g. BTC28FEB25FUT         → BTC
      Underlying = leading alpha characters before the first digit.
    - CRYPTO perpetuals: BTCUSDT / ETHUSDT
      Underlying = strip trailing USDT or USD quote-currency suffix.

    Args:
        symbol: OpenAlgo formatted symbol
        exchange: Exchange code (NFO, BFO, MCX, CDS, CRYPTO, etc.)

    Returns:
        Underlying name or None if not extractable
    """
    if not symbol or exchange not in FNO_EXCHANGES:
        return None

    if exchange in CRYPTO_EXCHANGES:
        upper = symbol.upper()
        # FUT / CE / PE canonical: underlying is leading alpha-nums before DDMMMYY expiry
        # e.g. BTC28FEB2580000CE → BTC,  1INCH28FEB25FUT → 1INCH
        m = _CRYPTO_UNDERLYING_PATTERN.match(upper)
        if m:
            return m.group(1)
        # Perpetual canonical: BTCUSD.P / BTC_INR.P — strip .P then quote-currency suffix
        if upper.endswith(".P"):
            upper = upper[:-2]
        for suffix in ("USDT", "USD", "_INR", "INR"):
            if upper.endswith(suffix) and len(upper) > len(suffix):
                return upper[: -len(suffix)]
        return upper  # fallback — return whole symbol

    match = _UNDERLYING_PATTERN.match(symbol.upper())
    if match:
        return match.group(1)

    return None


@dataclass
class CacheStats:
    """Statistics for cache performance monitoring"""

    hits: int = 0
    misses: int = 0
    db_queries: int = 0
    bulk_queries: int = 0
    cache_loads: int = 0
    last_loaded: datetime | None = None
    total_symbols: int = 0
    memory_usage_mb: float = 0.0

    def get_hit_rate(self) -> float:
        """Calculate cache hit rate"""
        total = self.hits + self.misses
        return (self.hits / total * 100) if total > 0 else 0.0

    def to_dict(self) -> dict:
        """Convert stats to dictionary for API response"""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": f"{self.get_hit_rate():.2f}%",
            "db_queries": self.db_queries,
            "bulk_queries": self.bulk_queries,
            "cache_loads": self.cache_loads,
            "last_loaded": self.last_loaded.isoformat() if self.last_loaded else None,
            "total_symbols": self.total_symbols,
            "memory_usage_mb": f"{self.memory_usage_mb:.2f}",
        }


@dataclass
class SymbolData:
    """Lightweight symbol data structure for in-memory storage"""

    symbol: str
    brsymbol: str
    name: str
    exchange: str
    brexchange: str
    token: str
    expiry: str | None = None
    strike: float | None = None
    lotsize: int | None = None
    instrumenttype: str | None = None
    tick_size: float | None = None
    underlying: str | None = None  # Extracted from OpenAlgo symbol format for F&O
    contract_value: float | None = None  # Contract multiplier (e.g. 0.001 for BTCUSD.P)


@dataclass(frozen=True)
class _SymbolSnapshot:
    """One complete generation of the symbol cache, never modified once published.

    The cache used to be a set of dicts cleared and refilled in place. A
    reload then ran while readers iterated them: under the gthread worker a
    search could raise "dictionary changed size during iteration", or return
    the half of an expiry list loaded so far, which the option chain, IV and
    GEX pages presented as complete. Under eventlet the rebuild never yielded,
    so nobody saw it half done.

    Now a load builds a new snapshot off to the side and publishes it with one
    reference assignment, which is atomic in every runtime. A reader binds the
    snapshot once per call and sees either the whole old universe or the whole
    new one. Sets are frozensets and per-exchange lists are tuples, so nothing
    reachable from a published snapshot can change under a reader.
    """

    symbols: dict[str, SymbolData] = field(default_factory=dict)
    by_symbol_exchange: dict[tuple[str, str], SymbolData] = field(default_factory=dict)
    by_token_exchange: dict[tuple[str, str], SymbolData] = field(default_factory=dict)
    by_brsymbol_exchange: dict[tuple[str, str], SymbolData] = field(default_factory=dict)
    by_token: dict[str, SymbolData] = field(default_factory=dict)
    by_exchange: dict[str, tuple[SymbolData, ...]] = field(default_factory=dict)
    expiries_by_exchange: dict[str, frozenset[str]] = field(default_factory=dict)
    # Options-only: underlyings that have at least one CE/PE row. Used by
    # option-chain / IV-chart / GEX dropdowns where futures-only commodities
    # would be dead-ends.
    underlyings_by_exchange: dict[str, frozenset[str]] = field(default_factory=dict)
    # Tradable: union of options-bearing underlyings AND underlyings with at
    # least one non-expired FUT row. Used by the generic /search/token UI
    # where MCX commodities like NATURALGASMINI / LEADMINI / COPPER (FUT-only)
    # are legitimate trade-able instruments.
    tradable_underlyings_by_exchange: dict[str, frozenset[str]] = field(default_factory=dict)
    expiries_by_exchange_underlying: dict[tuple[str, str], frozenset[str]] = field(
        default_factory=dict
    )
    cache_loaded: bool = False
    active_broker: str | None = None
    session_start: datetime | None = None
    next_reset_time: datetime | None = None

    def is_valid(self) -> bool:
        """True when this snapshot is loaded and still inside its session."""
        if not self.cache_loaded or not self.next_reset_time:
            return False
        now_ist = datetime.now(pytz.timezone("Asia/Kolkata"))
        return now_ist < self.next_reset_time


def _unloaded(previous: _SymbolSnapshot) -> _SymbolSnapshot:
    """An empty, unloaded snapshot that keeps the previous session timing.

    Clearing used to empty the indexes and drop the loaded flag but leave the
    session start and reset time in place, and the cache status still reports
    them, so they are carried over.
    """
    return _SymbolSnapshot(
        session_start=previous.session_start,
        next_reset_time=previous.next_reset_time,
    )


def _session_timing() -> tuple[datetime, datetime]:
    """(session start, next reset) from SESSION_EXPIRY_TIME, in IST."""
    import os

    now_ist = datetime.now(pytz.timezone("Asia/Kolkata"))

    # Get session expiry time from environment (default to 3:00 if not set)
    expiry_time = os.getenv("SESSION_EXPIRY_TIME", "03:00")
    try:
        hour, minute = map(int, expiry_time.split(":"))
    except ValueError:
        logger.warning(f"Invalid SESSION_EXPIRY_TIME format: {expiry_time}. Using default 03:00")
        hour, minute = 3, 0

    # Calculate next expiry time
    next_reset = now_ist.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now_ist >= next_reset:
        next_reset += timedelta(days=1)

    logger.debug(f"Cache valid until: {next_reset} (Session expiry: {expiry_time})")
    return now_ist, next_reset


def _build_snapshot(symbols, broker: str) -> _SymbolSnapshot:
    """Build a complete, loaded snapshot from SymToken rows. Pure: no shared state."""
    by_symbol_exchange: dict[tuple[str, str], SymbolData] = {}
    by_token_exchange: dict[tuple[str, str], SymbolData] = {}
    by_brsymbol_exchange: dict[tuple[str, str], SymbolData] = {}
    by_token: dict[str, SymbolData] = {}
    primary: dict[str, SymbolData] = {}
    by_exchange: dict[str, list[SymbolData]] = defaultdict(list)
    expiries_by_exchange: dict[str, set[str]] = defaultdict(set)
    underlyings_by_exchange: dict[str, set[str]] = defaultdict(set)
    tradable_underlyings_by_exchange: dict[str, set[str]] = defaultdict(set)
    expiries_by_exchange_underlying: dict[tuple[str, str], set[str]] = defaultdict(set)

    # Today (IST) for the live-future check on the tradable underlyings index.
    # Computed once per cache load — cache invalidates at the daily session
    # reset (3 AM IST default), so a fresh `today` is picked up each day.
    ist_today = datetime.now(pytz.timezone("Asia/Kolkata")).date()
    # Tiny memo for repeated expiry strings (~thousands of FUT rows share
    # a few dozen distinct dates); strptime is cheap but not free.
    _expiry_date_cache: dict[str, "datetime.date | None"] = {}

    def _exp_to_date(exp_str):
        if not exp_str:
            return None
        cached = _expiry_date_cache.get(exp_str)
        if cached is not None or exp_str in _expiry_date_cache:
            return cached
        parsed = None
        for fmt in ("%d-%b-%y", "%d-%b-%Y"):
            try:
                parsed = datetime.strptime(exp_str, fmt).date()
                break
            except ValueError:
                continue
        _expiry_date_cache[exp_str] = parsed
        return parsed

    # Build in-memory structures
    for sym in symbols:
        # Extract underlying from OpenAlgo symbol format for FNO exchanges
        underlying = None
        if sym.exchange in FNO_EXCHANGES:
            underlying = extract_underlying_from_symbol(sym.symbol, sym.exchange)

        # Create lightweight data object
        symbol_data = SymbolData(
            symbol=sym.symbol,
            brsymbol=sym.brsymbol,
            name=sym.name,
            exchange=sym.exchange,
            brexchange=sym.brexchange,
            token=sym.token,
            expiry=sym.expiry,
            strike=sym.strike,
            lotsize=sym.lotsize,
            instrumenttype=sym.instrumenttype,
            tick_size=sym.tick_size,
            underlying=underlying,
            contract_value=getattr(sym, "contract_value", None),
        )

        # Store in primary dict
        primary[sym.token] = symbol_data

        # Build indexes
        by_symbol_exchange[(sym.symbol, sym.exchange)] = symbol_data
        by_token_exchange[(sym.token, sym.exchange)] = symbol_data
        by_brsymbol_exchange[(sym.brsymbol, sym.exchange)] = symbol_data
        by_token[sym.token] = symbol_data

        # Build FNO filter indexes for O(1) lookups
        by_exchange[sym.exchange].append(symbol_data)
        if sym.expiry:
            expiries_by_exchange[sym.exchange].add(sym.expiry)
            # Use extracted underlying for index (more reliable than broker's name field)
            if underlying:
                expiries_by_exchange_underlying[(sym.exchange, underlying)].add(sym.expiry)
        # Use extracted underlying for underlyings index.
        # `underlyings_by_exchange` is options-only — option-chain/IV-chart
        # dropdowns must not show futures-only commodities (dead-ends).
        # `tradable_underlyings_by_exchange` is the union (options OR live
        # futures) — used by the generic search/token UI where every
        # tradable contract should be discoverable.
        sym_upper = sym.symbol.upper()
        if underlying:
            if sym_upper.endswith("CE") or sym_upper.endswith("PE"):
                underlyings_by_exchange[sym.exchange].add(underlying)
                tradable_underlyings_by_exchange[sym.exchange].add(underlying)
            elif sym_upper.endswith("FUT"):
                exp_date = _exp_to_date(sym.expiry)
                if exp_date and exp_date >= ist_today:
                    tradable_underlyings_by_exchange[sym.exchange].add(underlying)

    session_start, next_reset = _session_timing()
    return _SymbolSnapshot(
        symbols=primary,
        by_symbol_exchange=by_symbol_exchange,
        by_token_exchange=by_token_exchange,
        by_brsymbol_exchange=by_brsymbol_exchange,
        by_token=by_token,
        by_exchange={k: tuple(v) for k, v in by_exchange.items()},
        expiries_by_exchange={k: frozenset(v) for k, v in expiries_by_exchange.items()},
        underlyings_by_exchange={k: frozenset(v) for k, v in underlyings_by_exchange.items()},
        tradable_underlyings_by_exchange={
            k: frozenset(v) for k, v in tradable_underlyings_by_exchange.items()
        },
        expiries_by_exchange_underlying={
            k: frozenset(v) for k, v in expiries_by_exchange_underlying.items()
        },
        cache_loaded=True,
        active_broker=broker,
        session_start=session_start,
        next_reset_time=next_reset,
    )


class BrokerSymbolCache:
    """
    High-performance in-memory cache for broker symbols
    Designed to handle 100,000+ symbols with minimal memory footprint

    The data lives in one immutable :class:`_SymbolSnapshot`, replaced whole by
    each load. **Bind it once per call** (``snap = self._snap``) and use only
    that object: reading ``self._snap`` twice in one call can mix two
    generations. The attributes below (``symbols``, ``by_exchange``,
    ``cache_loaded`` and the rest) read the current snapshot, for callers that
    only need one of them.
    """

    def __init__(self):
        self._snap = _SymbolSnapshot()
        # Serialises loads, which span database I/O: two loads that overlapped
        # (the boot restore and a login's download hook) used to interleave
        # their clears and fills into one set of dicts. A plain stdlib lock:
        # green under eventlet, where the load does green-safe database work,
        # and real under gthread. Readers never take it.
        self._load_lock = threading.Lock()

        # Cache statistics. The counters are approximate under concurrency,
        # which is all a hit-rate display needs.
        self.stats = CacheStats()

        logger.debug("BrokerSymbolCache initialized")

    # -- The current snapshot, attribute by attribute ------------------------

    @property
    def symbols(self) -> dict[str, SymbolData]:
        return self._snap.symbols

    @property
    def by_symbol_exchange(self) -> dict[tuple[str, str], SymbolData]:
        return self._snap.by_symbol_exchange

    @property
    def by_token_exchange(self) -> dict[tuple[str, str], SymbolData]:
        return self._snap.by_token_exchange

    @property
    def by_brsymbol_exchange(self) -> dict[tuple[str, str], SymbolData]:
        return self._snap.by_brsymbol_exchange

    @property
    def by_token(self) -> dict[str, SymbolData]:
        return self._snap.by_token

    @property
    def by_exchange(self) -> dict[str, tuple[SymbolData, ...]]:
        return self._snap.by_exchange

    @property
    def expiries_by_exchange(self) -> dict[str, frozenset[str]]:
        return self._snap.expiries_by_exchange

    @property
    def underlyings_by_exchange(self) -> dict[str, frozenset[str]]:
        return self._snap.underlyings_by_exchange

    @property
    def tradable_underlyings_by_exchange(self) -> dict[str, frozenset[str]]:
        return self._snap.tradable_underlyings_by_exchange

    @property
    def expiries_by_exchange_underlying(self) -> dict[tuple[str, str], frozenset[str]]:
        return self._snap.expiries_by_exchange_underlying

    @property
    def cache_loaded(self) -> bool:
        return self._snap.cache_loaded

    @property
    def active_broker(self) -> str | None:
        return self._snap.active_broker

    @property
    def session_start(self) -> datetime | None:
        return self._snap.session_start

    @property
    def next_reset_time(self) -> datetime | None:
        return self._snap.next_reset_time

    def valid_snapshot(self) -> _SymbolSnapshot | None:
        """The current snapshot if it is loaded and inside its session, else None."""
        snap = self._snap
        return snap if snap.is_valid() else None

    # -- Loading ---------------------------------------------------------------

    def load_all_symbols(self, broker: str) -> bool:
        """
        Load all symbols for the active broker into memory
        This is called once after master contract download

        The new generation is built aside and published in one assignment, so
        readers keep the previous one until it is complete. As before, a load
        that finds no symbols or fails leaves the cache empty, and callers
        fall back to the database.
        """
        with self._load_lock:
            # Read once: the failure paths below carry its session timing
            # forward, as the in-place clear used to.
            previous = self._snap
            try:
                from database.symbol import SymToken

                start_time = time.time()
                logger.debug(f"Loading all symbols for broker: {broker}")

                # Query all symbols from database
                symbols = SymToken.query.all()

                if not symbols:
                    self._snap = _unloaded(previous)
                    logger.warning(f"No symbols found in database for broker: {broker}")
                    return False

                snap = _build_snapshot(symbols, broker)
                self._snap = snap

                # Update cache metadata
                self.stats.total_symbols = len(symbols)
                self.stats.cache_loads += 1
                self.stats.last_loaded = datetime.now(pytz.timezone("Asia/Kolkata"))

                # Calculate memory usage (rough estimate)
                self.stats.memory_usage_mb = (
                    len(snap.symbols) * 500  # ~500 bytes per symbol
                ) / (1024 * 1024)

                load_time = time.time() - start_time
                logger.debug(
                    f"Successfully loaded {self.stats.total_symbols} symbols "
                    f"in {load_time:.2f} seconds. "
                    f"Memory usage: {self.stats.memory_usage_mb:.2f} MB"
                )
                return True

            except Exception as e:
                self._snap = _unloaded(previous)
                logger.exception(f"Error loading symbols into cache: {e}")
                return False

    def is_cache_valid(self) -> bool:
        """Check if cache is still valid (before session expiry reset)"""
        return self._snap.is_valid()

    # -- Lookups: each binds the snapshot once ---------------------------------

    def _lookup(self, index: dict, key) -> SymbolData | None:
        """One O(1) lookup in an index the caller took from one snapshot."""
        found = index.get(key)
        if found is None:
            self.stats.misses += 1
        else:
            self.stats.hits += 1
        return found

    def get_token(self, symbol: str, exchange: str) -> str | None:
        """Get token for symbol and exchange - O(1) lookup"""
        found = self._lookup(self._snap.by_symbol_exchange, (symbol, exchange))
        return found.token if found is not None else None

    def get_symbol(self, token: str, exchange: str) -> str | None:
        """Get symbol for token and exchange - O(1) lookup"""
        found = self._lookup(self._snap.by_token_exchange, (token, exchange))
        return found.symbol if found is not None else None

    def get_br_symbol(self, symbol: str, exchange: str) -> str | None:
        """Get broker symbol for symbol and exchange - O(1) lookup"""
        found = self._lookup(self._snap.by_symbol_exchange, (symbol, exchange))
        return found.brsymbol if found is not None else None

    def get_oa_symbol(self, brsymbol: str, exchange: str) -> str | None:
        """Get OpenAlgo symbol for broker symbol and exchange - O(1) lookup"""
        found = self._lookup(self._snap.by_brsymbol_exchange, (brsymbol, exchange))
        return found.symbol if found is not None else None

    def get_brexchange(self, symbol: str, exchange: str) -> str | None:
        """Get broker exchange for symbol and exchange - O(1) lookup"""
        found = self._lookup(self._snap.by_symbol_exchange, (symbol, exchange))
        return found.brexchange if found is not None else None

    def get_symbol_info(self, symbol: str, exchange: str) -> SymbolData | None:
        """Get full symbol data for symbol and exchange - O(1) lookup"""
        return self._lookup(self._snap.by_symbol_exchange, (symbol, exchange))

    def get_symbol_data(self, token: str) -> SymbolData | None:
        """Get complete symbol data by token - O(1) lookup"""
        return self._lookup(self._snap.by_token, token)

    def get_tokens_bulk(
        self, symbol_exchange_pairs: list[tuple[str, str]], snap: _SymbolSnapshot | None = None
    ) -> list[str | None]:
        """
        Bulk retrieve tokens for multiple symbol-exchange pairs
        Optimized for performance with single pass
        """
        index = (snap or self._snap).by_symbol_exchange
        self.stats.bulk_queries += 1
        results = []

        for symbol, exchange in symbol_exchange_pairs:
            found = index.get((symbol, exchange))
            if found is not None:
                results.append(found.token)
                self.stats.hits += 1
            else:
                results.append(None)
                self.stats.misses += 1

        return results

    def get_symbols_bulk(
        self, token_exchange_pairs: list[tuple[str, str]], snap: _SymbolSnapshot | None = None
    ) -> list[str | None]:
        """
        Bulk retrieve symbols for multiple token-exchange pairs
        """
        index = (snap or self._snap).by_token_exchange
        self.stats.bulk_queries += 1
        results = []

        for token, exchange in token_exchange_pairs:
            found = index.get((token, exchange))
            if found is not None:
                results.append(found.symbol)
                self.stats.hits += 1
            else:
                results.append(None)
                self.stats.misses += 1

        return results

    def search_symbols(
        self,
        query: str,
        exchange: str | None = None,
        limit: int = 10000,
        snap: _SymbolSnapshot | None = None,
    ) -> list[SymbolData]:
        """
        Search symbols by partial match with multi-term support.
        All terms must match (AND logic).
        Returns list of matching SymbolData objects, most relevant first.
        Optimized to use exchange index when available.

        Ranked, not first-found: a query like "NIFTY" AND-matches every NIFTY
        option contract on NFO (thousands of them) as well as every NIFTY
        index (a few hundred). Stopping at the first ``limit`` hits in
        dict-iteration order let the option chain -- which has no natural
        relevance to a symbol search -- crowd out the index and equity
        matches a caller actually wants, with no way to reach the rest by
        typing a more specific query. Scoring on the query itself and taking
        the closest matches instead fixes that for every segment, not just
        indices, without hardcoding any exchange.
        """
        snap = snap or self._snap
        # Split query into terms
        query_upper = query.strip().upper()
        terms = [term.strip().upper() for term in query.split() if term.strip()]
        if not terms:
            return []

        # Parse numeric terms for strike matching
        num_terms = []
        for term in terms:
            try:
                num_terms.append(float(term))
            except ValueError:
                pass

        # Use exchange index if available - significantly faster
        exchange_rows = snap.by_exchange.get(exchange) if exchange else None
        if exchange_rows is not None:
            symbols_to_search = exchange_rows
        else:
            symbols_to_search = snap.symbols.values()

        # (score, length, symbol, tie-break sequence, row) — 0 = exact symbol
        # match, 1 = symbol starts with the query, 2 = query is a substring of
        # the symbol, 3 = matched only via brsymbol/name/token/strike. Shorter
        # symbols before longer ones at the same score, so "NIFTY" and
        # "NIFTY50" sort ahead of a 20-character option contract that merely
        # happens to start with the same letters.
        scored: list[tuple[int, int, str, int, SymbolData]] = []
        seq = 0
        for symbol_data in symbols_to_search:
            symbol_upper = symbol_data.symbol.upper()

            all_match = True
            symbol_term_match = True
            for term in terms:
                term_in_symbol = term in symbol_upper
                term_match = (
                    term_in_symbol
                    or term in symbol_data.brsymbol.upper()
                    or (symbol_data.name and term in symbol_data.name.upper())
                    or (symbol_data.token and term in symbol_data.token)
                )
                # Also check numeric terms against strike
                if not term_match and num_terms and symbol_data.strike:
                    try:
                        if float(term) == symbol_data.strike:
                            term_match = True
                    except ValueError:
                        pass

                if not term_match:
                    all_match = False
                    break
                symbol_term_match = symbol_term_match and term_in_symbol

            if not all_match:
                continue

            if symbol_upper == query_upper:
                score = 0
            elif symbol_upper.startswith(query_upper):
                score = 1
            elif symbol_term_match:
                score = 2
            else:
                score = 3

            seq += 1
            scored.append((score, len(symbol_upper), symbol_upper, seq, symbol_data))

        top = heapq.nsmallest(limit, scored, key=lambda row: row[:4])
        return [row[4] for row in top]

    def fno_search_symbols(
        self,
        query: str | None = None,
        exchange: str | None = None,
        expiry: str | None = None,
        instrumenttype: str | None = None,
        strike_min: float | None = None,
        strike_max: float | None = None,
        underlying: str | None = None,
        limit: int = 10000,
        snap: _SymbolSnapshot | None = None,
    ) -> list[SymbolData]:
        """
        FNO-specific search with advanced filters - in-memory cache search
        Optimized to use exchange index for O(n/exchanges) instead of O(n) iteration

        Args:
            query: Optional search query string
            exchange: Exchange filter (NFO, BFO, MCX, CDS)
            expiry: Expiry date filter (e.g., "26-DEC-24")
            instrumenttype: "FUT", "CE", or "PE" (based on symbol suffix)
            strike_min: Minimum strike price
            strike_max: Maximum strike price
            underlying: Underlying symbol name (e.g., "NIFTY")
            limit: Maximum results to return
            snap: The snapshot to search; the current one when omitted.

        Returns:
            List of matching SymbolData objects
        """
        snap = snap or self._snap
        matches = []
        query_upper = query.upper() if query else None
        underlying_upper = underlying.strip().upper() if underlying else None
        expiry_stripped = expiry.strip() if expiry else None
        inst_type = instrumenttype.strip().upper() if instrumenttype else None

        # Parse numeric terms from query for strike matching
        query_terms = []
        query_nums = []
        if query_upper:
            for term in query_upper.split():
                term = term.strip()
                if term:
                    query_terms.append(term)
                    try:
                        query_nums.append(float(term))
                    except ValueError:
                        pass

        # Use exchange index if available - significantly faster for FNO searches
        exchange_rows = snap.by_exchange.get(exchange) if exchange else None
        if exchange_rows is not None:
            symbols_to_search = exchange_rows
        else:
            # Fallback to all symbols if no exchange filter
            symbols_to_search = snap.symbols.values()

        for symbol_data in symbols_to_search:
            # Underlying filter (use extracted underlying from OpenAlgo symbol format)
            if underlying_upper and (
                not symbol_data.underlying or symbol_data.underlying != underlying_upper
            ):
                continue

            # Expiry filter
            if expiry_stripped and symbol_data.expiry != expiry_stripped:
                continue

            # Instrument type filter.
            # All exchanges (including CRYPTO) use canonical suffix conventions:
            #   CE      → symbol ends with "CE"  (e.g. BTC28FEB2580000CE)
            #   PE      → symbol ends with "PE"  (e.g. BTC28FEB2580000PE)
            #   FUT     → symbol ends with "FUT" (e.g. BTC28FEB25FUT)
            #   PERPFUT → stored instrumenttype field (e.g. BTCUSD.P)
            if inst_type:
                symbol_upper = symbol_data.symbol.upper()
                if inst_type == "FUT" and not symbol_upper.endswith("FUT"):
                    continue
                elif inst_type == "CE" and not symbol_upper.endswith("CE"):
                    continue
                elif inst_type == "PE" and not symbol_upper.endswith("PE"):
                    continue
                elif inst_type == "PERPFUT" and (
                    not symbol_data.instrumenttype
                    or symbol_data.instrumenttype.upper() != "PERPFUT"
                ):
                    continue

            # Strike range filter
            if strike_min is not None and (
                symbol_data.strike is None or symbol_data.strike < strike_min
            ):
                continue
            if strike_max is not None and (
                symbol_data.strike is None or symbol_data.strike > strike_max
            ):
                continue

            # Query text search (if provided)
            if query_terms:
                # All terms must match
                all_match = True
                for term in query_terms:
                    term_match = (
                        term in symbol_data.symbol.upper()
                        or term in symbol_data.brsymbol.upper()
                        or (symbol_data.name and term in symbol_data.name.upper())
                        or (symbol_data.token and term in symbol_data.token)
                    )
                    if not term_match:
                        all_match = False
                        break

                # Also check numeric terms against strike
                if not all_match and query_nums and symbol_data.strike:
                    for num in query_nums:
                        if symbol_data.strike == num:
                            all_match = True
                            break

                if not all_match:
                    continue

            matches.append(symbol_data)

        # Smart sorting: prioritize exact underlying matches, then alphabetical
        # Extract the primary search term (first term) for relevance scoring
        primary_term = query_terms[0] if query_terms else None

        def sort_key(s):
            """Sort FNO results by relevance: exact underlying, prefix match, then alphabetical."""
            # Priority 1: Exact match on underlying (e.g., "NIFTY" matches underlying="NIFTY" exactly)
            underlying_exact = (
                0 if (primary_term and s.underlying and s.underlying == primary_term) else 1
            )

            # Priority 2: Underlying starts with search term (e.g., "NIFTY" before "BANKNIFTY")
            underlying_starts = (
                0 if (primary_term and s.underlying and s.underlying.startswith(primary_term)) else 1
            )

            # Priority 3: Symbol starts with search term
            symbol_starts = 0 if (primary_term and s.symbol.upper().startswith(primary_term)) else 1

            # Priority 4: Alphabetical by symbol
            return (underlying_exact, underlying_starts, symbol_starts, s.symbol)

        matches.sort(key=sort_key)
        return matches[:limit]

    def clear_cache(self):
        """Clear all cached data"""
        # One assignment: a reader holding the previous snapshot finishes with
        # it, and the next reader sees an empty, unloaded cache.
        self._snap = _unloaded(self._snap)
        logger.debug("Cache cleared")

    def get_cache_info(self) -> dict:
        """Get cache information for monitoring"""
        snap = self._snap
        return {
            "active_broker": snap.active_broker,
            "cache_loaded": snap.cache_loaded,
            "total_symbols": self.stats.total_symbols,
            "cache_valid": snap.is_valid(),
            "session_start": snap.session_start.isoformat() if snap.session_start else None,
            "next_reset": snap.next_reset_time.isoformat() if snap.next_reset_time else None,
            "stats": self.stats.to_dict(),
        }


# Global cache instance (singleton pattern). Built at import rather than on
# first use: two cold callers used to be able to build one each, and a load
# could then fill an instance that readers never saw.
_cache_instance: BrokerSymbolCache = BrokerSymbolCache()


def get_cache() -> BrokerSymbolCache:
    """Get the global cache instance"""
    return _cache_instance


# Public API - Drop-in replacement for existing token_db functions
#
# Each function binds one valid snapshot (or None) and uses only that, so a
# reload landing mid-call cannot mix two generations.
def get_token(symbol: str, exchange: str) -> str | None:
    """
    Get token for a given symbol and exchange
    First checks cache, falls back to database if needed
    """
    cache = get_cache()
    snap = cache.valid_snapshot()

    # Check if cache is loaded and valid
    if snap is not None:
        found = cache._lookup(snap.by_symbol_exchange, (symbol, exchange))
        if found is not None:
            return found.token

    # Fallback to database query
    cache.stats.db_queries += 1
    return get_token_dbquery(symbol, exchange)


def get_symbol(token: str, exchange: str) -> str | None:
    """
    Get symbol for a given token and exchange
    """
    cache = get_cache()
    snap = cache.valid_snapshot()

    if snap is not None:
        found = cache._lookup(snap.by_token_exchange, (token, exchange))
        if found is not None:
            return found.symbol

    cache.stats.db_queries += 1
    return get_symbol_dbquery(token, exchange)


def get_br_symbol(symbol: str, exchange: str) -> str | None:
    """
    Get broker symbol for a given symbol and exchange
    """
    cache = get_cache()
    snap = cache.valid_snapshot()

    if snap is not None:
        found = cache._lookup(snap.by_symbol_exchange, (symbol, exchange))
        if found is not None:
            return found.brsymbol

    cache.stats.db_queries += 1
    return get_br_symbol_dbquery(symbol, exchange)


def get_oa_symbol(brsymbol: str, exchange: str) -> str | None:
    """
    Get OpenAlgo symbol for a given broker symbol and exchange
    """
    cache = get_cache()
    snap = cache.valid_snapshot()

    if snap is not None:
        found = cache._lookup(snap.by_brsymbol_exchange, (brsymbol, exchange))
        if found is not None:
            return found.symbol

    cache.stats.db_queries += 1
    return get_oa_symbol_dbquery(brsymbol, exchange)


def get_brexchange(symbol: str, exchange: str) -> str | None:
    """
    Get broker exchange for a given symbol and exchange
    """
    cache = get_cache()
    snap = cache.valid_snapshot()

    if snap is not None:
        found = cache._lookup(snap.by_symbol_exchange, (symbol, exchange))
        if found is not None:
            return found.brexchange

    cache.stats.db_queries += 1
    return get_brexchange_dbquery(symbol, exchange)


def get_symbol_info(symbol: str, exchange: str) -> SymbolData | None:
    """
    Get full symbol information (SymbolData object) for a given symbol and exchange
    Returns SymbolData with all fields: token, lotsize, strike, expiry, etc.
    First checks cache, falls back to database if needed
    """
    cache = get_cache()
    snap = cache.valid_snapshot()

    if snap is not None:
        found = cache._lookup(snap.by_symbol_exchange, (symbol, exchange))
        if found is not None:
            return found

    cache.stats.db_queries += 1
    return get_symbol_info_dbquery(symbol, exchange)


# Database fallback functions (imported from original token_db)
def get_token_dbquery(symbol: str, exchange: str) -> str | None:
    """Query database for token by symbol and exchange"""
    try:
        from database.symbol import SymToken

        sym_token = SymToken.query.filter_by(symbol=symbol, exchange=exchange).first()
        if sym_token:
            return sym_token.token
        else:
            return None
    except Exception as e:
        logger.exception(f"Error while querying the database: {e}")
        return None


def get_symbol_dbquery(token: str, exchange: str) -> str | None:
    """Query database for symbol by token and exchange"""
    try:
        from database.symbol import SymToken

        sym_token = SymToken.query.filter_by(token=token, exchange=exchange).first()
        if sym_token:
            return sym_token.symbol
        else:
            return None
    except Exception as e:
        logger.exception(f"Error while querying the database: {e}")
        return None


def get_br_symbol_dbquery(symbol: str, exchange: str) -> str | None:
    """Query database for broker symbol"""
    try:
        from database.symbol import SymToken

        sym_token = SymToken.query.filter_by(symbol=symbol, exchange=exchange).first()
        if sym_token:
            return sym_token.brsymbol
        else:
            return None
    except Exception as e:
        logger.exception(f"Error while querying the database: {e}")
        return None


def get_oa_symbol_dbquery(brsymbol: str, exchange: str) -> str | None:
    """Query database for OpenAlgo symbol"""
    try:
        from database.symbol import SymToken

        sym_token = SymToken.query.filter_by(brsymbol=brsymbol, exchange=exchange).first()
        if sym_token:
            return sym_token.symbol
        else:
            return None
    except Exception as e:
        logger.exception(f"Error while querying the database: {e}")
        return None


def get_brexchange_dbquery(symbol: str, exchange: str) -> str | None:
    """Query database for broker exchange"""
    try:
        from database.symbol import SymToken

        sym_token = SymToken.query.filter_by(symbol=symbol, exchange=exchange).first()
        if sym_token:
            return sym_token.brexchange
        else:
            return None
    except Exception as e:
        logger.exception(f"Error while querying the database: {e}")
        return None


def get_symbol_info_dbquery(symbol: str, exchange: str) -> SymbolData | None:
    """Query database for full symbol information, returns SymbolData object"""
    try:
        from database.symbol import SymToken

        sym_token = SymToken.query.filter_by(symbol=symbol, exchange=exchange).first()
        if sym_token:
            # Convert SymToken database object to SymbolData
            return SymbolData(
                symbol=sym_token.symbol,
                brsymbol=sym_token.brsymbol,
                name=sym_token.name,
                exchange=sym_token.exchange,
                brexchange=sym_token.brexchange,
                token=sym_token.token,
                expiry=sym_token.expiry,
                strike=sym_token.strike,
                lotsize=sym_token.lotsize,
                instrumenttype=sym_token.instrumenttype,
                tick_size=sym_token.tick_size,
            )
        else:
            return None
    except Exception as e:
        logger.exception(f"Error while querying the database: {e}")
        return None


def get_symbol_count() -> int:
    """Get the total count of symbols in the database"""
    try:
        from database.symbol import SymToken

        count = SymToken.query.count()
        return count
    except Exception as e:
        logger.exception(f"Error while counting symbols: {e}")
        return 0


# Cache management functions
def load_cache_for_broker(broker: str) -> bool:
    """
    Load cache for a specific broker
    Called after master contract download completes
    """
    cache = get_cache()
    return cache.load_all_symbols(broker)


def clear_cache():
    """Clear the cache - useful for manual refresh"""
    cache = get_cache()
    cache.clear_cache()


def get_cache_stats() -> dict:
    """Get cache statistics for monitoring"""
    cache = get_cache()
    return cache.get_cache_info()


# Bulk operations for performance
def get_tokens_bulk(symbol_exchange_pairs: list[tuple[str, str]]) -> list[str | None]:
    """Bulk retrieve tokens - optimized for performance"""
    cache = get_cache()
    snap = cache.valid_snapshot()

    if snap is not None:
        return cache.get_tokens_bulk(symbol_exchange_pairs, snap=snap)

    # Fallback to individual queries
    results = []
    for symbol, exchange in symbol_exchange_pairs:
        cache.stats.db_queries += 1
        results.append(get_token_dbquery(symbol, exchange))
    return results


def get_symbols_bulk(token_exchange_pairs: list[tuple[str, str]]) -> list[str | None]:
    """Bulk retrieve symbols - optimized for performance"""
    cache = get_cache()
    snap = cache.valid_snapshot()

    if snap is not None:
        return cache.get_symbols_bulk(token_exchange_pairs, snap=snap)

    # Fallback to individual queries
    results = []
    for token, exchange in token_exchange_pairs:
        cache.stats.db_queries += 1
        results.append(get_symbol_dbquery(token, exchange))
    return results


# Search functionality
def search_symbols(query: str, exchange: str | None = None, limit: int = 10000) -> list[dict]:
    """
    Search symbols with cache support
    Returns list of symbol dictionaries
    """
    cache = get_cache()
    snap = cache.valid_snapshot()

    if snap is not None:
        results = cache.search_symbols(query, exchange, limit, snap=snap)
        return [
            {
                "symbol": s.symbol,
                "brsymbol": s.brsymbol,
                "name": s.name,
                "exchange": s.exchange,
                "token": s.token,
                "instrumenttype": s.instrumenttype,
            }
            for s in results
        ]

    # Fallback to database search
    try:
        from database.symbol import SymToken

        query_obj = SymToken.query.filter(SymToken.symbol.like(f"%{query}%"))
        if exchange:
            query_obj = query_obj.filter_by(exchange=exchange)

        results = query_obj.limit(limit).all()
        return [
            {
                "symbol": r.symbol,
                "brsymbol": r.brsymbol,
                "name": r.name,
                "exchange": r.exchange,
                "token": r.token,
                "instrumenttype": r.instrumenttype,
            }
            for r in results
        ]
    except Exception as e:
        logger.exception(f"Error searching symbols: {e}")
        return []


def fno_search_symbols(
    query: str | None = None,
    exchange: str | None = None,
    expiry: str | None = None,
    instrumenttype: str | None = None,
    strike_min: float | None = None,
    strike_max: float | None = None,
    underlying: str | None = None,
    limit: int = 10000,
) -> list[dict]:
    """
    FNO-specific search with advanced filters - uses cache for fast in-memory search
    Falls back to database if cache is not available

    Args:
        query: Optional search query string
        exchange: Exchange filter (NFO, BFO, MCX, CDS)
        expiry: Expiry date filter (e.g., "26-DEC-24")
        instrumenttype: "FUT", "CE", or "PE" (based on symbol suffix)
        strike_min: Minimum strike price
        strike_max: Maximum strike price
        underlying: Underlying symbol name (e.g., "NIFTY")
        limit: Maximum results to return

    Returns:
        List of symbol dictionaries with all fields
    """
    cache = get_cache()
    snap = cache.valid_snapshot()

    # Import freeze qty function
    from database.qty_freeze_db import get_freeze_qty_for_option

    if snap is not None:
        results = cache.fno_search_symbols(
            query=query,
            exchange=exchange,
            expiry=expiry,
            instrumenttype=instrumenttype,
            strike_min=strike_min,
            strike_max=strike_max,
            underlying=underlying,
            limit=limit,
            snap=snap,
        )
        return [
            {
                "symbol": s.symbol,
                "brsymbol": s.brsymbol,
                "name": s.name,
                "exchange": s.exchange,
                "brexchange": s.brexchange,
                "token": s.token,
                "expiry": s.expiry,
                "strike": s.strike,
                "lotsize": s.lotsize,
                "instrumenttype": s.instrumenttype,
                "tick_size": s.tick_size,
                "underlying": s.underlying,
                "contract_value": s.contract_value,
                "freeze_qty": get_freeze_qty_for_option(s.symbol, s.exchange),
            }
            for s in results
        ]

    # Fallback to database search (import the DB-based function)
    logger.debug("Cache not available, falling back to database FNO search")
    cache.stats.db_queries += 1

    try:
        from database.symbol import fno_search_symbols_db

        return fno_search_symbols_db(
            query=query,
            exchange=exchange,
            expiry=expiry,
            instrumenttype=instrumenttype,
            strike_min=strike_min,
            strike_max=strike_max,
            underlying=underlying,
            limit=limit,
        )
    except Exception as e:
        logger.exception(f"Error in FNO search fallback: {e}")
        return []


def get_distinct_expiries_cached(
    exchange: str | None = None,
    underlying: str | None = None,
    instrumenttype: str | None = None,
) -> list[str]:
    """
    Get distinct expiry dates from cache - fast O(1) lookup using pre-computed indexes
    Falls back to database if cache is not available

    The pre-computed indexes do not distinguish futures from options, so a
    request that asks for one goes to the database. That matters on MCX, where
    the two calendars differ and a mixed list hands an option chain an expiry
    with no strikes behind it.
    """
    cache = get_cache()

    if instrumenttype:
        from database.symbol import get_distinct_expiries

        return get_distinct_expiries(
            exchange=exchange, underlying=underlying, instrumenttype=instrumenttype
        )

    snap = cache.valid_snapshot()
    if snap is not None:
        from datetime import datetime

        # Use pre-computed indexes for O(1) lookup instead of iterating all symbols
        underlying_upper = underlying.strip().upper() if underlying else None

        if exchange and underlying_upper:
            # Use the combined index for exchange + underlying
            expiries = snap.expiries_by_exchange_underlying.get(
                (exchange, underlying_upper), frozenset()
            )
        elif exchange:
            # Use the exchange-only index
            expiries = snap.expiries_by_exchange.get(exchange, frozenset())
        else:
            # No filter - combine all expiries (rare case)
            expiries = set()
            for exp_set in snap.expiries_by_exchange.values():
                expiries.update(exp_set)

        # Sort expiries chronologically and drop already-expired dates so
        # dropdowns only surface live expiries. Master-contract caches can
        # carry recently expired rows for several days; without this filter
        # the chain defaults to a dead expiry where brokers return empty
        # depth / volume = 0.
        def parse_expiry(exp_str):
            """Parse an expiry date string into a datetime for chronological sorting."""
            try:
                return datetime.strptime(exp_str, "%d-%b-%y")
            except ValueError:
                try:
                    return datetime.strptime(exp_str, "%d-%b-%Y")
                except ValueError:
                    return datetime.max

        today = datetime.now().date()
        live_expiries = [e for e in expiries if parse_expiry(e).date() >= today]
        return sorted(live_expiries, key=parse_expiry)

    # Fallback to database
    try:
        from database.symbol import get_distinct_expiries

        return get_distinct_expiries(exchange=exchange, underlying=underlying)
    except Exception as e:
        logger.exception(f"Error getting expiries: {e}")
        return []


def get_distinct_underlyings_cached(
    exchange: str | None = None, include_futures: bool = False
) -> list[str]:
    """
    Get distinct underlying names from cache - fast O(1) lookup using pre-computed indexes
    Falls back to database if cache is not available.

    Args:
        exchange: Exchange filter (NFO, BFO, MCX, ...).
        include_futures: When True, return the tradable index (options ∪ live
            futures). When False (default), return options-only — required for
            option-chain / IV-chart dropdowns where futures-only underlyings
            are dead ends.
    """
    cache = get_cache()
    snap = cache.valid_snapshot()

    if snap is not None:
        index = (
            snap.tradable_underlyings_by_exchange
            if include_futures
            else snap.underlyings_by_exchange
        )
        # Use pre-computed index for O(1) lookup instead of iterating all symbols
        if exchange:
            underlyings = index.get(exchange, frozenset())
        else:
            # No filter - combine all underlyings (rare case)
            underlyings = set()
            for underlying_set in index.values():
                underlyings.update(underlying_set)

        return sorted(list(underlyings))

    # Fallback to database. The DB query returns all distinct names for the
    # exchange — that already matches `include_futures=True` semantics. For
    # `include_futures=False` it's slightly broader than ideal, but this path
    # only fires while the cache is loading, so it's an acceptable degraded
    # window (a few seconds at startup).
    try:
        from database.symbol import get_distinct_underlyings

        return get_distinct_underlyings(exchange=exchange)
    except Exception as e:
        logger.exception(f"Error getting underlyings: {e}")
        return []
