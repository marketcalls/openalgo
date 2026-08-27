"""Side-effect-free contracts shared by Flow node validation and execution."""

import re
from datetime import datetime

# Order-update status values a watch can match on; ``any`` matches every update.
VALID_STATUSES = frozenset(
    {"any", "open", "trigger pending", "complete", "rejected", "cancelled"}
)


#: An expiry named on a leg, in DDMMMYY, e.g. 28OCT25.
EXPIRY_DATE_PATTERN = re.compile(r"\d{2}[A-Z]{3}\d{2}")

#: A strike named relative to the money: ATM, ITM1-ITM50, OTM1-OTM50.
OPTION_OFFSET_PATTERN = re.compile(r"(?:ATM|(?:ITM|OTM)(?:[1-9]|[1-4]\d|50))")

#: How a manually built leg picks its strike. OFFSET re-resolves against the
#: live underlying on every run; STRIKE names one contract and is used as given.
VALID_LEG_STRIKE_MODES = frozenset({"OFFSET", "STRIKE"})

#: Relative expiries the options nodes understand.
VALID_EXPIRY_TYPES = frozenset({"current_week", "next_week", "current_month", "next_month"})


#: Segments that trade contracts carried on margin rather than cash-settled
#: holdings. A position in one of these is normally taken NRML, so that is what
#: a node defaults to when its author never picked a product; MIS is the
#: default everywhere else. Index pseudo-exchanges are absent because no order
#: is ever placed on them.
DERIVATIVE_EXCHANGES = frozenset({"NFO", "BFO", "CDS", "BCD", "MCX", "NCDEX", "NCO"})


def default_product_for_exchange(exchange: str | None) -> str:
    """The product a node on ``exchange`` uses when its author picked none.

    This is a *default*, never an override: a product the author actually chose
    is stored on the node and wins, so an intraday NFO order stays MIS. The
    editor resolves the same rule so the panel shows what the run will send.
    """
    return "NRML" if (exchange or "").strip().upper() in DERIVATIVE_EXCHANGES else "MIS"


#: Expiry strings arrive from the master contract in a few shapes depending on
#: the broker; all of them are accepted and normalized to DDMMMYY.
_EXPIRY_INPUT_FORMATS = ("%d-%b-%y", "%d%b%y", "%d-%B-%Y", "%d%B%Y")


def parse_expiry_date(value: str) -> datetime | None:
    """One master-contract expiry string as a date, or None if unreadable."""
    if not value or not isinstance(value, str):
        return None
    for fmt in _EXPIRY_INPUT_FORMATS:
        try:
            return datetime.strptime(value.upper(), fmt)
        except ValueError:
            continue
    return None


def format_expiry_for_api(value: str) -> str:
    """DDMMMYY, the form every options API here expects."""
    return (value or "").replace("-", "").upper()


def select_expiry(expiries, expiry_type: str, *, now: datetime | None = None) -> str | None:
    """The expiry a relative type resolves to, in DDMMMYY.

    Shared by the executor and the editor's expiry picker. Keeping one
    implementation is what lets the panel promise "Same as node - 28AUG26" and
    have the run actually use 28AUG26; two copies of the rule would drift and
    the promise would quietly become wrong.

    The weekly types index into the sorted list, so on a monthly-only product
    such as an MCX commodity `current_week` is simply the nearest expiry. The
    monthly types take the *last* expiry within the month, which is the monthly
    contract on a weekly-listed underlying.

    Returns None when the type cannot be satisfied - no second expiry to be
    `next_week`, no contract in that month, or a type that is not known.
    """
    parsed = [
        (value, when)
        for value, when in ((value, parse_expiry_date(value)) for value in expiries or [])
        if when is not None
    ]
    if not parsed:
        return None
    parsed.sort(key=lambda pair: pair[1])

    if expiry_type == "current_week":
        return format_expiry_for_api(parsed[0][0])
    if expiry_type == "next_week":
        return format_expiry_for_api(parsed[1][0]) if len(parsed) > 1 else None

    if expiry_type not in ("current_month", "next_month"):
        return None

    reference = now or datetime.now()
    month, year = reference.month, reference.year
    if expiry_type == "next_month":
        month, year = (1, year + 1) if month == 12 else (month + 1, year)

    matches = [value for value, when in parsed if when.month == month and when.year == year]
    return format_expiry_for_api(matches[-1]) if matches else None


def normalize_status(value: str | None) -> str:
    """Canonicalize a broker order status for watch validation and matching."""
    return str(value or "").strip().lower().replace("_", " ")


def parse_underlying_symbol(underlying: str) -> tuple[str, str | None]:
    """Split an optional ``DDMMMYY`` expiry from an underlying symbol."""
    match = re.match(r"^([A-Z]+)(\d{2}[A-Z]{3}\d{2})(?:FUT)?$", underlying.upper())
    if match:
        return match.group(1), match.group(2)
    return underlying.upper(), None
