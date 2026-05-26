"""
Extract the broker access token from this OpenAlgo deployment's own database.

Intended for the OWNER of a self-hosted OpenAlgo instance who wants to call
broker-native endpoints OpenAlgo does not proxy (e.g., Upstox option-chain
Greeks). This script reuses OpenAlgo's existing Fernet decryption — it does
NOT re-implement crypto.

PRECONDITIONS:
  - Run inside the OpenAlgo venv:    uv run python scripts/extract_broker_token.py
  - .env must contain the same API_KEY_PEPPER used to encrypt the row
  - db/openalgo.db must contain an active Auth row (i.e. you've logged in today
    via the OpenAlgo UI — Indian broker tokens expire daily ~3:00 AM IST)

SECURITY NOTES (read before using):
  - Broker access tokens grant full account access (orders, funds, holdings).
  - Treat the printed value like a password: never paste it into chat, never
    commit it to git, never log it to disk.
  - Tokens expire daily — your token from yesterday is already useless.
  - Calls you make directly against the broker bypass OpenAlgo's traffic logs,
    analyzer, rate limits, action-center approvals, and (post-Apr-2026)
    SEBI static-IP allowlist if your script runs from a different IP.
  - Prefer building the missing feature inside OpenAlgo over scripting against
    a leaked token.

Usage:
  uv run python scripts/extract_broker_token.py            # human-readable
  uv run python scripts/extract_broker_token.py --json     # machine-readable
"""

from __future__ import annotations

import json
import os
import sys

# Make sure we can import OpenAlgo's modules from repo root.
HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
sys.path.insert(0, REPO_ROOT)

# Load .env so API_KEY_PEPPER is available before importing auth_db (which
# fails-fast if the pepper is missing).
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(REPO_ROOT, ".env"))
except ImportError:
    pass  # python-dotenv not strictly required if API_KEY_PEPPER is already exported

if not os.getenv("API_KEY_PEPPER"):
    sys.stderr.write(
        "ERROR: API_KEY_PEPPER not set. Either source the .env that holds it,\n"
        "or export it manually before running this script.\n"
    )
    sys.exit(2)

# Import after env is loaded — auth_db.py hard-fails on a missing pepper.
from database.auth_db import Auth, db_session, decrypt_token  # noqa: E402


def _banner(stream) -> None:
    stream.write("=" * 72 + "\n")
    stream.write("BROKER ACCESS TOKEN — treat as a credential\n")
    stream.write("  - Expires daily at ~3:00 AM IST\n")
    stream.write("  - Do NOT paste into chat / commit / log to disk\n")
    stream.write("  - Direct broker calls bypass OpenAlgo's audit & rate limits\n")
    stream.write("=" * 72 + "\n")


def main(as_json: bool = False) -> int:
    session = db_session()
    try:
        rows = session.query(Auth).all()
    finally:
        session.close()

    if not rows:
        sys.stderr.write(
            "No auth rows in db/openalgo.db. Log in via the OpenAlgo UI to "
            "create one (tokens expire daily, so this is normal first thing "
            "in the morning).\n"
        )
        return 1

    extracted = []
    for row in rows:
        extracted.append({
            "broker": row.broker,
            "name": row.name,
            "user_id": row.user_id,
            "auth_token": decrypt_token(row.auth),
            "feed_token": decrypt_token(row.feed_token) if row.feed_token else None,
        })

    if as_json:
        json.dump(extracted, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    _banner(sys.stderr)
    for r in extracted:
        print(f"broker       : {r['broker']}")
        print(f"name         : {r['name']}")
        print(f"user_id      : {r['user_id']}")
        print(f"auth_token   : {r['auth_token']}")
        if r["feed_token"]:
            print(f"feed_token   : {r['feed_token']}")
        print("-" * 72)
    return 0


if __name__ == "__main__":
    as_json = "--json" in sys.argv[1:]
    sys.exit(main(as_json=as_json))
