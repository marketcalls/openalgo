"""An unconfigured freeze quantity is 0, never 1.

The qty_freeze table ships seeded from NSE's file, so it holds NFO rows only.
Every other underlying resolved to 1, which is indistinguishable from a real
freeze limit of one unit -- and callers that reject `quantity > freeze` then
refused every order on BFO, CDS and MCX, plus any NFO underlying without a row.

One lot of SENSEX is 20 and one lot of CRUDEOIL is 100, both above 1, so the
smallest possible order was rejected. It survived because NFO index options,
the common case, do have rows: NIFTY resolves to 1800 and works, which is why
the terminal looked healthy while three exchanges were unusable.

0 is what every caller already tests for -- blueprints/scalping.py guards
`if freeze and freeze > 0` before enforcing, and its exit path does `or 0`
before computing a chunk size.
"""

import pytest

import database.qty_freeze_db as qf


@pytest.fixture(autouse=True)
def _seeded_cache(monkeypatch):
    """A cache holding only NFO rows, as a real install has."""
    monkeypatch.setattr(qf, "_cache_loaded", True)
    monkeypatch.setattr(
        qf,
        "_freeze_qty_cache",
        {"NFO:NIFTY": 1800, "NFO:BANKNIFTY": 900, "NFO:RELIANCE": 25000},
    )


class TestUnknownIsZero:
    @pytest.mark.parametrize(
        "symbol,exchange",
        [
            ("CRUDEOIL", "MCX"),
            ("NATURALGAS", "MCX"),
            ("SENSEX", "BFO"),
            ("BANKEX", "BFO"),
            ("USDINR", "CDS"),
            ("SOMETHINGNEW", "NFO"),
        ],
    )
    def test_an_unconfigured_underlying_returns_zero(self, symbol, exchange):
        assert qf.get_freeze_qty(symbol, exchange) == 0

    def test_a_configured_underlying_is_unchanged(self):
        assert qf.get_freeze_qty("NIFTY", "NFO") == 1800
        assert qf.get_freeze_qty("BANKNIFTY", "NFO") == 900

    def test_the_same_symbol_on_another_exchange_is_not_borrowed(self):
        """The cache is keyed exchange-first for a reason."""
        assert qf.get_freeze_qty("NIFTY", "BFO") == 0


class TestOptionAndFuturesSymbols:
    @pytest.mark.parametrize(
        "symbol,exchange,expected",
        [
            ("NIFTY30SEP2624000CE", "NFO", 1800),
            ("NIFTY30SEP26FUT", "NFO", 1800),
            ("BANKNIFTY30SEP2652000PE", "NFO", 900),
            ("CRUDEOIL15OCT268850CE", "MCX", 0),
            ("NATURALGAS25SEP26FUT", "MCX", 0),
            ("SENSEX24SEP2680000CE", "BFO", 0),
            ("BANKEX24SEP26FUT", "BFO", 0),
        ],
    )
    def test_resolution_from_a_full_contract_symbol(self, symbol, exchange, expected):
        assert qf.get_freeze_qty_for_option(symbol, exchange) == expected

    def test_a_symbol_that_does_not_parse_is_zero_not_one(self):
        """360ONE starts with a digit, so the underlying regex finds nothing.

        That fell through to the same `return 1`, which is why an NFO stock
        was blocked on an exchange whose table is otherwise fully populated.
        """
        assert qf.get_freeze_qty_for_option("360ONE29SEP26FUT", "NFO") == 0

    def test_longest_prefix_still_wins(self):
        """NIFTYNXT50 must not resolve to NIFTY's 1800."""
        qf._freeze_qty_cache["NFO:NIFTYNXT50"] = 6000
        assert qf.get_freeze_qty_for_option("NIFTYNXT5030SEP26FUT", "NFO") == 6000


class TestCallersTreatZeroAsNoLimit:
    """The contract the fix relies on: 0 disables enforcement, it does not
    become a limit of zero."""

    def test_zero_is_falsy_so_the_scalping_guard_skips(self):
        freeze = qf.get_freeze_qty_for_option("CRUDEOIL15OCT268850CE", "MCX")
        # blueprints/scalping.py:622
        assert not (freeze and freeze > 0)

    def test_a_real_limit_still_enforces(self):
        freeze = qf.get_freeze_qty_for_option("NIFTY30SEP2624000CE", "NFO")
        assert freeze and freeze > 0
        assert 2600 > freeze  # 40 NIFTY lots is genuinely over the freeze

    def test_the_exit_chunk_path_falls_back_rather_than_chunking_to_nothing(self):
        """blueprints/scalping.py:760-764, with MCX lot size 100."""
        lotsize = 100
        raw_freeze = qf.get_freeze_qty_for_option("CRUDEOIL15OCT268850CE", "MCX") or 0
        freeze = (raw_freeze // lotsize) * lotsize if raw_freeze else 0
        assert freeze == 0, "a zero chunk must fall through to the lot-based cap"
