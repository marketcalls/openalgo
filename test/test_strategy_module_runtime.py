"""Strategy module startup.

The ordering is the whole substance of this module, and each step in it is
there to close a window in which something would be missed. These assert the
order and that one failing piece does not take the rest down.
"""

from unittest.mock import MagicMock, patch

import pytest

from services.strategy_module import runtime


@pytest.fixture(autouse=True)
def not_started():
    runtime._started = False
    yield
    runtime._started = False


@pytest.fixture
def pieces():
    """Every background piece replaced, recording the order they are called."""
    order: list[str] = []
    feed = MagicMock()
    feed.set_on_price.side_effect = lambda _cb: order.append("price_hook")
    feed.add_run_subscriptions.side_effect = lambda *_a, **_k: order.append("subscribe")

    with (
        patch("services.strategy_module.order_events.start", side_effect=lambda: order.append("order_events")),
        patch(
            "services.strategy_module.recovery.recover_all",
            side_effect=lambda: (order.append("recovery"), {7: {("RELIANCE", "NSE")}})[1],
        ),
        patch("services.strategy_module.tick_feed.get_risk_tick_feed", return_value=feed),
        patch("services.strategy_module.checkpoint.start", side_effect=lambda: order.append("checkpoint")),
        patch("services.strategy_module.scheduler.start", side_effect=lambda: order.append("scheduler")),
        patch("services.strategy_module.scheduler.sync_all_jobs", side_effect=lambda: order.append("sync_jobs")),
    ):
        yield order, feed


def test_everything_starts_in_the_order_the_pieces_need(pieces):
    order, _feed = pieces

    runtime.start_strategy_module()

    # Order updates before recovery: recovery reconciles order rows, and a fill
    # arriving while it runs must be applied rather than fall between the two.
    assert order.index("order_events") < order.index("recovery")
    # The risk hook before any subscription: registering it after would leave a
    # window in which prices arrive and nothing judges them.
    assert order.index("price_hook") < order.index("subscribe")
    # The scheduler last: it can start new runs, and must not do that until
    # recovery has decided what is already running.
    assert order.index("recovery") < order.index("scheduler")


def test_the_risk_hook_is_the_engine_and_not_something_else(pieces):
    _order, feed = pieces
    from services.strategy_module import engine

    runtime.start_strategy_module()

    feed.set_on_price.assert_called_once_with(engine.process_tick)


def test_recovered_runs_get_their_instruments_back(pieces):
    _order, feed = pieces

    runtime.start_strategy_module()

    feed.add_run_subscriptions.assert_called_once()
    args = feed.add_run_subscriptions.call_args[0]
    assert args[0] == 7
    assert ("RELIANCE", "NSE") in args[1]


def test_one_failing_piece_does_not_stop_the_others(pieces):
    # A platform that will not boot because its strategy scheduler could not
    # start is worse than one that boots without it.
    order, _feed = pieces

    with patch(
        "services.strategy_module.checkpoint.start", side_effect=RuntimeError("boom")
    ):
        result = runtime.start_strategy_module()

    assert result["checkpoint"] is False
    assert result["scheduler"] is True
    assert "scheduler" in order


def test_a_failed_recovery_still_leaves_the_feed_and_scheduler_running(pieces):
    order, feed = pieces

    with patch(
        "services.strategy_module.recovery.recover_all", side_effect=RuntimeError("boom")
    ):
        result = runtime.start_strategy_module()

    assert result["recovery"] is False
    # The hook still gets registered, so a strategy started from the UI after
    # boot is still evaluated.
    feed.set_on_price.assert_called_once()
    assert "scheduler" in order


def test_starting_twice_does_nothing_the_second_time(pieces):
    order, _feed = pieces

    runtime.start_strategy_module()
    before = list(order)
    runtime.start_strategy_module()

    assert order == before
