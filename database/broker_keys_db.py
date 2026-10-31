# database/broker_keys_db.py
"""Broker keys saved in OpenAlgo, one set per broker.

The trader stores the API key and secret of every broker they use here, then
logs in to one of them at a time. The ``.env`` file still comes first: when it
names a broker (REDIRECT_URL) with a key, that broker's ``.env`` keys win over a
row stored here, and the rows serve every other broker. utils/broker_keys.py
owns that precedence and applies the chosen broker's keys to the process.

Every key and secret is encrypted with the auth_db Fernet (AES-128-CBC with
HMAC-SHA256, key from PBKDF2-SHA256 over API_KEY_PEPPER and the per-install
FERNET_SALT), so the pepper and salt rotations re-encrypt them with the broker
tokens (utils/env_check.py _migrate_fernet_db and upgrade/rotate_pepper.py list
these columns). Each ciphertext is bound to its broker and field: the
authenticated plaintext starts with both, and a value copied into another row
or column is refused on read instead of becoming another broker's secret, as
OpenAlgo Desktop binds its AES-GCM ciphertexts. The rotations decrypt and
re-encrypt the whole plaintext, so the binding survives them. Nothing here
returns a secret to a caller that only needs to show it: the masked view lives
in the blueprint.
"""

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy import delete as sql_delete
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker

from database.engine_factory import create_db_engine
from utils.logging import get_logger

logger = get_logger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_db_engine(DATABASE_URL)
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

#: The stored fields, in the order the .env file lists them.
KEY_FIELDS = ("api_key", "api_secret", "api_key_market", "api_secret_market")


class BrokerKey(Base):
    """One broker's keys. Every key column holds Fernet ciphertext."""

    __tablename__ = "broker_keys"

    id = Column(Integer, primary_key=True)
    broker = Column(String(50), unique=True, nullable=False, index=True)
    api_key = Column(Text, nullable=False, default="")
    api_secret = Column(Text, nullable=False, default="")
    api_key_market = Column(Text, nullable=False, default="")
    api_secret_market = Column(Text, nullable=False, default="")
    redirect_url = Column(String(500), nullable=False, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BrokerLoginState(Base):
    """A broker login started from the broker login page, not yet completed.

    Held in the database rather than in memory, as OpenAlgo Desktop's
    pending_oauth table is, so a login survives a restart while the trader is
    at the broker's site. Only SHA-256 digests are stored: the nonce lives in
    the browser's signed session and the state on the broker's return address,
    so a copy of this table lets nobody complete a login.
    """

    __tablename__ = "broker_login_states"

    id = Column(Integer, primary_key=True)
    nonce_hash = Column(String(64), unique=True, nullable=False, index=True)
    state_hash = Column(String(64), nullable=False, index=True)
    broker = Column(String(50), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)


#: How long a started login stays open, and how many may be open at once.
LOGIN_STATE_TTL = timedelta(minutes=10)
MAX_LOGIN_STATES = 16


def _digest(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


@dataclass(frozen=True)
class StoredBrokerKeys:
    """A broker's keys in plain text, detached from the session."""

    broker: str
    api_key: str
    api_secret: str
    api_key_market: str
    api_secret_market: str
    redirect_url: str
    updated_at: datetime | None


def init_db():
    """Create the broker keys table."""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Broker Keys DB", logger)


def ensure_broker_keys_tables_exists():
    """Create the table, then put the logged-in broker's keys in place.

    Runs in the startup database phase, before the first request is served, so
    an order placed straight after a restart already reaches the broker with the
    keys its session was opened with.
    """
    init_db()
    from utils.broker_keys import apply_logged_in_broker_keys

    apply_logged_in_broker_keys()


def _table_missing(exc):
    """Whether a read failed only because the table is not created yet.

    Normal before the first start after an upgrade: the startup database phase
    creates it, so this is not worth an error in the log.
    """
    return isinstance(exc, OperationalError) and "no such table" in str(exc).lower()


#: Prefix of every bound plaintext; the version lets the layout change later.
_BINDING = "openalgo.broker_keys.v1"


def _bound_prefix(broker, field):
    return f"{_BINDING}|{broker}|{field}|"


def _decrypt(broker, field, value):
    """The plain text of one stored field, or "" when it cannot be trusted.

    A value that does not decrypt (a lost pepper or salt) or that was bound to
    another broker or field reads as not saved, so the trader is asked to enter
    the key again rather than a wrong key being sent to a broker.
    """
    from database.auth_db import decrypt_token

    if not value:
        return ""
    plain = decrypt_token(value) or ""
    prefix = _bound_prefix(broker, field)
    if not plain.startswith(prefix):
        logger.warning(f"A saved {field} for {broker} could not be read; enter it again")
        return ""
    return plain[len(prefix) :]


def _encrypt(broker, field, value):
    from database.auth_db import encrypt_token

    return encrypt_token(_bound_prefix(broker, field) + value) if value else ""


def _to_record(row):
    fields = {field: _decrypt(row.broker, field, getattr(row, field)) for field in KEY_FIELDS}
    return StoredBrokerKeys(
        broker=row.broker,
        redirect_url=row.redirect_url or "",
        updated_at=row.updated_at,
        **fields,
    )


def get_broker_keys(broker):
    """The stored keys of one broker.

    Args:
        broker: The broker id, such as "zerodha".

    Returns:
        StoredBrokerKeys | None: None when nothing is stored for it, or when the
        table does not exist yet.
    """
    try:
        row = BrokerKey.query.filter_by(broker=broker).first()
        return _to_record(row) if row else None
    except Exception as exc:
        if not _table_missing(exc):
            logger.exception(f"Could not read the saved keys for {broker}")
        return None
    finally:
        db_session.remove()


def list_broker_keys():
    """Every broker with stored keys, in broker order.

    Returns:
        list[StoredBrokerKeys]: Empty when nothing is stored or the table does
        not exist yet.
    """
    try:
        rows = BrokerKey.query.order_by(BrokerKey.broker).all()
        return [_to_record(row) for row in rows]
    except Exception as exc:
        if not _table_missing(exc):
            logger.exception("Could not list the saved broker keys")
        return []
    finally:
        db_session.remove()


def save_broker_keys(broker, values, redirect_url=None):
    """Store a broker's keys, keeping any field left empty.

    Args:
        broker: The broker id.
        values: A mapping of KEY_FIELDS to plain text. An empty or missing
            value keeps what is stored; a broker saved for the first time has
            to come with its API key.
        redirect_url: The callback address; None keeps the stored one, and ""
            follows this host's default address (HOST_SERVER).

    Returns:
        tuple[bool, str]: Whether it was saved, and a message for the trader.
    """
    try:
        row = BrokerKey.query.filter_by(broker=broker).first()
        if row is None:
            if not values.get("api_key"):
                return False, "Enter the API key to save this broker."
            row = BrokerKey(broker=broker)
            db_session.add(row)
        for field in KEY_FIELDS:
            value = values.get(field)
            if value:
                setattr(row, field, _encrypt(broker, field, value))
        if redirect_url is not None:
            row.redirect_url = redirect_url
        row.updated_at = datetime.utcnow()
        db_session.commit()
        return True, "Saved."
    except Exception:
        db_session.rollback()
        logger.exception(f"Could not save the keys for {broker}")
        return False, "Could not save the keys. Try again."
    finally:
        db_session.remove()


def clear_broker_key_fields(broker, fields):
    """Empty some stored fields of a broker, such as its market data keys.

    Args:
        broker: The broker id.
        fields: Field names from KEY_FIELDS other than api_key.

    Returns:
        bool: True when the row exists and was updated.
    """
    try:
        row = BrokerKey.query.filter_by(broker=broker).first()
        if row is None:
            return False
        for field in fields:
            if field in KEY_FIELDS and field != "api_key":
                setattr(row, field, "")
        row.updated_at = datetime.utcnow()
        db_session.commit()
        return True
    except Exception:
        db_session.rollback()
        logger.exception(f"Could not clear keys for {broker}")
        return False
    finally:
        db_session.remove()


def delete_broker_keys(broker):
    """Remove a broker's stored keys.

    Returns:
        bool: True when a row was removed.
    """
    try:
        deleted = BrokerKey.query.filter_by(broker=broker).delete()
        db_session.commit()
        return bool(deleted)
    except Exception:
        db_session.rollback()
        logger.exception(f"Could not remove the keys for {broker}")
        return False
    finally:
        db_session.remove()


def record_login_state(broker, nonce, state):
    """Record a started broker login.

    Expired rows are removed first, and the oldest beyond MAX_LOGIN_STATES,
    so the table stays small however often Connect is pressed.

    Returns:
        bool: True when recorded.
    """
    now = datetime.utcnow()
    try:
        db_session.execute(sql_delete(BrokerLoginState).where(BrokerLoginState.expires_at <= now))
        db_session.add(
            BrokerLoginState(
                nonce_hash=_digest(nonce),
                state_hash=_digest(state),
                broker=broker,
                created_at=now,
                expires_at=now + LOGIN_STATE_TTL,
            )
        )
        db_session.flush()
        stale = (
            BrokerLoginState.query.order_by(
                BrokerLoginState.created_at.desc(), BrokerLoginState.id.desc()
            )
            .offset(MAX_LOGIN_STATES)
            .all()
        )
        for row in stale:
            db_session.delete(row)
        db_session.commit()
        return True
    except Exception:
        db_session.rollback()
        logger.exception("Could not record a started broker login")
        return False
    finally:
        db_session.remove()


def find_login_state(broker, nonce=None, state=None):
    """The id of an open login for a broker, matched by nonce or by state.

    Returns:
        int | None: None when there is no such open login.
    """
    if not nonce and not state:
        return None
    try:
        query = BrokerLoginState.query.filter(
            BrokerLoginState.broker == broker,
            BrokerLoginState.expires_at > datetime.utcnow(),
        )
        if nonce:
            query = query.filter(BrokerLoginState.nonce_hash == _digest(nonce))
        else:
            query = query.filter(BrokerLoginState.state_hash == _digest(state))
        row = query.first()
        return row.id if row else None
    except Exception as exc:
        if not _table_missing(exc):
            logger.exception("Could not read the started broker logins")
        return None
    finally:
        db_session.remove()


def consume_login_state(state_id):
    """Use up an open login. Exactly one caller wins when two race.

    Returns:
        bool: True when this call removed it.
    """
    try:
        result = db_session.execute(
            sql_delete(BrokerLoginState).where(
                BrokerLoginState.id == state_id,
                BrokerLoginState.expires_at > datetime.utcnow(),
            )
        )
        db_session.commit()
        return result.rowcount == 1
    except Exception:
        db_session.rollback()
        logger.exception("Could not use up a started broker login")
        return False
    finally:
        db_session.remove()


def clear_login_states():
    """Remove every started login (tests)."""
    try:
        db_session.execute(sql_delete(BrokerLoginState))
        db_session.commit()
    except Exception as exc:
        db_session.rollback()
        if not _table_missing(exc):
            logger.exception("Could not clear the started broker logins")
    finally:
        db_session.remove()
