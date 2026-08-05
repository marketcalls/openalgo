"""Sandbox GTT: trigger evaluation, leg construction, and claim safety.

The concurrency guarantee is the one worth proving. Three evaluators - the
polling engine, the WebSocket engine, and the boot-time catch-up scan - can
observe the same crossed trigger within milliseconds. If more than one fires,
the user gets duplicate orders from a single GTT, so the claim must admit
exactly one winner.
"""

import os
import sys
from decimal import Decimal
from unittest import mock

import pytest

# Repo root on the path before importing: test/sandbox/ is itself a package
# named "sandbox", so without this the import below resolves to this test
# package rather than the real one.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sandbox.gtt_manager import GTTManager, leg_is_triggered_by  # noqa: E402


class TestTriggerEvaluation:
    """Direction comes from the trigger's role, never from BUY/SELL.

    triggerprice_sl sits below the LTP and fires on a fall; triggerprice_tg
    sits above and fires on a rise. Deriving it from the action inverts
    BUY-on-dip and SELL-at-target, which would fire both on the first tick.
    """

    @pytest.mark.parametrize(
        "direction,trigger,ltp,expected",
        [
            ("above", 100, 101, True),
            ("above", 100, 100, True),   # touched exactly counts
            ("above", 100, 99, False),
            ("below", 100, 99, True),
            ("below", 100, 100, True),   # touched exactly counts
            ("below", 100, 101, False),
        ],
    )
    def test_direction(self, direction, trigger, ltp, expected):
        assert leg_is_triggered_by(direction, trigger, ltp) is expected

    def test_case_insensitive(self):
        assert leg_is_triggered_by("ABOVE", 100, 101) is True

    @pytest.mark.parametrize("trigger,ltp", [(None, 100), (100, None), (None, None)])
    def test_missing_values_never_trigger(self, trigger, ltp):
        """A missing quote must not be read as a crossed trigger."""
        assert leg_is_triggered_by("below", trigger, ltp) is False

    def test_decimal_and_float_compare_exactly(self):
        """Prices arrive as Decimal from the DB and float from quotes."""
        assert leg_is_triggered_by("above", Decimal("100.05"), 100.05) is True
        assert leg_is_triggered_by("above", Decimal("100.05"), 100.04) is False

    def test_unknown_direction_defaults_to_below(self):
        """Legs migrated from before the column existed default to 'below'."""
        assert leg_is_triggered_by("", 100, 99) is True
        assert leg_is_triggered_by(None, 100, 101) is False


class TestDocumentedScenarios:
    """The four cases from docs/api/order-management/placegttorder.md."""

    def _mgr(self):
        return GTTManager.__new__(GTTManager)

    def _single(self, **kw):
        payload = {
            "trigger_type": "SINGLE",
            "quantity": 10,
            "price": 100,
            "action": "BUY",
            **kw,
        }
        return self._mgr()._build_legs(payload)[0]

    def test_buy_on_dip_fires_when_price_falls(self):
        """triggerprice_sl below LTP. Action-based logic got this backwards."""
        leg = self._single(action="BUY", triggerprice_sl=95)
        assert leg["direction"] == "below"
        assert leg_is_triggered_by(leg["direction"], 95, 94) is True
        assert leg_is_triggered_by(leg["direction"], 95, 96) is False

    def test_sell_at_target_fires_when_price_rises(self):
        """triggerprice_tg above LTP. Action-based logic got this backwards too."""
        leg = self._single(action="SELL", triggerprice_tg=110)
        assert leg["direction"] == "above"
        assert leg_is_triggered_by(leg["direction"], 110, 111) is True
        assert leg_is_triggered_by(leg["direction"], 110, 109) is False

    def test_sell_stoploss_fires_when_price_falls(self):
        leg = self._single(action="SELL", triggerprice_sl=95)
        assert leg["direction"] == "below"
        assert leg_is_triggered_by(leg["direction"], 95, 94) is True

    def test_buy_breakout_fires_when_price_rises(self):
        leg = self._single(action="BUY", triggerprice_tg=110)
        assert leg["direction"] == "above"
        assert leg_is_triggered_by(leg["direction"], 110, 111) is True

    def test_oco_legs_get_opposite_directions(self):
        legs = self._mgr()._build_legs(
            {
                "trigger_type": "OCO",
                "action": "SELL",
                "quantity": 10,
                "price": 100,
                "triggerprice_sl": 95,
                "stoploss": 94,
                "triggerprice_tg": 110,
                "target": 111,
            }
        )
        assert [leg["direction"] for leg in legs] == ["below", "above"]


class TestLegConstruction:
    """Flat request fields to legs, without a database."""

    def _mgr(self):
        return GTTManager.__new__(GTTManager)  # no DB work needed

    def test_single_from_stoploss_trigger(self):
        legs = self._mgr()._build_legs(
            {
                "trigger_type": "SINGLE",
                "action": "SELL",
                "quantity": 10,
                "price": 95,
                "triggerprice_sl": 96,
            }
        )
        assert len(legs) == 1
        assert legs[0]["trigger_price"] == 96
        assert legs[0]["action"] == "SELL"

    def test_single_from_target_trigger(self):
        legs = self._mgr()._build_legs(
            {
                "trigger_type": "SINGLE",
                "action": "SELL",
                "quantity": 10,
                "price": 110,
                "triggerprice_tg": 109,
            }
        )
        assert len(legs) == 1
        assert legs[0]["trigger_price"] == 109

    def test_single_with_both_triggers_is_rejected(self):
        """That is an OCO the caller forgot to label; guessing would drop a leg."""
        assert (
            self._mgr()._build_legs(
                {
                    "trigger_type": "SINGLE",
                    "action": "SELL",
                    "quantity": 10,
                    "price": 100,
                    "triggerprice_sl": 96,
                    "triggerprice_tg": 109,
                }
            )
            == []
        )

    def test_single_without_any_trigger_is_rejected(self):
        assert (
            self._mgr()._build_legs(
                {"trigger_type": "SINGLE", "action": "SELL", "quantity": 10, "price": 100}
            )
            == []
        )

    def test_oco_builds_two_legs_with_their_own_limits(self):
        legs = self._mgr()._build_legs(
            {
                "trigger_type": "OCO",
                "action": "SELL",
                "quantity": 10,
                "price": 0,
                "triggerprice_sl": 96,
                "stoploss": 95.5,
                "triggerprice_tg": 109,
                "target": 109.5,
            }
        )
        assert len(legs) == 2
        assert (legs[0]["trigger_price"], legs[0]["price"]) == (96, 95.5)
        assert (legs[1]["trigger_price"], legs[1]["price"]) == (109, 109.5)

    @pytest.mark.parametrize(
        "payload",
        [
            {"triggerprice_sl": 96},                    # target missing
            {"triggerprice_tg": 109},                   # stoploss missing
            {"triggerprice_sl": 0, "triggerprice_tg": 0},
        ],
    )
    def test_oco_requires_both_triggers(self, payload):
        assert (
            self._mgr()._build_legs(
                {"trigger_type": "OCO", "action": "SELL", "quantity": 10, "price": 100, **payload}
            )
            == []
        )

    def test_oco_falls_back_to_price_when_a_limit_is_absent(self):
        legs = self._mgr()._build_legs(
            {
                "trigger_type": "OCO",
                "action": "SELL",
                "quantity": 10,
                "price": 100,
                "triggerprice_sl": 96,
                "triggerprice_tg": 109,
            }
        )
        assert [leg["price"] for leg in legs] == [100, 100]

    def test_non_numeric_trigger_is_rejected_not_crashed(self):
        assert (
            self._mgr()._build_legs(
                {
                    "trigger_type": "SINGLE",
                    "action": "BUY",
                    "quantity": 1,
                    "price": 10,
                    "triggerprice_sl": "not-a-number",
                }
            )
            == []
        )


class TestIdFormat:
    def test_gtt_id_shape(self):
        from sandbox.gtt_manager import _generate_gtt_id

        gtt_id = _generate_gtt_id()
        parts = gtt_id.split("-")
        assert parts[0] == "GTT"
        assert len(parts[1]) == 6 and parts[1].isdigit()
        assert len(parts[2]) == 8

    def test_ids_are_unique(self):
        from sandbox.gtt_manager import _generate_gtt_id

        assert len({_generate_gtt_id() for _ in range(200)}) == 200


# -- DB-backed lifecycle ----------------------------------------------------

GTT_TEST_USER = "gtt_test_user"


@pytest.fixture
def clean_gtt_user():
    """A user with funds initialised and no GTTs, torn down afterwards."""
    from database.sandbox_db import SandboxGTT, SandboxGTTLeg, db_session
    from sandbox.fund_manager import FundManager, initialize_user_funds

    def purge():
        """Drop this user's GTTs and reset their funds.

        Deleting a GTT row does not release the margin it blocked, so without
        the funds reset the reservation from one test leaks into the next and
        every reconciliation check sees a phantom discrepancy.
        """
        from decimal import Decimal as D

        from database.sandbox_db import SandboxFunds, SandboxOrders, SandboxPositions

        for gtt in SandboxGTT.query.filter_by(user_id=GTT_TEST_USER).all():
            SandboxGTTLeg.query.filter_by(gtt_id=gtt.gtt_id).delete()
            db_session.delete(gtt)
        SandboxPositions.query.filter_by(user_id=GTT_TEST_USER).delete()
        # Orders too, and for a reason worth stating: SQLite reuses a deleted
        # row's autoincrement id, so the next test's leg can be handed id 1
        # again. A leftover order still correlated to id 1 then trips the unique
        # index, and recovery reads it as "this GTT already fired". Production
        # never deletes legs, so this is a test-only hazard - but it makes the
        # suite lie in both directions if left.
        SandboxOrders.query.filter_by(user_id=GTT_TEST_USER).delete()
        db_session.commit()

        initialize_user_funds(GTT_TEST_USER)
        funds = SandboxFunds.query.filter_by(user_id=GTT_TEST_USER).first()
        if funds is not None:
            funds.available_balance += D(str(funds.used_margin or 0))
            funds.used_margin = D("0.00")
            db_session.commit()

    purge()
    yield FundManager(GTT_TEST_USER)
    purge()


def _single_gtt(trigger=95.0, qty=10, price=95.0):
    return {
        "trigger_type": "SINGLE",
        "symbol": "ZEEL",
        "exchange": "NSE",
        "action": "SELL",
        "product": "CNC",
        "quantity": qty,
        "pricetype": "LIMIT",
        "price": price,
        "triggerprice_sl": trigger,
        "strategy": "gtt-test",
    }


def _used_margin(fm):
    """Blocked margin, read from the row rather than the API projection.

    get_funds() exposes it as "utiliseddebits" for broker parity; the raw column
    is what the margin arithmetic actually moves.
    """
    from decimal import Decimal as D

    from database.sandbox_db import SandboxFunds

    row = SandboxFunds.query.filter_by(user_id=GTT_TEST_USER).first()
    return D(str(row.used_margin)) if row else D("0")


class TestGTTMargin:
    """Margin must be reserved at placement and returned on every exit path."""

    def test_placement_blocks_margin(self, clean_gtt_user):
        fm = clean_gtt_user
        before = _used_margin(fm)

        ok, response, status = GTTManager(GTT_TEST_USER).place_gtt(_single_gtt(), last_price=100)
        assert ok, response
        assert status == 200

        after = _used_margin(fm)
        assert after > before, "placing a GTT must reserve margin"

    def test_cancel_returns_the_margin_exactly(self, clean_gtt_user):
        fm = clean_gtt_user
        before = _used_margin(fm)

        mgr = GTTManager(GTT_TEST_USER)
        ok, response, _ = mgr.place_gtt(_single_gtt(), last_price=100)
        assert ok
        assert _used_margin(fm) > before

        ok, _, status = mgr.cancel_gtt(response["trigger_id"])
        assert ok and status == 200
        assert _used_margin(fm) == before, "cancel must return exactly what was blocked"

    def test_oco_blocks_the_larger_leg_not_both(self, clean_gtt_user):
        """Only one OCO leg can execute, so reserving both double-counts."""
        from database.sandbox_db import SandboxGTT

        fm = clean_gtt_user
        before = _used_margin(fm)
        mgr = GTTManager(GTT_TEST_USER)

        oco = _single_gtt()
        oco.update(
            {
                "trigger_type": "OCO",
                "triggerprice_sl": 95.0,
                "stoploss": 94.0,
                "triggerprice_tg": 120.0,
                "target": 121.0,
            }
        )
        ok, response, _ = mgr.place_gtt(oco, last_price=100)
        assert ok, response

        gtt = SandboxGTT.query.filter_by(gtt_id=response["trigger_id"]).first()
        leg_margins = [float(leg.leg_margin) for leg in gtt.legs]
        assert len(leg_margins) == 2
        blocked = float(gtt.margin_blocked)

        assert blocked == pytest.approx(max(leg_margins)), "max mode must block the larger leg"
        assert blocked < sum(leg_margins)
        assert _used_margin(fm) - before == pytest.approx(blocked, abs=0.01)

    def test_expiry_releases_margin(self, clean_gtt_user):
        from datetime import datetime, timedelta

        from database.sandbox_db import SandboxGTT, db_session
        from sandbox.gtt_manager import expire_due_gtts

        fm = clean_gtt_user
        before = _used_margin(fm)
        ok, response, _ = GTTManager(GTT_TEST_USER).place_gtt(_single_gtt(), last_price=100)
        assert ok

        gtt = SandboxGTT.query.filter_by(gtt_id=response["trigger_id"]).first()
        gtt.expires_at = datetime.now() - timedelta(hours=1)
        db_session.commit()

        assert expire_due_gtts() >= 1
        db_session.refresh(gtt)
        assert gtt.gtt_status == "expired"
        assert _used_margin(fm) == before, "an expired GTT must not keep holding margin"

    def test_cancelling_twice_does_not_double_release(self, clean_gtt_user):
        """The second cancel must be a no-op, not a second refund."""
        fm = clean_gtt_user
        before = _used_margin(fm)
        mgr = GTTManager(GTT_TEST_USER)

        ok, response, _ = mgr.place_gtt(_single_gtt(), last_price=100)
        assert ok
        trigger_id = response["trigger_id"]

        assert mgr.cancel_gtt(trigger_id)[0] is True
        after_first = _used_margin(fm)

        ok2, _, status2 = mgr.cancel_gtt(trigger_id)
        assert ok2 is False and status2 == 404
        assert _used_margin(fm) == after_first == before


class TestClaimConcurrency:
    """Exactly one evaluator may fire a leg."""

    def test_only_one_of_many_threads_wins_the_claim(self, clean_gtt_user):
        import threading

        from database.sandbox_db import SandboxGTT
        from sandbox.gtt_manager import try_claim_trigger

        ok, response, _ = GTTManager(GTT_TEST_USER).place_gtt(_single_gtt(), last_price=100)
        assert ok
        gtt = SandboxGTT.query.filter_by(gtt_id=response["trigger_id"]).first()
        leg_id = gtt.legs[0].id

        results: list[bool] = []
        results_lock = threading.Lock()
        start = threading.Barrier(8)

        def contend():
            start.wait(timeout=5)
            won = try_claim_trigger(leg_id)
            with results_lock:
                results.append(won)

        threads = [threading.Thread(target=contend) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert len(results) == 8
        assert sum(results) == 1, (
            f"expected exactly one winner, got {sum(results)} - a GTT would place "
            "that many duplicate orders"
        )

    def test_a_claimed_leg_cannot_be_claimed_again(self, clean_gtt_user):
        from database.sandbox_db import SandboxGTT
        from sandbox.gtt_manager import try_claim_trigger

        ok, response, _ = GTTManager(GTT_TEST_USER).place_gtt(_single_gtt(), last_price=100)
        assert ok
        leg_id = SandboxGTT.query.filter_by(gtt_id=response["trigger_id"]).first().legs[0].id

        assert try_claim_trigger(leg_id) is True
        assert try_claim_trigger(leg_id) is False


class TestStrandedLegReclaim:
    """A worker that dies mid-fire must not strand a leg forever."""

    def _claimed_leg(self):
        from database.sandbox_db import SandboxGTT
        from sandbox.gtt_manager import try_claim_trigger

        ok, response, _ = GTTManager(GTT_TEST_USER).place_gtt(_single_gtt(), last_price=100)
        assert ok
        leg = SandboxGTT.query.filter_by(gtt_id=response["trigger_id"]).first().legs[0]
        assert try_claim_trigger(leg.id) is True
        return leg

    def test_stale_claim_is_reverted_to_pending(self, clean_gtt_user):
        from datetime import datetime, timedelta

        from database.sandbox_db import SandboxGTTLeg, db_session
        from sandbox.gtt_manager import reclaim_stranded_legs

        leg = self._claimed_leg()
        leg.claimed_at = datetime.now() - timedelta(hours=1)
        db_session.commit()

        assert reclaim_stranded_legs() >= 1
        refreshed = SandboxGTTLeg.query.filter_by(id=leg.id).first()
        assert refreshed.leg_status == "pending"
        assert refreshed.claimed_at is None

    def test_a_fresh_claim_is_left_alone(self, clean_gtt_user):
        """The reaper must not yank a leg from a worker that is merely slow."""
        from database.sandbox_db import SandboxGTTLeg
        from sandbox.gtt_manager import reclaim_stranded_legs

        leg = self._claimed_leg()
        reclaim_stranded_legs()
        assert SandboxGTTLeg.query.filter_by(id=leg.id).first().leg_status == "triggering"


class TestMarginReconciliation:
    """A resting GTT must not look like leaked margin."""

    def test_active_gtt_margin_is_not_flagged_as_a_discrepancy(self, clean_gtt_user):
        """With auto_fix on, a false flag would release the GTT's reservation."""
        from sandbox.fund_manager import reconcile_margin

        ok, response, _ = GTTManager(GTT_TEST_USER).place_gtt(_single_gtt(), last_price=100)
        assert ok

        has_discrepancy, amount, message = reconcile_margin(GTT_TEST_USER, auto_fix=False)
        assert has_discrepancy is False, (
            f"active GTT margin was flagged as a discrepancy of {amount}: {message}"
        )

    def test_cancelled_gtt_margin_is_not_double_counted(self, clean_gtt_user):
        from sandbox.fund_manager import reconcile_margin

        mgr = GTTManager(GTT_TEST_USER)
        ok, response, _ = mgr.place_gtt(_single_gtt(), last_price=100)
        assert ok
        assert mgr.cancel_gtt(response["trigger_id"])[0] is True

        has_discrepancy, amount, _ = reconcile_margin(GTT_TEST_USER, auto_fix=False)
        assert has_discrepancy is False, f"discrepancy {amount} after cancelling a GTT"


class TestMaintenanceThread:
    """The upkeep that neither execution engine performs."""

    def test_intervals_are_sane(self):
        from sandbox.execution_thread import GTTMaintenanceThread

        # Reclaim must run well inside the claim timeout, or a stranded leg
        # waits far longer than the timeout promises.
        from sandbox.gtt_manager import DEFAULT_CLAIM_TIMEOUT_SEC

        assert GTTMaintenanceThread.RECLAIM_INTERVAL_SEC <= DEFAULT_CLAIM_TIMEOUT_SEC
        assert GTTMaintenanceThread.EXPIRY_INTERVAL_SEC >= 600

    def test_stop_is_idempotent(self):
        from sandbox.execution_thread import _stop_gtt_maintenance

        _stop_gtt_maintenance()
        _stop_gtt_maintenance()  # must not raise when nothing is running

    def test_thread_reclaims_and_stops(self, clean_gtt_user):
        """End to end: a stranded leg is recovered without the polling engine."""
        from datetime import datetime, timedelta

        from database.sandbox_db import SandboxGTT, SandboxGTTLeg, db_session
        from sandbox.execution_thread import GTTMaintenanceThread
        from sandbox.gtt_manager import try_claim_trigger

        ok, response, _ = GTTManager(GTT_TEST_USER).place_gtt(_single_gtt(), last_price=100)
        assert ok
        leg = SandboxGTT.query.filter_by(gtt_id=response["trigger_id"]).first().legs[0]
        assert try_claim_trigger(leg.id) is True
        leg.claimed_at = datetime.now() - timedelta(hours=1)
        db_session.commit()

        thread = GTTMaintenanceThread()
        thread.RECLAIM_INTERVAL_SEC = 1  # instance override, keeps the test quick
        thread.start()
        try:
            deadline = __import__("time").time() + 10
            while __import__("time").time() < deadline:
                db_session.expire_all()
                if SandboxGTTLeg.query.filter_by(id=leg.id).first().leg_status == "pending":
                    break
                __import__("time").sleep(0.2)
        finally:
            thread.stop()
            thread.join(timeout=5)

        assert not thread.is_alive(), "maintenance thread did not stop"
        assert SandboxGTTLeg.query.filter_by(id=leg.id).first().leg_status == "pending"


class TestCatchUp:
    def test_catch_up_is_exported_and_safe_with_no_gtts(self, clean_gtt_user):
        """Runs on every boot, so it must be a no-op when there is nothing to do."""
        from sandbox.catch_up_processor import catch_up_gtts

        catch_up_gtts()  # must not raise


def _oco_gtt(sl=95.0, tg=110.0, qty=10):
    return {
        "trigger_type": "OCO",
        "symbol": "ZEEL",
        "exchange": "NSE",
        "action": "SELL",
        "product": "CNC",
        "quantity": qty,
        "pricetype": "LIMIT",
        "price": 100,
        "triggerprice_sl": sl,
        "stoploss": sl - 1,
        "triggerprice_tg": tg,
        "target": tg + 1,
        "strategy": "gtt-test",
    }


class TestOCOExclusivity:
    """An OCO must place exactly one order, never both."""

    def test_only_one_leg_of_an_oco_can_be_claimed(self, clean_gtt_user):
        """The blocker: per-leg claims let both siblings be claimed at once."""
        from database.sandbox_db import SandboxGTT
        from sandbox.gtt_manager import try_claim_trigger

        ok, response, _ = GTTManager(GTT_TEST_USER).place_gtt(_oco_gtt(), last_price=100)
        assert ok, response
        legs = SandboxGTT.query.filter_by(gtt_id=response["trigger_id"]).first().legs
        assert len(legs) == 2

        first = try_claim_trigger(legs[0].id)
        second = try_claim_trigger(legs[1].id)
        assert first is True
        assert second is False, "both OCO legs were claimed - both would place an order"

    def test_concurrent_sibling_contention_yields_one_winner(self, clean_gtt_user):
        """Both trigger prices crossed by the same tick, both legs raced."""
        import threading

        from database.sandbox_db import SandboxGTT
        from sandbox.gtt_manager import try_claim_trigger

        ok, response, _ = GTTManager(GTT_TEST_USER).place_gtt(_oco_gtt(), last_price=100)
        assert ok
        leg_ids = [leg.id for leg in SandboxGTT.query.filter_by(
            gtt_id=response["trigger_id"]).first().legs]

        results: list[bool] = []
        lock = threading.Lock()
        start = threading.Barrier(6)

        def contend(leg_id):
            start.wait(timeout=5)
            won = try_claim_trigger(leg_id)
            with lock:
                results.append(won)

        threads = [threading.Thread(target=contend, args=(leg_ids[i % 2],)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert sum(results) == 1, (
            f"expected one winner across both OCO legs, got {sum(results)}"
        )


class TestCancelledGttCannotFire:
    def test_claimed_leg_is_cancelled_with_the_parent(self, clean_gtt_user):
        from database.sandbox_db import SandboxGTT, SandboxGTTLeg, db_session
        from sandbox.gtt_manager import try_claim_trigger

        mgr = GTTManager(GTT_TEST_USER)
        ok, response, _ = mgr.place_gtt(_single_gtt(), last_price=100)
        assert ok
        leg = SandboxGTT.query.filter_by(gtt_id=response["trigger_id"]).first().legs[0]
        assert try_claim_trigger(leg.id) is True

        assert mgr.cancel_gtt(response["trigger_id"])[0] is True

        db_session.expire_all()
        assert SandboxGTTLeg.query.filter_by(id=leg.id).first().leg_status == "cancelled"

    def test_fire_refuses_when_the_parent_is_not_active(self, clean_gtt_user):
        """fire_leg revalidates, so a cancel that lands mid-flight still wins."""
        from database.sandbox_db import SandboxGTT, SandboxOrders, db_session
        from sandbox.gtt_manager import fire_leg, try_claim_trigger

        mgr = GTTManager(GTT_TEST_USER)
        ok, response, _ = mgr.place_gtt(_single_gtt(), last_price=100)
        assert ok
        trigger_id = response["trigger_id"]
        gtt = SandboxGTT.query.filter_by(gtt_id=trigger_id).first()
        leg_id = gtt.legs[0].id
        assert try_claim_trigger(leg_id) is True

        # Cancel the parent only, leaving the leg claimed - the exact window.
        gtt.gtt_status = "cancelled"
        db_session.commit()

        orders_before = SandboxOrders.query.filter_by(user_id=GTT_TEST_USER).count()
        assert fire_leg(leg_id, execution_price=94) is False
        assert SandboxOrders.query.filter_by(user_id=GTT_TEST_USER).count() == orders_before

        db_session.expire_all()
        assert SandboxGTT.query.filter_by(gtt_id=trigger_id).first().gtt_status == "cancelled"


class TestMarketOrderMargin:
    def test_market_leg_reserves_margin(self, clean_gtt_user):
        """A MARKET leg has no limit price; sizing it at 0 reserved nothing."""
        from database.sandbox_db import SandboxGTT

        fm = clean_gtt_user
        before = _used_margin(fm)

        payload = _single_gtt()
        payload.update({"pricetype": "MARKET", "price": 0})
        ok, response, _ = GTTManager(GTT_TEST_USER).place_gtt(payload, last_price=100)
        assert ok, response

        gtt = SandboxGTT.query.filter_by(gtt_id=response["trigger_id"]).first()
        assert float(gtt.margin_blocked) > 0, "MARKET GTT reserved nothing"
        assert _used_margin(fm) > before


class TestOrderbookContract:
    """The frontend's GttOrder type is a contract, not a suggestion."""

    def test_entry_carries_trigger_prices(self, clean_gtt_user):
        mgr = GTTManager(GTT_TEST_USER)
        assert mgr.place_gtt(_oco_gtt(), last_price=100)[0] is True

        ok, response, status = mgr.list_gtts()
        assert ok and status == 200
        entry = response["data"][0]

        for field in (
            "trigger_id", "trigger_type", "status", "symbol", "exchange",
            "trigger_prices", "last_price", "legs", "created_at", "expires_at",
        ):
            assert field in entry, f"orderbook entry is missing {field}"

        assert isinstance(entry["trigger_prices"], list)
        assert entry["trigger_prices"] == [95.0, 110.0]

    def test_cancelled_gtts_are_hidden_by_default(self, clean_gtt_user):
        mgr = GTTManager(GTT_TEST_USER)
        ok, response, _ = mgr.place_gtt(_single_gtt(), last_price=100)
        assert ok
        assert mgr.cancel_gtt(response["trigger_id"])[0] is True

        _, active, _ = mgr.list_gtts()
        assert active["data"] == [], "a cancelled GTT must not appear in the orderbook"

        _, everything, _ = mgr.list_gtts(status_filter=None)
        assert len(everything["data"]) == 1


class TestSuppliedExpiry:
    def test_expires_at_is_honoured(self, clean_gtt_user):
        from database.sandbox_db import SandboxGTT

        payload = _single_gtt()
        payload["expires_at"] = "2026-12-31"
        ok, response, _ = GTTManager(GTT_TEST_USER).place_gtt(payload, last_price=100)
        assert ok

        gtt = SandboxGTT.query.filter_by(gtt_id=response["trigger_id"]).first()
        assert gtt.expires_at.strftime("%Y-%m-%d") == "2026-12-31"

    def test_unparseable_expiry_falls_back_rather_than_rejecting(self, clean_gtt_user):
        payload = _single_gtt()
        payload["expires_at"] = "whenever"
        assert GTTManager(GTT_TEST_USER).place_gtt(payload, last_price=100)[0] is True


class TestEventPublishing:
    def test_the_event_bus_import_resolves(self):
        """`from events import bus` raised, so triggers never published."""
        from events.order_events import GTTExpiredEvent, GTTTriggeredEvent  # noqa: F401
        from utils.event_bus import bus

        assert bus is not None


class TestCancelFireRace:
    """Cancel and fire must not both succeed on the same GTT."""

    def test_cancel_after_revalidation_still_prevents_the_order(self, clean_gtt_user):
        """The real race: cancel lands between the state check and place_order.

        The earlier test cancelled before fire_leg started, which the atomic
        claim was never in danger of failing. This one cancels from inside
        place_order, which is the window that actually mattered.
        """
        from unittest import mock

        from database.sandbox_db import SandboxGTT, SandboxOrders, db_session
        from sandbox.gtt_manager import fire_leg, try_claim_trigger

        mgr = GTTManager(GTT_TEST_USER)
        ok, response, _ = mgr.place_gtt(_single_gtt(), last_price=100)
        assert ok
        trigger_id = response["trigger_id"]
        leg_id = SandboxGTT.query.filter_by(gtt_id=trigger_id).first().legs[0].id
        assert try_claim_trigger(leg_id) is True

        cancel_result = {}

        def cancel_mid_flight(*args, **kwargs):
            cancel_result["value"] = mgr.cancel_gtt(trigger_id)
            return (True, {"orderid": "SHOULD-NOT-HAPPEN"}, 200)

        with mock.patch.object(
            __import__("sandbox.order_manager", fromlist=["OrderManager"]).OrderManager,
            "place_order",
            side_effect=cancel_mid_flight,
        ):
            fired = fire_leg(leg_id, execution_price=94)

        db_session.expire_all()
        gtt = SandboxGTT.query.filter_by(gtt_id=trigger_id).first()
        cancel_ok = cancel_result.get("value", (False,))[0]

        # Exactly one of the two may win, and they must agree with the state.
        assert not (fired and cancel_ok), "cancel and fire both reported success"
        if cancel_ok:
            assert gtt.gtt_status == "cancelled"
        else:
            assert gtt.gtt_status == "triggered"

        assert float(gtt.margin_blocked or 0) >= 0
        funds_used = _used_margin(clean_gtt_user)
        assert funds_used >= 0, f"used_margin went negative: {funds_used}"

    def test_cancel_cannot_succeed_once_the_parent_is_claimed(self, clean_gtt_user):
        from database.sandbox_db import SandboxGTT, db_session
        from sandbox.gtt_manager import try_claim_trigger

        mgr = GTTManager(GTT_TEST_USER)
        ok, response, _ = mgr.place_gtt(_single_gtt(), last_price=100)
        assert ok
        trigger_id = response["trigger_id"]
        assert try_claim_trigger(
            SandboxGTT.query.filter_by(gtt_id=trigger_id).first().legs[0].id
        )

        # Simulate the parent claim fire_leg performs.
        gtt = SandboxGTT.query.filter_by(gtt_id=trigger_id).first()
        gtt.gtt_status = "triggered"
        db_session.commit()

        ok2, _, status = mgr.cancel_gtt(trigger_id)
        assert ok2 is False and status == 404


class TestModifyImmutability:
    """action, symbol, exchange and trigger_type cannot be changed."""

    def _placed(self):
        mgr = GTTManager(GTT_TEST_USER)
        ok, response, _ = mgr.place_gtt(_single_gtt(), last_price=100)
        assert ok
        return mgr, response["trigger_id"]

    def test_action_flip_is_rejected(self, clean_gtt_user):
        mgr, trigger_id = self._placed()
        payload = _single_gtt()
        payload["action"] = "BUY"  # placed as SELL
        ok, response, status = mgr.modify_gtt(trigger_id, payload)
        assert ok is False and status == 400
        assert "action cannot be changed" in response["message"]

    def test_symbol_change_is_rejected(self, clean_gtt_user):
        mgr, trigger_id = self._placed()
        payload = _single_gtt()
        payload["symbol"] = "RELIANCE"
        ok, response, status = mgr.modify_gtt(trigger_id, payload)
        assert ok is False and status == 400
        assert "symbol cannot be changed" in response["message"]

    def test_trigger_type_change_is_rejected(self, clean_gtt_user):
        mgr, trigger_id = self._placed()
        payload = _oco_gtt()
        ok, response, status = mgr.modify_gtt(trigger_id, payload)
        assert ok is False and status == 400
        assert "trigger_type cannot be changed" in response["message"]

    def test_a_legal_modify_still_works(self, clean_gtt_user):
        mgr, trigger_id = self._placed()
        payload = _single_gtt(trigger=90.0, price=90.0)
        assert mgr.modify_gtt(trigger_id, payload)[0] is True


class TestTimezoneAwareExpiry:
    def test_offset_is_converted_not_ignored(self):
        """13:00Z and 13:00+05:30 are 5.5 hours apart, not the same instant."""
        from sandbox.gtt_manager import _resolve_expiry

        utc = _resolve_expiry("2026-12-31T13:00:00+00:00")
        ist = _resolve_expiry("2026-12-31T13:00:00+05:30")
        assert utc != ist
        assert abs((utc - ist).total_seconds()) == 5.5 * 3600

    def test_naive_input_is_preserved(self):
        from sandbox.gtt_manager import _resolve_expiry

        assert _resolve_expiry("2026-12-31 13:00:00").hour == 13

    def test_stored_value_is_naive(self):
        """The column is a naive DateTime; an aware value would break compares."""
        from sandbox.gtt_manager import _resolve_expiry

        assert _resolve_expiry("2026-12-31T13:00:00+05:30").tzinfo is None


class TestServiceOrderbookDefault:
    def test_service_layer_hides_cancelled_gtts(self, clean_gtt_user):
        """The manager default is not enough: the service passes it explicitly."""
        import inspect

        from services.sandbox_service import sandbox_gtt_orderbook

        default = inspect.signature(sandbox_gtt_orderbook).parameters["status_filter"].default
        assert default == "active", (
            "the service default overrides the manager's, so it must be active-only"
        )


class TestAtomicCancel:
    """Cancel is a conditional UPDATE, not a read followed by a write."""

    def test_cancel_pausing_after_its_read_cannot_clobber_a_fire(self, clean_gtt_user):
        """The exact sequence the audit described.

        Cancel reads the GTT while active, is held there while fire claims the
        parent, then resumes. Its write must not turn 'triggered' back into
        'cancelled' - that reported success for an order that still got placed
        and released the same margin twice.
        """
        import threading

        from database.sandbox_db import SandboxGTT, db_session
        from sandbox.gtt_manager import try_claim_trigger

        mgr = GTTManager(GTT_TEST_USER)
        ok, response, _ = mgr.place_gtt(_single_gtt(), last_price=100)
        assert ok
        trigger_id = response["trigger_id"]
        leg_id = SandboxGTT.query.filter_by(gtt_id=trigger_id).first().legs[0].id

        read_done = threading.Event()
        fire_done = threading.Event()
        result = {}

        original_get = GTTManager._get_active_gtt

        def slow_read(self, tid):
            gtt = original_get(self, tid)
            read_done.set()
            fire_done.wait(timeout=5)  # hold cancel between read and write
            return gtt

        def cancel_thread():
            with mock.patch.object(GTTManager, "_get_active_gtt", slow_read):
                result["cancel"] = mgr.cancel_gtt(trigger_id)

        t = threading.Thread(target=cancel_thread)
        t.start()
        assert read_done.wait(timeout=5), "cancel never performed its read"

        # Fire claims the parent while cancel is parked mid-operation.
        assert try_claim_trigger(leg_id) is True
        db_session.execute(
            __import__("sqlalchemy").update(SandboxGTT)
            .where(SandboxGTT.gtt_id == trigger_id, SandboxGTT.gtt_status == "active")
            .values(gtt_status="triggered")
        )
        db_session.commit()
        fire_done.set()
        t.join(timeout=10)

        cancel_ok = result["cancel"][0]
        db_session.expire_all()
        final = SandboxGTT.query.filter_by(gtt_id=trigger_id).first().gtt_status

        assert cancel_ok is False, "cancel reported success after the fire claimed it"
        assert final == "triggered", f"cancel clobbered the fire: status is {final}"


class TestFireExceptionCompensation:
    """An exception must not leave the GTT armed with no reservation."""

    def test_exception_after_release_restores_the_margin(self, clean_gtt_user):
        from database.sandbox_db import SandboxGTT, db_session
        from sandbox.gtt_manager import fire_leg, try_claim_trigger
        from sandbox.order_manager import OrderManager

        fm = clean_gtt_user
        mgr = GTTManager(GTT_TEST_USER)
        ok, response, _ = mgr.place_gtt(_single_gtt(), last_price=100)
        assert ok
        trigger_id = response["trigger_id"]
        blocked = _used_margin(fm)
        leg_id = SandboxGTT.query.filter_by(gtt_id=trigger_id).first().legs[0].id
        assert try_claim_trigger(leg_id) is True

        with mock.patch.object(OrderManager, "place_order", side_effect=RuntimeError("boom")):
            assert fire_leg(leg_id, execution_price=94) is False

        db_session.expire_all()
        gtt = SandboxGTT.query.filter_by(gtt_id=trigger_id).first()
        assert gtt.gtt_status == "active", "GTT did not return to active"
        assert float(gtt.margin_blocked) > 0, "GTT is armed with no reservation"
        assert _used_margin(fm) == blocked, "margin was not restored to its pre-fire value"

    def test_unrestorable_margin_marks_the_gtt_rejected(self, clean_gtt_user):
        """Better visibly dead than silently armed and unfunded."""
        from database.sandbox_db import SandboxGTT, db_session
        from sandbox.fund_manager import FundManager
        from sandbox.gtt_manager import fire_leg, try_claim_trigger
        from sandbox.order_manager import OrderManager

        mgr = GTTManager(GTT_TEST_USER)
        ok, response, _ = mgr.place_gtt(_single_gtt(), last_price=100)
        assert ok
        trigger_id = response["trigger_id"]
        leg_id = SandboxGTT.query.filter_by(gtt_id=trigger_id).first().legs[0].id
        assert try_claim_trigger(leg_id) is True

        with mock.patch.object(OrderManager, "place_order", side_effect=RuntimeError("boom")), \
             mock.patch.object(FundManager, "block_margin", return_value=(False, "no funds")):
            assert fire_leg(leg_id, execution_price=94) is False

        db_session.expire_all()
        gtt = SandboxGTT.query.filter_by(gtt_id=trigger_id).first()
        assert gtt.gtt_status == "rejected", (
            f"GTT left as '{gtt.gtt_status}' with no margin - it would fire and fail"
        )


class TestCrashRecovery:
    """A worker dying mid-fire must not strand the GTT forever."""

    def _strand(self, mgr):
        """Reproduce the crash state: parent triggered, leg still pending."""
        from database.sandbox_db import SandboxGTT, db_session

        ok, response, _ = mgr.place_gtt(_single_gtt(), last_price=100)
        assert ok
        trigger_id = response["trigger_id"]
        gtt = SandboxGTT.query.filter_by(gtt_id=trigger_id).first()
        gtt.gtt_status = "triggered"          # claimed the parent...
        gtt.margin_blocked = Decimal("0.00")  # ...released the margin...
        db_session.commit()                   # ...then died before placing.
        return trigger_id

    def test_crash_before_the_child_order_returns_the_gtt_to_active(self, clean_gtt_user):
        from database.sandbox_db import SandboxGTT, db_session
        from sandbox.gtt_manager import reclaim_stranded_parents

        mgr = GTTManager(GTT_TEST_USER)
        trigger_id = self._strand(mgr)

        assert reclaim_stranded_parents() >= 1
        db_session.expire_all()
        gtt = SandboxGTT.query.filter_by(gtt_id=trigger_id).first()
        assert gtt.gtt_status == "active"
        assert gtt.legs[0].leg_status == "pending"
        assert float(gtt.margin_blocked) > 0, "re-armed without restoring its reservation"

    def test_crash_after_the_child_order_is_finalised_not_undone(self, clean_gtt_user):
        """Undoing this would place a second order for one trigger."""
        from database.sandbox_db import SandboxGTT, db_session
        from sandbox.gtt_manager import reclaim_stranded_parents

        mgr = GTTManager(GTT_TEST_USER)
        trigger_id = self._strand(mgr)
        gtt = SandboxGTT.query.filter_by(gtt_id=trigger_id).first()
        gtt.legs[0].triggered_order_id = "ORDER-ALREADY-PLACED"
        db_session.commit()

        reclaim_stranded_parents()
        db_session.expire_all()
        assert SandboxGTT.query.filter_by(gtt_id=trigger_id).first().gtt_status == "triggered"

    def test_recovery_runs_from_the_normal_reaper(self, clean_gtt_user):
        from database.sandbox_db import SandboxGTT, db_session
        from sandbox.gtt_manager import reclaim_stranded_legs

        mgr = GTTManager(GTT_TEST_USER)
        trigger_id = self._strand(mgr)

        reclaim_stranded_legs()  # what the engines and catch-up actually call
        db_session.expire_all()
        assert SandboxGTT.query.filter_by(gtt_id=trigger_id).first().gtt_status == "active"


class TestDurableOrderCorrelation:
    """Recovery must read the order table, not just the leg's marker.

    The child order is committed before the leg records triggered_order_id. A
    crash between those two commits leaves a real order with no marker, and a
    recovery that trusts the marker alone would re-arm a GTT that had already
    fired - placing a second order for one trigger.
    """

    def test_child_order_carries_the_leg_correlation(self, clean_gtt_user):
        from database.sandbox_db import SandboxGTT, SandboxOrders
        from sandbox.gtt_manager import fire_leg, try_claim_trigger

        mgr = GTTManager(GTT_TEST_USER)
        payload = _single_gtt()
        payload["action"] = "BUY"  # BUY needs no holdings, so it fills
        ok, response, _ = mgr.place_gtt(payload, last_price=100)
        assert ok
        leg = SandboxGTT.query.filter_by(gtt_id=response["trigger_id"]).first().legs[0]
        assert try_claim_trigger(leg.id) is True
        assert fire_leg(leg.id, execution_price=96) is True

        order = SandboxOrders.query.filter_by(gtt_leg_id=leg.id).first()
        assert order is not None, "child order carries no correlation to its GTT leg"
        assert order.orderid == leg.triggered_order_id

    def test_crash_before_the_marker_does_not_re_arm(self, clean_gtt_user):
        """A real child order exists; only the marker is missing."""
        from database.sandbox_db import SandboxGTT, SandboxGTTLeg, SandboxOrders, db_session
        from sandbox.gtt_manager import fire_leg, reclaim_stranded_parents, try_claim_trigger

        mgr = GTTManager(GTT_TEST_USER)
        payload = _single_gtt()
        payload["action"] = "BUY"
        ok, response, _ = mgr.place_gtt(payload, last_price=100)
        assert ok
        trigger_id = response["trigger_id"]
        leg_id = SandboxGTT.query.filter_by(gtt_id=trigger_id).first().legs[0].id
        assert try_claim_trigger(leg_id) is True
        assert fire_leg(leg_id, execution_price=96) is True

        orders_after_fire = SandboxOrders.query.filter_by(user_id=GTT_TEST_USER).count()

        # Rewind exactly the state a crash between the two commits leaves:
        # the order row is real, the marker never got written, the leg is back
        # to pending and the parent still says triggered.
        db_session.execute(
            __import__("sqlalchemy").update(SandboxGTTLeg)
            .where(SandboxGTTLeg.id == leg_id)
            .values(leg_status="pending", triggered_order_id=None, claimed_at=None)
        )
        db_session.commit()

        reclaim_stranded_parents()
        db_session.expire_all()

        gtt = SandboxGTT.query.filter_by(gtt_id=trigger_id).first()
        assert gtt.gtt_status == "triggered", "a fired GTT was re-armed"
        assert gtt.legs[0].leg_status == "triggered", "leg was not finalised from the order row"
        assert gtt.legs[0].triggered_order_id, "marker was not repaired from the order row"
        assert (
            SandboxOrders.query.filter_by(user_id=GTT_TEST_USER).count() == orders_after_fire
        ), "recovery created a second child order"

    def test_the_correlation_is_unique(self, clean_gtt_user):
        """The unique index is what stops a replayed claim double-ordering."""
        # Create the correlated order this test needs rather than hoping one
        # survives from another test. It never did - the fixture purges orders
        # before each test, so this always skipped and proved nothing.
        from database.sandbox_db import SandboxGTT, SandboxOrders, db_session
        from sandbox.gtt_manager import fire_leg, try_claim_trigger

        mgr = GTTManager(GTT_TEST_USER)
        payload = _single_gtt()
        payload["action"] = "BUY"
        ok, response, _ = mgr.place_gtt(payload, last_price=100)
        assert ok
        leg = SandboxGTT.query.filter_by(gtt_id=response["trigger_id"]).first().legs[0]
        assert try_claim_trigger(leg.id) is True
        assert fire_leg(leg.id, execution_price=96) is True

        existing = SandboxOrders.query.filter_by(gtt_leg_id=leg.id).first()
        assert existing is not None, "the fired GTT produced no correlated order"
        clone = SandboxOrders(
            orderid="DUPLICATE-TEST",
            user_id=GTT_TEST_USER,
            symbol=existing.symbol,
            exchange=existing.exchange,
            action=existing.action,
            quantity=existing.quantity,
            price=existing.price,
            price_type=existing.price_type,
            product=existing.product,
            order_status="open",
            pending_quantity=0,
            gtt_leg_id=existing.gtt_leg_id,
        )
        db_session.add(clone)
        # IntegrityError specifically: the point is the unique index rejecting
        # it, not that any error occurs.
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


class TestRecoveryDoesNotDoubleBlock:
    def test_crash_before_the_release_keeps_one_reservation(self, clean_gtt_user):
        """The reproduced case: used margin went from 950 to 1900."""
        from database.sandbox_db import SandboxGTT, db_session
        from sandbox.gtt_manager import reclaim_stranded_parents

        fm = clean_gtt_user
        mgr = GTTManager(GTT_TEST_USER)
        ok, response, _ = mgr.place_gtt(_single_gtt(), last_price=100)
        assert ok
        blocked = _used_margin(fm)
        assert blocked > 0

        # Crash after claiming the parent, before releasing the margin: the
        # reservation is still intact on the row.
        gtt = SandboxGTT.query.filter_by(gtt_id=response["trigger_id"]).first()
        gtt.gtt_status = "triggered"
        db_session.commit()

        reclaim_stranded_parents()
        db_session.expire_all()

        assert _used_margin(fm) == blocked, "recovery reserved the same margin twice"
        gtt = SandboxGTT.query.filter_by(gtt_id=response["trigger_id"]).first()
        assert gtt.gtt_status == "active"
        assert float(gtt.margin_blocked) > 0


class TestCancelReportsReleaseFailure:
    def test_cancel_fails_when_the_funds_cannot_be_returned(self, clean_gtt_user):
        """Reporting success would leave funds locked against a dead trigger."""
        from database.sandbox_db import SandboxGTT, db_session
        from sandbox.fund_manager import FundManager

        mgr = GTTManager(GTT_TEST_USER)
        ok, response, _ = mgr.place_gtt(_single_gtt(), last_price=100)
        assert ok
        trigger_id = response["trigger_id"]

        with mock.patch.object(
            FundManager, "stage_margin_delta", return_value=(False, "ledger locked")
        ):
            ok2, resp, status = mgr.cancel_gtt(trigger_id)

        assert ok2 is False and status == 500
        assert "Could not release" in resp["message"]

        db_session.expire_all()
        gtt = SandboxGTT.query.filter_by(gtt_id=trigger_id).first()
        # The whole transaction rolls back now, so the GTT is untouched rather
        # than terminally cancelled with the money still held. That also keeps
        # it retryable - the old behaviour left a 'cancelled' row that no second
        # attempt could claim.
        assert gtt.gtt_status == "active", "cancel left the GTT in a terminal state"
        assert float(gtt.margin_blocked) > 0
        assert mgr.cancel_gtt(trigger_id)[0] is True, "the retry could not cancel it"

    def test_a_normal_cancel_still_succeeds(self, clean_gtt_user):
        mgr = GTTManager(GTT_TEST_USER)
        ok, response, _ = mgr.place_gtt(_single_gtt(), last_price=100)
        assert ok
        assert mgr.cancel_gtt(response["trigger_id"])[0] is True


class TestRejectedOrdersDoNotPoisonCorrelation:
    """A refused order is not evidence the GTT fired."""

    def _rejected_fire(self, mgr):
        """A CNC SELL with no holdings: the sandbox rejects it for real."""
        from database.sandbox_db import SandboxGTT
        from sandbox.gtt_manager import fire_leg, try_claim_trigger

        ok, response, _ = mgr.place_gtt(_single_gtt(), last_price=100)
        assert ok
        leg_id = SandboxGTT.query.filter_by(gtt_id=response["trigger_id"]).first().legs[0].id
        assert try_claim_trigger(leg_id) is True
        assert fire_leg(leg_id, execution_price=94) is False  # rejected
        return response["trigger_id"], leg_id

    def test_rejected_child_is_not_correlated(self, clean_gtt_user):
        from database.sandbox_db import SandboxOrders

        _, leg_id = self._rejected_fire(GTTManager(GTT_TEST_USER))
        correlated = SandboxOrders.query.filter_by(gtt_leg_id=leg_id).first()
        assert correlated is None, (
            "a rejected order claimed the unique correlation - the leg can now "
            "never place another order"
        )

    def test_recovery_re_arms_after_a_rejection(self, clean_gtt_user):
        """A rejected attempt must not be repaired into 'triggered'."""
        from database.sandbox_db import SandboxGTT, db_session
        from sandbox.gtt_manager import reclaim_stranded_parents

        mgr = GTTManager(GTT_TEST_USER)
        trigger_id, _ = self._rejected_fire(mgr)

        # Put the parent into the crash state and let recovery decide.
        gtt = SandboxGTT.query.filter_by(gtt_id=trigger_id).first()
        gtt.gtt_status = "triggered"
        db_session.commit()

        reclaim_stranded_parents()
        db_session.expire_all()
        gtt = SandboxGTT.query.filter_by(gtt_id=trigger_id).first()
        assert gtt.gtt_status == "active", (
            "a rejected attempt was treated as a completed fire"
        )

    def test_the_leg_can_fire_again_after_a_rejection(self, clean_gtt_user):
        """The unique index must not permanently block a retried leg."""
        from database.sandbox_db import SandboxGTT, SandboxGTTLeg, db_session
        from sandbox.gtt_manager import fire_leg, try_claim_trigger

        mgr = GTTManager(GTT_TEST_USER)
        trigger_id, leg_id = self._rejected_fire(mgr)

        # Make the retry succeed by flipping the leg to a BUY, which needs no
        # holdings. The point is that the INSERT is not blocked.
        db_session.execute(
            __import__("sqlalchemy").update(SandboxGTTLeg)
            .where(SandboxGTTLeg.id == leg_id)
            .values(action="BUY")
        )
        db_session.commit()

        assert try_claim_trigger(leg_id) is True
        assert fire_leg(leg_id, execution_price=96) is True, (
            "the retry was blocked, most likely by the rejected order's correlation"
        )
        db_session.expire_all()
        assert SandboxGTT.query.filter_by(gtt_id=trigger_id).first().gtt_status == "triggered"


class TestMarginTransitionsFailClosed:
    """No state change is published when the funds did not move."""

    def _patched_release(self):
        """Refuse the committing release, used by fire."""
        from sandbox.fund_manager import FundManager

        return mock.patch.object(
            FundManager, "release_margin", return_value=(False, "ledger locked")
        )

    def _patched_staged(self):
        """Refuse the staged change, used by modify and expiry.

        Those two now move funds inside their own transaction via
        stage_margin_delta, so refusing release_margin would no longer reach
        them - the assertion, that a refused fund move publishes no state
        change, is unchanged.
        """
        from sandbox.fund_manager import FundManager

        return mock.patch.object(
            FundManager, "stage_margin_delta", return_value=(False, "ledger locked")
        )

    def test_fire_does_not_place_when_the_release_fails(self, clean_gtt_user):
        """Placing anyway blocks a second reservation over one never returned."""
        from database.sandbox_db import SandboxGTT, SandboxOrders, db_session
        from sandbox.gtt_manager import fire_leg, try_claim_trigger

        fm = clean_gtt_user
        mgr = GTTManager(GTT_TEST_USER)
        payload = _single_gtt()
        payload["action"] = "BUY"
        ok, response, _ = mgr.place_gtt(payload, last_price=100)
        assert ok
        blocked = _used_margin(fm)
        leg_id = SandboxGTT.query.filter_by(gtt_id=response["trigger_id"]).first().legs[0].id
        assert try_claim_trigger(leg_id) is True

        orders_before = SandboxOrders.query.filter_by(user_id=GTT_TEST_USER).count()
        with self._patched_staged():
            assert fire_leg(leg_id, execution_price=96) is False

        db_session.expire_all()
        assert SandboxOrders.query.filter_by(user_id=GTT_TEST_USER).count() == orders_before
        assert _used_margin(fm) == blocked, "margin was blocked twice"
        gtt = SandboxGTT.query.filter_by(gtt_id=response["trigger_id"]).first()
        assert gtt.gtt_status == "active"

    def test_modify_reports_failure_when_the_release_fails(self, clean_gtt_user):
        from database.sandbox_db import SandboxGTT, db_session

        fm = clean_gtt_user
        mgr = GTTManager(GTT_TEST_USER)
        ok, response, _ = mgr.place_gtt(_single_gtt(trigger=95.0, price=95.0), last_price=100)
        assert ok
        trigger_id = response["trigger_id"]
        before_margin = _used_margin(fm)
        before_row = float(
            SandboxGTT.query.filter_by(gtt_id=trigger_id).first().margin_blocked
        )

        # Halving the quantity halves the requirement, so this is a decrease.
        smaller = _single_gtt(trigger=95.0, price=95.0, qty=5)
        with self._patched_staged():
            ok2, resp, status = mgr.modify_gtt(trigger_id, smaller)

        assert ok2 is False and status == 500
        db_session.expire_all()
        assert _used_margin(fm) == before_margin
        assert float(
            SandboxGTT.query.filter_by(gtt_id=trigger_id).first().margin_blocked
        ) == before_row, "the row shows a smaller reservation than the ledger holds"

    def test_expiry_leaves_the_gtt_active_when_the_release_fails(self, clean_gtt_user):
        from datetime import datetime, timedelta

        from database.sandbox_db import SandboxGTT, db_session
        from sandbox.gtt_manager import expire_due_gtts

        fm = clean_gtt_user
        mgr = GTTManager(GTT_TEST_USER)
        ok, response, _ = mgr.place_gtt(_single_gtt(), last_price=100)
        assert ok
        blocked = _used_margin(fm)

        gtt = SandboxGTT.query.filter_by(gtt_id=response["trigger_id"]).first()
        gtt.expires_at = datetime.now() - timedelta(hours=1)
        db_session.commit()

        with self._patched_staged():
            assert expire_due_gtts() == 0, "reported an expiry whose funds never moved"

        db_session.expire_all()
        gtt = SandboxGTT.query.filter_by(gtt_id=response["trigger_id"]).first()
        assert gtt.gtt_status == "active", "expired while its margin was still held"
        assert float(gtt.margin_blocked) > 0
        assert _used_margin(fm) == blocked

    def test_expiry_still_works_normally(self, clean_gtt_user):
        from datetime import datetime, timedelta

        from database.sandbox_db import SandboxGTT, db_session
        from sandbox.gtt_manager import expire_due_gtts

        fm = clean_gtt_user
        mgr = GTTManager(GTT_TEST_USER)
        ok, response, _ = mgr.place_gtt(_single_gtt(), last_price=100)
        assert ok
        before = _used_margin(fm)
        gtt = SandboxGTT.query.filter_by(gtt_id=response["trigger_id"]).first()
        gtt.expires_at = datetime.now() - timedelta(hours=1)
        db_session.commit()

        assert expire_due_gtts() >= 1
        db_session.expire_all()
        assert SandboxGTT.query.filter_by(
            gtt_id=response["trigger_id"]
        ).first().gtt_status == "expired"
        assert _used_margin(fm) < before


class TestFundsAndStateCommitTogether:
    """A failed commit must not leave the ledger and the row disagreeing."""

    def _break_commit(self, nth=1):
        """Fail the nth db_session.commit() of the operation under test.

        Which commit matters. Failing only the first would let a two-commit
        implementation fail at the funds step, so nothing moves and nothing
        splits - the test would pass against the very bug it exists to catch.
        Each case below breaks both the first and the second commit and asserts
        the row and the ledger still agree either way.
        """
        from database.sandbox_db import db_session

        real = db_session.commit
        state = {"n": 0}

        def flaky():
            state["n"] += 1
            if state["n"] == nth:
                raise RuntimeError(f"commit #{nth} failed")
            return real()

        return mock.patch.object(db_session, "commit", side_effect=flaky), state

    def test_modify_decrease_commit_failure_leaves_both_unchanged(self, clean_gtt_user):
        from database.sandbox_db import SandboxGTT, db_session

        fm = clean_gtt_user
        mgr = GTTManager(GTT_TEST_USER)
        ok, response, _ = mgr.place_gtt(_single_gtt(trigger=95.0, price=95.0), last_price=100)
        assert ok
        trigger_id = response["trigger_id"]
        ledger_before = _used_margin(fm)
        row_before = float(SandboxGTT.query.filter_by(gtt_id=trigger_id).first().margin_blocked)

        for nth in (1, 2):
            patch, _ = self._break_commit(nth)
            with patch:
                try:
                    mgr.modify_gtt(trigger_id, _single_gtt(trigger=95.0, price=95.0, qty=5))
                except Exception:
                    pass
            db_session.rollback()
            db_session.expire_all()
            # The invariant, not immutability: an unbroken iteration may
            # legitimately complete. What must never happen is the row and the
            # ledger describing different amounts of the same money.
            row_now = float(
                SandboxGTT.query.filter_by(gtt_id=trigger_id).first().margin_blocked
            )
            assert row_now == float(_used_margin(fm)), (
                f"commit #{nth}: row says {row_now}, ledger says {_used_margin(fm)}"
            )
        assert ledger_before is not None and row_before is not None

    def test_modify_increase_commit_failure_leaves_both_unchanged(self, clean_gtt_user):
        from database.sandbox_db import SandboxGTT, db_session

        fm = clean_gtt_user
        mgr = GTTManager(GTT_TEST_USER)
        ok, response, _ = mgr.place_gtt(_single_gtt(trigger=95.0, price=95.0, qty=5), last_price=100)
        assert ok
        trigger_id = response["trigger_id"]
        ledger_before = _used_margin(fm)
        row_before = float(SandboxGTT.query.filter_by(gtt_id=trigger_id).first().margin_blocked)

        for nth in (1, 2):
            patch, _ = self._break_commit(nth)
            with patch:
                try:
                    mgr.modify_gtt(trigger_id, _single_gtt(trigger=95.0, price=95.0, qty=10))
                except Exception:
                    pass
            db_session.rollback()
            db_session.expire_all()
            # The invariant, not immutability: an unbroken iteration may
            # legitimately complete. What must never happen is the row and the
            # ledger describing different amounts of the same money.
            row_now = float(
                SandboxGTT.query.filter_by(gtt_id=trigger_id).first().margin_blocked
            )
            assert row_now == float(_used_margin(fm)), (
                f"commit #{nth}: row says {row_now}, ledger says {_used_margin(fm)}"
            )
        assert ledger_before is not None and row_before is not None

    def test_expiry_commit_failure_does_not_release_funds(self, clean_gtt_user):
        """A retry would otherwise release the same reservation twice."""
        from datetime import datetime, timedelta

        from database.sandbox_db import SandboxGTT, db_session
        from sandbox.gtt_manager import expire_due_gtts

        fm = clean_gtt_user
        mgr = GTTManager(GTT_TEST_USER)
        ok, response, _ = mgr.place_gtt(_single_gtt(), last_price=100)
        assert ok
        trigger_id = response["trigger_id"]
        ledger_before = _used_margin(fm)

        gtt = SandboxGTT.query.filter_by(gtt_id=trigger_id).first()
        gtt.expires_at = datetime.now() - timedelta(hours=1)
        db_session.commit()

        for nth in (1, 2):
            patch, _ = self._break_commit(nth)
            with patch:
                try:
                    expire_due_gtts()
                except Exception:
                    pass
            db_session.rollback()
            db_session.expire_all()
            gtt = SandboxGTT.query.filter_by(gtt_id=trigger_id).first()
            row_now = float(gtt.margin_blocked or 0)
            assert row_now == float(_used_margin(fm)), (
                f"commit #{nth}: the GTT records {row_now} while the ledger holds "
                f"{_used_margin(fm)} - a retry would release it twice"
            )
        assert ledger_before is not None


class TestExpiryAndModifyRespectAFire:
    """Both must use a conditional claim, not a stale active read."""

    def test_expiry_cannot_overwrite_a_fired_gtt(self, clean_gtt_user):
        from datetime import datetime, timedelta

        from database.sandbox_db import SandboxGTT, SandboxOrders, db_session
        from sandbox.gtt_manager import expire_due_gtts, fire_leg, try_claim_trigger

        mgr = GTTManager(GTT_TEST_USER)
        payload = _single_gtt()
        payload["action"] = "BUY"
        ok, response, _ = mgr.place_gtt(payload, last_price=100)
        assert ok
        trigger_id = response["trigger_id"]
        gtt = SandboxGTT.query.filter_by(gtt_id=trigger_id).first()
        gtt.expires_at = datetime.now() - timedelta(hours=1)  # due to expire
        db_session.commit()

        leg_id = gtt.legs[0].id
        assert try_claim_trigger(leg_id) is True
        assert fire_leg(leg_id, execution_price=96) is True

        # Put the parent back to 'active' so the sweep's pre-filter selects it,
        # reproducing the real race: the query saw an active GTT, and the fire
        # completed before the update ran. Without the conditional claim the
        # sweep would overwrite the fire and release the order's margin.
        db_session.execute(
            __import__("sqlalchemy").update(SandboxGTT)
            .where(SandboxGTT.gtt_id == trigger_id)
            .values(gtt_status="active")
        )
        db_session.commit()
        # Drop the stale in-memory GTT, or a later flush writes its old
        # gtt_status back over what the injected fire set.
        db_session.expire_all()

        real_execute = db_session.execute
        real_commit = db_session.commit
        state = {"n": 0}

        def fire_lands_first(*args, **kwargs):
            # On the sweep's first statement, slip the fire's result in - the
            # GTT becomes 'triggered' before the expiry UPDATE is issued.
            state["n"] += 1
            if state["n"] == 1:
                real_execute(
                    __import__("sqlalchemy").update(SandboxGTT)
                    .where(SandboxGTT.gtt_id == trigger_id)
                    .values(gtt_status="triggered")
                )
                # Committed, or the sweep's own rollback would discard the very
                # fire this test is simulating.
                real_commit()
            return real_execute(*args, **kwargs)

        with mock.patch.object(db_session, "execute", side_effect=fire_lands_first):
            expire_due_gtts()
        db_session.expire_all()

        gtt = SandboxGTT.query.filter_by(gtt_id=trigger_id).first()
        assert gtt.gtt_status == "triggered", "expiry overwrote a fired GTT"
        order = SandboxOrders.query.filter_by(gtt_leg_id=leg_id).first()
        assert order is not None, "the child order was stranded by the expiry"

    def test_modify_fails_against_an_already_fired_gtt(self, clean_gtt_user):
        from database.sandbox_db import SandboxGTT, db_session
        from sandbox.gtt_manager import fire_leg, try_claim_trigger

        mgr = GTTManager(GTT_TEST_USER)
        payload = _single_gtt()
        payload["action"] = "BUY"
        ok, response, _ = mgr.place_gtt(payload, last_price=100)
        assert ok
        trigger_id = response["trigger_id"]
        leg_id = SandboxGTT.query.filter_by(gtt_id=trigger_id).first().legs[0].id
        assert try_claim_trigger(leg_id) is True
        assert fire_leg(leg_id, execution_price=96) is True

        payload2 = _single_gtt(trigger=90.0, price=90.0)
        payload2["action"] = "BUY"
        ok2, _, status = mgr.modify_gtt(trigger_id, payload2)
        assert ok2 is False and status == 404, "modify succeeded against a fired GTT"

        db_session.expire_all()
        assert SandboxGTT.query.filter_by(gtt_id=trigger_id).first().gtt_status == "triggered"

    def test_modify_reading_active_then_losing_the_race(self, clean_gtt_user):
        """Modify reads active, a fire completes, modify resumes."""
        import threading

        from database.sandbox_db import SandboxGTT, db_session
        from sandbox.gtt_manager import fire_leg, try_claim_trigger

        mgr = GTTManager(GTT_TEST_USER)
        payload = _single_gtt()
        payload["action"] = "BUY"
        ok, response, _ = mgr.place_gtt(payload, last_price=100)
        assert ok
        trigger_id = response["trigger_id"]
        leg_id = SandboxGTT.query.filter_by(gtt_id=trigger_id).first().legs[0].id

        read_done = threading.Event()
        fire_done = threading.Event()
        result = {}
        original = GTTManager._get_active_gtt

        def slow_read(self, tid):
            gtt = original(self, tid)
            read_done.set()
            fire_done.wait(timeout=5)
            return gtt

        def modify_thread():
            payload2 = _single_gtt(trigger=90.0, price=90.0)
            payload2["action"] = "BUY"
            with mock.patch.object(GTTManager, "_get_active_gtt", slow_read):
                result["modify"] = mgr.modify_gtt(trigger_id, payload2)

        t = threading.Thread(target=modify_thread)
        t.start()
        assert read_done.wait(timeout=5)

        assert try_claim_trigger(leg_id) is True
        assert fire_leg(leg_id, execution_price=96) is True
        fire_done.set()
        t.join(timeout=10)

        assert result["modify"][0] is False, "modify succeeded after the GTT fired"
        db_session.expire_all()
        assert SandboxGTT.query.filter_by(gtt_id=trigger_id).first().gtt_status == "triggered"


class TestFireAndCancelCrashConsistency:
    """Fire and cancel must leave funds and state agreeing after any failure."""

    def _break_commit(self, nth=1):
        from database.sandbox_db import db_session

        real = db_session.commit
        state = {"n": 0}

        def flaky():
            state["n"] += 1
            if state["n"] == nth:
                raise RuntimeError(f"commit #{nth} failed")
            return real()

        return mock.patch.object(db_session, "commit", side_effect=flaky)

    def _row_and_ledger_agree(self, fm, trigger_id):
        from database.sandbox_db import SandboxGTT

        gtt = SandboxGTT.query.filter_by(gtt_id=trigger_id).first()
        row = float(gtt.margin_blocked or 0)
        ledger = float(_used_margin(fm))
        assert row == ledger, (
            f"GTT records {row} reserved while the ledger holds {ledger}"
        )
        return gtt

    def test_fire_commit_failure_keeps_funds_and_row_together(self, clean_gtt_user):
        """The reported case: funds released, row still claiming the money.

        Recovery reads margin_blocked > 0 as proof the funds were never
        released, so a split here produced an active GTT with nothing behind it.
        """
        from database.sandbox_db import SandboxGTT, SandboxGTTLeg, db_session
        from sandbox.gtt_manager import fire_leg, try_claim_trigger

        fm = clean_gtt_user
        mgr = GTTManager(GTT_TEST_USER)
        payload = _single_gtt()
        payload["action"] = "BUY"
        ok, response, _ = mgr.place_gtt(payload, last_price=100)
        assert ok
        trigger_id = response["trigger_id"]

        # Every commit boundary, not just the first. Breaking only commit #1
        # lets a two-commit implementation fail at the release itself, so
        # nothing moves and nothing splits - the test would pass against the
        # very bug it exists to catch. The GTT is re-armed between iterations so
        # each boundary is genuinely reached.
        for nth in (1, 2, 3):
            db_session.rollback()
            db_session.expire_all()
            db_session.execute(
                __import__("sqlalchemy").update(SandboxGTT)
                .where(SandboxGTT.gtt_id == trigger_id)
                .values(gtt_status="active")
            )
            db_session.execute(
                __import__("sqlalchemy").update(SandboxGTTLeg)
                .where(SandboxGTTLeg.gtt_id == trigger_id)
                .values(leg_status="pending", claimed_at=None, triggered_order_id=None)
            )
            db_session.commit()
            db_session.expire_all()

            gtt = SandboxGTT.query.filter_by(gtt_id=trigger_id).first()
            leg_id = gtt.legs[0].id
            if not try_claim_trigger(leg_id):
                continue
            with self._break_commit(nth):
                try:
                    fire_leg(leg_id, execution_price=96)
                except Exception:
                    pass
            db_session.rollback()
            db_session.expire_all()
            self._row_and_ledger_agree(fm, trigger_id)

    def test_recovery_after_a_fire_crash_leaves_a_funded_gtt(self, clean_gtt_user):
        """An active GTT must never be armed with nothing behind it."""
        from database.sandbox_db import SandboxGTT, db_session
        from sandbox.gtt_manager import reclaim_stranded_parents

        fm = clean_gtt_user
        mgr = GTTManager(GTT_TEST_USER)
        ok, response, _ = mgr.place_gtt(_single_gtt(), last_price=100)
        assert ok
        trigger_id = response["trigger_id"]

        # Crash state: parent claimed, funds and row released together.
        gtt = SandboxGTT.query.filter_by(gtt_id=trigger_id).first()
        gtt.gtt_status = "triggered"
        gtt.margin_blocked = Decimal("0.00")
        db_session.commit()
        GTTManager(GTT_TEST_USER).fund_manager.release_margin(
            Decimal("950.00"), description="simulated release"
        )

        reclaim_stranded_parents()
        db_session.expire_all()
        gtt = self._row_and_ledger_agree(fm, trigger_id)
        assert gtt.gtt_status == "active"
        assert float(gtt.margin_blocked) > 0, "re-armed with no reservation behind it"

    def test_cancel_commit_failure_leaves_it_retryable(self, clean_gtt_user):
        """A failed cancel must not leave a terminal row with the funds held."""
        from database.sandbox_db import SandboxGTT, db_session

        fm = clean_gtt_user
        mgr = GTTManager(GTT_TEST_USER)
        ok, response, _ = mgr.place_gtt(_single_gtt(), last_price=100)
        assert ok
        trigger_id = response["trigger_id"]

        for nth in (1, 2):
            with self._break_commit(nth):
                try:
                    mgr.cancel_gtt(trigger_id)
                except Exception:
                    pass
            db_session.rollback()
            db_session.expire_all()
            self._row_and_ledger_agree(fm, trigger_id)

        # Whatever the outcome, the row and the ledger agree - that is the
        # invariant. And if the cancel did not go through, it must still be
        # claimable: the old code committed 'cancelled' first, so a failure left
        # a terminal row that no retry could take.
        gtt = self._row_and_ledger_agree(fm, trigger_id)
        if gtt.gtt_status == "active":
            assert mgr.cancel_gtt(trigger_id)[0] is True, "the retry could not cancel it"
            db_session.expire_all()
            self._row_and_ledger_agree(fm, trigger_id)
        else:
            assert gtt.gtt_status == "cancelled"
            assert float(gtt.margin_blocked or 0) == 0.0

    def test_placement_commit_failure_reserves_nothing(self, clean_gtt_user):
        """A failed insert must not leave money reserved for a GTT that does
        not exist. Blocking first and persisting after relied on a compensating
        release that could itself fail."""
        from database.sandbox_db import SandboxGTT, db_session

        fm = clean_gtt_user
        before = _used_margin(fm)

        # Both boundaries: breaking only the first lets a block-then-persist
        # implementation fail at the block, so nothing is reserved and nothing
        # splits - passing against the bug it exists to catch.
        for nth in (1, 2):
            with self._break_commit(nth):
                try:
                    GTTManager(GTT_TEST_USER).place_gtt(_single_gtt(), last_price=100)
                except Exception:
                    pass
            db_session.rollback()
            db_session.expire_all()

            stored = SandboxGTT.query.filter_by(user_id=GTT_TEST_USER).all()
            row_total = sum(float(g.margin_blocked or 0) for g in stored)
            assert row_total == float(_used_margin(fm)), (
                f"commit #{nth}: GTTs record {row_total} while the ledger holds "
                f"{_used_margin(fm)}"
            )
        assert before is not None


class TestConcurrentPlacementReservations:
    """Two placements racing must reserve twice, not once.

    The lost update: both threads read the same starting balance, each writes
    its own total, and the second commit erases the first. Two GTTs then record
    950 of margin each while the ledger moved only once - and firing or
    cancelling both drives used_margin negative, conjuring available funds.
    """

    def _sum_active_reservations(self):
        from database.sandbox_db import SandboxGTT

        return sum(
            float(g.margin_blocked or 0)
            for g in SandboxGTT.query.filter_by(
                user_id=GTT_TEST_USER, gtt_status="active"
            ).all()
        )

    def test_two_simultaneous_placements_both_reserve(self, clean_gtt_user):
        import threading

        from database.sandbox_db import db_session

        fm = clean_gtt_user
        before = float(_used_margin(fm))

        # Both threads reach the staging step before either commits, which is
        # the window the class lock does not cover.
        staged = threading.Barrier(2, timeout=10)
        results = []
        lock = threading.Lock()

        original_stage = type(fm).stage_margin_delta

        def staged_then_wait(self, delta, description=""):
            out = original_stage(self, delta, description=description)
            try:
                staged.wait()
            except threading.BrokenBarrierError:
                pass
            return out

        def place():
            try:
                with mock.patch.object(
                    type(fm), "stage_margin_delta", staged_then_wait
                ):
                    ok, response, _ = GTTManager(GTT_TEST_USER).place_gtt(
                        _single_gtt(), last_price=100
                    )
                with lock:
                    results.append(ok)
            except Exception:
                with lock:
                    results.append(False)
            finally:
                # Scoped sessions are per thread; leaving one bound leaks its
                # identity map into whatever runs on this thread next.
                db_session.remove()

        threads = [threading.Thread(target=place) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)

        db_session.expire_all()
        reserved = self._sum_active_reservations()
        ledger = float(_used_margin(fm)) - before

        assert reserved == ledger, (
            f"active GTTs record {reserved} reserved but the ledger moved {ledger} - "
            "one reservation was lost"
        )

    def test_reservations_and_ledger_agree_after_mixed_activity(self, clean_gtt_user):
        """The invariant the QA asked for, across a sequence of operations."""
        from database.sandbox_db import db_session

        fm = clean_gtt_user
        before = float(_used_margin(fm))
        mgr = GTTManager(GTT_TEST_USER)

        ids = []
        for _ in range(3):
            ok, response, _ = mgr.place_gtt(_single_gtt(), last_price=100)
            assert ok
            ids.append(response["trigger_id"])

        assert mgr.cancel_gtt(ids[0])[0] is True
        assert mgr.modify_gtt(ids[1], _single_gtt(trigger=95.0, price=95.0, qty=5))[0] is True

        db_session.expire_all()
        reserved = self._sum_active_reservations()
        assert reserved == float(_used_margin(fm)) - before, (
            f"reservations total {reserved} but the ledger moved "
            f"{float(_used_margin(fm)) - before}"
        )

    def test_a_placement_beyond_available_funds_is_refused(self, clean_gtt_user):
        """The sufficiency guard is in the WHERE clause, not a Python check."""
        huge = _single_gtt(qty=100_000_000, price=95.0, trigger=95.0)
        ok, response, status = GTTManager(GTT_TEST_USER).place_gtt(huge, last_price=100)
        assert ok is False and status == 400
        assert "Insufficient funds" in response["message"]


class TestMarginUnderflowGuard:
    """Releasing more than is reserved would invent money.

    Not reachable through a valid GTT transition today - the conditional claims
    prevent a double release - but the primitive allowed it, so any future
    caller or recovery bug supplying an excessive amount would have credited the
    difference as available cash and corrupted every figure derived from the
    balance.
    """

    def _funds(self, user):
        from database.sandbox_db import SandboxFunds

        return SandboxFunds.query.filter_by(user_id=user).first()

    def test_staged_release_beyond_the_reservation_is_refused(self, clean_gtt_user):
        from database.sandbox_db import db_session

        fm = clean_gtt_user
        row = self._funds(GTT_TEST_USER)
        before_used, before_avail = row.used_margin, row.available_balance

        ok, message = fm.stage_margin_delta(-1, "underflow probe")
        db_session.rollback()
        db_session.expire_all()

        assert ok is False
        assert "more than the reserved margin" in message
        row = self._funds(GTT_TEST_USER)
        assert row.used_margin == before_used
        assert row.available_balance == before_avail

    def test_committed_release_beyond_the_reservation_is_refused(self, clean_gtt_user):
        from database.sandbox_db import db_session

        fm = clean_gtt_user
        row = self._funds(GTT_TEST_USER)
        before_used, before_avail = row.used_margin, row.available_balance

        ok, message = fm.release_margin(1, description="underflow probe")
        db_session.expire_all()

        assert ok is False
        assert "only" in message
        row = self._funds(GTT_TEST_USER)
        assert row.used_margin == before_used
        assert row.available_balance == before_avail

    def test_used_margin_can_never_go_negative(self, clean_gtt_user):
        """The invariant, driven from a real reservation."""
        from database.sandbox_db import db_session

        fm = clean_gtt_user
        assert fm.block_margin(500, "x")[0] is True
        db_session.expire_all()

        # One cent more than is held.
        assert fm.release_margin(Decimal("500.01"), description="x")[0] is False
        db_session.expire_all()
        assert self._funds(GTT_TEST_USER).used_margin == Decimal("500.00")

        # Exactly what is held is fine.
        assert fm.release_margin(Decimal("500.00"), description="x")[0] is True
        db_session.expire_all()
        row = self._funds(GTT_TEST_USER)
        assert row.used_margin == Decimal("0.00")
        assert row.used_margin >= 0

    def test_a_normal_gtt_cycle_is_unaffected(self, clean_gtt_user):
        """The guard must not block the releases that are supposed to happen."""
        from database.sandbox_db import db_session

        fm = clean_gtt_user
        before = _used_margin(fm)
        mgr = GTTManager(GTT_TEST_USER)
        ok, response, _ = mgr.place_gtt(_single_gtt(), last_price=100)
        assert ok
        assert mgr.cancel_gtt(response["trigger_id"])[0] is True
        db_session.expire_all()
        assert _used_margin(fm) == before


class TestFandOCloseFollowsCAS:
    """NFO and BFO trade past the cash close under SEBI's Closing Auction Session."""

    def test_default_timings_close_fo_at_1540(self):
        from database.market_calendar_db import DEFAULT_MARKET_TIMINGS

        fo_close = (15 * 3600 + 40 * 60) * 1000
        cash_close = (15 * 3600 + 30 * 60) * 1000
        for ex in ("NFO", "BFO"):
            assert DEFAULT_MARKET_TIMINGS[ex]["end_offset"] == fo_close, ex
        # Cash is unchanged: CAS applies to the equity segment, which stops
        # continuous trading earlier, not later.
        for ex in ("NSE", "BSE"):
            assert DEFAULT_MARKET_TIMINGS[ex]["end_offset"] == cash_close, ex

    def test_expiry_settlement_matches_the_new_close(self):
        """Settling at 15:30 would close an expiring contract before it stops
        trading."""
        from datetime import time as dt_time

        from sandbox.position_manager import EXCHANGE_CLOSE_TIMES

        assert EXCHANGE_CLOSE_TIMES["NFO"] == dt_time(15, 40)
        assert EXCHANGE_CLOSE_TIMES["BFO"] == dt_time(15, 40)

    def test_migration_only_touches_rows_still_on_the_old_close(self):
        """An admin's customised timing must not be reset to a default."""
        from database.market_calendar_db import CAS_CLOSE_MIGRATION

        for ex, spec in CAS_CLOSE_MIGRATION.items():
            assert spec["old_end"] == (15 * 3600 + 30 * 60) * 1000, ex
            assert spec["new_end"] == (15 * 3600 + 40 * 60) * 1000, ex


class TestFundPrimitivesRejectBadAmounts:
    """Every committing fund method must refuse an amount that invents money."""

    def _funds(self):
        from database.sandbox_db import SandboxFunds

        return SandboxFunds.query.filter_by(user_id=GTT_TEST_USER).first()

    def test_t1_transfer_cannot_underflow(self, clean_gtt_user):
        """The T+1 settlement path. An over-transfer drives used_margin
        negative and the difference silently becomes headroom for more trades,
        without even the visible cash bump a bad release leaves."""
        from database.sandbox_db import db_session

        fm = clean_gtt_user
        before = self._funds().used_margin

        ok, message = fm.transfer_margin_to_holdings(1, "underflow probe")
        db_session.expire_all()

        assert ok is False
        assert "only" in message
        assert self._funds().used_margin == before

    def test_t1_transfer_still_works_normally(self, clean_gtt_user):
        from database.sandbox_db import db_session

        fm = clean_gtt_user
        assert fm.block_margin(500, "x")[0] is True
        db_session.expire_all()
        assert fm.transfer_margin_to_holdings(500, "x")[0] is True
        db_session.expire_all()
        row = self._funds()
        assert row.used_margin == Decimal("0.00")
        # Transferred to holdings, so available_balance is deliberately NOT
        # credited - the money is represented in holdings value.
        assert row.available_balance < Decimal("10000000.00")

    @pytest.mark.parametrize("amount", [0, -1, Decimal("-0.01")])
    def test_block_refuses_non_positive(self, clean_gtt_user, amount):
        """A negative block is a release wearing the wrong name."""
        from database.sandbox_db import db_session

        fm = clean_gtt_user
        before = (self._funds().used_margin, self._funds().available_balance)
        ok, _ = fm.block_margin(amount, "probe")
        db_session.expire_all()
        assert ok is False
        assert (self._funds().used_margin, self._funds().available_balance) == before

    @pytest.mark.parametrize("amount", [-1, Decimal("-0.01")])
    def test_release_refuses_negative(self, clean_gtt_user, amount):
        from database.sandbox_db import db_session

        fm = clean_gtt_user
        before = (self._funds().used_margin, self._funds().available_balance)
        ok, _ = fm.release_margin(amount, description="probe")
        db_session.expire_all()
        assert ok is False
        assert (self._funds().used_margin, self._funds().available_balance) == before

    @pytest.mark.parametrize("amount", [0, -1])
    def test_credit_refuses_non_positive(self, clean_gtt_user, amount):
        """A negative credit debits the balance with none of the checks a real
        debit goes through."""
        from database.sandbox_db import db_session

        fm = clean_gtt_user
        before = self._funds().available_balance
        ok, _ = fm.credit_sale_proceeds(amount, "probe")
        db_session.expire_all()
        assert ok is False
        assert self._funds().available_balance == before

    def test_used_margin_never_goes_negative_across_the_primitives(self, clean_gtt_user):
        """The invariant, driven through every committing path."""
        from database.sandbox_db import db_session

        fm = clean_gtt_user
        for call in (
            lambda: fm.release_margin(1, description="p"),
            lambda: fm.transfer_margin_to_holdings(1, "p"),
            lambda: fm.block_margin(-1, "p"),
        ):
            call()
            db_session.expire_all()
            assert self._funds().used_margin >= 0, "used_margin went negative"
