# blueprints/flow.py
"""
Flow Blueprint - Visual Workflow Automation
Provides routes for managing and executing workflows
"""

from flask import Blueprint, request, jsonify, session
import logging
from datetime import datetime

from database.auth_db import get_api_key_for_tradingview
from utils.session import check_session_validity

logger = logging.getLogger(__name__)

flow_bp = Blueprint('flow', __name__, url_prefix='/flow')


def get_current_api_key():
    """Get API key for the current user from session"""
    username = session.get('user')
    if not username:
        return None
    return get_api_key_for_tradingview(username)


# === Workflow CRUD Routes ===

@flow_bp.route('/api/workflows', methods=['GET'])
@check_session_validity
def list_workflows():
    """List all workflows"""
    from database.flow_db import get_all_workflows, get_workflow_executions

    workflows = get_all_workflows()
    items = []

    for wf in workflows:
        executions = get_workflow_executions(wf.id, limit=1)
        last_exec = executions[0] if executions else None

        items.append({
            'id': wf.id,
            'name': wf.name,
            'description': wf.description,
            'is_active': wf.is_active,
            'webhook_enabled': wf.webhook_enabled,
            'created_at': wf.created_at.isoformat() if wf.created_at else None,
            'updated_at': wf.updated_at.isoformat() if wf.updated_at else None,
            'last_execution_status': last_exec.status if last_exec else None
        })

    return jsonify(items)


@flow_bp.route('/api/workflows', methods=['POST'])
@check_session_validity
def create_workflow():
    """Create a new workflow"""
    from database.flow_db import create_workflow

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    name = data.get('name', 'Untitled Workflow')
    description = data.get('description')
    nodes = data.get('nodes', [])
    edges = data.get('edges', [])

    workflow = create_workflow(
        name=name,
        description=description,
        nodes=nodes,
        edges=edges
    )

    if not workflow:
        return jsonify({'error': 'Failed to create workflow'}), 500

    return jsonify({
        'id': workflow.id,
        'name': workflow.name,
        'description': workflow.description,
        'nodes': workflow.nodes,
        'edges': workflow.edges,
        'is_active': workflow.is_active,
        'webhook_token': workflow.webhook_token,
        'webhook_secret': workflow.webhook_secret,
        'webhook_enabled': workflow.webhook_enabled,
        'webhook_auth_type': workflow.webhook_auth_type,
        'created_at': workflow.created_at.isoformat() if workflow.created_at else None,
        'updated_at': workflow.updated_at.isoformat() if workflow.updated_at else None
    }), 201


@flow_bp.route('/api/workflows/<int:workflow_id>', methods=['GET'])
@check_session_validity
def get_workflow(workflow_id):
    """Get a workflow by ID"""
    from database.flow_db import get_workflow

    workflow = get_workflow(workflow_id)
    if not workflow:
        return jsonify({'error': 'Workflow not found'}), 404

    return jsonify({
        'id': workflow.id,
        'name': workflow.name,
        'description': workflow.description,
        'nodes': workflow.nodes,
        'edges': workflow.edges,
        'is_active': workflow.is_active,
        'schedule_job_id': workflow.schedule_job_id,
        'webhook_token': workflow.webhook_token,
        'webhook_secret': workflow.webhook_secret,
        'webhook_enabled': workflow.webhook_enabled,
        'webhook_auth_type': workflow.webhook_auth_type,
        'created_at': workflow.created_at.isoformat() if workflow.created_at else None,
        'updated_at': workflow.updated_at.isoformat() if workflow.updated_at else None
    })


@flow_bp.route('/api/workflows/<int:workflow_id>', methods=['PUT'])
@check_session_validity
def update_workflow(workflow_id):
    """Update a workflow"""
    from database.flow_db import update_workflow

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    workflow = update_workflow(workflow_id, **data)
    if not workflow:
        return jsonify({'error': 'Workflow not found'}), 404

    return jsonify({
        'id': workflow.id,
        'name': workflow.name,
        'description': workflow.description,
        'nodes': workflow.nodes,
        'edges': workflow.edges,
        'is_active': workflow.is_active,
        'webhook_token': workflow.webhook_token,
        'webhook_secret': workflow.webhook_secret,
        'webhook_enabled': workflow.webhook_enabled,
        'webhook_auth_type': workflow.webhook_auth_type,
        'created_at': workflow.created_at.isoformat() if workflow.created_at else None,
        'updated_at': workflow.updated_at.isoformat() if workflow.updated_at else None
    })


@flow_bp.route('/api/workflows/<int:workflow_id>', methods=['DELETE'])
@check_session_validity
def delete_workflow(workflow_id):
    """Delete a workflow"""
    from database.flow_db import delete_workflow, get_workflow
    from services.flow_scheduler_service import get_flow_scheduler

    workflow = get_workflow(workflow_id)
    if not workflow:
        return jsonify({'error': 'Workflow not found'}), 404

    # Deactivate if active (removes scheduler job)
    if workflow.is_active:
        scheduler = get_flow_scheduler()
        scheduler.remove_workflow_job(workflow_id)

    if delete_workflow(workflow_id):
        return jsonify({'status': 'success', 'message': 'Workflow deleted'})
    else:
        return jsonify({'error': 'Failed to delete workflow'}), 500


# === Activation/Deactivation Routes ===

@flow_bp.route('/api/workflows/<int:workflow_id>/activate', methods=['POST'])
@check_session_validity
def activate_workflow(workflow_id):
    """Activate a workflow"""
    from database.flow_db import get_workflow, activate_workflow as db_activate, set_schedule_job_id
    from services.flow_scheduler_service import get_flow_scheduler
    from services.flow_price_monitor_service import get_flow_price_monitor

    workflow = get_workflow(workflow_id)
    if not workflow:
        return jsonify({'error': 'Workflow not found'}), 404

    if workflow.is_active:
        return jsonify({'status': 'already_active', 'message': 'Workflow is already active'})

    api_key = get_current_api_key()
    if not api_key:
        return jsonify({'error': 'API key not configured'}), 400

    nodes = workflow.nodes or []

    # Find trigger node to determine activation type
    trigger_node = next((n for n in nodes if n.get('type') in ['start', 'webhookTrigger', 'priceAlert']), None)
    if not trigger_node:
        return jsonify({'error': 'No trigger node found in workflow'}), 400

    trigger_type = trigger_node.get('type')
    trigger_data = trigger_node.get('data', {})

    try:
        if trigger_type == 'start':
            # Check for schedule configuration
            schedule_type = trigger_data.get('scheduleType')
            if schedule_type and schedule_type != 'manual':
                scheduler = get_flow_scheduler()
                scheduler.set_api_key(api_key)

                job_id = scheduler.add_workflow_job(
                    workflow_id=workflow_id,
                    schedule_type=schedule_type,
                    time_str=trigger_data.get('time', '09:15'),
                    days=trigger_data.get('days'),
                    execute_at=trigger_data.get('executeAt'),
                    interval_value=trigger_data.get('intervalValue'),
                    interval_unit=trigger_data.get('intervalUnit')
                )
                set_schedule_job_id(workflow_id, job_id)

        elif trigger_type == 'priceAlert':
            price_monitor = get_flow_price_monitor()
            price_monitor.add_alert(
                workflow_id=workflow_id,
                symbol=trigger_data.get('symbol', ''),
                exchange=trigger_data.get('exchange', 'NSE'),
                condition=trigger_data.get('condition', 'greater_than'),
                target_price=float(trigger_data.get('price', 0)),
                price_lower=trigger_data.get('priceLower'),
                price_upper=trigger_data.get('priceUpper'),
                percentage=trigger_data.get('percentage'),
                api_key=api_key
            )

        # Update workflow as active
        db_activate(workflow_id)

        return jsonify({
            'status': 'success',
            'message': f'Workflow activated with {trigger_type} trigger'
        })

    except Exception as e:
        logger.error(f"Failed to activate workflow {workflow_id}: {e}")
        return jsonify({'error': str(e)}), 500


@flow_bp.route('/api/workflows/<int:workflow_id>/deactivate', methods=['POST'])
@check_session_validity
def deactivate_workflow(workflow_id):
    """Deactivate a workflow"""
    from database.flow_db import get_workflow, deactivate_workflow as db_deactivate, set_schedule_job_id
    from services.flow_scheduler_service import get_flow_scheduler
    from services.flow_price_monitor_service import get_flow_price_monitor

    workflow = get_workflow(workflow_id)
    if not workflow:
        return jsonify({'error': 'Workflow not found'}), 404

    if not workflow.is_active:
        return jsonify({'status': 'already_inactive', 'message': 'Workflow is already inactive'})

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

        return jsonify({'status': 'success', 'message': 'Workflow deactivated'})

    except Exception as e:
        logger.error(f"Failed to deactivate workflow {workflow_id}: {e}")
        return jsonify({'error': str(e)}), 500


# === Execution Routes ===

@flow_bp.route('/api/workflows/<int:workflow_id>/execute', methods=['POST'])
@check_session_validity
def execute_workflow_now(workflow_id):
    """Execute a workflow immediately"""
    from database.flow_db import get_workflow
    from services.flow_executor_service import execute_workflow

    workflow = get_workflow(workflow_id)
    if not workflow:
        return jsonify({'error': 'Workflow not found'}), 404

    api_key = get_current_api_key()
    if not api_key:
        return jsonify({'error': 'API key not configured'}), 400

    try:
        result = execute_workflow(workflow_id, api_key=api_key)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Failed to execute workflow {workflow_id}: {e}")
        return jsonify({'error': str(e)}), 500


@flow_bp.route('/api/workflows/<int:workflow_id>/executions', methods=['GET'])
@check_session_validity
def get_workflow_executions(workflow_id):
    """Get execution history for a workflow"""
    from database.flow_db import get_workflow_executions

    limit = request.args.get('limit', 20, type=int)
    executions = get_workflow_executions(workflow_id, limit=limit)

    return jsonify([
        {
            'id': ex.id,
            'workflow_id': ex.workflow_id,
            'status': ex.status,
            'started_at': ex.started_at.isoformat() if ex.started_at else None,
            'completed_at': ex.completed_at.isoformat() if ex.completed_at else None,
            'logs': ex.logs,
            'error': ex.error
        }
        for ex in executions
    ])


# === Webhook Routes ===

@flow_bp.route('/api/workflows/<int:workflow_id>/webhook/enable', methods=['POST'])
@check_session_validity
def enable_webhook(workflow_id):
    """Enable webhook for a workflow"""
    from database.flow_db import enable_webhook

    result = enable_webhook(workflow_id)
    if result:
        return jsonify({'status': 'success', 'message': 'Webhook enabled'})
    return jsonify({'error': 'Failed to enable webhook'}), 500


@flow_bp.route('/api/workflows/<int:workflow_id>/webhook/disable', methods=['POST'])
@check_session_validity
def disable_webhook(workflow_id):
    """Disable webhook for a workflow"""
    from database.flow_db import disable_webhook

    result = disable_webhook(workflow_id)
    if result:
        return jsonify({'status': 'success', 'message': 'Webhook disabled'})
    return jsonify({'error': 'Failed to disable webhook'}), 500


@flow_bp.route('/api/workflows/<int:workflow_id>/webhook/regenerate', methods=['POST'])
@check_session_validity
def regenerate_webhook(workflow_id):
    """Regenerate webhook token"""
    from database.flow_db import regenerate_webhook_token

    new_token = regenerate_webhook_token(workflow_id)
    if new_token:
        return jsonify({'status': 'success', 'webhook_token': new_token})
    return jsonify({'error': 'Failed to regenerate token'}), 500


@flow_bp.route('/api/workflows/<int:workflow_id>/webhook/auth-type', methods=['POST'])
@check_session_validity
def set_webhook_auth(workflow_id):
    """Set webhook auth type"""
    from database.flow_db import set_webhook_auth_type

    data = request.get_json()
    auth_type = data.get('auth_type', 'payload')

    result = set_webhook_auth_type(workflow_id, auth_type)
    if result:
        return jsonify({'status': 'success', 'auth_type': auth_type})
    return jsonify({'error': 'Invalid auth type'}), 400


# === Webhook Trigger Route (CSRF Exempt) ===

@flow_bp.route('/webhook/<token>', methods=['POST'])
def trigger_webhook(token):
    """Trigger a workflow via webhook (CSRF exempt)"""
    from database.flow_db import get_workflow_by_webhook_token
    from services.flow_executor_service import execute_workflow
    import hmac
    import hashlib

    workflow = get_workflow_by_webhook_token(token)
    if not workflow:
        return jsonify({'error': 'Invalid webhook token'}), 404

    if not workflow.webhook_enabled:
        return jsonify({'error': 'Webhook is disabled'}), 403

    if not workflow.is_active:
        return jsonify({'error': 'Workflow is not active'}), 403

    # Validate secret if auth_type is payload
    if workflow.webhook_auth_type == 'payload':
        data = request.get_json() or {}
        provided_secret = data.get('secret') or ''
        stored_secret = workflow.webhook_secret or ''
        # Use constant-time comparison to prevent timing attacks
        if not hmac.compare_digest(provided_secret, stored_secret):
            return jsonify({'error': 'Invalid webhook secret'}), 403
        webhook_data = {k: v for k, v in data.items() if k != 'secret'}
    else:
        # For URL auth, secret was already validated via token
        webhook_data = request.get_json() or {}

    # Get API key from the workflow's associated user
    # For now, we need to store API key association with workflows
    # This is a simplified approach - in production you'd want proper user association
    api_key = get_current_api_key()
    if not api_key:
        # Try to get from settings or environment
        import os
        api_key = os.getenv('OPENALGO_API_KEY')

    if not api_key:
        return jsonify({'error': 'No API key configured for workflow execution'}), 500

    try:
        result = execute_workflow(workflow.id, webhook_data=webhook_data, api_key=api_key)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Webhook execution failed for workflow {workflow.id}: {e}")
        return jsonify({'error': str(e)}), 500


# === Monitor Status Route ===

@flow_bp.route('/api/monitor/status', methods=['GET'])
@check_session_validity
def get_monitor_status():
    """Get price monitor status"""
    from services.flow_price_monitor_service import get_flow_price_monitor

    monitor = get_flow_price_monitor()
    return jsonify(monitor.get_status())


# === Export/Import Routes ===

@flow_bp.route('/api/workflows/<int:workflow_id>/export', methods=['GET'])
@check_session_validity
def export_workflow(workflow_id):
    """Export a workflow"""
    from database.flow_db import get_workflow

    workflow = get_workflow(workflow_id)
    if not workflow:
        return jsonify({'error': 'Workflow not found'}), 404

    return jsonify({
        'name': workflow.name,
        'description': workflow.description,
        'nodes': workflow.nodes,
        'edges': workflow.edges,
        'version': '1.0',
        'exported_at': datetime.utcnow().isoformat()
    })


@flow_bp.route('/api/workflows/import', methods=['POST'])
@check_session_validity
def import_workflow():
    """Import a workflow"""
    from database.flow_db import create_workflow

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    name = data.get('name', 'Imported Workflow')
    description = data.get('description')
    nodes = data.get('nodes', [])
    edges = data.get('edges', [])

    workflow = create_workflow(
        name=f"{name} (imported)",
        description=description,
        nodes=nodes,
        edges=edges
    )

    if workflow:
        return jsonify({
            'status': 'success',
            'workflow_id': workflow.id
        }), 201
    return jsonify({'error': 'Failed to import workflow'}), 500
