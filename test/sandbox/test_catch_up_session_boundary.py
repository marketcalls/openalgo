"""Tests for sandbox session boundary resolution and MIS catch-up filtering."""

import os
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

IST = ZoneInfo("Asia/Kolkata")


def _last_session_expiry():
    """Return the current last session expiry using the same helper as production."""
    from sandbox.session_boundary import last_session_expiry_utc

    return last_session_expiry_utc("03:00", datetime.now(IST))


def _clear_test_user(user_id: str):
    """Remove any leftover position and funds rows for a test user."""
    from database.sandbox_db import SandboxFunds, SandboxPositions, db_session

    SandboxPositions.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    SandboxFunds.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    db_session.commit()


def _create_position(
    user_id,
    symbol,
    exchange,
    product,
    quantity,
    average_price,
    created_at,
    updated_at,
):
    from database.sandbox_db import SandboxPositions, db_session

    position = SandboxPositions(
        user_id=user_id,
        symbol=symbol,
        exchange=exchange,
        product=product,
        quantity=quantity,
        average_price=Decimal(str(average_price)),
        ltp=Decimal(str(average_price)),
        created_at=created_at,
        updated_at=updated_at,
    )
    db_session.add(position)
    db_session.commit()
    db_session.refresh(position)
    return position


def test_last_session_expiry_utc_after_boundary_ist():
    """After 03:00 IST the boundary is today's 03:00 IST expressed in UTC."""
    from sandbox.session_boundary import last_session_expiry_utc

    now = datetime(2026, 8, 18, 10, 0, tzinfo=IST)
    boundary = last_session_expiry_utc("03:00", now)
    # 03:00 IST on Aug 18 = 21:30 UTC on Aug 17
    assert boundary == datetime(2026, 8, 17, 21, 30)


def test_last_session_expiry_utc_before_boundary_ist():
    """Before 03:00 IST the boundary is yesterday's 03:00 IST in UTC."""
    from sandbox.session_boundary import last_session_expiry_utc

    now = datetime(2026, 8, 18, 1, 0, tzinfo=IST)
    boundary = last_session_expiry_utc("03:00", now)
    # 03:00 IST on Aug 17 = 21:30 UTC on Aug 16
    assert boundary == datetime(2026, 8, 16, 21, 30)


@pytest.mark.parametrize(
    "bad_value",
    ["", "abc", "3", "03:00:00", "25:00", "-1:00", "03:99"],
)
def test_malformed_session_expiry_falls_back_to_default(bad_value):
    """A bad SESSION_EXPIRY_TIME must fall back, never raise.

    catch_up_mis_squareoff() wraps its whole body in `except Exception`, so a
    raise here is swallowed and the MIS square-off silently does not run. An
    out-of-range hour like "25:00" parses as two ints and only fails later in
    replace(), so parsing and range-checking have to happen together.
    """
    from sandbox.session_boundary import last_session_expiry_utc

    now = datetime(2026, 8, 18, 10, 0, tzinfo=IST)
    expected = last_session_expiry_utc("03:00", now)

    assert last_session_expiry_utc(bad_value, now) == expected


def test_valid_session_expiry_is_not_swallowed_by_the_fallback():
    """The fallback must not mask a perfectly good non-default value."""
    from sandbox.session_boundary import last_session_expiry_utc

    now = datetime(2026, 8, 18, 10, 0, tzinfo=IST)
    # 09:15 IST on Aug 18 = 03:45 UTC the same day.
    assert last_session_expiry_utc("09:15", now) == datetime(2026, 8, 18, 3, 45)


def test_t1_settlement_does_not_sweep_in_a_position_created_early_today(monkeypatch):
    """A CNC position from 01:00 IST today must not be settled a day early.

    created_at is the database clock (UTC). Building IST midnight and comparing
    it naive means the cutoff is read as UTC and lands 5.5 hours late, so a
    position created between 00:00 and 05:30 IST today looks like yesterday's.
    """
    from sandbox import catch_up_processor
    from sandbox.session_boundary import as_db_utc

    user_id = "test-t1-cutoff"
    _clear_test_user(user_id)

    ist_midnight = datetime.combine(datetime.now(IST).date(), datetime.min.time(), tzinfo=IST)
    _create_position(
        user_id=user_id,
        symbol="SBIN",
        exchange="NSE",
        product="CNC",
        quantity=10,
        average_price=800.00,
        created_at=as_db_utc(ist_midnight + timedelta(hours=1)),   # 01:00 IST today
        updated_at=as_db_utc(ist_midnight + timedelta(hours=1)),
    )

    called = []
    monkeypatch.setattr(
        "sandbox.holdings_manager.process_all_t1_settlements",
        lambda *a, **k: called.append(True),
    )

    catch_up_processor.catch_up_t1_settlement()

    assert not called, "a position created after IST midnight was settled a day early"

    _clear_test_user(user_id)

def test_reopened_mis_position_survives_catch_up():
    """Row reuse keeps old created_at; updated_at after boundary means live MIS."""
    from database.sandbox_db import SandboxPositions
    from sandbox.catch_up_processor import catch_up_mis_squareoff

    user_id = "test-reopened"
    _clear_test_user(user_id)

    last_session_expiry = _last_session_expiry()
    position = _create_position(
        user_id=user_id,
        symbol="ZEEL",
        exchange="NSE",
        product="MIS",
        quantity=50,
        average_price=100.00,
        created_at=last_session_expiry - timedelta(days=2),
        updated_at=last_session_expiry + timedelta(hours=6),
    )

    catch_up_mis_squareoff()

    refreshed = SandboxPositions.query.filter_by(id=position.id).first()
    assert refreshed is not None
    assert refreshed.quantity == 50
    assert refreshed.today_realized_pnl == Decimal("0.00")
    assert refreshed.margin_blocked == Decimal("0.00")

    _clear_test_user(user_id)


def test_overnight_mis_position_is_settled_on_catch_up():
    """Genuine overnight MIS: non-zero qty and updated_at before session boundary."""
    from database.sandbox_db import SandboxPositions
    from sandbox.catch_up_processor import catch_up_mis_squareoff

    user_id = "test-overnight"
    _clear_test_user(user_id)

    last_session_expiry = _last_session_expiry()
    position = _create_position(
        user_id=user_id,
        symbol="RELIANCE",
        exchange="NSE",
        product="MIS",
        quantity=-25,
        average_price=200.00,
        created_at=last_session_expiry - timedelta(days=1),
        updated_at=last_session_expiry - timedelta(hours=6),
    )

    catch_up_mis_squareoff()

    refreshed = SandboxPositions.query.filter_by(id=position.id).first()
    assert refreshed is not None
    assert refreshed.quantity == 0
    assert refreshed.today_realized_pnl == Decimal("0.00")

    _clear_test_user(user_id)


def test_crypto_mis_positions_are_skipped(monkeypatch):
    """When session expiry is disabled (crypto/24x7), catch-up must not square-off."""
    monkeypatch.setenv("DISABLE_SESSION_EXPIRY", "true")

    from database.sandbox_db import SandboxPositions
    from sandbox.catch_up_processor import catch_up_mis_squareoff

    user_id = "test-crypto"
    _clear_test_user(user_id)

    last_session_expiry = _last_session_expiry()
    position = _create_position(
        user_id=user_id,
        symbol="BTCUSD.P",
        exchange="CRYPTO",
        product="MIS",
        quantity=10,
        average_price=3000.00,
        created_at=last_session_expiry - timedelta(days=2),
        updated_at=last_session_expiry - timedelta(hours=6),
    )

    catch_up_mis_squareoff()

    refreshed = SandboxPositions.query.filter_by(id=position.id).first()
    assert refreshed is not None
    assert refreshed.quantity == 10

    _clear_test_user(user_id)


def test_unconfigured_exchange_mis_positions_are_skipped():
    """Exchanges with no configured square-off time are skipped, matching squareoff_manager."""
    from database.sandbox_db import SandboxPositions
    from sandbox.catch_up_processor import catch_up_mis_squareoff

    user_id = "test-unconfigured-exchange"
    _clear_test_user(user_id)

    last_session_expiry = _last_session_expiry()
    position = _create_position(
        user_id=user_id,
        symbol="UNKNOWN",
        exchange="UNKNOWN",
        product="MIS",
        quantity=10,
        average_price=100.00,
        created_at=last_session_expiry - timedelta(days=2),
        updated_at=last_session_expiry - timedelta(hours=6),
    )

    catch_up_mis_squareoff()

    refreshed = SandboxPositions.query.filter_by(id=position.id).first()
    assert refreshed is not None
    assert refreshed.quantity == 10

    _clear_test_user(user_id)
