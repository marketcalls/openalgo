import{j as e}from"./vendor-react-F6HEwVg5.js";import{B as h,m as a,s as N}from"./index-CSD6hOiS.js";import{A as m,b as x,a as p}from"./alert-9wDlb2Bt.js";import{C as n,a as l,b as i,c as o,d}from"./card-BG1iiLGF.js";import{A as f,a as s,b as t,c as r}from"./accordion-DCnm9T0y.js";import{L as c}from"./vendor-router-C6z-ZQmQ.js";import"./vendor-charts-DsbwmA-V.js";import"./vendor-icons-eXDrYLg_.js";import"./vendor-radix-CO6SlRDC.js";const u=`"""
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
`,j=`# API Configuration — auto-injected by the /python runner
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
MY_PARAM = os.getenv("MY_PARAM", "default_value")`,g=y=>{navigator.clipboard.writeText(y),N.success("Copied to clipboard","clipboard")};function C(){return e.jsxs("div",{className:"container mx-auto py-6 space-y-6 max-w-4xl",children:[e.jsx(h,{variant:"ghost",asChild:!0,children:e.jsx(c,{to:"/python",children:"← Back to Python Strategies"})}),e.jsxs("div",{className:"space-y-2",children:[e.jsx("h1",{className:"text-2xl font-bold tracking-tight",children:"Python Strategy Guide"}),e.jsxs("p",{className:"text-muted-foreground",children:["Self-host automated trading strategies inside OpenAlgo. Each strategy runs as an isolated subprocess with its own process, memory, and log file — managed through the ",e.jsx(c,{to:"/python",className:"text-primary hover:underline",children:"/python"})," dashboard."]})]}),e.jsxs(n,{children:[e.jsxs(l,{children:[e.jsx(i,{children:"Quick Start"}),e.jsx(o,{children:"Get your first strategy running in 5 minutes"})]}),e.jsx(d,{className:"space-y-4",children:e.jsxs("div",{className:"grid gap-4",children:[e.jsxs("div",{className:"flex gap-4",children:[e.jsx(a,{className:"h-6 w-6 rounded-full flex items-center justify-center shrink-0",children:"1"}),e.jsxs("div",{children:[e.jsx("p",{className:"font-medium",children:"Install OpenAlgo SDK"}),e.jsxs("div",{className:"mt-1 flex items-center gap-2",children:[e.jsx("code",{className:"bg-muted px-2 py-1 rounded text-sm",children:"pip install openalgo"}),e.jsx(h,{variant:"ghost",size:"sm",onClick:()=>g("pip install openalgo"),children:"Copy"})]})]})]}),e.jsxs("div",{className:"flex gap-4",children:[e.jsx(a,{className:"h-6 w-6 rounded-full flex items-center justify-center shrink-0",children:"2"}),e.jsxs("div",{children:[e.jsx("p",{className:"font-medium",children:"Get your API Key"}),e.jsxs("p",{className:"text-sm text-muted-foreground",children:["Go to ",e.jsx(c,{to:"/apikey",className:"text-primary hover:underline",children:"API Key"})," page and copy your OpenAlgo API key"]})]})]}),e.jsxs("div",{className:"flex gap-4",children:[e.jsx(a,{className:"h-6 w-6 rounded-full flex items-center justify-center shrink-0",children:"3"}),e.jsxs("div",{children:[e.jsx("p",{className:"font-medium",children:"Write your strategy"}),e.jsx("p",{className:"text-sm text-muted-foreground",children:"Create a Python file (.py) with your trading logic. Read configuration from environment variables so it works both standalone and under the /python runner without edits. See the sample strategy below."})]})]}),e.jsxs("div",{className:"flex gap-4",children:[e.jsx(a,{className:"h-6 w-6 rounded-full flex items-center justify-center shrink-0",children:"4"}),e.jsxs("div",{children:[e.jsx("p",{className:"font-medium",children:"Upload and configure"}),e.jsxs("p",{className:"text-sm text-muted-foreground",children:["On the ",e.jsx(c,{to:"/python",className:"text-primary hover:underline",children:"Python Strategies"})," page, click ",e.jsx("strong",{children:"Add Strategy"}),". Pick a name, select the exchange (NSE / MCX / CRYPTO / etc.), and add any custom parameters as environment variables."]})]})]}),e.jsxs("div",{className:"flex gap-4",children:[e.jsx(a,{className:"h-6 w-6 rounded-full flex items-center justify-center shrink-0",children:"5"}),e.jsxs("div",{children:[e.jsx("p",{className:"font-medium",children:"Start or schedule"}),e.jsxs("p",{className:"text-sm text-muted-foreground",children:["Click ",e.jsx("strong",{children:"Start"})," to run immediately, or configure a schedule (e.g. 09:15–15:30 Mon–Fri for NSE). The host auto-starts and auto-stops your strategy at the scheduled times, respecting the exchange's holiday calendar."]})]})]})]})})]}),e.jsxs(n,{children:[e.jsxs(l,{children:[e.jsx(i,{children:"How It Works"}),e.jsx(o,{children:"Process isolation, environment injection, and exchange-aware scheduling"})]}),e.jsx(d,{className:"space-y-4 text-sm",children:e.jsxs("div",{className:"space-y-3",children:[e.jsxs("div",{className:"bg-muted p-3 rounded-lg",children:[e.jsx("p",{className:"font-medium mb-1",children:"Process Isolation"}),e.jsxs("p",{className:"text-muted-foreground",children:["Each strategy runs as a separate ",e.jsx("code",{children:"subprocess.Popen"})," process with its own PID, memory, and file descriptors. A crash in one strategy cannot affect another or the host."]})]}),e.jsxs("div",{className:"bg-muted p-3 rounded-lg",children:[e.jsx("p",{className:"font-medium mb-1",children:"Environment Injection"}),e.jsxs("p",{className:"text-muted-foreground",children:["The host injects ",e.jsx("code",{children:"OPENALGO_API_KEY"}),", ",e.jsx("code",{children:"STRATEGY_ID"}),","," ",e.jsx("code",{children:"STRATEGY_NAME"}),", and ",e.jsx("code",{children:"OPENALGO_STRATEGY_EXCHANGE"})," into each strategy's environment. Your ",e.jsx("code",{children:".env"})," variables (like"," ",e.jsx("code",{children:"HOST_SERVER"}),", ",e.jsx("code",{children:"WEBSOCKET_URL"}),") are also inherited. Custom parameters from the upload form become additional env vars."]})]}),e.jsxs("div",{className:"bg-muted p-3 rounded-lg",children:[e.jsx("p",{className:"font-medium mb-1",children:"Exchange-Aware Calendar"}),e.jsx("p",{className:"text-muted-foreground",children:"Each strategy is tagged with an exchange. The host uses that exchange's holiday calendar to gate scheduled start/stop — an MCX strategy keeps running on an NSE holiday during the MCX evening session, a CRYPTO strategy ignores all holidays."})]}),e.jsxs("div",{className:"bg-muted p-3 rounded-lg",children:[e.jsx("p",{className:"font-medium mb-1",children:"Logging"}),e.jsxs("p",{className:"text-muted-foreground",children:["All ",e.jsx("code",{children:"print()"})," output is captured in timestamped log files under"," ",e.jsx("code",{children:"log/strategies/"}),". View them from the dashboard or via the Logs button on each strategy card."]})]})]})})]}),e.jsxs(n,{children:[e.jsxs(l,{children:[e.jsx(i,{children:"Environment Variables"}),e.jsx(o,{children:"Variables available inside your strategy script"})]}),e.jsxs(d,{className:"space-y-5",children:[e.jsxs("div",{children:[e.jsx("p",{className:"font-medium mb-2",children:"Injected by the Platform"}),e.jsx("p",{className:"text-sm text-muted-foreground mb-3",children:"These are set directly on each strategy subprocess by the /python runner:"}),e.jsx("div",{className:"overflow-x-auto",children:e.jsxs("table",{className:"w-full text-sm border-collapse",children:[e.jsx("thead",{children:e.jsxs("tr",{className:"border-b",children:[e.jsx("th",{className:"text-left py-2 pr-4 font-medium",children:"Variable"}),e.jsx("th",{className:"text-left py-2 font-medium",children:"Description"})]})}),e.jsxs("tbody",{className:"text-muted-foreground",children:[e.jsxs("tr",{className:"border-b",children:[e.jsx("td",{className:"py-2 pr-4",children:e.jsx("code",{children:"OPENALGO_API_KEY"})}),e.jsx("td",{className:"py-2",children:"Decrypted API key for this user"})]}),e.jsxs("tr",{className:"border-b",children:[e.jsx("td",{className:"py-2 pr-4",children:e.jsx("code",{children:"STRATEGY_ID"})}),e.jsx("td",{className:"py-2",children:"Unique identifier for this strategy"})]}),e.jsxs("tr",{className:"border-b",children:[e.jsx("td",{className:"py-2 pr-4",children:e.jsx("code",{children:"STRATEGY_NAME"})}),e.jsx("td",{className:"py-2",children:"Name of the strategy (as entered at upload)"})]}),e.jsxs("tr",{className:"border-b",children:[e.jsx("td",{className:"py-2 pr-4",children:e.jsx("code",{children:"OPENALGO_STRATEGY_EXCHANGE"})}),e.jsx("td",{className:"py-2",children:"Exchange picked at upload/edit (NSE / BSE / NFO / BFO / MCX / BCD / CDS / CRYPTO). Read this so your trading calls match the calendar the host gates against"})]}),e.jsxs("tr",{className:"border-b",children:[e.jsx("td",{className:"py-2 pr-4",children:e.jsx("code",{children:"OPENALGO_HOST"})}),e.jsxs("td",{className:"py-2",children:["Convenience fallback (",e.jsx("code",{children:"http://127.0.0.1:5000"}),"). Prefer ",e.jsx("code",{children:"HOST_SERVER"})," instead"]})]})]})]})})]}),e.jsxs("div",{children:[e.jsx("p",{className:"font-medium mb-2",children:"Inherited from .env"}),e.jsxs("p",{className:"text-sm text-muted-foreground mb-3",children:["Strategies inherit every variable from OpenAlgo's ",e.jsx("code",{children:".env"})," via"," ",e.jsx("code",{children:"os.environ.copy()"}),". The key ones for connecting back to OpenAlgo:"]}),e.jsx("div",{className:"overflow-x-auto",children:e.jsxs("table",{className:"w-full text-sm border-collapse",children:[e.jsx("thead",{children:e.jsxs("tr",{className:"border-b",children:[e.jsx("th",{className:"text-left py-2 pr-4 font-medium",children:"Variable"}),e.jsx("th",{className:"text-left py-2 font-medium",children:"Description"})]})}),e.jsxs("tbody",{className:"text-muted-foreground",children:[e.jsxs("tr",{className:"border-b",children:[e.jsx("td",{className:"py-2 pr-4",children:e.jsx("code",{children:"HOST_SERVER"})}),e.jsxs("td",{className:"py-2",children:["REST host, e.g. ",e.jsx("code",{children:"http://127.0.0.1:5000"})," — canonical name in ",e.jsx("code",{children:".env"}),", prefer this in scripts"]})]}),e.jsxs("tr",{className:"border-b",children:[e.jsx("td",{className:"py-2 pr-4",children:e.jsx("code",{children:"WEBSOCKET_URL"})}),e.jsxs("td",{className:"py-2",children:["Full WebSocket URL, e.g. ",e.jsx("code",{children:"ws://127.0.0.1:8765"})]})]}),e.jsxs("tr",{className:"border-b",children:[e.jsx("td",{className:"py-2 pr-4",children:e.jsx("code",{children:"WEBSOCKET_HOST"})}),e.jsxs("td",{className:"py-2",children:["WebSocket host component, e.g. ",e.jsx("code",{children:"127.0.0.1"})]})]}),e.jsxs("tr",{className:"border-b",children:[e.jsx("td",{className:"py-2 pr-4",children:e.jsx("code",{children:"WEBSOCKET_PORT"})}),e.jsxs("td",{className:"py-2",children:["WebSocket port, e.g. ",e.jsx("code",{children:"8765"})]})]}),e.jsxs("tr",{className:"border-b",children:[e.jsxs("td",{className:"py-2 pr-4",children:[e.jsx("code",{children:"FLASK_HOST_IP"})," / ",e.jsx("code",{children:"FLASK_PORT"})]}),e.jsx("td",{className:"py-2",children:"Flask binding address (available if you need raw components)"})]})]})]})})]}),e.jsxs("div",{children:[e.jsx("p",{className:"font-medium mb-2",children:"Recommended Pattern in Scripts"}),e.jsxs("div",{className:"relative",children:[e.jsx(h,{variant:"outline",size:"sm",className:"absolute top-2 right-2 z-10",onClick:()=>g(j),children:"Copy"}),e.jsx("pre",{className:"bg-muted p-4 rounded-lg overflow-x-auto text-xs",children:e.jsx("code",{children:j})})]})]}),e.jsxs(m,{children:[e.jsx(x,{children:"Reading OPENALGO_STRATEGY_EXCHANGE is strongly recommended"}),e.jsxs(p,{children:["If your script hardcodes ",e.jsx("code",{children:'exchange = "NSE"'}),", the host will still gate it correctly per its config (e.g. the host runs your script during the MCX evening session because ",e.jsx("code",{children:"exchange=MCX"}),"), but your"," ",e.jsx("code",{children:'client.placeorder(exchange="NSE", ...)'})," calls will still send NSE orders — and the broker will reject them. Wiring the env var keeps host calendar and script orders aligned."]})]})]})]}),e.jsxs(n,{children:[e.jsxs(l,{children:[e.jsx(i,{children:"Exchange-Aware Scheduling"}),e.jsx(o,{children:"Each strategy's exchange drives which holiday calendar the host uses"})]}),e.jsxs(d,{className:"space-y-5",children:[e.jsxs("div",{className:"space-y-3 text-sm",children:[e.jsx("p",{className:"text-muted-foreground",children:"When you upload or edit a strategy, you pick an exchange. The host uses that exchange's calendar to decide whether to start/stop the strategy on any given day. This means:"}),e.jsxs("ul",{className:"list-disc list-inside space-y-1 ml-2 text-muted-foreground",children:[e.jsxs("li",{children:["An ",e.jsx("strong",{children:"MCX"})," strategy keeps running on NSE/BSE holidays if MCX has a session"]}),e.jsxs("li",{children:["A ",e.jsx("strong",{children:"CRYPTO"})," strategy ignores all holidays and weekends (24/7)"]}),e.jsxs("li",{children:[e.jsx("strong",{children:"SPECIAL_SESSION"})," rows (Muhurat, DR-drill) override weekend rejects per-exchange"]})]})]}),e.jsxs("div",{children:[e.jsx("p",{className:"font-medium mb-2",children:"Supported Exchanges"}),e.jsxs("div",{className:"grid grid-cols-1 sm:grid-cols-2 gap-2 text-sm",children:[e.jsxs("div",{className:"bg-muted p-2 rounded",children:[e.jsx("strong",{children:"NSE"})," — Equity (09:15–15:30)"]}),e.jsxs("div",{className:"bg-muted p-2 rounded",children:[e.jsx("strong",{children:"BSE"})," — Equity (09:15–15:30)"]}),e.jsxs("div",{className:"bg-muted p-2 rounded",children:[e.jsx("strong",{children:"NFO"})," — NSE F&O (09:15–15:30)"]}),e.jsxs("div",{className:"bg-muted p-2 rounded",children:[e.jsx("strong",{children:"BFO"})," — BSE F&O (09:15–15:30)"]}),e.jsxs("div",{className:"bg-muted p-2 rounded",children:[e.jsx("strong",{children:"CDS"})," — NSE Currency (09:00–17:00)"]}),e.jsxs("div",{className:"bg-muted p-2 rounded",children:[e.jsx("strong",{children:"BCD"})," — BSE Currency (09:00–17:00)"]}),e.jsxs("div",{className:"bg-muted p-2 rounded",children:[e.jsx("strong",{children:"MCX"})," — Commodity (09:00–23:55)"]}),e.jsxs("div",{className:"bg-muted p-2 rounded",children:[e.jsx("strong",{children:"CRYPTO"})," — 24/7 (no holidays)"]})]}),e.jsx("p",{className:"text-xs text-muted-foreground mt-2",children:"Timings shown are defaults. Per-date overrides (partial holidays, special sessions) come from the market calendar DB."})]}),e.jsxs("div",{children:[e.jsx("p",{className:"font-medium mb-2",children:"Schedule Intersection Rule"}),e.jsxs("p",{className:"text-sm text-muted-foreground mb-3",children:["The effective trading window is the ",e.jsx("strong",{children:"intersection"})," of your"," ",e.jsx("code",{children:"start..stop"})," time and the exchange's session for that specific date."]}),e.jsxs("div",{className:"bg-muted p-3 rounded-lg text-sm space-y-1",children:[e.jsxs("p",{children:[e.jsx("strong",{children:"Example:"})," MCX strategy scheduled 09:15–23:55"]}),e.jsxs("p",{className:"text-muted-foreground",children:["On 14-Apr-2026 (Ambedkar Jayanti), MCX has a partial holiday with an evening session 17:00–23:55. The effective window becomes"," ",e.jsx("strong",{children:"17:00–23:55"})," (the intersection). You don't need to change the schedule for partial holidays."]})]})]}),e.jsxs("div",{children:[e.jsx("p",{className:"font-medium mb-3",children:"Worked Examples"}),e.jsx("div",{className:"overflow-x-auto",children:e.jsxs("table",{className:"w-full text-sm border-collapse",children:[e.jsx("thead",{children:e.jsxs("tr",{className:"border-b",children:[e.jsx("th",{className:"text-left py-2 pr-3 font-medium",children:"Scenario"}),e.jsx("th",{className:"text-left py-2 pr-3 font-medium",children:"Exchange"}),e.jsx("th",{className:"text-left py-2 font-medium",children:"Strategy Behavior"})]})}),e.jsxs("tbody",{className:"text-muted-foreground",children:[e.jsxs("tr",{className:"border-b",children:[e.jsxs("td",{className:"py-2 pr-3",rowSpan:3,children:[e.jsx("strong",{children:"14-Apr-2026"}),e.jsx("br",{}),e.jsx("span",{className:"text-xs",children:"Ambedkar Jayanti"})]}),e.jsx("td",{className:"py-2 pr-3",children:"NSE / BSE / NFO"}),e.jsx("td",{className:"py-2",children:"Closed all day. Strategies paused at 00:01 IST"})]}),e.jsxs("tr",{className:"border-b",children:[e.jsx("td",{className:"py-2 pr-3",children:"MCX"}),e.jsx("td",{className:"py-2",children:"Open 17:00–23:55. MCX strategies auto-start at 17:00"})]}),e.jsxs("tr",{className:"border-b",children:[e.jsx("td",{className:"py-2 pr-3",children:"CRYPTO"}),e.jsx("td",{className:"py-2",children:"Unaffected (24/7)"})]}),e.jsxs("tr",{className:"border-b",children:[e.jsxs("td",{className:"py-2 pr-3",rowSpan:3,children:[e.jsx("strong",{children:"8-Nov-2026"}),e.jsx("br",{}),e.jsx("span",{className:"text-xs",children:"Sunday Diwali Muhurat"})]}),e.jsx("td",{className:"py-2 pr-3",children:"NSE / BSE / NFO"}),e.jsx("td",{className:"py-2",children:"SPECIAL_SESSION 18:00–19:15. Runs only inside that window, despite being Sunday"})]}),e.jsxs("tr",{className:"border-b",children:[e.jsx("td",{className:"py-2 pr-3",children:"MCX"}),e.jsx("td",{className:"py-2",children:"SPECIAL_SESSION 18:00–00:15 next day"})]}),e.jsxs("tr",{className:"border-b",children:[e.jsx("td",{className:"py-2 pr-3",children:"CRYPTO"}),e.jsx("td",{className:"py-2",children:"Unaffected (24/7)"})]})]})]})})]}),e.jsxs("div",{children:[e.jsx("p",{className:"font-medium mb-2",children:"How the Host Gates Strategies"}),e.jsxs("div",{className:"space-y-2 text-sm text-muted-foreground",children:[e.jsxs("div",{className:"bg-muted p-3 rounded-lg",children:[e.jsx("strong",{children:"1. Cron job"})," — Fires ",e.jsx("code",{children:"start_<sid>"})," at your ",e.jsx("code",{children:"start_time"})," on each day in ",e.jsx("code",{children:"schedule_days"}),"."]}),e.jsxs("div",{className:"bg-muted p-3 rounded-lg",children:[e.jsx("strong",{children:"2. Daily check (00:01 IST)"})," — For each scheduled strategy, looks up ",e.jsx("code",{children:'get_market_status(config["exchange"])'}),". If the exchange has no session today, the strategy is stopped and marked"," ",e.jsx("code",{children:"paused_reason=holiday|weekend"}),"."]}),e.jsxs("div",{className:"bg-muted p-3 rounded-lg",children:[e.jsx("strong",{children:"3. Per-minute enforcer"})," — Same per-strategy check. When the exchange reopens (or a special session starts), previously-paused strategies are auto-resumed (unless ",e.jsx("code",{children:"manually_stopped"}),")."]})]})]}),e.jsxs("div",{className:"bg-primary/10 border border-primary/20 p-3 rounded-lg text-sm",children:[e.jsx("p",{className:"font-medium text-primary",children:"Smart Defaults When Uploading"}),e.jsx("p",{className:"text-muted-foreground mt-1",children:"Picking an exchange pre-fills sensible defaults: CRYPTO auto-selects all 7 days and 00:00–23:59, MCX defaults to 09:00–23:55 weekdays, and equity exchanges default to 09:15–15:30 Mon–Fri."})]})]})]}),e.jsxs(n,{children:[e.jsxs(l,{children:[e.jsx(i,{children:"Sample Strategy: EMA Crossover"}),e.jsxs(o,{children:["WebSocket-driven EMA crossover with real-time SL/target monitoring. All config is overridable via env vars — works standalone and under the /python runner without edits. Full version at ",e.jsx("code",{children:"examples/python/emacrossover_strategy_python.py"})]})]}),e.jsx(d,{children:e.jsxs("div",{className:"relative",children:[e.jsx(h,{variant:"outline",size:"sm",className:"absolute top-2 right-2 z-10",onClick:()=>g(u),children:"Copy"}),e.jsx("pre",{className:"bg-muted p-4 rounded-lg overflow-x-auto text-xs max-h-[32rem] overflow-y-auto",children:e.jsx("code",{children:u})})]})})]}),e.jsxs(n,{children:[e.jsx(l,{children:e.jsx(i,{children:"Frequently Asked Questions"})}),e.jsx(d,{children:e.jsxs(f,{type:"single",collapsible:!0,className:"w-full",children:[e.jsxs(s,{value:"logs",children:[e.jsx(t,{children:"How do I see my strategy logs?"}),e.jsxs(r,{className:"text-muted-foreground space-y-2",children:[e.jsxs("p",{children:["All ",e.jsx("code",{children:"print()"})," statements in your strategy are captured in log files."]}),e.jsx("p",{children:"To view logs:"}),e.jsxs("ol",{className:"list-decimal list-inside space-y-1 ml-2",children:[e.jsxs("li",{children:["Click the ",e.jsx("strong",{children:"Logs"})," button on your strategy card"]}),e.jsx("li",{children:"Select a log file from the list (newest first)"}),e.jsxs("li",{children:["Enable ",e.jsx("strong",{children:"Auto-refresh"})," to see live updates while running"]})]}),e.jsxs("p",{className:"text-sm",children:["Log files are stored in: ",e.jsx("code",{children:"log/strategies/"}),". Per-strategy limits: max ","{","STRATEGY_LOG_MAX_FILES","}"," files, ","{","STRATEGY_LOG_MAX_SIZE_MB","}"," MB total, retained for ","{","STRATEGY_LOG_RETENTION_DAYS","}"," days. Override these in ",e.jsx("code",{children:".env"}),"."]})]})]}),e.jsxs(s,{value:"scheduling",children:[e.jsx(t,{children:"How does scheduling work?"}),e.jsxs(r,{className:"text-muted-foreground space-y-3",children:[e.jsx("p",{children:"Every strategy has a schedule that controls when the host automatically starts and stops it."}),e.jsxs("div",{className:"space-y-2",children:[e.jsx("p",{className:"font-medium",children:"Schedule Configuration:"}),e.jsxs("ul",{className:"list-disc list-inside space-y-1 ml-2",children:[e.jsxs("li",{children:[e.jsx("strong",{children:"Exchange:"})," Drives the holiday calendar (NSE / MCX / CRYPTO / etc.)"]}),e.jsxs("li",{children:[e.jsx("strong",{children:"Start Time:"})," When the strategy auto-starts (IST, 24-hour format)"]}),e.jsxs("li",{children:[e.jsx("strong",{children:"Stop Time:"})," When to auto-stop (IST, 24-hour format)"]}),e.jsxs("li",{children:[e.jsx("strong",{children:"Days:"})," Which days to run (can include weekends for special sessions)"]})]})]}),e.jsxs("div",{className:"bg-muted p-3 rounded-lg space-y-2 text-sm",children:[e.jsx("p",{className:"font-medium",children:"Example Schedules:"}),e.jsxs("ul",{className:"list-disc list-inside space-y-1 ml-2",children:[e.jsx("li",{children:"NSE EMA strategy: 09:15–15:30, Mon–Fri"}),e.jsx("li",{children:"MCX evening strategy: 17:00–23:55, Mon–Fri"}),e.jsx("li",{children:"CRYPTO arb: 00:00–23:59, all 7 days"})]})]}),e.jsxs(m,{children:[e.jsx(x,{children:"Holiday & Weekend Protection"}),e.jsx(p,{children:"The host checks each strategy's exchange calendar before starting it. An NSE strategy won't start on NSE holidays, even if scheduled. Weekend strategies are blocked unless the calendar has a SPECIAL_SESSION row for that exchange on that date, or the exchange is CRYPTO (always open)."})]})]})]}),e.jsxs(s,{value:"status-indicators",children:[e.jsx(t,{children:"What do the status indicators mean?"}),e.jsxs(r,{className:"text-muted-foreground space-y-3",children:[e.jsx("p",{children:"Each strategy displays a status badge showing its current state:"}),e.jsxs("div",{className:"space-y-2",children:[e.jsxs("div",{className:"flex items-center gap-3 p-2 bg-muted rounded",children:[e.jsx(a,{className:"bg-green-500 text-white",children:"Running"}),e.jsx("span",{className:"text-sm",children:"Strategy is actively running and executing trades"})]}),e.jsxs("div",{className:"flex items-center gap-3 p-2 bg-muted rounded",children:[e.jsx(a,{className:"bg-blue-500 text-white",children:"Scheduled"}),e.jsxs("div",{className:"text-sm",children:[e.jsx("p",{children:"Strategy is armed and will auto-start at the scheduled time"}),e.jsx("p",{className:"text-xs text-muted-foreground mt-1",children:'Shows context: "Starts today at 9:15 IST" or "Next: Mon, Tue at 9:15 IST"'})]})]}),e.jsxs("div",{className:"flex items-center gap-3 p-2 bg-muted rounded",children:[e.jsx(a,{className:"bg-orange-500 text-white",children:"Manual Stop"}),e.jsx("span",{className:"text-sm",children:"Strategy was manually stopped — won't auto-start until you click Start"})]}),e.jsxs("div",{className:"flex items-center gap-3 p-2 bg-muted rounded",children:[e.jsx(a,{className:"bg-yellow-500 text-white",children:"Paused"}),e.jsx("span",{className:"text-sm",children:"Strategy is paused due to market holiday for its exchange"})]}),e.jsxs("div",{className:"flex items-center gap-3 p-2 bg-muted rounded",children:[e.jsx(a,{className:"bg-red-500 text-white",children:"Error"}),e.jsx("span",{className:"text-sm",children:"Strategy encountered an error and crashed"})]})]})]})]}),e.jsxs(s,{value:"start-stop",children:[e.jsx(t,{children:"How does Start and Stop work?"}),e.jsxs(r,{className:"text-muted-foreground space-y-3",children:[e.jsxs("div",{className:"bg-green-500/10 border border-green-500/20 p-3 rounded-lg",children:[e.jsx("p",{className:"font-medium text-green-600",children:"Start Button"}),e.jsxs("ul",{className:"list-disc list-inside space-y-1 ml-2 mt-2 text-sm",children:[e.jsxs("li",{children:[e.jsx("strong",{children:"Within schedule:"})," Strategy starts running immediately"]}),e.jsxs("li",{children:[e.jsx("strong",{children:"Outside schedule:"}),' Strategy is "armed" — status changes to "Scheduled"']}),e.jsxs("li",{children:["Button changes to ",e.jsx("strong",{children:"Cancel"})," after arming"]})]})]}),e.jsxs("div",{className:"bg-red-500/10 border border-red-500/20 p-3 rounded-lg",children:[e.jsx("p",{className:"font-medium text-red-600",children:"Stop Button (when running)"}),e.jsxs("ul",{className:"list-disc list-inside space-y-1 ml-2 mt-2 text-sm",children:[e.jsx("li",{children:"Stops the running strategy process (SIGTERM)"}),e.jsx("li",{children:`Sets "manually stopped" flag — won't auto-start`}),e.jsx("li",{children:'Status shows "Manual Stop"'})]})]}),e.jsxs("div",{className:"bg-orange-500/10 border border-orange-500/20 p-3 rounded-lg",children:[e.jsx("p",{className:"font-medium text-orange-600",children:"Cancel Button (when scheduled)"}),e.jsxs("ul",{className:"list-disc list-inside space-y-1 ml-2 mt-2 text-sm",children:[e.jsx("li",{children:"Cancels the scheduled auto-start"}),e.jsx("li",{children:'Sets "manually stopped" flag'}),e.jsx("li",{children:"Click Start again to re-arm"})]})]}),e.jsxs("div",{className:"bg-muted p-3 rounded-lg text-sm",children:[e.jsx("p",{className:"font-medium",children:"Use Cases"}),e.jsxs("ul",{className:"list-disc list-inside space-y-1 ml-2 mt-2",children:[e.jsxs("li",{children:[e.jsx("strong",{children:"Evening setup:"})," Click Start at night, strategy runs at 9:15 AM next day"]}),e.jsxs("li",{children:[e.jsx("strong",{children:"Vacation mode:"})," Click Stop, strategy stays off until you return"]}),e.jsxs("li",{children:[e.jsx("strong",{children:"Testing:"})," Edit schedule to test now, then revert schedule after"]})]})]})]})]}),e.jsxs(s,{value:"special-sessions",children:[e.jsx(t,{children:"What about special trading sessions (Muhurat, Budget Day)?"}),e.jsxs(r,{className:"text-muted-foreground space-y-3",children:[e.jsx("p",{children:"Exchanges occasionally conduct special sessions on holidays or weekends. The exchange-aware calendar handles these automatically:"}),e.jsxs("div",{className:"space-y-2 text-sm",children:[e.jsxs("div",{className:"bg-muted p-3 rounded-lg",children:[e.jsx("p",{className:"font-medium",children:"Automatic Handling (Recommended)"}),e.jsxs("ol",{className:"list-decimal list-inside space-y-1 ml-2 mt-2",children:[e.jsxs("li",{children:["Go to ",e.jsx(c,{to:"/admin/holidays",className:"text-primary hover:underline",children:"Admin → Holidays"})]}),e.jsxs("li",{children:["Add a ",e.jsx("strong",{children:"SPECIAL_SESSION"})," row for the date and exchange with the session timing (e.g. Muhurat: NSE 18:00–19:15)"]}),e.jsxs("li",{children:["Ensure the relevant day (Sat/Sun) is in your strategy's ",e.jsx("code",{children:"schedule_days"})]}),e.jsx("li",{children:"The host auto-starts the strategy within the special session window — no schedule edits needed, no need to revert afterward"})]})]}),e.jsxs("div",{className:"bg-muted p-3 rounded-lg",children:[e.jsx("p",{className:"font-medium",children:"Manual Override"}),e.jsxs("p",{className:"mt-1",children:["Log in to OpenAlgo before the session, wait for master contracts to download, and click ",e.jsx("strong",{children:"Start"})," manually. Click ",e.jsx("strong",{children:"Stop"})," when the session ends."]})]})]})]})]}),e.jsxs(s,{value:"master-contract",children:[e.jsx(t,{children:"Why does my strategy need master contracts?"}),e.jsxs(r,{className:"text-muted-foreground space-y-2",children:[e.jsx("p",{children:"Master contracts contain the symbol mappings required by your broker. Strategies cannot start until master contracts are downloaded."}),e.jsx("p",{children:"Master contracts are automatically downloaded when you:"}),e.jsxs("ol",{className:"list-decimal list-inside space-y-1 ml-2",children:[e.jsx("li",{children:"Log in to OpenAlgo"}),e.jsx("li",{children:"Wait for the download to complete (shown in header)"})]}),e.jsx("p",{className:"text-sm",children:'If you see "Waiting for master contracts", just wait a moment after login.'})]})]}),e.jsxs(s,{value:"resource-limits",children:[e.jsx(t,{children:"Are there resource limits?"}),e.jsxs(r,{className:"text-muted-foreground space-y-3",children:[e.jsx("p",{children:"On Linux/macOS, per-strategy resource limits prevent buggy scripts from crashing OpenAlgo. On Windows, these are not enforced at the OS level."}),e.jsx("div",{className:"overflow-x-auto",children:e.jsxs("table",{className:"w-full text-sm border-collapse",children:[e.jsx("thead",{children:e.jsxs("tr",{className:"border-b",children:[e.jsx("th",{className:"text-left py-2 pr-4 font-medium",children:"Resource"}),e.jsx("th",{className:"text-left py-2 pr-4 font-medium",children:"Default Limit"}),e.jsx("th",{className:"text-left py-2 font-medium",children:"Override (.env)"})]})}),e.jsxs("tbody",{children:[e.jsxs("tr",{className:"border-b",children:[e.jsx("td",{className:"py-2 pr-4",children:"Memory (virtual)"}),e.jsx("td",{className:"py-2 pr-4",children:"1024 MB"}),e.jsx("td",{className:"py-2",children:e.jsx("code",{children:"STRATEGY_MEMORY_LIMIT_MB"})})]}),e.jsxs("tr",{className:"border-b",children:[e.jsx("td",{className:"py-2 pr-4",children:"CPU time (cumulative)"}),e.jsx("td",{className:"py-2 pr-4",children:"3600 seconds"}),e.jsx("td",{className:"py-2",children:"Hardcoded"})]}),e.jsxs("tr",{className:"border-b",children:[e.jsx("td",{className:"py-2 pr-4",children:"Open file descriptors"}),e.jsx("td",{className:"py-2 pr-4",children:"256"}),e.jsx("td",{className:"py-2",children:"Hardcoded"})]}),e.jsxs("tr",{className:"border-b",children:[e.jsx("td",{className:"py-2 pr-4",children:"Max processes"}),e.jsx("td",{className:"py-2 pr-4",children:"256"}),e.jsx("td",{className:"py-2",children:"Hardcoded"})]}),e.jsxs("tr",{className:"border-b",children:[e.jsx("td",{className:"py-2 pr-4",children:"Log files per strategy"}),e.jsx("td",{className:"py-2 pr-4",children:"10 files"}),e.jsx("td",{className:"py-2",children:e.jsx("code",{children:"STRATEGY_LOG_MAX_FILES"})})]}),e.jsxs("tr",{className:"border-b",children:[e.jsx("td",{className:"py-2 pr-4",children:"Log size per strategy"}),e.jsx("td",{className:"py-2 pr-4",children:"50 MB"}),e.jsx("td",{className:"py-2",children:e.jsx("code",{children:"STRATEGY_LOG_MAX_SIZE_MB"})})]}),e.jsxs("tr",{className:"border-b",children:[e.jsx("td",{className:"py-2 pr-4",children:"Log retention"}),e.jsx("td",{className:"py-2 pr-4",children:"7 days"}),e.jsx("td",{className:"py-2",children:e.jsx("code",{children:"STRATEGY_LOG_RETENTION_DAYS"})})]})]})]})}),e.jsx("p",{className:"text-sm",children:"A typical EMA/crossover strategy uses 80–120 MB of RAM and 5–10 file descriptors. The defaults are generous. For simple strategies, lower memory to 256–512 MB and run more strategies concurrently."})]})]}),e.jsxs(s,{value:"restart",children:[e.jsx(t,{children:"What happens if I restart OpenAlgo?"}),e.jsxs(r,{className:"text-muted-foreground space-y-3",children:[e.jsx("p",{children:"OpenAlgo handles restarts gracefully:"}),e.jsxs("ul",{className:"list-disc list-inside space-y-1 ml-2",children:[e.jsx("li",{children:"Strategy configurations are saved to disk and persist"}),e.jsx("li",{children:"Schedules are automatically re-created for all strategies"}),e.jsx("li",{children:'Stale "running" flags are cleaned up on startup'}),e.jsx("li",{children:"Strategies will auto-start at their next scheduled time"})]}),e.jsxs(m,{children:[e.jsx(x,{children:"Manual Stop Persists"}),e.jsxs(p,{children:["If you manually stopped a strategy before the restart, it stays stopped. The ",e.jsx("code",{children:"manually_stopped"})," flag persists and the strategy won't auto-start until you click Start."]})]})]})]}),e.jsxs(s,{value:"migration",children:[e.jsx(t,{children:"I upgraded to exchange-aware /python. What do I need to do?"}),e.jsxs(r,{className:"text-muted-foreground space-y-3",children:[e.jsxs("p",{children:[e.jsx("strong",{children:"No data migration required."})," On the first restart after upgrading, ",e.jsx("code",{children:"load_configs()"})," writes ",e.jsx("code",{children:'"exchange": "NSE"'})," into any legacy entry missing the field."]}),e.jsxs("ul",{className:"list-disc list-inside space-y-1 ml-2",children:[e.jsx("li",{children:"No strategy is force-restarted or force-stopped by the upgrade"}),e.jsx("li",{children:"Legacy strategies keep running gated on NSE"}),e.jsxs("li",{children:["Strategies that trade MCX/CRYPTO need a ",e.jsx("strong",{children:"one-time UI edit"}),": Schedule → pick the correct exchange → Save"]}),e.jsxs("li",{children:[e.jsx("code",{children:"manually_stopped"})," strategies stay manually stopped"]}),e.jsxs("li",{children:["Rolling back to the previous code ignores the new ",e.jsx("code",{children:"exchange"})," field — forward-compatible"]})]})]})]}),e.jsxs(s,{value:"best-practices",children:[e.jsx(t,{children:"Best practices for writing strategies"}),e.jsx(r,{className:"text-muted-foreground space-y-2",children:e.jsxs("ul",{className:"list-disc list-inside space-y-2 ml-2",children:[e.jsxs("li",{children:[e.jsx("strong",{children:"Read config from env vars"})," — Use ",e.jsx("code",{children:"os.getenv()"})," with sensible fallbacks so the same script works standalone and under the /python runner"]}),e.jsxs("li",{children:[e.jsx("strong",{children:"Read OPENALGO_STRATEGY_EXCHANGE"})," — Wire the exchange from the host so your orders match the calendar"]}),e.jsxs("li",{children:[e.jsx("strong",{children:"Use print() for logging"})," — All output goes to log files"]}),e.jsxs("li",{children:[e.jsx("strong",{children:"Handle exceptions"})," — Wrap critical code in try/except"]}),e.jsxs("li",{children:[e.jsx("strong",{children:"Add sleep intervals"})," — Don't spam API calls, use ",e.jsx("code",{children:"time.sleep()"})]}),e.jsxs("li",{children:[e.jsx("strong",{children:"Handle KeyboardInterrupt"})," — The host sends SIGTERM to stop strategies; clean up open positions in the handler"]}),e.jsxs("li",{children:[e.jsx("strong",{children:"Test with small quantities"})," — Start with 1 share/lot"]}),e.jsxs("li",{children:[e.jsx("strong",{children:"Monitor logs initially"})," — Watch the first few runs closely"]})]})})]}),e.jsxs(s,{value:"add-libraries",children:[e.jsx(t,{children:"How do I add new libraries like TA-Lib, pandas-ta, etc.?"}),e.jsxs(r,{className:"text-muted-foreground space-y-3",children:[e.jsx("p",{children:"If your strategy needs additional Python libraries, install them in OpenAlgo's environment."}),e.jsxs("div",{className:"space-y-4",children:[e.jsxs("div",{className:"bg-muted p-3 rounded-lg",children:[e.jsx("p",{className:"font-medium mb-2",children:"Using UV (Recommended)"}),e.jsxs("ol",{className:"list-decimal list-inside space-y-1 ml-2 text-sm",children:[e.jsxs("li",{children:["Open ",e.jsx("code",{children:"pyproject.toml"})," and add your library to the"," ",e.jsx("code",{children:"dependencies"})," section"]}),e.jsxs("li",{children:["Run ",e.jsx("code",{children:"uv sync"})," in the openalgo directory"]}),e.jsx("li",{children:"Restart OpenAlgo"})]})]}),e.jsxs("div",{className:"bg-muted p-3 rounded-lg",children:[e.jsx("p",{className:"font-medium mb-2",children:"Using Regular Python venv"}),e.jsxs("ol",{className:"list-decimal list-inside space-y-1 ml-2 text-sm",children:[e.jsxs("li",{children:["Add your library to ",e.jsx("code",{children:"requirements.txt"})]}),e.jsxs("li",{children:["Activate your venv and run"," ",e.jsx("code",{children:"pip install -r requirements.txt"})]}),e.jsx("li",{children:"Restart OpenAlgo"})]})]})]}),e.jsxs(m,{children:[e.jsx(x,{children:"TA-Lib Installation Note"}),e.jsxs(p,{children:["TA-Lib requires the underlying C library to be installed first. On Mac: ",e.jsx("code",{children:"brew install ta-lib"})," | ","On Ubuntu: ",e.jsx("code",{children:"sudo apt-get install libta-lib-dev"})]})]})]})]}),e.jsxs(s,{value:"troubleshooting",children:[e.jsx(t,{children:"Troubleshooting common issues"}),e.jsx(r,{className:"text-muted-foreground space-y-3",children:e.jsxs("div",{className:"space-y-2 text-sm",children:[e.jsxs("div",{className:"bg-muted p-3 rounded-lg",children:[e.jsx("p",{className:"font-medium",children:"Strategy didn't run on a partial holiday (e.g. MCX evening on NSE holiday)"}),e.jsxs("ul",{className:"list-disc list-inside space-y-1 ml-2 mt-1",children:[e.jsxs("li",{children:["Open the strategy → Schedule → confirm ",e.jsx("strong",{children:"Exchange"})," is set to the right market (legacy strategies default to NSE)"]}),e.jsx("li",{children:"Confirm the date has a row in Admin → Holidays with the partial-open window for your exchange"}),e.jsx("li",{children:"Confirm your schedule overlaps the calendar window — they intersect"})]})]}),e.jsxs("div",{className:"bg-muted p-3 rounded-lg",children:[e.jsx("p",{className:"font-medium",children:'Orders rejected with "market closed" while strategy is running'}),e.jsxs("p",{className:"mt-1",children:["Your script's hardcoded ",e.jsx("code",{children:'exchange="NSE"'})," doesn't match the host's"," ",e.jsx("code",{children:'exchange="MCX"'}),". Read ",e.jsx("code",{children:"OPENALGO_STRATEGY_EXCHANGE"})," in your script (see Environment Variables above)."]})]}),e.jsxs("div",{className:"bg-muted p-3 rounded-lg",children:[e.jsx("p",{className:"font-medium",children:"Strategy ran on a Sunday/Saturday unexpectedly"}),e.jsxs("p",{className:"mt-1",children:["That's by design — the calendar's SPECIAL_SESSION row overrides the weekend reject. To opt out, remove Sat/Sun from ",e.jsx("code",{children:"schedule_days"}),"."]})]}),e.jsxs("div",{className:"bg-muted p-3 rounded-lg",children:[e.jsx("p",{className:"font-medium",children:"Strategy crashed with MemoryError"}),e.jsxs("p",{className:"mt-1",children:["The per-strategy memory limit was exceeded. Check if your strategy loads large datasets. Increase ",e.jsx("code",{children:"STRATEGY_MEMORY_LIMIT_MB"})," in ",e.jsx("code",{children:".env"})," or optimize memory usage."]})]}),e.jsxs("div",{className:"bg-muted p-3 rounded-lg",children:[e.jsx("p",{className:"font-medium",children:"OPENALGO_API_KEY not set"}),e.jsxs("p",{className:"mt-1",children:["Make sure you have generated an API key at"," ",e.jsx(c,{to:"/apikey",className:"text-primary hover:underline",children:"API Key"}),". The /python runner injects it automatically from the database."]})]})]})})]})]})})]}),e.jsxs(n,{children:[e.jsx(l,{children:e.jsx(i,{children:"OpenAlgo SDK Quick Reference"})}),e.jsxs(d,{className:"space-y-4",children:[e.jsxs("div",{className:"grid gap-3 text-sm",children:[e.jsxs("div",{className:"bg-muted p-3 rounded-lg",children:[e.jsx("p",{className:"font-medium mb-1",children:"Initialize Client"}),e.jsx("code",{className:"text-xs",children:"client = api(api_key=API_KEY, host=API_HOST, ws_url=WS_URL)"})]}),e.jsxs("div",{className:"bg-muted p-3 rounded-lg",children:[e.jsx("p",{className:"font-medium mb-1",children:"Place Order"}),e.jsx("code",{className:"text-xs",children:"client.placeorder(strategy, symbol, exchange, action, quantity, price_type, product)"})]}),e.jsxs("div",{className:"bg-muted p-3 rounded-lg",children:[e.jsx("p",{className:"font-medium mb-1",children:"Historical Data"}),e.jsx("code",{className:"text-xs",children:"client.history(symbol, exchange, interval, start_date, end_date)"})]}),e.jsxs("div",{className:"bg-muted p-3 rounded-lg",children:[e.jsx("p",{className:"font-medium mb-1",children:"WebSocket (LTP)"}),e.jsx("code",{className:"text-xs",children:"client.connect(); client.subscribe_ltp(instruments, on_data_received=callback)"})]}),e.jsxs("div",{className:"bg-muted p-3 rounded-lg",children:[e.jsx("p",{className:"font-medium mb-1",children:"Get Quotes"}),e.jsx("code",{className:"text-xs",children:'client.quotes(symbol="RELIANCE", exchange="NSE")'})]}),e.jsxs("div",{className:"bg-muted p-3 rounded-lg",children:[e.jsx("p",{className:"font-medium mb-1",children:"Order Status"}),e.jsx("code",{className:"text-xs",children:"client.orderstatus(order_id=order_id, strategy=strategy_name)"})]}),e.jsxs("div",{className:"bg-muted p-3 rounded-lg",children:[e.jsx("p",{className:"font-medium mb-1",children:"Positions / Holdings"}),e.jsx("code",{className:"text-xs",children:"client.positionbook()  |  client.holdings()"})]})]}),e.jsxs("p",{className:"text-sm text-muted-foreground",children:["For complete SDK documentation, visit:"," ",e.jsx("a",{href:"https://docs.openalgo.in",target:"_blank",rel:"noopener noreferrer",className:"text-primary hover:underline",children:"docs.openalgo.in"})]})]})]}),e.jsxs(n,{children:[e.jsx(l,{children:e.jsx(i,{children:"Directory Structure"})}),e.jsx(d,{children:e.jsx("pre",{className:"bg-muted p-4 rounded-lg overflow-x-auto text-xs",children:e.jsx("code",{children:`strategies/
  scripts/          # Uploaded strategy files
  examples/         # Example strategies
  configs.json      # Strategy configurations (atomic write)
  README.md         # Detailed documentation
  RESOURCE_LIMITS.md

log/
  strategies/       # Strategy log files (per-strategy rotation)

examples/
  python/           # Standalone example scripts
    emacrossover_strategy_python.py  # Full EMA crossover sample`})})})]})]})}export{C as default};
