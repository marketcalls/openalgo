"""Boot recovery for strategy runs, and the checkpoint writer that feeds it.

The engine keeps a run in an in-process dict, so a crash takes every live run
with it while the positions are still at the broker. What is tested here is
what comes back: which facts are taken from the order rows, which from the
newest checkpoint, what a run with no checkpoint at all can still reconstruct,
and what happens to a run that cannot be rebuilt at all.

The checkpoint writer is driven by calling its pass function directly. Waiting
on the loop would test the sleep, not the write.
"""

import time

import pytest

from database import strategy_module_db as store
from services.strategy_module import checkpoint, recovery, state

USER = "recovery_test_user"
CE = "NIFTY28MAY2624000CE"
PE = "NIFTY28MAY2624000PE"


def _leg(leg_id=1, position="S", sl_pts=20):
    return {
        "id": leg_id,
        "segment": "options",
        "expiry": "weekly",
        "lots": 1,
        "position": position,
        "option_type": "CE",
        "strike_mode": "atm",
        "atm_offset": "ATM",
        "sl_pts": sl_pts,
        "trail": {"x": 0, "y": 0},
    }


def _config(name="Recovery test", legs=None, **overrides):
    config = {
        "name": name,
        "underlying": "NIFTY",
        "underlying_exchange": "NSE_INDEX",
        "universe_tab": "weekly_monthly",
        "product": "NRML",
        "legs": legs if legs is not None else [_leg()],
    }
    config.update(overrides)
    return config


@pytest.fixture(autouse=True)
def clean_slate():
    store.init_db()

    def purge():
        for run_id in state.active_run_ids():
            state.clear_run_state(run_id)
        for row in store.list_strategies(USER):
            # Force to stopped first: delete refuses while a strategy is running.
            store.set_strategy_status(row["id"], "stopped", None)
            store.delete_strategy(row["id"], USER)
        # recover_all() is global by design, so an open run another suite left
        # behind after a failure would be recovered by these tests and would
        # show up in their results. Close them before starting.
        for run in store.list_open_runs():
            store.finish_run(run.id, "error")
        store.clear_strategy_module_cache()

    purge()
    yield
    purge()


# ---------------------------------------------------------------------------
# Fixture builders: the store is real, so these write actual rows.
# ---------------------------------------------------------------------------


def _strategy(name="Recovery test", legs=None, **overrides):
    created, error = store.create_strategy(USER, _config(name, legs, **overrides))
    assert error is None, error
    return created["id"]


def _run(strategy_id):
    run = store.create_run(strategy_id, "sandbox", "sandbox")
    assert run is not None
    run_id = run.id
    store.set_strategy_status(strategy_id, "running", run_id)
    return run_id


def _order(
    run_id,
    leg_id=1,
    kind="entry",
    action="SELL",
    symbol=CE,
    qty=75,
    status="complete",
    avg=None,
):
    row = store.record_order(
        run_id,
        leg_id,
        kind,
        {
            "symbol": symbol,
            "exchange": "NFO",
            "action": action,
            "qty": qty,
            "pricetype": "MARKET",
            "status": "open",
        },
    )
    assert row is not None
    store.update_order(row.id, status=status, avg_fill_price=avg)
    return row.id


def _cp_leg(leg_id=1, **overrides):
    """One leg exactly as state.snapshot_for_checkpoint would have stored it."""
    leg = {
        "leg_id": leg_id,
        "position": "S",
        "symbol": CE,
        "exchange": "NFO",
        "lots": 1,
        "qty": 75,
        "entry_order_id": None,
        "entry_status": "complete",
        "entry_avg": 100.0,
        "exit_order_id": None,
        "exit_kind": None,
        "exit_avg": None,
        "ltp": 95.0,
        "mtm": 375.0,
        "realized_pnl": 0.0,
        "status": "open",
        "tick_source": "ws",
        "sl_pts": 20,
        "target_pts": None,
        "trail_x": 0,
        "trail_y": 0,
        "effective_sl": None,
        "effective_target": None,
        "trail_active": False,
        "highest_price": None,
        "lowest_price": None,
    }
    leg.update(overrides)
    return leg


def _checkpoint(run_id, leg_state, **run_level):
    snapshot = {
        "pnl_realized": 0.0,
        "pnl_unrealized": 0.0,
        "pnl_total": 0.0,
        "pnl_peak": 0.0,
        "pnl_trough": 0.0,
        "lock_floor": None,
        "trail_to_entry_active": False,
        "leg_state": leg_state,
    }
    snapshot.update(run_level)
    assert store.write_checkpoint(run_id, snapshot) is True


# ---------------------------------------------------------------------------
# Orders against checkpoint
# ---------------------------------------------------------------------------


def test_a_run_takes_fill_facts_from_its_orders_and_risk_state_from_its_checkpoint():
    # The checkpoint below is deliberately wrong about everything the order
    # rows know: a stale symbol, the wrong quantity, the wrong entry price and
    # the wrong side. Those are the facts the orders own.
    sid = _strategy()
    run_id = _run(sid)
    _order(run_id, 1, "entry", action="SELL", status="complete", avg=100.0)
    _checkpoint(
        run_id,
        {
            "1": _cp_leg(
                symbol="A-DIFFERENT-STRIKE",
                qty=1,
                entry_avg=999.0,
                position="B",
                ltp=95.0,
                effective_sl=120.0,
                effective_target=60.0,
                lowest_price=92.0,
                trail_active=True,
            )
        },
        pnl_peak=375.0,
        pnl_trough=-150.0,
        lock_floor=200.0,
        trail_to_entry_active=True,
    )

    resumed = recovery.recover_all()

    assert resumed[run_id] == {(CE, "NFO")}
    live = state.get_run_state(run_id)
    leg = live["legs"]["1"]

    # Identity and fill facts: the order rows.
    assert leg["symbol"] == CE
    assert leg["exchange"] == "NFO"
    assert leg["qty"] == 75
    assert leg["position"] == "S"
    assert leg["entry_avg"] == 100.0
    assert leg["entry_status"] == "complete"
    assert leg["status"] == "open"

    # Volatile risk state: the checkpoint, because nothing else records it.
    assert leg["ltp"] == 95.0
    assert leg["effective_sl"] == 120.0
    assert leg["effective_target"] == 60.0
    assert leg["lowest_price"] == 92.0
    assert leg["trail_active"] is True

    # Run aggregates: the checkpoint too.
    assert live["pnl_peak"] == 375.0
    assert live["pnl_trough"] == -150.0
    assert live["lock_floor"] == 200.0
    assert live["lock_armed"] is True
    assert live["trail_to_entry_active"] is True


def test_a_run_with_no_checkpoint_recovers_from_its_orders_alone():
    # A run that died within seconds of starting has no snapshot at all. The
    # book is still fully knowable; only the risk levels have to be re-derived,
    # which the next tick does from the configured points.
    sid = _strategy()
    run_id = _run(sid)
    _order(run_id, 1, "entry", action="SELL", status="complete", avg=100.0)
    assert store.latest_checkpoint(run_id) is None

    resumed = recovery.recover_all()

    assert resumed[run_id] == {(CE, "NFO")}
    leg = state.get_run_state(run_id)["legs"]["1"]
    assert leg["status"] == "open"
    assert leg["position"] == "S"
    assert leg["entry_avg"] == 100.0
    # Nothing volatile survived, and nothing pretends it did.
    assert leg["ltp"] is None
    assert leg["effective_sl"] is None
    assert leg["highest_price"] is None
    assert leg["lowest_price"] is None
    # The configured stop is back from the strategy, so the level re-derives.
    assert leg["sl_pts"] == 20


def test_the_checkpoint_may_witness_a_fill_the_order_row_has_not_caught_up_with():
    # The checkpoint is written from the same fill engine.apply_fill applies to
    # live state, so it can see a fill before the row is updated. That upgrade
    # is the one direction it is allowed to move a fill fact.
    sid = _strategy()
    run_id = _run(sid)
    _order(run_id, 1, "entry", action="SELL", status="open", avg=None)
    _checkpoint(run_id, {"1": _cp_leg(entry_status="complete", entry_avg=100.0, status="open")})

    recovery.recover_all()

    leg = state.get_run_state(run_id)["legs"]["1"]
    assert leg["status"] == "open"
    assert leg["entry_avg"] == 100.0


def test_a_rejected_entry_is_never_upgraded_by_a_checkpoint():
    # The other direction. An entry the broker refused is a leg holding
    # nothing, and no snapshot may say otherwise. Leg 2 filled, so the run
    # itself stays live and the rejected leg can be inspected.
    sid = _strategy(legs=[_leg(1, "S"), _leg(2, "S")])
    run_id = _run(sid)
    _order(run_id, 1, "entry", action="SELL", symbol=CE, status="rejected")
    _order(run_id, 2, "entry", action="SELL", symbol=PE, status="complete", avg=50.0)
    _checkpoint(
        run_id,
        {
            "1": _cp_leg(1, symbol=CE, entry_status="complete", entry_avg=100.0, status="open"),
            "2": _cp_leg(2, symbol=PE, entry_avg=50.0),
        },
    )

    resumed = recovery.recover_all()

    leg = state.get_run_state(run_id)["legs"]["1"]
    assert leg["status"] == "rejected"
    assert leg["entry_avg"] == 0.0
    # It holds nothing, so it is not worth a subscription either.
    assert resumed[run_id] == {(PE, "NFO")}


def test_an_entry_still_working_holds_nothing_yet_but_is_still_watched():
    sid = _strategy()
    run_id = _run(sid)
    _order(run_id, 1, "entry", action="SELL", status="open")

    resumed = recovery.recover_all()

    leg = state.get_run_state(run_id)["legs"]["1"]
    # Not open: a rule must not be able to exit a position that does not exist,
    # and an unfilled leg must not be marked from an entry price of zero.
    assert leg["status"] == "configured"
    assert leg["entry_avg"] == 0.0
    # Still subscribed, so the fill is priced the moment it lands.
    assert resumed[run_id] == {(CE, "NFO")}


# ---------------------------------------------------------------------------
# Exits
# ---------------------------------------------------------------------------


def test_a_leg_whose_exit_already_filled_comes_back_closed_and_is_not_resubscribed():
    sid = _strategy(legs=[_leg(1, "S"), _leg(2, "S")])
    run_id = _run(sid)
    _order(run_id, 1, "entry", action="SELL", symbol=CE, status="complete", avg=100.0)
    _order(run_id, 1, "exit_sl", action="BUY", symbol=CE, status="complete", avg=80.0)
    _order(run_id, 2, "entry", action="SELL", symbol=PE, status="complete", avg=50.0)

    resumed = recovery.recover_all()

    legs = state.get_run_state(run_id)["legs"]
    assert legs["1"]["status"] == "closed"
    assert legs["1"]["exit_avg"] == 80.0
    assert legs["1"]["exit_kind"] == "exit_sl"
    # Short covered 20 points lower: a profit, derived from the two fills
    # because the run never checkpointed after the exit.
    assert legs["1"]["realized_pnl"] == pytest.approx((80.0 - 100.0) * 75 * -1)
    assert legs["2"]["status"] == "open"
    # Only the leg still held is worth a subscription.
    assert resumed[run_id] == {(PE, "NFO")}


def test_a_rejected_exit_leaves_the_leg_open_and_the_exit_retryable():
    # If a failed exit came back looking like one in flight, the engine's
    # duplicate-exit guard would refuse to try again and strand the position.
    sid = _strategy()
    run_id = _run(sid)
    _order(run_id, 1, "entry", action="SELL", status="complete", avg=100.0)
    _order(run_id, 1, "exit_sl", action="BUY", status="rejected")

    recovery.recover_all()

    leg = state.get_run_state(run_id)["legs"]["1"]
    assert leg["status"] == "open"
    assert leg["exit_order_id"] is None
    assert leg["exit_kind"] is None


def test_an_exit_in_flight_comes_back_marked_so_it_is_not_sent_twice():
    sid = _strategy()
    run_id = _run(sid)
    _order(run_id, 1, "entry", action="SELL", status="complete", avg=100.0)
    exit_id = _order(run_id, 1, "exit_sl", action="BUY", status="trigger pending")

    recovery.recover_all()

    leg = state.get_run_state(run_id)["legs"]["1"]
    assert leg["status"] == "open"
    assert leg["exit_order_id"] == exit_id
    assert leg["exit_kind"] == "exit_sl"


def test_a_run_whose_every_leg_has_closed_is_finished_rather_than_left_running():
    # The process died between the last exit fill and the finalise it would
    # have triggered. Resuming it would leave a strategy reading as running
    # while holding nothing, and no tick would ever arrive to close it.
    sid = _strategy()
    run_id = _run(sid)
    _order(run_id, 1, "entry", action="SELL", status="complete", avg=100.0)
    _order(run_id, 1, "exit_sl", action="BUY", status="complete", avg=80.0)

    resumed = recovery.recover_all()

    assert run_id not in resumed
    run = store.list_runs(sid)[0]
    assert run["stopped_at"] is not None
    assert run["pnl_realized"] == pytest.approx(1500.0)
    assert store.get_strategy(sid, USER).status == "stopped"
    assert state.get_run_state(run_id) is None


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------


def test_every_recovered_leg_carries_a_position():
    # A leg with no side is evaluated as a short by the risk core, which
    # silently inverts its P&L, its stop and its target. The checkpoint here
    # has lost the side entirely; the action that opened the leg supplies it.
    sid = _strategy(legs=[_leg(1, "S"), _leg(2, "B")])
    run_id = _run(sid)
    _order(run_id, 1, "entry", action="SELL", symbol=CE, status="complete", avg=100.0)
    _order(run_id, 2, "entry", action="BUY", symbol=PE, status="complete", avg=50.0)
    _checkpoint(
        run_id,
        {
            "1": _cp_leg(1, position=None, symbol=CE),
            "2": _cp_leg(2, position=None, symbol=PE, entry_avg=50.0),
        },
    )

    recovery.recover_all()

    legs = state.get_run_state(run_id)["legs"]
    assert all(leg["position"] in ("B", "S") for leg in legs.values())
    assert legs["1"]["position"] == "S"
    assert legs["2"]["position"] == "B"


@pytest.mark.parametrize("status", ["submitted", "trigger_pending", "TRIGGER PENDING", "modified"])
def test_a_working_broker_status_reads_the_same_way_everywhere(status):
    # PORTED DEFECT. The original normalises broker statuses in two separate
    # functions that disagree on exactly these three: one counts them as live
    # orders, the other writes them off as unknown and therefore dead. The same
    # row could then be read as holding a position or holding nothing.
    assert recovery.order_is_working(status) is True
    assert recovery.order_is_filled(status) is False
    assert recovery.order_is_dead(status) is False


def test_an_unrecognised_status_is_read_as_working_rather_than_dead():
    # Writing an unknown exit off as dead would let a second exit be placed
    # against a position already on its way out, and a second exit does not
    # close a position twice: it opens the opposite one.
    assert recovery.normalise_order_status("some-new-broker-word") == "open"
    assert recovery.order_is_dead("some-new-broker-word") is False


# ---------------------------------------------------------------------------
# Failure and idempotence
# ---------------------------------------------------------------------------


def test_a_run_that_cannot_be_recovered_is_finalised_rather_than_wedging_the_boot():
    # One unrecoverable run must not cost every other run its recovery, on this
    # boot or on any future one.
    bad_sid = _strategy(name="Recovery test bad")
    bad_run = _run(bad_sid)
    # An action that is neither BUY nor SELL leaves the leg with no side.
    _order(bad_run, 1, "entry", action="HOLD", status="complete", avg=100.0)

    good_sid = _strategy(name="Recovery test good")
    good_run = _run(good_sid)
    _order(good_run, 1, "entry", action="SELL", symbol=PE, status="complete", avg=100.0)

    resumed = recovery.recover_all()

    assert bad_run not in resumed
    assert resumed[good_run] == {(PE, "NFO")}

    closed = store.list_runs(bad_sid)[0]
    assert closed["stop_reason"] == "recovery_failed"
    assert closed["stopped_at"] is not None
    assert store.get_strategy(bad_sid, USER).status == "stopped"
    assert state.get_run_state(bad_run) is None
    assert "recovery_failed" in [event["kind"] for event in store.list_events(bad_sid)]


def test_recovering_twice_does_not_overwrite_live_state():
    # A second call, or a recovery racing a run that started normally, must not
    # replace live state with an older snapshot of it.
    sid = _strategy()
    run_id = _run(sid)
    _order(run_id, 1, "entry", action="SELL", status="complete", avg=100.0)
    recovery.recover_all()

    with state.run_state(run_id) as run:
        run["legs"]["1"]["ltp"] = 42.0

    resumed = recovery.recover_all()

    assert resumed[run_id] == {(CE, "NFO")}
    assert state.get_run_state(run_id)["legs"]["1"]["ltp"] == 42.0


# ---------------------------------------------------------------------------
# The checkpoint writer
# ---------------------------------------------------------------------------


def _live_run(name="Checkpoint test"):
    """A strategy, an open run and one live leg in state."""
    sid = _strategy(name=name)
    run_id = _run(sid)
    state.init_run_state(
        run_id,
        sid,
        [
            {
                "leg_id": 1,
                "position": "S",
                "symbol": CE,
                "exchange": "NFO",
                "quantity": 75,
                "sl_pts": 20,
            }
        ],
    )
    return sid, run_id


def test_the_checkpoint_writer_prunes_while_leaving_the_newest_row_intact(monkeypatch):
    # A row per run every few seconds for a session is thousands of rows per
    # run in a worker that never restarts. Recovery only ever reads the newest,
    # which is the one row a prune can never remove.
    _sid, run_id = _live_run()
    monkeypatch.setattr(checkpoint, "CHECKPOINT_KEEP", 3)

    for total in range(1, 7):
        with state.run_state(run_id) as run:
            run["pnl_total"] = float(total)
        assert checkpoint.write_once(prune=False) == 1
        # Only so the rows carry distinct timestamps; the writer itself is
        # never waited on.
        time.sleep(0.005)

    assert len(store.list_checkpoints(run_id)) == 6

    with state.run_state(run_id) as run:
        run["pnl_total"] = 99.0
    checkpoint.write_once(prune=True)

    assert len(store.list_checkpoints(run_id)) == 3
    newest = store.latest_checkpoint(run_id)
    assert newest["pnl_total"] == 99.0
    assert newest["leg_state"]["1"]["symbol"] == CE


def test_a_checkpoint_that_cannot_be_written_does_not_cost_the_other_runs_theirs(monkeypatch):
    _sid_a, run_a = _live_run(name="Checkpoint test A")
    _sid_b, run_b = _live_run(name="Checkpoint test B")
    real_write = store.write_checkpoint
    seen = []

    def flaky(run_id, snapshot):
        seen.append(run_id)
        if run_id == run_a:
            raise RuntimeError("disk went away")
        return real_write(run_id, snapshot)

    monkeypatch.setattr(store, "write_checkpoint", flaky)

    written = checkpoint.write_once(prune=False)

    assert set(seen) == {run_a, run_b}
    assert written == 1
    assert store.latest_checkpoint(run_a) is None
    assert store.latest_checkpoint(run_b) is not None


def test_a_pass_snapshots_every_live_run_in_the_shape_recovery_reads_back():
    _sid, run_id = _live_run()
    with state.run_state(run_id) as run:
        run["pnl_total"] = 375.0
        run["legs"]["1"]["entry_avg"] = 100.0
        run["legs"]["1"]["ltp"] = 95.0

    assert checkpoint.write_once(prune=False) == 1

    snapshot = store.latest_checkpoint(run_id)
    assert snapshot["pnl_total"] == 375.0
    assert snapshot["leg_state"]["1"]["entry_avg"] == 100.0
    assert snapshot["leg_state"]["1"]["ltp"] == 95.0
    assert snapshot["leg_state"]["1"]["position"] == "S"


def test_the_writer_starts_only_when_it_is_asked_to():
    # Two modules in this codebase start a scheduler as an import side effect,
    # which means any tool that imports the app spins up live background work.
    # Importing this one does nothing at all.
    assert checkpoint.is_running() is False

    assert checkpoint.start() is True
    try:
        assert checkpoint.is_running() is True
        # Idempotent, so a caller need not know whether it is already up.
        assert checkpoint.start() is False
    finally:
        checkpoint.stop()

    assert checkpoint.is_running() is False
    # Also idempotent on the way down.
    checkpoint.stop()
