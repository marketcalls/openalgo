"""Prompt caching for Claude models.

Every model call in an agent turn re-sends the same tool definitions and system
prompt, about 47,000 tokens, and a turn that searches and reads a page makes
several calls. A cache breakpoint lets the provider read that block back instead
of processing it again. The breakpoints must reach Claude models and no one else:
OpenAI caches on its own, and a ``cache_control`` field sent to a provider that
does not know it can be refused.
"""

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

pytest.importorskip("agno")

from services.agent import builder, prompts

TOOLS_POINT = {"location": "tool_config"}
SYSTEM_POINT = {"location": "message", "role": "system"}
LAST_POINT = {"location": "message", "index": -1}
ALL_POINTS = [TOOLS_POINT, SYSTEM_POINT, LAST_POINT]


@pytest.mark.parametrize(
    "litellm_id",
    [
        "anthropic/claude-haiku-5-5",
        "anthropic/claude-sonnet-5-5",
        "Anthropic/Claude-Opus-5-5",
        "bedrock/anthropic.claude-sonnet-5-5-v1:0",
        "vertex_ai/claude-sonnet-5-5",
        "openrouter/anthropic/claude-sonnet-5-5",
    ],
)
def test_a_claude_model_gets_a_breakpoint_on_the_tools_the_system_message_and_the_last_message(
    litellm_id,
):
    assert builder.prompt_cache_points(litellm_id) == ALL_POINTS


@pytest.mark.parametrize(
    "litellm_id",
    [
        "openai/gpt-5.4",
        "gpt-4o",
        "chatgpt/gpt-6-sol",
        "ollama/llama3.2",
        "gemini/gemini-2.5-pro",
        "bedrock/amazon.nova-pro-v1:0",
        "vertex_ai/gemini-2.5-pro",
        "openrouter/openai/gpt-5.4",
        # Claude by name, on a provider that does not take breakpoints. Only the
        # provider check stops these, so they pin it separately from the name check.
        "ollama/claude-like-local",
        "azure/claude-sonnet-5-5",
        "huggingface/anthropic-distill",
        "",
    ],
)
def test_no_other_provider_is_sent_a_cache_field(litellm_id):
    assert builder.prompt_cache_points(litellm_id) == []


def test_the_points_are_a_fresh_list_each_time():
    first = builder.prompt_cache_points("anthropic/claude-haiku-5-5")
    first.append({"location": "message", "index": 0})

    assert builder.prompt_cache_points("anthropic/claude-haiku-5-5") == ALL_POINTS


def _resolved(provider_kind, litellm_id):
    return builder.ResolvedModel(
        id=1,
        provider_kind=provider_kind,
        model_name=litellm_id.split("/", 1)[-1],
        display_name="Test",
        base_url="http://127.0.0.1:11434" if provider_kind == "ollama" else None,
        litellm_id=litellm_id,
        supports_reasoning=False,
        default_reasoning_effort="off",
        supports_vision=False,
        tools_unreliable=False,
        is_default=True,
        has_key=False,
        secret_name=None,
    )


def test_a_claude_model_is_built_with_the_injection_points(monkeypatch):
    monkeypatch.setattr(builder, "prompt_cache_points", lambda _id: ALL_POINTS)

    model = builder.build_model(_resolved("ollama", "ollama/llama3.2"))

    assert model.request_params["cache_control_injection_points"] == ALL_POINTS
    assert model.request_params["_skip_mcp_handler"] is True, "the earlier opt-out must survive"


def test_a_model_without_caching_is_built_without_the_field():
    model = builder.build_model(_resolved("ollama", "ollama/llama3.2"))

    assert "cache_control_injection_points" not in model.request_params


# ---------------------------------------------------------------------------
# The prompt itself has to be the same text from one message to the next
# ---------------------------------------------------------------------------

IST = ZoneInfo("Asia/Kolkata")


def _prompt(minute, lines=("Chart symbol: NIFTY, interval 5m",)):
    return prompts.build_system_prompt(
        surface="chat",
        now=dt.datetime(2026, 11, 19, 15, minute, tzinfo=IST),
        extra_runtime_lines=lines,
    )


def test_a_new_minute_changes_only_the_very_end_of_the_prompt():
    # A cache matches a prefix, so a changing character early in the prompt
    # throws away everything after it. This used to be 9 percent stable.
    first, second = _prompt(30), _prompt(31)

    differs_at = next(i for i, (a, b) in enumerate(zip(first, second, strict=False)) if a != b)

    assert differs_at / len(first) > 0.98
    assert first[:differs_at] == second[:differs_at]


def test_the_clock_and_the_chart_lines_are_still_in_the_prompt_and_come_last():
    prompt = _prompt(30)

    assert "Current date and time: Thursday, 2026-11-19 15:30 IST" in prompt
    assert "Chart symbol: NIFTY, interval 5m" in prompt
    assert prompt.rindex("RIGHT NOW") > prompt.rindex("THIS SESSION")
    assert prompt.index("RIGHT NOW") > prompt.index("HOW TO ANSWER"), "after every static section"


def test_what_changes_rarely_stays_in_the_static_part():
    on = prompts.build_system_prompt(surface="chat", trading_enabled=True)
    off = prompts.build_system_prompt(surface="chat", trading_enabled=False)

    assert "Trading is enabled" in on and "Trading is disabled" in off
    assert "Current date and time" not in on, "no clock was given, so none is invented"


def test_a_prompt_trimmed_to_its_budget_keeps_the_clock():
    # The highest-order sections are dropped first, and the clock is the last one.
    trimmed = prompts.build_system_prompt(
        surface="chat", now=dt.datetime(2026, 11, 19, 15, 30, tzinfo=IST), max_chars=6000
    )

    assert "Current date and time" in trimmed


def test_a_surface_with_no_clock_and_no_lines_adds_no_empty_section():
    assert prompts.volatile_section() is None
    assert prompts.volatile_section(extra_lines=["", "  "]) is None
