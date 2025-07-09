# Enhanced Trade Management Module - Implementation Plan

## Overview

This document outlines the comprehensive plan for implementing an enhanced trade management module in OpenAlgo that adds stop-loss, target, and trailing stop-loss functionality with real-time LTP monitoring.

## Technical Implementation Details

## Current State Analysis

### Existing Architecture
- **Order Management**: Orders are placed via REST API and tracked through broker APIs
- **Position Tracking**: Positions are fetched real-time from brokers, not stored locally
- **WebSocket**: Provides real-time market data (LTP, Quote, Depth)
- **Strategy Management**: Webhook-based with time controls, no price-based exits
- **Database**: No persistent storage of trades or position entry prices

### Key Gaps
1. No server-side monitoring of stop-loss or target prices
2. No persistent tracking of trade entry prices
3. No automated exit order placement based on price conditions
4. No trailing stop-loss functionality
5. No UI for managing active trades with SL/Target

## Proposed Architecture

### 1. Database Schema Changes

#### New Tables

```sql
-- Active trades table to track trades with SL/Target
CREATE TABLE active_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id VARCHAR(50) NOT NULL,
    strategy_id INTEGER,
    order_id VARCHAR(100) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    exchange VARCHAR(10) NOT NULL,
    product_type VARCHAR(10) NOT NULL,
    trade_type VARCHAR(10) NOT NULL,  -- 'LONG' or 'SHORT'
    entry_price DECIMAL(10, 2),
    quantity INTEGER NOT NULL,
    stop_loss DECIMAL(10, 2),
    target DECIMAL(10, 2),
    trailing_stop_loss BOOLEAN DEFAULT FALSE,
    trailing_stop_value DECIMAL(10, 2),  -- Points or percentage
    trailing_stop_type VARCHAR(10),  -- 'POINTS' or 'PERCENT'
    current_trailing_sl DECIMAL(10, 2),  -- Current calculated trailing SL
    highest_price DECIMAL(10, 2),  -- For LONG trades
    lowest_price DECIMAL(10, 2),   -- For SHORT trades
    current_ltp DECIMAL(10, 2),    -- Last known LTP for state recovery
    last_sync TIMESTAMP,            -- Last state sync timestamp
    websocket_subscribed BOOLEAN DEFAULT FALSE,  -- Subscription status
    status VARCHAR(20) DEFAULT 'ACTIVE',  -- 'ACTIVE', 'CLOSED', 'SL_HIT', 'TARGET_HIT'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMP,
    exit_price DECIMAL(10, 2),
    exit_order_id VARCHAR(100),
    pnl DECIMAL(10, 2),
    FOREIGN KEY (strategy_id) REFERENCES strategies(id) ON DELETE SET NULL,
    INDEX idx_active_trades_status (status),
    INDEX idx_active_trades_user_symbol (user_id, symbol, status)
);

-- Trade monitoring logs
CREATE TABLE trade_monitor_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL,
    ltp DECIMAL(10, 2) NOT NULL,
    action VARCHAR(50),  -- 'SL_TRIGGERED', 'TARGET_TRIGGERED', 'TRAILING_SL_UPDATED'
    details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (trade_id) REFERENCES active_trades(id) ON DELETE CASCADE
);
```

#### Updates to Existing Tables

```sql
-- Add columns to strategies table for risk management
ALTER TABLE strategies ADD COLUMN enable_sl BOOLEAN DEFAULT FALSE;
ALTER TABLE strategies ADD COLUMN sl_type VARCHAR(10);  -- 'PERCENT' or 'POINTS'
ALTER TABLE strategies ADD COLUMN sl_value DECIMAL(10, 2);
ALTER TABLE strategies ADD COLUMN enable_target BOOLEAN DEFAULT FALSE;
ALTER TABLE strategies ADD COLUMN target_type VARCHAR(10);  -- 'PERCENT' or 'POINTS'
ALTER TABLE strategies ADD COLUMN target_value DECIMAL(10, 2);
ALTER TABLE strategies ADD COLUMN enable_trailing_sl BOOLEAN DEFAULT FALSE;
ALTER TABLE strategies ADD COLUMN trailing_sl_type VARCHAR(10);  -- 'PERCENT' or 'POINTS'
ALTER TABLE strategies ADD COLUMN trailing_sl_value DECIMAL(10, 2);

-- Add columns for fund allocation
ALTER TABLE strategies ADD COLUMN allocated_funds DECIMAL(15, 2) DEFAULT 0;
ALTER TABLE strategies ADD COLUMN position_size_type VARCHAR(20);  -- 'FIXED_QUANTITY', 'FIXED_VALUE', 'PERCENT_ALLOCATION'
ALTER TABLE strategies ADD COLUMN position_size_value DECIMAL(15, 2);
ALTER TABLE strategies ADD COLUMN max_open_positions INTEGER DEFAULT 5;
ALTER TABLE strategies ADD COLUMN daily_loss_limit DECIMAL(15, 2);
ALTER TABLE strategies ADD COLUMN current_daily_pnl DECIMAL(15, 2) DEFAULT 0;
ALTER TABLE strategies ADD COLUMN last_pnl_reset_date DATE;

-- Add columns for portfolio-level risk management
ALTER TABLE strategies ADD COLUMN enable_portfolio_sl BOOLEAN DEFAULT FALSE;
ALTER TABLE strategies ADD COLUMN portfolio_sl_type VARCHAR(10);  -- 'AMOUNT' or 'PERCENT'
ALTER TABLE strategies ADD COLUMN portfolio_sl_value DECIMAL(15, 2);
ALTER TABLE strategies ADD COLUMN enable_portfolio_target BOOLEAN DEFAULT FALSE;
ALTER TABLE strategies ADD COLUMN portfolio_target_type VARCHAR(10);  -- 'AMOUNT' or 'PERCENT'
ALTER TABLE strategies ADD COLUMN portfolio_target_value DECIMAL(15, 2);
ALTER TABLE strategies ADD COLUMN enable_portfolio_trailing_sl BOOLEAN DEFAULT FALSE;
ALTER TABLE strategies ADD COLUMN portfolio_trailing_type VARCHAR(10);  -- 'AMOUNT' or 'PERCENT'
ALTER TABLE strategies ADD COLUMN portfolio_trailing_value DECIMAL(15, 2);
ALTER TABLE strategies ADD COLUMN portfolio_highest_pnl DECIMAL(15, 2) DEFAULT 0;
ALTER TABLE strategies ADD COLUMN portfolio_current_trailing_sl DECIMAL(15, 2);
```

#### New Fund Allocation Table

```sql
-- Strategy fund usage tracking
CREATE TABLE strategy_fund_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id INTEGER NOT NULL,
    date DATE NOT NULL,
    opening_balance DECIMAL(15, 2),
    funds_deployed DECIMAL(15, 2) DEFAULT 0,
    funds_available DECIMAL(15, 2),
    total_trades INTEGER DEFAULT 0,
    profitable_trades INTEGER DEFAULT 0,
    loss_trades INTEGER DEFAULT 0,
    total_pnl DECIMAL(15, 2) DEFAULT 0,
    max_drawdown DECIMAL(15, 2) DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (strategy_id) REFERENCES strategies(id) ON DELETE CASCADE,
    UNIQUE KEY idx_strategy_date (strategy_id, date)
);
```

### 2. Trade Monitoring Service

#### Core Components

**TradeMonitor Service** (`services/trade_monitor_service.py`)
- Background service that monitors active trades
- Subscribes to WebSocket for real-time LTP updates
- Checks SL/Target conditions
- Updates trailing stop-loss
- Triggers exit orders when conditions are met

**Integration with Existing Order Flow:**

1. **Order Placement Hook with Position Sizing**
   ```python
   # Calculate position size based on strategy settings
   def calculate_position_size(strategy, symbol_price):
       if not strategy.allocated_funds or strategy.allocated_funds <= 0:
           raise ValueError("No funds allocated to strategy")
       
       # Check daily loss limit
       if strategy.daily_loss_limit and strategy.current_daily_pnl <= -strategy.daily_loss_limit:
           raise ValueError("Daily loss limit reached")
       
       # Check max open positions
       active_trades = get_active_trades_count(strategy.id)
       if active_trades >= strategy.max_open_positions:
           raise ValueError("Max open positions reached")
       
       # Calculate position size
       if strategy.position_size_type == 'FIXED_QUANTITY':
           quantity = int(strategy.position_size_value)
       
       elif strategy.position_size_type == 'FIXED_VALUE':
           # Use fixed money amount (e.g., ₹50,000)
           quantity = int(strategy.position_size_value / symbol_price)
       
       elif strategy.position_size_type == 'PERCENT_ALLOCATION':
           # Use percentage of allocated funds
           available_funds = get_available_funds(strategy.id)
           trade_value = available_funds * (strategy.position_size_value / 100)
           quantity = int(trade_value / symbol_price)
       
       return quantity
   
   # In place_order_service.py, before order placement:
   if strategy and strategy.allocated_funds:
       # Get current price for position sizing
       ltp = get_ltp(symbol, exchange)
       quantity = calculate_position_size(strategy, ltp)
   
   # After successful order placement:
   if order_id and strategy.enable_sl or strategy.enable_target:
       # Create trade monitoring record
       create_trade_with_monitoring(
           order_id=order_id,
           symbol=symbol,
           exchange=exchange,
           quantity=quantity,
           strategy_id=strategy.id,
           sl_enabled=strategy.enable_sl,
           sl_type=strategy.sl_type,
           sl_value=strategy.sl_value,
           target_enabled=strategy.enable_target,
           target_type=strategy.target_type,
           target_value=strategy.target_value,
           trailing_enabled=strategy.enable_trailing_sl,
           trailing_type=strategy.trailing_sl_type,
           trailing_value=strategy.trailing_sl_value
       )
   ```

2. **Order Status Monitoring**
   ```python
   # Background task to check order completion
   def check_pending_orders():
       pending_trades = get_pending_trade_orders()
       for trade in pending_trades:
           status = get_order_status(trade.order_id)
           if status['order_status'] == 'complete':
               # Update trade with entry price
               update_trade_entry(
                   trade_id=trade.id,
                   entry_price=status['price'],
                   status='ACTIVE'
               )
               # Subscribe to WebSocket for LTP
               subscribe_symbol_ltp(trade.symbol, trade.exchange)
   ```

3. **LTP Processing Pipeline with Portfolio Monitoring**
   ```python
   class TradeMonitor:
       def on_ltp_update(self, symbol, exchange, ltp):
           # Get all active trades for this symbol
           active_trades = get_active_trades_for_symbol(symbol, exchange)
           strategies_to_check = set()
           
           for trade in active_trades:
               # Individual Trade Level Monitoring
               trade_exit_triggered = False
               
               # Check individual stop loss
               if trade.stop_loss and self.is_sl_triggered(trade, ltp):
                   self.execute_sl_exit(trade, 'INDIVIDUAL_SL')
                   trade_exit_triggered = True
               
               # Check individual target
               elif trade.target and self.is_target_triggered(trade, ltp):
                   self.execute_target_exit(trade, 'INDIVIDUAL_TARGET')
                   trade_exit_triggered = True
               
               # Update individual trailing stop loss
               elif trade.trailing_stop_loss:
                   self.update_individual_trailing_sl(trade, ltp)
               
               # Add strategy for portfolio-level check if trade wasn't exited
               if not trade_exit_triggered:
                   strategies_to_check.add(trade.strategy_id)
           
           # Portfolio Level Monitoring for affected strategies
           for strategy_id in strategies_to_check:
               self.check_portfolio_levels(strategy_id)
   
       def check_portfolio_levels(self, strategy_id):
           """Check portfolio-level SL/Target for the entire strategy"""
           strategy = get_strategy(strategy_id)
           if not strategy:
               return
           
           # Calculate current portfolio P&L
           portfolio_pnl = self.calculate_portfolio_pnl(strategy_id)
           allocated_funds = strategy.allocated_funds
           
           # Portfolio Stop Loss Check
           if strategy.enable_portfolio_sl:
               sl_breached = False
               
               if strategy.portfolio_sl_type == 'AMOUNT':
                   # Absolute amount loss (e.g., -₹10,000)
                   if portfolio_pnl <= -strategy.portfolio_sl_value:
                       sl_breached = True
               
               elif strategy.portfolio_sl_type == 'PERCENT':
                   # Percentage loss of allocated funds (e.g., -2% of ₹5,00,000 = -₹10,000)
                   sl_amount = allocated_funds * (strategy.portfolio_sl_value / 100)
                   if portfolio_pnl <= -sl_amount:
                       sl_breached = True
               
               if sl_breached:
                   self.execute_portfolio_sl(strategy_id, portfolio_pnl)
                   return  # Exit all, no need to check other levels
           
           # Portfolio Target Check
           if strategy.enable_portfolio_target:
               target_hit = False
               
               if strategy.portfolio_target_type == 'AMOUNT':
                   # Absolute amount profit (e.g., +₹15,000)
                   if portfolio_pnl >= strategy.portfolio_target_value:
                       target_hit = True
               
               elif strategy.portfolio_target_type == 'PERCENT':
                   # Percentage profit of allocated funds (e.g., +3% of ₹5,00,000 = +₹15,000)
                   target_amount = allocated_funds * (strategy.portfolio_target_value / 100)
                   if portfolio_pnl >= target_amount:
                       target_hit = True
               
               if target_hit:
                   self.execute_portfolio_target(strategy_id, portfolio_pnl)
                   return  # Exit all, no need to check trailing
           
           # Portfolio Trailing Stop Loss
           if strategy.enable_portfolio_trailing_sl:
               self.update_portfolio_trailing_sl(strategy_id, portfolio_pnl)
   
       def calculate_portfolio_pnl(self, strategy_id):
           """Calculate total unrealized P&L for all active trades in strategy"""
           active_trades = get_active_trades_for_strategy(strategy_id)
           total_pnl = 0
           
           for trade in active_trades:
               if trade.current_ltp and trade.entry_price:
                   if trade.trade_type == 'LONG':
                       trade_pnl = (trade.current_ltp - trade.entry_price) * trade.quantity
                   else:  # SHORT
                       trade_pnl = (trade.entry_price - trade.current_ltp) * trade.quantity
                   
                   total_pnl += trade_pnl
           
           return total_pnl
       
       def update_portfolio_trailing_sl(self, strategy_id, current_pnl):
           """Update portfolio-level trailing stop loss"""
           strategy = get_strategy(strategy_id)
           
           # Track highest portfolio P&L
           if current_pnl > strategy.portfolio_highest_pnl:
               strategy.portfolio_highest_pnl = current_pnl
               
               # Calculate new trailing SL level
               if strategy.portfolio_trailing_type == 'AMOUNT':
                   # Trail by absolute amount (e.g., ₹5,000 from peak)
                   new_trailing_sl = current_pnl - strategy.portfolio_trailing_value
               else:  # PERCENT
                   # Trail by percentage of allocated funds
                   trail_amount = strategy.allocated_funds * (strategy.portfolio_trailing_value / 100)
                   new_trailing_sl = current_pnl - trail_amount
               
               # Only update if new trailing SL is higher (less loss)
               if (strategy.portfolio_current_trailing_sl is None or 
                   new_trailing_sl > strategy.portfolio_current_trailing_sl):
                   strategy.portfolio_current_trailing_sl = new_trailing_sl
                   update_strategy_portfolio_state(strategy_id, {
                       'portfolio_highest_pnl': current_pnl,
                       'portfolio_current_trailing_sl': new_trailing_sl
                   })
           
           # Check if current P&L hit trailing SL
           if (strategy.portfolio_current_trailing_sl is not None and 
               current_pnl <= strategy.portfolio_current_trailing_sl):
               self.execute_portfolio_trailing_sl(strategy_id, current_pnl)
       
       def execute_portfolio_sl(self, strategy_id, portfolio_pnl):
           """Close all positions in strategy due to portfolio stop loss"""
           logger.warning(f"Portfolio SL triggered for strategy {strategy_id}: P&L {portfolio_pnl}")
           self.close_all_strategy_positions(strategy_id, 'PORTFOLIO_SL', portfolio_pnl)
       
       def execute_portfolio_target(self, strategy_id, portfolio_pnl):
           """Close all positions in strategy due to portfolio target"""
           logger.info(f"Portfolio Target hit for strategy {strategy_id}: P&L {portfolio_pnl}")
           self.close_all_strategy_positions(strategy_id, 'PORTFOLIO_TARGET', portfolio_pnl)
       
       def execute_portfolio_trailing_sl(self, strategy_id, portfolio_pnl):
           """Close all positions in strategy due to portfolio trailing SL"""
           logger.warning(f"Portfolio Trailing SL triggered for strategy {strategy_id}: P&L {portfolio_pnl}")
           self.close_all_strategy_positions(strategy_id, 'PORTFOLIO_TRAILING_SL', portfolio_pnl)
       
       def close_all_strategy_positions(self, strategy_id, exit_reason, portfolio_pnl):
           """Close all active positions for a strategy"""
           active_trades = get_active_trades_for_strategy(strategy_id)
           
           for trade in active_trades:
               # Use placesmartorder to close each position
               exit_payload = {
                   'apikey': get_user_api_key(trade.user_id),
                   'symbol': trade.symbol,
                   'exchange': trade.exchange,
                   'action': 'SELL' if trade.trade_type == 'LONG' else 'BUY',
                   'quantity': '0',
                   'position_size': '0',
                   'product': trade.product_type,
                   'pricetype': 'MARKET',
                   'price': '0',
                   'trigger_price': '0',
                   'disclosed_quantity': '0',
                   'strategy': f"{trade.strategy_name}_{exit_reason}"
               }
               
               success, response, code = place_smart_order_service(exit_payload)
               
               if success:
                   update_trade_exit(
                       trade_id=trade.id,
                       exit_order_id=response['orderid'],
                       exit_type=exit_reason,
                       status=exit_reason,
                       portfolio_pnl=portfolio_pnl
                   )
               else:
                   logger.error(f"Failed to close trade {trade.id} for {exit_reason}")
           
           # Log portfolio exit event
           log_portfolio_exit(strategy_id, exit_reason, portfolio_pnl, len(active_trades))
   ```

4. **Exit Order Execution**
   ```python
   def execute_exit_order(trade, exit_type):
       # Use placesmartorder with quantity=0 and position_size=0 to close position
       # This ensures complete position exit regardless of current position size
       
       # Determine action based on trade type
       if trade.trade_type == 'LONG':
           action = 'SELL'
       else:  # SHORT
           action = 'BUY'
       
       # Use placesmartorder for guaranteed position closure
       exit_order = {
           'apikey': get_user_api_key(trade.user_id),
           'symbol': trade.symbol,
           'exchange': trade.exchange,
           'action': action,
           'quantity': '0',  # Set to 0 for position exit
           'position_size': '0',  # This triggers complete position closure
           'product': trade.product_type,
           'pricetype': 'MARKET',
           'price': '0',
           'trigger_price': '0',
           'disclosed_quantity': '0',
           'strategy': f"{trade.strategy_name}_EXIT_{exit_type}"
       }
       
       # Use existing placesmartorder endpoint
       success, response, code = place_smart_order_service(exit_order)
       
       if success:
           update_trade_exit(
               trade_id=trade.id,
               exit_order_id=response['orderid'],
               exit_type=exit_type,
               status=f'{exit_type}_TRIGGERED'
           )
   ```

**Key Features:**
1. **Entry Detection**
   - Hook into existing order placement flow
   - Monitor order status using existing orderstatus API
   - When status = 'complete', fetch execution price
   - Create active_trade record with SL/Target calculations

2. **Real-time Monitoring**
   - Subscribe to WebSocket for symbols with active trades
   - Process LTP updates in real-time using SimpleFeed pattern
   - Check exit conditions (SL/Target/Trailing SL)
   - Batch process multiple trades for same symbol

3. **Exit Execution**
   - Use existing placesmartorder API with quantity=0 and position_size=0
   - This ensures complete position closure regardless of partial fills
   - Place market exit orders when conditions are met
   - Update trade status and log exit details
   - Calculate and store P&L based on execution price

4. **Position Validation**
   - Use existing positionbook API to validate positions
   - Periodically check open positions
   - Close trades if position no longer exists
   - Handle partial fills and modifications

5. **Trailing Stop-Loss Logic**
   ```python
   def update_trailing_sl(self, trade, current_ltp):
       if trade.trade_type == 'LONG':
           # For long trades, track highest price
           if current_ltp > trade.highest_price:
               trade.highest_price = current_ltp
               
               # Calculate new trailing SL
               if trade.trailing_stop_type == 'POINTS':
                   new_sl = current_ltp - trade.trailing_stop_value
               else:  # PERCENT
                   new_sl = current_ltp * (1 - trade.trailing_stop_value/100)
               
               # Only update if new SL is higher than current
               if new_sl > trade.current_trailing_sl:
                   trade.current_trailing_sl = new_sl
                   trade.stop_loss = new_sl
       
       else:  # SHORT trade
           # For short trades, track lowest price
           if current_ltp < trade.lowest_price:
               trade.lowest_price = current_ltp
               
               # Calculate new trailing SL
               if trade.trailing_stop_type == 'POINTS':
                   new_sl = current_ltp + trade.trailing_stop_value
               else:  # PERCENT
                   new_sl = current_ltp * (1 + trade.trailing_stop_value/100)
               
               # Only update if new SL is lower than current
               if new_sl < trade.current_trailing_sl:
                   trade.current_trailing_sl = new_sl
                   trade.stop_loss = new_sl
   ```

### 3. WebSocket Integration

#### Enhanced WebSocket Client
```python
class TradeMonitorWebSocketClient:
    - Maintains persistent connection to WebSocket server
    - Subscribes to symbols with active trades
    - Processes LTP updates efficiently
    - Handles reconnection and error recovery
    - Batches subscribe/unsubscribe requests
```

#### Data Flow
1. Trade created → Subscribe to symbol LTP
2. LTP update received → Check trade conditions
3. Trade closed → Unsubscribe from symbol
4. Optimize subscriptions to avoid duplicates

### 4. API Endpoints

Following the existing OpenAlgo REST API patterns, all endpoints will:
- Use POST method exclusively
- Require `apikey` field for authentication
- Be organized under `/api/v1/` namespace
- Use Marshmallow schemas for validation
- Return consistent response formats

#### New REST API Endpoints

1. **Create Trade with SL/Target**
   ```
   POST /api/v1/createtrade
   {
     "apikey": "your_api_key",
     "orderid": "123456",
     "stoploss_type": "PERCENT",  // PERCENT or POINTS
     "stoploss_value": "1.5",
     "target_type": "PERCENT",     // PERCENT or POINTS
     "target_value": "3.0",
     "trailing_stop": "YES",       // YES or NO
     "trailing_value": "0.5",
     "trailing_type": "PERCENT"    // PERCENT or POINTS
   }
   
   Response:
   {
     "status": "success",
     "data": {
       "tradeid": "789",
       "message": "Trade monitoring activated"
     }
   }
   ```

2. **Update Trade SL/Target**
   ```
   POST /api/v1/updatetrade
   {
     "apikey": "your_api_key",
     "tradeid": "789",
     "stoploss": "99.50",
     "target": "105.00",
     "trailing_stop": "NO"
   }
   
   Response:
   {
     "status": "success",
     "message": "Trade updated successfully"
   }
   ```

3. **Get Active Trades**
   ```
   POST /api/v1/activetrades
   {
     "apikey": "your_api_key"
   }
   
   Response:
   {
     "status": "success",
     "data": [
       {
         "tradeid": "789",
         "symbol": "RELIANCE",
         "exchange": "NSE",
         "entry_price": "2500.00",
         "current_ltp": "2510.00",
         "quantity": "10",
         "stoploss": "2450.00",
         "target": "2575.00",
         "pnl": "100.00",
         "status": "ACTIVE"
       }
     ]
   }
   ```

4. **Exit Trade Manually**
   ```
   POST /api/v1/exittrade
   {
     "apikey": "your_api_key",
     "tradeid": "789"
   }
   
   Response:
   {
     "status": "success",
     "data": {
       "orderid": "987654",
       "message": "Exit order placed successfully"
     }
   }
   ```
   
   Note: This endpoint internally uses the existing `placesmartorder` API with 
   `quantity=0` and `position_size=0` to ensure complete position closure.

5. **Get Trade History**
   ```
   POST /api/v1/tradehistory
   {
     "apikey": "your_api_key",
     "from_date": "2024-01-01",
     "to_date": "2024-01-31"
   }
   
   Response:
   {
     "status": "success",
     "data": [
       {
         "tradeid": "789",
         "symbol": "RELIANCE",
         "entry_price": "2500.00",
         "exit_price": "2525.00",
         "pnl": "250.00",
         "status": "TARGET_HIT",
         "entry_time": "2024-01-15 10:30:00",
         "exit_time": "2024-01-15 14:45:00"
       }
     ]
   }
   ```

#### API Implementation Structure

Each endpoint will follow the standard pattern:

**File Structure:**
```
restx_api/
├── createtrade.py
├── updatetrade.py
├── activetrades.py
├── exittrade.py
└── tradehistory.py

services/
├── create_trade_service.py
├── update_trade_service.py
├── active_trades_service.py
├── exit_trade_service.py
└── trade_history_service.py
```

**Schema Definitions** (in `restx_api/trade_schemas.py`):
```python
class CreateTradeSchema(Schema):
    apikey = fields.Str(required=True)
    orderid = fields.Str(required=True)
    stoploss_type = fields.Str(missing='PERCENT', validate=OneOf(['PERCENT', 'POINTS']))
    stoploss_value = fields.Str(required=True)
    target_type = fields.Str(missing='PERCENT', validate=OneOf(['PERCENT', 'POINTS']))
    target_value = fields.Str(required=True)
    trailing_stop = fields.Str(missing='NO', validate=OneOf(['YES', 'NO']))
    trailing_value = fields.Str(missing='0')
    trailing_type = fields.Str(missing='PERCENT', validate=OneOf(['PERCENT', 'POINTS']))

class UpdateTradeSchema(Schema):
    apikey = fields.Str(required=True)
    tradeid = fields.Str(required=True)
    stoploss = fields.Str(allow_none=True)
    target = fields.Str(allow_none=True)
    trailing_stop = fields.Str(validate=OneOf(['YES', 'NO']))
```

### 5. User Interface Changes

#### Strategy Configuration Page
- **Individual Trade Risk Settings:**
  - Default Stop Loss: Enable/Disable toggle + Value (% or Points)
  - Default Target: Enable/Disable toggle + Value (% or Points)
  - Trailing Stop Loss: Enable/Disable toggle + Value (% or Points)
  - Each can be individually enabled/disabled

- **Portfolio Risk Management (Strategy Level):**
  - Portfolio Stop Loss: Enable/Disable + Value (₹Amount or % of allocated funds)
  - Portfolio Target: Enable/Disable + Value (₹Amount or % of allocated funds)  
  - Portfolio Trailing SL: Enable/Disable + Value (₹Amount or % of allocated funds)
  - Example: Portfolio SL = 2% means close ALL positions if total strategy P&L hits -2%

- **Fund Allocation (Major Feature):**
  - Allocate Funds: Amount to allocate for this strategy
  - Position Sizing Method:
    - Fixed Quantity: Always trade X shares/lots
    - Fixed Value: Use ₹X per trade (e.g., ₹50,000 per trade)
    - Percentage Allocation: Use X% of allocated funds per trade
  - Max Open Positions: Limit concurrent trades
  - Daily Loss Limit: Stop trading if daily loss exceeds X

#### Trade Management Dashboard
- New page: `/trades` for monitoring active trades

- **Strategy Portfolio Summary Cards:**
  ```
  ┌─────────────────────────────────────────┐
  │ Nifty_Momentum Strategy                 │
  │ Portfolio P&L: +₹8,500 (1.7%)         │
  │ Active Trades: 3 | Allocated: ₹5,00,000│
  │ Portfolio SL: -₹10,000 | Target: +₹15,000│
  │ Portfolio Trailing SL: +₹6,500         │
  └─────────────────────────────────────────┘
  ```

- **Individual Trades Table:**
  - Symbol & Exchange
  - Entry Price & Current LTP
  - Individual Stop Loss Level (if enabled)
  - Individual Target Level (if enabled)
  - Individual Trailing SL Level (if enabled, dynamically updated)
  - Trade P&L (Amount & Percentage)
  - Trade Status
  - Quick Actions: Modify Levels, Manual Exit

- **Real-time Monitoring:**
  - Live LTP updates via WebSocket
  - Current levels for individual SL/Target/Trailing SL
  - Portfolio-level P&L and trailing SL updates
  - Real-time portfolio risk level indicators

- **Dual-Level Alerts Section:**
  - **Individual Trade Alerts:**
    - "RELIANCE Individual SL Hit at ₹2450 - Loss: ₹500"
    - "TCS Individual Target Hit at ₹3300 - Profit: ₹1,000"
    - "INFY Individual Trailing SL moved to ₹1420"
  
  - **Portfolio Level Alerts:**
    - "Nifty_Momentum Portfolio SL Hit - All 3 positions closed - Total Loss: ₹10,000"
    - "Options_Strategy Portfolio Target Hit - All 5 positions closed - Total Profit: ₹15,000"
    - "BankNifty_Strategy Portfolio Trailing SL updated to +₹8,000"
    - "Warning: Portfolio P&L near SL level (-₹9,500 of -₹10,000)"

#### P&L Summary Dashboard
- **Per Trade Summary:**
  - Entry/Exit prices
  - Reason for exit (SL/Target/Trailing SL/Manual)
  - Final P&L with percentage
  - Trade duration

- **Strategy Performance:**
  - Total P&L for strategy
  - Win/Loss ratio
  - Average profit per winning trade
  - Average loss per losing trade
  - Fund utilization percentage

### 6. Implementation Phases

#### Phase 1: Database and Core Infrastructure (Week 1)
1. Create database schema and migrations
2. Implement trade CRUD operations
3. Build TradeMonitor service skeleton
4. Add trade creation on order completion

#### Phase 2: Monitoring Service (Week 2)
1. Implement WebSocket integration
2. Build SL/Target checking logic
3. Add exit order placement
4. Implement trailing stop-loss logic

#### Phase 3: API Development (Week 3)
1. Create REST endpoints
2. Add validation and error handling
3. Implement trade update functionality
4. Add trade history and analytics

#### Phase 4: User Interface (Week 4)
1. Create trade management page
2. Add real-time updates
3. Implement trade modification UI
4. Add configuration to strategy page

#### Phase 5: Testing and Optimization (Week 5)
1. Unit and integration testing
2. Performance optimization
3. Error handling and recovery
4. Documentation and examples

### 7. State Management & Recovery

#### Persistent State Storage
All trade monitoring state is continuously persisted to the database to handle application restarts and crashes:

```sql
-- Real-time state updates in active_trades table
UPDATE active_trades SET
    current_ltp = ?,
    highest_price = ?,  -- For LONG trailing SL
    lowest_price = ?,   -- For SHORT trailing SL
    current_trailing_sl = ?,
    stop_loss = ?,  -- Updated by trailing SL
    updated_at = CURRENT_TIMESTAMP
WHERE id = ?;
```

#### Application Restart Recovery
```python
class TradeMonitorService:
    def __init__(self):
        self.recovery_mode = False
    
    def start_service(self):
        """Start trade monitoring with recovery support"""
        try:
            # Step 1: Recover active trades from database
            self.recover_active_trades()
            
            # Step 2: Re-establish WebSocket subscriptions
            self.restore_websocket_subscriptions()
            
            # Step 3: Validate positions against broker
            self.validate_active_positions()
            
            # Step 4: Resume normal monitoring
            self.recovery_mode = False
            logger.info("Trade monitoring service started successfully")
            
        except Exception as e:
            logger.error(f"Failed to start trade monitoring service: {e}")
            raise
    
    def recover_active_trades(self):
        """Recover active trades from database on startup"""
        active_trades = get_active_trades_from_db()
        
        for trade in active_trades:
            # Restore trade state in memory
            self.active_trades[trade.id] = {
                'trade_id': trade.id,
                'symbol': trade.symbol,
                'exchange': trade.exchange,
                'entry_price': trade.entry_price,
                'current_ltp': trade.current_ltp,
                'stop_loss': trade.stop_loss,
                'target': trade.target,
                'trailing_sl': trade.current_trailing_sl,
                'highest_price': trade.highest_price,
                'lowest_price': trade.lowest_price,
                'last_update': trade.updated_at
            }
        
        logger.info(f"Recovered {len(active_trades)} active trades")
    
    def restore_websocket_subscriptions(self):
        """Re-subscribe to WebSocket feeds for active trades"""
        symbols_to_subscribe = set()
        
        for trade in self.active_trades.values():
            symbol_key = f"{trade['exchange']}:{trade['symbol']}"
            symbols_to_subscribe.add(symbol_key)
        
        # Batch subscribe to unique symbols
        for symbol_key in symbols_to_subscribe:
            exchange, symbol = symbol_key.split(':')
            self.websocket_client.subscribe_symbol(symbol, exchange)
        
        logger.info(f"Re-subscribed to {len(symbols_to_subscribe)} symbols")
    
    def validate_active_positions(self):
        """Validate active trades against actual broker positions"""
        for trade_id, trade in list(self.active_trades.items()):
            try:
                # Check if position still exists at broker
                position = get_position_from_broker(
                    trade['symbol'], 
                    trade['exchange']
                )
                
                if not position or position['quantity'] == 0:
                    # Position closed outside the system
                    logger.warning(f"Trade {trade_id} position not found, closing trade")
                    self.close_trade_externally(trade_id)
                    
            except Exception as e:
                logger.error(f"Error validating position for trade {trade_id}: {e}")
```

#### Continuous State Persistence
```python
def update_trade_state(self, trade_id, ltp, **updates):
    """Update trade state both in memory and database"""
    try:
        # Update in-memory state
        if trade_id in self.active_trades:
            self.active_trades[trade_id].update({
                'current_ltp': ltp,
                'last_update': datetime.now(),
                **updates
            })
        
        # Persist to database immediately
        update_trade_in_db(trade_id, {
            'current_ltp': ltp,
            'updated_at': datetime.now(),
            **updates
        })
        
        # Log state update for audit
        log_trade_state_update(trade_id, ltp, updates)
        
    except Exception as e:
        logger.error(f"Failed to update trade state for {trade_id}: {e}")
        # Continue monitoring even if DB update fails
```

#### WebSocket Reconnection Handling
```python
class RobustWebSocketClient:
    def __init__(self):
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.reconnect_delay = 5  # seconds
        self.subscribed_symbols = set()
    
    def on_disconnect(self):
        """Handle WebSocket disconnection"""
        logger.warning("WebSocket disconnected, attempting reconnection...")
        self.reconnect_attempts = 0
        self.attempt_reconnection()
    
    def attempt_reconnection(self):
        """Attempt to reconnect with exponential backoff"""
        while self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                self.reconnect_attempts += 1
                delay = min(self.reconnect_delay * (2 ** self.reconnect_attempts), 60)
                
                logger.info(f"Reconnection attempt {self.reconnect_attempts}, waiting {delay}s")
                time.sleep(delay)
                
                # Reconnect and re-authenticate
                if self.connect() and self.authenticate():
                    # Re-subscribe to all previously subscribed symbols
                    self.resubscribe_all_symbols()
                    logger.info("WebSocket reconnected successfully")
                    return True
                    
            except Exception as e:
                logger.error(f"Reconnection attempt {self.reconnect_attempts} failed: {e}")
        
        logger.error("Max reconnection attempts reached, manual intervention required")
        self.notify_admin_of_failure()
    
    def resubscribe_all_symbols(self):
        """Re-subscribe to all symbols after reconnection"""
        for symbol_key in self.subscribed_symbols:
            exchange, symbol = symbol_key.split(':')
            self.subscribe_symbol(symbol, exchange)
```

#### Database State Synchronization
```python
def periodic_state_sync(self):
    """Periodically sync in-memory state with database (every 30 seconds)"""
    try:
        for trade_id, trade in self.active_trades.items():
            # Update database with current state
            sync_trade_state_to_db(trade_id, {
                'current_ltp': trade['current_ltp'],
                'highest_price': trade['highest_price'],
                'lowest_price': trade['lowest_price'],
                'current_trailing_sl': trade['trailing_sl'],
                'stop_loss': trade['stop_loss'],  # May be updated by trailing
                'last_sync': datetime.now()
            })
        
        logger.debug(f"Synced state for {len(self.active_trades)} active trades")
        
    except Exception as e:
        logger.error(f"Failed to sync trade states: {e}")

# Schedule periodic sync
scheduler.add_job(
    periodic_state_sync,
    'interval',
    seconds=30,
    id='trade_state_sync'
)
```

#### Recovery Validation & Health Checks
```python
def health_check(self):
    """Comprehensive health check of trade monitoring system"""
    health_status = {
        'websocket_connected': self.websocket_client.is_connected(),
        'active_trades_count': len(self.active_trades),
        'db_connectivity': test_database_connection(),
        'last_ltp_update': self.get_last_ltp_update_time(),
        'subscription_count': len(self.websocket_client.subscribed_symbols),
        'recovery_mode': self.recovery_mode
    }
    
    # Alert if system is unhealthy
    if not health_status['websocket_connected']:
        logger.error("WebSocket not connected - trades may not be monitored")
        self.attempt_reconnection()
    
    if (datetime.now() - health_status['last_ltp_update']).seconds > 300:
        logger.warning("No LTP updates received in 5 minutes")
    
    return health_status
```

### 8. Strategy Safety Controls

#### Active Trade Protection
Before allowing strategy deletion or deactivation, the system will check for active trades and warn users:

```python
def check_strategy_safety(strategy_id, action_type):
    """Check if strategy can be safely deleted/deactivated"""
    active_trades = get_active_trades_for_strategy(strategy_id)
    open_positions = get_open_positions_for_strategy(strategy_id)
    
    safety_check = {
        'safe_to_proceed': True,
        'warnings': [],
        'active_trades': [],
        'required_actions': []
    }
    
    if active_trades:
        safety_check['safe_to_proceed'] = False
        safety_check['warnings'].append(
            f"Strategy has {len(active_trades)} active trades with SL/Target monitoring"
        )
        
        for trade in active_trades:
            trade_info = {
                'symbol': trade.symbol,
                'exchange': trade.exchange,
                'quantity': trade.quantity,
                'entry_price': trade.entry_price,
                'current_ltp': trade.current_ltp,
                'unrealized_pnl': calculate_unrealized_pnl(trade),
                'stop_loss': trade.stop_loss if trade.stop_loss else 'Not Set',
                'target': trade.target if trade.target else 'Not Set',
                'status': trade.status
            }
            safety_check['active_trades'].append(trade_info)
        
        if action_type == 'DELETE':
            safety_check['required_actions'].extend([
                "Close all active positions manually, OR",
                "Transfer trades to another strategy, OR", 
                "Force close all positions (will trigger immediate market orders)"
            ])
        elif action_type == 'DEACTIVATE':
            safety_check['required_actions'].extend([
                "Existing trades will continue monitoring but no new trades will be accepted",
                "SL/Target monitoring will remain active",
                "Consider closing positions or wait for natural exits"
            ])
    
    if open_positions:
        safety_check['warnings'].append(
            f"Strategy has {len(open_positions)} open positions at broker"
        )
    
    return safety_check

def validate_strategy_deletion(strategy_id):
    """Validate strategy deletion with user confirmation"""
    safety = check_strategy_safety(strategy_id, 'DELETE')
    
    if not safety['safe_to_proceed']:
        return {
            'status': 'warning',
            'message': 'Strategy has active trades',
            'data': safety,
            'confirmation_required': True
        }
    
    return {'status': 'safe', 'message': 'Strategy can be safely deleted'}

def validate_strategy_deactivation(strategy_id):
    """Validate strategy deactivation with user notification"""
    safety = check_strategy_safety(strategy_id, 'DEACTIVATE')
    
    return {
        'status': 'info' if safety['safe_to_proceed'] else 'warning',
        'message': 'Strategy deactivation impact',
        'data': safety,
        'confirmation_required': len(safety['active_trades']) > 0
    }
```

#### UI Safety Dialogs

**Strategy Deletion Warning Dialog:**
```html
<!-- When user clicks delete strategy -->
<div class="modal modal-open" id="delete-strategy-modal">
    <div class="modal-box max-w-4xl">
        <h3 class="font-bold text-lg text-error">⚠️ Delete Strategy Warning</h3>
        
        {% if active_trades %}
        <div class="alert alert-error mt-4">
            <svg xmlns="http://www.w3.org/2000/svg" class="stroke-current shrink-0 h-6 w-6" fill="none" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L3.732 16.5c-.77.833.192 2.5 1.732 2.5z" />
            </svg>
            <span><strong>{{active_trades|length}} Active Trades Found!</strong><br>
                  Deleting this strategy will stop SL/Target monitoring for these positions.</span>
        </div>
        
        <!-- Active Trades Table -->
        <div class="overflow-x-auto mt-4">
            <table class="table table-zebra table-compact w-full">
                <thead>
                    <tr>
                        <th>Symbol</th>
                        <th>Qty</th>
                        <th>Entry Price</th>
                        <th>Current LTP</th>
                        <th>P&L</th>
                        <th>Stop Loss</th>
                        <th>Target</th>
                    </tr>
                </thead>
                <tbody>
                    {% for trade in active_trades %}
                    <tr>
                        <td>{{trade.symbol}}</td>
                        <td>{{trade.quantity}}</td>
                        <td>₹{{trade.entry_price}}</td>
                        <td>₹{{trade.current_ltp}}</td>
                        <td class="{{trade.pnl_class}}">₹{{trade.unrealized_pnl}}</td>
                        <td>{{trade.stop_loss}}</td>
                        <td>{{trade.target}}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        
        <!-- Action Options -->
        <div class="card bg-base-200 mt-4">
            <div class="card-body">
                <h4 class="card-title text-warning">Choose Action:</h4>
                <div class="form-control">
                    <label class="label cursor-pointer">
                        <span class="label-text">Close all positions immediately (Market Orders)</span>
                        <input type="radio" name="delete_action" value="close_all" class="radio radio-warning" />
                    </label>
                </div>
                <div class="form-control">
                    <label class="label cursor-pointer">
                        <span class="label-text">Stop monitoring and delete (Positions remain open)</span>
                        <input type="radio" name="delete_action" value="stop_monitoring" class="radio radio-error" />
                    </label>
                </div>
                <div class="form-control">
                    <label class="label cursor-pointer">
                        <span class="label-text">Cancel deletion</span>
                        <input type="radio" name="delete_action" value="cancel" class="radio radio-success" checked />
                    </label>
                </div>
            </div>
        </div>
        {% endif %}
        
        <div class="modal-action">
            <button class="btn btn-error" onclick="confirmStrategyDeletion()">
                Proceed with Deletion
            </button>
            <button class="btn" onclick="closeModal()">Cancel</button>
        </div>
    </div>
</div>
```

**Strategy Deactivation Warning Dialog:**
```html
<div class="modal modal-open" id="deactivate-strategy-modal">
    <div class="modal-box">
        <h3 class="font-bold text-lg text-warning">⚠️ Deactivate Strategy</h3>
        
        {% if active_trades %}
        <div class="alert alert-warning mt-4">
            <svg xmlns="http://www.w3.org/2000/svg" class="stroke-current shrink-0 h-6 w-6" fill="none" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L3.732 16.5c-.77.833.192 2.5 1.732 2.5z" />
            </svg>
            <div>
                <strong>{{active_trades|length}} Active Trades Found</strong>
                <ul class="list-disc list-inside mt-2">
                    <li>Existing trades will continue SL/Target monitoring</li>
                    <li>No new webhook signals will be processed</li>
                    <li>You can reactivate the strategy anytime</li>
                </ul>
            </div>
        </div>
        
        <div class="mt-4">
            <p><strong>Active Trades Summary:</strong></p>
            <ul class="list-disc list-inside">
                {% for trade in active_trades %}
                <li>{{trade.symbol}}: {{trade.quantity}} @ ₹{{trade.entry_price}} ({{trade.status}})</li>
                {% endfor %}
            </ul>
        </div>
        {% else %}
        <div class="alert alert-info mt-4">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" class="stroke-current shrink-0 w-6 h-6">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
            </svg>
            <span>No active trades found. Strategy can be safely deactivated.</span>
        </div>
        {% endif %}
        
        <div class="modal-action">
            <button class="btn btn-warning" onclick="confirmStrategyDeactivation()">
                Deactivate Strategy
            </button>
            <button class="btn" onclick="closeModal()">Cancel</button>
        </div>
    </div>
</div>
```

#### Backend API Updates

**Enhanced Delete Strategy Endpoint:**
```python
@strategy_bp.route('/<int:strategy_id>/delete', methods=['POST'])
@check_session_validity
def delete_strategy_route(strategy_id):
    """Delete strategy with safety checks"""
    user_id = session.get('user')
    if not user_id:
        return jsonify({'status': 'error', 'error': 'Session expired'}), 401
        
    strategy = get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        return jsonify({'status': 'error', 'error': 'Strategy not found'}), 404
    
    try:
        # Check for active trades
        safety_check = check_strategy_safety(strategy_id, 'DELETE')
        
        if not safety_check['safe_to_proceed']:
            action = request.json.get('action', 'check')
            
            if action == 'check':
                # Return warning with active trades info
                return jsonify({
                    'status': 'warning',
                    'message': 'Strategy has active trades',
                    'data': safety_check
                }), 200
            
            elif action == 'close_all':
                # Close all active positions first
                for trade in safety_check['active_trades']:
                    close_trade_immediately(trade['trade_id'])
                
                # Wait a moment for orders to process
                time.sleep(2)
                
                # Then delete strategy
                if delete_strategy(strategy_id):
                    return jsonify({'status': 'success', 'message': 'Strategy deleted and all positions closed'})
                    
            elif action == 'stop_monitoring':
                # Stop monitoring but keep positions
                deactivate_trade_monitoring(strategy_id)
                
                if delete_strategy(strategy_id):
                    return jsonify({'status': 'success', 'message': 'Strategy deleted, positions remain open'})
        
        else:
            # Safe to delete
            if delete_strategy(strategy_id):
                return jsonify({'status': 'success'})
                
    except Exception as e:
        logger.error(f'Error deleting strategy {strategy_id}: {str(e)}')
        return jsonify({'status': 'error', 'error': str(e)}), 500

def close_trade_immediately(trade_id):
    """Force close a trade immediately using smart order"""
    trade = get_active_trade(trade_id)
    if not trade:
        return
    
    # Use placesmartorder to close position
    exit_payload = {
        'apikey': get_user_api_key(trade.user_id),
        'symbol': trade.symbol,
        'exchange': trade.exchange,
        'action': 'SELL' if trade.trade_type == 'LONG' else 'BUY',
        'quantity': '0',
        'position_size': '0',
        'product': trade.product_type,
        'pricetype': 'MARKET',
        'price': '0',
        'trigger_price': '0',
        'disclosed_quantity': '0',
        'strategy': f"{trade.strategy_name}_FORCE_EXIT"
    }
    
    # Execute exit order
    success, response, code = place_smart_order_service(exit_payload)
    
    if success:
        update_trade_status(trade_id, 'FORCE_CLOSED', response.get('orderid'))
        logger.info(f"Force closed trade {trade_id}")
    else:
        logger.error(f"Failed to force close trade {trade_id}: {response}")
```

### 9. Technical Considerations

#### Performance
- Use efficient data structures for active trade lookup
- Batch WebSocket subscriptions
- Implement rate limiting for exit orders
- Use database indexes for quick queries
- In-memory cache with database persistence

#### Reliability & Recovery
- **Graceful Shutdown**: Save all states before shutdown
- **Automatic Recovery**: Restore active trades on startup
- **WebSocket Resilience**: Auto-reconnect with subscription restoration
- **Database Sync**: Continuous state persistence every 30 seconds
- **Position Validation**: Cross-check with broker positions
- **Health Monitoring**: Automated system health checks
- **Failover Logging**: Complete audit trail for recovery analysis

#### State Persistence Strategy
- **Immediate Updates**: Critical state changes saved instantly
- **Periodic Sync**: Full state sync every 30 seconds
- **Recovery Mode**: Special startup mode to restore from crashes
- **Conflict Resolution**: Broker position validation on recovery
- **Data Integrity**: Transaction-based database updates

#### Strategy Safety Controls
- **Active Trade Detection**: Check for trades before deletion/deactivation
- **User Warnings**: Clear dialogs showing impact of actions
- **Force Close Options**: Immediate position closure via smart orders
- **Monitoring Continuity**: Deactivation keeps existing trades monitored
- **Audit Trail**: Log all strategy lifecycle changes

### 8. Configuration

#### Environment Variables
```
TRADE_MONITOR_ENABLED=true
TRADE_MONITOR_INTERVAL=100  # ms
MAX_ACTIVE_TRADES_PER_USER=100
WEBSOCKET_RECONNECT_DELAY=5000  # ms
```

#### User Settings
- Enable/disable trade monitoring per user
- Default SL/Target percentages
- Notification preferences
- Risk management limits

### 9. Error Handling

1. **Order Failures**
   - Retry logic for exit orders
   - Alert user on repeated failures
   - Manual intervention options

2. **Data Issues**
   - Handle missing LTP data
   - Validate price sanity checks
   - Log anomalies for review

3. **System Failures**
   - Graceful degradation
   - State recovery on restart
   - Audit trail for all actions

### 10. Security Considerations

1. **Access Control**
   - Users can only manage their own trades
   - API authentication required
   - Rate limiting on sensitive operations

2. **Data Validation**
   - Validate all price inputs
   - Prevent manipulation of trade data
   - Audit log for modifications

3. **Risk Management**
   - Maximum loss limits
   - Position size validation
   - Daily trade limits

### 11. Integration with Strategy Management

The enhanced trade management will seamlessly integrate with the existing strategy management system:

#### Strategy-Level Configuration
```python
# In strategy creation/edit
strategy_config = {
    "name": "MyStrategy",
    "webhook_id": "uuid",
    "default_sl_percent": 1.5,
    "default_target_percent": 3.0,
    "enable_trailing_sl": True,
    "trailing_sl_value": 0.5,
    "trailing_sl_type": "PERCENT",
    "auto_sl_target": True  # Automatically apply SL/Target to all orders
}
```

#### Webhook Integration
When a webhook triggers an order through strategy:
1. Order is placed using existing flow
2. If strategy has `auto_sl_target` enabled:
   - Trade monitoring is automatically created
   - Uses strategy's default SL/Target settings
   - Can be overridden per trade via API

#### Strategy Dashboard Enhancement
Add to existing strategy view (`templates/strategy/view_strategy.html`):
- Active trades count for the strategy
- Total P&L from trades
- Success rate (Target hit vs SL hit)
- Quick toggle for auto SL/Target

### 12. Leveraging Existing Smart Order Functionality

The trade management system takes full advantage of OpenAlgo's existing `placesmartorder` capability:

#### Benefits of Using Smart Orders for Exits:
1. **Guaranteed Full Position Exit**: By setting `quantity=0` and `position_size=0`, the system ensures complete position closure
2. **Handles Partial Fills**: If the original entry was partially filled, smart order still closes the entire position
3. **No Position Tracking Required**: The system doesn't need to track exact position sizes
4. **Atomic Operations**: Single API call handles all exit logic
5. **Broker Agnostic**: Works consistently across all supported brokers

#### Example Exit Flow:
```python
# When SL/Target is triggered
exit_payload = {
    'apikey': user_api_key,
    'symbol': 'RELIANCE',
    'exchange': 'NSE',
    'action': 'SELL',  # For LONG position exit
    'quantity': '0',
    'position_size': '0',  # Magic values for complete exit
    'product': 'MIS',
    'pricetype': 'MARKET',
    'price': '0',
    'trigger_price': '0',
    'disclosed_quantity': '0',
    'strategy': 'MyStrategy_SL_EXIT'
}
# This will close the entire LONG position regardless of size
```

### 13. Backward Compatibility

The implementation ensures complete backward compatibility:

1. **Existing API Endpoints**: No changes to existing endpoints
2. **Optional Feature**: Trade management is opt-in per user/strategy
3. **Database**: Only additive changes, no breaking modifications
4. **WebSocket**: Reuses existing infrastructure
5. **Order Flow**: Hooks into existing flow without disrupting it
6. **Smart Order API**: Leverages existing functionality without modifications

Users can continue using OpenAlgo exactly as before, with trade management as an optional enhancement.

### 14. Dual-Level Risk Management Example

Here's a comprehensive example showing both individual and portfolio-level monitoring:

#### Strategy Setup:
```
Strategy: "Nifty_Momentum"
Allocated Funds: ₹5,00,000
Position Size: 10% per trade (₹50,000 each)

Individual Trade Settings:
- Stop Loss: 1.5% below entry
- Target: 3% above entry  
- Trailing SL: 0.5% from peak

Portfolio Settings:
- Portfolio SL: -₹10,000 (2% of allocated funds)
- Portfolio Target: +₹15,000 (3% of allocated funds)
- Portfolio Trailing SL: ₹5,000 from peak P&L
```

#### Trade Flow Example:

1. **Multiple Order Placements**
   ```
   10:30 AM: BUY 20 RELIANCE @ ₹2500 (₹50,000)
   10:45 AM: BUY 15 TCS @ ₹3333 (₹50,000)
   11:00 AM: BUY 35 INFY @ ₹1429 (₹50,000)
   
   Portfolio Status:
   - Total Deployed: ₹1,50,000
   - Portfolio P&L: ₹0
   - Active Trades: 3
   ```

2. **Individual Trade Monitoring**
   ```
   RELIANCE: Entry ₹2500, Current ₹2520
   - Individual SL: ₹2462.50 (1.5% below)
   - Individual Target: ₹2575 (3% above)
   - Individual Trailing SL: ₹2507.50 (0.5% from peak)
   - Trade P&L: +₹400
   
   TCS: Entry ₹3333, Current ₹3350
   - Individual SL: ₹3283.50
   - Individual Target: ₹3433
   - Individual Trailing SL: ₹3333 (entry level, no gain yet)
   - Trade P&L: +₹255
   
   INFY: Entry ₹1429, Current ₹1435
   - Individual SL: ₹1407.65
   - Individual Target: ₹1472
   - Individual Trailing SL: ₹1429 (entry level)
   - Trade P&L: +₹210
   ```

3. **Portfolio Level Monitoring**
   ```
   Portfolio P&L: +₹865 (₹400 + ₹255 + ₹210)
   Portfolio Highest P&L: +₹865
   Portfolio Trailing SL: -₹4,135 (₹865 - ₹5,000)
   
   Status: All positions safe
   - Portfolio SL: -₹10,000 (far away)
   - Portfolio Target: +₹15,000 (need +₹14,135 more)
   ```

4. **Price Movements & Monitoring**
   ```
   11:30 AM: Market moves favorably
   RELIANCE: ₹2580 (+₹1,600 trade P&L)
   TCS: ₹3380 (+₹705 trade P&L)
   INFY: ₹1445 (+₹560 trade P&L)
   
   Portfolio P&L: +₹2,865
   Portfolio Highest P&L: +₹2,865 (updated)
   Portfolio Trailing SL: -₹2,135 (₹2,865 - ₹5,000)
   
   Individual Updates:
   - RELIANCE Trailing SL: ₹2,567.50 (moved up)
   - TCS Trailing SL: ₹3,363.50 (activated)
   - INFY Trailing SL: ₹1,437.50 (activated)
   ```

5. **Exit Scenarios**

   **Scenario A: Individual SL Hit**
   ```
   12:00 PM: INFY drops to ₹1,405
   → Individual SL triggered (₹1,407.65)
   → Only INFY position closed
   → Portfolio continues with RELIANCE + TCS
   → Portfolio P&L: +₹2,305 (lost INFY's ₹560)
   ```

   **Scenario B: Portfolio SL Hit**
   ```
   12:30 PM: Market crashes
   RELIANCE: ₹2,350 (-₹3,000 trade P&L)
   TCS: ₹3,150 (-₹2,745 trade P&L) 
   INFY: ₹1,350 (-₹2,765 trade P&L)
   
   Portfolio P&L: -₹8,510
   → Still above Portfolio SL of -₹10,000
   
   1:00 PM: Further decline
   Portfolio P&L: -₹10,100
   → Portfolio SL triggered!
   → ALL 3 positions closed immediately
   → Strategy stops taking new signals
   ```

   **Scenario C: Portfolio Target Hit**
   ```
   2:00 PM: Strong rally
   RELIANCE: ₹2,650 (+₹3,000)
   TCS: ₹3,500 (+₹2,505)
   INFY: ₹1,500 (+₹2,485)
   
   Portfolio P&L: +₹7,990
   
   2:15 PM: Continued rally
   Portfolio P&L: +₹15,250
   → Portfolio Target Hit!
   → ALL 3 positions closed at profit
   → Total realized profit: ₹15,250
   ```

#### Key Benefits of Dual-Level Monitoring:

1. **Granular Control**: Each trade has its own SL/Target
2. **Portfolio Protection**: Overall strategy risk is capped
3. **Profit Booking**: Portfolio target ensures profits are locked
4. **Flexibility**: Individual trades can exit while portfolio continues
5. **Risk Management**: Portfolio SL prevents catastrophic losses across all positions

## Summary

This enhanced trade management module transforms OpenAlgo from a simple order execution platform to a comprehensive trading system with automated risk management. The modular design allows for incremental implementation while maintaining system stability.

The key innovation is the server-side monitoring of trades with real-time price tracking, eliminating the need for traders to constantly monitor positions. This professional-grade feature set brings OpenAlgo closer to institutional trading platforms while maintaining its open-source accessibility.

The implementation leverages existing infrastructure wherever possible, ensuring minimal disruption while adding powerful new capabilities. By following OpenAlgo's established patterns and conventions, the new features will feel native to the platform.