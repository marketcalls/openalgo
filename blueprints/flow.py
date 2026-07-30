# blueprints/flow.py
"""
Flow Blueprint - Visual Workflow Automation
Provides routes for managing and executing workflows
"""

import logging
from datetime import datetime

from flask import Blueprint, jsonify, request, session

from database.auth_db import get_api_key_for_tradingview
from utils.session import check_session_validity

logger = logging.getLogger(__name__)

flow_bp = Blueprint("flow", __name__, url_prefix="/flow")


def get_current_api_key():
    """Get API key for the current user from session"""
    username = session.get("user")
    if not username:
        return None
    return get_api_key_for_tradingview(username)


# === Workflow CRUD Routes ===


@flow_bp.route("/api/workflows", methods=["GET"])
@check_session_validity
def list_workflows():
    """List all workflows"""
    from database.flow_db import get_all_workflows, get_workflow_executions

    workflows = get_all_workflows()
    items = []

    for wf in workflows:
        executions = get_workflow_executions(wf.id, limit=1)
        last_exec = executions[0] if executions else None

        items.append(
            {
                "id": wf.id,
                "name": wf.name,
                "description": wf.description,
                "is_active": wf.is_active,
                "webhook_enabled": wf.webhook_enabled,
                "created_at": wf.created_at.isoformat() if wf.created_at else None,
                "updated_at": wf.updated_at.isoformat() if wf.updated_at else None,
                "last_execution_status": last_exec.status if last_exec else None,
            }
        )

    return jsonify(items)


@flow_bp.route("/api/workflows", methods=["POST"])
@check_session_validity
def create_workflow():
    """Create a new workflow"""
    from database.flow_db import create_workflow

    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    # Structural validation only, and only over what was actually sent. A new
    # workflow is created from the editor with just a name - no graph yet - so
    # requiring nodes/edges here rejected every "New Strategy" click.
    # Completeness (required fields, one trigger, reachability) is enforced at
    # import, activation, and execution instead of blocking a save.
    from services.flow_workflow_validator import validate_workflow

    if not isinstance(data, dict):
        # A JSON array or string is truthy but has no fields, so the
        # "was a graph sent?" check below would pass it straight through to
        # .get() and a 500. Reject it as the malformed payload it is.
        return jsonify(
            {
                "status": "error",
                "error": "Invalid workflow structure",
                "message": "Workflow must be a JSON object",
                "errors": validate_workflow(data),
            }
        ), 400

    errors = (
        validate_workflow(
            {
                "name": data.get("name") or "",
                "nodes": data.get("nodes") or [],
                "edges": data.get("edges") or [],
            },
            require_name=False,
            strict=False,
        )
        if ("nodes" in data or "edges" in data)
        else []
    )
    if errors:
        # Logged, not just returned: a bare 400 in the browser gives no reason,
        # which made this class of rejection hard to diagnose.
        logger.warning(
            f"Rejected workflow save: {errors[0]['path']} {errors[0]['code']} - "
            f"{errors[0]['message']}"
        )
        return jsonify(
            {
                "status": "error",
                "error": "Invalid workflow structure",
                "message": errors[0]["message"],
                "errors": errors,
            }
        ), 400

    name = data.get("name", "Untitled Workflow")
    description = data.get("description")
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])

    workflow = create_workflow(name=name, description=description, nodes=nodes, edges=edges)

    if not workflow:
        return jsonify({"error": "Failed to create workflow"}), 500

    return jsonify(
        {
            "id": workflow.id,
            "name": workflow.name,
            "description": workflow.description,
            "nodes": workflow.nodes,
            "edges": workflow.edges,
            "is_active": workflow.is_active,
            "webhook_token": workflow.webhook_token,
            "webhook_secret": workflow.webhook_secret,
            "webhook_enabled": workflow.webhook_enabled,
            "webhook_auth_type": workflow.webhook_auth_type,
            "created_at": workflow.created_at.isoformat() if workflow.created_at else None,
            "updated_at": workflow.updated_at.isoformat() if workflow.updated_at else None,
        }
    ), 201


@flow_bp.route("/api/workflows/<int:workflow_id>", methods=["GET"])
@check_session_validity
def get_workflow(workflow_id):
    """Get a workflow by ID"""
    from database.flow_db import get_workflow

    workflow = get_workflow(workflow_id)
    if not workflow:
        return jsonify({"error": "Workflow not found"}), 404

    return jsonify(
        {
            "id": workflow.id,
            "name": workflow.name,
            "description": workflow.description,
            "nodes": workflow.nodes,
            "edges": workflow.edges,
            "is_active": workflow.is_active,
            "schedule_job_id": workflow.schedule_job_id,
            "webhook_token": workflow.webhook_token,
            "webhook_secret": workflow.webhook_secret,
            "webhook_enabled": workflow.webhook_enabled,
            "webhook_auth_type": workflow.webhook_auth_type,
            "created_at": workflow.created_at.isoformat() if workflow.created_at else None,
            "updated_at": workflow.updated_at.isoformat() if workflow.updated_at else None,
        }
    )


@flow_bp.route("/api/workflows/<int:workflow_id>", methods=["PUT"])
@check_session_validity
def update_workflow(workflow_id):
    """Update a workflow"""
    from database.flow_db import update_workflow

    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    if not isinstance(data, dict):
        from services.flow_workflow_validator import validate_workflow as _validate

        return jsonify(
            {
                "status": "error",
                "error": "Invalid workflow structure",
                "message": "Workflow must be a JSON object",
                "errors": _validate(data),
            }
        ), 400

    # Partial updates (rename, toggle) carry no graph, and the API also accepts
    # nodes without edges or vice versa. Validate the merged graph so a partial
    # update is checked against what the workflow will actually become, rather
    # than being rejected for the half it did not send.
    if "nodes" in data or "edges" in data:
        from database.flow_db import get_workflow as _get_workflow
        from services.flow_workflow_validator import validate_workflow

        existing = _get_workflow(workflow_id)
        merged = {
            "name": data.get("name") or (existing.name if existing else ""),
            "nodes": data.get("nodes", (existing.nodes if existing else []) or []),
            "edges": data.get("edges", (existing.edges if existing else []) or []),
        }
        errors = validate_workflow(merged, require_name=False, strict=False)
        if errors:
            return jsonify(
                {
                    "status": "error",
                    "error": "Invalid workflow structure",
                    "message": errors[0]["message"],
                    "errors": errors,
                }
            ), 400

    workflow = update_workflow(workflow_id, **data)
    if not workflow:
        return jsonify({"error": "Workflow not found"}), 404

    return jsonify(
        {
            "id": workflow.id,
            "name": workflow.name,
            "description": workflow.description,
            "nodes": workflow.nodes,
            "edges": workflow.edges,
            "is_active": workflow.is_active,
            "webhook_token": workflow.webhook_token,
            "webhook_secret": workflow.webhook_secret,
            "webhook_enabled": workflow.webhook_enabled,
            "webhook_auth_type": workflow.webhook_auth_type,
            "created_at": workflow.created_at.isoformat() if workflow.created_at else None,
            "updated_at": workflow.updated_at.isoformat() if workflow.updated_at else None,
        }
    )


@flow_bp.route("/api/workflows/<int:workflow_id>", methods=["DELETE"])
@check_session_validity
def delete_workflow(workflow_id):
    """Delete a workflow"""
    from database.flow_db import delete_workflow, get_workflow
    from services.flow_order_update_monitor_service import get_flow_order_update_monitor
    from services.flow_price_monitor_service import get_flow_price_monitor
    from services.flow_scheduler_service import get_flow_scheduler

    workflow = get_workflow(workflow_id)
    if not workflow:
        return jsonify({"error": "Workflow not found"}), 404

    # Deactivate if active. Every in-memory registration must be torn down
    # here too - deleting the row alone would strand the watch/alert, which
    # then keeps matching events and tries to execute a workflow that no
    # longer exists.
    if workflow.is_active:
        scheduler = get_flow_scheduler()
        scheduler.remove_workflow_job(workflow_id)
        get_flow_price_monitor().remove_alert(workflow_id)
        get_flow_order_update_monitor().remove_watch(workflow_id)

    if delete_workflow(workflow_id):
        return jsonify({"status": "success", "message": "Workflow deleted"})
    else:
        return jsonify({"error": "Failed to delete workflow"}), 500


# === Activation/Deactivation Routes ===


@flow_bp.route("/api/workflows/<int:workflow_id>/activate", methods=["POST"])
@check_session_validity
def activate_workflow(workflow_id):
    """Activate a workflow"""
    from database.flow_db import activate_workflow as db_activate
    from database.flow_db import get_workflow, set_schedule_job_id
    from services.flow_order_update_monitor_service import get_flow_order_update_monitor
    from services.flow_price_monitor_service import get_flow_price_monitor
    from services.flow_scheduler_service import get_flow_scheduler

    workflow = get_workflow(workflow_id)
    if not workflow:
        return jsonify({"error": "Workflow not found"}), 404

    if workflow.is_active:
        return jsonify({"status": "already_active", "message": "Workflow is already active"})

    api_key = get_current_api_key()
    if not api_key:
        return jsonify({"error": "API key not configured"}), 400

    blocked = _execution_blocked(workflow)
    if blocked:
        return jsonify({**blocked, "error": "Workflow cannot be activated"}), 400

    nodes = workflow.nodes or []

    # Find trigger node to determine activation type
    trigger_node = next(
        (
            n
            for n in nodes
            if n.get("type") in ["start", "webhookTrigger", "priceAlert", "orderUpdateTrigger"]
        ),
        None,
    )
    if not trigger_node:
        return jsonify({"error": "No trigger node found in workflow"}), 400

    trigger_type = trigger_node.get("type")
    trigger_data = trigger_node.get("data", {})

    try:
        if trigger_type == "start":
            # Check for schedule configuration
            schedule_type = trigger_data.get("scheduleType")
            if schedule_type and schedule_type != "manual":
                scheduler = get_flow_scheduler()
                scheduler.set_api_key(api_key)

                job_id = scheduler.add_workflow_job(
                    workflow_id=workflow_id,
                    schedule_type=schedule_type,
                    time_str=trigger_data.get("time", "09:15"),
                    days=trigger_data.get("days"),
                    execute_at=trigger_data.get("executeAt"),
                    interval_value=trigger_data.get("intervalValue"),
                    interval_unit=trigger_data.get("intervalUnit"),
                    # Offered by the editor and defaulted on, but never read
                    # before, so schedules kept firing overnight and at weekends.
                    market_hours_only=bool(trigger_data.get("marketHoursOnly", False)),
                )
                set_schedule_job_id(workflow_id, job_id)

        elif trigger_type == "priceAlert":
            price_monitor = get_flow_price_monitor()
            price_monitor.add_alert(
                workflow_id=workflow_id,
                symbol=trigger_data.get("symbol", ""),
                exchange=trigger_data.get("exchange", "NSE"),
                condition=trigger_data.get("condition", "greater_than"),
                target_price=float(trigger_data.get("price", 0)),
                price_lower=trigger_data.get("priceLower"),
                price_upper=trigger_data.get("priceUpper"),
                percentage=trigger_data.get("percentage"),
                api_key=api_key,
                # Previously dropped here, so "Every Time" behaved as one-shot
                # and the expiry window was never applied.
                trigger=trigger_data.get("trigger", "once"),
                expiration=trigger_data.get("expiration", "none"),
            )

        elif trigger_type == "orderUpdateTrigger":
            order_monitor = get_flow_order_update_monitor()
            try:
                order_monitor.add_watch(
                    workflow_id=workflow_id,
                    api_key=api_key,
                    order_id=trigger_data.get("orderId") or None,
                    symbol=trigger_data.get("symbol") or None,
                    exchange=trigger_data.get("exchange") or None,
                    status=trigger_data.get("status", "complete"),
                    trigger=trigger_data.get("trigger", "once"),
                )
            except ValueError as e:
                # Misconfigured node (no Order ID/Symbol, a {{variable}} Order
                # ID, or an unknown status) is a client error, not a 500.
                return jsonify({"error": str(e)}), 400

        # Update workflow as active and store API key for webhook execution
        db_activate(workflow_id, api_key=api_key)

        return jsonify(
            {"status": "success", "message": f"Workflow activated with {trigger_type} trigger"}
        )

    except Exception as e:
        logger.exception(f"Failed to activate workflow {workflow_id}: {e}")
        return jsonify({"error": str(e)}), 500


@flow_bp.route("/api/workflows/<int:workflow_id>/deactivate", methods=["POST"])
@check_session_validity
def deactivate_workflow(workflow_id):
    """Deactivate a workflow"""
    from database.flow_db import deactivate_workflow as db_deactivate
    from database.flow_db import get_workflow, set_schedule_job_id
    from services.flow_order_update_monitor_service import get_flow_order_update_monitor
    from services.flow_price_monitor_service import get_flow_price_monitor
    from services.flow_scheduler_service import get_flow_scheduler

    workflow = get_workflow(workflow_id)
    if not workflow:
        return jsonify({"error": "Workflow not found"}), 404

    if not workflow.is_active:
        return jsonify({"status": "already_inactive", "message": "Workflow is already inactive"})

    try:
        # Remove scheduler job if any
        if workflow.schedule_job_id:
            scheduler = get_flow_scheduler()
            # An already-gone job is expected after a restart or a double click;
            # remove_job treats that as a no-op.
            scheduler.remove_job(workflow.schedule_job_id)
            set_schedule_job_id(workflow_id, None)

        # Remove price alert if any
        price_monitor = get_flow_price_monitor()
        price_monitor.remove_alert(workflow_id)

        # Remove order-update watch if any
        order_monitor = get_flow_order_update_monitor()
        order_monitor.remove_watch(workflow_id)

        # Update workflow as inactive
        db_deactivate(workflow_id)

        return jsonify({"status": "success", "message": "Workflow deactivated"})

    except Exception as e:
        logger.exception(f"Failed to deactivate workflow {workflow_id}: {e}")
        return jsonify({"error": str(e)}), 500


# === Execution Routes ===


def _execution_blocked(workflow):
    """Structured 400 payload when a workflow is not fit to execute, else None.

    Saving deliberately accepts a half-built graph so the editor stays usable,
    which means "stored" is not the same as "runnable". Every path that can
    reach the broker - Run Now, activation, and webhooks - checks completeness
    here instead. A workflow can also be edited into an invalid state after it
    was activated, so checking once at activation is not enough.
    """
    from services.flow_workflow_validator import validate_workflow

    errors = validate_workflow(
        {"name": workflow.name, "nodes": workflow.nodes or [], "edges": workflow.edges or []},
        strict=True,
    )
    if not errors:
        return None
    logger.warning(
        f"Workflow {getattr(workflow, 'id', '?')} ({getattr(workflow, 'name', '?')}) "
        f"blocked: {errors[0]['path']} {errors[0]['code']} - {errors[0]['message']}"
    )
    return {
        "status": "error",
        "error": "Workflow cannot be executed",
        "message": errors[0]["message"],
        "errors": errors,
    }


@flow_bp.route("/api/workflows/<int:workflow_id>/execute", methods=["POST"])
@check_session_validity
def execute_workflow_now(workflow_id):
    """Execute a workflow immediately"""
    from database.flow_db import get_workflow
    from services.flow_executor_service import execute_workflow

    workflow = get_workflow(workflow_id)
    if not workflow:
        return jsonify({"error": "Workflow not found"}), 404

    api_key = get_current_api_key()
    if not api_key:
        return jsonify({"error": "API key not configured"}), 400

    blocked = _execution_blocked(workflow)
    if blocked:
        return jsonify(blocked), 400

    try:
        result = execute_workflow(workflow_id, api_key=api_key)
        return jsonify(result)
    except Exception as e:
        logger.exception(f"Failed to execute workflow {workflow_id}: {e}")
        return jsonify({"error": str(e)}), 500


@flow_bp.route("/api/workflows/<int:workflow_id>/executions", methods=["GET"])
@check_session_validity
def get_workflow_executions(workflow_id):
    """Get execution history for a workflow"""
    from database.flow_db import get_workflow_executions

    limit = request.args.get("limit", 20, type=int)
    executions = get_workflow_executions(workflow_id, limit=limit)

    return jsonify(
        [
            {
                "id": ex.id,
                "workflow_id": ex.workflow_id,
                "status": ex.status,
                "started_at": ex.started_at.isoformat() if ex.started_at else None,
                "completed_at": ex.completed_at.isoformat() if ex.completed_at else None,
                "logs": ex.logs,
                "error": ex.error,
            }
            for ex in executions
        ]
    )


# === Webhook Routes ===


def get_webhook_base_url():
    """Get the base URL for webhooks based on server configuration"""
    import os

    # Use HOST_SERVER from .env or default to localhost
    host = os.getenv("HOST_SERVER", "http://127.0.0.1:5000")
    # Ensure no trailing slash
    return host.rstrip("/")


@flow_bp.route("/api/workflows/<int:workflow_id>/webhook", methods=["GET"])
@check_session_validity
def get_webhook_info(workflow_id):
    """Get webhook configuration for a workflow"""
    from database.flow_db import ensure_webhook_credentials, get_workflow

    workflow = get_workflow(workflow_id)
    if not workflow:
        return jsonify({"error": "Workflow not found"}), 404

    # Ensure webhook token and secret exist
    ensure_webhook_credentials(workflow_id)

    # Refresh workflow to get updated credentials
    workflow = get_workflow(workflow_id)

    # Build webhook URLs
    base_url = get_webhook_base_url()
    webhook_url = f"{base_url}/flow/webhook/{workflow.webhook_token}"
    auth_type = workflow.webhook_auth_type or "payload"

    return jsonify(
        {
            "webhook_token": workflow.webhook_token,
            "webhook_secret": workflow.webhook_secret,
            "webhook_enabled": workflow.webhook_enabled,
            "webhook_auth_type": auth_type,
            "webhook_url": webhook_url,
            "webhook_url_with_symbol": f"{webhook_url}/{{symbol}}",
            "webhook_url_with_secret": f"{webhook_url}?secret={workflow.webhook_secret}"
            if auth_type == "url"
            else None,
        }
    )


@flow_bp.route("/api/workflows/<int:workflow_id>/webhook/enable", methods=["POST"])
@check_session_validity
def enable_webhook(workflow_id):
    """Enable webhook for a workflow"""
    from database.flow_db import enable_webhook, ensure_webhook_credentials, get_workflow

    # Ensure credentials exist before enabling
    ensure_webhook_credentials(workflow_id)

    result = enable_webhook(workflow_id)
    if not result:
        return jsonify({"error": "Failed to enable webhook"}), 500

    # Get updated workflow and return full webhook info
    workflow = get_workflow(workflow_id)
    base_url = get_webhook_base_url()
    webhook_url = f"{base_url}/flow/webhook/{workflow.webhook_token}"
    auth_type = workflow.webhook_auth_type or "payload"

    return jsonify(
        {
            "status": "success",
            "message": "Webhook enabled",
            "webhook_token": workflow.webhook_token,
            "webhook_secret": workflow.webhook_secret,
            "webhook_enabled": True,
            "webhook_auth_type": auth_type,
            "webhook_url": webhook_url,
            "webhook_url_with_symbol": f"{webhook_url}/{{symbol}}",
            "webhook_url_with_secret": f"{webhook_url}?secret={workflow.webhook_secret}"
            if auth_type == "url"
            else None,
        }
    )


@flow_bp.route("/api/workflows/<int:workflow_id>/webhook/disable", methods=["POST"])
@check_session_validity
def disable_webhook(workflow_id):
    """Disable webhook for a workflow"""
    from database.flow_db import disable_webhook

    result = disable_webhook(workflow_id)
    if result:
        return jsonify({"status": "success", "message": "Webhook disabled"})
    return jsonify({"error": "Failed to disable webhook"}), 500


@flow_bp.route("/api/workflows/<int:workflow_id>/webhook/regenerate", methods=["POST"])
@check_session_validity
def regenerate_webhook(workflow_id):
    """Regenerate webhook token and secret"""
    from database.flow_db import get_workflow, regenerate_webhook_secret, regenerate_webhook_token

    new_token = regenerate_webhook_token(workflow_id)
    new_secret = regenerate_webhook_secret(workflow_id)

    if not new_token:
        return jsonify({"error": "Failed to regenerate token"}), 500

    # Get updated workflow and return full webhook info
    workflow = get_workflow(workflow_id)
    base_url = get_webhook_base_url()
    webhook_url = f"{base_url}/flow/webhook/{workflow.webhook_token}"

    return jsonify(
        {
            "status": "success",
            "message": "Webhook token and secret regenerated",
            "webhook_token": workflow.webhook_token,
            "webhook_secret": workflow.webhook_secret,
            "webhook_url": webhook_url,
            "webhook_url_with_symbol": f"{webhook_url}/{{symbol}}",
        }
    )


@flow_bp.route("/api/workflows/<int:workflow_id>/webhook/regenerate-secret", methods=["POST"])
@check_session_validity
def regenerate_webhook_secret_route(workflow_id):
    """Regenerate webhook secret only"""
    from database.flow_db import get_workflow, regenerate_webhook_secret

    new_secret = regenerate_webhook_secret(workflow_id)
    if not new_secret:
        return jsonify({"error": "Failed to regenerate secret"}), 500

    return jsonify(
        {"status": "success", "message": "Webhook secret regenerated", "webhook_secret": new_secret}
    )


@flow_bp.route("/api/workflows/<int:workflow_id>/webhook/auth-type", methods=["POST"])
@check_session_validity
def set_webhook_auth(workflow_id):
    """Set webhook auth type"""
    from database.flow_db import get_workflow, set_webhook_auth_type

    data = request.get_json()
    auth_type = data.get("auth_type", "payload")

    result = set_webhook_auth_type(workflow_id, auth_type)
    if not result:
        return jsonify({"error": "Invalid auth type"}), 400

    # Get updated workflow and return full webhook info
    workflow = get_workflow(workflow_id)
    base_url = get_webhook_base_url()
    webhook_url = f"{base_url}/flow/webhook/{workflow.webhook_token}"

    return jsonify(
        {
            "status": "success",
            "message": f"Webhook auth type set to '{auth_type}'",
            "webhook_auth_type": auth_type,
            "webhook_url": webhook_url,
            "webhook_url_with_secret": f"{webhook_url}?secret={workflow.webhook_secret}"
            if auth_type == "url"
            else None,
        }
    )


# === Webhook Trigger Routes (CSRF Exempt) ===


def _execute_webhook(token, webhook_data=None, url_secret=None):
    """Internal function to execute webhook"""
    import hmac
    import os

    from database.flow_db import get_workflow_by_webhook_token
    from services.flow_executor_service import execute_workflow

    workflow = get_workflow_by_webhook_token(token)
    if not workflow:
        return jsonify({"error": "Invalid webhook token"}), 404

    if not workflow.webhook_enabled:
        return jsonify({"error": "Webhook is disabled"}), 403

    if not workflow.is_active:
        return jsonify({"error": "Workflow is not active"}), 403

    data = webhook_data or {}
    auth_type = workflow.webhook_auth_type or "payload"

    # Validate webhook secret based on auth type
    if workflow.webhook_secret:
        if auth_type == "url":
            # Secret expected in URL query parameter
            if not url_secret:
                return jsonify(
                    {"error": "Missing webhook secret in URL. Use ?secret=your_secret"}
                ), 401
            if not hmac.compare_digest(url_secret, workflow.webhook_secret):
                return jsonify({"error": "Invalid webhook secret"}), 401
        else:
            # Secret expected in payload (default)
            provided_secret = data.pop("secret", "") or ""
            if not provided_secret:
                return jsonify(
                    {"error": "Missing webhook secret in payload. Add 'secret' field to JSON body"}
                ), 401
            if not hmac.compare_digest(provided_secret, workflow.webhook_secret):
                return jsonify({"error": "Invalid webhook secret"}), 401

    # Get API key - prioritize stored API key from workflow.
    # The column is encrypted at rest; use the helper that decrypts it
    # (and falls back to plaintext for pre-migration rows).
    from database.flow_db import get_workflow_api_key
    api_key = get_workflow_api_key(workflow)  # Use API key stored when workflow was activated
    if not api_key:
        api_key = get_current_api_key()  # Fallback to session (if called from UI)
    if not api_key:
        api_key = os.getenv("OPENALGO_API_KEY")  # Fallback to environment variable

    if not api_key:
        logger.error(f"Webhook: No API key for workflow {workflow.id}")
        return jsonify(
            {
                "error": "No API key configured for workflow execution. Please re-activate the workflow."
            }
        ), 500

    blocked = _execution_blocked(workflow)
    if blocked:
        logger.error(
            f"Webhook for workflow {workflow.id} rejected: {blocked['message']}"
        )
        return jsonify(blocked), 400

    try:
        logger.info(f"Webhook triggered for workflow {workflow.id}: {workflow.name}")
        result = execute_workflow(workflow.id, webhook_data=data, api_key=api_key)
        return jsonify(
            {
                "status": result.get("status", "success"),
                "message": f"Workflow '{workflow.name}' triggered",
                "execution_id": result.get("execution_id"),
                "workflow_id": workflow.id,
            }
        )
    except Exception as e:
        logger.exception(f"Webhook execution failed for workflow {workflow.id}: {e}")
        return jsonify({"error": str(e)}), 500


@flow_bp.route("/webhook/<token>", methods=["POST"])
def trigger_webhook(token):
    """
    Trigger a workflow via webhook (CSRF exempt)

    Authentication can be done via:
    1. URL query parameter: ?secret=your_secret (for Chartink, etc.)
    2. Payload field: {"secret": "your_secret", ...} (for TradingView, etc.)
    """
    url_secret = request.args.get("secret")
    payload = request.get_json() or {}
    return _execute_webhook(token, webhook_data=payload, url_secret=url_secret)


@flow_bp.route("/webhook/<token>/<symbol>", methods=["POST"])
def trigger_webhook_with_symbol(token, symbol):
    """
    Trigger a workflow via webhook with symbol in URL path (CSRF exempt)

    The symbol is automatically injected into the webhook data.
    """
    url_secret = request.args.get("secret")
    payload = request.get_json() or {}
    payload["symbol"] = symbol
    return _execute_webhook(token, webhook_data=payload, url_secret=url_secret)


# === Monitor Status Route ===


@flow_bp.route("/api/monitor/status", methods=["GET"])
@check_session_validity
def get_monitor_status():
    """Get price monitor and order-update monitor status"""
    from services.flow_order_update_monitor_service import get_flow_order_update_monitor
    from services.flow_price_monitor_service import get_flow_price_monitor

    monitor = get_flow_price_monitor()
    status = monitor.get_status()
    status["order_updates"] = get_flow_order_update_monitor().get_status()
    return jsonify(status)


# === Export/Import Routes ===


@flow_bp.route("/api/workflows/<int:workflow_id>/export", methods=["GET"])
@check_session_validity
def export_workflow(workflow_id):
    """Export a workflow"""
    from database.flow_db import get_workflow

    workflow = get_workflow(workflow_id)
    if not workflow:
        return jsonify({"error": "Workflow not found"}), 404

    return jsonify(
        {
            "name": workflow.name,
            "description": workflow.description,
            "nodes": workflow.nodes,
            "edges": workflow.edges,
            "version": "1.0",
            "exported_at": datetime.utcnow().isoformat(),
        }
    )


@flow_bp.route("/api/workflows/import", methods=["POST"])
@check_session_validity
def import_workflow():
    """Import a workflow.

    Validated before persistence: the editor checks the payload, but this
    endpoint is reachable directly, and a malformed graph stored here fails
    later - at activation or mid-execution - instead of at import.
    """
    from database.flow_db import create_workflow
    from services.flow_workflow_validator import migrate_legacy_node_data, validate_workflow

    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    # Upgrade legacy node payloads before validating, so an older exported
    # workflow imports as its canonical shape rather than being stored with a
    # field no reader honors.
    migration_notes: list[str] = []
    if isinstance(data.get("nodes"), list):
        data = dict(data)
        data["nodes"], migration_notes = migrate_legacy_node_data(data["nodes"])

    errors = validate_workflow(data)
    if errors:
        return jsonify(
            {
                "status": "error",
                "error": "Invalid workflow format",
                "message": errors[0]["message"],
                "errors": errors,
            }
        ), 400

    name = data.get("name")
    description = data.get("description")
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])

    workflow = create_workflow(
        name=f"{name} (imported)", description=description, nodes=nodes, edges=edges
    )

    if workflow:
        response = {"status": "success", "workflow_id": workflow.id}
        if migration_notes:
            response["migrations"] = migration_notes
        return jsonify(response), 201
    return jsonify({"error": "Failed to import workflow"}), 500


@flow_bp.route("/api/workflows/<int:workflow_id>/replace", methods=["POST"])
@check_session_validity
def replace_workflow(workflow_id):
    """Replace an existing workflow's graph from JSON, in place.

    Import always creates a new workflow, which for someone iterating on a
    strategy as JSON means a trail of copies and a new webhook URL each time.
    This keeps the workflow's id, webhook token and secret, API key and active
    state, and swaps only the graph.

    Held to import's rules, not save's: a JSON pasted here is presented as a
    finished workflow, so completeness is enforced.
    """
    from database.flow_db import get_workflow, update_workflow
    from services.flow_workflow_validator import (
        migrate_legacy_node_data,
        trigger_config,
        validate_workflow,
    )

    workflow = get_workflow(workflow_id)
    if not workflow:
        return jsonify({"error": "Workflow not found"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400
    if not isinstance(data, dict):
        return jsonify(
            {
                "status": "error",
                "error": "Invalid workflow structure",
                "message": "Workflow must be a JSON object",
            }
        ), 400

    # Same normalization the import endpoint applies, so a legacy export does
    # not arrive here still carrying a field no reader honors.
    migration_notes: list[str] = []
    payload = dict(data)
    if isinstance(payload.get("nodes"), list):
        payload["nodes"], migration_notes = migrate_legacy_node_data(payload["nodes"])

    # The name may legitimately be omitted when replacing only the graph.
    errors = validate_workflow(
        {
            "name": payload.get("name") or workflow.name,
            "nodes": payload.get("nodes") or [],
            "edges": payload.get("edges") or [],
        },
        strict=True,
    )
    if errors:
        logger.warning(
            f"Rejected replace of workflow {workflow_id}: {errors[0]['path']} "
            f"{errors[0]['code']} - {errors[0]['message']}"
        )
        return jsonify(
            {
                "status": "error",
                "error": "Invalid workflow format",
                "message": errors[0]["message"],
                "errors": errors,
            }
        ), 400

    # Captured before the write: reading the row afterwards would compare the
    # new graph against itself.
    trigger_changed = trigger_config(workflow.nodes or []) != trigger_config(payload["nodes"])
    was_active = bool(workflow.is_active)

    fields = {"nodes": payload["nodes"], "edges": payload.get("edges") or []}
    if payload.get("name"):
        fields["name"] = payload["name"]
    if payload.get("description") is not None:
        fields["description"] = payload["description"]

    updated = update_workflow(workflow_id, **fields)
    if not updated:
        return jsonify({"error": "Failed to replace workflow"}), 500

    # The graph is re-read on every run, so node edits apply immediately. The
    # trigger's schedule and any price/order watch are registered at activation,
    # so a trigger change needs the workflow reactivated.
    needs_reactivate = was_active and trigger_changed
    logger.info(
        f"Replaced workflow {workflow_id} from JSON "
        f"(nodes={len(fields['nodes'])} edges={len(fields['edges'])} "
        f"reactivate={needs_reactivate})"
    )
    return jsonify(
        {
            "status": "success",
            "workflow_id": workflow_id,
            "migrations": migration_notes,
            "needs_reactivate": needs_reactivate,
            "message": (
                "Trigger configuration changed. Deactivate and reactivate so the "
                "schedule is re-registered."
                if needs_reactivate
                else "Workflow replaced. Changes apply from the next run."
            ),
        }
    )


# === Index Symbols Lot Size Routes ===


@flow_bp.route("/api/index-symbols", methods=["GET"])
@check_session_validity
def get_index_symbols_lot_sizes():
    """
    Get lot sizes for index symbols from master contract database.
    Returns lot sizes for NSE and BSE index options (NIFTY, BANKNIFTY, etc.)
    """
    from sqlalchemy import distinct, func

    from database.symbol import SymToken, db_session

    # Define index symbols to look up
    nse_indices = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"]
    bse_indices = ["SENSEX", "BANKEX", "SENSEX50"]

    results = []

    try:
        # Get lot sizes for NSE indices (from NFO exchange)
        for index_name in nse_indices:
            # Query for any option symbol with this underlying name
            record = (
                db_session.query(SymToken.name, SymToken.lotsize)
                .filter(
                    SymToken.name == index_name,
                    SymToken.exchange == "NFO",
                    SymToken.lotsize.isnot(None),
                )
                .first()
            )

            if record and record.lotsize:
                results.append(
                    {
                        "value": index_name,
                        "label": index_name,
                        "exchange": "NFO",
                        "lotSize": record.lotsize,
                    }
                )

        # Get lot sizes for BSE indices (from BFO exchange)
        for index_name in bse_indices:
            record = (
                db_session.query(SymToken.name, SymToken.lotsize)
                .filter(
                    SymToken.name == index_name,
                    SymToken.exchange == "BFO",
                    SymToken.lotsize.isnot(None),
                )
                .first()
            )

            if record and record.lotsize:
                results.append(
                    {
                        "value": index_name,
                        "label": index_name,
                        "exchange": "BFO",
                        "lotSize": record.lotsize,
                    }
                )

        return jsonify({"status": "success", "data": results})

    except Exception as e:
        logger.exception(f"Error fetching index symbols lot sizes: {e}")
        return jsonify({"error": "Failed to fetch lot sizes"}), 500
