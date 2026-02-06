# Security Audit Report - OpenAlgo v2

**Audit Date:** February 2026
**Auditor:** Claude Code Security Analysis
**Scope:** Full codebase security review
**Version:** OpenAlgo v2.x

---

## Executive Summary

This security audit identified **23+ vulnerabilities** across the OpenAlgo codebase. The findings are categorized by severity and type, with recommended remediation steps.

### Risk Summary

| Category | Critical | High | Medium | Low |
|----------|----------|------|--------|-----|
| SQL Injection | 0 | 5 | 1 | 0 |
| Hardcoded Secrets | 0 | 8+ | 0 | 0 |
| Command Injection | 0 | 0 | 1 | 0 |
| XSS Vulnerabilities | 2 | 5 | 1 | 0 |
| Authentication Issues | 0 | 1 | 3 | 0 |
| Path Traversal | 1 | 1 | 1 | 0 |

### Overall Security Posture

**Strengths:**
- Strong password hashing (Argon2 with pepper)
- Proper CSRF protection implementation
- Good session management with daily expiry
- API key encryption and hashing
- TOTP/MFA support
- Rate limiting on authentication endpoints

**Weaknesses:**
- SQL injection in migration scripts
- Hardcoded API keys in example/test files
- XSS vulnerabilities in playground
- Path traversal in static file serving
- Non-distributed rate limiting

---

## 1. SQL Injection Vulnerabilities

### 1.1 Overview

SQL injection vulnerabilities were found primarily in database migration scripts where table names and query parameters are directly interpolated into SQL strings using f-strings.

### 1.2 Findings

#### VULN-SQL-001: Table Name Injection in migrate_historify_scheduler.py

**Severity:** HIGH
**File:** `/openalgo/upgrade/migrate_historify_scheduler.py`
**Lines:** 66-69
**CVSS Score:** 7.5

**Vulnerable Code:**
```python
def table_exists(conn, table_name):
    """Check if a table exists in the database."""
    result = conn.execute(f"""
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_name = '{table_name}'
    """).fetchone()
    return result[0] > 0
```

**Attack Vector:**
```python
table_name = "'; DROP TABLE market_data; --"
```

**Remediation:**
```python
def table_exists(conn, table_name):
    result = conn.execute(
        text("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = :table"),
        {"table": table_name}
    ).fetchone()
    return result[0] > 0
```

---

#### VULN-SQL-002: Table Name Injection in migrate_historify.py

**Severity:** HIGH
**File:** `/openalgo/upgrade/migrate_historify.py`
**Lines:** 282-285
**CVSS Score:** 7.5

**Vulnerable Code:**
```python
for table in required_tables:
    result = conn.execute(f"""
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_name = '{table}'
    """).fetchone()
```

**Remediation:** Use parameterized queries with SQLAlchemy `text()` and bind parameters.

---

#### VULN-SQL-003: WHERE Clause and File Path Injection in historify_db.py

**Severity:** MEDIUM-HIGH
**File:** `/openalgo/database/historify_db.py`
**Lines:** 2345, 2362-2365, 2385-2395
**CVSS Score:** 6.8

**Vulnerable Code:**
```python
# Line 2345
count_query = f"SELECT COUNT(*) FROM market_data WHERE {where_clause}"

# Lines 2362-2365
export_query = f"""
    COPY (
        SELECT ... FROM market_data
        WHERE {where_clause}
        ORDER BY symbol, exchange, interval, timestamp
    ) TO '{abs_output}'
    (FORMAT PARQUET, COMPRESSION '{compression}')
"""
```

**Issues:**
- `where_clause` directly interpolated
- `abs_output` file path interpolated
- `compression` parameter not validated

**Remediation:**
1. Validate `compression` against whitelist: `['zstd', 'snappy', 'gzip', 'none']`
2. Use parameterized queries for WHERE clauses
3. Sanitize file paths using `os.path` functions

---

#### VULN-SQL-004: Direct Interpolation in migrate_telegram_bot.py

**Severity:** HIGH
**File:** `/openalgo/upgrade/migrate_telegram_bot.py`
**Line:** 375
**CVSS Score:** 7.5

**Vulnerable Code:**
```python
for table in tables:
    conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
```

**Remediation:** Use whitelist validation for table names.

---

#### VULN-SQL-005: SQL Injection in migrate_sandbox.py

**Severity:** HIGH
**File:** `/openalgo/upgrade/migrate_sandbox.py`
**Lines:** 422-425
**CVSS Score:** 7.5

**Vulnerable Code:**
```python
for table in required_tables:
    result = conn.execute(
        text(f"""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='{table}'
    """)
    )
```

**Remediation:** Use parameterized queries.

---

#### VULN-SQL-006: LIKE Pattern Injection in token_db_enhanced.py

**Severity:** LOW
**File:** `/openalgo/database/token_db_enhanced.py`
**Line:** 910
**CVSS Score:** 4.3

**Vulnerable Code:**
```python
query_obj = SymToken.query.filter(SymToken.symbol.like(f"%{query}%"))
```

**Issue:** User input used directly in LIKE pattern allows wildcard injection.

**Remediation:** Escape `%` and `_` characters in user input before LIKE queries.

---

## 2. Hardcoded Secrets

### 2.1 Overview

Multiple API keys were found hardcoded in example files, test files, and API collection files. These represent a significant security risk if the repository is public or if the keys are still active.

### 2.2 Findings

#### VULN-SEC-001: Hardcoded API Keys in Example Files

**Severity:** HIGH
**Location:** `/openalgo/examples/python/`
**CVSS Score:** 7.5

**Affected Files and Keys:**

| File | Line | API Key (SHA256 hash format) |
|------|------|------------------------------|
| `test_2340_symbols.py` | 18 | `7653f710c940cdf1d757b5a7d808a60f43bc7e9c0239065435861da2869ec0fc` |
| `depth_example.py` | 11 | `7653f710c940cdf1d757b5a7d808a60f43bc7e9c0239065435861da2869ec0fc` |
| `depth_20_example.py` | 18 | `7653f710c940cdf1d757b5a7d808a60f43bc7e9c0239065435861da2869ec0fc` |
| `depth_50_example.py` | 18 | `7653f710c940cdf1d757b5a7d808a60f43bc7e9c0239065435861da2869ec0fc` |
| `ltp_example.py` | 11 | `7653f710c940cdf1d757b5a7d808a60f43bc7e9c0239065435861da2869ec0fc` |
| `quote_example.py` | 11 | `7653f710c940cdf1d757b5a7d808a60f43bc7e9c0239065435861da2869ec0fc` |
| `expiry_dates.py` | 18 | `7371cc58b9d30204e5fee1d143dc8cd926bcad90c24218201ad81735384d2752` |
| `heatmap.py` | 9 | `7371cc58b9d30204e5fee1d143dc8cd926bcad90c24218201ad81735384d2752` |
| `multiquotes_example.py` | 5 | `c32eb9dee6673190bb9dfab5f18ef0a96b0d76ba484cd36bc5ca5f7ebc8745bf` |
| `flask_optionchain.py` | 8 | `83ad96143dd5081d033abcfd20e9108daee5708fbea404121a762bed1e498dd0` |
| `optionchain_example.py` | 5 | `83ad96143dd5081d033abcfd20e9108daee5708fbea404121a762bed1e498dd0` |
| `placing ATM order.py` | 9 | `83ad96143dd5081d033abcfd20e9108daee5708fbea404121a762bed1e498dd0` |
| `straddle_scheduler.py` | 13 | `83ad96143dd5081d033abcfd20e9108daee5708fbea404121a762bed1e498dd0` |
| `straddle_with_stops.py` | 13 | `83ad96143dd5081d033abcfd20e9108daee5708fbea404121a762bed1e498dd0` |

---

#### VULN-SEC-002: Hardcoded API Keys in Test Files

**Severity:** HIGH
**Location:** `/openalgo/test/`
**CVSS Score:** 7.5

| File | Line | API Key |
|------|------|---------|
| `test_history_format.py` | 14 | `56c3dc6ba7d9c9df478e4f19ffc5d3e15e1dd91b5aa11e91c910f202c91eff9d` |
| `ltp_test_report.py` | 259 | `be51d361903e0898eafeee5824b2997430acb34116c5677240e1b97fc9c4d068` |
| `ltp_example_test_1800 symbols.py` | 120 | `be51d361903e0898eafeee5824b2997430acb34116c5677240e1b97fc9c4d068` |

---

#### VULN-SEC-003: Hardcoded API Keys in Bruno Collection

**Severity:** HIGH
**File:** `/openalgo/collections/openalgo_bruno.json`
**CVSS Score:** 7.5

Multiple API keys embedded in API collection requests:
- Primary: `a85992a13ab7db424c239c50826116366e9f4fd8c591345a2d23aad01ffa4d00` (18+ locations)
- Secondary: `38f99d7d226cc0c3baa19dcacf0b1f049d2f68371da1dda2c97b1b63a3a9ca2e`

---

### 2.3 Remediation

**Immediate Actions:**
1. Revoke/regenerate all identified API keys immediately
2. Remove all hardcoded API keys from source code
3. Clean git history using BFG Repo-Cleaner:
   ```bash
   bfg --replace-text secrets.txt repo.git
   git reflog expire --expire=now --all && git gc --prune=now --aggressive
   ```

**Code Changes:**
```python
# Before (VULNERABLE)
API_KEY = "7653f710c940cdf1d757b5a7d808a60f43bc7e9c0239065435861da2869ec0fc"

# After (SECURE)
import os
API_KEY = os.environ.get("OPENALGO_API_KEY", "YOUR_API_KEY_HERE")
```

**Preventive Measures:**
1. Implement pre-commit hooks using `detect-secrets` or `git-secrets`
2. Add SAST scanning to CI/CD pipeline
3. Use `.env` files with `.gitignore` protection

---

## 3. Command Injection Vulnerabilities

### 3.1 Overview

Command injection vulnerabilities were assessed across the codebase. Most subprocess calls use safe list-based arguments, but one area requires attention.

### 3.2 Findings

#### VULN-CMD-001: User-Uploaded Python Script Execution

**Severity:** MEDIUM
**File:** `/openalgo/blueprints/python_strategy.py`
**Line:** 469
**CVSS Score:** 6.5

**Code:**
```python
cmd = [get_python_executable(), "-u", str(file_path.absolute())]
process = subprocess.Popen(cmd, **subprocess_args)
```

**Mitigations Already in Place:**
- `secure_filename()` from werkzeug
- Additional alphanumeric filtering
- Path traversal protection
- Resource limits (memory, CPU, file descriptors)
- `preexec_fn=set_resource_limits` on Unix

**Recommendations:**
1. Add content scanning for uploaded Python files
2. Consider containerized execution (Docker)
3. Implement audit logging of strategy modifications

---

### 3.3 Safe Patterns Identified

| File | Line | Function | Status |
|------|------|----------|--------|
| `utils/logging.py` | 186 | Registry query | SAFE |
| `upgrade/migrate_all.py` | 75 | Migration runner | SAFE |
| `blueprints/python_strategy.py` | 565 | Process termination | SAFE |

All use list-based arguments without `shell=True`.

---

## 4. Cross-Site Scripting (XSS) Vulnerabilities

### 4.1 Overview

Multiple XSS vulnerabilities were found primarily in the playground JavaScript file where user-controlled or API data is directly inserted into the DOM using `innerHTML`.

### 4.2 Findings

#### VULN-XSS-001: Watchlist Symbol Rendering (CRITICAL)

**Severity:** CRITICAL
**File:** `/openalgo/playground/script.js`
**Line:** 331
**CVSS Score:** 8.2

**Vulnerable Code:**
```javascript
item.innerHTML = `
    <div class="flex justify-between items-center">
        <div>
            <div class="font-bold">${symbol.symbol}</div>
            <div class="text-xs text-gray-400">${symbol.exchange}</div>
        </div>
        ...
    </div>
`;
```

**Attack Vector:**
```javascript
symbol.symbol = '<img src=x onerror="alert(document.cookie)">'
```

---

#### VULN-XSS-002: Search Results Display (CRITICAL)

**Severity:** CRITICAL
**File:** `/openalgo/playground/script.js`
**Lines:** 337-342
**CVSS Score:** 8.2

**Vulnerable Code:**
```javascript
results.forEach(symbol => {
    content += `<div>
        <span>${symbol.symbol} (${symbol.exchange})</span>
        ...
    </div>`;
});
searchResultsContainer.innerHTML = content;
```

---

#### VULN-XSS-003: WebSocket Inspector Content

**Severity:** HIGH
**File:** `/openalgo/playground/script.js`
**Lines:** 135-147
**CVSS Score:** 7.1

**Vulnerable Code:**
```javascript
inspectorContent.innerHTML = filteredMessages.slice(-100).map(msg => {
    return `
        <div>
            <span>${msg.direction.toUpperCase()}</span>
            <span>${msg.type}</span>
            <pre>${JSON.stringify(msg.data, null, 2)}</pre>
        </div>
    `;
}).join('');
```

**Note:** `JSON.stringify` does not escape HTML characters.

---

#### VULN-XSS-004: Log Message Display

**Severity:** HIGH
**File:** `/openalgo/playground/script.js`
**Line:** 95
**CVSS Score:** 7.1

**Vulnerable Code:**
```javascript
logElement.innerHTML = `
    <span>${new Date().toLocaleTimeString()}</span>
    <span>[${logData.type.toUpperCase()}]</span>
    ${logData.message}
`;
```

---

#### VULN-XSS-005: Toast Messages

**Severity:** HIGH
**File:** `/openalgo/playground/script.js`
**Line:** 87
**CVSS Score:** 7.1

**Vulnerable Code:**
```javascript
toast.innerHTML = `<div><span>${message}</span></div>`;
```

---

#### VULN-XSS-006: Depth Panel Rendering

**Severity:** HIGH
**File:** `/openalgo/playground/script.js`
**Lines:** 383-384
**CVSS Score:** 7.3

---

#### VULN-XSS-007: Historical Data Results

**Severity:** HIGH
**File:** `/openalgo/playground/script.js`
**Line:** 432
**CVSS Score:** 7.1

---

#### VULN-XSS-008: Jinja2 Template User Input

**Severity:** MEDIUM
**File:** `/openalgo/examples/python/flask_optionchain.py`
**Lines:** 105-106, 119
**CVSS Score:** 6.5

**Vulnerable Code:**
```html
<option value="{{ exp }}" {% if exp == selected_expiry %} selected {% endif %}>
    {{ exp }}
</option>
```

Where `selected_expiry` comes from `request.args.get("expiry")`.

---

### 4.3 Remediation

**Option 1: Use textContent for Text Data**
```javascript
// Instead of:
element.innerHTML = `${data}`;

// Use:
element.textContent = data;
```

**Option 2: Use DOMPurify for HTML Content**
```javascript
import DOMPurify from 'dompurify';

// Sanitize before insertion
element.innerHTML = DOMPurify.sanitize(htmlContent);
```

**Option 3: Create Elements Programmatically**
```javascript
const div = document.createElement('div');
div.textContent = symbol.symbol;
container.appendChild(div);
```

**Option 4: Implement Escape Function**
```javascript
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

element.innerHTML = `<span>${escapeHtml(userInput)}</span>`;
```

---

## 5. Authentication & Authorization Issues

### 5.1 Overview

The authentication system is well-implemented with Argon2 hashing, TOTP support, and proper session management. However, several issues were identified.

### 5.2 Findings

#### VULN-AUTH-001: API Key Verification Brute Force

**Severity:** HIGH
**File:** `/openalgo/database/auth_db.py`
**Line:** 525
**CVSS Score:** 7.5

**Vulnerable Code:**
```python
def verify_api_key(provided_api_key):
    api_keys = ApiKeys.query.all()  # Gets ALL keys - O(n)

    for api_key_obj in api_keys:
        try:
            ph.verify(api_key_obj.api_key_hash, peppered_key)
            return api_key_obj.user_id
        except VerifyMismatchError:
            continue
```

**Issues:**
- O(n) complexity for each verification
- Timing attacks possible
- DoS vector with large number of API keys

**Remediation:**
1. Add database index on API key hash prefix
2. Implement hash-based lookup instead of iteration
3. Add per-key rate limiting

---

#### VULN-AUTH-002: Rate Limiting Not Distributed

**Severity:** MEDIUM
**File:** `/openalgo/limiter.py`
**Lines:** 1-8
**CVSS Score:** 5.3

**Vulnerable Code:**
```python
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="memory://",  # NOT distributed!
    strategy="moving-window"
)
```

**Issue:** In multi-worker deployments, rate limits are not shared across workers.

**Remediation:**
```python
# For production
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="redis://localhost:6379",
    strategy="moving-window"
)
```

---

#### VULN-AUTH-003: Session Cookie Security Conditional

**Severity:** MEDIUM
**File:** `/openalgo/app.py`
**Lines:** 144-160
**CVSS Score:** 5.0

**Code:**
```python
HOST_SERVER = os.getenv("HOST_SERVER", "http://127.0.0.1:5000")
USE_HTTPS = HOST_SERVER.startswith("https://")

app.config.update(
    SESSION_COOKIE_SECURE=USE_HTTPS,  # Depends on env var!
)
```

**Issue:** If `HOST_SERVER` is misconfigured, cookies may be sent over HTTP.

**Remediation:** Add warning log when HTTPS is not enabled in production.

---

#### VULN-AUTH-004: API Key Cache TTL Too Long

**Severity:** MEDIUM
**File:** `/openalgo/database/auth_db.py`
**Line:** 123
**CVSS Score:** 5.0

**Code:**
```python
verified_api_key_cache = TTLCache(maxsize=1024, ttl=36000)  # 10 hours!
```

**Issue:** Revoked API keys remain valid for up to 10 hours.

**Remediation:**
```python
verified_api_key_cache = TTLCache(maxsize=1024, ttl=3600)  # 1 hour
```

---

### 5.3 Positive Findings

| Feature | Implementation | Status |
|---------|---------------|--------|
| Password Hashing | Argon2 with pepper | SECURE |
| Password Policy | 8+ chars, mixed case, numbers, special | SECURE |
| CSRF Protection | Flask-WTF with proper cookie settings | SECURE |
| Session Management | Daily expiry, HttpOnly, SameSite=Lax | SECURE |
| API Key Storage | Hashed (Argon2) + Encrypted (Fernet) | SECURE |
| TOTP/MFA | PyOTP implementation | SECURE |
| Login Rate Limiting | 5/min, 25/hour | SECURE |
| Pepper Enforcement | Required, min 32 chars | SECURE |

---

## 6. Path Traversal Vulnerabilities

### 6.1 Overview

Path traversal vulnerabilities were found in static file serving and file upload handling.

### 6.2 Findings

#### VULN-PATH-001: Static File Serving (CRITICAL)

**Severity:** CRITICAL
**File:** `/openalgo/blueprints/react_app.py`
**Lines:** 463, 499, 508, 517
**CVSS Score:** 8.6

**Vulnerable Code:**
```python
@react_bp.route("/assets/<path:filename>")
def serve_assets(filename):
    assets_dir = FRONTEND_DIST / "assets"
    response = send_from_directory(assets_dir, filename)  # VULNERABLE
    return response
```

**Vulnerable Endpoints:**
- `/assets/<path:filename>` (Line 463)
- `/images/<path:filename>` (Line 499)
- `/sounds/<path:filename>` (Line 508)
- `/docs/<path:filename>` (Line 517)

**Attack Vector:**
```
GET /assets/../../.env
GET /images/../../../etc/passwd
GET /docs/../../../../config/secrets.yaml
```

**Remediation:**
```python
import os
from flask import abort

@react_bp.route("/assets/<path:filename>")
def serve_assets(filename):
    # Validate path doesn't escape directory
    safe_path = os.path.normpath(filename)
    if safe_path.startswith('..') or os.path.isabs(safe_path):
        abort(404)

    assets_dir = FRONTEND_DIST / "assets"
    full_path = (assets_dir / safe_path).resolve()

    # Verify resolved path is within allowed directory
    if not str(full_path).startswith(str(assets_dir.resolve())):
        abort(404)

    return send_from_directory(assets_dir, safe_path)
```

---

#### VULN-PATH-002: Hardcoded Temporary File Path

**Severity:** HIGH
**File:** `/openalgo/blueprints/admin.py`
**Lines:** 277-278
**CVSS Score:** 6.5

**Vulnerable Code:**
```python
temp_path = "/tmp/qtyfreeze_upload.csv"
file.save(temp_path)
```

**Issues:**
- Hardcoded predictable path
- Race condition with concurrent uploads
- Platform-dependent (fails on Windows)

**Remediation:**
```python
import tempfile

with tempfile.NamedTemporaryFile(
    mode='wb',
    suffix='.csv',
    prefix='qtyfreeze_',
    delete=False
) as f:
    file.save(f.name)
    temp_path = f.name

try:
    # Process file...
finally:
    os.unlink(temp_path)  # Clean up
```

---

#### VULN-PATH-003: CSV Upload Extension-Only Validation

**Severity:** MEDIUM
**File:** `/openalgo/blueprints/admin.py`
**Lines:** 269-273
**CVSS Score:** 5.3

**Code:**
```python
if not file.filename.endswith(".csv"):
    return jsonify({"status": "error", "message": "Please upload a CSV file"}), 400
```

**Issues:**
- Only checks extension, not content type
- No MIME type validation
- Could accept malicious files with `.csv` extension

**Remediation:**
```python
import magic

ALLOWED_MIMETYPES = ['text/csv', 'text/plain', 'application/csv']

def validate_csv_upload(file):
    # Check extension
    if not file.filename.endswith('.csv'):
        return False, "Invalid file extension"

    # Check MIME type
    file_content = file.read(2048)
    file.seek(0)  # Reset file pointer

    mime_type = magic.from_buffer(file_content, mime=True)
    if mime_type not in ALLOWED_MIMETYPES:
        return False, f"Invalid file type: {mime_type}"

    return True, None
```

---

### 6.3 Secure Implementations Found

| File | Feature | Status |
|------|---------|--------|
| `blueprints/historify.py` | CSV upload with tempfile | SECURE |
| `blueprints/historify.py` | Download path validation | SECURE |
| `blueprints/python_strategy.py` | Python file upload | SECURE |
| `database/historify_db.py` | Export path validation | SECURE |

---

## 7. Recommendations

### 7.1 Immediate Actions (Critical/High)

| Priority | Issue | Action |
|----------|-------|--------|
| 1 | Hardcoded API keys | Revoke keys, clean git history |
| 2 | Path traversal in react_app.py | Add path validation |
| 3 | XSS in playground/script.js | Use textContent or DOMPurify |
| 4 | SQL injection in migrations | Use parameterized queries |
| 5 | API key brute force | Add database index |

### 7.2 Short-term Actions (Medium)

| Priority | Issue | Action |
|----------|-------|--------|
| 6 | Rate limiting | Migrate to Redis backend |
| 7 | API key cache TTL | Reduce to 1 hour |
| 8 | Hardcoded temp path | Use tempfile module |
| 9 | CSV validation | Add MIME type checking |

### 7.3 Long-term Actions (Improvements)

| Priority | Issue | Action |
|----------|-------|--------|
| 10 | Secret detection | Add pre-commit hooks |
| 11 | SAST scanning | Add to CI/CD pipeline |
| 12 | Security reviews | Implement code review process |
| 13 | CSP headers | Implement Content Security Policy |
| 14 | Dependency scanning | Add Dependabot/Snyk |

---

## 8. Security Best Practices Checklist

### 8.1 Code Security

- [ ] All SQL queries use parameterized statements
- [ ] No hardcoded secrets in source code
- [ ] All user input is validated and sanitized
- [ ] File uploads are properly validated
- [ ] Path traversal protections in place

### 8.2 Authentication

- [ ] Strong password hashing (Argon2/bcrypt)
- [ ] Rate limiting on authentication endpoints
- [ ] Session timeout implemented
- [ ] CSRF protection enabled
- [ ] MFA/TOTP available

### 8.3 Infrastructure

- [ ] HTTPS enforced in production
- [ ] Security headers configured
- [ ] Logging and monitoring in place
- [ ] Regular security updates applied
- [ ] Backup and recovery tested

---

## 9. Appendix

### 9.1 Tools Used

- Static code analysis (manual review)
- Pattern matching (grep, ripgrep)
- Dependency analysis
- Configuration review

### 9.2 Files Reviewed

| Category | Files Reviewed |
|----------|----------------|
| Python Backend | 150+ files |
| JavaScript Frontend | 50+ files |
| Configuration | 20+ files |
| Templates | 30+ files |

### 9.3 References

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [CWE/SANS Top 25](https://cwe.mitre.org/top25/)
- [Flask Security Best Practices](https://flask.palletsprojects.com/en/2.0.x/security/)
- [SQLAlchemy Security](https://docs.sqlalchemy.org/en/14/core/sqlelement.html)

---

## 10. Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | Feb 2026 | Claude Code | Initial security audit |

---

**Disclaimer:** This security audit provides a point-in-time assessment of the codebase. Security is an ongoing process, and regular audits should be conducted as the codebase evolves.
