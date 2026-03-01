# Built-in Backtesting Engine — Implementation Plan

## Core Design Principle

**Zero-code-change compatibility**: A Python strategy written for live trading (using `openalgo` SDK) should run as a backtest with **no modifications**. The engine swaps the live `api` client with a `BacktestClient` that replays historical data and simulates execution.

---

## Existing Infrastructure Leveraged

### Historify (DuckDB) — Data Source
- **Database**: `db/historify.duckdb`
- **Main table**: `market_data` with columns: `symbol`, `exchange`, `interval`, `timestamp` (BIGINT epoch seconds), `open`, `high`, `low`, `close` (DOUBLE), `volume`, `oi` (BIGINT)
- **Storage intervals**: Only `1m` and `D` are physically stored
- **Computed intervals**: `5m`, `15m`, `30m`, `1h` aggregated on-the-fly from 1m data
- **Custom intervals**: Any `Nm` or `Nh` dynamically computed; `W`, `M`, `Q`, `Y` from daily data
- **Candle alignment**: Intraday candles align to exchange market open (NSE: 09:15 IST, MCX: 09:00 IST)
- **Key query function**: `get_ohlcv(symbol, exchange, interval, start_timestamp, end_timestamp)` returns pandas DataFrame
- **Export function**: `export_to_dataframe()` returns DataFrame with datetime index ready for backtesting
- **Performance**: <50ms for 1-year intraday queries due to columnar storage + vectorized aggregation
- **Supported exchanges**: NSE, BSE, NFO, BFO, MCX, CDS, BCD, NSE_INDEX, BSE_INDEX
- **Metadata**: `data_catalog` table provides instant answers to "do I have data for X from Y to Z?" without scanning main table

### Sandbox — Execution Model Reference
- **Order types**: MARKET, LIMIT, SL, SL-M all supported
- **Position netting**: Weighted average price, partial closes, reversals
- **Margin system**: Leverage-based (Equity MIS: 5x, CNC: 1x, Futures: 10x, Options: 1x)
- **P&L tracking**: Realized + unrealized, daily settlement, accumulated all-time
- **Fill logic**: MARKET fills at bid/ask; LIMIT fills at limit price when LTP crosses; SL triggers then fills
- **No slippage model**: Only implicit via bid/ask spread
- **No commission model**: P&L is gross

### OpenAlgo SDK — Strategy Interface
- Strategies use `from openalgo import api` and call methods like `client.history()`, `client.placeorder()`, `client.placesmartorder()`, `client.quotes()`, `client.positionbook()`, `client.funds()`, etc.
- `client.history(source="db")` already fetches from Historify DuckDB
- Strategies typically run in `while True` loops with `time.sleep()` between iterations

### Python Strategy Hosting
- Each strategy runs in a **separate subprocess** with resource limits
- Config stored in `strategies/strategy_configs.json`
- Logs captured to `log/strategies/`
- SSE (Server-Sent Events) for real-time UI updates
- Frontend uses CodeMirror-based Python editor

---

## Phase 1: Backtest Engine Core (Backend)

### Step 1 — Database Schema

**New file**: `database/backtest_db.py`
**New database**: `db/backtest.db` (SQLite, separate from all other databases)

**Why separate DB**: Keeps backtests isolated, can grow large without affecting live trading, easy to purge old results.

#### Table: BacktestRun

One row per backtest execution.

```python
class BacktestRun(db.Model):
    __tablename__ = 'backtest_runs'

    id                    = db.Column(db.String(50), primary_key=True)  # BT-YYYYMMDD-HHMMSS-{uuid8}
    user_id               = db.Column(db.String(50), index=True, nullable=False)
    name                  = db.Column(db.String(200), nullable=False)
    strategy_id           = db.Column(db.String(50), nullable=True)  # links to python_strategy if applicable
    strategy_code         = db.Column(db.Text, nullable=False)  # snapshot of code at run time

    # Configuration
    symbols               = db.Column(db.Text, nullable=False)  # JSON: [{"symbol":"SBIN","exchange":"NSE"}]
    start_date            = db.Column(db.String(10), nullable=False)  # YYYY-MM-DD
    end_date              = db.Column(db.String(10), nullable=False)
    interval              = db.Column(db.String(10), nullable=False)  # 1m, 5m, 15m, 1h, D
    initial_capital       = db.Column(db.Numeric(15, 2), nullable=False)
    slippage_pct          = db.Column(db.Numeric(6, 4), default=0.05)  # 0.05%
    commission_per_order  = db.Column(db.Numeric(10, 2), default=20.00)  # Rs.20 flat
    commission_pct        = db.Column(db.Numeric(6, 4), default=0.00)  # or percentage-based
    data_source           = db.Column(db.String(10), default='db')  # 'db' (Historify) or 'api' (broker)

    # Results (populated after run)
    status                = db.Column(db.String(20), default='pending')  # pending/running/completed/failed/cancelled
    final_capital         = db.Column(db.Numeric(15, 2), nullable=True)
    total_return_pct      = db.Column(db.Numeric(10, 4), nullable=True)
    cagr                  = db.Column(db.Numeric(10, 4), nullable=True)
    sharpe_ratio          = db.Column(db.Numeric(10, 4), nullable=True)
    sortino_ratio         = db.Column(db.Numeric(10, 4), nullable=True)
    max_drawdown_pct      = db.Column(db.Numeric(10, 4), nullable=True)
    calmar_ratio          = db.Column(db.Numeric(10, 4), nullable=True)
    win_rate              = db.Column(db.Numeric(10, 4), nullable=True)
    profit_factor         = db.Column(db.Numeric(10, 4), nullable=True)
    total_trades          = db.Column(db.Integer, default=0)
    winning_trades        = db.Column(db.Integer, default=0)
    losing_trades         = db.Column(db.Integer, default=0)
    avg_win               = db.Column(db.Numeric(15, 2), nullable=True)
    avg_loss              = db.Column(db.Numeric(15, 2), nullable=True)
    max_win               = db.Column(db.Numeric(15, 2), nullable=True)
    max_loss              = db.Column(db.Numeric(15, 2), nullable=True)
    expectancy            = db.Column(db.Numeric(15, 2), nullable=True)
    avg_holding_bars      = db.Column(db.Integer, nullable=True)

    # Serialized data
    equity_curve_json     = db.Column(db.Text, nullable=True)  # JSON array of {timestamp, equity, drawdown}
    monthly_returns_json  = db.Column(db.Text, nullable=True)  # JSON for calendar heatmap
    error_message         = db.Column(db.Text, nullable=True)

    # Timestamps
    created_at            = db.Column(db.DateTime, default=func.now())
    started_at            = db.Column(db.DateTime, nullable=True)
    completed_at          = db.Column(db.DateTime, nullable=True)
    duration_ms           = db.Column(db.Integer, nullable=True)  # execution time
```

#### Table: BacktestTrade

Every simulated trade recorded for analysis.

```python
class BacktestTrade(db.Model):
    __tablename__ = 'backtest_trades'

    id              = db.Column(db.Integer, primary_key=True, autoincrement=True)
    backtest_id     = db.Column(db.String(50), db.ForeignKey('backtest_runs.id'), index=True, nullable=False)
    trade_num       = db.Column(db.Integer, nullable=False)  # sequential trade number

    symbol          = db.Column(db.String(50), nullable=False)
    exchange        = db.Column(db.String(20), nullable=False)
    action          = db.Column(db.String(10), nullable=False)  # BUY/SELL
    quantity        = db.Column(db.Integer, nullable=False)
    entry_price     = db.Column(db.Numeric(10, 2), nullable=False)
    exit_price      = db.Column(db.Numeric(10, 2), nullable=True)  # null if still open at end
    entry_time      = db.Column(db.DateTime, nullable=False)
    exit_time       = db.Column(db.DateTime, nullable=True)

    pnl             = db.Column(db.Numeric(15, 2), default=0)  # gross P&L
    pnl_pct         = db.Column(db.Numeric(10, 4), default=0)
    commission      = db.Column(db.Numeric(10, 2), default=0)
    slippage_cost   = db.Column(db.Numeric(10, 2), default=0)
    net_pnl         = db.Column(db.Numeric(15, 2), default=0)  # pnl - commission - slippage

    bars_held       = db.Column(db.Integer, default=0)
    product         = db.Column(db.String(20), nullable=True)
    strategy_tag    = db.Column(db.String(100), nullable=True)

    __table_args__ = (
        db.Index('idx_backtest_trade', 'backtest_id', 'trade_num'),
    )
```

#### Initialization

```python
def init_backtest_db():
    """Initialize backtest database. Called from app.py parallel DB init."""
    db_path = os.path.join(os.path.dirname(__file__), '..', 'db', 'backtest.db')
    engine = create_engine(f'sqlite:///{db_path}')
    Base.metadata.create_all(engine)
```

Add `init_backtest_db()` to the parallel database initialization in `app.py` (line ~484).

---

### Step 2 — Backtest Client

**New file**: `services/backtest_client.py`

A drop-in replacement for the `openalgo.api` class that intercepts all SDK calls and simulates execution on historical data.

```python
class BacktestClient:
    """
    Drop-in replacement for openalgo.api that simulates execution on historical data.

    All public methods mirror the openalgo SDK interface exactly so that strategies
    written for live trading work in backtest mode with zero code changes.
    """

    def __init__(self, config):
        # Configuration
        self.initial_capital = float(config['initial_capital'])
        self.capital = float(config['initial_capital'])
        self.slippage_pct = float(config.get('slippage_pct', 0.0005))
        self.commission_per_order = float(config.get('commission_per_order', 20.0))
        self.commission_pct = float(config.get('commission_pct', 0.0))

        # Data store (populated by engine before run)
        self.data = {}                 # {symbol_key: DataFrame} preloaded OHLCV
        self.current_bar_index = {}    # {symbol_key: int} current position in replay
        self.current_timestamp = None  # current bar's timestamp

        # State tracking
        self.positions = {}            # {symbol_key: {qty, avg_price, product, margin}}
        self.orders = []               # all orders placed
        self.trades = []               # completed round-trip trades
        self.open_entries = {}         # {symbol_key: {entry_price, entry_time, entry_bar, qty, action}}
        self.pending_orders = []       # SL/LIMIT orders waiting for trigger
        self.equity_curve = []         # [{timestamp, equity, drawdown}]
        self.peak_equity = float(config['initial_capital'])
        self._order_counter = 0
        self._trade_counter = 0

    # ─── SDK-Compatible Methods ──────────────────────────────────────────

    def history(self, symbol, exchange, interval, start_date, end_date, source='db'):
        """
        Returns historical data UP TO current bar (no look-ahead bias).
        This is the CRITICAL method that prevents cheating in backtests.
        """
        key = f"{symbol}:{exchange}"
        if key not in self.data:
            return pd.DataFrame()
        df = self.data[key]
        current_idx = self.current_bar_index.get(key, len(df) - 1)
        return df.iloc[:current_idx + 1].copy()

    def quotes(self, symbol, exchange):
        """Returns current bar's OHLCV as a quote snapshot."""
        bar = self._get_current_bar(symbol, exchange)
        if bar is None:
            return {'status': 'error', 'message': 'No data'}
        prev_close = self._get_prev_close(symbol, exchange)
        return {
            'status': 'success',
            'data': {
                'ltp': float(bar['close']),
                'open': float(bar['open']),
                'high': float(bar['high']),
                'low': float(bar['low']),
                'close': float(bar['close']),
                'volume': int(bar['volume']),
                'bid': float(bar['close']),
                'ask': float(bar['close']),
                'prev_close': float(prev_close) if prev_close else float(bar['open']),
                'oi': int(bar.get('oi', 0)),
            }
        }

    def multiquotes(self, symbols):
        """Returns quotes for multiple symbols."""
        results = {}
        for sym in symbols:
            q = self.quotes(sym['symbol'], sym['exchange'])
            if q['status'] == 'success':
                results[f"{sym['symbol']}:{sym['exchange']}"] = q['data']
        return {'status': 'success', 'data': results}

    def placeorder(self, strategy='', symbol='', action='', exchange='',
                   price_type='MARKET', product='MIS', quantity=1,
                   price=0, trigger_price=0, **kwargs):
        """Simulate order execution using current bar data."""
        bar = self._get_current_bar(symbol, exchange)
        if bar is None:
            return {'status': 'error', 'message': 'No data for symbol'}

        self._order_counter += 1
        order_id = f'BT-{self._order_counter:06d}'

        if price_type == 'MARKET':
            exec_price = self._apply_slippage(float(bar['close']), action)
            self._execute_fill(symbol, exchange, action, int(quantity),
                               exec_price, product, strategy, bar)
            return {'orderid': order_id, 'status': 'success'}

        elif price_type in ('LIMIT', 'SL', 'SL-M'):
            # Queue as pending order, checked on each bar
            self.pending_orders.append({
                'order_id': order_id,
                'symbol': symbol,
                'exchange': exchange,
                'action': action,
                'quantity': int(quantity),
                'price_type': price_type,
                'price': float(price),
                'trigger_price': float(trigger_price),
                'product': product,
                'strategy': strategy,
                'placed_bar': self.current_bar_index.get(f"{symbol}:{exchange}", 0),
            })
            return {'orderid': order_id, 'status': 'success'}

        return {'status': 'error', 'message': f'Unknown price_type: {price_type}'}

    def placesmartorder(self, strategy='', symbol='', action='', exchange='',
                        price_type='MARKET', product='MIS', quantity=1,
                        position_size=0, **kwargs):
        """Position-aware order placement (mirrors live behavior)."""
        key = f"{symbol}:{exchange}"
        current_qty = self.positions.get(key, {}).get('qty', 0)

        if action == 'BUY':
            needed = int(position_size) - current_qty
            if needed > 0:
                return self.placeorder(strategy=strategy, symbol=symbol, action='BUY',
                                       exchange=exchange, price_type=price_type,
                                       product=product, quantity=needed, **kwargs)
            elif needed < 0:
                return self.placeorder(strategy=strategy, symbol=symbol, action='SELL',
                                       exchange=exchange, price_type=price_type,
                                       product=product, quantity=abs(needed), **kwargs)
        elif action == 'SELL':
            needed = current_qty - int(position_size)
            if needed > 0:
                return self.placeorder(strategy=strategy, symbol=symbol, action='SELL',
                                       exchange=exchange, price_type=price_type,
                                       product=product, quantity=needed, **kwargs)
            elif needed < 0:
                return self.placeorder(strategy=strategy, symbol=symbol, action='BUY',
                                       exchange=exchange, price_type=price_type,
                                       product=product, quantity=abs(needed), **kwargs)

        return {'status': 'success', 'message': 'No action needed'}

    def cancelorder(self, order_id='', **kwargs):
        """Cancel a pending order."""
        self.pending_orders = [o for o in self.pending_orders if o['order_id'] != order_id]
        return {'status': 'success'}

    def cancelallorder(self, strategy='', **kwargs):
        """Cancel all pending orders."""
        if strategy:
            self.pending_orders = [o for o in self.pending_orders if o.get('strategy') != strategy]
        else:
            self.pending_orders.clear()
        return {'status': 'success'}

    def closeposition(self, strategy='', **kwargs):
        """Close all open positions."""
        for key, pos in list(self.positions.items()):
            if pos['qty'] != 0:
                symbol, exchange = key.split(':')
                action = 'SELL' if pos['qty'] > 0 else 'BUY'
                self.placeorder(strategy=strategy, symbol=symbol, action=action,
                                exchange=exchange, price_type='MARKET',
                                product=pos.get('product', 'MIS'),
                                quantity=abs(pos['qty']))
        return {'status': 'success'}

    def positionbook(self):
        """Return current positions."""
        positions = []
        for key, pos in self.positions.items():
            if pos['qty'] != 0:
                symbol, exchange = key.split(':')
                bar = self._get_current_bar(symbol, exchange)
                ltp = float(bar['close']) if bar is not None else pos['avg_price']
                pnl = (ltp - pos['avg_price']) * pos['qty']
                positions.append({
                    'symbol': symbol, 'exchange': exchange,
                    'product': pos.get('product', 'MIS'),
                    'quantity': str(pos['qty']),
                    'average_price': str(pos['avg_price']),
                    'ltp': str(ltp), 'pnl': str(round(pnl, 2)),
                })
        return {'status': 'success', 'data': positions}

    def orderbook(self):
        """Return all orders."""
        return {'status': 'success', 'data': self.orders}

    def tradebook(self):
        """Return all executed trades."""
        return {'status': 'success', 'data': [
            {'symbol': t['symbol'], 'exchange': t['exchange'],
             'action': t['action'], 'quantity': t['quantity'],
             'price': t['entry_price'], 'strategy': t.get('strategy_tag', '')}
            for t in self.trades
        ]}

    def funds(self):
        """Return fund balances."""
        unrealized = self._total_unrealized()
        return {
            'status': 'success',
            'data': {
                'availablecash': str(round(self.capital, 2)),
                'collateral': '0',
                'm2mrealized': str(round(self.capital - self.initial_capital, 2)),
                'm2munrealized': str(round(unrealized, 2)),
            }
        }

    def openposition(self, strategy='', symbol='', exchange='', product='MIS'):
        """Check if a position exists for a symbol."""
        key = f"{symbol}:{exchange}"
        pos = self.positions.get(key, {})
        qty = pos.get('qty', 0)
        return {'status': 'success', 'quantity': str(qty)}

    # ─── Internal Methods ────────────────────────────────────────────────

    def _get_current_bar(self, symbol, exchange):
        """Get the current bar for a symbol."""
        key = f"{symbol}:{exchange}"
        if key not in self.data:
            return None
        idx = self.current_bar_index.get(key, 0)
        df = self.data[key]
        if idx >= len(df):
            return None
        return df.iloc[idx]

    def _get_prev_close(self, symbol, exchange):
        """Get previous bar's close price."""
        key = f"{symbol}:{exchange}"
        idx = self.current_bar_index.get(key, 0)
        if idx <= 0:
            return None
        return self.data[key].iloc[idx - 1]['close']

    def _apply_slippage(self, price, action):
        """Apply slippage to execution price."""
        if action == 'BUY':
            return round(price * (1 + self.slippage_pct / 100), 2)
        return round(price * (1 - self.slippage_pct / 100), 2)

    def _calculate_commission(self, trade_value):
        """Calculate commission for a trade."""
        if self.commission_pct > 0:
            return round(trade_value * self.commission_pct / 100, 2)
        return self.commission_per_order

    def _execute_fill(self, symbol, exchange, action, qty, exec_price, product, strategy, bar):
        """Execute a fill: update positions, deduct commission, record trade."""
        key = f"{symbol}:{exchange}"
        trade_value = qty * exec_price
        commission = self._calculate_commission(trade_value)
        slippage_cost = abs(exec_price - float(bar['close'])) * qty

        # Deduct commission
        self.capital -= commission

        # Record order
        self.orders.append({
            'symbol': symbol, 'exchange': exchange, 'action': action,
            'quantity': qty, 'price': exec_price, 'product': product,
            'strategy': strategy, 'status': 'complete',
            'timestamp': self.current_timestamp,
        })

        # Update position
        pos = self.positions.get(key, {'qty': 0, 'avg_price': 0, 'product': product})
        old_qty = pos['qty']

        if action == 'BUY':
            new_qty = old_qty + qty
        else:  # SELL
            new_qty = old_qty - qty

        # Determine if this is opening, adding, reducing, or closing
        if old_qty == 0:
            # New position
            pos['avg_price'] = exec_price
            pos['qty'] = new_qty
            pos['product'] = product
            # Record entry for trade tracking
            self.open_entries[key] = {
                'entry_price': exec_price, 'entry_time': self.current_timestamp,
                'entry_bar': self.current_bar_index.get(key, 0),
                'qty': abs(new_qty), 'action': action, 'strategy': strategy,
            }

        elif (old_qty > 0 and action == 'BUY') or (old_qty < 0 and action == 'SELL'):
            # Adding to position — weighted average
            total_cost = abs(old_qty) * pos['avg_price'] + qty * exec_price
            pos['qty'] = new_qty
            pos['avg_price'] = round(total_cost / abs(new_qty), 2)

        else:
            # Reducing or closing or reversing
            close_qty = min(abs(old_qty), qty)

            # Calculate P&L for closed portion
            if old_qty > 0:
                pnl = (exec_price - pos['avg_price']) * close_qty
            else:
                pnl = (pos['avg_price'] - exec_price) * close_qty

            # Credit P&L
            self.capital += pnl

            # Record completed trade
            entry = self.open_entries.get(key, {})
            self._trade_counter += 1
            self.trades.append({
                'trade_num': self._trade_counter,
                'symbol': symbol, 'exchange': exchange,
                'action': 'LONG' if old_qty > 0 else 'SHORT',
                'quantity': close_qty,
                'entry_price': pos['avg_price'],
                'exit_price': exec_price,
                'entry_time': entry.get('entry_time'),
                'exit_time': self.current_timestamp,
                'pnl': round(pnl, 2),
                'pnl_pct': round(pnl / (pos['avg_price'] * close_qty) * 100, 4) if pos['avg_price'] > 0 else 0,
                'commission': commission,
                'slippage_cost': round(slippage_cost, 2),
                'net_pnl': round(pnl - commission, 2),
                'bars_held': self.current_bar_index.get(key, 0) - entry.get('entry_bar', 0),
                'product': product,
                'strategy_tag': strategy,
            })

            pos['qty'] = new_qty

            if new_qty == 0:
                # Position fully closed
                pos['avg_price'] = 0
                self.open_entries.pop(key, None)
            elif (old_qty > 0 and new_qty < 0) or (old_qty < 0 and new_qty > 0):
                # Position reversed — open new entry for excess
                excess = abs(new_qty)
                pos['avg_price'] = exec_price
                self.open_entries[key] = {
                    'entry_price': exec_price, 'entry_time': self.current_timestamp,
                    'entry_bar': self.current_bar_index.get(key, 0),
                    'qty': excess, 'action': action, 'strategy': strategy,
                }

        self.positions[key] = pos

    def process_pending_orders(self):
        """Called each bar to check SL/LIMIT order triggers against current bar's OHLC."""
        remaining = []
        for order in self.pending_orders:
            key = f"{order['symbol']}:{order['exchange']}"
            bar = self._get_current_bar(order['symbol'], order['exchange'])
            if bar is None:
                remaining.append(order)
                continue

            triggered = False
            exec_price = 0

            if order['price_type'] == 'LIMIT':
                if order['action'] == 'BUY' and float(bar['low']) <= order['price']:
                    exec_price = order['price']
                    triggered = True
                elif order['action'] == 'SELL' and float(bar['high']) >= order['price']:
                    exec_price = order['price']
                    triggered = True

            elif order['price_type'] == 'SL':
                if order['action'] == 'BUY' and float(bar['high']) >= order['trigger_price']:
                    exec_price = min(order['price'], float(bar['high']))
                    triggered = True
                elif order['action'] == 'SELL' and float(bar['low']) <= order['trigger_price']:
                    exec_price = max(order['price'], float(bar['low']))
                    triggered = True

            elif order['price_type'] == 'SL-M':
                if order['action'] == 'BUY' and float(bar['high']) >= order['trigger_price']:
                    exec_price = self._apply_slippage(float(bar['close']), 'BUY')
                    triggered = True
                elif order['action'] == 'SELL' and float(bar['low']) <= order['trigger_price']:
                    exec_price = self._apply_slippage(float(bar['close']), 'SELL')
                    triggered = True

            if triggered:
                self._execute_fill(order['symbol'], order['exchange'], order['action'],
                                   order['quantity'], exec_price, order['product'],
                                   order['strategy'], bar)
            else:
                remaining.append(order)

        self.pending_orders = remaining

    def record_equity(self, timestamp):
        """Snapshot equity at each bar for equity curve generation."""
        unrealized = self._total_unrealized()
        equity = self.capital + unrealized
        self.peak_equity = max(self.peak_equity, equity)
        drawdown = (self.peak_equity - equity) / self.peak_equity if self.peak_equity > 0 else 0
        self.equity_curve.append({
            'timestamp': int(timestamp) if not isinstance(timestamp, int) else timestamp,
            'equity': round(equity, 2),
            'drawdown': round(drawdown, 6),
        })

    def close_all_positions_at_end(self):
        """Force-close all open positions at the last bar price."""
        for key, pos in list(self.positions.items()):
            if pos['qty'] != 0:
                symbol, exchange = key.split(':')
                bar = self._get_current_bar(symbol, exchange)
                if bar is not None:
                    action = 'SELL' if pos['qty'] > 0 else 'BUY'
                    exec_price = self._apply_slippage(float(bar['close']), action)
                    self._execute_fill(symbol, exchange, action, abs(pos['qty']),
                                       exec_price, pos.get('product', 'MIS'), 'backtest_close', bar)

    def _total_unrealized(self):
        """Calculate total unrealized P&L across all positions."""
        total = 0
        for key, pos in self.positions.items():
            if pos['qty'] != 0:
                symbol, exchange = key.split(':')
                bar = self._get_current_bar(symbol, exchange)
                if bar is not None:
                    ltp = float(bar['close'])
                    if pos['qty'] > 0:
                        total += (ltp - pos['avg_price']) * pos['qty']
                    else:
                        total += (pos['avg_price'] - ltp) * abs(pos['qty'])
        return total

    def advance_to(self, timestamp):
        """Advance all symbols to the given timestamp."""
        self.current_timestamp = timestamp
        for key, df in self.data.items():
            timestamps = df['timestamp'].values if 'timestamp' in df.columns else df.index.values
            # Find the latest bar at or before this timestamp
            mask = timestamps <= timestamp
            if mask.any():
                self.current_bar_index[key] = int(mask.sum()) - 1
```

---

### Step 3 — Backtest Engine

**New file**: `services/backtest_engine.py`

The orchestrator that loads data, replays bars, and runs strategy code.

```python
class BacktestEngine:
    """
    Bar-by-bar replay engine.

    Two execution modes:
    1. Event-driven: Strategy has while True + time.sleep() loop.
       Engine patches sleep -> bar advance, runs 1 iteration per bar.
    2. Vectorized: Strategy computes signals on full DataFrame at once.
       Faster, but strategy must follow vectorized pattern.
    """

    def __init__(self):
        self.cancelled = set()  # backtest IDs that have been cancelled

    def run(self, backtest_run, strategy_code):
        """
        Main entry point. Loads data, creates client, runs strategy, returns results.

        Args:
            backtest_run: BacktestRun model instance with all configuration
            strategy_code: Python source code of the strategy

        Returns:
            dict with all results, metrics, trades, equity curve
        """
        import json
        from database.historify_db import get_ohlcv

        symbols = json.loads(backtest_run.symbols)
        start_ts = int(datetime.strptime(backtest_run.start_date, '%Y-%m-%d').timestamp())
        end_ts = int(datetime.strptime(backtest_run.end_date + ' 23:59:59', '%Y-%m-%d %H:%M:%S').timestamp())

        # 1. Load historical data from Historify (DuckDB)
        data = {}
        for sym in symbols:
            df = get_ohlcv(
                symbol=sym['symbol'],
                exchange=sym['exchange'],
                interval=backtest_run.interval,
                start_timestamp=start_ts,
                end_timestamp=end_ts,
            )
            if df.empty:
                raise ValueError(f"No data found for {sym['symbol']}:{sym['exchange']} "
                                 f"in interval {backtest_run.interval} "
                                 f"from {backtest_run.start_date} to {backtest_run.end_date}. "
                                 f"Please download data via Historify first.")
            data[f"{sym['symbol']}:{sym['exchange']}"] = df

        # 2. Build unified timeline (sorted union of all symbols' timestamps)
        all_timestamps = set()
        for df in data.values():
            if 'timestamp' in df.columns:
                all_timestamps.update(df['timestamp'].tolist())
        timeline = sorted(all_timestamps)

        if not timeline:
            raise ValueError("No data points found in the specified date range.")

        # 3. Initialize BacktestClient
        client = BacktestClient(config={
            'initial_capital': float(backtest_run.initial_capital),
            'slippage_pct': float(backtest_run.slippage_pct),
            'commission_per_order': float(backtest_run.commission_per_order),
            'commission_pct': float(backtest_run.commission_pct),
        })
        client.data = data

        # 4. Patch and run strategy
        patcher = StrategyPatcher()
        iteration_fn = patcher.patch(strategy_code, client)

        # 5. Bar-by-bar replay
        total_bars = len(timeline)
        for bar_idx, timestamp in enumerate(timeline):
            # Check cancellation
            if backtest_run.id in self.cancelled:
                break

            # Advance all symbols to this timestamp
            client.advance_to(timestamp)

            # Process pending SL/LIMIT orders against current bar
            client.process_pending_orders()

            # Execute one iteration of strategy logic
            try:
                iteration_fn()
            except _BarComplete:
                pass  # Normal: strategy called time.sleep(), we advance to next bar
            except Exception as e:
                # Log error but continue (strategy might recover)
                pass

            # Record equity snapshot
            client.record_equity(timestamp)

            # Emit progress every 100 bars (for SSE)
            if bar_idx % 100 == 0:
                self._emit_progress(backtest_run.id, bar_idx, total_bars)

        # 6. Force-close open positions at last bar
        client.close_all_positions_at_end()

        # 7. Final equity snapshot
        if timeline:
            client.record_equity(timeline[-1])

        # 8. Calculate statistics
        metrics = calculate_metrics(
            trades=client.trades,
            equity_curve=client.equity_curve,
            initial_capital=float(backtest_run.initial_capital),
            interval=backtest_run.interval,
        )

        return {
            'metrics': metrics,
            'trades': client.trades,
            'equity_curve': client.equity_curve,
            'total_bars': total_bars,
        }

    def cancel(self, backtest_id):
        self.cancelled.add(backtest_id)

    def _emit_progress(self, backtest_id, current_bar, total_bars):
        """Emit progress via Socket.IO for real-time UI updates."""
        try:
            from extensions import socketio
            progress = round(current_bar / total_bars * 100, 1)
            socketio.emit('backtest_progress', {
                'backtest_id': backtest_id,
                'progress': progress,
                'current_bar': current_bar,
                'total_bars': total_bars,
            })
        except Exception:
            pass  # Non-critical


class _BarComplete(Exception):
    """Raised when strategy calls time.sleep() — signals engine to advance to next bar."""
    pass
```

---

### Step 4 — Strategy Patcher

**New file**: `services/backtest_patcher.py`

Transforms live strategy code to run in backtest mode. Two approaches (use simpler first, upgrade to AST later):

#### Approach A: Regex + Namespace Injection (simpler, ship first)

```python
class StrategyPatcher:
    """
    Transform live strategy code for backtest execution.

    Approach: Inject a modified namespace where:
    - `from openalgo import api` is intercepted
    - `api(...)` constructor returns the BacktestClient
    - `time.sleep(...)` raises _BarComplete to yield control
    - `datetime.now()` returns current bar timestamp
    - The while-True loop body is extracted as a single-iteration function
    """

    def patch(self, source_code, client):
        """
        Returns a callable that executes one iteration of the strategy.
        """
        import re

        # Remove openalgo imports (we inject our own)
        code = re.sub(r'from\s+openalgo\s+import\s+api', '# [backtest] openalgo import intercepted', source_code)
        code = re.sub(r'import\s+openalgo', '# [backtest] openalgo import intercepted', code)

        # Replace while True loop with single iteration
        # Pattern: find the main while True block and extract its body
        code = self._extract_loop_body(code)

        # Build namespace
        namespace = {
            '__builtins__': __builtins__,
            'api': lambda **kwargs: client,  # intercept api() constructor
            'pd': __import__('pandas'),
            'np': __import__('numpy'),
            'os': self._safe_os(),
            'time': self._backtest_time_module(client),
            'datetime': __import__('datetime'),
            'json': __import__('json'),
            'math': __import__('math'),
        }

        # Execute the patched code to define functions
        exec(compile(code, '<backtest_strategy>', 'exec'), namespace)

        # Return the iteration function
        if '_backtest_iteration' in namespace:
            return namespace['_backtest_iteration']

        # Fallback: look for common entry points
        for name in ['main', 'run', 'strategy', 'execute']:
            if name in namespace and callable(namespace[name]):
                return namespace[name]

        raise ValueError("Could not find strategy entry point. "
                         "Strategy must have a main(), run(), or while True loop.")

    def _extract_loop_body(self, code):
        """
        Find the innermost while True loop and convert it to a function.

        Transforms:
            while True:
                ... strategy logic ...
                time.sleep(15)

        Into:
            def _backtest_iteration():
                ... strategy logic ...
                # time.sleep removed
        """
        import textwrap
        lines = code.split('\n')
        result = []
        in_while_loop = False
        while_indent = 0
        loop_body = []

        for line in lines:
            stripped = line.lstrip()
            indent = len(line) - len(stripped)

            if not in_while_loop:
                # Check for while True pattern
                if re.match(r'while\s+(True|1)\s*:', stripped):
                    in_while_loop = True
                    while_indent = indent
                    result.append(' ' * indent + 'def _backtest_iteration():')
                    continue
                result.append(line)
            else:
                if stripped == '' or indent > while_indent:
                    # Inside while loop body
                    # Skip time.sleep() calls
                    if re.match(r'time\.sleep\s*\(', stripped):
                        continue
                    result.append(line)
                else:
                    # Exited while loop
                    in_while_loop = False
                    result.append(line)

        return '\n'.join(result)

    def _backtest_time_module(self, client):
        """Create a mock time module where sleep() raises _BarComplete."""
        import types
        mock_time = types.ModuleType('time')
        mock_time.sleep = lambda *args: (_ for _ in ()).throw(_BarComplete())
        mock_time.time = lambda: client.current_timestamp or 0
        return mock_time

    def _safe_os(self):
        """Create a restricted os module (allow getenv, block filesystem writes)."""
        import types
        mock_os = types.ModuleType('os')
        mock_os.getenv = __import__('os').getenv
        mock_os.environ = __import__('os').environ
        mock_os.path = __import__('os').path
        return mock_os
```

#### Approach B: AST-Based (future upgrade for robustness)

For strategies with complex patterns (nested loops, generators, async), upgrade to `ast` module:
- Parse source code into AST
- Walk the tree and transform nodes
- Replace `time.sleep()` calls with `raise _BarComplete()`
- Replace `datetime.now()` with `client.current_time()`
- Extract loop bodies into functions
- Recompile modified AST

This is more robust but more complex. Ship Approach A first.

---

### Step 5 — Performance Metrics Calculator

**New file**: `services/backtest_metrics.py`

```python
import numpy as np
import pandas as pd


def calculate_metrics(trades, equity_curve, initial_capital, interval):
    """
    Calculate all performance metrics from backtest results.

    Args:
        trades: list of trade dicts from BacktestClient
        equity_curve: list of {timestamp, equity, drawdown} dicts
        initial_capital: starting capital (float)
        interval: bar interval string ('1m', '5m', '15m', '30m', '1h', 'D')

    Returns:
        dict with all computed metrics
    """
    if not equity_curve:
        return _empty_metrics()

    equity = pd.Series([e['equity'] for e in equity_curve])
    returns = equity.pct_change().dropna()

    # Annualization factor (trading bars per year)
    bars_per_year = {
        '1m': 252 * 375,   # 375 minutes per trading day
        '5m': 252 * 75,
        '15m': 252 * 25,
        '30m': 252 * 12,
        '1h': 252 * 6,
        'D': 252,
    }.get(interval, 252)

    metrics = {}

    # ── Return Metrics ──
    final_equity = equity.iloc[-1]
    metrics['final_capital'] = round(float(final_equity), 2)
    metrics['total_return_pct'] = round((final_equity - initial_capital) / initial_capital * 100, 4)

    # CAGR
    total_bars = len(equity)
    if total_bars > 1 and final_equity > 0 and initial_capital > 0:
        years = total_bars / bars_per_year
        if years > 0:
            metrics['cagr'] = round(((final_equity / initial_capital) ** (1 / years) - 1) * 100, 4)
        else:
            metrics['cagr'] = 0
    else:
        metrics['cagr'] = 0

    # ── Risk Metrics ──
    if len(returns) > 1 and returns.std() > 0:
        metrics['sharpe_ratio'] = round(float(returns.mean() / returns.std() * np.sqrt(bars_per_year)), 4)
    else:
        metrics['sharpe_ratio'] = 0

    downside_returns = returns[returns < 0]
    if len(downside_returns) > 1 and downside_returns.std() > 0:
        metrics['sortino_ratio'] = round(float(returns.mean() / downside_returns.std() * np.sqrt(bars_per_year)), 4)
    else:
        metrics['sortino_ratio'] = 0

    metrics['max_drawdown_pct'] = round(max((e['drawdown'] for e in equity_curve), default=0) * 100, 4)

    if metrics['max_drawdown_pct'] > 0:
        metrics['calmar_ratio'] = round(metrics['cagr'] / metrics['max_drawdown_pct'], 4)
    else:
        metrics['calmar_ratio'] = 0

    # ── Trade Metrics ──
    if trades:
        wins = [t for t in trades if t['net_pnl'] > 0]
        losses = [t for t in trades if t['net_pnl'] <= 0]

        metrics['total_trades'] = len(trades)
        metrics['winning_trades'] = len(wins)
        metrics['losing_trades'] = len(losses)
        metrics['win_rate'] = round(len(wins) / len(trades) * 100, 4) if trades else 0

        gross_profit = sum(t['net_pnl'] for t in wins)
        gross_loss = abs(sum(t['net_pnl'] for t in losses))

        metrics['profit_factor'] = round(gross_profit / gross_loss, 4) if gross_loss > 0 else float('inf')
        metrics['avg_win'] = round(np.mean([t['net_pnl'] for t in wins]), 2) if wins else 0
        metrics['avg_loss'] = round(np.mean([t['net_pnl'] for t in losses]), 2) if losses else 0
        metrics['max_win'] = round(max([t['net_pnl'] for t in wins]), 2) if wins else 0
        metrics['max_loss'] = round(min([t['net_pnl'] for t in losses]), 2) if losses else 0
        metrics['expectancy'] = round(
            (metrics['win_rate'] / 100 * metrics['avg_win']) +
            ((1 - metrics['win_rate'] / 100) * metrics['avg_loss']),
            2
        )
        metrics['avg_holding_bars'] = round(np.mean([t['bars_held'] for t in trades]))

        # Total commissions and slippage
        metrics['total_commission'] = round(sum(t.get('commission', 0) for t in trades), 2)
        metrics['total_slippage'] = round(sum(t.get('slippage_cost', 0) for t in trades), 2)
    else:
        metrics.update({
            'total_trades': 0, 'winning_trades': 0, 'losing_trades': 0,
            'win_rate': 0, 'profit_factor': 0, 'avg_win': 0, 'avg_loss': 0,
            'max_win': 0, 'max_loss': 0, 'expectancy': 0, 'avg_holding_bars': 0,
            'total_commission': 0, 'total_slippage': 0,
        })

    # ── Monthly Returns (for calendar heatmap) ──
    try:
        equity_ts = pd.Series(
            [e['equity'] for e in equity_curve],
            index=pd.to_datetime([e['timestamp'] for e in equity_curve], unit='s')
        )
        monthly = equity_ts.resample('M').last().pct_change().dropna() * 100
        metrics['monthly_returns'] = {
            str(k.date()): round(float(v), 2) for k, v in monthly.items()
        }
    except Exception:
        metrics['monthly_returns'] = {}

    return metrics


def _empty_metrics():
    """Return empty metrics when no data is available."""
    return {
        'final_capital': 0, 'total_return_pct': 0, 'cagr': 0,
        'sharpe_ratio': 0, 'sortino_ratio': 0, 'max_drawdown_pct': 0,
        'calmar_ratio': 0, 'total_trades': 0, 'winning_trades': 0,
        'losing_trades': 0, 'win_rate': 0, 'profit_factor': 0,
        'avg_win': 0, 'avg_loss': 0, 'max_win': 0, 'max_loss': 0,
        'expectancy': 0, 'avg_holding_bars': 0,
        'total_commission': 0, 'total_slippage': 0,
        'monthly_returns': {},
    }
```

---

### Step 6 — Blueprint & API Endpoints

**New file**: `blueprints/backtest.py`

#### Blueprint Routes (UI)

| Route | Method | Purpose |
|-------|--------|---------|
| `/backtest` | GET | Backtest dashboard (list all runs) |
| `/backtest/new` | GET | New backtest configuration page |
| `/backtest/<id>` | GET | View backtest results |
| `/backtest/compare` | GET | Compare multiple backtests |

#### API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/backtest/api/run` | POST | Start a new backtest |
| `/backtest/api/status/<id>` | GET | Get status + progress |
| `/backtest/api/results/<id>` | GET | Full results (metrics + trades + equity curve) |
| `/backtest/api/cancel/<id>` | POST | Cancel running backtest |
| `/backtest/api/list` | GET | List all backtests for user |
| `/backtest/api/delete/<id>` | DELETE | Delete backtest and its trades |
| `/backtest/api/export/<id>` | GET | Export results as CSV/JSON |
| `/backtest/api/check-data` | POST | Check Historify data availability for symbols |
| `/backtest/api/forward-test/<id>` | POST | Deploy strategy to Sandbox for forward testing |
| `/backtest/api/events` | GET (SSE) | Real-time progress updates |

#### Execution Model

Run backtests as **background threads** (not subprocesses — they need access to DuckDB in-process).

```python
from concurrent.futures import ThreadPoolExecutor

# Max 3 concurrent backtests
backtest_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix='backtest')

@backtest_bp.route('/api/run', methods=['POST'])
@login_required
def run_backtest():
    config = request.json

    # Validate configuration
    # ...

    # Create BacktestRun record
    run = BacktestRun(id=generate_id(), user_id=current_user.id, ...)
    db.session.add(run)
    db.session.commit()

    # Submit to thread pool
    future = backtest_executor.submit(_run_backtest_task, run.id, config['strategy_code'])

    return {'status': 'success', 'backtest_id': run.id}


def _run_backtest_task(backtest_id, strategy_code):
    """Background task that runs the backtest."""
    run = BacktestRun.query.get(backtest_id)
    run.status = 'running'
    run.started_at = datetime.now()
    db.session.commit()

    try:
        engine = BacktestEngine()
        results = engine.run(run, strategy_code)

        # Save results
        run.status = 'completed'
        run.completed_at = datetime.now()
        run.duration_ms = int((run.completed_at - run.started_at).total_seconds() * 1000)

        # Populate all metric columns from results['metrics']
        for key, value in results['metrics'].items():
            if hasattr(run, key):
                setattr(run, key, value)

        run.equity_curve_json = json.dumps(results['equity_curve'])
        run.monthly_returns_json = json.dumps(results['metrics'].get('monthly_returns', {}))

        # Save individual trades
        for trade in results['trades']:
            bt_trade = BacktestTrade(backtest_id=backtest_id, **trade)
            db.session.add(bt_trade)

        db.session.commit()

        # Notify UI
        socketio.emit('backtest_complete', {'backtest_id': backtest_id, 'status': 'completed'})

    except Exception as e:
        run.status = 'failed'
        run.error_message = str(e)
        run.completed_at = datetime.now()
        db.session.commit()
        socketio.emit('backtest_complete', {'backtest_id': backtest_id, 'status': 'failed', 'error': str(e)})
```

---

## Phase 2: Frontend

### Step 7 — React Pages

**New files to create:**

```
frontend/src/pages/backtest/
    BacktestIndex.tsx        # List all backtests with status
    NewBacktest.tsx           # Configuration + code editor
    BacktestResults.tsx       # Full results dashboard
    CompareBacktests.tsx      # Side-by-side comparison

frontend/src/api/backtest.ts         # API client functions
frontend/src/types/backtest.ts       # TypeScript type definitions
```

#### BacktestIndex.tsx

Table of past backtests showing:
- Name, symbols, date range, interval
- Status badges: `pending`, `running` (with progress %), `completed`, `failed`
- Key metrics columns: Return %, Sharpe, Max DD, Win Rate, Trades
- SSE-based real-time status updates (reuse pattern from PythonStrategyIndex.tsx)
- Actions: View Results, Re-run, Compare, Delete

#### NewBacktest.tsx

Configuration form with:

```
+--------------------------------------------------+
| New Backtest                                      |
+--------------------------------------------------+
|                                                   |
| Strategy: [Select existing v] or [Write new]      |
|                                                   |
| +-----------------------------------------------+ |
| | # Python Editor (CodeMirror)                  | |
| | from openalgo import api                      | |
| | client = api(api_key='...', host='...')       | |
| | ...                                           | |
| +-----------------------------------------------+ |
|                                                   |
| -- Configuration -------------------------------- |
|                                                   |
| Symbols:   [SBIN:NSE] [+ Add]                    |
| Interval:  [5m v]                                 |
| Period:    [2024-01-01] to [2024-12-31]           |
| Capital:   [Rs.10,00,000]                         |
|                                                   |
| -- Costs ---------------------------------------- |
|                                                   |
| Slippage:     [0.05] %                            |
| Commission:   [Rs.20] per order                   |
| Data Source:  (*) Local DB  ( ) Broker API        |
|                                                   |
|          [> Run Backtest]                         |
|                                                   |
| -- Data Availability -------------------------    |
| SBIN:NSE 1m: 2023-06-01 to 2025-02-28 (450K) OK |
| Missing: None                                     |
+--------------------------------------------------+
```

Key features:
- Strategy selector dropdown (loads from existing Python strategies)
- CodeMirror Python editor (reuse existing `PythonEditor` component)
- Multi-symbol input with exchange selector
- Date range pickers
- Data availability check (queries Historify `data_catalog` before run)
- Real-time progress after submission (SSE)

#### BacktestResults.tsx

Full results dashboard:

```
+--------------------------------------------------+
| Backtest: EMA Crossover - SBIN 5m                 |
| Period: 2024-01-01 to 2024-12-31                  |
+--------------------------------------------------+
|                                                   |
| +------+ +------+ +------+ +------+ +--------+   |
| |Return| |Sharpe| |MaxDD | |Wins  | |Profit  |   |
| |+24.3%| | 1.82 | |-8.2% | | 58%  | |Factor  |   |
| |      | |      | |      | |      | |  1.74  |   |
| +------+ +------+ +------+ +------+ +--------+   |
|                                                   |
| -- Equity Curve --------------------------------  |
| +-----------------------------------------------+ |
| | Lightweight Charts: equity line + DD overlay  | |
| +-----------------------------------------------+ |
|                                                   |
| -- Monthly Returns Heatmap ---------------------  |
| +-----------------------------------------------+ |
| | Jan  Feb  Mar  Apr  May  Jun ...              | |
| | +2.1 -0.8 +3.4 +1.2 -1.5 +4.2 ...           | |
| +-----------------------------------------------+ |
|                                                   |
| -- Trade Log -----------------------------------  |
| +-----------------------------------------------+ |
| | #  Symbol  Action  Entry  Exit  P&L  Bars     | |
| | 1  SBIN    BUY     780    812   +32  14       | |
| | 2  SBIN    SELL    812    795   +17   8       | |
| | ...                                           | |
| +-----------------------------------------------+ |
|                                                   |
| [Export CSV] [Re-run] [Forward Test in Sandbox]   |
|                                                   |
+--------------------------------------------------+
```

Components used:
- `lightweight-charts` (already in deps) for equity curve + drawdown overlay
- CSS grid heatmap for monthly returns (green/red cells, no extra dependency)
- shadcn `Table` for trade log with column sorting and filtering
- shadcn `Card` for metric summary cards
- Buttons: Export CSV, Re-run (copies config to NewBacktest), Forward Test

#### CompareBacktests.tsx

Side-by-side comparison of 2-4 backtests:
- Overlaid equity curves on same chart
- Metric comparison table (rows = metrics, columns = backtests)
- Select backtests via checkboxes on BacktestIndex

---

### Step 8 — Frontend API Layer & Routes

#### API Client (`frontend/src/api/backtest.ts`)

```typescript
import { webClient, apiClient } from './client'

export const backtestApi = {
  run: (config: BacktestConfig) =>
    webClient.post('/backtest/api/run', config),

  getStatus: (id: string) =>
    webClient.get(`/backtest/api/status/${id}`),

  getResults: (id: string) =>
    webClient.get(`/backtest/api/results/${id}`),

  cancel: (id: string) =>
    webClient.post(`/backtest/api/cancel/${id}`),

  list: () =>
    webClient.get('/backtest/api/list'),

  delete: (id: string) =>
    webClient.delete(`/backtest/api/delete/${id}`),

  exportCSV: (id: string) =>
    webClient.get(`/backtest/api/export/${id}`, { responseType: 'blob' }),

  checkData: (symbols: SymbolConfig[], interval: string, startDate: string, endDate: string) =>
    webClient.post('/backtest/api/check-data', { symbols, interval, startDate, endDate }),

  forwardTest: (id: string) =>
    webClient.post(`/backtest/api/forward-test/${id}`),

  streamEvents: () =>
    new EventSource('/backtest/api/events'),
}
```

#### TypeScript Types (`frontend/src/types/backtest.ts`)

```typescript
export interface BacktestConfig {
  name: string
  strategy_id?: string
  strategy_code: string
  symbols: { symbol: string; exchange: string }[]
  start_date: string
  end_date: string
  interval: string
  initial_capital: number
  slippage_pct: number
  commission_per_order: number
  data_source: 'db' | 'api'
}

export interface BacktestRun {
  id: string
  name: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  symbols: { symbol: string; exchange: string }[]
  start_date: string
  end_date: string
  interval: string
  initial_capital: number
  // Metrics
  total_return_pct: number
  cagr: number
  sharpe_ratio: number
  sortino_ratio: number
  max_drawdown_pct: number
  calmar_ratio: number
  win_rate: number
  profit_factor: number
  total_trades: number
  // ... other fields
  created_at: string
  duration_ms: number
  error_message?: string
}

export interface BacktestTrade {
  trade_num: number
  symbol: string
  exchange: string
  action: 'LONG' | 'SHORT'
  quantity: number
  entry_price: number
  exit_price: number
  entry_time: string
  exit_time: string
  pnl: number
  net_pnl: number
  bars_held: number
}

export interface EquityCurvePoint {
  timestamp: number
  equity: number
  drawdown: number
}

export interface DataAvailability {
  symbol: string
  exchange: string
  interval: string
  has_data: boolean
  first_date: string
  last_date: string
  record_count: number
}
```

#### Routes (add to `frontend/src/App.tsx`)

```typescript
const BacktestIndex = lazy(() => import('@/pages/backtest/BacktestIndex'))
const NewBacktest = lazy(() => import('@/pages/backtest/NewBacktest'))
const BacktestResults = lazy(() => import('@/pages/backtest/BacktestResults'))
const CompareBacktests = lazy(() => import('@/pages/backtest/CompareBacktests'))

// Inside protected routes:
<Route path="/backtest" element={<BacktestIndex />} />
<Route path="/backtest/new" element={<NewBacktest />} />
<Route path="/backtest/:id" element={<BacktestResults />} />
<Route path="/backtest/compare" element={<CompareBacktests />} />
```

#### Navigation (add to `frontend/src/config/navigation.ts`)

Add "Backtest" item under Strategies section, with icon `FlaskConical` or `TestTube` from lucide-react.

---

## Phase 3: Sandbox Bridge (Backtest to Forward Test to Live)

### Step 9 — One-Click Forward Test

On the BacktestResults page, a "Forward Test in Sandbox" button that:

1. Copies the strategy code to Python Strategies (`strategies/scripts/`)
2. Auto-enables Analyzer mode (sandbox)
3. Starts the strategy with market-hours scheduler
4. Links backtest results to the forward test for comparison

```python
@backtest_bp.route('/api/forward-test/<backtest_id>', methods=['POST'])
@login_required
def start_forward_test(backtest_id):
    run = BacktestRun.query.get(backtest_id)
    if not run:
        return {'status': 'error', 'message': 'Backtest not found'}, 404

    # 1. Save strategy as Python Strategy
    strategy_id = save_as_python_strategy(
        code=run.strategy_code,
        name=f"FWD-{run.name}",
        schedule={'start_time': '09:15', 'stop_time': '15:30', 'days': ['mon','tue','wed','thu','fri']}
    )

    # 2. Enable analyzer mode
    from database.settings_db import update_setting
    update_setting('analyze_mode', 'true')

    # 3. Start strategy
    from blueprints.python_strategy import start_strategy
    start_strategy(strategy_id)

    return {
        'status': 'success',
        'strategy_id': strategy_id,
        'message': 'Strategy deployed to Sandbox mode. Monitor at /python'
    }
```

### Step 10 — Go Live

From forward test results (Python Strategy page), a "Go Live" button that:
1. Disables analyzer mode
2. Shows confirmation modal with warning
3. Restarts the same strategy in live mode

---

## Phase 4: Advanced Features (Post-MVP)

### Step 11 — Parameter Optimization

Grid search across parameter combinations:

```python
# User defines parameter grid in UI:
params = {
    'fast_period': [5, 10, 15, 20],
    'slow_period': [20, 30, 50],
}
# Engine runs all 12 combinations as separate backtests
# Results shown as heatmap (rows=fast_period, cols=slow_period, color=return%)
# Overfitting warning: use walk-forward validation (train/test split)
```

### Step 12 — Multi-Symbol Portfolio Backtest

Support strategies that trade multiple symbols with:
- Shared capital pool
- Portfolio-level drawdown tracking
- Correlation analysis between strategy returns
- Per-symbol allocation limits

### Step 13 — Benchmark Comparison

Compare backtest returns against:
- Buy & hold (same symbol)
- Nifty 50 index
- Fixed deposit rate (7% annualized)
- Other backtests (overlay equity curves)

---

## File Summary — What Gets Created

```
# Backend (Python)
database/backtest_db.py              # Schema + init (BacktestRun, BacktestTrade)
services/backtest_engine.py          # Bar replay orchestrator
services/backtest_client.py          # Mock openalgo.api client (drop-in replacement)
services/backtest_patcher.py         # Strategy code transformation (regex + namespace injection)
services/backtest_metrics.py         # Performance metric calculations
blueprints/backtest.py               # UI routes + API endpoints + SSE progress

# Frontend (React/TypeScript)
frontend/src/api/backtest.ts         # API client functions
frontend/src/types/backtest.ts       # TypeScript type definitions
frontend/src/pages/backtest/
  BacktestIndex.tsx                  # Dashboard listing all backtests
  NewBacktest.tsx                    # Configuration form + code editor
  BacktestResults.tsx                # Results visualization (charts + metrics + trades)
  CompareBacktests.tsx               # Side-by-side comparison

# Database
db/backtest.db                       # Auto-created on first run

# Migrations
upgrade/migrate_backtest.py          # DB initialization script (idempotent)
```

---

## Files Modified

```
app.py                                # Add init_backtest_db() to parallel DB init (~line 484)
                                       # Register backtest blueprint (~line 240)
                                       # Add DB session cleanup for backtest DB (~line 650)

frontend/src/App.tsx                   # Add backtest routes (4 lazy imports + Route elements)
frontend/src/config/navigation.ts      # Add "Backtest" nav item under Strategies section
```

---

## Implementation Order

| Step | What | Depends On | Effort |
|------|------|-----------|--------|
| 1 | `database/backtest_db.py` | Nothing | 1 day |
| 2 | `services/backtest_client.py` | Step 1 | 3 days |
| 3 | `services/backtest_engine.py` | Step 2 | 3 days |
| 4 | `services/backtest_patcher.py` | Step 3 | 2 days |
| 5 | `services/backtest_metrics.py` | Step 3 | 1 day |
| 6 | `blueprints/backtest.py` | Steps 1-5 | 2 days |
| 7 | Frontend pages (4 files + api + types) | Step 6 | 4 days |
| 8 | Route + nav integration | Step 7 | 0.5 day |
| 9 | Forward test bridge | Steps 6, 7 | 1 day |
| 10 | Go live button | Step 9 | 0.5 day |
| 11-13 | Advanced features (optimization, portfolio, benchmarks) | All above | 5+ days |

**Total MVP (Steps 1-10): ~18 working days**

---

## Key Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| **Strategy patching fragility** | Start with regex approach (Step 4 Approach A). Test with all example strategies in `strategies/examples/` and `examples/python/`. Fall back to subprocess mode with env-var SDK interception if needed |
| **Look-ahead bias** | `BacktestClient.history()` strictly returns data up to current bar only. Code review checkpoint |
| **Slow on 1m data (90K+ bars)** | DuckDB vectorized queries are fast (<50ms). Profile and optimize hot paths. Add progress bar. Downsample equity curve if >100K points |
| **Strategy uses external APIs** | Document limitation: backtest only works with `openalgo` SDK calls. External HTTP calls will fail. Show clear error message |
| **Memory for large equity curves** | Downsample equity curve (every Nth bar) if >100K points. Full data stays in DB |
| **Concurrent backtests** | ThreadPoolExecutor with max 3 workers. Queue additional requests. Show "queued" status in UI |
| **DuckDB thread safety** | DuckDB supports concurrent reads. Each backtest thread gets its own connection |
| **Strategy infinite loops** | Timeout per backtest (configurable, default 5 minutes). Kill thread on timeout |

---

## Testing Strategy

### Unit Tests
- `test/test_backtest_client.py`: Test all SDK methods against known historical data
- `test/test_backtest_metrics.py`: Test metric calculations with known trade sequences
- `test/test_backtest_patcher.py`: Test strategy patching with various code patterns

### Integration Tests
- Run backtests with example strategies (`ema_crossover.py`, `supertrend.py`)
- Compare results with VectorBT reference implementation (`backtesting_vectorbt.py`)
- Verify no look-ahead bias: results should be identical when run bar-by-bar vs full dataset

### Manual Testing
- Run via UI at `/backtest/new`
- Verify equity curve chart renders correctly
- Verify trade log matches expected fills
- Test cancellation mid-run
- Test with missing data (should show clear error)
- Test forward test deployment to sandbox
