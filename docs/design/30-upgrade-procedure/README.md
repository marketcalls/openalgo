# 30 - Upgrade Procedure

## Overview

Guidelines for upgrading OpenAlgo to new versions while preserving data and configurations.

## Pre-Upgrade Checklist

```
┌────────────────────────────────────────────────────────────────────────────┐
│                        Pre-Upgrade Checklist                                │
│                                                                             │
│  □ 1. Backup databases (db/*.db)                                           │
│  □ 2. Backup .env file                                                     │
│  □ 3. Backup custom strategies                                             │
│  □ 4. Note current version                                                 │
│  □ 5. Stop running OpenAlgo instance                                       │
│  □ 6. Read release notes for breaking changes                              │
│                                                                             │
└────────────────────────────────────────────────────────────────────────────┘
```

## Backup Procedure

### Database Backup

```bash
# Create backup directory
mkdir -p backups/$(date +%Y%m%d)

# Backup all databases
cp db/openalgo.db backups/$(date +%Y%m%d)/
cp db/logs.db backups/$(date +%Y%m%d)/
cp db/latency.db backups/$(date +%Y%m%d)/
cp db/sandbox.db backups/$(date +%Y%m%d)/
cp db/historify.duckdb backups/$(date +%Y%m%d)/
```

### Configuration Backup

```bash
# Backup environment file
cp .env backups/$(date +%Y%m%d)/

# Backup strategies (if any)
cp -r strategies/ backups/$(date +%Y%m%d)/
```

## Upgrade Steps

### Step 1: Stop OpenAlgo

```bash
# Stop running instance
# Press Ctrl+C if running in terminal

# Or if running as service
sudo systemctl stop openalgo
```

### Step 2: Pull Latest Changes

```bash
# Update from repository
git fetch origin
git pull origin main
```

### Step 3: Update Dependencies

```bash
# Sync Python dependencies
uv sync

# Update frontend dependencies
cd frontend
npm install
npm run build
cd ..
```

### Step 4: Update Environment

```bash
# Compare with sample.env
diff .env .sample.env

# Add any new variables from .sample.env to .env
```

### Step 5: Database Initialization

OpenAlgo uses automatic database initialization on startup. New tables are created automatically when the application starts - no manual migrations are required.

```bash
# Start the app to initialize any new database tables
# Tables are created if they don't exist (safe - won't overwrite existing data)
uv run app.py
```

> **Note**: There is no `migrations/` directory. Database schema updates are handled automatically by SQLAlchemy's `create_all()` during app startup.

### Step 6: Start OpenAlgo

```bash
# Start application
uv run app.py
```

## Version-Specific Upgrades

### Upgrading to v2.0.0

**CRITICAL**: v2.0.0 requires building the React frontend. The `frontend/dist/` directory is gitignored and must be built locally.

Major changes:
- React 19 frontend replaces Jinja2 templates for most UIs
- New database tables (flow_workflows, action_center, etc.)
- 40+ new environment variables (CORS, CSP, ZeroMQ, etc.)
- Flow Visual Builder with 53 node types
- Historify (DuckDB-based historical data)

```bash
# REQUIRED: Build React frontend
cd frontend
npm install
npm run build
cd ..

# Compare environment variables with new sample
diff .env .sample.env

# Add missing variables from .sample.env (especially CORS, ZeroMQ settings)
# See docs/design/28-environment-config/ for full variable list
```

> **Important**: Check `docs/CHANGELOG.md` for detailed v2.0.0 release notes.

### Database Schema Changes

```python
# Check if tables need updates
from database import init_all_databases

# Initialize new tables (safe - won't overwrite existing)
init_all_databases()
```

## Rollback Procedure

### If Upgrade Fails

```bash
# Stop current version
# Press Ctrl+C

# Restore previous version
git checkout v1.x.x  # Previous version tag

# Restore databases
cp backups/YYYYMMDD/openalgo.db db/
cp backups/YYYYMMDD/.env ./

# Restart
uv run app.py
```

## Docker Upgrade

### Pull New Image

```bash
# Stop container
docker-compose down

# Pull latest image
docker-compose pull

# Start with new image
docker-compose up -d
```

### Volume Preservation

```yaml
# docker-compose.yml
volumes:
  - ./db:/app/db          # Database persisted
  - ./.env:/app/.env      # Config persisted
```

## Systemd Service Update

### For Ubuntu Server

```bash
# Stop service
sudo systemctl stop openalgo

# Update code
git pull origin main
uv sync

# Restart service
sudo systemctl start openalgo

# Check status
sudo systemctl status openalgo
```

## Post-Upgrade Verification

### Health Checks

```bash
# Check application logs
tail -f log/openalgo.log

# Verify web access
curl http://127.0.0.1:5000/health

# Check database connectivity
uv run python -c "from database import init_all_databases; print('OK')"
```

### Functional Tests

1. Log in to web interface
2. Check broker connection
3. Place test order (analyzer mode)
4. Verify WebSocket connection
5. Check API endpoint

## Changelog Review

### Check Release Notes

```bash
# View release tags
git tag -l

# View changelog
cat CHANGELOG.md

# View specific release
git show v2.0.0
```

## Troubleshooting

### Common Upgrade Issues

| Issue | Solution |
|-------|----------|
| Missing dependency | Run `uv sync` |
| Database error | Check schema migration |
| Frontend not loading | Run `npm run build` |
| .env missing vars | Compare with .sample.env |
| Permission errors | Check file ownership |

### Reset to Clean State

```bash
# CAUTION: This removes all data

# Remove databases
rm -rf db/*.db

# Reinitialize
uv run python -c "from database import init_all_databases; init_all_databases()"
```

## Automated Upgrade Script

### upgrade.sh

```bash
#!/bin/bash
set -e

echo "Starting OpenAlgo upgrade..."

# Backup
BACKUP_DIR="backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p $BACKUP_DIR
cp db/*.db $BACKUP_DIR/
cp .env $BACKUP_DIR/

# Update code
git pull origin main

# Update dependencies
uv sync

# Build frontend
cd frontend
npm install
npm run build
cd ..

echo "Upgrade complete!"
echo "Backup stored in: $BACKUP_DIR"
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `.sample.env` | Reference for new variables |
| `CHANGELOG.md` | Version changes |
| `pyproject.toml` | Python dependencies |
| `frontend/package.json` | Frontend dependencies |
