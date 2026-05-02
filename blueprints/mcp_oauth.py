"""OAuth 2.1 authorization server for the Remote MCP feature.

Phase 2c (this file): discovery, JWKS, and Dynamic Client Registration.
Phase 2d will add the actual ``/oauth/authorize``, ``/oauth/token``, and
``/oauth/revoke`` flows on top of the storage and metadata laid down here.

All endpoints are gated upstream by ``MCP_HTTP_ENABLED`` in ``app.py`` —
this blueprint is never registered on installs that haven't opted in.

See ``docs/prd/remote-mcp.md`` for the full design and threat model.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlparse

from flask import Blueprint, jsonify, redirect, render_template_string, request, session

from database.oauth_db import (
    OAuthClient,
    db_session,
    get_client,
    hash_secret,
    verify_secret,
)
from database.user_db import User, find_user_by_exact_username
from limiter import limiter
from utils.logging import get_logger
from utils.oauth_codes import consume as consume_code
from utils.oauth_codes import discard as discard_code
from utils.oauth_codes import issue as issue_code
from utils.oauth_keys import ensure_signing_key, public_jwks
from utils.oauth_tokens import (
    issue_access_token,
    issue_initial_refresh_token,
    revoke_presented_refresh,
    rotate_refresh_token,
)
from utils.session import check_session_validity

logger = get_logger(__name__)

# Two blueprints — discovery is at root (/.well-known/...) per RFC 8414 / 9728,
# the rest hangs off /oauth.
mcp_oauth_bp = Blueprint("mcp_oauth_bp", __name__, url_prefix="/oauth")
mcp_wellknown_bp = Blueprint("mcp_wellknown_bp", __name__, url_prefix="")


def _cors_allowed_origins() -> list[str]:
    raw = os.getenv("MCP_HTTP_CORS_ORIGINS", "")
    return [o.strip() for o in raw.split(",") if o.strip()]


def _apply_cors_to_response(response):
    """Echo CORS headers for the configured allowlist origins.

    Hosted OAuth clients (claude.ai, chatgpt.com) post to
    /oauth/token from a browser context with a different Origin.
    Without these headers the browser blocks the response.
    """
    origin = request.headers.get("Origin")
    if not origin or origin not in _cors_allowed_origins():
        return response
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = (
        "Authorization, Content-Type, X-Requested-With"
    )
    response.headers["Access-Control-Expose-Headers"] = (
        "WWW-Authenticate, Link, Content-Type"
    )
    response.headers["Access-Control-Max-Age"] = "600"
    response.headers["Vary"] = "Origin"
    return response


@mcp_oauth_bp.after_request
def _oauth_after_request(response):
    return _apply_cors_to_response(response)


@mcp_wellknown_bp.after_request
def _wellknown_after_request(response):
    return _apply_cors_to_response(response)


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
    # Reject userinfo (user:pass@host) — RFC 3986 allows it but it's
    # confusing in browser contexts and some parsers disagree on which
    # part is the host (security review finding M-2).
    if parsed.username or parsed.password or "@" in (parsed.netloc or ""):
        return False, "redirect_uri must not contain userinfo"
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


def _build_protected_resource_metadata():
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


@mcp_wellknown_bp.route("/.well-known/oauth-protected-resource")
def discovery_protected_resource():
    """RFC 9728 — protected-resource metadata at the host root.

    Tells a client where to find the authorization server when it sees
    a 401 from /mcp. We point back at the same host since OpenAlgo is
    both AS and RS for this deployment.
    """
    return _build_protected_resource_metadata()


@mcp_wellknown_bp.route("/.well-known/oauth-protected-resource/mcp")
@mcp_wellknown_bp.route("/.well-known/oauth-protected-resource/<path:resource_path>")
def discovery_protected_resource_for_path(resource_path: str = "mcp"):
    """Path-suffixed variant per RFC 9728 §3.1.

    Some clients (notably ChatGPT's MCP integration) construct the
    metadata URL as ``<resource>/.well-known/oauth-protected-resource``
    or use a path-suffix variant rather than the host-root form. We
    serve the same payload on the suffixed path so both discovery
    styles work.
    """
    return _build_protected_resource_metadata()


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
# Authorization (RFC 6749 §4.1) + PKCE (RFC 7636)
# ---------------------------------------------------------------------------


# How long ``session["totp_verified_at"]`` remains "fresh" for a write-scope
# grant. Short window forces the admin to re-prompt for TOTP whenever
# they're approving order-placement authority for a new MCP client.
_FRESH_TOTP_SECONDS = 60


def _is_fresh_totp() -> bool:
    """True if the current session verified TOTP within the last 60 seconds."""
    ts = session.get("totp_verified_at")
    if not ts:
        return False
    try:
        return (datetime.utcnow() - datetime.fromisoformat(ts)) <= timedelta(
            seconds=_FRESH_TOTP_SECONDS
        )
    except (TypeError, ValueError):
        return False


def _client_redirect_uri_allowed(client: OAuthClient, candidate: str) -> bool:
    """Exact match against the registered list. No prefix games."""
    try:
        registered = json.loads(client.redirect_uris) if client.redirect_uris else []
    except json.JSONDecodeError:
        return False
    return candidate in registered


def _origin_of(uri: str) -> str:
    """Extract scheme://host[:port] from a redirect_uri (for CSP form-action)."""
    p = urlparse(uri)
    if not p.scheme or not p.netloc:
        return ""
    return f"{p.scheme}://{p.netloc}"


def _oauth_redirect(redirect_uri: str, query_params: dict[str, str]):
    """Build a 302 to the OAuth client with a relaxed form-action CSP.

    The global Flask CSP sets ``form-action 'self'`` (defense-in-depth
    against forms posting outside the dashboard). The OAuth consent
    form intentionally posts to ``/oauth/authorize`` and gets a 302 to
    the registered ``redirect_uri`` — a cross-origin destination that
    the strict CSP would otherwise block. We override the header on
    just this response to include the redirect target's origin, which
    has already been exact-matched against the client's registered
    list at this point.
    """
    sep = "&" if urlparse(redirect_uri).query else "?"
    target = f"{redirect_uri}{sep}{urlencode(query_params)}"
    response = redirect(target)
    origin = _origin_of(redirect_uri)
    if origin:
        # Replace the inherited CSP header so the redirect chain is
        # allowed by the browser. We keep 'self' so any in-page forms
        # also work, but add the specific origin we're about to send
        # the user to. This is per-response only; the rest of the app
        # still gets the strict policy.
        response.headers["Content-Security-Policy"] = (
            f"form-action 'self' {origin}"
        )
    return response


def _redirect_with_error(
    redirect_uri: str, error: str, description: str, state: str | None
) -> Any:
    """Send the user-agent back to the client with a standard OAuth error.

    Used for errors that occur *after* we've validated the redirect_uri —
    pre-validation errors render an inline page instead so we never
    redirect to an attacker-supplied URL.
    """
    params = {"error": error, "error_description": description}
    if state:
        params["state"] = state
    return _oauth_redirect(redirect_uri, params)


_CONSENT_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="referrer" content="no-referrer">
  <title>Authorize {{ client_name }} — OpenAlgo</title>
  <style>
    body { font-family: system-ui, -apple-system, sans-serif; background: #f9fafb;
           margin: 0; padding: 0; min-height: 100vh; display: flex;
           align-items: center; justify-content: center; }
    .card { background: white; border-radius: 12px; padding: 32px;
            box-shadow: 0 4px 24px rgba(0,0,0,0.08); max-width: 480px;
            width: 92%; }
    h1 { margin: 0 0 8px; font-size: 22px; }
    p { color: #4b5563; line-height: 1.5; }
    .scopes { background: #f3f4f6; border-radius: 8px; padding: 12px;
              margin: 16px 0; font-family: monospace; }
    .scopes li { margin: 4px 0; }
    .row { display: flex; gap: 12px; margin-top: 24px; }
    button { flex: 1; padding: 12px; border-radius: 8px; border: 0;
             font-size: 14px; font-weight: 600; cursor: pointer; }
    .approve { background: #10b981; color: white; }
    .deny { background: #f3f4f6; color: #374151; }
    .totp { margin: 16px 0; padding: 12px; background: #fef3c7;
            border-left: 4px solid #f59e0b; border-radius: 4px; }
    input[type=text] { padding: 10px; font-size: 16px; width: 100%;
                       box-sizing: border-box; border: 1px solid #d1d5db;
                       border-radius: 6px; font-family: monospace;
                       letter-spacing: 4px; text-align: center; }
    .err { color: #b91c1c; font-size: 13px; margin-top: 8px; }
    .meta { color: #6b7280; font-size: 12px; margin-top: 16px; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Authorize {{ client_name }}</h1>
    <p>This MCP client is requesting access to your OpenAlgo install.</p>

    <p><strong>Scopes requested:</strong></p>
    <ul class="scopes">
      {% for s in scopes %}<li>{{ s }}</li>{% endfor %}
    </ul>

    {% if requires_fresh_totp %}
    <div class="totp">
      <strong>2FA confirmation required</strong>
      <p style="margin: 8px 0 0; font-size: 13px;">
        This client wants <code>write:orders</code>. Enter the 6-digit code
        from your authenticator app to authorize order-placement.
      </p>
    </div>
    {% endif %}

    {% if error %}<div class="err">{{ error }}</div>{% endif %}

    <form method="POST" action="/oauth/authorize">
      <input type="hidden" name="client_id" value="{{ client_id }}">
      <input type="hidden" name="redirect_uri" value="{{ redirect_uri }}">
      <input type="hidden" name="scope" value="{{ scope }}">
      <input type="hidden" name="state" value="{{ state }}">
      <input type="hidden" name="code_challenge" value="{{ code_challenge }}">
      <input type="hidden" name="code_challenge_method" value="{{ code_challenge_method }}">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">

      {% if requires_fresh_totp %}
      <input type="text" name="totp_code" autocomplete="one-time-code"
             inputmode="numeric" pattern="[0-9]{6}" maxlength="6"
             placeholder="123456" autofocus required>
      {% endif %}

      <div class="row">
        <button type="submit" name="decision" value="deny" class="deny">Deny</button>
        <button type="submit" name="decision" value="approve" class="approve">Approve</button>
      </div>
    </form>

    <div class="meta">
      Client: <code>{{ client_id }}</code><br>
      Redirect: <code>{{ redirect_uri }}</code>
    </div>
  </div>
</body>
</html>
"""


def _render_consent(**ctx) -> str:
    return render_template_string(_CONSENT_TEMPLATE, **ctx)


@mcp_oauth_bp.route("/authorize", methods=["GET", "POST"])
@check_session_validity
@limiter.limit("30 per minute;200 per hour")
def authorize_endpoint():
    """RFC 6749 §4.1 authorization endpoint with PKCE.

    GET renders the consent screen once every client/scope check passes.
    POST records the user's decision: approve mints an authorization
    code and redirects back to the client; deny redirects with
    ``error=access_denied``.

    Pre-validation errors (bad client_id, bad redirect_uri) render an
    inline error page rather than redirecting to an unvalidated URL.
    Once redirect_uri is validated, errors are sent back to the client
    via the standard OAuth error redirect.
    """
    # Pull params from query string on GET, form on POST.
    src = request.values
    client_id = src.get("client_id", "").strip()
    redirect_uri = src.get("redirect_uri", "").strip()
    response_type = src.get("response_type", "code").strip()
    scope = src.get("scope", "").strip()
    state = src.get("state")
    # Cap state length so a malicious client can't make us render a
    # huge consent page or build a 10MB redirect URL (security review
    # finding L-1).
    if state is not None and len(state) > 512:
        return _oauth_error(
            "invalid_request", "state parameter too long (max 512 chars).", 400
        )
    code_challenge = src.get("code_challenge", "").strip()
    code_challenge_method = src.get("code_challenge_method", "").strip()

    # ---- Pre-validation: cannot redirect to an unverified URL ----
    if not client_id:
        return _oauth_error("invalid_request", "client_id is required.", 400)
    client = get_client(client_id)
    if client is None or client.revoked_at is not None:
        return _oauth_error("invalid_client", "Unknown or revoked client.", 400)
    if not client.approved:
        return _oauth_error(
            "unauthorized_client",
            "This client is registered but not yet approved by the admin.",
            403,
        )
    if not redirect_uri or not _client_redirect_uri_allowed(client, redirect_uri):
        return _oauth_error("invalid_request", "redirect_uri is not registered.", 400)

    # ---- Post-validation: now we can OAuth-redirect errors ----
    if response_type != "code":
        return _redirect_with_error(
            redirect_uri,
            "unsupported_response_type",
            "Only response_type=code is supported.",
            state,
        )
    if code_challenge_method != "S256" or not code_challenge:
        return _redirect_with_error(
            redirect_uri,
            "invalid_request",
            "PKCE S256 code_challenge is required.",
            state,
        )
    requested_scopes = [s for s in scope.split() if s]
    supported = set(_supported_scopes())
    bad_scope = next((s for s in requested_scopes if s not in supported), None)
    if bad_scope:
        return _redirect_with_error(
            redirect_uri, "invalid_scope", f"Unsupported scope: {bad_scope}", state
        )
    if not requested_scopes:
        return _redirect_with_error(
            redirect_uri, "invalid_scope", "scope is required.", state
        )

    # ---- Per-purpose 2FA gate (when admin has enabled it) ----
    user = find_user_by_exact_username(session["user"])
    if user is None:
        return _oauth_error("server_error", "Authenticated user not found.", 500)

    write_requested = SCOPE_WRITE_ORDERS in requested_scopes
    requires_fresh_totp = (
        write_requested and user.is_totp_required_for("mcp")
    )

    # ---- GET = render consent screen ----
    if request.method == "GET":
        return _render_consent(
            client_id=client_id,
            client_name=client.client_name,
            redirect_uri=redirect_uri,
            scope=scope,
            state=state or "",
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            scopes=requested_scopes,
            requires_fresh_totp=requires_fresh_totp,
            error=None,
        )

    # ---- POST = decision ----
    decision = request.form.get("decision")
    if decision == "deny":
        return _redirect_with_error(
            redirect_uri, "access_denied", "User denied the request.", state
        )

    # Approve path: enforce fresh TOTP if required for this scope set.
    if requires_fresh_totp:
        totp_code = (request.form.get("totp_code") or "").strip()
        if not totp_code or not user.verify_totp(totp_code):
            return _render_consent(
                client_id=client_id,
                client_name=client.client_name,
                redirect_uri=redirect_uri,
                scope=scope,
                state=state or "",
                code_challenge=code_challenge,
                code_challenge_method=code_challenge_method,
                scopes=requested_scopes,
                requires_fresh_totp=True,
                error="Invalid TOTP code. Please try again.",
            )
        # Successful TOTP refreshes the session marker so a follow-up
        # OAuth dance with another client doesn't re-prompt unnecessarily.
        from datetime import datetime as _dt

        session["totp_verified_at"] = _dt.utcnow().isoformat()

    # Mint the code.
    code_entry = issue_code(
        client_id=client.client_id,
        redirect_uri=redirect_uri,
        scope=" ".join(requested_scopes),
        user_id=user.id,
        code_challenge=code_challenge,
        code_challenge_method="S256",
        state=state,
    )
    logger.info(
        f"[OAuth /authorize] APPROVE client_id={client.client_id} "
        f"user={user.username} scope='{scope}' write={write_requested}"
    )

    params = {"code": code_entry.code}
    if state:
        params["state"] = state
    return _oauth_redirect(redirect_uri, params)


# ---------------------------------------------------------------------------
# Token endpoint (RFC 6749 §3.2)
# ---------------------------------------------------------------------------


def _verify_pkce_s256(verifier: str, challenge: str) -> bool:
    """RFC 7636 §4.6 S256 challenge verification — constant-time compare."""
    if not verifier or not challenge:
        return False
    if not (43 <= len(verifier) <= 128):
        return False
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return secrets.compare_digest(expected, challenge)


def _authenticate_client_at_token() -> tuple[OAuthClient | None, str]:
    """Resolve the client per RFC 6749 §2.3.1.

    Returns ``(client, error_message)`` — exactly one of the two is set.
    Supports HTTP Basic, post-body, and public clients (no secret).
    """
    auth = request.authorization
    if auth and auth.type and auth.type.lower() == "basic":
        client_id = (auth.username or "").strip()
        client_secret: str | None = auth.password or ""
    else:
        client_id = (request.form.get("client_id") or "").strip()
        client_secret = request.form.get("client_secret")

    if not client_id:
        return None, "client_id is required"

    client = get_client(client_id)
    if client is None or client.revoked_at is not None:
        return None, "unknown or revoked client"
    if not client.approved:
        return None, "client not approved"

    if client.client_secret_hash:
        # Confidential client — secret required.
        if not client_secret or not verify_secret(
            client_secret, client.client_secret_hash
        ):
            return None, "invalid client credentials"
    else:
        # Public client — no secret accepted.
        if client_secret:
            return None, "this client must not present a secret"
    return client, ""


@mcp_oauth_bp.route("/token", methods=["POST"])
@limiter.limit(TOKEN_RATE_LIMIT)
def token_endpoint():
    """RFC 6749 §3.2 token endpoint.

    Two grant types supported:

    * ``authorization_code`` — code → access + refresh (initial issuance)
    * ``refresh_token`` — refresh → new access + new refresh (rotation)

    Reuse-detection on the refresh path revokes the entire token family.
    """
    grant_type = (request.form.get("grant_type") or "").strip()
    if grant_type not in ("authorization_code", "refresh_token"):
        return _oauth_error(
            "unsupported_grant_type",
            "Supported grant types: authorization_code, refresh_token.",
            400,
        )

    client, err = _authenticate_client_at_token()
    if client is None:
        return _oauth_error("invalid_client", err, 401)

    if grant_type == "authorization_code":
        return _grant_authorization_code(client)
    return _grant_refresh(client)


def _grant_authorization_code(client: OAuthClient):
    """Validate the code + PKCE verifier and issue tokens."""
    code = (request.form.get("code") or "").strip()
    redirect_uri = (request.form.get("redirect_uri") or "").strip()
    code_verifier = (request.form.get("code_verifier") or "").strip()

    if not code or not redirect_uri or not code_verifier:
        return _oauth_error(
            "invalid_request",
            "code, redirect_uri, code_verifier are all required.",
            400,
        )

    entry = consume_code(code)
    if entry is None:
        return _oauth_error("invalid_grant", "Code unknown, expired, or already used.", 400)

    # All three must match what was bound at /authorize. The client_id
    # check forecloses the attack where a stolen code is exchanged by a
    # *different* client.
    if entry.client_id != client.client_id:
        return _oauth_error("invalid_grant", "client_id mismatch.", 400)
    if entry.redirect_uri != redirect_uri:
        return _oauth_error("invalid_grant", "redirect_uri mismatch.", 400)
    if not _verify_pkce_s256(code_verifier, entry.code_challenge):
        return _oauth_error("invalid_grant", "PKCE verification failed.", 400)

    access, ttl, jti = issue_access_token(
        user_id=entry.user_id,
        client_id=client.client_id,
        scope=entry.scope,
    )
    refresh = issue_initial_refresh_token(client_id=client.client_id, scope=entry.scope)

    # Touch last_used on the client for observability.
    client.last_used_at = datetime.utcnow()
    db_session.commit()

    logger.info(
        f"[OAuth /token] code-grant ok client_id={client.client_id} "
        f"jti={jti} scope='{entry.scope}'"
    )

    return jsonify(
        {
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": ttl,
            "refresh_token": refresh.plaintext,
            "scope": entry.scope,
        }
    )


def _grant_refresh(client: OAuthClient):
    """Validate + rotate a refresh token."""
    presented = (request.form.get("refresh_token") or "").strip()
    requested_scope = (request.form.get("scope") or "").strip()

    if not presented:
        return _oauth_error("invalid_request", "refresh_token is required.", 400)

    new_refresh = rotate_refresh_token(
        presented_plaintext=presented, client_id=client.client_id
    )
    if new_refresh is None:
        # Either bad/expired/unknown OR reuse-detected (in which case
        # rotate_refresh_token has already revoked the family).
        return _oauth_error("invalid_grant", "Invalid refresh_token.", 400)

    # RFC 6749 §6 — "The requested scope MUST NOT include any scope not
    # originally granted." We enforce by intersection: if the client
    # narrows scope on refresh, that's allowed; widening is rejected.
    granted_scopes = set(new_refresh.row.scopes.split())
    if requested_scope:
        narrowed = set(requested_scope.split())
        if not narrowed.issubset(granted_scopes):
            return _oauth_error(
                "invalid_scope",
                "Refresh cannot widen scope beyond original grant.",
                400,
            )
        granted_scopes = narrowed

    scope_str = " ".join(sorted(granted_scopes))
    access, ttl, jti = issue_access_token(
        user_id=0,  # refresh path doesn't carry user; sub left blank intentionally
        client_id=client.client_id,
        scope=scope_str,
    )

    client.last_used_at = datetime.utcnow()
    db_session.commit()

    logger.info(
        f"[OAuth /token] refresh ok client_id={client.client_id} "
        f"jti={jti} family={new_refresh.row.family_id}"
    )

    return jsonify(
        {
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": ttl,
            "refresh_token": new_refresh.plaintext,
            "scope": scope_str,
        }
    )


# ---------------------------------------------------------------------------
# Token revocation (RFC 7009)
# ---------------------------------------------------------------------------


@mcp_oauth_bp.route("/revoke", methods=["POST"])
@limiter.limit(TOKEN_RATE_LIMIT)
def revoke_endpoint():
    """RFC 7009 — best-effort token revocation.

    Per spec, the response is always 200 regardless of whether the
    token existed. We support refresh tokens (mark revoked); access
    tokens are JWTs that expire shortly anyway, so we acknowledge but
    do not maintain a blocklist. The kill-switch admin endpoint
    (Phase 2e) revokes ALL tokens at once via revoke_all_tokens().
    """
    client, err = _authenticate_client_at_token()
    if client is None:
        return _oauth_error("invalid_client", err, 401)

    token_value = (request.form.get("token") or "").strip()
    token_type_hint = (request.form.get("token_type_hint") or "").strip()

    if not token_value:
        # RFC 7009 §2.1 — empty token is still 200.
        return ("", 200)

    # We only act on refresh tokens. Access tokens are stateless JWTs.
    if token_type_hint in ("refresh_token", ""):
        revoke_presented_refresh(
            presented_plaintext=token_value, client_id=client.client_id
        )

    return ("", 200)
