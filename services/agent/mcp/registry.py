"""The external data servers the agent may reach over MCP.

Adding a server
---------------

Adding a server is **one entry** in :data:`MCP_SERVERS`. The toolkit, the
prompt section, the settings page and the connection test all read this tuple,
so nothing else changes::

    McpServerSpec(
        key="bse_eod",
        title="BSE end-of-day data",
        url="https://example.invalid/bse/mcp",
        description="Daily BSE prices and corporate filings.",
        use_for="BSE daily history and filings the broker does not carry.",
    ),

The key is what the model passes as ``server``, so keep it short, lower case and
stable: renaming one breaks every conversation that learned the old name.

What a spec does not carry
--------------------------

No credential. A server that needs a key should get one through ``ag_secret``
and the settings page the way web search does, never through a header written
into this file. No per-tool argument rules
either: the server's own ``inputSchema`` is the contract, read live and cached.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from services.agent.tools import ALL_SURFACES

__all__ = [
    "MCP_SERVERS",
    "TRANSPORT_STREAMABLE_HTTP",
    "McpServerSpec",
    "server_by_key",
    "servers_for_surface",
]

#: The one transport implemented: JSON-RPC 2.0 over HTTP POST, answered with a
#: JSON body or a short ``text/event-stream``. The older HTTP+SSE transport and
#: stdio are deliberately absent: the first is deprecated by the spec, and the
#: second would start a subprocess per server inside a worker that never
#: restarts.
TRANSPORT_STREAMABLE_HTTP = "streamable-http"

_TRANSPORTS = frozenset({TRANSPORT_STREAMABLE_HTTP})

_KEY_PATTERN = re.compile(r"\A[a-z][a-z0-9_]{1,31}\Z")


@dataclass(frozen=True)
class McpServerSpec:
    """One external MCP server.

    Attributes:
        key: Stable identifier the model passes as ``server``. Lower case,
            letters, digits and underscores.
        title: Short name a trader reads on the settings page and in an error.
        url: The server's streamable-HTTP endpoint. Must be ``https``.
        description: One or two sentences for the settings page.
        use_for: What the model should reach for this server for, written into
            the prompt section. One sentence; the prompt budget is shared.
        caveats: Data limits the model must state or respect, also written into
            the prompt section. Empty when there are none.
        provider: Who runs the server, named in a failure message so a trader
            knows the fault is not in their own setup. For example ``NSE``.
        transport: Only :data:`TRANSPORT_STREAMABLE_HTTP` today.
        connect_timeout_s: Seconds to wait for a connection.
        read_timeout_s: Seconds to wait for each read once connected.
        call_deadline_s: Wall-clock budget for one tool call, including a
            session re-initialisation and the retry. A retry is not attempted
            when it could not finish inside this.
        max_retries: Extra attempts after a timeout or a 5xx. One at most is
            sensible: a gateway that failed twice is not answering this minute.
        breaker_threshold: Consecutive failed calls that pause the server.
        breaker_cooldown_s: Seconds a paused server is answered "unavailable"
            without being called.
        tools_cache_ttl_s: Seconds the server's tool list is cached.
        negative_cache_ttl_s: Seconds a failed tool-list fetch is remembered, so
            a model asking again straight away is answered at once.
        allow_tools: When non-empty, the only tools offered from this server.
        deny_tools: Tools never offered from this server.
        surfaces: Surfaces this server is offered on.
    """

    key: str
    title: str
    url: str
    description: str
    use_for: str
    caveats: str = ""
    provider: str = ""
    transport: str = TRANSPORT_STREAMABLE_HTTP
    connect_timeout_s: float = 5.0
    read_timeout_s: float = 10.0
    call_deadline_s: float = 25.0
    max_retries: int = 1
    breaker_threshold: int = 3
    breaker_cooldown_s: float = 60.0
    tools_cache_ttl_s: float = 3600.0
    negative_cache_ttl_s: float = 30.0
    allow_tools: frozenset[str] = frozenset()
    deny_tools: frozenset[str] = frozenset()
    surfaces: frozenset[str] = field(default=ALL_SURFACES)

    def __post_init__(self) -> None:
        """Reject a spec that would fail at call time instead of at import.

        Raises:
            ValueError: A malformed key, a URL that is not https, an unknown
                transport, a non-positive timeout, or a tool both allowed and
                denied.
        """
        if not _KEY_PATTERN.match(self.key or ""):
            raise ValueError(
                f"MCP server key {self.key!r} must be 2 to 32 lower-case letters, digits or "
                "underscores, starting with a letter"
            )
        parts = urlsplit(self.url or "")
        if parts.scheme != "https" or not parts.netloc:
            raise ValueError(f"MCP server {self.key!r} needs an https URL, got {self.url!r}")
        if self.transport not in _TRANSPORTS:
            raise ValueError(f"MCP server {self.key!r} uses unknown transport {self.transport!r}")
        for name in (
            "connect_timeout_s",
            "read_timeout_s",
            "call_deadline_s",
            "breaker_cooldown_s",
            "tools_cache_ttl_s",
            "negative_cache_ttl_s",
        ):
            if not float(getattr(self, name)) > 0:
                raise ValueError(f"MCP server {self.key!r}: {name} must be positive")
        if self.max_retries < 0 or self.breaker_threshold < 1:
            raise ValueError(
                f"MCP server {self.key!r}: max_retries must be >= 0 and breaker_threshold >= 1"
            )
        object.__setattr__(self, "allow_tools", frozenset(self.allow_tools))
        object.__setattr__(self, "deny_tools", frozenset(self.deny_tools))
        object.__setattr__(self, "surfaces", frozenset(self.surfaces))
        overlap = self.allow_tools & self.deny_tools
        if overlap:
            raise ValueError(
                f"MCP server {self.key!r} both allows and denies: {', '.join(sorted(overlap))}"
            )
        if not self.surfaces:
            raise ValueError(f"MCP server {self.key!r} names no surface")

    def offers(self, tool: str) -> bool:
        """Whether this server's allowlist and denylist let a tool through.

        Args:
            tool: The tool name as the server lists it.

        Returns:
            True when the tool may be listed and called.
        """
        if tool in self.deny_tools:
            return False
        return not self.allow_tools or tool in self.allow_tools


#: Every server the agent may reach. One entry per server; see the module
#: docstring. Order is the order the prompt and the settings page list them.
#:
#: Empty today. NSE's two MCP servers (end-of-day bhavcopy and the live
#: cash-market snapshot) were the first entries and were removed on 2026-10-09:
#: in repeated live checks both stalled for 10 to 20 seconds and then timed out,
#: so every NSE question cost the trader a long wait for no answer. With nothing
#: registered the toolkit is not built and the prompt says nothing about it.
MCP_SERVERS: tuple[McpServerSpec, ...] = ()


def registered_servers() -> tuple[McpServerSpec, ...]:
    """Every registered server, read at call time.

    Consumers call this rather than importing :data:`MCP_SERVERS`, so the
    registry is read where it is used and a test can swap it in one place.

    Returns:
        The registered servers, in registry order.
    """
    return MCP_SERVERS


def server_by_key(key: str) -> McpServerSpec | None:
    """Find a registered server by its key.

    Args:
        key: The key as the model or a route sent it. Matched case-insensitively
            after trimming, because a model writing ``NSE_EOD`` meant the same
            server.

    Returns:
        The spec, or None when no server has that key.
    """
    wanted = str(key or "").strip().lower()
    for spec in MCP_SERVERS:
        if spec.key == wanted:
            return spec
    return None


def servers_for_surface(surface: str) -> tuple[McpServerSpec, ...]:
    """The servers offered on one surface, in registry order.

    Args:
        surface: ``chat``, ``chart`` or ``voice``.

    Returns:
        The matching specs. Empty for an unknown surface.
    """
    name = str(surface or "").strip().lower()
    return tuple(spec for spec in MCP_SERVERS if name in spec.surfaces)
