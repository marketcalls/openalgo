#!/usr/bin/env python3
"""
OpenAlgo Local Password Reset (RECOVERY)
========================================

Sets a new password for an OpenAlgo account from the command line, hashed with
the ``API_KEY_PEPPER`` currently in ``.env``.

    uv run python upgrade/reset_admin_password.py

Why this exists
---------------
The in-app recovery at ``/auth/reset-password`` needs either configured SMTP or
an enrolled TOTP authenticator. A fresh install has neither: SMTP is unset until
the operator configures it in Profile settings, and the TOTP QR code is shown
exactly once during setup and is easy to skip. An operator who cannot log in
therefore has no route back in at all -- ``upgrade/rotate_pepper.py`` even ends
by telling them to use the reset flow they cannot reach. See issue #1660.

This is consistent with the deployment model: OpenAlgo is single-user and
self-hosted, so whoever can run this script already has the server and the
database file. It grants no access that filesystem access did not already give.

What it does NOT fix
--------------------
If the password stopped working because ``API_KEY_PEPPER`` changed, the password
is only half the damage. Broker tokens, stored API keys and TOTP secrets are
Fernet-encrypted under the same pepper and cannot be recovered by re-hashing.
The script detects that case, says so plainly, and tells you what to redo. It
never silently papers over it.

Stop OpenAlgo before running this -- a live process caches the user row for 30
seconds (``username_cache`` in database/user_db.py) and will keep accepting the
old password until that expires.
"""

import argparse
import getpass
import os
import sqlite3
import sys

from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")

sys.path.insert(0, PROJECT_ROOT)

if not os.path.exists(ENV_PATH):
    print(f"ERROR: no .env found at {ENV_PATH}")
    sys.exit(1)

load_dotenv(ENV_PATH, override=True)

# Relative DATABASE_URL must resolve against the project root, exactly as it
# does when app.py is started correctly.
os.chdir(PROJECT_ROOT)


def resolve_main_db() -> str | None:
    url = os.getenv("DATABASE_URL", "sqlite:///db/openalgo.db")
    if not url.startswith("sqlite:///"):
        return None
    return os.path.abspath(url.replace("sqlite:///", "", 1))


def check_credential_health(db_path: str, username: str) -> bool:
    """Report whether this account's stored secrets decrypt with today's pepper.

    ``users.totp_secret`` is written by ``add_user()`` in the same transaction
    as the password hash, under the same pepper. If it will not decrypt now,
    the pepper or salt changed since the account was created -- which is also
    why the password stopped verifying.

    Returns True when the credentials are healthy (or there is nothing to
    check), False when drift was detected.
    """
    try:
        from cryptography.fernet import InvalidToken

        from database.auth_db import fernet
    except Exception as e:
        print(f"  Could not load the decryption key to check: {e}")
        return True

    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            row = conn.execute(
                "SELECT totp_secret FROM users WHERE username = ?", (username,)
            ).fetchone()
    except sqlite3.Error as e:
        print(f"  Could not read the stored secret to check: {e}")
        return True

    if not row or not row[0]:
        return True

    try:
        fernet.decrypt(row[0].encode() if isinstance(row[0], str) else row[0])
        return True
    except (InvalidToken, AttributeError, ValueError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reset an OpenAlgo account password from the command line"
    )
    parser.add_argument(
        "--username",
        help="Account to reset. Defaults to the single admin account when there is only one.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List accounts and exit without changing anything",
    )
    args = parser.parse_args()

    db_path = resolve_main_db()
    if db_path and not os.path.exists(db_path):
        print(f"ERROR: database not found at {db_path}")
        print("Run 'uv run python upgrade/init_db.py' first to check your install.")
        return 1

    print()
    print("=" * 72)
    print("  OpenAlgo Local Password Reset")
    print("=" * 72)
    print(f"  Database : {db_path}")
    print(f"  .env     : {ENV_PATH}")
    print()

    try:
        from database.user_db import User, db_session
    except RuntimeError as e:
        # user_db raises this when API_KEY_PEPPER is missing or under 32 chars.
        print(f"ERROR: {e}")
        return 1

    try:
        users = User.query.order_by(User.id).all()

        if not users:
            print("  No accounts exist in this database.")
            print("  Start OpenAlgo and visit /setup to create one.")
            return 1

        if args.list:
            print("  Accounts:")
            for u in users:
                print(f"    - {u.username} <{u.email}> ({'admin' if u.is_admin else 'user'})")
            return 0

        if args.username:
            user = next((u for u in users if u.username == args.username), None)
            if user is None:
                print(f"  ERROR: no account named '{args.username}'.")
                print("  Usernames are case-sensitive. Known accounts:")
                for u in users:
                    print(f"    - {u.username}")
                return 1
        else:
            admins = [u for u in users if u.is_admin]
            candidates = admins or users
            if len(candidates) != 1:
                print("  More than one account exists. Choose one with --username:")
                for u in candidates:
                    print(f"    - {u.username} <{u.email}>")
                return 1
            user = candidates[0]

        print(f"  Resetting password for: {user.username} <{user.email}>")
        print()

        healthy = check_credential_health(db_path, user.username) if db_path else True
        if not healthy:
            print("  " + "-" * 68)
            print("  WARNING: this account's stored secrets do not decrypt with the")
            print("  API_KEY_PEPPER currently in .env. The pepper (or FERNET_SALT)")
            print("  changed after the account was created. That is why your password")
            print("  stopped working, and resetting it here will get you logged in --")
            print("  but the following are encrypted under the OLD pepper and are NOT")
            print("  recoverable by this script:")
            print()
            print("    - broker auth and feed tokens  -> log in to your broker again")
            print("    - stored API key               -> regenerate it at /apikey")
            print("    - TOTP secret                  -> re-enrol 2FA if you used it")
            print()
            print("  If you have a backup of your original .env, STOP NOW. Restoring")
            print("  its API_KEY_PEPPER and FERNET_SALT lines recovers everything,")
            print("  including your existing password. This reset does not.")
            print("  " + "-" * 68)
            print()
            if input("  Continue with the reset anyway? (yes/N): ").strip().lower() not in (
                "yes",
                "y",
            ):
                print("  Cancelled. Nothing was changed.")
                return 1
            print()

        password = getpass.getpass("  New password: ")
        confirm = getpass.getpass("  Confirm password: ")

        if password != confirm:
            print()
            print("  ERROR: passwords do not match. Nothing was changed.")
            return 1

        from utils.auth_utils import validate_password_strength

        is_valid, error_message = validate_password_strength(password)
        if not is_valid:
            print()
            print(f"  ERROR: {error_message}")
            print("  Nothing was changed.")
            return 1

        user.set_password(password)
        db_session.commit()

        print()
        print("  Password updated.")
        print()
        print("  Next steps:")
        print(f"    1. Restart OpenAlgo, then log in as '{user.username}'.")
        if not healthy:
            print("    2. Log in to your broker again (the stored token is unreadable).")
            print("    3. Regenerate your API key at /apikey and update any external")
            print("       integrations (TradingView, Amibroker, Python scripts).")
        print()
        print("  Keep a backup of .env from now on -- 'cp .env .env.backup'. Losing")
        print("  API_KEY_PEPPER or FERNET_SALT makes login and stored credentials")
        print("  unrecoverable.")
        return 0

    except Exception as e:
        db_session.rollback()
        print()
        print(f"  ERROR: {e}")
        return 1
    finally:
        # Plain script, no Flask teardown to drop the scoped session for us.
        db_session.remove()


if __name__ == "__main__":
    sys.exit(main())
