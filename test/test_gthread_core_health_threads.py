"""The health check does not fail a healthy gthread instance for its thread pool.

The thread thresholds (50 warn, 100 fail) were sized for eventlet, where the
work runs on green threads. Under gthread the request pool alone is 64
threads before a single browser connection, the event bus or a scheduler is
counted, so /health/status answered 503 and load balancers took a healthy
instance out. There the defaults now sit above the pool; explicit settings
win; under eventlet and the dev server nothing changes. The thread budget
(open streams and browser connections against the pool) is reported beside
it.
"""

from __future__ import annotations

import threading

import pytest

import utils.health_monitor as hm
from utils import runtime


@pytest.fixture
def parked_threads():
    release = threading.Event()
    threads = [threading.Thread(target=release.wait, args=(30,), daemon=True) for _ in range(120)]
    for thread in threads:
        thread.start()
    yield threads
    release.set()
    for thread in threads:
        thread.join(5)


@pytest.fixture
def no_alerts(monkeypatch):
    monkeypatch.setattr(hm.HealthAlert, "create_alert", staticmethod(lambda **kwargs: None))
    monkeypatch.setattr(
        hm.HealthAlert, "auto_resolve_alerts", staticmethod(lambda *args, **kwargs: None)
    )


def test_a_busy_gthread_instance_is_not_failed(parked_threads, no_alerts, monkeypatch):
    monkeypatch.delenv("HEALTH_THREAD_WARNING_THRESHOLD", raising=False)
    monkeypatch.delenv("HEALTH_THREAD_CRITICAL_THRESHOLD", raising=False)
    monkeypatch.setattr(runtime, "gthread_active", lambda: True)
    monkeypatch.setattr(runtime, "configured_threads", lambda: 64)

    metrics = hm.get_thread_metrics()

    # Before the fix: 120+ threads against a fixed 100 was "fail", a 503.
    assert metrics["status"] != "fail"
    assert metrics["budget"]["threads"] == 64
    assert hm._thread_thresholds() == (144, 224)


def test_an_unknown_gthread_pool_assumes_the_launchers_constant(monkeypatch):
    monkeypatch.delenv("HEALTH_THREAD_WARNING_THRESHOLD", raising=False)
    monkeypatch.delenv("HEALTH_THREAD_CRITICAL_THRESHOLD", raising=False)
    monkeypatch.setattr(runtime, "gthread_active", lambda: True)
    monkeypatch.setattr(runtime, "configured_threads", lambda: None)
    assert hm._thread_thresholds() == (144, 224)


def test_explicit_thresholds_still_win_under_gthread(monkeypatch):
    monkeypatch.setenv("HEALTH_THREAD_WARNING_THRESHOLD", "70")
    monkeypatch.setenv("HEALTH_THREAD_CRITICAL_THRESHOLD", "90")
    monkeypatch.setattr(hm, "THREAD_WARNING_THRESHOLD", 70)
    monkeypatch.setattr(hm, "THREAD_CRITICAL_THRESHOLD", 90)
    monkeypatch.setattr(runtime, "gthread_active", lambda: True)
    monkeypatch.setattr(runtime, "configured_threads", lambda: 64)
    assert hm._thread_thresholds() == (70, 90)


def test_eventlet_and_the_dev_server_are_unchanged(parked_threads, no_alerts, monkeypatch):
    monkeypatch.setattr(runtime, "gthread_active", lambda: False)
    assert hm._thread_thresholds() == (hm.THREAD_WARNING_THRESHOLD, hm.THREAD_CRITICAL_THRESHOLD)

    metrics = hm.get_thread_metrics()
    assert "budget" not in metrics
    if hm.THREAD_CRITICAL_THRESHOLD <= 120:
        assert metrics["status"] == "fail"
