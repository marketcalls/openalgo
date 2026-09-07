"""The bridge between agno's blocking run loop and the eventlet request worker.

This is the one file in the module where the wrong instinct produces code that
passes every local test and then wedges production, so the shape is explained
here rather than left to be inferred.

The crossing
------------

Production is `gunicorn --worker-class eventlet -w 1`. There is exactly one
worker, and everything it serves runs as a greenlet on one OS thread. Agno's
`agent.run(stream=True)` returns a plain `Iterator[RunOutputEvent]`, but pulling
the next event blocks on the model provider's socket, on a tool, and inside
LiteLLM's C-served TLS reads. A greenlet that blocks stops the hub, which is
every other request on the box, for as long as the model is thinking. That is
the whole reason this file exists.

So the run is driven on a **real OS thread** and the frames come back over a
**real queue**, both from `utils.real_threading`, which resolves to the
unpatched originals under eventlet::

    green request handler                     real OS thread
    ---------------------                     --------------
    route builds the Agent            ->      agent.run(stream=True)
                                              translate each agno event
                                              real_queue.put(frame)
    drain with get_nowait()           <-
    yield "data: {...}\\n\\n"

Four rules follow from that picture, and each one is load-bearing:

* **The green side never blocks on the queue.** `get_nowait()` plus a short
  `time.sleep` between empty reads. A blocking `get()` on a real queue would
  freeze the worker, and a green queue would never be woken by a real thread's
  `put` at all: the waiter simply sits out its whole timeout.
* **The real side never touches a green primitive.** Its only wait is
  `Event.wait()` on the real stop event, which is a real `Condition` and never
  reaches the hub. In particular it does not call `time.sleep`, which eventlet
  has monkey-patched into a hub switch by the time this module is imported.
* **A heartbeat comment goes out while the queue is quiet**, so a reverse proxy
  does not close a stream that has gone silent for the thirty seconds a
  reasoning model spends thinking.
* **A dropped connection cancels the run and joins the thread.** The worker
  never restarts, so a thread leaked per abandoned request accumulates for the
  life of the process, still billing tokens to a browser that has gone away.

Cancelling from the right world
-------------------------------

`agent.cancel_run(run_id)` looks like a trivial dict write, and it is, but
agno's `InMemoryRunCancellationManager` guards that dict with a
`threading.Lock` built after eventlet has monkey-patched the stdlib, which makes
it **green**. The real agent thread already takes that lock on every
`raise_if_cancelled` check. If a greenlet took it too, the two worlds would
contend on it, and that is precisely the failure CLAUDE.md documents: the hub
tries to resume a waiter belonging to another OS thread, raises
`greenlet.error: Cannot switch to a different thread`, and the loser is wedged
for good.

So :func:`request_cancel` performs the cancel on a throwaway **real** thread.
No greenlet ever touches agno's lock, in this file or in the blueprint's cancel
route, which should call this function rather than agno directly.

Why there is no agno import here
--------------------------------

Events are read by their `event` string and their public attributes, never by
`isinstance`. Two things fall out of that: the translator is testable by feeding
it plain objects, with no provider and no agent anywhere near the test, and
`frames.py`'s rule that the wire contract stays importable without agno extends
one module further out. The event names are pinned as constants below and were
read off `agno==3.0.5`; an event this file does not name is ignored, so a new
one in a later release is inert rather than fatal.

Session hygiene
---------------

The producer thread runs tool code, which reaches OpenAlgo's services, which
open `scoped_session`s. Those are thread-local, so the Flask
`teardown_appcontext` that cleans up the greenlet's sessions never sees the
ones this thread opened. It calls `remove_all_scoped_sessions()` in its own
`finally` for exactly the reason `utils/db_sessions.py` exists.

None of this can be reproduced on the dev server: `uv run app.py` patches
nothing, so every primitive here behaves correctly whatever it is made of.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from services.agent import chatgpt_oauth
from services.agent.catalog import estimate_cost
from services.agent.frames import (
    Confirm,
    Done,
    DoneReason,
    Error,
    ErrorKind,
    Frame,
    Reasoning,
    Start,
    Token,
    ToolEnd,
    ToolStart,
    Usage,
    heartbeat,
    sse,
)
from services.agent.safety.audit import redact
from utils import real_threading
from utils.db_sessions import remove_all_scoped_sessions
from utils.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Agno's event vocabulary, read off agno==3.0.5 (`agno.run.agent.RunEvent`).
#
# Named as constants rather than imported so this module stays free of agno.
# An event not listed here is ignored by the translator.
# ---------------------------------------------------------------------------

EVENT_RUN_STARTED = "RunStarted"
EVENT_RUN_CONTENT = "RunContent"
EVENT_RUN_COMPLETED = "RunCompleted"
EVENT_RUN_ERROR = "RunError"
EVENT_RUN_CANCELLED = "RunCancelled"
EVENT_RUN_PAUSED = "RunPaused"
EVENT_RUN_CONTINUED = "RunContinued"
EVENT_TOOL_CALL_STARTED = "ToolCallStarted"
EVENT_TOOL_CALL_COMPLETED = "ToolCallCompleted"
EVENT_TOOL_CALL_ERROR = "ToolCallError"
EVENT_REASONING_STEP = "ReasoningStep"
EVENT_REASONING_CONTENT_DELTA = "ReasoningContentDelta"
EVENT_MODEL_REQUEST_COMPLETED = "ModelRequestCompleted"

# ---------------------------------------------------------------------------
# Tuning. Every value here is a trade between latency, syscalls and safety.
# ---------------------------------------------------------------------------

#: How long the green side sleeps between empty reads. Short enough that a
#: token is not perceptibly delayed, long enough that an idle stream is not a
#: busy loop. The sleep is eventlet's, so the hub runs during it.
DRAIN_POLL_SECONDS = 0.02

#: Emit an SSE comment when nothing has been written for this long. nginx's
#: default `proxy_read_timeout` is 60s and Cloudflare's is 100s; a reasoning
#: model can easily be quiet for a minute before its first token.
HEARTBEAT_SECONDS = 15.0

#: How long the green side waits for the producer thread after the stream ends
#: or the client disappears. A cancelled run usually stops within one event.
JOIN_TIMEOUT_SECONDS = 5.0

#: How long to wait for the throwaway thread that asks agno to cancel.
CANCEL_JOIN_TIMEOUT_SECONDS = 2.0

#: Frames buffered before the producer waits for the consumer. Backpressure
#: rather than an unbounded buffer: a client that stops reading must not grow
#: the worker's heap by the whole answer.
QUEUE_MAXSIZE = 4096

#: How long the producer waits when the queue is full before looking at the
#: stop flag again.
BACKPRESSURE_WAIT_SECONDS = 0.1

#: Yield to the hub every this many frames during a fast burst. Writing to the
#: socket usually yields on its own, but only once the send buffer fills.
YIELD_EVERY_FRAMES = 64

#: Sentinel put on the queue by the producer's `finally`. Its arrival is the
#: only thing that ends the green loop normally.
_END = object()


# ---------------------------------------------------------------------------
# Exception classification
# ---------------------------------------------------------------------------

# Matched against every class name in the exception's MRO, so a subclass of a
# named error classifies the same way. Names, not classes, to keep agno and
# litellm out of this module's imports.
_CANCELLED_ERROR_NAMES: frozenset[str] = frozenset({"RunCancelledException"})

_PROVIDER_ERROR_NAMES: frozenset[str] = frozenset(
    {
        "APIConnectionError",
        "APIError",
        "AuthenticationError",
        "BadRequestError",
        "ContentPolicyViolationError",
        "ContextWindowExceededError",
        "InternalServerError",
        "ModelAuthenticationError",
        "ModelProviderError",
        "ModelRateLimitError",
        "NotFoundError",
        "PermissionDeniedError",
        "RateLimitError",
        "RemoteServerUnavailableError",
        "RetryableModelProviderError",
        "ServiceUnavailableError",
        "Timeout",
        "UnprocessableEntityError",
    }
)

_TOOL_ERROR_NAMES: frozenset[str] = frozenset(
    {"AgentRunException", "RetryAgentRun", "StopAgentRun"}
)

_INPUT_ERROR_NAMES: frozenset[str] = frozenset(
    {"InputCheckError", "LookupError", "OutputCheckError", "ValueError"}
)


def _kind_for_name(*names: str) -> str:
    """Classify a failure from the names of the exception classes involved.

    Args:
        *names: Class names, most specific first. The MRO of a raised
            exception, or the single `error_type` string agno puts on a
            `RunError` event.

    Returns:
        One of :class:`~services.agent.frames.ErrorKind`. Anything unrecognised
        is `INTERNAL`, which is the honest answer: an unclassified failure is
        most likely a bug in this module rather than the provider's fault.
    """
    for name in names:
        if name in _PROVIDER_ERROR_NAMES:
            return ErrorKind.PROVIDER
        if name in _TOOL_ERROR_NAMES:
            return ErrorKind.TOOL
        if name in _INPUT_ERROR_NAMES:
            return ErrorKind.INPUT
    return ErrorKind.INTERNAL


def _is_cancellation(exc: BaseException) -> bool:
    """Whether an exception means the run was cancelled rather than broken."""
    return any(cls.__name__ in _CANCELLED_ERROR_NAMES for cls in type(exc).__mro__)


def _message_for_wire(value: Any) -> str:
    """Prepare a failure message for the browser and the log.

    The provider's own wording is kept, because "invalid API key" and "model not
    found" need different fixes and a generic string helps nobody. It is passed
    through the audit redactor first, which strips secret-shaped substrings and
    caps the length: a provider that echoes part of the request in its error
    text must not put a key on the wire, and an upstream that answers with an
    HTML error page must not put the page on it either.

    Args:
        value: Any object carrying the failure text.

    Returns:
        Redacted, length-capped text, never empty.
    """
    text = str(value or "").strip()
    if not text:
        return "The run failed without reporting a reason."
    redacted = redact(text)
    return redacted if isinstance(redacted, str) else str(redacted)


# ---------------------------------------------------------------------------
# Token and cost accounting
# ---------------------------------------------------------------------------


@dataclass
class _Totals:
    """Token counts for the turn so far.

    Mutable and touched only by the producer thread, which is single-threaded
    with respect to this object: the green side sees these numbers only as
    already-frozen :class:`~services.agent.frames.Usage` frames.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0

    def add(self, other: _Totals) -> None:
        """Accumulate another model call's counts into this turn's total."""
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.total_tokens += other.total_tokens
        self.cached_tokens += other.cached_tokens
        self.reasoning_tokens += other.reasoning_tokens

    def replace(self, other: _Totals) -> None:
        """Adopt an authoritative run total in place of the accumulation."""
        self.input_tokens = other.input_tokens
        self.output_tokens = other.output_tokens
        self.total_tokens = other.total_tokens
        self.cached_tokens = other.cached_tokens
        self.reasoning_tokens = other.reasoning_tokens

    def is_empty(self) -> bool:
        """Whether nothing has been counted yet."""
        return not (
            self.input_tokens
            or self.output_tokens
            or self.total_tokens
            or self.cached_tokens
            or self.reasoning_tokens
        )


def _int_or_zero(value: Any) -> int:
    """Coerce a reported token count to a non-negative int.

    Providers occasionally report a count as a float or a string, and agno
    passes whatever it was given straight through.
    """
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


# Set once if the catalog cannot price a call, so a broken or absent price
# table costs one log line per worker rather than one per model request.
_cost_lookup_warned = False


def _estimate_cost_usd(model: str | None, totals: _Totals) -> float | None:
    """Price a turn from LiteLLM's own table, or report that it cannot be.

    Cost is arithmetic over data the catalog already reads, never a second API
    call and never a guess. A model absent from the price table returns None,
    which the client renders as an unknown price beside real token counts.

    Args:
        model: The model id the provider billed.
        totals: The turn's accumulated token counts.

    Returns:
        The cost in US dollars, or None when it cannot be established.
    """
    global _cost_lookup_warned

    if not model or totals.is_empty():
        return None

    try:
        value = estimate_cost(
            model,
            input_tokens=totals.input_tokens,
            output_tokens=totals.output_tokens,
            cached_tokens=totals.cached_tokens,
        )
    except Exception:
        # Pricing is advisory. A price table that will not load must cost the
        # operator a log line, never the answer they are waiting for.
        if not _cost_lookup_warned:
            _cost_lookup_warned = True
            logger.exception("Agent cost estimation failed; reporting tokens without a price")
        return None

    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# The translator
# ---------------------------------------------------------------------------


class EventTranslator:
    """Turns one agno run's events into the frames the browser receives.

    All state lives here and is touched only by the producer thread, which sees
    one event at a time in order. The class is public because the only sane way
    to test the stream is to feed it synthetic events: anything with an `event`
    attribute and the fields that event carries will do, with no provider, no
    agent and no database in sight.

    Three measured agno behaviours are handled here rather than by the client:

    * a paused run **terminates the stream** with a `confirm` frame and no
      `done`, so nothing is synthesised to fill the gap;
    * a failed tool call is reported twice, as a `ToolCallCompleted` carrying an
      error and then a separate `ToolCallError`, so the second is suppressed;
    * an event this class does not name is ignored, so a later agno release
      adding one cannot break a run.

    Attributes:
        conversation_id: The `ag_conversation` row every frame belongs to.
        run_id: Agno's run id, learned from the first event that carries one.
        session_id: Agno's session id, learned the same way.
    """

    def __init__(
        self,
        conversation_id: int | str,
        *,
        model: str | None = None,
        tool_frames: Callable[[str, Any], Iterable[Frame]] | None = None,
        user_message_id: int | str = "",
    ) -> None:
        """Build a translator for one run.

        Args:
            conversation_id: The conversation this run belongs to, echoed in
                the `start` frame so the client can attribute the stream.
            model: The model id resolved before the run began. Used for pricing
                and in the `usage` frame until the provider reports its own.
            tool_frames: Optional hook called with `(tool_name, result)` after
                each tool finishes, returning extra frames to emit. This is how
                a `render_ui` or chart tool gets its `ui` and `chart_command`
                frames onto the wire without this module knowing those tools
                exist. A hook that raises is logged and ignored; a broken
                visualization must not kill the answer it belongs to.
        """
        self.conversation_id = conversation_id
        self.user_message_id = user_message_id
        self.run_id: str = ""
        self.session_id: str = ""

        self._model = model
        # The id resolved from the operator's own row, kept separately because
        # `_usage_frame` overwrites `self._model` with whatever the provider
        # reported. That reported name can arrive bare, and a bare subscription
        # name is unrecognisable: `catalog.get_model_meta("gpt-5.3-instant")`
        # answers None, having no bare entry at all, and each of the eight names
        # shared with the API answers OpenAI's PRICED row, which is worse than
        # answering nothing. The `chatgpt/` prefix is the only
        # working signal, and this is where it survives.
        self._resolved_model = model
        self._tool_frames = tool_frames

        self._started = False
        self._paused = False
        self._done_emitted = False

        self._totals = _Totals()
        self._last_usage: tuple[Any, ...] | None = None
        self._ttft_ms: float | None = None
        self._provider_ttft_ms: float | None = None
        self._run_began_at = time.monotonic()

        self._tool_started_at: dict[str, float] = {}
        self._tool_names: dict[str, str] = {}
        self._errored_tools: set[str] = set()
        self._last_tool_call_id = ""
        self._synthetic_tool_calls = 0

        self._dispatch: Mapping[str, Callable[[Any], list[Frame]]] = {
            EVENT_RUN_STARTED: self._on_ignored,
            EVENT_RUN_CONTINUED: self._on_ignored,
            EVENT_RUN_CONTENT: self._on_run_content,
            EVENT_REASONING_STEP: self._on_reasoning,
            EVENT_REASONING_CONTENT_DELTA: self._on_reasoning,
            EVENT_TOOL_CALL_STARTED: self._on_tool_call_started,
            EVENT_TOOL_CALL_COMPLETED: self._on_tool_call_completed,
            EVENT_TOOL_CALL_ERROR: self._on_tool_call_error,
            EVENT_MODEL_REQUEST_COMPLETED: self._on_model_request_completed,
            EVENT_RUN_PAUSED: self._on_run_paused,
            EVENT_RUN_ERROR: self._on_run_error,
            EVENT_RUN_CANCELLED: self._on_run_cancelled,
            EVENT_RUN_COMPLETED: self._on_run_completed,
        }

    # -- properties ---------------------------------------------------------

    @property
    def paused(self) -> bool:
        """Whether the run ended by pausing for a confirmation."""
        return self._paused

    @property
    def finished(self) -> bool:
        """Whether a terminal frame has already been emitted."""
        return self._paused or self._done_emitted

    # -- entry points -------------------------------------------------------

    def translate(self, event: Any) -> list[Frame]:
        """Convert one agno event into zero or more frames.

        Args:
            event: Any object with an `event` attribute naming the agno event
                and the public fields that event carries.

        Returns:
            The frames to write, in order. Empty for an event that has no
            representation on the wire, which is most of them.
        """
        name = getattr(event, "event", "") or ""
        frames = self._ensure_started(event)
        handler = self._dispatch.get(name)
        if handler is not None:
            frames.extend(handler(event))
        return frames

    def finalise(self) -> list[Frame]:
        """Close off a stream whose event iterator ended.

        Returns:
            A `done` frame when the run stopped without saying so, and nothing
            at all when it already ended properly. **A paused run gets no done
            frame**: agno terminates the stream on the pause, the client is
            waiting on the `confirm` it already received, and a synthesised
            done would be read as the turn having finished.
        """
        if self.finished:
            return []
        self._done_emitted = True
        return [Done(reason=DoneReason.INCOMPLETE)]

    def fail(self, exc: BaseException) -> list[Frame]:
        """Close off a stream whose iterator raised.

        Args:
            exc: The exception that escaped the agno iterator.

        Returns:
            A `done(cancelled)` when the run was cancelled, otherwise an
            `error` naming the layer that failed followed by a
            `done(incomplete)`. Nothing at all if the run had already ended,
            which happens when a failure surfaces after the terminal event.
        """
        if self.finished:
            return []
        self._done_emitted = True
        if _is_cancellation(exc):
            return [Done(reason=DoneReason.CANCELLED)]
        kind = _kind_for_name(*(cls.__name__ for cls in type(exc).__mro__))
        return [
            Error(message=_message_for_wire(exc), kind=kind),
            Done(reason=DoneReason.INCOMPLETE),
        ]

    # -- helpers ------------------------------------------------------------

    def _ensure_started(self, event: Any) -> list[Frame]:
        """Emit the `start` frame from whichever event arrives first.

        A resumed run opens with `RunContinued` rather than `RunStarted`, and a
        provider that answers instantly can put content first, so the start
        frame is derived from the first event of any kind rather than from one
        named event. That also guarantees the client learns the run id before
        any token, which is what makes the run cancellable.
        """
        if self._started:
            return []
        self._started = True
        self.run_id = str(getattr(event, "run_id", "") or "")
        self.session_id = str(getattr(event, "session_id", "") or "")
        return [
            Start(
                run_id=self.run_id,
                session_id=self.session_id,
                conversation_id=self.conversation_id,
                user_message_id=self.user_message_id,
            )
        ]

    def _on_ignored(self, event: Any) -> list[Frame]:
        """Consume an event whose only contribution is the `start` frame."""
        return []

    def _note_first_output(self) -> None:
        """Record time to first token, measured from this side of the wire.

        One definition throughout: from the moment the run was dispatched to
        the first character the operator could see, whether that is prose or a
        reasoning delta. It therefore includes agno's setup and any tool call
        the model made before saying anything, which is the wait the operator
        actually sat through rather than the model's internal latency.

        The provider's own `time_to_first_token` is kept separately and used
        only when a run produced no visible output at all, so the number never
        changes meaning depending on which events happened to arrive first.
        """
        if self._ttft_ms is None:
            self._ttft_ms = (time.monotonic() - self._run_began_at) * 1000.0

    def _note_provider_ttft(self, seconds: Any) -> None:
        """Keep the provider's own time to first token as a fallback."""
        if self._provider_ttft_ms is None and isinstance(seconds, (int, float)) and seconds >= 0:
            self._provider_ttft_ms = float(seconds) * 1000.0

    def _ttft(self) -> float | None:
        """The time to first token to report, ours preferred over theirs."""
        return self._ttft_ms if self._ttft_ms is not None else self._provider_ttft_ms

    def _on_run_content(self, event: Any) -> list[Frame]:
        """Translate one delta of the assistant's answer.

        Reasoning models interleave their trace into the same event, so both
        fields are read. Content that is not a string is a structured output
        object rather than prose and is deliberately dropped: the run's final
        value is returned to the caller by other means, and stringifying a
        model here would put a Python repr in the chat.
        """
        frames: list[Frame] = []

        reasoning = getattr(event, "reasoning_content", None)
        if isinstance(reasoning, str) and reasoning:
            self._note_first_output()
            frames.append(Reasoning(delta=reasoning))

        content = getattr(event, "content", None)
        if isinstance(content, str) and content:
            self._note_first_output()
            frames.append(Token(delta=content))

        return frames

    def _on_reasoning(self, event: Any) -> list[Frame]:
        """Translate a reasoning step or a reasoning delta.

        `ReasoningStep` carries a structured step whose text lives in
        `reasoning_content`; `ReasoningContentDelta` carries only the text. The
        structured `content` is used solely as a fallback and only when it is
        already a string.
        """
        text = getattr(event, "reasoning_content", None)
        if not isinstance(text, str) or not text:
            candidate = getattr(event, "content", None)
            text = candidate if isinstance(candidate, str) else None
        if not text:
            return []
        self._note_first_output()
        return [Reasoning(delta=text)]

    def _tool_identity(self, event: Any) -> tuple[str, str, Any]:
        """Resolve the call id, tool name and `ToolExecution` for an event.

        Agno carries all three on a `tool` object, but a call id is optional
        there. A call with no id is given a synthetic one so its start and end
        still pair up on the client, and the most recent id is remembered so a
        later error event with no id of its own attaches to the right call.

        Returns:
            A tuple of `(call_id, tool_name, tool_execution_or_None)`.
        """
        execution = getattr(event, "tool", None)
        name = str(getattr(execution, "tool_name", "") or "tool")

        raw_id = getattr(execution, "tool_call_id", None)
        if raw_id:
            call_id = str(raw_id)
        elif self._last_tool_call_id:
            call_id = self._last_tool_call_id
        else:
            self._synthetic_tool_calls += 1
            call_id = f"{name}#{self._synthetic_tool_calls}"

        self._last_tool_call_id = call_id
        if name != "tool":
            self._tool_names[call_id] = name
        else:
            name = self._tool_names.get(call_id, name)
        return call_id, name, execution

    def _tool_duration(self, call_id: str, execution: Any) -> float | None:
        """Seconds the call took, from agno's own timer or from ours.

        The start time is dropped whichever source wins, so the bookkeeping
        holds only the calls still in flight rather than every call of the run.
        """
        started_at = self._tool_started_at.pop(call_id, None)
        metrics = getattr(execution, "metrics", None)
        duration = getattr(metrics, "duration", None)
        if isinstance(duration, (int, float)) and duration >= 0:
            return float(duration)
        if started_at is None:
            return None
        return time.monotonic() - started_at

    def _hook_frames(self, name: str, result: Any) -> list[Frame]:
        """Run the tool-frames hook, never letting it break the run."""
        if self._tool_frames is None:
            return []
        try:
            return [frame for frame in self._tool_frames(name, result) if isinstance(frame, Frame)]
        except Exception:
            logger.exception("Agent tool frame hook failed for tool %s", name)
            return []

    def _on_tool_call_started(self, event: Any) -> list[Frame]:
        """Announce a dispatched tool call."""
        call_id, name, execution = self._tool_identity(event)
        self._tool_started_at[call_id] = time.monotonic()
        return [
            ToolStart(
                id=call_id,
                name=name,
                args=_safe_args(getattr(execution, "tool_args", None)),
            )
        ]

    def _on_tool_call_completed(self, event: Any) -> list[Frame]:
        """Report a finished tool call, successful or not.

        A completed call carrying `tool_call_error` is the **first** of agno's
        two reports of one failure. The id is recorded so the `ToolCallError`
        that follows can be dropped rather than shown as a second failure.
        """
        call_id, name, execution = self._tool_identity(event)
        failed = bool(getattr(execution, "tool_call_error", False))
        if failed:
            self._errored_tools.add(call_id)

        result = getattr(execution, "result", None)
        if result is None:
            result = getattr(event, "content", None)

        frames: list[Frame] = [
            ToolEnd(
                id=call_id,
                name=name,
                ok=not failed,
                result=redact(result),
                duration=self._tool_duration(call_id, execution),
            )
        ]
        if not failed:
            frames.extend(self._hook_frames(name, result))
        return frames

    def _on_tool_call_error(self, event: Any) -> list[Frame]:
        """Report a tool failure agno has not already reported.

        Agno emits `ToolCallCompleted` with an error flag and then a separate
        `ToolCallError` for the same call. Suppressing the second is what stops
        one failed order lookup appearing twice in the timeline.
        """
        call_id, name, execution = self._tool_identity(event)
        if call_id in self._errored_tools:
            self._errored_tools.discard(call_id)
            return []

        detail = getattr(event, "error", None) or getattr(execution, "result", None)
        return [
            ToolEnd(
                id=call_id,
                name=name,
                ok=False,
                result=_message_for_wire(detail),
                duration=self._tool_duration(call_id, execution),
            )
        ]

    def _usage_frame(self, model: str | None) -> list[Frame]:
        """Build a usage frame, unless it would say nothing new.

        Nothing is emitted for a turn whose token counts are all zero. Several
        providers report no usage at all on a streamed call, and a frame of
        zeros would be read as a free turn rather than as an unknown one.
        """
        if model:
            self._model = model

        if self._totals.is_empty():
            return []

        snapshot = (
            self._totals.input_tokens,
            self._totals.output_tokens,
            self._totals.total_tokens,
            self._totals.cached_tokens,
            self._totals.reasoning_tokens,
            self._model,
        )
        if snapshot == self._last_usage:
            return []
        self._last_usage = snapshot

        # A plan turn reports tokens and no cost. `estimate_cost` already answers
        # None for a `chatgpt/` model, but saying so here is what keeps the
        # frame's own `billing` field honest and stops the reported-cost patch
        # below from filling the gap back in with a zero.
        billing, cost_usd = chatgpt_oauth.apply_billing(
            self._model,
            _estimate_cost_usd(self._model, self._totals),
            resolved_model_id=self._resolved_model,
        )

        return [
            Usage(
                input_tokens=self._totals.input_tokens,
                output_tokens=self._totals.output_tokens,
                total_tokens=self._totals.total_tokens,
                cached_tokens=self._totals.cached_tokens,
                reasoning_tokens=self._totals.reasoning_tokens,
                cost_usd=cost_usd,
                billing=billing,
                model=self._model,
                ttft_ms=self._ttft(),
            )
        ]

    def _on_model_request_completed(self, event: Any) -> list[Frame]:
        """Accumulate one model call's tokens and report the turn's total.

        A turn makes one model call per tool round trip, so these arrive
        several times. Each frame carries the running total rather than the
        delta, which leaves the client with nothing to add up.
        """
        call = _Totals(
            input_tokens=_int_or_zero(getattr(event, "input_tokens", 0)),
            output_tokens=_int_or_zero(getattr(event, "output_tokens", 0)),
            total_tokens=_int_or_zero(getattr(event, "total_tokens", 0)),
            cached_tokens=_int_or_zero(getattr(event, "cache_read_tokens", 0)),
            reasoning_tokens=_int_or_zero(getattr(event, "reasoning_tokens", 0)),
        )
        self._totals.add(call)
        self._note_provider_ttft(getattr(event, "time_to_first_token", None))
        return self._usage_frame(getattr(event, "model", None))

    def _on_run_paused(self, event: Any) -> list[Frame]:
        """Hand the pending confirmations to the client and stop.

        This frame **terminates the stream**. Agno's iterator ends on a pause
        and no `done` follows, which is why :meth:`finalise` refuses to invent
        one: the turn has not finished, it is waiting for a human.
        """
        self._paused = True
        requirements = _requirement_payloads(event)
        return [
            Confirm(
                run_id=self.run_id or str(getattr(event, "run_id", "") or ""),
                session_id=self.session_id or str(getattr(event, "session_id", "") or ""),
                requirements=requirements,
            )
        ]

    def _on_run_error(self, event: Any) -> list[Frame]:
        """Report a failed run.

        No `done` is emitted here. The iterator is still running as far as this
        class knows, and :meth:`finalise` writes `done(incomplete)` when it
        ends, which keeps "how did this turn end" answered by exactly one place.
        """
        kind = _kind_for_name(str(getattr(event, "error_type", "") or ""))
        return [Error(message=_message_for_wire(getattr(event, "content", None)), kind=kind)]

    def _on_run_cancelled(self, event: Any) -> list[Frame]:
        """End a run that was cancelled, by the client or by an operator."""
        if self._done_emitted:
            return []
        self._done_emitted = True
        return [Done(reason=DoneReason.CANCELLED)]

    def _on_run_completed(self, event: Any) -> list[Frame]:
        """Report final usage and end the run.

        The event's `content` holds the whole answer, which has already been
        streamed delta by delta and is deliberately not re-sent. Its `metrics`
        hold the run total, which supersedes the per-call accumulation rather
        than adding to it.
        """
        frames: list[Frame] = []
        metrics = getattr(event, "metrics", None)
        if metrics is not None:
            total = _Totals(
                input_tokens=_int_or_zero(getattr(metrics, "input_tokens", 0)),
                output_tokens=_int_or_zero(getattr(metrics, "output_tokens", 0)),
                total_tokens=_int_or_zero(getattr(metrics, "total_tokens", 0)),
                cached_tokens=_int_or_zero(getattr(metrics, "cache_read_tokens", 0)),
                reasoning_tokens=_int_or_zero(getattr(metrics, "reasoning_tokens", 0)),
            )
            if not total.is_empty():
                self._totals.replace(total)

            self._note_provider_ttft(getattr(metrics, "time_to_first_token", None))
            frames.extend(self._usage_frame(None))
            frames = _apply_reported_cost(frames, metrics)
        else:
            frames.extend(self._usage_frame(None))

        if not self._done_emitted:
            self._done_emitted = True
            frames.append(Done(reason=DoneReason.STOP))
        return frames


def _apply_reported_cost(frames: list[Frame], metrics: Any) -> list[Frame]:
    """Fall back to agno's own cost when the local price table has none.

    The catalog is the primary source, because it is read from LiteLLM's price
    data and is the same number the settings screen shows. When the model is
    absent from that table but the provider reported a cost, using it beats
    reporting nothing; it is still a computed figure rather than a guess.

    **A subscription turn is skipped entirely.** LiteLLM cannot price a
    `chatgpt/` model and does not pretend to, but its `completion_cost` answers
    `0.0` rather than None for a model it has no entry for, and agno hands that
    straight through as `metrics.cost`. Patching it in would render `$0.00` under
    an answer that consumed the operator's plan quota, which is the one number
    less true than no number at all.
    """
    reported = getattr(metrics, "cost", None)
    if reported is None:
        return frames
    try:
        cost = float(reported)
    except (TypeError, ValueError):
        return frames

    patched: list[Frame] = []
    for frame in frames:
        if (
            isinstance(frame, Usage)
            and frame.cost_usd is None
            and frame.billing != chatgpt_oauth.BILLING_SUBSCRIPTION
        ):
            patched.append(
                Usage(
                    input_tokens=frame.input_tokens,
                    output_tokens=frame.output_tokens,
                    total_tokens=frame.total_tokens,
                    cached_tokens=frame.cached_tokens,
                    reasoning_tokens=frame.reasoning_tokens,
                    cost_usd=cost,
                    billing=frame.billing,
                    model=frame.model,
                    ttft_ms=frame.ttft_ms,
                )
            )
        else:
            patched.append(frame)
    return patched


def _requirement_payloads(event: Any) -> list[dict[str, Any]]:
    """Describe what a paused run is waiting for, in wire-safe dicts.

    Agno gives the same information two ways: `requirements`, each wrapping one
    `ToolExecution`, and a flat `tools` list. The first is preferred because it
    carries the requirement id the resume call needs; the second is the
    fallback.

    Args:
        event: The `RunPaused` event.

    Returns:
        One dict per pending decision, with the tool name and the arguments the
        operator is being asked to approve. Arguments are redacted, because
        this is model-supplied text on its way to a browser.
    """
    payloads: list[dict[str, Any]] = []

    for requirement in getattr(event, "requirements", None) or ():
        execution = getattr(requirement, "tool_execution", None)
        if execution is None:
            continue
        payloads.append(
            {
                "id": str(getattr(requirement, "id", "") or ""),
                "tool_call_id": str(getattr(execution, "tool_call_id", "") or ""),
                "tool_name": str(getattr(execution, "tool_name", "") or ""),
                "args": _safe_args(getattr(execution, "tool_args", None)),
                "kind": _requirement_kind(execution),
            }
        )

    if payloads:
        return payloads

    for execution in getattr(event, "tools", None) or ():
        if not getattr(execution, "is_paused", False):
            continue
        payloads.append(
            {
                "id": "",
                "tool_call_id": str(getattr(execution, "tool_call_id", "") or ""),
                "tool_name": str(getattr(execution, "tool_name", "") or ""),
                "args": _safe_args(getattr(execution, "tool_args", None)),
                "kind": _requirement_kind(execution),
            }
        )
    return payloads


def _requirement_kind(execution: Any) -> str:
    """Name what a paused tool call is waiting for."""
    if getattr(execution, "requires_confirmation", False):
        return "confirmation"
    if getattr(execution, "requires_user_input", False):
        return "user_input"
    if getattr(execution, "external_execution_required", False):
        return "external_execution"
    return "confirmation"


def _safe_args(args: Any) -> dict[str, Any]:
    """Redact and bound a tool's arguments for display."""
    if not isinstance(args, Mapping):
        return {}
    safe = redact(args)
    return safe if isinstance(safe, dict) else {}


# ---------------------------------------------------------------------------
# The crossing
# ---------------------------------------------------------------------------


class _RunHandle:
    """The few facts about a run that cross from the real thread to the hub.

    Every field is written once by the producer thread and read by the greenlet
    draining the queue. Each write is a single assignment of an immutable value
    and there is no read-modify-write anywhere, so the GIL is sufficient and no
    lock is taken. That matters: a lock shared between these two worlds is the
    exact hazard this module exists to avoid, and there is nothing here worth
    taking one for.
    """

    __slots__ = ("finished", "run_id", "session_id")

    def __init__(self) -> None:
        self.run_id: str = ""
        self.session_id: str = ""
        self.finished: bool = False

    def observe(self, event: Any) -> None:
        """Learn the run and session ids from an event, as early as possible.

        Read from the raw event rather than from the `start` frame so that a
        client which disconnects during the very first event can still be
        cancelled.
        """
        if not self.run_id:
            run_id = getattr(event, "run_id", None)
            if run_id:
                self.run_id = str(run_id)
        if not self.session_id:
            session_id = getattr(event, "session_id", None)
            if session_id:
                self.session_id = str(session_id)


def request_cancel(agent: Any, run_id: str) -> None:
    """Ask agno to cancel a run, from a world that is safe to ask from.

    **Call this instead of `agent.cancel_run()` anywhere a greenlet is
    running**, which includes every Flask route. Agno guards its cancellation
    registry with a `threading.Lock` created after eventlet has monkey-patched
    the stdlib, so that lock is green, and the real thread driving the run takes
    it on every cancellation check. A greenlet contending on it is how the hub
    ends up trying to resume a waiter that belongs to another OS thread, which
    raises `greenlet.error: Cannot switch to a different thread` and wedges
    whichever side lost. The work itself is a dictionary write, so handing it to
    a throwaway real thread costs nothing and keeps the hub off that lock.

    Never raises: cancellation is best effort, and the caller is usually already
    unwinding a dropped connection.

    Args:
        agent: The agno agent driving the run.
        run_id: The run to cancel. Ignored when empty, which means the run had
            not reported an id yet.
    """
    if not run_id:
        return

    def _cancel() -> None:
        try:
            agent.cancel_run(run_id)
        except Exception:
            logger.exception("Failed to cancel agent run %s", run_id)

    try:
        thread = real_threading.Thread(
            target=_cancel,
            name=f"agent-cancel-{run_id[:8]}",
            daemon=True,
        )
        thread.start()
    except Exception:
        logger.exception("Could not start the cancel thread for agent run %s", run_id)
        return

    # Joined so the thread is reaped rather than left for a worker that never
    # restarts to accumulate. It writes one dictionary entry, so this returns
    # almost immediately; the timeout only exists so a wedged lock cannot hold
    # up the request teardown.
    if not real_threading.join(thread, timeout=CANCEL_JOIN_TIMEOUT_SECONDS):
        logger.warning("Cancel thread for agent run %s did not finish in time", run_id)


def _offer(queue: Any, item: Any, stop: Any) -> bool:
    """Hand one frame to the hub, waiting if the consumer is behind.

    Runs on the producer thread. The wait is `Event.wait()` on a **real** event,
    which blocks on a real condition variable and never reaches the eventlet
    hub, and which returns the instant the green side asks the run to stop.
    `time.sleep` would be wrong here: eventlet has replaced it with a hub
    switch, and calling that from this thread spins up a second hub inside it.

    There is exactly one producer, so `full()` followed by `put_nowait()` cannot
    race with anybody: nothing else adds to this queue.

    Args:
        queue: The real queue shared with the green side.
        item: A frame, or the end sentinel.
        stop: The real stop event.

    Returns:
        True if the item was queued, False if the run was asked to stop first.
    """
    while not stop.is_set():
        if not queue.full():
            queue.put_nowait(item)
            return True
        stop.wait(BACKPRESSURE_WAIT_SECONDS)
    return False


def _release_agent_db_session(agent: Any) -> None:
    """Release the agno session this thread bound, if it bound one.

    Agno's `SqliteDb` holds a `scoped_session`, which is thread-local, and a run
    happens on a fresh OS thread every time. Nothing else releases the session
    that thread opened: Flask's `teardown_appcontext` only ever sees the
    greenlet's, and `remove_all_scoped_sessions()` covers OpenAlgo's registry,
    which agno's database is deliberately not part of. Without this the
    connection goes back to agno's pool only when the dead thread's locals are
    collected, which is a garbage-collector promise rather than a release.

    Never raises: this runs in a `finally` beside the frames the operator is
    waiting for, and a database that will not tidy up must not lose them.

    Args:
        agent: The agno agent whose database may hold a session for this thread.
    """
    session_factory = getattr(getattr(agent, "db", None), "Session", None)
    remove = getattr(session_factory, "remove", None)
    if not callable(remove):
        return
    try:
        remove()
    except Exception:
        logger.exception("Failed to release the agno database session")


def _producer(
    agent: Any,
    make_iterator: Callable[[], Iterator[Any]],
    translator: EventTranslator,
    queue: Any,
    stop: Any,
    handle: _RunHandle,
) -> None:
    """Drive the agno run and translate it, on a real OS thread.

    Everything that can block lives inside this function: building the model,
    the provider's socket, every tool, and agno's own database writes. None of
    it may run on a greenlet.

    Args:
        agent: The agno agent, held only so this thread can release the session
            it bound on agno's database before it dies.
        make_iterator: Called here rather than by the caller, so a failure while
            starting the run becomes an `error` frame on the stream instead of
            an exception in the route after the headers have gone out.
        translator: The per-run translator.
        queue: The real queue the green side drains.
        stop: The real stop event, set when the client goes away.
        handle: Shared facts the green side reads.
    """
    events: Iterator[Any] | None = None
    try:
        events = make_iterator()
        for event in events:
            handle.observe(event)
            if stop.is_set():
                break
            for frame in translator.translate(event):
                if not _offer(queue, frame, stop):
                    return
        else:
            # Only when the iterator ran to its natural end. A `break` above
            # means the client left, and inventing a terminal frame for a
            # stream nobody is reading is pointless.
            for frame in translator.finalise():
                if not _offer(queue, frame, stop):
                    return
    except Exception as exc:
        if _is_cancellation(exc):
            # The expected end of a cancelled run, not a fault. A traceback
            # here would make every client disconnect look like a defect.
            logger.info("Agent run %s was cancelled", handle.run_id or "unknown")
        else:
            logger.exception("Agent run failed for run_id %s", handle.run_id or "unknown")
        for frame in translator.fail(exc):
            if not _offer(queue, frame, stop):
                break
    finally:
        handle.finished = True

        # Closing the iterator raises GeneratorExit inside agno's run loop,
        # which is what releases the provider connection when this thread stops
        # early. Without it the socket stays open until the object is collected.
        closer = getattr(events, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                logger.exception("Failed to close the agno event iterator")

        # Tools open scoped sessions on this thread, and Flask's teardown only
        # ever sees the greenlet's. Left behind, each one holds a connection in
        # a worker that never restarts.
        remove_all_scoped_sessions()
        _release_agent_db_session(agent)

        # Unconditional: the green loop ends on this sentinel and on nothing
        # else. put_nowait rather than _offer because stop may already be set,
        # and a full queue here means the client has stopped reading anyway.
        try:
            queue.put_nowait(_END)
        except Exception:
            logger.exception("Could not signal the end of the agent stream")


def _pump(
    agent: Any,
    make_iterator: Callable[[], Iterator[Any]],
    translator: EventTranslator,
    *,
    label: str,
) -> Iterator[str]:
    """Run an agno stream on a real thread and yield SSE text from the hub.

    This generator is the green half of the crossing. It never blocks on the
    queue and never waits on anything the producer holds.

    Args:
        agent: The agno agent, needed only to cancel the run.
        make_iterator: Builds the agno event iterator. Called on the producer
            thread.
        translator: The per-run translator.
        label: Short name for the thread, for a stack dump to be readable.

    Yields:
        SSE text: `data:` frames, and `:` heartbeat comments while quiet.
    """
    queue = real_threading.Queue(maxsize=QUEUE_MAXSIZE)
    stop = real_threading.Event()
    handle = _RunHandle()

    thread = real_threading.Thread(
        target=_producer,
        args=(agent, make_iterator, translator, queue, stop, handle),
        name=f"agent-{label}",
        daemon=True,
    )
    thread.start()

    client_gone = False
    written = 0
    try:
        # Flush the response head before the model has said anything, so the
        # browser and every proxy in between commit to the connection now
        # rather than after the first token.
        yield heartbeat()
        last_write = time.monotonic()

        while True:
            # Read liveness first. If the thread is already gone and the queue
            # then reads empty, nothing further can arrive; the other order
            # would let the sentinel land in the gap and be dropped.
            alive = thread.is_alive()
            try:
                item = queue.get_nowait()
            except real_threading.Empty:
                if not alive:
                    break
                now = time.monotonic()
                if now - last_write >= HEARTBEAT_SECONDS:
                    last_write = now
                    yield heartbeat()
                time.sleep(DRAIN_POLL_SECONDS)
                continue

            if item is _END:
                break

            last_write = time.monotonic()
            written += 1
            yield sse(item)

            # A fast burst can otherwise hold the hub for as long as the socket
            # accepts writes without blocking. sleep(0) is eventlet's yield.
            if written % YIELD_EVERY_FRAMES == 0:
                time.sleep(0)
    except GeneratorExit:
        # The client hung up. Flask closes the generator here, and the run is
        # still going: without the cancel below it would keep calling the
        # provider, and keep billing, for a browser that has gone.
        client_gone = True
        raise
    finally:
        stop.set()
        if client_gone and not handle.finished:
            logger.info(
                "Agent stream client disconnected; cancelling run %s",
                handle.run_id or "unknown",
            )
            request_cancel(agent, handle.run_id)
        if not real_threading.join(thread, timeout=JOIN_TIMEOUT_SECONDS):
            # Daemon, so it cannot hold the process open, and it drops its work
            # the moment it looks at the stop event. Worth a line because a
            # thread outliving its stream is how a worker slowly fills up.
            logger.warning(
                "Agent run thread for %s did not stop within %ss",
                handle.run_id or "unknown",
                JOIN_TIMEOUT_SECONDS,
            )


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def stream_run(
    agent: Any,
    message: Any,
    *,
    conversation_id: int | str,
    session_id: str | None = None,
    user_id: str | None = None,
    model: str | None = None,
    tool_frames: Callable[[str, Any], Iterable[Frame]] | None = None,
    user_message_id: int | str = "",
    **run_kwargs: Any,
) -> Iterator[str]:
    """Stream one turn of a conversation as SSE text.

    The model must already be resolved and the agent already built: a bad model
    id has to fail as a clean HTTP error before the first byte, not halfway
    through a stream the client has committed to reading.

    Args:
        agent: The agno agent to run.
        message: The user's input, passed to `agent.run` positionally so it
            works whatever agno calls that parameter.
        conversation_id: The `ag_conversation` row this turn belongs to.
        session_id: Agno's session id for the conversation.
        user_id: The owning user, forwarded to agno's session store.
        model: The resolved model id, used for pricing until the provider
            reports its own.
        tool_frames: Optional hook turning a tool's result into extra frames.
            See :class:`EventTranslator`.
        **run_kwargs: Anything else `agent.run` accepts, such as `images`,
            `dependencies` or `session_state`.

    Yields:
        SSE text, ready to hand to a Flask response together with
        :data:`~services.agent.frames.SSE_HEADERS`.
    """
    translator = EventTranslator(
        conversation_id, model=model, tool_frames=tool_frames, user_message_id=user_message_id
    )

    def _start() -> Iterator[Any]:
        return agent.run(
            message,
            stream=True,
            stream_events=True,
            session_id=session_id,
            user_id=user_id,
            **run_kwargs,
        )

    return _pump(agent, _start, translator, label="run")


def stream_continue(
    agent: Any,
    *,
    run_id: str,
    session_id: str,
    conversation_id: int | str,
    decisions: Mapping[str, bool] | None = None,
    requirements: Any = None,
    note: str | None = None,
    user_id: str | None = None,
    model: str | None = None,
    tool_frames: Callable[[str, Any], Iterable[Frame]] | None = None,
    **continue_kwargs: Any,
) -> Iterator[str]:
    """Resume a paused run once the operator has approved or rejected its tools.

    The paused run is the one that ended with a `confirm` frame. Its stream had
    no `done`, and this call continues it in place: the same run id, the same
    session, the same conversation.

    `stream_events` is passed explicitly because `continue_run` defaults it to
    **False** where `run` leaves it unset. Without it agno yields the run's
    final output and nothing else, and the resumed turn arrives as a single
    silent block instead of a stream.

    Args:
        agent: The agno agent that owns the paused run.
        run_id: The paused run.
        session_id: The session the paused run belongs to. Agno refuses to
            resume from a run id without one.
        conversation_id: The `ag_conversation` row this turn belongs to.
        decisions: Approve or reject per pending call, keyed by tool call id or
            by requirement id. Requirements this mapping does not mention are
            left undecided, and agno pauses again on them, which is the right
            outcome for a partial answer rather than a silent approval.
        requirements: Already-decided agno requirement objects, for a caller
            that resolved them itself. Takes precedence over `decisions`.
        note: Reason recorded against every rejection, shown to the model so it
            can respond to the refusal rather than retrying blindly.
        user_id: The owning user, forwarded to agno's session store.
        model: The resolved model id, used for pricing.
        tool_frames: Optional hook turning a tool's result into extra frames.
        **continue_kwargs: Anything else `agent.continue_run` accepts.

    Yields:
        SSE text, exactly as :func:`stream_run` does.
    """
    translator = EventTranslator(conversation_id, model=model, tool_frames=tool_frames)

    def _start() -> Iterator[Any]:
        # Resolved on the producer thread, not here: it reads agno's session
        # database, and a failure has to become an `error` frame rather than an
        # exception raised after the response headers have been sent.
        resolved = requirements
        if resolved is None:
            resolved = _resolve_requirements(
                agent,
                run_id=run_id,
                session_id=session_id,
                user_id=user_id,
                decisions=decisions or {},
                note=note,
            )
        return agent.continue_run(
            run_id=run_id,
            session_id=session_id,
            user_id=user_id,
            requirements=resolved,
            stream=True,
            stream_events=True,
            **continue_kwargs,
        )

    return _pump(agent, _start, translator, label="continue")


def _resolve_requirements(
    agent: Any,
    *,
    run_id: str,
    session_id: str,
    user_id: str | None,
    decisions: Mapping[str, bool],
    note: str | None,
) -> list[Any]:
    """Apply the operator's decisions to a paused run's requirements.

    Runs on the producer thread. Loads the paused run from agno's own store,
    which is what makes a confirmation survive across two HTTP requests, and
    marks each requirement confirmed or rejected.

    Args:
        agent: The agno agent that owns the run.
        run_id: The paused run.
        session_id: The session the run belongs to.
        user_id: The owning user.
        decisions: Approve or reject, keyed by tool call id or requirement id.
        note: Reason recorded against a rejection.

    Returns:
        The requirement objects to hand to `continue_run`.

    Raises:
        LookupError: If the run is not in the store, which for the caller means
            an unknown or already-consumed run id.
        ValueError: If the run has nothing pending, or if no decision matched
            anything. Approving a call that is not waiting is a client bug, and
            resuming as though it had been approved would be an order placed on
            no authority at all.
    """
    run_output = agent.get_run_output(run_id=run_id, session_id=session_id, user_id=user_id)
    if run_output is None:
        raise LookupError(f"No paused run {run_id} in session {session_id}")

    requirements = list(getattr(run_output, "requirements", None) or ())
    if not requirements:
        raise ValueError(f"Run {run_id} has nothing awaiting a decision")

    applied = 0
    for requirement in requirements:
        if not getattr(requirement, "needs_confirmation", False):
            continue

        execution = getattr(requirement, "tool_execution", None)
        keys = (
            str(getattr(execution, "tool_call_id", "") or ""),
            str(getattr(requirement, "id", "") or ""),
        )
        decision: bool | None = None
        for key in keys:
            if key and key in decisions:
                decision = bool(decisions[key])
                break
        if decision is None:
            continue

        if decision:
            requirement.confirm()
        else:
            requirement.reject(note)
        applied += 1

    if not applied:
        raise ValueError(f"No decision in the request matched a pending call on run {run_id}")

    return requirements


__all__ = [
    "EventTranslator",
    "request_cancel",
    "stream_continue",
    "stream_run",
]
