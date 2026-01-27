# database/strategy_state_db.py

"""
Database access layer for strategy_state.db
This database stores Python strategy execution states and trade history.
"""

import os
import json
from datetime import datetime
from typing import Tuple
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Float, Boolean
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.pool import NullPool
from utils.logging import get_logger

logger = get_logger(__name__)

# Strategy state database path
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'db', 'strategy_state.db')
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


def delete_strategy_state(instance_id: str) -> Tuple[bool, str]:
    """
    Delete a strategy state by instance_id.
    
    Args:
        instance_id: The unique instance identifier
        
    Returns:
        Tuple[bool, str]: (success, message) where message indicates reason for failure
    """
    try:
        if not os.path.exists(DB_PATH):
            return False, "Strategy state database not found"
        
        state = StrategyExecutionState.query.filter_by(instance_id=instance_id).first()
        
        if not state:
            return False, "Strategy state not found"
        
        db_session.delete(state)
        db_session.commit()
        logger.info(f"Deleted strategy state: {instance_id}")
        return True, "Strategy state deleted successfully"
    
    except Exception as e:
        logger.error(f"Error deleting strategy state {instance_id}: {e}")
        db_session.rollback()
        return False, f"Database error: {str(e)}"
    finally:
        db_session.remove()


# ============================================================================
# Database Initialization
# ============================================================================

def init_db():
    """
    Initialize the strategy_overrides table if it doesn't exist.
    Called during application startup.
    """
    try:
        if os.path.exists(DB_PATH):
            # Create only the strategy_overrides table if it doesn't exist
            StrategyOverride.__table__.create(engine, checkfirst=True)
            logger.info("Strategy State DB: strategy_overrides table initialized")
    except Exception as e:
        logger.error(f"Strategy State DB: Error initializing strategy_overrides table: {e}")


# ============================================================================
# Strategy Override Functions
# ============================================================================


def create_strategy_override(instance_id: str, leg_key: str, override_type: str, new_value: float) -> dict:
    """
    Create a new strategy override record.
    
    Args:
        instance_id: The strategy instance ID
        leg_key: The leg identifier (e.g., "CE_SPREAD_CE_SELL")
        override_type: Either 'sl_price' or 'target_price' (validated by API layer)
        new_value: The new price value (validated by API layer)
        
    Returns:
        dict: The created override record or error dict
    """
    try:
        if not os.path.exists(DB_PATH):
            return {'error': 'Strategy state database not found'}
        
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
    
    except Exception as e:
        logger.error(f"Error creating strategy override: {e}")
        db_session.rollback()
        return {'error': str(e)}
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
