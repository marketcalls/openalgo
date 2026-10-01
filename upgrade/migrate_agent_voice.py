#!/usr/bin/env python3
"""
Migration: Voice surface for the agent module (Milo)

Seeds the seven ``voice_*`` rows into ``ag_setting``, and nothing else. There is
no schema change here: ``ag_setting`` is a key/value table created by
``migrate_agent.py``, which is exactly why a new setting costs no DDL. If that
table is absent this script refuses rather than creating it, because the table
belongs to the migration that owns the agent schema and two scripts creating the
same table is how the two drift apart.

    voice_enabled                   false
    voice_model                     gpt-live-1
    voice_speaker                   marin
    voice_agent_name                Ava
    voice_order_phrase              milo
    voice_trading_enabled           false
    voice_confirm_window_seconds    30

**Why this seeds rows when migrate_agent.py deliberately does not.** That script
argues, correctly, that writing a shipped default out as a row turns "the
operator never chose" into "the operator chose this", so a later release can no
longer move the default for anyone who ran the migration. The voice block is the
one place where that is the wanted outcome, and it is wanted because of what the
two switches mean: ``voice_enabled`` and ``voice_trading_enabled`` ship off, and
a release that later flipped either of them by changing a code default would
turn a microphone on, or let spoken words reach an order tool, in a room the
operator never agreed to. Pinning them as rows is what makes that impossible.
The remaining five are pinned with them so the voice configuration is one
coherent set of rows an operator can read and edit, rather than two rows and
five absences.

The values are not written out here. They are read from
``services.agent.settings.get_voice_defaults()``, which is the same mapping the
application resolves a missing row to, so a default changed in one place cannot
seed a different value from the other. The key set comes from there too: an
eighth voice setting added to the spec is seeded by this script with no edit.

**Every write is guarded on absence of the row, never on its value.** An
operator who has already set a voice setting - or who set it, then cleared it
back to empty - keeps exactly what the row says. A row that exists with a NULL
or empty value is still a row the operator wrote through the settings page, and
overwriting it with a default is the clobber CLAUDE.md forbids.

This migration is idempotent - safe to run multiple times.

Usage:
    cd upgrade
    uv run migrate_agent_voice.py           # Apply migration
    uv run migrate_agent_voice.py --status  # Check status without changing anything
"""

import argparse
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Add parent directory to path for imports
sys.path.insert(0, PROJECT_ROOT)
# Register the app's SQLite pragmas on this process's engines, so a migration
# waits the same 15s for a write lock the running app does instead of the
# sqlite3 default of 5s (GitHub issue #1726).
import _pragmas  # noqa: F401,E402
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

#: The table the rows go in. Created by ``migrate_agent.py``; never by this one.
TABLE = "ag_setting"


def resolve_sqlite_path(db_url):
    """Make a relative sqlite:/// path absolute against the project root.

    The documented invocation is `cd upgrade && uv run migrate_agent_voice.py`,
    and DATABASE_URL is relative by default ("sqlite:///db/openalgo.db"). Left
    relative it resolves against the current directory, so running from upgrade/
    would point at upgrade/db/openalgo.db - which SQLAlchemy creates empty on
    connect. The migration would then seed its rows into a database the app
    never opens and report success.

    Args:
        db_url: The DATABASE_URL as configured.

    Returns:
        The same URL with any relative sqlite path made absolute. A non-sqlite
        URL is returned unchanged.
    """
    prefix = "sqlite:///"
    if not db_url.startswith(prefix):
        return db_url
    path = db_url[len(prefix) :]
    if os.path.isabs(path):
        return db_url
    return prefix + os.path.join(PROJECT_ROOT, path).replace("\\", "/")


def get_database_url():
    """Read DATABASE_URL from the environment, with the project default.

    Returns:
        The resolved database URL.
    """
    from dotenv import load_dotenv

    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
    return resolve_sqlite_path(os.getenv("DATABASE_URL", "sqlite:///db/openalgo.db"))


def sqlite_file(db_url):
    """The filesystem path a sqlite URL points at, or None for other backends.

    Args:
        db_url: A resolved database URL.

    Returns:
        The absolute path, or None when the URL is not sqlite.
    """
    prefix = "sqlite:///"
    if not db_url.startswith(prefix):
        return None
    return db_url[len(prefix) :]


def _render(value):
    """One default rendered as the text `ag_setting.value` holds.

    Deliberately identical to ``services.agent.settings._serialise`` for the
    three kinds the voice block uses. It is reproduced here rather than imported
    because that function is private and takes a private field object, which a
    migration has no business constructing. The text has to round-trip through
    the application's parser, and for these three kinds it does: "true"/"false"
    are in its boolean tokens and the rest are read back as-is.

    Args:
        value: A default from ``get_voice_defaults()``.

    Returns:
        The text to store.
    """
    if isinstance(value, bool):
        # Checked before int, because bool is a subclass of int and would
        # otherwise be stored as "0"/"1". The application's parser accepts both,
        # but a row reading "0" beside six readable ones is a needless puzzle
        # for whoever opens the table next.
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return str(value)


def seed_values():
    """The rows this migration would write, keyed by setting name.

    Read from the application's own defaults so the two cannot disagree. This is
    the only place the seeded set is defined: the spec in
    ``services/agent/settings.py`` decides both which voice settings exist and
    what each one starts as.

    Returns:
        An ordered mapping of setting key to the text to store.
    """
    from services.agent.settings import get_voice_defaults

    return {key: _render(value) for key, value in get_voice_defaults().items()}


def existing_rows(engine, keys):
    """The voice rows already in the database, keyed by setting name.

    Args:
        engine: An engine bound to the target database.
        keys: The setting keys to look for.

    Returns:
        A mapping of key to stored value, holding only keys that have a row. A
        row whose value is NULL is present in this mapping with a None value:
        presence is what the guard tests, not the value.
    """
    from database.agent_db import AgSetting

    with Session(engine) as session:
        rows = session.query(AgSetting).filter(AgSetting.key.in_(list(keys))).all()
        return {row.key: row.value for row in rows}


def table_present(engine):
    """Whether ``ag_setting`` exists yet.

    Args:
        engine: An engine bound to the target database.

    Returns:
        True when the table is there.
    """
    return TABLE in set(inspect(engine).get_table_names())


def pending(engine):
    """Which voice rows are absent and would be written.

    Args:
        engine: An engine bound to the target database.

    Returns:
        ``(missing, present)``. ``missing`` is an ordered mapping of key to the
        text that would be written; ``present`` is a mapping of key to the value
        already stored, which this migration leaves untouched.
    """
    wanted = seed_values()
    have = existing_rows(engine, wanted)
    missing = {key: text for key, text in wanted.items() if key not in have}
    return missing, have


def status(engine, db_url):
    """Report what would change, without changing anything.

    Reads nothing when the sqlite file does not exist yet: connecting would
    create it, and an empty database file is exactly the kind of side effect
    --status must not have.

    Args:
        engine: An engine bound to the target database.
        db_url: The resolved database URL, used to find the sqlite file.

    Returns:
        True when every voice row is already in place, False when work is
        pending or the agent tables are not there yet.
    """
    print("\nVoice settings status")
    print("-" * 62)

    path = sqlite_file(db_url)
    if path is not None and not os.path.exists(path):
        print("Database file does not exist yet. Not created: --status changes nothing.")
        print(f"Run migrate_agent.py first, which creates {TABLE}.")
        return False

    try:
        if not table_present(engine):
            print(f"{TABLE} is missing. Nothing was changed.")
            print("Run migrate_agent.py first; it owns the agent schema.")
            return False
        missing, have = pending(engine)
    except Exception as exc:
        # Reported rather than raised. The agent models and the settings spec
        # are imported for this, and a half-finished install is exactly the
        # state in which that import can fail; a traceback out of a command
        # that promises to change nothing tells an operator far less than one
        # line naming the cause.
        print("-" * 62)
        print(f"Could not read the voice settings: {type(exc).__name__}: {exc}")
        print("Nothing was changed. Fix the installation and run --status again.")
        return False

    for key, text in seed_values().items():
        if key in have:
            stored = "(empty)" if have[key] in (None, "") else have[key]
            print(f"  {key:<30} set by operator, keeping {stored}")
        else:
            print(f"  {key:<30} MISSING, would seed {text}")
    print("-" * 62)

    if not missing:
        print("Up to date. Nothing to do.")
        return True

    print(f"Migration needed. Would insert {len(missing)} row(s) into {TABLE}:")
    for key, text in missing.items():
        print(f"  {key} = {text}")
    print(f"The {len(have)} row(s) already present would not be touched.")
    return False


def apply(engine):
    """Insert whatever voice row is absent. An existing row is left alone.

    Args:
        engine: An engine bound to the target database.

    Returns:
        True on success, False when the rows could not be written.
    """
    try:
        if not table_present(engine):
            print(f"  [FAIL] {TABLE} does not exist. Run migrate_agent.py first.")
            return False
        from database.agent_db import AgSetting

        missing, have = pending(engine)
    except Exception as exc:
        # A [FAIL] line and a False return, not a traceback out of main(). The
        # agent models are imported here, and on a half-finished install that
        # import is the thing most likely to fail.
        print(f"  [FAIL] Could not read the voice settings: {type(exc).__name__}: {exc}")
        return False

    if not missing:
        print(f"  All {len(have)} voice setting(s) already present. Nothing to do.")
        return True

    try:
        # One transaction for the whole seed. A partial insert is still safe to
        # re-run - the next run seeds only what is still absent - but there is
        # no reason to leave the configuration half written when the seven rows
        # describe one surface.
        with Session(engine) as session:
            for key, text in missing.items():
                session.add(AgSetting(key=key, value=text))
            session.commit()
    except Exception as exc:
        print(f"  [FAIL] Could not seed the voice settings: {exc}")
        return False

    for key, text in missing.items():
        print(f"  [OK] Seeded {key} = {text}")
    if have:
        print(f"  Left {len(have)} operator-set row(s) untouched.")
    return True


def main():
    """Entry point.

    Returns:
        0 on success, 1 when the migration could not be applied.
    """
    parser = argparse.ArgumentParser(description="Agent voice surface settings migration")
    parser.add_argument(
        "--status",
        action="store_true",
        help="Report what would change without changing anything",
    )
    args = parser.parse_args()

    db_url = get_database_url()
    shown = db_url if not db_url.startswith("sqlite") else "sqlite://..."
    print("\nAgent Voice Settings Migration")
    print("-" * 62)
    print(f"Database: {shown}")

    engine = create_engine(db_url, poolclass=NullPool)
    try:
        if args.status:
            status(engine, db_url)
            return 0

        print("\nApplying migration...")
        ok = apply(engine)
        print("-" * 62)
        if ok:
            print("Migration complete.")
            return 0
        print("Migration failed. See the messages above.")
        return 1
    finally:
        # A migration is a short-lived process, but disposing is what keeps the
        # SQLite file unlocked for the app that may be waiting on it.
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
