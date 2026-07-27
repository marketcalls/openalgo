import {
  AlertTriangle,
  ArrowLeft,
  BookOpen,
  Calendar,
  Circle,
  Clock,
  Code,
  Copy,
  FileCode,
  HardDrive,
  Pencil,
  Play,
  ScrollText,
  Server,
  Shield,
  Square,
  Terminal,
} from 'lucide-react'
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
Sample EMA Crossover Strategy using OpenAlgo SDK
This strategy buys when fast EMA crosses above slow EMA
and sells when fast EMA crosses below slow EMA.
"""

from openalgo import api
import time

# Configuration
SYMBOL = "RELIANCE"
EXCHANGE = "NSE"
QUANTITY = 1
FAST_EMA = 9
SLOW_EMA = 21

# Initialize OpenAlgo client
client = api(
    api_key="YOUR_OPENALGO_API_KEY",
    host="http://127.0.0.1:5000"
)

def calculate_ema(prices, period):
    """Calculate Exponential Moving Average"""
    if len(prices) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = (price * multiplier) + (ema * (1 - multiplier))
    return ema

def get_ltp():
    """Get Last Traded Price"""
    try:
        quotes = client.quotes(symbol=SYMBOL, exchange=EXCHANGE)
        if quotes.get('status') == 'success':
            return quotes.get('data', {}).get('ltp')
    except Exception as e:
        print(f"Error fetching quotes: {e}")
    return None

def main():
    print(f"Starting EMA Crossover Strategy for {SYMBOL}")
    print(f"Fast EMA: {FAST_EMA}, Slow EMA: {SLOW_EMA}")

    prices = []
    position = None  # 'long', 'short', or None

    while True:
        try:
            ltp = get_ltp()
            if ltp:
                prices.append(ltp)
                # Keep only last 100 prices
                prices = prices[-100:]

                fast_ema = calculate_ema(prices, FAST_EMA)
                slow_ema = calculate_ema(prices, SLOW_EMA)

                if fast_ema and slow_ema:
                    print(f"LTP: {ltp:.2f} | Fast EMA: {fast_ema:.2f} | Slow EMA: {slow_ema:.2f}")

                    # Buy signal: Fast EMA crosses above Slow EMA
                    if fast_ema > slow_ema and position != 'long':
                        print("BUY SIGNAL!")
                        response = client.placeorder(
                            symbol=SYMBOL,
                            exchange=EXCHANGE,
                            action="BUY",
                            quantity=QUANTITY,
                            price_type="MARKET",
                            product_type="MIS"
                        )
                        print(f"Order response: {response}")
                        position = 'long'

                    # Sell signal: Fast EMA crosses below Slow EMA
                    elif fast_ema < slow_ema and position == 'long':
                        print("SELL SIGNAL!")
                        response = client.placeorder(
                            symbol=SYMBOL,
                            exchange=EXCHANGE,
                            action="SELL",
                            quantity=QUANTITY,
                            price_type="MARKET",
                            product_type="MIS"
                        )
                        print(f"Order response: {response}")
                        position = None

            time.sleep(5)  # Check every 5 seconds

        except KeyboardInterrupt:
            print("Strategy stopped by user")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
`

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
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to Python Strategies
        </Link>
      </Button>

      {/* Header */}
      <div className="space-y-2">
        <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
          <BookOpen className="h-6 w-6" />
          Python Strategy Guide
        </h1>
        <p className="text-muted-foreground">
          Learn how to create, upload, and run automated trading strategies using Python
        </p>
      </div>

      {/* Quick Start */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Play className="h-5 w-5 text-green-500" />
            Quick Start
          </CardTitle>
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
                    <Copy className="h-3 w-3" />
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
                  Create a Python file (.py) with your trading logic using the OpenAlgo SDK
                </p>
              </div>
            </div>
            <div className="flex gap-4">
              <Badge className="h-6 w-6 rounded-full flex items-center justify-center shrink-0">4</Badge>
              <div>
                <p className="font-medium">Upload with schedule</p>
                <p className="text-sm text-muted-foreground">
                  Upload your strategy file on the <Link to="/python" className="text-primary hover:underline">Python Strategies</Link> page.
                  Configure the mandatory schedule (default: Mon-Fri, 9:00 AM - 4:00 PM IST).
                </p>
              </div>
            </div>
            <div className="flex gap-4">
              <Badge className="h-6 w-6 rounded-full flex items-center justify-center shrink-0">5</Badge>
              <div>
                <p className="font-medium">Start your strategy</p>
                <p className="text-sm text-muted-foreground">
                  Click the <Play className="h-3 w-3 inline" /> Start button to run immediately, or let the scheduler auto-start it at the configured time.
                </p>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Sample Strategy */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Code className="h-5 w-5" />
            Sample Strategy: EMA Crossover
          </CardTitle>
          <CardDescription>
            A simple moving average crossover strategy you can use as a template
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
              <Copy className="h-4 w-4 mr-2" />
              Copy
            </Button>
            <pre className="bg-muted p-4 rounded-lg overflow-x-auto text-xs max-h-96 overflow-y-auto">
              <code>{sampleStrategy}</code>
            </pre>
          </div>
        </CardContent>
      </Card>

      {/* FAQ Accordion */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ScrollText className="h-5 w-5" />
            Frequently Asked Questions
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Accordion type="single" collapsible className="w-full">
            <AccordionItem value="logs">
              <AccordionTrigger>
                <span className="flex items-center gap-2">
                  <Terminal className="h-4 w-4" />
                  How do I see my strategy logs?
                </span>
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
                  Log files are stored in: <code>log/strategies/</code>
                </p>
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="scheduling">
              <AccordionTrigger>
                <span className="flex items-center gap-2">
                  <Calendar className="h-4 w-4" />
                  How does scheduling work?
                </span>
              </AccordionTrigger>
              <AccordionContent className="text-muted-foreground space-y-3">
                <p>
                  <strong>Scheduling is mandatory</strong> for all strategies. Every strategy must have a defined schedule
                  that controls when it automatically starts and stops.
                </p>

                <div className="bg-muted p-3 rounded-lg space-y-2">
                  <p className="font-medium">Default Schedule (when uploading):</p>
                  <ul className="list-disc list-inside space-y-1 ml-2 text-sm">
                    <li><strong>Start Time:</strong> 9:00 AM IST</li>
                    <li><strong>Stop Time:</strong> 4:00 PM IST</li>
                    <li><strong>Days:</strong> Monday to Friday</li>
                  </ul>
                </div>

                <div className="space-y-2">
                  <p className="font-medium">Schedule Configuration:</p>
                  <ul className="list-disc list-inside space-y-1 ml-2">
                    <li><strong>Start Time:</strong> When the strategy auto-starts (required)</li>
                    <li><strong>Stop Time:</strong> When to auto-stop (required)</li>
                    <li><strong>Days:</strong> Which days to run - can include weekends for special sessions</li>
                  </ul>
                </div>

                <div className="bg-primary/10 border border-primary/20 p-3 rounded-lg">
                  <p className="font-medium text-primary flex items-center gap-2">
                    <Pencil className="h-4 w-4" />
                    Editing Schedule
                  </p>
                  <p className="text-sm mt-1">
                    Click the <Pencil className="h-3 w-3 inline" /> <strong>Edit Schedule</strong> button on your strategy card to modify the schedule times and days.
                  </p>
                </div>

                <Alert className="mt-2">
                  <AlertTriangle className="h-4 w-4" />
                  <AlertTitle>Holiday Protection</AlertTitle>
                  <AlertDescription>
                    Scheduled strategies will NOT auto-start on market holidays, even if scheduled.
                    Weekend trading is allowed if you explicitly add Sat/Sun to the schedule days (for special sessions like Budget Day or Muhurat Trading).
                  </AlertDescription>
                </Alert>
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="status-indicators">
              <AccordionTrigger>
                <span className="flex items-center gap-2">
                  <Circle className="h-4 w-4" />
                  What do the status indicators mean?
                </span>
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
                      <p>Strategy is armed and will auto-start at scheduled time</p>
                      <p className="text-xs text-muted-foreground mt-1">
                        Shows context: "Starts today at 9:00 IST" or "Next: Mon, Tue at 9:00 IST"
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3 p-2 bg-muted rounded">
                    <Badge className="bg-orange-500 text-white">Manual Stop</Badge>
                    <span className="text-sm">Strategy was manually stopped - won't auto-start until you click Start</span>
                  </div>
                  <div className="flex items-center gap-3 p-2 bg-muted rounded">
                    <Badge className="bg-yellow-500 text-white">Paused</Badge>
                    <span className="text-sm">Strategy is paused due to market holiday</span>
                  </div>
                  <div className="flex items-center gap-3 p-2 bg-muted rounded">
                    <Badge className="bg-red-500 text-white">Error</Badge>
                    <span className="text-sm">Strategy encountered an error and crashed</span>
                  </div>
                </div>

                <p className="text-sm">
                  <strong>Tip:</strong> Hover over the status badge to see a detailed message like "Starts today at 09:00 IST" or "Next scheduled day at 09:15 IST".
                </p>
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="manual-stop">
              <AccordionTrigger>
                <span className="flex items-center gap-2">
                  <Square className="h-4 w-4" />
                  How does Start and Stop work?
                </span>
              </AccordionTrigger>
              <AccordionContent className="text-muted-foreground space-y-3">
                <div className="bg-green-500/10 border border-green-500/20 p-3 rounded-lg">
                  <p className="font-medium text-green-600 flex items-center gap-2">
                    <Play className="h-4 w-4" />
                    Start Button
                  </p>
                  <ul className="list-disc list-inside space-y-1 ml-2 mt-2 text-sm">
                    <li><strong>Within schedule:</strong> Strategy starts running immediately</li>
                    <li><strong>Outside schedule:</strong> Strategy is "armed" - status changes to "Scheduled"</li>
                    <li>Button changes to <strong>Cancel</strong> after arming</li>
                  </ul>
                </div>

                <div className="bg-red-500/10 border border-red-500/20 p-3 rounded-lg">
                  <p className="font-medium text-red-600 flex items-center gap-2">
                    <Square className="h-4 w-4" />
                    Stop Button (when running)
                  </p>
                  <ul className="list-disc list-inside space-y-1 ml-2 mt-2 text-sm">
                    <li>Stops the running strategy process</li>
                    <li>Sets "manually stopped" flag - won't auto-start</li>
                    <li>Status shows "Manual Stop"</li>
                  </ul>
                </div>

                <div className="bg-orange-500/10 border border-orange-500/20 p-3 rounded-lg">
                  <p className="font-medium text-orange-600 flex items-center gap-2">
                    <Square className="h-4 w-4" />
                    Cancel Button (when scheduled)
                  </p>
                  <ul className="list-disc list-inside space-y-1 ml-2 mt-2 text-sm">
                    <li>Cancels the scheduled auto-start</li>
                    <li>Sets "manually stopped" flag</li>
                    <li>Status changes from "Scheduled" to "Manual Stop"</li>
                    <li>Click Start again to re-arm</li>
                  </ul>
                </div>

                <div className="bg-muted p-3 rounded-lg">
                  <p className="font-medium">Use Cases</p>
                  <ul className="list-disc list-inside space-y-1 ml-2 mt-2 text-sm">
                    <li><strong>Evening setup:</strong> Click Start at night, strategy runs at 9:00 AM next day</li>
                    <li><strong>Vacation mode:</strong> Click Stop, strategy stays off until you return</li>
                    <li><strong>Testing:</strong> Edit schedule to test now, then revert schedule after</li>
                  </ul>
                </div>
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="special-trading">
              <AccordionTrigger>
                <span className="flex items-center gap-2">
                  <Calendar className="h-4 w-4" />
                  What about special trading sessions (Budget Day, Muhurat)?
                </span>
              </AccordionTrigger>
              <AccordionContent className="text-muted-foreground space-y-3">
                <p>
                  Exchanges occasionally conduct special trading sessions on holidays/weekends:
                </p>
                <ul className="list-disc list-inside space-y-1 ml-2">
                  <li><strong>Budget Day:</strong> Live trading on Union Budget day (e.g., Feb 1, 2026 - Sunday)</li>
                  <li><strong>Muhurat Trading:</strong> Diwali day special session (usually 1 hour evening)</li>
                  <li><strong>Special Saturday:</strong> Occasional Saturday trading sessions</li>
                </ul>

                <div className="bg-primary/10 border border-primary/20 p-4 rounded-lg mt-3">
                  <p className="font-semibold text-primary mb-3">Step-by-Step: Trading on Special Sessions</p>

                  <div className="space-y-4 text-sm">
                    <div className="flex gap-3">
                      <Badge className="h-6 w-6 rounded-full flex items-center justify-center shrink-0">1</Badge>
                      <div>
                        <p className="font-medium">Update Holiday Calendar (Optional but Recommended)</p>
                        <p className="text-muted-foreground">
                          Go to <Link to="/admin/holidays" className="text-primary hover:underline">Admin → Holidays</Link>
                        </p>
                        <ul className="list-disc list-inside ml-2 mt-1 text-muted-foreground">
                          <li>Find the special session date (e.g., Feb 1, 2026)</li>
                          <li>Delete it from holidays OR add special session timing</li>
                          <li>This enables the scheduler to auto-start if configured</li>
                        </ul>
                      </div>
                    </div>

                    <div className="flex gap-3">
                      <Badge className="h-6 w-6 rounded-full flex items-center justify-center shrink-0">2</Badge>
                      <div>
                        <p className="font-medium">Update Market Timings (If Different Hours)</p>
                        <p className="text-muted-foreground">
                          Go to <Link to="/admin/market-timings" className="text-primary hover:underline">Admin → Market Timings</Link>
                        </p>
                        <ul className="list-disc list-inside ml-2 mt-1 text-muted-foreground">
                          <li>Muhurat: Usually 6:00 PM - 7:00 PM (not regular hours)</li>
                          <li>Budget Day: Usually 9:00 AM - 3:30 PM</li>
                          <li>Update the timings for NSE/BSE/NFO as announced</li>
                        </ul>
                      </div>
                    </div>

                    <div className="flex gap-3">
                      <Badge className="h-6 w-6 rounded-full flex items-center justify-center shrink-0">3</Badge>
                      <div>
                        <p className="font-medium">Update Your Strategy Schedule (If Using Scheduler)</p>
                        <p className="text-muted-foreground">
                          Go to your strategy → Schedule
                        </p>
                        <ul className="list-disc list-inside ml-2 mt-1 text-muted-foreground">
                          <li>Add the special day (e.g., add "Sun" for Sunday Budget Day)</li>
                          <li>Update start/stop time to match special session hours</li>
                          <li>Remember to remove after the special session!</li>
                        </ul>
                      </div>
                    </div>

                    <div className="flex gap-3">
                      <Badge className="h-6 w-6 rounded-full flex items-center justify-center shrink-0">4</Badge>
                      <div>
                        <p className="font-medium">OR Simply Start Manually</p>
                        <p className="text-muted-foreground">
                          The easiest approach:
                        </p>
                        <ul className="list-disc list-inside ml-2 mt-1 text-muted-foreground">
                          <li>Login to OpenAlgo before the special session</li>
                          <li>Wait for master contracts to download</li>
                          <li>Click <Play className="h-3 w-3 inline" /> Start on your strategy</li>
                          <li>Click Stop when session ends</li>
                        </ul>
                      </div>
                    </div>
                  </div>
                </div>

                <Alert className="mt-3">
                  <AlertTriangle className="h-4 w-4" />
                  <AlertTitle>Important: Revert Changes After Special Session</AlertTitle>
                  <AlertDescription>
                    If you modified holiday calendar, market timings, or schedule settings for a
                    special session, remember to revert them back to normal after the session ends.
                    Otherwise, your strategy might run on actual holidays!
                  </AlertDescription>
                </Alert>
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="market-hours">
              <AccordionTrigger>
                <span className="flex items-center gap-2">
                  <Clock className="h-4 w-4" />
                  What happens on weekends and after market hours?
                </span>
              </AccordionTrigger>
              <AccordionContent className="text-muted-foreground space-y-3">
                <p>
                  OpenAlgo is aware of market timings and handles non-trading periods intelligently:
                </p>
                <div className="bg-muted p-3 rounded-lg mt-2 space-y-2 text-sm">
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-red-500 border-red-500">Weekends (Default)</Badge>
                    <span>Strategies skip Sat/Sun unless explicitly added to schedule_days</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-green-500 border-green-500">Weekend (Scheduled)</Badge>
                    <span>If Sat/Sun is in your schedule days, strategy CAN auto-start</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-yellow-500 border-yellow-500">Holidays</Badge>
                    <span>Scheduled strategies always skip market holidays</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-blue-500 border-blue-500">After Hours</Badge>
                    <span>Running strategies continue until scheduled stop time</span>
                  </div>
                </div>

                <div className="bg-primary/10 border border-primary/20 p-3 rounded-lg">
                  <p className="font-medium text-primary">Weekend Scheduling for Special Sessions</p>
                  <p className="text-sm mt-1">
                    For Budget Day, Muhurat Trading, or other special sessions on weekends:
                  </p>
                  <ol className="list-decimal list-inside space-y-1 ml-2 mt-2 text-sm">
                    <li>Edit your strategy schedule</li>
                    <li>Add "Sat" or "Sun" to the schedule days</li>
                    <li>The strategy will auto-start on that day at the scheduled time</li>
                    <li>Remember to remove the weekend day after the special session!</li>
                  </ol>
                </div>

                <p className="text-sm">
                  <strong>Note:</strong> If your strategy is already running when market closes,
                  it will continue running until the scheduled stop time or until you manually stop it.
                </p>
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="master-contract">
              <AccordionTrigger>
                <span className="flex items-center gap-2">
                  <Server className="h-4 w-4" />
                  Why does my strategy need master contracts?
                </span>
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
                <span className="flex items-center gap-2">
                  <Shield className="h-4 w-4" />
                  Are there any resource limits?
                </span>
              </AccordionTrigger>
              <AccordionContent className="text-muted-foreground space-y-2">
                <p>
                  Yes, to prevent buggy strategies from crashing OpenAlgo, the following
                  limits are enforced (Linux/Mac only):
                </p>
                <div className="grid grid-cols-2 gap-2 mt-2 text-sm">
                  <div className="bg-muted p-2 rounded">
                    <HardDrive className="h-4 w-4 inline mr-1" />
                    Memory: 512 MB max
                  </div>
                  <div className="bg-muted p-2 rounded">
                    <Clock className="h-4 w-4 inline mr-1" />
                    CPU Time: 1 hour max
                  </div>
                  <div className="bg-muted p-2 rounded">
                    <FileCode className="h-4 w-4 inline mr-1" />
                    Open Files: 256 max
                  </div>
                  <div className="bg-muted p-2 rounded">
                    <Server className="h-4 w-4 inline mr-1" />
                    Processes: 64 max
                  </div>
                </div>
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="restart">
              <AccordionTrigger>
                <span className="flex items-center gap-2">
                  <Play className="h-4 w-4" />
                  What happens if I restart OpenAlgo?
                </span>
              </AccordionTrigger>
              <AccordionContent className="text-muted-foreground space-y-3">
                <p>OpenAlgo handles restarts gracefully with automatic cleanup:</p>
                <ul className="list-disc list-inside space-y-1 ml-2">
                  <li>Strategy configurations are saved to disk and persist</li>
                  <li>Schedules are automatically re-created for all strategies</li>
                  <li>Stale "running" flags are cleaned up on startup</li>
                  <li>Strategies will auto-start at their scheduled times</li>
                </ul>

                <div className="bg-muted p-3 rounded-lg space-y-2">
                  <p className="font-medium">Automatic Status Cleanup</p>
                  <ul className="list-disc list-inside space-y-1 ml-2 text-sm">
                    <li>If OpenAlgo restarts while a strategy was running, the status is reset to "stopped"</li>
                    <li>This prevents stale "Running" indicators for dead processes</li>
                    <li>The strategy will resume at the next scheduled start time</li>
                  </ul>
                </div>

                <div className="bg-yellow-500/10 border border-yellow-500/20 p-3 rounded-lg">
                  <p className="font-medium text-yellow-600 flex items-center gap-2">
                    <AlertTriangle className="h-4 w-4" />
                    Manual Stop Persists
                  </p>
                  <p className="text-sm mt-1">
                    If you manually stopped a strategy before the restart, it will remain stopped.
                    The "manually stopped" flag persists and the strategy won't auto-start until you click Start.
                  </p>
                </div>
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="realtime-updates">
              <AccordionTrigger>
                <span className="flex items-center gap-2">
                  <Server className="h-4 w-4" />
                  How do real-time status updates work?
                </span>
              </AccordionTrigger>
              <AccordionContent className="text-muted-foreground space-y-3">
                <p>
                  The strategy dashboard uses <strong>Server-Sent Events (SSE)</strong> for real-time updates.
                  You don't need to refresh the page to see status changes.
                </p>

                <div className="bg-muted p-3 rounded-lg space-y-2">
                  <p className="font-medium">Automatic Updates</p>
                  <ul className="list-disc list-inside space-y-1 ml-2 text-sm">
                    <li>When scheduler starts a strategy → Status changes to "Running" automatically</li>
                    <li>When scheduler stops a strategy → Status changes to "Scheduled" automatically</li>
                    <li>When you click Start/Stop → UI updates immediately</li>
                    <li>No page refresh needed - updates happen in real-time</li>
                  </ul>
                </div>

                <div className="bg-primary/10 border border-primary/20 p-3 rounded-lg">
                  <p className="font-medium text-primary">Connection Status</p>
                  <p className="text-sm mt-1">
                    The browser maintains a persistent connection to receive updates.
                    If disconnected, it will automatically reconnect. You can also use the
                    <strong> Refresh</strong> button to manually refresh the data.
                  </p>
                </div>
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="best-practices">
              <AccordionTrigger>
                <span className="flex items-center gap-2">
                  <BookOpen className="h-4 w-4" />
                  Best practices for writing strategies
                </span>
              </AccordionTrigger>
              <AccordionContent className="text-muted-foreground space-y-2">
                <ul className="list-disc list-inside space-y-2 ml-2">
                  <li>
                    <strong>Use print() for logging</strong> - All output goes to log files
                  </li>
                  <li>
                    <strong>Handle exceptions</strong> - Wrap critical code in try/except
                  </li>
                  <li>
                    <strong>Add sleep intervals</strong> - Don't spam API calls, use time.sleep()
                  </li>
                  <li>
                    <strong>Use infinite loops carefully</strong> - Always have a way to exit
                  </li>
                  <li>
                    <strong>Test with small quantities</strong> - Start with 1 share/lot
                  </li>
                  <li>
                    <strong>Monitor logs initially</strong> - Watch the first few runs closely
                  </li>
                </ul>
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="add-libraries">
              <AccordionTrigger>
                <span className="flex items-center gap-2">
                  <Code className="h-4 w-4" />
                  How do I add new libraries like TA-Lib, pandas-ta, etc.?
                </span>
              </AccordionTrigger>
              <AccordionContent className="text-muted-foreground space-y-3">
                <p>
                  If your strategy requires additional Python libraries (e.g., <code>talib</code>,
                  <code>pandas-ta</code>, <code>numpy</code>), you need to install them in
                  OpenAlgo's Python virtual environment.
                </p>

                <div className="bg-primary/10 border border-primary/20 p-4 rounded-lg space-y-4">
                  <div>
                    <p className="font-semibold text-primary mb-2">Method 1: Using UV (Recommended)</p>
                    <p className="text-sm mb-2">
                      If you installed OpenAlgo using the UV method:
                    </p>
                    <ol className="list-decimal list-inside space-y-2 ml-2 text-sm">
                      <li>
                        Open <code className="bg-muted px-1 rounded">openalgo/pyproject.toml</code>
                      </li>
                      <li>
                        Add your library to the <code>dependencies</code> section:
                        <pre className="bg-muted p-2 rounded mt-1 text-xs overflow-x-auto">
{`[project]
dependencies = [
    "openalgo",
    "TA-Lib",        # Add your library here
    "pandas-ta",
]`}
                        </pre>
                      </li>
                      <li>
                        Run <code className="bg-muted px-1 rounded">uv sync</code> in the openalgo directory
                      </li>
                      <li>Restart OpenAlgo</li>
                    </ol>
                  </div>

                  <div className="border-t border-primary/20 pt-4">
                    <p className="font-semibold text-primary mb-2">Method 2: Using Regular Python venv</p>
                    <p className="text-sm mb-2">
                      If you installed OpenAlgo using a regular Python virtual environment:
                    </p>
                    <ol className="list-decimal list-inside space-y-2 ml-2 text-sm">
                      <li>
                        Open <code className="bg-muted px-1 rounded">openalgo/requirements.txt</code>
                      </li>
                      <li>
                        Add your library:
                        <pre className="bg-muted p-2 rounded mt-1 text-xs overflow-x-auto">
{`openalgo
TA-Lib
pandas-ta`}
                        </pre>
                      </li>
                      <li>
                        Activate your virtual environment and install:
                        <pre className="bg-muted p-2 rounded mt-1 text-xs overflow-x-auto">
{`# Activate venv first
pip install -r requirements.txt`}
                        </pre>
                      </li>
                      <li>Restart OpenAlgo</li>
                    </ol>
                  </div>
                </div>

                <Alert className="mt-3">
                  <AlertTriangle className="h-4 w-4" />
                  <AlertTitle>TA-Lib Installation Note</AlertTitle>
                  <AlertDescription>
                    TA-Lib requires the underlying C library to be installed first.
                    On Mac: <code>brew install ta-lib</code><br />
                    On Ubuntu: <code>sudo apt-get install libta-lib-dev</code><br />
                    On Windows: Download from{' '}
                    <a href="https://www.lfd.uci.edu/~gohlke/pythonlibs/#ta-lib" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
                      unofficial binaries
                    </a>
                  </AlertDescription>
                </Alert>
              </AccordionContent>
            </AccordionItem>
          </Accordion>
        </CardContent>
      </Card>

      {/* OpenAlgo SDK Reference */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Code className="h-5 w-5" />
            OpenAlgo SDK Quick Reference
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 text-sm">
            <div className="bg-muted p-3 rounded-lg">
              <p className="font-medium mb-1">Initialize Client</p>
              <code className="text-xs">client = api(api_key="YOUR_KEY", host="http://127.0.0.1:5000")</code>
            </div>
            <div className="bg-muted p-3 rounded-lg">
              <p className="font-medium mb-1">Place Order</p>
              <code className="text-xs">client.placeorder(symbol, exchange, action, quantity, price_type, product_type)</code>
            </div>
            <div className="bg-muted p-3 rounded-lg">
              <p className="font-medium mb-1">Get Quotes</p>
              <code className="text-xs">client.quotes(symbol="RELIANCE", exchange="NSE")</code>
            </div>
            <div className="bg-muted p-3 rounded-lg">
              <p className="font-medium mb-1">Get Positions</p>
              <code className="text-xs">client.positionbook()</code>
            </div>
            <div className="bg-muted p-3 rounded-lg">
              <p className="font-medium mb-1">Get Holdings</p>
              <code className="text-xs">client.holdings()</code>
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
    </div>
  )
}
