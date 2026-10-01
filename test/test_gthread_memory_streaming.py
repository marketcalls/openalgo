"""Repeated broker reconnects must release the previous heartbeat worker."""

import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pocketful_rapid_reconnects_keep_one_heartbeat_thread():
    # Run in a child so the regression's sleeping daemon threads cannot affect
    # the rest of the suite before the fix is applied.
    script = textwrap.dedent(
        """
        import logging
        import threading
        import time

        import dotenv
        dotenv.load_dotenv = lambda *args, **kwargs: False
        dotenv.main.load_dotenv = dotenv.load_dotenv
        logging.disable(logging.CRITICAL)

        import websocket_proxy  # load the package before its broker imports
        from broker.pocketful.streaming.pocketful_adapter import PocketfulWebSocketAdapter

        class Socket:
            def __init__(self):
                self.sent = 0
            def send(self, _payload):
                self.sent += 1
            def close(self):
                pass

        adapter = object.__new__(PocketfulWebSocketAdapter)
        adapter.logger = logging.getLogger("pocketful-heartbeat-test")
        adapter.running = True
        adapter.connected = False
        adapter.ws_client = Socket()
        adapter.lock = threading.Lock()
        adapter.subscriptions = {}
        adapter._heartbeat_stop = None
        adapter._reconnect_stop = threading.Event()
        baseline = threading.active_count()

        for cycle in range(120):
            adapter._on_open(adapter.ws_client)
            deadline = time.monotonic() + 2
            while adapter.ws_client.sent <= cycle and time.monotonic() < deadline:
                time.sleep(0.001)
            assert adapter.ws_client.sent > cycle, f"heartbeat {cycle} did not run"
            adapter._on_close(adapter.ws_client)

        adapter._on_open(adapter.ws_client)
        deadline = time.monotonic() + 2
        while threading.active_count() > baseline + 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        active = threading.active_count() - baseline
        adapter.disconnect()
        assert active <= 2, f"{active} heartbeat threads retained after 120 reconnects"
        deadline = time.monotonic() + 2
        while threading.active_count() > baseline and time.monotonic() < deadline:
            time.sleep(0.01)
        assert threading.active_count() == baseline, "disconnect retained a heartbeat thread"
        print("OK")
        """
    )
    result = subprocess.run(
        [sys.executable, "-u", "-c", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_pocketful_repeated_connect_during_backoff_keeps_one_retry_thread():
    # The fake socket closes immediately, so each retry loop enters its full
    # backoff without touching a broker or waiting for a real network timeout.
    script = textwrap.dedent(
        """
        import logging
        import threading
        import time

        import dotenv
        dotenv.load_dotenv = lambda *args, **kwargs: False
        dotenv.main.load_dotenv = dotenv.load_dotenv
        logging.disable(logging.CRITICAL)

        import websocket_proxy
        from broker.pocketful.streaming import pocketful_adapter as module

        entered = threading.Event()
        class Socket:
            def __init__(self, *_args, **_kwargs):
                pass
            def run_forever(self):
                entered.set()
            def close(self):
                pass
        module.websocket.WebSocketApp = Socket
        module.get_auth_token = lambda *_args, **_kwargs: "token"

        adapter = object.__new__(module.PocketfulWebSocketAdapter)
        adapter.logger = logging.getLogger("pocketful-retry-test")
        adapter.running = True
        adapter.connected = False
        adapter.user_id = "test"
        adapter.access_token = "token"
        adapter.reconnect_attempts = 0
        adapter.max_reconnect_attempts = 1000
        adapter.reconnect_delay = 60
        adapter.max_reconnect_delay = 60
        adapter.ws_client = None
        adapter.lock = threading.Lock()
        adapter._reconnect_stop = threading.Event()
        adapter._connect_thread = None
        adapter._heartbeat_stop = None
        baseline = threading.active_count()

        adapter.connect()
        assert entered.wait(2), "retry thread did not enter broker socket"
        for _ in range(120):
            adapter.connect()
        time.sleep(0.1)
        active = threading.active_count() - baseline
        assert active <= 1, f"{active} retry threads started during one backoff"
        adapter.disconnect()
        deadline = time.monotonic() + 2
        while threading.active_count() > baseline and time.monotonic() < deadline:
            time.sleep(0.01)
        assert threading.active_count() == baseline, "logout retained retry thread in backoff"
        print("OK")
        """
    )
    result = subprocess.run(
        [sys.executable, "-u", "-c", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_pocketful_logout_during_token_read_cannot_open_a_socket():
    script = textwrap.dedent(
        """
        import logging
        import threading
        import time

        import dotenv
        dotenv.load_dotenv = lambda *args, **kwargs: False
        dotenv.main.load_dotenv = dotenv.load_dotenv
        logging.disable(logging.CRITICAL)

        import websocket_proxy
        from broker.pocketful.streaming import pocketful_adapter as module

        reading = threading.Event()
        finish_read = threading.Event()
        made_socket = []
        def read_token(*_args, **_kwargs):
            reading.set()
            assert finish_read.wait(2)
            return "revoked-token"
        class Socket:
            def __init__(self, *_args, **_kwargs):
                made_socket.append(1)
            def run_forever(self):
                pass
            def close(self):
                pass
        module.get_auth_token = read_token
        module.websocket.WebSocketApp = Socket

        adapter = object.__new__(module.PocketfulWebSocketAdapter)
        adapter.logger = logging.getLogger("pocketful-logout-test")
        adapter.running = True
        adapter.connected = False
        adapter.user_id = "test"
        adapter.access_token = "old-token"
        adapter.reconnect_attempts = 0
        adapter.max_reconnect_attempts = 10
        adapter.reconnect_delay = 1
        adapter.max_reconnect_delay = 1
        adapter.ws_client = None
        adapter.lock = threading.Lock()
        adapter._reconnect_stop = threading.Event()
        adapter._connect_thread = None
        adapter._heartbeat_stop = None

        adapter.connect()
        assert reading.wait(2), "retry thread did not reach token read"
        adapter.disconnect()
        finish_read.set()
        deadline = time.monotonic() + 2
        while adapter._connect_thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not adapter._connect_thread.is_alive(), "logged-out retry thread survived"
        assert not made_socket, "logged-out retry opened a socket with revoked token"
        print("OK")
        """
    )
    result = subprocess.run(
        [sys.executable, "-u", "-c", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout
