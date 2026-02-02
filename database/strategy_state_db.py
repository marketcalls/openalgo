# database/strategy_state_db.py

"""
Database access layer for strategy_state.db
This database stores Python strategy execution states and trade history.
"""

import os
import json
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Float, Boolean
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.pool import NullPool
from utils.logging import get_logger

logger = get_logger(__name__)


class StrategyStateError(Exception):
    """Base exception for strategy state database operations."""


class StrategyStateDbNotFoundError(StrategyStateError):
    """Raised when the strategy state database file is missing."""


class StrategyStateNotFoundError(StrategyStateError):
    """Raised when a requested strategy state record is missing."""


class StrategyStateDbError(StrategyStateError):
    """Raised for unexpected database errors."""


class StrategyStateDuplicateLegError(StrategyStateError):
    """Raised when a duplicate leg is detected for a strategy state."""


# Strategy state database path
DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'db', 'strategy_state.db')
DB_PATH = os.getenv('STRATEGY_STATE_DB_PATH', DEFAULT_DB_PATH)
DATABASE_URL = f'sqlite:///{DB_PATH}'

# Create engine with NullPool for SQLite
engine = create_engine(
    DATABASE_URL,
    poolclass=NullPool,
    connect_args={'check_same_thread': False}
)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


class StrategyExecutionState(Base):
    """Model for strategy_execution_state table"""
    __tablename__ = 'strategy_execution_state'
    
    id = Column(Integer, primary_key=True)
    strategy_name = Column(String(255), nullable=False)
    instance_id = Column(String(100), nullable=False, unique=True)
    user_id = Column(String(100), nullable=True)
    status = Column(String(20), nullable=False)  # RUNNING, PAUSED, COMPLETED, ERROR
    state_data = Column(Text, nullable=True)  # JSON blob
    last_heartbeat = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=True)
    last_updated = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    strategy_metadata = Column('metadata', Text, nullable=True)  # JSON blob - use 'metadata' as column name
    version = Column(Integer, nullable=True)
    pid = Column(Integer, nullable=True)


class StrategyOverride(Base):
    """
    Model for strategy_overrides table.
    Used for live SL/Target price modifications from UI.
    The strategy will poll for pending overrides and apply them.
    """
    __tablename__ = 'strategy_overrides'
    
    id = Column(Integer, primary_key=True)
    instance_id = Column(String(100), nullable=False, index=True)
    leg_key = Column(String(100), nullable=False)
    override_type = Column(String(20), nullable=False)  # 'sl_price' or 'target_price'
    new_value = Column(Float, nullable=False)
    applied = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, nullable=False)
    applied_at = Column(DateTime, nullable=True)


def get_all_strategy_states():
    """
    Get all strategy states with parsed state_data JSON.
    
    Returns:
        list: List of strategy state dictionaries
    """
    try:
        # Check if database file exists
        if not os.path.exists(DB_PATH):
            logger.warning(f"Strategy state database not found at {DB_PATH}")
            return []
        
        states = StrategyExecutionState.query.order_by(
            StrategyExecutionState.last_updated.desc()
        ).all()
        
        result = []
        for state in states:
            state_dict = {
                'id': state.id,
                'strategy_name': state.strategy_name,
                'instance_id': state.instance_id,
                'user_id': state.user_id,
                'status': state.status,
                'last_heartbeat': state.last_heartbeat.isoformat() if state.last_heartbeat else None,
                'created_at': state.created_at.isoformat() if state.created_at else None,
                'last_updated': state.last_updated.isoformat() if state.last_updated else None,
                'completed_at': state.completed_at.isoformat() if state.completed_at else None,
                'version': state.version,
                'pid': state.pid,
                'state_data': None,
                'is_state_data_malformed': False,
                'config': None,
                'legs': {},
                'trade_history': [],
                'orchestrator': None
            }
            
            # Parse state_data JSON
            if state.state_data:
                try:
                    parsed_state = json.loads(state.state_data)
                    state_dict['state_data'] = parsed_state
                    state_dict['config'] = parsed_state.get('config', {})
                    state_dict['legs'] = parsed_state.get('legs', {})
                    state_dict['trade_history'] = parsed_state.get('trade_history', [])
                    state_dict['orchestrator'] = parsed_state.get('orchestrator', {})
                except json.JSONDecodeError as e:
                    state_dict['is_state_data_malformed'] = True
                    logger.error(f"Error parsing state_data for {state.instance_id}: {e}")
            
            # Parse metadata JSON - always include key for consistent schema
            if state.strategy_metadata:
                try:
                    state_dict['metadata'] = json.loads(state.strategy_metadata)
                except json.JSONDecodeError:
                    state_dict['metadata'] = None
            else:
                state_dict['metadata'] = None
            
            result.append(state_dict)
        
        return result
    
    except Exception as e:
        logger.error(f"Error fetching strategy states: {e}")
        return []
    finally:
        db_session.remove()


def get_strategy_state_by_instance_id(instance_id: str):
    """
    Get a specific strategy state by instance_id.
    
    Args:
        instance_id: The unique instance identifier
        
    Returns:
        dict: Strategy state dictionary or None
    """
    try:
        if not os.path.exists(DB_PATH):
            return None
        
        state = StrategyExecutionState.query.filter_by(instance_id=instance_id).first()
        
        if not state:
            return None
        
        state_dict = {
            'id': state.id,
            'strategy_name': state.strategy_name,
            'instance_id': state.instance_id,
            'user_id': state.user_id,
            'status': state.status,
            'last_heartbeat': state.last_heartbeat.isoformat() if state.last_heartbeat else None,
            'created_at': state.created_at.isoformat() if state.created_at else None,
            'last_updated': state.last_updated.isoformat() if state.last_updated else None,
            'completed_at': state.completed_at.isoformat() if state.completed_at else None,
            'version': state.version,
            'pid': state.pid,
            'state_data': None,
            'is_state_data_malformed': False,
            'config': None,
            'legs': {},
            'trade_history': [],
            'orchestrator': None
        }
        
        if state.state_data:
            try:
                parsed_state = json.loads(state.state_data)
                state_dict['state_data'] = parsed_state
                state_dict['config'] = parsed_state.get('config', {})
                state_dict['legs'] = parsed_state.get('legs', {})
                state_dict['trade_history'] = parsed_state.get('trade_history', [])
                state_dict['orchestrator'] = parsed_state.get('orchestrator', {})
            except json.JSONDecodeError as e:
                state_dict['is_state_data_malformed'] = True
                logger.error(f"Error parsing state_data for {instance_id}: {e}")
        
        # Parse metadata JSON - always include key for consistent schema
        if state.strategy_metadata:
            try:
                state_dict['metadata'] = json.loads(state.strategy_metadata)
            except json.JSONDecodeError:
                state_dict['metadata'] = None
        else:
            state_dict['metadata'] = None
        
        return state_dict
    
    except Exception as e:
        logger.error(f"Error fetching strategy state {instance_id}: {e}")
        return None
    finally:
        db_session.remove()


def delete_strategy_state(instance_id: str) -> None:
    """Delete a strategy state by instance_id.

    Args:
        instance_id: The unique instance identifier

    Raises:
        StrategyStateDbNotFoundError: If the DB file is missing
        StrategyStateNotFoundError: If the record does not exist
        StrategyStateDbError: For other unexpected DB errors
    """
    try:
        if not os.path.exists(DB_PATH):
            raise StrategyStateDbNotFoundError("Strategy state database not found")

        state = StrategyExecutionState.query.filter_by(instance_id=instance_id).first()
        if not state:
            raise StrategyStateNotFoundError("Strategy state not found")

        db_session.delete(state)
        db_session.commit()
        logger.info(f"Deleted strategy state: {instance_id}")

    except (StrategyStateDbNotFoundError, StrategyStateNotFoundError):
        # Let caller handle expected error conditions
        db_session.rollback()
        raise

    except Exception as e:
        logger.error(f"Error deleting strategy state {instance_id}: {e}")
        db_session.rollback()
        raise StrategyStateDbError(f"Database error: {str(e)}") from e

    finally:
        db_session.remove()


def add_manual_strategy_leg(
    *,
    instance_id: str,
    leg_key: str,
    symbol: str,
    exchange: str,
    product: str,
    quantity: int,
    side: str,
    entry_price: float | None,
    entry_time: datetime | None,
    sl_price: float | None,
    target_price: float | None,
    leg_pair_name: str | None,
    is_main_leg: bool,
    sl_percent: float | None,
    target_percent: float | None,
    reentry_limit: int | None = None,
    reexecute_limit: int | None = None,
    status: str = "IN_POSITION",
    wait_trade_percent: float | None = None,
    wait_baseline_price: float | None = None,
) -> dict:
    """Append a manual leg to a strategy state.

    Args:
        instance_id: Strategy instance identifier.
        leg_key: Unique leg key for the strategy.
        symbol: Symbol without exchange prefix.
        exchange: Exchange name.
        product: Product type (MIS/NRML/CNC).
        quantity: Position quantity (positive integer).
        side: BUY or SELL.
        entry_price: Entry price from broker position.
        entry_time: Entry timestamp.
        sl_price: Computed stop loss price.
        target_price: Computed target price.
        leg_pair_name: Optional leg pair name.
        is_main_leg: True if main leg.
        sl_percent: Optional SL percent.
        target_percent: Optional target percent.

    Returns:
        dict: Updated strategy state data.
    """
    try:
        if not os.path.exists(DB_PATH):
            raise StrategyStateDbNotFoundError('Strategy state database not found')

        state = StrategyExecutionState.query.filter_by(instance_id=instance_id).first()
        if not state:
            raise StrategyStateNotFoundError('Strategy state not found')

        if not state.state_data:
            raise StrategyStateDbError('Strategy state data is empty')

        try:
            parsed_state = json.loads(state.state_data)
        except json.JSONDecodeError as exc:
            raise StrategyStateDbError('Strategy state data is malformed') from exc

        legs = parsed_state.get('legs') or {}

        # Check for duplicate legs with same characteristics
        for existing_leg in legs.values():
            # Skip if leg data is None or not a dict
            if not existing_leg:
                continue
            
            # Only check legs that are in position
            if existing_leg.get('status') != 'IN_POSITION':
                continue
            
            # Core fields that must always match
            symbol_match = existing_leg.get('symbol') == symbol
            side_match = existing_leg.get('side') == side
            qty_match = int(existing_leg.get('quantity') or 0) == int(quantity)
            
            # Optional fields - only check if they exist in the existing leg
            # This handles backward compatibility with legs created before exchange/product were stored
            exchange_match = True
            product_match = True
            
            if existing_leg.get('exchange') is not None:
                exchange_match = existing_leg.get('exchange') == exchange
            
            if existing_leg.get('product') is not None:
                product_match = existing_leg.get('product') == product
            
            if symbol_match and side_match and qty_match and exchange_match and product_match:
                raise StrategyStateDuplicateLegError('Similar open position already exists in this strategy')

        legs[leg_key] = {
            'leg_type': 'MANUAL',
            'status': status,
            'symbol': symbol,
            'exchange': exchange,
            'product': product,
            'entry_price': entry_price,
            'entry_time': entry_time.isoformat() if entry_time else None,
            'sl_price': sl_price,
            'target_price': target_price,
            'reentry_count': 0,
            'reexecute_count': 0,
            'quantity': quantity,
            'realized_pnl': 0,
            'unrealized_pnl': 0,
            'total_pnl': 0,
            'leg_pair_name': leg_pair_name,
            'side': side,
            'is_main_leg': is_main_leg,
            'sl_percent': sl_percent,
            'target_percent': target_percent,
            'reentry_limit': reentry_limit,
            'reexecute_limit': reexecute_limit,
            'wait_trade_percent': wait_trade_percent,
            'wait_baseline_price': wait_baseline_price,
        }

        parsed_state['legs'] = legs
        state.state_data = json.dumps(parsed_state)
        state.last_updated = datetime.utcnow()
        
        # Force SQLAlchemy to detect the change
        from sqlalchemy.orm import attributes
        attributes.flag_modified(state, 'state_data')
        
        # Create a MANUAL_SYNC override to notify the running strategy
        sync_override = StrategyOverride(
            instance_id=instance_id,
            leg_key=leg_key,
            override_type='MANUAL_SYNC',
            new_value=0.0,
            applied=False,
            created_at=datetime.utcnow()
        )
        db_session.add(sync_override)
        
        db_session.flush()
        db_session.commit()
        db_session.refresh(state)
        
        logger.info(f"Successfully added manual leg {leg_key} to strategy {instance_id}")

        return parsed_state

    except (StrategyStateDbNotFoundError, StrategyStateNotFoundError, StrategyStateDuplicateLegError):
        db_session.rollback()
        raise
    except Exception as exc:
        logger.error(f"Error adding manual leg for {instance_id}: {exc}")
        db_session.rollback()
        raise StrategyStateDbError(f"Database error: {str(exc)}") from exc
    finally:
        db_session.remove()


# ============================================================================
# Database Initialization
# ============================================================================

def init_db() -> None:
    """Initialize required tables for the Strategy State DB.

    Ensures both `strategy_execution_states` and `strategy_overrides` exist.
    Safe to call multiple times.
    """
    try:
        # Ensure the parent directory exists before attempting to create/connect.
        # If the DB file doesn't exist, SQLite will create it when the first connection
        # is made during table creation.
        db_dir = os.path.dirname(DB_PATH)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        StrategyExecutionState.__table__.create(engine, checkfirst=True)
        StrategyOverride.__table__.create(engine, checkfirst=True)
        logger.info("Strategy State DB: tables initialized")

    except Exception as e:
        logger.error(f"Strategy State DB: Error initializing tables: {e}")
        raise StrategyStateDbError(f"Failed to initialize tables: {str(e)}") from e


# ============================================================================
# Strategy Override Functions
# ============================================================================


def create_strategy_override(instance_id: str, leg_key: str, override_type: str, new_value: float) -> dict:
    """Create a new strategy override record.

    Args:
        instance_id: The strategy instance ID
        leg_key: The leg identifier (e.g., "CE_SPREAD_CE_SELL")
        override_type: Either 'sl_price' or 'target_price' (validated by API layer)
        new_value: The new price value (validated by API layer)

    Returns:
        dict: The created override record

    Raises:
        StrategyStateDbNotFoundError: If the DB file is missing
        StrategyStateDbError: For other unexpected DB errors
    """
    try:
        if not os.path.exists(DB_PATH):
            raise StrategyStateDbNotFoundError('Strategy state database not found')

        # Create the override record
        override = StrategyOverride(
            instance_id=instance_id,
            leg_key=leg_key,
            override_type=override_type,
            new_value=float(new_value),
            applied=False,
            created_at=datetime.utcnow(),
            applied_at=None
        )
        
        db_session.add(override)
        db_session.commit()
        
        result = {
            'id': override.id,
            'instance_id': override.instance_id,
            'leg_key': override.leg_key,
            'override_type': override.override_type,
            'new_value': override.new_value,
            'applied': override.applied,
            'created_at': override.created_at.isoformat() if override.created_at else None
        }
        
        logger.info(f"Created strategy override: {instance_id}/{leg_key}/{override_type} = {new_value}")
        return result
    
    except StrategyStateDbNotFoundError:
        db_session.rollback()
        raise

    except Exception as e:
        logger.error(f"Error creating strategy override: {e}")
        db_session.rollback()
        raise StrategyStateDbError(f"Database error: {str(e)}") from e

    finally:
        db_session.remove()


def get_pending_overrides(instance_id: str) -> list:
    """
    Get all pending (unapplied) overrides for a strategy instance.
    Used by strategies to poll for UI modifications.
    
    Args:
        instance_id: The strategy instance ID
        
    Returns:
        list: List of pending override dictionaries
    """
    try:
        if not os.path.exists(DB_PATH):
            return []
        
        overrides = StrategyOverride.query.filter_by(
            instance_id=instance_id,
            applied=False
        ).order_by(StrategyOverride.created_at.asc()).all()
        
        result = []
        for override in overrides:
            result.append({
                'id': override.id,
                'instance_id': override.instance_id,
                'leg_key': override.leg_key,
                'override_type': override.override_type,
                'new_value': override.new_value,
                'applied': override.applied,
                'created_at': override.created_at.isoformat() if override.created_at else None
            })
        
        return result
    
    except Exception as e:
        logger.error(f"Error fetching pending overrides for {instance_id}: {e}")
        return []
    finally:
        db_session.remove()


def mark_override_applied(override_id: int) -> bool:
    """
    Mark an override as applied.
    Called by strategies after successfully applying an override.
    
    Args:
        override_id: The override record ID
        
    Returns:
        bool: True if updated, False otherwise
    """
    try:
        if not os.path.exists(DB_PATH):
            return False
        
        override = StrategyOverride.query.filter_by(id=override_id).first()
        
        if not override:
            logger.warning(f"Override not found: {override_id}")
            return False
        
        override.applied = True
        override.applied_at = datetime.utcnow()
        db_session.commit()
        
        logger.info(f"Marked override as applied: {override_id}")
        return True
    
    except Exception as e:
        logger.error(f"Error marking override as applied {override_id}: {e}")
        db_session.rollback()
        return False
    finally:
        db_session.remove()


def manual_exit_strategy_leg(
    *,
    instance_id: str,
    leg_key: str,
    exit_price: float,
    exit_status: str,
    exit_time: datetime
) -> dict:
    """
    Manually exit a strategy leg and update status to SL_HIT or TARGET_HIT.
    Moves the leg to trade history and updates P&L.
    
    Args:
        instance_id: Strategy instance identifier.
        leg_key: Unique leg key for the strategy.
        exit_price: Manual exit price provided by user.
        exit_status: Either 'SL_HIT' or 'TARGET_HIT'.
        exit_time: Exit timestamp.
    
    Returns:
        dict: Updated strategy state data.
    
    Raises:
        StrategyStateDbNotFoundError: If DB file is missing.
        StrategyStateNotFoundError: If strategy or leg not found.
        StrategyStateDbError: For other DB errors.
    """
    try:
        if not os.path.exists(DB_PATH):
            raise StrategyStateDbNotFoundError('Strategy state database not found')
        
        state = StrategyExecutionState.query.filter_by(instance_id=instance_id).first()
        if not state:
            raise StrategyStateNotFoundError('Strategy state not found')
        
        if not state.state_data:
            raise StrategyStateDbError('Strategy state data is empty')
        
        try:
            parsed_state = json.loads(state.state_data)
        except json.JSONDecodeError as exc:
            raise StrategyStateDbError('Strategy state data is malformed') from exc
        
        legs = parsed_state.get('legs') or {}
        
        if leg_key not in legs:
            raise StrategyStateNotFoundError(f'Leg {leg_key} not found in strategy')
        
        leg = legs[leg_key]
        
        # Calculate P&L
        entry_price = leg.get('entry_price', 0)
        quantity = leg.get('quantity', 0)
        side = leg.get('side', 'BUY')
        
        if side == 'BUY':
            pnl = (exit_price - entry_price) * quantity
        else:  # SELL
            pnl = (entry_price - exit_price) * quantity
        
        # Update leg status and exit details
        leg['status'] = exit_status
        leg['exit_price'] = exit_price
        leg['exit_time'] = exit_time.isoformat() if exit_time else None
        leg['realized_pnl'] = pnl
        leg['unrealized_pnl'] = 0  # No longer unrealized
        leg['total_pnl'] = pnl
        
        # Add to trade history
        trade_history = parsed_state.get('trade_history') or []
        trade_history_entry = {
            'leg_key': leg_key,
            'symbol': leg.get('symbol'),
            'exchange': leg.get('exchange'),
            'product': leg.get('product'),
            'quantity': quantity,
            'side': side,
            'entry_price': entry_price,
            'entry_time': leg.get('entry_time'),
            'exit_price': exit_price,
            'exit_time': exit_time.isoformat() if exit_time else None,
            'exit_reason': exit_status,
            'pnl': pnl,
            'leg_pair_name': leg.get('leg_pair_name'),
            'is_main_leg': leg.get('is_main_leg'),
        }
        trade_history.append(trade_history_entry)
        parsed_state['trade_history'] = trade_history
        
        # Save updated state
        state.state_data = json.dumps(parsed_state)
        state.last_updated = datetime.utcnow()
        
        # Force SQLAlchemy to detect the change
        from sqlalchemy.orm import attributes
        attributes.flag_modified(state, 'state_data')
        
        db_session.flush()
        db_session.commit()
        db_session.refresh(state)
        
        logger.info(f"Successfully exited leg {leg_key} from strategy {instance_id} with status {exit_status}")
        
        return parsed_state
    
    except (StrategyStateDbNotFoundError, StrategyStateNotFoundError):
        db_session.rollback()
        raise
    except Exception as exc:
        logger.error(f"Error manually exiting leg {leg_key} for {instance_id}: {exc}")
        db_session.rollback()
        raise StrategyStateDbError(f"Database error: {str(exc)}") from exc
    finally:
        db_session.remove()
