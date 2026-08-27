"""Additive custom module for Python strategy onboarding.

This blueprint intentionally proxies to the existing /python handlers so custom
entry points live under a separate namespace with minimal merge surface.
"""

from flask import Blueprint, current_app, jsonify, session

from blueprints.auth import check_session_validity
from blueprints.python_strategy import (
    STRATEGY_CONFIGS,
    initialize_with_app_context,
    save_configs,
    start_strategy_process,
    verify_strategy_ownership,
)

python_strategy_custom_bp = Blueprint(
    "python_strategy_custom_bp", __name__, url_prefix="/python-custom"
)


def _delegate(endpoint: str):
    view = current_app.view_functions.get(endpoint)
    if view is None:
        raise RuntimeError(f"Endpoint not found: {endpoint}")
    return view()


def _delegate_any(*endpoints: str):
    for endpoint in endpoints:
        view = current_app.view_functions.get(endpoint)
        if view is not None:
            return view()
    raise RuntimeError(f"Endpoint not found: {', '.join(endpoints)}")


@python_strategy_custom_bp.route("/new", methods=["POST"])
@check_session_validity
def new_strategy():
    """Proxy upload strategy creation to the canonical python module."""
    return _delegate("python_strategy_bp.new_strategy")


@python_strategy_custom_bp.route("/new-path", methods=["POST"])
@check_session_validity
def add_strategy_from_path():
    """Proxy path-based strategy creation to the canonical python module."""
    return _delegate_any(
        "python_strategy_bp.new_strategy_from_path",
        "python_strategy_bp.add_strategy_from_path",
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
