"""What one deployment of an OpenScript strategy is, and what it is called.

**A strategy is not a run.** The same compiled program is deployed on one
instrument and on another, at the same time, by the same trader: a supertrend on
one stock and the same supertrend on a commodity future are two positions, two
books and two decisions to stop. The same is true of one instrument on two
timeframes, which is how a trend strategy is commonly run. So the thing this
platform starts, stops, tracks and attributes orders to is a **deployment**: a
script, the instrument it runs on, and the bar it runs on.

**It used to be the script alone, and that is the defect this exists to fix.**
Every run of one file shared an identity, so a trader could deploy a strategy on
only one instrument at a time, and, worse, the orders of a run on one instrument
appeared in the book of a run on another: the strategy panel showed a run on a
commodity future listing the stock orders the same file had placed that morning.
Two positions were reported as one, and a trader reading that book could not tell
which of them they were looking at.

**The name is the attribution.** A run tags every order it places with its own
id, and the per-deployment books are a filter on that tag. So the id has to
separate two deployments of one script, which is the whole of why the instrument
is in it.

**And it has to separate a deployment from the one it replaced.** An id worked
out from the script and the instrument alone is the same id again when a trader
removes a deployment and makes another like it, so the new one inherits the old
one's orders, fills and position: a strategy deployed a minute ago opens showing
a day of trades it never made, and a position it does not hold. The four parts
say what a deployment runs; they do not say which deployment it is. So a new one
is minted with a token of its own, kept in its settings, and two deployments that
look alike are still two.

**A deployment made before that token existed keeps the id it already had.** Its
orders carry that tag and its books are the answer to what it did, so deriving
the old id for an entry that has none is what keeps those books its own.

**It is bounded, because it is stored.** The column an order's tag is kept in
holds 120 characters. A readable id is built first, and only a triple that would
not fit is shortened, keeping a readable head and ending in a digest of the
whole so that two long names cannot collide. Shortening by truncation alone
would give two deployments one id, which is the failure this module exists to
prevent, reintroduced at the one length nobody tests.
"""

from __future__ import annotations

import hashlib
import re
import secrets

#: What every deployment id begins with. A run's log file, its registry key and
#: the tag on its orders all carry it, so it is the one word that says an order
#: came from this host rather than from a webhook or the no-code builder.
PREFIX = "openscript"

#: The most an id may be, and how much of the digest is kept when one has to be
#: shortened.
#:
#: The tag is stored in a column of 120 characters, and a value that does not fit
#: is either truncated by the database or refused by it, so the bound is here
#: rather than there. Eight hexadecimal characters is four thousand million
#: values, against a handful of deployments on one install.
MAX_LENGTH = 100
DIGEST_LENGTH = 8

#: How long the token that tells two otherwise identical deployments apart is.
#:
#: Six hexadecimal characters is sixteen million values against a handful of
#: deployments on one install, and it is short enough that the id stays readable:
#: it is the tag a trader sees in the global orderbook, not an internal key.
TOKEN_LENGTH = 6

#: What the parts are joined by before they are hashed. A character none of them
#: can hold, because a script name, an instrument, an exchange and an interval
#: are each letters, digits, dot, dash, colon or underscore. Without one, two
#: different deployments could join into the same string and hash to one id.
SEPARATOR = "|"

#: A deployment id as this mints one, for a route to match a path segment
#: against. Anchored, because a pattern that is not is a pattern that matches
#: the middle of something else.
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")


def stem(script: str) -> str:
    """A script's name without the extension every script carries."""
    return script[: -len(".oscript")] if script.endswith(".oscript") else script


def new_token() -> str:
    """A token for a deployment being created, so it is not the one it replaced.

    Random rather than counted or timed. A counter needs somewhere to keep the
    count, which is another thing to keep in step; a timestamp collides when two
    are made in the same second and leaks nothing useful. ``secrets`` rather than
    ``random`` because this names a thing that money is attributed to, and a
    predictable name is one somebody else can write orders against.
    """
    return secrets.token_hex(TOKEN_LENGTH // 2)


def deployment_id(
    script: str, symbol: str, exchange: str, interval: str = "", token: str = ""
) -> str:
    """The id this deployment is known by, everywhere.

    The registry key, the log file name and the tag on every order it places.
    One function, because those three agreeing is what makes a deployment's book
    its own: a tag written one way and read another answers an empty book for a
    strategy that is trading.

    **The interval is part of the identity.** One script on one instrument at
    five minutes and at one hour is two deployments, which is how a trend
    strategy is commonly run: the two disagree constantly, and a trader wants
    both positions and both books rather than one silently replacing the other.

    ``token`` is what tells this deployment from another on the same four parts,
    and an empty one derives the id those four alone produce. That is the id a
    deployment saved before tokens existed already has, and deriving it is what
    keeps its own orders its own.

    An empty instrument answers the script's own id, which is what a caller
    naming a script rather than a deployment means.
    """
    base = f"{PREFIX}_{stem(script)}"
    if not symbol:
        return base

    full = base
    for part in (symbol, exchange, interval, token):
        if part:
            full += f"_{part}"
    if len(full) <= MAX_LENGTH:
        return full

    # Too long to keep whole. The digest is over every part, so two deployments
    # that differ anywhere differ here, including past the point where the
    # readable head has been cut.
    joined = SEPARATOR.join((script, symbol, exchange, interval, token))
    digest = hashlib.sha256(joined.encode()).hexdigest()
    keep = MAX_LENGTH - DIGEST_LENGTH - 1
    return f"{full[:keep]}_{digest[:DIGEST_LENGTH]}"


def is_deployment_id(value: str) -> bool:
    """Whether this could be an id this minted, for a route to check a path.

    Shape only. Whether a deployment by that name exists is the settings store's
    answer, not this one's.
    """
    return bool(value) and value.startswith(f"{PREFIX}_") and bool(ID_PATTERN.match(value))
