"""Which endpoint a latency record is for, and which group that endpoint is in.

Every `/api/v1` call is timed and stored in `order_latency` with a short tag in
its `order_type` column. Until now the monitor then put all of those rows into
one average, one P99 and one "under 150 ms" figure, on a page titled Order
Latency Monitor. A chart or a scanner makes hundreds of history calls for every
order, so the page described the history calls and called them orders: an
install with 2,607 records and not one order showed "2,607 orders tracked"
(issues #2421 and #2286).

This module is the one place that says what each tag is and where it belongs.
Three things read it, and they used to keep a list each:

- `utils/latency_monitor.py`, to tag a call when it is recorded.
- `database/latency_db.py`, to total a group, and to decide what is kept.
- `blueprints/latency.py`, to hand the groups to the page, which keeps no list
  of its own.

The groups follow the sections of `docs/api/README.md`, so the monitor reads the
way the API reference does. Where the two differ it is on purpose: the reference
sorts by what an endpoint is about, and a latency figure only means something
across calls that cost roughly the same thing. So the GTT order book sits with
the other books rather than with the orders it lists, and the symbol lookups
that OpenAlgo answers from its own data are apart from the market data that
comes from the broker.

**Orders are the group that is kept.** Order records stay forever and every
other record is removed after a week, so `ORDER_TAGS` is also the keep list.
There used to be two copies of that list, with a comment on each asking that
they stay in step, and a third, separate table of tags by endpoint name. Six of
that table's names matched no endpoint, so options orders were recorded as
OPTIONSORDER and OPTIONSMULTIORDER, tags that were on neither keep list: their
latency was deleted after a week as though they were data queries. Rows written
under those two tags are read as the orders they are (`LEGACY_TAGS`).

Adding an endpoint: give its namespace an `Endpoint` in the group it belongs
to. `test/test_latency_groups.py` fails for a registered namespace that has
none, so a new endpoint cannot be left to fall into "Other" by accident.

No I/O here, and nothing imported from the application: both the recorder and
the database module import this, and neither may pull the other in through it.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Endpoint:
    """One kind of call: the tag it is stored under and the name a trader reads."""

    tag: str
    label: str
    #: The `/api/v1` namespaces recorded under this tag.
    namespaces: tuple[str, ...] = ()


@dataclass(frozen=True)
class Group:
    """Endpoints whose latency can sensibly be read together."""

    key: str
    label: str
    description: str
    endpoints: tuple[Endpoint, ...] = ()
    #: Whether the Excellent/Good/Acceptable/Slow scale applies. It was drawn
    #: up for an order confirmation and says nothing about a history download.
    rated: bool = False
    #: Whether these records are kept forever. Everything else goes after
    #: `RETENTION_DAYS`.
    kept: bool = False


#: How long a record outside the kept group stays.
RETENTION_DAYS = 7

ORDERS = "orders"
ALL = "all"
OTHER = "other"
DEFAULT_GROUP = ORDERS

GROUPS: tuple[Group, ...] = (
    Group(
        key=ORDERS,
        label="Orders",
        description=(
            "Placing, changing and cancelling orders. These are the calls a trade waits on."
        ),
        rated=True,
        kept=True,
        endpoints=(
            Endpoint("PLACE", "Place order", ("place_order",)),
            Endpoint("SMART", "Smart order", ("place_smart_order",)),
            Endpoint("OPTIONS", "Options order", ("optionsorder",)),
            Endpoint("OPTIONS_MULTI", "Options multi-leg order", ("optionsmultiorder",)),
            Endpoint("BASKET", "Basket order", ("basket_order",)),
            Endpoint("SPLIT", "Split order", ("split_order",)),
            Endpoint("MODIFY", "Modify order", ("modify_order",)),
            Endpoint("CANCEL", "Cancel order", ("cancel_order",)),
            Endpoint("CANCEL_ALL", "Cancel all orders", ("cancel_all_order",)),
            Endpoint("CLOSE", "Close position", ("close_position",)),
            Endpoint("GTT_PLACE", "Place GTT", ("place_gtt_order",)),
            Endpoint("GTT_MODIFY", "Modify GTT", ("modify_gtt_order",)),
            Endpoint("GTT_CANCEL", "Cancel GTT", ("cancel_gtt_order",)),
        ),
    ),
    Group(
        key="account",
        label="Account and books",
        description=("Order status, positions, holdings, funds and the order and trade books."),
        endpoints=(
            Endpoint("STATUS", "Order status", ("orderstatus",)),
            Endpoint("POSITION", "Open position", ("openposition",)),
            Endpoint("ORDERBOOK", "Order book", ("orderbook",)),
            Endpoint("TRADEBOOK", "Trade book", ("tradebook",)),
            Endpoint("POSITIONBOOK", "Position book", ("positionbook",)),
            Endpoint("HOLDINGS", "Holdings", ("holdings",)),
            Endpoint("FUNDS", "Funds", ("funds",)),
            Endpoint("MARGIN", "Margin", ("margin",)),
            Endpoint("GTT_ORDERBOOK", "GTT order book", ("gtt_orderbook",)),
        ),
    ),
    Group(
        key="market_data",
        label="Market data",
        description=(
            "Quotes, depth and price history. A history call returns a large "
            "response and is expected to be the slowest."
        ),
        endpoints=(
            Endpoint("QUOTES", "Quote", ("quotes",)),
            Endpoint("MULTIQUOTES", "Multiple quotes", ("multiquotes",)),
            Endpoint("DEPTH", "Market depth", ("depth",)),
            Endpoint("HISTORY", "History", ("history",)),
            Endpoint("TICKER", "Ticker", ("ticker",)),
        ),
    ),
    Group(
        key="options",
        label="Options",
        description="Option chain, Greeks and option symbol lookups.",
        endpoints=(
            Endpoint("OPTIONCHAIN", "Option chain", ("optionchain",)),
            Endpoint("OPTIONGREEKS", "Option Greeks", ("optiongreeks",)),
            Endpoint("MULTIOPTIONGREEKS", "Batch option Greeks", ("multioptiongreeks",)),
            Endpoint("OPTIONSYMBOL", "Option symbol", ("optionsymbol",)),
            Endpoint("SYNTHETICFUTURE", "Synthetic future", ("syntheticfuture",)),
        ),
    ),
    Group(
        key="reference",
        label="Symbols and settings",
        description=(
            "Symbol search, expiry dates, the market calendar and settings. These "
            "are answered from OpenAlgo's own data."
        ),
        endpoints=(
            Endpoint("SYMBOL", "Symbol", ("symbol",)),
            Endpoint("SEARCH", "Symbol search", ("search",)),
            Endpoint("EXPIRY", "Expiry dates", ("expiry",)),
            Endpoint("INSTRUMENTS", "Instruments", ("instruments",)),
            Endpoint("INTERVALS", "Intervals", ("intervals",)),
            Endpoint("MARKET_HOLIDAYS", "Market holidays", ("market/holidays",)),
            Endpoint("MARKET_TIMINGS", "Market timings", ("market/timings",)),
            Endpoint("ANALYZER", "Analyzer mode", ("analyzer",)),
            Endpoint("PNL", "Sandbox P&L", ("pnl",)),
            Endpoint("CHART", "Chart preferences", ("chart",)),
            Endpoint("PING", "Ping", ("ping",)),
        ),
    ),
    Group(
        key="tools",
        label="Tools and alerts",
        description=("Portfolio, SIP and sector analysis, the strategy module and alert messages."),
        endpoints=(
            Endpoint("PORTFOLIO", "Portfolio analysis", ("portfolio",)),
            Endpoint("SIP", "SIP backtest", ("sip",)),
            Endpoint("SECTORROTATION", "Sector rotation", ("sectorrotation",)),
            Endpoint("STRATEGY", "Strategy module", ("strategy",)),
            Endpoint("TELEGRAM", "Telegram", ("telegram",)),
            Endpoint("WHATSAPP", "WhatsApp", ("whatsapp",)),
            Endpoint("SLACK", "Slack", ("slack",)),
            Endpoint("DISCORD", "Discord", ("discord",)),
        ),
    ),
)

#: A record whose tag is in no group. Shown only when there is one.
OTHER_GROUP = Group(
    key=OTHER,
    label="Other",
    description="Calls that are in none of the groups above.",
)

#: Every record, whatever it is. Not rated: the scale means nothing across
#: unlike calls, which is the fault this module exists to end.
ALL_GROUP = Group(
    key=ALL,
    label="All calls",
    description=(
        "Every recorded call together. Orders and data calls take very different "
        "times, so read the groups for a figure you can act on."
    ),
)

#: Tags that rows were written under before this module, read as what they are.
LEGACY_TAGS: dict[str, str] = {
    "OPTIONSORDER": "OPTIONS",
    "OPTIONSMULTIORDER": "OPTIONS_MULTI",
}

_GROUP_BY_KEY: dict[str, Group] = {group.key: group for group in (*GROUPS, OTHER_GROUP, ALL_GROUP)}
_ENDPOINT_BY_TAG: dict[str, Endpoint] = {
    endpoint.tag: endpoint for group in GROUPS for endpoint in group.endpoints
}
_GROUP_KEY_BY_TAG: dict[str, str] = {
    endpoint.tag: group.key for group in GROUPS for endpoint in group.endpoints
}

#: namespace name -> the tag its calls are stored under.
TAG_FOR_NAMESPACE: dict[str, str] = {
    namespace: endpoint.tag
    for group in GROUPS
    for endpoint in group.endpoints
    for namespace in endpoint.namespaces
}

#: Every tag that is in a group, the legacy spellings included.
KNOWN_TAGS: frozenset[str] = frozenset(_ENDPOINT_BY_TAG) | frozenset(LEGACY_TAGS)


def canonical(tag: str | None) -> str | None:
    """The tag a stored value stands for."""
    return LEGACY_TAGS.get(tag, tag) if tag else tag


def tags_in(group_key: str) -> frozenset[str]:
    """Every stored value that belongs to a group, the legacy spellings included.

    Empty for `ALL` and `OTHER`, which are not defined by a list of tags.
    """
    group = _GROUP_BY_KEY.get(group_key)
    if group is None or not group.endpoints:
        return frozenset()
    own = {endpoint.tag for endpoint in group.endpoints}
    return frozenset(own | {old for old, new in LEGACY_TAGS.items() if new in own})


#: The records that are kept forever: the orders group. Also what
#: `purge_old_data_logs` leaves alone, so there is one list and not two.
ORDER_TAGS: frozenset[str] = tags_in(ORDERS)


def is_group(group_key: str | None) -> bool:
    return group_key in _GROUP_BY_KEY


def get_group(group_key: str) -> Group:
    return _GROUP_BY_KEY[group_key]


def group_keys() -> tuple[str, ...]:
    """Every key a caller may ask for, in the order the page shows them."""
    return (*(group.key for group in GROUPS), OTHER, ALL)


def group_key_of(tag: str | None) -> str:
    """The group a stored tag belongs to, `OTHER` for one that is in none."""
    return _GROUP_KEY_BY_TAG.get(canonical(tag), OTHER)


def label_of(tag: str | None) -> str:
    """What to call a stored tag on the page."""
    endpoint = _ENDPOINT_BY_TAG.get(canonical(tag))
    if endpoint is not None:
        return endpoint.label
    return tag or "Unknown"


def endpoint_order(group_key: str) -> dict[str, int]:
    """Position of each tag in its group, for listing endpoints in a fixed order."""
    group = _GROUP_BY_KEY.get(group_key)
    if group is not None and group.endpoints:
        return {endpoint.tag: index for index, endpoint in enumerate(group.endpoints)}
    return {tag: index for index, tag in enumerate(_ENDPOINT_BY_TAG)}
