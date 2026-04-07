#!/usr/bin/env python
"""
Encrypt Sensitive Data Migration Script for OpenAlgo

This migration encrypts existing plaintext sensitive data in the database:
- Samco secret_api_key in auth table (VULN-008)
- SMTP password re-encryption with PBKDF2 KDF (VULN-009)
- Telegram bot token in bot_config table (VULN-012)
- Flow workflow API keys in flow_workflows table (VULN-013)
- TOTP secrets in users table (VULN-014)

Usage:
    cd upgrade
    uv run migrate_encrypt_sensitive_data.py           # Apply migration
    uv run migrate_encrypt_sensitive_data.py --status  # Check status

Created: 2026-04-08
"""

import argparse
import base64
import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from sqlalchemy import create_engine, inspect, text

from utils.logging import get_logger

logger = get_logger(__name__)

# Migration metadata
MIGRATION_NAME = "encrypt_sensitive_data"
MIGRATION_VERSION = "001"

# Load environment
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(parent_dir, ".env"))


def get_engine(db_env_var="DATABASE_URL", default_path="db/openalgo.db"):
    """Get database engine"""
    database_url = os.getenv(db_env_var, f"sqlite:///{default_path}")

    if database_url.startswith("sqlite:///"):
        db_path = database_url.replace("sqlite:///", "")
        if not os.path.isabs(db_path):
            db_path = os.path.join(parent_dir, db_path)
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        database_url = f"sqlite:///{db_path}"

    return create_engine(database_url)


def get_fernet():
    """Get the Fernet cipher used by auth_db for encryption"""
    pepper = os.getenv("API_KEY_PEPPER")
    if not pepper:
        logger.error("API_KEY_PEPPER environment variable is required")
        return None
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"openalgo_static_salt",
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(pepper.encode()))
    return Fernet(key)


def get_telegram_fernet():
    """Get the Fernet cipher used by telegram_db for encryption"""
    pepper = os.getenv("API_KEY_PEPPER")
    if not pepper:
        return None
    salt = os.getenv("TELEGRAM_KEY_SALT", "telegram-openalgo-salt").encode()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(pepper.encode()))
    return Fernet(key)


def is_already_encrypted(value, fernet_instance):
    """Check if a value is already Fernet-encrypted"""
    if not value:
        return True  # Treat empty as "no action needed"
    try:
        fernet_instance.decrypt(value.encode())
        return True
    except (InvalidToken, Exception):
        return False


def encrypt_value(value, fernet_instance):
    """Encrypt a plaintext value"""
    if not value:
        return value
    return fernet_instance.encrypt(value.encode()).decode()


def get_smtp_legacy_key():
    """Get the legacy SMTP encryption key (ljust padding method)"""
    pepper = os.getenv("API_KEY_PEPPER", "default-pepper-key")
    key = base64.urlsafe_b64encode(pepper.ljust(32)[:32].encode())
    return key


def get_smtp_new_key():
    """Get the new SMTP encryption key (PBKDF2 method)"""
    pepper = os.getenv("API_KEY_PEPPER")
    if not pepper:
        return None
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"openalgo_smtp_salt",
        iterations=100000,
    )
    return base64.urlsafe_b64encode(kdf.derive(pepper.encode()))


def upgrade():
    """Apply the migration - encrypt all plaintext sensitive data"""
    try:
        logger.info(f"Starting migration: {MIGRATION_NAME} (v{MIGRATION_VERSION})")

        fernet = get_fernet()
        telegram_fernet = get_telegram_fernet()
        if not fernet or not telegram_fernet:
            logger.error("Cannot proceed without API_KEY_PEPPER")
            return False

        engine = get_engine()
        total_encrypted = 0

        with engine.connect() as conn:
            # 1. Encrypt Samco secret_api_key in auth table
            inspector = inspect(engine)
            auth_columns = {col["name"] for col in inspector.get_columns("auth")}

            if "secret_api_key" in auth_columns:
                rows = conn.execute(
                    text("SELECT id, secret_api_key FROM auth WHERE secret_api_key IS NOT NULL AND secret_api_key != ''")
                ).fetchall()

                for row in rows:
                    row_id, value = row[0], row[1]
                    if not is_already_encrypted(value, fernet):
                        encrypted = encrypt_value(value, fernet)
                        conn.execute(
                            text("UPDATE auth SET secret_api_key = :val WHERE id = :id"),
                            {"val": encrypted, "id": row_id},
                        )
                        total_encrypted += 1
                        logger.info(f"Encrypted Samco secret_api_key for auth record {row_id}")

            # 2. Re-encrypt SMTP password with new PBKDF2 KDF
            if "settings" in inspector.get_table_names():
                settings_columns = {col["name"] for col in inspector.get_columns("settings")}
                if "smtp_password_encrypted" in settings_columns:
                    rows = conn.execute(
                        text("SELECT id, smtp_password_encrypted FROM settings WHERE smtp_password_encrypted IS NOT NULL AND smtp_password_encrypted != ''")
                    ).fetchall()

                    legacy_key = get_smtp_legacy_key()
                    new_key = get_smtp_new_key()

                    if new_key:
                        legacy_fernet = Fernet(legacy_key)
                        new_fernet = Fernet(new_key)

                        for row in rows:
                            row_id, value = row[0], row[1]
                            # Check if already encrypted with new key
                            if is_already_encrypted(value, new_fernet):
                                logger.info(f"SMTP password already encrypted with new KDF for settings {row_id}")
                                continue
                            # Try decrypting with legacy key
                            try:
                                plaintext = legacy_fernet.decrypt(value.encode()).decode()
                                re_encrypted = new_fernet.encrypt(plaintext.encode()).decode()
                                conn.execute(
                                    text("UPDATE settings SET smtp_password_encrypted = :val WHERE id = :id"),
                                    {"val": re_encrypted, "id": row_id},
                                )
                                total_encrypted += 1
                                logger.info(f"Re-encrypted SMTP password with PBKDF2 KDF for settings {row_id}")
                            except InvalidToken:
                                logger.warning(f"Could not decrypt SMTP password for settings {row_id} with legacy key - skipping")

            # 3. Encrypt Telegram bot token in bot_config table
            telegram_db_url = os.getenv("LOGS_DATABASE_URL", "sqlite:///db/logs.db")
            # bot_config is in the main database (openalgo.db)
            if "bot_config" in inspector.get_table_names():
                bot_config_columns = {col["name"] for col in inspector.get_columns("bot_config")}
                if "token" in bot_config_columns:
                    rows = conn.execute(
                        text("SELECT id, token FROM bot_config WHERE token IS NOT NULL AND token != ''")
                    ).fetchall()

                    for row in rows:
                        row_id, value = row[0], row[1]
                        if not is_already_encrypted(value, telegram_fernet):
                            encrypted = telegram_fernet.encrypt(value.encode()).decode()
                            conn.execute(
                                text("UPDATE bot_config SET token = :val WHERE id = :id"),
                                {"val": encrypted, "id": row_id},
                            )
                            total_encrypted += 1
                            logger.info(f"Encrypted Telegram bot token for bot_config {row_id}")

            # 4. Encrypt Flow workflow API keys
            if "flow_workflows" in inspector.get_table_names():
                flow_columns = {col["name"] for col in inspector.get_columns("flow_workflows")}
                if "api_key" in flow_columns:
                    rows = conn.execute(
                        text("SELECT id, api_key FROM flow_workflows WHERE api_key IS NOT NULL AND api_key != ''")
                    ).fetchall()

                    for row in rows:
                        row_id, value = row[0], row[1]
                        if not is_already_encrypted(value, fernet):
                            encrypted = encrypt_value(value, fernet)
                            conn.execute(
                                text("UPDATE flow_workflows SET api_key = :val WHERE id = :id"),
                                {"val": encrypted, "id": row_id},
                            )
                            total_encrypted += 1
                            logger.info(f"Encrypted API key for flow_workflows {row_id}")

            # 5. Encrypt TOTP secrets in users table
            if "users" in inspector.get_table_names():
                users_columns = {col["name"] for col in inspector.get_columns("users")}
                if "totp_secret" in users_columns:
                    rows = conn.execute(
                        text("SELECT id, totp_secret FROM users WHERE totp_secret IS NOT NULL AND totp_secret != ''")
                    ).fetchall()

                    for row in rows:
                        row_id, value = row[0], row[1]
                        if not is_already_encrypted(value, fernet):
                            encrypted = encrypt_value(value, fernet)
                            conn.execute(
                                text("UPDATE users SET totp_secret = :val WHERE id = :id"),
                                {"val": encrypted, "id": row_id},
                            )
                            total_encrypted += 1
                            logger.info(f"Encrypted TOTP secret for user {row_id}")

            conn.commit()

        if total_encrypted > 0:
            logger.info(f"Migration {MIGRATION_NAME} completed: encrypted {total_encrypted} value(s)")
        else:
            logger.info(f"Migration {MIGRATION_NAME}: all sensitive data already encrypted")
        return True

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def status():
    """Check migration status - returns True if no plaintext sensitive data found"""
    try:
        logger.info(f"Checking status of migration: {MIGRATION_NAME}")

        fernet = get_fernet()
        telegram_fernet = get_telegram_fernet()
        if not fernet or not telegram_fernet:
            logger.error("Cannot check status without API_KEY_PEPPER")
            return False

        engine = get_engine()
        inspector = inspect(engine)
        plaintext_found = 0

        with engine.connect() as conn:
            # Check Samco secret_api_key
            auth_columns = {col["name"] for col in inspector.get_columns("auth")}
            if "secret_api_key" in auth_columns:
                rows = conn.execute(
                    text("SELECT id, secret_api_key FROM auth WHERE secret_api_key IS NOT NULL AND secret_api_key != ''")
                ).fetchall()
                for row in rows:
                    if not is_already_encrypted(row[1], fernet):
                        plaintext_found += 1

            # Check Telegram bot token
            if "bot_config" in inspector.get_table_names():
                rows = conn.execute(
                    text("SELECT id, token FROM bot_config WHERE token IS NOT NULL AND token != ''")
                ).fetchall()
                for row in rows:
                    if not is_already_encrypted(row[1], telegram_fernet):
                        plaintext_found += 1

            # Check Flow API keys
            if "flow_workflows" in inspector.get_table_names():
                flow_columns = {col["name"] for col in inspector.get_columns("flow_workflows")}
                if "api_key" in flow_columns:
                    rows = conn.execute(
                        text("SELECT id, api_key FROM flow_workflows WHERE api_key IS NOT NULL AND api_key != ''")
                    ).fetchall()
                    for row in rows:
                        if not is_already_encrypted(row[1], fernet):
                            plaintext_found += 1

            # Check TOTP secrets
            if "users" in inspector.get_table_names():
                rows = conn.execute(
                    text("SELECT id, totp_secret FROM users WHERE totp_secret IS NOT NULL AND totp_secret != ''")
                ).fetchall()
                for row in rows:
                    if not is_already_encrypted(row[1], fernet):
                        plaintext_found += 1

        if plaintext_found > 0:
            logger.info(f"Found {plaintext_found} plaintext value(s) - migration needed")
            return False

        logger.info("All sensitive data is encrypted")
        return True

    except Exception as e:
        logger.error(f"Status check failed: {e}")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=f"Migration: {MIGRATION_NAME} (v{MIGRATION_VERSION})",
    )
    parser.add_argument("--status", action="store_true", help="Check migration status")

    args = parser.parse_args()

    if args.status:
        success = status()
    else:
        success = upgrade()

    sys.exit(0 if success else 1)
