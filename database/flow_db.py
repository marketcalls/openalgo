# database/flow_db.py

import logging
import os
import secrets
from datetime import UTC, datetime, timedelta

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


def get_workflow_api_key(workflow):
    """Decrypt and return a workflow's stored OpenAlgo API key.

    The api_key column transitioned from plaintext to Fernet-encrypted
    (auth_db Fernet, PBKDF2 over API_KEY_PEPPER). Pre-migration plaintext
    rows are returned as-is via safe_decrypt_token's fallback.
    """
    if not workflow or not workflow.api_key:
        return None
    from database.auth_db import safe_decrypt_token
    return safe_decrypt_token(workflow.api_key)


def _encrypt_api_key(api_key):
    """Encrypt an API key for storage in flow_workflows.api_key."""
    if not api_key:
        return None
    from database.auth_db import encrypt_token
    return encrypt_token(api_key)


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
    except Exception:
        # Do not fail startup, but do not hide it either. Without api_key every
        # workflow activation fails to persist, and at debug level that was
        # invisible while `migrate_flow.py --status` reported all changes
        # applied. The registered migration adds the column properly; this hook
        # only covers an installation that has not run it yet.
        logger.exception(
            "Could not add the flow_workflows.api_key column. Run "
            "'cd upgrade && uv run migrate_all.py' -- until then, activating a "
            "workflow will not persist its API key."
        )


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
    """Get workflow by webhook token (token-to-id lookup cached for 5 minutes).

    Only the id is cached, never the ORM instance. Caching the instance handed
    the same object to every later request: the commit inside a workflow run
    expired it and the scoped session was removed at teardown, so the next
    webhook within the TTL raised DetachedInstanceError on the first attribute
    read -- outside any try -- and dropped every alert for five minutes. A
    cached id is also immune to a stale attribute snapshot, which is what let a
    rotated-out webhook secret keep authenticating.
    """
    cached_id = _workflow_webhook_cache.get(webhook_token)
    if cached_id is not None:
        workflow = get_workflow(cached_id)
        if workflow is not None and workflow.webhook_token == webhook_token:
            return workflow
        # The token moved or the workflow is gone; fall through to a real lookup.
        _workflow_webhook_cache.pop(webhook_token, None)

    try:
        workflow = FlowWorkflow.query.filter_by(webhook_token=webhook_token).first()
        if workflow:
            _workflow_webhook_cache[webhook_token] = workflow.id
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
                # api_key is encrypted at rest with the auth_db Fernet.
                if field == "api_key":
                    setattr(workflow, field, _encrypt_api_key(kwargs[field]))
                else:
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

        # Rotation must revoke the old secret immediately. Every other mutator
        # evicts this cache; this one did not, so for the whole 5-minute TTL the
        # leaked secret kept authenticating and the new one was rejected 401 --
        # the revocation did nothing at exactly the moment it mattered.
        _workflow_cache.clear()
        _workflow_webhook_cache.pop(workflow.webhook_token, None)

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
    """Create a new workflow execution.

    `started_at` is stamped here. It used to be set only by
    update_execution_status("running"), and nothing ever passed that status --
    the executor creates the row already running -- so every execution ever
    recorded had a NULL start time. The history query ordered on that column,
    and with every value NULL the sort collapsed to insertion order ascending,
    so the Executions panel listed the *oldest* runs and the dashboard's "last
    run" showed the first run the workflow ever had.
    """
    try:
        execution = FlowWorkflowExecution(
            workflow_id=workflow_id, status=status, logs=[], started_at=func.now()
        )
        db_session.add(execution)
        db_session.commit()

        logger.info(f"Created execution for workflow {workflow_id} (id={execution.id})")
        prune_workflow_executions(workflow_id)
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


# Defence in depth for the route's own clamp: a negative limit reaches SQLite as
# "no limit", which would load every execution row and its log blob into memory.
EXECUTIONS_QUERY_MAX = 200

# How much execution history to keep per workflow. Each row carries the full
# node trace as JSON, and a workflow on a one-minute schedule writes roughly 375
# rows a day, so without pruning the table grows without bound. Either limit can
# be disabled by setting it to 0.
EXECUTION_RETENTION_COUNT = int(os.getenv("FLOW_EXECUTION_RETENTION_COUNT", "500"))
EXECUTION_RETENTION_DAYS = int(os.getenv("FLOW_EXECUTION_RETENTION_DAYS", "30"))


def prune_workflow_executions(workflow_id, max_count=None, max_age_days=None):
    """Delete execution history for one workflow beyond the retention limits.

    Runs after a new execution is recorded, so the table is trimmed by the same
    activity that grows it. Both passes are indexed: age uses
    idx_flow_executions_started_at, count uses the primary key.

    The deletes synchronize the session rather than running detached: SQLite
    reuses a rowid once the highest one is removed, and a stale instance left in
    the identity map then collides with the next insert that takes that id.

    Returns the number of rows deleted.
    """
    max_count = EXECUTION_RETENTION_COUNT if max_count is None else max_count
    max_age_days = EXECUTION_RETENTION_DAYS if max_age_days is None else max_age_days

    deleted = 0
    try:
        if max_age_days and max_age_days > 0:
            cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
            deleted += (
                FlowWorkflowExecution.query.filter(
                    FlowWorkflowExecution.workflow_id == workflow_id,
                    FlowWorkflowExecution.started_at.isnot(None),
                    FlowWorkflowExecution.started_at < cutoff,
                ).delete(synchronize_session="fetch")
                or 0
            )

        if max_count and max_count > 0:
            # Keep the newest max_count by id. Ordering by id rather than
            # started_at matters for rows written before that column was
            # stamped: their timestamp is null and would sort unpredictably.
            keep = [
                row.id
                for row in FlowWorkflowExecution.query.with_entities(
                    FlowWorkflowExecution.id
                )
                .filter(FlowWorkflowExecution.workflow_id == workflow_id)
                .order_by(FlowWorkflowExecution.id.desc())
                .limit(max_count)
                .all()
            ]
            if len(keep) >= max_count:
                deleted += (
                    FlowWorkflowExecution.query.filter(
                        FlowWorkflowExecution.workflow_id == workflow_id,
                        FlowWorkflowExecution.id < min(keep),
                    ).delete(synchronize_session="fetch")
                    or 0
                )

        if deleted:
            db_session.commit()
            logger.info(
                f"Pruned {deleted} execution(s) for workflow {workflow_id} "
                f"(keep newest {max_count}, max age {max_age_days}d)"
            )
        return deleted
    except Exception:
        # Retention is housekeeping: a failure here must not fail the run that
        # triggered it.
        logger.exception(f"Could not prune execution history for workflow {workflow_id}")
        db_session.rollback()
        return 0


def get_workflow_executions(workflow_id, limit=50):
    """Get executions for a workflow"""
    try:
        limit = min(max(int(limit or 50), 1), EXECUTIONS_QUERY_MAX)
    except (TypeError, ValueError):
        limit = 50
    try:
        return (
            FlowWorkflowExecution.query.filter_by(workflow_id=workflow_id)
            # By id, not started_at. The id is monotonic and never null, while
            # rows written before started_at was stamped have none -- and the
            # two engines disagree on where nulls sort under DESC, so ordering
            # on the timestamp would list legacy rows first on one of them.
            .order_by(FlowWorkflowExecution.id.desc())
            .limit(limit)
            .all()
        )
    except Exception as e:
        logger.exception(f"Error getting executions for workflow {workflow_id}: {str(e)}")
        return []


def update_execution_status(execution_id, status, error=None, logs=None):
    """Update execution status, and persist the node trace when one is supplied.

    ``logs`` is written once at the end of the run rather than appended per
    node, so a 48-node workflow costs one write instead of ~50. Without it the
    logs column stayed empty for every execution, which meant a scheduled run
    that quietly did nothing left no record of which condition stopped it - the
    trace existed only in the HTTP response of a manual "Run Now".

    Args:
        execution_id: Row to update.
        status: "running", "completed" or "failed".
        error: Failure message, stored only when truthy.
        logs: Accumulated node trace. ``None`` leaves any existing value alone;
            an empty list is still written, since "ran and logged nothing" is
            itself worth recording.
    """
    try:
        execution = get_execution(execution_id)
        if not execution:
            return None

        execution.status = status
        if error:
            execution.error = error
        if logs is not None:
            execution.logs = list(logs)

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
