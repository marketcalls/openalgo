"""The first LiteLLM import must survive two requests making it at once.

Opening /agent/config sends the catalogue, the ChatGPT plan status and the
model list together. Before ``services/agent/litellm_loader.py`` the catalogue
ran ``import litellm`` while the plan status ran
``from litellm.llms.chatgpt.authenticator import ...``; Python's import system
deadlocked the two, one raised ``_DeadlockError``, the other
``KeyError: 'litellm'``, and the half-built package left behind had no
``exceptions`` attribute, so every model test failed until a restart.

Each case runs in a fresh interpreter: the suite has usually imported LiteLLM
already, and only a first import can race. The eventlet case runs there too,
because ``monkey_patch()`` is global and cannot be undone.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("litellm")

REPO = Path(__file__).resolve().parent.parent

_RACE = textwrap.dedent(
    """
    import sys
    sys.path.insert(0, {repo!r})
    {prelude}
    import threading

    from services.agent import catalog, chatgpt_oauth

    import time

    errors = []

    def catalogue():
        if catalog._litellm() is None:
            errors.append("catalogue could not import litellm")

    def plan_status():
        # Stage the race where it lives: the package body is running in the
        # other thread (it is in sys.modules, not finished), and this thread
        # now imports a submodule, taking litellm.llms on its way to litellm.
        deadline = time.monotonic() + 60
        while "litellm" not in sys.modules and time.monotonic() < deadline:
            time.sleep(0.001)
        try:
            chatgpt_oauth._bits()
        except Exception as exc:
            errors.append("chatgpt provider: %r" % (exc,))

    threads = [threading.Thread(target=catalogue), threading.Thread(target=plan_status)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    import litellm
    if not hasattr(litellm, "exceptions"):
        errors.append("litellm left half-built: no exceptions attribute")
    print("ERRORS:", errors)
    sys.exit(1 if errors else 0)
    """
)


def _run(prelude: str) -> subprocess.CompletedProcess[str]:
    script = _RACE.format(repo=str(REPO), prelude=prelude)
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )


def test_concurrent_first_import_on_real_threads():
    result = _run("")
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]


def test_concurrent_first_import_on_green_threads():
    pytest.importorskip("eventlet")
    result = _run("import eventlet\neventlet.monkey_patch()")
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
