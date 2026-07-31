"""SL-M price-type conversion for the Noren brokers (Shoonya, Flattrade).

These OMSes reject both MKT and SL-MKT for API orders, so transform_data
converts MARKET -> LMT and SL-M -> SL-LMT with a Market Price Protection
buffer. The happy path prices off the quote; these tests cover the *fallback*
path — no auth token, LTP 0, or a quote exception — where two rejections are
one line apart:

  * falling through as SL-MKT (the price type the broker refuses), and
  * emitting an off-tick limit price (calculate_protected_price rounds to two
    decimals when it has no tick size, which a 0.05-tick instrument rejects).

Both brokers delegate to utils.mpp_slab.protected_limit_from_trigger, so every
test here runs against both to prove they still share one implementation.

No sockets, no broker HTTP: transform_data is exercised directly with the
symbol lookups stubbed.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DATABASE_URL", "sqlite:///tmp/test_noren_slm_mpp.db")
os.environ.setdefault("API_KEY_PEPPER", "a" * 64)

from broker.flattrade.mapping import transform_data as flattrade  # noqa: E402
from broker.shoonya.mapping import transform_data as shoonya  # noqa: E402

MODULES = [("shoonya", shoonya), ("flattrade", flattrade)]

TRIGGER = 86.05  # deliberately a 0.05-tick value, as the exchange would have it

BASE_ORDER = {
    "apikey": "K1",
    "symbol": "NHPC",
    "exchange": "NSE",
    "quantity": 100,
    "price": "0",
    "trigger_price": str(TRIGGER),
    "product": "MIS",
    "action": "SELL",
}


class _SymbolInfo:
    def __init__(self, tick_size):
        self.tick_size = tick_size


def _set_tick_size(monkeypatch, tick_size):
    """Point the shared fallback's SymToken lookup at a known tick size.

    protected_limit_from_trigger imports get_symbol_info lazily from
    database.token_db, so patching it there covers both brokers at once —
    which is the point of the shared helper.
    """
    import database.token_db as token_db

    info = _SymbolInfo(tick_size) if tick_size else None
    monkeypatch.setattr(token_db, "get_symbol_info", lambda s, e: info)


@pytest.fixture(autouse=True)
def _stub_symbol_lookups(monkeypatch):
    """Keep the master-contract DB out of it; each test sets its own tick size."""
    for _name, module in MODULES:
        monkeypatch.setattr(module, "get_br_symbol", lambda s, e: f"{s}-EQ")
    _set_tick_size(monkeypatch, None)


def _on_tick(price, tick_size):
    return abs(round(float(price) / tick_size) * tick_size - float(price)) < 1e-9


@pytest.mark.parametrize("name,module", MODULES)
def test_slm_never_leaves_as_sl_mkt_without_a_quote(name, module):
    # No auth token -> the quote-based conversion never runs. The order must
    # still go out as SL-LMT, not the SL-MKT the OMS refuses.
    out = module.transform_data({**BASE_ORDER, "pricetype": "SL-M"}, None, auth_token=None)
    assert out["prctyp"] == "SL-LMT", name
    assert float(out["trgprc"]) == TRIGGER, name


@pytest.mark.parametrize("name,module", MODULES)
def test_slm_fallback_limit_is_tick_valid_without_a_tick_size(name, module):
    # Master contract has no tick size for the symbol: fall back to the trigger
    # itself, which is tick-valid by construction, rather than a 2-decimal
    # rounded price that a 0.05-tick instrument would reject.
    out = module.transform_data({**BASE_ORDER, "pricetype": "SL-M"}, None, auth_token=None)
    assert float(out["prc"]) == TRIGGER, name


@pytest.mark.parametrize("name,module", MODULES)
@pytest.mark.parametrize("tick_size", [0.05, 0.01])
def test_slm_fallback_buffers_and_aligns_when_the_tick_size_is_known(
    name, module, tick_size, monkeypatch
):
    _set_tick_size(monkeypatch, tick_size)

    sell = module.transform_data({**BASE_ORDER, "pricetype": "SL-M"}, None, auth_token=None)
    buy = module.transform_data(
        {**BASE_ORDER, "pricetype": "SL-M", "action": "BUY"}, None, auth_token=None
    )

    # A sell stop needs the limit *below* the trigger to fill on the way down,
    # a buy stop *above* it — and both must land on the tick grid.
    assert float(sell["prc"]) < TRIGGER, name
    assert float(buy["prc"]) > TRIGGER, name
    assert _on_tick(sell["prc"], tick_size), (name, sell["prc"])
    assert _on_tick(buy["prc"], tick_size), (name, buy["prc"])


@pytest.mark.parametrize("name,module", MODULES)
def test_slm_survives_a_failing_symbol_lookup(name, module, monkeypatch):
    import database.token_db as token_db

    def boom(symbol, exchange):
        raise RuntimeError("symbol cache cold")

    monkeypatch.setattr(token_db, "get_symbol_info", boom)
    out = module.transform_data({**BASE_ORDER, "pricetype": "SL-M"}, None, auth_token=None)
    assert out["prctyp"] == "SL-LMT", name
    assert float(out["prc"]) == TRIGGER, name


@pytest.mark.parametrize("name,module", MODULES)
def test_market_fallback_is_left_alone(name, module):
    # Unlike SL-M, a MARKET order has no reference price without a quote —
    # there is nothing to protect off, so it stays MKT and the broker's own
    # rejection is the honest outcome. Pinned so the SL-M fix does not creep.
    out = module.transform_data({**BASE_ORDER, "pricetype": "MARKET"}, None, auth_token=None)
    assert out["prctyp"] == "MKT", name


def test_shared_helper_handles_a_missing_trigger(monkeypatch):
    # Direct coverage of the utils/mpp_slab entry point both brokers call —
    # an SL-M with no usable trigger has nothing to price off, so the caller's
    # value passes through and the broker's own validation reports it.
    from utils.mpp_slab import protected_limit_from_trigger

    _set_tick_size(monkeypatch, 0.05)
    for missing in (None, 0, "0", ""):
        assert float(protected_limit_from_trigger("NHPC", "NSE", "SELL", missing)) == 0.0


def test_shared_helper_uses_the_options_slab(monkeypatch):
    # The slab is instrument-aware: options get a wider buffer than equity at
    # the same price (5% under 10 vs 2% under 100), derived from the symbol.
    from utils.mpp_slab import protected_limit_from_trigger

    _set_tick_size(monkeypatch, 0.05)
    option = float(protected_limit_from_trigger("NIFTY28MAR2420800CE", "NFO", "BUY", 8.0))
    equity = float(protected_limit_from_trigger("NHPC", "NSE", "BUY", 8.0))
    assert option > equity > 8.0


@pytest.mark.parametrize("name,module", MODULES)
def test_plain_sl_and_limit_are_untouched(name, module):
    sl = module.transform_data(
        {**BASE_ORDER, "pricetype": "SL", "price": "85"}, None, auth_token=None
    )
    assert sl["prctyp"] == "SL-LMT" and sl["prc"] == "85", name

    limit = module.transform_data(
        {**BASE_ORDER, "pricetype": "LIMIT", "price": "85"}, None, auth_token=None
    )
    assert limit["prctyp"] == "LMT" and limit["prc"] == "85", name
