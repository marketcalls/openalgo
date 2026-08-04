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

        from database.sandbox_db import SandboxFunds, SandboxPositions

        for gtt in SandboxGTT.query.filter_by(user_id=GTT_TEST_USER).all():
            SandboxGTTLeg.query.filter_by(gtt_id=gtt.gtt_id).delete()
            db_session.delete(gtt)
        SandboxPositions.query.filter_by(user_id=GTT_TEST_USER).delete()
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
