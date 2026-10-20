"""The check-then-act and sleep gates catch what they claim, and the tree passes them.

Each rule is driven with a small synthetic module written to tmp_path, both
the shape it must flag and the shape it must leave alone. The last tests run
both gates over the real tree with their reviewed lists, which is what the
``gthread-gates`` CI job does.
"""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"{name}_under_test", ROOT / "scripts" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up while it loads
    spec.loader.exec_module(module)
    return module


cta = _load("gthread_check_then_act")
sleep_gate = _load("gthread_sleep_gate")


def _module(tmp_path: Path, name: str, source: str) -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    return path


def _run(gate, tmp_path, path, allowlist_lines=(), extra=()):
    allowlist = tmp_path / f"{path.stem}_reviewed.txt"
    allowlist.write_text("\n".join(allowlist_lines) + "\n", encoding="utf-8")
    return gate.main([str(path), "--allowlist", str(allowlist), *extra])


# ------------------------------------------------------------ check-then-act


def test_an_unlocked_lazy_global_is_flagged(tmp_path, capsys):
    path = _module(
        tmp_path,
        "lazy.py",
        """
        _client = None

        def get_client():
            global _client
            if _client is None:
                _client = object()
            return _client
        """,
    )
    assert _run(cta, tmp_path, path) == 1
    assert "lazy-global _client" in capsys.readouterr().out


def test_double_checked_locking_is_not_flagged(tmp_path):
    path = _module(
        tmp_path,
        "double.py",
        """
        import threading
        _client = None
        _lock = threading.Lock()

        def get_client():
            global _client
            if _client is None:
                with _lock:
                    if _client is None:
                        _client = object()
            return _client

        def get_client_locked():
            global _client
            with _lock:
                if _client is None:
                    _client = object()
            return _client
        """,
    )
    assert _run(cta, tmp_path, path) == 0


def test_a_module_dict_check_then_act_is_flagged(tmp_path, capsys):
    path = _module(
        tmp_path,
        "cache.py",
        """
        _cache = {}
        _seen = set()

        def load(key):
            if key not in _cache:
                _cache[key] = object()
            return _cache[key]

        def remember(key):
            if key not in _seen:
                _seen.add(key)
        """,
    )
    assert _run(cta, tmp_path, path) == 1
    out = capsys.readouterr().out
    assert "container _cache" in out and "container _seen" in out


def test_a_guarded_augmented_assignment_is_flagged_unless_locked(tmp_path, capsys):
    path = _module(
        tmp_path,
        "funds.py",
        """
        def debit(account, amount):
            if account.balance >= amount:
                account.balance -= amount

        def debit_spelled_out(account, amount):
            if account.balance >= amount:
                account.balance = account.balance - amount

        def debit_locked(account, amount, lock):
            with lock:
                if account.balance >= amount:
                    account.balance -= amount
        """,
    )
    assert _run(cta, tmp_path, path) == 1
    out = capsys.readouterr().out
    assert "debit  guard-augassign account.balance" in out
    assert "debit_spelled_out  guard-augassign account.balance" in out
    assert "debit_locked" not in out


def test_a_reviewed_site_passes_and_a_stale_entry_is_reported(tmp_path, capsys):
    path = _module(
        tmp_path,
        "lazy.py",
        """
        _client = None

        def get_client():
            global _client
            if _client is None:
                _client = object()
            return _client
        """,
    )
    key = f"{path.resolve().as_posix()}::get_client::_client"
    stale = f"{path.resolve().as_posix()}::gone::_client"
    lines = [f"{key}  # benign: test", f"{stale}  # benign: test"]
    assert _run(cta, tmp_path, path, lines) == 0
    out = capsys.readouterr().out
    assert "REVIEWED" in out and "STALE" in out
    assert _run(cta, tmp_path, path, lines, ["--strict"]) == 1


# ------------------------------------------------------------------ sleeps


def test_a_sleep_under_a_lock_is_flagged(tmp_path, capsys):
    path = _module(
        tmp_path,
        "held.py",
        """
        import time

        class Feed:
            def connect(self):
                with self._lock:
                    time.sleep(1)
        """,
    )
    assert _run(sleep_gate, tmp_path, path) == 1
    assert "under-lock" in capsys.readouterr().out


def test_eventlet_sleep_needs_an_eventlet_branch(tmp_path, capsys):
    path = _module(
        tmp_path,
        "green.py",
        """
        import eventlet
        from utils.runtime import is_monkey_patched

        def pause():
            eventlet.sleep(0)

        def pause_guarded():
            if is_monkey_patched():
                eventlet.sleep(0)
        """,
    )
    assert _run(sleep_gate, tmp_path, path) == 1
    out = capsys.readouterr().out
    assert "pause  eventlet-outside-branch" in out
    assert "pause_guarded" not in out


def test_long_and_endless_sleeps_are_flagged_until_reviewed(tmp_path, capsys):
    path = _module(
        tmp_path,
        "loops.py",
        """
        from time import sleep

        def cleanup():
            sleep(300)

        def poll():
            while True:
                sleep(0.25)

        def quick():
            sleep(0.1)
        """,
    )
    assert _run(sleep_gate, tmp_path, path) == 1
    out = capsys.readouterr().out
    assert "cleanup  long" in out and "poll  loop" in out and "quick" not in out
    display = path.resolve().as_posix()
    lines = [f"{display}::cleanup  # benign: test", f"{display}::poll  # benign: test"]
    assert _run(sleep_gate, tmp_path, path, lines) == 0


# ------------------------------------------------------------- the real tree


@pytest.mark.parametrize("gate", [cta, sleep_gate], ids=["check-then-act", "sleep"])
def test_the_tree_passes_the_gate(gate, capsys):
    status = gate.main([])
    out = capsys.readouterr().out
    assert status == 0, out[-4000:]
