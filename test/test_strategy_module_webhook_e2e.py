"""The webhook path end to end, with only the broker mocked.

Every other test in this module exercises one layer against fakes. This one
runs the whole chain a TradingView alert actually takes:

    HTTP POST -> route -> token lookup -> validation pipeline -> bridge
              -> engine -> order dispatch -> store

and asserts on what reaches the database, because that is what an operator sees
afterwards. Only the final broker call is replaced.

It exists because the route was missing for a while without anything noticing:
the pipeline had 103 passing tests and the frontend displayed the URL, but
nothing was registered to serve it. Layer tests proved the logic was right;
none of them proved it was reachable.
"""

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
import pytz
from flask import Flask

sys.path.insert(0, str(Path(__file__).parents[1]))

# restx_api first: see the note in test_strategy_module_order_dispatch.py.
import restx_api  # noqa: E402,F401
from blueprints import strategy_module  # noqa: E402
from database import strategy_module_db as store  # noqa: E402
from database.engine_factory import create_db_engine  # noqa: E402
from limiter import limiter  # noqa: E402
from services.strategy_module import state, webhook  # noqa: E402
from services.strategy_module.order_dispatch import DispatchResult  # noqa: E402
from services.strategy_module.symbol_resolver import ResolvedLeg  # noqa: E402

USER = "e2e-user"


@pytest.fixture(scope="session", autouse=True)
def isolated_store(tmp_path_factory):
    path = tmp_path_factory.mktemp("strategy-e2e") / "e2e.db"
    engine = create_db_engine(f"sqlite:///{path.as_posix()}")
    store.db_session.remove()
    store.db_session.configure(bind=engine)
    store.engine = engine
    store.Base.metadata.create_all(bind=engine)
    yield engine
    store.db_session.remove()
    engine.dispose()


@pytest.fixture(autouse=True)
def clean(isolated_store):
    # Re-assert the binding on every test rather than only at session setup.
    # Sibling suites rebind this same global scoped_session to their own
    # throwaway database, and with two session-scoped fixtures doing that,
    # whichever set up last wins and a teardown can dispose an engine another
    # file is still using. Rebinding per test makes this file independent of
    # what else ran first.
    store.db_session.remove()
    store.db_session.configure(bind=isolated_store)
    store.engine = isolated_store
    with isolated_store.begin() as connection:
        for table in reversed(store.Base.metadata.sorted_tables):
            connection.execute(table.delete())
    store.clear_strategy_module_cache()
    webhook.reset_state()
    for run_id in list(state.active_run_ids()):
        state.clear_run_state(run_id)
    yield
    store.db_session.remove()
    webhook.reset_state()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(limiter, "enabled", False)
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="k", PROPAGATE_EXCEPTIONS=True)
    app.register_blueprint(strategy_module.strategy_module_bp)
    return app.test_client()


@pytest.fixture
def broker():
    """Records every order that would have reached a broker, and accepts them."""
    placed = []

    def record(**kwargs):
        placed.append(kwargs["order"])
        return DispatchResult(ok=True, broker_order_id=f"E2E-{len(placed)}", response={})

    with (
        patch("services.strategy_module.order_dispatch.dispatch_order", side_effect=record),
        patch("database.auth_db.get_api_key_for_tradingview", return_value="test-key"),
        # engine imports resolve_leg by name at module scope, so the engine's
        # own reference is what has to be replaced. Patching it on
        # symbol_resolver leaves engine.resolve_leg bound to the original.
        patch(
            "services.strategy_module.engine.resolve_leg",
            return_value=ResolvedLeg(
                ok=True,
                symbol="NIFTY28MAY2624000CE",
                exchange="NFO",
                segment="options",
                lotsize=75,
                quantity=75,
                lots=1,
                option_type="CE",
                strike=24000.0,
                expiry="28-MAY-26",
                underlying_ltp=24010.0,
            ),
        ),
    ):
        yield placed


def _batch_strategy():
    created, error = store.create_strategy(
        USER,
        {
            "name": "E2E batch",
            "underlying": "NIFTY",
            "underlying_exchange": "NSE_INDEX",
            "universe_tab": "weekly_monthly",
            "strategy_kind": "batch",
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
                }
            ],
        },
    )
    assert error is None, error
    return created["id"], created["webhook_token"]


def _signal_strategy():
    created, error = store.create_strategy(
        USER,
        {
            "name": "E2E signal",
            "underlying": "MULTI",
            "underlying_exchange": "NSE",
            "universe_tab": "stocks_fno",
            "strategy_kind": "signal",
            "direction": "both",
            "strategy_type": "positional",
            # Intraday, because these legs are cash and they short. Cash cannot
            # be carried short, so a carry product would have every short_entry
            # refused before it reached the broker.
            "product": "MIS",
            "legs": [
                {
                    "id": 1,
                    "symbol": "RELIANCE",
                    "exchange": "NSE",
                    "side": "both",
                    "qty": 100,
                    "segment": "cash",
                }
            ],
        },
    )
    assert error is None, error
    return created["id"], created["webhook_token"]


def _post(client, token, body):
    return client.post(f"/strategy/webhook/{token}", json=body)


# ---------------------------------------------------------------------------


def test_a_batch_start_alert_reaches_the_broker_and_the_audit_trail(client, broker):
    sid, token = _batch_strategy()

    response = _post(client, token, {"action": "start", "mode": "sandbox"})

    assert response.status_code == 200
    assert response.get_json()["status"] == "success"

    # An order actually went out.
    assert len(broker) == 1
    assert broker[0]["symbol"] == "NIFTY28MAY2624000CE"
    assert broker[0]["action"] == "SELL"

    # And the run, the order row and the audit rows all exist.
    runs = store.list_runs(sid)
    assert len(runs) == 1 and runs[0]["mode"] == "sandbox"
    assert [o["kind"] for o in store.list_orders(runs[0]["id"])] == ["entry"]
    assert [e["result"] for e in store.list_webhook_events(sid)] == ["ok"]
    assert store.get_strategy(sid, USER).status == "running"


def test_a_signal_alert_opens_one_leg_on_the_side_the_signal_asked_for(client, broker):
    sid, token = _signal_strategy()

    response = _post(client, token, {"action": "short_entry", "leg_id": 1})

    assert response.status_code == 200
    assert len(broker) == 1
    assert broker[0]["action"] == "SELL"
    assert broker[0]["symbol"] == "RELIANCE"

    run_id = store.get_strategy(sid, USER).current_run_id
    assert state.get_run_state(run_id)["legs"]["1"]["position"] == "S"


def test_a_signal_can_name_its_leg_by_symbol(client, broker):
    _sid, token = _signal_strategy()

    response = _post(
        client, token, {"action": "long_entry", "symbol": "RELIANCE", "exchange": "NSE"}
    )

    assert response.status_code == 200
    assert broker[0]["action"] == "BUY"


def test_a_repeat_signal_is_a_success_that_places_nothing(client, broker):
    # The property the whole no-op design exists for: reporting this as a
    # failure would invite the retry that turns one alert into two positions.
    _sid, token = _signal_strategy()
    _post(client, token, {"action": "long_entry", "leg_id": 1})
    assert len(broker) == 1

    response = _post(client, token, {"action": "long_entry", "leg_id": 1})

    assert response.status_code == 200
    assert response.get_json()["status"] == "success"
    assert len(broker) == 1


def test_an_exit_for_a_position_that_is_not_held_places_nothing(client, broker):
    _sid, token = _signal_strategy()

    response = _post(client, token, {"action": "long_exit", "leg_id": 1})

    assert response.status_code == 200
    assert not broker


def test_each_kind_refuses_the_other_vocabulary(client, broker):
    _bsid, batch_token = _batch_strategy()
    _ssid, signal_token = _signal_strategy()

    assert _post(client, batch_token, {"action": "long_entry", "leg_id": 1}).status_code == 400
    assert _post(client, signal_token, {"action": "start", "mode": "sandbox"}).status_code == 400
    assert not broker


def test_a_live_alert_is_refused_on_a_sandbox_only_strategy(client, broker):
    # The single most important refusal in the module: a strategy is born
    # sandbox-only and stays that way until the operator opts in.
    sid, token = _batch_strategy()

    response = _post(client, token, {"action": "start", "mode": "live"})

    assert response.status_code == 403
    assert not broker
    assert [e["result"] for e in store.list_webhook_events(sid)] == ["rejected_live_disabled"]


def test_an_unknown_token_is_answered_without_touching_any_strategy(client, broker):
    sid, _token = _batch_strategy()

    response = _post(client, "oaws_" + "Z" * 43, {"action": "start", "mode": "sandbox"})

    assert response.status_code == 404
    assert response.is_json
    assert not broker
    assert store.get_strategy(sid, USER).status == "stopped"


def test_a_rotated_token_stops_working_immediately(client, broker):
    sid, old_token = _batch_strategy()
    new_token, error = store.rotate_webhook_token(sid, USER)
    assert error is None

    assert _post(client, old_token, {"action": "start", "mode": "sandbox"}).status_code == 404
    assert not broker

    assert _post(client, new_token, {"action": "start", "mode": "sandbox"}).status_code == 200
    assert len(broker) == 1


def test_the_kill_switch_refuses_alerts_while_it_is_engaged(client, broker):
    sid, token = _batch_strategy()
    store.set_webhook_locked(sid, USER, True)

    response = _post(client, token, {"action": "start", "mode": "sandbox"})

    assert response.status_code == 403
    assert not broker
    assert [e["result"] for e in store.list_webhook_events(sid)] == ["rejected_locked"]


def test_the_token_never_appears_in_the_audit_payload(client, broker):
    sid, token = _batch_strategy()

    _post(client, token, {"action": "start", "mode": "sandbox", "note": token})

    rows = store.list_webhook_events(sid)
    assert rows
    assert token not in str(rows)
    assert store.WEBHOOK_TOKEN_PREFIX not in str(rows[0]["payload"])
