from broker.upstox.mapping.order_data import transform_holdings_data


def test_transform_holdings_uses_standard_ltp_contract():
    out = transform_holdings_data(
        [
            {
                "tradingsymbol": "INFY",
                "exchange": "NSE",
                "quantity": 2,
                "product": "D",
                "average_price": 100,
                "last_price": 120,
                "pnl": 40,
            }
        ]
    )

    assert out == [
        {
            "symbol": "INFY",
            "exchange": "NSE",
            "quantity": 2,
            "product": "D",
            "average_price": 100.0,
            "ltp": 120.0,
            "pnl": 40.0,
            "pnlpercent": 20.0,
        }
    ]


def test_transform_holdings_handles_zero_average_price():
    out = transform_holdings_data(
        [
            {
                "tradingsymbol": "BONUS",
                "exchange": "NSE",
                "quantity": 1,
                "product": "D",
                "average_price": None,
                "last_price": 50,
                "pnl": 5,
            }
        ]
    )

    assert out[0]["average_price"] == 0.0
    assert out[0]["ltp"] == 50.0
    assert out[0]["pnlpercent"] == 0.0
