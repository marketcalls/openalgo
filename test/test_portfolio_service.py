import pandas as pd
import pytest

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


def test_service_serializes_realized_costs_and_names_gst(monkeypatch):
    prices = matrix({"A": [100.0] * 21 + [200.0], "B": [100.0] * 22})
    monkeypatch.setattr(
        portfolio_service, "load_prices", lambda *_args, **_kwargs: prices
    )
    monkeypatch.setattr(
        portfolio_service,
        "summary",
        lambda *_args, **_kwargs: {
            "sharpe": 1.0,
            "sortino": 1.0,
            "max_drawdown": -0.1,
        },
    )
    monkeypatch.setattr(portfolio_service, "_series_analytics", lambda *_args: {})
    monkeypatch.setattr(portfolio_service, "walk_forward", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(portfolio_service, "monte_carlo", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        portfolio_service, "rebalancing_sweep", lambda *_args, **_kwargs: {}
    )
    monkeypatch.setattr(portfolio_service, "structure", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(portfolio_service, "crisis_analysis", lambda *_args: {})
    monkeypatch.setattr(portfolio_service, "build_findings", lambda *_args: [])
    monkeypatch.setattr(
        portfolio_service, "_symbol_names", lambda symbols: dict.fromkeys(symbols, "")
    )

    ok, payload, status = portfolio_service.run_portfolio_backtest(
        [
            {"symbol": "A", "exchange": "NSE", "weight": 50},
            {"symbol": "B", "exchange": "NSE", "weight": 50},
        ],
        "2024-01-01",
        "2024-01-30",
        rebalance="monthly",
        initial_capital=1_000.0,
        charge_overrides={
            "brokerage": {"flat": 10.0},
            "stt": {"rate": 0.01},
            "exchange_txn": {"rate": 0.0},
            "sebi": {"rate": 0.0},
            "stamp_duty": {"rate": 0.0},
        },
        gst_rate=0.10,
        slippage=0.02,
    )

    assert ok is True
    assert status == 200
    assert "tax" not in payload["costs"]
    assert payload["costs"]["brokerage"] == 20.0
    assert payload["costs"]["stt"] == 5.0
    assert payload["costs"]["gst"] == 2.0
    assert payload["costs"]["slippage"] == 10.0
    assert payload["costs"]["total"] == 37.0


def test_live_holdings_passes_feed_token_to_history_analysis(monkeypatch):
    monkeypatch.setattr(
        "services.holdings_service.get_holdings",
        lambda **_kwargs: (
            True,
            {
                "data": {
                    "holdings": [
                        {
                            "symbol": "INFY",
                            "exchange": "NSE",
                            "quantity": 2,
                            "average_price": 100,
                            "ltp": 120,
                            "pnl": 40,
                        }
                    ]
                }
            },
            200,
        ),
    )
    captured = {}

    def backtest(*_args, **kwargs):
        captured.update(kwargs)
        return False, {"message": "stop after capture"}, 422

    monkeypatch.setattr(portfolio_service, "run_portfolio_backtest", backtest)

    ok, _payload, status = portfolio_service.analyse_live_holdings(
        api_key="key",
        auth_token="auth",
        feed_token="feed",
        broker="xts-broker",
        source="api",
    )

    assert ok is True
    assert status == 200
    assert captured["auth_token"] == "auth"
    assert captured["feed_token"] == "feed"
    assert captured["broker"] == "xts-broker"


def test_tearsheet_uses_the_same_nondefault_costs_as_backtest(monkeypatch):
    prices = matrix({"A": [100.0] * 21 + [200.0], "B": [100.0] * 22})
    monkeypatch.setattr(
        portfolio_service, "load_prices", lambda *_args, **_kwargs: prices
    )
    captured = {}

    def render(returns, **kwargs):
        captured["returns"] = returns.copy()
        return "<html>charged report</html>"

    monkeypatch.setattr("openstatz.dashboard", render)

    ok, html, status = portfolio_service.generate_tearsheet(
        [
            {"symbol": "A", "exchange": "NSE", "weight": 50},
            {"symbol": "B", "exchange": "NSE", "weight": 50},
        ],
        "2024-01-01",
        "2024-01-30",
        rebalance="monthly",
        initial_capital=1_000.0,
        charge_overrides={
            "brokerage": {"flat": 10.0},
            "stt": {"rate": 0.01},
            "exchange_txn": {"rate": 0.0},
            "sebi": {"rate": 0.0},
            "stamp_duty": {"rate": 0.0},
        },
        gst_rate=0.10,
        slippage=0.02,
    )

    assert ok is True
    assert status == 200
    assert html == "<html>charged report</html>"
    assert float((1.0 + captured["returns"]).prod() - 1.0) == pytest.approx(
        0.463
    )
