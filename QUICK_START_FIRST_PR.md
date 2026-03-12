# 🚀 QUICK-START: Pick Your First PR Today

**Generated**: March 10, 2026  
**Read Time**: 5 minutes  
**Action Time**: Pick one item in next 30 seconds

---

## The Challenge ✅

- **Goal**: 70+ PRs in 20 days = **3-4 PRs/day**
- **Quality**: Production-ready (not quick hacks)
- **Timeline**: March 10 → April 1, 2026

## Your First 3 PRs (Start Tomorrow Morning)

### PR #1: Place Order Service Tests  ⏱️ 2 hours

**Why**: Real money transactions = critical for credibility

```bash
# File to test
services/place_order_service.py

# Create test file
test/test_place_order_comprehensive.py

# Test cases needed:
# 1. Valid order validation
# 2. Invalid order rejection
# 3. API key verification  
# 4. Rate limiting enforcement
# 5. Broker error handling
# 6. Order status in database

# Expected lines: ~250-300 test code
```

**Effort**: 2 hours  
**Expected approval**: HIGH (critical gap)  
**Repository**: github.com/marketcalls/openalgo

---

### PR #2: Holdings Service Tests + Refactoring  ⏱️ 1.5 hours

**Why**: Data formatting bugs affect every trade

```bash
# Problems to fix:
services/holdings_service.py (line 12-45)
  - Decimal formatting duplicated 4+ times
  - No tests for format_holdings_data()

# Create test file
test/test_holdings_service.py

# Create shared utility (BONUS: Eliminates 4 duplicates!)
utils/format_utils.py
  - extract format_decimal()
  - extract format_holdings_data()

# Then refactor:
services/holdings_service.py         (use new utils)
services/orderbook_service.py        (use new utils)
services/tradebook_service.py        (use new utils)
services/positionbook_service.py     (use new utils)

# This is 1 PR + 1 Refactor PR = 2 PRs, 1.5 hours total
```

**Effort**: 1.5 hours  
**Expected approval**: VERY HIGH (improves 4 files + tests)  
**Bonus**: Counts as code quality + test + refactoring PR

---

### PR #3: Place Order Endpoint API Tests  ⏱️ 1 hour

**Why**: REST API endpoints are what judges test first

```bash
# File to test  
restx_api/place_order.py

# Create/update test file
test/test_place_order_api.py

# Test cases:
# 1. Valid order request → 200 OK
# 2. Missing API key → 403 Forbidden
# 3. Invalid symbol → 400 Bad Request
# 4. Rate limit exceeded → 429 Too Many Requests
# 5. Broker connection failure → 500 Server Error

# Expected lines: ~150-200 test code
```

**Effort**: 1 hour  
**Expected approval**: HIGH (direct API testing)  
**Judges will run**: `curl -X POST http://localhost:5000/api/v1/place_order ...`

---

## Tomorrow's Schedule

```
7:30 AM  - Start PR #1 (place_order_service.py tests)
         - Write 5-6 test functions
         - Run: pytest test/test_place_order_comprehensive.py -v
         - Create PR (with good description)
         
9:30 AM  - Start PR #2 (holdings refactoring + tests)
         - Create utils/format_utils.py
         - Add tests for format_decimal()
         - Refactor 4 service files
         - Create PR

11:00 AM - Start PR #3 (REST API tests)
         - Write endpoint tests
         - Test error conditions
         - Create PR

1:00 PM  - Push PRs & Watch for Feedback
         - Check if maintainers have questions
         - Prepare for quick fixes

2:00 PM  - Pick next 3 PRs from work list
         - Repeat structure
```

---

## PR Description Template (Copy-Paste Ready)

```markdown
## Test: [Service Name] Comprehensive Testing

**Objective**: Add production-ready test coverage for [service_name]

**Changes**:
- ✅ 6 test functions covering core logic
- ✅ Edge case handling validated
- ✅ Error conditions tested
- ✅ Broker-specific variations verified

**Test Coverage**:
- [function_name](): [X test cases]
- [function_name](): [X test cases]
- [function_name](): [X test cases]

**How to Verify**:
```bash
pytest test/test_[service].py -v
# Expected: 6 passed, 0 failed
```

**Files Changed**:
- test/test_[service].py (NEW)
- services/[service].py (unchanged)

**Why This Matters**:
[SERVICE_NAME] is critical for [USE_CASE]. Without tests, we risk regressions in production trading.

---

## Refactor: Eliminate Decimal Formatting Duplication

**Objective**: Extract common `format_decimal()` logic into shared utility

**Current State**: 
- Duplicated in 4 service files
- No type hints
- Inconsistent documentation

**Changes**:
- ✅ Created utils/format_utils.py with shared functions
- ✅ Refactored 4 services to use new utility
- ✅ Added comprehensive docstrings
- ✅ Added type hints

**Files Changed**:
- utils/format_utils.py (NEW - 50 lines)
- services/holdings_service.py (refactored)
- services/orderbook_service.py (refactored)
- services/tradebook_service.py (refactored)
- services/positionbook_service.py (refactored)

**Impact**:
- 40 lines removed from 4 files = 160 lines eliminated
- Single source of truth for formatting
- Easier to maintain rounding precision

---

## API Endpoint Test: Place Order

**Objective**: Add comprehensive tests for /api/v1/place_order endpoint

**Test Scenarios**:
1. ✅ Valid order placement (200 OK)
2. ✅ Missing API key (403 Forbidden)
3. ✅ Invalid symbol (400 Bad Request)
4. ✅ Insufficient margin (400 Bad Request)
5. ✅ Rate limit exceeded (429 Too Many Requests)
6. ✅ Broker error (500 Server Error)

**How to Verify**:
```bash
pytest test/test_place_order_api.py -v
curl -X POST http://localhost:5000/api/v1/place_order \
  -H "Content-Type: application/json" \
  -d '{"apikey":"test","symbol":"SBIN-EQ","quantity":1,"price":500,"action":"BUY"}'
```

**Files Changed**:
- test/test_place_order_api.py (NEW)
- restx_api/place_order.py (unchanged)
```

---

## Key Things to Know Before Starting

### ✅ Setup Checklist
- [ ] You have local dev environment running
- [ ] `pytest` is installed (`pip list | grep pytest`)
- [ ] You can run: `pytest test/test_action_center.py -v` (existing test)
- [ ] You have git access to your fork
- [ ] You know how to create PRs on GitHub

### ✅ Python Testing Pattern Used

```python
import pytest
from database.auth_db import verify_api_key

class TestPlaceOrder:
    def setup_method(self):
        """Run before each test"""
        self.test_api_key = "test_key_12345"
    
    def test_valid_order(self):
        """Test placing a valid order"""
        # Arrange
        order_data = {
            "symbol": "SBIN-EQ",
            "quantity": 1,
            "price": 500,
            "action": "BUY"
        }
        
        # Act
        success, response, status = place_order(order_data, self.test_api_key)
        
        # Assert
        assert success == True
        assert status == 200
        assert "order_id" in response
```

### ✅ File Organization

```
Each service test file follows pattern:
test/test_[service_name].py
├── Imports
├── Setup fixtures
├── Class TestService:
│   ├── test_success_case()
│   ├── test_edge_case_1()
│   ├── test_edge_case_2()
│   ├── test_error_case()
│   └── test_broker_specific_handling()
└── if __name__ == "__main__":
    └── pytest.main([__file__, "-v"])
```

### ✅ What Makes a Good PR

```
✅ GOOD PR:
- Single concern (only tests, or only refactoring)
- 150-400 lines changed
- Clear description (judges can understand)
- All tests passing locally
- No unnecessary comments
- Follows existing code style

❌ BAD PR:
- Many unrelated changes
- 1000+ lines (too much)
- Vague description
- Failing tests
- Excessive comments
- Style doesn't match codebase
```

---

## Getting Unstuck (Troubleshooting)

### Problem: Import errors when running tests

```python
# Solution: Add to test file
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

### Problem: Database not initialized

```bash
# Solution: Initialize test DB
cd d:\sem4\openalgo
uv run python -c "from database.auth_db import init_db; init_db()"
```

### Problem: Can't find existing test as reference

```bash
# Browse: test/test_action_center.py (most comprehensive existing test)
# This shows patterns you should follow
```

### Problem: Pytest not found

```bash
# Solution
uv add pytest
# Or
pip install pytest
```

---

## Next Steps After First 3 PRs

**Pattern**: Pick 3 from work list each day

**Priority Order**:
1. **TIER 1 Tests** (place_order, margin, option_greeks, flow_executor, websocket) - Critical
2. **Data Service Tests** (history, quotes, depth, option_chain) - Important
3. **Database Tests** (auth, action_center, flow_db, sandbox) - Essential
4. **API Endpoint Tests** (all 15 remaining) - Expected
5. **Documentation** (service docstrings, database schema) - Competitive
6. **Refactoring** (duplicate code, complex functions) - Excellence

**Formula for 70+ PRs**:
- 30 Test PRs (1-2 hours each)
- 10 Refactoring PRs (1-2 hours each)  
- 15 Documentation PRs (45 min - 1 hour each)
- 10 Code Quality PRs (1 hour each)
- 5 Feature Completion PRs (1-2 hours each)

---

## Backup Resources

**Stuck?** Check these files:
- [COMPREHENSIVE_WORK_LIST.md](COMPREHENSIVE_WORK_LIST.md) - Full analysis
- [test/test_action_center.py](test/test_action_center.py) - Reference implementation
- [services/place_order_service.py](services/place_order_service.py) - Source code
- [CLAUDE.md](CLAUDE.md) - Project architecture

**Questions?**
- Read CLAUDE.md for architecture
- Look at similar existing tests
- Check existing service implementations

---

## 🎯 Your Goal for Next 24 Hours

```
✅ Create 3 PRs
✅ Each with tests or refactoring
✅ Each with clear description
✅ All passing locally
✅ Ready for maintainer review
```

**Start now**: Pick PR #1 (Place Order tests), spend 2 hours writing 6 test functions.

**Expected result**: HIGH approval rate (critical gap, solid work) + momentum for next 67 PRs.

---

**Let's GO! 🚀** You got this!
