"""Zerodha NSE rows traded outside the EQ series get OpenAlgo's bare symbol.

Kite's instrument list names a stock in the BE series HFCL-BE and a REIT
EMBASSY-RR, and the plugin stored those as the OpenAlgo symbol. OpenAlgo's
equity symbol is the base symbol (docs/prompt/symbol-format.md), which is how
NSE lists them (Symbol HFCL, Series BE). A Nifty 500 list pasted into
Historify as SYMBOL,NSE found 495 of its 500 members for that reason: HFCL,
STLTECH, EMBASSY, BIRET and BAGMANE were missing.

Pinned here:

* the OpenAlgo symbol drops the series suffix for BE, BZ, RR, IV, SM and ST;
* brsymbol keeps Kite's tradingsymbol unchanged, since that is what every
  order, quote and history call sends to Kite;
* names with a hyphen of their own (BAJAJ-AUTO), other exchanges, the debt
  and government security series, and -RL rows are untouched;
* a suffix is kept wherever dropping it would give two rows one symbol;
* holdings map Kite's tradingsymbol back to the OpenAlgo symbol, as the order,
  trade and position books already do.
"""

from __future__ import annotations

import pandas as pd
import pytest

from broker.zerodha.database import master_contract_db as zerodha_master
from broker.zerodha.mapping import order_data

KITE_COLUMNS = [
    "instrument_token",
    "exchange_token",
    "tradingsymbol",
    "name",
    "last_price",
    "expiry",
    "strike",
    "tick_size",
    "lot_size",
    "instrument_type",
    "segment",
    "exchange",
]


def _row(token, tradingsymbol, name, exchange="NSE", segment="NSE", instrument_type="EQ"):
    return [
        token,
        token,
        tradingsymbol,
        name,
        0,
        "",
        0,
        0.05,
        1,
        instrument_type,
        segment,
        exchange,
    ]


ROWS = [
    _row(1, "RELIANCE", "RELIANCE INDUSTRIES"),
    _row(2, "BAJAJ-AUTO", "BAJAJ AUTO"),
    _row(3, "HFCL-BE", "HFCL"),
    _row(4, "STLTECH-BE", "STERLITE TECHNOLOGIES"),
    _row(5, "EMBASSY-RR", "EMBASSY OFFICE PARKS REIT"),
    _row(6, "PGINVIT-IV", "POWERGRID INFRA INVESTMENT TRUST - INVIT"),
    _row(7, "SANWARIA-BZ", "SANWARIA CONSUMER"),
    _row(8, "OMFURN-SM", "OMFURN INDIA"),
    _row(9, "GOLDSTAR-ST", "GOLDSTAR POWER"),
    _row(10, "IL&FSENGG-BZ", "IL&FS ENG AND CONS CO"),
    # Debt and government securities keep their suffix.
    _row(11, "656KA30-SG", "SDL KA 6.56% 2030"),
    _row(12, "622GS2035-GS", "GOI LOAN 6.22% 2035"),
    # The bare name is another row's symbol, so -RL is kept.
    _row(13, "HDFCSIINAV", "HDFCSIINAV"),
    _row(14, "HDFCSIINAV-RL", "HDFCSIINAV-RL"),
    # Two suffixed rows would claim one bare name: both are kept.
    _row(15, "TWOSER-BE", "TWO SERIES"),
    _row(16, "TWOSER-BZ", "TWO SERIES"),
    # A bare name that is already an EQ symbol keeps the suffixed row apart.
    _row(17, "DUAL", "DUAL LTD"),
    _row(18, "DUAL-BE", "DUAL LTD"),
    # The same shape on BSE is not an NSE series and is untouched.
    _row(19, "RAMAPPR-B", "RAMA PAPER MILLS", exchange="BSE", segment="BSE"),
    _row(20, "XYZ-BE", "XYZ", exchange="BSE", segment="BSE"),
]


@pytest.fixture
def processed(tmp_path):
    path = tmp_path / "zerodha.csv"
    pd.DataFrame(ROWS, columns=KITE_COLUMNS).to_csv(path, index=False)
    df = zerodha_master.process_zerodha_csv(str(path))
    return {(r.brsymbol, r.exchange): r.symbol for r in df.itertuples()}


@pytest.mark.parametrize(
    ("brsymbol", "symbol"),
    [
        ("HFCL-BE", "HFCL"),
        ("STLTECH-BE", "STLTECH"),
        ("EMBASSY-RR", "EMBASSY"),
        ("PGINVIT-IV", "PGINVIT"),
        ("SANWARIA-BZ", "SANWARIA"),
        ("OMFURN-SM", "OMFURN"),
        ("GOLDSTAR-ST", "GOLDSTAR"),
        ("IL&FSENGG-BZ", "IL&FSENGG"),
    ],
)
def test_series_suffix_leaves_the_openalgo_symbol_and_stays_on_brsymbol(
    processed, brsymbol, symbol
):
    assert processed[(brsymbol, "NSE")] == symbol


@pytest.mark.parametrize(
    ("brsymbol", "exchange"),
    [
        ("RELIANCE", "NSE"),
        ("BAJAJ-AUTO", "NSE"),
        ("656KA30-SG", "NSE"),
        ("622GS2035-GS", "NSE"),
        ("HDFCSIINAV", "NSE"),
        ("HDFCSIINAV-RL", "NSE"),
        ("TWOSER-BE", "NSE"),
        ("TWOSER-BZ", "NSE"),
        ("DUAL", "NSE"),
        ("DUAL-BE", "NSE"),
        ("RAMAPPR-B", "BSE"),
        ("XYZ-BE", "BSE"),
    ],
)
def test_other_rows_keep_the_tradingsymbol_as_their_symbol(processed, brsymbol, exchange):
    assert processed[(brsymbol, exchange)] == brsymbol


def test_no_two_nse_rows_share_a_symbol(processed):
    nse = [symbol for (_, exchange), symbol in processed.items() if exchange == "NSE"]
    assert len(nse) == len(set(nse))


def test_holdings_report_the_openalgo_symbol(monkeypatch):
    oa = {("HFCL-BE", "NSE"): "HFCL", ("RELIANCE", "NSE"): "RELIANCE"}
    monkeypatch.setattr(
        order_data, "get_oa_symbol", lambda brsymbol, exchange: oa.get((brsymbol, exchange))
    )
    rows = order_data.map_portfolio_data(
        {
            "data": [
                {"tradingsymbol": "HFCL-BE", "exchange": "NSE", "product": "CNC"},
                {"tradingsymbol": "RELIANCE", "exchange": "NSE", "product": "CNC"},
                # Not in the master contract: Kite's symbol is kept, not blanked.
                {"tradingsymbol": "DELISTED", "exchange": "BSE", "product": "CNC"},
            ]
        }
    )
    assert [r["tradingsymbol"] for r in rows] == ["HFCL", "RELIANCE", "DELISTED"]
