"""AliceBlue SL / SL-M order mapping.

Validation, not a bug report: the mapping was checked against
broker-api-docs/aliceblue-api-docs (16-appendix.md gives SL = STOP LOSS and
SLM = STOPLOSS MARKET; 04-orders-management.md gives slTriggerPrice as the
trigger field) and against broker/dhan, broker/zerodha and broker/fyers. All
four price types map and round-trip correctly. These tests pin that.

The one hardening: an unknown pricetype still falls back to MARKET for
compatibility, but now logs. Silently turning a mistyped stop into an order
that fills immediately is the opposite of what was asked for, and "SLM" -
AliceBlue's own wire code for SL-M - is an easy thing to send by mistake.
broker/fyers logs at the same spot; zerodha and aliceblue did not.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

td = pytest.importorskip("broker.aliceblue.mapping.transform_data")


@pytest.mark.parametrize(
    "pricetype,expected",
    [("MARKET", "MARKET"), ("LIMIT", "LIMIT"), ("SL", "SL"), ("SL-M", "SLM")],
)
def test_price_types_map_to_the_documented_codes(pricetype, expected):
    assert td.map_order_type(pricetype) == expected


@pytest.mark.parametrize("pricetype", ["MARKET", "LIMIT", "SL", "SL-M"])
def test_price_types_round_trip(pricetype):
    """A resting SL must read back as SL in the orderbook, not as MARKET."""
    assert td.reverse_map_order_type(td.map_order_type(pricetype)) == pricetype


def test_unknown_pricetype_is_logged_rather_than_silently_becoming_market(caplog):
    """"SLM" is AliceBlue's own code - a plausible thing to send by mistake."""
    with caplog.at_level("WARNING"):
        assert td.map_order_type("SLM") == "MARKET"

    assert any("Unknown pricetype" in r.message for r in caplog.records), (
        "a mistyped stop silently became a live MARKET order with no warning"
    )


def test_sl_carries_both_a_limit_price_and_a_trigger():
    """Stop-limit needs both; losing either changes what the order does."""
    payload = td.transform_data(
        {
            "symbol": "RELIANCE", "exchange": "NSE", "action": "BUY", "quantity": 1,
            "product": "MIS", "pricetype": "SL", "price": 1290, "trigger_price": 1295,
        }
    )
    assert payload["orderType"] == "SL"
    assert payload["price"] == "1290"
    assert payload["slTriggerPrice"] == "1295"


def test_sl_m_carries_a_trigger_and_no_limit_price():
    payload = td.transform_data(
        {
            "symbol": "RELIANCE", "exchange": "NSE", "action": "BUY", "quantity": 1,
            "product": "MIS", "pricetype": "SL-M", "price": 0, "trigger_price": 1295,
        }
    )
    assert payload["orderType"] == "SLM"
    assert payload["slTriggerPrice"] == "1295"
    assert payload["price"] == "0"


@pytest.mark.parametrize("pricetype,expected", [("SL", "SL"), ("SL-M", "SLM")])
def test_modify_preserves_the_stop_type_and_trigger(pricetype, expected):
    """Modifying a resting stop must not quietly convert it to something else."""
    payload = td.transform_modify_order_data(
        {
            "orderid": "25080700001", "quantity": 1, "pricetype": pricetype,
            "price": 1290, "trigger_price": 1295,
        }
    )
    assert payload["orderType"] == expected
    assert payload["slTriggerPrice"] == "1295"
