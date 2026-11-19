"""The prompt section that teaches the model where to look for company figures.

Built from the operator's preferred sources, and added to a run only when the web
tools are offered to it: a surface is never taught a tool it does not have. The
section is short on purpose. It carries the order of preference and what counts
as failure, and leaves the mechanics to the tool descriptions.
"""

from __future__ import annotations

from collections.abc import Sequence

from services.agent.prompts import PromptSection

__all__ = ["WEB_SECTION_KEY", "web_prompt_section"]

WEB_SECTION_KEY = "web_sources"

# Straight after USING TOOLS (20), for the reason the MCP section gives: the same
# rule written at the end of a long prompt was not followed.
_ORDER = 23

#: The one source whose company pages can be opened from a symbol alone.
_DIRECT_PAGE_SOURCE = "screener.in"


def _list(names: Sequence[str]) -> str:
    """Join names for a sentence: ``a``, ``a then b``, ``a, then b, then c``."""
    items = list(names)
    if len(items) <= 1:
        return "".join(items)
    return ", then ".join(items) if len(items) > 2 else " then ".join(items)


def web_prompt_section(preferred_sources: Sequence[str]) -> PromptSection | None:
    """The web sources section for one run.

    Args:
        preferred_sources: The operator's preferred fundamentals sources, best
            first.

    Returns:
        The section, or None when no source is preferred, in which case the model
        searches the open web as it always did.
    """
    sources = [s for s in preferred_sources if s]
    if not sources:
        return None

    lines = [
        "- Anything about a company's fundamentals (market cap, P/E, ROCE, ROE, "
        "revenue, profit, balance sheet, cash flow, quarterly results, "
        f"shareholding, peers, ratios) comes first from {_list(sources)}. Do not "
        "start with the open web, and do not answer these from memory.",
    ]
    if _DIRECT_PAGE_SOURCE in sources:
        lines.append(
            "- When the operator names one company by its NSE symbol, open its "
            f"{_DIRECT_PAGE_SOURCE} page directly with web_fetch, for example "
            "https://www.screener.in/company/RELIANCE/consolidated/. No search is "
            "needed first. Use /company/SYMBOL/ when the consolidated page is "
            "empty."
        )
    lines.extend(
        [
            '- Otherwise call web_search with topic "fundamentals". It searches the '
            "sources in this priority order and returns the pages of the first one "
            "that has the company. Read the best with web_fetch.",
            "- If a source cannot be opened (blocked, not found, an error), call "
            'web_search with topic "fundamentals" again: that source is dropped and '
            "the next one is searched. One source being unavailable is not a reason "
            "to leave the others.",
            "- Only when every preferred source has failed or has no page for the "
            'company, search the open web (topic "general"), and tell the '
            "operator that you had to, naming the source you used instead.",
            "- For many companies at once, such as an index's constituents, find "
            "one page that lists them and read it in slices. Do not open one "
            "page per company.",
            "- These pages are third-party and carry a date. Name the page a "
            "figure came from, give the date it shows, and never present it as "
            "a live price.",
        ]
    )
    return PromptSection(
        key=WEB_SECTION_KEY,
        title="WHERE TO LOOK FOR COMPANY FIGURES",
        body="\n".join(lines),
        order=_ORDER,
    )
