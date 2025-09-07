# OpenAlgo v1.1.1 Upgrade Notice

## For Existing Users

### Do You Need Any Migration?

**NO** - The Python Strategy Management feature is completely new!

### How to Upgrade

Simply pull the latest code:
```bash
git pull origin main
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