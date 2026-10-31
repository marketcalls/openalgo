# database/auth_db.py

import base64
import os
import threading
from dataclasses import dataclass
from datetime import datetime

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import func

from utils.logging import get_logger
from utils.thread_safe_cache import MISSING, LockedTTLCache

# Initialize logger
logger = get_logger(__name__)

# Initialize Argon2 hasher
ph = PasswordHasher()

DATABASE_URL = os.getenv("DATABASE_URL")

# Security: Require API_KEY_PEPPER environment variable (fail fast if missing)
# Pepper must be at least 32 bytes (64 hex characters) for cryptographic security
_pepper_value = os.getenv("API_KEY_PEPPER")
if not _pepper_value:
    raise RuntimeError(
        "CRITICAL: API_KEY_PEPPER environment variable is not set. "
        "This is required for secure password and API key hashing. "
        'Generate one using: python -c "import secrets; print(secrets.token_hex(32))"'
    )
if len(_pepper_value) < 32:
    raise RuntimeError(
        f"CRITICAL: API_KEY_PEPPER must be at least 32 characters (got {len(_pepper_value)}). "
        'Generate a secure pepper using: python -c "import secrets; print(secrets.token_hex(32))"'
    )
PEPPER = _pepper_value


# Setup Fernet encryption for auth tokens.
#
# The KDF salt has two sources, in order of preference:
#   1. FERNET_SALT env var (per-install random hex, 32+ chars). This is the
#      production path. utils/env_check.py auto-provisions it on first boot
#      (and migrates existing ciphertext) so by the time this module imports,
#      the env var is set.
#   2. The legacy hardcoded literal b"openalgo_static_salt". This is the
#      fallback for one-off scripts that import auth_db directly without
#      going through the env_check bootstrap (CLI utilities, ad-hoc REPL,
#      docs/typecheck runs). A one-time stderr warning fires so the operator
#      notices if a real production process ever hits this path.
def _resolve_fernet_salt() -> bytes:
    raw = (os.getenv("FERNET_SALT") or "").strip()
    if raw and len(raw) >= 32:
        try:
            return bytes.fromhex(raw)
        except ValueError:
            pass
    # Fallback path. Print once so prod misuse is visible without spamming.
    if not getattr(_resolve_fernet_salt, "_warned", False):
        import sys as _sys
        _sys.stderr.write(
            "[auth_db] WARNING: FERNET_SALT not set or invalid; using legacy\n"
            "static salt. Run the app once via app.py so utils/env_check.py\n"
            "auto-provisions a per-install salt.\n"
        )
        _resolve_fernet_salt._warned = True  # type: ignore[attr-defined]
    return b"openalgo_static_salt"


def get_encryption_key():
    """Generate a Fernet key from PEPPER + per-install FERNET_SALT."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_resolve_fernet_salt(),
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(PEPPER.encode()))
    return Fernet(key)


# Initialize Fernet cipher
fernet = get_encryption_key()


# Calculate cache TTL based on session expiry time to minimize DB hits
def get_session_based_cache_ttl():
    """Calculate cache TTL based on daily session expiry time in .env"""
    try:
        from datetime import datetime

        import pytz

        # Get session expiry time from environment (default 3 AM)
        expiry_time = os.getenv("SESSION_EXPIRY_TIME", "03:00")
        hour, minute = map(int, expiry_time.split(":"))

        # Calculate time until next session expiry
        now_utc = datetime.now(pytz.timezone("UTC"))
        now_ist = now_utc.astimezone(pytz.timezone("Asia/Kolkata"))

        # Today's expiry time
        today_expiry = now_ist.replace(hour=hour, minute=minute, second=0, microsecond=0)

        # If we've passed today's expiry, use tomorrow's expiry
        if now_ist >= today_expiry:
            from datetime import timedelta

            today_expiry += timedelta(days=1)

        # Calculate seconds until expiry
        time_until_expiry = (today_expiry - now_ist).total_seconds()

        # Use time until session expiry, with reasonable bounds
        # Minimum 5 minutes, maximum 24 hours
        ttl_seconds = max(300, min(time_until_expiry, 24 * 3600))

        logger.debug(
            f"Auth cache TTL set to {ttl_seconds} seconds until session expiry at {today_expiry.strftime('%H:%M IST')}"
        )
        return int(ttl_seconds)

    except Exception as e:
        logger.warning(f"Could not calculate session-based cache TTL, using 5-minute default: {e}")
        return 300  # Fallback to 5 minutes


# The caches below are shared by request threads, the event bus pool,
# background services and, on the dev server, the websocket proxy's thread.
# They are LockedTTLCache rather than cachetools' TTLCache because under the
# gthread worker those really do run at once, and a plain TTLCache is not
# thread-safe: even its get() is a membership test followed by a subscript.
#
# Every reader fills through the generation it read before its database query
# (_fill below), and every writer clears or invalidates strictly after its
# commit. A read that started before a re-login, a revoke or an API key
# rotation therefore cannot put the superseded value back after the writer
# cleared it; its caller still gets the value it read, which was current when
# it asked. Under eventlet none of this interleaved, and the outcome of a
# read that does not race a writer is unchanged.

# Define auth token cache with TTL until session expiry to minimize DB hits
auth_cache = LockedTTLCache(maxsize=1024, ttl=get_session_based_cache_ttl())
# Define feed token cache with same TTL
feed_token_cache = LockedTTLCache(maxsize=1024, ttl=get_session_based_cache_ttl())
# Define a cache for broker names with a 5-minute TTL (longer since broker rarely changes)
broker_cache = LockedTTLCache(maxsize=1024, ttl=3000)
# Define a cache for verified API keys with 24-hour TTL
# Security: Only caches user_id (not sensitive), invalidated on key regeneration
# Long TTL is safe because cache is invalidated when keys are regenerated
verified_api_key_cache = LockedTTLCache(maxsize=1024, ttl=36000)  # 10 hours
# Define a cache for invalid API keys with shorter 5-minute TTL (prevent cache poisoning)
invalid_api_key_cache = LockedTTLCache(maxsize=512, ttl=300)  # 5 minutes
# Order mode (auto/semi_auto) is checked on every order request; cache it to
# avoid a DB query per order. Invalidated by update_order_mode via
# invalidate_user_cache, so the TTL is only a backstop.
order_mode_cache = LockedTTLCache(maxsize=128, ttl=60)


def _generation(cache):
    """The cache's generation before a load, or None for a plain mapping.

    Tests substitute plain dict subclasses for these caches to stage a race;
    a mapping without a generation is filled directly, as before.
    """
    return getattr(cache, "generation", None)


def _fill(cache, key, value, generation) -> None:
    """Store a loaded value unless the cache was invalidated since ``generation``."""
    fill = getattr(cache, "fill", None)
    if fill is not None and generation is not None:
        fill(key, value, generation)
    else:
        cache[key] = value


def _invalidate(cache, key) -> bool:
    """Drop ``key`` so no read that started earlier can store it again.

    Returns:
        True when the cache held an entry for ``key``.
    """
    invalidate = getattr(cache, "invalidate", None)
    if invalidate is None:
        return cache.pop(key, MISSING) is not MISSING
    with cache.lock:
        held = cache.get(key, MISSING) is not MISSING
        invalidate(key)
    return held

# Conditionally create engine based on DB type
if DATABASE_URL and "sqlite" in DATABASE_URL:
    # SQLite: Use NullPool — each checkout creates a fresh connection.
    # Session cleanup is handled by app.py teardown_appcontext.
    # StaticPool must NOT be used: concurrent requests on a single shared
    # SQLite connection cause "bad parameter or other API misuse" errors.
    engine = create_engine(
        DATABASE_URL, poolclass=NullPool, connect_args={"check_same_thread": False}
    )
else:
    # For other databases like PostgreSQL, use connection pooling
    engine = create_engine(DATABASE_URL, pool_size=50, max_overflow=100, pool_timeout=10)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


class Auth(Base):
    __tablename__ = "auth"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    auth = Column(Text, nullable=False)
    feed_token = Column(
        Text, nullable=True
    )  # Make it nullable as not all brokers will provide this
    broker = Column(String(20), nullable=False)
    user_id = Column(String(255), nullable=True)  # Add user_id column
    is_revoked = Column(Boolean, default=False)

    # Samco 2FA fields
    secret_api_key = Column(Text, nullable=True)
    primary_ip = Column(String(45), nullable=True)
    secondary_ip = Column(String(45), nullable=True)
    ip_updated_at = Column(DateTime, nullable=True)

    # Generic auxiliary fields for any broker needing extra storage
    aux_param1 = Column(Text, nullable=True)
    aux_param2 = Column(Text, nullable=True)
    aux_param3 = Column(Text, nullable=True)
    aux_param4 = Column(Text, nullable=True)

    # Performance indexes for frequently queried columns
    __table_args__ = (
        Index("idx_auth_broker", "broker"),  # Speeds up get_broker_name() queries
        Index("idx_auth_user_id", "user_id"),  # Speeds up get_user_id() lookups
        Index("idx_auth_is_revoked", "is_revoked"),  # Speeds up token validity checks
    )


@dataclass(frozen=True, slots=True)
class AuthRecord:
    """An immutable copy of the ``Auth`` columns the token caches need.

    The token caches used to hold live ``Auth`` instances. An instance belongs
    to the scoped session of the thread that loaded it: once that session is
    removed at request teardown, or its commit expires the instance, the next
    attribute read on another thread either raises DetachedInstanceError or
    refreshes through a session that is not its own (``flow_db`` lost five
    minutes of alerts to exactly that). A frozen copy has neither problem.
    The token fields stay encrypted, as they are in the row.
    """

    name: str
    auth: str | None
    feed_token: str | None
    broker: str | None
    user_id: str | None
    is_revoked: bool

    @classmethod
    def from_row(cls, row) -> "AuthRecord":
        """Copy the cached columns out of an ``Auth`` row."""
        return cls(
            name=row.name,
            auth=row.auth,
            feed_token=row.feed_token,
            broker=row.broker,
            user_id=row.user_id,
            is_revoked=bool(row.is_revoked),
        )


def _as_record(value) -> AuthRecord | None:
    """Return ``value`` as an AuthRecord, or None when it is not a token record."""
    if isinstance(value, AuthRecord):
        return value
    if isinstance(value, Auth):
        return AuthRecord.from_row(value)
    return None


class ApiKeys(Base):
    __tablename__ = "api_keys"
    id = Column(Integer, primary_key=True)
    user_id = Column(String, nullable=False, unique=True)
    api_key_hash = Column(Text, nullable=False)  # For verification
    api_key_encrypted = Column(Text, nullable=False)  # For retrieval
    created_at = Column(DateTime(timezone=True), default=func.now())
    order_mode = Column(String(20), default="auto")  # 'auto' or 'semi_auto'

    # Performance indexes
    __table_args__ = (
        Index("idx_api_keys_order_mode", "order_mode"),  # Speeds up filtering by order mode
        Index("idx_api_keys_created_at", "created_at"),  # Speeds up time-based queries
    )


class ActiveSession(Base):
    """Tracks active login sessions across devices for a user."""
    __tablename__ = "active_sessions"
    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False, index=True)
    session_id = Column(String(64), unique=True, nullable=False)  # Random token to identify session
    device_info = Column(String(500), nullable=True)  # User-Agent string
    ip_address = Column(String(45), nullable=True)
    broker = Column(String(20), nullable=True)
    login_time = Column(DateTime(timezone=True), default=func.now())
    last_seen = Column(DateTime(timezone=True), default=func.now())

    __table_args__ = (
        Index("idx_active_sessions_username", "username"),
    )


class LoginAttempt(Base):
    """Records all login attempts (successful and failed) for security auditing."""
    __tablename__ = "login_attempts"
    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False)
    ip_address = Column(String(45), nullable=True)
    device_info = Column(String(500), nullable=True)  # User-Agent
    status = Column(String(20), nullable=False)  # 'success', 'failed', 'resumed'
    login_type = Column(String(20), nullable=True)  # 'password', 'oauth', 'resume'
    broker = Column(String(20), nullable=True)
    failure_reason = Column(String(255), nullable=True)  # e.g. 'invalid_password', 'token_expired'
    timestamp = Column(DateTime(timezone=True), default=func.now())

    __table_args__ = (
        Index("idx_login_attempts_username", "username"),
        Index("idx_login_attempts_timestamp", "timestamp"),
        Index("idx_login_attempts_status", "status"),
    )


class SessionRevocation(Base):
    """When a user last ended every session: a logout, a password change or a reset.

    The browser session is a signed cookie, so the server cannot delete a copy
    held by another device. A session whose sign-in is older than this instant
    is refused instead (utils.session), which is what makes a logout end the
    sign-in on every device rather than only on the one that clicked it.
    """

    __tablename__ = "session_revocations"
    username = Column(String(255), primary_key=True)
    revoked_at = Column(DateTime, nullable=False)  # naive UTC
    # A logout from a sign-in that never reached a broker login ends every
    # such sign-in, and leaves the devices on the broker session alone.
    pre_broker_revoked_at = Column(DateTime, nullable=True)  # naive UTC


#: revoked_at of a row written only for a pre-broker logout: no session ended.
_NEVER = datetime(1970, 1, 1)


# Read on every authenticated request, written on logout and password changes.
_session_revocation_cache = LockedTTLCache(maxsize=64, ttl=60)

# Every write that decides who is signed in to which broker takes this lock: a
# login's final checks and the token write it guards (upsert_auth with a
# fence), every sign-out (_record_revocation), and a change to saved broker
# keys (blueprints/broker_config.py). A check made under it is still true when
# the write it guards lands. Reentrant, because a login that switches brokers
# signs the other devices out inside its own commit. Only requests and
# scheduler jobs take it, never one of the real threads (CLAUDE.md), so the
# stdlib lock is right: green under eventlet, real under gthread. Nothing
# waits on a broker or the network while holding it: upsert_auth hands its
# feed teardown back to the caller (``defer``).
_commit_lock = threading.RLock()


def auth_commit_guard():
    """The lock a login's final checks and its token write are made under."""
    return _commit_lock


class AuthCommitRefused(Exception):
    """A login's final checks refused its token write. Nothing was stored.

    Attributes:
        code: The refusal code Select Broker turns into a sentence.
        message: A sentence for the trader.
    """

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _now_ist():
    """Get current time in IST."""
    from datetime import datetime

    import pytz
    return datetime.now(pytz.timezone("Asia/Kolkata"))


def log_login_attempt(username, ip_address=None, device_info=None, status="failed",
                      login_type="password", broker=None, failure_reason=None):
    """Record a login attempt for audit purposes. All records are retained permanently."""
    try:
        attempt = LoginAttempt(
            username=username,
            ip_address=ip_address,
            device_info=device_info[:500] if device_info else None,
            status=status,
            login_type=login_type,
            broker=broker,
            failure_reason=failure_reason,
            timestamp=_now_ist(),
        )
        db_session.add(attempt)
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        logger.error(f"Error logging login attempt: {e}")


def get_login_attempts(limit=100, status_filter=None):
    """Get recent login attempts, optionally filtered by status."""
    try:
        query = LoginAttempt.query.order_by(LoginAttempt.timestamp.desc())
        if status_filter:
            query = query.filter(LoginAttempt.status == status_filter)
        attempts = query.limit(limit).all()
        return [
            {
                "username": a.username,
                "ip_address": a.ip_address,
                "device_info": a.device_info,
                "status": a.status,
                "login_type": a.login_type,
                "broker": a.broker,
                "failure_reason": a.failure_reason,
                "timestamp": a.timestamp.isoformat() if a.timestamp else None,
            }
            for a in attempts
        ]
    except Exception as e:
        logger.error(f"Error getting login attempts: {e}")
        return []


def clear_login_attempts():
    """Clear all login attempt records."""
    try:
        LoginAttempt.query.delete()
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        logger.error(f"Error clearing login attempts: {e}")


MAX_SESSIONS_PER_USER = 5  # Safety cap to prevent unbounded growth


def register_session(username, session_id, device_info=None, ip_address=None, broker=None):
    """Register a new active session for a user.
    Replaces any previous session from the same user+IP to prevent accumulation.
    Enforces a maximum of MAX_SESSIONS_PER_USER sessions per user.
    """
    try:
        # Remove stale sessions from the same device (same user + IP)
        if ip_address:
            ActiveSession.query.filter_by(username=username, ip_address=ip_address).delete()

        # Enforce per-user session cap — remove oldest if at limit
        current_count = ActiveSession.query.filter_by(username=username).count()
        if current_count >= MAX_SESSIONS_PER_USER:
            oldest = ActiveSession.query.filter_by(username=username).order_by(
                ActiveSession.login_time.asc()
            ).first()
            if oldest:
                db_session.delete(oldest)

        now = _now_ist()
        active = ActiveSession(
            username=username,
            session_id=session_id,
            device_info=device_info,
            ip_address=ip_address,
            broker=broker,
            login_time=now,
            last_seen=now,
        )
        db_session.add(active)
        db_session.commit()
        return True
    except Exception as e:
        db_session.rollback()
        logger.error(f"Error registering session: {e}")
        return False


def remove_session(session_id):
    """Remove a session when user logs out."""
    try:
        ActiveSession.query.filter_by(session_id=session_id).delete()
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        logger.error(f"Error removing session: {e}")


def get_active_sessions(username):
    """Get all active sessions for a user."""
    try:
        sessions = ActiveSession.query.filter_by(username=username).order_by(
            ActiveSession.last_seen.desc()
        ).all()
        return [
            {
                "session_id": s.session_id,
                "device_info": s.device_info,
                "ip_address": s.ip_address,
                "broker": s.broker,
                "login_time": s.login_time.isoformat() if s.login_time else None,
                "last_seen": s.last_seen.isoformat() if s.last_seen else None,
            }
            for s in sessions
        ]
    except Exception as e:
        logger.error(f"Error getting active sessions: {e}")
        return []


def update_session_last_seen(session_id):
    """Update last_seen timestamp for a session."""
    try:
        active = ActiveSession.query.filter_by(session_id=session_id).first()
        if active:
            active.last_seen = _now_ist()
            db_session.commit()
    except Exception as e:
        db_session.rollback()
        logger.error(f"Error updating session last_seen: {e}")


def clear_user_sessions(username):
    """Clear all sessions for a user (e.g., on token revocation at 3 AM)."""
    try:
        ActiveSession.query.filter_by(username=username).delete()
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        logger.error(f"Error clearing user sessions: {e}")


def _revocations(username):
    """(revoked_at, pre_broker_revoked_at) of ``username``, each aware UTC or None.

    Returns:
        tuple | MISSING: MISSING when it cannot be read.
    """
    from datetime import UTC

    def _aware(value):
        return value.replace(tzinfo=UTC) if value and value > _NEVER else None

    def _load():
        try:
            row = SessionRevocation.query.filter_by(username=username).first()
            if row is None:
                return (None, None)
            return (_aware(row.revoked_at), _aware(row.pre_broker_revoked_at))
        except Exception:
            logger.exception("Could not read when sessions were last ended")
            return MISSING

    return _session_revocation_cache.get_or_load(
        username, _load, should_cache=lambda v: v is not MISSING
    )


def broker_logged_in_at(username, when_utc):
    """The broker ``username`` was logged in to at ``when_utc`` (naive UTC), or None.

    The broker of the latest successful broker login at or before then: one
    broker is logged in at a time, so an order placed then went to it. Read
    from the login attempts, kept permanently. Their timestamps are stored in
    IST (naive in SQLite).
    """
    from datetime import UTC

    import pytz

    ist = pytz.timezone("Asia/Kolkata")
    when = when_utc.replace(tzinfo=UTC)
    try:
        rows = (
            LoginAttempt.query.filter(
                LoginAttempt.username == username,
                LoginAttempt.status == "success",
                LoginAttempt.broker.isnot(None),
                LoginAttempt.broker != "",
            )
            .order_by(LoginAttempt.timestamp.desc())
            .limit(200)
            .all()
        )
    except Exception:
        logger.exception("Could not read which broker was logged in at a time")
        return None
    for row in rows:
        stamp = row.timestamp
        if stamp is None:
            continue
        stamp = ist.localize(stamp) if stamp.tzinfo is None else stamp
        if stamp <= when:
            return row.broker
    return None


def get_sessions_revoked_at(username):
    """When ``username`` last ended every session, as an aware UTC datetime.

    Returns:
        datetime | None: None when never, or when it cannot be read; a read
        failure must not sign every device out.
    """
    value = _revocations(username)
    return None if value is MISSING else value[0]


def get_pre_broker_revoked_at(username):
    """When ``username`` last logged out of a sign-in with no broker login, aware UTC.

    Every sign-in from before then that has not reached a broker login is
    ended (utils.session.sign_in_revoked).

    Returns:
        datetime | None: None when never, or when it cannot be read.
    """
    value = _revocations(username)
    return None if value is MISSING else value[1]


def _record_revocation(username, field):
    from datetime import UTC

    from database.broker_keys_db import clear_login_states

    # Under the commit guard: a login whose final checks pass stores its token
    # before this sign-out is recorded, or sees it and stores nothing.
    with _commit_lock:
        now = datetime.now(UTC).replace(tzinfo=None)
        try:
            row = SessionRevocation.query.filter_by(username=username).first()
            if row is None:
                row = SessionRevocation(username=username, revoked_at=_NEVER)
                db_session.add(row)
            setattr(row, field, now)
            db_session.commit()
            recorded = True
        except Exception:
            db_session.rollback()
            logger.exception("Could not record the end of the sessions")
            recorded = False
        finally:
            _session_revocation_cache.invalidate(username)
        # A broker login started from an ended sign-in must not complete: it
        # would sign the browser back in (the XTS brokers answer without the
        # cookie).
        clear_login_states()
    return recorded


def revoke_all_sessions(username):
    """End every browser session of ``username`` signed in before now.

    Every broker login started before now is cancelled with them.

    Returns:
        bool: True when recorded.
    """
    return _record_revocation(username, "revoked_at")


def revoke_pre_broker_sessions(username):
    """End every sign-in of ``username`` from before now that has no broker login.

    A logout from such a sign-in: a copy of its cookie stops working, and so
    does any other sign-in that has not reached a broker login. The devices on
    the broker session are left alone; their logout ends everything
    (revoke_all_sessions). Every broker login started before now is cancelled.

    Returns:
        bool: True when recorded.
    """
    return _record_revocation(username, "pre_broker_revoked_at")


def ensure_session_revocation_columns(target_engine=None):
    """Add the columns session_revocations gained after it was first created.

    Run at startup and by upgrade/migrate_broker_keys.py, for an install that
    created the table before pre_broker_revoked_at existed. Idempotent.

    Returns:
        list[str]: The columns added.
    """
    from sqlalchemy import inspect, text

    target_engine = target_engine or engine
    inspector = inspect(target_engine)
    if "session_revocations" not in inspector.get_table_names():
        return []
    present = {column["name"] for column in inspector.get_columns("session_revocations")}
    added = []
    if "pre_broker_revoked_at" not in present:
        with target_engine.begin() as conn:
            conn.execute(
                text("ALTER TABLE session_revocations ADD COLUMN pre_broker_revoked_at DATETIME")
            )
        added.append("pre_broker_revoked_at")
    return added


def init_db():
    """Initialize the authentication database tables.

    Creates the ``auth`` and ``api_keys`` tables if they do not
    already exist, using the shared ``db_init_helper`` for
    consistent startup logging.
    """
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Auth DB", logger)
    try:
        ensure_session_revocation_columns()
    except Exception:
        logger.exception("Could not add the new session sign-out column")


def safe_decrypt_token(value):
    """Decrypt a Fernet-encrypted value, falling back to the raw value
    when decryption fails (typical reason: the column still holds plaintext
    from before the rotate_pepper.py migration). Returns None for empty input.

    This is the read-path helper used by columns that transitioned from
    plaintext to ciphertext (totp_secret, samco secret_api_key, flow api_key,
    telegram bot token). Callers must pass values encrypted with the same
    Fernet key (i.e. the auth_db one) — telegram_db and settings_db have
    their own derivations and use their own helpers.
    """
    if not value:
        return None
    decrypted = decrypt_token(value)
    return decrypted if decrypted is not None else value


def encrypt_token(token):
    """Encrypt auth token"""
    if not token:
        return ""
    return fernet.encrypt(token.encode()).decode()


# Track recent ciphertext fingerprints we've failed to decrypt so we log each
# orphan row's full traceback once per hour, then suppress repeated noise.
# Bound the cache: malformed tokens have an unbounded key space, and this
# worker can run indefinitely. Without dedupe, a row encrypted under a lost salt
# (e.g. the row left as-is after a Fernet salt rotation, see issue #1394)
# triggers a full ERROR + traceback on every WebSocket re-connect attempt,
# spamming the logs with hundreds of identical entries.
_decrypt_failure_fingerprints = LockedTTLCache(maxsize=256, ttl=3600)


def decrypt_token(encrypted_token):
    """Decrypt auth token"""
    if not encrypted_token:
        return ""
    try:
        return fernet.decrypt(encrypted_token.encode()).decode()
    except Exception as e:
        # Hash the ciphertext (not the plaintext — there is no plaintext yet)
        # so we don't keep the full token in memory just to dedupe log lines.
        import hashlib

        try:
            payload = (
                encrypted_token.encode()
                if isinstance(encrypted_token, str)
                else encrypted_token
            )
            fp = hashlib.blake2s(payload, digest_size=8).hexdigest()
        except Exception:
            fp = "unknown"

        # Check and insert together so concurrent requests report one full
        # traceback for the same bad ciphertext. Keep logging outside the lock.
        with _decrypt_failure_fingerprints.lock:
            seen = fp in _decrypt_failure_fingerprints
            if not seen:
                _decrypt_failure_fingerprints[fp] = True

        if seen:
            # Already reported the full traceback once — keep the signal
            # but at debug level so it doesn't spam ERROR logs.
            logger.debug(f"Repeat decrypt failure (fingerprint={fp})")
        else:
            logger.exception(
                f"Error decrypting token (fingerprint={fp}): {e}. "
                "This row may have been encrypted under a previous "
                "API_KEY_PEPPER or FERNET_SALT and survived a rotation. "
                "Re-authenticate the affected broker / user to overwrite "
                "the orphan ciphertext with a fresh value."
            )
        return None


def upsert_auth(
    name, auth_token, broker, feed_token=None, user_id=None, revoke=False, fence=None, defer=None
):
    """Store encrypted auth token and feed token if provided.

    Also publishes cache invalidation events via ZeroMQ for multi-process deployments.
    This ensures WebSocket proxy and other processes clear their stale cached tokens.
    See GitHub issue #765 for details on the cross-process cache synchronization problem.

    Args:
        fence: For a login, its final checks: called under the commit guard
            immediately before the write, returning (code, message) to refuse
            it or None. A sign-out, a key change or another login landing
            after the caller's own checks is seen here, not after the write.
        defer: A list. When given, the feed and order-feed teardown is appended
            to it instead of run, so the caller runs it once it has released
            the commit guard.

    Raises:
        AuthCommitRefused: When ``fence`` refused; nothing was written.
    """
    with _commit_lock:
        if fence is not None:
            refused = fence()
            if refused is not None:
                raise AuthCommitRefused(*refused)
        result = _store_auth(name, auth_token, broker, feed_token, user_id, revoke)
    if result is None:
        return None
    auth_id, after = result
    if after is not None:
        if defer is not None:
            defer.append(after)
        else:
            after()
    return auth_id


def _store_auth(name, auth_token, broker, feed_token, user_id, revoke):
    """The token write of upsert_auth. Hold the commit guard.

    Returns:
        tuple | None: (row id, the feed teardown to run, or None).
    """
    encrypted_token = encrypt_token(auth_token)
    encrypted_feed_token = encrypt_token(feed_token) if feed_token else None

    auth_obj = Auth.query.filter_by(name=name).first()

    # Decide whether the broker session MATERIALLY changed. A multi-device /
    # multi-session login re-persists the SAME token (the login path resumes an
    # existing valid broker session — see blueprints/auth._try_resume_broker_session),
    # and OpenAlgo is single-user/single-broker per instance, so all devices share
    # ONE server-side broker WebSocket feed. Tearing that feed down on an unchanged
    # token kills the stream for the already-connected device until it refreshes
    # (Shoonya) and, on Finvasia/Noren brokers that allow a single active session,
    # drops the broker token entirely (Flattrade). See issue #1591. Fernet ciphertext
    # is non-deterministic, so compare DECRYPTED plaintext, not the encrypted blobs.
    token_changed = True
    if auth_obj is not None:
        try:
            prev_token = decrypt_token(auth_obj.auth) if auth_obj.auth else None
        except Exception:
            prev_token = None  # undecryptable (e.g. post pepper/salt rotation) -> treat as changed
        try:
            prev_feed = decrypt_token(auth_obj.feed_token) if auth_obj.feed_token else None
        except Exception:
            prev_feed = None
        token_changed = (
            prev_token != auth_token
            or prev_feed != feed_token
            or auth_obj.broker != broker
            or bool(auth_obj.is_revoked) != bool(revoke)
        )

    if auth_obj:
        auth_obj.auth = encrypted_token
        auth_obj.feed_token = encrypted_feed_token
        auth_obj.broker = broker
        auth_obj.user_id = user_id
        auth_obj.is_revoked = revoke
    else:
        auth_obj = Auth(
            name=name,
            auth=encrypted_token,
            feed_token=encrypted_feed_token,
            broker=broker,
            user_id=user_id,
            is_revoked=revoke,
        )
        db_session.add(auth_obj)
    db_session.commit()

    # CRITICAL: Clear ENTIRE auth_cache on token update to prevent stale token issues
    # This is necessary because get_auth_token_broker() uses a different cache key format
    # (sha256(api_key)_include_feed_token) than upsert_auth() uses (auth-{name}).
    # Without clearing all entries, old cached tokens from get_auth_token_broker()
    # would persist and cause 401 Unauthorized errors after re-login.
    # See GitHub issue #851 for details on this cache key mismatch bug.
    # This is cheap and always safe — do it unconditionally so reads stay correct.
    # After the commit, never before: clear() also bumps each cache's
    # generation, so a read that loaded the previous token before this commit
    # cannot store it again afterwards.
    auth_cache.clear()
    feed_token_cache.clear()
    broker_cache.clear()  # Also clear broker cache to ensure fresh data
    try:
        # The logged-in broker decides whether sessions outlive the rollover
        # (a crypto broker); read it afresh after a login or a logout.
        from utils.broker_keys import forget_logged_in_broker

        forget_logged_in_broker()
    except Exception:
        logger.debug("Could not refresh the logged-in broker", exc_info=True)
    logger.info(f"Cleared all auth caches after token update for user: {name}")

    # The two operations below TEAR DOWN the shared broker WebSocket feed (the
    # ZeroMQ publish reaches the out-of-process proxy's _handle_cache_invalidation,
    # which disconnects the adapter + pool; the in-process call does the same on the
    # single-process dev server). They are only correct when the token actually
    # changed (real login, daily token rollover, logout/revoke). On an unchanged
    # token (multi-device session resume) we must SKIP them so a second device
    # logging in does not interrupt the first device's live stream. See issue #1591
    # (and #1394/#765/#851 for why the teardown exists in the first place).
    auth_id = auth_obj.id
    if not (token_changed or revoke):
        logger.info(
            f"Broker token unchanged for {name} (multi-session resume) — "
            f"preserving live WebSocket feed, skipping pool teardown"
        )
        return auth_id, None
    return auth_id, lambda: _tear_down_feed(name, broker, revoke)


def _tear_down_feed(name, broker, revoke):
    """What a real token change does to the broker feeds, after the token is stored.

    Network and process work, so never run under the commit guard.
    """
    # Publish cache invalidation event via ZeroMQ for other processes
    # This notifies WebSocket proxy and other processes to clear their stale caches
    try:
        from database.cache_invalidation import publish_all_cache_invalidation
        publish_all_cache_invalidation(name)
        logger.debug(f"Published cache invalidation for user: {name}")
    except Exception as e:
        # Don't fail auth operation if cache invalidation fails
        # The database fallback in other processes will handle it
        logger.warning(f"Failed to publish cache invalidation for user {name}: {e}")

    # Same-process invalidation. Production runs `gunicorn -w 1` per CLAUDE.md
    # (single worker required for SocketIO state), so the WebSocket proxy's
    # _POOLED_ADAPTERS registry lives in this very process. The ZeroMQ
    # publish above is for hypothetical multi-process deployments; without
    # also discarding the in-process cache here, the next WS connect after
    # re-login reuses the pool that was initialised with the *old* token
    # and fails with "Adapter initialization failed: No authentication
    # token found" until the process is restarted. See issue #1394.
    try:
        from websocket_proxy.broker_factory import cleanup_pools_for_user
        cleanup_pools_for_user(name, broker_name=broker)
    except Exception as e:
        # Don't fail auth on cleanup error — the user can still trade via
        # HTTP endpoints; only the WS layer is affected.
        logger.warning(f"Failed to invalidate WS adapter pool for {name}/{broker}: {e}")

    # Order-update adapter lifecycle (services/order_update_service.py): the
    # always-on broker order-feed follows the same real-token-change gate as
    # the teardown above — restart with fresh credentials on change, stop on
    # revoke, and (by virtue of the early return above) stay untouched on a
    # multi-session resume.
    try:
        from services.order_update_service import (
            start_order_update_adapter,
            stop_order_update_adapter,
        )

        if revoke:
            stop_order_update_adapter(name)
        else:
            start_order_update_adapter(name, broker)
    except Exception as e:
        logger.warning(f"Order-update adapter lifecycle failed for {name}/{broker}: {e}")


def _pin_keys(broker):
    """Pin, for the reading context, the keys of the broker a token belongs to.

    utils.broker_keys.pin_keys_for: a request that reads a token sends that
    broker's keys with it, even while a switch is being stored.

    Returns:
        bool: False when the token's keys could not be pinned.
    """
    if not broker:
        return True
    try:
        from utils.broker_keys import pin_keys_for

        return pin_keys_for(broker)
    except Exception:
        logger.exception("Could not pin the keys of the token's broker")
        return False


def _unpin_keys():
    try:
        from utils.broker_keys import clear_pin

        clear_pin()
    except Exception:
        logger.exception("Could not drop a pin of broker keys")


def _context_generation():
    """What moves when the keys or the stored session change: (keys, session cache)."""
    try:
        from utils.broker_keys import publication_generation

        keys = publication_generation()
    except Exception:
        keys = None
    return keys, _generation(auth_cache)


#: How often a token read starts again when a login, a sign-out or a key
#: change lands between reading the token and pinning its keys.
_COHERENT_READ_ATTEMPTS = 3


def _read_coherently(read, refused):
    """A token read whose token and pinned keys belong to one configuration.

    ``read()`` returns (result, token, broker). The keys or the stored session
    moving between the read and the pin (a switch, a key change with its
    sign-out, a forget) means the token read may belong to a configuration
    that is no longer the process's: the read starts again and finds the new
    session, or none. A token whose keys cannot be pinned is not returned:
    a request is refused before it reaches the broker rather than sent with
    keys that are not its token's.

    Returns:
        The result, or ``refused``.
    """
    for _ in range(_COHERENT_READ_ATTEMPTS):
        before = _context_generation()
        result, token, broker = read()
        if not token:
            return result
        if _pin_keys(broker) and _context_generation() == before:
            return result
        _unpin_keys()
    logger.warning("Refused a broker session whose keys kept changing while it was read")
    return refused


def get_auth_token(name, bypass_cache: bool = False):
    """Get decrypted auth token.

    Args:
        name: The user identifier to get the token for
        bypass_cache: If True, skip the cache and query the database directly.
                     Use this when retrying after a 403 error to get fresh credentials.
                     See GitHub issue #765 for details.

    Returns:
        The decrypted auth token, or None if not found/revoked
    """
    # Handle None or empty name gracefully
    if not name:
        logger.debug("get_auth_token called with empty/None name, returning None")
        return None

    def read():
        record = _auth_record(name, bypass_cache)
        if record is None:
            return None, None, None
        token = decrypt_token(record.auth)
        return token, token, record.broker

    return _read_coherently(read, None)


def _auth_record(name, bypass_cache=False):
    """The stored session of ``name`` as a cached record, or None when there is none."""
    cache_key = f"auth-{name}"

    # Bypass cache if requested (e.g., after 403 error for fresh token)
    if bypass_cache:
        logger.debug(f"Bypassing cache for user: {name} (fresh token requested)")
        # Clear stale cache entry. pop, not del: a TTLCache entry can expire
        # between a membership test and the delete, and the KeyError would
        # escape as a spurious auth failure.
        auth_cache.pop(cache_key, None)
        generation = _generation(auth_cache)
        # Query database directly
        auth_obj = get_auth_token_dbquery(name)
        if isinstance(auth_obj, Auth) and not auth_obj.is_revoked:
            # Update cache with fresh data
            record = AuthRecord.from_row(auth_obj)
            _fill(auth_cache, cache_key, record, generation)
            return record
        return None

    # Normal cache-first lookup. One get, not a membership test followed by a
    # subscript: between the two the entry can expire or be evicted, and the
    # KeyError surfaces to the caller as an expired broker session.
    cached = auth_cache.get(cache_key, MISSING)
    if cached is not MISSING and cached is not None:
        record = _as_record(cached)
        if record is not None and not record.is_revoked:
            return record
        auth_cache.pop(cache_key, None)
        return None

    # Taken before the query: a re-login or revoke that commits while this
    # read is in flight clears the cache and moves the generation, and the
    # value read here is then returned but not stored.
    generation = _generation(auth_cache)
    auth_obj = get_auth_token_dbquery(name)
    if isinstance(auth_obj, Auth) and not auth_obj.is_revoked:
        record = AuthRecord.from_row(auth_obj)
        _fill(auth_cache, cache_key, record, generation)
        return record
    return None


def get_auth_token_fresh(name):
    """Get fresh auth token directly from database, bypassing cache.

    This is a convenience function for use after authentication failures (403 errors).
    It clears the local cache and fetches the latest token from the database.
    See GitHub issue #765 for details on when to use this.

    Args:
        name: The user identifier to get the token for

    Returns:
        The decrypted auth token, or None if not found/revoked
    """
    return get_auth_token(name, bypass_cache=True)


def get_auth_token_dbquery(name):
    """Fetch the auth token record directly from the database.

    Args:
        name: The user identifier (username) to look up.

    Returns:
        The ``Auth`` ORM instance if a valid record exists,
        otherwise ``None``.
    """
    try:
        # Handle None or empty name gracefully
        if not name:
            logger.debug("get_auth_token_dbquery called with empty/None name")
            return None

        auth_obj = Auth.query.filter_by(name=name).first()
        if auth_obj and not auth_obj.is_revoked:
            return auth_obj
        else:
            # Only log warning for actual usernames, not None/empty
            if name:
                logger.warning(f"No valid auth token found for name '{name}'.")
            return None
    except Exception as e:
        logger.exception(f"Error while querying the database for auth token: {e}")
        return None


def get_feed_token(name):
    """Get the feed token for a user.

    Args:
        name: The user identifier (username) to look up.

    Returns:
        The feed token string, or ``None`` if unavailable.
    """
    # Handle None or empty name gracefully
    if not name:
        logger.debug("get_feed_token called with empty/None name, returning None")
        return None

    cache_key = f"feed-{name}"
    cached = feed_token_cache.get(cache_key, MISSING)
    if cached is not MISSING and cached is not None:
        record = _as_record(cached)
        if record is not None and not record.is_revoked:
            return decrypt_token(record.feed_token) if record.feed_token else None
        feed_token_cache.pop(cache_key, None)
        return None

    generation = _generation(feed_token_cache)
    auth_obj = get_feed_token_dbquery(name)
    if isinstance(auth_obj, Auth) and not auth_obj.is_revoked:
        record = AuthRecord.from_row(auth_obj)
        _fill(feed_token_cache, cache_key, record, generation)
        return decrypt_token(record.feed_token) if record.feed_token else None
    return None


def get_feed_token_dbquery(name):
    """Fetch the feed token record directly from the database.

    Args:
        name: The user identifier (username) to look up.

    Returns:
        The ``Auth`` ORM instance if a valid record exists,
        otherwise ``None``.
    """
    try:
        # Handle None or empty name gracefully
        if not name:
            logger.debug("get_feed_token_dbquery called with empty/None name")
            return None

        auth_obj = Auth.query.filter_by(name=name).first()
        if auth_obj and not auth_obj.is_revoked:
            return auth_obj
        else:
            # Only log warning for actual usernames, not None/empty
            if name:
                logger.warning(f"No valid feed token found for name '{name}'.")
            return None
    except Exception as e:
        logger.exception(f"Error while querying the database for feed token: {e}")
        return None


def get_user_id(name):
    """Get the stored user_id (DefinEdge uid) for a user"""
    try:
        if not name:
            logger.debug("get_user_id called with empty/None name")
            return None

        auth_obj = Auth.query.filter_by(name=name).first()
        if auth_obj and not auth_obj.is_revoked:
            return auth_obj.user_id  # This should return "1272808" for DefinEdge
        else:
            if name:
                logger.warning(f"No valid user_id found for name '{name}'.")
            return None
    except Exception as e:
        logger.exception(f"Error while querying the database for user_id: {e}")
        return None


def invalidate_user_cache(user_id):
    """
    Invalidate all cached data for a user when their credentials change.
    Security: Ensures old API keys/tokens are not usable after regeneration.
    """
    # Clear all caches that might contain this user's data. Callers run this
    # after their commit; clear() also bumps each cache's generation, so a
    # read that loaded the old key, token or mode cannot store it again.
    auth_cache.clear()
    broker_cache.clear()
    feed_token_cache.clear()
    verified_api_key_cache.clear()
    invalid_api_key_cache.clear()
    order_mode_cache.clear()
    logger.info(f"Cleared all caches for user_id: {user_id}")


def invalidate_user_auth_cache(name) -> list[str]:
    """Drop one user's cached broker and feed tokens. Never raises.

    For logout, session expiry and a broker rejecting a stale token, which
    used to test membership and then delete. Another thread can remove the
    entry between those two steps (a login clearing the whole cache, a TTL
    lapse), and the KeyError then escaped before the token was revoked.
    Invalidation also stops a read that is already in flight from storing the
    token again.

    Args:
        name: The user whose ``auth-`` and ``feed-`` entries to drop.

    Returns:
        The names of the caches that held an entry, for logging.
    """
    cleared = []
    try:
        if _invalidate(auth_cache, f"auth-{name}"):
            cleared.append("auth_cache")
        if _invalidate(feed_token_cache, f"feed-{name}"):
            cleared.append("feed_token_cache")
    except Exception:
        logger.exception(f"Could not clear the cached broker session for {name}")
    return cleared


def upsert_api_key(user_id, api_key):
    """Store both hashed and encrypted API key"""
    # Hash with Argon2 for verification
    peppered_key = api_key + PEPPER
    hashed_key = ph.hash(peppered_key)

    # Encrypt for retrieval
    encrypted_key = encrypt_token(api_key)

    api_key_obj = ApiKeys.query.filter_by(user_id=user_id).first()
    if api_key_obj:
        api_key_obj.api_key_hash = hashed_key
        api_key_obj.api_key_encrypted = encrypted_key
    else:
        api_key_obj = ApiKeys(
            user_id=user_id, api_key_hash=hashed_key, api_key_encrypted=encrypted_key
        )
        db_session.add(api_key_obj)
    db_session.commit()

    # Security: Invalidate all caches when API key changes
    invalidate_user_cache(user_id)

    return api_key_obj.id


def get_api_key(user_id):
    """Check if user has an API key"""
    try:
        api_key_obj = ApiKeys.query.filter_by(user_id=user_id).first()
        return api_key_obj is not None
    except Exception as e:
        logger.exception(f"Error while querying the database for API key: {e}")
        return None


def get_api_key_for_tradingview(user_id):
    """Get decrypted API key for TradingView configuration"""
    try:
        api_key_obj = ApiKeys.query.filter_by(user_id=user_id).first()
        if api_key_obj and api_key_obj.api_key_encrypted:
            return decrypt_token(api_key_obj.api_key_encrypted)
        return None
    except Exception as e:
        logger.exception(f"Error while querying the database for API key: {e}")
        return None


def get_first_available_api_key():
    """
    Get the first available decrypted API key from the database.
    Used for background services that don't have session context.

    Only returns keys for users who have an active (non-revoked) auth session
    with a broker configured. This prevents returning orphaned API keys for
    deleted users or users with revoked sessions.
    """
    try:
        # Join api_keys with auth to only return keys for users with active sessions
        api_keys = ApiKeys.query.all()
        for api_key_obj in api_keys:
            if not api_key_obj.api_key_encrypted:
                continue
            # Check if this user has an active auth session with a broker
            auth_obj = Auth.query.filter_by(name=api_key_obj.user_id).first()
            if auth_obj and not auth_obj.is_revoked and auth_obj.broker:
                return decrypt_token(api_key_obj.api_key_encrypted)
        return None
    except Exception as e:
        logger.exception(f"Error getting first available API key: {e}")
        return None


def verify_api_key(provided_api_key):
    """
    Verify an API key using Argon2 with intelligent caching.

    Security measures:
    - Only caches user_id (not sensitive data)
    - Uses SHA256 hash as cache key (never stores plaintext)
    - Invalid keys cached for 5min (prevents brute force)
    - Valid keys cached for 1hr (balances security vs performance)
    - Cache invalidated on key regeneration
    """
    import hashlib

    from flask import has_request_context, request

    from database.traffic_db import InvalidAPIKeyTracker
    from utils.ip_helper import get_real_ip

    # Generate secure cache key (SHA256 hash of API key)
    # Security: Never store plaintext API key in cache
    cache_key = hashlib.sha256(provided_api_key.encode()).hexdigest()

    # Step 1: Check invalid cache first (fast rejection of known bad keys).
    # One get each, never a membership test then a subscript: the entry can
    # go between the two and the KeyError would reach the order path.
    if invalid_api_key_cache.get(cache_key, MISSING) is not MISSING:
        logger.debug("API key rejected from invalid cache")
        return None

    # Step 2: Check valid cache (fast path for legitimate requests)
    cached_user_id = verified_api_key_cache.get(cache_key, MISSING)
    if cached_user_id is not MISSING:
        logger.debug(f"API key verified from cache for user_id: {cached_user_id}")
        return cached_user_id

    # Step 3: Cache miss - perform expensive Argon2 verification. The
    # generations are taken before the query, so a key regenerated while this
    # runs is not cached as valid (or invalid) from the superseded hashes.
    verified_generation = _generation(verified_api_key_cache)
    invalid_generation = _generation(invalid_api_key_cache)
    peppered_key = provided_api_key + PEPPER
    try:
        # Query all API keys
        api_keys = ApiKeys.query.all()

        # Try to verify against each stored hash
        for api_key_obj in api_keys:
            try:
                ph.verify(api_key_obj.api_key_hash, peppered_key)
                # Valid key found - cache it
                _fill(verified_api_key_cache, cache_key, api_key_obj.user_id, verified_generation)
                logger.debug(f"API key verified and cached for user_id: {api_key_obj.user_id}")
                return api_key_obj.user_id
            except VerifyMismatchError:
                continue

        # If we reach here, the API key is invalid
        # Cache the invalid result to prevent repeated expensive verifications
        _fill(invalid_api_key_cache, cache_key, True, invalid_generation)
        logger.debug("Invalid API key cached")

        # Track the invalid attempt
        try:
            # Check if we're in a request context
            if has_request_context():
                client_ip = get_real_ip()
            else:
                client_ip = "127.0.0.1"

            # Hash the API key for tracking (don't store plaintext)
            api_key_hash = hashlib.sha256(provided_api_key.encode()).hexdigest()[:16]

            # Track the invalid API key attempt
            InvalidAPIKeyTracker.track_invalid_api_key(client_ip, api_key_hash)

        except Exception as track_error:
            logger.warning(f"Could not track invalid API key attempt: {track_error}")

        return None
    except Exception as e:
        logger.exception(f"Error verifying API key: {e}")
        return None


def get_username_by_apikey(provided_api_key):
    """Get username for a given API key"""
    return verify_api_key(provided_api_key)


def get_broker_name(provided_api_key):
    """Get only the broker name for a valid API key with caching"""
    # Check if broker name is in cache
    cached_broker = broker_cache.get(provided_api_key, MISSING)
    if cached_broker is not MISSING:
        return cached_broker

    # Not in cache, need to look it up
    generation = _generation(broker_cache)
    user_id = verify_api_key(provided_api_key)

    if user_id:
        try:
            auth_obj = Auth.query.filter_by(name=user_id).first()
            if auth_obj and not auth_obj.is_revoked:
                # Cache the broker name
                _fill(broker_cache, provided_api_key, auth_obj.broker, generation)
                return auth_obj.broker
            else:
                logger.warning(f"No valid broker found for user_id '{user_id}'.")
                return None
        except Exception as e:
            logger.exception(f"Error while querying the database for broker name: {e}")
            return None
    return None


def get_auth_token_broker(provided_api_key, include_feed_token=False):
    """Auth token, feed token (optional) and broker for an API key, its broker's keys pinned.

    utils.broker_keys.pin_keys_for and _read_coherently: the token returned
    and the keys the request sends with it belong to one configuration.
    """
    refused = (None, None, None) if include_feed_token else (None, None)

    def read():
        result = _auth_token_broker(provided_api_key, include_feed_token)
        return result, result[0], result[-1]

    return _read_coherently(read, refused)


def _auth_token_broker(provided_api_key, include_feed_token=False):
    """
    Get auth token, feed token (optional) and broker for a valid API key with caching.

    Security measures:
    - Always checks is_revoked status (even for cached data)
    - Cache cleared on credential changes
    - TTL based on session expiry time
    """
    import hashlib

    # Generate cache key
    cache_key = f"{hashlib.sha256(provided_api_key.encode()).hexdigest()}_{include_feed_token}"

    # Check cache first (but still verify revocation status).
    #
    # One get rather than a membership test followed by a subscript. auth_cache
    # is a TTLCache with a maxsize, and the entry can go between the two: the
    # TTL can lapse, an LRU eviction can drop it (two different key schemes
    # share this cache), or another path can delete it. The KeyError then
    # escaped this function and reached /quotes and /multiquotes, where it was
    # reported to the user as "Broker Session Expired" on a session that was
    # perfectly valid.
    cached_result = auth_cache.get(cache_key)
    if cached_result is not None:
        # Security: Still check if auth is revoked even with cached data
        user_id = verify_api_key(provided_api_key)
        if user_id:
            try:
                auth_obj = Auth.query.filter_by(name=user_id).first()
                if auth_obj and auth_obj.is_revoked:
                    # Token was revoked, remove from cache
                    auth_cache.pop(cache_key, None)
                    logger.warning(f"Cached auth token was revoked for user_id '{user_id}'.")
                    return (None, None, None) if include_feed_token else (None, None)
                # Not revoked, return cached result
                logger.debug(f"Auth token retrieved from cache for user_id: {user_id}")
                return cached_result
            except Exception as e:
                logger.exception(f"Error checking revocation status: {e}")
                # On error, don't use cache. pop, not del: this is the recovery
                # path, and a del here raised a SECOND KeyError that nothing
                # caught, turning a harmless cache miss into a failed request.
                auth_cache.pop(cache_key, None)

    # Cache miss or revocation check failed - fetch from database. The
    # generation is taken first, so a re-login that commits while this read is
    # in flight stops its (superseded) token from being cached.
    generation = _generation(auth_cache)
    user_id = verify_api_key(provided_api_key)

    if user_id:
        try:
            auth_obj = Auth.query.filter_by(name=user_id).first()
            if auth_obj and not auth_obj.is_revoked:
                decrypted_token = decrypt_token(auth_obj.auth)
                if include_feed_token:
                    decrypted_feed_token = (
                        decrypt_token(auth_obj.feed_token) if auth_obj.feed_token else None
                    )
                    result = (decrypted_token, decrypted_feed_token, auth_obj.broker)
                else:
                    result = (decrypted_token, auth_obj.broker)

                # Cache the result
                _fill(auth_cache, cache_key, result, generation)
                logger.debug(f"Auth token cached for user_id: {user_id}")
                return result
            else:
                # Cache the negative result to prevent repeated DB queries and log spam
                # (e.g., orphaned users with revoked sessions polled by background services)
                negative_result = (None, None, None) if include_feed_token else (None, None)
                _fill(auth_cache, cache_key, negative_result, generation)
                logger.warning(f"No valid auth token or broker found for user_id '{user_id}'. Cached negative result.")
                return negative_result
        except Exception as e:
            logger.exception(f"Error while querying the database for auth token and broker: {e}")
            return (None, None, None) if include_feed_token else (None, None)
    else:
        return (None, None, None) if include_feed_token else (None, None)


def get_session_identity(provided_api_key):
    """(token, broker, account) of the API key's stored session, from one read of its row.

    For a call held to a known broker account (the strategy module): the
    token, its broker and the account the login recorded come from the same
    row, read afresh, so a login landing between separate reads cannot pair
    one account's token with another account's id. ``account`` is None when
    the broker's login records none.

    Returns:
        tuple: (None, None, None) when there is no usable session.
    """
    username = verify_api_key(provided_api_key)
    if not username:
        return None, None, None

    def read():
        try:
            row = Auth.query.populate_existing().filter_by(name=username).first()
            if row is None or row.is_revoked or not row.auth or not row.broker:
                return (None, None, None), None, None
            token = decrypt_token(row.auth)
            account = str(row.user_id).strip() if row.user_id else None
        except Exception:
            logger.exception("Could not read the stored broker session")
            return (None, None, None), None, None
        if not token:
            return (None, None, None), None, None
        return (token, row.broker, account or None), token, row.broker

    return _read_coherently(read, (None, None, None))


def get_order_mode(user_id):
    """
    Get the order mode for a user (auto or semi_auto)

    Args:
        user_id: User identifier

    Returns:
        str: 'auto' or 'semi_auto', defaults to 'auto' if not set
    """
    cached_mode = order_mode_cache.get(user_id)
    if cached_mode is not None:
        return cached_mode

    # Taken before the query. update_order_mode commits and then clears this
    # cache; a read that loaded 'auto' just before an operator switched to
    # semi_auto must not store it back, or orders would skip the Action
    # Center until the TTL ran out.
    generation = _generation(order_mode_cache)
    try:
        api_key_obj = ApiKeys.query.filter_by(user_id=user_id).first()
        mode = api_key_obj.order_mode if api_key_obj and api_key_obj.order_mode else "auto"
        _fill(order_mode_cache, user_id, mode, generation)
        return mode
    except Exception as e:
        logger.exception(f"Error getting order mode for user {user_id}: {e}")
        return "auto"  # Default to auto on error


def update_order_mode(user_id, mode):
    """
    Update the order mode for a user

    Args:
        user_id: User identifier
        mode: 'auto' or 'semi_auto'

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        if mode not in ["auto", "semi_auto"]:
            logger.error(f"Invalid order mode: {mode}")
            return False

        api_key_obj = ApiKeys.query.filter_by(user_id=user_id).first()
        if api_key_obj:
            api_key_obj.order_mode = mode
            db_session.commit()

            # Clear caches when mode changes
            invalidate_user_cache(user_id)

            logger.info(f"Order mode updated to '{mode}' for user: {user_id}")
            return True
        else:
            logger.error(f"No API key found for user: {user_id}")
            return False
    except Exception as e:
        logger.exception(f"Error updating order mode: {e}")
        db_session.rollback()
        return False


# ============================================================
# Samco 2FA Helper Functions
# Uses dedicated columns on the Auth table:
#   secret_api_key, primary_ip, secondary_ip, ip_updated_at
# ============================================================


def _get_samco_auth(user_id):
    """Get the Auth record for a Samco user by name."""
    try:
        return Auth.query.filter_by(broker="samco", name=user_id).first()
    except Exception as e:
        logger.error(f"Error getting samco auth for {user_id}: {e}")
        return None


def samco_save_secret_key(user_id, secret_api_key):
    """Save or update the secret API key for a Samco user.
    Creates a placeholder auth record if one doesn't exist yet (pre-login setup).

    The secret_api_key is encrypted at rest with the auth_db Fernet (PBKDF2
    over API_KEY_PEPPER). Pre-migration rows containing plaintext are
    transparently handled by safe_decrypt_token on read.
    """
    try:
        record = _get_samco_auth(user_id)
        if not record:
            record = Auth(
                name=user_id,
                auth="pending",
                broker="samco",
                is_revoked=True,
            )
            db_session.add(record)
            logger.info(f"Created placeholder auth record for samco user {user_id}")
        record.secret_api_key = encrypt_token(secret_api_key) if secret_api_key else None
        db_session.commit()
        return True
    except Exception as e:
        db_session.rollback()
        logger.error(f"Error saving secret key for {user_id}: {e}")
        return False


def samco_get_ip_status(user_id):
    """Get IP registration status and whether editing is allowed."""
    from datetime import datetime, timedelta

    record = _get_samco_auth(user_id)
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


def samco_save_ip_info(user_id, primary_ip, secondary_ip=None, ip_updated_at=None):
    """Save IP registration info for a Samco user."""
    from datetime import datetime

    try:
        record = _get_samco_auth(user_id)
        if record:
            record.primary_ip = primary_ip
            record.secondary_ip = secondary_ip
            record.ip_updated_at = ip_updated_at or datetime.utcnow()
            db_session.commit()
            return True
        else:
            logger.error(f"No auth record found for samco user {user_id}")
            return False
    except Exception as e:
        db_session.rollback()
        logger.error(f"Error saving IP info for {user_id}: {e}")
        return False


def samco_has_secret_key(user_id):
    """Check if a Samco user has a secret API key stored."""
    record = _get_samco_auth(user_id)
    return record is not None and record.secret_api_key is not None


def samco_get_secret_key(user_id):
    """Get the stored secret API key for a Samco user (decrypted).

    Falls back to the raw column value if Fernet decryption fails — that's
    a pre-migration plaintext row, which keeps working until the operator
    runs upgrade/rotate_pepper.py.
    """
    record = _get_samco_auth(user_id)
    if record and record.secret_api_key:
        return safe_decrypt_token(record.secret_api_key)
    return None


def samco_has_registered_ip(user_id):
    """Check if a Samco user has registered IPs."""
    record = _get_samco_auth(user_id)
    return record is not None and record.primary_ip is not None
