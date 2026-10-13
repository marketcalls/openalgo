"""Tool arguments a model really sends, reaching the normalisers instead of a refusal.

agno builds each tool's schema from its signature and wraps the method in
pydantic's ``validate_call``, so a hint narrower than the body's own normaliser
refuses a call before the normaliser ever runs. Each class here pins one input
that used to be refused or silently misread, and one genuinely invalid input
that must still be refused.

Everything is pure. No test reaches a broker, a database or the network: every
service is replaced on the module or the instance.
"""

from __future__ import annotations

import ast
import json
import typing
from typing import Any

import numpy as np
import pandas as pd
import pytest
from pydantic import TypeAdapter, ValidationError

pytest.importorskip("agno.tools", reason="the agent module needs agno")

from agno.exceptions import RetryAgentRun  # noqa: E402

import services.agent.tools.chart as chart_module  # noqa: E402
import services.agent.tools.indicators as indicators_module  # noqa: E402
import services.agent.tools.option_viz as option_viz  # noqa: E402
from services.agent import viz_sink  # noqa: E402
from services.agent.indicators.compute import (  # noqa: E402
    IndicatorError,
    compute,
    resolve_param_aliases,
)
from services.agent.indicators.registry import get_spec  # noqa: E402
from services.agent.tools import ToolContext  # noqa: E402
from services.agent.tools.chart import ChartToolkit  # noqa: E402
from services.agent.tools.indicators import (  # noqa: E402
    IndicatorsToolkit,
    evaluate_condition,
    parse_condition,
)
from services.agent.tools.option_viz import (  # noqa: E402
    OptionVizToolkit,
    leg_entries,
    leg_side_and_lots,
    leg_symbol,
    normalise_leg_expiry,
    resolve_expiry,
)
from services.agent.tools.strategy_gen import (  # noqa: E402
    StrategyGenToolkit,
    hardcoded_credentials,
    uses_websocket,
)
from services.agent.tools.websearch import (  # noqa: E402
    MAX_MAX_RESULTS,
    MIN_MAX_RESULTS,
    WebSearchToolkit,
)


def hint(method: Any, name: str) -> TypeAdapter:
    """The pydantic adapter for one tool argument, resolved exactly as agno does."""
    return TypeAdapter(typing.get_type_hints(method)[name])


def no_lot_size() -> int | None:
    raise AssertionError("the lot size is read only for a quantity")


# ---------------------------------------------------------------------------
# 1. Hints wide enough for what models send
# ---------------------------------------------------------------------------


class TestHintsLetTheNormalisersSee:
    def test_the_old_leg_hint_refused_a_fractional_strike_and_a_null_lot(self):
        # The defect itself, so the tests below cannot pass vacuously.
        old = TypeAdapter(list[str | dict[str, str | int]] | None)
        with pytest.raises(ValidationError):
            old.validate_python([{"strike": 23850.5, "option_type": "CE"}])
        with pytest.raises(ValidationError):
            old.validate_python([{"symbol": "NIFTY28NOV2523850CE", "lots": None}])
        with pytest.raises(ValidationError):
            old.validate_python('[{"symbol": "NIFTY28NOV2523850CE"}]')

    @pytest.mark.parametrize(
        "method", [OptionVizToolkit.plot_payoff, OptionVizToolkit.plot_combined_premium]
    )
    @pytest.mark.parametrize(
        "value",
        [
            [{"strike": 23850.5, "option_type": "CE", "lots": None}],
            {"symbol": "NIFTY28NOV2523850CE", "side": "SELL"},
            '[{"symbol": "NIFTY28NOV2523850CE"}]',
        ],
    )
    def test_legs_accept_floats_nulls_a_single_object_and_json_text(self, method, value):
        assert hint(method, "legs").validate_python(value) == value

    def test_option_viz_indicators_accept_a_single_object_and_json_text(self):
        adapter = hint(OptionVizToolkit.plot_combined_premium, "indicators")
        single = {"id": "supertrend", "inputs": {"length": 10, "multiplier": 3}}
        assert adapter.validate_python(single) == single
        assert adapter.validate_python(json.dumps([single])) == json.dumps([single])

    def test_indicator_params_accept_a_float_a_null_and_json_text(self):
        for method in (IndicatorsToolkit.compute_indicator, IndicatorsToolkit.scan_symbols):
            adapter = hint(method, "params")
            assert adapter.validate_python({"multiplier": 2.5, "period": None}) == {
                "multiplier": 2.5,
                "period": None,
            }
            assert adapter.validate_python('{"period": 21}') == '{"period": 21}'

    def test_batch_and_scan_lists_accept_text_and_a_single_object(self):
        batch = hint(IndicatorsToolkit.compute_indicators_batch, "indicators")
        assert batch.validate_python({"name": "rsi"}) == {"name": "rsi"}
        assert batch.validate_python("rsi, macd") == "rsi, macd"
        assert hint(IndicatorsToolkit.scan_symbols, "symbols").validate_python("SBIN") == "SBIN"

    def test_chart_settings_accept_json_text(self):
        adapter = hint(ChartToolkit.add_chart_indicator, "settings")
        assert adapter.validate_python('{"period": 20}') == '{"period": 20}'
        assert adapter.validate_python({"period": 20.0, "colour": None}) is not None

    def test_a_number_where_a_list_belongs_is_still_refused(self):
        with pytest.raises(ValidationError):
            hint(OptionVizToolkit.plot_payoff, "legs").validate_python(123)
        with pytest.raises(ValidationError):
            hint(IndicatorsToolkit.scan_symbols, "symbols").validate_python(123)

    @pytest.mark.parametrize(
        "method",
        [
            OptionVizToolkit.plot_payoff,
            OptionVizToolkit.plot_combined_premium,
            IndicatorsToolkit.compute_indicator,
            IndicatorsToolkit.compute_indicators_batch,
            IndicatorsToolkit.scan_symbols,
            ChartToolkit.add_chart_indicator,
        ],
    )
    def test_the_schema_agno_builds_is_one_every_provider_accepts(self, method):
        # A bare list renders as an array with no items, which some providers
        # refuse outright; dict[str, Any] renders its values as an empty object.
        from agno.tools.function import Function

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                if node.get("type") == "array":
                    assert "items" in node, method.__name__
                if node.get("type") == "object" and node.get("additionalProperties") is False:
                    assert node.get("properties"), method.__name__
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(Function.from_callable(method).parameters)


# ---------------------------------------------------------------------------
# 2. Option legs: side, lots, quantity, strike
# ---------------------------------------------------------------------------


class TestLegSideAndLots:
    @pytest.mark.parametrize(
        ("entry", "expected"),
        [
            ({"action": "SELL"}, ("SELL", 1)),
            ({"Side": "sell", "Lots": 2}, ("SELL", 2)),
            ({"transaction_type": "S"}, ("SELL", 1)),
            ({"ACTION": "buy", "lots": "3"}, ("BUY", 3)),
            ("NIFTY28NOV2523850CE", ("BUY", 1)),
        ],
    )
    def test_the_side_is_read_whatever_the_key_is_called(self, entry, expected):
        # {"action": "SELL"} used to be drawn as a bought leg of one lot.
        assert leg_side_and_lots(entry, 1, no_lot_size, []) == expected

    def test_a_quantity_becomes_lots_with_the_master_lot_size(self):
        assert leg_side_and_lots({"action": "SELL", "quantity": 150}, 1, lambda: 75, []) == (
            "SELL",
            2,
        )

    def test_a_quantity_without_a_lot_size_is_refused_rather_than_guessed(self):
        with pytest.raises(RetryAgentRun, match="no lot size"):
            leg_side_and_lots({"quantity": 150}, 1, lambda: None, [])

    def test_a_quantity_that_is_not_whole_lots_is_refused(self):
        with pytest.raises(RetryAgentRun, match="multiple of 75"):
            leg_side_and_lots({"qty": 100}, 1, lambda: 75, [])

    def test_a_null_lot_count_is_one_lot_with_a_notice(self):
        notices: list[str] = []
        assert leg_side_and_lots({"side": "BUY", "lots": None}, 2, no_lot_size, notices) == (
            "BUY",
            1,
        )
        assert notices == ["Leg 2 gave no lot count, so one lot was used."]

    def test_a_word_that_is_not_a_side_is_still_refused(self):
        with pytest.raises(RetryAgentRun, match="not a side"):
            leg_side_and_lots({"action": "HOLD"}, 1, no_lot_size, [])

    def test_a_strike_and_right_object_expands_like_the_shorthand(self):
        entry = {"strike": 23850.5, "option_type": "CE"}
        assert leg_symbol(entry, 1, "NIFTY", "28NOV25") == ("NIFTY28NOV2523850.5CE", "")
        assert leg_symbol({"strike": 23850.0, "right": "pe"}, 1, "NIFTY", "28NOV25")[0] == (
            "NIFTY28NOV2523850PE"
        )

    def test_a_strike_with_no_underlying_is_still_refused(self):
        with pytest.raises(RetryAgentRun, match="strike and a right"):
            leg_symbol({"strike": 23850, "option_type": "CE"}, 1, "", "")

    def test_a_single_object_sent_as_json_text_is_one_leg(self):
        text = '{"symbol": "NIFTY28NOV2523850CE", "action": "SELL"}'
        assert leg_entries(text, "legs") == [json.loads(text)]

    def test_broken_json_text_is_still_refused(self):
        with pytest.raises(RetryAgentRun, match="not valid JSON"):
            leg_entries('{"symbol": ', "legs")

    def test_named_legs_convert_a_quantity_with_the_contracts_lot_size(self, monkeypatch):
        def contract(_call, symbol, exchange, _where):
            return {"symbol": symbol, "exchange": exchange or "NFO", "lotSize": 75}

        monkeypatch.setattr(option_viz, "resolve_contract", contract)
        kit = object.__new__(OptionVizToolkit)
        kit.service_call = lambda _fn, **_kw: {"data": {"lotsize": 75}}
        notices: list[str] = []
        legs = kit._named_legs(
            [
                {"Symbol": "NIFTY28NOV2523850CE", "Action": "SELL", "Quantity": 150},
                {"strike": 23850.5, "option_type": "PE", "lots": None},
            ],
            "NIFTY",
            "28NOV25",
            notices,
        )
        assert [(leg["symbol"], leg["side"], leg["lots"]) for leg in legs] == [
            ("NIFTY28NOV2523850CE", "SELL", 2),
            ("NIFTY28NOV2523850.5PE", "BUY", 1),
        ]
        assert "Leg 2" in notices[0]


# ---------------------------------------------------------------------------
# 3. Expiry spellings
# ---------------------------------------------------------------------------


class TestExpirySpellings:
    @pytest.mark.parametrize(
        "said", ["28NOV25", "28-NOV-25", "28NOV2025", "2025-11-28", "28 NOV 25", "28 nov 2025"]
    )
    def test_every_common_spelling_comes_out_as_ddmmmyy(self, said):
        assert normalise_leg_expiry(said) == "28NOV25"

    def test_a_single_digit_day_is_padded(self):
        assert normalise_leg_expiry("5JAN26") == "05JAN26"

    @pytest.mark.parametrize("said", ["31FEB25", "28XYZ25", "tomorrow", "", "2025-13-01"])
    def test_something_that_is_not_a_date_is_refused(self, said):
        with pytest.raises(RetryAgentRun, match="DDMMMYY"):
            normalise_leg_expiry(said)

    def test_an_iso_date_reaches_the_chart_without_a_lookup(self):
        def call(_fn, **_kw):
            raise AssertionError("an exact date needs no listing")

        assert resolve_expiry(call, "NIFTY", "NSE_INDEX", "2025-11-28", []) == "28NOV25"


# ---------------------------------------------------------------------------
# 4. Indicator parameter aliases and condition names
# ---------------------------------------------------------------------------


def candles(count: int = 200) -> pd.DataFrame:
    """A deterministic candle frame long enough for every period used here."""
    rng = np.random.default_rng(7)
    close = 100 + np.cumsum(rng.normal(0, 1, count))
    index = pd.date_range("2025-01-01", periods=count, freq="D")
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(count, 1000.0),
        },
        index=index,
    )


class TestIndicatorParameterAliases:
    @pytest.mark.parametrize(
        ("indicator", "given", "expected"),
        [
            ("rsi", {"length": 21}, {"period": 21}),
            (
                "macd",
                {"fast": 8, "slow": 21, "signal": 5},
                {
                    "fast_period": 8,
                    "slow_period": 21,
                    "signal_period": 5,
                },
            ),
            ("bbands", {"std": 2.5}, {"std_dev": 2.5}),
            ("kama", {"fast": 3}, {"fast_length": 3}),
            ("rsi", {"Period": 14}, {"period": 14}),
        ],
    )
    def test_a_borrowed_name_maps_to_the_indicators_own(self, indicator, given, expected):
        assert resolve_param_aliases(get_spec(indicator), given) == expected

    def test_a_real_parameter_is_never_renamed(self):
        # kama really has a parameter called length.
        assert resolve_param_aliases(get_spec("kama"), {"length": 10}) == {"length": 10}

    def test_compute_runs_with_an_alias_and_reports_the_real_name(self):
        result = compute("rsi", candles(), {"length": 21}, last_n=3)
        assert result["params_used"]["period"] == 21
        assert result["defaults_applied"] is None

    def test_an_alias_next_to_its_real_name_is_still_refused(self):
        with pytest.raises(IndicatorError, match="no parameter 'length'"):
            compute("rsi", candles(), {"length": 21, "period": 14}, last_n=3)

    def test_a_name_that_is_no_alias_is_still_refused(self):
        with pytest.raises(IndicatorError, match="no parameter 'window'"):
            compute("rsi", candles(), {"window": 21}, last_n=3)

    def test_a_condition_matches_output_names_case_insensitively(self):
        result = {"indicator": "rsi", "values": {"rsi": [40.0, 25.0]}}
        hit, detail = evaluate_condition(parse_condition("RSI < 30"), result)
        assert hit is True and detail["condition_met"] is True
        macd = {"indicator": "macd", "values": {"macd_line": [1.0], "signal_line": [0.5]}}
        assert evaluate_condition(parse_condition("MACD_LINE > 0"), macd)[0] is True

    def test_an_output_the_indicator_does_not_have_still_fails(self):
        result = {"indicator": "rsi", "values": {"rsi": [25.0]}, "outputs": ["rsi"]}
        hit, detail = evaluate_condition(parse_condition("ADX < 30"), result)
        assert hit is False and "no output named" in detail["error"]


class TestIndicatorToolkitArguments:
    def test_params_sent_as_json_text_are_decoded(self):
        kit = object.__new__(IndicatorsToolkit)
        assert kit._params('{"period": 21}', "params") == {"period": 21}
        assert kit._params(None, "params") == {}

    def test_params_text_that_is_not_an_object_is_refused(self):
        kit = object.__new__(IndicatorsToolkit)
        with pytest.raises(RetryAgentRun, match="named parameters"):
            kit._params("period 21", "params")

    def test_batch_entries_arrive_as_text_json_or_one_object(self):
        kit = object.__new__(IndicatorsToolkit)
        assert kit._batch_requests("rsi, macd") == [("rsi", {}), ("macd", {})]
        assert kit._batch_requests('[{"name": "sma", "params": "{\\"period\\": 50}"}]') == [
            ("sma", {"period": 50})
        ]
        assert kit._batch_requests({"name": "rsi"}) == [("rsi", {})]

    def test_an_unknown_batch_name_is_still_refused(self):
        kit = object.__new__(IndicatorsToolkit)
        with pytest.raises(RetryAgentRun):
            kit._batch_requests("rsi, not_an_indicator")

    def test_scan_symbols_take_comma_text_and_an_upper_case_condition(self, monkeypatch):
        frame = candles()
        rows = [
            {
                "timestamp": int(moment.timestamp()),
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": float(row.volume),
            }
            for moment, row in frame.iterrows()
        ]
        monkeypatch.setattr(
            indicators_module,
            "get_history",
            lambda **_: (True, {"status": "success", "data": rows}, 200),
        )
        monkeypatch.setattr(
            indicators_module.intervals_service,
            "get_intervals",
            lambda **_: (True, {"data": {"days": ["D"], "minutes": [], "hours": []}}, 200),
        )
        monkeypatch.setattr(
            indicators_module,
            "normalise_pair",
            lambda symbol, exchange: (str(symbol).upper(), str(exchange).upper(), []),
        )
        kit = IndicatorsToolkit(
            ToolContext(api_key="k", surface="chat", trading_enabled=False, conversation_id=0)
        )
        answer = kit.scan_symbols("SBIN, INFY", "NSE", "rsi", "RSI < 101", params='{"length": 14}')
        assert '"matched_count": 2' in answer.replace(":2", ": 2")
        with pytest.raises(RetryAgentRun):
            kit.scan_symbols("SBIN", "NSE", "rsi", "RSI between 20 and 30")


# ---------------------------------------------------------------------------
# 5. Chart vocabulary
# ---------------------------------------------------------------------------

DAY = 86400.0
START = 1_700_000_000.0


def zigzag(levels: list[float], leg: int = 8) -> list[float]:
    out = [levels[0]]
    for start, end in zip(levels, levels[1:], strict=False):
        out.extend(start + (end - start) * step / leg for step in range(1, leg + 1))
    return out


@pytest.fixture
def chart(monkeypatch):
    closes = zigzag([100, 130, 100, 130, 100, 130, 105, 128, 115])
    rows = []
    for index, close in enumerate(closes):
        previous = closes[index - 1] if index else close
        rows.append(
            {
                "timestamp": int(START + index * DAY),
                "open": previous,
                "high": max(previous, close) + 3.0,
                "low": min(previous, close) - 3.0,
                "close": close,
                "volume": 1000 + index,
            }
        )
    monkeypatch.setattr(
        chart_module, "get_history", lambda **_: (True, {"status": "success", "data": rows}, 200)
    )
    monkeypatch.setattr(
        chart_module,
        "get_intervals",
        lambda **_: (True, {"data": {"days": ["D"], "minutes": [], "hours": []}}, 200),
    )
    sink = viz_sink.new_sink()
    context = ToolContext(
        api_key="k",
        surface="chart",
        trading_enabled=True,
        conversation_id=0,
        extras={
            "chart_context": {
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "interval": "D",
                "chart_type": "candlestick",
                "bars_loaded": 80,
                "visible_bars": 80,
                "visible_from": None,
                "visible_to": None,
                "last_price": 115.0,
                "indicators": [],
                "drawings": [],
                "agent_groups": [],
            },
            viz_sink.SINK_KEY: sink,
            "user_message": "draw the channel",
        },
    )
    return ChartToolkit(context), sink


def drained(sink) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for frame in viz_sink.drain(sink):
        out.extend(getattr(frame, "commands", []))
    return out


class TestChartVocabulary:
    @pytest.mark.parametrize(
        ("said", "sent"),
        [
            ("aroon_oscillator", "aroon-oscillator"),
            ("ut bot", "ut-bot"),
            ("Parabolic SAR", "parabolic-sar"),
        ],
    )
    def test_indicator_names_become_kebab_case_ids(self, chart, said, sent):
        kit, sink = chart
        kit.add_chart_indicator(said)
        kit.remove_chart_indicator(said)
        assert [command["id"] for command in drained(sink)] == [sent, sent]

    def test_a_period_in_the_name_is_still_refused(self, chart):
        kit, sink = chart
        with pytest.raises(RetryAgentRun, match="goes in settings"):
            kit.add_chart_indicator("EMA 20")
        assert drained(sink) == []

    def test_settings_sent_as_json_text_reach_the_chart(self, chart):
        kit, sink = chart
        kit.add_chart_indicator("ema", settings='{"period": 50}')
        assert drained(sink)[0]["settings"] == {"period": 50}

    def test_settings_text_that_is_not_an_object_is_refused(self, chart):
        kit, _sink = chart
        with pytest.raises(RetryAgentRun, match="named inputs"):
            kit.add_chart_indicator("ema", settings="period 50")

    @pytest.mark.parametrize(
        ("said", "group"),
        [
            ("all", None),
            ("level", "levels"),
            ("levels", "levels"),
            ("zones", "zone"),
            ("pattern", "patterns"),
            ("trendlines", "trendline"),
        ],
    )
    def test_clear_takes_all_and_either_number(self, chart, said, group):
        kit, sink = chart
        kit.clear_drawings(said)
        assert drained(sink) == [{"op": "clear", "group": group}]

    def test_clear_still_refuses_a_group_that_does_not_exist(self, chart):
        kit, sink = chart
        with pytest.raises(RetryAgentRun):
            kit.clear_drawings("arrows")
        assert drained(sink) == []

    def test_a_channel_is_both_rails(self, chart):
        kit, sink = chart
        answer = kit.draw_trendline(side="channel")
        assert "rail(s)" in answer
        assert drained(sink)[0]["group"] == "trendline"

    def test_consolidation_is_a_range_zone(self, chart):
        kit, _sink = chart
        assert (
            kit._choice(
                "kind", "Consolidation", chart_module._ZONE_KINDS, chart_module._ZONE_KIND_ALIASES
            )
            == "range"
        )
        with pytest.raises(RetryAgentRun):
            kit.draw_zone(kind="triangle")


# ---------------------------------------------------------------------------
# 6. Web search result count
# ---------------------------------------------------------------------------


class TestWebSearchResultCount:
    def test_an_out_of_range_count_is_clamped_with_a_notice(self):
        kit = object.__new__(WebSearchToolkit)
        count, notice = kit._validated_max_results(50)
        assert count == MAX_MAX_RESULTS and "50 results were asked for" in notice
        assert kit._validated_max_results(0)[0] == MIN_MAX_RESULTS
        assert kit._validated_max_results("5") == (5, None)

    def test_a_count_that_is_not_a_number_is_still_refused(self):
        kit = object.__new__(WebSearchToolkit)
        with pytest.raises(RetryAgentRun, match="whole number"):
            kit._validated_max_results("lots")


# ---------------------------------------------------------------------------
# 7. Strategy source checks
# ---------------------------------------------------------------------------

REST_ONLY = """
import os
from openalgo import api
API_KEY = os.getenv('OPENALGO_API_KEY', '')
API_HOST = os.getenv('HOST_SERVER', 'http://127.0.0.1:5000')
symbol_token = "NIFTY24OCT2425000CE"
client = api(api_key=API_KEY, host=API_HOST)
client.placeorder(symbol=symbol_token, exchange="NFO", action="BUY", quantity=75)
"""


class TestStrategySourceChecks:
    def test_a_trading_symbol_in_a_token_named_variable_is_not_a_secret(self):
        assert hardcoded_credentials(ast.parse(REST_ONLY)) == []
        futures = 'feed_token = "CRUDEOILM20MAY24FUT"\nstrike_token = "VEDL25APR24292.5CE"'
        assert hardcoded_credentials(ast.parse(futures)) == []

    @pytest.mark.parametrize(
        "source",
        [
            'access_token = "eyJhbGciOiJIUzI1NiJ9abc123"',
            'symbol_token = "a1b2c3d4e5f6a7b8"',
            'api_key = "NIFTY24OCT2425000CEdeadbeef1234"',
        ],
    )
    def test_a_real_key_or_token_is_still_found(self, source):
        assert hardcoded_credentials(ast.parse(source))

    def test_a_rest_only_strategy_need_not_read_the_websocket_url(self):
        tree = ast.parse(REST_ONLY)
        assert uses_websocket(tree) is False
        StrategyGenToolkit._require_environment_reads(object.__new__(StrategyGenToolkit), tree)

    def test_a_streaming_strategy_must_still_read_it(self):
        streaming = (
            REST_ONLY + "client.connect()\nclient.subscribe_ltp([], on_data_received=print)\n"
        )
        tree = ast.parse(streaming)
        assert uses_websocket(tree) is True
        with pytest.raises(RetryAgentRun, match="WEBSOCKET_URL"):
            StrategyGenToolkit._require_environment_reads(object.__new__(StrategyGenToolkit), tree)
