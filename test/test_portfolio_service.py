import pandas as pd

from portfolio.data import PriceMatrix
from services import portfolio_service


def matrix(data: dict[str, list[float]]) -> PriceMatrix:
    index = pd.bdate_range("2024-01-01", periods=len(next(iter(data.values()))))
    return PriceMatrix(
        closes=pd.DataFrame(data, index=index),
        source="db",
        start=index[0].date(),
        end=index[-1].date(),
    )


def test_negative_charge_override_is_a_client_error(monkeypatch):
    monkeypatch.setattr(
        portfolio_service,
        "load_prices",
        lambda *_args, **_kwargs: matrix({"A": [100.0, 101.0]}),
    )

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("invalid costs reached the simulation")

    monkeypatch.setattr(portfolio_service, "run_backtest", should_not_run)

    ok, payload, status = portfolio_service.run_portfolio_backtest(
        [{"symbol": "A", "exchange": "NSE", "weight": 100}],
        "2024-01-01",
        "2024-01-02",
        charge_overrides={"stt": {"rate": -0.01}},
    )

    assert ok is False
    assert status == 400
    assert "non-negative" in payload["message"]
