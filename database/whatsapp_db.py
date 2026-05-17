"""
WhatsApp Database Module — encrypted session storage, linked recipients,
preferences, command logs.

Mirrors database/telegram_db.py one-for-one, with one notable difference:
the WhatsApp paired-device session blob (~300 KB of Signal Protocol private
keys, identity, registration info from wars/whatsapp-rust) is encrypted at
rest using a Fernet key derived from:

    PBKDF2-SHA256(
        password = API_KEY_PEPPER,
        salt     = FERNET_SALT (per-install random hex, rotated by env_check)
                   + b":whatsapp-session"   # domain separator
    )

The domain separator prevents the derived key from colliding with the broker
auth-token key (which uses bare FERNET_SALT in database/auth_db.py) or any
other future Fernet domain on the same install. Same approach Signal's own
KDFs use to keep keys derived from one root distinct per purpose.

Anyone with the openalgo.db file AND the API_KEY_PEPPER + FERNET_SALT (i.e.
the .env) can impersonate the linked WhatsApp device. Both must be kept
secret. Losing one without the other leaves the blob unrecoverable.
"""

import base64
import json
import os
from datetime import datetime
from typing import Any

from cachetools import TTLCache
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, scoped_session, sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import func

from utils.logging import get_logger

logger = get_logger(__name__)

# 30-minute TTL caches — same as telegram_db, reduces DB hits in command paths.
_wa_user_cache: TTLCache = TTLCache(maxsize=10000, ttl=1800)
_wa_username_cache: TTLCache = TTLCache(maxsize=10000, ttl=1800)
_wa_preferences_cache: TTLCache = TTLCache(maxsize=10000, ttl=1800)
_wa_credentials_cache: TTLCache = TTLCache(maxsize=10000, ttl=1800)

# Tables live in the main openalgo.db by default. DATABASE_URL is whatever
# the operator configured in .env — we never carve out a separate sqlite file.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///db/openalgo.db")
if DATABASE_URL.startswith("sqlite:///") and ":memory:" not in DATABASE_URL:
    db_path = DATABASE_URL.replace("sqlite:///", "")
    if os.path.dirname(db_path):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)


def _resolve_whatsapp_salt() -> bytes:
    """FERNET_SALT (validated hex) + domain separator. Falls back to the
    same legacy static auth_db uses, with the same domain suffix, so the
    fallback path is still domain-separated from broker auth tokens."""
    raw = (os.getenv("FERNET_SALT") or "").strip()
    if raw and len(raw) >= 32:
        try:
            return bytes.fromhex(raw) + b":whatsapp-session"
        except ValueError:
            pass
    return b"openalgo_static_salt:whatsapp-session"


def _build_fernet() -> Fernet:
    pepper = os.getenv("API_KEY_PEPPER", "default-pepper-change-in-production")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_resolve_whatsapp_salt(),
        iterations=100000,
    )
    return Fernet(base64.urlsafe_b64encode(kdf.derive(pepper.encode())))


fernet = _build_fernet()


# SQLAlchemy engine — same NullPool pattern as the rest of OpenAlgo SQLite usage.
if DATABASE_URL and "sqlite" in DATABASE_URL:
    engine = create_engine(
        DATABASE_URL, poolclass=NullPool, connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(
        DATABASE_URL, pool_pre_ping=True, pool_recycle=3600, pool_size=50, max_overflow=100
    )

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


class WhatsAppConfig(Base):
    """Singleton config row (id=1) — encrypted paired-device session blob plus
    bot operational settings. The blob is what wars.export_session() returns
    after a successful pair; we encrypt it before persisting and decrypt on
    load. wars.WhatsApp.from_bytes() reconstitutes the client from these bytes
    without ever needing to re-pair."""

    __tablename__ = "whatsapp_config"

    id = Column(Integer, primary_key=True, default=1)
    session_blob = Column(LargeBinary)  # Fernet ciphertext of wars session bytes
    own_jid = Column(String(120))  # Device's own WhatsApp JID after pair
    own_phone = Column(String(32))  # Device's own phone number (E.164 digits)
    bot_username = Column(String(255))  # Display name of paired device
    # Single-user OpenAlgo: the operator who paired the device is the bot's
    # implicit "owner". We capture their internal user_id at pair time so the
    # bot's command handlers can look up the right api_key without depending
    # on any per-WhatsApp-user linking step.
    owner_user_id = Column(Integer)
    owner_username = Column(String(255))
    is_paired = Column(Boolean, default=False)
    is_active = Column(Boolean, default=False)  # Bot currently connected
    paired_at = Column(DateTime)
    max_message_length = Column(Integer, default=4096)
    rate_limit_per_minute = Column(Integer, default=30)
    broadcast_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class WhatsAppUser(Base):
    """Linked recipient — a WhatsApp number associated with an OpenAlgo user.
    The same physical phone may be both the device owner (own_jid in config)
    and a linked user (one row here) so it can run command-mode queries."""

    __tablename__ = "whatsapp_users"

    id = Column(Integer, primary_key=True)
    whatsapp_jid = Column(String(120), unique=True, nullable=False, index=True)
    phone_number = Column(String(32), nullable=False, index=True)  # E.164 digits
    openalgo_username = Column(String(255), nullable=False, index=True)
    encrypted_api_key = Column(Text)  # Fernet ciphertext, only set if user wants command mode
    host_url = Column(String(500))
    display_name = Column(String(255))
    broker = Column(String(50), default="default")
    is_active = Column(Boolean, default=True)
    notifications_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    last_command_at = Column(DateTime)

    command_logs = relationship(
        "WhatsAppCommandLog", back_populates="user", cascade="all, delete-orphan"
    )
    notifications = relationship(
        "WhatsAppNotificationQueue", back_populates="user", cascade="all, delete-orphan"
    )
    preferences = relationship(
        "WhatsAppUserPreference",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )


class WhatsAppCommandLog(Base):
    __tablename__ = "whatsapp_command_logs"

    id = Column(Integer, primary_key=True)
    whatsapp_jid = Column(
        String(120), ForeignKey("whatsapp_users.whatsapp_jid"), nullable=False, index=True
    )
    command = Column(String(100), nullable=False)
    parameters = Column(Text)
    executed_at = Column(DateTime, default=func.now())

    user = relationship("WhatsAppUser", back_populates="command_logs")


class WhatsAppNotificationQueue(Base):
    __tablename__ = "whatsapp_notification_queue"

    id = Column(Integer, primary_key=True)
    whatsapp_jid = Column(String(120), ForeignKey("whatsapp_users.whatsapp_jid"), nullable=False)
    message = Column(Text, nullable=False)
    media_path = Column(Text)  # Optional path to image/document for retry
    media_kind = Column(String(20))  # "image" or "document"
    priority = Column(Integer, default=5)
    status = Column(String(20), default="pending", index=True)
    created_at = Column(DateTime, default=func.now())
    sent_at = Column(DateTime)
    error_message = Column(Text)

    user = relationship("WhatsAppUser", back_populates="notifications")


class WhatsAppUserPreference(Base):
    __tablename__ = "whatsapp_user_preferences"

    whatsapp_jid = Column(
        String(120), ForeignKey("whatsapp_users.whatsapp_jid"), primary_key=True
    )
    order_notifications = Column(Boolean, default=True)
    trade_notifications = Column(Boolean, default=True)
    pnl_notifications = Column(Boolean, default=True)
    daily_summary = Column(Boolean, default=True)
    summary_time = Column(String(10), default="18:00")
    language = Column(String(10), default="en")
    timezone = Column(String(50), default="Asia/Kolkata")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    user = relationship("WhatsAppUser", back_populates="preferences")


def _ensure_columns(table: str, columns: dict[str, str]) -> None:
    """Idempotent SQLite ADD COLUMN migration. SQLAlchemy's create_all is
    additive at the TABLE level but does not retro-fit new columns onto an
    existing table — we have to issue ALTER TABLE ourselves. Safe to run
    every boot: PRAGMA table_info is cheap and ADD COLUMN is skipped if
    the column already exists. PostgreSQL/MySQL backends would need their
    own dialect-specific handling; this branch is SQLite-only because that
    is the only supported DATABASE_URL today."""
    if "sqlite" not in (DATABASE_URL or ""):
        return
    from sqlalchemy import text

    with engine.connect() as conn:
        existing = {
            row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))
        }
        for col_name, col_type in columns.items():
            if col_name not in existing:
                logger.info("WhatsApp DB: adding missing column %s.%s", table, col_name)
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"))
        conn.commit()


def init_db() -> None:
    """Create tables and seed the singleton config row if missing."""
    try:
        from database.db_init_helper import init_db_with_logging

        init_db_with_logging(Base, engine, "WhatsApp DB", logger)

        # Schema migrations for tables that existed before columns were added.
        try:
            _ensure_columns(
                "whatsapp_config",
                {
                    "owner_user_id": "INTEGER",
                    "owner_username": "VARCHAR(255)",
                },
            )
        except Exception:
            logger.exception("WhatsApp DB: column migration failed (continuing)")

        config = db_session.query(WhatsAppConfig).filter_by(id=1).first()
        if not config:
            logger.debug("WhatsApp DB: seeding default config row")
            db_session.add(WhatsAppConfig(id=1))
            db_session.commit()
    except Exception:
        logger.exception("WhatsApp DB: init failed")
        db_session.rollback()
    finally:
        db_session.remove()


# ---------------------------------------------------------------------------
# Session blob — the sensitive bit. Fernet-encrypted bytes in/out.
# ---------------------------------------------------------------------------


def save_session_blob(
    blob: bytes,
    own_jid: str | None = None,
    own_phone: str | None = None,
    bot_username: str | None = None,
    owner_user_id: int | None = None,
    owner_username: str | None = None,
) -> bool:
    """Persist the wars session bytes (encrypted) and mark device paired."""
    try:
        if not blob:
            return False
        config = db_session.query(WhatsAppConfig).filter_by(id=1).first()
        if not config:
            config = WhatsAppConfig(id=1)
            db_session.add(config)
        config.session_blob = fernet.encrypt(blob)
        if own_jid:
            config.own_jid = own_jid
        if own_phone:
            config.own_phone = own_phone
        if bot_username:
            config.bot_username = bot_username
        if owner_user_id is not None:
            config.owner_user_id = owner_user_id
        if owner_username:
            config.owner_username = owner_username
        config.is_paired = True
        config.paired_at = datetime.utcnow()
        db_session.commit()
        logger.info("WhatsApp session blob saved (paired device persisted)")
        return True
    except Exception:
        logger.exception("Failed to save WhatsApp session blob")
        db_session.rollback()
        return False
    finally:
        db_session.remove()


def load_session_blob() -> bytes | None:
    """Return decrypted session bytes, or None if device isn't paired."""
    try:
        config = db_session.query(WhatsAppConfig).filter_by(id=1).first()
        if not config or not config.session_blob:
            return None
        return fernet.decrypt(config.session_blob)
    except Exception:
        logger.exception("Failed to decrypt WhatsApp session blob")
        return None
    finally:
        db_session.remove()


def _persist_owner_identity(own_jid: str, own_phone: str) -> bool:
    """Update only the own_jid / own_phone columns. Used when the bot sniffs
    its own identity lazily from the first is_from_me=True message after a
    successful pair — we already have the encrypted session blob and just
    need to record who scanned the QR."""
    try:
        config = db_session.query(WhatsAppConfig).filter_by(id=1).first()
        if not config:
            return False
        if not config.own_jid:
            config.own_jid = own_jid
        if not config.own_phone and own_phone:
            config.own_phone = own_phone
        db_session.commit()
        return True
    except Exception:
        logger.exception("Failed to persist owner identity")
        db_session.rollback()
        return False
    finally:
        db_session.remove()


def clear_session_blob() -> bool:
    """Forget the paired device. User must re-pair to send/receive."""
    try:
        config = db_session.query(WhatsAppConfig).filter_by(id=1).first()
        if not config:
            return False
        config.session_blob = None
        config.own_jid = None
        config.own_phone = None
        config.bot_username = None
        config.owner_user_id = None
        config.owner_username = None
        config.is_paired = False
        config.is_active = False
        config.paired_at = None
        db_session.commit()
        logger.info("WhatsApp session cleared (device unlinked)")
        return True
    except Exception:
        logger.exception("Failed to clear WhatsApp session blob")
        db_session.rollback()
        return False
    finally:
        db_session.remove()


# ---------------------------------------------------------------------------
# Bot config — non-secret operational settings.
# ---------------------------------------------------------------------------


def get_bot_config() -> dict[str, Any]:
    try:
        config = db_session.query(WhatsAppConfig).filter_by(id=1).first()
        if not config:
            return {
                "is_paired": False,
                "is_active": False,
                "own_jid": None,
                "own_phone": None,
                "bot_username": None,
                "max_message_length": 4096,
                "rate_limit_per_minute": 30,
                "broadcast_enabled": True,
            }
        return {
            "is_paired": bool(config.is_paired),
            "is_active": bool(config.is_active),
            "own_jid": config.own_jid,
            "own_phone": config.own_phone,
            "bot_username": config.bot_username,
            "owner_user_id": config.owner_user_id,
            "owner_username": config.owner_username,
            "paired_at": config.paired_at,
            "max_message_length": config.max_message_length,
            "rate_limit_per_minute": config.rate_limit_per_minute,
            "broadcast_enabled": config.broadcast_enabled,
            "created_at": config.created_at,
            "updated_at": config.updated_at,
        }
    except Exception:
        logger.exception("Failed to get WhatsApp bot config")
        return {}
    finally:
        db_session.remove()


def update_bot_config(updates: dict[str, Any]) -> bool:
    """Update non-secret config fields. The session_blob is updated via
    save_session_blob() exclusively — never through this function."""
    SAFE_FIELDS = {
        "is_active",
        "max_message_length",
        "rate_limit_per_minute",
        "broadcast_enabled",
    }
    try:
        config = db_session.query(WhatsAppConfig).filter_by(id=1).first()
        if not config:
            config = WhatsAppConfig(id=1)
            db_session.add(config)
        for key, value in updates.items():
            if key == "rate_limit_per_minute":
                try:
                    value = max(1, min(120, int(value)))
                except (TypeError, ValueError):
                    continue
            if key in SAFE_FIELDS:
                setattr(config, key, value)
        db_session.commit()
        return True
    except Exception:
        logger.exception("Failed to update WhatsApp bot config")
        db_session.rollback()
        return False
    finally:
        db_session.remove()


# ---------------------------------------------------------------------------
# Linked users — recipients addressable by username.
# ---------------------------------------------------------------------------


def _invalidate_user_caches(jid: str | None, username: str | None) -> None:
    if jid:
        _wa_user_cache.pop(f"jid_{jid}", None)
        _wa_credentials_cache.pop(f"creds_{jid}", None)
        _wa_preferences_cache.pop(f"prefs_{jid}", None)
    if username:
        _wa_username_cache.pop(f"username_{username}", None)


def create_or_update_whatsapp_user(
    whatsapp_jid: str,
    phone_number: str,
    username: str,
    api_key: str | None = None,
    host_url: str | None = None,
    display_name: str = "",
    broker: str = "default",
) -> bool:
    try:
        user = db_session.query(WhatsAppUser).filter_by(whatsapp_jid=whatsapp_jid).first()
        encrypted_key = fernet.encrypt(api_key.encode()).decode() if api_key else None

        if user:
            user.openalgo_username = username
            user.phone_number = phone_number
            if encrypted_key is not None:
                user.encrypted_api_key = encrypted_key
            if host_url:
                user.host_url = host_url
            user.display_name = display_name or user.display_name
            user.broker = broker
            user.is_active = True
        else:
            user = WhatsAppUser(
                whatsapp_jid=whatsapp_jid,
                phone_number=phone_number,
                openalgo_username=username,
                encrypted_api_key=encrypted_key,
                host_url=host_url,
                display_name=display_name,
                broker=broker,
            )
            db_session.add(user)
            db_session.add(WhatsAppUserPreference(whatsapp_jid=whatsapp_jid))

        db_session.commit()
        _invalidate_user_caches(whatsapp_jid, username)
        return True
    except Exception:
        logger.exception("Failed to create/update WhatsApp user")
        db_session.rollback()
        return False
    finally:
        db_session.remove()


def get_whatsapp_user(whatsapp_jid: str) -> dict[str, Any] | None:
    cache_key = f"jid_{whatsapp_jid}"
    if cache_key in _wa_user_cache:
        return _wa_user_cache[cache_key]
    try:
        user = (
            db_session.query(WhatsAppUser)
            .filter_by(whatsapp_jid=whatsapp_jid, is_active=True)
            .first()
        )
        if not user:
            return None
        result = {
            "id": user.id,
            "whatsapp_jid": user.whatsapp_jid,
            "phone_number": user.phone_number,
            "openalgo_username": user.openalgo_username,
            "host_url": user.host_url,
            "display_name": user.display_name,
            "broker": user.broker,
            "is_active": user.is_active,
            "notifications_enabled": user.notifications_enabled,
            "created_at": user.created_at,
            "updated_at": user.updated_at,
            "last_command_at": user.last_command_at,
        }
        _wa_user_cache[cache_key] = result
        return result
    except Exception:
        logger.exception("Failed to get WhatsApp user")
        return None
    finally:
        db_session.remove()


def get_whatsapp_user_by_username(username: str) -> dict[str, Any] | None:
    cache_key = f"username_{username}"
    if cache_key in _wa_username_cache:
        return _wa_username_cache[cache_key]
    try:
        user = (
            db_session.query(WhatsAppUser)
            .filter_by(openalgo_username=username, is_active=True)
            .first()
        )
        if not user:
            return None
        result = {
            "id": user.id,
            "whatsapp_jid": user.whatsapp_jid,
            "phone_number": user.phone_number,
            "openalgo_username": user.openalgo_username,
            "display_name": user.display_name,
            "broker": user.broker,
            "is_active": user.is_active,
            "notifications_enabled": user.notifications_enabled,
            "created_at": user.created_at,
            "updated_at": user.updated_at,
            "last_command_at": user.last_command_at,
        }
        _wa_username_cache[cache_key] = result
        return result
    except Exception:
        logger.exception("Failed to get WhatsApp user by username")
        return None
    finally:
        db_session.remove()


def get_user_credentials(whatsapp_jid: str) -> dict[str, Any] | None:
    """Return decrypted api_key + host_url for command-mode SDK calls."""
    cache_key = f"creds_{whatsapp_jid}"
    if cache_key in _wa_credentials_cache:
        return _wa_credentials_cache[cache_key]
    try:
        user = (
            db_session.query(WhatsAppUser)
            .filter_by(whatsapp_jid=whatsapp_jid, is_active=True)
            .first()
        )
        if not user or not user.encrypted_api_key:
            return None
        try:
            api_key = fernet.decrypt(user.encrypted_api_key.encode()).decode()
        except Exception:
            logger.exception("Failed to decrypt user api_key — schema or key drift?")
            return None
        result = {
            "api_key": api_key,
            "host_url": user.host_url or os.getenv("HOST_SERVER", "http://127.0.0.1:5000"),
            "username": user.openalgo_username,
            "broker": user.broker,
        }
        _wa_credentials_cache[cache_key] = result
        return result
    except Exception:
        logger.exception("Failed to load WhatsApp user credentials")
        return None
    finally:
        db_session.remove()


def delete_whatsapp_user(whatsapp_jid: str) -> bool:
    """Soft-delete a linked user. Notifications stop; row is kept for audit."""
    try:
        user = db_session.query(WhatsAppUser).filter_by(whatsapp_jid=whatsapp_jid).first()
        if not user:
            return False
        username = user.openalgo_username
        user.is_active = False
        db_session.commit()
        _invalidate_user_caches(whatsapp_jid, username)
        return True
    except Exception:
        logger.exception("Failed to delete WhatsApp user")
        db_session.rollback()
        return False
    finally:
        db_session.remove()


def get_all_whatsapp_users(filters: dict | None = None) -> list[dict[str, Any]]:
    try:
        query = db_session.query(WhatsAppUser).filter_by(is_active=True)
        if filters:
            if "broker" in filters:
                query = query.filter_by(broker=filters["broker"])
            if "notifications_enabled" in filters:
                query = query.filter_by(notifications_enabled=filters["notifications_enabled"])
        users = query.all()
        return [
            {
                "id": u.id,
                "whatsapp_jid": u.whatsapp_jid,
                "phone_number": u.phone_number,
                "openalgo_username": u.openalgo_username,
                "display_name": u.display_name,
                "broker": u.broker,
                "notifications_enabled": u.notifications_enabled,
                "created_at": u.created_at,
                "last_command_at": u.last_command_at,
            }
            for u in users
        ]
    except Exception:
        logger.exception("Failed to list WhatsApp users")
        return []
    finally:
        db_session.remove()


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------


def get_user_preferences(whatsapp_jid: str) -> dict[str, Any]:
    cache_key = f"prefs_{whatsapp_jid}"
    if cache_key in _wa_preferences_cache:
        return _wa_preferences_cache[cache_key]
    try:
        prefs = (
            db_session.query(WhatsAppUserPreference)
            .filter_by(whatsapp_jid=whatsapp_jid)
            .first()
        )
        if not prefs:
            result = {
                "order_notifications": True,
                "trade_notifications": True,
                "pnl_notifications": True,
                "daily_summary": True,
                "summary_time": "18:00",
                "language": "en",
                "timezone": "Asia/Kolkata",
            }
        else:
            result = {
                "order_notifications": prefs.order_notifications,
                "trade_notifications": prefs.trade_notifications,
                "pnl_notifications": prefs.pnl_notifications,
                "daily_summary": prefs.daily_summary,
                "summary_time": prefs.summary_time,
                "language": prefs.language,
                "timezone": prefs.timezone,
            }
        _wa_preferences_cache[cache_key] = result
        return result
    except Exception:
        logger.exception("Failed to get WhatsApp user preferences")
        return {}
    finally:
        db_session.remove()


def update_user_preferences(whatsapp_jid: str, updates: dict[str, Any]) -> bool:
    ALLOWED = {
        "order_notifications",
        "trade_notifications",
        "pnl_notifications",
        "daily_summary",
        "summary_time",
        "language",
        "timezone",
    }
    try:
        prefs = (
            db_session.query(WhatsAppUserPreference)
            .filter_by(whatsapp_jid=whatsapp_jid)
            .first()
        )
        if not prefs:
            prefs = WhatsAppUserPreference(whatsapp_jid=whatsapp_jid)
            db_session.add(prefs)
        for key, value in updates.items():
            if key in ALLOWED:
                setattr(prefs, key, value)
        db_session.commit()
        _wa_preferences_cache.pop(f"prefs_{whatsapp_jid}", None)
        return True
    except Exception:
        logger.exception("Failed to update WhatsApp user preferences")
        db_session.rollback()
        return False
    finally:
        db_session.remove()


# ---------------------------------------------------------------------------
# Command logs + notification queue
# ---------------------------------------------------------------------------


def log_command(whatsapp_jid: str, command: str, parameters: dict | None = None) -> None:
    try:
        params_json = json.dumps(parameters) if parameters else None
        db_session.add(
            WhatsAppCommandLog(
                whatsapp_jid=whatsapp_jid, command=command, parameters=params_json
            )
        )
        user = db_session.query(WhatsAppUser).filter_by(whatsapp_jid=whatsapp_jid).first()
        if user:
            user.last_command_at = func.now()
        db_session.commit()
    except Exception:
        logger.exception("Failed to log WhatsApp command")
        db_session.rollback()
    finally:
        db_session.remove()


def get_command_stats(days: int = 7) -> dict[str, Any]:
    from datetime import timedelta

    try:
        since = datetime.utcnow() - timedelta(days=days)
        rows = (
            db_session.query(WhatsAppCommandLog)
            .filter(WhatsAppCommandLog.executed_at >= since)
            .all()
        )
        by_cmd: dict[str, int] = {}
        for r in rows:
            by_cmd[r.command] = by_cmd.get(r.command, 0) + 1
        return {
            "total_commands": len(rows),
            "by_command": by_cmd,
            "days": days,
        }
    except Exception:
        logger.exception("Failed to get WhatsApp command stats")
        return {"total_commands": 0, "by_command": {}, "days": days}
    finally:
        db_session.remove()


def add_notification(
    whatsapp_jid: str,
    message: str,
    priority: int = 5,
    media_path: str | None = None,
    media_kind: str | None = None,
) -> bool:
    try:
        db_session.add(
            WhatsAppNotificationQueue(
                whatsapp_jid=whatsapp_jid,
                message=message,
                priority=priority,
                media_path=media_path,
                media_kind=media_kind,
            )
        )
        db_session.commit()
        return True
    except Exception:
        logger.exception("Failed to enqueue WhatsApp notification")
        db_session.rollback()
        return False
    finally:
        db_session.remove()


# Auto-initialize on first import — matches database/telegram_db.py:858
# behavior so the tables exist as soon as any caller pulls in this module.
init_db()
