"""Strategy-module persistence behaviour.

The blueprint layer is thin, so the contract worth pinning is the store's: what
it does with a duplicate name, a token that has been rotated, a PATCH carrying
fields it must not accept, an edit attempted while a run is live, and a
checkpoint table that would otherwise grow all session.

These run against the configured database, like test_watchlist_db.py, and each
test starts and ends with no rows for either test user.
"""

import pytest

from database import strategy_module_db as sm

USER = "sm_test_user"
OTHER = "sm_other_user"


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
