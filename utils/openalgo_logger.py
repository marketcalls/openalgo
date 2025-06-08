"""
OpenAlgo Centralized Logging System

This module provides a centralized logging system for the OpenAlgo trading platform.
It's designed to be zero-config by default, performant, and trader-friendly.

Features:
- Zero configuration required by default
- Console logging by default, optional file logging
- Environment-based configuration
- Structured logging with trading-specific fields
- Daily log rotation when file logging is enabled
- Performance optimized with minimal overhead
- Automatic exception logging decorator
"""

import logging
import logging.handlers
import os
import sys
import json
from datetime import datetime
from functools import wraps
import traceback


class OpenAlgoFormatter(logging.Formatter):
    """Custom formatter for OpenAlgo logs with structured output"""
    
    def __init__(self, use_json=False, use_colors=True):
        self.use_json = use_json
        self.use_colors = use_colors and sys.stdout.isatty()
        
        if self.use_json:
            super().__init__()
        else:
            # Human-readable format for console
            super().__init__(
                fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
    
    def format(self, record):
        if self.use_json:
            return self._format_json(record)
        else:
            return self._format_console(record)
    
    def _format_json(self, record):
        """Format log record as JSON for structured logging"""
        log_data = {
            'timestamp': datetime.fromtimestamp(record.created).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }
        
        # Add extra fields if present
        if hasattr(record, 'extra_fields'):
            log_data.update(record.extra_fields)
        
        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)
        
        return json.dumps(log_data, default=str)
    
    def _format_console(self, record):
        """Format log record for console with optional colors"""
        formatted = super().format(record)
        
        if self.use_colors:
            # Color codes for different log levels
            colors = {
                'DEBUG': '\033[36m',    # Cyan
                'INFO': '\033[32m',     # Green
                'WARNING': '\033[33m',  # Yellow
                'ERROR': '\033[31m',    # Red
                'CRITICAL': '\033[35m'  # Magenta
            }
            reset = '\033[0m'
            
            level_color = colors.get(record.levelname, '')
            if level_color:
                formatted = formatted.replace(
                    record.levelname, 
                    f"{level_color}{record.levelname}{reset}"
                )
        
        # Add extra fields if present in human-readable format
        if hasattr(record, 'extra_fields') and record.extra_fields:
            extra_str = ' | '.join([f"{k}={v}" for k, v in record.extra_fields.items()])
            formatted += f" | {extra_str}"
        
        return formatted


class OpenAlgoLogger:
    """Centralized logger for OpenAlgo with trading-specific features"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self._setup_logging()
            self._initialized = True
    
    def _setup_logging(self):
        """Setup logging configuration based on environment variables"""
        # Get configuration from environment
        self.log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
        self.log_to_file = os.getenv('LOG_TO_FILE', 'false').lower() == 'true'
        self.log_format = os.getenv('LOG_FORMAT', 'console')  # console or json
        self.log_dir = os.getenv('LOG_DIR', 'logs')
        
        # Validate log level
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if self.log_level not in valid_levels:
            self.log_level = 'INFO'
        
        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, self.log_level))
        
        # Clear existing handlers
        root_logger.handlers.clear()
        
        # Setup console handler (always enabled)
        self._setup_console_handler(root_logger)
        
        # Setup file handlers if enabled
        if self.log_to_file:
            self._setup_file_handlers(root_logger)
        
        # Disable some noisy loggers in production
        if self.log_level != 'DEBUG':
            logging.getLogger('werkzeug').setLevel(logging.WARNING)
            logging.getLogger('urllib3').setLevel(logging.WARNING)
    
    def _setup_console_handler(self, root_logger):
        """Setup console logging handler"""
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, self.log_level))
        
        use_json = self.log_format.lower() == 'json'
        console_formatter = OpenAlgoFormatter(use_json=use_json, use_colors=True)
        console_handler.setFormatter(console_formatter)
        
        root_logger.addHandler(console_handler)
    
    def _setup_file_handlers(self, root_logger):
        """Setup file logging handlers with rotation"""
        # Ensure log directory exists
        os.makedirs(self.log_dir, exist_ok=True)
        
        # Main log file with daily rotation
        main_log_file = os.path.join(self.log_dir, 'openalgo.log')
        file_handler = logging.handlers.TimedRotatingFileHandler(
            main_log_file,
            when='midnight',
            interval=1,
            backupCount=30,  # Keep 30 days of logs
            encoding='utf-8'
        )
        file_handler.setLevel(getattr(logging, self.log_level))
        
        # Use JSON format for file logs for better parsing
        file_formatter = OpenAlgoFormatter(use_json=True, use_colors=False)
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
        
        # Separate error log file
        error_log_file = os.path.join(self.log_dir, 'openalgo-errors.log')
        error_handler = logging.handlers.TimedRotatingFileHandler(
            error_log_file,
            when='midnight',
            interval=1,
            backupCount=30,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(file_formatter)
        root_logger.addHandler(error_handler)


def get_logger(name: str = None) -> logging.Logger:
    """
    Get a logger instance for the specified module.
    
    Args:
        name: Logger name, typically __name__ from calling module
        
    Returns:
        Configured logger instance
    """
    # Ensure logging is initialized
    OpenAlgoLogger()
    
    if name is None:
        # Try to determine caller's module name
        import inspect
        frame = inspect.currentframe().f_back
        name = frame.f_globals.get('__name__', 'openalgo')
    
    return logging.getLogger(name)


def log_with_context(logger: logging.Logger, level: str, message: str, **extra_fields):
    """
    Log a message with additional context fields.
    
    Args:
        logger: Logger instance
        level: Log level (debug, info, warning, error, critical)
        message: Log message
        **extra_fields: Additional fields to include in the log
    """
    # Create a log record with extra fields
    record = logger.makeRecord(
        name=logger.name,
        level=getattr(logging, level.upper()),
        fn='',
        lno=0,
        msg=message,
        args=(),
        exc_info=None
    )
    record.extra_fields = extra_fields
    logger.handle(record)


def log_exception(logger: logging.Logger, message: str = "An exception occurred", **extra_fields):
    """
    Log an exception with context.
    
    Args:
        logger: Logger instance
        message: Custom message for the exception
        **extra_fields: Additional context fields
    """
    extra_fields['exception_type'] = sys.exc_info()[0].__name__ if sys.exc_info()[0] else 'Unknown'
    log_with_context(logger, 'error', message, **extra_fields)
    logger.error(traceback.format_exc())


def log_trading_event(logger: logging.Logger, event_type: str, message: str, **trading_fields):
    """
    Log a trading-specific event with structured fields.
    
    Args:
        logger: Logger instance
        event_type: Type of trading event (order, position, signal, etc.)
        message: Human-readable message
        **trading_fields: Trading-specific fields like symbol, quantity, price, etc.
    """
    trading_fields['event_type'] = event_type
    log_with_context(logger, 'info', message, **trading_fields)


def exception_logger(logger: logging.Logger = None):
    """
    Decorator to automatically log exceptions from functions.
    
    Args:
        logger: Logger instance, if None will use function's module logger
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            func_logger = logger or get_logger(func.__module__)
            try:
                return func(*args, **kwargs)
            except Exception as e:
                log_exception(
                    func_logger,
                    f"Exception in {func.__name__}: {str(e)}",
                    function=func.__name__,
                    args_count=len(args),
                    kwargs_keys=list(kwargs.keys()) if kwargs else []
                )
                raise
        return wrapper
    return decorator


# Convenience functions for common logging patterns
def log_api_request(logger: logging.Logger, method: str, url: str, **extra):
    """Log API request details"""
    log_with_context(logger, 'debug', f"API Request: {method} {url}", 
                    method=method, url=url, **extra)


def log_api_response(logger: logging.Logger, status_code: int, response_time_ms: float, **extra):
    """Log API response details"""
    level = 'info' if status_code < 400 else 'warning' if status_code < 500 else 'error'
    log_with_context(logger, level, f"API Response: {status_code} ({response_time_ms}ms)",
                    status_code=status_code, response_time_ms=response_time_ms, **extra)


def log_order_event(logger: logging.Logger, order_id: str, action: str, symbol: str, **extra):
    """Log order-related events"""
    log_trading_event(logger, 'order', f"Order {action}: {order_id}",
                     order_id=order_id, action=action, symbol=symbol, **extra)


def log_auth_event(logger: logging.Logger, user_id: str, event: str, success: bool, **extra):
    """Log authentication events"""
    level = 'info' if success else 'warning'
    message = f"Auth {event}: {'Success' if success else 'Failed'} for user {user_id}"
    log_with_context(logger, level, message, 
                    user_id=user_id, auth_event=event, success=success, **extra)


# Initialize logging when module is imported
try:
    OpenAlgoLogger()
except Exception as e:
    # Fallback to basic logging if initialization fails
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    logging.getLogger(__name__).error(f"Failed to initialize OpenAlgo logger: {e}")