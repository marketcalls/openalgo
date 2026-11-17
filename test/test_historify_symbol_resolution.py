"""Historify bulk add takes the symbols a trader pastes, including - & and _.

OpenAlgo's NSE and BSE symbols keep the exchange's own spelling, hyphen and
ampersand included: BAJAJ-AUTO, M&M, J&KBANK. Those were always accepted.
Lists copied from elsewhere can carry them as an underscore (TradingView's
symbol is NSE:BAJAJ_AUTO, and its chart links write M_M), and such a list was
refused symbol by symbol while the page reported only how many were added.

Pinned here, against the service and a real DuckDB watchlist:

* hyphen and ampersand symbols are added as written;
* an underscore spelling is added under the one master contract symbol it
  stands for, and the response says which;
* a symbol as written always wins over a reading of its underscores, so a
  symbol that really contains one (a crypto pair) is never rewritten;
* an underscore that could stand for two existing symbols is refused rather
  than guessed;
* a series suffix is neither added nor dropped here: the symbol the master
  contract holds is the one that resolves (see test_zerodha_series_symbols.py
  for how the Zerodha master contract names those rows);
* every refused symbol comes back with its reason.
"""

from __future__ import annotations

import duckdb
import pytest

from database import historify_db
from services import historify_service

# The master contract the tests run against: what get_symbol_info would find.
MASTER = {
    ("M&M", "NSE"),
    ("M&MFIN", "NSE"),
    ("BAJAJ-AUTO", "NSE"),
    ("J&KBANK", "NSE"),
    ("NAM-INDIA", "NSE"),
    ("RELIANCE", "NSE"),
    ("HFCL", "NSE"),
    # Both readings of A_B exist, so A_B is ambiguous.
    ("A-B", "NSE"),
    ("A&B", "NSE"),
    # A symbol that genuinely contains an underscore.
    ("BTC_INR", "CRYPTO"),
    ("BTC-INR", "CRYPTO"),
}


@pytest.fixture(autouse=True)
def master(monkeypatch):
    lookups = []

    def fake_get_symbol_info(symbol, exchange):
        lookups.append((symbol, exchange))
        return object() if (symbol, exchange) in MASTER else None

    monkeypatch.setattr(historify_service, "get_symbol_info", fake_get_symbol_info)
    monkeypatch.setattr(
        historify_service, "SUPPORTED_EXCHANGES", [*historify_service.SUPPORTED_EXCHANGES, "CRYPTO"]
    )
    return lookups


@pytest.fixture
def db_path(monkeypatch, tmp_path):
    path = tmp_path / "historify.duckdb"
    monkeypatch.setattr(historify_db, "HISTORIFY_DB_PATH", str(path))
    historify_db.init_database()
    return path


def _watchlist(path):
    conn = duckdb.connect(str(path), read_only=True)
    try:
        return sorted(conn.execute("SELECT symbol, exchange FROM watchlist").fetchall())
    finally:
        conn.close()


@pytest.mark.parametrize("symbol", ["M&M", "BAJAJ-AUTO", "J&KBANK", "NAM-INDIA", "m&m", "HFCL"])
def test_master_contract_symbols_resolve_as_written(symbol):
    assert historify_service.resolve_symbol(symbol, "NSE") == (symbol.upper(), "")


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("M_M", "M&M"),
        ("M_MFIN", "M&MFIN"),
        ("BAJAJ_AUTO", "BAJAJ-AUTO"),
        ("J_KBANK", "J&KBANK"),
        ("nam_india", "NAM-INDIA"),
    ],
)
def test_underscore_spelling_resolves_to_the_master_contract_symbol(typed, expected):
    assert historify_service.resolve_symbol(typed, "NSE") == (expected, "")


def test_a_symbol_that_exists_as_written_is_never_rewritten(master):
    assert historify_service.resolve_symbol("BTC_INR", "CRYPTO") == ("BTC_INR", "")
    # Found on the first lookup: no reading of the underscore was tried.
    assert master == [("BTC_INR", "CRYPTO")]


def test_a_series_suffix_is_not_dropped_to_find_a_symbol():
    # HFCL exists; HFCL-BE does not. Shortening it would be a guess.
    resolved, error = historify_service.resolve_symbol("HFCL-BE", "NSE")
    assert resolved is None
    assert "not found" in error


def test_an_underscore_with_two_readings_is_refused_not_guessed():
    resolved, error = historify_service.resolve_symbol("A_B", "NSE")
    assert resolved is None
    assert "A-B" in error and "A&B" in error


def test_an_unknown_symbol_is_refused_with_a_reason():
    resolved, error = historify_service.resolve_symbol("NOSUCH_SYMBOL", "NSE")
    assert resolved is None
    assert "not found" in error


def test_bulk_add_stores_master_contract_symbols_and_reports_every_refusal(db_path):
    pasted = ["M&M", "BAJAJ-AUTO", "M_M", "J_KBANK", "A_B", "NOSUCH", "RELIANCE"]
    ok, resp, status = historify_service.bulk_add_to_watchlist(
        [{"symbol": s, "exchange": "NSE"} for s in pasted]
    )

    assert ok and status == 200
    # M_M resolves to M&M, already in this batch, so it is skipped, not doubled.
    assert resp["added"] == 4
    assert resp["skipped"] == 1
    assert resp["renamed"] == [
        {"from": "M_M", "to": "M&M", "exchange": "NSE"},
        {"from": "J_KBANK", "to": "J&KBANK", "exchange": "NSE"},
    ]
    assert sorted(f["symbol"] for f in resp["failed"]) == ["A_B", "NOSUCH"]
    assert all(f["error"] for f in resp["failed"])
    assert _watchlist(db_path) == [
        ("BAJAJ-AUTO", "NSE"),
        ("J&KBANK", "NSE"),
        ("M&M", "NSE"),
        ("RELIANCE", "NSE"),
    ]


def test_single_add_stores_the_master_contract_symbol(db_path):
    ok, resp, status = historify_service.add_to_watchlist("BAJAJ_AUTO", "NSE")
    assert ok and status == 200
    assert _watchlist(db_path) == [("BAJAJ-AUTO", "NSE")]


def test_a_failed_write_is_reported_as_an_error_not_a_symbol(db_path, monkeypatch):
    monkeypatch.setattr(
        historify_service,
        "db_bulk_add_to_watchlist",
        lambda symbols: (0, 0, [{"symbol": "batch", "exchange": "", "error": "disk full"}]),
    )
    ok, resp, status = historify_service.bulk_add_to_watchlist(
        [{"symbol": "RELIANCE", "exchange": "NSE"}]
    )
    assert not ok and status == 500
    assert resp["status"] == "error"
    assert "batch" not in resp["message"]
