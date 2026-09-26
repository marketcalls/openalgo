"""CI boots the real launcher under both web servers and runs the eventlet tests.

Before this, CI never started gunicorn at all: pytest only, and the one
container check overrode the entrypoint. These assertions keep the three jobs
that close that gap from being dropped or quietly softened.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github" / "workflows" / "ci.yml"


def _jobs() -> dict:
    return yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"]


def _script(job: dict) -> str:
    return "\n".join(str(step.get("run", "")) for step in job["steps"])


def test_the_boot_job_runs_the_real_launcher_under_both_web_servers():
    job = _jobs()["gunicorn-boot"]
    cells = job["strategy"]["matrix"]["include"]
    assert {cell["worker"] for cell in cells} == {"eventlet", "gthread"}
    assert any(cell["mode"] == "docker" and cell["stop-within"] <= 10 for cell in cells)
    script = _script(job)
    assert "bash install/openalgo-gunicorn.sh" in script
    assert "scripts/gthread_smoke.py" in script
    assert "--stop-within" in script and "--log gunicorn.log" in script
    assert "continue-on-error" not in job
    assert not any(step.get("continue-on-error") for step in job["steps"])


def test_the_eventlet_job_runs_every_eventlet_file_and_refuses_skips():
    job = _jobs()["eventlet-fallback"]
    script = _script(job)
    for name in (
        "test_eventlet_cross_thread_locks.py",
        "test_sqlite_lock_cooperative.py",
        "test_agent_stream_eventlet.py",
        "test_telegram_startup.py",
        "test_telegram_startup_isolation.py",
        "test_gthread_deploy_eventlet.py",
    ):
        assert f"test/{name}" in script
        assert (ROOT / "test" / name).is_file(), name
    assert "import eventlet, gunicorn" in script
    assert "--junitxml=eventlet.xml" in script
    assert "tests == 0 or skipped" in script


def test_the_gates_job_runs_both_gates_and_the_deploy_tests():
    script = _script(_jobs()["gthread-gates"])
    assert "scripts/gthread_check_then_act.py" in script
    assert "scripts/gthread_sleep_gate.py" in script
    assert "test/test_gthread_deploy_*.py" in script


def test_images_are_built_only_after_the_new_jobs_pass():
    needs = set(_jobs()["docker-build"]["needs"])
    assert {"gunicorn-boot", "eventlet-fallback", "gthread-gates"} <= needs
