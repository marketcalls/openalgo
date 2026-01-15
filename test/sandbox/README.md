# Sandbox Mode Test Suite

This directory contains comprehensive tests for the OpenAlgo sandbox (virtual trading) mode.

## Test Files

### 1. test_margin_scenarios.py
**Purpose:** Tests complete margin flow across various trading scenarios

**Test Cases:**
- BUY 100 → SELL 50 → SELL 50 (partial position closure)
- BUY 100 → SELL 100 → BUY 100 → SELL 100 (position cycling)
- BUY 100 → SELL 200 (position reversal)
- BUY 100 → BUY 100 (adding to position)

**Key Features Tested:**
- Margin blocking at order placement
- Margin release on position closure
- Double-blocking prevention
- Position reopening after closure

### 2. test_cnc_sell_validation.py
**Purpose:** Tests CNC (delivery) SELL order validation

**Test Cases:**
- CNC SELL without position/holdings (should reject)
- CNC SELL with existing position (should succeed)
- CNC SELL exceeding available quantity (should reject)
- CNC SELL with holdings only
- MIS short selling (should allow without position)
- CNC SELL with combined position and holdings

**Key Features Tested:**
- Position and holdings validation
- Rejection reason clarity
- MIS vs CNC product differences
- Error message accuracy

### 3. test_rejected_order.py
**Purpose:** Verifies rejected orders appear in orderbook

**Test Cases:**
- Places invalid CNC SELL order
- Checks orderbook for rejected order
- Verifies rejection reason is stored

**Key Features Tested:**
- Audit trail for rejected orders
- Order ID generation for all orders
- Rejection reason storage
- No margin blocking for rejected orders

### 4. test_orderbook_api.py
**Purpose:** Tests orderbook API response structure

**Test Cases:**
- Retrieves orderbook via API
- Parses response structure
- Filters rejected orders
- Verifies rejection reasons in response

**Key Features Tested:**
- API response format
- Rejected order visibility
- Statistics accuracy
- Field completeness

### 5. test_fund_manager.py
**Purpose:** Tests fund management and margin calculations

**Test Cases:**
- Initial capital setup
- Margin blocking/release
- P&L calculations
- Balance updates

## Running Tests

### Individual Test
```bash
cd /path/to/openalgo
source .venv/bin/activate
python test/sandbox/test_margin_scenarios.py
```

### All Sandbox Tests
```bash
cd /path/to/openalgo
source .venv/bin/activate

# Run all tests
for test in test/sandbox/test_*.py; do
    echo "Running $test..."
    python "$test"
done
```

### Quick Test Commands
```bash
# Test margin scenarios
python test/sandbox/test_margin_scenarios.py

# Test CNC validation
python test/sandbox/test_cnc_sell_validation.py

# Test rejected orders
python test/sandbox/test_rejected_order.py

# Test orderbook API
python test/sandbox/test_orderbook_api.py
```

## Test Data

Tests use the following test data:
- **Test User:** `testuser` or `rajandran`
- **Test Symbol:** `ZEEL` or `RELIANCE`
- **Test Exchange:** `NSE`
- **Test Products:** `CNC` (delivery), `MIS` (intraday)
- **Initial Capital:** ₹1,00,00,000 (1 Crore)

## Common Issues

### 1. Order ID Conflicts
**Issue:** `UNIQUE constraint failed: sandbox_orders.orderid`
**Solution:** Clear all orders before testing
```python
SandboxOrders.query.delete()  # Clear ALL orders
db_session.commit()
```

### 2. API Authentication Failures
**Issue:** Quote fetching fails with authentication error
**Solution:** Test uses fallback prices when API unavailable

### 3. Database Lock Errors
**Issue:** Database is locked
**Solution:** Ensure no other processes are using the database

## Expected Test Results

All tests should pass with output similar to:
```
✅ SCENARIO 1 PASSED
✅ SCENARIO 2 PASSED
✅ SCENARIO 3 PASSED
✅ SCENARIO 4 PASSED

TEST RESULTS: 4 passed, 0 failed
🎉 ALL TESTS PASSED!
```

## Test Coverage

The test suite covers:
- ✅ Margin calculations (blocking, release, tracking)
- ✅ Position lifecycle (open, add, reduce, close, reopen)
- ✅ Order validation (product rules, quantity checks)
- ✅ Rejected order handling (audit trail, visibility)
- ✅ API response formats (orderbook, tradebook)
- ✅ Edge cases (reversals, partial fills, short selling)

## Adding New Tests

When adding new tests:
1. Follow the naming convention: `test_<feature>.py`
2. Include clear test cases with expected outcomes
3. Reset test data at the beginning of each test
4. Use descriptive assertion messages
5. Document the test purpose and scenarios

## Dependencies

Tests require:
- SQLAlchemy for database operations
- Decimal for precise calculations
- datetime for timestamps
- pytz for timezone handling

All dependencies are included in the main requirements.txt file.