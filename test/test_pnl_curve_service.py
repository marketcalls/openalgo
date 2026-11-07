# test/test_pnl_curve_service.py
"""get_pnl_curve: ledger rows + daily closes -> per-strategy curve.

Only the data sources are faked (the ledger table and the daily closes); the
trading-day calendar, the base day, the symbol selection and the maths run for
real.
"""

from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import StaticPool

import services.pnl_history_service as svc
from database.pnl_db import TradebookFill

DAYS = [date(2026, 5, d) for d in (4, 5, 6, 7, 8)]  # Mon..Fri, 4th is the base day


@pytest.fixture
def ledger(monkeypatch):
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    TradebookFill.__table__.create(engine)
    scoped = scoped_session(sessionmaker(bind=engine, autoflush=False))
    monkeypatch.setattr(svc, "db_session", scoped)
    monkeypatch.setattr(svc, "get_auth_token_broker", lambda api_key: ("token", "zerodha"))
    yield scoped
    engine.dispose()


def _row(n, action, qty, price, ts, strategy="S", symbol="ABC", segment="equity", product="CNC"):
    return TradebookFill(
        dedup_key=f"k{n}",
        tradeid=f"t{n}",
        orderid=f"o{n}",
        symbol=symbol,
        exchange="NSE",
        product=product,
        segment=segment,
        action=action,
        quantity=qty,
        average_price=price,
        trade_value=qty * price,
        trade_timestamp=ts,
        source="capture",
        strategy=strategy,
    )


def _fake_closes(monkeypatch, table):
    def fake(api_key, symbol, exchange, start, end):
        return table.get((symbol, exchange), {})

    monkeypatch.setattr(svc, "_daily_closes", fake)


def test_curve_for_a_lot_carried_into_the_range(ledger, monkeypatch):
    ledger.add_all(
        [
            _row(1, "BUY", 10, 90, datetime(2026, 4, 28, 15, 13)),
            _row(2, "SELL", 10, 115, datetime(2026, 5, 6, 15, 13)),
            # Same instrument family but not equity: must be ignored.
            _row(3, "BUY", 50, 100, datetime(2026, 5, 5, 10, 0), symbol="NIFTYFUT", segment="fno"),
        ]
    )
    ledger.commit()
    _fake_closes(
        monkeypatch,
        {
            ("NIFTY", "NSE_INDEX"): dict.fromkeys(DAYS, 1.0),
            ("ABC", "NSE"): dict(zip(DAYS, [100.0, 110.0, 120.0, 130.0, 140.0], strict=True)),
        },
    )

    ok, body, status = svc.get_pnl_curve("key", "2026-05-05", "2026-05-08", "range_start")

    assert ok and status == 200
    data = body["data"]
    assert data["dates"] == ["2026-05-05", "2026-05-06", "2026-05-07", "2026-05-08"]
    assert data["base_date"] == "2026-05-04"
    s = data["by_strategy"]["S"]
    # Cost is the 4th's close (100): +100 open on the 5th, 15*10 booked on the 6th.
    assert s["unrealized"] == [100.0, 0.0, 0.0, 0.0]
    assert s["realized"] == [0.0, 150.0, 0.0, 0.0]
    assert list(data["by_strategy"]) == ["S"]


def test_actual_cost_basis_and_unknown_basis(ledger, monkeypatch):
    ledger.add_all(
        [
            _row(1, "BUY", 10, 90, datetime(2026, 4, 28, 15, 13)),
            _row(2, "SELL", 10, 115, datetime(2026, 5, 6, 15, 13)),
        ]
    )
    ledger.commit()
    _fake_closes(
        monkeypatch,
        {
            ("NIFTY", "NSE_INDEX"): dict.fromkeys(DAYS, 1.0),
            ("ABC", "NSE"): dict(zip(DAYS, [100.0, 110.0, 120.0, 130.0, 140.0], strict=True)),
        },
    )

    ok, body, _ = svc.get_pnl_curve("key", "2026-05-05", "2026-05-08", "actual_cost")
    assert ok
    assert body["data"]["by_strategy"]["S"]["realized"][1] == 250.0

    ok, _, status = svc.get_pnl_curve("key", "2026-05-05", "2026-05-08", "nonsense")
    assert not ok and status == 400


def test_weekdays_are_used_when_the_broker_has_no_index_history(ledger, monkeypatch):
    ledger.add_all([_row(1, "BUY", 10, 100, datetime(2026, 5, 5, 15, 13))])
    ledger.commit()
    _fake_closes(monkeypatch, {})

    ok, body, _ = svc.get_pnl_curve("key", "2026-05-04", "2026-05-08", "range_start")

    assert ok
    assert len(body["data"]["dates"]) == 5
    assert "calendar" in body["data"]["notes"]


def test_bars_to_closes_reads_both_epoch_conventions():
    midnight_utc = int(datetime(2026, 5, 6, 0, 0, tzinfo=svc.UTC).timestamp())
    previous_evening = int(datetime(2026, 5, 5, 18, 30, tzinfo=svc.UTC).timestamp())
    out = svc._bars_to_closes(
        [{"timestamp": midnight_utc, "close": 10}, {"timestamp": previous_evening, "close": 11}]
    )
    # Both are the bar of 6 May, so one key survives.
    assert list(out) == [date(2026, 5, 6)]


def test_symbol_contains_narrows_the_fills_before_matching(ledger, monkeypatch):
    ledger.add_all(
        [
            _row(1, "BUY", 10, 100, datetime(2026, 5, 5, 15, 13), symbol="ABC"),
            _row(2, "SELL", 10, 110, datetime(2026, 5, 6, 15, 13), symbol="ABC"),
            _row(3, "BUY", 5, 200, datetime(2026, 5, 5, 15, 13), symbol="XYZ"),
            _row(4, "SELL", 5, 230, datetime(2026, 5, 6, 15, 13), symbol="XYZ"),
        ]
    )
    ledger.commit()
    _fake_closes(monkeypatch, {("NIFTY", "NSE_INDEX"): dict.fromkeys(DAYS, 1.0)})

    ok, body, _ = svc.get_pnl_curve("key", "2026-05-05", "2026-05-08", "actual_cost", "xy")
    assert ok
    total = sum(sum(v["realized"]) for v in body["data"]["by_strategy"].values())
    assert total == 150.0  # only XYZ: 5 * (230 - 200)

    ok, body, _ = svc.get_pnl_curve("key", "2026-05-05", "2026-05-08", "actual_cost")
    total = sum(sum(v["realized"]) for v in body["data"]["by_strategy"].values())
    assert total == 250.0
