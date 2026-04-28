#!/usr/bin/env python3
"""
OpenAlgo PEPPER Rotation Migration (DESTRUCTIVE)
=================================================

This script rotates API_KEY_PEPPER and re-encrypts every field that is
stored under a PEPPER-derived Fernet key. It is **destructive** in two
specific senses:

  1. Existing Argon2 password hashes (users.password_hash, apikeys.api_key_hash)
     cannot be migrated — Argon2 is one-way. After the rotation:
       - Users must reset their password via /auth/reset-password with TOTP.
       - apikeys.api_key_hash is re-derived from the (decrypted-then-re-encrypted)
         api_key_encrypted column — so external integrations that already
         have the API key value continue to work without action.
  2. The rotation overwrites .env in place with the new PEPPER value.

This script is NOT registered in upgrade/migrate_all.py because of (1).
It must be run explicitly by the operator at a controlled moment:

    cd upgrade
    uv run rotate_pepper.py            # interactive prompt
    uv run rotate_pepper.py --yes      # non-interactive

Pre-flight:
  1. Stop OpenAlgo (kill the running process / systemctl stop openalgo).
  2. Back up db/openalgo.db (the script also creates a backup, but
     belt-and-braces).
  3. Make sure no other writer is touching the DB.

Post-flight:
  1. Restart OpenAlgo.
  2. Visit /auth/reset-password and use your TOTP code to set a new
     password (your TOTP secret survives the rotation; only password
     hashes are invalidated).
  3. Confirm you can log in with the new password.

Columns rotated:
  auth_db Fernet (PBKDF2-SHA256, salt=b"openalgo_static_salt"):
    - auth.auth
    - auth.feed_token
    - auth.secret_api_key  (was plaintext for some installs)
    - apikeys.api_key_encrypted
    - users.totp_secret    (was plaintext for some installs)
    - flow_workflows.api_key   (was plaintext for some installs)
  apikeys.api_key_hash:
    - re-derived from the decrypted api_key plaintext (Argon2 + new pepper)
  telegram_db Fernet (PBKDF2-SHA256, salt=TELEGRAM_KEY_SALT):
    - telegram_users.encrypted_api_key
    - bot_config.token     (was plaintext for some installs)
  settings_db Fernet (raw 32-byte pepper, base64-encoded):
    - settings.smtp_password_encrypted

Idempotence: each row is processed once per run. Running the script twice
performs two rotations (each with its own re-encryption pass + password
reset requirement). There is no "skip if already rotated" mode — by design,
because every run rotates to a *new* random pepper.
"""

import argparse
import base64
import os
import re
import secrets
import shutil
import sqlite3
import sys
import time
from datetime import datetime

from argon2 import PasswordHasher
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from dotenv import load_dotenv

# Ensure project root is on sys.path so the dotenv pickup works the same
# way it does in app.py.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")

# Load env vars so DATABASE_URL etc. are available
load_dotenv(ENV_PATH)


# ---------- Fernet key derivations (must match the three modules) ----------

def _auth_db_fernet(pepper: str) -> Fernet:
    """Match database/auth_db.py:get_encryption_key()."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"openalgo_static_salt",
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(pepper.encode()))
    return Fernet(key)


def _telegram_db_fernet(pepper: str) -> Fernet:
    """Match database/telegram_db.py:get_encryption_key()."""
    salt = os.getenv("TELEGRAM_KEY_SALT", "telegram-openalgo-salt").encode()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(pepper.encode()))
    return Fernet(key)


def _settings_db_fernet(pepper: str) -> Fernet:
    """Match database/settings_db.py:_get_encryption_key().
    NB: settings_db uses raw pepper (no PBKDF2), padded/truncated to 32 bytes.
    """
    key = base64.urlsafe_b64encode(pepper.ljust(32)[:32].encode())
    return Fernet(key)


# ---------- Helpers ----------

def _resolve_db_path() -> str:
    """Resolve DATABASE_URL to an absolute SQLite path."""
    db_url = os.getenv("DATABASE_URL", "sqlite:///db/openalgo.db")
    m = re.match(r"sqlite:///(.+)", db_url)
    if not m:
        sys.stderr.write(
            f"\nThis script only supports SQLite. DATABASE_URL={db_url!r}\n"
            "For Postgres/MySQL, adapt the script to your connection style.\n"
        )
        sys.exit(2)
    db_path = m.group(1)
    if not os.path.isabs(db_path):
        db_path = os.path.join(PROJECT_ROOT, db_path)
    return db_path


def _atomic_rewrite_env_pepper(env_path: str, old_pepper: str, new_pepper: str) -> None:
    """Replace API_KEY_PEPPER in .env atomically, preserving all other
    content and line endings. Same pattern as utils/env_check.py.
    """
    with open(env_path, "r", encoding="utf-8", newline="") as f:
        content = f.read()

    if old_pepper not in content:
        # Operator may have changed the formatting; do a regex line replace
        # as a fallback so we don't corrupt the file.
        new_content, n = re.subn(
            r"^(API_KEY_PEPPER\s*=\s*)(['\"])([^'\"]*)\2",
            lambda m: f"{m.group(1)}{m.group(2)}{new_pepper}{m.group(2)}",
            content,
            count=1,
            flags=re.MULTILINE,
        )
        if n != 1:
            raise RuntimeError(
                "Could not locate API_KEY_PEPPER line in .env to update. "
                "Manual edit required."
            )
        content = new_content
    else:
        content = content.replace(old_pepper, new_pepper, 1)

    tmp = env_path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    if os.name != "nt":
        os.chmod(tmp, 0o600)

    # os.replace retry for Windows file-lock collisions
    for attempt in range(3):
        try:
            os.replace(tmp, env_path)
            return
        except OSError:
            if os.name != "nt" or attempt == 2:
                raise
            time.sleep(0.15)


def _try_decrypt(fernet: Fernet, value: str) -> tuple[str, bool]:
    """Attempt Fernet decrypt. Returns (plaintext_or_original, was_encrypted).
    If decryption fails, returns the original value unchanged with was_encrypted=False
    so the caller can encrypt-as-plaintext.
    """
    if value is None:
        return None, False
    try:
        return fernet.decrypt(value.encode()).decode(), True
    except (InvalidToken, ValueError, Exception):
        return value, False


def _encrypt(fernet: Fernet, plaintext: str) -> str:
    """Encrypt plaintext with the given Fernet."""
    if plaintext is None:
        return None
    return fernet.encrypt(plaintext.encode()).decode()


# ---------- Per-table rotation logic ----------

class Rotator:
    """Walks the DB rotating ciphertexts from old_pepper to new_pepper."""

    def __init__(self, conn: sqlite3.Connection, old_pepper: str, new_pepper: str):
        self.conn = conn
        self.old_auth = _auth_db_fernet(old_pepper)
        self.new_auth = _auth_db_fernet(new_pepper)
        self.old_telegram = _telegram_db_fernet(old_pepper)
        self.new_telegram = _telegram_db_fernet(new_pepper)
        self.old_settings = _settings_db_fernet(old_pepper)
        self.new_settings = _settings_db_fernet(new_pepper)
        # ph for re-hashing api_key_hash. Argon2 verifier needs the new pepper
        # appended to the plaintext key, then ph.hash() with default params.
        self.ph = PasswordHasher()
        self.new_pepper = new_pepper
        self.stats = {
            "auth.auth": 0,
            "auth.feed_token": 0,
            "auth.secret_api_key": 0,
            "auth.secret_api_key_plaintext_promoted": 0,
            "api_keys.api_key_encrypted": 0,
            "api_keys.api_key_hash": 0,
            "users.totp_secret": 0,
            "users.totp_secret_plaintext_promoted": 0,
            "settings.smtp_password_encrypted": 0,
            "telegram_users.encrypted_api_key": 0,
            "bot_config.token": 0,
            "bot_config.token_plaintext_promoted": 0,
            "flow_workflows.api_key": 0,
            "flow_workflows.api_key_plaintext_promoted": 0,
        }

    def _table_exists(self, name: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        )
        return cur.fetchone() is not None

    def _rotate_auth_fernet_column(
        self, table: str, key_col: str, value_col: str, allow_plaintext: bool
    ) -> int:
        """Re-encrypt rows in `table.value_col` from old_auth to new_auth.

        If `allow_plaintext` is True, rows that fail to decrypt are treated
        as plaintext (transition from a pre-migration plaintext column) and
        re-stored as ciphertext encrypted with new_auth.
        """
        if not self._table_exists(table):
            return 0
        cur = self.conn.execute(f"SELECT {key_col}, {value_col} FROM {table}")
        rows = cur.fetchall()
        rotated = 0
        promoted_plaintext = 0
        for pk, val in rows:
            if val is None or val == "":
                continue
            plaintext, was_encrypted = _try_decrypt(self.old_auth, val)
            if not was_encrypted and not allow_plaintext:
                # Don't silently re-encrypt unknown junk into the column.
                # Skip and warn.
                print(f"  WARN: {table}.{value_col} row {pk}: cannot decrypt, leaving alone")
                continue
            new_ct = _encrypt(self.new_auth, plaintext)
            self.conn.execute(
                f"UPDATE {table} SET {value_col} = ? WHERE {key_col} = ?",
                (new_ct, pk),
            )
            rotated += 1
            if not was_encrypted:
                promoted_plaintext += 1
        return rotated, promoted_plaintext if allow_plaintext else (rotated, 0)

    def rotate_all(self):
        # ---- auth.auth ----
        if self._table_exists("auth"):
            cur = self.conn.execute("SELECT id, auth, feed_token, secret_api_key FROM auth")
            for row_id, auth_v, feed_v, samco_v in cur.fetchall():
                if auth_v:
                    pt, was_enc = _try_decrypt(self.old_auth, auth_v)
                    if was_enc:
                        self.conn.execute(
                            "UPDATE auth SET auth = ? WHERE id = ?",
                            (_encrypt(self.new_auth, pt), row_id),
                        )
                        self.stats["auth.auth"] += 1
                    else:
                        print(f"  WARN: auth.auth row {row_id}: cannot decrypt, leaving alone")
                if feed_v:
                    pt, was_enc = _try_decrypt(self.old_auth, feed_v)
                    if was_enc:
                        self.conn.execute(
                            "UPDATE auth SET feed_token = ? WHERE id = ?",
                            (_encrypt(self.new_auth, pt), row_id),
                        )
                        self.stats["auth.feed_token"] += 1
                    else:
                        print(f"  WARN: auth.feed_token row {row_id}: cannot decrypt, leaving alone")
                if samco_v:
                    pt, was_enc = _try_decrypt(self.old_auth, samco_v)
                    self.conn.execute(
                        "UPDATE auth SET secret_api_key = ? WHERE id = ?",
                        (_encrypt(self.new_auth, pt), row_id),
                    )
                    self.stats["auth.secret_api_key"] += 1
                    if not was_enc:
                        self.stats["auth.secret_api_key_plaintext_promoted"] += 1

        # ---- apikeys: decrypt with old, re-encrypt with new, RE-HASH ----
        if self._table_exists("api_keys"):
            cur = self.conn.execute(
                "SELECT id, api_key_encrypted, api_key_hash FROM api_keys"
            )
            for row_id, enc_v, _hash_v in cur.fetchall():
                if enc_v is None:
                    continue
                pt, was_enc = _try_decrypt(self.old_auth, enc_v)
                if not was_enc:
                    print(f"  WARN: apikeys row {row_id}: api_key_encrypted does not decrypt, leaving alone")
                    continue
                # Re-encrypt with new pepper
                new_ct = _encrypt(self.new_auth, pt)
                # Re-hash with new pepper
                new_hash = self.ph.hash(pt + self.new_pepper)
                self.conn.execute(
                    "UPDATE api_keys SET api_key_encrypted = ?, api_key_hash = ? WHERE id = ?",
                    (new_ct, new_hash, row_id),
                )
                self.stats["api_keys.api_key_encrypted"] += 1
                self.stats["api_keys.api_key_hash"] += 1

        # ---- users.totp_secret ----
        if self._table_exists("users"):
            cur = self.conn.execute("SELECT id, totp_secret FROM users")
            for row_id, totp_v in cur.fetchall():
                if not totp_v:
                    continue
                pt, was_enc = _try_decrypt(self.old_auth, totp_v)
                self.conn.execute(
                    "UPDATE users SET totp_secret = ? WHERE id = ?",
                    (_encrypt(self.new_auth, pt), row_id),
                )
                self.stats["users.totp_secret"] += 1
                if not was_enc:
                    self.stats["users.totp_secret_plaintext_promoted"] += 1

        # ---- settings.smtp_password_encrypted (uses settings_db Fernet) ----
        if self._table_exists("settings"):
            cur = self.conn.execute("SELECT id, smtp_password_encrypted FROM settings")
            for row_id, smtp_v in cur.fetchall():
                if not smtp_v:
                    continue
                try:
                    pt = self.old_settings.decrypt(smtp_v.encode()).decode()
                except (InvalidToken, ValueError):
                    print(f"  WARN: settings.smtp_password_encrypted row {row_id}: cannot decrypt, leaving alone")
                    continue
                new_ct = self.new_settings.encrypt(pt.encode()).decode()
                self.conn.execute(
                    "UPDATE settings SET smtp_password_encrypted = ? WHERE id = ?",
                    (new_ct, row_id),
                )
                self.stats["settings.smtp_password_encrypted"] += 1

        # ---- telegram_users.encrypted_api_key (telegram_db Fernet) ----
        if self._table_exists("telegram_users"):
            cur = self.conn.execute("SELECT id, encrypted_api_key FROM telegram_users")
            for row_id, tg_v in cur.fetchall():
                if not tg_v:
                    continue
                try:
                    pt = self.old_telegram.decrypt(tg_v.encode()).decode()
                except (InvalidToken, ValueError):
                    print(f"  WARN: telegram_users.encrypted_api_key row {row_id}: cannot decrypt, leaving alone")
                    continue
                new_ct = self.new_telegram.encrypt(pt.encode()).decode()
                self.conn.execute(
                    "UPDATE telegram_users SET encrypted_api_key = ? WHERE id = ?",
                    (new_ct, row_id),
                )
                self.stats["telegram_users.encrypted_api_key"] += 1

        # ---- bot_config.token (was plaintext, telegram_db Fernet for new) ----
        if self._table_exists("bot_config"):
            cur = self.conn.execute("SELECT id, token FROM bot_config")
            for row_id, tok_v in cur.fetchall():
                if not tok_v:
                    continue
                try:
                    pt = self.old_telegram.decrypt(tok_v.encode()).decode()
                    was_enc = True
                except (InvalidToken, ValueError):
                    pt = tok_v
                    was_enc = False
                new_ct = self.new_telegram.encrypt(pt.encode()).decode()
                self.conn.execute(
                    "UPDATE bot_config SET token = ? WHERE id = ?",
                    (new_ct, row_id),
                )
                self.stats["bot_config.token"] += 1
                if not was_enc:
                    self.stats["bot_config.token_plaintext_promoted"] += 1

        # ---- flow_workflows.api_key (was plaintext, auth_db Fernet for new) ----
        if self._table_exists("flow_workflows"):
            cur = self.conn.execute("SELECT id, api_key FROM flow_workflows")
            for row_id, ak_v in cur.fetchall():
                if not ak_v:
                    continue
                pt, was_enc = _try_decrypt(self.old_auth, ak_v)
                self.conn.execute(
                    "UPDATE flow_workflows SET api_key = ? WHERE id = ?",
                    (_encrypt(self.new_auth, pt), row_id),
                )
                self.stats["flow_workflows.api_key"] += 1
                if not was_enc:
                    self.stats["flow_workflows.api_key_plaintext_promoted"] += 1


# ---------- Main ----------

def main():
    parser = argparse.ArgumentParser(description="Rotate API_KEY_PEPPER and re-encrypt all dependent fields")
    parser.add_argument("--yes", action="store_true", help="Skip the interactive confirmation prompt")
    parser.add_argument("--db", help="Path to SQLite DB (defaults to DATABASE_URL from .env)")
    parser.add_argument("--env", help="Path to .env file to update (defaults to project root .env)")
    parser.add_argument("--dry-run", action="store_true", help="Run rotation in a DB transaction but rollback at the end (no .env update)")
    args = parser.parse_args()

    env_path = args.env or ENV_PATH
    db_path = args.db or _resolve_db_path()
    old_pepper = os.getenv("API_KEY_PEPPER", "")
    if not old_pepper:
        sys.stderr.write("API_KEY_PEPPER is not set in .env. Aborting.\n")
        return 2
    if not os.path.exists(db_path):
        sys.stderr.write(f"Database not found at {db_path}. Aborting.\n")
        return 2

    new_pepper = secrets.token_hex(32)

    print()
    print("=" * 72)
    print("  OpenAlgo PEPPER Rotation Migration")
    print("=" * 72)
    print(f"  DB path     : {db_path}")
    print(f"  .env path   : {env_path}")
    print(f"  Mode        : {'DRY RUN (no changes persisted)' if args.dry_run else 'DESTRUCTIVE'}")
    print()
    print("  This will:")
    print("    1. Re-encrypt every PEPPER-derived ciphertext in the DB.")
    print("    2. Encrypt previously-plaintext credential columns.")
    print("    3. Re-hash apikeys.api_key_hash (Argon2 needs new pepper).")
    print("    4. Replace API_KEY_PEPPER in .env atomically.")
    print()
    print("  After this runs, you must:")
    print("    - Use /auth/reset-password (with TOTP) to set a new password.")
    print("    - Existing browser sessions remain valid (APP_KEY unchanged).")
    print()

    if not args.yes and not args.dry_run:
        try:
            ans = input("  Type 'yes' to proceed: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print()
            return 1
        if ans != "yes":
            print("Aborted.")
            return 1

    # Backup DB
    if not args.dry_run:
        backup_dir = os.path.join(os.path.dirname(db_path), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(backup_dir, f"openalgo.db.before-rotate-pepper-{ts}")
        shutil.copy2(db_path, backup_path)
        print(f"  DB backup   : {backup_path}")

    # Connect (single transaction)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    print()
    print("  Rotating ciphertexts...")
    print()
    rotator = Rotator(conn, old_pepper, new_pepper)
    try:
        rotator.rotate_all()
    except Exception as e:
        conn.rollback()
        sys.stderr.write(f"\n  FAILED: {e}\n  Rolled back. DB unchanged.\n")
        conn.close()
        return 1

    if args.dry_run:
        conn.rollback()
        conn.close()
        print()
        print("  Dry-run complete. Stats (would have been applied):")
        for k, v in rotator.stats.items():
            print(f"    {k:48s} {v:>5d}")
        return 0

    conn.commit()
    conn.close()

    # Update .env atomically
    print()
    print("  Updating .env with new API_KEY_PEPPER...")
    try:
        _atomic_rewrite_env_pepper(env_path, old_pepper, new_pepper)
    except Exception as e:
        sys.stderr.write(
            f"\n  FAILED to update .env: {e}\n"
            f"  DB has been rotated but .env was not. Update .env manually:\n"
            f"    API_KEY_PEPPER = '{new_pepper}'\n"
        )
        return 1

    print()
    print("=" * 72)
    print("  Rotation complete")
    print("=" * 72)
    print()
    print("  Stats:")
    for k, v in rotator.stats.items():
        if v > 0:
            print(f"    {k:48s} {v:>5d}")
    print()
    print("  Next steps:")
    print("    1. Restart OpenAlgo: uv run app.py  (or systemctl restart …)")
    print("    2. Open the web UI and go to /auth/reset-password")
    print("    3. Reset your password using your TOTP code")
    print("    4. Log in normally with the new password")
    print()
    print("  Your TOTP secret was preserved (re-encrypted, not regenerated).")
    print("  Your broker session is preserved (broker token re-encrypted).")
    print("  Your TradingView/external API keys are preserved (re-encrypted +")
    print("  api_key_hash re-derived). External integrations continue to work.")
    print()
    print("  The previous PEPPER is no longer in your .env. The DB no longer")
    print("  contains anything decryptable with the public sample value.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
