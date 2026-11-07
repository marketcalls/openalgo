import pytest

from utils.mpp_slab import (
    calculate_protected_price,
    get_instrument_type_from_symbol,
    get_mpp_info,
    get_mpp_percentage,
)


class TestInstrumentTypeFromSymbol:
    """Cash symbols ending in CE or PE are equity, not options (issue #2388)."""

    @pytest.mark.parametrize("symbol", ["RELIANCE", "BAJFINANCE", "PRINCEPIPE", "SBIN"])
    @pytest.mark.parametrize("exchange", ["NSE", "BSE", "nse"])
    def test_cash_exchange_is_always_equity(self, symbol, exchange):
        assert get_instrument_type_from_symbol(symbol, exchange) == "EQ"

    @pytest.mark.parametrize(
        "symbol, exchange, expected",
        [
            ("NIFTY28MAR2420800CE", "NFO", "CE"),
            ("NIFTY28MAR2420800PE", "NFO", "PE"),
            ("SENSEX28MAR2475000CE", "BFO", "CE"),
            ("BANKNIFTY24APR24FUT", "NFO", "FUT"),
            ("CRUDEOILM20MAY24FUT", "MCX", "FUT"),
            ("USDINR28MAR2483.5PE", "CDS", "PE"),
        ],
    )
    def test_derivative_exchange_uses_suffix(self, symbol, exchange, expected):
        assert get_instrument_type_from_symbol(symbol, exchange) == expected

    def test_without_exchange_keeps_suffix_rule(self):
        assert get_instrument_type_from_symbol("NIFTY28MAR2420800CE") == "CE"
        assert get_instrument_type_from_symbol("INFY") == "EQ"


class TestMasterContractOptionTypes:
    """Master contract types such as OPTIDX and OPTSTK use the options slabs."""

    @pytest.mark.parametrize("instrument_type", ["OPTIDX", "OPTSTK", "OPTFUT", "OPTCUR", "optidx"])
    def test_opt_types_use_options_slabs(self, instrument_type):
        assert get_mpp_percentage(5, instrument_type) == 5.0
        assert get_mpp_percentage(1000, instrument_type) == 1.0

    @pytest.mark.parametrize("instrument_type", ["FUTIDX", "FUTSTK", "FUTCOM", "EQ", ""])
    def test_non_option_types_use_equity_slabs(self, instrument_type):
        assert get_mpp_percentage(1000, instrument_type) == 0.5


class TestProtectedPriceUsesExchange:
    def test_reliance_on_nse_gets_equity_buffer(self):
        # Equity slab above 500 is 0.5%; the options slab would have given 1%.
        assert calculate_protected_price(1400, "BUY", symbol="RELIANCE", exchange="NSE") == 1407.0

    def test_cheap_equity_ending_in_pe_gets_equity_buffer(self):
        # Equity slab under 100 is 2%; the options slab would have given 3%.
        assert calculate_protected_price(50, "SELL", symbol="PRINCEPIPE", exchange="NSE") == 49.0

    def test_option_on_nfo_still_gets_options_buffer(self):
        assert (
            calculate_protected_price(5, "BUY", symbol="NIFTY28MAR2420800CE", exchange="NFO")
            == 5.25
        )

    def test_mpp_info_reports_equity_for_cash_symbol(self):
        info = get_mpp_info(1400, symbol="BAJFINANCE", exchange="NSE")
        assert info["instrument_type"] == "EQ"
        assert info["slab_type"] == "EQ/FUT"
        assert info["percentage"] == 0.5
