# Trading Strategies Architecture

OpenAlgo supports three distinct strategy execution models: TradingView webhooks, ChartInk scanner integration, and hosted Python strategies with process isolation.

## Strategy Types Overview

| Strategy Type | Trigger Method | Execution Model | Use Case |
|---------------|----------------|-----------------|----------|
| **TradingView Webhook** | HTTP POST | Event-driven | External charting signals |
| **ChartInk Scanner** | HTTP POST | Event-driven | Indian market screeners |
| **Python Strategy** | APScheduler | Scheduled/Event | Custom algorithmic trading |

## TradingView Webhook Integration

### Architecture

```
TradingView Alert
       │
       ▼
┌──────────────────┐
│ POST /webhook    │
│ (webhook_bp)     │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Validate API Key │
│ & Parse Payload  │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Transform Signal │
│ to Order Params  │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Route to Broker  │
│ Adapter          │
└──────────────────┘
```

### Webhook Endpoint

```python
# blueprints/webhook.py
@webhook_bp.route('/webhook', methods=['POST'])
def tradingview_webhook():
    """Process TradingView webhook alerts"""

    # 1. Extract and validate API key
    api_key = request.headers.get('X-API-Key') or request.json.get('apikey')
    if not validate_api_key(api_key):
        return jsonify({'status': 'error', 'message': 'Invalid API key'}), 401

    # 2. Parse webhook payload
    payload = request.json

    # 3. Extract order parameters
    order_params = {
        'symbol': payload.get('symbol'),
        'exchange': payload.get('exchange', 'NSE'),
        'action': payload.get('action'),        # BUY/SELL
        'quantity': payload.get('quantity'),
        'product': payload.get('product', 'MIS'),
        'order_type': payload.get('order_type', 'MARKET'),
        'price': payload.get('price', 0),
        'trigger_price': payload.get('trigger_price', 0)
    }

    # 4. Execute order through broker
    broker = get_user_broker(api_key)
    result = execute_order(broker, order_params)

    return jsonify(result)
```

### TradingView Alert Format

```json
{
    "apikey": "your-openalgo-api-key",
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 100,
    "product": "MIS",
    "order_type": "MARKET",
    "position_size": "10%",
    "strategy_name": "EMA Crossover"
}
```

### Advanced Webhook Features

**Position Sizing**
```python
def calculate_quantity(payload, user_id):
    """Calculate quantity based on position sizing rules"""

    if 'quantity' in payload:
        return payload['quantity']

    if 'position_size' in payload:
        # Percentage of available margin
        margin = get_available_margin(user_id)
        ltp = get_ltp(payload['symbol'], payload['exchange'])
        return int((margin * float(payload['position_size'].strip('%')) / 100) / ltp)

    if 'risk_amount' in payload:
        # Fixed risk per trade
        return calculate_risk_based_quantity(payload)

    return payload.get('default_quantity', 1)
```

**Symbol Transformation**
```python
def transform_symbol(payload):
    """Transform TradingView symbol to broker format"""
    symbol = payload['symbol']

    # Handle options format: NIFTY24DEC19500CE
    if is_options_symbol(symbol):
        return parse_options_symbol(symbol)

    # Handle futures format: NIFTY24DECFUT
    if is_futures_symbol(symbol):
        return parse_futures_symbol(symbol)

    # Equity symbol - direct mapping
    return symbol
```

## ChartInk Scanner Integration

### Architecture

ChartInk provides stock screener signals for Indian markets:

```
ChartInk Scan Alert
       │
       ▼
┌────────────────────┐
│ POST /chartink     │
│ (chartink_bp)      │
└─────────┬──────────┘
          │
          ▼
┌────────────────────┐
│ Parse Scan Results │
│ (Multiple Stocks)  │
└─────────┬──────────┘
          │
          ▼
┌────────────────────┐
│ Apply Filters &    │
│ Position Rules     │
└─────────┬──────────┘
          │
          ▼
┌────────────────────┐
│ Execute Basket     │
│ Orders             │
└────────────────────┘
```

### ChartInk Endpoint

```python
# blueprints/chartink.py
@chartink_bp.route('/chartink', methods=['POST'])
def chartink_webhook():
    """Process ChartInk scanner webhooks"""

    api_key = request.headers.get('X-API-Key')
    if not validate_api_key(api_key):
        return jsonify({'status': 'error'}), 401

    payload = request.json

    # ChartInk sends comma-separated stock list
    stocks = payload.get('stocks', '').split(',')
    scan_name = payload.get('scan_name', 'Unknown')
    action = payload.get('action', 'BUY')

    results = []
    for stock in stocks:
        stock = stock.strip()
        if not stock:
            continue

        # Check existing position
        if has_existing_position(api_key, stock) and action == 'BUY':
            continue

        order_params = {
            'symbol': stock,
            'exchange': 'NSE',
            'action': action,
            'quantity': get_default_quantity(api_key, stock),
            'product': 'CNC',
            'order_type': 'MARKET'
        }

        result = execute_order(get_user_broker(api_key), order_params)
        results.append({'stock': stock, 'result': result})

    return jsonify({'status': 'success', 'orders': results})
```

### ChartInk Payload Format

```json
{
    "apikey": "your-openalgo-api-key",
    "scan_name": "Volume Breakout",
    "stocks": "RELIANCE,TCS,INFY,HDFCBANK",
    "action": "BUY",
    "product": "CNC",
    "quantity_per_stock": 10
}
```

## Python Strategy Hosting

### Architecture

Python strategies run in isolated processes with APScheduler:

```
┌─────────────────────────────────────────────────────────────┐
│                    Main Flask Process                        │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              Strategy Manager                         │    │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │    │
│  │  │ APScheduler │  │ Process     │  │ Strategy    │  │    │
│  │  │ Controller  │  │ Pool        │  │ Registry    │  │    │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ Strategy Proc 1 │  │ Strategy Proc 2 │  │ Strategy Proc N │
│ (EMA Crossover) │  │ (Supertrend)    │  │ (Custom)        │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

### Strategy Base Class

```python
# strategies/base_strategy.py
from abc import ABC, abstractmethod
from apscheduler.schedulers.background import BackgroundScheduler

class BaseStrategy(ABC):
    """Base class for all Python trading strategies"""

    def __init__(self, config):
        self.config = config
        self.api_key = config.get('api_key')
        self.symbols = config.get('symbols', [])
        self.is_active = False
        self.scheduler = None

    @abstractmethod
    def on_tick(self, symbol, tick_data):
        """Called on each market tick (if subscribed)"""
        pass

    @abstractmethod
    def on_candle(self, symbol, candle_data):
        """Called on each candle close"""
        pass

    @abstractmethod
    def generate_signal(self, symbol):
        """Generate trading signal for symbol"""
        pass

    def place_order(self, symbol, action, quantity, **kwargs):
        """Place order through OpenAlgo API"""
        from services.order_service import place_order
        return place_order(
            api_key=self.api_key,
            symbol=symbol,
            action=action,
            quantity=quantity,
            **kwargs
        )

    def get_position(self, symbol):
        """Get current position for symbol"""
        from services.position_service import get_position
        return get_position(self.api_key, symbol)

    def start(self):
        """Start strategy execution"""
        self.is_active = True
        self.scheduler = BackgroundScheduler()
        self.setup_schedule()
        self.scheduler.start()

    def stop(self):
        """Stop strategy execution"""
        self.is_active = False
        if self.scheduler:
            self.scheduler.shutdown()

    @abstractmethod
    def setup_schedule(self):
        """Configure execution schedule"""
        pass
```

### Example Strategy Implementation

```python
# strategies/ema_crossover.py
import pandas as pd
import pandas_ta as ta
from strategies.base_strategy import BaseStrategy

class EMACrossoverStrategy(BaseStrategy):
    """EMA Crossover Strategy with configurable periods"""

    def __init__(self, config):
        super().__init__(config)
        self.fast_period = config.get('fast_period', 9)
        self.slow_period = config.get('slow_period', 21)
        self.timeframe = config.get('timeframe', '5min')
        self.quantity = config.get('quantity', 1)

    def setup_schedule(self):
        """Run on every candle close"""
        interval_map = {
            '1min': 1, '5min': 5, '15min': 15, '1hour': 60
        }
        minutes = interval_map.get(self.timeframe, 5)

        self.scheduler.add_job(
            self.run_strategy,
            'cron',
            minute=f'*/{minutes}',
            hour='9-15',  # Market hours IST
            day_of_week='mon-fri'
        )

    def on_tick(self, symbol, tick_data):
        """Not used in this strategy"""
        pass

    def on_candle(self, symbol, candle_data):
        """Process new candle data"""
        signal = self.generate_signal(symbol)
        if signal:
            self.execute_signal(symbol, signal)

    def generate_signal(self, symbol):
        """Generate EMA crossover signal"""
        # Fetch historical data
        df = self.get_historical_data(symbol, self.timeframe, 50)

        if df is None or len(df) < self.slow_period:
            return None

        # Calculate EMAs
        df['ema_fast'] = ta.ema(df['close'], length=self.fast_period)
        df['ema_slow'] = ta.ema(df['close'], length=self.slow_period)

        # Check for crossover
        current = df.iloc[-1]
        previous = df.iloc[-2]

        # Bullish crossover
        if (previous['ema_fast'] <= previous['ema_slow'] and
            current['ema_fast'] > current['ema_slow']):
            return 'BUY'

        # Bearish crossover
        if (previous['ema_fast'] >= previous['ema_slow'] and
            current['ema_fast'] < current['ema_slow']):
            return 'SELL'

        return None

    def execute_signal(self, symbol, signal):
        """Execute trading signal"""
        position = self.get_position(symbol)

        if signal == 'BUY' and not position:
            self.place_order(
                symbol=symbol,
                action='BUY',
                quantity=self.quantity,
                order_type='MARKET',
                product='MIS'
            )
        elif signal == 'SELL' and position and position.get('quantity', 0) > 0:
            self.place_order(
                symbol=symbol,
                action='SELL',
                quantity=position['quantity'],
                order_type='MARKET',
                product='MIS'
            )

    def run_strategy(self):
        """Main strategy loop"""
        for symbol in self.symbols:
            try:
                signal = self.generate_signal(symbol)
                if signal:
                    self.execute_signal(symbol, signal)
            except Exception as e:
                self.log_error(f"Error processing {symbol}: {e}")

    def get_historical_data(self, symbol, timeframe, bars):
        """Fetch historical candle data"""
        from services.data_service import get_historical_data
        return get_historical_data(
            api_key=self.api_key,
            symbol=symbol,
            timeframe=timeframe,
            bars=bars
        )
```

### Strategy Manager

```python
# services/strategy_manager.py
import multiprocessing
from importlib import import_module

class StrategyManager:
    """Manages strategy lifecycle and execution"""

    def __init__(self):
        self.strategies = {}  # strategy_id -> Process
        self.registry = {}    # strategy_name -> strategy_class
        self._discover_strategies()

    def _discover_strategies(self):
        """Auto-discover strategy classes"""
        strategy_dir = Path('strategies')
        for file in strategy_dir.glob('*.py'):
            if file.name.startswith('_'):
                continue
            module = import_module(f'strategies.{file.stem}')
            for name, obj in inspect.getmembers(module):
                if (inspect.isclass(obj) and
                    issubclass(obj, BaseStrategy) and
                    obj != BaseStrategy):
                    self.registry[name] = obj

    def start_strategy(self, strategy_id, strategy_type, config):
        """Start a strategy in isolated process"""
        if strategy_id in self.strategies:
            raise ValueError(f"Strategy {strategy_id} already running")

        strategy_class = self.registry.get(strategy_type)
        if not strategy_class:
            raise ValueError(f"Unknown strategy type: {strategy_type}")

        # Create and start process
        process = multiprocessing.Process(
            target=self._run_strategy,
            args=(strategy_class, config)
        )
        process.start()
        self.strategies[strategy_id] = process

        # Update database
        update_strategy_status(strategy_id, 'active')

        return {'status': 'started', 'pid': process.pid}

    def stop_strategy(self, strategy_id):
        """Stop a running strategy"""
        if strategy_id not in self.strategies:
            raise ValueError(f"Strategy {strategy_id} not running")

        process = self.strategies[strategy_id]
        process.terminate()
        process.join(timeout=5)

        if process.is_alive():
            process.kill()

        del self.strategies[strategy_id]
        update_strategy_status(strategy_id, 'stopped')

        return {'status': 'stopped'}

    def _run_strategy(self, strategy_class, config):
        """Run strategy in subprocess"""
        try:
            strategy = strategy_class(config)
            strategy.start()

            # Keep process alive
            while True:
                time.sleep(1)
        except Exception as e:
            log_strategy_error(config.get('strategy_id'), str(e))
```

### Strategy API

```python
# blueprints/strategy.py
@strategy_bp.route('/strategies', methods=['GET'])
def list_strategies():
    """List all available and active strategies"""
    pass

@strategy_bp.route('/strategies', methods=['POST'])
def create_strategy():
    """Create and configure a new strategy instance"""
    pass

@strategy_bp.route('/strategies/<strategy_id>/start', methods=['POST'])
def start_strategy(strategy_id):
    """Start strategy execution"""
    pass

@strategy_bp.route('/strategies/<strategy_id>/stop', methods=['POST'])
def stop_strategy(strategy_id):
    """Stop strategy execution"""
    pass

@strategy_bp.route('/strategies/<strategy_id>/status', methods=['GET'])
def strategy_status(strategy_id):
    """Get strategy execution status"""
    pass
```

## Strategy Configuration

### Database Schema

```python
class Strategy(Base):
    __tablename__ = 'strategies'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('user.id'))
    name = Column(String(100))
    strategy_type = Column(String(50))  # ema_crossover/supertrend/custom
    config = Column(JSON)               # Strategy-specific configuration
    symbols = Column(JSON)              # List of symbols to trade
    is_active = Column(Boolean, default=False)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
```

### Configuration Example

```json
{
    "strategy_type": "EMACrossoverStrategy",
    "name": "NIFTY EMA Strategy",
    "symbols": ["NIFTY24DECFUT", "BANKNIFTY24DECFUT"],
    "config": {
        "fast_period": 9,
        "slow_period": 21,
        "timeframe": "5min",
        "quantity": 50,
        "product": "MIS",
        "max_positions": 2,
        "stop_loss_percent": 1.0,
        "target_percent": 2.0
    }
}
```

## Scheduling Architecture

### APScheduler Configuration

```python
# services/scheduler_service.py
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.pool import ThreadPoolExecutor, ProcessPoolExecutor

jobstores = {
    'default': SQLAlchemyJobStore(url='sqlite:///databases/jobs.db')
}

executors = {
    'default': ThreadPoolExecutor(20),
    'processpool': ProcessPoolExecutor(5)
}

job_defaults = {
    'coalesce': False,
    'max_instances': 3
}

scheduler = BackgroundScheduler(
    jobstores=jobstores,
    executors=executors,
    job_defaults=job_defaults,
    timezone='Asia/Kolkata'
)
```

### Market Hours Scheduling

```python
def add_market_hours_job(func, strategy_id, interval_minutes=5):
    """Schedule job to run only during market hours"""
    scheduler.add_job(
        func,
        'cron',
        id=f'strategy_{strategy_id}',
        minute=f'*/{interval_minutes}',
        hour='9-15',
        day_of_week='mon-fri',
        timezone='Asia/Kolkata',
        misfire_grace_time=60
    )
```

## Risk Management

### Position Limits

```python
def check_position_limits(api_key, symbol, quantity):
    """Enforce position size limits"""
    config = get_user_risk_config(api_key)

    # Check max position size
    if quantity > config.get('max_position_size', 1000):
        raise RiskLimitError("Position size exceeds limit")

    # Check max positions per symbol
    current_position = get_position(api_key, symbol)
    if current_position:
        total = current_position['quantity'] + quantity
        if total > config.get('max_symbol_exposure', 2000):
            raise RiskLimitError("Symbol exposure exceeds limit")

    # Check max daily orders
    daily_orders = get_daily_order_count(api_key)
    if daily_orders >= config.get('max_daily_orders', 100):
        raise RiskLimitError("Daily order limit reached")
```

### Stop Loss Management

```python
def manage_stop_loss(position, config):
    """Automated stop loss management"""
    stop_loss_pct = config.get('stop_loss_percent', 2.0)

    if position['pnl_percent'] <= -stop_loss_pct:
        # Execute stop loss
        place_order(
            symbol=position['symbol'],
            action='SELL' if position['quantity'] > 0 else 'BUY',
            quantity=abs(position['quantity']),
            order_type='MARKET',
            product=position['product']
        )
        return True
    return False
```

## Monitoring and Logging

### Strategy Logging

```python
def log_strategy_event(strategy_id, event_type, data):
    """Log strategy events for analysis"""
    from database.strategy_logs_db import insert_strategy_log

    insert_strategy_log({
        'strategy_id': strategy_id,
        'event_type': event_type,  # signal/order/error/info
        'data': json.dumps(data),
        'timestamp': datetime.now()
    })
```

### Performance Metrics

```python
def calculate_strategy_metrics(strategy_id, period='daily'):
    """Calculate strategy performance metrics"""
    trades = get_strategy_trades(strategy_id, period)

    return {
        'total_trades': len(trades),
        'winning_trades': sum(1 for t in trades if t['pnl'] > 0),
        'losing_trades': sum(1 for t in trades if t['pnl'] < 0),
        'total_pnl': sum(t['pnl'] for t in trades),
        'win_rate': calculate_win_rate(trades),
        'sharpe_ratio': calculate_sharpe(trades),
        'max_drawdown': calculate_max_drawdown(trades)
    }
```

## Related Documentation

- [API Layer](./02_api_layer.md) - Webhook API endpoints
- [Broker Integration](./03_broker_integration.md) - Order execution
- [Database Layer](./04_database_layer.md) - Strategy persistence
- [Python Strategy Hosting](./11_python_strategy_hosting.md) - Advanced strategy details
- [WebSocket Architecture](./09_websocket_architecture.md) - Real-time data for strategies
