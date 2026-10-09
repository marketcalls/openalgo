"""The prompt section that teaches the model what each MCP server is for.

Generated from the registry, so a new server is described the moment it is
registered, and added to a run only when the MCP toolkit is offered to it: a
surface is never taught a tool it does not have.
"""

from __future__ import annotations

from services.agent.mcp.registry import McpServerSpec, servers_for_surface
from services.agent.prompts import PromptSection

__all__ = ["MCP_SECTION_KEY", "mcp_prompt_section"]

MCP_SECTION_KEY = "mcp"

# Straight after USING TOOLS (20) and before the domain sections. At 65 it sat
# at the very end of a prompt over 30k characters long, and in live testing the
# model answered every exchange statistic from web search instead; the surface
# section still comes later, so a surface's own rules keep the last word.
_ORDER = 22

_RULES = """
- The broker tools come first for live quotes, intraday candles, depth, option
  chains, funds, positions and orders. Use these servers for what the broker
  does not give.
- Each server below is the publisher's own data, not a website about it. When
  the operator names that publisher or asks for a figure it publishes (market
  breadth, gainers and losers, a 52-week high or low, a corporate action, an
  index valuation), call the server. Never answer those from web search or
  web research, which restate the same numbers second hand; keep web search for
  news, commentary and events.
- Pass the server key exactly. When unsure of a tool's name or arguments, call
  list_mcp_tools first, with tool set for one tool's full arguments. Cached.
- If a server fails, say the source is unavailable right now and answer from
  the broker tools where you can. Do not retry it more than once.
"""


def _server_line(spec: McpServerSpec) -> str:
    """One bullet describing one server.

    Args:
        spec: The server.

    Returns:
        ``- key (title): use for ... caveats``.
    """
    line = f"- {spec.key} ({spec.title}): use for {spec.use_for}."
    if spec.caveats:
        line += f" {spec.caveats}"
    return line


def mcp_prompt_section(surface: str) -> PromptSection | None:
    """The section for one surface, or None when no server is offered there.

    Args:
        surface: ``chat``, ``chart`` or ``voice``.

    Returns:
        A :class:`PromptSection` keyed :data:`MCP_SECTION_KEY`, or None.
    """
    servers = servers_for_surface(surface)
    if not servers:
        return None
    lines = [
        "Read-only data services, reached with list_mcp_tools and call_mcp_tool.",
        *(_server_line(spec) for spec in servers),
        _RULES.strip(),
    ]
    providers = sorted({spec.provider for spec in servers if spec.provider})
    if providers:
        # Once for every server rather than once per server: it is the
        # publisher's condition on the data, and the prompt budget is shared.
        lines.append(
            f"- Name {' and '.join(providers)} as the source. The data is published for "
            "information and education."
        )
    body = "\n".join(lines)
    return PromptSection(key=MCP_SECTION_KEY, title="EXTERNAL DATA (MCP)", body=body, order=_ORDER)
