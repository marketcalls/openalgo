# OpenAlgo Private Broker Token API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a private service-to-service endpoint that lets KhazanaOS import a freshly minted Zerodha broker access token into OpenAlgo's normal encrypted broker-auth storage.

**Architecture:** Add a new internal Flask blueprint at `POST /internal/broker-token` guarded by `OPENALGO_TOKEN_SERVICE_SECRET` plus a dedicated header. Put request validation, Zerodha profile validation, unchanged-token detection, and auth activation in a new service so the route stays thin. Refactor `utils/auth_utils.py` so browser broker login and the private import path share token persistence, cache invalidation, and master-contract side effects without creating browser session state for the private API.

**Tech Stack:** Flask blueprints, Flask-WTF CSRF exemptions, Flask-Limiter, SQLAlchemy auth models, shared `utils.httpx_client.get_httpx_client()`, pytest, Ruff.

---

## Branch

Work on branch:

```bash
git switch codex/openalgo-private-broker-token-api
```

If this branch is not present in the worker's checkout:

```bash
git switch -c codex/openalgo-private-broker-token-api main
```

## Source Spec

Read before implementation:

```bash
sed -n '1,260p' /Users/navtej/work/KhazanaOS/docs/superpowers/handoffs/2026-06-15-openalgo-private-broker-token-api.md
```

The OpenAlgo repo is the only implementation target. Do not add KhazanaOS caller changes in this branch.

## File Structure

- Create `blueprints/internal_broker_token.py`: private route, secret gate, header verification with `hmac.compare_digest()`, JSON parsing, service error mapping, rate limit.
- Create `services/broker_token_import_service.py`: API-key verification, supported-broker validation, Zerodha access-token validation, unchanged-token detection, auth activation, sanitized logging.
- Modify `broker/zerodha/api/auth_api.py`: add reusable Zerodha token formatting and profile validation helpers; keep `authenticate_broker()` behavior unchanged.
- Modify `utils/auth_utils.py`: add `activate_broker_auth_token()` for session-independent persistence and master-contract work; refactor `handle_auth_success()` to call it after browser session setup.
- Modify `blueprints/brlogin.py`: replace inline Zerodha `BROKER_API_KEY:access_token` formatting with the new Zerodha helper.
- Modify `app.py`: import/register the new blueprint with `url_prefix="/internal"` and exempt only `internal_broker_token.broker_token` from CSRF.
- Create `test/test_internal_broker_token_api.py`: endpoint contract, service behavior, no-raw-token logging, and unchanged-token behavior.
- Modify `test/test_auth_resume.py`: add a targeted Zerodha callback regression proving browser OAuth still stores `BROKER_API_KEY:access_token`.

---

### Task 1: Add Zerodha Token Formatting And Validation Helpers

**Files:**
- Modify: `broker/zerodha/api/auth_api.py`
- Test: `test/test_internal_broker_token_api.py`

- [ ] **Step 1: Write failing tests for Zerodha helpers**

Add these imports and tests to the new `test/test_internal_broker_token_api.py` file:

```python
import logging
from types import SimpleNamespace

import pytest

from broker.zerodha.api import auth_api as zerodha_auth_api


def test_zerodha_format_auth_token_uses_clean_env_api_key(monkeypatch):
    monkeypatch.setenv("BROKER_API_KEY", "'kite-key'")

    assert zerodha_auth_api.format_auth_token('"raw-access-token"') == "kite-key:raw-access-token"


def test_zerodha_format_auth_token_rejects_missing_api_key(monkeypatch):
    monkeypatch.delenv("BROKER_API_KEY", raising=False)

    with pytest.raises(ValueError, match="zerodha_broker_api_key_missing"):
        zerodha_auth_api.format_auth_token("raw-access-token")


def test_zerodha_format_auth_token_rejects_blank_access_token(monkeypatch):
    monkeypatch.setenv("BROKER_API_KEY", "kite-key")

    with pytest.raises(ValueError, match="zerodha_access_token_missing"):
        zerodha_auth_api.format_auth_token("  ")


def test_zerodha_validate_access_token_calls_profile(monkeypatch):
    monkeypatch.setenv("BROKER_API_KEY", "kite-key")
    calls = []

    class FakeClient:
        def get(self, url, headers):
            calls.append((url, headers))
            return SimpleNamespace(
                status_code=200,
                json=lambda: {"status": "success", "data": {"user_name": "Admin"}},
            )

    monkeypatch.setattr(zerodha_auth_api, "get_httpx_client", lambda: FakeClient())

    is_valid, reason = zerodha_auth_api.validate_access_token("raw-access-token")

    assert is_valid is True
    assert reason is None
    assert calls == [
        (
            "https://api.kite.trade/user/profile",
            {
                "Authorization": "token kite-key:raw-access-token",
                "X-Kite-Version": "3",
            },
        )
    ]


def test_zerodha_validate_access_token_rejects_profile_failure(monkeypatch):
    monkeypatch.setenv("BROKER_API_KEY", "kite-key")

    class FakeClient:
        def get(self, url, headers):
            return SimpleNamespace(
                status_code=403,
                json=lambda: {"status": "error", "message": "Token is invalid"},
            )

    monkeypatch.setattr(zerodha_auth_api, "get_httpx_client", lambda: FakeClient())

    is_valid, reason = zerodha_auth_api.validate_access_token("raw-access-token")

    assert is_valid is False
    assert reason == "zerodha_profile_rejected"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest test/test_internal_broker_token_api.py -q
```

Expected: fail with `AttributeError` for `format_auth_token` and `validate_access_token`.

- [ ] **Step 3: Add helpers to `broker/zerodha/api/auth_api.py`**

Keep `authenticate_broker()` intact and add these helpers above it:

```python
def _clean_secret_value(value: str | None) -> str:
    return (value or "").strip().strip("'\"")


def format_auth_token(access_token: str) -> str:
    broker_api_key = _clean_secret_value(os.getenv("BROKER_API_KEY"))
    cleaned_token = _clean_secret_value(access_token)
    if not broker_api_key:
        raise ValueError("zerodha_broker_api_key_missing")
    if not cleaned_token:
        raise ValueError("zerodha_access_token_missing")
    return f"{broker_api_key}:{cleaned_token}"


def validate_access_token(access_token: str) -> tuple[bool, str | None]:
    try:
        auth_token = format_auth_token(access_token)
    except ValueError as exc:
        return False, str(exc)

    client = get_httpx_client()
    try:
        response = client.get(
            "https://api.kite.trade/user/profile",
            headers={
                "Authorization": f"token {auth_token}",
                "X-Kite-Version": "3",
            },
        )
    except Exception:
        return False, "zerodha_profile_request_failed"

    if response.status_code != 200:
        return False, "zerodha_profile_rejected"

    try:
        payload = response.json()
    except ValueError:
        return False, "zerodha_profile_invalid_json"

    if payload.get("status") == "success":
        return True, None
    return False, "zerodha_profile_rejected"
```

- [ ] **Step 4: Run helper tests**

Run:

```bash
uv run pytest test/test_internal_broker_token_api.py -q
```

Expected: the helper tests pass. Later tests in this file may still be absent until subsequent tasks add them.

- [ ] **Step 5: Commit**

```bash
git add broker/zerodha/api/auth_api.py test/test_internal_broker_token_api.py
git commit -m "feat: add zerodha token formatting helpers"
```

---

### Task 2: Split Browser Session Auth From Broker Token Activation

**Files:**
- Modify: `utils/auth_utils.py`
- Test: `test/test_internal_broker_token_api.py`

- [ ] **Step 1: Write failing tests for session-independent activation**

Append these tests to `test/test_internal_broker_token_api.py`:

```python
import utils.auth_utils as auth_utils


def test_activate_broker_auth_token_upserts_and_starts_download(monkeypatch):
    calls = []

    monkeypatch.setattr(
        auth_utils,
        "upsert_auth",
        lambda name, auth_token, broker, feed_token=None, user_id=None: calls.append(
            ("upsert", name, auth_token, broker, feed_token, user_id)
        )
        or 42,
    )
    monkeypatch.setattr(
        auth_utils,
        "init_broker_status",
        lambda broker: calls.append(("init_status", broker)),
    )
    monkeypatch.setattr(
        auth_utils,
        "should_download_master_contract",
        lambda broker: (True, "No previous download found"),
    )

    class FakeThread:
        def __init__(self, target, args, daemon):
            calls.append(("thread", target.__name__, args, daemon))

        def start(self):
            calls.append(("thread_started",))

    monkeypatch.setattr(auth_utils, "Thread", FakeThread)

    inserted_id = auth_utils.activate_broker_auth_token(
        "kite-key:raw-access-token",
        "admin",
        "zerodha",
    )

    assert inserted_id == 42
    assert calls == [
        ("upsert", "admin", "kite-key:raw-access-token", "zerodha", None, None),
        ("init_status", "zerodha"),
        ("thread", "async_master_contract_download", ("zerodha",), True),
        ("thread_started",),
    ]


def test_activate_broker_auth_token_loads_existing_contract_when_fresh(monkeypatch):
    calls = []

    monkeypatch.setattr(auth_utils, "upsert_auth", lambda *args, **kwargs: 43)
    monkeypatch.setattr(auth_utils, "init_broker_status", lambda broker: calls.append(("init", broker)))
    monkeypatch.setattr(
        auth_utils,
        "should_download_master_contract",
        lambda broker: (False, "Already downloaded today"),
    )

    class FakeThread:
        def __init__(self, target, args, daemon):
            calls.append(("thread", target.__name__, args, daemon))

        def start(self):
            calls.append(("started",))

    monkeypatch.setattr(auth_utils, "Thread", FakeThread)

    assert auth_utils.activate_broker_auth_token("token", "admin", "zerodha") == 43
    assert calls == [
        ("init", "zerodha"),
        ("thread", "load_existing_master_contract", ("zerodha",), True),
        ("started",),
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest test/test_internal_broker_token_api.py -q
```

Expected: fail with `AttributeError: module 'utils.auth_utils' has no attribute 'activate_broker_auth_token'`.

- [ ] **Step 3: Add `activate_broker_auth_token()` to `utils/auth_utils.py`**

Place this helper above `handle_auth_success()`:

```python
def activate_broker_auth_token(auth_token, user_session_key, broker, feed_token=None, user_id=None):
    """
    Persist broker auth and start master-contract work without touching Flask session state.

    Browser logins and private service-to-service token imports share this path so
    cache invalidation, broker status initialization, and master-contract loading stay identical.
    """
    inserted_id = upsert_auth(
        user_session_key,
        auth_token,
        broker,
        feed_token=feed_token,
        user_id=user_id,
    )
    if not inserted_id:
        logger.error(f"Failed to upsert auth token for user {user_session_key}")
        return None

    logger.info(f"Database record upserted with ID: {inserted_id}")
    init_broker_status(broker)

    should_download, reason = should_download_master_contract(broker)
    logger.info(
        f"Smart download check for {broker}: should_download={should_download}, reason={reason}"
    )

    if should_download:
        thread = Thread(target=async_master_contract_download, args=(broker,), daemon=True)
        thread.start()
    else:
        logger.info(f"Skipping download for {broker}: {reason}")
        thread = Thread(target=load_existing_master_contract, args=(broker,), daemon=True)
        thread.start()

    return inserted_id
```

- [ ] **Step 4: Refactor `handle_auth_success()` to call the helper**

Replace the block from `# Store auth token in database` through the `else` handling of failed upsert with:

```python
    inserted_id = activate_broker_auth_token(
        auth_token,
        user_session_key,
        broker,
        feed_token=feed_token,
        user_id=user_id,
    )
    if inserted_id:
        if is_ajax_request():
            return jsonify(
                {
                    "status": "success",
                    "message": "Authentication successful",
                    "redirect": "/dashboard",
                }
            ), 200
        return redirect(url_for("dashboard_bp.dashboard"))

    if is_ajax_request():
        return jsonify(
            {
                "status": "error",
                "message": "Failed to store authentication token. Please try again.",
            }
        ), 500
    return redirect(url_for("auth.broker_login"))
```

- [ ] **Step 5: Run auth utility tests**

Run:

```bash
uv run pytest test/test_internal_broker_token_api.py test/test_auth_resume.py -q
```

Expected: pass for the new activation tests and existing auth-resume tests.

- [ ] **Step 6: Commit**

```bash
git add utils/auth_utils.py test/test_internal_broker_token_api.py
git commit -m "refactor: share broker auth activation path"
```

---

### Task 3: Create Broker Token Import Service

**Files:**
- Create: `services/broker_token_import_service.py`
- Test: `test/test_internal_broker_token_api.py`

- [ ] **Step 1: Write failing service tests**

Append these tests to `test/test_internal_broker_token_api.py`:

```python
from services import broker_token_import_service as import_service


def test_import_broker_token_rejects_invalid_apikey(monkeypatch):
    monkeypatch.setattr(import_service, "verify_api_key", lambda apikey: None)

    with pytest.raises(import_service.InvalidApiKeyError) as exc:
        import_service.import_broker_token("bad-api-key", "zerodha", "raw-access-token")

    assert exc.value.status_code == 403


def test_import_broker_token_rejects_unsupported_broker(monkeypatch):
    with pytest.raises(import_service.UnsupportedBrokerError) as exc:
        import_service.import_broker_token("openalgo-api-key", "dhan", "raw-access-token")

    assert exc.value.status_code == 400


def test_import_broker_token_rejects_blank_access_token(monkeypatch):
    with pytest.raises(import_service.InvalidAccessTokenError) as exc:
        import_service.import_broker_token("openalgo-api-key", "zerodha", " ")

    assert exc.value.status_code == 400


def test_import_broker_token_validation_failure_does_not_activate(monkeypatch):
    activated = {"called": False}

    monkeypatch.setattr(import_service, "verify_api_key", lambda apikey: "admin")
    monkeypatch.setattr(import_service, "format_auth_token", lambda token: "kite-key:raw-access-token")
    monkeypatch.setattr(
        import_service,
        "validate_access_token",
        lambda token: (False, "zerodha_profile_rejected"),
    )
    monkeypatch.setattr(
        import_service,
        "activate_broker_auth_token",
        lambda *args, **kwargs: activated.update(called=True),
    )

    with pytest.raises(import_service.InvalidAccessTokenError):
        import_service.import_broker_token("openalgo-api-key", "zerodha", "raw-access-token")

    assert activated["called"] is False


def test_import_broker_token_success_activates_formatted_token(monkeypatch):
    calls = []

    monkeypatch.setattr(import_service, "verify_api_key", lambda apikey: "admin")
    monkeypatch.setattr(import_service, "format_auth_token", lambda token: "kite-key:raw-access-token")
    monkeypatch.setattr(import_service, "validate_access_token", lambda token: (True, None))
    monkeypatch.setattr(import_service, "get_auth_token", lambda user_id, bypass_cache=False: None)
    monkeypatch.setattr(
        import_service,
        "activate_broker_auth_token",
        lambda auth_token, user_session_key, broker: calls.append(
            (auth_token, user_session_key, broker)
        )
        or 42,
    )

    result = import_service.import_broker_token("openalgo-api-key", "zerodha", "raw-access-token")

    assert result.broker == "zerodha"
    assert result.user_id == "admin"
    assert result.updated is True
    assert calls == [("kite-key:raw-access-token", "admin", "zerodha")]


def test_import_broker_token_unchanged_skips_activation(monkeypatch):
    activated = {"called": False}

    monkeypatch.setattr(import_service, "verify_api_key", lambda apikey: "admin")
    monkeypatch.setattr(import_service, "format_auth_token", lambda token: "kite-key:raw-access-token")
    monkeypatch.setattr(import_service, "validate_access_token", lambda token: (True, None))
    monkeypatch.setattr(
        import_service,
        "get_auth_token",
        lambda user_id, bypass_cache=False: "kite-key:raw-access-token",
    )
    monkeypatch.setattr(
        import_service,
        "activate_broker_auth_token",
        lambda *args, **kwargs: activated.update(called=True),
    )

    result = import_service.import_broker_token("openalgo-api-key", "zerodha", "raw-access-token")

    assert result.updated is False
    assert activated["called"] is False


def test_import_broker_token_persistence_failure_maps_to_500(monkeypatch):
    monkeypatch.setattr(import_service, "verify_api_key", lambda apikey: "admin")
    monkeypatch.setattr(import_service, "format_auth_token", lambda token: "kite-key:raw-access-token")
    monkeypatch.setattr(import_service, "validate_access_token", lambda token: (True, None))
    monkeypatch.setattr(import_service, "get_auth_token", lambda user_id, bypass_cache=False: None)
    monkeypatch.setattr(import_service, "activate_broker_auth_token", lambda *args, **kwargs: None)

    with pytest.raises(import_service.BrokerTokenPersistenceError) as exc:
        import_service.import_broker_token("openalgo-api-key", "zerodha", "raw-access-token")

    assert exc.value.status_code == 500
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest test/test_internal_broker_token_api.py -q
```

Expected: fail with `ImportError` or missing service attributes.

- [ ] **Step 3: Implement `services/broker_token_import_service.py`**

Create the file with:

```python
import hashlib
from dataclasses import dataclass

from broker.zerodha.api.auth_api import format_auth_token, validate_access_token
from database.auth_db import get_auth_token, verify_api_key
from utils.auth_utils import activate_broker_auth_token
from utils.logging import get_logger

logger = get_logger(__name__)


class BrokerTokenImportError(Exception):
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InvalidApiKeyError(BrokerTokenImportError):
    status_code = 403


class UnsupportedBrokerError(BrokerTokenImportError):
    status_code = 400


class InvalidAccessTokenError(BrokerTokenImportError):
    status_code = 400


class BrokerTokenPersistenceError(BrokerTokenImportError):
    status_code = 500


@dataclass(frozen=True)
class BrokerTokenImportResult:
    broker: str
    user_id: str
    updated: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "broker": self.broker,
            "user_id": self.user_id,
            "updated": self.updated,
        }


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def _log_import_result(broker: str, user_id: str, access_token: str, updated: bool) -> None:
    logger.info(
        "Broker token import broker=%s user_id=%s token_len=%d token_fp=%s updated=%s",
        broker,
        user_id,
        len(access_token),
        _fingerprint(access_token),
        updated,
    )


def import_broker_token(apikey: str | None, broker: str | None, access_token: str | None):
    cleaned_broker = (broker or "").strip().lower()
    if cleaned_broker != "zerodha":
        raise UnsupportedBrokerError("unsupported_broker")

    cleaned_access_token = (access_token or "").strip().strip("'\"")
    if not cleaned_access_token:
        raise InvalidAccessTokenError("zerodha_access_token_missing")

    cleaned_apikey = (apikey or "").strip()
    if not cleaned_apikey:
        raise InvalidApiKeyError("invalid_openalgo_apikey")

    user_id = verify_api_key(cleaned_apikey)
    if not user_id:
        raise InvalidApiKeyError("invalid_openalgo_apikey")

    try:
        formatted_token = format_auth_token(cleaned_access_token)
    except ValueError as exc:
        raise InvalidAccessTokenError(str(exc)) from exc

    is_valid, validation_reason = validate_access_token(cleaned_access_token)
    if not is_valid:
        raise InvalidAccessTokenError(validation_reason or "zerodha_profile_rejected")

    existing_token = get_auth_token(user_id, bypass_cache=True)
    if existing_token == formatted_token:
        _log_import_result(cleaned_broker, user_id, cleaned_access_token, updated=False)
        return BrokerTokenImportResult(
            broker=cleaned_broker,
            user_id=user_id,
            updated=False,
        )

    inserted_id = activate_broker_auth_token(formatted_token, user_id, cleaned_broker)
    if not inserted_id:
        raise BrokerTokenPersistenceError("broker_token_persist_failed")

    _log_import_result(cleaned_broker, user_id, cleaned_access_token, updated=True)
    return BrokerTokenImportResult(
        broker=cleaned_broker,
        user_id=user_id,
        updated=True,
    )
```

- [ ] **Step 4: Run service tests**

Run:

```bash
uv run pytest test/test_internal_broker_token_api.py -q
```

Expected: service tests pass.

- [ ] **Step 5: Commit**

```bash
git add services/broker_token_import_service.py test/test_internal_broker_token_api.py
git commit -m "feat: add broker token import service"
```

---

### Task 4: Add Private Internal Blueprint And App Registration

**Files:**
- Create: `blueprints/internal_broker_token.py`
- Modify: `app.py`
- Test: `test/test_internal_broker_token_api.py`

- [ ] **Step 1: Write failing endpoint tests**

Append these tests to `test/test_internal_broker_token_api.py`:

```python
from flask import Flask

from limiter import limiter
from blueprints import internal_broker_token as internal_broker_token_module
from blueprints.internal_broker_token import internal_broker_token_bp


@pytest.fixture()
def internal_token_client():
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        RATELIMIT_ENABLED=False,
    )
    limiter.init_app(app)
    app.register_blueprint(internal_broker_token_bp, url_prefix="/internal")
    return app.test_client()


def _post_broker_token(client, header_secret="shared-secret", payload=None):
    headers = {}
    if header_secret is not None:
        headers["X-OpenAlgo-Token-Service-Secret"] = header_secret
    return client.post(
        "/internal/broker-token",
        json=payload
        or {
            "apikey": "openalgo-api-key",
            "broker": "zerodha",
            "access_token": "raw-access-token",
        },
        headers=headers,
    )


def test_internal_broker_token_secret_unset_returns_404(
    monkeypatch,
    internal_token_client,
):
    monkeypatch.delenv("OPENALGO_TOKEN_SERVICE_SECRET", raising=False)

    response = _post_broker_token(internal_token_client)

    assert response.status_code == 404


def test_internal_broker_token_missing_secret_header_returns_403(
    monkeypatch,
    internal_token_client,
):
    monkeypatch.setenv("OPENALGO_TOKEN_SERVICE_SECRET", "shared-secret")

    response = _post_broker_token(internal_token_client, header_secret=None)

    assert response.status_code == 403


def test_internal_broker_token_bad_secret_header_returns_403(
    monkeypatch,
    internal_token_client,
):
    monkeypatch.setenv("OPENALGO_TOKEN_SERVICE_SECRET", "shared-secret")

    response = _post_broker_token(internal_token_client, header_secret="wrong-secret")

    assert response.status_code == 403


def test_internal_broker_token_success_response(
    monkeypatch,
    internal_token_client,
):
    monkeypatch.setenv("OPENALGO_TOKEN_SERVICE_SECRET", "shared-secret")

    monkeypatch.setattr(
        internal_broker_token_module,
        "import_broker_token",
        lambda **kwargs: import_service.BrokerTokenImportResult(
            broker="zerodha",
            user_id="admin",
            updated=True,
        ),
    )

    response = _post_broker_token(internal_token_client)

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "success",
        "data": {"broker": "zerodha", "user_id": "admin", "updated": True},
    }


def test_internal_broker_token_service_error_response(
    monkeypatch,
    internal_token_client,
):
    monkeypatch.setenv("OPENALGO_TOKEN_SERVICE_SECRET", "shared-secret")

    def fail_import(**kwargs):
        raise import_service.UnsupportedBrokerError("unsupported_broker")

    monkeypatch.setattr(internal_broker_token_module, "import_broker_token", fail_import)

    response = _post_broker_token(
        internal_token_client,
        payload={
            "apikey": "openalgo-api-key",
            "broker": "dhan",
            "access_token": "raw-access-token",
        },
    )

    assert response.status_code == 400
    assert response.get_json() == {"status": "error", "message": "unsupported_broker"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest test/test_internal_broker_token_api.py -q
```

Expected: fail with missing `blueprints.internal_broker_token`.

- [ ] **Step 3: Implement `blueprints/internal_broker_token.py`**

Create:

```python
import hmac
import os

from flask import Blueprint, jsonify, request

from limiter import limiter
from services.broker_token_import_service import BrokerTokenImportError, import_broker_token

internal_broker_token_bp = Blueprint("internal_broker_token", __name__)

SECRET_HEADER = "X-OpenAlgo-Token-Service-Secret"


def _configured_secret() -> str:
    return (os.getenv("OPENALGO_TOKEN_SERVICE_SECRET") or "").strip()


def _error(message: str, status_code: int):
    return jsonify({"status": "error", "message": message}), status_code


@internal_broker_token_bp.route("/broker-token", methods=["POST"])
@limiter.limit("20 per minute")
def broker_token():
    configured_secret = _configured_secret()
    if not configured_secret:
        return _error("not_found", 404)

    provided_secret = request.headers.get(SECRET_HEADER, "")
    if not provided_secret or not hmac.compare_digest(provided_secret, configured_secret):
        return _error("forbidden", 403)

    payload = request.get_json(silent=True) or {}
    try:
        result = import_broker_token(
            apikey=payload.get("apikey"),
            broker=payload.get("broker"),
            access_token=payload.get("access_token"),
        )
    except BrokerTokenImportError as exc:
        return _error(exc.message, exc.status_code)

    return jsonify({"status": "success", "data": result.to_dict()}), 200
```

- [ ] **Step 4: Register the blueprint and CSRF exemption in `app.py`**

Add the import near other blueprint imports:

```python
from blueprints.internal_broker_token import internal_broker_token_bp
```

Register near other non-REST blueprints:

```python
    app.register_blueprint(internal_broker_token_bp, url_prefix="/internal")
```

Add a CSRF exemption inside the existing `with app.app_context():` block that exempts webhooks and broker callbacks:

```python
        csrf.exempt(app.view_functions["internal_broker_token.broker_token"])
```

- [ ] **Step 5: Run endpoint tests**

Run:

```bash
uv run pytest test/test_internal_broker_token_api.py -q
```

Expected: endpoint and service tests pass.

- [ ] **Step 6: Commit**

```bash
git add app.py blueprints/internal_broker_token.py test/test_internal_broker_token_api.py
git commit -m "feat: add private broker token endpoint"
```

---

### Task 5: Refactor Zerodha Callback To Use Shared Formatter

**Files:**
- Modify: `blueprints/brlogin.py`
- Modify: `test/test_auth_resume.py`

- [ ] **Step 1: Write callback regression test**

Append this test to `test/test_auth_resume.py`:

```python
def test_zerodha_callback_formats_auth_token_with_broker_api_key(monkeypatch):
    import blueprints.brlogin as brlogin_module

    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.broker_auth_functions = {
        "zerodha_auth": lambda request_token: ("raw-access-token", None),
    }

    captured = {}

    def fake_handle_auth_success(auth_token, user_session_key, broker, feed_token=None, user_id=None):
        captured.update(
            {
                "auth_token": auth_token,
                "user_session_key": user_session_key,
                "broker": broker,
                "feed_token": feed_token,
                "user_id": user_id,
            }
        )
        return {"status": "ok"}, 200

    monkeypatch.setenv("BROKER_API_KEY", "kite-key")
    monkeypatch.setattr(brlogin_module, "BROKER_API_KEY", "stale-module-key", raising=False)
    monkeypatch.setattr(brlogin_module, "handle_auth_success", fake_handle_auth_success)

    with app.test_request_context("/zerodha/callback?request_token=request-token", method="GET"):
        session["user"] = "admin"
        response, status_code = brlogin_module.broker_callback("zerodha")

    assert status_code == 200
    assert response == {"status": "ok"}
    assert captured == {
        "auth_token": "kite-key:raw-access-token",
        "user_session_key": "admin",
        "broker": "zerodha",
        "feed_token": None,
        "user_id": None,
    }
```

- [ ] **Step 2: Run callback test**

Run:

```bash
uv run pytest test/test_auth_resume.py::test_zerodha_callback_formats_auth_token_with_broker_api_key -q
```

Expected: fail before the refactor because the current inline callback path reads the module-level `BROKER_API_KEY`; the refactor should make it read the current environment through `format_zerodha_auth_token()`.

- [ ] **Step 3: Refactor `blueprints/brlogin.py`**

Add this import:

```python
from broker.zerodha.api.auth_api import format_auth_token as format_zerodha_auth_token
```

Replace:

```python
        if broker == "zerodha":
            auth_token = f"{BROKER_API_KEY}:{auth_token}"
```

with:

```python
        if broker == "zerodha":
            auth_token = format_zerodha_auth_token(auth_token)
```

Remove the module-level `BROKER_API_KEY = get_broker_api_key()` only if no other code in `blueprints/brlogin.py` references it after the replacement. Verify with:

```bash
rg -n "BROKER_API_KEY" blueprints/brlogin.py
```

- [ ] **Step 4: Run callback and internal-token tests**

Run:

```bash
uv run pytest test/test_internal_broker_token_api.py test/test_auth_resume.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add blueprints/brlogin.py test/test_auth_resume.py
git commit -m "refactor: reuse zerodha auth token formatter"
```

---

### Task 6: Add No-Raw-Secret Logging Coverage

**Files:**
- Modify: `test/test_internal_broker_token_api.py`

- [ ] **Step 1: Add log-safety test**

Append:

```python
def test_import_broker_token_logs_no_raw_access_token_or_apikey(monkeypatch, caplog):
    monkeypatch.setattr(import_service, "verify_api_key", lambda apikey: "admin")
    monkeypatch.setattr(import_service, "format_auth_token", lambda token: "kite-key:super-secret-token")
    monkeypatch.setattr(import_service, "validate_access_token", lambda token: (True, None))
    monkeypatch.setattr(import_service, "get_auth_token", lambda user_id, bypass_cache=False: None)
    monkeypatch.setattr(import_service, "activate_broker_auth_token", lambda *args, **kwargs: 42)

    with caplog.at_level(logging.INFO):
        result = import_service.import_broker_token(
            "openalgo-api-key-secret",
            "zerodha",
            "super-secret-token",
        )

    assert result.updated is True
    logs = "\n".join(record.getMessage() for record in caplog.records)
    assert "super-secret-token" not in logs
    assert "openalgo-api-key-secret" not in logs
    assert "token_len=18" in logs
    assert "token_fp=" in logs
```

- [ ] **Step 2: Run log-safety test**

Run:

```bash
uv run pytest test/test_internal_broker_token_api.py::test_import_broker_token_logs_no_raw_access_token_or_apikey -q
```

Expected: pass.

- [ ] **Step 3: Commit**

```bash
git add test/test_internal_broker_token_api.py
git commit -m "test: cover private broker token log redaction"
```

---

### Task 7: Focused FD And Security Audit

**Files:**
- Inspect: `blueprints/internal_broker_token.py`
- Inspect: `services/broker_token_import_service.py`
- Inspect: `broker/zerodha/api/auth_api.py`
- Inspect: `utils/auth_utils.py`

- [ ] **Step 1: Run static FD scan**

Run:

```bash
rg -n "open\\(|socket\\.|subprocess|Popen|PIPE|Thread\\(|get_httpx_client|httpx\\.Client|create_engine|StaticPool|scoped_session|zmq|ZeroMQ" blueprints/internal_broker_token.py services/broker_token_import_service.py broker/zerodha/api/auth_api.py utils/auth_utils.py
```

Expected:
- `broker/zerodha/api/auth_api.py` uses only `get_httpx_client()`, not a new `httpx.Client`.
- `utils/auth_utils.py` uses `Thread(..., daemon=True)` for the existing master-contract async path.
- No new `open()`, raw sockets, subprocess pipes, `create_engine`, `StaticPool`, `scoped_session`, or ZeroMQ sockets appear in the new route/service.

- [ ] **Step 2: Verify no raw secret logging**

Run:

```bash
rg -n "access_token|apikey|OPENALGO_TOKEN_SERVICE_SECRET|BROKER_API_SECRET|BROKER_API_KEY" blueprints/internal_broker_token.py services/broker_token_import_service.py broker/zerodha/api/auth_api.py
```

Expected:
- Route and service do not log raw `access_token`, `apikey`, `OPENALGO_TOKEN_SERVICE_SECRET`, or `BROKER_API_SECRET`.
- Service logging includes only broker, user id, token length, token fingerprint, and updated state.
- `BROKER_API_KEY` appears only where it is read for formatting the Kite auth token or in tests.

- [ ] **Step 3: If the scan finds a leak, stop before final validation**

If a new FD is created outside the shared `get_httpx_client()` or daemon master-contract thread pattern, pause and report:

```text
FD audit found an unreleased descriptor in <file>:<line>. In a single-worker Gunicorn/eventlet OpenAlgo process this can accumulate until the process hits "too many open files", drops DB/socket work, or requires restart. The implementation needs a scoped cleanup fix before completion.
```

Then fix the specific leak before continuing.

- [ ] **Step 4: Commit audit-driven fixes if any were needed**

If the audit required code changes:

```bash
git add blueprints/internal_broker_token.py services/broker_token_import_service.py broker/zerodha/api/auth_api.py utils/auth_utils.py test/test_internal_broker_token_api.py
git commit -m "fix: close private token import resources"
```

If no code changes were needed, do not create an empty commit.

---

### Task 8: Final Verification

**Files:**
- Verify all changed files

- [ ] **Step 1: Run required tests**

Run:

```bash
uv run pytest test/test_internal_broker_token_api.py test/test_auth_resume.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run focused Ruff**

Run:

```bash
uv run ruff check blueprints/internal_broker_token.py services/broker_token_import_service.py broker/zerodha/api/auth_api.py utils/auth_utils.py blueprints/brlogin.py test/test_internal_broker_token_api.py test/test_auth_resume.py
```

Expected: no lint errors.

- [ ] **Step 3: Run whitespace check**

Run:

```bash
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 4: Review exact diff**

Run:

```bash
git diff --stat main...HEAD
git diff main...HEAD -- blueprints/internal_broker_token.py services/broker_token_import_service.py broker/zerodha/api/auth_api.py utils/auth_utils.py blueprints/brlogin.py app.py test/test_internal_broker_token_api.py test/test_auth_resume.py
```

Expected:
- No frontend files.
- No `/api/v1` changes.
- No KhazanaOS files.
- No raw token, API key, broker secret, or shared secret in logs.
- Private import path stores exactly `BROKER_API_KEY:access_token`.

- [ ] **Step 5: Final commit if remaining changes are unstaged**

If Task 8 produced code/test edits:

```bash
git add blueprints/internal_broker_token.py services/broker_token_import_service.py broker/zerodha/api/auth_api.py utils/auth_utils.py blueprints/brlogin.py app.py test/test_internal_broker_token_api.py test/test_auth_resume.py
git commit -m "feat: import zerodha broker tokens privately"
```

If all changes were already committed task-by-task, skip this commit.

## Self-Review

Spec coverage:
- Disabled-by-default behavior: Task 4 covers `404` when `OPENALGO_TOKEN_SERVICE_SECRET` is absent.
- Shared-secret header: Task 4 uses `X-OpenAlgo-Token-Service-Secret` and `hmac.compare_digest()`.
- API-key verification: Task 3 uses `database.auth_db.verify_api_key()` and returns `403` for invalid keys.
- Zerodha-only support: Task 3 rejects every broker except `zerodha`.
- Raw Kite token validation: Task 1 and Task 3 validate via Kite `/user/profile`.
- Existing token unchanged: Task 3 returns `updated:false` and skips activation.
- Same persistence side effects as browser login: Task 2 factors `activate_broker_auth_token()` and Task 3 calls it only when the token changes.
- Browser callback still formats token correctly: Task 5 adds callback coverage and uses the shared formatter.
- Logging safety: Task 6 verifies raw access token and OpenAlgo API key are absent from log records.
- FD hygiene: Task 7 audits the new route/service and touched auth paths.

Consistency checks:
- Route endpoint name is `internal_broker_token.broker_token`; use that exact name in the CSRF exemption.
- Service result field names are `broker`, `user_id`, and `updated`; route returns `result.to_dict()`.
- Browser `handle_auth_success()` still handles sessions, active-session tracking, SocketIO active-session updates, login attempt logging, and AJAX-vs-redirect responses.
- Private `import_broker_token()` does not create `session["logged_in"]`, `session["broker"]`, active sessions, or SocketIO active-session updates.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-15-openalgo-private-broker-token-api.md`. Two execution options:

**1. Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.
