"""The /strategy lifecycle routes: the ones that move money.

The engine is mocked throughout. What is asserted here is the layer above it:
what the API refuses, what status code it refuses with, what it records, and
that a route which is not yours is invisible rather than forbidden.

Shares the isolated-store fixtures from test_strategy_module_api.py's approach
so a failing test cannot leave rows behind for the next one.
"""

import sys
from datetime import datetime, time
from pathlib import Path
from unittest.mock import patch

import pytest
import pytz
from flask import Flask

sys.path.insert(0, str(Path(__file__).parents[1]))

from blueprints import strategy_module  # noqa: E402
from database import strategy_module_db as store  # noqa: E402
from database.engine_factory import create_db_engine  # noqa: E402
from limiter import limiter  # noqa: E402
from services.strategy_module.engine import StartResult  # noqa: E402

USER = "lifecycle-tester"
OTHER = "somebody-else"


@pytest.fixture(scope="session", autouse=True)
def isolated_store(tmp_path_factory):
    path = tmp_path_factory.mktemp("strategy-lifecycle") / "lifecycle-test.db"
    engine = create_db_engine(f"sqlite:///{path.as_posix()}")
    store.db_session.remove()
    store.db_session.configure(bind=engine)
    store.engine = engine
    store.Base.metadata.create_all(bind=engine)
    yield engine
    store.db_session.remove()
    engine.dispose()


@pytest.fixture(autouse=True)
def empty_tables(isolated_store):
    store.db_session.remove()
    with isolated_store.begin() as connection:
        for table in reversed(store.Base.metadata.sorted_tables):
            connection.execute(table.delete())
    yield
    store.db_session.remove()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(limiter, "enabled", False)
    application = Flask(__name__)
    application.config.update(TESTING=True, SECRET_KEY="k", PROPAGATE_EXCEPTIONS=True)
    application.register_blueprint(strategy_module.strategy_module_bp)
    test_client = application.test_client()
    with test_client.session_transaction() as flask_session:
        flask_session["logged_in"] = True
        flask_session["user"] = USER
        flask_session["login_time"] = datetime.now(pytz.timezone("Asia/Kolkata")).isoformat()
    return test_client


def _make(user=USER, name="Lifecycle", running_run_id=None):
    created, error = store.create_strategy(
        user,
        {
            "name": name,
            "underlying": "NIFTY",
            "underlying_exchange": "NSE_INDEX",
            "universe_tab": "weekly_monthly",
            "strategy_type": "intraday",
            "entry_time": time(9, 20),
            "exit_time": time(15, 10),
            # A complete leg. The store does no validation, but PATCH
            # re-validates the whole merged configuration, so a fixture that
            # wrote an incomplete one here would make every edit a 400.
            "legs": [
                {
                    "id": 1,
                    "segment": "options",
                    "position": "S",
                    "lots": 1,
                    "option_type": "CE",
                    "strike_mode": "atm",
                    "atm_offset": "ATM",
                    "expiry": "weekly",
                    "trail": {"x": 0, "y": 0},
                }
            ],
        },
    )
    assert error is None, error
    if running_run_id is not None:
        store.set_strategy_status(created["id"], "running", running_run_id)
    return created["id"]


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------


def test_start_requires_a_mode_and_never_defaults_one(client):
    # Defaulting would mean a caller that forgot the field placing real orders
    # on a strategy the operator believed was on paper.
    sid = _make()

    assert client.post(f"/strategy/api/strategies/{sid}/start", json={}).status_code == 400
    assert (
        client.post(f"/strategy/api/strategies/{sid}/start", json={"mode": "real"}).status_code
        == 400
    )


def test_start_hands_the_mode_through_and_returns_the_run(client):
    sid = _make()

    with patch(
        "services.strategy_module.engine.start_run",
        return_value=StartResult(ok=True, run_id=42, legs=[{"leg_id": 1, "ok": True}]),
    ) as start:
        response = client.post(f"/strategy/api/strategies/{sid}/start", json={"mode": "sandbox"})

    assert response.status_code == 200
    assert response.get_json()["run_id"] == 42
    assert start.call_args[0][2] == "sandbox"
    assert start.call_args[1]["trigger_source"] == "manual"


def test_starting_something_already_running_is_a_conflict_not_a_bad_request(client):
    # The UI shows these differently: a 409 means "somebody beat you to it",
    # a 400 means "your configuration is wrong".
    sid = _make()

    with patch(
        "services.strategy_module.engine.start_run",
        return_value=StartResult(ok=False, error="This strategy is already running"),
    ):
        response = client.post(f"/strategy/api/strategies/{sid}/start", json={"mode": "sandbox"})

    assert response.status_code == 409


def test_a_refused_start_reports_which_leg_failed(client):
    sid = _make()

    with patch(
        "services.strategy_module.engine.start_run",
        return_value=StartResult(
            ok=False,
            error="Leg 1: No option contract found",
            legs=[{"leg_id": 1, "ok": False, "error": "Leg 1: No option contract found"}],
        ),
    ):
        response = client.post(f"/strategy/api/strategies/{sid}/start", json={"mode": "sandbox"})

    assert response.status_code == 400
    assert "No option contract found" in response.get_json()["message"]


# ---------------------------------------------------------------------------
# Stop and close
# ---------------------------------------------------------------------------


def test_stopping_a_strategy_that_is_not_running_is_a_conflict(client):
    sid = _make()

    response = client.post(f"/strategy/api/strategies/{sid}/stop", json={})

    assert response.status_code == 409
    assert "not running" in response.get_json()["message"]


def test_stop_exits_the_current_run(client):
    sid = _make(running_run_id=7)

    with patch(
        "services.strategy_module.engine.stop_run", return_value={"ok": True, "exits": []}
    ) as stop:
        response = client.post(f"/strategy/api/strategies/{sid}/stop", json={})

    assert response.status_code == 200
    assert stop.call_args[0][0] == 7
    assert stop.call_args[1]["reason"] == "manual"


@pytest.mark.parametrize("route", ["stop", "close_all"])
def test_stop_endpoints_report_accepted_but_still_pending_exits(client, route):
    sid = _make(running_run_id=7)

    with patch(
        "services.strategy_module.engine.stop_run",
        return_value={"ok": True, "stop_pending": True, "exits": [{"ok": True}]},
    ):
        response = client.post(f"/strategy/api/strategies/{sid}/{route}", json={})

    assert response.status_code == 200
    body = response.get_json()
    assert body["stop_pending"] is True
    assert body["exits"] == [{"ok": True}]


@pytest.mark.parametrize("route", ["stop", "close_all"])
def test_stop_endpoint_failures_preserve_pending_and_per_exit_detail(client, route):
    sid = _make(running_run_id=7)
    exits = [{"leg_id": 1, "ok": False, "error": "No API key"}]

    with patch(
        "services.strategy_module.engine.stop_run",
        return_value={
            "ok": False,
            "stop_pending": True,
            "error": "No API key is configured for this user",
            "exits": exits,
        },
    ):
        response = client.post(f"/strategy/api/strategies/{sid}/{route}", json={})

    assert response.status_code == 409
    body = response.get_json()
    assert body["stop_pending"] is True
    assert body["exits"] == exits


def test_close_all_records_the_operator_intent_separately_from_the_stop(client):
    # This event is recorded before the broker exits settle, so it must preserve
    # operator intent without claiming that the account is already flat.
    sid = _make(running_run_id=7)

    with patch("services.strategy_module.engine.stop_run", return_value={"ok": True, "exits": []}):
        response = client.post(f"/strategy/api/strategies/{sid}/close_all", json={})

    assert response.status_code == 200
    events = store.list_events(sid)
    close_request = next(event for event in events if event["kind"] == "close_all_manual")
    assert close_request["message"] == "Operator requested closure of all held legs"


def test_closing_one_leg_reports_whether_the_run_is_now_flat(client):
    sid = _make(running_run_id=7)

    with patch(
        "services.strategy_module.engine.close_leg",
        return_value={"ok": True, "exits": [], "run_stopped": False},
    ) as close:
        response = client.post(f"/strategy/api/strategies/{sid}/legs/1/close", json={})

    assert response.status_code == 200
    body = response.get_json()
    assert body["run_stopped"] is False
    assert body["leg_id"] == "1"
    assert close.call_args[0][1] == "1"


def test_closing_a_leg_on_a_stopped_strategy_is_a_conflict(client):
    sid = _make()

    response = client.post(f"/strategy/api/strategies/{sid}/legs/1/close", json={})

    assert response.status_code == 409


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------


def test_the_kill_switch_flattens_an_active_run_not_just_the_webhook(client):
    # A lock that leaves a live position open is not a kill switch.
    sid = _make(running_run_id=7)

    with patch(
        "services.strategy_module.engine.stop_run", return_value={"ok": True, "exits": []}
    ) as stop:
        response = client.post(f"/strategy/api/strategies/{sid}/kill_switch", json={})

    assert response.status_code == 200
    body = response.get_json()
    assert body["webhook_locked"] is True
    assert body["run_stopped"] is True
    assert stop.call_count == 1
    assert store.get_strategy(sid, USER).webhook_locked is True


def test_the_kill_switch_does_not_report_stopped_while_exit_fills_are_pending(client):
    sid = _make(running_run_id=7)

    with patch(
        "services.strategy_module.engine.stop_run",
        return_value={"ok": True, "stop_pending": True, "exits": [{"ok": True}]},
    ):
        response = client.post(f"/strategy/api/strategies/{sid}/kill_switch", json={})

    assert response.status_code == 200
    body = response.get_json()
    assert body["webhook_locked"] is True
    assert body["run_stopped"] is False
    assert body["stop_pending"] is True
    assert "closed" not in body["message"].lower()


def test_the_kill_switch_locks_even_when_there_is_nothing_to_flatten(client):
    sid = _make()

    with patch("services.strategy_module.engine.stop_run") as stop:
        response = client.post(f"/strategy/api/strategies/{sid}/kill_switch", json={})

    assert response.status_code == 200
    assert response.get_json()["run_stopped"] is False
    assert stop.call_count == 0
    assert store.get_strategy(sid, USER).webhook_locked is True


def test_the_kill_switch_still_locks_when_flattening_fails(client):
    # If the broker is unreachable the position stays open, but the webhook must
    # still be shut so nothing new can be added on top of it.
    sid = _make(running_run_id=7)

    with patch(
        "services.strategy_module.engine.stop_run",
        return_value={"ok": False, "stop_pending": True, "error": "Broker unreachable"},
    ):
        response = client.post(f"/strategy/api/strategies/{sid}/kill_switch", json={})

    assert response.status_code == 200
    assert response.get_json()["run_stopped"] is False
    assert response.get_json()["stop_pending"] is True
    assert "exit fills pending" not in response.get_json()["message"].lower()
    events = store.list_events(sid)
    assert "exit fills pending" not in events[-1]["message"].lower()
    assert store.get_strategy(sid, USER).webhook_locked is True


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["start", "stop", "close_all", "kill_switch", "unlock_webhook", "legs/1/close"],
)
def test_somebody_elses_strategy_is_invisible_on_every_lifecycle_route(client, path):
    # 404, never 403: a 403 confirms the id is real and lets the space be probed.
    sid = _make(user=OTHER, name="Not yours", running_run_id=7)

    response = client.post(f"/strategy/api/strategies/{sid}/{path}", json={"mode": "sandbox"})

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Scheduler sync
#
# The job store is in memory so the database stays the single source of truth,
# which only holds if every write syncs. Without these calls the scheduler
# reflects the configuration as it stood at boot: a schedule saved today would
# not fire until the next restart, an edited start time would keep firing at
# the old one, and a deleted strategy would leave its jobs behind.
# ---------------------------------------------------------------------------


def _payload(**overrides):
    body = {
        "name": "Scheduled",
        "underlying": "NIFTY",
        "underlying_exchange": "NSE_INDEX",
        "strategy_type": "intraday",
        "entry_time": "09:20",
        "exit_time": "15:10",
        "legs": [
            {
                "segment": "options",
                "position": "S",
                "lots": 1,
                "option_type": "CE",
                "strike_mode": "atm",
                "atm_offset": "ATM",
                "expiry": "weekly",
            }
        ],
    }
    body.update(overrides)
    return body


def test_creating_a_strategy_installs_its_jobs_now_not_at_the_next_restart(client):
    with patch("services.strategy_module.scheduler.sync_strategy_jobs") as sync:
        response = client.post("/strategy/api/strategies", json=_payload())

    assert response.status_code in (200, 201)
    assert sync.call_count == 1


def test_editing_a_strategy_resyncs_its_jobs(client):
    sid = _make(name="Editable")

    with patch("services.strategy_module.scheduler.sync_strategy_jobs") as sync:
        response = client.patch(f"/strategy/api/strategies/{sid}", json={"name": "Renamed"})

    assert response.status_code == 200
    assert sync.call_count == 1


def test_deleting_a_strategy_removes_its_jobs(client):
    sid = _make(name="Deletable")

    with patch("services.strategy_module.scheduler.remove_strategy_jobs") as remove:
        response = client.delete(f"/strategy/api/strategies/{sid}")

    assert response.status_code == 200
    assert remove.call_count == 1


def test_a_scheduler_that_is_not_running_does_not_fail_the_request(client):
    # The configuration is saved either way, and the next boot re-derives every
    # job from it. Losing the save because a background scheduler was down
    # would be the worse failure.
    sid = _make(name="Resilient")

    with patch(
        "services.strategy_module.scheduler.sync_strategy_jobs",
        side_effect=RuntimeError("scheduler down"),
    ):
        response = client.patch(f"/strategy/api/strategies/{sid}", json={"name": "Still saved"})

    assert response.status_code == 200
    assert store.get_strategy(sid, USER).name == "Still saved"


# ---------------------------------------------------------------------------
# Broker-backed views
#
# These read the broker rather than the stored order rows. The stored rows
# record what was placed; the broker knows what happened to it, and for money
# that difference is the point.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "fn"),
    [
        ("orderbook", "strategy_orderbook"),
        ("tradebook", "strategy_tradebook"),
        ("positions", "strategy_positions"),
    ],
)
def test_a_broker_backed_view_passes_the_brokers_answer_through(client, path, fn):
    sid = _make(name=f"Book {path}")
    payload = {"status": "success", "data": {"orders": [{"orderid": "1"}]}}

    with (
        patch(f"services.strategy_module.views.{fn}", return_value=payload) as view,
        patch("database.auth_db.get_api_key_for_tradingview", return_value="k"),
    ):
        response = client.get(f"/strategy/api/strategies/{sid}/{path}")

    assert response.status_code == 200
    assert response.get_json() == payload
    assert view.call_args[0][0] == sid


def test_a_broker_failure_is_reported_as_an_upstream_error(client):
    # Passed through rather than reshaped: the broker's own message is more
    # useful than anything this layer could invent.
    sid = _make(name="Book fail")

    with (
        patch(
            "services.strategy_module.views.strategy_orderbook",
            return_value={"status": "error", "message": "Broker unreachable"},
        ),
        patch("database.auth_db.get_api_key_for_tradingview", return_value="k"),
    ):
        response = client.get(f"/strategy/api/strategies/{sid}/orderbook")

    assert response.status_code == 502
    assert "Broker unreachable" in response.get_json()["message"]


def test_a_broker_backed_view_needs_an_api_key(client):
    sid = _make(name="Book nokey")

    with (
        patch("database.auth_db.get_api_key_for_tradingview", return_value=None),
        patch("services.strategy_module.views.strategy_orderbook") as view,
    ):
        response = client.get(f"/strategy/api/strategies/{sid}/orderbook")

    assert response.status_code == 400
    assert view.call_count == 0


@pytest.mark.parametrize("path", ["orderbook", "tradebook", "positions"])
def test_somebody_elses_book_is_invisible(client, path):
    sid = _make(user=OTHER, name=f"Not yours {path}")

    response = client.get(f"/strategy/api/strategies/{sid}/{path}")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Public webhook route
#
# Unauthenticated and CSRF exempt by design: the URL token is the credential.
# Every decision lives in the pipeline; this route only reads the request and
# turns the outcome into a response.
# ---------------------------------------------------------------------------


def _webhook_client():
    """A client with no session at all: the webhook must not need one."""
    application = Flask(__name__)
    application.config.update(TESTING=True, SECRET_KEY="k", PROPAGATE_EXCEPTIONS=True)
    application.register_blueprint(strategy_module.strategy_module_bp)
    return application.test_client()


def test_the_webhook_needs_no_session(monkeypatch):
    monkeypatch.setattr(limiter, "enabled", False)
    client = _webhook_client()

    with patch("services.strategy_module.webhook.handle_webhook") as handle:
        handle.return_value.as_response.return_value = ({"status": "success"}, 200)
        response = client.post("/strategy/webhook/oaws_token", json={"action": "stop"})

    assert response.status_code == 200
    assert handle.call_count == 1


def test_an_unknown_token_answers_json_rather_than_reaching_the_404_handler(monkeypatch):
    # An unauthenticated 404 feeds Error404Tracker and counts toward an IP ban.
    # A scanner walking the token space must not be able to get the owner's own
    # address banned, so this is answered by the view, not by aborting.
    monkeypatch.setattr(limiter, "enabled", False)
    client = _webhook_client()

    with patch("services.strategy_module.webhook.handle_webhook") as handle:
        handle.return_value.as_response.return_value = (
            {"status": "error", "result": "rejected_token", "message": "Not found"},
            404,
        )
        response = client.post("/strategy/webhook/oaws_nope", json={"action": "stop"})

    assert response.status_code == 404
    assert response.is_json
    assert response.get_json()["result"] == "rejected_token"


def test_the_raw_body_is_handed_over_rather_than_a_parsed_dict(monkeypatch):
    # The pipeline enforces its own size cap and accepts several shapes, so it
    # needs what actually arrived rather than Flask's interpretation of it.
    monkeypatch.setattr(limiter, "enabled", False)
    client = _webhook_client()

    with patch("services.strategy_module.webhook.handle_webhook") as handle:
        handle.return_value.as_response.return_value = ({"status": "success"}, 200)
        client.post(
            "/strategy/webhook/oaws_token",
            data=b'{"action":"start","mode":"sandbox"}',
            content_type="application/json",
        )

    body = handle.call_args[0][1]
    assert isinstance(body, bytes)
    assert b"sandbox" in body


def test_the_caller_address_and_agent_are_passed_for_the_audit_row(monkeypatch):
    monkeypatch.setattr(limiter, "enabled", False)
    client = _webhook_client()

    with patch("services.strategy_module.webhook.handle_webhook") as handle:
        handle.return_value.as_response.return_value = ({"status": "success"}, 200)
        client.post(
            "/strategy/webhook/oaws_token",
            json={"action": "stop"},
            headers={"User-Agent": "TradingView"},
        )

    assert handle.call_args[1]["user_agent"] == "TradingView"
    assert handle.call_args[1]["ip"] is not None
