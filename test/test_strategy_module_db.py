"""Strategy-module persistence behaviour.

The blueprint layer is thin, so the contract worth pinning is the store's: what
it does with a duplicate name, a token that has been rotated, a PATCH carrying
fields it must not accept, an edit attempted while a run is live, and a
checkpoint table that would otherwise grow all session.

These run against the configured database, like test_watchlist_db.py, and each
test starts and ends with no rows for either test user.
"""

from datetime import UTC, datetime, timedelta

import pytest

from database import strategy_module_db as sm

USER = "sm_test_user"
OTHER = "sm_other_user"
ORDER = {
    "symbol": "NIFTY28MAY2624000CE",
    "exchange": "NFO",
    "action": "SELL",
    "qty": 75,
}


def _config(name="Iron condor weekly", **overrides):
    """A minimal valid strategy config, overridable per test."""
    config = {
        "name": name,
        "underlying": "NIFTY",
        "underlying_exchange": "NSE_INDEX",
        "universe_tab": "weekly_monthly",
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


def _run():
    """Create a minimal run for persistence-focused tests."""
    strategy, error = sm.create_strategy(USER, _config())
    assert error is None
    return sm.create_run(strategy["id"], "sandbox", "zerodha")


def _filled_order(
    run_id,
    leg_id,
    kind,
    action,
    *,
    requested_qty,
    status,
    avg_price,
    filled_qty,
    position_ref="auto",
    placed_at=None,
):
    """Persist one literal broker fill fact for reconciliation tests."""
    row = sm.record_order(
        run_id,
        leg_id,
        kind,
        {
            **ORDER,
            "action": action,
            "qty": requested_qty,
            "position_ref": (
                f"position-{leg_id}" if position_ref == "auto" else position_ref
            ),
            "status": "open",
        },
    )
    assert row is not None
    assert sm.update_order(
        row.id,
        status=status,
        avg_fill_price=avg_price,
        filled_qty=filled_qty,
    )
    if placed_at is not None:
        row.placed_at = placed_at
        sm.db_session.commit()
    return row


@pytest.fixture(autouse=True)
def clean_slate():
    # Start from a clean session; see the note in
    # test_strategy_module_engine.py about the shared identity map.
    sm.db_session.remove()
    sm.init_db()

    def purge():
        for user in (USER, OTHER):
            for row in sm.list_strategies(user):
                # Force to stopped first: delete refuses while running, and a
                # test that left one running would poison every later test.
                sm.set_strategy_status(row["id"], "stopped", None)
                sm.delete_strategy(row["id"], user)
        sm.clear_strategy_module_cache()

    purge()
    yield
    purge()


# ---------------------------------------------------------------------------
# Creation and the webhook token
# ---------------------------------------------------------------------------


def test_create_returns_the_strategy_and_list_reads_it_back():
    created, error = sm.create_strategy(USER, _config())

    assert error is None
    assert created["name"] == "Iron condor weekly"
    assert created["status"] == "stopped"
    assert [row["name"] for row in sm.list_strategies(USER)] == ["Iron condor weekly"]


def test_a_new_strategy_is_sandbox_only_until_explicitly_enabled():
    # The whole point of the opt-in: a strategy discovered to be misconfigured
    # cannot have been placing real orders in the meantime.
    created, _ = sm.create_strategy(USER, _config())

    assert created["live_enabled"] is False


def test_the_webhook_token_is_returned_once_and_never_again():
    created, _ = sm.create_strategy(USER, _config())
    token = created["webhook_token"]

    assert token.startswith(sm.WEBHOOK_TOKEN_PREFIX)

    # Every later read of the same strategy must not carry it, because only
    # the hash was stored and the plaintext is unrecoverable by design.
    row = sm.get_strategy(created["id"], USER)
    assert "webhook_token" not in sm.strategy_to_dict(row)
    assert token not in str(sm.strategy_to_dict(row))


def test_the_token_resolves_to_its_strategy_and_a_wrong_one_does_not():
    created, _ = sm.create_strategy(USER, _config())
    token = created["webhook_token"]

    assert sm.get_strategy_by_webhook_token(token).id == created["id"]
    assert sm.get_strategy_by_webhook_token("oaws_not-a-real-token") is None


def test_rotating_the_token_invalidates_the_old_one_immediately():
    created, _ = sm.create_strategy(USER, _config())
    old = created["webhook_token"]
    # Resolve once so the old digest is definitely in the lookup cache; the
    # bug this guards against is a rotated token that keeps working until the
    # cache entry happens to expire.
    assert sm.get_strategy_by_webhook_token(old) is not None

    new, error = sm.rotate_webhook_token(created["id"], USER)

    assert error is None
    assert new != old
    assert sm.get_strategy_by_webhook_token(old) is None
    assert sm.get_strategy_by_webhook_token(new).id == created["id"]


def test_deleting_a_strategy_stops_its_token_resolving():
    created, _ = sm.create_strategy(USER, _config())
    token = created["webhook_token"]
    assert sm.get_strategy_by_webhook_token(token) is not None

    sm.delete_strategy(created["id"], USER)

    assert sm.get_strategy_by_webhook_token(token) is None


def test_duplicate_name_is_refused_rather_than_creating_a_second():
    sm.create_strategy(USER, _config())

    created, error = sm.create_strategy(USER, _config())

    assert created is None
    assert "already exists" in error
    assert len(sm.list_strategies(USER)) == 1


def test_the_same_name_is_free_for_a_different_user():
    sm.create_strategy(USER, _config())

    created, error = sm.create_strategy(OTHER, _config())

    assert error is None
    assert created is not None


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------


def test_another_user_cannot_read_update_or_delete_a_strategy():
    created, _ = sm.create_strategy(USER, _config())
    sid = created["id"]

    assert sm.get_strategy(sid, OTHER) is None

    _, update_error = sm.update_strategy(sid, OTHER, {"name": "hijacked"})
    assert update_error == "Strategy not found"

    deleted, delete_error = sm.delete_strategy(sid, OTHER)
    assert deleted is False
    assert delete_error == "Strategy not found"

    # And the row is genuinely untouched.
    assert sm.get_strategy(sid, USER).name == "Iron condor weekly"


# ---------------------------------------------------------------------------
# Update guards
# ---------------------------------------------------------------------------


def test_patch_ignores_fields_outside_the_allowlist():
    # Mass assignment is the whole reason UPDATABLE_FIELDS exists: without it a
    # caller could set its own webhook_token_hash and mint a working token.
    created, _ = sm.create_strategy(USER, _config())
    sid = created["id"]
    before = sm.get_strategy(sid, USER)
    original_hash = before.webhook_token_hash

    sm.update_strategy(
        sid,
        USER,
        {
            "name": "Renamed",
            "webhook_token_hash": "a" * 64,
            "user_id": OTHER,
            "current_run_id": 999,
            "live_enabled": True,
            "status": "running",
        },
    )

    after = sm.get_strategy(sid, USER)
    assert after.name == "Renamed"
    assert after.webhook_token_hash == original_hash
    assert after.user_id == USER
    assert after.current_run_id is None
    assert after.live_enabled is False
    assert after.status == "stopped"


def test_deleting_a_strategy_takes_its_runs_orders_events_and_checkpoints_with_it():
    # ondelete="CASCADE" is declarative only here: SQLite enforces a foreign
    # key only under PRAGMA foreign_keys=ON, which this project never sets. If
    # the store leaned on the cascade, every delete would strand the whole
    # audit trail where no query can reach it and nothing can clean it up.
    created, _ = sm.create_strategy(USER, _config())
    sid = created["id"]
    # Read the id out before the delete: the row itself is gone afterwards, and
    # touching the expired ORM object would raise rather than answer.
    run_id = sm.create_run(sid, "sandbox", "zerodha").id
    sm.record_order(
        run_id,
        leg_id=1,
        kind="entry",
        order={"symbol": "NIFTY28MAY2624000CE", "exchange": "NFO", "action": "SELL", "qty": 75},
    )
    sm.record_event(sid, USER, "run_started", "Run started", run_id=run_id)
    sm.write_checkpoint(run_id, {"pnl_total": 10, "leg_state": {}})
    sm.record_webhook_event("ok", strategy_id=sid, action="start", mode="sandbox")

    assert sm.list_orders(run_id) and sm.list_events(sid)
    assert sm.list_checkpoints(run_id) and sm.list_webhook_events(sid)

    deleted, error = sm.delete_strategy(sid, USER)
    assert deleted is True and error is None

    assert sm.list_runs(sid) == []
    assert sm.list_orders(run_id) == []
    assert sm.list_events(sid) == []
    assert sm.list_checkpoints(run_id) == []
    assert sm.list_webhook_events(sid) == []
    assert sm.get_run(run_id) is None


def test_a_running_strategy_cannot_be_edited_or_deleted():
    created, _ = sm.create_strategy(USER, _config())
    sid = created["id"]
    sm.set_strategy_status(sid, "running", 1)

    _, update_error = sm.update_strategy(sid, USER, {"name": "Renamed"})
    assert "Stop the strategy" in update_error

    deleted, delete_error = sm.delete_strategy(sid, USER)
    assert deleted is False
    assert "Stop the strategy" in delete_error


def test_live_mode_cannot_be_flipped_while_a_run_is_active():
    created, _ = sm.create_strategy(USER, _config())
    sid = created["id"]
    sm.set_strategy_status(sid, "running", 1)

    ok, error = sm.set_live_enabled(sid, USER, True)

    assert ok is False
    assert "Stop the strategy" in error
    assert sm.get_strategy(sid, USER).live_enabled is False


def test_the_kill_switch_can_be_engaged_while_running():
    # Deliberately unlike the guards above: a kill switch that refused to
    # engage on a running strategy would be useless exactly when it is needed.
    created, _ = sm.create_strategy(USER, _config())
    sid = created["id"]
    sm.set_strategy_status(sid, "running", 1)

    ok, error = sm.set_webhook_locked(sid, USER, True)

    assert ok is True
    assert error is None
    assert sm.get_strategy(sid, USER).webhook_locked is True


# ---------------------------------------------------------------------------
# Runs, orders and events
# ---------------------------------------------------------------------------


def test_order_round_trip_preserves_position_ref():
    run = _run()

    row = sm.record_order(run.id, 1, "entry", {**ORDER, "position_ref": "pos-a"})

    assert sm.order_to_dict(row)["position_ref"] == "pos-a"


def test_request_run_stop_is_pending_until_finish():
    run = _run()

    assert sm.request_run_stop(run.id, "manual")

    pending = sm.run_to_dict(sm.get_run(run.id))
    assert pending["stopped_at"] is None
    assert pending["stop_requested_reason"] == "manual"
    assert pending["stop_requested_at"] is not None

    sm.finish_run(run.id, "manual")

    complete = sm.run_to_dict(sm.get_run(run.id))
    assert complete["stop_reason"] == "manual"
    assert complete["stop_requested_reason"] is None


def test_finish_and_release_is_one_atomic_owner_checked_transition():
    created, error = sm.create_strategy(USER, _config())
    assert error is None
    run = sm.create_run(created["id"], "sandbox", "zerodha")
    assert sm.set_strategy_status(created["id"], "running", run.id)

    won = sm.finish_run_and_release_strategy(
        run.id,
        created["id"],
        "manual",
        pnl_realized=125.0,
        pnl_peak=150.0,
        pnl_trough=-10.0,
    )

    assert won is True
    durable = sm.get_run(run.id)
    assert durable.stopped_at is not None
    assert float(durable.pnl_realized) == pytest.approx(125.0)
    strategy = sm.get_strategy(created["id"], USER)
    assert strategy.status == "stopped"
    assert strategy.current_run_id is None

    # The run and strategy have one terminal owner. A duplicate finalizer
    # loses without changing either row a second time.
    assert sm.finish_run_and_release_strategy(run.id, created["id"], "manual") is False


def test_finish_and_release_rolls_back_run_when_strategy_owns_a_different_run():
    created, error = sm.create_strategy(USER, _config())
    assert error is None
    first = sm.create_run(created["id"], "sandbox", "zerodha")
    current = sm.create_run(created["id"], "sandbox", "zerodha")
    assert sm.set_strategy_status(created["id"], "running", current.id)

    won = sm.finish_run_and_release_strategy(first.id, created["id"], "manual")

    assert won is False
    assert sm.get_run(first.id).stopped_at is None
    strategy = sm.get_strategy(created["id"], USER)
    assert strategy.status == "running"
    assert strategy.current_run_id == current.id


def test_detached_finish_cannot_close_current_but_can_close_an_older_residual():
    created, error = sm.create_strategy(USER, _config())
    assert error is None
    residual = sm.create_run(created["id"], "sandbox", "zerodha")
    current = sm.create_run(created["id"], "sandbox", "zerodha")
    assert residual is not None and current is not None
    residual_id = residual.id
    current_id = current.id
    assert sm.set_strategy_status(created["id"], "running", current_id)

    assert sm.finish_detached_run(current_id, created["id"], "manual") is False
    assert sm.get_run(current_id).stopped_at is None

    assert sm.finish_detached_run(
        residual_id,
        created["id"],
        "manual",
        pnl_realized=75.0,
    ) is True
    assert sm.get_run(residual_id).stopped_at is not None
    assert float(sm.get_run(residual_id).pnl_realized) == pytest.approx(75.0)
    strategy = sm.get_strategy(created["id"], USER)
    assert strategy.current_run_id == current_id
    assert strategy.status == "running"


def test_unlinked_run_cleanup_releases_only_an_unlinked_strategy_claim():
    created, error = sm.create_strategy(USER, _config())
    assert error is None
    strategy_id = created["id"]
    assert sm.claim_strategy_for_run(strategy_id)
    run = sm.create_run(strategy_id, "sandbox", "zerodha")
    assert run is not None
    run_id = run.id

    assert sm.finish_unlinked_run_and_release_claim(run_id, strategy_id, "error") is True
    assert sm.get_run(run_id).stopped_at is not None
    strategy = sm.get_strategy(strategy_id, USER)
    assert strategy.status == "stopped"
    assert strategy.current_run_id is None

    # A stale cleanup can close its own detached row, but it must not release
    # a newer run that has since acquired exact strategy ownership.
    assert sm.claim_strategy_for_run(strategy_id)
    stale = sm.create_run(strategy_id, "sandbox", "zerodha")
    current = sm.create_run(strategy_id, "sandbox", "zerodha")
    assert stale is not None and current is not None
    stale_id = stale.id
    current_id = current.id
    assert sm.set_strategy_status(strategy_id, "running", current_id)

    assert sm.finish_unlinked_run_and_release_claim(stale_id, strategy_id, "error") is False
    assert sm.get_run(stale_id).stopped_at is not None
    assert sm.get_run(current_id).stopped_at is None
    strategy = sm.get_strategy(strategy_id, USER)
    assert strategy.status == "running"
    assert strategy.current_run_id == current_id


def test_ack_binding_is_idempotent_and_refuses_target_or_broker_id_conflicts():
    run = _run()
    target = sm.record_order(run.id, 1, "entry", {**ORDER, "status": "pending"})
    other = sm.record_order(
        run.id,
        2,
        "entry",
        {**ORDER, "symbol": "NIFTY28MAY2624100CE", "status": "pending"},
    )
    assert target is not None and other is not None

    assert (
        sm.bind_order_acknowledgement(
            target.id,
            run.id,
            1,
            broker_order_id="ACK-EXACT",
            status="open",
            reject_reason=None,
        )
        == "repaired"
    )
    assert (
        sm.bind_order_acknowledgement(
            target.id,
            run.id,
            1,
            broker_order_id="ACK-EXACT",
            status="open",
            reject_reason=None,
        )
        == "already_bound"
    )

    # Exact target row already owns another broker id: never overwrite it.
    assert (
        sm.bind_order_acknowledgement(
            target.id,
            run.id,
            1,
            broker_order_id="ACK-CONFLICT",
            status="open",
            reject_reason=None,
        )
        == "conflict"
    )
    assert sm.get_order(target.id).broker_order_id == "ACK-EXACT"

    # A later terminal fact is stronger and must not be reopened by replaying
    # the original accepted acknowledgement event.
    assert sm.update_order(target.id, status="complete", filled_qty=75)
    assert (
        sm.bind_order_acknowledgement(
            target.id,
            run.id,
            1,
            broker_order_id="ACK-EXACT",
            status="open",
            reject_reason=None,
        )
        == "already_bound"
    )
    assert sm.get_order(target.id).status == "complete"

    # A broker id already bound to another row cannot be attached here.
    assert sm.update_order(other.id, broker_order_id="ACK-OTHER")
    third = sm.record_order(
        run.id,
        3,
        "entry",
        {**ORDER, "symbol": "NIFTY28MAY2624200CE", "status": "pending"},
    )
    assert third is not None
    assert (
        sm.bind_order_acknowledgement(
            third.id,
            run.id,
            3,
            broker_order_id="ACK-OTHER",
            status="open",
            reject_reason=None,
        )
        == "conflict"
    )
    unchanged = sm.get_order(third.id)
    assert unchanged.broker_order_id is None
    assert unchanged.status == "pending"


def test_rejected_ack_binding_can_terminally_repair_an_exact_pending_row_without_broker_id():
    run = _run()
    row = sm.record_order(run.id, 1, "entry", {**ORDER, "status": "pending"})
    assert row is not None

    assert (
        sm.bind_order_acknowledgement(
            row.id,
            run.id,
            1,
            broker_order_id=None,
            status="rejected",
            reject_reason="margin refused",
        )
        == "repaired"
    )
    durable = sm.get_order(row.id)
    assert durable.status == "rejected"
    assert durable.broker_order_id is None
    assert durable.reject_reason == "margin refused"


@pytest.mark.parametrize(
    ("entry_status", "exit_status", "entry_action", "exit_action", "expected"),
    [
        ("cancelled", "rejected", "BUY", "SELL", 12.0),
        ("rejected", "cancelled", "SELL", "BUY", -12.0),
    ],
)
def test_reconcile_run_pnl_uses_exact_terminal_partial_entry_and_exit_quantities(
    entry_status,
    exit_status,
    entry_action,
    exit_action,
    expected,
):
    run = _run()
    _filled_order(
        run.id,
        1,
        "entry",
        entry_action,
        requested_qty=40,
        status=entry_status,
        avg_price=100.0,
        filled_qty=4,
    )
    _filled_order(
        run.id,
        1,
        "exit_close_all",
        exit_action,
        requested_qty=30,
        status=exit_status,
        avg_price=104.0,
        filled_qty=3,
    )

    reconciled = sm.reconcile_run_pnl(run.id)

    assert reconciled == pytest.approx(expected)
    assert float(sm.get_run(run.id).pnl_realized) == pytest.approx(expected)


def test_reconcile_run_pnl_keeps_complete_fills_without_inventing_dead_fill_facts():
    run = _run()
    # Existing complete-row behavior: a missing filled quantity means the
    # broker completed the requested two units, for +10 on this long.
    _filled_order(
        run.id,
        1,
        "entry",
        "BUY",
        requested_qty=2,
        status="complete",
        avg_price=10.0,
        filled_qty=None,
    )
    _filled_order(
        run.id,
        1,
        "exit_close_all",
        "SELL",
        requested_qty=2,
        status="complete",
        avg_price=15.0,
        filled_qty=None,
    )
    # A terminal zero-fill must not fall back to the requested 100 units.
    _filled_order(
        run.id,
        2,
        "entry",
        "BUY",
        requested_qty=100,
        status="cancelled",
        avg_price=20.0,
        filled_qty=0,
    )
    _filled_order(
        run.id,
        2,
        "exit_close_all",
        "SELL",
        requested_qty=100,
        status="rejected",
        avg_price=25.0,
        filled_qty=0,
    )
    # Quantity without a usable terminal entry price proves exposure, but it
    # cannot create valued P&L.
    _filled_order(
        run.id,
        3,
        "entry",
        "BUY",
        requested_qty=50,
        status="rejected",
        avg_price=0.0,
        filled_qty=3,
    )
    _filled_order(
        run.id,
        3,
        "exit_close_all",
        "SELL",
        requested_qty=50,
        status="cancelled",
        avg_price=25.0,
        filled_qty=3,
    )
    # A usable entry plus an unpriced dead exit likewise cannot invent P&L.
    _filled_order(
        run.id,
        4,
        "entry",
        "BUY",
        requested_qty=4,
        status="complete",
        avg_price=30.0,
        filled_qty=4,
    )
    _filled_order(
        run.id,
        4,
        "exit_close_all",
        "SELL",
        requested_qty=40,
        status="cancelled",
        avg_price=0.0,
        filled_qty=2,
    )
    # One priced dead partial closes exactly two requested-of-99 short units,
    # adding +10 rather than +495.
    _filled_order(
        run.id,
        5,
        "entry",
        "SELL",
        requested_qty=99,
        status="complete",
        avg_price=50.0,
        filled_qty=2,
    )
    _filled_order(
        run.id,
        5,
        "exit_close_all",
        "BUY",
        requested_qty=99,
        status="rejected",
        avg_price=45.0,
        filled_qty=2,
    )

    reconciled = sm.reconcile_run_pnl(run.id)

    assert reconciled == pytest.approx(20.0)
    assert float(sm.get_run(run.id).pnl_realized) == pytest.approx(20.0)


def test_reconcile_run_pnl_separates_incarnations_and_caps_shuffled_exits():
    run = _run()
    base = datetime(2026, 8, 30, tzinfo=UTC).replace(tzinfo=None)

    # Insert deliberately out of chronology. Reconciliation must use durable
    # placement order inside each exact owner rather than query row order.
    _filled_order(
        run.id,
        1,
        "exit_signal",
        "SELL",
        requested_qty=4,
        status="complete",
        avg_price=110.0,
        filled_qty=4,
        position_ref="long-owner",
        placed_at=base + timedelta(minutes=3),
    )
    _filled_order(
        run.id,
        1,
        "exit_signal",
        "BUY",
        requested_qty=3,
        status="complete",
        avg_price=110.0,
        filled_qty=3,
        position_ref="short-owner",
        placed_at=base + timedelta(minutes=5),
    )
    _filled_order(
        run.id,
        1,
        "entry",
        "BUY",
        requested_qty=4,
        status="complete",
        avg_price=100.0,
        filled_qty=4,
        position_ref="long-owner",
        placed_at=base + timedelta(minutes=1),
    )
    _filled_order(
        run.id,
        1,
        "entry",
        "SELL",
        requested_qty=3,
        status="complete",
        avg_price=120.0,
        filled_qty=3,
        position_ref="short-owner",
        placed_at=base + timedelta(minutes=4),
    )
    _filled_order(
        run.id,
        1,
        "exit_signal",
        "SELL",
        requested_qty=2,
        status="complete",
        avg_price=105.0,
        filled_qty=2,
        position_ref="long-owner",
        placed_at=base + timedelta(minutes=2),
    )

    reconciled = sm.reconcile_run_pnl(run.id)

    # Long: 2 @ +5, then only the remaining 2 @ +10. Short: 3 @ +10.
    assert reconciled == pytest.approx(60.0)
    assert float(sm.get_run(run.id).pnl_realized) == pytest.approx(60.0)


def test_reconcile_run_pnl_keeps_overlapping_opposite_referenced_owners_separate():
    run = _run()
    base = datetime(2026, 8, 30, tzinfo=UTC).replace(tzinfo=None)
    facts = [
        ("entry", "BUY", 100.0, "long-owner", 1),
        ("entry", "SELL", 120.0, "short-owner", 2),
        ("exit_signal", "BUY", 110.0, "short-owner", 3),
        ("exit_signal", "SELL", 110.0, "long-owner", 4),
    ]
    for kind, action, price, position_ref, minute in facts:
        _filled_order(
            run.id,
            1,
            kind,
            action,
            requested_qty=1,
            status="complete",
            avg_price=price,
            filled_qty=1,
            position_ref=position_ref,
            placed_at=base + timedelta(minutes=minute),
        )

    reconciled = sm.reconcile_run_pnl(run.id)

    assert reconciled == pytest.approx(20.0)
    assert float(sm.get_run(run.id).pnl_realized) == pytest.approx(20.0)


def test_reconcile_run_pnl_uses_fifo_for_legacy_rows_without_crossing_references():
    run = _run()
    base = datetime(2026, 8, 30, tzinfo=UTC).replace(tzinfo=None)

    facts = [
        ("exit_signal", "SELL", 10, 25.0, None, 4),
        ("entry", "BUY", 1, 100.0, "referenced-owner", 5),
        ("entry", "BUY", 2, 10.0, None, 1),
        ("exit_signal", "SELL", 1, 110.0, "referenced-owner", 6),
        ("entry", "BUY", 2, 20.0, None, 3),
        ("exit_signal", "SELL", 1, 12.0, None, 2),
    ]
    for kind, action, qty, price, position_ref, minute in facts:
        _filled_order(
            run.id,
            1,
            kind,
            action,
            requested_qty=qty,
            status="complete",
            avg_price=price,
            filled_qty=qty,
            position_ref=position_ref,
            placed_at=base + timedelta(minutes=minute),
        )

    reconciled = sm.reconcile_run_pnl(run.id)

    # Legacy FIFO: +2, then +15 and +10 (the exit is capped at three).
    # The referenced owner is reconciled independently for +10.
    assert reconciled == pytest.approx(37.0)


def test_reconcile_run_pnl_preserves_authoritative_value_when_ownership_is_ambiguous():
    run = _run()
    base = datetime(2026, 8, 30, tzinfo=UTC).replace(tzinfo=None)
    _filled_order(
        run.id,
        1,
        "exit_signal",
        "SELL",
        requested_qty=1,
        status="complete",
        avg_price=110.0,
        filled_qty=1,
        position_ref="ambiguous-owner",
        placed_at=base,
    )
    _filled_order(
        run.id,
        1,
        "entry",
        "BUY",
        requested_qty=1,
        status="complete",
        avg_price=100.0,
        filled_qty=1,
        position_ref="ambiguous-owner",
        placed_at=base + timedelta(minutes=1),
    )
    sm.finish_run(run.id, "manual", pnl_realized=73.0)

    assert sm.reconcile_run_pnl(run.id) is None
    assert float(sm.get_run(run.id).pnl_realized) == pytest.approx(73.0)


def test_a_run_records_its_final_numbers_on_stop():
    created, _ = sm.create_strategy(USER, _config())
    run = sm.create_run(created["id"], "sandbox", "zerodha", trigger_source="manual")

    assert run.stopped_at is None
    assert run in sm.list_open_runs()

    sm.finish_run(run.id, "overall_target", pnl_realized=5230.0, pnl_peak=6000.0, pnl_trough=-120.0)

    stopped = sm.get_run(run.id)
    assert stopped.stopped_at is not None
    assert stopped.stop_reason == "overall_target"
    assert float(stopped.pnl_realized) == 5230.0
    assert stopped.id not in [r.id for r in sm.list_open_runs()]


def test_repeated_stop_request_preserves_the_first_cause_and_timestamp():
    run = _run()

    assert sm.request_run_stop(run.id, "overall_target") is True
    first = sm.get_run(run.id)
    first_requested_at = first.stop_requested_at

    assert sm.request_run_stop(run.id, "manual") is True
    repeated = sm.get_run(run.id)

    assert repeated.stop_requested_at == first_requested_at
    assert repeated.stop_requested_reason == "overall_target"


def test_orders_are_recorded_at_placement_and_updated_on_fill():
    created, _ = sm.create_strategy(USER, _config())
    run = sm.create_run(created["id"], "sandbox", "zerodha")

    order = sm.record_order(
        run.id,
        leg_id=1,
        kind="entry",
        order={
            "symbol": "NIFTY28MAY2624000CE",
            "exchange": "NFO",
            "action": "SELL",
            "qty": 75,
            "pricetype": "MARKET",
        },
    )

    assert order.status == "pending"
    assert order.filled_at is None

    sm.update_order(
        order.id,
        status="complete",
        broker_order_id="250101000123",
        avg_fill_price=100.5,
        filled_qty=75,
    )

    rows = sm.list_orders(run.id)
    assert len(rows) == 1
    assert rows[0]["status"] == "complete"
    assert rows[0]["avg_fill_price"] == 100.5
    # filled_at is stamped by the store when status first reaches complete,
    # so recovery can tell a fill apart from an order still in flight.
    assert rows[0]["filled_at"] is not None


def test_terminal_order_transition_has_one_winner():
    run = _run()
    order = sm.record_order(run.id, 1, "exit_signal", ORDER)
    transition = getattr(sm, "transition_order_terminal", None)

    assert callable(transition)
    assert transition(order.id, "rejected", reject_reason="broker refused") is True
    assert transition(order.id, "rejected", reject_reason="duplicate frame") is False


def test_events_are_listed_newest_first_and_filter_by_kind():
    created, _ = sm.create_strategy(USER, _config())
    run = sm.create_run(created["id"], "sandbox", "zerodha")

    sm.record_event(created["id"], USER, "run_started", "Run started", run_id=run.id)
    sm.record_event(
        created["id"],
        USER,
        "leg_sl_hit",
        "SL hit on leg 1",
        run_id=run.id,
        leg_id=1,
        severity="warn",
    )

    events = sm.list_events(created["id"])
    assert [e["kind"] for e in events] == ["leg_sl_hit", "run_started"]

    warns = sm.list_events(created["id"], severity="warn")
    assert [e["kind"] for e in warns] == ["leg_sl_hit"]
    assert warns[0]["leg_id"] == 1


def test_a_rejected_webhook_is_audited_just_like_an_accepted_one():
    # An alert that silently stopped working is exactly the case an operator
    # needs this table for, so rejections must leave a row too.
    created, _ = sm.create_strategy(USER, _config())

    sm.record_webhook_event(
        "ok", strategy_id=created["id"], action="start", mode="sandbox", ip="1.2.3.4"
    )
    sm.record_webhook_event(
        "rejected_live_disabled", strategy_id=created["id"], action="start", mode="live"
    )

    rows = sm.list_webhook_events(created["id"])
    assert [r["result"] for r in rows] == ["rejected_live_disabled", "ok"]


def test_a_webhook_with_an_unknown_token_is_audited_without_a_strategy():
    sm.record_webhook_event("rejected_token", ip="9.9.9.9", user_agent="curl/8")

    # Nothing to assert against a strategy id; the point is that it does not
    # raise and does not need one.
    assert sm.list_webhook_events(0) == []


# ---------------------------------------------------------------------------
# Checkpoints
# ---------------------------------------------------------------------------


def test_the_latest_checkpoint_is_what_recovery_reads():
    created, _ = sm.create_strategy(USER, _config())
    run = sm.create_run(created["id"], "sandbox", "zerodha")

    sm.write_checkpoint(
        run.id, {"pnl_total": 100, "pnl_peak": 100, "leg_state": {"1": {"ltp": 10}}}
    )
    sm.write_checkpoint(
        run.id,
        {"pnl_total": 250, "pnl_peak": 300, "lock_floor": 200, "leg_state": {"1": {"ltp": 12}}},
    )

    latest = sm.latest_checkpoint(run.id)
    assert latest["pnl_total"] == 250.0
    assert latest["pnl_peak"] == 300.0
    assert latest["lock_floor"] == 200.0
    assert latest["leg_state"] == {"1": {"ltp": 12}}


def test_pruning_keeps_the_newest_checkpoints_and_drops_the_rest():
    # Checkpoints are written every few seconds for a whole session, in a
    # process that never restarts. Without a bound this table is the module's
    # one unbounded writer.
    created, _ = sm.create_strategy(USER, _config())
    run = sm.create_run(created["id"], "sandbox", "zerodha")

    for i in range(25):
        sm.write_checkpoint(run.id, {"pnl_total": i, "leg_state": {}})

    removed = sm.prune_checkpoints(run.id, keep=10)

    assert removed == 15
    remaining = sm.list_checkpoints(run.id)
    assert len(remaining) == 10
    # The newest survive, so the checkpoint recovery reads is never the one
    # pruning removed.
    assert [c["pnl_total"] for c in remaining] == [float(i) for i in range(15, 25)]


def test_pruning_a_run_with_fewer_checkpoints_than_the_bound_removes_nothing():
    created, _ = sm.create_strategy(USER, _config())
    run = sm.create_run(created["id"], "sandbox", "zerodha")
    sm.write_checkpoint(run.id, {"pnl_total": 1, "leg_state": {}})

    assert sm.prune_checkpoints(run.id, keep=10) == 0
    assert len(sm.list_checkpoints(run.id)) == 1


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def test_money_leaves_the_store_as_float_not_decimal():
    # Numeric columns come back as Decimal, which jsonify cannot serialise.
    # Converting at the boundary is what keeps that out of every route.
    created, _ = sm.create_strategy(
        USER, _config(overall_sl_mtm=3000, overall_target_mtm=5000, daily_loss_limit_inr=10000)
    )

    assert isinstance(created["overall_sl_mtm"], float)
    assert created["overall_sl_mtm"] == 3000.0
    assert isinstance(created["overall_target_mtm"], float)
    assert isinstance(created["daily_loss_limit_inr"], float)


def test_timestamps_leave_the_store_with_an_explicit_offset():
    # Stored naive UTC. Emitting a bare string would leave every consumer
    # guessing which zone it was in; the offset makes it unambiguous.
    created, _ = sm.create_strategy(USER, _config())

    assert created["created_at"].endswith("+00:00")
    assert created["updated_at"].endswith("+00:00")


def test_the_list_view_omits_legs_but_the_detail_view_carries_them():
    created, _ = sm.create_strategy(USER, _config())

    listed = sm.list_strategies(USER)[0]
    assert "legs" not in listed

    detail = sm.strategy_to_dict(sm.get_strategy(created["id"], USER))
    assert len(detail["legs"]) == 1
    assert detail["legs"][0]["option_type"] == "CE"


def test_ownerless_webhook_audit_rows_are_capped():
    """A token nothing recognises leaves a row with no owner and no reader.

    Nothing shows it, because the audit view is scoped to a strategy, and
    nothing deletes it. Left unbounded, anyone who can reach the webhook URL
    grows the database as fast as they can send, invisibly. The rows are worth
    keeping, since a run of them is the first sign of somebody walking the
    token space, so they are capped rather than dropped.
    """
    cap = sm.MAX_UNATTRIBUTED_WEBHOOK_EVENTS
    for _ in range(cap + sm._PRUNE_UNATTRIBUTED_EVERY + 5):
        sm.record_webhook_event("rejected_token", ip="203.0.113.9")

    remaining = (
        sm.db_session.query(sm.SmWebhookEvent)
        .filter(sm.SmWebhookEvent.strategy_id.is_(None))
        .count()
    )
    assert remaining <= cap + sm._PRUNE_UNATTRIBUTED_EVERY, remaining
    assert remaining >= cap, "the newest are kept, not everything discarded"


def test_capping_ownerless_rows_leaves_a_strategys_own_audit_alone():
    created, _ = sm.create_strategy(USER, _config())
    sid = created["id"]
    sm.record_webhook_event("ok", strategy_id=sid, action="start", mode="sandbox")

    for _ in range(sm.MAX_UNATTRIBUTED_WEBHOOK_EVENTS + sm._PRUNE_UNATTRIBUTED_EVERY + 5):
        sm.record_webhook_event("rejected_token", ip="203.0.113.9")

    assert [e["result"] for e in sm.list_webhook_events(sid)] == ["ok"]
