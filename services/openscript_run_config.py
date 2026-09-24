"""What one OpenScript deployment is run on: the instrument, exchange and interval.

A compiled program says what to compute and what to send. It does not say which
instrument to compute it over, and nothing in the script can say it either: the
same script is run on one instrument by one trader and on another by the next.
So the server keeps that answer, and a start reads it here rather than carrying
it.

**The unit is a deployment and not a script.** One script is deployed on several
instruments at once, each with its own position, its own book and its own
decision to stop, so the settings are keyed by what `openscript_deployment`
mints from the script and the instrument together. They used to be keyed by the
script alone, which meant a strategy could be deployed once and a second
instrument silently replaced the first.

**An older file is read forward rather than migrated.** A file written when the
key was the script name carries the instrument inside each entry, which is
everything needed to work out the key it would have today, so it is read as if
it had always been in this shape. Nothing is rewritten until the next save,
which means a downgrade still reads what a trader has.

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
from typing import Any

import pytz

from services.openscript_deployment import deployment_id, is_deployment_id, new_token
from utils.logging import get_logger

logger = get_logger(__name__)

# The timezone every timestamp a trader reads is written in, as the strategy
# host already writes them.
IST = pytz.timezone("Asia/Kolkata")

#: Where the run settings live. Beside ``strategy_configs.json``, which is the
#: strategy host's own file, under the folder a container keeps on a named
#: volume so an upgrade leaves a trader's settings alone.
CONFIG_FILE = Path("strategies") / "openscript_run_configs.json"

#: The two sides a run's orders can have gone to, in the words the strategy
#: module's own column uses. A deployment remembers which one its run started
#: on, because its books are read from there. See ``record_run_mode``.
RUN_MODES = ("live", "sandbox")

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

#: Every field one deployment's settings hold. ``script`` is among them because
#: the key is no longer the script name: a reader holding an entry has to be
#: able to say which file it runs without taking the key apart.
FIELDS: tuple[str, ...] = (
    "deployment",
    "script",
    "symbol",
    "exchange",
    "interval",
    "product",
    "user_id",
    "inputs",
)

#: The most settings one script may carry, and the longest a key or a piece of
#: text may be. A script declares its own inputs, so these are far above any
#: real one; they are here because this file is written from a request body and
#: a bound nobody set is a file somebody can grow without limit.
MAX_INPUTS = 64
MAX_KEY_LENGTH = 64
MAX_TEXT_LENGTH = 256

# An input key, as a compiler mints one: a name from the script. Restated here
# because this value is stored and later handed to an engine, and a key that
# could hold anything is a key that could be read as something else by whatever
# reads it next.
_INPUT_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,63}$")

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
    filled["inputs"] = {}
    filled.update(entry)
    for name in ("deployment", "script", "symbol", "exchange", "interval", "product"):
        filled[name] = "" if filled.get(name) is None else str(filled[name])
    # Read back through the same check that let it in. A file an operator edited
    # by hand, or one written by an older version, reaches a run otherwise, and
    # the run is where a bad value costs an order rather than a message.
    kept, _ = _checked_inputs(filled.get("inputs"))
    filled["inputs"] = kept
    return filled


def _checked_inputs(given: Any) -> tuple[dict, str]:
    """The settings a run may carry, or an empty map and what is wrong with them.

    **These are the script's own parameters, and this is the only place that
    decides what one may be.** A value here is handed to an engine as the
    setting for an ``input()`` the script declared, so the shapes allowed are
    the shapes an engine reads: true or false, a number, or a piece of text.
    Anything else, a list, a nested object, a number that is not one, is not a
    setting any script could have asked for, and storing it would move the
    refusal from a page a trader is looking at into a log written a minute later
    by a process they cannot see.

    **What is refused here is not what makes a value correct.** A script states
    its own bounds and its own choices, and the engine holds a setting to them
    when it loads the program. This is the coarser question asked first: whether
    this is the kind of thing a setting can be at all.
    """
    if given is None or given == "":
        return {}, ""
    if not isinstance(given, dict):
        return {}, "The strategy parameters must be given as a set of named values."
    if len(given) > MAX_INPUTS:
        return {}, f"A strategy may carry at most {MAX_INPUTS} parameters."

    kept: dict = {}
    for key, value in given.items():
        if not isinstance(key, str) or not _INPUT_KEY.match(key):
            return {}, f"{key!r} is not the name of a parameter a script can declare."
        if isinstance(value, bool):
            kept[key] = value
            continue
        if isinstance(value, (int, float)):
            number = float(value)
            # A number that is not one reaches the engine as a setting it cannot
            # compare against a minimum, and JSON has no spelling for either, so
            # this only arises from a file edited by hand or a caller sending
            # something else entirely.
            if number != number or number in (float("inf"), float("-inf")):
                return {}, f"{key} was given a number that is not one."
            kept[key] = value
            continue
        if isinstance(value, str):
            if len(value) > MAX_TEXT_LENGTH:
                return {}, f"{key} is longer than a parameter may be."
            kept[key] = value
            continue
        return {}, f"{key} was given something a parameter cannot be."

    return kept, ""


def all_run_configs() -> dict[str, dict]:
    """Every deployment that has run settings saved, by deployment id.

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
        logger.error("The OpenScript run settings at %s are not a set of deployments", CONFIG_FILE)
        return {}

    out: dict[str, dict] = {}
    for name, entry in stored.items():
        if not isinstance(name, str) or not isinstance(entry, dict):
            continue
        filled = _normalised(entry)
        if is_script_name(name):
            # Written when the key was the script name. Everything needed to
            # work out the key it would have today is inside it, so it is read
            # as though it had always been in this shape rather than migrated:
            # nothing is rewritten until the next save, and a trader who goes
            # back to an older version still has their settings.
            filled["script"] = name
            name = deployment_id(
                name,
                filled.get("symbol", ""),
                filled.get("exchange", ""),
                filled.get("interval", ""),
            )
        # The id a deployment carries is its own, and a deployment made before
        # deployments carried one keeps the id its orders are already tagged
        # with. Deriving a fresh one for it would hand its whole book to
        # nobody: the rows stay in the account tagged as they were.
        filled["deployment"] = filled.get("deployment") or name
        out[str(filled["deployment"])] = filled
    return out


def deployments_of(script: str) -> dict[str, dict]:
    """Every deployment of one script, by deployment id."""
    return {
        name: entry
        for name, entry in all_run_configs().items()
        if entry.get("script") == script
    }


def read_run_config(name: str) -> dict | None:
    """One deployment's run settings, or nothing when there are none saved.

    ``name`` is a deployment id, or a script name when that script has exactly
    one deployment. **A script deployed twice is not resolved by name**, because
    guessing which of two instruments a caller meant is how an order reaches the
    one they did not.
    """
    if is_deployment_id(name):
        found = all_run_configs().get(name)
        return dict(found) if found is not None else None

    if not is_script_name(name):
        return None
    theirs = deployments_of(name)
    if len(theirs) != 1:
        return None
    return dict(next(iter(theirs.values())))


def require_run_config(name: str) -> tuple[dict | None, str]:
    """The settings a run needs, or nothing and a sentence saying what is missing.

    This is the answer a start acts on. The second half is written for the
    trader who asked for the run: it names what is not there and names what to
    do about it, because the person reading it is the one who can fix it and the
    run cannot.
    """
    if not is_deployment_id(name) and not is_script_name(name):
        return None, (
            f"{name!r} is not a script name. A name is letters, digits, dot, dash or "
            "underscore, and ends in .oscript"
        )

    if is_script_name(name):
        theirs = deployments_of(name)
        if len(theirs) > 1:
            # Resolving this by picking one is how an order reaches the
            # instrument a trader did not mean. The deployments are named so the
            # caller can say which.
            where = ", ".join(
                f"{one.get('symbol')} {one.get('exchange')} at {one.get('interval')}"
                for one in theirs.values()
            )
            return None, (
                f"{name} is deployed {len(theirs)} times ({where}), so this cannot tell which "
                "one to start. Start it from its own row."
            )

    found = read_run_config(name)
    if found is None:
        return None, (
            f"{name} has no run settings saved on this server, so nothing says which "
            "instrument, exchange and interval to run it on. Save its run settings, then "
            "start it again."
        )

    absent = [words for field, words in REQUIRED_FIELDS if not str(found.get(field) or "").strip()]
    if absent:
        return None, (
            f"{found.get('script') or name} is missing {_listed(absent)} from its run settings. "
            "Save them, then start it again."
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
    inputs: Any = None,
    deployment: str = "",
) -> tuple[bool, str]:
    """Save what one script is run on, replacing whatever was saved before.

    Everything is checked here and not only when a run starts, so a setting that
    could never start a run is refused while the trader is still looking at it
    rather than a minute later in a log.

    The strategy's own parameters are stored beside them, as the values an
    engine will resolve the script's ``input()`` declarations against. What may
    be one is decided in ``_checked_inputs``; what makes one correct for a
    particular script is decided by that script, when the engine loads it.

    ``deployment`` names the one being edited, and an empty one creates. The
    difference is the whole of what keeps a book its own:

    - **Editing keeps the id**, so the deployment's own orders stay its own.
    - **Creating mints a new one**, so a deployment made where another was
      removed does not inherit that one's orders, fills and position. Worked out
      from the four parts alone, the id was the same id again and a strategy
      deployed a minute ago opened showing a day of trades it never made.
    - **Creating a second deployment on the same script, instrument and interval
      is refused**, because that is one strategy running twice on one
      instrument: two runs, two positions, and a trader who believes they have
      one. It is what the single key used to prevent by collapsing them, said
      out loud instead.

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

    settings, wrong = _checked_inputs(inputs)
    if wrong:
        return False, wrong

    stored = all_run_configs()
    held = stored.get(deployment) if deployment else None

    # The same four as something already deployed, and not that thing itself.
    clash = next(
        (
            one
            for one, saved in stored.items()
            if one != deployment
            and saved.get("script") == script
            and saved.get("symbol") == symbol
            and saved.get("exchange") == exchange
            and saved.get("interval") == interval
        ),
        None,
    )
    if clash is not None:
        return False, (
            f"{script} is already deployed on {symbol} {exchange} at {interval}. One strategy "
            "runs once on one instrument and interval: change the instrument or the interval, "
            "or edit the deployment that is already there."
        )

    # **Editing keeps the id only while the deployment is still the same
    # deployment.** Changing the instrument or the interval is not moving this
    # one, it is making another: the form says so, and keeping the id would
    # leave the new instrument showing the old one's orders, which is the exact
    # confusion a token exists to end.
    stays = held is not None and (
        str(held.get("script") or "") == script
        and str(held.get("symbol") or "") == symbol
        and str(held.get("exchange") or "") == exchange
        and str(held.get("interval") or "") == interval
    )
    key = (
        str(held["deployment"])
        if stays
        else deployment_id(script, symbol, exchange, interval, token=new_token())
    )

    entry = {
        "deployment": key,
        "script": script,
        "symbol": symbol,
        "exchange": exchange,
        "interval": interval,
        "product": product,
        "user_id": user_id,
        "inputs": settings,
        "updated_at": _ist_now().strftime("%Y-%m-%d %H:%M:%S IST"),
    }
    # The side this deployment last traded on is not a setting and survives
    # an edit that keeps the deployment. Its orders are still where they went,
    # and a trader changing a parameter between runs still wants to read them.
    if stays and held.get("mode") in RUN_MODES:
        entry["mode"] = held["mode"]

    with _WRITE_LOCK:
        stored = all_run_configs()
        stored[key] = entry
        saved, why = _save(stored)

    if not saved:
        return False, why
    return True, f"{script} will run on {symbol} {exchange} at {interval}"


def record_run_mode(name: str, mode: str) -> bool:
    """Remember the side a deployment's run started on. True once it is saved.

    **Its books are read from here once the run has stopped**, because the
    orders it placed went where the platform sent them when they were placed,
    and the platform's analyzer setting may say something else by the time
    anybody looks. A deployment with no settings saved, which is a run started
    with an instrument passed straight in, has nowhere to keep it; its books
    follow the platform's setting once it stops, as they always did.

    Not a setting: nothing a trader sends reaches it, and ``write_run_config``
    carries it across an edit that keeps the deployment.
    """
    if mode not in RUN_MODES or not is_deployment_id(name):
        return False
    with _WRITE_LOCK:
        stored = all_run_configs()
        entry = stored.get(name)
        if entry is None:
            return False
        if entry.get("mode") == mode:
            return True
        entry["mode"] = mode
        saved, _ = _save(stored)
    return saved


def run_mode_of(name: str) -> str:
    """The side a deployment's run last started on, or an empty string.

    Only one of the two words is ever answered. A file edited by hand to say
    anything else answers nothing, and the caller falls back to the platform's
    setting rather than reading a book from a side nobody named.
    """
    mode = (read_run_config(name) or {}).get("mode")
    return mode if mode in RUN_MODES else ""


def delete_run_config(name: str) -> tuple[bool, str]:
    """Remove one deployment.

    A deployment with no settings can no longer be started, which is the point:
    a trader who has finished running a strategy on an instrument wants it to
    stop being one command away from running.

    ``name`` is a deployment id, or a script name when that script has exactly
    one deployment. A script deployed twice is refused by name rather than
    resolved, for the reason `read_run_config` gives: the wrong guess here
    removes a deployment a trader is still running.
    """
    if not is_deployment_id(name) and not is_script_name(name):
        return False, (
            f"{name!r} is not a script name. A name is letters, digits, dot, dash or "
            "underscore, and ends in .oscript"
        )

    with _WRITE_LOCK:
        stored = all_run_configs()
        key = name
        if key not in stored:
            theirs = [one for one, entry in stored.items() if entry.get("script") == name]
            if len(theirs) > 1:
                return False, (
                    f"{name} is deployed {len(theirs)} times, so this cannot tell which to "
                    "remove. Remove it from its own row."
                )
            if not theirs:
                return False, f"{name} has no run settings saved"
            key = theirs[0]
        gone = stored.pop(key)
        saved, why = _save(stored)

    if not saved:
        return False, why
    return True, f"The run settings for {gone.get('script') or key} are gone"


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
