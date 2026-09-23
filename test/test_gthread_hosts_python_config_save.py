"""The /python config file survives concurrent saves (hosts-01).

Every caller of ``save_configs`` wrote one shared ``strategy_configs.json.tmp``
and ``json.dump`` walked the live dict. Under the gthread worker two savers
interleave: one truncates and writes the temp file while the other renames it
into place, so the published JSON can carry the tail of the other payload (the
next start then reads no strategies at all), and a create or delete landing
mid-dump raises "dictionary changed size during iteration", which was
swallowed, so the change being saved never reached disk.

The first test runs sixteen savers against two threads creating and deleting
strategies and checks every file ever published parses and the last one equals
memory. On the old code it logs RuntimeError or FileNotFoundError and the file
can fail to parse. The second forces two saves to reach the file in the wrong
order and checks the newer state is the one left on disk.
"""

import json
import logging
import os
import threading

import pytest

from blueprints import python_strategy as ps


@pytest.fixture
def isolated_configs(tmp_path, monkeypatch):
    """Point the module at a temporary config file and an empty registry."""
    monkeypatch.setattr(ps, "CONFIG_FILE", tmp_path / "strategy_configs.json")
    saved = dict(ps.STRATEGY_CONFIGS)
    ps.STRATEGY_CONFIGS.clear()
    monkeypatch.setattr(ps, "_CONFIG_GENERATION", 0, raising=False)
    monkeypatch.setattr(ps, "_PERSISTED_GENERATION", 0, raising=False)
    yield tmp_path
    ps.STRATEGY_CONFIGS.clear()
    ps.STRATEGY_CONFIGS.update(saved)


def _config(sid):
    return {"name": sid, "file_path": f"strategies/scripts/{sid}.py", "exchange": "NSE"}


def test_concurrent_saves_always_publish_valid_json(isolated_configs, caplog):
    config_file = ps.CONFIG_FILE
    errors = []
    published = []
    stop = threading.Event()
    barrier = threading.Barrier(19)

    def saver():
        barrier.wait()
        for _ in range(50):
            if ps.save_configs() is False:
                errors.append("save reported failure")

    def mutator(prefix):
        barrier.wait()
        for i in range(200):
            sid = f"{prefix}_{i}"
            with ps.PROCESS_LOCK:
                ps.STRATEGY_CONFIGS[sid] = _config(sid)
            with ps.PROCESS_LOCK:
                if i % 2:
                    ps.STRATEGY_CONFIGS.pop(sid, None)

    def reader():
        barrier.wait()
        if os.name == "nt":
            # Windows refuses to rename over a file another thread has open,
            # so a reader here would fail the saves it is meant to observe.
            return
        while not stop.is_set():
            try:
                text = config_file.read_text(encoding="utf-8")
            except (FileNotFoundError, PermissionError):
                continue
            try:
                published.append(json.loads(text))
            except ValueError as exc:
                errors.append(f"published file did not parse: {exc}")

    with caplog.at_level(logging.ERROR):
        threads = [threading.Thread(target=saver) for _ in range(16)]
        threads += [threading.Thread(target=mutator, args=(p,)) for p in ("a", "b")]
        read_thread = threading.Thread(target=reader)
        for t in threads + [read_thread]:
            t.start()
        for t in threads:
            t.join(60)
        stop.set()
        read_thread.join(10)

    assert not errors, errors[:5]
    assert not [r for r in caplog.records if "Failed to save configs" in r.getMessage()]
    # A final save makes disk equal memory, whatever order the others landed in.
    assert ps.save_configs() is True
    assert json.loads(config_file.read_text(encoding="utf-8")) == ps.STRATEGY_CONFIGS
    leftovers = [p.name for p in config_file.parent.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == [], leftovers
    if os.name != "nt":
        assert published, "the reader never saw a published file"


def test_an_older_snapshot_never_overwrites_a_newer_one(isolated_configs, monkeypatch):
    """Two saves serialised as 1 then 2 may reach the file as 2 then 1."""
    config_file = ps.CONFIG_FILE
    real_replace = os.replace
    first_serialised = threading.Event()
    second_written = threading.Event()
    calls = []

    ps.STRATEGY_CONFIGS["s"] = {"state": "old"}

    class GatedLock:
        """The file lock, holding the first saver back until the second has written."""

        def __init__(self):
            self.inner = threading.Lock()

        def __enter__(self):
            if threading.current_thread().name == "first":
                first_serialised.set()
                second_written.wait(5)
            self.inner.acquire()
            return self

        def __exit__(self, *exc):
            self.inner.release()

    def tracking_replace(src, dst):
        calls.append(threading.current_thread().name)
        real_replace(src, dst)
        if threading.current_thread().name == "second":
            second_written.set()

    monkeypatch.setattr(ps, "_CONFIG_FILE_LOCK", GatedLock())
    monkeypatch.setattr(ps.os, "replace", tracking_replace)

    def first():
        ps.save_configs()

    def second():
        first_serialised.wait(5)
        with ps.PROCESS_LOCK:
            ps.STRATEGY_CONFIGS["s"] = {"state": "new"}
        ps.save_configs()

    # The first saver has serialised the old state and released PROCESS_LOCK;
    # the second changes the dict and writes before the first reaches the file.
    # That is the window the generation check closes.
    t1 = threading.Thread(target=first, name="first")
    t2 = threading.Thread(target=second, name="second")
    t1.start()
    t2.start()
    t1.join(10)
    t2.join(10)

    assert json.loads(config_file.read_text(encoding="utf-8")) == {"s": {"state": "new"}}
    assert calls == ["second"], f"the stale snapshot was written: {calls}"
