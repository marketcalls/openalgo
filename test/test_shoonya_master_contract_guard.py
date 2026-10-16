"""A failed Shoonya refresh must leave the existing symbols alone.

download_and_unzip_shoonya_data() caught and logged every per-file failure
and returned normally, and master_contract_download() then emptied symtoken
and loaded what had arrived. A failed download left the instance without
that segment's symbols, or with none at all once processing failed on the
missing file, and the shared caller recorded the run as a success
(issue #2099).

The network and the Shoonya parsers are replaced; the symtoken table is the
test database from conftest, so the keep-or-replace outcome is checked on
real rows.
"""

import io
import zipfile

import pandas as pd
import pytest

import broker.shoonya.database.master_contract_db as mcd

PROCESSORS = (
    "process_shoonya_nse_data",
    "process_shoonya_bse_data",
    "process_shoonya_nfo_data",
    "process_shoonya_cds_data",
    "process_shoonya_mcx_data",
    "process_shoonya_bfo_data",
)


def row(symbol, token, exchange="NSE"):
    return {
        "symbol": symbol,
        "brsymbol": symbol,
        "name": symbol,
        "exchange": exchange,
        "brexchange": exchange,
        "token": token,
        "expiry": "",
        "strike": -1.0,
        "lotsize": 1,
        "instrumenttype": "EQ",
        "tick_size": 0.05,
    }


def zipped(name):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr(name, "Exchange,Token\nNSE,1\n")
    return buffer.getvalue()


class Response:
    def __init__(self, status_code, content=b""):
        self.status_code = status_code
        self.content = content


def serve(fail=(), corrupt=()):
    """A requests.get that answers every Shoonya URL except those named."""
    urls = {url: key for key, url in mcd.shoonya_urls.items()}

    def get(url, timeout=None):
        key = urls[url]
        if key in fail:
            return Response(503)
        if key in corrupt:
            return Response(200, b"<html>not a zip</html>")
        return Response(200, zipped(f"{key}_symbols.txt"))

    return get


class Socket:
    def __init__(self):
        self.emitted = []

    def emit(self, event, payload):
        self.emitted.append((event, payload))
        return payload


@pytest.fixture
def shoonya(monkeypatch, tmp_path):
    mcd.init_db()
    mcd.SymToken.query.delete()
    mcd.db_session.bulk_insert_mappings(
        mcd.SymToken, [row("OLD1", "900001"), row("OLD2", "900002")]
    )
    mcd.db_session.commit()

    socket = Socket()
    monkeypatch.setattr(mcd, "socketio", socket)
    monkeypatch.setattr(mcd.requests, "get", serve())
    for i, name in enumerate(PROCESSORS):
        frame = pd.DataFrame([row(f"NEW{i}", str(100 + i))])
        monkeypatch.setattr(mcd, name, lambda path, frame=frame: frame.copy())
    monkeypatch.chdir(tmp_path)

    yield socket

    mcd.SymToken.query.delete()
    mcd.db_session.commit()


def symbols():
    return sorted(r.symbol for r in mcd.SymToken.query.all())


def test_one_failed_file_keeps_every_existing_symbol(shoonya, monkeypatch):
    monkeypatch.setattr(mcd.requests, "get", serve(fail={"MCX"}))

    with pytest.raises(RuntimeError, match="MCX"):
        mcd.master_contract_download()

    assert symbols() == ["OLD1", "OLD2"]
    assert shoonya.emitted[-1][1]["status"] == "error"
    assert "existing symbols were kept" in shoonya.emitted[-1][1]["message"]


def test_a_file_that_is_not_a_zip_keeps_them(shoonya, monkeypatch):
    monkeypatch.setattr(mcd.requests, "get", serve(corrupt={"NFO"}))

    with pytest.raises(RuntimeError, match="NFO"):
        mcd.master_contract_download()

    assert symbols() == ["OLD1", "OLD2"]


def test_a_network_error_keeps_them(shoonya, monkeypatch):
    def down(url, timeout=None):
        raise ConnectionError("network unreachable")

    monkeypatch.setattr(mcd.requests, "get", down)

    with pytest.raises(RuntimeError):
        mcd.master_contract_download()

    assert symbols() == ["OLD1", "OLD2"]


def test_a_file_that_fails_to_parse_keeps_them(shoonya, monkeypatch):
    def broken(path):
        raise KeyError("TradingSymbol")

    monkeypatch.setattr(mcd, "process_shoonya_cds_data", broken)

    with pytest.raises(KeyError):
        mcd.master_contract_download()

    assert symbols() == ["OLD1", "OLD2"]


def test_a_file_with_no_rows_keeps_them(shoonya, monkeypatch):
    monkeypatch.setattr(mcd, "process_shoonya_bse_data", lambda path: pd.DataFrame())

    with pytest.raises(RuntimeError, match="BSE"):
        mcd.master_contract_download()

    assert symbols() == ["OLD1", "OLD2"]


def test_a_failed_insert_rolls_back_to_the_old_symbols(shoonya, monkeypatch):
    def fail_insert(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(mcd.db_session, "bulk_insert_mappings", fail_insert)

    with pytest.raises(RuntimeError, match="disk full"):
        mcd.master_contract_download()

    monkeypatch.undo()
    assert symbols() == ["OLD1", "OLD2"]


def test_a_good_refresh_still_replaces_the_table(shoonya):
    """The guard must not stop the normal path from refreshing symbols."""
    mcd.master_contract_download()

    assert symbols() == [f"NEW{i}" for i in range(6)]
    assert shoonya.emitted[-1][1]["status"] == "success"


def test_the_same_token_on_two_exchanges_keeps_both_rows(shoonya, monkeypatch):
    """Dedup is per (token, exchange), as the old per-segment inserts were."""
    monkeypatch.setattr(
        mcd, "process_shoonya_bse_data", lambda path: pd.DataFrame([row("BSEROW", "100", "BSE")])
    )

    mcd.master_contract_download()

    assert "BSEROW" in symbols() and "NEW0" in symbols()


def test_files_stay_out_of_the_shared_tmp_folder(shoonya, tmp_path):
    """Zebu and TradeSmart write files with the same names into tmp/."""
    (tmp_path / "tmp").mkdir()
    other = tmp_path / "tmp" / "NSE_symbols.txt"
    other.write_text("another broker's file")

    mcd.master_contract_download()

    assert other.read_text() == "another broker's file"
