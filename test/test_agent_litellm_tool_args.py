"""Parallel tool calls must reach the agent with their arguments.

The defect was live and is measured, not inferred: asked for the history of
three instruments, the ChatGPT backend answered with three function calls whose
arguments arrived only in the ``done`` events, no deltas at all, and LiteLLM's
Responses-to-chat bridge dropped them. Every call in the batch reached agno as
``arguments: ""`` and failed with ``Missing required argument``; the model only
got data once it gave up and asked one instrument at a time.

The event sequences below are the ones captured from the backend. Each test
drives LiteLLM's real stream iterator, so the first one fails on an unpatched
LiteLLM and the duplication test fails the day LiteLLM starts emitting the
``done`` arguments itself, which is the signal to delete the patch.
"""

import json

import pytest

pytest.importorskip("litellm")

from litellm.completion_extras.litellm_responses_transformation import transformation

from services.agent import litellm_tool_args

Iterator = transformation.OpenAiResponsesToChatCompletionStreamIterator


@pytest.fixture(autouse=True)
def _patched():
    assert litellm_tool_args.install()


def _added(index, name, call_id):
    return {
        "type": "response.output_item.added",
        "output_index": index,
        "item": {"type": "function_call", "name": name, "call_id": call_id, "arguments": ""},
    }


def _args_done(index, arguments):
    return {
        "type": "response.function_call_arguments.done",
        "output_index": index,
        "arguments": arguments,
    }


def _item_done(index, name, call_id, arguments):
    return {
        "type": "response.output_item.done",
        "output_index": index,
        "item": {
            "type": "function_call",
            "name": name,
            "call_id": call_id,
            "arguments": arguments,
        },
    }


def _delta(index, text):
    return {"type": "response.function_call_arguments.delta", "output_index": index, "delta": text}


def _assemble(events):
    """Feed events through the real iterator and merge tool calls by index, as agno does."""
    iterator = Iterator(streaming_response=iter(()), sync_stream=True)
    calls = {}
    for event in events:
        chunk = iterator.chunk_parser(event)
        for choice in chunk.choices or ():
            for tool_call in getattr(choice.delta, "tool_calls", None) or ():
                entry = calls.setdefault(tool_call.index, {"id": None, "name": "", "arguments": ""})
                if tool_call.id:
                    entry["id"] = tool_call.id
                function = tool_call.function
                if function is not None and function.name:
                    entry["name"] = function.name
                if function is not None and function.arguments:
                    entry["arguments"] += function.arguments
    return [calls[index] for index in sorted(calls)]


TCS = '{"symbol": "TCS", "exchange": "NSE", "interval": "D"}'
INFY = '{"symbol": "INFY", "exchange": "NSE", "interval": "D"}'


def test_parallel_calls_without_deltas_keep_their_arguments():
    events = [
        _added(0, "get_history", "call_a"),
        _args_done(0, TCS),
        _item_done(0, "get_history", "call_a", TCS),
        _added(1, "get_history", "call_b"),
        _args_done(1, INFY),
        _item_done(1, "get_history", "call_b", INFY),
    ]

    calls = _assemble(events)

    assert [json.loads(call["arguments"]) for call in calls] == [
        json.loads(TCS),
        json.loads(INFY),
    ]
    assert [call["id"] for call in calls] == ["call_a", "call_b"]
    assert [call["name"] for call in calls] == ["get_history", "get_history"]


def test_a_streamed_call_is_never_delivered_twice():
    pieces = ['{"symbol":', '"TCS",', '"exchange":"NSE",', '"interval":"D"}']
    whole = "".join(pieces)
    events = [
        {"type": "response.output_item.added", "output_index": 0, "item": {"type": "reasoning"}},
        _added(1, "get_history", "call_a"),
        *(_delta(1, piece) for piece in pieces),
        _args_done(1, whole),
        _item_done(1, "get_history", "call_a", whole),
    ]

    calls = _assemble(events)

    assert len(calls) == 1
    assert calls[0]["arguments"] == whole


def test_only_the_closing_item_still_recovers_the_call():
    # A backend that skips the arguments-done event as well: the item's own
    # closing event is the last place the arguments appear.
    events = [_added(0, "web_research", "call_a"), _item_done(0, "web_research", "call_a", TCS)]

    calls = _assemble(events)

    assert calls[0]["arguments"] == TCS


def test_a_call_whose_announcement_was_missed_carries_its_name_and_id():
    events = [_item_done(0, "get_quote", "call_z", TCS)]

    calls = _assemble(events)

    assert calls[0] == {"id": "call_z", "name": "get_quote", "arguments": TCS}


def test_mixed_batch_indexes_stay_sequential_after_a_reasoning_item():
    events = [
        {"type": "response.output_item.added", "output_index": 0, "item": {"type": "reasoning"}},
        _added(1, "get_history", "call_a"),
        _args_done(1, TCS),
        _added(2, "get_history", "call_b"),
        _args_done(2, INFY),
    ]

    calls = _assemble(events)

    assert [call["arguments"] for call in calls] == [TCS, INFY]


def test_install_is_idempotent():
    first = Iterator.chunk_parser
    assert litellm_tool_args.install()
    assert Iterator.chunk_parser is first
