"""Tests for the cross-platform CI gates (gthread PR-10, section 7).

Covers GT-P-01 .. GT-P-07 and GT-P-12/13.

The existing Docker smoke test runs with `--entrypoint /app/.venv/bin/python`,
so it never executes start.sh, Gunicorn, Flask, Socket.IO or the WebSocket
proxy. It cannot catch a broken worker class, a proxy that never starts, a
supervisor that drops signals, or a container that reports healthy while market
data is dead. These gates must be green *before* the cutover, because they are
what would detect a bad one.
"""

from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
SMOKE = REPO / "scripts" / "gthread_container_smoke.sh"


@pytest.fixture(scope="module")
def ci():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def smoke_src():
    return SMOKE.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# GT-P-01/02/03: real-entrypoint boot on both architectures
# --------------------------------------------------------------------------


def test_container_boot_step_exists(ci):
    steps = ci["jobs"]["docker-build"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert any("Container boot" in n for n in names), (
        "no step boots the real entrypoint; the Kaleido smoke test overrides it"
    )


def test_container_boot_runs_on_both_architectures(ci):
    platforms = [m["platform"] for m in ci["jobs"]["docker-build"]["strategy"]["matrix"]["include"]]
    assert set(platforms) == {"linux/amd64", "linux/arm64"}


def test_container_boot_does_not_override_the_entrypoint(ci):
    steps = ci["jobs"]["docker-build"]["steps"]
    boot = next(s for s in steps if "Container boot" in s.get("name", ""))
    assert "--entrypoint" not in boot["run"], "boot test must use the real entrypoint"
    assert "gthread_container_smoke.sh" in boot["run"]


def test_expected_worker_class_is_the_single_cutover_switch(ci):
    """PR-11 should flip one variable here, not rewrite the test."""
    steps = ci["jobs"]["docker-build"]["steps"]
    boot = next(s for s in steps if "Container boot" in s.get("name", ""))
    assert boot["env"]["EXPECTED_WORKER_CLASS"] == "eventlet", (
        "must still assert the CURRENT worker until PR-11 flips it"
    )


# --------------------------------------------------------------------------
# GT-P-04/05/06/07: what the boot script actually asserts
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "probe,why",
    [
        ("auth/check-setup", "Flask health"),
        ("transport=polling", "Socket.IO polling"),
        ("transports=[\"websocket\"]", "Socket.IO WebSocket upgrade"),
        ("8765", "WebSocket proxy port"),
        ("configured_workers", "single-worker requirement"),
        ("websocket_proxy_mode", "proxy topology did not silently move"),
    ],
)
def test_smoke_script_probes_each_surface(smoke_src, probe, why):
    assert probe in smoke_src, f"boot script does not check {why}"


def test_smoke_script_verifies_clean_shutdown_of_both_processes(smoke_src):
    """The A7a gate: before the supervisor fix, `exec` destroyed the trap so
    SIGTERM never reached the proxy."""
    assert "docker stop" in smoke_src
    # The script uses [w]ebsocket_proxy.server so grep does not match itself.
    assert "ebsocket_proxy.server" in smoke_src, "must confirm the proxy was running"
    assert "Shutting down" in smoke_src, "must confirm the shutdown handler ran"
    assert "ExitCode" in smoke_src


def test_smoke_script_fails_the_build_on_any_failure(smoke_src):
    assert smoke_src.rstrip().endswith('[ "$FAIL" -eq 0 ]'), "script must exit non-zero on failure"


def test_smoke_script_is_parameterised_not_hardcoded(smoke_src):
    """Meaningful before the cutover (eventlet) and after it (gthread)."""
    assert "EXPECTED_WORKER_CLASS" in smoke_src
    assert 'EXPECTED_WORKER_CLASS="${2:-eventlet}"' in smoke_src


def test_smoke_script_parses(smoke_src):
    import subprocess

    result = subprocess.run(["bash", "-n", str(SMOKE)], capture_output=True)
    assert result.returncode == 0, result.stderr.decode()


# --------------------------------------------------------------------------
# GT-P-12/13: Windows and macOS dev startup
# --------------------------------------------------------------------------


def test_dev_startup_job_covers_all_three_platforms(ci):
    """CLAUDE.md requires code to work on the dev server and in production.
    CI only ever ran Linux, so a Windows- or macOS-only break was invisible."""
    matrix = ci["jobs"]["dev-startup"]["strategy"]["matrix"]["os"]
    assert set(matrix) == {"ubuntu-latest", "macos-latest", "windows-latest"}


def test_dev_startup_asserts_the_runtime_it_booted(ci):
    steps = ci["jobs"]["dev-startup"]["steps"]
    run = next(s["run"] for s in steps if "run" in s)
    assert "wsgi_hint" in run, "must assert which runtime it actually booted"
    assert "resolve_proxy_mode" in run, "must assert the proxy topology"


def test_gthread_suites_actually_run_in_ci(ci):
    """Found while writing PR-10: backend-test ran five named files, so none of
    the migration suites executed in CI. Guarantees that are never re-checked
    decay silently."""
    steps = ci["jobs"]["backend-test"]["steps"]
    runs = " ".join(s.get("run", "") for s in steps)
    assert "test_gthread_*.py" in runs, "gthread python suites do not run in CI"
    assert "test_gthread_unit_migration.sh" in runs, "shell suites do not run in CI"
    assert "test_gthread_start_supervisor.sh" in runs
    assert "gthread_check_then_act.py" in runs, "the check-then-act gate does not run in CI"
    assert "gthread_sleep_inventory.py" in runs, "the sleep inventory gate does not run in CI"


def test_dev_startup_does_not_block_on_docker(ci):
    """It gates on lint only, so a Docker Hub outage cannot hide a platform break."""
    assert ci["jobs"]["dev-startup"]["needs"] == ["backend-lint"]


def test_sqlite_platform_suite_runs_on_windows(ci):
    """GT-A4-08: CLAUDE.md records that SQLite locking is stricter on Windows,
    and the retry budget had only ever been exercised on one dev machine. The
    dev-startup job is the only place that runs on Windows."""
    job = ci["jobs"]["dev-startup"]
    assert "windows-latest" in job["strategy"]["matrix"]["os"]
    runs = " ".join(s.get("run", "") for s in job["steps"])
    assert "test_gthread_sqlite_platform.py" in runs, (
        "the platform SQLite suite does not run on Windows"
    )


def test_emit_evidence_is_reachable_from_diagnostics():
    """GT-A1-04: the emit lock can only be narrowed on evidence, and evidence
    needs to be collectable from a running server."""
    from blueprints.admin import _runtime_info

    info = _runtime_info()
    assert "socketio_emits" in info
    assert set(info["socketio_emits"]) >= {"emits", "binary_emits"}
