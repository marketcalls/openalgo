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
    # ---- Info / introspection — readable by anyone with any scope ----
    # These are exempt from the scope filter because they help clients
    # discover what they can do. Implementing as read:market keeps the
    # check uniform without inventing a fourth scope.
    "get_openalgo_version": SCOPE_READ_MARKET,
    "validate_order_constants": SCOPE_READ_MARKET,
}


def required_scope(tool_name: str) -> str | None:
    """Return the scope required to call ``tool_name``, or None if unknown."""
    return TOOL_SCOPES.get(tool_name)


def list_tools_for_scopes(granted_scopes: Iterable[str]) -> list[str]:
    """Tool names callable under at least one of the granted scopes."""
    granted = set(granted_scopes)
    return sorted(
        name for name, scope in TOOL_SCOPES.items() if scope in granted
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
    """
    if tool_name not in TOOL_SCOPES:
        return None
    module = _load_mcpserver_module()
    if module is None:
        return None
    fn = getattr(module, tool_name, None)
    return fn if callable(fn) else None


def audit_registry() -> None:
    """Warn about MCP tools registered with FastMCP but missing a scope.

    Best-effort — FastMCP's internal layout has shifted across versions,
    so multiple attribute paths are tried. A False return from this
    function is informational only; the HTTP transport still functions
    using TOOL_SCOPES alone.
    """
    _mod = _load_mcpserver_module()
    if _mod is None:
        return

    fastmcp = getattr(_mod, "mcp", None)
    if fastmcp is None:
        return

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

    if not candidates:
        return

    seen: set[str] = set()
    for d in candidates:
        seen.update(d.keys())

    missing = seen - set(TOOL_SCOPES.keys())
    if missing:
        logger.warning(
            "MCP tools registered with FastMCP but missing TOOL_SCOPES "
            f"entries: {sorted(missing)}. They will not be reachable via "
            "the HTTP transport. Add them to utils/mcp_tool_registry.py."
        )
