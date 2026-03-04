#!/bin/bash
# ============================================================================
# OpenAlgo Volume Migration Tool (macOS/Linux)
# Migrates data from legacy docker named volumes to local bind mounts
# ============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}  ========================================${NC}"
echo -e "${BLUE}       OpenAlgo Volume Migrator${NC}"
echo -e "${BLUE}  ========================================${NC}"
echo ""

echo -e "${YELLOW}[INFO]${NC} Creating local directories..."
mkdir -p db log strategies keys tmp

migrate_volume() {
    local vol_name=$1
    local dest_dir=$2
    
    if docker volume ls | grep -q "$vol_name"; then
        echo -e "${BLUE}[INFO]${NC} Migrating $vol_name -> ./$dest_dir..."
        docker run --rm -v "$vol_name":/from -v "$(pwd)/$dest_dir":/to alpine sh -c "cp -a /from/. /to/ 2>/dev/null || true"
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}[OK]${NC} Successfully migrated $vol_name."
        else
            echo -e "${RED}[ERROR]${NC} Failed to migrate $vol_name."
        fi
    else
        echo -e "${YELLOW}[SKIP]${NC} Volume $vol_name not found, skipping."
    fi
}

migrate_volume "openalgo_db" "db"
migrate_volume "openalgo_log" "log"
migrate_volume "openalgo_strategies" "strategies"
migrate_volume "openalgo_keys" "keys"

echo ""
echo -e "${GREEN}[SUCCESS]${NC} Migration complete! Your data is now in the local project directory."
echo "You can safely use the new docker-compose.yaml with bind mounts."
echo ""
