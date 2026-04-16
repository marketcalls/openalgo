"""
===============================================================================
                EMA CROSSOVER WITH FIXED DATETIME HANDLING
                            OpenAlgo Trading Bot
===============================================================================

Run standalone:
    export OPENALGO_API_KEY="your-api-key"
    python emacrossover_strategy_python.py

Run via OpenAlgo's /python strategy runner:
    OPENALGO_API_KEY            : injected per-strategy (PR #1247).
    OPENALGO_STRATEGY_EXCHANGE  : set from the strategy's `exchange` config
                                  (NSE / BSE / NFO / BFO / MCX / BCD / CDS / CRYPTO).
                                  Drives both this script's trading exchange and
                                  the host's calendar/holiday gating, so the two
                                  always agree (no NSE-only orders on an MCX-gated
                                  strategy).
    STRATEGY_ID / STRATEGY_NAME : injected for log/order tagging.
    HOST_SERVER / WEBSOCKET_URL : inherited from OpenAlgo's .env.
    No code changes required.
"""

import os
import threading
import time
from datetime import datetime, timedelta

import pandas as pd
from openalgo import api

# ===============================================================================
# TRADING CONFIGURATION
# ===============================================================================

# API Configuration — read from environment with sensible fallbacks.
# When launched via OpenAlgo's /python runner, these come from the platform:
#   OPENALGO_API_KEY : injected per-strategy (decrypted from DB)
#   HOST_SERVER      : inherited from OpenAlgo's .env
#   WEBSOCKET_URL    : inherited from OpenAlgo's .env
API_KEY = os.getenv("OPENALGO_API_KEY", "openalgo-apikey")
API_HOST = os.getenv("HOST_SERVER", "http://127.0.0.1:5000")
WS_URL = os.getenv("WEBSOCKET_URL", "ws://127.0.0.1:8765")

# Trade Settings
# EXCHANGE prefers OPENALGO_STRATEGY_EXCHANGE (set by /python runner from the
# strategy's config) so the script trades on whichever exchange the host is
# gating its calendar against. Falls back to EXCHANGE env var, then NSE.
SYMBOL = os.getenv("SYMBOL", "NHPC")              # Stock to trade
EXCHANGE = os.getenv(
    "OPENALGO_STRATEGY_EXCHANGE",
    os.getenv("EXCHANGE", "NSE"),
)                                                 # NSE, BSE, NFO, BFO, MCX, BCD, CDS, CRYPTO
QUANTITY = int(os.getenv("QUANTITY", "1"))        # Number of shares
PRODUCT = os.getenv("PRODUCT", "MIS")             # MIS (Intraday) or CNC (Delivery)

# Strategy Parameters
FAST_EMA_PERIOD = int(os.getenv("FAST_EMA_PERIOD", "2"))
SLOW_EMA_PERIOD = int(os.getenv("SLOW_EMA_PERIOD", "4"))
CANDLE_TIMEFRAME = os.getenv("CANDLE_TIMEFRAME", "5m")  # 1m, 5m, 15m, 30m, 1h, 1d

# Historical Data Lookback (1-30 days)
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "3"))

# Risk Management (Rupees)
STOPLOSS = float(os.getenv("STOPLOSS", "0.1"))
TARGET = float(os.getenv("TARGET", "0.2"))

# Direction Control: LONG, SHORT, BOTH
TRADE_DIRECTION = os.getenv("TRADE_DIRECTION", "BOTH")

# Signal Check Interval (seconds)
SIGNAL_CHECK_INTERVAL = int(os.getenv("SIGNAL_CHECK_INTERVAL", "5"))

# ===============================================================================
# TRADING BOT WITH FIXED DATETIME
# ===============================================================================


class ConfigurableEMABot:
    def __init__(self):
        """Initialize the trading bot with configurable parameters"""
        # Initialize API client
        self.client = api(
            api_key=API_KEY,
            host=API_HOST,
            ws_url=WS_URL,
        )

        # Position tracking
        self.position = None
        self.entry_price = 0
        self.stoploss_price = 0
        self.target_price = 0

        # Real-time price tracking
        self.ltp = None
        self.exit_in_progress = False

        # Thread control
        self.running = True
        self.stop_event = threading.Event()

        # Instrument for WebSocket
        self.instrument = [{"exchange": EXCHANGE, "symbol": SYMBOL}]

        # Strategy name — honor STRATEGY_NAME from the platform if present.
        self.strategy_name = os.getenv("STRATEGY_NAME", f"EMA_{TRADE_DIRECTION}")

        # Validate lookback period
        if LOOKBACK_DAYS < 1:
            print("[WARNING] LOOKBACK_DAYS too small, setting to 1")
            self.lookback_days = 1
        elif LOOKBACK_DAYS > 30:
            print("[WARNING] LOOKBACK_DAYS too large, setting to 30")
            self.lookback_days = 30
        else:
            self.lookback_days = LOOKBACK_DAYS

        print("[BOT] OpenAlgo Trading Bot Started")
        print(f"[BOT] Host: {API_HOST} | WS: {WS_URL}")
        print(f"[BOT] Symbol: {SYMBOL} on {EXCHANGE}")
        print(f"[BOT] Direction Mode: {TRADE_DIRECTION}")
        print(f"[BOT] Strategy: {FAST_EMA_PERIOD} EMA x {SLOW_EMA_PERIOD} EMA")
        print(f"[BOT] Lookback Period: {self.lookback_days} days")
        print(f"[BOT] Signal Check Interval: {SIGNAL_CHECK_INTERVAL} seconds")
        if os.getenv("OPENALGO_STRATEGY_EXCHANGE"):
            print(
                f"[BOT] Exchange resolved from OPENALGO_STRATEGY_EXCHANGE "
                f"(host calendar = {EXCHANGE})"
            )

    # ===========================================================================
    # WEBSOCKET HANDLER WITH IMMEDIATE EXIT
    # ===========================================================================

    def on_ltp_update(self, data):
        """Handle real-time LTP updates and place exit orders immediately"""
        if data.get("type") == "market_data" and data.get("symbol") == SYMBOL:
            self.ltp = float(data["data"]["ltp"])

            # Display current status
            current_time = datetime.now().strftime("%H:%M:%S")

            if self.position and not self.exit_in_progress:
                # Calculate real-time P&L
                if self.position == "BUY":
                    unrealized_pnl = (self.ltp - self.entry_price) * QUANTITY
                else:
                    unrealized_pnl = (self.entry_price - self.ltp) * QUANTITY

                pnl_sign = "+" if unrealized_pnl > 0 else "-"
                print(
                    f"\r[{current_time}] LTP: Rs.{self.ltp:.2f} | "
                    f"{self.position} @ Rs.{self.entry_price:.2f} | "
                    f"P&L: {pnl_sign}Rs.{abs(unrealized_pnl):.2f} | "
                    f"SL: {self.stoploss_price:.2f} | TG: {self.target_price:.2f}    ",
                    end="",
                )

                # Check and execute exit immediately
                exit_reason = None

                if self.position == "BUY":
                    if self.ltp <= self.stoploss_price:
                        exit_reason = "STOPLOSS HIT"
                        print(
                            f"\n[ALERT] STOPLOSS HIT! LTP Rs.{self.ltp:.2f} "
                            f"<= SL Rs.{self.stoploss_price:.2f}"
                        )
                    elif self.ltp >= self.target_price:
                        exit_reason = "TARGET HIT"
                        print(
                            f"\n[ALERT] TARGET HIT! LTP Rs.{self.ltp:.2f} "
                            f">= Target Rs.{self.target_price:.2f}"
                        )

                elif self.position == "SELL":
                    if self.ltp >= self.stoploss_price:
                        exit_reason = "STOPLOSS HIT"
                        print(
                            f"\n[ALERT] STOPLOSS HIT! LTP Rs.{self.ltp:.2f} "
                            f">= SL Rs.{self.stoploss_price:.2f}"
                        )
                    elif self.ltp <= self.target_price:
                        exit_reason = "TARGET HIT"
                        print(
                            f"\n[ALERT] TARGET HIT! LTP Rs.{self.ltp:.2f} "
                            f"<= Target Rs.{self.target_price:.2f}"
                        )

                # Place exit order immediately if SL/Target hit
                if exit_reason and not self.exit_in_progress:
                    self.exit_in_progress = True
                    print("[EXIT] Placing exit order immediately...")

                    # New thread for exit to avoid blocking WebSocket
                    exit_thread = threading.Thread(
                        target=self.place_exit_order,
                        args=(exit_reason,),
                    )
                    exit_thread.start()

            elif not self.position:
                print(
                    f"\r[{current_time}] LTP: Rs.{self.ltp:.2f} | No Position | "
                    f"Mode: {TRADE_DIRECTION} | Lookback: {self.lookback_days}d    ",
                    end="",
                )

    def websocket_thread(self):
        """WebSocket thread for real-time price updates"""
        try:
            print("[WEBSOCKET] Connecting...")
            self.client.connect()

            # Subscribe to LTP updates
            self.client.subscribe_ltp(self.instrument, on_data_received=self.on_ltp_update)
            print(f"[WEBSOCKET] Connected - Monitoring {SYMBOL} in real-time")

            # Keep thread alive
            while not self.stop_event.is_set():
                time.sleep(1)

        except Exception as e:
            print(f"\n[ERROR] WebSocket error: {e}")
        finally:
            print("\n[WEBSOCKET] Closing connection...")
            try:
                self.client.unsubscribe_ltp(self.instrument)
                self.client.disconnect()
            except Exception:
                pass
            print("[WEBSOCKET] Connection closed")

    # ===========================================================================
    # TRADING FUNCTIONS
    # ===========================================================================

    def get_historical_data(self):
        """Fetch historical candle data with configurable lookback"""
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=self.lookback_days)

            print(f"\n[DATA] Fetching {self.lookback_days} days of historical data...")
            print(
                f"[DATA] From: {start_date.strftime('%Y-%m-%d')} "
                f"To: {end_date.strftime('%Y-%m-%d')}"
            )

            data = self.client.history(
                symbol=SYMBOL,
                exchange=EXCHANGE,
                interval=CANDLE_TIMEFRAME,
                start_date=start_date.strftime("%Y-%m-%d"),
                end_date=end_date.strftime("%Y-%m-%d"),
            )

            if data is not None and len(data) > 0:
                if "datetime" in data.columns:
                    first_time = str(data["datetime"].iloc[0])
                    last_time = str(data["datetime"].iloc[-1])
                    print(f"[DATA] Received {len(data)} candles from {first_time} to {last_time}")
                elif "date" in data.columns:
                    first_date = str(data["date"].iloc[0])
                    last_date = str(data["date"].iloc[-1])
                    print(f"[DATA] Received {len(data)} candles from {first_date} to {last_date}")
                else:
                    print(f"[DATA] Received {len(data)} candles")
            else:
                print("[WARNING] No data received from API")

            return data

        except Exception as e:
            print(f"\n[ERROR] Failed to fetch data: {str(e)}")
            print(f"[DEBUG] Error type: {type(e).__name__}")

            # Fallback attempt
            try:
                end_date = datetime.now()
                start_date = end_date - timedelta(days=self.lookback_days)

                data = self.client.history(
                    symbol=SYMBOL,
                    exchange=EXCHANGE,
                    interval=CANDLE_TIMEFRAME,
                    start_date=start_date.strftime("%Y-%m-%d"),
                    end_date=end_date.strftime("%Y-%m-%d"),
                )

                if data is not None and len(data) > 0:
                    print(f"[DATA] Successfully received {len(data)} candles (alternative method)")
                    return data

            except Exception as e2:
                print(f"[ERROR] Alternative fetch also failed: {str(e2)}")

            return None

    def check_for_signal(self, data):
        """Check for EMA crossover signals with direction filter"""
        if data is None:
            return None

        if len(data) < SLOW_EMA_PERIOD + 2:
            print(
                f"[INFO] Insufficient data. Need at least {SLOW_EMA_PERIOD + 2} candles, "
                f"have {len(data)}"
            )
            return None

        try:
            # Calculate EMAs
            data["fast_ema"] = data["close"].ewm(span=FAST_EMA_PERIOD, adjust=False).mean()
            data["slow_ema"] = data["close"].ewm(span=SLOW_EMA_PERIOD, adjust=False).mean()

            # Last three candles
            prev = data.iloc[-3]
            last = data.iloc[-2]
            current = data.iloc[-1]

            print(
                f"[DEBUG] Fast EMA: {last['fast_ema']:.2f}, "
                f"Slow EMA: {last['slow_ema']:.2f}, Close: {current['close']:.2f}"
            )

            # BUY signal
            if prev["fast_ema"] <= prev["slow_ema"] and last["fast_ema"] > last["slow_ema"]:
                if TRADE_DIRECTION in ["LONG", "BOTH"]:
                    print("[SIGNAL] BUY - Fast EMA crossed above Slow EMA")
                    return "BUY"
                print(f"[SIGNAL] BUY signal detected but ignored (Mode: {TRADE_DIRECTION})")
                return None

            # SELL signal
            if prev["fast_ema"] >= prev["slow_ema"] and last["fast_ema"] < last["slow_ema"]:
                if TRADE_DIRECTION in ["SHORT", "BOTH"]:
                    print("[SIGNAL] SELL - Fast EMA crossed below Slow EMA")
                    return "SELL"
                print(f"[SIGNAL] SELL signal detected but ignored (Mode: {TRADE_DIRECTION})")
                return None

        except Exception as e:
            print(f"[ERROR] Error checking signal: {str(e)}")

        return None

    def get_executed_price(self, order_id):
        """Get actual executed price from order status"""
        max_attempts = 5

        for _ in range(max_attempts):
            time.sleep(2)

            try:
                response = self.client.orderstatus(
                    order_id=order_id,
                    strategy=self.strategy_name,
                )

                if response.get("status") == "success":
                    order_data = response.get("data", {})

                    if order_data.get("order_status") == "complete":
                        executed_price = float(order_data.get("average_price", 0))
                        if executed_price > 0:
                            return executed_price

                    elif order_data.get("order_status") in ["rejected", "cancelled"]:
                        print(f"[ERROR] Order {order_data.get('order_status')}")
                        return None

                    else:
                        print(f"[WAITING] Order status: {order_data.get('order_status')}")

            except Exception as e:
                print(f"[ERROR] Failed to get order status: {e}")

        return None

    def place_entry_order(self, signal):
        """Place entry order based on direction filter"""
        if signal == "BUY" and TRADE_DIRECTION == "SHORT":
            print("[INFO] BUY signal ignored - SHORT only mode")
            return False

        if signal == "SELL" and TRADE_DIRECTION == "LONG":
            print("[INFO] SELL signal ignored - LONG only mode")
            return False

        print(f"\n[ORDER] Placing {signal} order for {QUANTITY} shares of {SYMBOL}")

        try:
            response = self.client.placeorder(
                strategy=self.strategy_name,
                symbol=SYMBOL,
                exchange=EXCHANGE,
                action=signal,
                quantity=QUANTITY,
                price_type="MARKET",
                product=PRODUCT,
            )

            if response.get("status") == "success":
                order_id = response.get("orderid")
                print(f"[ORDER] Order placed. ID: {order_id}")

                executed_price = self.get_executed_price(order_id)

                if executed_price:
                    self.position = signal
                    self.entry_price = executed_price

                    if signal == "BUY":
                        self.stoploss_price = round(self.entry_price - STOPLOSS, 2)
                        self.target_price = round(self.entry_price + TARGET, 2)
                    else:  # SELL
                        self.stoploss_price = round(self.entry_price + STOPLOSS, 2)
                        self.target_price = round(self.entry_price - TARGET, 2)

                    print("\n" + "=" * 60)
                    print(" TRADE EXECUTED")
                    print("=" * 60)
                    print(f" Direction Mode: {TRADE_DIRECTION}")
                    print(f" Position: {signal}")
                    print(f" Entry Price: Rs.{self.entry_price:.2f}")
                    print(f" Quantity: {QUANTITY}")
                    print(f" Stoploss: Rs.{self.stoploss_price:.2f}")
                    print(f" Target: Rs.{self.target_price:.2f}")
                    print("=" * 60)
                    print("\n[INFO] WebSocket monitoring SL/Target in real-time...")

                    self.exit_in_progress = False
                    return True

                print("[ERROR] Could not get executed price")
            else:
                print(f"[ERROR] Order failed: {response}")

        except Exception as e:
            print(f"[ERROR] Failed to place order: {e}")

        return False

    def place_exit_order(self, reason="Manual"):
        """Place exit order - called immediately from WebSocket handler"""
        if not self.position:
            self.exit_in_progress = False
            return

        exit_action = "SELL" if self.position == "BUY" else "BUY"
        print(f"\n[EXIT] Closing {self.position} position - {reason}")

        try:
            response = self.client.placeorder(
                strategy=self.strategy_name,
                symbol=SYMBOL,
                exchange=EXCHANGE,
                action=exit_action,
                quantity=QUANTITY,
                price_type="MARKET",
                product=PRODUCT,
            )

            if response.get("status") == "success":
                order_id = response.get("orderid")
                print(f"[EXIT] Exit order placed. ID: {order_id}")

                exit_price = self.get_executed_price(order_id)

                if exit_price:
                    if self.position == "BUY":
                        pnl = (exit_price - self.entry_price) * QUANTITY
                    else:
                        pnl = (self.entry_price - exit_price) * QUANTITY

                    print("\n" + "=" * 60)
                    print(" POSITION CLOSED")
                    print("=" * 60)
                    print(f" Reason: {reason}")
                    print(f" Exit Price: Rs.{exit_price:.2f}")
                    print(f" Entry Price: Rs.{self.entry_price:.2f}")
                    print(f" P&L: Rs.{pnl:.2f} [{'PROFIT' if pnl > 0 else 'LOSS'}]")
                    print("=" * 60)
                else:
                    print("[WARNING] Exit order placed but could not confirm price")

                # Reset position regardless
                self.position = None
                self.entry_price = 0
                self.stoploss_price = 0
                self.target_price = 0
                self.exit_in_progress = False

            else:
                print(f"[ERROR] Exit order failed: {response}")
                self.exit_in_progress = False  # Allow retry

        except Exception as e:
            print(f"[ERROR] Failed to exit: {e}")
            self.exit_in_progress = False  # Allow retry

    # ===========================================================================
    # STRATEGY THREAD
    # ===========================================================================

    def strategy_thread(self):
        """Strategy thread for signal generation only (exit handled by WebSocket)"""
        print("[STRATEGY] Strategy thread started")
        print(f"[STRATEGY] Direction: {TRADE_DIRECTION} trades only")
        print(f"[STRATEGY] Checking signals every {SIGNAL_CHECK_INTERVAL} seconds")
        print(f"[STRATEGY] Using {self.lookback_days} days of historical data")

        initial_data_fetched = False

        while not self.stop_event.is_set():
            try:
                if not self.position and not self.exit_in_progress:
                    data = self.get_historical_data()

                    if data is not None:
                        if not initial_data_fetched:
                            print(f"[STRATEGY] Initial data loaded: {len(data)} candles")
                            initial_data_fetched = True

                        signal = self.check_for_signal(data)
                        if signal:
                            self.place_entry_order(signal)
                    else:
                        if not initial_data_fetched:
                            print("[WARNING] Waiting for historical data...")

                time.sleep(SIGNAL_CHECK_INTERVAL)

            except Exception as e:
                print(f"\n[ERROR] Strategy error: {e}")
                time.sleep(10)

    # ===========================================================================
    # MAIN RUN METHOD
    # ===========================================================================

    def run(self):
        """Main method to run the bot"""
        print("=" * 60)
        print(" EMA CROSSOVER BOT")
        print("=" * 60)
        print(f" Symbol: {SYMBOL} | Exchange: {EXCHANGE}")
        print(f" Strategy: {FAST_EMA_PERIOD} EMA x {SLOW_EMA_PERIOD} EMA")
        print(f" Direction: {TRADE_DIRECTION} trades only")
        print(f" Risk: SL Rs.{STOPLOSS} | Target Rs.{TARGET}")
        print(f" Timeframe: {CANDLE_TIMEFRAME}")
        print(f" Lookback: {self.lookback_days} days")
        print(f" Signal Check: Every {SIGNAL_CHECK_INTERVAL} seconds")
        print("=" * 60)

        if TRADE_DIRECTION == "LONG":
            print(" [MODE] LONG ONLY - Will only take BUY trades")
        elif TRADE_DIRECTION == "SHORT":
            print(" [MODE] SHORT ONLY - Will only take SELL trades")
        else:
            print(" [MODE] BOTH - Will take both BUY and SELL trades")

        print("=" * 60)
        print("\nPress Ctrl+C to stop the bot\n")

        ws_thread = threading.Thread(target=self.websocket_thread, daemon=True)
        ws_thread.start()

        # Give WebSocket time to connect
        time.sleep(2)

        strat_thread = threading.Thread(target=self.strategy_thread, daemon=True)
        strat_thread.start()

        try:
            while self.running:
                time.sleep(1)

        except KeyboardInterrupt:
            print("\n\n[SHUTDOWN] Shutting down bot...")
            self.running = False
            self.stop_event.set()

            if self.position and not self.exit_in_progress:
                print("[INFO] Closing open position before shutdown...")
                self.place_exit_order("Bot Shutdown")

            ws_thread.join(timeout=5)
            strat_thread.join(timeout=5)

            print("[SUCCESS] Bot stopped successfully!")


# ===============================================================================
# START THE BOT
# ===============================================================================

if __name__ == "__main__":
    if not API_KEY or API_KEY == "openalgo-apikey":
        print(
            "[WARNING] OPENALGO_API_KEY is not set in environment. "
            "Set it before running in live mode."
        )

    print("\n" + "=" * 60)
    print(" OPENALGO EMA STRATEGY - READY TO RUN")
    print("=" * 60)
    print(f" Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f" Mode: {TRADE_DIRECTION}")
    print(f" Lookback: {LOOKBACK_DAYS} days")
    print("=" * 60 + "\n")

    bot = ConfigurableEMABot()
    bot.run()
