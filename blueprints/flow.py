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
    from services.flow_scheduler_service import get_flow_scheduler

    workflow = get_workflow(workflow_id)
    if not workflow:
        return jsonify({"error": "Workflow not found"}), 404

    # Deactivate if active (removes scheduler job)
    if workflow.is_active:
        scheduler = get_flow_scheduler()
        scheduler.remove_workflow_job(workflow_id)

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

    nodes = workflow.nodes or []

    # Find trigger node to determine activation type
    trigger_node = next(
        (n for n in nodes if n.get("type") in ["start", "webhookTrigger", "priceAlert"]), None
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
            )

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
            scheduler.remove_job(workflow.schedule_job_id)
            set_schedule_job_id(workflow_id, None)

        # Remove price alert if any
        price_monitor = get_flow_price_monitor()
        price_monitor.remove_alert(workflow_id)

        # Update workflow as inactive
        db_deactivate(workflow_id)

        return jsonify({"status": "success", "message": "Workflow deactivated"})

    except Exception as e:
        logger.exception(f"Failed to deactivate workflow {workflow_id}: {e}")
        return jsonify({"error": str(e)}), 500


# === Execution Routes ===


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

    # Get API key - prioritize stored API key from workflow
    api_key = workflow.api_key  # Use API key stored when workflow was activated
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
    """Get price monitor status"""
    from services.flow_price_monitor_service import get_flow_price_monitor

    monitor = get_flow_price_monitor()
    return jsonify(monitor.get_status())


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
    """Import a workflow"""
    from database.flow_db import create_workflow

    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    name = data.get("name", "Imported Workflow")
    description = data.get("description")
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])

    workflow = create_workflow(
        name=f"{name} (imported)", description=description, nodes=nodes, edges=edges
    )

    if workflow:
        return jsonify({"status": "success", "workflow_id": workflow.id}), 201
    return jsonify({"error": "Failed to import workflow"}), 500


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
