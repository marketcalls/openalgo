"""Regression contracts for GitHub issue #2386.

Left running overnight, the order-update poller kept reading the order book
with the previous day's broker token, because the rollover revoke only runs
from a browser request. From the cutover Flattrade answers with a body that is
not JSON, and json.loads raised on every poll, logging a traceback every 5 s.
"""

from __future__ import annotations

from datetime import datetime
from unittest import mock

import httpx
import pytest
import pytz

from websocket_proxy import order_adapter
from websocket_proxy.order_adapter import PollingOrderUpdateAdapter


def run_cycles(
    adapter, module_sleep, cycles, *, session_current, books=None, expiry_disabled=False
):
    """Run ``cycles`` poll cycles synchronously; return (get_orderbook, publish) mocks."""
    remaining = {"n": cycles}

    def fake_sleep(_seconds):
        remaining["n"] -= 1
        if remaining["n"] <= 0:
            adapter._running = False

    module_sleep(order_adapter, fake_sleep)
    session = mock.Mock(side_effect=session_current)
    orderbook = mock.Mock(return_value=(True, {"data": {"orders": []}}, 200))
    if books is not None:
        orderbook.side_effect = [(True, {"data": {"orders": orders}}, 200) for orders in books]
    publish = mock.Mock()
    with (
        mock.patch("database.auth_db.get_auth_token", return_value="stale-token"),
        mock.patch("services.orderbook_service.get_orderbook", orderbook),
        mock.patch("utils.session.has_login_this_trading_session", session),
        mock.patch("utils.session.is_session_expiry_disabled", return_value=expiry_disabled),
        mock.patch.object(adapter, "_publish_order", publish),
    ):
        adapter._running = True
        adapter._generation = 1
        adapter._poll_loop(1)
    return orderbook, publish


@pytest.fixture
def adapter():
    poller = PollingOrderUpdateAdapter("flattrade", "trader", poll_interval=0.5)
    poller.logger = mock.Mock()
    return poller


def test_stale_session_never_reads_the_order_book(adapter, module_sleep):
    orderbook, _ = run_cycles(adapter, module_sleep, 3, session_current=[False, False, False])
    orderbook.assert_not_called()


def test_stale_session_is_logged_once_not_every_cycle(adapter, module_sleep):
    run_cycles(adapter, module_sleep, 3, session_current=[False, False, False])
    paused = [c for c in adapter.logger.info.call_args_list if "paused" in c.args[0]]
    assert len(paused) == 1
    assert "next broker login" in paused[0].args[0]


def test_polling_resumes_after_a_fresh_login(adapter, module_sleep):
    orderbook, _ = run_cycles(adapter, module_sleep, 3, session_current=[False, True, True])
    assert orderbook.call_count == 2
    assert any("resumed" in c.args[0] for c in adapter.logger.info.call_args_list)


def test_current_session_polls_as_before(adapter, module_sleep):
    orderbook, _ = run_cycles(adapter, module_sleep, 2, session_current=[True, True])
    assert orderbook.call_count == 2


def test_session_expiry_disabled_always_polls(adapter, module_sleep):
    orderbook, _ = run_cycles(
        adapter, module_sleep, 2, session_current=[False, False], expiry_disabled=True
    )
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
    debug = " ".join(str(c.args[0]) for c in log.debug.call_args_list)
    assert "HTTP 200" in debug
    assert repr(body) in debug


def order(orderid, status):
    return {"orderid": orderid, "order_status": status, "filled_quantity": 0}


def test_resuming_reseeds_instead_of_replaying_the_new_book(adapter, module_sleep):
    # Seeded before the rollover, paused, then the first book after the login
    # holds a different state; it must seed again, not publish as changes.
    _, publish = run_cycles(
        adapter,
        module_sleep,
        4,
        session_current=[True, False, True, True],
        books=[
            [order("1", "open")],
            [order("1", "cancelled"), order("2", "open")],
            [order("1", "cancelled"), order("2", "complete")],
        ],
    )
    assert [c.args[0]["orderid"] for c in publish.call_args_list] == ["2"]


class TestTradingSessionBoundary:
    """Between midnight and 03:00 IST the session that began at yesterday's 03:00 is still current."""

    IST = pytz.timezone("Asia/Kolkata")

    def check(self, now, login):
        from utils import session

        sessions = [{"session_id": "s", "login_time": login.isoformat()}]
        with (
            mock.patch("database.auth_db.get_active_sessions", return_value=sessions),
            mock.patch.object(session, "datetime", wraps=datetime) as clock,
        ):
            clock.now.return_value = self.IST.localize(now).astimezone(pytz.UTC)
            return session.has_login_this_trading_session("trader")

    def test_yesterday_evening_login_is_current_before_the_rollover(self):
        assert self.check(datetime(2026, 11, 7, 1, 30), datetime(2026, 11, 6, 20, 0)) is True

    def test_yesterday_login_is_stale_after_the_rollover(self):
        assert self.check(datetime(2026, 11, 7, 5, 0), datetime(2026, 11, 6, 20, 0)) is False

    def test_login_before_yesterdays_rollover_is_stale_at_night(self):
        assert self.check(datetime(2026, 11, 7, 1, 30), datetime(2026, 11, 6, 2, 0)) is False


class TestFlattradeBulkActionsOnNotOk:
    @pytest.fixture
    def order_api(self):
        from broker.flattrade.api import order_api

        return order_api

    def test_square_off_reports_a_failed_read(self, order_api):
        not_ok = {
            "stat": "Not_Ok",
            "emsg": "Flattrade did not return data. If this continues, log in to the broker again.",
        }
        with mock.patch.object(order_api, "get_positions", return_value=not_ok):
            body, status = order_api.close_all_positions("key", "token")
        assert status == 502
        assert body["status"] == "error"
        assert "log in to the broker again" in body["message"]

    def test_square_off_on_an_empty_book_has_nothing_to_close(self, order_api):
        with mock.patch.object(
            order_api, "get_positions", return_value={"stat": "Not_Ok", "emsg": "no data"}
        ):
            assert order_api.close_all_positions("key", "token") == (
                {"message": "No Open Positions Found"},
                200,
            )

    @pytest.mark.parametrize("book", [{"stat": "Ok"}, {"unexpected": "shape"}])
    def test_square_off_on_an_unrecognised_dict_is_an_error(self, order_api, book):
        with (
            mock.patch.object(order_api, "get_positions", return_value=book),
            mock.patch.object(order_api, "place_order_api") as place,
        ):
            body, status = order_api.close_all_positions("key", "token")
        assert status == 502
        assert body["status"] == "error"
        place.assert_not_called()

    def test_cancel_all_on_a_not_ok_book_cancels_nothing(self, order_api):
        with (
            mock.patch.object(
                order_api, "get_order_book", return_value={"stat": "Not_Ok", "emsg": "x"}
            ),
            mock.patch.object(order_api, "cancel_order") as cancel,
        ):
            assert order_api.cancel_all_orders_api({}, "token") == ([], [])
        cancel.assert_not_called()
