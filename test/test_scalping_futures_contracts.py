from types import SimpleNamespace

import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import database.symbol as symbol_db
import utils.session as session_utils
from blueprints.scalping import _serialize_futures_contract, scalping_bp


@pytest.fixture
def client(monkeypatch):
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="test")
    app.register_blueprint(scalping_bp)
    monkeypatch.setattr(session_utils, "is_session_valid", lambda: True)
    return app.test_client()


def test_futures_contract_serialization_preserves_master_contract_metadata():
    row = SimpleNamespace(
        symbol="NIFTY27AUG26FUT",
        expiry="27-AUG-26",
        lotsize=75,
        tick_size=0.05,
    )

    assert _serialize_futures_contract(row) == {
        "symbol": "NIFTY27AUG26FUT",
        "expiry": "27-AUG-26",
        "lotsize": 75,
        "tick_size": 0.05,
    }


def test_futures_route_requires_a_valid_session(client, monkeypatch):
    monkeypatch.setattr(session_utils, "is_session_valid", lambda: False)
    monkeypatch.setattr(session_utils, "revoke_user_tokens", lambda: None)

    response = client.get(
        "/scalping/api/futures?underlying=NIFTY&exchange=NFO",
        headers={"Accept": "application/json"},
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "session_expired"


def test_futures_route_filters_master_contracts_and_forwards_canonical_metadata(
    client, monkeypatch
):
    engine = create_engine("sqlite:///:memory:")
    symbol_db.Base.metadata.create_all(engine)
    db_session = sessionmaker(bind=engine)()
    db_session.add_all(
        [
            symbol_db.SymToken(
                symbol="NIFTY27AUG26FUT",
                brsymbol="NIFTY27AUG26FUT",
                name="NIFTY",
                exchange="NFO",
                expiry="27-AUG-26",
                lotsize=65,
                instrumenttype="FUT",
                tick_size=0.05,
            ),
            symbol_db.SymToken(
                symbol="NIFTY24SEP26FUT",
                brsymbol="NIFTY24SEP26FUT",
                name="NIFTY",
                exchange="NFO",
                expiry="24-SEP-26",
                lotsize=65,
                instrumenttype="FUT",
                tick_size=0.1,
            ),
            symbol_db.SymToken(
                symbol="NIFTY27AUG26FUT-BFO",
                brsymbol="NIFTY27AUG26FUT-BFO",
                name="NIFTY",
                exchange="BFO",
                expiry="27-AUG-26",
                lotsize=20,
                instrumenttype="FUT",
                tick_size=0.05,
            ),
            symbol_db.SymToken(
                symbol="BANKNIFTY27AUG26FUT",
                brsymbol="BANKNIFTY27AUG26FUT",
                name="BANKNIFTY",
                exchange="NFO",
                expiry="27-AUG-26",
                lotsize=30,
                instrumenttype="FUT",
                tick_size=0.05,
            ),
            symbol_db.SymToken(
                symbol="NIFTY27AUG2624600CE",
                brsymbol="NIFTY27AUG2624600CE",
                name="NIFTY",
                exchange="NFO",
                expiry="27-AUG-26",
                lotsize=65,
                instrumenttype="OPTIDX",
                tick_size=0.05,
            ),
        ]
    )
    db_session.commit()
    monkeypatch.setattr(symbol_db, "db_session", db_session)

    response = client.get("/scalping/api/futures?underlying=nifty&exchange=nfo")

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "success",
        "data": [
            {
                "symbol": "NIFTY27AUG26FUT",
                "expiry": "27-AUG-26",
                "lotsize": 65,
                "tick_size": 0.05,
            },
            {
                "symbol": "NIFTY24SEP26FUT",
                "expiry": "24-SEP-26",
                "lotsize": 65,
                "tick_size": 0.1,
            },
        ],
    }
