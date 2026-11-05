"""LiteLLM's MCP gateway must stay out of agent requests.

LiteLLM 1.106 imports its MCP gateway handler on every Responses API call and
on every ``completion`` that carries tools. That handler needs the mcp 2.x SDK
(``mcp.types.CacheableResult`` and sixteen other names); OpenAlgo pins mcp 1.30
for its own FastMCP server. So after the bump from 1.104.0 every agent turn
failed with "cannot import name 'CacheableResult' from 'mcp.types'", on every
model, while the model test on /agent/config, which sends no tools, still
passed for the API-key models.

The end-to-end cases run in a fresh interpreter: the gate is installed on
LiteLLM's module once per process, and the defect case needs a LiteLLM that
never saw it.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path
from types import ModuleType

import pytest

pytest.importorskip("litellm")

from services.agent import litellm_mcp_gateway  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
FUNCTION_TOOL_CHAT = {
    "type": "function",
    "function": {"name": "get_quote", "parameters": {"type": "object", "properties": {}}},
}
FUNCTION_TOOL_RESPONSES = {
    "type": "function",
    "name": "get_quote",
    "parameters": {"type": "object", "properties": {}},
}
MCP_TOOL = {"type": "mcp", "server_url": "litellm_proxy/mcp/zerodha", "server_label": "z"}


def _mcp_has_v2_types() -> bool:
    import mcp.types

    return hasattr(mcp.types, "CacheableResult")


def _run(body: str) -> subprocess.CompletedProcess[str]:
    script = f"import sys\nsys.path.insert(0, {str(REPO)!r})\n" + textwrap.dedent(body)
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )


_CALLS = f"""
import litellm
from services.agent import litellm_loader

TOOLS_CHAT = {[FUNCTION_TOOL_CHAT]!r}
TOOLS_RESPONSES = {[FUNCTION_TOOL_RESPONSES]!r}

def completion_error(**extra):
    try:
        litellm.completion(
            model="openai/gpt-4o-mini", messages=[{{"role": "user", "content": "hi"}}],
            tools=TOOLS_CHAT, mock_response="ok", api_key="test-key", **extra,
        )
    except Exception as exc:
        return str(exc)
    return ""

def responses_error():
    # A closed local port: past the gateway the call fails to connect, which
    # is the proof it got past the gateway at all.
    try:
        litellm.responses(
            model="openai/gpt-4o-mini", input="hi", tools=TOOLS_RESPONSES,
            api_key="test-key", api_base="http://127.0.0.1:9", timeout=5, num_retries=0,
        )
    except Exception as exc:
        return str(exc)
    return ""
"""


def test_the_defect_as_litellm_ships_it():
    """Without the gate, both paths fail on the import, so the fix below cannot pass vacuously."""
    if _mcp_has_v2_types():
        pytest.skip("the installed mcp has the 2.x types, so LiteLLM's gateway imports cleanly")
    result = _run(
        _CALLS
        + """
assert "CacheableResult" in completion_error(), completion_error()
assert "CacheableResult" in responses_error(), responses_error()
print("OK")
"""
    )
    assert "OK" in result.stdout, result.stderr[-3000:] + result.stdout[-2000:]


def test_agent_requests_never_reach_the_gateway():
    result = _run(
        _CALLS
        + """
litellm_loader.load()
assert completion_error(_skip_mcp_handler=True) == "", completion_error(_skip_mcp_handler=True)
error = responses_error()
assert error and "CacheableResult" not in error, error
assert "litellm.responses.mcp.litellm_proxy_mcp_handler" not in sys.modules
print("OK")
"""
    )
    assert "OK" in result.stdout, result.stderr[-3000:] + result.stdout[-2000:]


def test_build_model_opts_out_of_the_gateway():
    pytest.importorskip("agno")
    from services.agent import builder

    resolved = builder.ResolvedModel(
        id=1,
        provider_kind="ollama",
        model_name="llama3.2",
        display_name="Local",
        base_url="http://127.0.0.1:11434",
        litellm_id="ollama/llama3.2",
        supports_reasoning=False,
        default_reasoning_effort="off",
        supports_vision=False,
        tools_unreliable=False,
        is_default=True,
        has_key=False,
        secret_name=None,
    )
    model = builder.build_model(resolved)
    assert model.request_params["_skip_mcp_handler"] is True


# The gate itself, on a stand-in for litellm.responses.main.


def _fake_responses_main() -> tuple[ModuleType, list[dict]]:
    calls: list[dict] = []
    module = ModuleType("fake_responses_main")

    def dispatch(*, tools=None, skip_mcp_handler=False, model=None):
        calls.append({"tools": tools, "skip": skip_mcp_handler})
        return "gateway"

    module._responses_try_dispatch_mcp_gateway = dispatch
    return module, calls


def test_function_tools_skip_the_gateway():
    module, calls = _fake_responses_main()
    assert litellm_mcp_gateway.install(module) is True
    gated = module._responses_try_dispatch_mcp_gateway
    assert gated(tools=[FUNCTION_TOOL_RESPONSES], skip_mcp_handler=False, model="m") is None
    assert gated(tools=None, skip_mcp_handler=False, model="m") is None
    assert calls == []


def test_an_mcp_tool_still_reaches_the_gateway():
    module, calls = _fake_responses_main()
    litellm_mcp_gateway.install(module)
    gated = module._responses_try_dispatch_mcp_gateway
    tools = [FUNCTION_TOOL_RESPONSES, MCP_TOOL]
    assert gated(tools=tools, skip_mcp_handler=False, model="m") == "gateway"
    assert calls == [{"tools": tools, "skip": False}]
    # The caller's own opt-out still wins, as it does in LiteLLM.
    assert gated(tools=tools, skip_mcp_handler=True, model="m") is None
    assert len(calls) == 1


def test_install_is_idempotent():
    module, _ = _fake_responses_main()
    assert litellm_mcp_gateway.install(module) is True
    first = module._responses_try_dispatch_mcp_gateway
    assert litellm_mcp_gateway.install(module) is True
    assert module._responses_try_dispatch_mcp_gateway is first


def test_a_changed_litellm_is_left_alone():
    renamed = ModuleType("renamed")
    assert litellm_mcp_gateway.install(renamed) is False

    reshaped = ModuleType("reshaped")

    def dispatch(*, tool_list=None):
        return "gateway"

    reshaped._responses_try_dispatch_mcp_gateway = dispatch
    assert litellm_mcp_gateway.install(reshaped) is False
    assert reshaped._responses_try_dispatch_mcp_gateway is dispatch
