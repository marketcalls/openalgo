"""Pocketful market data over REST: quotes, depth, multiquotes, LTP and history.

No network. ``pocketful_request`` is replaced where data.py calls it, and the
answers are the examples printed on Pocketful's documentation pages
(get-market-data.md, get-last-traded-price.md, chart-data.md,
getting-started.md). The token lookups read a fixed table, and the module's
``time.sleep`` records instead of sleeping.
"""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import httpx
import pytest

from broker.pocketful.api import data
from broker.pocketful.api.baseurl import PocketfulResponse
from utils import runtime
from utils.broker_backpressure import BrokerBusyError
from utils.constants import SUPPORTED_INTERVALS

AUTH = "DEMO1:::jwt.abc.def"

# get-market-data.md, verbatim: token 14366 on NSE.
MARKET_DATA = {
    "data": {
        "ask_price": 1290,
        "ask_qty": 1089393,
        "average_trade_price": 12.97,
        "bid_price": 1285,
        "bid_qty": 3486991,
        "close_price": 13.1,
        "exchange": "NSE",
        "exchange_timestamp": 1710486278,
        "high_price": 13.3,
        "instrument_token": 14366,
        "last_trade_price": 12.9,
        "last_trade_qty": 1,
        "last_trade_time": 1710486277,
        "low_price": 12.75,
        "open_price": 13.15,
        "segment": "Capital",
        "total_buy_qty": 31748583,
        "total_sell_qty": 40173028,
        "trade_volume": 178286763,
        "yearly_high": 1840,
        "yearly_low": 570,
    },
    "message": "",
    "status": "success",
}

# get-last-traded-price.md, verbatim.
LTP_ANSWER = {"data": 446981.3, "message": "", "status": "success"}

# get-market-data.md, "Error response".
ERROR_ANSWER = {"data": {}, "message": "Invalid parameters", "status": "error"}

# chart-data.md, verbatim.
CHART_ANSWER = {
    "status": "success",
    "data": {
        "candles": [
            ["2025-01-01T09:15:00+0530", 138.35, 138.35, 137.75, 137.85, 16699],
            ["2025-01-01T09:16:00+0530", 137.85, 137.85, 137.4, 137.7, 19642],
        ]
    },
}

# getting-started.md, verbatim.
HISTORICAL_ANSWER = {
    "status": "success",
    "data": {
        "candles": [
            ["2025-01-01T09:15:00+0530", 51160, 51318.75, 51160, 51272.85, 2253300, 8805],
            ["2025-01-01T09:16:00+0530", 51256.75, 51266.8, 51100, 51126, 2253300, 16725],
        ]
    },
}

EMPTY_CANDLES = {"status": "success", "data": {"candles": []}}

TOKENS = {
    ("IDEA", "NSE"): "14366",
    ("RELIANCE", "NSE"): "2885",
    ("SBIN", "BSE"): "500112",
    ("NIFTY", "NSE_INDEX"): "26000",
    ("SENSEX", "BSE_INDEX"): "1",
    ("BANKNIFTY29JAN25FUT", "NFO"): "35001",
    ("BANKNIFTY29JAN2551000CE", "NFO"): "35002",
    ("SENSEX24DEC2580000CE", "BFO"): "8001",
    ("CRUDEOIL19DEC25FUT", "MCX"): "4001",
    ("USDINR26DEC25FUT", "CDS"): "9001",
}

# 2025-01-01T09:15:00+05:30 and 2025-01-01 00:00 UTC, in epoch seconds.
JAN1_0915_IST = 1735703100
JAN1_UTC_MIDNIGHT = 1735689600


class Broker:
    """Stands in for ``pocketful_request``: records each call and answers it."""

    def __init__(self, *answers):
        # Each answer is (status, body), an exception to raise, or a callable
        # taking the call and returning one of those. The last one repeats.
        self.answers = list(answers)
        self.calls = []

    def __call__(self, method, path, token, params=None, payload=None, timeout=None, headers=None):
        call = SimpleNamespace(
            method=method,
            path=path,
            token=token,
            params=params,
            payload=payload,
            timeout=timeout,
            headers=headers,
        )
        self.calls.append(call)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if callable(answer) and not isinstance(answer, type):
            answer = answer(call)
        if isinstance(answer, BaseException):
            raise answer
        status, body = answer
        return PocketfulResponse(status, body, json.dumps(body))


@pytest.fixture(autouse=True)
def isolated(monkeypatch, module_sleep):
    """No network, no real waits, fresh pacing state, not under gthread."""
    monkeypatch.setattr(runtime, "gthread_active", lambda: False)
    monkeypatch.setattr(data, "_next_slot", 0.0)
    monkeypatch.setattr(data, "get_token", lambda symbol, exchange: TOKENS.get((symbol, exchange)))
    monkeypatch.setattr(data, "get_tokens_bulk", lambda pairs: [TOKENS.get(pair) for pair in pairs])
    slept = []
    module_sleep(data, slept.append)
    return slept


@pytest.fixture
def broker(monkeypatch):
    def install(*answers):
        fake = Broker(*answers)
        monkeypatch.setattr(data, "pocketful_request", fake)
        return fake

    return install


def _plain_sentence(message: str):
    assert message[0].isupper() and message.endswith("."), message
    for jargon in ("HTTP", "/api", "401", "429", "Exception", "Error", "token="):
        assert jargon not in message, message


# ------------------------------------------------------------------ contract


def test_the_constructor_takes_the_auth_token_only(broker):
    fake = broker((200, MARKET_DATA))
    assert data.BrokerData.__init__.__code__.co_argcount == 2
    data.BrokerData(AUTH)
    assert fake.calls == [], "building a BrokerData sends nothing"


def test_every_advertised_interval_is_one_the_history_api_accepts():
    handler = data.BrokerData(AUTH)
    assert handler.get_intervals() == list(handler.timeframe_map)
    assert set(handler.timeframe_map) <= set(SUPPORTED_INTERVALS)
    # The values are the documented /api/data/v1/historical interval enum.
    assert set(handler.timeframe_map.values()) == {
        "1minute",
        "3minute",
        "5minute",
        "10minute",
        "15minute",
        "30minute",
        "60minute",
        "1day",
    }


# -------------------------------------------------------------------- quotes


def test_a_cash_quote_reads_the_documented_answer(broker):
    fake = broker((200, MARKET_DATA))

    quote = data.BrokerData(AUTH).get_quotes("IDEA", "NSE")

    assert [(c.method, c.path, c.params, c.token) for c in fake.calls] == [
        ("GET", "/api/v1/marketdata/NSE/Capital", {"token": "14366"}, AUTH)
    ]
    assert quote == {
        "ltp": 12.9,
        "open": 13.15,
        "high": 13.3,
        "low": 12.75,
        "prev_close": 13.1,
        "volume": 178286763,
        # The documented book is in paise: 1285 and 1290 for a 12.90 stock.
        "bid": 12.85,
        "ask": 12.9,
        "bid_qty": 3486991,
        "ask_qty": 1089393,
        "oi": 0,
    }


@pytest.mark.parametrize(
    ("symbol", "exchange", "path"),
    [
        ("SBIN", "BSE", "/api/v1/marketdata/BSE/Capital"),
        ("NIFTY", "NSE_INDEX", "/api/v1/marketdata/NSE/Capital"),
        ("SENSEX", "BSE_INDEX", "/api/v1/marketdata/BSE/Capital"),
        ("BANKNIFTY29JAN25FUT", "NFO", "/api/v1/marketdata/NFO/FutOpt"),
        ("SENSEX24DEC2580000CE", "BFO", "/api/v1/marketdata/BFO/FutOpt"),
        ("CRUDEOIL19DEC25FUT", "MCX", "/api/v1/marketdata/MCX/FutOpt"),
        ("USDINR26DEC25FUT", "CDS", "/api/v1/marketdata/CDS/Currency"),
    ],
)
def test_each_exchange_is_asked_on_its_segment(broker, symbol, exchange, path):
    fake = broker((200, MARKET_DATA))

    data.BrokerData(AUTH).get_quotes(symbol, exchange)

    assert [c.path for c in fake.calls] == [path]
    assert fake.calls[0].params == {"token": TOKENS[(symbol, exchange)]}


def test_a_book_sent_in_rupees_is_read_as_rupees(broker):
    answer = json.loads(json.dumps(MARKET_DATA))
    answer["data"].update(bid_price=12.85, ask_price=12.9)
    broker((200, answer))

    quote = data.BrokerData(AUTH).get_quotes("IDEA", "NSE")

    assert (quote["bid"], quote["ask"]) == (12.85, 12.9)


def test_a_book_without_any_rupee_price_follows_the_documented_paise(broker):
    answer = json.loads(json.dumps(MARKET_DATA))
    answer["data"].update(last_trade_price=0, close_price=0, open_price=0, average_trade_price=0)
    broker((200, answer))

    quote = data.BrokerData(AUTH).get_quotes("IDEA", "NSE")

    assert (quote["bid"], quote["ask"]) == (12.85, 12.9)


def test_open_interest_is_read_when_the_answer_carries_it(broker):
    answer = json.loads(json.dumps(MARKET_DATA))
    answer["data"]["current_open_interest"] = 8805
    broker((200, answer))

    assert data.BrokerData(AUTH).get_quotes("BANKNIFTY29JAN25FUT", "NFO")["oi"] == 8805


def test_a_symbol_not_in_the_master_contract_sends_nothing(broker):
    fake = broker((200, MARKET_DATA))

    with pytest.raises(data.PocketfulAPIError) as refused:
        data.BrokerData(AUTH).get_quotes("NOPE", "NSE")

    assert fake.calls == []
    assert "NOPE on NSE" in str(refused.value)
    _plain_sentence(str(refused.value))


def test_an_exchange_pocketful_does_not_quote_sends_nothing(broker):
    fake = broker((200, MARKET_DATA))

    with pytest.raises(data.PocketfulAPIError) as refused:
        data.BrokerData(AUTH).get_quotes("GUARSEED", "NCDEX")

    assert fake.calls == []
    _plain_sentence(str(refused.value))


def test_a_refusal_names_the_symbol_and_gives_the_brokers_words(broker):
    broker((200, ERROR_ANSWER))

    with pytest.raises(data.PocketfulAPIError) as refused:
        data.BrokerData(AUTH).get_quotes("IDEA", "NSE")

    message = str(refused.value)
    assert "IDEA on NSE" in message and "Invalid parameters" in message
    _plain_sentence(message)


def test_an_empty_answer_is_not_a_quote_of_zeros(broker):
    broker((200, {"data": {}, "message": "", "status": "success"}))

    with pytest.raises(data.PocketfulAPIError):
        data.BrokerData(AUTH).get_quotes("IDEA", "NSE")


def test_an_ended_session_says_to_log_in_again(broker):
    broker((401, {"status": "error", "message": "Request Unauthorised", "data": {}}))

    with pytest.raises(data.PocketfulUnavailableError) as refused:
        data.BrokerData(AUTH).get_quotes("IDEA", "NSE")

    assert str(refused.value) == data._SESSION_ENDED
    _plain_sentence(str(refused.value))


def test_a_transport_failure_is_a_sentence(broker):
    broker(httpx.ConnectError("connection refused"))

    with pytest.raises(data.PocketfulUnavailableError) as refused:
        data.BrokerData(AUTH).get_quotes("IDEA", "NSE")

    assert str(refused.value) == data._UNREACHABLE
    _plain_sentence(str(refused.value))


# --------------------------------------------------------------------- depth


@pytest.mark.parametrize("method", ["get_depth", "get_market_depth"])
def test_depth_is_the_best_bid_and_ask_padded_to_five_levels(broker, method):
    fake = broker((200, MARKET_DATA))

    depth = getattr(data.BrokerData(AUTH), method)("IDEA", "NSE")

    assert len(fake.calls) == 1
    assert (
        depth["bids"]
        == [{"price": 12.85, "quantity": 3486991}] + [{"price": 0.0, "quantity": 0}] * 4
    )
    assert (
        depth["asks"]
        == [{"price": 12.9, "quantity": 1089393}] + [{"price": 0.0, "quantity": 0}] * 4
    )
    assert {k: depth[k] for k in depth if k not in ("bids", "asks")} == {
        "high": 13.3,
        "low": 12.75,
        "ltp": 12.9,
        "ltq": 1,
        "oi": 0,
        "open": 13.15,
        "prev_close": 13.1,
        "totalbuyqty": 31748583,
        "totalsellqty": 40173028,
        "volume": 178286763,
    }


# ----------------------------------------------------------------------- LTP


@pytest.mark.parametrize(
    ("symbol", "exchange", "path"),
    [
        ("NIFTY", "NSE_INDEX", "/api/v1/marketdata/NSE/Capital"),
        ("BANKNIFTY29JAN2551000CE", "NFO", "/api/v1/marketdata/NFO/FutOpt"),
    ],
)
def test_ltp_is_one_request_with_the_documented_key(broker, symbol, exchange, path):
    fake = broker((200, LTP_ANSWER))

    price = data.BrokerData(AUTH).get_ltp(symbol, exchange)

    assert price == 446981.3 and isinstance(price, float)
    assert [(c.method, c.path, c.params) for c in fake.calls] == [
        ("GET", path, {"token": TOKENS[(symbol, exchange)], "key": "last_trade_price"})
    ]


@pytest.mark.parametrize(
    "answer",
    [
        (200, ERROR_ANSWER),
        (200, {"data": {}, "message": "", "status": "success"}),
        (200, {"data": 0, "message": "", "status": "success"}),
        (200, {"data": None, "message": "", "status": "success"}),
        (200, {"data": True, "message": "", "status": "success"}),
        (401, {"status": "error", "message": "Request Unauthorised", "data": {}}),
        (502, None),
        httpx.ReadTimeout("timed out"),
    ],
)
def test_ltp_is_zero_when_there_is_no_price(broker, answer):
    broker(answer)

    price = data.BrokerData(AUTH).get_ltp("IDEA", "NSE")

    assert price == 0.0 and isinstance(price, float)


@pytest.mark.parametrize(("symbol", "exchange"), [("NOPE", "NSE"), ("GUARSEED", "NCDEX")])
def test_ltp_of_something_pocketful_cannot_quote_is_zero_and_sends_nothing(
    broker, symbol, exchange
):
    fake = broker((200, LTP_ANSWER))

    assert data.BrokerData(AUTH).get_ltp(symbol, exchange) == 0.0
    assert fake.calls == []


def test_ltp_refused_by_pacing_is_zero_not_an_exception(broker, monkeypatch):
    fake = broker((200, LTP_ANSWER))
    monkeypatch.setattr(runtime, "gthread_active", lambda: True)
    monkeypatch.setattr(data, "_next_slot", data.time.monotonic() + 600)

    assert data.BrokerData(AUTH).get_ltp("IDEA", "NSE") == 0.0
    assert fake.calls == []


def test_ltp_rate_limited_to_the_end_is_zero(broker):
    fake = broker((429, {"status": "error", "message": "Rate limit Exceeded", "data": {}}))

    assert data.BrokerData(AUTH).get_ltp("IDEA", "NSE") == 0.0
    assert len(fake.calls) == 1 + data._RATE_LIMIT_RETRIES


# --------------------------------------------------------------- multiquotes


def test_multiquotes_quote_each_symbol_once_in_the_order_given(broker):
    def answer(call):
        body = json.loads(json.dumps(MARKET_DATA))
        body["data"]["last_trade_price"] = float(call.params["token"])
        return 200, body

    fake = broker(answer)
    symbols = [
        {"symbol": "IDEA", "exchange": "NSE"},
        {"symbol": "NOPE", "exchange": "NSE"},
        {"symbol": "NIFTY", "exchange": "NSE_INDEX"},
    ]

    results = data.BrokerData(AUTH).get_multiquotes(symbols)

    assert [c.params["token"] for c in fake.calls] == ["14366", "26000"]
    assert [(r["symbol"], r["exchange"]) for r in results] == [
        ("IDEA", "NSE"),
        ("NOPE", "NSE"),
        ("NIFTY", "NSE_INDEX"),
    ]
    assert results[0]["data"]["ltp"] == 14366.0
    assert results[2]["data"]["ltp"] == 26000.0
    assert "data" not in results[1]
    _plain_sentence(results[1]["error"])


def test_multiquotes_keep_one_symbols_refusal_and_go_on(broker):
    fake = broker((200, ERROR_ANSWER), (200, MARKET_DATA))

    results = data.BrokerData(AUTH).get_multiquotes(
        [{"symbol": "IDEA", "exchange": "NSE"}, {"symbol": "RELIANCE", "exchange": "NSE"}]
    )

    assert len(fake.calls) == 2
    assert "Invalid parameters" in results[0]["error"]
    assert results[1]["data"]["ltp"] == 12.9


@pytest.mark.parametrize(
    "answer",
    [
        (401, {"status": "error", "message": "Request Unauthorised", "data": {}}),
        httpx.ConnectError("connection refused"),
    ],
)
def test_multiquotes_stop_at_the_first_failure_every_symbol_would_share(broker, answer):
    fake = broker(answer)
    symbols = [{"symbol": "IDEA", "exchange": "NSE"}, {"symbol": "RELIANCE", "exchange": "NSE"}]

    with pytest.raises(data.PocketfulUnavailableError):
        data.BrokerData(AUTH).get_multiquotes(symbols)

    assert len(fake.calls) == 1


def test_a_pacing_refusal_reaches_the_quotes_service_as_busy(broker, monkeypatch):
    import services.quotes_service as quotes_service
    from services.broker_busy import is_broker_busy

    fake = broker((200, MARKET_DATA))
    monkeypatch.setattr(quotes_service, "get_token", lambda symbol, exchange: "14366")
    monkeypatch.setattr(runtime, "gthread_active", lambda: True)
    monkeypatch.setattr(data, "_next_slot", data.time.monotonic() + 600)
    request = [{"symbol": "IDEA", "exchange": "NSE"}]

    ok, response, status = quotes_service.get_multiquotes_with_auth(
        AUTH, None, "pocketful", request
    )
    assert not ok and is_broker_busy(status), (status, response)

    ok, response, status = quotes_service.get_quotes_with_auth(
        AUTH, None, "pocketful", "IDEA", "NSE"
    )
    assert not ok and is_broker_busy(status), (status, response)
    assert fake.calls == []


# -------------------------------------------------------------------- pacing


def test_requests_are_paced_from_module_state(broker, isolated):
    fake = broker((200, MARKET_DATA))

    # A new BrokerData per request, as the services build them.
    for _ in range(3):
        data.BrokerData(AUTH).get_quotes("IDEA", "NSE")

    assert len(fake.calls) == 3
    # The fake sleep does not move the clock, so each turn books after the last.
    assert len(isolated) == 2
    assert isolated[0] == pytest.approx(data._MIN_INTERVAL, abs=0.05)
    assert isolated[1] == pytest.approx(2 * data._MIN_INTERVAL, abs=0.05)


def test_under_gthread_a_turn_too_far_away_is_refused_before_booking(broker, monkeypatch):
    fake = broker((200, MARKET_DATA))
    monkeypatch.setattr(runtime, "gthread_active", lambda: True)
    booked = data.time.monotonic() + 600
    monkeypatch.setattr(data, "_next_slot", booked)

    with pytest.raises(BrokerBusyError):
        data.BrokerData(AUTH).get_quotes("IDEA", "NSE")

    assert fake.calls == []
    assert data._next_slot == booked, "a refused request must not book a turn"


def test_a_rate_limited_request_is_retried_with_backoff(broker, isolated):
    limited = (429, {"status": "error", "message": "Rate limit Exceeded", "data": {}})
    fake = broker(limited, limited, (200, MARKET_DATA))

    quote = data.BrokerData(AUTH).get_quotes("IDEA", "NSE")

    assert quote["ltp"] == 12.9 and len(fake.calls) == 3
    backoffs = [s for s in isolated if s >= 1.0]
    assert backoffs == [1.0, 2.0]


def test_a_rate_limit_that_holds_is_a_busy_refusal_with_a_sentence(broker):
    fake = broker((429, {"status": "error", "message": "Rate limit Exceeded", "data": {}}))

    with pytest.raises(BrokerBusyError) as refused:
        data.BrokerData(AUTH).get_multiquotes(
            [{"symbol": "IDEA", "exchange": "NSE"}, {"symbol": "RELIANCE", "exchange": "NSE"}]
        )

    assert len(fake.calls) == 1 + data._RATE_LIMIT_RETRIES, "the second symbol is not tried"
    assert str(refused.value) == data._RATE_LIMITED
    _plain_sentence(str(refused.value))


# ------------------------------------------------------------ chart history


def _candle(stamp, price, volume=100):
    return [stamp, price, price + 1, price - 1, price + 0.5, volume]


def _candles(*rows):
    return 200, {"status": "success", "data": {"candles": list(rows)}}


def test_chart_history_asks_for_one_minute_candles_in_contiguous_chunks(broker):
    fake = broker((200, CHART_ANSWER), (200, EMPTY_CANDLES))

    data.BrokerData(AUTH).get_history("IDEA", "NSE", "5m", "2025-01-01", "2025-01-20")

    assert {(c.method, c.path) for c in fake.calls} == {("GET", "/api/v1/charts")}
    # chart-data.md lists a clientid header beside the session's own.
    assert all(c.headers == {"clientid": "DEMO1"} for c in fake.calls)
    assert [c.params for c in fake.calls] == [
        {
            "exchange": "NSE",
            "token": "14366",
            "candletype": "1",
            "from_date": first,
            "to_date": last,
        }
        for first, last in [
            ("2025-01-01T00:00:00", "2025-01-07T23:59:59"),
            ("2025-01-08T00:00:00", "2025-01-14T23:59:59"),
            ("2025-01-15T00:00:00", "2025-01-20T23:59:59"),
        ]
    ]


def test_one_minute_bars_are_the_documented_candles_at_their_utc_instant(broker):
    broker((200, CHART_ANSWER))

    frame = data.BrokerData(AUTH).get_history("IDEA", "NSE", "1m", "2025-01-01", "2025-01-01")

    assert list(frame.columns) == ["timestamp", "open", "high", "low", "close", "volume", "oi"]
    assert frame.to_dict(orient="records") == [
        {
            "timestamp": JAN1_0915_IST,
            "open": 138.35,
            "high": 138.35,
            "low": 137.75,
            "close": 137.85,
            "volume": 16699,
            "oi": 0,
        },
        {
            "timestamp": JAN1_0915_IST + 60,
            "open": 137.85,
            "high": 137.85,
            "low": 137.4,
            "close": 137.7,
            "volume": 19642,
            "oi": 0,
        },
    ]


@pytest.mark.parametrize(
    ("symbol", "exchange", "timeframe", "first", "count", "starts"),
    [
        # NSE opens at 09:15: ten one minute candles make two 5 minute bars.
        ("IDEA", "NSE", "5m", "09:15", 10, ["09:15", "09:20"]),
        ("IDEA", "NSE", "1h", "09:15", 70, ["09:15", "10:15"]),
        ("IDEA", "NSE", "10m", "09:15", 20, ["09:15", "09:25"]),
        # MCX opens at 09:00.
        ("CRUDEOIL19DEC25FUT", "MCX", "1h", "09:00", 90, ["09:00", "10:00"]),
    ],
)
def test_built_bars_start_at_the_session_open(
    broker, symbol, exchange, timeframe, first, count, starts
):
    hour, minute = map(int, first.split(":"))
    base = hour * 60 + minute
    rows = [
        _candle(f"2025-01-01T{(base + i) // 60:02d}:{(base + i) % 60:02d}:00+0530", 100 + i)
        for i in range(count)
    ]
    broker(_candles(*rows))

    frame = data.BrokerData(AUTH).get_history(
        symbol, exchange, timeframe, "2025-01-01", "2025-01-01"
    )

    def epoch(hhmm):
        h, m = map(int, hhmm.split(":"))
        return JAN1_UTC_MIDNIGHT + (h * 60 + m) * 60 - 19800

    assert frame["timestamp"].tolist() == [epoch(s) for s in starts]
    per_bar = {"5m": 5, "10m": 10, "1h": 60}[timeframe]  # minutes in the first, full bar
    first_bar = frame.iloc[0]
    assert first_bar["open"] == 100
    assert first_bar["high"] == 100 + per_bar - 1 + 1
    assert first_bar["low"] == 100 - 1
    assert first_bar["close"] == 100 + per_bar - 1 + 0.5
    assert first_bar["volume"] == 100 * per_bar


def test_daily_bars_are_built_per_ist_date_at_utc_midnight(broker):
    broker(
        _candles(
            _candle("2025-01-01T09:15:00+0530", 100, volume=10),
            _candle("2025-01-01T15:29:00+0530", 110, volume=20),
            _candle("2025-01-02T09:15:00+0530", 120, volume=30),
        )
    )

    frame = data.BrokerData(AUTH).get_history("IDEA", "NSE", "D", "2025-01-01", "2025-01-02")

    assert frame.to_dict(orient="records") == [
        {
            "timestamp": JAN1_UTC_MIDNIGHT,
            "open": 100.0,
            "high": 111.0,
            "low": 99.0,
            "close": 110.5,
            "volume": 30,
            "oi": 0,
        },
        {
            "timestamp": JAN1_UTC_MIDNIGHT + 86400,
            "open": 120.0,
            "high": 121.0,
            "low": 119.0,
            "close": 120.5,
            "volume": 30,
            "oi": 0,
        },
    ]


def test_candles_outside_the_requested_dates_are_dropped(broker):
    broker(
        _candles(
            _candle("2024-12-31T15:29:00+0530", 90),
            _candle("2025-01-01T09:15:00+0530", 100),
            _candle("2025-01-02T09:15:00+0530", 110),
        )
    )

    frame = data.BrokerData(AUTH).get_history("IDEA", "NSE", "1m", "2025-01-01", "2025-01-01")

    assert frame["timestamp"].tolist() == [JAN1_0915_IST]


def test_index_history_is_asked_on_the_cash_exchange(broker):
    fake = broker((200, CHART_ANSWER))

    data.BrokerData(AUTH).get_history("NIFTY", "NSE_INDEX", "1m", "2025-01-01", "2025-01-01")

    assert fake.calls[0].params["exchange"] == "NSE"
    assert fake.calls[0].params["token"] == "26000"


def test_a_failed_chunk_fails_the_request_instead_of_leaving_a_gap(broker):
    fake = broker((200, CHART_ANSWER), (200, ERROR_ANSWER), (200, CHART_ANSWER))

    with pytest.raises(data.PocketfulAPIError) as refused:
        data.BrokerData(AUTH).get_history("IDEA", "NSE", "1m", "2025-01-01", "2025-01-20")

    assert len(fake.calls) == 2
    _plain_sentence(str(refused.value))


def test_no_candles_is_an_empty_frame_with_the_columns(broker):
    broker((200, EMPTY_CANDLES))

    frame = data.BrokerData(AUTH).get_history("IDEA", "NSE", "D", "2025-01-01", "2025-01-03")

    assert frame.empty
    assert list(frame.columns) == ["timestamp", "open", "high", "low", "close", "volume", "oi"]


@pytest.mark.parametrize(
    ("symbol", "exchange", "timeframe"),
    [("IDEA", "NSE", "2h"), ("IDEA", "NSE", "W"), ("NOPE", "NSE", "1m"), ("X", "NCDEX", "1m")],
)
def test_what_cannot_be_served_is_refused_before_any_request(broker, symbol, exchange, timeframe):
    fake = broker((200, CHART_ANSWER))

    with pytest.raises(data.PocketfulAPIError) as refused:
        data.BrokerData(AUTH).get_history(symbol, exchange, timeframe, "2025-01-01", "2025-01-02")

    assert fake.calls == []
    _plain_sentence(str(refused.value))


# ------------------------------------------------------------- NFO history


def test_nfo_option_history_posts_the_documented_body_and_keeps_oi(broker):
    fake = broker((200, HISTORICAL_ANSWER))

    frame = data.BrokerData(AUTH).get_history(
        "BANKNIFTY29JAN2551000CE", "NFO", "1m", "2025-01-01", "2025-01-01"
    )

    assert [(c.method, c.path, c.payload) for c in fake.calls] == [
        (
            "POST",
            "/api/data/v1/historical",
            {
                "symbol": "BANKNIFTY",
                "product_type": "options",
                "type": "CE",
                "strike_price": 51000,
                "expiry_date": "2025-01-29",
                "interval": "1minute",
                "from_date": "2025-01-01T00:00:00",
                "to_date": "2025-01-01T23:59:59",
            },
        )
    ]
    # The documented body sends a whole strike as 51000, not 51000.0.
    assert json.dumps(fake.calls[0].payload["strike_price"]) == "51000"
    assert frame["timestamp"].tolist() == [JAN1_0915_IST, JAN1_0915_IST + 60]
    assert frame["oi"].tolist() == [8805, 16725]
    assert frame["close"].tolist() == [51272.85, 51126.0]


@pytest.mark.parametrize(("timeframe", "interval"), [("1h", "60minute"), ("D", "1day")])
def test_nfo_future_history_sends_no_strike_and_the_documented_interval(
    broker, monkeypatch, timeframe, interval
):
    monkeypatch.setattr(data, "_ist_today", lambda: date(2025, 2, 1))
    fake = broker((200, HISTORICAL_ANSWER))

    data.BrokerData(AUTH).get_history(
        "BANKNIFTY29JAN25FUT", "NFO", timeframe, "2025-01-01", "2025-01-01"
    )

    assert fake.calls[0].payload == {
        "symbol": "BANKNIFTY",
        "product_type": "futures",
        "expiry_date": "2025-01-29",
        "interval": interval,
        "from_date": "2025-01-01T00:00:00",
        "to_date": "2025-01-01T23:59:59",
    }


@pytest.mark.parametrize("historical", [(200, ERROR_ANSWER), (200, EMPTY_CANDLES)])
def test_nfo_history_falls_back_to_chart_candles(broker, historical):
    def answer(call):
        return historical if call.path == "/api/data/v1/historical" else (200, CHART_ANSWER)

    fake = broker(answer)

    frame = data.BrokerData(AUTH).get_history(
        "BANKNIFTY29JAN2551000CE", "NFO", "1m", "2025-01-01", "2025-01-01"
    )

    assert [c.path for c in fake.calls] == ["/api/data/v1/historical", "/api/v1/charts"]
    assert fake.calls[1].params["exchange"] == "NFO" and fake.calls[1].params["token"] == "35002"
    assert frame["close"].tolist() == [137.85, 137.7]
    assert frame["oi"].tolist() == [0, 0]


def test_an_ended_session_does_not_fall_back(broker):
    fake = broker((401, {"status": "error", "message": "Request Unauthorised", "data": {}}))

    with pytest.raises(data.PocketfulUnavailableError):
        data.BrokerData(AUTH).get_history(
            "BANKNIFTY29JAN2551000CE", "NFO", "1m", "2025-01-01", "2025-01-01"
        )

    assert [c.path for c in fake.calls] == ["/api/data/v1/historical"]


def test_bfo_history_uses_chart_candles(broker):
    fake = broker((200, CHART_ANSWER))

    data.BrokerData(AUTH).get_history(
        "SENSEX24DEC2580000CE", "BFO", "1m", "2025-01-01", "2025-01-01"
    )

    assert [c.path for c in fake.calls] == ["/api/v1/charts"]
    assert fake.calls[0].params["exchange"] == "BFO"


def _daily_answer(*days):
    rows = [[f"{day}T00:00:00+0530", 100, 110, 90, 105, 1000, 50] for day in days]
    return 200, {"status": "success", "data": {"candles": rows}}


def _quote_traded_at(epoch):
    body = json.loads(json.dumps(MARKET_DATA))
    body["data"].update(
        last_trade_time=epoch,
        open_price=200,
        high_price=210,
        low_price=195,
        last_trade_price=205,
        trade_volume=777,
        current_open_interest=60,
    )
    return 200, body


def test_todays_daily_bar_comes_from_the_quote_when_the_series_stops_before_it(broker, monkeypatch):
    monkeypatch.setattr(data, "_ist_today", lambda: date(2025, 1, 2))
    jan2_1000_ist = JAN1_UTC_MIDNIGHT + 86400 + 10 * 3600 - 19800
    fake = broker(_daily_answer("2025-01-01"), _quote_traded_at(jan2_1000_ist))

    frame = data.BrokerData(AUTH).get_history(
        "BANKNIFTY29JAN25FUT", "NFO", "D", "2025-01-01", "2025-01-02"
    )

    assert [c.path for c in fake.calls] == [
        "/api/data/v1/historical",
        "/api/v1/marketdata/NFO/FutOpt",
    ]
    assert frame.to_dict(orient="records")[-1] == {
        "timestamp": JAN1_UTC_MIDNIGHT + 86400,
        "open": 200.0,
        "high": 210.0,
        "low": 195.0,
        "close": 205.0,
        "volume": 777,
        "oi": 60,
    }
    assert frame["timestamp"].tolist() == [JAN1_UTC_MIDNIGHT, JAN1_UTC_MIDNIGHT + 86400]


def test_a_quote_from_an_earlier_session_adds_no_daily_bar(broker, monkeypatch):
    monkeypatch.setattr(data, "_ist_today", lambda: date(2025, 1, 2))
    jan1_1500_ist = JAN1_UTC_MIDNIGHT + 15 * 3600 - 19800
    broker(_daily_answer("2025-01-01"), _quote_traded_at(jan1_1500_ist))

    frame = data.BrokerData(AUTH).get_history(
        "BANKNIFTY29JAN25FUT", "NFO", "D", "2025-01-01", "2025-01-02"
    )

    assert frame["timestamp"].tolist() == [JAN1_UTC_MIDNIGHT]


def test_a_daily_series_that_reaches_today_asks_for_no_quote(broker, monkeypatch):
    monkeypatch.setattr(data, "_ist_today", lambda: date(2025, 1, 2))
    fake = broker(_daily_answer("2025-01-01", "2025-01-02"))

    data.BrokerData(AUTH).get_history("BANKNIFTY29JAN25FUT", "NFO", "D", "2025-01-01", "2025-01-02")

    assert [c.path for c in fake.calls] == ["/api/data/v1/historical"]
