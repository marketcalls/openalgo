"""Integrity checks for the MCP tool surface.

Catches drift between the three places a tool is described:

* ``mcp/mcpserver.py`` — the tool itself, its annotations, toolset, and
  output risk.
* ``utils/mcp_tool_registry.py`` — the OAuth scope required to call it
  over the HTTP transport.
* ``docs/mcp-tool-reference.md`` — what the user is told exists.

A tool added to one and not the others is the recurring failure mode:
no scope means unreachable over HTTP, a wrong scope means a read-only
token can place orders, and a missing annotation means a client cannot
tell a quote lookup from a square-off before asking the user to approve.

Also covers the response contract every tool shares: structured errors,
the trust-boundary envelope, and the env-driven tool filtering.

Run: uv run pytest test/test_mcp_integrity.py -v
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# mcp/mcpserver.py raises at import time unless it sees stdio argv or
# this flag. Set before the registry loads the module.
os.environ.setdefault("OPENALGO_MCP_HTTP_BOOT", "1")

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _ensure_sdk_openalgo() -> None:
    """Stop the repo root from masking the installed ``openalgo`` SDK.

    The repo root is itself named ``openalgo`` and carries an empty
    ``__init__.py``, so pytest treats it as a package and puts its
    parent on sys.path. ``from openalgo import api`` in
    mcp/mcpserver.py then resolves to the repo instead of the pip
    package and fails with ImportError.

    Drop the parent entry, evict any module object already bound to the
    repo, then import the real SDK so it is pinned in sys.modules —
    pytest re-inserts the parent path as it collects later modules, and
    a resolved sys.modules entry is immune to that.
    """
    parent = str(PROJECT_ROOT.parent)
    while parent in sys.path:
        sys.path.remove(parent)

    shadow = sys.modules.get("openalgo")
    if shadow is not None and not hasattr(shadow, "api"):
        for name in [n for n in sys.modules if n == "openalgo" or n.startswith("openalgo.")]:
            del sys.modules[name]

    import openalgo

    assert hasattr(openalgo, "api"), (
        f"'openalgo' resolves to {getattr(openalgo, '__file__', '?')} rather than the installed SDK"
    )


_ensure_sdk_openalgo()

from utils.mcp_tool_registry import (  # noqa: E402
    SCOPE_READ_ACCOUNT,
    SCOPE_READ_MARKET,
    SCOPE_WRITE_ORDERS,
    TOOL_SCOPES,
    _load_mcpserver_module,
    get_tool_callable,
    list_tools_for_scopes,
    registered_tool_names,
)

READ_SCOPES = {SCOPE_READ_MARKET, SCOPE_READ_ACCOUNT}

# Tools that change something but are deliberately not write-scoped.
# Keep this list at zero-or-one entries and justify every addition —
# each one is a tool a read-only OAuth token can still trigger.
WRITE_SCOPE_EXCEPTIONS = {
    # Delivers only to the account owner's own Telegram bot; cannot move
    # money or place an order. Rationale recorded alongside its entry in
    # utils/mcp_tool_registry.py.
    "send_telegram_alert",
}


@pytest.fixture(scope="module")
def server():
    _ensure_sdk_openalgo()
    module = _load_mcpserver_module()
    assert module is not None, "could not load mcp/mcpserver.py"
    return module


@pytest.fixture(scope="module")
def fastmcp_tools(server):
    tools = server.mcp._tool_manager._tools
    assert tools, "FastMCP registered no tools"
    return tools


def _run_isolated(env_extra: dict[str, str], snippet: str) -> dict:
    """Import the MCP server in a fresh process under given env vars.

    Toolset filtering is evaluated at import time, so it cannot be
    exercised by mutating os.environ in this process — the module is
    already loaded and cached.
    """
    env = {**os.environ, "OPENALGO_MCP_HTTP_BOOT": "1", **env_extra}
    code = (
        "import sys, json;"
        f"sys.path.insert(0, {str(PROJECT_ROOT)!r});"
        "from utils.mcp_tool_registry import _load_mcpserver_module;"
        "m = _load_mcpserver_module();"
        f"{snippet}"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, f"subprocess failed: {proc.stderr[-2000:]}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------- drift


def test_every_registered_tool_has_a_scope(fastmcp_tools):
    """A tool with no scope entry is unreachable over the HTTP transport."""
    missing = sorted(set(fastmcp_tools) - set(TOOL_SCOPES))
    assert not missing, (
        f"tools registered with FastMCP but missing from TOOL_SCOPES: {missing}. "
        "Add them to utils/mcp_tool_registry.py."
    )


def test_every_scope_entry_has_a_tool(fastmcp_tools):
    """A scope entry with no tool is stale config left by a rename."""
    orphaned = sorted(set(TOOL_SCOPES) - set(fastmcp_tools))
    assert not orphaned, (
        f"TOOL_SCOPES entries with no registered tool: {orphaned}. "
        "Remove them from utils/mcp_tool_registry.py."
    )


def test_tool_meta_matches_registered_tools(server, fastmcp_tools):
    assert set(server.TOOL_META) == set(fastmcp_tools), (
        "TOOL_META and FastMCP disagree on which tools exist"
    )


def test_registered_tool_names_helper_agrees(fastmcp_tools):
    assert registered_tool_names() == set(fastmcp_tools)


def test_no_duplicate_titles(server):
    titles = [m.title for m in server.TOOL_META.values()]
    dupes = sorted({t for t in titles if titles.count(t) > 1})
    assert not dupes, f"duplicate tool titles confuse client UIs: {dupes}"


def test_every_tool_belongs_to_a_known_toolset(server):
    for name, meta in server.TOOL_META.items():
        assert meta.toolset in server.ALL_TOOLSETS, f"{name} has unknown toolset '{meta.toolset}'"


def test_every_tool_has_a_known_risk_class(server):
    for name, meta in server.TOOL_META.items():
        assert meta.risk in server.TRUST_INSTRUCTIONS, (
            f"{name} has unknown output risk '{meta.risk}'"
        )


# ----------------------------------------------------- annotations vs scope


def test_every_tool_has_annotations(fastmcp_tools):
    for name, tool in fastmcp_tools.items():
        assert tool.annotations is not None, f"{name} has no MCP annotations"
        assert tool.annotations.title, f"{name} has no annotation title"
        assert tool.annotations.readOnlyHint is not None, f"{name} has no readOnlyHint"


def test_write_tools_require_the_write_scope(server):
    """The check that actually matters: a write tool filed under a read
    scope would be callable with a read-only OAuth token.

    One documented exception, matching the rationale recorded in
    utils/mcp_tool_registry.py: send_telegram_alert has an outward side
    effect but delivers only to the account owner's own bot, so it is
    account-scoped rather than write-scoped. Any *other* tool that
    drifts into this state fails here.
    """
    offenders = [
        name
        for name, meta in server.TOOL_META.items()
        if not meta.read_only
        and TOOL_SCOPES.get(name) != SCOPE_WRITE_ORDERS
        and name not in WRITE_SCOPE_EXCEPTIONS
    ]
    assert not offenders, f"tools annotated as writes but not scoped write:orders: {offenders}"


def test_read_tools_do_not_require_the_write_scope(server):
    offenders = [
        name
        for name, meta in server.TOOL_META.items()
        if meta.read_only and TOOL_SCOPES.get(name) == SCOPE_WRITE_ORDERS
    ]
    assert not offenders, f"tools annotated read-only but scoped write:orders: {offenders}"


def test_annotations_agree_with_read_only_flag(server, fastmcp_tools):
    for name, meta in server.TOOL_META.items():
        ann = fastmcp_tools[name].annotations
        assert ann.readOnlyHint is meta.read_only, f"{name}: readOnlyHint mismatch"
        assert ann.destructiveHint is meta.destructive, f"{name}: destructiveHint mismatch"
        # A read-only call is repeatable; a write is not, since OpenAlgo
        # orders carry no idempotency key.
        assert ann.idempotentHint is meta.read_only, f"{name}: idempotentHint mismatch"


def test_order_tools_are_marked_destructive(server):
    for name, scope in TOOL_SCOPES.items():
        if scope != SCOPE_WRITE_ORDERS:
            continue
        meta = server.TOOL_META[name]
        assert meta.destructive, f"{name} is write-scoped but not destructiveHint"
        assert not meta.read_only, f"{name} is write-scoped but marked read-only"


def test_read_scoped_tools_are_annotated_read_only(server):
    for name, scope in TOOL_SCOPES.items():
        if scope not in READ_SCOPES:
            continue
        meta = server.TOOL_META[name]
        if name == "send_telegram_alert":
            # Account-scoped but has an outward side effect, so it is
            # deliberately not read-only. Asserted explicitly below.
            continue
        assert meta.read_only, f"{name} is read-scoped but not annotated read-only"


def test_send_telegram_alert_is_not_read_only(server):
    """It sends something outward, so read-only mode must drop it."""
    meta = server.TOOL_META["send_telegram_alert"]
    assert not meta.read_only
    assert not meta.destructive


# ------------------------------------------------------------ descriptions


def test_every_tool_has_a_description(fastmcp_tools):
    """tools/list feeds these to the model; an empty one makes the tool
    unusable even though it is advertised."""
    for name, tool in fastmcp_tools.items():
        assert (tool.description or "").strip(), f"{name} has no description"


def test_input_schemas_survive_the_wrapper(fastmcp_tools):
    """The envelope wrapper must not erase parameter metadata.

    Regression guard: clients that cannot see the schema guess parameter
    names, which is how calls using 'product_type' instead of 'product'
    reached the dispatcher.
    """
    schema = fastmcp_tools["place_order"].parameters
    assert schema["type"] == "object"
    props = schema["properties"]
    for expected in ("symbol", "quantity", "action", "exchange", "price_type", "product"):
        assert expected in props, f"place_order lost parameter '{expected}'"
    assert set(schema["required"]) == {"symbol", "quantity", "action"}


# ----------------------------------------------------------- structured errors


def test_error_helper_returns_parseable_json(server):
    payload = json.loads(server._error("something broke", error_type="Test"))
    assert payload["error"]["message"] == "something broke"
    assert payload["error"]["error_type"] == "Test"


def test_write_timeout_tells_the_model_to_verify_first(server):
    """No client order id exists, so a blind retry can duplicate a live
    order. The error must say so and name the tool to check with."""
    err = json.loads(server._fail("placing order", httpx.ReadTimeout("timed out"), write=True))[
        "error"
    ]
    assert err["error_type"] == "timeout"
    assert err["retry_safe"] is False
    assert err["verify_first"] is True
    assert "get_order_book" in err["verify_with"]
    assert "Do NOT retry blindly" in err["message"]


def test_read_timeout_is_marked_retry_safe(server):
    err = json.loads(server._fail("getting quote", httpx.ReadTimeout("t")))["error"]
    assert err["error_type"] == "timeout"
    assert err["retry_safe"] is True


# The openalgo SDK catches httpx itself and RETURNS an error dict rather
# than raising, so these — not the _fail paths above — are what actually
# happens when a live order times out.


def test_sdk_returned_timeout_is_upgraded_on_writes(server):
    sdk_response = {
        "status": "error",
        "message": "Request timed out. The server took too long to respond.",
        "error_type": "timeout_error",
    }
    err = json.loads(server._write_result(sdk_response, "placing order"))["error"]
    assert err["error_type"] == "timeout"
    assert err["retry_safe"] is False
    assert err["verify_first"] is True
    assert "Do NOT retry blindly" in err["message"]
    assert "get_order_book" in err["verify_with"]


def test_sdk_returned_connection_error_is_retry_safe(server):
    """Nothing was submitted, so the advice is the opposite of a timeout."""
    sdk_response = {
        "status": "error",
        "message": "Failed to connect to the server.",
        "error_type": "connection_error",
    }
    err = json.loads(server._write_result(sdk_response, "placing order"))["error"]
    assert err["error_type"] == "connection"
    assert err["retry_safe"] is True
    assert "never submitted" in err["message"]


def test_write_result_passes_broker_rejections_through(server):
    """A genuine broker rejection is not a transport failure and must
    reach the model unchanged."""
    sdk_response = {"status": "error", "message": "insufficient funds"}
    out = json.loads(server._write_result(sdk_response, "placing order"))
    assert out == sdk_response


def test_write_result_passes_success_through(server):
    sdk_response = {"status": "success", "orderid": "250408001002736"}
    out = json.loads(server._write_result(sdk_response, "placing order"))
    assert out == sdk_response


def test_every_write_tool_routes_through_write_result(server):
    """A new order tool that returns json.dumps(response) directly would
    silently reintroduce the swallowed-timeout gap."""
    source = (PROJECT_ROOT / "mcp" / "mcpserver.py").read_text(encoding="utf-8")
    write_calls = [
        "client.placeorder(",
        "client.placesmartorder(",
        "client.basketorder(",
        "client.splitorder(",
        "client.optionsorder(",
        "client.optionsmultiorder(",
        "client.modifyorder(",
        "client.cancelorder(",
        "client.cancelallorder(",
        "client.closeposition(",
        "client.analyzertoggle(",
        "client.telegram(",
    ]
    lines = source.splitlines()
    for call in write_calls:
        idx = next(i for i, line in enumerate(lines) if call in line)
        window = "\n".join(lines[idx : idx + 20])
        assert "_write_result(" in window, (
            f"the write via {call} does not route its response through _write_result; "
            "an SDK-reported timeout would be returned as an ordinary result"
        )


def test_transport_error_is_classified(server):
    err = json.loads(server._fail("getting quote", httpx.ConnectError("refused")))["error"]
    assert err["error_type"] == "transport"


def test_generic_error_records_exception_type(server):
    err = json.loads(server._fail("getting quote", ValueError("bad symbol")))["error"]
    assert err["error_type"] == "ValueError"
    assert "bad symbol" in err["message"]


def test_analyzer_toggle_timeout_points_at_analyzer_status(server):
    """A mode-flip timeout must not send the model to the order book."""
    err = json.loads(
        server._fail(
            "toggling analyzer mode",
            httpx.ReadTimeout("t"),
            write=True,
            verify_with="analyzer_status",
        )
    )["error"]
    assert err["verify_with"] == "analyzer_status"


def test_no_tool_returns_a_bare_error_string():
    """Every failure path must go through _error/_fail.

    A prose return like 'Error placing order: ...' is indistinguishable
    from a successful response that mentions an error.
    """
    source = (PROJECT_ROOT / "mcp" / "mcpserver.py").read_text(encoding="utf-8")
    offenders = [
        line.strip()
        for line in source.splitlines()
        if line.strip().startswith('return f"Error') or line.strip().startswith('return "Error')
    ]
    assert not offenders, f"tools returning prose errors: {offenders}"


# ------------------------------------------------------------ trust envelope


def test_envelope_separates_metadata_from_data(server):
    out = json.loads(
        server._envelope("get_quote", server.RISK_BROKER_STRUCTURED, json.dumps({"ltp": 100}))
    )
    assert set(out) == {server.SECURITY_KEY, server.DATA_KEY}
    assert out[server.DATA_KEY] == {"ltp": 100}
    meta = out[server.SECURITY_KEY]
    assert meta["trust"] == "untrusted_tool_output"
    assert meta["tool"] == "get_quote"
    assert meta["risk"] == server.RISK_BROKER_STRUCTURED


def test_external_text_envelope_carries_injection_warning(server):
    out = json.loads(
        server._envelope("search_instruments", server.RISK_EXTERNAL_TEXT, json.dumps({"a": 1}))
    )
    instructions = out[server.SECURITY_KEY]["instructions"]
    assert "prompt injection" in instructions
    assert "never place, modify, or cancel an order" in instructions.lower()


def test_envelope_carries_non_json_payloads_through(server):
    out = json.loads(server._envelope("t", server.RISK_BROKER_STRUCTURED, "plain prose"))
    assert out[server.DATA_KEY] == {"text": "plain prose"}


def test_free_text_tools_are_classified_external(server):
    """Tools relaying broker- or master-authored strings are where an
    injected instruction could reach the model."""
    for name in ("search_instruments", "get_instruments", "get_order_book"):
        assert server.TOOL_META[name].risk == server.RISK_EXTERNAL_TEXT, (
            f"{name} relays free text and must be classified external_text"
        )


def test_live_tool_output_is_enveloped(server):
    """End to end through a real tool: no broker call needed, the
    constants tool exercises the wrapper."""
    out = json.loads(server.validate_order_constants())
    assert server.SECURITY_KEY in out
    assert "product_types" in out[server.DATA_KEY]


def test_envelope_can_be_disabled():
    out = _run_isolated(
        {"OPENALGO_MCP_TRUST_ENVELOPE": "0"},
        "print(json.dumps({'keys': list(json.loads(m.validate_order_constants()))}))",
    )
    assert "product_types" in out["keys"]
    assert "_openalgo_mcp_security" not in out["keys"]


# --------------------------------------------------------- toolset filtering


def test_all_tools_registered_by_default(server, fastmcp_tools):
    assert len(fastmcp_tools) == len(server.TOOL_META)
    assert server.ACTIVE_TOOL_NAMES == frozenset(server.TOOL_META)


def test_read_only_mode_drops_every_write_tool():
    out = _run_isolated(
        {"OPENALGO_MCP_READ_ONLY": "1"},
        "print(json.dumps({"
        "'registered': sorted(m.mcp._tool_manager._tools),"
        "'writes': [n for n, x in m.TOOL_META.items() if x.registered and not x.read_only]}))",
    )
    assert out["writes"] == []
    for name in ("place_order", "cancel_all_orders", "analyzer_toggle", "send_telegram_alert"):
        assert name not in out["registered"], f"{name} survived read-only mode"
    assert "get_quote" in out["registered"]
    assert "get_order_book" in out["registered"]


def test_toolset_filter_narrows_registration():
    out = _run_isolated(
        {"OPENALGO_MCP_TOOLSETS": "marketdata,research"},
        "print(json.dumps({'registered': sorted(m.mcp._tool_manager._tools),"
        "'toolsets': sorted(m.ACTIVE_TOOLSETS)}))",
    )
    assert out["toolsets"] == ["marketdata", "research"]
    assert "get_quote" in out["registered"]
    assert "calculate_indicator" in out["registered"]
    assert "place_order" not in out["registered"]
    assert "get_funds" not in out["registered"]


def test_unknown_toolset_is_recorded_not_silently_dropped():
    out = _run_isolated(
        {"OPENALGO_MCP_TOOLSETS": "bogus,orders"},
        "print(json.dumps({'unknown': m.UNKNOWN_TOOLSETS, 'toolsets': sorted(m.ACTIVE_TOOLSETS)}))",
    )
    assert out["unknown"] == ["bogus"]
    assert out["toolsets"] == ["orders"]


def test_filtered_tool_is_unreachable_over_http():
    """Read-only mode must apply to the HTTP transport too, not just
    stdio — get_tool_callable is the dispatcher's entry point."""
    out = _run_isolated(
        {"OPENALGO_MCP_READ_ONLY": "1"},
        "from utils.mcp_tool_registry import get_tool_callable, list_tools_for_scopes;"
        "print(json.dumps({"
        "'place_order': get_tool_callable('place_order') is not None,"
        "'get_quote': get_tool_callable('get_quote') is not None,"
        "'write_listed': list_tools_for_scopes(['write:orders'])}))",
    )
    assert out["place_order"] is False
    assert out["get_quote"] is True
    assert out["write_listed"] == []


def test_scope_listing_unfiltered_by_default():
    listed = list_tools_for_scopes([SCOPE_WRITE_ORDERS])
    assert "place_order" in listed
    assert all(TOOL_SCOPES[n] == SCOPE_WRITE_ORDERS for n in listed)


def test_get_tool_callable_rejects_unknown_tool():
    assert get_tool_callable("no_such_tool") is None


# -------------------------------------------------- the guards actually fire
#
# Drift checks that cannot fail are worse than no checks, so each one is
# exercised against deliberately broken metadata.


def test_audit_detects_a_tool_with_no_scope(server, caplog, monkeypatch):
    import utils.mcp_tool_registry as registry

    patched = dict(TOOL_SCOPES)
    patched.pop("get_quote")
    monkeypatch.setattr(registry, "TOOL_SCOPES", patched)

    with caplog.at_level("WARNING"):
        registry.audit_registry()

    assert any(
        "get_quote" in r.message and "missing TOOL_SCOPES" in r.message for r in caplog.records
    ), "missing-scope drift was not reported"


def test_audit_detects_a_stale_scope_entry(server, caplog, monkeypatch):
    import utils.mcp_tool_registry as registry

    patched = dict(TOOL_SCOPES)
    patched["renamed_away_tool"] = SCOPE_READ_MARKET
    monkeypatch.setattr(registry, "TOOL_SCOPES", patched)

    with caplog.at_level("WARNING"):
        registry.audit_registry()

    assert any(
        "renamed_away_tool" in r.message and "no registered MCP tool" in r.message
        for r in caplog.records
    ), "stale scope entry was not reported"


def test_audit_detects_a_write_tool_under_a_read_scope(server, caplog, monkeypatch):
    """The security-relevant case: a read token reaching an order tool."""
    import utils.mcp_tool_registry as registry

    patched = dict(TOOL_SCOPES)
    patched["place_order"] = SCOPE_READ_MARKET
    monkeypatch.setattr(registry, "TOOL_SCOPES", patched)

    with caplog.at_level("WARNING"):
        registry.audit_registry()

    assert any(
        "place_order" in r.message and "read-only token" in r.message for r in caplog.records
    ), "write-under-read-scope was not reported"


def test_unknown_toolset_in_decorator_is_rejected(server):
    with pytest.raises(ValueError, match="unknown toolset"):
        server.openalgo_tool("not_a_toolset", title="X")


def test_unknown_risk_in_decorator_is_rejected(server):
    with pytest.raises(ValueError, match="unknown output risk"):
        server.openalgo_tool("marketdata", title="X", risk="not_a_risk")


# ------------------------------------------------------------------- docs


def test_documented_tools_exist(fastmcp_tools):
    """Every tool named with a heading in the reference doc must exist.

    Guards the other direction of drift: a renamed tool leaves the doc
    promising something the server no longer answers.
    """
    doc = (PROJECT_ROOT / "docs" / "mcp-tool-reference.md").read_text(encoding="utf-8")
    documented = {
        line.split("`")[1]
        for line in doc.splitlines()
        if line.startswith("### `") and "`" in line[5:]
    }
    missing = sorted(documented - set(fastmcp_tools))
    assert not missing, f"documented but not registered: {missing}"
