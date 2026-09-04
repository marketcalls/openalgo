"""The rendering tool: cards, tables and general charts the model composes.

This is the third renderer and the only one whose numbers the model types
itself. The other two are tools that fetch their own data
(:mod:`services.agent.tools.viz`), which is what makes a price chart
trustworthy. Here the model writes the markup, so **the provenance rule lives
in the prompt rather than in the plumbing**, and that is exactly why this tier
is for general data and never for prices, candles, open interest or Greeks. A
chart of invented prices is worse than no chart, because it reads as
authoritative.

The markup is OpenUI Lang. The component vocabulary and the language reference
the model is taught both come from one place,
``frontend/src/lib/agent/openuiLibrary.ts``, which is the same library object
the browser renders with; ``docs/prompt/openui-lang.md`` is generated from it
and injected by :data:`services.agent.prompts.OPENUI_LANG_SECTION` on the chat
surface. The model therefore cannot be taught a component the renderer lacks.

What this file enforces, and why each check is here rather than only in the
prompt
-------------------------------------------------------------------------

The prompt asks; this refuses. Everything below is a check the model can fail
and be told how to fix, which is the difference between a rule and a control:

* **A ``root`` binding.** ``root = Card(...)`` is the entry point of every
  OpenUI Lang program. Markup without one parses and renders **nothing at
  all**, silently, so the operator sees an empty answer and nobody learns why.
  Refusing it turns a blank card into one retry.
* **No URL.** ``MarkDownRenderer`` is in the component subset, and markdown in
  it can carry a link or an image. ``Message.tsx`` blocks markdown images in
  the prose for a reason: a fetched URL is how data leaves the machine, and
  this module feeds tool output back into the model's context, so it is exposed
  to precisely the injection that would aim one. The prompt says never emit a
  URL; this makes saying it unnecessary.
* **A length bound.** The markup crosses the wire and is persisted on the
  message row. A runaway string is cheaper to refuse than to store.

Nothing here mutates anything, so the tool needs no confirmation and writes no
audit row.

The payload does not go back to the model. It goes on the run's sink and
reaches the browser as a :class:`~services.agent.frames.Ui` frame, exactly as a
chart does; the model gets one line back. Echoing the markup would double the
cost of every rendered answer for no reader.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from services.agent.frames import Ui
from services.agent.prompts import wrap_tool_result
from services.agent.tools.base import OpenAlgoToolkit, invalid_argument, strip_code_fence
from services.agent.viz_sink import emit_frame, sink_of
from utils.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    from services.agent.tools import ToolContext

logger = get_logger(__name__)

__all__ = ["MAX_MARKUP_CHARS", "OpenUiToolkit"]

#: Longest markup one call may render. A card, a table and a couple of charts
#: come to a few thousand characters; well past this is a runaway string rather
#: than an answer, and it is about to be stored on the message row and sent
#: down the wire.
MAX_MARKUP_CHARS = 20_000

#: Matches a fetchable URL anywhere in the markup: an explicit ``http(s)://``,
#: or a protocol-relative ``//host.tld`` which a browser fetches just as
#: happily. Deliberately broader than "a link component", because the block is
#: on the text reaching the browser and ``MarkDownRenderer`` renders markdown,
#: where ``[x](//host/?q=secret)`` is a link and ``![x](...)`` is a fetch that
#: needs no click at all.
#:
#: The protocol-relative half requires a dot so ordinary prose is not refused.
#: ``50//50`` and ``a // b`` carry no host and are left alone; the cost of
#: getting that wrong is a card the operator asked for being refused, and the
#: cost of the other error is the exfiltration channel this closes.
_URL = re.compile(r"https?://|//[^\s/]*\.[a-z]", re.IGNORECASE)

#: The entry point every OpenUI Lang program must bind. Markup without it
#: renders nothing at all rather than failing, which is the worst shape of
#: failure to leave in front of an operator.
_ROOT = re.compile(r"^\s*root\s*=", re.MULTILINE)

#: What the sink entry and the log line call this tool.
_TOOL = "render_ui"

#: Said when the surface created no sink, so there is nowhere for the markup to
#: go. The model is told plainly rather than being allowed to report a rendering
#: that never reached anyone.
_NO_SINK = (
    "This surface cannot render UI, so nothing was drawn. Answer in markdown "
    "instead, and do not tell the operator a card was rendered."
)


class OpenUiToolkit(OpenAlgoToolkit):
    """Render a card of general data in the conversation."""

    def __init__(self, context: ToolContext) -> None:
        """Register the rendering tool.

        The sink is bound before ``super().__init__`` because agno introspects
        the bound methods the moment it receives them, and a method reading an
        attribute the instance does not have yet would fail during registration
        rather than during a call.

        Args:
            context: The run's tool context. Its ``extras`` carry the sink the
                surface created for this run.
        """
        self._sink = sink_of(context)
        super().__init__(context, name="openui", tools=[self.render_ui])

    def render_ui(self, markup: str) -> str:
        """Render a card of general data: charts, tables, metric callouts.

        Reach for this when the answer is a set of numbers that reads better
        drawn than written: position sizes, a funds breakdown, a comparison
        across instruments, a set of counts or shares. The operator sees a
        rendered card in the conversation rather than a markdown table.

        This is not the tool for prices. A price, a candle series, an open
        interest ladder or a Greek gets ``plot_price_chart``,
        ``plot_open_interest``, ``plot_gamma_exposure`` or
        ``plot_volatility_surface``, because those fetch their own data and
        this one draws whatever you type. Every number you put in this markup
        must come from a tool result you actually received in this
        conversation.

        Ordinary answers stay markdown. Rendering is a deliberate act, not a
        wrapper around every reply.

        Args:
            markup: The whole OpenUI Lang program, as described in the OPENUI
                LANG section of your instructions. It must bind ``root``, as in
                ``root = Card([title, chart])`` on the first line, and every
                name it defines must be reachable from ``root`` or it is
                silently dropped. Send the program alone, with no code fence
                and no commentary around it.

        Returns:
            One line confirming what was rendered. The markup is not read back
            to you; the operator can already see it, so describe what it shows
            rather than repeating it.
        """
        if not isinstance(markup, str) or not markup.strip():
            invalid_argument(
                "markup",
                "it is empty",
                "Send the whole OpenUI Lang program, starting with root = Card([...]).",
            )

        text = strip_code_fence(markup)
        if not text:
            invalid_argument(
                "markup",
                "it holds nothing but a code fence",
                "Send the program itself, unfenced.",
            )

        if len(text) > MAX_MARKUP_CHARS:
            invalid_argument(
                "markup",
                f"it is {len(text)} characters, more than the {MAX_MARKUP_CHARS} one "
                "rendering may carry",
                "Render fewer rows or fewer series, or answer in markdown instead.",
            )

        if not _ROOT.search(text):
            invalid_argument(
                "markup",
                "it binds no 'root', so it would render nothing at all",
                "Every program starts with a line binding root, such as "
                "root = Card([summary, chart]).",
            )

        if _URL.search(text):
            invalid_argument(
                "markup",
                "it carries a URL, and a rendered card never fetches one",
                "Remove the link or image and state the fact in text instead.",
            )

        drawn = emit_frame(self._sink, tool=_TOOL, frame=Ui(delta=text))
        if not drawn:
            return wrap_tool_result(_TOOL, _NO_SINK)

        logger.debug("Agent rendered %d characters of OpenUI markup", len(text))
        return wrap_tool_result(
            _TOOL,
            "Rendered the card in the conversation. The operator can see it, so "
            "describe what it shows rather than repeating its contents, and do "
            "not restate the same numbers as a markdown table underneath it.",
        )
