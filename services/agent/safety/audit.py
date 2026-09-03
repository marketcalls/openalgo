"""Append-only audit of every mutating agent tool call.

The `ag_audit` table answers one question after the fact: what did the agent try
to do, what was decided about it, and what came back. Every mutating tool writes
**two rows** - `attempt` before the service is called and `result` after it
returns - plus a `decision` row when a human approves or rejects a paused run.
Two rows rather than one because the interesting failure is the call that never
came back: an attempt with no matching result is a tool that hung or a worker
that died mid-order, and a single row written at the end cannot show that.

Two rules govern this module.

**Nothing secret is ever written.** Tool arguments carry an OpenAlgo API key on
several paths, and a conversation can put a provider key into an argument by
accident. :func:`redact` strips both shapes: argument names that look like
credentials, and values that look like keys regardless of their name. An audit
trail that leaks the key it is auditing is worse than no audit trail.

**A write failure never blocks a trade.** Every entry point swallows its
exception after `logger.exception`. This table is evidence, not a control: the
guard in `safety/risk.py` decides, and losing the paperwork must not stop an
order the operator approved, nor turn a successful order into an error the model
retries. The one thing that would be worse than a missing audit row is a second
unintended order caused by one.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from utils.logging import get_logger

logger = get_logger(__name__)

PHASE_ATTEMPT = "attempt"
PHASE_RESULT = "result"
PHASE_DECISION = "decision"

REDACTED = "[redacted]"

# Argument names whose value is never written. Matched as substrings of the
# lower-cased key, so `openalgo_api_key`, `X-API-KEY` and `broker_secret` are all
# caught without enumerating them.
_SECRET_KEY_MARKERS: tuple[str, ...] = (
    "api_key",
    "apikey",
    "api-key",
    "secret",
    "token",
    "password",
    "passwd",
    "pwd",
    "credential",
    "authorization",
    "auth_token",
    "cookie",
    "pepper",
    "private",
    "passphrase",
    "totp",
)

# Names that contain a marker but are not secrets. Counting tokens and naming an
# instrument are both ordinary things for a tool argument to do, and redacting
# them costs real audit value.
_SAFE_KEY_NAMES: frozenset[str] = frozenset(
    {
        "max_tokens",
        "min_tokens",
        "num_tokens",
        "n_tokens",
        "token_count",
        "total_tokens",
        "input_tokens",
        "output_tokens",
        "prompt_tokens",
        "completion_tokens",
        "reasoning_tokens",
        "cached_tokens",
        "tokens_used",
        "token",
        "tokens",
        "symboltoken",
        "symbol_token",
        "instrument_token",
        "exchange_token",
        "brtoken",
    }
)

# Value shapes that are secrets whatever the argument is called: a provider key,
# a bearer token, or a long pure-hex string, which is what every generated key in
# this project looks like (`secrets.token_hex(32)`).
_SECRET_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{16,}", re.IGNORECASE),
    re.compile(r"^[0-9a-f]{32,}$", re.IGNORECASE),
)

# Bounds. An audit row is a record, not a transcript: a tool that was handed a
# 200KB payload must not put 200KB into the database on every call.
_MAX_STRING = 2000
_MAX_ITEMS = 200
_MAX_DEPTH = 6
_MAX_ORDER_IDS = 100

# Compared against the lower-cased key, so `orderId`, `OrderID` and `orderid`
# all match the one entry.
_ORDER_ID_KEYS: frozenset[str] = frozenset(
    {"orderid", "order_id", "norenordno", "nestordernumber", "broker_orderid"}
)


def _is_secret_key(key: str) -> bool:
    """Whether an argument name means the value must not be stored."""
    lowered = key.strip().lower()
    if lowered in _SAFE_KEY_NAMES:
        return False
    return any(marker in lowered for marker in _SECRET_KEY_MARKERS)


def _redact_text(value: str) -> str:
    """Redact secret-shaped substrings and cap the length."""
    for pattern in _SECRET_VALUE_PATTERNS:
        value = pattern.sub(REDACTED, value)
    if len(value) > _MAX_STRING:
        return f"{value[:_MAX_STRING]}... [truncated, {len(value)} characters]"
    return value


def redact(value: Any, *, _depth: int = 0) -> Any:
    """Return a JSON-safe copy of ``value`` with every secret removed.

    Walks mappings and sequences, dropping the value of any key whose name looks
    like a credential and rewriting any string that looks like a key. Also caps
    depth, list length and string length so one oversized argument cannot bloat
    the audit table.

    Args:
        value: Any tool argument or response payload.
        _depth: Recursion depth, used internally.

    Returns:
        A structure of plain JSON-safe types, safe to store and to display.
    """
    if _depth > _MAX_DEPTH:
        return "[nested too deeply]"

    if value is None or isinstance(value, bool | int | float):
        return value

    if isinstance(value, str):
        return _redact_text(value)

    if isinstance(value, Decimal):
        return str(value)

    if isinstance(value, datetime | date):
        return value.isoformat()

    if isinstance(value, Enum):
        return redact(value.value, _depth=_depth + 1)

    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            redacted[key] = REDACTED if _is_secret_key(key) else redact(item, _depth=_depth + 1)
        return redacted

    if isinstance(value, bytes | bytearray):
        return f"[{len(value)} bytes]"

    if isinstance(value, Sequence | set | frozenset):
        items = list(value)
        rendered = [redact(item, _depth=_depth + 1) for item in items[:_MAX_ITEMS]]
        if len(items) > _MAX_ITEMS:
            rendered.append(f"... [{len(items) - _MAX_ITEMS} more items]")
        return rendered

    return _redact_text(repr(value))


def extract_order_ids(payload: Any, *, _depth: int = 0) -> list[str]:
    """Pull every order id out of a broker or service response.

    The shape differs per call - one id at the top level, a list under
    `results`, one per leg of a basket - so the payload is walked rather than
    pattern-matched against one known layout.

    Args:
        payload: A service response, already unwrapped or not.
        _depth: Recursion depth, used internally.

    Returns:
        The order ids found, de-duplicated, in the order they appeared, capped
        at 100.
    """
    found: list[str] = []

    def walk(node: Any, depth: int) -> None:
        if depth > _MAX_DEPTH or len(found) >= _MAX_ORDER_IDS:
            return
        if isinstance(node, Mapping):
            for key, value in node.items():
                if str(key).strip().lower() in _ORDER_ID_KEYS and isinstance(value, str | int):
                    text = str(value).strip()
                    if text and text not in found:
                        found.append(text)
                else:
                    walk(value, depth + 1)
        elif isinstance(node, Sequence) and not isinstance(node, str | bytes | bytearray):
            for item in node:
                walk(item, depth + 1)

    walk(payload, _depth)
    return found[:_MAX_ORDER_IDS]


def _verdict_summary(risk_verdict: Any) -> str | None:
    """Render a risk verdict as one short, stable string for its column.

    Accepts a `Verdict` from `safety/risk.py`, a plain string, or None. The full
    verdict belongs in the `result` row's response, where its numbers survive;
    this column is what a human scans.
    """
    if risk_verdict is None:
        return None
    allowed = getattr(risk_verdict, "allowed", None)
    code = getattr(risk_verdict, "code", None)
    if allowed is not None and code is not None:
        summary = f"{'allow' if allowed else 'block'}:{code}"
    else:
        summary = str(risk_verdict)
    # ag_audit.risk_verdict is String(60). SQLite would store an over-long value
    # happily and PostgreSQL would refuse the whole row, taking the audit trail
    # down on the one deployment that enforces it.
    return summary[:60]


def append(
    phase: str,
    tool: str,
    args: Any = None,
    *,
    conversation_id: Any = None,
    run_id: str | None = None,
    risk_verdict: Any = None,
    ok: bool | None = None,
    response: Any = None,
    order_ids: Iterable[Any] | None = None,
) -> int | None:
    """Write one audit row.

    Never raises. A failure to record is logged and swallowed, because this
    table is evidence and the trade is the thing that matters.

    Args:
        phase: One of `attempt`, `result`, `decision`.
        tool: The tool name, as the model sees it.
        args: The tool arguments. Redacted before they are stored.
        conversation_id: The `ag_conversation` id this call belongs to.
        run_id: The agno run id, which ties the two rows of one call together.
        risk_verdict: A `Verdict`, or a short string.
        ok: Whether the call succeeded. Only meaningful on a `result` row.
        response: The service response. Redacted before it is stored.
        order_ids: Order ids the call produced. Derived from ``response`` when
            not given.

    Returns:
        The new row id, or None when the row could not be written.
    """
    try:
        safe_args = redact(args) if args is not None else None
        safe_response = redact(response) if response is not None else None

        if order_ids is None:
            ids = extract_order_ids(response) if response is not None else []
        else:
            ids = [str(order_id).strip() for order_id in order_ids if str(order_id).strip()]
            ids = ids[:_MAX_ORDER_IDS]

        from database import agent_db

        return agent_db.record_audit(
            phase=str(phase),
            tool=str(tool),
            conversation_id=conversation_id,
            run_id=run_id,
            args=safe_args,
            risk_verdict=_verdict_summary(risk_verdict),
            ok=ok,
            response=safe_response,
            order_ids=ids or None,
        )
    except Exception:
        logger.exception("Agent audit row could not be written: phase=%s tool=%s", phase, tool)
        return None


def record_attempt(
    tool: str,
    args: Any = None,
    *,
    conversation_id: Any = None,
    run_id: str | None = None,
    risk_verdict: Any = None,
) -> int | None:
    """Write the `attempt` row, before the service is called.

    Args:
        tool: The tool name.
        args: The tool arguments.
        conversation_id: The conversation this call belongs to.
        run_id: The agno run id.
        risk_verdict: The guard's verdict, when it has already run.

    Returns:
        The new row id, or None.
    """
    return append(
        PHASE_ATTEMPT,
        tool,
        args,
        conversation_id=conversation_id,
        run_id=run_id,
        risk_verdict=risk_verdict,
    )


def record_result(
    tool: str,
    *,
    ok: bool,
    response: Any = None,
    args: Any = None,
    conversation_id: Any = None,
    run_id: str | None = None,
    risk_verdict: Any = None,
    order_ids: Iterable[Any] | None = None,
) -> int | None:
    """Write the `result` row, after the service returns or raises.

    Args:
        tool: The tool name.
        ok: Whether the call succeeded.
        response: The service response, or the error payload.
        args: The tool arguments, when worth repeating on the result row.
        conversation_id: The conversation this call belongs to.
        run_id: The agno run id.
        risk_verdict: The guard's verdict.
        order_ids: Order ids the call produced. Derived from ``response`` when
            not given.

    Returns:
        The new row id, or None.
    """
    return append(
        PHASE_RESULT,
        tool,
        args,
        conversation_id=conversation_id,
        run_id=run_id,
        risk_verdict=risk_verdict,
        ok=ok,
        response=response,
        order_ids=order_ids,
    )


def record_decision(
    tool: str,
    *,
    approved: bool,
    args: Any = None,
    conversation_id: Any = None,
    run_id: str | None = None,
    actor: str | None = None,
    note: str | None = None,
) -> int | None:
    """Write the `decision` row for a human approval or rejection.

    Args:
        tool: The tool the confirmation was requested for.
        approved: True when the human approved the call.
        args: The arguments the human was shown.
        conversation_id: The conversation this call belongs to.
        run_id: The agno run id of the paused run.
        actor: Who decided, when the caller knows.
        note: Anything the human typed alongside the decision.

    Returns:
        The new row id, or None.
    """
    payload: dict[str, Any] = {"approved": bool(approved)}
    if actor:
        payload["actor"] = actor
    if note:
        payload["note"] = note
    return append(
        PHASE_DECISION,
        tool,
        args,
        conversation_id=conversation_id,
        run_id=run_id,
        risk_verdict=f"decision:{'approved' if approved else 'rejected'}",
        ok=bool(approved),
        response=payload,
    )


def record_block(
    tool: str,
    args: Any,
    risk_verdict: Any,
    *,
    conversation_id: Any = None,
    run_id: str | None = None,
) -> None:
    """Record an order the guard refused, as both rows.

    A refusal is still a mutating call that was made, so it gets the same
    attempt-then-result pair as one that reached the broker. Without the pair, a
    blocked order looks in the audit trail exactly like a call that vanished.

    Args:
        tool: The tool name.
        args: The tool arguments.
        risk_verdict: The refusing `Verdict`.
        conversation_id: The conversation this call belongs to.
        run_id: The agno run id.
    """
    record_attempt(
        tool, args, conversation_id=conversation_id, run_id=run_id, risk_verdict=risk_verdict
    )
    as_dict = getattr(risk_verdict, "as_dict", None)
    as_message = getattr(risk_verdict, "as_message", None)
    response = {
        "error": as_message() if callable(as_message) else str(risk_verdict),
        "risk": as_dict() if callable(as_dict) else None,
    }
    record_result(
        tool,
        ok=False,
        response=response,
        conversation_id=conversation_id,
        run_id=run_id,
        risk_verdict=risk_verdict,
    )


@dataclass
class AuditedCall:
    """The handle :func:`audited` yields, used to fill in the result row.

    Attributes:
        ok: Whether the call succeeded. Defaults to True and is set to False
            automatically when the body raises.
        response: The payload stored on the result row.
        order_ids: Order ids to store. Derived from ``response`` when left
            empty.
        attempt_id: The id of the attempt row, when it was written.
    """

    ok: bool = True
    response: Any = None
    order_ids: list[str] = field(default_factory=list)
    attempt_id: int | None = None

    def succeeded(self, response: Any = None, order_ids: Iterable[Any] | None = None) -> None:
        """Mark the call successful.

        Args:
            response: The service response.
            order_ids: Order ids, when the caller already knows them.
        """
        self.ok = True
        self.response = response
        if order_ids is not None:
            self.order_ids = [str(order_id) for order_id in order_ids]

    def failed(self, response: Any = None) -> None:
        """Mark the call failed.

        Args:
            response: The error payload.
        """
        self.ok = False
        self.response = response


@contextmanager
def audited(
    tool: str,
    args: Any = None,
    *,
    conversation_id: Any = None,
    run_id: str | None = None,
    risk_verdict: Any = None,
):
    """Write the attempt row, run the body, then write the result row.

    The result row is written from a `finally` block, so a tool that raises
    still leaves a matching pair rather than an attempt with no ending. The
    exception itself is re-raised untouched: this module records, it does not
    handle.

    Args:
        tool: The tool name.
        args: The tool arguments.
        conversation_id: The conversation this call belongs to.
        run_id: The agno run id.
        risk_verdict: The guard's verdict for this call.

    Yields:
        An :class:`AuditedCall` on which to record the response.
    """
    call = AuditedCall()
    call.attempt_id = record_attempt(
        tool, args, conversation_id=conversation_id, run_id=run_id, risk_verdict=risk_verdict
    )
    try:
        yield call
    except Exception as exc:
        call.ok = False
        if call.response is None:
            call.response = {"error": f"{type(exc).__name__}: {exc}"}
        raise
    finally:
        record_result(
            tool,
            ok=call.ok,
            response=call.response,
            conversation_id=conversation_id,
            run_id=run_id,
            risk_verdict=risk_verdict,
            order_ids=call.order_ids or None,
        )
