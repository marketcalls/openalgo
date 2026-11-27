"""Fyers cash and index rows must carry no expiry (QA MC-05).

Fyers' NSE_CM file leaves "Expiry date" empty for stocks and most indices,
but holds a single space for some older indices (NIFTY200, HANGSENG
BEES-NAV, NIFTY200QUALTY30 ...). The parser copied the column as it is, so
46 NSE_INDEX rows were stored with ' ' as their expiry, which anything
testing `if expiry:` reads as a contract with an expiry.

The lines below are copied from Fyers' NSE_CM.csv.
"""

import broker.fyers.database.master_contract_db as mcd

LINES = [
    "10100000003045,STATE BANK OF INDIA,0,1,0.05,INE062A01020,0915-1530|1815-1915:,"
    "2026-11-26,,NSE:SBIN-EQ,10,10,3045,SBIN,3045,-1.0,XX,10100000003045,None,1,3.7",
    "101000000026000,NIFTY50-INDEX,10,0,0.05,,0915-1530|1815-1915:,2026-11-26,,"
    "NSE:NIFTY50-INDEX,10,10,26000,NIFTY,26000,-1.0,XX,101000000026000,None,0,0.0",
    "1010000000999002,NIFTY200-INDEX,10,1,0.05,,0915-1530|1815-1915:,2018-02-05, ,"
    "NSE:NIFTY200-INDEX,10,10,999002,NIFTY 200,999002,-1.0,XX,1010000000999002,None,0,0.0",
]


def test_cash_and_index_rows_have_no_expiry(tmp_path):
    (tmp_path / "NSE_CM.csv").write_text("\n".join(LINES) + "\n", encoding="utf-8")

    df = mcd.process_fyers_nse_csv(str(tmp_path))
    expiry = dict(zip(df["brsymbol"], df["expiry"], strict=True))

    assert set(expiry) == {"NSE:SBIN-EQ", "NSE:NIFTY50-INDEX", "NSE:NIFTY200-INDEX"}
    for brsymbol, value in expiry.items():
        assert not (isinstance(value, str) and value), f"{brsymbol} expiry {value!r}"
