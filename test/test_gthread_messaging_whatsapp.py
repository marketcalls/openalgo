"""The WhatsApp bot keeps one connection, and a command never holds up a send.

``wars.WhatsApp`` is a PyO3 ``unsendable`` class: every method panics when
called from any thread but the one that created the client. The service parks
the client on one bot thread and funnels every call through that thread's
queue. Two defects broke that under real threads:

* **Two clients for one device.** ``start_bot`` checked ``_is_running``, which
  the bot thread sets only after connecting, then spawned a thread and left the
  lock. A second start in that window (the auto start, the pairing auto start,
  a click, a double click) built a second client from the same session. The
  newer thread overwrote ``self._wa``, the older one then called the newer
  client from the wrong thread and panicked, a send came back reported as
  neither sent nor failed, and WhatsApp dropped one of the two connections.
  The same happened on the Start after a network drop, because the old pump
  kept running beside the new one.
* **A slash command held the pump.** Commands ran inline on the bot thread and
  call the OpenAlgo API over HTTP, so every send waited behind a /closeall's
  broker round trip, and chart alerts timed out.

The fake ``wars`` here enforces the thread confinement the real one does, by
raising a ``PanicException`` (a BaseException, like pyo3's) on a call from the
wrong thread.
"""

from __future__ import annotations

import threading
import time
import types

import pytest

import services.whatsapp_bot_service as wbs
from utils import shared_executors


class PanicException(BaseException):
    """Stands in for pyo3_runtime.PanicException, which is a BaseException."""


class FakeWhatsApp:
    """A wars client that, like the real one, only works on its creator thread."""

    created: list = []
    connect_delay = 0.2

    def __init__(self):
        self.owner = threading.get_ident()
        self.connected = False
        self.sent: list = []
        self.on_message_cb = None
        self.on_disconnect_cb = None
        self.panics = 0
        self.fail_sends = False

    @classmethod
    def from_bytes(cls, blob):
        time.sleep(cls.connect_delay)  # the window a racing start lands in
        client = cls()
        cls.created.append(client)
        return client

    def _confined(self):
        if threading.get_ident() != self.owner:
            self.panics += 1
            raise PanicException("WhatsApp is unsendable, but sent to another thread")

    def on_message(self, fn):
        self.on_message_cb = fn
        return fn

    def on_disconnect(self, fn):
        self.on_disconnect_cb = fn
        return fn

    def connect(self, phone=None):
        self._confined()
        self.connected = True

    def disconnect(self):
        self._confined()
        self.connected = False

    def send(self, *args, **kwargs):
        self._confined()
        if self.fail_sends:
            raise PanicException("send failed inside Rust")
        self.sent.append(args)
        return "msg-id"


@pytest.fixture
def service(monkeypatch):
    FakeWhatsApp.created = []
    FakeWhatsApp.connect_delay = 0.2
    fake_wars = types.ModuleType("wars")
    fake_wars.WhatsApp = FakeWhatsApp
    monkeypatch.setitem(__import__("sys").modules, "wars", fake_wars)
    config = {"is_paired": True, "owner_username": "admin", "own_jid": None}
    monkeypatch.setattr(wbs, "load_session_blob", lambda: b"session-blob")
    monkeypatch.setattr(wbs, "get_bot_config", lambda: dict(config))
    monkeypatch.setattr(wbs, "update_bot_config", lambda values: True)
    monkeypatch.setattr(wbs, "log_command", lambda *args, **kwargs: None)
    svc = wbs.WhatsAppBotService()
    monkeypatch.setattr(svc, "_emit", lambda event, payload: None)
    yield svc
    svc.stop_bot()
    shared_executors.shutdown_all()


def _live_bot_threads():
    return [t for t in threading.enumerate() if t.name == "WhatsAppBotThread" and t.is_alive()]


def _wait(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


PHONE = "919876543210"


def test_concurrent_starts_create_one_client(service):
    """PORTED DEFECT: two starts built two wars clients for one device."""
    callers = 6
    barrier = threading.Barrier(callers)
    answers = []
    lock = threading.Lock()

    def start():
        barrier.wait()
        answer = service.start_bot()
        with lock:
            answers.append(answer)

    threads = [threading.Thread(target=start) for _ in range(callers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)

    assert len(FakeWhatsApp.created) == 1, f"{len(FakeWhatsApp.created)} clients were created"
    assert len(_live_bot_threads()) == 1
    assert (True, "Bot started") in answers
    for ok, message in answers:
        assert (ok, message) in (
            (True, "Bot started"),
            (True, "Bot already running"),
            (False, wbs.CONNECTING_MESSAGE),
        )
    assert service.is_ready()


def test_a_restart_after_a_disconnect_replaces_the_pump(service):
    """PORTED DEFECT: the old pump kept running beside the new one."""
    assert service.start_bot() == (True, "Bot started")
    first = FakeWhatsApp.created[0]
    old_thread = service._bot_thread

    first.on_disconnect_cb()  # wars reports the connection dropped
    assert _wait(lambda: not service.is_running)
    assert old_thread.is_alive()  # the pump is still there, as before

    assert service.start_bot() == (True, "Bot started")
    assert not old_thread.is_alive(), "the old pump outlived the restart"
    assert first.connected is False, "the old client was not disconnected"
    assert first.panics == 0
    assert len(FakeWhatsApp.created) == 2
    assert len(_live_bot_threads()) == 1


def test_sends_never_cross_threads(service):
    assert service.start_bot() == (True, "Bot started")
    FakeWhatsApp.created[0].on_disconnect_cb()
    assert _wait(lambda: not service.is_running)
    assert service.start_bot() == (True, "Bot started")

    reports = []
    lock = threading.Lock()
    barrier = threading.Barrier(6)

    def send(n):
        barrier.wait()
        report = service.send_sync(PHONE, f"alert {n}")
        with lock:
            reports.append(report)

    threads = [threading.Thread(target=send, args=(n,)) for n in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)

    assert all(r["sent"] == [PHONE] and r["failed"] == [] for r in reports), reports
    current = FakeWhatsApp.created[-1]
    assert len(current.sent) == 6
    assert all(client.panics == 0 for client in FakeWhatsApp.created)
    assert service._bot_thread.is_alive()


def test_a_panic_inside_wars_is_a_reported_failure(service):
    """PORTED DEFECT: a PanicException came back as neither sent nor failed."""
    assert service.start_bot() == (True, "Bot started")
    FakeWhatsApp.created[0].fail_sends = True
    report = service.send_sync(PHONE, "alert")
    assert report["sent"] == []
    assert report["failed"] and report["failed"][0]["error"]
    assert service._bot_thread.is_alive(), "the pump died on the panic"
    FakeWhatsApp.created[0].fail_sends = False
    assert service.send_sync(PHONE, "again")["sent"] == [PHONE]


def test_a_stop_during_connect_is_honoured(service):
    FakeWhatsApp.connect_delay = 0.5
    starter = threading.Thread(target=service.start_bot)
    starter.start()
    assert _wait(lambda: service._gen is not None)
    assert service.start_bot() == (False, wbs.CONNECTING_MESSAGE)
    assert service.stop_bot() == (True, "Bot is not running")
    starter.join(20)
    assert not _live_bot_threads()
    assert service.is_running is False


def test_a_stop_retires_a_disconnected_pump(service):
    assert service.start_bot() == (True, "Bot started")
    thread = service._bot_thread
    FakeWhatsApp.created[0].on_disconnect_cb()
    assert _wait(lambda: not service.is_running)
    assert service.stop_bot() == (True, "Bot is not running")
    assert not thread.is_alive()


def test_sends_queued_when_the_bot_stops_fail_at_once(service, monkeypatch):
    assert service.start_bot() == (True, "Bot started")
    gen = service._gen
    gate = threading.Event()
    real_send = service._send_on_bot_thread

    def slow_send(*args, **kwargs):
        gate.wait(5)
        return real_send(*args, **kwargs)

    monkeypatch.setattr(service, "_send_on_bot_thread", slow_send)
    results = []
    senders = [
        threading.Thread(target=lambda: results.append(service.send_sync(PHONE, "x")))
        for _ in range(3)
    ]
    for sender in senders:
        sender.start()
    assert _wait(lambda: gen.cmd_queue.qsize() >= 2)
    stopper = threading.Thread(target=service.stop_bot)
    stopper.start()
    time.sleep(0.1)
    gate.set()
    started = time.monotonic()
    for sender in senders:
        sender.join(10)
    stopper.join(10)
    assert time.monotonic() - started < 5, "queued sends sat out the send timeout"
    errors = [f["error"] for r in results for f in r["failed"]]
    assert wbs.SEND_ABANDONED_ERROR in errors


# --- messaging-06: commands run off the pump ------------------------------------


def test_a_send_is_not_held_up_by_a_running_command(service, monkeypatch):
    """PORTED DEFECT: a slash command's broker round trip blocked every send."""
    monkeypatch.setattr(wbs.WhatsAppBotService, "SEND_TIMEOUT", 3.0)
    release = threading.Event()
    in_command = threading.Event()

    class SlowClient:
        def orderbook(self):
            in_command.set()
            release.wait(10)
            return {"status": "success", "data": []}

    monkeypatch.setattr(service, "_sdk_client_for_owner", lambda: (SlowClient(), None))
    assert service.start_bot() == (True, "Bot started")
    client = FakeWhatsApp.created[0]
    chat = f"{PHONE}@s.whatsapp.net"
    client.on_message_cb(
        types.SimpleNamespace(is_from_me=True, sender=chat, chat=chat, text="/orderbook")
    )
    assert in_command.wait(5), "the command never ran"

    started = time.monotonic()
    report = service.send_sync(PHONE, "chart alert")
    took = time.monotonic() - started
    assert report["sent"] == [PHONE], report
    assert took < 1.0, f"the send waited {took:.2f}s behind the command"

    release.set()
    # The command's own reply still goes out, through the pump.
    assert _wait(lambda: len(client.sent) >= 2)
    assert client.panics == 0


def test_commands_run_one_at_a_time_in_order(service, monkeypatch):
    order = []

    def fake_dispatch(wa, chat, sender, text):
        order.append(("start", text))
        time.sleep(0.05)
        order.append(("end", text))

    monkeypatch.setattr(service, "_dispatch_command", fake_dispatch)
    for n in range(4):
        service._submit_command("c", "s", f"/cmd{n}")
    assert _wait(lambda: len(order) == 8)
    assert order == [(edge, f"/cmd{n}") for n in range(4) for edge in ("start", "end")]


def test_a_command_releases_its_database_sessions(service, monkeypatch):
    released = []
    monkeypatch.setattr(wbs, "remove_all_scoped_sessions", lambda: released.append(1))
    monkeypatch.setattr(service, "_dispatch_command", lambda *args: None)
    service._run_command("c", "s", "/help")
    assert released == [1]
