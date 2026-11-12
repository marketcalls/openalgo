"""Issue #2388: cash symbols ending in CE or PE must get the equity MPP slab.

get_instrument_type_from_symbol used to decide from the last two letters, so
RELIANCE, BAJFINANCE, PRINCEPIPE and REDTAPE were treated as options and a
MARKET order converted to LIMIT got the options buffer (RELIANCE at 1339.7 was
sent at 1353.1 instead of 1346.4).
"""

import pytest

from utils.mpp_slab import (
    calculate_protected_price,
    get_instrument_type_from_symbol,
    get_mpp_info,
    get_mpp_percentage,
    is_option_instrument_type,
)

# NSE/BSE symbols from the master contract that end in CE or PE.
CASH_SYMBOLS_ENDING_CE_PE = [
    "RELIANCE",
    "BAJFINANCE",
    "PRINCEPIPE",
    "REDTAPE",
    "DEFENCE",
    "MODEFENCE",
    "FINPIPE",
    "ENDURANCE",
    "RACE",
    "ACE",
    "ADVANCE",
    "ONESOURCE",
    "DIGISPICE",
    "KESARPE",
    "NIEHSPE",
    "MINDSPACE",
]


class TestCashSymbols:
    @pytest.mark.parametrize("symbol", CASH_SYMBOLS_ENDING_CE_PE)
    def test_symbol_alone_is_equity(self, symbol):
        assert get_instrument_type_from_symbol(symbol) == "EQ"

    @pytest.mark.parametrize("exchange", ["NSE", "BSE", "nse"])
    @pytest.mark.parametrize("symbol", ["RELIANCE", "PRINCEPIPE", "NIFTY28MAR2420800CE"])
    def test_cash_exchange_is_always_equity(self, symbol, exchange):
        assert get_instrument_type_from_symbol(symbol, exchange) == "EQ"

    def test_plain_equity_unchanged(self):
        assert get_instrument_type_from_symbol("SBIN") == "EQ"
        assert get_instrument_type_from_symbol("INFY", "NSE") == "EQ"


class TestDerivativeSymbols:
    @pytest.mark.parametrize(
        "symbol, exchange, expected",
        [
            ("NIFTY28MAR2420800CE", "NFO", "CE"),
            ("NIFTY28MAR2420800PE", "NFO", "PE"),
            ("BANKNIFTY24APR2448000CE", None, "CE"),
            ("VEDL25APR24292.5CE", "NFO", "CE"),
            ("SENSEX28MAR2472000PE", "BFO", "PE"),
            ("CRUDEOIL17APR246750CE", "MCX", "CE"),
            ("USDINR10MAY2482.5PE", "CDS", "PE"),
            ("RELIANCE28MAR241400CE", "NFO", "CE"),
            ("M&M28MAR241800PE", "NFO", "PE"),
            ("BANKNIFTY24APR24FUT", "NFO", "FUT"),
            ("CRUDEOILM20MAY24FUT", "MCX", "FUT"),
            ("USDINR26APR24FUT", "CDS", "FUT"),
            ("BAJAJ-AUTO28MAR24FUT", None, "FUT"),
        ],
    )
    def test_derivative_type(self, symbol, exchange, expected):
        assert get_instrument_type_from_symbol(symbol, exchange) == expected

    def test_lowercase_symbol(self):
        assert get_instrument_type_from_symbol("nifty28mar2420800ce", "NFO") == "CE"

    def test_empty_symbol_is_equity(self):
        assert get_instrument_type_from_symbol("") == "EQ"
        assert get_instrument_type_from_symbol(None) == "EQ"


class TestMasterContractTypes:
    @pytest.mark.parametrize(
        "itype", ["CE", "PE", "OPTIDX", "OPTSTK", "OPTFUT", "OPTCUR", "optidx"]
    )
    def test_option_types(self, itype):
        assert is_option_instrument_type(itype)
        assert get_mpp_percentage(50, itype) == 3.0

    @pytest.mark.parametrize("itype", ["EQ", "FUT", "FUTIDX", "FUTSTK", "FUTCOM", "", None])
    def test_non_option_types(self, itype):
        assert not is_option_instrument_type(itype)


class TestProtectedPrice:
    def test_reliance_live_case_from_flattrade(self):
        # Live Flattrade log: LTP 1339.7, tick 0.1, BUY went out at 1353.1 (1%).
        assert calculate_protected_price(1339.7, "BUY", symbol="RELIANCE", tick_size=0.1) == 1346.4

    @pytest.mark.parametrize(
        "symbol, ltp, tick, buy, sell",
        [
            ("RELIANCE", 1400, 0.1, 1407.0, 1393.0),  # > 500: 0.5%
            ("REDTAPE", 108.5, 0.05, 109.6, 107.4),  # 100-500: 1%
            ("DEFENCE", 78.0, 0.05, 79.55, 76.45),  # < 100: 2%
        ],
    )
    def test_cash_symbols_get_equity_buffer(self, symbol, ltp, tick, buy, sell):
        assert calculate_protected_price(ltp, "BUY", symbol=symbol, tick_size=tick) == buy
        assert calculate_protected_price(ltp, "SELL", symbol=symbol, tick_size=tick) == sell

    def test_option_keeps_option_buffer(self):
        # 5 -> 5% options slab
        assert (
            calculate_protected_price(5, "BUY", symbol="NIFTY28MAR2420800CE", tick_size=0.05)
            == 5.25
        )

    def test_exchange_argument_passed_through(self):
        assert (
            calculate_protected_price(1400, "BUY", symbol="RELIANCE", tick_size=0.1, exchange="NSE")
            == 1407.0
        )

    def test_explicit_instrument_type_still_wins(self):
        assert (
            calculate_protected_price(
                1400, "BUY", symbol="RELIANCE", instrument_type="CE", tick_size=0.1
            )
            == 1414.0
        )

    def test_mpp_info(self):
        info = get_mpp_info(1400, symbol="PRINCEPIPE", tick_size=0.05)
        assert info["instrument_type"] == "EQ"
        assert info["slab_type"] == "EQ/FUT"
        assert info["percentage"] == 0.5


class TestBrokerCallSite:
    """Flattrade's real transform_data, unchanged, now prices RELIANCE as equity."""

    def test_flattrade_market_buy_reliance(self, monkeypatch):
        import broker.flattrade.mapping.transform_data as td

        class FakeBrokerData:
            def __init__(self, auth_token):
                pass

            def get_quotes(self, symbol, exchange):
                return {"ltp": 1339.7, "bid": 1339.7, "ask": 0.0, "tick_size": 0.1}

        monkeypatch.setattr(td, "BrokerData", FakeBrokerData)
        monkeypatch.setattr(td, "get_br_symbol", lambda symbol, exchange: f"{symbol}-EQ")

        out = td.transform_data(
            {
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "action": "BUY",
                "quantity": "1",
                "pricetype": "MARKET",
                "product": "CNC",
                "price": "0",
                "trigger_price": "0",
                "apikey": "x",
            },
            token="2885",
            auth_token="dummy",
        )
        assert out["prctyp"] == "LMT"
        assert float(out["prc"]) == 1346.4
