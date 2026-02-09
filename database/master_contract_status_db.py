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

    # Smart download tracking columns
    last_download_time = Column(DateTime, nullable=True)  # When download completed successfully
    download_date = Column(Date, nullable=True)           # Trading day of the download
    exchange_stats = Column(Text, nullable=True)          # JSON: {"NSE": 2500, "NFO": 85000, ...}
    download_duration_seconds = Column(Integer, nullable=True)  # How long download took


# Create table if it doesn't exist
Base.metadata.create_all(bind=engine)


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


def update_status(broker, status, message, total_symbols=None):
    """Update the download status for a broker"""
    session = SessionLocal()
    try:
        broker_status = session.query(MasterContractStatus).filter_by(broker=broker).first()

        if broker_status:
            broker_status.status = status
            broker_status.message = message
            broker_status.last_updated = datetime.now()
            broker_status.is_ready = status == "success"

            if total_symbols is not None:
                broker_status.total_symbols = str(total_symbols)
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
        logger.info(f"Updated master contract status for {broker}: {status}")

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
