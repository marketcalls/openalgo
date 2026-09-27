"""Fail-closed contracts for scripts that invoke the master migration."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _between(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def test_native_updater_checks_each_piped_master_migration_exit():
    """Neither server retry nor local tee pipelines may hide runner failure."""
    text = (ROOT / "install" / "update.sh").read_text(encoding="utf-8")
    migration_step = _between(text, "# Step 6:", "# Step 7:")

    assert migration_step.count("migration_status=${PIPESTATUS[0]}") == 3
    assert migration_step.count('if [ "$migration_status" -ne 0 ]; then') == 3
    assert migration_step.count('log_message "Database migrations failed') == 2
    assert migration_step.count("exit 1") == 2
    assert migration_step.count('log_message "Database migrations completed"') == 2


def test_docker_startup_stops_before_services_when_master_migration_fails():
    """The container must not boot the new ORM after a required schema failure."""
    text = (ROOT / "start.sh").read_text(encoding="utf-8")
    migration_step = _between(text, "# DATABASE MIGRATIONS", "# WEBSOCKET PROXY SERVER")

    assert "migrate_all.py ||" not in migration_step
    assert "if ! /app/.venv/bin/python /app/upgrade/migrate_all.py; then" in migration_step
    assert 'echo "[OpenAlgo] Database migrations failed; startup aborted."' in migration_step
    assert "exit 1" in migration_step


def test_windows_updater_propagates_master_migration_failure():
    """The Windows updater must stop instead of continuing after a failed schema."""
    text = (ROOT / "install" / "update.bat").read_text(encoding="utf-8")
    migration_step = _between(text, "REM Step 5: Run database migrations", "REM Build frontend")

    assert "if errorlevel 1 (" in migration_step
    assert "[ERROR] Database migrations failed; update aborted." in migration_step
    assert "exit /b 1" in migration_step
    assert "[OK] Database migrations completed." in migration_step


def test_docker_run_shell_migrate_command_returns_master_failure():
    """The published Docker helper must preserve a failed master's exit status."""
    text = (ROOT / "install" / "docker-run.sh").read_text(encoding="utf-8")
    migration_command = _between(text, "do_migrate() {", "# Help function")

    assert 'log_warn "Some migrations may have had issues. Check the output above."' in (
        migration_command
    )
    assert "return 1" in migration_command


def test_docker_run_windows_migrate_command_returns_master_failure():
    """The Windows Docker helper must preserve a failed master's exit status."""
    text = (ROOT / "install" / "docker-run.bat").read_text(encoding="utf-8")
    migration_command = _between(text, ":migrate", ":help")

    assert "[WARNING] Some migrations may have had issues. Check the output above." in (
        migration_command
    )
    assert "exit /b 1" in migration_command
