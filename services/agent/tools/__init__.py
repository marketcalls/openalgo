"""Agent tool registry.

This package holds every toolkit the agent can be given. The registry is the
only thing that decides which of them a particular run actually sees.

Adding a capability
-------------------

Adding a capability is **one new file plus one registry line**:

1. Write ``services/agent/tools/<name>.py`` holding a subclass of
   ``services.agent.tools.base.OpenAlgoToolkit``.
2. Add one ``ToolkitSpec(...)`` entry to :data:`TOOLKITS` below naming the
   module, the class, the surfaces it belongs to, and any run capability it
   requires (:data:`CAPABILITIES`).

Nothing else changes. ``builder.py`` passes :func:`build_toolkits` to agno as a
callable factory, so the list is re-evaluated on every run against the current
session state: a session that has not enabled trading never sees the order
tools in its schema at all, and the chart surface never sees them either.

Import safety
-------------

This module must stay importable when ``agno`` is not installed, so the rest of
OpenAlgo and the whole test suite can import it without pulling in the agent's
optional dependency. That is why:

* ``agno`` is imported **inside** :func:`build_toolkits`, never at module level;
* :data:`TOOLKITS` holds module and attribute *names*, not imported classes, so
  a registry entry costs nothing until a toolkit is actually built;
* :class:`ToolContext` lives here rather than in ``base.py`` (which does need
  agno), so a context can be constructed and the registry filtered with no
  optional dependency present at all.

Selection rules
---------------

A spec is selected when its surface list contains the context's surface and
every capability it names in ``requires`` is true on the context. Selection
never inspects anything the model can influence.

A capability is a boolean on :class:`ToolContext` that the surface decides per
run: ``trading_enabled`` and ``web_search_enabled`` today. Withholding the
toolkit is the whole enforcement -- a tool that is not built has no schema, so
the model cannot call it, cannot be talked into calling it, and does not pay for
its description. There is deliberately **one** mechanism for this rather than a
branch per switch, so the next capability is a constant and a spec field and
carries no new way to get the check wrong.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING, Any

from utils.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from agno.tools import Toolkit

logger = get_logger(__name__)

SURFACE_CHAT = "chat"
SURFACE_CHART = "chart"

#: Every surface the agent runs on. A toolkit that names all of them is offered
#: to both the conversation page and the chart panel.
ALL_SURFACES: frozenset[str] = frozenset({SURFACE_CHAT, SURFACE_CHART})

CHAT_ONLY: frozenset[str] = frozenset({SURFACE_CHAT})
CHART_ONLY: frozenset[str] = frozenset({SURFACE_CHART})

#: A run capability a toolkit may require. Each names a boolean attribute of
#: :class:`ToolContext` that the surface sets per run.
CAPABILITY_TRADING = "trading_enabled"
CAPABILITY_WEB_SEARCH = "web_search_enabled"

#: Every capability a spec may name. Validated on the spec so a typo is a build
#: error rather than a gate that is silently always open.
CAPABILITIES: frozenset[str] = frozenset({CAPABILITY_TRADING, CAPABILITY_WEB_SEARCH})

__all__ = [
    "ALL_SURFACES",
    "CAPABILITIES",
    "CAPABILITY_TRADING",
    "CAPABILITY_WEB_SEARCH",
    "CHART_ONLY",
    "CHAT_ONLY",
    "SURFACE_CHART",
    "SURFACE_CHAT",
    "TOOLKITS",
    "ToolContext",
    "ToolkitSpec",
    "add_spec",
    "agno_available",
    "build_toolkits",
    "context_value",
    "register",
    "registered_specs",
    "select_specs",
]


def _normalise_surface(value: Any) -> str:
    """Normalise a surface name to its canonical lower-case form.

    Args:
        value: Raw surface value from a context or a spec.

    Returns:
        The lower-case, whitespace-stripped surface name. An empty or
        unusable value becomes :data:`SURFACE_CHAT`.
    """
    if not isinstance(value, str):
        return SURFACE_CHAT
    cleaned = value.strip().lower()
    return cleaned or SURFACE_CHAT


@dataclass
class ToolContext:
    """Everything a toolkit needs to know about the run it is serving.

    One instance is built per agent run, before any tool is constructed. It
    carries no agno type and no database handle, so it can be created in a test
    or in a blueprint without the optional agent dependencies being installed.

    Attributes:
        api_key: The OpenAlgo API key the internal service layer resolves the
            user, broker and auth token from. Required.
        conversation_id: Primary key of the ``ag_conversation`` row this run
            belongs to, used to tie audit rows to a conversation.
        surface: ``chat`` or ``chart``. Decides which toolkits are offered.
        run_id: Agno run id for the current turn, when one is known.
        session_id: Agno session id for the current turn, when one is known.
        user_id: OpenAlgo user the run belongs to.
        trading_enabled: True when the operator has enabled trading for this
            session. Toolkits requiring :data:`CAPABILITY_TRADING` are withheld
            when it is false, so the model cannot see an order tool it may not
            use.
        web_search_enabled: True when this turn may reach the public web.
            Toolkits requiring :data:`CAPABILITY_WEB_SEARCH` are withheld when
            it is false, which is what the composer's Web search switch means:
            not "prefer not to search" but "the search tools are not in the
            request at all". Absent means on, so a surface that has no switch
            keeps the behaviour it had.
        analyzer_mode: True when the platform analyzer toggle is on. Carried for
            the risk guard and for prompt wording; it never selects toolkits.
        session_state: The agno session state mapping this context was derived
            from. Kept so a tool can read a value the context does not model.
        extras: Free-form extras for a surface that needs more, such as the
            chart panel's current symbol and interval.
    """

    api_key: str
    conversation_id: int | str | None = None
    surface: str = SURFACE_CHAT
    run_id: str | None = None
    session_id: str | None = None
    user_id: str | None = None
    trading_enabled: bool = False
    web_search_enabled: bool = True
    analyzer_mode: bool = False
    session_state: dict[str, Any] = field(default_factory=dict)
    extras: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalise the surface and reject a context with no API key."""
        if not self.api_key or not isinstance(self.api_key, str):
            raise ValueError("ToolContext requires a non-empty OpenAlgo api_key")
        self.surface = _normalise_surface(self.surface)
        self.trading_enabled = bool(self.trading_enabled)
        self.web_search_enabled = bool(self.web_search_enabled)
        self.analyzer_mode = bool(self.analyzer_mode)

    @classmethod
    def from_session_state(cls, session_state: Mapping[str, Any], **overrides: Any) -> ToolContext:
        """Build a context from an agno session-state mapping.

        ``builder.py`` hands the toolkit factory a run context whose session
        state carries the values below. Keys the context does not model are
        ignored but kept in :attr:`session_state`, so a later toolkit can read
        one without this class changing.

        Args:
            session_state: Mapping of session values. Recognised keys are the
                field names of this class.
            **overrides: Values that win over the mapping, used by callers that
                already know the run id or surface for the current turn.

        Returns:
            A populated :class:`ToolContext`.

        Raises:
            ValueError: If neither the mapping nor the overrides carry an
                ``api_key``.
        """
        known = {f.name for f in fields(cls)} - {"session_state", "extras"}
        values: dict[str, Any] = {
            name: session_state[name] for name in known if name in session_state
        }
        values.update({name: value for name, value in overrides.items() if name in known})
        extras = overrides.get("extras")
        return cls(
            session_state=dict(session_state),
            extras=dict(extras) if isinstance(extras, Mapping) else {},
            **values,
        )


def context_value(context: Any, *keys: str) -> Any:
    """Read the first of these keys a run's context carries, wherever it is.

    A surface hands a run its per-request objects through ``ToolContext.extras``:
    the rendering sink, the operator's own message for the turn, the chart panel's
    view of its chart. ``builder.tool_factory`` rebuilds the context from agno's
    session state on every run and copies ``extras`` across shallowly, which is
    what keeps those objects shared rather than duplicated, but it also means a
    value can be reached through either mapping depending on who built the
    context. Every reader therefore has to look in both, and this is that reader,
    once, rather than once per consumer.

    Args:
        context: The run's :class:`ToolContext`, or anything shaped like it.
        *keys: Keys to try, in order of preference.

    Returns:
        The first value found under any key, or None when the surface supplied
        none, which each caller treats as "this surface does not offer that"
        rather than as an error.
    """
    for source_name in ("extras", "session_state"):
        source = getattr(context, source_name, None)
        if not isinstance(source, Mapping):
            continue
        for key in keys:
            value = source.get(key)
            if value is not None:
                return value
    return None


@dataclass
class ToolkitSpec:
    """One registry entry: a toolkit class named by module and attribute.

    The class is not imported until a run actually selects it, which is what
    keeps this package importable without agno and keeps a broken toolkit from
    taking the whole agent down at import time.

    Attributes:
        key: Stable identifier, unique across the registry. Also the dedupe key.
        module: Fully qualified module holding the toolkit class.
        attr: Class name inside that module.
        surfaces: Surfaces the toolkit is offered on.
        requires: Capabilities from :data:`CAPABILITIES` that must all be true
            on the run's context for this toolkit to be built. Empty means the
            toolkit is always offered on its surfaces.
        order: Sort weight. Lower is offered first; ties break on ``key``.
        description: One line for logs and for the settings UI.
        cls: Resolved class, filled in by :meth:`resolve` or supplied up front
            by :func:`register`.
    """

    key: str
    module: str
    attr: str
    surfaces: frozenset[str] = ALL_SURFACES
    requires: frozenset[str] = frozenset()
    order: int = 100
    description: str = ""
    cls: type | None = None

    def __post_init__(self) -> None:
        """Normalise the surfaces and reject a capability that does not exist.

        A misspelt capability would name an attribute no context carries, and
        ``matches`` reads capabilities with a False default, so the toolkit
        would silently never be offered. Failing here instead makes that a
        startup error with the offending name in it.

        Raises:
            ValueError: The spec names no surface, or names a capability that
                is not in :data:`CAPABILITIES`.
        """
        self.surfaces = frozenset(_normalise_surface(s) for s in self.surfaces)
        if not self.surfaces:
            raise ValueError(f"Toolkit spec {self.key!r} names no surface")
        self.requires = frozenset(self.requires)
        unknown = sorted(self.requires - CAPABILITIES)
        if unknown:
            raise ValueError(
                f"Toolkit spec {self.key!r} requires unknown capabilities: {', '.join(unknown)}"
            )

    def resolve(self) -> type:
        """Import the module and return the toolkit class, caching the result.

        Returns:
            The toolkit class named by :attr:`module` and :attr:`attr`.

        Raises:
            ImportError: If the module cannot be imported, which includes agno
                being absent because ``base.py`` requires it.
            AttributeError: If the module has no such attribute.
            TypeError: If the attribute is not a class.
        """
        if self.cls is not None:
            return self.cls
        module = importlib.import_module(self.module)
        obj = getattr(module, self.attr)
        if not isinstance(obj, type):
            raise TypeError(f"{self.module}.{self.attr} is not a class")
        self.cls = obj
        return obj

    def matches(self, context: Any) -> bool:
        """Report whether this toolkit should be offered to a run.

        Capabilities are read with ``getattr(context, name, False)`` so a
        duck-typed context from a test is accepted, and a context missing one is
        treated as not permitted rather than permitted. That default is the
        fail-closed direction for every capability: an order toolkit and a web
        search toolkit are both worse to hand out by accident than to withhold.

        Args:
            context: The run's :class:`ToolContext`, or anything shaped like it.

        Returns:
            True when the surface matches and every required capability is on.
        """
        surface = _normalise_surface(getattr(context, "surface", SURFACE_CHAT))
        if surface not in self.surfaces:
            return False
        return all(bool(getattr(context, name, False)) for name in self.requires)


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

#: One entry per toolkit file. This is the single line an author adds when they
#: add a capability. Example, for ``services/agent/tools/market.py`` holding
#: ``class MarketToolkit(OpenAlgoToolkit)``::
#:
#:     ToolkitSpec(
#:         key="market",
#:         module="services.agent.tools.market",
#:         attr="MarketToolkit",
#:         surfaces=ALL_SURFACES,
#:         order=10,
#:         description="Quotes, depth, history and intervals.",
#:     ),
#:
#: An order toolkit adds ``requires=frozenset({CAPABILITY_TRADING})``; a chart
#: toolkit narrows to ``surfaces=CHART_ONLY``. Entries name a module and an
#: attribute rather than importing anything, so a toolkit that is not selected
#: costs nothing.
TOOLKITS: list[ToolkitSpec] = [
    ToolkitSpec(
        key="market",
        module="services.agent.tools.market",
        attr="MarketToolkit",
        surfaces=ALL_SURFACES,
        order=10,
        description="Quotes, depth, history and intervals.",
    ),
    ToolkitSpec(
        key="symbols",
        module="services.agent.tools.symbols",
        attr="SymbolsToolkit",
        surfaces=ALL_SURFACES,
        order=20,
        description="Symbol search, contract lookup and expiry dates.",
    ),
    ToolkitSpec(
        key="indicators",
        module="services.agent.tools.indicators",
        attr="IndicatorsToolkit",
        surfaces=ALL_SURFACES,
        order=25,
        description=(
            "Compute any of the 127 openalgo.ta indicators over real candles, several in "
            "one call, or screen a list of instruments for one condition."
        ),
    ),
    ToolkitSpec(
        key="account",
        module="services.agent.tools.account",
        attr="AccountToolkit",
        surfaces=ALL_SURFACES,
        order=30,
        description="Funds, positions, holdings, order book, trade book and order status.",
    ),
    ToolkitSpec(
        key="options",
        module="services.agent.tools.options",
        attr="OptionsToolkit",
        surfaces=ALL_SURFACES,
        order=40,
        description="Option chain, strike resolution, Greeks and the synthetic future.",
    ),
    ToolkitSpec(
        key="viz",
        module="services.agent.tools.viz",
        attr="VizToolkit",
        surfaces=ALL_SURFACES,
        order=45,
        description=(
            "Draw a price chart or an option analytics chart in the conversation. "
            "The tool fetches the data, so the model never supplies a number."
        ),
    ),
    ToolkitSpec(
        key="instrument",
        module="services.agent.tools.instrument",
        attr="InstrumentToolkit",
        surfaces=ALL_SURFACES,
        order=44,
        description=(
            "Draw a full instrument card: quote, the day's move, an intraday chart, the "
            "52 week range, the order book and the operator's own position in it."
        ),
    ),
    ToolkitSpec(
        key="option_viz",
        module="services.agent.tools.option_viz",
        attr="OptionVizToolkit",
        surfaces=ALL_SURFACES,
        order=43,
        description=(
            "Draw a combined option premium over time, rolling ATM or on fixed legs, and a "
            "payoff diagram of named legs or of the operator's own open positions."
        ),
    ),
    ToolkitSpec(
        key="live",
        module="services.agent.tools.live",
        attr="LiveToolkit",
        surfaces=ALL_SURFACES,
        order=47,
        description=(
            "Open a live streaming card: a list of instruments the browser subscribes to, or "
            "one derived value, such as an ATM straddle, recomputed on every tick of its legs."
        ),
    ),
    ToolkitSpec(
        key="chart",
        module="services.agent.tools.chart",
        attr="ChartToolkit",
        surfaces=CHART_ONLY,
        order=5,
        description=(
            "Read the chart the operator has open, analyse its trend, structure, momentum "
            "and patterns, and draw levels, trendlines and zones on it. Every price drawn "
            "comes from real candles; the model supplies none."
        ),
    ),
    ToolkitSpec(
        key="openui",
        module="services.agent.tools.openui",
        attr="OpenUiToolkit",
        surfaces=CHAT_ONLY,
        order=46,
        description=(
            "Render a card of general data: bar, line, area and pie charts, tables, "
            "metric callouts. The model composes the markup, so never prices."
        ),
    ),
    ToolkitSpec(
        key="orders",
        module="services.agent.tools.orders",
        attr="OrdersToolkit",
        surfaces=CHAT_ONLY,
        requires=frozenset({CAPABILITY_TRADING}),
        order=50,
        description=(
            "Place, modify, cancel and close real orders and positions. "
            "Every tool requires human approval and runs the risk guard."
        ),
    ),
    ToolkitSpec(
        key="strategy_gen",
        module="services.agent.tools.strategy_gen",
        attr="StrategyGenToolkit",
        surfaces=CHAT_ONLY,
        order=60,
        description="Write a generated Python strategy to strategies/scripts/. Never starts it.",
    ),
    ToolkitSpec(
        key="flow_gen",
        module="services.agent.tools.flow_gen",
        attr="FlowGenToolkit",
        surfaces=CHAT_ONLY,
        order=70,
        description="Validate Flow workflow JSON, and import a valid one as an inactive workflow.",
    ),
    ToolkitSpec(
        key="websearch",
        module="services.agent.tools.websearch",
        attr="WebSearchToolkit",
        surfaces=ALL_SURFACES,
        requires=frozenset({CAPABILITY_WEB_SEARCH}),
        order=80,
        description="Web search for links, and cited web research.",
    ),
]


def add_spec(spec: ToolkitSpec) -> ToolkitSpec:
    """Add a spec to the registry, replacing any earlier one with the same key.

    Replacing rather than appending keeps a module reload, or a test that
    registers a stand-in toolkit, from producing two entries that both build.

    Args:
        spec: The spec to register.

    Returns:
        The spec that was registered.
    """
    for index, existing in enumerate(TOOLKITS):
        if existing.key == spec.key:
            logger.debug("Replacing agent toolkit spec %r", spec.key)
            TOOLKITS[index] = spec
            return spec
    TOOLKITS.append(spec)
    return spec


def _default_key(cls: type) -> str:
    """Derive a registry key from a toolkit class name.

    ``MarketDataToolkit`` becomes ``market_data``.

    Args:
        cls: The toolkit class.

    Returns:
        A snake-case key.
    """
    name = cls.__name__
    if name.endswith("Toolkit"):
        name = name[: -len("Toolkit")] or cls.__name__
    out: list[str] = []
    for index, char in enumerate(name):
        if char.isupper() and index and not name[index - 1].isupper():
            out.append("_")
        out.append(char.lower())
    return "".join(out) or cls.__name__.lower()


def register(
    cls: type | None = None,
    /,
    *,
    key: str | None = None,
    surfaces: Iterable[str] = ALL_SURFACES,
    requires: Iterable[str] = (),
    order: int = 100,
    description: str = "",
) -> Any:
    """Register a toolkit class, as a decorator or by direct call.

    Use this for a toolkit that is not part of the built-in :data:`TOOLKITS`
    table, such as one contributed by a test or loaded at runtime. Built-in
    toolkits use the table instead, because the table needs no import to be
    filtered and a decorator only runs once its module has been imported.

    Args:
        cls: The toolkit class, when called directly rather than as a decorator.
        key: Registry key. Defaults to the snake-case class name with a trailing
            ``Toolkit`` removed.
        surfaces: Surfaces the toolkit is offered on.
        requires: Capabilities from :data:`CAPABILITIES` the run must have.
        order: Sort weight, lower first.
        description: One line describing the toolkit.

    Returns:
        The class when used directly, or the decorator when used with keywords.
    """

    def decorate(target: type) -> type:
        first_line = (target.__doc__ or "").strip().splitlines()
        add_spec(
            ToolkitSpec(
                key=key or _default_key(target),
                module=target.__module__,
                attr=target.__name__,
                surfaces=frozenset(surfaces),
                requires=frozenset(requires),
                order=order,
                description=description or (first_line[0] if first_line else ""),
                cls=target,
            )
        )
        return target

    if cls is not None:
        return decorate(cls)
    return decorate


def registered_specs() -> tuple[ToolkitSpec, ...]:
    """Return every registered spec, in registration order.

    Returns:
        A tuple snapshot of the registry, safe to iterate while it changes.
    """
    return tuple(TOOLKITS)


def select_specs(context: Any) -> list[ToolkitSpec]:
    """Return the specs a run should build, filtered and ordered.

    Nothing is imported here, so this is the cheap call for a status endpoint or
    a test that only wants to know what a given context would be offered.

    Args:
        context: The run's :class:`ToolContext`, or anything shaped like it.

    Returns:
        Matching specs sorted by ``order`` then ``key``.
    """
    surface = _normalise_surface(getattr(context, "surface", SURFACE_CHAT))
    if surface not in ALL_SURFACES:
        logger.warning(
            "Agent tool registry asked for unknown surface %r; no toolkit selected", surface
        )
        return []
    selected = [spec for spec in TOOLKITS if spec.matches(context)]
    selected.sort(key=lambda spec: (spec.order, spec.key))
    return selected


def agno_available() -> bool:
    """Report whether the optional ``agno`` dependency can be imported.

    Returns:
        True when ``agno.tools`` imports cleanly. Used by the setup gate so the
        UI can say the dependency is missing instead of failing mid-stream.
    """
    try:
        importlib.import_module("agno.tools")
    except ImportError:
        return False
    return True


def _require_agno() -> type:
    """Import agno's ``Toolkit`` base class or raise an actionable error.

    Returns:
        The ``agno.tools.Toolkit`` class.

    Raises:
        RuntimeError: When agno is not installed, with the command to fix it.
    """
    try:
        from agno.tools import Toolkit
    except ImportError as exc:
        raise RuntimeError(
            "The agent module requires the 'agno' package, which is not installed. "
            "Install it with: uv add agno"
        ) from exc
    return Toolkit


def build_toolkits(context: Any) -> list[Toolkit]:
    """Build the toolkits a run may use.

    Called on every run by the callable factory ``builder.py`` hands to agno, so
    a change to the session state (trading enabled, a different surface) takes
    effect on the next turn without rebuilding the agent.

    Each toolkit is imported and constructed independently and a failure is
    logged and skipped, so one broken toolkit costs its own tools rather than
    the whole agent.

    Args:
        context: The run's :class:`ToolContext`, or anything shaped like it.
            Must carry ``api_key``, ``surface`` and every capability in
            :data:`CAPABILITIES`.

    Returns:
        Toolkit instances, ordered by their spec's ``order`` then ``key``.

    Raises:
        RuntimeError: When the ``agno`` package is not installed.
    """
    toolkit_base = _require_agno()
    toolkits: list[Toolkit] = []

    for spec in select_specs(context):
        try:
            cls = spec.resolve()
        except Exception:
            logger.exception(
                "Agent toolkit %r could not be imported from %s.%s; skipping it",
                spec.key,
                spec.module,
                spec.attr,
            )
            continue

        try:
            instance = cls(context)
        except Exception:
            logger.exception("Agent toolkit %r could not be built; skipping it", spec.key)
            continue

        if not isinstance(instance, toolkit_base):
            logger.warning(
                "Agent toolkit %r built a %s, which is not an agno Toolkit; skipping it",
                spec.key,
                type(instance).__name__,
            )
            continue

        toolkits.append(instance)

    logger.debug(
        "Agent toolkits for surface=%s capabilities=%s: %s",
        getattr(context, "surface", SURFACE_CHAT),
        ",".join(f"{name}={bool(getattr(context, name, False))}" for name in sorted(CAPABILITIES)),
        ", ".join(getattr(t, "name", type(t).__name__) for t in toolkits) or "none",
    )
    return toolkits
