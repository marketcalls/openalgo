"""Sandbox findings from the gthread review (sandbox-01, -02 and -03).

sandbox-01. A reconcile pass that followed a lost compare-and-set ran inside
the transaction the failed write had opened, holding SQLite's write lock, and
returned without committing or rolling back when it found nothing to fix. The
engine threads that reconcile never release their sessions, so the lock stayed
held and every other sandbox writer failed with "database is locked".

sandbox-02. Reconcile read the positions and GTT totals before the funds row
and compared only the funds row when writing. A settlement committed between
those reads moved both, the funds row still matched its snapshot, and the
correction re-blocked the margin the settlement had just released.

sandbox-03. A GTT leg fires on the market-data thread, which delivers every
tick to every subscriber, and its order waited there for any other order on
the same position. The leg now only tries the lock and fires on a later tick.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from decimal import Decimal

import pytest
from test_gthread_sandbox_support import (
    CAPITAL,
    funds_of,
    prepare_databases,
    release_sessions,
    reset_user,
)

USER = "gthread_review_sandbox"


@pytest.fixture(autouse=True)
def fresh_account():
    prepare_databases()
    reset_user(USER)
    release_sessions()
    yield
    release_sessions()


def _on_thread(target, timeout=30.0):
    out = {}

    def run():
        try:
            out["value"] = target()
        except BaseException as exc:  # returned to the test
            out["error"] = exc
        finally:
            release_sessions()

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout)
    return worker, out


def _write_lock_is_free() -> bool:
    from database.sandbox_db import engine

    conn = sqlite3.connect(engine.url.database, timeout=0.3, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("ROLLBACK")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()


def _add_position(margin: Decimal, quantity: int = 75):
    from database.sandbox_db import SandboxPositions, db_session

    db_session.add(
        SandboxPositions(
            user_id=USER,
            symbol="RELIANCE",
            exchange="NSE",
            product="NRML",
            quantity=quantity,
            average_price=Decimal("2000"),
            ltp=Decimal("2000"),
            margin_blocked=margin,
            accumulated_realized_pnl=Decimal("0"),
        )
    )
    db_session.commit()
    db_session.remove()


def _settle_on_another_thread(margin: Decimal):
    """What a settlement commits: the position closed and its margin released, at once."""
    from database.sandbox_db import SandboxPositions, db_session
    from sandbox.fund_manager import FundManager

    def settle():
        ok, message = FundManager(USER).stage_release_margin(margin, 0, "settled", log=False)
        assert ok, message
        position = SandboxPositions.query.filter_by(user_id=USER, symbol="RELIANCE").first()
        position.quantity = 0
        position.margin_blocked = Decimal("0.00")
        db_session.commit()

    worker, out = _on_thread(settle)
    assert not worker.is_alive() and "error" not in out, out


# ---------------------------------------------------------------------------
# sandbox-01
# ---------------------------------------------------------------------------


def test_a_pass_after_a_lost_write_that_finds_nothing_releases_the_lock(monkeypatch):
    from sandbox import fund_manager
    from sandbox.fund_manager import FundManager, reconcile_margin

    stuck = Decimal("1000.00")
    _on_thread(lambda: FundManager(USER).block_margin(stuck, "resting order"))
    real_write = fund_manager.write_funds_if_unchanged
    raced = []

    def write_after_a_cancel(user_id, snapshot, new_values):
        if not raced:
            raced.append(1)
            # The resting order is cancelled between the snapshot and the write.
            _on_thread(lambda: FundManager(USER).release_margin(stuck, 0, "cancelled"))
        return real_write(user_id, snapshot, new_values)

    monkeypatch.setattr(fund_manager, "write_funds_if_unchanged", write_after_a_cancel)
    result = {}

    def engine_thread():
        # Like the market-data thread: reconcile, then never release the session.
        result["outcome"] = reconcile_margin(USER, auto_fix=True)
        result["lock_free"] = _write_lock_is_free()

    worker = threading.Thread(target=engine_thread, daemon=True)
    worker.start()
    worker.join(30)
    try:
        assert raced, "the cancel never landed between the snapshot and the write"
        assert result["outcome"][0] is False and result["outcome"][1] == 0
        assert result["lock_free"], "reconcile left its thread holding the write lock"
        assert _write_lock_is_free()
    finally:
        release_sessions()

    funds = funds_of(USER)
    assert funds["used"] == 0 and funds["available"] == CAPITAL


# ---------------------------------------------------------------------------
# sandbox-02
# ---------------------------------------------------------------------------


def _hook_gtt_read(monkeypatch, action):
    """Run ``action`` once, when reconcile reads the active GTT total."""
    from database.sandbox_db import SandboxGTT, db_session

    fired = []

    class Hooked:
        def filter_by(self, **kwargs):
            if not fired:
                fired.append(1)
                action()
            return db_session.query(SandboxGTT).filter_by(**kwargs)

    monkeypatch.setattr(SandboxGTT, "query", Hooked())
    return fired


def test_a_settlement_between_the_reads_is_not_undone(monkeypatch):
    from sandbox.fund_manager import FundManager, reconcile_margin

    margin = Decimal("150000.00")
    _on_thread(lambda: FundManager(USER).block_margin(margin, "future"))
    _add_position(margin)

    fired = _hook_gtt_read(monkeypatch, lambda: _settle_on_another_thread(margin))
    worker, out = _on_thread(lambda: reconcile_margin(USER, auto_fix=True))
    monkeypatch.undo()

    assert fired and "error" not in out, out
    funds = funds_of(USER)
    assert funds["used"] == 0, "reconcile re-blocked the margin the settlement released"
    assert funds["available"] == CAPITAL


def test_a_settlement_right_after_the_funds_read_is_caught_by_the_write(monkeypatch):
    """The other order of events: the retry pass, under the write lock, decides."""
    from sandbox import fund_manager
    from sandbox.fund_manager import FundManager, reconcile_margin

    margin = Decimal("150000.00")
    _on_thread(lambda: FundManager(USER).block_margin(margin, "future"))
    _add_position(margin)

    real_read = fund_manager.read_funds_snapshot
    fired = []

    def read_then_settle(user_id):
        snapshot = real_read(user_id)
        if not fired:
            fired.append(1)
            _settle_on_another_thread(margin)
        return snapshot

    monkeypatch.setattr(fund_manager, "read_funds_snapshot", read_then_settle)
    result = {}

    def engine_thread():
        result["outcome"] = reconcile_margin(USER, auto_fix=True)
        result["lock_free"] = _write_lock_is_free()

    worker = threading.Thread(target=engine_thread, daemon=True)
    worker.start()
    worker.join(30)
    monkeypatch.undo()
    release_sessions()

    assert fired and result["lock_free"]
    funds = funds_of(USER)
    assert funds["used"] == 0 and funds["available"] == CAPITAL


# ---------------------------------------------------------------------------
# sandbox-03
# ---------------------------------------------------------------------------


def _gtt_leg():
    from database.sandbox_db import SandboxGTT, db_session
    from sandbox.gtt_manager import GTTManager, try_claim_trigger

    ok, response, _ = GTTManager(USER).place_gtt(
        {
            "trigger_type": "SINGLE",
            "symbol": "ZEEL",
            "exchange": "NSE",
            "action": "SELL",
            "product": "CNC",
            "quantity": 10,
            "pricetype": "LIMIT",
            "price": 95.0,
            "triggerprice_sl": 95.0,
            "strategy": "review",
        },
        last_price=100,
    )
    assert ok, response
    gtt_id = response["trigger_id"]
    leg_id = SandboxGTT.query.filter_by(gtt_id=gtt_id).first().legs[0].id
    db_session.remove()
    assert try_claim_trigger(leg_id)
    db_session.remove()
    return gtt_id, leg_id


def test_a_leg_never_waits_for_another_order_on_its_position():
    from database.sandbox_db import SandboxGTT, SandboxGTTLeg, db_session
    from sandbox.gtt_manager import fire_leg
    from sandbox.position_locks import position_lock

    gtt_id, leg_id = _gtt_leg()
    before = funds_of(USER)
    held = threading.Event()
    release = threading.Event()

    def smart_order_in_progress():
        with position_lock(USER, "NSE", "ZEEL", "CNC"):
            held.set()
            release.wait(30)

    holder = threading.Thread(target=smart_order_in_progress, daemon=True)
    holder.start()
    assert held.wait(10)
    try:
        started = time.monotonic()
        worker, out = _on_thread(lambda: fire_leg(leg_id, execution_price=95.0), timeout=3.0)
        waited = time.monotonic() - started
        assert not worker.is_alive(), "the tick waited on another order's position lock"
        assert out.get("value") is False and waited < 2.0
    finally:
        release.set()
        holder.join(10)

    db_session.remove()
    assert SandboxGTTLeg.query.filter_by(id=leg_id).first().leg_status == "pending"
    assert SandboxGTT.query.filter_by(gtt_id=gtt_id).first().gtt_status == "active"
    db_session.remove()
    assert funds_of(USER) == before, "margin moved for a leg that did not fire"
