"""A Live run's orders go to the broker it started on, or nowhere.

OpenAlgo lets a trader log out of one broker and in to another. A run records
the broker it started on and, when the session names one, the broker account;
every later Live order, cancel and status read is held to that record. Before
this, the broker was resolved at send time, so stopping a run that held a short
at Zerodha after logging in to Fyers sent the covering BUY to Fyers: a new long
there, and the Zerodha short left with nothing managing it.

These tests switch the logged-in broker under a run that holds a position and
check that nothing reaches the new broker, that the run stays open and managed
with its position in view, that the refusal is said once in words a trader can
act on, and that logging back in to the run's broker resumes it.

Only the broker call and the stored session are faked. Dispatch, the binding
check, the run lock, the order rows and the audit trail are the real ones.
"""

import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import inspect

# restx_api first: see the note in test_strategy_module_order_dispatch.py.
import restx_api  # noqa: F401
import services.cancel_order_service  # noqa: F401
import services.orderstatus_service  # noqa: F401
import services.place_order_service  # noqa: F401
import services.sandbox_service  # noqa: F401
from database import strategy_module_db as store
from database.engine_factory import create_db_engine
from services.strategy_module import (
    ack_reconciliation,
    broker_binding,
    engine,
    order_dispatch,
    order_events,
    signals,
    state,
)
from services.strategy_module.order_dispatch import BrokerBinding
from services.strategy_module.symbol_resolver import ResolvedLeg

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "upgrade"))

import migrate_strategy_module as migration  # noqa: E402

USER = "broker_binding_test_user"
API_KEY = "binding-test-key"
SYMBOL = "NIFTY28MAY2624000CE"


# ---------------------------------------------------------------------------
# Fixtures: the stored session, and the broker call
# ---------------------------------------------------------------------------


class _Session:
    """The stored broker session, as database.auth_db reports it."""

    def __init__(self):
        self.token = "zerodha-token-1"
        self.broker = "zerodha"
        self.account = None
        self.token_reads = None

    def login(self, broker, token, account=None):
        self.broker, self.token, self.account = broker, token, account

    def logout(self):
        self.broker = self.token = self.account = None


@pytest.fixture(autouse=True)
def clean_slate():
    store.db_session.remove()
    store.init_db()

    def purge():
        for row in store.list_strategies(USER):
            for run in store.list_runs(row["id"]):
                state.clear_run_state(run["id"])
                engine._release_unactionable(run["id"])
            store.set_strategy_status(row["id"], "stopped", None)
            store.delete_strategy(row["id"], USER)
        store.clear_strategy_module_cache()

    purge()
    yield
    purge()


@pytest.fixture
def session():
    current = _Session()

    def token_broker(api_key, include_feed_token=False):
        return current.token, current.broker

    def account_of(name):
        return current.account

    with (
        patch("database.auth_db.get_auth_token_broker", side_effect=token_broker) as reads,
        patch("database.auth_db.get_user_id", side_effect=account_of),
        patch.object(engine, "_api_key_for", return_value=API_KEY),
        patch.object(signals, "_api_key_for", return_value=API_KEY),
        patch.object(engine, "_subscribe_run"),
        patch.object(engine, "_unsubscribe_run"),
    ):
        current.token_reads = reads
        yield current


@pytest.fixture(autouse=True)
def broker():
    """The live broker call: records what reached which broker, and accepts it.

    Autouse, so no test here can reach a real broker's API by forgetting it.
    """
    sent = []

    def place(order, auth_token, broker_name, original, force_live=False):
        sent.append(SimpleNamespace(token=auth_token, broker=broker_name, order=dict(order)))
        return True, {"status": "success", "orderid": f"LIVE-{len(sent)}"}, 200

    with patch("services.place_order_service.place_order_with_auth", side_effect=place):
        yield sent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config(**overrides):
    config = {
        "name": "Broker binding",
        "underlying": "NIFTY",
        "underlying_exchange": "NSE_INDEX",
        "universe_tab": "weekly_monthly",
        "product": "NRML",
        "legs": [
            {
                "id": 1,
                "segment": "options",
                "expiry": "weekly",
                "lots": 1,
                "position": "S",
                "option_type": "CE",
                "strike_mode": "atm",
                "atm_offset": "ATM",
                "sl_pts": 20,
                "trail": {"x": 0, "y": 0},
            }
        ],
    }
    config.update(overrides)
    return config


def _resolved():
    return ResolvedLeg(
        ok=True,
        symbol=SYMBOL,
        exchange="NFO",
        segment="options",
        lotsize=75,
        tick_size=0.05,
        strike=24000.0,
        expiry="28-MAY-26",
        expiry_symbol="28MAY26",
        quantity=75,
        lots=1,
        option_type="CE",
        underlying="NIFTY",
        underlying_ltp=24010.0,
        atm_strike=24000.0,
    )


def _make(config=None, live=True):
    created, error = store.create_strategy(USER, config or _config())
    assert error is None, error
    if live:
        assert store.set_live_enabled(created["id"], USER, True)[0]
    return created["id"]


def _start(mode="live"):
    """A run holding a short of 75 at whatever broker the session is on."""
    sid = _make(live=mode == "live")
    with patch.object(engine, "resolve_leg", return_value=_resolved()):
        started = engine.start_run(sid, USER, mode)
    assert started.ok, started.error
    engine.apply_fill(started.run_id, 1, 100.0, is_entry=True)
    leg = state.get_run_state(started.run_id)["legs"]["1"]
    assert (leg["status"], leg["position"], leg["qty"]) == ("open", "S", 75)
    return sid, started.run_id


def _exit_rows(run_id):
    return [row for row in store.list_orders(run_id) if row["kind"] != "entry"]


def _events(sid, run_id, kind):
    return store.list_events(sid, run_id=run_id, kind=kind)


def _assert_still_managed(sid, run_id):
    """Open, linked, priced and exitable: the position is still the run's."""
    run = store.get_run(run_id)
    assert run.stopped_at is None
    strategy = store.get_strategy(sid, USER)
    assert (strategy.status, strategy.current_run_id) == ("running", run_id)
    leg = state.get_run_state(run_id)["legs"]["1"]
    assert (leg["status"], leg["position"], leg["qty"]) == ("open", "S", 75)
    # No exit claim left behind: the stop, the target and the square-off can
    # all still act on this leg.
    assert leg["exit_kind"] is None
    assert leg["exit_claim_token"] is None
    assert leg["exit_order_id"] is None


# ---------------------------------------------------------------------------
# The defect: an exit after a broker switch
# ---------------------------------------------------------------------------


def test_a_stop_after_switching_brokers_sends_nothing_to_the_new_broker(session, broker):
    # The audit's probe, inverted. It used to pass with the cover sent to Fyers.
    sid, run_id = _start()
    assert store.get_run(run_id).broker == "zerodha"
    assert [(s.broker, s.order["action"]) for s in broker] == [("zerodha", "SELL")]

    session.login("fyers", "fyers-token")
    result = engine.stop_run(run_id, USER)

    assert broker[1:] == [], "the cover for a Zerodha short must never reach Fyers"
    assert result["ok"] is False
    assert result["stop_pending"] is True
    assert result["error"] == (
        "OpenAlgo is logged in to Fyers, but this strategy's run trades on Zerodha, so "
        "nothing was sent to Fyers. Log in to Zerodha to manage it."
    )
    # Asked before any exit row is written: nothing pretends an exit was tried.
    assert _exit_rows(run_id) == []
    # The stop stays durable, so it completes once the right broker is back.
    assert store.get_run(run_id).stop_requested_reason == "manual"
    _assert_still_managed(sid, run_id)

    failed = _events(sid, run_id, "run_stop_failed")
    assert len(failed) == 1
    assert failed[0]["severity"] == "critical"
    assert "positions are still open" in failed[0]["message"]
    assert "Log in to Zerodha to manage it." in failed[0]["message"]

    # The scheduler retries a pending stop every few seconds. Still on Fyers,
    # a retry sends nothing, writes no row and does not repeat the notice.
    for _ in range(3):
        retried = engine.reconcile_pending_stop(run_id)
        assert retried["stop_pending"] is True
    assert broker[1:] == []
    assert _exit_rows(run_id) == []
    assert len(_events(sid, run_id, "run_stop_failed")) == 1
    _assert_still_managed(sid, run_id)


def test_a_login_to_another_broker_is_refused_while_a_live_run_trades_elsewhere(session):
    """AUDIT R02 (admission). After a logout no broker session is stored, and
    with no login on record the switch check had nothing to go on, so a login
    to another broker went ahead under a Live run. The run records its broker,
    and that is what holds the switch now."""
    from utils import broker_switch

    _sid, run_id = _start("live")
    session.logout()
    with (
        patch("utils.broker_keys.live_broker", return_value=None),
        patch.object(broker_switch, "previous_broker", return_value=None),
    ):
        other = broker_switch.refusal_for_login("fyers", USER)
        same = broker_switch.refusal_for_login("zerodha", USER)

    assert store.get_run(run_id).broker == "zerodha"
    assert other.startswith("Zerodha still has 1 running Live strategy")
    assert same is None


def test_logging_back_in_to_the_run_broker_with_a_new_token_completes_the_stop(session, broker):
    sid, run_id = _start()
    session.login("fyers", "fyers-token")
    engine.stop_run(run_id, USER)

    # Back on Zerodha with a fresh token, as after the daily re-login.
    session.login("zerodha", "zerodha-token-2")
    result = engine.reconcile_pending_stop(run_id)

    assert result["ok"] is True
    cover = broker[-1]
    assert (cover.broker, cover.token) == ("zerodha", "zerodha-token-2")
    assert (cover.order["action"], cover.order["quantity"]) == ("BUY", "75")
    assert {s.broker for s in broker} == {"zerodha"}
    assert len(_events(sid, run_id, "recovery_succeeded")) == 1


def test_a_stop_on_the_run_broker_cancels_its_working_entry_there(session, broker):
    # An entry the broker accepted but has not filled is cancelled, not
    # reversed, and the cancel and the status read go to the run's broker.
    sid = _make()
    with patch.object(engine, "resolve_leg", return_value=_resolved()):
        run_id = engine.start_run(sid, USER, "live").run_id
    session.login("zerodha", "zerodha-token-2")

    with (
        patch("services.cancel_order_service.import_broker_module") as import_broker,
        patch("services.orderstatus_service.get_order_status") as status,
    ):
        import_broker.return_value.cancel_order.return_value = ({"status": "success"}, 200)
        status.return_value = (
            True,
            {
                "status": "success",
                "data": {
                    "orderid": "LIVE-1",
                    "order_status": "cancelled",
                    "filled_quantity": 0,
                    "average_price": 0,
                },
            },
            200,
        )
        result = engine.stop_run(run_id, USER)

    import_broker.return_value.cancel_order.assert_called_once_with("LIVE-1", "zerodha-token-2")
    status.assert_called_once_with(
        {"orderid": "LIVE-1"}, auth_token="zerodha-token-2", broker="zerodha"
    )
    assert result == {"ok": True, "stop_pending": False, "exits": []}
    assert broker[1:] == []


def test_a_refused_close_releases_its_claim_and_the_leg_can_be_closed_later(session, broker):
    # close_leg has no early check, so this is the dispatch guard on its own.
    sid, run_id = _start()
    session.login("fyers", "fyers-token")

    result = engine.close_leg(run_id, 1, USER)

    assert result["ok"] is False
    assert "Log in to Zerodha to manage it." in result["error"]
    assert broker[1:] == []
    [refused] = _exit_rows(run_id)
    assert refused["status"] == "rejected"
    assert refused["reject_reason"].startswith("OpenAlgo is logged in to Fyers")
    rejected = _events(sid, run_id, "leg_exit_rejected")
    assert any("Log in to Zerodha" in event["message"] for event in rejected)
    _assert_still_managed(sid, run_id)

    session.login("zerodha", "zerodha-token-2")
    assert engine.close_leg(run_id, 1, USER)["ok"] is True
    assert (broker[-1].broker, broker[-1].order["action"]) == ("zerodha", "BUY")


def test_a_stop_hit_while_logged_in_elsewhere_is_reported_once_and_sends_nothing(session, broker):
    # Prices keep arriving from the session that is logged in, so the stop
    # fires on every tick. Each would have been a refused exit row and a
    # critical event; it is one notice instead.
    sid, run_id = _start()
    session.login("fyers", "fyers-token")

    for _ in range(4):
        engine._process_tick_for_run(run_id, SYMBOL, "NFO", 130.0)

    assert broker[1:] == []
    assert _exit_rows(run_id) == []
    [notice] = _events(sid, run_id, "leg_exit_rejected")
    assert notice["severity"] == "critical"
    assert "positions are still open" in notice["message"]
    assert "Log in to Zerodha to manage it." in notice["message"]
    # The breach itself is on the trail once, not once per tick.
    assert len(_events(sid, run_id, "leg_sl_hit")) == 1
    _assert_still_managed(sid, run_id)

    # A quiet tick while still on Fyers does not announce a recovery.
    engine._process_tick_for_run(run_id, SYMBOL, "NFO", 105.0)
    assert _events(sid, run_id, "recovery_succeeded") == []

    session.login("zerodha", "zerodha-token-2")
    engine._process_tick_for_run(run_id, SYMBOL, "NFO", 130.0)

    assert [(s.broker, s.token, s.order["action"]) for s in broker[1:]] == [
        ("zerodha", "zerodha-token-2", "BUY")
    ]
    assert len(_events(sid, run_id, "recovery_succeeded")) == 1


# ---------------------------------------------------------------------------
# Account binding
# ---------------------------------------------------------------------------


def test_another_account_at_the_same_broker_is_refused_when_both_are_known(session, broker):
    session.account = "AB1234"
    sid, run_id = _start()
    assert store.get_run(run_id).broker_account == "AB1234"

    session.login("zerodha", "zerodha-token-2", account="XY9876")
    result = engine.stop_run(run_id, USER)

    assert broker[1:] == []
    assert result["stop_pending"] is True
    assert result["error"] == (
        "OpenAlgo is logged in to Zerodha account XY9876, but this strategy's run trades "
        "on Zerodha account AB1234, so nothing was sent. Log in to Zerodha with account "
        "AB1234 to manage it."
    )
    _assert_still_managed(sid, run_id)

    # The same account again, typed in lower case on the login form this time.
    session.login("zerodha", "zerodha-token-3", account="ab1234")
    assert engine.reconcile_pending_stop(run_id)["ok"] is True
    assert (broker[-1].broker, broker[-1].token) == ("zerodha", "zerodha-token-3")


def test_a_token_refresh_on_the_same_account_keeps_working(session, broker):
    session.account = "AB1234"
    _sid, run_id = _start()

    session.login("zerodha", "zerodha-token-2", account="AB1234")
    result = engine.close_leg(run_id, 1, USER)

    assert result["ok"] is True
    cover = broker[-1]
    assert (cover.broker, cover.token, cover.order["action"]) == (
        "zerodha",
        "zerodha-token-2",
        "BUY",
    )


@pytest.mark.parametrize(("at_start", "now"), [(None, "XY9876"), ("AB1234", None)])
def test_an_account_unknown_on_either_side_binds_by_broker_alone(session, broker, at_start, now):
    # Most brokers' logins name no account. Refusing then would refuse every
    # exit of every run on those brokers.
    session.account = at_start
    _sid, run_id = _start()

    session.login("zerodha", "zerodha-token-2", account=now)

    assert engine.close_leg(run_id, 1, USER)["ok"] is True
    assert broker[-1].broker == "zerodha"


# ---------------------------------------------------------------------------
# Sandbox, signals, and runs that started with no broker
# ---------------------------------------------------------------------------


def test_a_sandbox_run_is_untouched_by_a_broker_switch(session, broker):
    with patch("services.sandbox_service.sandbox_place_order") as sandbox:
        sandbox.return_value = (True, {"status": "success", "orderid": "SB-1"}, 200)
        sid, run_id = _start(mode="sandbox")
        session.login("fyers", "fyers-token")

        result = engine.stop_run(run_id, USER)

    assert result["ok"] is True
    assert [call.args[0]["action"] for call in sandbox.call_args_list] == ["SELL", "BUY"]
    assert broker == []
    run = store.get_run(run_id)
    assert (run.broker, run.broker_account) == ("sandbox", None)
    # The stored broker session is never consulted for a sandbox run.
    session.token_reads.assert_not_called()


def test_a_signal_exit_or_flip_after_switching_brokers_sends_nothing(session, broker):
    created, error = store.create_strategy(
        USER,
        {
            "name": "Signal binding",
            "underlying": "MULTI",
            "underlying_exchange": "NSE",
            "universe_tab": "stocks_fno",
            "strategy_kind": "signal",
            "direction": "both",
            "strategy_type": "positional",
            "product": "MIS",
            "legs": [
                {
                    "id": 1,
                    "symbol": "RELIANCE",
                    "exchange": "NSE",
                    "side": "both",
                    "qty": 100,
                    "segment": "cash",
                    "sl_pts": 20,
                    "trail": {"x": 0, "y": 0},
                }
            ],
        },
    )
    assert error is None, error
    assert store.set_live_enabled(created["id"], USER, True)[0]
    session.account = "AB1234"

    with (
        patch("services.strategy_module.symbol_resolver.contract_exists", return_value=True),
        patch(
            "services.strategy_module.symbol_resolver.resolve_quantity",
            return_value=(100, 1, None),
        ),
    ):
        strategy = store.get_strategy(created["id"], USER)
        entered = signals.handle_signal(strategy, "long_entry", leg_id=1)
        assert entered.ok, entered.error
        run_id = store.get_strategy(created["id"], USER).current_run_id
        run = store.get_run(run_id)
        assert (run.broker, run.broker_account) == ("zerodha", "AB1234")
        engine.apply_fill(run_id, 1, 100.0, is_entry=True)

        session.login("fyers", "fyers-token")
        strategy = store.get_strategy(created["id"], USER)
        exited = signals.handle_signal(strategy, "long_exit", leg_id=1)
        flipped = signals.handle_signal(strategy, "short_entry", leg_id=1)

    assert exited.ok is False
    assert "Log in to Zerodha to manage it." in exited.error
    assert flipped.ok is False
    assert [(s.broker, s.order["action"]) for s in broker] == [("zerodha", "BUY")]
    leg = state.get_run_state(run_id)["legs"]["1"]
    assert (leg["status"], leg["position"]) == ("open", "B")
    assert leg["exit_kind"] is None


def test_a_run_opened_before_any_login_is_bound_by_its_first_live_order(session):
    # A signal run opened before the day's login records its mode, not a broker.
    sid = _make()
    run_id = int(store.create_run(sid, "live", "live").id)

    session.logout()
    unbound = broker_binding.for_run(run_id, api_key=API_KEY, user_id=USER)
    assert unbound.known is False
    assert store.get_run(run_id).broker == "live"

    session.login("zerodha", "zerodha-token", account="AB1234")
    bound = broker_binding.for_run(run_id, api_key=API_KEY, user_id=USER)
    assert (bound.broker, bound.account) == ("zerodha", "AB1234")
    row = store.get_run(run_id)
    assert (row.broker, row.broker_account) == ("zerodha", "AB1234")

    # Bound once. A racing order, or a later session, cannot rebind it.
    assert store.bind_run_broker(run_id, "fyers", None) is False
    session.login("fyers", "fyers-token")
    refusal = broker_binding.refusal_for_run(run_id, api_key=API_KEY, user_id=USER)
    assert refusal is not None and "Log in to Zerodha to manage it." in refusal
    assert store.get_run(run_id).broker == "zerodha"


def test_the_unbound_markers_agree():
    assert set(store.UNBOUND_RUN_BROKERS) == order_dispatch.UNBOUND_BROKERS


# ---------------------------------------------------------------------------
# Cancels and status reads
# ---------------------------------------------------------------------------


def _order():
    return order_dispatch.build_order(
        symbol=SYMBOL,
        exchange="NFO",
        action="BUY",
        quantity=75,
        product="NRML",
        strategy_name="Broker binding",
    )


def test_a_live_cancel_and_status_read_go_only_to_the_run_broker(session):
    session.login("fyers", "fyers-token")
    zerodha = BrokerBinding(broker="zerodha")

    with (
        patch("services.cancel_order_service.import_broker_module") as import_broker,
        patch("services.orderstatus_service.get_order_status") as status,
    ):
        cancelled = order_dispatch.cancel_order(
            mode="live", api_key=API_KEY, broker_order_id="LIVE-1", binding=zerodha
        )
        read = order_dispatch.fetch_order_status(
            mode="live", api_key=API_KEY, broker_order_id="LIVE-1", binding=zerodha
        )

    assert cancelled.ok is False and "Log in to Zerodha" in cancelled.error
    assert read.ok is False and "Log in to Zerodha" in read.error
    import_broker.assert_not_called()
    status.assert_not_called()


def test_a_live_order_with_no_binding_is_not_sent(session, broker):
    # Every caller in the module passes the run's binding; one that forgets is
    # refused rather than sent to whichever broker is logged in.
    result = order_dispatch.dispatch_order(mode="live", api_key=API_KEY, order=_order())

    assert result.ok is False
    assert "could not confirm which broker" in result.error
    assert broker == []


def test_a_missing_session_is_reported_as_that_not_as_a_mismatch(session, broker):
    session.logout()

    result = order_dispatch.dispatch_order(
        mode="live", api_key=API_KEY, order=_order(), binding=BrokerBinding(broker="zerodha")
    )

    assert result.ok is False
    assert "not available or has expired" in result.error
    assert broker == []


def test_a_correction_cancel_is_not_sent_to_another_broker(session, broker):
    sid, run_id = _start()
    retry = store.record_order(
        run_id,
        1,
        "exit_close_all",
        {
            "symbol": SYMBOL,
            "exchange": "NFO",
            "action": "BUY",
            "qty": 75,
            "product": "NRML",
            "pricetype": "MARKET",
            "status": "open",
        },
    )
    assert store.update_order(retry.id, broker_order_id="LIVE-RETRY", status="open")
    session.login("fyers", "fyers-token")

    with patch("services.cancel_order_service.import_broker_module") as import_broker:
        cancelled = order_events._cancel_working_retry(run_id, retry.id)

    assert cancelled is False
    import_broker.assert_not_called()
    notices = [event["message"] for event in _events(sid, run_id, "leg_exit_rejected")]
    assert any(
        "could not be cancelled because OpenAlgo is logged in to Fyers" in message
        and "manage it. Its position remains managed" in message
        for message in notices
    )

    # On the run's broker the same cancel goes through, to that broker.
    session.login("zerodha", "zerodha-token-2")
    with patch("services.cancel_order_service.import_broker_module") as import_broker:
        import_broker.return_value.cancel_order.return_value = ({"status": "success"}, 200)
        assert order_events._cancel_working_retry(run_id, retry.id) is True
    import_broker.assert_called_once_with("zerodha")
    import_broker.return_value.cancel_order.assert_called_once_with("LIVE-RETRY", "zerodha-token-2")


def _sweep(run_id):
    with (
        patch.object(ack_reconciliation, "_next_open_run_ids", return_value=[run_id]),
        patch.object(
            ack_reconciliation,
            "reconcile",
            return_value=ack_reconciliation.AckRepairSummary(working_broker_ids=("LIVE-1",)),
        ),
        patch.object(ack_reconciliation, "_api_key_for", return_value=API_KEY),
        patch("services.orderstatus_service.get_order_status") as status,
    ):
        status.return_value = (False, {"status": "error", "message": "not found"}, 404)
        summary = ack_reconciliation.reconcile_open_runs()
    return summary, status


def test_the_acknowledgement_sweep_reads_status_only_from_the_run_broker(session, broker):
    _sid, run_id = _start()
    session.login("fyers", "fyers-token")

    summary, status = _sweep(run_id)

    status.assert_not_called()
    assert (summary.polled, summary.folded, summary.failed) == (1, 0, 1)

    session.login("zerodha", "zerodha-token-2")
    _summary, status = _sweep(run_id)

    status.assert_called_once_with(
        {"orderid": "LIVE-1"}, auth_token="zerodha-token-2", broker="zerodha"
    )


# ---------------------------------------------------------------------------
# The migration, on a copy of a real database forced back to the old schema
# ---------------------------------------------------------------------------


def _runs(connection):
    return connection.exec_driver_sql(
        "SELECT id, strategy_id, mode, broker, stopped_at FROM sm_strategy_run ORDER BY id"
    ).all()


def test_the_migration_adds_the_account_column_to_an_old_database(tmp_path, capsys, session):
    # The database this suite's store writes, holding a live run, copied with
    # SQLite's own backup so the copy is consistent.
    _sid, run_id = _start()
    source = Path(store.engine.url.database).resolve()
    copy = tmp_path / "before_broker_account.db"
    src, dst = sqlite3.connect(source), sqlite3.connect(copy)
    try:
        src.backup(dst)
        # Forced back to the schema an installation has before this change.
        dst.execute("ALTER TABLE sm_strategy_run DROP COLUMN broker_account")
        dst.commit()
    finally:
        src.close()
        dst.close()

    old = create_db_engine(f"sqlite:///{copy.as_posix()}")
    try:
        names = {column["name"] for column in inspect(old).get_columns("sm_strategy_run")}
        assert "broker_account" not in names
        with old.connect() as connection:
            before = _runs(connection)
        assert any(row.id == run_id and row.broker == "zerodha" for row in before)

        # --status reports it and changes nothing.
        assert migration.status(old) is False
        assert "sm_strategy_run.broker_account" in capsys.readouterr().out
        assert "broker_account" not in {
            column["name"] for column in inspect(old).get_columns("sm_strategy_run")
        }

        assert migration.apply(old) is True
        columns = {column["name"]: column for column in inspect(old).get_columns("sm_strategy_run")}
        assert columns["broker_account"]["nullable"] is True
        with old.connect() as connection:
            assert _runs(connection) == before
            accounts = connection.exec_driver_sql(
                "SELECT DISTINCT broker_account FROM sm_strategy_run"
            ).all()
        # Not derived for rows already there: nothing recorded what it was.
        assert accounts == [(None,)]

        # Idempotent, and reported as up to date afterwards.
        assert migration.apply(old) is True
        assert migration.status(old) is True
    finally:
        old.dispose()
