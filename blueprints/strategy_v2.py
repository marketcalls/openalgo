"""Strategy v2 REST API blueprint.

URL prefix: /strategy/api/v2
- Audit chain verifier
- Strategy CRUD + toggle
- Leg CRUD
- Webhook secret rotation + dry-run test endpoint

Phase 1 ships these. Subsequent phases add the run / orderbook / tradebook /
positionbook / events / risk-config endpoints.

Auth: existing OpenAlgo session is required for all endpoints. Webhooks
themselves (POST /strategy/webhook/<uuid>) are unauthenticated by URL secret
+ the signing layer in services/strategy/ingestion_service.py — those live
in the legacy /strategy blueprint.
"""

from __future__ import annotations

import json
import secrets as _secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

from flask import Blueprint, jsonify, request, session
from marshmallow import ValidationError

from database.strategy_v2_db import (
    AccountRiskConfig,
    AccountState,
    StrategyEvent,
    StrategyLeg,
    StrategyOrder,
    StrategyPosition,
    StrategyRiskConfig,
    StrategyRun,
    StrategyTrade,
    StrategyV2,
    db_session,
)
from events.strategy_events import WebhookSecretRotatedEvent
from restx_api.strategy_v2_schemas import (
    AccountRiskConfigSchema,
    LegSchema,
    RiskConfigSchema,
    StrategyCreateSchema,
    StrategyUpdateSchema,
    WebhookRotateSchema,
)
from services.strategy import serializers
from subscribers.strategy_audit_subscriber import verify_chain
from utils.event_bus import bus
from utils.logging import get_logger

logger = get_logger(__name__)

strategy_v2_bp = Blueprint("strategy_v2", __name__, url_prefix="/strategy/api/v2")


# ----------------------------------------------------------------------------
# Auth helper
# ----------------------------------------------------------------------------


def _current_user_id():
    """Return the logged-in user_id (mirrors the v1 pattern)."""
    return session.get("user")


def _require_login():
    """Return (user_id, error_response_or_none). Caller bails if error."""
    user = _current_user_id()
    if not user:
        return None, (jsonify({"status": "error", "code": "UNAUTHENTICATED"}), 401)
    return user, None


# ----------------------------------------------------------------------------
# Serializers
# ----------------------------------------------------------------------------


def _strategy_to_dict(s: StrategyV2, *, include_secrets: bool = False) -> dict:
    """Serialize a strategy row. Secrets only included on rotation responses
    (one-time display)."""
    d = {
        "id": s.id,
        "name": s.name,
        "webhook_id": s.webhook_id,
        "user_id": s.user_id,
        "platform": s.platform,
        # Phase 9 — segment + positional exit fields.
        "segment": s.segment or "CASH",
        "underlying": s.underlying,
        "underlying_exchange": s.underlying_exchange,
        "is_intraday": bool(s.is_intraday),
        "start_time": s.start_time,
        "end_time": s.end_time,
        "squareoff_time": s.squareoff_time,
        "exit_date": s.exit_date,
        "run_forever": bool(s.run_forever),
        "state": s.state,
        "is_active": bool(s.is_active),
        "mode": s.mode,
        "webhook_signing_method": s.webhook_signing_method,
        "webhook_replay_window_seconds": s.webhook_replay_window_seconds or 0,
        "webhook_ip_allowlist": json.loads(s.webhook_ip_allowlist) if s.webhook_ip_allowlist else [],
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }
    if include_secrets:
        d["webhook_secret"] = s.webhook_secret
        d["webhook_hmac_key"] = s.webhook_hmac_key
    return d


def _leg_to_dict(l: StrategyLeg) -> dict:
    return {
        "id": l.id,
        "leg_index": l.leg_index,
        "segment": l.segment,
        "position": l.position,
        "product": l.product,
        "symbol_cash": l.symbol_cash,
        "exchange_cash": l.exchange_cash,
        "qty": l.qty,
        "expiry_type": l.expiry_type,
        "lots": l.lots,
        "option_type": l.option_type,
        "strike_criteria": l.strike_criteria,
        "strike_value": float(l.strike_value) if l.strike_value is not None else None,
        "target_enabled": bool(l.target_enabled),
        "target_value": float(l.target_value) if l.target_value is not None else None,
        "target_unit": l.target_unit,
        "sl_enabled": bool(l.sl_enabled),
        "sl_value": float(l.sl_value) if l.sl_value is not None else None,
        "sl_unit": l.sl_unit,
        "trail_enabled": bool(l.trail_enabled),
        "trail_x": float(l.trail_x) if l.trail_x is not None else None,
        "trail_y": float(l.trail_y) if l.trail_y is not None else None,
        "trail_unit": l.trail_unit,
        "momentum_enabled": bool(l.momentum_enabled),
        "momentum_value": float(l.momentum_value) if l.momentum_value is not None else None,
        "momentum_unit": l.momentum_unit,
        "resolved_symbol": l.resolved_symbol,
        "resolved_exchange": l.resolved_exchange,
        "lot_size_cache": l.lot_size_cache,
        "tick_size_cache": float(l.tick_size_cache) if l.tick_size_cache is not None else None,
    }


# ----------------------------------------------------------------------------
# Strategy CRUD
# ----------------------------------------------------------------------------


_ACTIVE_RUN_STATES = ("ARMED", "ENTERING", "IN_TRADE", "EXITING")


def _strategy_live_snapshot(strategy_id: int) -> dict:
    """Compose a per-strategy live snapshot for the list page.

    Combines two sources:
      * The most recent ACTIVE run row (if any). The engine's in-memory
        registry holds fresh MTM via snapshot_run(); we prefer that over
        the persisted StrategyRun.peak_mtm because tick-rate updates only
        flush to DB at terminal states.
      * Today's realized P&L = sum(StrategyRun.realized_pnl) over runs
        that closed today in IST. Lets the operator see profit even when
        no run is currently active.

    Returned shape (matches the frontend's PnlTickPayload partials so the
    Socket.IO update path can patch the row):

        {
          "active_run_id": int | None,
          "active_state": str | None,
          "agg_mtm": float,        # 0.0 if no active run
          "peak_mtm": float,
          "drawdown": float,
          "realized_today": float, # sum of CLOSED runs today
        }
    """
    from datetime import datetime, time, timezone
    from zoneinfo import ZoneInfo

    snapshot = {
        "active_run_id": None,
        "active_state": None,
        "agg_mtm": 0.0,
        "peak_mtm": 0.0,
        "drawdown": 0.0,
        "realized_today": 0.0,
    }

    # Active run — there can only be one because of idx_strategy_runs_active.
    active = (
        db_session.query(StrategyRun)
        .filter(
            StrategyRun.strategy_id == strategy_id,
            StrategyRun.state.in_(_ACTIVE_RUN_STATES),
        )
        .order_by(StrategyRun.id.desc())
        .first()
    )
    if active is not None:
        snapshot["active_run_id"] = active.id
        snapshot["active_state"] = active.state
        # Try the engine first — fresher than the DB columns.
        try:
            from services.strategy.rms_engine import get_engine
            snap = get_engine().snapshot_run(active.id)
            if snap is not None:
                snapshot["agg_mtm"] = float(snap.get("agg_mtm") or 0)
                snapshot["peak_mtm"] = float(snap.get("peak_mtm") or 0)
                snapshot["drawdown"] = float(snap.get("drawdown") or 0)
            else:
                # Engine doesn't know about this run yet (eg ENTERING) —
                # fall back to the persisted columns (last flush).
                snapshot["peak_mtm"] = float(active.peak_mtm or 0)
                snapshot["drawdown"] = float(active.max_drawdown or 0)
        except Exception:
            logger.exception(
                "list_strategies: engine.snapshot_run failed for run=%s",
                active.id,
            )

    # Today's realized = sum of runs that exited within today (IST window).
    ist = ZoneInfo("Asia/Kolkata")
    now_ist = datetime.now(ist)
    midnight_ist = datetime.combine(now_ist.date(), time.min, tzinfo=ist)
    today_start_utc = midnight_ist.astimezone(timezone.utc)
    closed_today = (
        db_session.query(StrategyRun.realized_pnl)
        .filter(
            StrategyRun.strategy_id == strategy_id,
            StrategyRun.state == "CLOSED",
            StrategyRun.exited_at >= today_start_utc,
        )
        .all()
    )
    snapshot["realized_today"] = float(
        sum((r[0] or 0) for r in closed_today)
    )
    return snapshot


@strategy_v2_bp.route("/strategy", methods=["GET"])
def list_strategies():
    user, err = _require_login()
    if err:
        return err
    rows = (
        db_session.query(StrategyV2)
        .filter(StrategyV2.user_id == user)
        .order_by(StrategyV2.created_at.desc())
        .all()
    )
    out = []
    for s in rows:
        d = _strategy_to_dict(s)
        # Phase 9.2 — embed the live snapshot so the list page can render
        # P&L without a follow-up round-trip per row. Subsequent updates
        # come over Socket.IO via strategy_pnl_tick (room-scoped per id).
        d["live"] = _strategy_live_snapshot(s.id)
        out.append(d)
    return jsonify({"status": "success", "strategies": out}), 200


@strategy_v2_bp.route("/strategy/<int:strategy_id>", methods=["GET"])
def get_strategy(strategy_id: int):
    user, err = _require_login()
    if err:
        return err
    s = (
        db_session.query(StrategyV2)
        .filter(StrategyV2.id == strategy_id, StrategyV2.user_id == user)
        .first()
    )
    if not s:
        return jsonify({"status": "error", "code": "NOT_FOUND"}), 404
    legs = sorted(s.legs, key=lambda l: l.leg_index)
    return jsonify({
        "status": "success",
        "strategy": _strategy_to_dict(s),
        "legs": [_leg_to_dict(l) for l in legs],
    }), 200


def _make_webhook_secrets(method: str) -> tuple[str, str]:
    """Generate body-secret + HMAC key sized appropriately."""
    body_secret = _secrets.token_hex(16) if method in ("BODY_SECRET", "BOTH") else None
    hmac_key = _secrets.token_hex(32) if method in ("HMAC_SHA256", "BOTH") else None
    return body_secret, hmac_key


@strategy_v2_bp.route("/strategy", methods=["POST"])
def create_strategy():
    user, err = _require_login()
    if err:
        return err
    try:
        data = StrategyCreateSchema().load(request.get_json(silent=True) or {})
    except ValidationError as e:
        return jsonify({"status": "error", "code": "VALIDATION", "errors": e.messages}), 400

    method = data.get("webhook_signing_method", "NONE")
    body_secret, hmac_key = _make_webhook_secrets(method)

    # Phase 9 cross-field validation: positional strategies must specify
    # how they exit (a date or run-forever); intraday strategies must
    # specify end_time. We enforce here rather than in marshmallow so the
    # error message can name both fields together.
    is_intraday = data.get("is_intraday", True)
    if is_intraday:
        if not data.get("end_time"):
            return jsonify({"status": "error", "code": "VALIDATION",
                            "errors": {"end_time": "required for intraday"}}), 400
    else:
        if not data.get("exit_date") and not data.get("run_forever"):
            return jsonify({"status": "error", "code": "VALIDATION",
                            "errors": {"exit_date": "positional must set exit_date "
                                       "or run_forever=true"}}), 400

    s = StrategyV2(
        name=data["name"],
        webhook_id=str(uuid.uuid4()),
        user_id=user,
        platform=data.get("platform", "manual"),
        segment=data.get("segment", "CASH"),
        # Underlying is only meaningful for INDEX_FO strategies; CASH
        # strategies leave both null regardless of what was sent.
        underlying=data.get("underlying") if data.get("segment") == "INDEX_FO" else None,
        underlying_exchange=(
            data.get("underlying_exchange") if data.get("segment") == "INDEX_FO" else None
        ),
        is_intraday=is_intraday,
        start_time=data["start_time"],
        end_time=data.get("end_time"),
        squareoff_time=data.get("squareoff_time") if is_intraday else None,
        exit_date=data.get("exit_date") if not is_intraday else None,
        run_forever=bool(data.get("run_forever") and not is_intraday),
        state="DRAFT",
        is_active=False,
        mode=data.get("mode", "live"),
        webhook_signing_method=method,
        webhook_replay_window_seconds=data.get("webhook_replay_window_seconds", 0),
        webhook_ip_allowlist=(
            json.dumps(data["webhook_ip_allowlist"])
            if data.get("webhook_ip_allowlist")
            else None
        ),
    )
    s.webhook_secret = body_secret  # encrypted via descriptor
    s.webhook_hmac_key = hmac_key

    db_session.add(s)
    # Initialize an empty risk_config row
    db_session.flush()
    db_session.add(StrategyRiskConfig(strategy_id=s.id))
    db_session.commit()

    return jsonify({
        "status": "success",
        "strategy": _strategy_to_dict(s, include_secrets=True),
        "message": "Strategy created. Save the webhook_secret / webhook_hmac_key now — "
                   "they will not be displayed again.",
    }), 201


@strategy_v2_bp.route("/strategy/<int:strategy_id>", methods=["PUT"])
def update_strategy(strategy_id: int):
    user, err = _require_login()
    if err:
        return err
    s = (
        db_session.query(StrategyV2)
        .filter(StrategyV2.id == strategy_id, StrategyV2.user_id == user)
        .first()
    )
    if not s:
        return jsonify({"status": "error", "code": "NOT_FOUND"}), 404
    try:
        data = StrategyUpdateSchema().load(request.get_json(silent=True) or {})
    except ValidationError as e:
        return jsonify({"status": "error", "code": "VALIDATION", "errors": e.messages}), 400

    # Refuse to modify webhook signing method while is_active=True (avoids
    # mid-flight signature mismatches). Force a deactivate first.
    if "webhook_signing_method" in data and s.is_active:
        return jsonify({
            "status": "error", "code": "STRATEGY_ACTIVE",
            "message": "Disable the strategy before changing webhook_signing_method",
        }), 409

    for k, v in data.items():
        if k == "webhook_ip_allowlist":
            s.webhook_ip_allowlist = json.dumps(v) if v else None
        else:
            setattr(s, k, v)
    db_session.commit()
    return jsonify({"status": "success", "strategy": _strategy_to_dict(s)}), 200


@strategy_v2_bp.route("/strategy/<int:strategy_id>", methods=["DELETE"])
def delete_strategy(strategy_id: int):
    user, err = _require_login()
    if err:
        return err
    s = (
        db_session.query(StrategyV2)
        .filter(StrategyV2.id == strategy_id, StrategyV2.user_id == user)
        .first()
    )
    if not s:
        return jsonify({"status": "error", "code": "NOT_FOUND"}), 404
    if s.is_active:
        return jsonify({"status": "error", "code": "STRATEGY_ACTIVE",
                        "message": "Disable the strategy before deleting"}), 409
    db_session.delete(s)
    db_session.commit()
    return jsonify({"status": "success"}), 200


@strategy_v2_bp.route("/strategy/<int:strategy_id>/toggle", methods=["POST"])
def toggle_strategy(strategy_id: int):
    user, err = _require_login()
    if err:
        return err
    s = (
        db_session.query(StrategyV2)
        .filter(StrategyV2.id == strategy_id, StrategyV2.user_id == user)
        .first()
    )
    if not s:
        return jsonify({"status": "error", "code": "NOT_FOUND"}), 404
    s.is_active = not s.is_active
    # Keep state and is_active aligned. The state machine has 4 values:
    #   DRAFT     — never enabled; toggling to active arms it
    #   ARMED     — currently accepting webhooks
    #   DISABLED  — was active, user explicitly disabled it
    #   ARCHIVED  — terminal; toggle is blocked at the UI layer
    # Earlier versions only handled DRAFT->ARMED and ARMED->DISABLED, which
    # left re-enabling a previously-DISABLED strategy in a contradictory
    # state (is_active=True, state=DISABLED). Now: any "becoming active"
    # transition lands in ARMED; any "becoming inactive" lands in DISABLED.
    if s.is_active:
        if s.state in ("DRAFT", "DISABLED"):
            s.state = "ARMED"
    else:
        if s.state == "ARMED":
            s.state = "DISABLED"
    db_session.commit()

    # Squareoff scheduler — hook the strategy's intraday close-time job.
    try:
        from services.strategy import squareoff_scheduler

        if s.is_active:
            squareoff_scheduler.schedule_strategy(s.id)
        else:
            squareoff_scheduler.unschedule_strategy(s.id)
    except Exception:
        logger.exception("toggle_strategy: scheduler hook failed for id=%s", s.id)

    return jsonify({"status": "success", "is_active": s.is_active, "state": s.state}), 200


# ----------------------------------------------------------------------------
# Leg CRUD
# ----------------------------------------------------------------------------


def _validate_leg_payload(data: dict) -> tuple[bool, str]:
    """Cross-field constraints not expressible in marshmallow alone."""
    seg = data.get("segment")
    if seg == "CASH":
        if not data.get("symbol_cash") or not data.get("qty"):
            return False, "CASH leg requires symbol_cash and qty"
    elif seg == "FUT":
        if not data.get("expiry_type") or not data.get("lots"):
            return False, "FUT leg requires expiry_type and lots"
    elif seg == "OPT":
        if (not data.get("expiry_type") or not data.get("lots")
                or not data.get("option_type") or not data.get("strike_criteria")):
            return False, "OPT leg requires expiry_type, lots, option_type, strike_criteria"
    return True, ""


@strategy_v2_bp.route("/strategy/<int:strategy_id>/legs", methods=["POST"])
def add_leg(strategy_id: int):
    user, err = _require_login()
    if err:
        return err
    s = (
        db_session.query(StrategyV2)
        .filter(StrategyV2.id == strategy_id, StrategyV2.user_id == user)
        .first()
    )
    if not s:
        return jsonify({"status": "error", "code": "NOT_FOUND"}), 404
    try:
        data = LegSchema().load(request.get_json(silent=True) or {})
    except ValidationError as e:
        return jsonify({"status": "error", "code": "VALIDATION", "errors": e.messages}), 400
    ok, msg = _validate_leg_payload(data)
    if not ok:
        return jsonify({"status": "error", "code": "INVALID_LEG", "message": msg}), 400

    leg = StrategyLeg(strategy_id=s.id, **data)
    db_session.add(leg)
    db_session.commit()
    return jsonify({"status": "success", "leg": _leg_to_dict(leg)}), 201


@strategy_v2_bp.route("/strategy/<int:strategy_id>/legs/<int:leg_id>", methods=["PUT"])
def update_leg(strategy_id: int, leg_id: int):
    user, err = _require_login()
    if err:
        return err
    leg = (
        db_session.query(StrategyLeg)
        .join(StrategyV2)
        .filter(
            StrategyLeg.id == leg_id,
            StrategyLeg.strategy_id == strategy_id,
            StrategyV2.user_id == user,
        )
        .first()
    )
    if not leg:
        return jsonify({"status": "error", "code": "NOT_FOUND"}), 404
    try:
        data = LegSchema(partial=True).load(request.get_json(silent=True) or {})
    except ValidationError as e:
        return jsonify({"status": "error", "code": "VALIDATION", "errors": e.messages}), 400

    for k, v in data.items():
        setattr(leg, k, v)
    db_session.commit()
    return jsonify({"status": "success", "leg": _leg_to_dict(leg)}), 200


@strategy_v2_bp.route("/strategy/<int:strategy_id>/legs/<int:leg_id>", methods=["DELETE"])
def delete_leg(strategy_id: int, leg_id: int):
    user, err = _require_login()
    if err:
        return err
    leg = (
        db_session.query(StrategyLeg)
        .join(StrategyV2)
        .filter(
            StrategyLeg.id == leg_id,
            StrategyLeg.strategy_id == strategy_id,
            StrategyV2.user_id == user,
        )
        .first()
    )
    if not leg:
        return jsonify({"status": "error", "code": "NOT_FOUND"}), 404
    db_session.delete(leg)
    db_session.commit()
    return jsonify({"status": "success"}), 200


# ----------------------------------------------------------------------------
# Webhook actions: rotate + test
# ----------------------------------------------------------------------------


@strategy_v2_bp.route("/strategy/<int:strategy_id>/webhook/rotate", methods=["POST"])
def rotate_webhook_secrets(strategy_id: int):
    """Issue a new webhook_secret + webhook_hmac_key for the strategy.
    Requires `confirm: <strategy.name>` in the body — destructive action.
    """
    user, err = _require_login()
    if err:
        return err
    s = (
        db_session.query(StrategyV2)
        .filter(StrategyV2.id == strategy_id, StrategyV2.user_id == user)
        .first()
    )
    if not s:
        return jsonify({"status": "error", "code": "NOT_FOUND"}), 404
    try:
        data = WebhookRotateSchema().load(request.get_json(silent=True) or {})
    except ValidationError as e:
        return jsonify({"status": "error", "code": "VALIDATION", "errors": e.messages}), 400

    if data["confirm"] != s.name:
        return jsonify({
            "status": "error", "code": "CONFIRMATION_MISMATCH",
            "message": "confirm must match the strategy name exactly",
        }), 400

    body_secret, hmac_key = _make_webhook_secrets(s.webhook_signing_method or "NONE")
    s.webhook_secret = body_secret
    s.webhook_hmac_key = hmac_key
    db_session.commit()

    bus.publish(WebhookSecretRotatedEvent(
        strategy_id=s.id, method=s.webhook_signing_method or "NONE",
    ))

    return jsonify({
        "status": "success",
        "strategy": _strategy_to_dict(s, include_secrets=True),
        "message": "Secrets rotated. Save the new values now — they will not be displayed again.",
    }), 200


@strategy_v2_bp.route("/strategy/<int:strategy_id>/webhook/test", methods=["POST"])
def test_webhook(strategy_id: int):
    """Dry-run validation: feeds the request through the same pipeline as a
    real webhook (signature + replay + IP), but never creates a run or places
    orders. Lets users verify their TradingView/Python alert config.
    """
    user, err = _require_login()
    if err:
        return err
    s = (
        db_session.query(StrategyV2)
        .filter(StrategyV2.id == strategy_id, StrategyV2.user_id == user)
        .first()
    )
    if not s:
        return jsonify({"status": "error", "code": "NOT_FOUND"}), 404

    from services.strategy.ingestion_service import handle_webhook

    raw_body = request.get_data()
    status, body = handle_webhook(
        webhook_id=s.webhook_id,
        raw_body=raw_body,
        headers=dict(request.headers),
        request=request,
        dry_run=True,
    )
    return jsonify(body), status


# ----------------------------------------------------------------------------
# Strategy-level risk config (Phase 4)
# ----------------------------------------------------------------------------


def _risk_config_to_dict(rc: StrategyRiskConfig) -> dict:
    return {
        "strategy_id": rc.strategy_id,
        "overall_sl_enabled": bool(rc.overall_sl_enabled),
        "overall_sl_abs": float(rc.overall_sl_abs) if rc.overall_sl_abs is not None else None,
        "overall_target_enabled": bool(rc.overall_target_enabled),
        "overall_target_abs": (
            float(rc.overall_target_abs) if rc.overall_target_abs is not None else None
        ),
        "lock_profit_enabled": bool(rc.lock_profit_enabled),
        "lock_at_abs": float(rc.lock_at_abs) if rc.lock_at_abs is not None else None,
        "lock_min_abs": float(rc.lock_min_abs) if rc.lock_min_abs is not None else None,
        "trail_to_entry_enabled": bool(rc.trail_to_entry_enabled),
        "trail_to_entry_threshold": (
            float(rc.trail_to_entry_threshold)
            if rc.trail_to_entry_threshold is not None
            else 0.0
        ),
        "trail_to_entry_unit": rc.trail_to_entry_unit or "pct",
    }


@strategy_v2_bp.route("/strategy/<int:strategy_id>/risk_config", methods=["GET"])
def get_risk_config(strategy_id: int):
    user, err = _require_login()
    if err:
        return err
    s = (
        db_session.query(StrategyV2)
        .filter(StrategyV2.id == strategy_id, StrategyV2.user_id == user)
        .first()
    )
    if not s:
        return jsonify({"status": "error", "code": "NOT_FOUND"}), 404
    rc = (
        db_session.query(StrategyRiskConfig)
        .filter(StrategyRiskConfig.strategy_id == strategy_id)
        .first()
    )
    if rc is None:
        # Lazy-create if missing (e.g. older strategies created before
        # Phase 4).
        rc = StrategyRiskConfig(strategy_id=strategy_id)
        db_session.add(rc)
        db_session.commit()
    return jsonify({"status": "success", "data": _risk_config_to_dict(rc)}), 200


@strategy_v2_bp.route("/strategy/<int:strategy_id>/risk_config", methods=["PUT"])
def update_risk_config(strategy_id: int):
    user, err = _require_login()
    if err:
        return err
    s = (
        db_session.query(StrategyV2)
        .filter(StrategyV2.id == strategy_id, StrategyV2.user_id == user)
        .first()
    )
    if not s:
        return jsonify({"status": "error", "code": "NOT_FOUND"}), 404

    try:
        data = RiskConfigSchema().load(request.get_json(silent=True) or {})
    except ValidationError as e:
        return jsonify({"status": "error", "code": "VALIDATION", "errors": e.messages}), 400

    rc = (
        db_session.query(StrategyRiskConfig)
        .filter(StrategyRiskConfig.strategy_id == strategy_id)
        .first()
    )
    if rc is None:
        rc = StrategyRiskConfig(strategy_id=strategy_id)
        db_session.add(rc)

    for key, value in data.items():
        setattr(rc, key, value)
    db_session.commit()
    return jsonify({"status": "success", "data": _risk_config_to_dict(rc)}), 200


# ----------------------------------------------------------------------------
# Reporting endpoints — strategy-scoped orderbook / tradebook / positionbook /
# events / runs. Same JSON envelopes as the global /api/v1 endpoints so the
# frontend reuses table components.
# ----------------------------------------------------------------------------


def _user_owns_run(user: str, run_id: int) -> Optional[StrategyRun]:
    """Auth helper — only return the run if it belongs to the logged-in user."""
    return (
        db_session.query(StrategyRun)
        .join(StrategyV2, StrategyRun.strategy_id == StrategyV2.id)
        .filter(StrategyRun.id == run_id, StrategyV2.user_id == user)
        .first()
    )


def _user_owns_strategy(user: str, strategy_id: int) -> Optional[StrategyV2]:
    return (
        db_session.query(StrategyV2)
        .filter(StrategyV2.id == strategy_id, StrategyV2.user_id == user)
        .first()
    )


@strategy_v2_bp.route("/strategy/<int:strategy_id>/runs", methods=["GET"])
def list_runs(strategy_id: int):
    """List all runs for a strategy, most-recent first."""
    user, err = _require_login()
    if err:
        return err
    if not _user_owns_strategy(user, strategy_id):
        return jsonify({"status": "error", "code": "NOT_FOUND"}), 404
    rows = (
        db_session.query(StrategyRun)
        .filter(StrategyRun.strategy_id == strategy_id)
        .order_by(StrategyRun.id.desc())
        .all()
    )
    return jsonify(serializers.to_runs_format(rows)), 200


@strategy_v2_bp.route("/run/<int:run_id>", methods=["GET"])
def get_run(run_id: int):
    """Single-run details (state, P&L peaks, exit reason, timestamps)."""
    user, err = _require_login()
    if err:
        return err
    run = _user_owns_run(user, run_id)
    if not run:
        return jsonify({"status": "error", "code": "NOT_FOUND"}), 404
    return jsonify(serializers.run_detail(run)), 200


@strategy_v2_bp.route("/run/<int:run_id>/orderbook", methods=["GET"])
def run_orderbook(run_id: int):
    """Same JSON envelope as /api/v1/orderbook."""
    user, err = _require_login()
    if err:
        return err
    if not _user_owns_run(user, run_id):
        return jsonify({"status": "error", "code": "NOT_FOUND"}), 404
    rows = (
        db_session.query(StrategyOrder)
        .filter(StrategyOrder.run_id == run_id)
        .order_by(StrategyOrder.id.asc())
        .all()
    )
    return jsonify(serializers.to_orderbook_format(rows)), 200


@strategy_v2_bp.route("/run/<int:run_id>/tradebook", methods=["GET"])
def run_tradebook(run_id: int):
    """Same JSON envelope as /api/v1/tradebook."""
    user, err = _require_login()
    if err:
        return err
    if not _user_owns_run(user, run_id):
        return jsonify({"status": "error", "code": "NOT_FOUND"}), 404
    rows = (
        db_session.query(StrategyTrade)
        .filter(StrategyTrade.run_id == run_id)
        .order_by(StrategyTrade.id.asc())
        .all()
    )
    return jsonify(serializers.to_tradebook_format(rows)), 200


@strategy_v2_bp.route("/run/<int:run_id>/positionbook", methods=["GET"])
def run_positionbook(run_id: int):
    """Same JSON envelope as /api/v1/positionbook."""
    user, err = _require_login()
    if err:
        return err
    if not _user_owns_run(user, run_id):
        return jsonify({"status": "error", "code": "NOT_FOUND"}), 404
    rows = (
        db_session.query(StrategyPosition)
        .filter(StrategyPosition.run_id == run_id)
        .order_by(StrategyPosition.leg_id.asc())
        .all()
    )
    return jsonify(serializers.to_positionbook_format(rows)), 200


@strategy_v2_bp.route("/run/<int:run_id>/events", methods=["GET"])
def run_events(run_id: int):
    """Audit timeline for a run — every state change, RMS trigger, fill, etc."""
    user, err = _require_login()
    if err:
        return err
    if not _user_owns_run(user, run_id):
        return jsonify({"status": "error", "code": "NOT_FOUND"}), 404
    rows = (
        db_session.query(StrategyEvent)
        .filter(StrategyEvent.run_id == run_id)
        .order_by(StrategyEvent.id.asc())
        .all()
    )
    return jsonify(serializers.to_events_format(rows)), 200


# ----------------------------------------------------------------------------
# Account-level risk config + state + unlock (Phase 4.5)
# ----------------------------------------------------------------------------


def _account_config_to_dict(cfg: AccountRiskConfig) -> dict:
    return {
        "user_id": cfg.user_id,
        "max_concurrent_runs": cfg.max_concurrent_runs,
        "max_daily_loss_abs": (
            float(cfg.max_daily_loss_abs) if cfg.max_daily_loss_abs is not None else None
        ),
        "cooldown_after_loss_minutes": cfg.cooldown_after_loss_minutes,
        "max_runs_per_strategy_per_day": cfg.max_runs_per_strategy_per_day,
        "min_seconds_between_runs": cfg.min_seconds_between_runs,
        "auto_clear_at": cfg.auto_clear_at,
        "is_locked_out": bool(cfg.is_locked_out),
        "lockout_reason": cfg.lockout_reason,
        "lockout_until": cfg.lockout_until.isoformat() if cfg.lockout_until else None,
    }


def _account_state_to_dict(state: AccountState) -> dict:
    return {
        "user_id": state.user_id,
        "active_run_count": state.active_run_count or 0,
        "realized_pnl_today_live": (
            float(state.realized_pnl_today_live) if state.realized_pnl_today_live is not None else 0.0
        ),
        "realized_pnl_today_sandbox": (
            float(state.realized_pnl_today_sandbox)
            if state.realized_pnl_today_sandbox is not None
            else 0.0
        ),
        "unrealized_pnl_aggregate": (
            float(state.unrealized_pnl_aggregate)
            if state.unrealized_pnl_aggregate is not None
            else 0.0
        ),
    }


@strategy_v2_bp.route("/account/risk_config", methods=["GET"])
def get_account_risk_config():
    """Return the user's AccountRiskConfig + cached AccountState. Lazy-creates
    both rows if missing (so the first call from a new install always
    returns sensible defaults)."""
    user, err = _require_login()
    if err:
        return err
    from services.strategy.account_rms import (
        get_or_create_config,
        get_or_create_state,
        is_locked_now,
    )

    cfg = get_or_create_config(user)
    # Side-effect: is_locked_now auto-clears expired lockouts.
    is_locked_now(cfg)
    state = get_or_create_state(user)
    return jsonify({
        "status": "success",
        "config": _account_config_to_dict(cfg),
        "state": _account_state_to_dict(state),
    }), 200


@strategy_v2_bp.route("/account/risk_config", methods=["PUT"])
def update_account_risk_config():
    user, err = _require_login()
    if err:
        return err
    try:
        data = AccountRiskConfigSchema().load(request.get_json(silent=True) or {})
    except ValidationError as e:
        return jsonify({"status": "error", "code": "VALIDATION", "errors": e.messages}), 400

    from services.strategy.account_rms import get_or_create_config

    cfg = get_or_create_config(user)
    for key, value in data.items():
        setattr(cfg, key, value)
    db_session.commit()
    return jsonify({
        "status": "success",
        "config": _account_config_to_dict(cfg),
    }), 200


@strategy_v2_bp.route("/account/unlock", methods=["POST"])
def unlock_account_endpoint():
    """Manual unlock — clears the is_locked_out flag, lockout_until, and
    lockout_reason. Idempotent: calling on an already-unlocked account is a
    no-op."""
    user, err = _require_login()
    if err:
        return err
    from services.strategy.account_rms import get_or_create_config, unlock_account

    unlock_account(user, cleared_by="manual")
    cfg = get_or_create_config(user)
    return jsonify({
        "status": "success",
        "config": _account_config_to_dict(cfg),
    }), 200


# ----------------------------------------------------------------------------
# Audit chain verifier (Phase 0 carried forward)
# ----------------------------------------------------------------------------


@strategy_v2_bp.route("/audit/verify/<int:run_id>", methods=["GET"])
def audit_verify(run_id: int):
    user, err = _require_login()
    if err:
        return err
    try:
        result = verify_chain(run_id)
    except Exception as exc:
        logger.exception("audit verify failed for run_id=%s", run_id)
        return jsonify({"status": "error", "message": f"verifier crashed: {exc}"}), 500

    if result.get("events_verified", 0) == 0 and result.get("status") == "ok":
        return jsonify({"status": "error", "message": "no events for run"}), 404
    return jsonify(result), 200
