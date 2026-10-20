"""The combined premium chart: which expiry, which candle size, and what draws it.

Three things this surface got wrong, each found by asking it a question an
operator actually asks:

- "The current month straddle" was refused. The live card understood the words
  and the chart did not, because the expiry vocabulary had been written twice.
- "With a supertrend" drew a premium and no supertrend. A study reads the
  chart's primary series, and the premium was travelling as a plotted line
  rather than as the frame's bars, so there was nothing to attach one to.
- A candle size the broker does not serve refused rather than stepping down,
  which answers a question about a combination with nothing at all.

Everything here is pure. No test calls a provider, a broker or a database.
"""

from __future__ import annotations

import pytest

from services.agent.tools.option_viz import (
    DEFAULT_PREMIUM_INTERVAL,
    EXPIRY_CHOICES,
    FALLBACK_PREMIUM_INTERVAL,
    choose_expiry,
    monthly_expiry,
    premium_interval,
    resolve_expiry,
)

# Two index months: four weeklies in September, two in October. The monthly is
# the last weekly of its month, which is what makes 29SEP26 the September
# contract rather than 16SEP26, the nearest.
LISTED = ["16SEP26", "23SEP26", "29SEP26", "06OCT26", "27OCT26"]


def listing(*dates: str):
    """A stand-in for ``get_expiry_dates`` answering with exchange-form dates."""

    def call(_fn, **_kwargs):
        return {"data": list(dates)}

    return call


class TestTheExpiryVocabulary:
    @pytest.mark.parametrize(
        ("said", "expected"),
        [
            ("current_month", "29SEP26"),
            ("current month", "29SEP26"),
            ("Current Month", "29SEP26"),
            ("current-month", "29SEP26"),
            ("monthly", "29SEP26"),
            ("this_month", "29SEP26"),
            ("next_month", "27OCT26"),
            ("next month", "27OCT26"),
        ],
    )
    def test_the_monthly_contract_is_the_last_weekly_of_its_month(self, said, expected):
        # "The current month" is the monthly contract. Reading it as the
        # nearest expiry charts this week's straddle and calls it the month's.
        assert choose_expiry(LISTED, said, []) == expected

    def test_the_nearest_expiry_is_what_an_unnamed_one_means(self):
        assert choose_expiry(LISTED, "", []) == "16SEP26"

    def test_next_week_is_the_one_after_the_nearest(self):
        assert choose_expiry(LISTED, "next_week", []) == "23SEP26"

    def test_a_single_listed_expiry_cannot_have_a_next_one(self):
        notices: list[str] = []
        assert choose_expiry(["27OCT26"], "next_week", notices) == "27OCT26"
        assert "only listed expiry" in notices[0]

    def test_a_date_that_is_not_listed_is_refused_rather_than_charted(self):
        with pytest.raises(Exception) as caught:
            choose_expiry(LISTED, "31DEC26", [])
        # Naming a contract nothing trades on draws an empty chart and blames
        # the broker, so the refusal names the ones that exist.
        assert "16SEP26" in str(caught.value)

    def test_every_choice_resolves_to_something_listed(self):
        for choice in EXPIRY_CHOICES:
            assert choose_expiry(LISTED, choice, []) in LISTED

    def test_it_says_which_date_it_picked(self):
        notices: list[str] = []
        choose_expiry(LISTED, "current_month", notices)
        # The operator asked for a month and gets a date back, so the answer
        # has to say which one or the two of them are talking past each other.
        assert "29SEP26" in notices[0]

    def test_a_month_with_one_expiry_still_has_a_monthly(self):
        # A stock lists one expiry a month, so the monthly and the nearest are
        # the same contract.
        assert monthly_expiry(["24SEP26", "29OCT26"], later=False) == "24SEP26"
        assert monthly_expiry(["24SEP26", "29OCT26"], later=True) == "29OCT26"


class TestTheChartResolvesTheWordsItIsGiven:
    def test_current_month_reaches_the_chart_tool(self):
        # The gap this file was written for: the chart refused the phrasing the
        # live card accepted, so one question drew a card and not a chart.
        notices: list[str] = []
        got = resolve_expiry(listing(*LISTED), "NIFTY", "NSE_INDEX", "current month", notices)
        assert got == "29SEP26"

    def test_an_exact_date_costs_no_lookup(self):
        calls: list[str] = []

        def call(_fn, **_kwargs):
            calls.append("fetched")
            return {"data": LISTED}

        assert resolve_expiry(call, "NIFTY", "NSE_INDEX", "29SEP26", []) == "29SEP26"
        # The common call. Fetching the listing to check a date the model
        # already knows is a round trip on every chart.
        assert calls == []

    def test_an_underlying_with_no_listed_options_is_refused(self):
        with pytest.raises(Exception) as caught:
            resolve_expiry(listing(), "NIFTY", "NSE_INDEX", "current_month", [])
        assert "lists no option expiries" in str(caught.value)


class TestTheCandleSize:
    def test_five_minutes_is_what_an_unnamed_size_means(self):
        assert premium_interval("", ["1m", "5m", "15m"]) == (DEFAULT_PREMIUM_INTERVAL, None)

    def test_a_size_the_broker_serves_is_the_one_drawn(self):
        assert premium_interval("15m", ["1m", "5m", "15m"]) == ("15m", None)

    def test_a_size_the_broker_does_not_serve_steps_down_rather_than_refusing(self):
        got, notice = premium_interval("3m", ["1m", "5m", "15m"])
        # Refusing answers a question about a combination with no chart at all,
        # when a minute chart would have answered it.
        assert got == FALLBACK_PREMIUM_INTERVAL
        assert notice is not None

    def test_it_never_substitutes_silently(self):
        _got, notice = premium_interval("1h", ["1m", "5m"])
        # A 1m chart presented as the 1h chart that was asked for is a
        # different picture of the same session.
        assert "1h" in notice and "1m" in notice

    def test_case_alone_is_corrected_not_stepped_down(self):
        got, notice = premium_interval("5M", ["1m", "5m"])
        assert got == "5m"
        assert "case sensitive" in notice

    def test_a_broker_without_minute_candles_uses_what_it_has(self):
        got, notice = premium_interval("3m", ["15m", "1h"])
        assert got == "15m"
        assert "15m" in notice

    def test_an_unknown_listing_is_passed_through_rather_than_guessed(self):
        # The intervals lookup failing is not the operator's problem, and the
        # history service validates the size again anyway.
        assert premium_interval("7m", None) == ("7m", None)


class TestWhatDrawsIt:
    """The frame the premium goes out as, which is what makes studies possible."""

    @staticmethod
    def deliver(*, indicators=(), legs=None):
        """Run the delivery step over a short session and return the queued frame."""
        from services.agent.tools.option_viz import OptionVizToolkit

        rows = [{"time": 1_700_000_000 + i * 300} for i in range(4)]
        combined = [120.0, 124.5, 118.25, 130.0]
        sink: list = []

        toolkit = OptionVizToolkit.__new__(OptionVizToolkit)
        toolkit._sink = sink
        OptionVizToolkit._deliver_premium(
            toolkit,
            series=rows,
            combined=combined,
            legs=legs
            if legs is not None
            else [
                {"label": "23100 CE", "colour": "#16a34a", "values": [60.0, 62.0, 59.0, 65.0]},
                {"label": "23100 PE", "colour": "#dc2626", "values": [60.0, 62.5, 59.25, 65.0]},
            ],
            title="NIFTY 29SEP26 rolling ATM straddle, 5m",
            subtitle="Rolling ATM",
            axis="Straddle premium",
            interval="5m",
            indicators=list(indicators),
            source="straddle_chart_service",
            notices=[],
        )
        assert sink, "nothing was queued"
        return sink[0].frame

    def test_it_goes_out_as_the_platform_chart_not_a_generic_plot(self):
        frame = self.deliver()
        # The engine /trading and plot_price_chart already draw with. Drawing a
        # premium anywhere else is what made it the one chart with no studies.
        assert frame.kind == "candles"

    def test_the_combined_series_is_the_frame_bars(self):
        frame = self.deliver()
        bars = frame.spec["bars"]
        assert [bar["close"] for bar in bars] == [120.0, 124.5, 118.25, 130.0]
        # Studies read the primary series, which is built from these. The
        # combination has to be here or "with a supertrend" has nothing to
        # attach to.
        assert [bar["time"] for bar in bars] == [1_700_000_000 + i * 300 for i in range(4)]

    def test_a_bar_is_flat_because_a_combined_candle_would_be_invented(self):
        bar = self.deliver().spec["bars"][1]
        # The legs move against each other, so their highs happen at different
        # moments inside one bar and adding them invents a peak that never
        # traded.
        assert bar["open"] == bar["high"] == bar["low"] == bar["close"] == 124.5

    def test_it_is_drawn_as_a_line(self):
        assert self.deliver().spec["chart_type"] == "line"

    def test_the_legs_are_not_drawn_beside_the_combination(self):
        spec = self.deliver().spec
        # A combined premium is one number. The individual premiums move
        # against each other, so drawing them on the same axis fills the card
        # with two lines that cross and re-cross while the combination, the
        # thing that was asked about, reads as the flattest of the three.
        assert "series" not in spec or spec["series"] == []

    def test_the_studies_asked_for_travel_with_it(self):
        frame = self.deliver(indicators=[{"id": "supertrend", "inputs": {"length": 10}}])
        assert frame.spec["indicators"] == [{"id": "supertrend", "inputs": {"length": 10}}]

    def test_a_combined_value_that_did_not_print_is_absent_rather_than_zero(self):
        from services.agent.tools.option_viz import OptionVizToolkit

        rows = [{"time": 1_700_000_000 + i * 300} for i in range(3)]
        sink: list = []
        toolkit = OptionVizToolkit.__new__(OptionVizToolkit)
        toolkit._sink = sink
        OptionVizToolkit._deliver_premium(
            toolkit,
            series=rows,
            combined=[120.0, float("nan"), 130.0],
            legs=[],
            title="t",
            subtitle="s",
            axis="a",
            interval="5m",
            indicators=[],
            source="straddle_chart_service",
            notices=[],
        )
        # Zero is a number someone might read as the combination having
        # collapsed, so a bar that did not price is left out.
        assert [bar["close"] for bar in sink[0].frame.spec["bars"]] == [120.0, 130.0]
