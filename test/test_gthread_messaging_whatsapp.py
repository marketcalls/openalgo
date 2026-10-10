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

**The session a restart restores.** The bot runs from ``WhatsApp.from_bytes``,
which copies the stored session into a private file the client keeps writing
to. Nothing wrote it back, so every restart restored the snapshot taken at
pairing, and WhatsApp logged the device out a few seconds after each boot.
The bot now saves the live session a short while after each login, on an
interval, and when it stops, over the stored one only while that is still
the session it started from. wars reports the logout through ``on_disconnect``
(whatsapp-rust's LoggedOut event, never a transient drop), and it now clears
the dead session and says so wherever a trader looks.
"""

from __future__ import annotations

import ast
import threading
import time
import types
from pathlib import Path

import pytest

import services.whatsapp_bot_service as wbs
from utils import shared_executors


class PanicException(BaseException):
    """Stands in for pyo3_runtime.PanicException, which is a BaseException."""


def snapshot(tag: str, pages: int = 2) -> bytes:
    """A session export as wars returns one: a SQLite file of 512-byte pages."""
    header = bytearray(wbs._SQLITE_MAGIC + bytes(84))
    header[16:18] = (512).to_bytes(2, "big")
    return bytes(header) + tag.encode().ljust(512 * pages - len(header), b"\0")


START = snapshot("paired")


class FakeWhatsApp:
    """A wars client that, like the real one, only works on its creator thread."""

    created: list = []
    connect_delay = 0.2
    #: Records wars' own atexit registration (the session file's deletion).
    atexit_log: list | None = None

    def __init__(self, blob=b""):
        self.owner = threading.get_ident()
        self.connected = False
        self.sent: list = []
        self.on_message_cb = None
        self.on_disconnect_cb = None
        self.on_connected_cb = None
        self.panics = 0
        self.fail_sends = False
        # What export_session returns: the session as the client holds it now.
        self.session = blob
        self.logged_in = True
        self.fail_exports = False
        self.exports = 0
        self.export_gate: threading.Event | None = None
        self.in_export = threading.Event()
        self.calls: list = []

    @classmethod
    def from_bytes(cls, blob):
        time.sleep(cls.connect_delay)  # the window a racing start lands in
        client = cls(blob)
        if cls.atexit_log is not None:
            cls.atexit_log.append(("register", "wars deletes the session file"))
        cls.created.append(client)
        return client

    def _confined(self):
        if threading.get_ident() != self.owner:
            self.panics += 1
            raise PanicException("WhatsApp is unsendable, but sent to another thread")

    def on_message(self, fn):
        self.on_message_cb = fn
        return fn

    def on_connected(self, fn):
        self.on_connected_cb = fn
        return fn

    def on_disconnect(self, fn):
        self.on_disconnect_cb = fn
        return fn

    def connect(self, phone=None):
        self._confined()
        self.connected = True

    def disconnect(self):
        self._confined()
        self.calls.append("disconnect")
        self.connected = False

    def is_connected(self):
        self._confined()
        return self.connected and self.logged_in

    def export_session(self):
        self._confined()
        self.in_export.set()
        if self.export_gate is not None:
            self.export_gate.wait(10)
        self.exports += 1
        self.calls.append("export")
        if self.fail_exports:
            raise RuntimeError("flush failed")
        return self.session

    def send(self, *args, **kwargs):
        self._confined()
        if self.fail_sends:
            raise PanicException("send failed inside Rust")
        self.sent.append(args)
        return "msg-id"


class FakeStore:
    """The stored session, with the refusals database/whatsapp_db applies."""

    def __init__(self, config):
        self.config = config
        self.blob = START
        self.writes: list = []
        self.cleared: list = []
        self.lock = threading.Lock()

    def load(self):
        return self.blob

    def refresh(self, blob, expected=None):
        with self.lock:
            if not self.config["is_paired"] or self.blob is None:
                return False
            if expected is not None and self.blob != expected:
                return False
            self.blob = blob
            self.writes.append((blob, expected, threading.get_ident()))
            return True

    def clear_rejected(self, expected):
        with self.lock:
            self.cleared.append(expected)
            if self.blob is None or self.blob != expected:
                return False
            self.blob = None
            self.config["is_paired"] = False
            return True


@pytest.fixture
def store():
    return FakeStore({"is_paired": True, "owner_username": "admin", "own_jid": None})


@pytest.fixture
def make_service(monkeypatch, store):
    FakeWhatsApp.created = []
    FakeWhatsApp.connect_delay = 0.2
    FakeWhatsApp.atexit_log = None
    fake_wars = types.ModuleType("wars")
    fake_wars.WhatsApp = FakeWhatsApp
    monkeypatch.setitem(__import__("sys").modules, "wars", fake_wars)
    monkeypatch.setattr(wbs, "load_session_blob", store.load)
    monkeypatch.setattr(wbs, "refresh_session_blob", store.refresh)
    monkeypatch.setattr(wbs, "clear_rejected_session", store.clear_rejected)
    monkeypatch.setattr(wbs, "get_bot_config", lambda: dict(store.config))
    monkeypatch.setattr(wbs, "update_bot_config", lambda values: True)
    monkeypatch.setattr(wbs, "log_command", lambda *args, **kwargs: None)
    made = []

    def make(**timings):
        svc = wbs.WhatsAppBotService(**timings)
        svc.emitted = []
        monkeypatch.setattr(
            svc, "_emit", lambda event, payload: svc.emitted.append((event, payload))
        )
        made.append(svc)
        return svc

    yield make
    for svc in made:
        svc.stop_bot()
    shared_executors.shutdown_all()


@pytest.fixture
def service(make_service):
    return make_service()


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


def _pair_again(store):
    """What the operator does after a logout: pair, which stores a new session.

    wars calls on_disconnect for a logout (it was once read as a dropped
    connection), and a logged-out session is cleared, so the start that
    follows one is the start a new pairing makes.
    """
    store.blob = snapshot("paired again")
    store.config["is_paired"] = True


def test_a_restart_after_a_disconnect_replaces_the_pump(service, store):
    """PORTED DEFECT: the old pump kept running beside the new one."""
    assert service.start_bot() == (True, "Bot started")
    first = FakeWhatsApp.created[0]
    old_thread = service._bot_thread

    first.on_disconnect_cb()  # wars reports the device logged out
    assert _wait(lambda: not service.is_running)
    assert old_thread.is_alive()  # the pump is still there, as before

    _pair_again(store)
    assert service.start_bot() == (True, "Bot started")
    assert not old_thread.is_alive(), "the old pump outlived the restart"
    assert first.connected is False, "the old client was not disconnected"
    assert first.panics == 0
    assert len(FakeWhatsApp.created) == 2
    assert len(_live_bot_threads()) == 1


def test_sends_never_cross_threads(service, store):
    assert service.start_bot() == (True, "Bot started")
    FakeWhatsApp.created[0].on_disconnect_cb()
    assert _wait(lambda: not service.is_running)
    _pair_again(store)
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


# --- the stored session follows the live one ------------------------------------


def _bot_ident(svc):
    return svc._bot_thread.ident


def test_the_session_is_saved_a_while_after_connect(make_service, store):
    """PORTED DEFECT: the session was exported once, at pairing, and never again."""
    svc = make_service(first_save_seconds=0.3, save_interval_seconds=30)
    assert svc.start_bot() == (True, "Bot started")
    client = FakeWhatsApp.created[0]
    client.session = snapshot("after login")
    time.sleep(0.1)
    assert store.writes == [], "saved before the post-login writes were in"
    assert _wait(lambda: len(store.writes) == 1, timeout=3)
    blob, expected, ident = store.writes[0]
    assert blob == snapshot("after login")
    assert expected == START, "a save must replace only the session this run started from"
    assert ident == _bot_ident(svc), "the client was exported off its own thread"
    assert client.panics == 0


def test_the_session_is_saved_again_on_the_interval(make_service, store):
    svc = make_service(first_save_seconds=0.05, save_interval_seconds=0.15)
    assert svc.start_bot() == (True, "Bot started")
    client = FakeWhatsApp.created[0]
    for n in range(3):
        client.session = snapshot(f"state {n}")
        assert _wait(lambda n=n: store.blob == snapshot(f"state {n}"), timeout=3), n
    chain = [expected for _blob, expected, _ident in store.writes]
    assert chain == [START, snapshot("state 0"), snapshot("state 1")], (
        "each save must name the one before it"
    )
    assert client.panics == 0


def test_unchanged_bytes_are_not_rewritten(make_service, store):
    svc = make_service(first_save_seconds=0.05, save_interval_seconds=0.05)
    assert svc.start_bot() == (True, "Bot started")
    client = FakeWhatsApp.created[0]
    assert _wait(lambda: client.exports >= 4, timeout=3)
    assert store.writes == [], "an unchanged session was written again"


def test_the_session_is_saved_when_the_bot_stops(make_service, store):
    svc = make_service(first_save_seconds=60, save_interval_seconds=300)
    assert svc.start_bot() == (True, "Bot started")
    client = FakeWhatsApp.created[0]
    client.session = snapshot("at stop")
    assert svc.stop_bot() == (True, "Bot stopped")
    assert store.blob == snapshot("at stop")
    assert client.calls == ["export", "disconnect"], "the last save must come before the disconnect"
    assert client.panics == 0


def test_a_failing_save_never_stops_the_bot_and_is_logged_once(make_service, store, monkeypatch):
    logged = []
    monkeypatch.setattr(wbs.logger, "exception", lambda *a, **k: logged.append(a))
    svc = make_service(first_save_seconds=0.05, save_interval_seconds=0.05)
    assert svc.start_bot() == (True, "Bot started")
    client = FakeWhatsApp.created[0]
    client.fail_exports = True
    assert _wait(lambda: client.exports >= 4, timeout=3)
    assert len(logged) == 1, f"a run of failures was logged {len(logged)} times"
    assert svc.is_ready() and svc._bot_thread.is_alive()
    assert svc.send_sync(PHONE, "still sending")["sent"] == [PHONE]

    client.fail_exports = False
    client.session = snapshot("recovered")
    assert _wait(lambda: store.blob == snapshot("recovered"), timeout=3)
    client.fail_exports = True
    seen = client.exports
    assert _wait(lambda: client.exports >= seen + 2, timeout=3)
    assert len(logged) == 2, "a new run of failures after a success is logged again"


def test_an_empty_snapshot_is_never_stored(make_service, store, monkeypatch):
    """A snapshot of a session file already deleted is a one-page empty database."""
    monkeypatch.setattr(wbs.logger, "exception", lambda *a, **k: None)
    svc = make_service(first_save_seconds=0.05, save_interval_seconds=0.05)
    assert svc.start_bot() == (True, "Bot started")
    client = FakeWhatsApp.created[0]
    client.session = snapshot("", pages=1)
    assert _wait(lambda: client.exports >= 3, timeout=3)
    svc.stop_bot()
    assert store.writes == [] and store.blob == START


def test_no_save_while_the_device_is_not_logged_in(make_service, store):
    svc = make_service(first_save_seconds=0.05, save_interval_seconds=0.05)
    assert svc.start_bot() == (True, "Bot started")
    client = FakeWhatsApp.created[0]
    client.logged_in = False
    client.session = snapshot("while reconnecting")
    time.sleep(0.3)
    assert client.exports == 0 and store.writes == []


# --- logged out by WhatsApp ---------------------------------------------------------


def test_a_logout_is_reported_and_the_session_is_not_restored(make_service, store, monkeypatch):
    """PORTED DEFECT: "wars on_disconnect fired", and the device stayed marked paired.

    wars 0.1.4 calls on_disconnect for whatsapp-rust's LoggedOut event. The
    device was left paired, so every restart restored the same rejected session
    and alerts failed with "not paired or not connected".
    """
    warned = []
    monkeypatch.setattr(wbs.logger, "warning", lambda msg, *a, **k: warned.append(msg % a))
    svc = make_service(first_save_seconds=60, save_interval_seconds=300)
    assert svc.start_bot() == (True, "Bot started")
    client = FakeWhatsApp.created[0]

    client.on_disconnect_cb()
    assert _wait(lambda: not svc.is_running)
    assert _wait(lambda: store.blob is None)

    assert store.cleared == [START], "only the session this run started from may be cleared"
    assert store.config["is_paired"] is False, "auto-start would restore it again"
    assert wbs.LOGGED_OUT_MESSAGE in warned
    assert not any("on_disconnect fired" in w for w in warned)
    expected = {"is_running": False, "is_paired": False, "status_message": wbs.LOGGED_OUT_MESSAGE}
    assert svc.status_payload() == expected
    assert ("whatsapp_status", expected) in svc.emitted, "the page is not told"
    assert svc.unavailable_reason() == wbs.LOGGED_OUT_MESSAGE
    assert not svc.is_ready()
    report = svc.send_sync(PHONE, "alert")
    assert report["failed"][0]["error"] == wbs.LOGGED_OUT_MESSAGE
    assert svc.start_bot() == (False, wbs.LOGGED_OUT_MESSAGE)

    client.session = snapshot("after the logout")
    svc.stop_bot()
    assert store.writes == [], "a logged-out session was saved"


def test_a_logout_of_a_replaced_session_leaves_the_new_pairing_alone(make_service, store):
    svc = make_service(first_save_seconds=60, save_interval_seconds=300)
    assert svc.start_bot() == (True, "Bot started")
    store.blob = snapshot("a newer pairing")
    FakeWhatsApp.created[0].on_disconnect_cb()
    assert _wait(lambda: not svc.is_running)
    assert _wait(lambda: store.cleared == [START])
    time.sleep(0.2)
    assert store.blob == snapshot("a newer pairing")
    assert svc.unavailable_reason() is None


def test_flow_reports_the_logout(make_service, store, monkeypatch):
    from services.flow_openalgo_client import FlowOpenAlgoClient

    svc = make_service()
    assert svc.start_bot() == (True, "Bot started")
    FakeWhatsApp.created[0].on_disconnect_cb()
    assert _wait(lambda: svc.unavailable_reason() is not None)
    monkeypatch.setattr(wbs, "whatsapp_bot_service", svc)
    result = FlowOpenAlgoClient.whatsapp(types.SimpleNamespace(), "09:15 alert")
    assert result == {"status": "error", "error": wbs.LOGGED_OUT_MESSAGE}


def test_on_connected_restores_the_running_state(make_service, store, monkeypatch):
    active = []
    monkeypatch.setattr(wbs, "update_bot_config", lambda values: active.append(values))
    svc = make_service(first_save_seconds=60, save_interval_seconds=300)
    assert svc.start_bot() == (True, "Bot started")
    client = FakeWhatsApp.created[0]
    assert client.on_connected_cb is not None, "on_connected is not registered"
    with svc._lock:
        svc._is_running = False  # the service lost track of a live client
    assert not svc.is_ready()

    client.on_connected_cb()
    assert _wait(svc.is_ready)
    assert {"is_active": True} in active
    assert _wait(
        lambda: (
            svc.emitted[-1]
            == ("whatsapp_status", {"is_running": True, "is_paired": True, "status_message": None})
        )
    )


def test_on_connected_does_not_bring_back_a_logged_out_client(make_service, store):
    svc = make_service()
    assert svc.start_bot() == (True, "Bot started")
    client = FakeWhatsApp.created[0]
    client.on_disconnect_cb()
    assert _wait(lambda: svc.unavailable_reason() is not None)
    client.on_connected_cb()
    time.sleep(0.3)
    assert not svc.is_running and not svc.is_ready()


def test_a_reconnect_brings_the_next_save_forward(make_service, store):
    svc = make_service(first_save_seconds=0.2, save_interval_seconds=60)
    assert svc.start_bot() == (True, "Bot started")
    client = FakeWhatsApp.created[0]
    client.session = snapshot("first login")
    assert _wait(lambda: len(store.writes) == 1, timeout=3)
    client.session = snapshot("after reconnecting")
    client.on_connected_cb()  # whatsapp-rust logged in again by itself
    assert _wait(lambda: len(store.writes) == 2, timeout=3), "the reconnect's writes were not saved"


# --- a normal stop of the server ------------------------------------------------------


def test_the_server_stop_saves_the_session(make_service, store):
    import utils.shutdown as shutdown

    hooks = [h for h in shutdown._registered_hooks(early=False) if h.name == "whatsapp_bot"]
    assert hooks, "nothing stops the bot on a graceful shutdown"
    assert hooks[0].budget_s <= 3.0

    svc = make_service(first_save_seconds=60, save_interval_seconds=300)
    assert svc.start_bot() == (True, "Bot started")
    FakeWhatsApp.created[0].session = snapshot("at shutdown")
    svc.stop_for_exit()
    assert store.blob == snapshot("at shutdown")
    assert not svc.is_running and not _live_bot_threads()


def test_the_server_stop_waits_a_couple_of_seconds_at_most(make_service, store, monkeypatch):
    assert wbs.SHUTDOWN_JOIN_SECONDS <= 2.0
    monkeypatch.setattr(wbs, "SHUTDOWN_JOIN_SECONDS", 0.3)  # the same bound, sooner
    svc = make_service(first_save_seconds=60, save_interval_seconds=300)
    assert svc.start_bot() == (True, "Bot started")
    client = FakeWhatsApp.created[0]
    client.export_gate = threading.Event()  # the last save hangs
    started = time.monotonic()
    svc.stop_for_exit()
    took = time.monotonic() - started
    client.export_gate.set()
    assert took < 0.3 + 0.5, f"shutdown held for {took:.1f}s"


def test_the_exit_stop_runs_before_wars_deletes_the_session_file(make_service, monkeypatch):
    """atexit runs the most recent registration first."""
    log: list = []
    recorder = types.SimpleNamespace(
        register=lambda fn, *a, **k: log.append(("register", fn)),
        unregister=lambda fn: log.append(("unregister", fn)),
    )
    monkeypatch.setattr(wbs, "atexit", recorder)
    svc = make_service()
    FakeWhatsApp.atexit_log = log
    assert svc.start_bot() == (True, "Bot started")
    registrations = [fn for kind, fn in log if kind == "register"]
    assert registrations[-1] == svc.stop_for_exit
    assert registrations.index("wars deletes the session file") < len(registrations) - 1


# --- database/whatsapp_db against a real SQLite file ---------------------------------


@pytest.fixture
def wa_db(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import scoped_session, sessionmaker
    from sqlalchemy.pool import NullPool

    import database.whatsapp_db as wdb

    engine = create_engine(
        f"sqlite:///{(tmp_path / 'wa.db').as_posix()}",
        poolclass=NullPool,
        connect_args={"check_same_thread": False},
    )
    wdb.Base.metadata.create_all(engine)
    session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
    monkeypatch.setattr(wdb, "db_session", session)
    yield wdb
    session.remove()
    engine.dispose()


def test_a_refresh_replaces_only_the_session(wa_db):
    assert wa_db.save_session_blob(START, own_jid="91@s.whatsapp.net", owner_username="admin")
    before = wa_db.get_bot_config()
    assert wa_db.refresh_session_blob(snapshot("live"), expected=START) is True
    after = wa_db.get_bot_config()
    assert wa_db.load_session_blob() == snapshot("live")
    for field in ("paired_at", "owner_username", "own_jid", "is_paired"):
        assert after[field] == before[field], field


def test_a_refresh_after_unlink_does_not_resurrect_the_device(wa_db):
    assert wa_db.save_session_blob(START, owner_username="admin")
    assert wa_db.clear_session_blob()
    assert wa_db.refresh_session_blob(snapshot("late"), expected=START) is False
    assert wa_db.refresh_session_blob(snapshot("late")) is False
    assert wa_db.load_session_blob() is None
    assert wa_db.get_bot_config()["is_paired"] is False


def test_a_refresh_never_overwrites_a_newer_pairing(wa_db):
    assert wa_db.save_session_blob(START)
    assert wa_db.save_session_blob(snapshot("paired again"))
    assert wa_db.refresh_session_blob(snapshot("late"), expected=START) is False
    assert wa_db.load_session_blob() == snapshot("paired again")


def test_a_logout_clears_only_the_session_it_names(wa_db):
    assert wa_db.save_session_blob(START, own_jid="91@s.whatsapp.net", owner_username="admin")
    assert wa_db.clear_rejected_session(snapshot("another")) is False
    assert wa_db.load_session_blob() == START
    assert wa_db.clear_rejected_session(START) is True
    cfg = wa_db.get_bot_config()
    assert wa_db.load_session_blob() is None
    assert cfg["is_paired"] is False and cfg["own_jid"] is None and cfg["owner_username"] is None


def test_a_save_that_lands_after_an_unlink_does_not_resurrect_the_device(wa_db, monkeypatch):
    """The unlink's stop timed out while the bot was exporting; its save came later."""
    FakeWhatsApp.created = []
    FakeWhatsApp.connect_delay = 0.0
    FakeWhatsApp.atexit_log = None
    fake_wars = types.ModuleType("wars")
    fake_wars.WhatsApp = FakeWhatsApp
    monkeypatch.setitem(__import__("sys").modules, "wars", fake_wars)
    monkeypatch.setattr(wbs, "log_command", lambda *args, **kwargs: None)
    assert wa_db.save_session_blob(START, owner_username="admin")

    svc = wbs.WhatsAppBotService(first_save_seconds=0.05, save_interval_seconds=60)
    monkeypatch.setattr(svc, "_emit", lambda event, payload: None)
    assert svc.start_bot() == (True, "Bot started")
    client = FakeWhatsApp.created[0]
    thread = svc._bot_thread
    client.export_gate = threading.Event()
    client.session = snapshot("exported before the unlink")
    assert client.in_export.wait(3), "the save never started"

    monkeypatch.setattr(wbs, "BOT_JOIN_SECONDS", 0.2)
    assert svc.unlink() == (True, "Device unlinked")
    client.export_gate.set()
    thread.join(5)
    assert not thread.is_alive()
    assert client.exports >= 2, "the late save and the last save both ran"
    assert wa_db.load_session_blob() is None, "a late save brought an unlinked device back"
    assert wa_db.get_bot_config()["is_paired"] is False


# --- the send endpoints keep their contract -------------------------------------------


def _function_source(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return "\n".join(text.splitlines()[node.lineno - 1 : node.end_lineno])
    raise AssertionError(f"{name} is not defined in {path.name}")


def test_the_page_routes_name_the_logout_and_keep_their_answers():
    blueprint = Path(wbs.__file__).resolve().parents[1] / "blueprints" / "whatsapp.py"
    refusal = _function_source(blueprint, "_not_ready_response")
    assert "unavailable_reason()" in refusal and "NOT_READY_MESSAGE" in refusal
    assert '"status": "error"' in refusal and "409" in refusal
    for route in ("broadcast", "test_message", "send_to_phone"):
        assert "_not_ready_response()" in _function_source(blueprint, route), route
    assert 'cfg["status_message"] = whatsapp_bot_service.unavailable_reason()' in (
        _function_source(blueprint, "get_config")
    )
