from unittest.mock import patch

from broker.zerodha.mapping.order_data import (
    calculate_order_statistics,
    map_order_data,
    transform_order_data,
)


def _order(status, order_id="1"):
    return {
        "order_id": order_id,
        "status": status,
        "tradingsymbol": "SBIN",
        "exchange": "NSE",
        "transaction_type": "BUY",
        "quantity": 1,
        "order_type": "SL-M",
        "product": "MIS",
    }


def test_transient_rest_statuses_do_not_inherit_previous_order_status():
    transformed = transform_order_data(
        [
            _order("COMPLETE", "1"),
            _order("OPEN PENDING", "2"),
            _order("VALIDATION PENDING", "3"),
            _order("KITE FUTURE STATE", "4"),
        ]
    )

    assert [order["order_status"] for order in transformed] == [
        "complete",
        "open",
        "open",
        "kite future state",
    ]


def test_first_order_in_flight_has_a_status():
    [transformed] = transform_order_data([_order("OPEN PENDING")])

    assert transformed["order_status"] == "open"


def test_rest_order_book_exposes_trigger_pending_as_actionable_open():
    orders = [_order("TRIGGER PENDING")]
    [transformed] = transform_order_data(orders)

    assert transformed["order_status"] == "open"
    assert calculate_order_statistics(orders)["total_open_orders"] == sum(
        order["order_status"] == "open" for order in transform_order_data(orders)
    )


def test_statistics_count_trigger_pending_and_in_flight_as_open():
    stats = calculate_order_statistics(
        [
            _order("COMPLETE", "1"),
            _order("TRIGGER PENDING", "2"),
            _order("OPEN PENDING", "3"),
            _order("CANCELLED", "4"),
            _order("OPEN", "5"),
            _order("REJECTED", "6"),
        ]
    )

    assert stats == {
        "total_buy_orders": 6,
        "total_sell_orders": 0,
        "total_completed_orders": 1,
        "total_open_orders": 3,
        "total_rejected_orders": 1,
    }


def test_cancelled_order_preserves_verified_fill_in_position_units():
    def public_row(exchange, symbol, quantity, **fields):
        row = {
            **_order("CANCELLED"),
            "exchange": exchange,
            "tradingsymbol": symbol,
            "quantity": quantity,
            **fields,
        }
        with patch("broker.zerodha.mapping.order_data.get_oa_symbol", return_value=symbol):
            [public] = transform_order_data(map_order_data({"data": [row]}))
        return public

    assert public_row("NFO", "OPT", 50, filled_quantity=20)["filled_quantity"] == 20
    assert public_row("NFO", "OPT", 50, filled_quantity=0)["filled_quantity"] == 0
    crude = public_row("MCX", "CRUDEOIL26NOVFUT", 4, filled_quantity=2)
    assert (crude["quantity"], crude["filled_quantity"]) == (400, 200)
    assert "filled_quantity" not in public_row("NFO", "OPT", 50)
    for invalid in (None, True, -1, 5, 1.5, "bad"):
        assert "filled_quantity" not in public_row(
            "MCX", "CRUDEOIL26NOVFUT", 4, filled_quantity=invalid
        )


def test_order_status_reports_cancelled_partial_fill_without_guessing_from_position():
    from services.orderstatus_service import get_order_status_with_auth

    rows = [_order("CANCELLED", "partial") | {"quantity": 50, "filled_quantity": 20}]
    with (
        patch("services.orderstatus_service.get_analyze_mode", return_value=False),
        patch("database.settings_db.get_analyze_mode", return_value=False),
        patch("broker.zerodha.api.order_api.get_order_book", return_value={"data": rows}),
        patch("broker.zerodha.mapping.order_data.get_oa_symbol", return_value="SBIN"),
        patch("services.orderstatus_service.log_executor.submit"),
    ):
        success, response, code = get_order_status_with_auth(
            {"orderid": "partial"}, "test", "zerodha", {}
        )
    assert success and code == 200
    order = response["data"]
    assert (
        order["orderid"],
        order["order_status"],
        order["quantity"],
        order["filled_quantity"],
    ) == ("partial", "cancelled", 50, 20)
