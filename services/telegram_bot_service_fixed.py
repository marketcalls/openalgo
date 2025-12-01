import os
import asyncio
import logging
import threading
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
import httpx
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode
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
from utils.logging import get_logger

logger = get_logger(__name__)

class TelegramBotService:
    """Service class for managing Telegram bot operations with OpenAlgo SDK integration"""

    def __init__(self):
        self.application = None
        self.bot = None
        self.is_running = False
        self.bot_token = None
        self.webhook_url = None
        self.polling_mode = True  # Default to polling mode
        self.http_client = httpx.AsyncClient(timeout=30.0)
        self.bot_thread = None
        self.bot_loop = None
        self.sdk_clients = {}  # Cache for OpenAlgo SDK clients per user

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

            logger.info(f"Generating intraday chart for {symbol} on {exchange} with interval {interval}")

            # Get historical data
            loop = asyncio.get_event_loop()
            history_data = await loop.run_in_executor(
                None,
                client.history,
                symbol,
                exchange,
                interval,
                start_date.strftime("%Y-%m-%d"),
                end_date.strftime("%Y-%m-%d")
            )

            if not history_data or history_data.get('status') != 'success':
                logger.error(f"Failed to fetch history data: {history_data}")
                return None

            # Convert to DataFrame
            df = pd.DataFrame(history_data['data'])
            if df.empty:
                logger.error("No data available for chart generation")
                return None

            df['date'] = pd.to_datetime(df['date'])

            # Create candlestick chart with volume
            fig = make_subplots(
                rows=2, cols=1,
                shared_xaxes=True,
                vertical_spacing=0.03,
                subplot_titles=(f'{symbol} - {days} Day Intraday ({interval})', 'Volume'),
                row_heights=[0.7, 0.3]
            )

            # Add candlestick chart
            fig.add_trace(
                go.Candlestick(
                    x=df['date'],
                    open=df['open'],
                    high=df['high'],
                    low=df['low'],
                    close=df['close'],
                    name='Price'
                ),
                row=1, col=1
            )

            # Add volume bar chart
            colors = ['red' if close < open else 'green'
                     for close, open in zip(df['close'], df['open'])]

            fig.add_trace(
                go.Bar(
                    x=df['date'],
                    y=df['volume'],
                    marker_color=colors,
                    name='Volume',
                    showlegend=False
                ),
                row=2, col=1
            )

            # Update layout
            fig.update_layout(
                title=f'{symbol} ({exchange}) - Intraday Chart',
                xaxis_rangeslider_visible=False,
                height=800,
                template='plotly_white',
                showlegend=False
            )

            # Update x-axis
            fig.update_xaxes(title_text="Date", row=2, col=1)
            fig.update_yaxes(title_text="Price (₹)", row=1, col=1)
            fig.update_yaxes(title_text="Volume", row=2, col=1)

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

            logger.info(f"Generating daily chart for {symbol} on {exchange} with interval {interval}")

            # Get historical data
            loop = asyncio.get_event_loop()
            history_data = await loop.run_in_executor(
                None,
                client.history,
                symbol,
                exchange,
                interval,
                start_date.strftime("%Y-%m-%d"),
                end_date.strftime("%Y-%m-%d")
            )

            if not history_data or history_data.get('status') != 'success':
                logger.error(f"Failed to fetch history data: {history_data}")
                return None

            # Convert to DataFrame and limit to requested days
            df = pd.DataFrame(history_data['data'])
            if df.empty:
                logger.error("No data available for chart generation")
                return None

            df['date'] = pd.to_datetime(df['date'])
            df = df.tail(days)  # Keep last N trading days

            # Calculate moving averages
            df['MA20'] = df['close'].rolling(window=20).mean()
            df['MA50'] = df['close'].rolling(window=50).mean()
            if len(df) >= 200:
                df['MA200'] = df['close'].rolling(window=200).mean()

            # Create candlestick chart with volume
            fig = make_subplots(
                rows=2, cols=1,
                shared_xaxes=True,
                vertical_spacing=0.03,
                subplot_titles=(f'{symbol} - Daily Chart ({days} Days)', 'Volume'),
                row_heights=[0.7, 0.3]
            )

            # Add candlestick chart
            fig.add_trace(
                go.Candlestick(
                    x=df['date'],
                    open=df['open'],
                    high=df['high'],
                    low=df['low'],
                    close=df['close'],
                    name='Price'
                ),
                row=1, col=1
            )

            # Add moving averages
            fig.add_trace(
                go.Scatter(
                    x=df['date'],
                    y=df['MA20'],
                    mode='lines',
                    name='MA20',
                    line=dict(color='orange', width=1)
                ),
                row=1, col=1
            )

            fig.add_trace(
                go.Scatter(
                    x=df['date'],
                    y=df['MA50'],
                    mode='lines',
                    name='MA50',
                    line=dict(color='blue', width=1)
                ),
                row=1, col=1
            )

            if 'MA200' in df.columns:
                fig.add_trace(
                    go.Scatter(
                        x=df['date'],
                        y=df['MA200'],
                        mode='lines',
                        name='MA200',
                        line=dict(color='red', width=1)
                    ),
                    row=1, col=1
                )

            # Add volume bar chart
            colors = ['red' if close < open else 'green'
                     for close, open in zip(df['close'], df['open'])]

            fig.add_trace(
                go.Bar(
                    x=df['date'],
                    y=df['volume'],
                    marker_color=colors,
                    name='Volume',
                    showlegend=False
                ),
                row=2, col=1
            )

            # Update layout
            fig.update_layout(
                title=f'{symbol} ({exchange}) - Daily Chart with Moving Averages',
                xaxis_rangeslider_visible=False,
                height=800,
                template='plotly_white',
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1
                )
            )

            # Update x-axis
            fig.update_xaxes(title_text="Date", row=2, col=1)
            fig.update_yaxes(title_text="Price (₹)", row=1, col=1)
            fig.update_yaxes(title_text="Volume", row=2, col=1)

            # Convert to image bytes
            img_bytes = fig.to_image(format="png", engine="kaleido")
            return img_bytes

        except Exception as e:
            logger.error(f"Error generating daily chart: {e}")
            return None

    async def initialize_bot(self, token: str, webhook_url: Optional[str] = None) -> Tuple[bool, str]:
        """Initialize the Telegram bot with given token"""
        try:
            self.bot_token = token
            self.webhook_url = webhook_url

            # Create a temporary bot just to verify the token
            temp_app = Application.builder().token(token).build()
            await temp_app.initialize()

            # Test the token by getting bot info
            bot_info = await temp_app.bot.get_me()

            await temp_app.shutdown()

            # Update bot config in database
            update_bot_config({
                'bot_token': token,
                'webhook_url': webhook_url,
                'is_active': False
            })

            return True, f"Bot initialized successfully: @{bot_info.username}"

        except Exception as e:
            logger.error(f"Failed to initialize bot: {e}")
            return False, str(e)

    def _run_bot_async(self):
        """Run bot in separate thread with its own event loop"""
        self.bot_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.bot_loop)
        self.bot_loop.run_until_complete(self._start_bot())

    async def _start_bot(self):
        """Start the bot with proper handlers"""
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

            # Initialize
            await self.application.initialize()
            await self.application.start()

            if self.polling_mode:
                logger.info("Starting bot in polling mode...")
                await self.application.updater.start_polling()
            else:
                logger.info(f"Setting webhook to: {self.webhook_url}")
                await self.application.bot.set_webhook(self.webhook_url)

            self.is_running = True
            update_bot_config({'is_active': True})

            # Keep running
            while self.is_running:
                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Error in bot operation: {e}")
            self.is_running = False
            raise

    async def start_bot(self, polling: bool = True) -> Tuple[bool, str]:
        """Start the bot in polling or webhook mode"""
        try:
            if self.is_running:
                return False, "Bot is already running"

            config = get_bot_config()
            if not config or not config.get('bot_token'):
                return False, "Bot token not configured"

            self.bot_token = config['bot_token']
            self.webhook_url = config.get('webhook_url')
            self.polling_mode = polling

            # Start bot in separate thread
            self.bot_thread = threading.Thread(target=self._run_bot_async, daemon=True)
            self.bot_thread.start()

            # Wait a bit for the bot to start
            await asyncio.sleep(2)

            if self.is_running:
                return True, "Bot started successfully"
            else:
                return False, "Bot failed to start"

        except Exception as e:
            logger.error(f"Failed to start bot: {e}")
            return False, str(e)

    async def stop_bot(self) -> Tuple[bool, str]:
        """Stop the bot"""
        try:
            if not self.is_running:
                return False, "Bot is not running"

            self.is_running = False

            if self.application:
                await self.application.updater.stop()
                await self.application.stop()
                await self.application.shutdown()

            update_bot_config({'is_active': False})

            return True, "Bot stopped successfully"

        except Exception as e:
            logger.error(f"Failed to stop bot: {e}")
            return False, str(e)

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
                create_or_update_telegram_user(
                    telegram_id=user.id,
                    username=user.username,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    chat_id=chat_id,
                    api_key=api_key,
                    host_url=host_url
                )

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

        if not orders:
            await update.message.reply_text("📊 *ORDERBOOK*\n━━━━━━━━━━━━━━━\n\nNo open orders", parse_mode=ParseMode.MARKDOWN)
            return

        message = "📊 *ORDERBOOK*\n━━━━━━━━━━━━━━━\n\n"

        for order in orders[:10]:  # Limit to 10 orders
            status_emoji = "🟢" if order.get('status') == 'open' else "🔴"
            action_emoji = "📈" if order.get('action') == 'BUY' else "📉"

            message += (
                f"{status_emoji} *{order.get('symbol', 'N/A')}* ({order.get('exchange', 'N/A')})\n"
                f"{action_emoji} {order.get('action', 'N/A')} {order.get('quantity', 0)} @ ₹{order.get('price', 0)}\n"
                f"├ Type: {order.get('pricetype', 'N/A')}\n"
                f"├ Product: {order.get('product', 'N/A')}\n"
                f"├ Status: {order.get('status', 'N/A')}\n"
                f"└ Order ID: `{order.get('orderid', 'N/A')}`\n\n"
            )

        if len(orders) > 10:
            message += f"_... and {len(orders) - 10} more orders_"

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

        for trade in trades[:10]:  # Limit to 10 trades
            action_emoji = "📈" if trade.get('action') == 'BUY' else "📉"

            message += (
                f"{action_emoji} *{trade.get('symbol', 'N/A')}* ({trade.get('exchange', 'N/A')})\n"
                f"├ {trade.get('action', 'N/A')} {trade.get('quantity', 0)} @ ₹{trade.get('price', 0)}\n"
                f"├ Product: {trade.get('product', 'N/A')}\n"
                f"├ Time: {trade.get('trade_time', 'N/A')}\n"
                f"└ Trade ID: `{trade.get('tradeid', 'N/A')}`\n\n"
            )

        if len(trades) > 10:
            message += f"_... and {len(trades) - 10} more trades_"

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

        message = "💼 *POSITIONS*\n━━━━━━━━━━━━━━━\n\n"
        total_pnl = 0

        for pos in positions:
            pnl = float(pos.get('pnl', 0))
            total_pnl += pnl
            pnl_emoji = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "⚪"

            message += (
                f"{pnl_emoji} *{pos.get('symbol', 'N/A')}* ({pos.get('exchange', 'N/A')})\n"
                f"├ Qty: {pos.get('netqty', 0)} ({pos.get('product', 'N/A')})\n"
                f"├ Avg: ₹{pos.get('avgprice', 0)}\n"
                f"├ LTP: ₹{pos.get('ltp', 0)}\n"
                f"└ P&L: ₹{pnl:,.2f}\n\n"
            )

        total_emoji = "🟢" if total_pnl > 0 else "🔴" if total_pnl < 0 else "⚪"
        message += f"\n{total_emoji} *Total P&L: ₹{total_pnl:,.2f}*"

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
            pnl = float(holding.get('pnl', 0))
            pnl_percent = float(holding.get('pnlpercent', 0))
            pnl_emoji = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "⚪"

            message += (
                f"{pnl_emoji} *{holding.get('symbol', 'N/A')}* ({holding.get('exchange', 'N/A')})\n"
                f"├ Qty: {holding.get('quantity', 0)}\n"
                f"├ Avg: ₹{holding.get('avgprice', 0)}\n"
                f"├ LTP: ₹{holding.get('ltp', 0)}\n"
                f"└ P&L: ₹{pnl:,.2f} ({pnl_percent:+.2f}%)\n\n"
            )

        if len(holdings) > 10:
            message += f"_... and {len(holdings) - 10} more holdings_\n\n"

        # Add statistics
        if statistics:
            total_value = float(statistics.get('total_value', 0))
            total_pnl = float(statistics.get('total_pnl', 0))
            total_investment = float(statistics.get('total_investment', 0))

            stats_emoji = "🟢" if total_pnl > 0 else "🔴" if total_pnl < 0 else "⚪"

            message += (
                f"📊 *Portfolio Summary*\n"
                f"├ Total Value: ₹{total_value:,.2f}\n"
                f"├ Investment: ₹{total_investment:,.2f}\n"
                f"└ {stats_emoji} P&L: ₹{total_pnl:,.2f}"
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

        available = float(funds.get('availablecash', 0))
        collateral = float(funds.get('collateral', 0))
        utilized = float(funds.get('utiliseddebits', 0))

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

        realized_pnl = float(funds.get('m2mrealized', 0))
        unrealized_pnl = float(funds.get('m2munrealized', 0))
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
        response = await loop.run_in_executor(None, client.quotes, symbol, exchange)

        if not response or response.get('status') != 'success':
            await update.message.reply_text(f"❌ Failed to fetch quote for {symbol}")
            return

        quote = response.get('data', {})

        ltp = float(quote.get('ltp', 0))
        prev_close = float(quote.get('prev_close', ltp))
        change = ltp - prev_close
        change_pct = (change / prev_close * 100) if prev_close > 0 else 0

        change_emoji = "🟢" if change > 0 else "🔴" if change < 0 else "⚪"

        message = (
            f"📊 *{symbol}*\n"
            "━━━━━━━━━━━━━━━\n\n"
            f"{change_emoji} Price: ₹{ltp:,.2f}\n"
            f"├ Change: ₹{change:+.2f} ({change_pct:+.2f}%)\n"
            f"├ Open: ₹{quote.get('open', 0):,.2f}\n"
            f"├ High: ₹{quote.get('high', 0):,.2f}\n"
            f"├ Low: ₹{quote.get('low', 0):,.2f}\n"
            f"├ Prev Close: ₹{prev_close:,.2f}\n"
            f"└ Volume: {quote.get('volume', 0):,}"
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
                "Example: /chart RELIANCE\n"
                "Example: /chart RELIANCE NSE intraday 15m 10\n"
                "Example: /chart NIFTY NSE_INDEX daily D 100",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        # Parse arguments with defaults
        symbol = context.args[0].upper()
        exchange = context.args[1].upper() if len(context.args) > 1 else 'NSE'
        chart_type = context.args[2].lower() if len(context.args) > 2 else 'both'
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
                            caption=f"{symbol} - Daily Chart ({daily_days} days) with Moving Averages"
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


# Create global instance
telegram_bot_service = TelegramBotService()