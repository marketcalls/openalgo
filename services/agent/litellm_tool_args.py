"""Recover tool-call arguments the Responses bridge drops on parallel calls.

**The symptom.** A question naming two instruments ("history of TCS and INFY",
"news on BHEL and RELIANCE", "expiries for crude, gold and silver") failed every
tool call in the batch, each in a few milliseconds with ``Missing required
argument`` for every parameter, and the model retried until it fell back to one
call per turn, which worked. A question naming one instrument never failed.

**The cause, measured on the wire.** Every GPT-5 model with a reasoning effort,
and every ``chatgpt/`` subscription model, reaches LiteLLM's chat-completions
bridge over the Responses API
(``litellm.completion_extras.litellm_responses_transformation``). For a single
tool call the backend streams the arguments as ``function_call_arguments.delta``
events. For a batch of parallel calls it frequently sends **no deltas at all**:
each call's complete arguments arrive once, in
``response.function_call_arguments.done`` and again in
``response.output_item.done``. LiteLLM 1.104.0 builds the chat stream from the
``output_item.added`` event (id and name, empty arguments) and the deltas, and
deliberately ignores both ``done`` events on a per-stream iterator, so agno
assembles ``arguments: ""`` and pydantic refuses the call.

**The fix.** ``chunk_parser`` is wrapped per stream: it notes which output items
have already delivered argument text, and when a ``done`` event arrives for one
that has delivered none, it emits the complete arguments as a single delta at
the same tool-call index the bridge assigned. agno concatenates argument
fragments by index, so the call is whole by the time it runs. An item that did
stream its deltas is left untouched, so nothing is ever delivered twice.

Installed from ``builder._register_chatgpt_models`` next to the other LiteLLM
adjustments, never from a request path that must stay free of LiteLLM imports.
Idempotent, and silent on a LiteLLM whose bridge has a different shape: the
patch is a repair, and a LiteLLM it does not recognise costs the repair, not the
agent. Delete this module when LiteLLM emits the ``done`` arguments itself;
``test/test_agent_litellm_tool_args.py`` fails on duplicated arguments the day
that happens.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from utils.logging import get_logger
from utils.real_threading import Lock

logger = get_logger(__name__)

_TOOL_ITEM_TYPES = frozenset({"function_call", "custom_tool_call"})
_ADDED = "response.output_item.added"
_ITEM_DONE = "response.output_item.done"
_ARGS_DELTAS = frozenset(
    {"response.function_call_arguments.delta", "response.custom_tool_call_input.delta"}
)
_ARGS_DONE = "response.function_call_arguments.done"
_INPUT_DONE = "response.custom_tool_call_input.done"

#: Per-stream state kept on the iterator instance, named so it cannot collide
#: with an attribute LiteLLM adds later.
_STATE_ATTR = "_openalgo_tool_args_state"
_MARKER = "_openalgo_tool_args_patched"

_install_lock = Lock()
_installed = False


def _event_type(chunk: Mapping[str, Any]) -> str:
    """The event type as a plain string, whether LiteLLM handed an enum or text."""
    value = chunk.get("type")
    return str(getattr(value, "value", value) or "")


def _item_arguments(item: Any) -> str:
    """The complete argument text carried by a function or custom tool item."""
    if not isinstance(item, Mapping) or item.get("type") not in _TOOL_ITEM_TYPES:
        return ""
    value = item.get("arguments")
    if not value:
        value = item.get("input")
    return value if isinstance(value, str) else ""


def _state(iterator: Any) -> tuple[set[int], set[int]]:
    """The output indexes announced, and those whose arguments already streamed."""
    state = iterator.__dict__.get(_STATE_ATTR)
    if state is None:
        state = (set(), set())
        iterator.__dict__[_STATE_ATTR] = state
    return state


def recovered_arguments(iterator: Any, chunk: Any) -> tuple[int, str, dict[str, Any] | None] | None:
    """Decide whether this event carries arguments the caller has not received.

    Pure bookkeeping over the iterator's per-stream state, so it is testable
    without LiteLLM.

    Args:
        iterator: The stream iterator, which holds the per-stream state.
        chunk: One parsed Responses API event.

    Returns:
        ``(output_index, arguments, item)`` when the full arguments must be
        emitted now, ``item`` being the tool item when this event carries it
        and the announcement was missed. None when the bridge's own handling is
        complete.
    """
    if not isinstance(chunk, Mapping):
        return None
    event = _event_type(chunk)
    raw_index = chunk.get("output_index", 0)
    index = raw_index if isinstance(raw_index, int) else 0
    announced, streamed = _state(iterator)

    if event == _ADDED:
        item = chunk.get("item")
        if isinstance(item, Mapping) and item.get("type") in _TOOL_ITEM_TYPES:
            announced.add(index)
            if _item_arguments(item):
                streamed.add(index)
        return None

    if event in _ARGS_DELTAS:
        if chunk.get("delta"):
            streamed.add(index)
        return None

    item: Mapping[str, Any] | None = None
    if event == _ARGS_DONE:
        arguments = chunk.get("arguments")
    elif event == _INPUT_DONE:
        arguments = chunk.get("input")
    elif event == _ITEM_DONE:
        candidate = chunk.get("item")
        arguments = _item_arguments(candidate)
        item = candidate if isinstance(candidate, Mapping) else None
    else:
        return None

    if not isinstance(arguments, str) or not arguments or index in streamed:
        return None
    streamed.add(index)
    missed = item if (item is not None and index not in announced) else None
    announced.add(index)
    return index, arguments, missed


def _patched_chunk_parser(original: Any, iterator_cls: Any) -> Any:
    """Wrap the bridge's ``chunk_parser`` with the argument recovery."""

    def chunk_parser(self: Any, chunk: Any) -> Any:
        try:
            recovery = recovered_arguments(self, chunk)
            index_map = getattr(self, "_tool_call_index_map", None)
            if recovery is not None and isinstance(index_map, dict):
                return _emit(self, iterator_cls, index_map, *recovery)
        except Exception:
            logger.exception(
                "Could not recover streamed tool-call arguments; using LiteLLM's chunk"
            )
        return original(self, chunk)

    chunk_parser.__wrapped__ = original  # type: ignore[attr-defined]
    setattr(chunk_parser, _MARKER, True)
    return chunk_parser


def _emit(
    iterator: Any,
    iterator_cls: Any,
    index_map: dict[int, int],
    output_index: int,
    arguments: str,
    missed_item: Mapping[str, Any] | None,
) -> Any:
    """Build the chat chunk that delivers the complete arguments in one piece."""
    from litellm.types.llms.openai import ChatCompletionToolCallFunctionChunk
    from litellm.types.utils import (
        ChatCompletionToolCallChunk,
        Delta,
        ModelResponseStream,
        StreamingChoices,
    )

    tool_index = iterator_cls._sequential_tool_call_index(index_map, output_index)
    call_id = None
    name = None
    if missed_item is not None:
        # The announcement never reached the caller, so the id and the name
        # travel with the arguments; otherwise they were sent already and a
        # repeat would only be noise.
        call_id = missed_item.get("call_id") or missed_item.get("id")
        name = missed_item.get("name")
    chunk = ModelResponseStream(
        choices=[
            StreamingChoices(
                index=0,
                delta=Delta(
                    tool_calls=[
                        ChatCompletionToolCallChunk(
                            id=call_id,
                            index=tool_index,
                            type="function",
                            function=ChatCompletionToolCallFunctionChunk(
                                name=name, arguments=arguments
                            ),
                        )
                    ]
                ),
                finish_reason=None,
            )
        ]
    )
    scope = getattr(iterator, "_with_stream_scoped_id", None)
    return scope(chunk) if callable(scope) else chunk


def install() -> bool:
    """Patch LiteLLM's Responses-to-chat stream iterator. Idempotent.

    Returns:
        True when the patch is in place after this call.
    """
    global _installed
    with _install_lock:
        if _installed:
            return True
        try:
            from litellm.completion_extras.litellm_responses_transformation import (
                transformation,
            )

            iterator_cls = transformation.OpenAiResponsesToChatCompletionStreamIterator
            original = iterator_cls.chunk_parser
            if getattr(original, _MARKER, False):
                _installed = True
                return True
            if not hasattr(iterator_cls, "_sequential_tool_call_index"):
                logger.warning(
                    "LiteLLM's Responses stream bridge has an unexpected shape; parallel tool "
                    "call arguments will not be recovered"
                )
                return False
            iterator_cls.chunk_parser = _patched_chunk_parser(original, iterator_cls)
        except Exception:
            logger.exception("Could not install the parallel tool-call argument recovery")
            return False
        _installed = True
        return True
