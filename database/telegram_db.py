"""
Telegram Database Module using SQLAlchemy for secure database operations
"""

import os
import json
import base64
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Boolean, ForeignKey, Index, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker, relationship
from sqlalchemy.sql import func
from utils.logging import get_logger

logger = get_logger(__name__)

# Database configuration
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///db/telegram.db')
if DATABASE_URL.startswith('sqlite:///'):
    # Ensure the directory exists for SQLite
    db_path = DATABASE_URL.replace('sqlite:///', '')
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

# Encryption setup for API keys
TELEGRAM_KEY_SALT = os.getenv('TELEGRAM_KEY_SALT', 'telegram-openalgo-salt').encode()

def get_encryption_key():
    """Generate a Fernet key for encrypting API keys"""
    pepper = os.getenv('API_KEY_PEPPER', 'default-pepper-change-in-production')
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=TELEGRAM_KEY_SALT,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(pepper.encode()))
    return Fernet(key)

# Initialize Fernet cipher for API key encryption
fernet = get_encryption_key()

# Create engine and session
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))

Base = declarative_base()
Base.query = db_session.query_property()


class TelegramUser(Base):
    """Telegram users table"""
    __tablename__ = 'telegram_users'

    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False, index=True)
    openalgo_username = Column(String(255), nullable=False, index=True)
    encrypted_api_key = Column(Text)  # Encrypted API key for secure storage
    host_url = Column(String(500))  # OpenAlgo host URL
    first_name = Column(String(255))
    last_name = Column(String(255))
    telegram_username = Column(String(255))
    broker = Column(String(50), default='default')
    is_active = Column(Boolean, default=True)
    notifications_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    last_command_at = Column(DateTime)

    # Relationships
    command_logs = relationship("CommandLog", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("NotificationQueue", back_populates="user", cascade="all, delete-orphan")
    preferences = relationship("UserPreference", back_populates="user", uselist=False, cascade="all, delete-orphan")


class BotConfig(Base):
    """Bot configuration table"""
    __tablename__ = 'bot_config'

    id = Column(Integer, primary_key=True, default=1)
    token = Column(Text)
    is_active = Column(Boolean, default=False)
    bot_username = Column(String(255))
    max_message_length = Column(Integer, default=4096)
    rate_limit_per_minute = Column(Integer, default=30)
    broadcast_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class CommandLog(Base):
    """Command logs table for analytics"""
    __tablename__ = 'command_logs'

    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, ForeignKey('telegram_users.telegram_id'), nullable=False, index=True)
    command = Column(String(100), nullable=False)
    chat_id = Column(Integer)
    parameters = Column(Text)
    executed_at = Column(DateTime, default=func.now())

    # Relationship
    user = relationship("TelegramUser", back_populates="command_logs")


class NotificationQueue(Base):
    """Notification queue table"""
    __tablename__ = 'notification_queue'

    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, ForeignKey('telegram_users.telegram_id'), nullable=False)
    message = Column(Text, nullable=False)
    priority = Column(Integer, default=5)
    status = Column(String(20), default='pending', index=True)
    created_at = Column(DateTime, default=func.now())
    sent_at = Column(DateTime)
    error_message = Column(Text)

    # Relationship
    user = relationship("TelegramUser", back_populates="notifications")


class UserPreference(Base):
    """User preferences table"""
    __tablename__ = 'user_preferences'

    telegram_id = Column(Integer, ForeignKey('telegram_users.telegram_id'), primary_key=True)
    order_notifications = Column(Boolean, default=True)
    trade_notifications = Column(Boolean, default=True)
    pnl_notifications = Column(Boolean, default=True)
    daily_summary = Column(Boolean, default=True)
    summary_time = Column(String(10), default='18:00')
    language = Column(String(10), default='en')
    timezone = Column(String(50), default='Asia/Kolkata')
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationship
    user = relationship("TelegramUser", back_populates="preferences")


def init_db():
    """Initialize the database with required tables"""
    try:
        Base.metadata.create_all(bind=engine)

        # Create default bot config if not exists
        config = db_session.query(BotConfig).filter_by(id=1).first()
        if not config:
            default_config = BotConfig(id=1)
            db_session.add(default_config)
            db_session.commit()

        logger.info("Telegram database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {str(e)}")
        db_session.rollback()
    finally:
        db_session.remove()


# Telegram User Management Functions

def get_telegram_user(telegram_id: int) -> Optional[Dict]:
    """Get telegram user by telegram_id"""
    try:
        user = db_session.query(TelegramUser).filter_by(
            telegram_id=telegram_id,
            is_active=True
        ).first()

        if user:
            return {
                'id': user.id,
                'telegram_id': user.telegram_id,
                'openalgo_username': user.openalgo_username,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'telegram_username': user.telegram_username,
                'broker': user.broker,
                'is_active': user.is_active,
                'notifications_enabled': user.notifications_enabled,
                'created_at': user.created_at,
                'updated_at': user.updated_at,
                'last_command_at': user.last_command_at
            }
        return None
    except Exception as e:
        logger.error(f"Failed to get telegram user: {str(e)}")
        return None
    finally:
        db_session.remove()


def get_telegram_user_by_username(username: str) -> Optional[Dict]:
    """Get telegram user by OpenAlgo username"""
    try:
        user = db_session.query(TelegramUser).filter_by(
            openalgo_username=username,
            is_active=True
        ).first()

        if user:
            return {
                'id': user.id,
                'telegram_id': user.telegram_id,
                'openalgo_username': user.openalgo_username,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'telegram_username': user.telegram_username,
                'broker': user.broker,
                'is_active': user.is_active,
                'notifications_enabled': user.notifications_enabled,
                'created_at': user.created_at,
                'updated_at': user.updated_at,
                'last_command_at': user.last_command_at
            }
        return None
    except Exception as e:
        logger.error(f"Failed to get telegram user by username: {str(e)}")
        return None
    finally:
        db_session.remove()


def create_or_update_telegram_user(telegram_id: int, username: str, api_key: str = None,
                                  host_url: str = None, first_name: str = '',
                                  last_name: str = '', telegram_username: str = '',
                                  broker: str = 'default') -> bool:
    """Create or update telegram user with encrypted API key"""
    try:
        user = db_session.query(TelegramUser).filter_by(telegram_id=telegram_id).first()

        # Encrypt API key if provided
        encrypted_key = None
        if api_key:
            encrypted_key = fernet.encrypt(api_key.encode()).decode()

        if user:
            # Update existing user
            user.openalgo_username = username
            if encrypted_key:
                user.encrypted_api_key = encrypted_key
            if host_url:
                user.host_url = host_url
            user.first_name = first_name
            user.last_name = last_name
            user.telegram_username = telegram_username
            user.broker = broker
            user.is_active = True
            user.updated_at = func.now()
        else:
            # Create new user
            user = TelegramUser(
                telegram_id=telegram_id,
                openalgo_username=username,
                encrypted_api_key=encrypted_key,
                host_url=host_url,
                first_name=first_name,
                last_name=last_name,
                telegram_username=telegram_username,
                broker=broker
            )
            db_session.add(user)

            # Also create default preferences
            preferences = UserPreference(telegram_id=telegram_id)
            db_session.add(preferences)

        db_session.commit()
        logger.debug(f"Telegram user {telegram_id} linked successfully")
        return True

    except Exception as e:
        logger.error(f"Failed to create/update telegram user: {str(e)}")
        db_session.rollback()
        return False
    finally:
        db_session.remove()


def delete_telegram_user(telegram_id: int) -> bool:
    """Delete telegram user (soft delete by marking inactive)"""
    try:
        user = db_session.query(TelegramUser).filter_by(telegram_id=telegram_id).first()

        if user:
            user.is_active = False
            user.updated_at = func.now()
            db_session.commit()
            logger.debug(f"Telegram user {telegram_id} unlinked")
            return True

        return False

    except Exception as e:
        logger.error(f"Failed to delete telegram user: {str(e)}")
        db_session.rollback()
        return False
    finally:
        db_session.remove()


def get_all_telegram_users(filters: Optional[Dict] = None) -> List[Dict]:
    """Get all active telegram users with optional filters"""
    try:
        query = db_session.query(TelegramUser).filter_by(is_active=True)

        if filters:
            if 'broker' in filters:
                query = query.filter_by(broker=filters['broker'])
            if 'notifications_enabled' in filters:
                query = query.filter_by(notifications_enabled=filters['notifications_enabled'])

        users = query.all()

        return [{
            'id': user.id,
            'telegram_id': user.telegram_id,
            'openalgo_username': user.openalgo_username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'telegram_username': user.telegram_username,
            'broker': user.broker,
            'notifications_enabled': user.notifications_enabled,
            'created_at': user.created_at,
            'last_command_at': user.last_command_at
        } for user in users]

    except Exception as e:
        logger.error(f"Failed to get all telegram users: {str(e)}")
        return []
    finally:
        db_session.remove()


# Bot Configuration Functions

def get_bot_config() -> Dict:
    """Get bot configuration"""
    try:
        config = db_session.query(BotConfig).filter_by(id=1).first()

        if config:
            return {
                'bot_token': config.token,
                'token': config.token,  # Alias for backward compatibility
                'is_active': config.is_active,
                'bot_username': config.bot_username,
                'max_message_length': config.max_message_length,
                'rate_limit_per_minute': config.rate_limit_per_minute,
                'broadcast_enabled': config.broadcast_enabled,
                'created_at': config.created_at,
                'updated_at': config.updated_at
            }

        # Return default config if not exists
        return {
            'bot_token': None,
            'token': None,
            'is_active': False,
            'bot_username': None,
            'max_message_length': 4096,
            'rate_limit_per_minute': 30,
            'broadcast_enabled': True
        }

    except Exception as e:
        logger.error(f"Failed to get bot config: {str(e)}")
        return {}
    finally:
        db_session.remove()


def update_bot_config(config: Dict) -> bool:
    """Update bot configuration"""
    try:
        bot_config = db_session.query(BotConfig).filter_by(id=1).first()

        if not bot_config:
            bot_config = BotConfig(id=1)
            db_session.add(bot_config)

        # Update fields (map bot_token to token for database)
        for key, value in config.items():
            # Handle the bot_token -> token mapping
            if key == 'bot_token':
                setattr(bot_config, 'token', value)
            elif hasattr(bot_config, key) and key not in ['id', 'created_at']:
                setattr(bot_config, key, value)

        db_session.commit()
        logger.debug("Bot configuration updated")
        return True

    except Exception as e:
        logger.error(f"Failed to update bot config: {str(e)}")
        db_session.rollback()
        return False
    finally:
        db_session.remove()


# Command Logging Functions

def log_command(telegram_id: int, command: str, chat_id: int = None, parameters: Dict = None):
    """Log command execution for analytics"""
    try:
        params_json = json.dumps(parameters) if parameters else None

        # Create command log
        command_log = CommandLog(
            telegram_id=telegram_id,
            command=command,
            chat_id=chat_id,
            parameters=params_json
        )
        db_session.add(command_log)

        # Update last_command_at in telegram_users
        user = db_session.query(TelegramUser).filter_by(telegram_id=telegram_id).first()
        if user:
            user.last_command_at = func.now()

        db_session.commit()

    except Exception as e:
        logger.error(f"Failed to log command: {str(e)}")
        db_session.rollback()
    finally:
        db_session.remove()


def get_command_stats(days: int = 7) -> Dict:
    """Get command statistics for the last N days"""
    try:
        since_date = datetime.now() - timedelta(days=days)

        # Total commands
        total_commands = db_session.query(CommandLog).filter(
            CommandLog.executed_at >= since_date
        ).count()

        # Commands by type
        command_counts = db_session.query(
            CommandLog.command,
            func.count(CommandLog.id).label('count')
        ).filter(
            CommandLog.executed_at >= since_date
        ).group_by(CommandLog.command).order_by(func.count(CommandLog.id).desc()).all()

        commands_by_type = {cmd: count for cmd, count in command_counts}

        # Active users
        active_users = db_session.query(
            func.count(func.distinct(CommandLog.telegram_id))
        ).filter(
            CommandLog.executed_at >= since_date
        ).scalar()

        # Most active users
        top_users = db_session.query(
            TelegramUser.telegram_username,
            func.count(CommandLog.id).label('command_count')
        ).join(
            CommandLog, CommandLog.telegram_id == TelegramUser.telegram_id
        ).filter(
            CommandLog.executed_at >= since_date
        ).group_by(
            TelegramUser.telegram_username
        ).order_by(
            func.count(CommandLog.id).desc()
        ).limit(10).all()

        return {
            'total_commands': total_commands,
            'commands_by_type': commands_by_type,
            'active_users': active_users or 0,
            'top_users': [(username, count) for username, count in top_users],
            'period_days': days
        }

    except Exception as e:
        logger.error(f"Failed to get command stats: {str(e)}")
        return {
            'total_commands': 0,
            'commands_by_type': {},
            'active_users': 0,
            'top_users': [],
            'period_days': days
        }
    finally:
        db_session.remove()


# User Preferences Functions

def get_user_preferences(telegram_id: int) -> Dict:
    """Get user preferences"""
    try:
        pref = db_session.query(UserPreference).filter_by(telegram_id=telegram_id).first()

        if pref:
            return {
                'order_notifications': pref.order_notifications,
                'trade_notifications': pref.trade_notifications,
                'pnl_notifications': pref.pnl_notifications,
                'daily_summary': pref.daily_summary,
                'summary_time': pref.summary_time,
                'language': pref.language,
                'timezone': pref.timezone
            }

        # Return default preferences
        return {
            'order_notifications': True,
            'trade_notifications': True,
            'pnl_notifications': True,
            'daily_summary': True,
            'summary_time': '18:00',
            'language': 'en',
            'timezone': 'Asia/Kolkata'
        }

    except Exception as e:
        logger.error(f"Failed to get user preferences: {str(e)}")
        return {}
    finally:
        db_session.remove()


def update_user_preferences(telegram_id: int, preferences: Dict) -> bool:
    """Update user preferences"""
    try:
        pref = db_session.query(UserPreference).filter_by(telegram_id=telegram_id).first()

        if not pref:
            pref = UserPreference(telegram_id=telegram_id)
            db_session.add(pref)

        # Update fields
        for key, value in preferences.items():
            if hasattr(pref, key) and key not in ['telegram_id', 'created_at']:
                setattr(pref, key, value)

        db_session.commit()
        logger.debug(f"User preferences updated for telegram_id: {telegram_id}")
        return True

    except Exception as e:
        logger.error(f"Failed to update user preferences: {str(e)}")
        db_session.rollback()
        return False
    finally:
        db_session.remove()


# Notification Queue Functions

def add_notification(telegram_id: int, message: str, priority: int = 5) -> bool:
    """Add notification to queue"""
    try:
        notification = NotificationQueue(
            telegram_id=telegram_id,
            message=message,
            priority=priority
        )
        db_session.add(notification)
        db_session.commit()
        return True

    except Exception as e:
        logger.error(f"Failed to add notification: {str(e)}")
        db_session.rollback()
        return False
    finally:
        db_session.remove()


def get_pending_notifications(limit: int = 100) -> List[Dict]:
    """Get pending notifications from queue"""
    try:
        notifications = db_session.query(NotificationQueue).filter_by(
            status='pending'
        ).order_by(
            NotificationQueue.priority.desc(),
            NotificationQueue.created_at.asc()
        ).limit(limit).all()

        return [{
            'id': n.id,
            'telegram_id': n.telegram_id,
            'message': n.message,
            'priority': n.priority,
            'status': n.status,
            'created_at': n.created_at
        } for n in notifications]

    except Exception as e:
        logger.error(f"Failed to get pending notifications: {str(e)}")
        return []
    finally:
        db_session.remove()


def mark_notification_sent(notification_id: int, success: bool = True, error_message: str = None):
    """Mark notification as sent or failed"""
    try:
        notification = db_session.query(NotificationQueue).filter_by(id=notification_id).first()

        if notification:
            notification.status = 'sent' if success else 'failed'
            notification.sent_at = func.now()
            notification.error_message = error_message
            db_session.commit()

    except Exception as e:
        logger.error(f"Failed to update notification status: {str(e)}")
        db_session.rollback()
    finally:
        db_session.remove()


# Helper functions for API key management
def get_decrypted_api_key(telegram_id: int) -> Optional[str]:
    """Get and decrypt API key for a telegram user"""
    try:
        user = db_session.query(TelegramUser).filter_by(
            telegram_id=telegram_id,
            is_active=True
        ).first()

        if user and user.encrypted_api_key:
            decrypted_key = fernet.decrypt(user.encrypted_api_key.encode()).decode()
            return decrypted_key
        return None
    except Exception as e:
        logger.error(f"Failed to decrypt API key: {str(e)}")
        return None
    finally:
        db_session.remove()


def get_user_credentials(telegram_id: int) -> Optional[Dict]:
    """Get user's API credentials and host URL"""
    try:
        user = db_session.query(TelegramUser).filter_by(
            telegram_id=telegram_id,
            is_active=True
        ).first()

        if user:
            api_key = None
            if user.encrypted_api_key:
                try:
                    api_key = fernet.decrypt(user.encrypted_api_key.encode()).decode()
                except Exception as e:
                    logger.error(f"Failed to decrypt API key: {str(e)}")

            return {
                'username': user.openalgo_username,
                'api_key': api_key,
                'host_url': user.host_url or os.getenv('HOST_SERVER', 'http://127.0.0.1:5000'),
                'broker': user.broker
            }
        return None
    except Exception as e:
        logger.error(f"Failed to get user credentials: {str(e)}")
        return None
    finally:
        db_session.remove()


# Helper function to get auth token
def get_auth_token_by_username(username: str):
    """Helper function to get auth token - imports here to avoid circular imports"""
    from database.auth_db import get_auth_token
    return get_auth_token(username)


# Cleanup function
def cleanup_db():
    """Cleanup database connections"""
    db_session.remove()


# Initialize database on module load
init_db()