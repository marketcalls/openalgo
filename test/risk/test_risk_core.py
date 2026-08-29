"""Tests for the shared pure risk core, services/risk/.

Three layers:

  1. The golden vectors in vectors.json, run through both the dataclass API and
     the legacy dict adapter. That file is the contract the TypeScript copy in
     frontend/src/hooks/useTrailingSL.ts must also satisfy, so a rule change has
     to be made there before either implementation can move.
  2. Targeted unit tests for what a single tick cannot express: aggregate mark
     to market, lock profit over a sequence, trail to entry across a set, and
     the configuration validator.
  3. Property style checks that walk a price series and assert the ratchet
     invariants hold at every step, which is the part a fixed vector list can
     never cover.

Run: uv run pytest test/risk/ -v
"""

from __future__ import annotations

import dataclasses
import json
import math
import os
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from services.risk import (  # noqa: E402
    AggregateRisk,
    BreachReason,
    PositionPnL,
    PositionRisk,
    Side,
    TrailMode,
    aggregate_pnl,
    evaluate_aggregate,
    evaluate_position,
    evaluate_trail,
    position_pnl,
    side_from_quantity,
    stop_from_points,
    target_from_points,
    trail_stops_to_entry,
    validate_position,
)

VECTORS_PATH = Path(__file__).with_name("vectors.json")
VECTORS = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
CASES = VECTORS["cases"]
TOLERANCE = VECTORS["tolerance"]

# expected key -> PositionDecision attribute
DECISION_FIELDS = {
    "evaluated": "evaluated",
    "breached": "breached",
    "current_sl": "stop_price",
    "highest_price": "highest_price",
    "lowest_price": "lowest_price",
    "stop_moved": "stop_moved",
    "trail_armed": "trail_armed",
    "pnl": "pnl",
}


def _ids() -> list[str]:
    return [case["name"] for case in CASES]


def _close(actual, expected) -> bool:
    if expected is None or actual is None:
        return actual is expected or actual == expected
    return math.isclose(float(actual), float(expected), abs_tol=TOLERANCE)


# --------------------------------------------------------------------- vectors
class TestVectorFile:
    """The vector file is a shared contract, so its shape is itself under test."""

    def test_case_names_are_unique(self):
        names = [case["name"] for case in CASES]
        assert len(names) == len(set(names))

    def test_every_case_is_complete(self):
        for case in CASES:
            assert case["description"], case["name"]
            assert isinstance(case["state"], dict), case["name"]
            assert "ltp" in case, case["name"]
            assert isinstance(case["expected"], dict), case["name"]
            unknown = set(case["expected"]) - set(DECISION_FIELDS) - {"reason"}
            assert not unknown, f"{case['name']} expects unknown keys {unknown}"

    def test_reasons_are_wire_values(self):
        allowed = {None, BreachReason.STOP.value, BreachReason.TARGET.value}
        for case in CASES:
            assert case["expected"].get("reason") in allowed, case["name"]

    def test_both_sides_and_both_trail_modes_are_covered(self):
        sides = {str(case["state"].get("side", "BUY")).upper() for case in CASES}
        assert {"BUY", "SELL"} <= sides
        modes = {case["state"].get("trail_mode", "continuous") for case in CASES}
        assert {"continuous", "stepped"} <= modes

    def test_the_defect_cases_are_labelled(self):
        # A case that only the fixed core passes must say so, or a TypeScript
        # port will read a red test as its own bug rather than as work to do.
        labelled = [case["name"] for case in CASES if case.get("fixes")]
        assert len(labelled) >= 6


@pytest.mark.parametrize("case", CASES, ids=_ids())
def test_vector_against_the_dataclass_api(case):
    decision = evaluate_position(PositionRisk.from_state(case["state"]), case["ltp"])
    for key, expected in case["expected"].items():
        if key == "reason":
            actual = decision.reason.value if decision.reason is not None else None
            assert actual == expected, f"{case['name']}: reason"
            continue
        actual = getattr(decision, DECISION_FIELDS[key])
        if isinstance(expected, bool):
            assert actual is expected, f"{case['name']}: {key} was {actual}"
        else:
            assert _close(actual, expected), f"{case['name']}: {key} was {actual}"


@pytest.mark.parametrize("case", CASES, ids=_ids())
def test_vector_against_the_legacy_dict_adapter(case):
    """The adapter must produce the same answer in the shipped dict shape."""
    result = evaluate_trail(case["state"], case["ltp"])
    assert set(result) == {"highest_price", "lowest_price", "current_sl", "breached", "reason"}
    expected = case["expected"]
    assert result["breached"] is expected["breached"], case["name"]
    assert result["reason"] == expected["reason"], case["name"]
    for key in ("current_sl", "highest_price", "lowest_price"):
        if key in expected:
            assert _close(result[key], expected[key]), f"{case['name']}: {key}"


@pytest.mark.parametrize("case", CASES, ids=_ids())
def test_every_breach_explains_itself(case):
    """A breach with no detail is a breach a user cannot be told the reason for."""
    decision = evaluate_position(PositionRisk.from_state(case["state"]), case["ltp"])
    if decision.breached:
        assert decision.detail
        assert "sl" not in decision.detail.split()  # a sentence, not an enum value


# --------------------------------------------------------------------- purity
class TestPurity:
    def test_input_is_never_mutated(self):
        state = {
            "side": "BUY",
            "entry_price": 100.0,
            "quantity": 50,
            "current_sl": 90.0,
            "initial_sl": 90.0,
            "trailing_enabled": True,
            "trailing_step": 3.0,
            "highest_price": 100.0,
            "lowest_price": 100.0,
        }
        before = dict(state)
        evaluate_trail(state, 120.0)
        assert state == before

    def test_decisions_are_frozen(self):
        decision = evaluate_position(PositionRisk(entry_price=100.0, stop_price=90.0), 95.0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            decision.stop_price = 1.0  # type: ignore[misc]

    def test_the_package_imports_nothing_that_does_io(self):
        # The whole point of the core is that it can be imported into a green
        # thread, a real thread, a REST handler or a test with no platform
        # running. Any database, broker, feed or logging import would break
        # that, so assert on the import graph rather than trusting review.
        import services.risk as risk_pkg

        root = Path(risk_pkg.__file__).parent
        forbidden = (
            "import database",
            "from database",
            "import broker",
            "from broker",
            "import sqlalchemy",
            "from sqlalchemy",
            "utils.logging",
            "httpx",
            "socketio",
            "import requests",
            "websocket",
        )
        for path in sorted(root.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            # Skip the prose: only the code lines are the import graph.
            code = "\n".join(
                line for line in source.splitlines() if line.startswith(("import ", "from "))
            )
            for token in forbidden:
                assert token not in code, f"{path.name} imports {token}"


# --------------------------------------------------------------------- helpers
class TestConversions:
    def test_points_convert_to_prices_on_the_right_side(self):
        assert stop_from_points("BUY", 100.0, 10.0) == 90.0
        assert stop_from_points("SELL", 100.0, 10.0) == 110.0
        assert target_from_points("BUY", 100.0, 20.0) == 120.0
        assert target_from_points("SELL", 100.0, 20.0) == 80.0

    def test_a_stop_that_would_land_at_or_below_zero_is_no_stop(self):
        # A 120 point stop on a 100 rupee option is not a stop at minus 20.
        assert stop_from_points("BUY", 100.0, 120.0) is None
        assert target_from_points("SELL", 100.0, 100.0) is None

    def test_side_comes_from_the_sign_of_a_net_quantity(self):
        assert side_from_quantity(-75) is Side.SELL
        assert side_from_quantity(75) is Side.BUY
        assert side_from_quantity(0) is Side.BUY

    def test_points_configuration_loads_through_from_state(self):
        risk = PositionRisk.from_state(
            {"side": "SELL", "entry_price": 100.0, "sl_points": 10.0, "target_points": 20.0}
        )
        assert risk.effective_stop == 110.0
        assert risk.target_price == 80.0


# --------------------------------------------------------------------- validate
class TestValidation:
    def test_a_stop_on_the_wrong_side_is_refused(self):
        problems = validate_position(
            PositionRisk(side=Side.BUY, entry_price=100.0, stop_price=105.0), 100.0
        )
        assert any("exits immediately" in text for text in problems)

    def test_a_short_target_above_the_market_is_refused(self):
        problems = validate_position(
            PositionRisk(side=Side.SELL, entry_price=100.0, target_price=110.0), 100.0
        )
        assert any("target" in text for text in problems)

    def test_trailing_without_a_step_is_refused(self):
        problems = validate_position(
            PositionRisk(entry_price=100.0, stop_price=90.0, trailing_enabled=True), 100.0
        )
        assert any("trail step" in text for text in problems)

    def test_a_stepped_trail_that_overruns_its_trigger_is_refused(self):
        problems = validate_position(
            PositionRisk(
                entry_price=100.0,
                stop_price=90.0,
                trailing_enabled=True,
                trail_mode=TrailMode.STEPPED,
                trail_step=10.0,
                trail_trigger=1.0,
            ),
            100.0,
        )
        assert any("larger than its trigger" in text for text in problems)

    def test_a_sane_configuration_has_no_problems(self):
        assert (
            validate_position(
                PositionRisk(
                    entry_price=100.0,
                    stop_price=90.0,
                    target_price=120.0,
                    trailing_enabled=True,
                    trail_step=3.0,
                ),
                100.0,
            )
            == ()
        )


# --------------------------------------------------------------------- aggregate
def _open(identifier, side, entry, qty, ltp):
    return PositionPnL(
        identifier=identifier, side=side, entry_price=entry, quantity=qty, last_price=ltp
    )


class TestAggregatePnL:
    def test_open_and_closed_positions_are_summed_separately(self):
        summary = aggregate_pnl(
            [
                _open("a", Side.BUY, 100.0, 50, 110.0),  # +500
                _open("b", Side.SELL, 200.0, 25, 190.0),  # +250
                PositionPnL(identifier="c", closed=True, realized_pnl=-125.0),
            ]
        )
        assert summary.unrealized == pytest.approx(750.0)
        assert summary.realized == pytest.approx(-125.0)
        assert summary.total == pytest.approx(625.0)
        assert summary.priced == 2

    def test_an_unpriced_open_position_is_counted_not_guessed(self):
        summary = aggregate_pnl(
            [
                _open("a", Side.BUY, 100.0, 50, 110.0),
                PositionPnL(identifier="b", side=Side.BUY, entry_price=100.0, quantity=50),
            ]
        )
        assert summary.unpriced == 1
        assert summary.total == pytest.approx(500.0)

    def test_a_position_book_row_infers_its_side_from_a_signed_quantity(self):
        summary = aggregate_pnl(
            [
                {"symbol": "X", "quantity": -75, "average_price": 100.0, "ltp": 90.0},
            ]
        )
        assert summary.total == pytest.approx(750.0)

    def test_the_aggregate_is_derived_not_read_back(self):
        # openbull sums a `mtm` field the caller wrote on a previous pass, so a
        # stale write silently poisons the aggregate. Here a bogus mtm is ignored.
        summary = aggregate_pnl(
            [
                {
                    "symbol": "X",
                    "side": "BUY",
                    "quantity": 50,
                    "entry_price": 100.0,
                    "ltp": 110.0,
                    "mtm": 999999.0,
                },
            ]
        )
        assert summary.total == pytest.approx(500.0)

    def test_position_pnl_matches_the_per_position_decision(self):
        risk = PositionRisk(side=Side.SELL, entry_price=100.0, quantity=75, stop_price=110.0)
        decision = evaluate_position(risk, 90.0)
        assert decision.pnl == pytest.approx(position_pnl(Side.SELL, 100.0, 75, 90.0))


class TestCombinedLimits:
    def test_combined_stop_fires_at_the_limit(self):
        risk = AggregateRisk(combined_stoploss=5000.0)
        assert not evaluate_aggregate(risk, 0.0, -4999.0).breached
        decision = evaluate_aggregate(risk, 0.0, -5000.0)
        assert decision.breached and decision.reason is BreachReason.COMBINED_STOP
        assert decision.detail

    def test_combined_stop_is_read_as_a_magnitude(self):
        # A user may enter the limit as 5000 or as -5000 and mean the same loss.
        positive = evaluate_aggregate(AggregateRisk(combined_stoploss=5000.0), 0.0, -6000.0)
        negative = evaluate_aggregate(AggregateRisk(combined_stoploss=-5000.0), 0.0, -6000.0)
        assert positive.reason is negative.reason is BreachReason.COMBINED_STOP

    def test_combined_target_fires_at_the_limit(self):
        risk = AggregateRisk(combined_target=10000.0)
        assert not evaluate_aggregate(risk, 0.0, 9999.0).breached
        assert evaluate_aggregate(risk, 4000.0, 6000.0).reason is BreachReason.COMBINED_TARGET

    def test_peak_and_trough_ratchet_in_both_directions(self):
        decision = evaluate_aggregate(AggregateRisk(peak_pnl=8000.0, trough_pnl=-200.0), 0.0, 500.0)
        assert decision.peak_pnl == pytest.approx(8000.0)
        assert decision.trough_pnl == pytest.approx(-200.0)

    def test_trail_to_entry_bypasses_the_stop_but_not_the_target(self):
        # openbull's code bypasses both; its own spec bypasses only the stop.
        # Following the spec: every remaining position is at worst flat, so the
        # stop is redundant, but a set that reaches its target must still close.
        risk = AggregateRisk(combined_stoploss=5000.0, combined_target=10000.0, stop_bypassed=True)
        assert not evaluate_aggregate(risk, 0.0, -9000.0).breached
        assert evaluate_aggregate(risk, 0.0, 10000.0).reason is BreachReason.COMBINED_TARGET


class TestLockProfit:
    def test_it_does_not_arm_below_the_threshold(self):
        risk = AggregateRisk(lock_profit_at=5000.0, lock_profit_floor=3000.0)
        decision = evaluate_aggregate(risk, 0.0, 4999.0)
        assert not decision.lock_armed and not decision.breached

    def test_it_arms_at_the_threshold_and_sets_the_floor(self):
        risk = AggregateRisk(lock_profit_at=5000.0, lock_profit_floor=3000.0)
        decision = evaluate_aggregate(risk, 0.0, 5000.0)
        assert decision.lock_armed and decision.lock_armed_now
        assert decision.lock_floor == pytest.approx(3000.0)
        assert not decision.breached

    def test_it_fires_when_profit_falls_back_to_the_floor(self):
        risk = AggregateRisk(
            lock_profit_at=5000.0, lock_profit_floor=3000.0, lock_armed=True, lock_floor=3000.0
        )
        assert not evaluate_aggregate(risk, 0.0, 3001.0).breached
        assert evaluate_aggregate(risk, 0.0, 3000.0).reason is BreachReason.LOCK_PROFIT

    def test_the_trailing_floor_rises_with_the_peak(self):
        risk = AggregateRisk(
            lock_profit_at=5000.0,
            lock_profit_floor=3000.0,
            lock_trail_step=1000.0,
            lock_armed=True,
            lock_floor=3000.0,
            peak_pnl=5000.0,
        )
        decision = evaluate_aggregate(risk, 0.0, 8000.0)
        assert decision.lock_floor == pytest.approx(7000.0)
        assert decision.lock_floor_raised

    def test_the_floor_never_falls_back(self):
        risk = AggregateRisk(
            lock_profit_at=5000.0,
            lock_profit_floor=3000.0,
            lock_trail_step=1000.0,
            lock_armed=True,
            lock_floor=7000.0,
            peak_pnl=8000.0,
        )
        decision = evaluate_aggregate(risk, 0.0, 7100.0)
        assert decision.lock_floor == pytest.approx(7000.0)
        assert not decision.lock_floor_raised
        assert not decision.breached

    def test_a_floor_above_its_arming_threshold_says_so(self):
        # Self triggering on the arming tick is a configuration error, not a
        # market event, and the caller has to be able to tell the user which.
        risk = AggregateRisk(lock_profit_at=5000.0, lock_profit_floor=6000.0)
        decision = evaluate_aggregate(risk, 0.0, 5000.0)
        assert decision.reason is BreachReason.LOCK_PROFIT
        assert "above its arming threshold" in decision.detail

    def test_a_removed_configuration_does_not_keep_firing(self):
        # lock_armed persisted from a configuration the user has since deleted.
        risk = AggregateRisk(lock_armed=True, lock_floor=3000.0)
        assert not evaluate_aggregate(risk, 0.0, 100.0).breached

    def test_lock_profit_outranks_the_combined_stop(self):
        risk = AggregateRisk(
            combined_stoploss=5000.0,
            lock_profit_at=5000.0,
            lock_profit_floor=3000.0,
            lock_armed=True,
            lock_floor=3000.0,
        )
        assert evaluate_aggregate(risk, 0.0, 2000.0).reason is BreachReason.LOCK_PROFIT


class TestTrailToEntry:
    def _set(self):
        return [
            PositionRisk(identifier="win", side=Side.BUY, entry_price=100.0, stop_price=90.0),
            PositionRisk(identifier="short", side=Side.SELL, entry_price=200.0, stop_price=210.0),
            PositionRisk(identifier="already", side=Side.BUY, entry_price=50.0, stop_price=55.0),
            PositionRisk(identifier="trigger", side=Side.BUY, entry_price=10.0, stop_price=9.0),
        ]

    def test_it_moves_the_others_to_their_own_entry(self):
        decision = trail_stops_to_entry(self._set(), exclude=["trigger"])
        moved = {move.identifier: move.new_stop for move in decision.moves}
        assert moved == {"win": 100.0, "short": 200.0}
        assert decision.skipped_not_improving == ("already",)

    def test_it_never_loosens_a_stop_already_past_entry(self):
        decision = trail_stops_to_entry(
            [PositionRisk(identifier="a", side=Side.BUY, entry_price=100.0, stop_price=107.0)]
        )
        assert decision.moved == 0
        assert decision.skipped_not_improving == ("a",)

    def test_it_refuses_to_turn_a_loser_into_an_immediate_market_exit(self):
        # openbull moves this stop to 100 with the market at 95, which is not
        # "make the winners risk free", it is "sell the loser at market now".
        decision = trail_stops_to_entry(
            [PositionRisk(identifier="a", side=Side.BUY, entry_price=100.0, stop_price=90.0)],
            last_prices={"a": 95.0},
        )
        assert decision.moved == 0
        assert decision.skipped_through_price == ("a",)

    def test_it_moves_a_winner_when_a_price_is_supplied(self):
        decision = trail_stops_to_entry(
            [PositionRisk(identifier="a", side=Side.BUY, entry_price=100.0, stop_price=90.0)],
            last_prices={"a": 108.0},
        )
        assert decision.moved == 1

    def test_a_position_with_no_entry_is_reported_not_skipped_silently(self):
        decision = trail_stops_to_entry([PositionRisk(identifier="a", entry_price=0.0)])
        assert decision.skipped_no_entry == ("a",)

    def test_nothing_is_mutated(self):
        positions = [{"identifier": "a", "side": "BUY", "entry_price": 100.0, "current_sl": 90.0}]
        before = [dict(p) for p in positions]
        trail_stops_to_entry(positions)
        assert positions == before

    def test_the_moved_stops_hold_on_the_next_tick(self):
        # The whole point: after the move, price back at entry breaches, and a
        # tick above it does not.
        risk = PositionRisk(identifier="a", side=Side.BUY, entry_price=100.0, stop_price=90.0)
        move = trail_stops_to_entry([risk]).moves[0]
        moved = PositionRisk(
            identifier="a", side=Side.BUY, entry_price=100.0, stop_price=move.new_stop
        )
        assert evaluate_position(moved, 100.0).reason is BreachReason.STOP
        assert not evaluate_position(moved, 100.5).breached


# --------------------------------------------------------------------- properties
def _walk(seed: int, start: float, steps: int) -> list[float]:
    rng = random.Random(seed)
    price = start
    series = []
    for _ in range(steps):
        price = max(0.05, round(price * (1.0 + rng.uniform(-0.04, 0.045)), 2))
        series.append(price)
    return series


@pytest.mark.parametrize("seed", [1, 7, 42, 99, 2024])
@pytest.mark.parametrize("mode", [TrailMode.CONTINUOUS, TrailMode.STEPPED])
def test_a_long_stop_never_decreases(seed, mode):
    """The ratchet invariant, over a whole price series rather than one tick."""
    stop, highest = 90.0, 100.0
    for ltp in _walk(seed, 100.0, 200):
        risk = PositionRisk(
            side=Side.BUY,
            entry_price=100.0,
            quantity=50,
            stop_price=stop,
            initial_stop_price=90.0,
            highest_price=highest,
            trailing_enabled=True,
            trail_step=3.0,
            trail_trigger=5.0,
            trail_mode=mode,
        )
        decision = evaluate_position(risk, ltp)
        assert decision.stop_price >= stop - 1e-9, f"stop fell from {stop} to {decision.stop_price}"
        assert decision.highest_price >= highest - 1e-9
        # A trail may never place the stop beyond the best price actually seen.
        assert decision.stop_price <= decision.highest_price + 1e-9
        stop, highest = decision.stop_price, decision.highest_price
        if decision.breached:
            break


@pytest.mark.parametrize("seed", [1, 7, 42, 99, 2024])
@pytest.mark.parametrize("mode", [TrailMode.CONTINUOUS, TrailMode.STEPPED])
def test_a_short_stop_never_increases(seed, mode):
    stop, lowest = 110.0, 100.0
    for ltp in _walk(seed, 100.0, 200):
        risk = PositionRisk(
            side=Side.SELL,
            entry_price=100.0,
            quantity=75,
            stop_price=stop,
            initial_stop_price=110.0,
            lowest_price=lowest,
            trailing_enabled=True,
            trail_step=3.0,
            trail_trigger=5.0,
            trail_mode=mode,
        )
        decision = evaluate_position(risk, ltp)
        assert decision.stop_price <= stop + 1e-9, f"stop rose from {stop} to {decision.stop_price}"
        assert decision.lowest_price <= lowest + 1e-9
        assert decision.stop_price >= decision.lowest_price - 1e-9
        stop, lowest = decision.stop_price, decision.lowest_price
        if decision.breached:
            break


@pytest.mark.parametrize("seed", [3, 11, 77])
def test_the_lock_profit_floor_never_falls_back(seed):
    risk = AggregateRisk(lock_profit_at=5000.0, lock_profit_floor=3000.0, lock_trail_step=1500.0)
    rng = random.Random(seed)
    total = 0.0
    floor = None
    for _ in range(300):
        total += rng.uniform(-900.0, 1000.0)
        decision = evaluate_aggregate(risk, 0.0, total)
        if decision.lock_floor is not None and floor is not None:
            assert decision.lock_floor >= floor - 1e-9
        risk = AggregateRisk(
            lock_profit_at=5000.0,
            lock_profit_floor=3000.0,
            lock_trail_step=1500.0,
            lock_armed=decision.lock_armed,
            lock_floor=decision.lock_floor,
            peak_pnl=decision.peak_pnl,
            trough_pnl=decision.trough_pnl,
        )
        floor = decision.lock_floor
        if decision.breached:
            break


@pytest.mark.parametrize("seed", [5, 13, 21])
def test_an_unusable_tick_never_changes_anything(seed):
    """A dead tick in the middle of a series must be a no op, not a reset."""
    rng = random.Random(seed)
    state = {
        "side": "BUY",
        "entry_price": 100.0,
        "quantity": 50,
        "initial_sl": 90.0,
        "current_sl": 90.0,
        "trailing_enabled": True,
        "trailing_step": 3.0,
        "highest_price": 100.0,
        "lowest_price": 100.0,
    }
    for _ in range(50):
        good = evaluate_trail(state, round(rng.uniform(95.0, 130.0), 2))
        state.update({k: good[k] for k in ("highest_price", "lowest_price")})
        state["current_sl"] = good["current_sl"]
        snapshot = dict(state)
        for dead in (0.0, -1.0, None, float("nan"), float("inf")):
            result = evaluate_trail(state, dead)
            assert result["breached"] is False
            assert result["current_sl"] == snapshot["current_sl"]
            assert result["highest_price"] == snapshot["highest_price"]
        if good["breached"]:
            break


# --------------------------------------------------------- scalping parity
class TestScalpingParity:
    """The expectations test/test_scalping_risk_monitor.py already asserts.

    Duplicated here deliberately: they are the evidence that the scalping
    monitor can be pointed at the shared core without its own suite changing.
    """

    def _long(self, **over):
        state = {
            "symbol": "NIFTY25JUN2623600CE",
            "exchange": "NFO",
            "product": "NRML",
            "side": "BUY",
            "entry_price": 100.0,
            "current_sl": 90.0,
            "initial_sl": 90.0,
            "target": 0.0,
            "trailing_enabled": False,
            "trailing_step": 0.0,
            "highest_price": 100.0,
            "lowest_price": 100.0,
        }
        state.update(over)
        return state

    def _short(self, **over):
        return self._long(**{"side": "SELL", "current_sl": 110.0, "initial_sl": 110.0, **over})

    def test_long_stop_boundary(self):
        assert evaluate_trail(self._long(current_sl=95.0), 95.0)["reason"] == "sl"
        assert evaluate_trail(self._long(current_sl=95.0), 94.9)["breached"]
        assert not evaluate_trail(self._long(current_sl=95.0), 95.1)["breached"]

    def test_short_stop_boundary(self):
        assert evaluate_trail(self._short(current_sl=105.0), 105.0)["reason"] == "sl"
        assert evaluate_trail(self._short(current_sl=105.0), 105.1)["breached"]
        assert not evaluate_trail(self._short(current_sl=105.0), 104.9)["breached"]

    def test_target_boundaries(self):
        assert evaluate_trail(self._long(target=120.0), 120.0)["reason"] == "target"
        assert not evaluate_trail(self._long(target=120.0), 119.9)["breached"]
        assert evaluate_trail(self._short(target=80.0), 80.0)["reason"] == "target"
        assert not evaluate_trail(self._short(target=80.0), 80.1)["breached"]

    def test_stop_takes_priority(self):
        assert evaluate_trail(self._long(current_sl=95.0, target=120.0), 90.0)["reason"] == "sl"

    def test_long_trail_raises_the_stop(self):
        result = evaluate_trail(
            self._long(trailing_enabled=True, trailing_step=3.0, current_sl=90.0), 110.0
        )
        assert not result["breached"]
        assert result["current_sl"] == pytest.approx(107.0)
        assert result["highest_price"] == pytest.approx(110.0)

    def test_long_trail_only_moves_up(self):
        result = evaluate_trail(
            self._long(
                trailing_enabled=True, trailing_step=3.0, current_sl=107.0, highest_price=110.0
            ),
            108.0,
        )
        assert not result["breached"]
        assert result["current_sl"] == pytest.approx(107.0)

    def test_long_trail_waits_for_the_minimum_profit(self):
        result = evaluate_trail(
            self._long(trailing_enabled=True, trailing_step=3.0, current_sl=90.0), 100.5
        )
        assert result["current_sl"] == pytest.approx(90.0)

    def test_long_trailed_stop_then_breaches(self):
        state = self._long(trailing_enabled=True, trailing_step=3.0, current_sl=90.0)
        first = evaluate_trail(state, 110.0)
        second = evaluate_trail({**state, **first}, 106.9)
        assert second["breached"] and second["reason"] == "sl"

    def test_short_trail_lowers_the_stop(self):
        result = evaluate_trail(
            self._short(trailing_enabled=True, trailing_step=3.0, current_sl=110.0), 90.0
        )
        assert not result["breached"]
        assert result["current_sl"] == pytest.approx(93.0)
        assert result["lowest_price"] == pytest.approx(90.0)

    def test_short_trailed_stop_then_breaches(self):
        state = self._short(trailing_enabled=True, trailing_step=3.0, current_sl=110.0)
        first = evaluate_trail(state, 90.0)
        second = evaluate_trail({**state, **first}, 93.1)
        assert second["breached"] and second["reason"] == "sl"
