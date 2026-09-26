"""Two admin saves at once must both reach .env.

``blueprints.admin._set_env_value`` reads .env, changes one key and writes the
whole file back. Two saves racing through that (two tabs or two devices
saving the Remote MCP settings) each wrote back a copy without the other's
key, so one setting was silently reverted: for example
``MCP_OAUTH_REQUIRE_APPROVAL`` quietly returning to False. The eventlet worker
serialised the sequence by accident (plain file I/O never yields there); real
request threads do not.

The race is forced, not hoped for: each save's read waits at a barrier for the
other save to read too. Without the lock both pass the barrier holding the
same original text and one key is lost. With it the second save cannot start
reading until the first has written, the barrier times out for the first,
and both keys survive.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from blueprints import admin


class _BarrierPath(type(Path())):
    """A Path whose read_text waits for a second reader before returning."""

    barrier: threading.Barrier | None = None

    def read_text(self, *args, **kwargs):
        text = super().read_text(*args, **kwargs)
        barrier = type(self).barrier
        if barrier is not None:
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                pass
        return text


@pytest.fixture
def env_file(tmp_path):
    path = tmp_path / ".env"
    path.write_text("APP_KEY = 'x'\nMCP_HTTP_ENABLED = 'False'\n", encoding="utf-8")
    return path


def _save_both(env_file: Path) -> str:
    _BarrierPath.barrier = threading.Barrier(2, timeout=0.5)
    target = _BarrierPath(env_file)
    errors: list[BaseException] = []

    def save(key: str) -> None:
        try:
            admin._set_env_value(target, key, "True")
        except BaseException as error:  # surfaced below
            errors.append(error)

    threads = [
        threading.Thread(target=save, args=("MCP_OAUTH_REQUIRE_APPROVAL",)),
        threading.Thread(target=save, args=("MCP_OAUTH_WRITE_SCOPE_ENABLED",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    _BarrierPath.barrier = None
    assert not errors, errors
    return env_file.read_text(encoding="utf-8")


def test_two_concurrent_saves_both_land(env_file):
    text = _save_both(env_file)
    assert "MCP_OAUTH_REQUIRE_APPROVAL = 'True'" in text, text
    assert "MCP_OAUTH_WRITE_SCOPE_ENABLED = 'True'" in text, text
    assert "APP_KEY = 'x'" in text


def test_the_barrier_really_forces_the_race_without_the_lock(env_file, monkeypatch):
    """The control: with the lock removed, the same sequence loses a key.

    Without this the test above could pass because the two threads happened
    not to overlap, and would prove nothing.
    """

    class _NoLock:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(admin, "ENV_WRITE_LOCK", _NoLock())
    text = _save_both(env_file)
    both = (
        "MCP_OAUTH_REQUIRE_APPROVAL = 'True'" in text
        and "MCP_OAUTH_WRITE_SCOPE_ENABLED = 'True'" in text
    )
    assert not both, "the barrier did not make the two saves overlap"


def test_the_writer_uses_the_shared_env_lock():
    """Every .env writer in the process takes one lock, not one each."""
    from utils import env_check

    assert admin.ENV_WRITE_LOCK is env_check.ENV_WRITE_LOCK


def test_a_single_save_is_unchanged(env_file):
    """The quiet path: one save replaces the first assignment and keeps the rest."""
    env_file.write_text("A = '1'\nMCP_HTTP_ENABLED = 'False'\nB = '2'\n", encoding="utf-8")
    admin._set_env_value(env_file, "MCP_HTTP_ENABLED", "True")
    admin._set_env_value(env_file, "MCP_PUBLIC_URL", "https://example.com")
    assert env_file.read_text(encoding="utf-8") == (
        "A = '1'\nMCP_HTTP_ENABLED = 'True'\nB = '2'\nMCP_PUBLIC_URL = 'https://example.com'\n"
    )
