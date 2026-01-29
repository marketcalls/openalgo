# blueprints/strategy_state.py

"""
Blueprint for Strategy State API endpoints.
Provides read-only access to Python strategy execution states and positions.
"""

from flask import Blueprint, jsonify, request
from database.strategy_state_db import (
    get_all_strategy_states,
    get_strategy_state_by_instance_id,
    delete_strategy_state,
    create_strategy_override,
    StrategyStateDbNotFoundError,
    StrategyStateNotFoundError,
    StrategyStateDbError,
)
from utils.session import check_session_validity
from utils.logging import get_logger

logger = get_logger(__name__)

strategy_state_bp = Blueprint('strategy_state_bp', __name__, url_prefix='/api')


@strategy_state_bp.route('/strategy-state', methods=['GET'])
@check_session_validity
def get_strategy_states():
    """
    Get all strategy execution states with positions and trade history.

    Returns:
        JSON response with list of strategy states
    """
    try:
        logger.debug("GET /api/strategy-state called")
        states = get_all_strategy_states()
        logger.debug(f"Found {len(states)} strategy states")

        # Calculate summary statistics for each strategy
        # Summary counts must match the Strategy Positions UI logic.
        for state in states:
            total_realized_pnl = 0
            total_unrealized_pnl = 0

            # UI sections:
            # - Open Positions: IN_POSITION, PENDING_ENTRY, PENDING_EXIT
            # - IDLE Positions (waiting to enter): IDLE
            # Exited trades are derived from trade_history (not from legs).
            open_positions_count = 0
            idle_positions_count = 0

            legs = state.get('legs', {})
            for _, leg in legs.items():
                realized = leg.get('realized_pnl', 0) or 0
                unrealized = leg.get('unrealized_pnl', 0) or 0
                total_realized_pnl += realized
                total_unrealized_pnl += unrealized

                leg_status = leg.get('status', '')
                if leg_status in ['IN_POSITION', 'PENDING_ENTRY', 'PENDING_EXIT']:
                    open_positions_count += 1
                elif leg_status == 'IDLE':
                    idle_positions_count += 1

            # Exited trades: show trade history entries (main + hedge legs)
            trade_history = state.get('trade_history', [])
            trade_history_pnl = sum(t.get('pnl', 0) or 0 for t in trade_history)

            state['summary'] = {
                'total_realized_pnl': total_realized_pnl,
                'total_unrealized_pnl': total_unrealized_pnl,
                'total_pnl': total_realized_pnl + total_unrealized_pnl + trade_history_pnl,
                'trade_history_pnl': trade_history_pnl,
                'open_positions_count': open_positions_count,
                'idle_positions_count': idle_positions_count,
                'total_trades': len(trade_history)
            }

        return jsonify({
            'status': 'success',
            'data': states
        })

    except Exception as e:
        logger.error(f"Error in get_strategy_states: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@strategy_state_bp.route('/strategy-state/<path:instance_id>', methods=['GET'])
@check_session_validity
def get_strategy_state(instance_id):
    """
    Get a specific strategy state by instance_id.

    Args:
        instance_id: The unique instance identifier

    Returns:
        JSON response with strategy state
    """
    try:
        state = get_strategy_state_by_instance_id(instance_id)

        if not state:
            return jsonify({
                'status': 'error',
                'message': f'Strategy state not found: {instance_id}'
            }), 404

        return jsonify({
            'status': 'success',
            'data': state
        })

    except Exception as e:
        logger.error(f"Error in get_strategy_state: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@strategy_state_bp.route('/strategy-state/<path:instance_id>', methods=['DELETE'])
@check_session_validity
def delete_strategy_state_endpoint(instance_id):
    """
    Delete a specific strategy state by instance_id.

    Args:
        instance_id: The unique instance identifier

    Returns:
        JSON response with deletion status
    """
    try:
        logger.debug(f"DELETE request for instance_id: {instance_id}")

        try:
            delete_strategy_state(instance_id)
        except StrategyStateNotFoundError:
            logger.warning(f"Strategy state not found: {instance_id}")
            return jsonify({
                'status': 'error',
                'message': f'Strategy state not found: {instance_id}'
            }), 404
        except StrategyStateDbNotFoundError as e:
            logger.error(f"Strategy State DB missing: {e}")
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500
        except StrategyStateDbError as e:
            logger.error(f"Strategy State DB error deleting {instance_id}: {e}")
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500

        logger.debug(f"Strategy state deleted successfully: {instance_id}")
        return jsonify({
            'status': 'success',
            'message': f'Strategy state deleted: {instance_id}'
        })

    except Exception as e:
        logger.error(f"Error in delete_strategy_state: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@strategy_state_bp.route('/strategy-state/<path:instance_id>/override', methods=['POST'])
@check_session_validity
def create_strategy_override_endpoint(instance_id):
    """
    Create a strategy override for SL or Target price modification.
    The running strategy will poll for and apply these overrides.

    Args:
        instance_id: The unique instance identifier

    Request body:
        {
            "leg_key": "CE_SPREAD_CE_SELL",
            "override_type": "sl_price" | "target_price",
            "new_value": 123.45
        }

    Returns:
        JSON response with created override or error
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({
                'status': 'error',
                'message': 'Request body is required'
            }), 400

        leg_key = data.get('leg_key')
        override_type = data.get('override_type')
        new_value = data.get('new_value')

        # Validate required fields
        if not leg_key:
            return jsonify({
                'status': 'error',
                'message': 'leg_key is required'
            }), 400

        if not override_type:
            return jsonify({
                'status': 'error',
                'message': 'override_type is required'
            }), 400

        if override_type not in ('sl_price', 'target_price'):
            return jsonify({
                'status': 'error',
                'message': 'override_type must be sl_price or target_price'
            }), 400

        if new_value is None:
            return jsonify({
                'status': 'error',
                'message': 'new_value is required'
            }), 400

        try:
            new_value = float(new_value)
        except (TypeError, ValueError):
            return jsonify({
                'status': 'error',
                'message': 'new_value must be a valid number'
            }), 400

        if new_value < 0:
            return jsonify({
                'status': 'error',
                'message': 'new_value must be non-negative'
            }), 400

        # Verify the strategy instance exists
        state = get_strategy_state_by_instance_id(instance_id)
        if not state:
            return jsonify({
                'status': 'error',
                'message': f'Strategy state not found: {instance_id}'
            }), 404

        # Verify the leg exists in the strategy
        legs = state.get('legs', {})
        if leg_key not in legs:
            return jsonify({
                'status': 'error',
                'message': f'Leg not found: {leg_key}'
            }), 404

        # Verify the leg is in a position (can only modify active positions)
        leg = legs[leg_key]
        if leg.get('status') != 'IN_POSITION':
            return jsonify({
                'status': 'error',
                'message': f'Can only modify SL/Target for legs in IN_POSITION status. Current status: {leg.get("status")}'
            }), 400

        # Create the override
        try:
            result = create_strategy_override(
                instance_id=instance_id,
                leg_key=leg_key,
                override_type=override_type,
                new_value=new_value,
            )
        except StrategyStateDbNotFoundError as e:
            # Server-side issue (DB missing)
            logger.error(f"Strategy State DB missing: {e}")
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500
        except StrategyStateDbError as e:
            logger.error(f"Strategy State DB error creating override: {e}")
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500

        logger.info(f"Created override for {instance_id}/{leg_key}: {override_type}={new_value}")

        return jsonify({
            'status': 'success',
            'message': f'{override_type.replace("_", " ").title()} override created. Will be applied within 5 seconds.',
            'data': result
        })

    except Exception as e:
        logger.error(f"Error in create_strategy_override: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500
