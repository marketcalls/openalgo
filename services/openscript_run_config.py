"""What one OpenScript file is run on: the instrument, the exchange, the interval.

A compiled program says what to compute and what to send. It does not say which
instrument to compute it over, and nothing in the script can say it either: the
same script is run on one instrument by one trader and on another by the next.
So the server keeps that answer per script, and a start reads it here rather
than carrying it.

**Why a start does not carry the instrument.** A run started from a page, a run
started by a schedule and a run started again after a restart have to be the
same run. A start that carried the instrument is a start that can differ from
the one before it by one typed character, and the difference only becomes
visible as an order on something the trader never meant to trade. Saving it once
and starting by name leaves one place where that decision lives, and one place
to change it.

**This is the strategy host's pattern, followed rather than invented.**
``blueprints/python_strategy.py`` keeps ``strategies/strategy_configs.json``
beside the scripts it runs, writes it through a temporary file and renames it
into place so an interrupted write cannot leave half a file behind, and reads
the owning user back out of it when a schedule starts a strategy with nobody
watching. All three are here, for the same reasons, and this file sits in the
same folder for the reason the scripts do: on a container install that path is a
named volume, so what a trader saved survives an upgrade.

**Read through to the file, with no copy kept in memory.** The strategy host
holds its configurations in a module dictionary because its pages mutate them on
every request. A run configuration is written when a trader sets it and read
when a run starts, which is rare on both sides, so the file is the only copy and
an operator editing it by hand is read correctly the next time rather than
overwritten by a stale one.

**The lock is the ordinary one, deliberately.** Every caller here is a request
greenlet or a scheduled job, and under the production server both of those are
green: there is no real OS thread on any path into this module. A lock taken
from ``utils/real_threading`` would be the wrong one, because a greenlet that
blocks on a real lock stops the single worker for every user, and the section
below writes a file and flushes it. The ordinary lock hands the worker to the
next greenlet instead. It is here at all because a write is a read, a change and
a rename, and two of those interleaved would lose one script's settings.
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from threading import Lock

import pytz

from utils.logging import get_logger

logger = get_logger(__name__)

# The timezone every timestamp a trader reads is written in, as the strategy
# host already writes them.
IST = pytz.timezone("Asia/Kolkata")

#: Where the run settings live. Beside ``strategy_configs.json``, which is the
#: strategy host's own file, under the folder a container keeps on a named
#: volume so an upgrade leaves a trader's settings alone.
CONFIG_FILE = Path("strategies") / "openscript_run_configs.json"

#: The three products this platform sends. Restated here rather than imported
#: because the program that runs a script checks the same list from inside its
#: own process, and a value this file stored but that one refuses would be a run
#: that fails a minute later in a log instead of at the moment it was saved.
PRODUCTS = ("CNC", "NRML", "MIS")

# A script name these settings can be saved against. The same shape the route
# that stores sources accepts, restated because a name saved here reaches a
# command line when the run starts: a name with a separator, a dot segment or a
# dash at the front would be an argument rather than a file.
_SCRIPT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\.oscript$")

# The same, for the instrument and the interval, which reach that command line
# too.
_RUN_FIELD = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")

#: What a run cannot start without, against the words a trader reads for each.
#: A product is not here: a script that closes its position by the end of the
#: session needs none, and the one that carries a position overnight is refused
#: by name inside its own run, which is where the script's own declaration is
#: known.
REQUIRED_FIELDS: tuple[tuple[str, str], ...] = (
    ("symbol", "the instrument"),
    ("exchange", "the exchange"),
    ("interval", "the interval"),
)

#: Every field one script's settings hold.
FIELDS: tuple[str, ...] = ("symbol", "exchange", "interval", "product", "user_id")

# Guards the read, change and rename that a write is. See the module note for
# why it is the ordinary lock and not a real one.
_WRITE_LOCK = Lock()


def is_script_name(name: str) -> bool:
    """Whether this names a script these settings can be saved against."""
    return bool(_SCRIPT_NAME.match(name or ""))


def is_run_field(value: str) -> bool:
    """Whether this is an instrument, an exchange or an interval a run can use."""
    return bool(_RUN_FIELD.match(value or ""))


def is_product(value: str) -> bool:
    """Whether this is one of the products this platform sends."""
    return value in PRODUCTS


def _ist_now() -> datetime:
    return datetime.now(IST)


def _normalised(entry: dict) -> dict:
    """One stored entry with every field present, so a reader can index it.

    A caller that has to test for a key before reading it writes that test in
    four places and forgets it in a fifth. Anything else the entry carries is
    kept: this module is not the only writer a deployment may ever have.
    """
    filled = dict.fromkeys(FIELDS, "")
    filled["user_id"] = None
    filled.update(entry)
    for name in ("symbol", "exchange", "interval", "product"):
        filled[name] = "" if filled.get(name) is None else str(filled[name])
    return filled


def all_run_configs() -> dict[str, dict]:
    """Every script that has run settings saved, by file name.

    An unreadable file answers the same as an absent one, and says why in the
    log. The alternative is a start that fails with a message about a file, to a
    trader who cannot act on it and did not write it.
    """
    try:
        text = CONFIG_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError:
        logger.exception("Could not read the OpenScript run settings at %s", CONFIG_FILE)
        return {}

    try:
        stored = json.loads(text)
    except ValueError:
        logger.exception("The OpenScript run settings at %s do not read as JSON", CONFIG_FILE)
        return {}

    if not isinstance(stored, dict):
        logger.error("The OpenScript run settings at %s are not a set of scripts", CONFIG_FILE)
        return {}

    return {
        name: _normalised(entry)
        for name, entry in stored.items()
        if isinstance(name, str) and isinstance(entry, dict)
    }


def read_run_config(script: str) -> dict | None:
    """One script's run settings, or nothing when it has none saved.

    Nothing also answers a name that is not a script name, because a caller
    holding one has nothing to look up and a lookup that succeeded on it would
    be the more surprising answer.
    """
    if not is_script_name(script):
        return None
    found = all_run_configs().get(script)
    return dict(found) if found is not None else None


def require_run_config(script: str) -> tuple[dict | None, str]:
    """The settings a run needs, or nothing and a sentence saying what is missing.

    This is the answer a start acts on. The second half is written for the
    trader who asked for the run: it names the script, names what is not there
    and names what to do about it, because the person reading it is the one who
    can fix it and the run cannot.
    """
    if not is_script_name(script):
        return None, (
            f"{script!r} is not a script name. A name is letters, digits, dot, dash or "
            "underscore, and ends in .oscript"
        )

    found = read_run_config(script)
    if found is None:
        return None, (
            f"{script} has no run settings saved on this server, so nothing says which "
            "instrument, exchange and interval to run it on. Save its run settings, then "
            "start it again."
        )

    absent = [words for name, words in REQUIRED_FIELDS if not str(found.get(name) or "").strip()]
    if absent:
        return None, (
            f"{script} is missing {_listed(absent)} from its run settings. Save them, then "
            "start it again."
        )

    return found, ""


def _listed(words: list[str]) -> str:
    """A list of things, as a sentence says them."""
    if len(words) == 1:
        return words[0]
    return f"{', '.join(words[:-1])} and {words[-1]}"


def write_run_config(
    script: str,
    symbol: str,
    exchange: str,
    interval: str,
    product: str = "",
    user_id: str | None = None,
) -> tuple[bool, str]:
    """Save what one script is run on, replacing whatever was saved before.

    Everything is checked here and not only when a run starts, so a setting that
    could never start a run is refused while the trader is still looking at it
    rather than a minute later in a log.

    The exchange and the product are upper cased, because this platform states
    both in one case and a trader typing either in another means the same thing.
    The instrument and the interval are stored exactly as given: a symbol is the
    one string a broker mapping matches on, and quietly changing it is how a run
    ends up on a different instrument from the one that was typed.
    """
    if not is_script_name(script):
        return False, (
            f"{script!r} is not a script name. A name is letters, digits, dot, dash or "
            "underscore, and ends in .oscript"
        )

    symbol = (symbol or "").strip()
    exchange = (exchange or "").strip().upper()
    interval = (interval or "").strip()
    product = (product or "").strip().upper()

    for value, words in ((symbol, "instrument"), (exchange, "exchange"), (interval, "interval")):
        if not value:
            return False, f"{script} needs {'an' if words == 'exchange' else 'a'} {words} to run on"
        if not is_run_field(value):
            return False, (
                f"{value!r} is not {'an' if words == 'exchange' else 'a'} {words} this can start "
                "a run on"
            )

    if product and not is_product(product):
        return False, (
            f"{product!r} is not a product this platform sends. Use one of {', '.join(PRODUCTS)}."
        )

    entry = {
        "symbol": symbol,
        "exchange": exchange,
        "interval": interval,
        "product": product,
        "user_id": user_id,
        "updated_at": _ist_now().strftime("%Y-%m-%d %H:%M:%S IST"),
    }

    with _WRITE_LOCK:
        stored = all_run_configs()
        stored[script] = entry
        saved, why = _save(stored)

    if not saved:
        return False, why
    return True, f"{script} will run on {symbol} {exchange} at {interval}"


def delete_run_config(script: str) -> tuple[bool, str]:
    """Forget what one script is run on.

    A script with no settings can no longer be started, which is the point: a
    trader who has finished with a script wants it to stop being one command
    away from running.
    """
    if not is_script_name(script):
        return False, (
            f"{script!r} is not a script name. A name is letters, digits, dot, dash or "
            "underscore, and ends in .oscript"
        )

    with _WRITE_LOCK:
        stored = all_run_configs()
        if script not in stored:
            return False, f"{script} has no run settings saved"
        del stored[script]
        saved, why = _save(stored)

    if not saved:
        return False, why
    return True, f"The run settings for {script} are gone"


def _save(configs: dict[str, dict]) -> tuple[bool, str]:
    """Write every script's settings, all at once or not at all.

    Through a temporary file and a rename, which is what the strategy host does
    with its own and for the same reason: a rename replaces the file in one step,
    so a worker killed mid-write leaves the previous settings intact instead of
    half of the new ones. The flush is what makes that true, since a rename of a
    file whose bytes are still in a buffer replaces good settings with an empty
    file.

    The caller holds the write lock.
    """
    temporary = CONFIG_FILE.with_suffix(CONFIG_FILE.suffix + ".tmp")
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(configs, handle, indent=2, default=str, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, CONFIG_FILE)
    except OSError:
        logger.exception("Could not save the OpenScript run settings to %s", CONFIG_FILE)
        try:
            Path(temporary).unlink(missing_ok=True)
        except OSError:
            logger.debug("The half written run settings at %s could not be removed", temporary)
        return False, "These run settings could not be saved on this server"
    return True, ""
