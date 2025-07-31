# database/settings_db.py

from sqlalchemy import create_engine, Column, Integer, String, Boolean, MetaData, Text
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
import os
from utils.logging import get_logger
from cryptography.fernet import Fernet
import base64

logger = get_logger(__name__)

DATABASE_URL = os.getenv('DATABASE_URL')

engine = create_engine(
    DATABASE_URL,
    pool_size=50,
    max_overflow=100,
    pool_timeout=10
)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

class Settings(Base):
    __tablename__ = 'settings'
    id = Column(Integer, primary_key=True)
    analyze_mode = Column(Boolean, default=False)  # Default to Live Mode
    
    # SMTP Configuration
    smtp_server = Column(String(255), nullable=True)
    smtp_port = Column(Integer, nullable=True)
    smtp_username = Column(String(255), nullable=True)
    smtp_password_encrypted = Column(Text, nullable=True)  # Encrypted SMTP password
    smtp_use_tls = Column(Boolean, default=True)
    smtp_from_email = Column(String(255), nullable=True)
    smtp_helo_hostname = Column(String(255), nullable=True)  # HELO/EHLO hostname

def init_db():
    """Initialize the settings database"""
    logger.info("Initializing Settings DB")
    
    # Create tables if they don't exist
    Base.metadata.create_all(bind=engine)
    
    # Create default settings only if no settings exist
    if not Settings.query.first():
        logger.info("Creating default settings (Live Mode)")
        default_settings = Settings(analyze_mode=False)
        db_session.add(default_settings)
        db_session.commit()

def get_analyze_mode():
    """Get current analyze mode setting"""
    settings = Settings.query.first()
    if not settings:
        settings = Settings(analyze_mode=False)  # Default to Live Mode
        db_session.add(settings)
        db_session.commit()
    return settings.analyze_mode

def set_analyze_mode(mode: bool):
    """Set analyze mode setting"""
    settings = Settings.query.first()
    if not settings:
        settings = Settings(analyze_mode=mode)
        db_session.add(settings)
    else:
        settings.analyze_mode = mode
    db_session.commit()

def _get_encryption_key():
    """Get or create encryption key for SMTP password"""
    # Use API_KEY_PEPPER as the base for encryption key
    pepper = os.getenv('API_KEY_PEPPER', 'default-pepper-key')
    # Create a stable key from the pepper
    key = base64.urlsafe_b64encode(pepper.ljust(32)[:32].encode())
    return key

def _encrypt_password(password: str) -> str:
    """Encrypt SMTP password"""
    if not password:
        return None
    key = _get_encryption_key()
    f = Fernet(key)
    encrypted = f.encrypt(password.encode())
    return encrypted.decode()

def _decrypt_password(encrypted_password: str) -> str:
    """Decrypt SMTP password"""
    if not encrypted_password:
        return None
    key = _get_encryption_key()
    f = Fernet(key)
    decrypted = f.decrypt(encrypted_password.encode())
    return decrypted.decode()

def get_smtp_settings():
    """Get SMTP configuration"""
    settings = Settings.query.first()
    if not settings:
        return None
    
    return {
        'smtp_server': settings.smtp_server,
        'smtp_port': settings.smtp_port,
        'smtp_username': settings.smtp_username,
        'smtp_password': _decrypt_password(settings.smtp_password_encrypted) if settings.smtp_password_encrypted else None,
        'smtp_use_tls': settings.smtp_use_tls,
        'smtp_from_email': settings.smtp_from_email,
        'smtp_helo_hostname': settings.smtp_helo_hostname
    }

def set_smtp_settings(smtp_server=None, smtp_port=None, smtp_username=None, 
                     smtp_password=None, smtp_use_tls=True, smtp_from_email=None, smtp_helo_hostname=None):
    """Set SMTP configuration"""
    settings = Settings.query.first()
    if not settings:
        settings = Settings(analyze_mode=False)
        db_session.add(settings)
    
    if smtp_server is not None:
        settings.smtp_server = smtp_server
    if smtp_port is not None:
        settings.smtp_port = smtp_port
    if smtp_username is not None:
        settings.smtp_username = smtp_username
    if smtp_password is not None:
        settings.smtp_password_encrypted = _encrypt_password(smtp_password)
    if smtp_use_tls is not None:
        settings.smtp_use_tls = smtp_use_tls
    if smtp_from_email is not None:
        settings.smtp_from_email = smtp_from_email
    if smtp_helo_hostname is not None:
        settings.smtp_helo_hostname = smtp_helo_hostname
    
    db_session.commit()
    logger.info("SMTP settings updated successfully")
