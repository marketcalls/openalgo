import os
import asyncio
import logging
import sys
import concurrent.futures
from typing import Dict, List, Optional, Tuple, Any

# Import the original threading module to run the bot in a real OS thread,
# bypassing eventlet's monkey-patching which causes event loop conflicts.
if 'eventlet' in sys.modules:
    import eventlet
    original_threading = eventlet.patcher.original('threading')
else:
    import threading as original_threading

from datetime import datetime, timedelta
import httpx
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode
import telegram.error
import json
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import io
import base64
from openalgo import api as openalgo_api

# Database imports
from database.telegram_db import (
    get_telegram_user,
    create_or_update_telegram_user,
    get_bot_config,
    update_bot_config,
    log_command,
    get_command_stats,
    get_all_telegram_users,
    delete_telegram_user,
    get_user_credentials
)
from database.auth_db import get_username_by_apikey
from utils.logging import get_logger

logger = get_logger(__name__)

class TelegramBotService:
    """Service class for managing Telegram bot operations with OpenAlgo SDK integration"""

    def __init__(self):
        self.application = None
        self.bot = None
        self.is_running = False
        self.bot_token = None
        self.http_client = None  # Will be created in thread
        self.bot_thread = None
        self.bot_loop = None  # Store the bot's event loop
        self.sdk_clients = {}  # Cache for OpenAlgo SDK clients per user
        self._stop_event = original_threading.Event()  # Thread-safe stop signal

    def _get_sdk_client(self, telegram_id: int) -> Optional[openalgo_api]:
        """Get or create OpenAlgo SDK client for a user"""
        try:
            # Check if client already exists
            if telegram_id in self.sdk_clients:
                return self.sdk_clients[telegram_id]

            # Get user credentials
            credentials = get_user_credentials(telegram_id)
            if not credentials or not credentials.get('api_key'):
                logger.error(f"No valid credentials for telegram_id: {telegram_id}")
                return None

            host_url = credentials['host_url'].rstrip('/')
            api_key = credentials['api_key']

            # Create SDK client
            client = openalgo_api(api_key=api_key, host=host_url)

            # Cache the client
            self.sdk_clients[telegram_id] = client

            return client

        except Exception as e:
            logger.error(f"Error creating SDK client: {e}")
            return None

    async def _make_sdk_call(self, telegram_id: int, method: str, **kwargs) -> Optional[Dict]:
        """Make an SDK call in async context"""
        try:
            client = self._get_sdk_client(telegram_id)
            if not client:
                return None

            # Run the SDK method in a thread pool since it's synchronous
            loop = asyncio.get_event_loop()
            sdk_method = getattr(client, method)
            result = await loop.run_in_executor(None, sdk_method, *kwargs.values())

            return result

        except Exception as e:
            logger.error(f"Error making SDK call: {e}")
            return None

    async def _generate_intraday_chart(self, symbol: str, exchange: str, interval: str, days: int, telegram_id: int) -> Optional[bytes]:
        """Generate intraday chart with specified interval"""
        try:
            client = self._get_sdk_client(telegram_id)
            if not client:
                logger.error("No SDK client available")
                return None

            # Calculate dates
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)

            logger.debug(f"Generating intraday chart for {symbol} on {exchange} with interval {interval}")

            # Get historical data - be robust about event loops
            history_data = None

            # Try async first if we have a loop
            if hasattr(self, 'bot_loop') and self.bot_loop:
                try:
                    logger.debug("Using bot's event loop for intraday history")
                    history_data = await self.bot_loop.run_in_executor(
                        None,
                        lambda: client.history(
                            symbol=symbol,
                            exchange=exchange,
                            interval=interval,
                            start_date=start_date.strftime("%Y-%m-%d"),
                            end_date=end_date.strftime("%Y-%m-%d")
                        )
                    )
                except Exception as e:
                    logger.warning(f"Failed to fetch via bot loop: {e}")

            # If that didn't work, try direct sync call
            if history_data is None:
                try:
                    logger.debug("Using synchronous history fetch for intraday")
                    history_data = client.history(
                        symbol=symbol,
                        exchange=exchange,
                        interval=interval,
                        start_date=start_date.strftime("%Y-%m-%d"),
                        end_date=end_date.strftime("%Y-%m-%d")
                    )
                except Exception as e:
                    logger.error(f"Synchronous history fetch failed: {e}")
                    return None

            # Check if we got data
            if history_data is None or (isinstance(history_data, pd.DataFrame) and history_data.empty):
                logger.error("No data available for chart generation")
                return None

            # The API returns a DataFrame directly with timestamp as index
            df = history_data if isinstance(history_data, pd.DataFrame) else pd.DataFrame(history_data)

            # Reset index to get timestamp as a column
            df = df.reset_index()
            # After reset_index(), the index becomes a column named 'index'
            # Rename it to 'timestamp' for clarity
            if 'index' in df.columns:
                df.rename(columns={'index': 'timestamp'}, inplace=True)

            # Create candlestick chart with volume
            fig = make_subplots(
                rows=2, cols=1,
                shared_xaxes=True,
                vertical_spacing=0.03,
                subplot_titles=(f'{symbol} - {days} Day Intraday ({interval})', None),
                row_heights=[0.7, 0.3]
            )

            # Add candlestick chart (following sample code exactly)
            fig.add_trace(
                go.Candlestick(
                    x=df['timestamp'],  # x-axis as timestamp
                    open=df['open'],
                    high=df['high'],
                    low=df['low'],
                    close=df['close'],
                    name='Price',
                    increasing_line_color='green',
                    decreasing_line_color='red'
                ),
                row=1, col=1
            )

            # Add volume bar chart
            colors = ['red' if close < open else 'green'
                     for close, open in zip(df['close'], df['open'])]

            fig.add_trace(
                go.Bar(
                    x=df['timestamp'],  # x-axis as timestamp
                    y=df['volume'],
                    marker_color=colors,
                    name='Volume',
                    showlegend=False
                ),
                row=2, col=1
            )

            # Update layout - simplified like the sample code
            fig.update_layout(
                xaxis_rangeslider_visible=False,
                height=600,
                template='plotly_white',
                showlegend=False,
                hovermode='x unified'
            )

            # Apply category type to both x-axes to avoid gaps
            # Reduce tick density - show only every Nth tick
            tick_spacing = max(1, len(df) // 8)  # Show approximately 8 ticks
            # Format timestamps as "22 SEP 09:15"
            tick_labels = []
            for i in range(0, len(df), tick_spacing):
                if pd.notna(df['timestamp'].iloc[i]):
                    ts = pd.to_datetime(df['timestamp'].iloc[i])
                    tick_labels.append(ts.strftime('%d %b %H:%M').upper())
                else:
                    tick_labels.append('')

            fig.update_xaxes(
                type='category',
                row=2, col=1,  # Apply to bottom subplot
                tickmode='array',
                tickvals=list(range(0, len(df), tick_spacing)),
                ticktext=tick_labels,
                tickangle=45
            )
            # Hide ticks on top subplot
            fig.update_xaxes(
                type='category',
                row=1, col=1,  # Apply to top subplot
                showticklabels=False
            )

            # Clean up axes
            fig.update_yaxes(title_text="")

            # Convert to image bytes
            img_bytes = fig.to_image(format="png", engine="kaleido")
            return img_bytes

        except Exception as e:
            logger.error(f"Error generating intraday chart: {e}")
            return None

    async def _generate_daily_chart(self, symbol: str, exchange: str, interval: str, days: int, telegram_id: int) -> Optional[bytes]:
        """Generate daily chart with specified days"""
        try:
            client = self._get_sdk_client(telegram_id)
            if not client:
                logger.error("No SDK client available")
                return None

            # Calculate dates
            end_date = datetime.now()
            # For daily charts, add extra days to ensure we get enough trading days
            start_date = end_date - timedelta(days=int(days * 1.5))

            logger.debug(f"Generating daily chart for {symbol} on {exchange} with interval {interval}")

            # Get historical data - be robust about event loops
            history_data = None

            # Try async first if we have a loop
            if hasattr(self, 'bot_loop') and self.bot_loop:
                try:
                    logger.debug("Using bot's event loop for daily history")
                    history_data = await self.bot_loop.run_in_executor(
                        None,
                        lambda: client.history(
                            symbol=symbol,
                            exchange=exchange,
                            interval=interval,
                            start_date=start_date.strftime("%Y-%m-%d"),
                            end_date=end_date.strftime("%Y-%m-%d")
                        )
                    )
                except Exception as e:
                    logger.warning(f"Failed to fetch daily via bot loop: {e}")

            # If that didn't work, try direct sync call
            if history_data is None:
                try:
                    logger.debug("Using synchronous history fetch for daily")
                    history_data = client.history(
                        symbol=symbol,
                        exchange=exchange,
                        interval=interval,
                        start_date=start_date.strftime("%Y-%m-%d"),
                        end_date=end_date.strftime("%Y-%m-%d")
                    )
                except Exception as e:
                    logger.error(f"Synchronous daily history fetch failed: {e}")
                    return None

            # Check if we got data
            if history_data is None or (isinstance(history_data, pd.DataFrame) and history_data.empty):
                logger.error("No data available for chart generation")
                return None

            # The API returns a DataFrame directly with timestamp as index
            df = history_data if isinstance(history_data, pd.DataFrame) else pd.DataFrame(history_data)

            # Reset index to get timestamp as a column
            df = df.reset_index()
            # After reset_index(), the index becomes a column named 'index'
            # Rename it to 'timestamp' for clarity
            if 'index' in df.columns:
                df.rename(columns={'index': 'timestamp'}, inplace=True)

            # Keep last N trading days
            df = df.tail(days)

            # Create candlestick chart with volume
            fig = make_subplots(
                rows=2, cols=1,
                shared_xaxes=True,
                vertical_spacing=0.03,
                subplot_titles=(f'{symbol} - Daily Chart ({days} Days)', None),
                row_heights=[0.7, 0.3]
            )

            # Add candlestick chart (following sample code exactly)
            fig.add_trace(
                go.Candlestick(
                    x=df['timestamp'],  # x-axis as timestamp
                    open=df['open'],
                    high=df['high'],
                    low=df['low'],
                    close=df['close'],
                    name='Price',
                    increasing_line_color='green',
                    decreasing_line_color='red'
                ),
                row=1, col=1
            )


            # Add volume bar chart
            colors = ['red' if close < open else 'green'
                     for close, open in zip(df['close'], df['open'])]

            fig.add_trace(
                go.Bar(
                    x=df['timestamp'],  # x-axis as timestamp
                    y=df['volume'],
                    marker_color=colors,
                    name='Volume',
                    showlegend=False
                ),
                row=2, col=1
            )

            # Update layout - simplified like the sample code
            fig.update_layout(
                xaxis_rangeslider_visible=False,
                height=600,
                template='plotly_white',
                showlegend=False,
                hovermode='x unified'
            )

            # Apply category type to both x-axes to avoid gaps
            # Reduce tick density for daily charts - show only every Nth tick
            tick_spacing = max(1, len(df) // 10)  # Show approximately 10 ticks for daily
            # Format dates for display as "22 SEP"
            tick_labels = []
            for i in range(0, len(df), tick_spacing):
                if pd.notna(df['timestamp'].iloc[i]):
                    ts = pd.to_datetime(df['timestamp'].iloc[i])
                    tick_labels.append(ts.strftime('%d %b').upper())
                else:
                    tick_labels.append('')

            fig.update_xaxes(
                type='category',
                row=2, col=1,  # Apply to bottom subplot
                tickmode='array',
                tickvals=list(range(0, len(df), tick_spacing)),
                ticktext=tick_labels,
                tickangle=45
            )
            # Hide ticks on top subplot
            fig.update_xaxes(
                type='category',
                row=1, col=1,  # Apply to top subplot
                showticklabels=False
            )

            # Clean up axes
            fig.update_yaxes(title_text="")

            # Convert to image bytes
            img_bytes = fig.to_image(format="png", engine="kaleido")
            return img_bytes

        except Exception as e:
            logger.error(f"Error generating daily chart: {e}")
            return None

    async def initialize_bot(self, token: str) -> Tuple[bool, str]:
        """Initialize the Telegram bot with given token"""
        try:
            # If bot is running, stop it first
            if self.is_running:
                await self.stop_bot()
                # Wait a moment for cleanup
                await asyncio.sleep(1)

            self.bot_token = token

            # Create a temporary bot just to verify the token
            temp_app = Application.builder().token(token).build()
            await temp_app.initialize()

            # Test the token by getting bot info
            bot_info = await temp_app.bot.get_me()

            await temp_app.shutdown()

            # Update bot config in database
            update_bot_config({
                'bot_token': token,
                'is_active': False,
                'bot_username': bot_info.username
            })

            return True, f"Bot initialized successfully: @{bot_info.username}"

        except Exception as e:
            logger.error(f"Failed to initialize bot: {e}")
            return False, str(e)

    def initialize_bot_sync(self, token: str) -> Tuple[bool, str]:
        """Synchronous initialization for eventlet environments"""
        import sys

        # Check if we're in eventlet environment
        if 'eventlet' in sys.modules:
            logger.info("Using synchronous initialization for eventlet environment")
            # Use synchronous requests to validate token
            import requests

            try:
                response = requests.get(
                    f"https://api.telegram.org/bot{token}/getMe",
                    timeout=10
                )

                if response.status_code == 200:
                    data = response.json()
                    if data.get('ok'):
                        bot_info = data.get('result', {})
                        bot_username = bot_info.get('username', 'unknown')

                        # Store token and update config
                        self.bot_token = token
                        update_bot_config({
                            'bot_token': token,
                            'is_active': False,
                            'bot_username': bot_username
                        })

                        logger.info(f"Bot validated: @{bot_username}")
                        return True, f"Bot initialized successfully: @{bot_username}"
                    else:
                        return False, f"Invalid response: {data.get('description', 'Unknown error')}"
                else:
                    return False, f"HTTP {response.status_code}: Failed to validate token"

            except Exception as e:
                logger.error(f"Sync initialization error: {e}")
                # Store token anyway for retry later
                self.bot_token = token
                return True, "Token stored (will validate on start)"

        else:
            # Non-eventlet environment, use regular async initialization
            logger.info("Using async initialization (non-eventlet environment)")
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(self.initialize_bot(token))
            finally:
                loop.close()

    def _run_bot_in_thread(self):
        """Run bot in separate thread with its own isolated event loop"""
        import sys

        # Check if eventlet is active
        if 'eventlet' in sys.modules:
            logger.info("Eventlet detected - using special handling for asyncio")
            # For eventlet, we need to be very careful with asyncio
            import asyncio

            # Reset the event loop policy to avoid eventlet's monkey-patching
            try:
                # Use the default, unpatched event loop policy
                from asyncio import DefaultEventLoopPolicy, SelectorEventLoop
                policy = DefaultEventLoopPolicy()
                asyncio.set_event_loop_policy(policy)
                logger.info("Reset to default event loop policy")
            except Exception as e:
                logger.warning(f"Could not reset event loop policy: {e}")
        else:
            import asyncio

        # Create new event loop in this thread
        logger.info("Creating new event loop in bot thread")

        # Create a new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.bot_loop = loop  # Store the loop so we can schedule tasks in it

        try:
            # Create HTTP client in this thread's event loop
            self.http_client = httpx.AsyncClient(timeout=30.0)

            # Run the bot
            loop.run_until_complete(self._start_bot_isolated())
        except Exception as e:
            logger.error(f"Bot thread error: {e}")
        finally:
            # Cleanup
            try:
                if self.http_client:
                    loop.run_until_complete(self.http_client.aclose())
            except:
                pass
            loop.close()
            self.bot_loop = None  # Clear the reference
            self.is_running = False

    async def handle_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle errors in telegram bot operations"""
        import telegram.error

        error = context.error

        # Handle specific Telegram API errors
        if isinstance(error, telegram.error.NetworkError):
            logger.warning(f"Telegram NetworkError: {error}. Will retry automatically.")
        elif isinstance(error, telegram.error.Conflict):
            logger.error("Another instance of the bot is running! Please stop other instances.")
            self.is_running = False
        elif isinstance(error, telegram.error.TimedOut):
            logger.warning("Request to Telegram timed out. Will retry automatically.")
        elif isinstance(error, telegram.error.BadRequest):
            logger.error(f"Bad request to Telegram API: {error}")
        else:
            logger.error(f"Unhandled error in Telegram bot: {error}", exc_info=error)

        # If we have an update, try to inform the user (if possible)
        if update and hasattr(update, 'effective_chat'):
            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="⚠️ An error occurred. Please try again later."
                )
            except:
                pass  # If we can't send the message, just ignore

    async def _start_bot_isolated(self):
        """Start the bot with proper handlers and network error handling"""
        retry_count = 0
        max_retries = 5
        base_delay = 5  # seconds

        while retry_count < max_retries:
            try:
                # Create application
                self.application = Application.builder().token(self.bot_token).build()

                # Add command handlers
                self.application.add_handler(CommandHandler("start", self.cmd_start))
                self.application.add_handler(CommandHandler("help", self.cmd_help))
                self.application.add_handler(CommandHandler("link", self.cmd_link))
                self.application.add_handler(CommandHandler("unlink", self.cmd_unlink))
                self.application.add_handler(CommandHandler("status", self.cmd_status))
                self.application.add_handler(CommandHandler("orderbook", self.cmd_orderbook))
                self.application.add_handler(CommandHandler("tradebook", self.cmd_tradebook))
                self.application.add_handler(CommandHandler("positions", self.cmd_positions))
                self.application.add_handler(CommandHandler("holdings", self.cmd_holdings))
                self.application.add_handler(CommandHandler("funds", self.cmd_funds))
                self.application.add_handler(CommandHandler("pnl", self.cmd_pnl))
                self.application.add_handler(CommandHandler("quote", self.cmd_quote))
                self.application.add_handler(CommandHandler("chart", self.cmd_chart))
                self.application.add_handler(CommandHandler("menu", self.cmd_menu))

                # Add callback query handler for inline buttons
                self.application.add_handler(CallbackQueryHandler(self.button_callback))

                # Add error handler for network issues
                self.application.add_error_handler(self.handle_error)

                # Initialize
                await self.application.initialize()
                await self.application.start()

                # Configure polling with better error handling
                logger.debug("Starting bot in polling mode...")
                await self.application.updater.start_polling(
                    drop_pending_updates=True,  # Ignore old messages
                    allowed_updates=Update.ALL_TYPES
                )

                self.is_running = True
                update_bot_config({'is_active': True})
                logger.info("Telegram bot started successfully and is polling for updates")

                # Reset retry count on successful connection
                retry_count = 0

                # Keep running until stop signal
                while not self._stop_event.is_set():
                    await asyncio.sleep(1)

                # Stop signal received - clean shutdown
                logger.debug("Stop signal received, shutting down bot...")
                self.is_running = False

                # Stop the updater and wait for tasks to complete
                if self.application and self.application.updater.running:
                    await self.application.updater.stop()
                    await self.application.stop()
                    await self.application.shutdown()
                    # Give tasks a moment to clean up
                    await asyncio.sleep(0.5)

                # Clean shutdown when is_running becomes False
                logger.debug("Bot stopping gracefully...")
                break

            except (httpx.ConnectError, httpx.NetworkError, httpx.TimeoutException, telegram.error.NetworkError) as e:
                retry_count += 1
                delay = base_delay * (2 ** retry_count)  # Exponential backoff
                logger.warning(f"Network error while connecting to Telegram (attempt {retry_count}/{max_retries}): {type(e).__name__}")
                logger.debug(f"Network error details: {str(e)}")

                if retry_count < max_retries:
                    logger.info(f"Retrying in {delay} seconds...")
                    await asyncio.sleep(delay)
                else:
                    logger.error("Max retries reached. Unable to connect to Telegram servers.")
                    logger.info("This might be due to: 1) No internet connection, 2) Telegram blocked by firewall/ISP, 3) DNS issues")
                    self.is_running = False
                    break

            except Exception as e:
                # For non-network errors, log and stop
                logger.error(f"Unexpected error in bot operation: {e}")
                self.is_running = False
                break

        # Cleanup after the retry loop
        if self.application and hasattr(self.application, 'updater') and self.application.updater.running:
            try:
                await self.application.updater.stop()
            except Exception as e:
                logger.debug(f"Error stopping updater: {e}")

    def start_bot(self) -> Tuple[bool, str]:
        """Start the bot in a separate thread"""
        try:
            if self.is_running:
                return False, "Bot is already running"

            config = get_bot_config()
            if not config or not config.get('bot_token'):
                return False, "Bot token not configured"

            self.bot_token = config['bot_token']

            # Reset stop event
            self._stop_event.clear()

            # Start bot in separate thread with isolated event loop
            self.bot_thread = original_threading.Thread(
                target=self._run_bot_in_thread,
                daemon=True,
                name="TelegramBotThread"
            )
            self.bot_thread.start()

            # Wait for bot to start
            import time
            for _ in range(10):  # Wait up to 5 seconds
                if self.is_running:
                    return True, "Bot started successfully"
                time.sleep(0.5)

            return False, "Bot failed to start within timeout"

        except Exception as e:
            logger.error(f"Failed to start bot: {e}")
            return False, str(e)

    def stop_bot(self) -> Tuple[bool, str]:
        """Stop the bot"""
        try:
            if not self.is_running:
                return False, "Bot is not running"

            logger.debug("Stopping Telegram bot...")

            # Signal the thread to stop
            self._stop_event.set()

            # Wait for thread to finish
            if self.bot_thread and self.bot_thread.is_alive():
                self.bot_thread.join(timeout=10.0)
                if self.bot_thread.is_alive():
                    logger.warning("Bot thread did not stop cleanly")
                    self.is_running = False

            self.bot_thread = None
            self.application = None
            self.bot_loop = None  # Clear the loop reference

            # Update database
            update_bot_config({'is_active': False})

            logger.info("Telegram bot stopped")
            return True, "Bot stopped successfully"

        except Exception as e:
            logger.error(f"Failed to stop bot: {e}")
            return False, str(e)

    # Alias for compatibility
    stop_bot_sync = stop_bot

    # Command Handlers
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command"""
        user = update.effective_user

        # Check if user is already linked
        telegram_user = get_telegram_user(user.id)

        if telegram_user:
            await update.message.reply_text(
                f"Welcome back, {user.first_name}! 👋\n\n"
                "Your account is linked. Use /menu to see available options.",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                f"Welcome to OpenAlgo Bot, {user.first_name}! 🚀\n\n"
                "To get started, link your OpenAlgo account:\n"
                "`/link <api_key> <host_url>`\n\n"
                "Example:\n"
                "`/link your_api_key_here http://127.0.0.1:5000`\n\n"
                "Use /help to see all available commands.",
                parse_mode=ParseMode.MARKDOWN
            )

        log_command(user.id, 'start', update.effective_chat.id)

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command"""
        help_text = """
📚 *Available Commands:*

*Account Management:*
/link `<api_key> <host_url>` - Link your OpenAlgo account
/unlink - Unlink your account
/status - Check connection status

*Trading Information:*
/orderbook - View open orders
/tradebook - View executed trades
/positions - View current positions
/holdings - View holdings
/funds - View account funds
/pnl - View P&L (realized & unrealized)
/quote `<symbol> [exchange]` - Get stock quote

*Charts:*
/chart `<symbol> [exchange] [type] [interval] [days]`
  • type: intraday or daily (default: both)
  • interval: 1m, 5m, 15m, 30m, 1h, D (default: 5m for intraday, D for daily)
  • days: number of days (default: 5 for intraday, 252 for daily)

*Navigation:*
/menu - Show interactive menu
/help - Show this help message

*Examples:*
`/quote RELIANCE`
`/quote NIFTY NSE_INDEX`
`/chart RELIANCE`
`/chart RELIANCE NSE intraday 15m 10`
`/chart NIFTY NSE_INDEX daily D 100`
"""

        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
        log_command(update.effective_user.id, 'help', update.effective_chat.id)

    async def cmd_link(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /link command"""
        user = update.effective_user
        chat_id = update.effective_chat.id

        if not context.args or len(context.args) != 2:
            await update.message.reply_text(
                "❌ Invalid format\n"
                "Usage: `/link <api_key> <host_url>`\n"
                "Example: `/link your_api_key http://127.0.0.1:5000`",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        api_key = context.args[0]
        host_url = context.args[1].rstrip('/')

        # Validate API key by making a test call
        try:
            # Create temporary SDK client for validation
            test_client = openalgo_api(api_key=api_key, host=host_url)

            # Test with a simple call
            loop = asyncio.get_event_loop()
            test_response = await loop.run_in_executor(None, test_client.funds)

            if test_response and test_response.get('status') == 'success':
                # Valid credentials, save them
                # Get the actual OpenAlgo username from the API key
                openalgo_username = None
                try:
                    openalgo_username = get_username_by_apikey(api_key)
                    logger.info(f"API key lookup returned: '{openalgo_username}'")
                except Exception as e:
                    logger.error(f"Error getting username from API key: {e}")

                # If we couldn't get username from API key, try to extract from response
                if not openalgo_username and test_response.get('data'):
                    # Some brokers return username in the funds response
                    data = test_response.get('data', {})
                    if isinstance(data, dict):
                        openalgo_username = data.get('username') or data.get('user_id') or data.get('client_id')
                        if openalgo_username:
                            logger.info(f"Got username from funds response: {openalgo_username}")

                # Log for debugging
                logger.info(f"Linking Telegram user {user.id} (@{user.username}) with OpenAlgo username: '{openalgo_username}'")

                # If we still can't get username, DON'T use telegram username with @
                # Use a proper fallback
                if not openalgo_username:
                    # Try to get from session or use telegram ID
                    openalgo_username = f"user_{user.id}"
                    logger.warning(f"Could not get OpenAlgo username, using fallback: {openalgo_username}")
                else:
                    logger.info(f"Successfully retrieved OpenAlgo username: {openalgo_username}")

                create_or_update_telegram_user(
                    telegram_id=user.id,
                    username=openalgo_username,  # Use the actual OpenAlgo username
                    telegram_username=user.username,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    api_key=api_key,
                    host_url=host_url
                )

                logger.info(f"Database updated - Username stored as: {openalgo_username}")

                await update.message.reply_text(
                    "✅ Account linked successfully!\n"
                    "You can now use all bot features.\n"
                    "Type /menu to see available options.",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(
                    "❌ Failed to validate API key.\n"
                    "Please check your credentials and try again.",
                    parse_mode=ParseMode.MARKDOWN
                )

        except Exception as e:
            logger.error(f"Error linking account: {e}")
            await update.message.reply_text(
                "❌ Failed to link account.\n"
                f"Error: {str(e)}",
                parse_mode=ParseMode.MARKDOWN
            )

        log_command(user.id, 'link', chat_id)

    async def cmd_unlink(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /unlink command"""
        user = update.effective_user

        if delete_telegram_user(user.id):
            # Clear SDK client cache
            if user.id in self.sdk_clients:
                del self.sdk_clients[user.id]

            await update.message.reply_text(
                "✅ Account unlinked successfully.\n"
                "Your data has been removed.",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                "❌ No linked account found.",
                parse_mode=ParseMode.MARKDOWN
            )

        log_command(user.id, 'unlink', update.effective_chat.id)

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /status command"""
        user = update.effective_user
        telegram_user = get_telegram_user(user.id)

        if telegram_user:
            # Test connection using SDK
            client = self._get_sdk_client(user.id)
            if client:
                try:
                    loop = asyncio.get_event_loop()
                    test_response = await loop.run_in_executor(None, client.funds)

                    if test_response and test_response.get('status') == 'success':
                        status = "🟢 Connected"
                    else:
                        status = "🔴 Connection Failed"
                except:
                    status = "🔴 Connection Failed"
            else:
                status = "🔴 Client Error"

            await update.message.reply_text(
                f"*Account Status*\n"
                f"━━━━━━━━━━━━━━━\n"
                f"User: {telegram_user.get('username', 'N/A')}\n"
                f"Status: {status}\n"
                f"Host: {telegram_user.get('host_url', 'N/A')}\n"
                f"Linked: {telegram_user.get('created_at', 'N/A')}",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                "❌ No linked account found.\n"
                "Use /link to connect your OpenAlgo account.",
                parse_mode=ParseMode.MARKDOWN
            )

        log_command(user.id, 'status', update.effective_chat.id)

    async def cmd_orderbook(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /orderbook command"""
        user = update.effective_user
        telegram_user = get_telegram_user(user.id)

        if not telegram_user:
            await update.message.reply_text("❌ Please link your account first using /link")
            return

        # Get orderbook using SDK
        client = self._get_sdk_client(user.id)
        if not client:
            await update.message.reply_text("❌ Failed to connect to OpenAlgo")
            return

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, client.orderbook)

        if not response or response.get('status') != 'success':
            await update.message.reply_text("❌ Failed to fetch orderbook")
            return

        orders = response.get('data', {}).get('orders', [])
        statistics = response.get('data', {}).get('statistics', {})

        if not orders:
            await update.message.reply_text("📊 *ORDERBOOK*\n━━━━━━━━━━━━━━━\n\nNo open orders", parse_mode=ParseMode.MARKDOWN)
            return

        message = "📊 *ORDERBOOK*\n━━━━━━━━━━━━━━━\n\n"

        for order in orders[:10]:  # Limit to 10 orders
            status = order.get('order_status', 'unknown')
            status_emoji = "✅" if status == 'complete' else "🟡" if status == 'open' else "❌" if status == 'rejected' else "⏸️"
            action_emoji = "📈" if order.get('action') == 'BUY' else "📉"

            # Handle price and quantity (might be strings from some brokers)
            try:
                price = float(order.get('price', 0))
                price_str = "Market" if price == 0 and order.get('pricetype') == 'MARKET' else f"₹{price}"
            except (ValueError, TypeError):
                price_str = f"₹{order.get('price', 0)}"

            try:
                quantity = int(order.get('quantity', 0))
            except (ValueError, TypeError):
                quantity = order.get('quantity', 0)

            message += (
                f"{status_emoji} *{order.get('symbol', 'N/A')}* ({order.get('exchange', 'N/A')})\n"
                f"{action_emoji} {order.get('action', 'N/A')} {quantity} @ {price_str}\n"
                f"├ Type: {order.get('pricetype', 'N/A')}\n"
                f"├ Product: {order.get('product', 'N/A')}\n"
                f"├ Status: {status.title()}\n"
                f"├ Time: {order.get('timestamp', 'N/A')}\n"
            )

            # Handle trigger price (might be string from some brokers)
            try:
                trigger_price = float(order.get('trigger_price', 0))
                if trigger_price > 0:
                    message += f"├ Trigger: ₹{trigger_price}\n"
            except (ValueError, TypeError):
                # If conversion fails, skip trigger price
                pass

            message += f"└ Order ID: `{order.get('orderid', 'N/A')}`\n\n"

        if len(orders) > 10:
            message += f"_... and {len(orders) - 10} more orders_\n\n"

        # Add statistics summary
        if statistics:
            # Handle statistics that might be strings from some brokers
            try:
                total_open = int(statistics.get('total_open_orders', 0))
            except (ValueError, TypeError):
                total_open = 0

            try:
                total_completed = int(statistics.get('total_completed_orders', 0))
            except (ValueError, TypeError):
                total_completed = 0

            try:
                total_rejected = int(statistics.get('total_rejected_orders', 0))
            except (ValueError, TypeError):
                total_rejected = 0

            try:
                total_buy = int(statistics.get('total_buy_orders', 0))
            except (ValueError, TypeError):
                total_buy = 0

            try:
                total_sell = int(statistics.get('total_sell_orders', 0))
            except (ValueError, TypeError):
                total_sell = 0

            message += (
                "📈 *Summary*\n"
                f"├ Total Orders: {len(orders)}\n"
                f"├ Open: {total_open}\n"
                f"├ Completed: {total_completed}\n"
                f"├ Rejected: {total_rejected}\n"
                f"├ Buy Orders: {total_buy}\n"
                f"└ Sell Orders: {total_sell}"
            )

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
        log_command(user.id, 'orderbook', update.effective_chat.id)

    async def cmd_tradebook(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /tradebook command"""
        user = update.effective_user
        telegram_user = get_telegram_user(user.id)

        if not telegram_user:
            await update.message.reply_text("❌ Please link your account first using /link")
            return

        # Get tradebook using SDK
        client = self._get_sdk_client(user.id)
        if not client:
            await update.message.reply_text("❌ Failed to connect to OpenAlgo")
            return

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, client.tradebook)

        if not response or response.get('status') != 'success':
            await update.message.reply_text("❌ Failed to fetch tradebook")
            return

        trades = response.get('data', [])

        if not trades:
            await update.message.reply_text("📈 *TRADEBOOK*\n━━━━━━━━━━━━━━━\n\nNo trades executed today", parse_mode=ParseMode.MARKDOWN)
            return

        message = "📈 *TRADEBOOK*\n━━━━━━━━━━━━━━━\n\n"
        total_buy_value = 0
        total_sell_value = 0

        for trade in trades[:10]:  # Limit to 10 trades
            action_emoji = "📈" if trade.get('action') == 'BUY' else "📉"

            # Handle trade_value (might be string from some brokers)
            try:
                trade_value = float(trade.get('trade_value', 0))
            except (ValueError, TypeError):
                trade_value = 0.0

            if trade.get('action') == 'BUY':
                total_buy_value += trade_value
            else:
                total_sell_value += trade_value

            # Handle quantity and average_price formatting
            try:
                quantity = int(trade.get('quantity', 0))
            except (ValueError, TypeError):
                quantity = trade.get('quantity', 0)

            try:
                avg_price = float(trade.get('average_price', 0))
                avg_price_str = f"₹{avg_price:,.2f}"
            except (ValueError, TypeError):
                avg_price_str = f"₹{trade.get('average_price', 0)}"

            message += (
                f"{action_emoji} *{trade.get('symbol', 'N/A')}* ({trade.get('exchange', 'N/A')})\n"
                f"├ {trade.get('action', 'N/A')} {quantity} @ {avg_price_str}\n"
                f"├ Product: {trade.get('product', 'N/A')}\n"
                f"├ Value: ₹{trade_value:,.2f}\n"
                f"├ Time: {trade.get('timestamp', 'N/A')}\n"
                f"└ Order ID: `{trade.get('orderid', 'N/A')}`\n\n"
            )

        if len(trades) > 10:
            message += f"_... and {len(trades) - 10} more trades_\n\n"

        # Add summary
        message += (
            "📊 *Summary*\n"
            f"├ Total Trades: {len(trades)}\n"
            f"├ Buy Value: ₹{total_buy_value:,.2f}\n"
            f"└ Sell Value: ₹{total_sell_value:,.2f}"
        )

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
        log_command(user.id, 'tradebook', update.effective_chat.id)

    async def cmd_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /positions command"""
        user = update.effective_user
        telegram_user = get_telegram_user(user.id)

        if not telegram_user:
            await update.message.reply_text("❌ Please link your account first using /link")
            return

        # Get positions using SDK
        client = self._get_sdk_client(user.id)
        if not client:
            await update.message.reply_text("❌ Failed to connect to OpenAlgo")
            return

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, client.positionbook)

        if not response or response.get('status') != 'success':
            await update.message.reply_text("❌ Failed to fetch positions")
            return

        positions = response.get('data', [])

        if not positions:
            await update.message.reply_text("💼 *POSITIONS*\n━━━━━━━━━━━━━━━\n\nNo open positions", parse_mode=ParseMode.MARKDOWN)
            return

        # Filter out positions with 0 quantity
        active_positions = [pos for pos in positions if pos.get('quantity', 0) != 0]

        if not active_positions:
            await update.message.reply_text("💼 *POSITIONS*\n━━━━━━━━━━━━━━━\n\nNo active positions", parse_mode=ParseMode.MARKDOWN)
            return

        message = "💼 *POSITIONS*\n━━━━━━━━━━━━━━━\n\n"
        total_long = 0
        total_short = 0

        for pos in active_positions[:10]:  # Limit to 10 positions
            # Handle quantity and average_price (might be strings from some brokers)
            try:
                quantity = int(pos.get('quantity', 0))
            except (ValueError, TypeError):
                quantity = 0

            try:
                avg_price = float(pos.get('average_price', '0.00') or 0)
            except (ValueError, TypeError):
                avg_price = 0.0

            # Determine position type
            if quantity > 0:
                position_type = "LONG 📈"
                position_emoji = "🟢"
                total_long += 1
            else:
                position_type = "SHORT 📉"
                position_emoji = "🔴"
                total_short += 1

            message += (
                f"{position_emoji} *{pos.get('symbol', 'N/A')}* ({pos.get('exchange', 'N/A')})\n"
                f"├ Position: {position_type}\n"
                f"├ Qty: {abs(quantity)} ({pos.get('product', 'N/A')})\n"
            )

            if avg_price > 0:
                message += f"├ Avg Price: ₹{avg_price:,.2f}\n"

            message += "\n"

        if len(active_positions) > 10:
            message += f"_... and {len(active_positions) - 10} more positions_\n\n"

        # Add summary
        message += (
            "📊 *Summary*\n"
            f"├ Active Positions: {len(active_positions)}\n"
            f"├ Long Positions: {total_long}\n"
            f"└ Short Positions: {total_short}"
        )

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
        log_command(user.id, 'positions', update.effective_chat.id)

    async def cmd_holdings(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /holdings command"""
        user = update.effective_user
        telegram_user = get_telegram_user(user.id)

        if not telegram_user:
            await update.message.reply_text("❌ Please link your account first using /link")
            return

        # Get holdings using SDK
        client = self._get_sdk_client(user.id)
        if not client:
            await update.message.reply_text("❌ Failed to connect to OpenAlgo")
            return

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, client.holdings)

        if not response or response.get('status') != 'success':
            await update.message.reply_text("❌ Failed to fetch holdings")
            return

        holdings = response.get('data', {}).get('holdings', [])
        statistics = response.get('data', {}).get('statistics', {})

        if not holdings:
            await update.message.reply_text("🏦 *HOLDINGS*\n━━━━━━━━━━━━━━━\n\nNo holdings found", parse_mode=ParseMode.MARKDOWN)
            return

        message = "🏦 *HOLDINGS*\n━━━━━━━━━━━━━━━\n\n"

        for holding in holdings[:10]:
            # Handle numeric values that might be strings from some brokers
            try:
                pnl = float(holding.get('pnl', 0))
            except (ValueError, TypeError):
                pnl = 0.0

            try:
                pnl_percent = float(holding.get('pnlpercent', 0))
            except (ValueError, TypeError):
                pnl_percent = 0.0

            try:
                quantity = int(holding.get('quantity', 0))
            except (ValueError, TypeError):
                quantity = 0

            pnl_emoji = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "⚪"

            message += (
                f"{pnl_emoji} *{holding.get('symbol', 'N/A')}* ({holding.get('exchange', 'N/A')})\n"
                f"├ Product: {holding.get('product', 'CNC')}\n"
                f"├ Qty: {quantity}\n"
                f"└ P&L: ₹{pnl:,.2f} ({pnl_percent:+.2f}%)\n\n"
            )

        if len(holdings) > 10:
            message += f"_... and {len(holdings) - 10} more holdings_\n\n"

        # Add statistics
        if statistics:
            # Handle statistics that might be strings from some brokers
            try:
                total_holding_value = float(statistics.get('totalholdingvalue', 0))
            except (ValueError, TypeError):
                total_holding_value = 0.0

            try:
                total_inv_value = float(statistics.get('totalinvvalue', 0))
            except (ValueError, TypeError):
                total_inv_value = 0.0

            try:
                total_pnl = float(statistics.get('totalprofitandloss', 0))
            except (ValueError, TypeError):
                total_pnl = 0.0

            try:
                total_pnl_percent = float(statistics.get('totalpnlpercentage', 0))
            except (ValueError, TypeError):
                total_pnl_percent = 0.0

            stats_emoji = "🟢" if total_pnl > 0 else "🔴" if total_pnl < 0 else "⚪"

            message += (
                f"📊 *Portfolio Summary*\n"
                f"├ Current Value: ₹{total_holding_value:,.2f}\n"
                f"├ Investment: ₹{total_inv_value:,.2f}\n"
                f"└ {stats_emoji} P&L: ₹{total_pnl:,.2f} ({total_pnl_percent:+.2f}%)"
            )

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
        log_command(user.id, 'holdings', update.effective_chat.id)

    async def cmd_funds(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /funds command"""
        user = update.effective_user
        telegram_user = get_telegram_user(user.id)

        if not telegram_user:
            await update.message.reply_text("❌ Please link your account first using /link")
            return

        # Get funds using SDK
        client = self._get_sdk_client(user.id)
        if not client:
            await update.message.reply_text("❌ Failed to connect to OpenAlgo")
            return

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, client.funds)

        if not response or response.get('status') != 'success':
            await update.message.reply_text("❌ Failed to fetch funds")
            return

        funds = response.get('data', {})

        # Handle funds that might be strings from some brokers
        try:
            available = float(funds.get('availablecash', 0))
        except (ValueError, TypeError):
            available = 0.0

        try:
            collateral = float(funds.get('collateral', 0))
        except (ValueError, TypeError):
            collateral = 0.0

        try:
            utilized = float(funds.get('utiliseddebits', 0))
        except (ValueError, TypeError):
            utilized = 0.0

        message = (
            "💰 *FUNDS*\n"
            "━━━━━━━━━━━━━━━\n\n"
            f"💵 *Available Cash*\n"
            f"└ ₹{available:,.2f}\n\n"
            f"🔒 *Collateral*\n"
            f"└ ₹{collateral:,.2f}\n\n"
            f"📊 *Utilized Margin*\n"
            f"└ ₹{utilized:,.2f}\n\n"
            f"💼 *Total Balance*\n"
            f"└ ₹{(available + collateral):,.2f}"
        )

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
        log_command(user.id, 'funds', update.effective_chat.id)

    async def cmd_pnl(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /pnl command"""
        user = update.effective_user
        telegram_user = get_telegram_user(user.id)

        if not telegram_user:
            await update.message.reply_text("❌ Please link your account first using /link")
            return

        # Get P&L from funds using SDK
        client = self._get_sdk_client(user.id)
        if not client:
            await update.message.reply_text("❌ Failed to connect to OpenAlgo")
            return

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, client.funds)

        if not response or response.get('status') != 'success':
            await update.message.reply_text("❌ Failed to fetch P&L")
            return

        funds = response.get('data', {})

        # Handle P&L values that might be strings from some brokers
        try:
            realized_pnl = float(funds.get('m2mrealized', 0))
        except (ValueError, TypeError):
            realized_pnl = 0.0

        try:
            unrealized_pnl = float(funds.get('m2munrealized', 0))
        except (ValueError, TypeError):
            unrealized_pnl = 0.0

        total_pnl = realized_pnl + unrealized_pnl

        # Emojis based on P&L
        realized_emoji = "🟢" if realized_pnl > 0 else "🔴" if realized_pnl < 0 else "⚪"
        unrealized_emoji = "🟢" if unrealized_pnl > 0 else "🔴" if unrealized_pnl < 0 else "⚪"
        total_emoji = "🟢" if total_pnl > 0 else "🔴" if total_pnl < 0 else "⚪"

        message = (
            "💹 *PROFIT & LOSS*\n"
            "━━━━━━━━━━━━━━━\n\n"
            f"{realized_emoji} *Realized P&L*\n"
            f"└ ₹{realized_pnl:,.2f}\n\n"
            f"{unrealized_emoji} *Unrealized P&L*\n"
            f"└ ₹{unrealized_pnl:,.2f}\n\n"
            f"{total_emoji} *Total P&L*\n"
            f"└ ₹{total_pnl:,.2f}"
        )

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
        log_command(user.id, 'pnl', update.effective_chat.id)

    async def cmd_quote(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /quote command"""
        user = update.effective_user
        telegram_user = get_telegram_user(user.id)

        if not telegram_user:
            await update.message.reply_text("❌ Please link your account first using /link")
            return

        if not context.args:
            await update.message.reply_text(
                "❌ Usage: /quote <symbol> [exchange]\n"
                "Example: /quote RELIANCE\n"
                "Example: /quote NIFTY NSE_INDEX",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        symbol = context.args[0].upper()
        exchange = context.args[1].upper() if len(context.args) > 1 else 'NSE'

        # Get quote using SDK
        client = self._get_sdk_client(user.id)
        if not client:
            await update.message.reply_text("❌ Failed to connect to OpenAlgo")
            return

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.quotes(symbol=symbol, exchange=exchange)
        )

        if not response or response.get('status') != 'success':
            await update.message.reply_text(f"❌ Failed to fetch quote for {symbol}")
            return

        quote = response.get('data', {})

        # Handle quote values that might be strings from some brokers
        try:
            ltp = float(quote.get('ltp', 0))
        except (ValueError, TypeError):
            ltp = 0.0

        try:
            prev_close = float(quote.get('prev_close', ltp))
        except (ValueError, TypeError):
            prev_close = ltp

        change = ltp - prev_close
        change_pct = (change / prev_close * 100) if prev_close > 0 else 0

        change_emoji = "🟢" if change > 0 else "🔴" if change < 0 else "⚪"

        # Handle other quote values
        try:
            open_price = float(quote.get('open', 0))
        except (ValueError, TypeError):
            open_price = 0.0

        try:
            high_price = float(quote.get('high', 0))
        except (ValueError, TypeError):
            high_price = 0.0

        try:
            low_price = float(quote.get('low', 0))
        except (ValueError, TypeError):
            low_price = 0.0

        try:
            volume = int(quote.get('volume', 0))
        except (ValueError, TypeError):
            volume = 0

        message = (
            f"📊 *{symbol}*\n"
            "━━━━━━━━━━━━━━━\n\n"
            f"{change_emoji} Price: ₹{ltp:,.2f}\n"
            f"├ Change: ₹{change:+.2f} ({change_pct:+.2f}%)\n"
            f"├ Open: ₹{open_price:,.2f}\n"
            f"├ High: ₹{high_price:,.2f}\n"
            f"├ Low: ₹{low_price:,.2f}\n"
            f"├ Prev Close: ₹{prev_close:,.2f}\n"
            f"└ Volume: {volume:,}"
        )

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
        log_command(user.id, 'quote', update.effective_chat.id)

    async def cmd_chart(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /chart command with customizable parameters"""
        user = update.effective_user
        telegram_user = get_telegram_user(user.id)

        if not telegram_user:
            await update.message.reply_text("❌ Please link your account first using /link")
            return

        if not context.args:
            await update.message.reply_text(
                "❌ Usage: /chart <symbol> [exchange] [type] [interval] [days]\n"
                "Type: intraday (default), daily, or both\n\n"
                "Examples:\n"
                "/chart RELIANCE - 5m intraday chart\n"
                "/chart RELIANCE NSE intraday 15m 10\n"
                "/chart NIFTY NSE_INDEX daily D 100\n"
                "/chart RELIANCE NSE both - Both charts",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        # Parse arguments with defaults
        symbol = context.args[0].upper()
        exchange = context.args[1].upper() if len(context.args) > 1 else 'NSE'
        chart_type = context.args[2].lower() if len(context.args) > 2 else 'intraday'  # Default to intraday only
        interval = context.args[3] if len(context.args) > 3 else None
        days = int(context.args[4]) if len(context.args) > 4 else None

        # Set default intervals and days based on chart type
        if chart_type in ['intraday', 'i']:
            interval = interval or '5m'
            days = days or 5
        elif chart_type in ['daily', 'd']:
            interval = interval or 'D'
            days = days or 252
        else:  # both
            pass

        # Send loading message
        loading_msg = await update.message.reply_text("📊 Generating charts... Please wait.")

        try:
            charts_generated = []

            if chart_type in ['both', 'intraday', 'i']:
                # Generate intraday chart
                intraday_interval = interval or '5m'
                intraday_days = days or 5
                intraday_chart = await self._generate_intraday_chart(
                    symbol, exchange, intraday_interval, intraday_days, user.id
                )
                if intraday_chart:
                    charts_generated.append(
                        InputMediaPhoto(
                            intraday_chart,
                            caption=f"{symbol} - {intraday_days} Day Intraday Chart ({intraday_interval} intervals)"
                        )
                    )

            if chart_type in ['both', 'daily', 'd']:
                # Generate daily chart
                daily_interval = 'D' if chart_type == 'both' else (interval or 'D')
                daily_days = 252 if chart_type == 'both' else (days or 252)
                daily_chart = await self._generate_daily_chart(
                    symbol, exchange, daily_interval, daily_days, user.id
                )
                if daily_chart:
                    charts_generated.append(
                        InputMediaPhoto(
                            daily_chart,
                            caption=f"{symbol} - Daily Chart ({daily_days} days)"
                        )
                    )

            # Delete loading message
            await loading_msg.delete()

            if charts_generated:
                if len(charts_generated) > 1:
                    await update.message.reply_media_group(charts_generated)
                else:
                    await update.message.reply_photo(
                        photo=charts_generated[0].media,
                        caption=charts_generated[0].caption
                    )
            else:
                await update.message.reply_text(f"❌ Failed to generate charts for {symbol}")

        except Exception as e:
            logger.error(f"Error generating charts: {e}")
            try:
                await loading_msg.delete()
            except:
                pass
            await update.message.reply_text(f"❌ Error generating charts: {str(e)}")

        log_command(user.id, 'chart', update.effective_chat.id)

    async def cmd_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /menu command"""
        user = update.effective_user
        telegram_user = get_telegram_user(user.id)

        if not telegram_user:
            await update.message.reply_text("❌ Please link your account first using /link")
            return

        keyboard = [
            [
                InlineKeyboardButton("📊 Orderbook", callback_data='orderbook'),
                InlineKeyboardButton("📈 Tradebook", callback_data='tradebook'),
            ],
            [
                InlineKeyboardButton("💼 Positions", callback_data='positions'),
                InlineKeyboardButton("🏦 Holdings", callback_data='holdings'),
            ],
            [
                InlineKeyboardButton("💰 Funds", callback_data='funds'),
                InlineKeyboardButton("💹 P&L", callback_data='pnl'),
            ],
            [
                InlineKeyboardButton("🔄 Refresh", callback_data='menu'),
            ]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "📱 *OpenAlgo Trading Menu*\n"
            "Select an option below:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )

        log_command(user.id, 'menu', update.effective_chat.id)

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle inline button callbacks"""
        query = update.callback_query
        await query.answer()

        # Map callback data to commands
        command_map = {
            'orderbook': self.cmd_orderbook,
            'tradebook': self.cmd_tradebook,
            'positions': self.cmd_positions,
            'holdings': self.cmd_holdings,
            'funds': self.cmd_funds,
            'pnl': self.cmd_pnl,
            'menu': self.cmd_menu
        }

        handler = command_map.get(query.data)
        if handler:
            # Create a fake update with message for the handler
            fake_update = Update(
                update_id=update.update_id,
                message=query.message,
                callback_query=query
            )
            fake_update.effective_user = query.from_user
            fake_update.effective_chat = query.message.chat

            await handler(fake_update, context)

    async def send_notification(self, telegram_id: int, message: str) -> bool:
        """Send a notification to a specific Telegram user."""
        try:
            if not self.application or not self.is_running:
                logger.error("Bot not initialized or not running")
                return False

            # Get the bot from the application
            bot = self.application.bot

            await bot.send_message(
                chat_id=telegram_id,
                text=message,
                parse_mode='Markdown'
            )
            logger.debug(f"Notification sent to telegram_id: {telegram_id}")
            return True
        except Exception as e:
            logger.error(f"Error sending notification to {telegram_id}: {str(e)}")
            return False

    async def broadcast_message(self, message: str, filters: Dict = None) -> Tuple[int, int]:
        """Broadcast a message to all or filtered users."""
        try:
            if not self.application or not self.is_running:
                logger.error("Bot not initialized or not running for broadcast")
                return 0, 0

            # Get all telegram users
            users = get_all_telegram_users()

            # Apply filters if provided
            if filters:
                # Filter users based on criteria
                if filters.get('notifications_enabled') is not None:
                    users = [u for u in users if u.get('notifications_enabled') == filters['notifications_enabled']]
                if filters.get('openalgo_username'):
                    users = [u for u in users if u.get('openalgo_username') == filters['openalgo_username']]

            success_count = 0
            fail_count = 0

            for user in users:
                try:
                    telegram_id = user.get('telegram_id')
                    if telegram_id:
                        bot = self.application.bot
                        await bot.send_message(
                            chat_id=telegram_id,
                            text=message,
                            parse_mode='Markdown'
                        )
                        success_count += 1
                        # Add small delay to avoid rate limits
                        await asyncio.sleep(0.1)
                except Exception as e:
                    logger.error(f"Failed to send broadcast to {user.get('telegram_id')}: {str(e)}")
                    fail_count += 1

            logger.debug(f"Broadcast complete: {success_count} success, {fail_count} failed")
            return success_count, fail_count

        except Exception as e:
            logger.error(f"Error in broadcast: {str(e)}")
            return 0, 0


# Create global instance
telegram_bot_service = TelegramBotService()