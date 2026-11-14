"""The latency monitor reports each group of endpoints on its own.

Every `/api/v1` call is timed. The monitor used to put all of them into one
average, one P99 and one share under 150 ms, on a page that called them orders,
so a chart loading its history decided the figures a trader read as order
speed: an install with 2,607 records and no order at all showed "2,607 orders
tracked" (issues #2421 and #2286).

There was a second fault under that one. The table that gave each endpoint its
tag was keyed by names typed in by hand, and six matched no endpoint. Options
orders were stored under tags the keep list did not have, and their latency was
deleted after a week as though they were data queries.

The cases here pin both: what belongs to which group and is kept, and that a
group's figures come from that group's records and no others.
"""

import csv
import io
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from flask import Flask

import database.latency_db as latency_db
import database.latency_groups as groups
from database.latency_db import OrderLatency, latency_session

ROOT = Path(__file__).resolve().parents[1]


# --- what belongs where ------------------------------------------------------


def _registered_namespaces():
    """Every `/api/v1` namespace that serves something, by name."""
    from restx_api import api

    return {namespace.name for namespace in api.namespaces if namespace.resources}


def test_every_registered_endpoint_is_in_a_group():
    """A new endpoint has to be placed, or its calls fall into "Other" unseen."""
    unplaced = sorted(_registered_namespaces() - set(groups.TAG_FOR_NAMESPACE))

    assert not unplaced, (
        f"{', '.join(unplaced)} is registered in restx_api but is in no latency group. "
        "Add an Endpoint for it to the right Group in database/latency_groups.py."
    )


def test_no_group_names_an_endpoint_that_does_not_exist():
    """The old table had six names that matched nothing, and nothing noticed."""
    unknown = sorted(set(groups.TAG_FOR_NAMESPACE) - _registered_namespaces())

    assert not unknown, f"database/latency_groups.py names no such endpoint: {unknown}"


def test_a_tag_belongs_to_one_group_and_fits_its_column():
    seen = {}
    for group in groups.GROUPS:
        for endpoint in group.endpoints:
            assert endpoint.tag not in seen, (
                f"{endpoint.tag} is in {seen[endpoint.tag]} and {group.key}"
            )
            seen[endpoint.tag] = group.key
            assert len(endpoint.tag) <= OrderLatency.order_type.type.length, endpoint.tag
            assert endpoint.label and endpoint.namespaces, endpoint.tag

    assert not set(groups.LEGACY_TAGS) & set(seen), "a legacy spelling is also a current tag"
    assert set(groups.LEGACY_TAGS.values()) <= set(seen)


def test_every_order_endpoint_is_kept_as_an_order():
    """Options orders were recorded under tags that were on no keep list."""
    from utils.latency_monitor import KEEP_FOREVER_TYPES

    for namespace in (
        "place_order",
        "place_smart_order",
        "optionsorder",
        "optionsmultiorder",
        "basket_order",
        "split_order",
        "modify_order",
        "cancel_order",
        "cancel_all_order",
        "close_position",
        "place_gtt_order",
        "modify_gtt_order",
        "cancel_gtt_order",
    ):
        tag = groups.TAG_FOR_NAMESPACE[namespace]
        assert groups.group_key_of(tag) == groups.ORDERS, namespace
        assert tag in KEEP_FOREVER_TYPES, f"{namespace} is recorded as {tag}, which is not kept"

    # Rows already written under the old spellings are still orders.
    assert {"OPTIONSORDER", "OPTIONSMULTIORDER"} <= KEEP_FOREVER_TYPES
    assert groups.canonical("OPTIONSORDER") == "OPTIONS"
    assert KEEP_FOREVER_TYPES is groups.ORDER_TAGS, "the keep list has to be the one list"


def test_a_read_is_not_an_order():
    for namespace in ("gtt_orderbook", "orderbook", "orderstatus", "history", "quotes", "funds"):
        tag = groups.TAG_FOR_NAMESPACE[namespace]
        assert tag not in groups.ORDER_TAGS, namespace


def test_routes_timed_outside_the_api_use_a_tag_that_is_in_a_group():
    """The scalping and Positions routes carry their tag in a decorator."""
    used = {}
    for path in sorted((ROOT / "blueprints").glob("*.py")):
        for tag in re.findall(
            r'@track_latency\(\s*"([^"]+)"\s*\)', path.read_text(encoding="utf-8")
        ):
            used.setdefault(tag, path.name)

    assert used, "no @track_latency route was found: has the decorator been renamed?"
    stray = {tag: where for tag, where in used.items() if tag not in groups.KNOWN_TAGS}
    assert not stray, f"timed under a tag that is in no group: {stray}"


# --- a database of its own ---------------------------------------------------


@pytest.fixture
def latency(tmp_path):
    """The latency tables in a file of their own, empty.

    The shared test database is written to by every other test that makes an
    API call, and these figures are totals: one stray record changes them.
    """
    from database.engine_factory import create_db_engine

    engine = create_db_engine(f"sqlite:///{tmp_path / 'latency.db'}")
    latency_db.LatencyBase.metadata.create_all(engine)
    latency_session.remove()
    latency_session.configure(bind=engine)
    latency_db._stats_cache.clear()

    yield

    latency_session.remove()
    latency_session.configure(bind=latency_db.latency_engine)
    latency_db._stats_cache.clear()
    engine.dispose()


def _record(tag, total, *, count=1, broker="zerodha", status="SUCCESS", age_days=0, rtt=None):
    stamp = datetime.utcnow() - timedelta(days=age_days)
    for _ in range(count):
        latency_session.add(
            OrderLatency(
                timestamp=stamp,
                order_id="1",
                broker=broker,
                symbol="SBIN",
                order_type=tag,
                rtt_ms=total * 0.8 if rtt is None else rtt,
                validation_latency_ms=0,
                response_latency_ms=0,
                overhead_ms=total * 0.2 if rtt is None else total - rtt,
                total_latency_ms=total,
                status=status,
            )
        )
    latency_session.commit()
    latency_db._stats_cache.clear()


def _stats(group=groups.DEFAULT_GROUP):
    return OrderLatency.get_latency_stats(group)


def _counts(stats):
    return {item["key"]: item["count"] for item in stats["groups"]}


# --- a group's figures are its own -------------------------------------------


def test_data_calls_are_not_counted_as_orders(latency):
    """The report of #2421: history calls hid the order latency."""
    _record("PLACE", 60, count=3)
    _record("HISTORY", 1200, count=200)

    orders = _stats()

    assert orders["group"] == "orders" and orders["rated"] is True
    assert orders["total_orders"] == 3
    assert orders["avg_total"] == pytest.approx(60)
    assert orders["p99_total"] == pytest.approx(60)
    assert orders["sla_150ms"] == pytest.approx(100)
    assert orders["distribution"] == {"excellent": 3, "good": 0, "acceptable": 0, "slow": 0}

    data = _stats("market_data")
    assert data["total_orders"] == 200 and data["rated"] is False
    assert data["avg_total"] == pytest.approx(1200)

    everything = _stats("all")
    assert everything["total_orders"] == 203
    assert everything["avg_total"] == pytest.approx((3 * 60 + 200 * 1200) / 203)


def test_an_install_with_no_orders_shows_none(latency):
    """What the page showed as "2,607 orders tracked"."""
    _record("HISTORY", 40, count=25)
    _record("ORDERBOOK", 5, count=4)

    orders = _stats()

    assert orders["total_orders"] == 0
    assert orders["avg_total"] == 0 and orders["endpoints"] == [] and orders["broker_stats"] == {}
    assert _counts(orders) == {
        "orders": 0,
        "account": 4,
        "market_data": 25,
        "options": 0,
        "reference": 0,
        "tools": 0,
        "all": 29,
    }


def test_each_endpoint_of_a_group_is_reported_on_its_own(latency):
    """History is expected to be slow. It must not be averaged into the quotes."""
    _record("QUOTES", 20, count=10)
    _record("HISTORY", 900, count=5, status="FAILED")
    _record("HISTORY", 1100, count=5)

    rows = {row["type"]: row for row in _stats("market_data")["endpoints"]}

    assert list(rows) == ["QUOTES", "HISTORY"], "endpoints are listed in their group's order"
    assert rows["QUOTES"]["label"] == "Quote" and rows["HISTORY"]["label"] == "History"
    assert rows["QUOTES"]["total_orders"] == 10
    assert rows["QUOTES"]["avg_total"] == pytest.approx(20)
    assert rows["QUOTES"]["p99_total"] == pytest.approx(20)
    assert rows["HISTORY"]["total_orders"] == 10 and rows["HISTORY"]["failed_orders"] == 5
    assert rows["HISTORY"]["avg_total"] == pytest.approx(1000)
    assert rows["HISTORY"]["p50_total"] == pytest.approx(1000)


def test_an_average_across_endpoints_is_weighted_by_how_often_each_was_called(latency):
    """An average of the two endpoint averages would say 55 ms."""
    _record("PLACE", 100, count=1)
    _record("CANCEL", 10, count=9)

    assert _stats()["avg_total"] == pytest.approx(19)


def test_the_broker_table_and_the_split_of_time_are_for_the_group(latency):
    _record("PLACE", 100, count=2, broker="zerodha", rtt=90)
    _record("PLACE", 300, count=2, broker="dhan", rtt=250)
    _record("HISTORY", 2000, count=50, broker="zerodha")

    orders = _stats()

    assert set(orders["broker_stats"]) == {"zerodha", "dhan"}
    assert orders["broker_stats"]["zerodha"]["total_orders"] == 2
    assert orders["broker_stats"]["zerodha"]["avg_total"] == pytest.approx(100)
    assert orders["broker_stats"]["zerodha"]["sla_150ms"] == pytest.approx(100)
    assert orders["broker_stats"]["dhan"]["sla_150ms"] == pytest.approx(0)
    assert orders["avg_rtt"] == pytest.approx(170)
    assert orders["avg_overhead"] == pytest.approx(30)


def test_the_speed_bands_count_every_record_of_the_group(latency):
    """They used to be counted from the hundred newest records of any kind."""
    _record("PLACE", 100, count=150)
    _record("PLACE", 200, count=30)
    _record("PLACE", 300, count=15)
    _record("PLACE", 500, count=5)
    _record("HISTORY", 5000, count=300)

    stats = _stats()

    assert stats["distribution"] == {"excellent": 150, "good": 30, "acceptable": 15, "slow": 5}
    assert stats["sla_100ms"] == pytest.approx(0)
    assert stats["sla_150ms"] == pytest.approx(75)
    assert stats["sla_200ms"] == pytest.approx(75)


def test_rows_written_under_the_old_options_tags_are_options_orders(latency):
    _record("OPTIONSORDER", 80, count=2)
    _record("OPTIONS", 120, count=2)
    _record("OPTIONSMULTIORDER", 200, count=1)

    stats = _stats()

    rows = {row["type"]: row for row in stats["endpoints"]}
    assert stats["total_orders"] == 5
    assert rows["OPTIONS"]["total_orders"] == 4
    assert rows["OPTIONS"]["avg_total"] == pytest.approx(100)
    assert rows["OPTIONS"]["label"] == "Options order"
    assert rows["OPTIONS_MULTI"]["total_orders"] == 1
    assert "OPTIONSORDER" not in rows


def test_a_record_in_no_group_is_other_and_other_is_listed_only_when_there_is_one(latency):
    _record("PLACE", 50)
    assert "other" not in _counts(_stats())

    _record("SOMETHING_NEW", 70, count=2)
    _record(None, 90)

    stats = _stats()
    assert _counts(stats)["other"] == 3 and _counts(stats)["all"] == 4

    other = _stats("other")
    assert other["total_orders"] == 3
    assert [row["label"] for row in other["endpoints"]] == ["SOMETHING_NEW", "Unknown"]
    assert _stats("all")["total_orders"] == 4


def test_each_group_has_its_own_cached_figures(latency):
    """One shared cache entry answered every group with the first one asked for."""
    _record("PLACE", 60, count=3)
    _record("HISTORY", 1200, count=7)
    latency_db._stats_cache.clear()

    first = OrderLatency.get_latency_stats("orders")
    second = OrderLatency.get_latency_stats("market_data")

    assert first["total_orders"] == 3 and second["total_orders"] == 7
    assert OrderLatency.get_latency_stats("orders") is first, "a group's figures are cached"


def test_percentiles_cover_the_recent_window_and_counts_cover_everything(latency):
    _record("PLACE", 50, count=10)
    _record("PLACE", 9000, count=1, age_days=latency_db.PERCENTILE_WINDOW_DAYS + 5)

    stats = _stats()

    assert stats["total_orders"] == 11
    assert stats["p99_total"] == pytest.approx(50)
    assert stats["percentile_window_days"] == latency_db.PERCENTILE_WINDOW_DAYS


def test_a_group_says_how_long_its_records_are_kept(latency):
    assert _stats("orders")["retention_days"] is None, "orders are kept forever"
    assert _stats("market_data")["retention_days"] == groups.RETENTION_DAYS
    assert _stats("all")["retention_days"] == groups.RETENTION_DAYS


def test_a_name_that_is_not_a_group_gets_the_orders(latency):
    _record("PLACE", 60)

    assert OrderLatency.get_latency_stats("nonsense")["group"] == "orders"


# --- the recent records ------------------------------------------------------


def test_the_recent_list_of_a_group_is_not_pushed_out_by_other_calls(latency):
    _record("PLACE", 60, count=2, age_days=1)
    _record("HISTORY", 1000, count=150)

    newest = OrderLatency.get_recent_logs(limit=100)
    orders = OrderLatency.get_recent_logs(limit=100, group="orders")

    assert {log.order_type for log in newest} == {"HISTORY"}
    assert [log.order_type for log in orders] == ["PLACE", "PLACE"]
    assert len(OrderLatency.get_recent_logs(limit=None, group="all")) == 152


# --- what is kept ------------------------------------------------------------


def test_old_data_records_go_and_every_kind_of_order_stays(latency):
    old = groups.RETENTION_DAYS + 1
    _record("HISTORY", 1000, count=4, age_days=old)
    _record("GTT_ORDERBOOK", 20, count=1, age_days=old)
    _record("HISTORY", 1000, count=2)
    for tag in (
        "PLACE",
        "OPTIONS",
        "OPTIONS_MULTI",
        "OPTIONSORDER",
        "OPTIONSMULTIORDER",
        "GTT_PLACE",
    ):
        _record(tag, 80, age_days=old)

    deleted = latency_db.purge_old_data_logs()

    assert deleted == 5
    left = sorted(row[0] for row in latency_session.query(OrderLatency.order_type).all())
    assert left == sorted(
        [
            "HISTORY",
            "HISTORY",
            "PLACE",
            "OPTIONS",
            "OPTIONS_MULTI",
            "OPTIONSORDER",
            "OPTIONSMULTIORDER",
            "GTT_PLACE",
        ]
    )


# --- the routes the page calls -----------------------------------------------


@pytest.fixture
def client(latency, monkeypatch):
    import blueprints.latency as latency_routes
    import utils.session as session_module

    monkeypatch.setattr(session_module, "is_session_valid", lambda: True)
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(latency_routes.latency_bp)
    with app.test_client() as test_client:
        yield test_client


def test_the_figures_route_answers_for_orders_unless_told_otherwise(client):
    _record("PLACE", 60, count=3)
    _record("HISTORY", 1200, count=9)

    default = client.get("/latency/api/stats").get_json()
    data = client.get("/latency/api/stats?group=market_data").get_json()

    assert default["group"] == "orders" and default["total_orders"] == 3
    assert data["group"] == "market_data" and data["total_orders"] == 9
    assert [item["key"] for item in default["groups"]][0] == "orders"
    assert "broker_histograms" not in default


def test_a_group_that_does_not_exist_is_refused_in_plain_words(client):
    for path in ("/latency/api/stats", "/latency/api/logs", "/latency/export"):
        response = client.get(f"{path}?group=nonsense")

        assert response.status_code == 400, path
        message = response.get_json()["error"]
        assert "Orders" in message and "Market data" in message
        assert "nonsense" not in message and "400" not in message


def test_the_records_route_names_each_endpoint_and_its_group(client):
    _record("OPTIONSORDER", 80)
    _record("HISTORY", 1200, count=120)

    orders = client.get("/latency/api/logs").get_json()
    data = client.get("/latency/api/logs?group=market_data&limit=5").get_json()

    assert len(orders) == 1
    assert orders[0]["order_type"] == "OPTIONSORDER"
    assert orders[0]["endpoint"] == "Options order" and orders[0]["group"] == "orders"
    assert len(data) == 5 and {row["endpoint"] for row in data} == {"History"}
    assert client.get("/latency/api/logs?limit=many").status_code == 400


def test_the_export_holds_the_group_on_screen_or_everything(client):
    _record("PLACE", 60, count=2)
    _record("HISTORY", 1200, count=3)

    def exported(query=""):
        response = client.get(f"/latency/export{query}")
        rows = list(csv.reader(io.StringIO(response.get_data(as_text=True))))
        return response.headers["Content-Disposition"], rows[1:]

    name, rows = exported()
    assert "latency_logs.csv" in name and len(rows) == 5

    name, rows = exported("?group=orders")
    assert "latency_orders.csv" in name and len(rows) == 2
