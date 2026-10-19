"""Adding a pasted list of symbols to a watchlist.

Three layers, each pinned on its own: how pasted text is split, how a name is
resolved to an instrument the broker has, and how the store accounts for every
row it was handed. The broker's master contract is replaced by a small fixed
set, so what is under test is the resolution order, not a live symbol file.
"""

import pytest

from database import watchlist_db as wl
from services import watchlist_service as svc

USER = "watchlist_bulk_test_user"

#: The instruments the fake broker knows.
KNOWN = {
    ("RELIANCE", "NSE"),
    ("RELIANCE", "BSE"),
    ("TCS", "NSE"),
    ("INFY", "NSE"),
    ("BSEONLY", "BSE"),
    ("NIFTY", "NSE_INDEX"),
    ("SENSEX", "BSE_INDEX"),
    ("BAJAJ-AUTO", "NSE"),
    ("M&M", "NSE"),
    ("NIFTY28OCT2625000CE", "NFO"),
}


@pytest.fixture
def broker(monkeypatch):
    """Answer token lookups from KNOWN, and record every batch asked for."""
    calls = []

    def fake_known(pairs):
        calls.append(list(pairs))
        return {pair for pair in pairs if pair in KNOWN}

    monkeypatch.setattr(svc, "_known_pairs", fake_known)
    return calls


@pytest.fixture
def clean_lists():
    wl.init_db()
    for row in wl.get_watchlists(USER):
        wl.delete_watchlist(USER, row["id"])
    yield
    for row in wl.get_watchlists(USER):
        wl.delete_watchlist(USER, row["id"])


# -- parsing -------------------------------------------------------------------


def test_splits_on_commas_semicolons_spaces_and_new_lines():
    text = "reliance, TCS;INFY\n\tSBIN  HDFCBANK"

    assert svc.parse_symbol_list(text) == ["RELIANCE", "TCS", "INFY", "SBIN", "HDFCBANK"]


def test_keeps_the_first_of_a_repeated_name_and_the_order_given():
    assert svc.parse_symbol_list("TCS,INFY,tcs,TCS") == ["TCS", "INFY"]


def test_drops_section_markers_and_quotes_from_a_spreadsheet_copy():
    text = "###BANKING,'HDFCBANK',\"ICICIBANK\",###IT,TCS"

    assert svc.parse_symbol_list(text) == ["HDFCBANK", "ICICIBANK", "TCS"]


def test_caps_the_number_of_names_one_paste_can_cause_lookups_for():
    text = ",".join(f"S{i}" for i in range(svc.MAX_TOKENS + 50))

    assert len(svc.parse_symbol_list(text)) == svc.MAX_TOKENS


def test_empty_or_separator_only_text_is_no_names():
    assert svc.parse_symbol_list("") == []
    assert svc.parse_symbol_list(" ,; \n") == []


# -- resolution ----------------------------------------------------------------


def test_a_bare_name_prefers_the_nse_listing(broker):
    found, not_found = svc.resolve_symbols(["RELIANCE"])

    assert found == [{"symbol": "RELIANCE", "exchange": "NSE"}]
    assert not_found == []


def test_a_bare_name_not_on_nse_falls_back_to_bse(broker):
    found, _ = svc.resolve_symbols(["BSEONLY"])

    assert found == [{"symbol": "BSEONLY", "exchange": "BSE"}]


def test_a_bare_index_name_resolves_to_its_index_exchange(broker):
    found, _ = svc.resolve_symbols(["NIFTY", "SENSEX"])

    assert found == [
        {"symbol": "NIFTY", "exchange": "NSE_INDEX"},
        {"symbol": "SENSEX", "exchange": "BSE_INDEX"},
    ]


def test_a_bare_derivative_resolves_to_its_segment(broker):
    found, _ = svc.resolve_symbols(["NIFTY28OCT2625000CE"])

    assert found == [{"symbol": "NIFTY28OCT2625000CE", "exchange": "NFO"}]


def test_an_exchange_prefix_is_honoured_over_the_default_order(broker):
    found, _ = svc.resolve_symbols(["BSE:RELIANCE"])

    assert found == [{"symbol": "RELIANCE", "exchange": "BSE"}]


def test_a_prefixed_index_is_found_under_the_index_exchange(broker):
    # Other charting platforms write the index as NSE:NIFTY.
    found, _ = svc.resolve_symbols(["NSE:NIFTY"])

    assert found == [{"symbol": "NIFTY", "exchange": "NSE_INDEX"}]


def test_an_underscore_is_read_as_a_hyphen_or_an_ampersand(broker):
    found, _ = svc.resolve_symbols(["NSE:BAJAJ_AUTO", "M_M"])

    assert found == [
        {"symbol": "BAJAJ-AUTO", "exchange": "NSE"},
        {"symbol": "M&M", "exchange": "NSE"},
    ]


def test_an_unknown_name_is_reported_as_the_user_wrote_it(broker):
    found, not_found = svc.resolve_symbols(["TCS", "XYZ123", "NSE:NOPE", "1X:TCS"])

    assert found == [{"symbol": "TCS", "exchange": "NSE"}]
    assert not_found == ["XYZ123", "NSE:NOPE", "1X:TCS"]


def test_two_spellings_of_one_instrument_are_returned_once(broker):
    found, not_found = svc.resolve_symbols(["INFY", "NSE:INFY"])

    assert found == [{"symbol": "INFY", "exchange": "NSE"}]
    assert not_found == []


def test_the_whole_paste_is_one_lookup(broker):
    svc.resolve_symbols(["RELIANCE", "TCS", "NIFTY", "XYZ"])

    assert len(broker) == 1


def test_a_failed_lookup_reports_every_name_rather_than_raising(monkeypatch):
    def broken(_pairs):
        raise RuntimeError("symbol cache unavailable")

    monkeypatch.setattr(svc, "_known_pairs", broken)

    assert svc.resolve_symbols(["TCS", "INFY"]) == ([], ["TCS", "INFY"])


# -- where the master contract is read from -------------------------------------


class _Cache:
    """Stands in for the broker symbol cache: loaded with an index, or not."""

    def __init__(self, index=None):
        self._snap = None if index is None else type("Snap", (), {"by_symbol_exchange": index})()

    def valid_snapshot(self):
        return self._snap


def test_a_loaded_cache_answers_without_touching_the_database(monkeypatch):
    monkeypatch.setattr(svc, "get_cache", lambda: _Cache({("TCS", "NSE"): object()}))

    # Any database read would now raise AttributeError on None.
    monkeypatch.setattr(svc, "SymToken", None)

    assert svc._known_pairs([("TCS", "NSE"), ("TCS", "BSE")]) == {("TCS", "NSE")}


@pytest.fixture
def master_contract():
    """A few rows in the test database's symbol table, removed afterwards."""
    from database import symbol as sym

    sym.init_db()
    rows = [
        sym.SymToken(symbol=s, brsymbol=s, exchange=e, brexchange=e, token=f"t-{s}-{e}")
        for s, e in [("WLTEST-A", "NSE"), ("WLTEST-B", "BSE"), ("WLTEST-IDX", "NSE_INDEX")]
    ]
    sym.db_session.add_all(rows)
    sym.db_session.commit()
    yield
    sym.SymToken.query.filter(sym.SymToken.symbol.like("WLTEST-%")).delete(
        synchronize_session=False
    )
    sym.db_session.commit()
    sym.db_session.remove()


def test_without_the_cache_the_database_is_read_in_batches(monkeypatch, master_contract):
    monkeypatch.setattr(svc, "get_cache", lambda: _Cache(None))

    # Enough names that the candidate pairs span more than one batch.
    filler = [f"WLTEST-NONE{i}" for i in range(40)]
    tokens = ["WLTEST-A", "WLTEST-B", "NSE:WLTEST-IDX", *filler]
    assert len(tokens) * len(svc.BARE_ORDER) > svc._DB_BATCH

    from sqlalchemy import event

    from database import symbol as sym

    statements = []

    def count(_conn, _cursor, statement, *_rest):
        if "symtoken" in statement.lower():
            statements.append(statement)

    event.listen(sym.engine, "before_cursor_execute", count)
    try:
        found, not_found = svc.resolve_symbols(tokens)
    finally:
        event.remove(sym.engine, "before_cursor_execute", count)

    # One query per batch, not one per candidate pair: that fallback was
    # hundreds of queries on the single worker for an ordinary paste.
    pairs = sum(len(svc._candidates(token)) for token in tokens)
    assert len(statements) == -(-pairs // svc._DB_BATCH)
    assert found == [
        {"symbol": "WLTEST-A", "exchange": "NSE"},
        {"symbol": "WLTEST-B", "exchange": "BSE"},
        {"symbol": "WLTEST-IDX", "exchange": "NSE_INDEX"},
    ]
    assert not_found == filler


# -- the store -----------------------------------------------------------------


def test_add_items_appends_in_order_after_what_is_there(clean_lists):
    lst = wl.create_watchlist(USER, "Main", [{"symbol": "RELIANCE", "exchange": "NSE"}])

    result = wl.add_items(
        USER,
        lst["id"],
        [{"symbol": "TCS", "exchange": "NSE"}, {"symbol": "INFY", "exchange": "NSE"}],
    )

    assert [r["symbol"] for r in result["added"]] == ["TCS", "INFY"]
    items = wl.get_watchlists(USER)[0]["items"]
    assert [i["symbol"] for i in items] == ["RELIANCE", "TCS", "INFY"]
    assert [i["position"] for i in items] == [0, 1, 2]


def test_add_items_accounts_for_a_row_already_in_the_list(clean_lists):
    lst = wl.create_watchlist(USER, "Main", [{"symbol": "TCS", "exchange": "NSE"}])

    result = wl.add_items(
        USER,
        lst["id"],
        [{"symbol": "TCS", "exchange": "NSE"}, {"symbol": "INFY", "exchange": "NSE"}],
    )

    assert result["added"] == [{"symbol": "INFY", "exchange": "NSE"}]
    assert result["existing"] == [{"symbol": "TCS", "exchange": "NSE"}]
    assert len(wl.get_watchlists(USER)[0]["items"]) == 2


def test_add_items_stops_at_the_list_cap_and_says_which_were_refused(clean_lists, monkeypatch):
    monkeypatch.setattr(wl, "MAX_ITEMS_PER_LIST", 3)
    lst = wl.create_watchlist(USER, "Main", [{"symbol": "TCS", "exchange": "NSE"}])

    rows = [{"symbol": s, "exchange": "NSE"} for s in ("A", "B", "C", "D")]
    result = wl.add_items(USER, lst["id"], rows)

    assert [r["symbol"] for r in result["added"]] == ["A", "B"]
    assert [r["symbol"] for r in result["over_limit"]] == ["C", "D"]
    assert len(wl.get_watchlists(USER)[0]["items"]) == 3


def test_add_items_refuses_a_list_that_belongs_to_nobody_here(clean_lists):
    assert wl.add_items(USER, 999999, [{"symbol": "TCS", "exchange": "NSE"}]) is None
