"""
Strategy Risk Management — Concurrency Infrastructure

Thread-safety primitives used by the risk engine, order poller, and webhook handlers:
1. PositionLockManager — per-position threading locks
2. PositionUpdateBuffer — batch in-memory updates, flush to DB periodically
3. WebhookDedup — reject duplicate webhook signals within a time window
"""

import os
import threading
import time
from collections import defaultdict

from utils.logging import get_logger

logger = get_logger(__name__)

# Config from environment
POSITION_UPDATE_INTERVAL = float(os.getenv("STRATEGY_POSITION_UPDATE_INTERVAL", "1.0"))
WEBHOOK_DEDUP_WINDOW = int(os.getenv("STRATEGY_WEBHOOK_DEDUP_WINDOW", "5"))


class PositionLockManager:
    """Per-position threading lock to serialize mutations.

    Any code modifying a StrategyPosition row MUST hold the position lock:
    - Risk engine: before placing exit order (set position_state='exiting')
    - Poller: before updating position on fill
    - Webhook: before creating new entry (check position_state)
    """

    _locks = defaultdict(threading.Lock)

    @classmethod
    def get_lock(cls, strategy_id, symbol, exchange, product_type):
        """Get a lock for a specific position identified by its composite key."""
        key = (strategy_id, symbol, exchange, product_type)
        return cls._locks[key]

    @classmethod
    def cleanup(cls, strategy_id=None):
        """Remove locks for closed positions to prevent memory leaks.

        Args:
            strategy_id: If provided, only clean up locks for this strategy.
                         If None, remove all unlocked locks.
        """
        to_remove = []
        for key, lock in cls._locks.items():
            if strategy_id is not None and key[0] != strategy_id:
                continue
            if not lock.locked():
                to_remove.append(key)
        for key in to_remove:
            del cls._locks[key]
        if to_remove:
            logger.debug(f"Cleaned up {len(to_remove)} position locks")


class PositionUpdateBuffer:
    """Buffer in-memory position updates, flush to DB at a throttled rate.

    The risk engine receives sub-second LTP ticks for many positions.
    Writing to DB on every tick would overwhelm SQLite. This buffer
    collects updates in memory and flushes them in a single batch
    transaction at a configurable interval (default 1s).

    Trigger checks run against in-memory buffered values (fast),
    while DB persistence is batched (efficient).
    """

    def __init__(self, flush_interval=None):
        self.flush_interval = flush_interval or POSITION_UPDATE_INTERVAL
        self._buffer = {}  # position_id -> dict of fields to update
        self._lock = threading.Lock()
        self._flush_thread = None
        self._running = False

    def start(self):
        """Start the background flush thread."""
        if self._running:
            return
        self._running = True
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()
        logger.info(f"PositionUpdateBuffer started (flush every {self.flush_interval}s)")

    def stop(self):
        """Stop the flush thread and do a final flush."""
        self._running = False
        if self._flush_thread:
            self._flush_thread.join(timeout=5)
        # Final flush
        self.flush()

    def update(self, position_id, **data):
        """Buffer an update for a position. Latest update wins for each field."""
        with self._lock:
            if position_id not in self._buffer:
                self._buffer[position_id] = {}
            self._buffer[position_id].update(data)

    def get(self, position_id):
        """Read buffered values for a position (for trigger checks)."""
        with self._lock:
            return self._buffer.get(position_id, {}).copy()

    def get_all(self):
        """Get all buffered position data (for SocketIO emit)."""
        with self._lock:
            return {pid: data.copy() for pid, data in self._buffer.items()}

    def flush(self):
        """Batch-write all buffered updates to DB in a single transaction."""
        with self._lock:
            if not self._buffer:
                return
            to_flush = self._buffer.copy()
            self._buffer.clear()

        if not to_flush:
            return

        try:
            from database.strategy_position_db import StrategyPosition, db_session

            for position_id, data in to_flush.items():
                db_session.query(StrategyPosition).filter_by(id=position_id).update(data)
            db_session.commit()
        except Exception as e:
            logger.exception(f"Error flushing position updates: {e}")
            try:
                from database.strategy_position_db import db_session

                db_session.rollback()
            except Exception:
                pass
        finally:
            try:
                from database.strategy_position_db import db_session

                db_session.remove()
            except Exception:
                pass

    def _flush_loop(self):
        """Background loop that flushes at regular intervals."""
        while self._running:
            time.sleep(self.flush_interval)
            try:
                self.flush()
            except Exception as e:
                logger.exception(f"Error in flush loop: {e}")


class WebhookDedup:
    """Reject duplicate webhook signals within a configurable time window.

    TradingView and other signal sources may send duplicate webhooks
    (network retries, duplicate alerts). This deduplicator tracks recent
    signals and rejects duplicates within the window.
    """

    def __init__(self, window_seconds=None):
        self.window_seconds = window_seconds or WEBHOOK_DEDUP_WINDOW
        self._recent_signals = {}
        self._lock = threading.Lock()

    def is_duplicate(self, strategy_id, symbol, action):
        """Check if this signal is a duplicate within the dedup window.

        Args:
            strategy_id: Strategy ID
            symbol: Trading symbol
            action: BUY or SELL

        Returns:
            True if this is a duplicate signal that should be rejected.
        """
        key = f"{strategy_id}:{symbol}:{action}"
        now = time.time()

        with self._lock:
            if key in self._recent_signals:
                elapsed = now - self._recent_signals[key]
                if elapsed < self.window_seconds:
                    logger.warning(
                        f"Duplicate webhook rejected: {key} (last signal {elapsed:.1f}s ago)"
                    )
                    return True

            self._recent_signals[key] = now

            # Periodic cleanup of stale entries
            if len(self._recent_signals) > 1000:
                self._cleanup(now)

        return False

    def _cleanup(self, now):
        """Remove stale entries from the dedup cache."""
        stale = [
            k for k, t in self._recent_signals.items() if (now - t) > self.window_seconds * 2
        ]
        for k in stale:
            del self._recent_signals[k]


# Module-level singleton instances
webhook_dedup = WebhookDedup()
position_update_buffer = PositionUpdateBuffer()
