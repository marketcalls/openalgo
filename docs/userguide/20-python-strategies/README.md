# 20 - Python Strategies

## Introduction

Python is one of the most powerful ways to build trading strategies with OpenAlgo. Using the official OpenAlgo Python library, you can create sophisticated algorithms, backtest strategies, and execute trades programmatically.

## Getting Started

### Installing the Library

```bash
pip install openalgo
```

### Basic Setup

```python
from openalgo import api

# Initialize client
client = api(
    api_key="YOUR_API_KEY",
    host="http://127.0.0.1:5000"
)

# Test connection
print("Connected to OpenAlgo!")
```

## Core Functions

### Placing Orders

```python
# Market order
response = client.place_order(
    symbol="SBIN",
    exchange="NSE",
    action="BUY",
    quantity=100,
    price_type="MARKET",
    product="MIS",
    strategy="PythonStrategy"
)

print(f"Order ID: {response['orderid']}")
```

### Order Types

```python
# Limit order
client.place_order(
    symbol="SBIN",
    exchange="NSE",
    action="BUY",
    quantity=100,
    price_type="LIMIT",
    price=620.00,
    product="MIS",
    strategy="LimitStrategy"
)

# Stop-loss order
client.place_order(
    symbol="SBIN",
    exchange="NSE",
    action="SELL",
    quantity=100,
    price_type="SL",
    price=614.00,
    trigger_price=615.00,
    product="MIS",
    strategy="SLStrategy"
)

# Stop-loss market order
client.place_order(
    symbol="SBIN",
    exchange="NSE",
    action="SELL",
    quantity=100,
    price_type="SL-M",
    trigger_price=615.00,
    product="MIS",
    strategy="SLMStrategy"
)
```

### Smart Orders

```python
# Position-aware order
response = client.place_smart_order(
    symbol="SBIN",
    exchange="NSE",
    action="BUY",
    quantity=100,
    position_size=100,  # Target position
    price_type="MARKET",
    product="MIS",
    strategy="SmartStrategy"
)
```

### Basket Orders

```python
# Multiple orders at once
basket = [
    {
        "symbol": "SBIN",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": 100,
        "price_type": "MARKET",
        "product": "MIS"
    },
    {
        "symbol": "INFY",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": 50,
        "price_type": "MARKET",
        "product": "MIS"
    },
    {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": 25,
        "price_type": "MARKET",
        "product": "MIS"
    }
]

response = client.place_basket_order(
    orders=basket,
    strategy="BasketStrategy"
)

print(f"Successful: {response['successful']}")
print(f"Failed: {response['failed']}")
```

### Getting Positions

```python
# Get all positions
positions = client.get_positions()

for pos in positions['data']:
    print(f"{pos['symbol']}: {pos['quantity']} @ {pos['average_price']}")
```

### Getting Holdings

```python
# Get all holdings
holdings = client.get_holdings()

for holding in holdings['data']:
    print(f"{holding['symbol']}: {holding['quantity']} shares")
```

### Getting Order Book

```python
# Get all orders
orders = client.get_orders()

for order in orders['data']:
    print(f"{order['orderid']}: {order['symbol']} {order['action']} {order['status']}")
```

### Closing Positions

```python
# Close specific position
client.close_position(
    symbol="SBIN",
    exchange="NSE",
    product="MIS",
    strategy="CloseStrategy"
)

# Close all positions
client.close_all_positions(strategy="SquareOff")
```

## Strategy Examples

### 1. Simple Moving Average Crossover

```python
import pandas as pd
import numpy as np
from openalgo import api
import time

client = api(api_key="YOUR_KEY", host="http://127.0.0.1:5000")

def get_historical_data(symbol, exchange, interval, days=30):
    """Fetch historical data for analysis"""
    # You would typically use a data provider here
    # This is a placeholder for demonstration
    pass

def calculate_signals(df, fast_period=9, slow_period=21):
    """Calculate moving average crossover signals"""
    df['fast_ma'] = df['close'].rolling(window=fast_period).mean()
    df['slow_ma'] = df['close'].rolling(window=slow_period).mean()

    # Generate signals
    df['signal'] = 0
    df.loc[df['fast_ma'] > df['slow_ma'], 'signal'] = 1
    df.loc[df['fast_ma'] < df['slow_ma'], 'signal'] = -1

    return df

def run_strategy(symbol, exchange, quantity):
    """Main strategy loop"""
    current_position = 0

    while True:
        try:
            # Get latest data
            df = get_historical_data(symbol, exchange, '5min')
            df = calculate_signals(df)

            # Get latest signal
            latest_signal = df['signal'].iloc[-1]

            # Execute trades based on signal
            if latest_signal == 1 and current_position <= 0:
                # Buy signal
                if current_position < 0:
                    # Close short first
                    client.place_order(
                        symbol=symbol,
                        exchange=exchange,
                        action="BUY",
                        quantity=abs(current_position),
                        price_type="MARKET",
                        product="MIS",
                        strategy="MA_Crossover"
                    )

                # Go long
                client.place_order(
                    symbol=symbol,
                    exchange=exchange,
                    action="BUY",
                    quantity=quantity,
                    price_type="MARKET",
                    product="MIS",
                    strategy="MA_Crossover"
                )
                current_position = quantity
                print(f"Bought {quantity} {symbol}")

            elif latest_signal == -1 and current_position >= 0:
                # Sell signal
                if current_position > 0:
                    # Close long first
                    client.place_order(
                        symbol=symbol,
                        exchange=exchange,
                        action="SELL",
                        quantity=current_position,
                        price_type="MARKET",
                        product="MIS",
                        strategy="MA_Crossover"
                    )
                    current_position = 0
                    print(f"Sold {quantity} {symbol}")

            # Wait for next candle
            time.sleep(300)  # 5 minutes

        except Exception as e:
            print(f"Error: {e}")
            time.sleep(60)

# Run the strategy
if __name__ == "__main__":
    run_strategy("SBIN", "NSE", 100)
```

### 2. RSI Mean Reversion

```python
from openalgo import api
import pandas as pd
import numpy as np
import time

client = api(api_key="YOUR_KEY", host="http://127.0.0.1:5000")

def calculate_rsi(prices, period=14):
    """Calculate RSI indicator"""
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def rsi_strategy(symbol, exchange, quantity):
    """RSI mean reversion strategy"""
    position = 0

    while True:
        try:
            # Get data and calculate RSI
            df = get_historical_data(symbol, exchange, '15min')
            df['rsi'] = calculate_rsi(df['close'])

            current_rsi = df['rsi'].iloc[-1]

            # Oversold - Buy signal
            if current_rsi < 30 and position == 0:
                client.place_order(
                    symbol=symbol,
                    exchange=exchange,
                    action="BUY",
                    quantity=quantity,
                    price_type="MARKET",
                    product="MIS",
                    strategy="RSI_Strategy"
                )
                position = quantity
                print(f"RSI {current_rsi:.2f}: Bought {symbol}")

            # Overbought - Sell signal
            elif current_rsi > 70 and position > 0:
                client.place_order(
                    symbol=symbol,
                    exchange=exchange,
                    action="SELL",
                    quantity=position,
                    price_type="MARKET",
                    product="MIS",
                    strategy="RSI_Strategy"
                )
                position = 0
                print(f"RSI {current_rsi:.2f}: Sold {symbol}")

            time.sleep(900)  # 15 minutes

        except Exception as e:
            print(f"Error: {e}")
            time.sleep(60)
```

### 3. Multi-Symbol Scanner

```python
from openalgo import api
import pandas as pd
import time
from concurrent.futures import ThreadPoolExecutor

client = api(api_key="YOUR_KEY", host="http://127.0.0.1:5000")

# Watchlist
symbols = ["SBIN", "HDFC", "ICICIBANK", "INFY", "TCS", "RELIANCE"]

def analyze_symbol(symbol):
    """Analyze single symbol for trading signal"""
    try:
        df = get_historical_data(symbol, "NSE", "5min")

        # Calculate indicators
        df['sma20'] = df['close'].rolling(20).mean()
        df['sma50'] = df['close'].rolling(50).mean()
        df['volume_avg'] = df['volume'].rolling(20).mean()

        # Check conditions
        latest = df.iloc[-1]

        # Bullish conditions
        bullish = (
            latest['close'] > latest['sma20'] and
            latest['sma20'] > latest['sma50'] and
            latest['volume'] > latest['volume_avg'] * 1.5
        )

        return {
            'symbol': symbol,
            'bullish': bullish,
            'close': latest['close']
        }

    except Exception as e:
        return {'symbol': symbol, 'error': str(e)}

def scan_and_trade(max_positions=3, quantity=100):
    """Scan all symbols and trade top signals"""

    # Get current positions
    positions = client.get_positions()
    current_symbols = [p['symbol'] for p in positions.get('data', [])]
    open_positions = len(current_symbols)

    # Analyze symbols in parallel
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(analyze_symbol, symbols))

    # Filter bullish signals
    bullish_signals = [r for r in results if r.get('bullish') and r['symbol'] not in current_symbols]

    # Trade up to max positions
    available_slots = max_positions - open_positions

    for signal in bullish_signals[:available_slots]:
        client.place_order(
            symbol=signal['symbol'],
            exchange="NSE",
            action="BUY",
            quantity=quantity,
            price_type="MARKET",
            product="MIS",
            strategy="Scanner"
        )
        print(f"Bought {signal['symbol']} at {signal['close']}")

# Run scanner every 5 minutes
while True:
    scan_and_trade()
    time.sleep(300)
```

### 4. Options Strategy

```python
from openalgo import api
import datetime

client = api(api_key="YOUR_KEY", host="http://127.0.0.1:5000")

def get_option_symbol(underlying, expiry, strike, option_type):
    """Construct option symbol"""
    # Format: NIFTY25JAN21500CE
    expiry_str = expiry.strftime("%y%b").upper()
    return f"{underlying}{expiry_str}{strike}{option_type}"

def bull_call_spread(underlying, expiry, lower_strike, upper_strike, lot_size):
    """Execute bull call spread"""

    lower_call = get_option_symbol(underlying, expiry, lower_strike, "CE")
    upper_call = get_option_symbol(underlying, expiry, upper_strike, "CE")

    # Basket order for simultaneous execution
    basket = [
        {
            "symbol": lower_call,
            "exchange": "NFO",
            "action": "BUY",
            "quantity": lot_size,
            "price_type": "MARKET",
            "product": "NRML"
        },
        {
            "symbol": upper_call,
            "exchange": "NFO",
            "action": "SELL",
            "quantity": lot_size,
            "price_type": "MARKET",
            "product": "NRML"
        }
    ]

    response = client.place_basket_order(
        orders=basket,
        strategy="BullCallSpread"
    )

    return response

def iron_condor(underlying, expiry, call_sell, call_buy, put_sell, put_buy, lot_size):
    """Execute iron condor strategy"""

    basket = [
        {
            "symbol": get_option_symbol(underlying, expiry, call_sell, "CE"),
            "exchange": "NFO",
            "action": "SELL",
            "quantity": lot_size,
            "price_type": "MARKET",
            "product": "NRML"
        },
        {
            "symbol": get_option_symbol(underlying, expiry, call_buy, "CE"),
            "exchange": "NFO",
            "action": "BUY",
            "quantity": lot_size,
            "price_type": "MARKET",
            "product": "NRML"
        },
        {
            "symbol": get_option_symbol(underlying, expiry, put_sell, "PE"),
            "exchange": "NFO",
            "action": "SELL",
            "quantity": lot_size,
            "price_type": "MARKET",
            "product": "NRML"
        },
        {
            "symbol": get_option_symbol(underlying, expiry, put_buy, "PE"),
            "exchange": "NFO",
            "action": "BUY",
            "quantity": lot_size,
            "price_type": "MARKET",
            "product": "NRML"
        }
    ]

    response = client.place_basket_order(
        orders=basket,
        strategy="IronCondor"
    )

    return response

# Execute strategies
expiry = datetime.date(2025, 1, 30)  # Next expiry

# Bull call spread
bull_call_spread("NIFTY", expiry, 21500, 21600, 50)

# Iron condor
iron_condor("NIFTY", expiry, 22000, 22100, 21000, 20900, 50)
```

## Error Handling

### Robust Order Placement

```python
import time
from openalgo import api

client = api(api_key="YOUR_KEY", host="http://127.0.0.1:5000")

def place_order_with_retry(order_params, max_retries=3):
    """Place order with automatic retry on failure"""

    for attempt in range(max_retries):
        try:
            response = client.place_order(**order_params)

            if response.get('status') == 'success':
                return response
            else:
                print(f"Order failed: {response.get('message')}")

        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {e}")

        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)  # Exponential backoff

    return {'status': 'error', 'message': 'Max retries exceeded'}

# Usage
order = {
    'symbol': 'SBIN',
    'exchange': 'NSE',
    'action': 'BUY',
    'quantity': 100,
    'price_type': 'MARKET',
    'product': 'MIS',
    'strategy': 'RetryStrategy'
}

result = place_order_with_retry(order)
```

## Scheduling Strategies

### Using Schedule Library

```python
import schedule
import time
from openalgo import api

client = api(api_key="YOUR_KEY", host="http://127.0.0.1:5000")

def morning_scan():
    """Run at market open"""
    print("Running morning scan...")
    # Your scanning logic

def square_off():
    """Run before market close"""
    print("Squaring off positions...")
    client.close_all_positions(strategy="EOD_SquareOff")

def check_positions():
    """Periodic position check"""
    positions = client.get_positions()
    print(f"Open positions: {len(positions.get('data', []))}")

# Schedule tasks
schedule.every().day.at("09:20").do(morning_scan)
schedule.every().day.at("15:15").do(square_off)
schedule.every(5).minutes.do(check_positions)

# Run scheduler
while True:
    schedule.run_pending()
    time.sleep(1)
```

## Best Practices

### 1. Always Test in Analyzer Mode

```python
# Use Analyzer Mode for testing
# Enable it in OpenAlgo before running your strategy
```

### 2. Implement Risk Management

```python
def check_risk_limits(symbol, quantity, price):
    """Check if trade is within risk limits"""
    max_position_value = 100000  # ₹1 lakh per position
    max_daily_loss = 5000  # ₹5000 max daily loss

    position_value = quantity * price

    if position_value > max_position_value:
        return False, "Position size exceeds limit"

    # Check daily P&L
    # ... implementation

    return True, "OK"
```

### 3. Log Everything

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='trading.log'
)

def log_trade(action, symbol, quantity, price):
    logging.info(f"{action} {quantity} {symbol} @ {price}")
```

### 4. Handle Market Hours

```python
from datetime import datetime, time as dt_time

def is_market_open():
    """Check if market is open"""
    now = datetime.now().time()
    market_open = dt_time(9, 15)
    market_close = dt_time(15, 30)

    weekday = datetime.now().weekday()

    return (
        weekday < 5 and
        market_open <= now <= market_close
    )
```

---

**Previous**: [19 - GoCharting Integration](../19-gocharting-integration/README.md)

**Next**: [21 - Flow Visual Strategy Builder](../21-flow-visual-builder/README.md)
