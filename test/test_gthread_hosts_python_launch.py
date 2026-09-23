"""Strategies launch without running Python between fork and exec under gthread (hosts-06).

create_subprocess_args passed ``preexec_fn=set_resource_limits``. preexec_fn runs
in the child between fork and exec, and set_resource_limits logs when a limit
cannot be set. Logging takes locks, and under the gthread worker many request
threads hold them at any moment, so a child forked while one was mid log line
could hang before the strategy started, with the parent's Popen, and
PROCESS_LOCK with it, waiting on it.

Under gthread the limits are now applied by the child itself after exec, by a
small bootstrap that then runs the strategy file as ``__main__``. Under eventlet
and on the development server the launch is unchanged, and the first test pins
that.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from blueprints import python_strategy as ps

POSIX = os.name != "nt"


@pytest.fixture
def worker(monkeypatch):
    """Pretend to be the gthread worker, or not."""

    def choose(gthread: bool):
        monkeypatch.setattr(ps.runtime, "gthread_active", lambda: gthread)

    return choose


def test_eventlet_and_the_dev_server_launch_exactly_as_before(worker):
    worker(False)
    args = ps.create_subprocess_args()
    if POSIX:
        assert args["preexec_fn"] is ps.set_resource_limits
    else:
        assert "preexec_fn" not in args


def test_gthread_launches_without_preexec_fn(worker):
    worker(True)
    assert "preexec_fn" not in ps.create_subprocess_args()


@pytest.fixture
def captured_launch(monkeypatch, tmp_path):
    saved = dict(ps.STRATEGY_CONFIGS)
    running = dict(ps.RUNNING_STRATEGIES)
    ps.STRATEGY_CONFIGS.clear()
    ps.RUNNING_STRATEGIES.clear()
    script = tmp_path / "launch.py"
    script.write_text("print('x')\n", encoding="utf-8")
    ps.STRATEGY_CONFIGS["launch"] = {"name": "Launch", "file_path": str(script), "exchange": "NSE"}

    captured = {}

    class Recorder:
        def __init__(self, cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            self.pid = 2_000_200_000

        def poll(self):
            return None

    monkeypatch.setattr(ps.subprocess, "Popen", Recorder)
    monkeypatch.setattr(ps, "check_master_contract_ready", lambda *a, **k: (True, "ready"))
    monkeypatch.setattr(ps, "save_configs", lambda: True)
    monkeypatch.setattr(ps, "broadcast_status_update", lambda *a, **k: None)
    monkeypatch.setattr(ps, "LOGS_DIR", tmp_path)
    yield script, captured
    ps.STRATEGY_CONFIGS.clear()
    ps.STRATEGY_CONFIGS.update(saved)
    ps.RUNNING_STRATEGIES.clear()
    ps.RUNNING_STRATEGIES.update(running)


@pytest.mark.skipif(not POSIX, reason="resource limits and preexec_fn are POSIX only")
def test_gthread_start_passes_the_limits_to_the_child(worker, captured_launch):
    worker(True)
    script, captured = captured_launch

    ok, message = ps.start_strategy_process("launch")

    assert ok, message
    cmd = captured["cmd"]
    assert cmd[1:4] == ["-u", "-c", ps._RLIMIT_BOOTSTRAP]
    assert cmd[-1] == str(script.absolute())
    assert "preexec_fn" not in captured["kwargs"]
    env = captured["kwargs"]["env"]
    assert env["OPENALGO_STRATEGY_MEM_MB"] == str(ps.STRATEGY_MEMORY_LIMIT_MB)
    assert env["OPENALGO_STRATEGY_NPROC"] == str(ps.STRATEGY_NPROC_LIMIT)
    # The injected variables are still there alongside the limits.
    assert env["STRATEGY_ID"] == "launch"


def test_outside_gthread_the_command_line_is_unchanged(worker, captured_launch):
    worker(False)
    script, captured = captured_launch

    ok, message = ps.start_strategy_process("launch")

    assert ok, message
    assert captured["cmd"] == [sys.executable, "-u", str(script.absolute())]
    if "OPENALGO_STRATEGY_MEM_MB" not in os.environ:
        assert "OPENALGO_STRATEGY_MEM_MB" not in captured["kwargs"]["env"]


def _run_bootstrap(script: Path, *extra: str) -> subprocess.CompletedProcess:
    env = ps.apply_strategy_limits_env(os.environ.copy())
    env.pop("PYTHONSAFEPATH", None)
    return subprocess.run(
        [sys.executable, "-u", "-c", ps._RLIMIT_BOOTSTRAP, str(script), *extra],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        cwd=str(Path(__file__).resolve().parent.parent),
    )


def test_bootstrap_runs_the_script_as_main_with_its_own_folder_first(tmp_path):
    (tmp_path / "helper_mod_for_bootstrap.py").write_text("VALUE = 42\n", encoding="utf-8")
    script = tmp_path / "strategy.py"
    script.write_text(
        "import os, sys\n"
        "import helper_mod_for_bootstrap\n"
        "if __name__ == '__main__':\n"
        "    print('MAIN', helper_mod_for_bootstrap.VALUE)\n"
        "    print('FILE', os.path.abspath(__file__))\n"
        "    print('ARGV', sys.argv)\n"
        "    print('PATH0', sys.path[0])\n"
        "    print('CWD_ON_PATH', '' in sys.path)\n",
        encoding="utf-8",
    )

    result = _run_bootstrap(script, "--flag")

    assert result.returncode == 0, result.stderr
    lines = dict(line.split(" ", 1) for line in result.stdout.splitlines())
    assert lines["MAIN"] == "42"
    absolute = os.path.abspath(str(script))
    assert lines["FILE"] == absolute
    assert lines["ARGV"] == repr([absolute, "--flag"])
    assert lines["PATH0"] == os.path.dirname(absolute)
    # A direct launch never puts the working directory on the path, so the
    # platform's own packages cannot shadow a strategy's imports.
    assert lines["CWD_ON_PATH"] == "False"


@pytest.mark.skipif(not POSIX, reason="resource limits are POSIX only")
def test_bootstrap_applies_the_limits(tmp_path):
    script = tmp_path / "limits.py"
    script.write_text(
        "import resource\n"
        "for name in ('RLIMIT_AS', 'RLIMIT_CPU', 'RLIMIT_NOFILE', 'RLIMIT_NPROC'):\n"
        "    print(name, resource.getrlimit(getattr(resource, name))[0])\n",
        encoding="utf-8",
    )

    result = _run_bootstrap(script)

    assert result.returncode == 0, result.stderr
    limits = dict(line.split(" ") for line in result.stdout.splitlines())
    import resource

    def expected(name, wanted):
        hard = resource.getrlimit(getattr(resource, name))[1]
        return wanted if hard == resource.RLIM_INFINITY else min(wanted, hard)

    assert int(limits["RLIMIT_AS"]) == expected(
        "RLIMIT_AS", ps.STRATEGY_MEMORY_LIMIT_MB * 1024 * 1024
    )
    assert int(limits["RLIMIT_CPU"]) == expected("RLIMIT_CPU", ps.STRATEGY_CPU_TIME_LIMIT_SEC)
    assert int(limits["RLIMIT_NOFILE"]) == expected("RLIMIT_NOFILE", ps.STRATEGY_NOFILE_LIMIT)
    assert int(limits["RLIMIT_NPROC"]) == expected("RLIMIT_NPROC", ps.STRATEGY_NPROC_LIMIT)
