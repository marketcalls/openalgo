"""Two signal alerts that open the day's run at the same moment.

TradingView fires long_entry for one leg and long_entry for its partner on the
same bar close. Neither finds a run for the day, so both try to open one. The
conditional UPDATE in ``claim_strategy_for_run`` lets one of them win, and the
other used to read the strategy back before the winner had linked the run,
answer "This strategy is already running" and never place its leg.

Under eventlet ``_day_run`` never yielded between the claim and the link, so
the loser always found the finished run. Under the gthread worker the two
requests run in parallel. ``_day_run`` is now serialised per strategy, and the
run state exists before the strategy row names the run.
"""

import threading
from unittest.mock import patch

import pytest

# restx_api first: see the note in test_strategy_module_order_dispatch.py.
import restx_api  # noqa: F401
from database import strategy_module_db as store
from services.strategy_module import engine, signals, state
from services.strategy_module.order_dispatch import DispatchResult

USER = "gthread_signal_user"

_SEED_ROWS = [("RELIANCE", "NSE"), ("SBIN", "NSE")]


@pytest.fixture(scope="module", autouse=True)
def seed_master_contract():
    """Seed the traded symbols, then remove exactly what was seeded."""
    from database.symbol import SymToken, db_session, init_db

    init_db()
    inserted = []
    for symbol, exchange in _SEED_ROWS:
        if SymToken.query.filter_by(symbol=symbol, exchange=exchange).first() is not None:
            continue
        db_session.add(
            SymToken(
                symbol=symbol,
                brsymbol=symbol,
                name=symbol,
                exchange=exchange,
                brexchange=exchange,
                token=symbol,
                expiry="",
                strike=-1.0,
                lotsize=1,
                instrumenttype="EQ",
                tick_size=0.05,
            )
        )
        inserted.append((symbol, exchange))
    db_session.commit()
    yield
    for symbol, exchange in inserted:
        SymToken.query.filter_by(symbol=symbol, exchange=exchange).delete()
    db_session.commit()
    db_session.remove()


@pytest.fixture(autouse=True)
def clean_slate():
    store.db_session.remove()
    store.init_db()

    def purge():
        for row in store.list_strategies(USER):
            for run in store.list_runs(row["id"]):
                state.clear_run_state(run["id"])
            store.set_strategy_status(row["id"], "stopped", None)
            store.delete_strategy(row["id"], USER)
        store.clear_strategy_module_cache()

    purge()
    yield
    purge()


@pytest.fixture
def placed():
    seen = []
    seen_lock = threading.Lock()

    def record(**kwargs):
        with seen_lock:
            seen.append(kwargs["order"])
            number = len(seen)
        return DispatchResult(ok=True, broker_order_id=f"GT-SB-{number}", response={})

    with (
        patch.object(signals.order_dispatch, "dispatch_order", side_effect=record),
        patch.object(signals, "_api_key_for", return_value="test-key"),
        patch.object(engine.order_dispatch, "dispatch_order", side_effect=record),
        patch.object(engine, "_api_key_for", return_value="test-key"),
        patch.object(engine, "_subscribe_run"),
        patch.object(engine, "_unsubscribe_run"),
    ):
        yield seen


def _make():
    created, error = store.create_strategy(
        USER,
        {
            "name": "gthread signal pair",
            "underlying": "MULTI",
            "underlying_exchange": "NSE",
            "universe_tab": "stocks_fno",
            "strategy_kind": "signal",
            "direction": "both",
            "strategy_type": "positional",
            "product": "MIS",
            "legs": [
                {
                    "id": 1,
                    "symbol": "RELIANCE",
                    "exchange": "NSE",
                    "side": "both",
                    "qty": 100,
                    "segment": "cash",
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
            ],
        },
    )
    assert error is None, error
    return store.get_strategy(created["id"], USER)


def test_two_first_signals_of_the_day_both_enter(placed):
    """The winner of the claim is held until the loser has read the strategy
    back (or one second has passed, which is what happens once the day-run is
    serialised and the loser cannot get that far until the winner is done)."""
    strategy = _make()
    strategy_id = strategy.id

    real_claim = store.claim_strategy_for_run
    real_read = store.get_strategy_unscoped
    claimed_by: dict[int, bool] = {}
    loser_read = threading.Event()

    def claim(target_id):
        won = real_claim(target_id)
        claimed_by[threading.get_ident()] = won
        if won:
            loser_read.wait(1.0)
        return won

    def read(target_id):
        row = real_read(target_id)
        if claimed_by.get(threading.get_ident()) is False:
            loser_read.set()
        return row

    # Plain snapshots: each request thread has its own session.
    snapshot_a = signals._snapshot_strategy(strategy)
    snapshot_b = signals._snapshot_strategy(strategy)
    store.db_session.remove()
    results = {}
    start = threading.Barrier(2)

    def fire(name, snapshot, leg_id):
        try:
            start.wait()
            results[name] = signals.handle_signal(snapshot, "long_entry", leg_id=leg_id)
        finally:
            store.db_session.remove()

    with (
        patch.object(store, "claim_strategy_for_run", side_effect=claim),
        patch.object(store, "get_strategy_unscoped", side_effect=read),
    ):
        threads = [
            threading.Thread(target=fire, args=("leg1", snapshot_a, 1)),
            threading.Thread(target=fire, args=("leg2", snapshot_b, 2)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)

    assert results["leg1"].ok, results["leg1"]
    assert results["leg2"].ok, results["leg2"]
    assert results["leg1"].run_id == results["leg2"].run_id
    assert sorted(order["symbol"] for order in placed) == ["RELIANCE", "SBIN"]
    runs = store.list_runs(strategy_id)
    assert len(runs) == 1


def test_a_run_that_cannot_be_linked_leaves_no_state_behind(placed):
    """State now exists before the link, so a failed link must take it away."""
    strategy = _make()
    before = set(state.active_run_ids())

    with patch.object(store, "set_strategy_status", return_value=False):
        result = signals.handle_signal(strategy, "long_entry", leg_id=1)

    assert result.ok is False
    assert set(state.active_run_ids()) == before
    assert placed == []


def test_the_day_run_registry_empties_once_the_run_is_open(placed):
    strategy = _make()

    assert signals.handle_signal(strategy, "long_entry", leg_id=1).ok

    assert len(signals._day_run_locks) == 0
