"""Pocketful master contract: download, symbol building and the symtoken swap.

The fixtures are rows copied from Pocketful's exchange-wise contract
(https://algo.pocketful.in/api/v1/contract/Compact?info=download&exchanges=
NSE,NFO,BSE,BFO,MCX, downloaded 2026-11-17), in the files' own format, plus a
few rows made up in that format where a test needs a case the real file does
not have. No network, no Pocketful account and no shared database are used:
the HTTP client is a fake and the database is a SQLite file in the test's own
directory.
"""

import io
import os
import zipfile

import httpx
import pandas as pd
import pytest
from sqlalchemy.exc import IntegrityError

import broker.pocketful.database.master_contract_db as mcd
from database.engine_factory import create_db_engine

HEADER = (
    "exchange_token,trading_symbol,company_name,close_price,expiry,strike,tick_size,"
    "lot_size,instrument_name,option_type,segment,exchange,fin_instrm_pdct_tp_cd,asset_code"
)

NSE_ROWS = """\
2885,RELIANCE-EQ,RELIANCE INDUSTRIES LTD,1344.8,,0.0000,0.1000,1,EQ,,EQ,NSE,,
16669,BAJAJ-AUTO-EQ,BAJAJ AUTO LIMITED,10734,,0.0000,1.0000,1,EQ,,EQ,NSE,,
2031,M&M-EQ,MAHINDRA & MAHINDRA LTD,3339,,0.0000,0.1000,1,EQ,,EQ,NSE,,
13,ABB-EQ,ABB INDIA LIMITED,6895,,0.0000,0.5000,1,EQ,,EQ,NSE,,
21954,HFCL-BE,HFCL LIMITED,195.2,,0.0000,0.0100,1,BE,,BE,NSE,,
30491,FELDVR-BZ,FUTURE ENTERPRISES LTD,1.91,,0.0000,0.0100,1,BZ,,BZ,NSE,,
9383,EMBASSY-RR,EMBASSY OFFICE PARKS REIT,420,,0.0000,0.0100,1,RR,,RR,NSE,,
14806,IRBIT-IV,IRB INFRASTRUCTURE TRUST,0,,0.0000,0.0100,25000,IV,,IV,NSE,,
6079,DYNAMIC-SM,DYNAMIC SRVCS & SEC LTD,122.3,,0.0000,0.0500,500,SM,,SM,NSE,,
765371,FASCINATE-ST,FASCINATE TEXTILES LTD,140.3,,0.0000,0.0500,800,ST,,ST,NSE,,
1730,664PY32-SG,SDL PY 6.64% 2032,0,,0.0000,0.0100,100,SG,,SG,NSE,,
12904,SGBAUG27-GB,2.50%GOLDBONDS2027SR-III,13521.37,,0.0000,0.0100,1,GB,,GB,NSE,,
767019,OLAPP-E1,OLAELEC RS.6 PPD UP,22.5,,0.0000,0.0100,1,E1,,E1,NSE,,
26000,Nifty 50,,25144.3,,0.0000,0.0000,0,,,INDICES,NSE,,
26009,Nifty Bank,,61034.1,,0.0000,0.0000,0,,,INDICES,NSE,,
26037,Nifty Fin Service,,27855.5,,0.0000,0.0000,0,,,INDICES,NSE,,
26074,NIFTY MID SELECT,,14346.45,,0.0000,0.0000,0,,,INDICES,NSE,,
26013,Nifty Next 50,,72874.7,,0.0000,0.0000,0,,,INDICES,NSE,,
26017,India VIX,,15.5,,0.0000,0.0000,0,,,INDICES,NSE,,
26137,Nifty FPI 150,,1599,,0.0000,0.0000,0,,,INDICES,NSE,,
26052,Nifty GS 4 8Yr,,3321.14,,0.0000,0.0000,0,,,INDICES,NSE,,
26088,BHARATBOND-APR30,,1610.49,,0.0000,0.0000,0,,,INDICES,NSE,,
26048,NIFTY100 Qualty30,,5673.2,,0.0000,0.0000,0,,,INDICES,NSE,,
26500,INDEX1 NSETEST,,21538.45,,0.0000,0.0000,0,,,INDICES,NSE,,
"""

BSE_ROWS = """\
500325,RELIANCE-A,RELIANCE INDUSTRIES LTD.,1342,,0.0000,0.0500,1,E,,A,BSE,,
532977,BAJAJ-AUTO-A,BAJAJ AUTO LTD.,10709.9,,0.0000,0.0500,1,E,,A,BSE,,
500520,M&M-A,MAHINDRA & MAHINDRA LTD.,3350,,0.0000,0.0500,1,E,,A,BSE,,
500183,HFCL-T,HFCL LIMITED,194.8,,0.0000,0.0500,1,E,,T,BSE,,
542602,EMBASSY-IF,Embassy Office Parks REIT,420,,0.0000,0.0100,1,E,,IF,BSE,,
751153,SPPL-RE1-R,SHRADDHA PRIME PROJECTS LTD,1.3,,0.0000,0.0100,1,E,,R,BSE,,
977605,731PFCL36-F,PFCL-7.31%-03-03-26-PVT,0,,0.0000,0.0100,1,D,,F,BSE,,
590003,KARURVYSYA-B,KARUR VYSYA BANK LTD.,391.4,,0.0000,0.0500,1,E,,B,BSE,,
1,SENSEX,SENSEX,81592.45,,0.0000,0.0000,0,,,IDX,BSE,,
12,BANKEX,BANKEX,68809.34,,0.0000,0.0000,0,,,IDX,BSE,,
47,SNSX50,SNSX50,26389.14,,0.0000,0.0000,0,,,IDX,BSE,,
7,BSE CG,BSE CG,72756.69,,0.0000,0.0000,0,,,IDX,BSE,,
55,MID150,MID150,16744.57,,0.0000,0.0000,0,,,IDX,BSE,,
15,OILGAS,OILGAS,26476.08,,0.0000,0.0000,0,,,IDX,BSE,,
13,AUTO,AUTO,61432.54,,0.0000,0.0000,0,,,IDX,BSE,,
75,FOCIT,FOCIT,0,,0.0000,0.0000,0,,,IDX,BSE,,
83,BS1000,BS1000,0,,0.0000,0.0000,0,,,IDX,BSE,,
"""

NFO_ROWS = """\
54749,NIFTY27JANFUT,NIFTY,25605.7,25-Jan-2027,-0.0100,0.1000,65,FUTIDX,XX,XX,NFO,,
47854,NIFTY26D0125850PE,NIFTY,627.6,01-Dec-2026,25850.0000,0.0500,65,OPTIDX,PE,XX,NFO,,
55254,BANKNIFTY26NOV39200PE,BANKNIFTY,0,23-Nov-2026,39200.0000,0.0500,30,OPTIDX,PE,XX,NFO,,
61472,NIFTYFPI26NOVFUT,NIFTYFPI,1614.05,23-Nov-2026,-0.0100,0.0500,1100,FUTIDX,XX,XX,NFO,,
100519,CROMPTON26NOV192.5CE,CROMPTON,23.5,23-Nov-2026,192.5000,0.0100,2150,OPTSTK,CE,XX,NFO,,
61637,M&M26NOVFUT,M&M,3330.8,23-Nov-2026,-0.0100,0.1000,200,FUTSTK,XX,XX,NFO,,
61505,BAJAJ-AUTO26NOVFUT,BAJAJ-AUTO,10700,23-Nov-2026,-0.0100,1.0000,75,FUTSTK,XX,XX,NFO,,
"""

BFO_ROWS = """\
1161863,SENSEX26N1975000CE,SENSEX,6859.75,19-Nov-2026,75000.0000,0.0500,20,IO,CE,IO,BFO,BSXOPT,BSX
1179017,SENSEX5027JANFUT,SENSEX50,26838.2,28-Jan-2027,-0.0100,0.0500,75,IF,XX,IF,BFO,SX50FUT,SX50
1174176,BANKEX27JANFUT,BANKEX,70098.35,28-Jan-2027,-0.0100,0.0500,30,IF,XX,IF,BFO,BKXFUT,BKX
1116327,FOCIT26NOV31100PE,FOCIT,0.05,26-Nov-2026,31100.0000,0.0500,45,IO,PE,IO,BFO,BITOPT,BIT
"""

MCX_ROWS = """\
574826,SILVER10026NOVFUT,,1687,30-Nov-2026,0.0000,1.0000,100,FUTCOM,XX,XX,MCX,,
495214,SILVER26DECFUT,,167863,04-Dec-2026,0.0000,1.0000,30,FUTCOM,XX,XX,MCX,,
576264,CRUDEOIL26DECFUT,,8009,18-Dec-2026,0.0000,1.0000,100,FUTCOM,XX,XX,MCX,,
578249,NATURALGAS26DECFUT,,331.9,28-Dec-2026,0.0000,0.1000,1250,FUTCOM,XX,XX,MCX,,
560299,GOLD27JAN144500PE,,7961.5,29-Jan-2027,144500.0000,0.5000,1,OPTFUT,PE,XX,MCX,,
588130,MCXBULLDEX26NOV29400PE,,406.85,27-Nov-2026,29400.0000,0.0500,15,OPTIDX,PE,XX,MCX,,
590003,SILVERM27APR173000PE,,8380,23-Apr-2027,173000.0000,0.5000,5,OPTFUT,PE,XX,MCX,,
115,SILVER,,0,01-Jan-0001,0.0000,1.0000,30,COM,,XX,MCX,,
568,MCXBULLDEX,,0,01-Jan-0001,0.0000,0.0500,30,COM,,XX,MCX,,
"""

FILES = {
    "NSE": NSE_ROWS,
    "BSE": BSE_ROWS,
    "NFO": NFO_ROWS,
    "BFO": BFO_ROWS,
    "MCX": MCX_ROWS,
}


def _csv(rows):
    return HEADER + "\n" + rows


def write_contract(directory, **overrides):
    """Write the five files into ``directory``; ``overrides`` replace a file's rows."""
    for exchange, rows in {**FILES, **overrides}.items():
        path = os.path.join(directory, mcd.CONTRACT_FILES[exchange])
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(_csv(rows))
    return directory


@pytest.fixture
def contract_dir(tmp_path):
    return write_contract(str(tmp_path))


@pytest.fixture
def rows(contract_dir):
    return mcd.process_pocketful_contract(contract_dir)


def row(rows, exchange, brsymbol):
    match = rows[(rows["exchange"] == exchange) & (rows["brsymbol"] == brsymbol)]
    assert len(match) == 1, f"{brsymbol} on {exchange}: {len(match)} rows"
    return match.iloc[0]


def symbols(rows, exchange):
    return set(rows.loc[rows["exchange"] == exchange, "symbol"])


# --- NSE and BSE cash ---------------------------------------------------


@pytest.mark.parametrize(
    ("brsymbol", "symbol"),
    [
        ("RELIANCE-EQ", "RELIANCE"),
        ("M&M-EQ", "M&M"),
        # Only the series is removed, never the company's own hyphen.
        ("BAJAJ-AUTO-EQ", "BAJAJ-AUTO"),
        # The series outside EQ that a Nifty 500 stock can trade in.
        ("HFCL-BE", "HFCL"),
        ("FELDVR-BZ", "FELDVR"),
        ("EMBASSY-RR", "EMBASSY"),
        ("IRBIT-IV", "IRBIT"),
        ("DYNAMIC-SM", "DYNAMIC"),
        ("FASCINATE-ST", "FASCINATE"),
    ],
)
def test_nse_equity_series_give_the_base_symbol(rows, brsymbol, symbol):
    found = row(rows, "NSE", brsymbol)
    assert found["symbol"] == symbol
    assert found["brsymbol"] == brsymbol
    assert found["instrumenttype"] == "EQ"
    assert found["brexchange"] == "NSE"


@pytest.mark.parametrize("brsymbol", ["664PY32-SG", "SGBAUG27-GB", "OLAPP-E1"])
def test_nse_debt_bonds_and_partly_paid_keep_their_trading_symbol(rows, brsymbol):
    assert row(rows, "NSE", brsymbol)["symbol"] == brsymbol


def test_a_series_suffix_stays_when_the_bare_name_is_taken(tmp_path):
    """EQ wins the bare name; two other series claiming one name both keep theirs."""
    nse = (
        "900001,ACMECO-EQ,ACME CO LTD,10,,0.0000,0.0100,1,EQ,,EQ,NSE,,\n"
        "900002,ACMECO-BE,ACME CO LTD,10,,0.0000,0.0100,1,BE,,BE,NSE,,\n"
        "900003,ZEDCO-BE,ZED CO LTD,10,,0.0000,0.0100,1,BE,,BE,NSE,,\n"
        "900004,ZEDCO-ST,ZED CO LTD,10,,0.0000,0.0500,800,ST,,ST,NSE,,\n"
    )
    out = mcd.process_pocketful_nse_csv(write_contract(str(tmp_path), NSE=nse))
    by_brsymbol = dict(zip(out["brsymbol"], out["symbol"], strict=True))
    assert by_brsymbol == {
        "ACMECO-EQ": "ACMECO",
        "ACMECO-BE": "ACMECO-BE",
        "ZEDCO-BE": "ZEDCO-BE",
        "ZEDCO-ST": "ZEDCO-ST",
    }


@pytest.mark.parametrize(
    ("brsymbol", "symbol"),
    [
        ("RELIANCE-A", "RELIANCE"),
        ("M&M-A", "M&M"),
        ("BAJAJ-AUTO-A", "BAJAJ-AUTO"),
        ("HFCL-T", "HFCL"),
        ("EMBASSY-IF", "EMBASSY"),
        # A rights entitlement: only the group suffix "-R" goes.
        ("SPPL-RE1-R", "SPPL-RE1"),
        ("731PFCL36-F", "731PFCL36"),
    ],
)
def test_bse_group_suffix_is_removed(rows, brsymbol, symbol):
    found = row(rows, "BSE", brsymbol)
    assert found["symbol"] == symbol
    assert found["instrumenttype"] == "EQ"


# --- indices ------------------------------------------------------------


@pytest.mark.parametrize(
    ("exchange", "brsymbol", "symbol"),
    [
        ("NSE_INDEX", "Nifty 50", "NIFTY"),
        ("NSE_INDEX", "Nifty Bank", "BANKNIFTY"),
        ("NSE_INDEX", "Nifty Fin Service", "FINNIFTY"),
        ("NSE_INDEX", "NIFTY MID SELECT", "MIDCPNIFTY"),
        ("NSE_INDEX", "Nifty Next 50", "NIFTYNXT50"),
        ("NSE_INDEX", "India VIX", "INDIAVIX"),
        # The NFO underlying is NIFTYFPI; the index must carry the same name.
        ("NSE_INDEX", "Nifty FPI 150", "NIFTYFPI"),
        ("NSE_INDEX", "Nifty GS 4 8Yr", "NIFTYGS48YR"),
        ("NSE_INDEX", "BHARATBOND-APR30", "BHARATBONDAPR30"),
        ("NSE_INDEX", "NIFTY100 Qualty30", "NIFTY100QUALTY30"),
        ("BSE_INDEX", "SENSEX", "SENSEX"),
        ("BSE_INDEX", "BANKEX", "BANKEX"),
        ("BSE_INDEX", "SNSX50", "SENSEX50"),
        ("BSE_INDEX", "BSE CG", "BSECAPITALGOODS"),
        ("BSE_INDEX", "MID150", "BSE150MIDCAPINDEX"),
        ("BSE_INDEX", "OILGAS", "BSEOIL&GAS"),
        ("BSE_INDEX", "AUTO", "BSEAUTO"),
        ("BSE_INDEX", "FOCIT", "BSEFOCUSEDIT"),
        # A code symbol-format.md does not list keeps its own name.
        ("BSE_INDEX", "BS1000", "BS1000"),
    ],
)
def test_indices_carry_the_openalgo_index_symbol(rows, exchange, brsymbol, symbol):
    found = row(rows, exchange, brsymbol)
    assert found["symbol"] == symbol
    assert found["instrumenttype"] == "EQ"
    assert found["brexchange"] == exchange.split("_")[0]
    assert found["name"] == brsymbol


def test_index_rows_stay_off_the_cash_exchanges(rows):
    assert not symbols(rows, "NSE") & {"Nifty 50", "NIFTY"}
    assert not symbols(rows, "BSE") & {"SENSEX", "AUTO", "BSEAUTO"}


def test_exchange_test_indices_are_not_loaded(rows):
    assert "INDEX1 NSETEST" not in set(rows["brsymbol"])


# --- derivatives ----------------------------------------------------------


@pytest.mark.parametrize(
    ("exchange", "brsymbol", "symbol", "expiry", "strike", "instrumenttype", "name"),
    [
        ("NFO", "NIFTY27JANFUT", "NIFTY25JAN27FUT", "25-JAN-27", 0.0, "FUT", "NIFTY"),
        # Weekly: Pocketful writes 26D01 for 1 December 2026.
        ("NFO", "NIFTY26D0125850PE", "NIFTY01DEC2625850PE", "01-DEC-26", 25850.0, "PE", "NIFTY"),
        (
            "NFO",
            "BANKNIFTY26NOV39200PE",
            "BANKNIFTY23NOV2639200PE",
            "23-NOV-26",
            39200.0,
            "PE",
            "BANKNIFTY",
        ),
        ("NFO", "NIFTYFPI26NOVFUT", "NIFTYFPI23NOV26FUT", "23-NOV-26", 0.0, "FUT", "NIFTYFPI"),
        (
            "NFO",
            "CROMPTON26NOV192.5CE",
            "CROMPTON23NOV26192.5CE",
            "23-NOV-26",
            192.5,
            "CE",
            "CROMPTON",
        ),
        ("NFO", "M&M26NOVFUT", "M&M23NOV26FUT", "23-NOV-26", 0.0, "FUT", "M&M"),
        (
            "NFO",
            "BAJAJ-AUTO26NOVFUT",
            "BAJAJ-AUTO23NOV26FUT",
            "23-NOV-26",
            0.0,
            "FUT",
            "BAJAJ-AUTO",
        ),
        ("BFO", "SENSEX26N1975000CE", "SENSEX19NOV2675000CE", "19-NOV-26", 75000.0, "CE", "SENSEX"),
        ("BFO", "SENSEX5027JANFUT", "SENSEX5028JAN27FUT", "28-JAN-27", 0.0, "FUT", "SENSEX50"),
        ("BFO", "BANKEX27JANFUT", "BANKEX28JAN27FUT", "28-JAN-27", 0.0, "FUT", "BANKEX"),
        ("BFO", "FOCIT26NOV31100PE", "FOCIT26NOV2631100PE", "26-NOV-26", 31100.0, "PE", "FOCIT"),
        # MCX has no company_name: the underlying comes from the symbol, and
        # SILVER100 is not SILVER.
        ("MCX", "SILVER10026NOVFUT", "SILVER10030NOV26FUT", "30-NOV-26", 0.0, "FUT", "SILVER100"),
        ("MCX", "SILVER26DECFUT", "SILVER04DEC26FUT", "04-DEC-26", 0.0, "FUT", "SILVER"),
        ("MCX", "CRUDEOIL26DECFUT", "CRUDEOIL18DEC26FUT", "18-DEC-26", 0.0, "FUT", "CRUDEOIL"),
        ("MCX", "GOLD27JAN144500PE", "GOLD29JAN27144500PE", "29-JAN-27", 144500.0, "PE", "GOLD"),
        (
            "MCX",
            "MCXBULLDEX26NOV29400PE",
            "MCXBULLDEX27NOV2629400PE",
            "27-NOV-26",
            29400.0,
            "PE",
            "MCXBULLDEX",
        ),
        (
            "MCX",
            "SILVERM27APR173000PE",
            "SILVERM23APR27173000PE",
            "23-APR-27",
            173000.0,
            "PE",
            "SILVERM",
        ),
    ],
)
def test_derivatives_follow_the_openalgo_format(
    rows, exchange, brsymbol, symbol, expiry, strike, instrumenttype, name
):
    found = row(rows, exchange, brsymbol)
    assert found["symbol"] == symbol
    assert found["expiry"] == expiry
    # Futures arrive with the placeholder strike -0.01.
    assert found["strike"] == strike
    assert str(found["strike"]) != "-0.0"
    assert found["instrumenttype"] == instrumenttype
    assert found["name"] == name
    assert found["brexchange"] == exchange


def test_mcx_spot_definitions_are_not_loaded(rows):
    mcx = rows[rows["exchange"] == "MCX"]
    assert not set(mcx["brsymbol"]) & {"SILVER", "MCXBULLDEX"}
    assert len(mcx) == 7


# --- lot and tick sizes -------------------------------------------------


@pytest.mark.parametrize(
    ("exchange", "brsymbol", "lotsize", "tick_size"),
    [
        ("NSE", "RELIANCE-EQ", 1, 0.1),
        ("NSE", "BAJAJ-AUTO-EQ", 1, 1.0),
        ("NSE", "IRBIT-IV", 25000, 0.01),
        ("NSE", "DYNAMIC-SM", 500, 0.05),
        ("BSE", "RELIANCE-A", 1, 0.05),
        ("NFO", "NIFTY27JANFUT", 65, 0.1),
        ("NFO", "CROMPTON26NOV192.5CE", 2150, 0.01),
        ("BFO", "SENSEX26N1975000CE", 20, 0.05),
        # MCX lots are already units (CRUDEOIL 100 barrels, GOLD 1 kg) and
        # ticks already rupees.
        ("MCX", "CRUDEOIL26DECFUT", 100, 1.0),
        ("MCX", "NATURALGAS26DECFUT", 1250, 0.1),
        ("MCX", "GOLD27JAN144500PE", 1, 0.5),
        ("MCX", "MCXBULLDEX26NOV29400PE", 15, 0.05),
        ("NSE_INDEX", "Nifty 50", 0, 0.0),
    ],
)
def test_lot_and_tick_sizes_are_kept_as_given(rows, exchange, brsymbol, lotsize, tick_size):
    found = row(rows, exchange, brsymbol)
    assert found["lotsize"] == lotsize
    assert found["tick_size"] == pytest.approx(tick_size)


# --- the whole contract -------------------------------------------------


def test_the_processed_contract_has_the_symtoken_shape(rows):
    assert list(rows.columns) == mcd.SYMTOKEN_COLUMNS
    assert set(rows["instrumenttype"]) == {"EQ", "FUT", "CE", "PE"}
    assert set(rows["exchange"]) == {"NSE", "BSE", "NFO", "BFO", "MCX", "NSE_INDEX", "BSE_INDEX"}
    assert not rows.duplicated(subset=["symbol", "exchange"]).any()
    assert not rows.duplicated(subset=["token", "exchange"]).any()
    assert (rows["strike"] >= 0).all()


def test_a_repeated_symbol_on_one_exchange_keeps_only_the_first_row(tmp_path):
    """Two contracts that build one symbol would make get_token() ambiguous."""
    nfo = (
        NFO_ROWS
        + "99999,NIFTY27JANFUT-X,NIFTY,0,25-Jan-2027,-0.0100,0.1000,65,FUTIDX,XX,XX,NFO,,\n"
    )
    out = mcd.process_pocketful_contract(write_contract(str(tmp_path), NFO=nfo))
    futures = out[(out["exchange"] == "NFO") & (out["symbol"] == "NIFTY25JAN27FUT")]
    assert list(futures["token"]) == ["54749"]


def test_a_file_without_an_expected_column_is_refused(tmp_path):
    directory = write_contract(str(tmp_path))
    path = os.path.join(directory, mcd.CONTRACT_FILES["NFO"])
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(_csv(NFO_ROWS).replace("option_type", "opt_type"))
    with pytest.raises(ValueError, match="option_type"):
        mcd.process_pocketful_contract(directory)


# --- download -----------------------------------------------------------


def _archive(members):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in members.items():
            archive.writestr(name, text)
    return buffer.getvalue()


def _full_archive(**extra):
    members = {mcd.CONTRACT_FILES[e]: _csv(rows) for e, rows in FILES.items()}
    members.update(extra)
    return _archive(members)


class FakeClient:
    """Records each GET and answers with a fixed response."""

    def __init__(self, content=b"", status_code=200):
        self.calls = []
        self.content = content
        self.status_code = status_code

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return httpx.Response(
            self.status_code, content=self.content, request=httpx.Request("GET", url)
        )


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeClient(_full_archive())
    monkeypatch.setattr(mcd, "get_httpx_client", lambda: client)
    return client


def test_the_download_asks_for_the_documented_file_and_sends_no_credentials(fake_client, tmp_path):
    paths = mcd.download_pocketful_contract(str(tmp_path))

    assert len(fake_client.calls) == 1
    url, kwargs = fake_client.calls[0]
    assert url == (
        "https://algo.pocketful.in/api/v1/contract/Compact"
        "?info=download&exchanges=NSE,NFO,BSE,BFO,MCX"
    )
    # Public file: no token, no account, nothing else that identifies the trader.
    assert set(kwargs) == {"timeout"}
    assert kwargs["timeout"] == mcd.DOWNLOAD_TIMEOUT
    assert set(paths) == set(mcd.CONTRACT_EXCHANGES)
    for exchange, path in paths.items():
        with open(path, encoding="utf-8") as handle:
            assert handle.read() == _csv(FILES[exchange])


def test_the_download_writes_only_the_five_contract_files(monkeypatch, tmp_path):
    client = FakeClient(_full_archive(**{"../outside.csv": "x", "extra/notes.txt": "y"}))
    monkeypatch.setattr(mcd, "get_httpx_client", lambda: client)
    target = tmp_path / "work"
    target.mkdir()

    mcd.download_pocketful_contract(str(target))

    assert sorted(os.listdir(target)) == sorted(mcd.CONTRACT_FILES.values())
    assert not (tmp_path / "outside.csv").exists()


def test_an_archive_missing_a_file_is_refused(monkeypatch, tmp_path):
    members = {mcd.CONTRACT_FILES[e]: _csv(r) for e, r in FILES.items() if e != "MCX"}
    monkeypatch.setattr(mcd, "get_httpx_client", lambda: FakeClient(_archive(members)))
    with pytest.raises(ValueError, match="MCXCompactScrip.csv"):
        mcd.download_pocketful_contract(str(tmp_path))


def test_an_http_error_is_raised(monkeypatch, tmp_path):
    monkeypatch.setattr(mcd, "get_httpx_client", lambda: FakeClient(b"busy", status_code=503))
    with pytest.raises(httpx.HTTPStatusError):
        mcd.download_pocketful_contract(str(tmp_path))


# --- writing symtoken -----------------------------------------------------


@pytest.fixture
def symtoken_db(tmp_path):
    """Point the module's session at a SQLite file of this test's own."""
    engine = create_db_engine(f"sqlite:///{(tmp_path / 'symtoken.db').as_posix()}")
    mcd.Base.metadata.create_all(engine)
    mcd.db_session.remove()
    mcd.db_session.configure(bind=engine)
    try:
        yield engine
    finally:
        mcd.db_session.remove()
        mcd.db_session.configure(bind=mcd.engine)
        engine.dispose()


def stored(engine):
    return pd.read_sql("SELECT symbol, exchange, token FROM symtoken", engine)


def test_rows_sharing_a_token_on_two_exchanges_are_all_stored(symtoken_db, rows):
    """NSE ABB and the BSE index AUTO are both token 13; BSE KARURVYSYA and an
    MCX SILVERM option are both 590003. Each is its own instrument."""
    mcd.replace_symtoken_table(rows)

    table = stored(symtoken_db)
    assert len(table) == len(rows)
    by_key = {(r.exchange, r.token): r.symbol for r in table.itertuples()}
    assert by_key[("NSE", "13")] == "ABB"
    assert by_key[("BSE_INDEX", "13")] == "BSEAUTO"
    assert by_key[("BSE", "590003")] == "KARURVYSYA"
    assert by_key[("MCX", "590003")] == "SILVERM23APR27173000PE"


def test_a_failed_insert_leaves_the_previous_contract(symtoken_db, rows):
    mcd.replace_symtoken_table(rows)
    before = stored(symtoken_db)

    broken = rows.copy()
    broken.loc[broken.index[-1], "symbol"] = None  # symbol is NOT NULL
    with pytest.raises(IntegrityError):
        mcd.replace_symtoken_table(broken)

    pd.testing.assert_frame_equal(stored(symtoken_db), before)


def test_an_empty_contract_never_replaces_the_table(symtoken_db, rows):
    mcd.replace_symtoken_table(rows)
    with pytest.raises(ValueError):
        mcd.replace_symtoken_table(rows.iloc[0:0])
    assert len(stored(symtoken_db)) == len(rows)


# --- master_contract_download ------------------------------------------


class Emitter:
    def __init__(self):
        self.events = []

    def emit(self, event, payload):
        self.events.append((event, payload))
        return payload


@pytest.fixture
def emitter(monkeypatch):
    spy = Emitter()
    monkeypatch.setattr(mcd, "socketio", spy)
    return spy


@pytest.fixture
def work_dir(monkeypatch, tmp_path):
    path = tmp_path / "work"

    def mkdtemp(prefix=""):
        path.mkdir()
        return str(path)

    monkeypatch.setattr(mcd.tempfile, "mkdtemp", mkdtemp)
    return path


def test_a_failed_download_keeps_the_stored_contract_and_says_so(monkeypatch, emitter, work_dir):
    replaced = []
    monkeypatch.setattr(mcd, "replace_symtoken_table", replaced.append)

    def refuse(path):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(mcd, "download_pocketful_contract", refuse)

    # Raised again: utils/auth_utils treats a normal return as success.
    with pytest.raises(httpx.ConnectError):
        mcd.master_contract_download()

    assert replaced == []
    assert emitter.events == [
        ("master_contract_download", {"status": "error", "message": mcd.FAILED_MESSAGE})
    ]
    assert "connection refused" not in mcd.FAILED_MESSAGE
    assert not work_dir.exists()


def test_a_successful_download_replaces_the_contract(monkeypatch, emitter, work_dir, fake_client):
    replaced = []
    monkeypatch.setattr(mcd, "replace_symtoken_table", replaced.append)

    mcd.master_contract_download()

    assert len(replaced) == 1
    assert {"NIFTY", "BANKNIFTY"} <= symbols(replaced[0], "NSE_INDEX")
    assert "HFCL" in symbols(replaced[0], "NSE")
    assert emitter.events[-1][1]["status"] == "success"
    assert not work_dir.exists()
