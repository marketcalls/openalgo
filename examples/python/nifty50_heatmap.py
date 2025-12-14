"""
OpenAlgo Real-time Nifty 50 Heatmap - CLI Mode
Real-time WebSocket-based heatmap with color coding for Nifty 50 stocks

Features:
- Real-time LTP updates via WebSocket
- Color-coded price changes (green for gainers, red for losers)
- Detailed statistics: % change, volume, day range
- Auto-refreshing CLI display
- Sorted by % change (top gainers/losers)

Usage:
    python nifty50_heatmap.py

Requirements:
    pip install openalgo rich
"""

from openalgo import api
import time
import os
import sys
from datetime import datetime
from threading import Lock
from collections import OrderedDict

# Try to import rich for better terminal UI
try:
    from rich.console import Console
    from rich.table import Table
    from rich.live import Live
    from rich.panel import Panel
    from rich.layout import Layout
    from rich.text import Text
    from rich import box
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    print("For best experience, install rich: pip install rich")
    print("Falling back to basic terminal output...\n")

# ========== CONFIGURATION ==========
API_KEY = "your_api_key_here"  # Replace with your OpenAlgo API key
HOST = "http://127.0.0.1:5000"
WS_URL = "ws://127.0.0.1:8765"
REFRESH_RATE = 0.5  # seconds between display updates

# Nifty 50 Symbols (51 due to TATAMOTORS demerger)
NIFTY50_SYMBOLS = [
    "KOTAKBANK", "ETERNAL", "JIOFIN", "TATASTEEL", "SHRIRAMFIN",
    "JSWSTEEL", "GRASIM", "ADANIENT", "CIPLA", "MARUTI",
    "DRREDDY", "NESTLEIND", "EICHERMOT", "ULTRACEMCO", "TATACONSUM",
    "HDFCBANK", "COALINDIA", "WIPRO", "BAJFINANCE", "BAJAJ-AUTO",
    "ADANIPORTS", "SUNPHARMA", "HINDALCO", "MAXHEALTH", "APOLLOHOSP",
    "ONGC", "BEL", "HINDUNILVR", "NTPC", "LT",
    "TECHM", "SBIN", "INDIGO", "INFY", "POWERGRID",
    "TMPV", "SBILIFE", "AXISBANK", "BAJAJFINSV", "M&M",
    "ICICIBANK", "RELIANCE", "HCLTECH", "HDFCLIFE", "ITC",
    "TITAN", "TCS", "TRENT", "BHARTIARTL", "ASIANPAINT"
]

# Add NIFTY index for reference
NIFTY_INDEX = {"exchange": "NSE_INDEX", "symbol": "NIFTY"}

class Nifty50Heatmap:
    def __init__(self, api_key, host, ws_url):
        self.client = api(
            api_key=api_key,
            host=host,
            ws_url=ws_url,
            verbose=False  # Silent mode for clean output
        )
        self.data_lock = Lock()
        self.stock_data = {}
        self.nifty_data = {}
        self.last_update = None
        self.connected = False
        self.quotes_fetched = False

        # Initialize stock data structure
        for symbol in NIFTY50_SYMBOLS:
            self.stock_data[symbol] = {
                "ltp": 0.0,
                "open": 0.0,
                "high": 0.0,
                "low": 0.0,
                "prev_close": 0.0,
                "change": 0.0,
                "change_pct": 0.0,
                "volume": 0,
                "updated": False
            }

    def fetch_initial_quotes(self):
        """Fetch initial day's data using multiquotes API"""
        print("Fetching initial market data...")

        # Build symbols list for multiquotes
        symbols_list = [{"symbol": sym, "exchange": "NSE"} for sym in NIFTY50_SYMBOLS]

        try:
            # Fetch in batches of 20 to avoid rate limits
            batch_size = 20
            for i in range(0, len(symbols_list), batch_size):
                batch = symbols_list[i:i+batch_size]
                response = self.client.multiquotes(symbols=batch)

                if response.get("status") == "success":
                    for result in response.get("results", []):
                        symbol = result.get("symbol")
                        data = result.get("data", {})
                        if symbol in self.stock_data:
                            with self.data_lock:
                                self.stock_data[symbol].update({
                                    "open": data.get("open", 0.0),
                                    "high": data.get("high", 0.0),
                                    "low": data.get("low", 0.0),
                                    "prev_close": data.get("prev_close", 0.0),
                                    "volume": data.get("volume", 0),
                                    "ltp": data.get("ltp", 0.0)
                                })
                                # Calculate change
                                ltp = data.get("ltp", 0.0)
                                prev_close = data.get("prev_close", 0.0)
                                if prev_close > 0:
                                    self.stock_data[symbol]["change"] = ltp - prev_close
                                    self.stock_data[symbol]["change_pct"] = ((ltp - prev_close) / prev_close) * 100

                time.sleep(0.2)  # Small delay between batches

            # Fetch NIFTY index data
            nifty_response = self.client.quotes(symbol="NIFTY", exchange="NSE_INDEX")
            if nifty_response.get("status") == "success":
                data = nifty_response.get("data", {})
                self.nifty_data = {
                    "ltp": data.get("ltp", 0.0),
                    "open": data.get("open", 0.0),
                    "high": data.get("high", 0.0),
                    "low": data.get("low", 0.0),
                    "prev_close": data.get("prev_close", 0.0),
                    "volume": data.get("volume", 0)
                }
                if self.nifty_data["prev_close"] > 0:
                    self.nifty_data["change"] = self.nifty_data["ltp"] - self.nifty_data["prev_close"]
                    self.nifty_data["change_pct"] = (self.nifty_data["change"] / self.nifty_data["prev_close"]) * 100

            self.quotes_fetched = True
            print(f"Loaded data for {len(NIFTY50_SYMBOLS)} stocks")

        except Exception as e:
            print(f"Error fetching initial quotes: {e}")

    def on_quote_update(self, data):
        """Callback for WebSocket quote updates"""
        symbol = data.get("symbol")
        quote_data = data.get("data", {})

        with self.data_lock:
            if symbol == "NIFTY":
                self.nifty_data.update({
                    "ltp": quote_data.get("ltp", self.nifty_data.get("ltp", 0.0)),
                    "open": quote_data.get("open", self.nifty_data.get("open", 0.0)),
                    "high": quote_data.get("high", self.nifty_data.get("high", 0.0)),
                    "low": quote_data.get("low", self.nifty_data.get("low", 0.0)),
                    "volume": quote_data.get("volume", self.nifty_data.get("volume", 0))
                })
                if self.nifty_data.get("prev_close", 0) > 0:
                    self.nifty_data["change"] = self.nifty_data["ltp"] - self.nifty_data["prev_close"]
                    self.nifty_data["change_pct"] = (self.nifty_data["change"] / self.nifty_data["prev_close"]) * 100

            elif symbol in self.stock_data:
                ltp = quote_data.get("ltp", self.stock_data[symbol]["ltp"])
                self.stock_data[symbol].update({
                    "ltp": ltp,
                    "high": quote_data.get("high", self.stock_data[symbol]["high"]),
                    "low": quote_data.get("low", self.stock_data[symbol]["low"]),
                    "volume": quote_data.get("volume", self.stock_data[symbol]["volume"]),
                    "updated": True
                })

                # Recalculate change
                prev_close = self.stock_data[symbol]["prev_close"]
                if prev_close > 0:
                    self.stock_data[symbol]["change"] = ltp - prev_close
                    self.stock_data[symbol]["change_pct"] = ((ltp - prev_close) / prev_close) * 100

            self.last_update = datetime.now()

    def connect_websocket(self):
        """Connect to WebSocket and subscribe to all instruments"""
        print("Connecting to WebSocket...")

        try:
            self.client.connect()
            self.connected = True

            # Build instruments list
            instruments = [NIFTY_INDEX]
            instruments.extend([{"exchange": "NSE", "symbol": sym} for sym in NIFTY50_SYMBOLS])

            # Subscribe to quote stream
            print(f"Subscribing to {len(instruments)} instruments...")
            self.client.subscribe_quote(instruments, on_data_received=self.on_quote_update)

            print("WebSocket connected and subscribed!")
            return True

        except Exception as e:
            print(f"WebSocket connection error: {e}")
            return False

    def disconnect(self):
        """Disconnect WebSocket"""
        if self.connected:
            instruments = [NIFTY_INDEX]
            instruments.extend([{"exchange": "NSE", "symbol": sym} for sym in NIFTY50_SYMBOLS])
            try:
                self.client.unsubscribe_quote(instruments)
                self.client.disconnect()
            except:
                pass
            self.connected = False

    def get_color_for_change(self, change_pct):
        """Get color based on percentage change"""
        if change_pct >= 3.0:
            return "bright_green"
        elif change_pct >= 1.5:
            return "green"
        elif change_pct >= 0.5:
            return "dark_green"
        elif change_pct > 0:
            return "pale_green1"
        elif change_pct == 0:
            return "white"
        elif change_pct > -0.5:
            return "light_coral"
        elif change_pct > -1.5:
            return "red"
        elif change_pct > -3.0:
            return "red3"
        else:
            return "bright_red"

    def get_sorted_stocks(self):
        """Get stocks sorted by percentage change"""
        with self.data_lock:
            sorted_stocks = sorted(
                self.stock_data.items(),
                key=lambda x: x[1]["change_pct"],
                reverse=True
            )
        return sorted_stocks

    def calculate_market_stats(self):
        """Calculate overall market statistics"""
        with self.data_lock:
            gainers = sum(1 for s in self.stock_data.values() if s["change_pct"] > 0)
            losers = sum(1 for s in self.stock_data.values() if s["change_pct"] < 0)
            unchanged = len(self.stock_data) - gainers - losers

            total_change = sum(s["change_pct"] for s in self.stock_data.values())
            avg_change = total_change / len(self.stock_data) if self.stock_data else 0

            changes = [s["change_pct"] for s in self.stock_data.values()]
            max_gain = max(changes) if changes else 0
            max_loss = min(changes) if changes else 0

        return {
            "gainers": gainers,
            "losers": losers,
            "unchanged": unchanged,
            "avg_change": avg_change,
            "max_gain": max_gain,
            "max_loss": max_loss
        }

    def render_rich_display(self):
        """Render display using Rich library"""
        console = Console()

        def generate_table():
            # Main layout
            layout = Layout()

            # Get sorted stocks
            sorted_stocks = self.get_sorted_stocks()
            stats = self.calculate_market_stats()

            # Header with NIFTY info
            nifty_change = self.nifty_data.get("change", 0)
            nifty_change_pct = self.nifty_data.get("change_pct", 0)
            nifty_color = "green" if nifty_change >= 0 else "red"
            nifty_arrow = "▲" if nifty_change >= 0 else "▼"

            header_text = Text()
            header_text.append("NIFTY 50 REAL-TIME HEATMAP", style="bold white")
            header_text.append(" │ ", style="dim")
            header_text.append(f"NIFTY: {self.nifty_data.get('ltp', 0):,.2f} ", style="bold")
            header_text.append(f"{nifty_arrow} {nifty_change:+.2f} ({nifty_change_pct:+.2f}%)", style=f"bold {nifty_color}")
            header_text.append(" │ ", style="dim")
            header_text.append(f"Gainers: {stats['gainers']}", style="green")
            header_text.append(" │ ", style="dim")
            header_text.append(f"Losers: {stats['losers']}", style="red")
            header_text.append(" │ ", style="dim")
            header_text.append(f"Unchanged: {stats['unchanged']}", style="dim")

            # Create main table
            table = Table(
                title=header_text,
                box=box.ROUNDED,
                show_header=True,
                header_style="bold cyan",
                border_style="blue",
                padding=(0, 1)
            )

            # Add columns
            table.add_column("#", style="dim", width=3, justify="right")
            table.add_column("Symbol", style="bold", width=12)
            table.add_column("LTP", justify="right", width=10)
            table.add_column("Change", justify="right", width=10)
            table.add_column("% Chg", justify="right", width=8)
            table.add_column("Open", justify="right", width=10)
            table.add_column("High", justify="right", width=10)
            table.add_column("Low", justify="right", width=10)
            table.add_column("Volume", justify="right", width=12)
            table.add_column("Day Range", justify="center", width=15)

            # Add rows
            for idx, (symbol, data) in enumerate(sorted_stocks, 1):
                change_pct = data["change_pct"]
                change = data["change"]
                color = self.get_color_for_change(change_pct)

                # Day range visualization
                day_range = self._get_day_range_bar(data)

                # Format volume
                volume = data["volume"]
                if volume >= 10000000:
                    vol_str = f"{volume/10000000:.2f}Cr"
                elif volume >= 100000:
                    vol_str = f"{volume/100000:.2f}L"
                elif volume >= 1000:
                    vol_str = f"{volume/1000:.1f}K"
                else:
                    vol_str = str(volume)

                # Arrow indicator
                arrow = "▲" if change >= 0 else "▼" if change < 0 else "─"

                table.add_row(
                    str(idx),
                    Text(symbol, style=f"bold {color}"),
                    f"₹{data['ltp']:,.2f}",
                    Text(f"{arrow} {abs(change):.2f}", style=color),
                    Text(f"{change_pct:+.2f}%", style=f"bold {color}"),
                    f"₹{data['open']:,.2f}" if data['open'] > 0 else "-",
                    f"₹{data['high']:,.2f}" if data['high'] > 0 else "-",
                    f"₹{data['low']:,.2f}" if data['low'] > 0 else "-",
                    vol_str,
                    day_range
                )

            # Footer with stats
            update_time = self.last_update.strftime("%H:%M:%S") if self.last_update else "Waiting..."
            footer_text = Text()
            footer_text.append(f"\n  Last Update: {update_time}", style="dim")
            footer_text.append(f" │ Avg Change: {stats['avg_change']:+.2f}%", style="cyan")
            footer_text.append(f" │ Max Gain: {stats['max_gain']:+.2f}%", style="bright_green")
            footer_text.append(f" │ Max Loss: {stats['max_loss']:+.2f}%", style="bright_red")
            footer_text.append(f" │ Press Ctrl+C to exit", style="dim italic")

            return Panel(table, subtitle=footer_text, border_style="blue")

        # Live display
        with Live(generate_table(), console=console, refresh_per_second=2, screen=True) as live:
            try:
                while True:
                    time.sleep(REFRESH_RATE)
                    live.update(generate_table())
            except KeyboardInterrupt:
                pass

    def _get_day_range_bar(self, data):
        """Generate a visual day range bar"""
        low = data["low"]
        high = data["high"]
        ltp = data["ltp"]

        if high <= low or high == 0:
            return "──────────"

        # Calculate position (0-10)
        position = int(((ltp - low) / (high - low)) * 10) if (high - low) > 0 else 5
        position = max(0, min(10, position))

        bar = "─" * position + "●" + "─" * (10 - position)

        change_pct = data["change_pct"]
        color = self.get_color_for_change(change_pct)

        return Text(bar, style=color)

    def render_basic_display(self):
        """Fallback display without Rich library"""
        try:
            while True:
                # Clear screen
                os.system('cls' if os.name == 'nt' else 'clear')

                sorted_stocks = self.get_sorted_stocks()
                stats = self.calculate_market_stats()

                # Header
                nifty_change = self.nifty_data.get("change_pct", 0)
                print("=" * 100)
                print(f"NIFTY 50 REAL-TIME HEATMAP | NIFTY: {self.nifty_data.get('ltp', 0):,.2f} ({nifty_change:+.2f}%)")
                print(f"Gainers: {stats['gainers']} | Losers: {stats['losers']} | Unchanged: {stats['unchanged']}")
                print("=" * 100)

                # Table header
                print(f"{'#':>3} {'Symbol':<12} {'LTP':>10} {'Change':>10} {'%Chg':>8} {'Open':>10} {'High':>10} {'Low':>10} {'Volume':>12}")
                print("-" * 100)

                # Rows
                for idx, (symbol, data) in enumerate(sorted_stocks, 1):
                    change_pct = data["change_pct"]
                    change = data["change"]

                    # ANSI color codes
                    if change_pct >= 1.0:
                        color = "\033[92m"  # Bright green
                    elif change_pct > 0:
                        color = "\033[32m"  # Green
                    elif change_pct < -1.0:
                        color = "\033[91m"  # Bright red
                    elif change_pct < 0:
                        color = "\033[31m"  # Red
                    else:
                        color = "\033[0m"   # Reset

                    reset = "\033[0m"

                    # Format volume
                    volume = data["volume"]
                    if volume >= 10000000:
                        vol_str = f"{volume/10000000:.2f}Cr"
                    elif volume >= 100000:
                        vol_str = f"{volume/100000:.2f}L"
                    else:
                        vol_str = str(volume)

                    print(f"{idx:>3} {color}{symbol:<12}{reset} {data['ltp']:>10,.2f} {color}{change:>+10.2f}{reset} {color}{change_pct:>+8.2f}%{reset} {data['open']:>10,.2f} {data['high']:>10,.2f} {data['low']:>10,.2f} {vol_str:>12}")

                print("-" * 100)
                update_time = self.last_update.strftime("%H:%M:%S") if self.last_update else "Waiting..."
                print(f"Last Update: {update_time} | Avg Change: {stats['avg_change']:+.2f}% | Press Ctrl+C to exit")

                time.sleep(REFRESH_RATE)

        except KeyboardInterrupt:
            pass

    def run(self):
        """Main run method"""
        print("=" * 60)
        print("  NIFTY 50 REAL-TIME HEATMAP")
        print("  OpenAlgo WebSocket Streaming")
        print("=" * 60)

        # Fetch initial quotes
        self.fetch_initial_quotes()

        # Connect WebSocket
        if not self.connect_websocket():
            print("Failed to connect. Exiting.")
            return

        print("\nStarting heatmap display...")
        time.sleep(1)

        try:
            if RICH_AVAILABLE:
                self.render_rich_display()
            else:
                self.render_basic_display()
        finally:
            print("\nDisconnecting...")
            self.disconnect()
            print("Goodbye!")


def main():
    """Main entry point"""
    # Check for API key in environment or use default
    api_key = os.environ.get("OPENALGO_API_KEY", API_KEY)
    host = os.environ.get("OPENALGO_HOST", HOST)
    ws_url = os.environ.get("OPENALGO_WS_URL", WS_URL)

    if api_key == "your_api_key_here":
        print("=" * 60)
        print("  CONFIGURATION REQUIRED")
        print("=" * 60)
        print("\nPlease set your OpenAlgo API key:")
        print("  1. Edit this file and set API_KEY variable, or")
        print("  2. Set environment variable: export OPENALGO_API_KEY=your_key")
        print("\nAlso ensure OpenAlgo server is running at:")
        print(f"  REST API: {host}")
        print(f"  WebSocket: {ws_url}")
        print()
        return

    heatmap = Nifty50Heatmap(api_key, host, ws_url)
    heatmap.run()


if __name__ == "__main__":
    main()
