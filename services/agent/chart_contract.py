"""The chart wire contract, in both directions.

Inbound is :class:`ChartView`, what the `/trading` panel sends about the chart
the operator is looking at. Outbound is the command vocabulary the agent sends
back. Both live here so the panel, the toolkit and a test read one file, and so
neither half needs agno or a database to be checked.

Outbound: commands
------------------

Commands ride a :class:`~services.agent.frames.ChartCommand` frame, which
carries a list of dicts each keyed by ``op``. The terminal **ignores an op it
does not know** rather than throwing, so a newer backend cannot break an older
client mid-turn, and this module can grow an op without a lockstep release.

Three ops, and that is the whole vocabulary:

``{"op": "draw", "group": str, "shapes": [...]}``
    Replace the named agent group with these shapes. Replacing rather than
    appending is what makes a second call to the same tool redraw rather than
    stack, so an operator asking twice gets one set of levels.

``{"op": "clear", "group": str | null}``
    Remove one agent group, or every agent group when ``group`` is null.

Grouping is load-bearing
------------------------

Everything the agent draws goes into a named group from :data:`GROUPS`, and every
shape carries an id of ``ai:{group}:{index}``. That namespace is the entire
reason a clear is safe: the terminal removes drawings whose id starts with
``ai:``, and a drawing the operator placed by hand has an id the terminal
generated, which never starts with that prefix. **An agent that wipes an
operator's markup is worse than one that draws nothing**, so the prefix is
applied here, in the one place a shape is built, rather than by each caller.

Provenance
----------

A shape's anchors are ``{time, price}`` in UTC epoch seconds and real price
units, and every one of them comes from a candle the platform returned. The
model chooses which structure to draw; it never supplies a number. That is
enforced upstream, by the tools taking no price argument at all, and here by
:func:`safe_note`: the one string a caller may pass through from the model has
every digit removed, so a price cannot reach the canvas dressed as a caption.

Tone, not colour
----------------

A shape carries a semantic ``tone`` and the chart resolves it against the active
theme. A shape carrying its own hex would be stranded on the old palette the
moment the operator switched themes, and the backend has no business knowing
what bullish looks like.

Inbound: the context
--------------------

:class:`ChartView` is operator-supplied text that reaches the prompt on **every
turn**, so every field it models is bounded here: scalars are capped in length,
lists are capped in count, and anything the panel sends that this class does not
model is dropped rather than carried. The blueprint's ``_runtime_lines`` renders
the scalar half into prompt bullets on its own; the lists reach only the tools,
which is why the caps on them live here rather than there.

This module imports no agno and does no I/O, so the blueprint, a test and the
toolkit can all read the same vocabulary.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = [
    "AI_PREFIX",
    "GROUPS",
    "GROUP_LEVELS",
    "GROUP_PATTERNS",
    "GROUP_TRENDLINE",
    "GROUP_ZONE",
    "MAX_DRAWINGS",
    "MAX_DRAWING_POINTS",
    "MAX_INDICATORS",
    "MAX_NOTE_CHARS",
    "MAX_SHAPES",
    "TONES",
    "ChartView",
    "anchor",
    "clear",
    "draw",
    "drawing_id",
    "level",
    "marker",
    "safe_note",
    "trendline",
    "zone",
]

#: Marks a drawing as the agent's rather than the operator's. The terminal
#: splits an id on ":", so a group name must never contain one.
AI_PREFIX = "ai"

GROUP_LEVELS = "levels"
GROUP_TRENDLINE = "trendline"
GROUP_ZONE = "zone"
GROUP_PATTERNS = "patterns"

#: The closed set of groups the agent may draw into. A clear with no group
#: removes exactly these and nothing else.
GROUPS: tuple[str, ...] = (GROUP_LEVELS, GROUP_TRENDLINE, GROUP_ZONE, GROUP_PATTERNS)

#: Semantic tones. The chart resolves each against the active theme.
TONES: frozenset[str] = frozenset({"bullish", "bearish", "neutral"})

#: Most shapes one group may carry. A draw command crosses the wire on every
#: turn it happens in; a hundred markers is a mess on the canvas long before it
#: is a problem on the wire.
MAX_SHAPES = 24

#: Longest caption a caller may pass through from the model.
MAX_NOTE_CHARS = 48

#: What survives :func:`safe_note`. Letters, spaces and the punctuation a phrase
#: needs. **No digits**, which is the point: a caption is the only string that
#: reaches the canvas from the model, and a digit in it would be a price the
#: model chose rather than one the candles gave.
_NOTE_ALLOWED = re.compile(r"[^A-Za-z ,.:;()/'-]+")

_WHITESPACE = re.compile(r"\s+")


def safe_note(value: Any) -> str:
    """Reduce a model-supplied caption to something safe to draw.

    Every digit is removed, along with every character outside a small allowed
    set, and the result is capped. A caption is the only text a tool passes
    through from the model onto the canvas, and a number in it would be read by
    the operator as a level, so the number is what this takes away.

    Args:
        value: Whatever the model passed. Anything that is not a string reads as
            no caption at all.

    Returns:
        The cleaned caption, possibly empty. Empty is the correct answer for a
        caption that was nothing but digits.
    """
    if not isinstance(value, str):
        return ""
    text = _NOTE_ALLOWED.sub(" ", value)
    text = _WHITESPACE.sub(" ", text).strip(" ,.:;-")
    return text[:MAX_NOTE_CHARS].strip()


def _tone(value: Any) -> str:
    """Coerce a tone to one the chart knows.

    Args:
        value: The requested tone.

    Returns:
        The tone when it is one of :data:`TONES`, else ``neutral``.
    """
    text = str(value or "").strip().lower()
    return text if text in TONES else "neutral"


def _number(value: Any) -> float | None:
    """Coerce a price or a time to a finite float.

    Args:
        value: The raw value.

    Returns:
        The float, or None when it is missing or not finite. A shape built on a
        None is dropped rather than drawn at zero.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def anchor(time: Any, price: Any) -> dict[str, float] | None:
    """Build one anchor in data space.

    Args:
        time: UTC epoch seconds. May sit between bars or past the last one.
        price: Price on the pane's scale.

    Returns:
        ``{"time": ..., "price": ...}``, or None when either value is unusable.
    """
    moment, level_price = _number(time), _number(price)
    if moment is None or level_price is None:
        return None
    return {"time": float(moment), "price": round(float(level_price), 4)}


def _as_anchor(value: Any) -> dict[str, float] | None:
    """Accept an anchor mapping or an object exposing time and price.

    Args:
        value: A mapping with ``time`` and ``price``, or anything carrying those
            attributes, such as a :class:`services.agent.chart_geometry.Pivot`.

    Returns:
        A fresh anchor dict, or None when the value carries neither.
    """
    if isinstance(value, Mapping):
        return anchor(value.get("time"), value.get("price"))
    return anchor(getattr(value, "time", None), getattr(value, "price", None))


def drawing_id(group: str, index: int) -> str:
    """Build the namespaced id one shape is drawn under.

    Args:
        group: One of :data:`GROUPS`.
        index: Position of the shape within its group.

    Returns:
        ``ai:{group}:{index}``. The prefix is what lets a clear remove the
        agent's markup without touching a drawing the operator placed.
    """
    return f"{AI_PREFIX}:{group}:{int(index)}"


def level(
    price: Any, *, time: Any = None, label: str = "", tone: str = "neutral"
) -> dict[str, Any] | None:
    """A horizontal support or resistance line.

    Args:
        price: The level, from a candle the platform returned.
        time: Where the line starts, in UTC epoch seconds. None spans the whole
            pane; a value makes it a ray running right from that bar.
        label: Caption drawn with the line. Built by the tool from real numbers.
        tone: One of :data:`TONES`.

    Returns:
        The shape, or None when the price is unusable.
    """
    value = _number(price)
    if value is None:
        return None
    shape: dict[str, Any] = {
        "kind": "level",
        "price": round(float(value), 4),
        "tone": _tone(tone),
    }
    moment = _number(time)
    if moment is not None:
        shape["time"] = float(moment)
        shape["ray"] = True
    if label:
        shape["label"] = str(label)[:80]
    return shape


def trendline(
    start: Any,
    end: Any,
    *,
    extend_right: bool = True,
    label: str = "",
    tone: str = "neutral",
) -> dict[str, Any] | None:
    """A straight line between two anchors, optionally projected right.

    Args:
        start: The first anchor, a mapping or a pivot.
        end: The second anchor.
        extend_right: Project the line past its last anchor.
        label: Caption drawn with the line.
        tone: One of :data:`TONES`.

    Returns:
        The shape, or None when either anchor is unusable.
    """
    first, last = _as_anchor(start), _as_anchor(end)
    if first is None or last is None:
        return None
    shape: dict[str, Any] = {
        "kind": "trendline",
        "from": first,
        "to": last,
        "extend_right": bool(extend_right),
        "tone": _tone(tone),
    }
    if label:
        shape["label"] = str(label)[:80]
    return shape


def zone(start: Any, end: Any, *, label: str = "", tone: str = "neutral") -> dict[str, Any] | None:
    """A filled rectangle, for a demand or supply area.

    Args:
        start: One corner, a mapping or a pivot.
        end: The opposite corner.
        label: Caption drawn with the band.
        tone: One of :data:`TONES`.

    Returns:
        The shape, or None when either corner is unusable.
    """
    first, last = _as_anchor(start), _as_anchor(end)
    if first is None or last is None:
        return None
    shape: dict[str, Any] = {
        "kind": "zone",
        "from": first,
        "to": last,
        "tone": _tone(tone),
    }
    if label:
        shape["label"] = str(label)[:80]
    return shape


def marker(at: Any, text: str, *, tone: str = "neutral") -> dict[str, Any] | None:
    """A labelled dot on one bar, for naming a pattern where it printed.

    Args:
        at: The anchor, a mapping or a pivot.
        text: The label. Built by the tool from what it detected.
        tone: One of :data:`TONES`.

    Returns:
        The shape, or None when the anchor is unusable.
    """
    point = _as_anchor(at)
    if point is None:
        return None
    return {
        "kind": "marker",
        "at": point,
        "text": str(text or "")[:80],
        "tone": _tone(tone),
    }


def draw(group: str, shapes: Sequence[Any]) -> dict[str, Any]:
    """Build a draw command, replacing one group and leaving every other alone.

    Shapes are ids'd here rather than by the caller, so the ``ai:`` namespace
    cannot be forgotten in one path and applied in another.

    Args:
        group: One of :data:`GROUPS`.
        shapes: Shapes from the builders above. A None entry, which is what a
            builder returns for an unusable anchor, is dropped.

    Returns:
        ``{"op": "draw", "group": ..., "shapes": [...]}``, capped at
        :data:`MAX_SHAPES` shapes.

    Raises:
        ValueError: When the group is not one of :data:`GROUPS`. That is a
            programming error, and a shape drawn into an unknown group could
            never be cleared.
    """
    name = str(group or "").strip().lower()
    if name not in GROUPS:
        raise ValueError(f"Unknown chart group {group!r}. Valid groups: {', '.join(GROUPS)}")

    kept: list[dict[str, Any]] = []
    for shape in shapes:
        if not isinstance(shape, Mapping):
            continue
        entry = dict(shape)
        entry["id"] = drawing_id(name, len(kept))
        kept.append(entry)
        if len(kept) >= MAX_SHAPES:
            break

    return {"op": "draw", "group": name, "shapes": kept}


def clear(group: str | None = None) -> dict[str, Any]:
    """Build a clear command.

    Args:
        group: The group to remove, or None for every agent group. Never touches
            a drawing the operator placed by hand.

    Returns:
        ``{"op": "clear", "group": ...}``. The group is null when every agent
        group is to go, which is the shape the terminal reads as "all of mine".

    Raises:
        ValueError: When a named group is not one of :data:`GROUPS`.
    """
    if group is None:
        return {"op": "clear", "group": None}
    name = str(group).strip().lower()
    if name not in GROUPS:
        raise ValueError(f"Unknown chart group {group!r}. Valid groups: {', '.join(GROUPS)}")
    return {"op": "clear", "group": name}


# ---------------------------------------------------------------------------
# Inbound: the chart the operator is looking at
# ---------------------------------------------------------------------------

#: Most indicators one context may report. A chart with more than a dozen
#: overlays is not a chart the model needs the full list of.
MAX_INDICATORS = 12

#: Most operator drawings one context may report.
MAX_DRAWINGS = 24

#: Anchors kept per operator drawing. Two covers a line, a ray and a rectangle;
#: four covers a channel and a fib. A freehand path with three hundred vertices
#: is a shape, not a level, and its first anchors are enough to place it.
MAX_DRAWING_POINTS = 4


def _text(value: Any, limit: int, *, upper: bool = False) -> str:
    """Bound one scalar field of the inbound context.

    Args:
        value: The raw field.
        limit: Characters kept.
        upper: Upper-case the result, for a symbol or an exchange.

    Returns:
        A single-line string of at most ``limit`` characters. Control characters
        and line breaks are folded to spaces, because this text is about to be
        rendered as prompt bullets and a value carrying its own line breaks can
        otherwise fake the structure around it.
    """
    if not isinstance(value, str):
        value = "" if value is None else str(value)
    cleaned = _WHITESPACE.sub(" ", "".join(ch if ch.isprintable() else " " for ch in value))
    cleaned = cleaned.strip()[:limit]
    return cleaned.upper() if upper else cleaned


def _count(value: Any) -> int:
    """Coerce a count field to a non-negative integer.

    Args:
        value: The raw field.

    Returns:
        The count, or 0 when it is missing or unusable.
    """
    number = _number(value)
    return max(int(number), 0) if number is not None else 0


@dataclass(frozen=True, slots=True)
class ChartView:
    """What the panel reports about the chart, read fresh on every message.

    Every field is bounded, because this is operator-supplied content reaching
    the prompt on every turn. :meth:`from_payload` is the only way to build one
    from the wire, and it is where every cap is applied.

    Attributes:
        symbol: OpenAlgo symbol on the chart, in capitals.
        exchange: Its exchange code.
        interval: Candle size, in OpenAlgo's own vocabulary.
        chart_type: How the bars are drawn, for example ``candlestick``.
        bars_loaded: Bars the chart has fetched.
        visible_bars: Bars inside the viewport.
        visible_from: Left edge of the viewport in UTC epoch seconds.
        visible_to: Right edge in UTC epoch seconds.
        last_price: The chart's live last price, when it has one.
        indicators: Overlays on the chart, each ``{"id", "name"}`` where ``id``
            is the descriptor the chart registry knows, so an indicator tool can
            name it.
        drawings: The operator's own drawings, each ``{"tool", "points", "text"}``
            with anchors in ``{time, price}``. Agent drawings are excluded by the
            panel, which knows them by their ``ai:`` id prefix.
        agent_groups: Agent groups still on the chart. The operator can clear the
            agent's markup from the toolbar without any tool being called, so the
            backend's own idea of what it drew is not the truth about what is on
            screen.
    """

    symbol: str = ""
    exchange: str = ""
    interval: str = ""
    chart_type: str = ""
    bars_loaded: int = 0
    visible_bars: int = 0
    visible_from: float | None = None
    visible_to: float | None = None
    last_price: float | None = None
    indicators: tuple[dict[str, str], ...] = ()
    drawings: tuple[dict[str, Any], ...] = ()
    agent_groups: tuple[str, ...] = ()

    @property
    def is_open(self) -> bool:
        """Report whether the context names an instrument at all.

        Returns:
            True when a symbol, an exchange and an interval are all present,
            which is the minimum a tool needs to fetch the right candles.
        """
        return bool(self.symbol and self.exchange and self.interval)

    @classmethod
    def from_payload(cls, payload: Any) -> ChartView:
        """Build a bounded view from whatever the panel sent.

        Args:
            payload: The ``chart_context`` object from the request body, which
                may be anything at all.

        Returns:
            The view. An unusable payload yields an empty one, whose
            :attr:`is_open` is false, and every tool answers that plainly rather
            than guessing a symbol.
        """
        if not isinstance(payload, Mapping):
            return cls()

        indicators: list[dict[str, str]] = []
        for item in payload.get("indicators") or ():
            if not isinstance(item, Mapping):
                continue
            name = _text(item.get("name"), 48)
            if not name:
                continue
            # ``indicatorId`` is the descriptor the chart registry knows, which
            # is the only id an indicator tool can act on. ``id`` is the
            # instance, ``ema-1``, unique so three EMAs can coexist and useless
            # to name one by. Older panels send only ``id``, so it is the
            # fallback rather than the preference.
            marker = item.get("indicatorId") or item.get("id")
            indicators.append({"id": _text(marker, 48), "name": name})
            if len(indicators) >= MAX_INDICATORS:
                break

        drawings: list[dict[str, Any]] = []
        for item in payload.get("drawings") or ():
            if not isinstance(item, Mapping):
                continue
            points: list[dict[str, float]] = []
            for raw in item.get("points") or ():
                point = _as_anchor(raw)
                if point is not None:
                    points.append(point)
                if len(points) >= MAX_DRAWING_POINTS:
                    break
            entry: dict[str, Any] = {"tool": _text(item.get("tool"), 32), "points": points}
            note = _text(item.get("text"), 80)
            if note:
                entry["text"] = note
            drawings.append(entry)
            if len(drawings) >= MAX_DRAWINGS:
                break

        groups = tuple(
            name
            for name in dict.fromkeys(
                _text(value, 16).lower() for value in payload.get("agent_groups") or ()
            )
            if name in GROUPS
        )

        return cls(
            symbol=_text(payload.get("symbol"), 64, upper=True),
            exchange=_text(payload.get("exchange"), 16, upper=True),
            interval=_text(payload.get("interval"), 16),
            chart_type=_text(payload.get("chart_type"), 24),
            bars_loaded=_count(payload.get("bars_loaded")),
            visible_bars=_count(payload.get("visible_bars")),
            visible_from=_number(payload.get("visible_from")),
            visible_to=_number(payload.get("visible_to")),
            last_price=_number(payload.get("last_price")),
            indicators=tuple(indicators),
            drawings=tuple(drawings),
            agent_groups=groups,
        )
