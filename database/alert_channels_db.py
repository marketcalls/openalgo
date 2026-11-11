# database/alert_channels_db.py
"""Where each alert channel's settings are kept.

One row per channel that a trader has changed on the /alerts page: whether the
channel is on, which event groups it receives, and for a webhook channel
(Slack, Discord) the webhook address. A channel with no row uses its defaults
(``services.alerts.settings``), so an install that never opens /alerts keeps
exactly the alerts it had, and no seed data is ever needed.

**A webhook address is a secret.** Anybody holding a Slack or Discord webhook
URL can post into that channel, so it is stored encrypted with the auth_db
Fernet key, never returned to the browser, and never logged. Rotating the key
re-encrypts it: the column is in ``utils.env_check._migrate_fernet_db`` and
``upgrade/rotate_pepper.py``.

Mirrors database/alert_log_db.py: SQLite through the engine factory (NullPool)
and a scoped session registered in utils/db_sessions.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from database.engine_factory import create_db_engine
from utils.logging import get_logger

logger = get_logger(__name__)

engine = create_db_engine()

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


class AlertChannelRow(Base):
    """One alert channel's saved settings."""

    __tablename__ = "alert_channels"

    #: The channel's name: telegram, whatsapp, slack or discord.
    channel = Column(String(20), primary_key=True)
    enabled = Column(Boolean, nullable=False, default=True)
    #: The event groups this channel receives, comma separated.
    categories = Column(Text, nullable=False, default="")
    #: Webhook channels only: the webhook URL, encrypted. Null when none is saved.
    webhook_url = Column(Text, nullable=True)
    updated_at = Column(DateTime, nullable=False)


@dataclass(frozen=True)
class StoredChannel:
    """A channel's saved settings, without the webhook address itself.

    Attributes:
        enabled: Whether the channel is on.
        categories: The event groups it receives, as saved.
        webhook_saved: Whether a webhook address is stored.
    """

    enabled: bool
    categories: tuple[str, ...]
    webhook_saved: bool


def init_db():
    """Create the table if it does not exist."""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Alert Channels DB", logger)


def load_channel(channel: str) -> StoredChannel | None:
    """A channel's saved settings, or None when it has never been changed.

    Raises:
        SQLAlchemyError: The database could not be read. The caller decides
            whether to fall back to defaults.
    """
    try:
        row = db_session.get(AlertChannelRow, channel)
        if row is None:
            return None
        return StoredChannel(
            enabled=bool(row.enabled),
            categories=_split(row.categories),
            webhook_saved=bool(row.webhook_url),
        )
    finally:
        db_session.remove()


def save_channel(channel: str, *, enabled: bool, categories: tuple[str, ...]) -> None:
    """Save whether a channel is on and which groups it receives.

    A saved webhook address is kept as it is.
    """
    try:
        row = db_session.get(AlertChannelRow, channel) or AlertChannelRow(channel=channel)
        row.enabled = enabled
        row.categories = ",".join(categories)
        row.updated_at = _now()
        db_session.add(row)
        db_session.commit()
    except Exception:
        db_session.rollback()
        raise
    finally:
        db_session.remove()


def save_webhook(
    channel: str, url: str, *, enabled: bool, default_categories: tuple[str, ...]
) -> None:
    """Store a channel's webhook address, encrypted, and set it on or off.

    Args:
        channel: The webhook channel.
        url: The address, already validated by the channel.
        enabled: Whether the channel is on afterwards.
        default_categories: The groups to start with when the channel has
            never been saved before. An existing choice is kept.
    """
    from database.auth_db import encrypt_token

    try:
        row = db_session.get(AlertChannelRow, channel)
        if row is None:
            row = AlertChannelRow(channel=channel, categories=",".join(default_categories))
        row.webhook_url = encrypt_token(url)
        row.enabled = enabled
        row.updated_at = _now()
        db_session.add(row)
        db_session.commit()
    except Exception:
        db_session.rollback()
        raise
    finally:
        db_session.remove()


def clear_webhook(channel: str) -> None:
    """Forget a channel's webhook address and turn the channel off."""
    try:
        row = db_session.get(AlertChannelRow, channel)
        if row is None:
            return
        row.webhook_url = None
        row.enabled = False
        row.updated_at = _now()
        db_session.commit()
    except Exception:
        db_session.rollback()
        raise
    finally:
        db_session.remove()


def read_webhook_url(channel: str) -> str | None:
    """A channel's webhook address, decrypted, or None when none is usable.

    An address that no longer decrypts (a key rotated without the rotation
    script, say) reads as not saved: the trader is asked to save it again
    rather than shown an error they cannot act on.
    """
    from database.auth_db import decrypt_token

    try:
        row = db_session.get(AlertChannelRow, channel)
        ciphertext = row.webhook_url if row is not None else None
    finally:
        db_session.remove()
    if not ciphertext:
        return None
    return decrypt_token(ciphertext) or None


def _split(categories: str | None) -> tuple[str, ...]:
    return tuple(part for part in (categories or "").split(",") if part)


def _now() -> datetime:
    """Now in UTC, naive, as every DateTime column in this project stores it."""
    return datetime.now(UTC).replace(tzinfo=None)
