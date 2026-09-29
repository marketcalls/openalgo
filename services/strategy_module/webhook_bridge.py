"""Adapts the engine to the shape the webhook handler expects.

The two modules were built to different signatures on purpose. The webhook
handler takes a strategy row, because that is what its token lookup produces
and what every one of its validation stages already needs. The engine takes
ids, because it is also driven by the UI and the scheduler, which have a user
in scope and no row in hand.

Rather than bend either to the other, this translates. It is the only place
that knows both shapes, so a change to one is a change to one file.

It also decides which run a webhook ``stop`` applies to: the strategy's current
run. The webhook never names a run, and it should not have to.
"""

from __future__ import annotations

from typing import Any

from services.strategy_module.webhook import EngineResult
from utils.logging import get_logger

logger = get_logger(__name__)


def start_run(
    strategy: Any,
    mode: str,
    *,
    trigger_source: str = "webhook",
    webhook_event_id: int | None = None,
) -> EngineResult:
    """Start a run for a strategy the webhook has already validated."""
    from services.strategy_module import engine

    result = engine.start_run(
        strategy.id,
        strategy.user_id,
        mode,
        trigger_source=trigger_source,
        webhook_event_id=webhook_event_id,
    )
    return EngineResult(ok=result.ok, run_id=result.run_id, error=result.error)


def stop_run(
    strategy: Any,
    *,
    stop_reason: str = "manual",
    trigger_source: str = "webhook",
    webhook_event_id: int | None = None,
) -> EngineResult:
    """Stop whichever run the strategy currently holds.

    A stop for a strategy that is already flat is a success, not a failure. The
    sender asked for it to be stopped and it is stopped; answering with an error
    would make a duplicate alert look like a fault worth retrying.
    """
    from services.strategy_module import engine

    run_id = getattr(strategy, "current_run_id", None)
    if not run_id:
        return EngineResult(ok=True, run_id=None)

    result = engine.stop_run(run_id, strategy.user_id, reason=stop_reason)
    return EngineResult(
        ok=bool(result.get("ok")),
        run_id=run_id,
        error=result.get("error"),
        stop_pending=(bool(result.get("stop_pending")) if "stop_pending" in result else None),
        exits=list(result.get("exits") or []),
    )
