"""The clock a run reads its calendar in, for any zone, supplied by this host.

**The engine reads one zone and leaves the rest to the host.** The Python engine's
own ``openscript/zones.py`` holds UTC and declines every other zone, on purpose:
the engine carries no dependencies, a table of offsets would be one, and its
conformance rules forbid an answer that depends on which machine a case ran on.
That module ends on the sentence this one exists for: "A host whose instruments
trade in another zone supplies the reader". Every instrument on this platform is
read in the market calendar's zone, Asia/Kolkata, so without a reader every
calendar call a script makes (``date.hour``, ``date.dayOfWeek``, ``session.isIn``
and the rest) is answered absent on every bar, and a condition built on one is
never true.

**This host has the database the engine declines to carry.** ``zoneinfo`` reads
the operating system's zone files, and where there are none, which is Windows,
it reads the ``tzdata`` package. That package is a pinned dependency of this
platform (``pyproject.toml``), so every install has it whatever it runs on.

**How the reader reaches the engine, and why it is checked rather than
trusted.** Version 0.5.0 takes a reader for a written time at load
(``read_time``) and nothing for the calendar calls. Those all reach two
functions in ``openscript.dates``, ``fields_in`` and ``instant_of``, which is
where its calendar meets a zone, so that is where this reader is put. UTC still
goes to the engine's own arithmetic untouched, and every other zone is read
here. Putting a function into a package is not a seam the package promises, so
after it is put there the engine's own ``date.hour`` and ``date.startOfDay`` are
asked about one instant in the zone the run needs and compared with this
server's database. A reader that is not in effect is taken back out and the zone
is reported unreadable, which is the refusal a run had before this existed.

**Two wall clock readings have no single instant, and ``stdlib.md`` 12.2 settles
both.** A reading the clock skipped is the instant it would have been, and a
reading the clock repeated is the first of its two. Both are what the standard
library answers for a reading with ``fold=0``, so nothing here decides either.
The platform's own zone changes its clock for neither, and the rule is kept for
a script that names another zone.

Nothing here imports the platform. It runs inside the strategy's own process,
which deliberately does not attach to the platform's logging or its database.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

#: A wall clock reading written as milliseconds from this, as though it were
#: UTC, which is how the engine's own arithmetic writes one.
_EPOCH = datetime(1970, 1, 1)

#: The instant the engine is asked about to check that the reader is in effect.
#: Any instant would do, since the answer is compared with the database for
#: whatever zone the run needs rather than with a number written here.
_PROBE_MS = 1_700_000_000_000


def _milliseconds(offset: timedelta) -> int:
    return int(offset.total_seconds() * 1000)


def _engine_own(function: Callable, attribute: str) -> Callable:
    """The engine's own function, where a reader may already have been put in its place."""
    owner = getattr(function, "__self__", None)
    if isinstance(owner, CalendarReader):
        return getattr(owner, attribute)
    return function


class CalendarReader:
    """The engine's two zone functions, for every zone this server's database holds.

    Built from the engine's own pieces rather than importing them, because the
    runner resolves the engine once and says so in a sentence when it is not
    installed. ``named`` is the engine's rule for what a zone name may look like
    at all, which ``stdlib.md`` 12.2 applies before any database is consulted,
    so a name every engine refuses is refused here as well.
    """

    def __init__(
        self,
        calendar: Any,
        named: Callable[[object], bool],
        readable: str,
        fields_at: Callable[[int], Any],
        instant_at: Callable[[Any], int],
        whole_instant: Callable[[float], int | None],
        max_instant: float,
    ) -> None:
        self._calendar = calendar
        self._named = named
        self._readable = readable
        self._fields_at = fields_at
        self._instant_at = instant_at
        self._whole = whole_instant
        self._max = max_instant
        #: The engine's own two, kept for UTC and for putting back. Found through
        #: a reader already in their place, so a second reader built in the
        #: same process never takes the first one for the engine.
        self._engine_fields_in = _engine_own(calendar.fields_in, "_engine_fields_in")
        self._engine_instant_of = _engine_own(calendar.instant_of, "_engine_instant_of")
        self._zones: dict[str, ZoneInfo | None] = {}
        self.installed = False

    # -- what a zone is -----------------------------------------------------

    def zone(self, name: object) -> ZoneInfo | None:
        """The database's zone for a name, or nothing where it holds none."""
        if not isinstance(name, str) or not self._named(name):
            return None
        if name not in self._zones:
            try:
                self._zones[name] = ZoneInfo(name)
            except (ZoneInfoNotFoundError, ValueError, OSError):
                self._zones[name] = None
        return self._zones[name]

    def knows(self, name: object) -> bool:
        """Whether a clock can be read in this zone: UTC, or one the database holds."""
        return name == self._readable or self.zone(name) is not None

    # -- the two functions the engine's calendar reaches ----------------------

    def fields_in(self, instant: Any, zone: Any) -> Any:
        """The civil reading of an instant in a zone, or nothing where there is none.

        Absent where the engine's own reader would be: a zone nobody can read, a
        timestamp that is not a number, and one past the largest instant a
        calendar reads. Also absent past the years the standard library holds,
        which no bar a platform serves is anywhere near.
        """
        if zone == self._readable:
            return self._engine_fields_in(instant, zone)
        found = self.zone(zone)
        if found is None:
            return None
        if not isinstance(instant, (int, float)) or isinstance(instant, bool):
            return None
        whole = self._whole(float(instant))
        if whole is None:
            return None
        try:
            offset = datetime.fromtimestamp(whole / 1000, UTC).astimezone(found).utcoffset()
        except (OverflowError, OSError, ValueError):
            return None
        if offset is None:
            return None
        return self._fields_at(whole + _milliseconds(offset))

    def instant_of(self, fields: Any, zone: Any) -> int | None:
        """The instant a wall clock reading names in a zone, or nothing for no reading."""
        if zone == self._readable:
            return self._engine_instant_of(fields, zone)
        if self.zone(zone) is None:
            return None
        return self.from_wall(self._instant_at(fields), zone)

    def from_wall(self, wall: int | float, zone: Any) -> int | None:
        """A wall clock reading, written as if it were UTC, as the instant it names.

        The reading is turned into a date and time before the zone is applied,
        so a field the engine's own arithmetic carried past its range (a
        thirteenth month from ``date.from``) is read the same way that
        arithmetic reads it rather than refused.
        """
        found = self.zone(zone)
        if found is None:
            return None
        if abs(wall) > self._max:
            return None
        try:
            reading = _EPOCH + timedelta(milliseconds=int(wall))
            offset = reading.replace(tzinfo=found).utcoffset()
        except (OverflowError, ValueError):
            return None
        if offset is None:
            return None
        instant = int(wall) - _milliseconds(offset)
        return None if abs(instant) > self._max else instant

    def time_reader(self, zone: str, read_as_utc: Callable[[str], float | None]):
        """How a written date and time becomes an instant, for a ``time`` input.

        The text is read by the engine's own reader, which knows the spellings
        a written time may take, and the reading it answers is then placed in
        this zone. So a trader who types ``2026-09-23 09:15`` for an instrument
        read in Asia/Kolkata gets the instant the market calls 09:15, rather than
        the one five and a half hours later that reading it as UTC gives.
        """
        if zone == self._readable:
            return read_as_utc

        def read(text: str) -> float | None:
            wall = read_as_utc(text)
            if wall is None:
                return None
            found = self.from_wall(wall, zone)
            return None if found is None else float(found)

        return read

    # -- putting it where the engine reads a zone -------------------------------

    def install(self, zone: object) -> bool:
        """Put this reader where the engine's calendar reads a zone. True once it answers.

        UTC needs nothing. A zone the database does not hold cannot be read
        however it is installed. Anything else is installed and then checked,
        and removed again if the engine's own calendar calls do not answer what
        the database says.
        """
        if zone == self._readable:
            return True
        if self.zone(zone) is None:
            return False
        if not self.installed:
            self._calendar.fields_in = self.fields_in
            self._calendar.instant_of = self.instant_of
            self.installed = True
        if self._answers(zone):
            return True
        self.uninstall()
        return False

    def uninstall(self) -> None:
        """Give the engine its own two functions back."""
        if not self.installed:
            return
        self._calendar.fields_in = self._engine_fields_in
        self._calendar.instant_of = self._engine_instant_of
        self.installed = False

    def _answers(self, zone: object) -> bool:
        """Whether the engine's own calendar calls read this zone as the database does.

        Asked through the engine's public reads rather than through this class,
        because the question is whether a script's call reaches this reader, and
        a check that called the reader directly would pass with the reader
        installed nowhere.
        """
        found = self.zone(zone)
        if found is None:
            return False
        try:
            hour = self._calendar.field_of(_PROBE_MS, zone, "hour")
            midnight = self._calendar.start_of(_PROBE_MS, zone, "day")
            local = datetime.fromtimestamp(_PROBE_MS / 1000, UTC).astimezone(found)
            expected = local.replace(hour=0, minute=0, second=0, microsecond=0)
            return float(hour) == local.hour and float(midnight) == expected.timestamp() * 1000
        except Exception:  # noqa: BLE001 - an engine that answers oddly is one this did not reach
            return False
