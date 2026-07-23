#!/usr/bin/env python3
"""
OpenAlgo Database Initializer and Install Diagnostic (SAFE / READ-MOSTLY)
========================================================================

Creates every OpenAlgo table synchronously, then reports on the state of the
install. Nothing here deletes or overwrites data: table creation is
``CREATE TABLE IF NOT EXISTS`` throughout, so running it against a healthy
install is a no-op that just prints a report.

    uv run python upgrade/init_db.py

Stop OpenAlgo first. Nothing here corrupts a running instance, but the
Historify database is DuckDB, which allows a single writer process -- with the
app up, that one step reports FAILED on a lock it cannot take, which is noise
in a report you are reading to find real problems.

Why this exists
---------------
app.py creates tables on a background thread (see ``_init_databases_and_schedulers``)
and swallows per-database failures into a log line. That is fine at runtime but
useless when an install is misbehaving, because there is no single place to look.
This script does the same work in the foreground and answers the three questions
that actually come up in bug reports:

  1. Which database file is this install really using? ``DATABASE_URL`` is a
     *relative* path by default (``sqlite:///db/openalgo.db``), so it resolves
     against the process working directory. Start the app from somewhere else
     and you silently get a second, empty database.

  2. Do the tables exist, and is there a user account in them?

  3. Do the stored credentials still decrypt with the current
     ``API_KEY_PEPPER`` / ``FERNET_SALT``? A mismatch here is the usual cause
     of "Invalid credentials" on a password the operator knows is right, and
     it is otherwise invisible. See issue #1660.

Exit codes: 0 when everything checks out, 1 when a problem was found that
needs operator action.
"""

import os
import sqlite3
import sys

from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")

sys.path.insert(0, PROJECT_ROOT)

if not os.path.exists(ENV_PATH):
    print(f"ERROR: no .env found at {ENV_PATH}")
    print("Solution: copy .sample.env to .env and configure it, then re-run.")
    sys.exit(1)

# Deliberately load_dotenv() rather than utils.env_check.load_and_check_env_variables():
# a diagnostic must never rotate keys or rewrite .env as a side effect.
load_dotenv(ENV_PATH, override=True)

PLACEHOLDER_PEPPER = "OPENALGO_PLACEHOLDER_API_KEY_PEPPER_REGENERATE_BEFORE_USE"
LEAKED_LITERAL_PEPPER = "a25d94718479b170c16278e321ea6c989358bf499a658fd20c90033cef8ce772"

_problems: list[str] = []


def section(title: str) -> None:
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


def problem(msg: str) -> None:
    _problems.append(msg)
    print(f"  PROBLEM: {msg}")


def resolve_sqlite_path(url: str) -> str | None:
    """Absolute path SQLAlchemy would open for ``url``, or None if not SQLite.

    Mirrors SQLAlchemy's own behaviour: a relative path in the URL is resolved
    against the *current working directory*, not the project root. That
    difference is the whole point of the check below.
    """
    if not url or not url.startswith("sqlite:///"):
        return None
    return os.path.abspath(url.replace("sqlite:///", "", 1))


# --------------------------------------------------------------------------
# 1. Where does this install keep its data?
# --------------------------------------------------------------------------

section("1. Database locations")

cwd = os.getcwd()
print(f"  Project root      : {PROJECT_ROOT}")
print(f"  Working directory : {cwd}")

db_urls = {
    "Main (users, auth)": os.getenv("DATABASE_URL", "sqlite:///db/openalgo.db"),
    "Traffic logs": os.getenv("LOGS_DATABASE_URL", ""),
    "Latency": os.getenv("LATENCY_DATABASE_URL", ""),
    "Health": os.getenv("HEALTH_DATABASE_URL", ""),
    "Sandbox": os.getenv("SANDBOX_DATABASE_URL", ""),
}

main_url = db_urls["Main (users, auth)"]
main_db_path = resolve_sqlite_path(main_url)

if os.path.normcase(os.path.abspath(cwd)) != os.path.normcase(PROJECT_ROOT):
    from_root = os.path.abspath(
        os.path.join(PROJECT_ROOT, main_url.replace("sqlite:///", "", 1))
    ) if main_url.startswith("sqlite:///") else None
    if from_root and from_root != main_db_path:
        problem(
            "You are not running from the project root, and DATABASE_URL is a "
            "relative path. Started from here the app would use\n"
            f"             {main_db_path}\n"
            "           but from the project root it would use\n"
            f"             {from_root}\n"
            "           Those are two different databases. Always start OpenAlgo "
            "from the project root, or set DATABASE_URL to an absolute path."
        )

print()
for label, url in db_urls.items():
    if not url:
        print(f"  {label:<20}: (not configured)")
        continue
    path = resolve_sqlite_path(url)
    if path is None:
        print(f"  {label:<20}: {url}  (not SQLite)")
        continue
    exists = "exists" if os.path.exists(path) else "will be created"
    size = f"{os.path.getsize(path):,} bytes" if os.path.exists(path) else "-"
    print(f"  {label:<20}: {path}")
    print(f"  {'':<20}  {exists}, {size}")

# Stray database directories are a strong signal that the app has been started
# from more than one working directory at some point.
stray = []
for candidate in (cwd, PROJECT_ROOT, os.path.dirname(PROJECT_ROOT)):
    p = os.path.join(candidate, "db", "openalgo.db")
    if os.path.exists(p) and os.path.abspath(p) != main_db_path:
        stray.append(os.path.abspath(p))
if stray:
    print()
    problem(
        "Found other openalgo.db files outside the one in use:\n           "
        + "\n           ".join(stray)
        + "\n           Your account may live in one of those."
    )


# --------------------------------------------------------------------------
# 2. Create every table
# --------------------------------------------------------------------------

section("2. Creating tables")

# Match app.py: relative DATABASE_URL must resolve against the project root.
os.chdir(PROJECT_ROOT)
os.makedirs(os.path.join(PROJECT_ROOT, "db"), exist_ok=True)


def _load_init_functions() -> list:
    """Import the table-creation entry points, mirroring app.py's list."""
    from database.action_center_db import init_db as action_center
    from database.analyzer_db import init_db as analyzer
    from database.apilog_db import init_db as api_log
    from database.auth_db import init_db as auth
    from database.chart_prefs_db import ensure_chart_prefs_tables_exists as chart_prefs
    from database.chartink_db import init_db as chartink
    from database.flow_db import init_db as flow
    from database.historify_db import init_database as historify
    from database.latency_db import init_latency_db as latency
    from database.leverage_db import init_db as leverage
    from database.market_calendar_db import (
        ensure_market_calendar_tables_exists as market_calendar,
    )
    from database.qty_freeze_db import ensure_qty_freeze_tables_exists as qty_freeze
    from database.sandbox_db import init_db as sandbox
    from database.scalping_db import init_db as scalping
    from database.settings_db import init_db as settings
    from database.strategy_db import init_db as strategy
    from database.strategy_portfolio_db import (
        ensure_strategy_portfolio_tables_exists as strategy_portfolio,
    )
    from database.symbol import init_db as master_contract
    from database.traffic_db import init_logs_db as traffic_logs
    from database.user_db import init_db as user

    return [
        ("Auth DB", auth),
        ("User DB", user),
        ("Master Contract DB", master_contract),
        ("API Log DB", api_log),
        ("Analyzer DB", analyzer),
        ("Settings DB", settings),
        ("Chartink DB", chartink),
        ("Traffic Logs DB", traffic_logs),
        ("Latency DB", latency),
        ("Strategy DB", strategy),
        ("Sandbox DB", sandbox),
        ("Action Center DB", action_center),
        ("Chart Prefs DB", chart_prefs),
        ("Market Calendar DB", market_calendar),
        ("Qty Freeze DB", qty_freeze),
        ("Historify DB", historify),
        ("Flow DB", flow),
        ("Scalping DB", scalping),
        ("Leverage DB", leverage),
        ("Strategy Portfolio DB", strategy_portfolio),
    ]


try:
    init_functions = _load_init_functions()
except RuntimeError as e:
    # database/user_db.py raises this when API_KEY_PEPPER is missing or too short.
    print(f"  FAILED to import database modules: {e}")
    sys.exit(1)

# Serial, not the ThreadPoolExecutor app.py uses. A diagnostic wants a stable
# ordering and one clear failure at a time, and 20 CREATE TABLE IF NOT EXISTS
# batches are fast enough that the parallelism buys nothing here.
failed = 0
for name, func in init_functions:
    try:
        func()
        print(f"  ok      {name}")
    except Exception as e:
        failed += 1
        print(f"  FAILED  {name}: {e}")

if failed:
    problem(f"{failed} database(s) failed to initialize (see above).")


# --------------------------------------------------------------------------
# 3. What is actually in the main database?
# --------------------------------------------------------------------------

section("3. Account state")

users: list[tuple] = []
if main_db_path and os.path.exists(main_db_path):
    try:
        with sqlite3.connect(f"file:{main_db_path}?mode=ro", uri=True) as conn:
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
            ]
            print(f"  Tables present    : {len(tables)}")

            if "users" not in tables:
                problem("The 'users' table does not exist. Table creation did not complete.")
            else:
                users = list(
                    conn.execute("SELECT username, email, is_admin FROM users")
                )
                print(f"  User accounts     : {len(users)}")
                for username, email, is_admin in users:
                    role = "admin" if is_admin else "user"
                    print(f"    - {username} <{email}> ({role})")
                if not users:
                    print()
                    print("  No account exists yet. Start OpenAlgo and visit /setup to")
                    print("  create one. This is the expected state on a fresh install.")

            for table, label in (("auth", "Broker sessions"), ("api_keys", "API keys")):
                if table in tables:
                    n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    print(f"  {label:<18}: {n}")
    except sqlite3.Error as e:
        problem(f"Could not read {main_db_path}: {e}")
else:
    problem(f"Main database file not found at {main_db_path}")


# --------------------------------------------------------------------------
# 4. Do stored credentials still decrypt?
# --------------------------------------------------------------------------

section("4. Credential health (API_KEY_PEPPER / FERNET_SALT)")

pepper = os.getenv("API_KEY_PEPPER", "")
salt = (os.getenv("FERNET_SALT") or "").strip()

if pepper in (PLACEHOLDER_PEPPER, LEAKED_LITERAL_PEPPER):
    problem(
        "API_KEY_PEPPER is the publicly-known sample value. Every broker token, "
        "API key and TOTP secret in this database is decryptable by anyone who "
        "obtains the file."
    )
else:
    print(f"  API_KEY_PEPPER    : set, {len(pepper)} chars (value not shown)")

print(f"  FERNET_SALT       : {'set' if salt else 'NOT SET (legacy static salt in use)'}")

# The real test. users.totp_secret is written by add_user() at the same moment
# the password hash is written, with the same pepper. If it no longer decrypts,
# the pepper (or salt) has changed since the account was created -- which means
# the Argon2 password hash is dead too. That is invisible from the login page,
# where it surfaces only as "Invalid credentials".
if users and main_db_path and os.path.exists(main_db_path):
    try:
        from cryptography.fernet import InvalidToken

        from database.auth_db import fernet

        with sqlite3.connect(f"file:{main_db_path}?mode=ro", uri=True) as conn:
            secrets_rows = [
                r[0]
                for r in conn.execute(
                    "SELECT totp_secret FROM users WHERE totp_secret IS NOT NULL "
                    "AND totp_secret != ''"
                )
            ]

        undecryptable = 0
        for ct in secrets_rows:
            try:
                fernet.decrypt(ct.encode() if isinstance(ct, str) else ct)
            except (InvalidToken, AttributeError, ValueError):
                undecryptable += 1

        if not secrets_rows:
            print("  Stored secrets    : none to check")
        elif undecryptable == 0:
            print("  Stored secrets    : decrypt correctly")
            print()
            print("  The pepper in .env matches the one your account was created with,")
            print("  so a login failure is NOT a pepper problem. Check the username")
            print("  (it is case-sensitive and is not your email address).")
        else:
            problem(
                f"{undecryptable} of {len(secrets_rows)} stored secret(s) do not "
                "decrypt with the current API_KEY_PEPPER / FERNET_SALT.\n"
                "           Your account was created under DIFFERENT values than the "
                "ones now in .env.\n"
                "           This is exactly what causes 'Invalid credentials' on a "
                "password you know is correct:\n"
                "           the Argon2 password hash is bound to the old pepper and "
                "cannot be migrated.\n"
                "\n"
                "           Fix, best option first:\n"
                "             1. Restore API_KEY_PEPPER and FERNET_SALT from your .env "
                "backup and restart.\n"
                "                Only this keeps your existing password and broker tokens.\n"
                "             2. Reset the password against the current pepper:\n"
                "                  uv run python upgrade/reset_admin_password.py\n"
                "                Broker tokens and the stored API key stay unreadable; "
                "re-login to your\n"
                "                broker and regenerate the API key at /apikey afterwards.\n"
                "             3. On a throwaway install, delete db/openalgo.db and "
                "restart to start over."
            )
    except Exception as e:
        print(f"  Could not run the decryption check: {e}")
elif not users:
    print("  Stored secrets    : no accounts yet, nothing to check")


# --------------------------------------------------------------------------

section("Summary")

if _problems:
    print(f"  {len(_problems)} problem(s) found:")
    print()
    for i, msg in enumerate(_problems, 1):
        print(f"  {i}. {msg.splitlines()[0]}")
    print()
    print("  Scroll up for the full detail and suggested fix for each.")
    sys.exit(1)

print("  All tables present and all checks passed.")
print()
print("  If you still cannot log in, the cause is not the database. Confirm the")
print("  username (case-sensitive, and not your email address), then report the")
print("  issue with the FULL startup output from the very first line -- the part")
print("  printed before 'Starting OpenAlgo...' is the part that matters.")
sys.exit(0)
