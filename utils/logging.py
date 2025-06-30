import logging
import os
import re
import sys
from datetime import datetime, timedelta
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Optional

# Load environment variables if .env file exists
try:
    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
    if os.path.exists(env_path):
        load_dotenv(dotenv_path=env_path, override=False)
except ImportError:
    pass

try:
    from colorama import Fore, Back, Style, init
    # Initialize colorama for Windows compatibility
    init(autoreset=True)
    COLORAMA_AVAILABLE = True
except ImportError:
    COLORAMA_AVAILABLE = False

# Sensitive patterns to filter out
SENSITIVE_PATTERNS = [
    (r'(api[_-]?key[\s]*[=:]\s*)[\w\-]+', r'\1[REDACTED]'),
    (r'(password[\s]*[=:]\s*)[\w\-]+', r'\1[REDACTED]'),
    (r'(token[\s]*[=:]\s*)[\w\-]+', r'\1[REDACTED]'),
    (r'(secret[\s]*[=:]\s*)[\w\-]+', r'\1[REDACTED]'),
    (r'(authorization[\s]*[=:]\s*)[\w\-]+', r'\1[REDACTED]'),
    (r'(Bearer\s+)[\w\-\.]+', r'\1[REDACTED]'),
]

# Color mappings for different log levels
if COLORAMA_AVAILABLE:
    LOG_COLORS = {
        'DEBUG': Fore.CYAN,
        'INFO': Fore.GREEN,
        'WARNING': Fore.YELLOW,
        'ERROR': Fore.RED,
        'CRITICAL': Fore.RED + Style.BRIGHT,
    }
    
    # Additional colors for components
    COMPONENT_COLORS = {
        'timestamp': Fore.BLUE,
        'module': Fore.MAGENTA,
        'reset': Style.RESET_ALL,
    }
else:
    LOG_COLORS = {}
    COMPONENT_COLORS = {}


class SensitiveDataFilter(logging.Filter):
    """Filter to redact sensitive information from log messages."""
    
    def filter(self, record):
        try:
            # Filter the main message
            for pattern, replacement in SENSITIVE_PATTERNS:
                record.msg = re.sub(pattern, replacement, str(record.msg), flags=re.IGNORECASE)
            
            # Filter args if present
            if hasattr(record, 'args') and record.args:
                filtered_args = []
                for arg in record.args:
                    filtered_arg = str(arg)
                    for pattern, replacement in SENSITIVE_PATTERNS:
                        filtered_arg = re.sub(pattern, replacement, filtered_arg, flags=re.IGNORECASE)
                    filtered_args.append(filtered_arg)
                record.args = tuple(filtered_args)
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
        force_color = os.environ.get('FORCE_COLOR', '').lower()
        if force_color in ['1', 'true', 'yes', 'on']:
            return True
        elif force_color in ['0', 'false', 'no', 'off']:
            return False
        
        # Check for NO_COLOR environment variable (standard)
        if os.environ.get('NO_COLOR'):
            return False
        
        # Check if we're in a terminal that supports colors
        if hasattr(sys.stdout, 'isatty') and sys.stdout.isatty():
            # Check environment variables
            term = os.environ.get('TERM', '')
            if 'color' in term.lower() or term in ['xterm', 'xterm-256color', 'screen', 'screen-256color']:
                return True
                
            # Check for common CI environments that support colors
            ci_envs = ['GITHUB_ACTIONS', 'GITLAB_CI', 'JENKINS_URL', 'BUILDKITE']
            if any(env in os.environ for env in ci_envs):
                return True
        
        # For Windows Command Prompt or PowerShell, check if ANSI support is available
        if os.name == 'nt':
            try:
                # Try to enable ANSI escape sequences on Windows
                import subprocess
                result = subprocess.run(['reg', 'query', 'HKCU\\Console', '/v', 'VirtualTerminalLevel'], 
                                      capture_output=True, text=True)
                if result.returncode == 0 and 'VirtualTerminalLevel' in result.stdout:
                    return True
            except:
                pass
            
            # Check if running in Windows Terminal, VS Code, or similar
            wt_session = os.environ.get('WT_SESSION')
            vscode_term = os.environ.get('VSCODE_INJECTION')
            if wt_session or vscode_term:
                return True
                
        return False
    
    def format(self, record):
        if not self.enable_colors:
            return super().format(record)
        
        # Get the original formatted message
        original_format = super().format(record)
        
        # Apply colors to different components
        level_color = LOG_COLORS.get(record.levelname, '')
        reset = COMPONENT_COLORS.get('reset', '')
        timestamp_color = COMPONENT_COLORS.get('timestamp', '')
        module_color = COMPONENT_COLORS.get('module', '')
        
        # Parse the format to identify components
        # This assumes the default format: [timestamp] LEVEL in module: message
        if '[' in original_format and ']' in original_format:
            # Color the timestamp
            original_format = re.sub(
                r'(\[.*?\])', 
                f'{timestamp_color}\\1{reset}', 
                original_format
            )
        
        # Color the log level
        if record.levelname in original_format:
            original_format = original_format.replace(
                record.levelname,
                f'{level_color}{record.levelname}{reset}'
            )
        
        # Color the module name
        if hasattr(record, 'module') and record.module in original_format:
            original_format = original_format.replace(
                f' in {record.module}:',
                f' in {module_color}{record.module}{reset}:'
            )
        
        return original_format


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
    log_to_file = os.getenv('LOG_TO_FILE', 'False').lower() == 'true'
    log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
    log_dir = os.getenv('LOG_DIR', 'log')
    log_format = os.getenv('LOG_FORMAT', '[%(asctime)s] %(levelname)s in %(module)s: %(message)s')
    log_retention = int(os.getenv('LOG_RETENTION', '14'))
    log_colors = os.getenv('LOG_COLORS', 'True').lower() == 'true'
    
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
            when='midnight',
            interval=1,
            backupCount=log_retention,
            encoding='utf-8'
        )
        file_handler.setFormatter(file_formatter)
        file_handler.addFilter(sensitive_filter)
        root_logger.addHandler(file_handler)
    
    # Suppress noisy third-party loggers
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    

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
    log_colors = os.getenv('LOG_COLORS', 'True').lower() == 'true'
    force_color = os.getenv('FORCE_COLOR', '').lower() in ['1', 'true', 'yes', 'on']
    
    if not log_colors and not force_color:
        return text or url
    
    # Create bright, attention-grabbing formatting
    bright_cyan = Fore.CYAN + Style.BRIGHT
    bright_white = Fore.WHITE + Style.BRIGHT
    reset = Style.RESET_ALL
    
    display_text = text or url
    
    # Format: [bright_white]text[reset] -> [bright_cyan]url[reset]
    if text and text != url:
        return f"{bright_white}{text}{reset} -> {bright_cyan}{url}{reset}"
    else:
        return f"{bright_cyan}{url}{reset}"


def log_startup_banner(logger_instance, title: str, url: str, separator_char: str = "=", width: int = 60):
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
    log_colors = os.getenv('LOG_COLORS', 'True').lower() == 'true'
    force_color = os.getenv('FORCE_COLOR', '').lower() in ['1', 'true', 'yes', 'on']
    
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