#!/bin/bash
# ============================================================================
# OpenAlgo Remote MCP enabler
# ============================================================================
# Run AFTER a successful install/install.sh deployment to opt the install
# into the Remote MCP feature. Same-domain mode requires no nginx changes
# (the existing `location /` block already proxies /mcp, /oauth, and
# /.well-known/oauth-* to Gunicorn).
#
# Subdomain mode is documented but NOT automated by this script — the
# manual steps are in install/Remote-MCP-readme.md and the existing
# install/change-domain.sh + Docker-Multi-SSL flows give you the
# building blocks.
#
# What this script does:
#   1. Detects an existing OpenAlgo install (.env + systemd unit)
#   2. Prompts for the public MCP URL (default: https://<your-domain>)
#   3. Adds / updates MCP_* keys in .env
#   4. Generates a fresh OAuth signing key directory if missing
#   5. Restarts the OpenAlgo service so Flask picks up the new env
#
# Defaults are deliberately conservative:
#   * MCP_OAUTH_REQUIRE_APPROVAL = True   (DCR clients land pending)
#   * MCP_OAUTH_WRITE_SCOPE_ENABLED = False (read-only out of the box)
# Flip them later by editing the .env directly and restarting.
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


# ---------------------------------------------------------------------------
# 1. Detect existing install
# ---------------------------------------------------------------------------
# install.sh creates services named openalgo-<deploy-name>. We list them
# and ask the user to pick one when there's more than one.
log "\n[1/6] Detecting existing OpenAlgo installation..." "$BLUE"
mapfile -t SERVICES < <(systemctl list-unit-files --no-legend --type=service \
    | awk '{print $1}' | grep '^openalgo-' || true)

if [[ ${#SERVICES[@]} -eq 0 ]]; then
    fail "No openalgo-* systemd services found. Run install/install.sh first."
fi

if [[ ${#SERVICES[@]} -gt 1 ]]; then
    log "Multiple OpenAlgo deployments detected:" "$YELLOW"
    for i in "${!SERVICES[@]}"; do
        printf '  [%d] %s\n' "$((i+1))" "${SERVICES[$i]}"
    done
    read -rp "Pick one [1-${#SERVICES[@]}]: " PICK
    SERVICE_NAME="${SERVICES[$((PICK-1))]}"
else
    SERVICE_NAME="${SERVICES[0]}"
fi
SERVICE_NAME="${SERVICE_NAME%.service}"
log "Service: $SERVICE_NAME" "$GREEN"

# Resolve the WorkingDirectory (where .env lives) from the unit file.
UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
[[ -f "$UNIT_FILE" ]] || fail "Unit file not found: $UNIT_FILE"
BASE_PATH=$(grep -E '^WorkingDirectory=' "$UNIT_FILE" | head -n1 | cut -d= -f2)
[[ -n "$BASE_PATH" && -d "$BASE_PATH" ]] \
    || fail "Could not resolve install directory from $UNIT_FILE"
ENV_FILE="$BASE_PATH/.env"
[[ -f "$ENV_FILE" ]] || fail "No .env at $ENV_FILE"
log "Install directory: $BASE_PATH" "$GREEN"

# Resolve install ownership ONCE here; we need it for migrations (run as
# the deploy user) and again later for chown on the keys dir. Earlier
# revisions of this script assigned OWNER only after the migrations
# block, which made `sudo -u "$OWNER_USER"` run as no user and the
# `|| log` swallow the failure — migrations silently didn't apply.
OWNER=$(stat -c '%U:%G' "$BASE_PATH" 2>/dev/null || stat -f '%Su:%Sg' "$BASE_PATH" 2>/dev/null || true)
if [[ -z "$OWNER" ]]; then
    fail "Could not determine ownership of $BASE_PATH (neither GNU nor BSD stat worked)."
fi
OWNER_USER="${OWNER%:*}"
log "Install owner: $OWNER" "$GREEN"


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
log "\n[2/6] Public MCP URL" "$BLUE"

# Best-effort default: pull the configured HOST_SERVER from the existing
# .env, fall back to deriving from SERVICE_NAME.
DEFAULT_URL=$(grep -E "^[[:space:]]*HOST_SERVER[[:space:]]*=" "$ENV_FILE" \
    | head -n1 | sed -E "s/.*=[[:space:]]*['\"]?([^'\"]+)['\"]?.*/\1/")

if [[ -z "$DEFAULT_URL" ]]; then
    # Service names are openalgo-<deploy-name> where <deploy-name> often
    # carries a broker suffix (e.g. openalgo-myzerodha-account). The old
    # heuristic of converting ALL dashes to dots produced nonsense URLs
    # like https://myzerodha.account. Leave it empty and force the
    # operator to type the right hostname rather than auto-suggest a
    # wrong one.
    DEFAULT_URL=""
fi

log "Same-domain mode (default): hosted MCP clients reach the server via the" "$YELLOW"
log "  same hostname as the dashboard. No nginx changes required." "$YELLOW"
log "Subdomain mode: see install/Remote-MCP-readme.md for the manual steps." "$YELLOW"
if [[ -n "$DEFAULT_URL" ]]; then
    read -rp "Public MCP URL [$DEFAULT_URL]: " MCP_URL
    MCP_URL="${MCP_URL:-$DEFAULT_URL}"
else
    read -rp "Public MCP URL (e.g. https://yourdomain.com): " MCP_URL
fi
MCP_URL="${MCP_URL%/}"  # strip trailing slash

if [[ -z "$MCP_URL" ]]; then
    fail "MCP URL is required."
fi
if [[ ! "$MCP_URL" =~ ^https://[A-Za-z0-9.\-]+(/.*)?$ ]]; then
    fail "MCP URL must be HTTPS. Got: $MCP_URL"
fi
log "MCP_PUBLIC_URL = $MCP_URL" "$GREEN"


# ---------------------------------------------------------------------------
# 4. Confirm the security defaults
# ---------------------------------------------------------------------------
log "\n[3/6] Security defaults" "$BLUE"
log "  MCP_OAUTH_REQUIRE_APPROVAL = True  (DCR clients require admin approval)" "$YELLOW"
log "  MCP_OAUTH_WRITE_SCOPE_ENABLED = False (read-only — no order placement via MCP)" "$YELLOW"
log "" "$NC"
log "These defaults are recommended. To enable order placement later," "$YELLOW"
log "edit $ENV_FILE manually and set MCP_OAUTH_WRITE_SCOPE_ENABLED='True'." "$YELLOW"
read -rp "Continue with defaults? [Y/n]: " GO
case "${GO,,}" in
    n|no) fail "Aborted." ;;
esac


# ---------------------------------------------------------------------------
# 5. Update the .env
# ---------------------------------------------------------------------------
log "\n[4/6] Updating $ENV_FILE..." "$BLUE"

# Helper: set OR replace a key in the env file. Uses a single-quoted
# value form (matching install.sh's existing style).
set_env() {
    local key="$1"
    local value="$2"
    if grep -qE "^[[:space:]]*${key}[[:space:]]*=" "$ENV_FILE"; then
        # Update in place. The sed pattern preserves leading whitespace
        # (none expected, but cheap insurance).
        sudo sed -i "s|^[[:space:]]*${key}[[:space:]]*=.*|${key} = '${value}'|" "$ENV_FILE"
    else
        echo "${key} = '${value}'" | sudo tee -a "$ENV_FILE" >/dev/null
    fi
}

# Backup before mutating.
BACKUP="${ENV_FILE}.pre-mcp.$(date +%Y%m%d-%H%M%S)"
sudo cp -p "$ENV_FILE" "$BACKUP"
log "Backup written to $BACKUP" "$GREEN"

set_env "MCP_HTTP_ENABLED" "True"
set_env "MCP_PUBLIC_URL" "$MCP_URL"
set_env "MCP_OAUTH_REQUIRE_APPROVAL" "True"
set_env "MCP_OAUTH_WRITE_SCOPE_ENABLED" "False"
# These are documented in .sample.env; we let them inherit defaults
# unless the operator wants to override.
log ".env updated" "$GREEN"


# ---------------------------------------------------------------------------
# 6. Ensure keys/ directory exists with chmod 700
# ---------------------------------------------------------------------------
log "\n[5/6] Running database migrations..." "$BLUE"
# Schema additions for the 2FA flag columns and OAuth tables ride
# upgrade/migrate_all.py. The systemd service started by install.sh
# does NOT call migrations on every restart (only Docker's start.sh
# does), so existing native Ubuntu users upgrading to remotemcp need
# this step. Idempotent — every individual migration short-circuits
# when already applied.
if [[ -f "$BASE_PATH/upgrade/migrate_all.py" ]]; then
    UV_BIN="$BASE_PATH/.venv/bin/uv"
    if [[ -x "$UV_BIN" ]]; then
        sudo -u "$OWNER_USER" "$UV_BIN" --project "$BASE_PATH" run python \
            "$BASE_PATH/upgrade/migrate_all.py" \
            || log "  (migration script returned non-zero — see output above)" "$YELLOW"
    elif command -v python3 >/dev/null 2>&1; then
        ( cd "$BASE_PATH" && sudo -u "$OWNER_USER" python3 upgrade/migrate_all.py ) \
            || log "  (migration script returned non-zero — see output above)" "$YELLOW"
    else
        log "Could not locate uv or python3 to run migrations. Skipping." "$YELLOW"
        log "Run manually after this script: cd $BASE_PATH && uv run python upgrade/migrate_all.py" "$YELLOW"
    fi
else
    log "  (migration script not found — branch may predate it)" "$YELLOW"
fi


log "\n[6/6] Preparing keys/ directory and restarting service..." "$BLUE"
KEYS_DIR="$BASE_PATH/keys"
if [[ ! -d "$KEYS_DIR" ]]; then
    sudo mkdir -p "$KEYS_DIR"
    log "Created $KEYS_DIR" "$GREEN"
fi
sudo chmod 700 "$KEYS_DIR"
# OWNER was resolved at the top of the script.
sudo chown "$OWNER" "$KEYS_DIR"

# Restart the service so Flask picks up the new env. The MCP blueprint
# auto-generates the RS256 signing key on first request — we don't need
# to pre-generate.
sudo systemctl restart "$SERVICE_NAME"
sleep 2

if ! sudo systemctl is-active --quiet "$SERVICE_NAME"; then
    log "Service failed to come up after restart." "$RED"
    log "Check: sudo journalctl -u $SERVICE_NAME -n 80 --no-pager" "$RED"
    log "Your previous .env was backed up to $BACKUP — restore with:" "$YELLOW"
    log "  sudo cp '$BACKUP' '$ENV_FILE' && sudo systemctl restart $SERVICE_NAME" "$YELLOW"
    exit 1
fi


# ---------------------------------------------------------------------------
# Smoke checks
# ---------------------------------------------------------------------------
log "\nVerifying endpoints..." "$BLUE"
sleep 1

probe() {
    local label="$1"
    local url="$2"
    local code
    code=$(curl -ks -o /dev/null -w '%{http_code}' --max-time 5 "$url" || echo "000")
    if [[ "$code" =~ ^(200|401|403)$ ]]; then
        log "  ✓ ${label}  → ${code}" "$GREEN"
    else
        log "  ✗ ${label}  → ${code}" "$RED"
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
cat <<EOF

$(printf '%b' "${GREEN}=========================================================${NC}")
$(printf '%b' "${GREEN} Remote MCP enabled successfully${NC}")
$(printf '%b' "${GREEN}=========================================================${NC}")

  Public URL: $MCP_URL/mcp
  Discovery : $MCP_URL/.well-known/oauth-authorization-server
  Audit log : $BASE_PATH/log/mcp.jsonl

  Next steps for connecting from a hosted client (claude.ai, chatgpt.com):
    1. Point your client at $MCP_URL/mcp as the MCP server URL
    2. Complete the OAuth dance — DCR happens automatically
    3. Approve the new client at /admin/oauth-clients (admin UI in
       progress; until then flip approved=True in db/openalgo.db)
    4. Sign in to OpenAlgo to authorize the requested scopes

  Order placement is OFF by default. To enable:
    sudo sed -i "s|MCP_OAUTH_WRITE_SCOPE_ENABLED.*|MCP_OAUTH_WRITE_SCOPE_ENABLED = 'True'|" $ENV_FILE
    sudo systemctl restart $SERVICE_NAME
    Then re-authorize the client (OAuth tokens don't grow scope on refresh).

  See install/Remote-MCP-readme.md for the full design + threat model.
EOF
