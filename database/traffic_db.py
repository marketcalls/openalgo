from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Boolean, Text
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
import os
import logging
from datetime import datetime, timedelta
import json
from database.settings_db import get_security_settings

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

class IPBan(LogBase):
    """Model for banned IPs"""
    __tablename__ = 'ip_bans'

    id = Column(Integer, primary_key=True)
    ip_address = Column(String(50), unique=True, nullable=False, index=True)
    ban_reason = Column(String(200))
    ban_count = Column(Integer, default=1)  # Track repeat offenses
    banned_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True))  # NULL means permanent ban
    is_permanent = Column(Boolean, default=False)
    created_by = Column(String(50), default='system')  # 'system' or 'manual'

    @staticmethod
    def is_ip_banned(ip_address):
        """Check if an IP is currently banned"""
        try:
            ban = IPBan.query.filter_by(ip_address=ip_address).first()
            if not ban:
                return False

            # Check permanent ban
            if ban.is_permanent:
                return True

            # Check temporary ban expiry
            if ban.expires_at:
                if datetime.utcnow() < ban.expires_at.replace(tzinfo=None):
                    return True
                else:
                    # Ban expired, remove it
                    logs_session.delete(ban)
                    logs_session.commit()
                    return False

            return False
        except Exception as e:
            logger.error(f"Error checking IP ban status: {e}")
            logs_session.rollback()
            return False

    @staticmethod
    def ban_ip(ip_address, reason, duration_hours=24, permanent=False, created_by='system'):
        """Ban an IP address"""
        try:
            # Never ban localhost
            if ip_address in ['127.0.0.1', '::1', 'localhost']:
                logger.warning(f"Attempted to ban localhost IP {ip_address} - ignoring")
                return False

            # Get repeat offender limit from settings
            security_settings = get_security_settings()
            repeat_limit = security_settings['repeat_offender_limit']

            existing_ban = IPBan.query.filter_by(ip_address=ip_address).first()

            if existing_ban:
                # Increment ban count for repeat offender
                existing_ban.ban_count += 1
                existing_ban.ban_reason = reason
                existing_ban.banned_at = datetime.utcnow()

                # After configured number of bans, make it permanent
                if existing_ban.ban_count >= repeat_limit:
                    existing_ban.is_permanent = True
                    existing_ban.expires_at = None
                    logger.warning(f"IP {ip_address} permanently banned after {existing_ban.ban_count} offenses")
                else:
                    existing_ban.is_permanent = permanent
                    existing_ban.expires_at = None if permanent else datetime.utcnow() + timedelta(hours=duration_hours)
            else:
                # Create new ban
                ban = IPBan(
                    ip_address=ip_address,
                    ban_reason=reason,
                    is_permanent=permanent,
                    expires_at=None if permanent else datetime.utcnow() + timedelta(hours=duration_hours),
                    created_by=created_by
                )
                logs_session.add(ban)

            logs_session.commit()
            logger.info(f"IP {ip_address} banned: {reason}")
            return True
        except Exception as e:
            logger.error(f"Error banning IP {ip_address}: {e}")
            logs_session.rollback()
            return False

    @staticmethod
    def unban_ip(ip_address):
        """Remove IP ban"""
        try:
            ban = IPBan.query.filter_by(ip_address=ip_address).first()
            if ban:
                logs_session.delete(ban)
                logs_session.commit()
                logger.info(f"IP {ip_address} unbanned")
                return True
            return False
        except Exception as e:
            logger.error(f"Error unbanning IP: {e}")
            logs_session.rollback()
            return False

    @staticmethod
    def get_all_bans():
        """Get all current IP bans"""
        try:
            # Remove expired bans first
            expired = IPBan.query.filter(
                IPBan.is_permanent == False,
                IPBan.expires_at < datetime.utcnow()
            ).all()

            for ban in expired:
                logs_session.delete(ban)

            logs_session.commit()

            # Return active bans
            return IPBan.query.all()
        except Exception as e:
            logger.error(f"Error getting IP bans: {e}")
            return []

class Error404Tracker(LogBase):
    """Track 404 errors per IP for bot detection"""
    __tablename__ = 'error_404_tracker'

    id = Column(Integer, primary_key=True)
    ip_address = Column(String(50), nullable=False, index=True)
    error_count = Column(Integer, default=1)
    first_error_at = Column(DateTime(timezone=True), server_default=func.now())
    last_error_at = Column(DateTime(timezone=True), server_default=func.now())
    paths_attempted = Column(Text)  # JSON array of attempted paths

    @staticmethod
    def track_404(ip_address, path):
        """Track a 404 error for an IP"""
        try:
            # Check if already banned
            if IPBan.is_ip_banned(ip_address):
                return False

            # Get security settings from database
            security_settings = get_security_settings()
            threshold_404 = security_settings['404_threshold']
            ban_duration_404 = security_settings['404_ban_duration']

            now = datetime.utcnow()
            tracker = Error404Tracker.query.filter_by(ip_address=ip_address).first()

            if tracker:
                # Check if tracking period expired (24 hours)
                if (now - tracker.first_error_at.replace(tzinfo=None)).days >= 1:
                    # Reset counter for new day
                    tracker.error_count = 1
                    tracker.first_error_at = now
                    tracker.paths_attempted = json.dumps([path])
                else:
                    # Increment counter
                    tracker.error_count += 1

                    # Add path to attempted paths
                    paths = json.loads(tracker.paths_attempted or '[]')
                    if path not in paths:
                        paths.append(path)
                        tracker.paths_attempted = json.dumps(paths[-50:])  # Keep last 50 paths

                tracker.last_error_at = now

                # Check if threshold reached (configurable, default 20 404s per day)
                if tracker.error_count >= threshold_404:
                    # Don't ban localhost IPs
                    if ip_address not in ['127.0.0.1', '::1', 'localhost']:
                        # Ban the IP
                        IPBan.ban_ip(
                            ip_address=ip_address,
                            reason=f"Exceeded 404 threshold: {tracker.error_count} errors in 24 hours",
                            duration_hours=ban_duration_404,
                            created_by='404_detector'
                        )

                        # Clean up tracker entry
                        logs_session.delete(tracker)
            else:
                # Create new tracker
                tracker = Error404Tracker(
                    ip_address=ip_address,
                    error_count=1,
                    paths_attempted=json.dumps([path])
                )
                logs_session.add(tracker)

            logs_session.commit()
            return True

        except Exception as e:
            logger.error(f"Error tracking 404: {e}")
            logs_session.rollback()
            return False

    @staticmethod
    def get_suspicious_ips(min_errors=5):
        """Get IPs with suspicious 404 activity"""
        try:
            # Clean up old entries (older than 24 hours)
            cutoff = datetime.utcnow() - timedelta(days=1)
            old_entries = Error404Tracker.query.filter(
                Error404Tracker.first_error_at < cutoff
            ).all()

            for entry in old_entries:
                logs_session.delete(entry)

            logs_session.commit()

            # Return suspicious IPs
            return Error404Tracker.query.filter(
                Error404Tracker.error_count >= min_errors
            ).order_by(Error404Tracker.error_count.desc()).all()
        except Exception as e:
            logger.error(f"Error getting suspicious IPs: {e}")
            return []

class InvalidAPIKeyTracker(LogBase):
    """Track invalid API key attempts per IP"""
    __tablename__ = 'invalid_api_key_tracker'

    id = Column(Integer, primary_key=True)
    ip_address = Column(String(50), nullable=False, index=True)
    attempt_count = Column(Integer, default=1)
    first_attempt_at = Column(DateTime(timezone=True), server_default=func.now())
    last_attempt_at = Column(DateTime(timezone=True), server_default=func.now())
    api_keys_tried = Column(Text)  # JSON array of API keys tried (hashed)

    @staticmethod
    def track_invalid_api_key(ip_address, api_key_hash=None):
        """Track an invalid API key attempt"""
        try:
            # Check if already banned
            if IPBan.is_ip_banned(ip_address):
                return False

            # Get security settings from database
            security_settings = get_security_settings()
            threshold_api = security_settings['api_threshold']
            ban_duration_api = security_settings['api_ban_duration']

            now = datetime.utcnow()
            tracker = InvalidAPIKeyTracker.query.filter_by(ip_address=ip_address).first()

            if tracker:
                # Check if tracking period expired (24 hours)
                if (now - tracker.first_attempt_at.replace(tzinfo=None)).days >= 1:
                    # Reset counter for new day
                    tracker.attempt_count = 1
                    tracker.first_attempt_at = now
                    tracker.api_keys_tried = json.dumps([api_key_hash] if api_key_hash else [])
                else:
                    # Increment counter
                    tracker.attempt_count += 1

                    # Add API key hash to tried list
                    if api_key_hash:
                        keys_tried = json.loads(tracker.api_keys_tried or '[]')
                        if api_key_hash not in keys_tried:
                            keys_tried.append(api_key_hash)
                            tracker.api_keys_tried = json.dumps(keys_tried[-20:])  # Keep last 20 keys

                tracker.last_attempt_at = now

                # Check if threshold reached (configurable, default 10 invalid API keys per day)
                if tracker.attempt_count >= threshold_api:
                    # Don't ban localhost IPs but keep tracking
                    if ip_address not in ['127.0.0.1', '::1', 'localhost']:
                        # Ban the IP
                        success = IPBan.ban_ip(
                            ip_address=ip_address,
                            reason=f"Exceeded invalid API key threshold: {tracker.attempt_count} attempts in 24 hours",
                            duration_hours=ban_duration_api,  # Configurable hours for API abuse
                            created_by='api_key_detector'
                        )

                        # Only delete tracker if ban was successful
                        if success:
                            logs_session.delete(tracker)
            else:
                # Create new tracker
                tracker = InvalidAPIKeyTracker(
                    ip_address=ip_address,
                    attempt_count=1,
                    api_keys_tried=json.dumps([api_key_hash] if api_key_hash else [])
                )
                logs_session.add(tracker)

            logs_session.commit()
            return True

        except Exception as e:
            logger.error(f"Error tracking invalid API key: {e}")
            logs_session.rollback()
            return False

    @staticmethod
    def get_suspicious_api_users(min_attempts=3):
        """Get IPs with suspicious API key activity"""
        try:
            # Clean up old entries (older than 24 hours)
            cutoff = datetime.utcnow() - timedelta(days=1)
            old_entries = InvalidAPIKeyTracker.query.filter(
                InvalidAPIKeyTracker.first_attempt_at < cutoff
            ).all()

            for entry in old_entries:
                logs_session.delete(entry)

            logs_session.commit()

            # Return suspicious IPs
            return InvalidAPIKeyTracker.query.filter(
                InvalidAPIKeyTracker.attempt_count >= min_attempts
            ).order_by(InvalidAPIKeyTracker.attempt_count.desc()).all()
        except Exception as e:
            logger.error(f"Error getting suspicious API users: {e}")
            return []

def init_logs_db():
    """Initialize the logs database"""
    # Extract directory from database URL and create if it doesn't exist
    db_path = LOGS_DATABASE_URL.replace('sqlite:///', '')
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    logger.info(f"Initializing Traffic Logs DB at: {LOGS_DATABASE_URL}")

    # Create all tables
    LogBase.metadata.create_all(bind=logs_engine)
