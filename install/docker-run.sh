#!/bin/bash
# ============================================================================
# OpenAlgo Docker Runner for macOS/Linux
# ============================================================================
#
# Usage: ./docker-run.sh [command]
#
# Commands:
#   start    - Start OpenAlgo container (default)
#   stop     - Stop and remove container
#   restart  - Restart container
#   logs     - View container logs (live)
#   pull     - Pull latest image from Docker Hub
#   status   - Show container status
#   shell    - Open bash shell in container
#   setup    - Initial setup (create .env from sample)
#   help     - Show this help
#
# Prerequisites:
#   1. Docker Desktop installed and running
#   2. .env file configured (run './docker-run.sh setup' first)
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
SAMPLE_ENV=".sample.env"

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Go to parent directory (project root)
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

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

# Setup function
do_setup() {
    log_info "Setting up OpenAlgo..."
    echo ""

    # Check if .env already exists
    if [ -f "$PROJECT_DIR/$ENV_FILE" ]; then
        log_warn ".env file already exists!"
        read -p "Do you want to overwrite it? (y/n): " OVERWRITE
        if [[ ! "$OVERWRITE" =~ ^[Yy]$ ]]; then
            log_info "Setup cancelled. Using existing .env file."
            exit 0
        fi
    fi

    # Check if sample.env exists
    if [ ! -f "$PROJECT_DIR/$SAMPLE_ENV" ]; then
        log_error "$SAMPLE_ENV not found!"
        echo "Please ensure you are in the OpenAlgo project directory."
        exit 1
    fi

    # Copy sample.env to .env
    cp "$PROJECT_DIR/$SAMPLE_ENV" "$PROJECT_DIR/$ENV_FILE"
    log_ok "Created .env from $SAMPLE_ENV"

    # Generate random keys
    log_info "Generating secure keys..."

    # Check if Python is available
    if command -v python3 &> /dev/null; then
        PYTHON_CMD="python3"
    elif command -v python &> /dev/null; then
        PYTHON_CMD="python"
    else
        log_error "Python is not installed. Please install Python 3.x"
        echo ""
        echo "Generated keys (copy these manually to .env):"
        echo "  APP_KEY=$(openssl rand -hex 32 2>/dev/null || head -c 64 /dev/urandom | xxd -p | tr -d '\n')"
        echo "  API_KEY_PEPPER=$(openssl rand -hex 32 2>/dev/null || head -c 64 /dev/urandom | xxd -p | tr -d '\n')"
        echo ""
        exit 1
    fi

    APP_KEY=$($PYTHON_CMD -c "import secrets; print(secrets.token_hex(32))")
    API_KEY_PEPPER=$($PYTHON_CMD -c "import secrets; print(secrets.token_hex(32))")

    # Display keys for manual update
    echo ""
    echo -e "${YELLOW}[IMPORTANT]${NC} Add these keys to your .env file:"
    echo ""
    echo "  APP_KEY=$APP_KEY"
    echo "  API_KEY_PEPPER=$API_KEY_PEPPER"
    echo ""
    log_info "Please update your .env file with:"
    echo "  1. APP_KEY and API_KEY_PEPPER with the values above"
    echo "  2. BROKER_API_KEY and BROKER_API_SECRET with your broker credentials"
    echo "  3. Any other settings as needed"
    echo ""

    # Try to open .env in editor
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS - use open with default text editor
        read -p "Open .env in your default editor? (y/n): " OPEN_EDITOR
        if [[ "$OPEN_EDITOR" =~ ^[Yy]$ ]]; then
            open -t "$PROJECT_DIR/$ENV_FILE"
        fi
    else
        # Linux - try common editors
        if command -v nano &> /dev/null; then
            read -p "Open .env in nano? (y/n): " OPEN_EDITOR
            if [[ "$OPEN_EDITOR" =~ ^[Yy]$ ]]; then
                nano "$PROJECT_DIR/$ENV_FILE"
            fi
        elif command -v vim &> /dev/null; then
            read -p "Open .env in vim? (y/n): " OPEN_EDITOR
            if [[ "$OPEN_EDITOR" =~ ^[Yy]$ ]]; then
                vim "$PROJECT_DIR/$ENV_FILE"
            fi
        else
            echo "Edit .env manually: $PROJECT_DIR/$ENV_FILE"
        fi
    fi

    echo ""
    log_ok "Setup complete! Run './docker-run.sh start' to launch OpenAlgo."
}

# Start function
do_start() {
    log_info "Starting OpenAlgo..."
    echo ""

    # Check if .env exists
    if [ ! -f "$PROJECT_DIR/$ENV_FILE" ]; then
        log_error ".env file not found!"
        echo ""
        echo "Please run setup first:"
        echo "  ./docker-run.sh setup"
        echo ""
        exit 1
    fi

    # Create db directory if not exists
    if [ ! -d "$PROJECT_DIR/db" ]; then
        log_info "Creating db directory..."
        mkdir -p "$PROJECT_DIR/db"
    fi

    # Pull latest image
    log_info "Pulling latest image..."
    if ! docker pull "$IMAGE"; then
        log_warn "Could not pull latest image. Using cached version if available."
    fi

    # Stop and remove existing container if exists
    docker stop "$CONTAINER" >/dev/null 2>&1
    docker rm "$CONTAINER" >/dev/null 2>&1

    # Run container
    log_info "Starting container..."
    if docker run -d \
        --name "$CONTAINER" \
        -p 5000:5000 \
        -p 8765:8765 \
        -v "$PROJECT_DIR/db:/app/db" \
        -v "$PROJECT_DIR/.env:/app/.env:ro" \
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
        echo "  3. Check .env file for errors"
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
}

# Shell function
do_shell() {
    log_info "Opening shell in container..."
    docker exec -it "$CONTAINER" /bin/bash
}

# Help function
do_help() {
    echo ""
    echo "Usage: ./docker-run.sh [command]"
    echo ""
    echo "Commands:"
    echo "  start    Start OpenAlgo container (default)"
    echo "  stop     Stop and remove container"
    echo "  restart  Restart container"
    echo "  logs     View container logs (live)"
    echo "  pull     Pull latest image from Docker Hub"
    echo "  status   Show container status"
    echo "  shell    Open bash shell in container"
    echo "  setup    Initial setup (create .env from sample)"
    echo "  help     Show this help"
    echo ""
    echo "Prerequisites:"
    echo "  1. Docker Desktop installed and running"
    echo "     macOS: https://docs.docker.com/desktop/install/mac-install/"
    echo "     Linux: https://docs.docker.com/desktop/install/linux-install/"
    echo ""
    echo "  2. .env file configured"
    echo "     Run './docker-run.sh setup' for initial configuration"
    echo ""
    echo "Examples:"
    echo "  ./docker-run.sh setup     First time setup"
    echo "  ./docker-run.sh start     Start OpenAlgo"
    echo "  ./docker-run.sh logs      View live logs"
    echo "  ./docker-run.sh restart   Restart after config changes"
    echo ""
}

# Check Docker is running (except for help)
CMD="${1:-start}"
if [[ "$CMD" != "help" ]]; then
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
