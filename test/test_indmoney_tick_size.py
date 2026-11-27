"""INDmoney's instrument master gives TICK_SIZE in paise, as Angel's does.

On 2 Nov 2026 the master listed NIFTY options at 5 (Rs 0.05) and RELIANCE at
10 (Rs 0.10). Stored as rupees, a 24.5 trigger rounded to a Rs 5 tick became
25 for the trigger and 20 for the limit.

No network and no database: the CSVs are written to tmp_path and the progress
reporting is replaced.
"""

import pytest

import broker.indmoney.database.master_contract_db as mcd
import database.master_contract_status_db as status_db

EQUITY_CSV = (
    "EXCH,SEGMENT,SECURITY_ID,INSTRUMENT_NAME,TRADING_SYMBOL,LOT_UNITS,TICK_SIZE\n"
    "NSE,E,2885,EQUITY,RELIANCE,1,10\n"
)
FNO_CSV = (
    "EXCH,SEGMENT,SECURITY_ID,INSTRUMENT_NAME,TRADING_SYMBOL,LOT_UNITS,"
    "EXPIRY_DATE,STRIKE_PRICE,OPTION_TYPE,TICK_SIZE\n"
    "NSE,D,53940,OPTIDX,NIFTY-Nov2026-23300-CE,65,2026-11-03,23300,CE,5\n"
)


@pytest.fixture
def processed(tmp_path, monkeypatch):
    (tmp_path / "equity.csv").write_text(EQUITY_CSV, encoding="utf-8")
    (tmp_path / "fno.csv").write_text(FNO_CSV, encoding="utf-8")
    monkeypatch.setattr(mcd.socketio, "emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(status_db, "update_status", lambda *args, **kwargs: None)
    df = mcd.process_indmoney_csv(str(tmp_path))
    return {r.token: r for r in df.itertuples()}


def test_tick_size_is_stored_in_rupees(processed):
    assert processed["2885"].tick_size == pytest.approx(0.10)
    assert processed["53940"].tick_size == pytest.approx(0.05)
    assert processed["53940"].symbol == "NIFTY03NOV2623300CE"
