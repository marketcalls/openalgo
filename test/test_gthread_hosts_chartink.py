"""Chartink: orders without HTTP to itself under gthread, and square-offs after a restart.

hosts-13. The order queue posted every order to this server's own /api/v1
endpoints. Under the gthread worker that request needs a free thread from the
pool its own server is serving; with the pool held by long lived connections it
waited, the post gave up after 30 seconds and the order was logged as failed,
and the server could still execute it once a thread freed. Under gthread the
queue now calls the order services directly, after the same schema validation.
Under eventlet and on the development server it posts exactly as before.

hosts-14. A square-off job was only ever added when a strategy was created,
and the scheduler keeps its jobs in memory, so after any restart no intraday
Chartink strategy was squared off at its square-off time. Under the gthread
worker they are now put back once after startup, for every intraday strategy
that is turned on. A strategy that is off gets none, because a square-off
closes the whole net position in each mapped symbol. Under eventlet and on the
development server nothing is restored, exactly as before (review
eventlet-neutrality-01 and hosts-messaging-02).
"""

import threading
import time
from types import SimpleNamespace

import pytest
from flask import Flask

import blueprints.chartink as chartink
import restx_api  # noqa: F401 - imported first, as the app does, to settle its import cycle
import services.place_order_service as place_order_service
import services.place_smart_order_service as place_smart_order_service
import utils.session

ORDER = {
    "apikey": "key",
    "strategy": "chartink_scan",
    "symbol": "SBIN",
    "exchange": "NSE",
    "action": "BUY",
    "product": "MIS",
    "pricetype": "MARKET",
    "quantity": "10",
}
SMART = {
    "apikey": "key",
    "strategy": "chartink_scan",
    "symbol": "INFY",
    "exchange": "NSE",
    "action": "SELL",
    "product": "MIS",
    "pricetype": "MARKET",
    "quantity": "0",
    "position_size": "0",
    "price": "0",
    "trigger_price": "0",
    "disclosed_quantity": "0",
}


@pytest.fixture
def recorded(monkeypatch):
    calls = {"post": [], "place": [], "smart": []}

    def post(url, json=None, timeout=None):
        calls["post"].append((url, json))
        return SimpleNamespace(ok=True, text="ok")

    def place(order_data, api_key=None):
        calls["place"].append((order_data, api_key))
        return True, {"status": "success", "orderid": "1"}, 200

    def smart(order_data, api_key=None):
        calls["smart"].append((order_data, api_key))
        return True, {"status": "success", "orderid": "2"}, 200

    monkeypatch.setattr(chartink.requests, "post", post)
    monkeypatch.setattr(place_order_service, "place_order", place)
    monkeypatch.setattr(place_smart_order_service, "place_smart_order", smart)
    return calls


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def test_under_gthread_orders_reach_the_services_without_http(recorded, monkeypatch):
    monkeypatch.setattr(chartink.runtime, "gthread_active", lambda: True)
    released = []
    monkeypatch.setattr(chartink, "remove_all_scoped_sessions", lambda: released.append(1))

    chartink.queue_order("placeorder", dict(ORDER))
    chartink.queue_order("placesmartorder", dict(SMART))

    assert _wait_for(lambda: recorded["place"] and recorded["smart"])
    assert recorded["post"] == [], "an order was posted back to this server over HTTP"

    order_data, api_key = recorded["place"][0]
    assert api_key == "key"
    assert order_data["quantity"] == 10.0  # validated by the order schema
    smart_data, smart_key = recorded["smart"][0]
    assert smart_key == "key"
    assert "apikey" not in smart_data
    assert smart_data["position_size"] == 0.0
    assert len(released) >= 2, "the processor thread kept its database sessions"


def test_outside_gthread_orders_are_posted_exactly_as_before(recorded, monkeypatch):
    monkeypatch.setattr(chartink.runtime, "gthread_active", lambda: False)

    chartink.queue_order("placeorder", dict(ORDER))
    chartink.queue_order("placesmartorder", dict(SMART))

    assert _wait_for(lambda: len(recorded["post"]) == 2)
    urls = sorted(url for url, _ in recorded["post"])
    assert urls == [
        f"{chartink.BASE_URL}/api/v1/placeorder",
        f"{chartink.BASE_URL}/api/v1/placesmartorder",
    ]
    assert recorded["place"] == [] and recorded["smart"] == []


def test_an_order_the_schema_refuses_is_reported_not_placed(recorded, monkeypatch):
    monkeypatch.setattr(chartink, "remove_all_scoped_sessions", lambda: None)
    bad = dict(ORDER, exchange="MOON")

    ok, detail = chartink._place_in_process("placeorder", bad)

    assert ok is False
    assert "exchange" in detail
    assert recorded["place"] == []


class FakeScheduler:
    def __init__(self):
        self.jobs = {}
        self.lock = threading.Lock()

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def remove_job(self, job_id):
        self.jobs.pop(job_id, None)

    def add_job(self, func, trigger=None, id=None, replace_existing=False, **fields):
        with self.lock:
            self.jobs[id] = SimpleNamespace(func=func, trigger=trigger, **fields)


def _strategy(sid, intraday=True, squareoff="15:12", active=True):
    return SimpleNamespace(
        id=sid,
        is_intraday=intraday,
        squareoff_time=squareoff if intraday else None,
        is_active=active,
    )


@pytest.fixture
def restore(monkeypatch):
    monkeypatch.setattr(chartink.runtime, "gthread_active", lambda: True)
    scheduler = FakeScheduler()
    strategies = [_strategy(1), _strategy(2, squareoff="14:05", active=False), _strategy(3, False)]
    reads = []

    class Query:
        @staticmethod
        def all():
            reads.append(1)
            time.sleep(0.05)
            return strategies

    monkeypatch.setattr(chartink, "scheduler", scheduler)
    monkeypatch.setattr(chartink, "ChartinkStrategy", SimpleNamespace(query=Query))
    monkeypatch.setattr(chartink, "_squareoffs_restored", False)
    return scheduler, reads


def test_restore_puts_back_one_squareoff_per_intraday_strategy(restore):
    scheduler, reads = restore
    barrier = threading.Barrier(2)
    results = []

    def run():
        barrier.wait()
        results.append(chartink.restore_squareoff_jobs())

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert chartink.restore_squareoff_jobs() is True

    assert results == [True, True]
    assert len(reads) == 1, "the strategies were read by more than one restore"
    # Strategy 2 is turned off: a restart never revives its square-off.
    assert sorted(scheduler.jobs) == ["squareoff_1"]
    job = scheduler.jobs["squareoff_1"]
    assert (job.hour, job.minute, job.args) == (15, 12, [1])


def test_turning_a_strategy_back_on_restores_its_squareoff(restore):
    scheduler, _ = restore
    chartink.restore_squareoff_jobs()
    assert "squareoff_2" not in scheduler.jobs

    chartink._restore_squareoff_on_activation(_strategy(2, squareoff="14:05", active=True))

    job = scheduler.jobs["squareoff_2"]
    assert (job.hour, job.minute, job.args) == (14, 5, [2])


def test_nothing_is_restored_outside_gthread(restore, monkeypatch):
    scheduler, reads = restore
    monkeypatch.setattr(chartink.runtime, "gthread_active", lambda: False)

    assert chartink.restore_squareoff_jobs() is True
    chartink._restore_squareoff_on_activation(_strategy(1))

    assert scheduler.jobs == {} and reads == []


def test_a_job_created_since_startup_is_left_alone(restore):
    scheduler, _ = restore
    existing = SimpleNamespace(marker="created")
    scheduler.jobs["squareoff_1"] = existing

    chartink.restore_squareoff_jobs()

    assert scheduler.jobs["squareoff_1"] is existing


def test_a_database_that_is_not_ready_is_retried(restore, monkeypatch):
    scheduler, _ = restore
    rolled_back = []

    class Broken:
        @staticmethod
        def all():
            raise RuntimeError("no such table")

    monkeypatch.setattr(chartink, "ChartinkStrategy", SimpleNamespace(query=Broken))
    monkeypatch.setattr(chartink.db_session, "rollback", lambda: rolled_back.append(1))

    assert chartink.restore_squareoff_jobs() is False
    assert chartink._squareoffs_restored is False
    assert rolled_back == [1]

    # The scheduled attempt books the next one.
    chartink._restore_squareoffs_on_schedule.__wrapped__(attempt=3)
    retry = scheduler.jobs[chartink._SQUAREOFF_RESTORE_JOB_ID]
    assert retry.args == [4]


def test_the_first_chartink_request_restores_when_the_scheduled_attempt_has_not(
    restore, monkeypatch
):
    scheduler, _ = restore
    monkeypatch.setattr(utils.session, "is_session_valid", lambda: False)
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(chartink.chartink_bp)

    app.test_client().get("/chartink/api/strategies", headers={"Accept": "application/json"})

    assert chartink._squareoffs_restored is True
    assert "squareoff_1" in scheduler.jobs


def test_startup_books_no_restore_outside_gthread():
    """This process is the development server: nothing is booked at import."""
    assert not chartink.runtime.gthread_active()
    assert chartink.scheduler.get_job(chartink._SQUAREOFF_RESTORE_JOB_ID) is None
