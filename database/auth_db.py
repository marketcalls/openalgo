# database/auth_db.py

import base64
import os

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cachetools import TTLCache
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


# Setup Fernet encryption for auth tokens
def get_encryption_key():
    """Generate a Fernet key from the pepper"""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"openalgo_static_salt",
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


# Define auth token cache with TTL until session expiry to minimize DB hits
auth_cache = TTLCache(maxsize=1024, ttl=get_session_based_cache_ttl())
# Define feed token cache with same TTL
feed_token_cache = TTLCache(maxsize=1024, ttl=get_session_based_cache_ttl())
# Define a cache for broker names with a 5-minute TTL (longer since broker rarely changes)
broker_cache = TTLCache(maxsize=1024, ttl=3000)
# Define a cache for verified API keys with 24-hour TTL
# Security: Only caches user_id (not sensitive), invalidated on key regeneration
# Long TTL is safe because cache is invalidated when keys are regenerated
verified_api_key_cache = TTLCache(maxsize=1024, ttl=36000)  # 10 hours
# Define a cache for invalid API keys with shorter 5-minute TTL (prevent cache poisoning)
invalid_api_key_cache = TTLCache(maxsize=512, ttl=300)  # 5 minutes

# Conditionally create engine based on DB type
if DATABASE_URL and "sqlite" in DATABASE_URL:
    # SQLite: Use NullPool to prevent connection pool exhaustion
    # NullPool creates a new connection for each request and closes it when done
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

    # Performance indexes for frequently queried columns
    __table_args__ = (
        Index("idx_auth_broker", "broker"),  # Speeds up get_broker_name() queries
        Index("idx_auth_user_id", "user_id"),  # Speeds up get_user_id() lookups
        Index("idx_auth_is_revoked", "is_revoked"),  # Speeds up token validity checks
    )


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


def init_db():
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Auth DB", logger)


def encrypt_token(token):
    """Encrypt auth token"""
    if not token:
        return ""
    return fernet.encrypt(token.encode()).decode()


def decrypt_token(encrypted_token):
    """Decrypt auth token"""
    if not encrypted_token:
        return ""
    try:
        return fernet.decrypt(encrypted_token.encode()).decode()
    except Exception as e:
        logger.exception(f"Error decrypting token: {e}")
        return None


def upsert_auth(name, auth_token, broker, feed_token=None, user_id=None, revoke=False):
    """Store encrypted auth token and feed token if provided.

    Also publishes cache invalidation events via ZeroMQ for multi-process deployments.
    This ensures WebSocket proxy and other processes clear their stale cached tokens.
    See GitHub issue #765 for details on the cross-process cache synchronization problem.
    """
    encrypted_token = encrypt_token(auth_token)
    encrypted_feed_token = encrypt_token(feed_token) if feed_token else None

    auth_obj = Auth.query.filter_by(name=name).first()
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
    auth_cache.clear()
    feed_token_cache.clear()
    broker_cache.clear()  # Also clear broker cache to ensure fresh data
    logger.info(f"Cleared all auth caches after token update for user: {name}")

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

    return auth_obj.id


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

    cache_key = f"auth-{name}"

    # Bypass cache if requested (e.g., after 403 error for fresh token)
    if bypass_cache:
        logger.debug(f"Bypassing cache for user: {name} (fresh token requested)")
        # Clear stale cache entry
        if cache_key in auth_cache:
            del auth_cache[cache_key]
        # Query database directly
        auth_obj = get_auth_token_dbquery(name)
        if isinstance(auth_obj, Auth) and not auth_obj.is_revoked:
            # Update cache with fresh data
            auth_cache[cache_key] = auth_obj
            return decrypt_token(auth_obj.auth)
        return None

    # Normal cache-first lookup
    if cache_key in auth_cache:
        auth_obj = auth_cache[cache_key]
        if isinstance(auth_obj, Auth) and not auth_obj.is_revoked:
            return decrypt_token(auth_obj.auth)
        else:
            del auth_cache[cache_key]
            return None
    else:
        auth_obj = get_auth_token_dbquery(name)
        if isinstance(auth_obj, Auth) and not auth_obj.is_revoked:
            auth_cache[cache_key] = auth_obj
            return decrypt_token(auth_obj.auth)
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
    """Get decrypted feed token"""
    # Handle None or empty name gracefully
    if not name:
        logger.debug("get_feed_token called with empty/None name, returning None")
        return None

    cache_key = f"feed-{name}"
    if cache_key in feed_token_cache:
        auth_obj = feed_token_cache[cache_key]
        if isinstance(auth_obj, Auth) and not auth_obj.is_revoked:
            return decrypt_token(auth_obj.feed_token) if auth_obj.feed_token else None
        else:
            del feed_token_cache[cache_key]
            return None
    else:
        auth_obj = get_feed_token_dbquery(name)
        if isinstance(auth_obj, Auth) and not auth_obj.is_revoked:
            feed_token_cache[cache_key] = auth_obj
            return decrypt_token(auth_obj.feed_token) if auth_obj.feed_token else None
        return None


def get_feed_token_dbquery(name):
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
    # Clear all caches that might contain this user's data
    auth_cache.clear()
    broker_cache.clear()
    feed_token_cache.clear()
    verified_api_key_cache.clear()
    invalid_api_key_cache.clear()
    logger.info(f"Cleared all caches for user_id: {user_id}")


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
    """
    try:
        api_key_obj = ApiKeys.query.first()
        if api_key_obj and api_key_obj.api_key_encrypted:
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

    # Step 1: Check invalid cache first (fast rejection of known bad keys)
    if cache_key in invalid_api_key_cache:
        logger.debug("API key rejected from invalid cache")
        return None

    # Step 2: Check valid cache (fast path for legitimate requests)
    if cache_key in verified_api_key_cache:
        user_id = verified_api_key_cache[cache_key]
        logger.debug(f"API key verified from cache for user_id: {user_id}")
        return user_id

    # Step 3: Cache miss - perform expensive Argon2 verification
    peppered_key = provided_api_key + PEPPER
    try:
        # Query all API keys
        api_keys = ApiKeys.query.all()

        # Try to verify against each stored hash
        for api_key_obj in api_keys:
            try:
                ph.verify(api_key_obj.api_key_hash, peppered_key)
                # Valid key found - cache it
                verified_api_key_cache[cache_key] = api_key_obj.user_id
                logger.debug(f"API key verified and cached for user_id: {api_key_obj.user_id}")
                return api_key_obj.user_id
            except VerifyMismatchError:
                continue

        # If we reach here, the API key is invalid
        # Cache the invalid result to prevent repeated expensive verifications
        invalid_api_key_cache[cache_key] = True
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
    if provided_api_key in broker_cache:
        return broker_cache[provided_api_key]

    # Not in cache, need to look it up
    user_id = verify_api_key(provided_api_key)

    if user_id:
        try:
            auth_obj = Auth.query.filter_by(name=user_id).first()
            if auth_obj and not auth_obj.is_revoked:
                # Cache the broker name
                broker_cache[provided_api_key] = auth_obj.broker
                return auth_obj.broker
            else:
                logger.warning(f"No valid broker found for user_id '{user_id}'.")
                return None
        except Exception as e:
            logger.exception(f"Error while querying the database for broker name: {e}")
            return None
    return None


def get_auth_token_broker(provided_api_key, include_feed_token=False):
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

    # Check cache first (but still verify revocation status)
    if cache_key in auth_cache:
        cached_result = auth_cache[cache_key]
        # Security: Still check if auth is revoked even with cached data
        user_id = verify_api_key(provided_api_key)
        if user_id:
            try:
                auth_obj = Auth.query.filter_by(name=user_id).first()
                if auth_obj and auth_obj.is_revoked:
                    # Token was revoked, remove from cache
                    del auth_cache[cache_key]
                    logger.warning(f"Cached auth token was revoked for user_id '{user_id}'.")
                    return (None, None, None) if include_feed_token else (None, None)
                # Not revoked, return cached result
                logger.debug(f"Auth token retrieved from cache for user_id: {user_id}")
                return cached_result
            except Exception as e:
                logger.exception(f"Error checking revocation status: {e}")
                # On error, don't use cache
                del auth_cache[cache_key]

    # Cache miss or revocation check failed - fetch from database
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
                auth_cache[cache_key] = result
                logger.debug(f"Auth token cached for user_id: {user_id}")
                return result
            else:
                logger.warning(f"No valid auth token or broker found for user_id '{user_id}'.")
                return (None, None, None) if include_feed_token else (None, None)
        except Exception as e:
            logger.exception(f"Error while querying the database for auth token and broker: {e}")
            return (None, None, None) if include_feed_token else (None, None)
    else:
        return (None, None, None) if include_feed_token else (None, None)


def get_order_mode(user_id):
    """
    Get the order mode for a user (auto or semi_auto)

    Args:
        user_id: User identifier

    Returns:
        str: 'auto' or 'semi_auto', defaults to 'auto' if not set
    """
    try:
        api_key_obj = ApiKeys.query.filter_by(user_id=user_id).first()
        if api_key_obj and api_key_obj.order_mode:
            return api_key_obj.order_mode
        return "auto"  # Default to auto mode
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
