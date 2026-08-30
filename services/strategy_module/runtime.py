"""Starts the strategy module, in the order the pieces need.

One call from ``app.py``. Everything the module runs in the background is
started here and nowhere else, so nothing begins listening merely because
something imported it.

The order is not arbitrary:

1. **Order updates first.** Recovery reconciles order rows, and a fill arriving
   while it runs should be applied rather than missed. Subscribing first means
   the window where a fill can fall between the two is closed.
2. **Recovery next**, before any price arrives. It rebuilds the live state of
   every run that was open when the process died, and tells us what each still
   needs prices for.
3. **The price hook, then the subscriptions.** The hook is what drives risk
   evaluation, so it is registered before any symbol is subscribed. Registering
   it after would leave a gap in which prices arrive and nothing judges them.
4. **Checkpointing**, once there is state worth snapshotting.
5. **The scheduler last.** It can start new runs, and it should not do that
   until recovery has finished deciding what is already running.

Every step is independently guarded. A module that fails to start is logged and
skipped rather than taking the app down with it: a platform that will not boot
because its strategy scheduler could not start is worse than one that boots
without it.
"""

from __future__ import annotations

from utils.logging import get_logger

logger = get_logger(__name__)

_started = False


def start_strategy_module() -> dict[str, bool]:
    """Bring the module up. Idempotent. Returns what actually started."""
    global _started
    if _started:
        return {}
    _started = True

    result: dict[str, bool] = {}

    result["order_events"] = _guard("order updates", _start_order_events)
    recovered = _recover()
    result["recovery"] = recovered is not None
    result["tick_feed"] = _guard("price feed", lambda: _start_tick_feed(recovered or {}))
    result["checkpoint"] = _guard("checkpointing", _start_checkpoint)
    result["scheduler"] = _guard("scheduler", _start_scheduler)

    logger.info("Strategy module started: %s", result)
    return result


def _guard(what: str, fn) -> bool:
    try:
        fn()
        return True
    except Exception:
        logger.exception("Strategy module: could not start %s", what)
        return False


def _start_order_events() -> None:
    from services.strategy_module import order_events

    order_events.start()


def _recover() -> dict | None:
    """Rebuild every run that was live when the process stopped."""
    try:
        from services.strategy_module import recovery

        symbols_by_run = recovery.recover_all()
        if symbols_by_run:
            logger.info("Strategy module recovered %d run(s)", len(symbols_by_run))
        return symbols_by_run
    except Exception:
        logger.exception("Strategy module: recovery failed")
        return None


def _start_tick_feed(symbols_by_run: dict) -> None:
    """Register the risk hook, then resubscribe what recovery brought back."""
    from services.strategy_module import engine
    from services.strategy_module.tick_feed import get_risk_tick_feed

    feed = get_risk_tick_feed()
    # This is the wire that makes the module react to the market. Both the
    # websocket and the REST fallback go through it, so a leg on the fallback
    # is evaluated on polled prices rather than merely displayed.
    feed.set_on_price(engine.process_tick)

    for run_id, symbols in (symbols_by_run or {}).items():
        try:
            feed.add_run_subscriptions(run_id, list(symbols))
        except Exception:
            logger.exception("Could not resubscribe prices for recovered run %s", run_id)


def _start_checkpoint() -> None:
    from services.strategy_module import checkpoint

    checkpoint.start()


def _start_scheduler() -> None:
    from services.strategy_module import scheduler

    scheduler.start()
    scheduler.sync_all_jobs()


def stop_strategy_module() -> None:
    """Stop the background pieces. For shutdown and for tests."""
    global _started
    for what, fn in (
        ("checkpointing", _stop_checkpoint),
        ("scheduler", _stop_scheduler),
        ("price feed", _stop_tick_feed),
    ):
        try:
            fn()
        except Exception:
            logger.exception("Strategy module: could not stop %s", what)
    _started = False


def _stop_checkpoint() -> None:
    from services.strategy_module import checkpoint

    checkpoint.stop()


def _stop_scheduler() -> None:
    from services.strategy_module import scheduler

    scheduler.shutdown()


def _stop_tick_feed() -> None:
    from services.strategy_module.tick_feed import get_risk_tick_feed

    get_risk_tick_feed().stop()
