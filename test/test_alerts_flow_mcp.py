"""Slack and Discord from Flow and from MCP.

Both reach the same rules as ``POST /api/v1/<channel>/notify``: the Flow nodes
call ``services.alerts.notify`` directly, and the MCP tools call the endpoint.
So a message a Flow node posts is one the endpoint would accept, and the other
way round, and neither can post while the channel is switched off at /alerts.
"""

from __future__ import annotations

import json
import os
import time

import httpx
import pytest
from flask import Flask
from flask_restx import Api

os.environ.setdefault("OPENALGO_MCP_HTTP_BOOT", "1")

# Importing it pins the installed openalgo SDK over the repo folder of the same
# name, which mcp/mcpserver.py would otherwise import instead.
import test_alerts_api as alerts_api  # noqa: E402
import test_mcp_integrity  # noqa: E402, F401

import services.flow_executor_service as fes  # noqa: E402
from services.alerts import settings  # noqa: E402
from services.alerts.channels import webhook  # noqa: E402
from services.alerts.notify import notify  # noqa: E402
from services.alerts.registry import get_channel  # noqa: E402
from services.flow_openalgo_client import FlowOpenAlgoClient  # noqa: E402
from services.flow_workflow_validator import validate_workflow  # noqa: E402
from utils.mcp_tool_registry import _load_mcpserver_module  # noqa: E402

# The alert table on a file of its own, and a stand-in for Slack and Discord:
# the same fixtures the notify endpoint's own tests use.
store = alerts_api.store
provider = alerts_api.provider

URLS = {"slack": alerts_api.SLACK_URL, "discord": alerts_api.DISCORD_URL}
CHANNELS = ["slack", "discord"]


def _drain(name: str) -> None:
    lane = webhook._lane(name)
    deadline = time.monotonic() + 5
    while lane.pending and time.monotonic() < deadline:
        time.sleep(0.01)
    assert lane.pending == 0


def _posted_text(name: str, request: httpx.Request) -> str:
    body = json.loads(request.content)
    return body["text"] if name == "slack" else body["content"]


# ---------------------------------------------------------------------------
# The shared rules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", CHANNELS)
def test_a_long_message_is_refused_unless_shortening_is_asked_for(store, provider, name):
    channel = get_channel(name)
    settings.save_webhook(channel, URLS[name])
    long = "x" * (channel.max_length + 50)

    refused = notify(channel, long)
    shortened = notify(channel, long, shorten=True)
    _drain(name)

    assert (refused.ok, refused.status_code) == (False, 400)
    assert shortened.ok
    [request] = provider["requests"]
    text = _posted_text(name, request)
    assert len(text) == channel.max_length
    assert text.endswith("...")


# ---------------------------------------------------------------------------
# Flow
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", CHANNELS)
def test_the_flow_node_posts_to_the_saved_webhook(store, provider, name):
    settings.save_webhook(get_channel(name), URLS[name])

    result = getattr(FlowOpenAlgoClient("key"), name)("Bought NIFTY")
    _drain(name)

    assert result["status"] == "success", result
    [request] = provider["requests"]
    assert str(request.url) == URLS[name]
    assert _posted_text(name, request) == "Bought NIFTY"


@pytest.mark.parametrize("name", CHANNELS)
def test_a_long_flow_message_is_shortened_not_lost(store, provider, name):
    """Nobody is watching a running workflow to send a refused alert again."""
    channel = get_channel(name)
    settings.save_webhook(channel, URLS[name])

    result = getattr(FlowOpenAlgoClient("key"), name)("y" * (channel.max_length * 2))
    _drain(name)

    assert result["status"] == "success", result
    [request] = provider["requests"]
    assert len(_posted_text(name, request)) == channel.max_length


@pytest.mark.parametrize("name", CHANNELS)
def test_the_flow_node_posts_nothing_while_the_channel_is_off(store, provider, name):
    channel = get_channel(name)
    settings.save_webhook(channel, URLS[name])
    settings.update_settings(channel, enabled=False)

    result = getattr(FlowOpenAlgoClient("key"), name)("Bought NIFTY")
    _drain(name)

    assert result["status"] == "error"
    assert "turned off" in result["error"]
    assert provider["requests"] == []


@pytest.mark.parametrize("name", CHANNELS)
def test_the_flow_node_posts_nothing_without_a_webhook(store, provider, name):
    result = getattr(FlowOpenAlgoClient("key"), name)("Bought NIFTY")

    assert result["status"] == "error"
    assert provider["requests"] == []


@pytest.mark.parametrize("name", CHANNELS)
def test_a_flow_alert_that_fails_unexpectedly_says_where_to_look(name, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr("services.alerts.notify.notify", broken)

    result = getattr(FlowOpenAlgoClient("key"), name)("Bought NIFTY")

    assert result["status"] == "error"
    assert "database is locked" not in result["error"]
    assert "log" in result["error"]


@pytest.mark.parametrize(
    ("node_type", "name"), [("slackAlert", "slack"), ("discordAlert", "discord")]
)
def test_the_executor_dispatches_the_node_with_its_variables_filled_in(node_type, name):
    sent = []

    class Client:
        def slack(self, message):
            sent.append(("slack", message))
            return {"status": "success", "data": {"message": "Notification queued."}}

        def discord(self, message):
            sent.append(("discord", message))
            return {"status": "success", "data": {"message": "Notification queued."}}

    context = fes.WorkflowContext()
    context.set_variable("sym", "NIFTY")
    executor = fes.NodeExecutor(Client(), context, [])
    nodes = [{"id": "n1", "type": node_type, "data": {"message": "Bought {{sym}}"}}]

    fes.execute_node_chain("n1", nodes, {}, {}, executor, context, {})

    assert sent == [(name, "Bought NIFTY")]
    assert executor.errors == []


@pytest.mark.parametrize("node_type", ["slackAlert", "discordAlert"])
def test_the_run_log_keeps_a_preview_not_the_whole_message(node_type):
    """Every run's log is stored; one variable can make a message 4000 long."""
    sent = []

    class Client:
        def slack(self, message):
            sent.append(message)
            return {"status": "success", "data": {"message": "Notification queued."}}

        discord = slack

    logs: list = []
    context = fes.WorkflowContext()
    executor = fes.NodeExecutor(Client(), context, logs)
    message = "z" * 5000
    nodes = [{"id": "n1", "type": node_type, "data": {"message": message}}]

    fes.execute_node_chain("n1", nodes, {}, {}, executor, context, {})

    assert sent == [message]  # the channel still gets the whole text
    assert logs, "nothing was logged"
    assert all(len(entry["message"]) < 400 for entry in logs), [len(e["message"]) for e in logs]
    assert any("5000 characters" in entry["message"] for entry in logs)


@pytest.mark.parametrize("node_type", ["slackAlert", "discordAlert"])
def test_the_validator_accepts_the_node_and_requires_a_message(node_type):
    def workflow(**data):
        return {
            "name": "W",
            "nodes": [
                {"id": "t", "type": "start", "position": {"x": 0, "y": 0}, "data": {}},
                {"id": "a", "type": node_type, "position": {"x": 0, "y": 0}, "data": data},
            ],
            "edges": [{"id": "e1", "source": "t", "target": "a"}],
        }

    assert validate_workflow(workflow(message="Done")) == []
    errors = validate_workflow(workflow())
    assert any(error["path"] == "/nodes/1/data/message" for error in errors), errors


# ---------------------------------------------------------------------------
# MCP: the tools call the real notify endpoint
# ---------------------------------------------------------------------------


@pytest.fixture
def server(store, provider, monkeypatch):
    """The MCP server, its SDK client pointed at an app serving the endpoints."""
    from limiter import limiter
    from restx_api import webhook_alerts

    monkeypatch.setattr(
        webhook_alerts, "verify_api_key", lambda key: "trader" if key == "good" else None
    )
    app = Flask(__name__)
    app.config["RATELIMIT_ENABLED"] = False
    # init_app would leave the shared limiter off for every later file.
    monkeypatch.setattr(limiter, "enabled", limiter.enabled)
    limiter.init_app(app)
    rest = Api(app, prefix="/api/v1")
    rest.add_namespace(webhook_alerts.slack_ns, path="/slack")
    rest.add_namespace(webhook_alerts.discord_ns, path="/discord")

    module = _load_mcpserver_module()
    assert module is not None, "could not load mcp/mcpserver.py"
    http = httpx.Client(transport=httpx.WSGITransport(app=app))
    monkeypatch.setattr(module, "client", type("Sdk", (), {"client": http})())
    monkeypatch.setattr(module, "host", "http://openalgo.test")
    monkeypatch.setattr(module, "api_key", "good")
    yield module
    http.close()


def _call(server, name: str, *args, **kwargs) -> dict:
    """A tool's answer, inside the envelope every MCP tool output carries."""
    out = json.loads(getattr(server, f"send_{name}_alert")(*args, **kwargs))
    return out[server.DATA_KEY]


@pytest.mark.parametrize("name", CHANNELS)
def test_the_mcp_tool_posts_through_the_endpoint(server, provider, name):
    settings.save_webhook(get_channel(name), URLS[name])

    answer = _call(server, name, "Breakout on NIFTY", wait_for_delivery=True)

    assert answer["status"] == "success", answer
    [request] = provider["requests"]
    assert str(request.url) == URLS[name]
    assert _posted_text(name, request) == "Breakout on NIFTY"


@pytest.mark.parametrize("name", CHANNELS)
def test_the_mcp_tool_is_refused_while_the_channel_is_off(server, provider, name):
    channel = get_channel(name)
    settings.save_webhook(channel, URLS[name])
    settings.update_settings(channel, enabled=False)

    answer = _call(server, name, "Breakout on NIFTY")

    assert answer["status"] == "error"
    assert "turned off" in answer["message"]
    assert provider["requests"] == []


@pytest.mark.parametrize("name", CHANNELS)
def test_the_mcp_tool_sends_the_key_in_the_body_never_the_url(name, monkeypatch):
    server = _load_mcpserver_module()
    seen = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"status": "success", "message": "Notification queued."})

    http = httpx.Client(transport=httpx.MockTransport(answer))
    monkeypatch.setattr(server, "client", type("Sdk", (), {"client": http})())
    monkeypatch.setattr(server, "host", "http://openalgo.test/")
    monkeypatch.setattr(server, "api_key", "the-key")

    _call(server, name, "hi")

    [request] = seen
    assert request.url.path == f"/api/v1/{name}/notify"
    assert "the-key" not in str(request.url)
    assert json.loads(request.content) == {
        "apikey": "the-key",
        "message": "hi",
        "wait_for_delivery": False,
    }


@pytest.mark.parametrize("name", CHANNELS)
def test_an_mcp_timeout_says_to_check_the_channel_before_retrying(name, monkeypatch):
    server = _load_mcpserver_module()

    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    http = httpx.Client(transport=httpx.MockTransport(slow))
    monkeypatch.setattr(server, "client", type("Sdk", (), {"client": http})())
    monkeypatch.setattr(server, "host", "http://openalgo.test")

    error = _call(server, name, "hi")["error"]

    assert error["retry_safe"] is False
    assert error["verify_first"] is True
    assert name.capitalize() in error["verify_with"]


@pytest.mark.parametrize("name", CHANNELS)
def test_an_unreadable_answer_is_a_structured_error(name, monkeypatch):
    server = _load_mcpserver_module()

    def html(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html>Bad Gateway</html>")

    http = httpx.Client(transport=httpx.MockTransport(html))
    monkeypatch.setattr(server, "client", type("Sdk", (), {"client": http})())
    monkeypatch.setattr(server, "host", "http://openalgo.test")

    error = _call(server, name, "hi")["error"]

    assert error["error_type"] == "http"
    assert error["status_code"] == 502
    assert error["retry_safe"] is False
