"""
Tests for services/strike_profile_service.py.

The option chain is replaced with synthetic chains so the arithmetic (units,
signs, walls, the gamma flip and the strike window) is checked without a
broker.
"""

import time

import pytest

from services import strike_profile_service as sps

SPOT = 20000.0


def _leg(oi, gamma=0.0, delta=0.0, iv=12.0, priced=True):
    leg = {"symbol": "X", "oi": oi, "ltp": 10, "lotsize": 75}
    if priced:
        leg.update({"gamma": gamma, "delta": delta, "implied_volatility": iv})
    return leg


def _chain(rows, days=3.0, spot=SPOT, forward=None):
    now = int(time.time())
    return {
        "status": "success",
        "underlying_ltp": spot,
        "forward_price": forward or spot,
        "expiry_ts": now + int(days * 86400),
        "server_ts": now,
        "chain": rows,
    }


class FakeChains:
    """Stands in for get_option_chain: answers per expiry, records each call."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def __call__(self, underlying, exchange, expiry_date, strike_count, api_key, with_greeks):
        self.calls.append((expiry_date, strike_count))
        answer = self.answers[expiry_date]
        if callable(answer):
            answer = answer(strike_count)
        return answer


def _run(monkeypatch, answers, expiries, range_pct=5.0):
    fake = FakeChains(answers)
    monkeypatch.setattr(sps, "get_option_chain", fake)
    ok, body, status = sps.get_strike_profile("NIFTY", "NFO", expiries, "key", range_pct)
    return ok, body, status, fake


def test_units_and_signs(monkeypatch):
    rows = [
        {
            "strike": 20000,
            "ce": _leg(1_000_000, gamma=0.001, delta=0.5),
            "pe": _leg(500_000, gamma=0.001, delta=-0.5),
        }
    ]
    ok, body, status, _ = _run(
        monkeypatch, {"20OCT26": (True, _chain(rows), 200)}, ["20OCT26"], None
    )
    assert ok and status == 200
    cell = body["expiries"][0]["cells"][0]
    # gamma * OI * spot^2 * 1% / 1e7: 0.001 * 1e6 * 4e8 * 0.01 / 1e7 = 400 crore
    assert cell["ce_gex"] == pytest.approx(400)
    # Puts count negative for GEX
    assert cell["pe_gex"] == pytest.approx(-200)
    assert cell["gex"] == pytest.approx(200)
    # delta * OI * spot / 1e7: 0.5 * 1e6 * 2e4 / 1e7 = 1000 crore; put delta is already negative
    assert cell["ce_dex"] == pytest.approx(1000)
    assert cell["pe_dex"] == pytest.approx(-500)
    assert cell["dex"] == pytest.approx(500)
    assert body["expiries"][0]["net_gex"] == pytest.approx(200)
    assert body["expiries"][0]["dte"] in (2, 3)


def test_unpriced_open_interest_is_flagged(monkeypatch):
    rows = [{"strike": 20000, "ce": _leg(1000, priced=False), "pe": _leg(0, priced=False)}]
    ok, body, _, _ = _run(monkeypatch, {"20OCT26": (True, _chain(rows), 200)}, ["20OCT26"], None)
    assert ok
    cell = body["expiries"][0]["cells"][0]
    assert cell["unpriced"] is True
    assert cell["gex"] == 0


def test_walls_and_union_of_strikes(monkeypatch):
    near = [
        {"strike": 19900, "ce": _leg(100, 0.001, 0.6), "pe": _leg(9000, 0.001, -0.4)},
        {"strike": 20000, "ce": _leg(500, 0.001, 0.5), "pe": _leg(500, 0.001, -0.5)},
        {"strike": 20100, "ce": _leg(8000, 0.001, 0.4), "pe": _leg(100, 0.001, -0.6)},
    ]
    far = [{"strike": 20200, "ce": _leg(100, 0.0002, 0.3), "pe": _leg(10, 0.0002, -0.7)}]
    answers = {
        "20OCT26": (True, _chain(near), 200),
        "27OCT26": (True, _chain(far, days=10), 200),
    }
    ok, body, _, _ = _run(monkeypatch, answers, ["20OCT26", "27OCT26"], None)
    assert ok
    assert body["strikes"] == [19900, 20000, 20100, 20200]
    assert body["call_wall"] == 20100
    assert body["put_wall"] == 19900
    # The far expiry does not list the near strikes: None, not zero
    far_cells = body["expiries"][1]["cells"]
    assert far_cells[:3] == [None, None, None]
    assert far_cells[3]["gex"] > 0


def test_gamma_flip_sits_between_put_and_call_concentrations(monkeypatch):
    from opengreeks import black76

    t = 3 / 365
    rows = []
    for k in range(19500, 20550, 50):
        g = float(black76.gamma("c", SPOT, k, t, 0.0, 0.12))
        # Puts below 20000, calls above: negative GEX under spot, positive over it
        ce_oi = 1_000_000 if k > 20000 else 0
        pe_oi = 1_000_000 if k < 20000 else 0
        rows.append({"strike": k, "ce": _leg(ce_oi, g, 0.5), "pe": _leg(pe_oi, g, -0.5)})
    ok, body, _, _ = _run(
        monkeypatch, {"20OCT26": (True, _chain(rows, days=3), 200)}, ["20OCT26"], None
    )
    assert ok
    assert body["flip"] is not None
    assert 19900 < body["flip"] < 20100


def test_no_flip_without_a_sign_change(monkeypatch):
    rows = [
        {"strike": k, "ce": _leg(1000, 0.001, 0.5), "pe": _leg(0)} for k in (19900, 20000, 20100)
    ]
    ok, body, _, _ = _run(monkeypatch, {"20OCT26": (True, _chain(rows), 200)}, ["20OCT26"], None)
    assert ok
    assert body["flip"] is None
    assert body["put_wall"] is None


def test_later_expiry_failure_is_marked_not_fatal(monkeypatch):
    rows = [{"strike": 20000, "ce": _leg(10, 0.001, 0.5), "pe": _leg(10, 0.001, -0.5)}]
    answers = {
        "20OCT26": (True, _chain(rows), 200),
        "27OCT26": (False, {"status": "error", "message": "No strikes"}, 404),
    }
    ok, body, _, _ = _run(monkeypatch, answers, ["20OCT26", "27OCT26"], None)
    assert ok
    assert body["expiries"][1]["available"] is False
    assert body["expiries"][1]["cells"] == [None]


def test_first_expiry_failure_and_busy_refusal_are_returned(monkeypatch):
    refused = (False, {"status": "error", "message": "busy"}, 429)
    ok, body, status, _ = _run(monkeypatch, {"20OCT26": refused}, ["20OCT26"], None)
    assert not ok and status == 429

    rows = [{"strike": 20000, "ce": _leg(10, 0.001, 0.5), "pe": _leg(10, 0.001, -0.5)}]
    answers = {"20OCT26": (True, _chain(rows), 200), "27OCT26": refused}
    ok, body, status, _ = _run(monkeypatch, answers, ["20OCT26", "27OCT26"], None)
    assert not ok and status == 429


def test_window_widens_the_strike_count_from_the_probe(monkeypatch):
    def answer(strike_count):
        rows = [
            {"strike": SPOT + 50 * i, "ce": _leg(10, 0.001, 0.5), "pe": _leg(10, 0.001, -0.5)}
            for i in range(-strike_count, strike_count + 1)
        ]
        return True, _chain(rows), 200

    ok, body, _, fake = _run(monkeypatch, {"20OCT26": answer}, ["20OCT26"], range_pct=10.0)
    assert ok
    # 10% of 20000 is 2000 points, 40 strikes of 50 plus one: capped at 40
    assert fake.calls == [("20OCT26", sps.DEFAULT_STRIKE_COUNT), ("20OCT26", 40)]
    assert len(body["strikes"]) == 81


def test_empty_expiry_list_is_refused():
    ok, body, status = sps.get_strike_profile("NIFTY", "NFO", [], "key")
    assert not ok and status == 400
