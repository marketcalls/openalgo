"""Dhan MCX contract value.

Dhan lists every MCX contract with ``SEM_LOT_UNITS`` 1: its order quantity
counts lots. A CRUDEOIL lot is 100 barrels, so a 254 -> 270 move on 3 lots is
Rs 4,800, not Rs 48, and 3 lots at 254 block Rs 76,200 of premium, not Rs 762.
The scrip master does not carry the lot's units, so the master contract fills
``contract_value`` from ``MCX_CONTRACT_UNITS``; sandbox P&L already multiplies
by it, and margin now does too.
"""

from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import create_engine, inspect, text

from broker.dhan.database import master_contract_db as dhan

# Verbatim rows of Dhan's api-scrip-master.csv, 10 Nov 2026.
MASTER_CSV = """\
SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_SMST_SECURITY_ID,SEM_INSTRUMENT_NAME,SEM_EXPIRY_CODE,SEM_TRADING_SYMBOL,SEM_LOT_UNITS,SEM_CUSTOM_SYMBOL,SEM_EXPIRY_DATE,SEM_STRIKE_PRICE,SEM_OPTION_TYPE,SEM_TICK_SIZE,SEM_EXPIRY_FLAG,SEM_EXCH_INSTRUMENT_TYPE,SEM_SERIES,SM_SYMBOL_NAME
MCX,M,582926,OPTFUT,0,CRUDEOIL-17Nov2026-8800-CE,1.0,CRUDEOIL 17 NOV 8800 CALL,2026-11-17 23:30:00,8800.00000,CE,10.0000,M,OPTFUT,2,CRUDEOIL
MCX,M,578641,FUTCOM,0,SILVER100-31Dec2026-FUT,1.0,SILVER100 DEC FUT,2026-12-31 23:30:00,0.00000,XX,100.0000,M,FUTCOM,2,SILVER100
MCX,M,581711,FUTCOM,0,CARDAMOM-31Dec2026-FUT,1.0,CARDAMOM DEC FUT,2026-12-31 23:30:00,0.00000,XX,100.0000,M,FUTCOM,1,CARDAMOM
NSE,D,45320,OPTIDX,0,NIFTY-Nov2026-24000-CE,65.0,NIFTY 17 NOV 24000 CALL,2026-11-17 14:30:00,24000.00000,CE,5.0000,W,OP,,
"""


def test_process_dhan_csv_fills_the_mcx_lots_units_and_nothing_else(tmp_path):
    (tmp_path / "master.csv").write_text(MASTER_CSV, encoding="utf-8")
    df = dhan.process_dhan_csv(str(tmp_path))
    rows = {r.symbol: (r.exchange, r.lotsize, r.contract_value) for r in df.itertuples()}
    assert rows["CRUDEOIL17NOV268800CE"] == ("MCX", 1, 100)     # Rs/barrel, 100 barrels
    assert rows["SILVER10031DEC26FUT"] == ("MCX", 1, 10)        # Rs/10 g, 100 g
    assert rows["CARDAMOM31DEC26FUT"][2] is None                # not in the table: empty, read as 1
    assert rows["NIFTY17NOV2624000CE"] == ("NFO", 65, None)     # lot size already in units


def test_init_db_adds_the_column_to_an_older_symtoken(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE symtoken (id INTEGER PRIMARY KEY, symbol TEXT, brsymbol TEXT, name TEXT, "
                          "exchange TEXT, brexchange TEXT, token TEXT, expiry TEXT, strike REAL, lotsize INTEGER, "
                          "instrumenttype TEXT, tick_size REAL)"))
        conn.commit()
    monkeypatch.setattr(dhan, "engine", engine)
    dhan.init_db()
    dhan.init_db()                                     # idempotent
    assert "contract_value" in {c["name"] for c in inspect(engine).get_columns("symtoken")}


def test_sandbox_margin_multiplies_by_contract_value(monkeypatch):
    import sandbox.fund_manager as fm

    cv = {"CRUDEOIL17NOV268800CE": 100.0, "NIFTY25NOV2624000CE": None}
    monkeypatch.setattr(
        fm, "get_symbol_info", lambda symbol, exchange: SimpleNamespace(contract_value=cv[symbol])
    )
    monkeypatch.setattr(fm.FundManager, "_get_leverage", lambda self, *a, **k: Decimal("1"))
    manager = fm.FundManager("TEST_USER_MCX_CV")
    margin, _ = manager.calculate_margin_required("CRUDEOIL17NOV268800CE", "MCX", "NRML", 3, 254, "BUY")
    assert margin == Decimal("76200")
    margin, _ = manager.calculate_margin_required("NIFTY25NOV2624000CE", "NFO", "NRML", 65, 100, "BUY")
    assert margin == Decimal("6500")
