"""OAuth 2.1 persistence for the Remote MCP feature.

SCAFFOLD ONLY — schema is intentionally not yet created. Phase 2 of the
remotemcp project plan will land:

- OAuthClient    — DCR-registered clients
                   (client_id PK, client_name, redirect_uris[],
                    client_secret_hash, approved BOOL, created_at)
- OAuthRefreshToken — single-use rotated refresh tokens
                   (id PK, client_id FK, token_hash, scopes,
                    created_at, expires_at, revoked_at, last_used_at,
                    parent_token_id FK — for reuse-detection family revocation)
- OAuthSigningKey — JWKS state
                   (kid PK, algorithm, public_jwk, private_path,
                    is_active BOOL, created_at, rotated_at)

All tokens are stored hashed using the existing API_KEY_PEPPER pipeline.
Authorization codes are NOT persisted — kept in-memory with 60s TTL.

See docs/prd/remote-mcp.md for the full schema and security rationale.
"""

# Phase 2 of the remotemcp branch will move these onto the existing
# auth_db engine. Keeping a stub module here so the import surface
# is reserved and reviewers can see where state will land.
