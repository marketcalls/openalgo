import {
  AlertTriangle,
  ArrowLeft,
  BookOpen,
  Calendar,
  Clock,
  Code,
  Copy,
  FileCode,
  HardDrive,
  Play,
  ScrollText,
  Server,
  Shield,
  Terminal,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
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
  toast.success('Copied to clipboard')
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
                <p className="font-medium">Upload and run</p>
                <p className="text-sm text-muted-foreground">
                  Upload your strategy file on the <Link to="/python" className="text-primary hover:underline">Python Strategies</Link> page
                  and click Start
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
              <AccordionContent className="text-muted-foreground space-y-2">
                <p>You can schedule strategies to automatically start and stop at specific times:</p>
                <ul className="list-disc list-inside space-y-1 ml-2">
                  <li><strong>Start Time:</strong> When the strategy should begin (e.g., 9:15 AM)</li>
                  <li><strong>Stop Time:</strong> When to stop (e.g., 3:30 PM) - optional</li>
                  <li><strong>Days:</strong> Which days to run (Mon-Fri typical)</li>
                </ul>
                <Alert className="mt-2">
                  <AlertTriangle className="h-4 w-4" />
                  <AlertTitle>Holiday Protection</AlertTitle>
                  <AlertDescription>
                    Scheduled strategies will NOT start on market holidays or weekends,
                    even if scheduled. This prevents unnecessary resource usage.
                  </AlertDescription>
                </Alert>
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
              <AccordionContent className="text-muted-foreground space-y-2">
                <p>
                  OpenAlgo is aware of market timings and handles non-trading periods:
                </p>
                <div className="bg-muted p-3 rounded-lg mt-2 space-y-2 text-sm">
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-red-500 border-red-500">Weekends</Badge>
                    <span>Scheduled strategies will NOT auto-start on Sat/Sun</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-yellow-500 border-yellow-500">Holidays</Badge>
                    <span>Scheduled strategies skip market holidays automatically</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-blue-500 border-blue-500">After Hours</Badge>
                    <span>Running strategies continue until stop time or manual stop</span>
                  </div>
                </div>
                <p className="text-sm mt-2">
                  <strong>Note:</strong> If your strategy is already running when market closes,
                  it will continue running. Use the scheduled stop time or manually stop it.
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
              <AccordionContent className="text-muted-foreground space-y-2">
                <p>OpenAlgo handles restarts gracefully:</p>
                <ul className="list-disc list-inside space-y-1 ml-2">
                  <li>Strategy configurations are saved to disk</li>
                  <li>Running strategies are detected and restored if still alive</li>
                  <li>Schedules are automatically re-created</li>
                  <li>If a strategy crashed, it will show an error state</li>
                </ul>
                <p className="text-sm">
                  Note: Strategies that were running will attempt to restart automatically
                  after master contracts are downloaded.
                </p>
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
