"""JWT issuance + refresh-token rotation for the Remote MCP OAuth server.

Two distinct credentials live here:

* **Access token** — RS256-signed JWT, 15-minute TTL by default. Stateless
  verification: the resource server (the /mcp transport) checks the
  signature against the JWKS, validates ``exp``, ``iss``, ``aud``, and the
  ``scope`` claim. No DB lookup per request.

* **Refresh token** — opaque random string, 30-day TTL by default. Hashed
  with the existing API_KEY_PEPPER and persisted in
  ``oauth_refresh_tokens``. **Single-use** — every successful refresh
  issues a new token in the same family and marks the old one revoked.
  If a token whose ``revoked_at`` is set is presented (reuse detection),
  the entire family is revoked immediately per RFC 6749 §10.4.

The signing key comes from :mod:`utils.oauth_keys`; the active row's
``kid`` is embedded in every JWT header so verifiers can look it up in
JWKS even after rotation.
"""

from __future__ import annotations

import os
import secrets
import time
from datetime import datetime, timedelta
from typing import Iterable, NamedTuple

from authlib.jose import JsonWebKey, jwt
from authlib.jose.errors import JoseError

from database.oauth_db import (
    OAuthRefreshToken,
    db_session,
    hash_secret,
    revoke_family,
    verify_secret,
)
from utils.logging import get_logger
from utils.oauth_keys import ensure_signing_key, load_private_pem

logger = get_logger(__name__)


# Configuration — bounded so an environment misconfiguration can't extend
# token lifetimes beyond what the threat model assumes.
ACCESS_TTL_DEFAULT = 900  # 15 min
ACCESS_TTL_MAX = 3600  # hard ceiling: 1 hour
REFRESH_TTL_DEFAULT = 2_592_000  # 30 days
REFRESH_TTL_MAX = 31 * 24 * 3600  # hard ceiling: 31 days


def _access_ttl() -> int:
    try:
        v = int(os.getenv("MCP_OAUTH_ACCESS_TTL", str(ACCESS_TTL_DEFAULT)))
    except ValueError:
        v = ACCESS_TTL_DEFAULT
    return max(60, min(v, ACCESS_TTL_MAX))


def _refresh_ttl() -> int:
    try:
        v = int(os.getenv("MCP_OAUTH_REFRESH_TTL", str(REFRESH_TTL_DEFAULT)))
    except ValueError:
        v = REFRESH_TTL_DEFAULT
    return max(3600, min(v, REFRESH_TTL_MAX))


def _issuer() -> str:
    return (os.getenv("MCP_PUBLIC_URL") or "").rstrip("/")


def _audience() -> str:
    base = _issuer()
    return f"{base}/mcp" if base else "mcp"


# ---------------------------------------------------------------------------
# Access token (JWT)
# ---------------------------------------------------------------------------


def issue_access_token(
    *,
    user_id: int,
    client_id: str,
    scope: str,
) -> tuple[str, int, str]:
    """Mint an RS256 JWT access token.

    Returns ``(token_str, expires_in_seconds, jti)``. ``jti`` is also
    embedded in the JWT and is what the audit log keys on for every
    tool call later.
    """
    key = ensure_signing_key()
    private_pem = load_private_pem(key)
    now = int(time.time())
    ttl = _access_ttl()
    jti = secrets.token_urlsafe(16)

    header = {"alg": "RS256", "kid": key.kid, "typ": "JWT"}
    payload = {
        "iss": _issuer(),
        "sub": str(user_id),
        "aud": _audience(),
        "iat": now,
        "exp": now + ttl,
        "jti": jti,
        "client_id": client_id,
        "scope": scope,
    }
    token_bytes = jwt.encode(header, payload, private_pem)
    token_str = token_bytes.decode("ascii") if isinstance(token_bytes, bytes) else token_bytes
    return token_str, ttl, jti


# ---------------------------------------------------------------------------
# Refresh token (opaque + DB-persisted)
# ---------------------------------------------------------------------------


class IssuedRefreshToken(NamedTuple):
    plaintext: str
    row: OAuthRefreshToken
    expires_in: int


def _new_refresh_value() -> str:
    """32 url-safe bytes ≈ 43 chars. Plenty of entropy."""
    return secrets.token_urlsafe(32)


def issue_initial_refresh_token(
    *,
    client_id: str,
    scope: str,
) -> IssuedRefreshToken:
    """Mint the first refresh token in a brand-new family.

    Called from ``/oauth/token`` on a successful authorization-code
    exchange. The family is anchored to a fresh, opaque ``family_id``
    so subsequent rotations can find their siblings cheaply.
    """
    plaintext = _new_refresh_value()
    family_id = secrets.token_urlsafe(16)
    ttl = _refresh_ttl()
    now = datetime.utcnow()
    row = OAuthRefreshToken(
        client_id=client_id,
        token_hash=hash_secret(plaintext),
        scopes=scope,
        family_id=family_id,
        parent_id=None,
        created_at=now,
        expires_at=now + timedelta(seconds=ttl),
    )
    db_session.add(row)
    db_session.commit()
    return IssuedRefreshToken(plaintext=plaintext, row=row, expires_in=ttl)


def rotate_refresh_token(
    *,
    presented_plaintext: str,
    client_id: str,
) -> IssuedRefreshToken | None:
    """Validate + rotate a presented refresh token.

    Returns the freshly issued replacement on success.
    Returns ``None`` on any failure — and on **reuse detection** the
    entire family is revoked as a side effect (RFC 6749 §10.4). The
    caller maps None to ``invalid_grant`` per RFC 6749.
    """
    if not presented_plaintext or not client_id:
        return None

    # Pull every non-expired row for the client; refresh tokens are
    # rare enough per client that this scales fine without an index
    # on token_hash (which we can't query against by plaintext anyway —
    # Argon2 hashes are salted).
    candidates = (
        OAuthRefreshToken.query.filter_by(client_id=client_id)
        .order_by(OAuthRefreshToken.id.desc())
        .limit(50)  # bounded; well above any honest churn for one client
        .all()
    )

    matched: OAuthRefreshToken | None = None
    for row in candidates:
        if verify_secret(presented_plaintext, row.token_hash):
            matched = row
            break

    if matched is None:
        # Unknown token. Could be expired-and-purged (we don't purge yet)
        # or simply garbage. Treat as an authentication failure but do
        # NOT walk every family's revocation — we have no signal of which
        # family was attacked.
        return None

    now = datetime.utcnow()

    # Reuse detection: a previously-revoked token is being replayed.
    # Per RFC 6749 §10.4 we revoke the entire family so the legitimate
    # client's currently-active refresh is invalidated too. The
    # legitimate client will then have to perform a fresh /authorize
    # round trip, which the human admin will notice.
    if matched.revoked_at is not None:
        revoke_family(matched.family_id, "reuse_detected")
        logger.warning(
            f"[OAuth refresh] reuse detected on family={matched.family_id} "
            f"for client_id={client_id}; entire family revoked"
        )
        return None

    if matched.expires_at < now:
        return None

    # Healthy rotation path. Mark old revoked, issue successor.
    matched.revoked_at = now
    matched.last_used_at = now
    matched.revoke_reason = "rotated"

    plaintext = _new_refresh_value()
    ttl = _refresh_ttl()
    successor = OAuthRefreshToken(
        client_id=client_id,
        token_hash=hash_secret(plaintext),
        scopes=matched.scopes,
        family_id=matched.family_id,
        parent_id=matched.id,
        created_at=now,
        expires_at=now + timedelta(seconds=ttl),
    )
    db_session.add(successor)
    db_session.commit()

    return IssuedRefreshToken(plaintext=plaintext, row=successor, expires_in=ttl)


def revoke_presented_refresh(
    *, presented_plaintext: str, client_id: str
) -> bool:
    """Mark a refresh token revoked. Returns True on success or no-op."""
    if not presented_plaintext or not client_id:
        return False

    candidates = (
        OAuthRefreshToken.query.filter_by(client_id=client_id, revoked_at=None)
        .order_by(OAuthRefreshToken.id.desc())
        .limit(50)
        .all()
    )
    for row in candidates:
        if verify_secret(presented_plaintext, row.token_hash):
            row.revoked_at = datetime.utcnow()
            row.revoke_reason = "client_revoked"
            db_session.commit()
            return True

    # RFC 7009 §2.2 — unknown tokens still respond 200; no information
    # leak about whether the token ever existed.
    return True


# ---------------------------------------------------------------------------
# Access token verification (used by the MCP HTTP transport)
# ---------------------------------------------------------------------------


class AccessTokenError(Exception):
    """Single error type for the resource-server token check.

    The string value is what we surface to the client in the
    ``WWW-Authenticate: Bearer error="..."`` header. Mapping per
    RFC 6750 §3.1: ``invalid_token``, ``insufficient_scope``,
    ``invalid_request``.
    """


def verify_access_token(token_str: str) -> dict:
    """Validate an RS256 JWT access token.

    Returns the claims dict on success. Raises AccessTokenError with a
    spec-compliant ``error`` string ("invalid_token" / "invalid_request")
    on failure. Scope checks are the caller's responsibility — this
    function only validates the signature, exp, iss, and aud claims.

    Verification is stateless: no DB hit per request. The kid is
    matched against JWKS (cached in-process via the active signing key
    + any in-flight predecessor during rotation).
    """
    if not token_str:
        raise AccessTokenError("invalid_request")

    # Build a JWKS object from every known signing key. ``public_jwks``
    # already exposes both the active and the in-flight predecessor
    # during a rotation window, so freshly issued tokens AND tokens
    # signed by the previous key both validate for one TTL window.
    from utils.oauth_keys import public_jwks  # avoid import cycle

    try:
        jwks = JsonWebKey.import_key_set(public_jwks())
    except Exception as e:
        logger.exception(f"JWKS import failed: {e}")
        raise AccessTokenError("invalid_token") from e

    expected_iss = _issuer()
    expected_aud = _audience()

    claims_options = {
        "iss": {"essential": True, "value": expected_iss},
        "aud": {"essential": True, "value": expected_aud},
        "exp": {"essential": True},
    }

    try:
        claims = jwt.decode(token_str, jwks, claims_options=claims_options)
        # Validates iss/aud/exp/nbf/iat per the options above.
        claims.validate()
    except JoseError as e:
        # Authlib's error message is log-worthy but never returned to the
        # client (would leak details about why a token is bad).
        logger.info(f"[OAuth verify] token rejected: {type(e).__name__}: {e}")
        raise AccessTokenError("invalid_token") from e
    except Exception as e:
        logger.exception(f"[OAuth verify] unexpected verification error: {e}")
        raise AccessTokenError("invalid_token") from e

    # claims is a CombinedClaims object — return as a plain dict so the
    # caller can do regular .get() lookups.
    return dict(claims)


def claims_have_scope(claims: dict, required: str) -> bool:
    """True if ``required`` is in the token's space-delimited scope claim."""
    granted = (claims.get("scope") or "").split()
    return required in granted
