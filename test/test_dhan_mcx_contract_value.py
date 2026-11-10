"""Dhan MCX contract value.

Dhan lists every MCX contract with ``SEM_LOT_UNITS`` 1: its order quantity
counts lots. A CRUDEOIL lot is 100 barrels, so a 254 -> 270 move on 3 lots is
Rs 4,800, not Rs 48, and 3 lots at 254 block Rs 76,200 of premium, not Rs 762.
The scrip master does not carry the lot's units, so the master contract fills
``contract_value`` from ``MCX_CONTRACT_UNITS``; sandbox P&L already multiplies
by it, and margin now does too.
"""

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

MASTER = Path("broker/dhan/database/master_contract_db.py")


def _units() -> dict:
    """MCX_CONTRACT_UNITS as the module ships it (read, not imported: the module
    opens the broker database on import)."""
    source = MASTER.read_text(encoding="utf-8")
    start = source.index("MCX_CONTRACT_UNITS = {")
    end = source.index("}", start) + 1
    scope: dict = {}
    exec(source[start:end], scope)
    return scope["MCX_CONTRACT_UNITS"]


def _fill(frame: pd.DataFrame) -> pd.Series:
    """The fill as ``process_dhan_csv`` performs it."""
    units = frame["name"].map(_units()).where(frame["exchange"].eq("MCX"))
    return units.astype(object).where(units.notna(), None)


def test_mcx_rows_carry_the_lots_units_and_nothing_else_does():
    frame = pd.DataFrame(
        {
            "name": ["CRUDEOIL", "SILVERM", "GOLDM", "NATURALGASM", "NIFTY", "CRUDEOIL", "CARDAMOM"],
            "exchange": ["MCX", "MCX", "MCX", "MCX", "NFO", "NSE", "MCX"],
        }
    )
    assert list(_fill(frame)) == [100, 5, 10, 250, None, None, None]


def test_the_fill_the_module_ships_matches_this_rule():
    source = MASTER.read_text(encoding="utf-8")
    assert 'units = token_df["name"].map(MCX_CONTRACT_UNITS).where(token_df["exchange"].eq("MCX"))' in source
    assert 'token_df["contract_value"] = units.astype(object).where(units.notna(), None)' in source
    assert "contract_value = Column(Float)" in source


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
