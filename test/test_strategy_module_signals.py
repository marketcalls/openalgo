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
from services.strategy_module import signals, state
from services.strategy_module.order_dispatch import DispatchResult

USER = "signal_test_user"


def _legs():
    return [
        {"id": 1, "symbol": "RELIANCE", "exchange": "NSE", "side": "both", "qty": 100,
         "segment": "cash", "sl_pts": 20, "trail": {"x": 0, "y": 0}},
        {"id": 2, "symbol": "SBIN", "exchange": "NSE", "side": "long", "qty": 50,
         "segment": "cash", "trail": {"x": 0, "y": 0}},
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
        patch.object(signals.order_dispatch, "dispatch_order", side_effect=record),
        patch.object(signals, "_api_key_for", return_value="test-key"),
    ):
        yield seen


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
    strategy = _make()
    signals.handle_signal(strategy, "short_entry", leg_id=1)
    signals.handle_signal(strategy, "long_entry", leg_id=2)
    placed.clear()

    refreshed = store.get_strategy(strategy.id, USER)
    closed = signals.close_all_signal_legs(refreshed, reason="eod")

    assert closed == 2
    actions = sorted(o["action"] for o in placed)
    assert actions == ["BUY", "SELL"]  # cover the short, sell the long
