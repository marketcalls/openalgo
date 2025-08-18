import logging
import os
from datetime import datetime
import pytz

class EventFilter(logging.Filter):
    """
    A custom filter to add a default 'event' to the log record if it's not present.
    It defaults to the log level name (e.g., INFO, ERROR).
    """
    def filter(self, record):
        if not hasattr(record, 'event'):
            record.event = record.levelname
        return True

def setup_logger(strategy_name, log_path, mode: str):
    """
    Sets up a logger for a specific strategy that writes to a daily, mode-specific log file.

    Args:
        strategy_name (str): The name of the strategy.
        log_path (str): The directory where log files should be stored.
        mode (str): The trading mode ('LIVE' or 'PAPER').

    Returns:
        logging.Logger: A configured logger instance.
    """
    # Ensure the log directory exists
    os.makedirs(log_path, exist_ok=True)

    # Use IST for timestamps
    ist_timezone = pytz.timezone("Asia/Kolkata")

    # Generate a dynamic, mode-specific log file name
    log_file_name = f"{strategy_name}_{mode.lower()}_{datetime.now(ist_timezone).strftime('%Y-%m-%d')}.log"
    log_file_path = os.path.join(log_path, log_file_name)

    # Create a logger
    logger = logging.getLogger(strategy_name)
    logger.setLevel(logging.INFO)

    # Avoid adding duplicate handlers if the logger is already configured
    if logger.hasHandlers():
        logger.handlers.clear()

    # Create a file handler to write to the log file
    file_handler = logging.FileHandler(log_file_path)

    # Create a custom formatter
    # The format will be: Timestamp (IST) - StrategyName - EventType - Message
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(event)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S %Z'
    )

    # Monkey-patch the formatter to use IST
    def formatTime(self, record, datefmt=None):
        ct = datetime.fromtimestamp(record.created, ist_timezone)
        if datefmt:
            s = ct.strftime(datefmt)
        else:
            t = ct.strftime(self.default_time_format)
            s = self.default_msec_format % (t, record.msecs)
        return s

    formatter.formatTime = formatTime.__get__(formatter)

    file_handler.setFormatter(formatter)

    # Add the handler and filter to the logger
    logger.addHandler(file_handler)
    logger.addFilter(EventFilter())

    # Also add a console handler for immediate feedback
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger