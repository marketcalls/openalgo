"""OAuth 2.1 persistence for the Remote MCP feature.

Three tables, all in db/openalgo.db. Hashing pipeline is identical to the
existing API key flow in database/auth_db.py — Argon2id with the same
API_KEY_PEPPER. We do NOT introduce a new secret material here.

See docs/prd/remote-mcp.md for the schema rationale and threat model.
"""

import os
from datetime import datetime, timedelta
from typing import List, Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool

from utils.logging import get_logger

logger = get_logger(__name__)

# Reuse the same DATABASE_URL + pepper as auth_db so the OAuth tables live
# alongside users in db/openalgo.db. No new secret material is introduced.
DATABASE_URL = os.getenv("DATABASE_URL")
PEPPER = os.getenv("API_KEY_PEPPER")

if not PEPPER or len(PEPPER) < 32:
    # Defer the failure to runtime — auth_db will already have raised on
    # import if PEPPER is missing. Keeping the OAuth module importable
    # (and gated by MCP_HTTP_ENABLED at the blueprint level) means tests
    # and tooling don't trip over a missing pepper unrelated to MCP.
    PEPPER = PEPPER or ""

# Argon2 hasher — same params as auth_db (library defaults at the time).
ph = PasswordHasher()

if DATABASE_URL and "sqlite" in DATABASE_URL:
    engine = create_engine(
        DATABASE_URL, poolclass=NullPool, connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(DATABASE_URL, pool_size=20, max_overflow=40, pool_timeout=10)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class OAuthClient(Base):
    """A DCR-registered OAuth client.

    Created by ``POST /oauth/register``. When MCP_OAUTH_REQUIRE_APPROVAL=True
    (default), ``approved`` starts False and the admin must explicitly
    approve before the client can complete an OAuth flow.

    The ``client_secret`` is generated server-side and returned exactly
    once at registration. We persist only its Argon2 hash with PEPPER.
    """

    __tablename__ = "oauth_clients"

    id = Column(Integer, primary_key=True)
    client_id = Column(String(64), unique=True, nullable=False, index=True)
    client_name = Column(String(255), nullable=False)

    # JSON-encoded list of allowed redirect URIs. Exact-match comparison only.
    redirect_uris = Column(Text, nullable=False)

    # Argon2(client_secret + PEPPER). NULL = public client (no secret, PKCE only).
    client_secret_hash = Column(Text, nullable=True)

    # Comma-separated list of scopes the client requested at DCR.
    # The /authorize step further constrains to whatever the user approves.
    scopes_requested = Column(String(255), default="")

    approved = Column(Boolean, default=False, nullable=False)
    approved_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = Column(DateTime, nullable=True)

    __table_args__ = (Index("idx_oauth_client_approved", "approved", "revoked_at"),)


class OAuthRefreshToken(Base):
    """Single-use refresh token, rotated on every use.

    Replay detection: if a token whose ``revoked_at`` is set is presented,
    every token in the same family (linked through ``parent_id``) is
    revoked immediately — RFC 6749 §10.4. Forces an attacker who stole
    one refresh to lose the entire chain the moment the legitimate
    client refreshes again.
    """

    __tablename__ = "oauth_refresh_tokens"

    id = Column(Integer, primary_key=True)
    client_id = Column(String(64), nullable=False, index=True)

    # Argon2(token_value + PEPPER). The plaintext token is opaque random,
    # returned to the client exactly once.
    token_hash = Column(Text, nullable=False, unique=True)

    scopes = Column(String(255), nullable=False, default="")

    # Family head — every refresh issued from the same authorization code
    # shares the same family_id. On reuse-detection we revoke by family_id.
    family_id = Column(String(64), nullable=False, index=True)

    # Immediate predecessor; NULL for the very first refresh in a family.
    parent_id = Column(Integer, ForeignKey("oauth_refresh_tokens.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True, index=True)
    revoke_reason = Column(String(64), nullable=True)


class OAuthSigningKey(Base):
    """JWKS state. Private key lives on disk under keys/."""

    __tablename__ = "oauth_signing_keys"

    id = Column(Integer, primary_key=True)
    kid = Column(String(64), unique=True, nullable=False, index=True)
    algorithm = Column(String(16), default="RS256", nullable=False)

    # JSON-encoded JWK with public key only.
    public_jwk = Column(Text, nullable=False)

    # Filesystem path to the private key (chmod 600).
    private_path = Column(String(512), nullable=False)

    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    rotated_at = Column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# Hashing helpers
# ---------------------------------------------------------------------------


def hash_secret(secret: str) -> str:
    """Argon2(secret + PEPPER). Used for both client secrets and refresh tokens."""
    return ph.hash(secret + PEPPER)


def verify_secret(secret: str, hashed: str) -> bool:
    """Constant-time-ish verification via Argon2."""
    if not secret or not hashed:
        return False
    try:
        ph.verify(hashed, secret + PEPPER)
        return True
    except VerifyMismatchError:
        return False
    except Exception as e:
        logger.exception(f"Unexpected error verifying OAuth secret: {e}")
        return False


# ---------------------------------------------------------------------------
# DB initialization
# ---------------------------------------------------------------------------


def init_db() -> None:
    """Create OAuth tables. Idempotent — safe to call repeatedly."""
    logger.info("Initializing OAuth tables in db/openalgo.db ...")
    Base.metadata.create_all(bind=engine)
    logger.info("OAuth tables ready.")


# ---------------------------------------------------------------------------
# Token-family revocation (RFC 6749 §10.4 reuse detection)
# ---------------------------------------------------------------------------


def revoke_family(family_id: str, reason: str) -> int:
    """Revoke every refresh token in the given family. Returns count revoked."""
    now = datetime.utcnow()
    rows = (
        OAuthRefreshToken.query.filter_by(family_id=family_id, revoked_at=None)
        .update({"revoked_at": now, "revoke_reason": reason})
    )
    db_session.commit()
    if rows:
        logger.warning(f"Revoked {rows} refresh tokens in family={family_id} reason={reason}")
    return rows


def revoke_client(client_id: str, reason: str) -> int:
    """Revoke every refresh token for a client AND mark the client revoked."""
    now = datetime.utcnow()
    rows = (
        OAuthRefreshToken.query.filter_by(client_id=client_id, revoked_at=None)
        .update({"revoked_at": now, "revoke_reason": reason})
    )
    OAuthClient.query.filter_by(client_id=client_id).update({"revoked_at": now})
    db_session.commit()
    logger.warning(f"Revoked client_id={client_id} ({rows} tokens) reason={reason}")
    return rows


def revoke_all_tokens(reason: str) -> int:
    """Kill switch. Revokes every refresh token in the system."""
    now = datetime.utcnow()
    rows = OAuthRefreshToken.query.filter_by(revoked_at=None).update(
        {"revoked_at": now, "revoke_reason": reason}
    )
    db_session.commit()
    logger.warning(f"KILL SWITCH: revoked {rows} refresh tokens reason={reason}")
    return rows


# ---------------------------------------------------------------------------
# Convenience accessors
# ---------------------------------------------------------------------------


def get_client(client_id: str) -> OAuthClient | None:
    return OAuthClient.query.filter_by(client_id=client_id).first()


def list_pending_clients() -> list[OAuthClient]:
    return (
        OAuthClient.query.filter_by(approved=False, revoked_at=None)
        .order_by(OAuthClient.created_at.desc())
        .all()
    )


def list_approved_clients() -> list[OAuthClient]:
    return (
        OAuthClient.query.filter_by(approved=True, revoked_at=None)
        .order_by(OAuthClient.created_at.desc())
        .all()
    )


def get_active_signing_key() -> OAuthSigningKey | None:
    return OAuthSigningKey.query.filter_by(is_active=True).first()
