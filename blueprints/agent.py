# blueprints/agent.py
"""HTTP surface for the /agent module: the LLM agent's setup, chat and streams.

Everything here is session-authenticated and CSRF-protected. There is no
webhook and no unauthenticated entry point, which is deliberate: this blueprint
can reach a model provider with the operator's key and, once trading is
enabled, the broker.

Five rules the routes hold to, each of them load-bearing rather than stylistic:

* **409, never a silent stream, while nothing is configured.** Every chat route
  checks the setup gate before it opens a response. The React gate is a
  convenience; this is the enforcement.
* **404, never 403, for a conversation that is not yours.** A 403 confirms the
  row exists and lets the id space be walked. Every ``<int:conversation_id>``
  route resolves through the owner-scoped store read first.
* **A secret is never returned, not even masked.** The model list carries a
  presence boolean and a fingerprint. The key input starts empty even when a
  key is stored, and a blank ``api_key`` on a PATCH means "keep the existing
  one" rather than "clear it".
* **A traceback must not carry a key.** Every function a decrypted credential
  passes through logs with ``logger.error`` and no traceback; every other
  handler here uses ``logger.exception`` as CLAUDE.md requires. The vector is
  the exception's own message rather than the frame locals: a stdlib traceback
  never prints a local, but it does print ``str(exc)``, and a provider that
  quotes the key it rejected puts it there unlabelled, where
  ``utils.logging``'s redaction patterns -- which all key off a ``token=`` or
  ``secret:`` style label -- do not match it.
* **Nothing is read from the environment.** Provider, model, credential and
  policy all come from the database through ``services/agent/settings.py``. The
  rate-limit budgets below are module constants for the same reason.

The streaming routes hand off to ``services/agent/stream.py``, which owns the
eventlet crossing: the agent runs on a real OS thread and this greenlet only
drains a real queue. Nothing in this file may block on that thread.
"""

from __future__ import annotations

import ipaddress
import json
import time
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

from flask import Blueprint, Response, jsonify, request, session, stream_with_context

from database import agent_db
from database.auth_db import get_api_key_for_tradingview
from database.settings_db import get_analyze_mode
from limiter import limiter
from services.agent import builder, catalog, providers
from services.agent import settings as agent_settings
from services.agent import stream as agent_stream
from services.agent.frames import SSE_HEADERS
from services.agent.safety import audit
from services.agent.tools import ToolContext
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

agent_bp = Blueprint("agent_bp", __name__, url_prefix="/agent")

# Budgets are constants, not environment variables. This module takes no
# configuration from `.env` at all, and a rate limit read from there would be
# the one exception that makes the rule untrue.
#
# One shared scope across the ordinary routes, so a client cannot draw a fresh
# budget per endpoint by alternating between them.
AGENT_RATE_LIMIT = "240 per minute"

# Tighter, and on their own scopes: a stream holds a connection and bills a
# provider per token, and a credential test makes a real upstream call. Neither
# should be reachable at the browsing rate of a settings page.
AGENT_STREAM_RATE_LIMIT = "30 per minute"
AGENT_TEST_RATE_LIMIT = "12 per minute"

_api_limit = limiter.shared_limit(AGENT_RATE_LIMIT, scope="agent_api")
_stream_limit = limiter.shared_limit(AGENT_STREAM_RATE_LIMIT, scope="agent_stream")
_test_limit = limiter.shared_limit(AGENT_TEST_RATE_LIMIT, scope="agent_test")

#: The longest prompt one turn may carry. A model's own context window is the
#: real limit; this only stops a single request pinning memory before the run
#: starts.
MAX_MESSAGE_CHARS = 32000

#: Seconds a credential test waits on the provider. Long enough for a cold
#: local Ollama to load a model, short enough that an unreachable endpoint is
#: reported rather than left hanging.
TEST_TIMEOUT_SECONDS = 30

#: How much of a provider's failure message is stored and returned. The message
#: is kept verbatim because "invalid API key" and "model not found" need
#: different fixes; the cap only stops a stack-shaped error filling the column.
MAX_TEST_ERROR_CHARS = 2000

NOT_FOUND = "Conversation not found"

#: Refused outright as a base URL host. The cloud metadata address is the one
#: destination an operator never means to type, and reaching it from this
#: process would hand the instance's own credentials to whatever is on the
#: other end of the "provider". A private or loopback host is deliberately
#: allowed: a local Ollama is the point of that provider kind.
BLOCKED_BASE_URL_HOSTS = frozenset(
    {
        "169.254.169.254",
        "fd00:ec2::254",
        "metadata.google.internal",
        "metadata",
    }
)

#: What a POST or PATCH may set on a model row, beyond the identity fields the
#: store owns. An allowlist rather than a denylist: `is_default`, `last_test_ok`
#: and the rest each have their own transaction in the store, and a
#: mass-assignment here would be a way to reach them.
MODEL_FLAG_FIELDS = (
    "enabled",
    "supports_reasoning",
    "supports_vision",
    "tools_unreliable",
)

#: Where a submitted key is stored. `provider` is the default and is what lets
#: one pasted OpenAI key serve every GPT model the operator adds; `model` writes
#: a per-model override, which covers two accounts with the same provider.
SECRET_SCOPES = ("provider", "model")


@agent_bp.errorhandler(429)
def _rate_limited(error):
    """Answer an over-limit caller with JSON rather than the app-wide redirect.

    ``app.py``'s handler returns JSON only for paths under ``/api/`` and
    redirects everything else to the React rate-limited page. These routes live
    under ``/agent/api/``, so without this a throttled ``fetch`` would receive
    200 and an HTML document and the client would parse a page as a payload.
    """
    retry_after = 60
    breached = getattr(error, "limit", None)
    try:
        retry_after = int(breached.limit.get_expiry())
    except (AttributeError, TypeError, ValueError):
        pass

    response = jsonify(
        {
            "status": "error",
            "message": "Rate limit exceeded. Please slow down your requests.",
            "retry_after": retry_after,
        }
    )
    response.status_code = 429
    response.headers["Retry-After"] = str(retry_after)
    return response


# ---------------------------------------------------------------------------
# Envelope and request helpers
# ---------------------------------------------------------------------------


def _current_user() -> str | None:
    """The session username, the way every other session blueprint reads it."""
    return session.get("user")


def _ok(payload: dict | None = None, code: int = 200):
    """A success envelope, matching the other session blueprints."""
    body: dict[str, Any] = {"status": "success"}
    if payload:
        body.update(payload)
    return jsonify(body), code


def _error(message: str, code: int, payload: dict | None = None):
    """An error envelope, matching the other session blueprints."""
    body: dict[str, Any] = {"status": "error", "message": message}
    if payload:
        body.update(payload)
    return jsonify(body), code


def _json_body():
    """The request body as a dict, or ``(None, error_response)``."""
    payload = request.get_json(silent=True)
    if payload is None:
        return None, _error("A JSON body is required", 400)
    if not isinstance(payload, dict):
        return None, _error("The request body must be a JSON object", 400)
    return payload, None


def _build_error(exc: builder.AgentBuildError):
    """Render a typed build failure with the status and kind it carries."""
    return _error(exc.message, exc.status, {"kind": exc.kind})


def _openalgo_api_key(username: str) -> str | None:
    """The OpenAlgo API key the agent's tools call the service layer with.

    Not the provider key. This is the platform's own key, which the internal
    service layer resolves the user, broker and auth token from, and without it
    no tool can read a quote or a position.

    Args:
        username: The session username.

    Returns:
        The decrypted key, or None when the operator has never generated one.
    """
    try:
        return get_api_key_for_tradingview(username)
    except Exception as exc:
        # logger.error and no traceback, for the same reason as test_model
        # below: the decrypted key passes through this frame, and str(exc) from
        # a decryption or storage failure can quote the material it choked on.
        # utils.logging redacts a labelled "key=..." but not a bare credential.
        logger.error("Could not read the OpenAlgo API key for %s: %s", username, type(exc).__name__)
        return None


def _resolve_conversation(conversation_id: int):
    """``(username, row, error_response)`` for an owner-scoped conversation route.

    A conversation belonging to somebody else is indistinguishable from one that
    does not exist: both answer 404. Returning 403 would confirm the id is real.
    """
    username = _current_user()
    if not username:
        return None, None, _error("Not authenticated", 401)
    row = agent_db.get_conversation(conversation_id, username)
    if row is None:
        return username, None, _error(NOT_FOUND, 404)
    return username, row, None


def _redact_secret(text: str, secret: str | None) -> str:
    """Remove a decrypted key from text that is about to be stored or returned.

    A provider is entitled to echo whatever it likes in an error, and some of
    them quote the credential they rejected. The message is otherwise kept
    verbatim, because replacing it with a generic failure is what makes an
    invalid key and an unknown model look like the same problem.

    Args:
        text: The message to clean.
        secret: The plaintext key used for the call, when there was one.

    Returns:
        The message with any occurrence of the key replaced.
    """
    if not secret or len(secret) < 8:
        return text
    return text.replace(secret, "[redacted]")


def _validate_base_url(raw: Any, provider_kind: str) -> tuple[str | None, str | None]:
    """Check an operator-supplied provider endpoint before it is saved.

    The server makes requests to this address, so it is an SSRF surface even in
    a single-user product: the goal is preventing an accident, not defending
    against the operator, who already has server access.

    Implemented, and only this: the scheme must be ``http`` or ``https``;
    credentials embedded in the URL are refused; the cloud metadata addresses
    are refused; an unparseable URL is refused rather than passed through. A
    private or loopback host is **allowed**, because a local Ollama is the
    entire point of that provider kind.

    Not implemented: the host is not resolved, so a hostname that resolves to a
    metadata address is not caught here. Resolving would put a DNS lookup in the
    save path and would refuse a container hostname that is simply not up yet.

    Args:
        raw: The submitted value, possibly absent or blank.
        provider_kind: The provider kind, which decides whether one is required.

    Returns:
        ``(normalized_url, error)``. The URL is None when none was given and the
        provider does not need one; exactly one of the two is not None
        otherwise.
    """
    url = providers.normalize_base_url(raw if isinstance(raw, str) else None)
    if not url:
        try:
            if providers.requires_base_url(provider_kind):
                spec = providers.provider_spec(provider_kind)
                return None, f"{spec.label} requires a base URL"
        except ValueError as exc:
            return None, str(exc)
        return None, None

    try:
        parts = urlsplit(url)
    except ValueError:
        # Fail closed. An address that cannot be parsed is not a safe address.
        return None, "The base URL could not be parsed"

    if parts.scheme not in ("http", "https"):
        return None, "The base URL must start with http:// or https://"
    if "@" in parts.netloc:
        return None, "The base URL must not carry a username or password"

    try:
        host = parts.hostname
    except ValueError:
        return None, "The base URL could not be parsed"
    if not host:
        return None, "The base URL must name a host"

    host = host.strip().strip("[]").lower().rstrip(".")
    if host in BLOCKED_BASE_URL_HOSTS:
        return None, "That address is the cloud metadata endpoint and cannot be used"

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and str(address) in BLOCKED_BASE_URL_HOSTS:
        return None, "That address is the cloud metadata endpoint and cannot be used"

    return url, None


def _secret_scope(body: dict) -> tuple[str, str | None]:
    """Read where a submitted key should be stored.

    Args:
        body: The request body.

    Returns:
        ``(scope, error)``, where scope is ``provider`` or ``model``.
    """
    scope = str(body.get("api_key_scope") or "provider").strip().lower()
    if scope not in SECRET_SCOPES:
        return "provider", f"api_key_scope must be one of: {', '.join(SECRET_SCOPES)}"
    return scope, None


def _model_or_404(model_id: int):
    """``(row, error_response)`` for a route addressing one configured model."""
    row = agent_db.get_model(model_id)
    if row is None:
        return None, _error("Model not found", 404)
    return row, None


# ---------------------------------------------------------------------------
# Status and catalog
# ---------------------------------------------------------------------------


@agent_bp.route("/api/status", methods=["GET"])
@check_session_validity
@_api_limit
def agent_status():
    """The setup gate: whether ``/agent`` has a usable model yet.

    ``configured`` is true only for an enabled default model whose credential
    test passed, which is the same condition every chat route enforces.
    """
    username = _current_user()
    if not username:
        return _error("Not authenticated", 401)

    default_row = agent_db.get_default_model()
    try:
        trading_enabled = bool(agent_settings.is_trading_enabled(fresh=True))
    except Exception:
        logger.exception("Could not read the agent trading setting")
        trading_enabled = False

    return _ok(
        {
            "configured": agent_db.is_configured(),
            "model_count": len(agent_db.list_models(enabled_only=True)),
            "default_model_id": default_row.id if default_row is not None else None,
            "trading_enabled": trading_enabled,
            # Two facts the setup screen needs to explain why chat is refused
            # even after a model has been added.
            "agent_available": _agno_available(),
            "has_openalgo_api_key": bool(_openalgo_api_key(username)),
        }
    )


def _agno_available() -> bool:
    """Whether the optional agno dependency is installed.

    Reported rather than assumed: the catalogue, the model registry and the
    settings all work without it, and an operator who can see the setup screen
    but not run a turn deserves to be told which of the two is missing.
    """
    try:
        import agno  # noqa: F401
    except Exception:
        return False
    return True


@agent_bp.route("/api/catalog/providers", methods=["GET"])
@check_session_validity
@_api_limit
def catalog_providers():
    """Every chat-capable provider LiteLLM knows about.

    Read from LiteLLM's own in-package data at request time, so bumping the
    package is the entire maintenance story: no catalog table, no generated
    frontend constant, no network call.
    """
    return _ok(
        {
            "available": catalog.is_available(),
            "data": [info.as_dict() for info in catalog.list_providers()],
        }
    )


@agent_bp.route("/api/catalog/models", methods=["GET"])
@check_session_validity
@_api_limit
def catalog_models():
    """One provider's models, enriched with context window, price and tool support.

    ``supports_function_calling`` is load-bearing rather than decoration: this
    agent is entirely tool-driven, so a model without it cannot drive it.
    """
    provider = (request.args.get("provider") or "").strip()
    if not provider:
        return _error("A provider is required", 400)

    chat_only = (request.args.get("chat_only") or "true").strip().lower() != "false"
    info = catalog.get_provider(provider)
    models = catalog.list_models(provider, chat_only=chat_only)
    return _ok(
        {
            "available": catalog.is_available(),
            "provider": info.as_dict() if info is not None else None,
            "data": [model.as_dict() for model in models],
        }
    )


# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------


@agent_bp.route("/api/models", methods=["GET"])
@check_session_validity
@_api_limit
def list_models():
    """Every configured model, with its key described and never shown.

    Each row carries ``has_api_key``, ``api_key_fingerprint`` and
    ``api_key_source`` plus its last test result. No endpoint in this module
    returns a key value, masked or otherwise.
    """
    return _ok({"data": agent_db.list_models()})


@agent_bp.route("/api/models", methods=["POST"])
@check_session_validity
@_api_limit
def create_model():
    """Register a model, optionally storing the key it will use.

    The key defaults to the shared ``provider:{kind}`` secret, which is what
    lets an operator paste one OpenAI key and tick five GPT models. It is
    written **before** the row when it is a provider key, so a failed row
    creation cannot leave a model configured with no credential; a per-model
    override needs the row's id and is therefore written after it.

    A new model is never the default. The store promotes it on its first
    passing test, or the operator does it explicitly.
    """
    body, error = _json_body()
    if error:
        return error

    provider_kind = str(body.get("provider_kind") or "").strip()
    if provider_kind not in agent_db.PROVIDER_KINDS:
        return _error(
            f"provider_kind must be one of: {', '.join(agent_db.PROVIDER_KINDS)}",
            400,
        )

    model_name = str(body.get("model_name") or "").strip()
    if not model_name:
        return _error("A model name is required", 400)
    display_name = str(body.get("display_name") or "").strip() or model_name

    base_url, url_error = _validate_base_url(body.get("base_url"), provider_kind)
    if url_error:
        return _error(url_error, 400)

    effort = str(body.get("default_reasoning_effort") or "off").strip().lower()
    if effort not in agent_db.REASONING_EFFORTS:
        return _error(
            f"default_reasoning_effort must be one of: {', '.join(agent_db.REASONING_EFFORTS)}",
            400,
        )

    scope, scope_error = _secret_scope(body)
    if scope_error:
        return _error(scope_error, 400)
    api_key = str(body.get("api_key") or "").strip()

    if api_key and scope == "provider":
        stored, message = agent_db.set_secret(agent_db.provider_secret_name(provider_kind), api_key)
        if not stored:
            return _error(message or "Could not store the API key", 500)

    config = {
        "provider_kind": provider_kind,
        "model_name": model_name,
        "display_name": display_name,
        "base_url": base_url,
        "default_reasoning_effort": effort,
    }
    for field in MODEL_FLAG_FIELDS:
        if field in body:
            config[field] = bool(body[field])

    created, message = agent_db.create_model(config)
    if created is None:
        code = 409 if message and "already registered" in message else 400
        return _error(message or "Could not register the model", code)

    if api_key and scope == "model":
        stored, secret_message = agent_db.set_secret(
            agent_db.model_secret_name(created["id"]), api_key
        )
        if not stored:
            # The row stands. Saying so is better than deleting a model the
            # operator asked for: the key can be set with a PATCH, and without
            # this message they would discover the gap at test time.
            return _error(
                f"{display_name} was registered but its API key could not be stored: "
                f"{secret_message or 'unknown error'}",
                500,
                {"data": created},
            )

    logger.info("Agent model registered: %s (%s)", display_name, provider_kind)
    return _ok({"data": agent_db.provider_model_to_dict(agent_db.get_model(created["id"]))}, 201)


@agent_bp.route("/api/models/<int:model_id>", methods=["PATCH"])
@check_session_validity
@_api_limit
def update_model(model_id: int):
    """Update a registered model, and replace its key only when one is supplied.

    A blank ``api_key`` means "keep the existing one", matching the SMTP
    precedent in ``blueprints/auth.py``: the input starts empty even when a key
    is configured, so a save that treated blank as "clear it" would silently
    unconfigure the provider on every unrelated edit.
    """
    row, error = _model_or_404(model_id)
    if error:
        return error

    body, error = _json_body()
    if error:
        return error

    changes: dict[str, Any] = {}
    if "display_name" in body:
        changes["display_name"] = str(body.get("display_name") or "").strip()
    if "base_url" in body:
        base_url, url_error = _validate_base_url(body.get("base_url"), row.provider_kind)
        if url_error:
            return _error(url_error, 400)
        changes["base_url"] = base_url
    if "default_reasoning_effort" in body:
        effort = str(body.get("default_reasoning_effort") or "").strip().lower()
        if effort not in agent_db.REASONING_EFFORTS:
            return _error(
                f"default_reasoning_effort must be one of: {', '.join(agent_db.REASONING_EFFORTS)}",
                400,
            )
        changes["default_reasoning_effort"] = effort
    for field in MODEL_FLAG_FIELDS:
        if field in body:
            changes[field] = bool(body[field])

    # Forwarded rather than dropped so the store's own refusal reaches the
    # operator. Silently ignoring them would answer 200 to a request that
    # changed nothing, which reads as success.
    for guarded in ("is_default", "provider_kind", "model_name"):
        if guarded in body:
            changes[guarded] = body[guarded]

    scope, scope_error = _secret_scope(body)
    if scope_error:
        return _error(scope_error, 400)
    api_key = str(body.get("api_key") or "").strip()

    if not changes and not api_key:
        return _error("Nothing to update", 400)

    if changes:
        updated, message = agent_db.update_model(model_id, changes)
        if updated is None:
            code = 409 if message and "already registered" in message else 400
            return _error(message or "Could not update the model", code)

    if api_key:
        name = (
            agent_db.model_secret_name(model_id)
            if scope == "model"
            else agent_db.provider_secret_name(row.provider_kind)
        )
        stored, message = agent_db.set_secret(name, api_key)
        if not stored:
            return _error(message or "Could not store the API key", 500)

    return _ok({"data": agent_db.provider_model_to_dict(agent_db.get_model(model_id))})


@agent_bp.route("/api/models/<int:model_id>", methods=["DELETE"])
@check_session_validity
@_api_limit
def delete_model(model_id: int):
    """Remove a model, its per-model key override and its default status.

    The store hands the default to another tested, enabled model in the same
    transaction when the deleted one held it.
    """
    removed, message = agent_db.delete_model(model_id)
    if not removed:
        code = 404 if message == "Model not found" else 500
        return _error(message or "Could not delete the model", code)
    logger.info("Agent model %s deleted", model_id)
    return _ok({"message": "Model deleted"})


@agent_bp.route("/api/models/<int:model_id>/test", methods=["POST"])
@check_session_validity
@_test_limit
def test_model(model_id: int):
    """Validate a model's credentials with the cheapest possible real call.

    A completion capped at one token, with retries off. Anything less is not a
    test: only a real request tells an operator whether the key is accepted, the
    model name exists and the endpoint answers.

    On success the result is recorded and the stored error cleared. On failure
    the provider's own message is stored **verbatim**, because "invalid API key"
    and "model not found" need different fixes and a generic failure message
    helps nobody. The only thing removed from it is the key itself, in case the
    provider quoted the credential it rejected.

    **This function's locals hold a decrypted API key**, so its failure paths log
    with ``logger.error`` and ``str(exc)`` rather than ``logger.exception``:
    ``exc_info`` captures local variables, and a traceback raised from this frame
    would write the operator's provider key into ``log/errors.jsonl`` in
    plaintext.

    Returns:
        ``{ok, message, latency_ms}`` alongside the refreshed model row.
    """
    row, error = _model_or_404(model_id)
    if error:
        return error

    provider_kind = row.provider_kind
    api_key, secret_name = agent_db.resolve_api_key(model_id, provider_kind)

    config_error = providers.validate_provider_config(
        provider_kind, row.model_name, row.base_url, has_key=bool(api_key)
    )
    if config_error:
        agent_db.record_model_test(model_id, False, config_error)
        return _ok(
            {
                "ok": False,
                "message": config_error,
                "latency_ms": 0,
                "data": agent_db.provider_model_to_dict(agent_db.get_model(model_id)),
            }
        )

    try:
        call_kwargs = providers.litellm_kwargs(row, api_key)
    except ValueError as exc:
        message = str(exc)
        agent_db.record_model_test(model_id, False, message)
        return _ok({"ok": False, "message": message, "latency_ms": 0})

    started = time.perf_counter()
    try:
        # Imported here rather than at module scope: importing litellm costs
        # seconds of process start-up, and every other route in this blueprint
        # works without it.
        import litellm

        litellm.completion(
            model=call_kwargs["id"],
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
            timeout=TEST_TIMEOUT_SECONDS,
            num_retries=0,
            api_key=call_kwargs.get("api_key"),
            api_base=call_kwargs.get("api_base"),
        )
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        message = _redact_secret(str(exc), api_key)[:MAX_TEST_ERROR_CHARS]
        # logger.error, not logger.exception: this frame's locals hold the
        # decrypted provider key and exc_info would write it to errors.jsonl.
        logger.error(
            "Agent model %s failed its credential test: %s",
            row.display_name,
            message,
        )
        agent_db.record_model_test(model_id, False, message)
        return _ok(
            {
                "ok": False,
                "message": message,
                "latency_ms": latency_ms,
                "data": agent_db.provider_model_to_dict(agent_db.get_model(model_id)),
            }
        )
    finally:
        # The plaintext lives no longer than the call it was needed for.
        api_key = None
        call_kwargs = None

    latency_ms = int((time.perf_counter() - started) * 1000)
    agent_db.record_model_test(model_id, True, None)
    if secret_name:
        agent_db.mark_secret_used(secret_name)
    logger.info("Agent model %s passed its credential test in %sms", row.display_name, latency_ms)

    return _ok(
        {
            "ok": True,
            "message": "The provider accepted the request",
            "latency_ms": latency_ms,
            "data": agent_db.provider_model_to_dict(agent_db.get_model(model_id)),
        }
    )


@agent_bp.route("/api/models/<int:model_id>/default", methods=["POST"])
@check_session_validity
@_api_limit
def set_default_model(model_id: int):
    """Make one model the default.

    Refused for an untested model. A model may be saved untested; it may not be
    the thing an unqualified request resolves to, because a failure there
    surfaces mid-stream instead of at setup.
    """
    ok, message = agent_db.set_default_model(model_id)
    if not ok:
        code = 404 if message == "Model not found" else 409
        return _error(message or "Could not set the default model", code)
    return _ok({"data": agent_db.provider_model_to_dict(agent_db.get_model(model_id))})


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def _json_safe_settings(values: dict[str, Any]) -> dict[str, Any]:
    """Render typed setting values the way ``settings.get_all`` renders them.

    The defaults come back in their parsed form, which carries a ``frozenset``
    for every list-valued limit and a ``Decimal`` for every money and percentage
    one. Neither is JSON serialisable, and the two halves of the settings
    response have to agree on a shape or the screen compares a list against a
    set and shows every field as changed.

    Args:
        values: The typed values, as ``settings.get_setting_defaults`` returns
            them.

    Returns:
        The same mapping with sets sorted into lists and decimals as strings.
    """
    payload: dict[str, Any] = {}
    for key, value in values.items():
        if isinstance(value, frozenset | set):
            payload[key] = sorted(value)
        elif isinstance(value, Decimal):
            payload[key] = str(value)
        else:
            payload[key] = value
    return payload


@agent_bp.route("/api/settings", methods=["GET"])
@check_session_validity
@_api_limit
def get_settings():
    """Every agent setting, with the shipped defaults alongside.

    The defaults travel with the payload so the settings screen can show what a
    field reverts to without a second endpoint or a duplicated table.
    """
    try:
        return _ok(
            {
                "data": agent_settings.get_all(fresh=True),
                "defaults": _json_safe_settings(agent_settings.get_setting_defaults()),
            }
        )
    except Exception:
        logger.exception("Could not read the agent settings")
        return _error("Could not read the agent settings", 500)


@agent_bp.route("/api/settings", methods=["PUT"])
@check_session_validity
@_api_limit
def put_settings():
    """Persist a partial settings update.

    Every value is parsed and validated before anything is written, so a request
    carrying one bad field changes nothing at all. An unknown key is rejected
    rather than ignored: a typo that silently does nothing is indistinguishable
    from a limit that was never applied.
    """
    body, error = _json_body()
    if error:
        return error
    if not body:
        return _error("Nothing to update", 400)

    try:
        return _ok({"data": agent_settings.update(body)})
    except ValueError as exc:
        return _error(str(exc), 400)
    except Exception:
        logger.exception("Could not write the agent settings")
        return _error("Could not save the agent settings", 500)


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------


@agent_bp.route("/api/conversations", methods=["GET"])
@check_session_validity
@_api_limit
def list_conversations():
    """The signed-in user's conversations, most recently updated first."""
    username = _current_user()
    if not username:
        return _error("Not authenticated", 401)

    surface = (request.args.get("surface") or "").strip() or None
    if surface and surface not in agent_db.SURFACES:
        return _error(f"surface must be one of: {', '.join(agent_db.SURFACES)}", 400)

    try:
        limit = min(max(int(request.args.get("limit", 100)), 1), 200)
    except (TypeError, ValueError):
        return _error("limit must be a whole number", 400)

    return _ok({"data": agent_db.list_conversations(username, surface=surface, limit=limit)})


@agent_bp.route("/api/conversations", methods=["POST"])
@check_session_validity
@_api_limit
def create_conversation():
    """Open a conversation on one surface.

    Optional: ``/chat/stream`` creates one when the request names none, so the
    first message of a new conversation is a single round trip.
    """
    username = _current_user()
    if not username:
        return _error("Not authenticated", 401)

    body, error = _json_body()
    if error:
        return error

    surface = str(body.get("surface") or "chat").strip().lower()
    if surface not in agent_db.SURFACES:
        return _error(f"surface must be one of: {', '.join(agent_db.SURFACES)}", 400)
    title = str(body.get("title") or "").strip()[:300] or None

    created, message = agent_db.create_conversation(username, title=title, surface=surface)
    if created is None:
        return _error(message or "Could not create the conversation", 500)
    return _ok({"data": created}, 201)


@agent_bp.route("/api/conversations/<int:conversation_id>", methods=["GET"])
@check_session_validity
@_api_limit
def get_conversation(conversation_id: int):
    """One conversation and its messages, oldest first."""
    _username, row, error = _resolve_conversation(conversation_id)
    if error:
        return error

    return _ok(
        {
            "data": agent_db.conversation_to_dict(row),
            "messages": agent_db.list_messages(conversation_id),
        }
    )


@agent_bp.route("/api/conversations/<int:conversation_id>", methods=["DELETE"])
@check_session_validity
@_api_limit
def delete_conversation(conversation_id: int):
    """Delete a conversation and its messages.

    Its audit rows stay. They are a trade record and they outlive the
    conversation the trade was typed into.
    """
    username, _row, error = _resolve_conversation(conversation_id)
    if error:
        return error

    removed, message = agent_db.delete_conversation(conversation_id, username)
    if not removed:
        code = 404 if message == NOT_FOUND else 500
        return _error(message or "Could not delete the conversation", code)
    return _ok({"message": "Conversation deleted"})


# ---------------------------------------------------------------------------
# The turn recorder
#
# `stream.py` yields SSE text, which is what the client needs and what the route
# must not reshape. The recorder reads a copy of each frame on its way past so
# the finished turn can be persisted: without it a reloaded conversation would
# show the questions and none of the answers.
# ---------------------------------------------------------------------------


class _TurnRecorder:
    """Accumulates one turn's frames so it can be written to ``ag_message``.

    Attributes:
        text: The assistant's prose, concatenated from ``token`` deltas.
        tools: One entry per tool call, keyed by call id while it is open.
        notices: The turn's non-prose frames, each keeping its own ``type``
            discriminator: ``notice``, ``usage``, ``error``, ``confirm`` and the
            accumulated ``ui`` markup. The column is free-form JSON, and one
            ordered list of what happened beside the answer is what the client
            re-renders from.
        run_id: Agno's run id, learned from the ``start`` frame.
        session_id: Agno's session id, learned from the same frame. Bound back
            onto the conversation so a paused confirmation can be resumed.
        paused: True when the run ended on a ``confirm`` frame, which
            deliberately carries no ``done`` after it.
    """

    __slots__ = (
        "_open",
        "_ui",
        "_usage",
        "notices",
        "paused",
        "run_id",
        "session_id",
        "text",
        "tools",
    )

    def __init__(self) -> None:
        self.text: list[str] = []
        self.tools: list[dict[str, Any]] = []
        self.notices: list[dict[str, Any]] = []
        self.run_id: str = ""
        self.session_id: str = ""
        self.paused: bool = False
        self._open: dict[str, dict[str, Any]] = {}
        self._ui: list[str] = []
        self._usage: dict[str, Any] | None = None

    def observe(self, payload: dict[str, Any]) -> None:
        """Fold one decoded frame into the turn.

        Args:
            payload: The frame as it went out on the wire, already decoded.
        """
        kind = payload.get("type")
        if kind == "token":
            self.text.append(str(payload.get("delta") or ""))
        elif kind == "ui":
            self._ui.append(str(payload.get("delta") or ""))
        elif kind == "start":
            self.run_id = str(payload.get("run_id") or "")
            self.session_id = str(payload.get("session_id") or "")
        elif kind == "tool_start":
            entry = {
                "id": payload.get("id"),
                "name": payload.get("name"),
                "args": payload.get("args"),
            }
            self.tools.append(entry)
            self._open[str(payload.get("id"))] = entry
        elif kind == "tool_end":
            entry = self._open.pop(str(payload.get("id")), None)
            if entry is None:
                entry = {"id": payload.get("id"), "name": payload.get("name")}
                self.tools.append(entry)
            entry["ok"] = payload.get("ok")
            entry["result"] = payload.get("result")
            entry["duration"] = payload.get("duration")
        elif kind == "usage":
            # Every usage frame carries the running total for the turn, so the
            # last one is the only one worth keeping.
            self._usage = payload
        elif kind in ("notice", "error"):
            self.notices.append(payload)
        elif kind == "confirm":
            self.paused = True
            self.notices.append(payload)

    def content(self) -> str:
        """The assistant's prose for this turn."""
        return "".join(self.text)

    def sidecar(self) -> list[dict[str, Any]]:
        """Everything that belongs beside the prose, in the order it happened."""
        entries = list(self.notices)
        if self._ui:
            entries.append({"type": "ui", "content": "".join(self._ui)})
        if self._usage is not None:
            entries.append(self._usage)
        return entries

    def has_content(self) -> bool:
        """Whether the turn produced anything worth persisting."""
        return bool(self.text or self.tools or self.notices or self._ui or self._usage)


def _record_stream(chunks, recorder: _TurnRecorder, conversation_id: int, username: str):
    """Pass SSE text through untouched while recording what it carried.

    The persist happens in a ``finally``, so a client that hangs up mid-answer
    still leaves the partial turn in the conversation rather than losing it. The
    generator that produced the chunks cancels the run server-side on the same
    unwind.

    Args:
        chunks: The SSE text iterator from ``services/agent/stream.py``.
        recorder: The recorder to fold each frame into.
        conversation_id: The conversation being appended to.
        username: The owner, for the owner-scoped session binding.

    Yields:
        Each chunk exactly as it arrived.
    """
    try:
        for chunk in chunks:
            if chunk.startswith("data: "):
                try:
                    recorder.observe(json.loads(chunk[6:]))
                except (ValueError, TypeError):
                    # A frame the recorder cannot read still reaches the client.
                    # The transcript is worth less than the answer.
                    logger.exception("Could not record an agent frame")
            yield chunk
    finally:
        _persist_turn(recorder, conversation_id, username)


def _persist_turn(recorder: _TurnRecorder, conversation_id: int, username: str) -> None:
    """Write the finished turn, and bind the conversation to its agno session.

    Never raises. A conversation that could not be written is a lost transcript;
    failing the response the operator already received would be worse.
    """
    try:
        if recorder.session_id:
            row = agent_db.get_conversation(conversation_id, username)
            if row is not None and row.agno_session_id != recorder.session_id:
                agent_db.update_conversation(
                    conversation_id, username, agno_session_id=recorder.session_id
                )
        if recorder.has_content():
            agent_db.add_message(
                conversation_id,
                "assistant",
                recorder.content(),
                tools=recorder.tools or None,
                notices=recorder.sidecar() or None,
            )
    except Exception:
        logger.exception("Could not persist the agent turn for conversation %s", conversation_id)


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


def _chat_preconditions():
    """``(username, api_key, error_response)`` shared by every chat route.

    The setup gate is enforced here rather than in the browser: a request that
    arrives with nothing configured is answered 409 before a response is opened,
    so a client that skipped the gate gets an error it can read instead of an
    empty stream.
    """
    username = _current_user()
    if not username:
        return None, None, _error("Not authenticated", 401)

    if not agent_db.is_configured():
        return (
            None,
            None,
            _error(
                "No model is configured for the agent. Add a model, test its "
                "credentials and set it as the default before chatting.",
                409,
                {"kind": "config", "configured": False},
            ),
        )

    api_key = _openalgo_api_key(username)
    if not api_key:
        return (
            None,
            None,
            _error(
                "This deployment has no OpenAlgo API key. Generate one at /apikey "
                "so the agent's tools can reach the platform.",
                409,
                {"kind": "config"},
            ),
        )

    return username, api_key, None


def _surface_of(body: dict) -> tuple[str, str | None]:
    """Read and validate the requested surface."""
    surface = str(body.get("surface") or "chat").strip().lower()
    if surface not in agent_db.SURFACES:
        return "chat", f"surface must be one of: {', '.join(agent_db.SURFACES)}"
    return surface, None


def _reasoning_effort_of(body: dict) -> tuple[str | None, str | None]:
    """Read and validate an optional per-run reasoning effort."""
    raw = body.get("reasoning_effort")
    if raw is None or raw == "":
        return None, None
    effort = str(raw).strip().lower()
    if effort not in agent_db.REASONING_EFFORTS:
        return None, (f"reasoning_effort must be one of: {', '.join(agent_db.REASONING_EFFORTS)}")
    return effort, None


def _runtime_lines(chart_context: Any) -> list[str]:
    """Render a chart panel's context as prompt bullets.

    Only scalars, only a handful, and each one short. The panel reads its
    context fresh at send time and this is what reaches the model, so an
    oversized payload here would be an operator-supplied prompt of unbounded
    length.

    Args:
        chart_context: Whatever the client sent, which may be anything.

    Returns:
        At most ten ``key: value`` lines.
    """
    if not isinstance(chart_context, dict):
        return []
    lines: list[str] = []
    for key in sorted(chart_context):
        value = chart_context[key]
        if not isinstance(value, str | int | float | bool):
            continue
        lines.append(f"{str(key)[:40]}: {str(value)[:120]}")
        if len(lines) >= 10:
            break
    return lines


def _model_id_of(agent: Any) -> str | None:
    """The LiteLLM model id the built agent will bill against.

    Read off the constructed model rather than resolved a second time: a second
    resolution is another database read and another chance for the two to
    disagree, and the translator only needs this to price the turn from
    LiteLLM's own table.

    Args:
        agent: The agno agent that was just built.

    Returns:
        The model id, or None when the agent does not expose one.
    """
    model_id = getattr(getattr(agent, "model", None), "id", None)
    return str(model_id) if model_id else None


def _build_context(
    username: str,
    api_key: str,
    body: dict,
    conversation_id: int,
    surface: str,
) -> ToolContext:
    """Build the run's tool context.

    ``trading_enabled`` here is only the session asking. The builder ANDs it with
    the operator's database setting, so a session that asks for order tools while
    trading is off in settings still does not get them.

    This runs after the conversation row exists and outside the caller's
    ``try``, so nothing in it may raise: an exception here answers a JSON client
    with a 500 HTML page and leaves behind the empty conversation
    ``_discard_empty_conversation`` exists to clean up.
    """
    chart_context = body.get("chart_context")
    return ToolContext(
        api_key=api_key,
        conversation_id=conversation_id,
        surface=surface,
        user_id=username,
        trading_enabled=bool(body.get("trading_enabled", False)),
        analyzer_mode=_analyzer_mode(),
        extras={"chart_context": chart_context} if isinstance(chart_context, dict) else {},
    )


def _analyzer_mode() -> bool:
    """Whether the platform analyzer toggle is on, defaulting to live.

    ``get_analyze_mode`` reads ``openalgo.db`` on a cold cache, so the first
    chat request a worker serves can fail here on a database that is busy or
    not yet migrated.

    **False, not True, is the safe default.** This flag feeds the risk guard's
    "analyzer mode if required" check, so claiming analyzer mode when it cannot
    be read would satisfy that gate on an unverified assumption and let a live
    order through. Reporting live means an operator who requires analyzer mode
    has their order refused, which is the failure worth having.
    """
    try:
        return bool(get_analyze_mode())
    except Exception:
        logger.exception("Could not read the analyzer mode; treating the run as live")
        return False


def _discard_empty_conversation(opened_here: bool, conversation_id: int, username: str) -> None:
    """Remove a conversation this request opened and never wrote a message to.

    Only ever called on a build failure, and only for a conversation created in
    the same request, so an existing conversation is never touched. Failure is
    swallowed: an orphan row is untidy, and turning it into a second error would
    replace a useful message about the model with a useless one about cleanup.

    Args:
        opened_here: Whether this request created the conversation.
        conversation_id: The conversation to remove.
        username: The owner, for the owner-scoped delete.
    """
    if not opened_here:
        return
    try:
        agent_db.delete_conversation(conversation_id, username)
    except Exception:
        logger.exception("Could not discard the empty conversation %s", conversation_id)


@agent_bp.route("/api/chat/stream", methods=["POST"])
@check_session_validity
@_stream_limit
def chat_stream():
    """Stream one turn of a conversation as Server-Sent Events.

    Everything that can fail happens before the response is opened: the setup
    gate, the conversation lookup, model resolution and agent construction. A
    bad model id is therefore a clean HTTP error rather than an answer that dies
    halfway through.

    The frames are ``data: {json}`` with no ``event:`` line, discriminated on a
    ``type`` field. A run that pauses for a confirmation ends on a ``confirm``
    frame with **no** ``done`` after it, and the client resumes it at
    ``/chat/confirm``.
    """
    username, api_key, error = _chat_preconditions()
    if error:
        return error

    body, error = _json_body()
    if error:
        return error

    message = str(body.get("message") or "").strip()
    if not message:
        return _error("A message is required", 400)
    if len(message) > MAX_MESSAGE_CHARS:
        return _error(f"A message may be at most {MAX_MESSAGE_CHARS} characters", 400)

    surface, surface_error = _surface_of(body)
    if surface_error:
        return _error(surface_error, 400)
    effort, effort_error = _reasoning_effort_of(body)
    if effort_error:
        return _error(effort_error, 400)

    raw_conversation = body.get("conversation_id")
    opened_here = raw_conversation in (None, "")
    if opened_here:
        created, store_message = agent_db.create_conversation(
            username, title=message[:80], surface=surface
        )
        if created is None:
            return _error(store_message or "Could not create the conversation", 500)
        conversation = agent_db.get_conversation(created["id"], username)
        if conversation is None:
            return _error("Could not create the conversation", 500)
    else:
        try:
            conversation_id = int(raw_conversation)
        except (TypeError, ValueError):
            return _error("conversation_id must be a whole number", 400)
        conversation = agent_db.get_conversation(conversation_id, username)
        if conversation is None:
            return _error(NOT_FOUND, 404)

    conversation_id = conversation.id
    session_id = conversation.agno_session_id
    if not conversation.title:
        agent_db.update_conversation(conversation_id, username, title=message[:80])

    context = _build_context(username, api_key, body, conversation_id, surface)
    try:
        agent = builder.build_agent(
            context,
            model_id=body.get("model_id"),
            session_id=session_id,
            reasoning_effort=effort,
            extra_runtime_lines=_runtime_lines(body.get("chart_context")),
        )
    except builder.AgentBuildError as exc:
        # A conversation opened by this request has nothing in it, and leaving
        # one behind per failed attempt fills the sidebar with empty rows for a
        # problem that is about the model rather than the conversation.
        _discard_empty_conversation(opened_here, conversation_id, username)
        return _build_error(exc)
    except Exception:
        _discard_empty_conversation(opened_here, conversation_id, username)
        logger.exception("Could not build the agent for conversation %s", conversation_id)
        return _error("Could not start the agent", 500)

    agent_db.add_message(conversation_id, "user", message)

    recorder = _TurnRecorder()
    chunks = agent_stream.stream_run(
        agent,
        message,
        conversation_id=conversation_id,
        session_id=session_id,
        user_id=username,
        model=_model_id_of(agent),
    )

    response = Response(
        stream_with_context(_record_stream(chunks, recorder, conversation_id, username)),
        mimetype="text/event-stream",
    )
    for header, value in SSE_HEADERS.items():
        response.headers[header] = value
    return response


@agent_bp.route("/api/chat/confirm", methods=["POST"])
@check_session_validity
@_stream_limit
def chat_confirm():
    """Resume a paused run once the operator has approved or rejected its tools.

    The paused run is the one whose stream ended on a ``confirm`` frame. This
    continues it in place: same run id, same agno session, same conversation.

    Decisions arrive either as a mapping of tool-call id to boolean, or as a
    list of ``{id, approved, tool}`` objects. A requirement no decision mentions
    is left undecided and agno pauses on it again, which is the right outcome
    for a partial answer rather than a silent approval.
    """
    username, api_key, error = _chat_preconditions()
    if error:
        return error

    body, error = _json_body()
    if error:
        return error

    run_id = str(body.get("run_id") or "").strip()
    if not run_id:
        return _error("A run_id is required", 400)

    try:
        conversation_id = int(body.get("conversation_id"))
    except (TypeError, ValueError):
        return _error("conversation_id must be a whole number", 400)

    conversation = agent_db.get_conversation(conversation_id, username)
    if conversation is None:
        return _error(NOT_FOUND, 404)

    session_id = str(body.get("session_id") or conversation.agno_session_id or "").strip()
    if not session_id:
        return _error("A session_id is required to resume a paused run", 400)

    decisions, tool_names, decision_error = _read_decisions(body.get("decisions"))
    if decision_error:
        return _error(decision_error, 400)
    if not decisions:
        return _error("At least one decision is required", 400)

    note = str(body.get("note") or "").strip()[:500] or None
    surface, surface_error = _surface_of(body)
    if surface_error:
        return _error(surface_error, 400)

    context = _build_context(username, api_key, body, conversation_id, surface)
    try:
        agent = builder.build_agent(
            context,
            model_id=body.get("model_id"),
            session_id=session_id,
        )
    except builder.AgentBuildError as exc:
        return _build_error(exc)
    except Exception:
        logger.exception("Could not build the agent to resume run %s", run_id)
        return _error("Could not resume the run", 500)

    # The human decision is recorded before the run is resumed, so an approval
    # is in the trail even if the resumed run then fails. The audit writer
    # swallows its own failures; it never blocks a trade.
    for call_id, approved in decisions.items():
        audit.record_decision(
            tool_names.get(call_id) or "pending_tool",
            approved=approved,
            args={"tool_call_id": call_id},
            conversation_id=conversation_id,
            run_id=run_id,
            actor=username,
            note=note,
        )

    recorder = _TurnRecorder()
    chunks = agent_stream.stream_continue(
        agent,
        run_id=run_id,
        session_id=session_id,
        conversation_id=conversation_id,
        decisions=decisions,
        note=note,
        user_id=username,
        model=_model_id_of(agent),
    )

    response = Response(
        stream_with_context(_record_stream(chunks, recorder, conversation_id, username)),
        mimetype="text/event-stream",
    )
    for header, value in SSE_HEADERS.items():
        response.headers[header] = value
    return response


def _read_decisions(raw: Any) -> tuple[dict[str, bool], dict[str, str], str | None]:
    """Normalise the two accepted shapes of a confirmation payload.

    Args:
        raw: Either ``{call_id: bool}`` or a list of ``{id, approved, tool}``.

    Returns:
        ``(decisions, tool_names, error)``. ``tool_names`` is only used for the
        audit row and is empty for the mapping form.
    """
    decisions: dict[str, bool] = {}
    tool_names: dict[str, str] = {}

    if isinstance(raw, dict):
        for key, value in raw.items():
            call_id = str(key).strip()
            if not call_id:
                return {}, {}, "A decision must name a tool call id"
            if not isinstance(value, bool):
                return {}, {}, "A decision must be true or false"
            decisions[call_id] = value
        return decisions, tool_names, None

    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                return {}, {}, "Each decision must be an object"
            call_id = str(entry.get("id") or "").strip()
            approved = entry.get("approved")
            if not call_id:
                return {}, {}, "A decision must name a tool call id"
            if not isinstance(approved, bool):
                return {}, {}, "A decision's approved field must be true or false"
            decisions[call_id] = approved
            name = str(entry.get("tool") or "").strip()
            if name:
                tool_names[call_id] = name[:120]
        return decisions, tool_names, None

    return {}, {}, "decisions must be an object or a list"


@agent_bp.route("/api/chat/<run_id>/cancel", methods=["POST"])
@check_session_validity
@_api_limit
def cancel_run(run_id: str):
    """Stop a running turn server-side.

    No agent is built and no credential is decrypted: agno's cancellation
    registry is process-global and ``Agent.cancel_run`` is a static method, so
    the class itself is all that is needed. The call is still handed to
    ``request_cancel``, which runs it on a real OS thread, because that registry
    is guarded by a lock created after eventlet monkey-patched the stdlib and a
    greenlet contending on it can wedge the worker.

    Cancellation is best effort. A run that has already finished, or that never
    existed, answers success: the caller's intent, that the run not continue, is
    satisfied either way, and reporting a 404 would let the run id space be
    probed for what is live.
    """
    username = _current_user()
    if not username:
        return _error("Not authenticated", 401)

    run_id = (run_id or "").strip()
    if not run_id:
        return _error("A run_id is required", 400)

    try:
        from agno.agent import Agent
    except ImportError:
        return _error("The agent module requires the 'agno' package", 503)

    agent_stream.request_cancel(Agent, run_id)
    logger.info("Agent run %s cancelled by %s", run_id, username)
    return _ok({"message": "Cancellation requested", "run_id": run_id})
