"""Fyers index subscriptions take their HSM name from the master contract.

The HSM feed subscribes an index by name, "if|nse_cm|Nifty IT", and the
official SDK sends the display name Fyers publishes at
public.fyers.in/sym_details/index_hsm_mapping.json. No master-contract column
carries that name (Symbol Details is "NIFTYIT-INDEX", Underlying symbol is
"NIFTYIT"), so the download fetches the table and stores the display name in
symtoken.name for index rows, keeping the ticker stem where Fyers publishes
none; the feed accepted the stem too when measured on 2026-09-29. The token
converter then reads the name through the symbol cache like every other
field. The same download names the BSE indices that used to fall through the
normalisation map unprefixed (ALLCAP, UTILS, BHRT22...).

No network and no database: the HTTP client, the symbol lookups and the Fyers
symbol-token API are all replaced. The CSV rows are real lines from Fyers'
BSE_CM.csv of 2026-09-29.
"""

import pandas as pd
import pytest

import broker.fyers.database.master_contract_db as mcd
import broker.fyers.streaming.fyers_token_converter as ftc

BSE_CSV = (
    "121000000036,S&P BSE AllCap-INDEX,10,1,0.01,,0915-1530|1815-1915:,2018-02-05,,"
    "BSE:ALLCAP-INDEX,12,10,36,ALLCAP,36,-1.0,XX,121000000036,None,0,0.0\n"
    "1210000000500112,STATE BANK OF INDIA,0,1,0.05,INE062A01020,0915-1530|1815-1915:,"
    "2026-09-24,,BSE:SBIN-A,12,10,500112,SBIN,500112,-1.0,XX,1210000000500112,None,0,0.0\n"
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error

    def get(self, url, timeout=None):
        if self.error:
            raise self.error
        return FakeResponse(self.payload)


# --- master contract download -----------------------------------------------


def processed_frame():
    """The shape a cash-segment processor hands back, before the database copy."""
    return pd.DataFrame(
        [
            {"brsymbol": "NSE:NIFTYIT-INDEX", "exchange": "NSE_INDEX", "name": "NIFTYIT-INDEX"},
            {
                "brsymbol": "NSE:NIFTYALPHALOWVOL-INDEX",
                "exchange": "NSE_INDEX",
                "name": "NIFTYALPHALOWVOL-INDEX",
            },
            {"brsymbol": "NSE:SBIN-EQ", "exchange": "NSE", "name": "STATE BANK OF INDIA"},
        ]
    )


def test_index_rows_take_the_published_display_name():
    df = processed_frame()

    mcd._apply_index_names(df, {"NSE:NIFTYIT-INDEX": "Nifty IT"})

    assert list(df["name"]) == ["Nifty IT", "NIFTYALPHALOWVOL", "STATE BANK OF INDIA"]


def test_without_a_table_index_rows_keep_the_ticker_stem():
    df = processed_frame()

    mcd._apply_index_names(df, {})

    assert list(df["name"]) == ["NIFTYIT", "NIFTYALPHALOWVOL", "STATE BANK OF INDIA"]


def test_a_frame_without_the_columns_is_left_alone():
    df = pd.DataFrame([{"symbol": "SBIN", "exchange": "NSE", "token": "1"}])

    mcd._apply_index_names(df, {"NSE:NIFTYIT-INDEX": "Nifty IT"})

    assert list(df.columns) == ["symbol", "exchange", "token"]


def test_fetch_returns_the_published_table(monkeypatch):
    monkeypatch.setattr(
        mcd, "get_httpx_client", lambda: FakeClient({"NSE:NIFTY50-INDEX": "Nifty 50"})
    )

    assert mcd.fetch_index_hsm_names() == {"NSE:NIFTY50-INDEX": "Nifty 50"}


@pytest.mark.parametrize(
    "client",
    [FakeClient(error=RuntimeError("offline")), FakeClient(["not", "an", "object"])],
    ids=["request fails", "not an object"],
)
def test_a_failed_fetch_yields_an_empty_table(monkeypatch, client):
    monkeypatch.setattr(mcd, "get_httpx_client", lambda: client)

    assert mcd.fetch_index_hsm_names() == {}


def test_a_bse_index_outside_the_old_map_gets_a_prefixed_symbol_and_its_name(tmp_path):
    (tmp_path / "BSE_CM.csv").write_text(BSE_CSV, encoding="utf-8")

    df = mcd.process_fyers_bse_csv(str(tmp_path))
    mcd._apply_index_names(df, {"BSE:ALLCAP-INDEX": "BSEALLCAP"})
    rows = {r.brsymbol: r for r in df.itertuples()}

    assert rows["BSE:ALLCAP-INDEX"].symbol == "BSEALLCAP"  # fell through as ALLCAP before
    assert rows["BSE:ALLCAP-INDEX"].exchange == "BSE_INDEX"
    assert rows["BSE:ALLCAP-INDEX"].name == "BSEALLCAP"
    assert rows["BSE:SBIN-A"].symbol == "SBIN"
    assert rows["BSE:SBIN-A"].name == "STATE BANK OF INDIA"


def test_the_download_names_both_cash_segments_before_copying(monkeypatch):
    table = {"NSE:NIFTY50-INDEX": "Nifty 50"}
    applied = []
    monkeypatch.setattr(mcd, "download_csv_fyers_data", lambda path: (True, [], None))
    monkeypatch.setattr(mcd, "fetch_index_hsm_names", lambda: table)
    monkeypatch.setattr(mcd, "delete_symtoken_table", lambda: None)
    monkeypatch.setattr(mcd, "copy_from_dataframe", lambda df: None)
    monkeypatch.setattr(mcd, "delete_fyers_temp_data", lambda path: None)
    monkeypatch.setattr(mcd.socketio, "emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(mcd, "_apply_index_names", lambda df, names: applied.append(names))
    for name in (
        "process_fyers_nse_csv",
        "process_fyers_bse_csv",
        "process_fyers_nfo_csv",
        "process_fyers_bfo_csv",
        "process_fyers_cds_json",
        "process_fyers_mcx_json",
    ):
        monkeypatch.setattr(mcd, name, lambda path: pd.DataFrame())

    mcd.master_contract_download()

    assert applied == [table, table]


# --- token converter ---------------------------------------------------------


class Info:
    def __init__(self, name):
        self.name = name


BRSYMBOLS = {"NIFTYIT": "NSE:NIFTYIT-INDEX", "BSEPSU": "BSE:PSU-INDEX"}
FYTOKENS = {"NSE:NIFTYIT-INDEX": "101000000026008", "BSE:PSU-INDEX": "121000000010"}


def fake_symbol_token_api(**kwargs):
    asked = kwargs["json"]["symbols"]
    return FakeResponse(
        {"s": "ok", "validSymbol": {s: FYTOKENS[s] for s in asked}, "invalidSymbol": []}
    )


def converter(monkeypatch, names):
    monkeypatch.setattr(ftc, "get_br_symbol", lambda symbol, exchange: BRSYMBOLS.get(symbol))
    monkeypatch.setattr(
        ftc,
        "get_symbol_info",
        lambda symbol, exchange: Info(names[symbol]) if symbol in names else None,
    )
    monkeypatch.setattr(ftc.requests, "post", fake_symbol_token_api)
    return ftc.FyersTokenConverter("appid:token")


def test_an_index_named_in_the_master_contract_subscribes_by_that_name(monkeypatch):
    conv = converter(monkeypatch, {"NIFTYIT": "Nifty IT", "BSEPSU": "BSEPSU"})

    tokens, mapping, invalid = conv.convert_openalgo_symbols_to_hsm(
        [
            {"symbol": "NIFTYIT", "exchange": "NSE_INDEX"},
            {"symbol": "BSEPSU", "exchange": "BSE_INDEX"},
        ]
    )

    assert sorted(tokens) == ["if|bse_cm|BSEPSU", "if|nse_cm|Nifty IT"]
    assert mapping["if|nse_cm|Nifty IT"] == "NSE:NIFTYIT-INDEX"
    assert invalid == []


def test_an_index_with_no_stored_name_subscribes_by_the_ticker_stem(monkeypatch):
    conv = converter(monkeypatch, {})

    tokens, _, _ = conv.convert_openalgo_symbols_to_hsm(
        [{"symbol": "NIFTYIT", "exchange": "NSE_INDEX"}]
    )

    assert tokens == ["if|nse_cm|NIFTYIT"]


def test_the_manual_fallback_uses_the_stored_name(monkeypatch):
    conv = converter(monkeypatch, {"NIFTYIT": "Nifty IT"})
    conv.convert_openalgo_symbols_to_hsm([{"symbol": "NIFTYIT", "exchange": "NSE_INDEX"}])

    tokens, mapping, invalid = conv._manual_conversion(["NSE:NIFTYIT-INDEX"], "SymbolUpdate")

    assert tokens == ["if|nse_cm|Nifty IT"]
    assert mapping == {"if|nse_cm|Nifty IT": "NSE:NIFTYIT-INDEX"}
    assert invalid == []