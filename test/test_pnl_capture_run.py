# test/test_pnl_capture_run.py
"""The daily P&L capture must leave an audit row, and tell the operator,
whenever a day's capture does not complete (SKYSHIELD_PATCHES.md, 2026-10-20).

Before this a run that stopped early (no broker session, token not resolved)
wrote nothing, so a day missing from the ledger was indistinguishable from a
day the job never fired. 2026-10-08 was lost on two accounts that way.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

import database.pnl_db as pnl_db
import services.pnl_capture_service as cap
from database.pnl_db import Base, PnlCaptureRun


@pytest.fixture()
def session(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'tradebook.db'}")
    Base.metadata.create_all(engine)
    scoped = scoped_session(sessionmaker(bind=engine, autocommit=False, autoflush=False))
    monkeypatch.setattr(cap, "db_session", scoped)
    monkeypatch.setattr(pnl_db, "engine", engine)
    yield scoped
    scoped.remove()
    engine.dispose()


@pytest.fixture()
def alerts(monkeypatch):
    sent = []
    monkeypatch.setattr(cap, "_notify_capture_problem", lambda *args: sent.append(args))
    return sent


def _runs(scoped):
    rows = scoped.query(PnlCaptureRun).order_by(PnlCaptureRun.id).all()
    out = [(r.run_date, r.status, r.error) for r in rows]
    scoped.remove()
    return out


def _trading_day(monkeypatch):
    monkeypatch.setattr(cap, "is_market_holiday", lambda *a, **k: False)


def test_capture_runs_at_1540_ist():
    assert (cap.CAPTURE_HOUR_IST, cap.CAPTURE_MINUTE_IST) == (15, 40)


def test_no_broker_session_writes_a_skipped_row_and_alerts(session, alerts, monkeypatch):
    _trading_day(monkeypatch)
    monkeypatch.setattr("database.auth_db.get_first_available_api_key", lambda: None)

    cap.run_daily_capture()

    runs = _runs(session)
    assert len(runs) == 1
    assert runs[0][1] == "skipped"
    assert "session" in runs[0][2]
    assert len(alerts) == 1 and alerts[0][1] == "skipped"


def test_unresolved_token_writes_a_skipped_row_and_alerts(session, alerts, monkeypatch):
    _trading_day(monkeypatch)
    monkeypatch.setattr("database.auth_db.get_first_available_api_key", lambda: "key")
    monkeypatch.setattr("database.auth_db.get_auth_token_broker", lambda k: (None, None))

    cap.run_daily_capture()

    runs = _runs(session)
    assert [r[1] for r in runs] == ["skipped"]
    assert len(alerts) == 1


def test_market_holiday_is_silent(session, alerts, monkeypatch):
    monkeypatch.setattr(cap, "is_market_holiday", lambda *a, **k: True)

    cap.run_daily_capture()

    assert _runs(session) == []
    assert alerts == []


def test_failed_tradebook_fetch_alerts(session, alerts, monkeypatch):
    monkeypatch.setattr(
        "services.tradebook_service.get_tradebook",
        lambda **kw: (False, {"message": "broker down"}, 500),
    )

    result = cap.capture_today_trades("token", "zerodha")

    assert result["status"] == "failed"
    assert [r[1] for r in _runs(session)] == ["failed"]
    assert len(alerts) == 1
    assert alerts[0][1:] == ("failed", "broker down")


def test_successful_capture_does_not_alert(session, alerts, monkeypatch):
    monkeypatch.setattr(
        "services.tradebook_service.get_tradebook",
        lambda **kw: (True, {"data": []}, 200),
    )

    result = cap.capture_today_trades("token", "zerodha")

    assert result["status"] == "success"
    assert alerts == []


def test_alert_failure_never_breaks_the_job(monkeypatch):
    class Boom:
        enabled = True

        def is_bot_active(self):
            raise RuntimeError("telegram down")

        def send_broadcast_alert(self, message):
            raise RuntimeError("telegram down")

    monkeypatch.setattr("services.telegram_alert_service.telegram_alert_service", Boom())
    monkeypatch.setattr("services.whatsapp_alert_service.whatsapp_alert_service", Boom())

    cap._notify_capture_problem("2026-10-08", "skipped", "No active broker session was found.")
