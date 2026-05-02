"""Streamable HTTP transport for the Remote MCP feature.

SCAFFOLD ONLY — this blueprint is intentionally non-functional in this commit.
Phase 3 of the remotemcp project plan will:

- Reuse the FastMCP tool registry (extracted from mcp/mcpserver.py into
  mcp/tool_registry.py — kept in sync, single source of truth)
- Add token validation middleware that:
    * verifies RS256 JWT signature against active+previous kids in JWKS
    * checks exp, jti, scope claims
    * enforces per-token rate limits (5/min for write:orders, 60/min reads)
    * applies replay protection for write_orders via request_id
- Implement POST /mcp — JSON-RPC 2.0 dispatcher. For each tool call:
    1. extract bearer token, validate
    2. resolve tool name → required scope; reject if not granted
    3. fire pre-execution Telegram notification when scope=write:orders
    4. dispatch to tool function
    5. apply per-tool soft timeout (5s reads, 30s writes)
    6. append audit row to log/mcp.jsonl
- Implement GET /mcp — SSE event stream for server-initiated messages
- Add a CORS middleware with strict allowlist (MCP_HTTP_CORS_ORIGINS)

The blueprint is registered in app.py only when MCP_HTTP_ENABLED=True.

See docs/prd/remote-mcp.md for the full design and threat model.
"""

from flask import Blueprint, jsonify

from utils.logging import get_logger

logger = get_logger(__name__)

mcp_http_bp = Blueprint("mcp_http_bp", __name__, url_prefix="/mcp")


@mcp_http_bp.route("/_status")
def _scaffold_status():
    """Returns 501 — this blueprint is a scaffold only.

    Phase 3 of the remotemcp branch will replace this with the real
    streamable HTTP transport.
    """
    return (
        jsonify(
            {
                "status": "not_implemented",
                "message": "Remote MCP HTTP transport is scaffold-only on "
                "this commit. See docs/prd/remote-mcp.md for the "
                "implementation plan.",
            }
        ),
        501,
    )
