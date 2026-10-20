"""Regression tests for the master migration runner."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

with patch.object(sys, "platform", "test"):
    from upgrade import migrate_all


def _failing_script(directory: Path, name: str) -> None:
    (directory / name).write_text("raise SystemExit(7)\n", encoding="utf-8")


def test_strategy_module_nonzero_exit_is_a_master_migration_failure(tmp_path, monkeypatch):
    """A broken required schema migration must make the master runner fail."""
    script_name = "migrate_strategy_module.py"
    _failing_script(tmp_path, script_name)
    monkeypatch.setattr(migrate_all, "UPGRADE_DIR", str(tmp_path))
    monkeypatch.setattr(migrate_all, "PROJECT_ROOT", str(tmp_path))

    assert migrate_all.run_migration(script_name, "Strategy Module") is False


def test_legacy_nonzero_exit_keeps_warning_compatibility(tmp_path, monkeypatch):
    """Existing best-effort migrations retain their historical warning result."""
    script_name = "legacy_warning.py"
    _failing_script(tmp_path, script_name)
    monkeypatch.setattr(migrate_all, "UPGRADE_DIR", str(tmp_path))
    monkeypatch.setattr(migrate_all, "PROJECT_ROOT", str(tmp_path))

    assert migrate_all.run_migration(script_name, "Legacy Warning") is True


def test_missing_required_strategy_script_is_a_master_migration_failure(tmp_path, monkeypatch):
    """An incomplete release cannot silently skip its required schema script."""
    monkeypatch.setattr(migrate_all, "UPGRADE_DIR", str(tmp_path))

    assert migrate_all.run_migration("migrate_strategy_module.py", "Strategy Module") is False


def test_strategy_module_migration_is_registered_once():
    """The supported master command must dispatch the strategy schema migration."""
    names = [script_name for script_name, _description in migrate_all.MIGRATIONS]

    assert names.count("migrate_strategy_module.py") == 1
    assert names.index("migrate_strategy_module.py") > names.index("migrate_watchlist.py")


def test_unknown_status_option_is_rejected_before_any_migration_runs(monkeypatch):
    """A mistaken master --status command must never apply migrations."""
    dispatched = []
    monkeypatch.setattr(sys, "argv", ["migrate_all.py", "--status"])
    monkeypatch.setattr(
        migrate_all,
        "run_migration",
        lambda script_name, description: dispatched.append((script_name, description)),
    )

    with pytest.raises(SystemExit) as exc_info:
        migrate_all.main()

    assert exc_info.value.code == 2
    assert dispatched == []


def test_required_failure_reaches_master_summary_and_exit_code(monkeypatch, capsys):
    """The supported master command returns non-zero after a required failure."""
    monkeypatch.setattr(sys, "argv", ["migrate_all.py"])
    monkeypatch.setattr(migrate_all, "MIGRATIONS", [("required.py", "Required Schema")])
    monkeypatch.setattr(migrate_all, "run_migration", lambda *_args: False)

    assert migrate_all.main() == 1

    output = capsys.readouterr().out
    assert "Successful: 0" in output
    assert "Failed: 1" in output
    assert "All migrations completed successfully" not in output
