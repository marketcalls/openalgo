from types import SimpleNamespace

from blueprints.scalping import _serialize_futures_contract


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
