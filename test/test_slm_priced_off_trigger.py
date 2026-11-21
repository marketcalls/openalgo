"""SL-M sent as SL-LMT is priced off the trigger, not the LTP (issue #2390).

Shoonya, Flattrade and Firstock refuse SL-MKT from API sessions, so OpenAlgo
sends SL-M as SL-LMT. The limit used to be computed from the current LTP: a
SELL stop with trigger 980 while the LTP was 1000 went out with a limit near
995, above its own trigger, so the triggered order rested away from the market.
"""

from types import SimpleNamespace
from unittest import mock

import pytest

from broker.firstock.mapping import transform_data as firstock
from broker.flattrade.mapping import transform_data as flattrade
from broker.shoonya.mapping import transform_data as shoonya
from utils.mpp_slab import calculate_stop_limit_price


class TestCalculateStopLimitPrice:
    @pytest.mark.parametrize(
        "trigger, action, instrument_type, tick, expected",
        [
            (980, "SELL", "EQ", 0.05, 975.1),  # 0.5% below
            (1020, "BUY", "EQ", 0.05, 1025.1),  # 0.5% above
            (50, "SELL", "EQ", 0.05, 49.0),  # 2% below
            (5, "BUY", "CE", 0.05, 5.25),  # 5% above
            (100.05, "SELL", "EQ", 0.01, 99.04),  # floored away from the trigger
            (0.1, "BUY", "PE", 0.05, 0.15),  # at least one tick past the trigger
        ],
    )
    def test_limit_is_beyond_the_trigger_in_the_fill_direction(
        self, trigger, action, instrument_type, tick, expected
    ):
        assert calculate_stop_limit_price(trigger, action, instrument_type, tick) == expected

    @pytest.mark.parametrize("trigger", [0, None, -5])
    def test_refuses_without_a_trigger(self, trigger):
        with pytest.raises(ValueError, match="trigger price"):
            calculate_stop_limit_price(trigger, "SELL", "EQ", 0.05)

    @pytest.mark.parametrize("tick", [None, 0])
    def test_without_a_tick_size_the_trigger_is_the_limit(self, tick):
        assert calculate_stop_limit_price(980, "SELL", "EQ", tick) == 980
        assert calculate_stop_limit_price(1020, "BUY", "EQ", tick) == 1020

    def test_refuses_a_sell_limit_that_would_not_be_positive(self):
        with pytest.raises(ValueError, match="too low"):
            calculate_stop_limit_price(0.05, "SELL", "CE", 0.05)


ORDER = {
    "apikey": "FA0001",
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "quantity": "1",
    "pricetype": "SL-M",
    "product": "MIS",
    "price": "0",
}

BROKERS = [
    pytest.param(
        shoonya, "broker.shoonya.api.data.BrokerData", ("prctyp", "prc", "trgprc"), id="shoonya"
    ),
    pytest.param(
        flattrade,
        "broker.flattrade.mapping.transform_data.BrokerData",
        ("prctyp", "prc", "trgprc"),
        id="flattrade",
    ),
    pytest.param(
        firstock,
        "broker.firstock.api.data.BrokerData",
        ("priceType", "price", "triggerPrice"),
        id="firstock",
    ),
]


def transform(module, broker_data_path, **order):
    """Run the broker's transform_data with the LTP at 1000 and a 0.05 tick."""
    quotes = mock.Mock()
    quotes.return_value.get_quotes.return_value = {"ltp": 1000.0, "tick_size": 0.05}
    with (
        mock.patch.object(module, "get_br_symbol", return_value="RELIANCE-EQ"),
        mock.patch.object(module, "get_symbol_info", return_value=SimpleNamespace(tick_size=0.05)),
        mock.patch(broker_data_path, quotes),
    ):
        return module.transform_data({**ORDER, **order}, "2885", auth_token="token")


@pytest.mark.parametrize("module, broker_data_path, keys", BROKERS)
def test_sell_stop_limit_is_below_its_trigger(module, broker_data_path, keys):
    order_type, price, trigger = keys
    out = transform(module, broker_data_path, action="SELL", trigger_price="980")

    assert out[order_type] == "SL-LMT"
    assert out[trigger] == "980"
    assert float(out[price]) == 975.1
    assert float(out[price]) < 980


@pytest.mark.parametrize("module, broker_data_path, keys", BROKERS)
def test_buy_stop_limit_is_above_its_trigger(module, broker_data_path, keys):
    order_type, price, trigger = keys
    out = transform(module, broker_data_path, action="BUY", trigger_price="1020")

    assert out[order_type] == "SL-LMT"
    assert out[trigger] == "1020"
    assert float(out[price]) == 1025.1
    assert float(out[price]) > 1020


@pytest.mark.parametrize("module, broker_data_path, keys", BROKERS)
@pytest.mark.parametrize(
    "symbol_info",
    [
        {"return_value": None},
        {"return_value": SimpleNamespace(tick_size=None)},
        {"side_effect": RuntimeError("cache not loaded")},
    ],
    ids=["no-row", "no-tick", "lookup-error"],
)
def test_sl_m_without_symbol_metadata_uses_the_trigger_as_limit(
    module, broker_data_path, keys, symbol_info
):
    order_type, price, trigger = keys
    with (
        mock.patch.object(module, "get_br_symbol", return_value="RELIANCE-EQ"),
        mock.patch.object(module, "get_symbol_info", **symbol_info),
    ):
        out = module.transform_data(
            {**ORDER, "action": "SELL", "trigger_price": "980"}, "2885", auth_token="token"
        )

    assert out[order_type] == "SL-LMT"
    assert out[trigger] == "980"
    assert float(out[price]) == 980


@pytest.mark.parametrize("module, broker_data_path, keys", BROKERS)
def test_sl_m_without_a_trigger_is_refused(module, broker_data_path, keys):
    with pytest.raises(ValueError, match="trigger price"):
        transform(module, broker_data_path, action="SELL", trigger_price="0")


@pytest.mark.parametrize("module, broker_data_path, keys", BROKERS)
def test_market_is_still_priced_off_the_ltp(module, broker_data_path, keys):
    order_type, price, _ = keys
    out = transform(module, broker_data_path, action="BUY", pricetype="MARKET")

    assert out[order_type] == "LMT"
    assert float(out[price]) == 1005.0


def test_firstock_modify_prices_sl_m_off_the_trigger():
    with (
        mock.patch.object(firstock, "get_br_symbol", return_value="RELIANCE-EQ"),
        mock.patch.object(
            firstock, "get_symbol_info", return_value=SimpleNamespace(tick_size=0.05)
        ),
    ):
        out = firstock.transform_modify_order_data(
            {**ORDER, "orderid": "1", "action": "SELL", "trigger_price": "980"}, "2885", "token"
        )

    assert out["priceType"] == "SL-LMT"
    assert out["triggerPrice"] == "980"
    assert float(out["price"]) == 975.1
    assert out["mkt_protection"] == "0"
