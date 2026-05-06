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
from services.strategy.state_machine import has_active_run, transition_run
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

    # 7. Strip signing fields before passing to engine
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

    # 8. Per-strategy duplicate-active-run guard (cheap; before account RMS)
    if has_active_run(strategy.id):
        return _reject(
            strategy=strategy, webhook_id=webhook_id,
            reason="Strategy already has an active run",
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

    # 9. Publish signal received & create run
    bus.publish(
        StrategySignalReceivedEvent(
            strategy_id=strategy.id,
            webhook_id=webhook_id,
            payload=body,
            source_ip=source_ip,
            signing_method=method,
        )
    )

    # Resolve API key for the strategy's user — broker adapters need this.
    api_key = get_api_key_for_tradingview(strategy.user_id)
    if not api_key:
        return _reject(
            strategy=strategy, webhook_id=webhook_id,
            reason="No active broker session for strategy owner",
            code="NO_BROKER_SESSION",
            status=503, source_ip=source_ip,
        )

    # 10-13: handed off to the engine (run + entry orchestration).
    return _start_run(strategy=strategy, body=body, api_key=api_key, source_ip=source_ip)


# -----------------------------------------------------------------------------
# Run lifecycle: ARMED → ENTERING → execute_entry handles → IN_TRADE
# -----------------------------------------------------------------------------


def _start_run(
    *,
    strategy: StrategyV2,
    body: dict,
    api_key: str,
    source_ip: str,
) -> IngestResult:
    """Create the run row, resolve legs, place entries. Caller already
    validated everything — we only fail on broker / DB / engine issues.
    """
    # Create ARMED run row
    run = StrategyRun(
        strategy_id=strategy.id,
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

    # Resolve legs (cache symbol / tick_size / lot_size on each leg row)
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
