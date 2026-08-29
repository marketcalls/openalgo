"""Additive custom module for Python strategy onboarding.

This blueprint intentionally proxies to the existing /python handlers so custom
entry points live under a separate namespace with minimal merge surface.
"""

import sys
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request, session

from blueprints.python_strategy import (
    IST,
    STRATEGY_CONFIGS,
    initialize_with_app_context,
    save_configs,
    schedule_strategy,
    start_strategy_process,
    verify_strategy_ownership,
)
from blueprints.python_strategy import new_strategy as create_strategy
from utils.logging import get_logger
from utils.session import check_session_validity

python_strategy_custom_bp = Blueprint(
    "python_strategy_custom_bp", __name__, url_prefix="/python-custom"
)
logger = get_logger(__name__)

if "eventlet" in sys.modules:
    import eventlet

    _original_threading = eventlet.patcher.original("threading")
else:
    import threading as _original_threading


@python_strategy_custom_bp.route("/new", methods=["GET"])
def new_strategy_page():
    """Serve the React custom strategy form on a direct navigation or refresh."""
    from blueprints.react_app import serve_react_app

    return serve_react_app()


@python_strategy_custom_bp.route("/new", methods=["POST"])
def new_strategy():
    """Proxy upload strategy creation to the canonical python module."""
    return create_strategy()


@python_strategy_custom_bp.route("/new-path", methods=["POST"])
def add_strategy_from_path():
    """Register an existing strategy script and its schedule."""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    data = request.get_json(silent=True) or {}
    strategy_name = str(data.get("strategy_name", "")).strip()
    strategy_path_raw = str(data.get("strategy_path", "")).strip()
    if not strategy_name:
        return jsonify({"status": "error", "message": "Strategy name is required"}), 400
    if not strategy_path_raw:
        return jsonify({"status": "error", "message": "Strategy path is required"}), 400

    file_path = Path(strategy_path_raw).expanduser().resolve()
    if not file_path.is_file():
        return jsonify({"status": "error", "message": "Strategy file not found"}), 404
    if file_path.suffix.lower() not in {".py", ".sh", ".bat", ".cmd"}:
        return jsonify(
            {
                "status": "error",
                "message": "Unsupported file type. Use one of: .py, .sh, .bat, .cmd",
            }
        ), 400

    working_dir_raw = str(data.get("working_dir", "")).strip()
    working_dir = (
        Path(working_dir_raw).expanduser().resolve() if working_dir_raw else file_path.parent
    )
    if not working_dir.is_dir():
        return jsonify(
            {"status": "error", "message": "Working directory must be an existing folder"}
        ), 400

    exchange = str(data.get("exchange") or "NSE").upper()
    is_crypto = exchange == "CRYPTO"
    schedule_start = data.get("schedule_start") or ("00:00" if is_crypto else "09:00")
    schedule_stop = data.get("schedule_stop") or ("23:59" if is_crypto else "16:00")
    schedule_days = data.get("schedule_days")
    if not isinstance(schedule_days, list) or not schedule_days:
        schedule_days = (
            ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
            if is_crypto
            else [
                "mon",
                "tue",
                "wed",
                "thu",
                "fri",
            ]
        )

    created_at = datetime.now(IST)
    safe_stem = (
        "".join(
            character if character.isalnum() or character in {"-", "_"} else "_"
            for character in file_path.stem
        ).strip("_")
        or "strategy"
    )
    strategy_id = f"{safe_stem}_{created_at.strftime('%Y%m%d%H%M%S')}"

    STRATEGY_CONFIGS[strategy_id] = {
        "name": strategy_name[:100],
        "file_path": str(file_path),
        "file_name": file_path.name,
        "runner_type": "python"
        if file_path.suffix.lower() == ".py"
        else ("shell" if file_path.suffix.lower() == ".sh" else "batch"),
        "working_dir": str(working_dir),
        "source_mode": "path",
        "managed_file": False,
        "exchange": exchange,
        "is_running": False,
        "is_scheduled": True,
        "created_at": created_at.isoformat(),
        "user_id": user_id,
        "schedule_start": schedule_start,
        "schedule_stop": schedule_stop,
        "schedule_days": schedule_days,
    }
    save_configs()

    def install_schedule():
        try:
            schedule_strategy(
                strategy_id,
                start_time=schedule_start,
                stop_time=schedule_stop,
                days=schedule_days,
            )
        except Exception:
            logger.exception("Failed to install schedule for strategy %s", strategy_id)

    _original_threading.Thread(
        target=install_schedule,
        name=f"strategy-schedule-{strategy_id}",
        daemon=True,
    ).start()

    return jsonify(
        {
            "status": "success",
            "message": f'Strategy "{strategy_name}" added from path successfully',
            "data": {"strategy_id": strategy_id},
        }
    )


@python_strategy_custom_bp.route("/start-force/<strategy_id>", methods=["POST"])
@check_session_validity
def start_strategy_force(strategy_id):
    """Force-start strategy now, bypassing schedule window checks."""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    is_owner, error_response = verify_strategy_ownership(strategy_id, user_id)
    if not is_owner:
        return error_response

    config = STRATEGY_CONFIGS.get(strategy_id, {})
    if config.get("manually_stopped"):
        config.pop("manually_stopped", None)
        STRATEGY_CONFIGS[strategy_id] = config
        save_configs()

    initialize_with_app_context()
    success, message = start_strategy_process(strategy_id)
    return jsonify(
        {
            "status": "success" if success else "error",
            "message": message,
            "data": {"forced": True},
        }
    )
