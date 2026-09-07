import json
import logging
import os
import re
import sys
import traceback
from datetime import datetime, timedelta
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Optional

from utils import real_threading as _real_threading
from utils.url_redaction import redact_url_credentials


def _create_real_lock(self) -> None:
    """Give every logging handler a REAL lock instead of eventlet's green one.

    ``logging.Handler`` serialises emit() with a lock it builds in __init__.
    Under gunicorn+eventlet the app is imported after monkey-patching, so that
    lock is a green semaphore owned by the hub, and it can only be handed
    between greenlets.

    Every real OS thread in this project logs: the websocket client's asyncio
    loop, the Telegram bot thread and its Kaleido renderer, the broker snapshot
    feed threads. The moment one of them logs while a greenlet holds the same
    handler lock, the hub tries to resume a waiter belonging to another thread,
    raises ``greenlet.error: Cannot switch to a different thread`` inside
    ``fire_timers``, and leaves that thread blocked on the handler **forever**.
    The give-away beforehand is ``AttributeError: 'StreamHandler' object has no
    attribute 'lock'`` on unrelated requests. See issues #1569 and #1402.

    A real lock is held only for the duration of one emit, and it is the same
    lock the dev server has always used, where nothing is patched.

    Patched on the class so it also covers handlers this project does not
    create: gunicorn's, Flask's, and any third-party library's.
    """
    self.lock = _real_threading.RLock()


logging.Handler.createLock = _create_real_lock

# Handlers built before this module was imported still hold a green lock.
# Re-lock whatever is already attached anywhere in the tree.
for _logger in [logging.getLogger()] + [
    logging.getLogger(_name) for _name in list(logging.root.manager.loggerDict)
]:
    for _handler in list(getattr(_logger, "handlers", ())):
        _handler.createLock()

# Load environment variables if .env file exists
try:
    from dotenv import load_dotenv

    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        load_dotenv(dotenv_path=env_path, override=False)
except ImportError:
    pass

try:
    from colorama import Back, Fore, Style, init

    # Initialize colorama for Windows compatibility
    init(autoreset=True)
    COLORAMA_AVAILABLE = True
except ImportError:
    COLORAMA_AVAILABLE = False

# Sensitive patterns to filter out.
#
# The patterns must match the forms the codebase actually emits, not just
# `key=value`. Python dict repr (`'apikey': 'X'`), JSON (`"apikey":"X"`),
# and shell-style (`apikey="X"`) all need to redact. The character class on
# the value side allows `\w \- . + / =` so JWTs and base64 tokens are fully
# consumed; the surrounding quote (if any) is preserved by anchoring on the
# prefix capture group.
SENSITIVE_PATTERNS = [
    # Bearer header tokens, run first so the broader pattern below doesn't
    # leave the bearer suffix exposed when wrapped in quotes.
    #
    # The value is not always a single word. Two brokers send a composite
    # credential: tradejini uses "Bearer <api_key>:<access_token>" and aliceblue
    # uses "Bearer <user_id> <session_id>". A [\w\-\.]+ value class stops at the
    # separator, so it redacted the harmless half and left the real secret in
    # the log. Continue across ':' and single spaces between word characters.
    # That still stops at a quote, comma or brace, so it cannot swallow the rest
    # of a headers dict.
    (r"(Bearer\s+)[\w\-\.]+(?:[:\s][\w\-\.]+)*", r"\1[REDACTED]"),
    # Legacy callback diagnostics also used prose rather than key=value:
    # "Received authorization code: X", "The request token is X", and
    # similar forms. Keep the useful label while removing the replayable
    # value. This is deliberately narrower than a generic ``code`` rule so
    # HTTP/status/error codes remain visible.
    (
        r"((?:received\s+(?:authorization\s+code|token[_-]?id)|the\s+(?:request\s+token|code)\s+is|oauth\s+callback\s+with\s+code)\s*:?\s*)[^\s'\",;}\]]+",
        r"\1[REDACTED]",
    ),
    # Common credential keys in any of: key=val, key: val, 'key': 'val',
    # "key":"val", key="val". Includes broker-token aliases the codebase
    # actually logs (enctoken, feed_token, access_token, session_token).
    # Value class is a negated set so passwords with symbols (@!#$ ...) are
    # fully consumed; we stop at whitespace, quotes, and dict/JSON structure.
    (
        r"(['\"]?(?:api[_-]?key[_-]?pepper|api[_-]?key|app[_-]?key|password|access[_-]?token|enctoken|feed[_-]?token|session[_-]?token|auth[_-]?token|api[_-]?session|token[_-]?id|request[_-]?token|auth[_-]?code|authorization|cookie|secret|pepper|token)['\"]?\s*[:=]\s*['\"]?)[^\s'\",;}\]]+",
        r"\1[REDACTED]",
    ),
]

# Color mappings for different log levels
if COLORAMA_AVAILABLE:
    LOG_COLORS = {
        "DEBUG": Fore.CYAN,
        "INFO": Fore.GREEN,
        "WARNING": Fore.YELLOW,
        "ERROR": Fore.RED,
        "CRITICAL": Fore.RED + Style.BRIGHT,
    }

    # Additional colors for components
    COMPONENT_COLORS = {
        "timestamp": Fore.BLUE,
        "module": Fore.MAGENTA,
        "reset": Style.RESET_ALL,
    }
else:
    LOG_COLORS = {}
    COMPONENT_COLORS = {}


class WerkzeugErrorFilter(logging.Filter):
    """Filter to suppress known Werkzeug development server errors that are not actionable."""

    # Patterns of error messages to suppress
    SUPPRESSED_PATTERNS = [
        "write() before start_response",  # SSE/streaming response race condition
        "greenlet.GreenletExit",  # Normal greenlet termination
    ]

    def filter(self, record) -> bool:
        """
        Filter out specific development server errors.

        Args:
            record (logging.LogRecord): The log record to check.

        Returns:
            bool: False if the record matches a suppressed pattern, True otherwise.
        """
        try:
            msg = str(record.msg)
            # Check if this is a suppressed error pattern
            for pattern in self.SUPPRESSED_PATTERNS:
                if pattern in msg:
                    return False

            # Also check exc_info if present
            if record.exc_info and record.exc_info[1]:
                exc_str = str(record.exc_info[1])
                for pattern in self.SUPPRESSED_PATTERNS:
                    if pattern in exc_str:
                        return False
        except Exception:
            pass

        return True


class WebSocketHandshakeFilter(logging.Filter):
    """Suppress noisy WebSocket handshake errors from short-lived connections."""

    SUPPRESSED_PATTERNS = [
        "opening handshake failed",
        "did not receive a valid HTTP request",
        "connection closed while reading HTTP request line",
    ]

    def filter(self, record) -> bool:
        """
        Filter out specific WebSocket handshake errors.

        Args:
            record (logging.LogRecord): The log record to check.

        Returns:
            bool: False if the record matches a suppressed pattern, True otherwise.
        """
        try:
            msg = str(record.getMessage())
            for pattern in self.SUPPRESSED_PATTERNS:
                if pattern in msg:
                    return False

            if record.exc_info and record.exc_info[1]:
                exc_str = str(record.exc_info[1])
                for pattern in self.SUPPRESSED_PATTERNS:
                    if pattern in exc_str:
                        return False
        except Exception:
            pass

        return True


def redact_text(text: str) -> str:
    """Apply every sensitive pattern to a piece of text."""
    text = redact_url_credentials(text)
    for pattern, replacement in SENSITIVE_PATTERNS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


class SensitiveDataFilter(logging.Filter):
    """Redact sensitive information from log records.

    The record is rendered first and redacted afterwards, which is the only
    order that is both correct and safe.

    Redacting the template and the arguments separately, as this used to, went
    wrong in three ways at once. Every argument was passed through ``str()``,
    so an argument feeding a ``%d`` or ``%.2f`` became text and the record
    could no longer be formatted: the operator was shown "Strategy module
    recovered %d run(s)", with no way to tell whether it recovered none or
    twelve. A mapping argument, the ``%(key)s`` form, was iterated as keys and
    replaced by a tuple of key names. And redacting the template could delete a
    placeholder along with the secret beside it, leaving more arguments than
    specifiers.

    Rendering first fixes all three: the arguments are still their own types
    when the message is built, so numbers format; the mapping form formats
    normally; and the redaction then runs over the finished text, which is
    where a secret ends up regardless of whether it arrived in the template or
    in an argument. Clearing ``args`` afterwards is what keeps the two in step,
    and is the same thing the JSON handler below already does.
    """

    def filter(self, record) -> bool:
        """Redact the record in place. Always returns True."""
        try:
            try:
                text = record.getMessage()
            except Exception:
                # Malformed format string or mismatched arguments. Fall back to
                # the raw template so the line is still emitted and still
                # redacted, rather than being dropped.
                text = str(record.msg)

            text = redact_text(text)

            # The traceback too. A secret raised inside an exception message,
            # or sitting in a frame's arguments, reaches every sink through
            # exc_info rather than through the message, and the message was the
            # only thing being redacted. Rendering it here and storing the
            # redacted form in exc_text is what the standard Formatter reads in
            # preference to formatting exc_info again.
            if record.exc_info and record.exc_info[0] is not None:
                record.exc_text = redact_text("".join(traceback.format_exception(*record.exc_info)))
            elif record.exc_text:
                record.exc_text = redact_text(record.exc_text)
            if record.stack_info:
                record.stack_info = redact_text(record.stack_info)

            record.msg = text
            # Rendered, so there is nothing left to substitute. getMessage()
            # skips formatting entirely when args is falsy, which also means a
            # stray "%" surviving in the text cannot raise later.
            record.args = ()
        except Exception:
            # If filtering fails, don't block the log message
            pass

        return True


class ColoredFormatter(logging.Formatter):
    """Custom formatter that adds colors to log levels and components for console output."""

    def __init__(self, fmt=None, datefmt=None, enable_colors=True):
        super().__init__(fmt, datefmt)
        self.enable_colors = enable_colors and COLORAMA_AVAILABLE and self._supports_color()

    def _supports_color(self):
        """Check if the terminal supports color output."""
        # Check for FORCE_COLOR environment variable first
        force_color = os.environ.get("FORCE_COLOR", "").lower()
        if force_color in ["1", "true", "yes", "on"]:
            return True
        elif force_color in ["0", "false", "no", "off"]:
            return False

        # Check for NO_COLOR environment variable (standard)
        if os.environ.get("NO_COLOR"):
            return False

        # Check if we're in a terminal that supports colors
        if hasattr(sys.stdout, "isatty") and sys.stdout.isatty():
            # Check environment variables
            term = os.environ.get("TERM", "")
            if "color" in term.lower() or term in [
                "xterm",
                "xterm-256color",
                "screen",
                "screen-256color",
            ]:
                return True

            # Check for common CI environments that support colors
            ci_envs = ["GITHUB_ACTIONS", "GITLAB_CI", "JENKINS_URL", "BUILDKITE"]
            if any(env in os.environ for env in ci_envs):
                return True

        # For Windows Command Prompt or PowerShell, check if ANSI support is available
        if os.name == "nt":
            try:
                # Try to enable ANSI escape sequences on Windows
                import subprocess

                result = subprocess.run(
                    ["reg", "query", "HKCU\\Console", "/v", "VirtualTerminalLevel"],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0 and "VirtualTerminalLevel" in result.stdout:
                    return True
            except Exception:
                pass

            # Check if running in Windows Terminal, VS Code, or similar
            wt_session = os.environ.get("WT_SESSION")
            vscode_term = os.environ.get("VSCODE_INJECTION")
            if wt_session or vscode_term:
                return True

        return False

    def format(self, record):
        if not self.enable_colors:
            return super().format(record)

        # Get the original formatted message
        # Wrap in try-except to handle format string mismatches from external libraries
        try:
            original_format = super().format(record)
        except (TypeError, ValueError):
            # Handle cases where external libraries (like hpack) pass wrong types
            # Example: hpack passes strings like '2' to %d format specifier
            # Fallback to basic formatting without the problematic args
            try:
                record.message = str(record.msg)  # Convert message to string
                record.args = None  # Clear args to avoid format issues
                original_format = super().format(record)
            except Exception:
                # Last resort: return raw message
                return f"[{record.levelname}] {record.msg}"

        # Apply colors to different components
        level_color = LOG_COLORS.get(record.levelname, "")
        reset = COMPONENT_COLORS.get("reset", "")
        timestamp_color = COMPONENT_COLORS.get("timestamp", "")
        module_color = COMPONENT_COLORS.get("module", "")

        # Parse the format to identify components
        # This assumes the default format: [timestamp] LEVEL in module: message
        if "[" in original_format and "]" in original_format:
            # Color the timestamp
            original_format = re.sub(r"(\[.*?\])", f"{timestamp_color}\\1{reset}", original_format)

        # Color the log level
        if record.levelname in original_format:
            original_format = original_format.replace(
                record.levelname, f"{level_color}{record.levelname}{reset}"
            )

        # Color the module name
        if hasattr(record, "module") and record.module in original_format:
            original_format = original_format.replace(
                f" in {record.module}:", f" in {module_color}{record.module}{reset}:"
            )

        return original_format


class JSONErrorFormatter(logging.Formatter):
    """Formats ERROR+ records as single-line JSON for machine consumption.

    Output goes to log/errors.jsonl — one JSON object per line.
    Claude Code can read this file directly to diagnose issues.
    """

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "module": record.module,
            "file": f"{record.pathname}:{record.lineno}",
            "message": record.getMessage(),
        }

        # Capture full traceback if present
        if record.exc_info and record.exc_info[0] is not None:
            # Redacted here as well as in the filter: this handler renders
            # exc_info itself rather than reading the exc_text the filter
            # prepared, and log/errors.jsonl is the first place CLAUDE.md tells
            # anyone to look when debugging.
            entry["exception"] = [
                redact_text(line) for line in traceback.format_exception(*record.exc_info)
            ]

        # Capture Flask request context if available
        try:
            from flask import has_request_context, request

            if has_request_context():
                entry["request"] = {
                    "method": request.method,
                    "path": redact_url_credentials(request.path),
                    "ip": request.remote_addr,
                }
        except Exception:
            pass

        return json.dumps(entry, default=str)


def cleanup_old_logs(log_dir: Path, retention_days: int):
    """Remove log files older than retention_days."""
    if not log_dir.exists():
        return

    cutoff_date = datetime.now() - timedelta(days=retention_days)

    for log_file in log_dir.glob("*.log*"):
        try:
            # Get file modification time
            file_mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
            if file_mtime < cutoff_date:
                log_file.unlink()
        except Exception:
            # Skip files that can't be processed
            pass


def setup_logging():
    """Initialize the logging configuration from environment variables."""
    # Get configuration from environment
    log_to_file = os.getenv("LOG_TO_FILE", "False").lower() == "true"
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_dir = os.getenv("LOG_DIR", "log")
    log_format = os.getenv("LOG_FORMAT", "[%(asctime)s] %(levelname)s in %(module)s: %(message)s")
    log_retention = int(os.getenv("LOG_RETENTION", "14"))
    log_colors = os.getenv("LOG_COLORS", "True").lower() == "true"

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level, logging.INFO))

    # Remove existing handlers
    root_logger.handlers = []

    # Create formatters
    # Colored formatter for console (if colors are enabled)
    console_formatter = ColoredFormatter(log_format, enable_colors=log_colors)
    # Regular formatter for file output (no colors)
    file_formatter = logging.Formatter(log_format)

    # Add sensitive data filter
    sensitive_filter = SensitiveDataFilter()

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(console_formatter)
    console_handler.addFilter(sensitive_filter)
    root_logger.addHandler(console_handler)

    # File handler (if enabled)
    if log_to_file:
        log_path = Path(log_dir)
        log_path.mkdir(exist_ok=True)

        # Clean up old logs
        cleanup_old_logs(log_path, log_retention)

        # Create file handler with daily rotation
        log_file = log_path / f"openalgo_{datetime.now().strftime('%Y-%m-%d')}.log"
        file_handler = TimedRotatingFileHandler(
            filename=str(log_file),
            when="midnight",
            interval=1,
            backupCount=log_retention,
            encoding="utf-8",
        )
        file_handler.setFormatter(file_formatter)
        file_handler.addFilter(sensitive_filter)
        root_logger.addHandler(file_handler)

    # JSON error log — always active, captures ERROR+ to log/errors.jsonl
    # Truncate to last 1000 entries on startup to prevent unbounded growth
    errors_dir = Path(log_dir)
    errors_dir.mkdir(exist_ok=True)
    errors_file = errors_dir / "errors.jsonl"
    try:
        if errors_file.exists() and errors_file.stat().st_size > 0:
            lines = errors_file.read_text(encoding="utf-8").splitlines()
            if len(lines) > 1000:
                errors_file.write_text("\n".join(lines[-1000:]) + "\n", encoding="utf-8")
    except Exception:
        pass
    json_handler = logging.FileHandler(
        filename=str(errors_file),
        encoding="utf-8",
    )
    json_handler.setLevel(logging.ERROR)
    json_handler.setFormatter(JSONErrorFormatter())
    json_handler.addFilter(sensitive_filter)
    root_logger.addHandler(json_handler)

    # Suppress noisy third-party loggers
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    # Add Werkzeug error filter to suppress known development server errors
    werkzeug_error_filter = WerkzeugErrorFilter()
    logging.getLogger("werkzeug").addFilter(werkzeug_error_filter)
    logging.getLogger("werkzeug._internal").addFilter(werkzeug_error_filter)
    # Flask uses _internal logger for werkzeug errors
    internal_logger = logging.getLogger("_internal")
    internal_logger.addFilter(werkzeug_error_filter)
    # Suppress noisy WebSocket handshake errors (short-lived connections)
    ws_handshake_filter = WebSocketHandshakeFilter()
    logging.getLogger("websockets").addFilter(ws_handshake_filter)
    logging.getLogger("websockets.server").addFilter(ws_handshake_filter)
    logging.getLogger("server").addFilter(ws_handshake_filter)
    # Suppress hpack DEBUG logs - they have format string bugs and are not useful
    logging.getLogger("hpack.hpack").setLevel(logging.INFO)
    logging.getLogger("hpack").setLevel(logging.INFO)
    # Suppress APScheduler verbose logs
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("apscheduler.scheduler").setLevel(logging.WARNING)
    logging.getLogger("apscheduler.executors").setLevel(logging.WARNING)
    # Suppress websockets library logs
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("websockets.server").setLevel(logging.WARNING)
    # Suppress telegram-bot library logs
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("telegram.ext").setLevel(logging.WARNING)


def highlight_url(url: str, text: str = None) -> str:
    """
    Create a highlighted URL string with bright colors and styling.

    Args:
        url: The URL to highlight
        text: Optional text to display instead of the URL

    Returns:
        Formatted string with colors (if available) or plain text
    """
    if not COLORAMA_AVAILABLE:
        return text or url

    # Check if colors are enabled
    log_colors = os.getenv("LOG_COLORS", "True").lower() == "true"
    force_color = os.getenv("FORCE_COLOR", "").lower() in ["1", "true", "yes", "on"]

    if not log_colors and not force_color:
        return text or url

    # Create bright, attention-grabbing formatting
    bright_cyan = Fore.CYAN + Style.BRIGHT
    bright_white = Fore.WHITE + Style.BRIGHT
    reset = Style.RESET_ALL

    # Format: [bright_white]text[reset] -> [bright_cyan]url[reset]
    if text and text != url:
        return f"{bright_white}{text}{reset} -> {bright_cyan}{url}{reset}"
    else:
        return f"{bright_cyan}{url}{reset}"


def log_startup_banner(
    logger_instance, title: str, url: str, separator_char: str = "=", width: int = 60
):
    """
    Log a highlighted startup banner with URL.

    Args:
        logger_instance: Logger instance to use
        title: Main title text
        url: URL to highlight
        separator_char: Character for separator lines
        width: Width of the banner
    """
    if not COLORAMA_AVAILABLE:
        # Fallback without colors
        logger_instance.info(separator_char * width)
        logger_instance.info(title)
        logger_instance.info(f"Access the application at: {url}")
        logger_instance.info(separator_char * width)
        return

    # Check if colors are enabled
    log_colors = os.getenv("LOG_COLORS", "True").lower() == "true"
    force_color = os.getenv("FORCE_COLOR", "").lower() in ["1", "true", "yes", "on"]

    if not log_colors and not force_color:
        # Fallback without colors
        logger_instance.info(separator_char * width)
        logger_instance.info(title)
        logger_instance.info(f"Access the application at: {url}")
        logger_instance.info(separator_char * width)
        return

    # Create colorful banner
    bright_green = Fore.GREEN + Style.BRIGHT
    bright_yellow = Fore.YELLOW + Style.BRIGHT
    bright_cyan = Fore.CYAN + Style.BRIGHT
    reset = Style.RESET_ALL

    # Log colored banner
    separator_line = f"{bright_yellow}{separator_char * width}{reset}"
    title_line = f"{bright_green}{title}{reset}"
    url_line = f"Access the application at: {bright_cyan}{url}{reset}"

    logger_instance.info(separator_line)
    logger_instance.info(title_line)
    logger_instance.info(url_line)
    logger_instance.info(separator_line)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a module.

    Args:
        name: Module name (typically __name__)

    Returns:
        Logger instance configured with the module name and color support

    Environment Variables:
        LOG_COLORS: Enable/disable colored console output (default: True)
        LOG_LEVEL: Set logging level (default: INFO)
        LOG_TO_FILE: Enable file logging (default: False)
        LOG_DIR: Directory for log files (default: log)
        LOG_FORMAT: Custom log format string
        LOG_RETENTION: Days to retain log files (default: 14)
    """
    return logging.getLogger(name)


# Initialize logging on import
setup_logging()
