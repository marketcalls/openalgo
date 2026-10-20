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
    monkeypatch.setattr(mcd, "delete_symtoken_table", lambda: setattr(s, "deleted", s.deleted + 1))
    monkeypatch.setattr(mcd, "copy_from_dataframe", lambda df: setattr(s, "copied", s.copied + 1))
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

    mcd.master_contract_download()

    assert spy.deleted == 0
    assert spy.copied == 0
    assert spy.status == "error"


def test_a_partial_download_also_keeps_them(spy, monkeypatch):
    """Five of six files is still not a contract worth replacing six with."""
    set_download(monkeypatch, (False, ["tmp/NSE_CM.csv"] * 5, "HTTP error 503 downloading MCX_COM"))

    mcd.master_contract_download()

    assert spy.deleted == 0
    assert spy.copied == 0


def test_the_failure_says_what_went_wrong(spy, monkeypatch):
    set_download(monkeypatch, (False, [], "HTTP error 503 downloading MCX_COM"))

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
