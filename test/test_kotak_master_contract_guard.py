"""A failed Kotak refresh must leave the existing symbols alone.

master_contract_download() went ahead as long as at least one segment file
downloaded: it emptied symtoken, skipped the files that were missing, and
logged-and-skipped any segment that failed to parse. One failed download or
one bad file silently dropped that segment's symbols, and a refresh where
every segment failed parsing left the table empty (issue #2099). The failure
was also reported to the shared caller as a success.

The network and the Kotak parsers are replaced; the symtoken table is the
test database from conftest, so the keep-or-replace outcome is checked on
real rows.
"""

import pandas as pd
import pytest

import broker.kotak.database.master_contract_db as mcd

SEGMENTS = mcd.REQUIRED_SEGMENTS
URLS = {key: f"https://kotak.test/{key.lower()}.csv" for key in SEGMENTS}
PROCESSORS = (
    "process_kotak_nse_csv",
    "process_kotak_nfo_csv",
    "process_kotak_bse_csv",
    "process_kotak_cds_csv",
    "process_kotak_mcx_csv",
    "process_kotak_bfo_csv",
)


def row(symbol, token):
    return {
        "symbol": symbol,
        "brsymbol": symbol,
        "name": symbol,
        "exchange": "NSE",
        "brexchange": "nse_cm",
        "token": token,
        "expiry": "",
        "strike": -1.0,
        "lotsize": 1,
        "instrumenttype": "EQ",
        "tick_size": 0.05,
    }


class Response:
    def __init__(self, status_code, content=b"col\n1\n"):
        self.status_code = status_code
        self.content = content


class Client:
    """Answers 200 for every URL except the ones listed in ``fail``."""

    def __init__(self, fail=()):
        self.fail = set(fail)

    def get(self, url, timeout=None):
        if any(url == URLS[key] for key in self.fail):
            return Response(503, b"")
        return Response(200)


class Socket:
    def __init__(self):
        self.emitted = []

    def emit(self, event, payload):
        self.emitted.append((event, payload))
        return payload


@pytest.fixture
def kotak(monkeypatch, tmp_path):
    mcd.init_db()
    mcd.SymToken.query.delete()
    mcd.db_session.bulk_insert_mappings(
        mcd.SymToken, [row("OLD1", "900001"), row("OLD2", "900002")]
    )
    mcd.db_session.commit()

    socket = Socket()
    monkeypatch.setattr(mcd, "socketio", socket)
    monkeypatch.setattr(mcd, "get_kotak_master_filepaths", lambda: dict(URLS))
    monkeypatch.setattr(mcd, "get_httpx_client", lambda: Client())
    monkeypatch.setattr(mcd, "delete_kotak_temp_data", lambda path: None)
    for i, name in enumerate(PROCESSORS):
        frame = pd.DataFrame([row(f"NEW{i}", str(100 + i))])
        monkeypatch.setattr(mcd, name, lambda path, frame=frame: frame.copy())
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tmp").mkdir()

    yield socket

    mcd.SymToken.query.delete()
    mcd.db_session.commit()


def symbols():
    return sorted(r.symbol for r in mcd.SymToken.query.all())


def test_one_failed_segment_keeps_every_existing_symbol(kotak, monkeypatch):
    monkeypatch.setattr(mcd, "get_httpx_client", lambda: Client(fail={"MCX_FO"}))

    with pytest.raises(Exception, match="MCX_FO"):
        mcd.master_contract_download()

    assert symbols() == ["OLD1", "OLD2"]
    assert kotak.emitted[-1][1]["status"] == "error"
    assert "existing symbols were kept" in kotak.emitted[-1][1]["message"]


def test_a_segment_missing_from_the_scripmaster_list_also_keeps_them(kotak, monkeypatch):
    urls = {k: v for k, v in URLS.items() if k != "BSE_FO"}
    monkeypatch.setattr(mcd, "get_kotak_master_filepaths", lambda: urls)

    with pytest.raises(Exception, match="BSE_FO"):
        mcd.master_contract_download()

    assert symbols() == ["OLD1", "OLD2"]


def test_a_file_that_fails_to_parse_keeps_them(kotak, monkeypatch):
    def broken(path):
        raise KeyError("pSymbolName")

    monkeypatch.setattr(mcd, "process_kotak_cds_csv", broken)

    with pytest.raises(Exception, match="CDS"):
        mcd.master_contract_download()

    assert symbols() == ["OLD1", "OLD2"]


def test_a_file_with_no_rows_keeps_them(kotak, monkeypatch):
    monkeypatch.setattr(mcd, "process_kotak_bse_csv", lambda path: pd.DataFrame())

    with pytest.raises(Exception, match="BSE Cash"):
        mcd.master_contract_download()

    assert symbols() == ["OLD1", "OLD2"]


def test_a_failed_insert_rolls_back_to_the_old_symbols(kotak, monkeypatch):
    def fail_insert(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(mcd.db_session, "bulk_insert_mappings", fail_insert)

    with pytest.raises(RuntimeError, match="disk full"):
        mcd.master_contract_download()

    monkeypatch.undo()
    assert symbols() == ["OLD1", "OLD2"]


def test_a_good_refresh_still_replaces_the_table(kotak):
    """The guard must not stop the normal path from refreshing symbols."""
    mcd.master_contract_download()

    assert symbols() == [f"NEW{i}" for i in range(6)]
    assert kotak.emitted[-1][1]["status"] == "success"
