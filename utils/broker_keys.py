"""Which broker keys this process uses, and putting them in place.

A trader's broker keys come from two places:

1. The ``.env`` file. When REDIRECT_URL names a broker and BROKER_API_KEY is
   set, that broker uses the ``.env`` keys. This always comes first.
2. The keys saved in OpenAlgo (database/broker_keys_db.py), one set per broker,
   for every broker the ``.env`` file does not set, and for all of them when it
   sets none.

Only one broker is logged in at a time. The broker plugins read their keys from
the process environment at the moment they call the broker
(``os.getenv("BROKER_API_KEY")`` in about 140 files), so choosing a broker means
writing its keys into ``os.environ`` before its code runs: at the broker login,
when a session is resumed, at startup for the broker already logged in, and in
the websocket proxy process before it starts that broker's feed.

Two rules keep that safe:

- **A broker another session is logged in to is never replaced.** While a
  device holds a session from the current trading day, starting a login for a
  different broker is refused until the trader logs out, because the live
  session's orders read the same variables.
- **A pure ``.env`` install is never touched.** Its broker resolves to the
  ``.env`` values, which are what the environment already holds, so nothing is
  written.

This module performs no Flask work, so the websocket proxy process can use it.
"""

import functools
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# utils.config reloads .env over the environment the first time it is imported
# in a process. Importing it here, before anything below writes a key, makes
# sure that one-time reload can never land after a broker's keys were applied
# and quietly put the .env broker's keys back.
import utils.config  # noqa: F401
from utils.logging import get_logger
from utils.real_threading import Lock
from utils.thread_safe_cache import MISSING, LockedTTLCache

logger = get_logger(__name__)

#: Each stored field and the environment variable the broker plugins read.
ENV_VARS = {
    "api_key": "BROKER_API_KEY",
    "api_secret": "BROKER_API_SECRET",
    "api_key_market": "BROKER_API_KEY_MARKET",
    "api_secret_market": "BROKER_API_SECRET_MARKET",
    "redirect_url": "REDIRECT_URL",
}

PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: The broker variables as this process started with them, used where the
#: .env file does not list one (a value supplied by the container instead).
_STARTUP_VALUES = {var: os.environ.get(var) for var in ENV_VARS.values()}

_CALLBACK_PATTERN = re.compile(r"/([^/]+)/callback$")

#: Display names for messages a trader reads.
BROKER_NAMES = {
    "fivepaisa": "5 Paisa",
    "fivepaisaxts": "5 Paisa (XTS)",
    "aliceblue": "Alice Blue",
    "angel": "Angel One",
    "arrow": "Arrow",
    "compositedge": "CompositEdge",
    "dhan": "Dhan",
    "deltaexchange": "Delta Exchange",
    "indmoney": "IndMoney",
    "dhan_sandbox": "Dhan (Sandbox)",
    "definedge": "Definedge",
    "firstock": "Firstock",
    "flattrade": "Flattrade",
    "motilal": "Motilal Oswal",
    "fyers": "Fyers",
    "groww": "Groww",
    "hdfcsecurities": "HDFC Securities",
    "hdfcsky": "HDFC Sky",
    "ibulls": "Ibulls",
    "iifl": "IIFL",
    "iiflcapital": "IIFL Capital",
    "jainamxts": "JainamXts",
    "kotak": "Kotak Securities",
    "mstock": "mStock by Mirae Asset",
    "nubra": "Nubra",
    "paytm": "Paytm Money",
    "pocketful": "Pocketful",
    "rmoney": "RMoney",
    "rupeezy": "Rupeezy",
    "sahi": "Sahi",
    "samco": "Samco",
    "shoonya": "Shoonya",
    "tradejini": "Tradejini",
    "tradesmart": "TradeSmart",
    "upstox": "Upstox",
    "wisdom": "Wisdom Capital",
    "zebu": "Zebu",
    "zerodha": "Zerodha",
}

_apply_lock = Lock()

#: Longest a login holds the broker slot, in case its request never returns.
#: A token exchange takes seconds; a stuck one must not keep every other
#: broker out until a restart.
LOGIN_SLOT_SECONDS = 120

# The broker whose login is writing its keys and storing its token. In memory:
# production runs one worker process, and only it serves broker logins.
_slot_lock = Lock()
_slot = {"broker": None, "holders": set(), "until": 0.0}

# The logged-in broker, read on every request through the session-expiry
# check, so it is cached briefly; a login or logout changes it rarely.
_logged_in_broker_cache = LockedTTLCache(maxsize=1, ttl=10)


class BrokerKeysRefused(Exception):
    """A broker's keys cannot be used now. ``str(exc)`` is written for a trader."""


@dataclass(frozen=True)
class BrokerKeys:
    """One broker's keys and where they came from ("env" or "saved")."""

    broker: str
    source: str
    api_key: str
    api_secret: str
    api_key_market: str
    api_secret_market: str
    redirect_url: str


def broker_title(broker):
    """A broker's name as a trader knows it."""
    return BROKER_NAMES.get(broker, (broker or "").capitalize())


def broker_from_redirect_url(redirect_url):
    """The broker a callback address belongs to, or None.

    Args:
        redirect_url: An address ending in /<broker>/callback.
    """
    if not redirect_url:
        return None
    match = _CALLBACK_PATTERN.search(redirect_url.strip())
    if not match:
        return None
    broker = match.group(1).lower()
    if not broker or broker.startswith("<"):
        return None
    return broker


_BROKER_ID = re.compile(r"[a-z0-9_]+")


@functools.lru_cache(maxsize=64)
def broker_type(broker):
    """A broker's type from its plugin.json ("IN_stock", "crypto"), "" if unknown."""
    if not broker or not _BROKER_ID.fullmatch(broker):
        return ""
    try:
        plugin = PROJECT_ROOT / "broker" / broker / "plugin.json"
        return str(json.loads(plugin.read_text(encoding="utf-8")).get("broker_type") or "")
    except (OSError, ValueError):
        return ""


def default_redirect_url(broker):
    """The callback address OpenAlgo serves for a broker on this host."""
    host = (os.getenv("HOST_SERVER") or "http://127.0.0.1:5000").strip().rstrip("/")
    return f"{host}/{broker}/callback"


def env_file_path():
    """The .env file this install reads. A function so tests can point it elsewhere."""
    return PROJECT_ROOT / ".env"


def env_file_values():
    """The broker values the .env file sets, as plain text.

    Read from the file rather than from os.environ, because os.environ holds
    whichever broker was applied last. A variable the file does not list falls
    back to the value the process started with, which covers a container that
    passes it in the environment instead.

    Returns:
        dict: Every field of ENV_VARS, "" when unset.
    """
    path = env_file_path()
    file_values = {}
    try:
        if path.is_file():
            from dotenv import dotenv_values

            file_values = dotenv_values(path)
    except Exception:
        logger.exception("Could not read the .env file for the broker keys")
    values = {}
    for field, var in ENV_VARS.items():
        value = file_values[var] if var in file_values else _STARTUP_VALUES.get(var)
        values[field] = (value or "").strip()
    return values


def env_broker(values=None):
    """The broker the .env file sets keys for, or None when it sets none.

    The .env file sets a broker when REDIRECT_URL names one and BROKER_API_KEY
    is not empty.
    """
    values = values if values is not None else env_file_values()
    if not values["api_key"]:
        return None
    return broker_from_redirect_url(values["redirect_url"])


#: API key layouts some brokers need, as "field:::field". (separators, message)
_KEY_FORMATS = {
    "fivepaisa": (2, "5paisa API key must be in format: 'User_Key:::User_ID:::client_id'"),
    "flattrade": (1, "Flattrade API key must be in format: 'client_id:::api_key'"),
    "dhan": (1, "Dhan API key must be in format: 'client_id:::api_key'"),
}


def key_format_error(broker, api_key):
    """Why an API key does not fit its broker's layout, or None when it does."""
    expected = _KEY_FORMATS.get(broker)
    if not expected or not api_key:
        return None
    separators, message = expected
    return None if api_key.count(":::") == separators else message


def enabled_brokers():
    """Brokers this install can log in to: listed in VALID_BROKERS and present.

    Returns:
        list[str]: In VALID_BROKERS order.
    """
    listed = [b.strip().lower() for b in os.getenv("VALID_BROKERS", "").split(",") if b.strip()]
    broker_dir = PROJECT_ROOT / "broker"
    return [b for b in dict.fromkeys(listed) if (broker_dir / b / "api" / "auth_api.py").is_file()]


def resolve(broker):
    """The keys a broker logs in with, .env first.

    Args:
        broker: The broker id.

    Returns:
        BrokerKeys | None: None when neither source has a key for it.
    """
    env = env_file_values()
    if broker and broker == env_broker(env):
        return BrokerKeys(broker=broker, source="env", **env)

    from database.broker_keys_db import get_broker_keys

    stored = get_broker_keys(broker)
    if stored is None or not stored.api_key:
        return None
    return BrokerKeys(
        broker=broker,
        source="saved",
        api_key=stored.api_key,
        api_secret=stored.api_secret,
        api_key_market=stored.api_key_market,
        api_secret_market=stored.api_secret_market,
        redirect_url=stored.redirect_url or default_redirect_url(broker),
    )


def configured_brokers():
    """Every broker the trader can log in to, each once, .env first.

    Returns:
        list[dict]: ``{"broker", "name", "source"}`` where source is "env" or
        "saved". A broker missing from VALID_BROKERS is left out.
    """
    from database.broker_keys_db import list_broker_keys

    enabled = set(enabled_brokers())
    out = []
    env = env_broker()
    if env and env in enabled:
        out.append({"broker": env, "name": broker_title(env), "source": "env"})
    for stored in list_broker_keys():
        if stored.broker == env or stored.broker not in enabled or not stored.api_key:
            continue
        out.append(
            {"broker": stored.broker, "name": broker_title(stored.broker), "source": "saved"}
        )
    return out


def _never_expires(broker):
    """Whether a broker's session runs past the daily rollover (crypto, or the flag)."""
    if os.getenv("DISABLE_SESSION_EXPIRY", "false").lower() == "true":
        return True
    return broker_type(broker) == "crypto"


def _signed_in_since_rollover(username, broker):
    """Whether this broker's session was opened during the current trading day.

    Either a device holds a session from today, or a broker login (fresh or
    resumed) for this broker was recorded since the rollover. The second
    matters because a password change or reset clears every device session but
    leaves the broker token live: the slot must stay held until the token is
    revoked or the day ends.
    """
    import pytz

    from database.auth_db import LoginAttempt, get_active_sessions
    from utils.session import last_rollover_boundary

    ist = pytz.timezone("Asia/Kolkata")
    boundary = last_rollover_boundary()

    def _ist(value):
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except ValueError:
                return None
        if value is None:
            return None
        return ist.localize(value) if value.tzinfo is None else value

    for sess in get_active_sessions(username):
        login = _ist(sess.get("login_time"))
        if login is not None and login >= boundary:
            return True

    latest = (
        LoginAttempt.query.filter_by(username=username, status="success", broker=broker)
        .order_by(LoginAttempt.timestamp.desc())
        .first()
    )
    login = _ist(latest.timestamp) if latest else None
    return login is not None and login >= boundary


def logged_in_broker():
    """The broker of the stored, unrevoked broker session, or None.

    Unlike live_broker() it does not ask whether the session is from today:
    it names the broker OpenAlgo is logged in to, for decisions that follow the
    broker itself, such as whether its session runs past the rollover.
    """
    from database.auth_db import Auth

    def _load():
        try:
            for row in Auth.query.filter_by(is_revoked=False).all():
                if row.auth and row.broker:
                    return row.broker
            return None
        except Exception:
            logger.exception("Could not read which broker is logged in")
            return MISSING

    value = _logged_in_broker_cache.get_or_load(
        "broker", _load, should_cache=lambda v: v is not MISSING
    )
    return None if value is MISSING else value


def forget_logged_in_broker():
    """Drop the cached logged-in broker (after a login or a logout)."""
    _logged_in_broker_cache.invalidate()


def live_broker():
    """The broker a current session is logged in to, or None.

    A broker counts as logged in while its token is stored and not revoked and
    it was signed in to during the current trading day (or it never expires: a
    crypto broker). A token left from an earlier day is dead at the broker and
    does not hold the slot.
    """
    from database.auth_db import Auth

    try:
        rows = Auth.query.filter_by(is_revoked=False).all()
        for row in rows:
            if not (row.auth and row.broker):
                continue
            if _never_expires(row.broker) or _signed_in_since_rollover(row.name, row.broker):
                return row.broker
    except Exception:
        logger.exception("Could not read which broker is logged in")
    return None


def _apply(keys):
    """Write a broker's keys into the process environment.

    A variable that already holds the value is not written, so applying the
    broker that is already in place changes nothing. An empty value clears a
    variable that is set and leaves an unset one unset, as an .env line with
    no value would.

    Returns:
        bool: True when anything changed.
    """
    changed = False
    with _apply_lock:
        for field, var in ENV_VARS.items():
            value = getattr(keys, field) or ""
            current = os.environ.get(var)
            if not value and current is None:
                continue
            if current != value:
                os.environ[var] = value
                changed = True
    return changed


def hold_login_slot(broker):
    """Hold the broker slot while a login writes its keys and stores its token.

    The environment holds one broker's keys, so a login exchanging its code
    keeps every other broker's login from writing theirs until its token is
    stored: otherwise that token would be stored and used with the other
    broker's keys. Logins to the same broker share the slot. Release it with
    release_login_slot() when the request ends, however it ends.

    Returns:
        object: The holder to release.

    Raises:
        BrokerKeysRefused: While a login to another broker holds the slot.
    """
    holder = object()
    now = time.monotonic()
    with _slot_lock:
        held = _slot["broker"]
        busy = bool(_slot["holders"]) and _slot["until"] > now
        other = held if busy and held != broker else None
        if other is None:
            if held != broker or not busy:
                _slot["holders"] = set()
            _slot["broker"] = broker
            _slot["holders"].add(holder)
            _slot["until"] = now + LOGIN_SLOT_SECONDS
    if other:
        raise BrokerKeysRefused(
            f"A login to {broker_title(other)} is under way. Wait for it to finish, then try again."
        )
    return holder


def release_login_slot(holder):
    """Give back a holder from hold_login_slot(). None is ignored."""
    if holder is None:
        return
    with _slot_lock:
        _slot["holders"].discard(holder)
        if not _slot["holders"]:
            _slot.update(broker=None, until=0.0)


def login_slot_broker():
    """The broker whose login holds the slot, or None."""
    with _slot_lock:
        if _slot["holders"] and _slot["until"] > time.monotonic():
            return _slot["broker"]
    return None


def _refuse_another_broker(broker):
    """Refuse while another broker is logged in or its login is under way."""
    live = live_broker()
    if live and live != broker:
        raise BrokerKeysRefused(
            f"OpenAlgo is logged in to {broker_title(live)}. End that session on the "
            f"broker login page first, then choose {broker_title(broker)}."
        )
    pending = login_slot_broker()
    if pending and pending != broker:
        raise BrokerKeysRefused(
            f"A login to {broker_title(pending)} is under way. Wait for it to finish, then try again."
        )


def _resolve_or_refuse(broker):
    keys = resolve(broker)
    if keys is None:
        raise BrokerKeysRefused(
            f"No API key is saved for {broker_title(broker)}. "
            "Add it under Broker Keys, then try again."
        )
    return keys


def keys_for_login(broker):
    """The keys a login to this broker starts with, leaving the environment alone.

    Starting a login only builds the broker's sign-in address, so nothing is
    written: the keys go in place at the callback, under the login slot.

    Raises:
        BrokerKeysRefused: While another broker is logged in or its login is
            under way, or when no key is configured for this one.
    """
    _refuse_another_broker(broker)
    return _resolve_or_refuse(broker)


def use_broker_keys(broker, check_live=True):
    """Put a broker's keys in place for the code about to call it.

    A login holds the slot (hold_login_slot) before calling this, so no other
    broker's login can replace the keys before its token is stored.

    Args:
        broker: The broker id.
        check_live: Refuse when another broker is logged in or its login is
            under way. False only where the broker passed is the one already
            logged in (startup, resume, the websocket proxy).

    Returns:
        BrokerKeys: The keys now in place.

    Raises:
        BrokerKeysRefused: With a message for the trader.
    """
    if check_live:
        _refuse_another_broker(broker)
    keys = _resolve_or_refuse(broker)
    if _apply(keys):
        where = "the .env file" if keys.source == "env" else "the keys saved in OpenAlgo"
        logger.info(f"Using {where} for {broker_title(broker)}")
    return keys


def apply_logged_in_broker_keys():
    """At startup, put back the keys of the broker whose session is stored.

    A restart loses the environment a login wrote. Without this, an order
    placed after a restart would reach a broker saved in OpenAlgo with the
    .env broker's keys.
    """
    from database.auth_db import Auth

    try:
        rows = Auth.query.filter_by(is_revoked=False).all()
        brokers = [row.broker for row in rows if row.auth and row.broker]
    except Exception:
        logger.exception("Could not read the stored broker session at startup")
        return None
    for broker in brokers:
        try:
            return use_broker_keys(broker, check_live=False)
        except BrokerKeysRefused:
            logger.warning(
                f"The stored session is for {broker_title(broker)}, but no keys are "
                "configured for it any more. Log in to a broker again."
            )
    return None
