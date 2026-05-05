"""Audit subscriber — single writer of the strategy_events table.

The Strategy v2 engine and surrounding services publish events on the bus.
This subscriber is wired to every strategy.* and account.* topic in
subscribers/__init__.py. It serializes the event payload, computes a chained
SHA-256 hash, and inserts a strategy_events row.

The chain:
    row.prev_hash = sha256(prev_payload + prev.prev_hash).hex
    row.row_hash  = sha256(this_payload + row.prev_hash).hex

GET /strategy/api/v2/audit/verify/<run_id> recomputes the chain and reports
the first divergent row — tampering or corruption is detectable, not
preventable.

The engine MUST NOT insert into strategy_events directly — see plan §13 D21.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from typing import Any, Optional

from sqlalchemy import desc

from database.strategy_v2_db import StrategyEvent, db_session
from utils.logging import get_logger

logger = get_logger(__name__)


# Mapping bus topic → audit type column. Most topics share their suffix.
_TOPIC_TO_AUDIT_TYPE = {
    # strategy.*
    "strategy.signal_received": "SIGNAL_RECEIVED",
    "strategy.signal_rejected": "SIGNAL_REJECTED",
    "strategy.run_started": "RUN_STARTED",
    "strategy.state_changed": "STATE_CHANGE",
    "strategy.leg_resolved": "LEG_RESOLVED",
    "strategy.leg_filled": "LEG_FILLED",
    "strategy.rms_triggered": "RMS_TRIGGERED",
    "strategy.trail_advanced": "TRAIL_ADVANCED",
    "strategy.exit_triggered": "EXIT_TRIGGERED",
    "strategy.enter_failed": "ENTRY_FAILED",
    "strategy.exit_failed": "EXIT_PARTIAL_FAILURE",
    "strategy.run_closed": "RUN_CLOSED",
    "strategy.engine_error": "ENGINE_ERROR",
    "strategy.webhook_secret_rotated": "WEBHOOK_KEY_ROTATED",
    "strategy.webhook_banned": "WEBHOOK_BANNED",
    # account.*
    "account.locked": "ACCOUNT_LOCKED",
    "account.unlocked": "ACCOUNT_UNLOCKED",
}


def _payload_for_event(event: Any) -> str:
    """Serialize a dataclass-event's fields (minus topic) to a sorted-key JSON string.
    Sorted keys make the hash deterministic so the chain verifier is reproducible."""
    if is_dataclass(event):
        d = asdict(event)
    elif isinstance(event, dict):
        d = dict(event)
    else:
        d = {"repr": repr(event)}
    d.pop("topic", None)
    return json.dumps(d, sort_keys=True, default=_json_default)


def _json_default(value: Any) -> Any:
    """Best-effort JSON encoding for values dataclasses might carry (datetime, Decimal, etc.)."""
    try:
        return value.isoformat()
    except Exception:  # noqa: BLE001
        try:
            return float(value)
        except Exception:
            return repr(value)


def _last_hash_for_run(run_id: Optional[int]) -> str:
    """Return the row_hash of the most recent strategy_events row for this run,
    or '' if this is the first row. Used as the previous link in the chain.
    Run-id is the chain partition — separate runs have independent chains."""
    if not run_id:
        return ""
    row = (
        db_session.query(StrategyEvent.row_hash)
        .filter(StrategyEvent.run_id == run_id)
        .order_by(desc(StrategyEvent.id))
        .first()
    )
    return (row[0] if row and row[0] else "") if row else ""


def compute_row_hash(payload: str, prev_hash: str) -> str:
    """Public helper — used by the verifier endpoint to recompute the chain."""
    h = hashlib.sha256()
    h.update(prev_hash.encode("utf-8"))
    h.update(b"|")
    h.update(payload.encode("utf-8"))
    return h.hexdigest()


def on_event(event: Any) -> None:
    """Subscriber callback — wired in subscribers/__init__.py for every
    strategy.* and account.* topic."""
    topic = getattr(event, "topic", "")
    audit_type = _TOPIC_TO_AUDIT_TYPE.get(topic)
    if audit_type is None:
        # Topic not mapped — log but don't drop. Indicates a missing wiring.
        logger.warning("strategy_audit_subscriber: unmapped topic %r", topic)
        audit_type = topic.upper().replace(".", "_")

    strategy_id = int(getattr(event, "strategy_id", 0) or 0)
    run_id = int(getattr(event, "run_id", 0) or 0) or None
    leg_id = int(getattr(event, "leg_id", 0) or 0) or None

    payload_json = _payload_for_event(event)
    prev_hash = _last_hash_for_run(run_id)
    row_hash = compute_row_hash(payload_json, prev_hash)

    try:
        row = StrategyEvent(
            strategy_id=strategy_id,
            run_id=run_id,
            leg_id=leg_id,
            type=audit_type,
            payload=payload_json,
            prev_hash=prev_hash,
            row_hash=row_hash,
        )
        db_session.add(row)
        db_session.commit()
    except Exception:
        db_session.rollback()
        # Never let an audit failure cascade into other subscribers — log only.
        logger.exception(
            "strategy_audit_subscriber failed to persist event topic=%s strategy_id=%s run_id=%s",
            topic,
            strategy_id,
            run_id,
        )
    finally:
        db_session.remove()


def verify_chain(run_id: int) -> dict:
    """Walk the chain for a run; return the first divergent row's id or 'ok'.
    Used by GET /strategy/api/v2/audit/verify/<run_id>."""
    rows = (
        db_session.query(StrategyEvent)
        .filter(StrategyEvent.run_id == run_id)
        .order_by(StrategyEvent.id)
        .all()
    )
    prev = ""
    for row in rows:
        expected = compute_row_hash(row.payload or "", prev)
        if expected != row.row_hash:
            return {
                "status": "tampered",
                "first_bad_event_id": row.id,
                "expected_row_hash": expected,
                "stored_row_hash": row.row_hash,
                "events_verified": rows.index(row),
            }
        prev = row.row_hash or ""
    return {"status": "ok", "events_verified": len(rows)}
