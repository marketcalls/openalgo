# OpenAlgo Security Audit

Date: 2025-05-11

This document outlines a security audit performed on the OpenAlgo project. The audit aims to identify potential security vulnerabilities and provide recommendations for improvement.

## Audit Scope

The audit covers the following aspects of the OpenAlgo application:
- Authentication and Authorization
- Input Validation
- Session Management
- Error Handling and Logging
- Security Headers (CSP, CORS)
- Dependency Management
- API Security (including Rate Limiting)
- Configuration Management (including `.env` files and `install.sh`)
- Sensitive Data Exposure (including API keys for brokers)
- Dockerfile and Deployment Security (including `Dockerfile`, `docker-compose.yaml`, `.ebextensions`)
- Broker Integration Security

## Findings and Recommendations

Details for each section will be filled in as the audit progresses.

### 1. Authentication and Authorization
*Investigation needed: Review `app.py`, `blueprints`, `broker` directory, XTS API credential handling.*

### 2. Input Validation
*Investigation needed: Review `app.py`, `blueprints` for XSS, SQLi, etc.*

### 3. Session Management
*Investigation needed: Check for secure cookie handling, session timeouts if sessions are used.*

### 4. Error Handling and Logging
*Investigation needed: Review `app.py`, `logs` directory. Ensure no sensitive data leakage.*

### 5. Security Headers (CSP, CORS)
*Status: Implemented (as per Memory `4b6a564d-c9fb-46f4-a260-d1be9a8937ad` regarding `csp.py`, `cors.py`). Integration in `app.py` confirmed.*

**CORS (`cors.py`, `app.py`, `.sample.env`):**
- Implemented and configurable via environment variables.
- Default `CORS_ENABLED = 'TRUE'`.
- Default `CORS_ALLOWED_ORIGINS = 'http://127.0.0.1:5000'`. This is secure for development but **must** be changed for production to reflect the actual frontend domain(s).
- Default `CORS_ALLOW_CREDENTIALS = 'FALSE'`, which is a good security practice.
- **Recommendation:** Review and update `CORS_ALLOWED_ORIGINS` for production environments.

**CSP (`csp.py`, `app.py`, `.sample.env`):**
- Implemented and configurable via environment variables. Supports report-only mode.
- Default `CSP_ENABLED = 'TRUE'` and `CSP_REPORT_ONLY = 'FALSE'` (enforced by default).
- Default `CSP_DEFAULT_SRC = "'self'"`, which is a strong baseline.
- **Potential Issue (Critical):** `CSP_SCRIPT_SRC` defaults to `"'self' 'unsafe-inline' https://cdn.socket.io https://static.cloudflareinsights.com"`. The use of `'unsafe-inline'` for scripts significantly weakens protection against XSS vulnerabilities. While a comment suggests it's for Socket.IO, this needs thorough investigation to see if nonces, hashes, or stricter policies can be applied.
- `CSP_STYLE_SRC` also includes `'unsafe-inline'`. While less critical than for scripts, avoiding it is preferable.
- `CSP_OBJECT_SRC = "'none'"` is an excellent default.
- `CSP_MEDIA_SRC` includes broad wildcards (`https://*.amazonaws.com https://*.cloudfront.net`). If possible, specify more precise domains.
- `CSP_FRAME_ANCESTORS = "'self'"` provides good clickjacking protection.
- `CSP_UPGRADE_INSECURE_REQUESTS` defaults to `'FALSE'`. This should be `'TRUE'` in production when served over HTTPS.
- `CSP_REPORT_URI` is not set by default. Configuring a report URI is crucial for monitoring and refining the CSP.
- **Recommendations:**
    - **High Priority:** Investigate and aim to remove `'unsafe-inline'` from `CSP_SCRIPT_SRC`. Explore alternatives like nonces/hashes.
    - Attempt to remove `'unsafe-inline'` from `CSP_STYLE_SRC`.
    - Refine `CSP_MEDIA_SRC` to be more specific if possible.
    - Set `CSP_UPGRADE_INSECURE_REQUESTS = 'TRUE'` in production (HTTPS environments).
    - Configure a `CSP_REPORT_URI` for active monitoring of violations.

### 6. Dependency Management
*Investigation of `requirements.txt` and `package.json` complete.*

**Python Dependencies (`requirements.txt`):**
- A comprehensive list of Python packages with pinned versions is provided.
- Key libraries for web framework (Flask, Werkzeug), database (SQLAlchemy), security (argon2, cryptography, PyJWT), and HTTP are included.
- Versions for major components like Flask (3.0.3) and cryptography (44.0.1) appear relatively recent.
- **Manual review of each package for vulnerabilities is impractical.**
- **Recommendations:**
    - **Critical:** Regularly run a vulnerability scanner tool (e.g., `pip-audit install -r requirements.txt` or `safety check -r requirements.txt`) against `requirements.txt` to identify known vulnerabilities.
    - Implement a process for periodically reviewing and updating dependencies to their latest stable and secure versions.

**Node.js Dependencies (`package.json`):**
- Contains only `devDependencies` (autoprefixer, daisyui, postcss, tailwindcss).
- These are used for the frontend asset build process (CSS).
- While not directly part of the runtime production bundle served to users, vulnerabilities in build tools could compromise the build pipeline.
- **Recommendations:**
    - Regularly run `npm audit` (or `yarn audit`) to check `devDependencies` for known vulnerabilities.
    - Keep these build-tool dependencies updated.

### 7. API Security
*Investigation partially complete: Review of rate limiting, input validation, authentication, and authorization.*

**Rate Limiting (`limiter.py`, `restx_api/*.py`, `blueprints/auth.py`, `.sample.env`):**
- `Flask-Limiter` is initialized using `get_remote_address` (IP-based) and a `moving-window` strategy.
- API rate limits (`API_RATE_LIMIT`, default "10 per second") are loaded from `.sample.env` and consistently applied via `@limiter.limit()` decorator to methods within `flask-restx` resources in the `restx_api` directory.
- Login rate limits (`LOGIN_RATE_LIMIT_MIN`, "5 per minute"; `LOGIN_RATE_LIMIT_HOUR`, "25 per hour") are applied to authentication routes in `blueprints/auth.py`.
- This provides good protection against brute-force and denial-of-service attempts on API and authentication endpoints.
- **Consideration:** `storage_uri="memory://"` is used. This is fine for single-process setups but will not provide consistent rate limiting across multiple processes or distributed servers. For such deployments, a shared storage backend (e.g., Redis) is recommended for the limiter.

**Input Validation (`restx_api/schemas.py`, `restx_api/place_order.py`):**
- Marshmallow schemas (e.g., `OrderSchema`) are used for request payload definition.
- Endpoint-specific manual validation is also performed for certain fields (e.g., `exchange`, `action`) against allowed value lists.
- **Potential Issue (High Priority):** Numeric fields like `quantity`, `price` in schemas are defined as `fields.Str()`. This defers type validation and can be error-prone. They should be proper numeric types (e.g., `fields.Integer`, `fields.Float`, `fields.Decimal`) with appropriate validation.
- **Recommendation:**
    - Refactor Marshmallow schemas to use correct numeric types for numeric data, including validation (e.g., range checks).
    - Consider adding length constraints to string fields in schemas (e.g., `symbol`, `strategy`).

**Authentication & Authorization (`restx_api/place_order.py`, `database/auth_db.py`, `blueprints/apikey.py`):**
- **Authentication:** API requests are authenticated via an `apikey` in the JSON body. `database.auth_db.get_auth_token_broker(api_key)` validates this key by comparing a peppered Argon2 hash of the provided key against the stored hash. A valid key retrieves the broker auth token.
- **Authorization:** Access is granted based on a valid API key. No finer-grained permissions within an API key's scope are apparent. This is typical for such APIs.
- Web UI for API key management (`/apikey`) is session-protected.

### 8. Configuration Management
*Investigation completed: Review of `.sample.env` and absence of `install.sh`.*

**`.sample.env` Review:**
- The `.sample.env` file is well-structured and provides defaults for many settings, including security configurations like rate limits, CORS, and CSP.
- **Strengths:**
    - Clear comments, especially for `APP_KEY` and `API_KEY_PEPPER`, instructing users to generate new random values and providing a command for the pepper.
    - Parameterized security settings.
- **Areas for Attention/Recommendations (for production):**
    - `FLASK_DEBUG` should remain `False`.
    - `FLASK_ENV` should be set to `production`.
    - `REDIRECT_URL` and `HOST_SERVER` should use HTTPS.
    - CSP: `'unsafe-inline'` for `script-src` and `style-src` should be mitigated if possible. `CSP_UPGRADE_INSECURE_REQUESTS` should be `TRUE`. `CSP_REPORT_URI` should be configured.

**Installation Script (`install.sh`):**
- **Finding (Critical):** The `install.sh` script is missing from the repository.
- **Impact:** Without an automated setup script:
    - Users must manually copy `.sample.env` to `.env`.
    - There's a very high risk that the default, publicly known `APP_KEY` (Flask `SECRET_KEY`) and `API_KEY_PEPPER` will be used in production.
    - This would allow attackers with knowledge of these defaults to potentially compromise session integrity, decrypt sensitive data (API keys, broker tokens), and bypass CSRF protections.
- **Recommendations (High Priority):**
    1.  **Develop an Installation Script (`install.sh` or equivalent):**
        - This script MUST automatically generate new random values for `APP_KEY` and `API_KEY_PEPPER` when creating the `.env` file.
        - It should not use the default values from `.sample.env` for these critical secrets.
    2.  **Application Startup Check (Defense in Depth):**
        - Consider adding a check in `app.py` that, if `FLASK_ENV` is 'production', warns loudly or refuses to start if the default `APP_KEY` or `API_KEY_PEPPER` are detected.
    3.  **Documentation:**
        - Clearly document the setup process, emphasizing the new installation script and the critical need to use unique secrets.

### 9. Sensitive Data Exposure
*Investigation partially complete: Review of API key and broker token handling.*

**API Key & Broker Token Handling (`database/auth_db.py`, `blueprints/apikey.py`):**
- **API Keys (`ApiKeys` table):**
    - Stored securely. For verification, the user-provided API key is combined with a server-side `API_KEY_PEPPER` and then hashed using Argon2. The hash is stored.
    - For retrieval by the user (e.g., in UI), the raw API key is encrypted using Fernet (AES128-CBC with HMAC-SHA256) and stored. The Fernet key is derived from the `API_KEY_PEPPER` via PBKDF2HMAC.
    - This is a strong approach, protecting keys even if the database is compromised (assuming the `API_KEY_PEPPER` remains secret).
    - API keys are generated using `secrets.token_hex(32)`, which is secure.
- **Broker Authentication Tokens (`Auth` table):**
    - Broker `auth_token` and `feed_token` are encrypted using the same Fernet mechanism (key derived from `API_KEY_PEPPER`) before database storage.
    - Decrypted tokens are cached in memory for 30 seconds for performance.
- **Criticality of `API_KEY_PEPPER`:** The security of all encrypted API keys and broker tokens hinges on the secrecy of the `API_KEY_PEPPER`. Its compromise would allow decryption of this sensitive data.
- **Recommendations:**
    - Strongly document the importance of a unique, strong `API_KEY_PEPPER` for production and its protection as a critical secret.
    - Advise users to treat their API keys with the same security level as passwords when displayed in the UI.

### 10. Dockerfile and Deployment Security
*Investigation completed: Review of `Dockerfile`, `start.sh`, and `docker-compose.yaml`.*

**`Dockerfile` Analysis:**
- Uses a multi-stage build (builder and production stages), which is good practice.
- Base images `python:3.13-bookworm` (builder) and `python:3.13-slim-bookworm` (production) are specific and the `slim` variant for production is good for reducing size and attack surface.
- Installs dependencies using `uv` within a virtual environment (`.venv`).
- **Security Best Practice Implemented:** Runs the application as a non-root user (`appuser`).
- **Potential Issues/Recommendations:**
    - **`COPY . .` (High Priority):** The production stage uses `COPY --chown=appuser:appuser . .`, which copies the entire build context. This could include sensitive files (e.g., `.git`, local `.env` files if not gitignored/dockerignored), test files, etc. 
        - **Recommendation:** Create a comprehensive `.dockerignore` file. Be more specific in `COPY` commands (e.g., copy only necessary app directories like `openalgo/`, `static/`, `templates/`).
    - **Lock Files:** If `uv sync` uses a lock file (e.g., `uv.lock`, `poetry.lock`), ensure it's copied to the builder stage before `uv sync` for reproducible builds. `pyproject.toml` should pin dependencies.

**`start.sh` Analysis (Entrypoint Script):**
- Creates `db` and `logs` directories.
- **Critical Vulnerability:** Executes `chmod -R 777 db logs`. This gives universal read/write/execute permissions, which is highly insecure for the database and log directories. This command should be **removed entirely**.
- Starts Gunicorn with `eventlet` workers. Number of workers is hardcoded to 1; consider making this configurable for production (e.g., via `GUNICORN_WORKERS` env var).

**`docker-compose.yaml` Analysis:**
- Builds the image using the `Dockerfile`.
- Maps host port (default 5000 or `$FLASK_PORT`) to container port 5000.
- **Volumes:**
    - Mounts `./db:/app/db` for database persistence. The `chmod 777` in `start.sh` poses a risk to the host's `./db` directory if this mount is used.
    - Mounts `./.env:/app/.env:ro` (read-only), which is a good way to provide environment configuration.
- **Environment Variables:** Sets `FLASK_ENV=production` and `FLASK_DEBUG=0` by default, which are secure defaults.
- `restart: unless-stopped` is good for resilience.

**Overall Recommendations for Docker Setup:**
1.  **`start.sh` (Critical):** Remove `chmod -R 777 db logs`.
2.  **`Dockerfile` (High Priority):** Implement `.dockerignore` and use specific `COPY` statements.
3.  **`Dockerfile`/`pyproject.toml`:** Ensure fully pinned dependencies for reproducible and secure builds.
4.  **Gunicorn Workers (`start.sh`):** Make worker count configurable.

### 11. Broker Integration Security
*Investigation partially complete: Review of `zerodha` and `upstox` broker modules (`auth_api.py`, `order_api.py`).*

**Common Findings (Zerodha, Upstox):**
- **Credential Sourcing for Initial Auth (High Priority Concern):**
    - Both `broker/zerodha/api/auth_api.py` and `broker/upstox/api/auth_api.py` fetch primary broker credentials (e.g., `BROKER_API_KEY`, `BROKER_API_SECRET`) directly from environment variables using `os.getenv()`.
    - This bypasses the centralized, encrypted storage mechanism provided by `database/auth_db.py` for managing sensitive tokens.
    - **Implications:**
        - Reduced flexibility: Likely ties an application instance to a single set of broker API credentials per broker type, or requires complex environment management for multiple users/accounts.
        - Inconsistent security model: `access_tokens` (session tokens) are intended to be stored encrypted in the database, but the primary keys/secrets to obtain these tokens are sourced less securely from environment variables.
        - Security relies heavily on the protection of these environment variables. If compromised, attacker gains direct access to broker API key/secret.
- **Access Token Usage:**
    - Once an `access_token` is obtained (presumably stored by `auth_db.py` and retrieved by higher-level functions), it is correctly used in the `Authorization` header for subsequent API calls (e.g., in `order_api.py` for both Zerodha and Upstox).
- **API Communication:** All direct interactions with broker APIs (e.g., token exchange, order placement) use HTTPS.
- **Redundant API Key Fetching (Zerodha `order_api.py`):**
    - Zerodha's `order_api.py` also fetches `BROKER_API_KEY` via `os.getenv()` and includes it in the order placement payload. This is likely unnecessary as the `access_token` in the header should suffice for Zerodha's order API.
- **Debugging `print` Statements:** Some broker API files (e.g., Zerodha `order_api.py`) contain `print()` statements for payload/response data that should be removed or guarded in production.

**Recommendations for Broker Integration:**
1.  **Centralize Broker Credential Management (High Priority - Strategic):**
    - Align the management of initial broker API keys/secrets with the secure, encrypted storage approach in `database/auth_db.py`.
    - Modify `auth_db.py` (or create a related mechanism) to securely store these initial credentials (encrypted with `API_KEY_PEPPER`) per user/broker configuration.
    - Update individual broker `auth_api.py` scripts to fetch these credentials from the central database store, not `os.getenv()`.
    - This enhances security and flexibility for users managing multiple broker accounts.
    - If the global environment variable approach is a deliberate choice for specific deployment scenarios, this must be clearly documented along with its security implications.
2.  **Remove Unnecessary API Key Usage:** Clean up redundant fetching/sending of `BROKER_API_KEY` in Zerodha's `order_api.py` if it's not required by the broker when an `access_token` is used.
3.  **Sanitize Debug Logs:** Remove or conditionally compile `print` statements that output sensitive API request/response data.

*Further investigation needed: Review error handling and data sanitization in other broker modules if time permits, or assume similar patterns.* 

## Summary Table

| Area                          | Status        | Notes & Recommendations                                     |
|-------------------------------|---------------|-------------------------------------------------------------|
| Authentication & Authorization| TBD           |                                                             |
| Input Validation              | TBD           |                                                             |
| Session Management            | TBD           |                                                             |
| Error Handling and Logging    | Partially Reviewed | Default Flask logging. Debug prints found in some modules (e.g. broker APIs). **Further review recommended to ensure no sensitive data is logged, especially in production or verbose debug modes.** |
| Security Headers (CSP, CORS)  | Implemented   | CORS: Defaults good for dev, `CORS_ALLOWED_ORIGINS` needs prod config. <br> CSP: Good baseline, but `'unsafe-inline'` in `script-src` is a critical concern. `CSP_UPGRADE_INSECURE_REQUESTS` and `CSP_REPORT_URI` need attention for production. |
| Dependency Management         | Partially Reviewed | Python: Pinned versions present; recommend automated vulnerability scanning (e.g., `pip-audit`) and regular updates. <br> Node.js: Only `devDependencies`; recommend `npm audit` and regular updates. |
| API Security                  | Reviewed           | Rate limiting OK (scaler consideration for `memory://` store). Input validation needs schema numeric types fixed (High Prio). AuthN/AuthZ uses secure API key (Argon2 hash verify, Fernet encrypt store), links to broker. |
| Configuration Management      | Reviewed           | `.sample.env` is good, but **CRITICAL risk due to missing `install.sh` to enforce unique `APP_KEY` & `API_KEY_PEPPER` generation.** Recommendations made for script creation and app startup checks. | 
| Sensitive Data Exposure       | Reviewed           | API keys stored securely (Argon2 hash + Pepper for verify; Fernet encrypt + Pepper for retrieve). Broker tokens Fernet encrypted. `API_KEY_PEPPER` is critical. |
| Dockerfile & Deployment       | Reviewed           | `Dockerfile` good (multi-stage, non-root). **CRITICAL: `start.sh` uses `chmod 777`**. `docker-compose.yaml` secure defaults. Recommendations: `.dockerignore`, specific COPYs, remove `chmod 777`. | 
| Broker Integration Security   | Partially Reviewed | HTTPS used. `access_tokens` used correctly. **HIGH RISK: Initial broker API Key/Secrets fetched via `os.getenv()` in broker modules, bypassing central encrypted store.** Recommendation: Centralize and encrypt storage of initial broker keys/secrets. | 
