# OpenAlgo Testing Guide
## Complete Guide to Writing and Running Tests

---

## 📚 Table of Contents
1. [Test Structure](#test-structure)
2. [Running Tests](#running-tests)
3. [Writing Tests](#writing-tests)
4. [Test Patterns](#test-patterns)
5. [Mocking & Fixtures](#mocking--fixtures)
6. [Coverage & CI](#coverage--ci)

---

## Test Structure

### Directory Organization
```
openalgo/
├── test/
│   ├── __init__.py
│   ├── test_auth.py
│   ├── test_brokers.py
│   ├── test_services/
│   │   ├── test_place_order_service.py
│   │   ├── test_margin_service.py
│   │   └── test_holdings_service.py
│   └── test_database/
│       ├── test_auth_db.py
│       └── test_order_db.py
```

### File Naming Convention
- **Pattern**: `test_<module>_<functionality>.py`
- **Examples**:
  - `test_place_order_service.py` (service tests)
  - `test_auth_api.py` (API endpoint tests)
  - `test_zerodha_mapping.py` (broker-specific tests)

---

## Running Tests

### Basic Test Execution

```bash
# Run all tests
uv run pytest test/ -v

# Run specific test file
uv run pytest test/test_auth.py -v

# Run specific test class
uv run pytest test/test_auth.py::TestUserAuthentication -v

# Run specific test function
uv run pytest test/test_auth.py::TestUserAuthentication::test_login_success -v
```

### Advanced Test Options

```bash
# Run with coverage report
uv run pytest test/ --cov=services --cov-report=html

# Run only fast tests (skip slow integration tests)
uv run pytest test/ -m "not slow" -v

# Run tests with detailed output
uv run pytest test/ -vv --tb=long

# Run tests and stop on first failure
uv run pytest test/ -x

# Run tests in parallel (faster)
uv run pytest test/ -n auto

# Run with specific Python version
uv run pytest test/ --python-version=3.12
```

### Performance Testing

```bash
# Show slowest tests
uv run pytest test/ --durations=10

# Profile test execution
uv run pytest test/ --profile
```

---

## Writing Tests

### Basic Test Template

```python
import unittest
import sys
from datetime import datetime
from decimal import Decimal

sys.path.insert(0, 'D:\\sem4\\openalgo')

class TestMyFeature(unittest.TestCase):
    """Test suite for MyFeature functionality"""
    
    def setUp(self):
        """Run before each test"""
        self.test_data = {"symbol": "NSE:SBIN-EQ", "quantity": 100}
    
    def tearDown(self):
        """Run after each test"""
        pass
    
    def test_valid_scenario(self):
        """Test happy path"""
        result = my_function(self.test_data)
        self.assertEqual(result, expected_value)
    
    def test_invalid_input(self):
        """Test error handling"""
        with self.assertRaises(ValueError):
            my_function(invalid_input)
```

### Test Naming Convention

**Pattern**: `test_<what_is_being_tested>_<condition_or_expected_result>`

**Examples**:
```python
def test_order_placement_with_valid_symbol(self):
def test_margin_calculation_with_zero_balance(self):
def test_negative_quantity_rejected(self):
def test_order_status_updated_after_execution(self):
def test_invalid_price_raises_error(self):
```

---

## Test Patterns

### Pattern 1: Unit Testing (Business Logic)

```python
def test_margin_calculation(self):
    """Test margin calculation logic"""
    # Arrange
    balance = Decimal("100000.00")
    used_margin = Decimal("20000.00")
    
    # Act
    available = balance - used_margin
    
    # Assert
    self.assertEqual(available, Decimal("80000.00"))
```

### Pattern 2: Validation Testing

```python
def test_invalid_symbol_rejected(self):
    """Test that invalid symbols are rejected"""
    valid_symbols = ["NSE:SBIN-EQ", "NFO:NIFTY24JAN24000CE"]
    invalid_symbol = "INVALID"
    
    self.assertTrue(invalid_symbol not in valid_symbols)
```

### Pattern 3: State Transition Testing

```python
def test_order_status_transitions(self):
    """Test valid order status transitions"""
    valid_transitions = {
        "PENDING": ["OPEN", "REJECTED"],
        "OPEN": ["PARTIALLY_FILLED", "FILLED", "CANCELLED"],
        "FILLED": []  # Terminal state
    }
    
    current_status = "OPEN"
    next_status = "FILLED"
    
    self.assertIn(next_status, valid_transitions[current_status])
```

### Pattern 4: Error Handling Testing

```python
def test_zero_quantity_raises_error(self):
    """Test that zero quantity is rejected"""
    quantity = 0
    
    # Should fail validation
    is_valid = quantity > 0
    self.assertFalse(is_valid)
```

### Pattern 5: Financial Calculation Testing

```python
def test_realized_pnl_calculation(self):
    """Test realistic P&L calculation with Decimal precision"""
    buy_qty = 100
    buy_price = Decimal("500.25")
    sell_qty = 100
    sell_price = Decimal("520.75")
    
    # Calculate P&L
    pnl = sell_qty * (sell_price - buy_price)
    
    self.assertEqual(pnl, Decimal("2050.00"))
```

---

## Mocking & Fixtures

### Using Fixtures

```python
import pytest

@pytest.fixture
def valid_order():
    return {
        "symbol": "NSE:SBIN-EQ",
        "quantity": 100,
        "price": Decimal("500.00"),
        "side": "BUY"
    }

def test_order_validation(valid_order):
    # valid_order is automatically injected
    assert valid_order["quantity"] > 0
```

### Mocking External Calls

```python
from unittest.mock import Mock, patch

@patch('services.order_service.broker_api.place_order')
def test_place_order_calls_broker(mock_broker_api):
    mock_broker_api.return_value = {"order_id": "123"}
    
    result = place_order({"symbol": "NSE:SBIN-EQ"})
    
    assert result["order_id"] == "123"
    mock_broker_api.assert_called_once()
```

### Mock Setup Examples

```python
# Mock a database query
with patch('database.Order.query.filter_by') as mock_query:
    mock_query.return_value.first.return_value = order_mock
    result = get_order(order_id)
    assert result == order_mock

# Mock API response
with patch('requests.post') as mock_post:
    mock_post.return_value.json.return_value = {"status": "success"}
    response = api_call()
    assert response["status"] == "success"
```

---

## Coverage & CI

### Check Test Coverage

```bash
# Generate coverage report
uv run pytest test/ --cov=services --cov-report=term-missing

# HTML coverage report
uv run pytest test/ --cov=services --cov-report=html
# Open htmlcov/index.html in browser
```

### Coverage Targets

```
| Module | Target |
|--------|--------|
| services/ | 85%+ |
| database/ | 80%+ |
| utils/ | 90%+ |
| broker/ | 70%+ |
| restx_api/ | 75%+ |
```

### CI/CD Integration

Tests run automatically on every push:
1. **GitHub Actions** triggers on PR
2. Runs: `uv run pytest test/ --cov`
3. Fails if coverage drops below threshold
4. Comments on PR with results

---

## Best Practices

### ✅ DO

- ✅ Write one assertion per test (when possible)
- ✅ Use descriptive test names
- ✅ Test both happy path and error cases
- ✅ Use fixtures for repeated setup
- ✅ Mock external dependencies
- ✅ Keep tests fast (<100ms each)
- ✅ Test business logic, not implementation
- ✅ Document complex test scenarios

### ❌ DON'T

- ❌ Don't test third-party libraries
- ❌ Don't make tests dependent on each other
- ❌ Don't use actual databases in unit tests
- ❌ Don't make network calls in tests
- ❌ Don't use hard-coded paths
- ❌ Don't skip tests with `@skip` without reason
- ❌ Don't write tests in production code
- ❌ Don't use sleep() in tests

---

## Common Test Scenarios

### Testing Decimal Precision (Financial)

```python
def test_financial_calculation_precision(self):
    """Financial calculations require Decimal, not float"""
    price = Decimal("100.15")
    quantity = 50
    total = price * quantity
    
    self.assertEqual(total, Decimal("5007.50"))
    self.assertIsInstance(total, Decimal)
```

### Testing Time-Based Logic

```python
def test_trade_execution_time_recorded(self):
    """Verify trade execution time is recorded"""
    before = datetime.now()
    execute_trade()
    after = datetime.now()
    
    trade = get_latest_trade()
    self.assertGreaterEqual(trade.timestamp, before)
    self.assertLessEqual(trade.timestamp, after)
```

### Testing Symbol Validation

```python
def test_valid_symbol_formats(self):
    """Test all valid symbol formats are accepted"""
    valid_symbols = [
        "NSE:SBIN-EQ",           # Equity
        "NFO:NIFTY24JAN24000CE", # Options
        "NSE:NIFTY-INDEX",       # Index
        "BSE:SENSEX-INDEX"       # BSE Index
    ]
    
    for symbol in valid_symbols:
        self.assertTrue(is_valid_symbol(symbol))
```

---

## Debugging Failed Tests

### Step 1: Get Detailed Output

```bash
uv run pytest test/test_failing.py -vv --tb=long
```

### Step 2: Print Debug Info

```python
def test_failing_test(self):
    value = complex_function()
    print(f"\nDebug: value={value}, type={type(value)}")
    self.assertEqual(value, expected)
```

Run with `-s` to see prints:
```bash
uv run pytest test/test_failing.py -s
```

### Step 3: Use Python Debugger

```python
def test_with_breakpoint(self):
    value = complex_function()
    breakpoint()  # Execution pauses here
    self.assertEqual(value, expected)
```

---

## Continuous Integration

### GitHub Actions (Automated)

All tests run automatically when you push:

```yaml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: astral-sh/setup-uv@v1
      - run: uv run pytest test/ --cov
```

### Local Pre-commit Hook

Run tests before git commit:

```bash
#!/bin/bash
# .git/hooks/pre-commit
uv run pytest test/ -q || exit 1
```

---

## Additional Resources

- **pytest Documentation**: https://docs.pytest.org
- **unittest (Python stdlib)**: https://docs.python.org/3/library/unittest.html
- **Coverage.py**: https://coverage.readthedocs.io

---

**Last Updated**: March 10, 2026  
**Status**: Production Ready ✅  
**Version**: 1.0  
