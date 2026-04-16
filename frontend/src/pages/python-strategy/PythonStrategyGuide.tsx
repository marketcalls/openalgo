import { Link } from 'react-router-dom'
import { showToast } from '@/utils/toast'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'

const sampleStrategy = `"""
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
`

const envVarsSnippet = `# API Configuration — auto-injected by the /python runner
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
MY_PARAM = os.getenv("MY_PARAM", "default_value")`

const copyToClipboard = (text: string) => {
  navigator.clipboard.writeText(text)
  showToast.success('Copied to clipboard', 'clipboard')
}

export default function PythonStrategyGuide() {
  return (
    <div className="container mx-auto py-6 space-y-6 max-w-4xl">
      {/* Back Button */}
      <Button variant="ghost" asChild>
        <Link to="/python">
          &larr; Back to Python Strategies
        </Link>
      </Button>

      {/* Header */}
      <div className="space-y-2">
        <h1 className="text-2xl font-bold tracking-tight">
          Python Strategy Guide
        </h1>
        <p className="text-muted-foreground">
          Self-host automated trading strategies inside OpenAlgo. Each strategy runs as an
          isolated subprocess with its own process, memory, and log file &mdash; managed
          through the <Link to="/python" className="text-primary hover:underline">/python</Link> dashboard.
        </p>
      </div>

      {/* Quick Start */}
      <Card>
        <CardHeader>
          <CardTitle>Quick Start</CardTitle>
          <CardDescription>Get your first strategy running in 5 minutes</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4">
            <div className="flex gap-4">
              <Badge className="h-6 w-6 rounded-full flex items-center justify-center shrink-0">1</Badge>
              <div>
                <p className="font-medium">Install OpenAlgo SDK</p>
                <div className="mt-1 flex items-center gap-2">
                  <code className="bg-muted px-2 py-1 rounded text-sm">pip install openalgo</code>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => copyToClipboard('pip install openalgo')}
                  >
                    Copy
                  </Button>
                </div>
              </div>
            </div>
            <div className="flex gap-4">
              <Badge className="h-6 w-6 rounded-full flex items-center justify-center shrink-0">2</Badge>
              <div>
                <p className="font-medium">Get your API Key</p>
                <p className="text-sm text-muted-foreground">
                  Go to <Link to="/apikey" className="text-primary hover:underline">API Key</Link> page
                  and copy your OpenAlgo API key
                </p>
              </div>
            </div>
            <div className="flex gap-4">
              <Badge className="h-6 w-6 rounded-full flex items-center justify-center shrink-0">3</Badge>
              <div>
                <p className="font-medium">Write your strategy</p>
                <p className="text-sm text-muted-foreground">
                  Create a Python file (.py) with your trading logic. Read configuration from
                  environment variables so it works both standalone and under the /python runner
                  without edits. See the sample strategy below.
                </p>
              </div>
            </div>
            <div className="flex gap-4">
              <Badge className="h-6 w-6 rounded-full flex items-center justify-center shrink-0">4</Badge>
              <div>
                <p className="font-medium">Upload and configure</p>
                <p className="text-sm text-muted-foreground">
                  On the <Link to="/python" className="text-primary hover:underline">Python Strategies</Link> page,
                  click <strong>Add Strategy</strong>. Pick a name, select the exchange
                  (NSE / MCX / CRYPTO / etc.), and add any custom parameters as environment variables.
                </p>
              </div>
            </div>
            <div className="flex gap-4">
              <Badge className="h-6 w-6 rounded-full flex items-center justify-center shrink-0">5</Badge>
              <div>
                <p className="font-medium">Start or schedule</p>
                <p className="text-sm text-muted-foreground">
                  Click <strong>Start</strong> to run immediately, or configure a schedule
                  (e.g. 09:15&ndash;15:30 Mon&ndash;Fri for NSE). The host auto-starts and
                  auto-stops your strategy at the scheduled times, respecting the exchange's
                  holiday calendar.
                </p>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* How It Works */}
      <Card>
        <CardHeader>
          <CardTitle>How It Works</CardTitle>
          <CardDescription>
            Process isolation, environment injection, and exchange-aware scheduling
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 text-sm">
          <div className="space-y-3">
            <div className="bg-muted p-3 rounded-lg">
              <p className="font-medium mb-1">Process Isolation</p>
              <p className="text-muted-foreground">
                Each strategy runs as a separate <code>subprocess.Popen</code> process with its own
                PID, memory, and file descriptors. A crash in one strategy cannot affect another
                or the host.
              </p>
            </div>
            <div className="bg-muted p-3 rounded-lg">
              <p className="font-medium mb-1">Environment Injection</p>
              <p className="text-muted-foreground">
                The host injects <code>OPENALGO_API_KEY</code>, <code>STRATEGY_ID</code>,{' '}
                <code>STRATEGY_NAME</code>, and <code>OPENALGO_STRATEGY_EXCHANGE</code> into
                each strategy's environment. Your <code>.env</code> variables (like{' '}
                <code>HOST_SERVER</code>, <code>WEBSOCKET_URL</code>) are also inherited.
                Custom parameters from the upload form become additional env vars.
              </p>
            </div>
            <div className="bg-muted p-3 rounded-lg">
              <p className="font-medium mb-1">Exchange-Aware Calendar</p>
              <p className="text-muted-foreground">
                Each strategy is tagged with an exchange. The host uses that exchange's
                holiday calendar to gate scheduled start/stop &mdash; an MCX strategy keeps running
                on an NSE holiday during the MCX evening session, a CRYPTO strategy ignores
                all holidays.
              </p>
            </div>
            <div className="bg-muted p-3 rounded-lg">
              <p className="font-medium mb-1">Logging</p>
              <p className="text-muted-foreground">
                All <code>print()</code> output is captured in timestamped log files under{' '}
                <code>log/strategies/</code>. View them from the dashboard or via the Logs button
                on each strategy card.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Environment Variables */}
      <Card>
        <CardHeader>
          <CardTitle>Environment Variables</CardTitle>
          <CardDescription>
            Variables available inside your strategy script
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div>
            <p className="font-medium mb-2">Injected by the Platform</p>
            <p className="text-sm text-muted-foreground mb-3">
              These are set directly on each strategy subprocess by the /python runner:
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr className="border-b">
                    <th className="text-left py-2 pr-4 font-medium">Variable</th>
                    <th className="text-left py-2 font-medium">Description</th>
                  </tr>
                </thead>
                <tbody className="text-muted-foreground">
                  <tr className="border-b">
                    <td className="py-2 pr-4"><code>OPENALGO_API_KEY</code></td>
                    <td className="py-2">Decrypted API key for this user</td>
                  </tr>
                  <tr className="border-b">
                    <td className="py-2 pr-4"><code>STRATEGY_ID</code></td>
                    <td className="py-2">Unique identifier for this strategy</td>
                  </tr>
                  <tr className="border-b">
                    <td className="py-2 pr-4"><code>STRATEGY_NAME</code></td>
                    <td className="py-2">Name of the strategy (as entered at upload)</td>
                  </tr>
                  <tr className="border-b">
                    <td className="py-2 pr-4"><code>OPENALGO_STRATEGY_EXCHANGE</code></td>
                    <td className="py-2">
                      Exchange picked at upload/edit (NSE / BSE / NFO / BFO / MCX / BCD / CDS / CRYPTO).
                      Read this so your trading calls match the calendar the host gates against
                    </td>
                  </tr>
                  <tr className="border-b">
                    <td className="py-2 pr-4"><code>OPENALGO_HOST</code></td>
                    <td className="py-2">
                      Convenience fallback (<code>http://127.0.0.1:5000</code>).
                      Prefer <code>HOST_SERVER</code> instead
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <div>
            <p className="font-medium mb-2">Inherited from .env</p>
            <p className="text-sm text-muted-foreground mb-3">
              Strategies inherit every variable from OpenAlgo's <code>.env</code> via{' '}
              <code>os.environ.copy()</code>. The key ones for connecting back to OpenAlgo:
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr className="border-b">
                    <th className="text-left py-2 pr-4 font-medium">Variable</th>
                    <th className="text-left py-2 font-medium">Description</th>
                  </tr>
                </thead>
                <tbody className="text-muted-foreground">
                  <tr className="border-b">
                    <td className="py-2 pr-4"><code>HOST_SERVER</code></td>
                    <td className="py-2">
                      REST host, e.g. <code>http://127.0.0.1:5000</code> &mdash; canonical name in <code>.env</code>,
                      prefer this in scripts
                    </td>
                  </tr>
                  <tr className="border-b">
                    <td className="py-2 pr-4"><code>WEBSOCKET_URL</code></td>
                    <td className="py-2">Full WebSocket URL, e.g. <code>ws://127.0.0.1:8765</code></td>
                  </tr>
                  <tr className="border-b">
                    <td className="py-2 pr-4"><code>WEBSOCKET_HOST</code></td>
                    <td className="py-2">WebSocket host component, e.g. <code>127.0.0.1</code></td>
                  </tr>
                  <tr className="border-b">
                    <td className="py-2 pr-4"><code>WEBSOCKET_PORT</code></td>
                    <td className="py-2">WebSocket port, e.g. <code>8765</code></td>
                  </tr>
                  <tr className="border-b">
                    <td className="py-2 pr-4"><code>FLASK_HOST_IP</code> / <code>FLASK_PORT</code></td>
                    <td className="py-2">Flask binding address (available if you need raw components)</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <div>
            <p className="font-medium mb-2">Recommended Pattern in Scripts</p>
            <div className="relative">
              <Button
                variant="outline"
                size="sm"
                className="absolute top-2 right-2 z-10"
                onClick={() => copyToClipboard(envVarsSnippet)}
              >
                Copy
              </Button>
              <pre className="bg-muted p-4 rounded-lg overflow-x-auto text-xs">
                <code>{envVarsSnippet}</code>
              </pre>
            </div>
          </div>

          <Alert>
            <AlertTitle>Reading OPENALGO_STRATEGY_EXCHANGE is strongly recommended</AlertTitle>
            <AlertDescription>
              If your script hardcodes <code>exchange = "NSE"</code>, the host will still gate
              it correctly per its config (e.g. the host runs your script during the MCX evening
              session because <code>exchange=MCX</code>), but your{' '}
              <code>client.placeorder(exchange="NSE", ...)</code> calls will still send NSE
              orders &mdash; and the broker will reject them. Wiring the env var keeps host
              calendar and script orders aligned.
            </AlertDescription>
          </Alert>
        </CardContent>
      </Card>

      {/* Exchange-Aware Scheduling */}
      <Card>
        <CardHeader>
          <CardTitle>Exchange-Aware Scheduling</CardTitle>
          <CardDescription>
            Each strategy's exchange drives which holiday calendar the host uses
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="space-y-3 text-sm">
            <p className="text-muted-foreground">
              When you upload or edit a strategy, you pick an exchange. The host uses that
              exchange's calendar to decide whether to start/stop the strategy on any given day.
              This means:
            </p>
            <ul className="list-disc list-inside space-y-1 ml-2 text-muted-foreground">
              <li>An <strong>MCX</strong> strategy keeps running on NSE/BSE holidays if MCX has a session</li>
              <li>A <strong>CRYPTO</strong> strategy ignores all holidays and weekends (24/7)</li>
              <li><strong>SPECIAL_SESSION</strong> rows (Muhurat, DR-drill) override weekend rejects per-exchange</li>
            </ul>
          </div>

          <div>
            <p className="font-medium mb-2">Supported Exchanges</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-sm">
              <div className="bg-muted p-2 rounded">
                <strong>NSE</strong> &mdash; Equity (09:15&ndash;15:30)
              </div>
              <div className="bg-muted p-2 rounded">
                <strong>BSE</strong> &mdash; Equity (09:15&ndash;15:30)
              </div>
              <div className="bg-muted p-2 rounded">
                <strong>NFO</strong> &mdash; NSE F&O (09:15&ndash;15:30)
              </div>
              <div className="bg-muted p-2 rounded">
                <strong>BFO</strong> &mdash; BSE F&O (09:15&ndash;15:30)
              </div>
              <div className="bg-muted p-2 rounded">
                <strong>CDS</strong> &mdash; NSE Currency (09:00&ndash;17:00)
              </div>
              <div className="bg-muted p-2 rounded">
                <strong>BCD</strong> &mdash; BSE Currency (09:00&ndash;17:00)
              </div>
              <div className="bg-muted p-2 rounded">
                <strong>MCX</strong> &mdash; Commodity (09:00&ndash;23:55)
              </div>
              <div className="bg-muted p-2 rounded">
                <strong>CRYPTO</strong> &mdash; 24/7 (no holidays)
              </div>
            </div>
            <p className="text-xs text-muted-foreground mt-2">
              Timings shown are defaults. Per-date overrides (partial holidays, special sessions) come from the market calendar DB.
            </p>
          </div>

          <div>
            <p className="font-medium mb-2">Schedule Intersection Rule</p>
            <p className="text-sm text-muted-foreground mb-3">
              The effective trading window is the <strong>intersection</strong> of your{' '}
              <code>start..stop</code> time and the exchange's session for that specific date.
            </p>
            <div className="bg-muted p-3 rounded-lg text-sm space-y-1">
              <p><strong>Example:</strong> MCX strategy scheduled 09:15&ndash;23:55</p>
              <p className="text-muted-foreground">
                On 14-Apr-2026 (Ambedkar Jayanti), MCX has a partial holiday with an evening
                session 17:00&ndash;23:55. The effective window becomes{' '}
                <strong>17:00&ndash;23:55</strong> (the intersection). You don't need to change
                the schedule for partial holidays.
              </p>
            </div>
          </div>

          <div>
            <p className="font-medium mb-3">Worked Examples</p>
            <div className="overflow-x-auto">
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr className="border-b">
                    <th className="text-left py-2 pr-3 font-medium">Scenario</th>
                    <th className="text-left py-2 pr-3 font-medium">Exchange</th>
                    <th className="text-left py-2 font-medium">Strategy Behavior</th>
                  </tr>
                </thead>
                <tbody className="text-muted-foreground">
                  <tr className="border-b">
                    <td className="py-2 pr-3" rowSpan={3}>
                      <strong>14-Apr-2026</strong><br />
                      <span className="text-xs">Ambedkar Jayanti</span>
                    </td>
                    <td className="py-2 pr-3">NSE / BSE / NFO</td>
                    <td className="py-2">Closed all day. Strategies paused at 00:01 IST</td>
                  </tr>
                  <tr className="border-b">
                    <td className="py-2 pr-3">MCX</td>
                    <td className="py-2">Open 17:00&ndash;23:55. MCX strategies auto-start at 17:00</td>
                  </tr>
                  <tr className="border-b">
                    <td className="py-2 pr-3">CRYPTO</td>
                    <td className="py-2">Unaffected (24/7)</td>
                  </tr>
                  <tr className="border-b">
                    <td className="py-2 pr-3" rowSpan={3}>
                      <strong>8-Nov-2026</strong><br />
                      <span className="text-xs">Sunday Diwali Muhurat</span>
                    </td>
                    <td className="py-2 pr-3">NSE / BSE / NFO</td>
                    <td className="py-2">SPECIAL_SESSION 18:00&ndash;19:15. Runs only inside that window, despite being Sunday</td>
                  </tr>
                  <tr className="border-b">
                    <td className="py-2 pr-3">MCX</td>
                    <td className="py-2">SPECIAL_SESSION 18:00&ndash;00:15 next day</td>
                  </tr>
                  <tr className="border-b">
                    <td className="py-2 pr-3">CRYPTO</td>
                    <td className="py-2">Unaffected (24/7)</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <div>
            <p className="font-medium mb-2">How the Host Gates Strategies</p>
            <div className="space-y-2 text-sm text-muted-foreground">
              <div className="bg-muted p-3 rounded-lg">
                <strong>1. Cron job</strong> &mdash; Fires <code>start_&lt;sid&gt;</code> at
                your <code>start_time</code> on each day in <code>schedule_days</code>.
              </div>
              <div className="bg-muted p-3 rounded-lg">
                <strong>2. Daily check (00:01 IST)</strong> &mdash; For each scheduled strategy,
                looks up <code>get_market_status(config["exchange"])</code>. If the exchange has
                no session today, the strategy is stopped and marked{' '}
                <code>paused_reason=holiday|weekend</code>.
              </div>
              <div className="bg-muted p-3 rounded-lg">
                <strong>3. Per-minute enforcer</strong> &mdash; Same per-strategy check. When
                the exchange reopens (or a special session starts), previously-paused strategies
                are auto-resumed (unless <code>manually_stopped</code>).
              </div>
            </div>
          </div>

          <div className="bg-primary/10 border border-primary/20 p-3 rounded-lg text-sm">
            <p className="font-medium text-primary">Smart Defaults When Uploading</p>
            <p className="text-muted-foreground mt-1">
              Picking an exchange pre-fills sensible defaults: CRYPTO auto-selects all 7 days
              and 00:00&ndash;23:59, MCX defaults to 09:00&ndash;23:55 weekdays, and equity
              exchanges default to 09:15&ndash;15:30 Mon&ndash;Fri.
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Sample Strategy */}
      <Card>
        <CardHeader>
          <CardTitle>Sample Strategy: EMA Crossover</CardTitle>
          <CardDescription>
            WebSocket-driven EMA crossover with real-time SL/target monitoring.
            All config is overridable via env vars &mdash; works standalone and under the
            /python runner without edits.
            Full version at <code>examples/python/emacrossover_strategy_python.py</code>
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="relative">
            <Button
              variant="outline"
              size="sm"
              className="absolute top-2 right-2 z-10"
              onClick={() => copyToClipboard(sampleStrategy)}
            >
              Copy
            </Button>
            <pre className="bg-muted p-4 rounded-lg overflow-x-auto text-xs max-h-[32rem] overflow-y-auto">
              <code>{sampleStrategy}</code>
            </pre>
          </div>
        </CardContent>
      </Card>

      {/* FAQ */}
      <Card>
        <CardHeader>
          <CardTitle>Frequently Asked Questions</CardTitle>
        </CardHeader>
        <CardContent>
          <Accordion type="single" collapsible className="w-full">
            <AccordionItem value="logs">
              <AccordionTrigger>
                How do I see my strategy logs?
              </AccordionTrigger>
              <AccordionContent className="text-muted-foreground space-y-2">
                <p>
                  All <code>print()</code> statements in your strategy are captured in log files.
                </p>
                <p>To view logs:</p>
                <ol className="list-decimal list-inside space-y-1 ml-2">
                  <li>Click the <strong>Logs</strong> button on your strategy card</li>
                  <li>Select a log file from the list (newest first)</li>
                  <li>Enable <strong>Auto-refresh</strong> to see live updates while running</li>
                </ol>
                <p className="text-sm">
                  Log files are stored in: <code>log/strategies/</code>. Per-strategy limits:
                  max {'{'}STRATEGY_LOG_MAX_FILES{'}'} files, {'{'}STRATEGY_LOG_MAX_SIZE_MB{'}'} MB total,
                  retained for {'{'}STRATEGY_LOG_RETENTION_DAYS{'}'} days. Override these in <code>.env</code>.
                </p>
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="scheduling">
              <AccordionTrigger>
                How does scheduling work?
              </AccordionTrigger>
              <AccordionContent className="text-muted-foreground space-y-3">
                <p>
                  Every strategy has a schedule that controls when the host automatically starts and stops it.
                </p>

                <div className="space-y-2">
                  <p className="font-medium">Schedule Configuration:</p>
                  <ul className="list-disc list-inside space-y-1 ml-2">
                    <li><strong>Exchange:</strong> Drives the holiday calendar (NSE / MCX / CRYPTO / etc.)</li>
                    <li><strong>Start Time:</strong> When the strategy auto-starts (IST, 24-hour format)</li>
                    <li><strong>Stop Time:</strong> When to auto-stop (IST, 24-hour format)</li>
                    <li><strong>Days:</strong> Which days to run (can include weekends for special sessions)</li>
                  </ul>
                </div>

                <div className="bg-muted p-3 rounded-lg space-y-2 text-sm">
                  <p className="font-medium">Example Schedules:</p>
                  <ul className="list-disc list-inside space-y-1 ml-2">
                    <li>NSE EMA strategy: 09:15&ndash;15:30, Mon&ndash;Fri</li>
                    <li>MCX evening strategy: 17:00&ndash;23:55, Mon&ndash;Fri</li>
                    <li>CRYPTO arb: 00:00&ndash;23:59, all 7 days</li>
                  </ul>
                </div>

                <Alert>
                  <AlertTitle>Holiday &amp; Weekend Protection</AlertTitle>
                  <AlertDescription>
                    The host checks each strategy's exchange calendar before starting it.
                    An NSE strategy won't start on NSE holidays, even if scheduled.
                    Weekend strategies are blocked unless the calendar has a SPECIAL_SESSION row
                    for that exchange on that date, or the exchange is CRYPTO (always open).
                  </AlertDescription>
                </Alert>
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="status-indicators">
              <AccordionTrigger>
                What do the status indicators mean?
              </AccordionTrigger>
              <AccordionContent className="text-muted-foreground space-y-3">
                <p>Each strategy displays a status badge showing its current state:</p>

                <div className="space-y-2">
                  <div className="flex items-center gap-3 p-2 bg-muted rounded">
                    <Badge className="bg-green-500 text-white">Running</Badge>
                    <span className="text-sm">Strategy is actively running and executing trades</span>
                  </div>
                  <div className="flex items-center gap-3 p-2 bg-muted rounded">
                    <Badge className="bg-blue-500 text-white">Scheduled</Badge>
                    <div className="text-sm">
                      <p>Strategy is armed and will auto-start at the scheduled time</p>
                      <p className="text-xs text-muted-foreground mt-1">
                        Shows context: "Starts today at 9:15 IST" or "Next: Mon, Tue at 9:15 IST"
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3 p-2 bg-muted rounded">
                    <Badge className="bg-orange-500 text-white">Manual Stop</Badge>
                    <span className="text-sm">Strategy was manually stopped &mdash; won't auto-start until you click Start</span>
                  </div>
                  <div className="flex items-center gap-3 p-2 bg-muted rounded">
                    <Badge className="bg-yellow-500 text-white">Paused</Badge>
                    <span className="text-sm">Strategy is paused due to market holiday for its exchange</span>
                  </div>
                  <div className="flex items-center gap-3 p-2 bg-muted rounded">
                    <Badge className="bg-red-500 text-white">Error</Badge>
                    <span className="text-sm">Strategy encountered an error and crashed</span>
                  </div>
                </div>
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="start-stop">
              <AccordionTrigger>
                How does Start and Stop work?
              </AccordionTrigger>
              <AccordionContent className="text-muted-foreground space-y-3">
                <div className="bg-green-500/10 border border-green-500/20 p-3 rounded-lg">
                  <p className="font-medium text-green-600">Start Button</p>
                  <ul className="list-disc list-inside space-y-1 ml-2 mt-2 text-sm">
                    <li><strong>Within schedule:</strong> Strategy starts running immediately</li>
                    <li><strong>Outside schedule:</strong> Strategy is "armed" &mdash; status changes to "Scheduled"</li>
                    <li>Button changes to <strong>Cancel</strong> after arming</li>
                  </ul>
                </div>

                <div className="bg-red-500/10 border border-red-500/20 p-3 rounded-lg">
                  <p className="font-medium text-red-600">Stop Button (when running)</p>
                  <ul className="list-disc list-inside space-y-1 ml-2 mt-2 text-sm">
                    <li>Stops the running strategy process (SIGTERM)</li>
                    <li>Sets "manually stopped" flag &mdash; won't auto-start</li>
                    <li>Status shows "Manual Stop"</li>
                  </ul>
                </div>

                <div className="bg-orange-500/10 border border-orange-500/20 p-3 rounded-lg">
                  <p className="font-medium text-orange-600">Cancel Button (when scheduled)</p>
                  <ul className="list-disc list-inside space-y-1 ml-2 mt-2 text-sm">
                    <li>Cancels the scheduled auto-start</li>
                    <li>Sets "manually stopped" flag</li>
                    <li>Click Start again to re-arm</li>
                  </ul>
                </div>

                <div className="bg-muted p-3 rounded-lg text-sm">
                  <p className="font-medium">Use Cases</p>
                  <ul className="list-disc list-inside space-y-1 ml-2 mt-2">
                    <li><strong>Evening setup:</strong> Click Start at night, strategy runs at 9:15 AM next day</li>
                    <li><strong>Vacation mode:</strong> Click Stop, strategy stays off until you return</li>
                    <li><strong>Testing:</strong> Edit schedule to test now, then revert schedule after</li>
                  </ul>
                </div>
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="special-sessions">
              <AccordionTrigger>
                What about special trading sessions (Muhurat, Budget Day)?
              </AccordionTrigger>
              <AccordionContent className="text-muted-foreground space-y-3">
                <p>
                  Exchanges occasionally conduct special sessions on holidays or weekends.
                  The exchange-aware calendar handles these automatically:
                </p>

                <div className="space-y-2 text-sm">
                  <div className="bg-muted p-3 rounded-lg">
                    <p className="font-medium">Automatic Handling (Recommended)</p>
                    <ol className="list-decimal list-inside space-y-1 ml-2 mt-2">
                      <li>
                        Go to <Link to="/admin/holidays" className="text-primary hover:underline">Admin &rarr; Holidays</Link>
                      </li>
                      <li>
                        Add a <strong>SPECIAL_SESSION</strong> row for the date and exchange with the
                        session timing (e.g. Muhurat: NSE 18:00&ndash;19:15)
                      </li>
                      <li>
                        Ensure the relevant day (Sat/Sun) is in your strategy's <code>schedule_days</code>
                      </li>
                      <li>
                        The host auto-starts the strategy within the special session window &mdash;
                        no schedule edits needed, no need to revert afterward
                      </li>
                    </ol>
                  </div>

                  <div className="bg-muted p-3 rounded-lg">
                    <p className="font-medium">Manual Override</p>
                    <p className="mt-1">
                      Log in to OpenAlgo before the session, wait for master contracts to download,
                      and click <strong>Start</strong> manually. Click <strong>Stop</strong> when the session ends.
                    </p>
                  </div>
                </div>
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="master-contract">
              <AccordionTrigger>
                Why does my strategy need master contracts?
              </AccordionTrigger>
              <AccordionContent className="text-muted-foreground space-y-2">
                <p>
                  Master contracts contain the symbol mappings required by your broker.
                  Strategies cannot start until master contracts are downloaded.
                </p>
                <p>Master contracts are automatically downloaded when you:</p>
                <ol className="list-decimal list-inside space-y-1 ml-2">
                  <li>Log in to OpenAlgo</li>
                  <li>Wait for the download to complete (shown in header)</li>
                </ol>
                <p className="text-sm">
                  If you see "Waiting for master contracts", just wait a moment after login.
                </p>
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="resource-limits">
              <AccordionTrigger>
                Are there resource limits?
              </AccordionTrigger>
              <AccordionContent className="text-muted-foreground space-y-3">
                <p>
                  On Linux/macOS, per-strategy resource limits prevent buggy scripts from
                  crashing OpenAlgo. On Windows, these are not enforced at the OS level.
                </p>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm border-collapse">
                    <thead>
                      <tr className="border-b">
                        <th className="text-left py-2 pr-4 font-medium">Resource</th>
                        <th className="text-left py-2 pr-4 font-medium">Default Limit</th>
                        <th className="text-left py-2 font-medium">Override (.env)</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr className="border-b">
                        <td className="py-2 pr-4">Memory (virtual)</td>
                        <td className="py-2 pr-4">1024 MB</td>
                        <td className="py-2"><code>STRATEGY_MEMORY_LIMIT_MB</code></td>
                      </tr>
                      <tr className="border-b">
                        <td className="py-2 pr-4">CPU time (cumulative)</td>
                        <td className="py-2 pr-4">3600 seconds</td>
                        <td className="py-2">Hardcoded</td>
                      </tr>
                      <tr className="border-b">
                        <td className="py-2 pr-4">Open file descriptors</td>
                        <td className="py-2 pr-4">256</td>
                        <td className="py-2">Hardcoded</td>
                      </tr>
                      <tr className="border-b">
                        <td className="py-2 pr-4">Max processes</td>
                        <td className="py-2 pr-4">256</td>
                        <td className="py-2">Hardcoded</td>
                      </tr>
                      <tr className="border-b">
                        <td className="py-2 pr-4">Log files per strategy</td>
                        <td className="py-2 pr-4">10 files</td>
                        <td className="py-2"><code>STRATEGY_LOG_MAX_FILES</code></td>
                      </tr>
                      <tr className="border-b">
                        <td className="py-2 pr-4">Log size per strategy</td>
                        <td className="py-2 pr-4">50 MB</td>
                        <td className="py-2"><code>STRATEGY_LOG_MAX_SIZE_MB</code></td>
                      </tr>
                      <tr className="border-b">
                        <td className="py-2 pr-4">Log retention</td>
                        <td className="py-2 pr-4">7 days</td>
                        <td className="py-2"><code>STRATEGY_LOG_RETENTION_DAYS</code></td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <p className="text-sm">
                  A typical EMA/crossover strategy uses 80&ndash;120 MB of RAM and 5&ndash;10 file descriptors.
                  The defaults are generous. For simple strategies, lower memory to 256&ndash;512 MB and
                  run more strategies concurrently.
                </p>
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="restart">
              <AccordionTrigger>
                What happens if I restart OpenAlgo?
              </AccordionTrigger>
              <AccordionContent className="text-muted-foreground space-y-3">
                <p>OpenAlgo handles restarts gracefully:</p>
                <ul className="list-disc list-inside space-y-1 ml-2">
                  <li>Strategy configurations are saved to disk and persist</li>
                  <li>Schedules are automatically re-created for all strategies</li>
                  <li>Stale "running" flags are cleaned up on startup</li>
                  <li>Strategies will auto-start at their next scheduled time</li>
                </ul>

                <Alert>
                  <AlertTitle>Manual Stop Persists</AlertTitle>
                  <AlertDescription>
                    If you manually stopped a strategy before the restart, it stays stopped.
                    The <code>manually_stopped</code> flag persists and the strategy won't
                    auto-start until you click Start.
                  </AlertDescription>
                </Alert>
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="migration">
              <AccordionTrigger>
                I upgraded to exchange-aware /python. What do I need to do?
              </AccordionTrigger>
              <AccordionContent className="text-muted-foreground space-y-3">
                <p>
                  <strong>No data migration required.</strong> On the first restart after
                  upgrading, <code>load_configs()</code> writes <code>"exchange": "NSE"</code> into
                  any legacy entry missing the field.
                </p>
                <ul className="list-disc list-inside space-y-1 ml-2">
                  <li>No strategy is force-restarted or force-stopped by the upgrade</li>
                  <li>Legacy strategies keep running gated on NSE</li>
                  <li>Strategies that trade MCX/CRYPTO need a <strong>one-time UI edit</strong>: Schedule &rarr; pick the correct exchange &rarr; Save</li>
                  <li><code>manually_stopped</code> strategies stay manually stopped</li>
                  <li>Rolling back to the previous code ignores the new <code>exchange</code> field &mdash; forward-compatible</li>
                </ul>
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="best-practices">
              <AccordionTrigger>
                Best practices for writing strategies
              </AccordionTrigger>
              <AccordionContent className="text-muted-foreground space-y-2">
                <ul className="list-disc list-inside space-y-2 ml-2">
                  <li>
                    <strong>Read config from env vars</strong> &mdash; Use <code>os.getenv()</code> with
                    sensible fallbacks so the same script works standalone and under the /python runner
                  </li>
                  <li>
                    <strong>Read OPENALGO_STRATEGY_EXCHANGE</strong> &mdash; Wire the exchange from
                    the host so your orders match the calendar
                  </li>
                  <li>
                    <strong>Use print() for logging</strong> &mdash; All output goes to log files
                  </li>
                  <li>
                    <strong>Handle exceptions</strong> &mdash; Wrap critical code in try/except
                  </li>
                  <li>
                    <strong>Add sleep intervals</strong> &mdash; Don't spam API calls, use <code>time.sleep()</code>
                  </li>
                  <li>
                    <strong>Handle KeyboardInterrupt</strong> &mdash; The host sends SIGTERM to stop strategies;
                    clean up open positions in the handler
                  </li>
                  <li>
                    <strong>Test with small quantities</strong> &mdash; Start with 1 share/lot
                  </li>
                  <li>
                    <strong>Monitor logs initially</strong> &mdash; Watch the first few runs closely
                  </li>
                </ul>
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="add-libraries">
              <AccordionTrigger>
                How do I add new libraries like TA-Lib, pandas-ta, etc.?
              </AccordionTrigger>
              <AccordionContent className="text-muted-foreground space-y-3">
                <p>
                  If your strategy needs additional Python libraries, install them in
                  OpenAlgo's environment.
                </p>

                <div className="space-y-4">
                  <div className="bg-muted p-3 rounded-lg">
                    <p className="font-medium mb-2">Using UV (Recommended)</p>
                    <ol className="list-decimal list-inside space-y-1 ml-2 text-sm">
                      <li>
                        Open <code>pyproject.toml</code> and add your library to the{' '}
                        <code>dependencies</code> section
                      </li>
                      <li>
                        Run <code>uv sync</code> in the openalgo directory
                      </li>
                      <li>Restart OpenAlgo</li>
                    </ol>
                  </div>

                  <div className="bg-muted p-3 rounded-lg">
                    <p className="font-medium mb-2">Using Regular Python venv</p>
                    <ol className="list-decimal list-inside space-y-1 ml-2 text-sm">
                      <li>
                        Add your library to <code>requirements.txt</code>
                      </li>
                      <li>
                        Activate your venv and run{' '}
                        <code>pip install -r requirements.txt</code>
                      </li>
                      <li>Restart OpenAlgo</li>
                    </ol>
                  </div>
                </div>

                <Alert>
                  <AlertTitle>TA-Lib Installation Note</AlertTitle>
                  <AlertDescription>
                    TA-Lib requires the underlying C library to be installed first.
                    On Mac: <code>brew install ta-lib</code>{' | '}
                    On Ubuntu: <code>sudo apt-get install libta-lib-dev</code>
                  </AlertDescription>
                </Alert>
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="troubleshooting">
              <AccordionTrigger>
                Troubleshooting common issues
              </AccordionTrigger>
              <AccordionContent className="text-muted-foreground space-y-3">
                <div className="space-y-2 text-sm">
                  <div className="bg-muted p-3 rounded-lg">
                    <p className="font-medium">Strategy didn't run on a partial holiday (e.g. MCX evening on NSE holiday)</p>
                    <ul className="list-disc list-inside space-y-1 ml-2 mt-1">
                      <li>Open the strategy &rarr; Schedule &rarr; confirm <strong>Exchange</strong> is set to the right market (legacy strategies default to NSE)</li>
                      <li>Confirm the date has a row in Admin &rarr; Holidays with the partial-open window for your exchange</li>
                      <li>Confirm your schedule overlaps the calendar window &mdash; they intersect</li>
                    </ul>
                  </div>

                  <div className="bg-muted p-3 rounded-lg">
                    <p className="font-medium">Orders rejected with "market closed" while strategy is running</p>
                    <p className="mt-1">
                      Your script's hardcoded <code>exchange="NSE"</code> doesn't match the host's{' '}
                      <code>exchange="MCX"</code>. Read <code>OPENALGO_STRATEGY_EXCHANGE</code> in your
                      script (see Environment Variables above).
                    </p>
                  </div>

                  <div className="bg-muted p-3 rounded-lg">
                    <p className="font-medium">Strategy ran on a Sunday/Saturday unexpectedly</p>
                    <p className="mt-1">
                      That's by design &mdash; the calendar's SPECIAL_SESSION row overrides the
                      weekend reject. To opt out, remove Sat/Sun from <code>schedule_days</code>.
                    </p>
                  </div>

                  <div className="bg-muted p-3 rounded-lg">
                    <p className="font-medium">Strategy crashed with MemoryError</p>
                    <p className="mt-1">
                      The per-strategy memory limit was exceeded. Check if your strategy loads
                      large datasets. Increase <code>STRATEGY_MEMORY_LIMIT_MB</code> in <code>.env</code> or
                      optimize memory usage.
                    </p>
                  </div>

                  <div className="bg-muted p-3 rounded-lg">
                    <p className="font-medium">OPENALGO_API_KEY not set</p>
                    <p className="mt-1">
                      Make sure you have generated an API key at{' '}
                      <Link to="/apikey" className="text-primary hover:underline">API Key</Link>.
                      The /python runner injects it automatically from the database.
                    </p>
                  </div>
                </div>
              </AccordionContent>
            </AccordionItem>
          </Accordion>
        </CardContent>
      </Card>

      {/* SDK Quick Reference */}
      <Card>
        <CardHeader>
          <CardTitle>OpenAlgo SDK Quick Reference</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 text-sm">
            <div className="bg-muted p-3 rounded-lg">
              <p className="font-medium mb-1">Initialize Client</p>
              <code className="text-xs">{'client = api(api_key=API_KEY, host=API_HOST, ws_url=WS_URL)'}</code>
            </div>
            <div className="bg-muted p-3 rounded-lg">
              <p className="font-medium mb-1">Place Order</p>
              <code className="text-xs">{'client.placeorder(strategy, symbol, exchange, action, quantity, price_type, product)'}</code>
            </div>
            <div className="bg-muted p-3 rounded-lg">
              <p className="font-medium mb-1">Historical Data</p>
              <code className="text-xs">{'client.history(symbol, exchange, interval, start_date, end_date)'}</code>
            </div>
            <div className="bg-muted p-3 rounded-lg">
              <p className="font-medium mb-1">WebSocket (LTP)</p>
              <code className="text-xs">{'client.connect(); client.subscribe_ltp(instruments, on_data_received=callback)'}</code>
            </div>
            <div className="bg-muted p-3 rounded-lg">
              <p className="font-medium mb-1">Get Quotes</p>
              <code className="text-xs">{'client.quotes(symbol="RELIANCE", exchange="NSE")'}</code>
            </div>
            <div className="bg-muted p-3 rounded-lg">
              <p className="font-medium mb-1">Order Status</p>
              <code className="text-xs">{'client.orderstatus(order_id=order_id, strategy=strategy_name)'}</code>
            </div>
            <div className="bg-muted p-3 rounded-lg">
              <p className="font-medium mb-1">Positions / Holdings</p>
              <code className="text-xs">{'client.positionbook()  |  client.holdings()'}</code>
            </div>
          </div>
          <p className="text-sm text-muted-foreground">
            For complete SDK documentation, visit:{' '}
            <a
              href="https://docs.openalgo.in"
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary hover:underline"
            >
              docs.openalgo.in
            </a>
          </p>
        </CardContent>
      </Card>

      {/* Directory Structure */}
      <Card>
        <CardHeader>
          <CardTitle>Directory Structure</CardTitle>
        </CardHeader>
        <CardContent>
          <pre className="bg-muted p-4 rounded-lg overflow-x-auto text-xs">
            <code>{`strategies/
  scripts/          # Uploaded strategy files
  examples/         # Example strategies
  configs.json      # Strategy configurations (atomic write)
  README.md         # Detailed documentation
  RESOURCE_LIMITS.md

log/
  strategies/       # Strategy log files (per-strategy rotation)

examples/
  python/           # Standalone example scripts
    emacrossover_strategy_python.py  # Full EMA crossover sample`}</code>
          </pre>
        </CardContent>
      </Card>
    </div>
  )
}
