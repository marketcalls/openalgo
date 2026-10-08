"""Groww API calls are paced per Groww API type and retried on HTTP 429.

Groww limits requests by API type (broker-api-docs/groww-api-docs/
01-introduction.md, "Rate limits"): Orders 250/min, Live Data 300/min,
Non Trading 500/min, Authentication 30/min. Calls of one type are spaced by
that per-minute figure; different types do not wait for each other.
"""

import pytest

import broker.groww.api.rate_limiter as rl
from utils import runtime
from utils.broker_backpressure import BrokerBusyError


class FakeClock:
    """time.time / time.sleep pair that only moves when slept."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(round(seconds, 3))
        self.now += seconds


class Resp:
    def __init__(self, status, headers=None):
        self.status_code = status
        self.headers = headers or {}


class Client:
    def __init__(self, statuses, headers=None):
        self.statuses = list(statuses)
        self.headers = headers
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url))
        return Resp(self.statuses.pop(0), self.headers)


@pytest.fixture
def clock(monkeypatch):
    c = FakeClock()
    monkeypatch.setattr(rl.time, "time", c.time)
    monkeypatch.setattr(rl.time, "sleep", c.sleep)
    monkeypatch.setattr(rl, "_last_call_time", dict.fromkeys(rl.MIN_INTERVAL, 0.0))
    return c


@pytest.mark.parametrize(
    "category,per_minute", [("order", 250), ("live", 300), ("non_trading", 500), ("auth", 30)]
)
def test_calls_of_one_type_are_spaced_by_the_documented_per_minute_limit(clock, category, per_minute):
    for _ in range(3):
        rl.apply_rate_limit(category)
    assert clock.sleeps == [round(60 / per_minute, 3)] * 2


def test_types_do_not_wait_for_each_other(clock):
    rl.apply_rate_limit("live")
    rl.apply_rate_limit("order")
    rl.apply_rate_limit("non_trading")
    assert clock.sleeps == []


def test_a_429_is_retried_after_the_delay_groww_asks_for(clock):
    client = Client([429, 200], headers={"Retry-After": "2"})
    resp = rl.groww_request(client, "GET", "https://api.groww.in/x", "live")
    assert resp.status_code == 200
    assert len(client.calls) == 2
    assert 2.0 in clock.sleeps


def test_retries_stop_after_max_retries_and_return_the_429(clock):
    client = Client([429] * (rl.MAX_RETRIES + 1))
    resp = rl.groww_request(client, "POST", "https://api.groww.in/x", "order")
    assert resp.status_code == 429
    assert len(client.calls) == rl.MAX_RETRIES + 1
    # exponential fallback when Groww sends no Retry-After: 1, 2, 4
    assert [s for s in clock.sleeps if s >= 1] == [1.0, 2.0, 4.0]


def test_under_gthread_a_long_server_delay_is_refused_not_slept(clock, monkeypatch):
    monkeypatch.setattr(runtime, "gthread_active", lambda: True)
    client = Client([429, 200], headers={"Retry-After": "600"})
    with pytest.raises(BrokerBusyError):
        rl.groww_request(client, "GET", "https://api.groww.in/x", "live")
    assert len(client.calls) == 1
