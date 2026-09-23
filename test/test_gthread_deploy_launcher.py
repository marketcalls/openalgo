"""The launcher starts the web server .env names, with the options OpenAlgo needs.

``install/openalgo-gunicorn.sh`` reads ``OPENALGO_WORKER_CLASS`` at every start
through ``install/lib/resolve_runtime.py``, which uses python-dotenv, the
app's own parser, so the launcher and the app can never disagree about what
the file says. The resolver is tested directly everywhere; the launcher
itself is a bash script for Linux servers and is run with ``--dry-run`` on
Linux only.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "install" / "openalgo-gunicorn.sh"
RESOLVER = ROOT / "install" / "lib" / "resolve_runtime.py"

linux_only = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="the launcher is a bash script for Linux servers",
)


def _load_resolver():
    spec = importlib.util.spec_from_file_location("resolve_runtime_under_test", RESOLVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


resolver = _load_resolver()

#: (.env content, expected effective worker) pairs, CRLF and all.
ENV_CASES = [
    ("", "eventlet"),
    ("APP_KEY = 'x'\n", "eventlet"),
    ("OPENALGO_WORKER_CLASS = 'gthread'\n", "gthread"),
    ("OPENALGO_WORKER_CLASS = 'eventlet'\n", "eventlet"),
    ("OPENALGO_WORKER_CLASS = 'gthread'\r\nOPENALGO_WORKER_CLASS = 'eventlet'\r\n", "eventlet"),
    ("OPENALGO_WORKER_CLASS = 'eventlet'\nOPENALGO_WORKER_CLASS=gthread\n", "gthread"),
    ('export OPENALGO_WORKER_CLASS="GThread"  # switched after hours\n', "gthread"),
    ("OPENALGO_WORKER_CLASS=gthread # comment\r\n", "gthread"),
    ("# OPENALGO_WORKER_CLASS = 'gthread'\n", "eventlet"),
    ("OPENALGO_WORKER_CLASS = ''\n", "eventlet"),
    ("OPENALGO_WORKER_CLASS = 'eventlt'\n", "eventlet"),
]


def _write(path: Path, text: str) -> Path:
    path.write_bytes(text.encode("utf-8"))
    return path


# --------------------------------------------------------------- resolver


@pytest.mark.parametrize("content,expected", ENV_CASES)
def test_the_resolver_reads_env_like_the_app(tmp_path, content, expected):
    env_file = _write(tmp_path / ".env", content)
    raw = resolver.read_requested(str(env_file), environ={})
    effective, _requested, _warnings = resolver.resolve(raw, eventlet_available=True)
    assert effective == expected


@pytest.mark.parametrize("content,_expected", ENV_CASES)
def test_the_resolver_agrees_with_python_dotenv(tmp_path, content, _expected):
    """Parity: the raw value is exactly what dotenv_values (the app's parser) returns."""
    from dotenv import dotenv_values

    env_file = _write(tmp_path / ".env", content)
    assert resolver.read_requested(str(env_file), environ={}) == dotenv_values(env_file).get(
        resolver.KEY
    )


@pytest.mark.parametrize("content,_expected", ENV_CASES)
def test_the_fallback_parser_agrees_with_python_dotenv(tmp_path, content, _expected):
    """The parser used when python-dotenv is missing reaches the same answer."""
    from dotenv import dotenv_values

    env_file = _write(tmp_path / ".env", content)
    expected = dotenv_values(env_file).get(resolver.KEY)
    fallback = resolver._fallback_value(str(env_file))
    assert (fallback or "").strip().lower() == (expected or "").strip().lower()


def test_the_process_environment_is_used_only_when_env_is_silent(tmp_path):
    env_file = _write(tmp_path / ".env", "APP_KEY = 'x'\n")
    assert resolver.read_requested(str(env_file), {"OPENALGO_WORKER_CLASS": "gthread"}) == "gthread"
    env_file = _write(tmp_path / ".env", "OPENALGO_WORKER_CLASS = 'eventlet'\n")
    assert (
        resolver.read_requested(str(env_file), {"OPENALGO_WORKER_CLASS": "gthread"}) == "eventlet"
    )
    assert resolver.read_requested(str(tmp_path / "missing"), {}) is None


def test_an_unknown_value_is_reported_and_the_default_used():
    effective, requested, warnings = resolver.resolve("eventlt", eventlet_available=True)
    assert effective == "eventlet"
    assert requested == "eventlt"
    assert len(warnings) == 1 and "'eventlt'" in warnings[0]


def test_eventlet_missing_falls_back_to_gthread_with_a_reason():
    effective, _requested, warnings = resolver.resolve(None, eventlet_available=False)
    assert effective == "gthread"
    assert warnings and "not installed" in warnings[0]


def test_nothing_is_said_when_the_setting_is_absent_or_valid():
    for raw in (None, "", "eventlet", "gthread", " GTHREAD "):
        assert resolver.resolve(raw, eventlet_available=True)[2] == []


def test_set_rewrites_every_assignment_and_keeps_line_endings(tmp_path):
    env_file = _write(
        tmp_path / ".env",
        "A = '1'\r\nOPENALGO_WORKER_CLASS = 'eventlet'\r\n# OPENALGO_WORKER_CLASS = 'x'\r\n"
        "export OPENALGO_WORKER_CLASS=eventlet\r\n",
    )
    resolver.set_requested(str(env_file), "gthread")
    assert env_file.read_bytes() == (
        b"A = '1'\r\nOPENALGO_WORKER_CLASS = 'gthread'\r\n# OPENALGO_WORKER_CLASS = 'x'\r\n"
        b"OPENALGO_WORKER_CLASS = 'gthread'\r\n"
    )
    other = _write(tmp_path / "other.env", "A = '1'")
    resolver.set_requested(str(other), "eventlet")
    assert other.read_text() == "A = '1'\nOPENALGO_WORKER_CLASS = 'eventlet'\n"
    with pytest.raises(ValueError):
        resolver.set_requested(str(other), "gevent")


def test_the_shell_output_is_safe_to_read_without_evaluation(tmp_path):
    env_file = _write(tmp_path / ".env", "OPENALGO_WORKER_CLASS = 'x;rm -rf $HOME`'\n")
    result = subprocess.run(
        [sys.executable, str(RESOLVER), "--env-file", str(env_file), "--shell"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0
    for line in result.stdout.splitlines():
        key, _, value = line.partition("=")
        assert key.isupper()
        assert all(ch.isalnum() or ch in "._-" for ch in value), line
    # eventlet, or gthread where eventlet is not installed (a Windows dev box).
    assert any(
        line in ("WORKER_CLASS=eventlet", "WORKER_CLASS=gthread")
        for line in result.stdout.splitlines()
    )
    assert "does not recognise" in result.stderr


def test_print_requested_names_what_the_operator_asked_for(tmp_path):
    def run(content):
        env_file = _write(tmp_path / ".env", content)
        return subprocess.run(
            [sys.executable, str(RESOLVER), "--env-file", str(env_file), "--print", "requested"],
            capture_output=True,
            text=True,
            timeout=60,
        )

    assert run("").stdout.strip() == "default"
    assert run("").stderr == ""
    assert run("OPENALGO_WORKER_CLASS = 'gthread'\r\n").stdout.strip() == "gthread"
    assert run("OPENALGO_WORKER_CLASS = 'eventlet'\n").stdout.strip() == "eventlet"


# --------------------------------------------------------------- launcher


def _fake_venv(root: Path) -> Path:
    """A venv whose python is the test interpreter and whose gunicorn is a stub."""
    venv = root / "venv"
    bin_dir = venv / "bin"
    bin_dir.mkdir(parents=True)
    python = bin_dir / "python"
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    gunicorn = bin_dir / "gunicorn"
    gunicorn.write_text("#!/bin/sh\nexit 0\n")
    for path in (python, gunicorn):
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return venv


def _fake_app(root: Path, env_text: str) -> Path:
    app = root / "app"
    (app / "install" / "lib").mkdir(parents=True)
    shutil.copy2(LAUNCHER, app / "install" / LAUNCHER.name)
    for helper in ("resolve_runtime.py", "gunicorn_hooks.py"):
        shutil.copy2(ROOT / "install" / "lib" / helper, app / "install" / "lib" / helper)
    (app / "app.py").write_text("")
    _write(app / ".env", env_text)
    return app


def _dry_run(tmp_path, env_text="", extra_env=None, *args):
    app = _fake_app(tmp_path, env_text)
    venv = _fake_venv(tmp_path)
    env = {k: v for k, v in os.environ.items() if not k.startswith("OPENALGO_")}
    env.pop("GUNICORN_CMD_ARGS", None)
    env.update(extra_env or {})
    result = subprocess.run(
        [
            "bash",
            str(app / "install" / LAUNCHER.name),
            "--venv",
            str(venv),
            "--bind",
            "unix:/tmp/openalgo-test.sock",
            "--dry-run",
            *args,
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    argv = [line[4:] for line in result.stdout.splitlines() if line.startswith("ARG ")]
    exported = dict(
        line[4:].split("=", 1) for line in result.stdout.splitlines() if line.startswith("ENV ")
    )
    return argv, exported, result.stderr, app


def _option(argv, name):
    return argv[argv.index(name) + 1] if name in argv else None


@linux_only
def test_nothing_set_starts_eventlet_with_todays_flags(tmp_path):
    argv, exported, stderr, _app = _dry_run(tmp_path)
    assert _option(argv, "--worker-class") == "eventlet"
    assert "--threads" not in argv
    assert _option(argv, "--workers") == "1"
    assert _option(argv, "--bind") == "unix:/tmp/openalgo-test.sock"
    assert _option(argv, "--timeout") == "300"
    assert _option(argv, "--log-level") == "info"
    assert argv[-1] == "app:app"
    assert exported["OPENALGO_EFFECTIVE_WORKER_CLASS"] == "eventlet"
    assert "OPENALGO_EFFECTIVE_THREADS" not in exported
    assert "Traceback" not in stderr


@linux_only
def test_gthread_gets_the_fixed_thread_budget(tmp_path):
    argv, exported, stderr, _app = _dry_run(tmp_path, "OPENALGO_WORKER_CLASS = 'gthread'\r\n")
    assert _option(argv, "--worker-class") == "gthread"
    assert _option(argv, "--threads") == "64"
    assert _option(argv, "--workers") == "1"
    assert exported["OPENALGO_EFFECTIVE_THREADS"] == "64"
    assert exported["OPENALGO_REQUESTED_WORKER_CLASS"] == "gthread"
    assert "64 request threads" in stderr
    assert "OPENALGO_WORKER_CLASS = 'eventlet'" in stderr


@linux_only
def test_the_last_assignment_wins(tmp_path):
    argv, *_ = _dry_run(
        tmp_path, "OPENALGO_WORKER_CLASS = 'gthread'\nOPENALGO_WORKER_CLASS = 'eventlet'\n"
    )
    assert _option(argv, "--worker-class") == "eventlet"


@linux_only
def test_an_unknown_value_starts_eventlet_and_says_why(tmp_path):
    argv, exported, stderr, _app = _dry_run(tmp_path, "OPENALGO_WORKER_CLASS = 'eventlt'\n")
    assert _option(argv, "--worker-class") == "eventlet"
    assert exported["OPENALGO_REQUESTED_WORKER_CLASS"] == "eventlt"
    assert "'eventlt'" in stderr


@linux_only
def test_settings_from_outside_the_command_line_are_ignored(tmp_path):
    argv, _exported, stderr, _app = _dry_run(
        tmp_path,
        "OPENALGO_WORKER_CLASS = 'gthread'\n",
        {"GUNICORN_CMD_ARGS": "--preload --max-requests 10"},
    )
    assert "Ignoring GUNICORN_CMD_ARGS" in stderr
    for forbidden in ("--preload", "--max-requests", "--reload", "--access-logfile"):
        assert forbidden not in argv
    assert argv[0] == "-c"
    assert argv[1].endswith("install/lib/gunicorn_hooks.py")


@linux_only
def test_hardening_flags_are_always_passed(tmp_path):
    for index, env_text in enumerate(("", "OPENALGO_WORKER_CLASS = 'gthread'\n")):
        argv, exported, _stderr, _app = _dry_run(tmp_path / f"case{index}", env_text)
        assert int(_option(argv, "--keep-alive")) > 60  # longer than nginx's 60 s keepalive
        assert _option(argv, "--graceful-timeout") == "30"
        assert exported["WEBSOCKET_PROXY_MODE"] == "subprocess"
        assert exported["OPENALGO_LAUNCHER_VERSION"] == "1"


@linux_only
def test_docker_options_are_passed_through(tmp_path):
    argv, exported, _stderr, _app = _dry_run(
        tmp_path,
        "OPENALGO_WORKER_CLASS = 'gthread'\n",
        None,
        "--proxy-mode",
        "external",
        "--graceful-timeout",
        "7",
        "--worker-tmp-dir",
        "/tmp/gunicorn_workers",
        "--log-level",
        "warning",
    )
    assert exported["WEBSOCKET_PROXY_MODE"] == "external"
    assert _option(argv, "--graceful-timeout") == "7"
    assert _option(argv, "--worker-tmp-dir") == "/tmp/gunicorn_workers"
    assert _option(argv, "--log-level") == "warning"


@linux_only
def test_a_missing_gunicorn_is_refused_in_plain_words(tmp_path):
    app = _fake_app(tmp_path, "")
    venv = _fake_venv(tmp_path)
    (venv / "bin" / "gunicorn").unlink()
    result = subprocess.run(
        ["bash", str(app / "install" / LAUNCHER.name), "--venv", str(venv), "--bind", "x:1"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 2
    assert "gunicorn is not installed" in result.stderr


@linux_only
def test_the_shell_fallback_is_used_when_python_cannot_run(tmp_path):
    app = _fake_app(
        tmp_path, "OPENALGO_WORKER_CLASS = 'eventlet'\nOPENALGO_WORKER_CLASS=gthread\r\n"
    )
    venv = _fake_venv(tmp_path)
    (venv / "bin" / "python").write_text("#!/bin/sh\nexit 1\n")
    result = subprocess.run(
        [
            "bash",
            str(app / "install" / LAUNCHER.name),
            "--venv",
            str(venv),
            "--bind",
            "unix:/tmp/x.sock",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    argv = [line[4:] for line in result.stdout.splitlines() if line.startswith("ARG ")]
    assert _option(argv, "--worker-class") == "gthread"


def test_the_launcher_is_lf_and_never_moves():
    """Units reference this exact path forever, and bash cannot run CRLF."""
    assert LAUNCHER.is_file()
    assert b"\r\n" not in LAUNCHER.read_bytes() or sys.platform == "win32"
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "*.sh text eol=lf" in attributes
    assert "install/lib/*.py text eol=lf" in attributes
