# test/test_pnl_history_csv_import.py
"""Segment mapping for Zerodha Console CSVs: Console's tradebook export sets exchange=NSE/BSE
for F&O rows too, so deriving segment from exchange alone mis-tags every
options/futures trade as equity. _normalize_csv_row must read the CSV's
own segment column instead.
"""

from restx_api.pnl_history import _normalize_csv_row


def test_fo_row_with_nse_exchange_maps_to_fno_segment():
    # A real row shape from a Zerodha Console F&O tradebook export -
    # exchange is the plain "NSE" code, not "NFO".
    row = {
        "symbol": "NIFTY2610625750PE",
        "isin": "",
        "trade_date": "2026-01-05",
        "exchange": "NSE",
        "segment": "FO",
        "series": "",
        "trade_type": "sell",
        "auction": "false",
        "quantity": "130.000000",
        "price": "1.750000",
        "trade_id": "4651213",
        "order_id": "1400000230629349",
        "order_execution_time": "2026-01-05T15:04:45",
        "expiry_date": "2026-01-06",
    }
    normalized = _normalize_csv_row(row)
    assert normalized["segment"] == "fno"
    assert normalized["exchange"] == "NSE"


def test_eq_row_maps_to_equity_segment():
    row = {
        "symbol": "CEIGALL",
        "isin": "INE0AG901020",
        "trade_date": "2026-01-05",
        "exchange": "NSE",
        "segment": "EQ",
        "series": "EQ",
        "trade_type": "buy",
        "auction": "false",
        "quantity": "30.000000",
        "price": "271.399994",
        "trade_id": "2803586",
        "order_id": "1000000024048887",
        "order_execution_time": "2026-01-05T11:25:11",
    }
    normalized = _normalize_csv_row(row)
    assert normalized["segment"] == "equity"


def test_missing_segment_column_falls_back_to_no_segment_key():
    # Some broker exports (Kotak's, per the module docstring, unverified)
    # may not carry a segment column at all - the caller falls back to
    # derive_segment(exchange) whenever "segment" is absent.
    row = {
        "tradingsymbol": "RELIANCE",
        "exchange": "NSE",
        "trade_type": "buy",
        "quantity": "10",
        "price": "1400",
        "order_id": "123",
        "trade_id": "456",
        "trade_date": "2026-01-05",
        "order_execution_time": "2026-01-05T09:30:00",
    }
    normalized = _normalize_csv_row(row)
    assert "segment" not in normalized


def test_unrecognized_segment_code_is_dropped_not_guessed():
    row = {
        "symbol": "SOMEMF",
        "exchange": "NSE",
        "segment": "XYZ",
        "trade_type": "buy",
        "quantity": "1",
        "price": "10",
        "order_id": "1",
        "trade_id": "2",
        "trade_date": "2026-01-05",
        "order_execution_time": "2026-01-05T09:30:00",
    }
    normalized = _normalize_csv_row(row)
    assert "segment" not in normalized


def test_fno_row_labelled_nse_or_bse_is_stored_as_nfo_or_bfo():
    # Console labels a NIFTY option NSE and a SENSEX option BSE; the capture
    # job stores NFO/BFO, so the import must store the same for one segment
    # to show one set of exchanges.
    from database.pnl_db import normalize_fno_exchange

    assert normalize_fno_exchange("fno", "NSE") == "NFO"
    assert normalize_fno_exchange("fno", "BSE") == "BFO"


def test_fno_exchange_already_derivatives_or_unknown_is_unchanged():
    from database.pnl_db import normalize_fno_exchange

    assert normalize_fno_exchange("fno", "NFO") == "NFO"
    assert normalize_fno_exchange("fno", "BFO") == "BFO"
    assert normalize_fno_exchange("fno", "MCX") == "MCX"
    assert normalize_fno_exchange("fno", None) is None


def test_non_fno_segments_keep_their_exchange():
    # Cash equity really is on NSE/BSE - only F&O rows are relabelled.
    from database.pnl_db import normalize_fno_exchange

    assert normalize_fno_exchange("equity", "NSE") == "NSE"
    assert normalize_fno_exchange("equity", "BSE") == "BSE"
    assert normalize_fno_exchange(None, "NSE") == "NSE"
