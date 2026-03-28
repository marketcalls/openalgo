# test/test_ai_symbol_mapper.py
import pytest
from ai.symbol_mapper import to_openalgo, to_yfinance, parse_openalgo_symbol


def test_to_yfinance_nse_equity():
    assert to_yfinance("RELIANCE", "NSE") == "RELIANCE.NS"


def test_to_yfinance_bse_equity():
    assert to_yfinance("RELIANCE", "BSE") == "RELIANCE.BO"


def test_to_openalgo_from_yfinance():
    symbol, exchange = to_openalgo("RELIANCE.NS")
    assert symbol == "RELIANCE"
    assert exchange == "NSE"


def test_to_openalgo_from_yfinance_bse():
    symbol, exchange = to_openalgo("RELIANCE.BO")
    assert symbol == "RELIANCE"
    assert exchange == "BSE"


def test_to_openalgo_no_suffix():
    symbol, exchange = to_openalgo("RELIANCE")
    assert symbol == "RELIANCE"
    assert exchange == "NSE"  # default


def test_to_yfinance_nfo():
    assert to_yfinance("NIFTY24JAN24000CE", "NFO") == "NIFTY24JAN24000CE.NS"


def test_parse_openalgo_symbol_with_exchange_prefix():
    symbol, exchange = parse_openalgo_symbol("NSE:RELIANCE")
    assert symbol == "RELIANCE"
    assert exchange == "NSE"


def test_parse_openalgo_symbol_plain():
    symbol, exchange = parse_openalgo_symbol("RELIANCE")
    assert symbol == "RELIANCE"
    assert exchange == "NSE"
