"""CI boots both web servers and runs the migration suite on supported hosts.

Before this, CI never started gunicorn at all: pytest only, and the one
container check overrode the entrypoint. These assertions keep the runtime and
platform jobs from being dropped or quietly softened.
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


def test_the_gates_job_runs_both_static_gates():
    script = _script(_jobs()["gthread-gates"])
    assert "scripts/gthread_check_then_act.py" in script
    assert "scripts/gthread_sleep_gate.py" in script


def test_the_full_migration_suite_runs_on_linux_with_eventlet_installed():
    job = _jobs()["gthread-migration"]
    script = _script(job)
    assert job["runs-on"] == "ubuntu-latest"
    assert job["timeout-minutes"] <= 30
    assert '"eventlet==0.41.2"' in script
    assert "test/test_gthread_*.py" in script
    assert "--timeout=120" in script
    assert "--ignore" not in script and "-k " not in script
    assert not any(step.get("continue-on-error") for step in job["steps"])


def test_cross_platform_runtime_suite_covers_windows_mac_and_arm64():
    job = _jobs()["gthread-platforms"]
    assert set(job["strategy"]["matrix"]["runner"]) == {
        "windows-latest",
        "macos-latest",
        "ubuntu-24.04-arm",
    }
    script = _script(job)
    for name in (
        "test_gthread_foundation_runtime.py",
        "test_gthread_foundation_lifecycle.py",
        "test_gthread_core_db_sessions.py",
        "test_gthread_core_shutdown.py",
        "test_gthread_core_proxy_mode.py",
        "test_gthread_hosts_chartink.py",
        "test_gthread_historify_lifecycle.py",
        "test_gthread_sandbox_funds.py",
        "test_gthread_sandbox_orders.py",
        "test_gthread_review_funds_cas_cleanup.py",
        "test_gthread_memory_auth_decrypt.py",
        "test_gthread_memory_order_updates.py",
        "test_gthread_memory_streaming.py",
        "test_gthread_memory_flow.py",
    ):
        assert f"test/{name}" in script
        assert (ROOT / "test" / name).is_file(), name
    assert job["timeout-minutes"] <= 20
    assert "uv run --no-sync python -m pytest" in script
    assert '"eventlet==0.41.2"' in script
    assert not any(step.get("continue-on-error") for step in job["steps"])


def test_images_are_built_only_after_the_new_jobs_pass():
    needs = set(_jobs()["docker-build"]["needs"])
    assert {
        "gunicorn-boot",
        "eventlet-fallback",
        "gthread-gates",
        "gthread-migration",
        "gthread-platforms",
    } <= needs
