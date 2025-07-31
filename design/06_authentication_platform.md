# Platform Authentication & Authorization

This section describes how users authenticate with the OpenAlgo platform itself (Web UI and API) and how authorization is managed, distinct from authenticating with external brokers.

## Authentication Mechanisms

OpenAlgo supports multiple ways for users/clients to authenticate:

1.  **Web UI Session Authentication (Username/Password):**
    *   **Library:** Uses `Flask-Login` (implied by session usage and typical Flask patterns) and `Flask-Bcrypt` or `Argon2` (explicitly used in `database/auth_db.py` and `database/user_db.py`) for password hashing.
    *   **Flow:**
        1.  User navigates to the login page (`/auth/login`).
        2.  User submits username and password via an HTML form.
        3.  The `auth.login` route in `blueprints/auth.py` receives the credentials.
        4.  `authenticate_user` function (in `database/user_db.py`) retrieves the user record and verifies the submitted password against the stored hash (using `bcrypt.check_password_hash` or `ph.verify`).
        5.  If valid, the username (or user ID) is stored in the Flask `session` (`session['user'] = username`).
        6.  Subsequent requests from the user's browser include the session cookie, allowing Flask to identify the logged-in user.
    *   **Session Management:** Flask's built-in session management (likely server-side sessions secured by `app.secret_key`) is used. The `@check_session_validity` decorator (`utils/session.py`) is used on protected routes to ensure a user is logged in.
    *   **Password Reset:** A password reset flow involving email and TOTP verification is implemented in `auth.reset_password`.

2.  **API Key Authentication:**
    *   **Purpose:** Allows programmatic access to the OpenAlgo API by external applications or scripts.
    *   **Generation:** Users can generate/manage their API keys via the Web UI (`/apikey` route handled by `blueprints/apikey.py`). Secure random keys are generated using `secrets.token_hex`.
    *   **Storage:** API keys are stored securely in the `api_keys` table (`database/auth_db.py`):
        *   A **hash** of the key (peppered with `API_KEY_PEPPER` and hashed using Argon2 `ph.hash`) is stored for verification (`api_key_hash`).
        *   The key itself is **encrypted** using Fernet (derived from `API_KEY_PEPPER`) for potential retrieval/display (`api_key_encrypted`).
    *   **Verification:** When an API request includes an API key (e.g., in an `Authorization` header or query parameter), the platform:
        1.  Retrieves the corresponding `ApiKeys` record based on the provided key (potentially requiring a lookup mechanism or verifying against all stored hashes if the key itself isn't indexed directly for lookup).
        2.  Uses `ph.verify(stored_hash, provided_key + PEPPER)` via the `verify_api_key` function to check if the provided key matches the stored hash.
        3.  If valid, the request is authenticated as the associated `user_id`.

## Authorization

Authorization (determining what an authenticated user is allowed to do) appears relatively simple in the current structure:

*   **Login Required:** Most blueprints/routes likely rely on `@check_session_validity` or API key verification to ensure a user is authenticated.
*   **Role-Based Access Control (RBAC):** There is no explicit evidence of a fine-grained RBAC system (e.g., different user roles like 'admin', 'trader', 'viewer'). Authorization seems primarily based on successful authentication – if a user is logged in or provides a valid API key, they likely have access to most features associated with their account.
*   **Ownership:** Authorization might be implicitly enforced by fetching data scoped to the authenticated `user_id` (e.g., only retrieving orders or strategies belonging to the logged-in user).

## Security Considerations

*   **Password Hashing:** Strong hashing (Argon2) is used for user passwords.
*   **API Key Security:** Keys are hashed for verification and encrypted at rest. A pepper is used.
*   **Session Security:** Flask sessions are signed with `app.secret_key`. Ensure this key is strong and kept secret.
*   **Rate Limiting:** Applied to login and password reset endpoints via `Flask-Limiter` to mitigate brute-force attacks.
*   **Input Validation:** Handled by Flask-WTF and Flask-RESTX.
