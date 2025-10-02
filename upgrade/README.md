# OpenAlgo Upgrade Guide

## Running Migrations

All migration scripts support the `uv run` command (recommended) or standard Python execution:

```bash
# Using uv (recommended)
uv run upgrade/<migration_script>.py

# Using Python directly
python upgrade/<migration_script>.py
```

## Latest Migrations

### Sandbox Mode Migrations (v2.0.0)
**New Feature** - Complete sandbox testing environment with margin tracking

#### How to Apply
```bash
# Navigate to openalgo directory
cd openalgo

# Apply sandbox migration
uv run upgrade/migrate_sandbox.py

# Or using Python directly
python upgrade/migrate_sandbox.py
```

#### What It Does
The `migrate_sandbox.py` script performs a comprehensive migration:
- Creates complete sandbox database (`db/sandbox.db`)
- Sets up all required tables (orders, trades, positions, holdings, funds, config)
- Adds indexes and constraints for optimal performance
- Inserts default configuration values
- Tracks margin accurately across all trading scenarios
- Handles partial position closures correctly
- Manages position reversals properly
- Provides fallback for API failures in sandbox mode

#### Migration Features
- **Idempotent**: Safe to run multiple times
- **Non-destructive**: Won't overwrite existing data
- **Automatic backup**: Creates backup before migration
- **Status checking**: Shows current migration state
- **Comprehensive logging**: Detailed progress information

---

### Telegram Bot Integration (v1.0.0)
**New Feature** - Telegram bot for read-only trading data access

#### How to Apply
```bash
# Navigate to openalgo directory
cd openalgo

# Apply the migration (creates tables)
uv run upgrade/migrate_telegram_bot.py

# Check migration status
uv run upgrade/migrate_telegram_bot.py --status

# Rollback if needed
uv run upgrade/migrate_telegram_bot.py --downgrade
```

#### What It Does
- Creates 5 new tables for Telegram functionality
- Adds user linking between Telegram and OpenAlgo
- Enables read-only access to trading data via Telegram
- Provides analytics and command tracking

#### After Migration
1. Access Telegram Bot from Profile menu (top-right dropdown)
2. Configure bot token from @BotFather
3. Start bot and link your account

---

## Python Strategy Management (v1.1.1)

### Do You Need Any Migration?

**NO** - The Python Strategy Management feature is completely new!

### How to Upgrade

Simply pull the latest code:
```bash
git pull origin main

# If using uv, sync dependencies
uv sync
```

That's it! You're ready to use the new Python Strategy Management feature.

### What's New

**Python Strategy Management System** - A complete solution for running Python trading strategies:
- Upload and manage multiple strategies via web interface at `/python`
- Each strategy runs in a separate process (complete isolation)
- Schedule strategies to run at specific times (IST timezone)
- Built-in code editor with syntax highlighting
- Environment variables support (regular and encrypted secure variables)
- Real-time logging and monitoring
- Master contract dependency checking
- Persistent state across application restarts
- Export/Import strategies for backup

### No Database Changes

This feature uses file-based storage, so:
- No database migrations needed
- No schema changes required
- All configurations stored as JSON files
- Strategies stored as Python files

### Auto-Created Structure

When you first use the feature, these will be created automatically:
- `keys/` - Encryption keys (already in git with .gitignore)
- `strategies/scripts/` - Your strategy Python files
- `strategies/strategy_configs.json` - Strategy configurations
- `strategies/strategy_env.json` - Environment variables
- `strategies/.secure_env` - Encrypted sensitive variables
- `log/strategies/` - Strategy execution logs

---

## Core Database Migrations

### Available Migrations
- **add_feed_token.py** - Adds feed token support for data feeds
- **add_user_id.py** - Adds user ID column to various tables
- **migrate_security_columns.py** - Migrates security-related columns
- **migrate_smtp_simple.py** - SMTP configuration migration

---

## Creating New Migrations

### Naming Convention
- Sandbox migrations: `00X_descriptive_name.py` (numbered sequence)
- Core migrations: `descriptive_name.py`

### Required Functions
```python
def upgrade():
    """Apply the migration"""
    pass

def rollback():
    """Reverse the migration (optional but recommended)"""
    pass

def status():
    """Check if migration is applied"""
    pass
```

### Best Practices
1. Make migrations idempotent (safe to run multiple times)
2. Include rollback functionality where possible
3. Add proper logging
4. Test both upgrade and rollback
5. Document changes clearly
6. Handle missing columns/tables gracefully

### Testing Migrations
```bash
# Test upgrade
python your_migration.py upgrade
python your_migration.py status

# Test rollback
python your_migration.py rollback
python your_migration.py status
```

---

## Troubleshooting

### Common Issues

1. **Module not found errors**: Ensure you're running from the OpenAlgo directory with virtual environment:
   ```bash
   cd /path/to/openalgo
   source .venv/bin/activate  # or use uv run
   python upgrade/migration_name.py
   ```

2. **Database locked errors**: Ensure no other processes are using the database

3. **Index already exists**: Migrations handle this with `CREATE INDEX IF NOT EXISTS`

4. **Rollback issues**: Some SQLite operations require table recreation

---

*For full documentation, see [OpenAlgo Documentation](../docs/)*