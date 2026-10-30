"""The published 2026 Muhurat session reaches new and existing installs.

Until the exchanges published it on 19 October 2026, the calendar OpenAlgo
shipped held Sunday 8 November at a guessed 18:00 to 19:15, MCX to 00:15 the
next morning, and no NCO row. The session is 14:20 to 15:30, F&O to 15:40. The
seed loads only into an empty table, so without the update an existing install
would keep the guess: a strategy scheduled for the real session would never
start, and one for the guess would run with the market shut.
"""

import os
import subprocess
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.orm import scoped_session, sessionmaker

import database.market_calendar_db as mc
from database.engine_factory import create_db_engine

ROOT = Path(__file__).resolve().parents[1]
SUNDAY = date(2026, 11, 8)

#: What the 2026 seed shipped before the timings were published.
GUESS = {
    "NSE": (1794141000000, 1794145500000),  # 18:00 - 19:15 IST
    "BSE": (1794141000000, 1794145500000),
    "NFO": (1794141000000, 1794145500000),
    "BFO": (1794141000000, 1794145500000),
    "CDS": (1794141000000, 1794145500000),
    "BCD": (1794141000000, 1794145500000),
    "MCX": (1794141000000, 1794163500000),  # 18:00 - 00:15 the next morning
}

#: As published: 14:20 to 15:30 IST, equity derivatives to 15:40.
PUBLISHED = {
    "NSE": (1794127800000, 1794132000000),
    "BSE": (1794127800000, 1794132000000),
    "NFO": (1794127800000, 1794132600000),
    "BFO": (1794127800000, 1794132600000),
    "CDS": (1794127800000, 1794132000000),
    "BCD": (1794127800000, 1794132000000),
    "MCX": (1794127800000, 1794132000000),
    "NCO": (1794127800000, 1794132000000),
}


def _bind(monkeypatch, url):
    """Point the calendar module at a scratch database."""
    engine = create_db_engine(url)
    session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
    monkeypatch.setattr(mc, "engine", engine)
    monkeypatch.setattr(mc, "db_session", session)
    return engine, session


@pytest.fixture
def calendar(tmp_path, monkeypatch):
    """The calendar on its own tables, seeded by its own 2026 function."""
    engine, session = _bind(monkeypatch, f"sqlite:///{(tmp_path / 'calendar.db').as_posix()}")
    # Swapped by hand: monkeypatch reads the old value with getattr, and a
    # query property read on the declarative base itself raises.
    previous_query = mc.Base.__dict__["query"]
    mc.Base.query = session.query_property()
    try:
        mc.Base.metadata.create_all(engine)
        mc.clear_market_calendar_cache()
        mc.seed_holidays_2026()
        yield mc
    finally:
        mc.clear_market_calendar_cache()
        mc.Base.query = previous_query
        session.remove()
        engine.dispose()


def _rows(calendar):
    holiday = calendar.Holiday.query.filter_by(holiday_date=SUNDAY).one()
    return {
        row.exchange_code: (row.start_time, row.end_time) if row.is_open else "closed"
        for row in calendar.HolidayExchange.query.filter_by(holiday_id=holiday.id)
    }


def _as_shipped(calendar):
    """Put 8 November back the way an install seeded before the circular has it."""
    holiday = calendar.Holiday.query.filter_by(holiday_date=SUNDAY).one()
    for row in calendar.HolidayExchange.query.filter_by(holiday_id=holiday.id).all():
        if row.exchange_code in GUESS:
            row.start_time, row.end_time = GUESS[row.exchange_code]
        else:
            calendar.db_session.delete(row)
    calendar.db_session.commit()
    calendar.clear_market_calendar_cache()


def _set(calendar, exchange, **fields):
    holiday = calendar.Holiday.query.filter_by(holiday_date=SUNDAY).one()
    row = calendar.HolidayExchange.query.filter_by(
        holiday_id=holiday.id, exchange_code=exchange
    ).one()
    for name, value in fields.items():
        setattr(row, name, value)
    calendar.db_session.commit()


def _remove(calendar, exchange):
    holiday = calendar.Holiday.query.filter_by(holiday_date=SUNDAY).one()
    calendar.HolidayExchange.query.filter_by(holiday_id=holiday.id, exchange_code=exchange).delete()
    calendar.db_session.commit()


def test_the_published_session_is_what_the_module_carries():
    assert mc.MUHURAT_2026_SESSION == PUBLISHED
    assert mc.MUHURAT_2026_DATE == SUNDAY


def test_a_new_install_is_seeded_with_the_published_session(calendar):
    assert _rows(calendar) == PUBLISHED
    assert all(action == "current" for _exchange, action in calendar.plan_muhurat_2026())
    window = calendar.get_special_session(SUNDAY, "NSE")
    assert (window["start_ms"], window["end_ms"]) == PUBLISHED["NSE"]


def test_an_existing_install_moves_from_the_guess(calendar):
    _as_shipped(calendar)
    plan = dict(calendar.plan_muhurat_2026())
    assert plan.pop("NCO") == "insert"
    assert set(plan.values()) == {"update"}
    cached = calendar.get_special_session(SUNDAY, "MCX")
    assert (cached["start_ms"], cached["end_ms"]) == GUESS["MCX"]

    calendar.migrate_muhurat_2026()

    assert _rows(calendar) == PUBLISHED
    # The cache read above is dropped, so a reader sees the session at once.
    window = calendar.get_special_session(SUNDAY, "MCX")
    assert (window["start_ms"], window["end_ms"]) == PUBLISHED["MCX"]


def test_rerunning_changes_nothing(calendar):
    _as_shipped(calendar)
    calendar.migrate_muhurat_2026()
    first = _rows(calendar)

    assert all(action == "current" for _exchange, action in calendar.migrate_muhurat_2026())
    assert _rows(calendar) == first


def test_what_an_admin_set_is_left_alone(calendar):
    _as_shipped(calendar)
    own = (1794142800000, 1794146400000)  # 18:30 - 19:30 IST
    _set(calendar, "NSE", start_time=own[0], end_time=own[1])
    _set(calendar, "CDS", is_open=False, start_time=None, end_time=None)
    _remove(calendar, "MCX")

    plan = dict(calendar.plan_muhurat_2026())
    assert plan["NSE"] == plan["CDS"] == plan["MCX"] == "custom"

    calendar.migrate_muhurat_2026()
    rows = _rows(calendar)

    assert rows["NSE"] == own
    assert rows["CDS"] == "closed"
    assert "MCX" not in rows
    assert rows["NFO"] == PUBLISHED["NFO"]
    assert rows["NCO"] == PUBLISHED["NCO"]


def test_a_removed_special_session_is_not_recreated(calendar):
    holiday = calendar.Holiday.query.filter_by(holiday_date=SUNDAY).one()
    calendar.HolidayExchange.query.filter_by(holiday_id=holiday.id).delete()
    calendar.db_session.delete(holiday)
    calendar.db_session.commit()

    assert calendar.plan_muhurat_2026() is None
    assert calendar.migrate_muhurat_2026() is None
    assert calendar.Holiday.query.filter_by(holiday_date=SUNDAY).count() == 0


def test_the_app_applies_it_at_startup(calendar, monkeypatch):
    """Restarting is enough; migrate_all is not required."""
    _as_shipped(calendar)
    monkeypatch.setattr(calendar, "init_db", lambda: None)

    calendar.ensure_market_calendar_tables_exists()

    assert _rows(calendar) == PUBLISHED


def test_the_migration_is_registered():
    # On Windows migrate_all rewraps stdout at import, which closes pytest's capture.
    with patch.object(sys, "platform", "test"):
        from upgrade import migrate_all

    names = [script for script, _description in migrate_all.MIGRATIONS]
    assert names.count("migrate_muhurat_2026.py") == 1


def _script(db_file, *args):
    """Run the real script from the project root, as migrate_all.py runs it.

    The test settings put logs in a relative LOG_DIR, which from upgrade/
    would point at a directory a fresh checkout does not have.
    """
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db_file.as_posix()}"}
    return subprocess.run(
        [sys.executable, str(Path("upgrade") / "migrate_muhurat_2026.py"), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_the_upgrade_script_reports_then_applies(calendar, tmp_path):
    """The real script, from upgrade/, against a database file in the shipped state."""
    _as_shipped(calendar)
    db_file = tmp_path / "calendar.db"
    shipped = _rows(calendar)

    status = _script(db_file, "--status")
    assert status.returncode == 0, status.stdout + status.stderr
    assert "Would change 8 exchange(s)." in status.stdout
    calendar.db_session.remove()
    assert _rows(calendar) == shipped

    applied = _script(db_file)
    assert applied.returncode == 0, applied.stdout + applied.stderr
    assert "[OK] Updated 8 exchange(s)." in applied.stdout
    calendar.db_session.remove()
    assert _rows(calendar) == PUBLISHED

    again = _script(db_file)
    assert again.returncode == 0
    assert "[OK] Nothing to change." in again.stdout


def test_the_upgrade_script_creates_no_database(tmp_path):
    missing = tmp_path / "absent.db"
    result = _script(missing)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not missing.exists()
