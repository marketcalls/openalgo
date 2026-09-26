"""/api/v1/orderstatus reports an order's average across all its fills.

The service took average_price from the tradebook, stopping at the first row
whose orderid matched. A broker that reports one tradebook row per fill (Kite
always does) gives several rows for an order that filled in parts, so
orderstatus returned the first fill's price rather than the order's average
(issue #1987): 88.15 instead of 88.0833 on a 390-lot exit. Realised P&L built
on it drifted from the broker's books by the size of the split.

The fills below are one split consistent with the figures in the issue, not the
reporter's actual fills.
"""

import pytest

import services.orderbook_service as orderbook_service
import services.orderstatus_service as oss

ORDER_ID = "2095446703975997440"


class _Inline:
    """Stands in for the log executor and socketio: runs nothing, raises nothing."""

    def submit(self, *args, **kwargs):
        return None

    def emit(self, *args, **kwargs):
        return None

    def start_background_task(self, *args, **kwargs):
        return None


@pytest.fixture
def status_of(monkeypatch):
    """Returns a function that runs orderstatus against a given set of fills."""
    monkeypatch.setattr(oss, "get_analyze_mode", lambda: False)
    monkeypatch.setattr(oss, "log_executor", _Inline())
    monkeypatch.setattr(oss, "socketio", _Inline())
    monkeypatch.setattr(oss, "async_log_order", lambda *args, **kwargs: None)

    order = {"orderid": ORDER_ID, "symbol": "NIFTY08SEP2623900PE", "order_status": "complete"}
    monkeypatch.setattr(
        orderbook_service,
        "get_orderbook",
        lambda **kwargs: (True, {"status": "success", "data": {"orders": [dict(order)]}}, 200),
    )

    def run(fills):
        monkeypatch.setattr(
            oss,
            "get_tradebook",
            lambda **kwargs: (True, {"status": "success", "data": fills}, 200),
        )
        ok, response, status = oss.get_order_status_with_auth(
            {"orderid": ORDER_ID}, "token", "zerodha", {"orderid": ORDER_ID}
        )
        assert ok and status == 200, response
        return response["data"]["average_price"]

    return run


def fill(price, qty, orderid=ORDER_ID):
    return {"orderid": orderid, "average_price": price, "quantity": qty}


def test_multi_fill_order_reports_the_weighted_average(status_of):
    """The SELL exit from the issue: first fill 88.15, order average 88.0833."""
    fills = [fill(88.15, 130), fill(88.05, 260)]

    assert status_of(fills) == pytest.approx(88.083333333, abs=1e-9)


def test_equal_split_fill_reports_the_midpoint(status_of):
    """The BUY exit from the issue: first fill 138.60, order average 138.625."""
    fills = [fill(138.60, 195), fill(138.65, 195)]

    assert status_of(fills) == pytest.approx(138.625, abs=1e-9)


def test_other_orders_fills_are_ignored(status_of):
    fills = [fill(90.00, 50, orderid="other"), fill(88.15, 130), fill(88.05, 260)]

    assert status_of(fills) == pytest.approx(88.083333333, abs=1e-9)


def test_single_fill_is_unchanged(status_of):
    """Entries that filled in one go were already right and must stay so."""
    assert status_of([fill(86.40, 390)]) == pytest.approx(86.40)


def test_fills_without_quantity_fall_back_to_the_first_price(status_of):
    fills = [
        {"orderid": ORDER_ID, "average_price": 88.15},
        {"orderid": ORDER_ID, "average_price": 88.05},
    ]

    assert status_of(fills) == pytest.approx(88.15)


def test_full_precision_is_kept(status_of):
    """The issue asks for the broker's full precision, not a rounded 88.08."""
    price = status_of([fill(88.15, 130), fill(88.05, 260)])

    assert round(price, 2) != price
