#!/bin/bash
# OpenAlgo Docker Build and Deployment Script
# This script builds and deploys OpenAlgo with numba/llvmlite support

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
IMAGE_NAME="openalgo"
IMAGE_TAG="latest"
CONTAINER_NAME="openalgo-web"

# Functions
print_header() {
    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}\n"
}

print_success() {
    echo -e "${GREEN}[OK] $1${NC}"
}

print_error() {
    echo -e "${RED}[ERROR] $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}[WARNING] $1${NC}"
}

print_info() {
    echo -e "${BLUE}[INFO] $1${NC}"
}

# True when .env names a broker in REDIRECT_URL. Empty, or the "<broker>"
# placeholder of an unchanged .sample.env, means no broker: the trader sets up
# brokers in OpenAlgo (Broker Configuration) instead. The backend reads it the same way.
env_sets_broker() {
    grep -qE "^[[:space:]]*REDIRECT_URL[[:space:]]*=[[:space:]]*['\"]?[^'\"[:space:]#]" .env 2>/dev/null \
        && ! grep -qE "^[[:space:]]*REDIRECT_URL[[:space:]]*=.*<broker>" .env 2>/dev/null
}

# A random hex string of $1 bytes
new_hex() {
    python3 -c "import secrets; print(secrets.token_hex($1))" 2>/dev/null || openssl rand -hex "$1"
}

# Create .env from .sample.env for a new install: fresh security keys, no
# broker (the trader adds broker keys in OpenAlgo after signing in), and the
# container bindings docker-compose.yaml needs. It must exist before
# `docker-compose up`, or Docker creates a folder named .env in its place.
create_env_file() {
    if [ ! -f ".sample.env" ]; then
        print_error ".sample.env not found. Run this script from the OpenAlgo folder."
        return 1
    fi

    # A database left in the Docker volume belongs to keys that are gone with
    # the old .env; new keys would make its passwords and broker keys unreadable.
    local project
    project=$(basename "$PWD" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9_-]//g')
    if docker volume inspect "${COMPOSE_PROJECT_NAME:-$project}_openalgo_db" >/dev/null 2>&1; then
        print_error ".env file not found, but an OpenAlgo database already exists in Docker."
        print_info "Restore the .env you used before (its keys protect your saved data), then run this script again."
        return 1
    fi

    local app_key pepper salt
    app_key=$(new_hex 32)
    pepper=$(new_hex 32)
    salt=$(new_hex 16)
    if [ -z "$app_key" ] || [ -z "$pepper" ] || [ -z "$salt" ]; then
        print_error "Could not generate security keys. Install Python 3 or openssl and run this script again."
        return 1
    fi

    if ! ( umask 077 && sed \
        -e "s|^BROKER_API_KEY *=.*|BROKER_API_KEY = ''|" \
        -e "s|^BROKER_API_SECRET *=.*|BROKER_API_SECRET = ''|" \
        -e "s|^BROKER_API_KEY_MARKET *=.*|BROKER_API_KEY_MARKET = ''|" \
        -e "s|^BROKER_API_SECRET_MARKET *=.*|BROKER_API_SECRET_MARKET = ''|" \
        -e "s|^REDIRECT_URL *=.*|REDIRECT_URL = ''|" \
        -e "s|OPENALGO_PLACEHOLDER_APP_KEY_REGENERATE_BEFORE_USE|$app_key|" \
        -e "s|OPENALGO_PLACEHOLDER_API_KEY_PEPPER_REGENERATE_BEFORE_USE|$pepper|" \
        -e "s|OPENALGO_PLACEHOLDER_FERNET_SALT_REGENERATE_BEFORE_USE|$salt|" \
        -e "s|WEBSOCKET_HOST='127.0.0.1'|WEBSOCKET_HOST='0.0.0.0'|" \
        -e "s|FLASK_HOST_IP='127.0.0.1'|FLASK_HOST_IP='0.0.0.0'|" \
        .sample.env > .env.new && mv .env.new .env ); then
        rm -f .env.new
        print_error "Could not create .env in $PWD"
        return 1
    fi

    # The container runs as UID 1000 and must read and write .env (see
    # docker-compose.yaml). On Linux that needs the file owned by UID 1000;
    # Docker Desktop on macOS maps ownership itself.
    if [ "$(uname)" = "Linux" ] && [ "$(id -u)" -ne 1000 ]; then
        local owned="no"
        if [ "$(id -u)" -eq 0 ]; then
            chown 1000:1000 .env 2>/dev/null && owned="yes"
        elif command -v sudo >/dev/null 2>&1; then
            sudo chown 1000:1000 .env 2>/dev/null && owned="yes"
        fi
        if [ "$owned" != "yes" ]; then
            print_warning "The container cannot read .env until it belongs to user 1000. Run:"
            print_warning "  sudo chown 1000:1000 $PWD/.env"
        fi
    fi

    print_success "Created .env with new security keys and no broker"
    print_info "Back up .env: its keys protect your saved passwords and broker keys."
    return 0
}

# Check if .env exists
check_env_file() {
    print_header "Checking Environment Configuration"

    if [ -d ".env" ]; then
        print_error ".env is a folder, not a file. Docker created it because .env was missing."
        print_info "Delete the empty .env folder and run this script again; it creates the file."
        exit 1
    fi

    if [ ! -f ".env" ]; then
        print_info ".env file not found. Creating it from .sample.env..."
        create_env_file || exit 1
    fi

    print_success ".env file found"

    # Check critical variables
    if grep -q "YOUR_BROKER_API_KEY" .env 2>/dev/null; then
        print_info "The broker lines in .env still hold the sample placeholders, so no broker is set"
        print_info "there. Add your broker in OpenAlgo under Broker Configuration after you sign in."
    fi

    # Display broker configuration (without secrets)
    if ! env_sets_broker; then
        print_info "No broker in .env. Sign in to OpenAlgo and add your broker keys in Broker Configuration."
    elif grep -q "REDIRECT_URL.*fyers" .env; then
        print_info "Detected broker: Fyers"
    elif grep -q "REDIRECT_URL.*zerodha" .env; then
        print_info "Detected broker: Zerodha"
    elif grep -q "REDIRECT_URL.*angel" .env; then
        print_info "Detected broker: Angel One"
    else
        print_info "Broker configuration detected in .env"
    fi
}

# Stop and remove existing container
cleanup_existing() {
    print_header "Cleaning Up Existing Containers"

    if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        print_info "Stopping existing container: ${CONTAINER_NAME}"
        docker-compose down 2>/dev/null || docker stop ${CONTAINER_NAME} 2>/dev/null || true
        print_success "Existing container stopped"
    else
        print_info "No existing container found"
    fi
}

# Build Docker image
build_image() {
    print_header "Building Docker Image"

    print_info "Building ${IMAGE_NAME}:${IMAGE_TAG} with numba/llvmlite support..."
    print_info "This may take 5-10 minutes depending on your system..."

    # Build with docker-compose (recommended)
    if [ -f "docker-compose.yaml" ]; then
        print_info "Using docker-compose build..."
        docker-compose build --no-cache
        print_success "Docker image built successfully via docker-compose"
    else
        # Fallback to direct docker build
        print_info "Using docker build..."
        docker build \
            --no-cache \
            --tag ${IMAGE_NAME}:${IMAGE_TAG} \
            --build-arg BUILDKIT_INLINE_CACHE=1 \
            .
        print_success "Docker image built successfully via docker build"
    fi

    # Display image info
    IMAGE_SIZE=$(docker images ${IMAGE_NAME}:${IMAGE_TAG} --format "{{.Size}}")
    print_info "Image size: ${IMAGE_SIZE}"
}

# Verify image dependencies
verify_dependencies() {
    print_header "Verifying Dependencies"

    print_info "Checking if runtime libraries are installed..."

    # Create temporary container to check
    TEMP_CONTAINER=$(docker run -d ${IMAGE_NAME}:${IMAGE_TAG} sleep 10)

    # Check for required libraries
    if docker exec ${TEMP_CONTAINER} dpkg -l | grep -q "libopenblas0"; then
        print_success "libopenblas0 installed"
    else
        print_error "libopenblas0 missing"
    fi

    if docker exec ${TEMP_CONTAINER} dpkg -l | grep -q "libgomp1"; then
        print_success "libgomp1 installed"
    else
        print_error "libgomp1 missing"
    fi

    if docker exec ${TEMP_CONTAINER} dpkg -l | grep -q "libgfortran5"; then
        print_success "libgfortran5 installed"
    else
        print_error "libgfortran5 missing"
    fi

    # Check environment variables
    print_info "Checking environment variables..."
    if docker exec ${TEMP_CONTAINER} env | grep -q "TMPDIR=/app/tmp"; then
        print_success "TMPDIR configured correctly"
    else
        print_error "TMPDIR not set"
    fi

    if docker exec ${TEMP_CONTAINER} env | grep -q "NUMBA_CACHE_DIR=/app/tmp/numba_cache"; then
        print_success "NUMBA_CACHE_DIR configured correctly"
    else
        print_error "NUMBA_CACHE_DIR not set"
    fi

    # Cleanup temp container
    docker stop ${TEMP_CONTAINER} >/dev/null 2>&1
    docker rm ${TEMP_CONTAINER} >/dev/null 2>&1
}

# Start container
start_container() {
    print_header "Starting OpenAlgo Container"

    if [ -f "docker-compose.yaml" ]; then
        print_info "Starting with docker-compose..."
        docker-compose up -d
        print_success "Container started via docker-compose"
    else
        print_info "Starting with docker run..."
        docker run -d \
            --name ${CONTAINER_NAME} \
            --shm-size=2g \
            -p 5000:5000 \
            -p 8765:8765 \
            -v openalgo_db:/app/db \
            -v openalgo_log:/app/log \
            -v openalgo_strategies:/app/strategies \
            -v openalgo_keys:/app/keys \
            -v "$(pwd)/.env:/app/.env" \
            --tmpfs /app/tmp:size=1g,mode=1777 \
            --restart unless-stopped \
            ${IMAGE_NAME}:${IMAGE_TAG}
        print_success "Container started via docker run"
    fi

    print_info "Waiting for container to be ready..."
    sleep 5
}

# Health check
health_check() {
    print_header "Running Health Checks"

    # Check if container is running
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        print_success "Container is running"
    else
        print_error "Container is not running!"
        print_info "Checking logs..."
        docker-compose logs --tail=50 openalgo || docker logs ${CONTAINER_NAME}
        exit 1
    fi

    # Wait for application to start
    print_info "Waiting for application to start (up to 30 seconds)..."
    for i in {1..30}; do
        if curl -s -f http://127.0.0.1:5000/auth/check-setup >/dev/null 2>&1; then
            print_success "Application is responding"
            break
        fi
        if [ $i -eq 30 ]; then
            print_warning "Application not responding after 30 seconds"
            print_info "This is normal for first-time startup. Check logs with: docker-compose logs -f"
        fi
        sleep 1
    done
}

# Test Python dependencies
test_python_deps() {
    print_header "Testing Python Dependencies (numba/llvmlite)"

    print_info "Testing basic imports..."

    # Test 1: Basic imports
    if docker-compose exec -T openalgo python -c "import numba; import llvmlite; print('SUCCESS')" 2>/dev/null | grep -q "SUCCESS"; then
        print_success "numba, llvmlite imports successful"
    else
        print_error "Failed to import dependencies"
        print_info "Running detailed test..."
        docker-compose exec openalgo python -c "import numba; import llvmlite; print('SUCCESS')"
        return 1
    fi

    # Test 2: Numba JIT compilation
    print_info "Testing numba JIT compilation..."
    if docker-compose exec -T openalgo python -c "
from numba import jit
import numpy as np

@jit(nopython=True)
def test_func(x):
    return x * 2

result = test_func(np.array([1, 2, 3]))
print('SUCCESS' if len(result) == 3 else 'FAILED')
" 2>/dev/null | grep -q "SUCCESS"; then
        print_success "Numba JIT compilation works"
    else
        print_error "Numba JIT compilation failed"
        return 1
    fi

    # Test 3: Cache directory permissions
    print_info "Testing cache directory..."
    if docker-compose exec -T openalgo bash -c "
[ -d /app/tmp/numba_cache ] && [ -w /app/tmp/numba_cache ] && echo 'SUCCESS'
" 2>/dev/null | grep -q "SUCCESS"; then
        print_success "Numba cache directory is writable"
    else
        print_warning "Numba cache directory issue (may not affect functionality)"
    fi
}

# Display access information
show_access_info() {
    print_header "Deployment Complete!"

    echo -e "${GREEN} OpenAlgo is now running${NC}\n"

    echo -e "${BLUE}Access URLs:${NC}"
    echo -e "  Web UI:       ${GREEN}http://127.0.0.1:5000${NC}"
    echo -e "  WebSocket:    ${GREEN}ws://127.0.0.1:8765${NC}"
    echo -e "  API Docs:     ${GREEN}http://127.0.0.1:5000/api/docs${NC}"
    echo -e "  React UI:     ${GREEN}http://127.0.0.1:5000/react${NC}"

    echo -e "\n${BLUE}Useful Commands:${NC}"
    echo -e "  View logs:        ${YELLOW}docker-compose logs -f${NC}"
    echo -e "  Stop container:   ${YELLOW}docker-compose down${NC}"
    echo -e "  Restart:          ${YELLOW}docker-compose restart${NC}"
    echo -e "  Shell access:     ${YELLOW}docker-compose exec openalgo bash${NC}"
    echo -e "  Run strategy:     ${YELLOW}docker-compose exec openalgo uv run python /app/strategies/scripts/your_script.py${NC}"

    echo -e "\n${BLUE}Configured Broker:${NC}"
    if ! env_sets_broker; then
        echo -e "  ${YELLOW}None in .env. Sign in to OpenAlgo and add your broker keys in Broker Configuration,${NC}"
        echo -e "  ${YELLOW}then register the redirect URL shown there in your broker's developer console.${NC}"
    elif grep -q "fyers" .env 2>/dev/null; then
        echo -e "  ${GREEN}Fyers${NC}"
        echo -e "  Callback URL: ${YELLOW}http://127.0.0.1:5000/fyers/callback${NC}"
    elif grep -q "zerodha" .env 2>/dev/null; then
        echo -e "  ${GREEN}Zerodha${NC}"
        echo -e "  Callback URL: ${YELLOW}http://127.0.0.1:5000/zerodha/callback${NC}"
    else
        echo -e "  ${YELLOW}Check your .env file for configured broker${NC}"
    fi

    echo -e "\n${BLUE}Next Steps:${NC}"
    echo -e "  1. Open ${GREEN}http://127.0.0.1:5000${NC} in your browser"
    echo -e "  2. Complete the initial setup wizard"
    echo -e "  3. Configure your broker credentials"
    echo -e "  4. Start trading with Python strategies!"

    echo -e "\n${YELLOW}Note: First-time startup may take 30-60 seconds${NC}"
    echo -e "${YELLOW}Check logs if needed: docker-compose logs -f${NC}\n"
}

# Main execution
main() {
    print_header "OpenAlgo Docker Build & Deploy"
    print_info "Starting build process with numba/llvmlite support..."

    # Step 1: Check environment
    check_env_file

    # Step 2: Cleanup existing containers
    cleanup_existing

    # Step 3: Build image
    build_image

    # Step 4: Verify dependencies in image
    verify_dependencies

    # Step 5: Start container
    start_container

    # Step 6: Health check
    health_check

    # Step 7: Test Python dependencies
    if test_python_deps; then
        print_success "All dependency tests passed!"
    else
        print_warning "Some dependency tests failed - check logs above"
    fi

    # Step 8: Show access information
    show_access_info
}

# Run main function
main "$@"
