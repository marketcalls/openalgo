"""HDFC snapshot feeds must not freeze the eventlet hub while they connect.

HDFC Securities and HDFC Sky serve quotes, depth and option-chain OI through a
short-lived feed socket opened per request. Its reader runs on a real OS
thread, which sets ``_connection_ready``, a real Event, once the socket is up.
The request waited for that with ``Event.wait()``. Under eventlet the request
is a greenlet, and a greenlet blocking on a real primitive blocks the hub's
OS thread, so the single worker served nothing for the whole handshake: up to
eight seconds when the broker was slow (CLAUDE.md, rule B).

``wait_for_connection`` now waits through ``utils.real_threading.wait_for``,
which polls the flag and yields under eventlet and is the native wait
everywhere else. The eventlet cases run in a subprocess, because
``monkey_patch()`` cannot be undone, and measure hub liveness, which is the
only thing that ever differed: the return value was always right. The first
eventlet case asserts the defect itself, so the pair cannot pass vacuously.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: Importing a broker's streaming client first runs its package __init__, which
#: imports the adapter and through it websocket_proxy, which imports every
#: adapter again. The app imports websocket_proxy at startup, so it never meets
#: the cycle; a test that starts from the client has to do the same.
PRELOAD = "websocket_proxy"

CLIENTS = [
    ("broker.hdfcsecurities.streaming.hdfcsecurities_websocket", "HDFCSecuritiesWebSocket"),
    ("broker.hdfcsky.streaming.hdfcsky_websocket", "HDFCSkyWebSocket"),
]


def _client_class(module_name, class_name):
    __import__(PRELOAD)
    module = __import__(module_name, fromlist=[class_name])
    return getattr(module, class_name)


@pytest.mark.parametrize(("module_name", "class_name"), CLIENTS)
def test_the_wait_returns_as_soon_as_the_feed_thread_reports_the_socket_open(
    module_name, class_name
):
    client = _client_class(module_name, class_name)(access_token="token")

    timer = threading.Timer(0.3, client._connection_ready.set)
    timer.start()
    started = time.monotonic()
    try:
        assert client.wait_for_connection(timeout=5) is True
    finally:
        timer.cancel()
    assert time.monotonic() - started < 2


@pytest.mark.parametrize(("module_name", "class_name"), CLIENTS)
def test_the_wait_times_out_when_the_socket_never_opens(module_name, class_name):
    client = _client_class(module_name, class_name)(access_token="token")

    started = time.monotonic()
    assert client.wait_for_connection(timeout=0.3) is False
    assert 0.25 <= time.monotonic() - started < 2


# --- under a real eventlet hub ------------------------------------------------

EVENTLET_SCRIPT = """
import eventlet
eventlet.monkey_patch()

import sys, time

sys.path.insert(0, {root!r})

from utils import real_threading
import {preload}
from {module_name} import {class_name}

client = {class_name}(access_token="token")
ticks = [0]
running = [True]


def ticker():
    while running[0]:
        ticks[0] += 1
        eventlet.sleep(0.05)


def feed_thread():
    # The real OS thread that sets the Event once the socket is up.
    real_threading.sleep(1.0)
    client._connection_ready.set()


eventlet.spawn(ticker)
eventlet.sleep(0.1)
before = ticks[0]
real_threading.Thread(target=feed_thread, daemon=True).start()
started = time.monotonic()
if {defect!r}:
    ok = client._connection_ready.wait(3)
else:
    ok = client.wait_for_connection(timeout=3)
elapsed = time.monotonic() - started
advanced = ticks[0] - before
running[0] = False
print(f"RESULT ok={{ok}} elapsed={{elapsed:.2f}} advanced={{advanced}}")
"""


def _run_under_eventlet(module_name, class_name, defect):
    script = EVENTLET_SCRIPT.format(
        root=str(ROOT),
        preload=PRELOAD,
        module_name=module_name,
        class_name=class_name,
        defect=defect,
    )
    proc = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(ROOT),
        env=dict(os.environ),
    )
    lines = [line for line in proc.stdout.splitlines() if line.startswith("RESULT ")]
    assert proc.returncode == 0 and lines, proc.stdout[-2000:] + proc.stderr[-4000:]
    fields = dict(item.split("=") for item in lines[-1].split()[1:])
    return fields["ok"] == "True", float(fields["elapsed"]), int(fields["advanced"])


@pytest.mark.parametrize(("module_name", "class_name"), CLIENTS)
def test_eventlet_defect_a_blocking_wait_on_the_real_event_freezes_the_hub(module_name, class_name):
    """What the old code did: the green ticker never runs during the wait."""
    pytest.importorskip("eventlet", reason="eventlet is installed by the production installer")
    ok, elapsed, advanced = _run_under_eventlet(module_name, class_name, defect=True)
    assert ok, "the feed thread's set() should still end the wait"
    assert elapsed >= 0.9
    assert advanced <= 2, f"the hub kept running ({advanced} ticks); the defect is not reproduced"


@pytest.mark.parametrize(("module_name", "class_name"), CLIENTS)
def test_eventlet_wait_for_connection_keeps_the_hub_serving(module_name, class_name):
    pytest.importorskip("eventlet", reason="eventlet is installed by the production installer")
    ok, elapsed, advanced = _run_under_eventlet(module_name, class_name, defect=False)
    assert ok
    assert 0.9 <= elapsed < 3
    # About twenty ticks fit in the one-second handshake at 50 ms each.
    assert advanced >= 15, f"the hub stalled during the wait ({advanced} ticks)"
