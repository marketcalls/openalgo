"""OAuth 2.1 authorization server for the Remote MCP feature.

SCAFFOLD ONLY — this blueprint is intentionally non-functional in this commit.
Phase 2 of the remotemcp project plan will:

- Wire Authlib's authorization server (RS256, PKCE-only)
- Add discovery endpoints (/.well-known/oauth-authorization-server,
  /.well-known/oauth-protected-resource)
- Implement DCR (with admin-approval gate via MCP_OAUTH_REQUIRE_APPROVAL)
- Implement /oauth/authorize (gated by @check_session_validity + fresh TOTP
  for write:orders scope per docs/prd/remote-mcp.md)
- Implement /oauth/token, /oauth/revoke
- Persist client + refresh token state via database/oauth_db.py

The blueprint is registered in app.py only when MCP_HTTP_ENABLED=True.
Pre-flight refusal: if FLASK_DEBUG=True AND MCP_HTTP_ENABLED=True, app
startup must fail — debug mode leaks tokens via tracebacks.

See docs/prd/remote-mcp.md for the full design and threat model.
"""

from flask import Blueprint, jsonify

from utils.logging import get_logger

logger = get_logger(__name__)

mcp_oauth_bp = Blueprint("mcp_oauth_bp", __name__, url_prefix="/oauth")


@mcp_oauth_bp.route("/_status")
def _scaffold_status():
    """Returns 501 — this blueprint is a scaffold only.

    Phase 2 of the remotemcp branch will replace this with the real OAuth
    endpoints. The route exists so integration tests can confirm the
    blueprint is wired and that registration is gated by
    MCP_HTTP_ENABLED, without yet exposing a real OAuth surface.
    """
    return (
        jsonify(
            {
                "status": "not_implemented",
                "message": "Remote MCP OAuth is scaffold-only on this commit. "
                "See docs/prd/remote-mcp.md for the implementation plan.",
            }
        ),
        501,
    )
