"""An expired Upstox login is one warning, not four errors every thirty seconds.

The stored Upstox login expires every night. Until the next login, every
reconnect of the market data client was refused the same way, and each round
logged four ERROR lines: the refused authorize, then a dial of the old URL
(which Upstox had already refused) logged twice by the client and once more by
the adapter. On demo.openalgo.in that was 248 entries in one hour of
``log/errors.jsonl``, all saying the same thing.

Pinned here:

* a refused authorize is not followed by a dial of the stale URL;
* the refusal is logged once per streak, as a warning a person can act on;
* the "over the connection limit" alert, whose advice is wrong for this cause,
  does not fire when the cause is a refused login;
* when the budget runs out the reason is the login, said once;
* a login that works again resets the streak and the client dials again.
"""

from __future__ import annotations

import logging

import pytest
import requests

from broker.upstox.streaming import upstox_client as uc

LOGGER = "upstox_websocket"
REFUSAL_BODY = (
    '{"status":"error","errors":[{"errorCode":"UDAPI100050",'
    '"message":"Invalid token used to access API"}]}'
)


class FakeResponse:
    def __init__(self, status, body="", url=None):
        self.status_code = status
        self.text = body
        self._url = url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        return {"data": {"authorized_redirect_uri": self._url}}


class FakeSocket:
    """Stands in for websocket.WebSocketApp: counts dials, never connects."""

    dials = 0

    def __init__(self, url=None, **callbacks):
        self.url = url

    def run_forever(self, **kwargs):
        FakeSocket.dials += 1


@pytest.fixture
def client(monkeypatch):
    FakeSocket.dials = 0
    monkeypatch.setattr(uc.websocket, "WebSocketApp", FakeSocket)
    monkeypatch.setattr(uc.UpstoxWebSocketClient, "BACKOFF_SLICE", 0.001)
    client = uc.UpstoxWebSocketClient("expired-token", user_id=None)
    client._reconnect_config = {"max_attempts": 8, "base_delay": 0, "max_delay": 0}
    client.ws = FakeSocket("wss://stale")  # the socket from before the login expired
    client.running = True
    return client


def _records(caplog, level=logging.DEBUG):
    return [r for r in caplog.records if r.name == LOGGER and r.levelno >= level]


def test_an_expired_login_is_reported_once_and_never_redialled(client, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    monkeypatch.setattr(uc.requests, "get", lambda *a, **k: FakeResponse(401, REFUSAL_BODY))

    client._run_websocket()

    # Only the socket that was open when the login expired; no dial after that.
    assert FakeSocket.dials == 1, f"the stale URL was dialled {FakeSocket.dials - 1} more times"

    warnings = [
        r.getMessage() for r in _records(caplog, logging.WARNING) if r.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    assert "log in to Upstox again" in warnings[0]

    errors = [r.getMessage() for r in _records(caplog, logging.ERROR)]
    assert not [e for e in errors if "authorize rejected" in e], (
        "each refusal was logged as an error"
    )
    assert not [e for e in errors if "per-user limit" in e], (
        "the connection-limit advice fired for a login"
    )
    assert errors == [
        "Stopped retrying Upstox market data: Upstox still refuses the stored login. "
        "Log in to Upstox again and market data restarts."
    ]


def test_a_login_that_works_again_resets_the_streak_and_dials(client, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    answers = iter(
        [FakeResponse(401, REFUSAL_BODY), FakeResponse(401, REFUSAL_BODY)]
        + [FakeResponse(200, url="wss://fresh")] * 10
    )
    monkeypatch.setattr(uc.requests, "get", lambda *a, **k: next(answers))

    def stop_after_fresh_dial(**kwargs):
        FakeSocket.dials += 1
        if FakeSocket.dials == 2:
            client.running = False

    monkeypatch.setattr(FakeSocket, "run_forever", lambda self, **kw: stop_after_fresh_dial(**kw))

    client._run_websocket()

    assert FakeSocket.dials == 2  # the stale socket, then the fresh one
    assert client._authorize_refusals == 0
    infos = [r.getMessage() for r in _records(caplog, logging.INFO)]
    assert any("accepted the login again after 2 refusals" in message for message in infos)


def test_other_refusals_are_still_errors(client, monkeypatch, caplog):
    # A refusal that is not the login keeps its ERROR, with Upstox's reason.
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    monkeypatch.setattr(uc.requests, "get", lambda *a, **k: FakeResponse(429, '{"errors":"limit"}'))
    client._reconnect_config["max_attempts"] = 2
    client._run_websocket()
    errors = [r.getMessage() for r in _records(caplog, logging.ERROR)]
    assert any("authorize rejected: HTTP 429" in e for e in errors)
