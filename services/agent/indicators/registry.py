"""The 127-entry indicator registry for the ``openalgo.ta`` singleton.

``from openalgo import ta`` yields a *singleton instance* of
``TechnicalAnalysis``, not a module. On the pinned openalgo 2.0.3 build
``len([m for m in dir(ta) if not m.startswith("_")]) == 127``: 114 indicators
plus 13 utilities. The introduction doc says "over 80" and the flow reference
says 116; both are wrong. Every fact below was obtained by executing the
installed build over OHLCV frames, not by reading a doc page.

Why this is not ``services/indicator_service.py``
-------------------------------------------------

``indicator_service.list_supported_indicators()`` returns **116**, and the 11 it
leaves out are ``beta``, ``correlation``, ``cross``, ``crossover``,
``crossunder``, ``exrem``, ``flip``, ``median_bands``, ``ulcerindex``,
``valuewhen`` and ``vi``. That list is correct **for its consumer**: it feeds
Flow's single-symbol ``indicator`` node, whose graph shape cannot express a
second price series at all, so a two-series indicator there could only fail.

The agent is a different consumer. It takes ``compare_symbol`` and fetches the
second series, so eight of those eleven are usable, and several of them
(``crossover``, ``crossunder``, ``valuewhen``) are exactly the primitives a scan
is built from. Widening the service instead would change the vocabulary of a
node that ships in an operator's saved workflows, to serve a caller the node
cannot serve. So the catalogue lives here, the service is left alone, and the
two agree wherever they overlap:

* ``vi`` and ``ulcerindex`` really do return all-NaN on this build, measured
  again here. Both are registered ``status="broken"`` and refused with the
  reason, which is the same verdict ``UNSUPPORTED_INDICATORS`` reaches.
* ``median_bands`` is in the service's unsupported set but **works** on this
  build: measured first finite values at bars 2, 13, 13 and 2 of its four
  outputs. It is registered ``ok`` here. The service is not edited for it,
  because a Flow node offering it would still have to answer for the extra
  optional ``source`` series.

Why ``inputs`` and ``outputs`` are hand-coded
--------------------------------------------

They are not derivable at runtime, and this is the one place in this repository
where a hand-written map is the correct answer rather than the lazy one:

* 22 methods carry no parameter annotations at all (``alligator``,
  ``avgprice``, ``bbpercent``, ``bbwidth``, ``chandelier_exit``, ``chop``,
  ``fractals``, ``gator_oscillator``, ``hv``, ``kst``, ``ma_envelopes``,
  ``mcginley``, ``medprice``, ``rwi``, ``starc``, ``stc``, ``trima``, ``tsi``,
  ``typprice``, ``ulcerindex``, ``vidya``, ``wclprice``), and a further dozen
  annotate the series but not the return.
* Several methods annotated ``-> np.ndarray`` actually return a ``pd.Series``,
  because ``BaseIndicator.format_output`` mirrors the input type.
* Parameter *names* do not identify the OHLCV column: ``ta.hv`` calls its close
  series ``close``, ``ta.sma`` calls it ``data``, ``ta.bop`` calls open
  ``open_prices``.

What keeps it from going stale is the other half of the design, and it must not
be dropped: :attr:`IndicatorSpec.params` is built at import from
``inspect.signature`` with the series arguments removed, so a renamed parameter
or a changed default is picked up immediately, and :func:`validate_registry`
compares the table against ``dir(ta)`` and is asserted at import.

Traps this table encodes, all verified by execution
---------------------------------------------------

* ``ta.frama`` takes (high, low), NOT close.
* ``ta.bop``, ``ta.rvi`` and ``ta.avgprice`` take the full OHLC set; open is
  named ``open_prices``.
* ``ta.emv`` takes (high, low, volume) with NO close.
* ``ta.volosc``, ``ta.vroc`` and ``ta.rvol`` take volume as their only series.
* ``ta.correlation(data1, data2)`` and ``ta.beta(asset, market)`` take two
  independent price series and cannot be driven from one OHLCV frame. Flagged
  ``needs_second_series=True``.
* ``ta.adx`` returns (plus_di, minus_di, adx). ADX is the THIRD element.
* ``ta.psar`` returns a SINGLE series, not the 2-tuple the hybrid doc shows.
* ``ta.aroon`` default period is 25, not 14.
* ``ta.stochastic`` hides ``smooth_k`` between ``k_period`` and ``d_period``.
* ``ta.rvi`` is the Relative *Vigor* Index (OHLC, 2-tuple). The Relative
  *Volatility* Index is imported as ``VolatilityRVI`` and never exposed on
  ``ta``.
* ``ta.median_bands`` takes ``source`` as its 4th positional parameter, an
  optional override series defaulting to hl2. Pass the tuning parameters by
  keyword or an int binds silently to ``source``.
* ``ta.vwap`` accepts six band-multiplier arguments and still returns a single
  Series.
* ``ta.uo_oscillator`` is numerically identical to ``ta.ultimate_oscillator``.
  Registered ``status="alias"``.
* Three methods change return arity based on an argument value, recorded in
  ``conditional_outputs``: ``obv_smoothed``
  (``ma_type='SMA + Bollinger Bands'`` gives a 3-tuple), ``variance``
  (``return_components=True`` gives a 5-tuple) and ``ulcerindex``
  (``return_signal=True`` gives a 2-tuple).
* The 13 utilities take derived series rather than OHLCV columns, so their
  ``inputs`` is empty and their real series parameters are in ``series_args``.
  They always return a raw ``np.ndarray``, so the pandas index is lost.

Caller obligations, enforced in :mod:`compute` rather than here
---------------------------------------------------------------

* Clean the frame before every call. The backend's ``sma`` and ``rolling_sum``
  are cumsum based, so one NaN at bar 50 of 900 leaves ``ta.sma`` with 37
  finite values out of 900. Measured.
* Period arguments must be Python ``int``. ``validate_period`` does
  ``isinstance(period, int)``, so both ``14.0`` and ``np.int64(14)`` raise
  ``TypeError``, and JSON decodes every number to float.
* :attr:`IndicatorSpec.warmup` is the measured index of the first bar where
  every output is finite, using the defaults in ``params``. It scales with the
  period arguments, so treat it as the minimum padding.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from openalgo import ta

CATEGORIES: tuple[str, ...] = (
    "trend",
    "momentum",
    "volatility",
    "volume",
    "oscillators",
    "statistical",
    "hybrid",
    "talib_extra",
    "utility",
)

#: The OHLCV column names an indicator may declare as an input.
OHLCV: tuple[str, ...] = ("open", "high", "low", "close", "volume")

_STATUSES = ("ok", "broken", "alias")

__all__ = [
    "CATEGORIES",
    "CATEGORY_COUNTS",
    "OHLCV",
    "REGISTRY",
    "IndicatorSpec",
    "ParamSpec",
    "get_spec",
    "ta_callables",
    "validate_registry",
]


@dataclass(frozen=True)
class ParamSpec:
    """One non-series argument of an indicator, read from ``inspect.signature``.

    Attributes:
        name: The parameter name, exactly as the library declares it.
        kind: ``int``, ``float``, ``str`` or ``bool``.
        default: The library's own default, or None when the parameter is
            required.
        enum: The values the library validates, when it validates any.
        required: True when the library declares no default, so a caller that
            omits it gets a ``TypeError``.
    """

    name: str
    kind: str
    default: Any = None
    enum: tuple[Any, ...] | None = None
    required: bool = False


@dataclass(frozen=True)
class IndicatorSpec:
    """One callable on the ``ta`` singleton.

    Attributes:
        name: The exact method name on ``ta``.
        category: One of :data:`CATEGORIES`.
        inputs: OHLCV column names the method needs, in call order. Empty for
            the utilities, which take derived series.
        outputs: Output names in return order. A 1-tuple means a single series.
        params: Non-series arguments, keyed by name, in signature order. Built
            at import from the live signature.
        status: ``ok``, ``broken`` or ``alias``.
        alias_of: For ``status="alias"``, the canonical method name.
        warmup: Bars of leading NaN before every output is finite, with the
            library's own defaults.
        note: Caveats a caller must know.
        series_args: The signature parameter names carrying series data, in
            order. ``inputs[i]`` maps to ``series_args[i]``. Longer than
            ``inputs`` when the method takes an extra optional series
            (``median_bands.source``) or a second independent price series
            (``correlation``, ``beta``).
        needs_second_series: True when the method compares two instruments.
        conditional_outputs: Maps ``"param=value"`` to the alternate outputs
            produced when that argument is supplied.
    """

    name: str
    category: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    params: Mapping[str, ParamSpec] = field(default_factory=dict)
    status: str = "ok"
    alias_of: str | None = None
    warmup: int = 0
    note: str = ""
    series_args: tuple[str, ...] = ()
    needs_second_series: bool = False
    conditional_outputs: Mapping[str, tuple[str, ...]] | None = None


# ---------------------------------------------------------------------------
# Parameter extraction
# ---------------------------------------------------------------------------

#: The only string parameters the library actually validates. Everything else
#: that looks enum-like (``apo.ma_type``, ``ulcerindex.signal_type``,
#: ``vwap.anchor``, ``vwap.source``) is accepted silently, so it stays free-form
#: here and is called out in the spec note instead.
_ENUMS: dict[str, dict[str, tuple[str, ...]]] = {
    "obv_smoothed": {
        "ma_type": (
            "None",
            "SMA",
            "SMA + Bollinger Bands",
            "EMA",
            "SMMA (RMA)",
            "WMA",
            "VWMA",
        ),
    },
    "po": {"ma_type": ("SMA", "EMA")},
    "ma_envelopes": {"ma_type": ("SMA", "EMA")},
    "variance": {"mode": ("PR", "LR")},
    "pvi_with_signal": {"signal_type": ("EMA", "SMA")},
}

_ANNOTATION_KINDS: dict[Any, str] = {
    bool: "bool",
    int: "int",
    float: "float",
    str: "str",
    "bool": "bool",
    "int": "int",
    "float": "float",
    "str": "str",
}


def _kind_of(param: inspect.Parameter) -> str:
    """Infer a JSON-schema-ish kind for one parameter.

    The annotation is read first and the default's type second, because 22
    methods carry no annotations at all.

    Args:
        param: The parameter from the live signature.

    Returns:
        ``int``, ``float``, ``str`` or ``bool``. ``bool`` is checked before
        ``int`` because ``bool`` is a subclass of ``int``.
    """
    annotation = param.annotation
    if annotation is not inspect.Parameter.empty:
        kind = _ANNOTATION_KINDS.get(annotation)
        if kind:
            return kind

    default = param.default
    if default is not inspect.Parameter.empty:
        if isinstance(default, bool):
            return "bool"
        if isinstance(default, int):
            return "int"
        if isinstance(default, float):
            return "float"
        if isinstance(default, str):
            return "str"
    return "str"


def _build_params(name: str, series_args: tuple[str, ...]) -> dict[str, ParamSpec]:
    """Read the live signature of one ``ta`` method, dropping its series arguments.

    This is what keeps the hand-written half of the table honest: a future SDK
    that renames ``period`` to ``length`` or changes a default is reflected here
    without an edit, and the change shows up in ``describe_indicator``.

    Args:
        name: The method name on ``ta``.
        series_args: Parameter names carrying series data, which are supplied
            positionally by the dispatcher and are not parameters the model
            sets.

    Returns:
        The remaining parameters, keyed by name, in signature order.
    """
    fn = getattr(ta, name, None)
    if fn is None:
        return {}

    enums = _ENUMS.get(name, {})
    out: dict[str, ParamSpec] = {}
    for pname, param in inspect.signature(fn).parameters.items():
        if pname in series_args or pname in ("self", "args", "kwargs"):
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        required = param.default is inspect.Parameter.empty
        out[pname] = ParamSpec(
            name=pname,
            kind=_kind_of(param),
            default=None if required else param.default,
            enum=enums.get(pname),
            required=required,
        )
    return out


def _series_args_from_signature(name: str, count: int) -> tuple[str, ...]:
    """Return the first ``count`` parameter names of a ``ta`` method.

    Every ``ta`` method lists its series arguments before any scalar one, so
    the first ``len(inputs)`` names are the series arguments.

    Args:
        name: The method name on ``ta``.
        count: How many series arguments the spec declares.

    Returns:
        The parameter names, or an empty tuple when the method is absent.
    """
    fn = getattr(ta, name, None)
    if fn is None:
        return ()
    return tuple(list(inspect.signature(fn).parameters)[:count])


def _spec(
    name: str,
    category: str,
    inputs: tuple[str, ...],
    outputs: tuple[str, ...],
    warmup: int = 0,
    *,
    series_args: tuple[str, ...] | None = None,
    status: str = "ok",
    alias_of: str | None = None,
    note: str = "",
    needs_second_series: bool = False,
    conditional_outputs: dict[str, tuple[str, ...]] | None = None,
) -> IndicatorSpec:
    """Build one registry entry, filling ``params`` from the live signature.

    Args:
        name: The method name on ``ta``.
        category: One of :data:`CATEGORIES`.
        inputs: OHLCV column names, in call order.
        outputs: Output names, in return order.
        warmup: Measured bars of leading NaN with the library's own defaults.
        series_args: Parameter names carrying series data, when they cannot be
            read as the first ``len(inputs)`` names.
        status: ``ok``, ``broken`` or ``alias``.
        alias_of: Canonical name, for an alias.
        note: Caveats a caller must know.
        needs_second_series: True for an indicator comparing two instruments.
        conditional_outputs: Alternate outputs keyed by ``"param=value"``.

    Returns:
        The populated :class:`IndicatorSpec`.
    """
    assert category in CATEGORIES, f"{name}: unknown category {category}"
    assert status in _STATUSES, f"{name}: unknown status {status}"
    assert all(item in OHLCV for item in inputs), f"{name}: inputs must be OHLCV names"

    resolved = (
        series_args if series_args is not None else _series_args_from_signature(name, len(inputs))
    )
    return IndicatorSpec(
        name=name,
        category=category,
        inputs=inputs,
        outputs=outputs,
        params=MappingProxyType(_build_params(name, resolved)),
        status=status,
        alias_of=alias_of,
        warmup=warmup,
        note=note,
        series_args=resolved,
        needs_second_series=needs_second_series,
        conditional_outputs=(
            MappingProxyType(dict(conditional_outputs)) if conditional_outputs else None
        ),
    )


_HL = ("high", "low")
_HLC = ("high", "low", "close")
_HLCV = ("high", "low", "close", "volume")
_OHLC = ("open", "high", "low", "close")
_CV = ("close", "volume")
_C = ("close",)
_V = ("volume",)

_NO_DEFAULT_PERIOD = (
    "period has no default: the caller must supply it or the call raises TypeError."
)
_UTILITY = (
    "Utility function: it takes a plain series rather than a named OHLCV role, and always "
    "returns a raw np.ndarray, so the pandas index is lost."
)
_UTILITY_ON_CLOSE = _UTILITY + " Run on the close series here. "
_UTILITY_PAIR = (
    "Utility function taking TWO derived series, which one instrument's candles cannot "
    "supply, so it has no callable form through these tools. Use scan_symbols, whose "
    "condition accepts crossover(a, b), crossunder(a, b) and cross(a, b) over an "
    "indicator's own outputs: that is what this primitive is for."
)


# ---------------------------------------------------------------------------
# The table. inputs and outputs are hand-coded; see the module docstring.
# ---------------------------------------------------------------------------

_SPECS: tuple[IndicatorSpec, ...] = (
    # ---- trend (20) --------------------------------------------------------
    _spec("sma", "trend", _C, ("sma",), 13, note=_NO_DEFAULT_PERIOD + " Warm-up is period-1."),
    _spec(
        "ema",
        "trend",
        _C,
        ("ema",),
        0,
        note=_NO_DEFAULT_PERIOD + " No warm-up: seeded from bar 0.",
    ),
    _spec("wma", "trend", _C, ("wma",), 13, note=_NO_DEFAULT_PERIOD + " Warm-up is period-1."),
    _spec(
        "dema",
        "trend",
        _C,
        ("dema",),
        26,
        note=_NO_DEFAULT_PERIOD + " Warm-up is about 2*period-2.",
    ),
    _spec(
        "tema",
        "trend",
        _C,
        ("tema",),
        39,
        note=_NO_DEFAULT_PERIOD + " Warm-up is about 3*period-3.",
    ),
    _spec("hma", "trend", _C, ("hma",), 15, note=_NO_DEFAULT_PERIOD),
    _spec(
        "vwma",
        "trend",
        _CV,
        ("vwma",),
        13,
        series_args=("data", "volume"),
        note="Takes close and volume. " + _NO_DEFAULT_PERIOD,
    ),
    _spec("alma", "trend", _C, ("alma",), 20),
    _spec("kama", "trend", _C, ("kama",), 14, note="Period argument is named length, not period."),
    _spec("zlema", "trend", _C, ("zlema",), 0, note=_NO_DEFAULT_PERIOD),
    _spec("t3", "trend", _C, ("t3",), 0),
    _spec(
        "frama",
        "trend",
        _HL,
        ("frama",),
        0,
        note="TRAP: takes high and low, NOT close, unlike every other moving average.",
    ),
    _spec("trima", "trend", _C, ("trima",), 19),
    _spec("mcginley", "trend", _C, ("mcginley",), 13),
    _spec("vidya", "trend", _C, ("vidya",), 14),
    _spec(
        "alligator",
        "trend",
        _C,
        ("jaw", "teeth", "lips"),
        20,
        note="Shift arguments displace the lines; warm-up differs per line (20/12/7).",
    ),
    _spec(
        "ma_envelopes",
        "trend",
        _C,
        ("upper_envelope", "middle_line", "lower_envelope"),
        19,
        note="ma_type is validated: SMA or EMA only.",
    ),
    _spec(
        "supertrend",
        "trend",
        _HLC,
        ("supertrend", "direction"),
        9,
        note=(
            "direction is float64 and carries the Pine convention, which is the opposite "
            "of what the sign reads like: -1.0 means the trend is UP and the supertrend "
            "line sits BELOW price, +1.0 means the trend is DOWN and the line sits above "
            "it. Report -1 as bullish. It is not a bool. Arguments are period then "
            "multiplier."
        ),
    ),
    _spec(
        "ichimoku",
        "trend",
        _HLC,
        ("conversion_line", "base_line", "leading_span_a", "leading_span_b", "lagging_span"),
        76,
        note="Per-line warm-up is 8/25/50/76/0; the spans are displaced forward.",
    ),
    _spec(
        "ckstop",
        "trend",
        _HLC,
        ("stop_long", "stop_short"),
        17,
        note="Chande Kroll Stop. Arguments are p (atr period), x (multiplier), q (stop period).",
    ),
    # ---- momentum (9) ------------------------------------------------------
    _spec("rsi", "momentum", _C, ("rsi",), 14),
    _spec("macd", "momentum", _C, ("macd_line", "signal_line", "histogram"), 0),
    _spec(
        "stochastic",
        "momentum",
        _HLC,
        ("k_percent", "d_percent"),
        17,
        note="TRAP: positional order is k_period, smooth_k, d_period. The docs omit smooth_k, "
        "so ta.stochastic(h, l, c, 14, 3) sets smooth_k, not d_period.",
    ),
    _spec("cci", "momentum", _HLC, ("cci",), 19),
    _spec("williams_r", "momentum", _HLC, ("williams_r",), 13),
    _spec(
        "bop",
        "momentum",
        _OHLC,
        ("bop",),
        0,
        note="Takes full OHLC; the open series parameter is named open_prices.",
    ),
    _spec("elderray", "momentum", _HLC, ("bull_power", "bear_power"), 0),
    _spec("fisher", "momentum", _HL, ("fisher", "trigger"), 8),
    _spec(
        "crsi",
        "momentum",
        _C,
        ("crsi",),
        99,
        note="Connors RSI. lenroc=100 means it needs about 100 bars before the first value.",
    ),
    # ---- volatility (15) ---------------------------------------------------
    _spec("atr", "volatility", _HLC, ("atr",), 13),
    _spec("bbands", "volatility", _C, ("upper_band", "middle_band", "lower_band"), 19),
    _spec("keltner", "volatility", _HLC, ("upper_channel", "middle_line", "lower_channel"), 19),
    _spec(
        "donchian",
        "volatility",
        _HL,
        ("upper_channel", "middle_line", "lower_channel"),
        19,
        note="Takes high and low only, no close.",
    ),
    _spec(
        "chaikin",
        "volatility",
        _HL,
        ("chaikin",),
        19,
        note="Chaikin Volatility: high and low only, not the Chaikin oscillator (see ta.cho).",
    ),
    _spec("natr", "volatility", _HLC, ("natr",), 13),
    _spec(
        "ultimate_oscillator",
        "volatility",
        _HLC,
        ("ultimate_oscillator",),
        27,
        note="Numerically identical to ta.uo_oscillator; this is the canonical one.",
    ),
    _spec("true_range", "volatility", _HLC, ("true_range",), 0),
    _spec("massindex", "volatility", _HL, ("massindex",), 9),
    _spec("bbpercent", "volatility", _C, ("bbpercent",), 19),
    _spec("bbwidth", "volatility", _C, ("bbwidth",), 19),
    _spec("chandelier_exit", "volatility", _HLC, ("long_exit", "short_exit"), 21),
    _spec(
        "hv",
        "volatility",
        _C,
        ("hv",),
        10,
        series_args=("close",),
        note="Historical volatility. Its close series parameter is literally named close.",
    ),
    _spec(
        "ulcerindex",
        "volatility",
        _C,
        ("ulcerindex",),
        0,
        status="broken",
        note="BROKEN in openalgo 2.0.3: returns all-NaN. highest() emits a NaN warm-up prefix "
        "which the cumsum-based sma() then propagates over the whole array. signal_type is "
        "not validated by the library.",
        conditional_outputs={"return_signal=True": ("ulcer", "signal")},
    ),
    _spec(
        "starc",
        "volatility",
        _HLC,
        ("upper_band", "middle_line", "lower_band"),
        14,
        note="Per-band warm-up is 14/4/14.",
    ),
    # ---- volume (17) -------------------------------------------------------
    _spec("obv", "volume", _CV, ("obv",), 0),
    _spec(
        "obv_smoothed",
        "volume",
        _CV,
        ("obv_smoothed",),
        0,
        note="Returns a single series unless ma_type='SMA + Bollinger Bands', which yields a "
        "3-tuple. ma_type is validated; an unknown value raises ValueError.",
        conditional_outputs={
            "ma_type=SMA + Bollinger Bands": ("obv_smoothed", "bb_upper", "bb_lower")
        },
    ),
    _spec(
        "vwap",
        "volume",
        _HLCV,
        ("vwap",),
        0,
        note="Accepts six band-multiplier arguments but still returns a SINGLE series; the bands "
        "need ta._vwap.calculate_with_bands(). anchor and source are not validated.",
    ),
    _spec("mfi", "volume", _HLCV, ("mfi",), 13),
    _spec("adl", "volume", _HLCV, ("adl",), 0),
    _spec("cmf", "volume", _HLCV, ("cmf",), 19),
    _spec(
        "emv",
        "volume",
        ("high", "low", "volume"),
        ("emv",),
        14,
        note="TRAP: takes high, low and volume, with NO close.",
    ),
    _spec("force_index", "volume", _CV, ("force_index",), 1),
    _spec("nvi", "volume", _CV, ("nvi",), 0),
    _spec(
        "nvi_with_ema",
        "volume",
        _CV,
        ("nvi", "nvi_ema"),
        0,
        note="Same NVI class as ta.nvi; ema_length=255 means the EMA line needs a long history.",
    ),
    _spec("pvi", "volume", _CV, ("pvi",), 0),
    _spec(
        "pvi_with_signal",
        "volume",
        _CV,
        ("pvi", "signal"),
        0,
        note="signal_type is validated: EMA or SMA. signal_length=255 needs a long history for "
        "the signal line to be meaningful, even though both outputs are finite from bar 0.",
    ),
    _spec("volosc", "volume", _V, ("volosc",), 0, note="TRAP: volume is its only series argument."),
    _spec("vroc", "volume", _V, ("vroc",), 25, note="TRAP: volume is its only series argument."),
    _spec("kvo", "volume", _HLCV, ("kvo", "trigger"), 0),
    _spec("pvt", "volume", _CV, ("pvt",), 0),
    _spec(
        "rvol",
        "volume",
        _V,
        ("rvol",),
        19,
        note="TRAP: volume is its only series argument. Relative volume, not realized vol.",
    ),
    # ---- oscillators (19) --------------------------------------------------
    _spec("cmo", "oscillators", _C, ("cmo",), 14),
    _spec("trix", "oscillators", _C, ("trix",), 1),
    _spec(
        "uo_oscillator",
        "oscillators",
        _HLC,
        ("uo_oscillator",),
        27,
        status="alias",
        alias_of="ultimate_oscillator",
        note="oscillators.UO and volatility.ULTOSC are different classes with identical "
        "signatures and numerically identical output. Use ta.ultimate_oscillator instead.",
    ),
    _spec("awesome_oscillator", "oscillators", _HL, ("awesome_oscillator",), 33),
    _spec("accelerator_oscillator", "oscillators", _HL, ("accelerator_oscillator",), 37),
    _spec("ppo", "oscillators", _C, ("ppo_line", "signal_line", "histogram"), 0),
    _spec("po", "oscillators", _C, ("po",), 19, note="ma_type is validated: SMA or EMA only."),
    _spec("dpo", "oscillators", _C, ("dpo",), 31),
    _spec("aroon_oscillator", "oscillators", _HL, ("aroon_oscillator",), 14),
    _spec(
        "stochrsi",
        "oscillators",
        _C,
        ("k_percent", "d_percent"),
        14,
        note="The library calls these %K and %D; renamed here to stay identifier-safe.",
    ),
    _spec(
        "rvi",
        "oscillators",
        _OHLC,
        ("rvi", "signal"),
        15,
        note="TRAP: this is the Relative VIGOR Index and needs full OHLC. The volatility doc's "
        "ta.rvi(df['close']) raises TypeError. The Relative Volatility Index is imported as "
        "VolatilityRVI and never exposed on ta.",
    ),
    _spec(
        "cho",
        "oscillators",
        _HLCV,
        ("cho",),
        0,
        note="Chaikin oscillator, distinct from ta.chaikin (Chaikin volatility).",
    ),
    _spec("chop", "oscillators", _HLC, ("chop",), 13),
    _spec("kst", "oscillators", _C, ("kst", "signal_line"), 52),
    _spec("tsi", "oscillators", _C, ("tsi", "signal_line"), 0),
    _spec(
        "vi",
        "oscillators",
        _HLC,
        ("vi_plus", "vi_minus"),
        0,
        status="broken",
        note="BROKEN in openalgo 2.0.3: returns (all-NaN, all-NaN). _backend.vi seeds vmp/vmm "
        "with NaN at index 0 and rolling_sum is cumsum-based, so the NaN poisons everything.",
    ),
    _spec("stc", "oscillators", _C, ("stc",), 0),
    _spec("gator_oscillator", "oscillators", _HL, ("upper_histogram", "lower_histogram"), 20),
    _spec("coppock", "oscillators", _C, ("coppock",), 14),
    # ---- statistical (9) ---------------------------------------------------
    _spec("linreg", "statistical", _C, ("linreg",), 13),
    _spec(
        "lrslope",
        "statistical",
        _C,
        ("lrslope",),
        100,
        note="period=100 by default, so it needs about 101 bars before the first value.",
    ),
    _spec(
        "correlation",
        "statistical",
        _C,
        ("correlation",),
        19,
        series_args=("data1", "data2"),
        needs_second_series=True,
        note="Takes TWO independent price series (rolling Pearson correlation). Cannot be driven "
        "from one OHLCV frame: the caller must fetch and align a second symbol.",
    ),
    _spec(
        "beta",
        "statistical",
        _C,
        ("beta",),
        252,
        series_args=("asset", "market"),
        needs_second_series=True,
        note="Takes TWO independent price series (asset against benchmark). period=252 means it "
        "needs about 253 bars; fewer than period bars raises ValueError.",
    ),
    _spec(
        "variance",
        "statistical",
        _C,
        ("variance",),
        19,
        note="mode is validated: PR or LR. Returns a 5-tuple when return_components=True.",
        conditional_outputs={
            "return_components=True": (
                "variance",
                "ema_variance",
                "zscore",
                "ema_zscore",
                "stdev",
            ),
        },
    ),
    _spec("tsf", "statistical", _C, ("tsf",), 13),
    _spec("median", "statistical", _C, ("median",), 2),
    _spec(
        "median_bands",
        "statistical",
        _HLC,
        ("median", "upper_band", "lower_band", "median_ema"),
        13,
        series_args=("high", "low", "close", "source"),
        note="Works on this build despite services/indicator_service.py listing it unsupported. "
        "source is an optional 4th positional override series (default hl2), so pass the "
        "tuning arguments by keyword or an int binds silently to source.",
    ),
    _spec("mode", "statistical", _C, ("mode",), 19),
    # ---- hybrid (7) --------------------------------------------------------
    _spec(
        "adx",
        "hybrid",
        _HLC,
        ("plus_di", "minus_di", "adx"),
        26,
        note="TRAP: ADX is the THIRD element, not the first. Per-line warm-up is 13/13/26.",
    ),
    _spec(
        "aroon",
        "hybrid",
        _HL,
        ("aroon_up", "aroon_down"),
        25,
        note="TRAP: default period is 25, not the 14 the hybrid doc claims.",
    ),
    _spec(
        "pivot_points",
        "hybrid",
        _HLC,
        ("pivot", "r1", "s1", "r2", "s2", "r3", "s3"),
        0,
        note="Seven outputs; the order interleaves resistance and support.",
    ),
    _spec(
        "psar",
        "hybrid",
        _HL,
        ("psar",),
        0,
        note="TRAP: returns a SINGLE series, not the (sar, direction) tuple the hybrid doc "
        "shows. Takes high and low only.",
    ),
    _spec(
        "dmi",
        "hybrid",
        _HLC,
        ("plus_di", "minus_di"),
        13,
        note="Directional indicators only; use ta.adx for the ADX line.",
    ),
    _spec(
        "fractals",
        "hybrid",
        _HL,
        ("fractal_up", "fractal_down"),
        0,
        note="Williams fractals. Both outputs are BOOLEAN flags on this build, not the "
        "float 0.0/1.0 the docs suggest, so their summary reports how many bars fired "
        "rather than a minimum and a maximum.",
    ),
    _spec("rwi", "hybrid", _HLC, ("rwi_high", "rwi_low"), 14),
    # ---- talib_extra (18) --------------------------------------------------
    _spec("mom", "talib_extra", _C, ("mom",), 10),
    _spec(
        "rocp",
        "talib_extra",
        _C,
        ("rocp",),
        10,
        note="Rate of change as a fraction. Distinct from the ta.roc utility, which returns an "
        "ndarray.",
    ),
    _spec("rocr", "talib_extra", _C, ("rocr",), 10),
    _spec("rocr100", "talib_extra", _C, ("rocr100",), 10),
    _spec("midpoint", "talib_extra", _C, ("midpoint",), 13),
    _spec(
        "apo",
        "talib_extra",
        _C,
        ("apo",),
        25,
        note="ma_type is documented as SMA or EMA but is NOT validated: junk is accepted silently.",
    ),
    _spec("medprice", "talib_extra", _HL, ("medprice",), 0),
    _spec("typprice", "talib_extra", _HLC, ("typprice",), 0),
    _spec("wclprice", "talib_extra", _HLC, ("wclprice",), 0),
    _spec("midprice", "talib_extra", _HL, ("midprice",), 13),
    _spec(
        "avgprice",
        "talib_extra",
        _OHLC,
        ("avgprice",),
        0,
        note="Takes full OHLC; the open series parameter is named open_prices.",
    ),
    _spec("plus_dm", "talib_extra", _HL, ("plus_dm",), 13),
    _spec("minus_dm", "talib_extra", _HL, ("minus_dm",), 13),
    _spec("dx", "talib_extra", _HLC, ("dx",), 14),
    _spec("adxr", "talib_extra", _HLC, ("adxr",), 40),
    _spec("stochf", "talib_extra", _HLC, ("fastk", "fastd"), 6),
    _spec("linregangle", "talib_extra", _C, ("linregangle",), 13),
    _spec("linregintercept", "talib_extra", _C, ("linregintercept",), 13),
    # ---- utility (13) ------------------------------------------------------
    _spec(
        "crossover",
        "utility",
        (),
        ("crossover",),
        0,
        series_args=("series1", "series2"),
        note=_UTILITY_PAIR + " True on the bar where series1 crosses ABOVE series2.",
    ),
    _spec(
        "crossunder",
        "utility",
        (),
        ("crossunder",),
        0,
        series_args=("series1", "series2"),
        note=_UTILITY_PAIR + " True on the bar where series1 crosses BELOW series2.",
    ),
    _spec(
        "cross",
        "utility",
        (),
        ("cross",),
        0,
        series_args=("series1", "series2"),
        note=_UTILITY_PAIR + " True on a cross in either direction.",
    ),
    _spec(
        "highest",
        "utility",
        _C,
        ("highest",),
        13,
        series_args=("data",),
        note=_UTILITY_ON_CLOSE + "Use donchian for the high-low channel. period is "
        "required (no default); warm-up is period-1.",
    ),
    _spec(
        "lowest",
        "utility",
        _C,
        ("lowest",),
        13,
        series_args=("data",),
        note=_UTILITY_ON_CLOSE + "Use donchian for the high-low channel. period is "
        "required (no default); warm-up is period-1.",
    ),
    _spec(
        "change",
        "utility",
        _C,
        ("change",),
        1,
        series_args=("data",),
        note=_UTILITY_ON_CLOSE + "close[i] - close[i-length]. Use mom for the "
        "Series-returning form.",
    ),
    _spec(
        "roc",
        "utility",
        _C,
        ("roc",),
        14,
        series_args=("data",),
        note=_UTILITY_ON_CLOSE + "This is the UTILITY roc: length is required, the result "
        "is an ndarray "
        "and the warm-up is length (not length-1). The Series-returning rate-of-change family "
        "is mom/rocp/rocr/rocr100.",
    ),
    _spec(
        "stdev",
        "utility",
        _C,
        ("stdev",),
        13,
        series_args=("data",),
        note=_UTILITY_ON_CLOSE + "Use bbwidth for a normalised spread. period is "
        "required (no default); warm-up is period-1.",
    ),
    _spec(
        "exrem",
        "utility",
        (),
        ("exrem",),
        0,
        series_args=("primary", "secondary"),
        note=_UTILITY_PAIR + " Removes repeated primary signals until a secondary signal fires.",
    ),
    _spec(
        "flip",
        "utility",
        (),
        ("flip",),
        0,
        series_args=("primary", "secondary"),
        note=_UTILITY_PAIR + " Latching toggle: on at primary, off at secondary.",
    ),
    _spec(
        "valuewhen",
        "utility",
        (),
        ("valuewhen",),
        0,
        series_args=("expr", "array"),
        note=_UTILITY_PAIR + " Value of array at the nth most recent bar where expr "
        "was true. Warm-up "
        "is data dependent, not fixed: NaN until expr has fired n times.",
    ),
    _spec(
        "rising",
        "utility",
        _C,
        ("rising",),
        0,
        series_args=("data",),
        note=_UTILITY_ON_CLOSE + "Returns BOOLEAN flags. Use lrslope for a gradient. "
        "length is required (no default).",
    ),
    _spec(
        "falling",
        "utility",
        _C,
        ("falling",),
        0,
        series_args=("data",),
        note=_UTILITY_ON_CLOSE + "Returns BOOLEAN flags. Use lrslope for a gradient. "
        "length is required (no default).",
    ),
)

#: Every registered indicator, keyed by its exact ``ta`` method name.
REGISTRY: dict[str, IndicatorSpec] = {spec.name: spec for spec in _SPECS}

#: How many indicators each category holds, for the discovery tool's summary.
CATEGORY_COUNTS: dict[str, int] = {
    category: sum(1 for spec in REGISTRY.values() if spec.category == category)
    for category in CATEGORIES
}


# ---------------------------------------------------------------------------
# Drift detection and lookup
# ---------------------------------------------------------------------------


def ta_callables() -> list[str]:
    """List the public method names on the ``ta`` singleton.

    Returns:
        Every attribute of ``ta`` not starting with an underscore. 127 on the
        pinned openalgo 2.0.3 build.
    """
    return [name for name in dir(ta) if not name.startswith("_")]


def validate_registry() -> list[str]:
    """Compare :data:`REGISTRY` against the installed ``ta`` singleton.

    Returns:
        Human-readable discrepancies. Empty means the table matches the SDK
        exactly. Any entry means the SDK drifted and the table needs an edit.
    """
    live = set(ta_callables())
    known = set(REGISTRY)
    problems: list[str] = []

    for name in sorted(live - known):
        problems.append(f"missing from REGISTRY: ta.{name}")
    for name in sorted(known - live):
        problems.append(f"extra in REGISTRY (not on ta): {name}")
    if len(_SPECS) != len(REGISTRY):
        problems.append(
            f"duplicate spec names: {len(_SPECS)} specs collapsed to {len(REGISTRY)} keys"
        )
    for name, spec in REGISTRY.items():
        if spec.status == "alias" and spec.alias_of not in REGISTRY:
            problems.append(f"{name}: alias_of={spec.alias_of!r} is not a registered indicator")
    return problems


def get_spec(name: str) -> IndicatorSpec | None:
    """Look up one indicator by its exact ``ta`` method name.

    Args:
        name: The method name, already lower-cased and stripped.

    Returns:
        The spec, or None when nothing is registered under that name.
    """
    return REGISTRY.get(name)


# Startup assertion. An SDK upgrade that adds or removes an indicator fails
# here, loudly, instead of silently shipping a stale catalogue. The agent's
# toolkit registry catches a toolkit import failure and skips that toolkit, so
# the cost of this raise is the indicator tools and a traceback in
# log/errors.jsonl, never the platform.
_DRIFT = validate_registry()
if _DRIFT:
    raise RuntimeError(
        "The agent indicator registry does not match the installed openalgo build: "
        + "; ".join(_DRIFT)
    )
