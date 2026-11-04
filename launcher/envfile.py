"""Reading and writing ``.env`` without the application or python-dotenv.

Line-based, so a rewrite keeps every comment and every line it was not asked to
change. Only the simple ``KEY = 'value'  # comment`` shape that ``.sample.env``
uses is understood; that is all the launcher ever edits.
"""

import re
import secrets
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

#: Shipped in ``.sample.env``; ``install.sh`` replaces them the same way.
PLACEHOLDER_APP_KEY = "OPENALGO_PLACEHOLDER_APP_KEY_REGENERATE_BEFORE_USE"
PLACEHOLDER_PEPPER = "OPENALGO_PLACEHOLDER_API_KEY_PEPPER_REGENERATE_BEFORE_USE"

#: Where and how the server listens. A reset keeps these, so the client's
#: address, and whether phones on the network can reach it, never change under
#: them. Everything else in ``.env`` goes back to the ``.sample.env`` default.
NETWORK_KEYS = (
    "FLASK_HOST_IP",
    "FLASK_PORT",
    "HOST_SERVER",
    "WEBSOCKET_HOST",
    "WEBSOCKET_PORT",
    "WEBSOCKET_URL",
    "ZMQ_HOST",
    "ZMQ_PORT",
    "CORS_ALLOWED_ORIGINS",
)

#: XTS brokers need a second key pair for market data. Same list as install.sh.
XTS_BROKERS = frozenset(
    {"fivepaisaxts", "compositedge", "ibulls", "iifl", "jainamxts", "rmoney", "wisdom"}
)

#: Brokers whose API key packs several values joined by ``:::``, and how many
#: separators ``utils/env_check.py`` requires, with the shape it shows.
KEY_FORMATS = {
    "fivepaisa": (2, "User_Key:::User_ID:::client_id"),
    "flattrade": (1, "client_id:::api_key"),
    "dhan": (1, "client_id:::api_key"),
}


@dataclass(frozen=True)
class Broker:
    """The broker a reset switches to. The app will not start without one."""

    name: str
    api_key: str
    api_secret: str
    market_api_key: str = ""
    market_api_secret: str = ""


def broker_problem(broker: Broker, valid_brokers: str) -> str | None:
    """Why the app would refuse to start with ``broker``, for the client; None if it would start.

    Mirrors the start-up checks in ``utils/env_check.py``, so a bad entry is
    caught in the reset dialog instead of leaving an installation that will
    not start.
    """
    valid = {b.strip().lower() for b in valid_brokers.split(",") if b.strip()}
    if broker.name not in valid:
        return f"{broker.name or 'That'} is not a broker this installation supports."
    if not broker.api_key.strip() or not broker.api_secret.strip():
        return "Enter both the API key and the API secret from your broker."
    if broker.name in KEY_FORMATS:
        separators, shape = KEY_FORMATS[broker.name]
        if broker.api_key.count(":::") != separators:
            return f"For {broker.name}, the API key is several values joined like this: {shape}"
    if broker.name in XTS_BROKERS and (
        not broker.market_api_key.strip() or not broker.market_api_secret.strip()
    ):
        return f"{broker.name} also needs its market data API key and secret."
    return None


_LINE = re.compile(
    r"^(?P<lead>\s*(?P<key>[A-Z][A-Z0-9_]*)\s*=\s*)"
    r"(?P<quote>['\"]?)(?P<value>.*?)(?P=quote)"
    r"(?P<tail>\s*(?:#.*)?)$"
)


def read_values(text: str) -> dict[str, str]:
    """Every ``KEY = value`` in ``text``. The last one wins, as in python-dotenv."""
    values = {}
    for line in text.splitlines():
        match = _LINE.match(line)
        if match:
            values[match["key"]] = match["value"]
    return values


def set_value(text: str, key: str, value: str) -> str:
    """Replace ``key``'s value on every line that sets it, keeping quotes and comments.

    Raises KeyError if no line sets ``key``: the launcher only edits keys
    ``.sample.env`` defines, so a missing one means the template changed.
    """
    found = False
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        body = line.rstrip("\r\n")
        match = _LINE.match(body)
        if match and match["key"] == key:
            quote = match["quote"] or "'"
            ending = line[len(body) :]
            lines[i] = f"{match['lead']}{quote}{value}{quote}{match['tail']}{ending}"
            found = True
    if not found:
        raise KeyError(key)
    return "".join(lines)


def _with_port(url: str, port: str) -> str:
    parts = urlsplit(url)
    if not parts.hostname:
        return url
    return urlunsplit(parts._replace(netloc=f"{parts.hostname}:{port}"))


def fresh_env(sample_text: str, broker: Broker, current_text: str | None = None) -> str:
    """A ``.env`` as a new install has it, for ``broker``, keeping the network settings of ``current_text``.

    New ``APP_KEY`` and ``API_KEY_PEPPER`` (``secrets.token_hex(32)``, as
    ``install.sh`` does). ``FERNET_SALT`` stays a placeholder: the app replaces
    it on first start. The broker's keys go in as ``install.sh`` puts them, and
    ``REDIRECT_URL`` names the broker on the kept HTTP port, so the redirect the
    client registers with the broker points at the port they actually use.
    Check ``broker_problem`` first; this does not.
    """
    text = sample_text.replace(PLACEHOLDER_APP_KEY, secrets.token_hex(32))
    text = text.replace(PLACEHOLDER_PEPPER, secrets.token_hex(32))
    text = set_value(text, "BROKER_API_KEY", broker.api_key.strip())
    text = set_value(text, "BROKER_API_SECRET", broker.api_secret.strip())
    if broker.name in XTS_BROKERS:
        text = set_value(text, "BROKER_API_KEY_MARKET", broker.market_api_key.strip())
        text = set_value(text, "BROKER_API_SECRET_MARKET", broker.market_api_secret.strip())

    sample = read_values(text)
    current = read_values(current_text) if current_text is not None else {}
    for key in NETWORK_KEYS:
        if key in current and key in sample and current[key] != sample[key]:
            text = set_value(text, key, current[key])

    redirect = sample["REDIRECT_URL"].replace("<broker>", broker.name)
    port = current.get("FLASK_PORT")
    if port:
        redirect = _with_port(redirect, port)
    return set_value(text, "REDIRECT_URL", redirect)
