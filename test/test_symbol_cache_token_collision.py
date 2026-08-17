"""
Regression tests for #1774 / #1778: BrokerSymbolCache's primary store must be
keyed by (exchange, token), not token alone, since broker tokens are only
unique within an exchange. AliceBlue (and other Noren-family brokers) issue
small integers on both NSE and CDS, so a token-only key silently drops one
row per collision on every load.

These tests build a synthetic fixture rather than relying on live data,
because the collision is intermittent - CDS recycles token slots as
contracts expire, so a clean install on a given day proves nothing.

No real DB or Flask app context is used: SymToken.query.all() is monkeypatched
to return lightweight stub rows, and each test builds its own
BrokerSymbolCache() instance rather than using the get_cache() singleton, so
tests stay fast and isolated.
"""

from types import SimpleNamespace

import pytest

from database.token_db_enhanced import BrokerSymbolCache


def make_row(symbol, exchange, token, brsymbol=None, name=None, brexchange=None,
             expiry=None, strike=None, lotsize=1, instrumenttype=None,
             tick_size=0.05, underlying=None):
    """Build a stub row matching the attributes load_all_symbols() reads off
    a SymToken ORM object."""
    return SimpleNamespace(
        symbol=symbol,
        brsymbol=brsymbol or symbol,
        name=name or symbol,
        exchange=exchange,
        brexchange=brexchange or exchange,
        token=token,
        expiry=expiry,
        strike=strike,
        lotsize=lotsize,
        instrumenttype=instrumenttype,
        tick_size=tick_size,
        underlying=underlying,
    )


class FakeQuery:
    """Stand-in for the Flask-SQLAlchemy query object returned by
    SymToken.query - only .all() is needed here."""

    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


def patch_symtoken(monkeypatch, rows):
    """Patch database.symbol.SymToken.query.all() to return the given stub
    rows, without touching a real database."""
    from database.symbol import SymToken

    monkeypatch.setattr(SymToken, "query", FakeQuery(rows))


def test_colliding_tokens_across_exchanges_both_survive(monkeypatch):
    """The exact #1774 scenario: NSE RELIANCE (token 2885) and a CDS option
    contract that happens to share token 2885. Both must be present after
    load - this is the core of the fix."""
    rows = [
        make_row("RELIANCE", "NSE", "2885"),
        make_row("USDINR28SEP26100.25PE", "CDS", "2885"),
        make_row("INFY", "NSE", "1594"),
        make_row("GBPINR21AUG26121.75PE", "CDS", "1594"),
    ]
    patch_symtoken(monkeypatch, rows)

    cache = BrokerSymbolCache()
    ok = cache.load_all_symbols("test_broker")

    assert ok is True
    assert len(cache.symbols) == 4
    assert ("NSE", "2885") in cache.symbols
    assert ("CDS", "2885") in cache.symbols
    assert cache.symbols[("NSE", "2885")].symbol == "RELIANCE"
    assert cache.symbols[("CDS", "2885")].symbol == "USDINR28SEP26100.25PE"


def test_unfiltered_search_returns_recovered_nse_row(monkeypatch):
    """Reproduces the reported symptom: /trading search with no exchange
    filter must return the NSE row, not just the CDS row that used to win
    the overwrite."""
    rows = [
        make_row("RELIANCE", "NSE", "2885"),
        make_row("USDINR28SEP26100.25PE", "CDS", "2885"),
    ]
    patch_symtoken(monkeypatch, rows)

    cache = BrokerSymbolCache()
    cache.load_all_symbols("test_broker")

    results = cache.search_symbols("RELIANCE", exchange=None, limit=500)
    exchanges = [(r.symbol, r.exchange) for r in results]
    assert ("RELIANCE", "NSE") in exchanges


def test_recovered_row_ranks_first_not_just_present(monkeypatch):
    """search_symbols scores and ranks rather than returning in iteration
    order. An exact match (score 0) must outrank longer, unrelated symbols
    even when the colliding equity is the FIRST row loaded (the harder case:
    a naive fix could pass by coincidence of load order) and even with
    several competing partial matches also in the cache."""
    rows = [
        make_row("RELIANCE", "NSE", "2885"),                   # exact match, loaded FIRST
        make_row("USDINR28SEP26100.25PE", "CDS", "2885"),       # collides on token
        make_row("RELIANCEPOWER", "NSE", "3001"),                # partial match, longer
        make_row("RELIANCE-BE", "BSE", "3002"),                  # partial match, longer
        make_row("HDFCRELIANCEFUND", "NSE", "3003"),              # partial match, contains term
    ]
    patch_symtoken(monkeypatch, rows)

    cache = BrokerSymbolCache()
    cache.load_all_symbols("test_broker")

    results = cache.search_symbols("RELIANCE", exchange=None, limit=500)
    assert results[0].symbol == "RELIANCE"
    assert results[0].exchange == "NSE"
    assert len(results) >= 4, "all partial and exact matches should be present"


def test_scoped_indexes_unaffected_by_collision(monkeypatch):
    """by_symbol_exchange / by_token_exchange are already correctly keyed
    and must resolve both sides of a collision independently, matching the
    original bug report's explanation of why exchange-filtered search was
    never broken."""
    rows = [
        make_row("RELIANCE", "NSE", "2885"),
        make_row("USDINR28SEP26100.25PE", "CDS", "2885"),
    ]
    patch_symtoken(monkeypatch, rows)

    cache = BrokerSymbolCache()
    cache.load_all_symbols("test_broker")

    assert cache.get_token("RELIANCE", "NSE") == "2885"
    assert cache.get_symbol("2885", "NSE") == "RELIANCE"
    assert cache.get_symbol("2885", "CDS") == "USDINR28SEP26100.25PE"


def test_non_colliding_set_all_rows_present_and_ordered(monkeypatch):
    """For a broker with no collisions, (exchange, token) and token are in
    1:1 correspondence, so nothing about search results should change."""
    rows = [
        make_row("RELIANCE", "NSE", "2885"),
        make_row("INFY", "NSE", "1594"),
        make_row("TCS", "NSE", "11536"),
    ]
    patch_symtoken(monkeypatch, rows)

    cache = BrokerSymbolCache()
    cache.load_all_symbols("test_broker")

    assert len(cache.symbols) == 3
    results = cache.search_symbols("RELIANCE", exchange=None, limit=500)
    assert results[0].symbol == "RELIANCE"



def test_search_symbols_unaffected_results_keep_exact_order(monkeypatch):
    """Regression guard for #1778: the exchange/token key change must not
    alter the ordered results for inputs unaffected by token collisions."""
    rows = [
        make_row("NIFTY", "NSE", "1001"),
        make_row("NIFTY50", "NSE", "1002"),
        make_row("NIFTYBEES", "NSE", "1003"),
        make_row("BANKNIFTY", "NSE", "1004"),
        make_row("NIFTYALPHA", "NSE", "1005"),
    ]
    patch_symtoken(monkeypatch, rows)

    cache = BrokerSymbolCache()
    cache.load_all_symbols("test_broker")

    results = cache.search_symbols("NIFTY", exchange=None, limit=500)
    actual = [(r.symbol, r.exchange) for r in results]

    expected = [
        ("NIFTY", "NSE"),
        ("NIFTY50", "NSE"),
        ("NIFTYBEES", "NSE"),
        ("NIFTYALPHA", "NSE"),
        ("BANKNIFTY", "NSE"),
    ]
    assert actual == expected


def test_fno_search_symbols_unaffected_results_keep_exact_order(monkeypatch):
    """Regression guard for #1778: FNO search ordering must remain unchanged
    for inputs unaffected by the exchange/token collision fix."""
    rows = [
        make_row(
            "NIFTY26SEP26000CE", "NFO", "2001",
            expiry="26-SEP-26", strike=26000, instrumenttype="CE",
            underlying="NIFTY",
        ),
        make_row(
            "NIFTY26SEP25500CE", "NFO", "2002",
            expiry="26-SEP-26", strike=25500, instrumenttype="CE",
            underlying="NIFTY",
        ),
        make_row(
            "BANKNIFTY26SEP55000CE", "NFO", "2003",
            expiry="26-SEP-26", strike=55000, instrumenttype="CE",
            underlying="BANKNIFTY",
        ),
        make_row(
            "NIFTY26SEP25000PE", "NFO", "2004",
            expiry="26-SEP-26", strike=25000, instrumenttype="PE",
            underlying="NIFTY",
        ),
    ]
    patch_symtoken(monkeypatch, rows)

    cache = BrokerSymbolCache()
    cache.load_all_symbols("test_broker")

    results = cache.fno_search_symbols(
        query="NIFTY",
        exchange="NFO",
        expiry="26-SEP-26",
        limit=500,
    )
    actual = [(r.symbol, r.exchange) for r in results]

    expected = [
        ("NIFTY26SEP25000PE", "NFO"),
        ("NIFTY26SEP25500CE", "NFO"),
        ("NIFTY26SEP26000CE", "NFO"),
        ("BANKNIFTY26SEP55000CE", "NFO"),
    ]
    assert actual == expected

def test_load_mismatch_detected_and_logged(monkeypatch, caplog):
    """A genuine duplicate (exchange, token) pair - which should not occur
    post-fix but guards against a future regression or a broker issuing
    duplicate tokens within a single exchange - must be counted and logged,
    not silently absorbed the way #1774 was."""
    rows = [
        make_row("RELIANCE", "NSE", "2885"),
        make_row("RELIANCE_DUP", "NSE", "2885"),  # same (exchange, token)
    ]
    patch_symtoken(monkeypatch, rows)

    cache = BrokerSymbolCache()
    import logging
    with caplog.at_level(logging.ERROR):
        cache.load_all_symbols("test_broker")

    assert cache._last_load_row_count == 2
    assert cache._last_load_cache_count == 1
    assert "Symbol cache load mismatch" in caplog.text


def test_load_no_mismatch_not_logged(monkeypatch, caplog):
    """Clean load: counts match, nothing logged at ERROR level."""
    rows = [
        make_row("RELIANCE", "NSE", "2885"),
        make_row("INFY", "NSE", "1594"),
    ]
    patch_symtoken(monkeypatch, rows)

    cache = BrokerSymbolCache()
    import logging
    with caplog.at_level(logging.ERROR):
        cache.load_all_symbols("test_broker")

    assert cache._last_load_row_count == cache._last_load_cache_count == 2
    assert "Symbol cache load mismatch" not in caplog.text


def test_get_cache_info_reports_load_counts(monkeypatch):
    """get_cache_info() / get_cache_stats() / the /api/cache/status endpoint
    all forward these fields - verify the dict shape directly."""
    rows = [
        make_row("RELIANCE", "NSE", "2885"),
        make_row("USDINR28SEP26100.25PE", "CDS", "2885"),
    ]
    patch_symtoken(monkeypatch, rows)

    cache = BrokerSymbolCache()
    cache.load_all_symbols("test_broker")

    info = cache.get_cache_info()
    assert info["load_row_count"] == 2
    assert info["load_cache_count"] == 2
    assert info["load_mismatch"] is False

def test_by_token_and_get_symbol_data_removed():
    """Regression guard for #1778: by_token / get_symbol_data() were removed
    because they're keyed by token alone and reintroduce the exact
    cross-exchange ambiguity #1774 fixed. Fails loudly if either returns."""
    cache = BrokerSymbolCache()
    assert not hasattr(cache, "by_token"), (
        "self.by_token was removed in #1778 - token-only lookups are "
        "ambiguous across exchanges. Do not reintroduce it."
    )
    assert not hasattr(cache, "get_symbol_data"), (
        "get_symbol_data() was removed in #1778 for the same reason. "
        "Use get_symbol_info(symbol, exchange) or get_symbol(token, exchange)."
    )


def test_load_mismatch_message_survives_real_filter_and_json_formatter():
    """Regression for #1798: the reviewer reproduced a TypeError because the
    mismatch log used %d placeholders while SensitiveDataFilter can stringify
    arguments during redaction. This drives the exact message text through the
    real filter and the real JSONErrorFormatter (the errors.jsonl sink), not a
    bare logger.error() call, so a future placeholder mismatch fails here
    instead of silently vanishing from the log file again.
    """
    import json
    import logging

    from utils.logging import JSONErrorFormatter, SensitiveDataFilter

    record = logging.LogRecord(
        "database.token_db_enhanced",
        logging.ERROR,
        __file__,
        1,
        "Symbol cache load mismatch for broker=%s: read %s rows "
        "from symtoken but primary cache holds %s entries (%s "
        "lost). This means duplicate (exchange, token) pairs "
        "exist in the master contract for this broker.",
        ("aliceblue", 1000, 998, 2),
        None,
    )

    assert SensitiveDataFilter().filter(record) is True

    formatted = record.getMessage()
    assert "broker=aliceblue" in formatted
    assert "read 1000 rows" in formatted
    assert "holds 998 entries" in formatted
    assert "(2 lost)" in formatted

    json_output = JSONErrorFormatter().format(record)
    payload = json.loads(json_output)
    assert "1000" in payload["message"]
    assert "998" in payload["message"]
    assert payload["level"] == "ERROR"


def test_cache_status_endpoint_reports_load_counts(monkeypatch):
    """Kalaiviswa's ask on #1798: confirm /api/cache/status exposes
    load_row_count, load_cache_count and load_mismatch end-to-end through
    the actual Flask route, not just the dict returned by get_cache_info()."""
    import sys

    import utils.session as us

    monkeypatch.setattr(us, "check_session_validity", lambda f: f)
    for module in list(sys.modules):
        if module == "blueprints.master_contract_status":
            del sys.modules[module]

    import blueprints.master_contract_status as status_bp_module

    rows = [
        make_row("RELIANCE", "NSE", "2885"),
        make_row("USDINR28SEP26100.25PE", "CDS", "2885"),
    ]
    patch_symtoken(monkeypatch, rows)

    cache = BrokerSymbolCache()
    cache.load_all_symbols("test_broker")

    import database.token_db_enhanced as tde
    monkeypatch.setattr(tde, "_cache_instance", cache)

    from flask import Flask

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(status_bp_module.master_contract_status_bp)

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["broker"] = "test_broker"

    response = client.get("/api/cache/status")
    assert response.status_code == 200

    payload = response.get_json()
    assert "load_row_count" in payload
    assert "load_cache_count" in payload
    assert "load_mismatch" in payload
    assert payload["load_row_count"] == 2
    assert payload["load_cache_count"] == 2
    assert payload["load_mismatch"] is False
