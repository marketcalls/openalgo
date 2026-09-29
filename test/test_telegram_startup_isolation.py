"""The eventlet startup proof must not alter pytest's own process."""

from pathlib import Path


def test_telegram_startup_eventlet_case_is_isolated_from_pytest_collection():
    source = (Path(__file__).parent / "test_telegram_startup.py").read_text(encoding="utf-8")

    assert "eventlet.monkey_patch()" not in source
    assert "telegram_startup_eventlet_child.py" in source
