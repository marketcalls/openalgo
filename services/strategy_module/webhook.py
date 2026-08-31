"""Validation pipeline for the public ``/strategy/webhook/<token>`` endpoint.

This is the one place in the module where an unauthenticated caller can start
or stop real trading. The route that fronts it is public, CSRF exempt and
reachable by anything that can resolve the host, so every decision about
whether a signal is acted on is made here rather than in the view, and the
whole pipeline is callable without a request context so it can be tested for
what it refuses rather than only for what it accepts.

The token is the credential, and it is in the URL because TradingView cannot
set a header. Three consequences shape this file:

* **The token is never logged and never persisted.** Only a SHA-256 digest is
  stored, and what appears in a log line here is the first twelve characters of
  that digest, which is enough to correlate two events and useless to anyone
  who intercepts it. The inbound payload is redacted before it reaches the
  audit row, because a user who pastes the webhook URL into an alert message
  would otherwise write the credential into the database in plaintext.
* **A rejection must not say whether the token exists.** An unknown token and a
  token that never was one produce the same result label, the same body and the
  same status. A malformed one is refused on its shape before any lookup, so a
  scanner cannot even measure the database round trip.
* **The route answers with a controlled 404, not Flask's.** ``app.py``'s 404
  error handler feeds ``Error404Tracker``, which bans an IP after enough
  unauthenticated misses. Letting a rotated token fall through to it would let
  a scanner walking the token space ban the address a legitimate alert arrives
  from. :func:`unknown_token_outcome` is what the view returns instead: it
  keeps the status, writes the audit row and never raises ``NotFound``, so the
  app handler is not consulted.

The order of the stages below is the contract, and it is deliberate: the kill
switch outranks the allowlist, the allowlist outranks the payload (so a body
from a blocked address is never even parsed), and the live gate sits behind
both action checks so a malformed alert can never be the thing that reaches a
broker.

Idempotency and cooling off exist for two failure modes seen in the wild.
TradingView retries an alert it thinks failed, so the same start would place a
second set of legs; and a misconfigured pair of alerts fires start and stop
against each other, so a strategy oscillates and pays the spread each time.
Both windows are held in bounded :class:`~cachetools.TTLCache` instances, not
plain dicts: this process is a single Gunicorn worker that never restarts, so
an unbounded key space keyed by strategy would be a slow leak.

The engine is injected. Nothing here imports it, so this module can be tested,
and reviewed, without a broker, a database engine or a running strategy.
"""

from __future__ import annotations

import ipaddress
import json
import re
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from cachetools import TTLCache

from database import strategy_module_db as store
from utils.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Vocabulary and limits
# ---------------------------------------------------------------------------

#: What an inbound alert may ask for. ``mode`` is required with ``start`` and
#: ignored with ``stop``, which is why it is not part of this tuple.
ACTIONS = ("start", "stop")

#: Largest body accepted, measured on the bytes as received. A TradingView
#: alert is a few hundred bytes; the cap is here so a body that is not an alert
#: at all is refused before it is parsed and before it reaches a JSON column.
MAX_PAYLOAD_BYTES = 16384

#: Two identical signals inside this window are one signal. Sized for a sender
#: that retries a delivery it believes failed, not for a strategy that
#: legitimately restarts.
DEDUPE_WINDOW_SECONDS = 60

#: A strategy that has just stopped refuses to start again for this long. Short
#: enough that a deliberate restart is only briefly inconvenient, long enough
#: that a start/stop pair firing against each other cannot cycle.
COOLING_OFF_SECONDS = 30

#: Bound on each window's key space. TTL alone is not a bound: a burst inside
#: one window would still be held in memory in a worker that never restarts.
#: On overflow ``TTLCache`` evicts the least recently used entry, so the worst
#: case is that one deduplication is missed under a flood the route's rate
#: limit is already refusing.
MAX_TRACKED_KEYS = 4096

#: HTTP status per result label. Every key is a member of
#: ``store.WEBHOOK_RESULTS``; ``rate_limited`` belongs to the route's limiter
#: and is listed so the view has one table to read.
RESULT_STATUS: dict[str, int] = {
    "ok": 200,
    "rejected_token": 404,
    "rejected_locked": 403,
    "rejected_ip": 403,
    "rejected_payload": 400,
    "rejected_invalid_action": 400,
    "rejected_live_disabled": 403,
    "rejected_dedupe": 200,
    "rejected_cooling_off": 409,
    "rejected_engine_error": 500,
    "rate_limited": 429,
}

#: The one message an unresolvable token ever produces. A single constant
#: rather than a literal at each call site, because the two paths that use it
#: (a token that is not one, and a token that is not ours) must stay
#: byte-identical or the difference becomes an oracle.
_UNKNOWN_TOKEN_MESSAGE = "Unknown or expired webhook token"

#: A token is prefix plus 43 URL-safe characters. The bounds are loose so a
#: future token length still resolves normally rather than being refused here.
_TOKEN_BODY = re.compile(r"^[A-Za-z0-9_-]{16,128}$")

# Redaction limits for the audit copy of the payload.
_REDACTED = "[redacted]"
_SECRET_KEY_HINTS = (
    "token",
    "secret",
    "password",
    "passwd",
    "apikey",
    "api_key",
    "auth",
    "signature",
)
_MAX_AUDIT_ITEMS = 50
_MAX_AUDIT_STRING = 500
_MAX_AUDIT_DEPTH = 4


# ---------------------------------------------------------------------------
# Clock and bounded windows
#
# The clock is a module attribute rather than a direct call to time.monotonic
# so a test can drive the two windows without sleeping through them. Both
# caches read it through _now, which looks the attribute up on every call.
# ---------------------------------------------------------------------------

_clock = time.monotonic


def _now() -> float:
    return _clock()


def _new_dedupe_cache() -> TTLCache:
    return TTLCache(maxsize=MAX_TRACKED_KEYS, ttl=DEDUPE_WINDOW_SECONDS, timer=_now)


def _new_cooling_off_cache() -> TTLCache:
    return TTLCache(maxsize=MAX_TRACKED_KEYS, ttl=COOLING_OFF_SECONDS, timer=_now)


#: (strategy_id, action, mode) -> when it was claimed.
_dedupe: TTLCache = _new_dedupe_cache()

#: strategy_id -> when its run stopped.
_cooling_off: TTLCache = _new_cooling_off_cache()

# Guards the two caches above and nothing else. Under eventlet this is a green
# lock and under the threaded development server a real one, which is correct
# in both: the critical sections below are in-memory bookkeeping with no yield
# point, and no database or engine call is ever made while it is held.
_cache_lock = threading.Lock()


def reset_state() -> None:
    """Drop both windows. For tests, and for a deliberate operator reset."""
    global _dedupe, _cooling_off
    with _cache_lock:
        _dedupe = _new_dedupe_cache()
        _cooling_off = _new_cooling_off_cache()


def note_run_stopped(strategy_id: int) -> None:
    """Arm the cooling-off window for a strategy whose run has just ended.

    Called from here when a webhook stop succeeds, and meant to be called by
    the engine for every stop it initiates itself: an end-of-day square-off, an
    overall stop loss, a manual stop from the UI. Without that second caller a
    strategy stopped by its own risk rules would accept a start from a stale
    alert one second later, which is the exact sequence the window exists to
    prevent.
    """
    with _cache_lock:
        _cooling_off[strategy_id] = _now()


def _cooling_off_remaining(strategy_id: int) -> int:
    """Whole seconds left on a strategy's cooling-off window, floor 1."""
    stopped_at = _cooling_off.get(strategy_id)
    if stopped_at is None:
        return 0
    return max(1, int(COOLING_OFF_SECONDS - (_now() - stopped_at)))


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EngineResult:
    """What the engine reports back about one start or stop.

    ``ok`` is whether the engine accepted the instruction, not whether every
    leg filled. Fills arrive later over the order-update stream.
    """

    ok: bool
    run_id: int | None = None
    error: str | None = None
    stop_pending: bool | None = None
    exits: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class WebhookOutcome:
    """The decision, ready for the view to turn into a response.

    ``ok`` and ``result`` are not the same question. A deduplicated retry is
    ``ok`` because the caller's intent was already satisfied, and its result is
    ``rejected_dedupe`` because the audit trail has to show that this
    particular delivery did nothing.
    """

    ok: bool
    result: str
    status: int
    message: str
    strategy_id: int | None = None
    run_id: int | None = None
    webhook_event_id: int | None = None
    stop_pending: bool | None = None
    exits: list[dict[str, Any]] = field(default_factory=list)

    @property
    def body(self) -> dict[str, Any]:
        """The JSON body. Carries nothing a caller has not already proved."""
        payload: dict[str, Any] = {
            "status": "success" if self.ok else "error",
            "result": self.result,
            "message": self.message,
        }
        if self.strategy_id is not None:
            payload["strategy_id"] = self.strategy_id
        if self.run_id is not None:
            payload["run_id"] = self.run_id
        if self.stop_pending is not None:
            payload["stop_pending"] = self.stop_pending
            payload["exits"] = self.exits
        return payload

    def as_response(self) -> tuple[dict[str, Any], int]:
        """``(body, status)``, which the view hands to ``jsonify``."""
        return self.body, self.status


# ---------------------------------------------------------------------------
# Engine injection
#
# The engine is a parameter, and its default is a lazy import resolved at call
# time. Nothing is imported at module scope, so this module has no opinion on
# where the engine lives and a test never has to construct one.
# ---------------------------------------------------------------------------


class WebhookEngine(Protocol):
    """What this module needs from the engine. A module satisfies it."""

    def start_run(
        self,
        strategy: Any,
        mode: str,
        *,
        trigger_source: str = "webhook",
        webhook_event_id: int | None = None,
    ) -> EngineResult | dict[str, Any] | bool | None:
        """Start a run for ``strategy`` in ``mode`` (``live`` or ``sandbox``)."""

    def stop_run(
        self,
        strategy: Any,
        *,
        stop_reason: str = "manual",
        trigger_source: str = "webhook",
        webhook_event_id: int | None = None,
    ) -> EngineResult | dict[str, Any] | bool | None:
        """Stop the strategy's current run."""


def _default_engine() -> WebhookEngine:
    """The engine used when the caller injects none.

    This is the bridge in webhook_bridge.py, not the engine itself: the two were
    built to different signatures on purpose (this handler holds a strategy row,
    the engine takes ids because the UI and scheduler drive it too), and the
    bridge is the one place that knows both.

    Imported here rather than at module scope so that importing this module
    pulls in no broker or database dependency of the engine's, and so that a
    test can replace this function without touching an import graph.
    """
    from services.strategy_module import webhook_bridge  # noqa: PLC0415

    return webhook_bridge


def _coerce_engine_result(value: Any) -> EngineResult:
    """Normalize whatever the engine returned.

    An :class:`EngineResult` is preferred. A mapping, a bare bool and ``None``
    are accepted so the engine is not forced to import this module, and so a
    first implementation that simply returns ``True`` still wires up.
    """
    if isinstance(value, EngineResult):
        return value
    if value is None or value is True:
        return EngineResult(ok=True)
    if value is False:
        return EngineResult(ok=False, error="The engine refused the signal")
    if isinstance(value, dict):
        return EngineResult(
            ok=bool(value.get("ok", True)),
            run_id=value.get("run_id"),
            error=value.get("error"),
            stop_pending=(bool(value.get("stop_pending")) if "stop_pending" in value else None),
            exits=list(value.get("exits") or []),
        )
    ok = getattr(value, "ok", None)
    if ok is not None:
        return EngineResult(
            ok=bool(ok),
            run_id=getattr(value, "run_id", None),
            error=getattr(value, "error", None),
            stop_pending=getattr(value, "stop_pending", None),
            exits=list(getattr(value, "exits", None) or []),
        )
    return EngineResult(ok=True)


# ---------------------------------------------------------------------------
# Token, address and payload checks
# ---------------------------------------------------------------------------


def _looks_like_token(token: Any) -> bool:
    """Whether a URL segment is shaped like one of our tokens.

    A cheap shape check before the lookup, so a scanner posting arbitrary path
    segments costs nothing but the audit write, and so the timing of a refusal
    does not distinguish a well-formed guess from a wrong one by way of the
    database round trip.
    """
    if not isinstance(token, str):
        return False
    prefix = store.WEBHOOK_TOKEN_PREFIX
    if not token.startswith(prefix):
        return False
    return bool(_TOKEN_BODY.match(token[len(prefix) :]))


def _token_hint(token: Any) -> str:
    """A short, non-reversible handle for logs.

    The first twelve hex characters of the stored digest. Enough to line two
    log lines up against one strategy, and not enough to be a credential.
    """
    if not isinstance(token, str) or not token:
        return "none"
    try:
        return store.hash_webhook_token(token)[:12]
    except Exception:
        logger.exception("Could not hash an inbound webhook token")
        return "unhashable"


def ip_allowed(ip: str | None, allowlist: Iterable[str] | None) -> bool:
    """Whether ``ip`` falls inside a strategy's allowlist.

    An empty or absent allowlist allows everything, which is the default a
    strategy is created with. A non-empty one is a closed set: an address that
    cannot be parsed, or that was never supplied because the request arrived
    without one, is refused rather than waved through.

    Entries are CIDR ranges, and a bare address is read as its own /32 or /128.
    A single malformed entry is skipped rather than failing the whole list
    closed, so one bad row in the JSON column cannot silently disable a
    strategy's webhook.
    """
    entries = [e.strip() for e in (allowlist or []) if isinstance(e, str) and e.strip()]
    if not entries:
        return True
    if not isinstance(ip, str) or not ip.strip():
        return False

    try:
        address = ipaddress.ip_address(ip.strip())
    except ValueError:
        return False

    # A proxy in front of the app may present an IPv4 caller in its IPv6-mapped
    # form. Both spellings are the same machine, so both are tested.
    candidates = [address]
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        candidates.append(mapped)

    for entry in entries:
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError:
            logger.warning("Skipping a malformed webhook allowlist entry: %r", entry)
            continue
        for candidate in candidates:
            if candidate.version == network.version and candidate in network:
                return True
    return False


def _parse_payload(body: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Read the request body into a dict, or say why it cannot be one.

    Accepts what the view has, in either form: the raw bytes or text it read
    off the request, or an already-parsed mapping. Everything else, a JSON
    list included, is refused: the contract is an object with an ``action``.
    """
    if body is None:
        return None, "The request body is empty"

    if isinstance(body, bytes | bytearray):
        if len(body) > MAX_PAYLOAD_BYTES:
            return None, f"The request body is larger than {MAX_PAYLOAD_BYTES} bytes"
        try:
            return _parse_text(bytes(body).decode("utf-8"))
        except UnicodeDecodeError:
            return None, "The request body is not valid UTF-8"

    if isinstance(body, str):
        if len(body.encode("utf-8", "replace")) > MAX_PAYLOAD_BYTES:
            return None, f"The request body is larger than {MAX_PAYLOAD_BYTES} bytes"
        return _parse_text(body)

    if isinstance(body, dict):
        # Already parsed by the view. Still measured, because the cap protects
        # the audit column as much as it protects the parser.
        try:
            encoded = json.dumps(body, default=str)
        except (TypeError, ValueError):
            return None, "The request body is not valid JSON"
        if len(encoded.encode("utf-8", "replace")) > MAX_PAYLOAD_BYTES:
            return None, f"The request body is larger than {MAX_PAYLOAD_BYTES} bytes"
        return body, None

    return None, "The request body must be a JSON object"


def _parse_text(text: str) -> tuple[dict[str, Any] | None, str | None]:
    stripped = text.strip()
    if not stripped:
        return None, "The request body is empty"
    try:
        parsed = json.loads(stripped)
    except ValueError:
        return None, "The request body is not valid JSON"
    if not isinstance(parsed, dict):
        return None, "The request body must be a JSON object"
    return parsed, None


def _redact(value: Any, token: Any, depth: int = 0) -> Any:
    """A copy of the payload that is safe to store.

    Two rules, both aimed at the same accident. A key that names a credential
    loses its value, and any string carrying the token, or anything else
    wearing the webhook token prefix, is replaced whole. The webhook URL is the
    thing an operator is most likely to paste into an alert message by mistake,
    and the audit table is readable from the UI.

    Depth, item count and string length are all capped, so a hostile body
    cannot turn one webhook into an unbounded JSON column.
    """
    if depth > _MAX_AUDIT_DEPTH:
        return "[truncated]"

    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in list(value.items())[:_MAX_AUDIT_ITEMS]:
            name = str(key)[:_MAX_AUDIT_STRING]
            if any(hint in name.lower() for hint in _SECRET_KEY_HINTS):
                redacted[name] = _REDACTED
            else:
                redacted[name] = _redact(item, token, depth + 1)
        return redacted

    if isinstance(value, list | tuple):
        return [_redact(item, token, depth + 1) for item in list(value)[:_MAX_AUDIT_ITEMS]]

    if isinstance(value, str):
        if isinstance(token, str) and token and token in value:
            return _REDACTED
        if store.WEBHOOK_TOKEN_PREFIX in value:
            return _REDACTED
        return value[:_MAX_AUDIT_STRING]

    if isinstance(value, bool | int | float) or value is None:
        return value

    return str(value)[:_MAX_AUDIT_STRING]


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def _audit(
    result: str,
    *,
    strategy_id: int | None = None,
    action: str | None = None,
    mode: str | None = None,
    payload: dict[str, Any] | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    error: str | None = None,
) -> int | None:
    """Write one row to ``sm_webhook_event`` and return its id.

    Every outcome is audited, rejections included: a webhook that was refused
    is exactly what an operator needs to see when an alert quietly stops
    working. The columns are narrow, so ``action`` and ``mode`` are truncated
    to what they hold rather than trusting the sender to have been sensible.

    Never called with a token. The plaintext is not a parameter of this
    function, which is the simplest way to keep it out of the table.
    """
    try:
        row = store.record_webhook_event(
            result=result,
            strategy_id=strategy_id,
            action=(action[:20] if isinstance(action, str) else None),
            mode=(mode[:10] if isinstance(mode, str) else None),
            payload=payload,
            ip=ip,
            user_agent=user_agent,
            error=error,
        )
        return getattr(row, "id", None)
    except Exception:
        # An audit failure must not swallow the signal, and must not be the
        # thing that 500s a webhook that was otherwise fine.
        logger.exception("Could not audit a webhook (%s)", result)
        return None


def _outcome(
    result: str,
    message: str,
    *,
    ok: bool = False,
    strategy_id: int | None = None,
    run_id: int | None = None,
    webhook_event_id: int | None = None,
    stop_pending: bool | None = None,
    exits: list[dict[str, Any]] | None = None,
) -> WebhookOutcome:
    return WebhookOutcome(
        ok=ok,
        result=result,
        status=RESULT_STATUS.get(result, 400),
        message=message,
        strategy_id=strategy_id,
        run_id=run_id,
        webhook_event_id=webhook_event_id,
        stop_pending=stop_pending,
        exits=list(exits or []),
    )


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def unknown_token_outcome(
    *,
    ip: str | None = None,
    user_agent: str | None = None,
    audit: bool = True,
) -> WebhookOutcome:
    """The canonical answer to a token that resolves to nothing.

    The view uses this for any request on the webhook path that cannot name a
    strategy, including one with no token segment at all. Returning it is what
    keeps the response out of Flask's 404 handler, which counts unauthenticated
    misses towards an IP ban: a scanner walking the token space would otherwise
    be able to get the address a real alert arrives from banned, and a rotated
    token would answer with the React shell instead of saying what happened.

    Identical in every field to the answer a well-formed but unregistered token
    gets, because those two cases must not be distinguishable.
    """
    event_id = _audit("rejected_token", ip=ip, user_agent=user_agent) if audit else None
    return _outcome(
        "rejected_token",
        _UNKNOWN_TOKEN_MESSAGE,
        webhook_event_id=event_id,
    )


def handle_webhook(
    token: str | None,
    body: bytes | str | dict[str, Any] | None = None,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
    engine: WebhookEngine | None = None,
) -> WebhookOutcome:
    """Run one inbound alert through the pipeline and dispatch it, or refuse it.

    ``body`` is whatever the view has: raw bytes, raw text, or an
    already-parsed mapping. ``engine`` overrides the lazily imported default
    and is how a test, or a caller that owns its own engine, injects one.

    The stages, in order, each writing its own audit row:

    1. the token resolves to a strategy       -> ``rejected_token`` (404)
    2. the strategy is not locked             -> ``rejected_locked`` (403)
    3. the caller is inside the allowlist     -> ``rejected_ip`` (403)
    4. the body is a JSON object within cap   -> ``rejected_payload`` (400)
    5. the action is one we accept            -> ``rejected_invalid_action`` (400)
    6. a start names a valid mode             -> ``rejected_invalid_action`` (400)
    7. a live start is enabled for live       -> ``rejected_live_disabled`` (403)
    8. it is not a retry of the last signal   -> ``rejected_dedupe`` (200, ok)
    9. the strategy is not cooling off        -> ``rejected_cooling_off`` (409)
    10. the engine accepts it                 -> ``ok`` (200)

    Never raises. An unexpected failure anywhere is logged with a traceback and
    reported as ``rejected_engine_error``, because a webhook endpoint that
    raises tells its caller nothing and tells the operator less.
    """
    try:
        return _handle(token, body, ip=ip, user_agent=user_agent, engine=engine)
    except Exception:
        logger.exception("Unhandled failure dispatching webhook %s", _token_hint(token))
        _audit(
            "rejected_engine_error",
            ip=ip,
            user_agent=user_agent,
            error="Unhandled failure in the webhook pipeline",
        )
        return _outcome("rejected_engine_error", "The signal could not be processed")


def _handle(
    token: str | None,
    body: bytes | str | dict[str, Any] | None,
    *,
    ip: str | None,
    user_agent: str | None,
    engine: WebhookEngine | None,
) -> WebhookOutcome:
    hint = _token_hint(token)

    # 1. Token. Shape first, so a segment that was never a token costs no
    #    lookup, then the hashed lookup. Both answer identically.
    if not _looks_like_token(token):
        logger.debug("Webhook rejected: malformed token from %s", ip)
        return unknown_token_outcome(ip=ip, user_agent=user_agent)

    strategy = store.get_strategy_by_webhook_token(token)
    if strategy is None:
        logger.debug("Webhook rejected: unknown token %s from %s", hint, ip)
        return unknown_token_outcome(ip=ip, user_agent=user_agent)

    strategy_id = strategy.id

    # 2. Kill switch. Ahead of everything else a caller controls, so an
    #    operator who has locked a strategy has locked it against a malformed
    #    payload and a valid one alike.
    if strategy.webhook_locked:
        logger.warning("Webhook refused: strategy %s is locked (token %s)", strategy_id, hint)
        event_id = _audit(
            "rejected_locked",
            strategy_id=strategy_id,
            ip=ip,
            user_agent=user_agent,
            error="The webhook kill switch is engaged",
        )
        return _outcome(
            "rejected_locked",
            "This strategy's webhook is locked",
            strategy_id=strategy_id,
            webhook_event_id=event_id,
        )

    # 3. Address. Before the body is parsed: a caller outside the allowlist
    #    gets no parser attention at all.
    if not ip_allowed(ip, strategy.webhook_ip_allowlist):
        logger.warning("Webhook refused: %s is outside strategy %s allowlist", ip, strategy_id)
        event_id = _audit(
            "rejected_ip",
            strategy_id=strategy_id,
            ip=ip,
            user_agent=user_agent,
            error="The caller address is outside the allowlist",
        )
        return _outcome(
            "rejected_ip",
            "This address is not allowed to trigger this strategy",
            strategy_id=strategy_id,
            webhook_event_id=event_id,
        )

    # 4. Payload.
    payload, parse_error = _parse_payload(body)
    if payload is None:
        event_id = _audit(
            "rejected_payload",
            strategy_id=strategy_id,
            ip=ip,
            user_agent=user_agent,
            error=parse_error,
        )
        return _outcome(
            "rejected_payload",
            parse_error or "The request body could not be read",
            strategy_id=strategy_id,
            webhook_event_id=event_id,
        )

    safe_payload = _redact(payload, token)

    # 5. Action. Which actions are valid depends on the strategy's kind: a
    #    batch strategy takes start and stop, a signal strategy takes the four
    #    directional actions. Sending one kind's vocabulary to the other is a
    #    configuration mistake, not a half-understood request, so it is refused
    #    rather than partly handled.
    from services.strategy_module import signals as signal_mode  # noqa: PLC0415

    allowed_actions = signal_mode.actions_for(getattr(strategy, "strategy_kind", "batch"))
    raw_action = payload.get("action")
    action = raw_action.strip().lower() if isinstance(raw_action, str) else None
    if action not in allowed_actions:
        event_id = _audit(
            "rejected_invalid_action",
            strategy_id=strategy_id,
            action=action or (str(raw_action) if raw_action is not None else None),
            payload=safe_payload,
            ip=ip,
            user_agent=user_agent,
            error="Unrecognised action",
        )
        return _outcome(
            "rejected_invalid_action",
            f"'action' must be one of {', '.join(allowed_actions)}",
            strategy_id=strategy_id,
            webhook_event_id=event_id,
        )

    # 5b. Signal-mode strategies branch out here, before the batch-only stages
    #     that follow.
    #
    #     Mode is not in a signal payload: the run takes it from the strategy's
    #     own live opt-in, so there is nothing to validate and no separate live
    #     gate to apply.
    #
    #     They also skip the dedupe and cooling-off windows deliberately.
    #     Those exist because a repeated start would open a second position;
    #     signal mode is already idempotent by meaning - a second long_entry on
    #     a leg already long is a no-op, and an exit for a position that is not
    #     held is a no-op. A 60 second window here would do harm rather than
    #     good: a genuine long, short, long sequence inside a minute is a real
    #     thing a strategy does, and suppressing the third leaves the position
    #     backwards.
    if action in signal_mode.SIGNAL_ACTIONS:
        return _dispatch_signal(
            strategy=strategy,
            action=action,
            payload=payload,
            safe_payload=safe_payload,
            ip=ip,
            user_agent=user_agent,
        )

    # 6. Mode, required by start and ignored by stop. A stop that carries one
    #    is not refused for it: the sender's extra field is not a reason to
    #    leave a position open.
    mode: str | None = None
    if action == "start":
        raw_mode = payload.get("mode")
        mode = raw_mode.strip().lower() if isinstance(raw_mode, str) else None
        if mode not in store.RUN_MODES:
            event_id = _audit(
                "rejected_invalid_action",
                strategy_id=strategy_id,
                action=action,
                mode=mode or (str(raw_mode) if raw_mode is not None else None),
                payload=safe_payload,
                ip=ip,
                user_agent=user_agent,
                error="Unrecognised mode",
            )
            return _outcome(
                "rejected_invalid_action",
                f"'mode' must be one of {', '.join(store.RUN_MODES)} when starting",
                strategy_id=strategy_id,
                webhook_event_id=event_id,
            )

        # 7. The live gate. The whole difference between a paper test and real
        #    money, and the reason a strategy is born sandbox-only.
        if mode == "live" and not strategy.live_enabled:
            logger.warning("Webhook refused: live start on sandbox-only strategy %s", strategy_id)
            event_id = _audit(
                "rejected_live_disabled",
                strategy_id=strategy_id,
                action=action,
                mode=mode,
                payload=safe_payload,
                ip=ip,
                user_agent=user_agent,
                error="Live trading is not enabled for this strategy",
            )
            return _outcome(
                "rejected_live_disabled",
                "Live trading is not enabled for this strategy",
                strategy_id=strategy_id,
                webhook_event_id=event_id,
            )

    # 8 and 9. Both windows are read and the claim is written under one lock,
    # so two deliveries arriving together cannot both pass.
    key = (strategy_id, action, mode)
    with _cache_lock:
        if key in _dedupe:
            refusal = "rejected_dedupe"
        elif action == "start" and strategy_id in _cooling_off:
            refusal = "rejected_cooling_off"
        else:
            refusal = ""
            _dedupe[key] = _now()

    if refusal == "rejected_dedupe":
        logger.info("Webhook deduplicated: %s on strategy %s", action, strategy_id)
        event_id = _audit(
            "rejected_dedupe",
            strategy_id=strategy_id,
            action=action,
            mode=mode,
            payload=safe_payload,
            ip=ip,
            user_agent=user_agent,
            error=f"Duplicate signal inside {DEDUPE_WINDOW_SECONDS}s",
        )
        # A success: the caller's intent was satisfied by the first delivery,
        # and a sender told otherwise would only retry harder.
        return _outcome(
            "rejected_dedupe",
            f"Duplicate signal ignored, already handled within {DEDUPE_WINDOW_SECONDS}s",
            ok=True,
            strategy_id=strategy_id,
            webhook_event_id=event_id,
        )

    if refusal == "rejected_cooling_off":
        remaining = _cooling_off_remaining(strategy_id)
        logger.warning("Webhook refused: strategy %s is cooling off", strategy_id)
        event_id = _audit(
            "rejected_cooling_off",
            strategy_id=strategy_id,
            action=action,
            mode=mode,
            payload=safe_payload,
            ip=ip,
            user_agent=user_agent,
            error=f"Stopped within the last {COOLING_OFF_SECONDS}s",
        )
        return _outcome(
            "rejected_cooling_off",
            f"This strategy stopped recently, try again in {remaining}s",
            strategy_id=strategy_id,
            webhook_event_id=event_id,
        )

    # 10. Dispatch. The accepted row is written first so the engine can point
    # its run at the event that caused it; sm_webhook_event is append-only, so
    # an engine failure appends a second row rather than editing this one.
    event_id = _audit(
        "ok",
        strategy_id=strategy_id,
        action=action,
        mode=mode,
        payload=safe_payload,
        ip=ip,
        user_agent=user_agent,
    )
    return _dispatch(
        strategy=strategy,
        action=action,
        mode=mode,
        key=key,
        event_id=event_id,
        safe_payload=safe_payload,
        ip=ip,
        user_agent=user_agent,
        engine=engine,
    )


def _dispatch_signal(
    *,
    strategy: Any,
    action: str,
    payload: dict[str, Any],
    safe_payload: dict[str, Any],
    ip: str | None,
    user_agent: str | None,
) -> WebhookOutcome:
    """Hand one directional signal to the signal engine and audit the outcome.

    Three outcomes, and the difference between them is the point:

    accepted        an order was placed
    accepted no-op  the signal was understood and correctly did nothing
    refused         the signal contradicts how the strategy is configured

    A no-op is audited as ``ok`` and answered 200, because the sender did
    nothing wrong and a failure would invite a retry it must not make.
    """
    from services.strategy_module import signals as signal_mode  # noqa: PLC0415

    leg_id = payload.get("leg_id")
    symbol = payload.get("symbol")
    exchange = payload.get("exchange")
    # Signal handling may synchronously replay a sandbox fill and remove every
    # scoped session on this thread. The webhook audit needs only the stable
    # scalar identity after that boundary.
    strategy_id = int(strategy.id)

    try:
        result = signal_mode.handle_signal(
            strategy, action, leg_id=leg_id, symbol=symbol, exchange=exchange
        )
    except Exception as exc:
        logger.exception("Signal engine failed on %s for strategy %s", action, strategy_id)
        event_id = _audit(
            "rejected_engine_error",
            strategy_id=strategy_id,
            action=action,
            payload=safe_payload,
            ip=ip,
            user_agent=user_agent,
            error=str(exc) or exc.__class__.__name__,
        )
        return _outcome(
            "rejected_engine_error",
            "The engine could not act on the signal",
            strategy_id=strategy_id,
            webhook_event_id=event_id,
        )

    if not result.ok:
        # A configuration mismatch: the wrong direction for this strategy, the
        # wrong side for this leg, or a leg the signal does not name.
        event_id = _audit(
            "rejected_invalid_action",
            strategy_id=strategy_id,
            action=action,
            payload=safe_payload,
            ip=ip,
            user_agent=user_agent,
            error=result.error,
        )
        return _outcome(
            "rejected_invalid_action",
            result.error or "The signal was refused",
            strategy_id=strategy_id,
            webhook_event_id=event_id,
        )

    event_id = _audit(
        "ok",
        strategy_id=strategy_id,
        action=action,
        payload=safe_payload,
        ip=ip,
        user_agent=user_agent,
        error=None,
    )
    message = f"Signal accepted ({result.note})" if result.note else "Signal accepted"
    return _outcome(
        "ok",
        message,
        ok=True,
        strategy_id=strategy_id,
        run_id=result.run_id,
        webhook_event_id=event_id,
    )


def _dispatch(
    *,
    strategy: Any,
    action: str,
    mode: str | None,
    key: tuple[Any, ...],
    event_id: int | None,
    safe_payload: dict[str, Any],
    ip: str | None,
    user_agent: str | None,
    engine: WebhookEngine | None,
) -> WebhookOutcome:
    """Hand an accepted signal to the engine and report what it did."""
    strategy_id = strategy.id
    was_live = strategy.status != "stopped"

    try:
        target = engine if engine is not None else _default_engine()
        if action == "start":
            raw = target.start_run(
                strategy,
                mode,
                trigger_source="webhook",
                webhook_event_id=event_id,
            )
        else:
            raw = target.stop_run(
                strategy,
                stop_reason="manual",
                trigger_source="webhook",
                webhook_event_id=event_id,
            )
        outcome = _coerce_engine_result(raw)
    except Exception as exc:
        logger.exception("Engine failed on %s for strategy %s", action, strategy_id)
        outcome = EngineResult(ok=False, error=str(exc) or exc.__class__.__name__)

    if not outcome.ok:
        # Release the claim so the sender's retry is not swallowed as a
        # duplicate of a delivery that never did anything.
        with _cache_lock:
            _dedupe.pop(key, None)
        error_id = _audit(
            "rejected_engine_error",
            strategy_id=strategy_id,
            action=action,
            mode=mode,
            payload=safe_payload,
            ip=ip,
            user_agent=user_agent,
            error=outcome.error or "The engine could not act on the signal",
        )
        return _outcome(
            "rejected_engine_error",
            outcome.error or "The engine could not act on the signal",
            strategy_id=strategy_id,
            run_id=outcome.run_id,
            webhook_event_id=error_id,
            stop_pending=outcome.stop_pending,
            exits=outcome.exits,
        )

    if action == "stop" and was_live and not outcome.stop_pending:
        # Only a stop that stopped something arms the window. A stop against an
        # already-stopped strategy is a no-op, and letting it block the next
        # start would turn a stray alert into an outage.
        note_run_stopped(strategy_id)

    logger.info(
        "Webhook accepted: %s%s on strategy %s (run %s)",
        action,
        f" in {mode}" if mode else "",
        strategy_id,
        outcome.run_id,
    )
    return _outcome(
        "ok",
        f"Strategy {action} accepted",
        ok=True,
        strategy_id=strategy_id,
        run_id=outcome.run_id,
        webhook_event_id=event_id,
        stop_pending=outcome.stop_pending,
        exits=outcome.exits,
    )
