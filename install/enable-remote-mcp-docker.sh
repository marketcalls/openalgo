#!/bin/bash
# ============================================================================
# OpenAlgo Remote MCP enabler — Docker variant
# ============================================================================
# Run AFTER a successful install via install-docker.sh or
# install-docker-multi-custom-ssl.sh. Detects Docker Compose stacks
# under /opt/openalgo/<domain>/ (or a path you provide), edits the
# bind-mounted .env, restarts the container.
#
# Database migrations:
#   The Docker container's start.sh ALREADY runs migrate_all.py on
#   every container start, so you don't need to run them separately
#   here — restarting the container picks them up. This is the one
#   advantage Docker has over the native install path on upgrades.
#
# What this script does:
#   1. Detect Docker Compose stacks under /opt/openalgo (default)
#   2. Pick one (or run for all in batch mode)
#   3. Backs up the per-instance .env
#   4. Adds / updates MCP_* keys in .env
#   5. docker compose restart for the picked instance
#   6. Smoke-probes the OAuth + MCP endpoints over the public domain
#
# Defaults:
#   * MCP_OAUTH_REQUIRE_APPROVAL = True
#   * MCP_OAUTH_WRITE_SCOPE_ENABLED = False
#   * MCP_HTTP_CORS_ORIGINS = "https://claude.ai,https://chatgpt.com"
# Edit the .env afterwards to flip these if your deployment requires.
# ============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { printf '%b\n' "${2:-$NC}$1$NC"; }
fail() { log "$1" "$RED"; exit 1; }


# ---------------------------------------------------------------------------
# 0. Sanity
# ---------------------------------------------------------------------------
if [[ $EUID -ne 0 ]]; then
    fail "Please run this script with sudo."
fi

if ! command -v docker >/dev/null 2>&1; then
    fail "docker is not installed. This script targets Docker installs only."
fi

if ! docker compose version >/dev/null 2>&1; then
    fail "'docker compose' (v2 plugin) is not available. Update your Docker Engine."
fi


# ---------------------------------------------------------------------------
# 1. Discover Docker Compose stacks
# ---------------------------------------------------------------------------
INSTALL_BASE="${INSTALL_BASE:-/opt/openalgo}"

log "\n[1/5] Detecting OpenAlgo Docker stacks..." "$BLUE"
log "Looking under: $INSTALL_BASE" "$YELLOW"

mapfile -t STACK_DIRS < <(find "$INSTALL_BASE" -maxdepth 2 -name "docker-compose.yaml" -o -name "docker-compose.yml" 2>/dev/null \
    | xargs -I {} dirname {} | sort -u)

if [[ ${#STACK_DIRS[@]} -eq 0 ]]; then
    fail "No docker-compose.{yaml,yml} files found under $INSTALL_BASE.
Either you installed elsewhere — re-run with INSTALL_BASE=/your/path
in front of the script — or you haven't run install-docker.sh /
install-docker-multi-custom-ssl.sh yet."
fi

# Pick a single stack; multi-instance setups can re-run this script
# for each one. (A future enhancement could batch-enable all of them.)
if [[ ${#STACK_DIRS[@]} -gt 1 ]]; then
    log "Multiple Docker stacks detected:" "$YELLOW"
    for i in "${!STACK_DIRS[@]}"; do
        printf '  [%d] %s\n' "$((i+1))" "${STACK_DIRS[$i]}"
    done
    read -rp "Pick one [1-${#STACK_DIRS[@]}]: " PICK
    # Validate: must be a positive integer in range. Empty or non-numeric
    # input would otherwise resolve to ${STACK_DIRS[-1]} (last element)
    # silently selecting the wrong deployment.
    if ! [[ "$PICK" =~ ^[1-9][0-9]*$ ]] || (( PICK > ${#STACK_DIRS[@]} )); then
        fail "Invalid selection: $PICK. Must be 1..${#STACK_DIRS[@]}."
    fi
    STACK_DIR="${STACK_DIRS[$((PICK-1))]}"
else
    STACK_DIR="${STACK_DIRS[0]}"
fi
[[ -d "$STACK_DIR" ]] || fail "Picked stack directory does not exist: $STACK_DIR"
log "Stack: $STACK_DIR" "$GREEN"

# Each install-docker* script bind-mounts .env from the stack
# directory into /app/.env in the container.
ENV_FILE="$STACK_DIR/.env"
[[ -f "$ENV_FILE" ]] || fail "No .env at $ENV_FILE — install scripts should have created one."


# ---------------------------------------------------------------------------
# 2. Pre-flight: refuse if FLASK_DEBUG=True
# ---------------------------------------------------------------------------
if grep -qE "^[[:space:]]*FLASK_DEBUG[[:space:]]*=[[:space:]]*['\"]?[Tt]rue" "$ENV_FILE"; then
    log "\nFLASK_DEBUG=True is set in $ENV_FILE." "$RED"
    log "Remote MCP refuses to start in debug mode (token leak risk via" "$RED"
    log "Werkzeug tracebacks). Set FLASK_DEBUG=False, then retry." "$RED"
    exit 1
fi


# ---------------------------------------------------------------------------
# 3. Determine the public URL
# ---------------------------------------------------------------------------
log "\n[2/5] Public MCP URL" "$BLUE"

# install-docker-multi-custom-ssl.sh names the stack directory after
# the domain (/opt/openalgo/<domain>/), so derive the suggested
# public URL from the path. Fall back to HOST_SERVER in .env when the
# layout differs.
GUESSED_DOMAIN=$(basename "$STACK_DIR")
if [[ "$GUESSED_DOMAIN" =~ \. ]]; then
    DEFAULT_URL="https://$GUESSED_DOMAIN"
else
    DEFAULT_URL=""
fi

if [[ -z "$DEFAULT_URL" ]]; then
    DEFAULT_URL=$(grep -E "^[[:space:]]*HOST_SERVER[[:space:]]*=" "$ENV_FILE" \
        | head -n1 | sed -E "s/.*=[[:space:]]*['\"]?([^'\"]+)['\"]?.*/\1/")
fi

log "Same-domain mode: hosted MCP clients reach the server via the same" "$YELLOW"
log "  hostname as the dashboard. The existing nginx config that fronts" "$YELLOW"
log "  this Docker container already proxies /mcp, /oauth, and" "$YELLOW"
log "  /.well-known/oauth-* — no extra config required." "$YELLOW"
read -rp "Public MCP URL [$DEFAULT_URL]: " MCP_URL
MCP_URL="${MCP_URL:-$DEFAULT_URL}"
MCP_URL="${MCP_URL%/}"

if [[ ! "$MCP_URL" =~ ^https://[A-Za-z0-9.\-]+(/.*)?$ ]]; then
    fail "MCP URL must be HTTPS. Got: $MCP_URL"
fi
log "MCP_PUBLIC_URL = $MCP_URL" "$GREEN"


# ---------------------------------------------------------------------------
# 4. Confirm security defaults
# ---------------------------------------------------------------------------
log "\n[3/5] Security defaults" "$BLUE"
log "  MCP_OAUTH_REQUIRE_APPROVAL = True  (DCR clients require admin approval)" "$YELLOW"
log "  MCP_OAUTH_WRITE_SCOPE_ENABLED = False (read-only — no order placement via MCP)" "$YELLOW"
log "" "$NC"
log "Edit $ENV_FILE manually to flip these later. To enable order" "$YELLOW"
log "placement: set MCP_OAUTH_WRITE_SCOPE_ENABLED='True' and re-restart" "$YELLOW"
log "the container. Re-authorize the MCP client afterwards." "$YELLOW"
read -rp "Continue with defaults? [Y/n]: " GO
case "${GO,,}" in
    n|no) fail "Aborted." ;;
esac


# ---------------------------------------------------------------------------
# 5. Update the .env
# ---------------------------------------------------------------------------
log "\n[4/5] Updating $ENV_FILE..." "$BLUE"

set_env() {
    local key="$1"
    local value="$2"
    if grep -qE "^[[:space:]]*${key}[[:space:]]*=" "$ENV_FILE"; then
        sed -i "s|^[[:space:]]*${key}[[:space:]]*=.*|${key} = '${value}'|" "$ENV_FILE"
    else
        echo "${key} = '${value}'" >> "$ENV_FILE"
    fi
}

BACKUP="${ENV_FILE}.pre-mcp.$(date +%Y%m%d-%H%M%S)"
cp -p "$ENV_FILE" "$BACKUP"
log "Backup written to $BACKUP" "$GREEN"

set_env "MCP_HTTP_ENABLED" "True"
set_env "MCP_PUBLIC_URL" "$MCP_URL"
set_env "MCP_OAUTH_REQUIRE_APPROVAL" "True"
set_env "MCP_OAUTH_WRITE_SCOPE_ENABLED" "False"
# Default CORS allowlist for the two main hosted clients. Edit if you
# only need one or want to add more (mobile etc.).
if ! grep -qE "^[[:space:]]*MCP_HTTP_CORS_ORIGINS[[:space:]]*=" "$ENV_FILE"; then
    set_env "MCP_HTTP_CORS_ORIGINS" "https://claude.ai,https://chatgpt.com"
fi

# Match the bind-mount's expected ownership (Docker container runs as
# UID 1000). install-docker-multi-custom-ssl.sh already chown 1000
# the .env after fresh creation — preserving that on update.
chown 1000:1000 "$ENV_FILE" 2>/dev/null || true
chmod 600 "$ENV_FILE"
log ".env updated" "$GREEN"


# ---------------------------------------------------------------------------
# 6. Restart container
# ---------------------------------------------------------------------------
log "\n[5/5] Restarting Docker stack..." "$BLUE"
# The container's start.sh runs migrate_all.py before gunicorn — schema
# changes (2FA flag columns) apply automatically on this restart.
( cd "$STACK_DIR" && docker compose restart ) \
    || fail "docker compose restart failed. Check: cd $STACK_DIR && docker compose logs --tail=80"

# Give Gunicorn a moment to come up before probing.
sleep 4

# Confirm the container is healthy.
HEALTH=$(cd "$STACK_DIR" && docker compose ps --format json 2>/dev/null \
    | grep -oE '"State":"[^"]+"' | head -n1 || true)
if [[ -z "$HEALTH" ]] || [[ "$HEALTH" != *"running"* ]]; then
    log "Container did not return to running state after restart." "$RED"
    log "Inspect: cd $STACK_DIR && docker compose logs --tail=80" "$RED"
    log "Roll back .env with: cp '$BACKUP' '$ENV_FILE' && cd $STACK_DIR && docker compose restart" "$YELLOW"
    exit 1
fi


# ---------------------------------------------------------------------------
# Smoke checks
# ---------------------------------------------------------------------------
log "\nVerifying endpoints..." "$BLUE"
sleep 1

PROBE_FAILURES=0

probe() {
    local label="$1"
    local url="$2"
    local code
    # Drop -k so an invalid TLS cert is reported as a smoke-probe failure
    # rather than a silent pass. The whole point of probing the public
    # URL is to validate that the deployment is reachable from outside.
    code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 "$url" 2>/dev/null || echo "000")
    if [[ "$code" =~ ^(200|401|403)$ ]]; then
        log "  ✓ ${label}  → ${code}" "$GREEN"
    else
        log "  ✗ ${label}  → ${code}" "$RED"
        PROBE_FAILURES=$((PROBE_FAILURES + 1))
    fi
}

probe "OAuth discovery" "$MCP_URL/.well-known/oauth-authorization-server"
probe "Resource metadata" "$MCP_URL/.well-known/oauth-protected-resource"
probe "JWKS"             "$MCP_URL/oauth/jwks.json"
probe "MCP healthz"      "$MCP_URL/mcp/healthz"
probe "MCP (no token)"   "$MCP_URL/mcp"  # expect 401


# ---------------------------------------------------------------------------
# Closing message
# ---------------------------------------------------------------------------
if (( PROBE_FAILURES > 0 )); then
    log "" "$NC"
    log "$PROBE_FAILURES smoke probe(s) failed. Common causes:" "$RED"
    log "  - DNS for $MCP_URL not yet resolving (or wrong hostname)" "$RED"
    log "  - HTTPS certificate not yet issued / not trusted from this host" "$RED"
    log "  - Reverse proxy not yet routing /mcp + /oauth/* + /.well-known/*" "$RED"
    log "  - Container still booting; retry in a few seconds" "$RED"
    log "Roll back .env with: cp '$BACKUP' '$ENV_FILE' && cd $STACK_DIR && docker compose restart" "$YELLOW"
    exit 1
fi

cat <<EOF

$(printf '%b' "${GREEN}=========================================================${NC}")
$(printf '%b' "${GREEN} Remote MCP enabled successfully (Docker)${NC}")
$(printf '%b' "${GREEN}=========================================================${NC}")

  Public URL: $MCP_URL/mcp
  Discovery : $MCP_URL/.well-known/oauth-authorization-server
  Audit log : ${STACK_DIR}/log/mcp.jsonl  (Docker volume — see docker compose logs)
  Stack     : $STACK_DIR

  Next steps for connecting from a hosted client (claude.ai, chatgpt.com):
    1. Point your client at $MCP_URL/mcp
    2. Complete the OAuth dance — DCR happens automatically
    3. Approve the new client at /admin/remote-mcp on the dashboard
       (sign in to OpenAlgo first)
    4. Sign in to OpenAlgo when prompted to authorize the requested scopes

  Order placement is OFF by default. To enable on this instance:
    sudo sed -i "s|MCP_OAUTH_WRITE_SCOPE_ENABLED.*|MCP_OAUTH_WRITE_SCOPE_ENABLED = 'True'|" $ENV_FILE
    cd $STACK_DIR && docker compose restart
    Then re-authorize the client (OAuth tokens don't grow scope on refresh).

  For multi-instance deployments, re-run this script and pick a different
  stack each time — each instance gets its own OAuth signing keys + tables.

  See install/Remote-MCP-readme.md for the full design + threat model.
EOF
