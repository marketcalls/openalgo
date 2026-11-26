"""Keep LiteLLM's MCP gateway out of requests that carry no MCP tool.

LiteLLM 1.106 runs a gateway that resolves MCP tools served by a LiteLLM proxy.
Every Responses API call (the ChatGPT plan models, and any model whose
registry mode is ``responses``) passes through
``litellm.responses.main._responses_try_dispatch_mcp_gateway``, which imports
the gateway's handler before it looks at the tools. That handler imports the
proxy's MCP catalogue, which needs the mcp 2.x SDK (``mcp.types.CacheableResult``
and sixteen other names). OpenAlgo pins mcp 1.30, because its own MCP server
is written against ``FastMCP``, which mcp 2 renamed. So with nothing else
wrong, every such call failed with::

    cannot import name 'CacheableResult' from 'mcp.types'

``litellm.completion`` does the same whenever ``tools`` is set, which is every
agent turn; :func:`services.agent.builder.build_model` sends LiteLLM's own
``_skip_mcp_handler`` flag for that path. This module covers the Responses
path, where the import happens before the flag is read.

The gateway only ever engages for a tool of type ``mcp`` (LiteLLM's
``_mcp_server_url`` returns None for anything else), so answering "no gateway"
for a request without one is exactly what the original returns, minus the
import. A request that does carry an MCP tool still goes to the original. The
agent never sends one: it runs its MCP servers itself and hands LiteLLM plain
function tools.

Drop this module once OpenAlgo moves to mcp 2.x, or once LiteLLM imports the
handler only when an MCP tool is present.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Iterable, Mapping
from types import ModuleType
from typing import Any

from utils.logging import get_logger

logger = get_logger(__name__)

RESPONSES_MODULE = "litellm.responses.main"
DISPATCH = "_responses_try_dispatch_mcp_gateway"
_MARKER = "_openalgo_mcp_gateway_gate"


def names_an_mcp_tool(tools: Iterable[Any] | None) -> bool:
    """True when any tool is an MCP tool, the only kind the gateway acts on."""
    return any(isinstance(tool, Mapping) and tool.get("type") == "mcp" for tool in tools or ())


def install(responses_main: ModuleType) -> bool:
    """Gate the Responses API's MCP dispatch on an MCP tool being present.

    Idempotent. Called by :func:`services.agent.litellm_loader.load` under its
    import lock, so it takes the module rather than importing it (the loader's
    lock is not re-entrant).

    Args:
        responses_main: The ``litellm.responses.main`` module.

    Returns:
        True when the gate is in place after this call.
    """
    original = getattr(responses_main, DISPATCH, None)
    if original is None:
        logger.warning(
            "LiteLLM no longer has %s.%s; the MCP gateway gate is not installed",
            RESPONSES_MODULE,
            DISPATCH,
        )
        return False
    if getattr(original, _MARKER, False):
        return True
    params = inspect.signature(original).parameters
    if "tools" not in params or "skip_mcp_handler" not in params:
        logger.warning(
            "LiteLLM's %s has an unexpected signature; the MCP gateway gate is not installed",
            DISPATCH,
        )
        return False

    @functools.wraps(original)
    def gated(*args: Any, **kwargs: Any) -> Any:
        # The original takes keyword arguments only, so a positional one means a
        # changed signature: that call goes to the original untouched.
        if not args and (
            kwargs.get("skip_mcp_handler") or not names_an_mcp_tool(kwargs.get("tools"))
        ):
            return None
        return original(*args, **kwargs)

    setattr(gated, _MARKER, True)
    setattr(responses_main, DISPATCH, gated)
    return True
