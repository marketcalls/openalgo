"""
Unit tests for per-strategy P&L leg ordering.

Flow workflows address a leg positionally (`{{pnl.legs[0].average_price}}`)
because the node vocabulary cannot filter a list. The strategy book keeps flat
legs indefinitely and resets a closed leg's average price to 0, so `legs[0]`
must be an open leg whenever the strategy holds one.

Run with: uv run pytest test/test_strategy_pnl_leg_order.py -v
"""

from services.strategy_pnl_service import pnl_from_book


def _leg(symbol, quantity, average_price, **overrides):
    leg = {
        "strategy": "S",
        "symbol": symbol,
        "exchange": "NFO",
        "product": "NRML",
        "quantity": quantity,
        "average_price": average_price,
        "realized_pnl": 0.0,
        "today_realized_pnl": 0.0,
    }
    leg.update(overrides)
    return leg


def test_open_leg_sorts_ahead_of_older_flat_leg():
    """The common second-day shape: yesterday's closed leg was inserted first."""
    legs = [
        _leg("NIFTY04AUG2624300PE", 0.0, 0.0, realized_pnl=120.0),
        _leg("NIFTY11AUG2624450PE", 65.0, 45.75),
    ]
    positions = [
        {"symbol": "NIFTY11AUG2624450PE", "exchange": "NFO", "product": "NRML", "ltp": 50.5}
    ]

    result = pnl_from_book(legs, positions, strategy="S")

    assert result["legs"][0]["symbol"] == "NIFTY11AUG2624450PE"
    assert result["legs"][0]["average_price"] == 45.75
    assert result["open_quantity"] == 65.0
    # A percentage exit reads legs[0] and must not divide by a reset average.
    assert result["legs"][0]["average_price"] > 0


def test_short_leg_counts_as_open():
    """A negative quantity is an open position, not a closed one."""
    legs = [_leg("FLAT", 0.0, 0.0), _leg("SHORT", -25.0, 8.0)]

    result = pnl_from_book(legs, [], strategy="S")

    assert result["legs"][0]["symbol"] == "SHORT"
    assert result["open_quantity"] == -25.0


def test_open_legs_keep_their_relative_order():
    """Sorting is stable, so a multi-leg structure keeps its booked sequence."""
    legs = [_leg("A", 0.0, 0.0), _leg("B", 50.0, 10.0), _leg("C", -25.0, 8.0)]

    result = pnl_from_book(legs, [], strategy="S")

    assert [leg["symbol"] for leg in result["legs"]] == ["B", "C", "A"]


def test_flat_strategy_keeps_its_closed_legs():
    """Ordering must not drop or invent legs when nothing is open."""
    legs = [_leg("CLOSED", 0.0, 0.0, realized_pnl=120.0, today_realized_pnl=120.0)]

    result = pnl_from_book(legs, [], strategy="S")

    assert result["open_quantity"] == 0.0
    assert [leg["symbol"] for leg in result["legs"]] == ["CLOSED"]
    assert result["realized"] == 120.0


def test_unknown_strategy_returns_a_flat_shape():
    """An exit guard reads open_quantity before legs; it must always resolve."""
    result = pnl_from_book([], [], strategy="never-traded")

    assert result["open_quantity"] == 0.0
    assert result["legs"] == []
