"""The external /api/v1/strategy surface: what it refuses, and with what code.

The engine is mocked throughout. What is asserted here is the layer above it:
that a start without a mode never reaches the order path, that live is refused
on a strategy that has not opted into it, that a strategy belonging to somebody
else is invisible rather than forbidden, and that no response anywhere carries a
webhook token.

Several tests assert the negative in its strongest form -- that the engine was
not called at all -- rather than only that the status code was right. A refusal
that still placed the order would satisfy the weaker assertion.

The store is redirected at a temporary SQLite file for the session, following
test_strategy_module_lifecycle_api.py, so a failing test cannot leave rows
behind for the next one or touch a real installation.
"""

import sys
from datetime import time
from pathlib import Path

import pytest
from flask import Flask
from flask_restx import Api

sys.path.insert(0, str(Path(__file__).parents[1]))

from database import strategy_module_db as store  # noqa: E402
from database.engine_factory import create_db_engine  # noqa: E402
from limiter import limiter  # noqa: E402
from restx_api import strategy as strategy_api  # noqa: E402
from services.strategy_module.engine import StartResult  # noqa: E402

USER = "restx-strategy-tester"
OTHER = "somebody-else"

API_KEY = "this-users-api-key"
OTHER_KEY = "another-users-api-key"

RUN_ID = 4242


def _verify_api_key(provided):
    """Stands in for database.auth_db.verify_api_key: key to username."""
    return {API_KEY: USER, OTHER_KEY: OTHER}.get(provided)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def isolated_store(tmp_path_factory):
    path = tmp_path_factory.mktemp("strategy-restx") / "restx-test.db"
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


class FakeEngine:
    """Records what it was asked to do, and answers however a test wants.

    Standing in for services.strategy_module.engine. Nothing in this suite is
    allowed to reach the real one: every method here would otherwise resolve
    symbols and place orders.
    """

    def __init__(self):
        self.calls = []
        self.start_result = StartResult(
            ok=True, run_id=RUN_ID, legs=[{"leg_id": 1, "ok": True, "error": None}]
        )
        self.stop_result = {
            "ok": True,
            "stop_pending": True,
            "exits": [{"leg_id": 1, "ok": True, "error": None}],
        }
        self.close_leg_result = {
            "ok": True,
            "exits": [{"leg_id": 1, "ok": True, "error": None}],
            "run_stopped": False,
        }

    def start_run(self, strategy_id, user_id, mode, trigger_source="manual", **_kwargs):
        self.calls.append(("start_run", strategy_id, user_id, mode, trigger_source))
        return self.start_result

    def stop_run(self, run_id, user_id, reason="manual"):
        self.calls.append(("stop_run", run_id, user_id, reason))
        return self.stop_result

    def close_leg(self, run_id, leg_id, user_id):
        self.calls.append(("close_leg", run_id, leg_id, user_id))
        return self.close_leg_result


@pytest.fixture
def engine():
    return FakeEngine()


@pytest.fixture
def client(monkeypatch, engine):
    monkeypatch.setattr(limiter, "enabled", False)
    monkeypatch.setattr(strategy_api, "verify_api_key", _verify_api_key)
    monkeypatch.setattr(strategy_api, "_engine", lambda: engine)

    app = Flask(__name__)
    app.config.update(TESTING=True, PROPAGATE_EXCEPTIONS=False)
    rest_api = Api(app)
    rest_api.add_namespace(strategy_api.api, path="/strategy")
    return app.test_client()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make(user=USER, name="Short Straddle", live_enabled=False, running=False):
    """Create a strategy and return ``(id, webhook_token)``."""
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
    sid = created["id"]

    # Order matters: the store refuses a live-flag change while running.
    if live_enabled:
        ok, message = store.set_live_enabled(sid, user, True)
        assert ok, message
    if running:
        assert store.set_strategy_status(sid, "running", RUN_ID)

    return sid, created["webhook_token"]


def post(client, path, **body):
    body.setdefault("apikey", API_KEY)
    return client.post(f"/strategy/{path}", json=body)


def _every_route(sid):
    """Every route with a body that should succeed on a running strategy."""
    return [
        ("list", {}),
        ("status", {"strategy_id": sid}),
        ("start", {"strategy_id": sid, "mode": "sandbox"}),
        ("stop", {"strategy_id": sid}),
        ("close_all", {"strategy_id": sid}),
        ("close_leg", {"strategy_id": sid, "leg_id": 1}),
        ("runs", {"strategy_id": sid}),
        ("orders", {"strategy_id": sid}),
        ("events", {"strategy_id": sid}),
    ]


# ---------------------------------------------------------------------------
# Start: mode is required and never defaulted
# ---------------------------------------------------------------------------


def test_start_without_a_mode_is_a_400_and_never_reaches_the_engine(client, engine):
    """The single most important assertion in this file.

    A caller that omits the field must be refused, not given a default. The
    default a hurried reader reaches for is the one that places real orders.
    """
    sid, _token = _make(live_enabled=True)

    response = post(client, "start", strategy_id=sid)

    assert response.status_code == 400
    assert response.get_json()["status"] == "error"
    assert engine.calls == [], "the engine ran on a start with no mode"


@pytest.mark.parametrize("mode", ["real", "paper", "LIVE", "Sandbox", "", None, 1, ["live"]])
def test_start_with_an_invalid_mode_is_a_400(client, engine, mode):
    """Case-sensitive and exact. 'LIVE' is not 'live', and a near-miss such as
    'paper' must not be quietly read as sandbox."""
    sid, _token = _make(live_enabled=True)

    response = post(client, "start", strategy_id=sid, mode=mode)

    assert response.status_code == 400
    assert response.get_json()["status"] == "error"
    assert engine.calls == []


def test_start_in_sandbox_reaches_the_engine_with_the_mode_it_was_given(client, engine):
    sid, _token = _make()

    response = post(client, "start", strategy_id=sid, mode="sandbox")

    assert response.status_code == 200
    body = response.get_json()
    assert body == {
        "status": "success",
        "run_id": RUN_ID,
        "mode": "sandbox",
        "legs": [{"leg_id": 1, "ok": True, "error": None}],
    }
    assert engine.calls == [("start_run", sid, USER, "sandbox", "manual")]


# ---------------------------------------------------------------------------
# Start: live is opt-in per strategy
# ---------------------------------------------------------------------------


def test_live_on_a_sandbox_only_strategy_is_refused(client, engine):
    """The engine checks this too. This layer checks it as well so the refusal
    happens before the order path and carries an actionable message."""
    sid, _token = _make(live_enabled=False)

    response = post(client, "start", strategy_id=sid, mode="live")

    assert response.status_code == 409
    body = response.get_json()
    assert body["status"] == "error"
    assert "not enabled for live trading" in body["message"]
    assert engine.calls == [], "the engine ran on a live start it should have refused"


def test_live_is_allowed_once_the_strategy_opts_in(client, engine):
    sid, _token = _make(live_enabled=True)

    response = post(client, "start", strategy_id=sid, mode="live")

    assert response.status_code == 200
    assert response.get_json()["mode"] == "live"
    assert engine.calls == [("start_run", sid, USER, "live", "manual")]


def test_an_engine_refusal_is_a_conflict_only_when_it_is_one(client, engine):
    sid, _token = _make()

    engine.start_result = StartResult(ok=False, error="This strategy is already running")
    assert post(client, "start", strategy_id=sid, mode="sandbox").status_code == 409

    engine.start_result = StartResult(ok=False, error="Leg 1 could not be resolved")
    assert post(client, "start", strategy_id=sid, mode="sandbox").status_code == 400


# ---------------------------------------------------------------------------
# Ownership: 404, never 403
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("route,extra", _every_route(1)[1:])
def test_another_users_strategy_is_404_not_403(client, engine, route, extra):
    """A 403 would confirm the id exists, which is all an attacker needs to
    walk the id space and learn how many strategies the box has."""
    sid, _token = _make(user=OTHER, running=True)

    response = post(client, route, **{**extra, "strategy_id": sid})

    assert response.status_code == 404, f"{route} answered {response.status_code}"
    body = response.get_json()
    assert body["status"] == "error"
    assert body["message"] == "Strategy not found"
    assert engine.calls == []


def test_a_missing_strategy_is_indistinguishable_from_one_that_is_not_yours(client):
    mine, _token = _make(user=OTHER)
    absent = mine + 5000

    theirs = post(client, "status", strategy_id=mine)
    missing = post(client, "status", strategy_id=absent)

    assert theirs.status_code == missing.status_code == 404
    assert theirs.get_json() == missing.get_json()


def test_a_list_only_returns_this_users_strategies(client):
    _make(user=USER, name="Mine")
    _make(user=OTHER, name="Theirs")

    body = post(client, "list").get_json()

    assert [row["name"] for row in body["data"]] == ["Mine"]


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def test_an_invalid_api_key_is_rejected(client, engine):
    sid, _token = _make(live_enabled=True, running=True)

    for route, extra in _every_route(sid):
        response = client.post(f"/strategy/{route}", json={**extra, "apikey": "not-a-key"})
        assert response.status_code == 403, f"{route} answered {response.status_code}"
        assert response.get_json() == {"status": "error", "message": "Invalid openalgo apikey"}

    assert engine.calls == [], "the engine ran without a valid API key"


def test_a_missing_api_key_is_rejected(client, engine):
    sid, _token = _make(live_enabled=True, running=True)

    for route, extra in _every_route(sid):
        response = client.post(f"/strategy/{route}", json=extra)
        assert response.status_code == 400, f"{route} answered {response.status_code}"
        assert response.get_json()["status"] == "error"

    assert engine.calls == []


def test_an_empty_body_never_starts_anything(client, engine):
    """No apikey, no strategy_id, no mode. Every one of those is required, and
    the failure must be a refusal rather than a defaulted live start."""
    response = client.post("/strategy/start", json={})

    assert response.status_code == 400
    assert engine.calls == []


# ---------------------------------------------------------------------------
# Stop, close_all and close_leg
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "route,extra",
    [("stop", {}), ("close_all", {}), ("close_leg", {"leg_id": 1})],
)
def test_stopping_a_strategy_that_is_not_running_is_a_conflict(client, engine, route, extra):
    """409, not 400: the payload is fine, the state is not."""
    sid, _token = _make(running=False)

    response = post(client, route, strategy_id=sid, **extra)

    assert response.status_code == 409
    body = response.get_json()
    assert body["status"] == "error"
    assert body["message"] == "This strategy is not running"
    assert engine.calls == []


def test_stop_resolves_the_run_from_the_strategy(client, engine):
    """The caller never supplies a run id: it would be a second thing to
    authorise, and getting it wrong would stop a run that is not the live one."""
    sid, _token = _make(running=True)

    response = post(client, "stop", strategy_id=sid)

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "success",
        "run_id": RUN_ID,
        "stop_pending": True,
        "exits": [{"leg_id": 1, "ok": True, "error": None}],
    }
    assert engine.calls == [("stop_run", RUN_ID, USER, "manual")]


@pytest.mark.parametrize("route", ["stop", "close_all"])
def test_stop_failures_preserve_pending_and_per_exit_detail(client, engine, route):
    sid, _token = _make(running=True)
    exits = [{"leg_id": 1, "ok": False, "error": "No API key"}]
    engine.stop_result = {
        "ok": False,
        "stop_pending": True,
        "error": "No API key is configured for this user",
        "exits": exits,
    }

    response = post(client, route, strategy_id=sid)

    assert response.status_code == 409
    assert response.get_json() == {
        "status": "error",
        "message": "No API key is configured for this user",
        "stop_pending": True,
        "exits": exits,
    }


def test_restx_close_all_event_matches_the_browser_intent_contract(client, engine):
    """Both API surfaces record a request, never pre-fill closure."""
    sid, _token = _make(running=True)

    response = post(client, "close_all", strategy_id=sid)
    assert response.status_code == 200
    assert response.get_json()["stop_pending"] is True

    event = next(
        event
        for event in store.list_events(sid)
        if event["kind"] == "close_all_manual"
    )
    assert event["message"] == "Operator requested closure of all held legs"
    assert "closed" not in event["message"].lower()
    assert engine.calls == [("stop_run", RUN_ID, USER, "manual")]


def test_close_leg_passes_the_leg_through_and_reports_whether_the_run_ended(client, engine):
    sid, _token = _make(running=True)
    engine.close_leg_result = {"ok": True, "exits": [], "run_stopped": True}

    body = post(client, "close_leg", strategy_id=sid, leg_id=2).get_json()

    assert body == {
        "status": "success",
        "run_id": RUN_ID,
        "leg_id": 2,
        "run_stopped": True,
        "exits": [],
    }
    assert engine.calls == [("close_leg", RUN_ID, 2, USER)]


def test_close_leg_requires_a_leg_id(client, engine):
    sid, _token = _make(running=True)

    assert post(client, "close_leg", strategy_id=sid).status_code == 400
    assert engine.calls == []


@pytest.mark.parametrize("route,extra", [("stop", {}), ("close_leg", {"leg_id": 1})])
def test_an_engine_refusal_on_an_exit_is_a_conflict(client, engine, route, extra):
    sid, _token = _make(running=True)
    engine.stop_result = {"ok": False, "error": "Run is not active"}
    engine.close_leg_result = {"ok": False, "error": "That leg is not open"}

    response = post(client, route, strategy_id=sid, **extra)

    assert response.status_code == 409
    assert response.get_json()["status"] == "error"


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def test_status_returns_the_configuration_and_the_current_run(client):
    sid, _token = _make(running=True)
    run = store.create_run(strategy_id=sid, mode="sandbox", broker="sandbox")
    store.set_strategy_status(sid, "running", run.id)

    body = post(client, "status", strategy_id=sid).get_json()

    assert body["status"] == "success"
    assert body["data"]["id"] == sid
    assert body["data"]["legs"][0]["id"] == 1
    assert body["run"]["id"] == run.id
    assert body["run"]["mode"] == "sandbox"


def test_status_reports_a_null_run_when_the_strategy_is_stopped(client):
    sid, _token = _make()

    body = post(client, "status", strategy_id=sid).get_json()

    assert body["run"] is None
    assert body["data"]["status"] == "stopped"


def test_runs_orders_and_events_are_scoped_to_the_strategy(client):
    sid, _token = _make()
    other_sid, _other_token = _make(name="Another")

    run = store.create_run(strategy_id=sid, mode="sandbox", broker="sandbox")
    other_run = store.create_run(strategy_id=other_sid, mode="sandbox", broker="sandbox")
    store.record_order(
        run.id,
        1,
        "entry",
        {"symbol": "NIFTY", "exchange": "NFO", "action": "SELL", "qty": 75},
    )
    store.record_order(
        other_run.id,
        1,
        "entry",
        {"symbol": "BANKNIFTY", "exchange": "NFO", "action": "SELL", "qty": 15},
    )
    store.record_event(sid, USER, "run_started", "mine", run_id=run.id)
    store.record_event(other_sid, USER, "run_started", "theirs", run_id=other_run.id)

    assert [r["id"] for r in post(client, "runs", strategy_id=sid).get_json()["data"]] == [run.id]

    orders = post(client, "orders", strategy_id=sid).get_json()["data"]
    assert [o["symbol"] for o in orders] == ["NIFTY"]

    events = post(client, "events", strategy_id=sid).get_json()["data"]
    assert [e["message"] for e in events] == ["mine"]


def test_a_foreign_run_id_filter_leaks_nothing(client):
    """run_id needs no separate ownership check because the store joins through
    this strategy, but that only holds if it really does."""
    sid, _token = _make()
    other_sid, _other_token = _make(name="Another")
    other_run = store.create_run(strategy_id=other_sid, mode="sandbox", broker="sandbox")
    store.record_order(
        other_run.id,
        1,
        "entry",
        {"symbol": "BANKNIFTY", "exchange": "NFO", "action": "SELL", "qty": 15},
    )
    store.record_event(other_sid, USER, "run_started", "theirs", run_id=other_run.id)

    orders = post(client, "orders", strategy_id=sid, run_id=other_run.id).get_json()
    events = post(client, "events", strategy_id=sid, run_id=other_run.id).get_json()

    assert orders["data"] == []
    assert events["data"] == []


@pytest.mark.parametrize(
    "route,extra",
    [
        ("events", {"kind": "not-a-kind"}),
        ("events", {"severity": "loud"}),
        ("events", {"limit": 0}),
        ("events", {"limit": -1}),
        ("events", {"limit": 100000}),
        ("runs", {"limit": 0}),
        ("runs", {"limit": -1}),
        ("list", {"status": "halted"}),
    ],
)
def test_an_out_of_vocabulary_filter_is_refused(client, route, extra):
    """A negative limit especially: SQLite reads it as 'no limit', so an
    unbounded field would serialize every row the strategy has."""
    sid, _token = _make()

    response = post(client, route, strategy_id=sid, **extra)

    assert response.status_code == 400
    assert response.get_json()["status"] == "error"


# ---------------------------------------------------------------------------
# The envelope
# ---------------------------------------------------------------------------


def test_every_route_returns_the_success_envelope(client):
    sid, _token = _make(live_enabled=True, running=True)

    for route, extra in _every_route(sid):
        response = post(client, route, **extra)
        assert response.status_code == 200, f"{route} answered {response.status_code}"
        body = response.get_json()
        assert isinstance(body, dict), f"{route} did not return a JSON object"
        assert body["status"] == "success", f"{route} returned {body}"
        assert "message" not in body, f"{route} returned an error message on success"


def test_every_route_returns_the_error_envelope(client):
    for route, extra in _every_route(999999):
        # A strategy id nobody owns provokes the scoped routes; /list takes no
        # id, so a bad key is what provokes it.
        key = "not-a-key" if route == "list" else API_KEY
        response = client.post(f"/strategy/{route}", json={**extra, "apikey": key})
        assert response.status_code >= 400, f"{route} answered {response.status_code}"
        body = response.get_json()
        assert body["status"] == "error", f"{route} returned {body}"
        assert "message" in body, f"{route} returned no message"


# ---------------------------------------------------------------------------
# The webhook token is never returned
# ---------------------------------------------------------------------------


def test_no_response_anywhere_contains_a_webhook_token(client):
    """Only the SHA-256 digest is stored, so there is nothing to return. This
    asserts that no route implies otherwise, including by name."""
    sid, token = _make(live_enabled=True, running=True)
    assert token.startswith(store.WEBHOOK_TOKEN_PREFIX)

    digest = store.hash_webhook_token(token)

    bodies = []
    for route, extra in _every_route(sid):
        bodies.append((route, post(client, route, **extra).get_data(as_text=True)))
        # Error paths too: a message that echoed the row could leak as easily.
        bodies.append((route, post(client, route, strategy_id=999999).get_data(as_text=True)))

    for route, text in bodies:
        assert token not in text, f"{route} returned the webhook token"
        assert digest not in text, f"{route} returned the webhook token hash"
        assert store.WEBHOOK_TOKEN_PREFIX not in text, f"{route} returned a token-shaped string"
        assert "webhook_token" not in text, f"{route} names a webhook token field"


def test_the_status_payload_carries_no_token_field(client):
    sid, _token = _make()

    data = post(client, "status", strategy_id=sid).get_json()["data"]

    assert "webhook_token" not in data
    assert "webhook_token_hash" not in data
