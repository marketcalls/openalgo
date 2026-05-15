import json
import logging
import os
from datetime import datetime, date, timedelta

from sqlalchemy import Boolean, Column, Date, DateTime, Integer, String, Text, create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

# If a download stays in 'downloading' state longer than this, treat it as stuck/failed
DOWNLOAD_TIMEOUT_MINUTES = 5

# Get the database path from environment variable or use default
DB_PATH = os.getenv("DATABASE_URL", "sqlite:///db/openalgo.db")

# Ensure the directory exists
os.makedirs(os.path.dirname(DB_PATH.replace("sqlite:///", "")), exist_ok=True)

# Create the engine and session
# Conditionally create engine based on DB type
if DB_PATH and "sqlite" in DB_PATH:
    # SQLite: Use NullPool to prevent connection pool exhaustion
    engine = create_engine(
        DB_PATH,
        echo=False,
        poolclass=NullPool,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
else:
    # For other databases like PostgreSQL, use connection pooling
    engine = create_engine(DB_PATH, echo=False, pool_size=50, max_overflow=100, pool_timeout=10)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class MasterContractStatus(Base):
    __tablename__ = "master_contract_status"

    broker = Column(String, primary_key=True)
    status = Column(String, default="pending")  # pending, downloading, success, error
    message = Column(String)
    last_updated = Column(DateTime, default=datetime.now)
    total_symbols = Column(String, default="0")
    is_ready = Column(Boolean, default=False)
    progress = Column(Integer, default=0)         # Progress percentage (0-100)
    stages = Column(Text, nullable=True)          # JSON: {"download": 50, "process": 0, "import": 0}

    # Smart download tracking columns
    last_download_time = Column(DateTime, nullable=True)  # When download completed successfully
    download_date = Column(Date, nullable=True)           # Trading day of the download
    exchange_stats = Column(Text, nullable=True)          # JSON: {"NSE": 2500, "NFO": 85000, ...}
    download_duration_seconds = Column(Integer, nullable=True)  # How long download took


# Create table if it doesn't exist
Base.metadata.create_all(bind=engine)


def ensure_schema_up_to_date():
    """Ensure the master_contract_status table has all necessary columns"""
    try:
        with engine.connect() as conn:
            # Check for missing columns using PRAGMA table_info
            result = conn.execute(text("PRAGMA table_info(master_contract_status)"))
            columns = [row[1] for row in result]

            if "progress" not in columns:
                logger.info("Adding 'progress' column to master_contract_status table")
                conn.execute(text("ALTER TABLE master_contract_status ADD COLUMN progress INTEGER DEFAULT 0"))
                conn.commit()

            if "stages" not in columns:
                logger.info("Adding 'stages' column to master_contract_status table")
                conn.execute(text("ALTER TABLE master_contract_status ADD COLUMN stages TEXT"))
                conn.commit()
    except Exception as e:
        logger.error(f"Error ensuring schema is up to date: {e}")


# Run schema update on module import
ensure_schema_up_to_date()


def init_broker_status(broker):
    """Initialize status for a broker when they login"""
    session = SessionLocal()
    try:
        # Check if status already exists
        existing = session.query(MasterContractStatus).filter_by(broker=broker).first()

        if existing:
            # Update existing status
            existing.status = "pending"
            existing.message = "Master contract download pending"
            existing.last_updated = datetime.now()
            existing.is_ready = False
        else:
            # Create new status
            status = MasterContractStatus(
                broker=broker,
                status="pending",
                message="Master contract download pending",
                last_updated=datetime.now(),
                is_ready=False,
            )
            session.add(status)

        session.commit()
        logger.info(f"Initialized master contract status for {broker}")

    except Exception as e:
        logger.exception(f"Error initializing status for {broker}: {str(e)}")
        session.rollback()
    finally:
        session.close()


def update_status(broker, status, message, total_symbols=None, progress=None, stages=None):
    """Update the download status for a broker"""
    session = SessionLocal()
    try:
        broker_status = session.query(MasterContractStatus).filter_by(broker=broker).first()

        if broker_status:
            broker_status.status = status
            broker_status.message = message
            broker_status.last_updated = datetime.now()
            broker_status.is_ready = status == "success"
            
            if progress is not None:
                broker_status.progress = progress
                
            if stages is not None:
                broker_status.stages = json.dumps(stages)

            if total_symbols is not None:
                broker_status.total_symbols = str(total_symbols)
            
            # If status is success, set progress to 100
            if status == "success":
                broker_status.progress = 100
            elif status == "pending":
                broker_status.progress = 0
        else:
            # Create new status if it doesn't exist
            broker_status = MasterContractStatus(
                broker=broker,
                status=status,
                message=message,
                last_updated=datetime.now(),
                is_ready=(status == "success"),
                total_symbols=str(total_symbols) if total_symbols else "0",
            )
            session.add(broker_status)

        session.commit()
        logger.info(f"Updated master contract status for {broker}: {status} ({broker_status.progress}%)")

    except Exception as e:
        logger.exception(f"Error updating status for {broker}: {str(e)}")
        session.rollback()
    finally:
        session.close()


def get_status(broker):
    """Get the current status for a broker"""
    session = SessionLocal()
    try:
        status = session.query(MasterContractStatus).filter_by(broker=broker).first()

        if status:
            # Detect stuck downloads: if status is 'downloading' but last_updated
            # is older than the timeout, auto-transition to 'error'
            if (
                status.status == "downloading"
                and status.last_updated
                and datetime.now() - status.last_updated > timedelta(minutes=DOWNLOAD_TIMEOUT_MINUTES)
            ):
                logger.warning(
                    f"Download for {broker} stuck for >{DOWNLOAD_TIMEOUT_MINUTES}min, marking as error"
                )
                status.status = "error"
                status.message = (
                    f"Download timed out (stuck for >{DOWNLOAD_TIMEOUT_MINUTES} minutes). "
                    "Click Force Download to retry."
                )
                status.last_updated = datetime.now()
                status.is_ready = False
                session.commit()

            # Parse exchange_stats JSON if present
            exchange_stats = None
            if status.exchange_stats:
                try:
                    exchange_stats = json.loads(status.exchange_stats)
                except json.JSONDecodeError:
                    exchange_stats = None

            return {
                "broker": status.broker,
                "status": status.status,
                "message": status.message,
                "last_updated": status.last_updated.isoformat() if status.last_updated else None,
                "total_symbols": status.total_symbols,
                "is_ready": status.is_ready,
                # Smart download fields
                "last_download_time": status.last_download_time.isoformat() if status.last_download_time else None,
                "download_date": status.download_date.isoformat() if status.download_date else None,
                "exchange_stats": exchange_stats,
                "download_duration_seconds": status.download_duration_seconds,
                "progress": status.progress or 0,
                "stages": json.loads(status.stages) if status.stages else {},
            }
        else:
            return {
                "broker": broker,
                "status": "unknown",
                "message": "No status available",
                "last_updated": None,
                "total_symbols": "0",
                "is_ready": False,
                "last_download_time": None,
                "download_date": None,
                "exchange_stats": None,
                "download_duration_seconds": None,
            }
    except Exception as e:
        logger.exception(f"Error getting status for {broker}: {str(e)}")
        return {
            "broker": broker,
            "status": "error",
            "message": f"Error retrieving status: {str(e)}",
            "last_updated": None,
            "total_symbols": "0",
            "is_ready": False,
            "last_download_time": None,
            "download_date": None,
            "exchange_stats": None,
            "download_duration_seconds": None,
        }
    finally:
        session.close()


def check_if_ready(broker):
    """Check if master contracts are ready for a broker"""
    session = SessionLocal()
    try:
        status = session.query(MasterContractStatus).filter_by(broker=broker).first()
        return status.is_ready if status else False
    except Exception as e:
        logger.exception(f"Error checking if ready for {broker}: {str(e)}")
        return False
    finally:
        session.close()


def get_last_download_time(broker):
    """Get the last successful download time for a broker"""
    session = SessionLocal()
    try:
        status = session.query(MasterContractStatus).filter_by(broker=broker).first()
        return status.last_download_time if status else None
    except Exception as e:
        logger.exception(f"Error getting last download time for {broker}: {str(e)}")
        return None
    finally:
        session.close()


def get_last_downloaded_broker():
    """Get the broker that most recently downloaded master contracts successfully.

    Since the symtoken table is shared (no broker column), only the most recent
    broker's data is valid. This helps detect broker switches that require re-download.
    """
    session = SessionLocal()
    try:
        status = (
            session.query(MasterContractStatus)
            .filter(MasterContractStatus.last_download_time.isnot(None))
            .order_by(MasterContractStatus.last_download_time.desc())
            .first()
        )
        return status.broker if status else None
    except Exception as e:
        logger.exception(f"Error getting last downloaded broker: {str(e)}")
        return None
    finally:
        session.close()


def update_download_stats(broker, duration_seconds, exchange_stats=None):
    """Update download statistics after successful download"""
    session = SessionLocal()
    try:
        status = session.query(MasterContractStatus).filter_by(broker=broker).first()
        if status:
            status.last_download_time = datetime.now()
            status.download_date = date.today()
            status.download_duration_seconds = duration_seconds
            if exchange_stats:
                status.exchange_stats = json.dumps(exchange_stats)
            session.commit()
            logger.info(f"Updated download stats for {broker}: {duration_seconds}s")
    except Exception as e:
        logger.exception(f"Error updating download stats for {broker}: {str(e)}")
        session.rollback()
    finally:
        session.close()


def mark_status_ready_without_download(broker):
    """Mark master contract as ready without downloading (using existing data)"""
    session = SessionLocal()
    try:
        status = session.query(MasterContractStatus).filter_by(broker=broker).first()
        if status and status.last_download_time:
            status.is_ready = True
            status.status = "success"
            status.message = "Using cached master contract"
            status.last_updated = datetime.now()
            session.commit()
            logger.info(f"Marked existing master contract as ready for {broker}")
            return True
        return False
    except Exception as e:
        logger.exception(f"Error marking status ready for {broker}: {str(e)}")
        session.rollback()
        return False
    finally:
        session.close()


def reset_all_stuck_statuses():
    """Reset all brokers that are stuck in 'downloading' state to 'error' or 'pending'.
    This should be called during application startup to clear any persistent states
    from a previous session that crashed or was stopped.
    """
    session = SessionLocal()
    try:
        stuck_brokers = session.query(MasterContractStatus).filter_by(status="downloading").all()
        for status in stuck_brokers:
            logger.info(f"Resetting stuck 'downloading' status for {status.broker} on startup")
            status.status = "error"
            status.message = "Interrupted by server restart. Click Force Download to retry."
            status.last_updated = datetime.now()
            status.is_ready = False
        session.commit()
    except Exception as e:
        logger.exception(f"Error resetting stuck statuses: {str(e)}")
        session.rollback()
    finally:
        session.close()


def get_exchange_stats_from_db():
    """Get exchange-wise symbol counts from symtoken table"""
    try:
        # Query symtoken table directly using raw SQL
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT
                    exchange,
                    COUNT(*) as total
                FROM symtoken
                GROUP BY exchange
                ORDER BY total DESC
            """)).fetchall()

            stats = {}
            for row in result:
                stats[row[0]] = row[1]
            return stats
    except Exception as e:
        logger.exception(f"Error getting exchange stats: {str(e)}")
        return {}
