"""Regression contracts for GitHub issue #2386.

Left running overnight, the order-update poller kept reading the order book
with the previous day's broker token, because the rollover revoke only runs
from a browser request. From the cutover Flattrade answers with a body that is
not JSON, and json.loads raised on every poll, logging a traceback every 5 s.
"""

from __future__ import annotations

from unittest import mock

import httpx
import pytest

from websocket_proxy import order_adapter
from websocket_proxy.order_adapter import PollingOrderUpdateAdapter


def run_cycles(adapter, cycles, *, session_current, expiry_disabled=False):
    """Run ``cycles`` poll cycles synchronously and return the get_orderbook mock."""
    remaining = {"n": cycles}

    def fake_sleep(_seconds):
        remaining["n"] -= 1
        if remaining["n"] <= 0:
            adapter._running = False

    session = mock.Mock(side_effect=session_current)
    orderbook = mock.Mock(return_value=(True, {"data": {"orders": []}}, 200))
    with (
        mock.patch("database.auth_db.get_auth_token", return_value="stale-token"),
        mock.patch("services.orderbook_service.get_orderbook", orderbook),
        mock.patch("utils.session.has_login_this_trading_session", session),
        mock.patch("utils.session.is_session_expiry_disabled", return_value=expiry_disabled),
        mock.patch.object(order_adapter.time, "sleep", fake_sleep),
    ):
        adapter._running = True
        adapter._generation = 1
        adapter._poll_loop(1)
    return orderbook


@pytest.fixture
def adapter():
    poller = PollingOrderUpdateAdapter("flattrade", "trader", poll_interval=0.5)
    poller.logger = mock.Mock()
    return poller


def test_stale_session_never_reads_the_order_book(adapter):
    orderbook = run_cycles(adapter, 3, session_current=[False, False, False])
    orderbook.assert_not_called()


def test_stale_session_is_logged_once_not_every_cycle(adapter):
    run_cycles(adapter, 3, session_current=[False, False, False])
    paused = [c for c in adapter.logger.info.call_args_list if "paused" in c.args[0]]
    assert len(paused) == 1
    assert "next broker login" in paused[0].args[0]


def test_polling_resumes_after_a_fresh_login(adapter):
    orderbook = run_cycles(adapter, 3, session_current=[False, True, True])
    assert orderbook.call_count == 2
    assert any("resumed" in c.args[0] for c in adapter.logger.info.call_args_list)


def test_current_session_polls_as_before(adapter):
    orderbook = run_cycles(adapter, 2, session_current=[True, True])
    assert orderbook.call_count == 2


def test_session_expiry_disabled_always_polls(adapter):
    orderbook = run_cycles(adapter, 2, session_current=[False, False], expiry_disabled=True)
    assert orderbook.call_count == 2


@pytest.mark.parametrize("body", ["", "<html>Session expired</html>"], ids=["empty", "html"])
def test_flattrade_non_json_answer_is_a_not_ok_without_raising(monkeypatch, body):
    from broker.flattrade.api import order_api

    monkeypatch.setenv("BROKER_API_KEY", "FT0001:::FT0001")
    client = mock.Mock()
    client.request.return_value = httpx.Response(200, text=body)
    monkeypatch.setattr(order_api, "get_httpx_client", lambda: client)
    monkeypatch.setattr(order_api.DATA_LIMITER, "acquire", lambda: None)
    log = mock.Mock()
    monkeypatch.setattr(order_api, "logger", log)

    response = order_api.get_order_book("stale-token")

    assert response["stat"] == "Not_Ok"
    assert "log in to the broker again" in response["emsg"]
    log.error.assert_not_called()
    log.exception.assert_not_called()
