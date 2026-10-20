"""A restart is not an error in the market data client's log.

systemd stops every process of the service at once, so on each restart the
websocket proxy disappeared a moment before this process was told to stop. The
client saw the close, redialled at once, was refused, and logged it with
``logger.exception``: an ERROR and a full traceback in ``log/errors.jsonl`` on
every restart, for a failure that was not one.

Pinned here, by driving the reconnect loop directly with a fake connection and
a fake sleep so every case is exact and fast:

* once OpenAlgo has begun to stop, the client does not redial and logs no
  warning or error;
* a refused connection is a one-line warning, never a traceback;
* a proxy that stays unreachable is still reported, once, as an ERROR that
  says what stopped working;
* an unexpected failure keeps its traceback, because that one is a bug.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from services import websocket_client as wc
from utils import stream_registry

LOGGER = "services.websocket_client"


@pytest.fixture(autouse=True)
def clear_stop_signal():
    stream_registry._reset_for_tests()
    stream_registry.STOP.clear()
    yield
    stream_registry._reset_for_tests()
    stream_registry.STOP.clear()


def _run_loop(monkeypatch, connect, iterations):
    """Run the reconnect loop until it has slept ``iterations`` times."""
    client = wc.WebSocketClient("restart-logging-key", host="127.0.0.1", port=1)
    client.running = True
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= iterations:
            client.running = False

    client._sleep_while_running = fake_sleep
    monkeypatch.setattr(wc.websockets, "connect", connect)
    asyncio.run(client._connect_and_run())
    return sleeps


class Refused:
    """websockets.connect for a proxy that is not listening."""

    def __init__(self):
        self.calls = 0

    def __call__(self, url):
        self.calls += 1
        raise ConnectionRefusedError(111, "Connect call failed ('127.0.0.1', 8765)")


def _records(caplog, level=logging.DEBUG):
    return [r for r in caplog.records if r.name == LOGGER and r.levelno >= level]


def test_a_refused_connection_is_a_warning_without_a_traceback(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    refused = Refused()
    _run_loop(monkeypatch, refused, iterations=3)

    assert refused.calls == 3
    assert not _records(caplog, logging.ERROR), "a refused connection was logged as an error"
    assert not [r for r in _records(caplog) if r.exc_info], (
        "a refused connection carried a traceback"
    )
    warnings = [r.getMessage() for r in _records(caplog, logging.WARNING)]
    assert len(warnings) == 3
    assert all("is not accepting connections" in message for message in warnings)


def test_no_redial_once_openalgo_is_stopping(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    stream_registry.request_drain()  # what the stop signal does
    refused = Refused()
    _run_loop(monkeypatch, refused, iterations=4)

    assert refused.calls == 0, "the client redialled a proxy that is stopping with the app"
    assert not _records(caplog, logging.WARNING)
    infos = [r.getMessage() for r in _records(caplog, logging.INFO)]
    assert infos.count("OpenAlgo is stopping; the market data client will not reconnect") == 1


def test_a_proxy_that_stays_down_is_reported_once(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    monkeypatch.setattr(wc.WebSocketClient, "UNREACHABLE_ERROR_AFTER", 8)
    refused = Refused()
    _run_loop(monkeypatch, refused, iterations=20)

    errors = _records(caplog, logging.ERROR)
    assert len(errors) == 1
    assert "Live prices and tick-driven stops are not updating" in errors[0].getMessage()
    assert not errors[0].exc_info
    # Attempts 1-5 and every tenth are warned; the rest of the streak is quiet.
    warned = [r for r in _records(caplog, logging.WARNING) if r.levelno == logging.WARNING]
    assert len(warned) == 7  # attempts 1, 2, 3, 4, 5, 10 and 20


def test_the_stop_signal_mid_outage_silences_the_rest(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    refused = Refused()

    def refuse_then_stop(url):
        if refused.calls == 1:
            stream_registry.request_drain()
        refused(url)

    _run_loop(monkeypatch, refuse_then_stop, iterations=5)
    assert refused.calls == 2
    assert not _records(caplog, logging.ERROR)
    assert not [r for r in _records(caplog) if r.exc_info]


def test_an_unexpected_failure_keeps_its_traceback(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)

    def broken(url):
        raise RuntimeError("a bug, not a proxy restart")

    _run_loop(monkeypatch, broken, iterations=1)
    errors = _records(caplog, logging.ERROR)
    assert len(errors) == 1 and errors[0].exc_info, "an unexpected failure lost its traceback"
