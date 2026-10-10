"""Web search reaches its provider through the hub, never from the agent thread.

The agent runs on a real OS thread. The shared HTTP client's pool locks were
built after eventlet patched the standard library, and its event hooks read
Flask's ``g``, so a request made on that thread directly is the crossing
CLAUDE.md forbids: correct on the development server and under gthread, able to
hang the worker under eventlet. These pin the two properties that matter: the
request goes through the hub crossing, and the hub waits longer than the
request itself, so a slow but healthy answer is not abandoned.
"""

import json

import pytest

pytest.importorskip("agno")

from services.agent.tools import base, websearch


class _Response:
    status_code = 200


def test_a_provider_request_runs_on_the_hub_with_a_longer_wait(monkeypatch):
    waits: list[float] = []
    posted: list[dict] = []

    def run_on_hub(fn, *args, timeout, **kwargs):
        waits.append(timeout)
        return fn(*args, **kwargs)

    class Client:
        def post(self, url, **kwargs):
            posted.append({"url": url, **kwargs})
            return _Response()

    monkeypatch.setattr(base.real_threading, "run_on_hub", run_on_hub)
    monkeypatch.setattr(websearch, "get_httpx_client", lambda: Client())

    response = websearch._post("https://example.invalid/search", timeout=20.0, json={"q": "x"})

    assert isinstance(response, _Response)
    assert posted == [
        {"url": "https://example.invalid/search", "timeout": 20.0, "json": {"q": "x"}}
    ]
    assert waits == [20.0 + websearch.HUB_WAIT_MARGIN_SECONDS]


def test_the_client_is_looked_up_on_the_hub_too(monkeypatch):
    order: list[str] = []

    def run_on_hub(fn, *args, timeout, **kwargs):
        order.append("hub")
        return fn(*args, **kwargs)

    class Client:
        def post(self, url, **kwargs):
            return _Response()

    def client():
        order.append("client")
        return Client()

    monkeypatch.setattr(base.real_threading, "run_on_hub", run_on_hub)
    monkeypatch.setattr(websearch, "get_httpx_client", client)

    websearch._post("https://example.invalid", timeout=1.0)

    assert order == ["hub", "client"]


def test_a_provider_failure_still_reaches_the_caller(monkeypatch):
    monkeypatch.setattr(base.real_threading, "run_on_hub", lambda fn, *a, timeout, **k: fn(*a, **k))

    class Client:
        def post(self, url, **kwargs):
            raise ConnectionError("refused")

    monkeypatch.setattr(websearch, "get_httpx_client", lambda: Client())

    with pytest.raises(ConnectionError):
        websearch._post("https://example.invalid", timeout=1.0)


# ---------------------------------------------------------------------------
# A busy hub is this platform, not the provider
# ---------------------------------------------------------------------------


def _hub_full(*_args, **_kwargs):
    raise base.real_threading.HubQueueFull("full")


def _hub_timed_out(*_args, **_kwargs):
    raise base._HubTimeout("the hub wait ran out")


@pytest.mark.parametrize("failure", [_hub_full, _hub_timed_out])
def test_a_busy_hub_on_tavily_names_this_platform_and_no_exception_class(monkeypatch, failure):
    monkeypatch.setattr(websearch, "_post", failure)

    outcome = websearch._tavily_search("nifty results", 5, "tvly-test")

    assert outcome.ok is False and outcome.busy is True
    assert "web server was too busy" in outcome.error
    for word in ("HubQueueFull", "_HubTimeout", "Tavily could not be reached"):
        assert word not in outcome.error


@pytest.mark.parametrize("failure", [_hub_full, _hub_timed_out])
def test_a_busy_hub_on_perplexity_names_this_platform(monkeypatch, failure):
    monkeypatch.setattr(websearch, "_post", failure)

    outcome = websearch._perplexity_research("why did the rupee fall", "model", "pplx-test")

    assert outcome.ok is False and outcome.busy is True
    assert "web server was too busy" in outcome.error
    assert "Perplexity could not be reached" not in outcome.error


def test_a_provider_transport_failure_is_still_a_provider_failure(monkeypatch):
    def refused(*_args, **_kwargs):
        raise ConnectionError("refused")

    monkeypatch.setattr(websearch, "_post", refused)

    outcome = websearch._tavily_search("nifty results", 5, "tvly-test")

    assert outcome.ok is False and outcome.busy is False
    assert outcome.error.startswith("Tavily could not be reached")


def _toolkit(monkeypatch, provider: str):
    from services.agent.tools import ToolContext

    monkeypatch.setattr(websearch, "_configured_provider", lambda: provider)
    monkeypatch.setattr(websearch, "_provider_key", lambda name: f"{name}-key")
    monkeypatch.setattr(websearch, "_get_setting", lambda key, default: default)
    monkeypatch.setattr(websearch, "_setting_int", lambda key, default, lo, hi: default)
    monkeypatch.setattr(websearch, "_read_usage", lambda: ("2026-10-09", 0))
    recorded: list[int] = []
    monkeypatch.setattr(websearch, "_increment_usage", lambda: recorded.append(1) or 1)
    context = ToolContext(api_key="k", extras={"user_message": "nifty results today"})
    return websearch.WebSearchToolkit(context), recorded


def test_a_busy_hub_does_not_fall_back_to_duckduckgo(monkeypatch):
    kit, recorded = _toolkit(monkeypatch, websearch.PROVIDER_TAVILY)
    monkeypatch.setattr(websearch, "_post", _hub_full)
    searched: list[str] = []
    monkeypatch.setattr(
        websearch, "_duckduckgo_search", lambda query, count: searched.append(query)
    )

    body = json.loads(kit.web_search("nifty results"))

    assert body["ok"] is False and body["error"] == "platform_busy"
    assert searched == [], "a busy hub is not a Tavily failure to fall back from"
    assert recorded == [], "a search that never went out must not use the budget"


def test_a_tavily_failure_still_falls_back_to_duckduckgo(monkeypatch):
    kit, _recorded = _toolkit(monkeypatch, websearch.PROVIDER_TAVILY)

    def refused(*_args, **_kwargs):
        raise ConnectionError("refused")

    monkeypatch.setattr(websearch, "_post", refused)
    monkeypatch.setattr(
        websearch,
        "_duckduckgo_search",
        lambda query, count: websearch.ProviderOutcome(
            ok=True, provider=websearch.PROVIDER_DUCKDUCKGO, results=()
        ),
    )

    text = kit.web_search("nifty results")

    assert websearch.PROVIDER_DUCKDUCKGO in text
    assert "DuckDuckGo answered instead" in text


def test_a_busy_hub_on_web_research_is_reported_as_this_platform(monkeypatch):
    kit, recorded = _toolkit(monkeypatch, websearch.PROVIDER_PERPLEXITY)
    monkeypatch.setattr(websearch, "_post", _hub_timed_out)

    body = json.loads(kit.web_research("why did nifty fall today"))

    assert body["ok"] is False and body["error"] == "platform_busy"
    assert "web server was too busy" in body["message"]
    assert recorded == []
