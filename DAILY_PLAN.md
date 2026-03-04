# OpenAlgo FOSS Hack 2026 — Daily Contribution Plan

Generated: 2026-02-28 | Last Updated: 2026-03-01
Status: [0 PRs merged] [2 PRs open (#981, #993)] [4 issues opened (#949, #980, #992, #994)]

---

## CONTRIBUTION BACKLOG (priority ordered)

| ID | Title | Type | Est. Days | Merge Prob. | Status |
|----|-------|------|-----------|-------------|--------|
| B01 | Create `test/conftest.py` pytest fixtures | Test Infra | 1 | 95% | 🔲 TODO |
| B02 | Unit tests for `services/place_order_service.py` | Tests | 1 | 95% | ✅ DONE |
| B03 | Unit tests for `services/place_smart_order_service.py` | Tests | 1 | 95% | 🔲 TODO |
| B04 | Unit tests for `services/cancel_order_service.py` | Tests | 1 | 95% | 🔲 TODO |
| B05 | Unit tests for `services/basket_order_service.py` | Tests | 1 | 95% | 🔲 TODO |
| B06 | Unit tests for `services/close_position_service.py` | Tests | 1 | 95% | 🔲 TODO |
| B07 | Expand CI to run new test files | CI | 0.5 | 98% | 🔲 TODO |
| B08 | Docstrings for `database/` module (14 functions) | Docs | 0.5 | 98% | ✅ DONE |
| B09 | Docstrings for `utils/` module (30 functions) | Docs | 1 | 98% | 🔲 TODO |
| B10 | Docstrings for Zerodha broker adapter | Docs | 1 | 95% | 🔲 TODO |
| B11 | Docstrings for Angel broker adapter | Docs | 1 | 95% | 🔲 TODO |
| B12 | Docstrings for AliceBlue broker adapter | Docs | 1 | 95% | 🔲 TODO |
| B13 | Docstrings for `blueprints/auth.py` (10 functions) | Docs | 0.5 | 95% | 🔲 TODO |
| B14 | Replace `print()` with `logger` in 3 broker files | Refactor | 1 | 85% | 🔲 TODO |
| B15 | Fix Docker compose volumes (#910) | Bug Fix | 0.5 | 85% | 🔲 TODO |
| B16 | Fix `.env` file permissions (#960) | Bug Fix | 0.5 | 85% | 🔲 TODO |
| B17 | Document atexit SIGKILL limitation (#949) | Docs | 0.5 | 90% | 🔲 TODO |
| B18 | Mock broker adapter for integration tests | Test Infra | 2 | 80% | 🔲 TODO |
| B19 | End-to-end integration tests using mock broker | Tests | 2 | 80% | 🔲 TODO |
| B20 | Add integration tests to CI pipeline | CI | 0.5 | 85% | 🔲 TODO |
| B21 | Sandbox execution engine unit tests | Tests | 1 | 90% | 🔲 TODO |
| B22 | Type hints for service modules | Style | 1 | 92% | 🔲 TODO |
| B23 | Testing guide documentation | Docs | 1 | 95% | 🔲 TODO |
| B24 | Fix webhook KeyError bug (line 872) | Bug Fix | 0.5 | 80% | 🔲 TODO |
| B25 | Security edge-case tests in all test PRs | Security | ongoing | 90% | 🔲 TODO |
| B26 | Accessibility fixes (follow #940 pattern) | Design | 0.5 | 85% | 🔲 TODO |
| B27 | Secret logging audit in broker adapters | Security | 0.5 | 90% | 🔲 TODO |

---


## SECURITY & DESIGN INTEGRATION STRATEGY

> **Principle:** Don't add separate PRs. Make every existing PR smarter.

### 🔒 Security — Embedded in Every Task

| When | Security Action |
|------|----------------|
| **Test PRs** (Days 2, 3, 5, 7, 8, 12, 19, 21) | Add 2-3 security edge-case tests: empty keys, SQL injection inputs, oversized values, None handling |
| **Docstring PRs** (Days 4, 6, 11, 14, 20) | While reading code, note any `bare except:`, logged secrets, or missing validation — open 1 issue per week |
| **Day 15** (print→logger) | Also audit for accidental secret logging (`print(token)`) |
| **Mock broker** (Days 17-19) | Test auth bypass, expired tokens, revoked API keys |

### 🎨 Design — One Focused Contribution

| When | Design Action |
|------|---------------|
| **Week 2-3** | Open 1 accessibility issue (follow pattern of merged #940) |
| **Day 20** (light day) | Submit accessibility fix PR — missing aria-labels, keyboard nav |
| **While testing** | Screenshot any broken mobile views → open issue |

### 📊 Security Issues to Open (1 per week)

| Week | Potential Issue to File |
|------|------------------------|
| Week 1 | `bare except:` clauses that swallow errors silently (spot while doing docstrings) |
| Week 2 | Missing input validation on API endpoints (spot while writing tests) |
| Week 3 | Accessibility gaps in UI pages (follow #940 pattern) |
| Week 4 | Rate limiting gaps on sensitive endpoints (spot during integration tests) |

---

## WEEK 1 PLAN (Mar 1–7): ESTABLISH PRESENCE

> **Goal:** Ship 7 PRs. All Tier 1 (guaranteed merges). Build trust with maintainer.

---

### Day 1 (Sat, Mar 1) — ✅ DONE

**BACKLOG:** B08 — Docstrings for `database/` module

**TASK:** Add Google-style docstrings to all 14 undocumented functions in `database/`.

**FILES TO EDIT:**
- `database/apilog_db.py` — add docstrings to `init_db()` (line 46) and `async_log_order()` (line 56)
- `database/auth_db.py` — add docstrings to `init_db()` and `get_auth_token_dbquery()` and `get_feed_token_dbquery()`
- `database/cache_invalidation.py` — add docstring to `__init__()`
- `database/symbol.py` — add docstrings to `parse_expiry()` and `sort_key()`
- `database/token_db_enhanced.py` — add docstrings to `__init__()`, `sort_key()`, `parse_expiry()`
- `database/tv_search.py` — add docstring to `search_symbols()`
- `database/user_db.py` — add docstrings to `init_db()` (line 100) and `add_user()` (line 106)

**DOCSTRING FORMAT:**
```python
def init_db():
    """Initialize the API log database tables.

    Creates the order_logs table if it doesn't exist using the
    SQLAlchemy Base metadata and the configured database engine.
    """
```

**WHY IT WILL MERGE:** Pure documentation. Zero risk. Improves IDE support for every developer. Maintainer has merged similar PRs (e.g., #954 docs guide).

**OUTPUT:** 1 PR on GitHub

**BRANCH:** `docs/add-docstrings-database`

**COMMIT MESSAGE:** `docs: add Google-style docstrings to database module functions`

**LINES CHANGED:** ~80 (actual: 148)

**BACKUP TASK:** If somehow blocked, do B13 (auth.py docstrings) instead.

**RESULT:** ✅ Completed. 6 files, 148 insertions. Branch pushed. All 7 CI-safe tests pass.
- Discovered: `cache_invalidation.py` `__init__()` was already well-documented.
- Also documented: `init_db()` in `symbol.py` (improved from one-liner to full docstring).
- Pre-existing ruff issues found (deprecated typing imports) — not in scope for this PR.

---

### Day 2 (Sun, Mar 2) ✅ DONE

**BACKLOG:** B01 — Create `test/conftest.py` pytest fixtures

**TASK:** Create reusable test infrastructure that enables all future test PRs.

**FILES TO CREATE:**
- `test/conftest.py`

**WHAT TO IMPLEMENT:**
```python
# test/conftest.py
import pytest
from unittest.mock import MagicMock, patch
import os

# Fixture: Set required env vars for testing
@pytest.fixture(autouse=True)
def mock_env_vars(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("BROKER_API_KEY", "test_api_key")
    monkeypatch.setenv("BROKER_API_SECRET", "test_api_secret")
    monkeypatch.setenv("API_KEY_PEPPER", "a" * 64)
    monkeypatch.setenv("APP_KEY", "test_app_key")
    monkeypatch.setenv("HOST_SERVER", "http://127.0.0.1:5000")
    monkeypatch.setenv("REDIRECT_URL", "http://127.0.0.1:5000/callback")

# Fixture: Valid order data factory
@pytest.fixture
def valid_order_data():
    return {
        "apikey": "test_api_key",
        "strategy": "Test",
        "symbol": "RELIANCE-EQ",
        "exchange": "NSE",
        "action": "BUY",
        "product": "MIS",
        "pricetype": "MARKET",
        "quantity": "10",
        "price": "0",
        "trigger_price": "0",
        "disclosed_quantity": "0",
    }

# Fixture: Mock broker module
@pytest.fixture
def mock_broker_module():
    module = MagicMock()
    module.place_order_api.return_value = (
        MagicMock(status=200),
        {"status": "success", "data": {"order_id": "12345"}},
        "12345",
    )
    module.get_order_book.return_value = {"status": "success", "data": []}
    module.get_positions.return_value = {"status": True, "data": []}
    module.cancel_order.return_value = ({"status": "success", "orderid": "12345"}, 200)
    module.close_all_positions.return_value = (
        {"status": "success", "message": "All positions closed"},
        200,
    )
    return module
```

**WHY IT WILL MERGE:** Test infrastructure is always welcome. Creates shared fixtures that every future test PR uses. Zero runtime impact.

**OUTPUT:** 1 PR on GitHub

**BRANCH:** `test/add-conftest-fixtures`

**COMMIT MESSAGE:** `test: add pytest conftest.py with reusable test fixtures and data factories`

**LINES CHANGED:** ~120

**BACKUP TASK:** If conftest pattern already exists by someone else, do B09 (utils docstrings).

**✅ DAY 2 COMPLETION NOTES (Mar 2):**
- Created `test/conftest.py` with 8 fixtures (196 lines):
  - `mock_env_vars` (autouse), `valid_order_data`, `valid_smart_order_data`,
    `valid_cancel_order_data`, `mock_broker_module`, `malicious_order_data`,
    `empty_auth_data`, `oversized_order_data`
- Created `test/test_conftest_smoke.py` with 10 smoke tests — all pass in 0.04s
- All 17 tests (7 existing + 10 new) pass
- Ruff clean, no secrets, no debug prints
- Commit: `dc1f24ec` on branch `test/add-conftest-fixtures`
- 🔒 Security: Included `malicious_order_data` (SQL injection, XSS),
  `empty_auth_data` (auth bypass), and `oversized_order_data` fixtures

**🔒 SECURITY BONUS:** Add these security-focused fixtures to `conftest.py`:
```python
# Fixture: Security edge-case order data
@pytest.fixture
def malicious_order_data():
    """Order data with SQL injection and XSS payloads for security testing."""
    return {
        "apikey": "test_api_key",
        "strategy": "Test",
        "symbol": "'; DROP TABLE orders;--",
        "exchange": "<script>alert('xss')</script>",
        "action": "BUY",
        "product": "MIS",
        "pricetype": "MARKET",
        "quantity": "10",
    }

@pytest.fixture
def empty_auth_data():
    """Empty/None auth data for testing auth bypass scenarios."""
    return {
        "apikey": "",
        "strategy": "",
        "symbol": "",
    }
```

---

### Day 3 (Mon, Mar 3)

**BACKLOG:** B02 — Unit tests for `services/place_order_service.py`

**TASK:** Write unit tests for the core order validation and placement functions.

**FILES TO CREATE:**
- `test/test_place_order_service.py`

**TEST CASES (10+):**
1. `test_validate_order_data_valid` — valid order returns `(True, data, None)`
2. `test_validate_order_data_missing_symbol` — returns error for missing symbol
3. `test_validate_order_data_missing_action` — returns error for missing action
4. `test_validate_order_data_invalid_exchange` — "INVALID" exchange returns error
5. `test_validate_order_data_invalid_product` — bad product type returns error
6. `test_validate_order_data_invalid_pricetype` — bad price type returns error
7. `test_validate_order_data_invalid_action` — "HOLD" action returns error
8. `test_validate_order_data_zero_quantity` — quantity "0" returns error
9. `test_validate_order_data_negative_quantity` — quantity "-5" returns error
10. `test_import_broker_module_valid` — "zerodha" returns a module
11. `test_import_broker_module_invalid` — "nonexistent" returns None
12. `test_emit_analyzer_error_response_format` — verify dict has "status" and "message" keys

**FUNCTIONS TO TEST:**
- `validate_order_data()` at `services/place_order_service.py:79-128`
- `import_broker_module()` at `services/place_order_service.py:30-46`
- `emit_analyzer_error()` at `services/place_order_service.py:49-76`

**WHY IT WILL MERGE:** Tests core order path. Uses conftest fixtures from Day 2. Maintainer gets free regression coverage.

**OUTPUT:** 1 PR on GitHub

**BRANCH:** `test/place-order-service`

**COMMIT MESSAGE:** `test: add unit tests for place_order_service validation logic`

**LINES CHANGED:** ~200

**BACKUP TASK:** Do B04 (cancel_order tests) instead if place_order has dependency issues.

**🔒 SECURITY BONUS:** Add these test cases to `test_place_order_service.py`:
```python
def test_validate_order_data_sql_injection_symbol():
    """Security: SQL injection in symbol field should return validation error."""
    data = valid_order_data.copy()
    data["symbol"] = "'; DROP TABLE orders;--"
    # Should fail validation, not reach database

def test_validate_order_data_empty_api_key():
    """Security: empty API key must be rejected."""
    data = valid_order_data.copy()
    data["apikey"] = ""

def test_validate_order_data_oversized_quantity():
    """Security: absurdly large quantity should be rejected."""
    data = valid_order_data.copy()
    data["quantity"] = "99999999999"
```

**✅ DAY 3 COMPLETION NOTES (Mar 3):**
- Created `test/test_place_order_service.py` with 21 unit tests
- Mocked all heavy dependencies (`socketio`, `database` modules, `marshmallow`) via sys.modules to allow testing without a live broker DB connection.
- 🔒 Security: Added robust security tests covering SQL injection on symbols, XSS on exchange field, and large quantities.
- Commit pushed to `test/place-order-service` branch.

---

### Day 4 (Tue, Mar 4)

**BACKLOG:** B09 — Docstrings for `utils/` module (30 functions)

**TASK:** Add Google-style docstrings to all 30 undocumented functions in `utils/`.

**FILES TO EDIT:**
- `utils/config.py` — `get_broker_api_key()`, `get_broker_api_secret()`, `get_login_rate_limit_min()`, `get_login_rate_limit_hour()`, `get_host_server()`
- `utils/env_check.py` — `load_and_check_env_variables()`
- `utils/httpx_client.py` — `get()`, `post()`, `put()`, `delete()`
- `utils/latency_monitor.py` — `__init__()`, `decorator()`, `wrapped()`
- `utils/logging.py` — both `filter()` methods
- And ~15 more functions across other utils files

**WHY IT WILL MERGE:** Pure documentation. Improves developer experience for all utils consumers.

**OUTPUT:** 1 PR on GitHub

**BRANCH:** `docs/add-docstrings-utils`

**COMMIT MESSAGE:** `docs: add Google-style docstrings to utils module functions`

**LINES CHANGED:** ~150

**BACKUP TASK:** If utils is too large for one PR, split into two: config+env_check and httpx+logging.

**🔒 SECURITY AUDIT WHILE READING:** While adding docstrings to `utils/`, look for:
- [ ] Any `bare except:` clauses in config loading
- [ ] Hardcoded default secrets or API keys
- [ ] Missing input validation in HTTP client wrappers
- [ ] Secrets passed as URL parameters instead of headers
→ Open 1 issue for the most critical finding

---

### Day 5 (Wed, Mar 5)

**BACKLOG:** B03 — Unit tests for `services/place_smart_order_service.py`

**TASK:** Write unit tests for smart order validation and position-aware logic.

**FILES TO CREATE:**
- `test/test_smart_order_service.py`

**TEST CASES (8+):**
1. `test_validate_smart_order_valid` — valid smart order returns success
2. `test_validate_smart_order_missing_position_size` — returns error
3. `test_validate_smart_order_missing_symbol` — returns error
4. `test_validate_smart_order_invalid_exchange` — returns error
5. `test_validate_smart_order_invalid_action` — returns error
6. `test_validate_smart_order_zero_quantity` — should be valid (exit order)
7. `test_import_broker_module_smart` — dynamic import works
8. `test_emit_analyzer_error_smart` — error response format correct

**FUNCTIONS TO TEST:**
- `validate_smart_order()` at `services/place_smart_order_service.py:79-117`
- `emit_analyzer_error()` at `services/place_smart_order_service.py:30-57`

**WHY IT WILL MERGE:** Tests critical position-aware logic. Smart orders are used by every strategy.

**OUTPUT:** 1 PR on GitHub

**BRANCH:** `test/smart-order-service`

**COMMIT MESSAGE:** `test: add unit tests for place_smart_order_service validation`

**LINES CHANGED:** ~180

**BACKUP TASK:** Do B04 (cancel_order tests) instead.

**🔒 SECURITY BONUS:** Add to smart order tests:
```python
def test_smart_order_negative_position_size():
    """Security: negative position_size should be handled safely."""

def test_smart_order_none_auth_token():
    """Security: None auth token must not crash the service."""
```

---

### Day 6 (Thu, Mar 6)

**BACKLOG:** B10 — Docstrings for Zerodha broker adapter

**TASK:** Add Google-style docstrings to all functions in the Zerodha broker adapter (the reference implementation).

**FILES TO EDIT:**
- `broker/zerodha/api/order_api.py` — 12 functions:
  - `get_order_book()` (line 77), `get_trade_book()` (line 81), `get_positions()` (line 85), `get_holdings()` (line 89)
  - `get_open_position()` (line 93), `place_order_api()` (line 114)
  - `place_smartorder_api()` (line 173), `close_all_positions()` (line 246)
  - `cancel_order()` (line 292 — already has docstring, verify/enhance)
  - `modify_order()` (line 336), `cancel_all_orders_api()` (line 393)
- `broker/zerodha/api/data.py` — all public functions
- `broker/zerodha/api/funds.py` — all public functions
- `broker/zerodha/api/auth_api.py` — `authenticate_broker()`

**WHY IT WILL MERGE:** Zerodha is the reference adapter. Documenting it benefits every future broker contributor. The maintainer merged #954 (broker integration guide) same-day.

**OUTPUT:** 1 PR on GitHub

**BRANCH:** `docs/add-docstrings-zerodha`

**COMMIT MESSAGE:** `docs: add Google-style docstrings to Zerodha broker adapter`

**LINES CHANGED:** ~120

**BACKUP TASK:** Do B11 (Angel docstrings) instead.

**🔒 SECURITY AUDIT WHILE READING:** While documenting Zerodha adapter:
- [ ] Check if auth tokens are logged in plaintext anywhere
- [ ] Check error handlers — do they leak broker credentials in error messages?
- [ ] Note any hardcoded URLs or timeout values that should be configurable
→ If found, open Week 1 security issue

---

### Day 7 (Fri, Mar 7)

**BACKLOG:** B04 — Unit tests for `services/cancel_order_service.py`

**TASK:** Write unit tests for the cancel order service.

**FILES TO CREATE:**
- `test/test_cancel_order_service.py`

**TEST CASES (8+):**
1. `test_cancel_order_with_auth_success` — mock broker returns success
2. `test_cancel_order_with_auth_broker_error` — mock broker returns error
3. `test_cancel_order_with_auth_import_failure` — invalid broker name
4. `test_cancel_order_api_key_auth` — full flow with API key
5. `test_cancel_order_no_auth` — missing both api_key and auth_token
6. `test_cancel_order_invalid_broker` — broker module not found
7. `test_cancel_order_analyzer_mode` — verify analyzer mode handling
8. `test_emit_analyzer_error_cancel` — error response format

**FUNCTIONS TO TEST:**
- `cancel_order_with_auth()` at `services/cancel_order_service.py:67-152`
- `cancel_order()` at `services/cancel_order_service.py:155-227`
- `emit_analyzer_error()` at `services/cancel_order_service.py:18-45`

**WHY IT WILL MERGE:** Tests essential order lifecycle function. Uses conftest fixtures.

**OUTPUT:** 1 PR on GitHub

**BRANCH:** `test/cancel-order-service`

**COMMIT MESSAGE:** `test: add unit tests for cancel_order_service`

**LINES CHANGED:** ~180

**BACKUP TASK:** Do B13 (auth.py docstrings) instead.

**🔒 SECURITY BONUS:** Add to cancel order tests:
```python
def test_cancel_order_with_revoked_token():
    """Security: revoked auth token should return unauthorized."""

def test_cancel_order_wrong_user_orderid():
    """Security: user cannot cancel another user's order."""
```

---

## WEEK 2 PLAN (Mar 8–14): EXPAND COVERAGE + TIER 2 FIXES

> **Goal:** 7 more PRs. Mix Tier 1 tests/docs with Tier 2 pre-approved fixes. Comment on issues before coding.
> **🔒 Security goal:** Open 1 security issue based on findings from Week 1 code reading.
> **🎨 Design goal:** Identify 1 accessibility gap while testing UI — screenshot it.

---

### Day 8 (Sat, Mar 8)

**BACKLOG:** B05 — Unit tests for `services/basket_order_service.py`

**TASK:** Write unit tests for the basket order service.

**FILES TO CREATE:**
- `test/test_basket_order_service.py`

**TEST CASES (8+):**
1. `test_validate_order_valid_basket_item` — single valid item
2. `test_validate_order_missing_symbol` — missing symbol returns error
3. `test_validate_order_invalid_exchange` — invalid exchange returns error
4. `test_validate_order_invalid_action` — invalid action returns error
5. `test_validate_order_zero_quantity` — quantity "0" returns error
6. `test_validate_order_invalid_product` — invalid product type
7. `test_validate_order_negative_quantity` — negative quantity
8. `test_import_broker_module_basket` — dynamic import for basket

**FUNCTIONS TO TEST:**
- `validate_order()` at `services/basket_order_service.py:79-117`
- `import_broker_module()` at `services/basket_order_service.py:60-76`

**COMMIT MESSAGE:** `test: add unit tests for basket_order_service validation`

**LINES CHANGED:** ~200

---

### Day 9 (Sun, Mar 9)

**BACKLOG:** B15 — Fix Docker compose volumes (#910)

**PRE-STEP: Comment on issue #910 FIRST:**
> "I can fix this. I'll update docker-compose.yaml with volume mappings for `./db:/app/db`, `./log:/app/log`, `./strategies:/app/strategies`, `./keys:/app/keys`, and `./.env:/app/.env:ro`. I'll also update the Docker README. Does this approach look correct?"

**TASK (after maintainer ACK):**

**FILES TO EDIT:**
- `docker-compose.yaml` — add volume mappings under `services.openalgo.volumes`
- `DOCKER_README.md` — add section explaining persistent volume configuration

**COMMIT MESSAGE:** `fix: update docker-compose volume mappings for persistent data (#910)`

**LINES CHANGED:** ~50

**BACKUP TASK:** If maintainer doesn't respond, do B11 (Angel docstrings) instead.

---

### Day 10 (Mon, Mar 10)

**BACKLOG:** B16 — Fix `.env` file permissions (#960)

**PRE-STEP: Comment on issue #960 FIRST:**
> "The issue is that `chmod 600 .env` makes the file unreadable by the container's non-root user. I can fix `utils/env_check.py` to catch `PermissionError` and provide a clear diagnostic message like 'File exists but cannot be read — check file ownership matches the container user.'"

**TASK (after maintainer ACK):**

**FILES TO EDIT:**
- `utils/env_check.py` — around line 272, replace bare `except:` with specific exception handling:
  ```python
  except PermissionError:
      print("ERROR: .env file exists but cannot be read.")
      print("If using Docker, ensure the file is owned by the container user.")
      print("Fix: chmod 644 .env  OR  chown <container-user> .env")
      sys.exit(1)
  except FileNotFoundError:
      # existing handling...
  ```

**COMMIT MESSAGE:** `fix: handle .env permission errors with clear diagnostics (#960)`

**LINES CHANGED:** ~40

**BACKUP TASK:** If maintainer doesn't ACK, do B12 (AliceBlue docstrings).

---

### Day 11 (Tue, Mar 11)

**BACKLOG:** B11 — Docstrings for Angel broker adapter

**TASK:** Add Google-style docstrings to all undocumented functions in `broker/angel/api/`.

**FILES TO EDIT:**
- `broker/angel/api/order_api.py` — `get_api_response()`, `get_order_book()`, `get_trade_book()`, `get_positions()`, `get_holdings()`, `get_open_position()`, `place_order_api()`, `place_smartorder_api()`, `close_all_positions()`, `cancel_order()`, `modify_order()`, `cancel_all_orders_api()`
- `broker/angel/api/data.py` — all public functions
- `broker/angel/api/funds.py` — all public functions
- `broker/angel/api/auth_api.py` — `authenticate_broker()`

**COMMIT MESSAGE:** `docs: add Google-style docstrings to Angel broker adapter`

**LINES CHANGED:** ~130

---

### Day 12 (Wed, Mar 12)

**BACKLOG:** B06 — Unit tests for `services/close_position_service.py`

**TASK:** Write unit tests for close position service.

**FILES TO CREATE:**
- `test/test_close_position_service.py`

**TEST CASES (8+):**
1. `test_close_position_with_auth_success` — mock broker closes all positions
2. `test_close_position_with_auth_no_positions` — no open positions
3. `test_close_position_with_auth_broker_error` — broker API failure
4. `test_close_position_with_auth_import_failure` — invalid broker name
5. `test_close_position_api_key_auth` — flow with API key
6. `test_close_position_no_auth` — missing auth
7. `test_close_position_analyzer_mode` — verify analyzer handling
8. `test_emit_analyzer_error_close` — error format check

**FUNCTIONS TO TEST:**
- `close_position_with_auth()` at `services/close_position_service.py:68-171`
- `close_position()` at `services/close_position_service.py:174-244`

**COMMIT MESSAGE:** `test: add unit tests for close_position_service`

**LINES CHANGED:** ~180

---

### Day 13 (Thu, Mar 13)

**BACKLOG:** B07 — Expand CI to run new test files

**TASK:** Add all new test files from Days 3, 5, 7, 8, 12 to the GitHub Actions CI pipeline.

**FILES TO EDIT:**
- `.github/workflows/ci.yml` — line 47, add new test files to the `uv run pytest` command:

```yaml
      - name: Run CI-safe tests
        run: |
          uv run pytest test/test_log_location.py test/test_navigation_update.py \
            test/test_python_editor.py test/test_rate_limits_simple.py \
            test/test_logout_csrf.py \
            test/test_place_order_service.py \
            test/test_smart_order_service.py \
            test/test_cancel_order_service.py \
            test/test_basket_order_service.py \
            test/test_close_position_service.py \
            -v --timeout=60
```

**WHY IT WILL MERGE:** Permanent infrastructure improvement. Every future PR runs your tests. This is the single highest-impact PR measured by long-term benefit.

**COMMIT MESSAGE:** `ci: expand backend test suite with new service unit tests`

**LINES CHANGED:** ~10

---

### Day 14 (Fri, Mar 14)

**BACKLOG:** B13 + PR review — Docstrings for `blueprints/auth.py` + address review feedback

**TASK (morning):** Review all open PRs, respond to comments, push fix commits.

**TASK (afternoon):** Add docstrings to auth blueprint.

**FILES TO EDIT:**
- `blueprints/auth.py` — add docstrings to: `ratelimit_handler()`, `login()`, `broker_login()`, `reset_password()`, `change_password()`, `configure_smtp()`, `test_smtp()`, `debug_smtp()`, `logout()`

**COMMIT MESSAGE:** `docs: add docstrings to auth blueprint route handlers`

**LINES CHANGED:** ~80

---

## WEEK 3 PLAN (Mar 15–21): SIGNATURE CONTRIBUTION

> **Goal:** Build the mock broker + integration test harness. This is the FOSS Hack trophy piece.
> **🔒 Security goal:** Audit for secret logging in broker adapters (Day 15). Add auth security tests to mock broker.
> **🎨 Design goal:** Submit accessibility fix PR on Day 20 (light day).

---

### Day 15 (Sat, Mar 15)

**BACKLOG:** B14 — Replace `print()` with `logger` in broker files

**PRE-STEP: Open a new GitHub issue FIRST:**
> **Title:** `refactor: replace bare print() calls with logger in broker adapter files`
> **Body:** "Several broker adapter files use bare `print()` calls instead of the project's `utils.logging.get_logger()`. This loses timestamps, log levels, and module context, and doesn't integrate with Traffic Monitor. Files affected: `broker/firstock/api/data.py` (15 print calls), `broker/indmoney/mapping/transform_data.py`, `broker/fyers/streaming/fyers_websocket_adapter.py`, `broker/dhan_sandbox/api/order_api.py`. I'd like to replace these with structured logger calls."

**TASK (after maintainer ACK):**

**FILES TO EDIT:**
- `broker/firstock/api/data.py` — replace 15 `print()` calls (lines 502-576) with `logger.info()` / `logger.debug()` / `logger.error()`
- `broker/indmoney/mapping/transform_data.py` — replace `print()` with `logger`
- `broker/dhan_sandbox/api/order_api.py` — replace `print()` with `logger`

**Add to top of each file if missing:**
```python
from utils.logging import get_logger
logger = get_logger(__name__)
```

**COMMIT MESSAGE:** `refactor: replace bare print() with structured logger in broker adapters`

**LINES CHANGED:** ~80

**🔒 SECURITY BONUS — SECRET LOGGING AUDIT:**
While replacing `print()` calls, actively scan for:
- [ ] `print(token)` or `print(auth)` — secrets dumped to stdout
- [ ] `print(response.text)` where response contains credentials
- [ ] Any `print(api_key)` or `print(password)`
→ Replace with `logger.debug("Token retrieved for user: %s", user_id)` (never log the actual token)
→ If found, mention in PR description: "Also removed N instances of accidental credential logging"

---

### Day 16 (Sun, Mar 16)

**BACKLOG:** B17 — Document atexit SIGKILL limitation (#949)

**PRE-STEP: Comment on issue #949:**
> "PR #971 added atexit shutdown drain. However, atexit handlers do NOT run on SIGKILL, OOM kills, or hard power loss. I'd like to document this limitation in code comments and a doc file, so Docker/systemd users know to use SIGTERM for graceful shutdown."

**TASK:**

**FILES TO EDIT:**
- `blueprints/strategy.py` — add docstring above the atexit block (around line 99 area) explaining the limitation
- Create `docs/order_queue_shutdown.md` — document:
  - How graceful shutdown works (atexit drain, PR #971)
  - What triggers it: `SIGTERM`, `Ctrl+C`, normal exit, `sys.exit()`
  - What does NOT trigger it: `SIGKILL` (kill -9), OOM Killer, power loss
  - Docker recommendation: `stop_grace_period: 30s` in compose
  - systemd recommendation: `TimeoutStopSec=30`

**COMMIT MESSAGE:** `docs: document order queue shutdown behavior and SIGKILL limitation (#949)`

**LINES CHANGED:** ~100

---

### Day 17 (Mon, Mar 17)

**BACKLOG:** B18 (Part 1) — Mock broker adapter: structure + auth + data

**TASK:** Create the mock broker adapter that simulates all broker operations without real credentials.

**FILES TO CREATE:**
- `test/mock_broker/__init__.py`
- `test/mock_broker/plugin.json`:
  ```json
  {
    "broker_name": "mock",
    "display_name": "Mock Broker (Testing)",
    "version": "1.0.0",
    "auth_type": "api_key",
    "api_base_url": "http://localhost/mock",
    "supported_features": ["orders", "positions", "holdings", "quotes"]
  }
  ```
- `test/mock_broker/api/__init__.py`
- `test/mock_broker/api/auth_api.py` — returns fake auth token
- `test/mock_broker/api/data.py` — returns static LTP/quote data for common symbols (RELIANCE, NIFTY, SBIN)
- `test/mock_broker/api/funds.py` — returns a mock fund balance (₹10,00,000)
- `test/mock_broker/mapping/__init__.py`
- `test/mock_broker/mapping/order_data.py` — identity mapping for order data
- `test/mock_broker/mapping/transform_data.py` — identity transforms

**COMMIT MESSAGE:** `test: add mock broker adapter for credential-free testing (part 1)`

**LINES CHANGED:** ~250

---

### Day 18 (Tue, Mar 18)

**BACKLOG:** B18 (Part 2) — Mock broker adapter: order API + position tracking

**FILES TO CREATE / EDIT:**
- `test/mock_broker/api/order_api.py`:
  - `get_order_book(auth)` — returns in-memory order list
  - `get_trade_book(auth)` — returns in-memory trade list
  - `get_positions(auth)` — returns in-memory positions
  - `get_holdings(auth)` — returns static mock holdings
  - `get_open_position(symbol, exchange, product, auth)` — looks up in-memory positions
  - `place_order_api(data, auth)` — generates fake order ID, adds to in-memory book
  - `place_smartorder_api(data, auth)` — implements position-aware logic using in-memory state
  - `close_all_positions(api_key, auth)` — clears all in-memory positions
  - `cancel_order(orderid, auth)` — removes from in-memory order book
  - `modify_order(data, auth)` — updates in-memory order
  - `cancel_all_orders_api(data, auth)` — cancels all open in-memory orders

**COMMIT MESSAGE:** `test: add mock broker order API with in-memory state tracking (part 2)`

**LINES CHANGED:** ~300

---

### Day 19 (Wed, Mar 19)

**BACKLOG:** B19 — End-to-end integration tests using mock broker

**FILES TO CREATE:**
- `test/test_integration_order_flow.py`

**INTEGRATION TEST CASES (10):**
1. `test_place_market_order_flow` — place order → appears in order book
2. `test_place_limit_order_flow` — limit order with price > 0
3. `test_cancel_order_flow` — place then cancel → order removed from book
4. `test_modify_order_flow` — place then modify price → updated in book
5. `test_close_position_flow` — place order → position created → close position
6. `test_smart_order_enter_long` — smart order BUY when flat → position opens
7. `test_smart_order_exit_long` — smart order with position_size=0 → position closes
8. `test_basket_order_flow` — multi-leg basket → all legs in order book
9. `test_order_book_after_multiple_orders` — verify order book state after 5 orders
10. `test_cancel_all_orders_flow` — place 3 orders → cancel all → all removed

**COMMIT MESSAGE:** `test: add end-to-end integration tests using mock broker adapter`

**LINES CHANGED:** ~350

**🔒 SECURITY BONUS:** Add these security integration tests:
```python
def test_place_order_with_empty_auth():
    """Security: order placement with empty auth should fail gracefully."""

def test_place_order_with_revoked_token():
    """Security: revoked token should not allow order placement."""

def test_cancel_order_nonexistent_id():
    """Security: cancelling non-existent order should return error, not crash."""

def test_modify_order_wrong_user():
    """Security: modifying another user's order should be rejected."""
```

---

### Day 20 (Thu, Mar 20)

**BACKLOG:** B12 — Docstrings for AliceBlue broker adapter (cool-down day)

**TASK:** Add Google-style docstrings to AliceBlue adapter. Lower effort to allow PR review recovery.

**FILES TO EDIT:**
- `broker/aliceblue/api/order_api.py` — all public functions (~12)
- `broker/aliceblue/api/data.py` — all public functions
- `broker/aliceblue/api/auth_api.py` — `authenticate_broker()`

**COMMIT MESSAGE:** `docs: add Google-style docstrings to AliceBlue broker adapter`

**LINES CHANGED:** ~120

**🎨 DESIGN BONUS — ACCESSIBILITY PR:** Since Day 20 is a light day, also:
1. Audit 3-5 pages for missing `aria-label` attributes on icon-only buttons
2. Check keyboard navigation (Tab order) on the main dashboard
3. Open issue: `a11y: add missing aria-labels to [page]`
4. Submit small PR: `fix(a11y): add aria-labels to [page] icon buttons`
5. Reference merged #940 as prior art in the PR description

**BRANCH:** `fix/accessibility-improvements`
**LINES CHANGED:** ~30-50 (HTML only)

---

### Day 21 (Fri, Mar 21)

**BACKLOG:** B21 — Sandbox execution engine unit tests

**FILES TO CREATE:**
- `test/test_sandbox_execution.py`

**TEST CASES (8):**
1. `test_market_order_execution` — market order fills immediately
2. `test_limit_order_execution` — limit order at price matches LTP
3. `test_order_creates_position` — executed order creates position
4. `test_margin_blocked_on_order` — fund manager blocks margin
5. `test_margin_released_on_close` — margin released when position closed
6. `test_pnl_calculation` — P&L computed correctly for closed position
7. `test_rejected_order_insufficient_margin` — order rejected when no funds
8. `test_order_book_populated` — orders appear in sandbox order book

**COMMIT MESSAGE:** `test: add unit tests for sandbox execution engine`

**LINES CHANGED:** ~200

---

## WEEK 4 PLAN (Mar 22–28): POLISH & VIDEO

> **Goal:** Close all loops. No new large PRs. Submit everything by Mar 25. Video by Mar 28.

---

### Day 22 (Sat, Mar 22)

**BACKLOG:** B20 — Add integration tests to CI pipeline

**FILES TO EDIT:**
- `.github/workflows/ci.yml` — add integration test job:

```yaml
  # Integration tests (uses mock broker - no credentials needed)
  integration-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: astral-sh/setup-uv@v7
        with:
          enable-cache: true
          python-version: "3.12"
      - run: uv sync
      - name: Run integration tests
        run: |
          uv run pytest test/test_integration_order_flow.py -v --timeout=120
```

**COMMIT MESSAGE:** `ci: add integration test job using mock broker to CI pipeline`

**LINES CHANGED:** ~15

---

### Day 23 (Sun, Mar 23)

**BACKLOG:** B22 — Type hints for service modules

**TASK:** Add type hints to function signatures that are missing them.

**FILES TO EDIT:**
- `services/basket_order_service.py` — `place_single_order()` inner helper
- `services/cancel_order_service.py` — verify all signatures have types
- `services/close_position_service.py` — verify all signatures have types
- `services/modify_order_service.py` — add types to any missing signatures

**COMMIT MESSAGE:** `style: add missing type hints to order service modules`

**LINES CHANGED:** ~60

---

### Day 24 (Mon, Mar 24)

**BACKLOG:** B23 — Testing guide documentation

**FILES TO CREATE:**
- `docs/testing_guide.md`

**CONTENT:**
- How to set up the test environment (`uv sync && uv run pytest`)
- Running tests with markers (`@pytest.mark.unit`, `@pytest.mark.integration`)
- Using `conftest.py` fixtures (from Day 2)
- How the mock broker works (from Days 17-18)
- Adding new integration tests
- CI pipeline explanation
- Link to this from `CONTRIBUTING.md` testing section

**COMMIT MESSAGE:** `docs: add comprehensive testing guide with mock broker documentation`

**LINES CHANGED:** ~200

---

### Day 25 (Tue, Mar 25) ⚠️ LAST DAY FOR NEW PRs

**TASK:** Final PR submission + review all open PRs.

**Morning:** Submit any remaining PRs (B23 testing guide if not done yesterday).

**Afternoon:** Go through EVERY open PR:
- Respond to all maintainer comments
- Push fix commits for requested changes
- Be professional and graceful in all responses
- Sync fork: `git fetch upstream && git merge upstream/main`

**Evening:** Verify all tests pass locally: `uv run pytest test/ -v --timeout=60`

> ⚠️ **NO NEW PRs AFTER TODAY.**

---

### Day 26 (Wed, Mar 26)

**TASK:** Address review feedback + prepare video script.

**Morning:** Push any remaining fix commits on open PRs.

**Afternoon:** Write video demo script:

**Video Script (3-5 minutes):**
```
0:00 - Intro: "Hi, I'm LuckyAnsari22, contributing to OpenAlgo for FOSS Hack 2026"
0:30 - Show GitHub profile: Green contribution graph for all of March
1:00 - Show PR list: Scroll through all PRs, highlight test + docs + fixture variety
1:30 - Terminal demo: Run `uv run pytest test/ -v`
       Show all tests passing (unit + integration with mock broker)
2:30 - Show CI pipeline: GitHub Actions running expanded test suite on a real PR
3:00 - Show mock broker code: Walk through test/mock_broker/ structure
3:30 - Impact summary: "Added X tests, Y docstrings, Z issues fixed, built
       an integration test harness that enables every future contributor
       to test without broker credentials"
4:00 - Thank OpenAlgo maintainers and FOSS Hack community
```

---

### Day 27 (Thu, Mar 27)

**TASK:** Final code cleanup + address any last reviews.

- Run `uv run ruff check . --fix` on all branches
- Run `uv run ruff format --check .` to verify
- Resolve any merge conflicts with upstream
- Push final commits

---

### Day 28 (Fri, Mar 28) 🎬 VIDEO RECORDING DAY

**TASK:** Record and submit FOSS Hack video demo.

**TOOL:** OBS Studio or built-in screen recorder.

**Record the video following Day 26's script.**

**Export as MP4, ensure it's under 5 minutes.**

**Upload to YouTube (or wherever FOSS Hack requires).**

> ⚠️ **DO NOT POSTPONE THIS. RECORD TODAY.**

---

### Day 29 (Sat, Mar 29) — Buffer

**TASK:** Submit FOSS Hack evaluation form.
- Link all PR URLs
- Attach video demo
- Write project summary
- List all contributions with commit counts

---

### Day 30 (Sun, Mar 30) — Buffer

**TASK:** Respond to any last-minute review feedback.
- Check all PRs once more
- Thank maintainers on GitHub and/or Discord

---

### Day 31 (Mon, Mar 31) — Wrap-Up

**TASK:** Final check-in.
- Verify final PR merge status
- Update this DAILY_PLAN.md with final counts
- Post thank-you message on OpenAlgo community channels

---

## DAILY COMMIT DISCIPLINE

If no major PR work exists for a day, do at **minimum one** of these:

- [ ] Update an existing PR based on review feedback
- [ ] Add a docstring to 3 functions in any broker adapter
- [ ] Add 1 test case to an existing test file
- [ ] Improve one error message string (make it more descriptive)
- [ ] Fix one bare `except:` → `except Exception as e:` in any file

This ensures **at least 1 commit per day** = 31 green squares on GitHub.

---

## MAINTAINER COMMUNICATION LOG

| Date | Type | Where | What | Response |
|------|------|-------|------|----------|
| 2026-02-22 | Issue | #949 | Filed architecture issue about in-memory queue | PR #971 merged fixing this |
| 2026-03-01 | Issue | #980 | Filed docs issue for database module docstrings | Opened, will PR shortly |
| 2026-03-01 | PR | #981 | docs: add docstrings to database module (Closes #980) | Open, review feedback addressed |
| 2026-03-02 | Issue | #992 | Filed test infra issue for conftest.py fixtures | Opened, PR submitted |
| 2026-03-02 | PR | #993 | test: add conftest.py fixtures (Closes #992) | Open, awaiting review |

_Update this table every time you interact with maintainers._

---

## PR TRACKER

| PR # | Title | Backlog | Status | Opened | Merged/Closed | Notes |
|------|-------|---------|--------|--------|---------------|-------|
| #981 | `docs: add docstrings to database module` | B08 | 🟡 OPEN | Mar 1 | — | Day 1, Closes #980 |
| #993 | `test: add conftest.py fixtures` | B01 | 🟡 OPEN | Mar 2 | — | Day 2, Closes #992 |
| — | `test: place_order_service tests` | B02 | 🔲 TODO | Mar 3 | — | Day 3 |
| — | `docs: add docstrings to utils module` | B09 | 🔲 TODO | Mar 4 | — | Day 4 |
| — | `test: smart_order_service tests` | B03 | 🔲 TODO | Mar 5 | — | Day 5 |
| — | `docs: Zerodha adapter docstrings` | B10 | 🔲 TODO | Mar 6 | — | Day 6 |
| — | `test: cancel_order_service tests` | B04 | 🔲 TODO | Mar 7 | — | Day 7 |
| — | `test: basket_order_service tests` | B05 | 🔲 TODO | Mar 8 | — | Day 8 |
| — | `fix: docker-compose volumes (#910)` | B15 | 🔲 TODO | Mar 9 | — | Day 9, pre-approve |
| — | `fix: .env permissions (#960)` | B16 | 🔲 TODO | Mar 10 | — | Day 10, pre-approve |
| — | `docs: Angel adapter docstrings` | B11 | 🔲 TODO | Mar 11 | — | Day 11 |
| — | `test: close_position_service tests` | B06 | 🔲 TODO | Mar 12 | — | Day 12 |
| — | `ci: expand backend test suite` | B07 | 🔲 TODO | Mar 13 | — | Day 13 |
| — | `docs: auth.py docstrings` | B13 | 🔲 TODO | Mar 14 | — | Day 14 |
| — | `refactor: print() → logger` | B14 | 🔲 TODO | Mar 15 | — | Day 15, pre-approve |
| — | `docs: atexit limitation (#949)` | B17 | 🔲 TODO | Mar 16 | — | Day 16, pre-approve |
| — | `test: mock broker (part 1)` | B18 | 🔲 TODO | Mar 17 | — | Day 17 |
| — | `test: mock broker (part 2)` | B18 | 🔲 TODO | Mar 18 | — | Day 18 |
| — | `test: integration tests` | B19 | 🔲 TODO | Mar 19 | — | Day 19 |
| — | `docs: AliceBlue docstrings` | B12 | 🔲 TODO | Mar 20 | — | Day 20 |
| — | `test: sandbox engine tests` | B21 | 🔲 TODO | Mar 21 | — | Day 21 |
| — | `ci: integration tests in CI` | B20 | 🔲 TODO | Mar 22 | — | Day 22 |
| — | `style: type hints` | B22 | 🔲 TODO | Mar 23 | — | Day 23 |
| — | `docs: testing guide` | B23 | 🔲 TODO | Mar 24 | — | Day 24 |

**Totals: ~24 PRs planned**
- 📝 Documentation PRs: 8
- 🧪 Test PRs: 10
- 🔧 Bug Fix PRs: 2
- ⚙️ CI PRs: 2
- 🔄 Refactor PRs: 1
- 💅 Style PRs: 1

---

## RULES FOR SUCCESS

1. **Never push to main** — always feature branches
2. **Never include `frontend/dist/`** — CI auto-builds it
3. **Always run ruff** before committing: `uv run ruff check . --fix`
4. **Always use conventional commits** — `feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `style:`, `ci:`
5. **Keep PRs under 300 lines** — never exceed 500
6. **Reference issues** in PR body — `Closes #XXX` or `Related to #XXX`
7. **Respond to reviews within 12 hours** — weekends included
8. **Test locally** before pushing — `uv run pytest test/ -v`
9. **Comment on issues before coding** for Tier 2+ items
10. **Record video by Mar 28** — NOT Mar 31
11. **All PRs submitted by Mar 25** — NO exceptions
12. **Never argue with maintainers** — accept feedback gracefully
13. **Sync fork daily** — `git fetch upstream && git merge upstream/main`
14. **Minimum 1 commit per day** — keep the streak alive
15. **Don't reopen the SQLite queue PR** — it was declined. Move on.

---

> **"You've already filed #949. The maintainer knows your name. Now show them you can ship." 🚀**
