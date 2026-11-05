"""A crypto strategy on /python can run 24/7 (issue #1557).

Before: the schedule forced a stop time, so a 00:00 - 23:59 crypto strategy was
stopped every night, and 00:00 - 00:00 gave a window of no length that refused
the Start button all day. A crypto strategy may now have no stop time at all,
and the exchange list follows the broker's own plugin.json.

Run inside the project root:
    uv run pytest test/test_python_strategy_crypto_24x7.py -v
"""

import os
import sys
from datetime import datetime
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytz  # noqa: E402

IST = pytz.timezone("Asia/Kolkata")


@pytest.fixture()
def ps():
    from blueprints import python_strategy as module

    module.STRATEGY_CONFIGS.clear()
    module.RUNNING_STRATEGIES.clear()
    yield module
    module.STRATEGY_CONFIGS.clear()
    module.RUNNING_STRATEGIES.clear()


class FakeScheduler:
    """Records the jobs schedule_strategy creates, without running any."""

    def __init__(self):
        self.jobs = {}

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def remove_job(self, job_id):
        self.jobs.pop(job_id, None)

    def add_job(self, func=None, trigger=None, id=None, replace_existing=False):
        self.jobs[id] = trigger


def _at(ps_module, hour, minute, second=0, microsecond=0):
    fixed = IST.localize(datetime(2026, 4, 12, hour, minute, second, microsecond))
    patcher = patch("blueprints.python_strategy.datetime")
    mock_dt = patcher.start()
    mock_dt.now.return_value = fixed
    mock_dt.combine = datetime.combine
    mock_dt.min = datetime.min
    return patcher


def test_no_stop_time_creates_no_stop_job(ps, monkeypatch):
    scheduler = FakeScheduler()
    monkeypatch.setattr(ps, "SCHEDULER", scheduler)
    monkeypatch.setattr(ps, "save_configs", lambda: None)
    ps.STRATEGY_CONFIGS["c"] = {"exchange": "CRYPTO", "user_id": "u"}

    ps.schedule_strategy("c", "00:00", None, ["mon", "tue", "wed", "thu", "fri", "sat", "sun"])

    assert "start_c" in scheduler.jobs
    assert "stop_c" not in scheduler.jobs
    assert ps.STRATEGY_CONFIGS["c"]["schedule_stop"] is None


def test_crypto_without_stop_is_inside_its_window_in_the_last_second(ps):
    ps.STRATEGY_CONFIGS["c"] = {"exchange": "CRYPTO", "schedule_start": "00:00"}
    for hour, minute, second, micro in ((0, 0, 0, 0), (12, 0, 0, 0), (23, 59, 59, 500_000)):
        patcher = _at(ps, hour, minute, second, micro)
        try:
            assert ps.is_within_schedule_time("c") is True, (hour, minute, second)
        finally:
            patcher.stop()


def test_status_reads_24x7_without_a_stop_time(ps):
    every_day = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    patcher = _at(ps, 3, 0)
    try:
        status, message = ps.get_schedule_status(
            {
                "exchange": "CRYPTO",
                "schedule_start": "00:00",
                "schedule_stop": None,
                "schedule_days": every_day,
            }
        )
    finally:
        patcher.stop()
    assert status == "scheduled"
    assert message == "Runs 24/7"
    assert "None" not in message


def _schedule_request(ps, payload, config):
    from flask import Flask

    ps.STRATEGY_CONFIGS["c"] = {"user_id": "u", "is_running": False, **config}
    app = Flask(__name__)
    app.secret_key = "test"
    with app.test_request_context("/python/schedule/c", method="POST", json=payload):
        from flask import session

        session["user"] = "u"
        response = ps.schedule_strategy_route.__wrapped__("c")
    body, code = response if isinstance(response, tuple) else (response, 200)
    return body.get_json(), code


def test_schedule_route_accepts_a_crypto_strategy_with_no_stop(ps, monkeypatch):
    scheduler = FakeScheduler()
    monkeypatch.setattr(ps, "SCHEDULER", scheduler)
    monkeypatch.setattr(ps, "save_configs", lambda: None)

    body, code = _schedule_request(
        ps,
        {"start_time": "00:00", "stop_time": "", "days": ["mon", "sun"], "exchange": "CRYPTO"},
        {"exchange": "CRYPTO"},
    )

    assert code == 200, body
    assert body["message"] == "[CRYPTO] Scheduled at 00:00 IST, runs 24/7"
    assert "stop_c" not in scheduler.jobs
    assert ps.STRATEGY_CONFIGS["c"]["schedule_stop"] is None


def test_schedule_route_refuses_equal_start_and_stop(ps, monkeypatch):
    scheduler = FakeScheduler()
    monkeypatch.setattr(ps, "SCHEDULER", scheduler)
    monkeypatch.setattr(ps, "save_configs", lambda: None)

    body, code = _schedule_request(
        ps,
        {"start_time": "00:00", "stop_time": "00:00", "days": ["mon"], "exchange": "CRYPTO"},
        {"exchange": "CRYPTO"},
    )

    assert code == 400
    assert "Run 24/7" in body["message"]
    assert scheduler.jobs == {}


INDIAN = ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX", "NCO"]


@pytest.mark.parametrize(
    ("capabilities", "expected", "default"),
    [
        ({"broker_type": "crypto", "supported_exchanges": ["CRYPTO"]}, ["CRYPTO"], "CRYPTO"),
        # A stock broker keeps every Indian exchange it was offered before,
        # even ones its plugin does not list, and loses only CRYPTO.
        ({"broker_type": "IN_stock", "supported_exchanges": ["NSE", "NFO"]}, INDIAN, "NSE"),
        # A plugin that says nothing leaves every exchange on offer, as before.
        (None, INDIAN + ["CRYPTO"], "NSE"),
    ],
)
def test_exchange_list_follows_the_broker_type(ps, capabilities, expected, default):
    from flask import Flask, session

    app = Flask(__name__)
    app.secret_key = "test"
    with (
        patch("utils.plugin_loader.get_broker_capabilities", return_value=capabilities),
        patch.object(ps, "get_all_market_timings", return_value=[]),
        app.test_request_context("/python/api/exchanges"),
    ):
        session["broker"] = "anybroker"
        body = ps.api_get_exchanges.__wrapped__().get_json()

    assert [item["value"] for item in body["exchanges"]] == expected
    assert body["default"] == default


def test_indian_schedule_with_equal_times_is_saved_as_before(ps, monkeypatch):
    """The equal-time refusal is for crypto only; NSE schedules are untouched."""
    scheduler = FakeScheduler()
    monkeypatch.setattr(ps, "SCHEDULER", scheduler)
    monkeypatch.setattr(ps, "save_configs", lambda: None)

    body, code = _schedule_request(
        ps,
        {"start_time": "09:15", "stop_time": "09:15", "days": ["mon"], "exchange": "NSE"},
        {"exchange": "NSE"},
    )

    assert code == 200, body
    assert {"start_c", "stop_c"} <= set(scheduler.jobs)


@pytest.mark.parametrize(
    ("exchange", "stored_stop", "has_stop_job"),
    [
        # Indian exchanges keep their 16:00 default exactly as before.
        ("NSE", "16:00", True),
        # Only a crypto upload with no stop time runs 24/7.
        ("CRYPTO", None, False),
    ],
)
def test_upload_without_a_stop_time(ps, monkeypatch, tmp_path, exchange, stored_stop, has_stop_job):
    import io

    from flask import Flask, session

    scheduler = FakeScheduler()
    monkeypatch.setattr(ps, "SCHEDULER", scheduler)
    monkeypatch.setattr(ps, "save_configs", lambda: None)
    monkeypatch.setattr(ps, "STRATEGIES_DIR", tmp_path)

    app = Flask(__name__)
    app.secret_key = "test"
    data = {
        "strategy_name": "bot",
        "exchange": exchange,
        "strategy_file": (io.BytesIO(b"print(1)"), "bot.py"),
    }
    with app.test_request_context(
        "/python/new", method="POST", data=data, content_type="multipart/form-data"
    ):
        session["user"] = "u"
        response = ps.new_strategy.__wrapped__()

    assert response.get_json()["status"] == "success"
    (strategy_id,) = ps.STRATEGY_CONFIGS
    assert ps.STRATEGY_CONFIGS[strategy_id]["schedule_stop"] == stored_stop
    assert (f"stop_{strategy_id}" in scheduler.jobs) is has_stop_job
