"""Correcting the 2026 holiday calendar keeps every holiday an admin set.

upgrade/migrate_market_holidays.py deleted every holiday and reseeded from code
on each upgrade, and the startup check did the same whenever no special session
was stored. Both took every holiday an admin had added or edited on the
Holidays page. The correction that replaces them touches only rows still
exactly as the first calendar (December 2025) shipped them.

The first calendar is rebuilt here from the current seed and the module's own
record of what that release had differently, so the tests run without git.
"""

import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import scoped_session, sessionmaker

import database.market_calendar_db as mc
from database.engine_factory import create_db_engine

ROOT = Path(__file__).resolve().parents[1]

#: A holiday OpenAlgo never shipped, as an admin would add one.
ADMIN_DAY = date(2026, 12, 31)


@pytest.fixture
def calendar(tmp_path, monkeypatch):
    """The calendar on its own tables, seeded with the current calendar."""
    engine = create_db_engine(f"sqlite:///{(tmp_path / 'calendar.db').as_posix()}")
    session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
    monkeypatch.setattr(mc, "engine", engine)
    monkeypatch.setattr(mc, "db_session", session)
    # Swapped by hand: monkeypatch reads the old value with getattr, and a
    # query property read on the declarative base itself raises.
    previous_query = mc.Base.__dict__["query"]
    mc.Base.query = session.query_property()
    try:
        mc.Base.metadata.create_all(engine)
        mc.clear_market_calendar_cache()
        mc.seed_holidays_2025()
        mc.seed_holidays_2026()
        yield mc
    finally:
        mc.clear_market_calendar_cache()
        mc.Base.query = previous_query
        session.remove()
        engine.dispose()


def _stored(calendar):
    return {
        holiday.holiday_date.isoformat(): calendar._stored_entry(holiday)
        for holiday in calendar.Holiday.query.all()
    }


def _shipped_now(calendar):
    entries = {}
    for entry in calendar.shipped_holidays_2025() + calendar.shipped_holidays_2026():
        entries[entry["date"]] = (
            entry["description"],
            entry.get("holiday_type", "TRADING_HOLIDAY"),
            tuple(sorted(entry["closed"])),
            tuple(sorted((o["exchange"], o["start_time"], o["end_time"]) for o in entry["open"])),
        )
    return entries


def _delete(calendar, day):
    for holiday in calendar.Holiday.query.filter_by(holiday_date=day).all():
        calendar.HolidayExchange.query.filter_by(holiday_id=holiday.id).delete()
        calendar.db_session.delete(holiday)
    calendar.db_session.commit()


def _first_calendar(calendar):
    """Turn the seeded calendar into the one the December 2025 release shipped."""
    for day in calendar._CORRECTED_DATES:
        _delete(calendar, date.fromisoformat(day))
    for day, (description, kind, closed, opened) in calendar._V1_ONLY_ENTRIES.items():
        info = {
            "date": day,
            "description": description,
            "holiday_type": kind,
            "closed": list(closed),
            "open": [{"exchange": e, "start_time": s, "end_time": t} for e, s, t in opened],
        }
        calendar._add_holiday(info, int(day[:4]))
    calendar.db_session.commit()
    calendar.clear_market_calendar_cache()


def _add_admin_holiday(calendar):
    calendar._add_holiday(
        {
            "date": ADMIN_DAY.isoformat(),
            "description": "Office closed",
            "closed": ["NSE", "NFO"],
            "open": [],
        },
        2026,
    )
    calendar.db_session.commit()


def test_the_first_calendar_differs_where_the_record_says():
    """The record and the seed describe different calendars on exactly the
    corrected dates, or the rebuild below would test nothing."""
    assert len(mc._V1_ONLY_ENTRIES) == 17
    assert len(mc._CORRECTED_DATES) == 13
    current = {e["date"] for e in mc.shipped_holidays_2025() + mc.shipped_holidays_2026()}
    assert mc._CORRECTED_DATES <= current


def test_a_first_calendar_install_gets_the_current_one(calendar):
    _first_calendar(calendar)
    assert "2026-03-10" in _stored(calendar)  # Holi, a week late

    steps = calendar.correct_2026_calendar()

    assert sum(1 for action, *_ in steps if action == "remove") == 17
    assert sum(1 for action, *_ in steps if action == "add") == 13
    assert _stored(calendar) == _shipped_now(calendar)


def test_the_muhurat_it_adds_is_the_published_session(calendar):
    _first_calendar(calendar)
    calendar.correct_2026_calendar()

    assert all(action == "current" for _exchange, action in calendar.plan_muhurat_2026())


@pytest.mark.parametrize("first_calendar", [True, False])
def test_a_holiday_an_admin_added_survives(calendar, first_calendar):
    if first_calendar:
        _first_calendar(calendar)
    _add_admin_holiday(calendar)
    admin_row = _stored(calendar)[ADMIN_DAY.isoformat()]

    calendar.correct_2026_calendar()

    assert _stored(calendar)[ADMIN_DAY.isoformat()] == admin_row


def test_a_current_calendar_is_not_touched_at_all(calendar):
    """An admin who deleted a holiday OpenAlgo ships keeps it deleted."""
    _add_admin_holiday(calendar)
    _delete(calendar, date(2026, 10, 20))  # Dussehra
    before = _stored(calendar)

    assert calendar.plan_2026_calendar_correction() == []
    calendar.correct_2026_calendar()

    assert _stored(calendar) == before


def test_a_first_calendar_row_an_admin_edited_is_left(calendar):
    _first_calendar(calendar)
    holi = calendar.Holiday.query.filter_by(holiday_date=date(2026, 3, 10)).one()
    holi.description = "Holi (our office)"
    calendar.db_session.commit()

    calendar.correct_2026_calendar()
    stored = _stored(calendar)

    assert stored["2026-03-10"][0] == "Holi (our office)"
    assert stored["2026-03-03"][0] == "Holi"


def test_a_date_the_admin_already_fixed_is_not_doubled(calendar):
    _first_calendar(calendar)
    calendar._add_holiday(
        {
            "date": "2026-03-03",
            "description": "Holi (added by hand)",
            "closed": ["NSE"],
            "open": [],
        },
        2026,
    )
    calendar.db_session.commit()

    calendar.correct_2026_calendar()

    holi = calendar.Holiday.query.filter_by(holiday_date=date(2026, 3, 3)).all()
    assert [row.description for row in holi] == ["Holi (added by hand)"]


def test_rerunning_changes_nothing(calendar):
    _first_calendar(calendar)
    calendar.correct_2026_calendar()
    first = _stored(calendar)

    assert calendar.correct_2026_calendar() == []
    assert _stored(calendar) == first


def test_an_empty_calendar_is_left_for_the_seed(calendar):
    for holiday in calendar.Holiday.query.all():
        _delete(calendar, holiday.holiday_date)

    assert calendar.plan_2026_calendar_correction() is None
    assert calendar.correct_2026_calendar() is None
    assert calendar.Holiday.query.count() == 0


def test_startup_no_longer_wipes_when_every_special_session_is_gone(calendar, monkeypatch):
    """PINNED DEFECT. With no special session stored, startup deleted every
    holiday and reseeded, taking the admin's own with them."""
    _add_admin_holiday(calendar)
    for holiday in calendar.Holiday.query.filter_by(holiday_type="SPECIAL_SESSION").all():
        _delete(calendar, holiday.holiday_date)
    before = _stored(calendar)
    monkeypatch.setattr(calendar, "init_db", lambda: None)

    calendar.ensure_market_calendar_tables_exists()

    assert _stored(calendar) == before


def test_startup_corrects_a_first_calendar_install(calendar, monkeypatch):
    _first_calendar(calendar)
    monkeypatch.setattr(calendar, "init_db", lambda: None)

    calendar.ensure_market_calendar_tables_exists()

    assert _stored(calendar) == _shipped_now(calendar)


def _script(db_file, *args):
    """Run the real script from the project root, as migrate_all.py runs it.

    The test settings put logs in a relative LOG_DIR, which from upgrade/
    would point at a directory a fresh checkout does not have.
    """
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db_file.as_posix()}"}
    return subprocess.run(
        [sys.executable, str(Path("upgrade") / "migrate_market_holidays.py"), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_the_upgrade_script_keeps_an_admin_holiday(calendar, tmp_path):
    """PINNED DEFECT. The script deleted every holiday and reseeded on every
    upgrade, so this row was gone after each one."""
    _add_admin_holiday(calendar)
    before = _stored(calendar)

    result = _script(tmp_path / "calendar.db")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[OK] Nothing to change." in result.stdout
    calendar.db_session.remove()
    assert _stored(calendar) == before


def test_the_upgrade_script_corrects_a_first_calendar_install(calendar, tmp_path):
    _first_calendar(calendar)
    _add_admin_holiday(calendar)
    db_file = tmp_path / "calendar.db"

    status = _script(db_file, "--status")
    assert status.returncode == 0, status.stdout + status.stderr
    assert "Would change 30 holiday(s)." in status.stdout

    applied = _script(db_file)
    assert applied.returncode == 0, applied.stdout + applied.stderr
    assert "[OK] Changed 30 holiday(s)." in applied.stdout
    calendar.db_session.remove()
    stored = _stored(calendar)
    assert stored.pop(ADMIN_DAY.isoformat())[0] == "Office closed"
    assert stored == _shipped_now(calendar)

    again = _script(db_file)
    assert "[OK] Nothing to change." in again.stdout
