#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# OpenAlgo Update Script
echo -e "${BLUE}"
echo "  ██████╗ ██████╗ ███████╗███╗   ██╗ █████╗ ██╗      ██████╗  ██████╗ "
echo " ██╔═══██╗██╔══██╗██╔════╝████╗  ██║██╔══██╗██║     ██╔════╝ ██╔═══██╗"
echo " ██║   ██║██████╔╝███████╗██╔██╗ ██║███████║██║     ██║  ███╗██║   ██║"
echo " ██║   ██║██╔═══╝ ██╔══╝  ██║╚██╗██║██╔══██║██║     ██║   ██║██║   ██║"
echo " ╚██████╔╝██╗     ███████╗██║ ╚████║██║  ██║███████╗╚██████╔╝╚██████╔╝"
echo "  ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═══╝╚═╝  ╚═╝╚══════╝ ╚═════╝  ╚═════╝ "
echo "                                                                        "
echo "                         Update Script                                 "
echo -e "${NC}"

# Function to log messages to both console
log_message() {
    local message="$1"
    local color="$2"
    echo -e "${color}${message}${NC}"
}

# Function to check if command was successful
check_status() {
    if [ $? -ne 0 ]; then
        log_message "Error: $1" "$RED"
        exit 1
    fi
}

# Detect OS type
OS_TYPE=$(grep -w "ID" /etc/os-release | cut -d "=" -f 2 | tr -d '"')

# Handle OS variants - map to base distributions
case "$OS_TYPE" in
    "pop"|"linuxmint"|"zorin")
        OS_TYPE="ubuntu"
        ;;
    "manjaro"|"manjaro-arm"|"endeavouros"|"cachyos")
        OS_TYPE="arch"
        ;;
    "rocky"|"almalinux"|"ol")
        OS_TYPE="rhel"
        ;;
esac

# Detect web server user based on OS
case "$OS_TYPE" in
    ubuntu | debian | raspbian)
        WEB_USER="www-data"
        WEB_GROUP="www-data"
        ;;
    centos | fedora | rhel | amzn)
        WEB_USER="nginx"
        WEB_GROUP="nginx"
        ;;
    arch)
        WEB_USER="http"
        WEB_GROUP="http"
        ;;
esac

# Function to find all OpenAlgo installations
find_installations() {
    local installations=()
    
    # Find all openalgo-flask directories
    if [ -d "/var/python/openalgo-flask" ]; then
        for deploy_dir in /var/python/openalgo-flask/*; do
            if [ -d "$deploy_dir" ] && [ -d "$deploy_dir/openalgo" ] && [ -d "$deploy_dir/openalgo/.git" ]; then
                installations+=("$deploy_dir")
            fi
        done
    fi
    
    echo "${installations[@]}"
}

# Function to update a single installation
update_installation() {
    local base_path="$1"
    local openalgo_path="$base_path/openalgo"
    local venv_path="$base_path/venv"
    local deploy_name=$(basename "$base_path")
    
    log_message "\n===========================================" "$BLUE"
    log_message "Updating installation: $deploy_name" "$BLUE"
    log_message "Path: $openalgo_path" "$BLUE"
    log_message "===========================================" "$BLUE"
    
    # Check if installation exists
    if [ ! -d "$openalgo_path" ]; then
        log_message "Error: OpenAlgo directory not found at $openalgo_path" "$RED"
        return 1
    fi
    
    # Check if it's a git repository
    if [ ! -d "$openalgo_path/.git" ]; then
        log_message "Error: Not a git repository at $openalgo_path" "$RED"
        return 1
    fi
    
    # Get current branch and commit (before any operations)
    cd "$openalgo_path"
    CURRENT_BRANCH=$(sudo -u $WEB_USER git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
    LOCAL_COMMIT=$(sudo -u $WEB_USER git rev-parse HEAD 2>/dev/null)
    
    log_message "Current branch: $CURRENT_BRANCH" "$BLUE"
    log_message "Current commit: ${LOCAL_COMMIT:0:8}..." "$BLUE"
    
    # Fetch latest changes
    log_message "\nFetching latest changes from remote..." "$BLUE"
    sudo -u $WEB_USER git fetch origin 2>&1
    check_status "Failed to fetch from remote"
    
    # Check if there are updates available
    REMOTE_COMMIT=$(sudo -u $WEB_USER git rev-parse origin/${CURRENT_BRANCH:-main})
    
    if [ "$LOCAL_COMMIT" = "$REMOTE_COMMIT" ]; then
        log_message "Already up to date!" "$GREEN"
        return 0
    fi
    
    # Show what will be updated
    log_message "\nChanges to be pulled:" "$YELLOW"
    sudo -u $WEB_USER git log --oneline HEAD..origin/${CURRENT_BRANCH:-main} 2>/dev/null | head -10
    log_message "..." "$YELLOW"
    
    # Backup current state
    BACKUP_DIR="$base_path/backup_$(date +%Y%m%d_%H%M%S)"
    log_message "\nCreating backup at $BACKUP_DIR..." "$BLUE"
    sudo mkdir -p "$BACKUP_DIR"
    sudo cp -r "$openalgo_path" "$BACKUP_DIR/openalgo" 2>/dev/null || log_message "Warning: Could not create full backup" "$YELLOW"
    
    # Check for uncommitted changes
    if [ -n "$(sudo -u $WEB_USER git status --porcelain 2>/dev/null)" ]; then
        log_message "Warning: Uncommitted changes detected!" "$YELLOW"
        log_message "Stashing changes..." "$YELLOW"
        sudo -u $WEB_USER git stash push -m "Auto-stash before update $(date +%Y%m%d_%H%M%S)" 2>/dev/null || {
            log_message "Error: Could not stash changes. Please commit or discard changes manually." "$RED"
            return 1
        }
        STASHED=true
    else
        STASHED=false
    fi
    
    # Pull latest changes
    log_message "\nPulling latest changes..." "$BLUE"
    sudo -u $WEB_USER git pull origin ${CURRENT_BRANCH:-main} 2>&1
    if [ $? -ne 0 ]; then
        log_message "Error: Failed to pull changes. Attempting to restore backup..." "$RED"
        if [ -d "$BACKUP_DIR/openalgo" ]; then
            log_message "Restoring from backup..." "$YELLOW"
            sudo rm -rf "$openalgo_path"
            sudo cp -r "$BACKUP_DIR/openalgo" "$openalgo_path"
            sudo chown -R $WEB_USER:$WEB_GROUP "$openalgo_path"
        fi
        return 1
    fi
    
    # Restore stashed changes if any
    if [ "$STASHED" = true ]; then
        log_message "\nRestoring stashed changes..." "$YELLOW"
        sudo -u $WEB_USER git stash pop 2>/dev/null || log_message "Warning: Could not restore stashed changes. Check with 'git stash list'" "$YELLOW"
    fi
    
    # Get new commit
    NEW_COMMIT=$(sudo -u $WEB_USER git rev-parse HEAD)
    log_message "Updated to commit: ${NEW_COMMIT:0:8}..." "$GREEN"
    
    # Check if requirements.txt changed and update dependencies
    if [ -f "$venv_path/bin/activate" ]; then
        log_message "\nChecking for dependency updates..." "$BLUE"
        
        # Compare requirements file timestamps
        REQUIREMENTS_FILE="$openalgo_path/requirements-nginx.txt"
        if [ -f "$REQUIREMENTS_FILE" ]; then
            # Check if requirements file was modified
            if sudo -u $WEB_USER git diff --name-only "$LOCAL_COMMIT" "$NEW_COMMIT" | grep -q "requirements"; then
                log_message "Requirements file changed. Updating dependencies..." "$YELLOW"
                
                # Detect uv command
                if command -v uv >/dev/null 2>&1; then
                    UV_CMD="uv"
                elif python3 -m uv --version >/dev/null 2>&1; then
                    UV_CMD="python3 -m uv"
                else
                    log_message "Warning: uv not found. Skipping dependency update." "$YELLOW"
                    UV_CMD=""
                fi
                
                if [ -n "$UV_CMD" ]; then
                    sudo $UV_CMD pip install --python $venv_path/bin/python -r "$REQUIREMENTS_FILE" 2>&1 | head -20
                    log_message "Dependencies updated" "$GREEN"
                fi
            else
                log_message "No dependency changes detected" "$GREEN"
            fi
        fi
    fi
    
    # Restart service if it exists
    local service_name="openalgo-$(basename "$base_path")"
    if systemctl list-units --type=service | grep -q "^${service_name}.service"; then
        log_message "\nRestarting service: $service_name..." "$BLUE"
        sudo systemctl restart "$service_name" 2>&1
        if [ $? -eq 0 ]; then
            log_message "Service restarted successfully" "$GREEN"
            # Wait a moment for service to start
            sleep 2
            # Check service status
            if systemctl is-active --quiet "$service_name"; then
                log_message "Service is running" "$GREEN"
            else
                log_message "Warning: Service may have failed to start. Check status with: sudo systemctl status $service_name" "$YELLOW"
            fi
        else
            log_message "Warning: Failed to restart service. Please restart manually: sudo systemctl restart $service_name" "$YELLOW"
        fi
    fi
    
    log_message "\nUpdate completed successfully for $deploy_name!" "$GREEN"
    return 0
}

# Main execution
INSTALLATIONS=($(find_installations))

if [ ${#INSTALLATIONS[@]} -eq 0 ]; then
    log_message "No OpenAlgo installations found." "$RED"
    log_message "Expected location: /var/python/openalgo-flask/*/openalgo" "$YELLOW"
    exit 1
fi

# If specific path provided as argument
if [ $# -gt 0 ]; then
    SPECIFIC_PATH="$1"
    if [ -d "$SPECIFIC_PATH/openalgo" ] && [ -d "$SPECIFIC_PATH/openalgo/.git" ]; then
        update_installation "$SPECIFIC_PATH"
        exit $?
    else
        log_message "Error: Invalid OpenAlgo installation path: $SPECIFIC_PATH" "$RED"
        exit 1
    fi
fi

# If multiple installations, ask which to update
if [ ${#INSTALLATIONS[@]} -eq 1 ]; then
    # Single installation, update it
    update_installation "${INSTALLATIONS[0]}"
else
    # Multiple installations
    log_message "\nFound ${#INSTALLATIONS[@]} OpenAlgo installation(s):" "$BLUE"
    for i in "${!INSTALLATIONS[@]}"; do
        deploy_name=$(basename "${INSTALLATIONS[$i]}")
        log_message "  [$((i+1))] $deploy_name (${INSTALLATIONS[$i]})" "$BLUE"
    done
    
    read -p "Enter number to update (or 'all' for all, 'q' to quit): " choice
    
    if [ "$choice" = "q" ] || [ "$choice" = "Q" ]; then
        log_message "Update cancelled." "$YELLOW"
        exit 0
    elif [ "$choice" = "all" ] || [ "$choice" = "ALL" ]; then
        log_message "\nUpdating all installations..." "$BLUE"
        FAILED=0
        for inst in "${INSTALLATIONS[@]}"; do
            update_installation "$inst" || FAILED=$((FAILED + 1))
        done
        if [ $FAILED -eq 0 ]; then
            log_message "\nAll installations updated successfully!" "$GREEN"
            exit 0
        else
            log_message "\nWarning: $FAILED installation(s) failed to update" "$YELLOW"
            exit 1
        fi
    elif [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le ${#INSTALLATIONS[@]} ]; then
        update_installation "${INSTALLATIONS[$((choice-1))]}"
        exit $?
    else
        log_message "Invalid choice." "$RED"
        exit 1
    fi
fi


