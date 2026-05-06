"""Account-level RMS — guards above strategy-level RMS.

Where strategy-level RMS protects ONE strategy from ONE bad run, account
RMS protects you from N strategies all losing simultaneously. Single-user
platform, so "account" = the OpenAlgo user_id.

Caps (all configurable via /strategy/api/v2/account/risk_config):
  max_concurrent_runs            — how many runs may be active at once
                                    across ALL strategies
  max_daily_loss_abs              — abs ₹ realized loss across CLOSED live runs;
                                    once breached, account locks
  cooldown_after_loss_minutes     — after a losing run closes, refuse new
                                    runs for this many minutes
  min_seconds_between_runs        — debounce per strategy
  max_runs_per_strategy_per_day   — per-strategy daily run cap
  auto_clear_at                   — optional 'HH:MM' IST; lockout self-clears
                                    at this time next trading day
                                    (still requires manual clear by default)

Lockout state:
  account_risk_config.is_locked_out (bool)
  account_risk_config.lockout_reason  ('DAILY_LOSS_CAP', 'COOLDOWN', 'MANUAL')
  account_risk_config.lockout_until    (UTC datetime; NULL = manual-only clear)

Lifecycle hooks (subscribers/__init__.py wires these):
  StrategyStateChangedEvent → on_state_changed
    new_state == 'IN_TRADE'  → active_run_count++
    new_state in TERMINAL    → active_run_count-- + accumulate realized_pnl
                               + check daily cap → lock if breached
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional, Tuple

from sqlalchemy import desc, func

from database.strategy_v2_db import (
    AccountRiskConfig,
    AccountState,
    StrategyRun,
    StrategyV2,
    db_session,
)
from events.account_events import AccountLockedEvent, AccountUnlockedEvent
from utils.event_bus import bus
from utils.ist_time import IST, now_utc, to_epoch_ms
from utils.logging import get_logger

logger = get_logger(__name__)


# Terminal states that decrement active_run_count + accumulate P&L.
_TERMINAL_STATES = (
    "CLOSED", "EXIT_FAILED", "ERRORED", "STOPPED", "ENTRY_FAILED",
)


# ---------------------------------------------------------------------------
# State accessors
# ---------------------------------------------------------------------------


def get_or_create_config(user_id: str) -> AccountRiskConfig:
    """Lazy-create the account_risk_config row with safe defaults.

    Defaults are conservative: max_concurrent_runs=5, no daily loss cap (None
    means "unlimited" — user must opt in).
    """
    cfg = (
        db_session.query(AccountRiskConfig)
        .filter(AccountRiskConfig.user_id == user_id)
        .first()
    )
    if cfg is None:
        cfg = AccountRiskConfig(user_id=user_id)
        db_session.add(cfg)
        db_session.commit()
    return cfg


def get_or_create_state(user_id: str) -> AccountState:
    state = (
        db_session.query(AccountState)
        .filter(AccountState.user_id == user_id)
        .first()
    )
    if state is None:
        state = AccountState(user_id=user_id)
        db_session.add(state)
        db_session.commit()
    return state


# ---------------------------------------------------------------------------
# Lock / unlock
# ---------------------------------------------------------------------------


def lock_account(
    user_id: str,
    *,
    reason: str,
    cumulative_loss: float = 0.0,
    until: Optional[datetime] = None,
) -> None:
    """Engage the account lockout. Idempotent — re-locking with a new reason
    just updates the row and emits a fresh AccountLockedEvent."""
    cfg = get_or_create_config(user_id)
    cfg.is_locked_out = True
    cfg.lockout_reason = reason
    cfg.lockout_until = until
    db_session.commit()

    until_ts = to_epoch_ms(until) if until else 0
    bus.publish(
        AccountLockedEvent(
            user_id=user_id,
            reason=reason,
            until_ts_utc=until_ts,
            cumulative_loss=cumulative_loss,
        )
    )
    logger.warning(
        "account_rms: LOCKED user=%s reason=%s cum_loss=%.2f until=%s",
        user_id, reason, cumulative_loss, until,
    )


def unlock_account(user_id: str, *, cleared_by: str = "manual") -> None:
    cfg = get_or_create_config(user_id)
    if not cfg.is_locked_out:
        return
    cfg.is_locked_out = False
    cfg.lockout_reason = None
    cfg.lockout_until = None
    db_session.commit()

    bus.publish(AccountUnlockedEvent(user_id=user_id, cleared_by=cleared_by))
    logger.info("account_rms: UNLOCKED user=%s by=%s", user_id, cleared_by)


def is_locked_now(cfg: AccountRiskConfig) -> bool:
    """True if the account is locked AND the lockout hasn't auto-expired.

    auto-expiry: if lockout_until is set and now > lockout_until, the lock
    self-clears (we still flip the flag to False on read so subsequent
    queries see the new state — eventual consistency).
    """
    if not cfg.is_locked_out:
        return False
    if cfg.lockout_until is None:
        return True
    until = cfg.lockout_until
    # Make `until` timezone-aware (DB stores UTC datetime; SQLAlchemy may
    # return naive on SQLite).
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    if now_utc() >= until:
        # Auto-clear stale lockout.
        cfg.is_locked_out = False
        cfg.lockout_reason = None
        cfg.lockout_until = None
        try:
            db_session.commit()
            # Publish the unlock event so the audit chain reflects the
            # state change. Without this, an operator inspecting the
            # audit log sees a lock event with no matching unlock and
            # has to infer that the auto-clear fired. The event is also
            # what wakes the React UI's lockout banner so it disappears
            # without a page reload.
            try:
                from utils.event_bus import bus  # local import — avoid cycle
                bus.publish(
                    AccountUnlockedEvent(user_id=cfg.user_id, cleared_by="auto_expiry")
                )
            except Exception:
                logger.exception("account_rms: failed to publish auto-unlock event")
        except Exception:
            db_session.rollback()
        return False
    return True


# ---------------------------------------------------------------------------
# Preflight — gates new runs at webhook ingestion
# ---------------------------------------------------------------------------


def _today_start_utc() -> datetime:
    """Start of TODAY in IST, returned as UTC. Used for "runs today" /
    "loss today" windows. India has no DST so this is unambiguous."""
    now_ist = now_utc().astimezone(IST)
    midnight_ist = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight_ist.astimezone(timezone.utc)


def preflight_check(user_id: str, strategy_id: int) -> Tuple[bool, str]:
    """Called from ingestion_service.handle_webhook BEFORE creating a run.

    Returns (allowed, reason).
      allowed=True   — proceed
      allowed=False  — reason explains; ingestion returns 403/409/429 with it.

    Order of checks (cheapest first; reasons map to ingestion HTTP codes):
      1. is_locked_out                    → 429 ACCOUNT_LOCKED
      2. max_concurrent_runs              → 429 MAX_CONCURRENT_REACHED
      3. max_daily_loss_abs               → 429 DAILY_LOSS_CAP
      4. cooldown_after_loss              → 429 COOLDOWN
      5. min_seconds_between_runs         → 429 DEBOUNCE
      6. max_runs_per_strategy_per_day    → 429 STRATEGY_DAILY_CAP
    """
    cfg = get_or_create_config(user_id)
    state = get_or_create_state(user_id)

    # 1. Lockout
    if is_locked_now(cfg):
        return False, f"Account locked: {cfg.lockout_reason or 'unknown'}"

    # 2. Concurrent run cap
    if cfg.max_concurrent_runs and state.active_run_count >= cfg.max_concurrent_runs:
        return False, (
            f"max_concurrent_runs ({cfg.max_concurrent_runs}) reached — "
            f"current active runs: {state.active_run_count}"
        )

    # 3. Daily loss cap (live mode only — sandbox is virtual and shouldn't gate)
    if cfg.max_daily_loss_abs is not None:
        cap = abs(float(cfg.max_daily_loss_abs))
        loss_today = abs(min(0.0, float(state.realized_pnl_today_live or 0)))
        if loss_today >= cap:
            return False, (
                f"Daily loss cap reached: ₹{loss_today:.2f} >= ₹{cap:.2f}"
            )

    # 4. Cooldown after a losing run (only checked if cooldown configured)
    if cfg.cooldown_after_loss_minutes and cfg.cooldown_after_loss_minutes > 0:
        last_loss_close = (
            db_session.query(StrategyRun.exited_at)
            .join(StrategyV2, StrategyRun.strategy_id == StrategyV2.id)
            .filter(
                StrategyV2.user_id == user_id,
                StrategyRun.state == "CLOSED",
                StrategyRun.mode == "live",
                StrategyRun.realized_pnl < 0,
                StrategyRun.exited_at >= _today_start_utc(),
            )
            .order_by(desc(StrategyRun.exited_at))
            .first()
        )
        if last_loss_close and last_loss_close[0] is not None:
            exited_at = last_loss_close[0]
            if exited_at.tzinfo is None:
                exited_at = exited_at.replace(tzinfo=timezone.utc)
            elapsed = (now_utc() - exited_at).total_seconds()
            cooldown_secs = cfg.cooldown_after_loss_minutes * 60
            if elapsed < cooldown_secs:
                remaining = int(cooldown_secs - elapsed)
                return False, (
                    f"Post-loss cooldown active — try again in {remaining}s"
                )

    # 5. Per-strategy debounce (last run of THIS strategy, not user-wide)
    if cfg.min_seconds_between_runs and cfg.min_seconds_between_runs > 0:
        last_run = (
            db_session.query(StrategyRun.triggered_at)
            .filter(StrategyRun.strategy_id == strategy_id)
            .order_by(desc(StrategyRun.triggered_at))
            .first()
        )
        if last_run and last_run[0] is not None:
            triggered_at = last_run[0]
            if triggered_at.tzinfo is None:
                triggered_at = triggered_at.replace(tzinfo=timezone.utc)
            elapsed = (now_utc() - triggered_at).total_seconds()
            if elapsed < cfg.min_seconds_between_runs:
                remaining = int(cfg.min_seconds_between_runs - elapsed)
                return False, (
                    f"Debounce active — wait {remaining}s before next signal"
                )

    # 6. Per-strategy daily run cap
    if cfg.max_runs_per_strategy_per_day:
        runs_today = (
            db_session.query(func.count(StrategyRun.id))
            .filter(
                StrategyRun.strategy_id == strategy_id,
                StrategyRun.triggered_at >= _today_start_utc(),
            )
            .scalar()
            or 0
        )
        if runs_today >= cfg.max_runs_per_strategy_per_day:
            return False, (
                f"Strategy run cap reached: {runs_today} runs today "
                f"(max {cfg.max_runs_per_strategy_per_day})"
            )

    return True, ""


# ---------------------------------------------------------------------------
# Lifecycle hook — subscribed to strategy.state_changed
# ---------------------------------------------------------------------------


def on_state_changed(event) -> None:
    """Maintain active_run_count + realized_pnl_today_live/sandbox.

    IN_TRADE (entered)              → active_run_count++
    Terminal (CLOSED/etc.)          → active_run_count-- AND
                                       realized_pnl accumulates
    On terminal with loss tipping over the daily cap → lock_account.
    """
    new_state = getattr(event, "new_state", "")
    run_id = getattr(event, "run_id", 0) or 0
    if not run_id:
        return

    try:
        run = db_session.query(StrategyRun).filter(StrategyRun.id == run_id).first()
        if run is None:
            return
        strategy = (
            db_session.query(StrategyV2)
            .filter(StrategyV2.id == run.strategy_id)
            .first()
        )
        if strategy is None:
            return
        user_id = strategy.user_id

        state = get_or_create_state(user_id)

        if new_state == "IN_TRADE":
            state.active_run_count = (state.active_run_count or 0) + 1
            db_session.commit()

        elif new_state in _TERMINAL_STATES:
            # Decrement active count (clamp to 0 for defensive safety).
            state.active_run_count = max(0, (state.active_run_count or 0) - 1)

            # Accumulate realized P&L into the right bucket.
            realized = float(run.realized_pnl or 0)
            if run.mode == "sandbox":
                state.realized_pnl_today_sandbox = (
                    Decimal(str(state.realized_pnl_today_sandbox or 0))
                    + Decimal(str(realized))
                )
            else:
                state.realized_pnl_today_live = (
                    Decimal(str(state.realized_pnl_today_live or 0))
                    + Decimal(str(realized))
                )
            db_session.commit()

            # Check daily-loss cap (live mode only)
            if run.mode == "live":
                _maybe_lock_on_loss(user_id, realized)
    except Exception:
        db_session.rollback()
        logger.exception("account_rms.on_state_changed failed for run_id=%s", run_id)
    finally:
        db_session.remove()


def _maybe_lock_on_loss(user_id: str, this_run_realized: float) -> None:
    """If today's cumulative live realized P&L is now <= -cap, lock."""
    cfg = get_or_create_config(user_id)
    if cfg.max_daily_loss_abs is None or cfg.max_daily_loss_abs <= 0:
        return
    if cfg.is_locked_out:
        return  # already locked

    state = get_or_create_state(user_id)
    cum = float(state.realized_pnl_today_live or 0)
    cap = abs(float(cfg.max_daily_loss_abs))
    if cum <= -cap:
        # Compute lockout_until from auto_clear_at if set, else NULL (manual).
        until = _compute_auto_clear(cfg)
        lock_account(
            user_id,
            reason="DAILY_LOSS_CAP",
            cumulative_loss=cum,
            until=until,
        )


def _compute_auto_clear(cfg: AccountRiskConfig) -> Optional[datetime]:
    """If cfg.auto_clear_at is 'HH:MM', compute the next IST occurrence as
    a UTC datetime. Otherwise None (manual unlock required)."""
    raw = (cfg.auto_clear_at or "").strip()
    if not raw or ":" not in raw:
        return None
    try:
        hh, mm = raw.split(":")
        hour = int(hh)
        minute = int(mm)
    except ValueError:
        return None

    now_ist = now_utc().astimezone(IST)
    candidate = now_ist.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now_ist:
        candidate = candidate + timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def on_account_unlock_request(user_id: str, *, cleared_by: str = "manual") -> bool:
    """Public unlock — called by the REST endpoint."""
    unlock_account(user_id, cleared_by=cleared_by)
    return True
