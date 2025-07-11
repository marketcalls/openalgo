from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Use a separate database for logs
LOGS_DATABASE_URL = os.getenv('LOGS_DATABASE_URL', 'sqlite:///db/logs.db')

logs_engine = create_engine(
    LOGS_DATABASE_URL,
    pool_size=50,
    max_overflow=100,
    pool_timeout=10
)

logs_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=logs_engine))
LogBase = declarative_base()
LogBase.query = logs_session.query_property()

class TrafficLog(LogBase):
    """Model for traffic logging"""
    __tablename__ = 'traffic_logs'
    
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    client_ip = Column(String(50), nullable=False)
    method = Column(String(10), nullable=False)
    path = Column(String(500), nullable=False)
    status_code = Column(Integer, nullable=False)
    duration_ms = Column(Float, nullable=False)
    host = Column(String(500))
    error = Column(String(500))
    user_id = Column(Integer)  # No foreign key since it's a separate database

    @staticmethod
    def log_request(client_ip, method, path, status_code, duration_ms, host=None, error=None, user_id=None):
        """Log a request to the database"""
        try:
            log = TrafficLog(
                client_ip=client_ip,
                method=method,
                path=path,
                status_code=status_code,
                duration_ms=duration_ms,
                host=host,
                error=error,
                user_id=user_id
            )
            logs_session.add(log)
            logs_session.commit()
            return True
        except Exception as e:
            logger.error(f"Error logging traffic: {str(e)}")
            logs_session.rollback()
            return False

    @staticmethod
    def get_recent_logs(limit=100):
        """Get recent traffic logs ordered by timestamp"""
        try:
            return TrafficLog.query.order_by(TrafficLog.timestamp.desc()).limit(limit).all()
        except Exception as e:
            logger.error(f"Error getting recent logs: {str(e)}")
            return []

    @staticmethod
    def get_stats():
        """Get basic traffic statistics"""
        try:
            from sqlalchemy import func
            
            total_requests = TrafficLog.query.count()
            error_requests = TrafficLog.query.filter(TrafficLog.status_code >= 400).count()
            avg_duration = logs_session.query(func.avg(TrafficLog.duration_ms)).scalar() or 0
            
            return {
                'total_requests': total_requests,
                'error_requests': error_requests,
                'avg_duration': round(float(avg_duration), 2)
            }
        except Exception as e:
            logger.error(f"Error getting traffic stats: {str(e)}")
            return {
                'total_requests': 0,
                'error_requests': 0,
                'avg_duration': 0
            }

def init_logs_db():
    """Initialize the logs database"""
    # Extract directory from database URL and create if it doesn't exist
    db_path = LOGS_DATABASE_URL.replace('sqlite:///', '')
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    
    logger.info(f"Initializing Traffic Logs DB at: {LOGS_DATABASE_URL}")
    LogBase.metadata.create_all(bind=logs_engine)
