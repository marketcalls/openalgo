from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import importlib.util
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from utils.runtime import is_monkey_patched as _is_monkey_patched
from utils.runtime import original as _original_module
from utils.runtime import worker_class as _worker_class

# The original threading module, the one utils.real_threading is built on:
# the bot and the Kaleido renderer need real OS threads, because asyncio
# cannot run on a green one. Chosen by whether eventlet patched this process,
# never by whether it was imported. The bot's own lifecycle primitives come
# from utils.real_threading; this name is kept for the renderer and for the
# code and tests that read it.
original_threading = _original_module("threading")

import base64
import io
import json
from datetime import datetime, timedelta

import httpx

from database.auth_db import get_broker_name, get_username_by_apikey

# Database imports
from database.telegram_db import (
    create_or_update_telegram_user,
    delete_telegram_user,
    get_all_telegram_users,
    get_bot_config,
    get_command_stats,
    get_telegram_user,
    get_user_credentials,
    log_command,
    update_bot_config,
)
from utils import real_threading
from utils.constants import CRYPTO_BROKERS
from utils.logging import get_logger

logger = get_logger(__name__)


@functools.cache
def _eventlet_installed() -> bool:
    """Return True when eventlet can be imported. Never imports it."""
    try:
        return importlib.util.find_spec("eventlet") is not None
    except (ImportError, ValueError):
        return False


#: Seconds a start waits for the bot to begin polling before it answers.
BOT_START_WAIT_SECONDS = 5.0

#: Seconds a stop waits for the bot thread to finish.
BOT_STOP_JOIN_SECONDS = 10.0

#: What a start or stop is told while another one is still in progress.
BOT_BUSY_MESSAGE = "The bot is still starting or stopping. Check its status in a few seconds."

#: Seconds the bot waits for a strategy stop (or listing) run on the web
#: server's own loop under eventlet. A stop waits for the strategy process to
#: exit, which takes up to about ten seconds.
STRATEGY_CALL_TIMEOUT_SECONDS = 60.0

#: Seconds between reconnect attempts' stop checks while backing off.
_BACKOFF_STEP_SECONDS = 1.0


def use_sync_initialization() -> bool:
    """Return True where the eventlet-era start path would have been taken.

    Token validation no longer depends on this: :meth:`TelegramBotService.
    initialize_bot_sync` and :meth:`TelegramBotService.initialize_bot` both
    validate with one bounded ``getMe`` request and never stop a running bot,
    in every runtime. The answer is kept, unchanged, for ``app.py``'s auto
    start, which still branches on it, and for the tests that pin it:

    * the eventlet worker: True;
    * the development server: True when eventlet is installed in its
      environment, as every install.sh server's is (answered by whether it is
      installed, never by import order), else False;
    * the gthread worker: False.

    Returns:
        True for the branch the eventlet worker took, False for the other.
    """
    if _is_monkey_patched():
        return True
    if _worker_class() != "dev":
        return False
    return _eventlet_installed()


def _running_python_strategies() -> list[tuple[str, str]]:
    """The running Python strategies as ``(id, display name)``, oldest first.

    Uses ``blueprints.python_strategy.snapshot_running_strategies`` when the
    strategy host provides it, which reads the table under its own lock, and
    otherwise copies the table's keys, one atomic read under the GIL. Called
    through :meth:`TelegramBotService._in_app_world`, so under eventlet it runs
    on the hub, where that lock belongs.
    """
    from blueprints import python_strategy

    snapshot = getattr(python_strategy, "snapshot_running_strategies", None)
    if callable(snapshot):
        return [(str(sid), str(name)) for sid, name in snapshot()]
    configs = python_strategy.STRATEGY_CONFIGS
    return [
        (sid, configs.get(sid, {}).get("name", sid))
        for sid in list(python_strategy.RUNNING_STRATEGIES.keys())
    ]


def _stop_python_strategy(strategy_id: str) -> tuple[bool, str]:
    """Stop one Python strategy. Runs on the hub under eventlet (see above)."""
    from blueprints.python_strategy import stop_strategy_process

    return stop_strategy_process(strategy_id)


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

        # One bot at a time. Each start is a generation with its own stop
        # Event, and a thread writes the shared fields (is_running, bot_loop,
        # is_active in the database) only while its generation is the current
        # one, so a thread that outlives its stop cannot overwrite a newer
        # bot's state. The lock is real because the bot thread is real in
        # every runtime and request code takes it too; nothing is done under
        # it but reading and assigning these fields.
        self._lifecycle_lock = real_threading.Lock()
        self._gen = 0
        self._gen_stop = real_threading.Event()

    @property
    def _stop_event(self):
        """The current generation's stop signal, set to ask the bot to stop."""
        return self._gen_stop

    def _is_current(self, gen: int | None) -> bool:
        """True while ``gen`` is the latest bot generation (None means current)."""
        return gen is None or gen == self._gen

    def _get_sdk_client(self, telegram_id: int) -> openalgo_api | None:
        """Get or create OpenAlgo SDK client for a user"""
        from openalgo import api as openalgo_api

        try:
            # Check if client already exists
            if telegram_id in self.sdk_clients:
                return self.sdk_clients[telegram_id]

            # Get user credentials
            credentials = get_user_credentials(telegram_id)
            if not credentials or not credentials.get("api_key"):
                logger.error(f"No valid credentials for telegram_id: {telegram_id}")
                return None

            host_url = credentials["host_url"].rstrip("/")
            api_key = credentials["api_key"]

            # Create SDK client
            client = openalgo_api(api_key=api_key, host=host_url)

            # Cache the client
            self.sdk_clients[telegram_id] = client

            return client

        except Exception as e:
            logger.exception(f"Error creating SDK client: {e}")
            return None

    def _cs(self, telegram_user: dict) -> str:
        """Return the currency symbol for the user's broker ($ for crypto brokers, ₹ for others)."""
        return "$" if telegram_user.get("broker") in CRYPTO_BROKERS else "₹"

    async def _make_sdk_call(self, telegram_id: int, method: str, **kwargs) -> dict | None:
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
            logger.exception(f"Error making SDK call: {e}")
            return None

    def _render_plotly_png(self, fig) -> bytes:
        """Render a Plotly figure to PNG bytes using Kaleido on a real OS thread.

        Kaleido 1.x's fig.to_image() internally calls asyncio.run(), which
        raises RuntimeError when invoked from a thread that already has a
        running event loop — which is exactly our situation inside a PTB
        command handler (self.bot_loop is a live asyncio loop on self.bot_thread).

        Dispatching via asyncio's run_in_executor does NOT escape this under
        gunicorn + eventlet: the default ThreadPoolExecutor spawns workers
        through threading.Thread, which is monkey-patched by eventlet into
        greenlets that still share the PTB loop's context. So Kaleido's
        asyncio.run() still sees a running loop and still blows up.

        The reliable escape hatch — the same one the bot itself uses to
        isolate from eventlet — is original_threading.Thread, the real,
        unpatched OS-level threading module. A brand-new OS thread has no
        event loop of its own, so asyncio.run() inside Kaleido gets a clean
        slate and can spawn Chromium (installed in the Docker image).

        The caller blocks on t.join() for the duration of the render
        (~1-3 s per chart). This briefly pauses the PTB event loop, which
        is acceptable for personal / low-volume bot usage.
        """
        import queue as _queue

        result_q: "_queue.Queue[tuple[str, object]]" = _queue.Queue()

        def _worker() -> None:
            try:
                png = fig.to_image(format="png", engine="kaleido")
                result_q.put(("ok", png))
            except BaseException as exc:  # noqa: BLE001 - propagate across thread
                result_q.put(("err", exc))

        t = original_threading.Thread(target=_worker, daemon=True, name="openalgo-kaleido-render")
        t.start()
        t.join()

        status, payload = result_q.get_nowait()
        if status == "err":
            raise payload  # type: ignore[misc]
        return payload  # type: ignore[return-value]

    async def _generate_intraday_chart(
        self, symbol: str, exchange: str, interval: str, days: int, telegram_id: int
    ) -> bytes | None:
        """Generate intraday chart with specified interval"""
        import pandas as pd
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots

        try:
            client = self._get_sdk_client(telegram_id)
            if not client:
                logger.error("No SDK client available")
                return None

            # Calculate dates
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)

            logger.debug(
                f"Generating intraday chart for {symbol} on {exchange} with interval {interval}"
            )

            # Get historical data - be robust about event loops
            history_data = None

            # Try async first if we have a loop
            if hasattr(self, "bot_loop") and self.bot_loop:
                try:
                    logger.debug("Using bot's event loop for intraday history")
                    history_data = await self.bot_loop.run_in_executor(
                        None,
                        lambda: client.history(
                            symbol=symbol,
                            exchange=exchange,
                            interval=interval,
                            start_date=start_date.strftime("%Y-%m-%d"),
                            end_date=end_date.strftime("%Y-%m-%d"),
                        ),
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
                        end_date=end_date.strftime("%Y-%m-%d"),
                    )
                except Exception as e:
                    logger.exception(f"Synchronous history fetch failed: {e}")
                    return None

            # Check if we got data
            if history_data is None or (
                isinstance(history_data, pd.DataFrame) and history_data.empty
            ):
                logger.error("No data available for chart generation")
                return None

            # The API returns a DataFrame directly with timestamp as index
            df = (
                history_data
                if isinstance(history_data, pd.DataFrame)
                else pd.DataFrame(history_data)
            )

            # Reset index to get timestamp as a column
            df = df.reset_index()
            # After reset_index(), the index becomes a column named 'index'
            # Rename it to 'timestamp' for clarity
            if "index" in df.columns:
                df.rename(columns={"index": "timestamp"}, inplace=True)

            # Create candlestick chart with volume
            fig = make_subplots(
                rows=2,
                cols=1,
                shared_xaxes=True,
                vertical_spacing=0.03,
                subplot_titles=(f"{symbol} - {days} Day Intraday ({interval})", None),
                row_heights=[0.7, 0.3],
            )

            # Add candlestick chart (following sample code exactly)
            fig.add_trace(
                go.Candlestick(
                    x=df["timestamp"],  # x-axis as timestamp
                    open=df["open"],
                    high=df["high"],
                    low=df["low"],
                    close=df["close"],
                    name="Price",
                    increasing_line_color="green",
                    decreasing_line_color="red",
                ),
                row=1,
                col=1,
            )

            # Add volume bar chart
            colors = [
                "red" if close < open else "green" for close, open in zip(df["close"], df["open"])
            ]

            fig.add_trace(
                go.Bar(
                    x=df["timestamp"],  # x-axis as timestamp
                    y=df["volume"],
                    marker_color=colors,
                    name="Volume",
                    showlegend=False,
                ),
                row=2,
                col=1,
            )

            # Update layout - simplified like the sample code
            fig.update_layout(
                xaxis_rangeslider_visible=False,
                height=600,
                template="plotly_white",
                showlegend=False,
                hovermode="x unified",
            )

            # Apply category type to both x-axes to avoid gaps
            # Reduce tick density - show only every Nth tick
            tick_spacing = max(1, len(df) // 8)  # Show approximately 8 ticks
            # Format timestamps as "22 SEP 09:15"
            tick_labels = []
            for i in range(0, len(df), tick_spacing):
                if pd.notna(df["timestamp"].iloc[i]):
                    ts = pd.to_datetime(df["timestamp"].iloc[i])
                    tick_labels.append(ts.strftime("%d %b %H:%M").upper())
                else:
                    tick_labels.append("")

            fig.update_xaxes(
                type="category",
                row=2,
                col=1,  # Apply to bottom subplot
                tickmode="array",
                tickvals=list(range(0, len(df), tick_spacing)),
                ticktext=tick_labels,
                tickangle=45,
            )
            # Hide ticks on top subplot
            fig.update_xaxes(
                type="category",
                row=1,
                col=1,  # Apply to top subplot
                showticklabels=False,
            )

            # Clean up axes
            fig.update_yaxes(title_text="")

            # Convert to image bytes via a real OS thread — see
            # self._render_plotly_png for why asyncio.run_in_executor is
            # not usable here under gunicorn + eventlet + PTB.
            img_bytes = self._render_plotly_png(fig)
            return img_bytes

        except Exception as e:
            logger.exception(f"Error generating intraday chart: {e}")
            return None

    async def _generate_daily_chart(
        self, symbol: str, exchange: str, interval: str, days: int, telegram_id: int
    ) -> bytes | None:
        """Generate daily chart with specified days"""
        import pandas as pd
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots

        try:
            client = self._get_sdk_client(telegram_id)
            if not client:
                logger.error("No SDK client available")
                return None

            # Calculate dates
            end_date = datetime.now()
            # For daily charts, add extra days to ensure we get enough trading days
            start_date = end_date - timedelta(days=int(days * 1.5))

            logger.debug(
                f"Generating daily chart for {symbol} on {exchange} with interval {interval}"
            )

            # Get historical data - be robust about event loops
            history_data = None

            # Try async first if we have a loop
            if hasattr(self, "bot_loop") and self.bot_loop:
                try:
                    logger.debug("Using bot's event loop for daily history")
                    history_data = await self.bot_loop.run_in_executor(
                        None,
                        lambda: client.history(
                            symbol=symbol,
                            exchange=exchange,
                            interval=interval,
                            start_date=start_date.strftime("%Y-%m-%d"),
                            end_date=end_date.strftime("%Y-%m-%d"),
                        ),
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
                        end_date=end_date.strftime("%Y-%m-%d"),
                    )
                except Exception as e:
                    logger.exception(f"Synchronous daily history fetch failed: {e}")
                    return None

            # Check if we got data
            if history_data is None or (
                isinstance(history_data, pd.DataFrame) and history_data.empty
            ):
                logger.error("No data available for chart generation")
                return None

            # The API returns a DataFrame directly with timestamp as index
            df = (
                history_data
                if isinstance(history_data, pd.DataFrame)
                else pd.DataFrame(history_data)
            )

            # Reset index to get timestamp as a column
            df = df.reset_index()
            # After reset_index(), the index becomes a column named 'index'
            # Rename it to 'timestamp' for clarity
            if "index" in df.columns:
                df.rename(columns={"index": "timestamp"}, inplace=True)

            # Keep last N trading days
            df = df.tail(days)

            # Create candlestick chart with volume
            fig = make_subplots(
                rows=2,
                cols=1,
                shared_xaxes=True,
                vertical_spacing=0.03,
                subplot_titles=(f"{symbol} - Daily Chart ({days} Days)", None),
                row_heights=[0.7, 0.3],
            )

            # Add candlestick chart (following sample code exactly)
            fig.add_trace(
                go.Candlestick(
                    x=df["timestamp"],  # x-axis as timestamp
                    open=df["open"],
                    high=df["high"],
                    low=df["low"],
                    close=df["close"],
                    name="Price",
                    increasing_line_color="green",
                    decreasing_line_color="red",
                ),
                row=1,
                col=1,
            )

            # Add volume bar chart
            colors = [
                "red" if close < open else "green" for close, open in zip(df["close"], df["open"])
            ]

            fig.add_trace(
                go.Bar(
                    x=df["timestamp"],  # x-axis as timestamp
                    y=df["volume"],
                    marker_color=colors,
                    name="Volume",
                    showlegend=False,
                ),
                row=2,
                col=1,
            )

            # Update layout - simplified like the sample code
            fig.update_layout(
                xaxis_rangeslider_visible=False,
                height=600,
                template="plotly_white",
                showlegend=False,
                hovermode="x unified",
            )

            # Apply category type to both x-axes to avoid gaps
            # Reduce tick density for daily charts - show only every Nth tick
            tick_spacing = max(1, len(df) // 10)  # Show approximately 10 ticks for daily
            # Format dates for display as "22 SEP"
            tick_labels = []
            for i in range(0, len(df), tick_spacing):
                if pd.notna(df["timestamp"].iloc[i]):
                    ts = pd.to_datetime(df["timestamp"].iloc[i])
                    tick_labels.append(ts.strftime("%d %b").upper())
                else:
                    tick_labels.append("")

            fig.update_xaxes(
                type="category",
                row=2,
                col=1,  # Apply to bottom subplot
                tickmode="array",
                tickvals=list(range(0, len(df), tick_spacing)),
                ticktext=tick_labels,
                tickangle=45,
            )
            # Hide ticks on top subplot
            fig.update_xaxes(
                type="category",
                row=1,
                col=1,  # Apply to top subplot
                showticklabels=False,
            )

            # Clean up axes
            fig.update_yaxes(title_text="")

            # Convert to image bytes via a real OS thread — see
            # self._render_plotly_png for why asyncio.run_in_executor is
            # not usable here under gunicorn + eventlet + PTB.
            img_bytes = self._render_plotly_png(fig)
            return img_bytes

        except Exception as e:
            logger.exception(f"Error generating daily chart: {e}")
            return None

    async def initialize_bot(self, token: str) -> tuple[bool, str]:
        """Validate and store the bot token, for a caller running an event loop.

        Validates exactly as :meth:`initialize_bot_sync` does, which it calls:
        one bounded ``getMe`` request, blocking this coroutine's loop for at
        most its timeout. The only caller is a start path that builds a
        throwaway loop for this one call.

        It used to stop a running bot first, through ``await
        self.stop_bot()``. ``stop_bot`` is synchronous, so that stopped the bot
        and then failed on awaiting the tuple it returned, answering a Start
        pressed on a running bot with a Python error and no bot. Validating a
        token has no reason to touch the bot that is running.

        Args:
            token: The bot token from BotFather.

        Returns:
            ``(success, message)``, as :meth:`initialize_bot_sync`.
        """
        return self.initialize_bot_sync(token)

    def initialize_bot_sync(self, token: str) -> tuple[bool, str]:
        """Validate the bot token with Telegram and store it.

        The one start path in every runtime: a single ``getMe`` request on the
        shared HTTP client, bounded at ten seconds, which is what the eventlet
        worker has always used. No asyncio loop is created or set on the
        calling thread, which under the gthread worker is a pooled request
        thread that serves every later request too. A running bot is left
        running.

        A token Telegram rejects is refused. When Telegram cannot be reached
        the token is stored anyway, and the bot retries on start.

        Args:
            token: The bot token from BotFather.

        Returns:
            ``(success, message)``, the message written for the trader.
        """
        from utils.httpx_client import get_httpx_client

        try:
            response = get_httpx_client().get(
                f"https://api.telegram.org/bot{token}/getMe", timeout=10
            )
        except Exception as e:
            logger.exception(f"Telegram token check could not reach Telegram: {e}")
            # Store token anyway for retry later
            self.bot_token = token
            return True, "Token stored (will validate on start)"

        try:
            data = response.json() if response.status_code == 200 else {}
        except ValueError:
            data = {}
        if response.status_code == 200 and data.get("ok"):
            bot_info = data.get("result", {}) or {}
            bot_username = bot_info.get("username", "unknown")
            self.bot_token = token
            # Persist the token and username only. is_active is owned by
            # start_bot/stop_bot: writing False here would flip the flag off on
            # the auto-start path (app.py) purely to have start_bot set it back
            # a moment later, and a crash in that window would leave the bot
            # disabled on the next boot.
            update_bot_config({"bot_token": token, "bot_username": bot_username})
            logger.info(f"Bot validated: @{bot_username}")
            return True, f"Bot initialized successfully: @{bot_username}"

        logger.warning(
            f"Telegram refused the bot token check (HTTP {response.status_code}: "
            f"{data.get('description', '') if isinstance(data, dict) else ''})"
        )
        if response.status_code in (401, 404):
            return (
                False,
                "Telegram did not accept this bot token. Copy it again from BotFather and save it.",
            )
        return (
            False,
            "Telegram did not confirm the bot token. Try again in a few minutes, and "
            "if it keeps failing, copy the token again from BotFather.",
        )

    def _run_bot_in_thread(self, gen: int | None = None, stop=None):
        """Run one bot generation on this real thread, with its own event loop.

        Args:
            gen: The generation this thread belongs to. Shared state is written
                only while it is still the current one. None means whichever
                generation is current.
            stop: This generation's stop Event, the current one when None.
        """
        if stop is None:
            stop = self._gen_stop
        logger.debug("Creating new event loop in bot thread")

        # A new event loop for this thread. No process-wide event loop policy
        # is set: that replaced the policy for every thread in the process to
        # reach the same default this call already gets.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        with self._lifecycle_lock:
            if self._is_current(gen):
                self.bot_loop = loop  # Store the loop so we can schedule tasks in it

        http_client = None
        try:
            # Create HTTP client in this thread's event loop
            http_client = httpx.AsyncClient(timeout=30.0)
            self.http_client = http_client

            # Run the bot
            loop.run_until_complete(self._start_bot_isolated(gen, stop))
        except Exception as e:
            logger.exception(f"Bot thread error: {e}")
        finally:
            # Cleanup
            try:
                if http_client is not None:
                    loop.run_until_complete(http_client.aclose())
            except Exception:
                pass
            loop.close()
            with self._lifecycle_lock:
                if self._is_current(gen):
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
        if update and hasattr(update, "effective_chat"):
            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="An error occurred. Please try again later.",
                )
            except Exception:
                pass  # If we can't send the message, just ignore

    async def _sleep_unless_stopped(self, stop, seconds: float) -> bool:
        """Sleep on the bot's loop in short steps, returning True once stopped.

        The reconnect backoff reaches 80 seconds, and a stop that waited for it
        outlived stop_bot's join, so the next start raced a thread that then
        went back to polling.
        """
        deadline = asyncio.get_running_loop().time() + seconds
        while not stop.is_set():
            left = deadline - asyncio.get_running_loop().time()
            if left <= 0:
                return False
            await asyncio.sleep(min(_BACKOFF_STEP_SECONDS, left))
        return True

    def _publish_running(self, gen: int | None, stop) -> bool:
        """Mark this generation as polling, unless it was stopped or replaced."""
        with self._lifecycle_lock:
            if not self._is_current(gen) or stop.is_set():
                return False
            self.is_running = True
        update_bot_config({"is_active": True})
        return True

    def _clear_running(self, gen: int | None) -> None:
        """Mark this generation as not polling, if it is still the current one."""
        with self._lifecycle_lock:
            if self._is_current(gen):
                self.is_running = False

    async def _start_bot_isolated(self, gen: int | None = None, stop=None):
        """Start the bot with proper handlers and network error handling"""
        import telegram.error
        from telegram import Update
        from telegram.ext import (
            Application,
            CallbackQueryHandler,
            CommandHandler,
        )

        if stop is None:
            stop = self._gen_stop

        retry_count = 0
        max_retries = 5
        base_delay = 5  # seconds

        while retry_count < max_retries and not stop.is_set():
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
                self.application.add_handler(CommandHandler("closeall", self.cmd_closeall))
                self.application.add_handler(CommandHandler("stoppython", self.cmd_stoppython))
                self.application.add_handler(CommandHandler("mode", self.cmd_mode))
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
                    allowed_updates=Update.ALL_TYPES,
                )

                if self._publish_running(gen, stop):
                    logger.debug("Telegram bot started successfully and is polling for updates")

                # Reset retry count on successful connection
                retry_count = 0

                # Keep running until stop signal
                while not stop.is_set():
                    await asyncio.sleep(1)

                # Stop signal received - clean shutdown
                logger.debug("Stop signal received, shutting down bot...")
                self._clear_running(gen)

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

            except (
                httpx.ConnectError,
                httpx.NetworkError,
                httpx.TimeoutException,
                telegram.error.NetworkError,
            ) as e:
                retry_count += 1
                delay = base_delay * (2**retry_count)  # Exponential backoff
                logger.warning(
                    f"Network error while connecting to Telegram (attempt {retry_count}/{max_retries}): {type(e).__name__}"
                )
                logger.debug(f"Network error details: {str(e)}")

                if retry_count < max_retries:
                    logger.info(f"Retrying in {delay} seconds...")
                    if await self._sleep_unless_stopped(stop, delay):
                        self._clear_running(gen)
                        break
                else:
                    logger.error("Max retries reached. Unable to connect to Telegram servers.")
                    logger.info(
                        "This might be due to: 1) No internet connection, 2) Telegram blocked by firewall/ISP, 3) DNS issues"
                    )
                    self._clear_running(gen)
                    break

            except Exception as e:
                # For non-network errors, log and stop
                logger.exception(f"Unexpected error in bot operation: {e}")
                self._clear_running(gen)
                break

        # Cleanup after the retry loop
        if (
            self.application
            and hasattr(self.application, "updater")
            and self.application.updater.running
        ):
            try:
                await self.application.updater.stop()
            except Exception as e:
                logger.debug(f"Error stopping updater: {e}")

    def _busy_answer(self) -> tuple[bool, str] | None:
        """The refusal for a start while a bot thread is alive, else None.

        Call with ``_lifecycle_lock`` held.
        """
        if not self._bot_thread_alive():
            return None
        if self.is_running:
            return False, "Bot is already running"
        return False, BOT_BUSY_MESSAGE

    def _bot_thread_alive(self) -> bool:
        """True while the registered bot thread runs, or is about to.

        A thread is registered under the lock and started just after it is
        released, and until then ``is_alive()`` is False, so a registered
        thread with no ident yet counts as alive: without that, every start
        racing into that gap spawned a poller of its own.
        """
        thread = self.bot_thread
        return thread is not None and (thread.ident is None or thread.is_alive())

    def start_bot(self) -> tuple[bool, str]:
        """Start the bot on a real thread, unless one is already alive.

        Single flight. A bot thread that is alive, whether polling, still
        connecting, backing off a network error or finishing a stop, refuses a
        second start, because two pollers on one token get 409 Conflict from
        Telegram and the bot stops answering, /closeall included. The check
        and the new thread's registration happen in one hold of the lifecycle
        lock; the configuration read happens before it.

        Returns:
            ``(success, message)``.
        """
        try:
            with self._lifecycle_lock:
                busy = self._busy_answer()
            if busy is not None:
                return busy

            config = get_bot_config()
            if not config or not config.get("bot_token"):
                return False, "Bot token not configured"

            with self._lifecycle_lock:
                busy = self._busy_answer()
                if busy is not None:
                    return busy
                self._gen += 1
                gen = self._gen
                stop = real_threading.Event()
                self._gen_stop = stop
                self.bot_token = config["bot_token"]
                self.is_running = False
                # Start bot in separate thread with isolated event loop
                thread = real_threading.Thread(
                    target=self._run_bot_in_thread,
                    args=(gen, stop),
                    daemon=True,
                    name="TelegramBotThread",
                )
                self.bot_thread = thread
            try:
                thread.start()
            except BaseException:
                with self._lifecycle_lock:
                    if self.bot_thread is thread:
                        self.bot_thread = None
                raise

            # Wait for bot to start. time.sleep is eventlet's cooperative one
            # under that worker, so the wait never holds up another request.
            deadline = time.monotonic() + BOT_START_WAIT_SECONDS
            while time.monotonic() < deadline:
                if self.is_running:
                    return True, "Bot started successfully"
                if not thread.is_alive():
                    break
                time.sleep(0.5)
            if self.is_running:
                return True, "Bot started successfully"

            return False, "Bot failed to start within timeout"

        except Exception as e:
            logger.exception(f"Failed to start bot: {e}")
            return False, "The bot could not be started. Check the server logs for the cause."

    def stop_bot(self) -> tuple[bool, str]:
        """Stop the bot, including one that is still starting or backing off.

        The stop is sent to the thread that is alive even when it is not yet
        polling: answering "not running" there left a starting bot to come up
        after the trader had asked it to stop. A thread that has not finished
        within the join timeout stays registered, so a start cannot put a
        second poller beside it.

        Returns:
            ``(success, message)``.
        """
        try:
            with self._lifecycle_lock:
                thread = self.bot_thread
                stop = self._gen_stop
                gen = self._gen
                alive = self._bot_thread_alive()
                if not self.is_running and not alive:
                    return False, "Bot is not running"

            logger.debug("Stopping Telegram bot...")

            # Signal the thread to stop
            stop.set()

            # A start registers its thread just before starting it; give it
            # the moment it needs, since a thread cannot be joined before then.
            start_deadline = time.monotonic() + 1.0
            while thread is not None and thread.ident is None:
                if time.monotonic() >= start_deadline:
                    break
                time.sleep(0.01)

            # Wait for thread to finish
            if alive and thread is not None and thread.ident is not None:
                # Cooperative: bot_thread is a real OS thread and stop_bot()
                # is reached from the /telegram stop route, so a blocking
                # join would freeze every other request for up to 10s.
                real_threading.join(thread, timeout=BOT_STOP_JOIN_SECONDS)
                if thread.is_alive():
                    logger.warning("Bot thread did not stop cleanly")

            with self._lifecycle_lock:
                if self._gen == gen:
                    self.is_running = False
                    if thread is None or not thread.is_alive():
                        self.bot_thread = None
                        self.application = None
                        self.bot_loop = None  # Clear the loop reference

            # Update database
            update_bot_config({"is_active": False})

            logger.info("Telegram bot stopped")
            return True, "Bot stopped successfully"

        except Exception as e:
            logger.exception(f"Failed to stop bot: {e}")
            return False, "The bot could not be stopped. Check the server logs for the cause."

    # Alias for compatibility
    stop_bot_sync = stop_bot

    async def _in_app_world(self, fn, *args, timeout: float, offload: bool = True):
        """Call ``fn(*args)`` where the web app's own code runs, from the bot's loop.

        The bot's loop runs on a real OS thread in every runtime. Under the
        eventlet worker the Python strategy host guards its process table
        with a green lock and its status stream with green queues, and a real
        thread that takes either can wedge a request waiting on them for good.
        So under eventlet the call is handed to the hub with
        ``utils.real_threading.submit_to_hub`` and this coroutine polls a real
        Event with ``asyncio.sleep``, which keeps the bot answering meanwhile.
        Everywhere else there is nothing green to reach, and ``fn`` runs as it
        always did: on the loop's executor, or inline when ``offload`` is
        False.

        Args:
            fn: The callable.
            *args: Its positional arguments.
            timeout: Seconds to wait under eventlet before giving up.
            offload: Run on the executor outside eventlet (False runs inline,
                for a cheap read).

        Returns:
            Whatever ``fn`` returned.

        Raises:
            TimeoutError: Under eventlet, when the call did not finish in time.
            Exception: Whatever ``fn`` raised.
        """
        loop = asyncio.get_running_loop()
        if not real_threading.is_monkey_patched():
            if not offload:
                return fn(*args)
            return await loop.run_in_executor(None, functools.partial(fn, *args))

        done = real_threading.Event()
        box: dict[str, Any] = {}

        def task() -> None:
            try:
                box["value"] = fn(*args)
            except BaseException as exc:  # noqa: BLE001 - re-raised on the bot's loop
                box["error"] = exc
            finally:
                done.set()

        real_threading.submit_to_hub(task)
        deadline = loop.time() + timeout
        while not done.is_set():
            if loop.time() >= deadline:
                raise TimeoutError(f"the web app did not finish the call within {timeout}s")
            await asyncio.sleep(0.05)
        if "error" in box:
            raise box["error"]
        return box.get("value")

    # Command Handlers
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command"""
        from telegram.constants import ParseMode

        user = update.effective_user

        # Check if user is already linked
        telegram_user = get_telegram_user(user.id)

        if telegram_user:
            await update.message.reply_text(
                f"Welcome back, {user.first_name}! \n\n"
                "Your account is linked. Use /menu to see available options.",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await update.message.reply_text(
                f"Welcome to OpenAlgo Bot, {user.first_name}! \n\n"
                "To get started, link your OpenAlgo account:\n"
                "`/link <api_key> <host_url>`\n\n"
                "Example:\n"
                "`/link your_api_key_here http://127.0.0.1:5000`\n\n"
                "Use /help to see all available commands.",
                parse_mode=ParseMode.MARKDOWN,
            )

        log_command(user.id, "start", update.effective_chat.id)

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command"""
        from telegram.constants import ParseMode

        help_text = """
*Available Commands:*

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

*Remote Actions:*
/closeall - Close all open positions (with confirmation)
/stoppython - Stop running Python strategies (with confirmation)
/mode - View or toggle trading mode (Live / Analyze)

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
        log_command(update.effective_user.id, "help", update.effective_chat.id)

    async def cmd_link(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /link command"""
        from telegram.constants import ParseMode

        user = update.effective_user
        chat_id = update.effective_chat.id

        if not context.args or len(context.args) != 2:
            await update.message.reply_text(
                "Invalid format\n"
                "Usage: `/link <api_key> <host_url>`\n"
                "Example: `/link your_api_key http://127.0.0.1:5000`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        api_key = context.args[0]
        host_url = context.args[1].rstrip("/")

        # Validate API key by making a test call
        try:
            from openalgo import api as openalgo_api

            # Create temporary SDK client for validation
            test_client = openalgo_api(api_key=api_key, host=host_url)

            # Test with a simple call
            loop = asyncio.get_event_loop()
            test_response = await loop.run_in_executor(None, test_client.funds)

            if test_response and test_response.get("status") == "success":
                # Valid credentials, save them
                # Get the actual OpenAlgo username from the API key
                openalgo_username = None
                try:
                    openalgo_username = get_username_by_apikey(api_key)
                    logger.info(f"API key lookup returned: '{openalgo_username}'")
                except Exception as e:
                    logger.exception(f"Error getting username from API key: {e}")

                # If we couldn't get username from API key, try to extract from response
                if not openalgo_username and test_response.get("data"):
                    # Some brokers return username in the funds response
                    data = test_response.get("data", {})
                    if isinstance(data, dict):
                        openalgo_username = (
                            data.get("username") or data.get("user_id") or data.get("client_id")
                        )
                        if openalgo_username:
                            logger.info(f"Got username from funds response: {openalgo_username}")

                # Log for debugging
                logger.info(
                    f"Linking Telegram user {user.id} (@{user.username}) with OpenAlgo username: '{openalgo_username}'"
                )

                # If we still can't get username, DON'T use telegram username with @
                # Use a proper fallback
                if not openalgo_username:
                    # Try to get from session or use telegram ID
                    openalgo_username = f"user_{user.id}"
                    logger.warning(
                        f"Could not get OpenAlgo username, using fallback: {openalgo_username}"
                    )
                else:
                    logger.info(f"Successfully retrieved OpenAlgo username: {openalgo_username}")

                # Determine broker for currency symbol selection
                broker_name = get_broker_name(api_key) or "default"
                logger.info(f"Detected broker for Telegram user {user.id}: {broker_name}")

                create_or_update_telegram_user(
                    telegram_id=user.id,
                    username=openalgo_username,  # Use the actual OpenAlgo username
                    telegram_username=user.username,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    api_key=api_key,
                    host_url=host_url,
                    broker=broker_name,
                )

                logger.info(f"Database updated - Username stored as: {openalgo_username}")

                await update.message.reply_text(
                    "Account linked successfully!\n"
                    "You can now use all bot features.\n"
                    "Type /menu to see available options.",
                    parse_mode=ParseMode.MARKDOWN,
                )
            else:
                await update.message.reply_text(
                    "Failed to validate API key.\nPlease check your credentials and try again.",
                    parse_mode=ParseMode.MARKDOWN,
                )

        except Exception as e:
            logger.exception(f"Error linking account: {e}")
            await update.message.reply_text(
                f"Failed to link account.\nError: {str(e)}", parse_mode=ParseMode.MARKDOWN
            )

        log_command(user.id, "link", chat_id)

    async def cmd_unlink(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /unlink command"""
        from telegram.constants import ParseMode

        user = update.effective_user

        if delete_telegram_user(user.id):
            # Clear SDK client cache
            if user.id in self.sdk_clients:
                del self.sdk_clients[user.id]

            await update.message.reply_text(
                "Account unlinked successfully.\nYour data has been removed.",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await update.message.reply_text(
                "No linked account found.", parse_mode=ParseMode.MARKDOWN
            )

        log_command(user.id, "unlink", update.effective_chat.id)

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /status command"""
        from telegram.constants import ParseMode

        user = update.effective_user
        telegram_user = get_telegram_user(user.id)

        if telegram_user:
            # Test connection using SDK
            client = self._get_sdk_client(user.id)
            if client:
                try:
                    loop = asyncio.get_event_loop()
                    test_response = await loop.run_in_executor(None, client.funds)

                    if test_response and test_response.get("status") == "success":
                        status = "Connected"
                    else:
                        status = "Connection Failed"
                except Exception:
                    status = "Connection Failed"
            else:
                status = "Client Error"

            # Get display name (prefer telegram_username, fallback to openalgo_username)
            display_name = (
                telegram_user.get("telegram_username")
                or telegram_user.get("openalgo_username")
                or "N/A"
            )
            host_url = telegram_user.get("host_url") or "N/A"

            await update.message.reply_text(
                f"*Account Status*\n"
                f"━━━━━━━━━━━━━━━\n"
                f"User: {display_name}\n"
                f"Status: {status}\n"
                f"Host: {host_url}\n"
                f"Linked: {telegram_user.get('created_at', 'N/A')}",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await update.message.reply_text(
                "No linked account found.\nUse /link to connect your OpenAlgo account.",
                parse_mode=ParseMode.MARKDOWN,
            )

        log_command(user.id, "status", update.effective_chat.id)

    async def cmd_orderbook(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /orderbook command"""
        from telegram.constants import ParseMode

        user = update.effective_user
        telegram_user = get_telegram_user(user.id)

        if not telegram_user:
            await update.message.reply_text("Please link your account first using /link")
            return

        cs = self._cs(telegram_user)

        # Get orderbook using SDK
        client = self._get_sdk_client(user.id)
        if not client:
            await update.message.reply_text("Failed to connect to OpenAlgo")
            return

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, client.orderbook)

        if not response or response.get("status") != "success":
            await update.message.reply_text("Failed to fetch orderbook")
            return

        orders = response.get("data", {}).get("orders", [])
        statistics = response.get("data", {}).get("statistics", {})

        if not orders:
            await update.message.reply_text(
                "*ORDERBOOK*\n━━━━━━━━━━━━━━━\n\nNo open orders", parse_mode=ParseMode.MARKDOWN
            )
            return

        message = "*ORDERBOOK*\n━━━━━━━━━━━━━━━\n\n"

        for order in orders[:10]:  # Limit to 10 orders
            status = order.get("order_status", "unknown")
            status_emoji = (
                "[OK]"
                if status == "complete"
                else "[OPEN]"
                if status == "open"
                else "[REJECTED]"
                if status == "rejected"
                else "[OTHER]"
            )
            action_emoji = "[BUY]" if order.get("action") == "BUY" else "[SELL]"

            # Handle price and quantity (might be strings from some brokers)
            try:
                price = float(order.get("price", 0))
                price_str = (
                    "Market"
                    if price == 0 and order.get("pricetype") == "MARKET"
                    else f"{cs}{price}"
                )
            except (ValueError, TypeError):
                price_str = f"{cs}{order.get('price', 0)}"

            try:
                quantity = int(order.get("quantity", 0))
            except (ValueError, TypeError):
                quantity = order.get("quantity", 0)

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
                trigger_price = float(order.get("trigger_price", 0))
                if trigger_price > 0:
                    message += f"├ Trigger: {cs}{trigger_price}\n"
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
                total_open = int(statistics.get("total_open_orders", 0))
            except (ValueError, TypeError):
                total_open = 0

            try:
                total_completed = int(statistics.get("total_completed_orders", 0))
            except (ValueError, TypeError):
                total_completed = 0

            try:
                total_rejected = int(statistics.get("total_rejected_orders", 0))
            except (ValueError, TypeError):
                total_rejected = 0

            try:
                total_buy = int(statistics.get("total_buy_orders", 0))
            except (ValueError, TypeError):
                total_buy = 0

            try:
                total_sell = int(statistics.get("total_sell_orders", 0))
            except (ValueError, TypeError):
                total_sell = 0

            message += (
                "*Summary*\n"
                f"├ Total Orders: {len(orders)}\n"
                f"├ Open: {total_open}\n"
                f"├ Completed: {total_completed}\n"
                f"├ Rejected: {total_rejected}\n"
                f"├ Buy Orders: {total_buy}\n"
                f"└ Sell Orders: {total_sell}"
            )

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
        log_command(user.id, "orderbook", update.effective_chat.id)

    async def cmd_tradebook(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /tradebook command"""
        from telegram.constants import ParseMode

        user = update.effective_user
        telegram_user = get_telegram_user(user.id)

        if not telegram_user:
            await update.message.reply_text("Please link your account first using /link")
            return

        cs = self._cs(telegram_user)

        # Get tradebook using SDK
        client = self._get_sdk_client(user.id)
        if not client:
            await update.message.reply_text("Failed to connect to OpenAlgo")
            return

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, client.tradebook)

        if not response or response.get("status") != "success":
            await update.message.reply_text("Failed to fetch tradebook")
            return

        trades = response.get("data", [])

        if not trades:
            await update.message.reply_text(
                "*TRADEBOOK*\n━━━━━━━━━━━━━━━\n\nNo trades executed today",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        message = "*TRADEBOOK*\n━━━━━━━━━━━━━━━\n\n"
        total_buy_value = 0
        total_sell_value = 0

        for trade in trades[:10]:  # Limit to 10 trades
            action_emoji = "[BUY]" if trade.get("action") == "BUY" else "[SELL]"

            # Handle trade_value (might be string from some brokers)
            try:
                trade_value = float(trade.get("trade_value", 0))
            except (ValueError, TypeError):
                trade_value = 0.0

            if trade.get("action") == "BUY":
                total_buy_value += trade_value
            else:
                total_sell_value += trade_value

            # Handle quantity and average_price formatting
            try:
                quantity = int(trade.get("quantity", 0))
            except (ValueError, TypeError):
                quantity = trade.get("quantity", 0)

            try:
                avg_price = float(trade.get("average_price", 0))
                avg_price_str = f"{cs}{avg_price:,.2f}"
            except (ValueError, TypeError):
                avg_price_str = f"{cs}{trade.get('average_price', 0)}"

            message += (
                f"{action_emoji} *{trade.get('symbol', 'N/A')}* ({trade.get('exchange', 'N/A')})\n"
                f"├ {trade.get('action', 'N/A')} {quantity} @ {avg_price_str}\n"
                f"├ Product: {trade.get('product', 'N/A')}\n"
                f"├ Value: {cs}{trade_value:,.2f}\n"
                f"├ Time: {trade.get('timestamp', 'N/A')}\n"
                f"└ Order ID: `{trade.get('orderid', 'N/A')}`\n\n"
            )

        if len(trades) > 10:
            message += f"_... and {len(trades) - 10} more trades_\n\n"

        # Add summary
        message += (
            "*Summary*\n"
            f"├ Total Trades: {len(trades)}\n"
            f"├ Buy Value: {cs}{total_buy_value:,.2f}\n"
            f"└ Sell Value: {cs}{total_sell_value:,.2f}"
        )

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
        log_command(user.id, "tradebook", update.effective_chat.id)

    async def cmd_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /positions command"""
        from telegram.constants import ParseMode

        user = update.effective_user
        telegram_user = get_telegram_user(user.id)

        if not telegram_user:
            await update.message.reply_text("Please link your account first using /link")
            return

        cs = self._cs(telegram_user)

        # Get positions using SDK
        client = self._get_sdk_client(user.id)
        if not client:
            await update.message.reply_text("Failed to connect to OpenAlgo")
            return

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, client.positionbook)

        if not response or response.get("status") != "success":
            await update.message.reply_text("Failed to fetch positions")
            return

        positions = response.get("data", [])

        if not positions:
            await update.message.reply_text(
                "*POSITIONS*\n━━━━━━━━━━━━━━━\n\nNo open positions",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Filter out positions with 0 quantity
        active_positions = [pos for pos in positions if pos.get("quantity", 0) != 0]

        if not active_positions:
            await update.message.reply_text(
                "*POSITIONS*\n━━━━━━━━━━━━━━━\n\nNo active positions",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        message = "*POSITIONS*\n━━━━━━━━━━━━━━━\n\n"
        total_long = 0
        total_short = 0

        for pos in active_positions[:10]:  # Limit to 10 positions
            # Handle quantity and average_price (might be strings from some brokers)
            try:
                quantity = int(pos.get("quantity", 0))
            except (ValueError, TypeError):
                quantity = 0

            try:
                avg_price = float(pos.get("average_price", "0.00") or 0)
            except (ValueError, TypeError):
                avg_price = 0.0

            # Determine position type
            if quantity > 0:
                position_type = "LONG"
                position_emoji = "[LONG]"
                total_long += 1
            else:
                position_type = "SHORT"
                position_emoji = "[SHORT]"
                total_short += 1

            message += (
                f"{position_emoji} *{pos.get('symbol', 'N/A')}* ({pos.get('exchange', 'N/A')})\n"
                f"├ Position: {position_type}\n"
                f"├ Qty: {abs(quantity)} ({pos.get('product', 'N/A')})\n"
            )

            if avg_price > 0:
                message += f"├ Avg Price: {cs}{avg_price:,.2f}\n"

            message += "\n"

        if len(active_positions) > 10:
            message += f"_... and {len(active_positions) - 10} more positions_\n\n"

        # Add summary
        message += (
            "*Summary*\n"
            f"├ Active Positions: {len(active_positions)}\n"
            f"├ Long Positions: {total_long}\n"
            f"└ Short Positions: {total_short}"
        )

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
        log_command(user.id, "positions", update.effective_chat.id)

    async def cmd_holdings(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /holdings command"""
        from telegram.constants import ParseMode

        user = update.effective_user
        telegram_user = get_telegram_user(user.id)

        if not telegram_user:
            await update.message.reply_text("Please link your account first using /link")
            return

        cs = self._cs(telegram_user)

        # Get holdings using SDK
        client = self._get_sdk_client(user.id)
        if not client:
            await update.message.reply_text("Failed to connect to OpenAlgo")
            return

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, client.holdings)

        if not response or response.get("status") != "success":
            await update.message.reply_text("Failed to fetch holdings")
            return

        holdings = response.get("data", {}).get("holdings", [])
        statistics = response.get("data", {}).get("statistics", {})

        if not holdings:
            await update.message.reply_text(
                "*HOLDINGS*\n━━━━━━━━━━━━━━━\n\nNo holdings found", parse_mode=ParseMode.MARKDOWN
            )
            return

        message = "*HOLDINGS*\n━━━━━━━━━━━━━━━\n\n"

        for holding in holdings[:10]:
            # Handle numeric values that might be strings from some brokers
            try:
                pnl = float(holding.get("pnl", 0))
            except (ValueError, TypeError):
                pnl = 0.0

            try:
                pnl_percent = float(holding.get("pnlpercent", 0))
            except (ValueError, TypeError):
                pnl_percent = 0.0

            try:
                quantity = int(holding.get("quantity", 0))
            except (ValueError, TypeError):
                quantity = 0

            pnl_emoji = "[+]" if pnl > 0 else "[-]" if pnl < 0 else "[=]"

            message += (
                f"{pnl_emoji} *{holding.get('symbol', 'N/A')}* ({holding.get('exchange', 'N/A')})\n"
                f"├ Product: {holding.get('product', 'CNC')}\n"
                f"├ Qty: {quantity}\n"
                f"└ P&L: {cs}{pnl:,.2f} ({pnl_percent:+.2f}%)\n\n"
            )

        if len(holdings) > 10:
            message += f"_... and {len(holdings) - 10} more holdings_\n\n"

        # Add statistics
        if statistics:
            # Handle statistics that might be strings from some brokers
            try:
                total_holding_value = float(statistics.get("totalholdingvalue", 0))
            except (ValueError, TypeError):
                total_holding_value = 0.0

            try:
                total_inv_value = float(statistics.get("totalinvvalue", 0))
            except (ValueError, TypeError):
                total_inv_value = 0.0

            try:
                total_pnl = float(statistics.get("totalprofitandloss", 0))
            except (ValueError, TypeError):
                total_pnl = 0.0

            try:
                total_pnl_percent = float(statistics.get("totalpnlpercentage", 0))
            except (ValueError, TypeError):
                total_pnl_percent = 0.0

            stats_emoji = "[+]" if total_pnl > 0 else "[-]" if total_pnl < 0 else "[=]"

            message += (
                f"*Portfolio Summary*\n"
                f"├ Current Value: {cs}{total_holding_value:,.2f}\n"
                f"├ Investment: {cs}{total_inv_value:,.2f}\n"
                f"└ {stats_emoji} P&L: {cs}{total_pnl:,.2f} ({total_pnl_percent:+.2f}%)"
            )

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
        log_command(user.id, "holdings", update.effective_chat.id)

    async def cmd_funds(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /funds command"""
        from telegram.constants import ParseMode

        user = update.effective_user
        telegram_user = get_telegram_user(user.id)

        if not telegram_user:
            await update.message.reply_text("Please link your account first using /link")
            return

        cs = self._cs(telegram_user)

        # Get funds using SDK
        client = self._get_sdk_client(user.id)
        if not client:
            await update.message.reply_text("Failed to connect to OpenAlgo")
            return

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, client.funds)

        if not response or response.get("status") != "success":
            await update.message.reply_text("Failed to fetch funds")
            return

        funds = response.get("data", {})

        # Handle funds that might be strings from some brokers
        try:
            available = float(funds.get("availablecash", 0))
        except (ValueError, TypeError):
            available = 0.0

        try:
            collateral = float(funds.get("collateral", 0))
        except (ValueError, TypeError):
            collateral = 0.0

        try:
            utilized = float(funds.get("utiliseddebits", 0))
        except (ValueError, TypeError):
            utilized = 0.0

        message = (
            "*FUNDS*\n"
            "━━━━━━━━━━━━━━━\n\n"
            f"*Available Cash*\n"
            f"└ {cs}{available:,.2f}\n\n"
            f"*Collateral*\n"
            f"└ {cs}{collateral:,.2f}\n\n"
            f"*Utilized Margin*\n"
            f"└ {cs}{utilized:,.2f}\n\n"
            f"*Total Balance*\n"
            f"└ {cs}{(available + collateral):,.2f}"
        )

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
        log_command(user.id, "funds", update.effective_chat.id)

    async def cmd_pnl(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /pnl command"""
        from telegram.constants import ParseMode

        user = update.effective_user
        telegram_user = get_telegram_user(user.id)

        if not telegram_user:
            await update.message.reply_text("Please link your account first using /link")
            return

        cs = self._cs(telegram_user)

        # Get P&L from funds using SDK
        client = self._get_sdk_client(user.id)
        if not client:
            await update.message.reply_text("Failed to connect to OpenAlgo")
            return

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, client.funds)

        if not response or response.get("status") != "success":
            await update.message.reply_text("Failed to fetch P&L")
            return

        message = self._format_pnl_funds(response, cs=cs)

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
        log_command(user.id, "pnl", update.effective_chat.id)

    async def cmd_quote(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /quote command"""
        from telegram.constants import ParseMode

        user = update.effective_user
        telegram_user = get_telegram_user(user.id)

        if not telegram_user:
            await update.message.reply_text("Please link your account first using /link")
            return

        if not context.args:
            await update.message.reply_text(
                "Usage: /quote <symbol> [exchange]\n"
                "Example: /quote RELIANCE\n"
                "Example: /quote NIFTY NSE_INDEX",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        cs = self._cs(telegram_user)

        symbol = context.args[0].upper()
        exchange = context.args[1].upper() if len(context.args) > 1 else "NSE"

        # Get quote using SDK
        client = self._get_sdk_client(user.id)
        if not client:
            await update.message.reply_text("Failed to connect to OpenAlgo")
            return

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, lambda: client.quotes(symbol=symbol, exchange=exchange)
        )

        if not response or response.get("status") != "success":
            await update.message.reply_text(f"Failed to fetch quote for {symbol}")
            return

        quote = response.get("data", {})

        # Handle quote values that might be strings from some brokers
        try:
            ltp = float(quote.get("ltp", 0))
        except (ValueError, TypeError):
            ltp = 0.0

        try:
            prev_close = float(quote.get("prev_close", ltp))
        except (ValueError, TypeError):
            prev_close = ltp

        change = ltp - prev_close
        change_pct = (change / prev_close * 100) if prev_close > 0 else 0

        change_emoji = "[+]" if change > 0 else "[-]" if change < 0 else "[=]"

        # Handle other quote values
        try:
            open_price = float(quote.get("open", 0))
        except (ValueError, TypeError):
            open_price = 0.0

        try:
            high_price = float(quote.get("high", 0))
        except (ValueError, TypeError):
            high_price = 0.0

        try:
            low_price = float(quote.get("low", 0))
        except (ValueError, TypeError):
            low_price = 0.0

        try:
            volume = int(quote.get("volume", 0))
        except (ValueError, TypeError):
            volume = 0

        message = (
            f"*{symbol}*\n"
            "━━━━━━━━━━━━━━━\n\n"
            f"{change_emoji} Price: {cs}{ltp:,.2f}\n"
            f"├ Change: {cs}{change:+.2f} ({change_pct:+.2f}%)\n"
            f"├ Open: {cs}{open_price:,.2f}\n"
            f"├ High: {cs}{high_price:,.2f}\n"
            f"├ Low: {cs}{low_price:,.2f}\n"
            f"├ Prev Close: {cs}{prev_close:,.2f}\n"
            f"└ Volume: {volume:,}"
        )

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
        log_command(user.id, "quote", update.effective_chat.id)

    async def cmd_chart(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /chart command with customizable parameters"""
        from telegram import InputMediaPhoto
        from telegram.constants import ParseMode

        user = update.effective_user
        telegram_user = get_telegram_user(user.id)

        if not telegram_user:
            await update.message.reply_text("Please link your account first using /link")
            return

        if not context.args:
            await update.message.reply_text(
                "Usage: /chart <symbol> [exchange] [type] [interval] [days]\n"
                "Type: intraday (default), daily, or both\n\n"
                "Examples:\n"
                "/chart RELIANCE - 5m intraday chart\n"
                "/chart RELIANCE NSE intraday 15m 10\n"
                "/chart NIFTY NSE_INDEX daily D 100\n"
                "/chart RELIANCE NSE both - Both charts",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Parse arguments with defaults
        symbol = context.args[0].upper()
        exchange = context.args[1].upper() if len(context.args) > 1 else "NSE"
        chart_type = (
            context.args[2].lower() if len(context.args) > 2 else "intraday"
        )  # Default to intraday only
        interval = context.args[3] if len(context.args) > 3 else None
        days = int(context.args[4]) if len(context.args) > 4 else None

        # Set default intervals and days based on chart type
        if chart_type in ["intraday", "i"]:
            interval = interval or "5m"
            days = days or 5
        elif chart_type in ["daily", "d"]:
            interval = interval or "D"
            days = days or 252
        else:  # both
            pass

        # Send loading message
        loading_msg = await update.message.reply_text("Generating charts... Please wait.")

        try:
            charts_generated = []

            if chart_type in ["both", "intraday", "i"]:
                # Generate intraday chart
                intraday_interval = interval or "5m"
                intraday_days = days or 5
                intraday_chart = await self._generate_intraday_chart(
                    symbol, exchange, intraday_interval, intraday_days, user.id
                )
                if intraday_chart:
                    charts_generated.append(
                        InputMediaPhoto(
                            intraday_chart,
                            caption=f"{symbol} - {intraday_days} Day Intraday Chart ({intraday_interval} intervals)",
                        )
                    )

            if chart_type in ["both", "daily", "d"]:
                # Generate daily chart
                daily_interval = "D" if chart_type == "both" else (interval or "D")
                daily_days = 252 if chart_type == "both" else (days or 252)
                daily_chart = await self._generate_daily_chart(
                    symbol, exchange, daily_interval, daily_days, user.id
                )
                if daily_chart:
                    charts_generated.append(
                        InputMediaPhoto(
                            daily_chart, caption=f"{symbol} - Daily Chart ({daily_days} days)"
                        )
                    )

            # Delete loading message
            await loading_msg.delete()

            if charts_generated:
                if len(charts_generated) > 1:
                    await update.message.reply_media_group(charts_generated)
                else:
                    await update.message.reply_photo(
                        photo=charts_generated[0].media, caption=charts_generated[0].caption
                    )
            else:
                await update.message.reply_text(f"Failed to generate charts for {symbol}")

        except Exception as e:
            logger.exception(f"Error generating charts: {e}")
            try:
                await loading_msg.delete()
            except Exception:
                pass
            await update.message.reply_text(f"Error generating charts: {str(e)}")

        log_command(user.id, "chart", update.effective_chat.id)

    async def cmd_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /menu command"""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from telegram.constants import ParseMode

        user = update.effective_user
        telegram_user = get_telegram_user(user.id)

        if not telegram_user:
            await update.message.reply_text("Please link your account first using /link")
            return

        keyboard = [
            [
                InlineKeyboardButton("Orderbook", callback_data="orderbook"),
                InlineKeyboardButton("Tradebook", callback_data="tradebook"),
            ],
            [
                InlineKeyboardButton("Positions", callback_data="positions"),
                InlineKeyboardButton("Holdings", callback_data="holdings"),
            ],
            [
                InlineKeyboardButton("Funds", callback_data="funds"),
                InlineKeyboardButton("P&L", callback_data="pnl"),
            ],
            [
                InlineKeyboardButton("Refresh", callback_data="menu"),
            ],
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "*OpenAlgo Trading Menu*\nSelect an option below:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN,
        )

        log_command(user.id, "menu", update.effective_chat.id)

    def _format_orderbook(self, response: dict, cs: str = "₹") -> str:
        """Format orderbook response into message"""
        if not response or response.get("status") != "success":
            return "Failed to fetch orderbook"

        orders = response.get("data", {}).get("orders", [])
        if not orders:
            return "*ORDERBOOK*\n━━━━━━━━━━━━━━━\n\nNo open orders"

        message = "*ORDERBOOK*\n━━━━━━━━━━━━━━━\n\n"
        for order in orders[:10]:
            status = order.get("order_status", "unknown")
            status_emoji = (
                "[OK]"
                if status == "complete"
                else "[OPEN]"
                if status == "open"
                else "[REJECTED]"
                if status == "rejected"
                else "[OTHER]"
            )
            action_emoji = "[BUY]" if order.get("action") == "BUY" else "[SELL]"
            try:
                price = float(order.get("price", 0))
                price_str = "Market" if price == 0 else f"{cs}{price}"
            except Exception:
                price_str = f"{cs}{order.get('price', 0)}"
            try:
                quantity = int(order.get("quantity", 0))
            except Exception:
                quantity = order.get("quantity", 0)
            message += (
                f"{status_emoji} *{order.get('symbol', 'N/A')}* ({order.get('exchange', 'N/A')})\n"
            )
            message += f"{action_emoji} {order.get('action', 'N/A')} {quantity} @ {price_str}\n"
            message += f"└ Status: {status.title()}\n\n"
        if len(orders) > 10:
            message += f"_... and {len(orders) - 10} more orders_"
        return message

    def _format_tradebook(self, response: dict, cs: str = "₹") -> str:
        """Format tradebook response into message"""
        if not response or response.get("status") != "success":
            return "Failed to fetch tradebook"

        trades = response.get("data", [])
        if not trades:
            return "*TRADEBOOK*\n━━━━━━━━━━━━━━━\n\nNo trades executed today"

        message = "*TRADEBOOK*\n━━━━━━━━━━━━━━━\n\n"
        for trade in trades[:10]:
            action_emoji = "[BUY]" if trade.get("action") == "BUY" else "[SELL]"
            try:
                quantity = int(trade.get("quantity", 0))
            except Exception:
                quantity = trade.get("quantity", 0)
            try:
                avg_price = float(trade.get("average_price", 0))
                avg_price_str = f"{cs}{avg_price:,.2f}"
            except Exception:
                avg_price_str = f"{cs}{trade.get('average_price', 0)}"
            message += (
                f"{action_emoji} *{trade.get('symbol', 'N/A')}* ({trade.get('exchange', 'N/A')})\n"
            )
            message += f"├ {trade.get('action', 'N/A')} {quantity} @ {avg_price_str}\n"
            message += f"└ Time: {trade.get('timestamp', 'N/A')}\n\n"
        if len(trades) > 10:
            message += f"_... and {len(trades) - 10} more trades_"
        return message

    def _format_positions(self, response: dict, cs: str = "₹") -> str:
        """Format positions response into message"""
        if not response or response.get("status") != "success":
            return "Failed to fetch positions"

        positions = response.get("data", [])
        active_positions = [pos for pos in positions if pos.get("quantity", 0) != 0]
        if not active_positions:
            return "*POSITIONS*\n━━━━━━━━━━━━━━━\n\nNo active positions"

        message = "*POSITIONS*\n━━━━━━━━━━━━━━━\n\n"
        for pos in active_positions[:10]:
            try:
                quantity = int(pos.get("quantity", 0))
            except Exception:
                quantity = 0
            position_emoji = "[LONG]" if quantity > 0 else "[SHORT]"
            position_type = "LONG" if quantity > 0 else "SHORT"
            message += (
                f"{position_emoji} *{pos.get('symbol', 'N/A')}* ({pos.get('exchange', 'N/A')})\n"
            )
            message += f"├ {position_type}\n"
            message += f"└ Qty: {abs(quantity)}\n\n"
        if len(active_positions) > 10:
            message += f"_... and {len(active_positions) - 10} more positions_"
        return message

    def _format_holdings(self, response: dict, cs: str = "₹") -> str:
        """Format holdings response into message"""
        if not response or response.get("status") != "success":
            return "Failed to fetch holdings"

        holdings = response.get("data", {}).get("holdings", [])
        if not holdings:
            return "*HOLDINGS*\n━━━━━━━━━━━━━━━\n\nNo holdings found"

        message = "*HOLDINGS*\n━━━━━━━━━━━━━━━\n\n"
        for holding in holdings[:10]:
            try:
                pnl = float(holding.get("pnl", 0))
                pnl_percent = float(holding.get("pnlpercent", 0))
            except Exception:
                pnl, pnl_percent = 0.0, 0.0
            pnl_emoji = "[+]" if pnl > 0 else "[-]" if pnl < 0 else "[=]"
            message += f"{pnl_emoji} *{holding.get('symbol', 'N/A')}*\n"
            message += f"└ P&L: {cs}{pnl:,.2f} ({pnl_percent:+.2f}%)\n\n"
        if len(holdings) > 10:
            message += f"_... and {len(holdings) - 10} more holdings_"
        return message

    def _format_funds(self, response: dict, cs: str = "₹") -> str:
        """Format funds response into message"""
        if not response or response.get("status") != "success":
            return "Failed to fetch funds"

        funds = response.get("data", {})
        try:
            available = float(funds.get("availablecash", 0))
            collateral = float(funds.get("collateral", 0))
            utilized = float(funds.get("utiliseddebits", 0))
        except Exception:
            available, collateral, utilized = 0.0, 0.0, 0.0

        return (
            "*FUNDS*\n━━━━━━━━━━━━━━━\n\n"
            f"Available: {cs}{available:,.2f}\n"
            f"Collateral: {cs}{collateral:,.2f}\n"
            f"Utilized: {cs}{utilized:,.2f}\n"
            f"Total: {cs}{(available + collateral):,.2f}"
        )

    def _format_pnl_funds(self, response: dict, cs: str = "₹") -> str:
        """Format P&L from the funds response (realized + unrealized + total).

        Shared by the /pnl command and the menu P&L button so both report the
        exact same values from the same source (GitHub issue #1576 — the menu
        button previously summed positionbook day-P&L, which disagreed with /pnl).
        """
        if not response or response.get("status") != "success":
            return "Failed to fetch P&L"

        funds = response.get("data", {})

        # P&L values may arrive as strings from some brokers
        try:
            realized_pnl = float(funds.get("m2mrealized", 0))
        except (ValueError, TypeError):
            realized_pnl = 0.0

        try:
            unrealized_pnl = float(funds.get("m2munrealized", 0))
        except (ValueError, TypeError):
            unrealized_pnl = 0.0

        total_pnl = realized_pnl + unrealized_pnl

        realized_emoji = "[+]" if realized_pnl > 0 else "[-]" if realized_pnl < 0 else "[=]"
        unrealized_emoji = "[+]" if unrealized_pnl > 0 else "[-]" if unrealized_pnl < 0 else "[=]"
        total_emoji = "[+]" if total_pnl > 0 else "[-]" if total_pnl < 0 else "[=]"

        return (
            "*PROFIT & LOSS*\n"
            "━━━━━━━━━━━━━━━\n\n"
            f"{realized_emoji} *Realized P&L*\n"
            f"└ {cs}{realized_pnl:,.2f}\n\n"
            f"{unrealized_emoji} *Unrealized P&L*\n"
            f"└ {cs}{unrealized_pnl:,.2f}\n\n"
            f"{total_emoji} *Total P&L*\n"
            f"└ {cs}{total_pnl:,.2f}"
        )

    async def cmd_closeall(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /closeall command — close all open positions with confirmation"""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from telegram.constants import ParseMode

        user = update.effective_user
        telegram_user = get_telegram_user(user.id)

        if not telegram_user:
            await update.message.reply_text("Please link your account first using /link")
            return

        keyboard = [
            [
                InlineKeyboardButton("Yes, close all", callback_data="confirm_closeall"),
            ],
            [
                InlineKeyboardButton(
                    "Close all + Stop strategies",
                    callback_data="confirm_closeall_with_strategies",
                ),
            ],
            [
                InlineKeyboardButton("Cancel", callback_data="cancel_action"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "*Close All Positions*\n"
            "━━━━━━━━━━━━━━━\n\n"
            "This will close ALL open positions across all strategies.\n\n"
            "Choose *Close all + Stop strategies* to also stop every running "
            "Python strategy after closing positions.\n\n"
            "Are you sure?",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN,
        )
        log_command(user.id, "closeall", update.effective_chat.id)

    async def cmd_stoppython(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /stoppython command — list running Python strategies and stop selected/all"""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from telegram.constants import ParseMode

        user = update.effective_user
        telegram_user = get_telegram_user(user.id)

        if not telegram_user:
            await update.message.reply_text("Please link your account first using /link")
            return

        # Snapshot the running strategies (id, display name) at the moment of invocation.
        # Using user_data for index→id mapping keeps callback_data within Telegram's 64-byte cap.
        running = await self._in_app_world(
            _running_python_strategies, timeout=STRATEGY_CALL_TIMEOUT_SECONDS, offload=False
        )

        if not running:
            await update.message.reply_text(
                "ℹ *No Python strategies running.*",
                parse_mode=ParseMode.MARKDOWN,
            )
            log_command(user.id, "stoppython", update.effective_chat.id)
            return

        context.user_data["stoppy_list"] = running

        keyboard = [
            [InlineKeyboardButton(f"{name}", callback_data=f"spy_{idx}")]
            for idx, (_, name) in enumerate(running)
        ]
        keyboard.append([InlineKeyboardButton("Stop All", callback_data="spy_all")])
        keyboard.append([InlineKeyboardButton("Cancel", callback_data="cancel_action")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"*Running Python Strategies* ({len(running)})\n"
            "━━━━━━━━━━━━━━━\n\n"
            "Select a strategy to stop, or *Stop All* to stop every running strategy.",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN,
        )
        log_command(user.id, "stoppython", update.effective_chat.id)

    async def cmd_mode(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /mode command — view or toggle trading mode (Live / Analyze)"""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from telegram.constants import ParseMode

        user = update.effective_user
        telegram_user = get_telegram_user(user.id)

        if not telegram_user:
            await update.message.reply_text("Please link your account first using /link")
            return

        from database.settings_db import get_analyze_mode

        loop = asyncio.get_event_loop()
        is_analyze = await loop.run_in_executor(None, get_analyze_mode)

        current = "Analyze Mode" if is_analyze else "Live Mode"
        toggle_label = "Switch to Live" if is_analyze else "Switch to Analyze"
        toggle_data = "mode_live" if is_analyze else "mode_analyze"

        keyboard = [
            [
                InlineKeyboardButton(f"{toggle_label}", callback_data=toggle_data),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"*Trading Mode*\n"
            f"━━━━━━━━━━━━━━━\n\n"
            f"Current: {current}\n\n"
            f"• *Live Mode* — Orders execute with real broker\n"
            f"• *Analyze Mode* — Sandbox mode (no real orders)\n",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN,
        )
        log_command(user.id, "mode", update.effective_chat.id)

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle inline button callbacks"""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from telegram.constants import ParseMode

        query = update.callback_query
        await query.answer()

        user = query.from_user
        chat_id = query.message.chat.id
        callback_data = query.data

        # Handle cancel action
        if callback_data == "cancel_action":
            await query.edit_message_text("Action cancelled.")
            return

        # Handle close all positions confirmation
        if callback_data == "confirm_closeall":
            telegram_user = get_telegram_user(user.id)
            if not telegram_user:
                await query.edit_message_text("Please link your account first using /link")
                return

            client = self._get_sdk_client(user.id)
            if not client:
                await query.edit_message_text("Failed to connect to OpenAlgo")
                return

            await query.edit_message_text("Closing all positions...")

            try:
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(None, client.closeposition)

                if response and response.get("status") == "success":
                    msg = response.get("message", "All positions closed")
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"*Positions Closed*\n━━━━━━━━━━━━━━━\n\n{msg}",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                else:
                    error = response.get("message", "Unknown error") if response else "No response"
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"*Failed to close positions*\n\n{error}",
                        parse_mode=ParseMode.MARKDOWN,
                    )
            except Exception as e:
                logger.exception(f"Error in closeall: {e}")
                await context.bot.send_message(
                    chat_id=chat_id, text="Error closing positions. Check server logs."
                )
            log_command(user.id, "confirm_closeall", chat_id)
            return

        # Handle close all + stop strategies
        if callback_data == "confirm_closeall_with_strategies":
            telegram_user = get_telegram_user(user.id)
            if not telegram_user:
                await query.edit_message_text("Please link your account first using /link")
                return

            client = self._get_sdk_client(user.id)
            if not client:
                await query.edit_message_text("Failed to connect to OpenAlgo")
                return

            await query.edit_message_text("Closing all positions and stopping strategies...")

            close_msg = ""
            try:
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(None, client.closeposition)
                if response and response.get("status") == "success":
                    close_msg = f"{response.get('message', 'All positions closed')}"
                else:
                    err = response.get("message", "Unknown error") if response else "No response"
                    close_msg = f"Failed to close positions: {err}"
            except Exception as e:
                logger.exception(f"Error in confirm_closeall_with_strategies (close): {e}")
                close_msg = "Error closing positions. Check server logs."

            stop_msg = ""
            try:
                running_ids = [
                    sid
                    for sid, _name in await self._in_app_world(
                        _running_python_strategies,
                        timeout=STRATEGY_CALL_TIMEOUT_SECONDS,
                        offload=False,
                    )
                ]
                if not running_ids:
                    stop_msg = "ℹ No Python strategies were running."
                else:
                    stopped, failed = 0, 0
                    for sid in running_ids:
                        try:
                            ok, _ = await self._in_app_world(
                                _stop_python_strategy,
                                sid,
                                timeout=STRATEGY_CALL_TIMEOUT_SECONDS,
                            )
                            if ok:
                                stopped += 1
                            else:
                                failed += 1
                        except Exception:
                            logger.exception(f"Error stopping strategy {sid}")
                            failed += 1
                    stop_msg = f"Strategies stopped: {stopped}"
                    if failed:
                        stop_msg += f" (failed: {failed})"
            except Exception as e:
                logger.exception(f"Error in confirm_closeall_with_strategies (stop): {e}")
                stop_msg = "Error stopping strategies. Check server logs."

            await context.bot.send_message(
                chat_id=chat_id,
                text=f"*Close All + Stop Strategies*\n━━━━━━━━━━━━━━━\n\n{close_msg}\n\n{stop_msg}",
                parse_mode=ParseMode.MARKDOWN,
            )
            log_command(user.id, "confirm_closeall_with_strategies", chat_id)
            return

        # Handle /stoppython single-strategy selection → confirmation
        if callback_data.startswith("spy_") and callback_data != "spy_all":
            try:
                idx = int(callback_data.removeprefix("spy_"))
            except ValueError:
                await query.edit_message_text("Invalid selection.")
                return

            stoppy_list = context.user_data.get("stoppy_list", [])
            if idx < 0 or idx >= len(stoppy_list):
                await query.edit_message_text("Selection expired. Please run /stoppython again.")
                return

            sid, name = stoppy_list[idx]
            keyboard = [
                [
                    InlineKeyboardButton("Yes, stop", callback_data=f"csy_{idx}"),
                    InlineKeyboardButton("Cancel", callback_data="cancel_action"),
                ]
            ]
            await query.edit_message_text(
                f"*Stop Strategy*\n━━━━━━━━━━━━━━━\n\nStop *{name}*?",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Handle /stoppython "Stop All" → confirmation
        if callback_data == "spy_all":
            stoppy_list = context.user_data.get("stoppy_list", [])
            count = len(stoppy_list)
            if count == 0:
                await query.edit_message_text("Selection expired. Please run /stoppython again.")
                return

            keyboard = [
                [
                    InlineKeyboardButton("Yes, stop all", callback_data="csy_all"),
                    InlineKeyboardButton("Cancel", callback_data="cancel_action"),
                ]
            ]
            await query.edit_message_text(
                f"*Stop All Strategies*\n━━━━━━━━━━━━━━━\n\n"
                f"This will stop *{count}* running Python "
                f"{'strategy' if count == 1 else 'strategies'}.\n\nAre you sure?",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Handle confirmed stop of a single strategy
        if callback_data.startswith("csy_") and callback_data != "csy_all":
            try:
                idx = int(callback_data.removeprefix("csy_"))
            except ValueError:
                await query.edit_message_text("Invalid selection.")
                return

            stoppy_list = context.user_data.get("stoppy_list", [])
            if idx < 0 or idx >= len(stoppy_list):
                await query.edit_message_text("Selection expired. Please run /stoppython again.")
                return

            sid, name = stoppy_list[idx]
            await query.edit_message_text(f"Stopping *{name}*...", parse_mode=ParseMode.MARKDOWN)
            try:
                ok, msg = await self._in_app_world(
                    _stop_python_strategy, sid, timeout=STRATEGY_CALL_TIMEOUT_SECONDS
                )
                emoji = "[OK]" if ok else "[FAILED]"
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"{emoji} *{name}*\n{msg}",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception as e:
                logger.exception(f"Error stopping strategy {sid}: {e}")
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"Error stopping *{name}*. Check server logs.",
                    parse_mode=ParseMode.MARKDOWN,
                )
            log_command(user.id, "confirm_stoppython", chat_id)
            return

        # Handle confirmed stop of all strategies
        if callback_data == "csy_all":
            await query.edit_message_text("Stopping all running strategies...")
            try:
                running_ids = [
                    sid
                    for sid, _name in await self._in_app_world(
                        _running_python_strategies,
                        timeout=STRATEGY_CALL_TIMEOUT_SECONDS,
                        offload=False,
                    )
                ]
                if not running_ids:
                    await context.bot.send_message(
                        chat_id=chat_id, text="ℹ No Python strategies were running."
                    )
                else:
                    stopped, failed = 0, 0
                    for sid in running_ids:
                        try:
                            ok, _ = await self._in_app_world(
                                _stop_python_strategy,
                                sid,
                                timeout=STRATEGY_CALL_TIMEOUT_SECONDS,
                            )
                            if ok:
                                stopped += 1
                            else:
                                failed += 1
                        except Exception:
                            logger.exception(f"Error stopping strategy {sid}")
                            failed += 1
                    summary = f"*Strategies Stopped*\n━━━━━━━━━━━━━━━\n\nStopped: {stopped}"
                    if failed:
                        summary += f"\nFailed: {failed}"
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=summary,
                        parse_mode=ParseMode.MARKDOWN,
                    )
            except Exception as e:
                logger.exception(f"Error in csy_all: {e}")
                await context.bot.send_message(
                    chat_id=chat_id, text="Error stopping strategies. Check server logs."
                )
            log_command(user.id, "confirm_stoppython_all", chat_id)
            return

        # Handle remote logout confirmation
        # Handle mode toggle
        if callback_data in ("mode_live", "mode_analyze"):
            try:
                from database.settings_db import get_analyze_mode, set_analyze_mode

                new_mode = callback_data == "mode_analyze"
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, set_analyze_mode, new_mode)

                # Sync mode to frontend via SocketIO. This runs on the bot's real
                # thread, so the emit goes through the helper that hands it to
                # the hub under eventlet instead of touching green queues here.
                try:
                    from extensions import emit_from_any_thread

                    emit_from_any_thread("app_mode_changed", {"analyze_mode": new_mode})
                except Exception:
                    pass

                mode_label = "Analyze Mode" if new_mode else "Live Mode"
                await query.edit_message_text(
                    f"*Mode Changed*\n━━━━━━━━━━━━━━━\n\nNow in: {mode_label}",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception as e:
                logger.exception(f"Error toggling mode: {e}")
                await query.edit_message_text("Failed to change mode. Check server logs.")
            log_command(user.id, callback_data, chat_id)
            return

        # Handle menu refresh separately - edit the existing message
        if callback_data == "menu":
            keyboard = [
                [
                    InlineKeyboardButton("Orderbook", callback_data="orderbook"),
                    InlineKeyboardButton("Tradebook", callback_data="tradebook"),
                ],
                [
                    InlineKeyboardButton("Positions", callback_data="positions"),
                    InlineKeyboardButton("Holdings", callback_data="holdings"),
                ],
                [
                    InlineKeyboardButton("Funds", callback_data="funds"),
                    InlineKeyboardButton("P&L", callback_data="pnl"),
                ],
                [
                    InlineKeyboardButton("Refresh", callback_data="menu"),
                ],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            try:
                from datetime import datetime

                timestamp = datetime.now().strftime("%H:%M:%S")
                await query.edit_message_text(
                    f"*OpenAlgo Trading Menu*\nSelect an option below:\n_Updated: {timestamp}_",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception as e:
                # If edit fails (message not modified), just acknowledge
                logger.debug(f"Menu refresh: {e}")
            return

        # Get user data for other commands
        telegram_user = get_telegram_user(user.id)
        if not telegram_user:
            await context.bot.send_message(
                chat_id=chat_id, text="Please link your account first using /link"
            )
            return

        cs = self._cs(telegram_user)

        client = self._get_sdk_client(user.id)
        if not client:
            await context.bot.send_message(chat_id=chat_id, text="Failed to connect to OpenAlgo")
            return

        # Map callback data to API calls and formatters
        try:
            loop = asyncio.get_event_loop()

            if callback_data == "orderbook":
                response = await loop.run_in_executor(None, client.orderbook)
                message = self._format_orderbook(response, cs=cs)
            elif callback_data == "tradebook":
                response = await loop.run_in_executor(None, client.tradebook)
                message = self._format_tradebook(response, cs=cs)
            elif callback_data == "positions":
                response = await loop.run_in_executor(None, client.positionbook)
                message = self._format_positions(response, cs=cs)
            elif callback_data == "holdings":
                response = await loop.run_in_executor(None, client.holdings)
                message = self._format_holdings(response, cs=cs)
            elif callback_data == "funds":
                response = await loop.run_in_executor(None, client.funds)
                message = self._format_funds(response, cs=cs)
            elif callback_data == "pnl":
                response = await loop.run_in_executor(None, client.funds)
                message = self._format_pnl_funds(response, cs=cs)
            else:
                message = "Unknown command"

            await context.bot.send_message(
                chat_id=chat_id, text=message, parse_mode=ParseMode.MARKDOWN
            )
            log_command(user.id, callback_data, chat_id)

        except Exception as e:
            logger.exception(f"Error in button callback for {callback_data}: {e}")
            await context.bot.send_message(
                chat_id=chat_id, text="Failed to fetch data. Please try again."
            )

    async def send_notification(self, telegram_id: int, message: str) -> bool:
        """Send a notification to a specific Telegram user."""
        try:
            if not self.application or not self.is_running:
                logger.error("Bot not initialized or not running")
                return False

            # Get the bot from the application
            bot = self.application.bot

            await bot.send_message(chat_id=telegram_id, text=message, parse_mode="Markdown")
            logger.debug(f"Notification sent to telegram_id: {telegram_id}")
            return True
        except Exception as e:
            logger.exception(f"Error sending notification to {telegram_id}: {str(e)}")
            return False

    async def broadcast_message(self, message: str, filters: dict = None) -> tuple[int, int]:
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
                if filters.get("notifications_enabled") is not None:
                    users = [
                        u
                        for u in users
                        if u.get("notifications_enabled") == filters["notifications_enabled"]
                    ]
                if filters.get("openalgo_username"):
                    users = [
                        u
                        for u in users
                        if u.get("openalgo_username") == filters["openalgo_username"]
                    ]

            success_count = 0
            fail_count = 0

            for user in users:
                try:
                    telegram_id = user.get("telegram_id")
                    if telegram_id:
                        bot = self.application.bot
                        await bot.send_message(
                            chat_id=telegram_id, text=message, parse_mode="Markdown"
                        )
                        success_count += 1
                        # Add small delay to avoid rate limits
                        await asyncio.sleep(0.1)
                except Exception as e:
                    logger.exception(
                        f"Failed to send broadcast to {user.get('telegram_id')}: {str(e)}"
                    )
                    fail_count += 1

            logger.debug(f"Broadcast complete: {success_count} success, {fail_count} failed")
            return success_count, fail_count

        except Exception as e:
            logger.exception(f"Error in broadcast: {str(e)}")
            return 0, 0


# Create global instance
telegram_bot_service = TelegramBotService()
