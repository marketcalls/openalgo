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

*For the full documentation, see [Python Strategies Documentation](../docs/python_strategies/)*