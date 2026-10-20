"""Kotak's currency (cde_fo) prices are scaled by 10^7, not by 100.

process_kotak_cds_csv divided dStrikePrice and dTickSize by 100, copied from
the paise-priced NSE F&O processor. cde_fo carries lPrecision 4 and
lMultiplier 1000, so its prices are 10^7 times the rupee value:
USDINR26DEC101.75PE was stored with strike 10175000, the OpenAlgo symbol was
built from it (USDINR29DEC2610175000PE), and USDINR's 0.0025 tick became 250.

The rows below are copied verbatim from Kotak's cde_fo.csv of 2026-10-15,
including its padded and semicolon-suffixed column names.
"""

import pandas as pd
import pytest

import broker.kotak.database.master_contract_db as mcd

CDE_FO = """\
pSymbol,pExchSeg,pSymbolName,pTrdSymbol,pOptionType,dTickSize ,lLotSize,lExpiryDate ,dStrikePrice;
10806,cde_fo,JPYINR,JPYINR26NOV64.5PE,PE,25000,1,1480170600,6.45e+08
4690,cde_fo,USDINR,USDINR26DEC101.75PE,PE,25000,1,1483021800,1.0175e+09
8392,cde_fo,GBPUSD,GBPUSD26OCT1.375CE,CE,1000,1,1477665000,1.375e+07
9990,cde_fo,USDJPY,USDJPY26OCT163CE,CE,100000,1,1477665000,1.63e+09
2928,cde_fo,USDINR,USDINR27MARFUT,XX,25000,1,1490797800,-1
"""


@pytest.fixture
def cds(tmp_path):
    (tmp_path / "CDE_FO.csv").write_text(CDE_FO)
    return mcd.process_kotak_cds_csv(str(tmp_path)).set_index("brsymbol")


@pytest.mark.parametrize(
    ("brsymbol", "strike"),
    [
        ("USDINR26DEC101.75PE", 101.75),
        ("JPYINR26NOV64.5PE", 64.5),
        ("GBPUSD26OCT1.375CE", 1.375),
        ("USDJPY26OCT163CE", 163),
    ],
)
def test_option_strike_matches_the_kotak_trading_symbol(cds, brsymbol, strike):
    assert cds.loc[brsymbol, "strike"] == pytest.approx(strike)


def test_the_openalgo_symbol_carries_the_real_strike(cds):
    assert cds.loc["USDINR26DEC101.75PE", "symbol"] == "USDINR29DEC26101.75PE"
    assert cds.loc["JPYINR26NOV64.5PE", "symbol"] == "JPYINR26NOV2664.5PE"
    assert cds.loc["USDJPY26OCT163CE", "symbol"] == "USDJPY28OCT26163CE"


@pytest.mark.parametrize(
    ("brsymbol", "tick"),
    [
        ("USDINR26DEC101.75PE", 0.0025),
        ("GBPUSD26OCT1.375CE", 0.0001),
        ("USDJPY26OCT163CE", 0.01),
        ("USDINR27MARFUT", 0.0025),
    ],
)
def test_tick_size_is_in_rupees(cds, brsymbol, tick):
    assert cds.loc[brsymbol, "tick_size"] == pytest.approx(tick)


def test_futures_keep_the_same_placeholder_strike_as_other_segments(cds):
    """dStrikePrice -1 on a future stays -0.01, as NSE F&O stores it."""
    assert cds.loc["USDINR27MARFUT", "strike"] == pytest.approx(-0.01)
    assert cds.loc["USDINR27MARFUT", "symbol"].endswith("FUT")


def test_no_other_segment_changed_scale(tmp_path):
    """NSE F&O prices are paise; its divisor of 100 is correct and untouched."""
    nfo = pd.DataFrame(
        {
            "pSymbol": ["35003"],
            "pExchSeg": ["nse_fo"],
            "pSymbolName": ["NIFTY"],
            "pTrdSymbol": ["NIFTY26OCT25000CE"],
            "pOptionType": ["CE"],
            "dTickSize ": [5],
            "lLotSize": [75],
            "lExpiryDate ": [1477665000],
            "pInstType": ["OPTIDX"],
            "dStrikePrice;": [2500000],
        }
    )
    nfo.to_csv(tmp_path / "NSE_FO.csv", index=False)
    out = mcd.process_kotak_nfo_csv(str(tmp_path))
    assert out["strike"].iloc[0] == 25000
