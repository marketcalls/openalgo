"""Regression tests for credential-safe core service logging."""

from flask import Flask

TEST_KEY = "test-token-not-real-1234567890"


def request_context():
    return Flask(__name__).test_request_context("/", method="POST", json={"apikey": TEST_KEY})


class RecordingLogger:
    def __init__(self):
        self.messages = []

    def warning(self, message, *args):
        self.messages.append(message % args if args else message)

    def exception(self, message, *args):
        self.messages.append(message % args if args else message)

    error = exception


def test_option_greeks_invalid_key_is_not_logged(monkeypatch):
    from restx_api import option_greeks

    logger = RecordingLogger()
    monkeypatch.setattr(option_greeks, "logger", logger)
    monkeypatch.setattr(
        option_greeks.option_greeks_schema,
        "load",
        lambda data: {"apikey": TEST_KEY, "symbol": "NIFTY", "exchange": "NFO"},
    )
    monkeypatch.setattr(option_greeks, "verify_api_key", lambda api_key: False)

    with request_context():
        response = option_greeks.OptionGreeks().post()

    assert response.status_code == 401
    assert logger.messages == ["Invalid API key used for option greeks"]
    assert TEST_KEY not in " ".join(logger.messages)


def test_multi_option_greeks_invalid_key_is_not_logged(monkeypatch):
    from restx_api import multi_option_greeks

    logger = RecordingLogger()
    monkeypatch.setattr(multi_option_greeks, "logger", logger)
    monkeypatch.setattr(
        multi_option_greeks.multi_option_greeks_schema,
        "load",
        lambda data: {"apikey": TEST_KEY, "symbols": []},
    )
    monkeypatch.setattr(multi_option_greeks, "verify_api_key", lambda api_key: False)

    with request_context():
        response = multi_option_greeks.MultiOptionGreeks().post()

    assert response.status_code == 401
    assert logger.messages == ["Invalid API key used for multi option greeks"]
    assert TEST_KEY not in " ".join(logger.messages)


def test_websocket_close_error_does_not_log_api_key(monkeypatch):
    from services import websocket_client

    logger = RecordingLogger()
    monkeypatch.setattr(websocket_client, "logger", logger)

    class FailingClient:
        def disconnect(self):
            raise RuntimeError(f"disconnect failed for {TEST_KEY}")

    monkeypatch.setattr(
        websocket_client,
        "_client_instances",
        {TEST_KEY: FailingClient()},
    )

    websocket_client.close_all_clients()

    assert logger.messages == ["Error closing WebSocket client"]
    assert TEST_KEY not in " ".join(logger.messages)
