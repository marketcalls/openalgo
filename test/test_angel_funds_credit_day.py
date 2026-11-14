"""Angel's free cash must not drop when the day's booked profit puts the account in credit.

On a credit day Angel's getRMS holds `availablecash` and `utilisedpayout` at
the opening cash, makes `utiliseddebits` negative, and moves only `net`. The
old mapping read `availablecash` as the net figure, so cash = net + debits
came out as opening cash minus the profit (97500.00 below) while Angel's
own net, the figure its app offers to an order, was 102500.00.

The readings follow the shape of a live account's getRMS on a credit day and
a debit day (amounts changed), so the credit-day test fails against the old
mapping.
"""

import json

import pytest

import broker.angel.api.funds as funds

# A booked profit of 2500.00 on 100000.00 opening cash.
CREDIT_DAY = {
    "net": "102500.0000",
    "availablecash": "100000.0000",
    "availableintradaypayin": "0.0000",
    "availablelimitmargin": "0.0000",
    "collateral": "0.0000",
    "m2munrealized": "0.0000",
    "m2mrealized": "0.0000",
    "utiliseddebits": "-2500.0000",
    "utilisedpayout": "100000.0000",
}

# Losses and margin of 7500.00 on 100000.00 opening cash.
DEBIT_DAY = {
    "net": "92500.0000",
    "availablecash": "92500.0000",
    "collateral": "0.0000",
    "utiliseddebits": "7500.0000",
    "utilisedpayout": "92500.0000",
}


class _Response:
    def __init__(self, data):
        self.status_code = 200
        self.text = json.dumps({"status": True, "message": "SUCCESS", "data": data})


class _Client:
    def __init__(self, data):
        self.data = data

    def get(self, url, headers):
        return _Response(self.data)


def _margins(monkeypatch, data):
    monkeypatch.setenv("BROKER_API_KEY", "key")
    monkeypatch.setattr(funds, "get_httpx_client", lambda: _Client(data))
    monkeypatch.setattr(funds, "_get_realised_unrealised_pnl", lambda token: (0.0, 0.0))
    return funds.get_margin_data("token")


def test_credit_day_cash_is_the_opening_cash(monkeypatch):
    result = _margins(monkeypatch, CREDIT_DAY)

    # cash - debits must give back Angel's net, as on a debit day
    assert result["availablecash"] == "100000.00"
    assert result["utiliseddebits"] == "-2500.00"
    assert result["collateral"] == "0.00"


def test_debit_day_is_unchanged(monkeypatch):
    result = _margins(monkeypatch, DEBIT_DAY)

    assert result["availablecash"] == "100000.00"
    assert result["utiliseddebits"] == "7500.00"
    assert result["collateral"] == "0.00"


@pytest.mark.parametrize("net", [None, ""])
def test_missing_net_falls_back_to_availablecash(monkeypatch, net):
    result = _margins(monkeypatch, {**DEBIT_DAY, "net": net})

    assert result["availablecash"] == "100000.00"
