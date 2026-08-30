"""Signal-mode strategies.

One TradingView alert moves one leg. What is tested here is which signals are
accepted, which are quietly ignored, which are refused, and above all that a
leg is held and exited on the side the signal actually opened it - not the side
its configuration mentions.

The distinction between a no-op and a refusal carries weight. An alert engine
repeats itself; answering a repeat as a failure invites a retry, and a retry on
an order path is how one alert becomes two positions.
"""

from datetime import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

# restx_api first: see the note in test_strategy_module_order_dispatch.py.
import restx_api  # noqa: F401
from database import strategy_module_db as store
from services.strategy_module import engine, signals, state
from services.strategy_module.order_dispatch import DispatchResult

USER = "signal_test_user"


def _legs():
    return [
        {
            "id": 1,
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "side": "both",
            "qty": 100,
            "segment": "cash",
            "sl_pts": 20,
            "trail": {"x": 0, "y": 0},
        },
        {
            "id": 2,
            "symbol": "SBIN",
            "exchange": "NSE",
            "side": "long",
            "qty": 50,
            "segment": "cash",
            "trail": {"x": 0, "y": 0},
        },
    ]


@pytest.fixture(autouse=True)
def clean_slate():
    store.db_session.remove()
    store.init_db()

    def purge():
        for row in store.list_strategies(USER):
            if row["current_run_id"]:
                state.clear_run_state(row["current_run_id"])
            store.set_strategy_status(row["id"], "stopped", None)
            store.delete_strategy(row["id"], USER)
        store.clear_strategy_module_cache()

    purge()
    yield
    purge()


@pytest.fixture
def placed():
    """Records every order dispatched, and accepts them all."""
    seen = []

    def record(**kwargs):
        seen.append(kwargs["order"])
        return DispatchResult(ok=True, broker_order_id=f"SB-{len(seen)}", response={})

    with (
        # Both modules hold their own reference to the dispatcher and their own
        # _api_key_for, and a signal strategy is squared off through the
        # engine, so patching only the signal side records the entries and
        # silently misses every exit.
        patch.object(signals.order_dispatch, "dispatch_order", side_effect=record),
        patch.object(signals, "_api_key_for", return_value="test-key"),
        patch.object(engine.order_dispatch, "dispatch_order", side_effect=record),
        patch.object(engine, "_api_key_for", return_value="test-key"),
        patch.object(engine, "_subscribe_run"),
        patch.object(engine, "_unsubscribe_run"),
    ):
        yield seen


def _fill(strategy, *leg_ids, price=100.0):
    """Confirm the entry fills for these legs.

    An exit closes a confirmed quantity. A leg whose entry the broker accepted
    but has not filled has nothing to close, and sending the configured size
    the other way would be a naked position if that entry later cancels, so the
    module refuses. Every test that goes on to exit something has to say the
    entry filled, which is what happens in life.
    """
    run_id = store.get_strategy(strategy.id, USER).current_run_id
    for leg_id in leg_ids:
        engine.apply_fill(run_id, leg_id, price, is_entry=True)
    return run_id


def _make(**overrides):
    config = {
        "name": "Signal test",
        "underlying": "MULTI",
        "underlying_exchange": "NSE",
        "universe_tab": "stocks_fno",
        "strategy_kind": "signal",
        "direction": "both",
        "strategy_type": "positional",
        "product": "MIS",
        "legs": _legs(),
    }
    config.update(overrides)
    created, error = store.create_strategy(USER, config)
    assert error is None, error
    return store.get_strategy(created["id"], USER)


# ---------------------------------------------------------------------------
# Which actions belong to which kind
# ---------------------------------------------------------------------------


def test_each_kind_accepts_only_its_own_actions():
    # The router is shared, so a start against a signal strategy and a
    # long_entry against a batch one must both be refused rather than
    # half-handled.
    assert signals.actions_for("batch") == ("start", "stop")
    assert set(signals.actions_for("signal")) == set(signals.SIGNAL_ACTIONS)


def test_an_unknown_action_is_refused(placed):
    strategy = _make()

    result = signals.handle_signal(strategy, "buy", leg_id=1)

    assert result.ok is False
    assert not placed


# ---------------------------------------------------------------------------
# Gates: refusals, not no-ops
# ---------------------------------------------------------------------------


def test_the_strategy_direction_blocks_the_wrong_side(placed):
    strategy = _make(direction="long_only")

    result = signals.handle_signal(strategy, "short_entry", leg_id=1)

    assert result.ok is False
    assert "long_only" in result.error
    assert not placed


def test_a_leg_refuses_a_side_it_does_not_accept(placed):
    # Leg 2 is configured long-only.
    strategy = _make()

    result = signals.handle_signal(strategy, "short_entry", leg_id=2)

    assert result.ok is False
    assert "long" in result.error
    assert not placed


def test_a_signal_matching_no_leg_is_refused(placed):
    strategy = _make()

    assert signals.handle_signal(strategy, "long_entry", leg_id=99).ok is False
    assert signals.handle_signal(strategy, "long_entry", symbol="TCS", exchange="NSE").ok is False
    assert not placed


# ---------------------------------------------------------------------------
# Targeting
# ---------------------------------------------------------------------------


def test_a_leg_can_be_named_by_symbol_when_no_id_is_given(placed):
    strategy = _make()

    result = signals.handle_signal(strategy, "long_entry", symbol="reliance", exchange="nse")

    assert result.ok is True
    assert result.leg_id == 1
    assert placed[0]["symbol"] == "RELIANCE"


def test_leg_id_wins_over_symbol_when_both_are_sent(placed):
    strategy = _make()

    result = signals.handle_signal(
        strategy, "long_entry", leg_id=2, symbol="RELIANCE", exchange="NSE"
    )

    assert result.leg_id == 2
    assert placed[0]["symbol"] == "SBIN"


# ---------------------------------------------------------------------------
# The side a leg is actually held
# ---------------------------------------------------------------------------


def test_a_leg_is_held_on_the_side_the_signal_opened_not_the_one_configured(placed):
    # PORTED DEFECT. A signal leg's configuration says which signals it
    # ACCEPTS, which is not which way it is currently held. The original
    # conflates them and never records a side at all, so the risk core
    # evaluated every signal leg as a short: its stop fired on a favourable
    # move.
    strategy = _make()

    signals.handle_signal(strategy, "short_entry", leg_id=1)

    run_id = store.get_strategy(strategy.id, USER).current_run_id
    leg = state.get_run_state(run_id)["legs"]["1"]
    assert leg["position"] == "S"
    assert placed[0]["action"] == "SELL"


def test_a_long_signal_opens_a_long(placed):
    strategy = _make()

    signals.handle_signal(strategy, "long_entry", leg_id=1)

    run_id = store.get_strategy(strategy.id, USER).current_run_id
    assert state.get_run_state(run_id)["legs"]["1"]["position"] == "B"
    assert placed[0]["action"] == "BUY"


def test_an_exit_covers_the_side_actually_held(placed):
    strategy = _make()
    signals.handle_signal(strategy, "short_entry", leg_id=1)
    # Filled, because an exit closes a confirmed quantity. A leg whose entry
    # the broker has accepted but not filled has nothing to close, and sending
    # the configured size the other way would be a naked position.
    _fill(strategy, 1)

    result = signals.handle_signal(strategy, "short_exit", leg_id=1)

    assert result.ok is True
    # Covering a short is a BUY. Deriving this from configuration rather than
    # from the held side is what doubled the position in the original.
    assert placed[-1]["action"] == "BUY"


# ---------------------------------------------------------------------------
# No-ops: answered 200, because a retry would place a second order
# ---------------------------------------------------------------------------


def test_an_exit_for_a_position_that_is_not_held_does_nothing(placed):
    strategy = _make()

    result = signals.handle_signal(strategy, "long_exit", leg_id=1)

    assert result.ok is True
    assert result.note == "no_matching_position"
    assert not placed


def test_an_exit_for_the_other_side_does_nothing(placed):
    strategy = _make()
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    placed.clear()

    result = signals.handle_signal(strategy, "short_exit", leg_id=1)

    assert result.ok is True
    assert result.note == "no_matching_position"
    assert not placed


def test_entering_a_side_already_held_does_not_add_to_it(placed):
    # The repeat alert. Adding here would double a position on a signal the
    # sender believes it has already delivered.
    strategy = _make()
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    placed.clear()

    result = signals.handle_signal(strategy, "long_entry", leg_id=1)

    assert result.ok is True
    assert result.note == "already_long"
    assert not placed


def test_an_opposite_entry_squares_first_then_opens(placed):
    # Reversing without closing would leave both positions on the book.
    strategy = _make()
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    _fill(strategy, 1)
    placed.clear()

    result = signals.handle_signal(strategy, "short_entry", leg_id=1)

    assert result.ok is True
    assert result.flipped is True
    assert [o["action"] for o in placed] == ["SELL", "SELL"]  # close the long, open the short

    run_id = store.get_strategy(strategy.id, USER).current_run_id
    assert state.get_run_state(run_id)["legs"]["1"]["position"] == "S"


# ---------------------------------------------------------------------------
# Trading window
# ---------------------------------------------------------------------------


def test_an_entry_before_the_entry_time_is_ignored(placed):
    strategy = _make(strategy_type="intraday", entry_time=time(9, 20), exit_time=time(15, 10))

    with patch.object(signals, "_now_ist", return_value=SimpleNamespace(time=lambda: time(9, 0))):
        result = signals.handle_signal(strategy, "long_entry", leg_id=1)

    assert result.ok is True
    assert result.note == "outside_entry_window"
    assert not placed


def test_an_exit_before_the_entry_time_is_allowed(placed):
    # A position carried in from a previous session must always be closable.
    strategy = _make(strategy_type="intraday", entry_time=time(9, 20), exit_time=time(15, 10))

    with patch.object(signals, "_now_ist", return_value=SimpleNamespace(time=lambda: time(9, 0))):
        result = signals.handle_signal(strategy, "long_exit", leg_id=1)

    # No position, so it is a no-op rather than a window rejection.
    assert result.note == "no_matching_position"


def test_everything_stops_after_the_exit_time(placed):
    strategy = _make(strategy_type="intraday", entry_time=time(9, 20), exit_time=time(15, 10))

    with patch.object(signals, "_now_ist", return_value=SimpleNamespace(time=lambda: time(15, 30))):
        entry = signals.handle_signal(strategy, "long_entry", leg_id=1)
        exit_signal = signals.handle_signal(strategy, "long_exit", leg_id=1)

    assert entry.note == "outside_trading_window"
    assert exit_signal.note == "outside_trading_window"
    assert not placed


def test_a_positional_strategy_has_no_window(placed):
    strategy = _make(strategy_type="positional")

    with patch.object(signals, "_now_ist", return_value=SimpleNamespace(time=lambda: time(3, 0))):
        result = signals.handle_signal(strategy, "long_entry", leg_id=1)

    assert result.ok is True
    assert result.note is None
    assert placed


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


def test_the_first_signal_of_the_day_opens_the_run(placed):
    strategy = _make()
    assert strategy.current_run_id is None

    signals.handle_signal(strategy, "long_entry", leg_id=1)

    refreshed = store.get_strategy(strategy.id, USER)
    assert refreshed.current_run_id is not None
    assert refreshed.status == "running"
    assert len(store.list_runs(strategy.id)) == 1


def test_later_signals_reuse_the_same_run(placed):
    strategy = _make()
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    first = store.get_strategy(strategy.id, USER).current_run_id

    signals.handle_signal(strategy, "long_entry", leg_id=2)

    assert store.get_strategy(strategy.id, USER).current_run_id == first
    assert len(store.list_runs(strategy.id)) == 1


def test_a_run_is_sandbox_unless_the_strategy_opted_into_live(placed):
    strategy = _make()

    signals.handle_signal(strategy, "long_entry", leg_id=1)

    run_id = store.get_strategy(strategy.id, USER).current_run_id
    assert store.get_run(run_id).mode == "sandbox"


def test_squaring_off_closes_every_open_leg_on_the_side_it_is_held(placed):
    """Through engine.stop_run, which is the path every square-off takes.

    The scheduler, the kill switch and the operator's Close All all reach it,
    and it handles both strategy kinds. signals used to carry its own
    close_all_signal_legs for this, with no caller anywhere: a second way to
    send exits, reachable only by somebody wiring it up later.
    """
    strategy = _make()
    signals.handle_signal(strategy, "short_entry", leg_id=1)
    signals.handle_signal(strategy, "long_entry", leg_id=2)
    _fill(strategy, 1, 2)
    placed.clear()

    run_id = store.get_strategy(strategy.id, USER).current_run_id
    engine.stop_run(run_id, USER, reason="scheduler")

    actions = sorted(o["action"] for o in placed)
    assert actions == ["BUY", "SELL"]  # cover the short, sell the long


def test_five_lots_of_nifty_is_sent_as_the_lot_size_times_five(placed):
    # The whole point of lots mode. The user configures 5 lots; the broker is
    # sent 325, because NIFTY's lot size is 65.
    strategy = _make(
        legs=[
            {
                "id": 1,
                "symbol": "NIFTY",
                "exchange": "NFO",
                "side": "both",
                "qty": 5,
                "qty_mode": "lots",
                "segment": "futures",
                "trail": {"x": 0, "y": 0},
            }
        ]
    )

    with patch("services.strategy_module.symbol_resolver.lot_size_for", return_value=65):
        result = signals.handle_signal(strategy, "long_entry", leg_id=1)

    assert result.ok is True
    assert placed[0]["quantity"] == "325"

    run_id = store.get_strategy(strategy.id, USER).current_run_id
    leg = state.get_run_state(run_id)["legs"]["1"]
    assert leg["qty"] == 325
    # The configured lot count is kept alongside, so the audit trail and the UI
    # can show what was asked for rather than only what was sent.
    assert leg["lots"] == 5


def test_lots_mode_refuses_rather_than_guessing_an_unknown_lot_size(placed):
    # Fabricating the size of a real order is the one thing this must not do.
    strategy = _make(
        legs=[
            {
                "id": 1,
                "symbol": "WHATEVER",
                "exchange": "NFO",
                "side": "both",
                "qty": 5,
                "qty_mode": "lots",
                "segment": "futures",
                "trail": {"x": 0, "y": 0},
            }
        ]
    )

    with patch("services.strategy_module.symbol_resolver.lot_size_for", return_value=None):
        result = signals.handle_signal(strategy, "long_entry", leg_id=1)

    assert result.ok is False
    assert "lot size" in result.error
    assert not placed


def test_units_mode_still_has_to_land_on_a_lot_boundary(placed):
    # A strategy saved before the master contract was downloaded, or edited
    # directly, arrives here unchecked. The broker would refuse it rather than
    # round it.
    strategy = _make(
        legs=[
            {
                "id": 1,
                "symbol": "NIFTY",
                "exchange": "NFO",
                "side": "both",
                "qty": 7,
                "qty_mode": "units",
                "segment": "futures",
                "trail": {"x": 0, "y": 0},
            }
        ]
    )

    with patch("services.strategy_module.symbol_resolver.lot_size_for", return_value=65):
        result = signals.handle_signal(strategy, "long_entry", leg_id=1)

    assert result.ok is False
    assert "whole number of lots" in result.error
    assert not placed


def test_units_mode_on_cash_places_the_quantity_as_written(placed):
    strategy = _make()

    result = signals.handle_signal(strategy, "long_entry", leg_id=1)

    assert result.ok is True
    assert placed[0]["quantity"] == "100"


# ---------------------------------------------------------------------------
# The trading-day boundary
#
# A signal run IS a trading day: its P&L, peak, trough and audit trail describe
# that day. Reusing one across days merges them, and a strategy left alone over
# a long weekend would report a single run spanning four sessions.
# ---------------------------------------------------------------------------


from datetime import UTC, datetime, timedelta  # noqa: E402


def _age_run(run_id, days):
    """Backdate a run's start, as if it had been opened on an earlier day."""
    run = store.get_run(run_id)
    run.started_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
    store.db_session.commit()


def test_a_flat_run_from_an_earlier_day_is_rolled(placed):
    strategy = _make()
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    first_run = store.get_strategy(strategy.id, USER).current_run_id

    # Close the leg so nothing is held. An exit ORDER is not a closed leg: the
    # leg closes when the fill arrives, which is what apply_fill delivers.
    engine.apply_fill(first_run, 1, 100.0, is_entry=True)
    signals.handle_signal(store.get_strategy(strategy.id, USER), "long_exit", leg_id=1)
    engine.apply_fill(first_run, 1, 105.0, is_entry=False)
    _age_run(first_run, days=3)

    signals.handle_signal(store.get_strategy(strategy.id, USER), "long_entry", leg_id=1)

    second_run = store.get_strategy(strategy.id, USER).current_run_id
    assert second_run != first_run

    closed = store.get_run(first_run)
    assert closed.stopped_at is not None
    assert closed.stop_reason == "eod"


def test_a_run_still_holding_a_position_is_never_rolled(placed):
    # An open leg is a live position. Finalising the run that owns it would
    # leave it with no run managing it, which is far worse than a merged P&L.
    strategy = _make()
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    run_id = store.get_strategy(strategy.id, USER).current_run_id
    _age_run(run_id, days=3)

    signals.handle_signal(store.get_strategy(strategy.id, USER), "long_entry", leg_id=2)

    assert store.get_strategy(strategy.id, USER).current_run_id == run_id
    assert store.get_run(run_id).stopped_at is None


def test_a_run_from_today_is_reused(placed):
    strategy = _make()
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    run_id = store.get_strategy(strategy.id, USER).current_run_id

    signals.handle_signal(store.get_strategy(strategy.id, USER), "long_entry", leg_id=2)

    assert store.get_strategy(strategy.id, USER).current_run_id == run_id
    assert len(store.list_runs(strategy.id)) == 1


def test_the_day_boundary_is_ist_not_utc(placed):
    # A run opened at 23:00 UTC is 04:30 IST the NEXT day. Comparing UTC dates
    # would roll the day in the middle of the night rather than between
    # sessions, and would treat that run as belonging to the previous day.
    strategy = _make()
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    run_id = store.get_strategy(strategy.id, USER).current_run_id
    run = store.get_run(run_id)

    # 23:00 UTC today is 04:30 IST tomorrow, so in IST terms this run has not
    # started before today and must not be rolled.
    run.started_at = datetime.now(UTC).replace(hour=23, minute=0, tzinfo=None)
    store.db_session.commit()

    assert signals._started_before_today(store.get_run(run_id)) is False


def test_a_signal_run_survives_a_round_trip_and_stays_open_for_the_session(placed):
    # A batch run ends when it goes flat, because a basket is entered and
    # exited as a unit. A signal run is a trading day: a leg exiting is an
    # ordinary mid-session event and the next alert reopens it. Ending the run
    # here would give five round trips five separate runs, fragmenting the
    # P&L, the peak and trough, and the audit trail meant to describe the day.
    strategy = _make()
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    run_id = store.get_strategy(strategy.id, USER).current_run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)

    signals.handle_signal(store.get_strategy(strategy.id, USER), "long_exit", leg_id=1)
    went_flat = engine.apply_fill(run_id, 1, 105.0, is_entry=False)

    assert went_flat is True
    # Flat, but still the session's run.
    assert store.get_run(run_id).stopped_at is None
    assert store.get_strategy(strategy.id, USER).current_run_id == run_id

    # And the next alert reuses it rather than opening a second.
    signals.handle_signal(store.get_strategy(strategy.id, USER), "long_entry", leg_id=1)
    assert store.get_strategy(strategy.id, USER).current_run_id == run_id
    assert len(store.list_runs(strategy.id)) == 1


def test_a_batch_run_still_ends_when_it_goes_flat(placed):
    # The other half of the same rule: a basket with nothing held is finished.
    strategy = _make(strategy_kind="batch", underlying="NIFTY", underlying_exchange="NSE_INDEX")
    run = store.create_run(strategy.id, "sandbox", "sandbox")
    store.set_strategy_status(strategy.id, "running", run.id)
    state.init_run_state(
        run.id,
        strategy.id,
        [{"leg_id": 1, "position": "S", "symbol": "X", "exchange": "NFO", "quantity": 75}],
    )
    engine.apply_fill(run.id, 1, 100.0, is_entry=True)

    went_flat = engine.apply_fill(run.id, 1, 80.0, is_entry=False)

    assert went_flat is True
    assert store.get_run(run.id).stopped_at is not None
    assert store.get_strategy(strategy.id, USER).status == "stopped"
