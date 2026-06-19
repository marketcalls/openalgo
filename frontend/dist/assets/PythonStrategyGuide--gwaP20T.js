import{f as e,n as t}from"./react-vendor-CSdmlVNG.js";import{dt as n,t as r,ut as i}from"./index-DBASeRtM.js";import{n as a,r as o,t as s}from"./alert-CjINttcb.js";import{a as c,i as l,n as u,r as d,t as f}from"./card-BadXfHqy.js";import{i as p,n as m,r as h,t as g}from"./accordion-DG45lRaW.js";var _=e(),v=`"""
===============================================================================
                EMA CROSSOVER WITH FIXED DATETIME HANDLING
                            OpenAlgo Trading Bot
===============================================================================

Run standalone:
    export OPENALGO_API_KEY="your-api-key"
    python emacrossover_strategy_python.py

Run via OpenAlgo's /python strategy runner:
    OPENALGO_API_KEY            : injected per-strategy (PR #1247).
    OPENALGO_STRATEGY_EXCHANGE  : set from the strategy's \`exchange\` config
                                  (NSE / BSE / NFO / BFO / MCX / BCD / CDS / CRYPTO).
                                  Drives both this script's trading exchange and
                                  the host's calendar/holiday gating, so the two
                                  always agree.
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
)                                                 # NSE, BSE, NFO, MCX, etc.
QUANTITY = int(os.getenv("QUANTITY", "1"))        # Number of shares
PRODUCT = os.getenv("PRODUCT", "MIS")             # MIS (Intraday) or CNC (Delivery)

# Strategy Parameters
FAST_EMA_PERIOD = int(os.getenv("FAST_EMA_PERIOD", "2"))
SLOW_EMA_PERIOD = int(os.getenv("SLOW_EMA_PERIOD", "4"))
CANDLE_TIMEFRAME = os.getenv("CANDLE_TIMEFRAME", "5m")

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
# TRADING BOT
# ===============================================================================

class ConfigurableEMABot:
    def __init__(self):
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

        # Strategy name from the platform
        self.strategy_name = os.getenv("STRATEGY_NAME", f"EMA_{TRADE_DIRECTION}")

        print(f"[BOT] Symbol: {SYMBOL} on {EXCHANGE}")
        print(f"[BOT] Strategy: {FAST_EMA_PERIOD} EMA x {SLOW_EMA_PERIOD} EMA")

    # =========================================================================
    # WEBSOCKET HANDLER — real-time SL/Target monitoring
    # =========================================================================

    def on_ltp_update(self, data):
        if data.get("type") == "market_data" and data.get("symbol") == SYMBOL:
            self.ltp = float(data["data"]["ltp"])

            if self.position and not self.exit_in_progress:
                # Check stoploss / target
                exit_reason = None
                if self.position == "BUY":
                    if self.ltp <= self.stoploss_price:
                        exit_reason = "STOPLOSS HIT"
                    elif self.ltp >= self.target_price:
                        exit_reason = "TARGET HIT"
                elif self.position == "SELL":
                    if self.ltp >= self.stoploss_price:
                        exit_reason = "STOPLOSS HIT"
                    elif self.ltp <= self.target_price:
                        exit_reason = "TARGET HIT"

                if exit_reason and not self.exit_in_progress:
                    self.exit_in_progress = True
                    threading.Thread(
                        target=self.place_exit_order, args=(exit_reason,)
                    ).start()

    def websocket_thread(self):
        try:
            self.client.connect()
            self.client.subscribe_ltp(
                self.instrument, on_data_received=self.on_ltp_update
            )
            while not self.stop_event.is_set():
                time.sleep(1)
        except Exception as e:
            print(f"[ERROR] WebSocket error: {e}")
        finally:
            try:
                self.client.unsubscribe_ltp(self.instrument)
                self.client.disconnect()
            except Exception:
                pass

    # =========================================================================
    # TRADING FUNCTIONS
    # =========================================================================

    def get_historical_data(self):
        end_date = datetime.now()
        start_date = end_date - timedelta(days=LOOKBACK_DAYS)
        return self.client.history(
            symbol=SYMBOL,
            exchange=EXCHANGE,
            interval=CANDLE_TIMEFRAME,
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
        )

    def check_for_signal(self, data):
        if data is None or len(data) < SLOW_EMA_PERIOD + 2:
            return None

        data["fast_ema"] = data["close"].ewm(
            span=FAST_EMA_PERIOD, adjust=False
        ).mean()
        data["slow_ema"] = data["close"].ewm(
            span=SLOW_EMA_PERIOD, adjust=False
        ).mean()

        prev = data.iloc[-3]
        last = data.iloc[-2]

        # BUY: fast crosses above slow
        if prev["fast_ema"] <= prev["slow_ema"] and \\
           last["fast_ema"] > last["slow_ema"]:
            if TRADE_DIRECTION in ["LONG", "BOTH"]:
                return "BUY"
        # SELL: fast crosses below slow
        if prev["fast_ema"] >= prev["slow_ema"] and \\
           last["fast_ema"] < last["slow_ema"]:
            if TRADE_DIRECTION in ["SHORT", "BOTH"]:
                return "SELL"
        return None

    def place_entry_order(self, signal):
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
            # ... track position, set SL/target levels
            self.position = signal

    def place_exit_order(self, reason="Manual"):
        exit_action = "SELL" if self.position == "BUY" else "BUY"
        self.client.placeorder(
            strategy=self.strategy_name,
            symbol=SYMBOL,
            exchange=EXCHANGE,
            action=exit_action,
            quantity=QUANTITY,
            price_type="MARKET",
            product=PRODUCT,
        )
        self.position = None
        self.exit_in_progress = False

    # =========================================================================
    # MAIN LOOP
    # =========================================================================

    def run(self):
        # Start WebSocket thread for real-time SL/Target
        ws_thread = threading.Thread(target=self.websocket_thread, daemon=True)
        ws_thread.start()
        time.sleep(2)

        try:
            while self.running:
                if not self.position and not self.exit_in_progress:
                    data = self.get_historical_data()
                    signal = self.check_for_signal(data)
                    if signal:
                        self.place_entry_order(signal)
                time.sleep(SIGNAL_CHECK_INTERVAL)
        except KeyboardInterrupt:
            self.running = False
            self.stop_event.set()
            if self.position:
                self.place_exit_order("Bot Shutdown")

if __name__ == "__main__":
    bot = ConfigurableEMABot()
    bot.run()
`,y=`# API Configuration — auto-injected by the /python runner
API_KEY = os.getenv("OPENALGO_API_KEY", "openalgo-apikey")
API_HOST = os.getenv("HOST_SERVER", "http://127.0.0.1:5000")
WS_URL = os.getenv("WEBSOCKET_URL", "ws://127.0.0.1:8765")

# Exchange — reads OPENALGO_STRATEGY_EXCHANGE so your script
# trades on the same exchange the host gates its calendar against.
EXCHANGE = os.getenv(
    "OPENALGO_STRATEGY_EXCHANGE",
    os.getenv("EXCHANGE", "NSE"),
)

# Strategy identity (for tagging orders/logs)
STRATEGY_NAME = os.getenv("STRATEGY_NAME", "MyStrategy")
STRATEGY_ID = os.getenv("STRATEGY_ID", "")

# All custom parameters from the upload form are also available:
MY_PARAM = os.getenv("MY_PARAM", "default_value")`,b=e=>{navigator.clipboard.writeText(e),r.success(`Copied to clipboard`,`clipboard`)};function x(){return(0,_.jsxs)(`div`,{className:`container mx-auto py-6 space-y-6 max-w-4xl`,children:[(0,_.jsx)(i,{variant:`ghost`,asChild:!0,children:(0,_.jsx)(t,{to:`/python`,children:`← Back to Python Strategies`})}),(0,_.jsxs)(`div`,{className:`space-y-2`,children:[(0,_.jsx)(`h1`,{className:`text-2xl font-bold tracking-tight`,children:`Python Strategy Guide`}),(0,_.jsxs)(`p`,{className:`text-muted-foreground`,children:[`Self-host automated trading strategies inside OpenAlgo. Each strategy runs as an isolated subprocess with its own process, memory, and log file — managed through the`,` `,(0,_.jsx)(t,{to:`/python`,className:`text-primary hover:underline`,children:`/python`}),` `,`dashboard.`]})]}),(0,_.jsxs)(f,{children:[(0,_.jsxs)(l,{children:[(0,_.jsx)(c,{children:`Quick Start`}),(0,_.jsx)(d,{children:`Get your first strategy running in 5 minutes`})]}),(0,_.jsx)(u,{className:`space-y-4`,children:(0,_.jsxs)(`div`,{className:`grid gap-4`,children:[(0,_.jsxs)(`div`,{className:`flex gap-4`,children:[(0,_.jsx)(n,{className:`h-6 w-6 rounded-full flex items-center justify-center shrink-0`,children:`1`}),(0,_.jsxs)(`div`,{children:[(0,_.jsx)(`p`,{className:`font-medium`,children:`Install OpenAlgo SDK`}),(0,_.jsxs)(`div`,{className:`mt-1 flex items-center gap-2`,children:[(0,_.jsx)(`code`,{className:`bg-muted px-2 py-1 rounded text-sm`,children:`pip install openalgo`}),(0,_.jsx)(i,{variant:`ghost`,size:`sm`,onClick:()=>b(`pip install openalgo`),children:`Copy`})]})]})]}),(0,_.jsxs)(`div`,{className:`flex gap-4`,children:[(0,_.jsx)(n,{className:`h-6 w-6 rounded-full flex items-center justify-center shrink-0`,children:`2`}),(0,_.jsxs)(`div`,{children:[(0,_.jsx)(`p`,{className:`font-medium`,children:`Get your API Key`}),(0,_.jsxs)(`p`,{className:`text-sm text-muted-foreground`,children:[`Go to`,` `,(0,_.jsx)(t,{to:`/apikey`,className:`text-primary hover:underline`,children:`API Key`}),` `,`page and copy your OpenAlgo API key`]})]})]}),(0,_.jsxs)(`div`,{className:`flex gap-4`,children:[(0,_.jsx)(n,{className:`h-6 w-6 rounded-full flex items-center justify-center shrink-0`,children:`3`}),(0,_.jsxs)(`div`,{children:[(0,_.jsx)(`p`,{className:`font-medium`,children:`Write your strategy`}),(0,_.jsx)(`p`,{className:`text-sm text-muted-foreground`,children:`Create a Python file (.py) with your trading logic. Read configuration from environment variables so it works both standalone and under the /python runner without edits. See the sample strategy below.`})]})]}),(0,_.jsxs)(`div`,{className:`flex gap-4`,children:[(0,_.jsx)(n,{className:`h-6 w-6 rounded-full flex items-center justify-center shrink-0`,children:`4`}),(0,_.jsxs)(`div`,{children:[(0,_.jsx)(`p`,{className:`font-medium`,children:`Upload and configure`}),(0,_.jsxs)(`p`,{className:`text-sm text-muted-foreground`,children:[`On the`,` `,(0,_.jsx)(t,{to:`/python`,className:`text-primary hover:underline`,children:`Python Strategies`}),` `,`page, click `,(0,_.jsx)(`strong`,{children:`Add Strategy`}),`. Pick a name, select the exchange (NSE / MCX / CRYPTO / etc.), and add any custom parameters as environment variables.`]})]})]}),(0,_.jsxs)(`div`,{className:`flex gap-4`,children:[(0,_.jsx)(n,{className:`h-6 w-6 rounded-full flex items-center justify-center shrink-0`,children:`5`}),(0,_.jsxs)(`div`,{children:[(0,_.jsx)(`p`,{className:`font-medium`,children:`Start or schedule`}),(0,_.jsxs)(`p`,{className:`text-sm text-muted-foreground`,children:[`Click `,(0,_.jsx)(`strong`,{children:`Start`}),` to run immediately, or configure a schedule (e.g. 09:15–15:30 Mon–Fri for NSE). The host auto-starts and auto-stops your strategy at the scheduled times, respecting the exchange's holiday calendar.`]})]})]})]})})]}),(0,_.jsxs)(f,{children:[(0,_.jsxs)(l,{children:[(0,_.jsx)(c,{children:`How It Works`}),(0,_.jsx)(d,{children:`Process isolation, environment injection, and exchange-aware scheduling`})]}),(0,_.jsx)(u,{className:`space-y-4 text-sm`,children:(0,_.jsxs)(`div`,{className:`space-y-3`,children:[(0,_.jsxs)(`div`,{className:`bg-muted p-3 rounded-lg`,children:[(0,_.jsx)(`p`,{className:`font-medium mb-1`,children:`Process Isolation`}),(0,_.jsxs)(`p`,{className:`text-muted-foreground`,children:[`Each strategy runs as a separate `,(0,_.jsx)(`code`,{children:`subprocess.Popen`}),` process with its own PID, memory, and file descriptors. A crash in one strategy cannot affect another or the host.`]})]}),(0,_.jsxs)(`div`,{className:`bg-muted p-3 rounded-lg`,children:[(0,_.jsx)(`p`,{className:`font-medium mb-1`,children:`Environment Injection`}),(0,_.jsxs)(`p`,{className:`text-muted-foreground`,children:[`The host injects `,(0,_.jsx)(`code`,{children:`OPENALGO_API_KEY`}),`, `,(0,_.jsx)(`code`,{children:`STRATEGY_ID`}),`,`,` `,(0,_.jsx)(`code`,{children:`STRATEGY_NAME`}),`, and `,(0,_.jsx)(`code`,{children:`OPENALGO_STRATEGY_EXCHANGE`}),` into each strategy's environment. Your `,(0,_.jsx)(`code`,{children:`.env`}),` variables (like`,` `,(0,_.jsx)(`code`,{children:`HOST_SERVER`}),`, `,(0,_.jsx)(`code`,{children:`WEBSOCKET_URL`}),`) are also inherited. Custom parameters from the upload form become additional env vars.`]})]}),(0,_.jsxs)(`div`,{className:`bg-muted p-3 rounded-lg`,children:[(0,_.jsx)(`p`,{className:`font-medium mb-1`,children:`Exchange-Aware Calendar`}),(0,_.jsx)(`p`,{className:`text-muted-foreground`,children:`Each strategy is tagged with an exchange. The host uses that exchange's holiday calendar to gate scheduled start/stop — an MCX strategy keeps running on an NSE holiday during the MCX evening session, a CRYPTO strategy ignores all holidays.`})]}),(0,_.jsxs)(`div`,{className:`bg-muted p-3 rounded-lg`,children:[(0,_.jsx)(`p`,{className:`font-medium mb-1`,children:`Logging`}),(0,_.jsxs)(`p`,{className:`text-muted-foreground`,children:[`All `,(0,_.jsx)(`code`,{children:`print()`}),` output is captured in timestamped log files under`,` `,(0,_.jsx)(`code`,{children:`log/strategies/`}),`. View them from the dashboard or via the Logs button on each strategy card.`]})]})]})})]}),(0,_.jsxs)(f,{children:[(0,_.jsxs)(l,{children:[(0,_.jsx)(c,{children:`Environment Variables`}),(0,_.jsx)(d,{children:`Variables available inside your strategy script`})]}),(0,_.jsxs)(u,{className:`space-y-5`,children:[(0,_.jsxs)(`div`,{children:[(0,_.jsx)(`p`,{className:`font-medium mb-2`,children:`Injected by the Platform`}),(0,_.jsx)(`p`,{className:`text-sm text-muted-foreground mb-3`,children:`These are set directly on each strategy subprocess by the /python runner:`}),(0,_.jsx)(`div`,{className:`overflow-x-auto`,children:(0,_.jsxs)(`table`,{className:`w-full text-sm border-collapse`,children:[(0,_.jsx)(`thead`,{children:(0,_.jsxs)(`tr`,{className:`border-b`,children:[(0,_.jsx)(`th`,{className:`text-left py-2 pr-4 font-medium`,children:`Variable`}),(0,_.jsx)(`th`,{className:`text-left py-2 font-medium`,children:`Description`})]})}),(0,_.jsxs)(`tbody`,{className:`text-muted-foreground`,children:[(0,_.jsxs)(`tr`,{className:`border-b`,children:[(0,_.jsx)(`td`,{className:`py-2 pr-4`,children:(0,_.jsx)(`code`,{children:`OPENALGO_API_KEY`})}),(0,_.jsx)(`td`,{className:`py-2`,children:`Decrypted API key for this user`})]}),(0,_.jsxs)(`tr`,{className:`border-b`,children:[(0,_.jsx)(`td`,{className:`py-2 pr-4`,children:(0,_.jsx)(`code`,{children:`STRATEGY_ID`})}),(0,_.jsx)(`td`,{className:`py-2`,children:`Unique identifier for this strategy`})]}),(0,_.jsxs)(`tr`,{className:`border-b`,children:[(0,_.jsx)(`td`,{className:`py-2 pr-4`,children:(0,_.jsx)(`code`,{children:`STRATEGY_NAME`})}),(0,_.jsx)(`td`,{className:`py-2`,children:`Name of the strategy (as entered at upload)`})]}),(0,_.jsxs)(`tr`,{className:`border-b`,children:[(0,_.jsx)(`td`,{className:`py-2 pr-4`,children:(0,_.jsx)(`code`,{children:`OPENALGO_STRATEGY_EXCHANGE`})}),(0,_.jsx)(`td`,{className:`py-2`,children:`Exchange picked at upload/edit (NSE / BSE / NFO / BFO / MCX / BCD / CDS / CRYPTO). Read this so your trading calls match the calendar the host gates against`})]}),(0,_.jsxs)(`tr`,{className:`border-b`,children:[(0,_.jsx)(`td`,{className:`py-2 pr-4`,children:(0,_.jsx)(`code`,{children:`OPENALGO_HOST`})}),(0,_.jsxs)(`td`,{className:`py-2`,children:[`Convenience fallback (`,(0,_.jsx)(`code`,{children:`http://127.0.0.1:5000`}),`). Prefer`,` `,(0,_.jsx)(`code`,{children:`HOST_SERVER`}),` instead`]})]})]})]})})]}),(0,_.jsxs)(`div`,{children:[(0,_.jsx)(`p`,{className:`font-medium mb-2`,children:`Inherited from .env`}),(0,_.jsxs)(`p`,{className:`text-sm text-muted-foreground mb-3`,children:[`Strategies inherit every variable from OpenAlgo's `,(0,_.jsx)(`code`,{children:`.env`}),` via`,` `,(0,_.jsx)(`code`,{children:`os.environ.copy()`}),`. The key ones for connecting back to OpenAlgo:`]}),(0,_.jsx)(`div`,{className:`overflow-x-auto`,children:(0,_.jsxs)(`table`,{className:`w-full text-sm border-collapse`,children:[(0,_.jsx)(`thead`,{children:(0,_.jsxs)(`tr`,{className:`border-b`,children:[(0,_.jsx)(`th`,{className:`text-left py-2 pr-4 font-medium`,children:`Variable`}),(0,_.jsx)(`th`,{className:`text-left py-2 font-medium`,children:`Description`})]})}),(0,_.jsxs)(`tbody`,{className:`text-muted-foreground`,children:[(0,_.jsxs)(`tr`,{className:`border-b`,children:[(0,_.jsx)(`td`,{className:`py-2 pr-4`,children:(0,_.jsx)(`code`,{children:`HOST_SERVER`})}),(0,_.jsxs)(`td`,{className:`py-2`,children:[`REST host, e.g. `,(0,_.jsx)(`code`,{children:`http://127.0.0.1:5000`}),` — canonical name in`,` `,(0,_.jsx)(`code`,{children:`.env`}),`, prefer this in scripts`]})]}),(0,_.jsxs)(`tr`,{className:`border-b`,children:[(0,_.jsx)(`td`,{className:`py-2 pr-4`,children:(0,_.jsx)(`code`,{children:`WEBSOCKET_URL`})}),(0,_.jsxs)(`td`,{className:`py-2`,children:[`Full WebSocket URL, e.g. `,(0,_.jsx)(`code`,{children:`ws://127.0.0.1:8765`})]})]}),(0,_.jsxs)(`tr`,{className:`border-b`,children:[(0,_.jsx)(`td`,{className:`py-2 pr-4`,children:(0,_.jsx)(`code`,{children:`WEBSOCKET_HOST`})}),(0,_.jsxs)(`td`,{className:`py-2`,children:[`WebSocket host component, e.g. `,(0,_.jsx)(`code`,{children:`127.0.0.1`})]})]}),(0,_.jsxs)(`tr`,{className:`border-b`,children:[(0,_.jsx)(`td`,{className:`py-2 pr-4`,children:(0,_.jsx)(`code`,{children:`WEBSOCKET_PORT`})}),(0,_.jsxs)(`td`,{className:`py-2`,children:[`WebSocket port, e.g. `,(0,_.jsx)(`code`,{children:`8765`})]})]}),(0,_.jsxs)(`tr`,{className:`border-b`,children:[(0,_.jsxs)(`td`,{className:`py-2 pr-4`,children:[(0,_.jsx)(`code`,{children:`FLASK_HOST_IP`}),` / `,(0,_.jsx)(`code`,{children:`FLASK_PORT`})]}),(0,_.jsx)(`td`,{className:`py-2`,children:`Flask binding address (available if you need raw components)`})]})]})]})})]}),(0,_.jsxs)(`div`,{children:[(0,_.jsx)(`p`,{className:`font-medium mb-2`,children:`Recommended Pattern in Scripts`}),(0,_.jsxs)(`div`,{className:`relative`,children:[(0,_.jsx)(i,{variant:`outline`,size:`sm`,className:`absolute top-2 right-2 z-10`,onClick:()=>b(y),children:`Copy`}),(0,_.jsx)(`pre`,{className:`bg-muted p-4 rounded-lg overflow-x-auto text-xs`,children:(0,_.jsx)(`code`,{children:y})})]})]}),(0,_.jsxs)(s,{children:[(0,_.jsx)(o,{children:`Reading OPENALGO_STRATEGY_EXCHANGE is strongly recommended`}),(0,_.jsxs)(a,{children:[`If your script hardcodes `,(0,_.jsx)(`code`,{children:`exchange = "NSE"`}),`, the host will still gate it correctly per its config (e.g. the host runs your script during the MCX evening session because `,(0,_.jsx)(`code`,{children:`exchange=MCX`}),`), but your`,` `,(0,_.jsx)(`code`,{children:`client.placeorder(exchange="NSE", ...)`}),` calls will still send NSE orders — and the broker will reject them. Wiring the env var keeps host calendar and script orders aligned.`]})]})]})]}),(0,_.jsxs)(f,{children:[(0,_.jsxs)(l,{children:[(0,_.jsx)(c,{children:`Exchange-Aware Scheduling`}),(0,_.jsx)(d,{children:`Each strategy's exchange drives which holiday calendar the host uses`})]}),(0,_.jsxs)(u,{className:`space-y-5`,children:[(0,_.jsxs)(`div`,{className:`space-y-3 text-sm`,children:[(0,_.jsx)(`p`,{className:`text-muted-foreground`,children:`When you upload or edit a strategy, you pick an exchange. The host uses that exchange's calendar to decide whether to start/stop the strategy on any given day. This means:`}),(0,_.jsxs)(`ul`,{className:`list-disc list-inside space-y-1 ml-2 text-muted-foreground`,children:[(0,_.jsxs)(`li`,{children:[`An `,(0,_.jsx)(`strong`,{children:`MCX`}),` strategy keeps running on NSE/BSE holidays if MCX has a session`]}),(0,_.jsxs)(`li`,{children:[`A `,(0,_.jsx)(`strong`,{children:`CRYPTO`}),` strategy ignores all holidays and weekends (24/7)`]}),(0,_.jsxs)(`li`,{children:[(0,_.jsx)(`strong`,{children:`SPECIAL_SESSION`}),` rows (Muhurat, DR-drill) override weekend rejects per-exchange`]})]})]}),(0,_.jsxs)(`div`,{children:[(0,_.jsx)(`p`,{className:`font-medium mb-2`,children:`Supported Exchanges`}),(0,_.jsxs)(`div`,{className:`grid grid-cols-1 sm:grid-cols-2 gap-2 text-sm`,children:[(0,_.jsxs)(`div`,{className:`bg-muted p-2 rounded`,children:[(0,_.jsx)(`strong`,{children:`NSE`}),` — Equity (09:15–15:30)`]}),(0,_.jsxs)(`div`,{className:`bg-muted p-2 rounded`,children:[(0,_.jsx)(`strong`,{children:`BSE`}),` — Equity (09:15–15:30)`]}),(0,_.jsxs)(`div`,{className:`bg-muted p-2 rounded`,children:[(0,_.jsx)(`strong`,{children:`NFO`}),` — NSE F&O (09:15–15:30)`]}),(0,_.jsxs)(`div`,{className:`bg-muted p-2 rounded`,children:[(0,_.jsx)(`strong`,{children:`BFO`}),` — BSE F&O (09:15–15:30)`]}),(0,_.jsxs)(`div`,{className:`bg-muted p-2 rounded`,children:[(0,_.jsx)(`strong`,{children:`CDS`}),` — NSE Currency (09:00–17:00)`]}),(0,_.jsxs)(`div`,{className:`bg-muted p-2 rounded`,children:[(0,_.jsx)(`strong`,{children:`BCD`}),` — BSE Currency (09:00–17:00)`]}),(0,_.jsxs)(`div`,{className:`bg-muted p-2 rounded`,children:[(0,_.jsx)(`strong`,{children:`MCX`}),` — Commodity (09:00–23:55)`]}),(0,_.jsxs)(`div`,{className:`bg-muted p-2 rounded`,children:[(0,_.jsx)(`strong`,{children:`CRYPTO`}),` — 24/7 (no holidays)`]})]}),(0,_.jsx)(`p`,{className:`text-xs text-muted-foreground mt-2`,children:`Timings shown are defaults. Per-date overrides (partial holidays, special sessions) come from the market calendar DB.`})]}),(0,_.jsxs)(`div`,{children:[(0,_.jsx)(`p`,{className:`font-medium mb-2`,children:`Schedule Intersection Rule`}),(0,_.jsxs)(`p`,{className:`text-sm text-muted-foreground mb-3`,children:[`The effective trading window is the `,(0,_.jsx)(`strong`,{children:`intersection`}),` of your`,` `,(0,_.jsx)(`code`,{children:`start..stop`}),` time and the exchange's session for that specific date.`]}),(0,_.jsxs)(`div`,{className:`bg-muted p-3 rounded-lg text-sm space-y-1`,children:[(0,_.jsxs)(`p`,{children:[(0,_.jsx)(`strong`,{children:`Example:`}),` MCX strategy scheduled 09:15–23:55`]}),(0,_.jsxs)(`p`,{className:`text-muted-foreground`,children:[`On 14-Apr-2026 (Ambedkar Jayanti), MCX has a partial holiday with an evening session 17:00–23:55. The effective window becomes `,(0,_.jsx)(`strong`,{children:`17:00–23:55`}),` `,`(the intersection). You don't need to change the schedule for partial holidays.`]})]})]}),(0,_.jsxs)(`div`,{children:[(0,_.jsx)(`p`,{className:`font-medium mb-3`,children:`Worked Examples`}),(0,_.jsx)(`div`,{className:`overflow-x-auto`,children:(0,_.jsxs)(`table`,{className:`w-full text-sm border-collapse`,children:[(0,_.jsx)(`thead`,{children:(0,_.jsxs)(`tr`,{className:`border-b`,children:[(0,_.jsx)(`th`,{className:`text-left py-2 pr-3 font-medium`,children:`Scenario`}),(0,_.jsx)(`th`,{className:`text-left py-2 pr-3 font-medium`,children:`Exchange`}),(0,_.jsx)(`th`,{className:`text-left py-2 font-medium`,children:`Strategy Behavior`})]})}),(0,_.jsxs)(`tbody`,{className:`text-muted-foreground`,children:[(0,_.jsxs)(`tr`,{className:`border-b`,children:[(0,_.jsxs)(`td`,{className:`py-2 pr-3`,rowSpan:3,children:[(0,_.jsx)(`strong`,{children:`14-Apr-2026`}),(0,_.jsx)(`br`,{}),(0,_.jsx)(`span`,{className:`text-xs`,children:`Ambedkar Jayanti`})]}),(0,_.jsx)(`td`,{className:`py-2 pr-3`,children:`NSE / BSE / NFO`}),(0,_.jsx)(`td`,{className:`py-2`,children:`Closed all day. Strategies paused at 00:01 IST`})]}),(0,_.jsxs)(`tr`,{className:`border-b`,children:[(0,_.jsx)(`td`,{className:`py-2 pr-3`,children:`MCX`}),(0,_.jsx)(`td`,{className:`py-2`,children:`Open 17:00–23:55. MCX strategies auto-start at 17:00`})]}),(0,_.jsxs)(`tr`,{className:`border-b`,children:[(0,_.jsx)(`td`,{className:`py-2 pr-3`,children:`CRYPTO`}),(0,_.jsx)(`td`,{className:`py-2`,children:`Unaffected (24/7)`})]}),(0,_.jsxs)(`tr`,{className:`border-b`,children:[(0,_.jsxs)(`td`,{className:`py-2 pr-3`,rowSpan:3,children:[(0,_.jsx)(`strong`,{children:`8-Nov-2026`}),(0,_.jsx)(`br`,{}),(0,_.jsx)(`span`,{className:`text-xs`,children:`Sunday Diwali Muhurat`})]}),(0,_.jsx)(`td`,{className:`py-2 pr-3`,children:`NSE / BSE / NFO`}),(0,_.jsx)(`td`,{className:`py-2`,children:`SPECIAL_SESSION 18:00–19:15. Runs only inside that window, despite being Sunday`})]}),(0,_.jsxs)(`tr`,{className:`border-b`,children:[(0,_.jsx)(`td`,{className:`py-2 pr-3`,children:`MCX`}),(0,_.jsx)(`td`,{className:`py-2`,children:`SPECIAL_SESSION 18:00–00:15 next day`})]}),(0,_.jsxs)(`tr`,{className:`border-b`,children:[(0,_.jsx)(`td`,{className:`py-2 pr-3`,children:`CRYPTO`}),(0,_.jsx)(`td`,{className:`py-2`,children:`Unaffected (24/7)`})]})]})]})})]}),(0,_.jsxs)(`div`,{children:[(0,_.jsx)(`p`,{className:`font-medium mb-2`,children:`How the Host Gates Strategies`}),(0,_.jsxs)(`div`,{className:`space-y-2 text-sm text-muted-foreground`,children:[(0,_.jsxs)(`div`,{className:`bg-muted p-3 rounded-lg`,children:[(0,_.jsx)(`strong`,{children:`1. Cron job`}),` — Fires `,(0,_.jsx)(`code`,{children:`start_<sid>`}),` at your`,` `,(0,_.jsx)(`code`,{children:`start_time`}),` on each day in `,(0,_.jsx)(`code`,{children:`schedule_days`}),`.`]}),(0,_.jsxs)(`div`,{className:`bg-muted p-3 rounded-lg`,children:[(0,_.jsx)(`strong`,{children:`2. Daily check (00:01 IST)`}),` — For each scheduled strategy, looks up `,(0,_.jsx)(`code`,{children:`get_market_status(config["exchange"])`}),`. If the exchange has no session today, the strategy is stopped and marked`,` `,(0,_.jsx)(`code`,{children:`paused_reason=holiday|weekend`}),`.`]}),(0,_.jsxs)(`div`,{className:`bg-muted p-3 rounded-lg`,children:[(0,_.jsx)(`strong`,{children:`3. Per-minute enforcer`}),` — Same per-strategy check. When the exchange reopens (or a special session starts), previously-paused strategies are auto-resumed (unless `,(0,_.jsx)(`code`,{children:`manually_stopped`}),`).`]})]})]}),(0,_.jsxs)(`div`,{className:`bg-primary/10 border border-primary/20 p-3 rounded-lg text-sm`,children:[(0,_.jsx)(`p`,{className:`font-medium text-primary`,children:`Smart Defaults When Uploading`}),(0,_.jsx)(`p`,{className:`text-muted-foreground mt-1`,children:`Picking an exchange pre-fills sensible defaults: CRYPTO auto-selects all 7 days and 00:00–23:59, MCX defaults to 09:00–23:55 weekdays, and equity exchanges default to 09:15–15:30 Mon–Fri.`})]})]})]}),(0,_.jsxs)(f,{children:[(0,_.jsxs)(l,{children:[(0,_.jsx)(c,{children:`Sample Strategy: EMA Crossover`}),(0,_.jsxs)(d,{children:[`WebSocket-driven EMA crossover with real-time SL/target monitoring. All config is overridable via env vars — works standalone and under the /python runner without edits. Full version at `,(0,_.jsx)(`code`,{children:`examples/python/emacrossover_strategy_python.py`})]})]}),(0,_.jsx)(u,{children:(0,_.jsxs)(`div`,{className:`relative`,children:[(0,_.jsx)(i,{variant:`outline`,size:`sm`,className:`absolute top-2 right-2 z-10`,onClick:()=>b(v),children:`Copy`}),(0,_.jsx)(`pre`,{className:`bg-muted p-4 rounded-lg overflow-x-auto text-xs max-h-[32rem] overflow-y-auto`,children:(0,_.jsx)(`code`,{children:v})})]})})]}),(0,_.jsxs)(f,{children:[(0,_.jsx)(l,{children:(0,_.jsx)(c,{children:`Frequently Asked Questions`})}),(0,_.jsx)(u,{children:(0,_.jsxs)(g,{type:`single`,collapsible:!0,className:`w-full`,children:[(0,_.jsxs)(h,{value:`logs`,children:[(0,_.jsx)(p,{children:`How do I see my strategy logs?`}),(0,_.jsxs)(m,{className:`text-muted-foreground space-y-2`,children:[(0,_.jsxs)(`p`,{children:[`All `,(0,_.jsx)(`code`,{children:`print()`}),` statements in your strategy are captured in log files.`]}),(0,_.jsx)(`p`,{children:`To view logs:`}),(0,_.jsxs)(`ol`,{className:`list-decimal list-inside space-y-1 ml-2`,children:[(0,_.jsxs)(`li`,{children:[`Click the `,(0,_.jsx)(`strong`,{children:`Logs`}),` button on your strategy card`]}),(0,_.jsx)(`li`,{children:`Select a log file from the list (newest first)`}),(0,_.jsxs)(`li`,{children:[`Enable `,(0,_.jsx)(`strong`,{children:`Auto-refresh`}),` to see live updates while running`]})]}),(0,_.jsxs)(`p`,{className:`text-sm`,children:[`Log files are stored in: `,(0,_.jsx)(`code`,{children:`log/strategies/`}),`. Per-strategy limits: max`,` `,`{`,`STRATEGY_LOG_MAX_FILES`,`}`,` files, `,`{`,`STRATEGY_LOG_MAX_SIZE_MB`,`}`,` MB total, retained for `,`{`,`STRATEGY_LOG_RETENTION_DAYS`,`}`,` days. Override these in`,` `,(0,_.jsx)(`code`,{children:`.env`}),`.`]})]})]}),(0,_.jsxs)(h,{value:`scheduling`,children:[(0,_.jsx)(p,{children:`How does scheduling work?`}),(0,_.jsxs)(m,{className:`text-muted-foreground space-y-3`,children:[(0,_.jsx)(`p`,{children:`Every strategy has a schedule that controls when the host automatically starts and stops it.`}),(0,_.jsxs)(`div`,{className:`space-y-2`,children:[(0,_.jsx)(`p`,{className:`font-medium`,children:`Schedule Configuration:`}),(0,_.jsxs)(`ul`,{className:`list-disc list-inside space-y-1 ml-2`,children:[(0,_.jsxs)(`li`,{children:[(0,_.jsx)(`strong`,{children:`Exchange:`}),` Drives the holiday calendar (NSE / MCX / CRYPTO / etc.)`]}),(0,_.jsxs)(`li`,{children:[(0,_.jsx)(`strong`,{children:`Start Time:`}),` When the strategy auto-starts (IST, 24-hour format)`]}),(0,_.jsxs)(`li`,{children:[(0,_.jsx)(`strong`,{children:`Stop Time:`}),` When to auto-stop (IST, 24-hour format)`]}),(0,_.jsxs)(`li`,{children:[(0,_.jsx)(`strong`,{children:`Days:`}),` Which days to run (can include weekends for special sessions)`]})]})]}),(0,_.jsxs)(`div`,{className:`bg-muted p-3 rounded-lg space-y-2 text-sm`,children:[(0,_.jsx)(`p`,{className:`font-medium`,children:`Example Schedules:`}),(0,_.jsxs)(`ul`,{className:`list-disc list-inside space-y-1 ml-2`,children:[(0,_.jsx)(`li`,{children:`NSE EMA strategy: 09:15–15:30, Mon–Fri`}),(0,_.jsx)(`li`,{children:`MCX evening strategy: 17:00–23:55, Mon–Fri`}),(0,_.jsx)(`li`,{children:`CRYPTO arb: 00:00–23:59, all 7 days`})]})]}),(0,_.jsxs)(s,{children:[(0,_.jsx)(o,{children:`Holiday & Weekend Protection`}),(0,_.jsx)(a,{children:`The host checks each strategy's exchange calendar before starting it. An NSE strategy won't start on NSE holidays, even if scheduled. Weekend strategies are blocked unless the calendar has a SPECIAL_SESSION row for that exchange on that date, or the exchange is CRYPTO (always open).`})]})]})]}),(0,_.jsxs)(h,{value:`status-indicators`,children:[(0,_.jsx)(p,{children:`What do the status indicators mean?`}),(0,_.jsxs)(m,{className:`text-muted-foreground space-y-3`,children:[(0,_.jsx)(`p`,{children:`Each strategy displays a status badge showing its current state:`}),(0,_.jsxs)(`div`,{className:`space-y-2`,children:[(0,_.jsxs)(`div`,{className:`flex items-center gap-3 p-2 bg-muted rounded`,children:[(0,_.jsx)(n,{className:`bg-green-500 text-white`,children:`Running`}),(0,_.jsx)(`span`,{className:`text-sm`,children:`Strategy is actively running and executing trades`})]}),(0,_.jsxs)(`div`,{className:`flex items-center gap-3 p-2 bg-muted rounded`,children:[(0,_.jsx)(n,{className:`bg-blue-500 text-white`,children:`Scheduled`}),(0,_.jsxs)(`div`,{className:`text-sm`,children:[(0,_.jsx)(`p`,{children:`Strategy is armed and will auto-start at the scheduled time`}),(0,_.jsx)(`p`,{className:`text-xs text-muted-foreground mt-1`,children:`Shows context: "Starts today at 9:15 IST" or "Next: Mon, Tue at 9:15 IST"`})]})]}),(0,_.jsxs)(`div`,{className:`flex items-center gap-3 p-2 bg-muted rounded`,children:[(0,_.jsx)(n,{className:`bg-orange-500 text-white`,children:`Manual Stop`}),(0,_.jsx)(`span`,{className:`text-sm`,children:`Strategy was manually stopped — won't auto-start until you click Start`})]}),(0,_.jsxs)(`div`,{className:`flex items-center gap-3 p-2 bg-muted rounded`,children:[(0,_.jsx)(n,{className:`bg-yellow-500 text-white`,children:`Paused`}),(0,_.jsx)(`span`,{className:`text-sm`,children:`Strategy is paused due to market holiday for its exchange`})]}),(0,_.jsxs)(`div`,{className:`flex items-center gap-3 p-2 bg-muted rounded`,children:[(0,_.jsx)(n,{className:`bg-red-500 text-white`,children:`Error`}),(0,_.jsx)(`span`,{className:`text-sm`,children:`Strategy encountered an error and crashed`})]})]})]})]}),(0,_.jsxs)(h,{value:`start-stop`,children:[(0,_.jsx)(p,{children:`How does Start and Stop work?`}),(0,_.jsxs)(m,{className:`text-muted-foreground space-y-3`,children:[(0,_.jsxs)(`div`,{className:`bg-green-500/10 border border-green-500/20 p-3 rounded-lg`,children:[(0,_.jsx)(`p`,{className:`font-medium text-green-600`,children:`Start Button`}),(0,_.jsxs)(`ul`,{className:`list-disc list-inside space-y-1 ml-2 mt-2 text-sm`,children:[(0,_.jsxs)(`li`,{children:[(0,_.jsx)(`strong`,{children:`Within schedule:`}),` Strategy starts running immediately`]}),(0,_.jsxs)(`li`,{children:[(0,_.jsx)(`strong`,{children:`Outside schedule:`}),` Strategy is "armed" — status changes to "Scheduled"`]}),(0,_.jsxs)(`li`,{children:[`Button changes to `,(0,_.jsx)(`strong`,{children:`Cancel`}),` after arming`]})]})]}),(0,_.jsxs)(`div`,{className:`bg-red-500/10 border border-red-500/20 p-3 rounded-lg`,children:[(0,_.jsx)(`p`,{className:`font-medium text-red-600`,children:`Stop Button (when running)`}),(0,_.jsxs)(`ul`,{className:`list-disc list-inside space-y-1 ml-2 mt-2 text-sm`,children:[(0,_.jsx)(`li`,{children:`Stops the running strategy process (SIGTERM)`}),(0,_.jsx)(`li`,{children:`Sets "manually stopped" flag — won't auto-start`}),(0,_.jsx)(`li`,{children:`Status shows "Manual Stop"`})]})]}),(0,_.jsxs)(`div`,{className:`bg-orange-500/10 border border-orange-500/20 p-3 rounded-lg`,children:[(0,_.jsx)(`p`,{className:`font-medium text-orange-600`,children:`Cancel Button (when scheduled)`}),(0,_.jsxs)(`ul`,{className:`list-disc list-inside space-y-1 ml-2 mt-2 text-sm`,children:[(0,_.jsx)(`li`,{children:`Cancels the scheduled auto-start`}),(0,_.jsx)(`li`,{children:`Sets "manually stopped" flag`}),(0,_.jsx)(`li`,{children:`Click Start again to re-arm`})]})]}),(0,_.jsxs)(`div`,{className:`bg-muted p-3 rounded-lg text-sm`,children:[(0,_.jsx)(`p`,{className:`font-medium`,children:`Use Cases`}),(0,_.jsxs)(`ul`,{className:`list-disc list-inside space-y-1 ml-2 mt-2`,children:[(0,_.jsxs)(`li`,{children:[(0,_.jsx)(`strong`,{children:`Evening setup:`}),` Click Start at night, strategy runs at 9:15 AM next day`]}),(0,_.jsxs)(`li`,{children:[(0,_.jsx)(`strong`,{children:`Vacation mode:`}),` Click Stop, strategy stays off until you return`]}),(0,_.jsxs)(`li`,{children:[(0,_.jsx)(`strong`,{children:`Testing:`}),` Edit schedule to test now, then revert schedule after`]})]})]})]})]}),(0,_.jsxs)(h,{value:`special-sessions`,children:[(0,_.jsx)(p,{children:`What about special trading sessions (Muhurat, Budget Day)?`}),(0,_.jsxs)(m,{className:`text-muted-foreground space-y-3`,children:[(0,_.jsx)(`p`,{children:`Exchanges occasionally conduct special sessions on holidays or weekends. The exchange-aware calendar handles these automatically:`}),(0,_.jsxs)(`div`,{className:`space-y-2 text-sm`,children:[(0,_.jsxs)(`div`,{className:`bg-muted p-3 rounded-lg`,children:[(0,_.jsx)(`p`,{className:`font-medium`,children:`Automatic Handling (Recommended)`}),(0,_.jsxs)(`ol`,{className:`list-decimal list-inside space-y-1 ml-2 mt-2`,children:[(0,_.jsxs)(`li`,{children:[`Go to`,` `,(0,_.jsx)(t,{to:`/admin/holidays`,className:`text-primary hover:underline`,children:`Admin → Holidays`})]}),(0,_.jsxs)(`li`,{children:[`Add a `,(0,_.jsx)(`strong`,{children:`SPECIAL_SESSION`}),` row for the date and exchange with the session timing (e.g. Muhurat: NSE 18:00–19:15)`]}),(0,_.jsxs)(`li`,{children:[`Ensure the relevant day (Sat/Sun) is in your strategy's`,` `,(0,_.jsx)(`code`,{children:`schedule_days`})]}),(0,_.jsx)(`li`,{children:`The host auto-starts the strategy within the special session window — no schedule edits needed, no need to revert afterward`})]})]}),(0,_.jsxs)(`div`,{className:`bg-muted p-3 rounded-lg`,children:[(0,_.jsx)(`p`,{className:`font-medium`,children:`Manual Override`}),(0,_.jsxs)(`p`,{className:`mt-1`,children:[`Log in to OpenAlgo before the session, wait for master contracts to download, and click `,(0,_.jsx)(`strong`,{children:`Start`}),` manually. Click `,(0,_.jsx)(`strong`,{children:`Stop`}),` when the session ends.`]})]})]})]})]}),(0,_.jsxs)(h,{value:`master-contract`,children:[(0,_.jsx)(p,{children:`Why does my strategy need master contracts?`}),(0,_.jsxs)(m,{className:`text-muted-foreground space-y-2`,children:[(0,_.jsx)(`p`,{children:`Master contracts contain the symbol mappings required by your broker. Strategies cannot start until master contracts are downloaded.`}),(0,_.jsx)(`p`,{children:`Master contracts are automatically downloaded when you:`}),(0,_.jsxs)(`ol`,{className:`list-decimal list-inside space-y-1 ml-2`,children:[(0,_.jsx)(`li`,{children:`Log in to OpenAlgo`}),(0,_.jsx)(`li`,{children:`Wait for the download to complete (shown in header)`})]}),(0,_.jsx)(`p`,{className:`text-sm`,children:`If you see "Waiting for master contracts", just wait a moment after login.`})]})]}),(0,_.jsxs)(h,{value:`resource-limits`,children:[(0,_.jsx)(p,{children:`Are there resource limits?`}),(0,_.jsxs)(m,{className:`text-muted-foreground space-y-3`,children:[(0,_.jsx)(`p`,{children:`On Linux/macOS, per-strategy resource limits prevent buggy scripts from crashing OpenAlgo. On Windows, these are not enforced at the OS level.`}),(0,_.jsx)(`div`,{className:`overflow-x-auto`,children:(0,_.jsxs)(`table`,{className:`w-full text-sm border-collapse`,children:[(0,_.jsx)(`thead`,{children:(0,_.jsxs)(`tr`,{className:`border-b`,children:[(0,_.jsx)(`th`,{className:`text-left py-2 pr-4 font-medium`,children:`Resource`}),(0,_.jsx)(`th`,{className:`text-left py-2 pr-4 font-medium`,children:`Default Limit`}),(0,_.jsx)(`th`,{className:`text-left py-2 font-medium`,children:`Override (.env)`})]})}),(0,_.jsxs)(`tbody`,{children:[(0,_.jsxs)(`tr`,{className:`border-b`,children:[(0,_.jsx)(`td`,{className:`py-2 pr-4`,children:`Memory (virtual)`}),(0,_.jsx)(`td`,{className:`py-2 pr-4`,children:`1024 MB`}),(0,_.jsx)(`td`,{className:`py-2`,children:(0,_.jsx)(`code`,{children:`STRATEGY_MEMORY_LIMIT_MB`})})]}),(0,_.jsxs)(`tr`,{className:`border-b`,children:[(0,_.jsx)(`td`,{className:`py-2 pr-4`,children:`CPU time (cumulative)`}),(0,_.jsx)(`td`,{className:`py-2 pr-4`,children:`3600 seconds`}),(0,_.jsx)(`td`,{className:`py-2`,children:`Hardcoded`})]}),(0,_.jsxs)(`tr`,{className:`border-b`,children:[(0,_.jsx)(`td`,{className:`py-2 pr-4`,children:`Open file descriptors`}),(0,_.jsx)(`td`,{className:`py-2 pr-4`,children:`256`}),(0,_.jsx)(`td`,{className:`py-2`,children:`Hardcoded`})]}),(0,_.jsxs)(`tr`,{className:`border-b`,children:[(0,_.jsx)(`td`,{className:`py-2 pr-4`,children:`Max processes`}),(0,_.jsx)(`td`,{className:`py-2 pr-4`,children:`256`}),(0,_.jsx)(`td`,{className:`py-2`,children:`Hardcoded`})]}),(0,_.jsxs)(`tr`,{className:`border-b`,children:[(0,_.jsx)(`td`,{className:`py-2 pr-4`,children:`Log files per strategy`}),(0,_.jsx)(`td`,{className:`py-2 pr-4`,children:`10 files`}),(0,_.jsx)(`td`,{className:`py-2`,children:(0,_.jsx)(`code`,{children:`STRATEGY_LOG_MAX_FILES`})})]}),(0,_.jsxs)(`tr`,{className:`border-b`,children:[(0,_.jsx)(`td`,{className:`py-2 pr-4`,children:`Log size per strategy`}),(0,_.jsx)(`td`,{className:`py-2 pr-4`,children:`50 MB`}),(0,_.jsx)(`td`,{className:`py-2`,children:(0,_.jsx)(`code`,{children:`STRATEGY_LOG_MAX_SIZE_MB`})})]}),(0,_.jsxs)(`tr`,{className:`border-b`,children:[(0,_.jsx)(`td`,{className:`py-2 pr-4`,children:`Log retention`}),(0,_.jsx)(`td`,{className:`py-2 pr-4`,children:`7 days`}),(0,_.jsx)(`td`,{className:`py-2`,children:(0,_.jsx)(`code`,{children:`STRATEGY_LOG_RETENTION_DAYS`})})]})]})]})}),(0,_.jsx)(`p`,{className:`text-sm`,children:`A typical EMA/crossover strategy uses 80–120 MB of RAM and 5–10 file descriptors. The defaults are generous. For simple strategies, lower memory to 256–512 MB and run more strategies concurrently.`})]})]}),(0,_.jsxs)(h,{value:`restart`,children:[(0,_.jsx)(p,{children:`What happens if I restart OpenAlgo?`}),(0,_.jsxs)(m,{className:`text-muted-foreground space-y-3`,children:[(0,_.jsx)(`p`,{children:`OpenAlgo handles restarts gracefully:`}),(0,_.jsxs)(`ul`,{className:`list-disc list-inside space-y-1 ml-2`,children:[(0,_.jsx)(`li`,{children:`Strategy configurations are saved to disk and persist`}),(0,_.jsx)(`li`,{children:`Schedules are automatically re-created for all strategies`}),(0,_.jsx)(`li`,{children:`Stale "running" flags are cleaned up on startup`}),(0,_.jsx)(`li`,{children:`Strategies will auto-start at their next scheduled time`})]}),(0,_.jsxs)(s,{children:[(0,_.jsx)(o,{children:`Manual Stop Persists`}),(0,_.jsxs)(a,{children:[`If you manually stopped a strategy before the restart, it stays stopped. The`,` `,(0,_.jsx)(`code`,{children:`manually_stopped`}),` flag persists and the strategy won't auto-start until you click Start.`]})]})]})]}),(0,_.jsxs)(h,{value:`migration`,children:[(0,_.jsx)(p,{children:`I upgraded to exchange-aware /python. What do I need to do?`}),(0,_.jsxs)(m,{className:`text-muted-foreground space-y-3`,children:[(0,_.jsxs)(`p`,{children:[(0,_.jsx)(`strong`,{children:`No data migration required.`}),` On the first restart after upgrading,`,` `,(0,_.jsx)(`code`,{children:`load_configs()`}),` writes `,(0,_.jsx)(`code`,{children:`"exchange": "NSE"`}),` into any legacy entry missing the field.`]}),(0,_.jsxs)(`ul`,{className:`list-disc list-inside space-y-1 ml-2`,children:[(0,_.jsx)(`li`,{children:`No strategy is force-restarted or force-stopped by the upgrade`}),(0,_.jsx)(`li`,{children:`Legacy strategies keep running gated on NSE`}),(0,_.jsxs)(`li`,{children:[`Strategies that trade MCX/CRYPTO need a `,(0,_.jsx)(`strong`,{children:`one-time UI edit`}),`: Schedule → pick the correct exchange → Save`]}),(0,_.jsxs)(`li`,{children:[(0,_.jsx)(`code`,{children:`manually_stopped`}),` strategies stay manually stopped`]}),(0,_.jsxs)(`li`,{children:[`Rolling back to the previous code ignores the new `,(0,_.jsx)(`code`,{children:`exchange`}),` field — forward-compatible`]})]})]})]}),(0,_.jsxs)(h,{value:`best-practices`,children:[(0,_.jsx)(p,{children:`Best practices for writing strategies`}),(0,_.jsx)(m,{className:`text-muted-foreground space-y-2`,children:(0,_.jsxs)(`ul`,{className:`list-disc list-inside space-y-2 ml-2`,children:[(0,_.jsxs)(`li`,{children:[(0,_.jsx)(`strong`,{children:`Read config from env vars`}),` — Use `,(0,_.jsx)(`code`,{children:`os.getenv()`}),` `,`with sensible fallbacks so the same script works standalone and under the /python runner`]}),(0,_.jsxs)(`li`,{children:[(0,_.jsx)(`strong`,{children:`Read OPENALGO_STRATEGY_EXCHANGE`}),` — Wire the exchange from the host so your orders match the calendar`]}),(0,_.jsxs)(`li`,{children:[(0,_.jsx)(`strong`,{children:`Use print() for logging`}),` — All output goes to log files`]}),(0,_.jsxs)(`li`,{children:[(0,_.jsx)(`strong`,{children:`Handle exceptions`}),` — Wrap critical code in try/except`]}),(0,_.jsxs)(`li`,{children:[(0,_.jsx)(`strong`,{children:`Add sleep intervals`}),` — Don't spam API calls, use`,` `,(0,_.jsx)(`code`,{children:`time.sleep()`})]}),(0,_.jsxs)(`li`,{children:[(0,_.jsx)(`strong`,{children:`Handle KeyboardInterrupt`}),` — The host sends SIGTERM to stop strategies; clean up open positions in the handler`]}),(0,_.jsxs)(`li`,{children:[(0,_.jsx)(`strong`,{children:`Test with small quantities`}),` — Start with 1 share/lot`]}),(0,_.jsxs)(`li`,{children:[(0,_.jsx)(`strong`,{children:`Monitor logs initially`}),` — Watch the first few runs closely`]})]})})]}),(0,_.jsxs)(h,{value:`add-libraries`,children:[(0,_.jsx)(p,{children:`How do I add new libraries like TA-Lib, pandas-ta, etc.?`}),(0,_.jsxs)(m,{className:`text-muted-foreground space-y-3`,children:[(0,_.jsx)(`p`,{children:`If your strategy needs additional Python libraries, install them in OpenAlgo's environment.`}),(0,_.jsxs)(`div`,{className:`space-y-4`,children:[(0,_.jsxs)(`div`,{className:`bg-muted p-3 rounded-lg`,children:[(0,_.jsx)(`p`,{className:`font-medium mb-2`,children:`Using UV (Recommended)`}),(0,_.jsxs)(`ol`,{className:`list-decimal list-inside space-y-1 ml-2 text-sm`,children:[(0,_.jsxs)(`li`,{children:[`Open `,(0,_.jsx)(`code`,{children:`pyproject.toml`}),` and add your library to the`,` `,(0,_.jsx)(`code`,{children:`dependencies`}),` section`]}),(0,_.jsxs)(`li`,{children:[`Run `,(0,_.jsx)(`code`,{children:`uv sync`}),` in the openalgo directory`]}),(0,_.jsx)(`li`,{children:`Restart OpenAlgo`})]})]}),(0,_.jsxs)(`div`,{className:`bg-muted p-3 rounded-lg`,children:[(0,_.jsx)(`p`,{className:`font-medium mb-2`,children:`Using Regular Python venv`}),(0,_.jsxs)(`ol`,{className:`list-decimal list-inside space-y-1 ml-2 text-sm`,children:[(0,_.jsxs)(`li`,{children:[`Add your library to `,(0,_.jsx)(`code`,{children:`requirements.txt`})]}),(0,_.jsxs)(`li`,{children:[`Activate your venv and run `,(0,_.jsx)(`code`,{children:`pip install -r requirements.txt`})]}),(0,_.jsx)(`li`,{children:`Restart OpenAlgo`})]})]})]}),(0,_.jsxs)(s,{children:[(0,_.jsx)(o,{children:`TA-Lib Installation Note`}),(0,_.jsxs)(a,{children:[`TA-Lib requires the underlying C library to be installed first. On Mac:`,` `,(0,_.jsx)(`code`,{children:`brew install ta-lib`}),` | `,`On Ubuntu: `,(0,_.jsx)(`code`,{children:`sudo apt-get install libta-lib-dev`})]})]})]})]}),(0,_.jsxs)(h,{value:`troubleshooting`,children:[(0,_.jsx)(p,{children:`Troubleshooting common issues`}),(0,_.jsx)(m,{className:`text-muted-foreground space-y-3`,children:(0,_.jsxs)(`div`,{className:`space-y-2 text-sm`,children:[(0,_.jsxs)(`div`,{className:`bg-muted p-3 rounded-lg`,children:[(0,_.jsx)(`p`,{className:`font-medium`,children:`Strategy didn't run on a partial holiday (e.g. MCX evening on NSE holiday)`}),(0,_.jsxs)(`ul`,{className:`list-disc list-inside space-y-1 ml-2 mt-1`,children:[(0,_.jsxs)(`li`,{children:[`Open the strategy → Schedule → confirm `,(0,_.jsx)(`strong`,{children:`Exchange`}),` `,`is set to the right market (legacy strategies default to NSE)`]}),(0,_.jsx)(`li`,{children:`Confirm the date has a row in Admin → Holidays with the partial-open window for your exchange`}),(0,_.jsx)(`li`,{children:`Confirm your schedule overlaps the calendar window — they intersect`})]})]}),(0,_.jsxs)(`div`,{className:`bg-muted p-3 rounded-lg`,children:[(0,_.jsx)(`p`,{className:`font-medium`,children:`Orders rejected with "market closed" while strategy is running`}),(0,_.jsxs)(`p`,{className:`mt-1`,children:[`Your script's hardcoded `,(0,_.jsx)(`code`,{children:`exchange="NSE"`}),` doesn't match the host's`,` `,(0,_.jsx)(`code`,{children:`exchange="MCX"`}),`. Read `,(0,_.jsx)(`code`,{children:`OPENALGO_STRATEGY_EXCHANGE`}),` in your script (see Environment Variables above).`]})]}),(0,_.jsxs)(`div`,{className:`bg-muted p-3 rounded-lg`,children:[(0,_.jsx)(`p`,{className:`font-medium`,children:`Strategy ran on a Sunday/Saturday unexpectedly`}),(0,_.jsxs)(`p`,{className:`mt-1`,children:[`That's by design — the calendar's SPECIAL_SESSION row overrides the weekend reject. To opt out, remove Sat/Sun from `,(0,_.jsx)(`code`,{children:`schedule_days`}),`.`]})]}),(0,_.jsxs)(`div`,{className:`bg-muted p-3 rounded-lg`,children:[(0,_.jsx)(`p`,{className:`font-medium`,children:`Strategy crashed with MemoryError`}),(0,_.jsxs)(`p`,{className:`mt-1`,children:[`The per-strategy memory limit was exceeded. Check if your strategy loads large datasets. Increase `,(0,_.jsx)(`code`,{children:`STRATEGY_MEMORY_LIMIT_MB`}),` in `,(0,_.jsx)(`code`,{children:`.env`}),` `,`or optimize memory usage.`]})]}),(0,_.jsxs)(`div`,{className:`bg-muted p-3 rounded-lg`,children:[(0,_.jsx)(`p`,{className:`font-medium`,children:`OPENALGO_API_KEY not set`}),(0,_.jsxs)(`p`,{className:`mt-1`,children:[`Make sure you have generated an API key at`,` `,(0,_.jsx)(t,{to:`/apikey`,className:`text-primary hover:underline`,children:`API Key`}),`. The /python runner injects it automatically from the database.`]})]})]})})]})]})})]}),(0,_.jsxs)(f,{children:[(0,_.jsx)(l,{children:(0,_.jsx)(c,{children:`OpenAlgo SDK Quick Reference`})}),(0,_.jsxs)(u,{className:`space-y-4`,children:[(0,_.jsxs)(`div`,{className:`grid gap-3 text-sm`,children:[(0,_.jsxs)(`div`,{className:`bg-muted p-3 rounded-lg`,children:[(0,_.jsx)(`p`,{className:`font-medium mb-1`,children:`Initialize Client`}),(0,_.jsx)(`code`,{className:`text-xs`,children:`client = api(api_key=API_KEY, host=API_HOST, ws_url=WS_URL)`})]}),(0,_.jsxs)(`div`,{className:`bg-muted p-3 rounded-lg`,children:[(0,_.jsx)(`p`,{className:`font-medium mb-1`,children:`Place Order`}),(0,_.jsx)(`code`,{className:`text-xs`,children:`client.placeorder(strategy, symbol, exchange, action, quantity, price_type, product)`})]}),(0,_.jsxs)(`div`,{className:`bg-muted p-3 rounded-lg`,children:[(0,_.jsx)(`p`,{className:`font-medium mb-1`,children:`Historical Data`}),(0,_.jsx)(`code`,{className:`text-xs`,children:`client.history(symbol, exchange, interval, start_date, end_date)`})]}),(0,_.jsxs)(`div`,{className:`bg-muted p-3 rounded-lg`,children:[(0,_.jsx)(`p`,{className:`font-medium mb-1`,children:`WebSocket (LTP)`}),(0,_.jsx)(`code`,{className:`text-xs`,children:`client.connect(); client.subscribe_ltp(instruments, on_data_received=callback)`})]}),(0,_.jsxs)(`div`,{className:`bg-muted p-3 rounded-lg`,children:[(0,_.jsx)(`p`,{className:`font-medium mb-1`,children:`Get Quotes`}),(0,_.jsx)(`code`,{className:`text-xs`,children:`client.quotes(symbol="RELIANCE", exchange="NSE")`})]}),(0,_.jsxs)(`div`,{className:`bg-muted p-3 rounded-lg`,children:[(0,_.jsx)(`p`,{className:`font-medium mb-1`,children:`Order Status`}),(0,_.jsx)(`code`,{className:`text-xs`,children:`client.orderstatus(order_id=order_id, strategy=strategy_name)`})]}),(0,_.jsxs)(`div`,{className:`bg-muted p-3 rounded-lg`,children:[(0,_.jsx)(`p`,{className:`font-medium mb-1`,children:`Positions / Holdings`}),(0,_.jsx)(`code`,{className:`text-xs`,children:`client.positionbook()  |  client.holdings()`})]})]}),(0,_.jsxs)(`p`,{className:`text-sm text-muted-foreground`,children:[`For complete SDK documentation, visit:`,` `,(0,_.jsx)(`a`,{href:`https://docs.openalgo.in`,target:`_blank`,rel:`noopener noreferrer`,className:`text-primary hover:underline`,children:`docs.openalgo.in`})]})]})]}),(0,_.jsxs)(f,{children:[(0,_.jsx)(l,{children:(0,_.jsx)(c,{children:`Directory Structure`})}),(0,_.jsx)(u,{children:(0,_.jsx)(`pre`,{className:`bg-muted p-4 rounded-lg overflow-x-auto text-xs`,children:(0,_.jsx)(`code`,{children:`strategies/
  scripts/          # Uploaded strategy files
  examples/         # Example strategies
  configs.json      # Strategy configurations (atomic write)
  README.md         # Detailed documentation
  RESOURCE_LIMITS.md

log/
  strategies/       # Strategy log files (per-strategy rotation)

examples/
  python/           # Standalone example scripts
    emacrossover_strategy_python.py  # Full EMA crossover sample`})})})]})]})}export{x as default};