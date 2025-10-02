# Sandbox Mode Integration Status

## Completed Core Components ✅

### 1. Database Layer
- ✅ 6 tables created in `db/sandbox.db`:
  - `sandbox_orders` - All sandbox orders
  - `sandbox_trades` - Executed trades
  - `sandbox_positions` - Open positions with MTM
  - `sandbox_holdings` - T+1 settled CNC holdings
  - `sandbox_funds` - Simulated capital and margin tracking
  - `sandbox_config` - Configurable settings
- ✅ All timestamps use IST timezone (`Asia/Kolkata`)
- ✅ Migration script: `upgrade/migrate_sandbox.py`

### 2. Core Managers
- ✅ `sandbox/fund_manager.py` - Fund and margin management
  - ₹10,000,000 starting capital
  - Sunday reset at midnight IST
  - Leverage calculations (5x equity MIS, 1x CNC, 10x futures)
  - Margin blocking/release
  - P&L tracking (realized + unrealized)

- ✅ `sandbox/order_manager.py` - Order lifecycle management
  - Order placement with validation
  - Order modification
  - Order cancellation
  - Orderbook retrieval
  - Support for MARKET, LIMIT, SL, SL-M order types

- ✅ `sandbox/execution_engine.py` - Order execution engine
  - Real-time quote fetching from broker
  - Order execution based on price type logic
  - Rate limit compliance (10 orders/sec, 50 API calls/sec)
  - Batch processing for efficiency
  - Background execution every 5 seconds (configurable)

- ✅ `sandbox/position_manager.py` - Position tracking
  - Real-time MTM calculations
  - Position netting logic
  - Tradebook generation
  - Background MTM updates (configurable)

- ✅ `sandbox/holdings_manager.py` - Holdings management
  - T+1 settlement for CNC positions
  - Holdings P&L tracking
  - Auto conversion from positions to holdings

- ✅ `sandbox/squareoff_manager.py` - Auto square-off
  - Exchange-specific timings (all IST):
    - NSE/BSE/NFO/BFO: 3:15 PM
    - CDS/BCD: 4:45 PM
    - MCX: 11:30 PM
    - NCDEX: 5:00 PM
  - Automatic MIS position closure
  - Configurable timings

### 3. Service Integration Layer
- ✅ `services/sandbox_service.py` - Routing layer
  - Routes analyzer mode requests to sandbox
  - Maintains same response format with `"mode": "analyze"` field
  - All functions preserve existing API signatures
  - No impact on live mode

### 4. Integrated Services
Services that route to sandbox when analyzer mode is enabled:

#### Order Management
- ✅ `services/place_order_service.py` - Routes to `sandbox_place_order()`
- ✅ `services/modify_order_service.py` - Routes to `sandbox_modify_order()`
- ✅ `services/cancel_order_service.py` - Routes to `sandbox_cancel_order()`

## Remaining Service Integrations 🔄

The following services need to be updated to check analyzer mode and route to sandbox:

### Data Retrieval Services
1. **orderbook_service.py** - Route to `sandbox_get_orderbook()`
2. **orderstatus_service.py** - Route to `sandbox_get_order_status()`
3. **openposition_service.py** - Route to `sandbox_get_positions()`
4. **positionbook_service.py** - Route to `sandbox_get_positions()`
5. **holdings_service.py** - Route to `sandbox_get_holdings()`
6. **tradebook_service.py** - Route to `sandbox_get_tradebook()`
7. **funds_service.py** - Route to `sandbox_get_funds()`
8. **close_position_service.py** - Route to `sandbox_close_position()`

### Batch Order Services
9. **basket_order_service.py** - Loop through orders, call `sandbox_place_order()` for each
10. **split_order_service.py** - Split orders, call `sandbox_place_order()` for each
11. **place_smart_order_service.py** - Handle smart order logic, call `sandbox_place_order()`
12. **cancel_all_order_service.py** - Get all orders, call `sandbox_cancel_order()` for each

## Integration Pattern

All service integrations follow this pattern:

```python
# In the service's main function with auth (e.g., get_orderbook_with_auth)

# Add this check BEFORE calling broker module:
if get_analyze_mode():
    from services.sandbox_service import sandbox_get_orderbook

    api_key = original_data.get('apikey')
    if not api_key:
        return False, {
            'status': 'error',
            'message': 'API key required for sandbox mode',
            'mode': 'analyze'
        }, 400

    return sandbox_get_orderbook(api_key, original_data)

# Existing broker module logic continues here...
```

## Testing Status

### Tested Components
- ✅ Fund manager - All tests passed
- ✅ Database migration - Successfully created all tables
- ✅ Timezone handling - All IST timestamps verified

### Pending Tests
- ⏳ Order placement end-to-end
- ⏳ Order execution with live quotes
- ⏳ Position MTM updates
- ⏳ T+1 settlement processing
- ⏳ Auto square-off trigger
- ⏳ Integration with existing API endpoints

## Configuration

All sandbox settings stored in `sandbox_config` table:

| Config Key | Default Value | Description |
|------------|---------------|-------------|
| starting_capital | 10000000.00 | Starting virtual capital (₹1 Crore) |
| reset_day | Sunday | Day for automatic fund reset |
| reset_time | 00:00 | Time for fund reset (IST) |
| order_check_interval | 5 | Seconds between order execution checks |
| mtm_update_interval | 5 | Seconds between MTM updates (0 = manual only) |
| nse_bse_square_off_time | 15:15 | NSE/BSE square-off time (IST) |
| cds_bcd_square_off_time | 16:45 | CDS/BCD square-off time (IST) |
| mcx_square_off_time | 23:30 | MCX square-off time (IST) |
| ncdex_square_off_time | 17:00 | NCDEX square-off time (IST) |
| equity_mis_leverage | 5 | Leverage for equity MIS |
| equity_cnc_leverage | 1 | Leverage for equity CNC |
| futures_leverage | 10 | Leverage for all futures |
| option_buy_leverage | 1 | Leverage for buying options (premium) |
| option_sell_leverage | 10 | Leverage for selling options (futures margin) |
| order_rate_limit | 10 | Maximum orders per second |
| api_rate_limit | 50 | Maximum API calls per second |
| smart_order_rate_limit | 2 | Maximum smart orders per second |
| smart_order_delay | 0.5 | Delay between smart order iterations |

## Key Features

1. **Real Market Data** - Uses actual live quotes from broker via `quotes_service`
2. **No Mock Data** - All executions based on real LTP, not simulated prices
3. **Realistic Execution** - Order types execute exactly as they would in live trading
4. **Position Netting** - Same symbol/exchange/product positions are netted correctly
5. **Margin System** - Full margin blocking/release with leverage-based calculations
6. **T+1 Settlement** - CNC positions automatically convert to holdings after 1 trading day
7. **Auto Square-Off** - MIS positions squared-off at exchange times
8. **Rate Limit Compliance** - All operations respect configured rate limits
9. **IST Timezone** - All timestamps in Indian Standard Time
10. **Separate Database** - Complete isolation in `sandbox/sandbox.db`

## Next Steps

1. Complete integration of remaining 12 services
2. Test end-to-end order flow with real quotes
3. Set up background processes for:
   - Order execution engine (every 5 sec)
   - MTM updates (every 5 sec)
   - Square-off checker (every 1 min)
   - T+1 settlement (daily at market close)
   - Sunday fund reset (weekly at midnight IST)
4. Create UI for sandbox configuration
5. Add sandbox statistics dashboard
