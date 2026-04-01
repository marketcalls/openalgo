# database/samco_auth_db.py

import os
from datetime import datetime, timedelta

from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool

from utils.logging import get_logger

logger = get_logger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

# Conditionally create engine based on DB type
if DATABASE_URL and "sqlite" in DATABASE_URL:
    engine = create_engine(
        DATABASE_URL, poolclass=NullPool, connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(DATABASE_URL, pool_size=50, max_overflow=100, pool_timeout=10)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


class SamcoAuth(Base):
    __tablename__ = "samco_auth"
    id = Column(Integer, primary_key=True)
    user_id = Column(String(50), unique=True, nullable=False)
    secret_api_key = Column(Text, nullable=True)
    primary_ip = Column(String(45), nullable=True)
    secondary_ip = Column(String(45), nullable=True)
    ip_updated_at = Column(DateTime, nullable=True)


def init_db():
    """Initialize the samco_auth database table"""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Samco Auth DB", logger)


def get_samco_auth(user_id):
    """Get Samco auth record for a user"""
    try:
        return SamcoAuth.query.filter_by(user_id=user_id).first()
    except Exception as e:
        logger.error(f"Error getting samco auth for {user_id}: {e}")
        return None


def save_secret_key(user_id, secret_api_key):
    """Save or update the secret API key for a user"""
    try:
        record = SamcoAuth.query.filter_by(user_id=user_id).first()
        if record:
            record.secret_api_key = secret_api_key
        else:
            record = SamcoAuth(user_id=user_id, secret_api_key=secret_api_key)
            db_session.add(record)
        db_session.commit()
        return True
    except Exception as e:
        db_session.rollback()
        logger.error(f"Error saving secret key for {user_id}: {e}")
        return False


def get_ip_status(user_id):
    """Get IP registration status and whether editing is allowed this week"""
    record = get_samco_auth(user_id)
    if not record:
        return {
            "primary_ip": None,
            "secondary_ip": None,
            "editable": True,
            "ip_updated_at": None,
            "next_editable_date": None,
        }

    editable = True
    next_editable_date = None

    if record.ip_updated_at:
        now = datetime.utcnow()
        # Locked for 7 days from last update
        unlock_date = record.ip_updated_at + timedelta(days=7)
        if now < unlock_date:
            editable = False
            next_editable_date = unlock_date.strftime("%Y-%m-%d")

    return {
        "primary_ip": record.primary_ip,
        "secondary_ip": record.secondary_ip,
        "editable": editable,
        "ip_updated_at": record.ip_updated_at.isoformat() if record.ip_updated_at else None,
        "next_editable_date": next_editable_date,
    }


def save_ip_info(user_id, primary_ip, secondary_ip=None, ip_updated_at=None):
    """Save IP registration info"""
    try:
        record = SamcoAuth.query.filter_by(user_id=user_id).first()
        if record:
            record.primary_ip = primary_ip
            record.secondary_ip = secondary_ip
            record.ip_updated_at = ip_updated_at or datetime.utcnow()
        else:
            record = SamcoAuth(
                user_id=user_id,
                primary_ip=primary_ip,
                secondary_ip=secondary_ip,
                ip_updated_at=ip_updated_at or datetime.utcnow(),
            )
            db_session.add(record)
        db_session.commit()
        return True
    except Exception as e:
        db_session.rollback()
        logger.error(f"Error saving IP info for {user_id}: {e}")
        return False


def has_secret_key(user_id):
    """Check if a user has a secret API key stored"""
    record = get_samco_auth(user_id)
    return record is not None and record.secret_api_key is not None


def get_secret_key(user_id):
    """Get the stored secret API key for a user"""
    record = get_samco_auth(user_id)
    if record and record.secret_api_key:
        return record.secret_api_key
    return None


def has_registered_ip(user_id):
    """Check if a user has registered IPs"""
    record = get_samco_auth(user_id)
    return record is not None and record.primary_ip is not None
