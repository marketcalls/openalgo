"""Tool registry shim shared by stdio and HTTP transports.

stdio (legacy):
    The Claude Desktop / Cursor / Windsurf integration runs
    ``python mcp/mcpserver.py KEY HOST`` directly. FastMCP picks up
    ``@mcp.tool()`` decorators at import time and dispatches via stdio.

HTTP / SSE (new):
    ``blueprints/mcp_http.py`` imports this module after setting
    ``OPENALGO_MCP_HTTP_BOOT=1``. We expose:

    * ``TOOL_SCOPES`` — explicit map of tool_name → required OAuth scope.
      Maintained here (not derived from FastMCP) so security review can
      audit one place.
    * ``required_scope(name)`` — getter, returns ``None`` for unknown tools
    * ``list_tools_for_scopes(scopes)`` — filtered tool list for the
      ``tools/list`` JSON-RPC method
    * ``get_tool_callable(name)`` — resolves the underlying Python
      function so the dispatcher can call it directly. We do NOT round-
      trip through FastMCP's async layer — the SDK calls inside each
      tool are synchronous httpx calls and the eventlet worker handles
      them fine.

Drift check:
    ``audit_registry()`` walks FastMCP's internal tool list and warns
    about any tool that's missing from ``TOOL_SCOPES``. Logged at
    import time so a new tool added to ``mcp/mcpserver.py`` without a
    scope annotation surfaces in the boot log.
"""

from __future__ import annotations

from typing import Callable, Iterable

from utils.logging import get_logger

logger = get_logger(__name__)


# --------------------------------------------------------------------
# Scope catalogue. Three-way split per docs/prd/remote-mcp.md.
# --------------------------------------------------------------------
SCOPE_READ_MARKET = "read:market"
SCOPE_READ_ACCOUNT = "read:account"
SCOPE_WRITE_ORDERS = "write:orders"


# --------------------------------------------------------------------
# Explicit scope map — ONE source of truth. Adding a new MCP tool MUST
# add an entry here or it won't be reachable over the HTTP transport.
# audit_registry() warns about omissions at boot.
# --------------------------------------------------------------------
TOOL_SCOPES: dict[str, str] = {
    # ---- Order placement / modification / cancellation ----
    "place_order": SCOPE_WRITE_ORDERS,
    "place_smart_order": SCOPE_WRITE_ORDERS,
    "place_basket_order": SCOPE_WRITE_ORDERS,
    "place_split_order": SCOPE_WRITE_ORDERS,
    "place_options_order": SCOPE_WRITE_ORDERS,
    "place_options_multi_order": SCOPE_WRITE_ORDERS,
    "modify_order": SCOPE_WRITE_ORDERS,
    "cancel_order": SCOPE_WRITE_ORDERS,
    "cancel_all_orders": SCOPE_WRITE_ORDERS,
    "close_all_positions": SCOPE_WRITE_ORDERS,
    # analyzer_toggle flips between live and analyze (paper) modes — a
    # mistaken True silently routes future orders to the real broker.
    # Treated as a write because the blast radius is the same.
    "analyzer_toggle": SCOPE_WRITE_ORDERS,
    # ---- Account state ----
    "get_open_position": SCOPE_READ_ACCOUNT,
    "get_order_status": SCOPE_READ_ACCOUNT,
    "get_order_book": SCOPE_READ_ACCOUNT,
    "get_trade_book": SCOPE_READ_ACCOUNT,
    "get_position_book": SCOPE_READ_ACCOUNT,
    "get_holdings": SCOPE_READ_ACCOUNT,
    "get_funds": SCOPE_READ_ACCOUNT,
    "calculate_margin": SCOPE_READ_ACCOUNT,
    "analyzer_status": SCOPE_READ_ACCOUNT,
    # send_telegram_alert is account-scoped because the receiving channel
    # is the account owner's bot. No order placement, but it has a real
    # external side effect.
    "send_telegram_alert": SCOPE_READ_ACCOUNT,
    # ---- Market data ----
    "get_quote": SCOPE_READ_MARKET,
    "get_multi_quotes": SCOPE_READ_MARKET,
    "get_option_chain": SCOPE_READ_MARKET,
    "get_market_depth": SCOPE_READ_MARKET,
    "get_historical_data": SCOPE_READ_MARKET,
    "search_instruments": SCOPE_READ_MARKET,
    "get_symbol_info": SCOPE_READ_MARKET,
    "get_index_symbols": SCOPE_READ_MARKET,
    "get_expiry_dates": SCOPE_READ_MARKET,
    "get_available_intervals": SCOPE_READ_MARKET,
    "get_option_symbol": SCOPE_READ_MARKET,
    "get_synthetic_future": SCOPE_READ_MARKET,
    "get_option_greeks": SCOPE_READ_MARKET,
    "get_holidays": SCOPE_READ_MARKET,
    "get_timings": SCOPE_READ_MARKET,
    "check_holiday": SCOPE_READ_MARKET,
    "get_instruments": SCOPE_READ_MARKET,
    # ---- Research: technical indicators (openalgo.ta over history) ----
    "calculate_indicator": SCOPE_READ_MARKET,
    "get_trend_snapshot": SCOPE_READ_MARKET,
    "get_momentum_snapshot": SCOPE_READ_MARKET,
    "get_volatility_snapshot": SCOPE_READ_MARKET,
    "get_support_resistance": SCOPE_READ_MARKET,
    "detect_signals": SCOPE_READ_MARKET,
    "screen_instruments": SCOPE_READ_MARKET,
    "multi_timeframe_analysis": SCOPE_READ_MARKET,
    "correlation_beta": SCOPE_READ_MARKET,
    # ---- Info / introspection — readable by anyone with any scope ----
    # These are exempt from the scope filter because they help clients
    # discover what they can do. Implementing as read:market keeps the
    # check uniform without inventing a fourth scope.
    "get_openalgo_version": SCOPE_READ_MARKET,
    "validate_order_constants": SCOPE_READ_MARKET,
}


# Tools that change something but are deliberately not write-scoped.
# Every entry is a tool a read-only token can still trigger, so each one
# needs a justification next to its TOOL_SCOPES entry above.
WRITE_SCOPE_EXCEPTIONS = {"send_telegram_alert"}


def required_scope(tool_name: str) -> str | None:
    """Return the scope required to call ``tool_name``, or None if unknown."""
    return TOOL_SCOPES.get(tool_name)


def active_tool_names() -> set[str] | None:
    """Tool names the MCP server actually registered this boot.

    ``mcp/mcpserver.py`` narrows its own registration from
    ``OPENALGO_MCP_TOOLSETS`` / ``OPENALGO_MCP_READ_ONLY``. The HTTP
    transport reads the result here so both transports advertise and
    accept the same set — an operator who boots read-only must not find
    order placement still reachable over HTTP.

    Returns None when the set cannot be determined, which callers treat
    as "no filtering" so a metadata failure never takes the transport
    down. ``tools/list`` did not previously load the tool module at all,
    so the load is guarded here rather than allowed to surface as a
    JSON-RPC error.
    """
    try:
        module = _load_mcpserver_module()
    except Exception:
        logger.exception("Could not load mcp/mcpserver.py to read active tools")
        return None
    names = getattr(module, "ACTIVE_TOOL_NAMES", None) if module else None
    if not names:
        return None
    return set(names)


def list_tools_for_scopes(granted_scopes: Iterable[str]) -> list[str]:
    """Tool names callable under at least one of the granted scopes.

    Intersected with the tools actually registered this boot.
    """
    granted = set(granted_scopes)
    active = active_tool_names()
    return sorted(
        name
        for name, scope in TOOL_SCOPES.items()
        if scope in granted and (active is None or name in active)
    )


def _load_mcpserver_module():
    """Load ``mcp/mcpserver.py`` directly by file path.

    The local ``mcp/`` directory is NOT a Python package (no
    ``__init__.py``) and the pip-installed ``mcp`` package shadows the
    name in normal imports. To reach our tool definitions we therefore
    resolve the file by path and load it through ``importlib.util``.
    Cached on the function attribute so repeat calls are free.
    """
    import importlib.util
    import os
    import sys

    cached = getattr(_load_mcpserver_module, "_module", None)
    if cached is not None:
        return cached

    # This file lives at <project>/utils/mcp_tool_registry.py; the MCP
    # entry point lives at <project>/mcp/mcpserver.py. Walk up + over.
    here = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(here)
    target = os.path.join(project_root, "mcp", "mcpserver.py")
    spec = importlib.util.spec_from_file_location("openalgo_mcp_server", target)
    if spec is None or spec.loader is None:
        logger.error("Could not build spec for mcp/mcpserver.py")
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules["openalgo_mcp_server"] = module  # so its decorators bind
    spec.loader.exec_module(module)
    setattr(_load_mcpserver_module, "_module", module)
    return module


def get_tool_callable(tool_name: str) -> Callable | None:
    """Resolve the underlying Python function for a tool.

    The HTTP transport is responsible for setting
    ``OPENALGO_MCP_HTTP_BOOT=1`` before this module is loaded so the
    stdio argv check is bypassed.

    Returns None for a tool the server did not register this boot, so a
    narrowed server (read-only, or a subset of toolsets) refuses the
    call instead of running a tool it never advertised.
    """
    if tool_name not in TOOL_SCOPES:
        return None
    active = active_tool_names()
    if active is not None and tool_name not in active:
        return None
    module = _load_mcpserver_module()
    if module is None:
        return None
    fn = getattr(module, tool_name, None)
    return fn if callable(fn) else None


def registered_tool_names() -> set[str]:
    """Tool names FastMCP holds in its internal tool table.

    Best-effort — FastMCP's internal layout has shifted across versions,
    so multiple attribute paths are tried. An empty set means the layout
    was not recognised, not that there are no tools.
    """
    _mod = _load_mcpserver_module()
    if _mod is None:
        return set()

    fastmcp = getattr(_mod, "mcp", None)
    if fastmcp is None:
        return set()

    candidates = []
    for path in ("_tool_manager", "_tool_registry", "tools"):
        obj = getattr(fastmcp, path, None)
        if obj is None:
            continue
        # FastMCP often wraps tools in a manager that has a `_tools` dict
        for sub in ("_tools", "tools"):
            inner = getattr(obj, sub, None)
            if isinstance(inner, dict):
                candidates.append(inner)
        if isinstance(obj, dict):
            candidates.append(obj)

    seen: set[str] = set()
    for d in candidates:
        seen.update(d.keys())
    return seen


def audit_registry() -> None:
    """Log drift between mcp/mcpserver.py and this scope map.

    Three checks, all advisory — the HTTP transport still functions on
    TOOL_SCOPES alone, so a metadata mismatch degrades to a log line
    rather than a failed boot:

    1. A tool registered with FastMCP but absent from TOOL_SCOPES is
       unreachable over HTTP.
    2. A TOOL_SCOPES entry with no corresponding tool is dead config,
       usually a rename that only got applied on one side.
    3. A tool whose annotations disagree with its scope — a write tool
       filed under a read scope would be callable with a read-only
       token, so this is the one that actually matters for security.

    test/test_mcp_integrity.py asserts all three are clean, so in a
    healthy tree these never fire.
    """
    _mod = _load_mcpserver_module()
    if _mod is None:
        return

    seen = registered_tool_names()
    if not seen:
        return

    scoped = set(TOOL_SCOPES)

    missing = seen - scoped
    if missing:
        logger.warning(
            "MCP tools registered with FastMCP but missing TOOL_SCOPES "
            f"entries: {sorted(missing)}. They will not be reachable via "
            "the HTTP transport. Add them to utils/mcp_tool_registry.py."
        )

    # Only meaningful when the server booted unfiltered; a narrowed
    # server is expected to leave scope entries without a live tool.
    tool_meta = getattr(_mod, "TOOL_META", {}) or {}
    if tool_meta and len(seen) == len(tool_meta):
        orphaned = scoped - seen
        if orphaned:
            logger.warning(
                f"TOOL_SCOPES entries with no registered MCP tool: {sorted(orphaned)}. "
                "Stale after a rename or removal; drop them from "
                "utils/mcp_tool_registry.py."
            )

    for name, meta in tool_meta.items():
        scope = TOOL_SCOPES.get(name)
        if scope is None or name in WRITE_SCOPE_EXCEPTIONS:
            continue
        if not meta.read_only and scope != SCOPE_WRITE_ORDERS:
            logger.warning(
                f"MCP tool '{name}' is annotated as a write "
                f"(readOnlyHint=False) but carries scope '{scope}'. A read-only "
                "token could call it. Fix the scope in "
                "utils/mcp_tool_registry.py or the annotation in mcp/mcpserver.py."
            )
        elif meta.read_only and scope == SCOPE_WRITE_ORDERS:
            logger.warning(
                f"MCP tool '{name}' is annotated read-only but requires the "
                f"'{SCOPE_WRITE_ORDERS}' scope. Clients will be denied a call "
                "their annotations say is safe."
            )
