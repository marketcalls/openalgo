"""Symbol-cache accessors must bind ONE snapshot generation (GT-A2-01).

PR-4 made snapshot *publication* atomic: a reload builds a whole new
``_SymbolSnapshot`` and rebinds ``BrokerSymbolCache._snap`` once. That is
necessary but not sufficient, and an external audit was right to catch it.

Every accessor reached the snapshot through a property, and each property read
``self._snap`` again. So::

    if key in self.by_symbol_exchange:            # generation A
        return self.by_symbol_exchange[key].token # generation B -> KeyError

The guard proved membership in a generation that was no longer the one being
indexed. The class docstring claimed readers "never see a mix"; they could.

Under eventlet this was unreachable -- nothing between the two reads yields.
Under real threads it is a live crash on the order path during the daily
symbol refresh, and it is reachable today on Windows and macOS, whose dev
server has always used real threads.

These tests drive the REAL accessors while the generation changes underneath
them, rather than asserting that a whole-snapshot assignment is atomic (which
was never the part in doubt).
"""

import threading

import pytest

from database.token_db_enhanced import BrokerSymbolCache, SymbolData, _SymbolSnapshot


def _row(symbol="INFY", exchange="NSE", token="1594"):
    return SymbolData(
        symbol=symbol, brsymbol=symbol, name=symbol, exchange=exchange,
        brexchange=exchange, token=token, expiry="", strike=0.0,
        lotsize=1, instrumenttype="EQ", tick_size=0.05,
    )


class _FlipSnapshot:
    """Yields the populated generation on the first read of a field and the
    replacement generation on every read after it.

    This is what a real swap looks like from inside a single accessor: the
    membership test lands on the old generation, the lookup on the new one.
    """

    def __init__(self, first, later):
        self._first, self._later = first, later
        self.reads = 0

    def _pick(self, field):
        self.reads += 1
        src = self._first if self.reads == 1 else self._later
        return getattr(src, field)

    def __getattr__(self, name):
        if name in _SymbolSnapshot.__slots__:
            return self._pick(name)
        raise AttributeError(name)


def _populated(**kw):
    snap = _SymbolSnapshot()
    row = _row(**kw)
    snap.symbols[row.symbol] = row
    snap.by_symbol_exchange[(row.symbol, row.exchange)] = row
    snap.by_token_exchange[(row.token, row.exchange)] = row
    snap.by_brsymbol_exchange[(row.brsymbol, row.exchange)] = row
    snap.by_token[row.token] = row
    snap.by_exchange[row.exchange].append(row)
    return snap


# (method name, args) for every accessor that reads a snapshot field.
ACCESSORS = [
    ("get_token", ("INFY", "NSE")),
    ("get_symbol", ("1594", "NSE")),
    ("get_br_symbol", ("INFY", "NSE")),
    ("get_oa_symbol", ("INFY", "NSE")),
    ("get_brexchange", ("INFY", "NSE")),
    ("get_symbol_info", ("INFY", "NSE")),
    ("get_symbol_data", ("1594",)),
]


@pytest.mark.parametrize("method,args", ACCESSORS)
def test_accessor_does_not_mix_generations(method, args):
    """The old generation has the row; the new one does not -- exactly what an
    expired contract disappearing across a refresh looks like."""
    cache = BrokerSymbolCache()
    cache._snap = _FlipSnapshot(_populated(), _SymbolSnapshot())

    # Must return the old generation's answer or None. It must not raise.
    result = getattr(cache, method)(*args)
    assert result is not None or result is None  # the point is that it returned


@pytest.mark.parametrize("method,args", [
    ("get_tokens_bulk", ([("INFY", "NSE")],)),
    ("get_symbols_bulk", ([("1594", "NSE")],)),
])
def test_bulk_accessor_does_not_mix_generations(method, args):
    cache = BrokerSymbolCache()
    cache._snap = _FlipSnapshot(_populated(), _SymbolSnapshot())
    assert isinstance(getattr(cache, method)(*args), list)


@pytest.mark.parametrize("method", ["search_symbols", "fno_search_symbols"])
def test_search_binds_one_generation(method):
    """Search reads two different fields; both must come from one generation,
    or it can iterate an exchange index whose rows are absent from .symbols."""
    cache = BrokerSymbolCache()
    cache._snap = _FlipSnapshot(_populated(), _SymbolSnapshot())
    assert isinstance(getattr(cache, method)("INFY", "NSE"), list)


def test_accessors_read_the_snapshot_exactly_once():
    """Stronger than 'does not raise': binding must actually happen, otherwise
    a future edit could reintroduce the second read without failing above."""
    for method, args in ACCESSORS:
        cache = BrokerSymbolCache()
        flip = _FlipSnapshot(_populated(), _SymbolSnapshot())
        cache._snap = flip
        getattr(cache, method)(*args)
        assert flip.reads == 1, (
            f"{method} read the snapshot {flip.reads} times; it must bind one "
            "generation and reuse it"
        )


def test_no_method_reads_a_snapshot_field_twice():
    """Structural gate covering methods that do not exist yet.

    The behavioural tests above only cover today's accessors. This one reads
    the class itself, so a new method written next month with the same
    membership-then-index shape fails here rather than in production during a
    symbol refresh.
    """
    import ast
    import inspect

    import database.token_db_enhanced as mod

    tree = ast.parse(inspect.getsource(mod))
    cls = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef) and n.name == "BrokerSymbolCache"
    )
    fields = set(_SymbolSnapshot.__slots__)

    offenders = []
    for fn in cls.body:
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # The properties themselves are the single-read accessors.
        if any(isinstance(d, ast.Name) and d.id == "property" for d in fn.decorator_list):
            continue
        # Both routes to a snapshot field count, because both re-read _snap:
        #
        #   self.by_symbol_exchange          -> property -> self._snap.<field>
        #   self._snap.by_symbol_exchange    -> direct
        #
        # Counting only the first would have been a blind spot precisely where
        # the fix lives: the corrected accessors use the *second* form, so this
        # check could not see the pattern it exists to protect. A local
        # `snap = self._snap` followed by `snap.<field>` is the safe shape and
        # is deliberately not counted -- the generation is already bound.
        def _is_snapshot_read(node):
            if not (isinstance(node, ast.Attribute) and node.attr in fields):
                return False
            base = node.value
            if isinstance(base, ast.Name) and base.id == "self":
                return True  # via property
            return (
                isinstance(base, ast.Attribute)
                and base.attr == "_snap"
                and isinstance(base.value, ast.Name)
                and base.value.id == "self"
            )  # direct

        reads = [node.attr for node in ast.walk(fn) if _is_snapshot_read(node)]
        if len(reads) >= 2:
            offenders.append(f"{fn.name} reads {sorted(set(reads))} {len(reads)} times")

    assert offenders == [], (
        "these methods reach the snapshot through `self.<field>` more than once, "
        "so they can straddle a swap; bind `snap = self._snap` and reuse it: "
        f"{offenders}"
    )


def test_concurrent_swap_during_lookups_never_raises():
    """The end-to-end property, under real threads rather than a stub."""
    cache = BrokerSymbolCache()
    cache._snap = _populated()

    stop = threading.Event()
    errors = []

    def swapper():
        full, empty = _populated(), _SymbolSnapshot()
        while not stop.is_set():
            cache._snap = empty
            cache._snap = full

    def reader():
        while not stop.is_set():
            try:
                cache.get_token("INFY", "NSE")
                cache.get_symbol_data("1594")
                cache.search_symbols("INFY", "NSE")
            except Exception as exc:  # noqa: BLE001 - recording is the point
                errors.append(f"{type(exc).__name__}: {exc}")
                return

    threads = [threading.Thread(target=swapper)] + [
        threading.Thread(target=reader) for _ in range(4)
    ]
    for t in threads:
        t.start()
    stop.wait(2.0)
    stop.set()
    for t in threads:
        t.join(timeout=5)

    assert errors == [], f"lookups raised during a swap: {errors[:3]}"
