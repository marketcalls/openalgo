"""Angel option symbols must carry the strike as written, decimals included.

process_angel_json built the CDS, MCX and BFO option symbols by stripping
".0" from the strike text with an unanchored regex, which removed it from
the middle as well as the end: EURUSD 1.05 became "15" (EURUSD29DEC2615CE),
1.075 became "175", and a 100.05 stock strike became "1005". The strike
column stayed right, so the symbol and its own strike disagreed (QA MC-10)
and an order for EURUSD29DEC261.05CE found nothing.

The rows below follow the Angel scrip master's shape: strike in paise, and
currency option strikes scaled a further 100000.
"""

import json

import pytest

from broker.angel.database.master_contract_db import process_angel_json


def row(token, symbol, name, exch, itype, strike_raw, expiry="29DEC2026"):
    return {
        "token": token,
        "symbol": symbol,
        "name": name,
        "expiry": expiry,
        "strike": f"{strike_raw:.6f}",
        "lotsize": "1",
        "instrumenttype": itype,
        "exch_seg": exch,
        "tick_size": "25.000000",
    }


ROWS = [
    # currency options: strike / 100 / 100000
    row("1", "EURUSD26DEC1.05CE", "EURUSD", "CDS", "OPTCUR", 1.05 * 1e7),
    row("2", "EURUSD26DEC1.075PE", "EURUSD", "CDS", "OPTCUR", 1.075 * 1e7),
    row("3", "USDINR26DEC89CE", "USDINR", "CDS", "OPTCUR", 89.0 * 1e7),
    row("4", "USDINR26DEC90.25PE", "USDINR", "CDS", "OPTCUR", 90.25 * 1e7),
    # commodity, index and stock options: strike / 100
    row("5", "GOLD26DEC168500CE", "GOLD", "MCX", "OPTFUT", 168500 * 100),
    row("6", "SENSEX26DEC75000CE", "SENSEX", "BFO", "OPTIDX", 75000 * 100),
    row("7", "SAIL26DEC100.05CE", "SAIL", "BFO", "OPTSTK", 100.05 * 100),
    row("8", "RELIANCE26DEC1302.5PE", "RELIANCE", "BFO", "OPTSTK", 1302.5 * 100),
]

EXPECTED = {
    "1": "EURUSD29DEC261.05CE",
    "2": "EURUSD29DEC261.075PE",
    "3": "USDINR29DEC2689CE",
    "4": "USDINR29DEC2690.25PE",
    "5": "GOLD29DEC26168500CE",
    "6": "SENSEX29DEC2675000CE",
    "7": "SAIL29DEC26100.05CE",
    "8": "RELIANCE29DEC261302.5PE",
}


@pytest.fixture
def symbols(tmp_path):
    path = tmp_path / "angel.json"
    path.write_text(json.dumps(ROWS), encoding="utf-8")
    df = process_angel_json(str(path))
    return dict(zip(df["token"].astype(str), df["symbol"], strict=True)), df


@pytest.mark.parametrize("token", sorted(EXPECTED))
def test_the_symbol_carries_the_strike_as_written(symbols, token):
    by_token, _ = symbols
    assert by_token[token] == EXPECTED[token]


@pytest.mark.parametrize(
    ("name", "itype", "raw_tick", "want"),
    [
        ("USDINR", "OPTCUR", 25000, 0.0025),  # Kite lists 0.0025
        ("USDINR", "FUTCUR", 25000, 0.0025),
        ("EURUSD", "OPTCUR", 1000, 0.0001),
        ("USDJPY", "FUTCUR", 100000, 0.01),
        ("633GS2035", "FUTIRC", 25000, 0.0025),
    ],
)
def test_cds_ticks_are_in_rupees(tmp_path, name, itype, raw_tick, want):
    """Angel's CDS ticks share the strike scale; divided by 100 alone USDINR read 250."""
    suffix = "FUT" if itype.startswith("FUT") else "CE"
    r = row("9", f"{name}26DEC{suffix}", name, "CDS", itype,
            -100 if suffix == "FUT" else 90 * 1e7)
    r["tick_size"] = f"{raw_tick:.6f}"
    path = tmp_path / "angel.json"
    path.write_text(json.dumps([r]), encoding="utf-8")
    df = process_angel_json(str(path))
    assert df["tick_size"].iloc[0] == pytest.approx(want)


def test_ticks_outside_cds_are_unchanged(tmp_path):
    r = row("10", "GOLD26DEC168500CE", "GOLD", "MCX", "OPTFUT", 168500 * 100)
    r["tick_size"] = "100.000000"
    path = tmp_path / "angel.json"
    path.write_text(json.dumps([r]), encoding="utf-8")
    assert process_angel_json(str(path))["tick_size"].iloc[0] == pytest.approx(1.0)


def test_the_symbol_strike_agrees_with_the_strike_column(symbols):
    _, df = symbols
    for sym, strike, typ in zip(df["symbol"], df["strike"], df["symbol"].str[-2:], strict=True):
        text = f"{float(strike):.6f}".rstrip("0").rstrip(".")
        assert sym.endswith(text + typ), f"{sym} does not carry strike {strike}"
