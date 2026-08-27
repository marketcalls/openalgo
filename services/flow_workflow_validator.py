# services/flow_workflow_validator.py
"""Structural validation for Flow workflow payloads.

The editor validates before it posts, but the API is reachable directly, so
without a server-side check a malformed graph is persisted and only fails
later - sometimes at activation, sometimes mid-execution against a live
broker. A workflow that cannot be rendered or executed should never reach the
database in the first place.

This validates *structure*, not trading semantics: shape, identifiers, known
node types, edge endpoints, and the one-trigger rule. Per-node field contracts
stay with the executor, which is where their defaults and coercions live.
"""

import json
import math
import re
from typing import Any

from services.flow_node_contracts import (
    EXPIRY_DATE_PATTERN as _EXPIRY_DATE_PATTERN,
)
from services.flow_node_contracts import (
    OPTION_OFFSET_PATTERN as _OPTION_OFFSET_PATTERN,
)
from services.flow_node_contracts import (
    VALID_EXPIRY_TYPES as VALID_LEG_EXPIRY_TYPES,
)
from services.flow_node_contracts import (
    VALID_STATUSES,
    normalize_status,
    parse_underlying_symbol,
)
from utils.constants import VALID_ACTIONS as SHARED_VALID_ACTIONS
from utils.constants import VALID_EXCHANGES as SHARED_VALID_EXCHANGES
from utils.constants import VALID_PRICE_TYPES as SHARED_VALID_PRICE_TYPES
from utils.constants import VALID_PRODUCT_TYPES as SHARED_VALID_PRODUCT_TYPES
from utils.logging import get_logger

logger = get_logger(__name__)

# The node types the editor can render and the executor can dispatch. Kept in
# lockstep with frontend/src/components/flow/nodes/index.ts; the parity test in
# test/test_flow_workflow_validator.py fails if the two drift.
VALID_NODE_TYPES: frozenset[str] = frozenset(
    {
        "andGate",
        "barOffset",
        "basketOrder",
        "calendar",
        "cancelAllOrders",
        "cancelOrder",
        "closePositions",
        "delay",
        "expiry",
        "fundCheck",
        "funds",
        "getDepth",
        "getOrderStatus",
        "getQuote",
        "group",
        "history",
        "holdings",
        "holidays",
        "httpRequest",
        "indicator",
        "intervals",
        "log",
        "margin",
        "mathExpression",
        "modifyOrder",
        "multiQuotes",
        "notGate",
        "openPosition",
        "optionChain",
        "optionSymbol",
        "optionsMultiOrder",
        "optionsOrder",
        "orGate",
        "orderBook",
        "orderUpdateTrigger",
        "placeOrder",
        "positionBook",
        "positionCheck",
        "priceAlert",
        "priceCondition",
        "priorPeriodOhlc",
        "smartOrder",
        "splitOrder",
        "start",
        "strategyPnl",
        "subscribeDepth",
        "subscribeLtp",
        "subscribeQuote",
        "symbol",
        "syntheticFuture",
        "telegramAlert",
        "timeCondition",
        "timeWindow",
        "timings",
        "tradeBook",
        "unsubscribe",
        "varCondition",
        "variable",
        "waitUntil",
        "webhookTrigger",
        "whatsappAlert",
    }
)

TRIGGER_NODE_TYPES: frozenset[str] = frozenset(
    {"start", "webhookTrigger", "priceAlert", "orderUpdateTrigger"}
)

# Fields required only for particular option values. A channel alert is
# configured with priceLower/priceUpper and has no single `price`, so requiring
# one unconditionally rejected a documented, working alert.
# Fields required only for particular option values, keyed on the *canonical*
# condition the price monitor uses. The editor and the monitor keep separate
# spellings for the same conditions, so the selector is normalized through the
# monitor's own alias table before lookup - keying on the editor's spellings let
# an alias such as `price_above` activate with no target price at all.
CONDITIONAL_REQUIRED_FIELDS: dict[str, dict[str, dict[str, tuple[str, ...]]]] = {
    "priceAlert": {
        "condition": {
            "greater_than": ("price",),
            "less_than": ("price",),
            "crossing": ("price",),
            "crossing_up": ("price",),
            "crossing_down": ("price",),
            "entering_channel": ("priceLower", "priceUpper"),
            "inside_channel": ("priceLower", "priceUpper"),
            "exiting_channel": ("priceLower", "priceUpper"),
            "outside_channel": ("priceLower", "priceUpper"),
            "moving_up_percent": ("percentage",),
            "moving_down_percent": ("percentage",),
            "moving_up": (),
            "moving_down": (),
        }
    },
}


def _positive_number(value: object) -> float | None:
    """The value as a positive number, or None when it is not one."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _valid_quantity(value: object, *, allow_zero: bool = False) -> bool:
    """Return whether an order quantity is positive, or non-negative when allowed."""
    if isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(number):
        return False
    return number >= 0 if allow_zero else number > 0


def _alert_threshold_errors(
    base: str, data: dict, condition: str, required: tuple[str, ...]
) -> list[dict]:
    """Sanity-check the numbers a price alert compares against.

    A zero or negative level is never reached by a real instrument price, and an
    inverted channel is empty, so either would leave the alert registered and
    unable to fire - the same silent non-firing this node has had before.
    """
    errors: list[dict] = []
    for field in required:
        if field not in data:
            continue  # absence is reported as a missing required field
        if _positive_number(data.get(field)) is None:
            errors.append(
                _err(
                    f"{base}/data/{field}",
                    "invalid_threshold",
                    f"{field} must be a positive number for a '{condition}' alert; "
                    f"{data.get(field)!r} can never be reached.",
                    "a positive number",
                    data.get(field),
                )
            )
    lower = _positive_number(data.get("priceLower"))
    upper = _positive_number(data.get("priceUpper"))
    if "priceLower" in required and lower is not None and upper is not None and lower >= upper:
        errors.append(
            _err(
                f"{base}/data/priceLower",
                "invalid_threshold",
                f"priceLower ({lower}) must be below priceUpper ({upper}); "
                "an inverted channel contains no prices.",
                "priceLower < priceUpper",
                [lower, upper],
            )
        )
    return errors


def _canonical_condition(value: object) -> str:
    """Resolve a condition to the name the price monitor compares on.

    Delegated to the monitor so the two cannot drift; falls back to a plain
    normalization if it cannot be imported (docs builds, lint environments).
    """
    try:
        from services.flow_price_monitor_service import FlowPriceMonitor

        return FlowPriceMonitor.normalize_condition(str(value))
    except Exception:
        return str(value or "").strip().lower().replace("-", "_")


# Nodes that exist only in the editor. They are never dispatched, so they are
# exempt from reachability.
DECORATIVE_NODE_TYPES: frozenset[str] = frozenset({"group"})

MAX_NODES = 500
MAX_EDGES = 1000

# Source handles each node kind may emit. Condition nodes and gates fork; the
# executor treats yes/no as synonyms of true/false. Anything else on an edge is
# a typo that silently drops the branch at run time.
_BRANCHING_HANDLES = frozenset({"true", "false", "yes", "no"})
BRANCHING_NODE_TYPES: frozenset[str] = frozenset(
    {
        "positionCheck",
        "fundCheck",
        "priceCondition",
        "varCondition",
        "timeWindow",
        "timeCondition",
        "andGate",
        "orGate",
        "notGate",
        # Renders true/false handles like the condition nodes, so rejecting them
        # made a valid price-alert workflow fail on its own edges.
        "priceAlert",
    }
)

# Fields an order node cannot execute without. Checked here because a workflow
# missing them fails at the broker, mid-session, rather than at import.
REQUIRED_NODE_FIELDS: dict[str, tuple[str, ...]] = {
    "placeOrder": ("symbol", "exchange", "action", "quantity"),
    "smartOrder": ("symbol", "exchange", "action", "quantity"),
    "optionsOrder": ("underlying", "action", "quantity"),
    "modifyOrder": ("orderId",),
    "cancelOrder": ("orderId",),
    "getOrderStatus": ("orderId",),
    "getQuote": ("symbol", "exchange"),
    "getDepth": ("symbol", "exchange"),
    "history": ("symbol", "exchange", "interval"),
    "indicator": ("indicatorName",),
    "priorPeriodOhlc": ("symbol", "exchange"),
    "barOffset": ("symbol", "exchange"),
    "openPosition": ("symbol", "exchange"),
    "telegramAlert": ("message",),
    "whatsappAlert": ("message",),
    "mathExpression": ("expression",),
    "varCondition": ("leftValue", "operator"),
    "priceCondition": ("symbol", "exchange", "operator"),
    # Condition gates that fail OPEN when unconfigured, so an empty one lets the
    # order behind it through unconditionally: positionCheck with no symbol reads
    # a zero-quantity position, which makes `not_exists` always true.
    "positionCheck": ("symbol", "exchange", "condition"),
    # Broker-mutating nodes. An empty one reaches the broker as a malformed
    # order rather than failing at import.
    "splitOrder": ("symbol", "exchange", "action", "quantity", "splitSize"),
    "basketOrder": ("orders",),
    "optionsMultiOrder": ("underlying", "quantity"),
    # `price` is required only for level conditions - see CONDITIONAL_FIELDS.
    "priceAlert": ("symbol", "exchange", "condition"),
    "subscribeLtp": ("symbol", "exchange"),
    "subscribeQuote": ("symbol", "exchange"),
    "subscribeDepth": ("symbol", "exchange"),
    "optionSymbol": ("underlying", "optionType"),
    "optionChain": ("underlying",),
    "syntheticFuture": ("underlying",),
    "expiry": ("symbol", "exchange"),
    "symbol": ("symbol", "exchange"),
    "multiQuotes": ("symbols",),
    "httpRequest": ("url",),
    "variable": ("variableName",),
    "waitUntil": ("targetTime",),
}


# Nodes that need at least one of a set of interchangeable fields, rather than
# every field in a list. fundCheck reads `minAvailable`, or a legacy `threshold`
# from a node saved before that field existed; with neither, its guard compares
# against zero and passes on any balance at all -- the bypass the field was
# added to prevent.
EITHER_REQUIRED_FIELDS: dict[str, tuple[tuple[str, ...], ...]] = {
    "fundCheck": (("minAvailable", "threshold"),),
}


# Order constants, from docs/prompt/order-constants.md. Presence checks alone
# let an invalid value through to the broker, where it becomes a rejection at
# best and a silently different order at worst -- several broker mappers fall
# back to a default for an unrecognised price type rather than refusing it, so
# a typo'd "LIMT" becomes a MARKET order.
VALID_EXCHANGES = frozenset(SHARED_VALID_EXCHANGES)
VALID_PRODUCTS = frozenset(SHARED_VALID_PRODUCT_TYPES)
VALID_PRICE_TYPES = frozenset(SHARED_VALID_PRICE_TYPES)
VALID_ACTIONS = frozenset(SHARED_VALID_ACTIONS)
VALID_OPTION_TYPES = frozenset({"CE", "PE"})
VALID_VARIABLE_OPERATIONS = frozenset(
    {
        "set",
        "get",
        "add",
        "subtract",
        "multiply",
        "divide",
        "increment",
        "decrement",
        "parse_json",
        "stringify",
        "append",
    }
)
PRICED_ORDER_NODE_TYPES = frozenset(
    {"placeOrder", "smartOrder", "optionsOrder", "optionsMultiOrder", "basketOrder", "splitOrder"}
)

# Which of those vocabularies each field is drawn from.
ENUM_FIELDS: dict[str, frozenset[str]] = {
    "exchange": VALID_EXCHANGES,
    "action": VALID_ACTIONS,
    "product": VALID_PRODUCTS,
    "priceType": VALID_PRICE_TYPES,
    "pricetype": VALID_PRICE_TYPES,
    "operation": VALID_VARIABLE_OPERATIONS,
}

# Fields that must be a positive number wherever they appear. SmartOrder
# quantity is the exception: zero denotes a valid target-position square-off.
POSITIVE_NUMBER_FIELDS = frozenset({"quantity", "splitSize", "lots"})


def _priced_order_errors(
    base: str,
    data: dict,
    strict: bool,
    price_type_key: str = "priceType",
    price_key: str = "price",
    trigger_price_key: str = "triggerPrice",
) -> list[dict]:
    """Validate price fields selected by a static price type without touching templates."""
    price_type = data.get(price_type_key)
    if not isinstance(price_type, str) or "{{" in price_type:
        return []
    canonical = price_type.strip().upper()
    found: list[dict] = []
    for field, applies_to in (
        (price_key, {"LIMIT", "SL"}),
        (trigger_price_key, {"SL", "SL-M"}),
    ):
        if canonical not in applies_to:
            continue
        value = data.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            if strict:
                found.append(
                    _err(
                        f"{base}/{field}",
                        "missing_price",
                        f"A {canonical} order needs {field} before it can execute.",
                        field,
                        value,
                    )
                )
            continue
        if isinstance(value, str) and "{{" in value:
            continue
        if _positive_number(value) is None:
            found.append(
                _err(
                    f"{base}/{field}",
                    "invalid_price",
                    f"A {canonical} order needs a positive {field}; {value!r} cannot be priced.",
                    "a positive number",
                    value,
                )
            )
    return found


def _static_order_leg_errors(
    base: str,
    data: dict,
    strict: bool,
    required_fields: tuple[str, ...],
    *,
    price_type_key: str,
    trigger_price_key: str = "triggerPrice",
    option_leg: bool = False,
) -> list[dict]:
    """Validate a parsed Margin or custom-options leg without rewriting it."""
    found: list[dict] = []
    for field in required_fields:
        value = data.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            if strict:
                found.append(
                    _err(
                        f"{base}/{field}",
                        "missing_required_field",
                        f"A position needs {field} before it can execute.",
                        field,
                        value,
                    )
                )

    enum_fields = {
        "exchange": VALID_EXCHANGES,
        "action": VALID_ACTIONS,
        "product": VALID_PRODUCTS,
        price_type_key: VALID_PRICE_TYPES,
    }
    if option_leg:
        enum_fields["optionType"] = VALID_OPTION_TYPES
        if price_type_key == "priceType" and "pricetype" in data:
            enum_fields["pricetype"] = VALID_PRICE_TYPES
    for field, allowed in enum_fields.items():
        if field not in data:
            continue
        value = data.get(field)
        if isinstance(value, str) and ("{{" in value or not value.strip()):
            continue
        if not isinstance(value, str) or value.strip().upper() not in allowed:
            found.append(
                _err(
                    f"{base}/{field}",
                    "invalid_constant",
                    f"'{value}' is not a valid {field} constant.",
                    sorted(allowed),
                    value,
                )
            )

    if "quantity" in data:
        quantity = data.get("quantity")
        if not (isinstance(quantity, str) and ("{{" in quantity or not quantity.strip())):
            if not _valid_quantity(quantity):
                found.append(
                    _err(
                        f"{base}/quantity",
                        "invalid_quantity",
                        f"quantity must be a positive number; {quantity!r} cannot execute.",
                        "a positive number",
                        quantity,
                    )
                )
    found.extend(
        _priced_order_errors(
            base,
            data,
            strict,
            price_type_key,
            trigger_price_key=trigger_price_key,
        )
    )
    return found


def _margin_errors(base: str, data: dict, strict: bool) -> list[dict]:
    """Validate Margin's legacy single position or its raw JSON basket."""
    raw_key = next(
        (
            key
            for key in ("positionsJson", "positions")
            if data.get(key) is not None
            and not (isinstance(data.get(key), str) and not data.get(key).strip())
        ),
        None,
    )
    if raw_key is None:
        symbol = data.get("symbol")
        if symbol is not None and not (isinstance(symbol, str) and not symbol.strip()):
            return []
        return (
            [
                _err(
                    f"{base}/data/positionsJson",
                    "missing_alternative",
                    "A Margin node needs positionsJson, positions, or a legacy symbol.",
                    "a non-empty positionsJson, positions, or symbol",
                    None,
                )
            ]
            if strict
            else []
        )

    raw = data[raw_key]
    raw_base = f"{base}/data/{raw_key}"
    if isinstance(raw, str):
        text = raw.strip()
        if "{{" in text:
            return []
        try:
            positions = json.loads(text)
        except (TypeError, ValueError):
            return [
                _err(
                    raw_base,
                    "invalid_positions",
                    "Margin positions must be a JSON array of position objects.",
                    "a JSON array of objects",
                    raw,
                )
            ]
    else:
        positions = raw

    if not isinstance(positions, list) or not positions:
        return [
            _err(
                raw_base,
                "invalid_positions",
                "Margin positions must be a non-empty array of position objects.",
                "a non-empty array of objects",
                positions,
            )
        ]

    found: list[dict] = []
    for index, leg in enumerate(positions):
        leg_base = f"{raw_base}/{index}"
        if not isinstance(leg, dict):
            found.append(
                _err(
                    leg_base,
                    "invalid_positions",
                    "Every Margin position must be an object.",
                    "object",
                    leg,
                )
            )
            continue
        found.extend(
            _static_order_leg_errors(
                leg_base,
                leg,
                strict,
                ("symbol", "exchange", "action", "quantity", "product", "pricetype"),
                price_type_key="pricetype",
                trigger_price_key="trigger_price",
            )
        )
    return found


def _options_multi_errors(base: str, data: dict, strict: bool) -> list[dict]:
    """Validate the executable shape of generated and custom option strategies."""
    strategy = data.get("strategy", "straddle")
    if isinstance(strategy, str) and "{{" in strategy:
        return []
    canonical = strategy.strip().lower() if isinstance(strategy, str) else ""
    if canonical != "custom":
        price_type = data.get("priceType")
        if isinstance(price_type, str) and "{{" not in price_type:
            if price_type.strip().upper() not in {"MARKET", "LIMIT"}:
                return [
                    _err(
                        f"{base}/data/priceType",
                        "invalid_constant",
                        "Generated option strategies support only MARKET and LIMIT price types.",
                        ["LIMIT", "MARKET"],
                        price_type,
                    )
                ]
        return []

    legs_key = "orderLegs" if "legs" not in data and "orderLegs" in data else "legs"
    legs = data.get(legs_key)
    legs_base = f"{base}/data/{legs_key}"
    if legs is None or (isinstance(legs, str) and not legs.strip()):
        return (
            [
                _err(
                    legs_base,
                    "missing_required_field",
                    "A custom options strategy needs at least one leg.",
                    "a non-empty legs array",
                    legs,
                )
            ]
            if strict
            else []
        )
    if isinstance(legs, str) and "{{" in legs:
        return []
    if not isinstance(legs, list) or not legs:
        return [
            _err(
                legs_base,
                "invalid_legs",
                "Custom options strategy legs must be a non-empty array.",
                "a non-empty array of objects",
                legs,
            )
        ]

    found: list[dict] = []
    for index, leg in enumerate(legs):
        leg_base = f"{legs_base}/{index}"
        if not isinstance(leg, dict):
            found.append(
                _err(
                    leg_base,
                    "invalid_legs",
                    "Every custom options leg must be an object.",
                    "object",
                    leg,
                )
            )
            continue
        effective_leg = dict(leg)
        if "product" not in effective_leg and "product" in data:
            effective_leg["product"] = data["product"]
        price_type_key = "priceType" if "priceType" in leg else "pricetype"
        if price_type_key not in effective_leg and "priceType" in data:
            effective_leg[price_type_key] = data["priceType"]
        for field in ("price", "triggerPrice"):
            if field not in effective_leg and field in data:
                effective_leg[field] = data[field]
        # A leg picks its strike one of two ways, so neither selector is
        # required on its own -- demanding `offset` rejected every leg that
        # names an absolute strike, which the executor has always accepted.
        found.extend(
            _static_order_leg_errors(
                leg_base,
                effective_leg,
                strict,
                ("optionType", "action", "quantity"),
                price_type_key=price_type_key,
                option_leg=True,
            )
        )
        found.extend(_option_leg_strike_and_expiry_errors(leg_base, leg, strict))
    return found


def _option_leg_strike_and_expiry_errors(base: str, leg: dict, strict: bool) -> list[dict]:
    """Check the two selectors a manually built leg adds: strike and expiry.

    Both are optional in the sense that each has a fallback -- an offset instead
    of a strike, the node's expiry instead of the leg's -- so the check is that
    whatever the leg *does* name is usable, and that it names a strike one way
    or the other. Mirrors execute_options_multi_order; a leg accepted here must
    not fail at run time, because by then the rest of the basket may already be
    filled.
    """
    found: list[dict] = []

    def templated(value) -> bool:
        return isinstance(value, str) and "{{" in value

    strike_mode = leg.get("strikeMode")
    if strike_mode is not None and not templated(strike_mode):
        if not isinstance(strike_mode, str) or strike_mode.strip().upper() not in {
            "OFFSET",
            "STRIKE",
        }:
            found.append(
                _err(
                    f"{base}/strikeMode",
                    "invalid_constant",
                    f"'{strike_mode}' is not a valid strikeMode constant.",
                    ["OFFSET", "STRIKE"],
                    strike_mode,
                )
            )

    names_strike = leg.get("strike") is not None and not (
        isinstance(leg.get("strike"), str) and not leg["strike"].strip()
    )
    offset = leg.get("offset")
    names_offset = offset is not None and not (
        isinstance(offset, str) and not offset.strip()
    )

    if names_strike:
        strike = leg["strike"]
        if not templated(strike):
            # bool is an int subclass, so True would otherwise pass as strike 1.
            numeric = None
            if isinstance(strike, bool):
                numeric = None
            elif isinstance(strike, (int, float)):
                numeric = float(strike)
            elif isinstance(strike, str):
                try:
                    numeric = float(strike.strip())
                except ValueError:
                    numeric = None
            if numeric is None or numeric <= 0:
                found.append(
                    _err(
                        f"{base}/strike",
                        "invalid_strike",
                        f"strike must be a positive number; {strike!r} names no contract.",
                        "a positive number",
                        strike,
                    )
                )
    elif names_offset:
        if not templated(offset):
            text = str(offset).strip().upper()
            if not _OPTION_OFFSET_PATTERN.fullmatch(text):
                found.append(
                    _err(
                        f"{base}/offset",
                        "invalid_constant",
                        f"'{offset}' is not a valid offset.",
                        "ATM, ITM1-ITM50 or OTM1-OTM50",
                        offset,
                    )
                )
    elif strict:
        found.append(
            _err(
                f"{base}/offset",
                "missing_required_field",
                "A leg needs either an offset or an absolute strike before it can execute.",
                "offset or strike",
                None,
            )
        )

    expiry = leg.get("expiry")
    if expiry is not None and not templated(expiry):
        text = str(expiry).strip().upper()
        if text and not _EXPIRY_DATE_PATTERN.fullmatch(text):
            found.append(
                _err(
                    f"{base}/expiry",
                    "invalid_expiry",
                    f"expiry must be in DDMMMYY format such as 28OCT25; got {expiry!r}.",
                    "DDMMMYY",
                    expiry,
                )
            )

    expiry_type = leg.get("expiryType")
    if expiry_type is not None and not templated(expiry_type):
        text = str(expiry_type).strip().lower()
        if text and text not in VALID_LEG_EXPIRY_TYPES:
            found.append(
                _err(
                    f"{base}/expiryType",
                    "invalid_constant",
                    f"'{expiry_type}' is not a valid expiryType constant.",
                    sorted(VALID_LEG_EXPIRY_TYPES),
                    expiry_type,
                )
            )

    return found


def _enum_and_range_errors(base: str, node_type: str, data: dict, strict: bool) -> list:
    """Value-level checks for order fields: known constants, sane numbers.

    Skipped for any value carrying a {{variable}}, which is only resolvable at
    run time -- the executor checks those separately before it calls the broker.
    """
    found = []
    for field, allowed in ENUM_FIELDS.items():
        if field not in data:
            continue
        value = data.get(field)
        if isinstance(value, str) and "{{" in value:
            continue
        if isinstance(value, str) and not value.strip() and field != "operation":
            continue
        if not isinstance(value, str):
            # A number or boolean here is not merely unknown, it is the wrong
            # type: skipping non-strings let `"exchange": 123` reach the broker
            # mapper, which stringifies it and looks up nothing.
            found.append(
                _err(
                    f"{base}/data/{field}",
                    "invalid_constant",
                    f"{field} must be one of the {field} constants written as a "
                    f"string; {value!r} is a {type(value).__name__}.",
                    sorted(allowed),
                    value,
                )
            )
            continue
        canonical = value if field == "operation" else value.strip().upper()
        if canonical not in allowed:
            found.append(
                _err(
                    f"{base}/data/{field}",
                    "invalid_constant",
                    f"'{value}' is not a valid {field}. Brokers may silently "
                    "substitute a default for an unrecognised value rather than "
                    "reject the order.",
                    sorted(allowed),
                    value,
                )
            )

    for field in POSITIVE_NUMBER_FIELDS:
        if field not in data:
            continue
        value = data.get(field)
        if isinstance(value, str) and ("{{" in value or not value.strip()):
            continue
        allow_zero = node_type == "smartOrder" and field == "quantity"
        if not _valid_quantity(value, allow_zero=allow_zero):
            expectation = "a non-negative number" if allow_zero else "a positive number"
            message = (
                f"SmartOrder quantity must be a non-negative number; {value!r} "
                "cannot describe a target position."
                if allow_zero
                else f"{field} must be a positive number; {value!r} reaches the broker as a malformed order."
            )
            found.append(
                _err(
                    f"{base}/data/{field}",
                    "invalid_quantity",
                    message,
                    expectation,
                    value,
                )
            )

    if node_type in PRICED_ORDER_NODE_TYPES:
        found.extend(_priced_order_errors(f"{base}/data", data, strict))

    # An indicator's params must be the JSON string the executor parses. The
    # object form imports cleanly and then fails at run time on json.loads, so
    # the workflow looks valid right up until it runs.
    if node_type == "indicator" and "params" in data:
        params = data.get("params")
        if params is not None and not isinstance(params, str):
            found.append(
                _err(
                    f"{base}/data/params",
                    "invalid_params",
                    "params must be a JSON object written as a string, for "
                    'example "{\"period\": 14}". An object here is accepted by '
                    "import and then fails when the node runs.",
                    "a JSON object string",
                    params,
                )
            )

    if node_type == "orderUpdateTrigger":
        for field in ("orderId", "symbol"):
            value = data.get(field)
            if value is not None and not isinstance(value, str):
                found.append(
                    _err(
                        f"{base}/data/{field}",
                        "invalid_type",
                        f"orderUpdateTrigger {field} must be a string filter; "
                        f"{type(value).__name__} cannot match an order update.",
                        "string",
                        value,
                    )
                )
        status = data.get("status", "complete")
        if normalize_status(status) not in VALID_STATUSES:
            found.append(
                _err(
                    f"{base}/data/status",
                    "invalid_status",
                    f"orderUpdateTrigger status must be one of {sorted(VALID_STATUSES)}, "
                    f"got {status!r}",
                    sorted(VALID_STATUSES),
                    status,
                )
            )

    # httpRequest: the fields whose shape only failed at run time before.
    if node_type == "httpRequest":
        method = data.get("method")
        if isinstance(method, str) and method.strip() and "{{" not in method:
            if method.strip().upper() not in HTTP_METHODS:
                found.append(
                    _err(
                        f"{base}/data/method",
                        "invalid_method",
                        f"'{method}' is not a method this node can send. Only "
                        f"{', '.join(sorted(HTTP_METHODS))} are implemented.",
                        sorted(HTTP_METHODS),
                        method,
                    )
                )
        headers = data.get("headers")
        if isinstance(headers, str) and headers.strip() and "{{" not in headers:
            import json as _json

            try:
                parsed = _json.loads(headers)
            except ValueError:
                parsed = None
            if not isinstance(parsed, dict):
                found.append(
                    _err(
                        f"{base}/data/headers",
                        "invalid_headers",
                        "headers must be a JSON object written as a string, for "
                        'example "{\"Authorization\": \"Bearer x\"}". An '
                        "unparseable value is dropped and the request goes out "
                        "unauthenticated.",
                        "a JSON object string",
                        headers,
                    )
                )
        timeout = data.get("timeout")
        if timeout is not None and not (isinstance(timeout, str) and "{{" in timeout):
            try:
                milliseconds = float(timeout)
            except (TypeError, ValueError):
                milliseconds = None
            if (
                milliseconds is None
                or milliseconds < HTTP_TIMEOUT_MIN_MS
                or milliseconds > HTTP_TIMEOUT_MAX_MS
            ):
                # The lower bound matters as much as the upper one: a 1 ms
                # timeout is not a fast request, it is a request that can only
                # ever fail, and it reads as a deliberate setting.
                found.append(
                    _err(
                        f"{base}/data/timeout",
                        "invalid_timeout",
                        f"timeout is in milliseconds and must be between "
                        f"{HTTP_TIMEOUT_MIN_MS} and {HTTP_TIMEOUT_MAX_MS}. The "
                        "request blocks the workflow for its whole duration.",
                        f"{HTTP_TIMEOUT_MIN_MS}..{HTTP_TIMEOUT_MAX_MS}",
                        timeout,
                    )
                )
    return found


# Mirrors NodeExecutor.HTTP_TIMEOUT_MAX_MS; the executor clamps, the validator
# refuses, so an import cannot quietly ship a value the runtime will override.
HTTP_TIMEOUT_MAX_MS = 60_000
# A second is the shortest timeout that can describe a real remote call.
HTTP_TIMEOUT_MIN_MS = 1_000

# The methods execute_http_request actually implements. Anything else reached
# the node and returned "Unsupported method" at run time.
HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})


class WorkflowValidationError(Exception):
    """One or more structural problems, each with a path and a reason."""

    def __init__(self, errors: list[dict[str, Any]]):
        self.errors = errors
        super().__init__(f"{len(errors)} validation error(s)")


def _err(path: str, code: str, message: str, expected=None, received=None) -> dict[str, Any]:
    entry = {"path": path, "code": code, "message": message}
    if expected is not None:
        entry["expected"] = expected
    if received is not None:
        entry["received"] = received
    return entry


def validate_workflow(
    payload: Any, *, require_name: bool = True, strict: bool = True
) -> list[dict[str, Any]]:
    """Return a list of errors; empty means the workflow passes.

    Two levels, because the editor saves continuously while a graph is still
    being wired:

    * Always checked (structure) - shape, ids, known node types, edge endpoints,
      branch handles. A graph failing these cannot be rendered and is corrupt
      however incomplete the user\'s work is.
    * ``strict`` only (completeness) - required node fields, exactly one
      trigger, reachability, and cycles. Enforced at import and activation,
      where the workflow is presented as finished, and skipped on save so a
      half-built graph remains savable.
    """
    errors: list[dict[str, Any]] = []

    if not isinstance(payload, dict):
        return [
            _err(
                "/",
                "invalid_type",
                "Workflow must be a JSON object",
                "object",
                type(payload).__name__,
            )
        ]

    name = payload.get("name")
    if require_name and (not isinstance(name, str) or not name.strip()):
        errors.append(_err("/name", "required", "Workflow needs a non-empty name", "string", name))

    nodes = payload.get("nodes")
    edges = payload.get("edges")
    if not isinstance(nodes, list):
        errors.append(
            _err(
                "/nodes",
                "required",
                "Workflow needs a nodes array",
                "array",
                type(nodes).__name__ if nodes is not None else None,
            )
        )
        nodes = []
    if not isinstance(edges, list):
        errors.append(
            _err(
                "/edges",
                "required",
                "Workflow needs an edges array",
                "array",
                type(edges).__name__ if edges is not None else None,
            )
        )
        edges = []

    if len(nodes) > MAX_NODES:
        errors.append(
            _err(
                "/nodes",
                "too_large",
                f"Workflow has more than {MAX_NODES} nodes",
                MAX_NODES,
                len(nodes),
            )
        )
    if len(edges) > MAX_EDGES:
        errors.append(
            _err(
                "/edges",
                "too_large",
                f"Workflow has more than {MAX_EDGES} edges",
                MAX_EDGES,
                len(edges),
            )
        )

    node_ids: set[str] = set()
    triggers: list[str] = []

    for i, node in enumerate(nodes):
        base = f"/nodes/{i}"
        if not isinstance(node, dict):
            errors.append(
                _err(base, "invalid_type", "Node must be an object", "object", type(node).__name__)
            )
            continue

        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id.strip():
            errors.append(
                _err(
                    f"{base}/id", "required", "Node needs a non-empty string id", "string", node_id
                )
            )
        elif node_id in node_ids:
            errors.append(
                _err(
                    f"{base}/id",
                    "duplicate",
                    f"Duplicate node id '{node_id}'",
                    "unique id",
                    node_id,
                )
            )
        else:
            node_ids.add(node_id)

        node_type = node.get("type")
        if not isinstance(node_type, str) or not node_type:
            errors.append(
                _err(f"{base}/type", "required", "Node needs a type", "string", node_type)
            )
        elif node_type not in VALID_NODE_TYPES:
            errors.append(
                _err(
                    f"{base}/type",
                    "unknown_node_type",
                    f"'{node_type}' is not a Flow node type. Node types are "
                    "fixed; inventing one makes the workflow unrenderable.",
                    "one of the documented node types",
                    node_type,
                )
            )
        elif node_type in TRIGGER_NODE_TYPES:
            triggers.append(str(node_id))

        data = node.get("data")

        # Value-level checks run at every level, not just `strict`. A field that
        # is absent may simply not be wired yet, but a field holding an invalid
        # constant, a negative quantity or a malformed header is wrong however
        # incomplete the graph is -- and the editor saves through the non-strict
        # path, so gating these on `strict` let a save store exactly the node
        # the importer would have refused.
        if isinstance(data, dict) and isinstance(node_type, str):
            errors.extend(_enum_and_range_errors(base, node_type, data, strict))
            if node_type == "margin":
                errors.extend(_margin_errors(base, data, strict))
            elif node_type == "optionsMultiOrder":
                errors.extend(_options_multi_errors(base, data, strict))

        if strict and isinstance(data, dict) and isinstance(node_type, str):
            required = list(REQUIRED_NODE_FIELDS.get(node_type, ()))
            if node_type == "indicator":
                source_series = data.get("sourceSeries")
                if source_series is None or (
                    isinstance(source_series, str) and not source_series.strip()
                ):
                    required.extend(("symbol", "exchange"))
            elif node_type in {"optionSymbol", "optionChain"}:
                underlying = data.get("underlying")
                has_embedded_expiry = (
                    isinstance(underlying, str)
                    and "{{" not in underlying
                    and bool(underlying.strip())
                    and parse_underlying_symbol(underlying)[1] is not None
                )
                if not has_embedded_expiry and not (
                    isinstance(underlying, str) and "{{" in underlying
                ):
                    required.append("expiryDate")
            elif node_type == "syntheticFuture":
                required.append("expiryDate")
            elif node_type == "variable":
                operation = data.get("operation", "set")
                if isinstance(operation, str) and "{{" not in operation:
                    if operation in VALID_VARIABLE_OPERATIONS:
                        if operation in {"get", "stringify"}:
                            required.append("sourceVariable")
                        elif operation in {
                            "add",
                            "subtract",
                            "multiply",
                            "divide",
                            "parse_json",
                        }:
                            required.append("value")

            if node_type == "orderUpdateTrigger":
                order_id = data.get("orderId")
                symbol = data.get("symbol")
                has_order_id = isinstance(order_id, str) and bool(order_id.strip())
                has_symbol = isinstance(symbol, str) and bool(symbol.strip())
                if not has_order_id and not has_symbol:
                    errors.append(
                        _err(
                            f"{base}/data/orderId",
                            "missing_alternative",
                            "An orderUpdateTrigger needs an Order ID or a Symbol to watch.",
                            "a non-empty orderId or symbol",
                            None,
                        )
                    )
                elif isinstance(order_id, str) and "{{" in order_id:
                    errors.append(
                        _err(
                            f"{base}/data/orderId",
                            "invalid_trigger_filter",
                            "orderUpdateTrigger Order ID must be a literal order id, not a "
                            "{{variable}} reference.",
                            "a literal order id",
                            order_id,
                        )
                    )
            for selector, options in CONDITIONAL_REQUIRED_FIELDS.get(node_type, {}).items():
                chosen = _canonical_condition(data.get(selector, ""))
                if chosen and chosen not in options:
                    # An unrecognized condition can never evaluate true, so the
                    # trigger would sit registered and silently never fire.
                    errors.append(
                        _err(
                            f"{base}/data/{selector}",
                            "unknown_condition",
                            f"'{data.get(selector)}' is not a condition the price "
                            "monitor can evaluate, so this alert could never fire.",
                            sorted(options),
                            data.get(selector),
                        )
                    )
                required.extend(options.get(chosen, ()))
                errors.extend(_alert_threshold_errors(base, data, chosen, options.get(chosen, ())))
            for group in EITHER_REQUIRED_FIELDS.get(node_type, ()):
                if not any(
                    data.get(f) is not None
                    and not (isinstance(data.get(f), str) and not data.get(f).strip())
                    for f in group
                ):
                    errors.append(
                        _err(
                            f"{base}/data/{group[0]}",
                            "missing_required_field",
                            f"A {node_type} node needs {group[0]}. Without it the "
                            "check passes unconditionally, so whatever it guards "
                            "runs every time.",
                            group[0],
                            None,
                        )
                    )

            for field in required:
                value = data.get(field)
                if value is None or (isinstance(value, str) and not value.strip()):
                    errors.append(
                        _err(
                            f"{base}/data/{field}",
                            "missing_required_field",
                            f"A {node_type} node needs {field}. Without it the node "
                            "fails at run time, not at import.",
                            field,
                            value,
                        )
                    )
        if not isinstance(data, dict):
            errors.append(
                _err(
                    f"{base}/data",
                    "required",
                    "Node needs a data object",
                    "object",
                    type(node.get("data")).__name__ if node.get("data") is not None else None,
                )
            )

        position = node.get("position")
        if not isinstance(position, dict):
            errors.append(
                _err(
                    f"{base}/position",
                    "required",
                    "Node needs a position {x, y}",
                    "object",
                    type(position).__name__ if position is not None else None,
                )
            )
        else:
            for axis in ("x", "y"):
                if not isinstance(position.get(axis), (int, float)) or isinstance(
                    position.get(axis), bool
                ):
                    errors.append(
                        _err(
                            f"{base}/position/{axis}",
                            "invalid_type",
                            f"position.{axis} must be a number",
                            "number",
                            position.get(axis),
                        )
                    )

    edge_ids: set[str] = set()
    for i, edge in enumerate(edges):
        base = f"/edges/{i}"
        if not isinstance(edge, dict):
            errors.append(
                _err(base, "invalid_type", "Edge must be an object", "object", type(edge).__name__)
            )
            continue

        edge_id = edge.get("id")
        if not isinstance(edge_id, str) or not edge_id.strip():
            errors.append(
                _err(
                    f"{base}/id", "required", "Edge needs a non-empty string id", "string", edge_id
                )
            )
        elif edge_id in edge_ids:
            errors.append(
                _err(
                    f"{base}/id",
                    "duplicate",
                    f"Duplicate edge id '{edge_id}'",
                    "unique id",
                    edge_id,
                )
            )
        else:
            edge_ids.add(edge_id)

        for endpoint in ("source", "target"):
            value = edge.get(endpoint)
            if not isinstance(value, str) or not value:
                errors.append(
                    _err(
                        f"{base}/{endpoint}",
                        "required",
                        f"Edge needs a {endpoint} node id",
                        "string",
                        value,
                    )
                )
            elif node_ids and value not in node_ids:
                # A dangling edge renders as a broken connection and silently
                # drops whatever branch it was meant to carry.
                errors.append(
                    _err(
                        f"{base}/{endpoint}",
                        "dangling_edge",
                        f"Edge {endpoint} '{value}' is not a node in this workflow",
                        "an existing node id",
                        value,
                    )
                )

    node_types_by_id = {
        n.get("id"): n.get("type")
        for n in nodes
        if isinstance(n, dict) and isinstance(n.get("id"), str)
    }
    for i, edge in enumerate(edges):
        if not isinstance(edge, dict):
            continue
        handle = edge.get("sourceHandle")
        if handle is None or handle == "":
            continue  # an unconditional edge is legitimate
        source_type = node_types_by_id.get(edge.get("source"))
        if source_type in BRANCHING_NODE_TYPES and str(handle) not in _BRANCHING_HANDLES:
            errors.append(
                _err(
                    f"/edges/{i}/sourceHandle",
                    "invalid_source_handle",
                    f"'{handle}' is not a branch of a {source_type} node, so this edge "
                    "is never followed and its branch is silently dropped.",
                    sorted(_BRANCHING_HANDLES),
                    handle,
                )
            )
        elif source_type and source_type not in BRANCHING_NODE_TYPES:
            # Non-branching nodes render a single unnamed source handle, so any
            # named one is a phantom: the edge points at a socket that does not
            # exist and the branch it carries is silently dropped.
            errors.append(
                _err(
                    f"/edges/{i}/sourceHandle",
                    "invalid_source_handle",
                    f"A {source_type} node has no '{handle}' output handle; it emits a "
                    "single unconditional output.",
                    "no sourceHandle",
                    handle,
                )
            )

    # Gate input slots. `targetHandle: "input-N"` must name a slot the gate
    # actually has: a higher N is never filled, so the gate waits for an input
    # that can never arrive and its branch silently never fires.
    def _slot_count(value) -> int:
        """Gate input count, tolerant of a malformed value.

        Casting directly raised ValueError out of the validator, so a
        malformed payload crashed the request it was supposed to reject.
        """
        try:
            return max(int(value), 1) if value not in (None, "") else 2
        except (TypeError, ValueError):
            return 2

    gate_slots = {
        n.get("id"): _slot_count(n.get("data", {}).get("inputCount"))
        for n in nodes
        if isinstance(n, dict)
        and n.get("type") in ("andGate", "orGate")
        and isinstance(n.get("data"), dict)
    }
    for i, edge in enumerate(edges):
        if not isinstance(edge, dict):
            continue
        handle = edge.get("targetHandle")
        if handle is None or handle == "":
            continue
        slots = gate_slots.get(edge.get("target"))
        if slots is None:
            # Only gates render numbered input slots. Naming one on any other
            # node points the edge at a socket that does not exist.
            if re.fullmatch(r"input-\d+", str(handle)):
                target_type = node_types_by_id.get(edge.get("target"))
                errors.append(
                    _err(
                        f"/edges/{i}/targetHandle",
                        "invalid_target_handle",
                        f"Only gate nodes have numbered input slots; a "
                        f"{target_type or 'non-gate'} node has no '{handle}'.",
                        "no targetHandle",
                        handle,
                    )
                )
            continue
        match = re.fullmatch(r"input-(\d+)", str(handle))
        if not match or int(match.group(1)) >= slots:
            errors.append(
                _err(
                    f"/edges/{i}/targetHandle",
                    "invalid_target_handle",
                    f"'{handle}' is not an input slot on this gate, which has {slots}. "
                    "The gate would wait for an input that never arrives.",
                    [f"input-{n}" for n in range(slots)],
                    handle,
                )
            )

    if strict and not nodes:
        errors.append(
            _err(
                "/nodes",
                "no_trigger",
                "Workflow has no nodes, so it can never run.",
                "at least a trigger node",
                0,
            )
        )
    elif strict and nodes and not triggers:
        errors.append(
            _err(
                "/nodes",
                "no_trigger",
                "Workflow has no trigger node, so it can never run. Add one of: "
                + ", ".join(sorted(TRIGGER_NODE_TYPES)),
                "exactly one trigger",
                0,
            )
        )
    elif strict and len(triggers) > 1:
        # The executor walks from the first trigger it finds; the rest of the
        # graph never executes and nothing reports why.
        errors.append(
            _err(
                "/nodes",
                "multiple_triggers",
                "Workflow has more than one trigger. Only the first would run and "
                "everything downstream of the others would be silently skipped.",
                "exactly one trigger",
                triggers,
            )
        )

    # Only meaningful once ids and endpoints are sound.
    if strict and not errors:
        errors.extend(_graph_errors(nodes, edges, node_ids, triggers))

    return errors


def _graph_errors(nodes: list, edges: list, node_ids: set[str], triggers: list[str]) -> list[dict]:
    """Cycles and nodes the trigger can never reach."""
    errors: list[dict] = []
    adjacency: dict[str, list[str]] = {nid: [] for nid in node_ids}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        src, dst = edge.get("source"), edge.get("target")
        if src in adjacency and dst in node_ids:
            adjacency[src].append(dst)

    # Cycle detection. The executor caps depth and visits rather than detecting
    # a loop, so a cycle burns the whole budget and truncates the run instead of
    # reporting anything.
    WHITE, GREY, BLACK = 0, 1, 2
    colour = dict.fromkeys(node_ids, WHITE)
    cycle: list[str] = []

    def visit(node: str, path: list[str]) -> bool:
        colour[node] = GREY
        for nxt in adjacency.get(node, ()):
            if colour[nxt] == GREY:
                cycle.extend(path[path.index(nxt) :] + [nxt] if nxt in path else [nxt])
                return True
            if colour[nxt] == WHITE and visit(nxt, path + [nxt]):
                return True
        colour[node] = BLACK
        return False

    for nid in node_ids:
        if colour[nid] == WHITE and visit(nid, [nid]):
            errors.append(
                _err(
                    "/edges",
                    "cycle",
                    "The graph contains a cycle, which runs until the executor's "
                    "visit limit and then truncates rather than reporting a loop: "
                    + " -> ".join(cycle[:6]),
                    "an acyclic graph",
                    cycle[:6],
                )
            )
            break

    # Reachability from the trigger. A node the trigger cannot reach never runs,
    # and nothing at run time says so.
    if triggers:
        seen: set[str] = set()
        stack = list(triggers)
        while stack:
            nid = stack.pop()
            if nid in seen:
                continue
            seen.add(nid)
            stack.extend(adjacency.get(nid, ()))
        # `group` is a visual container with no execution behaviour, so it is
        # legitimately unconnected while the nodes drawn inside it run through
        # their own edges.
        decorative = {
            n.get("id")
            for n in nodes
            if isinstance(n, dict) and n.get("type") in DECORATIVE_NODE_TYPES
        }
        unreachable = sorted(node_ids - seen - decorative)
        if unreachable:
            errors.append(
                _err(
                    "/nodes",
                    "unreachable",
                    "These nodes cannot be reached from the trigger and will never "
                    "run: " + ", ".join(unreachable[:8]),
                    "every node reachable from the trigger",
                    unreachable[:8],
                )
            )
    return errors


def assert_valid_workflow(payload: Any, *, require_name: bool = True, strict: bool = True) -> None:
    """Raise WorkflowValidationError when the workflow does not pass."""
    errors = validate_workflow(payload, require_name=require_name, strict=strict)
    if errors:
        raise WorkflowValidationError(errors)


# Legacy node payloads, and the canonical shape they map to. Applied at import
# so the stored workflow is correct, rather than relying on every reader to
# remember the old spelling forever.
def migrate_legacy_node_data(nodes: list) -> tuple[list, list[str]]:
    """Upgrade legacy node payloads. Returns (nodes, human-readable notes)."""
    notes: list[str] = []
    if not isinstance(nodes, list):
        return nodes, notes

    migrated = []
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("data"), dict):
            migrated.append(node)
            continue
        node_type = node.get("type")
        data = dict(node["data"])

        if node_type == "fundCheck" and "minAvailable" not in data and "threshold" in data:
            # fundCheck can only express "at least this much". A legacy
            # greater-than maps cleanly; a legacy less-than means the opposite,
            # and silently reversing a capital guard is worse than refusing to
            # guess, so that one is left for the user to restate.
            operator = str(data.get("operator") or "gt").strip().lower()
            if operator in ("gt", "gte", "ge", ">", ">="):
                data["minAvailable"] = data.pop("threshold")
                data.pop("operator", None)
                notes.append(
                    f"fundCheck '{node.get('id')}': threshold -> minAvailable "
                    f"({data['minAvailable']})"
                )
            else:
                notes.append(
                    f"fundCheck '{node.get('id')}': operator '{operator}' has no "
                    "equivalent - this node only supports a minimum. Left unchanged; "
                    "set Minimum Available yourself."
                )
        elif node_type == "positionCheck" and "condition" not in data and "operator" in data:
            # Preserve the comparison instead of flattening every legacy operator
            # to "exists", which would turn a quantity-based exit into an
            # unconditional one.
            operator = str(data.get("operator") or "").strip().lower()
            mapping = {
                "gt": "quantity_above",
                ">": "quantity_above",
                "gte": "quantity_above",
                "ge": "quantity_above",
                ">=": "quantity_above",
                "lt": "quantity_below",
                "<": "quantity_below",
                "lte": "quantity_below",
                "le": "quantity_below",
                "<=": "quantity_below",
            }
            condition = mapping.get(operator)
            if condition:
                data["condition"] = condition
                data.pop("operator", None)
                notes.append(
                    f"positionCheck '{node.get('id')}': operator '{operator}' -> "
                    f"condition '{condition}' (threshold kept)"
                )
            else:
                notes.append(
                    f"positionCheck '{node.get('id')}': operator '{operator}' has no "
                    "equivalent condition. Left unchanged; set the condition yourself."
                )
        elif node_type == "priceCondition" and "value" not in data and "threshold" in data:
            data["value"] = data.pop("threshold")
            notes.append(f"priceCondition '{node.get('id')}': threshold -> value")

        migrated.append({**node, "data": data})
    return migrated, notes


# Trigger fields that are registered with the scheduler or a monitor at
# activation rather than read per run. A change to any of them needs a
# deactivate/reactivate cycle, which comparing node *types* alone would miss:
# editing an interval from 1m to 5m keeps the same trigger type.
TRIGGER_CONFIG_FIELDS: tuple[str, ...] = (
    # start
    "scheduleType",
    "time",
    "days",
    "executeAt",
    "intervalMinutes",
    "intervalValue",
    "intervalUnit",
    "marketHoursOnly",
    # priceAlert - every field add_alert() captures, including the channel
    # bounds and percentage that only some conditions use
    "symbol",
    "exchange",
    "condition",
    "price",
    "priceLower",
    "priceUpper",
    "percentage",
    "expiration",
    # orderUpdateTrigger
    "orderId",
    "status",
    # shared
    "trigger",
)


def trigger_config(nodes: list) -> dict:
    """The activation-relevant configuration of a graph's trigger node(s).

    Two graphs with equal trigger_config can be swapped under a running
    workflow; anything else needs the workflow reactivated so the scheduler and
    monitors pick the change up.
    """
    config: dict = {}
    if not isinstance(nodes, list):
        return config
    for node in nodes:
        if not isinstance(node, dict) or node.get("type") not in TRIGGER_NODE_TYPES:
            continue
        data = node.get("data") or {}
        if not isinstance(data, dict):
            continue
        config[str(node.get("type"))] = {
            field: data.get(field) for field in TRIGGER_CONFIG_FIELDS if field in data
        }
    return config
