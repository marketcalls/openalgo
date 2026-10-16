#!/bin/bash

# OpenAlgo Docker Multi-Instance Installation with Custom SSL
# Supports deploying multiple instances with existing SSL certificates (including Wildcards)

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Base Configuration
INSTALL_BASE="/opt/openalgo"
START_FLASK_PORT=5000
START_WS_PORT=8765
# Overridable so the deployment failure path can be exercised by tests without
# writing to the real Nginx configuration.
NGINX_SITES_AVAILABLE="${NGINX_SITES_AVAILABLE:-/etc/nginx/sites-available}"
NGINX_SITES_ENABLED="${NGINX_SITES_ENABLED:-/etc/nginx/sites-enabled}"

# Script Banner
echo -e "${BLUE}"
echo "  ██████╗ ██████╗ ███████╗███╗   ██╗ █████╗ ██╗      ██████╗  ██████╗ "
echo " ██╔═══██╗██╔══██╗██╔════╝████╗  ██║██╔══██╗██║     ██╔════╝ ██╔═══██╗"
echo " ██║   ██║██████╔╝███████╗██╔██╗ ██║███████║██║     ██║  ███╗██║   ██║"
echo " ██║   ██║██╔═══╝ ██╔══╝  ██║╚██╗██║██╔══██║██║     ██║   ██║██║   ██║"
echo " ╚██████╔╝██╗     ███████╗██║ ╚████║██║  ██║███████╗╚██████╔╝╚██████╔╝"
echo "  ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═══╝╚═╝  ╚═╝╚══════╝ ╚═════╝  ╚═════╝ "
echo "             MULTI-INSTANCE DOCKER + CUSTOM SSL INSTALLER               "
echo -e "${NC}"

# -----------------
# Helper Functions
# -----------------

log() {
    echo -e "${2}${1}${NC}"
}

check_status() {
    if [ $? -ne 0 ]; then
        log "Error: $1" "$RED"
        exit 1
    fi
}

generate_hex() {
    python3 -c "import secrets; print(secrets.token_hex(32))"
}

validate_broker() {
    local broker=$1
    local valid_brokers="fivepaisa,fivepaisaxts,aliceblue,angel,arrow,compositedge,definedge,deltaexchange,dhan,dhan_sandbox,firstock,flattrade,fyers,groww,hdfcsecurities,hdfcsky,ibulls,iifl,iiflcapital,indmoney,jainamxts,kotak,motilal,mstock,nubra,paytm,pocketful,rmoney,rupeezy,samco,shoonya,tradejini,tradesmart,upstox,wisdom,zebu,zerodha"
    [[ ",$valid_brokers," == *",$broker,"* ]]
}

is_xts_broker() {
    local broker=$1
    local xts_brokers="fivepaisaxts,compositedge,ibulls,iifl,jainamxts,rmoney,wisdom"
    if [[ ",$xts_brokers," == *",$broker,"* ]]; then
        return 0
    else
        return 1
    fi
}

sanitize_domain() {
    echo "$1" | tr '.' '-'
}

# Host ports an instance is already published on, read from the compose file
# this installer generated ("127.0.0.1:<flask>:5000" / "127.0.0.1:<ws>:8765").
# The repository ships its own docker-compose.yaml with "${FLASK_PORT:-5000}"
# mappings; those never match, so a pristine checkout reports nothing.
compose_ports() {
    local file="$1" f w
    [ -f "$file" ] || return 1
    f=$(grep -oE '127\.0\.0\.1:[0-9]+:5000' "$file" | head -1 | cut -d: -f2)
    w=$(grep -oE '127\.0\.0\.1:[0-9]+:8765' "$file" | head -1 | cut -d: -f2)
    [ -n "$f" ] && [ -n "$w" ] && echo "$f $w"
}

# The same pair from an Nginx vhost this installer generated: its two upstream
# blocks name the flask port first and the websocket port second.
vhost_ports() {
    local file="$1" ports
    [ -f "$file" ] || return 1
    ports=$(grep -oE 'server 127\.0\.0\.1:[0-9]+' "$file" | head -2 | cut -d: -f2 | tr '\n' ' ')
    [ "$(echo "$ports" | wc -w)" -eq 2 ] && echo $ports
}

get_next_ports() {
    # Highest ports used by any installed instance, plus one. Only compose
    # files this installer generated count (see compose_ports), and only the
    # ones directly inside an instance directory.
    local max_flask=$((START_FLASK_PORT - 1))
    local max_ws=$((START_WS_PORT - 1))
    local file ports f_port w_port

    if [ -d "$INSTALL_BASE" ]; then
        while IFS= read -r file; do
            ports=$(compose_ports "$file") || continue
            f_port=${ports% *}
            w_port=${ports#* }
            [ "$f_port" -gt "$max_flask" ] && max_flask=$f_port
            [ "$w_port" -gt "$max_ws" ] && max_ws=$w_port
        done < <(find "$INSTALL_BASE" -mindepth 2 -maxdepth 2 -name docker-compose.yaml)
    fi

    echo "$((max_flask + 1)) $((max_ws + 1))"
}

# Ports for one instance. An instance that is already deployed keeps the ports
# it has: allocating "highest + 1" on every update moved it to a fresh pair each
# time, so the container, its compose file and its Nginx vhost drifted apart
# whenever a run stopped part way. Order: the compose file, then the Nginx
# vhost (which survives a compose file the repository overwrote), then new.
resolve_instance_ports() {
    local domain="$1" ports
    ports=$(compose_ports "$INSTALL_BASE/$domain/docker-compose.yaml") && { echo "$ports"; return 0; }
    ports=$(compose_ports "$(compose_snapshot_path "$domain")") && { echo "$ports"; return 0; }
    ports=$(vhost_ports "$NGINX_SITES_AVAILABLE/$domain") && { echo "$ports"; return 0; }
    get_next_ports
}

# An instance's reachability depends on two generated files agreeing: the port
# mappings in its compose file, and the upstreams in its Nginx vhost. Both are
# rewritten before the image is built, and the single Nginx reload at the end of
# the run activates whatever is on disk by then. When a build fails we skip
# `docker compose up -d`, so the running container keeps the ports it already
# had -- and without putting these files back, that reload would point the
# domain at ports nothing is listening on, taking a working instance offline.
# The compose snapshot lives outside the instance directory. That directory is
# the Docker build context (`COPY . .`), and a snapshot inside it changes on
# every run -- it is the previous run's compose file -- so the layer never
# stayed cached and a run that changed nothing still rebuilt and recreated the
# container.
compose_snapshot_path() {
    echo "$INSTALL_BASE/.deploy-snapshots/$1.docker-compose.yaml.pre-deploy"
}

snapshot_instance_config() {
    local instance_dir="$1" domain="$2"
    discard_instance_snapshot "$instance_dir" "$domain"
    if [ -f "$instance_dir/docker-compose.yaml" ]; then
        mkdir -p "$INSTALL_BASE/.deploy-snapshots"
        cp -p "$instance_dir/docker-compose.yaml" "$(compose_snapshot_path "$domain")"
    fi
    if [ -f "$NGINX_SITES_AVAILABLE/$domain" ]; then
        cp -p "$NGINX_SITES_AVAILABLE/$domain" "$NGINX_SITES_AVAILABLE/$domain.pre-deploy"
    fi
    return 0
}

restore_instance_config() {
    local instance_dir="$1" domain="$2"
    if [ -f "$(compose_snapshot_path "$domain")" ]; then
        mv -f "$(compose_snapshot_path "$domain")" "$instance_dir/docker-compose.yaml"
    fi
    if [ -f "$NGINX_SITES_AVAILABLE/$domain.pre-deploy" ]; then
        mv -f "$NGINX_SITES_AVAILABLE/$domain.pre-deploy" "$NGINX_SITES_AVAILABLE/$domain"
    else
        # Fresh install: there is no working configuration to return to, so
        # leave no vhost behind pointing at a port that will never be served.
        rm -f "$NGINX_SITES_ENABLED/$domain" "$NGINX_SITES_AVAILABLE/$domain"
    fi
    return 0
}

discard_instance_snapshot() {
    local instance_dir="$1" domain="$2"
    rm -f "$(compose_snapshot_path "$domain")" \
          "$NGINX_SITES_AVAILABLE/$domain.pre-deploy"
    return 0
}

# -----------------
# Per-instance options: memory profile, web server, build network
# -----------------

# Memory profile. The numbers below used to be computed once per run from the
# domains typed in that run. They are now chosen per instance:
#   auto          the original sizing, from RAM divided by the instances in
#                 this run (3 tiers; a strategy gets 256, 512 or 1024 MB)
#   unrestricted  for hosts running many or large strategy scripts: each
#                 strategy may use up to STRATEGY_MEM_LIMIT_MB (default 3072),
#                 shm at its 1024 MB ceiling, threads from the core count
#                 alone, and no container memory limit
# STRATEGY_MEMORY_LIMIT_MB is an address-space cap (RLIMIT_AS) on each Python
# strategy process, not on the container; the container itself has no memory
# limit in either profile unless OPENALGO_CONTAINER_MEM_MB is set.
DEFAULT_UNRESTRICTED_STRATEGY_MB=3072

compute_resources() {
    local profile="$1" total_ram="$2" cores="$3" instances="$4"
    local per_instance cores_per
    [ "$instances" -lt 1 ] && instances=1
    per_instance=$((total_ram / instances))
    RAM_PER_INSTANCE=$per_instance

    SHM_SIZE_MB=$((per_instance / 4))
    [ $SHM_SIZE_MB -lt 128 ] && SHM_SIZE_MB=128
    [ $SHM_SIZE_MB -gt 1024 ] && SHM_SIZE_MB=1024

    if [ "$profile" = "unrestricted" ]; then
        SHM_SIZE_MB=1024
        THREAD_LIMIT=$cores
        [ $THREAD_LIMIT -lt 2 ] && THREAD_LIMIT=2
        [ $THREAD_LIMIT -gt 4 ] && THREAD_LIMIT=4
        STRATEGY_MEM_LIMIT=${STRATEGY_MEM_LIMIT_MB:-$DEFAULT_UNRESTRICTED_STRATEGY_MB}
        return 0
    fi

    # auto: <2GB: 1 thread | 2-4GB: 2 threads | 4GB+: max(2, min(4, cores/instances))
    if [ $per_instance -lt 2000 ]; then
        THREAD_LIMIT=1
        STRATEGY_MEM_LIMIT=256
    elif [ $per_instance -lt 4000 ]; then
        THREAD_LIMIT=2
        STRATEGY_MEM_LIMIT=512
    else
        cores_per=$((cores / instances))
        THREAD_LIMIT=$((cores_per < 2 ? 2 : cores_per))
        [ $THREAD_LIMIT -gt 4 ] && THREAD_LIMIT=4
        STRATEGY_MEM_LIMIT=1024
    fi
}

valid_memory_profile() { [ "$1" = "auto" ] || [ "$1" = "unrestricted" ]; }
valid_worker_class() { [ "$1" = "eventlet" ] || [ "$1" = "gthread" ]; }

# The installer keeps its own per-instance choices out of .env, which the
# application reads.
INSTALLER_CONF_NAME=".installer.conf"

read_instance_profile() {
    local conf="$INSTALL_BASE/$1/$INSTALLER_CONF_NAME" value=""
    [ -f "$conf" ] && value=$(sed -n 's/^MEMORY_PROFILE=//p' "$conf" | head -1)
    valid_memory_profile "$value" && echo "$value" || echo "auto"
}

write_instance_profile() {
    local conf="$1/$INSTALLER_CONF_NAME"
    printf 'MEMORY_PROFILE=%s\n' "$2" > "$conf"
}

# The web server an instance's .env asks for. OpenAlgo runs eventlet unless
# OPENALGO_WORKER_CLASS = 'gthread' is set (docs/gthread/README.md).
read_worker_class() {
    local env_file="$1" value=""
    [ -f "$env_file" ] && value=$(grep -E "^[[:space:]]*OPENALGO_WORKER_CLASS[[:space:]]*=" "$env_file" | tail -1 | cut -d= -f2- | tr -d " '\"")
    valid_worker_class "$value" && echo "$value" || echo "eventlet"
}

# Idempotent: drops any active OPENALGO_WORKER_CLASS line (the commented-out
# one in .sample.env stays as documentation) and appends one. Written through
# cat so the file keeps its owner and mode.
set_env_value() {
    local env_file="$1" key="$2" value="$3" tmp
    tmp=$(mktemp)
    grep -vE "^[[:space:]]*${key}[[:space:]]*=" "$env_file" > "$tmp"
    printf "%s = '%s'\n" "$key" "$value" >> "$tmp"
    cat "$tmp" > "$env_file"
    rm -f "$tmp"
}

set_worker_class() {
    set_env_value "$1" OPENALGO_WORKER_CLASS "$2"
}

# The diagnostics page reports the commit and branch the instance was built
# from (issue #1388). .git/ is dockerignored, so the container cannot read
# them itself; they are refreshed on every run from the checkout the image was
# just built from.
set_git_info() {
    local instance_dir="$1" env_file="$2" branch commit
    branch=$(cd "$instance_dir" && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
    commit=$(cd "$instance_dir" && git rev-parse --short HEAD 2>/dev/null || echo "")
    set_env_value "$env_file" OPENALGO_GIT_BRANCH "$branch"
    set_env_value "$env_file" OPENALGO_GIT_COMMIT "$commit"
}

# Switching restarts the container: strategies and market data pause for up to
# a minute. The gthread guide says to switch after 23:30 IST and before 09:00.
# OPENALGO_NOW_HHMM lets tests set the clock.
in_trading_hours() {
    local hhmm="${OPENALGO_NOW_HHMM:-$(TZ=Asia/Kolkata date +%H%M)}"
    hhmm=$((10#$hhmm))
    [ "$hhmm" -ge 900 ] && [ "$hhmm" -lt 2330 ]
}

# Ask which web server an instance should use. Echoes the choice. Reads the
# answer from stdin; Enter keeps the current one. A change inside trading
# hours needs an explicit yes (FORCE_WORKER_SWITCH=1 skips the question).
choose_worker_class() {
    local domain="$1" current="$2" mode="${3:-existing}" answer confirm
    answer="${INSTALL_WORKER_CLASS:-}"
    if [ -z "$answer" ]; then
        read -r -p "Web server for $domain [eventlet/gthread] (current: $current, Enter keeps it): " answer </dev/stdin
    fi
    answer="${answer:-$current}"
    if ! valid_worker_class "$answer"; then
        log "Unknown web server '$answer'; keeping $current." "$YELLOW" >&2
        echo "$current"; return 0
    fi
    if [ "$mode" != "new" ] && [ "$answer" != "$current" ] && in_trading_hours && [ "${FORCE_WORKER_SWITCH:-0}" != "1" ]; then
        log "Switching $domain from $current to $answer restarts it; strategies and market data pause for up to a minute." "$YELLOW" >&2
        log "The gthread guide asks for 23:30-09:00 IST. It is trading time now." "$YELLOW" >&2
        read -r -p "Switch now anyway? (yes/no): " confirm </dev/stdin
        if [ "$confirm" != "yes" ]; then
            log "Keeping $current for $domain." "$YELLOW" >&2
            echo "$current"; return 0
        fi
    fi
    echo "$answer"
}

choose_memory_profile() {
    local domain="$1" current="$2" answer
    answer="${INSTALL_MEMORY_PROFILE:-}"
    if [ -z "$answer" ]; then
        read -r -p "Memory profile for $domain [auto/unrestricted] (current: $current, Enter keeps it): " answer </dev/stdin
    fi
    answer="${answer:-$current}"
    if ! valid_memory_profile "$answer"; then
        log "Unknown memory profile '$answer'; keeping $current." "$YELLOW" >&2
        echo "$current"; return 0
    fi
    echo "$answer"
}

# Optional pin of files.pythonhosted.org to one CDN edge, written into the
# build's extra_hosts. PyPI is served by Fastly; from some networks one edge is
# fast and the others crawl (a 16 MB wheel at 20 KB/s timed the build out).
#   PYPI_EDGE_IP=<address>  pin to that address
#   PYPI_EDGE_IP=auto       time each known edge and pin the fastest, only when
#                           the DNS answer is slow; otherwise do nothing
# Unset leaves DNS alone. A pin is a workaround: remove it when routing heals.
PYPI_EDGE_CANDIDATES="151.101.0.223 151.101.64.223 151.101.128.223 151.101.192.223"

# Bytes per second for the first ~2 MB of one PyPI file through one address.
# $2 empty means "use DNS as the machine does".
probe_pypi_speed() {
    local url="$1" ip="$2" resolve=()
    [ -n "$ip" ] && resolve=(--resolve "files.pythonhosted.org:443:$ip")
    curl -4 -s -o /dev/null -r 0-2000000 -m 10 -w '%{speed_download}' "${resolve[@]}" "$url" 2>/dev/null | cut -d. -f1
}

pypi_probe_url() {
    curl -4 -s -m 15 https://pypi.org/pypi/uv/json 2>/dev/null | python3 -c "
import sys, json
try:
    urls = json.load(sys.stdin)['urls']
    print(next(u['url'] for u in urls if u['filename'].endswith('.whl')))
except Exception:
    pass
"
}

select_pypi_edge() {
    local setting="${PYPI_EDGE_IP:-}" url base ip speed best_ip="" best=0
    case "$setting" in
        "") return 0 ;;
        auto) ;;
        *) echo "$setting"; return 0 ;;
    esac
    url=$(pypi_probe_url)
    [ -n "$url" ] || return 0
    base=$(probe_pypi_speed "$url" "")
    # DNS is fine: leave it alone.
    if [ "${base:-0}" -ge 500000 ]; then return 0; fi
    for ip in $PYPI_EDGE_CANDIDATES; do
        speed=$(probe_pypi_speed "$url" "$ip")
        if [ "${speed:-0}" -gt "$best" ]; then best=$speed; best_ip=$ip; fi
    done
    # Pin only for a clear win, so a transient blip does not pin a bad edge.
    if [ -n "$best_ip" ] && [ "$best" -ge $((${base:-0} * 5)) ] && [ "$best" -ge 500000 ]; then
        echo "$best_ip"
    fi
}

# Writes an instance's compose file from the variables set by the deploy loop:
# PROJECT_NAME FLASK_PORT WS_PORT THREAD_LIMIT STRATEGY_MEM_LIMIT SHM_SIZE_MB,
# plus the optional PYPI_EDGE_PIN and OPENALGO_CONTAINER_MEM_MB.
write_instance_compose() {
    local target="$1"
    BUILD_EXTRA_HOSTS_YAML=""
    if [ -n "${PYPI_EDGE_PIN:-}" ]; then
        BUILD_EXTRA_HOSTS_YAML="      extra_hosts:
        - \"files.pythonhosted.org:${PYPI_EDGE_PIN}\"
"
    fi
    MEM_LIMIT_YAML=""
    if [ -n "${OPENALGO_CONTAINER_MEM_MB:-}" ]; then
        MEM_LIMIT_YAML="    mem_limit: ${OPENALGO_CONTAINER_MEM_MB}m
"
    fi
    cat <<EOF > "$target"
services:
  openalgo:
    image: ${PROJECT_NAME}:latest
    build:
      context: .
      dockerfile: Dockerfile
${BUILD_EXTRA_HOSTS_YAML}    container_name: ${PROJECT_NAME}-web
    ports:
      - "127.0.0.1:${FLASK_PORT}:5000"
      - "127.0.0.1:${WS_PORT}:8765"
    volumes:
      - openalgo_db:/app/db
      - openalgo_log:/app/log
      - openalgo_strategies:/app/strategies
      - openalgo_keys:/app/keys
      - openalgo_tmp:/app/tmp
      - ./.env:/app/.env
    environment:
      - FLASK_ENV=production
      - FLASK_DEBUG=0
      - APP_MODE=standalone
      - TZ=Asia/Kolkata
      # Resource limits auto-calculated for multi-instance deployment
      # See: https://github.com/marketcalls/openalgo/issues/822
      - OPENBLAS_NUM_THREADS=${THREAD_LIMIT}
      - OMP_NUM_THREADS=${THREAD_LIMIT}
      - MKL_NUM_THREADS=${THREAD_LIMIT}
      - NUMEXPR_NUM_THREADS=${THREAD_LIMIT}
      - NUMBA_NUM_THREADS=${THREAD_LIMIT}
      - STRATEGY_MEMORY_LIMIT_MB=${STRATEGY_MEM_LIMIT}
    shm_size: '${SHM_SIZE_MB}m'
${MEM_LIMIT_YAML}    # Required for gthread: a stop gives open requests up to 30 s to finish and
    # Docker kills the container after 10 s by default. Harmless on eventlet.
    # See docs/gthread/README.md.
    stop_grace_period: 45s
    healthcheck:
      test: ["CMD", "curl", "-f", "http://127.0.0.1:5000/auth/check-setup"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    restart: unless-stopped

volumes:
  openalgo_db:
    driver: local
  openalgo_log:
    driver: local
  openalgo_strategies:
    driver: local
  openalgo_keys:
    driver: local
  openalgo_tmp:
    driver: local
EOF
}

# After `up`, confirm the container started on the web server the instance's
# .env asks for. start.sh quietly falls back to eventlet when the image has no
# launcher (an older image or fork), so a gthread request must be checked
# against the log rather than assumed. Returns 0 when it matches, 1 when the
# other server started, 2 when the log never said (container still starting).
verify_worker_started() {
    local instance_dir="$1" expected="$2" waited=0 limit="${3:-120}" logs
    while [ "$waited" -le "$limit" ]; do
        logs=$(cd "$instance_dir" && docker compose logs --no-log-prefix --tail 300 2>/dev/null)
        if echo "$logs" | grep -q "Starting application on port .* with $expected"; then
            return 0
        fi
        if echo "$logs" | grep -q "Starting application on port .* with [a-z]*"; then
            return 1
        fi
        sleep "${VERIFY_POLL_SECONDS:-5}"
        waited=$((waited + ${VERIFY_POLL_SECONDS:-5}))
    done
    return 2
}

# Tests source this script to exercise the helpers above in isolation:
#   OPENALGO_INSTALLER_LIB_ONLY=1 source install-docker-multi-custom-ssl.sh
# Nothing past this point runs in that mode.
if [ "${OPENALGO_INSTALLER_LIB_ONLY:-0}" = "1" ]; then
    return 0 2>/dev/null || exit 0
fi

# -----------------
# System Prep
# -----------------

# Check root
if [[ $EUID -ne 0 ]]; then
   log "This script must be run as root" "$RED" 
   exit 1
fi

log "\n=== System Preparation ===" "$BLUE"

# Update system
log "Updating system packages..." "$YELLOW"
apt-get update -y && apt-get upgrade -y
check_status "System update failed"

# Install basics
log "Installing dependencies..." "$YELLOW"
apt-get install -y \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    git \
    nginx \
    ufw \
    python3-full \
    python3-pip
check_status "Package installation failed"

# Host Timezone Check
log "Checking Host Timezone..." "$YELLOW"
CURRENT_TZ=$(timedatectl show --property=Timezone --value 2>/dev/null || cat /etc/timezone)
if [[ "$CURRENT_TZ" != *"Asia/Kolkata"* ]]; then
    log "Setting Host Timezone to Asia/Kolkata..." "$YELLOW"
    timedatectl set-timezone Asia/Kolkata
    check_status "Failed to set timezone"
    log "Timezone set to Asia/Kolkata" "$GREEN"
else
    log "Host Timezone is already Asia/Kolkata." "$GREEN"
fi

# Install Docker
if ! command -v docker &> /dev/null; then
    log "Installing Docker..." "$YELLOW"
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
    rm get-docker.sh
    check_status "Docker installation failed"
else
    log "Docker already installed" "$GREEN"
fi

# Install uv (if not present, though Docker installs it inside container, we might need it for utilities)
if ! command -v uv &> /dev/null; then
     log "Installing uv..." "$YELLOW"
     curl -LsSf https://astral.sh/uv/install.sh | sh
     if [ -f "$HOME/.cargo/env" ]; then
         source "$HOME/.cargo/env"
     fi
fi


# -----------------
# Configuration Collection
# -----------------

log "\n=== Configuration ===" "$BLUE"

# 0. Git Repository Selection
DEFAULT_REPO="https://github.com/marketcalls/openalgo.git"
read -p "Enter Git Repository URL [Default: $DEFAULT_REPO]: " REPO_URL
REPO_URL=${REPO_URL:-$DEFAULT_REPO}
log "Using Repository: $REPO_URL" "$GREEN"

# 1. Get Domains
while true; do
    read -p "Enter domain names separated by SPACE (e.g., domain.com zerodha.domain.com): " -a DOMAINS_INPUT
    if [ ${#DOMAINS_INPUT[@]} -eq 0 ]; then
        log "Error: At least one domain is required" "$RED"
        continue
    fi
    break
done

# 2. First Pass: Determine which domains are updates vs fresh installs
declare -a NEW_DOMAINS
declare -a UPDATE_DOMAINS

for DOMAIN in "${DOMAINS_INPUT[@]}"; do
    INSTANCE_DIR="$INSTALL_BASE/$DOMAIN"
    if [ -d "$INSTANCE_DIR" ] && [ -d "$INSTANCE_DIR/.git" ] && [ -f "$INSTANCE_DIR/.env" ]; then
        log "Found existing installation: $DOMAIN" "$GREEN"
        UPDATE_DOMAINS+=("$DOMAIN")
    else
        NEW_DOMAINS+=("$DOMAIN")
    fi
done

log "Update domains: ${#UPDATE_DOMAINS[@]}, New domains: ${#NEW_DOMAINS[@]}" "$BLUE"

# 3. Wildcard SSL Check - Only ask if there are NEW domains to configure
WILDCARD_CERT_PATH=""
WILDCARD_KEY_PATH=""
USE_WILDCARD_SSL="n"

if [ ${#NEW_DOMAINS[@]} -gt 0 ]; then
    log "\n${#NEW_DOMAINS[@]} new domain(s) detected. SSL configuration required." "$YELLOW"
    read -p "Do you have a WILDCARD SSL certificate for these domains? (y/n): " USE_WILDCARD_SSL

    if [[ $USE_WILDCARD_SSL =~ ^[Yy]$ ]]; then
        while true; do
            read -e -p "Enter path to Wildcard FULL CHAIN .pem file: " WILDCARD_CERT_PATH
            if [ ! -f "$WILDCARD_CERT_PATH" ]; then
                log "Error: File not found at $WILDCARD_CERT_PATH" "$RED"
                continue
            fi
            break
        done

        while true; do
            read -e -p "Enter path to Wildcard PRIVATE KEY .key file: " WILDCARD_KEY_PATH
            if [ ! -f "$WILDCARD_KEY_PATH" ]; then
                log "Error: File not found at $WILDCARD_KEY_PATH" "$RED"
                continue
            fi
            break
        done
    fi
else
    log "\nAll domains are existing installations - SSL configuration will be preserved." "$GREEN"
fi

# Arrays to store config
declare -a CONF_DOMAINS
declare -a CONF_BROKERS
declare -a CONF_API_KEYS
declare -a CONF_API_SECRETS
declare -a CONF_MARKET_KEYS
declare -a CONF_MARKET_SECRETS
declare -a CONF_SSL_CERTS
declare -a CONF_SSL_KEYS
declare -a UPDATE_MODE  # Track update vs fresh install per domain
declare -a CONF_PROFILES      # Memory profile per instance: auto | unrestricted
declare -a CONF_WORKERS       # Web server per instance: eventlet | gthread
declare -a CONF_PREV_WORKERS  # Web server the instance's .env asked for before this run

# Helper function to extract value from .env file
extract_env_value() {
    local env_file="$1"
    local key="$2"
    grep "^${key}" "$env_file" 2>/dev/null | head -1 | cut -d"'" -f2 | tr -d "'" || echo ""
}

# 3. Iterate Domains for Config
for DOMAIN in "${DOMAINS_INPUT[@]}"; do
    log "\n--- Configuring Instance: $DOMAIN ---" "$YELLOW"

    # Check existing installation
    INSTANCE_DIR="$INSTALL_BASE/$DOMAIN"
    IS_UPDATE="false"
    
    if [ -d "$INSTANCE_DIR" ] && [ -d "$INSTANCE_DIR/.git" ]; then
        read -p "Instance for $DOMAIN already exists. Update code only? (y=update, n=skip, r=reinstall): " UPDATE_CHOICE
        case "$UPDATE_CHOICE" in
            [Yy]*)
                IS_UPDATE="true"
                log "Update mode: Will pull latest code and preserve configuration." "$GREEN"
                
                # Load existing configuration from .env
                EXISTING_ENV="$INSTANCE_DIR/.env"
                if [ -f "$EXISTING_ENV" ]; then
                    log "Loading existing configuration from .env..." "$GREEN"
                    EXISTING_BROKER=$(extract_env_value "$EXISTING_ENV" "REDIRECT_URL" | sed 's|.*/\([^/]*\)/callback|\1|')
                    EXISTING_API_KEY=$(extract_env_value "$EXISTING_ENV" "BROKER_API_KEY")
                    EXISTING_API_SECRET=$(extract_env_value "$EXISTING_ENV" "BROKER_API_SECRET")
                    EXISTING_M_KEY=$(extract_env_value "$EXISTING_ENV" "BROKER_API_KEY_MARKET")
                    EXISTING_M_SECRET=$(extract_env_value "$EXISTING_ENV" "BROKER_API_SECRET_MARKET")
                    
                    # Use existing values
                    CONF_DOMAINS+=("$DOMAIN")
                    CONF_BROKERS+=("$EXISTING_BROKER")
                    CONF_API_KEYS+=("$EXISTING_API_KEY")
                    CONF_API_SECRETS+=("$EXISTING_API_SECRET")
                    CONF_MARKET_KEYS+=("${EXISTING_M_KEY:-}")
                    CONF_MARKET_SECRETS+=("${EXISTING_M_SECRET:-}")
                    UPDATE_MODE+=("true")
                    
                    # SSL already configured, get existing paths
                    SSL_DIR="/etc/nginx/ssl/$DOMAIN"
                    if [ -f "$SSL_DIR/fullchain.pem" ]; then
                        CONF_SSL_CERTS+=("$SSL_DIR/fullchain.pem")
                        CONF_SSL_KEYS+=("$SSL_DIR/privkey.pem")
                    else
                        log "Warning: SSL certs not found, will need reconfiguration" "$YELLOW"
                        CONF_SSL_CERTS+=("EXISTING")
                        CONF_SSL_KEYS+=("EXISTING")
                    fi
                    
                    log "Loaded: Broker=$EXISTING_BROKER" "$GREEN"

                    # Per-instance options (Enter keeps what the instance has)
                    PREV_WORKER=$(read_worker_class "$EXISTING_ENV")
                    CONF_PREV_WORKERS+=("$PREV_WORKER")
                    CONF_WORKERS+=("$(choose_worker_class "$DOMAIN" "$PREV_WORKER")")
                    CONF_PROFILES+=("$(choose_memory_profile "$DOMAIN" "$(read_instance_profile "$DOMAIN")")")
                    continue  # Skip interactive prompts for this domain
                else
                    log "Warning: No .env found, treating as fresh install" "$YELLOW"
                    IS_UPDATE="false"
                fi
                ;;
            [Nn]*)
                log "Skipping $DOMAIN" "$YELLOW"
                continue
                ;;
            [Rr]*)
                log "Reinstall mode: Will ask for all configuration again." "$YELLOW"
                log "Warning: This will regenerate security keys and invalidate existing passwords!" "$RED"
                read -p "Are you sure you want to reinstall? (yes to confirm): " CONFIRM_REINSTALL
                if [ "$CONFIRM_REINSTALL" != "yes" ]; then
                    log "Skipping $DOMAIN" "$YELLOW"
                    continue
                fi
                ;;
            *)
                log "Invalid choice. Skipping $DOMAIN" "$RED"
                continue
                ;;
        esac
    fi
    
    # Mark as fresh install if not update mode
    UPDATE_MODE+=("$IS_UPDATE")

    CONF_DOMAINS+=("$DOMAIN")

    # Broker
    while true; do
        read -p "Enter BROKER for $DOMAIN: " BROKER
        if validate_broker "$BROKER"; then
            CONF_BROKERS+=("$BROKER")
            break
        else
            log "Invalid broker path. See documentation for list." "$RED"
        fi
    done

    # Credentials
    log "Redirect URL: https://$DOMAIN/$BROKER/callback" "$GREEN"
    # Credentials
    log "Redirect URL: https://$DOMAIN/$BROKER/callback" "$GREEN"
    while true; do
        read -p "Enter API Key: " API_KEY
        if [ ! -z "$API_KEY" ]; then
            CONF_API_KEYS+=("$API_KEY")
            break
        else
            log "API Key cannot be empty." "$RED"
        fi
    done

    while true; do
        read -p "Enter API Secret: " API_SECRET
        if [ ! -z "$API_SECRET" ]; then
            CONF_API_SECRETS+=("$API_SECRET")
            break
        else
            log "API Secret cannot be empty." "$RED"
        fi
    done

    # XTS Check
    if is_xts_broker "$BROKER"; then
        read -p "Enter Market Data API Key: " M_KEY
        read -p "Enter Market Data API Secret: " M_SECRET
        CONF_MARKET_KEYS+=("$M_KEY")
        CONF_MARKET_SECRETS+=("$M_SECRET")
    else
        CONF_MARKET_KEYS+=("")
        CONF_MARKET_SECRETS+=("")
    fi

    # SSL Config
    if [[ $USE_WILDCARD_SSL =~ ^[Yy]$ ]]; then
        CONF_SSL_CERTS+=("$WILDCARD_CERT_PATH")
        CONF_SSL_KEYS+=("$WILDCARD_KEY_PATH")
    else
        log "SSL Configuration for $DOMAIN" "$BLUE"
        echo "Select SSL Type:"
        echo "1) Custom SSL (You have your own .pem/.key files)"
        echo "2) Let's Encrypt (Automated via Certbot)"
         read -p "Enter choice [1/2] (Default: 1): " SSL_CHOICE
        SSL_CHOICE=${SSL_CHOICE:-1}

        if [ "$SSL_CHOICE" == "2" ]; then
             # Let's Encrypt
             CONF_SSL_CERTS+=("LETSENCRYPT_AUTO")
             CONF_SSL_KEYS+=("LETSENCRYPT_AUTO")
        else
             # Custom SSL with default suggestion
             DEFAULT_CERT_PATH="/etc/ssl/certs/${DOMAIN}.pem" # Example default
             DEFAULT_KEY_PATH="/etc/ssl/private/${DOMAIN}.key" # Example default
             
             # Try to find if user has a standard 'certs' folder in home or root
             if [ -d "$HOME/certs" ]; then
                 DEFAULT_CERT_PATH="$HOME/certs/${DOMAIN}.crt"
                 DEFAULT_KEY_PATH="$HOME/certs/${DOMAIN}.key"
             elif [ -d "/root/certs" ]; then
                 DEFAULT_CERT_PATH="/root/certs/${DOMAIN}.crt"
                 DEFAULT_KEY_PATH="/root/certs/${DOMAIN}.key"
             fi

             while true; do
                 read -e -p "Enter path to SSL Certificate [Default: $DEFAULT_CERT_PATH]: " CERT_PATH
                 CERT_PATH=${CERT_PATH:-$DEFAULT_CERT_PATH}
                 if [ ! -f "$CERT_PATH" ]; then
                     log "Error: File not found at $CERT_PATH" "$RED"
                     continue
                 fi
                 break
             done

             while true; do
                 read -e -p "Enter path to SSL Private Key [Default: $DEFAULT_KEY_PATH]: " KEY_PATH
                 KEY_PATH=${KEY_PATH:-$DEFAULT_KEY_PATH}
                 if [ ! -f "$KEY_PATH" ]; then
                     log "Error: File not found at $KEY_PATH" "$RED"
                     continue
                 fi
                 break
             done
             CONF_SSL_CERTS+=("$CERT_PATH")
             CONF_SSL_KEYS+=("$KEY_PATH")
         fi
    fi

    # Per-instance options for a new instance
    CONF_PREV_WORKERS+=("eventlet")
    CONF_WORKERS+=("$(choose_worker_class "$DOMAIN" "eventlet" new)")
    CONF_PROFILES+=("$(choose_memory_profile "$DOMAIN" "auto")")
done

# -----------------
# Deployment Loop
# -----------------

log "\n=== Starting Deployment ===" "$BLUE"

# Calculate dynamic resource limits based on system specs and number of instances
TOTAL_RAM_MB=$(($(grep MemTotal /proc/meminfo | awk '{print $2}') / 1024))
CPU_CORES=$(nproc 2>/dev/null || echo 2)
NUM_INSTANCES=${#CONF_DOMAINS[@]}
[ "$NUM_INSTANCES" -lt 1 ] && NUM_INSTANCES=1

# Calculate per-instance RAM (divide total by number of instances)
RAM_PER_INSTANCE=$((TOTAL_RAM_MB / NUM_INSTANCES))
log "System: ${TOTAL_RAM_MB}MB RAM, ${CPU_CORES} cores, ${NUM_INSTANCES} instances" "$BLUE"
log "Per-instance share (auto profile): ~${RAM_PER_INSTANCE}MB" "$BLUE"

# Resource limits are chosen per instance (memory profile) inside the loop below.

# Base Dir
mkdir -p "$INSTALL_BASE"
chmod 755 "$INSTALL_BASE"

# Firewall Init (Open standard ports)
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# Optional Portainer Installation - Smart Detection
PORTAINER_RUNNING=$(docker ps -q -f name=portainer)
PORTAINER_EXISTS=$(docker ps -aq -f name=portainer)
INSTALL_PORTAINER="n"
PORTAINER_DOMAIN=""

if [ ! -z "$PORTAINER_RUNNING" ]; then
    # Portainer is already running
    CURRENT_IMAGE=$(docker inspect portainer --format '{{.Config.Image}}' 2>/dev/null || echo "unknown")
    log "Portainer is already running (Image: $CURRENT_IMAGE)" "$GREEN"
    
    read -p "Check for Portainer updates? (y/n): " CHECK_PORTAINER_UPDATE
    if [[ $CHECK_PORTAINER_UPDATE =~ ^[Yy]$ ]]; then
        log "Checking for Portainer updates..." "$YELLOW"
        docker pull portainer/portainer-ce:latest
        
        NEW_IMAGE_ID=$(docker inspect portainer/portainer-ce:latest --format '{{.Id}}' 2>/dev/null | cut -c8-19)
        OLD_IMAGE_ID=$(docker inspect portainer --format '{{.Image}}' 2>/dev/null | cut -c8-19)
        
        if [ "$NEW_IMAGE_ID" != "$OLD_IMAGE_ID" ] && [ ! -z "$NEW_IMAGE_ID" ]; then
            log "New Portainer version available. Updating..." "$YELLOW"
            
            # Get current binding (preserve domain/IP configuration)
            CURRENT_BIND=$(docker port portainer 9000 2>/dev/null | cut -d: -f1)
            BIND_IP="${CURRENT_BIND:-127.0.0.1}"
            
            docker stop portainer && docker rm portainer
            docker run -d -p $BIND_IP:9000:9000 --name portainer --restart=always \
                -v /var/run/docker.sock:/var/run/docker.sock \
                -v portainer_data:/data \
                portainer/portainer-ce:latest
            log "Portainer updated successfully!" "$GREEN"
        else
            log "Portainer is already at latest version." "$GREEN"
        fi
    fi
    
    # Skip all further Portainer prompts - already configured
    INSTALL_PORTAINER="skip"
    
elif [ ! -z "$PORTAINER_EXISTS" ]; then
    # Portainer container exists but is stopped
    log "Portainer container exists but is stopped." "$YELLOW"
    read -p "Start existing Portainer? (y/n): " START_PORTAINER
    if [[ $START_PORTAINER =~ ^[Yy]$ ]]; then
        docker start portainer
        log "Portainer started." "$GREEN"
    fi
    INSTALL_PORTAINER="skip"
    
else
    # Fresh install option
    read -p "Do you want to install Portainer (Docker Management UI)? (y/n): " INSTALL_PORTAINER
fi

if [[ $INSTALL_PORTAINER =~ ^[Yy]$ ]]; then
    read -p "Enter Domain for Portainer (Leave EMPTY to use IP:9000): " PORTAINER_DOMAIN
    
    log "\nInstalling Portainer..." "$BLUE"
    
    # 1. Install Portainer Container
    if [ ! "$(docker ps -q -f name=portainer)" ]; then
        if [ "$(docker ps -aq -f status=exited -f name=portainer)" ]; then
            docker rm portainer
        fi
        
        docker volume create portainer_data
        # Run on localhost:9000 only if using Nginx, otherwise 0.0.0.0:9000
        if [ ! -z "$PORTAINER_DOMAIN" ]; then
            BIND_IP="127.0.0.1"
            log "Configuring Portainer for domain: $PORTAINER_DOMAIN" "$GREEN"
        else
            BIND_IP="0.0.0.0"
            ufw allow 9000/tcp
            log "Configuring Portainer for IP Access (Port 9000)" "$YELLOW"
        fi
        
        docker run -d -p $BIND_IP:9000:9000 --name portainer --restart=always \
            -v /var/run/docker.sock:/var/run/docker.sock \
            -v portainer_data:/data \
            portainer/portainer-ce:latest
            
    else
        log "Portainer is already running." "$YELLOW"
    fi

    # 2. Configure Nginx for Portainer (If domain provided)
    if [ ! -z "$PORTAINER_DOMAIN" ]; then
        # SSL Selection for Portainer
        P_SSL_CERT=""
        P_SSL_KEY=""
        P_SSL_MODE="none"
        
        echo "Select SSL Type for Portainer:"
        echo "1) Custom SSL (You have your own .pem/.key files)"
        echo "2) Let's Encrypt (Automated via Certbot)"
        echo "3) None (HTTP only - Not Recommended)"
        read -p "Enter choice [1/2/3] (Default: 1): " P_SSL_CHOICE
        P_SSL_CHOICE=${P_SSL_CHOICE:-1}

        if [ "$P_SSL_CHOICE" == "2" ]; then
             P_SSL_MODE="letsencrypt"
             P_SSL_CERT="LETSENCRYPT_AUTO"
             P_SSL_KEY="LETSENCRYPT_AUTO"
        elif [ "$P_SSL_CHOICE" == "1" ]; then
             P_SSL_MODE="custom"
             
             # Check for Wildcard match
             if [[ $USE_WILDCARD_SSL =~ ^[Yy]$ ]]; then
                 read -p "Use the same Wildcard SSL for Portainer? (y/n): " USE_WC_PORTAINER
                 if [[ $USE_WC_PORTAINER =~ ^[Yy]$ ]]; then
                     P_SSL_CERT="$WILDCARD_CERT_PATH"
                     P_SSL_KEY="$WILDCARD_KEY_PATH"
                 fi
             fi
             
             if [ -z "$P_SSL_CERT" ]; then
                 # Custom SSL with default suggestion
                 DEFAULT_P_CERT="/etc/ssl/certs/${PORTAINER_DOMAIN}.pem"
                 DEFAULT_P_KEY="/etc/ssl/private/${PORTAINER_DOMAIN}.key"
                 
                 if [ -d "$HOME/certs" ]; then
                     DEFAULT_P_CERT="$HOME/certs/${PORTAINER_DOMAIN}.crt"
                     DEFAULT_P_KEY="$HOME/certs/${PORTAINER_DOMAIN}.key"
                 elif [ -d "/root/certs" ]; then
                     DEFAULT_P_CERT="/root/certs/${PORTAINER_DOMAIN}.crt"
                     DEFAULT_P_KEY="/root/certs/${PORTAINER_DOMAIN}.key"
                 fi

                 while true; do
                     read -e -p "Enter path to Portainer SSL Certificate [Default: $DEFAULT_P_CERT]: " P_SSL_CERT
                     P_SSL_CERT=${P_SSL_CERT:-$DEFAULT_P_CERT}
                     if [ ! -f "$P_SSL_CERT" ]; then
                         log "Error: File not found at $P_SSL_CERT" "$RED"
                         continue
                     fi
                     break
                 done

                while true; do
                    read -e -p "Enter path to Portainer SSL Private Key [Default: $DEFAULT_P_KEY]: " P_SSL_KEY
                    P_SSL_KEY=${P_SSL_KEY:-$DEFAULT_P_KEY}
                    if [ ! -f "$P_SSL_KEY" ]; then
                        log "Error: File not found at $P_SSL_KEY" "$RED"
                        continue
                    fi
                    break
                done
            fi
        else
            log "Warning: Portainer will be deployed without SSL." "$YELLOW"
        fi

        
        # Setup SSL Dir
        P_SSL_DIR="/etc/nginx/ssl/$PORTAINER_DOMAIN"
        mkdir -p "$P_SSL_DIR"

        if [ "$P_SSL_CERT" == "LETSENCRYPT_AUTO" ]; then
             log "Generating Let's Encrypt SSL for Portainer ($PORTAINER_DOMAIN)..." "$YELLOW"
             
             # Ensure Certbot installed
             if ! command -v certbot &> /dev/null; then
                 apt-get install -y certbot
             fi
             
             systemctl stop nginx 2>/dev/null
             
             certbot certonly --standalone -d "$PORTAINER_DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email
             
             LE_CERT="/etc/letsencrypt/live/$PORTAINER_DOMAIN/fullchain.pem"
             LE_KEY="/etc/letsencrypt/live/$PORTAINER_DOMAIN/privkey.pem"
             
            if [ -f "$LE_CERT" ]; then
                log "Portainer SSL Generated Successfully" "$GREEN"
                cp -L "$LE_CERT" "$P_SSL_DIR/fullchain.pem"
                cp -L "$LE_KEY" "$P_SSL_DIR/privkey.pem"
            else
                log "Error: Portainer Let's Encrypt generation failed." "$RED"
                # Fallback or exit? user might want to continue. Let's exit to be safe.
                exit 1
            fi
        else
            cp "$P_SSL_CERT" "$P_SSL_DIR/fullchain.pem"
            cp "$P_SSL_KEY" "$P_SSL_DIR/privkey.pem"
        fi
        
        chmod 600 "$P_SSL_DIR/privkey.pem"
        chmod 644 "$P_SSL_DIR/fullchain.pem"

        # Create Nginx Config
        cat <<EOF > "/etc/nginx/sites-available/$PORTAINER_DOMAIN"
server {
    listen 80;
    server_name $PORTAINER_DOMAIN;
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2;
    server_name $PORTAINER_DOMAIN;

    ssl_certificate $P_SSL_DIR/fullchain.pem;
    ssl_certificate_key $P_SSL_DIR/privkey.pem;
    
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers EECDH+AESGCM:EDH+AESGCM;
    ssl_prefer_server_ciphers on;
    
    location / {
        proxy_pass http://127.0.0.1:9000;
        proxy_http_version 1.1;
        # Plain HTTP only: /ws, /ws/ and /socket.io/ have their own blocks.
        # Forcing "Connection: upgrade" here sent every ordinary request
        # upstream with a bogus upgrade header and an empty Upgrade:, which
        # breaks HTTP/1.1 keep-alive to gunicorn and shows up as intermittent
        # truncated asset responses and 5xx (GitHub issue #1807).
        proxy_set_header Connection "";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
        ln -sf "/etc/nginx/sites-available/$PORTAINER_DOMAIN" "/etc/nginx/sites-enabled/"
        log "Portainer Nginx configuration created." "$GREEN"
    fi
fi

# Instances whose image failed to build. Collected so one bad instance does
# not abort the others, and so the final banner can tell the truth.
FAILED_DOMAINS=()

# Optional pin of the PyPI download host to a fast CDN edge (PYPI_EDGE_IP).
PYPI_EDGE_PIN=$(select_pypi_edge)
if [ -n "$PYPI_EDGE_PIN" ]; then
    log "PyPI downloads pinned to edge $PYPI_EDGE_PIN for this build (PYPI_EDGE_IP)." "$YELLOW"
fi

for i in "${!CONF_DOMAINS[@]}"; do
    DOMAIN="${CONF_DOMAINS[$i]}"
    BROKER="${CONF_BROKERS[$i]}"
    API_KEY="${CONF_API_KEYS[$i]}"
    API_SECRET="${CONF_API_SECRETS[$i]}"
    M_KEY="${CONF_MARKET_KEYS[$i]}"
    M_SECRET="${CONF_MARKET_SECRETS[$i]}"
    SSL_CERT="${CONF_SSL_CERTS[$i]}"
    SSL_KEY="${CONF_SSL_KEYS[$i]}"

    log "\nDeploying $DOMAIN..." "$BLUE"

    # 1. Allocation
    INSTANCE_DIR="$INSTALL_BASE/$DOMAIN"
    PORTS=($(resolve_instance_ports "$DOMAIN"))
    FLASK_PORT=${PORTS[0]}
    WS_PORT=${PORTS[1]}
    SANITIZED_NAME=$(sanitize_domain "$DOMAIN")
    PROJECT_NAME="openalgo-${SANITIZED_NAME}"

    PROFILE="${CONF_PROFILES[$i]:-auto}"
    WORKER="${CONF_WORKERS[$i]:-eventlet}"
    PREV_WORKER="${CONF_PREV_WORKERS[$i]:-eventlet}"
    compute_resources "$PROFILE" "$TOTAL_RAM_MB" "$CPU_CORES" "$NUM_INSTANCES"

    log " -> Ports: Flask=$FLASK_PORT, WS=$WS_PORT" "$GREEN"
    log " -> Memory profile: $PROFILE (strategy cap ${STRATEGY_MEM_LIMIT}MB, shm ${SHM_SIZE_MB}MB, ${THREAD_LIMIT} threads)" "$GREEN"
    log " -> Web server: $WORKER" "$GREEN"
    if [ "$WORKER" = "gthread" ] && [ "$RAM_PER_INSTANCE" -lt 2000 ]; then
        log "    Note: gthread uses 64 request threads per instance; this host has about ${RAM_PER_INSTANCE}MB per instance." "$YELLOW"
    fi
    log " -> Dir: $INSTANCE_DIR" "$GREEN"

    # 3. SSL Setup
    SSL_DIR="/etc/nginx/ssl/$DOMAIN"
    mkdir -p "$SSL_DIR"

    if [ "$SSL_CERT" == "LETSENCRYPT_AUTO" ]; then
        log "Generating Let's Encrypt SSL for $DOMAIN..." "$YELLOW"
        
        # Ensure Certbot installed
        if ! command -v certbot &> /dev/null; then
            log "Installing Certbot..." "$YELLOW"
            apt-get install -y certbot
        fi

        # Stop Nginx for standalone mode
        systemctl stop nginx 2>/dev/null
        
        # Run Certbot
        certbot certonly --standalone -d "$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email
        
        LE_CERT="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
        LE_KEY="/etc/letsencrypt/live/$DOMAIN/privkey.pem"
        
        if [ -f "$LE_CERT" ]; then
            log "Let's Encrypt Certificate Generated Successfully" "$GREEN"
            cp -L "$LE_CERT" "$SSL_DIR/fullchain.pem"
            cp -L "$LE_KEY" "$SSL_DIR/privkey.pem"
        else
            log "Error: Let's Encrypt generation failed." "$RED"
            exit 1
        fi
    else
        # Custom SSL
        cp "$SSL_CERT" "$SSL_DIR/fullchain.pem"
        cp "$SSL_KEY" "$SSL_DIR/privkey.pem"
    fi

    chmod 600 "$SSL_DIR/privkey.pem"
    chmod 644 "$SSL_DIR/fullchain.pem"
    
    # Snapshot the generated compose file and vhost BEFORE the repository sync:
    # docker-compose.yaml is a tracked file, so `git reset --hard` below
    # replaces the generated one with the repository's own, and a snapshot
    # taken afterwards would "restore" the wrong file after a failed build.
    snapshot_instance_config "$INSTANCE_DIR" "$DOMAIN"

    # 4. Clone/Update Repo
    if [ ! -d "$INSTANCE_DIR/.git" ]; then
        if [ -d "$INSTANCE_DIR" ]; then
            log "Directory exists but is not a valid git repo. Backing up and re-cloning..." "$YELLOW"
            mv "$INSTANCE_DIR" "${INSTANCE_DIR}_backup_$(date +%s)"
        fi
        # --filter=blob:none makes this a partial clone: the server sends every
        # commit and tree but no file contents, so it pulls ~20 MB instead of
        # ~280 MB. Blobs outside the current checkout are fetched on demand, so
        # the full history stays usable -- all 4,824 commits, 62 tags, every
        # branch -- which keeps `git reset --hard HEAD~n`, tag checkouts and
        # branch switching working. Nearly all of that 280 MB is superseded
        # frontend/dist bundles that a server never reads. A host without filter
        # support just full-clones, so this is never worse than no flag at all.
        git clone --filter=blob:none "$REPO_URL" "$INSTANCE_DIR"
    else
        log "Updating existing repository..." "$GREEN"
        cd "$INSTANCE_DIR"
        # Force sync with the selected repo URL to pick up Dockerfile fixes
        git remote set-url origin "$REPO_URL"
        git fetch origin
        git reset --hard origin/main
    fi
    
    mkdir -p "$INSTANCE_DIR"/{log,logs,keys,db,strategies/scripts,strategies/examples}
    
    # 5. Env Config - CRITICAL: Preserve .env during updates to maintain passwords
    IS_UPDATE_MODE="${UPDATE_MODE[$i]}"
    ENV_FILE="$INSTANCE_DIR/.env"
    
    if [ "$IS_UPDATE_MODE" == "true" ] && [ -f "$ENV_FILE" ]; then
        log "Preserving existing .env file (keeps APP_KEY, PEPPER, and passwords valid)" "$GREEN"
        
        # Only update connectivity settings if needed (in case domain changed)
        # These are safe to update without breaking authentication
        sed -i "s|WEBSOCKET_URL='.*'|WEBSOCKET_URL='wss://$DOMAIN/ws'|g" "$ENV_FILE"
        
        # CORS: Add domain if not already present (preserves custom domains like chart.domain.com)
        # NOTE: Flask-CORS expects comma-separated origins (see cors.py line 25)
        if ! grep "CORS_ALLOWED_ORIGINS" "$ENV_FILE" | grep -q "https://$DOMAIN"; then
            # Extract current CORS value and append new domain with comma
            CURRENT_CORS=$(grep "CORS_ALLOWED_ORIGINS" "$ENV_FILE" | sed "s/.*= '\\(.*\\)'/\\1/")
            if [ -n "$CURRENT_CORS" ]; then
                NEW_CORS="$CURRENT_CORS,https://$DOMAIN"
                # Remove duplicates while preserving comma format
                NEW_CORS=$(echo "$NEW_CORS" | tr ',' '\n' | sort -u | tr '\n' ',' | sed 's/,$//')
                sed -i "s|CORS_ALLOWED_ORIGINS = '.*'|CORS_ALLOWED_ORIGINS = '$NEW_CORS'|g" "$ENV_FILE"
            fi
        fi
        
        # CSP: Add domain if not already present (delete-and-append avoids sed regex issues with nested quotes)
        # See: https://github.com/marketcalls/openalgo/issues/938
        if ! grep "CSP_CONNECT_SRC" "$ENV_FILE" | grep -q "https://$DOMAIN"; then
            CURRENT_CSP=$(grep "^CSP_CONNECT_SRC" "$ENV_FILE" | sed 's/^CSP_CONNECT_SRC *= *//; s/^"//; s/"$//')
            if [ -n "$CURRENT_CSP" ] && ! echo "$CURRENT_CSP" | grep -q "https://$DOMAIN"; then
                NEW_CSP="$CURRENT_CSP https://$DOMAIN wss://$DOMAIN"
                sed -i '/^CSP_CONNECT_SRC/d' "$ENV_FILE"
                echo "CSP_CONNECT_SRC = \"$NEW_CSP\"" >> "$ENV_FILE"
            fi
        fi
        
        log "Updated connectivity settings (preserved custom domains)" "$GREEN"
    else
        log "Creating new .env configuration..." "$YELLOW"
        cp "$INSTANCE_DIR/.sample.env" "$ENV_FILE"
        
        APP_KEY=$(generate_hex)
        PEPPER=$(generate_hex)
        
        sed -i "s|YOUR_BROKER_API_KEY|$API_KEY|g" "$ENV_FILE"
        sed -i "s|YOUR_BROKER_API_SECRET|$API_SECRET|g" "$ENV_FILE"
        sed -i "s|http://127.0.0.1:5000|https://$DOMAIN|g" "$ENV_FILE"
        sed -i "s|<broker>|$BROKER|g" "$ENV_FILE"
        sed -i "s|OPENALGO_PLACEHOLDER_APP_KEY_REGENERATE_BEFORE_USE|$APP_KEY|g" "$ENV_FILE"
        sed -i "s|OPENALGO_PLACEHOLDER_API_KEY_PEPPER_REGENERATE_BEFORE_USE|$PEPPER|g" "$ENV_FILE"

        # OPENALGO_GIT_BRANCH / OPENALGO_GIT_COMMIT are written after the image
        # builds, for new and updated instances alike (see set_git_info).
        # Each instance is published only on 127.0.0.1 with nginx in front;
        # trust the proxy's X-Forwarded-For / X-Real-IP.
        sed -i "s|TRUST_PROXY_HEADERS = 'FALSE'|TRUST_PROXY_HEADERS = 'TRUE'|g" "$ENV_FILE"
        # .env is bind-mounted read+write into the container so auto-rotation
        # of compromised APP_KEY/API_KEY_PEPPER (utils/env_check.py) can run.
        # Container runs as appuser (UID 1000); chown to UID 1000 + chmod 600
        # gives appuser read+write while keeping the file private on the host.
        chown 1000:1000 "$ENV_FILE"
        chmod 600 "$ENV_FILE"
        
        # XTS
        if [ ! -z "$M_KEY" ]; then
            sed -i "s|YOUR_BROKER_MARKET_API_KEY|$M_KEY|g" "$ENV_FILE"
            sed -i "s|YOUR_BROKER_MARKET_API_SECRET|$M_SECRET|g" "$ENV_FILE"
        fi
        
        # Connectivity
        sed -i "s|WEBSOCKET_URL='.*'|WEBSOCKET_URL='wss://$DOMAIN/ws'|g" "$ENV_FILE"
        # WEBSOCKET_HOST / FLASK_HOST_IP bind to 0.0.0.0 inside the container so
        # the Docker port mapping can route traffic from the host's nginx.
        sed -i "s|WEBSOCKET_HOST='127.0.0.1'|WEBSOCKET_HOST='0.0.0.0'|g" "$ENV_FILE"
        sed -i "s|FLASK_HOST_IP='127.0.0.1'|FLASK_HOST_IP='0.0.0.0'|g" "$ENV_FILE"
        # ZMQ_HOST stays on loopback: internal message bus, same-container only.
        # Exposing it would leak the raw tick feed.
        sed -i "s|CORS_ALLOWED_ORIGINS = '.*'|CORS_ALLOWED_ORIGINS = 'https://$DOMAIN'|g" "$ENV_FILE"
        # CSP: Set connect sources with domain (delete-and-append avoids sed regex issues with nested quotes)
        # See: https://github.com/marketcalls/openalgo/issues/938
        sed -i '/^CSP_CONNECT_SRC/d' "$ENV_FILE"
        echo "CSP_CONNECT_SRC = \"'self' wss://$DOMAIN https://$DOMAIN wss: ws: https://cdn.socket.io\"" >> "$ENV_FILE"
        
        log "New .env created with fresh security keys" "$GREEN"
    fi

    # 6. Docker Compose
    # Both files below are about to be regenerated. A copy was taken before the
    # repository sync (see above) so a failed build can hand the instance back
    # its working routing before the shared Nginx reload at the end of the run.
    write_instance_compose "$INSTANCE_DIR/docker-compose.yaml"
    write_instance_profile "$INSTANCE_DIR" "$PROFILE"

    # 7. Nginx Config
    cat <<EOF > "$NGINX_SITES_AVAILABLE/$DOMAIN"
upstream openalgo_flask_${SANITIZED_NAME} {
    server 127.0.0.1:${FLASK_PORT};
    keepalive 64;
}

upstream openalgo_websocket_${SANITIZED_NAME} {
    server 127.0.0.1:${WS_PORT};
    keepalive 64;
}

server {
    listen 80;
    server_name $DOMAIN;

    # OPENALGO_WEBHOOK_LOG_GUARD: suppress URL-secret routes before redirect logs.
    set \$openalgo_loggable 1;
    if (\$uri ~ ^/(strategy|flow|chartink)/webhook/) {
        set \$openalgo_loggable 0;
    }
    access_log /var/log/nginx/${DOMAIN}_access.log combined if=\$openalgo_loggable;
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2;
    server_name $DOMAIN;

    # OPENALGO_WEBHOOK_LOG_GUARD: URL credentials never enter nginx access logs.
    set \$openalgo_loggable 1;
    if (\$uri ~ ^/(strategy|flow|chartink)/webhook/) {
        set \$openalgo_loggable 0;
    }
    access_log /var/log/nginx/${DOMAIN}_access.log combined if=\$openalgo_loggable;

    ssl_certificate $SSL_DIR/fullchain.pem;
    ssl_certificate_key $SSL_DIR/privkey.pem;
    
    # Modern SSL Config
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers EECDH+AESGCM:EDH+AESGCM;
    ssl_prefer_server_ciphers on;
    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL:10m;
    
    # Security Headers
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    
    client_max_body_size 50M;

    # Logic: WebSocket
    location = /ws {
        proxy_pass http://openalgo_websocket_${SANITIZED_NAME};
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_read_timeout 86400s;
    }
    location /ws/ {
        proxy_pass http://openalgo_websocket_${SANITIZED_NAME}/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_read_timeout 86400s;
    }

    # Logic: Socket.IO (Flask-SocketIO real-time events)
    location /socket.io/ {
        proxy_pass http://openalgo_flask_${SANITIZED_NAME}/socket.io/;
        proxy_http_version 1.1;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
        proxy_buffering off;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # Logic: Main App
    location / {
        proxy_pass http://openalgo_flask_${SANITIZED_NAME};
        proxy_http_version 1.1;
        proxy_read_timeout 300s;
        proxy_connect_timeout 300s;
        proxy_send_timeout 300s;

        # Increased buffer sizes for large headers (auth tokens, session cookies)
        proxy_buffer_size 128k;
        proxy_buffers 4 256k;
        proxy_busy_buffers_size 256k;

        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
    
    # Activate Nginx
    ln -sf "$NGINX_SITES_AVAILABLE/$DOMAIN" "$NGINX_SITES_ENABLED/"
    
    # 8. Service Start
    log "Starting Container for $DOMAIN..." "$BLUE"
    log "Building Docker image (includes automated frontend build, may take 2-5 minutes)..." "$YELLOW"
    cd "$INSTANCE_DIR"
    # Never start a container from a stale image. A failed build leaves the
    # PREVIOUS image still tagged, so an unconditional `docker compose up -d`
    # restarts the old code and every later message -- including
    # "INSTALLATION COMPLETE" -- reports success while nothing was updated.
    if ! docker compose build; then
        # Put the previous compose/Nginx files back before the reload, so this
        # domain keeps pointing at the ports its container is actually on.
        restore_instance_config "$INSTANCE_DIR" "$DOMAIN"
        log "Error: Docker image build FAILED for $DOMAIN." "$RED"
        if [ "$IS_UPDATE_MODE" == "true" ]; then
            log "       This instance was NOT updated. Its previous configuration" "$RED"
            log "       has been restored, so the container that was already" "$RED"
            log "       running stays reachable on its existing ports." "$RED"
        else
            log "       This instance was NOT installed. No container exists for" "$RED"
            log "       it, and its Nginx site has been removed." "$RED"
        fi
        FAILED_DOMAINS+=("$DOMAIN")
        continue
    fi
    # Deliberately no restore here. Compose has already acted on the new file,
    # so a container may exist -- stopped, or partially recreated -- on the new
    # ports. Reverting Nginx alone would guarantee a mismatch, and we cannot
    # claim the previous image is still serving.
    # The web server is written to .env only now that the image has built, so a
    # failed build never leaves .env asking for a server the running image may
    # not have. .env is bind-mounted, so changing it does not restart a running
    # container; a change of web server therefore forces a recreate.
    set_worker_class "$ENV_FILE" "$WORKER"
    set_git_info "$INSTANCE_DIR" "$ENV_FILE"
    UP_FLAGS=""
    if [ "$WORKER" != "$PREV_WORKER" ]; then
        UP_FLAGS="--force-recreate"
        log "Web server changes from $PREV_WORKER to $WORKER: recreating the container." "$YELLOW"
    fi
    if ! docker compose up -d $UP_FLAGS; then
        discard_instance_snapshot "$INSTANCE_DIR" "$DOMAIN"
        log "Error: Container failed to start for $DOMAIN." "$RED"
        log "       Check: cd $INSTANCE_DIR && docker compose logs" "$RED"
        FAILED_DOMAINS+=("$DOMAIN")
        continue
    fi
    discard_instance_snapshot "$INSTANCE_DIR" "$DOMAIN"

    # Confirm the container is on the web server .env asks for. Only when it
    # matters: gthread requested, or the web server just changed.
    if [ "$WORKER" = "gthread" ] || [ "$WORKER" != "$PREV_WORKER" ]; then
        verify_worker_started "$INSTANCE_DIR" "$WORKER"
        VERIFY_RC=$?
    else
        VERIFY_RC=skip
    fi
    case $VERIFY_RC in
        skip) ;;
        0) log "Verified: $DOMAIN is running on $WORKER." "$GREEN" ;;
        1)
            log "Error: $DOMAIN was asked to run $WORKER but started on the other web server." "$RED"
            if [ "$WORKER" = "gthread" ]; then
                log "       The image has no gthread launcher (an older OpenAlgo version or fork). Update the code and re-run." "$RED"
            fi
            FAILED_DOMAINS+=("$DOMAIN")
            ;;
        *) log "Warning: could not confirm the web server for $DOMAIN yet. Check: openalgo-ctl logs $DOMAIN" "$YELLOW" ;;
    esac
    
done

# Restart Nginx to load new configs
log "Reloading Nginx..." "$YELLOW"
nginx -t && systemctl reload nginx
check_status "Nginx reload failed"


# -----------------
# Management Tool
# -----------------

cat <<'EOF' > /usr/local/bin/openalgo-ctl
#!/bin/bash
# OpenAlgo Manager

INSTALL_BASE="/opt/openalgo"

cmd=$1
target=$2

list_instances() {
    echo "INSTALLED INSTANCES:"
    echo "--------------------"
    for d in $INSTALL_BASE/*/; do
        [ -d "$d" ] || continue
        dom=$(basename "$d")
        # skip backup folders
        if [[ "$dom" == *"_backup_"* ]]; then
             continue
        fi
        status=$(cd "$d" && docker compose ps --format "{{.Status}}" 2>/dev/null)
        echo "$dom : ${status:-STOPPED}"
    done
}

usage() {
    echo "Usage: openalgo-ctl <command> [domain]"
    echo "Commands:"
    echo "  list              - List all instances"
    echo "  restart <domain>  - Restart specific instance"
    echo "  logs <domain>     - Show logs for instance"
    echo "  status <domain>   - Show status"
    echo "  worker <domain> [gthread|eventlet]"
    echo "                    - Show the web server, or switch it (recreates the container)"
}

# Web server an instance is actually running, from the gunicorn process in its
# container. The start-up log line scrolls away on a container that has been up
# for days; the command line does not.
running_worker() {
    local cid
    cid=$(cd "$1" && docker compose ps -q 2>/dev/null | head -1)
    [ -n "$cid" ] || return 0
    docker top "$cid" -eo pid,args 2>/dev/null | grep -o -- '--worker-class [a-z]*' | head -1 | awk '{print $2}'
}

# Web server of an instance, as its .env asks for it
worker_of() {
    local v
    v=$(grep -E "^[[:space:]]*OPENALGO_WORKER_CLASS[[:space:]]*=" "$1/.env" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d " '\"")
    echo "${v:-eventlet}"
}

if [ "$cmd" == "list" ]; then
    list_instances
    exit 0
fi

if [ -z "$target" ]; then
    usage
    exit 1
fi

TARGET_DIR="$INSTALL_BASE/$target"
if [ ! -d "$TARGET_DIR" ]; then
    echo "Error: Instance $target not found."
    exit 1
fi

case "$cmd" in
    restart)
        cd "$TARGET_DIR" && docker compose restart
        ;;
    logs)
        cd "$TARGET_DIR" && docker compose logs -f --tail=100
        ;;
    status)
        cd "$TARGET_DIR" && docker compose ps
        ;;
    stop)
        cd "$TARGET_DIR" && docker compose stop
        ;;
    start)
        cd "$TARGET_DIR" && docker compose start
        ;;
    worker)
        wanted=$3
        asked=$(worker_of "$TARGET_DIR")
        running=$(running_worker "$TARGET_DIR")
        if [ -z "$wanted" ]; then
            echo "$target: .env asks for $asked; running on ${running:-unknown}"
            exit 0
        fi
        if [ "$wanted" != "gthread" ] && [ "$wanted" != "eventlet" ]; then
            echo "Error: choose gthread or eventlet."
            exit 1
        fi
        if [ "$wanted" == "$asked" ] && [ "$wanted" == "$running" ]; then
            echo "$target already runs on $wanted."
            exit 0
        fi
        if ! grep -q "stop_grace_period" "$TARGET_DIR/docker-compose.yaml"; then
            echo "Error: this instance's compose file has no stop_grace_period (required for gthread)."
            echo "       Re-run the installer for $target to regenerate it."
            exit 1
        fi
        hhmm=$((10#${OPENALGO_NOW_HHMM:-$(TZ=Asia/Kolkata date +%H%M)}))
        if [ "$hhmm" -ge 900 ] && [ "$hhmm" -lt 2330 ] && [ "$FORCE_WORKER_SWITCH" != "1" ]; then
            echo "It is trading time (09:00-23:30 IST). Switching restarts $target; strategies and market data pause for up to a minute."
            read -p "Switch anyway? (yes/no): " confirm
            [ "$confirm" == "yes" ] || { echo "Cancelled."; exit 0; }
        fi
        tmp=$(mktemp)
        grep -vE "^[[:space:]]*OPENALGO_WORKER_CLASS[[:space:]]*=" "$TARGET_DIR/.env" > "$tmp"
        printf "OPENALGO_WORKER_CLASS = '%s'\n" "$wanted" >> "$tmp"
        cat "$tmp" > "$TARGET_DIR/.env"
        rm -f "$tmp"
        cd "$TARGET_DIR" && docker compose up -d --force-recreate
        echo "Waiting for $target to start..."
        for _ in $(seq 1 24); do
            now=$(running_worker "$TARGET_DIR")
            [ -n "$now" ] && break
            sleep 5
        done
        echo "$target is now running on ${now:-unknown} (asked for $wanted)."
        [ "$now" == "$wanted" ] || exit 1
        ;;
    *)
        usage
        exit 1
        ;;
esac
EOF

chmod +x /usr/local/bin/openalgo-ctl


if [ ${#FAILED_DOMAINS[@]} -gt 0 ]; then
    log "\n==============================================" "$RED"
    log " INSTALLATION COMPLETED WITH ERRORS" "$RED"
    log "==============================================" "$RED"
    log "The following instances did not deploy successfully:" "$RED"
    for FAILED in "${FAILED_DOMAINS[@]}"; do
        log "  - $FAILED" "$RED"
    done
    log "Scroll up for the build error, fix it, then re-run this script." "$YELLOW"
else
    log "\n==============================================" "$GREEN"
    log " INSTALLATION COMPLETE" "$GREEN"
    log "==============================================" "$GREEN"
fi
log "Management Command: openalgo-ctl" "$BLUE"
log "  openalgo-ctl list" "$BLUE"
log "  openalgo-ctl restart <domain.com>" "$BLUE"
log "  openalgo-ctl logs <domain.com>" "$BLUE"

log "\n[IMPORTANT] CLOUD FIREWALL SETTINGS:" "$YELLOW"
log "Ensure the following Inbound Ports are OPEN in your Azure NSG / AWS Security Group:" "$RED"
log "  - TCP 80 (HTTP)" "$NC"
log "  - TCP 443 (HTTPS)" "$NC"
log "  - TCP 22 (SSH)" "$NC"
if [[ $INSTALL_PORTAINER =~ ^[Yy]$ ]]; then
    if [ -z "$PORTAINER_DOMAIN" ]; then
        log "  - TCP 9000 (Portainer UI)" "$NC"
    fi
fi
log "\nAccess your instances via their respective HTTPS domains." "$GREEN"

if [ ${#FAILED_DOMAINS[@]} -gt 0 ]; then
    exit 1
fi
