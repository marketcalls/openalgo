"""Argument normalisation for the agent's market, chart, symbol and option tools.

Every helper here runs before a broker request is spent, and each one either
turns a spelling a model commonly sends into the one the service takes, or
refuses it with a message the model can act on. These tests pin both halves:
the newly accepted spellings, and that a genuinely invalid value is still
refused rather than passed through to fail at the broker.

Nothing here reaches a broker, the network or the symbol database. Where a
helper asks the database whether a pair is listed, ``is_listed`` is replaced.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import get_type_hints

import pytest

pytest.importorskip("agno.tools", reason="the agent module needs agno")

from agno.exceptions import RetryAgentRun  # noqa: E402
from pydantic import TypeAdapter  # noqa: E402

import services.agent.tools.market as market  # noqa: E402
import services.agent.tools.options as options  # noqa: E402
import services.agent.tools.viz as viz  # noqa: E402
from services.agent.tools import ToolContext  # noqa: E402
from services.agent.tools.market import (  # noqa: E402
    IST,
    clean_exchange,
    daily_interval,
    history_range,
    lookback_range,
    normalise_date,
    normalise_interval,
    normalise_pair,
    symbol_pairs,
)
from services.agent.tools.options import (  # noqa: E402
    UNDERLYING_EXCHANGES,
    index_underlying,
    normalise_exchange,
    normalise_expiry,
    normalise_expiry_argument,
    normalise_int,
    normalise_offset,
    normalise_option_type,
)
from services.agent.tools.symbols import SymbolsToolkit  # noqa: E402

ACCEPTED = ["1m", "5m", "15m", "1h", "D", "W", "M"]


@pytest.fixture
def listed(monkeypatch):
    """Replace the symbol database with a fixed set of listed pairs."""
    pairs = {
        ("INFY", "NSE"),
        ("SBIN", "NSE"),
        ("RELIANCE", "NSE"),
        ("NIFTY", "NSE_INDEX"),
        ("SENSEX", "BSE_INDEX"),
    }
    monkeypatch.setattr(market, "is_listed", lambda symbol, exchange: (symbol, exchange) in pairs)
    return pairs


def _today() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# market.clean_exchange and its three users
# ---------------------------------------------------------------------------


class TestExchangeSpelling:
    @pytest.mark.parametrize("raw", ["nse index", "NSE-INDEX", " nse_index ", "Nse  Index"])
    def test_every_spelling_reads_as_the_code(self, raw):
        assert clean_exchange(raw) == "NSE_INDEX"

    def test_options_reads_the_same_spellings(self):
        assert normalise_exchange("bse-index", UNDERLYING_EXCHANGES) == "BSE_INDEX"

    def test_options_still_refuses_an_unknown_code(self):
        with pytest.raises(RetryAgentRun, match="'exchange' argument"):
            normalise_exchange("LSE", UNDERLYING_EXCHANGES)

    def test_symbols_reads_the_same_spellings(self):
        kit = object.__new__(SymbolsToolkit)
        assert kit._exchange("nse index", allow_blank=False) == "NSE_INDEX"
        with pytest.raises(RetryAgentRun):
            kit._exchange("NASDAQ", allow_blank=False)


# ---------------------------------------------------------------------------
# market.normalise_date and history_range
# ---------------------------------------------------------------------------


class TestDates:
    @pytest.mark.parametrize(
        "raw",
        [
            "2026-10-09",
            "2026-10-09T00:00:00",
            "2026-10-09T15:30:00+05:30",
            "2026-10-09 09:15",
            "09-10-2026",
            "9-10-2026",
            "2026/10/09",
            "09-Oct-2026",
            "09-OCT-2026",
        ],
    )
    def test_accepted_spellings(self, raw):
        assert normalise_date("start_date", raw) == "2026-10-09"

    def test_today_and_yesterday_are_ist(self):
        today = datetime.now(IST).date()
        assert normalise_date("end_date", "today") == today.isoformat()
        assert normalise_date("end_date", " Yesterday ") == (today - timedelta(days=1)).isoformat()

    @pytest.mark.parametrize(
        "raw", ["next friday", "31-02-2026", "2026-13-01", "09-Foo-2026", "10/09/2026", ""]
    )
    def test_anything_else_is_still_refused(self, raw):
        with pytest.raises(RetryAgentRun, match="Use YYYY-MM-DD"):
            normalise_date("start_date", raw)

    def test_both_dates_left_out_is_a_lookback_ending_today(self):
        start, end = history_range("D", None, None)
        assert end == _today()
        assert start == lookback_range("D", market.DEFAULT_HISTORY_BARS)[0]

    def test_empty_strings_are_treated_as_left_out(self):
        assert history_range("D", "", "") == history_range("D", None, None)

    def test_only_an_end_date_gives_the_lookback_ending_there(self):
        start, end = history_range("D", None, "2026-03-31")
        assert end == "2026-03-31"
        anchor = datetime(2026, 3, 31).date()
        assert start == lookback_range("D", market.DEFAULT_HISTORY_BARS, end_date=anchor)[0]

    def test_only_a_start_date_runs_to_today(self):
        assert history_range("D", "2026-01-01", None) == ("2026-01-01", _today())

    def test_both_given_are_unchanged(self):
        assert history_range("5m", "2026-01-01", "2026-01-31") == ("2026-01-01", "2026-01-31")

    def test_a_backwards_range_is_still_refused(self):
        with pytest.raises(RetryAgentRun, match="start_date"):
            history_range("D", "2026-02-01", "2026-01-01")


# ---------------------------------------------------------------------------
# market.normalise_interval and daily_interval
# ---------------------------------------------------------------------------


class TestIntervals:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1d", "D"),
            ("1D", "D"),
            ("day", "D"),
            ("Daily", "D"),
            ("1day", "D"),
            ("1w", "W"),
            ("week", "W"),
            ("weekly", "W"),
            ("1mo", "M"),
            ("month", "M"),
            ("Monthly", "M"),
            ("5min", "5m"),
            ("5mins", "5m"),
            ("15minute", "15m"),
            ("15 minutes", "15m"),
            ("1hr", "1h"),
            ("1hour", "1h"),
            ("1 hours", "1h"),
        ],
    )
    def test_aliases_are_translated_with_a_notice(self, raw, expected):
        interval, notice = normalise_interval(raw, "api", ACCEPTED)
        assert interval == expected
        assert notice and repr(raw) in notice

    def test_an_accepted_value_passes_without_a_notice(self):
        for value in ACCEPTED:
            assert normalise_interval(value, "api", ACCEPTED) == (value, None)

    def test_lower_case_m_is_never_months(self):
        assert normalise_interval("1m", "api", ACCEPTED) == ("1m", None)
        # The existing case correction: 5M reads as five minutes, not months.
        assert normalise_interval("5M", "api", ACCEPTED)[0] == "5m"

    def test_sixty_minutes_becomes_an_hour_only_where_the_broker_lacks_60m(self):
        interval, notice = normalise_interval("60m", "api", ACCEPTED)
        assert interval == "1h" and notice
        assert normalise_interval("60min", "api", ACCEPTED)[0] == "1h"
        assert normalise_interval("60m", "api", [*ACCEPTED, "60m"]) == ("60m", None)

    def test_sixty_minutes_is_refused_where_the_broker_has_neither(self):
        with pytest.raises(RetryAgentRun, match="Use one of"):
            normalise_interval("60m", "api", ["1m", "5m", "D"])

    def test_an_alias_the_broker_does_not_offer_is_refused(self):
        with pytest.raises(RetryAgentRun, match="Use one of"):
            normalise_interval("2hours", "api", ACCEPTED)

    @pytest.mark.parametrize("raw", ["fortnight", "1y", "quarterly", "5 candles"])
    def test_an_unknown_interval_is_still_refused(self, raw):
        with pytest.raises(RetryAgentRun, match="'interval' argument"):
            normalise_interval(raw, "api", ACCEPTED)

    def test_aliases_apply_to_the_local_store_and_an_unknown_list(self):
        assert normalise_interval("1d", "db", None)[0] == "D"
        assert normalise_interval("5min", "api", None)[0] == "5m"
        # Anything else is still passed through untouched where nothing is checked.
        assert normalise_interval("3D", "db", None) == ("3D", None)

    def test_the_daily_interval_follows_the_broker(self):
        assert daily_interval(["1m", "D"]) == "D"
        assert daily_interval(["1m", "1d"]) == "1d"
        assert daily_interval([]) == "D"
        assert daily_interval(None) == "D"


# ---------------------------------------------------------------------------
# market.normalise_pair and symbol_pairs
# ---------------------------------------------------------------------------


class TestPairs:
    def test_a_prefixed_symbol_needs_no_exchange(self, listed):
        assert normalise_pair("NSE:INFY", "") == ("INFY", "NSE", [])
        assert normalise_pair("nse index:NIFTY", None) == ("NIFTY", "NSE_INDEX", [])

    def test_the_prefix_wins_and_says_so(self, listed):
        symbol, exchange, notices = normalise_pair("NSE:INFY", "BSE")
        assert (symbol, exchange) == ("INFY", "NSE")
        assert notices and "NSE" in notices[0]

    def test_a_prefix_that_is_not_an_exchange_is_not_split(self, listed):
        with pytest.raises(RetryAgentRun, match="'exchange' argument"):
            normalise_pair("FOO:BAR", "")

    def test_an_empty_exchange_is_still_refused_without_a_prefix(self, listed):
        with pytest.raises(RetryAgentRun, match="'exchange' argument"):
            normalise_pair("INFY", "")

    def test_an_index_on_its_cash_exchange_still_moves(self, listed):
        symbol, exchange, notices = normalise_pair("NIFTY", "nse")
        assert (symbol, exchange) == ("NIFTY", "NSE_INDEX")
        assert notices

    def test_a_comma_separated_string_of_pairs(self, listed):
        pairs, notices = symbol_pairs("NSE:INFY, NSE:SBIN; NSE_INDEX:NIFTY")
        assert pairs == [
            {"symbol": "INFY", "exchange": "NSE"},
            {"symbol": "SBIN", "exchange": "NSE"},
            {"symbol": "NIFTY", "exchange": "NSE_INDEX"},
        ]
        assert notices == []

    def test_a_json_string_still_works(self, listed):
        pairs, _ = symbol_pairs('[{"symbol": "INFY", "exchange": "NSE"}]')
        assert pairs == [{"symbol": "INFY", "exchange": "NSE"}]

    def test_an_object_carrying_a_prefixed_symbol(self, listed):
        pairs, _ = symbol_pairs([{"symbol": "NSE:SBIN"}])
        assert pairs == [{"symbol": "SBIN", "exchange": "NSE"}]

    def test_a_string_of_bare_symbols_is_still_refused(self, listed):
        with pytest.raises(RetryAgentRun, match="'symbols' argument"):
            symbol_pairs("INFY, SBIN")

    def test_get_quotes_signature_admits_the_documented_shapes(self):
        hint = get_type_hints(market.MarketToolkit.get_quotes)["symbols"]
        adapter = TypeAdapter(hint)
        for value in (
            ["NSE:INFY", "NSE:SBIN"],
            "NSE:INFY, NSE:SBIN",
            [{"symbol": "INFY", "exchange": "NSE"}, "NSE:SBIN"],
        ):
            assert adapter.validate_python(value) == value


# ---------------------------------------------------------------------------
# get_history and plot_price_chart defaults
# ---------------------------------------------------------------------------


class TestHistoryDefaults:
    def test_get_history_with_only_a_symbol_asks_for_daily_candles_to_today(
        self, listed, monkeypatch
    ):
        kit = market.MarketToolkit(ToolContext(api_key="k"))
        calls: list[dict] = []

        def fake_service_call(fn, *args, **kwargs):
            if fn is market.intervals_service.get_intervals:
                return {"data": {"days": ["D"], "minutes": ["1m", "5m"]}}
            calls.append(kwargs)
            return {"data": []}

        monkeypatch.setattr(kit, "service_call", fake_service_call)
        result = kit.get_history("INFY", "NSE")
        assert calls[0]["interval"] == "D"
        assert calls[0]["end_date"] == _today()
        assert calls[0]["start_date"] == lookback_range("D", market.DEFAULT_HISTORY_BARS)[0]
        assert '"rows_total":0' in result.replace(" ", "")

    def test_the_tools_declare_the_defaults(self):
        import inspect

        for method in (market.MarketToolkit.get_history, viz.VizToolkit.plot_price_chart):
            parameters = inspect.signature(method).parameters
            assert parameters["interval"].default == "D"
            assert parameters["start_date"].default is None
            assert parameters["end_date"].default is None


# ---------------------------------------------------------------------------
# viz indicators and expiry lists
# ---------------------------------------------------------------------------


class TestChartIndicators:
    def test_aliases_and_hyphenated_ids(self):
        overlays = viz.normalise_indicators(
            ["bbands:20", "psar", "parabolic-sar", "stochastic_rsi", "ema(50)"]
        )
        assert [item["id"] for item in overlays] == [
            "bollinger",
            "parabolic-sar",
            "parabolic-sar",
            "stochastic-rsi",
            "ema",
        ]
        assert overlays[0]["inputs"] == {"length": 20}

    def test_a_bare_string_a_json_string_and_an_object(self):
        assert viz.normalise_indicators("ema:20") == [{"id": "ema", "inputs": {"length": 20}}]
        assert viz.normalise_indicators('["ema:20", "rsi:14"]')[1]["id"] == "rsi"
        objects = viz.normalise_indicators([{"id": "supertrend", "inputs": {"multiplier": 3}}])
        assert objects == [{"id": "supertrend", "inputs": {"multiplier": 3}}]

    def test_an_unknown_id_is_refused_with_close_matches(self):
        with pytest.raises(RetryAgentRun, match="cannot draw") as caught:
            viz.normalise_indicators(["bolinger"])
        assert "bollinger" in str(caught.value)

    def test_the_signature_admits_every_shape_the_docstring_shows(self):
        hint = get_type_hints(viz.VizToolkit.plot_price_chart)["indicators"]
        adapter = TypeAdapter(hint)
        for value in (
            ["ema:20"],
            '["ema:20"]',
            "ema:20",
            [{"id": "supertrend", "inputs": {"length": 10, "multiplier": 3}}],
            None,
        ):
            assert adapter.validate_python(value) == value

    def test_surface_expiries_accept_a_string_and_name_the_right_argument(self):
        hint = get_type_hints(viz.VizToolkit.plot_volatility_surface)["expiry_dates"]
        assert TypeAdapter(hint).validate_python("28NOV25, 26DEC25") == "28NOV25, 26DEC25"
        assert viz._expiries("28-NOV-25, 2025-12-26") == ["28NOV25", "26DEC25"]
        with pytest.raises(RetryAgentRun, match="'expiry_dates' argument"):
            viz._expiries(["28XYZ25"])


# ---------------------------------------------------------------------------
# options: expiry, offset, option type, index underlying, integers
# ---------------------------------------------------------------------------


class TestExpiry:
    @pytest.mark.parametrize(
        "raw",
        ["28OCT26", "28-OCT-26", "28oct26", "28OCT2026", "2026-10-28", "28 OCT 26", "28-Oct-2026"],
    )
    def test_every_spelling_becomes_ddmmmyy(self, raw):
        assert normalise_expiry(raw) == "28OCT26"

    def test_a_single_digit_day_is_padded(self):
        assert normalise_expiry("8OCT26") == "08OCT26"

    @pytest.mark.parametrize(
        "raw", ["28XYZ26", "2026-02-30", "32OCT26", "00OCT26", "next week", "28OCT6"]
    )
    def test_anything_else_is_still_refused(self, raw):
        with pytest.raises(RetryAgentRun, match="'expiry_date' argument"):
            normalise_expiry(raw)

    def test_an_empty_expiry_is_refused_under_the_given_name(self):
        with pytest.raises(RetryAgentRun, match="'expiry_dates' argument"):
            normalise_expiry("", "expiry_dates")

    def test_an_embedded_expiry_still_allows_an_empty_argument(self):
        assert normalise_expiry_argument("", "NIFTY28OCT25FUT", allow_embedded=True) == ""
        with pytest.raises(RetryAgentRun):
            normalise_expiry_argument("", "NIFTY", allow_embedded=True)


class TestOffsetAndType:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("atm", "ATM"),
            ("ATM0", "ATM"),
            ("ATM+0", "ATM"),
            ("otm 2", "OTM2"),
            ("OTM-2", "OTM2"),
            (" itm 10 ", "ITM10"),
            ("OTM50", "OTM50"),
        ],
    )
    def test_accepted_offsets(self, raw, expected):
        assert normalise_offset(raw) == expected

    @pytest.mark.parametrize("raw", ["ATM+2", "ATM-1", "atm 3"])
    def test_a_step_from_atm_is_refused_with_the_spelling_to_use(self, raw):
        with pytest.raises(RetryAgentRun) as caught:
            normalise_offset(raw)
        assert "OTM2" in str(caught.value) and "ITM2" in str(caught.value)

    @pytest.mark.parametrize("raw", ["OTM51", "OTM0", "NEAR", ""])
    def test_a_non_offset_is_still_refused(self, raw):
        with pytest.raises(RetryAgentRun, match="'offset' argument"):
            normalise_offset(raw)

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("CE", "CE"), ("c", "CE"), ("Call", "CE"), ("pe", "PE"), ("P", "PE"), ("PUT", "PE")],
    )
    def test_option_type_aliases(self, raw, expected):
        assert normalise_option_type(raw) == expected

    @pytest.mark.parametrize("raw", ["X", "FUT", ""])
    def test_a_non_option_type_is_still_refused(self, raw):
        with pytest.raises(RetryAgentRun, match="'option_type' argument"):
            normalise_option_type(raw)


class TestIndexUnderlying:
    def test_an_index_on_its_cash_exchange_moves(self, listed):
        exchange, notice = index_underlying("NIFTY", "NSE")
        assert exchange == "NSE_INDEX" and notice
        assert index_underlying("SENSEX", "BSE")[0] == "BSE_INDEX"

    def test_a_futures_underlying_is_looked_up_by_its_base(self, listed):
        assert index_underlying("NIFTY28OCT25FUT", "NSE")[0] == "NSE_INDEX"

    def test_a_stock_and_the_other_exchanges_stay(self, listed):
        assert index_underlying("RELIANCE", "NSE") == ("NSE", None)
        assert index_underlying("NIFTY", "NSE_INDEX") == ("NSE_INDEX", None)
        assert index_underlying("NIFTY", "NFO") == ("NFO", None)
        assert index_underlying("CRUDEOIL", "MCX") == ("MCX", None)

    def test_an_unknown_symbol_is_left_for_the_service_to_report(self, listed):
        assert index_underlying("NOSUCH", "NSE") == ("NSE", None)

    def test_the_option_chain_tool_sends_the_corrected_exchange(self, listed, monkeypatch):
        kit = options.OptionsToolkit(ToolContext(api_key="k"))
        calls: list[dict] = []

        def fake_service_call(fn, *args, **kwargs):
            calls.append(kwargs)
            return {"status": "success", "chain": []}

        monkeypatch.setattr(kit, "service_call", fake_service_call)
        result = kit.get_option_chain("NIFTY", "NSE", "28-OCT-26")
        assert calls[0]["exchange"] == "NSE_INDEX"
        assert calls[0]["expiry_date"] == "28OCT26"
        assert "notices" in result


class TestIntegers:
    def test_the_refusal_names_the_fields_own_default(self):
        with pytest.raises(RetryAgentRun, match="the default strike_count is 15"):
            normalise_int(0, "strike_count", 1, 100, 15)
        with pytest.raises(RetryAgentRun, match="the default days is 1"):
            normalise_int("ten", "days", 1, 5, 1)

    def test_without_a_default_no_value_is_suggested(self):
        with pytest.raises(RetryAgentRun) as caught:
            normalise_int(30, "width", 1, 20)
        assert "default" not in str(caught.value)
        assert "sensible" not in str(caught.value)

    def test_whole_numbers_in_range_still_pass(self):
        assert normalise_int("5", "strike_count", 0, 100, 5) == 5
        assert normalise_int(7.0, "strike_count", 0, 100, 5) == 7


# ---------------------------------------------------------------------------
# symbols.get_expiry_dates on a cash or index exchange
# ---------------------------------------------------------------------------


class TestExpiryExchange:
    @pytest.mark.parametrize(
        ("raw", "venue"),
        [
            ("NSE", "NFO"),
            ("nse index", "NFO"),
            ("BSE", "BFO"),
            ("BSE_INDEX", "BFO"),
            ("MCX_INDEX", "MCX"),
        ],
    )
    def test_a_cash_or_index_exchange_moves_to_its_derivatives(self, raw, venue):
        kit = object.__new__(SymbolsToolkit)
        resolved, notice = kit._expiry_exchange(raw)
        assert resolved == venue and venue in notice

    def test_a_derivatives_exchange_is_unchanged(self):
        kit = object.__new__(SymbolsToolkit)
        assert kit._expiry_exchange("NFO") == ("NFO", None)

    def test_an_exchange_with_no_derivatives_home_is_still_refused(self):
        kit = object.__new__(SymbolsToolkit)
        with pytest.raises(RetryAgentRun, match="derivatives exchange"):
            kit._expiry_exchange("GLOBAL_INDEX")

    def test_the_tool_reports_the_move(self, monkeypatch):
        kit = SymbolsToolkit(ToolContext(api_key="k"))
        calls: list[dict] = []

        def fake_service_call(fn, *args, **kwargs):
            calls.append(kwargs)
            return {"data": ["28-OCT-26"]}

        monkeypatch.setattr(kit, "service_call", fake_service_call)
        result = kit.get_expiry_dates("NIFTY", "NSE_INDEX", "options")
        assert calls[0]["exchange"] == "NFO"
        assert "notices" in result and "28OCT26" in result


class TestVizOptionChartsMoveAnIndex:
    """The option charts quote the underlying on the exchange they are given, so
    NIFTY on NSE has to move to NSE_INDEX here exactly as it does for the chain."""

    @pytest.mark.parametrize(
        ("method", "service_name", "kwargs"),
        [
            ("plot_open_interest", "get_option_chain", {"expiry_date": "28OCT26"}),
            ("plot_gamma_exposure", "get_gex_data", {"expiry_date": "28OCT26"}),
            ("plot_volatility_surface", "get_vol_surface_data", {"expiry_dates": ["28OCT26"]}),
        ],
    )
    def test_nifty_on_nse_reaches_the_service_on_nse_index(
        self, listed, monkeypatch, method, service_name, kwargs
    ):
        kit = viz.VizToolkit(ToolContext(api_key="k"))
        seen: list[dict] = []

        def fake_service_call(fn, *args, **call_kwargs):
            if fn is getattr(viz, service_name):
                seen.append(call_kwargs)
            return {}

        monkeypatch.setattr(kit, "service_call", fake_service_call)
        result = getattr(kit, method)(underlying="NIFTY", exchange="NSE", **kwargs)

        assert seen and seen[0]["exchange"] == "NSE_INDEX"
        assert "<tool_result" in result


class TestWeeklyAndMonthlyFromDailyCandles:
    """A broker that serves nothing above D still answers a weekly question: the
    live battery's "weekly candles of INFY" was refused on exactly such a broker."""

    DAILY_ONLY = ["1m", "5m", "15m", "1h", "D"]

    def test_weekly_on_a_daily_only_broker_is_fetched_daily_and_rolled_up(self):
        fetched, notice, rollup = market.plan_interval("W", "api", self.DAILY_ONLY)
        assert (fetched, rollup) == ("D", "W")
        assert "weekly candles were built from its daily ones" in notice

    def test_spoken_spellings_reach_the_roll_up_too(self):
        assert market.plan_interval("weekly", "api", self.DAILY_ONLY)[2] == "W"
        assert market.plan_interval("monthly", "api", self.DAILY_ONLY)[2] == "M"

    def test_a_broker_that_serves_weekly_is_asked_for_weekly(self):
        assert market.plan_interval("W", "api", ["D", "W", "M"]) == ("W", None, None)

    def test_minutes_are_never_mistaken_for_months(self):
        assert market.plan_interval("5m", "api", self.DAILY_ONLY) == ("5m", None, None)

    def test_an_unservable_interval_is_still_refused(self):
        with pytest.raises(RetryAgentRun):
            market.plan_interval("W", "api", ["1m", "5m"])

    def test_daily_candles_roll_up_into_iso_weeks(self):
        def day(y, m, d, o, h, low, c, v):
            stamp = datetime(y, m, d, tzinfo=IST).isoformat()
            return {"timestamp": stamp, "open": o, "high": h, "low": low, "close": c, "volume": v}

        rows = [
            day(2026, 10, 5, 100, 105, 99, 104, 10),  # Monday, week 41
            day(2026, 10, 7, 104, 110, 101, 108, 20),
            day(2026, 10, 9, 108, 109, 95, 97, 30),  # Friday, week 41
            day(2026, 10, 12, 97, 99, 96, 98, 5),  # Monday, week 42
        ]
        columns = market.candle_columns(rows[0])
        weeks = market.roll_up_candles(rows, columns, "W")

        assert len(weeks) == 2
        assert weeks[0]["open"] == 100 and weeks[0]["close"] == 97
        assert weeks[0]["high"] == 110 and weeks[0]["low"] == 95
        assert weeks[0]["volume"] == 60
        assert weeks[0]["timestamp"] == rows[0]["timestamp"]
        assert weeks[1]["volume"] == 5

    def test_get_history_answers_weekly_from_daily(self, listed, monkeypatch):
        kit = market.MarketToolkit(ToolContext(api_key="k"))
        asked: list[dict] = []
        daily = [
            {
                "timestamp": datetime(2026, 10, d, tzinfo=IST).isoformat(),
                "open": 1,
                "high": 2,
                "low": 1,
                "close": 2,
                "volume": 1,
            }
            for d in (5, 6, 12, 13)
        ]

        def fake_service_call(fn, *args, **kwargs):
            if fn is market.intervals_service.get_intervals:
                return {"data": {"minutes": ["1m", "5m"], "days": ["D"]}}
            asked.append(kwargs)
            return {"data": daily}

        monkeypatch.setattr(kit, "service_call", fake_service_call)
        result = kit.get_history("INFY", "NSE", interval="W")

        assert asked[0]["interval"] == "D"
        compact = result.replace(" ", "")
        assert '"interval":"W"' in compact
        assert '"rows_total":2' in compact
        assert "built from its daily ones" in result
