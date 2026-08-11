"""Strategy Builder derivative venues must survive the public expiry boundary."""

import pytest

from restx_api.data_schemas import ExpirySchema
from services.expiry_service import get_expiry_dates


_ROWS = [
    ("GUARSEED31DEC301000CE", "NCDEX", "OPTFUT"),
    ("USDINR31DEC30100CE", "BCD", "OPTCUR"),
]


@pytest.fixture(scope="module", autouse=True)
def seed_derivative_expiries():
    from database.symbol import SymToken, db_session, init_db

    try:
        init_db()
    except Exception:
        pass

    for symbol, exchange, instrumenttype in _ROWS:
        if SymToken.query.filter_by(symbol=symbol, exchange=exchange).first() is None:
            db_session.add(
                SymToken(
                    symbol=symbol,
                    brsymbol=symbol,
                    name=symbol,
                    exchange=exchange,
                    brexchange=exchange,
                    token=f"test-{exchange}-{symbol}",
                    expiry="31-DEC-30",
                    strike=1000.0,
                    lotsize=1,
                    instrumenttype=instrumenttype,
                    tick_size=0.05,
                )
            )
    db_session.commit()
    yield

    for symbol, exchange, _instrumenttype in _ROWS:
        SymToken.query.filter_by(symbol=symbol, exchange=exchange).delete()
    db_session.commit()


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
