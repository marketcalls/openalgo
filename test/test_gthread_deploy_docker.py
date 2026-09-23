"""Docker: today's eventlet start is untouched, and gthread starts only when asked.

``start.sh`` is the image's entrypoint. The default path must stay the exact
eventlet command every Docker install runs today. Only when .env (or the
container environment) asks for gthread does it start through the launcher,
with a 30 second graceful window that the documented stop_grace_period
covers (Docker's default 10 second stop would not). Every
script it runs must lose Windows line endings in the image, because an image
built from a Windows checkout would otherwise not start.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
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

GUIDE = ROOT / "docs" / "gthread" / "README.md"


def _start_text() -> str:
    return START.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_the_default_start_is_todays_eventlet_command():
    assert _start_text().endswith(EVENTLET_START)


def test_the_gthread_branch_needs_an_explicit_request():
    text = _start_text()
    assert '--print requested)"' in text
    assert '[ "$OPENALGO_WORKER_REQUESTED" = "gthread" ]' in text
    assert "--worker-class eventlet" not in text.split(EVENTLET_START)[0]


def test_the_gthread_stop_fits_the_grace_period_the_guide_requires():
    text = _start_text()
    launcher = text[text.index("/bin/bash /app/install/openalgo-gunicorn.sh") :]
    launcher = launcher[: launcher.index(" &\n")]
    graceful = int(re.search(r"--graceful-timeout (\d+)", launcher).group(1))
    required = re.search(r"stop_grace_period: (\d+)s", GUIDE.read_text(encoding="utf-8"))
    assert required, "docs/gthread/README.md must tell Docker users which stop_grace_period to set"
    # The worker's window plus time for the arbiter and the proxy to exit.
    assert graceful + 10 <= int(required.group(1))
    # start.sh gives the proxy 5 seconds (ten half second looks) after the web
    # server has gone, inside those 10.
    supervisor = text[text.index("GUNICORN_PID=$!") : text.index(EVENTLET_START)]
    assert "for _ in 1 2 3 4 5 6 7 8 9 10; do" in supervisor
    assert "gthread_pause 0.5" in supervisor
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
    # The last assignment: the first one is inside the Railway .env generator.
    tail = re.sub(
        r"/app(?=[/\s\"']|$)",
        lambda _match: str(app),
        text[text.rindex('APP_PORT="${PORT:-5000}"') :],
        flags=re.M,
    )
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
        assert "--graceful-timeout 30" in line
        assert "-c " in line and "gunicorn_hooks.py" in line


# ---------------------------------------------------------------------------
# Docker gthread: start.sh looks after the WebSocket proxy
# ---------------------------------------------------------------------------
#
# With --proxy-mode external the web server never starts a proxy, so start.sh
# keeps the one it started alive: it is started again after a pause if it
# dies, never while the previous one is still running, and stopped with the
# container. Driven here with a fake /app: a proxy and a gunicorn that only
# record what happens to them.

FAKE_PYTHON = r"""#!/bin/bash
if [ "$1" = "-m" ] && [ "$2" = "websocket_proxy.server" ]; then
  # Never two at once: every proxy started before this one must be gone.
  if [ -f "$STATE/proxy_starts" ]; then
    while read -r earlier; do
      if kill -0 "$earlier" 2>/dev/null; then echo "$earlier" >> "$STATE/two_proxies"; fi
    done < "$STATE/proxy_starts"
  fi
  echo "$$" >> "$STATE/proxy_starts"
  trap 'echo "$$" >> "$STATE/proxy_stopped"; exit 0' TERM
  while :; do sleep 0.05; done
fi
exec "__PYTHON__" "$@"
"""

FAKE_GUNICORN = r"""#!/bin/bash
echo "$$" > "$STATE/gunicorn_pid"
trap 'echo TERM >> "$STATE/gunicorn_signals"; exit 0' TERM
while :; do sleep 0.05; done
"""


def _wait_until(check, seconds=10.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.05)
    return False


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _lines(path: Path) -> list[str]:
    return path.read_text().split() if path.exists() else []


@pytest.fixture
def docker_box(tmp_path):
    if sys.platform == "win32" or shutil.which("bash") is None:
        pytest.skip("runs start.sh with bash")
    app = tmp_path / "app"
    (app / "install" / "lib").mkdir(parents=True)
    for rel in (
        "install/openalgo-gunicorn.sh",
        "install/lib/resolve_runtime.py",
        "install/lib/gunicorn_hooks.py",
    ):
        shutil.copy2(ROOT / rel, app / rel)
    (app / "app.py").write_text("")
    (app / ".env").write_text("OPENALGO_WORKER_CLASS = 'gthread'\n")
    bin_dir = app / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python").write_text(FAKE_PYTHON.replace("__PYTHON__", sys.executable))
    (bin_dir / "gunicorn").write_text(FAKE_GUNICORN)
    for name in ("python", "gunicorn"):
        path = bin_dir / name
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    state = tmp_path / "state"
    state.mkdir()

    text = _start_text()
    start = text.rindex("# ====", 0, text.index("# WEBSOCKET PROXY SERVER"))
    tail = re.sub(
        r"/app(?=[/\s\"']|$)",
        lambda _match: str(app),
        text[start:],
        flags=re.M,
    )
    program = f'ENV_FILE="{app}/.env"\ncd "{app}"\n{tail}'
    env = {k: v for k, v in os.environ.items() if not k.startswith("OPENALGO_")}
    env["STATE"] = str(state)
    log = tmp_path / "start.log"
    handle = open(log, "w")
    process = subprocess.Popen(
        ["bash", "-c", program],
        stdout=handle,
        stderr=subprocess.STDOUT,
        env=env,
        start_new_session=True,
    )
    box = type("DockerBox", (), {})()
    box.process, box.state, box.log = process, state, log
    yield box
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(10)
    handle.close()
    for pid in _lines(state / "proxy_starts") + _lines(state / "gunicorn_pid"):
        if _alive(int(pid)):
            os.kill(int(pid), signal.SIGKILL)


def _started(state: Path) -> bool:
    return bool(_lines(state / "proxy_starts")) and bool(_lines(state / "gunicorn_pid"))


def test_a_proxy_that_dies_is_started_again_and_never_twice(docker_box):
    state = docker_box.state
    assert _wait_until(lambda: _started(state))
    first = int(_lines(state / "proxy_starts")[0])

    os.kill(first, signal.SIGKILL)

    assert _wait_until(lambda: len(_lines(state / "proxy_starts")) == 2), docker_box.log.read_text()
    second = int(_lines(state / "proxy_starts")[1])
    assert second != first and _alive(second)
    assert not (state / "two_proxies").exists(), "a proxy started while another was running"
    said = docker_box.log.read_text()
    assert "The WebSocket proxy server stopped" in said
    assert "starting it again in 1 seconds" in said

    # A second quick failure waits longer.
    os.kill(second, signal.SIGKILL)
    assert _wait_until(lambda: "starting it again in 2 seconds" in docker_box.log.read_text())
    assert _wait_until(lambda: len(_lines(state / "proxy_starts")) == 3)
    assert not (state / "two_proxies").exists()


def test_a_stop_ends_the_web_server_first_then_the_proxy(docker_box):
    state = docker_box.state
    assert _wait_until(lambda: _started(state))
    proxy = int(_lines(state / "proxy_starts")[0])
    gunicorn = int(_lines(state / "gunicorn_pid")[0])

    docker_box.process.send_signal(signal.SIGTERM)
    code = docker_box.process.wait(20)

    assert code == 0
    assert _lines(state / "gunicorn_signals") == ["TERM"]
    assert _lines(state / "proxy_stopped") == [str(proxy)]
    assert not _alive(proxy) and not _alive(gunicorn)
    assert len(_lines(state / "proxy_starts")) == 1, "a proxy was started during the stop"


def test_a_web_server_that_exits_takes_the_proxy_with_it(docker_box):
    state = docker_box.state
    assert _wait_until(lambda: _started(state))
    proxy = int(_lines(state / "proxy_starts")[0])
    gunicorn = int(_lines(state / "gunicorn_pid")[0])

    os.kill(gunicorn, signal.SIGKILL)
    code = docker_box.process.wait(20)

    assert code == 128 + signal.SIGKILL
    assert _lines(state / "proxy_stopped") == [str(proxy)]
    assert not _alive(proxy)
