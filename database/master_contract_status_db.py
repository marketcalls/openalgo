import os
from sqlalchemy import create_engine, Column, String, DateTime, Boolean, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Get the database path from environment variable or use default
DB_PATH = os.getenv('DATABASE_URL', 'sqlite:///db/openalgo.db')

# Ensure the directory exists
os.makedirs(os.path.dirname(DB_PATH.replace('sqlite:///', '')), exist_ok=True)

# Create the engine and session
engine = create_engine(
    DB_PATH, 
    echo=False,
    pool_size=50,
    max_overflow=100,
    pool_timeout=10
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class MasterContractStatus(Base):
    __tablename__ = 'master_contract_status'
    
    broker = Column(String, primary_key=True)
    status = Column(String, default='pending')  # pending, downloading, success, error
    message = Column(String)
    last_updated = Column(DateTime, default=datetime.now)
    total_symbols = Column(String, default='0')
    is_ready = Column(Boolean, default=False)

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
            existing.status = 'pending'
            existing.message = 'Master contract download pending'
            existing.last_updated = datetime.now()
            existing.is_ready = False
        else:
            # Create new status
            status = MasterContractStatus(
                broker=broker,
                status='pending',
                message='Master contract download pending',
                last_updated=datetime.now(),
                is_ready=False
            )
            session.add(status)
        
        session.commit()
        logger.info(f"Initialized master contract status for {broker}")
        
    except Exception as e:
        logger.error(f"Error initializing status for {broker}: {str(e)}")
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
            broker_status.is_ready = (status == 'success')
            
            if total_symbols is not None:
                broker_status.total_symbols = str(total_symbols)
        else:
            # Create new status if it doesn't exist
            broker_status = MasterContractStatus(
                broker=broker,
                status=status,
                message=message,
                last_updated=datetime.now(),
                is_ready=(status == 'success'),
                total_symbols=str(total_symbols) if total_symbols else '0'
            )
            session.add(broker_status)
        
        session.commit()
        logger.info(f"Updated master contract status for {broker}: {status}")
        
    except Exception as e:
        logger.error(f"Error updating status for {broker}: {str(e)}")
        session.rollback()
    finally:
        session.close()

def get_status(broker):
    """Get the current status for a broker"""
    session = SessionLocal()
    try:
        status = session.query(MasterContractStatus).filter_by(broker=broker).first()
        
        if status:
            return {
                'broker': status.broker,
                'status': status.status,
                'message': status.message,
                'last_updated': status.last_updated.isoformat() if status.last_updated else None,
                'total_symbols': status.total_symbols,
                'is_ready': status.is_ready
            }
        else:
            return {
                'broker': broker,
                'status': 'unknown',
                'message': 'No status available',
                'last_updated': None,
                'total_symbols': '0',
                'is_ready': False
            }
    except Exception as e:
        logger.error(f"Error getting status for {broker}: {str(e)}")
        return {
            'broker': broker,
            'status': 'error',
            'message': f'Error retrieving status: {str(e)}',
            'last_updated': None,
            'total_symbols': '0',
            'is_ready': False
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
        logger.error(f"Error checking if ready for {broker}: {str(e)}")
        return False
    finally:
        session.close()