"""A forked child must not inherit a handler lock another thread was holding.

utils/logging.py gives every handler a real lock (so real OS threads can log
under eventlet). CPython's own createLock also registers the lock to be
re-initialised in a forked child; the replacement used to skip that. Under the
gthread worker many threads log at once, so a fork (``subprocess`` with
``preexec_fn`` forks) can land while one of them holds a handler lock, and the
child then deadlocks on its first log line, holding up the parent's Popen.

POSIX only, and each case runs in its own interpreter so pytest's own threads
are never forked. The first test shows the hang without the registration, so
the second cannot pass vacuously.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(not hasattr(os, "fork"), reason="fork is POSIX only")

SCRIPT = """
import logging, os, sys, threading, time
{setup}
import utils.logging  # installs the real-lock createLock

handler = logging.StreamHandler(sys.stderr)
log = logging.getLogger("fork-probe")
log.addHandler(handler)
log.propagate = False

held, release = threading.Event(), threading.Event()

def holder():
    with handler.lock:
        held.set()
        release.wait(10)

threading.Thread(target=holder, daemon=True).start()
assert held.wait(5)

pid = os.fork()
if pid == 0:
    log.warning("child logged")
    os._exit(0)

deadline = time.monotonic() + 3
status = None
while time.monotonic() < deadline:
    done, status = os.waitpid(pid, os.WNOHANG)
    if done:
        break
    time.sleep(0.02)
else:
    os.kill(pid, 9)
    os.waitpid(pid, 0)
    release.set()
    print("CHILD HUNG")
    sys.exit(0)
release.set()
print("CHILD EXITED", os.waitstatus_to_exitcode(status))
"""


def _run(setup: str = "") -> str:
    env = dict(os.environ)
    env.update({"PYTHONPATH": str(REPO), "LOG_TO_FILE": "False"})
    result = subprocess.run(
        [
            sys.executable,
            "-W",
            "ignore::DeprecationWarning",
            "-c",
            textwrap.dedent(SCRIPT.format(setup=setup)),
        ],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.stdout + result.stderr


def test_without_the_registration_the_child_deadlocks():
    """The defect: a real lock nobody re-initialises is still held in the child."""
    out = _run(setup="logging._register_at_fork_reinit_lock = lambda instance: None")
    assert "CHILD HUNG" in out, out


def test_the_real_lock_is_reinitialised_in_a_forked_child():
    out = _run()
    assert "CHILD EXITED 0" in out, out
