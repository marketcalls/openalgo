"""Strategy Builder derivative venues must survive the public expiry boundary."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import StaticPool

from database.symbol import Base, SymToken
from restx_api.data_schemas import ExpirySchema
from services import expiry_service
from services.expiry_service import get_expiry_dates

_ROWS = [
    ("GUARSEED31DEC301000CE", "NCDEX", "OPTFUT", "31-DEC-30"),
    ("USDINR31DEC30100CE", "BCD", "OPTCUR", "31-DEC-30"),
    ("USDINR30NOV30FUT", "BCD", "FUTCUR", "30-NOV-30"),
]


@pytest.fixture(autouse=True)
def isolated_derivative_expiries(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = scoped_session(sessionmaker(bind=engine))
    monkeypatch.setattr(expiry_service, "db_session", test_session)
    for symbol, exchange, instrumenttype, expiry in _ROWS:
        test_session.add(
            SymToken(
                symbol=symbol,
                brsymbol=symbol,
                name=symbol,
                exchange=exchange,
                brexchange=exchange,
                token=f"test-{exchange}-{symbol}",
                expiry=expiry,
                strike=1000.0,
                lotsize=1,
                instrumenttype=instrumenttype,
                tick_size=0.05,
            )
        )
    test_session.commit()
    yield
    test_session.remove()
    engine.dispose()


@pytest.mark.parametrize(
    ("exchange", "symbol"),
    [("NCDEX", "GUARSEED"), ("BCD", "USDINR")],
)
def test_public_expiry_schema_accepts_strategy_builder_venue(exchange, symbol):
    loaded = ExpirySchema().load(
        {
            "apikey": "key",
            "symbol": symbol,
            "exchange": exchange,
            "instrumenttype": "options",
        }
    )
    assert loaded["exchange"] == exchange


@pytest.mark.parametrize(
    ("exchange", "symbol"),
    [("NCDEX", "GUARSEED"), ("BCD", "USDINR")],
)
def test_expiry_service_returns_options_for_strategy_builder_venue(exchange, symbol):
    success, response, status = get_expiry_dates(
        symbol=symbol,
        exchange=exchange,
        instrumenttype="options",
    )

    assert success is True
    assert status == 200
    assert response["data"] == ["31-DEC-30"]


def test_bcd_expiry_service_keeps_futures_and_options_separate():
    success, response, status = get_expiry_dates(
        symbol="USDINR",
        exchange="BCD",
        instrumenttype="futures",
    )

    assert success is True
    assert status == 200
    assert response["data"] == ["30-NOV-30"]
