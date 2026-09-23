"""Streamable HTTP transport for the Remote MCP feature.

Two endpoints:

* ``POST /mcp`` — JSON-RPC 2.0 dispatcher. Accepts ``initialize``,
  ``tools/list``, ``tools/call`` (and ``ping``). Validates a Bearer
  access token, checks scope, and dispatches to the underlying
  ``@mcp.tool()`` Python function via :mod:`mcp.tool_registry`.

* ``GET /mcp`` — Server-Sent Events stream. Holds the connection open
  with periodic comments so the client knows the channel is alive.
  Server-initiated notifications (e.g. ``notifications/tools/list_changed``)
  can be pushed here later; v1 does only keepalives.

Auth + audit security model summarized:
  - 401 + ``WWW-Authenticate: Bearer`` on missing/bad token
  - 403 ``insufficient_scope`` on scope mismatch
  - Every tool call appended to ``log/mcp.jsonl`` with ts, jti,
    client_id, tool, scope, params_hash, duration_ms, outcome, ip
  - Per-token rate limit (60/min reads, 5/min writes — Phase 3 sets a
    single conservative cap, refines per-scope in a follow-up)
  - Pre-write Telegram notification when configured (best-effort)

Under the gthread worker (opt-in through ``OPENALGO_WORKER_CLASS``) every
request holds one thread from a fixed pool, where the default eventlet worker
spends only a greenlet. Three things here therefore behave differently under
gthread, and only there (``utils.runtime.gthread_active()``):

  - A ``GET /mcp`` stream is counted and capped (:data:`MCP_SSE_MAX_STREAMS`),
    and ends after :data:`MCP_SSE_MAX_SECONDS`; the client reconnects.
  - Tool calls in flight are capped (:func:`_tool_call_limit`). A call over the
    cap is refused before anything is sent, with ``retry_safe`` true.
  - The SDK client the tools use is served by this app on the calling thread
    (:class:`_InProcessWsgi`) instead of an HTTP loopback, so a tool call never
    needs a second pool thread to answer it and cannot wait on its own queue.

Under eventlet and on the development server none of this applies and the
tools reach ``/api/v1/`` over HTTP exactly as before.

See ``docs/prd/remote-mcp.md`` for the full design.
"""

from __future__ import annotations

import collections
import contextvars
import hashlib
import json
import os
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from flask import Blueprint, Response, jsonify, request, stream_with_context

from limiter import limiter
from utils import runtime, stream_registry
from utils.logging import get_logger
from utils.oauth_tokens import AccessTokenError, claims_have_scope, verify_access_token

logger = get_logger(__name__)


mcp_http_bp = Blueprint("mcp_http_bp", __name__, url_prefix="/mcp")


@mcp_http_bp.after_request
def _mcp_after_request(response: Response) -> Response:
    """Apply CORS allowlist to every response from this blueprint.

    Hosted MCP clients (claude.ai, chatgpt.com) reach /mcp from a
    different origin. Without these headers their browsers block the
    response. The mismatched-origin path returns no headers, so the
    browser refuses — which is what we want.
    """
    return _apply_cors(response, request.headers.get("Origin"))


# Keepalive cadence for the SSE stream. SSE comment lines (starting with
# ":") are NOT delivered to the client app but keep the TCP socket warm.
_SSE_KEEPALIVE_SECONDS = 15

# The GET stream's budget under the gthread worker. Module constants rather
# than settings: they exist only to keep a keepalive-only stream from holding
# threads the order path needs, and nothing a trader configures depends on them.
#
#: Streams open at once. The stream pushes nothing but keepalives, so one per
#: connected client is plenty and a handful covers several clients.
MCP_SSE_MAX_STREAMS = 4
#: Seconds a stream stays open before it ends cleanly and the client reconnects,
#: so a half-open connection (a laptop asleep, a NAT that dropped it) cannot
#: hold a thread for longer than this.
MCP_SSE_MAX_SECONDS = 300
#: Reconnect delay advertised on a stream with a lifetime, in milliseconds (the
#: SSE ``retry`` field).
MCP_SSE_RETRY_MS = 30_000
#: The stream_registry kind every GET stream is counted under.
_SSE_STREAM_KIND = "mcp_sse"
#: What a client over the stream cap is told.
SSE_BUSY_MESSAGE = (
    "OpenAlgo is already holding as many MCP event streams as it allows. Try again in a moment."
)

# Tool calls in flight under the gthread worker: one call per this many worker
# threads, and never fewer than two, so MCP cannot take more than a small share
# of the pool however many calls a client fires in parallel.
_TOOL_CALL_THREAD_SHARE = 8
_TOOL_CALL_MIN_LIMIT = 2
#: The cap when the gthread worker's thread count is not known.
_TOOL_CALL_FALLBACK_LIMIT = 8
#: The reason sent with a call refused for being over the cap.
TOOL_CALLS_BUSY_MESSAGE = (
    "OpenAlgo is busy with other requests, so this call was not run and nothing "
    "was sent. Try again in a few seconds."
)


# Per-token rate limits, configurable via env. Defaults match the PRD:
# 60/min for read scopes, 5/min for write scope. The keying function
# below extracts the JTI from the bearer token so a single token can't
# exceed its quota by hopping IPs.
_RATE_LIMIT_READ = os.getenv("MCP_RATE_LIMIT_READ", "60 per minute")
_RATE_LIMIT_WRITE = os.getenv("MCP_RATE_LIMIT_WRITE", "50 per minute")
# A coarser ceiling on the dispatcher itself, applied per JTI/IP so a
# single token can't fire reads at unlimited speed even before scope
# enforcement happens.
_DISPATCH_RATE_LIMIT = "120 per minute"
_SSE_RATE_LIMIT = "5 per minute"


# CORS allowlist — read at module load. Empty list means no Origin is
# advertised back; hosted clients (claude.ai, chatgpt.com) need to be
# in this list for browser-side OAuth flows to work.
def _cors_allowed_origins() -> list[str]:
    # Default to the two hosted clients we ship support for. An operator
    # who wants to lock this down can set MCP_HTTP_CORS_ORIGINS=""
    # (empty) to disable browser-side OAuth flows entirely, or supply a
    # narrower list. The native enabler doesn't write this key, so the
    # default has to be sane on its own.
    default = "https://claude.ai,https://chatgpt.com"
    raw = os.getenv("MCP_HTTP_CORS_ORIGINS", default)
    return [o.strip() for o in raw.split(",") if o.strip()]


def _parse_rate_spec(spec: str) -> tuple[int, int]:
    """Parse a 'N per minute' / 'N per hour' / 'N per second' spec.

    Returns (count, window_seconds). Defaults to 60/min on a parse
    failure so misconfiguration fails closed enough to be visible.
    """
    parts = (spec or "").lower().replace("per ", "per_").split()
    try:
        count = int(parts[0])
    except (ValueError, IndexError):
        return (60, 60)
    unit = parts[-1] if len(parts) > 1 else "per_minute"
    return {
        "per_second": (count, 1),
        "per_minute": (count, 60),
        "per_hour": (count, 3600),
    }.get(unit, (count, 60))


# In-memory sliding window per (jti, scope). The prune, the test and the
# append happen in one hold of _scope_quota_lock: under the gthread worker two
# calls on one token run truly in parallel, and without the lock both could
# pass the test before either appended, admitting one call over the quota.
# A plain threading.Lock: only request handlers touch it (green under
# eventlet, real under gthread) and it guards in-memory work only.
#
# Access tokens live fifteen minutes, so a new jti arrives all day in a worker
# that never restarts. Every _QUOTA_SWEEP_SECONDS the whole dict is swept for
# buckets whose newest hit is older than the longest window, which bounds it
# by the tokens active in that window.
_scope_quota: dict[str, collections.deque] = {}
_scope_quota_lock = threading.Lock()
_QUOTA_SWEEP_SECONDS = 300.0
_last_quota_sweep = 0.0


def _longest_quota_window() -> int:
    """The longest window either quota counts over, in seconds."""
    return max(_parse_rate_spec(_RATE_LIMIT_READ)[1], _parse_rate_spec(_RATE_LIMIT_WRITE)[1])


def _sweep_scope_quota_locked(now: float) -> None:
    """Drop buckets no call can still count against. Call with the lock held."""
    global _last_quota_sweep

    if now - _last_quota_sweep < _QUOTA_SWEEP_SECONDS:
        return
    _last_quota_sweep = now
    horizon = now - _longest_quota_window()
    stale = [key for key, bucket in _scope_quota.items() if not bucket or bucket[-1] < horizon]
    for key in stale:
        del _scope_quota[key]


def _within_scope_quota(*, jti: str | None, scope: str) -> bool:
    """True if (jti, scope) is below its configured per-window quota.

    The dispatcher-level Flask-Limiter still applies — this is a
    second, tighter check specifically for the write scope.
    """
    if not jti:
        return False
    spec = _RATE_LIMIT_WRITE if "write:" in scope else _RATE_LIMIT_READ
    count, window = _parse_rate_spec(spec)
    now = time.time()
    cutoff = now - window
    key = f"{jti}|{scope}"
    with _scope_quota_lock:
        _sweep_scope_quota_locked(now)
        bucket = _scope_quota.get(key)
        if bucket is None:
            bucket = collections.deque()
            _scope_quota[key] = bucket
        # Drop expired hits.
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= count:
            return False
        bucket.append(now)
        return True


# Tool calls in flight, counted in every runtime and capped only under the
# gthread worker. A plain threading.Lock guarding one integer, touched only by
# request handlers.
_tool_calls_lock = threading.Lock()
_tool_calls_open = 0


def _tool_call_limit() -> int | None:
    """The most tool calls allowed in flight, or None for no limit.

    None under eventlet and on the development server, where a waiting call
    costs a greenlet or an unpooled thread. Under gthread each call holds a
    pool thread for as long as its broker round trip takes, so the cap is a
    share of the configured thread count.
    """
    if not runtime.gthread_active():
        return None
    threads = runtime.configured_threads()
    if not threads:
        return _TOOL_CALL_FALLBACK_LIMIT
    return max(_TOOL_CALL_MIN_LIMIT, threads // _TOOL_CALL_THREAD_SHARE)


def _claim_tool_call() -> bool:
    """Count one tool call in, unless the limit is already reached."""
    global _tool_calls_open

    limit = _tool_call_limit()
    with _tool_calls_lock:
        if limit is not None and _tool_calls_open >= limit:
            return False
        _tool_calls_open += 1
        return True


def _release_tool_call() -> None:
    """Count one tool call out. Called exactly once per successful claim."""
    global _tool_calls_open

    with _tool_calls_lock:
        _tool_calls_open = max(0, _tool_calls_open - 1)


def tool_calls_in_flight() -> int:
    """How many MCP tool calls are running right now, for diagnostics."""
    with _tool_calls_lock:
        return _tool_calls_open


def _apply_cors(response: Response, origin: str | None) -> Response:
    """Add CORS headers if the request origin is on the allowlist.

    Mismatches return without CORS headers — the browser will then
    refuse the response, which is the desired behavior. We never
    leak the allowlist on a mismatch.
    """
    if not origin:
        return response
    if origin in _cors_allowed_origins():
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = (
            "Authorization, Content-Type, X-Requested-With"
        )
        # Browser-side OAuth clients need to read the discovery hint
        # from the 401 response. Without this header the WWW-Authenticate
        # value is hidden by CORS and the client reports "no OAuth".
        response.headers["Access-Control-Expose-Headers"] = "WWW-Authenticate, Link, Content-Type"
        response.headers["Access-Control-Max-Age"] = "600"
        response.headers["Vary"] = "Origin"
    return response


# Audit log path. Same directory as the rest of the structured logs so
# operators have one place to look. The directory always exists at this
# point — utils/logging.py already created it.
_AUDIT_PATH = Path(os.getenv("LOG_DIR", "log")) / "mcp.jsonl"

# Bound the audit log so a chatty MCP client can't fill the disk. We
# rotate at the same shape as utils/logging.py's errors.jsonl: keep the
# last N lines on every write. 5000 is generous for human inspection
# without blowing past a few MB.
_AUDIT_MAX_LINES = 5000

# The file size past which a write also trims the log to _AUDIT_MAX_LINES.
_AUDIT_TRIM_BYTES = 2_000_000

# One append-then-trim at a time. Under the gthread worker file I/O releases
# the GIL, so without this an append landing between a trim's read and its
# rewrite was lost, and one landing during the rewrite was torn. A plain
# threading.Lock: only request handlers write the audit log, and under
# eventlet the blocking file I/O never yields, so it is never contended there.
_audit_lock = threading.Lock()


# Rate limit choice for v1: a single conservative per-token cap. The
# existing Flask-Limiter is keyed by IP by default — we override with
# the JTI claim once verified, so a noisy client on one IP can't
# starve other clients on the same NAT.
def _rate_limit_key() -> str:
    """Use the JWT jti as the rate-limit key when available, else the IP."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(None, 1)[1].strip()
        try:
            claims = verify_access_token(token)
            jti = claims.get("jti")
            if jti:
                return f"jti:{jti}"
        except Exception:
            pass
    return request.remote_addr or "unknown"


# Pre-flight: HTTP transport refuses to register without a configured
# api_key + loopback host. The init runs once per process, on the first
# /mcp request (app.py only registers the blueprint).
_initialized = False

# Makes that first-request init single-flight. A hosted client typically sends
# initialize, tools/list and a GET close together, and each used to run the
# whole init: two module objects, two SDK clients (one of them leaked), and a
# third request that saw the flag set before init_for_http had run got no
# client at all. A plain threading.Lock, deliberately not a real one: under
# eventlet the holder yields during the database lookup and the module load,
# and a second greenlet must wait cooperatively.
_init_lock = threading.Lock()


class _InProcessWsgi:
    """Serve an SDK request with this app, on the calling thread, as its own request.

    Under the gthread worker a tool call runs on a pool thread, and the SDK
    client it uses would otherwise call back into ``/api/v1/`` over HTTP, which
    needs a second pool thread to answer. With the pool busy the tool's thread
    waits on a request queued behind it until the SDK gives up. Handing the
    SDK an ``httpx.WSGITransport`` over this class runs that request here
    instead: the same WSGI stack (traffic log, security middleware, routing,
    API-key check, rate limits) and the same response, with no second thread
    and no network.

    Each request runs in an empty ``contextvars`` context, so Flask pushes a
    fresh application context for it exactly as it would for a request from
    outside, rather than sharing the tool call's ``g``. Its teardown releases
    the scoped sessions on this thread; the tool call does no database work of
    its own after the SDK returns, only its audit line, which is a file.

    The body is read in full, and the app's iterable closed, inside that
    context: the ``/api/v1/`` endpoints the SDK calls all answer with a single
    JSON body.
    """

    def __init__(self, app: Any) -> None:
        self._app = app

    def __call__(self, environ: dict, start_response: Any) -> list[bytes]:
        return contextvars.Context().run(self._serve, environ, start_response)

    def _serve(self, environ: dict, start_response: Any) -> list[bytes]:
        result = self._app(environ, start_response)
        try:
            return [b"".join(result)]
        finally:
            close = getattr(result, "close", None)
            if close is not None:
                close()


def _serve_sdk_in_process(mcp_module: Any) -> None:
    """Point the tools' SDK client at this app instead of the HTTP loopback.

    Called only under the gthread worker; see :class:`_InProcessWsgi`. Needs
    the app, so it is skipped (and the loopback kept) when called outside an
    application context, and it replaces only an SDK whose HTTP client has the
    shape this was written against.

    Args:
        mcp_module: The loaded ``mcp/mcpserver.py`` module, after
            ``init_for_http`` has built its client.
    """
    from flask import current_app, has_app_context

    sdk = getattr(mcp_module, "client", None)
    previous = getattr(sdk, "client", None)
    if not has_app_context() or not isinstance(previous, httpx.Client):
        logger.info("[MCP HTTP] tool calls use the HTTP loopback")
        return
    app = current_app._get_current_object()
    sdk.client = httpx.Client(
        transport=httpx.WSGITransport(app=_InProcessWsgi(app)),
        timeout=getattr(sdk, "timeout", 120.0),
    )
    try:
        previous.close()
    except Exception:
        logger.exception("[MCP HTTP] could not close the replaced SDK client")
    logger.info("[MCP HTTP] tool calls are served in process by this worker")


def init_http_transport() -> None:
    """Wire the SDK client used by the @mcp.tool() functions.

    Runs once per process, on the first request to this blueprint; every
    route calls it and every call after the first returns at once. Looks up
    the admin's existing OpenAlgo API key (stored in db/openalgo.db)
    and points the SDK at the local loopback so tool calls go through
    the existing /api/v1/* surface — same code path as the SDK uses
    everywhere else. Under the gthread worker that surface is reached in
    process rather than over HTTP (:func:`_serve_sdk_in_process`).
    """
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        _init_http_transport_locked()


def _init_http_transport_locked() -> None:
    """The body of :func:`init_http_transport`. Call only under ``_init_lock``.

    ``_initialized`` is set last, once the SDK client exists, so a request that
    sees it set never finds the tools without a client.
    """
    global _initialized

    # Make the legacy stdio module skip its argv check when the HTTP
    # transport boots it. MUST be set BEFORE loading mcp/mcpserver.py.
    os.environ["OPENALGO_MCP_HTTP_BOOT"] = "1"

    # The local ``mcp/`` directory is not a Python package (no
    # ``__init__.py``) — adding one would shadow the pip-installed
    # ``mcp`` package that FastMCP itself comes from. We bypass the
    # collision by loading ``mcp/mcpserver.py`` directly through
    # importlib in tool_registry, then reuse that loader here.
    from utils.mcp_tool_registry import _load_mcpserver_module, audit_registry

    mcp_module = _load_mcpserver_module()
    if mcp_module is None:
        logger.error("[MCP HTTP] failed to load mcp/mcpserver.py")
        _initialized = True
        return

    # Look up the admin's API key. get_first_available_api_key() returns
    # the decrypted plaintext used by the SDK; falls back to None when
    # no key is set, in which case tool calls will fail with the SDK's
    # usual "invalid apikey" — better than booting with a fake key.
    from database.auth_db import get_first_available_api_key

    api_key = get_first_available_api_key()
    # Loopback target the bundled openalgo SDK uses to call back into
    # /api/v1/*. Resolution order:
    #   1. MCP_LOOPBACK_URL — explicit override for unusual topologies.
    #   2. HOST_SERVER — set by every official install script
    #      (install.sh, install-docker.sh, ...). On native installs
    #      gunicorn binds to a Unix socket, so the public HTTPS URL
    #      via nginx is the only loopback that actually answers.
    #   3. http://127.0.0.1:{FLASK_PORT} — dev server / Docker port-
    #      mapped install fallback.
    loopback = (os.getenv("MCP_LOOPBACK_URL") or "").strip()
    if not loopback:
        loopback = (os.getenv("HOST_SERVER") or "").strip()
    if not loopback:
        flask_port = os.getenv("FLASK_PORT") or os.getenv("PORT") or "5000"
        loopback = f"http://127.0.0.1:{flask_port}"
    host = loopback.rstrip("/")

    if api_key is None:
        logger.warning(
            "[MCP HTTP] No OpenAlgo API key found in db/openalgo.db. "
            "Tool calls will fail until the admin creates an API key. "
            "Visit /apikey to generate one."
        )
        # Still init with a placeholder so the FastMCP instance exists
        # — list_tools etc. work without account access.
        api_key = "<not-configured>"

    mcp_module.init_for_http(api_key, host)
    if runtime.gthread_active():
        _serve_sdk_in_process(mcp_module)
    audit_registry()  # warns about scope/annotation drift
    _initialized = True
    logger.info(
        f"[MCP HTTP] transport initialized; loopback={host}, "
        f"key={'configured' if api_key != '<not-configured>' else 'MISSING'}"
    )

    # The tool surface is env-configurable, so record what this boot
    # actually exposes. Without it a narrowed server looks identical to
    # a broken one in the logs.
    active = getattr(mcp_module, "ACTIVE_TOOL_NAMES", ())
    total = len(getattr(mcp_module, "TOOL_META", {}) or {})
    logger.info(
        f"[MCP HTTP] tools exposed: {len(active)}/{total}; "
        f"toolsets={sorted(getattr(mcp_module, 'ACTIVE_TOOLSETS', ()))}; "
        f"read_only={getattr(mcp_module, 'READ_ONLY', False)}; "
        f"trust_envelope={getattr(mcp_module, 'TRUST_ENVELOPE_ENABLED', True)}"
    )
    unknown = getattr(mcp_module, "UNKNOWN_TOOLSETS", ())
    if unknown:
        logger.warning(
            f"[MCP HTTP] OPENALGO_MCP_TOOLSETS contains unknown names: {list(unknown)}. "
            "They were ignored. Check for a typo before assuming a tool is disabled."
        )


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------


def _bearer_or_none() -> str | None:
    """Extract the Bearer token from the Authorization header.

    Resilient to malformed values: a header of exactly ``Bearer`` (or
    ``Bearer `` with no token) returns ``None`` rather than raising
    ``IndexError``. Anything else with a non-empty token is returned
    after stripping surrounding whitespace.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    parts = auth.split(None, 1)
    if len(parts) != 2:
        return None
    token = parts[1].strip()
    return token or None


def _resource_metadata_url() -> str:
    """Pointer used in WWW-Authenticate to advertise OAuth resource metadata."""
    base = (os.getenv("MCP_PUBLIC_URL") or "").rstrip("/")
    return f"{base}/.well-known/oauth-protected-resource"


def _unauthorized(error_code: str, description: str = "") -> Response:
    """RFC 6750 §3 — 401 with WWW-Authenticate Bearer challenge."""
    challenge = f'Bearer realm="openalgo-mcp", error="{error_code}"'
    if description:
        challenge += f', error_description="{description}"'
    challenge += f', resource_metadata="{_resource_metadata_url()}"'
    resp = jsonify({"error": error_code, "error_description": description})
    resp.status_code = 401 if error_code == "invalid_token" else 403
    if error_code == "insufficient_scope":
        resp.status_code = 403
    resp.headers["WWW-Authenticate"] = challenge
    return resp


def _jsonrpc_error(rpc_id: Any, code: int, message: str, data: Any = None) -> Response:
    """JSON-RPC 2.0 error response."""
    body: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "error": {"code": code, "message": message},
    }
    if data is not None:
        body["error"]["data"] = data
    return jsonify(body)


def _jsonrpc_result(rpc_id: Any, result: Any) -> Response:
    return jsonify({"jsonrpc": "2.0", "id": rpc_id, "result": result})


def _params_hash(params: Any) -> str:
    """Deterministic short hash of the call args for audit correlation."""
    try:
        canonical = json.dumps(params, sort_keys=True, default=str)
    except (TypeError, ValueError):
        canonical = repr(params)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _audit_log(entry: dict[str, Any]) -> None:
    """Append a single line to log/mcp.jsonl. Best-effort."""
    try:
        line = json.dumps(entry, default=str) + "\n"
        with _audit_lock:
            path = _AUDIT_PATH
            path.parent.mkdir(exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
            _trim_audit_log_locked(path)
    except Exception as e:
        # Don't let an audit-log failure break the request. Log to the
        # central logger so the operator at least sees the failure.
        logger.exception(f"[MCP audit] failed to write entry: {e}")


def _trim_audit_log_locked(path: Path) -> None:
    """Keep the last _AUDIT_MAX_LINES lines once the file passes _AUDIT_TRIM_BYTES.

    Call with ``_audit_lock`` held. Cheap rotation: linear in the file size,
    but a 5000-line file is small enough that this is unmeasurable next to a
    broker call. The kept lines are written to a temporary file beside the log
    and moved over it, so a crash mid-trim leaves the old log whole rather than
    truncated. Windows refuses to replace a file another process has open, and
    there the log is rewritten in place instead, which is what it always was.

    Args:
        path: The audit log.
    """
    try:
        if path.stat().st_size <= _AUDIT_TRIM_BYTES:
            return
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) <= _AUDIT_MAX_LINES:
            return
        kept = "\n".join(lines[-_AUDIT_MAX_LINES:]) + "\n"
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".mcp-audit-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                tmp.write(kept)
            try:
                os.replace(tmp_name, path)
            except PermissionError:
                path.write_text(kept, encoding="utf-8")
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
    except OSError:
        pass


def _notify_pre_write(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    client_id: str,
    jti: str | None,
) -> None:
    """Surface a write-scope tool call to the admin BEFORE it fires.

    v1 emits a WARNING-level log line — the existing JSON error log
    handler captures every WARNING+ to ``log/errors.jsonl`` and the
    Diagnostics page surfaces them prominently with grouping. A future
    follow-up wires Telegram alerts on top of this same hook by
    listening for a specific marker in the log line.

    The message is intentionally short — full argument detail is in
    ``log/mcp.jsonl`` keyed by jti.
    """
    preview = json.dumps(arguments, default=str)[:200]
    logger.warning(
        f"[MCP write tool] PRE-EXECUTION client={client_id} jti={jti} "
        f"tool={tool_name} args={preview}"
    )


# --------------------------------------------------------------------
# JSON-RPC dispatcher (POST /mcp)
# --------------------------------------------------------------------


@mcp_http_bp.route("", methods=["OPTIONS"], strict_slashes=False)
def mcp_preflight():
    """CORS preflight handler. Returns 204 with allow headers when the
    Origin is on the MCP_HTTP_CORS_ORIGINS allowlist, 403 otherwise."""
    origin = request.headers.get("Origin")
    response = Response(status=204)
    return _apply_cors(response, origin)


@mcp_http_bp.route("", methods=["POST"], strict_slashes=False)
@limiter.limit(_DISPATCH_RATE_LIMIT, key_func=_rate_limit_key)
def mcp_dispatch():
    """JSON-RPC 2.0 endpoint for MCP."""
    init_http_transport()  # idempotent

    # ---- Bearer token check ----
    token_str = _bearer_or_none()
    if not token_str:
        return _unauthorized("invalid_token", "Missing Bearer token.")
    try:
        claims = verify_access_token(token_str)
    except AccessTokenError as e:
        return _unauthorized(str(e), "")

    granted_scopes = (claims.get("scope") or "").split()
    client_id = claims.get("client_id") or "unknown"
    jti = claims.get("jti")

    # ---- JSON-RPC envelope parse ----
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _jsonrpc_error(None, -32700, "Parse error: body must be a JSON object.")

    if body.get("jsonrpc") != "2.0":
        return _jsonrpc_error(body.get("id"), -32600, "Invalid Request: jsonrpc must be 2.0.")

    rpc_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}

    if method == "initialize":
        # MCP handshake. We advertise tools capability; nothing else
        # for v1.
        return _jsonrpc_result(
            rpc_id,
            {
                "protocolVersion": "2025-06-18",
                "serverInfo": {"name": "openalgo", "version": _openalgo_version()},
                "capabilities": {"tools": {"listChanged": False}},
            },
        )

    if method == "ping":
        return _jsonrpc_result(rpc_id, {})

    if method == "tools/list":
        from utils.mcp_tool_registry import list_tools_for_scopes

        names = list_tools_for_scopes(granted_scopes)
        tools = [_tool_descriptor(n) for n in names]
        return _jsonrpc_result(rpc_id, {"tools": tools})

    if method == "tools/call":
        return _dispatch_tool_call(
            rpc_id=rpc_id,
            params=params,
            granted_scopes=granted_scopes,
            client_id=client_id,
            jti=jti,
        )

    return _jsonrpc_error(rpc_id, -32601, f"Method not found: {method}")


def _openalgo_version() -> str:
    try:
        from utils.version import get_version

        return get_version()
    except Exception:
        return "unknown"


def _docstring_summary(name: str) -> str:
    """First line of the tool's docstring."""
    try:
        from utils.mcp_tool_registry import _load_mcpserver_module

        mod = _load_mcpserver_module()
        fn = getattr(mod, name, None) if mod else None
        if fn and fn.__doc__:
            return fn.__doc__.strip().splitlines()[0]
    except Exception:
        pass
    return ""


def _tool_descriptor(name: str) -> dict[str, Any]:
    """Build a full MCP tool descriptor: name, description, JSON-Schema.

    Pulls the input schema FastMCP generated from the function's type
    hints. Without this, MCP clients (ChatGPT) have to guess parameter
    names — which is how we ended up with calls using ``product_type``
    instead of the actual ``product`` parameter.
    """
    descriptor: dict[str, Any] = {
        "name": name,
        "description": _docstring_summary(name) or name,
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": True},
    }

    try:
        from utils.mcp_tool_registry import _load_mcpserver_module

        mod = _load_mcpserver_module()
        if mod is None:
            return descriptor
        tool_manager = getattr(getattr(mod, "mcp", None), "_tool_manager", None)
        if tool_manager is None:
            return descriptor
        tools_dict = getattr(tool_manager, "_tools", None)
        if not isinstance(tools_dict, dict):
            return descriptor
        tool = tools_dict.get(name)
        if tool is None:
            return descriptor
        # FastMCP stores the JSON schema under .parameters (Pydantic-built)
        params = getattr(tool, "parameters", None)
        if isinstance(params, dict) and params.get("type") == "object":
            descriptor["inputSchema"] = params
        # Use the full FastMCP description if available — usually richer
        # than the docstring summary because it includes Args block.
        full_desc = getattr(tool, "description", None)
        if isinstance(full_desc, str) and full_desc.strip():
            descriptor["description"] = full_desc.strip()
        # Annotations (readOnlyHint / destructiveHint / ...) let a client
        # tell "read the order book" apart from "cancel every order"
        # before prompting the user to approve. Without this, remote
        # clients would see every tool as equally risky while stdio
        # clients get the hints.
        annotations = getattr(tool, "annotations", None)
        if annotations is not None:
            dump = getattr(annotations, "model_dump", None)
            if callable(dump):
                hints = {k: v for k, v in dump().items() if v is not None}
                if hints:
                    descriptor["annotations"] = hints
    except Exception as e:  # never block tools/list on a metadata bug
        logger.warning(f"[MCP tools/list] failed to build descriptor for {name}: {e}")

    return descriptor


def _dispatch_tool_call(
    *,
    rpc_id: Any,
    params: dict,
    granted_scopes: list[str],
    client_id: str,
    jti: str | None,
):
    """Handle a tools/call request. Validates scope, runs the tool,
    captures the result, audits, returns JSON-RPC."""
    from utils.mcp_tool_registry import get_tool_callable, required_scope

    # JSON-RPC 2.0 allows ``params`` to be an object OR an array; we
    # only accept object form. Reject anything else with -32602 instead
    # of letting ``.get`` raise AttributeError on a list/string/int.
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return _jsonrpc_error(rpc_id, -32602, "Invalid params: must be an object.")
    tool_name = params.get("name")
    arguments = params.get("arguments") or {}

    if not tool_name or not isinstance(tool_name, str):
        return _jsonrpc_error(rpc_id, -32602, "Invalid params: 'name' is required.")
    if not isinstance(arguments, dict):
        return _jsonrpc_error(rpc_id, -32602, "Invalid params: 'arguments' must be an object.")

    needed = required_scope(tool_name)
    if needed is None:
        return _jsonrpc_error(rpc_id, -32601, f"Unknown tool: {tool_name}")
    if not claims_have_scope({"scope": " ".join(granted_scopes)}, needed):
        # Don't leak the required scope value back to the client beyond
        # the WWW-Authenticate challenge — fold it into the JSON-RPC
        # error data block for clients that look there.
        return _jsonrpc_error(rpc_id, -32000, "insufficient_scope", data={"required_scope": needed})

    fn = get_tool_callable(tool_name)
    if fn is None:
        return _jsonrpc_error(rpc_id, -32601, f"Tool not implemented: {tool_name}")

    # The in-flight cap, which only the gthread worker enforces. Checked before
    # the quota so a refused call does not use up the token's budget, and
    # before the pre-write notice so nothing reports an order that never ran.
    if not _claim_tool_call():
        _audit_log(
            {
                "ts": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                "jti": jti,
                "client_id": client_id,
                "tool": tool_name,
                "scope": needed,
                "params_hash": _params_hash(arguments),
                "duration_ms": 0,
                "outcome": "busy",
                "request_ip": request.remote_addr,
            }
        )
        return _jsonrpc_error(
            rpc_id,
            -32000,
            "server_busy",
            data={"reason": TOOL_CALLS_BUSY_MESSAGE, "retry_safe": True},
        )
    try:
        return _run_tool_call(
            rpc_id=rpc_id,
            fn=fn,
            tool_name=tool_name,
            arguments=arguments,
            needed=needed,
            client_id=client_id,
            jti=jti,
        )
    finally:
        _release_tool_call()


def _run_tool_call(
    *,
    rpc_id: Any,
    fn: Any,
    tool_name: str,
    arguments: dict[str, Any],
    needed: str,
    client_id: str,
    jti: str | None,
):
    """Check the quota, run one tool and audit it. Holds a tool-call slot."""
    from utils.mcp_tool_registry import SCOPE_WRITE_ORDERS

    # Per-token-per-scope rate limit (security review finding C-2).
    # The dispatcher-level @limiter.limit on mcp_dispatch caps the
    # gross rate per JTI; this adds a tighter cap specifically on
    # write:orders so a stolen write token can't spam orders inside
    # its 15-minute TTL window. Values configurable via
    # MCP_RATE_LIMIT_READ / MCP_RATE_LIMIT_WRITE.
    if not _within_scope_quota(jti=jti, scope=needed):
        return _jsonrpc_error(
            rpc_id,
            -32000,
            "rate_limited",
            data={
                "scope": needed,
                "limit": _RATE_LIMIT_WRITE if needed == SCOPE_WRITE_ORDERS else _RATE_LIMIT_READ,
            },
        )

    # Pre-write notification — fires BEFORE the broker call so the
    # admin sees the impending write even if the call later succeeds.
    if needed == SCOPE_WRITE_ORDERS:
        _notify_pre_write(
            tool_name=tool_name,
            arguments=arguments,
            client_id=client_id,
            jti=jti,
        )

    started = time.perf_counter()
    outcome = "success"
    try:
        result_text = fn(**arguments)  # tools accept kwargs only
    except TypeError:
        outcome = "bad_arguments"
        result_text = None
    except Exception as e:
        # Any tool-internal failure is logged but not leaked verbatim.
        outcome = "error"
        logger.exception(f"[MCP tool] {tool_name} raised: {e}")
        result_text = None
    duration_ms = int((time.perf_counter() - started) * 1000)

    _audit_log(
        {
            "ts": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "jti": jti,
            "client_id": client_id,
            "tool": tool_name,
            "scope": needed,
            "params_hash": _params_hash(arguments),
            "duration_ms": duration_ms,
            "outcome": outcome,
            "request_ip": request.remote_addr,
        }
    )

    if outcome != "success":
        # Do NOT echo the exception back to the client: it can carry SQL
        # error messages, internal paths, or function-signature reveals
        # (security review finding H-4). The full detail is in the
        # audit log + log/errors.jsonl for the admin to triage. We
        # surface only a coarse outcome category to the client.
        client_message = {
            "bad_arguments": "Invalid arguments. Check the tool schema.",
            "error": "Tool execution failed. See server audit log.",
        }.get(outcome, "Tool execution failed.")
        return _jsonrpc_error(rpc_id, -32603, "tool_error", data={"reason": client_message})

    # MCP content blocks per spec — tools return a string per OpenAlgo
    # convention (_to_json wraps SDK responses).
    return _jsonrpc_result(
        rpc_id,
        {"content": [{"type": "text", "text": result_text}], "isError": False},
    )


# --------------------------------------------------------------------
# SSE event stream (GET /mcp)
# --------------------------------------------------------------------


@mcp_http_bp.route("", methods=["GET"], strict_slashes=False)
@limiter.limit(_SSE_RATE_LIMIT, key_func=_rate_limit_key)
def mcp_sse():
    """Server-Sent Events stream. Sends keepalive comments every 15s.

    The MCP streamable-HTTP transport uses this channel for server-
    initiated messages. v1 keeps the channel open for spec compliance
    but does not push notifications. Validation runs on every
    connection — a stale token gets disconnected.

    Every stream is counted in ``utils.stream_registry`` under
    ``mcp_sse``. Under the gthread worker each one holds a pool thread, so
    there, and only there, at most :data:`MCP_SSE_MAX_STREAMS` are open at
    once (a client over the cap gets 429 with ``Retry-After``), and each
    ends cleanly after :data:`MCP_SSE_MAX_SECONDS`, having told the client
    through the SSE ``retry`` field how long to wait before reconnecting.
    Under eventlet and on the development server a stream stays open until
    the client leaves, as it always has. In every runtime a stream ends when
    the server begins shutting down.
    """
    init_http_transport()

    token_str = _bearer_or_none()
    if not token_str:
        return _unauthorized("invalid_token", "Missing Bearer token.")
    try:
        verify_access_token(token_str)
    except AccessTokenError as e:
        return _unauthorized(str(e), "")

    ticket = stream_registry.admit(
        _SSE_STREAM_KIND, stream_registry.enforced_limit(MCP_SSE_MAX_STREAMS)
    )
    if ticket is None:
        busy = Response(SSE_BUSY_MESSAGE, status=429, mimetype="text/plain")
        busy.headers["Retry-After"] = str(MCP_SSE_RETRY_MS // 1000)
        return busy
    lifetime = MCP_SSE_MAX_SECONDS if runtime.gthread_active() else None

    def gen():
        try:
            # Initial comment so the client knows the stream is live. A stream
            # that will end by itself first says how long to wait before
            # reconnecting, so the reconnect does not arrive at once.
            if lifetime is not None:
                yield f"retry: {MCP_SSE_RETRY_MS}\n: openalgo-mcp connected\n\n"
            else:
                yield ": openalgo-mcp connected\n\n"
            started = last_keepalive = time.monotonic()
            # Loop until the client disconnects, the lifetime runs out, or the
            # server shuts down. One second per pass, as before; wait_stop's
            # sleep is time.sleep, eventlet's cooperative one under that worker.
            while True:
                now = time.monotonic()
                step = 1.0
                if lifetime is not None:
                    left = lifetime - (now - started)
                    if left <= 0:
                        return
                    step = min(step, left)
                if now - last_keepalive >= _SSE_KEEPALIVE_SECONDS:
                    yield ": keepalive\n\n"
                    last_keepalive = now
                if stream_registry.wait_stop(step, poll=step):
                    return
        finally:
            ticket.release()

    response = Response(stream_with_context(gen()), mimetype="text/event-stream")
    # Also released here: a client that leaves before the first byte closes a
    # generator that never started, so its finally never runs.
    response.call_on_close(ticket.release)
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"  # nginx — disable buffering
    response.headers["Connection"] = "keep-alive"
    return response


# --------------------------------------------------------------------
# Health probe — same /mcp path with /healthz suffix, NOT auth-gated
# --------------------------------------------------------------------


@mcp_http_bp.route("/healthz", methods=["GET"])
def healthz():
    """Liveness probe for nginx / monitors. No auth; returns minimal info."""
    return jsonify({"status": "ok", "service": "openalgo-mcp"}), 200


@mcp_http_bp.route("/.well-known/oauth-protected-resource", methods=["GET"])
def mcp_resource_metadata_alias():
    """Path-relative discovery alias for ``/mcp/.well-known/oauth-protected-resource``.

    Some MCP client implementations (notably ChatGPT) follow the
    convention of fetching ``<resource_url>/.well-known/oauth-protected-resource``
    rather than the host-root form. Without this alias the request
    falls through to the React SPA fallback and returns HTML, which
    the client interprets as "this server does not implement OAuth".
    """
    from blueprints.mcp_oauth import _build_protected_resource_metadata

    return _build_protected_resource_metadata()
