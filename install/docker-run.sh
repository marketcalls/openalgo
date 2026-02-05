#!/bin/bash
# ============================================================================
# OpenAlgo Docker Runner for macOS/Linux
# ============================================================================
#
# Quick Start (2 commands):
#   1. Download: curl -O https://raw.githubusercontent.com/marketcalls/openalgo/main/install/docker-run.sh && chmod +x docker-run.sh
#   2. Run:      ./docker-run.sh
#
# Commands:
#   start    - Start OpenAlgo container (default, runs setup if needed)
#   stop     - Stop and remove container
#   restart  - Restart container
#   logs     - View container logs (live)
#   pull     - Pull latest image from Docker Hub
#   status   - Show container status
#   shell    - Open bash shell in container
#   migrate  - Run database migrations manually
#   setup    - Re-run setup (regenerate keys, edit .env)
#   help     - Show this help
#
# Prerequisites:
#   - Docker Desktop installed and running
#
# ============================================================================

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
IMAGE="marketcalls/openalgo:latest"
CONTAINER="openalgo"
ENV_FILE=".env"
SAMPLE_ENV_URL="https://raw.githubusercontent.com/marketcalls/openalgo/main/.sample.env"
# Use the directory where the script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPENALGO_DIR="$SCRIPT_DIR"

# XTS Brokers that require market data credentials
XTS_BROKERS="fivepaisaxts,compositedge,ibulls,iifl,jainamxts,wisdom"

# Valid brokers list
VALID_BROKERS="fivepaisa,fivepaisaxts,aliceblue,angel,compositedge,definedge,dhan,dhan_sandbox,firstock,flattrade,fyers,groww,ibulls,iifl,indmoney,jainamxts,kotak,motilal,mstock,paytm,pocketful,samco,shoonya,tradejini,upstox,wisdom,zebu,zerodha"

# Banner
echo ""
echo -e "${BLUE}  ========================================${NC}"
echo -e "${BLUE}       OpenAlgo Docker Runner${NC}"
echo -e "${BLUE}       Desktop Edition (macOS/Linux)${NC}"
echo -e "${BLUE}  ========================================${NC}"
echo ""

# Function to print messages
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_ok() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

# Check if Docker is running
check_docker() {
    if ! docker info >/dev/null 2>&1; then
        log_error "Docker is not running!"
        echo ""
        echo "Please start Docker Desktop first:"
        if [[ "$OSTYPE" == "darwin"* ]]; then
            echo "  1. Open Docker Desktop from Applications"
        else
            echo "  1. Start Docker: sudo systemctl start docker"
            echo "     Or open Docker Desktop if using the desktop version"
        fi
        echo "  2. Wait for Docker to fully start"
        echo "  3. Run this script again"
        echo ""
        exit 1
    fi
}

# Validate broker name
validate_broker() {
    local broker=$1
    if [[ ",$VALID_BROKERS," == *",$broker,"* ]]; then
        return 0
    else
        return 1
    fi
}

# Check if broker is XTS based
is_xts_broker() {
    local broker=$1
    if [[ ",$XTS_BROKERS," == *",$broker,"* ]]; then
        return 0
    else
        return 1
    fi
}

# Setup function
do_setup() {
    log_info "Setting up OpenAlgo in $OPENALGO_DIR..."
    echo ""

    # Create db directory
    if [ ! -d "$OPENALGO_DIR/db" ]; then
        log_info "Creating database directory..."
        mkdir -p "$OPENALGO_DIR/db"
        if [ $? -ne 0 ]; then
            log_error "Failed to create database directory"
            return 1
        fi
    fi

    # Check if .env already exists
    if [ -f "$OPENALGO_DIR/$ENV_FILE" ]; then
        log_warn ".env file already exists at $OPENALGO_DIR/$ENV_FILE"
        read -p "Do you want to overwrite it? (y/n): " OVERWRITE
        if [[ ! "$OVERWRITE" =~ ^[Yy]$ ]]; then
            log_info "Setup cancelled. Using existing .env file."
            return 0
        fi
    fi

    # Download sample.env from GitHub
    log_info "Downloading configuration template from GitHub..."
    if ! curl -sL "$SAMPLE_ENV_URL" -o "$OPENALGO_DIR/$ENV_FILE"; then
        log_error "Failed to download configuration template!"
        echo "Please check your internet connection."
        return 1
    fi
    log_ok "Configuration template downloaded."

    # Generate random keys
    log_info "Generating secure keys..."

    # Check if Python is available
    if command -v python3 &> /dev/null; then
        PYTHON_CMD="python3"
    elif command -v python &> /dev/null; then
        PYTHON_CMD="python"
    else
        log_warn "Python not found. Using openssl for key generation."
        APP_KEY=$(openssl rand -hex 32)
        API_KEY_PEPPER=$(openssl rand -hex 32)
        if [ -z "$APP_KEY" ] || [ -z "$API_KEY_PEPPER" ]; then
            log_error "Failed to generate keys. Please install Python or openssl."
            return 1
        fi
    fi

    if [ -z "$APP_KEY" ]; then
        APP_KEY=$($PYTHON_CMD -c "import secrets; print(secrets.token_hex(32))")
        API_KEY_PEPPER=$($PYTHON_CMD -c "import secrets; print(secrets.token_hex(32))")
    fi

    # Update .env file with generated keys
    log_info "Updating configuration with secure keys..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS sed syntax
        sed -i '' "s/3daa0403ce2501ee7432b75bf100048e3cf510d63d2754f952e93d88bf07ea84/$APP_KEY/g" "$OPENALGO_DIR/$ENV_FILE"
        sed -i '' "s/a25d94718479b170c16278e321ea6c989358bf499a658fd20c90033cef8ce772/$API_KEY_PEPPER/g" "$OPENALGO_DIR/$ENV_FILE"
    else
        # Linux sed syntax
        sed -i "s/3daa0403ce2501ee7432b75bf100048e3cf510d63d2754f952e93d88bf07ea84/$APP_KEY/g" "$OPENALGO_DIR/$ENV_FILE"
        sed -i "s/a25d94718479b170c16278e321ea6c989358bf499a658fd20c90033cef8ce772/$API_KEY_PEPPER/g" "$OPENALGO_DIR/$ENV_FILE"
    fi
    log_ok "Secure keys generated and saved."

    # Get broker configuration
    echo ""
    echo -e "${BLUE}  ========================================${NC}"
    echo -e "${BLUE}  Broker Configuration${NC}"
    echo -e "${BLUE}  ========================================${NC}"
    echo ""
    echo "  Valid brokers:"
    echo "  fivepaisa, fivepaisaxts, aliceblue, angel, compositedge,"
    echo "  definedge, dhan, dhan_sandbox, firstock, flattrade, fyers,"
    echo "  groww, ibulls, iifl, indmoney, jainamxts, kotak, motilal,"
    echo "  mstock, paytm, pocketful, samco, shoonya, tradejini,"
    echo "  upstox, wisdom, zebu, zerodha"
    echo ""

    # Get broker name with validation
    while true; do
        read -p "Enter broker name (e.g., zerodha, fyers, angel): " BROKER_NAME
        if validate_broker "$BROKER_NAME"; then
            break
        else
            log_error "Invalid broker: $BROKER_NAME"
            echo "Please enter a valid broker name from the list above."
        fi
    done
    log_ok "Broker: $BROKER_NAME"

    # Get broker API credentials
    echo ""
    read -p "Enter your $BROKER_NAME API Key: " BROKER_API_KEY
    read -p "Enter your $BROKER_NAME API Secret: " BROKER_API_SECRET

    if [ -z "$BROKER_API_KEY" ]; then
        log_error "API Key is required!"
        return 1
    fi

    if [ -z "$BROKER_API_SECRET" ]; then
        log_error "API Secret is required!"
        return 1
    fi

    # Check if XTS broker (requires market data credentials)
    IS_XTS=0
    if is_xts_broker "$BROKER_NAME"; then
        IS_XTS=1
        echo ""
        log_info "$BROKER_NAME is an XTS-based broker."
        echo "       Additional market data credentials are required."
        echo ""
        read -p "Enter Market Data API Key: " BROKER_API_KEY_MARKET
        read -p "Enter Market Data API Secret: " BROKER_API_SECRET_MARKET

        if [ -z "$BROKER_API_KEY_MARKET" ]; then
            log_error "Market Data API Key is required for XTS brokers!"
            return 1
        fi
        if [ -z "$BROKER_API_SECRET_MARKET" ]; then
            log_error "Market Data API Secret is required for XTS brokers!"
            return 1
        fi
    fi

    # Update .env with broker configuration
    echo ""
    log_info "Updating broker configuration..."

    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS sed syntax
        sed -i '' "s/BROKER_API_KEY = 'YOUR_BROKER_API_KEY'/BROKER_API_KEY = '$BROKER_API_KEY'/g" "$OPENALGO_DIR/$ENV_FILE"
        sed -i '' "s/BROKER_API_SECRET = 'YOUR_BROKER_API_SECRET'/BROKER_API_SECRET = '$BROKER_API_SECRET'/g" "$OPENALGO_DIR/$ENV_FILE"
        sed -i '' "s|<broker>|$BROKER_NAME|g" "$OPENALGO_DIR/$ENV_FILE"

        if [ "$IS_XTS" -eq 1 ]; then
            sed -i '' "s/BROKER_API_KEY_MARKET = 'YOUR_BROKER_MARKET_API_KEY'/BROKER_API_KEY_MARKET = '$BROKER_API_KEY_MARKET'/g" "$OPENALGO_DIR/$ENV_FILE"
            sed -i '' "s/BROKER_API_SECRET_MARKET = 'YOUR_BROKER_MARKET_API_SECRET'/BROKER_API_SECRET_MARKET = '$BROKER_API_SECRET_MARKET'/g" "$OPENALGO_DIR/$ENV_FILE"
        fi
    else
        # Linux sed syntax
        sed -i "s/BROKER_API_KEY = 'YOUR_BROKER_API_KEY'/BROKER_API_KEY = '$BROKER_API_KEY'/g" "$OPENALGO_DIR/$ENV_FILE"
        sed -i "s/BROKER_API_SECRET = 'YOUR_BROKER_API_SECRET'/BROKER_API_SECRET = '$BROKER_API_SECRET'/g" "$OPENALGO_DIR/$ENV_FILE"
        sed -i "s|<broker>|$BROKER_NAME|g" "$OPENALGO_DIR/$ENV_FILE"

        if [ "$IS_XTS" -eq 1 ]; then
            sed -i "s/BROKER_API_KEY_MARKET = 'YOUR_BROKER_MARKET_API_KEY'/BROKER_API_KEY_MARKET = '$BROKER_API_KEY_MARKET'/g" "$OPENALGO_DIR/$ENV_FILE"
            sed -i "s/BROKER_API_SECRET_MARKET = 'YOUR_BROKER_MARKET_API_SECRET'/BROKER_API_SECRET_MARKET = '$BROKER_API_SECRET_MARKET'/g" "$OPENALGO_DIR/$ENV_FILE"
        fi
    fi

    log_ok "Broker configuration saved."

    echo ""
    echo -e "${GREEN}  ========================================${NC}"
    echo -e "${GREEN}  Setup Complete!${NC}"
    echo -e "${GREEN}  ========================================${NC}"
    echo ""
    echo "  Broker:         $BROKER_NAME"
    if [ "$IS_XTS" -eq 1 ]; then
        echo "  Type:           XTS API (with market data)"
    fi
    echo "  Data directory: $OPENALGO_DIR"
    echo "  Config file:    $OPENALGO_DIR/$ENV_FILE"
    echo "  Database:       $OPENALGO_DIR/db/"
    echo "  Strategies:     $OPENALGO_DIR/strategies/"
    echo "  Logs:           $OPENALGO_DIR/log/"
    echo ""
    echo "  Redirect URL for broker portal:"
    echo "  http://127.0.0.1:5000/$BROKER_NAME/callback"
    echo ""
    echo "  Documentation: https://docs.openalgo.in"
    echo ""

    # Try to open .env in editor (non-blocking)
    read -p "Open .env in editor for review? (y/n): " OPEN_EDITOR
    if [[ "$OPEN_EDITOR" =~ ^[Yy]$ ]]; then
        if [[ "$OSTYPE" == "darwin"* ]]; then
            open -t "$OPENALGO_DIR/$ENV_FILE"
        elif command -v xdg-open &> /dev/null; then
            # Linux with desktop environment - non-blocking
            xdg-open "$OPENALGO_DIR/$ENV_FILE" &>/dev/null &
        elif command -v gedit &> /dev/null; then
            gedit "$OPENALGO_DIR/$ENV_FILE" &>/dev/null &
        elif command -v code &> /dev/null; then
            code "$OPENALGO_DIR/$ENV_FILE"
        else
            echo "  Edit .env manually: $OPENALGO_DIR/$ENV_FILE"
        fi
    fi

    echo ""
    log_ok "Setup complete! Run './docker-run.sh start' to launch OpenAlgo."
    echo ""
    return 0
}

# Start function
do_start() {
    log_info "Starting OpenAlgo..."
    echo ""

    # Check if setup is needed
    if [ ! -f "$OPENALGO_DIR/$ENV_FILE" ]; then
        log_info "First time setup detected. Running setup..."
        echo ""
        if ! do_setup; then
            echo ""
            log_error "Setup failed. Cannot start OpenAlgo."
            echo "Please fix the issues above and try again."
            exit 1
        fi
        echo ""
        log_info "Starting OpenAlgo after setup..."
        echo ""
    fi

    # Create db, strategies, log, keys, and tmp directories if not exist
    if [ ! -d "$OPENALGO_DIR/db" ]; then
        log_info "Creating database directory..."
        mkdir -p "$OPENALGO_DIR/db"
    fi
    if [ ! -d "$OPENALGO_DIR/strategies" ]; then
        log_info "Creating strategies directory..."
        mkdir -p "$OPENALGO_DIR/strategies/scripts"
        mkdir -p "$OPENALGO_DIR/strategies/examples"
    fi
    if [ ! -d "$OPENALGO_DIR/log" ]; then
        log_info "Creating log directory..."
        mkdir -p "$OPENALGO_DIR/log/strategies"
    fi
    if [ ! -d "$OPENALGO_DIR/keys" ]; then
        log_info "Creating keys directory..."
        mkdir -p "$OPENALGO_DIR/keys"
    fi
    if [ ! -d "$OPENALGO_DIR/tmp" ]; then
        log_info "Creating temp directory..."
        mkdir -p "$OPENALGO_DIR/tmp"
    fi

    # Pull latest image
    log_info "Pulling latest image..."
    if ! docker pull "$IMAGE"; then
        log_warn "Could not pull latest image. Using cached version if available."
    fi

    # Stop and remove existing container if exists
    docker stop "$CONTAINER" >/dev/null 2>&1
    docker rm "$CONTAINER" >/dev/null 2>&1

    # Calculate dynamic resource limits based on available RAM
    if [[ "$OSTYPE" == "darwin"* ]]; then
        TOTAL_RAM_MB=$(($(sysctl -n hw.memsize) / 1024 / 1024))
        CPU_CORES=$(sysctl -n hw.ncpu 2>/dev/null || echo 2)
    else
        TOTAL_RAM_MB=$(($(grep MemTotal /proc/meminfo | awk '{print $2}') / 1024))
        CPU_CORES=$(nproc 2>/dev/null || echo 2)
    fi

    # shm_size: 25% of RAM (min 256MB, max 2GB)
    SHM_SIZE_MB=$((TOTAL_RAM_MB / 4))
    [ $SHM_SIZE_MB -lt 256 ] && SHM_SIZE_MB=256
    [ $SHM_SIZE_MB -gt 2048 ] && SHM_SIZE_MB=2048

    # Thread limits based on RAM (prevents RLIMIT_NPROC exhaustion)
    # <3GB: 1 thread | 3-6GB: 2 threads | 6GB+: min(4, cores)
    # See: https://github.com/marketcalls/openalgo/issues/822
    if [ $TOTAL_RAM_MB -lt 3000 ]; then
        THREAD_LIMIT=1
    elif [ $TOTAL_RAM_MB -lt 6000 ]; then
        THREAD_LIMIT=2
    else
        THREAD_LIMIT=$((CPU_CORES < 4 ? CPU_CORES : 4))
    fi

    # Strategy memory limit based on RAM
    # <3GB: 256MB | 3-6GB: 512MB | 6GB+: 1024MB
    if [ $TOTAL_RAM_MB -lt 3000 ]; then
        STRATEGY_MEM_LIMIT=256
    elif [ $TOTAL_RAM_MB -lt 6000 ]; then
        STRATEGY_MEM_LIMIT=512
    else
        STRATEGY_MEM_LIMIT=1024
    fi

    log_info "System: ${TOTAL_RAM_MB}MB RAM, ${CPU_CORES} cores"
    log_info "Config: shm=${SHM_SIZE_MB}MB, threads=${THREAD_LIMIT}, strategy_mem=${STRATEGY_MEM_LIMIT}MB"

    # Run container
    log_info "Starting container..."
    if docker run -d \
        --name "$CONTAINER" \
        --shm-size=${SHM_SIZE_MB}m \
        -p 5000:5000 \
        -p 8765:8765 \
        -e "OPENBLAS_NUM_THREADS=${THREAD_LIMIT}" \
        -e "OMP_NUM_THREADS=${THREAD_LIMIT}" \
        -e "MKL_NUM_THREADS=${THREAD_LIMIT}" \
        -e "NUMEXPR_NUM_THREADS=${THREAD_LIMIT}" \
        -e "NUMBA_NUM_THREADS=${THREAD_LIMIT}" \
        -e "STRATEGY_MEMORY_LIMIT_MB=${STRATEGY_MEM_LIMIT}" \
        -e "TZ=Asia/Kolkata" \
        -v "$OPENALGO_DIR/db:/app/db" \
        -v "$OPENALGO_DIR/strategies:/app/strategies" \
        -v "$OPENALGO_DIR/log:/app/log" \
        -v "$OPENALGO_DIR/keys:/app/keys" \
        -v "$OPENALGO_DIR/tmp:/app/tmp" \
        -v "$OPENALGO_DIR/.env:/app/.env:ro" \
        --restart unless-stopped \
        "$IMAGE"; then

        echo ""
        log_success "OpenAlgo started successfully!"
        echo ""
        echo -e "${GREEN}  ========================================${NC}"
        echo -e "${GREEN}  Web UI:     http://127.0.0.1:5000${NC}"
        echo -e "${GREEN}  WebSocket:  ws://127.0.0.1:8765${NC}"
        echo -e "${GREEN}  ========================================${NC}"
        echo ""
        echo "  Data directory: $OPENALGO_DIR"
        echo ""
        echo "  Useful commands:"
        echo "    ./docker-run.sh logs     - View logs"
        echo "    ./docker-run.sh stop     - Stop OpenAlgo"
        echo "    ./docker-run.sh restart  - Restart OpenAlgo"
        echo ""
    else
        echo ""
        log_error "Failed to start container!"
        echo ""
        echo "Troubleshooting:"
        echo "  1. Check if ports 5000 and 8765 are available"
        echo "  2. Ensure Docker Desktop is running"
        echo "  3. Check .env file: $OPENALGO_DIR/$ENV_FILE"
        echo ""
        exit 1
    fi
}

# Stop function
do_stop() {
    log_info "Stopping OpenAlgo..."
    docker stop "$CONTAINER" >/dev/null 2>&1
    docker rm "$CONTAINER" >/dev/null 2>&1
    log_ok "OpenAlgo stopped."
}

# Restart function
do_restart() {
    log_info "Restarting OpenAlgo..."
    do_stop
    echo ""
    do_start
}

# Logs function
do_logs() {
    log_info "Showing logs (Press Ctrl+C to exit)..."
    echo ""
    docker logs -f "$CONTAINER"
}

# Pull function
do_pull() {
    log_info "Pulling latest image..."
    if docker pull "$IMAGE"; then
        log_ok "Image updated successfully."
        log_info "Run './docker-run.sh restart' to apply the update."
    else
        log_error "Failed to pull image."
        exit 1
    fi
}

# Status function
do_status() {
    log_info "Container status:"
    echo ""
    docker ps -a --filter "name=$CONTAINER" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    echo ""

    # Check if container is running
    if docker ps --filter "name=$CONTAINER" --filter "status=running" | grep -q "$CONTAINER"; then
        echo -e "${GREEN}[STATUS]${NC} OpenAlgo is running."
        echo ""
        echo "  Web UI: http://127.0.0.1:5000"
    else
        echo -e "${YELLOW}[STATUS]${NC} OpenAlgo is NOT running."
    fi
    echo ""
    echo "  Data directory: $OPENALGO_DIR"
}

# Shell function
do_shell() {
    log_info "Opening shell in container..."
    docker exec -it "$CONTAINER" /bin/bash
}

# Migrate function
do_migrate() {
    log_info "Running database migrations..."
    docker exec -it "$CONTAINER" /app/.venv/bin/python /app/upgrade/migrate_all.py
    if [ $? -eq 0 ]; then
        log_ok "Migrations completed successfully."
    else
        log_warn "Some migrations may have had issues. Check the output above."
    fi
}

# Help function
do_help() {
    echo ""
    echo "Usage: ./docker-run.sh [command]"
    echo ""
    echo "Commands:"
    echo "  start    Start OpenAlgo (runs setup if needed, default)"
    echo "  stop     Stop and remove container"
    echo "  restart  Restart container"
    echo "  logs     View container logs (live)"
    echo "  pull     Pull latest image from Docker Hub"
    echo "  status   Show container status"
    echo "  shell    Open bash shell in container"
    echo "  migrate  Run database migrations manually"
    echo "  setup    Re-run setup (regenerate keys, edit .env)"
    echo "  help     Show this help"
    echo ""
    echo "Quick Start:"
    echo "  1. Install Docker Desktop:"
    echo "     macOS: https://docs.docker.com/desktop/install/mac-install/"
    echo "     Linux: https://docs.docker.com/desktop/install/linux-install/"
    echo ""
    echo "  2. Download and run:"
    echo "     curl -O https://raw.githubusercontent.com/marketcalls/openalgo/main/install/docker-run.sh"
    echo "     chmod +x docker-run.sh"
    echo "     ./docker-run.sh"
    echo ""
    echo "Data Location: $OPENALGO_DIR"
    echo "  - Config:     $OPENALGO_DIR/.env"
    echo "  - Database:   $OPENALGO_DIR/db/"
    echo "  - Strategies: $OPENALGO_DIR/strategies/"
    echo "  - Logs:       $OPENALGO_DIR/log/"
    echo ""
    echo "XTS Brokers (require market data credentials):"
    echo "  fivepaisaxts, compositedge, ibulls, iifl, jainamxts, wisdom"
    echo ""
}

# Check Docker is running (except for help)
CMD="${1:-start}"
if [[ "$CMD" != "help" && "$CMD" != "--help" && "$CMD" != "-h" ]]; then
    check_docker
fi

# Parse command
case "$CMD" in
    start)
        do_start
        ;;
    stop)
        do_stop
        ;;
    restart)
        do_restart
        ;;
    logs)
        do_logs
        ;;
    pull)
        do_pull
        ;;
    status)
        do_status
        ;;
    shell)
        do_shell
        ;;
    migrate)
        do_migrate
        ;;
    setup)
        do_setup
        ;;
    help|--help|-h)
        do_help
        ;;
    *)
        log_error "Unknown command: $CMD"
        do_help
        exit 1
        ;;
esac
