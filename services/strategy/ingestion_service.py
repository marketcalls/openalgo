"""Webhook ingestion — the entry point for external signals.

Pipeline (per plan §8.4.6 + §6.3):

  1. Lookup strategy by webhook_id
  2. Adaptive ban check (per webhook_id, in-memory tracker)
  3. IP allowlist check
  4. JSON parse
  5. Signature verification (BODY_SECRET / HMAC_SHA256 / BOTH / NONE)
  6. Replay window check
  7. Strip signing fields from payload
  8. Account-level preflight (active-run guard, account locked, daily caps)
  9. Create strategy_run row in ARMED state
 10. Publish StrategySignalReceivedEvent
 11. Transition ARMED → ENTERING
 12. Resolve every leg (leg_resolver_service)
 13. Place entry orders via execution_service (which handles ENTERING → IN_TRADE)

Every rejection writes a SIGNAL_REJECTED event with the reason for audit.
The first 5-7 steps are pure verification — they fire BEFORE any state
change so a hostile request never produces a strategy_run row.

Account-level RMS is delegated to a stub function for Phase 1 (ships full
in Phase 4.5). Currently it only does the duplicate-active-run guard.
"""

from __future__ import annotations

import json
import secrets as _secrets
from datetime import datetime, timezone
from typing import Any, Optional, Tuple

from database.auth_db import get_api_key_for_tradingview
from database.strategy_v2_db import StrategyRun, StrategyV2, db_session
from events.strategy_events import (
    StrategyRunStartedEvent,
    StrategySignalReceivedEvent,
    StrategySignalRejectedEvent,
    WebhookBannedEvent,
)
from services.strategy import leg_resolver_service
from services.strategy.broker_adapter_impls import get_adapter
from services.strategy.execution_service import execute_entry
from services.strategy.state_machine import (
    find_active_run,
    has_active_run,
    transition_run,
)
from utils.event_bus import bus
from utils.logging import get_logger
from utils.webhook_guard import (
    DEFAULT_TRACKER,
    parse_allowlist,
    request_ip_allowed,
    verify_body_secret,
    verify_hmac,
    verify_replay,
)

logger = get_logger(__name__)


# Result triple — (http_status, response_dict). Caller turns into Flask response.
IngestResult = Tuple[int, dict]


# -----------------------------------------------------------------------------
# Reject helpers
# -----------------------------------------------------------------------------


def _reject(
    *,
    strategy: Optional[StrategyV2],
    webhook_id: str,
    reason: str,
    code: str,
    status: int,
    source_ip: str = "",
    extra: Optional[dict] = None,
) -> IngestResult:
    """Publish SignalRejectedEvent and return the JSON response."""
    bus.publish(
        StrategySignalRejectedEvent(
            strategy_id=getattr(strategy, "id", 0) or 0,
            webhook_id=webhook_id or "",
            reason=reason,
            source_ip=source_ip,
        )
    )
    body = {"status": "error", "code": code, "message": reason}
    if extra:
        body.update(extra)
    return status, body


def _record_signature_failure(strategy_id: int, webhook_id: str, source_ip: str) -> None:
    """Bump the adaptive-ban counter; emit WebhookBannedEvent if newly banned."""
    newly_banned, _failures = DEFAULT_TRACKER.record_failure(webhook_id)
    if newly_banned:
        bus.publish(
            WebhookBannedEvent(
                strategy_id=strategy_id,
                webhook_id=webhook_id,
                failures=DEFAULT_TRACKER.failure_threshold,
                ban_duration_seconds=DEFAULT_TRACKER.ban_seconds,
                source_ip=source_ip,
            )
        )


# -----------------------------------------------------------------------------
# Main entry point
# -----------------------------------------------------------------------------


def handle_webhook(
    *,
    webhook_id: str,
    raw_body: bytes,
    headers: dict,
    request,
    dry_run: bool = False,
) -> IngestResult:
    """Top-level webhook handler. Called from blueprints/strategy.py route.

    Args:
        webhook_id:  UUID from the URL path.
        raw_body:    request body as bytes (BEFORE JSON parse — required for HMAC).
        headers:     dict of request headers (we only need X-OpenAlgo-Signature).
        request:     Flask request object — needed for client IP resolution.
        dry_run:     if True, perform all validation but do NOT create a run
                     or place orders. Used by /strategy/<id>/webhook/test.

    Returns: (http_status, response_body_dict).
    """
    # Use the project's canonical client-IP resolver so audit-log
    # source_ip matches what the IP allowlist sees. Both gate on
    # TRUST_PROXY_HEADERS — same source of truth as login rate-limit
    # and ban-list. See utils/ip_helper.py.
    if request is not None:
        try:
            from utils.ip_helper import get_real_ip
            source_ip = get_real_ip() or ""
        except Exception:
            source_ip = request.remote_addr or ""
    else:
        source_ip = ""

    # 1. Lookup
    strategy = (
        db_session.query(StrategyV2)
        .filter(StrategyV2.webhook_id == webhook_id)
        .first()
    )
    if not strategy:
        # Don't disclose strategy existence — return 404 generically.
        return 404, {"status": "error", "code": "UNKNOWN_WEBHOOK"}

    if not strategy.is_active and not dry_run:
        return _reject(
            strategy=strategy, webhook_id=webhook_id,
            reason="Strategy is disabled", code="STRATEGY_DISABLED",
            status=403, source_ip=source_ip,
        )

    # 2. Adaptive ban
    banned, secs_remaining = DEFAULT_TRACKER.is_banned(webhook_id)
    if banned:
        return _reject(
            strategy=strategy, webhook_id=webhook_id,
            reason=f"Webhook temporarily banned for {int(secs_remaining)}s due to repeated signature failures",
            code="WEBHOOK_BANNED",
            status=429, source_ip=source_ip,
            extra={"retry_after_seconds": int(secs_remaining)},
        )

    # 3. IP allowlist
    if not request_ip_allowed(request, strategy.webhook_ip_allowlist):
        return _reject(
            strategy=strategy, webhook_id=webhook_id,
            reason="Source IP not in allowlist", code="IP_NOT_ALLOWED",
            status=403, source_ip=source_ip,
        )

    # 4. JSON parse
    try:
        body = json.loads(raw_body) if raw_body else {}
    except (TypeError, ValueError):
        return _reject(
            strategy=strategy, webhook_id=webhook_id,
            reason="Body is not valid JSON", code="BAD_JSON",
            status=400, source_ip=source_ip,
        )
    if not isinstance(body, dict):
        return _reject(
            strategy=strategy, webhook_id=webhook_id,
            reason="Body must be a JSON object", code="BAD_JSON",
            status=400, source_ip=source_ip,
        )

    # 5. Signature
    method = strategy.webhook_signing_method or "NONE"
    sig_ok = True
    if method == "BODY_SECRET":
        sig_ok = verify_body_secret(body, strategy.webhook_secret)
    elif method == "HMAC_SHA256":
        sig_ok = verify_hmac(
            raw_body,
            headers.get("X-OpenAlgo-Signature"),
            strategy.webhook_hmac_key,
        )
    elif method == "BOTH":
        sig_ok = verify_body_secret(body, strategy.webhook_secret) or verify_hmac(
            raw_body,
            headers.get("X-OpenAlgo-Signature"),
            strategy.webhook_hmac_key,
        )
    # NONE → URL-only secret; sig_ok stays True.

    if not sig_ok:
        _record_signature_failure(strategy.id, webhook_id, source_ip)
        return _reject(
            strategy=strategy, webhook_id=webhook_id,
            reason=f"Signature verification failed (method={method})",
            code="INVALID_SIGNATURE",
            status=403, source_ip=source_ip,
        )

    DEFAULT_TRACKER.record_success(webhook_id)

    # 6. Replay window
    ok, msg = verify_replay(body, int(strategy.webhook_replay_window_seconds or 0))
    if not ok:
        return _reject(
            strategy=strategy, webhook_id=webhook_id,
            reason=msg, code="REPLAY_PROTECTION",
            status=403, source_ip=source_ip,
        )

    # 7. Strip signing fields before passing to engine.
    #    Both the new short name (`secret`) and the legacy long name
    #    (`webhook_secret`) are accepted by verify_body_secret; pop both
    #    so neither ends up in the audit log payload.
    body.pop("secret", None)
    body.pop("webhook_secret", None)
    body.pop("ts", None)

    if dry_run:
        return 200, {
            "status": "success",
            "mode": "dry_run",
            "message": "Webhook validated successfully — no order placed",
            "signing_method": method,
            "strategy_id": strategy.id,
        }

    # 8. Publish signal_received — the webhook passed signing so the
    # signal "arrived" from the operator's perspective. Downstream
    # routing or dispatch failures still log REJECT events but the
    # received-event represents "valid signed signal" semantics.
    bus.publish(
        StrategySignalReceivedEvent(
            strategy_id=strategy.id,
            webhook_id=webhook_id,
            payload=body,
            source_ip=source_ip,
            signing_method=method,
        )
    )

    # 8b. Phase 13 — segment-aware routing. CASH strategies route per-
    # symbol (each leg can have its own active run); F&O strategies are
    # pack-style (one active run per strategy). Resolve (intent,
    # target_leg) so the active-run check is correctly scoped and we
    # can dispatch entry-vs-exit later without re-deriving from the body.
    routed = _route_for_segment(strategy, body)
    if isinstance(routed, tuple) and routed[0] == "REJECT":
        _, msg, code, http_status = routed
        return _reject(
            strategy=strategy, webhook_id=webhook_id,
            reason=msg, code=code, status=http_status, source_ip=source_ip,
        )
    intent, target_leg = routed  # ("entry"|"exit", StrategyLeg|None)

    target_leg_id = target_leg.id if target_leg is not None else None
    if intent == "entry" and has_active_run(strategy.id, target_leg_id):
        return _reject(
            strategy=strategy, webhook_id=webhook_id,
            reason=(
                "Already has an active run for this symbol"
                if target_leg_id is not None
                else "Strategy already has an active run"
            ),
            code="ALREADY_RUNNING",
            status=409, source_ip=source_ip,
        )

    # 8b. Account-level RMS preflight (lockout, concurrent cap, daily loss
    #     cap, cooldown, debounce, per-strategy daily cap). See plan §9.1.
    from services.strategy.account_rms import preflight_check as _preflight

    allowed, reason = _preflight(strategy.user_id, strategy.id)
    if not allowed:
        return _reject(
            strategy=strategy, webhook_id=webhook_id,
            reason=reason,
            code="ACCOUNT_PREFLIGHT_FAILED",
            status=429, source_ip=source_ip,
        )

    # 9. Resolve API key for the strategy's user — broker adapters need this.
    api_key = get_api_key_for_tradingview(strategy.user_id)
    if not api_key:
        return _reject(
            strategy=strategy, webhook_id=webhook_id,
            reason="No active broker session for strategy owner",
            code="NO_BROKER_SESSION",
            status=503, source_ip=source_ip,
        )

    # 10. Dispatch to entry or exit based on the resolved intent.
    if intent == "exit":
        return _dispatch_exit(
            strategy=strategy, target_leg=target_leg,
            api_key=api_key, source_ip=source_ip,
        )
    return _start_run(
        strategy=strategy, body=body, api_key=api_key, source_ip=source_ip,
        target_leg=target_leg,
    )


# -----------------------------------------------------------------------------
# Phase 13 — segment-aware routing
# -----------------------------------------------------------------------------


def _route_for_segment(strategy: StrategyV2, body: dict):
    """Decide whether this webhook is an entry or exit, and pick the
    target leg (if any) for CASH per-symbol routing.

    Returns either:
      ("entry"|"exit", StrategyLeg | None)
      ("REJECT", reason, code, http_status)

    Rules:
      F&O strategies (INDEX_FO, STOCK_FO):
        - Always entry; pack-style. target_leg = None (run is strategy-
          level; all legs fire together via execute_entry).
      CASH strategies:
        - Body MUST include `symbol` matching one of the strategy's legs
          (case-insensitive on symbol_cash). 404 otherwise.
        - Body MUST include `action` ∈ {BUY, SELL}.
        - Mode + action + position_size dictate intent:
            LONG  + BUY  -> entry long
            LONG  + SELL -> exit long
            SHORT + SELL -> entry short
            SHORT + BUY  -> exit short
            BOTH  + position_size>0 -> entry (BUY=long, SELL=short)
            BOTH  + position_size=0 -> exit opposite-direction position
    """
    # Default to CASH when the attribute is missing (legacy rows / test
    # fixtures using SimpleNamespace shims).
    segment = getattr(strategy, "segment", None) or "CASH"
    if segment != "CASH":
        # F&O pack — symbol/action are not consulted; the strategy's
        # legs (with their pre-configured B/S) define the structure.
        return ("entry", None)

    raw_symbol = (body.get("symbol") or "").strip().upper()
    if not raw_symbol:
        return ("REJECT",
                "Cash webhook must include `symbol`",
                "MISSING_SYMBOL", 400)

    # Match the leg by symbol_cash (case-insensitive, stripped).
    target_leg = None
    for leg in strategy.legs:
        if leg.segment == "CASH" and (leg.symbol_cash or "").strip().upper() == raw_symbol:
            target_leg = leg
            break
    if target_leg is None:
        return ("REJECT",
                f"Symbol {raw_symbol!r} not configured on this strategy",
                "UNKNOWN_SYMBOL", 404)

    action = (body.get("action") or "").strip().upper()
    if action not in ("BUY", "SELL"):
        return ("REJECT",
                "`action` must be 'BUY' or 'SELL'",
                "BAD_ACTION", 400)

    trading_mode = (strategy.trading_mode or "LONG").upper()

    if trading_mode == "LONG":
        return ("entry" if action == "BUY" else "exit", target_leg)
    if trading_mode == "SHORT":
        return ("entry" if action == "SELL" else "exit", target_leg)

    # BOTH — position_size disambiguates open vs close.
    raw_size = body.get("position_size")
    try:
        position_size = int(raw_size) if raw_size is not None else None
    except (TypeError, ValueError):
        return ("REJECT",
                "`position_size` must be an integer when mode=BOTH",
                "BAD_POSITION_SIZE", 400)
    if position_size is None:
        return ("REJECT",
                "BOTH-mode webhook must include `position_size`",
                "MISSING_POSITION_SIZE", 400)
    if position_size > 0:
        return ("entry", target_leg)
    if position_size == 0:
        return ("exit", target_leg)
    return ("REJECT",
            "`position_size` must be >= 0",
            "BAD_POSITION_SIZE", 400)


def _dispatch_exit(
    *,
    strategy: StrategyV2,
    target_leg,
    api_key: str,
    source_ip: str,
) -> IngestResult:
    """Webhook arrived requesting an exit (e.g. LONG-mode + SELL). Find
    the active run for this (strategy, leg) and ask exit_service to
    flatten it. No-op (404) if there's no open position to close —
    surfaces TradingView misconfigurations instead of silently dropping.
    """
    target_leg_id = target_leg.id if target_leg is not None else None
    run_id = find_active_run(strategy.id, target_leg_id)
    if run_id is None:
        return _reject(
            strategy=strategy, webhook_id=strategy.webhook_id,
            reason=(
                "No active position to close for this symbol"
                if target_leg_id is not None
                else "No active run to close"
            ),
            code="NO_OPEN_POSITION",
            status=404, source_ip=source_ip,
        )
    # Lazy import to avoid a circular dep at module-load time.
    from services.strategy.exit_service import exit_strategy

    # exit_strategy takes only run_id + reason; it looks up the strategy
    # and api_key internally via the run row. The api_key arg here is
    # unused but kept on _dispatch_exit's signature so callers can stay
    # uniform with _start_run.
    _ = api_key
    success, summary = exit_strategy(
        run_id=run_id,
        reason="webhook_exit",
    )
    return (200 if success else 500), {
        "status": "success" if success else "error",
        "code": "EXIT_REQUESTED" if success else "EXIT_FAILED",
        "run_id": run_id,
        "summary": summary,
    }


# -----------------------------------------------------------------------------
# Run lifecycle: ARMED → ENTERING → execute_entry handles → IN_TRADE
# -----------------------------------------------------------------------------


def _start_run(
    *,
    strategy: StrategyV2,
    body: dict,
    api_key: str,
    source_ip: str,
    target_leg=None,
) -> IngestResult:
    """Create the run row, resolve legs, place entries. Caller already
    validated everything — we only fail on broker / DB / engine issues.

    Phase 13 — when `target_leg` is provided (CASH per-symbol routing),
    the run is pinned to that leg via run.leg_id and only that leg is
    fed through resolution + entry. F&O packs pass target_leg=None and
    every configured leg fires together.
    """
    # Create ARMED run row.
    run = StrategyRun(
        strategy_id=strategy.id,
        leg_id=target_leg.id if target_leg is not None else None,
        state="ARMED",
        mode=strategy.mode or "live",
        signal_payload=json.dumps(body, default=str),
        signal_source="webhook",
        triggered_at=datetime.now(timezone.utc),
    )
    try:
        db_session.add(run)
        db_session.commit()
    except Exception:
        db_session.rollback()
        # Could be the unique partial index on idx_strategy_runs_active firing —
        # treat as duplicate signal.
        return _reject(
            strategy=strategy, webhook_id=strategy.webhook_id,
            reason="Strategy already has an active run (race-protected)",
            code="ALREADY_RUNNING",
            status=409, source_ip=source_ip,
        )

    bus.publish(
        StrategyRunStartedEvent(
            strategy_id=strategy.id,
            run_id=run.id,
            mode=run.mode,
            signal_payload=body,
        )
    )

    # ARMED → ENTERING
    if not transition_run(
        run.id, expected_old="ARMED", new_state="ENTERING",
        reason="signal accepted", strategy_id=strategy.id,
    ):
        return 500, {"status": "error", "code": "STATE_RACE",
                     "message": "Failed to transition ARMED → ENTERING"}

    # Resolve legs (cache symbol / tick_size / lot_size on each leg row).
    # For CASH per-symbol routing, restrict to just the matched leg —
    # the run represents a single-symbol order, not the whole basket.
    if target_leg is not None:
        legs = [target_leg]
    else:
        legs = sorted(strategy.legs, key=lambda l: l.leg_index)
    if not legs:
        transition_run(
            run.id, expected_old="ENTERING", new_state="ENTRY_FAILED",
            reason="no legs configured", strategy_id=strategy.id,
        )
        return 400, {"status": "error", "code": "NO_LEGS",
                     "message": "Strategy has no legs configured"}

    ok, _, errors = leg_resolver_service.resolve_all(
        legs,
        underlying=strategy.underlying or "",
        underlying_exchange=strategy.underlying_exchange or "",
        api_key=api_key,
        strategy_id=strategy.id,
        run_id=run.id,
    )
    if not ok:
        transition_run(
            run.id, expected_old="ENTERING", new_state="ENTRY_FAILED",
            reason="leg resolution failed", strategy_id=strategy.id,
        )
        return 400, {"status": "error", "code": "LEG_RESOLUTION_FAILED",
                     "errors": errors}

    # Place entry orders via the right segment-routing service.
    adapter = get_adapter(run.mode, api_key)
    success, summary = execute_entry(
        strategy=strategy, run_id=run.id, legs=legs, adapter=adapter,
    )

    return (200 if success else 500), {
        "status": "success" if success else "error",
        "code": "RUN_STARTED" if success else "ENTRY_FAILED",
        "run_id": run.id,
        "summary": summary,
    }
