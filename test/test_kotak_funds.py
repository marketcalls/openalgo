"""Kotak availablecash counts a same-day deposit or withdrawal.

Issue #2224. A deposit made during the day is not in "CollateralValue" until it
settles; /quick/user/limits reports it under "RmsPayInAmt", and "Net" already
counts it. availablecash was CollateralValue alone, so an account funded with
3,00,000 on top of 1,040 cash reported 1,040, and anything sizing positions
from funds saw almost nothing to trade with.

Two measured responses pin the arithmetic: the one on the issue (pay-in, no
collateral) and the one recorded in broker/kotak/api/funds.py when #1955 made
availablecash cash-only (pledged collateral, no pay-in). Both satisfy

    Net = CollateralValue + RmsPayInAmt - RmsPayOutAmt + Collateral - MarginUsed

so availablecash + collateral - utiliseddebits must equal Net, and collateral
must never be folded into availablecash.

The shared HTTP client is replaced with one that returns the response, so the
real parsing runs and nothing reaches the network.
"""

import json
from types import SimpleNamespace

import pytest

import broker.kotak.api.funds as funds

AUTH = "trading-token:::trading-sid:::https://kotak.invalid:::access-token"

# Issue #2224, sensitive fields removed by the reporter.
FUNDED_TODAY = {
    "stat": "Ok",
    "Net": 301040,
    "CollateralValue": 1040,
    "Collateral": 0,
    "MarginUsed": 0,
    "RmsPayInAmt": 300000,
    "RmsPayOutAmt": 0,
    "UnrealizedMtomPrsnt": 0,
    "RealizedMtomPrsnt": 0,
}

# The account measured for #1955, after pledging two holdings.
PLEDGED = {
    "stat": "Ok",
    "Net": 402108.1,
    "CollateralValue": 179542.8,
    "Collateral": 222565.5,
    "MarginUsed": 0.2,
    "RmsPayInAmt": 0,
    "RmsPayOutAmt": 0,
}


def _limits(monkeypatch, response):
    """Run get_margin_data against a canned /quick/user/limits response."""
    body = json.dumps(response)
    client = SimpleNamespace(
        post=lambda url, headers, content: SimpleNamespace(status_code=200, text=body)
    )
    monkeypatch.setattr(funds, "get_httpx_client", lambda: client)
    return funds.get_margin_data(AUTH)


def _reconciles_with_net(result, response):
    usable = (
        float(result["availablecash"])
        + float(result["collateral"])
        - float(result["utiliseddebits"])
    )
    return usable == pytest.approx(float(response["Net"]))


def test_a_same_day_deposit_is_available_cash(monkeypatch):
    result = _limits(monkeypatch, FUNDED_TODAY)
    assert result["availablecash"] == "301040.00", "the 3,00,000 deposited today is missing"
    assert result["collateral"] == "0.00"
    assert result["utiliseddebits"] == "0.00"
    assert _reconciles_with_net(result, FUNDED_TODAY)


def test_pledged_collateral_is_not_counted_as_cash(monkeypatch):
    """The #1955 account: no fund movement, so availablecash is unchanged by this fix."""
    result = _limits(monkeypatch, PLEDGED)
    assert result["availablecash"] == "179542.80"
    assert result["collateral"] == "222565.50"
    assert result["utiliseddebits"] == "0.20"
    assert _reconciles_with_net(result, PLEDGED)


def test_a_same_day_withdrawal_is_taken_out_of_available_cash(monkeypatch):
    response = {
        "stat": "Ok",
        "Net": 30000,
        "CollateralValue": 50000,
        "Collateral": 0,
        "MarginUsed": 0,
        "RmsPayInAmt": 0,
        "RmsPayOutAmt": 20000,
    }
    result = _limits(monkeypatch, response)
    assert result["availablecash"] == "30000.00"
    assert _reconciles_with_net(result, response)


def test_used_margin_stays_in_utiliseddebits(monkeypatch):
    """Margin blocked by a position is reported as used, not taken out of cash twice."""
    response = dict(FUNDED_TODAY, Net=201040, MarginUsed=100000)
    result = _limits(monkeypatch, response)
    assert result["availablecash"] == "301040.00"
    assert result["utiliseddebits"] == "100000.00"
    assert _reconciles_with_net(result, response)


def test_amounts_sent_as_strings_are_read(monkeypatch):
    response = {key: str(value) for key, value in FUNDED_TODAY.items()}
    assert _limits(monkeypatch, response)["availablecash"] == "301040.00"


def test_a_response_without_fund_movement_fields_reports_cash_alone(monkeypatch):
    response = {"stat": "Ok", "CollateralValue": 1040, "Collateral": 0, "MarginUsed": 0}
    assert _limits(monkeypatch, response)["availablecash"] == "1040.00"
