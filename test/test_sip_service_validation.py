import pandas as pd
import pytest

from portfolio.data import PriceMatrix
from services import sip_service


def _request(**updates):
    request = {
        "symbol": "INFY",
        "exchange": "NSE",
        "start_date": "2024-01-01",
        "end_date": "2024-04-30",
        "amount": 1000,
        "include_grids": False,
    }
    request.update(updates)
    return request


def _prices() -> PriceMatrix:
    index = pd.bdate_range("2024-01-01", "2024-04-30")
    return PriceMatrix(
        closes=pd.DataFrame({"INFY": 100.0}, index=index),
        source="db",
        start=index[0].date(),
        end=index[-1].date(),
    )


@pytest.mark.parametrize(
    "amount",
    [
        "invalid",
        None,
        "nan",
        "inf",
        float("nan"),
        float("inf"),
        float("-inf"),
        pytest.param(10**1000, id="overflow"),
        0,
        -1,
    ],
)
def test_invalid_amounts_do_not_load_prices(monkeypatch, amount):
    monkeypatch.setattr(
        sip_service,
        "load_prices",
        lambda *_args, **_kwargs: pytest.fail("price loader should not be called"),
    )

    success, response, status = sip_service.run_sip_backtest(**_request(amount=amount))

    assert success is False
    assert status == 400
    assert response["message"] == "amount must be a positive number"


@pytest.mark.parametrize(
    ("frequency", "day_of_month"),
    [
        ("monthly", 0),
        ("monthly", 29),
        ("monthly", "1"),
        ("monthly", 1.5),
        ("monthly", True),
        ("quarterly", 0),
        ("quarterly", 29),
    ],
)
def test_invalid_sip_days_do_not_load_prices(monkeypatch, frequency, day_of_month):
    monkeypatch.setattr(
        sip_service,
        "load_prices",
        lambda *_args, **_kwargs: pytest.fail("price loader should not be called"),
    )

    success, response, status = sip_service.run_sip_backtest(
        **_request(frequency=frequency, day_of_month=day_of_month)
    )

    assert success is False
    assert status == 400
    assert response["message"] == "day_of_month must be an integer between 1 and 28"


@pytest.mark.parametrize("day_of_month", [1, 28])
def test_boundary_sip_days_load_prices_for_valid_requests(monkeypatch, day_of_month):
    calls = []

    def load_prices(*args, **kwargs):
        calls.append((args, kwargs))
        return _prices()

    monkeypatch.setattr(sip_service, "load_prices", load_prices)

    success, response, status = sip_service.run_sip_backtest(**_request(day_of_month=day_of_month))

    assert success is True
    assert status == 200
    assert response["request"]["amount"] == 1000.0
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == (["INFY"], ["NSE"], "2024-01-01", "2024-04-30")
    assert kwargs["source"] == "db"
