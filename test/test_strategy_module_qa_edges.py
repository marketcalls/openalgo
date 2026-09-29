"""Adversarial edge cases for the /strategy module.

This suite is deliberately hostile. Everything here is a sequence a real broker,
a real alert engine or a real operator can produce, aimed at the seams the
happy-path suites do not reach: a fill that arrives twice or out of order, a
price that is not a price, an exit the broker refuses, a leg exited before its
entry ever filled, two signals a second apart.

What is asserted is money: how many orders were placed, with what action and
what quantity, and what the run's realized P&L ended up as. "It did not raise"
is not an outcome anybody's account can be reconciled against.

Only two things are mocked: the broker call (``dispatch_order``) and contract
resolution. The store, the run state and the risk core are the real ones, so a
figure asserted here is the figure the platform would report.

Tests marked ``xfail(strict=True)`` each name a defect that is live at the time
of writing. They assert the behaviour the module should have, not the behaviour
it has, so fixing the defect turns the marker into a failure that says so.
"""

import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

# restx_api first: see the note in test_strategy_module_order_dispatch.py.
import restx_api  # noqa: F401
from database import strategy_module_db as store
from services.strategy_module import (
    engine,
    order_events,
    recovery,
    risk_adapter,
    signals,
    state,
)
from services.strategy_module.order_dispatch import DispatchResult
from services.strategy_module.symbol_resolver import ResolvedLeg

USER = "sm_qa_edges_user"

CE = "NIFTY28MAY2624000CE"
PE = "NIFTY28MAY2624000PE"


# ---------------------------------------------------------------------------
# Fixtures and builders
# ---------------------------------------------------------------------------


def _leg(leg_id=1, position="S", sl_pts=20, target_pts=None, trail=None):
    leg = {
        "id": leg_id,
        "segment": "options",
        "expiry": "weekly",
        "lots": 1,
        "position": position,
        "option_type": "CE",
        "strike_mode": "atm",
        "atm_offset": "ATM",
        "sl_pts": sl_pts,
        "trail": trail or {"x": 0, "y": 0},
    }
    if target_pts is not None:
        leg["target_pts"] = target_pts
    return leg


def _config(name="QA edges", legs=None, **overrides):
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


def _resolved(symbol=CE, qty=75):
    return ResolvedLeg(
        ok=True,
        symbol=symbol,
        exchange="NFO",
        segment="options",
        lotsize=75,
        tick_size=0.05,
        strike=24000.0,
        expiry="28-MAY-26",
        expiry_symbol="28MAY26",
        quantity=qty,
        lots=1,
        option_type="CE",
        underlying="NIFTY",
        underlying_ltp=24010.0,
        atm_strike=24000.0,
    )


@pytest.fixture(autouse=True)
def clean_slate():
    store.db_session.remove()
    store.init_db()

    def purge():
        for row in store.list_strategies(USER):
            for run in store.list_runs(row["id"]):
                state.clear_run_state(run["id"])
                if run["stopped_at"] is None:
                    store.finish_run(run["id"], "error")
            state.clear_run_state(row["current_run_id"] or -1)
            store.set_strategy_status(row["id"], "stopped", None)
            store.delete_strategy(row["id"], USER)
        # See the note in test_strategy_module_qa_segments.py: run state is
        # keyed by a rowid SQLite reuses, so anything left registered becomes
        # another suite's run.
        for run_id in list(state.active_run_ids()):
            state.clear_run_state(run_id)
        store.clear_strategy_module_cache()

    purge()
    yield
    purge()


@pytest.fixture(autouse=True)
def api_key():
    """Every order path needs a server-side API key; none of these need a real one.

    The price feed is stubbed out with it. Every test here drives
    ``process_tick`` directly, so letting ``start_run`` subscribe would spin up
    the real feed's poller and reach for quotes over the network for prices
    nothing in this file reads.
    """
    with (
        patch.object(engine, "_api_key_for", return_value="qa-api-key"),
        patch.object(signals, "_api_key_for", return_value="qa-api-key"),
        patch.object(engine, "_subscribe_run"),
        patch.object(engine, "_unsubscribe_run"),
    ):
        yield "qa-api-key"


class Broker:
    """A fake broker that records every order and can be told to refuse.

    ``orders`` is the audit this suite asserts against: action, quantity and
    symbol, in the order they reached the broker.
    """

    def __init__(self):
        self.orders = []
        self.refuse = False
        self.error = "Broker refused the order"
        self._n = 0

    def __call__(self, **kwargs):
        order = kwargs["order"]
        self.orders.append(order)
        if self.refuse:
            return DispatchResult(ok=False, error=self.error)
        self._n += 1
        return DispatchResult(ok=True, broker_order_id=f"QA-{self._n}", response={})

    @property
    def actions(self):
        return [o["action"] for o in self.orders]

    @property
    def quantities(self):
        return [int(o["quantity"]) for o in self.orders]

    def clear(self):
        self.orders.clear()


@pytest.fixture
def broker():
    fake = Broker()
    with patch.object(engine.order_dispatch, "dispatch_order", side_effect=fake):
        yield fake


def _make(config=None):
    created, error = store.create_strategy(USER, config or _config())
    assert error is None, error
    return created["id"]


def _start(sid, resolved=None, mode="sandbox"):
    resolved = resolved if resolved is not None else [_resolved()]
    with (
        patch.object(engine, "resolve_leg", side_effect=list(resolved) * 6),
        patch.object(engine, "_broker_for", return_value="sandbox"),
    ):
        return engine.start_run(sid, USER, mode)


def _live(run_id, leg_id=1):
    """One leg of a live run, as a plain dict."""
    snapshot = state.get_run_state(run_id)
    assert snapshot is not None, f"run {run_id} has no live state"
    return snapshot["legs"][str(leg_id)]


def _event(orderid, status="complete", avg=100.0, filled=None, rejection=""):
    if filled is None and str(status).strip().lower() in {
        "rejected",
        "cancelled",
        "canceled",
    }:
        filled = 0
    return SimpleNamespace(
        orderid=orderid,
        order_status=status,
        average_price=avg,
        filled_quantity=filled,
        rejection_reason=rejection,
    )


def _two_leg_run(broker, positions=("S", "B")):
    """A started run holding two legs on distinct instruments."""
    sid = _make(
        _config(
            legs=[
                _leg(leg_id=1, position=positions[0]),
                _leg(leg_id=2, position=positions[1]),
            ]
        )
    )
    result = _start(sid, resolved=[_resolved(symbol=CE), _resolved(symbol=PE)])
    assert result.ok is True, result.error
    broker.clear()
    return sid, result.run_id


# ===========================================================================
# Fills and the order-update path
# ===========================================================================


@pytest.mark.parametrize(
    "case",
    ["stale_order_id", "no_exit_in_flight", "partial_entry", "zero_entry_price"],
)
def test_apply_fill_warnings_run_after_the_run_lock_is_released(case):
    """Logging may acquire handler locks, so no warning may run under a run lock."""
    run_id = 991_000
    state.init_run_state(
        run_id,
        strategy_id=1,
        legs=[
            {
                "leg_id": 1,
                "position": "B",
                "position_ref": "warning-position",
                "symbol": CE,
                "exchange": "NFO",
                "quantity": 75,
            }
        ],
    )
    with state.run_state(run_id) as run:
        leg = run["legs"]["1"]
        leg["status"] = "open"
        leg["entry_status"] = "complete"

    if case == "stale_order_id":
        with state.run_state(run_id) as run:
            run["legs"]["1"]["entry_order_id"] = 10
        fill = {"avg_price": 100.0, "is_entry": True, "order_row_id": 11}
    elif case == "no_exit_in_flight":
        fill = {"avg_price": 99.0, "is_entry": False, "order_row_id": 11}
    elif case == "partial_entry":
        fill = {"avg_price": 100.0, "is_entry": True, "filled_qty": 25}
    else:
        fill = {"avg_price": 99.0, "is_entry": False}

    run_lock = state.get_state_lock(run_id)
    warning_lock_states = []

    def observe_warning(*_args, **_kwargs):
        acquired = run_lock.acquire(blocking=False)
        warning_lock_states.append(acquired)
        if acquired:
            run_lock.release()

    with patch.object(engine.logger, "warning", side_effect=observe_warning):
        engine.apply_fill(run_id, 1, position_ref="warning-position", **fill)

    assert warning_lock_states == [True], "logger.warning ran while state.run_state was held"


def test_a_positive_fill_quantity_without_price_stays_managed_and_visible(broker):
    """A positive broker quantity is exposure even when its price is unusable."""
    sid = _make()
    run_id = _start(sid).run_id

    order_events._apply_update("QA-1", _event("QA-1", avg="0", filled=75))

    leg = _live(run_id)
    assert leg["entry_avg"] == 0.0
    assert leg["entry_status"] == "complete"
    assert leg["status"] == "open"
    assert leg["qty"] == 75
    critical = [
        event
        for event in store.list_events(sid)
        if event["kind"] == "leg_entry_placed" and event["severity"] == "critical"
    ]
    assert critical
    assert "managed" in critical[0]["message"].lower()
    assert "price" in critical[0]["message"].lower()
    assert store.get_strategy(sid, USER)  # keep the strategy referenced


def test_an_unpriced_filled_leg_can_still_be_flattened_at_exact_quantity(broker):
    """Unavailable valuation disables automatic risk, not manual flattening."""
    sid = _make()
    run_id = _start(sid).run_id
    order_events._apply_update("QA-1", _event("QA-1", avg="0", filled=75))
    broker.clear()

    engine.process_tick(CE, "NFO", 500.0)

    leg = _live(run_id)
    assert leg["entry_status"] == "complete"
    assert leg["effective_sl"] is None
    assert broker.orders == []

    result = engine.stop_run(run_id, USER, reason="manual")

    assert result["ok"] is True
    assert result["stop_pending"] is True
    assert broker.quantities == [75]


def test_a_fill_priced_negative_is_not_applied(broker):
    """A negative average price is not a price on any exchange.

    It passes the ``if avg_price:`` guard, so the leg is seeded at the negative
    number. Nothing downstream rejects it: the stop is silently absent, and the
    realized figure the exit fill later produces is wrong by the whole notional.
    """
    sid = _make()
    run_id = _start(sid).run_id

    order_events._apply_update("QA-1", _event("QA-1", avg=-12.5))

    assert _live(run_id)["entry_avg"] == 0.0, "a negative fill price reached the leg"


def test_a_fill_priced_as_a_numeric_string_is_applied_as_that_number(broker):
    """Brokers send numbers as strings. A usable one must still seed the leg."""
    sid = _make()
    run_id = _start(sid).run_id

    order_events._apply_update("QA-1", _event("QA-1", avg="101.5"))

    leg = _live(run_id)
    assert leg["entry_avg"] == 101.5
    assert leg["entry_status"] == "complete"


def test_an_unparseable_fill_price_keeps_quantity_managed_but_unpriced(broker):
    """Junk is not a price, but a complete quantity remains real exposure."""
    sid = _make()
    run_id = _start(sid).run_id

    order_events._apply_update("QA-1", _event("QA-1", avg="N/A"))

    leg = _live(run_id)
    assert leg["entry_avg"] == 0.0
    assert leg["entry_status"] == "complete"
    assert leg["status"] == "open"
    assert leg["qty"] == 75


def test_a_partially_filled_entry_is_exited_at_the_quantity_that_actually_filled(broker):
    """75 were ordered, 25 filled. The exit must be for 25.

    Exiting 75 against a position of 25 does not flatten it, it reverses it:
    the account ends the day short 50 of a contract nobody chose to be short of,
    with no stop and no run watching it.
    """
    sid = _make()
    run_id = _start(sid).run_id
    order_events._apply_update("QA-1", _event("QA-1", avg=100.0, filled=25))
    broker.clear()

    engine.stop_run(run_id, USER, reason="manual")

    exits = [o for o in store.list_orders(run_id) if o["kind"] != "entry"]
    assert len(exits) == 1
    assert exits[0]["qty"] == 25
    assert broker.quantities == [25]


def test_the_same_exit_fill_arriving_twice_is_counted_once_in_the_run_pnl(broker):
    """A postback and the update stream deliver the same fill.

    Counted twice, the run's realized figure doubles, and every strategy-level
    rule is then judged against a number the account never made.
    """
    sid, run_id = _two_leg_run(broker)
    order_events._apply_update("QA-1", _event("QA-1", avg=100.0))  # leg placed first
    order_events._apply_update("QA-2", _event("QA-2", avg=50.0))
    entry_ids = {o["leg_id"]: o["broker_order_id"] for o in store.list_orders(run_id)}

    with patch.object(engine.order_dispatch, "dispatch_order", side_effect=broker):
        engine.close_leg(run_id, 1, USER)
    exit_row = [o for o in store.list_orders(run_id) if o["kind"] == "exit_leg_manual"][0]

    order_events._apply_update(
        exit_row["broker_order_id"], _event(exit_row["broker_order_id"], avg=80.0)
    )
    order_events._apply_update(
        exit_row["broker_order_id"], _event(exit_row["broker_order_id"], avg=80.0)
    )

    leg_one_entry = 100.0 if entry_ids.get(1) == "QA-1" else 50.0
    expected = (80.0 - leg_one_entry) * 75 * -1  # leg 1 is the short
    assert _live(run_id, 1)["realized_pnl"] == pytest.approx(expected)
    assert state.get_run_state(run_id)["pnl_realized"] == pytest.approx(expected)


def test_higher_complete_after_cancel_is_terminal_correction_and_managed_exposure(broker):
    """Higher cumulative fill evidence corrects a dead zero without becoming working."""
    sid = _make()
    run_id = _start(sid).run_id

    order_events._apply_update("QA-1", _event("QA-1", status="cancelled", avg=0, filled=0))
    order_events._apply_update("QA-1", _event("QA-1", status="complete", avg=101.5))

    durable = store.list_orders(run_id)[0]
    assert durable["status"] == "complete"
    assert durable["filled_qty"] == 75
    assert _live(run_id)["entry_avg"] == pytest.approx(101.5)
    assert _live(run_id)["entry_status"] == "complete"
    assert _live(run_id)["status"] == "open"
    assert _live(run_id)["qty"] == 75


def test_a_cancelled_order_is_recorded_as_cancelled_not_as_rejected(broker):
    """``store.ORDER_STATUSES`` carries both. The audit trail should tell them apart."""
    sid = _make()
    run_id = _start(sid).run_id

    order_events._apply_update("QA-1", _event("QA-1", status="cancelled", avg=0))

    assert store.list_orders(run_id)[0]["status"] == "cancelled"


def test_a_working_status_arriving_after_a_fill_does_not_downgrade_the_row(broker):
    """Brokers replay. "complete" then "open" must leave the fill standing."""
    sid = _make()
    run_id = _start(sid).run_id

    order_events._apply_update("QA-1", _event("QA-1", status="complete", avg=101.5))
    order_events._apply_update("QA-1", _event("QA-1", status="open", avg=0, filled=0))

    row = store.list_orders(run_id)[0]
    assert row["status"] == "complete"
    assert row["avg_fill_price"] == 101.5
    assert _live(run_id)["entry_avg"] == 101.5


def test_a_fill_for_a_rejected_entry_never_opens_a_position(broker):
    """The entry was refused at dispatch. A stream fill must not invent a leg."""
    broker.refuse = True
    sid = _make()
    result = _start(sid)
    assert result.ok is False
    broker.refuse = False

    # The run was finalised, so a late fill has nothing to attach to. What must
    # not happen is a leg coming back open, or an exit being placed for it.
    run_id = store.list_runs(sid)[0]["id"]
    order_events._apply_update("QA-1", _event("QA-1", avg=100.0))

    assert state.get_run_state(run_id) is None
    assert [o["kind"] for o in store.list_orders(run_id)] == ["entry"]
    assert store.list_orders(run_id)[0]["status"] == "rejected"


def test_a_fill_for_a_finished_runs_order_leaves_every_live_run_alone(broker):
    """One strategy's stale fill must not disturb another that is still trading."""
    dead_sid = _make(_config(name="Finished"))
    dead_run = _start(dead_sid).run_id
    dead_order = store.list_orders(dead_run)[0]["broker_order_id"]
    engine.stop_run(dead_run, USER, reason="manual")
    broker.clear()

    live_sid = _make(_config(name="Still trading"))
    live_run = _start(live_sid, resolved=[_resolved(symbol=PE)]).run_id
    live_order = store.list_orders(live_run)[0]["broker_order_id"]
    order_events._apply_update(live_order, _event(live_order, avg=100.0))
    broker.clear()

    order_events._apply_update(dead_order, _event(dead_order, avg=999.0))

    assert _live(live_run)["entry_avg"] == 100.0
    assert broker.orders == []


def test_a_broker_order_id_shared_by_two_legs_seeds_only_the_first_row(broker):
    """``get_order_by_broker_id`` is unscoped and takes ``.first()``.

    Two rows carrying the same reference means one leg is silently never
    seeded, so it keeps its stop derived from an entry of zero, which is no
    stop at all. Characterised rather than xfailed: a broker reusing a
    reference across two orders is out of contract, but nothing here detects it.
    """
    sid = _make(_config(legs=[_leg(leg_id=1, position="S"), _leg(leg_id=2, position="B")]))
    with (
        patch.object(
            engine,
            "resolve_leg",
            side_effect=[_resolved(symbol=CE), _resolved(symbol=PE)] * 3,
        ),
        patch.object(engine, "_broker_for", return_value="sandbox"),
        patch.object(
            engine.order_dispatch,
            "dispatch_order",
            return_value=DispatchResult(ok=True, broker_order_id="SAME", response={}),
        ),
    ):
        run_id = engine.start_run(sid, USER, "sandbox").run_id

    order_events._apply_update("SAME", _event("SAME", avg=100.0))

    seeded = [_live(run_id, 1)["entry_avg"], _live(run_id, 2)["entry_avg"]]
    assert sorted(seeded) == [0.0, 100.0], "one of the two legs was left unseeded"


# ===========================================================================
# The daily loss limit
# ===========================================================================


def test_the_daily_loss_limit_counts_what_earlier_runs_already_lost(broker):
    """The limit is on the session, not on whichever run happens to be open.

    It was validated, stored, shown in the UI and read by nothing, so a
    strategy that lost its whole budget across three runs opened a fourth.
    overall_sl_mtm cannot express this: that one resets every time a run opens,
    which for a signal or scheduled strategy is several times a day.
    """
    sid = _make(_config(daily_loss_limit_inr=1000))

    # Two runs that are already over, together down 1100: the budget is spent.
    for _ in range(2):
        done = _start(sid).run_id
        # Filled, or the stop is refused: there is no confirmed quantity to
        # square off and the run stays open by design.
        engine.apply_fill(done, 1, 100.0, is_entry=True)
        engine.stop_run(done, USER, "manual")
        exit_row = max(store.list_orders(done), key=lambda row: row["id"])
        order_events._apply_update(
            exit_row["broker_order_id"],
            _event(exit_row["broker_order_id"], avg=100.0 + (550.0 / 75.0)),
        )
    broker.clear()

    # A third opens anyway, and is squared off on its first tick even though
    # this run itself has lost nothing.
    run_id = _start(sid).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    broker.clear()

    engine.process_tick(CE, "NFO", 100.0)

    pending_run = store.get_run(run_id)
    assert pending_run.stop_reason is None
    assert pending_run.stop_requested_reason == "daily_loss_limit"
    assert pending_run.stopped_at is None
    assert broker.actions == ["BUY"], "the open position was squared off"

    exit_row = max(store.list_orders(run_id), key=lambda row: row["id"])
    order_events._apply_update(
        exit_row["broker_order_id"],
        _event(exit_row["broker_order_id"], avg=100.0),
    )

    stopped_run = store.get_run(run_id)
    assert stopped_run.stop_reason == "daily_loss_limit"
    assert stopped_run.stopped_at is not None


def test_a_session_still_inside_the_daily_limit_keeps_trading(broker):
    """The other half: the limit must not fire early."""
    sid = _make(_config(daily_loss_limit_inr=1000))
    first = _start(sid).run_id
    engine.apply_fill(first, 1, 100.0, is_entry=True)
    engine.stop_run(first, USER, "manual")
    exit_row = max(store.list_orders(first), key=lambda row: row["id"])
    order_events._apply_update(
        exit_row["broker_order_id"],
        _event(exit_row["broker_order_id"], avg=100.0 + (700.0 / 75.0)),
    )
    broker.clear()

    run_id = _start(sid).run_id
    order_events._apply_update("QA-3", _event("QA-3", avg=100.0))
    broker.clear()

    engine.process_tick(CE, "NFO", 100.0)

    assert store.get_run(run_id).stopped_at is None, "700 down against a limit of 1000"
    assert broker.orders == []


def test_a_strategy_with_no_daily_limit_is_never_stopped_by_one(broker):
    sid = _make()
    first = _start(sid).run_id
    engine.apply_fill(first, 1, 100.0, is_entry=True)
    engine.stop_run(first, USER, "manual")
    exit_row = max(store.list_orders(first), key=lambda row: row["id"])
    order_events._apply_update(
        exit_row["broker_order_id"],
        _event(exit_row["broker_order_id"], avg=100.0 + (99999.0 / 75.0)),
    )
    broker.clear()

    run_id = _start(sid).run_id
    order_events._apply_update("QA-3", _event("QA-3", avg=100.0))
    broker.clear()

    engine.process_tick(CE, "NFO", 100.0)

    assert store.get_run(run_id).stopped_at is None
    assert broker.orders == []


# ===========================================================================
# Run lifecycle
# ===========================================================================


def test_two_starts_racing_place_exactly_one_set_of_entries(broker):
    """The UI, the scheduler and a webhook can all fire on the same instant."""
    sid = _make()
    results = []
    barrier = threading.Barrier(2)

    # Patched once, out here, rather than inside each thread. unittest.mock
    # restores by writing the saved value back, so two threads patching the
    # same attribute can interleave save and restore and leave the mock
    # installed for the rest of the session: every later suite then resolved
    # every leg to this file's fake option, until the side_effect list ran out
    # and they raised StopIteration instead.
    def go():
        barrier.wait()
        results.append(engine.start_run(sid, USER, "sandbox"))

    with (
        patch.object(engine, "resolve_leg", side_effect=[_resolved()] * 6),
        patch.object(engine, "_broker_for", return_value="sandbox"),
    ):
        threads = [threading.Thread(target=go) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

    assert sorted(r.ok for r in results) == [False, True]
    assert len(store.list_runs(sid)) == 1
    assert len(broker.orders) == 1


def test_one_rejected_entry_of_three_leaves_the_other_two_managed(broker):
    """A partial basket still has to be a managed basket.

    The refused leg must not be exited, must not be priced, and must not stop
    the other two from having their stops enforced.
    """
    sid = _make(
        _config(
            legs=[
                _leg(leg_id=1, position="S"),
                _leg(leg_id=2, position="S"),
                _leg(leg_id=3, position="S"),
            ]
        )
    )
    calls = {"n": 0}

    def flaky(**kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            return DispatchResult(ok=False, error="Insufficient margin")
        return broker(**kwargs)

    with patch.object(engine.order_dispatch, "dispatch_order", side_effect=flaky):
        result = _start(
            sid,
            resolved=[
                _resolved(symbol="LEG1"),
                _resolved(symbol="LEG2"),
                _resolved(symbol="LEG3"),
            ],
        )
        assert result.ok is True
        assert [leg["ok"] for leg in result.legs] == [True, False, True]

        engine.apply_fill(result.run_id, 1, 100.0, is_entry=True)
        engine.apply_fill(result.run_id, 3, 100.0, is_entry=True)
        broker.clear()

        engine.process_tick("LEG2", "NFO", 500.0)  # the refused leg: nothing to do
        assert broker.orders == []

        engine.process_tick("LEG1", "NFO", 121.0)  # a real stop on a real leg

    assert broker.actions == ["BUY"]
    assert _live(result.run_id, 2)["status"] == "rejected"
    assert store.get_run(result.run_id).stopped_at is None


def test_every_entry_rejected_places_no_exit_at_all(broker):
    """Nothing was bought, so nothing may be sold.

    An exit placed here would open the opposite position outright.
    """
    broker.refuse = True
    sid = _make(_config(legs=[_leg(leg_id=1, position="S"), _leg(leg_id=2, position="B")]))

    result = _start(sid, resolved=[_resolved(symbol=CE), _resolved(symbol=PE)])

    assert result.ok is False
    kinds = [o["kind"] for o in store.list_orders(store.list_runs(sid)[0]["id"])]
    assert kinds == ["entry", "entry"]
    assert len(broker.orders) == 2


def _filled_batch_run(broker):
    strategy_id = _make()
    run_id = _start(strategy_id).run_id
    entry = store.list_orders(run_id)[0]
    order_events._apply_update(
        entry["broker_order_id"],
        _event(entry["broker_order_id"], status="complete", avg=100.0),
    )
    broker.clear()
    return strategy_id, run_id


def test_stop_pending_is_durable_before_exit_dispatch_and_waits_for_the_fill(broker):
    strategy_id, run_id = _filled_batch_run(broker)
    at_dispatch = []

    def inspect_stop_intent(**kwargs):
        run = store.get_run(run_id)
        kinds = [event["kind"] for event in store.list_events(strategy_id)]
        at_dispatch.append((run.stop_requested_reason, "run_stop_requested" in kinds))
        return broker(**kwargs)

    with patch.object(engine.order_dispatch, "dispatch_order", side_effect=inspect_stop_intent):
        result = engine.stop_run(run_id, USER, reason="manual")

    assert at_dispatch == [("manual", True)]
    assert result["ok"] is True
    assert result["stop_pending"] is True
    assert store.get_run(run_id).stopped_at is None
    assert state.get_run_state(run_id) is not None
    kinds = [event["kind"] for event in store.list_events(strategy_id)]
    assert kinds.count("run_stop_requested") == 1
    assert "run_stopped" not in kinds


def test_stop_is_not_dispatched_when_its_durable_request_cannot_be_written(broker):
    _strategy_id, run_id = _filled_batch_run(broker)

    with patch.object(store, "request_run_stop", return_value=False):
        result = engine.stop_run(run_id, USER, reason="manual")

    assert result["ok"] is False
    assert broker.orders == []
    assert [order for order in store.list_orders(run_id) if order["kind"] != "entry"] == []
    assert state.get_run_state(run_id) is not None


def test_immediate_exit_fill_finishes_the_stop_once_and_returns_not_pending(broker):
    strategy_id, run_id = _filled_batch_run(broker)

    def fill_before_ack(**_kwargs):
        broker_order_id = "QA-INLINE-EXIT"
        order_events._apply_update(
            broker_order_id,
            _event(broker_order_id, status="complete", avg=90.0),
        )
        return DispatchResult(ok=True, broker_order_id=broker_order_id, response={})

    with patch.object(engine.order_dispatch, "dispatch_order", side_effect=fill_before_ack):
        result = engine.stop_run(run_id, USER, reason="manual")

    assert result["ok"] is True
    assert result["stop_pending"] is False
    assert store.get_run(run_id).stopped_at is not None
    assert state.get_run_state(run_id) is None
    kinds = [event["kind"] for event in store.list_events(strategy_id)]
    assert kinds.count("run_stop_requested") == 1
    assert kinds.count("run_stopped") == 1


def test_synchronous_sandbox_target_lifecycle_preserves_reason_and_final_figures():
    """A target peak and later execution P&L are separate durable truths."""
    sid = _make(
        _config(
            legs=[
                _leg(leg_id=1, position="S"),
                _leg(leg_id=2, position="S"),
            ],
            overall_target_mtm=500,
        )
    )
    entry_prices = iter([888.10, 620.50])
    exit_prices = iter([883.45, 623.85])
    entry_number = 0
    exit_number = 0

    def fill_inside_dispatch(**kwargs):
        nonlocal entry_number, exit_number
        order = kwargs["order"]
        if order["action"] == "SELL":
            entry_number += 1
            broker_order_id = f"SYNC-ENTRY-{entry_number}"
            price = next(entry_prices)
        else:
            exit_number += 1
            broker_order_id = f"SYNC-TARGET-EXIT-{exit_number}"
            price = next(exit_prices)
        # The sandbox publishes before dispatch returns. The update is cached
        # until the durable pending row receives this broker reference, then
        # replayed synchronously by the engine acknowledgement path.
        order_events._apply_update(
            broker_order_id,
            _event(
                broker_order_id,
                status="complete",
                avg=price,
                filled=90,
            ),
        )
        return DispatchResult(
            ok=True,
            broker_order_id=broker_order_id,
            response={},
        )

    with (
        patch.object(
            engine,
            "resolve_leg",
            side_effect=[
                _resolved(symbol=CE, qty=90),
                _resolved(symbol=PE, qty=90),
            ],
        ),
        patch.object(engine, "_broker_for", return_value="sandbox"),
        patch.object(
            engine.order_dispatch,
            "dispatch_order",
            side_effect=fill_inside_dispatch,
        ),
    ):
        started = engine.start_run(sid, USER, "sandbox")
        assert started.ok is True
        run_id = started.run_id
        assert run_id is not None

        # First mark contributes +418.50. The second latest mark contributes
        # +94.50 and takes the basket to its +513.00 target. Execution then
        # realizes only +117.00 because the PE exit fills at 623.85.
        engine.process_tick(CE, "NFO", 883.45)
        engine.process_tick(PE, "NFO", 619.45)

    durable = store.get_run(run_id)
    assert durable.stopped_at is not None
    assert durable.stop_reason == "overall_target"
    assert durable.stop_requested_reason is None
    assert float(durable.pnl_realized) == pytest.approx(117.0)
    assert float(durable.pnl_peak) == pytest.approx(513.0)
    assert float(durable.pnl_trough) == pytest.approx(0.0)
    assert state.get_run_state(run_id) is None

    orders = store.list_orders(run_id)
    assert [row["kind"] for row in orders] == [
        "entry",
        "entry",
        "exit_overall_target",
        "exit_overall_target",
    ]
    assert [row["status"] for row in orders] == [
        "complete",
        "complete",
        "complete",
        "complete",
    ]
    events = store.list_events(sid)
    event_kinds = [event["kind"] for event in events]
    assert event_kinds.count("overall_target_hit") == 1
    assert event_kinds.count("run_stop_requested") == 1
    assert event_kinds.count("run_stopped") == 1
    target_event = next(event for event in events if event["kind"] == "overall_target_hit")
    payload = target_event["payload"]
    assert payload == {
        "trigger_total": 513.0,
        "reason": "overall_target",
        "threshold": 500.0,
        "triggering_tick": {
            "symbol": PE,
            "exchange": "NFO",
            "ltp": 619.45,
        },
        "legs": [
            {
                "symbol": CE,
                "exchange": "NFO",
                "ltp": 883.45,
                "mtm": 418.5,
                "tick_source": "ws",
                "qty": 90,
                "position": "S",
            },
            {
                "symbol": PE,
                "exchange": "NFO",
                "ltp": 619.45,
                "mtm": 94.5,
                "tick_source": "ws",
                "qty": 90,
                "position": "S",
            },
        ],
    }
    assert sum(leg["mtm"] for leg in payload["legs"]) == pytest.approx(513.0)
    assert sum(leg["mtm"] for leg in payload["legs"]) == pytest.approx(
        payload["trigger_total"]
    )
    lifecycle = [
        event["kind"]
        for event in sorted(events, key=lambda event: event["id"])
        if event["kind"]
        in {"overall_target_hit", "leg_exit_placed", "run_stopped"}
    ]
    assert lifecycle == [
        "overall_target_hit",
        "leg_exit_placed",
        "leg_exit_placed",
        "run_stopped",
    ]


def test_final_exit_fill_completes_a_pending_stop(broker):
    strategy_id, run_id = _filled_batch_run(broker)
    pending = engine.stop_run(run_id, USER, reason="scheduler")
    exit_row = max(store.list_orders(run_id), key=lambda row: row["id"])

    order_events._apply_update(
        exit_row["broker_order_id"],
        _event(exit_row["broker_order_id"], status="complete", avg=101.0),
    )

    assert pending["stop_pending"] is True
    stopped = store.get_run(run_id)
    assert stopped.stopped_at is not None
    assert stopped.stop_reason == "scheduler"
    assert stopped.stop_requested_reason is None
    assert state.get_run_state(run_id) is None
    kinds = [event["kind"] for event in store.list_events(strategy_id)]
    assert kinds.count("run_stopped") == 1


def test_async_rejected_stop_exit_stays_managed_and_retryable(broker):
    strategy_id, run_id = _filled_batch_run(broker)
    first = engine.stop_run(run_id, USER, reason="manual")
    exit_row = max(store.list_orders(run_id), key=lambda row: row["id"])

    order_events._apply_update(
        exit_row["broker_order_id"],
        _event(exit_row["broker_order_id"], status="rejected", avg=0, filled=0),
    )

    assert first["stop_pending"] is True
    assert store.get_run(run_id).stopped_at is None
    leg = state.get_run_state(run_id)["legs"]["1"]
    assert leg["exit_order_id"] is None
    assert leg["exit_kind"] is None
    failures = [
        event for event in store.list_events(strategy_id) if event["kind"] == "run_stop_failed"
    ]
    assert len(failures) == 1
    assert "managed" in failures[0]["message"].lower()
    assert "retry" in failures[0]["message"].lower()

    broker.clear()
    retry = engine.stop_run(run_id, USER, reason="manual")
    assert retry["ok"] is True
    assert retry["stop_pending"] is True
    assert broker.actions == ["BUY"]


def test_pending_stop_waits_for_both_live_and_superseded_position_fills(broker):
    strategy = _signal_strategy()
    strategy_id = strategy.id
    assert signals.handle_signal(strategy, "long_entry", leg_id=1).ok is True
    run_id = _run_of(strategy)
    first_entry = store.list_orders(run_id)[0]
    order_events._apply_update(
        first_entry["broker_order_id"],
        _event(first_entry["broker_order_id"], status="complete", avg=100.0, filled=100),
    )
    broker.clear()
    strategy = store.get_strategy(strategy_id, USER)

    # The old long's SELL is accepted but not filled, and the replacement
    # short opens immediately. One leg id now owns two actual positions.
    flipped = signals.handle_signal(strategy, "short_entry", leg_id=1)
    assert flipped.ok is True
    assert flipped.flipped is True
    rows = store.list_orders(run_id)
    replacement_entry = [row for row in rows if row["kind"] == "entry"][-1]
    outgoing_exit = [row for row in rows if row["kind"] == "exit_signal"][-1]
    order_events._apply_update(
        replacement_entry["broker_order_id"],
        _event(
            replacement_entry["broker_order_id"],
            status="complete",
            avg=95.0,
            filled=100,
        ),
    )
    broker.clear()

    pending = engine.stop_run(run_id, USER, reason="manual")
    assert pending["stop_pending"] is True
    live_exit = [row for row in store.list_orders(run_id) if row["kind"] == "exit_close_all"][-1]
    assert live_exit["position_ref"] == replacement_entry["position_ref"]

    # The old long's first exit dies after acceptance. Retrying the stop must
    # cover that exact old reference without duplicating the live short exit.
    order_events._apply_update(
        outgoing_exit["broker_order_id"],
        _event(outgoing_exit["broker_order_id"], status="rejected", avg=0, filled=0),
    )
    broker.clear()
    retried = engine.stop_run(run_id, USER, reason="manual")
    assert retried["stop_pending"] is True
    assert broker.actions == ["SELL"]
    outgoing_retry = max(store.list_orders(run_id), key=lambda row: row["id"])
    assert outgoing_retry["position_ref"] == first_entry["position_ref"]
    assert outgoing_retry["position_ref"] != live_exit["position_ref"]

    # The replacement short is flat, but the outgoing long is still held.
    order_events._apply_update(
        live_exit["broker_order_id"],
        _event(live_exit["broker_order_id"], status="complete", avg=90.0, filled=100),
    )
    assert store.get_run(run_id).stopped_at is None
    remaining = state.get_run_state(run_id)["legs"]["1"]
    assert remaining["status"] == "closed"
    assert remaining["superseded"]["position_ref"] == first_entry["position_ref"]

    # Only the old long's exact exit can now make the run genuinely flat.
    order_events._apply_update(
        outgoing_retry["broker_order_id"],
        _event(outgoing_retry["broker_order_id"], status="complete", avg=98.0, filled=100),
    )
    assert store.get_run(run_id).stopped_at is not None
    assert state.get_run_state(run_id) is None
    stops = [event for event in store.list_events(strategy_id) if event["kind"] == "run_stopped"]
    assert len(stops) == 1


def test_a_stop_whose_exits_were_all_refused_does_not_close_the_run(broker):
    """The broker said no. The position is still there.

    Finalising here releases the strategy, drops the run's live state and
    unsubscribes its prices, so the position that is still at the broker has no
    stop loss and nothing watching it for the rest of the session.
    """
    sid = _make()
    run_id = _start(sid).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    broker.clear()
    broker.refuse = True

    result = engine.stop_run(run_id, USER, reason="manual")

    assert result["ok"] is False
    assert result["stop_pending"] is True
    assert store.get_run(run_id).stop_requested_reason == "manual"
    assert store.get_run(run_id).stopped_at is None
    assert state.get_run_state(run_id) is not None
    kinds = [event["kind"] for event in store.list_events(sid)]
    assert "run_stop_requested" in kinds
    assert "run_stop_failed" in kinds
    assert "run_stopped" not in kinds


def test_manual_retry_keeps_the_first_automatic_stop_cause_and_exit_kind(broker):
    """An operator retry must not rewrite why risk first stopped the run."""
    sid = _make()
    run_id = _start(sid).run_id
    order_events._apply_update("QA-1", _event("QA-1", avg=100.0))
    broker.clear()
    broker.refuse = True

    first = engine.stop_run(run_id, USER, reason="overall_target")
    first_requested_at = store.get_run(run_id).stop_requested_at
    broker.refuse = False
    second = engine.stop_run(run_id, USER, reason="manual")

    assert first["stop_pending"] is True
    assert second["stop_pending"] is True
    durable = store.get_run(run_id)
    assert durable.stop_requested_at == first_requested_at
    assert durable.stop_requested_reason == "overall_target"
    exit_kinds = [
        row["kind"] for row in store.list_orders(run_id) if row["kind"] != "entry"
    ]
    assert exit_kinds == ["exit_overall_target", "exit_overall_target"]
    requested_messages = [
        event["message"]
        for event in store.list_events(sid)
        if event["kind"] == "run_stop_requested"
    ]
    assert requested_messages == [
        "Stop requested (overall_target); exit orders are being attempted",
        "Stop requested (overall_target); exit orders are being attempted",
    ]


def test_closing_a_leg_whose_exit_was_refused_reports_the_failure(broker):
    """The operator pressed close and the broker refused. Saying "ok" is a lie.

    The UI marks the leg closed, the operator moves on, and the position stays
    open with nothing said about it.
    """
    sid, run_id = _two_leg_run(broker)
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    engine.apply_fill(run_id, 2, 50.0, is_entry=True)
    broker.refuse = True

    result = engine.close_leg(run_id, 1, USER)

    assert result["ok"] is False


def test_a_stopped_run_records_the_pnl_its_exit_fills_actually_produced(broker):
    """Short 75 at 100, bought back at 80: the run made 1500.

    A run must stay active until this fill arrives. Finalising on broker
    acceptance writes zero before the real figure exists and discards the
    state that could have calculated it.
    """
    sid = _make()
    run_id = _start(sid).run_id
    order_events._apply_update("QA-1", _event("QA-1", avg=100.0))
    broker.clear()

    engine.stop_run(run_id, USER, reason="manual")
    exit_row = [o for o in store.list_orders(run_id) if o["kind"] != "entry"][0]
    order_events._apply_update(
        exit_row["broker_order_id"], _event(exit_row["broker_order_id"], avg=80.0)
    )

    assert store.list_runs(sid)[0]["pnl_realized"] == pytest.approx(1500.0)


def test_an_exit_fill_on_a_leg_whose_entry_never_filled_books_no_pnl(broker):
    """Leg 2's entry is still working. Its exit fills at 90.

    ``(90 - 0) * 75`` is booked as 6750 of profit the account never made. That
    figure then flows into ``run_pnl``, which is what the combined stop, the
    combined target and the lock-profit floor are judged against, so a phantom
    6750 can square off the entire remaining book.
    """
    sid, run_id = _two_leg_run(broker, positions=("S", "B"))
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)  # leg 1 filled
    # Leg 2's entry was accepted but has not filled: entry_avg is still 0.
    assert _live(run_id, 2)["entry_avg"] == 0.0
    engine.close_leg(run_id, 2, USER)

    engine.apply_fill(run_id, 2, 90.0, is_entry=False)

    assert _live(run_id, 2)["realized_pnl"] == 0.0
    assert risk_adapter.run_pnl(state.get_run_state(run_id))[0] == 0.0


def test_a_stop_while_an_entry_is_unfilled_places_nothing_and_keeps_the_run(broker):
    """A leg is open from broker acceptance, not from its fill.

    Squaring off here used to send a full-size opposite market order against a
    position that may not exist yet: if the entry were then cancelled or
    rejected, that order is itself a naked position in the other direction.
    There is no confirmed quantity to close, so nothing is closed.

    Refusing is not the same as ignoring. The run stays open and managed and
    the caller is told why, so the stop can be retried once the fill lands,
    rather than the run being finalised while a working entry is still out
    there. Cancelling the working entry would be better still, and the module
    has no cancel path to do it with.
    """
    sid = _make()
    run_id = _start(sid).run_id
    assert _live(run_id)["entry_avg"] == 0.0
    assert _live(run_id)["status"] == "open"
    broker.clear()

    result = engine.stop_run(run_id, USER, reason="manual")

    assert broker.orders == [], "nothing was sent against an unconfirmed position"
    assert result["ok"] is False
    assert result["stop_pending"] is True
    assert any("not filled" in str(exit_["error"]).lower() for exit_ in result["exits"])
    assert store.get_run(run_id).stop_requested_reason == "manual"
    assert store.get_run(run_id).stopped_at is None, "the run is still open and still managed"

    # Once the entry fills, the same stop works.
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    engine.stop_run(run_id, USER, reason="manual")
    assert broker.actions == ["BUY"]
    assert broker.quantities == [75]


def test_the_last_leg_closing_twice_finalises_the_run_only_once(broker):
    """A duplicated final exit fill must not finalise twice or restate the P&L."""
    sid = _make()
    run_id = _start(sid).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)

    first = engine.apply_fill(run_id, 1, 80.0, is_entry=False)
    stopped_at = store.get_run(run_id).stopped_at
    second = engine.apply_fill(run_id, 1, 60.0, is_entry=False)

    assert first is True
    assert second is False
    assert store.get_run(run_id).stopped_at == stopped_at
    assert store.list_runs(sid)[0]["pnl_realized"] == pytest.approx(1500.0)
    stops = [e for e in store.list_events(sid) if e["kind"] == "run_stopped"]
    assert len(stops) == 1


def test_a_tick_for_a_just_finalised_run_places_nothing(broker):
    """The feed keeps delivering for a moment after a run ends."""
    sid = _make()
    run_id = _start(sid).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    engine.stop_run(run_id, USER, reason="manual")
    exit_row = max(store.list_orders(run_id), key=lambda row: row["id"])
    order_events._apply_update(
        exit_row["broker_order_id"],
        _event(exit_row["broker_order_id"], avg=90.0),
    )
    broker.clear()

    engine.process_tick(CE, "NFO", 500.0)

    assert broker.orders == []
    assert run_id not in state.active_run_ids()


def test_close_leg_for_a_leg_id_that_does_not_exist_places_nothing(broker):
    sid, run_id = _two_leg_run(broker)
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)

    result = engine.close_leg(run_id, 99, USER)

    assert result["ok"] is False
    assert result["error"] == "That leg is not open"
    assert broker.orders == []


def test_close_leg_for_a_leg_that_has_already_closed_places_nothing(broker):
    sid, run_id = _two_leg_run(broker)
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    engine.apply_fill(run_id, 2, 50.0, is_entry=True)
    engine.close_leg(run_id, 1, USER)
    engine.apply_fill(run_id, 1, 80.0, is_entry=False)
    broker.clear()

    result = engine.close_leg(run_id, 1, USER)

    assert result["ok"] is False
    assert broker.orders == []


def test_a_leg_already_on_its_way_out_is_not_sent_a_second_exit(broker):
    """Two rules can fire on the same tick; a second exit reverses the position."""
    sid, run_id = _two_leg_run(broker)
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    engine.apply_fill(run_id, 2, 50.0, is_entry=True)
    strategy = store.strategy_to_dict(store.get_strategy(sid, USER))

    engine._exit_legs(run_id, strategy, [1], "exit_sl", "sandbox", "k", USER)
    engine._exit_legs(run_id, strategy, [1], "exit_target", "sandbox", "k", USER)

    assert len(broker.orders) == 1


def test_an_exit_whose_audit_row_could_not_be_written_still_blocks_a_second_one(broker):
    """The order reached the broker. Whether the row was written is our problem.

    ``record_order`` swallows its own failures and returns ``None``. The guard
    reads ``exit_order_id``, which is then ``None``, so the next rule to fire
    sends the same exit again and the position flips instead of closing.
    """
    sid, run_id = _two_leg_run(broker)
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    engine.apply_fill(run_id, 2, 50.0, is_entry=True)
    strategy = store.strategy_to_dict(store.get_strategy(sid, USER))

    with patch.object(engine.store, "record_order", return_value=None):
        engine._exit_legs(run_id, strategy, [1], "exit_sl", "sandbox", "k", USER)
        engine._exit_legs(run_id, strategy, [1], "exit_target", "sandbox", "k", USER)

    assert len(broker.orders) == 1


def test_a_refused_exit_can_be_retried_rather_than_looking_like_a_duplicate(broker):
    """A failed attempt that armed the guard would strand the position forever."""
    sid, run_id = _two_leg_run(broker)
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    engine.apply_fill(run_id, 2, 50.0, is_entry=True)
    strategy = store.strategy_to_dict(store.get_strategy(sid, USER))
    broker.refuse = True

    engine._exit_legs(run_id, strategy, [1], "exit_sl", "sandbox", "k", USER)
    broker.refuse = False
    engine._exit_legs(run_id, strategy, [1], "exit_sl", "sandbox", "k", USER)

    assert len(broker.orders) == 2
    assert broker.actions == ["BUY", "BUY"]


# ===========================================================================
# Signal mode
# ===========================================================================


def _signal_legs():
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
            "side": "both",
            "qty": 50,
            "segment": "cash",
            "trail": {"x": 0, "y": 0},
        },
    ]


def _signal_strategy(**overrides):
    config = {
        "name": "QA signal",
        "underlying": "MULTI",
        "underlying_exchange": "NSE",
        "universe_tab": "stocks_fno",
        "strategy_kind": "signal",
        "direction": "both",
        "strategy_type": "positional",
        "product": "MIS",
        "legs": _signal_legs(),
    }
    config.update(overrides)
    created, error = store.create_strategy(USER, config)
    assert error is None, error
    return store.get_strategy(created["id"], USER)


def _run_of(strategy):
    return store.get_strategy(strategy.id, USER).current_run_id


def test_a_repeated_exit_alert_before_the_first_fills_does_not_reverse_the_position(broker):
    """TradingView repeats. Held long 100, two long_exit alerts a second apart.

    A leg stays ``open`` until its exit fill arrives, so ``_held_side`` still
    answers long on the second alert and a second SELL 100 goes out. The account
    ends up short 100 of a stock the strategy only ever meant to be flat in.
    The engine's own ``_exit_legs`` guards exactly this; the signal path does not.
    """
    strategy = _signal_strategy()
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    engine.apply_fill(_run_of_strategy(strategy.id), 1, 100.0, is_entry=True)
    broker.clear()

    signals.handle_signal(strategy, "long_exit", leg_id=1)
    signals.handle_signal(strategy, "long_exit", leg_id=1)

    assert broker.actions == ["SELL"]
    assert broker.quantities == [100]


def test_an_exit_alert_after_the_scheduler_squared_off_places_nothing(broker):
    """The end-of-day job already sent the exit. The alert arrives after it."""
    strategy = _signal_strategy()
    signals.handle_signal(strategy, "short_entry", leg_id=1)
    run_id = store.get_strategy(strategy.id, USER).current_run_id
    engine.stop_run(run_id, USER, reason="scheduler")
    broker.clear()

    signals.handle_signal(strategy, "short_exit", leg_id=1)

    assert broker.orders == []


def test_a_refused_exit_alert_does_not_disarm_the_legs_stop_loss(broker):
    """The signal exit was refused, so the position is still held.

    ``_place`` sets ``exit_order_id`` on the leg regardless of the outcome.
    ``engine._exit_legs`` skips any leg with that field set, so from this point
    the leg's stop loss, its target and any square-off driven through the engine
    are all silently unable to place an order. The engine's own exit path clears
    the marker on failure; the signal path does not.
    """
    strategy = _signal_strategy()
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    run_id = _run_of(strategy)
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    broker.refuse = True
    signals.handle_signal(strategy, "long_exit", leg_id=1)
    broker.refuse = False
    broker.clear()

    engine.stop_run(run_id, USER, reason="manual")

    assert broker.actions == ["SELL"], "the engine could not exit a leg it still holds"


def test_a_flip_whose_closing_order_is_refused_does_not_open_the_other_side(broker):
    """Reversing without closing leaves both positions on the book."""
    strategy = _signal_strategy()
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    run_id = _run_of(strategy)
    # Filled, so there is a confirmed position for the flip to try to close.
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    broker.clear()
    broker.refuse = True

    result = signals.handle_signal(strategy, "short_entry", leg_id=1)

    assert result.ok is False
    assert broker.actions == ["SELL"], "only the refused close was attempted"
    assert _live(run_id, 1)["position"] == "B", "the leg is still held long"


def test_an_entry_alert_for_a_leg_whose_entry_was_refused_can_be_retried(broker):
    """A refused entry holds nothing, so the next alert must be free to try again."""
    strategy = _signal_strategy()
    broker.refuse = True
    first = signals.handle_signal(strategy, "long_entry", leg_id=1)
    assert first.ok is False
    run_id = _run_of(strategy)
    assert _live(run_id, 1)["status"] == "rejected"
    broker.refuse = False
    broker.clear()

    second = signals.handle_signal(strategy, "long_entry", leg_id=1)

    assert second.ok is True
    assert broker.actions == ["BUY"]
    assert _live(run_id, 1)["status"] == "open"


def test_an_exit_alert_for_a_leg_whose_entry_was_refused_places_nothing(broker):
    strategy = _signal_strategy()
    broker.refuse = True
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    broker.refuse = False
    broker.clear()

    result = signals.handle_signal(strategy, "long_exit", leg_id=1)

    assert result.ok is True
    assert result.note == "no_matching_position"
    assert broker.orders == []


def test_a_repeated_entry_alert_before_the_first_fills_does_not_double_the_position(broker):
    """The leg is open but unfilled. A repeat must still be a no-op."""
    strategy = _signal_strategy()
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    broker.clear()

    result = signals.handle_signal(strategy, "long_entry", leg_id=1)

    assert result.note == "already_long"
    assert broker.orders == []


def test_re_entering_a_signal_leg_keeps_the_pnl_of_its_earlier_round_trip(broker):
    """Long 100 at 100, out at 90: the day is down 1000.

    The next alert on the same leg wipes that figure, so the run's realized
    total goes back to zero. Every strategy-level rule, the overall stop loss
    most of all, is then judged against a day that never happened: a daily loss
    limit resets to zero on every flat moment and can never be reached.
    """
    strategy = _signal_strategy()
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    run_id = _run_of(strategy)
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    signals.handle_signal(strategy, "long_exit", leg_id=1)
    engine.apply_fill(run_id, 1, 90.0, is_entry=False)
    assert risk_adapter.run_pnl(state.get_run_state(run_id))[0] == pytest.approx(-1000.0)

    signals.handle_signal(strategy, "long_entry", leg_id=1)

    assert risk_adapter.run_pnl(state.get_run_state(run_id))[0] == pytest.approx(-1000.0)


def test_a_signal_run_survives_going_flat_so_the_day_stays_one_run(broker):
    """A round trip is a mid-session event, not the end of the session."""
    strategy = _signal_strategy()
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    run_id = _run_of(strategy)
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    signals.handle_signal(strategy, "long_exit", leg_id=1)

    went_flat = engine.apply_fill(run_id, 1, 90.0, is_entry=False)

    assert went_flat is True
    assert store.get_run(run_id).stopped_at is None
    assert _run_of(strategy) == run_id
    assert len(store.list_runs(strategy.id)) == 1


def test_an_exit_alert_on_a_flat_strategy_still_opens_a_run(broker):
    """Characterisation. ``_day_run`` runs before anything checks there is a position.

    A stale alert for a strategy that traded nothing today leaves it reading as
    ``running`` with an empty run behind it, and the end-of-day job has already
    been and gone. Harmless to the book, misleading on the dashboard.
    """
    strategy = _signal_strategy()

    result = signals.handle_signal(strategy, "long_exit", leg_id=1)

    assert result.note == "no_matching_position"
    assert broker.orders == []
    refreshed = store.get_strategy(strategy.id, USER)
    assert refreshed.status == "running"
    assert refreshed.current_run_id is not None


# ===========================================================================
# Risk evaluation
# ===========================================================================


@pytest.mark.parametrize(
    "bad_price",
    [0, 0.0, -1.0, -250.0, float("nan"), float("inf"), float("-inf"), "not a price", None],
)
def test_an_unusable_tick_moves_nothing_and_places_nothing(broker, bad_price):
    """A short at 100 with a 20 point stop.

    None of these prices may exit it, poison its favourable extreme, or become
    its last traded price. ``max(nan, x)`` is argument-order dependent, so a
    single NaN reaching the ratchet would corrupt the stop for the whole session.
    """
    sid = _make()
    run_id = _start(sid).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    engine.process_tick(CE, "NFO", 95.0)
    before = _live(run_id)
    broker.clear()

    engine.process_tick(CE, "NFO", bad_price)

    after = _live(run_id)
    assert broker.orders == []
    assert after["ltp"] == before["ltp"] == 95.0
    assert after["lowest_price"] == before["lowest_price"] == 95.0
    assert after["effective_sl"] == before["effective_sl"] == pytest.approx(120.0)


def test_a_tick_delivered_as_a_numeric_string_is_honoured(broker):
    """The REST fallback and some feeds hand prices over as text."""
    sid = _make()
    run_id = _start(sid).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    broker.clear()

    engine.process_tick(CE, "NFO", "121.0")

    assert broker.actions == ["BUY"]
    assert _live(run_id)["ltp"] == 121.0


def test_a_leg_with_no_entry_price_is_never_given_a_stop_derived_from_zero(broker):
    """A stop 20 points from an entry of zero is a stop at -20, or at +20 on a short.

    Either way it fires on the first tick and exits a position the run does not
    yet hold. The leg must simply not be evaluated until its entry price lands.
    """
    sid = _make()
    run_id = _start(sid).run_id
    assert _live(run_id)["entry_avg"] == 0.0
    broker.clear()

    engine.process_tick(CE, "NFO", 0.05)
    engine.process_tick(CE, "NFO", 100000.0)

    assert broker.orders == []
    assert _live(run_id)["effective_sl"] is None
    assert _live(run_id)["mtm"] == 0.0


def test_a_leg_with_no_entry_price_contributes_nothing_to_the_run_pnl(broker):
    """An unpriced leg must not drag the combined stop through its limit."""
    sid, run_id = _two_leg_run(broker)
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)  # short at 100
    engine.process_tick(CE, "NFO", 98.0)  # +150 on leg 1
    engine.process_tick(PE, "NFO", 4000.0)  # leg 2 has no entry price

    realized, unrealized = risk_adapter.run_pnl(state.get_run_state(run_id))

    assert realized == 0.0
    assert unrealized == pytest.approx(150.0)


def test_a_stop_and_a_target_that_both_trigger_on_one_tick_exit_once_as_a_stop(broker):
    """Within one tick the order of the two touches is unknowable.

    Assume the adverse one, and above all place exactly one order: two exits do
    not close a position twice, they open the opposite one.
    """
    sid = _make(_config(legs=[_leg(leg_id=1, position="B", sl_pts=10, target_pts=10)]))
    run_id = _start(sid).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    # Non-vacuous: both levels really are configured on the leg.
    assert _live(run_id)["sl_pts"] == 10
    assert _live(run_id)["target_pts"] == 10
    broker.clear()

    # A long at 100 with a stop at 90 and a target at 110. A single tick cannot
    # be both, so drive the stop and confirm no second order follows.
    engine.process_tick(CE, "NFO", 89.0)

    assert broker.actions == ["SELL"]
    kinds = [o["kind"] for o in store.list_orders(run_id) if o["kind"] != "entry"]
    assert kinds == ["exit_sl"]


def test_a_stop_takes_priority_over_a_target_on_the_same_tick(broker):
    """Constructed so both comparisons are true at once.

    A long whose trailing stop has ratcheted above its target: the tick is at
    or above the target and at or below the stop simultaneously.
    """
    from services.risk import PositionRisk, Side, evaluate_position

    decision = evaluate_position(
        PositionRisk(
            identifier="1",
            side=Side.BUY,
            entry_price=100.0,
            quantity=75,
            stop_price=110.0,
            target_price=105.0,
        ),
        110.0,
    )

    assert decision.breached is True
    assert decision.reason == "sl"


def test_a_price_that_gaps_through_several_trail_steps_advances_by_all_of_them(broker):
    """A gap opening is one tick, not one step.

    A short entered at 100 with a 20 point stop, trailing X=5 Y=2. The price
    gaps to 80: four completed triggers, so the stop must move 8 points to 112
    in a single evaluation rather than one step of 2.
    """
    sid = _make(_config(legs=[_leg(leg_id=1, position="S", sl_pts=20, trail={"x": 5, "y": 2})]))
    run_id = _start(sid).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    broker.clear()

    engine.process_tick(CE, "NFO", 80.0)

    leg = _live(run_id)
    assert leg["effective_sl"] == pytest.approx(112.0)
    assert leg["trail_active"] is True
    assert broker.orders == []


def test_a_trailing_stop_never_loosens_when_the_price_comes_back(broker):
    """The ratchet is the whole product. A stop that slides back gives protection away."""
    sid = _make(_config(legs=[_leg(leg_id=1, position="S", sl_pts=20, trail={"x": 5, "y": 2})]))
    run_id = _start(sid).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    engine.process_tick(CE, "NFO", 80.0)
    tightened = _live(run_id)["effective_sl"]
    broker.clear()

    engine.process_tick(CE, "NFO", 99.0)

    assert _live(run_id)["effective_sl"] == pytest.approx(tightened)
    assert broker.orders == []


def test_a_trail_that_gaps_straight_through_its_own_new_stop_exits_on_that_tick(broker):
    """Late detection is still detection.

    The stop ratchets on the same tick that runs back through it, which is what
    a violent reversal inside one tick looks like. It must fire, not be skipped
    because the level was only just set.
    """
    sid = _make(_config(legs=[_leg(leg_id=1, position="S", sl_pts=20, trail={"x": 5, "y": 5})]))
    run_id = _start(sid).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    engine.process_tick(CE, "NFO", 70.0)  # deep in profit, stop ratchets down
    stop = _live(run_id)["effective_sl"]
    broker.clear()

    engine.process_tick(CE, "NFO", stop + 1.0)

    assert broker.actions == ["BUY"]


def test_a_leg_evaluated_with_a_missing_side_raises_rather_than_guessing(broker):
    """The ported defect this module refuses: anything not "B" read as a short."""
    with pytest.raises(ValueError):
        risk_adapter.leg_to_position_risk({"leg_id": 1, "position": None, "entry_avg": 100.0})
    with pytest.raises(ValueError):
        risk_adapter.leg_to_position_risk({"leg_id": 1, "position": "LONG", "entry_avg": 100.0})


# ===========================================================================
# Recovery
# ===========================================================================


def _bare_run(strategy_id):
    run = store.create_run(strategy_id, "sandbox", "sandbox")
    assert run is not None
    store.set_strategy_status(strategy_id, "running", run.id)
    return run.id


def _order_row(run_id, leg_id, kind, action, symbol, qty, status, avg=None):
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


def test_a_checkpoint_cannot_talk_a_rejected_exit_into_a_closed_leg(broker):
    """The broker refused the exit, so the position is still held.

    A checkpoint written while the exit looked live must not close the leg:
    reading it as closed abandons a real position with no stop.
    """
    sid = _make()
    run_id = _bare_run(sid)
    _order_row(run_id, 1, "entry", "SELL", CE, 75, "complete", avg=100.0)
    _order_row(run_id, 1, "exit_sl", "BUY", CE, 75, "rejected")
    store.write_checkpoint(
        run_id,
        {
            "pnl_realized": 0.0,
            "leg_state": {
                "1": {
                    "leg_id": 1,
                    "position": "S",
                    "symbol": CE,
                    "exchange": "NFO",
                    "qty": 75,
                    "status": "closed",
                    "entry_avg": 100.0,
                    "exit_avg": 80.0,
                    "sl_pts": 20,
                }
            },
        },
    )

    result = recovery.recover_run(run_id)

    assert result.ok is True
    leg = _live(run_id)
    assert leg["status"] == "open"
    assert leg["exit_order_id"] is None, "a refused exit must stay retryable"
    assert leg["exit_kind"] is None


def test_a_checkpoint_cannot_revive_a_rejected_entry(broker):
    """A rejection is a fact. The account never held this."""
    sid = _make(_config(legs=[_leg(leg_id=1), _leg(leg_id=2)]))
    run_id = _bare_run(sid)
    _order_row(run_id, 1, "entry", "SELL", CE, 75, "rejected")
    _order_row(run_id, 2, "entry", "SELL", PE, 75, "complete", avg=50.0)
    store.write_checkpoint(
        run_id,
        {
            "leg_state": {
                "1": {
                    "leg_id": 1,
                    "position": "S",
                    "symbol": CE,
                    "exchange": "NFO",
                    "qty": 75,
                    "status": "open",
                    "entry_avg": 100.0,
                    "entry_status": "complete",
                }
            }
        },
    )

    result = recovery.recover_run(run_id)

    assert result.ok is True
    assert _live(run_id, 1)["status"] == "rejected"
    assert _live(run_id, 1)["entry_avg"] == 0.0
    assert _live(run_id, 2)["status"] == "open"


def test_a_checkpoint_leg_the_configuration_no_longer_has_is_still_recovered(broker):
    """The operator edited the strategy while a run was open.

    The position is at the broker whatever the configuration now says, so the
    leg has to come back and be managed.
    """
    sid = _make()  # one configured leg, id 1
    run_id = _bare_run(sid)
    _order_row(run_id, 1, "entry", "SELL", CE, 75, "complete", avg=100.0)
    store.write_checkpoint(
        run_id,
        {
            "leg_state": {
                "1": {
                    "leg_id": 1,
                    "position": "S",
                    "symbol": CE,
                    "exchange": "NFO",
                    "qty": 75,
                    "status": "open",
                    "entry_avg": 100.0,
                    "sl_pts": 20,
                },
                "9": {
                    "leg_id": 9,
                    "position": "B",
                    "symbol": PE,
                    "exchange": "NFO",
                    "qty": 75,
                    "status": "open",
                    "entry_status": "complete",
                    "entry_avg": 50.0,
                    "sl_pts": 15,
                },
            }
        },
    )

    result = recovery.recover_run(run_id)

    assert result.ok is True
    ghost = _live(run_id, 9)
    assert ghost["status"] == "open"
    assert ghost["position"] == "B"
    assert ghost["entry_avg"] == 50.0
    assert ghost["sl_pts"] == 15
    assert (PE, "NFO") in result.symbols


def test_a_run_with_no_orders_and_no_checkpoint_is_closed_not_resumed(broker):
    """Characterisation, and a hazard worth naming.

    A run row with nothing under it is closed as "recovered flat" with the
    message "every leg had already closed". If the process died between opening
    the run and writing its first order row, that claim is false and a real
    position is abandoned. Nothing distinguishes the two cases.
    """
    sid = _make()
    run_id = _bare_run(sid)

    result = recovery.recover_run(run_id)

    assert result.ok is False
    assert result.finalised is True
    assert store.get_run(run_id).stopped_at is not None
    assert store.get_strategy(sid, USER).status == "stopped"


def test_a_leg_whose_entry_is_still_working_comes_back_priced_but_not_open(broker):
    """It holds nothing yet, so no rule may exit it, but its fill must be priced."""
    sid = _make()
    run_id = _bare_run(sid)
    _order_row(run_id, 1, "entry", "SELL", CE, 75, "open")

    result = recovery.recover_run(run_id)

    assert result.ok is True
    assert result.open_legs == 0
    assert (CE, "NFO") in result.symbols
    assert _live(run_id)["status"] == "configured"


def test_recovery_is_idempotent_against_a_run_that_is_already_live(broker):
    """A second boot pass, or one racing a normal start, must not overwrite state."""
    sid = _make()
    run_id = _start(sid).run_id
    engine.apply_fill(run_id, 1, 137.5, is_entry=True)

    result = recovery.recover_run(run_id)

    assert result.ok is True
    assert _live(run_id)["entry_avg"] == 137.5


def test_an_unrecognised_broker_status_is_read_as_still_working(broker):
    """Reading an unknown exit as dead lets a second exit be placed."""
    assert recovery.normalise_order_status("SOMETHING_NEW") == "open"
    assert recovery.order_is_working("SOMETHING_NEW") is True
    assert recovery.order_is_dead("SOMETHING_NEW") is False


# ===========================================================================
# State
# ===========================================================================


def test_two_threads_filling_different_legs_both_reach_the_run_total(broker):
    """The run total is recomputed under the lock from every leg, not accumulated.

    An accumulating total would lose one of these fills entirely, and the run
    would be judged against a number missing a whole trade.
    """
    sid = _make(
        _config(
            legs=[
                _leg(leg_id=1, position="S"),
                _leg(leg_id=2, position="S"),
                _leg(leg_id=3, position="S"),
            ]
        )
    )
    run_id = _start(
        sid,
        resolved=[
            _resolved(symbol="L1"),
            _resolved(symbol="L2"),
            _resolved(symbol="L3"),
        ],
    ).run_id
    for leg_id in (1, 2, 3):
        engine.apply_fill(run_id, leg_id, 100.0, is_entry=True)

    barrier = threading.Barrier(2)

    def exit_leg(leg_id, price):
        barrier.wait()
        engine.apply_fill(run_id, leg_id, price, is_entry=False)

    threads = [
        threading.Thread(target=exit_leg, args=(1, 80.0)),
        threading.Thread(target=exit_leg, args=(2, 90.0)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    snapshot = state.get_run_state(run_id)
    expected = (100.0 - 80.0) * 75 + (100.0 - 90.0) * 75
    assert snapshot["pnl_realized"] == pytest.approx(expected)
    assert snapshot["legs"]["3"]["status"] == "open"


def test_a_leg_id_addressed_as_an_int_and_as_a_string_is_the_same_leg(broker):
    """The state dict is keyed by string; the HTTP route hands over a string and
    the order row hands over an int. Both must reach the one leg."""
    sid, run_id = _two_leg_run(broker)

    engine.apply_fill(run_id, "1", 100.0, is_entry=True)
    assert _live(run_id, 1)["entry_avg"] == 100.0

    engine.apply_fill(run_id, 2, 50.0, is_entry=True)
    broker.clear()

    result = engine.close_leg(run_id, "2", USER)  # a string, as the URL delivers it

    assert result["ok"] is True
    assert broker.quantities == [75]
    assert store.list_orders(run_id)[-1]["leg_id"] == 2


def test_clearing_a_runs_state_drops_its_lock_too(broker):
    """A lock left behind is a per-run leak in a worker that never restarts."""
    sid = _make()
    run_id = _start(sid).run_id
    assert state._lock_for(run_id, create=False) is not None

    state.clear_run_state(run_id)

    assert state._lock_for(run_id, create=False) is None
    assert state.get_run_state(run_id) is None


def test_reading_the_state_of_a_run_that_never_existed_registers_nothing(broker):
    """A stale websocket or a retried request must not grow the registry."""
    before = len(state._state_locks)

    assert state.get_run_state(9_999_999) is None
    with state.run_state(9_999_998) as run:
        assert run is None

    assert len(state._state_locks) == before


def test_a_leg_with_an_unusable_side_is_refused_rather_than_defaulted(broker):
    """A silent "B" is the ported defect that evaluated shorts upside down."""
    with pytest.raises(ValueError):
        state._new_leg_state(
            {"leg_id": 1, "position": "", "symbol": CE, "exchange": "NFO", "quantity": 75}
        )


def test_a_broker_that_fills_inside_the_dispatch_call_still_seeds_the_leg():
    """The sandbox, exactly: a MARKET order is filled before dispatch returns.

    _place_entries dispatches and only then records the order row, so the fill
    is published while nothing carries that broker id. Keyed on broker id
    alone the update reads as another surface's order and is dropped, and the
    leg keeps entry_avg 0.0 for the rest of the run: stop_from_points refuses a
    non-positive entry, so there is no stop, no target and no mark to market,
    while the page shows the leg as open. Every sandbox run behaved this way,
    which is the mode an operator tries first.

    Nothing caught it because every other test either calls apply_fill directly
    or delivers the update after the row exists. This one drives the order of
    events the sandbox actually produces.
    """
    sid = _make()
    filled = []

    def fills_immediately(**_kwargs):
        broker_id = f"SBX-{len(filled) + 1}"
        filled.append(broker_id)
        # The sandbox executes and publishes from inside place_order, so the
        # update is dispatched here, before dispatch_order has even returned.
        # Through _on_order_update rather than _apply_update, because that is
        # what the bus calls: it hands the work to the pool, so the update runs
        # on another thread exactly as it does in production.
        order_events._on_order_update(_event(broker_id, avg=101.5, filled=75))
        return DispatchResult(ok=True, broker_order_id=broker_id, response={})

    with (
        patch.object(engine, "resolve_leg", side_effect=[_resolved()] * 6),
        patch.object(engine, "_broker_for", return_value="sandbox"),
        patch.object(engine.order_dispatch, "dispatch_order", side_effect=fills_immediately),
    ):
        run_id = engine.start_run(sid, USER, "sandbox").run_id

    # The pool thread may still be working; the fill is asynchronous by design.
    deadline = time.time() + 10
    while time.time() < deadline and _live(run_id)["entry_avg"] != 101.5:
        time.sleep(0.02)

    leg = _live(run_id)
    assert leg["entry_avg"] == 101.5, "the fill published during dispatch was applied"
    assert leg["entry_status"] == "complete"

    row = store.list_orders(run_id)[0]
    assert row["status"] == "complete"
    assert row["avg_fill_price"] == 101.5

    # And the consequence that matters: the leg is now managed.
    engine.process_tick(CE, "NFO", 101.5)
    assert _live(run_id)["effective_sl"] is not None, "a seeded leg has a stop"


def test_the_order_row_exists_before_the_broker_is_called():
    """Durable intent first, dispatch second.

    The row used to be written from the dispatch result, so the window between
    broker acceptance and the insert held a real position that nothing
    recorded: invisible to the operator, to restart recovery, and to every
    later exit. A crash or a database failure in that window loses the
    position entirely. The in-memory replay cache added for fast fills does not
    help here, because it is in memory.
    """
    sid = _make()
    seen_at_dispatch = []

    def records_what_exists(**kwargs):
        order = kwargs["order"]
        rows = [
            o for o in store.list_orders(_run_of_strategy(sid)) if o["symbol"] == order["symbol"]
        ]
        seen_at_dispatch.append([(o["status"], o["broker_order_id"]) for o in rows])
        return DispatchResult(ok=True, broker_order_id="BRK-AFTER", response={})

    with (
        patch.object(engine, "resolve_leg", side_effect=[_resolved()] * 6),
        patch.object(engine, "_broker_for", return_value="sandbox"),
        patch.object(engine.order_dispatch, "dispatch_order", side_effect=records_what_exists),
    ):
        run_id = engine.start_run(sid, USER, "sandbox").run_id

    assert seen_at_dispatch == [[("pending", None)]], (
        "the intent was durable, and carried no broker id yet, when the broker was called"
    )

    final = store.list_orders(run_id)[0]
    assert final["status"] == "open"
    assert final["broker_order_id"] == "BRK-AFTER"


def test_an_entry_whose_row_cannot_be_written_is_never_placed(broker):
    """Refusing costs one leg. Placing it blind costs an unmanaged position.

    An order the module cannot record is one it cannot manage: no stop is
    evaluated for it, no square-off finds it, and no operator can see it. The
    exit path takes the opposite decision on purpose.
    """
    sid = _make()

    with (
        patch.object(engine, "resolve_leg", side_effect=[_resolved()] * 6),
        patch.object(engine, "_broker_for", return_value="sandbox"),
        patch.object(store, "record_order", return_value=None),
    ):
        result = engine.start_run(sid, USER, "sandbox")

    assert broker.orders == [], "nothing reached the broker"
    assert result.ok is False or all(not o["ok"] for o in (result.legs or [])), (
        "the leg reports the refusal rather than a placed order"
    )
    kinds = [e["kind"] for e in store.list_events(sid)]
    assert "leg_entry_rejected" in kinds


def _run_of_strategy(sid):
    row = store.get_strategy(sid, USER)
    return row.current_run_id


def test_an_exit_rejected_after_dispatch_can_be_retried(broker):
    """The broker took the exit, then rejected it a moment later.

    The synchronous refusal path releases the leg's claim so a later stop,
    stop loss or square-off can reach it. Nothing did that for a rejection
    arriving on the order stream afterwards, so the leg kept an exit that was
    never going to fill, and every later attempt passed over a position the
    broker still held. For the rest of the session.
    """
    # Two legs, so the run stays live after one of them is exited by its stop.
    sid = _make(_config(legs=[_leg(leg_id=1, position="S"), _leg(leg_id=2, position="S")]))
    run_id = _start(sid, resolved=[_resolved(symbol=CE), _resolved(symbol=PE)]).run_id
    order_events._apply_update("QA-1", _event("QA-1", avg=100.0))
    order_events._apply_update("QA-2", _event("QA-2", avg=100.0))
    broker.clear()

    # Leg 1's stop fires and its exit is accepted.
    engine.process_tick(CE, "NFO", 500.0)
    exit_order = [o for o in store.list_orders(run_id) if o["kind"] != "entry"][0]
    assert broker.actions == ["BUY"]
    broker.clear()

    # The broker then rejects it.
    order_events._apply_update(
        exit_order["broker_order_id"],
        _event(exit_order["broker_order_id"], status="rejected", avg=0, filled=0),
    )

    # The position is still held, so the next tick must try again.
    engine.process_tick(CE, "NFO", 500.0)
    assert broker.actions == ["BUY"], "the leg was exitable again"


def test_an_entry_rejected_after_dispatch_is_not_squared_off(broker):
    """The mirror case: an entry that dies later is not a position.

    Left marked open, the next square-off sends a full-size order against
    nothing, which is a naked position in the other direction.
    """
    sid = _make()
    run_id = _start(sid).run_id
    broker.clear()

    order_events._apply_update("QA-1", _event("QA-1", status="rejected", avg=0, filled=0))

    assert _live(run_id)["status"] == "rejected"
    engine.stop_run(run_id, USER, reason="manual")
    assert broker.orders == [], "nothing was sent for a leg that never traded"


def test_an_exit_rejected_after_stop_acceptance_is_reported_as_managed(broker):
    """A delayed rejection keeps the pending stop open and retryable."""
    sid = _make()
    run_id = _start(sid).run_id
    order_events._apply_update("QA-1", _event("QA-1", avg=100.0))
    engine.stop_run(run_id, USER, reason="manual")
    exit_order = [o for o in store.list_orders(run_id) if o["kind"] != "entry"][0]

    order_events._apply_update(
        exit_order["broker_order_id"],
        _event(exit_order["broker_order_id"], status="rejected", avg=0, filled=0),
    )

    stranded = [e for e in store.list_events(sid) if e["kind"] == "run_stop_failed"]
    assert stranded, "the held position was recorded"
    assert stranded[0]["severity"] == "critical"
    assert "managed" in stranded[0]["message"]
    assert "retryable" in stranded[0]["message"]
    assert store.get_run(run_id).stopped_at is None
    assert state.get_run_state(run_id) is not None
