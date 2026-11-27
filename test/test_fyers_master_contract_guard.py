"""A failed Fyers download must leave the existing symbols alone.

master_contract_download() called download_csv_fyers_data() and then deleted
symtoken unconditionally. That download catches every per-file network error
and reports it in its return value instead of raising, so the surrounding
try/except never saw a failure: the table was emptied, parsing then failed on
files that were never written, and the instance was left with no symbols at
all (issue #2099). Nothing resolves until a later download happens to succeed,
so a transient outage becomes an outage of every symbol lookup.

Everything the function touches is replaced, so no network, database or Fyers
account is involved.
"""

import pandas as pd
import pytest

import broker.fyers.database.master_contract_db as mcd

FRAME = pd.DataFrame([{"symbol": "SBIN", "exchange": "NSE", "token": "1"}])


class Spy:
    """Records whether the table was emptied and what the UI was told."""

    def __init__(self):
        self.deleted = 0
        self.copied = 0
        self.emitted = []

    def emit(self, event, payload):
        self.emitted.append((event, payload))
        return payload

    @property
    def status(self):
        return self.emitted[-1][1]["status"]

    @property
    def message(self):
        return self.emitted[-1][1]["message"]


@pytest.fixture
def spy(monkeypatch):
    s = Spy()
    monkeypatch.setattr(mcd, "socketio", s)

    def replace(frames):
        s.deleted += 1
        s.copied += len(frames)

    monkeypatch.setattr(mcd, "replace_symtoken_table", replace)
    monkeypatch.setattr(mcd, "delete_fyers_temp_data", lambda path: None)
    for name in (
        "process_fyers_nse_csv",
        "process_fyers_bse_csv",
        "process_fyers_bfo_csv",
        "process_fyers_nfo_csv",
        "process_fyers_cds_json",
        "process_fyers_mcx_json",
    ):
        monkeypatch.setattr(mcd, name, lambda path: FRAME.copy())
    return s


def set_download(monkeypatch, result):
    monkeypatch.setattr(mcd, "download_csv_fyers_data", lambda path: result)


def test_a_failed_download_keeps_the_existing_symbols(spy, monkeypatch):
    set_download(monkeypatch, (False, [], "Request error occurred while downloading NSE_CM"))

    with pytest.raises(RuntimeError):
        mcd.master_contract_download()

    assert spy.deleted == 0
    assert spy.copied == 0
    assert spy.status == "error"


def test_a_partial_download_also_keeps_them(spy, monkeypatch):
    """Five of six files is still not a contract worth replacing six with."""
    set_download(monkeypatch, (False, ["tmp/NSE_CM.csv"] * 5, "HTTP error 503 downloading MCX_COM"))

    with pytest.raises(RuntimeError):
        mcd.master_contract_download()

    assert spy.deleted == 0
    assert spy.copied == 0


def test_the_failure_says_what_went_wrong(spy, monkeypatch):
    set_download(monkeypatch, (False, [], "HTTP error 503 downloading MCX_COM"))

    with pytest.raises(RuntimeError):
        mcd.master_contract_download()

    assert "503" in spy.message
    assert "keeping the existing symbols" in spy.message


def test_a_good_download_still_replaces_the_table(spy, monkeypatch):
    """The fix must not stop the normal path from refreshing symbols."""
    set_download(monkeypatch, (True, ["tmp/NSE_CM.csv"] * 6, None))

    mcd.master_contract_download()

    assert spy.deleted == 1
    assert spy.copied == 6
    assert spy.status == "success"


def test_a_file_that_cannot_be_parsed_keeps_them_and_raises(spy, monkeypatch):
    """A file that downloaded but cannot be read is no better than a missing one."""
    set_download(monkeypatch, (True, ["tmp/NSE_CM.csv"] * 6, None))

    def broken(path):
        raise ValueError("unexpected columns in BSE_FO.csv")

    monkeypatch.setattr(mcd, "process_fyers_bfo_csv", broken)

    with pytest.raises(ValueError):
        mcd.master_contract_download()

    assert spy.deleted == 0
    assert spy.copied == 0
    assert spy.status == "error"


def test_a_segment_with_no_rows_keeps_them_and_raises(spy, monkeypatch):
    set_download(monkeypatch, (True, ["tmp/NSE_CM.csv"] * 6, None))
    monkeypatch.setattr(mcd, "process_fyers_cds_json", lambda path: pd.DataFrame())

    with pytest.raises(RuntimeError, match="CDS"):
        mcd.master_contract_download()

    assert spy.deleted == 0
    assert "existing symbols were kept" in spy.message


# --- the swap itself, on the conftest database --------------------------------


def db_row(symbol, token, exchange="NSE"):
    return {"symbol": symbol, "brsymbol": f"{exchange}:{symbol}", "name": symbol,
            "exchange": exchange, "brexchange": exchange, "token": token, "expiry": "",
            "strike": -1.0, "lotsize": 1, "instrumenttype": "EQ", "tick_size": 0.05}


@pytest.fixture
def table():
    mcd.init_db()
    mcd.SymToken.query.delete()
    mcd.db_session.bulk_insert_mappings(mcd.SymToken, [db_row("OLD1", "900001"), db_row("OLD2", "900002")])
    mcd.db_session.commit()
    yield
    mcd.SymToken.query.delete()
    mcd.db_session.commit()


def symbols():
    return sorted(r.symbol for r in mcd.SymToken.query.all())


def test_the_swap_replaces_every_segment(table):
    mcd.replace_symtoken_table([pd.DataFrame([db_row("NEW1", "1")]),
                                pd.DataFrame([db_row("NEW2", "2", "BSE")])])

    assert symbols() == ["NEW1", "NEW2"]


def test_a_failed_insert_rolls_back_to_the_old_symbols(table, monkeypatch):
    def fail_insert(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(mcd.db_session, "bulk_insert_mappings", fail_insert)

    with pytest.raises(RuntimeError, match="disk full"):
        mcd.replace_symtoken_table([pd.DataFrame([db_row("NEW1", "1")])])

    monkeypatch.undo()
    assert symbols() == ["OLD1", "OLD2"]


def test_a_token_already_taken_by_an_earlier_segment_is_dropped(table):
    mcd.replace_symtoken_table([pd.DataFrame([db_row("FIRST", "7")]),
                                pd.DataFrame([db_row("SECOND", "7", "BSE")])])

    assert symbols() == ["FIRST"]
