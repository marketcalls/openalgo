"""SMTP sends are bounded under the gthread worker, and close their connection.

Password reset and the test email run on a request thread. With no socket
timeout, a mail server that accepts the connection and never answers held that
thread for good: under eventlet a parked greenlet, under gthread one of a fixed
pool. The bound applies only under gthread; eventlet and the development server
keep the socket default, as before. On every path the connection is closed,
where a failure used to leave the socket to garbage collection.
"""

from __future__ import annotations

import smtplib
import socket
import threading
import time
import types

import pytest

from utils import email_utils, runtime

SETTINGS = {
    "smtp_server": "127.0.0.1",
    "smtp_port": 587,
    "smtp_username": "user",
    "smtp_password": "pass",
    "smtp_from_email": "from@example.com",
    "smtp_use_tls": False,
}


@pytest.fixture(autouse=True)
def _clean_runtime(monkeypatch):
    monkeypatch.setattr(runtime, "_registered", None)
    monkeypatch.setattr(runtime, "_worker_ref", None)


def _as_gthread():
    cls = type("FakeWorker", (), {})
    cls.__module__ = "gunicorn.workers.gthread"
    worker = cls()
    worker.cfg = types.SimpleNamespace(
        worker_class_str="gthread", threads=64, workers=1, graceful_timeout=30
    )
    runtime.register_gunicorn_worker(worker)


@pytest.fixture
def silent_server():
    """A listener that accepts connections and never says a word."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)
    held = []
    stop = threading.Event()

    def accept():
        listener.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _addr = listener.accept()
                held.append(conn)
            except OSError:
                continue

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    yield listener.getsockname()[1]
    stop.set()
    thread.join(2)
    for conn in held:
        conn.close()
    listener.close()


class _RecordingSMTP:
    """Records how it was built and whether it was closed."""

    instances: list = []

    def __init__(self, host, port, **kwargs):
        self.kwargs = kwargs
        self.closed = False
        type(self).instances.append(self)

    def ehlo(self, *args):
        return (250, b"ok")

    def starttls(self, **kwargs):
        return (220, b"ok")

    def login(self, user, password):
        raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    def sendmail(self, *args):
        return {}

    def quit(self):
        self.closed = True

    def close(self):
        self.closed = True


def test_under_gthread_a_silent_mail_server_cannot_hold_the_thread(silent_server, monkeypatch):
    _as_gthread()
    monkeypatch.setattr(email_utils, "SMTP_TIMEOUT_SECONDS", 1.0)
    settings = dict(SETTINGS, smtp_port=silent_server)
    started = time.monotonic()
    result = email_utils.send_email("to@example.com", "s", "t", smtp_settings=settings)
    took = time.monotonic() - started
    assert result["success"] is False
    assert took < email_utils.SMTP_TIMEOUT_SECONDS + 2
    started = time.monotonic()
    assert email_utils.validate_smtp_settings(settings)["success"] is False
    assert time.monotonic() - started < email_utils.SMTP_TIMEOUT_SECONDS + 2


def test_off_gthread_the_socket_default_is_kept(monkeypatch):
    _RecordingSMTP.instances = []
    monkeypatch.setattr(smtplib, "SMTP", _RecordingSMTP)
    assert email_utils._smtp_timeout_kwargs() == {}
    email_utils.send_email("to@example.com", "s", "t", smtp_settings=dict(SETTINGS))
    email_utils.validate_smtp_settings(dict(SETTINGS))
    assert [smtp.kwargs for smtp in _RecordingSMTP.instances] == [{}, {}]


def test_under_gthread_every_constructor_is_bounded(monkeypatch):
    _as_gthread()
    _RecordingSMTP.instances = []
    monkeypatch.setattr(smtplib, "SMTP", _RecordingSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _RecordingSMTP)
    for port in (587, 465):
        settings = dict(SETTINGS, smtp_port=port)
        email_utils.send_email("to@example.com", "s", "t", smtp_settings=settings)
        email_utils.validate_smtp_settings(settings)
    bound = {"timeout": email_utils.SMTP_TIMEOUT_SECONDS}
    assert [smtp.kwargs.get("timeout") for smtp in _RecordingSMTP.instances] == [
        bound["timeout"]
    ] * 4


def test_a_failed_send_closes_its_connection(monkeypatch):
    _RecordingSMTP.instances = []
    monkeypatch.setattr(smtplib, "SMTP", _RecordingSMTP)
    result = email_utils.send_email("to@example.com", "s", "t", smtp_settings=dict(SETTINGS))
    assert result["success"] is False
    assert "Authentication failed" in result["message"]
    assert email_utils.validate_smtp_settings(dict(SETTINGS))["success"] is False
    assert all(smtp.closed for smtp in _RecordingSMTP.instances)


def test_a_connect_timeout_is_explained_only_where_the_bound_applies(monkeypatch):
    def times_out(*args, **kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr(smtplib, "SMTP", times_out)
    before = email_utils.send_email("to@example.com", "s", "t", smtp_settings=dict(SETTINGS))
    assert before["message"] == "Failed to send email: timed out"  # unchanged off gthread

    _as_gthread()
    after = email_utils.send_email("to@example.com", "s", "t", smtp_settings=dict(SETTINGS))
    assert after == {"success": False, "message": email_utils.MAIL_SERVER_UNREACHABLE_MESSAGE}
    assert "SMTP host and port" in email_utils.MAIL_SERVER_UNREACHABLE_MESSAGE
