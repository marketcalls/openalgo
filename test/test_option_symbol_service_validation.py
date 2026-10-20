"""The option-symbol resolver refuses unusable strikes and option types.

Two defects lived in the strike calculations. The legacy strike_int path
divided the underlying LTP by the caller's interval with no guard, so a zero
interval raised ZeroDivisionError and a NaN or infinite one produced a strike
that formats into a symbol no exchange lists. Separately, every offset
calculation branches on CE and treats anything else as a put, so an option
type of "CALL", "C" or None resolved to the put strike. The symbol built
around it then failed the master-contract lookup, so the caller saw a
confusing "not found in NFO" where the real fault was the option type.

The REST schema validates both fields, but services/flow_openalgo_client.py
calls get_option_symbol() in process and bypasses it, so the fix and these
tests sit at the resolver boundary rather than in the schema.

The tests are fully local: no broker credentials, no network, and no database
rows - the quote fetch and the symbol lookup are stubbed.
"""

import math
import os
import sys
from decimal import Decimal

import numpy
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import option_symbol_service as oss  # noqa: E402
from services.option_symbol_service import (  # noqa: E402
    VALID_OPTION_TYPES,
    calculate_offset_strike,
    calculate_offset_strike_from_actual,
    find_atm_strike_from_actual,
    get_atm_strike,
    get_option_symbol,
    validate_option_type,
    validate_strike_interval,
)

#: A realistic NIFTY chain: 50-point strikes either side of a 23600 ATM.
STRIKES = [23400.0, 23450.0, 23500.0, 23550.0, 23600.0, 23650.0, 23700.0, 23750.0]

#: Values that are not a usable divisor. Zero and the negatives are the
#: reported defect; True is included because bool is an int subclass and would
#: otherwise slip through as an interval of 1.
UNUSABLE_INTERVALS = [
    0,
    0.0,
    -50,
    -0.5,
    float("nan"),
    float("inf"),
    float("-inf"),
    None,
    "50",
    "",
    True,
    [50],
    #: math.isfinite() raises rather than returning False for these two: an int
    #: too large to convert to a float raises OverflowError, and a signalling
    #: NaN raises ValueError. Both are reachable from the public endpoint.
    10**400,
    Decimal("sNaN"),
]

#: Everything the resolver must refuse rather than silently price as a put.
UNSUPPORTED_OPTION_TYPES = ["CALL", "PUT", "C", "P", "XX", "", "  ", None, 0, 1, ["CE"]]


class TestValidateOptionType:
    @pytest.mark.parametrize(
        ("supplied", "expected"),
        [("CE", "CE"), ("PE", "PE"), ("ce", "CE"), ("pe", "PE"), ("Ce", "CE"), (" pe ", "PE")],
    )
    def test_supported_types_normalize_to_canonical_case(self, supplied, expected):
        assert validate_option_type(supplied) == expected

    @pytest.mark.parametrize("supplied", UNSUPPORTED_OPTION_TYPES)
    def test_unsupported_types_raise(self, supplied):
        with pytest.raises(ValueError, match="option_type"):
            validate_option_type(supplied)

    def test_only_ce_and_pe_are_supported(self):
        assert VALID_OPTION_TYPES == ("CE", "PE")


class TestValidateStrikeInterval:
    @pytest.mark.parametrize("interval", [1, 50, 100, 2.5, 0.05])
    def test_positive_finite_intervals_keep_their_value(self, interval):
        assert validate_strike_interval(interval) == interval

    @pytest.mark.parametrize("interval", UNUSABLE_INTERVALS)
    def test_unusable_intervals_raise(self, interval):
        with pytest.raises(ValueError, match="strike_int"):
            validate_strike_interval(interval)

    def test_a_numpy_scalar_is_accepted(self):
        """np.int64 is not an int, but it divides an LTP perfectly well."""
        assert validate_strike_interval(numpy.int64(50)) == 50

    @pytest.mark.parametrize("interval", [50, 2.5, numpy.int64(50), Decimal("50")])
    def test_an_accepted_interval_is_returned_as_a_usable_divisor(self, interval):
        """The point of the validator is that the next line can divide by it.

        Decimal is the case that proves it: finite and positive, so it passes
        the checks, but float / Decimal raises TypeError.
        """
        validated = validate_strike_interval(interval)

        assert isinstance(validated, float)
        assert 23587.50 / validated == 23587.50 / float(interval)

    def test_a_decimal_interval_resolves_the_same_strike_as_an_int(self):
        assert get_atm_strike(23587.50, Decimal("50")) == get_atm_strike(23587.50, 50)


class TestGetAtmStrike:
    @pytest.mark.parametrize(
        ("ltp", "interval", "expected"),
        [
            (23587.50, 50, 23600),
            (23574.00, 50, 23550),
            (292.30, 2.5, 292.5),
            (44000.00, 100, 44000),
        ],
    )
    def test_valid_input_is_unaffected(self, ltp, interval, expected):
        assert get_atm_strike(ltp, interval) == pytest.approx(expected)

    @pytest.mark.parametrize("interval", UNUSABLE_INTERVALS)
    def test_unusable_interval_raises_valueerror_not_zerodivisionerror(self, interval):
        """ValueError is what get_option_symbol() answers as HTTP 400."""
        with pytest.raises(ValueError, match="strike_int"):
            get_atm_strike(23587.50, interval)


class TestCalculateOffsetStrike:
    """The legacy strike_int path."""

    @pytest.mark.parametrize(
        ("offset", "option_type", "expected"),
        [
            ("ATM", "CE", 23600),
            ("ATM", "PE", 23600),
            ("ITM2", "CE", 23500),
            ("OTM2", "CE", 23700),
            ("ITM2", "PE", 23700),
            ("OTM2", "PE", 23500),
            ("itm1", "ce", 23550),
            ("otm1", "pe", 23550),
        ],
    )
    def test_valid_calls_and_puts_are_unchanged(self, offset, option_type, expected):
        assert calculate_offset_strike(23600, offset, 50, option_type) == pytest.approx(expected)

    @pytest.mark.parametrize("option_type", UNSUPPORTED_OPTION_TYPES)
    def test_unsupported_option_type_is_rejected_not_treated_as_a_put(self, option_type):
        with pytest.raises(ValueError, match="option_type"):
            calculate_offset_strike(23600, "ITM2", 50, option_type)

    @pytest.mark.parametrize("interval", UNUSABLE_INTERVALS)
    def test_unusable_interval_is_rejected(self, interval):
        with pytest.raises(ValueError, match="strike_int"):
            calculate_offset_strike(23600, "ITM2", interval, "CE")

    def test_unknown_offset_still_raises(self):
        with pytest.raises(ValueError, match="offset"):
            calculate_offset_strike(23600, "DEEP3", 50, "CE")


class TestFindAtmStrikeFromActual:
    @pytest.mark.parametrize(
        ("ltp", "expected"), [(23587.50, 23600.0), (23574.00, 23550.0), (23400.0, 23400.0)]
    )
    def test_nearest_strike_is_unchanged(self, ltp, expected):
        assert find_atm_strike_from_actual(ltp, STRIKES) == expected

    @pytest.mark.parametrize("ltp", [float("nan"), float("inf"), float("-inf"), None, "23587.50"])
    def test_non_finite_ltp_returns_none_instead_of_the_first_strike(self, ltp):
        """NaN compares false against every strike, so min() returned STRIKES[0]."""
        assert find_atm_strike_from_actual(ltp, STRIKES) is None

    def test_a_numpy_ltp_still_resolves(self):
        assert find_atm_strike_from_actual(numpy.float64(23587.50), STRIKES) == 23600.0


class TestCalculateOffsetStrikeFromActual:
    """The actual-strikes path, which shares the same CE/else branching."""

    @pytest.mark.parametrize(
        ("offset", "option_type", "expected"),
        [
            ("ATM", "CE", 23600.0),
            ("ITM2", "CE", 23500.0),
            ("OTM2", "CE", 23700.0),
            ("ITM2", "PE", 23700.0),
            ("OTM2", "PE", 23500.0),
            ("itm1", "ce", 23550.0),
        ],
    )
    def test_valid_calls_and_puts_are_unchanged(self, offset, option_type, expected):
        assert (
            calculate_offset_strike_from_actual(23600.0, offset, option_type, STRIKES) == expected
        )

    @pytest.mark.parametrize("option_type", UNSUPPORTED_OPTION_TYPES)
    def test_unsupported_option_type_is_rejected_not_treated_as_a_put(self, option_type):
        with pytest.raises(ValueError, match="option_type"):
            calculate_offset_strike_from_actual(23600.0, "ITM2", option_type, STRIKES)

    def test_offset_out_of_range_still_returns_none(self):
        assert calculate_offset_strike_from_actual(23600.0, "OTM9", "CE", STRIKES) is None

    def test_unknown_offset_still_returns_none(self):
        assert calculate_offset_strike_from_actual(23600.0, "DEEP3", "CE", STRIKES) is None


@pytest.fixture
def stub_resolver(monkeypatch):
    """Stub every outbound call get_option_symbol() makes.

    Returns the list of quote requests, so a test can assert that a rejected
    request never reached the broker.
    """
    import database.qty_freeze_db as qty_freeze_db

    quote_calls = []

    def fake_get_quotes(symbol, exchange, api_key):
        quote_calls.append((symbol, exchange))
        return True, {"status": "success", "data": {"ltp": 23587.50}}, 200

    monkeypatch.setattr(oss, "get_quotes", fake_get_quotes)
    monkeypatch.setattr(oss, "get_available_strikes", lambda *args, **kwargs: list(STRIKES))
    monkeypatch.setattr(
        oss,
        "find_option_in_database",
        lambda symbol, exchange: {
            "symbol": symbol,
            "exchange": exchange,
            "lotsize": 75,
            "tick_size": 0.05,
        },
    )
    monkeypatch.setattr(qty_freeze_db, "get_freeze_qty_for_option", lambda symbol, exchange: 1800)
    return quote_calls


class TestGetOptionSymbolBoundary:
    """Both legacy paths reject at the boundary, before any broker call."""

    def _request(self, **overrides):
        request = {
            "underlying": "NIFTY",
            "exchange": "NSE_INDEX",
            "expiry_date": "28OCT25",
            "strike_int": None,
            "offset": "ITM2",
            "option_type": "CE",
            "api_key": "test-api-key-not-real",
        }
        request.update(overrides)
        return request

    def test_actual_strikes_path_resolves_as_before(self, stub_resolver):
        success, response, status_code = get_option_symbol(**self._request())

        assert (success, status_code) == (True, 200)
        assert response["symbol"] == "NIFTY28OCT2523500CE"
        assert response["underlying_ltp"] == 23587.50

    def test_strike_int_path_resolves_as_before(self, stub_resolver):
        success, response, status_code = get_option_symbol(**self._request(strike_int=50))

        assert (success, status_code) == (True, 200)
        assert response["symbol"] == "NIFTY28OCT2523500CE"

    def test_lowercase_option_type_still_resolves(self, stub_resolver):
        success, response, status_code = get_option_symbol(
            **self._request(option_type="pe", offset="ATM")
        )

        assert (success, status_code) == (True, 200)
        assert response["symbol"] == "NIFTY28OCT2523600PE"

    @pytest.mark.parametrize("option_type", ["CALL", "C", "", None, 1])
    def test_unsupported_option_type_is_a_client_error(self, stub_resolver, option_type):
        success, response, status_code = get_option_symbol(**self._request(option_type=option_type))

        assert (success, status_code) == (False, 400)
        assert response["status"] == "error"
        assert "option_type" in response["message"]
        assert stub_resolver == [], "a rejected request must not reach the broker"

    @pytest.mark.parametrize(
        "strike_int", [0, -50, float("nan"), float("inf"), "50", 10**400, Decimal("sNaN")]
    )
    def test_unusable_strike_interval_is_a_client_error(self, stub_resolver, strike_int):
        success, response, status_code = get_option_symbol(**self._request(strike_int=strike_int))

        assert (success, status_code) == (False, 400)
        assert response["status"] == "error"
        assert "strike_int" in response["message"]
        assert stub_resolver == [], "a rejected request must not reach the broker"

    @pytest.mark.parametrize("ltp", [float("nan"), float("inf")])
    def test_non_finite_ltp_is_reported_instead_of_resolving_a_symbol(self, stub_resolver, ltp):
        success, response, status_code = get_option_symbol(**self._request(underlying_ltp=ltp))

        assert (success, status_code) == (False, 500)
        assert "LTP" in response["message"]

    def test_a_valid_pre_fetched_ltp_skips_the_quote_request(self, stub_resolver):
        success, response, _ = get_option_symbol(**self._request(underlying_ltp=23574.00))

        assert success is True
        assert response["symbol"] == "NIFTY28OCT2523450CE"
        assert stub_resolver == []


class TestNoSilentPutFallback:
    """The regression itself: an unrecognised type must never price as a put."""

    def test_legacy_interval_path_no_longer_resolves_call_to_the_put_strike(self):
        put_strike = calculate_offset_strike(23600, "ITM2", 50, "PE")

        with pytest.raises(ValueError):
            calculate_offset_strike(23600, "ITM2", 50, "CALL")

        assert put_strike == 23700, "the put branch itself is unchanged"

    def test_actual_strikes_path_no_longer_resolves_call_to_the_put_strike(self):
        put_strike = calculate_offset_strike_from_actual(23600.0, "ITM2", "PE", STRIKES)

        with pytest.raises(ValueError):
            calculate_offset_strike_from_actual(23600.0, "ITM2", "CALL", STRIKES)

        assert put_strike == 23700.0, "the put branch itself is unchanged"

    def test_zero_interval_no_longer_raises_zerodivisionerror(self):
        with pytest.raises(ValueError):
            get_atm_strike(23587.50, 0)

    def test_nan_ltp_no_longer_resolves_to_the_lowest_strike(self):
        assert find_atm_strike_from_actual(math.nan, STRIKES) is None
