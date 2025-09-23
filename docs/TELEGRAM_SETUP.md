# Telegram Bot Integration Setup Guide

## Overview
This guide will help you set up the Telegram bot integration for OpenAlgo, enabling read-only access to trading data through Telegram.

## Prerequisites
1. Python 3.8 or higher
2. OpenAlgo application running
3. Telegram account

## Installation Steps

### 1. Install Dependencies
```bash
# Using uv (recommended)
uv pip install python-telegram-bot==21.3

# Or using pip
pip install python-telegram-bot==21.3
```

### 2. Run Database Migration
The migration script will create all necessary tables for the Telegram integration.

```bash
# Navigate to the openalgo directory
cd openalgo

# Run the migration using uv
uv run upgrade/migrate_telegram_bot.py

# Or using python directly
python upgrade/migrate_telegram_bot.py
```

You should see output confirming the creation of tables:
- `telegram_users` - Stores linked Telegram users
- `bot_config` - Bot configuration settings
- `command_logs` - Command usage analytics
- `notification_queue` - Message queue
- `user_preferences` - User notification preferences

### 3. Create Your Telegram Bot
1. Open Telegram and search for **@BotFather**
2. Send the command `/newbot`
3. Choose a name for your bot (e.g., "OpenAlgo Trading Bot")
4. Choose a username (must end with 'bot', e.g., "openalgo_trading_bot")
5. Copy the bot token provided by BotFather

### 4. Configure the Bot in OpenAlgo
1. Start your OpenAlgo application
2. Log in to the web interface
3. Click on your profile icon (top right)
4. Select **"Telegram Bot"** from the dropdown menu
5. Click on **"Configuration"**
6. Paste your bot token
7. Select **Polling** mode (recommended for local setups)
8. Save the configuration

### 5. Start the Bot
1. Return to the Telegram dashboard
2. Click the **"Start Bot"** button
3. The status should change to "Running"

### 6. Link Your Account
1. Open Telegram and search for your bot username
2. Send `/start` to the bot
3. Send `/link <your_api_key> <host_url> [username]` to link your account
   - Example: `/link your_api_key_here http://127.0.0.1:5000 admin`
   - The API key should be your OpenAlgo API key (found in Profile → API Key)
   - The host URL should be where your OpenAlgo is running
   - Username is optional (defaults to your Telegram username)

## Available Commands

Once linked, users can use these commands:

- `/start` - Welcome message and help
- `/link <api_key> <host_url> [username]` - Link OpenAlgo account with API key
- `/menu` - Interactive menu with buttons
- `/orderbook` - View open orders
- `/tradebook` - View executed trades
- `/positions` - View open positions
- `/holdings` - View portfolio holdings
- `/funds` - View account funds
- `/pnl` - View profit & loss (realized and unrealized)
- `/quote <symbol>` - Get stock quote (e.g., `/quote RELIANCE`)
- `/help` - Show help message
- `/unlink` - Unlink your account

## Features

### Web UI Control Panel
Access the control panel from the Profile dropdown menu → Telegram Bot

- **Dashboard**: Monitor bot status, user count, and command statistics
- **Configuration**: Manage bot token and settings
- **Users**: View and manage linked users
- **Analytics**: Detailed usage statistics and charts
- **Broadcast**: Send messages to all users

### Security Features
- Read-only access (no trading operations)
- API key validation required for linking accounts
- All API keys are encrypted using Fernet encryption
- User authentication through OpenAlgo API
- SQLAlchemy for secure database operations
- Rate limiting to prevent abuse
- Host URL validation to prevent unauthorized access

## Troubleshooting

### Bot Not Starting
1. Verify the bot token is correct
2. Check if the token has been revoked (regenerate from @BotFather)
3. Ensure database migration completed successfully

### Cannot Link Account
1. Verify your OpenAlgo API key is correct (found in Profile → API Key)
2. Ensure the host URL is correct (e.g., http://127.0.0.1:5000)
3. Test your API key by accessing the OpenAlgo API directly
4. Check if the account is already linked

### Commands Not Working
1. Ensure you've linked your account first
2. Check if the bot is running (check status in web UI)
3. Try restarting the bot from the control panel

## Database Management

### View Migration Status
```bash
uv run upgrade/migrate_telegram_bot.py --status
```

### Apply Migration
```bash
uv run upgrade/migrate_telegram_bot.py
```

### Rollback Migration (Remove Tables)
```bash
uv run upgrade/migrate_telegram_bot.py --downgrade
```

## Advanced Configuration

### Webhook Mode (For Production)
1. Requires HTTPS domain
2. Set webhook URL in configuration
3. Configure reverse proxy (nginx/Apache)
4. Restart bot after configuration

### Rate Limiting
- Default: 30 commands per minute per user
- Adjustable in bot configuration
- Prevents abuse and ensures fair usage

## Support

For issues or questions:
1. Check the Logs section in OpenAlgo
2. Review command statistics in Analytics
3. Contact your system administrator

## Notes

- The bot operates in read-only mode for security
- All data is fetched in real-time from your broker
- Bot messages are formatted for mobile viewing
- Supports multiple users with individual account linking
- Command usage is logged for analytics