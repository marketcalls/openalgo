"""Database-backed configuration for the `/agent` module.

Every agent setting lives in the `ag_setting` table and is read and written
through :mod:`database.agent_db`. **This module never reads the process
environment.** The build contract puts provider, model, credential and policy
configuration in the database precisely so an operator can change it from the UI
without editing `.env` and restarting, and so a setting cannot end up silently
different between the Gunicorn worker, a strategy subprocess and a test.

Caching
-------

The order guard reads the limits on every order, so reads are served from a
short-lived `TTLCache`. Every writer here invalidates that cache in a `finally`
block, which is not defensive tidiness: `database/flow_db.py` carries the scar.
Its webhook-secret rotation was the one mutator that did not evict the cache, so
for the whole five-minute TTL the rotated-out secret kept authenticating and the
new one was rejected - the revocation did nothing at exactly the moment it
mattered. The same shape here would let an operator switch `trading_enabled`
off and have the agent keep placing orders until the TTL expired.

Two further consequences of that lesson are built in:

* The cache holds an immutable `MappingProxyType` snapshot of the raw rows, never
  an ORM instance. A cached instance belongs to a `scoped_session` that is
  removed at teardown, so the next read inside the TTL raises
  `DetachedInstanceError` on the first attribute access.
* The safety-critical accessors default to `fresh=True` and pay one indexed read
  per order rather than trusting a snapshot. Only the cosmetic ones (the system
  prompt, the reasoning effort) are served from cache by default.

A failed read returns the defaults rather than raising, and the defaults are the
safe end of every switch: `trading_enabled` is off and `require_analyzer_mode`
is on. A database that cannot be read must not be a database that trades.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import Any

from cachetools import TTLCache

from utils import real_threading
from utils.constants import VALID_EXCHANGES, VALID_PRODUCT_TYPES
from utils.logging import get_logger

logger = get_logger(__name__)

# services/agent/settings.py -> services/agent -> services -> repository root.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Presence of this file halts every mutating agent tool. The switch has two
# forms because they fail differently: the `kill_switch` row is what the UI
# toggles, and this file is what an operator can `touch` when the UI is
# unreachable, the database is locked, or the process is wedged. Either one
# engages it.
DEFAULT_KILL_SWITCH_FILE = str(PROJECT_ROOT / "agent_kill_switch")

# Index exchanges are quote-only, so they are not offered as order destinations.
TRADABLE_EXCHANGES: frozenset[str] = frozenset(
    exchange for exchange in VALID_EXCHANGES if not exchange.endswith("_INDEX")
)

REASONING_EFFORTS: frozenset[str] = frozenset({"off", "low", "medium", "high"})

# Money is Numeric(18,2) everywhere in this project, so a money-valued setting is
# quantised to paise before it is stored and after it is read.
MONEY_QUANTUM = Decimal("0.01")

# The stored key names. Four of them mirror the constants in
# `database.agent_db` (`SETTING_TRADING_ENABLED`, `SETTING_SYSTEM_PROMPT`,
# `SETTING_DEFAULT_REASONING_EFFORT`, `SETTING_KILL_SWITCH`) and are repeated as
# literals rather than imported, because importing `database.agent_db` here
# would build a database engine the moment anything reads a setting name.
KEY_TRADING_ENABLED = "trading_enabled"
KEY_REQUIRE_ANALYZER_MODE = "require_analyzer_mode"
KEY_SYSTEM_PROMPT_OVERRIDE = "system_prompt"
KEY_DEFAULT_REASONING_EFFORT = "default_reasoning_effort"
KEY_KILL_SWITCH = "kill_switch"
KEY_MAX_ORDERS_PER_SESSION = "max_orders_per_session"
KEY_MAX_ORDER_QUANTITY = "max_order_quantity"
KEY_MAX_ORDER_VALUE = "max_order_value"
KEY_MAX_PRICE_DEVIATION_PCT = "max_price_deviation_pct"
KEY_DUPLICATE_ORDER_WINDOW_SECONDS = "duplicate_order_window_seconds"
KEY_ALLOWED_EXCHANGES = "allowed_exchanges"
KEY_ALLOWED_PRODUCTS = "allowed_products"
KEY_SYMBOL_ALLOWLIST = "symbol_allowlist"
KEY_SYMBOL_BLOCKLIST = "symbol_blocklist"
KEY_MAX_FUNDS_UTILIZATION_PCT = "max_funds_utilization_pct"
KEY_ALLOW_BULK_DESTRUCTIVE = "allow_bulk_destructive"
KEY_KILL_SWITCH_FILE = "kill_switch_file"


@dataclass(frozen=True)
class _Field:
    """One row of the settings schema.

    Attributes:
        kind: How the stored text is parsed. One of ``bool``, ``int``,
            ``money``, ``percent``, ``text``, ``enum``, ``set``.
        default: The value returned when the row is absent or unparseable.
        minimum: Inclusive lower bound for ``int``, ``money`` and ``percent``.
        maximum: Inclusive upper bound for the same kinds, or ``None``.
        choices: Permitted values for ``enum``.
    """

    kind: str
    default: Any
    minimum: Any = None
    maximum: Any = None
    choices: frozenset[str] | None = None


_SPEC: Mapping[str, _Field] = MappingProxyType(
    {
        # The master switch. Off by default: a fresh install must not be able to
        # send a live order because somebody opened /agent and typed a sentence.
        KEY_TRADING_ENABLED: _Field("bool", False),
        # On by default for the same reason. Turning it off is the operator
        # saying, in the database, that the agent may reach the real broker.
        KEY_REQUIRE_ANALYZER_MODE: _Field("bool", True),
        KEY_SYSTEM_PROMPT_OVERRIDE: _Field("text", ""),
        KEY_DEFAULT_REASONING_EFFORT: _Field("enum", "off", choices=REASONING_EFFORTS),
        KEY_MAX_ORDERS_PER_SESSION: _Field("int", 20, minimum=0),
        KEY_MAX_ORDER_QUANTITY: _Field("int", 10000, minimum=0),
        KEY_MAX_ORDER_VALUE: _Field("money", Decimal("500000.00"), minimum=Decimal("0")),
        KEY_MAX_PRICE_DEVIATION_PCT: _Field(
            "percent", Decimal("5"), minimum=Decimal("0"), maximum=Decimal("100")
        ),
        KEY_DUPLICATE_ORDER_WINDOW_SECONDS: _Field("int", 10, minimum=0),
        KEY_ALLOWED_EXCHANGES: _Field("set", TRADABLE_EXCHANGES),
        KEY_ALLOWED_PRODUCTS: _Field("set", frozenset(VALID_PRODUCT_TYPES)),
        # Empty allowlist means "every symbol", which is the only sane default
        # for a platform whose symbol master runs to hundreds of thousands of
        # rows. The blocklist is the targeted tool.
        KEY_SYMBOL_ALLOWLIST: _Field("set", frozenset()),
        KEY_SYMBOL_BLOCKLIST: _Field("set", frozenset()),
        KEY_MAX_FUNDS_UTILIZATION_PCT: _Field(
            "percent", Decimal("100"), minimum=Decimal("0"), maximum=Decimal("100")
        ),
        KEY_ALLOW_BULK_DESTRUCTIVE: _Field("bool", False),
        KEY_KILL_SWITCH: _Field("bool", False),
        KEY_KILL_SWITCH_FILE: _Field("text", DEFAULT_KILL_SWITCH_FILE),
    }
)

SETTING_KEYS: tuple[str, ...] = tuple(_SPEC)

_TRUE_TOKENS = frozenset({"1", "true", "t", "yes", "y", "on", "enabled"})
_FALSE_TOKENS = frozenset({"0", "false", "f", "no", "n", "off", "disabled"})

# 30 seconds is long enough to absorb the read burst of a single agent turn and
# short enough that a change made outside this process (a migration, a second
# instance, a manual UPDATE) is picked up without a restart.
_settings_cache: TTLCache = TTLCache(maxsize=2, ttl=30)
_CACHE_KEY = "ag_setting"

# A real lock, not a green one. The agent runs its tools on a real OS thread
# (see the eventlet rules in CLAUDE.md) while the blueprint writes settings from
# a greenlet, so both worlds touch this cache. The critical section is a single
# dictionary assignment; every database read happens outside it.
_cache_lock = real_threading.RLock()

_EMPTY: Mapping[str, Any] = MappingProxyType({})


@dataclass(frozen=True)
class RiskLimits:
    """An immutable snapshot of every limit the order guard enforces.

    The guard takes one of these per check. Passing an explicit instance is what
    lets `services/agent/safety/risk.py` be exercised with no database, no
    broker and no Flask app: nothing in the guard reads configuration except
    through this object.

    Attributes:
        trading_enabled: Master switch for every mutating tool.
        require_analyzer_mode: Whether orders are only permitted while the
            platform-wide analyzer (sandbox) toggle is on.
        max_orders_per_session: Orders one agent session may claim. 0 blocks all.
        max_order_quantity: Largest quantity a single order may carry.
        max_order_value: Largest notional a single order may carry, in rupees.
        max_price_deviation_pct: How far a limit or stop price may sit from the
            last traded price before the order is refused.
        duplicate_order_window_seconds: Window in which an identical order is
            treated as a duplicate.
        allowed_exchanges: Exchanges orders may be sent to.
        allowed_products: Product types orders may use.
        symbol_allowlist: When non-empty, the only symbols that may be traded.
        symbol_blocklist: Symbols that may never be traded.
        max_funds_utilization_pct: Share of available funds a single order (or
            one basket) may consume.
        allow_bulk_destructive: Whether account-wide destructive operations
            (cancel every order, close every position) are permitted.
        kill_switch_engaged: The stored kill-switch flag, set from the UI.
        kill_switch_file: Path whose existence also engages the kill switch.
    """

    trading_enabled: bool
    require_analyzer_mode: bool
    max_orders_per_session: int
    max_order_quantity: int
    max_order_value: Decimal
    max_price_deviation_pct: Decimal
    duplicate_order_window_seconds: int
    allowed_exchanges: frozenset[str]
    allowed_products: frozenset[str]
    symbol_allowlist: frozenset[str]
    symbol_blocklist: frozenset[str]
    max_funds_utilization_pct: Decimal
    allow_bulk_destructive: bool
    kill_switch_engaged: bool
    kill_switch_file: str

    @property
    def kill_switch_path(self) -> Path:
        """The kill-switch file as an absolute path.

        A relative setting resolves against the repository root so a value typed
        into the UI means the same thing whatever the process working directory
        happens to be.

        Returns:
            The absolute path whose existence engages the kill switch.
        """
        path = Path(self.kill_switch_file).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path

    def as_dict(self) -> dict[str, Any]:
        """Render the limits as JSON-safe primitives.

        Returns:
            A dictionary with sets rendered as sorted lists and decimals as
            strings, suitable for an HTTP response or an audit row.
        """
        return {
            KEY_TRADING_ENABLED: self.trading_enabled,
            KEY_REQUIRE_ANALYZER_MODE: self.require_analyzer_mode,
            KEY_MAX_ORDERS_PER_SESSION: self.max_orders_per_session,
            KEY_MAX_ORDER_QUANTITY: self.max_order_quantity,
            KEY_MAX_ORDER_VALUE: str(self.max_order_value),
            KEY_MAX_PRICE_DEVIATION_PCT: str(self.max_price_deviation_pct),
            KEY_DUPLICATE_ORDER_WINDOW_SECONDS: self.duplicate_order_window_seconds,
            KEY_ALLOWED_EXCHANGES: sorted(self.allowed_exchanges),
            KEY_ALLOWED_PRODUCTS: sorted(self.allowed_products),
            KEY_SYMBOL_ALLOWLIST: sorted(self.symbol_allowlist),
            KEY_SYMBOL_BLOCKLIST: sorted(self.symbol_blocklist),
            KEY_MAX_FUNDS_UTILIZATION_PCT: str(self.max_funds_utilization_pct),
            KEY_ALLOW_BULK_DESTRUCTIVE: self.allow_bulk_destructive,
            KEY_KILL_SWITCH: self.kill_switch_engaged,
            KEY_KILL_SWITCH_FILE: self.kill_switch_file,
        }


def _to_bool(raw: Any, default: bool, key: str, strict: bool) -> bool:
    """Parse a stored boolean."""
    if isinstance(raw, bool):
        return raw
    token = str(raw).strip().lower()
    if token in _TRUE_TOKENS:
        return True
    if token in _FALSE_TOKENS:
        return False
    if strict:
        raise ValueError(f"{key} must be a boolean, got {raw!r}")
    logger.warning("Agent setting %s holds an unparseable boolean %r; using %s", key, raw, default)
    return default


def _to_int(raw: Any, field: _Field, key: str, strict: bool) -> int:
    """Parse a stored integer and apply its bounds."""
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        if strict:
            raise ValueError(f"{key} must be a whole number, got {raw!r}") from None
        logger.warning(
            "Agent setting %s holds an unparseable integer %r; using %s", key, raw, field.default
        )
        return int(field.default)
    if field.minimum is not None and value < field.minimum:
        if strict:
            raise ValueError(f"{key} must be at least {field.minimum}, got {value}")
        return int(field.minimum)
    if field.maximum is not None and value > field.maximum:
        if strict:
            raise ValueError(f"{key} must be at most {field.maximum}, got {value}")
        return int(field.maximum)
    return value


def _to_decimal(raw: Any, field: _Field, key: str, strict: bool) -> Decimal:
    """Parse a stored decimal, quantising money to paise and applying bounds."""
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, TypeError, ValueError):
        if strict:
            raise ValueError(f"{key} must be a number, got {raw!r}") from None
        logger.warning(
            "Agent setting %s holds an unparseable number %r; using %s", key, raw, field.default
        )
        return Decimal(field.default)
    if not value.is_finite():
        if strict:
            raise ValueError(f"{key} must be a finite number, got {raw!r}")
        return Decimal(field.default)
    if field.kind == "money":
        value = value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    if field.minimum is not None and value < field.minimum:
        if strict:
            raise ValueError(f"{key} must be at least {field.minimum}, got {value}")
        return Decimal(field.minimum)
    if field.maximum is not None and value > field.maximum:
        if strict:
            raise ValueError(f"{key} must be at most {field.maximum}, got {value}")
        return Decimal(field.maximum)
    return value


def _to_set(raw: Any, field: _Field, key: str, strict: bool) -> frozenset[str]:
    """Parse a stored set of upper-cased tokens.

    Accepts a JSON array, a comma-separated string, or any iterable of strings,
    because all three reach this module: JSON from the store, a comma-separated
    string from a hand-edited row, and a Python list from the HTTP layer.
    """
    items: Iterable[Any]
    if raw is None:
        return frozenset(field.default)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return frozenset()
        if text.startswith("["):
            try:
                decoded = json.loads(text)
            except json.JSONDecodeError:
                if strict:
                    raise ValueError(
                        f"{key} must be a JSON array or a comma-separated list"
                    ) from None
                logger.warning(
                    "Agent setting %s holds invalid JSON %r; using its default", key, raw
                )
                return frozenset(field.default)
            if not isinstance(decoded, list):
                if strict:
                    raise ValueError(f"{key} must be a JSON array")
                return frozenset(field.default)
            items = decoded
        else:
            items = text.split(",")
    elif isinstance(raw, Iterable):
        items = raw
    else:
        if strict:
            raise ValueError(f"{key} must be a list of strings, got {raw!r}")
        return frozenset(field.default)
    return frozenset(str(item).strip().upper() for item in items if str(item).strip())


def _parse(key: str, field: _Field, raw: Any, *, strict: bool) -> Any:
    """Turn a stored value into its typed form.

    Args:
        key: The setting key, used only in messages.
        field: The schema entry for that key.
        raw: The stored text, or a caller-supplied value on a write.
        strict: True on a write, where a bad value must raise so the HTTP layer
            can answer 400. False on a read, where a corrupt row must degrade to
            the default rather than take the order guard down with it.

    Returns:
        The typed value.

    Raises:
        ValueError: When ``strict`` is set and the value cannot be used.
    """
    if raw is None:
        return field.default
    match field.kind:
        case "bool":
            return _to_bool(raw, bool(field.default), key, strict)
        case "int":
            return _to_int(raw, field, key, strict)
        case "money" | "percent":
            return _to_decimal(raw, field, key, strict)
        case "set":
            return _to_set(raw, field, key, strict)
        case "enum":
            token = str(raw).strip().lower()
            choices = field.choices or frozenset()
            if token in choices:
                return token
            if strict:
                raise ValueError(f"{key} must be one of {', '.join(sorted(choices))}, got {raw!r}")
            logger.warning(
                "Agent setting %s holds an unknown value %r; using %s", key, raw, field.default
            )
            return field.default
        case _:
            return str(raw)


def _serialise(field: _Field, value: Any) -> str:
    """Render a typed value as the text stored in `ag_setting.value`."""
    match field.kind:
        case "bool":
            return "true" if value else "false"
        case "int":
            return str(int(value))
        case "money" | "percent":
            return str(value)
        case "set":
            return json.dumps(sorted(value))
        case _:
            return str(value)


def _coerce_rows(raw: Any) -> dict[str, Any]:
    """Normalise whatever the store hands back into a plain key/value mapping.

    The store may return a mapping or a sequence of rows carrying ``key`` and
    ``value`` attributes. Both are accepted so a change of shape in
    :mod:`database.agent_db` cannot silently reset every setting to its default.
    """
    if raw is None:
        return {}
    if isinstance(raw, Mapping):
        return {str(key): value for key, value in raw.items()}
    rows: dict[str, Any] = {}
    for row in raw:
        key = getattr(row, "key", None)
        if key is None:
            continue
        rows[str(key)] = getattr(row, "value", None)
    return rows


def _load_all(*, fresh: bool = False) -> Mapping[str, Any]:
    """Read every setting row, cached unless ``fresh`` is set.

    Args:
        fresh: Bypass the cache and read the database.

    Returns:
        A read-only mapping of key to raw stored value. Empty when the store
        cannot be read, which makes every accessor fall back to its default.
    """
    if not fresh:
        with _cache_lock:
            cached = _settings_cache.get(_CACHE_KEY)
        if cached is not None:
            return cached

    try:
        from database import agent_db

        snapshot: Mapping[str, Any] = MappingProxyType(_coerce_rows(agent_db.get_all_settings()))
    except Exception:
        # Deliberately not cached: a transient failure must not pin the defaults
        # in place for the whole TTL. Every default is the safe end of its
        # switch, so the agent degrades to "cannot trade" rather than to
        # "unconstrained".
        logger.exception("Agent settings could not be read; falling back to defaults")
        return _EMPTY

    with _cache_lock:
        _settings_cache[_CACHE_KEY] = snapshot
    return snapshot


def invalidate_cache() -> None:
    """Drop the cached settings snapshot.

    Called by every writer in this module, in a ``finally`` block, and exposed
    so a migration or an out-of-band writer can force the next read to hit the
    database.
    """
    with _cache_lock:
        _settings_cache.clear()


def _typed(values: Mapping[str, Any], key: str) -> Any:
    """Return one setting in its typed form, tolerating a corrupt row."""
    field = _SPEC[key]
    return _parse(key, field, values.get(key), strict=False)


def get_setting_defaults() -> dict[str, Any]:
    """Return the typed default for every setting.

    Returns:
        A mapping of setting key to its default value, with no database access.
    """
    return {key: field.default for key, field in _SPEC.items()}


def is_trading_enabled(*, fresh: bool = True) -> bool:
    """Whether mutating agent tools may run at all.

    Args:
        fresh: Read past the cache. True by default: this is the master switch
            and an operator turning it off expects the next order to be refused,
            not the one after the TTL expires.

    Returns:
        True when trading is enabled. False on any read failure.
    """
    return bool(_typed(_load_all(fresh=fresh), KEY_TRADING_ENABLED))


def requires_analyzer_mode(*, fresh: bool = True) -> bool:
    """Whether orders are confined to analyzer (sandbox) mode.

    Args:
        fresh: Read past the cache. True by default, for the same reason as
            :func:`is_trading_enabled`.

    Returns:
        True when the agent may only trade while the platform-wide analyzer
        toggle is on. True on any read failure.
    """
    return bool(_typed(_load_all(fresh=fresh), KEY_REQUIRE_ANALYZER_MODE))


def is_kill_switch_engaged(*, fresh: bool = True) -> bool:
    """Whether the stored kill-switch flag is set.

    This is only half the switch. The other half is the kill-switch file, which
    the order guard tests as well, so an operator can stop the agent without a
    working UI. Use :func:`get_risk_limits` and let the guard test both.

    Args:
        fresh: Read past the cache. True by default.

    Returns:
        True when the flag is set. False on any read failure, because the file
        half of the switch is the one that answers when the database cannot.
    """
    return bool(_typed(_load_all(fresh=fresh), KEY_KILL_SWITCH))


def get_system_prompt_override(*, fresh: bool = False) -> str | None:
    """The operator's replacement system prompt.

    Args:
        fresh: Read past the cache.

    Returns:
        The override text, or None when the operator has not set one. Whitespace
        only counts as not set, so clearing the textarea in the UI restores the
        built-in prompt.
    """
    text = str(_typed(_load_all(fresh=fresh), KEY_SYSTEM_PROMPT_OVERRIDE) or "").strip()
    return text or None


def get_default_reasoning_effort(*, fresh: bool = False) -> str:
    """The reasoning effort applied when a request does not name one.

    Args:
        fresh: Read past the cache.

    Returns:
        One of ``off``, ``low``, ``medium``, ``high``.
    """
    return str(_typed(_load_all(fresh=fresh), KEY_DEFAULT_REASONING_EFFORT))


def get_max_orders_per_session(*, fresh: bool = True) -> int:
    """How many orders one agent session may claim.

    Args:
        fresh: Read past the cache.

    Returns:
        The cap. Zero blocks every order.
    """
    return int(_typed(_load_all(fresh=fresh), KEY_MAX_ORDERS_PER_SESSION))


def _limits_from(typed: Mapping[str, Any]) -> RiskLimits:
    """Assemble a :class:`RiskLimits` from already-typed setting values."""
    return RiskLimits(
        trading_enabled=bool(typed[KEY_TRADING_ENABLED]),
        require_analyzer_mode=bool(typed[KEY_REQUIRE_ANALYZER_MODE]),
        max_orders_per_session=int(typed[KEY_MAX_ORDERS_PER_SESSION]),
        max_order_quantity=int(typed[KEY_MAX_ORDER_QUANTITY]),
        max_order_value=Decimal(typed[KEY_MAX_ORDER_VALUE]),
        max_price_deviation_pct=Decimal(typed[KEY_MAX_PRICE_DEVIATION_PCT]),
        duplicate_order_window_seconds=int(typed[KEY_DUPLICATE_ORDER_WINDOW_SECONDS]),
        allowed_exchanges=frozenset(typed[KEY_ALLOWED_EXCHANGES]),
        allowed_products=frozenset(typed[KEY_ALLOWED_PRODUCTS]),
        symbol_allowlist=frozenset(typed[KEY_SYMBOL_ALLOWLIST]),
        symbol_blocklist=frozenset(typed[KEY_SYMBOL_BLOCKLIST]),
        max_funds_utilization_pct=Decimal(typed[KEY_MAX_FUNDS_UTILIZATION_PCT]),
        allow_bulk_destructive=bool(typed[KEY_ALLOW_BULK_DESTRUCTIVE]),
        kill_switch_engaged=bool(typed[KEY_KILL_SWITCH]),
        kill_switch_file=str(typed[KEY_KILL_SWITCH_FILE]),
    )


def get_risk_limits(*, fresh: bool = True) -> RiskLimits:
    """Build the limit snapshot the order guard checks against.

    Args:
        fresh: Read past the cache. True by default: the guard runs once per
            human-approved order, so the cost of an indexed read is irrelevant
            beside the cost of enforcing a limit the operator has already
            changed.

    Returns:
        A fully populated :class:`RiskLimits`. Never raises; an unreadable store
        yields the defaults, which refuse to trade.
    """
    values = _load_all(fresh=fresh)
    return _limits_from({key: _typed(values, key) for key in _SPEC})


def default_risk_limits() -> RiskLimits:
    """Return the limits with no database access.

    Useful for tests and for any caller that wants the shipped policy rather
    than the operator's.

    Returns:
        A :class:`RiskLimits` built entirely from the schema defaults.
    """
    return _limits_from(get_setting_defaults())


def get_all(*, fresh: bool = False) -> dict[str, Any]:
    """Every setting in JSON-safe form, for `GET /agent/api/settings`.

    Args:
        fresh: Read past the cache.

    Returns:
        A mapping of key to value, with decimals as strings and sets as sorted
        lists. `system_prompt` is None rather than an empty string when it is
        unset.
    """
    values = _load_all(fresh=fresh)
    payload: dict[str, Any] = {}
    for key, field in _SPEC.items():
        value = _parse(key, field, values.get(key), strict=False)
        match field.kind:
            case "money" | "percent":
                payload[key] = str(value)
            case "set":
                payload[key] = sorted(value)
            case _:
                payload[key] = value
    payload[KEY_SYSTEM_PROMPT_OVERRIDE] = (
        str(payload[KEY_SYSTEM_PROMPT_OVERRIDE] or "").strip() or None
    )
    return payload


def update(values: Mapping[str, Any]) -> dict[str, Any]:
    """Persist a partial settings update.

    Every value is parsed and validated before anything is written, so a request
    carrying one bad field changes nothing at all.

    Args:
        values: Mapping of setting key to new value. Unknown keys are rejected
            rather than ignored, because a typo that silently does nothing is
            indistinguishable from a limit that was never applied.

    Returns:
        The full settings payload after the write, as :func:`get_all` renders it.

    Raises:
        ValueError: When a key is unknown or a value cannot be used.
        Exception: Whatever the store raises when the write fails.
    """
    unknown = sorted(set(values) - set(_SPEC))
    if unknown:
        raise ValueError(f"Unknown agent setting(s): {', '.join(unknown)}")

    prepared = {
        key: _serialise(_SPEC[key], _parse(key, _SPEC[key], raw, strict=True))
        for key, raw in values.items()
    }

    try:
        from database import agent_db

        # set_setting logs and swallows its own failures and reports them as a
        # False return, so a caller that ignored the return value would tell an
        # operator their limit was saved when it was not.
        failed = [key for key, text in prepared.items() if not agent_db.set_setting(key, text)]
        if failed:
            raise RuntimeError(f"Could not persist agent setting(s): {', '.join(sorted(failed))}")
    except Exception:
        logger.exception("Failed to persist agent settings: %s", ", ".join(sorted(prepared)))
        raise
    finally:
        # In the finally block on purpose. A write that raised part-way through
        # has still changed some rows, and a cache holding the pre-write values
        # would keep serving them until the TTL expired.
        invalidate_cache()

    logger.info("Agent settings updated: %s", ", ".join(sorted(prepared)))
    return get_all(fresh=True)


def set_trading_enabled(enabled: bool) -> bool:
    """Turn the master trading switch on or off.

    Args:
        enabled: True to allow mutating tools to run.

    Returns:
        The persisted value.
    """
    return bool(update({KEY_TRADING_ENABLED: enabled})[KEY_TRADING_ENABLED])


def set_require_analyzer_mode(required: bool) -> bool:
    """Set whether the agent may only trade in analyzer mode.

    Args:
        required: True to confine the agent to the sandbox.

    Returns:
        The persisted value.
    """
    return bool(update({KEY_REQUIRE_ANALYZER_MODE: required})[KEY_REQUIRE_ANALYZER_MODE])


def set_kill_switch(engaged: bool) -> bool:
    """Engage or release the stored kill switch.

    Args:
        engaged: True to refuse every mutating tool call.

    Returns:
        The persisted value.
    """
    return bool(update({KEY_KILL_SWITCH: engaged})[KEY_KILL_SWITCH])


def set_system_prompt_override(prompt: str | None) -> str | None:
    """Replace or clear the operator's system prompt.

    Args:
        prompt: The replacement prompt. None or whitespace clears the override.

    Returns:
        The persisted override, or None when cleared.
    """
    return update({KEY_SYSTEM_PROMPT_OVERRIDE: prompt or ""})[KEY_SYSTEM_PROMPT_OVERRIDE]


def set_default_reasoning_effort(effort: str) -> str:
    """Set the reasoning effort used when a request does not name one.

    Args:
        effort: One of ``off``, ``low``, ``medium``, ``high``.

    Returns:
        The persisted value.

    Raises:
        ValueError: When ``effort`` is not one of the four permitted values.
    """
    return str(update({KEY_DEFAULT_REASONING_EFFORT: effort})[KEY_DEFAULT_REASONING_EFFORT])


def set_max_orders_per_session(cap: int) -> int:
    """Set how many orders one agent session may claim.

    Args:
        cap: The new cap. Zero blocks every order.

    Returns:
        The persisted value.

    Raises:
        ValueError: When ``cap`` is negative or not a whole number.
    """
    return int(update({KEY_MAX_ORDERS_PER_SESSION: cap})[KEY_MAX_ORDERS_PER_SESSION])


def set_risk_limits(**limits: Any) -> dict[str, Any]:
    """Update one or more risk limits by keyword.

    Args:
        **limits: Any subset of the risk-limit setting keys.

    Returns:
        The full settings payload after the write.

    Raises:
        ValueError: When a key is unknown or a value cannot be used.
    """
    return update(limits)
