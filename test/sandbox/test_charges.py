"""The sandbox charge calculation, checked against a published brokerage calculator.

``sandbox/charges.py`` performs no I/O, so nothing here needs a database, a
broker or a clock.

``charges_reference.json`` holds 117 round trips read from a discount broker's
public calculator on 23 November 2026, one line at a time: sixteen trades of
odd sizes in each equity and F&O segment, and smaller sets for currency and
commodities on each exchange. Its statutory rates are the published ones and
are the same at every broker. The calculator here has to show the same lines,
because that page is what a trader holds this one against.

It does, on every line of 103 of them. The other fourteen are pinned below by
name, for two reasons that are both deliberate:

* Eight are a paisa over on one line. The exact figure there is a half paisa
  (brokerage of 30.015, an exchange charge of 148.005), which exact arithmetic
  rounds up and the page's floating point rounds down.
* Six are currency futures on NSE. The page shows the exchange charge with the
  Investor Protection Fund Trust levy in it, then leaves the levy out of its
  GST and its total, so its own lines do not add up to its own total. Here the
  levy is charged throughout and the total is always the sum of the lines.

The first version of this arithmetic rounded every line to the paisa on each
fill and matched 8 of the 117. It also opened each calculator card on BSE,
which is what made a trader say that nothing matched.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from sandbox.charges import (
    CHARGES_ENABLED_KEY,
    MARKET_CRYPTO,
    MARKET_INDIAN,
    MAX_BROKERAGE_FLAT,
    MAX_BROKERAGE_PERCENT,
    NO_CHARGES,
    SEGMENTS,
    SEGMENTS_BY_KEY,
    Charges,
    brokerage_flat_key,
    brokerage_for,
    brokerage_percent_key,
    classify_segment,
    compute_charges,
    config_keys,
    default_config_rows,
    default_config_values,
    describe_brokerage,
    estimate_round_trip,
    exchanges_of,
    is_enabled,
    market_for_broker_type,
    rupee,
    segments_for,
    split_exchange_charges,
    validate_brokerage,
    validate_config_value,
)

D = Decimal

#: The brokerage plan the reference calculator prices under, to compare like
#: with like. The sandbox's defaults differ on purpose for equity (see the
#: tests further down).
REFERENCE_PLAN = {
    "equity_delivery": (D("0"), D("0")),
    "equity_intraday": (D("20"), D("0.03")),
    "fno_futures": (D("20"), D("0.03")),
    "fno_options": (D("20"), D("0")),
    "currency_futures": (D("20"), D("0.03")),
    "currency_options": (D("20"), D("0")),
    "commodity_futures": (D("20"), D("0.03")),
    "commodity_options": (D("20"), D("0")),
}


def round_trip(segment, exchange, buy_price, sell_price, quantity, plan=REFERENCE_PLAN):
    flat, percent = plan[segment]
    return estimate_round_trip(
        segment, exchange, D(str(buy_price)), D(str(sell_price)), D(str(quantity)), flat, percent
    )


# ---------------------------------------------------------------------------
# The calculator's figures
# ---------------------------------------------------------------------------

REFERENCE = json.loads(
    (Path(__file__).parent / "charges_reference.json").read_text(encoding="utf-8")
)
TRADES = REFERENCE["trades"]


def _name(trade) -> str:
    return (
        f"{trade['segment']} {trade['exchange']} "
        f"{trade['buy']}/{trade['sell']} x {trade['quantity']}"
    )


def _priced(trade) -> Charges:
    return estimate_round_trip(
        trade["segment"],
        trade["exchange"],
        D(trade["buy"]),
        D(trade["sell"]),
        D(trade["quantity"]),
        D(trade["flat"]),
        D(trade["percent"]),
    )["total"]


def _differences(trade) -> dict[str, tuple[Decimal, Decimal]]:
    """The lines where this module and the published calculator disagree: (ours, theirs)."""
    charges = _priced(trade)
    out = {}
    for line, shown in trade["shown"].items():
        ours = charges.total if line == "total" else getattr(charges, line)
        if ours != D(shown):
            out[line] = (ours, D(shown))
    return out


#: A paisa over on one line, and so on the total, because the exact figure is
#: a half paisa. The line and the exact figure are given for each.
HALF_PAISA = {
    "equity_intraday NSE 1000/1001 x 50": ("brokerage", "30.015"),
    "equity_intraday NSE 1000/1010 x 5": ("brokerage", "3.015"),
    "fno_futures NFO 1000/1001 x 50": ("brokerage", "30.015"),
    "fno_futures NFO 1000/1010 x 5": ("brokerage", "3.015"),
    "fno_options BFO 0.85/1.15 x 6500": ("exchange_charges", "4.225"),
    "fno_options BFO 18.75/19.2 x 12000": ("exchange_charges", "148.005"),
    "commodity_futures MCX 5425/5460 x 3000": ("exchange_charges", "685.755"),
    "commodity_options MCX 4.35/5.1 x 7500": ("stt", "19.125"),
}


def _is_levy_case(trade) -> bool:
    return (trade["segment"], trade["exchange"]) == ("currency_futures", "CDS")


def test_the_reference_file_is_the_one_this_was_checked_against():
    assert REFERENCE["read_on"] == "2026-11-23"
    assert len(TRADES) == 117
    by_market = {}
    for trade in TRADES:
        key = (trade["segment"], trade["exchange"])
        by_market[key] = by_market.get(key, 0) + 1
    assert by_market == {
        ("equity_intraday", "NSE"): 16,
        ("equity_delivery", "NSE"): 16,
        ("fno_futures", "NFO"): 16,
        ("fno_options", "NFO"): 16,
        ("fno_options", "BFO"): 16,
        ("currency_futures", "CDS"): 6,
        ("currency_futures", "BCD"): 6,
        ("currency_options", "CDS"): 6,
        ("currency_options", "BCD"): 6,
        ("commodity_futures", "MCX"): 5,
        ("commodity_futures", "NCO"): 2,
        ("commodity_options", "MCX"): 5,
        ("commodity_options", "NCO"): 1,
    }
    # Every trade is priced under the plan the published calculator uses.
    for trade in TRADES:
        assert (D(trade["flat"]), D(trade["percent"])) == REFERENCE_PLAN[trade["segment"]]


@pytest.mark.parametrize(
    "trade",
    [t for t in TRADES if _name(t) not in HALF_PAISA and not _is_levy_case(t)],
    ids=_name,
)
def test_a_round_trip_shows_the_lines_the_published_calculator_shows(trade):
    """Brokerage, STT or CTT, exchange charge, GST, SEBI, stamp duty and total."""
    assert _differences(trade) == {}


def test_all_but_fourteen_of_the_reference_trades_match_on_every_line():
    """The count, so a rate or a rounding rule that drifts cannot hide in a parametrize id."""
    matching = [trade for trade in TRADES if not _differences(trade)]
    differing = {_name(trade) for trade in TRADES if _differences(trade)}

    assert len(matching) == 103
    assert differing == set(HALF_PAISA) | {_name(t) for t in TRADES if _is_levy_case(t)}


@pytest.mark.parametrize("name", sorted(HALF_PAISA))
def test_a_half_paisa_is_rounded_up_where_the_published_calculator_rounds_it_down(name):
    """One line a paisa over, the total with it, and nothing else."""
    line, exact = HALF_PAISA[name]
    trade = next(t for t in TRADES if _name(t) == name)
    differences = _differences(trade)

    assert set(differences) == {line, "total"} or set(differences) == {line, "gst", "total"}
    ours, theirs = differences[line]
    # The exact figure ends in a half paisa: up is ours, down is theirs.
    assert D(exact) - theirs == D("0.005") and ours - D(exact) == D("0.005")
    over = sum(o - t for key, (o, t) in differences.items() if key != "total")
    assert differences["total"][0] - differences["total"][1] == over
    assert over <= D("0.02")


@pytest.mark.parametrize("trade", [t for t in TRADES if _is_levy_case(t)], ids=_name)
def test_currency_futures_charge_the_levy_the_published_total_leaves_out(trade):
    """NSE currency futures, the one place the published page disagrees with itself.

    Its exchange line includes the Investor Protection Fund Trust levy, and
    this module shows the same line. Its GST and total are worked as if the
    levy were not there, so its lines add up to more than its total. Here the
    levy pays GST like the rest of the exchange charge and the total is the
    sum of the lines.
    """
    shown = {line: D(value) for line, value in trade["shown"].items()}
    charges = _priced(trade)
    turnover = (D(trade["buy"]) + D(trade["sell"])) * D(trade["quantity"])
    _transaction, levy = split_exchange_charges(
        "currency_futures", "CDS", turnover, charges.exchange_charges
    )

    # The lines that are shown agree, the exchange line included.
    assert charges.brokerage == shown["brokerage"]
    assert charges.exchange_charges == shown["exchange_charges"]
    assert charges.sebi_charges == shown["sebi_charges"]
    assert charges.stamp_duty == shown["stamp_duty"]
    assert levy > 0

    # The published total is short of its own lines by exactly the levy.
    their_lines = sum(value for line, value in shown.items() if line != "total")
    assert their_lines - shown["total"] == levy
    # Ours is the sum of its lines, and its GST is 18 percent of the three it is charged on.
    assert charges.total == charges.brokerage + charges.exchange_charges + charges.sebi_charges + (
        charges.stamp_duty + charges.gst
    )
    assert charges.gst == (
        (charges.brokerage + charges.exchange_charges + charges.sebi_charges) * D("0.18")
    ).quantize(D("0.01"), rounding="ROUND_HALF_UP")
    assert charges.gst >= shown["gst"]


def test_the_examples_the_calculator_page_opens_on_are_the_published_figures():
    """The trades each card shows before anything is typed, on the exchange it opens on."""
    intraday = round_trip("equity_intraday", "NSE", 1000, 1100, 400)
    assert intraday["total"].total == D("200.62")
    assert intraday["net_pnl"] == D("39799.38")
    assert intraday["points_to_breakeven"] == D("0.50")

    delivery = round_trip("equity_delivery", "NSE", 1000, 1100, 400)
    assert delivery["total"].total == D("931.42")
    assert delivery["points_to_breakeven"] == D("2.33")

    futures = round_trip("fno_futures", "NFO", 1000, 1100, 400)
    assert futures["total"].total == D("294.33")

    options = round_trip("fno_options", "NFO", 100, 110, 400)["total"]
    assert (options.exchange_charges, options.stamp_duty, options.total) == (
        D("29.85"),
        D("1.00"),
        D("149.52"),
    )


# ---------------------------------------------------------------------------
# Rounding: a contract note's, on a fill and on a round trip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("0.17675", "0.00"),
        ("0.4995", "1.00"),  # 0.50 to the paisa first, and then up
        ("0.50", "1.00"),
        ("1.20", "1.00"),
        ("1.5", "2.00"),
        ("7.50", "8.00"),
        ("12.2745", "12.00"),
        ("12.5125", "13.00"),
        ("840", "840.00"),
    ],
)
def test_stt_and_stamp_duty_go_to_the_nearest_rupee(value, expected):
    assert rupee(D(value)) == D(expected)


def test_a_fill_is_charged_as_a_contract_note_for_that_one_trade():
    """STT and stamp duty in whole rupees, the other lines to the paisa."""
    buy = compute_charges("fno_options", "NFO", "BUY", D("40000"), D("20"), D("0"))
    sell = compute_charges("fno_options", "NFO", "SELL", D("44000"), D("20"), D("0"))

    assert buy.stamp_duty == D("1.00")  # 0.003% of 40,000 is 1.20
    assert sell.stt == D("66.00")
    assert (buy.exchange_charges, sell.exchange_charges) == (D("14.21"), D("15.63"))
    assert (buy.stt, sell.stamp_duty) == (D("0.00"), D("0.00"))


def test_two_fills_can_come_to_a_paisa_less_than_the_round_trip_they_make():
    """Two rounded halves are not always the rounded whole, and the page says so."""
    buy = compute_charges("fno_options", "NFO", "BUY", D("40000"), D("20"), D("0"))
    sell = compute_charges("fno_options", "NFO", "SELL", D("44000"), D("20"), D("0"))
    together = round_trip("fno_options", "NFO", 100, 110, 400)["total"]

    assert buy.exchange_charges + sell.exchange_charges == D("29.84")
    assert together.exchange_charges == D("29.85")
    assert together.total - (buy.total + sell.total) == D("0.01")
    # The lines a rupee rounding decides are the same either way.
    assert together.stt == buy.stt + sell.stt
    assert together.stamp_duty == buy.stamp_duty + sell.stamp_duty


def test_commodity_tax_is_kept_to_the_paisa_where_stt_is_not():
    """CTT 25.20 on 2,52,000 sold, where the same rule as STT would make it 25."""
    futures = round_trip("commodity_futures", "MCX", 250, 252, 1000)["total"]

    assert futures.stt == D("25.20")
    assert futures.stamp_duty == D("5.00")
    assert futures.total == D("90.43")


def test_the_exchange_charge_and_its_levy_are_rounded_apart_and_then_added():
    """6,670 of NSE turnover: 0.20 and 0.01, where the combined rate gives 0.20."""
    charges = round_trip("equity_intraday", "NSE", 333, 334, 10)["total"]
    transaction, levy = split_exchange_charges(
        "equity_intraday", "NSE", D("6670"), charges.exchange_charges
    )

    assert charges.exchange_charges == D("0.21")
    assert (transaction, levy) == (D("0.20"), D("0.01"))
    assert (D("6670") * D("0.00307") / 100).quantize(D("0.01")) == D("0.20")


def test_a_round_trip_reports_one_figure_per_line_and_no_sides():
    result = round_trip("equity_intraday", "NSE", 1000, 1100, 400)

    assert set(result) == {"turnover", "total", "gross_pnl", "net_pnl", "points_to_breakeven"}
    assert result["net_pnl"] == result["gross_pnl"] - result["total"].total


# ---------------------------------------------------------------------------
# One market per broker
# ---------------------------------------------------------------------------


def test_every_segment_belongs_to_one_market_and_crypto_is_the_crypto_exchange():
    indian = [segment.key for segment in segments_for(MARKET_INDIAN)]
    crypto = [segment.key for segment in segments_for(MARKET_CRYPTO)]

    assert crypto == ["crypto_futures", "crypto_options"]
    assert len(indian) == 8 and not set(indian) & set(crypto)
    assert [segment.key for segment in segments_for()] == [segment.key for segment in SEGMENTS]
    for segment in SEGMENTS:
        on_crypto = exchanges_of(segment) == ("CRYPTO",)
        assert (segment.market == MARKET_CRYPTO) == on_crypto


@pytest.mark.parametrize(
    "broker_type,market",
    [
        ("crypto", MARKET_CRYPTO),
        ("CRYPTO", MARKET_CRYPTO),
        (" crypto ", MARKET_CRYPTO),
        ("IN_stock", MARKET_INDIAN),
        ("", MARKET_INDIAN),
        (None, MARKET_INDIAN),
        ("something_new", MARKET_INDIAN),
    ],
)
def test_only_a_plugin_that_says_crypto_is_shown_the_crypto_rate_card(broker_type, market):
    assert market_for_broker_type(broker_type) == market


def test_a_segment_lists_its_main_exchange_first():
    assert {segment.key: exchanges_of(segment) for segment in SEGMENTS} == {
        "equity_delivery": ("NSE", "BSE"),
        "equity_intraday": ("NSE", "BSE"),
        "fno_futures": ("NFO", "BFO"),
        "fno_options": ("NFO", "BFO"),
        "currency_futures": ("CDS", "BCD"),
        "currency_options": ("CDS", "BCD"),
        "commodity_futures": ("MCX", "NCDEX", "NCO"),
        "commodity_options": ("MCX", "NCDEX", "NCO"),
        "crypto_futures": ("CRYPTO",),
        "crypto_options": ("CRYPTO",),
    }


# ---------------------------------------------------------------------------
# The sandbox's own default plan
# ---------------------------------------------------------------------------


def default_plan(segment):
    row = SEGMENTS_BY_KEY[segment]
    return row.default_flat, row.default_percent


def test_delivery_is_charged_brokerage_by_default_though_the_reference_charges_none():
    """20 per executed order, or 2.5% of the order value if that is lower."""
    flat, percent = default_plan("equity_delivery")
    assert (flat, percent) == (D("20"), D("2.5"))

    # 400 shares at 1000: 2.5% is 10,000, so the flat 20 applies on each side.
    result = estimate_round_trip(
        "equity_delivery", "NSE", D("1000"), D("1100"), D("400"), flat, percent
    )
    assert result["total"].brokerage == D("40.00")
    # 931.42 without brokerage, plus 40 and the 18% GST on it.
    assert result["total"].total == D("931.42") + D("40") + D("7.20")

    # A small order: 2.5% of 500 is 12.50, which is lower than 20.
    small = compute_charges("equity_delivery", "NSE", "BUY", D("500"), flat, percent)
    assert small.brokerage == D("12.50")


def test_intraday_is_twenty_or_a_tenth_of_a_percent_whichever_is_lower():
    flat, percent = default_plan("equity_intraday")
    assert (flat, percent) == (D("20"), D("0.1"))

    # 0.1% of 4,00,000 is 400: the flat 20 is lower.
    large = compute_charges("equity_intraday", "NSE", "BUY", D("400000"), flat, percent)
    assert large.brokerage == D("20.00")

    # 0.1% of 15,000 is 15: lower than 20.
    small = compute_charges("equity_intraday", "NSE", "BUY", D("15000"), flat, percent)
    assert small.brokerage == D("15.00")

    # Exactly at the crossover the two agree.
    even = compute_charges("equity_intraday", "NSE", "BUY", D("20000"), flat, percent)
    assert even.brokerage == D("20.00")


def test_the_other_defaults_are_the_calculators():
    for segment in (
        "fno_futures",
        "fno_options",
        "currency_futures",
        "currency_options",
        "commodity_futures",
        "commodity_options",
    ):
        assert default_plan(segment) == REFERENCE_PLAN[segment], segment


def test_every_crypto_value_is_zero_until_the_trader_enters_one():
    """A crypto venue prices differently from an Indian exchange, so none of
    the schedule is assumed for it: no fee, no tax on the fee, no levies."""
    for key in ("crypto_futures", "crypto_options"):
        row = SEGMENTS_BY_KEY[key]
        assert default_plan(key) == (D("0"), D("0"))
        assert (row.stt_buy, row.stt_sell, row.stamp_buy, row.sebi, row.gst) == (0, 0, 0, 0, 0)
        assert row.exchange_txn == {} and row.ipft == {}
        for action in ("BUY", "SELL"):
            assert compute_charges(key, "CRYPTO", action, D("100000"), D("0"), D("0")) == Charges()

    # A fee the trader enters is charged as entered, with nothing added to it.
    charged = compute_charges("crypto_futures", "CRYPTO", "SELL", D("100000"), D("0"), D("0.05"))
    assert charged.brokerage == D("50.00")
    assert charged.total == D("50.00")
    assert charged == Charges(brokerage=D("50.00"))


def test_the_exchange_levy_is_part_of_the_exchange_charge_not_an_addition():
    """A breakdown may list the levy apart. The fill is still charged once."""
    value = D("10000000")  # one crore, so a rate reads off directly

    def split(segment, exchange):
        paid = compute_charges(segment, exchange, "SELL", value, D("0"), D("0")).exchange_charges
        transaction, ipft = split_exchange_charges(segment, exchange, value, paid)
        assert transaction + ipft == paid
        return transaction, ipft

    assert split("equity_delivery", "NSE") == (D("297.00"), D("10.00"))
    assert split("equity_intraday", "NSE") == (D("297.00"), D("10.00"))
    assert split("fno_futures", "NFO") == (D("173.00"), D("10.00"))
    assert split("fno_options", "NFO") == (D("3503.00"), D("50.00"))
    assert split("currency_futures", "CDS") == (D("35.00"), D("5.00"))
    assert split("currency_options", "CDS") == (D("3110.00"), D("200.00"))
    # Exchanges with no such levy.
    for segment, exchange in [
        ("equity_delivery", "BSE"),
        ("fno_options", "BFO"),
        ("currency_futures", "BCD"),
        ("commodity_futures", "MCX"),
        ("crypto_futures", "CRYPTO"),
    ]:
        assert split(segment, exchange)[1] == 0, (segment, exchange)

    # The levy can never be more than the charge it is part of.
    for row in SEGMENTS:
        for exchange, rate in row.ipft.items():
            assert rate < row.exchange_txn[exchange], (row.key, exchange)
    # An unknown segment has nothing to split.
    assert split_exchange_charges(None, "NSE", value, D("12.34")) == (D("12.34"), D("0.00"))


# ---------------------------------------------------------------------------
# The brokerage rule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,flat,percent,expected",
    [
        ("100000", "20", "0.03", "20"),  # both set: 30 against 20, flat is lower
        ("50000", "20", "0.03", "15"),  # both set: 15 against 20, percent is lower
        ("100000", "20", "0", "20"),  # flat only
        ("10", "20", "0", "20"),  # flat only is not capped by the trade value
        ("100000", "0", "0.5", "500"),  # percent only
        ("100000", "0", "0", "0"),  # neither
        ("0", "20", "0.03", "0"),  # nothing traded, nothing charged
    ],
)
def test_brokerage_is_the_lower_of_the_two_when_both_are_set(value, flat, percent, expected):
    assert brokerage_for(D(value), D(flat), D(percent)) == D(expected)


def test_a_plan_reads_as_a_brokers_pricing_page_would_put_it():
    assert describe_brokerage(D("20"), D("0.1")) == (
        "20 per executed order or 0.1% of the trade value, whichever is lower"
    )
    assert describe_brokerage(D("20"), D("0")) == "20 per executed order"
    assert describe_brokerage(D("0"), D("0.5")) == "0.5% of the trade value"
    assert describe_brokerage(D("0"), D("0")) == "No brokerage"


# ---------------------------------------------------------------------------
# Which side pays what
# ---------------------------------------------------------------------------


def test_stamp_duty_is_paid_on_the_buy_only():
    for segment in SEGMENTS:
        exchange = next(iter(segment.exchange_txn), "CRYPTO")
        sell = compute_charges(segment.key, exchange, "SELL", D("1000000"), D("0"), D("0"))
        assert sell.stamp_duty == D("0.00"), segment.key


def test_stt_falls_on_the_sell_except_for_delivery_which_pays_both_ways():
    value = D("1000000")
    for key, buy, sell in [
        ("equity_delivery", "1000.00", "1000.00"),
        ("equity_intraday", "0.00", "250.00"),
        ("fno_futures", "0.00", "500.00"),
        ("fno_options", "0.00", "1500.00"),
        ("currency_futures", "0.00", "0.00"),
        ("currency_options", "0.00", "0.00"),
        ("commodity_futures", "0.00", "100.00"),
        ("commodity_options", "0.00", "500.00"),
    ]:
        exchange = next(iter(SEGMENTS_BY_KEY[key].exchange_txn))
        assert compute_charges(key, exchange, "BUY", value, D("0"), D("0")).stt == D(buy), key
        assert compute_charges(key, exchange, "SELL", value, D("0"), D("0")).stt == D(sell), key


def test_gst_is_eighteen_percent_of_the_lines_it_is_charged_on():
    """Brokerage, exchange charges and SEBI fees. Not STT and not stamp duty."""
    charges = compute_charges("equity_intraday", "NSE", "SELL", D("440000"), D("20"), D("0.1"))
    base = charges.brokerage + charges.exchange_charges + charges.sebi_charges
    assert charges.gst == (base * D("0.18")).quantize(D("0.01"))
    assert charges.stt > 0  # present, and plainly not part of the base


def test_each_exchange_is_charged_its_own_transaction_rate():
    value = D("10000000")  # one crore, so a rate reads off directly

    def exchange_charge(segment, exchange):
        return compute_charges(segment, exchange, "SELL", value, D("0"), D("0")).exchange_charges

    assert exchange_charge("equity_intraday", "NSE") == D("307.00")
    assert exchange_charge("equity_intraday", "BSE") == D("375.00")
    assert exchange_charge("fno_futures", "NFO") == D("183.00")
    assert exchange_charge("fno_futures", "BFO") == D("0.00")
    assert exchange_charge("fno_options", "NFO") == D("3553.00")
    assert exchange_charge("fno_options", "BFO") == D("3250.00")
    assert exchange_charge("currency_futures", "CDS") == D("40.00")
    assert exchange_charge("currency_futures", "BCD") == D("45.00")
    assert exchange_charge("currency_options", "CDS") == D("3310.00")
    assert exchange_charge("currency_options", "BCD") == D("100.00")
    assert exchange_charge("commodity_futures", "MCX") == D("210.00")
    assert exchange_charge("commodity_futures", "NCO") == D("10.00")
    assert exchange_charge("commodity_options", "MCX") == D("4180.00")
    assert exchange_charge("commodity_options", "NCO") == D("100.00")


def test_every_line_is_held_to_two_places_and_the_total_is_their_sum():
    charges = compute_charges("fno_options", "NFO", "BUY", D("1234.56"), D("20"), D("0"))
    for name, value in charges.as_columns().items():
        assert value == value.quantize(D("0.01")), name
    parts = charges.as_columns()
    assert parts.pop("total_charges") == sum(parts.values())


def test_an_unknown_segment_or_an_empty_trade_is_charged_nothing():
    assert compute_charges(None, "NSE", "BUY", D("1000"), D("20"), D("0.1")) is NO_CHARGES
    assert compute_charges("nonsense", "NSE", "BUY", D("1000"), D("20"), D("0.1")) is NO_CHARGES
    assert compute_charges("equity_intraday", "NSE", "BUY", D("0"), D("20"), D("0.1")) is NO_CHARGES


# ---------------------------------------------------------------------------
# Which segment an order belongs to
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exchange,product,symbol,expected",
    [
        ("NSE", "CNC", "INFY", "equity_delivery"),
        ("NSE", "MIS", "INFY", "equity_intraday"),
        ("BSE", "CNC", "SBIN", "equity_delivery"),
        ("BSE", "MIS", "SBIN", "equity_intraday"),
        # RELIANCE and PE-suffixed tickers end in an option suffix. They are
        # shares, and must never be charged STT on a premium.
        ("NSE", "MIS", "RELIANCE", "equity_intraday"),
        ("NSE", "CNC", "RELIANCE", "equity_delivery"),
        ("NFO", "NRML", "BANKNIFTY24APR24FUT", "fno_futures"),
        ("NFO", "MIS", "NIFTY28MAR2420800CE", "fno_options"),
        ("BFO", "NRML", "SENSEX28MAR2472000PE", "fno_options"),
        ("BFO", "NRML", "SENSEX28MAR24FUT", "fno_futures"),
        ("CDS", "NRML", "USDINR28NOV25FUT", "currency_futures"),
        ("CDS", "NRML", "USDINR28NOV2584.5CE", "currency_options"),
        ("BCD", "MIS", "USDINR28NOV25FUT", "currency_futures"),
        ("MCX", "NRML", "CRUDEOILM20MAY24FUT", "commodity_futures"),
        ("MCX", "NRML", "CRUDEOIL17DEC255500PE", "commodity_options"),
        ("NCDEX", "NRML", "JEERAUNJHA20DEC24FUT", "commodity_futures"),
        ("NCO", "NRML", "GOLD05DEC24FUT", "commodity_futures"),
        ("CRYPTO", "NRML", "BTCUSDFUT", "crypto_futures"),
        ("CRYPTO", "NRML", "BTC28FEB2562000CE", "crypto_options"),
        ("crypto", "nrml", "btcusd", "crypto_futures"),
        ("NSE_INDEX", "MIS", "NIFTY", None),
        ("BSE_INDEX", "MIS", "SENSEX", None),
        ("GLOBAL_INDEX", "MIS", "US30", None),
        ("", "", "", None),
    ],
)
def test_an_order_is_filed_under_the_right_segment(exchange, product, symbol, expected):
    assert classify_segment(exchange, product, symbol) == expected


# ---------------------------------------------------------------------------
# Settings: defaults and what a trader may enter
# ---------------------------------------------------------------------------


def test_every_segment_has_its_two_settings_and_charges_start_switched_on():
    values = default_config_values()
    assert values[CHARGES_ENABLED_KEY] == "true"
    for segment in SEGMENTS:
        assert D(values[brokerage_flat_key(segment.key)]) == segment.default_flat
        assert D(values[brokerage_percent_key(segment.key)]) == segment.default_percent
    assert len(values) == 1 + 2 * len(SEGMENTS)
    assert set(config_keys()) == set(values)
    assert all(row["description"] for row in default_config_rows())


def test_the_defaults_are_themselves_values_a_trader_could_save():
    for segment in SEGMENTS:
        _flat, _percent, error = validate_brokerage(
            segment.key, segment.default_flat, segment.default_percent
        )
        assert error is None, segment.key


@pytest.mark.parametrize(
    "flat,percent,fragment",
    [
        ("-1", "0", "cannot be negative"),
        ("0", "-0.01", "cannot be negative"),
        ("abc", "0", "enter a number"),
        ("20", "", "enter a number"),
        ("nan", "0", "enter a number"),
        ("inf", "0", "enter a number"),
        (str(MAX_BROKERAGE_FLAT + 1), "0", "amount per order cannot be more than"),
        ("20", str(MAX_BROKERAGE_PERCENT + 1), "percentage cannot be more than"),
    ],
)
def test_a_value_that_would_misprice_every_trade_is_refused(flat, percent, fragment):
    _flat, _percent, error = validate_brokerage("equity_intraday", flat, percent)
    assert error is not None and fragment in error
    # The message names the segment, so a trader knows which row to fix.
    assert error.startswith("Equity Intraday")


def test_the_limits_themselves_are_accepted():
    flat, percent, error = validate_brokerage(
        "equity_intraday", MAX_BROKERAGE_FLAT, MAX_BROKERAGE_PERCENT
    )
    assert error is None
    assert (flat, percent) == (MAX_BROKERAGE_FLAT, MAX_BROKERAGE_PERCENT)


def test_a_segment_that_does_not_exist_is_refused():
    _flat, _percent, error = validate_brokerage("penny_stocks", "20", "0")
    assert error is not None


def test_the_one_key_update_route_cannot_store_what_the_page_would_refuse():
    assert validate_config_value(CHARGES_ENABLED_KEY, "true") is None
    assert validate_config_value(CHARGES_ENABLED_KEY, "false") is None
    assert validate_config_value(CHARGES_ENABLED_KEY, "maybe") is not None

    flat_key = brokerage_flat_key("fno_options")
    percent_key = brokerage_percent_key("fno_options")
    assert validate_config_value(flat_key, "20") is None
    assert validate_config_value(flat_key, "-5") is not None
    assert validate_config_value(flat_key, "twenty") is not None
    assert validate_config_value(percent_key, "0.03") is None
    assert validate_config_value(percent_key, "30") is not None

    # A key that belongs to another part of the sandbox is not this module's
    # to judge.
    assert validate_config_value("starting_capital", "anything") is None


def test_a_damaged_switch_reads_as_on_so_trades_are_never_silently_free():
    for value in ("true", "True", "1", "", "garbage", None):
        assert is_enabled(value) is True, value
    for value in ("false", "FALSE", " false ", "0", "off", "no"):
        assert is_enabled(value) is False, value
