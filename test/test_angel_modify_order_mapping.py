"""Angel One modify-order mapping.

Angel reads a stop-loss order's trigger from ``triggerprice``. The modify
mapping used to send the new trigger only as ``stoploss``, so modifying an SL
order returned success while the trigger stayed where it was.
"""

from broker.angel.mapping.transform_data import transform_modify_order_data


def _modify(pricetype, price, trigger_price):
    return {
        "orderid": "261023000520814",
        "symbol": "NIFTY27OCT2622500PE",
        "exchange": "NFO",
        "pricetype": pricetype,
        "product": "NRML",
        "quantity": "195",
        "price": price,
        "trigger_price": trigger_price,
        "disclosed_quantity": "0",
    }


def test_modify_sl_sends_the_new_trigger_as_triggerprice():
    out = transform_modify_order_data(_modify("SL", "142.50", "150.00"), "12345")

    assert out["variety"] == "STOPLOSS"
    assert out["ordertype"] == "STOPLOSS_LIMIT"
    assert out["price"] == "142.50"
    assert out["triggerprice"] == "150.00"


def test_modify_sl_m_sends_the_new_trigger_as_triggerprice():
    out = transform_modify_order_data(_modify("SL-M", "0", "150.00"), "12345")

    assert out["ordertype"] == "STOPLOSS_MARKET"
    assert out["triggerprice"] == "150.00"


def test_modify_without_a_trigger_sends_zero():
    data = _modify("LIMIT", "16.5", "0")
    del data["trigger_price"]

    out = transform_modify_order_data(data, "12345")

    assert out["triggerprice"] == "0"
