"""Regression coverage for Groww holdings statistics.

broker.groww.api.order_api.get_holdings() returns a tuple of
(holdings, status) and services/holdings_service.py passes that value
straight through, so calculate_portfolio_statistics() must accept it.
When it did not, every total silently came back as zero while the
holdings rows still rendered correctly.
"""

from broker.groww.mapping.order_data import calculate_portfolio_statistics

ZERO_STATS = {
    "totalholdingvalue": 0,
    "totalinvvalue": 0,
    "totalpnlpercentage": 0,
    "totalprofitandloss": 0,
}

# Shape returned by Groww's GET /v1/holdings/user, as normalised by
# get_holdings(). Note there is no price or pnl field.
HOLDINGS = [
    {
        "symbol": "ASTRAL",
        "isin": "INE006I01046",
        "quantity": 250.0,
        "average_price": 1325.70,
        "free_quantity": 250.0,
        "locked_quantity": 0.0,
        "pledged_quantity": 0.0,
        "t1_quantity": 0.0,
    },
    {
        "symbol": "IFCI",
        "isin": "INE039A01010",
        "quantity": 4000.0,
        "average_price": 69.18,
        "free_quantity": 4000.0,
        "locked_quantity": 0.0,
        "pledged_quantity": 0.0,
        "t1_quantity": 0.0,
    },
]

# 250 * 1325.70 + 4000 * 69.18
EXPECTED_VALUE = 608145.0


def test_statistics_from_get_holdings_tuple():
    """The actual (holdings, status) return value must be unwrapped."""
    stats = calculate_portfolio_statistics((HOLDINGS, {"status": "success"}))

    assert stats["totalinvvalue"] == EXPECTED_VALUE
    assert stats["totalholdingvalue"] == EXPECTED_VALUE


def test_statistics_from_plain_list():
    """A bare list keeps working."""
    assert calculate_portfolio_statistics(HOLDINGS)["totalinvvalue"] == EXPECTED_VALUE


def test_statistics_from_payload_and_data_wrappers():
    """Both documented dict wrappers keep working."""
    assert (
        calculate_portfolio_statistics({"payload": {"holdings": HOLDINGS}})["totalinvvalue"]
        == EXPECTED_VALUE
    )
    assert (
        calculate_portfolio_statistics({"data": {"holdings": HOLDINGS}})["totalinvvalue"]
        == EXPECTED_VALUE
    )


def test_precomputed_statistics_are_passed_through():
    precomputed = {"totalholdingvalue": 7, "totalinvvalue": 7}
    assert calculate_portfolio_statistics({"data": {"statistics": precomputed}}) == precomputed


def test_error_tuple_yields_zero_stats():
    """get_holdings() returns (None, {"status": "error"}) on failure."""
    assert calculate_portfolio_statistics((None, {"status": "error"})) == ZERO_STATS


def test_empty_inputs_yield_zero_stats():
    assert calculate_portfolio_statistics(([], {"status": "success"})) == ZERO_STATS
    assert calculate_portfolio_statistics([]) == ZERO_STATS
    assert calculate_portfolio_statistics(None) == ZERO_STATS


def test_pnl_is_summed_when_present():
    """Groww omits pnl today, but the field is honoured when supplied."""
    with_pnl = [dict(HOLDINGS[0], pnl=1000.0), dict(HOLDINGS[1], pnl=-250.0)]

    stats = calculate_portfolio_statistics((with_pnl, {"status": "success"}))

    assert stats["totalprofitandloss"] == 750.0
    assert stats["totalpnlpercentage"] == round(750.0 / EXPECTED_VALUE * 100, 2)
