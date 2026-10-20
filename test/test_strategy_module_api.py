"""The /strategy configuration API.

The store in ``database/strategy_module_db.py`` validates nothing by design, so
``blueprints/strategy_module.py`` is the only thing standing between a webhook
payload and a JSON column. These tests assert the refusals rather than the happy
path: what the API must not accept, what it must not reveal, and what it must
not let through while a strategy is live.

Three properties are worth naming, because each one is a bug that would only
surface with real money on the line:

* a fractional strike survives untouched (rounding 292.5 to 292 names a
  contract that is not listed);
* ``overall_sl_mtm`` is refused when negative, because it is applied as a
  negative threshold and -5000 would silently mean "stop at a profit of 5000";
* somebody else's strategy answers 404, never 403, so the id space cannot be
  probed.

The store is rebound to a database of this run's own rather than the shared
``db/openalgo-test.db``, so a failing test cannot leave rows behind for the next
one.
"""

import sys
from datetime import datetime
from pathlib import Path

import pytest
import pytz
from flask import Flask

sys.path.insert(0, str(Path(__file__).parents[1]))

from blueprints import strategy_module  # noqa: E402
from database import strategy_module_db as store  # noqa: E402
from database.engine_factory import create_db_engine  # noqa: E402
from limiter import limiter  # noqa: E402

USER = "tester"
OTHER = "somebody-else"


# --------------------------------------------------------------------- fixtures


@pytest.fixture(scope="session", autouse=True)
def isolated_store(tmp_path_factory):
    """Point the store's scoped_session at a throwaway database."""
    path = tmp_path_factory.mktemp("strategy-module") / "strategy-module-test.db"
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
    """Every test starts with no strategies, so names cannot collide."""
    store.db_session.remove()
    with isolated_store.begin() as connection:
        for table in reversed(store.Base.metadata.sorted_tables):
            connection.execute(table.delete())
    yield
    store.db_session.remove()


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(limiter, "enabled", False)
    application = Flask(__name__)
    application.config.update(
        TESTING=True,
        SECRET_KEY="strategy-module-tests",
        PROPAGATE_EXCEPTIONS=True,
    )
    application.register_blueprint(strategy_module.strategy_module_bp)
    return application


def _log_in(client, username=USER):
    """The session shape ``utils.session.is_session_valid`` accepts."""
    with client.session_transaction() as flask_session:
        flask_session["logged_in"] = True
        flask_session["user"] = username
        flask_session["login_time"] = datetime.now(pytz.timezone("Asia/Kolkata")).isoformat()


@pytest.fixture
def client(app):
    test_client = app.test_client()
    _log_in(test_client)
    return test_client


# --------------------------------------------------------------------- payloads


def leg(**overrides):
    body = {
        "segment": "options",
        "position": "S",
        "lots": 1,
        "option_type": "CE",
        "strike_mode": "atm",
        "atm_offset": "ATM",
        "expiry": "weekly",
    }
    body.update(overrides)
    return body


def payload(**overrides):
    body = {
        "name": "Short Straddle",
        "underlying": "NIFTY",
        "underlying_exchange": "NSE_INDEX",
        "strategy_type": "intraday",
        "entry_time": "09:20",
        "exit_time": "15:10",
        "legs": [leg(), leg(option_type="PE")],
    }
    body.update(overrides)
    return body


def create(client, **overrides):
    """Create through the API and return the parsed response body."""
    response = client.post("/strategy/api/strategies", json=payload(**overrides))
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def create_for(username, **overrides):
    """Create straight in the store, on behalf of another user."""
    config, error = strategy_module.validate_strategy_config(payload(**overrides))
    assert error is None, error
    created, error = store.create_strategy(username, config)
    assert created, error
    return created


# ------------------------------------------------------------------- create


class TestCreate:
    def test_a_strategy_is_created_with_its_legs(self, client):
        body = create(client)

        assert body["status"] == "success"
        assert body["data"]["name"] == "Short Straddle"
        assert body["data"]["status"] == "stopped"
        assert len(body["data"]["legs"]) == 2

    def test_live_trading_is_off_until_it_is_asked_for(self, client):
        assert create(client)["data"]["live_enabled"] is False

    def test_the_webhook_token_comes_back_once(self, client):
        body = create(client)

        assert body["webhook_token"].startswith(store.WEBHOOK_TOKEN_PREFIX)

    def test_the_token_is_never_returned_again(self, client):
        body = create(client)

        detail = client.get(f"/strategy/api/strategies/{body['data']['id']}")
        listing = client.get("/strategy/api/strategies")

        assert "webhook_token" not in detail.get_json()
        assert "webhook_token" not in detail.get_data(as_text=True)
        assert "webhook_token" not in listing.get_data(as_text=True)

    def test_the_stored_token_is_a_hash_of_the_one_returned(self, client):
        """The response is the only copy: nothing can recover it afterwards."""
        body = create(client)
        row = store.get_strategy(body["data"]["id"], USER)

        assert row.webhook_token_hash == store.hash_webhook_token(body["webhook_token"])
        assert body["webhook_token"] not in str(row.webhook_token_hash)

    def test_a_duplicate_name_is_a_conflict(self, client):
        create(client)

        response = client.post("/strategy/api/strategies", json=payload())

        assert response.status_code == 409

    def test_a_body_that_is_not_an_object_is_refused(self, client):
        response = client.post("/strategy/api/strategies", json=["legs"])

        assert response.status_code == 400

    def test_no_body_at_all_is_refused(self, client):
        assert client.post("/strategy/api/strategies").status_code == 400


# --------------------------------------------------------------------- validation


#: (what is wrong, override, a word the message must carry).
REFUSALS = [
    # Top level, unknown and missing fields
    ("an unknown top-level field", {"turbo": True}, "turbo"),
    ("a field the store owns", {"webhook_token_hash": "x"}, "webhook_token_hash"),
    ("a missing name", {"name": None}, "name"),
    ("an empty name", {"name": "   "}, "name"),
    ("a name over 200 characters", {"name": "n" * 201}, "200"),
    ("a name that is not text", {"name": 42}, "name"),
    ("a missing underlying", {"underlying": None}, "underlying"),
    ("an underlying over 50 characters", {"underlying": "U" * 51}, "50"),
    ("a missing exchange", {"underlying_exchange": None}, "underlying_exchange"),
    ("an unknown exchange", {"underlying_exchange": "LSE"}, "underlying_exchange"),
    # Enums, every one against the store's own tuples
    ("an unknown strategy_kind", {"strategy_kind": "scalp"}, "strategy_kind"),
    ("an unknown direction", {"direction": "sideways"}, "direction"),
    ("an unknown strategy_type", {"strategy_type": "swing"}, "strategy_type"),
    ("an unknown product", {"product": "COVER"}, "product"),
    ("an unknown pricetype", {"pricetype": "ICEBERG"}, "pricetype"),
    ("a non-boolean trail_sl_to_entry", {"trail_sl_to_entry": "yes"}, "trail_sl_to_entry"),
    # Times
    ("a malformed entry_time", {"entry_time": "9.20am"}, "entry_time"),
    ("an entry_time hour out of range", {"entry_time": "25:00"}, "entry_time"),
    ("an entry_time minute out of range", {"entry_time": "09:75"}, "entry_time"),
    ("an intraday strategy with no entry_time", {"entry_time": None}, "entry_time"),
    ("an intraday strategy with no exit_time", {"exit_time": None}, "exit_time"),
    ("an exit before the entry", {"entry_time": "15:20"}, "earlier"),
    ("an exit equal to the entry", {"exit_time": "09:20"}, "earlier"),
    # Legs
    ("no legs field", {"legs": None}, "legs"),
    ("an empty leg list", {"legs": []}, "at least"),
    ("legs that are not a list", {"legs": {"0": leg()}}, "legs"),
    ("eleven legs", {"legs": [leg() for _ in range(11)]}, "at most 10"),
    ("a leg that is not an object", {"legs": ["CE"]}, "legs[0]"),
    ("an unknown leg field", {"legs": [leg(hedge=True)]}, "hedge"),
    ("a missing segment", {"legs": [leg(segment=None)]}, "segment"),
    ("an unknown segment", {"legs": [leg(segment="crypto")]}, "segment"),
    ("a missing position", {"legs": [leg(position=None)]}, "position"),
    ("a position that is not B or S", {"legs": [leg(position="BUY")]}, "position"),
    ("missing lots", {"legs": [leg(lots=None)]}, "lots"),
    ("zero lots", {"legs": [leg(lots=0)]}, "lots"),
    ("fifty-one lots", {"legs": [leg(lots=51)]}, "lots"),
    ("a fractional lot", {"legs": [leg(lots=1.5)]}, "whole number"),
    ("lots sent as a boolean", {"legs": [leg(lots=True)]}, "whole number"),
    ("an options leg with no option_type", {"legs": [leg(option_type=None)]}, "option_type"),
    ("an unknown option_type", {"legs": [leg(option_type="CALL")]}, "option_type"),
    ("an unknown strike_mode", {"legs": [leg(strike_mode="delta")]}, "strike_mode"),
    ("an unknown atm_offset", {"legs": [leg(atm_offset="OTM6")]}, "atm_offset"),
    ("an atm_offset that is not one of ours", {"legs": [leg(atm_offset="ATM+1")]}, "atm_offset"),
    ("a missing expiry", {"legs": [leg(expiry=None)]}, "expiry"),
    ("an unknown expiry", {"legs": [leg(expiry="quarterly")]}, "expiry"),
    (
        "a strike leg with no strike",
        {"legs": [leg(strike_mode="strike", atm_offset=None)]},
        "strike",
    ),
    (
        "a strike of zero",
        {"legs": [leg(strike_mode="strike", atm_offset=None, strike=0)]},
        "strike",
    ),
    (
        "a negative strike",
        {"legs": [leg(strike_mode="strike", atm_offset=None, strike=-100)]},
        "strike",
    ),
    (
        "a strike named alongside an ATM offset",
        {"legs": [leg(strike_mode="strike", strike=24500)]},
        "atm_offset",
    ),
    ("a strike named on an ATM leg", {"legs": [leg(strike=24500)]}, "strike"),
    (
        "an option_type on a futures leg",
        {"legs": [leg(segment="futures", strike_mode=None, atm_offset=None)]},
        "option_type",
    ),
    (
        "an expiry on a cash leg",
        {"legs": [leg(segment="cash", option_type=None, strike_mode=None, atm_offset=None)]},
        "expiry",
    ),
    ("a negative sl_pts", {"legs": [leg(sl_pts=-1)]}, "sl_pts"),
    ("a negative target_pts", {"legs": [leg(target_pts=-1)]}, "target_pts"),
    ("a non-numeric sl_pts", {"legs": [leg(sl_pts="tight")]}, "sl_pts"),
    ("a trail with no y", {"legs": [leg(trail={"x": 10})]}, "trail.y"),
    ("a trail with no x", {"legs": [leg(trail={"y": 5})]}, "trail.x"),
    ("a negative trail x", {"legs": [leg(trail={"x": -10, "y": 5})]}, "trail.x"),
    ("a negative trail y", {"legs": [leg(trail={"x": 10, "y": -5})]}, "trail.y"),
    ("an unknown trail field", {"legs": [leg(trail={"x": 10, "y": 5, "z": 1})]}, "z"),
    ("two legs sharing an id", {"legs": [leg(id=1), leg(id=1)]}, "id"),
    # Strategy-level risk
    ("a negative overall_target_mtm", {"overall_target_mtm": -1}, "overall_target_mtm"),
    ("a non-numeric overall_sl_mtm", {"overall_sl_mtm": "lots"}, "overall_sl_mtm"),
    # Lock profit
    ("a lock_profit that is not an object", {"lock_profit": "lock"}, "lock_profit"),
    (
        "a lock_profit with no mode",
        {"lock_profit": {"if_profit_reaches": 5000, "lock_profit": 2000}},
        "mode",
    ),
    (
        "an unknown lock_profit mode",
        {"lock_profit": {"mode": "ratchet", "if_profit_reaches": 5000, "lock_profit": 2000}},
        "mode",
    ),
    (
        "a lock_profit with no trigger",
        {"lock_profit": {"mode": "lock", "lock_profit": 2000}},
        "if_profit_reaches",
    ),
    (
        "a zero trigger",
        {"lock_profit": {"mode": "lock", "if_profit_reaches": 0, "lock_profit": 0}},
        "if_profit_reaches",
    ),
    (
        "a floor above the profit that arms it",
        {"lock_profit": {"mode": "lock", "if_profit_reaches": 5000, "lock_profit": 6000}},
        "lock_profit",
    ),
    (
        "lock_and_trail with no trail_step",
        {
            "lock_profit": {
                "mode": "lock_and_trail",
                "if_profit_reaches": 5000,
                "lock_profit": 2000,
            }
        },
        "trail_step",
    ),
    (
        "a zero trail_step",
        {
            "lock_profit": {
                "mode": "lock_and_trail",
                "if_profit_reaches": 5000,
                "lock_profit": 2000,
                "trail_step": 0,
            }
        },
        "trail_step",
    ),
    (
        "an unknown lock_profit field",
        {
            "lock_profit": {
                "mode": "lock",
                "if_profit_reaches": 5000,
                "lock_profit": 2000,
                "ratchet": True,
            }
        },
        "ratchet",
    ),
    # Scheduler
    ("a scheduler that is not an object", {"scheduler": True}, "scheduler"),
    (
        "an unknown scheduler field",
        {"scheduler": {"enabled": False, "timezone": "UTC"}},
        "timezone",
    ),
    ("a non-boolean enabled", {"scheduler": {"enabled": "yes"}}, "enabled"),
    ("an unknown day", {"scheduler": {"enabled": False, "days": ["MONDAY"]}}, "days[0]"),
    (
        "a repeated day",
        {"scheduler": {"enabled": False, "days": ["MON", "mon"]}},
        "more than once",
    ),
    ("an enabled scheduler with no days", {"scheduler": {"enabled": True}}, "days"),
    (
        "an enabled scheduler with no start_time",
        {"scheduler": {"enabled": True, "days": ["MON"], "auto_stop_time": "15:10"}},
        "start_time",
    ),
    (
        "an enabled scheduler with no auto_stop_time",
        {"scheduler": {"enabled": True, "days": ["MON"], "start_time": "09:20"}},
        "auto_stop_time",
    ),
    (
        "a scheduler that stops before it starts",
        {
            "scheduler": {
                "enabled": True,
                "days": ["MON"],
                "start_time": "15:20",
                "auto_stop_time": "09:20",
            }
        },
        "earlier",
    ),
    (
        "a malformed scheduler time",
        {"scheduler": {"enabled": False, "start_time": "9am"}},
        "start_time",
    ),
    (
        "an unknown default_mode",
        {"scheduler": {"enabled": False, "default_mode": "paper"}},
        "default_mode",
    ),
    # Webhook allowlist
    ("an allowlist that is not a list", {"webhook_ip_allowlist": "1.2.3.4"}, "allowlist"),
    ("an entry that is not an address", {"webhook_ip_allowlist": ["not-an-ip"]}, "allowlist[0]"),
    ("an empty allowlist entry", {"webhook_ip_allowlist": ["  "]}, "allowlist[0]"),
]


@pytest.mark.parametrize(
    "override,fragment",
    [(override, fragment) for _label, override, fragment in REFUSALS],
    ids=[label for label, _override, _fragment in REFUSALS],
)
def test_a_bad_payload_is_refused_with_a_reason(client, override, fragment):
    response = client.post("/strategy/api/strategies", json=payload(**override))

    assert response.status_code == 400, response.get_json()
    message = response.get_json()["message"]
    assert fragment in message, f"{fragment!r} missing from {message!r}"


def test_nothing_is_stored_when_the_payload_is_refused(client):
    client.post("/strategy/api/strategies", json=payload(legs=[]))

    assert store.list_strategies(USER) == []


def test_an_unknown_field_is_refused_rather_than_dropped(client):
    """Silently dropping it would report success for a strategy that is not
    the one the caller described."""
    response = client.post("/strategy/api/strategies", json=payload(overall_sl_mtmm=5000))

    assert response.status_code == 400
    assert "overall_sl_mtmm" in response.get_json()["message"]
    assert store.list_strategies(USER) == []


class TestTheLossThresholdIsEnteredPositive:
    def test_a_negative_overall_sl_mtm_is_refused(self, client):
        response = client.post("/strategy/api/strategies", json=payload(overall_sl_mtm=-5000))

        assert response.status_code == 400

    def test_the_message_explains_the_sign(self, client):
        response = client.post("/strategy/api/strategies", json=payload(overall_sl_mtm=-5000))

        message = response.get_json()["message"]
        assert "positive" in message and "negative threshold" in message

    def test_a_negative_daily_loss_limit_is_refused_the_same_way(self, client):
        response = client.post("/strategy/api/strategies", json=payload(daily_loss_limit_inr=-2000))

        assert response.status_code == 400
        assert "positive" in response.get_json()["message"]

    def test_a_positive_amount_is_stored_as_entered(self, client):
        """Stored positive, negated where the comparison happens. Storing it
        negative would make the value fail its own validator on the next PATCH."""
        body = create(client, overall_sl_mtm=5000)

        assert body["data"]["overall_sl_mtm"] == 5000


class TestStrikesAreNeverRounded:
    def test_a_fractional_strike_survives_a_round_trip(self, client):
        body = create(
            client,
            legs=[leg(strike_mode="strike", atm_offset=None, strike=292.5)],
        )

        detail = client.get(f"/strategy/api/strategies/{body['data']['id']}").get_json()

        assert detail["data"]["legs"][0]["strike"] == 292.5

    def test_a_fractional_strike_survives_an_update(self, client):
        body = create(client)
        sid = body["data"]["id"]

        client.patch(
            f"/strategy/api/strategies/{sid}",
            json={"legs": [leg(strike_mode="strike", atm_offset=None, strike=1234.75)]},
        )
        detail = client.get(f"/strategy/api/strategies/{sid}").get_json()

        assert detail["data"]["legs"][0]["strike"] == 1234.75

    def test_a_whole_strike_stays_whole(self, client):
        body = create(client, legs=[leg(strike_mode="strike", atm_offset=None, strike=24500)])

        assert body["data"]["legs"][0]["strike"] == 24500


class TestNormalization:
    def test_enums_are_stored_in_their_canonical_spelling(self, client):
        body = create(client, legs=[leg(position="b", expiry="WEEKLY", option_type="ce")])

        stored = body["data"]["legs"][0]
        assert (stored["position"], stored["expiry"], stored["option_type"]) == (
            "B",
            "weekly",
            "CE",
        )

    def test_an_underlying_is_upper_cased(self, client):
        assert create(client, underlying="nifty")["data"]["underlying"] == "NIFTY"

    def test_scheduler_days_come_back_in_week_order(self, client):
        body = create(
            client,
            scheduler={
                "enabled": True,
                "days": ["FRI", "mon", "WED"],
                "start_time": "09:20",
                "auto_stop_time": "15:10",
            },
        )

        assert body["data"]["scheduler"]["days"] == ["MON", "WED", "FRI"]

    def test_the_scheduler_defaults_to_sandbox(self, client):
        """Live has to be asked for, here as everywhere else in the module."""
        body = create(client, scheduler={"enabled": False})

        assert body["data"]["scheduler"]["default_mode"] == "sandbox"

    def test_a_positional_strategy_needs_no_times(self, client):
        body = create(client, strategy_type="positional", entry_time=None, exit_time=None)

        assert body["data"]["entry_time"] is None


# ------------------------------------------------------------------------ update


class TestUpdate:
    def test_a_stopped_strategy_can_be_renamed(self, client):
        sid = create(client)["data"]["id"]

        response = client.patch(f"/strategy/api/strategies/{sid}", json={"name": "Renamed"})

        assert response.status_code == 200
        assert response.get_json()["data"]["name"] == "Renamed"

    def test_an_unknown_field_is_refused(self, client):
        sid = create(client)["data"]["id"]

        response = client.patch(f"/strategy/api/strategies/{sid}", json={"turbo": True})

        assert response.status_code == 400
        assert "turbo" in response.get_json()["message"]

    @pytest.mark.parametrize("field", ["status", "live_enabled", "user_id", "current_run_id"])
    def test_fields_outside_the_store_allowlist_are_refused(self, client, field):
        """Mass assignment: these have their own routes or belong to the engine."""
        sid = create(client)["data"]["id"]

        response = client.patch(f"/strategy/api/strategies/{sid}", json={field: "running"})

        assert response.status_code == 400
        assert field in response.get_json()["message"]

    def test_status_is_untouched_by_a_refused_update(self, client):
        sid = create(client)["data"]["id"]

        client.patch(f"/strategy/api/strategies/{sid}", json={"status": "running"})

        assert store.get_strategy(sid, USER).status == "stopped"

    def test_a_partial_update_is_checked_against_the_whole_strategy(self, client):
        """entry_time alone is valid; against the stored 15:10 exit it is not."""
        sid = create(client)["data"]["id"]

        response = client.patch(f"/strategy/api/strategies/{sid}", json={"entry_time": "15:30"})

        assert response.status_code == 400
        assert "earlier" in response.get_json()["message"]

    def test_an_untouched_field_is_left_alone(self, client):
        sid = create(client, overall_sl_mtm=5000)["data"]["id"]

        client.patch(f"/strategy/api/strategies/{sid}", json={"name": "Renamed"})

        assert store.get_strategy(sid, USER).name == "Renamed"
        assert float(store.get_strategy(sid, USER).overall_sl_mtm) == 5000

    def test_an_empty_body_is_refused(self, client):
        sid = create(client)["data"]["id"]

        assert client.patch(f"/strategy/api/strategies/{sid}", json={}).status_code == 400

    def test_a_running_strategy_cannot_be_edited(self, client):
        sid = create(client)["data"]["id"]
        store.set_strategy_status(sid, "running", run_id=None)

        response = client.patch(f"/strategy/api/strategies/{sid}", json={"name": "Renamed"})

        assert response.status_code == 409
        assert "Stop the strategy" in response.get_json()["message"]

    def test_a_running_strategy_keeps_its_configuration(self, client):
        sid = create(client)["data"]["id"]
        store.set_strategy_status(sid, "running", run_id=None)

        client.patch(f"/strategy/api/strategies/{sid}", json={"name": "Renamed"})

        assert store.get_strategy(sid, USER).name == "Short Straddle"


# ------------------------------------------------------------------------ delete


class TestDelete:
    def test_a_stopped_strategy_is_deleted(self, client):
        sid = create(client)["data"]["id"]

        response = client.delete(f"/strategy/api/strategies/{sid}")

        assert response.status_code == 200
        assert store.get_strategy(sid, USER) is None

    def test_a_running_strategy_cannot_be_deleted(self, client):
        sid = create(client)["data"]["id"]
        store.set_strategy_status(sid, "running", run_id=None)

        response = client.delete(f"/strategy/api/strategies/{sid}")

        assert response.status_code == 409
        assert store.get_strategy(sid, USER) is not None


# -------------------------------------------------------------------- ownership


#: Every route that names a strategy by id.
OWNED_ROUTES = [
    ("GET", ""),
    ("PATCH", ""),
    ("DELETE", ""),
    ("POST", "/webhook/rotate"),
    ("POST", "/live"),
    ("POST", "/kill_switch"),
    ("POST", "/unlock_webhook"),
    ("GET", "/runs"),
    ("GET", "/orders"),
    ("GET", "/events"),
    ("GET", "/webhook_events"),
    ("GET", "/checkpoints"),
]


@pytest.mark.parametrize(
    "method,suffix", OWNED_ROUTES, ids=[f"{m}{s or '/'}" for m, s in OWNED_ROUTES]
)
def test_somebody_elses_strategy_is_404_never_403(client, method, suffix):
    """403 would confirm the row exists. The two cases must be identical."""
    theirs = create_for(OTHER, name="Theirs")

    response = client.open(
        f"/strategy/api/strategies/{theirs['id']}{suffix}",
        method=method,
        json={"name": "Mine now", "enabled": True},
    )

    assert response.status_code == 404
    assert response.get_json()["message"] == "Strategy not found"


@pytest.mark.parametrize(
    "method,suffix", OWNED_ROUTES, ids=[f"{m}{s or '/'}" for m, s in OWNED_ROUTES]
)
def test_a_strategy_that_never_existed_answers_the_same(client, method, suffix):
    response = client.open(
        f"/strategy/api/strategies/999999{suffix}",
        method=method,
        json={"name": "x", "enabled": True},
    )

    assert response.status_code == 404


def test_somebody_elses_strategy_is_not_modified(client):
    theirs = create_for(OTHER, name="Theirs")

    client.patch(f"/strategy/api/strategies/{theirs['id']}", json={"name": "Mine now"})
    client.delete(f"/strategy/api/strategies/{theirs['id']}")

    assert store.get_strategy(theirs["id"], OTHER).name == "Theirs"


def test_a_listing_only_shows_your_own(client):
    create_for(OTHER, name="Theirs")
    create(client, name="Mine")

    names = [row["name"] for row in client.get("/strategy/api/strategies").get_json()["data"]]

    assert names == ["Mine"]


def test_an_unauthenticated_request_is_refused(app):
    response = app.test_client().get(
        "/strategy/api/strategies", headers={"Accept": "application/json"}
    )

    assert response.status_code == 401


# ------------------------------------------------------------------ webhook token


class TestWebhookToken:
    def test_rotating_issues_a_different_token(self, client):
        body = create(client)
        sid = body["data"]["id"]

        rotated = client.post(f"/strategy/api/strategies/{sid}/webhook/rotate")

        assert rotated.status_code == 200
        assert rotated.get_json()["webhook_token"] != body["webhook_token"]

    def test_the_old_token_stops_resolving(self, client):
        body = create(client)
        sid = body["data"]["id"]

        rotated = client.post(f"/strategy/api/strategies/{sid}/webhook/rotate").get_json()

        assert store.get_strategy_by_webhook_token(body["webhook_token"]) is None
        assert store.get_strategy_by_webhook_token(rotated["webhook_token"]).id == sid


class TestLiveAndKillSwitch:
    def test_live_can_be_turned_on(self, client):
        sid = create(client)["data"]["id"]

        response = client.post(f"/strategy/api/strategies/{sid}/live", json={"enabled": True})

        assert response.status_code == 200
        assert store.get_strategy(sid, USER).live_enabled is True

    def test_live_can_be_turned_off_again(self, client):
        sid = create(client)["data"]["id"]
        client.post(f"/strategy/api/strategies/{sid}/live", json={"enabled": True})

        client.post(f"/strategy/api/strategies/{sid}/live", json={"enabled": False})

        assert store.get_strategy(sid, USER).live_enabled is False

    @pytest.mark.parametrize("value", ["true", 1, "yes", None])
    def test_enabled_must_be_an_actual_boolean(self, client, value):
        """'false' is a truthy string, so a loose read would enable live trading."""
        sid = create(client)["data"]["id"]

        response = client.post(f"/strategy/api/strategies/{sid}/live", json={"enabled": value})

        assert response.status_code == 400
        assert store.get_strategy(sid, USER).live_enabled is False

    def test_live_cannot_be_changed_while_running(self, client):
        sid = create(client)["data"]["id"]
        store.set_strategy_status(sid, "running", run_id=None)

        response = client.post(f"/strategy/api/strategies/{sid}/live", json={"enabled": True})

        assert response.status_code == 409
        assert store.get_strategy(sid, USER).live_enabled is False

    def test_the_kill_switch_locks_the_webhook(self, client):
        sid = create(client)["data"]["id"]

        response = client.post(f"/strategy/api/strategies/{sid}/kill_switch")

        assert response.status_code == 200
        assert store.get_strategy(sid, USER).webhook_locked is True

    def test_the_kill_switch_can_be_released(self, client):
        sid = create(client)["data"]["id"]
        client.post(f"/strategy/api/strategies/{sid}/kill_switch")

        client.post(f"/strategy/api/strategies/{sid}/unlock_webhook")

        assert store.get_strategy(sid, USER).webhook_locked is False

    def test_the_kill_switch_works_on_a_running_strategy(self, client):
        """The one control that must not be blocked by a running strategy."""
        sid = create(client)["data"]["id"]
        store.set_strategy_status(sid, "running", run_id=None)

        assert client.post(f"/strategy/api/strategies/{sid}/kill_switch").status_code == 200


# ------------------------------------------------------------------------ listing


class TestListing:
    def test_a_stopped_row_exposes_its_finalized_pnl_not_a_stale_checkpoint(self, client):
        """The list must not label pre-close MTM as exposure after the run is flat."""
        sid = create(client)["data"]["id"]
        run = store.create_run(sid, "sandbox", "")
        store.write_checkpoint(
            run.id,
            {
                "pnl_realized": 0,
                "pnl_unrealized": -19.5,
                "pnl_total": -19.5,
                "pnl_peak": 0,
                "pnl_trough": -19.5,
            },
        )
        assert store.finish_run(
            run.id,
            "manual",
            pnl_realized=-52,
            pnl_peak=0,
            pnl_trough=-52,
        )

        row = client.get("/strategy/api/strategies").get_json()["data"][0]

        assert row["last_finalized_run"]["id"] == run.id
        assert row["last_finalized_run"]["pnl_realized"] == -52.0
        assert row["last_finalized_run"]["stopped_at"] is not None

    def test_the_status_filter_is_checked(self, client):
        response = client.get("/strategy/api/strategies?status=galloping")

        assert response.status_code == 400

    def test_the_status_filter_narrows_the_list(self, client):
        running = create(client, name="Running")["data"]["id"]
        create(client, name="Stopped")
        store.set_strategy_status(running, "running", run_id=None)

        rows = client.get("/strategy/api/strategies?status=running").get_json()["data"]

        assert [row["name"] for row in rows] == ["Running"]

    def test_the_search_matches_on_name(self, client):
        create(client, name="Bank Nifty Condor")
        create(client, name="Nifty Straddle")

        rows = client.get("/strategy/api/strategies?q=condor").get_json()["data"]

        assert [row["name"] for row in rows] == ["Bank Nifty Condor"]


# ------------------------------------------------------------------------ history


class TestHistory:
    def test_runs_are_listed_for_the_strategy(self, client):
        sid = create(client)["data"]["id"]
        store.create_run(sid, "sandbox", "")

        rows = client.get(f"/strategy/api/strategies/{sid}/runs").get_json()["data"]

        assert len(rows) == 1 and rows[0]["mode"] == "sandbox"

    def test_orders_can_be_narrowed_to_one_run(self, client):
        sid = create(client)["data"]["id"]
        first = store.create_run(sid, "sandbox", "")
        second = store.create_run(sid, "sandbox", "")
        for run in (first, second):
            store.record_order(
                run.id,
                1,
                "entry",
                {"symbol": "NIFTY", "exchange": "NFO", "action": "SELL", "qty": 75},
            )

        rows = client.get(f"/strategy/api/strategies/{sid}/orders?run_id={first.id}").get_json()[
            "data"
        ]

        assert [row["run_id"] for row in rows] == [first.id]

    def test_a_non_numeric_run_id_is_refused(self, client):
        sid = create(client)["data"]["id"]

        response = client.get(f"/strategy/api/strategies/{sid}/orders?run_id=all")

        assert response.status_code == 400

    def test_creating_a_strategy_writes_an_event(self, client):
        sid = create(client)["data"]["id"]

        rows = client.get(f"/strategy/api/strategies/{sid}/events").get_json()["data"]

        assert [row["kind"] for row in rows] == ["strategy_created"]

    def test_an_unknown_event_kind_is_refused(self, client):
        sid = create(client)["data"]["id"]

        response = client.get(f"/strategy/api/strategies/{sid}/events?kind=exploded")

        assert response.status_code == 400

    def test_an_unknown_event_severity_is_refused(self, client):
        sid = create(client)["data"]["id"]

        response = client.get(f"/strategy/api/strategies/{sid}/events?severity=fatal")

        assert response.status_code == 400

    def test_the_event_limit_is_honoured(self, client):
        sid = create(client)["data"]["id"]
        store.record_event(sid, USER, "run_started", "started")

        rows = client.get(f"/strategy/api/strategies/{sid}/events?limit=1").get_json()["data"]

        assert len(rows) == 1

    def test_a_negative_limit_does_not_mean_unlimited(self, client):
        """SQLite reads a negative LIMIT as no limit at all."""
        sid = create(client)["data"]["id"]
        store.record_event(sid, USER, "run_started", "started")

        rows = client.get(f"/strategy/api/strategies/{sid}/events?limit=-1").get_json()["data"]

        assert len(rows) == 1

    def test_webhook_events_are_listed(self, client):
        sid = create(client)["data"]["id"]
        store.record_webhook_event("rejected_locked", strategy_id=sid)

        rows = client.get(f"/strategy/api/strategies/{sid}/webhook_events").get_json()["data"]

        assert [row["result"] for row in rows] == ["rejected_locked"]

    def test_checkpoints_default_to_the_latest_run(self, client):
        sid = create(client)["data"]["id"]
        run = store.create_run(sid, "sandbox", "")
        store.write_checkpoint(run.id, {"pnl_total": 1200})

        body = client.get(f"/strategy/api/strategies/{sid}/checkpoints").get_json()

        assert body["run_id"] == run.id
        assert [row["pnl_total"] for row in body["data"]] == [1200.0]

    def test_checkpoints_are_empty_when_nothing_has_run(self, client):
        sid = create(client)["data"]["id"]

        body = client.get(f"/strategy/api/strategies/{sid}/checkpoints").get_json()

        assert body["data"] == [] and body["run_id"] is None

    def test_a_run_from_another_strategy_is_refused(self, client):
        """list_checkpoints is keyed on run_id alone, so the route has to check
        the run belongs here or any run id would answer."""
        mine = create(client, name="Mine")["data"]["id"]
        theirs = create_for(OTHER, name="Theirs")
        their_run = store.create_run(theirs["id"], "sandbox", "")
        store.write_checkpoint(their_run.id, {"pnl_total": 999})

        response = client.get(f"/strategy/api/strategies/{mine}/checkpoints?run_id={their_run.id}")

        assert response.status_code == 404
        assert "999" not in response.get_data(as_text=True)


# ---------------------------------------------------------------- validator unit


class TestTheValidatorEntryPoint:
    def test_it_returns_a_config_and_no_error(self):
        config, error = strategy_module.validate_strategy_config(payload())

        assert error is None
        assert config["name"] == "Short Straddle"

    def test_it_converts_times_for_the_store(self):
        config, _error = strategy_module.validate_strategy_config(payload())

        assert (config["entry_time"].hour, config["entry_time"].minute) == (9, 20)

    def test_it_returns_a_message_and_no_config(self):
        config, error = strategy_module.validate_strategy_config(payload(legs=[]))

        assert config is None
        assert "at least" in error

    def test_it_is_idempotent_over_its_own_output(self):
        """A PATCH feeds the stored configuration back through, so normalizing
        must reach a fixed point or an untouched strategy would stop saving."""
        once, _error = strategy_module.validate_strategy_config(
            payload(legs=[leg(position="s", expiry="WEEKLY")])
        )
        again, error = strategy_module.validate_strategy_config(
            {**once, "entry_time": "09:20", "exit_time": "15:10"}
        )

        assert error is None
        assert again["legs"] == once["legs"]
