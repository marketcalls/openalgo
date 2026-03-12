# 📝 PR TEMPLATES & EXECUTION CHECKLIST

**Purpose**: Use these templates for fastest PR creation  
**Time Saved**: 10-15 min per PR  
**Quality**: Ensures consistent, professional PRs

---

## TEMPLATE 1: Test PR (Most Common - 30+ PRs)

### Command Line Quick-Add

```bash
# 1. Create test file
touch test/test_[service_name].py

# 2. Copy template below into file
# 3. Write 5-6 test functions
# 4. Run tests: pytest test/test_[service_name].py -v
# 5. Create PR with description template

# Time: 1-2 hours per PR
```

### File Template

```python
# test/test_[service_name].py
"""
Comprehensive tests for [service_name]

These tests verify:
- Core functionality
- Edge case handling
- Error conditions
- Broker-specific behavior
"""

import pytest
from [module_path] import [function_1, function_2]
from database.auth_db import verify_api_key


class Test[ServiceName]:
    """Test suite for [service_name]"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures before each test"""
        self.test_api_key = "test_api_key_12345"
        self.test_symbol = "SBIN-EQ"
        yield
        # Cleanup (if needed)

    # TEST 1: Success case
    def test_[function_name]_success(self):
        """Test [function_name] with valid inputs"""
        # Arrange
        input_data = {
            "symbol": self.test_symbol,
            "quantity": 100,
            # ... more fields
        }

        # Act
        result = [function_name](input_data, self.test_api_key)

        # Assert
        assert result is not None
        assert isinstance(result, dict)
        assert "status" in result

    # TEST 2: Edge case
    def test_[function_name]_zero_quantity(self):
        """Test [function_name] with zero quantity"""
        # Arrange
        input_data = {
            "symbol": self.test_symbol,
            "quantity": 0,  # Edge case
        }

        # Act & Assert
        with pytest.raises(ValueError):
            [function_name](input_data, self.test_api_key)

    # TEST 3: Error condition
    def test_[function_name]_invalid_api_key(self):
        """Test [function_name] with invalid API key"""
        # Arrange
        input_data = {"symbol": self.test_symbol}
        invalid_key = "invalid_key"

        # Act
        result = [function_name](input_data, invalid_key)

        # Assert
        assert result["status"] == "error"
        assert "API key" in result.get("message", "")

    # TEST 4: Data validation
    def test_[function_name]_missing_symbol(self):
        """Test [function_name] without required symbol"""
        # Arrange
        input_data = {"quantity": 100}  # Missing symbol

        # Act & Assert
        with pytest.raises(KeyError):
            [function_name](input_data, self.test_api_key)

    # TEST 5: Broker-specific
    def test_[function_name]_zerodha_specific(self):
        """Test [function_name] with Zerodha-specific behavior"""
        # Arrange
        input_data = {
            "symbol": self.test_symbol,
            "product": "MIS",  # Zerodha specific
        }

        # Act
        result = [function_name](input_data, self.test_api_key, broker="zerodha")

        # Assert
        assert result["broker"] == "zerodha"

    # TEST 6: Response format
    def test_[function_name]_response_format(self):
        """Test [function_name] returns properly formatted response"""
        # Arrange
        input_data = {"symbol": self.test_symbol}

        # Act
        result = [function_name](input_data, self.test_api_key)

        # Assert
        assert "status" in result  # Required field
        assert result["status"] in ["success", "error"]
        assert "message" in result  # Required field
        assert isinstance(result.get("data"), (dict, list, type(None)))


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
```

### PR Description Template

```markdown
## test(services): add comprehensive tests for [service_name]

**Objective**: Add production-ready test coverage for `[service_name]`

**What was tested**:
- ✅ [function_1]() - 3 test functions covering success, edge case, error
- ✅ [function_2]() - 2 test functions covering success, API key validation
- ✅ Broker-specific behavior for Zerodha, Angel, Dhan

**Test Coverage Summary**:
```
test_[service]_success           ✅ Happy path
test_[service]_edge_case         ✅ Boundary values
test_[service]_invalid_input     ✅ Error handling
test_[service]_missing_field     ✅ Data validation
test_[service]_broker_specific   ✅ Broker variations
test_[service]_response_format   ✅ Contract validation
```

**How to Verify**:
```bash
pytest test/test_[service_name].py -v
# Expected: 6 passed in X.XXs
```

**Files Modified**:
- `test/test_[service_name].py` (NEW - ~250 lines)

**Why This Matters**:
`[service_name]` is critical for [USE_CASE]. Without tests, we risk:
- Silent failures in production
- Regressions on new broker additions
- Undetected edge case bugs

**Related Issues**: Closes #[issue_number]

**Checklist**:
- [x] Tests run successfully locally
- [x] All assertions pass
- [x] Code follows PEP 8
- [x] Docstrings added to test functions
- [x] No debugging print statements
```

---

## TEMPLATE 2: Refactoring PR (Extract Duplication - 10 PRs)

### Quick Checklist

```bash
# 1. Identify duplicated code (check WORK_LIST.md)
# 2. Create new utils file
# 3. Extract common function
# 4. Refactor N service files to use it
# 5. Add tests if not already present
# 6. Update imports

# Time: 1-1.5 hours per PR
```

### File Template - New Utility

```python
# utils/format_utils.py
"""
Common formatting utilities for data transformation

Used by: holdings_service, orderbook_service, tradebook_service, positionbook_service
"""

from typing import Any


def format_decimal(value: float | int) -> float:
    """
    Format numeric value to 2 decimal places.

    Args:
        value: Numeric value to format (int or float)

    Returns:
        Rounded value to 2 decimal places, or original value if not numeric

    Example:
        >>> format_decimal(100.456)
        100.46
        >>> format_decimal(100)
        100.0
    """
    if isinstance(value, (int, float)):
        return round(value, 2)
    return value


def format_holdings_data(holdings_data: list[dict] | dict) -> list[dict] | dict:
    """
    Format all numeric values in holdings data to 2 decimal places.

    Applies formatting to P&L fields only, preserves quantity as integer.

    Args:
        holdings_data: Holdings list or single holding dict

    Returns:
        Holdings with formatted numeric values

    Example:
        >>> data = [{"symbol": "SBIN", "pnl": 100.456}]
        >>> format_holdings_data(data)
        [{"symbol": "SBIN", "pnl": 100.46}]
    """
    if isinstance(holdings_data, list):
        return [
            {
                key: format_decimal(value) if key in ["pnl", "pnlpercent"] else value
                for key, value in item.items()
            }
            for item in holdings_data
        ]
    return holdings_data


def format_order_data(order_data: list[dict] | dict) -> list[dict] | dict:
    """
    Format order data numeric values to 2 decimal places.

    Preserves quantity fields as integers, sets price to 0 for market orders.

    Args:
        order_data: Order list or single order dict

    Returns:
        Orders with formatted numeric values

    Example:
        >>> data = [{"symbol": "SBIN", "price": 100.456, "quantity": 5.5}]
        >>> format_order_data(data)
        [{"symbol": "SBIN", "price": 100.46, "quantity": 5}]
    """
    quantity_fields = {
        "quantity",
        "qty",
        "filledqty",
        "filled_quantity",
        "tradedqty",
        "traded_quantity",
    }

    if isinstance(order_data, list):
        formatted_orders = []
        for item in order_data:
            formatted_item = {}
            for key, value in item.items():
                if isinstance(value, (int, float)):
                    if key.lower() in quantity_fields:
                        formatted_item[key] = int(value)
                    else:
                        formatted_item[key] = format_decimal(value)
                else:
                    formatted_item[key] = value

            # Market orders should have price = 0
            if formatted_item.get("pricetype", "").upper() == "MARKET":
                formatted_item["price"] = 0.0

            formatted_orders.append(formatted_item)
        return formatted_orders
    return order_data
```

### Refactoring Template (One Per Affected File)

```python
# In services/holdings_service.py

# BEFORE:
# def format_decimal(value):
#     """Format numeric value to 2 decimal places"""
#     if isinstance(value, (int, float)):
#         return round(value, 2)
#     return value

# AFTER:
from utils.format_utils import format_decimal, format_holdings_data

# Rest of file unchanged - just use imported functions
```

### PR Description Template

```markdown
## refactor: extract decimal formatting into shared utility

**Objective**: Eliminate code duplication across 4 services

**Current State**:
- `format_decimal()` duplicated in 4 files
- ~160 lines of duplicate code
- No single source of truth for rounding logic

**Changes**:
- ✅ Created `utils/format_utils.py` with shared functions
- ✅ Refactored 4 services to import from utility
- ✅ Added comprehensive docstrings and type hints
- ✅ Added unit tests for utility functions

**Code Impact**:
```
services/holdings_service.py        -40 lines (use utils)
services/orderbook_service.py       -40 lines (use utils)
services/tradebook_service.py       -40 lines (use utils)
services/positionbook_service.py    -40 lines (use utils)
utils/format_utils.py               +80 lines (shared, tested)
────────────────────────────────────────
NET SAVINGS                         -160 lines
```

**Benefits**:
- Single source of truth for formatting
- Easier to modify rounding rules in future
- Clearer separation of concerns
- No logic duplication across services

**Files Changed**:
- `utils/format_utils.py` (NEW)
- `services/holdings_service.py` (refactored)
- `services/orderbook_service.py` (refactored)
- `services/tradebook_service.py` (refactored)
- `services/positionbook_service.py` (refactored)

**How to Verify**:
```bash
# All existing tests should still pass
pytest test/test_holdings_service.py -v
pytest test/test_orderbook_service.py -v
pytest test/test_format_utils.py -v  # New utility tests
```

**Checklist**:
- [x] All affected services refactored
- [x] No functional changes (same behavior)
- [x] Tests pass locally
- [x] No breaking changes to exports
```

---

## TEMPLATE 3: Documentation PR (Add Docstrings - 15 PRs)

### Quick Checklist

```bash
# 1. Pick service file from WORK_LIST.md
# 2. Add module-level docstring
# 3. Document all public functions
# 4. Add type hints to function signatures
# 5. Add Usage Examples section
# 6. Run: python -m pydoc -b services/[service].py

# Time: 45 min - 1 hour per PR
```

### Module-Level Docstring Template

```python
# services/[service_name].py
"""
[Service Name] Service

Handles [brief description of responsibility].

Example Usage:
    >>> from services.[service_name] import [function_name]
    >>> result = [function_name](data={"symbol": "SBIN-EQ"})
    >>> print(result["status"])
    'success'

Core Functions:
    - [function_1](): [Description]
    - [function_2](): [Description]
    - [function_3](): [Description]

Configuration:
    Environment variables:
    - BROKER_API_KEY: Required broker API key
    - RATE_LIMIT: Optional rate limit config

Dependencies:
    - database.auth_db: Authentication
    - utils.logging: Logging setup

Error Handling:
    Returns tuple of (success: bool, response: dict, status_code: int)
    Common errors:
    - 400 Bad Request: Invalid input data
    - 403 Forbidden: Invalid API key
    - 500 Server Error: Broker API failure

Thread Safety:
    This service is thread-safe. Multiple threads can call
    functions simultaneously without race conditions.
"""

import logging
from typing import Any, Tuple

logger = logging.getLogger(__name__)


def [function_name](
    data: dict[str, Any],
    api_key: str | None = None,
    broker: str = "zerodha"
) -> Tuple[bool, dict[str, Any], int]:
    """
    [Function short description].

    [Longer description explaining the function's behavior, edge cases,
    and any important considerations.]

    Args:
        data: Request data containing required fields:
            - symbol (str): Trading symbol in OpenAlgo format (e.g., "SBIN-EQ")
            - quantity (int): Number of shares/contracts to trade
            - [other_fields]
        api_key: Optional API key for authentication.
            If not provided, uses session-based auth.
        broker: Broker name for broker-specific handling.
            Default: "zerodha"

    Returns:
        Tuple of (success, response, status_code) where:
        - success (bool): True if operation succeeded
        - response (dict): Response data or error message
        - status_code (int): HTTP status code (200, 400, 403, 500, etc)

    Raises:
        ValueError: If required data field is missing or invalid
        ConnectionError: If broker API is unreachable
        KeyError: If configuration is incomplete

    Example:
        >>> result = [function_name](
        ...     data={"symbol": "SBIN-EQ", "quantity": 100},
        ...     api_key="test_key"
        ... )
        >>> success, response, status = result
        >>> if success:
        ...     print(f"Order placed: {response['order_id']}")
        ... else:
        ...     print(f"Error: {response['message']}")

    Note:
        - This function respects the ORDER_RATE_LIMIT setting
        - Returns immediately even if broker processing is async
        - Order status should be checked separately
    """
```

### PR Description Template

```markdown
## docs(services): add comprehensive docstrings to [service_name]

**Objective**: Document `[service_name]` for maintainability

**What was documented**:
- ✅ Module-level purpose and usage
- ✅ All public functions with parameters/returns
- ✅ Usage examples for key functions
- ✅ Error handling and exceptions
- ✅ Configuration requirements
- ✅ Type hints added to signatures

**Documentation Coverage**:
```
Module docstring            ✅ Added
[function_1]() docs         ✅ Added  
[function_2]() docs         ✅ Added
[function_3]() docs         ✅ Added
Type hints                   ✅ Added to 8 functions
Configuration docs           ✅ Added
Error codes documented       ✅ Added
Examples provided            ✅ Added
```

**How to Verify**:
```bash
# View documentation in terminal
python -m pydoc services.[service_name]

# Or generate HTML docs
python -m pydoc -b services.[service_name]
```

**Files Modified**:
- `services/[service_name].py` (+80 lines of documentation)

**Why This Matters**:
Clear documentation helps:
- New contributors understand the codebase
- Future maintenance and debugging
- API contract clarity for consumers
- Type checking with static analysis tools

**Checklist**:
- [x] Module docstring clear and complete
- [x] All public functions documented
- [x] Type hints on function signatures
- [x] Examples provided where helpful
- [x] No grammar/spelling errors
- [x] Follows PEP 257 style guide
```

---

## TEMPLATE 4: Code Quality PR (Add Type Hints - 10 PRs)

### Command Quick-Check

```bash
# Check current type hint coverage
python -m pylance analyze services/[service_name].py

# Or install pylint
uv add pylint
pylint services/[service_name].py
```

### Type Hints Template

**Example: Before & After**

```python
# BEFORE (untyped)
def format_order_data(order_data):
    if isinstance(order_data, list):
        return [...]
    return order_data

def get_broker_config(broker_name):
    try:
        config = load_config(broker_name)
        return config
    except:
        return None

# AFTER (fully typed)
from typing import Any, Optional, Dict, List

def format_order_data(
    order_data: List[Dict[str, Any]] | Dict[str, Any]
) -> List[Dict[str, Any]] | Dict[str, Any]:
    """Format all numeric values in order data.
    
    Args:
        order_data: Single order dict or list of orders
        
    Returns:
        Formatted order(s) with rounded decimals and normalized prices
    """
    if isinstance(order_data, list):
        return [...]
    return order_data


def get_broker_config(broker_name: str) -> Optional[Dict[str, Any]]:
    """Get broker configuration.
    
    Args:
        broker_name: Name of the broker (e.g., 'zerodha')
        
    Returns:
        Configuration dict or None if not found
        
    Raises:
        ConnectionError: If broker API is unreachable
    """
    try:
        config: Dict[str, Any] = load_config(broker_name)
        return config
    except Exception as e:
        logger.error(f"Failed to load config for {broker_name}: {e}")
        return None
```

### PR Description Template

```markdown
## refactor: add comprehensive type hints to [service_name]

**Objective**: Improve code clarity and enable static type checking

**Type Hints Added**:
- ✅ Function parameters (8 functions)
- ✅ Return types (8 functions)
- ✅ Class attributes (if applicable)
- ✅ Complex type aliases (Dict, List, Optional)

**Benefits**:
- IDE autocomplete now works (better DX)
- Type checker (mypy) can catch errors
- Self-documenting code (no need for typing comments)
- Future-proof for Python 3.13+

**Files Modified**:
- `services/[service_name].py` (+50 lines of type hints)

**How to Verify**:
```bash
mypy services/[service_name].py
# Expected: Success: no issues found
```

**Checklist**:
- [x] All public functions typed
- [x] Complex types documented
- [x] No `Any` without reason
- [x] Tests still pass
```

---

## DAILY EXECUTION SCHEDULE

### 7:30-10:00 AM: Stream 1 Test PR

```bash
cd ~/openalgo

# Step 1: Create test file
touch test/test_[service].py

# Step 2: Write tests using TEMPLATE 1
# (Copy template, modify for your service, write 5-6 tests)

# Step 3: Run tests
pytest test/test_[service].py -v

# Step 4: Commit & push
git add test/test_[service].py
git commit -m "test(services): add tests for [service]"
git push origin [your-branch]

# Step 5: Create PR on GitHub with DESCRIPTION TEMPLATE
```

### 10:00-1:00 PM: Stream 2 Documentation or Refactoring PR

```bash
cd ~/openalgo

# IF Documentation:
# Step 1: Add docstrings to services/[service].py using TEMPLATE 3
# Step 2: Run pydoc check
# Step 3: Commit & push

# IF Refactoring:
# Step 1: Create utils/[new_utility].py using TEMPLATE 2
# Step 2: Refactor services using new utility  
# Step 3: Test that everything works
# Step 4: Commit & push
```

### 1:00-3:30 PM: Stream 3 Code Quality PR

```bash
cd ~/openalgo

# Step 1: Pick service with no type hints
# Step 2: Add type hints using TEMPLATE 4
# Step 3: Run mypy check
# Step 4: Commit & push
```

### 3:30-5:00 PM: Monitor & Polish

```bash
# Check for feedback on PRs
# Make quick fixes if review comments
# Update FOSS_HACKATHON_2026_TRACKER.md with status
# Pick tomorrow's 3 PRs from COMPREHENSIVE_WORK_LIST.md
```

---

## Success Formula

```
TIER 1: Pick from CRITICAL list first      (20 PRs - Weeks 1-2)
TIER 2: Pick from HIGH/MEDIUM list next    (25 PRs - Weeks 2-3)
TIER 3: Pick from NICE-TO-HAVE list last   (20+ PRs - Week 3-4)

Each PR = 1-2 hours of focused work
3 PRs/day × 20 days = 60 PRs minimum
4 PRs/day × 20 days = 80 PRs maximum
```

---

## Copy-Paste Ready: First PR Scaffolding

```bash
#!/bin/bash
# save as: create_pr.sh
# usage: bash create_pr.sh place_order_service tests

SERVICE_NAME=$1
PR_TYPE=$2  # tests, docs, refactor, quality

# Create test file
cat > test/test_${SERVICE_NAME}.py << 'EOF'
"""Comprehensive tests for [service]"""
import pytest
from services.${SERVICE_NAME} import main_function

class Test$(echo ${SERVICE_NAME} | sed 's/_//g'):
    def test_success(self):
        result = main_function({})
        assert result is not None

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
EOF

echo "✅ Created test/test_${SERVICE_NAME}.py"
echo "📝 Edit the file to add your test functions"
echo "🧪 Run tests with: pytest test/test_${SERVICE_NAME}.py -v"
```

---

## 🎯 Final Checklist Before Pushing PR

- [ ] Code follows PEP 8 (`black --check file.py`)
- [ ] All tests pass locally (`pytest test_file.py -v`)
- [ ] No print() statements left in code
- [ ] Docstrings added/updated
- [ ] Type hints present (for new/modified functions)
- [ ] No unnecessary imports
- [ ] No hardcoded values (use environment variables)
- [ ] Error handling is specific (not bare `except:`)
- [ ] PR description is clear (judges read this)
- [ ] Commit message follows conventional commits

---

**Ready to start?** Pick TEMPLATE 1 above and copy into your first test file. 

**Time to first PR**: 2 hours  
**Expected approval**: HIGH (critical gap)  
**Momentum**: Ready for 67 more! 🚀
