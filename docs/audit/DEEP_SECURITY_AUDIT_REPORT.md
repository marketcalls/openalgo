# OpenAlgo Deep Codebase Security Audit Report

## Metadata
- **Project:** OpenAlgo
- **PR Context:** https://github.com/marketcalls/openalgo/pull/947 (Crypto Exchange Integration)
- **Audit date:** 2026-03-03
- **Auditor:** Claude Opus 4.6
- **Scope:** Full codebase audit of `openalgo/services/`, `openalgo/blueprints/`, `openalgo/restx_api/`, `openalgo/database/`, `openalgo/sandbox/`, `openalgo/broker/`, `openalgo/upgrade/`
- **Focus:** SQL injection, input validation, security vulnerabilities, crypto integration impact on existing Indian broker functionality

---

## Executive Summary

A full codebase audit beyond the PR #947 diff was conducted across all backend Python files. The codebase demonstrates strong security fundamentals (Argon2 hashing with pepper, CSRF protection, CSP middleware, HttpOnly/SameSite cookies, constant-time webhook secret comparison). However, **1 High-severity SQL injection**, **2 High-severity input validation gaps**, and **7 Medium-severity issues** were identified in the existing codebase. Existing Indian broker functionality is at **very low risk** from crypto integration -- hardcoded exchange whitelists are additive.

**Finding counts:** Critical: 0 | High: 3 | Medium: 7 | Low: 13

---

## HIGH SEVERITY FINDINGS

### H1: SQL Injection via `compression` parameter in Historify export

- **File:** `database/historify_db.py:2386-2396`
- **Category:** SQL Injection
- **Exploitable by:** Authenticated user

**Vulnerable code:**
```python
conn.execute(f"""
    COPY (
        SELECT ...
        FROM market_data
        ORDER BY symbol, exchange, interval, timestamp
    ) TO '{abs_output}'
    (FORMAT PARQUET, COMPRESSION '{compression}')
""")
```

**Source of input:** `blueprints/historify.py:440`:
```python
compression = data.get("compression", "zstd")  # For Parquet
```

**Analysis:** The `compression` value comes directly from user-supplied JSON (`request.get_json()`) with no validation or sanitization. An authenticated user could craft a malicious value like `zstd'); DROP TABLE market_data; --` which gets interpolated directly into the DuckDB SQL statement.

**Mitigating factors:**
- Requires session authentication (`@check_session_validity`)
- Only executes when `params` is empty (no symbol/interval/date filters)
- DuckDB may reject invalid COMPRESSION values before executing the rest

**Recommended fix:**
```python
VALID_COMPRESSIONS = ["zstd", "snappy", "gzip", "none"]
if compression not in VALID_COMPRESSIONS:
    compression = "zstd"
```

---

### H2: `exchange` field unvalidated in 16+ API schemas

- **Files:** `restx_api/schemas.py`, `restx_api/data_schemas.py`
- **Category:** Input Validation / Exchange Injection
- **Exploitable by:** API key holder

**Vulnerable schemas (no `validate.OneOf()`):**

| Schema | File | Line |
|--------|------|------|
| `OrderSchema` | `schemas.py` | 7 |
| `SmartOrderSchema` | `schemas.py` | 36 |
| `ModifyOrderSchema` | `schemas.py` | 64 |
| `BasketOrderItemSchema` | `schemas.py` | 105 |
| `SplitOrderSchema` | `schemas.py` | 139 |
| `OptionsOrderSchema` | `schemas.py` | 173 |
| `OptionsMultiOrderSchema` | `schemas.py` | 256 |
| `SyntheticFutureSchema` | `schemas.py` | 275 |
| `QuotesSchema` | `data_schemas.py` | 41 |
| `SymbolExchangePair` | `data_schemas.py` | 46 |
| `HistorySchema` | `data_schemas.py` | 59 |
| `DepthSchema` | `data_schemas.py` | 104 |
| `SymbolSchema` | `data_schemas.py` | 114 |
| `OptionSymbolSchema` | `data_schemas.py` | 159 |
| `OptionChainSchema` | `data_schemas.py` | 213 |
| `SearchSchema` | `data_schemas.py` | 139 |

**Only 4 schemas properly validate exchange:** `MarginPositionSchema`, `ExpirySchema`, `OptionGreeksSchema`, `InstrumentsSchema`.

The secondary validation in `place_order_service.py` `validate_order_data()` only covers `/placeorder` -- all other endpoints (smart order, basket, split, options, modify, quotes, depth, history, search, symbol) pass unvalidated exchange values to downstream services.

**Recommended fix:** Add `validate=validate.OneOf(VALID_EXCHANGES)` to all exchange fields, importing from `utils/constants.py`.

---

### H3: `place_order.py` bypasses Marshmallow schema validation

- **File:** `restx_api/place_order.py:22-34`
- **Category:** Input Validation Bypass
- **Exploitable by:** API key holder

**Vulnerable code:**
```python
def post(self):
    data = request.json
    api_key = data.get("apikey", None)
    success, response_data, status_code = place_order(order_data=data, api_key=api_key)
```

Unlike every other order endpoint (`place_smart_order`, `modify_order`, `cancel_order`, `basket_order`, `split_order`, `options_order`), this endpoint passes raw `request.json` directly to the service without schema validation at the API layer. If `request.json` is `None` (malformed body), `data.get()` raises `AttributeError`.

**Recommended fix:** Add `OrderSchema().load(request.json)` validation at the endpoint level, consistent with all other endpoints.

---

## MEDIUM SEVERITY FINDINGS

### M1: LIKE wildcard injection in 25+ search functions

- **Files:** `database/symbol.py:81-92`, 24+ broker `master_contract_db.py` files
- **Category:** Data Disclosure / Performance DoS

**Vulnerable code (representative):**
```python
SymToken.symbol.ilike(f"%{term}%")
SymToken.brsymbol.ilike(f"%{term}%")
SymToken.name.ilike(f"%{term}%")
```

User search terms from `request.args.get("q")` are directly interpolated into LIKE patterns without escaping `%` and `_` wildcards. Searching for `%` returns all records.

**Note:** This is NOT traditional SQL injection -- SQLAlchemy properly parameterizes values. The risk is unintended broad matching and performance degradation.

**Affected broker files:**
zerodha, angel, dhan, upstox, kotak, fyers, samco, groww, motilal, aliceblue, mstock, indmoney, wisdom, iifl, ibulls, pocketful, fivepaisaxts, fivepaisa, paytm, dhan_sandbox, rmoney, compositedge, jainamxts, nubra, definedge

**Recommended fix:**
```python
def escape_like(s):
    return s.replace('%', r'\%').replace('_', r'\_')
```

---

### M2: Full Python tracebacks returned to API clients

- **Files:** `blueprints/log.py:303-305`, `blueprints/analyzer.py:131`
- **Category:** Information Disclosure

**Vulnerable code:**
```python
error_msg = f"Error exporting logs: {str(e)}\n{traceback.format_exc()}"
return jsonify({"error": error_msg}), 500
```

Exposes internal file paths, line numbers, variable names, and potentially database schema details. Additionally, 30+ endpoints across blueprints return `str(e)` which can leak internal information.

**Recommended fix:** Return generic error messages; log full tracebacks server-side only.

---

### M3: Python strategy execution -- no Windows resource limits

- **File:** `blueprints/python_strategy.py:462, 333`
- **Category:** Resource Exhaustion / Arbitrary Code Execution

User-uploaded `.py` files are executed via `subprocess.Popen`. Resource limits via the `resource` module only work on Linux/macOS. On Windows (`if IS_WINDOWS: return` at line 333), strategies can consume unlimited CPU, memory, and file descriptors. No Python-level sandboxing restricts imports, filesystem access, or network calls.

**Mitigating factors:** Requires session authentication + ownership checks.

**Recommended fix:** Implement Windows Job Objects for resource limits; consider Docker containerization for strategy execution.

---

### M4: Telegram endpoints lack schema validation

- **File:** `restx_api/telegram_bot.py`
- **Category:** Input Validation

Multiple endpoints read user JSON without Marshmallow schemas:
- `/config` POST (line 141): `rate_limit_per_minute` -- no type/range validation
- `/broadcast` POST (line 380): `message` -- no length limit
- `/notify` POST (line 431): `priority` -- no type/range validation
- `/stats` GET (line 530): `days = int(request.args.get("days", 7))` -- no max value cap

**Recommended fix:** Create proper Marshmallow schemas for all Telegram endpoints.

---

### M5: `apikey` field has no length constraints across all schemas

- **Files:** `restx_api/schemas.py`, `restx_api/account_schema.py`, `restx_api/data_schemas.py`
- **Category:** Resource Exhaustion

Every schema defines `apikey = fields.Str(required=True)` with no max length. Only `MarginCalculatorSchema` has `validate.Length(min=1)`. An attacker could send megabytes of data as the API key, causing performance issues in Argon2 hashing and SHA256 cache key computation.

**Recommended fix:** Add `validate=validate.Length(min=1, max=256)` to all `apikey` fields.

---

### M6: `ChartSchema` accepts arbitrary JSON data

- **File:** `restx_api/account_schema.py:51-56`
- **Category:** Storage Exhaustion

```python
class ChartSchema(Schema):
    apikey = fields.Str(required=True)
    class Meta:
        unknown = INCLUDE  # Allow any key-value pairs
```

All arbitrary keys are stored directly to the database. Allows storage exhaustion via large JSON payloads.

**Recommended fix:** Validate preference keys against an allowlist of known chart preference keys.

---

### M7: Non-distributed rate limiting

- **File:** `app.py:129`
- **Category:** Rate Limiting Bypass

Flask-Limiter uses in-memory storage. In multi-worker deployments, each worker maintains its own counters, multiplying the effective rate limit by worker count.

**Mitigating factor:** CLAUDE.md recommends `-w 1` for WebSocket compatibility, which mitigates this in practice.

**Recommended fix:** For multi-worker deployments, configure Flask-Limiter with Redis backend.

---

## LOW SEVERITY FINDINGS

| ID | Finding | File(s) | Description |
|----|---------|---------|-------------|
| L1 | Telegram webhook timing attack | `restx_api/telegram_bot.py:309` | Uses `!=` instead of `hmac.compare_digest()` for secret comparison |
| L2 | API key in URL query string | `restx_api/ticker.py:139,157` | API keys in GET params logged in access logs, browser history |
| L3 | `market_holidays`/`market_timings` skip API key verification | `restx_api/market_holidays.py:30-36` | Schema requires `apikey` but handler never verifies it |
| L4 | `SmartOrderSchema` allows quantity=0 | `restx_api/schemas.py:39` | `position_size` field has no range validation (negative values accepted) |
| L5 | Content-Disposition header injection | `blueprints/python_strategy.py:2380` | Filename not quoted in header |
| L6 | Legacy strategy ownership bypass | `blueprints/python_strategy.py:151-182` | Missing `user_id` field skips ownership check |
| L7 | No `request.json` null check on most endpoints | Multiple POST endpoints | Causes 500 instead of proper 400 |
| L8 | `symbol`, `strategy`, `orderid` unbounded strings | `restx_api/schemas.py` | No `validate.Length()` -- storage exhaustion risk |
| L9 | `MultiQuotesSchema` no max list length | `restx_api/data_schemas.py:49` | Could overload broker API with thousands of symbols |
| L10 | `expiry_date`, `expiry_time` lack format validation | `schemas.py`, `data_schemas.py` | Comments document expected format but no regex validation |
| L11 | `underlying_exchange` unvalidated | `data_schemas.py:189,242` | Optional field accepts any string |
| L12 | Hardcoded temp path for admin upload | `blueprints/admin.py:277` | Uses `/tmp/qtyfreeze_upload.csv` -- race condition risk |
| L13 | Error messages leak `str(e)` | 30+ endpoints | Database schema details may leak via exception messages |

---

## SQL INJECTION DETAILED ASSESSMENT

### Findings

| # | Finding | Severity | User Input? | Exploitable? |
|---|---------|----------|-------------|--------------|
| 1 | `compression` param in DuckDB COPY SQL | **HIGH** | Yes (JSON body) | Yes, by authenticated user |
| 2 | LIKE wildcard injection in 25+ search functions | **MEDIUM** | Yes (query params) | Wildcard injection only |
| 3 | Host LIKE wildcard in security blueprint (`blueprints/security.py:200`) | **MEDIUM** | Yes (JSON body) | Wildcard injection only (admin-only) |
| 4 | Traffic LIKE with hardcoded values (`blueprints/traffic.py:173`) | LOW | No | No |
| 5 | Migration scripts with f-string DDL (`upgrade/*.py`) | LOW | No | No (hardcoded values, manual runs) |
| 6 | Dynamic UPDATE column construction (`database/historify_db.py:3185,3337`) | LOW | No | No (hardcoded column names) |
| 7 | Dynamic WHERE clause construction (`database/historify_db.py:2346,2468`) | LOW | No | No (hardcoded conditions, parameterized values) |
| 8 | Integer f-strings in aggregation SQL (`database/historify_db.py:976-1005`) | LOW | No | No (computed constants) |

### Positive SQL Security Findings

- **No `eval()` or `exec()` calls** found anywhere in the codebase
- **REST API layer** (`restx_api/`) contains zero direct database operations -- all queries go through service/database layers
- **SQLAlchemy ORM** is used consistently for the main SQLite database with proper column comparisons
- **Raw SQL with `text()`** in the main database always uses named parameter binding (`:user_id`, `:name`)
- **DuckDB queries** in `historify_db.py` consistently use `?` parameterized queries for user-supplied values

---

## CRYPTO INTEGRATION IMPACT ON INDIAN BROKERS

### Overall Risk: LOW

Adding crypto exchanges is **additive** -- hardcoded exchange whitelists mean existing Indian broker logic is untouched. No direct regression was identified.

### Detailed Impact Matrix

| Area | File(s) | Risk to Indian Brokers | Risk to Crypto Users |
|------|---------|----------------------|---------------------|
| Central `VALID_EXCHANGES` | `utils/constants.py:18-29` | None (additive) | Must be updated |
| Order placement flow | `services/place_order_service.py` | None | Works if exchange added |
| Broker adapters (24+) | `broker/*/` | None | Unknown exchanges rejected |
| Symbol detection (`is_option`, `is_future`) | `sandbox/order_manager.py:34-45` | None | Crypto symbols undetected |
| Product-exchange compatibility | `sandbox/order_manager.py:1039-1053` | None | Falls through all checks |
| WebSocket streaming mappers | `broker/*/streaming/` | None | Crypto exchanges ignored |
| NSE default exchange | `flow_executor_service.py` (20+ places) | None | Confusing errors |
| UI exchange dropdowns | `frontend/src/lib/flow/constants.ts:8-18` | None | Crypto not selectable |

### 6 Independently Duplicated Exchange Lists (Maintenance Risk)

These lists are NOT centralized via `VALID_EXCHANGES` import. Missing any one causes crypto to work in some endpoints but fail in others:

| Location | File | Line | Exchanges Listed |
|----------|------|------|-----------------|
| Central constant | `utils/constants.py` | 18-29 | NSE, NFO, CDS, BSE, BFO, BCD, MCX, NCDEX, NSE_INDEX, BSE_INDEX |
| Margin schema | `restx_api/schemas.py` | 289 | NSE, BSE, NFO, BFO, CDS, MCX |
| Instruments schema | `restx_api/data_schemas.py` | 202 | NSE, BSE, NFO, BFO, BCD, CDS, MCX, NSE_INDEX, BSE_INDEX |
| Strategy blueprint | `blueprints/strategy.py` | 70 | NSE, BSE, NFO, CDS, BFO, BCD, MCX, NCDEX |
| Market calendar | `database/market_calendar_db.py` | 50 | NSE, BSE, NFO, BFO, MCX, BCD, CDS |
| Sandbox order mgr | `sandbox/order_manager.py` | 1086 | NSE, BSE, NFO, BFO, CDS, BCD, MCX, NCDEX |

### P0 Crypto-Specific Issues (must fix before crypto goes live)

1. **MIS positions never auto-squared-off for crypto** -- `sandbox/squareoff_manager.py:37-46` only has Indian exchanges in the timing dict; unknown exchanges are silently skipped with `continue`
2. **No `is_crypto()` function exists** -- zero matches in entire codebase; no instrument type detection for crypto
3. **Market calendar assumes IST and Indian holidays** -- crypto is 24/7, doesn't fit the model (`database/market_calendar_db.py:56-64`)
4. **Streaming mappers default to NSE** for unknown exchanges -- crypto would silently map to NSE's exchange type code in 7+ broker mappers

---

## POSITIVE SECURITY FINDINGS

| Area | Implementation | Assessment |
|------|---------------|------------|
| Password/API key hashing | Argon2 with 32+ char pepper, enforced at startup | Strong |
| API key verification caching | SHA256 cache keys (never plaintext), invalid key cache (5 min), revocation check | Strong |
| CSRF protection | Flask-WTF with appropriate exemptions (API uses key auth, webhooks use secrets) | Strong |
| Session cookies | HttpOnly, SameSite=Lax, Secure on HTTPS, `__Secure-` prefix, daily IST expiry | Strong |
| Content Security Policy | CSP middleware applied via `apply_csp_middleware(app)` | Strong |
| Webhook secret comparison | `hmac.compare_digest()` for flow webhook secrets | Strong |
| Safe math evaluation | `flow_executor_service.py` uses `ast.parse()` with operator allowlist, no `eval()`/`exec()` | Strong |
| Secrets management | All critical secrets from environment variables, not hardcoded | Strong |
| Path traversal protection | Flask `send_from_directory()` for static assets, `os.path.abspath()` validation for exports | Strong |
| No insecure deserialization | No `pickle.loads()`, `yaml.load()` without SafeLoader, or custom JSON decoders | Strong |
| CORS | Disabled by default, configurable via env vars when needed | Strong |
| No `eval()`/`exec()` | Zero occurrences found in entire codebase | Strong |

---

## REMEDIATION PRIORITY TABLE

| Priority | ID | Finding | Severity | Estimated Effort |
|----------|----|---------|----------|-----------------|
| P0 | H1 | Validate `compression` param in historify export | HIGH | 5 minutes |
| P0 | H2 | Add `validate.OneOf(VALID_EXCHANGES)` to all 16 exchange fields | HIGH | 30 minutes |
| P0 | H3 | Add Marshmallow validation to `place_order.py` | HIGH | 10 minutes |
| P1 | M2 | Remove tracebacks from API error responses (2 files + 30 `str(e)` occurrences) | MEDIUM | 1 hour |
| P1 | M1 | Escape LIKE wildcards in search functions (25+ files) | MEDIUM | 1 hour |
| P1 | M4 | Add Marshmallow schemas for Telegram endpoints | MEDIUM | 30 minutes |
| P1 | M5 | Add `validate.Length(min=1, max=256)` to all `apikey` fields | MEDIUM | 30 minutes |
| P2 | M3 | Windows resource limits for strategy execution | MEDIUM | 2-4 hours |
| P2 | M6 | Restrict `ChartSchema` to known preference keys | MEDIUM | 15 minutes |
| P2 | M7 | Configure Redis backend for Flask-Limiter in multi-worker mode | MEDIUM | 30 minutes |
| P3 | L1-L13 | Low-severity fixes | LOW | Variable |

---

## CONSOLIDATED VALIDATION TABLE

| Validation Item | Scope/Area | Status | Severity | Evidence | Required Action |
|---|---|---|---|---|---|
| SQL injection in historify export | `database/historify_db.py:2386` | **FAIL** | **HIGH** | `compression` param interpolated into DuckDB SQL without validation | Validate against allowlist |
| Exchange field validation in API schemas | `restx_api/schemas.py`, `data_schemas.py` | **FAIL** | **HIGH** | 16 schemas accept arbitrary exchange strings | Add `validate.OneOf(VALID_EXCHANGES)` |
| Place order schema validation | `restx_api/place_order.py` | **FAIL** | **HIGH** | Bypasses Marshmallow; raw `request.json` passed to service | Add schema validation at endpoint |
| LIKE wildcard injection in search | `database/symbol.py`, 24+ broker DBs | **FAIL** | MEDIUM | User search terms not escaped for LIKE wildcards | Escape `%` and `_` in search terms |
| Traceback/exception info disclosure | `blueprints/log.py`, `analyzer.py`, 30+ endpoints | **FAIL** | MEDIUM | Full tracebacks and `str(e)` returned to clients | Return generic errors; log details server-side |
| Strategy execution sandboxing (Windows) | `blueprints/python_strategy.py` | **FAIL** | MEDIUM | No resource limits on Windows; no import sandboxing | Implement Windows Job Objects |
| Telegram input validation | `restx_api/telegram_bot.py` | **FAIL** | MEDIUM | No Marshmallow schemas; unbounded fields | Add schema validation |
| API key length constraints | All schemas | **FAIL** | MEDIUM | No max length on `apikey` fields | Add `Length(min=1, max=256)` |
| Chart schema arbitrary data | `restx_api/account_schema.py` | **FAIL** | MEDIUM | `unknown = INCLUDE` stores any JSON to DB | Restrict to known keys |
| Rate limiting distribution | `app.py` | **FAIL** | MEDIUM | In-memory storage not shared across workers | Use Redis backend |
| Crypto exchange list centralization | 6 independent locations | **FAIL** | MEDIUM (maintenance) | Exchange lists duplicated across utils, schemas, blueprints, sandbox, database | Centralize all to `VALID_EXCHANGES` |
| Crypto MIS square-off handling | `sandbox/squareoff_manager.py` | **FAIL** | HIGH (crypto only) | Unknown exchanges silently skipped; positions never squared off | Add crypto exchange handling |
| ORM parameterization (main DB) | All SQLAlchemy queries | PASS | High check | Proper ORM filters and parameterized `text()` queries | None |
| DuckDB parameterization | `database/historify_db.py` | PASS | High check | `?` placeholders used for all user values (except `compression`) | Fix compression only |
| No eval/exec usage | Entire codebase | PASS | High check | Zero occurrences found | None |
| No insecure deserialization | Entire codebase | PASS | High check | No pickle/unsafe yaml/custom JSON decoders | None |
| Auth/session security | `database/auth_db.py`, `app.py` | PASS | High check | Argon2+pepper, HttpOnly/SameSite cookies, session expiry | None |
| CSRF protection | `app.py` | PASS | High check | Flask-WTF with appropriate exemptions | None |
| Indian broker regression from crypto | Shared services + constants | PASS | Medium | Changes are crypto-gated; no Indian broker route break | Run regression tests |

---

## FINAL VERDICT

- **Indian broker safety:** Existing Indian broker functionality is safe. Crypto integration is additive and does not alter existing exchange validation, order routing, or broker adapter behavior.
- **Codebase security posture:** Strong fundamentals with 3 high-severity gaps (SQL injection, exchange validation, schema bypass) that should be fixed regardless of the crypto PR.
- **Crypto readiness:** Requires P0 fixes (exchange list centralization, MIS square-off handling, `is_crypto()` detection, 24/7 market calendar support) before crypto can go live safely.
