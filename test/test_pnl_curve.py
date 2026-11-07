# test/test_pnl_curve.py
"""services/pnl_curve.py: daily realized and unrealized P&L, hand-worked.

Days: Mon 4 May 2026 is the base (last day before the range), the range is
Tue 5 May .. Fri 8 May.
"""

from datetime import date, datetime

import pytest

from services.pnl_curve import (
    BASIS_ACTUAL_COST,
    BASIS_RANGE_START,
    build_curve,
    symbols_needing_closes,
)

BASE = date(2026, 5, 4)
DAYS = [date(2026, 5, 5), date(2026, 5, 6), date(2026, 5, 7), date(2026, 5, 8)]
KEY = ("ABC", "NSE")


def fill(action, qty, price, day, hour=15, strategy="S", product="CNC", symbol="ABC"):
    return {
        "symbol": symbol,
        "exchange": "NSE",
        "action": action,
        "quantity": qty,
        "average_price": price,
        "timestamp": datetime(day.year, day.month, day.day, hour, 13),
        "product": product,
        "strategy": strategy,
    }


def closes(**by_day):
    return {KEY: {date(2026, 5, int(k[1:])): v for k, v in by_day.items()}}


# base close 100 on the 4th, then 110, 120, 130, 140.
CLOSES = closes(d4=100, d5=110, d6=120, d7=130, d8=140)


def test_bought_in_range_sold_in_range_counts_unrealized_then_realized():
    # Buy 10 at 105 on the 5th, sell 10 at 125 on the 7th.
    out = build_curve(
        [fill("BUY", 10, 105, DAYS[0]), fill("SELL", 10, 125, DAYS[2])],
        CLOSES,
        DAYS,
        BASE,
    )
    s = out["by_strategy"]["S"]
    # Held at the close of the 5th and 6th: 10*(110-105), 10*(120-105). Sold on the 7th.
    assert s["unrealized"] == [50.0, 150.0, 0.0, 0.0]
    assert s["realized"] == [0.0, 0.0, 200.0, 0.0]
    combined = [r + u for r, u in zip(s["realized"], s["unrealized"], strict=True)]
    assert combined == [50.0, 150.0, 200.0, 0.0]  # realized is a daily amount here


def test_carried_lot_is_valued_from_the_base_close_by_default():
    # Bought on 28 April at 90, sold on the 6th at 115.
    fills = [fill("BUY", 10, 90, date(2026, 4, 28)), fill("SELL", 10, 115, DAYS[1])]
    out = build_curve(fills, CLOSES, DAYS, BASE, BASIS_RANGE_START)["by_strategy"]["S"]
    # Cost is the base close 100: unrealized on the 5th is 10*(110-100); realized 10*(115-100).
    assert out["unrealized"] == [100.0, 0.0, 0.0, 0.0]
    assert out["realized"] == [0.0, 150.0, 0.0, 0.0]


def test_actual_cost_basis_keeps_the_whole_gain():
    fills = [fill("BUY", 10, 90, date(2026, 4, 28)), fill("SELL", 10, 115, DAYS[1])]
    out = build_curve(fills, CLOSES, DAYS, BASE, BASIS_ACTUAL_COST)["by_strategy"]["S"]
    assert out["unrealized"] == [200.0, 0.0, 0.0, 0.0]
    assert out["realized"] == [0.0, 250.0, 0.0, 0.0]


def test_adjacent_ranges_add_up_on_the_range_start_basis():
    fills = [fill("BUY", 10, 90, date(2026, 4, 28)), fill("SELL", 10, 115, DAYS[2])]
    whole = build_curve(fills, CLOSES, DAYS, BASE)["by_strategy"]["S"]
    first = build_curve(fills, CLOSES, DAYS[:2], BASE)["by_strategy"]["S"]
    second = build_curve(fills, CLOSES, DAYS[2:], DAYS[1])["by_strategy"]["S"]

    def total(x):
        return sum(x["realized"]) + x["unrealized"][-1]

    assert total(whole) == pytest.approx(total(first) + total(second))
    # Whole range: 10 * (115 - 100) realized, nothing open at the end.
    assert total(whole) == pytest.approx(150.0)


def test_still_open_at_the_end_stays_in_unrealized():
    out = build_curve([fill("BUY", 10, 105, DAYS[0])], CLOSES, DAYS, BASE)["by_strategy"]["S"]
    assert out["unrealized"] == [50.0, 150.0, 250.0, 350.0]
    assert out["realized"] == [0.0] * 4


def test_intraday_round_trip_is_realized_only():
    fills = [
        fill("BUY", 5, 100, DAYS[0], hour=10, product="MIS"),
        fill("SELL", 5, 104, DAYS[0], hour=14, product="MIS"),
    ]
    out = build_curve(fills, CLOSES, DAYS, BASE)["by_strategy"]["S"]
    assert out["realized"][0] == 20.0
    assert out["unrealized"] == [0.0] * 4


def test_partial_exit_uses_fifo_and_keeps_the_rest_open():
    fills = [
        fill("BUY", 10, 100, DAYS[0]),
        fill("BUY", 10, 120, DAYS[0]),
        fill("SELL", 15, 130, DAYS[1]),
    ]
    out = build_curve(fills, CLOSES, DAYS, BASE)["by_strategy"]["S"]
    # 10 @100 and 5 of the @120 lot sold at 130 -> 300 + 50. 5 @120 remain.
    assert out["realized"][1] == 350.0
    assert out["unrealized"][1] == 5 * (120 - 120)
    assert out["unrealized"][2] == 5 * (130 - 120)


def test_strategy_follows_the_entry_fill_and_untagged_is_named():
    fills = [
        fill("BUY", 10, 100, DAYS[0], strategy=None),
        fill("SELL", 10, 110, DAYS[1], strategy="X"),
    ]
    out = build_curve(fills, CLOSES, DAYS, BASE)["by_strategy"]
    assert list(out) == ["Untagged"]
    assert out["Untagged"]["realized"][1] == 100.0


def test_a_sell_with_no_matching_buy_is_reported_not_turned_into_a_short():
    out = build_curve([fill("SELL", 10, 110, DAYS[1])], CLOSES, DAYS, BASE)
    assert out["by_strategy"] == {}
    assert out["notes"]["orphan_sells"][0]["symbol"] == "ABC"


def test_missing_close_carries_the_last_known_close_forward():
    sparse = closes(d4=100, d5=110)  # nothing after the 5th
    out = build_curve([fill("BUY", 10, 105, DAYS[0])], sparse, DAYS, BASE)["by_strategy"]["S"]
    assert out["unrealized"] == [50.0, 50.0, 50.0, 50.0]


def test_no_close_at_all_is_reported():
    out = build_curve([fill("BUY", 10, 105, DAYS[0])], {}, DAYS, BASE)
    assert "ABC" in out["notes"]["missing_close"]
    assert out["by_strategy"] == {}


def test_symbols_needing_closes_skips_flat_positions():
    fills = [
        fill("BUY", 10, 100, date(2026, 3, 1), symbol="OLD"),
        fill("SELL", 10, 110, date(2026, 3, 5), symbol="OLD"),  # flat long before the range
        fill("BUY", 10, 100, date(2026, 4, 1), symbol="HELD"),  # carried through
        fill("BUY", 5, 100, DAYS[1], symbol="INTRA", product="MIS"),
        fill("SELL", 5, 101, DAYS[1], symbol="INTRA", product="MIS"),  # flat by the close
    ]
    needed = symbols_needing_closes(fills, BASE, DAYS[-1])
    assert needed == {("HELD", "NSE")}


def test_same_day_sell_then_buy_is_an_intraday_short_and_leaves_nothing_open():
    # Sold first, bought back the same day years ago (imported, product unknown), then a
    # normal buy and sell inside the range. The old round trip must not sit in front of
    # the new lot in the queue.
    old = date(2021, 4, 20)
    fills = [
        fill("SELL", 340, 510, old, hour=12, product=None, strategy=None),
        fill("BUY", 340, 508.4, old, hour=14, product=None, strategy=None),
        fill("BUY", 45, 100, DAYS[0], product=None, strategy="S"),
        fill("SELL", 45, 125, DAYS[2], product=None, strategy="S"),
    ]
    out = build_curve(fills, CLOSES, DAYS, BASE)
    s = out["by_strategy"]["S"]
    assert s["realized"] == [0.0, 0.0, 45 * 25.0, 0.0]
    assert s["unrealized"][3] == 0.0
    assert "Untagged" not in out["by_strategy"]
    assert out["notes"]["orphan_sells"] == []


def test_a_short_that_survives_the_day_is_dropped_and_reported():
    out = build_curve([fill("SELL", 10, 110, DAYS[0], product=None)], CLOSES, DAYS, BASE)
    assert out["by_strategy"] == {}
    assert out["notes"]["orphan_sells"][0]["symbol"] == "ABC"


def test_realized_matches_the_fifo_engine_for_a_mixed_ledger():
    # Both engines run the same intraday-first rule, so P&L History and the
    # curve cannot disagree on realized for the same fills.
    from utils.pnl_fifo import compute_realized_pnl

    f = [
        fill("BUY", 66, 1056.95, DAYS[0], hour=15, product="CNC"),
        fill("BUY", 306, 1087.43, DAYS[1], hour=9, product="CNC"),
        fill("SELL", 306, 1080.65, DAYS[1], hour=11, product="CNC"),
        fill("BUY", 40, 500.0, DAYS[1], hour=12, product="MIS"),
        fill("SELL", 25, 510.0, DAYS[1], hour=14, product="MIS"),
        fill("SELL", 66, 991.31, DAYS[3], hour=15, product="CNC"),
        fill("SELL", 15, 520.0, DAYS[3], hour=10, product="MIS"),
    ]
    out = build_curve(f, CLOSES, DAYS, BASE, BASIS_ACTUAL_COST)
    curve_total = sum(sum(s["realized"]) for s in out["by_strategy"].values())

    trades = [
        {
            "symbol": x["symbol"],
            "exchange": x["exchange"],
            "product": x["product"],
            "segment": "equity",
            "action": x["action"],
            "quantity": x["quantity"],
            "average_price": x["average_price"],
            "trade_timestamp": x["timestamp"],
            "strategy": x["strategy"],
        }
        for x in f
    ]
    fifo_total = compute_realized_pnl(trades).total_realized_pnl
    assert curve_total == pytest.approx(fifo_total)
