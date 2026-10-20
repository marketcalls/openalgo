"""Repair broker acknowledgements preserved in append-only strategy events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from database import strategy_module_db as store
from services.strategy_module import order_dispatch, order_events
from utils.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class AckRepairSummary:
    total: int = 0
    repaired: int = 0
    already_bound: int = 0
    unresolved: int = 0
    unresolved_exposure: int = 0
    working_broker_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OpenRunAckRepairSummary:
    examined: int = 0
    repaired: int = 0
    already_bound: int = 0
    unresolved: int = 0
    polled: int = 0
    folded: int = 0
    failed: int = 0


# The existing shared APScheduler job calls this module every five seconds.
# Page through ordinary open runs rather than scanning all of them or creating
# a timer/thread per run. APScheduler's max_instances=1 makes this cursor's
# access serial, and a process restart safely begins the idempotent sweep at 0.
OPEN_RUN_REPAIR_BATCH = 50
BROKER_STATUS_POLL_BATCH = 50
_open_run_cursor = 0

_WORKING_STATUSES = frozenset(
    {"pending", "open", "working", "trigger pending", "trigger_pending"}
)


def _whole(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def reconcile(run_id: int, *, replay_updates: bool = True) -> AckRepairSummary:
    """Bind every exact lost-ack witness without guessing order ownership.

    Events from the older, message-only format are deliberately unresolved:
    that event was emitted only for an accepted order, so treating it as flat
    would discard possible exposure. Structured rejected events, by contrast,
    can terminally repair their exact pending row even without a broker id.
    """
    events = store.list_order_ack_events(run_id)
    if events is None:
        return AckRepairSummary(unresolved=1, unresolved_exposure=1)
    repaired = already_bound = unresolved = unresolved_exposure = 0
    working_broker_ids: list[str] = []

    for event in events:
        payload = event.get("payload")
        valid = isinstance(payload, dict) and payload.get("version") == 1
        order_id = _whole(payload.get("order_id")) if isinstance(payload, dict) else None
        payload_run_id = _whole(payload.get("run_id")) if isinstance(payload, dict) else None
        payload_leg_id = _whole(payload.get("leg_id")) if isinstance(payload, dict) else None
        event_leg_id = _whole(event.get("leg_id"))
        accepted = payload.get("accepted") if isinstance(payload, dict) else None
        status = payload.get("status") if isinstance(payload, dict) else None
        broker_order_id = payload.get("broker_order_id") if isinstance(payload, dict) else None
        reject_reason = payload.get("reject_reason") if isinstance(payload, dict) else None

        valid = bool(
            valid
            and order_id is not None
            and payload_run_id == run_id
            and payload_leg_id is not None
            and event_leg_id == payload_leg_id
            and isinstance(accepted, bool)
            and status == ("open" if accepted else "rejected")
            and (broker_order_id is None or isinstance(broker_order_id, str))
            and (reject_reason is None or isinstance(reject_reason, str))
            and (not accepted or bool(str(broker_order_id or "").strip()))
        )
        if not valid:
            unresolved += 1
            # Message-only legacy events were emitted only on acceptance. A
            # malformed structured witness cannot prove exact rejected-row
            # ownership either, so it must also keep the run reserved.
            unresolved_exposure += 1
            continue

        outcome = store.bind_order_acknowledgement(
            order_id,
            run_id,
            payload_leg_id,
            broker_order_id=broker_order_id,
            status=status,
            reject_reason=reject_reason,
        )
        if outcome == "repaired":
            repaired += 1
            if accepted and broker_order_id and replay_updates:
                # A synchronous fill that arrived before the id became
                # attributable may still be waiting in the short-lived replay
                # cache. Fold it before recovery snapshots durable orders.
                order_events.replay_for(broker_order_id)
        elif outcome == "already_bound":
            already_bound += 1
        else:
            unresolved += 1
            unresolved_exposure += 1
            logger.critical(
                "Lost acknowledgement event %s could not bind exact order row %s on run %s: %s",
                event.get("id"),
                order_id,
                run_id,
                outcome,
            )

        if outcome in {"repaired", "already_bound"} and accepted and broker_order_id:
            # Reload after replay: a cached terminal frame must not trigger a
            # redundant broker poll. The exact row/event linkage is checked a
            # second time before exposing the id to the periodic status fold.
            row = store.get_order(order_id)
            row_broker_id = str(row.broker_order_id).strip() if row and row.broker_order_id else None
            row_status = str(row.status or "pending").strip().lower() if row else ""
            if (
                row is not None
                and int(row.run_id) == run_id
                and int(row.leg_id) == payload_leg_id
                and row_broker_id == broker_order_id
                and row_status in _WORKING_STATUSES
                and broker_order_id not in working_broker_ids
            ):
                working_broker_ids.append(broker_order_id)

    return AckRepairSummary(
        total=len(events),
        repaired=repaired,
        already_bound=already_bound,
        unresolved=unresolved,
        unresolved_exposure=unresolved_exposure,
        working_broker_ids=tuple(working_broker_ids),
    )


def _api_key_for(user_id: str) -> str | None:
    """Read the owner's API key without importing the engine circularly."""
    try:
        from database.auth_db import get_api_key_for_tradingview

        return get_api_key_for_tradingview(user_id)
    except Exception:
        logger.exception("Could not read the API key for acknowledgement repair")
        return None


def _next_open_run_ids(limit: int) -> list[int]:
    global _open_run_cursor

    run_ids = store.list_open_run_ids_after(_open_run_cursor, limit)
    if not run_ids and _open_run_cursor:
        _open_run_cursor = 0
        run_ids = store.list_open_run_ids_after(0, limit)
    if run_ids:
        _open_run_cursor = run_ids[-1]
    return run_ids


def reconcile_open_runs(
    *,
    run_limit: int = OPEN_RUN_REPAIR_BATCH,
    status_poll_limit: int = BROKER_STATUS_POLL_BATCH,
) -> OpenRunAckRepairSummary:
    """Repair a bounded rotating page of ordinary open runs.

    Accepted rows are first made attributable by their exact structured event.
    A cached push frame is replayed immediately. If that frame has expired or
    never arrived, at most ``status_poll_limit`` broker facts are read and
    folded through the normal order-event path. No lock is held across broker
    I/O, and the shared APScheduler job supplies the existing execution lane.
    """
    bounded_runs = max(0, min(int(run_limit), OPEN_RUN_REPAIR_BATCH))
    bounded_polls = max(0, min(int(status_poll_limit), BROKER_STATUS_POLL_BATCH))
    if bounded_runs == 0:
        return OpenRunAckRepairSummary()

    run_ids = _next_open_run_ids(bounded_runs)
    repaired = already_bound = unresolved = polled = folded = failed = 0

    for run_id in run_ids:
        try:
            repair = reconcile(run_id)
        except Exception:
            logger.exception("Acknowledgement repair failed for open run %s", run_id)
            failed += 1
            continue

        repaired += repair.repaired
        already_bound += repair.already_bound
        unresolved += repair.unresolved
        if not repair.working_broker_ids or polled >= bounded_polls:
            continue

        run = store.get_run(run_id)
        strategy = store.get_strategy_unscoped(run.strategy_id) if run is not None else None
        api_key = _api_key_for(str(strategy.user_id)) if strategy is not None else None
        if run is None or strategy is None or not api_key:
            failed += 1
            continue

        for broker_order_id in repair.working_broker_ids:
            if polled >= bounded_polls:
                break
            polled += 1
            try:
                status = order_dispatch.fetch_order_status(
                    mode=str(run.mode),
                    api_key=api_key,
                    broker_order_id=broker_order_id,
                )
                if status.ok and status.order is not None:
                    order_events.apply_order_snapshot(broker_order_id, status.order)
                    folded += 1
                else:
                    failed += 1
            except Exception:
                logger.exception(
                    "Broker status fold failed for acknowledgement %s on run %s",
                    broker_order_id,
                    run_id,
                )
                failed += 1

    return OpenRunAckRepairSummary(
        examined=len(run_ids),
        repaired=repaired,
        already_bound=already_bound,
        unresolved=unresolved,
        polled=polled,
        folded=folded,
        failed=failed,
    )
