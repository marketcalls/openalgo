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
from werkzeug.exceptions import RequestEntityTooLarge

from database import agent_db
from database.auth_db import get_api_key_for_tradingview
from database.settings_db import get_analyze_mode
from limiter import limiter
from services.agent import attachments as agent_attachments
from services.agent import builder, catalog, chatgpt_oauth, providers
from services.agent import settings as agent_settings
from services.agent import stream as agent_stream
from services.agent import viz_sink as viz_sink_module
from services.agent.frames import SSE_HEADERS
from services.agent.providers import litellm_model_id, reasoning_capable
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

#: The largest request body any route here will read. Attachments arrive as
#: base64 inside the JSON body, which inflates them by about a third, so this is
#: ``attachments.MAX_TOTAL_BYTES`` plus that inflation plus room for the message
#: and the rest of the envelope. Without it a single POST could ask this process
#: to buffer an unbounded string before a single validation runs; Flask sets no
#: ``MAX_CONTENT_LENGTH`` by default and the production worker never restarts.
MAX_REQUEST_BYTES = 12_000_000

#: Sidecar entry recording which files a turn carried. Metadata only, never the
#: bytes: see ``services/agent/attachments.py`` for the size comparison that
#: decided that. The client's hydrator ignores a notice type it does not know,
#: so a stored row renders exactly as it did before this existed.
ATTACHMENTS_NOTICE = "attachments"

#: Seconds a credential test waits on the provider. Long enough for a cold
#: local Ollama to load a model, short enough that an unreachable endpoint is
#: reported rather than left hanging.
TEST_TIMEOUT_SECONDS = 30

#: How much of a provider's failure message is stored and returned. The message
#: is kept verbatim because "invalid API key" and "model not found" need
#: different fixes; the cap only stops a stack-shaped error filling the column.
MAX_TEST_ERROR_CHARS = 2000

NOT_FOUND = "Conversation not found"

#: Sidecar entry the stream route writes on the user's own message so the resume
#: route can rebuild the agent the way the original turn built it. The client's
#: hydrator ignores a notice type it does not recognise, so this renders nothing.
RUN_OPTIONS_NOTICE = "run_options"

#: How many ``viz`` charts one stored turn keeps. A chart spec is a series, not
#: a sentence, so an unbounded count would put a data dump in a text column.
MAX_STORED_VIZ = 4

#: How many chart-context bullets reach the prompt. The panel reads its context
#: fresh at send time, so without a cap this is an operator-supplied prompt of
#: unbounded length.
MAX_RUNTIME_LINES = 10

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
    """The request body as a dict, or ``(None, error_response)``.

    The size limit is a fact about these routes, not about the application, so
    it is applied per request rather than as ``MAX_CONTENT_LENGTH``, which would
    change every other blueprint's behaviour.

    It is applied **twice**, and the declared-length check is the one that does
    the work. ``request.max_content_length`` alone was not enough here, measured
    against the running app: CSRF protection looks for a token in
    ``request.form`` before the view runs, which resolves the cached ``stream``
    property while the limit is still unset, so a 13 MB body sailed through to
    be refused later by a per-file cap. Reading ``content_length`` off the header
    does not depend on who touched the stream first. The assignment is kept for
    the case the header does not cover, a chunked body with no declared length.
    """
    declared = request.content_length
    if declared is not None and declared > MAX_REQUEST_BYTES:
        return None, _error(
            f"The request body may be at most {MAX_REQUEST_BYTES // 1_000_000} MB", 413
        )
    request.max_content_length = MAX_REQUEST_BYTES
    try:
        payload = request.get_json(silent=True)
    except RequestEntityTooLarge:
        return None, _error(
            f"The request body may be at most {MAX_REQUEST_BYTES // 1_000_000} MB", 413
        )
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
    if address is not None:
        # An IPv4-mapped IPv6 literal is the same address written differently,
        # and `str()` renders it as `::ffff:a9fe:a9fe`, which matches nothing in
        # the set. `http://[::ffff:169.254.169.254]/` reached the metadata
        # endpoint before this line existed.
        mapped = getattr(address, "ipv4_mapped", None)
        if mapped is not None:
            address = mapped
        if str(address) in BLOCKED_BASE_URL_HOSTS:
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


def _websearch_spec_or_400(provider: str):
    """``(spec, error_response)`` for a route addressing one web search provider.

    Resolved before anything else happens, so an unknown id is refused at the
    edge and every later line, including every log line, carries a vocabulary
    member rather than whatever was typed into the path.

    Args:
        provider: The path segment naming the provider.

    Returns:
        The resolved spec, or a 400 naming the three that exist.
    """
    try:
        return agent_settings.websearch_provider_spec(provider), None
    except ValueError as exc:
        return None, _error(str(exc), 400)


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

    try:
        # Does no network work and starts no device login, so it is safe to read
        # on the gate. It is here rather than behind a second request because a
        # `chatgpt/` model that is registered but not signed in looks configured
        # and is not, and the setup page has to render that on first paint.
        chatgpt_authorised = bool(chatgpt_oauth.is_authorised())
    except Exception:
        # logger.error and no traceback: this reads a credential.
        logger.error("Could not read the ChatGPT subscription authorisation")
        chatgpt_authorised = False

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
            "chatgpt_authorised": chatgpt_authorised,
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
    return _ok({"data": _with_resolved_capabilities(agent_db.list_models())})


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
    return _ok(
        {
            "data": _with_resolved_capabilities(
                agent_db.provider_model_to_dict(agent_db.get_model(created["id"]))
            )
        },
        201,
    )


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

    return _ok(
        {
            "data": _with_resolved_capabilities(
                agent_db.provider_model_to_dict(agent_db.get_model(model_id))
            )
        }
    )


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
                "data": _with_resolved_capabilities(
                    agent_db.provider_model_to_dict(agent_db.get_model(model_id))
                ),
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

        # Streamed, because streaming is the only way the agent ever runs a
        # model: `stream.py` calls `agent.run(stream=True)` and nothing else.
        # A test that takes a path the product never takes can fail on a defect
        # no operator would ever meet, and can pass over one they would.
        #
        # It is not hypothetical. LiteLLM's non-streaming reader for the
        # ChatGPT subscription raises "Unknown items in responses API
        # response: []" on a reply that streams back perfectly, so a plan model
        # that works in the chat reported Failed here. Measured on this
        # install: both OpenAI rows pass either way, the subscription row only
        # streamed.
        stream = litellm.completion(
            model=call_kwargs["id"],
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
            timeout=TEST_TIMEOUT_SECONDS,
            num_retries=0,
            stream=True,
            api_key=call_kwargs.get("api_key"),
            api_base=call_kwargs.get("api_base"),
        )
        # Draining is the test. An iterator left unread would report success
        # on a credential the provider goes on to reject, which is the one
        # thing this route exists to catch.
        for _ in stream:
            pass
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
                "data": _with_resolved_capabilities(
                    agent_db.provider_model_to_dict(agent_db.get_model(model_id))
                ),
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
            "data": _with_resolved_capabilities(
                agent_db.provider_model_to_dict(agent_db.get_model(model_id))
            ),
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
    return _ok(
        {
            "data": _with_resolved_capabilities(
                agent_db.provider_model_to_dict(agent_db.get_model(model_id))
            )
        }
    )


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
# Web search
#
# Separate from `/api/settings` on purpose. A credential must not travel in the
# same payload as a display setting: the settings PUT accepts a partial body and
# echoes it back, and a key added to that shape would be one careless `data`
# render away from the screen. These routes follow the model registry instead,
# which is the pattern for the same problem: a boolean and a fingerprint on the
# way out, a write-only key on the way in, and a separate explicit test.
# ---------------------------------------------------------------------------


@agent_bp.route("/api/websearch", methods=["GET"])
@check_session_validity
@_api_limit
def get_websearch():
    """The web search configuration, with every key described and none shown.

    Carries the selected provider, the tunables, today's usage against the daily
    cap, and one entry per selectable provider saying whether it needs a key,
    whether one is stored and what its fingerprint is. The shipped defaults
    travel alongside, as they do on ``/api/settings``.
    """
    try:
        return _ok(
            {
                "data": agent_settings.get_websearch_config(),
                "defaults": agent_settings.get_websearch_defaults(),
            }
        )
    except Exception:
        logger.exception("Could not read the web search configuration")
        return _error("Could not read the web search configuration", 500)


@agent_bp.route("/api/websearch", methods=["PUT"])
@check_session_validity
@_api_limit
def put_websearch():
    """Select the provider, and set the tunables around it.

    Every value is validated before anything is written, so a request carrying
    one bad field changes nothing. An unknown key is rejected rather than
    ignored, and so is an unknown provider: writing one would leave the tool
    module quietly falling back to DuckDuckGo while the screen claimed
    otherwise.

    This route never accepts a key. Keys have their own route below.
    """
    body, error = _json_body()
    if error:
        return error
    if not body:
        return _error("Nothing to update", 400)

    try:
        return _ok({"data": agent_settings.update_websearch(body)})
    except ValueError as exc:
        return _error(str(exc), 400)
    except Exception:
        logger.exception("Could not write the web search configuration")
        return _error("Could not save the web search configuration", 500)


@agent_bp.route("/api/websearch/providers/<provider>/key", methods=["PUT"])
@check_session_validity
@_api_limit
def put_websearch_key(provider: str):
    """Store one provider's key.

    Refused for DuckDuckGo, which takes no key. The value is encrypted with the
    platform's existing Fernet and the store compares the **decrypted
    plaintext** before it writes, so re-saving an unchanged key touches no row.
    That comparison is not an optimisation: Fernet is non-deterministic, a
    ciphertext comparison never matches, and rewriting the row on every save is
    how real "database is locked" failures were produced elsewhere here.

    Blank is refused rather than read as "clear it", because this route takes
    only a key. Clearing one is the DELETE below, which says so.

    Returns:
        The refreshed configuration. The key is not in it.
    """
    spec, error = _websearch_spec_or_400(provider)
    if error:
        return error

    body, error = _json_body()
    if error:
        return error

    api_key = body.get("api_key")
    try:
        data = agent_settings.set_websearch_key(spec.id, api_key)
    except ValueError as exc:
        return _error(str(exc), 400)
    except Exception:
        # logger.error and no traceback: the submitted key is a local in this
        # frame, and str(exc) from a storage or encryption failure can quote the
        # material it choked on, where utils.logging's redaction patterns -- all
        # of which key off a "token=" or "secret:" style label -- do not match it.
        logger.error("Could not store the %s web search key", spec.id)
        return _error(f"Could not store the {spec.label} key", 500)
    finally:
        # The plaintext lives no longer than the call it was needed for.
        api_key = None

    logger.info("Web search key stored for %s", spec.id)
    return _ok({"data": data, "message": f"{spec.label} key stored"})


@agent_bp.route("/api/websearch/providers/<provider>/key", methods=["DELETE"])
@check_session_validity
@_api_limit
def delete_websearch_key(provider: str):
    """Remove one provider's key.

    Idempotent: clearing a key that is not there succeeds, because the operator
    asked for that provider to hold no key and it holds none. A paid provider
    left selected with no key degrades to DuckDuckGo and says so in the tool
    result rather than failing silently.
    """
    spec, error = _websearch_spec_or_400(provider)
    if error:
        return error

    try:
        data = agent_settings.clear_websearch_key(spec.id)
    except ValueError as exc:
        return _error(str(exc), 400)
    except Exception:
        logger.exception("Could not clear the %s web search key", spec.id)
        return _error(f"Could not clear the {spec.label} key", 500)

    return _ok({"data": data, "message": f"{spec.label} key cleared"})


@agent_bp.route("/api/websearch/providers/<provider>/test", methods=["POST"])
@check_session_validity
@_test_limit
def test_websearch_provider(provider: str):
    """Validate one web search provider with a single real query.

    The same shape as ``/api/models/<id>/test`` and the same rule: a real call,
    or it is not a test. The query runs through the very functions the two tools
    dispatch to, which is why Perplexity is exercised on the research path and
    not the link path. Perplexity answers questions and returns no links, so
    testing it as a link provider would report a working key as broken.

    An ``api_key`` in the body is used in place of the stored one, so a key the
    operator has just typed can be tested before it is saved. It is never
    logged, never stored by this route, and never returned.

    **This function's locals hold a provider key**, so its failure paths log with
    ``logger.error`` and no traceback, exactly as ``test_model`` does.

    Returns:
        ``{ok, provider, message, latency_ms, result_count}`` alongside the
        refreshed configuration, since a passing test updates the key's last
        use.
    """
    spec, error = _websearch_spec_or_400(provider)
    if error:
        return error

    # A body is optional here: testing the stored key is the common case, and
    # requiring an empty object for it would be noise.
    body = request.get_json(silent=True)
    if body is not None and not isinstance(body, dict):
        return _error("The request body must be a JSON object", 400)

    api_key = (body or {}).get("api_key")
    if api_key is not None and not isinstance(api_key, str):
        return _error("api_key must be a string", 400)

    try:
        probe = agent_settings.probe_websearch_provider(spec.id, api_key)
        # Belt and braces. The probe builds its message from provider labels,
        # HTTP statuses and exception class names rather than response bodies,
        # but a message that ever did quote the key must not become a log line.
        message = _redact_secret(probe.message, api_key)[:MAX_TEST_ERROR_CHARS]
    except ValueError as exc:
        return _error(str(exc), 400)
    except Exception:
        logger.error("The %s web search test could not be run", spec.id)
        return _error("Could not run the web search test", 500)
    finally:
        api_key = None

    if probe.ok:
        logger.info("Web search provider %s passed its test in %sms", spec.id, probe.latency_ms)
    else:
        logger.error("Web search provider %s failed its test: %s", spec.id, message)

    return _ok(
        {
            "ok": probe.ok,
            "provider": spec.id,
            "message": message,
            "latency_ms": probe.latency_ms,
            "result_count": probe.result_count,
            "data": agent_settings.get_websearch_config(),
        }
    )


# ---------------------------------------------------------------------------
# ChatGPT subscription
# ---------------------------------------------------------------------------


@agent_bp.route("/api/chatgpt/status", methods=["GET"])
@check_session_validity
@_api_limit
def chatgpt_status():
    """Whether a ChatGPT plan is authorised, and what any login in flight is doing.

    Carries a fingerprint and never a token, exactly as the model routes do for
    an API key. The fingerprint is taken over the refresh token rather than over
    the stored blob, so it survives an access-token refresh and stays the
    identifier the operator saw when they signed in.

    Returns:
        ``{data: {provider, authorised, fingerprint, account_id,
        access_token_expires_at, access_token_expired, stored_in_database,
        token_dir, login: {...}}}``.
    """
    try:
        data = chatgpt_oauth.status()
    except Exception:
        # logger.error and no traceback: this reads a credential, and a decrypt
        # failure can put the material it choked on into str(exc), which
        # utils.logging's redaction patterns do not match because they all key
        # off a "token=" or "secret:" style label.
        logger.error("Could not read the ChatGPT subscription status")
        return _error("Could not read the ChatGPT subscription status", 500)

    return _ok({"data": data})


@agent_bp.route("/api/chatgpt/login", methods=["POST"])
@check_session_validity
@_test_limit
def chatgpt_login():
    """Start the OAuth device flow and return the code to show the operator.

    Returns as soon as the device code has been issued, which is one bounded
    HTTP request; the poll that waits for the operator to approve it runs on a
    real OS thread and nothing green ever waits on it. On ``_test_limit`` rather
    than the shared budget because it reaches upstream.

    A login already in flight is returned as it stands rather than replaced: the
    device endpoint applies a cooldown after issuing a code, and the first code
    may already be half typed at the verification URL. ``{"force": true}``,
    which is what a "start over" control sends, cancels it and begins again.

    The user code is in the response and deliberately in no log line: it is a
    standing phishing target and belongs on the authenticated operator's screen.

    Returns:
        ``{data: {state, user_code, verification_url, started_at, expires_at,
        message}, reused: bool}``. ``501`` when LiteLLM has no chatgpt provider,
        ``502`` when the device code could not be issued.
    """
    body = request.get_json(silent=True)
    if body is not None and not isinstance(body, dict):
        return _error("The request body must be a JSON object", 400)
    force = bool((body or {}).get("force"))

    before = chatgpt_oauth.login_status()
    try:
        snapshot = chatgpt_oauth.start_login(force=force)
    except chatgpt_oauth.ChatGptOAuthUnavailable as exc:
        logger.error("ChatGPT subscription login is unavailable: %s", exc)
        return _error(str(exc), 501, {"data": chatgpt_oauth.login_status().as_dict()})
    except chatgpt_oauth.ChatGptOAuthError as exc:
        logger.error("ChatGPT subscription login could not start: %s", exc)
        return _error(str(exc), 502, {"data": chatgpt_oauth.login_status().as_dict()})
    except Exception:
        logger.exception("Could not start the ChatGPT subscription login")
        return _error("Could not start the ChatGPT sign-in", 500)

    reused = (
        before.pending
        and snapshot.started_at == before.started_at
        and snapshot.user_code == before.user_code
    )
    return _ok({"data": snapshot.as_dict(), "reused": reused})


@agent_bp.route("/api/chatgpt/cancel", methods=["POST"])
@check_session_validity
@_api_limit
def chatgpt_cancel():
    """Stop a login in flight.

    Idempotent: cancelling when nothing is running succeeds with ``stopped``
    false, because the operator asked for no login to be running and none is.

    The snapshot is read back through ``login_status``, which is a frozen copy
    taken under a real lock and costs nothing. ``status()`` is deliberately not
    used here: it decrypts the stored credential to build a fingerprint, and a
    UI polling this while a code is on screen would pay for that every second.

    Returns:
        ``{data: {state, ...}, stopped: bool}``.
    """
    try:
        stopped = chatgpt_oauth.cancel_login()
    except Exception:
        logger.exception("Could not cancel the ChatGPT subscription login")
        return _error("Could not cancel the ChatGPT sign-in", 500)

    return _ok({"data": chatgpt_oauth.login_status().as_dict(), "stopped": stopped})


@agent_bp.route("/api/chatgpt/session", methods=["DELETE"])
@check_session_validity
@_api_limit
def chatgpt_forget():
    """Sign the subscription out: drop the stored secret and the cached file.

    Idempotent, and it cancels a login in flight first, so signing out during a
    half-finished sign-in leaves nothing behind polling for a code nobody will
    enter.

    Returns:
        ``{removed: bool}``, true when either copy of the credential was there
        to remove.
    """
    try:
        removed = bool(chatgpt_oauth.forget())
    except Exception:
        # logger.error and no traceback for the same reason as the status route:
        # this path handles a credential.
        logger.error("Could not remove the ChatGPT subscription authorisation")
        return _error("Could not sign out of ChatGPT", 500)

    return _ok({"removed": removed, "message": "ChatGPT subscription signed out"})


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


@agent_bp.route(
    "/api/conversations/<int:conversation_id>/messages/<int:message_id>", methods=["DELETE"]
)
@check_session_validity
@_api_limit
def truncate_conversation(conversation_id: int, message_id: int):
    """Remove a message and everything after it, from BOTH stores.

    This is what editing a question does before it is asked again. The answer
    that followed it, and everything after that, has to go: an edited question
    sitting above its old answer is incoherent.

    Two stores, and truncating only the first is the failure this route exists
    to avoid. ``ag_message`` is the transcript the sidebar renders. Agno's own
    session store is what gets replayed into the model's context through
    ``add_history_to_context``, so a purely visual truncation would leave the
    model still answering the question the operator has just rewritten. The
    edit would look right and silently not be.

    The agno runs are found through the ``run`` entry each assistant row carries
    in its sidecar. A row stored before that entry existed simply has none, and
    its run stays in the session store: the transcript is still correct, and the
    model may carry one superseded exchange it will age out of its history
    window anyway. That is the honest degradation, and it is better than
    refusing to truncate at all.

    Ownership is checked first. A conversation id is a small integer and the
    route is authenticated but not authorised by anything else, so without this
    an operator could truncate somebody else's thread by guessing.
    """
    username = session.get("user")
    conversation = agent_db.get_conversation(conversation_id, username)
    if conversation is None:
        return _error(NOT_FOUND, 404)

    try:
        removed = agent_db.truncate_messages_from(conversation_id, message_id)
    except Exception:
        logger.exception("Could not truncate conversation %s", conversation_id)
        return _error("Could not truncate the conversation", 500)

    run_ids = [
        str(entry.get("run_id"))
        for row in removed
        for entry in (row.get("notices") or [])
        if isinstance(entry, dict) and entry.get("type") == "run" and entry.get("run_id")
    ]

    forgotten = _forget_agno_runs(run_ids)

    logger.info(
        "Truncated conversation %s from message %s: %d messages, %d runs forgotten",
        conversation_id,
        message_id,
        len(removed),
        forgotten,
    )
    return _ok({"removed": len(removed), "runs_forgotten": forgotten})


def _forget_agno_runs(run_ids: list[str]) -> int:
    """Delete runs from agno's own session store.

    Never raises. A transcript that was truncated and a model history that was
    not is a worse outcome than either alone, but it is still better than an
    error after the rows are already gone: the caller has committed, and the
    operator is waiting to re-ask their question.

    Args:
        run_ids: The runs to remove.

    Returns:
        How many were removed.
    """
    if not run_ids:
        return 0
    try:
        store = builder.session_db()
    except Exception:
        logger.exception("Could not open the agno session store to forget runs")
        return 0
    if store is None:
        return 0

    forgotten = 0
    for run_id in run_ids:
        try:
            # delete_run takes the run id alone and answers whether it removed
            # anything, so a run already gone is not counted as forgotten.
            if store.delete_run(run_id=run_id):
                forgotten += 1
        except Exception:
            # One run that will not delete should not strand the rest. It ages
            # out of num_history_runs on its own.
            logger.exception("Could not forget agno run %s", run_id)
    return forgotten


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
            discriminator: ``notice``, ``usage``, ``error``, ``confirm``, each
            ``viz`` chart and the accumulated ``ui`` markup. The column is
            free-form JSON, and one ordered list of what happened beside the
            answer is what the client re-renders from.
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
        "_viz",
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
        self._viz: list[dict[str, Any]] = []
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
        elif kind == "viz":
            # Kept so a reloaded conversation still shows its charts. Capped
            # because a chart spec is a data series rather than a sentence, and
            # this row is stored JSON: a turn that drew a dozen of them would
            # otherwise put a megabyte in one column.
            if len(self._viz) < MAX_STORED_VIZ:
                self._viz.append(payload)
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
        entries.extend(self._viz)
        if self._ui:
            entries.append({"type": "ui", "content": "".join(self._ui)})
        if self._usage is not None:
            entries.append(self._usage)
        if self.run_id:
            # The agno run that produced this answer, carried so an edit can
            # truncate the model's OWN history and not merely the transcript
            # the operator sees. Those are two different stores: ag_message is
            # what the sidebar renders, and agno's session store is what gets
            # replayed into context. Dropping only the first would leave the
            # model still seeing a question the operator has since rewritten,
            # so the edit would look right and silently not be.
            #
            # It rides in the existing JSON sidecar rather than a new column,
            # which is what keeps this off the migration path entirely.
            # `hydrate.ts` ignores a notice type it does not know, so a stored
            # row still renders as before.
            entries.append({"type": "run", "run_id": self.run_id})
        return entries

    def has_content(self) -> bool:
        """Whether the turn produced anything worth persisting."""
        return bool(self.text or self.tools or self.notices or self._viz or self._ui or self._usage)


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
        if len(lines) >= MAX_RUNTIME_LINES:
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
    operator_message: str = "",
    viz_sink: list | None = None,
    web_search: bool = True,
) -> ToolContext:
    """Build the run's tool context.

    ``trading_enabled`` here is only the session asking. The builder ANDs it with
    the operator's database setting, so a session that asks for order tools while
    trading is off in settings still does not get them.

    ``web_search`` is the composer's own switch for this turn, and off means the
    web search toolkit is not built, so its two tools are not in the request the
    provider receives. That is the only reading of the switch that is true: a
    tool the model can still see is a tool it can still call, and an instruction
    not to would be a preference rather than a control.

    ``operator_message`` is the turn's own message from the person, and it is
    the surface's job to supply it. The web search taint boundary builds every
    outbound query from it and refuses outright when it is missing, so a route
    that forgets it does not degrade search, it disables it. It is passed
    explicitly rather than read out of ``body`` because the resume route has no
    new message and has to recover the one that opened the run.

    ``viz_sink`` is the list a chart tool leaves its payload on. It is created
    per request and passed here rather than made by this function, because the
    route also has to hand the *same* list to the streaming call, which is what
    turns a queued payload into a frame. ``ToolContext.from_session_state``
    copies ``extras`` shallowly, so every toolkit the run builds shares this one
    list rather than a copy of it.

    This runs after the conversation row exists and outside the caller's
    ``try``, so nothing in it may raise: an exception here answers a JSON client
    with a 500 HTML page and leaves behind the empty conversation
    ``_discard_empty_conversation`` exists to clean up.
    """
    chart_context = body.get("chart_context")
    extras: dict = {"user_message": operator_message} if operator_message else {}
    if isinstance(chart_context, dict):
        extras["chart_context"] = chart_context
    if viz_sink is not None:
        extras[viz_sink_module.SINK_KEY] = viz_sink
    return ToolContext(
        api_key=api_key,
        conversation_id=conversation_id,
        surface=surface,
        user_id=username,
        trading_enabled=bool(body.get("trading_enabled", False)),
        web_search_enabled=bool(web_search),
        analyzer_mode=_analyzer_mode(),
        extras=extras,
    )


def _web_search_of(body: dict) -> bool:
    """Whether this turn may reach the public web.

    Absent means on, which is the behaviour every caller had before the switch
    existed and what the module's own acceptance criteria ask for: search works
    out of the box with nothing configured. Only an explicit false withholds the
    tools.

    A string is read as well as a boolean. A switch that only understood JSON
    ``false`` would be silently on for a client that sent ``"false"``, and the
    direction of that mistake is the wrong one.

    Args:
        body: The request body.

    Returns:
        True when the web search toolkit should be built for this turn.
    """
    raw = body.get("web_search")
    if raw is None:
        return True
    if isinstance(raw, str):
        return raw.strip().lower() not in ("false", "0", "off", "no", "")
    return bool(raw)


def _last_user_row(conversation_id: int) -> dict[str, Any]:
    """The most recent turn the person sent in this conversation.

    A resumed run carries only the approval decisions, so everything the
    original turn was started with has to come back out of the store. That is
    the operator's own message, which the web search boundary builds every
    outbound query from, and the run options the turn was built with, which
    :func:`_run_options_of` reads off the same row.

    A read failure degrades to an empty row rather than raising: the resumed run
    then loses the message and the options, which is a worse answer, not a
    failed one.

    Args:
        conversation_id: The conversation being resumed.

    Returns:
        The last user message row, or an empty mapping when there is none.
    """
    try:
        rows = agent_db.list_messages(conversation_id)
    except Exception:
        logger.exception("Could not read the last user turn for conversation %s", conversation_id)
        return {}
    for row in reversed(rows):
        if row.get("role") == "user":
            return dict(row)
    return {}


def _operator_message_of(row: dict[str, Any]) -> str:
    """The operator's own text from a stored user row.

    Args:
        row: A row from :func:`_last_user_row`.

    Returns:
        The message, or an empty string. Empty refuses web search rather than
        searching on something unverified.
    """
    content = row.get("content")
    return content if isinstance(content, str) and content.strip() else ""


def _run_options_notice(
    effort: str | None,
    runtime_lines: list[str],
    web_search: bool,
    files: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]] | None:
    """Store what a turn was built with, beside the message that opened it.

    The resume route receives neither the reasoning effort, nor the chart
    context, nor the web search switch: the client posts only the decisions.
    Recording them on the user row is what lets a resumed run be built the same
    way the original was, rather than silently dropping to the platform default
    and to no chart awareness at all.

    **The web search switch is the one that matters for safety here.** A turn
    sent with search off that pauses on a confirmation would otherwise come back
    with the search tools in its schema, because the resume route builds a fresh
    agent and would have nothing telling it the switch was off. The operator
    approving an order is not asking to lift a switch they set on the question.
    It is stored as an explicit false, so a stored ``off`` and a row written
    before this existed stay distinguishable.

    The chart context is stored **already rendered** into the same bounded lines
    the prompt would carry, so what comes back is exactly what goes into the
    prompt and no second, unbounded shape is persisted.

    Args:
        effort: The reasoning effort the request asked for, if any.
        runtime_lines: The rendered chart-context lines, if any.
        web_search: Whether this turn was allowed to reach the web.
        files: Attachment metadata, if the turn carried any.

    Returns:
        The notices list, or None when the turn carried nothing worth
        recording. Each entry's ``type`` is unknown to the client's hydrator,
        which ignores what it does not recognise, so a user row still renders as
        plain text.
    """
    entry: dict[str, Any] = {"type": RUN_OPTIONS_NOTICE}
    if effort:
        entry["reasoning_effort"] = effort
    if runtime_lines:
        entry["runtime_lines"] = list(runtime_lines)
    if not web_search:
        entry["web_search"] = False

    notices: list[dict[str, Any]] = [entry] if len(entry) > 1 else []
    if files:
        notices.append({"type": ATTACHMENTS_NOTICE, "items": files})
    return notices or None


def _run_options_of(row: dict[str, Any]) -> tuple[str | None, list[str], bool]:
    """Recover the run options a stored turn was built with.

    Every value is re-validated on the way out. The row is our own write, but a
    stored value reaching ``build_agent`` unchecked is exactly the shape of
    mistake that outlives the code that wrote it.

    Args:
        row: A row from :func:`_last_user_row`.

    Returns:
        ``(reasoning_effort, runtime_lines, web_search)``. The first two may be
        absent; the third defaults to True, matching a row written before the
        switch existed and the behaviour of a client that sends no switch.
    """
    notices = row.get("notices")
    if not isinstance(notices, list):
        return None, [], True

    for entry in notices:
        if not isinstance(entry, dict) or entry.get("type") != RUN_OPTIONS_NOTICE:
            continue
        effort = str(entry.get("reasoning_effort") or "").strip().lower()
        if effort not in agent_db.REASONING_EFFORTS:
            effort = ""
        raw_lines = entry.get("runtime_lines")
        lines = (
            [str(line)[:200] for line in raw_lines[:MAX_RUNTIME_LINES] if isinstance(line, str)]
            if isinstance(raw_lines, list)
            else []
        )
        return effort or None, lines, entry.get("web_search") is not False
    return None, [], True


def _with_resolved_capabilities(payload: Any) -> Any:
    """Overlay the capabilities LiteLLM knows onto a serialised model row.

    ``supports_reasoning`` is an operator checkbox in the database, and the
    builder does not trust it on its own: LiteLLM decides for any model it
    knows, and the checkbox only fills in for one it has never heard of. If the
    API handed the raw column to the client, the picker would offer a reasoning
    control the run would ignore, or hide one the run would honour, and the two
    would disagree without either being wrong on its own terms.

    So the resolved answer is computed once and used both places. This is a
    presentation overlay rather than a write: the operator's own choice stays in
    the column exactly as they set it.

    Args:
        payload: One serialised model dict, or a list of them.

    Returns:
        The same shape, with ``supports_reasoning`` resolved.
    """
    if isinstance(payload, list):
        return [_with_resolved_capabilities(item) for item in payload]
    if not isinstance(payload, dict):
        return payload

    kind = str(payload.get("provider_kind") or "")
    name = str(payload.get("model_name") or "")
    if not kind or not name:
        return payload

    try:
        resolved = reasoning_capable(
            litellm_model_id(kind, name), bool(payload.get("supports_reasoning"))
        )
    except Exception:
        logger.exception("Could not resolve reasoning support for %s/%s", kind, name)
        return payload

    return {**payload, "supports_reasoning": resolved}


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

    # Before the conversation row exists, so a refused file leaves nothing
    # behind. Every cap, the content sniff and the declared-type check all run
    # here; what survives is bytes this process has already measured.
    try:
        files = agent_attachments.parse_attachments(body.get("attachments"))
    except agent_attachments.AttachmentError as exc:
        return _error(exc.message, 400, {"kind": "input"})

    web_search = _web_search_of(body)

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

    runtime_lines = _runtime_lines(body.get("chart_context"))
    viz_sink = viz_sink_module.new_sink()
    context = _build_context(
        username,
        api_key,
        body,
        conversation_id,
        surface,
        message,
        viz_sink=viz_sink,
        web_search=web_search,
    )
    try:
        agent = builder.build_agent(
            context,
            model_id=body.get("model_id"),
            session_id=session_id,
            reasoning_effort=effort,
            extra_runtime_lines=runtime_lines,
            require_vision=agent_attachments.has_image(files),
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

    # The stored content is the operator's own typed text, never the composed
    # input below. Two reasons, and the second is a control rather than a
    # preference: the transcript should show the question that was asked, and
    # `_operator_message_of` reads this row back to build the web search taint
    # boundary. Folding a file's contents in here would make every word of an
    # attached document a token the model is allowed to send to a search
    # provider, which is exactly the exfiltration path that boundary exists for.
    stored_user, _store_error = agent_db.add_message(
        conversation_id,
        "user",
        message,
        notices=_run_options_notice(
            effort, runtime_lines, web_search, agent_attachments.stored_metadata(files)
        ),
    )
    # The client addresses a truncation by database id, and its own message ids
    # are local counters, so the row it just created has to travel back in the
    # start frame. Without it an edit has nothing to name and fails silently.
    user_message_id = (stored_user or {}).get("id") or ""

    # A text attachment is prompt text and travels inside the message; an image
    # is a media part and travels beside it. Both are what the model sees this
    # turn and what agno replays into every later turn of the conversation.
    text_block = agent_attachments.prompt_block(files)
    model_input = f"{message}\n\n{text_block}" if text_block else message

    recorder = _TurnRecorder()
    chunks = agent_stream.stream_run(
        agent,
        model_input,
        images=agent_attachments.images_for_run(files) or None,
        conversation_id=conversation_id,
        session_id=session_id,
        user_id=username,
        model=_model_id_of(agent),
        tool_frames=viz_sink_module.frame_hook(viz_sink),
        user_message_id=user_message_id,
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
    effort, effort_error = _reasoning_effort_of(body)
    if effort_error:
        return _error(effort_error, 400)

    # A resumed run has to be built the way the run it resumes was built. The
    # client posts only the decisions, so the reasoning effort and the chart
    # context come back off the user row the way the operator's message does;
    # a value the client did send still wins, because it is the fresher one.
    last_user = _last_user_row(conversation_id)
    stored_effort, stored_lines, stored_web_search = _run_options_of(last_user)
    effort = effort or stored_effort
    runtime_lines = _runtime_lines(body.get("chart_context")) or stored_lines
    # Both have to agree. The stored value is the switch the operator set on the
    # question; the body's is whatever this client sent. Approving a pending
    # order is not an occasion to hand the run a tool the original turn withheld,
    # so the resumed run gets the narrower of the two.
    web_search = stored_web_search and _web_search_of(body)

    viz_sink = viz_sink_module.new_sink()
    context = _build_context(
        username,
        api_key,
        body,
        conversation_id,
        surface,
        _operator_message_of(last_user),
        viz_sink=viz_sink,
        web_search=web_search,
    )
    try:
        agent = builder.build_agent(
            context,
            model_id=body.get("model_id"),
            session_id=session_id,
            reasoning_effort=effort,
            extra_runtime_lines=runtime_lines,
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
        tool_frames=viz_sink_module.frame_hook(viz_sink),
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
