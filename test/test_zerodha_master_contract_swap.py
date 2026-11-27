"""A failed Zerodha refresh must leave the existing symbols alone.

Zerodha emptied symtoken with one commit and then inserted the new
contract with another, and copy_from_dataframe swallowed any insert error.
A failed insert therefore left the table empty while the shared caller
recorded the refresh as a success. The swap now runs in one transaction, as
Kotak's does, and a file with no usable rows is refused before it.

The network and the parsers are replaced; the symtoken table is the test
database from conftest, so the keep-or-replace outcome is checked on real
rows.
"""

import pandas as pd
import pytest

import broker.zerodha.database.master_contract_db as zerodha

# (module, download function, parser, temp cleanup)
BROKERS = {
    "zerodha": (zerodha, "download_csv_zerodha_data", "process_zerodha_csv", "delete_zerodha_temp_data"),
}


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


# The same token on two exchanges: both rows must survive the swap.
NEW = pd.DataFrame([row("NEW1", "101"), row("NEW2", "101", "BSE"), row("NEW3", "102")])


class Socket:
    def __init__(self):
        self.emitted = []

    def emit(self, event, payload):
        self.emitted.append((event, payload))
        return payload


@pytest.fixture(params=list(BROKERS))
def broker(request, monkeypatch):
    mcd, download, parse, cleanup = BROKERS[request.param]
    mcd.init_db()
    mcd.SymToken.query.delete()
    mcd.db_session.bulk_insert_mappings(mcd.SymToken, [row("OLD1", "900001"), row("OLD2", "900002")])
    mcd.db_session.commit()

    socket = Socket()
    monkeypatch.setattr(mcd, "socketio", socket)
    monkeypatch.setattr(mcd, download, lambda *args: None)
    monkeypatch.setattr(mcd, parse, lambda path: NEW.copy())
    monkeypatch.setattr(mcd, cleanup, lambda path: None)

    yield mcd, parse, socket

    mcd.SymToken.query.delete()
    mcd.db_session.commit()


def symbols(mcd):
    return sorted(r.symbol for r in mcd.SymToken.query.all())


def test_a_failed_insert_rolls_back_to_the_old_symbols(broker, monkeypatch):
    mcd, _, socket = broker

    def fail_insert(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(mcd.db_session, "bulk_insert_mappings", fail_insert)

    with pytest.raises(RuntimeError, match="disk full"):
        mcd.master_contract_download()

    monkeypatch.undo()
    assert symbols(mcd) == ["OLD1", "OLD2"]
    assert socket.emitted[-1][1]["status"] == "error"


def test_a_file_with_no_rows_keeps_them(broker, monkeypatch):
    mcd, parse, socket = broker
    monkeypatch.setattr(mcd, parse, lambda path: pd.DataFrame())

    with pytest.raises(Exception, match="no usable rows"):
        mcd.master_contract_download()

    assert symbols(mcd) == ["OLD1", "OLD2"]
    assert "existing symbols were kept" in socket.emitted[-1][1]["message"]


def test_a_failed_download_keeps_them(broker, monkeypatch):
    mcd, _, socket = broker
    name = BROKERS["zerodha"][1]

    def fail(*args):
        raise RuntimeError("Master contract download failed, keeping the existing symbols")

    monkeypatch.setattr(mcd, name, fail)

    with pytest.raises(RuntimeError):
        mcd.master_contract_download()

    assert symbols(mcd) == ["OLD1", "OLD2"]
    assert socket.emitted[-1][1]["status"] == "error"


def test_a_good_refresh_replaces_every_row(broker):
    """Rows sharing a token across exchanges are all kept, as before."""
    mcd, _, socket = broker

    mcd.master_contract_download()

    assert symbols(mcd) == ["NEW1", "NEW2", "NEW3"]
    assert socket.emitted[-1][1]["status"] == "success"
