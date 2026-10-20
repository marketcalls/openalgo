"""Dhan's Forever Order HTTP client is built once, however many threads ask.

``broker/dhan/api/gtt_api._get_client`` built its dedicated HTTP/1.1 client
lazily with an unguarded ``if client is None: client = httpx.Client(...)``.
Under eventlet nothing between the check and the assignment yields, so it
could not interleave. Under the gthread worker two requests placing or
listing Forever Orders at once can both see None and both build a client; the
first one assigned is overwritten while its caller may still be using it, and
is never closed. It is now a ``utils.lazy.LazyInit``.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from broker.dhan.api import gtt_api

THREADS = 16


class _SlowClient:
    """Stands in for httpx.Client; slow to build, so a race has room to happen."""

    built: list[_SlowClient] = []
    lock = threading.Lock()

    def __init__(self, **kwargs):
        time.sleep(0.05)
        self.kwargs = kwargs
        with _SlowClient.lock:
            _SlowClient.built.append(self)


def _forget_client():
    holder = gtt_api._dhan_gtt_client
    if hasattr(holder, "reset"):
        holder.reset()
    else:  # the unguarded global it replaced
        gtt_api._dhan_gtt_client = None


@pytest.fixture
def slow_httpx(monkeypatch):
    _SlowClient.built = []
    monkeypatch.setattr(gtt_api, "httpx", SimpleNamespace(Client=_SlowClient))
    _forget_client()
    yield
    _forget_client()


def test_concurrent_first_use_builds_one_client(slow_httpx):
    barrier = threading.Barrier(THREADS)
    got = []
    lock = threading.Lock()

    def worker():
        barrier.wait(10)
        client = gtt_api._get_client()
        with lock:
            got.append(client)

    threads = [threading.Thread(target=worker) for _ in range(THREADS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)

    assert len(_SlowClient.built) == 1, f"{len(_SlowClient.built)} clients built"
    assert len(got) == THREADS
    assert all(client is got[0] for client in got)


def test_the_client_is_http11_with_an_explicit_timeout(slow_httpx):
    client = gtt_api._get_client()
    assert client.kwargs == {"http2": False, "timeout": 30.0}
    assert gtt_api._get_client() is client
