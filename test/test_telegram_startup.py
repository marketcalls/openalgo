"""Exercise the eventlet Telegram startup path without patching pytest itself."""

import subprocess
import sys
from pathlib import Path


def test_bot_starts_and_stops_cleanly_in_eventlet_env():
    child = Path(__file__).with_name("telegram_startup_eventlet_child.py")
    result = subprocess.run(
        [sys.executable, str(child)],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
