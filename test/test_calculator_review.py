from unittest.mock import Mock

import pytest
from flask import Flask

import restx_api.schemas  # Initialize REST namespaces before service imports.
from services.place_order_service import _risk_error, place_order


@pytest.mark.parametrize(
    "key,value",
    [("stoploss", -1), ("target", float("nan")), ("trailing_stoploss", 0), ("target", "bad")],
)
def test_invalid_risk_rejected(key, value):
    assert _risk_error({key: value})


@pytest.mark.parametrize("action,stop,target", [("BUY", 110, 120), ("SELL", 90, 80)])
def test_risk_wrong_side_rejected(action, stop, target):
    assert _risk_error(
        {"action": action, "pricetype": "LIMIT", "price": 100, "stoploss": stop, "target": target}
    )


def test_gtt_rejected_before_semi_auto_queue(monkeypatch):
    queue = Mock()
    monkeypatch.setattr("services.order_router_service.should_route_to_pending", queue)
    ok, response, code = place_order({"gtt": True}, api_key="test")
    assert not ok and code == 400 and "GTT" in response["message"]
    queue.assert_not_called()


@pytest.mark.parametrize(
    "payload", [["symbols"], {"symbols": [None]}, {"symbols": ["SBI"], "exchange": None}]
)
def test_invalid_leverage_payload_returns_400(payload):
    from blueprints.intraday_leverage import get_leverage_batch

    app = Flask(__name__)
    with app.test_request_context(json=payload):
        assert get_leverage_batch.__wrapped__()[1] == 400


def test_mode_switch_requests_watch_sync(monkeypatch):
    from database import settings_db
    from services.symbol_exit_monitor_service import get_symbol_exit_monitor

    monkeypatch.setattr(settings_db, "Settings", Mock())
    monkeypatch.setattr(settings_db, "db_session", Mock())
    sync = Mock()
    monkeypatch.setattr(get_symbol_exit_monitor(), "request_sync", sync)
    settings_db.set_analyze_mode(True)
    sync.assert_called_once()


def test_leverage_migration_seeds_shared_data_idempotently(monkeypatch):
    from pathlib import Path

    from sqlalchemy import create_engine, text

    from database.intraday_leverage_data import _LEVERAGE_DATA

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "upgrade"))
    from upgrade import migrate_intraday_leverage as migration

    engine = create_engine("sqlite:///:memory:")
    try:
        for _ in range(2):
            migration.create_table(engine)
            migration.seed_data(engine)
        with engine.connect() as conn:
            rows = dict(
                conn.execute(text("SELECT symbol, multiplier FROM intraday_leverage")).all()
            )
        assert rows == _LEVERAGE_DATA
    finally:
        engine.dispose()


def test_bse_leverage_shares_nse_schedule_but_preserves_overrides(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from database import intraday_leverage_db as db

    engine = create_engine("sqlite:///:memory:")
    db.Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                db.IntradayLeverage(symbol="SBI", exchange="NSE", multiplier=5),
                db.IntradayLeverage(symbol="OTHER", exchange="NSE", multiplier=5),
                db.IntradayLeverage(symbol="OTHER", exchange="BSE", multiplier=2),
            ]
        )
        session.commit()
        monkeypatch.setattr(db.IntradayLeverage, "query", session.query(db.IntradayLeverage))
        monkeypatch.setattr(db, "_leverage_cache", {})
        assert db.get_multiplier("SBI", "BSE") == 5
        assert db.get_multipliers_bulk(["SBI", "OTHER"], "BSE") == {"SBI": 5, "OTHER": 2}
    engine.dispose()


@pytest.mark.parametrize("script", ["migrate_intraday_leverage.py", "migrate_symbol_exit_watch.py"])
def test_required_migration_failure_reaches_runner(monkeypatch, script):
    import sys

    # The standalone runner wraps Windows stdout on import. Avoid replacing
    # pytest's capture stream when testing its pure runner logic in-process.
    with monkeypatch.context() as scoped:
        scoped.setattr(sys, "platform", "linux")
        from upgrade import migrate_all

    monkeypatch.setattr(migrate_all.subprocess, "run", lambda *a, **kw: Mock(returncode=1))
    assert migrate_all.run_migration(script, "test migration") is False
