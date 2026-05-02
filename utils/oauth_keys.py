"""RS256 signing-key lifecycle for the Remote MCP OAuth server.

Generates an RSA-2048 key pair on first run, stores the private key under
``keys/`` (chmod 600), and persists the public JWK in the
``oauth_signing_keys`` table for the JWKS endpoint.

A token's ``kid`` claim points back to this row so we can rotate keys —
two rows can be active simultaneously during a rotation window so older
access tokens still validate for one TTL window.
"""

from __future__ import annotations

import json
import os
import secrets
import stat
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Tuple

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from database.oauth_db import (
    OAuthSigningKey,
    db_session,
    get_active_signing_key,
)
from utils.logging import get_logger

logger = get_logger(__name__)

# Where private keys live. The directory already exists (created by start.sh
# / install.sh) with chmod 700. We chmod 600 individual key files.
KEYS_DIR = Path(os.getenv("MCP_OAUTH_KEYS_DIR", "keys"))


def _ensure_keys_dir() -> None:
    KEYS_DIR.mkdir(mode=0o700, exist_ok=True)
    # Tighten if some prior run left it world-readable.
    try:
        current = KEYS_DIR.stat().st_mode & 0o777
        if current != 0o700:
            KEYS_DIR.chmod(0o700)
    except OSError as e:
        logger.warning(f"Could not enforce 0700 on keys dir: {e}")


def _new_kid() -> str:
    """Short, URL-safe key id. 16 hex chars = 64 bits of entropy."""
    return secrets.token_hex(8)


def _rsa_public_jwk(public_key, kid: str) -> dict[str, Any]:
    """Encode an RSA public key as a JWK (RFC 7517) with our claims."""
    numbers = public_key.public_numbers()

    def _b64u(value: int) -> str:
        # Big-endian, minimal length; base64url without padding.
        import base64

        length = (value.bit_length() + 7) // 8
        raw = value.to_bytes(length, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": kid,
        "n": _b64u(numbers.n),
        "e": _b64u(numbers.e),
    }


def generate_keypair() -> tuple[OAuthSigningKey, str]:
    """Create a fresh RS256 keypair, persist it, mark it active.

    Any previously-active key is left in place but marked inactive so
    tokens it signed continue to validate via JWKS for one TTL window.

    Returns the new ``OAuthSigningKey`` row and the absolute path to the
    private PEM file.
    """
    _ensure_keys_dir()

    kid = _new_kid()
    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )

    pem_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    private_path = (KEYS_DIR / f"mcp_oauth_{kid}.pem").resolve()
    private_path.write_bytes(pem_bytes)
    private_path.chmod(0o600)

    public_jwk = _rsa_public_jwk(private_key.public_key(), kid)

    # Demote any prior active key — a successor is taking over.
    OAuthSigningKey.query.filter_by(is_active=True).update(
        {"is_active": False, "rotated_at": datetime.utcnow()}
    )

    row = OAuthSigningKey(
        kid=kid,
        algorithm="RS256",
        public_jwk=json.dumps(public_jwk),
        private_path=str(private_path),
        is_active=True,
    )
    db_session.add(row)
    db_session.commit()

    logger.info(f"Generated new OAuth signing key kid={kid} path={private_path}")
    return row, str(private_path)


def ensure_signing_key() -> OAuthSigningKey:
    """Idempotent — returns the active signing key, creating one if needed.

    Verifies the private file is still present and chmod'd correctly. If
    the file vanished (e.g. wiped from disk while the row remained), a
    fresh keypair is generated and the orphaned row is demoted.
    """
    active = get_active_signing_key()
    if active is None:
        row, _ = generate_keypair()
        return row

    private_path = Path(active.private_path)
    if not private_path.is_file():
        logger.warning(
            f"Active signing key file missing at {private_path}; generating replacement."
        )
        row, _ = generate_keypair()
        return row

    # Tighten perms if something nudged them looser.
    try:
        current = private_path.stat().st_mode & 0o777
        if current != 0o600:
            private_path.chmod(0o600)
    except OSError as e:
        logger.warning(f"Could not enforce 0600 on {private_path}: {e}")

    return active


def load_private_pem(key: OAuthSigningKey) -> bytes:
    """Read the private PEM bytes for a signing key. Raises on missing file."""
    return Path(key.private_path).read_bytes()


def public_jwks() -> dict[str, list[dict[str, Any]]]:
    """All currently-relevant signing keys for the /oauth/jwks.json endpoint.

    Returns:
      * The active key
      * Plus any key rotated within the last access-token TTL window
        (so freshly issued tokens that were signed by the predecessor
        still validate during the rotation overlap)

    Older keys are excluded so the JWKS doesn't grow unbounded across
    rotations (security review finding M-1).
    """
    from datetime import datetime, timedelta

    # Match the access TTL ceiling so the window covers any in-flight
    # token signed by a recently-demoted key.
    overlap_window = timedelta(seconds=3600)  # ACCESS_TTL_MAX
    cutoff = datetime.utcnow() - overlap_window

    keys: list[dict[str, Any]] = []
    rows = OAuthSigningKey.query.order_by(OAuthSigningKey.created_at.desc()).all()
    for row in rows:
        # Always include the active row.
        if not row.is_active:
            # Skip demoted rows older than the overlap window.
            rotated = row.rotated_at or row.created_at
            if rotated and rotated < cutoff:
                continue
        try:
            keys.append(json.loads(row.public_jwk))
        except json.JSONDecodeError:
            logger.warning(f"Bad public_jwk JSON for kid={row.kid}; skipping.")
    return {"keys": keys}


def cleanup_stale_signing_keys() -> int:
    """Delete on-disk private PEMs for signing keys outside the JWKS window.

    The DB row stays — JWKS already filters by recency — but the
    private file is removed so a later filesystem compromise can't
    forge tokens for an arbitrarily old period.

    Safe to call from a startup hook or periodic cleanup. Returns
    count of files deleted.
    """
    from datetime import datetime, timedelta

    cutoff = datetime.utcnow() - timedelta(seconds=3600)
    removed = 0
    for row in OAuthSigningKey.query.filter_by(is_active=False).all():
        rotated = row.rotated_at or row.created_at
        if rotated and rotated < cutoff:
            try:
                p = Path(row.private_path)
                if p.is_file():
                    p.unlink()
                    removed += 1
                    logger.info(
                        f"[OAuth keys] removed stale private file kid={row.kid} "
                        f"path={row.private_path}"
                    )
            except OSError as e:
                logger.warning(f"Could not remove {row.private_path}: {e}")
    return removed
