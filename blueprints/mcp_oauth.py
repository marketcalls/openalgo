"""OAuth 2.1 authorization server for the Remote MCP feature.

Phase 2c (this file): discovery, JWKS, and Dynamic Client Registration.
Phase 2d will add the actual ``/oauth/authorize``, ``/oauth/token``, and
``/oauth/revoke`` flows on top of the storage and metadata laid down here.

All endpoints are gated upstream by ``MCP_HTTP_ENABLED`` in ``app.py`` —
this blueprint is never registered on installs that haven't opted in.

See ``docs/prd/remote-mcp.md`` for the full design and threat model.
"""

from __future__ import annotations

import json
import os
import secrets
from typing import Any
from urllib.parse import urlparse

from flask import Blueprint, jsonify, request

from database.oauth_db import (
    OAuthClient,
    db_session,
    hash_secret,
)
from limiter import limiter
from utils.logging import get_logger
from utils.oauth_keys import ensure_signing_key, public_jwks

logger = get_logger(__name__)

# Two blueprints — discovery is at root (/.well-known/...) per RFC 8414 / 9728,
# the rest hangs off /oauth.
mcp_oauth_bp = Blueprint("mcp_oauth_bp", __name__, url_prefix="/oauth")
mcp_wellknown_bp = Blueprint("mcp_wellknown_bp", __name__, url_prefix="")


# Rate limits per the PRD. Per-IP for the un-authenticated DCR and token
# endpoints; per-token rate limits land in Phase 2d once tokens exist.
DCR_RATE_LIMIT = "10 per hour"
TOKEN_RATE_LIMIT = "20 per minute"

# Scope catalogue. write:orders is gated by a separate env var so MCP is
# read-only out of the box.
SCOPE_READ_MARKET = "read:market"
SCOPE_READ_ACCOUNT = "read:account"
SCOPE_WRITE_ORDERS = "write:orders"

MAX_CLIENT_NAME_LEN = 200
MAX_REDIRECT_URIS = 5
MAX_REDIRECT_URI_LEN = 2000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _public_url() -> str:
    """Configured base URL where the MCP server is reachable.

    Falls back to ``request.host_url`` if MCP_PUBLIC_URL is not set so
    a fresh install advertises something sensible. Production MUST set
    MCP_PUBLIC_URL to the canonical HTTPS origin.
    """
    return (os.getenv("MCP_PUBLIC_URL") or "").rstrip("/")


def _supported_scopes() -> list[str]:
    """Scopes we are willing to advertise + grant.

    ``write:orders`` is opt-in via MCP_OAUTH_WRITE_SCOPE_ENABLED. While
    that flag is False the scope is not advertised in discovery and any
    DCR or token request that asks for it returns ``invalid_scope``.
    """
    scopes = [SCOPE_READ_MARKET, SCOPE_READ_ACCOUNT]
    if os.getenv("MCP_OAUTH_WRITE_SCOPE_ENABLED", "False").lower() == "true":
        scopes.append(SCOPE_WRITE_ORDERS)
    return scopes


def _require_approval() -> bool:
    """Whether DCR-registered clients must be approved by the admin first."""
    return os.getenv("MCP_OAUTH_REQUIRE_APPROVAL", "True").lower() == "true"


def _oauth_error(error_code: str, description: str, status: int):
    """Format an RFC 6749/7591-style error response."""
    return (
        jsonify({"error": error_code, "error_description": description}),
        status,
    )


def _validate_redirect_uri(uri: Any) -> tuple[bool, str]:
    """Strict checks on a single user-supplied redirect URI.

    HTTPS is required except for localhost callbacks, which CLI clients
    use during development. Fragments are forbidden — they can't carry
    state through an OAuth round-trip and tend to be a sign of confusion
    on the client side.
    """
    if not isinstance(uri, str) or not uri:
        return False, "redirect_uri must be a non-empty string"
    if len(uri) > MAX_REDIRECT_URI_LEN:
        return False, "redirect_uri exceeds 2000 chars"
    parsed = urlparse(uri)
    if parsed.scheme not in ("https", "http"):
        return False, "redirect_uri must use https"
    if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1"):
        return False, "http redirect_uri only permitted for localhost / 127.0.0.1"
    if not parsed.netloc:
        return False, "redirect_uri must include a host"
    if "#" in uri:
        return False, "redirect_uri must not contain a fragment"
    return True, ""


# ---------------------------------------------------------------------------
# Discovery (RFC 8414, RFC 9728)
# ---------------------------------------------------------------------------


@mcp_wellknown_bp.route("/.well-known/oauth-authorization-server")
def discovery_authorization_server():
    """RFC 8414 — authorization server metadata.

    The response is what hosted MCP clients (claude.ai, chatgpt.com)
    fetch to discover our endpoints. Everything in here must reflect
    the actual implementation — drift causes opaque OAuth failures on
    the client side.
    """
    base = _public_url() or request.host_url.rstrip("/")
    return jsonify(
        {
            "issuer": base,
            "authorization_endpoint": f"{base}/oauth/authorize",
            "token_endpoint": f"{base}/oauth/token",
            "registration_endpoint": f"{base}/oauth/register",
            "revocation_endpoint": f"{base}/oauth/revoke",
            "jwks_uri": f"{base}/oauth/jwks.json",
            "scopes_supported": _supported_scopes(),
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            # PKCE S256 only — `plain` is forbidden by the PRD threat model.
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": [
                "client_secret_basic",
                "client_secret_post",
                "none",  # public clients (PKCE-only)
            ],
            "service_documentation": "https://docs.openalgo.in/remote-mcp",
        }
    )


@mcp_wellknown_bp.route("/.well-known/oauth-protected-resource")
def discovery_protected_resource():
    """RFC 9728 — protected-resource metadata.

    Tells a client where to find the authorization server when it sees
    a 401 from /mcp. We point back at the same host since OpenAlgo is
    both AS and RS for this deployment.
    """
    base = _public_url() or request.host_url.rstrip("/")
    return jsonify(
        {
            "resource": f"{base}/mcp",
            "authorization_servers": [base],
            "bearer_methods_supported": ["header"],
            "scopes_supported": _supported_scopes(),
            "resource_documentation": "https://docs.openalgo.in/remote-mcp",
        }
    )


# ---------------------------------------------------------------------------
# JWKS
# ---------------------------------------------------------------------------


@mcp_oauth_bp.route("/jwks.json")
def jwks_endpoint():
    """Public keys for verifying access-token signatures.

    A client validating an access-token JWT looks up the ``kid`` claim
    in this set. We expose the active key plus any in-flight rotation
    predecessor so tokens issued under the old key still validate for
    one TTL window after rotation.
    """
    # Idempotent — generates a key on the very first request if none exists.
    ensure_signing_key()
    return jsonify(public_jwks())


# ---------------------------------------------------------------------------
# Dynamic Client Registration (RFC 7591)
# ---------------------------------------------------------------------------


@mcp_oauth_bp.route("/register", methods=["POST"])
@limiter.limit(DCR_RATE_LIMIT)
def register_client():
    """RFC 7591 — Dynamic Client Registration.

    Hosted MCP clients (claude.ai, chatgpt.com) post here to register
    themselves. We validate strictly:

    - At most ``MAX_REDIRECT_URIS`` redirect URIs, each HTTPS (or
      localhost for dev), no fragments, capped length
    - Requested scopes must be a subset of what we advertise — write
      scope rejected when MCP_OAUTH_WRITE_SCOPE_ENABLED=False
    - ``token_endpoint_auth_method`` must be one of the three we
      explicitly support; default ``client_secret_basic``

    When ``MCP_OAUTH_REQUIRE_APPROVAL=True`` (the default per the PRD),
    the new client lands with ``approved=False`` and the OAuth flow at
    ``/oauth/authorize`` must reject it until the admin approves on the
    forthcoming admin UI. Until that lands the admin can flip the flag
    via ``database/oauth_db.py`` directly.
    """
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return _oauth_error("invalid_client_metadata", "Body must be a JSON object.", 400)

    client_name = (data.get("client_name") or "").strip()[:MAX_CLIENT_NAME_LEN]
    if not client_name:
        return _oauth_error("invalid_client_metadata", "client_name is required.", 400)

    redirect_uris = data.get("redirect_uris")
    if not isinstance(redirect_uris, list) or not redirect_uris:
        return _oauth_error(
            "invalid_redirect_uri", "redirect_uris must be a non-empty list.", 400
        )
    if len(redirect_uris) > MAX_REDIRECT_URIS:
        return _oauth_error(
            "invalid_redirect_uri",
            f"At most {MAX_REDIRECT_URIS} redirect URIs.",
            400,
        )
    for uri in redirect_uris:
        ok, reason = _validate_redirect_uri(uri)
        if not ok:
            return _oauth_error("invalid_redirect_uri", reason, 400)

    # Requested scope is informational at registration; the actual grant
    # is decided on /authorize. We still validate the client isn't asking
    # for something we don't recognize.
    requested_scopes_raw = data.get("scope") or ""
    if not isinstance(requested_scopes_raw, str):
        return _oauth_error(
            "invalid_client_metadata", "scope must be a space-delimited string.", 400
        )
    requested_scopes = [s for s in requested_scopes_raw.split() if s]
    supported = set(_supported_scopes())
    for s in requested_scopes:
        if s not in supported:
            return _oauth_error("invalid_scope", f"Unsupported scope: {s}", 400)

    # Confidential vs public client.
    auth_method = data.get("token_endpoint_auth_method") or "client_secret_basic"
    if auth_method not in ("client_secret_basic", "client_secret_post", "none"):
        return _oauth_error(
            "invalid_client_metadata",
            f"Unsupported token_endpoint_auth_method: {auth_method}",
            400,
        )
    is_public = auth_method == "none"

    client_id = secrets.token_urlsafe(24)
    client_secret = None if is_public else secrets.token_urlsafe(32)

    new_client = OAuthClient(
        client_id=client_id,
        client_name=client_name,
        redirect_uris=json.dumps(redirect_uris),
        client_secret_hash=hash_secret(client_secret) if client_secret else None,
        scopes_requested=" ".join(requested_scopes),
        approved=not _require_approval(),
    )
    db_session.add(new_client)
    db_session.commit()

    logger.info(
        f"[OAuth DCR] registered client_id={client_id} name='{client_name}' "
        f"public={is_public} approved={new_client.approved} ip={request.remote_addr}"
    )

    response: dict[str, Any] = {
        "client_id": client_id,
        "client_id_issued_at": int(new_client.created_at.timestamp()),
        "client_name": client_name,
        "redirect_uris": redirect_uris,
        "token_endpoint_auth_method": auth_method,
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "scope": " ".join(requested_scopes) if requested_scopes else " ".join(_supported_scopes()),
    }
    if client_secret:
        # RFC 7591 — secret is returned exactly once at registration.
        # 0 means "never expires"; rotation is via re-register.
        response["client_secret"] = client_secret
        response["client_secret_expires_at"] = 0
    if not new_client.approved:
        # Surfaced to the client so it knows the next /authorize will
        # 403 until the admin approves. Not part of RFC 7591 but a
        # sensible courtesy.
        response["status"] = "pending_approval"

    return jsonify(response), 201


# ---------------------------------------------------------------------------
# Phase 2d stubs — kept here so ``app.py`` can register one blueprint and
# discovery returns 200s for endpoints that visibly exist.
# ---------------------------------------------------------------------------


@mcp_oauth_bp.route("/authorize", methods=["GET", "POST"])
def authorize_endpoint():
    return _oauth_error(
        "not_implemented",
        "Phase 2d implements /oauth/authorize. See docs/prd/remote-mcp.md.",
        501,
    )


@mcp_oauth_bp.route("/token", methods=["POST"])
@limiter.limit(TOKEN_RATE_LIMIT)
def token_endpoint():
    return _oauth_error(
        "not_implemented",
        "Phase 2d implements /oauth/token. See docs/prd/remote-mcp.md.",
        501,
    )


@mcp_oauth_bp.route("/revoke", methods=["POST"])
def revoke_endpoint():
    return _oauth_error(
        "not_implemented",
        "Phase 2d implements /oauth/revoke. See docs/prd/remote-mcp.md.",
        501,
    )
