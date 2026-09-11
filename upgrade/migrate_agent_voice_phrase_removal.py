"""Remove the voice approval-phrase settings, which no longer exist.

The voice surface used to approve a staged order with a configured secret word.
That is gone: an order is now approved by confirming it out loud after the agent
has read it back, or by tapping the card on screen. Two settings went with it,
and this removes their rows.

They are harmless if left - nothing reads them - but one of them held a word an
operator chose as a secret, and a row nothing reads is a row nobody will think
to clear. `ag_setting` is small and its contents are read by the settings screen,
so leaving retired keys in it makes the live configuration harder to read than
it needs to be.

Idempotent, and safe to run on a database that never had them.

Usage:
    uv run migrate_agent_voice_phrase_removal.py
    uv run migrate_agent_voice_phrase_removal.py --status
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine, inspect  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

load_dotenv()

TABLE = "ag_setting"

#: The keys this migration removes. Retired when spoken approval became a plain
#: confirmation after the read-back.
RETIRED_KEYS = ("voice_order_phrase", "voice_approval_mode")


def get_database_url():
    """The database this instance uses.

    Returns:
        str: The SQLAlchemy URL.
    """
    return os.getenv("DATABASE_URL", "sqlite:///db/openalgo.db")


def sqlite_file(db_url):
    """The file a sqlite URL points at, or None for any other backend.

    Args:
        db_url: The database URL.

    Returns:
        Path | None: The file path.
    """
    if not db_url.startswith("sqlite"):
        return None
    tail = db_url.split("///")[-1]
    return Path(tail) if tail else None


def present(engine):
    """Which retired keys still have a row.

    Args:
        engine: An engine bound to the target database.

    Returns:
        list[str]: The keys found, in the order they are declared.
    """
    if TABLE not in set(inspect(engine).get_table_names()):
        return []
    from database.agent_db import AgSetting

    with Session(engine) as session:
        rows = session.query(AgSetting).filter(AgSetting.key.in_(RETIRED_KEYS)).all()
        found = {row.key for row in rows}
    return [key for key in RETIRED_KEYS if key in found]


def status(engine, db_url):
    """Report what would be removed, without removing anything.

    Args:
        engine: An engine bound to the target database, or None.
        db_url: The database URL, for the report.

    Returns:
        bool: True when the report was produced.
    """
    print("Retired voice settings status")
    print("-" * 62)
    path = sqlite_file(db_url)
    if path is not None and not path.exists():
        print("Database file does not exist yet. Not created: --status changes nothing.")
        return True
    found = present(engine)
    if not found:
        print("Nothing to remove. Neither retired key has a row.")
        return True
    for key in found:
        print(f"  {key:<26} present, would be removed")
    print(f"Would remove {len(found)} row(s) from {TABLE}.")
    return True


def apply(engine):
    """Remove whichever retired rows are present.

    Args:
        engine: An engine bound to the target database.

    Returns:
        bool: True on success.
    """
    try:
        found = present(engine)
    except Exception as exc:
        print(f"  [FAIL] Could not read the settings: {type(exc).__name__}: {exc}")
        return False

    if not found:
        print("  Nothing to remove. Neither retired key has a row.")
        return True

    try:
        from database.agent_db import AgSetting

        with Session(engine) as session:
            session.query(AgSetting).filter(AgSetting.key.in_(found)).delete(
                synchronize_session=False
            )
            session.commit()
    except Exception as exc:
        print(f"  [FAIL] Could not remove the retired settings: {exc}")
        return False

    for key in found:
        print(f"  [OK] Removed {key}")
    return True


def main():
    """Entry point.

    Returns:
        int: 0 on success, 1 on failure.
    """
    parser = argparse.ArgumentParser(description="Remove retired voice approval settings")
    parser.add_argument(
        "--status", action="store_true", help="Report what would change without changing it"
    )
    args = parser.parse_args()

    db_url = get_database_url()
    path = sqlite_file(db_url)
    if args.status and path is not None and not path.exists():
        return 0 if status(None, db_url) else 1

    engine = create_engine(db_url)
    try:
        if args.status:
            return 0 if status(engine, db_url) else 1
        print(f"Database: {db_url.split('///')[0]}///...")
        print("\nApplying migration...")
        ok = apply(engine)
        print("-" * 62)
        print("Migration complete." if ok else "Migration failed. See the messages above.")
        return 0 if ok else 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
