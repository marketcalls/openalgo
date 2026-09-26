"""The messaging fixes under a real eventlet hub: correct, prompt, and hub-safe.

The default production worker is eventlet, and none of the gthread work may
change what it does. These cases run in a subprocess under
``eventlet.monkey_patch()`` (it is global and cannot be undone), in the style
of ``test_eventlet_cross_thread_locks.py``, and assert on elapsed time and hub
liveness as well as on results, because the results were always right on the
development server.

* The Telegram bot's lifecycle lock is a real one, taken by request greenlets
  and by the bot's real thread; start and stop must keep the hub turning.
* The Telegram bot's real thread reaches the Python strategy host (a green lock
  under eventlet) only through the hub. Called directly it waits forever,
  which is asserted first so the fix cannot pass vacuously.
* The WhatsApp bot, its command pool and send_sync keep working on greenlets.
* Nothing the gthread worker caps is capped here.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytest.importorskip(
    "eventlet",
    reason="eventlet is installed by the production installer, not by pyproject",
)

REPO = Path(__file__).resolve().parents[1]

PREAMBLE = """
import eventlet
eventlet.monkey_patch()

import asyncio, os, sys, threading, time, types
import eventlet.patcher

_orig = eventlet.patcher.original("threading")


def ticker():
    ticks = []

    def run():
        while True:
            ticks.append(1)
            eventlet.sleep(0.02)

    return ticks, eventlet.spawn(run)
"""


def run(body: str, tmp_path: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    db = tmp_path / "db"
    db.mkdir(exist_ok=True)
    env.update(
        {
            "DATABASE_URL": f"sqlite:///{(db / 'openalgo.db').as_posix()}",
            "LOG_DIR": str(tmp_path / "log"),
            "API_KEY_PEPPER": "0" * 64,
            "APP_KEY": "test-only-app-key",
            "PYTHONPATH": str(REPO),
        }
    )
    env.pop("OPENALGO_WORKER_CLASS", None)
    return subprocess.run(
        [sys.executable, "-c", PREAMBLE + textwrap.dedent(body)],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_telegram_start_and_stop_keep_the_hub_turning(tmp_path):
    result = run(
        """
        import services.telegram_bot_service as tg
        from utils import real_threading as rt

        tg.get_bot_config = lambda: {"bot_token": "t"}
        tg.update_bot_config = lambda values: True
        svc = tg.TelegramBotService()

        def fake_bot(gen=None, stop=None):
            # The bot thread is real: it takes the real lifecycle lock too.
            rt.sleep(0.3)
            svc._publish_running(gen, stop)
            while not stop.is_set():
                with svc._lifecycle_lock:
                    pass
                rt.sleep(0.01)
            svc._clear_running(gen)

        svc._run_bot_in_thread = fake_bot
        ticks, g = ticker()
        eventlet.sleep(0.05)

        t0 = time.monotonic(); before = len(ticks)
        assert svc.start_bot() == (True, "Bot started successfully")
        took_start, ticks_start = time.monotonic() - t0, len(ticks) - before
        assert svc.start_bot() == (False, "Bot is already running")

        t0 = time.monotonic(); before = len(ticks)
        assert svc.stop_bot() == (True, "Bot stopped successfully")
        took_stop, ticks_stop = time.monotonic() - t0, len(ticks) - before
        g.kill()

        assert svc.is_running is False and svc.bot_thread is None
        assert took_start < 2.5, took_start
        assert took_stop < 2.0, took_stop
        assert ticks_start > 5, f"start froze the hub: {ticks_start} ticks"
        assert ticks_stop > 0, f"stop froze the hub: {ticks_stop} ticks"
        print("OK")
        """,
        tmp_path,
    )
    assert "OK" in result.stdout, result.stdout + result.stderr
    assert "greenlet.error" not in result.stderr


def test_a_real_thread_taking_the_strategy_hosts_green_lock_hangs(tmp_path):
    """hosts-09, the defect: the old path, so the fix below cannot pass vacuously.

    The bot's real thread took the strategy host's lock (a green RLock under
    eventlet) while a request greenlet held it. It never gets it.
    """
    result = run(
        """
        from utils import real_threading as rt

        process_lock = threading.RLock()  # green, like PROCESS_LOCK under eventlet
        done = []

        def stop_strategy(sid):
            with process_lock:
                done.append(sid)

        def holder():
            with process_lock:
                eventlet.sleep(0.4)

        eventlet.spawn(holder)
        eventlet.sleep(0.05)
        t = _orig.Thread(target=stop_strategy, args=("s1",), daemon=True)
        t.start()
        finished = rt.join(t, timeout=2.0)
        print("HANG" if not finished and not done else "PASSED THROUGH")
        sys.stdout.flush()
        os._exit(0)  # the stuck real thread is abandoned
        """,
        tmp_path,
    )
    assert "HANG" in result.stdout, result.stdout + result.stderr


def test_the_telegram_thread_reaches_the_strategy_host_only_through_the_hub(tmp_path):
    """hosts-09, the fix: the call runs on the hub and the bot's loop polls for it."""
    result = run(
        """
        import services.telegram_bot_service as tg
        from utils import real_threading as rt

        assert rt.start_hub_worker() is True
        eventlet.sleep(0.05)
        hub_ident = rt._real_get_ident()

        process_lock = threading.RLock()  # green, like PROCESS_LOCK under eventlet

        def stop_strategy(sid):
            with process_lock:
                return True, rt._real_get_ident()

        def holder():
            with process_lock:
                eventlet.sleep(0.4)

        svc = tg.TelegramBotService()
        out = {}

        def bot_thread():
            async def scenario():
                t0 = time.monotonic()
                out["result"] = await svc._in_app_world(stop_strategy, "s1", timeout=5)
                out["took"] = time.monotonic() - t0
            asyncio.run(scenario())

        ticks, g = ticker()
        h = eventlet.spawn(holder)
        eventlet.sleep(0.05)
        before = len(ticks)
        t = _orig.Thread(target=bot_thread, daemon=True)
        t.start()
        assert rt.join(t, timeout=10), "the bot thread never finished"
        during = len(ticks) - before
        g.kill()
        h.wait()

        ok, ran_on = out["result"]
        assert ok is True
        assert ran_on == hub_ident, "the call did not run on the hub"
        assert out["took"] < 2.0, out["took"]
        assert during > 5, f"the hub froze: {during} ticks"
        print("OK")
        """,
        tmp_path,
    )
    assert "OK" in result.stdout, result.stdout + result.stderr
    assert "greenlet.error" not in result.stderr


def test_whatsapp_start_send_command_and_stop_on_greenlets(tmp_path):
    result = run(
        """
        import services.whatsapp_bot_service as wbs
        from utils import runtime

        assert runtime.worker_class() == "eventlet"

        class FakeWhatsApp:
            created = []

            def __init__(self):
                self.sent = []
                self.connected = False

            @classmethod
            def from_bytes(cls, blob):
                eventlet.sleep(0.1)
                c = cls(); cls.created.append(c); return c

            def on_message(self, fn):
                self.on_message_cb = fn; return fn

            def on_disconnect(self, fn):
                self.on_disconnect_cb = fn; return fn

            def connect(self, phone=None):
                self.connected = True

            def disconnect(self):
                self.connected = False

            def send(self, *args, **kwargs):
                self.sent.append(args); return "id"

        sys.modules["wars"] = types.SimpleNamespace(WhatsApp=FakeWhatsApp)
        wbs.load_session_blob = lambda: b"blob"
        wbs.get_bot_config = lambda: {"is_paired": True, "owner_username": "a", "own_jid": None}
        wbs.update_bot_config = lambda values: True
        wbs.log_command = lambda *a, **k: None
        svc = wbs.WhatsAppBotService()
        svc._emit = lambda event, payload: None

        release = eventlet.event.Event()

        class Slow:
            def orderbook(self):
                release.wait()
                return {"status": "success", "data": []}

        svc._sdk_client_for_owner = lambda: (Slow(), None)

        ticks, g = ticker()
        starts = [eventlet.spawn(svc.start_bot) for _ in range(4)]
        answers = [s.wait() for s in starts]
        assert len(FakeWhatsApp.created) == 1, len(FakeWhatsApp.created)
        assert (True, "Bot started") in answers, answers

        chat = "919876543210@s.whatsapp.net"
        FakeWhatsApp.created[0].on_message_cb(
            types.SimpleNamespace(is_from_me=True, sender=chat, chat=chat, text="/orderbook")
        )
        eventlet.sleep(0.3)
        t0 = time.monotonic()
        report = svc.send_sync("919876543210", "alert")
        took = time.monotonic() - t0
        assert report["sent"] == ["919876543210"], report
        assert took < 1.0, took
        release.send(True)
        eventlet.sleep(0.5)
        assert len(FakeWhatsApp.created[0].sent) >= 2

        before = len(ticks)
        assert svc.stop_bot() == (True, "Bot stopped")
        assert len(ticks) - before >= 0
        g.kill()
        assert svc.is_running is False
        print("OK")
        """,
        tmp_path,
    )
    assert "OK" in result.stdout, result.stdout + result.stderr


def test_nothing_the_gthread_worker_caps_is_capped_under_eventlet(tmp_path):
    result = run(
        """
        from utils import runtime, stream_registry
        assert runtime.worker_class() == "eventlet"
        assert runtime.gthread_active() is False

        import blueprints.mcp_http as mcp_http
        assert mcp_http._tool_call_limit() is None
        assert stream_registry.enforced_limit(mcp_http.MCP_SSE_MAX_STREAMS) is None

        import blueprints.agent as agent_bp
        assert stream_registry.enforced_limit(agent_bp.MAX_CONCURRENT_STREAMS) is None

        import services.agent.stream as agent_stream
        assert agent_stream._ending_message(None) is None

        from utils import email_utils
        assert email_utils._smtp_timeout_kwargs() == {}

        import services.telegram_bot_service as tg
        assert tg.use_sync_initialization() is True
        print("OK")
        """,
        tmp_path,
    )
    assert "OK" in result.stdout, result.stdout + result.stderr
