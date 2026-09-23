"""Docker: today's eventlet start is untouched, and gthread starts only when asked.

``start.sh`` is the image's entrypoint. The default path must stay the exact
eventlet command every Docker install runs today. Only when .env (or the
container environment) asks for gthread does it start through the launcher,
with a graceful window that fits Docker's default 10 second stop. Every
script it runs must lose Windows line endings in the image, because an image
built from a Windows checkout would otherwise not start.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
START = ROOT / "start.sh"
DOCKERFILE = ROOT / "Dockerfile"

#: The eventlet start as it was before gthread existed, byte for byte.
EVENTLET_START = """echo "[OpenAlgo] Starting application on port ${APP_PORT} with eventlet..."

# Create gunicorn worker temp directory (must be inside container, not mounted volume)
mkdir -p /tmp/gunicorn_workers

exec /app/.venv/bin/gunicorn \\
    --worker-class eventlet \\
    --workers 1 \\
    --bind 0.0.0.0:${APP_PORT} \\
    --timeout 300 \\
    --graceful-timeout 30 \\
    --worker-tmp-dir /tmp/gunicorn_workers \\
    --no-control-socket \\
    --log-level warning \\
    app:app
"""

DOCKER_STOP_SECONDS = 10


def _start_text() -> str:
    return START.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_the_default_start_is_todays_eventlet_command():
    assert _start_text().endswith(EVENTLET_START)


def test_the_gthread_branch_needs_an_explicit_request():
    text = _start_text()
    assert '--print requested)"' in text
    assert '[ "$OPENALGO_WORKER_REQUESTED" = "gthread" ]' in text
    assert "--worker-class eventlet" not in text.split(EVENTLET_START)[0]


def test_the_gthread_stop_fits_dockers_default_window():
    text = _start_text()
    launcher = text[text.index("exec /bin/bash /app/install/openalgo-gunicorn.sh") :]
    launcher = launcher[: launcher.index("\nfi\n")]
    graceful = int(re.search(r"--graceful-timeout (\d+)", launcher).group(1))
    assert graceful + 2 <= DOCKER_STOP_SECONDS
    assert "--proxy-mode external" in launcher
    assert '--env-file "$ENV_FILE"' in launcher


def test_every_script_start_sh_runs_loses_carriage_returns_in_the_image():
    used = set(re.findall(r"/app/install/[\w./-]+", _start_text()))
    # The launcher itself reads its two helpers.
    used |= {"/app/install/lib/resolve_runtime.py", "/app/install/lib/gunicorn_hooks.py"}
    joined = DOCKERFILE.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\\\n", " ")
    sed_lines = [line for line in joined.splitlines() if "sed -i 's/\\r$//'" in line]
    assert sed_lines, "the Dockerfile no longer strips carriage returns"
    for path in sorted(used):
        assert any(path in line for line in sed_lines), f"{path} keeps its CR in the image"


def test_the_resolver_line_reads_a_windows_env(tmp_path):
    resolver = ROOT / "install" / "lib" / "resolve_runtime.py"

    def requested(content: bytes) -> str:
        env_file = tmp_path / ".env"
        env_file.write_bytes(content)
        result = subprocess.run(
            [sys.executable, str(resolver), "--env-file", str(env_file), "--print", "requested"],
            capture_output=True,
            text=True,
            timeout=60,
            env={k: v for k, v in os.environ.items() if k != "OPENALGO_WORKER_CLASS"},
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    assert requested(b"APP_KEY = 'x'\r\n") == "default"
    assert requested(b"OPENALGO_WORKER_CLASS = 'gthread'\r\n") == "gthread"
    assert requested(b"OPENALGO_WORKER_CLASS = 'eventlet'\r\n") == "eventlet"


@pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None, reason="runs start.sh with bash"
)
@pytest.mark.parametrize(
    "env_text,expected",
    [
        ("APP_KEY = 'x'\r\n", "eventlet-direct"),
        ("OPENALGO_WORKER_CLASS = 'eventlet'\r\n", "eventlet-direct"),
        ("OPENALGO_WORKER_CLASS = 'gthread'\r\n", "gthread-launcher"),
    ],
)
def test_start_sh_picks_the_web_server_from_env(tmp_path, env_text, expected):
    """Run start.sh's final section against a fake /app, with gunicorn stubbed."""
    app = tmp_path / "app"
    (app / "install" / "lib").mkdir(parents=True)
    for rel in (
        "install/openalgo-gunicorn.sh",
        "install/lib/resolve_runtime.py",
        "install/lib/gunicorn_hooks.py",
    ):
        shutil.copy2(ROOT / rel, app / rel)
    (app / "app.py").write_text("")
    (app / ".env").write_bytes(env_text.encode())
    bin_dir = app / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python").write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    (bin_dir / "gunicorn").write_text('#!/bin/sh\necho "GUNICORN $*"\n')
    for name in ("python", "gunicorn"):
        path = bin_dir / name
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    text = _start_text()
    tail = text[text.index('APP_PORT="${PORT:-5000}"') :].replace("/app/", f"{app}/")
    program = f'ENV_FILE="{app}/.env"\n{tail}'
    env = {k: v for k, v in os.environ.items() if not k.startswith("OPENALGO_")}
    result = subprocess.run(
        ["bash", "-c", program], capture_output=True, text=True, timeout=60, env=env
    )
    assert result.returncode == 0, result.stderr
    line = next(line for line in result.stdout.splitlines() if line.startswith("GUNICORN "))
    if expected == "eventlet-direct":
        assert "with eventlet..." in result.stdout
        assert line == (
            "GUNICORN --worker-class eventlet --workers 1 --bind 0.0.0.0:5000 --timeout 300 "
            "--graceful-timeout 30 --worker-tmp-dir /tmp/gunicorn_workers --no-control-socket "
            "--log-level warning app:app"
        )
    else:
        assert "with gthread..." in result.stdout
        assert "--worker-class gthread --threads 64 --workers 1 --bind 0.0.0.0:5000" in line
        assert "--graceful-timeout 7" in line
        assert "-c " in line and "gunicorn_hooks.py" in line
