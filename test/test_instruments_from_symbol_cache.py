"""/api/v1/instruments serves the in-memory symbol cache when it is loaded (issue #2401).

Building the NFO list from the database took over a second for 90,000 rows,
which held the single worker and left every other page waiting.
"""

from types import SimpleNamespace
from unittest import mock

import pytest

import services.instruments_service as svc
from database.token_db_enhanced import _build_snapshot


def row(symbol, exchange, token, **extra):
    fields = {
        "symbol": symbol,
        "brsymbol": f"{symbol}-BR",
        "name": symbol[:5],
        "exchange": exchange,
        "brexchange": exchange,
        "token": token,
        "expiry": None,
        "strike": None,
        "lotsize": 1,
        "instrumenttype": "EQ",
        "tick_size": 0.05,
    }
    fields.update(extra)
    return SimpleNamespace(**fields)


ROWS = [
    row("SBIN", "NSE", "3045"),
    row(
        "NIFTY27NOV2626000CE",
        "NFO",
        "50001",
        expiry="27-NOV-26",
        strike=26000.0,
        lotsize=75,
        instrumenttype="CE",
    ),
    row("RELIANCE", "NSE", "2885"),
    row(
        "NIFTY27NOV2626000PE",
        "NFO",
        "50002",
        expiry="27-NOV-26",
        strike=26000.0,
        lotsize=75,
        instrumenttype="PE",
    ),
]


@pytest.fixture(autouse=True)
def api_key():
    with mock.patch.object(svc, "verify_api_key", return_value="trader"):
        yield


@pytest.fixture
def cached():
    snap = _build_snapshot(ROWS, "zerodha")
    cache = SimpleNamespace(valid_snapshot=lambda: snap)
    with (
        mock.patch.object(svc, "get_cache", return_value=cache),
        mock.patch.object(svc, "SymToken") as symtoken,
    ):
        yield symtoken


@pytest.fixture
def uncached():
    cache = SimpleNamespace(valid_snapshot=lambda: None)
    query = mock.Mock()
    query.filter.return_value = query
    with (
        mock.patch.object(svc, "get_cache", return_value=cache),
        mock.patch.object(svc, "SymToken") as symtoken,
    ):
        symtoken.query = query
        yield query


def expected(rows):
    return [{field: getattr(r, field) for field in svc.INSTRUMENT_FIELDS} for r in rows]


def test_exchange_request_is_served_from_the_cache_without_a_query(cached):
    ok, body, status, _ = svc.get_instruments(exchange="NFO", api_key="k")
    assert (ok, status) == (True, 200)
    assert body["data"] == expected([ROWS[1], ROWS[3]])
    assert body["message"] == "Found 2 instruments"
    cached.query.all.assert_not_called()
    cached.query.filter.assert_not_called()


def test_all_exchanges_are_served_from_the_cache(cached):
    ok, body, _, _ = svc.get_instruments(api_key="k")
    assert ok
    assert sorted(r["token"] for r in body["data"]) == ["2885", "3045", "50001", "50002"]
    cached.query.all.assert_not_called()


def test_unknown_exchange_from_the_cache_is_an_empty_success(cached):
    ok, body, status, _ = svc.get_instruments(exchange="MCX", api_key="k")
    assert (ok, status, body["data"]) == (True, 200, [])


def test_csv_from_the_cache_keeps_the_column_order(cached):
    ok, content, _, headers = svc.get_instruments(exchange="NSE", api_key="k", format="csv")
    assert ok
    lines = content.splitlines()
    assert lines[0] == ",".join(svc.INSTRUMENT_FIELDS)
    assert lines[1].startswith("SBIN,SBIN-BR,SBIN,NSE,NSE,3045")
    assert headers["Content-Disposition"].endswith("instruments_NSE.csv")


def test_falls_back_to_the_database_when_the_cache_is_not_loaded(uncached):
    uncached.all.return_value = [ROWS[0], ROWS[2]]
    ok, body, _, _ = svc.get_instruments(exchange="NSE", api_key="k")
    assert ok
    assert body["data"] == expected([ROWS[0], ROWS[2]])
    uncached.filter.assert_called_once()
    uncached.all.assert_called_once()


def test_cache_and_database_answers_match(cached):
    _, from_cache, _, _ = svc.get_instruments(exchange="NFO", api_key="k")
    query = mock.Mock()
    query.filter.return_value = query
    query.all.return_value = [ROWS[1], ROWS[3]]
    with mock.patch.object(
        svc, "get_cache", return_value=SimpleNamespace(valid_snapshot=lambda: None)
    ):
        cached.query = query
        _, from_db, _, _ = svc.get_instruments(exchange="NFO", api_key="k")
    assert from_cache == from_db
