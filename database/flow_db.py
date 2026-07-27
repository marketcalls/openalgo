# database/flow_db.py

import logging
import os
import secrets

from cachetools import TTLCache
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, scoped_session, sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import func

logger = logging.getLogger(__name__)

# Flow workflow caches - 5 minute TTL for webhook lookups (high frequency)
_workflow_webhook_cache = TTLCache(maxsize=5000, ttl=300)  # 5 minutes TTL
_workflow_cache = TTLCache(maxsize=1000, ttl=600)  # 10 minutes TTL

DATABASE_URL = os.getenv("DATABASE_URL")

# Conditionally create engine based on DB type
if DATABASE_URL and "sqlite" in DATABASE_URL:
    # SQLite: Use NullPool to prevent connection pool exhaustion
    engine = create_engine(
        DATABASE_URL, poolclass=NullPool, connect_args={"check_same_thread": False}
    )
else:
    # For other databases like PostgreSQL, use connection pooling
    engine = create_engine(DATABASE_URL, pool_size=50, max_overflow=100, pool_timeout=10)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


def generate_webhook_token():
    """Generate a unique webhook token"""
    return secrets.token_urlsafe(32)


def generate_webhook_secret():
    """Generate a unique webhook secret for message validation"""
    return secrets.token_hex(32)


class FlowWorkflow(Base):
    """Model for flow workflows"""

    __tablename__ = "flow_workflows"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    nodes = Column(JSON, default=list)
    edges = Column(JSON, default=list)
    is_active = Column(Boolean, default=False)
    schedule_job_id = Column(String(255), nullable=True)
    webhook_token = Column(String(64), unique=True, nullable=True, default=generate_webhook_token)
    webhook_secret = Column(String(64), nullable=True, default=generate_webhook_secret)
    webhook_enabled = Column(Boolean, default=False)
    webhook_auth_type = Column(String(20), default="payload")  # "payload" or "url"
    api_key = Column(
        String(255), nullable=True
    )  # Stored when workflow is activated, used for webhook execution
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    executions = relationship(
        "FlowWorkflowExecution", back_populates="workflow", cascade="all, delete-orphan"
    )


class FlowWorkflowExecution(Base):
    """Model for flow workflow executions"""

    __tablename__ = "flow_workflow_executions"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("flow_workflows.id"), nullable=False)
    status = Column(String(50), default="pending")  # pending, running, completed, failed
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    logs = Column(JSON, default=list)
    error = Column(Text, nullable=True)

    # Relationships
    workflow = relationship("FlowWorkflow", back_populates="executions")


def init_db():
    """Initialize the database"""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Flow DB", logger)

    # Migrate: Add api_key column if it doesn't exist (for existing databases)
    _migrate_add_api_key_column()


def _migrate_add_api_key_column():
    """Add api_key column to flow_workflows table if it doesn't exist"""
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)

        # Check if table exists
        if "flow_workflows" not in inspector.get_table_names():
            return

        # Check if column exists
        columns = [col["name"] for col in inspector.get_columns("flow_workflows")]
        if "api_key" not in columns:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE flow_workflows ADD COLUMN api_key VARCHAR(255)"))
                conn.commit()
                logger.info("Migration: Added 'api_key' column to flow_workflows table")
    except Exception as e:
        # Log but don't fail - column might already exist or other DB issue
        logger.debug(f"Migration check for api_key column: {e}")


# --- Workflow CRUD Operations ---


def create_workflow(name, description=None, nodes=None, edges=None):
    """Create a new workflow"""
    try:
        workflow = FlowWorkflow(
            name=name, description=description, nodes=nodes or [], edges=edges or []
        )
        db_session.add(workflow)
        db_session.commit()

        # Clear workflow cache
        _workflow_cache.clear()

        logger.info(f"Created workflow: {name} (id={workflow.id})")
        return workflow
    except Exception as e:
        logger.exception(f"Error creating workflow: {str(e)}")
        db_session.rollback()
        return None


def get_workflow(workflow_id):
    """Get workflow by ID"""
    try:
        return FlowWorkflow.query.get(workflow_id)
    except Exception as e:
        logger.exception(f"Error getting workflow {workflow_id}: {str(e)}")
        return None


def get_workflow_by_webhook_token(webhook_token):
    """Get workflow by webhook token (cached for 5 minutes)"""
    # Check cache first
    if webhook_token in _workflow_webhook_cache:
        return _workflow_webhook_cache[webhook_token]

    try:
        workflow = FlowWorkflow.query.filter_by(webhook_token=webhook_token).first()
        # Cache the result (including None for not found)
        if workflow:
            _workflow_webhook_cache[webhook_token] = workflow
        return workflow
    except Exception as e:
        logger.exception(f"Error getting workflow by webhook token: {str(e)}")
        return None


def get_all_workflows():
    """Get all workflows"""
    try:
        return FlowWorkflow.query.order_by(FlowWorkflow.updated_at.desc()).all()
    except Exception as e:
        logger.exception(f"Error getting all workflows: {str(e)}")
        return []


def get_active_workflows():
    """Get all active workflows"""
    try:
        return FlowWorkflow.query.filter_by(is_active=True).all()
    except Exception as e:
        logger.exception(f"Error getting active workflows: {str(e)}")
        return []


def update_workflow(workflow_id, **kwargs):
    """Update workflow fields"""
    try:
        workflow = get_workflow(workflow_id)
        if not workflow:
            return None

        # Update allowed fields
        allowed_fields = [
            "name",
            "description",
            "nodes",
            "edges",
            "is_active",
            "schedule_job_id",
            "webhook_enabled",
            "webhook_auth_type",
            "api_key",
        ]
        for field in allowed_fields:
            if field in kwargs:
                setattr(workflow, field, kwargs[field])

        db_session.commit()

        # Clear caches
        _workflow_cache.clear()
        if workflow.webhook_token in _workflow_webhook_cache:
            del _workflow_webhook_cache[workflow.webhook_token]

        logger.info(f"Updated workflow {workflow_id}")
        return workflow
    except Exception as e:
        logger.exception(f"Error updating workflow {workflow_id}: {str(e)}")
        db_session.rollback()
        return None


def delete_workflow(workflow_id):
    """Delete workflow and its executions"""
    try:
        workflow = get_workflow(workflow_id)
        if not workflow:
            return False

        # Store for cache invalidation
        webhook_token = workflow.webhook_token

        db_session.delete(workflow)
        db_session.commit()

        # Clear caches
        _workflow_cache.clear()
        if webhook_token in _workflow_webhook_cache:
            del _workflow_webhook_cache[webhook_token]

        logger.info(f"Deleted workflow {workflow_id}")
        return True
    except Exception as e:
        logger.exception(f"Error deleting workflow {workflow_id}: {str(e)}")
        db_session.rollback()
        return False


def activate_workflow(workflow_id, api_key=None):
    """Activate a workflow and optionally store the API key for webhook execution"""
    kwargs = {"is_active": True}
    if api_key:
        kwargs["api_key"] = api_key
    return update_workflow(workflow_id, **kwargs)


def deactivate_workflow(workflow_id):
    """Deactivate a workflow"""
    return update_workflow(workflow_id, is_active=False)


def regenerate_webhook_token(workflow_id):
    """Regenerate webhook token for a workflow"""
    try:
        workflow = get_workflow(workflow_id)
        if not workflow:
            return None

        old_token = workflow.webhook_token
        workflow.webhook_token = generate_webhook_token()
        db_session.commit()

        # Clear old token from cache
        if old_token in _workflow_webhook_cache:
            del _workflow_webhook_cache[old_token]

        logger.info(f"Regenerated webhook token for workflow {workflow_id}")
        return workflow.webhook_token
    except Exception as e:
        logger.exception(f"Error regenerating webhook token for workflow {workflow_id}: {str(e)}")
        db_session.rollback()
        return None


def regenerate_webhook_secret(workflow_id):
    """Regenerate webhook secret for a workflow"""
    try:
        workflow = get_workflow(workflow_id)
        if not workflow:
            return None

        workflow.webhook_secret = generate_webhook_secret()
        db_session.commit()

        logger.info(f"Regenerated webhook secret for workflow {workflow_id}")
        return workflow.webhook_secret
    except Exception as e:
        logger.exception(f"Error regenerating webhook secret for workflow {workflow_id}: {str(e)}")
        db_session.rollback()
        return None


def enable_webhook(workflow_id):
    """Enable webhook for a workflow"""
    return update_workflow(workflow_id, webhook_enabled=True)


def disable_webhook(workflow_id):
    """Disable webhook for a workflow"""
    return update_workflow(workflow_id, webhook_enabled=False)


def set_webhook_auth_type(workflow_id, auth_type):
    """Set webhook auth type for a workflow"""
    if auth_type not in ["payload", "url"]:
        logger.error(f"Invalid webhook auth type: {auth_type}")
        return None
    return update_workflow(workflow_id, webhook_auth_type=auth_type)


def ensure_webhook_credentials(workflow_id):
    """Ensure webhook token and secret exist for a workflow"""
    try:
        workflow = get_workflow(workflow_id)
        if not workflow:
            return False

        needs_update = False
        if not workflow.webhook_token:
            workflow.webhook_token = generate_webhook_token()
            needs_update = True
        if not workflow.webhook_secret:
            workflow.webhook_secret = generate_webhook_secret()
            needs_update = True

        if needs_update:
            db_session.commit()
            # Clear cache to force refresh
            _workflow_cache.clear()
            logger.info(f"Generated webhook credentials for workflow {workflow_id}")

        return True
    except Exception as e:
        logger.exception(f"Error ensuring webhook credentials for workflow {workflow_id}: {str(e)}")
        db_session.rollback()
        return False


def set_schedule_job_id(workflow_id, job_id):
    """Set schedule job ID for a workflow"""
    try:
        workflow = get_workflow(workflow_id)
        if not workflow:
            return None

        workflow.schedule_job_id = job_id
        db_session.commit()

        logger.info(f"Set schedule job ID {job_id} for workflow {workflow_id}")
        return workflow
    except Exception as e:
        logger.exception(f"Error setting schedule job ID for workflow {workflow_id}: {str(e)}")
        db_session.rollback()
        return None


# --- Workflow Execution CRUD Operations ---


def create_execution(workflow_id, status="pending"):
    """Create a new workflow execution"""
    try:
        execution = FlowWorkflowExecution(workflow_id=workflow_id, status=status, logs=[])
        db_session.add(execution)
        db_session.commit()

        logger.info(f"Created execution for workflow {workflow_id} (id={execution.id})")
        return execution
    except Exception as e:
        logger.exception(f"Error creating execution for workflow {workflow_id}: {str(e)}")
        db_session.rollback()
        return None


def get_execution(execution_id):
    """Get execution by ID"""
    try:
        return FlowWorkflowExecution.query.get(execution_id)
    except Exception as e:
        logger.exception(f"Error getting execution {execution_id}: {str(e)}")
        return None


def get_workflow_executions(workflow_id, limit=50):
    """Get executions for a workflow"""
    try:
        return (
            FlowWorkflowExecution.query.filter_by(workflow_id=workflow_id)
            .order_by(FlowWorkflowExecution.started_at.desc())
            .limit(limit)
            .all()
        )
    except Exception as e:
        logger.exception(f"Error getting executions for workflow {workflow_id}: {str(e)}")
        return []


def update_execution_status(execution_id, status, error=None):
    """Update execution status"""
    try:
        execution = get_execution(execution_id)
        if not execution:
            return None

        execution.status = status
        if error:
            execution.error = error

        if status == "running" and not execution.started_at:
            execution.started_at = func.now()
        elif status in ["completed", "failed"]:
            execution.completed_at = func.now()

        db_session.commit()

        logger.info(f"Updated execution {execution_id} status to {status}")
        return execution
    except Exception as e:
        logger.exception(f"Error updating execution {execution_id}: {str(e)}")
        db_session.rollback()
        return None


def add_execution_log(execution_id, log_entry):
    """Add a log entry to execution"""
    try:
        execution = get_execution(execution_id)
        if not execution:
            return None

        # Get current logs and append
        logs = execution.logs or []
        logs.append(log_entry)
        execution.logs = logs

        db_session.commit()
        return execution
    except Exception as e:
        logger.exception(f"Error adding log to execution {execution_id}: {str(e)}")
        db_session.rollback()
        return None


def clear_workflow_cache():
    """Clear all workflow caches"""
    _workflow_webhook_cache.clear()
    _workflow_cache.clear()
    logger.info("Flow workflow cache cleared")
