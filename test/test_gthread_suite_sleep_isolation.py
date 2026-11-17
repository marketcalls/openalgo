"""A fake sleep stays inside the module it was given to.

The gthread suite runs in one interpreter alongside threads earlier tests left
running. chartink's order loop is one: it idles on ``time.sleep(0.1)``. A test
that wrote ``monkeypatch.setattr(module.time, "sleep", recorder)`` replaced the
shared ``time.sleep``, so that loop spun at full speed filling the recorder,
``assert slept == []`` failed on millions of entries, and formatting the
failure while the loop held the GIL ran past the 120s timeout. That was the
gthread-migration failure on main in run 38561590951.

The first test asserts the defect itself, so the second cannot pass vacuously.
"""

from __future__ import annotations

import threading
import time
import types

import pytest

REAL_SLEEP = time.sleep
BYSTANDER = "sleep-isolation-bystander"


def _module_using_time(
    source: str = "import time\n\ndef wait(seconds):\n    time.sleep(seconds)\n",
):
    module = types.ModuleType("sleep_isolation_target")
    exec(source, module.__dict__)
    return module


class _Bystander:
    """A thread outside the module under test that idles on time.sleep."""

    def __init__(self):
        self.stop = threading.Event()
        self.loops = 0
        self.thread = threading.Thread(target=self._run, name=BYSTANDER, daemon=True)

    def _run(self):
        while not self.stop.is_set():
            self.loops += 1
            time.sleep(0.05)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
        self.thread.join(5)


def test_patching_module_time_reaches_every_thread(monkeypatch):
    """The defect: ``module.time`` is the shared module, so every thread gets the fake."""
    target = _module_using_time()
    callers = []
    seen = threading.Event()

    def recorder(seconds):
        callers.append(threading.current_thread().name)
        if threading.current_thread().name == BYSTANDER:
            seen.set()
        REAL_SLEEP(seconds)  # keep every thread that lands here from spinning

    with _Bystander():
        monkeypatch.setattr(target.time, "sleep", recorder)
        try:
            reached = seen.wait(5)
        finally:
            monkeypatch.undo()

    assert reached and BYSTANDER in callers


def test_module_sleep_fakes_only_the_module_it_is_given(module_sleep):
    target = _module_using_time()
    callers = []

    with _Bystander() as bystander:
        module_sleep(target, lambda seconds: callers.append(threading.current_thread().name))
        before = bystander.loops
        target.wait(30)
        time.sleep(0.3)  # the real sleep: the fixture left the shared module alone
        spun = bystander.loops - before

    assert callers == [threading.current_thread().name]
    assert time.sleep is REAL_SLEEP
    assert spun < 50, f"the bystander looped {spun} times in 0.3s, so its sleep was faked"
    assert target.time.monotonic is time.monotonic


def test_module_sleep_refuses_a_module_that_does_not_import_time(module_sleep):
    target = _module_using_time("from time import sleep\n")
    with pytest.raises(AssertionError, match="does not reach sleep"):
        module_sleep(target, lambda seconds: None)
