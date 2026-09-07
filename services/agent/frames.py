"""The agent SSE wire contract.

Every byte the `/agent` stream writes is produced here, and this module is the
only definition of what the browser may receive. Two rules keep it useful:

    **No agno import, direct or transitive.** This is the transport contract and
    nothing else. `stream.py` translates agno's events into these frames; the
    frames themselves know nothing about the library that produced them, so the
    blueprint, the tests and the client-side contract stay importable with agno
    absent or not yet installed.

    **No I/O.** No database, no logging, no clock, no network. A frame is built
    on a real OS thread, handed across a real queue and serialised on a
    greenlet, so it has to be a plain value with no hidden dependency on which
    world it was created in.

Wire format
-----------

One frame is one SSE data event::

    data: {"type": "token", "delta": "hel"}\\n\\n

There is deliberately **no** `event:` line. Every frame is discriminated on its
`type` field, which lets the client run one switch over an open union and lets
the request carry a JSON body, since it is read with `fetch` plus a
`ReadableStream` reader rather than `EventSource`.

:func:`heartbeat` emits an SSE comment, not a frame. A comment keeps an idle
connection out of a reverse proxy's read timeout without the client having to
know or ignore a keepalive message type.

Typical use
-----------

    from services.agent.frames import DoneReason, Done, Token, sse

    yield sse(Token(delta=chunk))
    yield sse(Done(reason=DoneReason.STOP))
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar

# Response headers for the streaming routes. `X-Accel-Buffering` is what stops
# nginx holding a frame back until its buffer fills, which turns a token stream
# into one long pause followed by the whole answer at once.
#
# `Connection` is deliberately absent. It is a hop-by-hop header, which PEP 3333
# forbids a WSGI application from setting, and the server owns it: HTTP/1.1 is
# persistent by default, so asking for keep-alive buys nothing, while a
# chunked stream that the server means to close ends up answering
# `Connection: keep-alive, close` - both tokens, merged, contradicting each
# other. A client that reads the first token keeps the socket in its pool and
# the server has already closed it, so the next request on that connection gets
# no reply at all and sits out its whole timeout. Measured against the dev
# server: every call made after a finished turn on the same connection timed
# out, while the same call on a fresh connection answered in milliseconds.
SSE_HEADERS: Mapping[str, str] = MappingProxyType(
    {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }
)


class DoneReason(StrEnum):
    """Why a run ended.

    A run that pauses for a confirmation ends its stream with a
    :class:`Confirm` frame and **no** :class:`Done`, so the absence of a done
    frame is not by itself a failure. See `docs/design/55-agent/README.md`.
    """

    STOP = "stop"
    CANCELLED = "cancelled"
    INCOMPLETE = "incomplete"


class NoticeLevel(StrEnum):
    """Severity of an out-of-band message shown beside the conversation."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ErrorKind(StrEnum):
    """Which layer failed, so the client can suggest the right fix.

    The field is typed as a plain string and any value is carried through
    untouched; these are the values this module ships, and using one of them
    keeps the client's handling of a common failure predictable.

    Attributes:
        CONFIG: No usable model is configured, or the named one is disabled.
        INPUT: The request itself was malformed or rejected before the run.
        PROVIDER: The upstream model provider refused or failed the call.
        TOOL: A tool raised in a way the run could not recover from.
        INTERNAL: Anything else, including a bug in this module.
    """

    CONFIG = "config"
    INPUT = "input"
    PROVIDER = "provider"
    TOOL = "tool"
    INTERNAL = "internal"


@dataclass(frozen=True, slots=True)
class Frame:
    """Base for every frame on the wire.

    Frozen because a frame crosses a thread boundary: it is built on the real
    OS thread running the agent and serialised on the greenlet draining the
    queue. Nothing may mutate it in between.

    Attributes:
        FRAME_TYPE: The value written to the `type` key. Set by each subclass.
    """

    FRAME_TYPE: ClassVar[str] = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-ready dict.

        Returns:
            The frame's fields in declaration order, preceded by a `type` key
            carrying this class's :attr:`FRAME_TYPE`. Values are returned by
            reference and are not copied.
        """
        payload: dict[str, Any] = {"type": self.FRAME_TYPE}
        for spec in fields(self):
            payload[spec.name] = getattr(self, spec.name)
        return payload


@dataclass(frozen=True, slots=True)
class Start(Frame):
    """First frame of every run, sent before any model output.

    Attributes:
        run_id: Agno's run identifier, needed to cancel or resume this run.
        session_id: Agno's session identifier, carried by a confirm resume.
        conversation_id: The `ag_conversation` row this run belongs to.
    """

    FRAME_TYPE: ClassVar[str] = "start"

    run_id: str
    session_id: str
    conversation_id: int | str
    #: The stored ``ag_message`` row for the question that opened this run, or
    #: an empty string on a surface that stores nothing. The client needs it to
    #: edit that question later: its own message ids are local counters, and
    #: truncation addresses rows by their database id.
    user_message_id: int | str = ""


@dataclass(frozen=True, slots=True)
class Token(Frame):
    """One chunk of assistant prose.

    Attributes:
        delta: The new characters only. The client appends; it never replaces.
    """

    FRAME_TYPE: ClassVar[str] = "token"

    delta: str


@dataclass(frozen=True, slots=True)
class ToolStart(Frame):
    """A tool call has been dispatched.

    Attributes:
        id: The tool call id, matching the later :class:`ToolEnd`.
        name: The tool's registered name.
        args: The arguments the model supplied, already JSON-safe.
    """

    FRAME_TYPE: ClassVar[str] = "tool_start"

    id: str
    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolEnd(Frame):
    """A tool call has returned.

    Exactly one of these follows each :class:`ToolStart`. Agno reports a failed
    call twice, as a completed event carrying an error and then a separate error
    event; the translator suppresses the second so a single failure is not shown
    to the user as two.

    Attributes:
        id: The tool call id, matching the earlier :class:`ToolStart`.
        name: The tool's registered name.
        ok: False when the call raised or returned an error.
        result: The tool's return value, already JSON-safe and length-capped.
        duration: Wall-clock seconds the call took, or None when not measured.
    """

    FRAME_TYPE: ClassVar[str] = "tool_end"

    id: str
    name: str
    ok: bool
    result: Any = None
    duration: float | None = None


@dataclass(frozen=True, slots=True)
class Reasoning(Frame):
    """One chunk of the model's reasoning trace.

    Attributes:
        delta: The new characters only, appended like a :class:`Token`.
    """

    FRAME_TYPE: ClassVar[str] = "reasoning"

    delta: str


@dataclass(frozen=True, slots=True)
class Ui(Frame):
    """One chunk of OpenUI Lang markup emitted by the `render_ui` tool.

    The client feeds the **whole accumulated string** to the renderer on every
    frame, not just this delta; the renderer diffs internally.

    Attributes:
        delta: The new characters only.
    """

    FRAME_TYPE: ClassVar[str] = "ui"

    delta: str


@dataclass(frozen=True, slots=True)
class Viz(Frame):
    """A complete chart the client renders with a purpose-built engine.

    This is the counterpart to :class:`Ui`, and the difference is the point.
    `Ui` streams OpenUI markup the model composes itself, so its numbers are
    whatever the model typed. A `Viz` frame carries a payload a **tool** built
    from a service call, so the model never types a price. That is what makes a
    price chart trustworthy: it cannot show a candle the platform did not
    return.

    It also keeps the data out of the model's context. The tool answers the
    model with a one line confirmation while the full series travels here, so
    charting five hundred candles costs the conversation nothing.

    `kind` selects the renderer, and the client ignores a kind it does not know
    rather than throwing, so a newer backend cannot break an older client
    mid-turn:

    * `candles` renders through `openalgo-charts`, the same engine as
      `/trading`, so an OHLC chart in chat is the chart the operator already
      knows, indicators included.
    * `plotly` renders through the shared `Plot2D` and `Plot3D` wrappers, the
      same ones `/strategybuilder` and the option analytics pages use. Its
      `spec` is a Plotly figure: `data`, and optionally `layout` and `config`.
    * `instrument` renders the instrument card built by
      `services/agent/tools/instrument.py`: the quote and the day's move, an
      intraday price and volume series, the 52 week range, the order book, and
      the operator's own position in that instrument. Every section beyond the
      quote is optional, and one that could not be read is absent from the spec
      and named in its `unavailable` mapping instead.

    Attributes:
        kind: Which renderer draws this. See above.
        spec: The renderer's payload. Self-contained; the client fetches
            nothing further to draw it.
        title: Heading shown above the chart. May be empty.
        source: What produced the data, for example `history_service`. Shown to
            the operator so the provenance of a number is never a guess.
    """

    FRAME_TYPE: ClassVar[str] = "viz"

    kind: str = ""
    spec: dict[str, Any] = field(default_factory=dict)
    title: str = ""
    source: str = ""


@dataclass(frozen=True, slots=True)
class ChartCommand(Frame):
    """Commands for the `/trading` terminal to apply.

    Attributes:
        commands: A list of chart commands, each a dict with an `op` key. The
            terminal ignores an unknown `op` rather than throwing, so a newer
            backend cannot break an older client mid-turn.
    """

    FRAME_TYPE: ClassVar[str] = "chart_command"

    commands: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Confirm(Frame):
    """The run has paused and needs the user to approve a mutating tool call.

    This frame **terminates the stream** with no :class:`Done` after it. The
    client resumes by posting `run_id` and `session_id` back with a decision per
    requirement; it must not treat the missing done frame as a failure.

    Attributes:
        run_id: The paused run, needed to resume it.
        session_id: The session the paused run belongs to.
        requirements: One entry per tool call awaiting a decision.
    """

    FRAME_TYPE: ClassVar[str] = "confirm"

    run_id: str
    session_id: str
    requirements: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Notice(Frame):
    """An out-of-band message about the run rather than from the model.

    Attributes:
        level: One of :class:`NoticeLevel`.
        message: Human-readable text, safe to show verbatim.
    """

    FRAME_TYPE: ClassVar[str] = "notice"

    level: str
    message: str


@dataclass(frozen=True, slots=True)
class Usage(Frame):
    """What the turn has consumed so far, in tokens and money.

    Every usage frame carries the **running total for the turn**, not the delta
    since the last one, so a client renders the latest frame and discards the
    one before it. A single turn makes one model call per tool round trip, and a
    per-call frame would otherwise leave the client adding up numbers whose
    meaning depends on how many it happened to receive.

    Attributes:
        input_tokens: Prompt tokens billed, including cached ones.
        output_tokens: Completion tokens billed.
        total_tokens: The provider's own total where it reports one.
        cached_tokens: Prompt tokens served from the provider's cache.
        reasoning_tokens: Output tokens spent on a reasoning trace.
        cost_usd: Computed locally from LiteLLM's price table, or None when the
            model is absent from it. Showing tokens and admitting the price is
            unknown beats inventing a number. Always None when `billing` is
            `subscription`: those tokens came out of a plan and have no
            per-token price, so any figure here would be a false one.
        billing: `metered` when the turn is billed per token, `subscription`
            when it came out of a ChatGPT plan. The two are not distinguishable
            from `model` alone: eight of the ten subscription models share a
            bare name with an `openai` one, and a client rendering `$0.00` for a
            plan turn would be saying it was free. A client that does not know
            this field renders tokens and no cost, which is already correct.
        model: The model id the provider billed, as the provider reported it.
        ttft_ms: Milliseconds from the start of the run to its first token.
    """

    FRAME_TYPE: ClassVar[str] = "usage"

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float | None = None
    billing: str = "metered"
    model: str | None = None
    ttft_ms: float | None = None


@dataclass(frozen=True, slots=True)
class Error(Frame):
    """The run failed. No further frames follow except a :class:`Done`.

    Attributes:
        message: The upstream message verbatim where there is one. A provider
            distinguishes an invalid key from an unknown model and the operator
            needs that difference; do not replace it with a generic string.
        kind: One of :class:`ErrorKind`, naming the layer that failed.
    """

    FRAME_TYPE: ClassVar[str] = "error"

    message: str
    kind: str = ErrorKind.INTERNAL


@dataclass(frozen=True, slots=True)
class Done(Frame):
    """Last frame of a run that reached an end.

    Attributes:
        reason: One of :class:`DoneReason`.
    """

    FRAME_TYPE: ClassVar[str] = "done"

    reason: str = DoneReason.STOP


# The closed set of frame classes, keyed by wire type. A translator building a
# frame by name and a test asserting the vocabulary both read this rather than
# repeating the list.
FRAME_CLASSES: Mapping[str, type[Frame]] = MappingProxyType(
    {
        Start.FRAME_TYPE: Start,
        Token.FRAME_TYPE: Token,
        ToolStart.FRAME_TYPE: ToolStart,
        ToolEnd.FRAME_TYPE: ToolEnd,
        Reasoning.FRAME_TYPE: Reasoning,
        Ui.FRAME_TYPE: Ui,
        Viz.FRAME_TYPE: Viz,
        ChartCommand.FRAME_TYPE: ChartCommand,
        Confirm.FRAME_TYPE: Confirm,
        Notice.FRAME_TYPE: Notice,
        Usage.FRAME_TYPE: Usage,
        Error.FRAME_TYPE: Error,
        Done.FRAME_TYPE: Done,
    }
)

FRAME_TYPES: tuple[str, ...] = tuple(FRAME_CLASSES)


def sse(frame: Frame | Mapping[str, Any]) -> str:
    """Render one frame as an SSE data event.

    Serialisation is deliberately forgiving: `default=str` means a value the
    tool layer failed to normalise (a Decimal, a datetime, a numpy scalar)
    degrades to its string form instead of killing the stream mid-run with a
    TypeError. `ensure_ascii=False` keeps Indian symbol names and currency signs
    readable on the wire rather than escaping them.

    Args:
        frame: A :class:`Frame`, or a mapping already carrying a `type` key.

    Returns:
        The event text, `data: {json}\\n\\n`, with no `event:` line.

    Raises:
        ValueError: If a mapping is passed without a `type` key, which would
            reach the client as an undiscriminated frame it must drop.
    """
    if isinstance(frame, Frame):
        payload = frame.to_dict()
    else:
        payload = dict(frame)
        if "type" not in payload:
            raise ValueError("An SSE frame must carry a 'type' key")

    body = json.dumps(payload, default=str, ensure_ascii=False, separators=(",", ":"))
    return f"data: {body}\n\n"


def heartbeat() -> str:
    """Render an SSE comment that keeps an idle connection open.

    A comment rather than a frame, so the client needs no handling for it and
    no frame type is spent on a keepalive. Emit one when the queue has been
    empty for a while; a reverse proxy will otherwise close a stream that has
    gone quiet while the model thinks.

    Returns:
        The comment line, `: heartbeat\\n\\n`.
    """
    return ": heartbeat\n\n"
