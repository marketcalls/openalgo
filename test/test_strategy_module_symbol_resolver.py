"""A strategy leg must become an exact contract before the run starts.

A leg is written relatively - "the ATM call of the weekly expiry, two lots" -
and nothing can be ordered from that. The resolver turns it into one symbol the
master contract confirms exists, with the lot size that contract actually
carries. It has to be right before the first order goes out, because a
multi-leg basket fails leg by leg: by the time leg three is refused, legs one
and two are filled and the position is not the one anybody chose.

The cases below are the ones where being approximately right is indistinguish-
able from being wrong:

* the monthly expiry is the last one of its calendar month, which cannot be
  read off a weekday - NFO moved its monthly from Thursday to Tuesday, MCX
  never had a weekday rule, and a holiday shifts any of them;
* ITM and OTM point in opposite directions for a call and a put, so a sign
  error turns a debit spread into a credit one;
* strikes are not integers (VEDL25APR24292.5CE is a real contract), so an
  int() anywhere names a strike that does not exist;
* the lot size comes from the master contract and nowhere else, since NIFTY has
  been 25, 50 and 75, and a default of 1 would send an order 75 times too
  small; and
* MCX has no spot at all, so a commodity option prices off its near-month
  future or off nothing.

Everything is stubbed: no broker, no network, no downloaded master contract.
The dates are in 2030 so the "not expired" filtering cannot make the suite go
stale.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import expiry_service, option_symbol_service, quotes_service  # noqa: E402
from services.strategy_module.symbol_resolver import (  # noqa: E402
    EXPIRY_RANKS,
    ResolvedLeg,
    resolve_expiry_rank,
    resolve_leg,
    resolve_underlying_ltp,
)

#: A full NFO calendar: four or five weeklies a month, the last of which is the
#: monthly. Deliberately not every month's monthly falls on the same weekday.
NIFTY_EXPIRIES = [
    "03-JAN-30",
    "10-JAN-30",
    "17-JAN-30",
    "24-JAN-30",
    "31-JAN-30",
    "07-FEB-30",
    "14-FEB-30",
    "21-FEB-30",
    "28-FEB-30",
    "07-MAR-30",
    "28-MAR-30",
]

#: 50-point strikes either side of the money.
NIFTY_STRIKES = [23400.0, 23450.0, 23500.0, 23550.0, 23600.0, 23650.0, 23700.0, 23750.0]

#: 23587.50 rounds to a 23600 ATM, and is not itself a listed strike.
NIFTY_LTP = 23587.50

#: A stock ladder in 2.5 point steps, which is where fractional strikes come
#: from. VEDL really does list 292.5.
VEDL_STRIKES = [287.5, 290.0, 292.5, 295.0]
VEDL_LTP = 292.30

#: "argument not supplied", distinct from a supplied None.
UNSET = object()


class FakeMarket:
    """The master contract, the expiry calendar and the tape, in memory.

    Registration is by exception: any symbol is taken to be listed with a
    default lot size unless a test says otherwise, so a test only has to state
    the thing it is actually about.
    """

    def __init__(self):
        self.default_expiries = list(NIFTY_EXPIRIES)
        self.expiries: dict[tuple[str, str, str], list[str]] = {}
        self.default_strikes = list(NIFTY_STRIKES)
        self.strikes: dict[tuple[str, str, str, str], list[float]] = {}
        self.contracts: dict[tuple[str, str], dict] = {}
        self.missing: set[str] = set()
        self.auto_list = True
        self.default_lotsize = 75
        self.futures: dict[tuple[str, str], dict] = {}
        self.prices: dict[tuple[str, str], float] = {}
        self.expiry_calls: list[tuple[str, str, str]] = []
        self.strike_calls: list[tuple[str, str, str, str]] = []
        self.quote_calls: list[tuple[str, str]] = []
        self.lookups: list[tuple[str, str]] = []

    def list_contract(self, symbol, exchange, lotsize=UNSET, tick_size=0.05):
        self.contracts[(symbol, exchange)] = {
            "symbol": symbol,
            "exchange": exchange,
            # A sentinel, not None: a lot size of None is one of the broken
            # rows a test needs to be able to register.
            "lotsize": self.default_lotsize if lotsize is UNSET else lotsize,
            "tick_size": tick_size,
        }

    # -- the stubs themselves -------------------------------------------------

    def get_expiry_dates(self, symbol, exchange, instrumenttype, api_key=None):
        self.expiry_calls.append((symbol, exchange, instrumenttype))
        dates = self.expiries.get((symbol, exchange, instrumenttype), self.default_expiries)
        return True, {"status": "success", "data": list(dates)}, 200

    def get_available_strikes(self, base_symbol, expiry_date, option_type, exchange):
        key = (base_symbol, expiry_date, option_type, exchange)
        self.strike_calls.append(key)
        return list(self.strikes.get(key, self.default_strikes))

    def find_option_in_database(self, symbol, exchange):
        self.lookups.append((symbol, exchange))
        if symbol in self.missing:
            return None
        registered = self.contracts.get((symbol, exchange))
        if registered is not None:
            return registered
        if not self.auto_list:
            return None
        return {
            "symbol": symbol,
            "exchange": exchange,
            "lotsize": self.default_lotsize,
            "tick_size": 0.05,
        }

    def find_near_month_futures(self, base_symbol, exchange):
        return self.futures.get(((base_symbol or "").upper(), (exchange or "").upper()))

    def get_quotes(self, symbol, exchange, api_key=None, **kwargs):
        self.quote_calls.append((symbol, exchange))
        price = self.prices.get((symbol, exchange))
        if price is None:
            return False, {"status": "error", "message": f"No quote for {symbol}"}, 404
        return True, {"status": "success", "data": {"ltp": price}}, 200


@pytest.fixture
def market(monkeypatch):
    """Point the resolver's collaborators at the in-memory market."""
    fake = FakeMarket()
    fake.prices[("NIFTY", "NSE_INDEX")] = NIFTY_LTP
    fake.prices[("VEDL", "NSE")] = VEDL_LTP

    monkeypatch.setattr(expiry_service, "get_expiry_dates", fake.get_expiry_dates)
    monkeypatch.setattr(option_symbol_service, "get_available_strikes", fake.get_available_strikes)
    monkeypatch.setattr(
        option_symbol_service, "find_option_in_database", fake.find_option_in_database
    )
    monkeypatch.setattr(
        option_symbol_service, "find_near_month_futures", fake.find_near_month_futures
    )
    monkeypatch.setattr(quotes_service, "get_quotes", fake.get_quotes)
    return fake


@pytest.fixture
def mcx(market):
    """GOLD on MCX: a near-month future, no spot, its own two calendars."""
    market.futures[("GOLD", "MCX")] = {
        "symbol": "GOLD05AUG30FUT",
        "exchange": "MCX",
        "expiry": "05-AUG-30",
    }
    market.prices[("GOLD05AUG30FUT", "MCX")] = 72500.0
    # The two calendars genuinely differ: the August future expires on the 5th
    # while August options expire on the 28th.
    market.expiries[("GOLD", "MCX", "options")] = ["28-AUG-30", "26-SEP-30"]
    market.expiries[("GOLD", "MCX", "futures")] = ["05-AUG-30", "05-SEP-30"]
    market.strikes[("GOLD", "28AUG30", "CE", "MCX")] = [72000.0, 72500.0, 73000.0]
    market.strikes[("GOLD", "28AUG30", "PE", "MCX")] = [72000.0, 72500.0, 73000.0]
    market.default_lotsize = 100
    return market


def option_leg(**overrides):
    leg = {"segment": "options", "option_type": "CE", "expiry": "weekly", "lots": 1}
    leg.update(overrides)
    return leg


class TestExpiryRanks:
    def test_weekly_is_the_nearest_live_expiry(self, market):
        result = resolve_expiry_rank("NIFTY", "NSE_INDEX", "options", "weekly")
        assert result.ok
        assert result.expiry == "03-JAN-30"

    def test_current_is_a_synonym_for_weekly(self, market):
        """MCX commodities have no weeklies, so the rank has a neutral name."""
        assert resolve_expiry_rank("NIFTY", "NFO", "options", "current").expiry == "03-JAN-30"

    def test_next_week_is_the_one_after(self, market):
        result = resolve_expiry_rank("NIFTY", "NFO", "options", "next_week")
        assert result.expiry == "10-JAN-30"
        assert result.fallback is False

    def test_next_is_a_synonym_for_next_week(self, market):
        assert resolve_expiry_rank("NIFTY", "NFO", "options", "next").expiry == "10-JAN-30"

    def test_monthly_is_the_last_expiry_of_its_month(self, market):
        """Not the nearest, and not a fixed weekday: the last one January has."""
        result = resolve_expiry_rank("NIFTY", "NFO", "options", "monthly")
        assert result.expiry == "31-JAN-30"

    def test_next_month_is_the_monthly_after_that(self, market):
        assert resolve_expiry_rank("NIFTY", "NFO", "options", "next_month").expiry == "28-FEB-30"

    def test_monthly_skips_a_month_whose_monthly_has_gone(self, market):
        """Mid-February, January's monthly is behind us and February's is next."""
        market.default_expiries = ["14-FEB-30", "21-FEB-30", "28-FEB-30", "07-MAR-30", "28-MAR-30"]
        assert resolve_expiry_rank("NIFTY", "NFO", "options", "monthly").expiry == "28-FEB-30"
        assert resolve_expiry_rank("NIFTY", "NFO", "options", "next_month").expiry == "28-MAR-30"

    def test_a_monthly_only_calendar_has_no_weeklies_to_confuse_it(self, market):
        """MCX again: every expiry is the last of its month, so weekly and
        monthly agree and next_week and next_month do too."""
        market.default_expiries = ["28-AUG-30", "26-SEP-30", "29-OCT-30"]
        assert resolve_expiry_rank("GOLD", "MCX", "options", "weekly").expiry == "28-AUG-30"
        assert resolve_expiry_rank("GOLD", "MCX", "options", "monthly").expiry == "28-AUG-30"
        assert resolve_expiry_rank("GOLD", "MCX", "options", "next_week").expiry == "26-SEP-30"
        assert resolve_expiry_rank("GOLD", "MCX", "options", "next_month").expiry == "26-SEP-30"

    @pytest.mark.parametrize("rank", ["next_week", "next"])
    def test_next_week_falls_back_when_only_one_expiry_is_listed(self, market, rank):
        market.default_expiries = ["31-JUL-30"]
        result = resolve_expiry_rank("NIFTY", "NFO", "options", rank)
        assert result.ok
        assert result.expiry == "31-JUL-30"
        assert result.fallback is True, "a fallback must be visible, not silent"

    def test_next_month_falls_back_when_only_one_monthly_is_listed(self, market):
        market.default_expiries = ["03-JAN-30", "10-JAN-30", "31-JAN-30"]
        result = resolve_expiry_rank("NIFTY", "NFO", "options", "next_month")
        assert result.expiry == "31-JAN-30"
        assert result.fallback is True

    def test_both_spellings_of_the_expiry_come_back(self, market):
        """The database stores 03-JAN-30; a symbol embeds 03JAN30."""
        result = resolve_expiry_rank("NIFTY", "NFO", "options", "weekly")
        assert result.expiry == "03-JAN-30"
        assert result.expiry_symbol == "03JAN30"

    def test_a_four_digit_year_still_yields_a_two_digit_symbol_form(self, market):
        market.default_expiries = ["03-JAN-2030"]
        result = resolve_expiry_rank("NIFTY", "NFO", "options", "weekly")
        assert result.expiry_symbol == "03JAN30"

    def test_ranks_are_case_and_separator_insensitive(self, market):
        assert resolve_expiry_rank("NIFTY", "NFO", "options", "Next-Week").expiry == "10-JAN-30"
        assert resolve_expiry_rank("NIFTY", "NFO", "options", " NEXT MONTH ").expiry == "28-FEB-30"

    def test_options_and_futures_ask_for_different_calendars(self, mcx):
        """On MCX they really are different, so the instrument type has to
        reach get_expiry_dates rather than being assumed."""
        assert resolve_expiry_rank("GOLD", "MCX", "options", "current").expiry == "28-AUG-30"
        assert resolve_expiry_rank("GOLD", "MCX", "futures", "current").expiry == "05-AUG-30"
        assert ("GOLD", "MCX", "options") in mcx.expiry_calls
        assert ("GOLD", "MCX", "futures") in mcx.expiry_calls

    def test_an_unknown_rank_is_refused_by_name(self, market):
        result = resolve_expiry_rank("NIFTY", "NFO", "options", "fortnightly")
        assert not result.ok
        assert result.code == "invalid_rank"
        assert "fortnightly" in result.error

    def test_every_documented_rank_resolves(self, market):
        for rank in EXPIRY_RANKS:
            assert resolve_expiry_rank("NIFTY", "NFO", "options", rank).ok, rank

    def test_an_empty_calendar_says_which_symbol_had_none(self, market):
        market.default_expiries = []
        result = resolve_expiry_rank("NIFTY", "NFO", "options", "weekly")
        assert not result.ok
        assert result.code == "no_expiry"
        assert "NIFTY" in result.error and "NFO" in result.error

    def test_expired_and_unparseable_rows_are_ignored(self, market):
        """Master contract dumps carry recently expired rows for days."""
        market.default_expiries = ["01-JAN-20", "not-a-date", "03-JAN-30", "10-JAN-30"]
        result = resolve_expiry_rank("NIFTY", "NFO", "options", "weekly")
        assert result.expiry == "03-JAN-30"
        assert result.available == ("03-JAN-30", "10-JAN-30")

    def test_the_underlying_exchange_maps_to_the_derivatives_one(self, market):
        resolve_expiry_rank("NIFTY", "NSE_INDEX", "options", "weekly")
        resolve_expiry_rank("SENSEX", "BSE_INDEX", "options", "weekly")
        assert ("NIFTY", "NFO", "options") in market.expiry_calls
        assert ("SENSEX", "BFO", "options") in market.expiry_calls


class TestUnderlyingReference:
    def test_an_index_option_prices_off_the_spot_index(self, market):
        quote = resolve_underlying_ltp("NIFTY", "NSE_INDEX")
        assert quote.ok
        assert (quote.symbol, quote.exchange) == ("NIFTY", "NSE_INDEX")
        assert quote.ltp == NIFTY_LTP

    def test_a_stock_option_prices_off_the_cash_equity(self, market):
        quote = resolve_underlying_ltp("VEDL", "NSE")
        assert (quote.symbol, quote.exchange) == ("VEDL", "NSE")

    def test_an_mcx_option_prices_off_the_near_month_future(self, mcx):
        """MCX lists GOLD05AUG30FUT and no plain GOLD, so a spot quote can only
        ever fail. The underlying IS the future."""
        quote = resolve_underlying_ltp("GOLD", "MCX")
        assert quote.ok
        assert quote.symbol == "GOLD05AUG30FUT"
        assert quote.symbol.endswith("FUT")
        assert quote.exchange == "MCX"
        assert mcx.quote_calls == [("GOLD05AUG30FUT", "MCX")]
        assert ("GOLD", "MCX") not in mcx.quote_calls

    def test_an_mcx_product_with_no_live_future_says_so(self, market):
        quote = resolve_underlying_ltp("CRUDEOIL", "MCX")
        assert not quote.ok
        assert quote.code == "no_underlying_contract"
        assert "CRUDEOIL" in quote.error
        assert market.quote_calls == [], "nothing to quote, so nothing was asked"

    def test_a_derivatives_exchange_is_refused_rather_than_guessed_at(self, market):
        quote = resolve_underlying_ltp("NIFTY", "NFO")
        assert not quote.ok
        assert quote.code == "invalid_underlying_exchange"

    def test_a_missing_price_is_a_failure_not_a_zero(self, market):
        quote = resolve_underlying_ltp("BANKNIFTY", "NSE_INDEX")
        assert not quote.ok
        assert quote.code == "quote_failed"


class TestAtmOffsets:
    """ITM and OTM run in opposite directions for a call and a put."""

    @pytest.mark.parametrize(
        ("offset", "expected"),
        [("ATM", 23600.0), ("ITM1", 23550.0), ("ITM2", 23500.0), ("OTM1", 23650.0)],
    )
    def test_a_call_walks_down_for_itm_and_up_for_otm(self, market, offset, expected):
        leg = resolve_leg(
            option_leg(option_type="CE", atm_offset=offset), "NIFTY", "NSE_INDEX", "custom"
        )
        assert leg.ok, leg.error
        assert leg.strike == expected
        assert leg.atm_strike == 23600.0

    @pytest.mark.parametrize(
        ("offset", "expected"),
        [("ATM", 23600.0), ("ITM1", 23650.0), ("ITM2", 23700.0), ("OTM1", 23550.0)],
    )
    def test_a_put_walks_up_for_itm_and_down_for_otm(self, market, offset, expected):
        leg = resolve_leg(
            option_leg(option_type="PE", atm_offset=offset), "NIFTY", "NSE_INDEX", "custom"
        )
        assert leg.ok, leg.error
        assert leg.strike == expected

    def test_the_two_directions_are_mirror_images(self, market):
        call = resolve_leg(option_leg(option_type="CE", atm_offset="ITM2"), "NIFTY", "NSE_INDEX")
        put = resolve_leg(option_leg(option_type="PE", atm_offset="ITM2"), "NIFTY", "NSE_INDEX")
        assert call.strike < call.atm_strike < put.strike
        assert put.strike - call.atm_strike == call.atm_strike - call.strike

    def test_the_symbol_carries_the_offset_strike(self, market):
        leg = resolve_leg(option_leg(atm_offset="OTM1"), "NIFTY", "NSE_INDEX")
        assert leg.symbol == "NIFTY03JAN3023650CE"
        assert leg.exchange == "NFO"

    def test_a_supplied_price_is_used_instead_of_a_fresh_quote(self, market):
        """Every leg of one basket must be measured against the same tick."""
        leg = resolve_leg(option_leg(), "NIFTY", "NSE_INDEX", "straddle", underlying_ltp=23423.0)
        assert leg.ok
        assert leg.atm_strike == 23400.0
        assert market.quote_calls == []

    def test_an_offset_off_the_end_of_the_chain_is_refused(self, market):
        leg = resolve_leg(option_leg(atm_offset="OTM5"), "NIFTY", "NSE_INDEX")
        assert not leg.ok
        assert leg.code == "offset_out_of_range"

    def test_an_unsupported_offset_is_named(self, market):
        leg = resolve_leg(option_leg(atm_offset="ITM6"), "NIFTY", "NSE_INDEX")
        assert not leg.ok
        assert leg.code == "invalid_offset"
        assert "ITM6" in leg.error

    def test_an_unsupported_option_type_is_refused_not_treated_as_a_put(self, market):
        leg = resolve_leg(option_leg(option_type="CALL"), "NIFTY", "NSE_INDEX")
        assert not leg.ok
        assert "option_type" in leg.error

    def test_a_strike_interval_switches_to_the_arithmetic_path(self, market):
        """Supplying strike_int is the legacy method and must still agree."""
        leg = resolve_leg(option_leg(atm_offset="ITM2", strike_int=50), "NIFTY", "NSE_INDEX")
        assert leg.ok, leg.error
        assert leg.strike == 23500.0
        assert market.strike_calls == [], "the listed-strike path was not needed"


class TestFractionalStrikes:
    """VEDL25APR24292.5CE is a real contract. An int() anywhere loses it."""

    @pytest.fixture(autouse=True)
    def vedl(self, market):
        market.default_expiries = ["25-APR-30"]
        market.default_strikes = list(VEDL_STRIKES)
        market.default_lotsize = 1150
        return market

    def test_a_fractional_atm_strike_survives_into_the_symbol(self, market):
        leg = resolve_leg(option_leg(), "VEDL", "NSE", "custom")
        assert leg.ok, leg.error
        assert leg.strike == 292.5
        assert leg.symbol == "VEDL25APR30292.5CE"

    def test_a_fractional_strike_named_outright_survives(self, market):
        leg = resolve_leg(option_leg(strike_mode="strike", strike=292.5), "VEDL", "NSE", "custom")
        assert leg.ok, leg.error
        assert leg.strike == 292.5
        assert leg.symbol.endswith("292.5CE")

    def test_a_fractional_offset_strike_survives(self, market):
        leg = resolve_leg(option_leg(atm_offset="OTM1"), "VEDL", "NSE")
        assert leg.strike == 295.0
        assert leg.symbol == "VEDL25APR30295CE", "a whole strike carries no trailing .0"

    def test_the_strike_is_not_truncated_to_an_int(self, market):
        leg = resolve_leg(option_leg(), "VEDL", "NSE")
        assert leg.strike != 292
        assert "292.5" in leg.symbol


class TestQuantityAndLotSize:
    def test_quantity_is_lots_times_the_master_contract_lot_size(self, market):
        market.list_contract("NIFTY03JAN3023600CE", "NFO", lotsize=75)
        leg = resolve_leg(option_leg(lots=3), "NIFTY", "NSE_INDEX", "straddle")
        assert leg.ok, leg.error
        assert (leg.lots, leg.lotsize, leg.quantity) == (3, 75, 225)

    def test_the_lot_size_is_read_and_never_assumed(self, market):
        """NIFTY has been 25, 50 and 75. Whatever the contract says wins."""
        market.list_contract("NIFTY03JAN3023600CE", "NFO", lotsize=25)
        leg = resolve_leg(option_leg(lots=2), "NIFTY", "NSE_INDEX")
        assert leg.quantity == 50

    def test_lots_default_to_one(self, market):
        leg = resolve_leg({"segment": "options", "option_type": "CE"}, "NIFTY", "NSE_INDEX")
        assert leg.ok, leg.error
        assert leg.lots == 1
        assert leg.quantity == leg.lotsize

    @pytest.mark.parametrize("lotsize", [0, -50, None, "75"])
    def test_an_unusable_lot_size_is_a_hard_failure(self, market, lotsize):
        """Never a silent 1: that would send an order 75 times too small."""
        market.list_contract("NIFTY03JAN3023600CE", "NFO", lotsize=lotsize)
        leg = resolve_leg(option_leg(lots=2), "NIFTY", "NSE_INDEX")
        assert not leg.ok
        assert leg.code == "invalid_lotsize"
        assert leg.quantity is None
        assert "NIFTY03JAN3023600CE" in leg.error

    @pytest.mark.parametrize("lots", [0, -1, 1.5, "two", True])
    def test_an_unusable_lot_count_is_refused(self, market, lots):
        leg = resolve_leg(option_leg(lots=lots), "NIFTY", "NSE_INDEX")
        assert not leg.ok
        assert leg.code == "invalid_lots"

    def test_the_tick_size_comes_from_the_contract(self, market):
        market.list_contract("NIFTY03JAN3023600CE", "NFO", tick_size=0.05)
        assert resolve_leg(option_leg(), "NIFTY", "NSE_INDEX").tick_size == 0.05


class TestMissingContract:
    def test_a_missing_option_names_exactly_what_was_looked_for(self, market):
        market.missing.add("NIFTY31JAN3024000CE")
        leg = resolve_leg(
            option_leg(strike_mode="strike", strike=24000, expiry="31-JAN-30"),
            "NIFTY",
            "NSE_INDEX",
            "custom",
        )
        assert not leg.ok
        assert leg.code == "contract_not_found"
        assert "No option contract found for NIFTY 31-JAN-30 24000 CE on NFO" in leg.error
        assert "NIFTY31JAN3024000CE" in leg.error

    def test_a_failure_is_a_value_and_not_an_exception(self, market):
        market.auto_list = False
        leg = resolve_leg(option_leg(), "NIFTY", "NSE_INDEX")
        assert isinstance(leg, ResolvedLeg)
        assert not leg.ok

    def test_a_failure_carries_no_half_built_quantity(self, market):
        market.auto_list = False
        leg = resolve_leg(option_leg(lots=2), "NIFTY", "NSE_INDEX")
        assert leg.quantity is None
        assert leg.lotsize is None

    def test_an_empty_chain_is_reported_before_a_symbol_is_invented(self, market):
        market.default_strikes = []
        leg = resolve_leg(option_leg(), "NIFTY", "NSE_INDEX")
        assert not leg.ok
        assert leg.code == "no_strikes"

    def test_an_unusable_strike_is_refused(self, market):
        leg = resolve_leg(option_leg(strike_mode="strike", strike=0), "NIFTY", "NSE_INDEX")
        assert not leg.ok
        assert leg.code == "invalid_strike"


class TestSegments:
    def test_a_cash_leg_is_the_underlying_equity_itself(self, market):
        market.list_contract("RELIANCE", "NSE", lotsize=1, tick_size=0.05)
        leg = resolve_leg({"segment": "cash", "lots": 10}, "RELIANCE", "NSE", "custom")
        assert leg.ok, leg.error
        assert (leg.symbol, leg.exchange) == ("RELIANCE", "NSE")
        assert leg.quantity == 10
        assert leg.strike is None and leg.expiry is None

    def test_a_cash_leg_on_an_index_is_refused_in_plain_words(self, market):
        market.auto_list = False
        leg = resolve_leg({"segment": "cash"}, "NIFTY", "NSE_INDEX")
        assert not leg.ok
        assert "No cash contract found for NIFTY on NSE" in leg.error

    def test_a_futures_leg_builds_base_expiry_fut(self, market):
        leg = resolve_leg({"segment": "futures", "expiry": "monthly", "lots": 2}, "NIFTY", "NFO")
        assert leg.ok, leg.error
        assert leg.symbol == "NIFTY31JAN30FUT"
        assert leg.exchange == "NFO"
        assert leg.expiry == "31-JAN-30"
        assert leg.strike is None

    def test_a_futures_leg_is_verified_against_the_master_contract(self, market):
        market.missing.add("NIFTY31JAN30FUT")
        leg = resolve_leg({"segment": "futures", "expiry": "monthly"}, "NIFTY", "NSE_INDEX")
        assert not leg.ok
        assert leg.code == "contract_not_found"
        assert "NIFTY31JAN30FUT" in leg.error

    def test_a_futures_leg_uses_the_futures_calendar(self, mcx):
        leg = resolve_leg({"segment": "futures", "expiry": "current"}, "GOLD", "MCX")
        assert leg.symbol == "GOLD05AUG30FUT"
        assert ("GOLD", "MCX", "futures") in mcx.expiry_calls

    def test_an_unknown_segment_is_refused(self, market):
        leg = resolve_leg({"segment": "swaps"}, "NIFTY", "NSE_INDEX")
        assert not leg.ok
        assert leg.code == "invalid_segment"

    def test_camelcase_leg_keys_are_understood(self, market):
        leg = resolve_leg(
            {"segment": "options", "optionType": "PE", "strikeMode": "atm", "atmOffset": "OTM1"},
            "NIFTY",
            "NSE_INDEX",
        )
        assert leg.ok, leg.error
        assert leg.symbol == "NIFTY03JAN3023550PE"


class TestMcxOptionLeg:
    def test_an_mcx_option_leg_resolves_against_its_future(self, mcx):
        leg = resolve_leg(
            option_leg(option_type="CE", expiry="current", lots=2), "GOLD", "MCX", "straddle"
        )
        assert leg.ok, leg.error
        assert leg.symbol == "GOLD28AUG3072500CE"
        assert leg.exchange == "MCX"
        assert leg.expiry == "28-AUG-30"
        assert leg.quantity == 200
        assert leg.underlying_ltp == 72500.0
        assert mcx.quote_calls == [("GOLD05AUG30FUT", "MCX")]

    def test_the_option_expiry_is_not_the_futures_expiry(self, mcx):
        """The quote comes from the 5th; the contract expires on the 28th."""
        leg = resolve_leg(option_leg(expiry="current"), "GOLD", "MCX")
        assert leg.expiry == "28-AUG-30"
        assert leg.detail["quote_symbol"] == "GOLD05AUG30FUT"

    def test_a_commodity_with_no_future_cannot_price_its_options(self, market):
        market.expiries[("SILVER", "MCX", "options")] = ["28-AUG-30"]
        leg = resolve_leg(option_leg(expiry="current"), "SILVER", "MCX")
        assert not leg.ok
        assert leg.code == "no_underlying_contract"
        assert "SILVER" in leg.error


class TestResultShape:
    def test_a_resolved_leg_carries_everything_an_order_needs(self, market):
        leg = resolve_leg(option_leg(lots=2, action="SELL"), "NIFTY", "NSE_INDEX", "short_straddle")
        assert leg.ok, leg.error
        payload = leg.as_dict()
        for key in ("symbol", "exchange", "lotsize", "tick_size", "strike", "expiry", "quantity"):
            assert payload[key] is not None, key
        assert payload["action"] == "SELL"
        assert payload["strategy_type"] == "short_straddle"
        assert payload["underlying"] == "NIFTY"
        assert payload["expiry_symbol"] == "03JAN30"

    def test_a_leg_that_is_not_a_mapping_is_refused(self, market):
        leg = resolve_leg(["options"], "NIFTY", "NSE_INDEX")
        assert not leg.ok
        assert leg.code == "invalid_leg"
