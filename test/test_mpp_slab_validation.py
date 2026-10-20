import pytest

from utils.mpp_slab import calculate_protected_price, get_mpp_percentage


class TestGetMppPercentageSlabs:
    """Boundary behaviour of the slab lookup (unchanged by validation)."""

    @pytest.mark.parametrize(
        "price, instrument_type, expected",
        [
            (50, "EQ", 2.0),
            (99.99, "EQ", 2.0),
            (100, "EQ", 1.0),
            (499.99, "EQ", 1.0),
            (500, "EQ", 0.5),
            (10000, "EQ", 0.5),
            (50, "FUT", 2.0),
            (5, "PE", 5.0),
            (9.99, "CE", 5.0),
            (10, "CE", 3.0),
            (99.99, "CE", 3.0),
            (100, "CE", 2.0),
            (500, "CE", 1.0),
        ],
    )
    def test_boundary_slabs_unchanged(self, price, instrument_type, expected):
        assert get_mpp_percentage(price, instrument_type) == expected


class TestGetMppPercentageValidation:
    """Invalid prices fail fast instead of leaking None or a bare TypeError."""

    @pytest.mark.parametrize("bad_price", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_price_rejected(self, bad_price):
        with pytest.raises(ValueError, match="finite"):
            get_mpp_percentage(bad_price, "EQ")

    @pytest.mark.parametrize("bad_price", [None, "50", [50], {"price": 50}, True])
    def test_non_numeric_price_rejected(self, bad_price):
        with pytest.raises(TypeError, match="must be a number"):
            get_mpp_percentage(bad_price, "CE")

    def test_nan_price_propagates_as_value_error(self):
        # Previously returned None, which crashed downstream on percentage / 100.
        with pytest.raises(ValueError, match="finite"):
            calculate_protected_price(float("nan"), "BUY", instrument_type="EQ")
