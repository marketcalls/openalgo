# blueprints/flow.py
"""
Flow Blueprint - Visual Workflow Automation
Provides routes for managing and executing workflows
"""

import json
import logging
import os
from datetime import datetime

from flask import Blueprint, jsonify, request, session

from database.auth_db import get_api_key_for_tradingview
from limiter import limiter
from utils.session import check_session_validity

logger = logging.getLogger(__name__)

flow_bp = Blueprint("flow", __name__, url_prefix="/flow")

# The same variable and default the /chartink webhook reads, and the legacy
# /strategy webhook read before it was removed. Flow inherits the budget an
# operator has already configured rather than introducing a second knob.
WEBHOOK_RATE_LIMIT = os.getenv("WEBHOOK_RATE_LIMIT", "100 per minute")


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


# Execution-history page size. The maximum bounds one response; a workflow on a
# one-minute schedule writes hundreds of rows a day, each with a full log blob.
EXECUTIONS_DEFAULT_LIMIT = 20
EXECUTIONS_MAX_LIMIT = 200


def _execution_status_code(result: dict) -> int:
    """HTTP status for an executor result.

    Every outcome used to return 200, including a run that placed no orders
    because another was already in flight and a run whose broker calls were all
    rejected. A client checking response.ok saw success for both.
    """
    if not isinstance(result, dict):
        return 200
    if result.get("already_running"):
        return 409
    if result.get("status") == "error":
        return 502 if result.get("errors") else 500
    return 200


def _existing_for_trigger_check(workflow_id):
    """The stored workflow, for comparing trigger config across an update."""
    from database.flow_db import get_workflow as _get

    return _get(workflow_id)


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

    # Only what the editor may change. The database allowlist also accepts
    # is_active, schedule_job_id, webhook_enabled and api_key, so a PUT could
    # flip lifecycle state without the registration that has to go with it --
    # marking a workflow active with no scheduler job (shows Active, never
    # fires), marking it inactive while its job keeps trading, or enabling the
    # webhook without ensure_webhook_credentials, which leaves webhook_secret
    # NULL and _execute_webhook then skips authentication entirely. Those
    # transitions belong to the activate/deactivate/webhook routes.
    editable = {"name", "description", "nodes", "edges"}
    rejected = sorted(set(data) - editable)
    data = {key: value for key, value in data.items() if key in editable}
    if rejected:
        logger.warning(
            f"Ignoring non-editable field(s) {rejected} in PUT for workflow {workflow_id}"
        )

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

    # Trigger registrations are built at activation time from a snapshot of the
    # trigger node, and nothing here re-reads them -- so editing the schedule
    # time, the alert symbol or the watched order on an active workflow saved
    # cleanly while the scheduler and monitors kept running the old
    # configuration. The /replace route already reports this; the plain PUT did
    # not, so the editor had no way to know.
    from services.flow_workflow_validator import trigger_config

    existing = _existing_for_trigger_check(workflow_id)
    trigger_before = trigger_config(existing.nodes or []) if existing else {}
    was_active = bool(existing.is_active) if existing else False

    workflow = update_workflow(workflow_id, **data)
    if not workflow:
        return jsonify({"error": "Workflow not found"}), 404

    trigger_changed = was_active and trigger_config(workflow.nodes or []) != trigger_before
    needs_reactivate = False
    if trigger_changed:
        # Re-arm in place. The registration is a snapshot taken at activation,
        # so without this a new schedule time or alert symbol saved cleanly
        # while the scheduler and monitors kept running the old one.
        logger.info(
            f"Workflow {workflow_id} trigger configuration changed while active; "
            "re-registering it"
        )
        try:
            _reregister_trigger(workflow)
        except Exception:
            # Fail closed: rather than leave the workflow active with a stale or
            # absent registration, stand it down and say so. The editor turns
            # needs_reactivate into a visible warning.
            logger.exception(
                f"Could not re-register the trigger for workflow {workflow_id}; "
                "deactivating it so it cannot run a stale configuration"
            )
            _rollback_activation(workflow_id)
            needs_reactivate = True

    return jsonify(
        {
            "needs_reactivate": needs_reactivate,
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
    from services.flow_executor_service import release_workflow_subscriptions
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

    # Unconditionally, not only when active: a workflow deactivated and then
    # deleted has already been released, and this is a no-op, but one that
    # subscribed while active and was never deactivated still holds them.
    release_workflow_subscriptions(workflow_id)

    if delete_workflow(workflow_id):
        return jsonify({"status": "success", "message": "Workflow deleted"})
    else:
        return jsonify({"error": "Failed to delete workflow"}), 500


# === Activation/Deactivation Routes ===


def _trigger_node(nodes):
    """The workflow's trigger node, or None."""
    return next(
        (
            n
            for n in (nodes or [])
            if n.get("type") in ["start", "webhookTrigger", "priceAlert", "orderUpdateTrigger"]
        ),
        None,
    )


def _unregister_trigger(workflow_id):
    """Remove every in-memory trigger registration for a workflow.

    Deliberately unconditional across all three kinds: the stored
    schedule_job_id can be missing, and a workflow whose trigger type changed
    still has the previous kind registered.
    """
    from services.flow_order_update_monitor_service import get_flow_order_update_monitor
    from services.flow_price_monitor_service import get_flow_price_monitor
    from services.flow_scheduler_service import get_flow_scheduler

    get_flow_scheduler().remove_workflow_job(workflow_id, strict=True)
    get_flow_price_monitor().remove_alert(workflow_id)
    get_flow_order_update_monitor().remove_watch(workflow_id)


def _register_trigger(workflow_id, trigger_type, trigger_data, api_key):
    """Arm the scheduler job, price alert or order watch for a trigger node.

    Shared by activation and by a save that changes the trigger of an already
    active workflow, so the two cannot drift.

    Raises ValueError for a misconfigured node (a client error) and
    RuntimeError when a registration cannot be recorded. The caller decides how
    to report it and what to roll back.
    """
    from database.flow_db import set_schedule_job_id
    from services.flow_order_update_monitor_service import get_flow_order_update_monitor
    from services.flow_price_monitor_service import get_flow_price_monitor
    from services.flow_scheduler_service import get_flow_scheduler

    if trigger_type == "start":
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
            if not set_schedule_job_id(workflow_id, job_id):
                # Without the stored id, deactivation cannot find the job.
                # Undo the job rather than leave one nothing can reach.
                scheduler.remove_workflow_job(workflow_id)
                raise RuntimeError("Could not record the scheduler job id for this workflow")

    elif trigger_type == "priceAlert":
        get_flow_price_monitor().add_alert(
            workflow_id=workflow_id,
            symbol=trigger_data.get("symbol", ""),
            exchange=trigger_data.get("exchange", "NSE"),
            condition=trigger_data.get("condition", "greater_than"),
            target_price=float(trigger_data.get("price", 0) or 0),
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
        get_flow_order_update_monitor().add_watch(
            workflow_id=workflow_id,
            api_key=api_key,
            order_id=trigger_data.get("orderId") or None,
            symbol=trigger_data.get("symbol") or None,
            exchange=trigger_data.get("exchange") or None,
            status=trigger_data.get("status", "complete"),
            trigger=trigger_data.get("trigger", "once"),
        )


def _reregister_trigger(workflow):
    """Swap a live workflow's trigger registration for its current graph.

    Tears the old one down first, unconditionally and across all three kinds,
    because the trigger type itself may have changed. Raises if the new
    registration cannot be armed, leaving the caller to fail closed.
    """
    trigger_node = _trigger_node(workflow.nodes)
    if not trigger_node:
        raise ValueError("Workflow has no trigger node")

    api_key = get_current_api_key()
    if not api_key:
        raise RuntimeError("API key not configured")

    _unregister_trigger(workflow.id)
    _register_trigger(
        workflow.id, trigger_node.get("type"), trigger_node.get("data", {}) or {}, api_key
    )


def _rollback_activation(workflow_id):
    """Undo a partial activation so nothing is left armed.

    Activation persists `is_active` before registering the trigger, so a
    registration failure must clear the flag again -- otherwise the workflow
    reports Active with nothing watching, and the activate endpoint refuses to
    retry it as `already_active`. Every registration is torn down too, because
    a multi-step activation can fail after one of them succeeded.
    """
    from database.flow_db import deactivate_workflow as db_deactivate
    from services.flow_order_update_monitor_service import get_flow_order_update_monitor
    from services.flow_price_monitor_service import get_flow_price_monitor
    from services.flow_scheduler_service import get_flow_scheduler

    for undo, what in (
        (lambda: get_flow_scheduler().remove_workflow_job(workflow_id), "scheduler job"),
        (lambda: get_flow_price_monitor().remove_alert(workflow_id), "price alert"),
        (lambda: get_flow_order_update_monitor().remove_watch(workflow_id), "order-update watch"),
        (lambda: db_deactivate(workflow_id), "active flag"),
    ):
        try:
            undo()
        except Exception:
            logger.exception(
                f"Could not roll back the {what} for workflow {workflow_id} after a "
                "failed activation; it may need to be deactivated manually"
            )


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
    trigger_node = _trigger_node(nodes)
    if not trigger_node:
        return jsonify({"error": "No trigger node found in workflow"}), 400

    trigger_type = trigger_node.get("type")
    trigger_data = trigger_node.get("data", {})

    # Persist the active state before registering anything. The old order
    # registered the trigger first and ignored what the database said, so a
    # failed write returned HTTP 200 "success" while leaving a live scheduler
    # job against a row marked inactive -- a workflow that traded on schedule
    # and could not be stopped, because deactivate short-circuits on
    # already_inactive and delete only removes the job when the row is active.
    # Persisting first fails closed: nothing is registered yet, so a failure
    # here leaves nothing running.
    if not db_activate(workflow_id, api_key=api_key):
        logger.error(f"Failed to persist active state for workflow {workflow_id}")
        return jsonify({"error": "Could not activate workflow"}), 500

    try:
        _register_trigger(workflow_id, trigger_type, trigger_data, api_key)

        return jsonify(
            {"status": "success", "message": f"Workflow activated with {trigger_type} trigger"}
        )

    except ValueError as e:
        # Misconfigured node (no Order ID/Symbol, a {{variable}} Order ID, or an
        # unknown status) is a client error, not a 500.
        _rollback_activation(workflow_id)
        return jsonify({"error": str(e)}), 400

    except Exception as e:
        logger.exception(f"Failed to activate workflow {workflow_id}: {e}")
        _rollback_activation(workflow_id)
        return jsonify({"error": str(e)}), 500


@flow_bp.route("/api/workflows/<int:workflow_id>/deactivate", methods=["POST"])
@check_session_validity
def deactivate_workflow(workflow_id):
    """Deactivate a workflow"""
    from database.flow_db import deactivate_workflow as db_deactivate
    from database.flow_db import get_workflow, set_schedule_job_id
    from services.flow_executor_service import release_workflow_subscriptions
    from services.flow_order_update_monitor_service import get_flow_order_update_monitor
    from services.flow_price_monitor_service import get_flow_price_monitor
    from services.flow_scheduler_service import get_flow_scheduler

    workflow = get_workflow(workflow_id)
    if not workflow:
        return jsonify({"error": "Workflow not found"}), 404

    if not workflow.is_active:
        return jsonify({"status": "already_inactive", "message": "Workflow is already inactive"})

    try:
        # Removed by workflow id, not by the stored schedule_job_id. The id is
        # derived deterministically, so this still finds the job when the stored
        # pointer was never written or was cleared -- the case that used to skip
        # removal entirely and strand a live job. strict=True turns a jobstore
        # failure into an exception instead of a silent False, so the workflow
        # is never marked inactive while its job is still armed. An already-gone
        # job returns False and is fine: that is the desired end state.
        scheduler = get_flow_scheduler()
        scheduler.remove_workflow_job(workflow_id, strict=True)
        if workflow.schedule_job_id:
            set_schedule_job_id(workflow_id, None)

        # Remove price alert if any
        price_monitor = get_flow_price_monitor()
        price_monitor.remove_alert(workflow_id)

        # Remove order-update watch if any
        order_monitor = get_flow_order_update_monitor()
        order_monitor.remove_watch(workflow_id)

        # Give back any market-data subscription the workflow opened. The
        # websocket client is a process-wide singleton, so a subscription left
        # behind is held for the life of the worker and counts against the
        # per-broker symbol ceiling that /trading and the sandbox engine share.
        release_workflow_subscriptions(workflow_id)

        # Update workflow as inactive
        if not db_deactivate(workflow_id):
            logger.error(f"Failed to persist inactive state for workflow {workflow_id}")
            return jsonify({"error": "Could not deactivate workflow"}), 500

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
        return jsonify(result), _execution_status_code(result)
    except Exception as e:
        logger.exception(f"Failed to execute workflow {workflow_id}: {e}")
        return jsonify({"error": str(e)}), 500


@flow_bp.route("/api/workflows/<int:workflow_id>/executions", methods=["GET"])
@check_session_validity
def get_workflow_executions(workflow_id):
    """Get execution history for a workflow"""
    from database.flow_db import get_workflow_executions

    # Clamped. The raw value went straight into SQL LIMIT, where SQLite reads a
    # negative as "no limit" -- so ?limit=-1 serialised every execution row, each
    # carrying a full log blob, into one response. `type=int` also yields None on
    # a non-numeric value, which reaches LIMIT as unlimited too.
    requested = request.args.get("limit", EXECUTIONS_DEFAULT_LIMIT, type=int)
    limit = min(max(requested or EXECUTIONS_DEFAULT_LIMIT, 1), EXECUTIONS_MAX_LIMIT)
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
    if not new_token:
        return jsonify({"error": "Failed to regenerate token"}), 500

    # Checked, not just called. The secret's return value was discarded, so a
    # failed rotation still reported success and the caller kept using a secret
    # they believed had been replaced.
    if not regenerate_webhook_secret(workflow_id):
        return jsonify({"error": "Failed to regenerate secret"}), 500

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


def _webhook_token_key():
    """Rate-limit key naming the workflow instead of the caller."""
    token = (request.view_args or {}).get("token") or ""
    return f"flow-webhook:{token}"


# Two limits at the same budget, because they bound different things and neither
# subsumes the other.
#
# By caller address: the only key that can stop someone walking the token space.
# Every guess carries a different token, so a token-keyed limit would score each
# one against an empty bucket and never fire, while each miss still costs a
# database lookup. This is also exactly what /chartink enforces, so Flow is not
# weaker than the surface it replaces.
#
# By token: bounds what one leaked token can do to the broker account no matter
# how many addresses replay it. The token is the credential here (the payload
# secret is optional), so this is the limit that caps real order flow.
#
# Both are shared scopes so /webhook/<token> and /webhook/<token>/<symbol> draw
# on one budget. Per-endpoint buckets would hand the same workflow twice the
# configured rate simply for alternating between two spellings of itself.
_webhook_caller_limit = limiter.shared_limit(WEBHOOK_RATE_LIMIT, scope="flow_webhook_caller")
_webhook_workflow_limit = limiter.shared_limit(
    WEBHOOK_RATE_LIMIT, scope="flow_webhook_workflow", key_func=_webhook_token_key
)


@flow_bp.errorhandler(429)
def _rate_limited(error):
    """Answer an over-limit caller with 429 JSON rather than the app-wide redirect.

    app.py's 429 handler returns JSON only for paths under `/api/` and redirects
    everything else to the React `/rate-limited` page. A browser reads that; an
    automated caller does not. TradingView would follow the redirect, receive
    HTML and 200, and record the alert as delivered, so a throttled workflow
    would be indistinguishable from a working one and nothing would surface the
    loss. A blueprint handler is consulted ahead of the application one, so this
    corrects the answer for Flow without changing it for the rest of the product.
    """
    retry_after = 60
    breached = getattr(error, "limit", None)
    try:
        retry_after = int(breached.limit.get_expiry())
    except (AttributeError, TypeError, ValueError):
        pass

    response = jsonify(
        {
            "status": "error",
            "message": "Rate limit exceeded. Please slow down your requests.",
            "limit": getattr(error, "description", None),
            "retry_after": retry_after,
        }
    )
    response.status_code = 429
    response.headers["Retry-After"] = str(retry_after)
    return response


def _read_webhook_payload():
    """Read a webhook body whatever shape the sender used.

    `request.get_json()` refuses anything not declared `application/json` and
    Flask answers 415 before the handler runs. External platforms are exactly
    the callers that cannot set a header: a TradingView alert left on its
    default plain-text message never reached the workflow at all, and neither
    did a form-encoded post.

    Order matters. The body is parsed as JSON first regardless of what the
    sender declared, because a sender that cannot set a Content-Type still
    posts JSON far more often than not. Only a body that is not JSON falls
    through to form fields, then to raw text under `message`.
    """
    raw = request.get_data(as_text=True) or ""
    text = raw.strip()

    if text:
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed
        if parsed is not None:
            # Valid JSON that is not an object: a list, a bare string or number.
            # Keep the decoded value, and the raw text so a template can read
            # either without the workflow having to know which arrived.
            return {"message": text, "payload": parsed}

    # Form-encoded (ChartInk and friends). `request.form` is empty for the
    # content types handled above, so this cannot shadow a JSON body.
    if request.form:
        return dict(request.form)

    return {"message": text} if text else {}


def _execute_webhook(token, webhook_data=None, url_secret=None):
    """Internal function to execute webhook"""
    import hmac

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
            # A secret carried in the payload requires a payload with fields,
            # so plain text is not accepted on this path. It is not that the
            # text could not be parsed: it is that an unauthenticated body must
            # not reach the workflow, and text has nowhere to put the secret.
            # Send JSON, or switch the workflow to URL auth.
            if not provided_secret:
                return jsonify(
                    {
                        "error": (
                            "Missing webhook secret in payload. Send JSON with a 'secret' "
                            "field. Plain text cannot carry one: switch the webhook to URL "
                            "auth to authenticate with ?secret=... instead."
                        )
                    }
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
        status = result.get("status", "success")
        # On failure, report the run's own message. Overwriting it left a caller
        # such as TradingView with HTTP 200 and the text "Workflow 'X' triggered"
        # whether the orders were placed or the broker rejected them, so nothing
        # could alert or retry.
        triggered = f"Workflow '{workflow.name}' triggered"
        message = triggered if status == "success" else (result.get("message") or triggered)
        return jsonify(
            {
                "status": status,
                "message": message,
                "errors": result.get("errors"),
                "execution_id": result.get("execution_id"),
                "workflow_id": workflow.id,
            }
        ), _execution_status_code(result)
    except Exception as e:
        logger.exception(f"Webhook execution failed for workflow {workflow.id}: {e}")
        return jsonify({"error": str(e)}), 500


@flow_bp.route("/webhook/<token>", methods=["POST"])
@_webhook_caller_limit
@_webhook_workflow_limit
def trigger_webhook(token):
    """
    Trigger a workflow via webhook (CSRF exempt)

    Authentication can be done via:
    1. URL query parameter: ?secret=your_secret (for Chartink, etc.)
    2. Payload field: {"secret": "your_secret", ...} (for TradingView, etc.)
    """
    url_secret = request.args.get("secret")
    payload = _read_webhook_payload()
    return _execute_webhook(token, webhook_data=payload, url_secret=url_secret)


@flow_bp.route("/webhook/<token>/<symbol>", methods=["POST"])
@_webhook_caller_limit
@_webhook_workflow_limit
def trigger_webhook_with_symbol(token, symbol):
    """
    Trigger a workflow via webhook with symbol in URL path (CSRF exempt)

    The symbol is automatically injected into the webhook data.
    """
    url_secret = request.args.get("secret")
    payload = _read_webhook_payload()
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
    # trigger's schedule and any price/order watch are snapshotted at
    # activation, so a trigger change is re-armed here rather than waiting for
    # the user to cycle the workflow.
    needs_reactivate = False
    if was_active and trigger_changed:
        try:
            _reregister_trigger(updated)
        except Exception:
            # Fail closed rather than leave it active on a stale registration.
            logger.exception(
                f"Could not re-register the trigger for workflow {workflow_id}; "
                "deactivating it so it cannot run a stale configuration"
            )
            _rollback_activation(workflow_id)
            needs_reactivate = True

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
                "Trigger changed and could not be re-registered, so the workflow "
                "was deactivated. Activate it again when the trigger is valid."
                if needs_reactivate
                else "Workflow replaced. Changes apply from the next run."
            ),
        }
    )


# === Index Symbols Lot Size Routes ===


@flow_bp.route("/api/index-symbols", methods=["GET"])
@check_session_validity
def get_index_symbols_lot_sizes():
    """Lot sizes for every underlying the options nodes offer.

    Named for the index options it originally covered; it now also answers for
    the MCX commodities, which the Options Order and Multi-Leg nodes list
    alongside them. The route name is left alone because the frontend caches
    against it.

    An underlying with no usable lot size is omitted rather than returned with a
    null, so the dropdown never offers something the executor would then refuse
    to size.
    """
    from database.symbol import SymToken, db_session
    from database.token_db_enhanced import extract_underlying_from_symbol
    from services.flow_executor_service import MCX_OPTION_UNDERLYINGS, symbol_prefix_filter

    # Define index symbols to look up
    nse_indices = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"]
    bse_indices = ["SENSEX", "BANKEX", "SENSEX50"]

    def _lot_size(index_name: str, exchange: str) -> int | None:
        """Lot size for an index from the master contract.

        Matches SymToken.name first - it is the indexed column and is correct on
        most brokers - then falls back to the OpenAlgo symbol. `name` holds the
        underlying root only where the broker's master contract put it there;
        some ship the contract description instead, which left this endpoint
        returning an empty list and the Options Order node with no underlyings
        to choose from. The symbol column is normalized by OpenAlgo, so it reads
        the same on every broker.

        The prefix alone is not enough - symbols starting "NIFTY" also include
        NIFTYNXT50 at a different lot size - so each candidate is confirmed with
        the same extractor the underlying dropdown uses.
        """
        record = (
            db_session.query(SymToken.lotsize)
            .filter(
                SymToken.name == index_name,
                SymToken.exchange == exchange,
                SymToken.lotsize.isnot(None),
                SymToken.lotsize > 0,
            )
            .first()
        )
        if record and record[0]:
            return int(record[0])

        candidates = (
            db_session.query(SymToken.symbol, SymToken.lotsize)
            .filter(
                symbol_prefix_filter(SymToken.symbol, index_name),
                SymToken.exchange == exchange,
                SymToken.lotsize.isnot(None),
                SymToken.lotsize > 0,
            )
            .yield_per(200)
        )
        for symbol, lotsize in candidates:
            if extract_underlying_from_symbol(symbol, exchange) == index_name:
                return int(lotsize)
        return None

    results = []

    try:
        for index_name, exchange in (
            [(n, "NFO") for n in nse_indices]
            + [(n, "BFO") for n in bse_indices]
            # MCX options trade on MCX itself, so the lot size is read from the
            # same exchange the option is listed on.
            + [(n, "MCX") for n in MCX_OPTION_UNDERLYINGS]
        ):
            lot_size = _lot_size(index_name, exchange)
            if lot_size:
                results.append(
                    {
                        "value": index_name,
                        "label": index_name,
                        "exchange": exchange,
                        "lotSize": lot_size,
                    }
                )

        return jsonify({"status": "success", "data": results})

    except Exception as e:
        logger.exception(f"Error fetching index symbols lot sizes: {e}")
        return jsonify({"error": "Failed to fetch lot sizes"}), 500


# A margin basket is capped at 50 positions by margin_service, so a lookup can
# never legitimately need more pairs than that. Bounding it keeps a crafted or
# buggy caller from turning one request into an unbounded IN clause.
MAX_LOT_SIZE_LOOKUP = 50


@flow_bp.route("/api/symbol-lotsizes", methods=["POST"])
@check_session_validity
def get_symbol_lot_sizes():
    """Lot sizes for a bounded set of exact (symbol, exchange) pairs.

    The index-symbols endpoint above only covers index underlyings, and
    /search/api/search matches by prefix - asking it for a lot size while the
    user is still typing can scan thousands of contracts. This resolves exact
    symbols only, so the Margin Calculator's per-leg quantity can be entered in
    lots the way the options tools do.

    Batched deliberately: a 50-leg basket opened in the editor would otherwise
    issue 50 requests. One grouped query answers the whole basket.

    A pair resolves to null - not an error - when the symbol is unknown or the
    master contract carries no usable lot size, so the caller can fall back to
    plain units instead of blocking on a lookup that will never succeed. That
    is a different condition from the request failing, and the caller is
    expected to present them differently.
    """
    from sqlalchemy import tuple_

    from database.symbol import SymToken, db_session

    payload = request.get_json(silent=True) or {}
    raw_pairs = payload.get("symbols")
    if not isinstance(raw_pairs, list) or not raw_pairs:
        return jsonify({"status": "error", "message": "symbols must be a non-empty array"}), 400
    if len(raw_pairs) > MAX_LOT_SIZE_LOOKUP:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": f"at most {MAX_LOT_SIZE_LOOKUP} symbols per request",
                }
            ),
            400,
        )

    pairs = []
    for entry in raw_pairs:
        if not isinstance(entry, dict):
            return jsonify({"status": "error", "message": "each symbol must be an object"}), 400
        symbol = str(entry.get("symbol") or "").strip().upper()
        exchange = str(entry.get("exchange") or "").strip().upper()
        if not symbol or not exchange:
            return (
                jsonify({"status": "error", "message": "symbol and exchange are required"}),
                400,
            )
        pairs.append((symbol, exchange))

    try:
        rows = (
            db_session.query(SymToken.symbol, SymToken.exchange, SymToken.lotsize)
            .filter(
                tuple_(SymToken.symbol, SymToken.exchange).in_(set(pairs)),
                SymToken.lotsize.isnot(None),
                SymToken.lotsize > 0,
            )
            .all()
        )
        # lotsize is a float column and some segments carry fractional sizes
        # (Delta Exchange crypto contracts store 0.0001). int() would truncate
        # those to 0, and a caller that trusted it would divide a quantity by
        # zero. A fraction of a unit is not a lot, so it resolves to null like
        # any other contract with no usable lot size.
        found = {}
        for symbol, exchange, lotsize in rows:
            size = int(lotsize)
            if size >= 1 and size == lotsize:
                found[f"{exchange}:{symbol}"] = size
        # Echo every requested pair, so a caller can tell "looked up, not found"
        # from "not looked up" without diffing its own request.
        lot_sizes = {f"{exchange}:{symbol}": found.get(f"{exchange}:{symbol}") for symbol, exchange in pairs}
        return jsonify({"status": "success", "lotSizes": lot_sizes})
    except Exception as e:
        logger.exception(f"Error fetching lot sizes for {len(pairs)} pair(s): {e}")
        return jsonify({"status": "error", "message": "Failed to fetch lot sizes"}), 500


def _sorted_expiry_codes(raw_dates: list) -> list[str]:
    """Normalize broker expiry strings to DDMMMYY and sort them chronologically.

    Brokers return expiries in several formats and in no guaranteed order, but
    a symbol is built from the DDMMMYY code and the builder offers "nearest
    first". An unparseable entry is kept, sorted last, rather than dropped -
    hiding a listed expiry is worse than showing one out of order.
    """
    codes: list[str] = []
    for raw in raw_dates:
        if not isinstance(raw, str) or not raw.strip():
            continue
        text = raw.strip().upper()
        parsed = None
        for fmt in ("%d-%b-%y", "%d-%b-%Y", "%d%b%y", "%d%b%Y"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        codes.append(parsed.strftime("%d%b%y").upper() if parsed else text)

    def sort_key(code: str):
        try:
            return (0, datetime.strptime(code, "%d%b%y"))
        except ValueError:
            return (1, datetime.max)

    # dict.fromkeys dedupes while keeping first-seen order for unparseable codes.
    return sorted(dict.fromkeys(codes), key=sort_key)


#: Strikes returned either side of ATM. Enough to reach a deep-ITM or far-OTM
#: leg without shipping a whole chain into a sidebar dropdown.
OPTION_STRIKE_WINDOW = 25


@flow_bp.route("/api/option-strikes", methods=["GET"])
@check_session_validity
def get_option_strikes():
    """Listed expiries and strikes for one underlying, for the manual leg builder.

    A manually built leg can name an absolute strike and its own expiry. The
    editor should offer contracts the exchange actually lists rather than a free
    number and a typed date, so this answers with the master contract's own
    list: every strike carries the symbol it resolves to and its moneyness, and
    every relative expiry type carries the date it currently picks.

    Both halves come back in one response because the builder needs them
    together: pick an expiry, then a strike within it.

    Structure only - no per-strike broker quotes - because the builder needs the
    contract, not its price, and a quoted chain costs a multiquote round trip
    every time a dropdown opens.
    """
    from services.expiry_service import get_expiry_dates
    from services.flow_executor_service import resolve_option_exchanges
    from services.flow_node_contracts import (
        VALID_EXPIRY_TYPES,
        format_expiry_for_api,
        select_expiry,
    )
    from services.option_chain_service import get_option_chain
    from services.option_symbol_service import parse_underlying_symbol

    underlying = (request.args.get("underlying") or "").strip().upper()
    if not underlying:
        return jsonify({"status": "error", "message": "underlying is required"}), 400

    option_type = (request.args.get("optionType") or "CE").strip().upper()
    if option_type not in ("CE", "PE"):
        return jsonify({"status": "error", "message": "optionType must be CE or PE"}), 400

    requested_expiry = format_expiry_for_api(request.args.get("expiry") or "")
    requested_expiry_type = (request.args.get("expiryType") or "").strip().lower()

    api_key = get_current_api_key()
    if not api_key:
        return (
            jsonify(
                {"status": "error", "message": "API key not configured. Generate one at /apikey"}
            ),
            401,
        )

    try:
        _, fo_exchange = resolve_option_exchanges(
            underlying, (request.args.get("exchange") or "").strip().upper()
        )
        base_symbol, _embedded_expiry = parse_underlying_symbol(underlying)

        success, response, status_code = get_expiry_dates(
            symbol=base_symbol,
            exchange=fo_exchange,
            instrumenttype="options",
            api_key=api_key,
        )
        if not success:
            return jsonify(response), status_code

        listed = response.get("data") or []
        expiries = _sorted_expiry_codes(listed)
        if not expiries:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": f"No option expiries found for {base_symbol} on {fo_exchange}",
                    }
                ),
                404,
            )

        # Resolved once here with the executor's own selector, so the panel can
        # show which contract "current_week" means instead of leaving the author
        # to find out at run time.
        resolved = {
            expiry_type: select_expiry(listed, expiry_type)
            for expiry_type in sorted(VALID_EXPIRY_TYPES)
        }

        # Precedence matches the executor's: an explicit date wins over a
        # relative type, and an expiry the contract does not list falls back to
        # the nearest rather than answering with an empty strike list.
        expiry = ""
        if requested_expiry in expiries:
            expiry = requested_expiry
        elif requested_expiry_type:
            expiry = resolved.get(requested_expiry_type) or ""
        if expiry not in expiries:
            expiry = expiries[0]

        chain_ok, chain, chain_code = get_option_chain(
            underlying=base_symbol,
            exchange=fo_exchange,
            expiry_date=expiry,
            strike_count=OPTION_STRIKE_WINDOW,
            api_key=api_key,
            with_quotes=False,
        )
        if not chain_ok:
            return jsonify(chain), chain_code

        side = option_type.lower()
        strikes = [
            {
                "strike": row.get("strike"),
                "symbol": (row.get(side) or {}).get("symbol"),
                # ATM / ITMn / OTMn, which differ per side at the same strike.
                "label": (row.get(side) or {}).get("label"),
            }
            for row in chain.get("chain", []) or []
            if row.get("strike") is not None
        ]

        return jsonify(
            {
                "status": "success",
                "data": {
                    "underlying": underlying,
                    "exchange": fo_exchange,
                    "expiry": chain.get("expiry_date", expiry),
                    "expiries": expiries,
                    "resolved": resolved,
                    "optionType": option_type,
                    "strikes": strikes,
                    "atm": chain.get("atm_strike"),
                    "underlyingLtp": chain.get("underlying_ltp"),
                    "underlyingSymbol": chain.get("underlying_symbol"),
                },
            }
        )
    except Exception as e:
        logger.exception(f"Error fetching option strikes for {underlying}: {e}")
        return jsonify({"status": "error", "message": "Failed to fetch option strikes"}), 500
