# database/idempotency_db.py
"""
Application-level order idempotency store.

Maps (api_key_hash, client_order_id) -> broker orderid so a client that
retries a timed-out /api/v1/placeorder POST gets the existing order echoed
back instead of a duplicate position. Also records the caller-supplied
`tag` so the orderbook can echo it.

Design notes:

* **Keyed by SHA-256 of the OpenAlgo apikey**, never the plaintext. The
  auth module already treats the apikey as a secret (Argon2 verify, hashed
  cache keys); this store must not introduce a plaintext copy.
* **One row per placement attempt resolution.** A successful placement
  writes (client_order_id -> orderid). A duplicate POST short-circuits at
  the service layer and replays the recorded response — the broker is never
  called twice for the same client_order_id.
* **In-flight reservations.** A row is written before the broker call
  (status="in_flight") so a retry racing a slow placement cannot double-fire.
  If the placement fails, the reservation is released so a corrected retry
  with the same id is not blocked forever.
* **TTL.** Rows expire after ORDER_IDEMPOTENCY_TTL_HOURS (default 24h) so
  the table cannot grow unbounded; a client_order_id reused after expiry is
  treated as new. This matches broker-side order-book retention horizons
  closely enough for the timeout-retry use case.
* **Own SQLite file** (idempotency.db) with the project-wide NullPool
  engine policy — writes are one per order placement, reads are one per
  placement, so contention is negligible.
"""

import hashlib
import os
import threading
from datetime import datetime, timedelta

from sqlalchemy import Column, DateTime, Index, Integer, String, UniqueConstraint, create_engine
from sqlalchemy import text as sa_text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool

from utils.logging import get_logger

logger = get_logger(__name__)

IDEMPOTENCY_DATABASE_URL = os.getenv("IDEMPOTENCY_DATABASE_URL", "sqlite:///db/idempotency.db")

if IDEMPOTENCY_DATABASE_URL and "sqlite" in IDEMPOTENCY_DATABASE_URL:
    # SQLite: NullPool to prevent connection pool exhaustion (project-wide policy)
    idempotency_engine = create_engine(
        IDEMPOTENCY_DATABASE_URL, poolclass=NullPool, connect_args={"check_same_thread": False}
    )
else:
    # For other databases like PostgreSQL, use connection pooling
    idempotency_engine = create_engine(IDEMPOTENCY_DATABASE_URL, pool_size=10, max_overflow=20)

IDEMPOTENCY_TTL_HOURS = int(os.getenv("ORDER_IDEMPOTENCY_TTL_HOURS", "24"))

idempotency_session = scoped_session(
    sessionmaker(autocommit=False, autoflush=False, bind=idempotency_engine)
)
IdempotencyBase = declarative_base()
IdempotencyBase.query = idempotency_session.query_property()


class ClientOrderId(IdempotencyBase):
    """A client-supplied idempotency key and the order it resolved to."""

    __tablename__ = "client_order_ids"

    id = Column(Integer, primary_key=True)
    api_key_hash = Column(
        String(64), nullable=False, index=True
    )  # sha256 hex of the OpenAlgo apikey
    client_order_id = Column(String(128), nullable=False)
    orderid = Column(String(64), nullable=True)  # broker/OpenAlgo orderid once known
    tag = Column(
        String(128), nullable=True
    )  # caller's original `tag` passthrough, echoed in the orderbook
    # in_flight: broker call not yet resolved. placed: orderid recorded.
    status = Column(String(16), nullable=False, default="in_flight")
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        # The idempotency key is (user, client id) — one resolution per pair.
        UniqueConstraint("api_key_hash", "client_order_id", name="uq_client_order_ids_key"),
    )


Index("ix_client_order_ids_created_at", ClientOrderId.created_at)
# The orderbook echoes labels per orderid on every poll; (api_key_hash,
# orderid) covers that lookup without scanning the user's partition.
Index(
    "ix_client_order_ids_api_key_hash_orderid",
    ClientOrderId.api_key_hash,
    ClientOrderId.orderid,
)


_init_lock = threading.Lock()
_initialized = False


def _hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def init_idempotency_db() -> None:
    """Create tables if absent. Idempotent; safe to call per-request."""
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        IdempotencyBase.metadata.create_all(bind=idempotency_engine)
        # create_all only builds indexes for new tables. Existing installs
        # created client_order_ids without the created_at / (api_key_hash,
        # orderid) indexes, so add them explicitly (IF NOT EXISTS semantics).
        with idempotency_engine.connect() as conn:
            for stmt in (
                "CREATE INDEX IF NOT EXISTS ix_client_order_ids_created_at "
                "ON client_order_ids (created_at)",
                "CREATE INDEX IF NOT EXISTS ix_client_order_ids_api_key_hash_orderid "
                "ON client_order_ids (api_key_hash, orderid)",
            ):
                conn.execute(sa_text(stmt))
            conn.commit()
        _initialized = True


def _prune_expired(session) -> None:
    """Delete rows older than the TTL. Called opportunistically on writes."""
    cutoff = datetime.now() - timedelta(hours=IDEMPOTENCY_TTL_HOURS)
    session.query(ClientOrderId).filter(ClientOrderId.created_at < cutoff).delete()
    session.commit()


def reserve_client_order_id(
    api_key: str, client_order_id: str, tag: str | None = None
) -> tuple[str, str | None]:
    """Claim (api_key, client_order_id) before the broker call.

    INSERT-first: the unique constraint on (api_key_hash, client_order_id)
    makes the claim atomic, so two concurrent retries cannot both proceed.

    Returns:
        ("reserved", None) — this call created the reservation and must
        proceed with the placement, then record_success() or release it.
        ("existing", status) — another call already claimed the key; status
        is "placed" (replay the recorded orderid) or "in_flight" (a placement
        is racing right now; caller should report 409).
    """
    init_idempotency_db()
    key_hash = _hash_api_key(api_key)
    with _init_lock:
        try:
            row = ClientOrderId(
                api_key_hash=key_hash,
                client_order_id=client_order_id,
                tag=tag,
                status="in_flight",
            )
            idempotency_session.add(row)
            _prune_expired(idempotency_session)
            idempotency_session.commit()
            return "reserved", None
        except IntegrityError:
            idempotency_session.rollback()
            existing = (
                idempotency_session.query(ClientOrderId)
                .filter_by(api_key_hash=key_hash, client_order_id=client_order_id)
                .one_or_none()
            )
            if existing is None:
                # Row vanished between the conflict and the re-read (TTL prune).
                # Nothing is in flight, so the caller may retry the reserve.
                return "vacated", None
            return "existing", existing.status


def record_success(api_key: str, client_order_id: str, orderid: str) -> None:
    """Attach the broker orderid to an in_flight reservation."""
    init_idempotency_db()
    key_hash = _hash_api_key(api_key)
    with _init_lock:
        row = (
            idempotency_session.query(ClientOrderId)
            .filter_by(api_key_hash=key_hash, client_order_id=client_order_id)
            .one_or_none()
        )
        if row is None:
            # Reservation lost (manual DB wipe mid-flight): record fresh so the
            # mapping still exists for orderbook echo and dedupe.
            row = ClientOrderId(
                api_key_hash=key_hash, client_order_id=client_order_id, status="in_flight"
            )
            idempotency_session.add(row)
        row.orderid = str(orderid)
        row.status = "placed"
        idempotency_session.commit()


def release_client_order_id(api_key: str, client_order_id: str) -> None:
    """Drop an in_flight reservation after a failed placement.

    A retry with the same id must be allowed to proceed after a failure —
    blocking it would turn one broker outage into a permanent 409 for that id.
    """
    init_idempotency_db()
    key_hash = _hash_api_key(api_key)
    with _init_lock:
        row = (
            idempotency_session.query(ClientOrderId)
            .filter_by(api_key_hash=key_hash, client_order_id=client_order_id)
            .one_or_none()
        )
        if row is not None and row.status == "in_flight":
            idempotency_session.delete(row)
            idempotency_session.commit()


def get_resolution(api_key: str, client_order_id: str) -> dict | None:
    """Return the recorded resolution for a key, or None if unknown.

    Shape: {"orderid": str|None, "status": "in_flight"|"placed", "tag": str|None}
    An in_flight resolution means a placement is racing right now.
    """
    init_idempotency_db()
    key_hash = _hash_api_key(api_key)
    row = (
        idempotency_session.query(ClientOrderId)
        .filter_by(api_key_hash=key_hash, client_order_id=client_order_id)
        .one_or_none()
    )
    if row is None:
        return None
    return {"orderid": row.orderid, "status": row.status, "tag": row.tag}


def get_labels_for_orderids(api_key: str, orderids: list[str]) -> dict[str, dict[str, str]]:
    """Return {orderid: {"client_order_id", "tag"}} for the given orderids.

    Used by the orderbook service to echo caller-supplied fields onto
    broker-proxied orderbook rows.
    """
    if not orderids:
        return {}
    init_idempotency_db()
    key_hash = _hash_api_key(api_key)
    rows = (
        idempotency_session.query(ClientOrderId)
        .filter(
            ClientOrderId.api_key_hash == key_hash,
            ClientOrderId.orderid.in_([str(o) for o in orderids]),
        )
        .all()
    )
    return {row.orderid: {"client_order_id": row.client_order_id, "tag": row.tag} for row in rows}
