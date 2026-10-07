from broker.zerodha.mapping.order_data import (
    calculate_order_statistics,
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
    [transformed] = transform_order_data([_order("TRIGGER PENDING")])

    assert transformed["order_status"] == "open"


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
