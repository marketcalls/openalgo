"""The indicator dispatcher: one code path for all 127 ``ta`` callables.

Pure Python over a DataFrame the caller already fetched. No database, no broker,
no clock, no HTTP. Every input arrives as an argument and every decision leaves
as a return value, which is what lets a test drive it without a running
platform and lets it be called from the agent's real OS thread without touching
anything the eventlet hub owns.

Every rule here was measured against the pinned openalgo 2.0.3 build:

* **Period arguments must be Python ``int``.** ``validate_period`` does
  ``isinstance(period, int)``, so both ``14.0`` and ``np.int64(14)`` raise
  ``TypeError``. JSON tool arguments decode every number to float, so roughly
  half of all indicator calls fail without :func:`_coerce_params`.
* **A single NaN poisons everything downstream**, because the backend's ``sma``
  and ``rolling_sum`` are cumsum based. One NaN at bar 50 of 900 left
  ``ta.sma`` with 37 finite values out of 900. Frames arrive cleaned; this
  module additionally refuses a series that is still empty or too short.
* **Warm-up varies wildly.** ``beta`` needs 253 bars before its first finite
  value, ``lrslope`` 101, ``crsi`` 100, ``adxr`` 41. :func:`required_bars` pads
  the fetch, so a caller asking for the last 10 values of ``beta`` gets numbers
  rather than ten nulls.
* **Three methods change return arity based on an argument value.**
  ``spec.conditional_outputs`` maps ``"param=value"`` to the alternate names and
  :func:`_resolve_outputs` applies it.
* **``vi`` and ``ulcerindex`` return all-NaN on this build.** They are refused
  with the reason rather than answering with a wall of nulls.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from openalgo import ta

from services.agent.indicators.descriptions import describe
from services.agent.indicators.registry import REGISTRY, IndicatorSpec, get_spec
from services.indicator_service import REQUIRED_PARAM_DEFAULTS

__all__ = [
    "IndicatorError",
    "compute",
    "required_bars",
    "search_specs",
    "spec_to_dict",
]

#: Extra bars fetched on top of the measured warm-up, so the caller gets a
#: usable tail even when the warm-up estimate is a bar or two light.
WARMUP_MARGIN = 30

#: Floor on the bars any request fetches. Below this the shortest indicator has
#: no room and the saving is not worth a second round trip.
MIN_BARS = 60

#: Decimal places kept on every returned value. Six is past the tick size of
#: anything traded here and keeps a long tail of float noise out of the model's
#: context.
_ROUND_DP = 6


class IndicatorError(Exception):
    """Raised for anything the caller can fix by changing the request.

    Distinct from a library exception on purpose: the tool layer turns this
    into a message the model can act on, and lets anything else surface as a
    platform failure.
    """


# ---------------------------------------------------------------------------
# Argument handling
# ---------------------------------------------------------------------------


def _coerce_params(spec: IndicatorSpec, params: dict[str, Any] | None) -> dict[str, Any]:
    """Cast JSON-decoded arguments into what the library will actually accept.

    This is the single most load-bearing function in the module. JSON has one
    number type and the library type-checks periods with ``isinstance(x, int)``,
    so without the coercion here about half of all calls raise ``TypeError``
    from inside the Rust backend with a message the model cannot act on.

    Args:
        spec: The indicator being called.
        params: The parameters the caller supplied, or None.

    Returns:
        The parameters, coerced to the kinds the library declares, with any
        required parameter the caller omitted filled from the shared defaults.

    Raises:
        IndicatorError: For an unknown parameter name, a period that is not a
            whole positive number, or a string outside a validated enum.
    """
    out: dict[str, Any] = {}
    for key, value in (params or {}).items():
        if key not in spec.params:
            raise IndicatorError(
                f"{spec.name} has no parameter {key!r}. Valid parameters: "
                f"{', '.join(spec.params) or 'none'}."
            )
        pspec = spec.params[key]
        if value is None:
            continue

        if pspec.kind == "int":
            try:
                as_float = float(value)
            except (TypeError, ValueError):
                raise IndicatorError(
                    f"{spec.name}.{key} must be a whole number, got {value!r}."
                ) from None
            if not as_float.is_integer():
                raise IndicatorError(f"{spec.name}.{key} must be a whole number, got {value!r}.")
            coerced: Any = int(as_float)
            if coerced <= 0:
                raise IndicatorError(f"{spec.name}.{key} must be positive, got {coerced}.")
        elif pspec.kind == "float":
            try:
                coerced = float(value)
            except (TypeError, ValueError):
                raise IndicatorError(
                    f"{spec.name}.{key} must be a number, got {value!r}."
                ) from None
        elif pspec.kind == "bool":
            coerced = (
                value.strip().lower() in ("1", "true", "yes")
                if isinstance(value, str)
                else bool(value)
            )
        else:
            coerced = str(value)
            if pspec.enum and coerced not in pspec.enum:
                raise IndicatorError(
                    f"{spec.name}.{key} must be one of {list(pspec.enum)}, got {coerced!r}."
                )
        out[key] = coerced

    # 14 ta methods declare a period with no default, so omitting it raises a
    # TypeError from inside the Rust backend that names the argument but not a
    # usable value. Filling the gap and reporting what was filled answers the
    # question in one call instead of spending a turn on "which period?".
    # The table is services.indicator_service.REQUIRED_PARAM_DEFAULTS, shared
    # with Flow's indicator node rather than copied: it is a fact about the
    # pinned library, and a second copy would drift.
    for key, value in REQUIRED_PARAM_DEFAULTS.get(spec.name, {}).items():
        if key in spec.params and key not in out:
            out[key] = value
    return out


def _resolve_outputs(spec: IndicatorSpec, params: dict[str, Any]) -> tuple[str, ...]:
    """Apply ``conditional_outputs`` when a flag changes the return arity.

    Args:
        spec: The indicator being called.
        params: The already-coerced parameters.

    Returns:
        The output names to label the returned series with.
    """
    if not spec.conditional_outputs:
        return spec.outputs
    for condition, outputs in spec.conditional_outputs.items():
        key, _, raw = condition.partition("=")
        if key not in params:
            continue
        if str(params[key]) == raw:
            return outputs
    return spec.outputs


def required_bars(spec: IndicatorSpec, params: dict[str, Any] | None = None, want: int = 10) -> int:
    """How many bars to fetch so ``want`` finite values come back.

    The measured warm-up is the floor, scaled up when the caller overrides a
    period, because warm-up tracks the period arguments. This is what makes
    "the last 10 values of beta" a real answer rather than ten nulls, and it is
    why the tools take a lookback instead of asking the operator for dates.

    Args:
        spec: The indicator being called.
        params: The parameters the caller supplied, coerced or not.
        want: How many finite values the caller wants at the end.

    Returns:
        A bar count, never below :data:`MIN_BARS`.
    """
    warmup = int(spec.warmup or 0)
    for key, value in (params or {}).items():
        pspec = spec.params.get(key)
        if not pspec or pspec.kind != "int":
            continue
        try:
            requested = int(float(value))
        except (TypeError, ValueError):
            continue
        default = pspec.default if isinstance(pspec.default, int) else None
        if default is None:
            warmup = max(warmup, requested)
        elif requested > default:
            warmup += requested - default
    return max(MIN_BARS, warmup + int(want) + WARMUP_MARGIN)


# ---------------------------------------------------------------------------
# Series handling
# ---------------------------------------------------------------------------


def _series_for(spec: IndicatorSpec, frame: pd.DataFrame) -> list[pd.Series]:
    """Map the spec's declared inputs onto real DataFrame columns.

    Args:
        spec: The indicator being called.
        frame: The cleaned candle frame.

    Returns:
        The series to pass positionally, in call order.

    Raises:
        IndicatorError: When a required column is absent, or carries nothing.

    A series is treated as carrying nothing when every bar is NaN **or** every
    bar is exactly zero. Both are what "this venue does not publish that" looks
    like, and the second is the one that actually happens: an index quotes no
    volume, and this broker serves the column as zeros rather than as nulls.
    Testing only for NaN missed it, and the 19 volume indicators then ran over
    a series of zeros. Two of them (``vwap``, ``volosc``) raised out of the
    library, and the other seventeen returned a number: ``mfi`` answered 100.0
    on NIFTY, which reads as maximally overbought, and ``rvol`` answered 1.0,
    which reads as an ordinary day. A value derived from the absence of data is
    worse than a refusal, because it is indistinguishable from a reading.

    A whole series of exact zeros is not real market data for any OHLCV column,
    so the test is not special-cased to volume. A genuinely quiet instrument
    still has one non-zero bar somewhere in the window.
    """
    series: list[pd.Series] = []
    for column in spec.inputs:
        if column not in frame.columns:
            raise IndicatorError(
                f"{spec.name} needs the {column!r} series but these candles only carry "
                f"{', '.join(map(str, frame.columns))}."
            )
        values = frame[column]
        if values.isna().all() or bool(values.fillna(0).eq(0).all()):
            carries = "is empty" if values.isna().all() else "is zero on every bar"
            hint = (
                " An index carries no volume, so a volume indicator cannot be computed on one; "
                "run it on the future or on a share instead."
                if column == "volume"
                else ""
            )
            raise IndicatorError(
                f"{spec.name}: the {column!r} series {carries} for this instrument, so any "
                f"value computed from it would come from the absence of data rather than "
                f"from the market.{hint}"
            )
        series.append(values)
    return series


def _to_list(values: Any) -> list[Any]:
    """Convert one output series into JSON-safe Python values.

    Args:
        values: A pandas Series, a numpy array or any sequence.

    Returns:
        A list where NaN and the infinities are None, booleans stay booleans,
        and everything else is a float rounded to six decimals. None is what
        both a JSON reader and a chart read as a gap, and it is the honest
        rendering of a bar the indicator had no value for.
    """
    if isinstance(values, (pd.Series, np.ndarray)):
        raw = values.tolist()
    else:
        raw = list(values)

    out: list[Any] = []
    for item in raw:
        if isinstance(item, (bool, np.bool_)):
            out.append(bool(item))
        elif item is None:
            out.append(None)
        else:
            try:
                number = float(item)
            except (TypeError, ValueError):
                out.append(None)
            else:
                out.append(
                    None if (math.isnan(number) or math.isinf(number)) else round(number, _ROUND_DP)
                )
    return out


def _stats(values: list[Any]) -> dict[str, Any]:
    """Summarise one output series so the model need not read every value.

    Args:
        values: The full output, as returned by :func:`_to_list`.

    Returns:
        The latest finite value, how many were finite, the range, and whether
        the series is rising, falling or flat. A series with no finite value
        reports that plainly rather than inventing a zero.

        A boolean output is summarised differently, because a minimum and a
        maximum of True and False say nothing. ``ta.fractals``, ``ta.rising``
        and ``ta.falling`` return booleans on this build, and counting them as
        "no finite values" would report a working signal as a broken one.
    """
    flags = [v for v in values if isinstance(v, bool)]
    if flags:
        return {
            "latest": flags[-1],
            "kind": "signal",
            "bars_true": sum(1 for value in flags if value),
            "finite_count": len(flags),
        }

    finite = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not finite:
        return {"latest": None, "finite_count": 0}

    latest = finite[-1]
    out: dict[str, Any] = {
        "latest": latest,
        "finite_count": len(finite),
        "min": min(finite),
        "max": max(finite),
    }
    if len(finite) >= 2:
        previous = finite[-2]
        out["previous"] = previous
        out["direction"] = (
            "rising" if latest > previous else ("falling" if latest < previous else "flat")
        )
    return out


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def compute(
    name: str,
    frame: pd.DataFrame,
    params: dict[str, Any] | None = None,
    second_series: pd.Series | None = None,
    last_n: int = 10,
) -> dict[str, Any]:
    """Run one indicator over a cleaned frame and return a JSON-safe result.

    Args:
        name: The exact ``ta`` method name, already lower-cased.
        frame: Cleaned candle frame, oldest first, indexed by timestamp.
        params: Indicator parameters, before coercion.
        second_series: The comparison instrument's close series, required only
            for ``correlation`` and ``beta``.
        last_n: How many recent values to return per output.

    Returns:
        The indicator name and category, the parameters actually used, the bar
        count, the output names, the timestamps of the returned tail, the tail
        of each output, and a summary of each output computed over the whole
        series rather than only the tail.

    Raises:
        IndicatorError: For an unknown or broken indicator, a bad parameter, a
            missing comparison series, or a frame too short for the period.
    """
    spec = get_spec(name)
    if spec is None:
        raise IndicatorError(
            f"Unknown indicator {name!r}. Call list_indicators to see the "
            f"{len(REGISTRY)} available names."
        )
    if spec.status == "broken":
        raise IndicatorError(
            f"{spec.name} cannot be computed on the installed openalgo build: it returns only "
            f"nulls. {spec.note} Pick a different indicator."
        )
    if not spec.inputs and not spec.needs_second_series:
        # A pair utility (crossover, exrem, valuewhen and the rest) takes two
        # already-computed series, which one instrument's candles cannot supply.
        # Refusing here with the alternative is the whole answer; letting it
        # through would reach the library as "missing 2 required positional
        # arguments", which tells the model nothing it can act on.
        raise IndicatorError(f"{spec.name} cannot be computed directly. {spec.note}")

    target = spec
    if spec.status == "alias" and spec.alias_of:
        target = get_spec(spec.alias_of) or spec

    clean_params = _coerce_params(target, params)

    if frame is None or len(frame) == 0:
        raise IndicatorError(
            f"{target.name}: no candles came back for this request. Check the symbol, the "
            "exchange and the interval, and that the range covers a trading day."
        )

    series = _series_for(target, frame)

    if target.needs_second_series:
        if second_series is None:
            raise IndicatorError(
                f"{target.name} compares two instruments and needs a second one. Supply "
                "compare_symbol and compare_exchange."
            )
        aligned = pd.Series(second_series).reindex(frame.index).ffill().bfill()
        if aligned.isna().all():
            raise IndicatorError(
                f"{target.name}: the comparison instrument's candles do not overlap this "
                "one's. Use the same interval and a range both instruments traded in."
            )
        series = [series[0], aligned]

    longest = max(
        (
            value
            for key, value in clean_params.items()
            if target.params.get(key) and target.params[key].kind == "int"
        ),
        default=0,
    )
    if longest and len(frame) <= longest:
        raise IndicatorError(
            f"{target.name}: a period of {longest} needs more than the {len(frame)} bars "
            "available. Raise lookback_bars, use a larger interval, or use a shorter period."
        )

    # Every failure inside the library becomes an IndicatorError, because the
    # caller turns that into something the model can act on and turns anything
    # else into a dead run. The library does not use one exception type for one
    # condition: an absent volume series raises ValueError from force_index and
    # RuntimeError from vwap and volosc, so an allowlist of types is a list that
    # is wrong on the next SDK release. In a batch this is the difference
    # between one indicator reporting why it could not run and the whole call,
    # including the indicators that did work, being lost.
    try:
        raw = getattr(ta, target.name)(*series, **clean_params)
    except TypeError as exc:
        raise IndicatorError(f"{target.name}: bad arguments, {exc}") from None
    except ValueError as exc:
        raise IndicatorError(f"{target.name}: {exc}") from None
    except Exception as exc:  # noqa: BLE001
        raise IndicatorError(
            f"{target.name} could not be computed on these candles: {type(exc).__name__}, {exc}"
        ) from None

    outputs = _resolve_outputs(target, clean_params)
    parts = list(raw) if isinstance(raw, tuple) else [raw]
    if len(parts) != len(outputs):
        # Trust reality over the registry rather than mislabelling a column. A
        # mismatch here means the SDK changed an arity the table records, and
        # naming the columns output_1..N is honest where a stale label is not.
        outputs = tuple(f"output_{index + 1}" for index in range(len(parts)))

    tail = max(int(last_n or 10), 1)
    values: dict[str, Any] = {}
    summary: dict[str, Any] = {}
    for label, part in zip(outputs, parts, strict=False):
        full = _to_list(part)
        values[label] = full[-tail:]
        summary[label] = _stats(full)

    result: dict[str, Any] = {
        "indicator": target.name,
        "category": target.category,
        "description": describe(target.name),
        "params_used": {
            **{key: spec_param.default for key, spec_param in target.params.items()},
            **clean_params,
        },
        "bars_used": int(len(frame)),
        "defaults_applied": sorted(key for key in clean_params if key not in (params or {}))
        or None,
        "outputs": list(outputs),
        "values_returned": min(tail, len(frame)),
        "timestamps": [_timestamp(moment) for moment in frame.index[-tail:]],
        "values": values,
        "summary": summary,
    }
    if target.note:
        result["note"] = target.note
    if spec is not target:
        result["requested_as"] = spec.name
    return result


def _timestamp(moment: Any) -> str:
    """Render one frame index entry as a string the model can read.

    Args:
        moment: A pandas Timestamp, or whatever the index holds.

    Returns:
        An ISO-8601 string when the index is a timestamp, otherwise ``str()``.
    """
    if isinstance(moment, pd.Timestamp):
        return moment.isoformat()
    return str(moment)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def spec_to_dict(spec: IndicatorSpec, verbose: bool = False) -> dict[str, Any]:
    """Render one spec for a tool result.

    Args:
        spec: The indicator.
        verbose: True for the full signature, which is what
            ``describe_indicator`` returns. False for the one-line form
            ``list_indicators`` returns, because the full form for every match
            would not fit the tool's character budget.

    Returns:
        A JSON-safe dictionary.
    """
    out: dict[str, Any] = {
        "name": spec.name,
        "category": spec.category,
        "description": describe(spec.name),
    }
    if spec.status != "ok":
        out["status"] = spec.status
        if spec.alias_of:
            out["alias_of"] = spec.alias_of
    if not verbose:
        return out

    out.update(
        {
            "requires_series": list(spec.inputs) or ["two derived series"],
            "outputs": list(spec.outputs),
            "warmup_bars": spec.warmup,
            "parameters": {
                key: {
                    "type": param.kind,
                    "default": param.default,
                    **({"required": True} if param.required else {}),
                    **({"allowed": list(param.enum)} if param.enum else {}),
                }
                for key, param in spec.params.items()
            },
        }
    )
    if spec.needs_second_series:
        out["needs_second_symbol"] = True
    if spec.conditional_outputs:
        out["conditional_outputs"] = {
            key: list(value) for key, value in spec.conditional_outputs.items()
        }
    if spec.note:
        out["note"] = spec.note
    return out


def search_specs(query: str = "", category: str = "") -> list[IndicatorSpec]:
    """Filter the registry by keyword and category.

    The description is part of the haystack, so an intent-based query such as
    "bollinger", "trend strength" or "money flow" finds the right entry without
    the caller knowing the method name.

    Args:
        query: Case-insensitive substring matched against the name, the
            category, the description and the spec's note.
        category: Exact category filter, or empty for all.

    Returns:
        Matching specs, sorted by category then name.
    """
    needle = (query or "").strip().lower()
    wanted = (category or "").strip().lower()

    found: list[IndicatorSpec] = []
    for spec in REGISTRY.values():
        if wanted and spec.category.lower() != wanted:
            continue
        if needle:
            haystack = (f"{spec.name} {spec.category} {describe(spec.name)} {spec.note}").lower()
            if needle not in haystack:
                continue
        found.append(spec)
    return sorted(found, key=lambda spec: (spec.category, spec.name))
