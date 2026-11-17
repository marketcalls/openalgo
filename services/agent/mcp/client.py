"""A small synchronous MCP client for the streamable-HTTP transport.

Why not the ``mcp`` SDK or agno's ``MCPTools``
----------------------------------------------

Both are asyncio. Production runs eventlet by default, and eventlet cannot host
``asyncio.run()`` or an event loop in request code (CLAUDE.md, "No asyncio in
request code"). The transport itself is plain: JSON-RPC 2.0 over HTTP POST,
answered with a JSON body or a short ``text/event-stream``. Four methods cover
everything the agent needs (``initialize``, ``notifications/initialized``,
``tools/list``, ``tools/call``), so this module speaks them directly.

Where the bytes go out
----------------------

Every request goes through the shared ``utils.httpx_client`` client, handed to
the hub with ``utils.real_threading.run_on_hub``. Agent tools run on a real OS
thread, and that client's connection pool locks were built after eventlet
patched the standard library, so they are green: a real thread contending on
one is blocked for good (``services/agent/chatgpt_oauth.py`` documents the same
crossing). Under the gthread worker and the development server ``run_on_hub``
simply calls inline. The only thing that crosses back is a plain
:class:`_Reply` of status, headers and decoded text.

Failure handling
----------------

The NSE gateways this was first built against answered the same request in 0.3
seconds, with a 504 after 10, or not at all for 40, from one minute to the next,
and were removed from the registry for it. A server can behave that way, so:

* every request carries the spec's own connect and read timeouts, and one tool
  call is bounded by ``call_deadline_s`` across its retry and any session
  re-initialisation;
* a timeout, a transport error or a 5xx is retried at most ``max_retries``
  times, and only while the deadline still has room for it;
* a per-server **circuit breaker** pauses a server after
  ``breaker_threshold`` consecutive failed operations, answers "unavailable" at
  once for ``breaker_cooldown_s``, then lets one call through to test it;
* the tool list is cached for ``tools_cache_ttl_s`` and a failed fetch is
  remembered for ``negative_cache_ttl_s``.

Errors are typed (:class:`McpUnreachable`, :class:`McpTimedOut`,
:class:`McpToolError`, :class:`McpProtocolError`) and each carries a sentence a
trader can read. Status codes and protocol detail go to the log only.

Resources
---------

No thread, no client and no socket is created here. Module state is one
:class:`McpClient` per registered server, built lazily and bounded by
:data:`~services.agent.mcp.registry.MCP_SERVERS`, and each client's caches are
``LockedTTLCache`` instances of size one. Locks are real
(``utils.real_threading``) because the agent's real thread and a green request
handler (the settings page's connection test) both touch this state; every
critical section is in-memory bookkeeping and no I/O happens under one.
"""

from __future__ import annotations

import copy
import itertools
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from services.agent.mcp.registry import McpServerSpec, registered_servers, server_by_key
from utils import real_threading
from utils.logging import get_logger
from utils.thread_safe_cache import LockedTTLCache

logger = get_logger(__name__)

__all__ = [
    "PROTOCOL_VERSION",
    "McpBusy",
    "McpCircuitOpen",
    "McpClient",
    "McpError",
    "McpProtocolError",
    "McpTimedOut",
    "McpToolError",
    "McpUnreachable",
    "ServerCheck",
    "ToolResult",
    "check_servers",
    "get_client",
    "reset_clients",
]

#: The protocol revision announced in ``initialize``. Servers answer with the
#: revision they will speak; servers seen so far echo this one.
PROTOCOL_VERSION = "2025-06-18"

_JSONRPC = "2.0"

#: Extra seconds the agent's thread waits for the hub beyond the request's own
#: timeouts, so httpx's timeout fires first and is reported as what it is.
_HUB_SLACK_S = 5.0

#: Ceiling on a response body this client will parse. A tool result larger than
#: this is not something the toolkit could hand the model anyway.
MAX_RESPONSE_CHARS = 2_000_000

#: JSON-RPC error codes that mean the request named a bad tool or bad
#: arguments, which the model can fix, rather than a broken server.
_ARGUMENT_ERROR_CODES = frozenset({-32602, -32601})


def _user_agent() -> str:
    """The User-Agent sent on every request, naming the platform and version."""
    try:
        from utils.version import get_version

        return f"OpenAlgo-Agent/{get_version()}"
    except Exception:
        return "OpenAlgo-Agent"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class McpError(Exception):
    """Base class for every failure this client reports.

    ``str(exc)`` is the trader-facing sentence: the cause in plain words and
    what to do next. ``detail`` is for the log and never shown.

    Attributes:
        code: Stable short code the toolkit puts in its result.
        server: Key of the server the failure belongs to.
        detail: Technical detail for the log.
    """

    code = "mcp_error"

    def __init__(self, message: str, *, server: str = "", detail: str = "") -> None:
        super().__init__(message)
        self.server = server
        self.detail = detail


class McpUnreachable(McpError):
    """The server could not be reached or answered with a server-side error."""

    code = "unavailable"


class McpCircuitOpen(McpUnreachable):
    """The server failed repeatedly and is paused for a cooldown.

    Attributes:
        retry_after_s: Seconds until the next call is let through.
    """

    code = "paused"

    def __init__(self, message: str, *, server: str = "", retry_after_s: float = 0.0) -> None:
        super().__init__(message, server=server, detail="circuit open")
        self.retry_after_s = max(0.0, float(retry_after_s))


class McpTimedOut(McpError):
    """The server accepted the connection but did not answer in time."""

    code = "timed_out"


class McpBusy(McpError):
    """This platform's own web server could not take the request in time."""

    code = "busy"


class McpToolError(McpError):
    """The server ran the tool and reported a failure, or refused its arguments.

    Attributes:
        text: The server's own message. Third-party text: the toolkit wraps it
            as untrusted before the model reads it.
    """

    code = "tool_error"

    def __init__(self, message: str, *, server: str = "", text: str = "") -> None:
        super().__init__(message, server=server, detail="tool reported an error")
        self.text = text


class McpProtocolError(McpError):
    """The server answered with something this client cannot use.

    Attributes:
        status: The HTTP status when the server refused the request outright,
            else 0.
    """

    code = "protocol_error"

    def __init__(
        self, message: str, *, server: str = "", detail: str = "", status: int = 0
    ) -> None:
        super().__init__(message, server=server, detail=detail)
        self.status = status

    @property
    def is_refusal(self) -> bool:
        """True for a 4xx other than 404, such as a firewall's 403.

        A 404 is excluded because it is how a server says a session expired,
        which the client answers by initialising again.
        """
        return 400 <= self.status < 500 and self.status != 404


class _SessionExpired(Exception):
    """Internal: the server no longer knows the session id we sent."""


class _InFlightTimeout(TimeoutError):
    """Internal: the hub wait ran out after the request had been sent.

    The hub took the request, so this platform was not the bottleneck: the
    server kept the request open past every allowance.
    """


class _Retryable(Exception):
    """Internal: a failure worth one more attempt (timeout, transport, 5xx)."""

    def __init__(self, error: McpError) -> None:
        super().__init__(str(error))
        self.error = error


# ---------------------------------------------------------------------------
# Wire helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Reply:
    """What crosses back from the hub: plain data, never an httpx object.

    Attributes:
        status: HTTP status code.
        headers: Response headers, names lower-cased.
        text: The body decoded as UTF-8.
    """

    status: int
    headers: Mapping[str, str]
    text: str


#: ``post(url, headers, body, timeout) -> _Reply``. Injected in tests.
PostFn = Callable[[str, Mapping[str, str], bytes, httpx.Timeout], _Reply]


def _shared_post(
    url: str, headers: Mapping[str, str], body: bytes, timeout: httpx.Timeout
) -> _Reply:
    """Send one POST on the shared client, from the world that owns it.

    Args:
        url: The server endpoint.
        headers: Request headers.
        body: The JSON-RPC message, already encoded as UTF-8.
        timeout: httpx timeout for this request.

    Returns:
        A :class:`_Reply`.

    Raises:
        httpx.TimeoutException: The request timed out.
        httpx.TransportError: The connection failed.
        _InFlightTimeout: The hub wait ran out with the request already sent.
        TimeoutError: The hub never started the call in time.
        real_threading.HubQueueFull: The hub had too much waiting.
    """
    # Set on the hub once the request starts, read here after a timed-out
    # wait. A single flag write, so no lock is needed across the two worlds.
    started: dict[str, bool] = {}

    def send() -> _Reply:
        from utils.httpx_client import get_httpx_client

        started["sent"] = True

        response = get_httpx_client().post(
            url, content=body, headers=dict(headers), timeout=timeout
        )
        # Decoded explicitly as UTF-8. Tool descriptions carry the rupee sign,
        # and a text/event-stream with no charset must not fall back to a
        # guessed encoding.
        text = response.content.decode("utf-8", errors="replace")
        return _Reply(
            status=response.status_code,
            headers={name.lower(): value for name, value in response.headers.items()},
            text=text,
        )

    wait = float(timeout.connect or 0) + 2 * float(timeout.read or 0) + _HUB_SLACK_S
    try:
        return real_threading.run_on_hub(send, timeout=wait)
    except TimeoutError as exc:
        if started.get("sent"):
            raise _InFlightTimeout(str(exc)) from None
        raise


def parse_sse(text: str) -> list[Any]:
    """Parse a ``text/event-stream`` body into the JSON messages it carries.

    Events are separated by a blank line; each event's ``data:`` lines are
    joined with newlines, as the SSE specification says. Comments, ``event:``
    and ``id:`` lines are ignored, and an event whose data is not JSON is
    skipped rather than failing the whole body.

    Args:
        text: The response body.

    Returns:
        The decoded messages in order.
    """
    messages: list[Any] = []
    data: list[str] = []

    def flush() -> None:
        if not data:
            return
        joined = "\n".join(data)
        data.clear()
        try:
            messages.append(json.loads(joined))
        except ValueError:
            logger.debug("Skipped a non-JSON server-sent event")

    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if not line:
            flush()
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            value = line[5:]
            data.append(value[1:] if value.startswith(" ") else value)
    flush()
    return messages


def _pick_response(messages: list[Any], request_id: int) -> Mapping[str, Any] | None:
    """Find the JSON-RPC response to one request among a stream of messages.

    A stream may carry server notifications or requests before the response,
    and a JSON body may be a batch. The response is the message with our id;
    failing that, the last message carrying a result or an error.

    Args:
        messages: Decoded messages.
        request_id: The id we sent.

    Returns:
        The response object, or None when none is present.
    """
    flat: list[Mapping[str, Any]] = []
    for message in messages:
        if isinstance(message, list):
            flat.extend(item for item in message if isinstance(item, Mapping))
        elif isinstance(message, Mapping):
            flat.append(message)
    for message in flat:
        if message.get("id") == request_id and ("result" in message or "error" in message):
            return message
    for message in reversed(flat):
        if "result" in message or "error" in message:
            return message
    return None


@dataclass(frozen=True)
class ToolResult:
    """The outcome of one successful ``tools/call``.

    Attributes:
        text: The text content items joined with newlines. Non-text items are
            named in place, since the model cannot read an image through JSON.
        structured: ``structuredContent`` when the server sent one.
        elapsed_ms: Wall-clock time of the call, re-initialisation included.
    """

    text: str
    structured: Any = None
    elapsed_ms: int = 0


@dataclass(frozen=True)
class ServerCheck:
    """The result of one connection test.

    Attributes:
        key: Server key.
        title: Server title.
        ok: True when the server initialised and listed its tools.
        latency_ms: Wall-clock time of the test.
        tool_count: Tools offered after the allowlist and denylist.
        message: A sentence for the settings page.
        server_name: The name the server reported, when it answered.
    """

    key: str
    title: str
    ok: bool
    latency_ms: int
    tool_count: int = 0
    message: str = ""
    server_name: str = ""

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe form for a route."""
        return {
            "key": self.key,
            "title": self.title,
            "ok": self.ok,
            "latency_ms": self.latency_ms,
            "tool_count": self.tool_count,
            "message": self.message,
            "server_name": self.server_name,
        }


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------


@dataclass
class _Breaker:
    """Per-server circuit breaker state. Read and written under the client lock.

    Attributes:
        failures: Consecutive failed operations.
        open_until: Monotonic time before which calls are refused.
        probing: True while one half-open trial call is in flight.
    """

    failures: int = 0
    open_until: float = 0.0
    probing: bool = False


@dataclass
class _Session:
    """Per-server session state. Read and written under the client lock."""

    session_id: str | None = None
    initialized: bool = False
    server_name: str = ""


class McpClient:
    """A synchronous client for one MCP server.

    Safe to share between threads: every piece of mutable state is read and
    written under one real lock held only for in-memory bookkeeping.

    Args:
        spec: The server.
        post: Transport function. Defaults to the shared client on the hub.
        clock: Monotonic clock, injectable for tests of the breaker and caches.
    """

    def __init__(
        self,
        spec: McpServerSpec,
        *,
        post: PostFn | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.spec = spec
        self._post: PostFn = post or _shared_post
        self._clock = clock
        self._lock = real_threading.Lock()
        self._breaker = _Breaker()
        self._session = _Session()
        self._ids = itertools.count(1)
        self._tools: LockedTTLCache = LockedTTLCache(
            maxsize=1, ttl=spec.tools_cache_ttl_s, timer=clock
        )
        self._tools_failure: LockedTTLCache = LockedTTLCache(
            maxsize=1, ttl=spec.negative_cache_ttl_s, timer=clock
        )

    # -- public ---------------------------------------------------------------

    def list_tools(self, *, refresh: bool = False) -> tuple[dict[str, Any], ...]:
        """The server's tools, after the spec's allowlist and denylist.

        Args:
            refresh: Bypass the cache and the remembered failure.

        Returns:
            Each tool as the server described it (``name``, ``description``,
            ``inputSchema``), in server order.

        Raises:
            McpError: Any subclass. A failure is remembered for
                ``negative_cache_ttl_s`` and raised again from memory.
        """
        if not refresh:
            cached = self._tools.get("tools")
            if cached is not None:
                return cached
            remembered = self._tools_failure.get("error")
            if remembered is not None:
                # A fresh traceback each time: re-raising the stored instance
                # as-is would chain every raise onto the last one for the TTL.
                raise remembered.with_traceback(None)

        generation = self._tools.generation
        try:
            result = self._operation("tools/list", {}, force=refresh)
        except McpError as exc:
            # A copy without a traceback, so the remembered error does not keep
            # the failed request's frames (and the reply they hold) alive.
            self._tools_failure["error"] = copy.copy(exc).with_traceback(None)
            raise

        raw = result.get("tools") if isinstance(result, Mapping) else None
        if not isinstance(raw, list):
            error = self._protocol_error("listed its tools in a shape this platform cannot read")
            self._tools_failure["error"] = error
            raise error

        tools: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            name = item.get("name")
            if not isinstance(name, str) or not name or not self.spec.offers(name):
                continue
            tools.append(dict(item))
        snapshot = tuple(tools)
        self._tools.fill("tools", snapshot, generation)
        self._tools_failure.invalidate()
        return snapshot

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> ToolResult:
        """Call one tool.

        Args:
            name: The tool name, already checked against :meth:`list_tools`.
            arguments: The arguments, passed through as the model wrote them.

        Returns:
            A :class:`ToolResult`.

        Raises:
            McpToolError: The server reported the tool failed, or refused the
                tool name or its arguments.
            McpError: Any other subclass for a transport or protocol failure.
        """
        if not self.spec.offers(name):
            raise McpToolError(
                f"The tool {name} is not offered from {self.spec.title}.", server=self.spec.key
            )
        started = self._clock()
        result = self._operation("tools/call", {"name": name, "arguments": dict(arguments)})
        if not isinstance(result, Mapping):
            raise self._protocol_error("answered a tool call in a shape this platform cannot read")

        text = _content_text(result.get("content"))
        elapsed_ms = int((self._clock() - started) * 1000)
        if result.get("isError") is True:
            raise McpToolError(
                f"{self.spec.title} could not answer that request.",
                server=self.spec.key,
                text=text,
            )
        return ToolResult(
            text=text, structured=result.get("structuredContent"), elapsed_ms=elapsed_ms
        )

    def check(self) -> ServerCheck:
        """Test the connection: initialise afresh and list the tools.

        Ignores the breaker and the caches, because the operator pressed a
        button asking whether the server answers now. A pass closes the breaker
        and refreshes the cached tool list.

        Returns:
            A :class:`ServerCheck`. Never raises.
        """
        started = self._clock()
        with self._lock:
            self._session = _Session()
        try:
            tools = self.list_tools(refresh=True)
        except McpError as exc:
            return ServerCheck(
                key=self.spec.key,
                title=self.spec.title,
                ok=False,
                latency_ms=int((self._clock() - started) * 1000),
                message=str(exc),
            )
        with self._lock:
            server_name = self._session.server_name
        return ServerCheck(
            key=self.spec.key,
            title=self.spec.title,
            ok=True,
            latency_ms=int((self._clock() - started) * 1000),
            tool_count=len(tools),
            message=f"{self.spec.title} answered and offers {len(tools)} tools.",
            server_name=server_name,
        )

    def breaker_snapshot(self) -> dict[str, Any]:
        """The breaker's state, for diagnostics and tests.

        Returns:
            ``{"failures", "open", "retry_after_s"}``.
        """
        now = self._clock()
        with self._lock:
            failures = self._breaker.failures
            open_until = self._breaker.open_until
        return {
            "failures": failures,
            "open": open_until > now,
            "retry_after_s": max(0.0, open_until - now),
        }

    # -- breaker --------------------------------------------------------------

    def _admit(self, force: bool) -> bool:
        """Decide whether an operation may go out now.

        Args:
            force: True for an operator's connection test, which always goes.

        Returns:
            True when this operation is the half-open trial.

        Raises:
            McpCircuitOpen: The server is paused, or its trial is in flight.
        """
        now = self._clock()
        with self._lock:
            breaker = self._breaker
            if force or breaker.failures < self.spec.breaker_threshold:
                return False
            if now < breaker.open_until or breaker.probing:
                retry_after = max(breaker.open_until - now, 1.0)
            else:
                breaker.probing = True
                return True
        raise McpCircuitOpen(
            f"{self.spec.title} has not been answering, so it is paused for about "
            f"{int(retry_after) + 1} seconds. {self._side()} Try again after that.",
            server=self.spec.key,
            retry_after_s=retry_after,
        )

    def _settle(self, ok: bool, trial: bool) -> None:
        """Record an operation's outcome on the breaker.

        Args:
            ok: True when the server answered (a tool error still counts as an
                answer).
            trial: True when this was the half-open trial.
        """
        now = self._clock()
        with self._lock:
            breaker = self._breaker
            if trial:
                breaker.probing = False
            if ok:
                breaker.failures = 0
                breaker.open_until = 0.0
                return
            breaker.failures += 1
            opened = breaker.failures >= self.spec.breaker_threshold
            if opened:
                breaker.open_until = now + self.spec.breaker_cooldown_s
        if opened:
            logger.warning(
                "MCP server %s paused for %.0fs after %d consecutive failures",
                self.spec.key,
                self.spec.breaker_cooldown_s,
                self.spec.breaker_threshold,
            )

    # -- operations -------------------------------------------------------------

    def _operation(self, method: str, params: Mapping[str, Any], *, force: bool = False) -> Any:
        """Run one request inside a session, under the breaker and the deadline.

        Args:
            method: ``tools/list`` or ``tools/call``.
            params: The method's params.
            force: Bypass the breaker (the connection test).

        Returns:
            The JSON-RPC ``result``.

        Raises:
            McpError: Any subclass.
        """
        trial = self._admit(force)
        deadline = self._clock() + self.spec.call_deadline_s
        started = self._clock()
        try:
            result = self._in_session(method, params, deadline)
        except McpBusy:
            # This platform's hub could not send the request, so the server was
            # never asked. Neither an answer nor an outage: free the trial slot
            # and leave the count alone.
            if trial:
                with self._lock:
                    self._breaker.probing = False
            raise
        except McpError as exc:
            # A tool error or an unreadable answer still means the server is up,
            # so neither pauses it. A refusal at the door (a firewall's 403, for
            # example) answers every call the same way, so it counts as a failure.
            outage = isinstance(exc, (McpUnreachable, McpTimedOut)) or (
                isinstance(exc, McpProtocolError) and exc.is_refusal
            )
            self._settle(not outage, trial)
            if outage:
                logger.warning(
                    "MCP %s %s failed after %d ms: %s",
                    self.spec.key,
                    method,
                    int((self._clock() - started) * 1000),
                    exc.detail or exc.code,
                )
            raise
        except BaseException:
            if trial:
                with self._lock:
                    self._breaker.probing = False
            raise
        self._settle(True, trial)
        logger.info(
            "MCP %s %s answered in %d ms",
            self.spec.key,
            method,
            int((self._clock() - started) * 1000),
        )
        return result

    def _in_session(self, method: str, params: Mapping[str, Any], deadline: float) -> Any:
        """Send a request, initialising first and once more if the session expired."""
        for attempt in range(2):
            session_id = self._ensure_session(deadline)
            try:
                return self._rpc(method, params, session_id, deadline)
            except _SessionExpired:
                with self._lock:
                    if self._session.session_id == session_id:
                        self._session = _Session()
                if attempt == 0:
                    logger.info("MCP %s session expired; initialising again", self.spec.key)
                    continue
                raise self._protocol_error(
                    "kept refusing a fresh session", detail="session expired twice"
                ) from None
        raise self._protocol_error("could not hold a session")  # pragma: no cover

    def _ensure_session(self, deadline: float) -> str | None:
        """Return the live session id, running ``initialize`` when there is none."""
        with self._lock:
            if self._session.initialized:
                return self._session.session_id

        request_id = next(self._ids)
        reply = self._send(
            {
                "jsonrpc": _JSONRPC,
                "id": request_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "openalgo-agent", "version": _user_agent()},
                },
            },
            None,
            deadline,
        )
        if reply.status == 404:
            raise self._protocol_error("refused to start a session", detail="initialize 404")
        message = self._decode(reply, request_id)
        result = self._result_of(message, "initialize")
        session_id = reply.headers.get("mcp-session-id") or None

        server_info = result.get("serverInfo") if isinstance(result, Mapping) else None

        # The spec requires this notification before any other request. A
        # server that answers it with an error has still given us a session,
        # so its status is not checked; a transport failure still raises.
        self._send(
            {"jsonrpc": _JSONRPC, "method": "notifications/initialized"}, session_id, deadline
        )

        with self._lock:
            self._session = _Session(
                session_id=session_id,
                initialized=True,
                server_name=str((server_info or {}).get("name") or ""),
            )
        return session_id

    def _rpc(
        self, method: str, params: Mapping[str, Any], session_id: str | None, deadline: float
    ) -> Any:
        """Send one request inside an established session and return its result.

        Raises:
            _SessionExpired: The server answered 404 to our session id.
            McpError: Any subclass.
        """
        request_id = next(self._ids)
        reply = self._send(
            {"jsonrpc": _JSONRPC, "id": request_id, "method": method, "params": dict(params)},
            session_id,
            deadline,
        )
        if session_id and (
            reply.status == 404 or (reply.status == 400 and "session" in reply.text[:500].lower())
        ):
            raise _SessionExpired()
        message = self._decode(reply, request_id)
        return self._result_of(message, method)

    def _send(self, payload: Mapping[str, Any], session_id: str | None, deadline: float) -> _Reply:
        """POST one message, retrying a timeout, transport error or 5xx once.

        Args:
            payload: The JSON-RPC message.
            session_id: The session header to send, if any.
            deadline: Monotonic time the whole operation must finish by.

        Returns:
            The reply, whose status is below 500.

        Raises:
            McpError: The last failure once attempts or time ran out.
        """
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": _user_agent(),
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if session_id:
            headers["Mcp-Session-Id"] = session_id

        attempts = 1 + self.spec.max_retries
        last: McpError | None = None
        for attempt in range(attempts):
            remaining = deadline - self._clock()
            # A retry that cannot even connect inside the deadline only adds
            # waiting to a failure that is already certain.
            if attempt and remaining < self.spec.connect_timeout_s + 1.0:
                break
            if remaining <= 0:
                break
            timeout = httpx.Timeout(
                min(self.spec.read_timeout_s, remaining),
                connect=min(self.spec.connect_timeout_s, remaining),
            )
            try:
                return self._attempt(body, headers, timeout)
            except _Retryable as retry:
                last = retry.error
                if attempt + 1 < attempts:
                    logger.info(
                        "MCP %s attempt %d failed (%s); retrying",
                        self.spec.key,
                        attempt + 1,
                        last.detail or last.code,
                    )
        raise last or self._timed_out("deadline reached before the request was sent")

    def _attempt(self, body: bytes, headers: Mapping[str, str], timeout: httpx.Timeout) -> _Reply:
        """One HTTP attempt, with every failure translated.

        Raises:
            _Retryable: Timeout, transport error or 5xx.
            McpTimedOut: The hub wait ran out with the request in flight. Not
                retried, because that request may still be running on the hub.
            McpBusy: This platform's web server could not take the request.
            McpUnreachable: A 429, which is not retried.
        """
        try:
            reply = self._post(self.spec.url, headers, body, timeout)
        except httpx.TimeoutException as exc:
            raise _Retryable(self._timed_out(type(exc).__name__)) from None
        except httpx.TransportError as exc:
            raise _Retryable(self._unreachable(type(exc).__name__)) from None
        except real_threading.HubQueueFull:
            raise self._busy("hub queue full") from None
        except _InFlightTimeout:
            raise self._timed_out("hub wait ran out with the request in flight") from None
        except TimeoutError:
            raise self._busy("hub never started the request") from None

        if reply.status >= 500:
            raise _Retryable(self._unreachable(f"HTTP {reply.status}"))
        if reply.status == 429:
            raise McpUnreachable(
                f"{self.spec.title} asked this platform to slow down. Wait a minute and try again.",
                server=self.spec.key,
                detail="HTTP 429",
            )
        return reply

    # -- decoding ---------------------------------------------------------------

    def _decode(self, reply: _Reply, request_id: int) -> Mapping[str, Any]:
        """Turn a reply into the JSON-RPC response to ``request_id``.

        Raises:
            McpProtocolError: A 4xx, an unreadable body, or no response in it.
        """
        if reply.status >= 400:
            raise self._protocol_error(
                "refused the request",
                detail=f"HTTP {reply.status}: {reply.text[:200]!r}",
                status=reply.status,
            )
        if len(reply.text) > MAX_RESPONSE_CHARS:
            raise self._protocol_error(
                "sent a reply too large to use", detail=f"{len(reply.text)} chars"
            )
        content_type = reply.headers.get("content-type", "").lower()
        try:
            if "text/event-stream" in content_type:
                messages = parse_sse(reply.text)
            else:
                messages = [json.loads(reply.text)] if reply.text.strip() else []
        except ValueError:
            raise self._protocol_error(
                "sent a reply that is not readable data", detail=f"bad JSON ({content_type})"
            ) from None
        message = _pick_response(messages, request_id)
        if message is None:
            raise self._protocol_error("sent no answer to the request", detail="no response")
        return message

    def _result_of(self, message: Mapping[str, Any], method: str) -> Any:
        """Return a response's ``result``, or raise its ``error`` as a typed one.

        Raises:
            McpToolError: A ``tools/call`` error the model can fix.
            McpProtocolError: Any other JSON-RPC error.
        """
        error = message.get("error")
        if error is None:
            return message.get("result")
        code = error.get("code") if isinstance(error, Mapping) else None
        text = str(error.get("message") if isinstance(error, Mapping) else error or "")[:1000]
        if method == "tools/call" and code in _ARGUMENT_ERROR_CODES:
            raise McpToolError(
                f"{self.spec.title} refused that tool name or its arguments.",
                server=self.spec.key,
                text=text,
            )
        raise self._protocol_error(
            "returned an error", detail=f"{method} JSON-RPC error {code}: {text[:200]!r}"
        )

    # -- error construction ---------------------------------------------------

    def _side(self) -> str:
        """The sentence that places an outage with whoever runs the server."""
        owner = f"{self.spec.provider}'s" if self.spec.provider else "the service's"
        return f"The fault is on {owner} side, not in your setup."

    def _unreachable(self, detail: str) -> McpUnreachable:
        return McpUnreachable(
            f"{self.spec.title} is not answering right now. {self._side()} Try again in a "
            "minute or two.",
            server=self.spec.key,
            detail=detail,
        )

    def _timed_out(self, detail: str) -> McpTimedOut:
        return McpTimedOut(
            f"{self.spec.title} took too long to answer. {self._side()} Try again in a "
            "minute or two.",
            server=self.spec.key,
            detail=detail,
        )

    def _busy(self, detail: str) -> McpBusy:
        return McpBusy(
            "This platform's web server was too busy to send the request. Nothing was "
            "changed; try again in a moment.",
            server=self.spec.key,
            detail=detail,
        )

    def _protocol_error(self, what: str, *, detail: str = "", status: int = 0) -> McpProtocolError:
        return McpProtocolError(
            f"{self.spec.title} {what}. The service may have changed; if this keeps "
            "happening, report it so the integration can be updated.",
            server=self.spec.key,
            detail=detail or what,
            status=status,
        )


def _content_text(content: Any) -> str:
    """Join a ``tools/call`` result's content items into text.

    Args:
        content: ``result.content``, a list of typed items.

    Returns:
        The text items joined with newlines; other item types named in place.
    """
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, Mapping):
            continue
        kind = item.get("type")
        if kind == "text":
            parts.append(str(item.get("text") or ""))
        elif kind == "resource":
            resource = item.get("resource")
            if isinstance(resource, Mapping) and isinstance(resource.get("text"), str):
                parts.append(resource["text"])
            else:
                parts.append("[a binary resource was omitted]")
        elif kind:
            parts.append(f"[{kind} content was omitted]")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Module state: one client per registered server
# ---------------------------------------------------------------------------

_clients_lock = real_threading.Lock()
_clients: dict[str, McpClient] = {}


def get_client(key: str) -> McpClient | None:
    """The shared client for one registered server, built on first use.

    Bounded by the registry: a key that names no server builds nothing.

    Args:
        key: The server key.

    Returns:
        The client, or None for an unknown key.
    """
    spec = server_by_key(key)
    if spec is None:
        return None
    with _clients_lock:
        client = _clients.get(spec.key)
        if client is None or client.spec is not spec:
            client = McpClient(spec)
            _clients[spec.key] = client
        return client


def reset_clients() -> None:
    """Drop every client, and with it every session, breaker and cache. For tests."""
    with _clients_lock:
        _clients.clear()


def check_servers(keys: list[str] | tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    """Test the connection to registered servers, one after another.

    Each test initialises a fresh session and lists the tools, bypassing the
    breaker and the caches. Sequential on purpose: two requests to the same
    gateway at once prove nothing more than one.

    Args:
        keys: Servers to test. None tests every registered server.

    Returns:
        One :meth:`ServerCheck.as_dict` per server, in registry order. Never
        raises.
    """
    wanted = None if keys is None else {str(key).strip().lower() for key in keys}
    results: list[dict[str, Any]] = []
    for spec in registered_servers():
        if wanted is not None and spec.key not in wanted:
            continue
        client = get_client(spec.key)
        if client is None:  # pragma: no cover - the spec came from the registry
            continue
        try:
            check = client.check()
        except Exception:
            logger.exception("MCP connection test for %s raised", spec.key)
            check = ServerCheck(
                key=spec.key,
                title=spec.title,
                ok=False,
                latency_ms=0,
                message=f"The test for {spec.title} could not be run. Try again in a moment.",
            )
        level = logger.info if check.ok else logger.warning
        level(
            "MCP connection test %s: ok=%s latency_ms=%d tools=%d",
            spec.key,
            check.ok,
            check.latency_ms,
            check.tool_count,
        )
        results.append(check.as_dict())
    return results
