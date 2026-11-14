"""The /latency order figures count order calls only (issue #2286).

Every endpoint wrapped by utils.latency_monitor logs a row to order_latency,
data queries (QUOTES, HISTORY, PING, FUNDS, ...) included. The dashboard's
"Total Orders Tracked", success rate, averages, SLA, percentiles and the
per-broker rows used to count every one of them as an order.
"""

import inspect
from datetime import datetime, timedelta

import pytest

import database.latency_db as latency_db
from database.latency_db import ORDER_TYPES, OrderLatency, latency_session


@pytest.fixture
def latency_table():
    latency_db.init_latency_db()
    latency_session.query(OrderLatency).delete()
    latency_session.commit()
    latency_db._stats_cache.clear()
    yield
    latency_session.rollback()
    latency_session.query(OrderLatency).delete()
    latency_session.commit()
    latency_session.remove()
    latency_db._stats_cache.clear()


def _row(order_type, total_ms, status="SUCCESS", broker="zerodha", timestamp=None):
    row = OrderLatency(
        order_id="unknown" if order_type not in ORDER_TYPES else f"ord-{total_ms}",
        user_id=1,
        broker=broker,
        symbol="SBIN",
        order_type=order_type,
        rtt_ms=total_ms,
        validation_latency_ms=0,
        response_latency_ms=0,
        overhead_ms=0,
        total_latency_ms=total_ms,
        status=status,
    )
    if timestamp is not None:
        row.timestamp = timestamp
    latency_session.add(row)
    latency_session.commit()


def _orders_and_data_calls():
    _row("PLACE", 50.0)
    _row("PLACE", 120.0)
    _row("CANCEL", 80.0, status="FAILED")
    # Data queries: slow history and quotes, a fast ping, and a FUNDS call
    # from a second broker that has placed no orders at all.
    _row("HISTORY", 1500.0)
    _row("QUOTES", 900.0)
    _row("PING", 5.0)
    _row("FUNDS", 300.0, broker="angel")


def test_overall_figures_count_only_order_calls(latency_table):
    _orders_and_data_calls()

    stats = OrderLatency.get_latency_stats()

    assert stats["total_orders"] == 3
    assert stats["failed_orders"] == 1
    assert stats["success_rate"] == pytest.approx(200 / 3)
    assert stats["avg_total"] == pytest.approx((50 + 120 + 80) / 3)
    assert stats["sla_100ms"] == pytest.approx(200 / 3)
    assert stats["sla_150ms"] == pytest.approx(100.0)
    assert stats["p99_total"] <= 120.0


def test_broker_rows_count_only_order_calls(latency_table):
    _orders_and_data_calls()

    broker_stats = OrderLatency.get_latency_stats()["broker_stats"]

    # The broker that only answered a FUNDS call has no order row.
    assert set(broker_stats) == {"zerodha"}
    zerodha = broker_stats["zerodha"]
    assert zerodha["total_orders"] == 3
    assert zerodha["failed_orders"] == 1
    assert zerodha["avg_total"] == pytest.approx((50 + 120 + 80) / 3)
    assert zerodha["p99_total"] <= 120.0
    assert zerodha["sla_150ms"] == pytest.approx(100.0)


def test_data_calls_are_reported_separately(latency_table):
    _orders_and_data_calls()

    assert OrderLatency.get_latency_stats()["non_order_calls"] == 4


def test_only_data_calls_report_no_orders(latency_table):
    _row("QUOTES", 400.0)
    _row("PING", 4.0)

    stats = OrderLatency.get_latency_stats()

    assert stats["total_orders"] == 0
    assert stats["avg_total"] == 0
    assert stats["p50_total"] == 0
    assert stats["broker_stats"] == {}
    assert stats["non_order_calls"] == 2


def test_purge_keeps_orders_and_drops_old_data_calls(latency_table):
    old = datetime.utcnow() - timedelta(days=30)
    _row("PLACE", 60.0, timestamp=old)
    _row("GTT_PLACE", 70.0, timestamp=old)
    _row("QUOTES", 300.0, timestamp=old)
    _row("QUOTES", 310.0)

    assert latency_db.purge_old_data_logs(days=7) == 1
    remaining = sorted(r.order_type for r in OrderLatency.query.all())
    assert remaining == ["GTT_PLACE", "PLACE", "QUOTES"]


def test_purge_drops_old_rows_without_a_type(latency_table):
    # The stats count a row with no type as a data call, so the purge must
    # drop it like one. SQL NOT IN never matches NULL.
    old = datetime.utcnow() - timedelta(days=30)
    _row(None, 40.0, timestamp=old)
    _row("PLACE", 60.0, timestamp=old)

    assert latency_db.purge_old_data_logs(days=7) == 1
    assert [r.order_type for r in OrderLatency.query.all()] == ["PLACE"]


def test_gtt_rows_from_before_the_gtt_mapping_still_count_as_orders(latency_table):
    # GTT calls were logged under their endpoint names before they were
    # mapped to GTT_*. Those rows are orders: counted, and never purged.
    old = datetime.utcnow() - timedelta(days=30)
    _row("PLACE_GTT_ORDER", 90.0, timestamp=old)
    _row("CANCEL_GTT_ORDER", 30.0)

    assert OrderLatency.get_latency_stats()["total_orders"] == 2
    assert latency_db.purge_old_data_logs(days=7) == 0


def test_monitor_keeps_forever_the_types_the_dashboard_counts():
    from utils import latency_monitor

    assert latency_monitor.KEEP_FOREVER_TYPES == ORDER_TYPES
    # The session routes' decorators log these types; each is an order.
    assert {"PLACE", "CLOSE", "CANCEL_ALL"} <= ORDER_TYPES


def test_broker_histogram_counts_only_order_calls(latency_table):
    from blueprints.latency import get_histogram_data

    _orders_and_data_calls()

    histogram = get_histogram_data("zerodha")

    assert sum(histogram["counts"]) == 3
    assert histogram["max_rtt"] == pytest.approx(120.0)


def test_logs_api_flags_order_calls(latency_table):
    from flask import Flask

    from blueprints import latency

    _row("PLACE", 50.0)
    _row("QUOTES", 900.0)

    view = inspect.unwrap(latency.get_logs)
    with Flask(__name__).test_request_context("/latency/api/logs"):
        logs = view().get_json()

    assert {log["order_type"]: log["is_order"] for log in logs} == {
        "PLACE": True,
        "QUOTES": False,
    }
