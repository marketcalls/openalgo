"""The side channel a rendering tool's payload travels on.

Why this exists
---------------

A chart tool has two audiences and they want opposite things. The model wants
one line saying the chart was drawn, because a five hundred candle series
costs the conversation its context window to say nothing the summary does not
already say. The browser wants every candle, because that is the chart.

So the tool returns the line and puts the payload here, and the payload reaches
the client as a :class:`~services.agent.frames.Viz` frame instead of as a tool
result. Charting five hundred candles therefore costs the conversation a
sentence. **A viz tool that returns its series to the model has missed the
point of this module.**

Both rendering tiers travel this way, not just the charts. ``render_ui`` leaves
a :class:`~services.agent.frames.Ui` frame on the same list, for the same
reason: markup the operator is about to read is not something the model needs
read back to it. One sink, one hook, one cap, so a third tier is a frame type
rather than another side channel to wire into every route.

How it is wired
---------------

The sink is a plain list the request creates and drops in
``ToolContext.extras``, which ``builder.tool_factory`` copies onto the per-run
context, so every toolkit the run builds shares the same list::

    sink = viz_sink.new_sink()
    context = ToolContext(api_key=..., extras={viz_sink.SINK_KEY: sink})
    agent = builder.build_agent(context, ...)
    chunks = stream.stream_run(agent, message, tool_frames=viz_sink.frame_hook(sink))

Deliberately **not** a module-level registry keyed by run id. Production is a
single gunicorn worker that never restarts, so a module-level dict of runs is a
leak that grows for the life of the process. A list owned by the request is
collected with the request, whether the run finished, failed or the client hung
up mid-answer.

Import safety
-------------

No agno import, direct or transitive, so ``blueprints/agent.py`` can create a
sink and build the hook without the optional dependency being installed.
:mod:`services.agent.tools.viz` needs agno; this module does not.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from services.agent.frames import Frame, Viz
from services.agent.tools import context_value
from utils.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "MAX_SINK_ENTRIES",
    "SINK_KEY",
    "VizEntry",
    "drain",
    "emit",
    "emit_frame",
    "frame_hook",
    "new_sink",
    "no_sink_message",
    "sink_of",
]

#: Where the sink lives inside ``ToolContext.extras``.
SINK_KEY = "viz_sink"

#: Most payloads one run may leave undrained. With the hook attached the sink
#: holds at most one entry at a time, because every completed tool call drains
#: it; reaching this cap means the caller forgot the hook, and the entries would
#: otherwise pile up for the length of the run. A chart spec can be a hundred
#: kilobytes, so the cap is small on purpose: the oldest is dropped, which loses
#: a chart rather than growing the worker's memory without limit.
MAX_SINK_ENTRIES = 8


@dataclass(frozen=True, slots=True)
class VizEntry:
    """One rendering waiting to go out on the wire.

    Attributes:
        tool: The tool that produced it. Carried for logs only; the frame is
            not addressed to a tool call and the client needs no such link.
        frame: The frame to emit, already complete. Typed as the base
            :class:`~services.agent.frames.Frame` rather than as ``Viz``,
            because both rendering tiers travel this way: a chart tool leaves a
            :class:`~services.agent.frames.Viz`, and ``render_ui`` leaves a
            :class:`~services.agent.frames.Ui`. One sink and one hook serve
            both, so adding a tier is a frame type rather than a second
            side channel to wire into every route.
    """

    tool: str
    frame: Frame


def no_sink_message(what: str) -> str:
    """Tell the model that a rendering could not be delivered to this surface.

    Every rendering tool needs the same sentence, and the sentence is doing
    real work: without it a tool whose payload went nowhere still reads as a
    success, and the model tells the operator to look at a chart that is not
    on screen. One wording here rather than one per tool, so the instruction
    not to claim a drawing cannot be softened in a copy nobody rereads.

    Args:
        what: What was not delivered, named the way the operator would name
            it, for example ``chart`` or ``instrument card``.

    Returns:
        The confirmation to return in place of a success line.
    """
    return (
        f"The {what} could not be delivered to this surface, so nothing was drawn. Answer in "
        f"prose and do not tell the operator that a {what} is on screen."
    )


def new_sink() -> list[VizEntry]:
    """Create an empty sink for one run.

    Returns:
        A fresh list. Put it in ``ToolContext.extras`` under :data:`SINK_KEY`
        and hand the same object to :func:`frame_hook`.
    """
    return []


def sink_of(context: Any) -> list[VizEntry] | None:
    """Find the sink a run's context carries, if it carries one.

    Args:
        context: The run's tool context, or anything shaped like it.

    Returns:
        The sink, or None when the surface did not create one, in which case a
        viz tool renders nothing and says so rather than failing.
    """
    candidate = context_value(context, SINK_KEY)
    return candidate if isinstance(candidate, list) else None


def emit(
    sink: list[VizEntry] | None,
    *,
    tool: str,
    kind: str,
    spec: dict[str, Any],
    title: str = "",
    source: str = "",
) -> bool:
    """Queue one chart for delivery to the client.

    Args:
        sink: The run's sink, or None when there is none.
        tool: The tool producing the chart, recorded for logs.
        kind: Which renderer draws this. See :class:`~services.agent.frames.Viz`.
        spec: The renderer's payload, already JSON-safe.
        title: Heading shown above the chart.
        source: What produced the data, for example ``history_service``.

    Returns:
        True when the chart was queued, False when there was no sink to queue
        it on, which the tool reports to the model rather than pretending a
        chart was drawn.
    """
    return emit_frame(sink, tool=tool, frame=Viz(kind=kind, spec=spec, title=title, source=source))


def emit_frame(sink: list[VizEntry] | None, *, tool: str, frame: Frame) -> bool:
    """Queue one already-built frame for delivery to the client.

    The one place an entry is appended and the one place the cap is enforced,
    so a second rendering tier is a new frame type here rather than a second
    queue with its own bound to get wrong. :func:`emit` is the chart-shaped
    front door onto this.

    Args:
        sink: The run's sink, or None when there is none.
        tool: The tool producing the frame, recorded for logs.
        frame: The frame to deliver, already complete.

    Returns:
        True when it was queued, False when there was no sink to queue it on,
        which the tool reports to the model rather than pretending it drew
        something.
    """
    if sink is None:
        logger.warning("Agent viz tool %s produced a rendering but the run carries no sink", tool)
        return False

    while len(sink) >= MAX_SINK_ENTRIES:
        dropped = sink.pop(0)
        logger.warning(
            "Agent viz sink is full; dropping the undrained rendering from %s", dropped.tool
        )

    sink.append(VizEntry(tool=tool, frame=frame))
    return True


def drain(sink: list[VizEntry] | None) -> list[Frame]:
    """Take every queued frame, emptying the sink.

    Everything queued is taken rather than only the entries matching the tool
    that just finished. A rendering frame is not addressed to a tool call, the
    queue order is the order the renderings were produced, and draining
    everything is what guarantees the list empties even if a tool name never
    matches.

    Args:
        sink: The run's sink, or None.

    Returns:
        The queued frames, oldest first.
    """
    if not sink:
        return []
    taken = [entry.frame for entry in sink]
    sink.clear()
    return taken


def frame_hook(sink: list[VizEntry] | None) -> Callable[[str, Any], Iterable[Frame]]:
    """Build the ``tool_frames`` hook ``stream.py`` calls after each tool.

    Args:
        sink: The run's sink, the same object the tool context carries.

    Returns:
        A callable taking ``(tool_name, result)`` and returning the frames to
        emit. The result is deliberately ignored: the payload never travels
        through the model's context, which is the whole point of the sink.
    """

    def hook(name: str, result: Any) -> Iterable[Frame]:
        del result  # The payload is on the sink, never in the model's result.
        frames = drain(sink)
        if frames:
            logger.debug("Agent tool %s produced %d viz frame(s)", name, len(frames))
        return frames

    return hook
