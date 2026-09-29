"""Pytest coverage for the standalone SMTP diagnostic."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.orm import scoped_session, sessionmaker

from database import settings_db
from database.engine_factory import create_db_engine

DIAGNOSTIC_PATH = Path(__file__).with_name("test_email_functionality.py")


@pytest.fixture(autouse=True)
def isolated_settings_database(tmp_path, monkeypatch):
    """Bind every collected test to a disposable settings database."""
    test_engine = create_db_engine(f"sqlite:///{(tmp_path / 'settings.db').as_posix()}")
    original_query = settings_db.Base.__dict__["query"]
    test_session = None
    try:
        test_session = scoped_session(
            sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
        )
        monkeypatch.setattr(settings_db, "engine", test_engine)
        monkeypatch.setattr(settings_db, "db_session", test_session)
        settings_db.Base.query = test_session.query_property()
        settings_db.init_db()
        yield
    finally:
        try:
            if test_session is not None:
                test_session.remove()
                assert not test_session.registry.has()
        finally:
            try:
                test_engine.dispose()
            finally:
                settings_db.Base.query = original_query


@pytest.fixture
def smtp_diagnostic():
    """Load the CLI file by its exact path without retaining its path mutation."""
    spec = importlib.util.spec_from_file_location("_openalgo_smtp_diagnostic", DIAGNOSTIC_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    original_path = sys.path.copy()
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = original_path
    return module


def test_cli_help_does_not_require_pytest():
    """The manual diagnostic remains usable when pytest is not installed."""
    probe = """
import importlib.abc
import runpy
import sys


class BlockPytest(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == "pytest" or fullname.startswith("pytest."):
            raise ModuleNotFoundError("pytest deliberately unavailable")
        return None


script = sys.argv[1]
sys.meta_path.insert(0, BlockPytest())
sys.argv = [script, "--help"]
runpy.run_path(script, run_name="__main__")
"""
    completed = subprocess.run(
        [sys.executable, "-c", probe, str(DIAGNOSTIC_PATH)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "usage: test_email_functionality.py" in completed.stdout


def test_smtp_connection(monkeypatch, smtp_diagnostic):
    """The collected diagnostic reads synthetic settings without opening SMTP."""
    settings_db.set_smtp_settings(
        smtp_server="smtp.invalid",
        smtp_port=2525,
        smtp_username="fixture-user",
        smtp_password="fixture-password",
        smtp_use_tls=True,
        smtp_from_email="sender@example.invalid",
        smtp_helo_hostname="client.example.invalid",
    )
    observed = []

    def fake_validate_smtp_settings(smtp_settings):
        observed.append(smtp_settings.copy())
        return {"success": True, "message": "synthetic validation"}

    monkeypatch.setattr(smtp_diagnostic, "validate_smtp_settings", fake_validate_smtp_settings)

    assert smtp_diagnostic.check_smtp_connection() is True
    assert observed == [
        {
            "smtp_server": "smtp.invalid",
            "smtp_port": 2525,
            "smtp_username": "fixture-user",
            "smtp_password": "fixture-password",
            "smtp_use_tls": True,
            "smtp_from_email": "sender@example.invalid",
            "smtp_helo_hostname": "client.example.invalid",
        }
    ]
