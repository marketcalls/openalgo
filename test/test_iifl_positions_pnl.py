from broker.iifl.mapping.order_data import map_position_data, transform_positions_data


def test_closed_position_uses_realized_mtm_for_pnl(monkeypatch):
    """IIFL keeps realized P&L on a zero-quantity position as RealizedMTM."""
    monkeypatch.setattr(
        "broker.iifl.mapping.order_data.get_symbol",
        lambda _token, _exchange: "BANKNIFTY25AUG2657600CE",
    )

    response = {
        "result": {
            "positionList": [
                {
                    "ExchangeInstrumentId": 2657600,
                    "ExchangeSegment": "NSEFO",
                    "ProductType": "NRML",
                    "Quantity": 0,
                    "BuyAveragePrice": 100.0,
                    "SellAveragePrice": 110.0,
                    "RealizedMTM": 33154.5,
                }
            ]
        }
    }

    positions = transform_positions_data(map_position_data(response))

    assert positions[0]["quantity"] == 0
    assert positions[0]["pnl"] == 33154.5
