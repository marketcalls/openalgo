#!/usr/bin/env python
"""
Options Alpha Strategy - First 15-Min Breakout (WebSocket Version)
===================================================================

STRATEGY OVERVIEW:
------------------
A systematic momentum-based options buying strategy that trades ATM options
using a multi-level resistance-based trailing stop loss system. The strategy
captures directional moves in the first hour of trading and trails profits
using predefined resistance levels calculated at market open.

CORE CONCEPTS:
--------------
1. **Dual Timeframe Approach**:
   - 5-min candle (9:15-9:20): Calculate resistance levels (R1-R6) and BEP
   - 15-min candle (9:15-9:30): Determine ATM strike and entry levels

2. **Resistance Level System**:
   - TRUE ATM: Strike where |CE_price - PE_price| is minimum at 9:20 AM
   - BEP (Break Even Point): (ATM_CE + ATM_PE) / 2
   - R1-R6: Calculated using straddle/strangle prices at different strikes
   - Formula: R_n = ((ATM - n×gap)_CE + (ATM + n×gap)_PE) / 2
   - Example: R1 = (ATM-50_CE + ATM+50_PE) / 2 for NIFTY

3. **Entry Logic**:
   - Waits for price to break above entry level with confirmation
   - Entry level for PE: Average(PE 15min low, CE 15min high)
   - Entry level for CE: Average(CE 15min low, CE 15min high)
   - Confirmation: Current 1min candle open AND close above entry level
   - Crossover: Previous 1min candle open OR close below entry level

4. **Level-Based Trailing Stop Loss**:
   - Initial SL: 5% below entry level
   - When LTP touches R1: SL moves to R1 × (1 - 10%) = R1 × 0.90
   - When LTP touches R2: SL moves to R2 × 0.90
   - Continues for R3, R4, R5, R6
   - SL only moves UP, never down
   - Target: Entry price × 2.80 (180% profit)

TIMING & SCHEDULE:
------------------
09:15 - Market opens
09:20 - First 5-min candle closes → Calculate R1-R6 levels (STATIC for day)
09:30 - First 15-min candle closes → Calculate ATM strike & entry levels
09:31 - Strategy starts monitoring for entry conditions
14:15 - No new entries allowed after this time
15:00 - Force exit all positions
15:30 - Market closes

RISK MANAGEMENT:
----------------
- Capital: 80% of available funds per trade
- Max Trades: 2 completed trades per day (default)
- Stop Loss: 5% below entry level initially, then trails with R levels
- Target: 180% of entry price (2.80x multiplier)
- Position Sizing: Calculated based on capital and lot size
- Only one position at a time (CE or PE, whichever breaks out first)

TECHNICAL FEATURES:
-------------------
- WebSocket-first architecture with HTTP fallback for price updates
- Auto-reconnection with exponential backoff (up to 10 attempts)
- Health monitoring every 30 seconds
- Stale data detection and automatic recovery
- Crash recovery with up to 3 restart attempts
- Order verification with retry logic (3 attempts)
- Thread-safe tick data management
- 1-minute candle building from WebSocket ticks

EXAMPLE TRADE FLOW:
-------------------
09:20 AM:
  - NIFTY 5min close: 22,500
  - TRUE ATM: 22,500 (|CE-PE| is minimum here)
  - ATM_CE price: 150, ATM_PE price: 145
  - BEP: (150 + 145) / 2 = 147.50
  - R1: (22450_CE + 22550_PE) / 2 = (200 + 100) / 2 = 150.00
  - R2: (22400_CE + 22600_PE) / 2 = (250 + 60) / 2 = 155.00
  - ... R3-R6 calculated similarly

09:30 AM:
  - NIFTY 15min close: 22,510
  - ATM Strike: 22,500 (nearest 50 multiple)
  - PE Symbol: NIFTY10FEB2622500PE
  - CE Symbol: NIFTY10FEB2622500CE
  - PE 15min: Low=140, High=160
  - CE 15min: Low=145, High=165
  - PE Entry Level: (140 + 165) / 2 = 152.50
  - CE Entry Level: (145 + 165) / 2 = 155.00

09:42 AM:
  - PE LTP crosses 152.50
  - Current 1min candle: Open=153, Close=154 (both > 152.50) ✓
  - Previous 1min candle: Open=151, Close=152 (at least one < 152.50) ✓
  - Entry confirmed! Buy PE @ 154.00
  - Initial SL: 152.50 × 0.95 = 144.88
  - Target: 154.00 × 2.80 = 431.20

10:15 AM:
  - PE LTP reaches 152.00 (R1)
  - SL moves to: 150.00 × 0.90 = 135.00
  - Current PnL: Unrealized profit

10:45 AM:
  - PE LTP reaches 158.00 (R2)
  - SL moves to: 155.00 × 0.90 = 139.50
  - Locking in more profit

11:20 AM:
  - PE LTP drops to 138.00
  - SL hit at 139.50
  - Exit @ 138.00
  - PnL: (138.00 - 154.00) × 25 lots × 25 qty = Loss
  - BUT: Protected profits from R2 level

CONFIGURATION OPTIONS:
----------------------
Edit these constants at the top of the file:

INDEX = "NIFTY"                    # NIFTY, BANKNIFTY, SENSEX
EXPIRY_WEEK = 1                    # 1=current, 2=next week
CAPITAL_PERCENT = 0.80             # Use 80% of available capital
SL_PERCENT = 0.05                  # 5% initial stop loss
TARGET_MULTIPLIER = 2.80           # 180% profit target
SL_BUFFER_PERCENT = 0.10           # 10% below each R level for SL
NUM_RESISTANCE_LEVELS = 6          # R1 to R6
MAX_COMPLETED_TRADES = 2           # Max trades per day
NO_NEW_ENTRY_TIME = "14:15"        # Last entry time
FORCE_EXIT_TIME = "15:00"          # Square off time

REQUIREMENTS:
-------------
- OpenAlgo API running on http://127.0.0.1:5002 (Fyers)
- WebSocket server running on ws://127.0.0.1:8767 (Fyers)
- API key configured in ~/.config/openalgo/config.json
- Live broker connection with sufficient margin
- Market data subscription for selected index

USAGE:
------
uv run python3 nifty_optionsalpha.py

LOGS:
-----
- Console: INFO level messages
- File: logs/strategy_YYYYMMDD_HHMMSS.log (if LOG_TO_FILE=True)

Author: Generated with Claude
Version: 3.0 (Robust Reconnection + Error Handling)
Last Updated: 2026-02-05
"""

import time
import threading
import logging
import sys
import os
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, Literal, Dict, List, Callable
from enum import Enum
import traceback
from pathlib import Path
import pandas as pd
from openalgo import api


# =============================================================================
# LOGGING SETUP
# =============================================================================

class StrategyLogger:
    """Custom logger with console and optional file output"""

    def __init__(self, name: str, log_to_file: bool = False, log_dir: str = "logs"):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers = []  # Clear existing handlers

        # Console handler (only if file logging is disabled)
        if not log_to_file:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(logging.INFO)
            console_format = logging.Formatter(
                '[%(asctime)s] %(levelname)s: %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            console_handler.setFormatter(console_format)
            self.logger.addHandler(console_handler)

        # File handler
        if log_to_file:
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(
                log_dir,
                f"strategy_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            )
            file_handler = logging.FileHandler(log_file)
            file_handler.setLevel(logging.DEBUG)
            file_format = logging.Formatter(
                '[%(asctime)s] %(levelname)s [%(funcName)s:%(lineno)d]: %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            file_handler.setFormatter(file_format)
            self.logger.addHandler(file_handler)
            self.logger.info(f"Logging to file: {log_file}")

    def info(self, msg): self.logger.info(msg)
    def debug(self, msg): self.logger.debug(msg)
    def warning(self, msg): self.logger.warning(msg)
    def error(self, msg): self.logger.error(msg)
    def critical(self, msg): self.logger.critical(msg)


# =============================================================================
# CONNECTION STATE
# =============================================================================

class ConnectionState(Enum):
    """WebSocket connection states"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


# =============================================================================
# USER CONFIGURATION - EDIT THESE VALUES
# =============================================================================

# OpenAlgo API Key - loaded from central config (Fyers broker)
from pathlib import Path
sys.path.insert(0, str(Path.home() / ".config/openalgo"))
try:
    from client import get_config
    _fyers_cfg = get_config("fyers")
    API_KEY = _fyers_cfg["api_key"]
except ImportError:
    API_KEY = "YOUR_API_KEY_HERE"  # Fallback - edit ~/.config/openalgo/config.json

# OpenAlgo Server (Fyers instance)
HOST = "http://127.0.0.1:5002"
WS_URL = "ws://127.0.0.1:8767"

# Index to trade
INDEX = "NIFTY"                    # NIFTY, BANKNIFTY, SENSEX

# Expiry week (1 = current week, 2 = next week, etc.)
EXPIRY_WEEK = 1

# Capital & Position Sizing
CAPITAL_PERCENT = 0.80             # Use 80% of available capital

# Risk Management
SL_PERCENT = 0.05                  # 5% stop loss below entry level
TARGET_MULTIPLIER = 2.80           # 180% profit target (entry * 2.80)

# Trailing SL (Level-based)
SL_BUFFER_PERCENT = 0.10           # 10% below each R level for SL
NUM_RESISTANCE_LEVELS = 6          # R1 to R6

# Trading Limits
MAX_COMPLETED_TRADES = 2               # Max completed (exited) trades per day
NO_NEW_ENTRY_TIME = "14:15"            # No new entries after this time
FORCE_EXIT_TIME = "15:00"              # Force exit all positions at this time

# Excel Performance Tracking
EXCEL_LOG_FILE = "nifty_optionsalpha_performance.xlsx"  # Excel file for trade history

# Freeze Quantity (exchange limit per order)
FREEZE_QTY = 1755                          # NIFTY freeze limit

# Robustness Settings
LOG_TO_FILE = True                     # Enable file logging
LOG_DIR = "logs"                       # Log directory
MAX_RECONNECT_ATTEMPTS = 10            # Max WebSocket reconnection attempts
RECONNECT_BASE_DELAY = 2               # Initial reconnect delay (seconds)
RECONNECT_MAX_DELAY = 60               # Max reconnect delay (seconds)
HEALTH_CHECK_INTERVAL = 30             # Check connection health every N seconds
STALE_DATA_THRESHOLD = 60              # Data older than N seconds = stale
AUTO_RESTART_ON_CRASH = True           # Auto-restart strategy on crash
MAX_CRASH_RESTARTS = 3                 # Max restarts before giving up

# =============================================================================


@dataclass
class Config:
    """Strategy configuration - uses top-level constants as defaults"""

    # Index Settings
    INDEX: str = INDEX
    INDEX_EXCHANGE: str = "NSE_INDEX"       # Auto-set based on INDEX
    OPTIONS_EXCHANGE: str = "NFO"           # Auto-set based on INDEX
    STRIKE_INTERVAL: int = 50               # Auto-set based on INDEX

    # Expiry & Capital (from top-level config)
    EXPIRY_WEEK: int = EXPIRY_WEEK
    CAPITAL_PERCENT: float = CAPITAL_PERCENT

    # Risk Management (from top-level config)
    SL_PERCENT: float = SL_PERCENT
    TARGET_MULTIPLIER: float = TARGET_MULTIPLIER
    SL_BUFFER_PERCENT: float = SL_BUFFER_PERCENT
    NUM_RESISTANCE_LEVELS: int = NUM_RESISTANCE_LEVELS
    MAX_COMPLETED_TRADES: int = MAX_COMPLETED_TRADES

    # Timing (IST) - usually don't need to change
    MARKET_OPEN: str = "09:15"
    FIRST_CANDLE_CLOSE: str = "09:30"
    MARKET_CLOSE: str = "15:30"
    NO_NEW_ENTRY_TIME: str = NO_NEW_ENTRY_TIME
    FORCE_EXIT_TIME: str = FORCE_EXIT_TIME

    # Strategy Name
    STRATEGY_NAME: str = "OptionsAlpha"


# Index-specific configurations (for scalability)
INDEX_CONFIG = {
    "NIFTY": {
        "index_exchange": "NSE_INDEX",
        "options_exchange": "NFO",
        "strike_interval": 50,
        "lot_size": 65  # Fallback, actual fetched from API
    },
    "BANKNIFTY": {
        "index_exchange": "NSE_INDEX",
        "options_exchange": "NFO",
        "strike_interval": 100,
        "lot_size": 30
    },
    "SENSEX": {
        "index_exchange": "BSE_INDEX",
        "options_exchange": "BFO",
        "strike_interval": 100,
        "lot_size": 20
    }
}


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class EntryLevels:
    """Calculated entry levels for the day"""
    atm_strike: int
    pe_symbol: str
    ce_symbol: str
    pe_entry_level: float
    ce_entry_level: float
    expiry_date: str
    lot_size: int


@dataclass
class ResistanceLevels:
    """Resistance levels calculated at 9:20 AM (static for the day)"""
    bep: float                      # Break Even Point (reference)
    r1: float                       # Resistance level 1
    r2: float                       # Resistance level 2
    r3: float                       # Resistance level 3
    r4: float                       # Resistance level 4
    r5: float                       # Resistance level 5
    r6: float                       # Resistance level 6
    true_atm: int                   # True ATM strike used for calculation
    calculated_at: datetime         # When levels were calculated

    def get_level(self, n: int) -> float:
        """Get resistance level by number (1-6)"""
        return getattr(self, f"r{n}", 0.0)

    def get_all_levels(self) -> List[float]:
        """Get all R levels as sorted list"""
        return [self.r1, self.r2, self.r3, self.r4, self.r5, self.r6]


@dataclass
class Position:
    """Active position tracking"""
    option_type: Literal["CE", "PE"]
    symbol: str
    entry_price: float
    quantity: int
    sl_price: float
    target_price: float
    entry_time: datetime
    order_ids: List[str]           # Entry order IDs (multiple if split)
    cost_basis: float              # Total cost for PnL calculation
    current_r_level: int = 0       # Current R level reached (0 = none, 1 = R1, etc.)


@dataclass
class TickData:
    """Real-time tick data for a symbol"""
    symbol: str
    ltp: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)


# =============================================================================
# REAL-TIME TICK MANAGER (WebSocket) - WITH ROBUST RECONNECTION
# =============================================================================

class TickManager:
    """Manages real-time tick data via WebSocket with auto-reconnection"""

    def __init__(self, client: api, config: Config, logger: StrategyLogger):
        self.client = client
        self.config = config
        self.logger = logger
        self.ticks: Dict[str, TickData] = {}
        self.lock = threading.Lock()

        # Connection state management
        self.state = ConnectionState.DISCONNECTED
        self.subscribed_symbols: List[dict] = []
        self.reconnect_attempts = 0
        self.last_tick_time: Optional[datetime] = None

        # Background threads
        self._health_check_thread: Optional[threading.Thread] = None
        self._stop_health_check = threading.Event()

        # Callbacks
        self.on_reconnect_callback: Optional[Callable] = None
        self.on_disconnect_callback: Optional[Callable] = None

    def on_tick(self, data: dict):
        """Callback for WebSocket tick updates"""
        try:
            symbol = data.get("symbol")
            market_data = data.get("data", {})
            ltp = float(market_data.get("ltp", 0))
            if symbol and ltp > 0:
                self._update_tick(symbol, ltp)
                self.last_tick_time = datetime.now()
        except Exception as e:
            self.logger.error(f"[TickManager] Error processing tick: {e}")

    def _update_tick(self, symbol: str, ltp: float):
        """Update LTP for a symbol"""
        with self.lock:
            if symbol not in self.ticks:
                self.ticks[symbol] = TickData(symbol=symbol)
            tick = self.ticks[symbol]
            tick.ltp = ltp
            tick.timestamp = datetime.now()

    def get_ltp(self, symbol: str) -> float:
        """Get current LTP for a symbol"""
        with self.lock:
            tick = self.ticks.get(symbol)
            return tick.ltp if tick else 0.0

    def get_tick_age(self, symbol: str) -> float:
        """Get age of last tick in seconds"""
        with self.lock:
            tick = self.ticks.get(symbol)
            if tick and tick.timestamp:
                return (datetime.now() - tick.timestamp).total_seconds()
            return float('inf')

    def is_data_stale(self) -> bool:
        """Check if data is stale (no recent ticks)"""
        if not self.last_tick_time:
            return True
        age = (datetime.now() - self.last_tick_time).total_seconds()
        return age > STALE_DATA_THRESHOLD

    def subscribe(self, symbols: List[dict]) -> bool:
        """Subscribe to symbols via WebSocket with retry logic"""
        self.subscribed_symbols = symbols
        return self._connect_and_subscribe()

    def _connect_and_subscribe(self) -> bool:
        """Internal method to connect and subscribe"""
        self.state = ConnectionState.CONNECTING
        try:
            self.client.connect()
            self.client.subscribe_ltp(
                self.subscribed_symbols,
                on_data_received=self.on_tick
            )
            self.state = ConnectionState.CONNECTED
            self.reconnect_attempts = 0
            self.logger.info(f"[TickManager] Connected and subscribed to {len(self.subscribed_symbols)} symbols")

            # Start health check thread
            self._start_health_check()
            return True

        except Exception as e:
            self.logger.error(f"[TickManager] Connection error: {e}")
            self.state = ConnectionState.DISCONNECTED
            return False

    def reconnect(self) -> bool:
        """Attempt to reconnect with exponential backoff (iterative, not recursive)"""
        if self.state == ConnectionState.RECONNECTING:
            return False

        self.state = ConnectionState.RECONNECTING

        # Iterative reconnection to avoid stack overflow
        while self.reconnect_attempts < MAX_RECONNECT_ATTEMPTS:
            self.reconnect_attempts += 1

            # Calculate delay with exponential backoff
            delay = min(
                RECONNECT_BASE_DELAY * (2 ** (self.reconnect_attempts - 1)),
                RECONNECT_MAX_DELAY
            )

            self.logger.warning(
                f"[TickManager] Reconnecting in {delay}s (attempt {self.reconnect_attempts}/{MAX_RECONNECT_ATTEMPTS})"
            )
            time.sleep(delay)

            # Try to disconnect cleanly first
            try:
                self.client.disconnect()
            except Exception:
                pass

            # Attempt reconnection
            if self._connect_and_subscribe():
                self.logger.info("[TickManager] Reconnection successful!")
                if self.on_reconnect_callback:
                    self.on_reconnect_callback()
                return True
            else:
                self.logger.error(f"[TickManager] Reconnection attempt {self.reconnect_attempts} failed")

        # All attempts exhausted
        self.logger.critical(f"[TickManager] Max reconnection attempts ({MAX_RECONNECT_ATTEMPTS}) exceeded")
        self.state = ConnectionState.FAILED
        return False

    def _start_health_check(self):
        """Start background health check thread (only if not already running)"""
        # Prevent multiple health check threads
        if self._health_check_thread and self._health_check_thread.is_alive():
            return

        self._stop_health_check.clear()
        self._health_check_thread = threading.Thread(
            target=self._health_check_loop,
            daemon=True
        )
        self._health_check_thread.start()

    def _health_check_loop(self):
        """Background loop to check connection health"""
        while not self._stop_health_check.is_set():
            time.sleep(HEALTH_CHECK_INTERVAL)

            if self._stop_health_check.is_set():
                break

            # Check if data is stale
            if self.state == ConnectionState.CONNECTED and self.is_data_stale():
                self.logger.warning("[TickManager] Stale data detected, triggering reconnection")
                if self.on_disconnect_callback:
                    self.on_disconnect_callback()
                self.reconnect()

    def unsubscribe(self, symbols: List[dict]):
        """Unsubscribe from symbols"""
        try:
            self.client.unsubscribe_ltp(symbols)
        except Exception as e:
            self.logger.error(f"[TickManager] Unsubscribe error: {e}")

    def disconnect(self):
        """Disconnect WebSocket and cleanup"""
        self._stop_health_check.set()

        try:
            self.client.disconnect()
            self.state = ConnectionState.DISCONNECTED
            self.logger.info("[TickManager] Disconnected")
        except Exception as e:
            self.logger.error(f"[TickManager] Disconnect error: {e}")

    @property
    def connected(self) -> bool:
        """Check if currently connected"""
        return self.state == ConnectionState.CONNECTED


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def is_trading_day(client: api) -> tuple[bool, str]:
    """
    Check if today is a trading day.
    Returns: (is_trading: bool, message: str)

    Note: Checks market timings API first to handle special trading days
    (e.g., Union Budget day on weekends). Weekend check is only used as fallback.
    """
    today = datetime.now()
    is_weekend = today.weekday() >= 5  # Saturday = 5, Sunday = 6

    # Check market timings API first (handles special trading days like Budget day)
    try:
        result = client.timings(date=today.strftime("%Y-%m-%d"))
        if result.get("status") == "success":
            data = result.get("data", [])
            if not data:
                # No exchange data = holiday or market closed
                if is_weekend:
                    return False, "Weekend - Market closed"
                return False, "Holiday - Market closed"

            # Check if NSE/NFO is open
            for exchange in data:
                if exchange.get("exchange") in ["NSE", "NFO"]:
                    if is_weekend:
                        return True, "Special trading day (market open on weekend)"
                    return True, "Trading day"

            return False, "NSE/NFO not open today"
    except Exception as e:
        # If API fails, fail-safe: don't trade on uncertain days
        print(f"Warning: Could not check market timings: {e}")
        if is_weekend:
            return False, "Weekend - Market closed (API check failed)"
        # FAIL-SAFE: Don't trade if we can't confirm it's a trading day
        return False, "Cannot confirm trading day (API check failed) - not trading to be safe"

    return True, "Trading day"


def round_to_tick(price: float, tick_size: float = 0.05) -> float:
    """
    Round price to nearest tick size (default 0.05 for options).

    Examples:
        round_to_tick(245.23) → 245.25
        round_to_tick(245.21) → 245.20
        round_to_tick(245.00) → 245.00
    """
    return round(round(price / tick_size) * tick_size, 2)


def get_expiry_date(client: api, index: str, exchange: str, expiry_week: int) -> str:
    """
    Get expiry date based on expiry_week parameter.
    expiry_week: 1 = current/nearest, 2 = next week, etc.
    Returns date in DDMMMYY format (e.g., 28NOV25)
    """
    result = client.expiry(
        symbol=index,
        exchange=exchange,
        instrumenttype="options"
    )

    if result.get("status") != "success":
        raise Exception(f"Failed to fetch expiry dates: {result.get('message')}")

    expiry_dates = result.get("data", [])
    if not expiry_dates:
        raise Exception("No expiry dates available")

    # expiry_dates are sorted, pick based on expiry_week
    idx = min(expiry_week - 1, len(expiry_dates) - 1)

    # Skip expiry day — if nearest expiry is today, use next week's
    today_str = datetime.now().strftime("%d-%b-%y").upper()  # e.g., 10-FEB-26
    if expiry_dates[idx].upper() == today_str and len(expiry_dates) > idx + 1:
        idx += 1

    # Expiry API returns DD-MMM-YY (e.g., 10-FEB-26) but optionsymbol API
    # expects DDMMMYY (e.g., 10FEB26) — strip hyphens
    return expiry_dates[idx].replace("-", "")


def build_option_symbol(index: str, expiry_date: str, strike: int, option_type: str) -> str:
    """
    Build option symbol in OpenAlgo format.
    Example: NIFTY28NOV2526000CE

    Note: This is only used for resistance level calculation where we need to
    build multiple symbols (20+ API calls would be slow). For main entry level
    calculation, use optionsymbol() API instead.
    """
    return f"{index}{expiry_date}{strike}{option_type}"


def get_5min_candle_close(client: api, symbol: str, exchange: str) -> float:
    """
    Fetch the first 5-minute candle close (9:15-9:20).
    Returns: close price
    """
    today = datetime.now().strftime("%Y-%m-%d")

    df = client.history(
        symbol=symbol,
        exchange=exchange,
        interval="5m",
        start_date=today,
        end_date=today
    )

    if isinstance(df, dict) and df.get("status") == "error":
        raise Exception(f"Failed to fetch 5min candle: {df.get('message')}")

    if df is None or df.empty:
        raise Exception(f"No 5min candle data for {symbol}")

    # Get the first candle (9:15-9:20)
    first_candle = df.iloc[0]
    return float(first_candle["close"])


def calculate_resistance_levels(
    client: api,
    index: str,
    index_exchange: str,
    options_exchange: str,
    strike_interval: int,
    expiry_date: str,
    num_levels: int = 6
) -> ResistanceLevels:
    """
    Calculate resistance levels (R1-R6) at 9:20 AM using first 5-min candle close.

    Formula:
    - TRUE_ATM = strike where |CE_close - PE_close| is minimum
    - BEP = (ATM_CE + ATM_PE) / 2
    - R1 = ((ATM-1*gap)_CE + (ATM+1*gap)_PE) / 2
    - R2 = ((ATM-2*gap)_CE + (ATM+2*gap)_PE) / 2
    - ...and so on for R3-R6

    Returns: ResistanceLevels dataclass with bep, r1-r6, true_atm
    """
    # Step 1: Get spot price from first 5-min candle
    spot_close = get_5min_candle_close(client, index, index_exchange)
    print(f"[Levels] {index} spot (5min close): {spot_close}")

    # Step 2: Get approximate ATM
    approx_atm = int(round(spot_close / strike_interval)) * strike_interval
    print(f"[Levels] Approximate ATM: {approx_atm}")

    # Step 3: Build option symbols for strikes around ATM
    # We need strikes from (ATM - 2*gap) to (ATM + num_levels*gap) for finding true ATM and calculating levels
    strikes_needed = []
    for offset in range(-2, num_levels + 3):  # Extra buffer for true ATM search
        strikes_needed.append(approx_atm + (offset * strike_interval))

    # Step 4: Fetch 5-min close prices for all required options
    option_prices = {}  # {strike_CE: price, strike_PE: price}

    for strike in strikes_needed:
        ce_symbol = build_option_symbol(index, expiry_date, strike, "CE")
        pe_symbol = build_option_symbol(index, expiry_date, strike, "PE")

        try:
            ce_close = get_5min_candle_close(client, ce_symbol, options_exchange)
            option_prices[f"{strike}_CE"] = ce_close
        except Exception as e:
            print(f"[Levels] Warning: Could not get CE price for {strike}: {e}")
            option_prices[f"{strike}_CE"] = 0.0

        try:
            pe_close = get_5min_candle_close(client, pe_symbol, options_exchange)
            option_prices[f"{strike}_PE"] = pe_close
        except Exception as e:
            print(f"[Levels] Warning: Could not get PE price for {strike}: {e}")
            option_prices[f"{strike}_PE"] = 0.0

    # Step 5: Find TRUE ATM (strike where |CE - PE| is minimum)
    min_diff = float('inf')
    true_atm = approx_atm

    for offset in range(-2, 3):  # Check ±2 strikes from approx ATM
        strike = approx_atm + (offset * strike_interval)
        ce_price = option_prices.get(f"{strike}_CE", 0)
        pe_price = option_prices.get(f"{strike}_PE", 0)

        if ce_price > 0 and pe_price > 0:
            diff = abs(ce_price - pe_price)
            if diff < min_diff:
                min_diff = diff
                true_atm = strike

    print(f"[Levels] TRUE ATM: {true_atm} (diff: {min_diff:.2f})")

    # Step 6: Calculate BEP
    atm_ce = option_prices.get(f"{true_atm}_CE", 0)
    atm_pe = option_prices.get(f"{true_atm}_PE", 0)
    bep = (atm_ce + atm_pe) / 2.0
    print(f"[Levels] BEP: {bep:.2f} (ATM_CE: {atm_ce:.2f}, ATM_PE: {atm_pe:.2f})")

    # Step 7: Calculate R1-R6
    # R_n = ((ATM - n*gap)_CE + (ATM + n*gap)_PE) / 2
    r_levels = []
    for i in range(1, num_levels + 1):
        ce_strike = true_atm - (i * strike_interval)  # Lower strike CE (more expensive)
        pe_strike = true_atm + (i * strike_interval)  # Higher strike PE (more expensive)

        ce_price = option_prices.get(f"{ce_strike}_CE", 0)
        pe_price = option_prices.get(f"{pe_strike}_PE", 0)

        r_value = (ce_price + pe_price) / 2.0
        r_levels.append(round_to_tick(r_value))
        print(f"[Levels] R{i}: {round_to_tick(r_value):.2f} (CE@{ce_strike}: {ce_price:.2f}, PE@{pe_strike}: {pe_price:.2f})")

    # Pad with zeros if needed
    while len(r_levels) < 6:
        r_levels.append(0.0)

    return ResistanceLevels(
        bep=round_to_tick(bep),
        r1=r_levels[0],
        r2=r_levels[1],
        r3=r_levels[2],
        r4=r_levels[3],
        r5=r_levels[4],
        r6=r_levels[5],
        true_atm=true_atm,
        calculated_at=datetime.now()
    )


def get_15min_candle(client: api, symbol: str, exchange: str) -> dict:
    """
    Fetch the first 15-minute candle (9:15-9:30).
    Returns: {open, high, low, close}
    """
    today = datetime.now().strftime("%Y-%m-%d")

    df = client.history(
        symbol=symbol,
        exchange=exchange,
        interval="15m",
        start_date=today,
        end_date=today
    )

    if isinstance(df, dict) and df.get("status") == "error":
        raise Exception(f"Failed to fetch 15min candle: {df.get('message')}")

    if df.empty:
        raise Exception(f"No 15min candle data for {symbol}")

    # Get the first candle (9:15-9:30)
    first_candle = df.iloc[0]
    return {
        "open": float(first_candle["open"]),
        "high": float(first_candle["high"]),
        "low": float(first_candle["low"]),
        "close": float(first_candle["close"])
    }


def calculate_quantity(capital: float, price: float, lot_size: int) -> int:
    """
    Calculate quantity based on capital and lot size.

    Returns 0 if insufficient capital or invalid inputs.
    """
    if price <= 0 or lot_size <= 0 or capital <= 0:
        return 0

    max_lots = int(capital / (price * lot_size))

    if max_lots < 1:
        return 0  # Insufficient capital for even 1 lot

    return max_lots * lot_size


def check_entry_condition(
    ltp: float,
    candles: "pd.DataFrame",
    entry_level: float
) -> bool:
    """
    Check entry condition using LTP (WebSocket) + 1-min candles (API):
    1. LTP > entry_level
    2. Last COMPLETED candle [-2]: open AND close > entry_level
    3. Candle before that [-3]: open OR close < entry_level (crossover)

    Note: [-1] is the in-progress candle (broker may include it) — skip it.
    """
    # WebSocket LTP must be above entry level
    if ltp <= 0 or ltp <= entry_level:
        return False

    # Need at least 3 candles ([-1] is in-progress, we use [-2] and [-3])
    if len(candles) < 3:
        return False

    # [-2] (last completed candle): open AND close above entry level
    latest = candles.iloc[-2]
    if not (latest["open"] > entry_level and latest["close"] > entry_level):
        return False

    # [-3] (candle before): open OR close below entry level (crossover)
    prev = candles.iloc[-3]
    if not (prev["open"] < entry_level or prev["close"] < entry_level):
        return False

    return True


# =============================================================================
# MAIN STRATEGY CLASS
# =============================================================================

class OptionsAlphaStrategy:
    """Main strategy class with WebSocket support and robust error handling"""

    def __init__(self, config: Config):
        self.config = config

        # Setup logger first
        self.logger = StrategyLogger(
            name=config.STRATEGY_NAME,
            log_to_file=LOG_TO_FILE,
            log_dir=LOG_DIR
        )

        self.client = api(
            api_key=API_KEY,
            host=HOST,
            ws_url=WS_URL
        )

        # Load index-specific config
        idx_config = INDEX_CONFIG.get(config.INDEX, INDEX_CONFIG["NIFTY"])
        self.index_exchange = idx_config["index_exchange"]
        self.options_exchange = idx_config["options_exchange"]
        self.strike_interval = idx_config["strike_interval"]

        # Tick manager for WebSocket (with logger)
        self.tick_manager = TickManager(self.client, config, self.logger)

        # Set reconnection callbacks
        self.tick_manager.on_reconnect_callback = self._on_ws_reconnect
        self.tick_manager.on_disconnect_callback = self._on_ws_disconnect

        # State
        self.resistance_levels: Optional[ResistanceLevels] = None
        self.entry_levels: Optional[EntryLevels] = None
        self.position: Optional[Position] = None
        self.completed_trades: int = self._get_todays_completed_trades()
        self.can_trade: bool = self.completed_trades < self.config.MAX_COMPLETED_TRADES
        self.daily_pnl: float = 0.0
        self.trades_dict: dict = {}          # Key: entry_order_id, Value: complete trade info
        self.subscribed_symbols: List[dict] = []

        # 1-min candle cache (fetched from API, refreshed every 5 seconds)
        self._candle_cache: Dict[str, "pd.DataFrame"] = {}
        self._candle_cache_time: float = 0.0

        # Crash recovery state
        self.crash_count: int = 0
        self.running: bool = False

    def log(self, message: str):
        """Log message with timestamp"""
        self.logger.info(message)

    def get_1m_candles(self, symbol: str) -> "pd.DataFrame":
        """
        Get 1-min candles from history API with 5-second TTL cache.
        Avoids stale data from minute-boundary fetches where the broker
        API hasn't yet finalized the previous candle.
        """
        now = time.time()

        if now - self._candle_cache_time >= 5:
            # Cache expired — clear for fresh fetch
            self._candle_cache.clear()
            self._candle_cache_time = now

        if symbol in self._candle_cache:
            return self._candle_cache[symbol]

        today = datetime.now().strftime("%Y-%m-%d")
        df = self.client.history(
            symbol=symbol,
            exchange=self.options_exchange,
            interval="1m",
            start_date=today,
            end_date=today
        )

        if isinstance(df, dict) and df.get("status") == "error":
            self.logger.warning(f"Failed to fetch 1m candles for {symbol}: {df.get('message')}")
            df = pd.DataFrame()

        self._candle_cache[symbol] = df
        return df

    def _get_todays_completed_trades(self) -> int:
        """Read Excel trade log and count how many trades were completed today."""
        try:
            excel_file = Path(EXCEL_LOG_FILE)
            if not excel_file.exists():
                return 0
            df = pd.read_excel(excel_file, engine='openpyxl')
            if df.empty or "Date" not in df.columns:
                return 0
            today = datetime.now().strftime("%Y-%m-%d")
            today_trades = df[df["Date"].astype(str) == today]
            count = len(today_trades)
            if count > 0:
                self.log(f"Resuming: found {count} completed trade(s) today in Excel log")
            return count
        except Exception as e:
            self.logger.warning(f"Could not read trade history from Excel: {e}")
            return 0

    def log_trade_to_excel(self, trade_data: dict):
        """
        Log trade details to Excel file for long-term performance tracking.
        Creates file if it doesn't exist, appends new row otherwise.

        Args:
            trade_data: Dictionary with complete trade information
        """
        try:
            excel_file = Path(EXCEL_LOG_FILE)

            # Prepare row data with 9:30 calculated levels + trade execution details
            row_data = {
                "Date": datetime.now().strftime("%Y-%m-%d"),
                "ATM Strike": self.entry_levels.atm_strike if self.entry_levels else "",
                "PE Symbol": self.entry_levels.pe_symbol if self.entry_levels else "",
                "PE Entry Level": self.entry_levels.pe_entry_level if self.entry_levels else "",
                "CE Symbol": self.entry_levels.ce_symbol if self.entry_levels else "",
                "CE Entry Level": self.entry_levels.ce_entry_level if self.entry_levels else "",
                "Expiry": self.entry_levels.expiry_date if self.entry_levels else "",
                "Entry Order ID": trade_data.get("entry_order_id", ""),
                "Exit Order ID": trade_data.get("exit_order_id", ""),
                "Trade Type": trade_data.get("option_type", ""),
                "Traded Symbol": trade_data.get("symbol", ""),
                "Entry Time": trade_data.get("entry_time", ""),
                "Entry Price": trade_data.get("entry_price", 0.0),
                "Initial SL": trade_data.get("initial_sl", 0.0),
                "Target Price": trade_data.get("target_price", 0.0),
                "Exit Time": trade_data.get("exit_time", ""),
                "Exit Price": trade_data.get("exit_price", 0.0),
                "Final SL": trade_data.get("final_sl", 0.0),
                "Quantity": trade_data.get("quantity", 0),
                "PnL": trade_data.get("pnl", 0.0),
                "Exit Reason": trade_data.get("exit_reason", ""),
                "R Level Reached": trade_data.get("r_level_reached", 0)
            }

            # Convert to DataFrame
            new_row_df = pd.DataFrame([row_data])

            # Append to existing file or create new one
            if excel_file.exists():
                # Read existing data
                existing_df = pd.read_excel(excel_file, engine='openpyxl')
                # Append new row
                updated_df = pd.concat([existing_df, new_row_df], ignore_index=True)
            else:
                # Create new file
                updated_df = new_row_df

            # Write to Excel
            updated_df.to_excel(excel_file, index=False, engine='openpyxl')
            self.logger.debug(f"Trade logged to Excel: {excel_file}")

        except Exception as e:
            self.logger.error(f"Failed to log trade to Excel: {e}")
            # Don't raise - Excel logging failure shouldn't stop the strategy

    def _on_ws_reconnect(self):
        """Callback when WebSocket reconnects"""
        self.log("WebSocket reconnected - resuming strategy")

    def _on_ws_disconnect(self):
        """Callback when WebSocket disconnects"""
        self.log("WebSocket disconnected - will attempt reconnection")

    def is_market_hours(self) -> tuple[bool, str]:
        """
        Check if we're within tradeable market hours.
        Returns: (can_trade: bool, message: str)
        """
        now = datetime.now()
        today_str = now.strftime('%Y-%m-%d')

        market_open = datetime.strptime(f"{today_str} {self.config.MARKET_OPEN}", "%Y-%m-%d %H:%M")
        market_close = datetime.strptime(f"{today_str} {self.config.MARKET_CLOSE}", "%Y-%m-%d %H:%M")

        if now > market_close:
            return False, f"Market is closed for today (closes at {self.config.MARKET_CLOSE})"
        elif now < market_open:
            return True, f"Market not yet open (opens at {self.config.MARKET_OPEN})"
        else:
            return True, "Market is open"

    def wait_for_market_open(self):
        """Wait until market opens (called only if market not yet closed)"""
        self.log(f"Waiting for market open at {self.config.MARKET_OPEN}...")

        while True:
            now = datetime.now()
            market_open = datetime.strptime(
                f"{now.strftime('%Y-%m-%d')} {self.config.MARKET_OPEN}",
                "%Y-%m-%d %H:%M"
            )

            if now >= market_open:
                break

            time.sleep(10)

        self.log("Market is open!")

    def wait_for_5min_candle_and_calculate_levels(self):
        """Wait for first 5-min candle (9:20) and calculate R1-R6 levels"""
        self.log("Waiting for first 5-min candle to close at 09:20...")

        while True:
            now = datetime.now()
            candle_close = datetime.strptime(
                f"{now.strftime('%Y-%m-%d')} 09:20",
                "%Y-%m-%d %H:%M"
            )

            if now >= candle_close:
                break

            time.sleep(5)

        # Wait a bit for data to be available
        time.sleep(5)
        self.log("First 5-min candle closed! Calculating resistance levels...")

        # Get expiry date first (needed for level calculation)
        expiry_date = get_expiry_date(
            self.client,
            self.config.INDEX,
            self.options_exchange,
            self.config.EXPIRY_WEEK
        )
        self.log(f"Using expiry: {expiry_date}")

        # Calculate resistance levels
        self.resistance_levels = calculate_resistance_levels(
            client=self.client,
            index=self.config.INDEX,
            index_exchange=self.index_exchange,
            options_exchange=self.options_exchange,
            strike_interval=self.strike_interval,
            expiry_date=expiry_date,
            num_levels=self.config.NUM_RESISTANCE_LEVELS
        )

        self.log("=" * 50)
        self.log("RESISTANCE LEVELS (Static for today)")
        self.log("=" * 50)
        self.log(f"TRUE ATM: {self.resistance_levels.true_atm}")
        self.log(f"BEP: {self.resistance_levels.bep:.2f}")
        self.log(f"R1: {self.resistance_levels.r1:.2f}")
        self.log(f"R2: {self.resistance_levels.r2:.2f}")
        self.log(f"R3: {self.resistance_levels.r3:.2f}")
        self.log(f"R4: {self.resistance_levels.r4:.2f}")
        self.log(f"R5: {self.resistance_levels.r5:.2f}")
        self.log(f"R6: {self.resistance_levels.r6:.2f}")
        self.log("=" * 50)

    def wait_for_first_candle(self):
        """Wait for first 15-min candle to complete (9:30)"""
        self.log(f"Waiting for first 15-min candle to close at {self.config.FIRST_CANDLE_CLOSE}...")

        while True:
            now = datetime.now()
            candle_close = datetime.strptime(
                f"{now.strftime('%Y-%m-%d')} {self.config.FIRST_CANDLE_CLOSE}",
                "%Y-%m-%d %H:%M"
            )

            if now >= candle_close:
                break

            time.sleep(5)

        # Wait a bit more for data to be available
        time.sleep(10)
        self.log("First 15-min candle closed!")

    def calculate_entry_levels(self) -> EntryLevels:
        """Calculate ATM strike and entry levels using 9:30 candle close (static for the day)"""
        self.log("Calculating entry levels...")

        # Get expiry date
        expiry_date = get_expiry_date(
            self.client,
            self.config.INDEX,
            self.options_exchange,
            self.config.EXPIRY_WEEK
        )
        self.log(f"Expiry Date: {expiry_date}")

        # Get index first 15-min candle to determine ATM from 9:30 close (not live price)
        today = datetime.now().strftime("%Y-%m-%d")
        index_df = self.client.history(
            symbol=self.config.INDEX,
            exchange=self.index_exchange,
            interval="15m",
            start_date=today,
            end_date=today
        )
        if isinstance(index_df, dict) and index_df.get("status") == "error":
            raise Exception(f"Failed to fetch index 15m candle: {index_df.get('message')}")
        if hasattr(index_df, 'empty') and index_df.empty:
            raise Exception("No index 15m candle data")

        spot_at_930 = float(index_df.iloc[0]["close"])
        atm_strike = round(spot_at_930 / self.strike_interval) * self.strike_interval

        # Build symbols from fixed 9:30 ATM strike
        pe_symbol = build_option_symbol(self.config.INDEX, expiry_date, atm_strike, "PE")
        ce_symbol = build_option_symbol(self.config.INDEX, expiry_date, atm_strike, "CE")

        # Get lot size from optionsymbol API
        pe_result = self.client.optionsymbol(
            underlying=self.config.INDEX,
            exchange=self.index_exchange,
            expiry_date=expiry_date,
            offset="ATM",
            option_type="PE"
        )
        lot_size = pe_result.get("lotsize", INDEX_CONFIG.get(self.config.INDEX, {}).get("lot_size", 1))

        self.log(f"ATM Strike: {atm_strike} (9:30 close: {spot_at_930:.2f})")
        self.log(f"PE Symbol: {pe_symbol}")
        self.log(f"CE Symbol: {ce_symbol}")
        self.log(f"Lot Size: {lot_size}")

        # Get first 15-min candle for PE and CE
        pe_candle = get_15min_candle(self.client, pe_symbol, self.options_exchange)
        ce_candle = get_15min_candle(self.client, ce_symbol, self.options_exchange)

        self.log(f"PE 15-min candle: Low={pe_candle['low']}, High={pe_candle['high']}")
        self.log(f"CE 15-min candle: Low={ce_candle['low']}, High={ce_candle['high']}")

        # Calculate entry levels
        # PE_entry_level = Avg(PE 15min low, CE 15min high)
        pe_entry_level = (pe_candle["low"] + ce_candle["high"]) / 2

        # CE_entry_level = Avg(CE 15min low, PE 15min high)
        ce_entry_level = (ce_candle["low"] + pe_candle["high"]) / 2

        self.log(f"PE Entry Level: {pe_entry_level:.2f}")
        self.log(f"CE Entry Level: {ce_entry_level:.2f}")

        return EntryLevels(
            atm_strike=atm_strike,
            pe_symbol=pe_symbol,
            ce_symbol=ce_symbol,
            pe_entry_level=pe_entry_level,
            ce_entry_level=ce_entry_level,
            expiry_date=expiry_date,
            lot_size=lot_size
        )

    def setup_websocket(self):
        """Setup WebSocket subscription for PE and CE symbols"""
        self.log("Setting up WebSocket connection...")

        self.subscribed_symbols = [
            {"exchange": self.options_exchange, "symbol": self.entry_levels.pe_symbol},
            {"exchange": self.options_exchange, "symbol": self.entry_levels.ce_symbol}
        ]

        self.tick_manager.subscribe(self.subscribed_symbols)

        # Wait for initial ticks
        self.log("Waiting for initial tick data...")
        time.sleep(3)

        # Verify we're receiving data
        pe_ltp = self.tick_manager.get_ltp(self.entry_levels.pe_symbol)
        ce_ltp = self.tick_manager.get_ltp(self.entry_levels.ce_symbol)
        self.log(f"Initial LTP - PE: {pe_ltp:.2f}, CE: {ce_ltp:.2f}")

    def cleanup_websocket(self):
        """Cleanup WebSocket connection"""
        if self.subscribed_symbols:
            self.tick_manager.unsubscribe(self.subscribed_symbols)
        self.tick_manager.disconnect()

    def get_available_capital(self) -> float:
        """Get available capital from account"""
        result = self.client.funds()
        if result.get("status") == "success":
            available = float(result.get("data", {}).get("availablecash", 0))
            return available * self.config.CAPITAL_PERCENT
        return 0.0

    def get_ltp_http(self, symbol: str, exchange: str) -> float:
        """
        Get LTP via HTTP API (fallback when WebSocket unavailable).

        Args:
            symbol: Trading symbol
            exchange: Exchange (NFO, NSE, etc.)

        Returns:
            LTP price or 0.0 if failed
        """
        try:
            result = self.client.quotes(symbol=symbol, exchange=exchange)
            if result.get("status") == "success":
                ltp = float(result.get("data", {}).get("ltp", 0))
                return ltp
        except Exception as e:
            self.logger.error(f"HTTP LTP fetch failed for {symbol}: {e}")
        return 0.0

    def get_ltp_with_fallback(self, symbol: str, exchange: str = None) -> float:
        """
        Get LTP with WebSocket primary and HTTP fallback.

        Priority:
        1. WebSocket (if connected and data fresh)
        2. HTTP API (fallback)

        Args:
            symbol: Trading symbol
            exchange: Exchange (defaults to options_exchange)

        Returns:
            LTP price or 0.0 if all methods fail
        """
        exchange = exchange or self.options_exchange

        # Try WebSocket first (if connected and data is fresh)
        if self.tick_manager.connected:
            ws_ltp = self.tick_manager.get_ltp(symbol)
            tick_age = self.tick_manager.get_tick_age(symbol)

            # Use WebSocket data if fresh (< 5 seconds old)
            if ws_ltp > 0 and tick_age < 5:
                return ws_ltp

            # WebSocket data is stale, log warning
            if ws_ltp > 0:
                self.logger.warning(f"WebSocket data stale ({tick_age:.1f}s), using HTTP fallback")

        # Fallback to HTTP
        http_ltp = self.get_ltp_http(symbol, exchange)
        if http_ltp > 0:
            self.logger.debug(f"HTTP LTP for {symbol}: {http_ltp}")
            return http_ltp

        # Last resort: return stale WebSocket data if available
        if self.tick_manager.connected:
            ws_ltp = self.tick_manager.get_ltp(symbol)
            if ws_ltp > 0:
                self.logger.warning(f"Using stale WebSocket data for {symbol}: {ws_ltp}")
                return ws_ltp

        self.logger.error(f"Failed to get LTP for {symbol} (both WS and HTTP failed)")
        return 0.0

    def verify_order_executed(
        self,
        order_id: str,
        expected_action: str,
        max_wait_seconds: int = 10,
        check_interval: float = 0.5
    ) -> dict:
        """
        Verify order execution status.

        Args:
            order_id: Order ID to check
            expected_action: Expected action (BUY/SELL)
            max_wait_seconds: Maximum time to wait for execution
            check_interval: Time between status checks

        Returns:
            dict with keys:
                - executed: bool
                - status: str (order status)
                - filled_qty: int
                - avg_price: float
                - message: str
        """
        start_time = time.time()
        last_status = "UNKNOWN"

        self.log(f"Verifying order {order_id}...")

        while (time.time() - start_time) < max_wait_seconds:
            try:
                result = self.client.orderstatus(order_id=order_id)

                if result.get("status") == "success":
                    order_data = result.get("data", {})
                    order_status = order_data.get("order_status", "").upper()
                    last_status = order_status

                    # Check for completed/executed status
                    if order_status in ["COMPLETE", "COMPLETED", "FILLED", "EXECUTED"]:
                        filled_qty = int(order_data.get("quantity", 0))
                        avg_price = round_to_tick(float(order_data.get("average_price", 0)))

                        self.log(f"Order EXECUTED: Qty={filled_qty}, Avg Price={avg_price:.2f}")
                        return {
                            "executed": True,
                            "status": order_status,
                            "filled_qty": filled_qty,
                            "avg_price": round_to_tick(avg_price),
                            "message": "Order executed successfully"
                        }

                    # Check for rejected/cancelled
                    elif order_status in ["REJECTED", "CANCELLED", "CANCELED", "FAILED"]:
                        reject_reason = order_data.get("reject_reason", order_data.get("message", "Unknown"))
                        self.logger.error(f"Order {order_status}: {reject_reason}")
                        return {
                            "executed": False,
                            "status": order_status,
                            "filled_qty": 0,
                            "avg_price": 0.0,
                            "message": f"Order {order_status}: {reject_reason}"
                        }

                    # Still pending - continue waiting
                    self.logger.debug(f"Order status: {order_status}, waiting...")

                else:
                    self.logger.warning(f"orderstatus API error: {result.get('message')}")

            except Exception as e:
                self.logger.error(f"Error checking order status: {e}")

            time.sleep(check_interval)

        # Timeout
        self.logger.warning(f"Order verification timeout. Last status: {last_status}")
        return {
            "executed": False,
            "status": last_status,
            "filled_qty": 0,
            "avg_price": 0.0,
            "message": f"Timeout waiting for order execution. Last status: {last_status}"
        }

    def _place_orders(self, symbol: str, action: str, quantity: int) -> dict:
        """
        Place order(s), using splitorder if quantity exceeds freeze limit.
        Returns dict with 'order_ids' list and 'status'.
        """
        if quantity <= FREEZE_QTY:
            result = self.client.placeorder(
                strategy=self.config.STRATEGY_NAME,
                symbol=symbol,
                exchange=self.options_exchange,
                action=action,
                quantity=quantity,
                price_type="MARKET",
                product="MIS"
            )
            if result.get("status") == "success":
                return {"status": "success", "order_ids": [result.get("orderid", "")]}
            return {"status": "error", "message": result.get("message", ""), "order_ids": []}

        # Quantity exceeds freeze limit — use splitorder
        self.log(f"Qty {quantity} > freeze {FREEZE_QTY}, using splitorder")
        result = self.client.splitorder(
            strategy=self.config.STRATEGY_NAME,
            symbol=symbol,
            action=action,
            exchange=self.options_exchange,
            quantity=quantity,
            splitsize=FREEZE_QTY,
            price_type="MARKET",
            product="MIS"
        )

        if result.get("status") == "success":
            order_ids = [r["orderid"] for r in result.get("results", []) if r.get("status") == "success"]
            failed = [r for r in result.get("results", []) if r.get("status") != "success"]
            if failed:
                self.logger.warning(f"{len(failed)} split orders failed: {failed}")
            return {"status": "success" if order_ids else "error", "order_ids": order_ids}

        return {"status": "error", "message": result.get("message", ""), "order_ids": []}

    def _verify_all_orders(self, order_ids: List[str], action: str) -> dict:
        """
        Verify all order IDs and return aggregated result.
        Returns: {executed: bool, total_qty: int, avg_price: float, verified_ids: [str]}
        """
        total_qty = 0
        total_value = 0.0
        verified_ids = []
        failed_ids = []

        for oid in order_ids:
            v = self.verify_order_executed(oid, action)
            if v["executed"]:
                qty = v["filled_qty"]
                price = v["avg_price"]
                total_qty += qty
                total_value += price * qty
                verified_ids.append(oid)
            else:
                self.logger.error(f"Order {oid} not executed: {v['message']}")
                failed_ids.append(oid)

        if total_qty > 0:
            avg_price = round_to_tick(total_value / total_qty)
        else:
            avg_price = 0.0

        return {
            "executed": total_qty > 0,
            "total_qty": total_qty,
            "avg_price": avg_price,
            "verified_ids": verified_ids,
            "failed_ids": failed_ids
        }

    def place_order(self, option_type: Literal["CE", "PE"], entry_price: float) -> Optional[Position]:
        """Place buy order(s) and create position. Splits if qty > freeze limit."""
        symbol = self.entry_levels.ce_symbol if option_type == "CE" else self.entry_levels.pe_symbol
        entry_level = self.entry_levels.ce_entry_level if option_type == "CE" else self.entry_levels.pe_entry_level

        # Calculate quantity
        capital = self.get_available_capital()
        quantity = calculate_quantity(capital, entry_price, self.entry_levels.lot_size)

        if quantity <= 0:
            self.log("Insufficient capital for order")
            return None

        self.log(f"Placing {option_type} BUY order: {symbol} @ ~{entry_price:.2f}, Qty: {quantity}")

        # Place order(s)
        result = self._place_orders(symbol, "BUY", quantity)
        if result["status"] != "success" or not result["order_ids"]:
            self.log(f"Order placement failed: {result.get('message', 'no orders placed')}")
            return None

        order_ids = result["order_ids"]
        self.log(f"Orders placed: {len(order_ids)} order(s) | IDs: {order_ids}")

        # Verify all orders
        verification = self._verify_all_orders(order_ids, "BUY")

        if not verification["executed"]:
            self.logger.error("No BUY orders executed")
            return None

        # Use verified fill price
        actual_price = verification["avg_price"]
        if actual_price <= 0:
            actual_price = self.tick_manager.get_ltp(symbol)
        if actual_price <= 0:
            actual_price = entry_price

        actual_price = round_to_tick(actual_price)
        filled_qty = verification["total_qty"] if verification["total_qty"] > 0 else quantity

        # Calculate SL and Target (rounded to tick size)
        sl_price = round_to_tick(entry_level * (1 - self.config.SL_PERCENT))
        target_price = round_to_tick(actual_price * self.config.TARGET_MULTIPLIER)

        position = Position(
            option_type=option_type,
            symbol=symbol,
            entry_price=actual_price,
            quantity=filled_qty,
            sl_price=sl_price,
            target_price=target_price,
            entry_time=datetime.now(),
            order_ids=verification["verified_ids"],
            cost_basis=actual_price * filled_qty,
            current_r_level=0
        )

        self.log(f"Position CONFIRMED: Entry={actual_price:.2f}, Qty={filled_qty}, SL={sl_price:.2f}, Target={target_price:.2f}")

        # Log R levels for reference
        if self.resistance_levels:
            self.log(f"Trail levels: R1={self.resistance_levels.r1:.2f}, R2={self.resistance_levels.r2:.2f}, "
                     f"R3={self.resistance_levels.r3:.2f}, R4={self.resistance_levels.r4:.2f}")
        return position

    def manage_position(self) -> bool:
        """
        Manage active position with level-based trailing SL using WebSocket data.

        Trailing Logic:
        - LTP touches R1 → SL moves to R1 × (1 - SL_BUFFER_PERCENT)
        - LTP touches R2 → SL moves to R2 × (1 - SL_BUFFER_PERCENT)
        - ... and so on for R3-R6

        Returns True if position is closed, False otherwise.
        """
        if not self.position:
            return False

        if not self.resistance_levels:
            return False

        # Get LTP with WebSocket + HTTP fallback (critical for SL/target)
        ltp = self.get_ltp_with_fallback(self.position.symbol)
        if ltp <= 0:
            self.logger.warning("Could not get LTP for position management")
            return False

        current_value = ltp * self.position.quantity
        pnl = current_value - self.position.cost_basis
        pnl_percent = (pnl / self.position.cost_basis) * 100

        # Check target hit
        if ltp >= self.position.target_price:
            self.log(f"TARGET HIT! LTP: {ltp:.2f}, Target: {self.position.target_price:.2f}")
            return self.close_position("TARGET")

        # Check SL hit
        if ltp <= self.position.sl_price:
            self.log(f"SL HIT! LTP: {ltp:.2f}, SL: {self.position.sl_price:.2f}")
            return self.close_position("STOPLOSS")

        # Level-based Trailing SL logic
        # Check each R level from current+1 to R6
        r_levels = self.resistance_levels.get_all_levels()  # [R1, R2, R3, R4, R5, R6]

        for level_num in range(self.position.current_r_level + 1, len(r_levels) + 1):
            r_value = r_levels[level_num - 1]  # R1 is at index 0

            # Check if LTP has touched this R level
            if ltp >= r_value and r_value > 0:
                # Calculate new SL (10% below this R level)
                new_sl = round_to_tick(r_value * (1 - self.config.SL_BUFFER_PERCENT))

                # Only update if new SL is higher than current SL
                if new_sl > self.position.sl_price:
                    old_sl = self.position.sl_price
                    self.position.sl_price = new_sl
                    self.position.current_r_level = level_num
                    self.log(
                        f"R{level_num} TOUCHED! LTP: {ltp:.2f}, R{level_num}: {r_value:.2f} | "
                        f"SL moved: {old_sl:.2f} → {new_sl:.2f} (PnL: {pnl_percent:.1f}%)"
                    )

        return False

    def close_position(self, reason: str, max_retries: int = 3) -> bool:
        """
        Robust position close with retries. Uses splitorder if qty > freeze limit.

        Args:
            reason: Exit reason (STOPLOSS, TARGET, TIME_EXIT, MANUAL_EXIT, etc.)
            max_retries: Number of retry attempts for failed orders

        Returns:
            True if position closed successfully, False otherwise
        """
        if not self.position:
            self.log("No position to close")
            return False

        self.log(f"{'='*50}")
        self.log(f"CLOSING POSITION: {reason}")
        self.log(f"Symbol: {self.position.symbol}, Qty: {self.position.quantity}")
        self.log(f"{'='*50}")

        # Store position details before closing
        symbol = self.position.symbol
        quantity = self.position.quantity
        entry_price = self.position.entry_price
        option_type = self.position.option_type
        entry_time = self.position.entry_time
        entry_order_ids = self.position.order_ids
        initial_sl = self.position.sl_price
        target_price = self.position.target_price
        r_level_reached = self.position.current_r_level
        final_sl = self.position.sl_price

        # Attempt to close with retries
        order_success = False
        exit_price = 0.0
        exit_order_ids = []

        for attempt in range(1, max_retries + 1):
            self.log(f"Exit attempt {attempt}/{max_retries}...")

            try:
                result = self._place_orders(symbol, "SELL", quantity)

                if result["status"] == "success" and result["order_ids"]:
                    exit_order_ids = result["order_ids"]
                    self.log(f"Exit orders placed: {len(exit_order_ids)} order(s)")

                    # Verify all exit orders
                    verification = self._verify_all_orders(exit_order_ids, "SELL")

                    if verification["executed"]:
                        order_success = True
                        exit_price = verification["avg_price"]

                        # Fallback if avg_price not available
                        if exit_price <= 0:
                            exit_price = self.tick_manager.get_ltp(symbol)
                        if exit_price <= 0:
                            if reason == "STOPLOSS":
                                exit_price = self.position.sl_price
                            elif reason == "TARGET":
                                exit_price = self.position.target_price
                            else:
                                exit_price = entry_price

                        exit_price = round_to_tick(exit_price)
                        self.log(f"Exit CONFIRMED at {exit_price:.2f} | Qty: {verification['total_qty']}")
                        break
                    else:
                        self.logger.warning(f"Exit orders not confirmed: {verification.get('failed_ids', [])}")
                        if attempt < max_retries:
                            time.sleep(2)

                else:
                    self.log(f"Exit order placement failed: {result.get('message', '')}")
                    if attempt < max_retries:
                        time.sleep(2)

            except Exception as e:
                self.logger.error(f"Exit order exception: {e}")
                if attempt < max_retries:
                    time.sleep(2)

        if not order_success:
            self.logger.critical(f"FAILED TO CLOSE POSITION after {max_retries} attempts!")
            self.logger.critical(f"MANUAL INTERVENTION REQUIRED: {symbol} x {quantity}")
            return False

        # Calculate PnL
        pnl = (exit_price - entry_price) * quantity
        self.daily_pnl += pnl

        # Record trade
        trade_key = entry_order_ids[0] if entry_order_ids else "unknown"
        trade_record = {
            "entry_order_id": ", ".join(entry_order_ids),
            "exit_order_id": ", ".join(exit_order_ids),
            "symbol": symbol,
            "option_type": option_type,
            "entry_time": entry_time.strftime("%H:%M:%S"),
            "entry_price": entry_price,
            "initial_sl": initial_sl,
            "target_price": target_price,
            "exit_time": datetime.now().strftime("%H:%M:%S"),
            "exit_price": exit_price,
            "final_sl": final_sl,
            "quantity": quantity,
            "pnl": pnl,
            "exit_reason": reason,
            "r_level_reached": r_level_reached
        }
        self.trades_dict[trade_key] = trade_record

        # Log trade to Excel for long-term tracking
        self.log_trade_to_excel(trade_record)

        # Clear position
        self.position = None

        # Increment completed trades
        self.completed_trades += 1

        # Log summary
        pnl_str = f"+{pnl:.2f}" if pnl >= 0 else f"{pnl:.2f}"
        self.log(f"Position CLOSED: Entry={entry_price:.2f}, Exit={exit_price:.2f}, PnL={pnl_str}")
        self.log(f"Completed trades: {self.completed_trades}/{self.config.MAX_COMPLETED_TRADES}")

        # Check if max trades reached - stop new entries
        if self.completed_trades >= self.config.MAX_COMPLETED_TRADES:
            self.can_trade = False
            self.log(f"MAX COMPLETED TRADES ({self.config.MAX_COMPLETED_TRADES}) REACHED - No more entries today")

        return True

    def is_force_exit_time(self) -> bool:
        """Check if it's time to force exit all positions (15:00)"""
        now = datetime.now()
        exit_time = datetime.strptime(
            f"{now.strftime('%Y-%m-%d')} {self.config.FORCE_EXIT_TIME}",
            "%Y-%m-%d %H:%M"
        )
        return now >= exit_time

    def is_new_entry_allowed(self) -> bool:
        """
        Check if new entries are allowed.
        Returns False if:
        - Time is past NO_NEW_ENTRY_TIME (14:15)
        - can_trade flag is False (max completed trades reached)
        """
        if not self.can_trade:
            return False

        now = datetime.now()
        cutoff_time = datetime.strptime(
            f"{now.strftime('%Y-%m-%d')} {self.config.NO_NEW_ENTRY_TIME}",
            "%Y-%m-%d %H:%M"
        )
        return now < cutoff_time

    def print_summary(self):
        """Print comprehensive end-of-day summary"""
        self.log("=" * 70)
        self.log("END OF DAY SUMMARY")
        self.log("=" * 70)
        self.log(f"Index: {self.config.INDEX} | ATM Strike: {self.entry_levels.atm_strike if self.entry_levels else 'N/A'}")
        self.log(f"Completed Trades: {self.completed_trades}/{self.config.MAX_COMPLETED_TRADES}")

        # Calculate win/loss stats
        if self.trades_dict:
            wins = sum(1 for t in self.trades_dict.values() if t['pnl'] > 0)
            losses = sum(1 for t in self.trades_dict.values() if t['pnl'] < 0)
            win_rate = (wins / len(self.trades_dict) * 100) if self.trades_dict else 0
            self.log(f"Win Rate: {wins}W / {losses}L ({win_rate:.1f}%)")

        pnl_color = "+" if self.daily_pnl >= 0 else ""
        self.log(f"Daily PnL: {pnl_color}{self.daily_pnl:.2f}")
        self.log("=" * 70)

        if not self.trades_dict:
            self.log("No trades executed today")
        else:
            for i, (entry_order_id, trade) in enumerate(self.trades_dict.items(), 1):
                pnl_sign = "+" if trade['pnl'] >= 0 else ""
                r_level_str = f"R{trade['r_level_reached']}" if trade['r_level_reached'] > 0 else "Entry"

                self.log(f"\nTrade #{i} ({trade['exit_reason']})")
                self.log(f"  Entry Order : {entry_order_id}")
                self.log(f"  Exit Order  : {trade.get('exit_order_id', 'N/A')}")
                self.log(f"  Symbol      : {trade['option_type']} {trade['symbol']}")
                self.log(f"  Entry Time  : {trade['entry_time']} @ {trade['entry_price']:.2f}")
                self.log(f"  Initial SL  : {trade['initial_sl']:.2f}")
                self.log(f"  Target      : {trade['target_price']:.2f}")
                self.log(f"  Exit Time   : {trade['exit_time']} @ {trade['exit_price']:.2f}")
                self.log(f"  Final SL    : {trade['final_sl']:.2f} [{r_level_str}]")
                self.log(f"  Quantity    : {trade['quantity']}")
                self.log(f"  PnL         : {pnl_sign}{trade['pnl']:.2f}")

        self.log("=" * 70)

    def print_status(self):
        """Print current status (called periodically)"""
        if not self.entry_levels:
            return

        pe_ltp = self.tick_manager.get_ltp(self.entry_levels.pe_symbol)
        ce_ltp = self.tick_manager.get_ltp(self.entry_levels.ce_symbol)

        status = f"PE: {pe_ltp:.2f} (Entry: {self.entry_levels.pe_entry_level:.2f}) | "
        status += f"CE: {ce_ltp:.2f} (Entry: {self.entry_levels.ce_entry_level:.2f})"

        if self.position:
            pos_ltp = self.get_ltp_with_fallback(self.position.symbol)
            pnl = (pos_ltp - self.position.entry_price) * self.position.quantity if pos_ltp > 0 else 0
            r_level = f"R{self.position.current_r_level}" if self.position.current_r_level > 0 else "Entry"
            status += f" | POS: {self.position.option_type} LTP: {pos_ltp:.2f} PnL: {pnl:.2f} SL: {self.position.sl_price:.2f} [{r_level}]"

            # Show next R level to watch
            if self.resistance_levels and self.position.current_r_level < 6:
                next_r = self.resistance_levels.get_level(self.position.current_r_level + 1)
                status += f" Next: R{self.position.current_r_level + 1}={next_r:.2f}"

        self.log(status)

    def safe_execute(self, func: Callable, description: str, *args, **kwargs):
        """Execute a function with error handling and retry logic"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                self.logger.error(f"{description} failed (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    raise

    def run(self):
        """Main strategy loop with robust error handling"""
        self.running = True
        self.log(f"Starting {self.config.STRATEGY_NAME} Strategy for {self.config.INDEX} (WebSocket v3.0)")
        self.log(f"Robustness: reconnect_attempts={MAX_RECONNECT_ATTEMPTS}, health_check={HEALTH_CHECK_INTERVAL}s")

        try:
            # FIRST: Check market hours (local check, no API needed)
            # This allows immediate exit if running after market close
            can_trade, hours_message = self.is_market_hours()
            if not can_trade:
                self.log(f"{hours_message}. Exiting strategy.")
                return

            self.log(f"Market hours: {hours_message}")

            # SECOND: Check if today is a trading day (holiday check via API)
            is_trading, message = is_trading_day(self.client)
            if not is_trading:
                self.log(f"{message}. Exiting strategy.")
                return

            self.log(f"Market status: {message}")

            # Wait for market open (if before 9:15)
            self.wait_for_market_open()

            # Wait for first 5-min candle (9:20) and calculate R1-R6 levels
            self.safe_execute(
                self.wait_for_5min_candle_and_calculate_levels,
                "Calculate resistance levels"
            )

            # Wait for first 15-min candle (9:30)
            self.wait_for_first_candle()

            # Calculate entry levels (with retry)
            self.entry_levels = self.safe_execute(
                self.calculate_entry_levels,
                "Calculate entry levels"
            )

            # Check if max trades already completed today (from Excel log)
            if not self.can_trade:
                self.log(f"Max trades ({self.config.MAX_COMPLETED_TRADES}) already completed today. Exiting.")
                return

            # Setup WebSocket (with retry)
            self.safe_execute(self.setup_websocket, "Setup WebSocket")

            # Main trading loop
            self.log("Trading loop active. Monitoring for entries...")
            last_status_log = time.time()
            last_health_log = datetime.now()

            while self.running:
                try:
                    # Periodic status log every 30 seconds
                    now_ts = time.time()
                    if now_ts - last_status_log >= 30:
                        self.print_status()
                        last_status_log = now_ts

                    # Check force exit time
                    if self.is_force_exit_time():
                        self.log("FORCE EXIT TIME reached!")
                        if self.position:
                            self.close_position("TIME_EXIT")
                        break

                    # Check WebSocket health
                    if self.tick_manager.state == ConnectionState.FAILED:
                        self.logger.critical("WebSocket permanently failed - exiting strategy")
                        if self.position:
                            self.close_position("WS_FAILED")
                        break

                    # No position + no new entries possible = exit strategy
                    if not self.position and (not self.can_trade or not self.is_new_entry_allowed()):
                        reason = "Max completed trades reached" if not self.can_trade else "Past entry cutoff time"
                        self.log(f"{reason}, no position running - exiting strategy")
                        break

                    # Log health status periodically
                    if (datetime.now() - last_health_log).seconds >= 300:  # Every 5 mins
                        self._log_health_status()
                        last_health_log = datetime.now()

                    # Skip trading logic if WebSocket is not connected
                    if not self.tick_manager.connected:
                        time.sleep(1)
                        continue

                    # If we have a position, manage it
                    if self.position:
                        self.manage_position()

                    # If no position and new entries allowed, check entry conditions
                    elif self.is_new_entry_allowed():
                        pe_ltp = self.tick_manager.get_ltp(self.entry_levels.pe_symbol)
                        ce_ltp = self.tick_manager.get_ltp(self.entry_levels.ce_symbol)
                        pe_candles = self.get_1m_candles(self.entry_levels.pe_symbol)
                        ce_candles = self.get_1m_candles(self.entry_levels.ce_symbol)

                        # Check PE entry condition
                        if check_entry_condition(
                            pe_ltp, pe_candles, self.entry_levels.pe_entry_level
                        ):
                            self.log(f"PE Entry condition met! LTP: {pe_ltp:.2f}")
                            self.position = self.place_order("PE", pe_ltp)

                        # Check CE entry condition
                        elif check_entry_condition(
                            ce_ltp, ce_candles, self.entry_levels.ce_entry_level
                        ):
                            self.log(f"CE Entry condition met! LTP: {ce_ltp:.2f}")
                            self.position = self.place_order("CE", ce_ltp)

                    # Small sleep to prevent CPU spinning (WebSocket handles the data)
                    time.sleep(0.1)

                except Exception as loop_error:
                    self.logger.error(f"Error in main loop: {loop_error}")
                    self.logger.debug(traceback.format_exc())
                    time.sleep(1)  # Prevent tight error loop

        except KeyboardInterrupt:
            self.log("Strategy interrupted by user (Ctrl+C)")
            self.running = False
            if self.position:
                self.close_position("MANUAL_EXIT")

        except Exception as e:
            self.logger.critical(f"Critical error: {str(e)}")
            self.logger.error(traceback.format_exc())
            if self.position:
                try:
                    self.close_position("ERROR_EXIT")
                except Exception:
                    self.logger.error("Failed to exit position on error")
            raise  # Re-raise for crash recovery

        finally:
            self.running = False
            self.cleanup_websocket()
            self.print_summary()
            self.log("Strategy finished.")

    def _log_health_status(self):
        """Log current health status"""
        ws_state = self.tick_manager.state.value
        stale = self.tick_manager.is_data_stale()
        reconnects = self.tick_manager.reconnect_attempts

        self.logger.info(
            f"[Health] WS: {ws_state}, Stale: {stale}, Reconnects: {reconnects}, "
            f"Completed: {self.completed_trades}/{self.config.MAX_COMPLETED_TRADES}, PnL: {self.daily_pnl:.2f}"
        )

    def stop(self):
        """Gracefully stop the strategy"""
        self.log("Stop requested...")
        self.running = False


# =============================================================================
# ENTRY POINT WITH CRASH RECOVERY
# =============================================================================

def run_with_crash_recovery():
    """Run strategy with automatic crash recovery"""
    crash_count = 0

    while True:
        try:
            # Create fresh config and strategy instance
            config = Config()
            strategy = OptionsAlphaStrategy(config)

            if crash_count > 0:
                strategy.log(f"Restarting after crash (attempt {crash_count}/{MAX_CRASH_RESTARTS})")

            # Run strategy
            strategy.run()

            # If we get here normally (no exception), exit the loop
            break

        except KeyboardInterrupt:
            print("\n[MAIN] Keyboard interrupt - exiting")
            break

        except Exception as e:
            crash_count += 1
            print(f"\n[MAIN] Strategy crashed: {e}")
            print(traceback.format_exc())

            if not AUTO_RESTART_ON_CRASH:
                print("[MAIN] Auto-restart disabled - exiting")
                break

            if crash_count >= MAX_CRASH_RESTARTS:
                print(f"[MAIN] Max crash restarts ({MAX_CRASH_RESTARTS}) exceeded - exiting")
                break

            # Check if market is still open before restarting
            now = datetime.now()
            exit_time = datetime.strptime(
                f"{now.strftime('%Y-%m-%d')} 15:00",
                "%Y-%m-%d %H:%M"
            )
            if now >= exit_time:
                print("[MAIN] Market closed - not restarting")
                break

            # Wait before restart
            restart_delay = 10 * crash_count  # Increasing delay
            print(f"[MAIN] Restarting in {restart_delay} seconds...")
            time.sleep(restart_delay)


if __name__ == "__main__":
    # Validate API key
    if API_KEY == "YOUR_API_KEY_HERE" or len(API_KEY) < 10:
        print("=" * 60)
        print("ERROR: API key not configured!")
        print("Configure API key in ~/.config/openalgo/config.json")
        print("Get your key from: http://127.0.0.1:5002/apikey")
        print("=" * 60)
        exit(1)

    print("=" * 60)
    print("Options Alpha Strategy v3.0")
    print("Features: WebSocket, Auto-Reconnect, Crash Recovery")
    print("=" * 60)

    # Run with crash recovery wrapper
    run_with_crash_recovery()
