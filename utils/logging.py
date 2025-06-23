import logging
import os
import re
from datetime import datetime, timedelta
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Optional

# Sensitive patterns to filter out
SENSITIVE_PATTERNS = [
    (r'(api[_-]?key[\s]*[=:]\s*)[\w\-]+', r'\1[REDACTED]'),
    (r'(password[\s]*[=:]\s*)[\w\-]+', r'\1[REDACTED]'),
    (r'(token[\s]*[=:]\s*)[\w\-]+', r'\1[REDACTED]'),
    (r'(secret[\s]*[=:]\s*)[\w\-]+', r'\1[REDACTED]'),
    (r'(authorization[\s]*[=:]\s*)[\w\-]+', r'\1[REDACTED]'),
    (r'(Bearer\s+)[\w\-\.]+', r'\1[REDACTED]'),
]


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
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level, logging.INFO))
    
    # Remove existing handlers
    root_logger.handlers = []
    
    # Create formatter
    formatter = logging.Formatter(log_format)
    
    # Add sensitive data filter
    sensitive_filter = SensitiveDataFilter()
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
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
        file_handler.setFormatter(formatter)
        file_handler.addFilter(sensitive_filter)
        root_logger.addHandler(file_handler)
    
    # Suppress noisy third-party loggers
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    

def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a module.
    
    Args:
        name: Module name (typically __name__)
        
    Returns:
        Logger instance configured with the module name
    """
    return logging.getLogger(name)


# Initialize logging on import
setup_logging()