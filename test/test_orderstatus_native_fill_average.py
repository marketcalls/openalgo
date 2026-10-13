"""Native Delta execution facts survive the final order-status response."""

from copy import deepcopy

import pytest

from broker.deltaexchange.mapping import order_data
from services import orderbook_service, orderstatus_service


@pytest.fixture
def status(monkeypatch):
    monkeypatch.setattr(orderstatus_service, "get_analyze_mode", lambda: False)
    monkeypatch.setattr(orderstatus_service.log_executor, "submit", lambda *a, **k: None)
    monkeypatch.setattr(order_data, "get_symbol", lambda *a: None)

    def run(*, broker="deltaexchange", **changes):
        native = {
            "id": 1234, "product_id": 7, "product_symbol": "P-TEST-100-010130",
            "side": "sell", "size": 250, "unfilled_size": 0,
            "average_fill_price": "7.12345", "state": "closed", "order_type": "market_order",
            "limit_price": None, "created_at": "2030-01-01T10:00:00.123456Z", **changes,
        }
        orders = orderbook_service.format_order_data(
            order_data.transform_order_data(order_data.map_order_data([native])))
        monkeypatch.setattr(orderbook_service, "get_orderbook_with_auth", lambda *args, **kwargs:
                            (True, {"status": "success", "data": {"orders": deepcopy(orders)}}, 200))
        fill_reads = []

        def tradebook(**kwargs):
            fill_reads.append(kwargs)
            return True, {"status": "success", "data": [
                {"orderid": "7:1234", "quantity": 250, "average_price": 8.99}]}, 200

        monkeypatch.setattr(orderstatus_service, "get_tradebook", tradebook)
        success, response, code = orderstatus_service.get_order_status_with_auth(
            {"orderid": "7:1234"}, "test-auth", broker, {})
        assert success and code == 200
        return response["data"], fill_reads

    return run


@pytest.mark.parametrize("unfilled,state,filled", [(0, "closed", "250"), (175, "open", "75")])
def test_native_average_is_preserved_without_rounded_fill_lookup(status, unfilled, state, filled):
    row, reads = status(unfilled_size=unfilled, state=state)
    assert row["average_price"] == "7.12345"
    assert row["filled_quantity"] == filled
    assert reads == []


@pytest.mark.parametrize("updates", [
    {"average_fill_price": 0}, {"average_fill_price": "0"}, {"average_fill_price": "NaN"},
    {"average_fill_price": -1}, {"unfilled_size": 250}, {"unfilled_size": -1},
    {"size": "NaN"},
])
def test_open_order_does_not_report_invalid_native_average(status, updates):
    row, reads = status(**{"state": "open", "unfilled_size": 175, **updates})
    assert row["average_price"] == 0.0
    assert reads == []


@pytest.mark.parametrize("updates", [{"average_fill_price": "0"}, {"unfilled_size": 175}])
def test_complete_order_without_valid_full_native_fill_keeps_existing_fallback(status, updates):
    row, reads = status(**updates)
    assert row["average_price"] == 8.99
    assert len(reads) == 1


def test_other_broker_keeps_existing_tradebook_fallback(status):
    row, reads = status(broker="zerodha")
    assert row["average_price"] == 8.99
    assert len(reads) == 1
