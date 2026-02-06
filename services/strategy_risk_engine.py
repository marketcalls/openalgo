"""
Strategy Risk Engine — Real-Time Position Monitoring & Exit Triggers

Singleton service that:
1. Subscribes to MarketDataService with CRITICAL priority
2. On each LTP update: updates positions, checks SL/target/trail/breakeven triggers
3. Places exit orders via pluggable ExitExecutionStrategy
4. Emits SocketIO events via a throttled emit thread (300ms)
5. Handles restart recovery by reloading active positions
6. Auto-falls back to REST polling if WebSocket data goes stale

Threading model:
- LTP callback: runs on MarketDataService's thread (fast path)
- SocketIO emit thread: separate daemon, 300ms interval
- PositionUpdateBuffer: separate daemon, 1s flush interval
- MIS auto-square-off: checked each minute via scheduler
"""

import os
import threading
import time
from datetime import datetime

import pytz

from utils.logging import get_logger

logger = get_logger(__name__)

IST = pytz.timezone("Asia/Kolkata")

# Configuration from environment
SOCKETIO_EMIT_INTERVAL = float(os.getenv("STRATEGY_SOCKETIO_EMIT_INTERVAL", "0.3"))
REST_POLL_INTERVAL = float(os.getenv("STRATEGY_REST_POLL_INTERVAL", "5"))
STALE_THRESHOLD = float(os.getenv("STRATEGY_STALE_THRESHOLD", "30"))
HEALTH_CHECK_INTERVAL = float(os.getenv("STRATEGY_HEALTH_CHECK_INTERVAL", "5"))
PNL_SNAPSHOT_TIME = os.getenv("STRATEGY_PNL_SNAPSHOT_TIME", "15:35")


class StrategyRiskEngine:
    """Singleton risk engine that monitors strategy positions in real-time.

    Subscribes to MarketDataService CRITICAL priority for sub-second LTP updates.
    Checks SL/target/trailing stop/breakeven triggers on every tick.
    Auto-falls back to REST polling if WebSocket data goes stale.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._running = False
        self._subscriber_id = None
        self._scheduler = None

        # In-memory position cache: position_id -> position snapshot dict
        # Used for fast trigger checks without DB reads on every tick
        self._positions = {}  # {position_id: {symbol, exchange, action, ...}}
        self._positions_lock = threading.Lock()

        # Symbol → set of position_ids mapping for fast lookup on LTP callback
        self._symbol_positions = {}  # {"NSE:SBIN": {pos_id_1, pos_id_2, ...}}

        # Track which positions changed since last SocketIO emit
        self._changed_positions = set()
        self._changed_lock = threading.Lock()

        # Threads
        self._emit_thread = None
        self._health_thread = None
        self._rest_poll_thread = None

        # Engine mode
        self._mode = "websocket"  # 'websocket' or 'rest_polling'
        self._last_ltp_time = 0

    def start(self):
        """Start the risk engine — load positions, subscribe to market data, start threads."""
        if self._running:
            logger.warning("StrategyRiskEngine already running")
            return

        logger.info("Starting StrategyRiskEngine...")

        # Check master contract prerequisite
        if not self._check_master_contract():
            logger.warning(
                "Master contract not downloaded — risk engine starting in degraded mode. "
                "Download master contract from Broker → Settings."
            )

        self._running = True

        # Load active positions from DB into memory
        self._load_active_positions()

        # Start the order poller
        self._start_order_poller()

        # Subscribe to MarketDataService if we have positions
        if self._positions:
            self._subscribe_to_market_data()

        # Start SocketIO emit thread
        self._emit_thread = threading.Thread(
            target=self._emit_loop, daemon=True, name="RiskEngine-Emit"
        )
        self._emit_thread.start()

        # Start health monitor thread
        self._health_thread = threading.Thread(
            target=self._health_loop, daemon=True, name="RiskEngine-Health"
        )
        self._health_thread.start()

        # Start position update buffer
        from services.strategy_concurrency import position_update_buffer
        position_update_buffer.start()

        # Start APScheduler for MIS auto square-off and daily PnL snapshots
        self._start_scheduler()

        logger.info(
            f"StrategyRiskEngine started — {len(self._positions)} positions loaded, "
            f"mode={self._mode}"
        )

    def stop(self):
        """Stop the risk engine gracefully."""
        if not self._running:
            return

        logger.info("Stopping StrategyRiskEngine...")
        self._running = False

        # Stop scheduler
        if self._scheduler:
            try:
                self._scheduler.shutdown(wait=False)
            except Exception:
                pass

        # Unsubscribe from market data
        self._unsubscribe_from_market_data()

        # Stop position update buffer (flushes remaining updates)
        from services.strategy_concurrency import position_update_buffer
        position_update_buffer.stop()

        # Wait for threads
        for thread in (self._emit_thread, self._health_thread, self._rest_poll_thread):
            if thread and thread.is_alive():
                thread.join(timeout=5)

        logger.info("StrategyRiskEngine stopped")

    # ──────────────────────────────────────────────────────────────
    # Market Data Callback (runs on MarketDataService thread)
    # ──────────────────────────────────────────────────────────────

    def on_ltp_update(self, data):
        """Callback from MarketDataService on every LTP update.

        This is the hot path — must be fast. All DB writes are batched
        via PositionUpdateBuffer. Trigger checks run against in-memory values.

        Args:
            data: Dict from MarketDataService with keys: symbol, exchange, mode, data
        """
        try:
            symbol = data.get("symbol")
            exchange = data.get("exchange")
            market_data = data.get("data", {})
            ltp = market_data.get("ltp", 0)

            if not symbol or not exchange or not ltp:
                return

            self._last_ltp_time = time.time()
            symbol_key = f"{exchange}:{symbol}"

            # Find positions for this symbol
            with self._positions_lock:
                position_ids = self._symbol_positions.get(symbol_key, set()).copy()

            if not position_ids:
                return

            # Safety check — is market data reliable?
            from services.market_data_service import MarketDataService
            mds = MarketDataService()
            is_safe, reason = mds.is_trade_management_safe()
            if not is_safe:
                # Log once per minute to avoid spam
                if not hasattr(self, '_last_unsafe_log') or time.time() - self._last_unsafe_log > 60:
                    logger.warning(f"Risk engine paused: {reason}")
                    self._last_unsafe_log = time.time()
                    self._emit_risk_paused(reason)
                return

            # Process each position for this symbol
            for pos_id in position_ids:
                self._process_position_tick(pos_id, ltp)

            # Check combined P&L groups after all per-leg updates
            self._check_combined_groups()

        except Exception as e:
            logger.exception(f"Error in on_ltp_update: {e}")

    def _process_position_tick(self, position_id, ltp):
        """Process a single LTP tick for one position.

        Updates in-memory state, checks triggers, buffers DB writes.
        """
        with self._positions_lock:
            pos = self._positions.get(position_id)
            if not pos:
                return
            # Skip if not actively monitored
            if pos.get("position_state") != "active":
                return

        action = pos["action"]
        quantity = pos["quantity"]

        # 1. Update LTP and unrealized P&L
        if action == "BUY":
            unrealized_pnl = (ltp - pos["average_entry_price"]) * quantity
        else:  # SELL (short)
            unrealized_pnl = (pos["average_entry_price"] - ltp) * quantity

        unrealized_pnl_pct = (
            (unrealized_pnl / (pos["average_entry_price"] * quantity) * 100)
            if pos["average_entry_price"] and quantity
            else 0
        )

        # 2. Update peak price (for trailing stop calculation)
        peak_price = pos.get("peak_price", pos["average_entry_price"])
        if action == "BUY" and ltp > peak_price:
            peak_price = ltp
        elif action == "SELL" and ltp < peak_price:
            peak_price = ltp

        # 3. Check breakeven threshold (one-time move)
        breakeven_activated = pos.get("breakeven_activated", False)
        stoploss_price = pos.get("stoploss_price")

        if pos.get("breakeven_type") and not breakeven_activated:
            if self._check_breakeven(pos, ltp):
                tick_size = pos.get("tick_size", 0.05)
                from services.strategy_position_tracker import round_to_tick
                stoploss_price = round_to_tick(pos["average_entry_price"], tick_size)
                breakeven_activated = True
                logger.info(
                    f"Breakeven activated for position {position_id}: "
                    f"SL moved to entry {stoploss_price}"
                )

        # 4. Recalculate trailing stop from peak
        trailstop_price = pos.get("trailstop_price")
        if pos.get("trailstop_type") and pos.get("trailstop_value") is not None:
            from services.strategy_position_tracker import compute_trailstop_price
            tick_size = pos.get("tick_size", 0.05)
            new_trail = compute_trailstop_price(
                action, peak_price, pos["trailstop_type"], pos["trailstop_value"], tick_size
            )
            if new_trail is not None:
                # Trail only moves in the favorable direction
                if action == "BUY":
                    trailstop_price = max(trailstop_price or 0, new_trail)
                else:
                    trailstop_price = min(trailstop_price or float("inf"), new_trail) if trailstop_price else new_trail

        # 5. Update in-memory position state
        with self._positions_lock:
            pos["ltp"] = ltp
            pos["unrealized_pnl"] = unrealized_pnl
            pos["unrealized_pnl_pct"] = unrealized_pnl_pct
            pos["peak_price"] = peak_price
            pos["stoploss_price"] = stoploss_price
            pos["trailstop_price"] = trailstop_price
            pos["breakeven_activated"] = breakeven_activated

        # 6. Buffer DB write
        from services.strategy_concurrency import position_update_buffer
        position_update_buffer.update(
            position_id,
            ltp=ltp,
            unrealized_pnl=round(unrealized_pnl, 2),
            peak_price=peak_price,
            stoploss_price=stoploss_price,
            trailstop_price=trailstop_price,
            breakeven_activated=breakeven_activated,
        )

        # Mark as changed for SocketIO emit
        with self._changed_lock:
            self._changed_positions.add(position_id)

        # 7. Check per-leg / single triggers (skip combined mode)
        if pos.get("risk_mode") != "combined":
            self._check_triggers(position_id, pos, ltp, stoploss_price, trailstop_price)

    def _check_breakeven(self, pos, ltp):
        """Check if breakeven threshold has been hit."""
        action = pos["action"]
        entry = pos["average_entry_price"]
        be_type = pos.get("breakeven_type")
        be_threshold = pos.get("breakeven_threshold")

        if not be_type or be_threshold is None:
            return False

        if be_type == "percentage":
            if action == "BUY":
                return ltp >= entry * (1 + be_threshold / 100)
            else:
                return ltp <= entry * (1 - be_threshold / 100)
        else:  # points
            if action == "BUY":
                return ltp >= entry + be_threshold
            else:
                return ltp <= entry - be_threshold

    def _check_triggers(self, position_id, pos, ltp, stoploss_price, trailstop_price):
        """Check if SL/target/trailing stop triggers have fired."""
        action = pos["action"]
        target_price = pos.get("target_price")

        # Compute effective stop: most protective wins
        effective_stop = None
        stop_source = None  # Track which stop triggered

        if action == "BUY":
            candidates = []
            if stoploss_price is not None:
                candidates.append((stoploss_price, "stoploss"))
            if trailstop_price is not None:
                candidates.append((trailstop_price, "trailstop"))
            if candidates:
                # For longs, the highest (most protective) stop wins
                effective_stop, stop_source = max(candidates, key=lambda x: x[0])
        else:  # SELL (short)
            candidates = []
            if stoploss_price is not None:
                candidates.append((stoploss_price, "stoploss"))
            if trailstop_price is not None:
                candidates.append((trailstop_price, "trailstop"))
            if candidates:
                # For shorts, the lowest (most protective) stop wins
                effective_stop, stop_source = min(candidates, key=lambda x: x[0])

        # Determine exit_detail based on source
        detail_map = {
            "stoploss": "breakeven_sl" if pos.get("breakeven_activated") else "leg_sl",
            "trailstop": "leg_tsl",
        }

        # Check stop trigger
        if effective_stop is not None:
            if action == "BUY" and ltp <= effective_stop:
                self._trigger_exit(
                    position_id, pos, stop_source,
                    detail_map.get(stop_source, "leg_sl"), ltp
                )
                return
            elif action == "SELL" and ltp >= effective_stop:
                self._trigger_exit(
                    position_id, pos, stop_source,
                    detail_map.get(stop_source, "leg_sl"), ltp
                )
                return

        # Check target trigger
        if target_price is not None:
            if action == "BUY" and ltp >= target_price:
                self._trigger_exit(position_id, pos, "target", "leg_target", ltp)
                return
            elif action == "SELL" and ltp <= target_price:
                self._trigger_exit(position_id, pos, "target", "leg_target", ltp)
                return

    def _trigger_exit(self, position_id, pos, exit_reason, exit_detail, trigger_ltp):
        """Place exit order when a trigger fires.

        Acquires position lock, sets state to 'exiting', places order via ExitExecutor.
        """
        from services.strategy_concurrency import PositionLockManager

        lock = PositionLockManager.get_lock(
            pos["strategy_id"], pos["symbol"], pos["exchange"], pos["product_type"]
        )

        if not lock.acquire(blocking=False):
            # Another thread is already handling this position
            logger.debug(f"Position {position_id} lock busy, skipping trigger")
            return

        try:
            # Re-check state under lock (another trigger may have fired)
            with self._positions_lock:
                current_pos = self._positions.get(position_id)
                if not current_pos or current_pos.get("position_state") != "active":
                    return
                # Set state to exiting
                current_pos["position_state"] = "exiting"
                current_pos["exit_reason"] = exit_reason
                current_pos["exit_detail"] = exit_detail

            logger.info(
                f"Exit triggered: position={position_id} {pos['symbol']}/{pos['exchange']} "
                f"reason={exit_reason} detail={exit_detail} ltp={trigger_ltp}"
            )

            # Update DB immediately (not buffered — state change is critical)
            try:
                from database.strategy_position_db import update_position
                update_position(
                    position_id,
                    position_state="exiting",
                    exit_reason=exit_reason,
                    exit_detail=exit_detail,
                )
            except Exception as e:
                logger.exception(f"Error updating position state to exiting: {e}")

            # Emit exit triggered event
            self._emit_exit_triggered(pos, exit_reason, exit_detail, trigger_ltp)

            # Get API key for the user who owns this strategy
            api_key = self._get_api_key_for_user(pos["user_id"])
            if not api_key:
                logger.error(
                    f"No API key for user {pos['user_id']} — cannot place exit order "
                    f"for position {position_id}"
                )
                # Revert state so it can be retried
                with self._positions_lock:
                    if current_pos := self._positions.get(position_id):
                        current_pos["position_state"] = "active"
                        current_pos["exit_reason"] = None
                        current_pos["exit_detail"] = None
                return

            # Place exit via ExitExecutor (runs on this thread — acceptable latency)
            from services.strategy_exit_executor import get_execution_strategy

            # Build a lightweight position-like object for the executor
            pos_obj = _PositionProxy(position_id, pos)
            executor = get_execution_strategy(pos.get("exit_execution", "market"))
            orderids = executor.execute(pos_obj, exit_reason, exit_detail, api_key)

            if orderids:
                logger.info(
                    f"Exit orders placed for position {position_id}: {orderids}"
                )
            else:
                logger.error(
                    f"No exit orders placed for position {position_id} — "
                    f"reverting to active"
                )
                # Revert state
                with self._positions_lock:
                    if current_pos := self._positions.get(position_id):
                        current_pos["position_state"] = "active"
                        current_pos["exit_reason"] = None
                        current_pos["exit_detail"] = None
                try:
                    from database.strategy_position_db import update_position
                    update_position(
                        position_id,
                        position_state="active",
                        exit_reason=None,
                        exit_detail=None,
                    )
                except Exception:
                    pass

        except Exception as e:
            logger.exception(f"Error in _trigger_exit for position {position_id}: {e}")
        finally:
            lock.release()

    # ──────────────────────────────────────────────────────────────
    # Combined P&L Group Checks
    # ──────────────────────────────────────────────────────────────

    def _check_combined_groups(self):
        """Check combined P&L triggers for multi-leg groups.

        Implements AFL-style trailing stop logic (Phase 2 — ratcheting):
        - Phase 1 (init) is handled in StrategyPositionTracker._initialize_group_risk()
        - Phase 2 (here): peak_pnl = max(peak, current_pnl),
          new_stop = initial_stop + peak_pnl, current_stop = max(new_stop, prev_stop)

        Exit triggers checked in order: Max Loss → Max Profit → Trailing Stop.
        The exit_triggered flag prevents duplicate exit attempts on the same group.
        """
        try:
            from database.strategy_position_db import (
                get_active_position_groups,
                get_positions_by_group,
            )

            groups = get_active_position_groups()
            for group in groups:
                if group.group_status != "active":
                    continue

                # Duplicate exit prevention — once triggered, don't re-trigger
                if group.exit_triggered:
                    continue

                legs = get_positions_by_group(group.id)
                if not legs:
                    continue

                # Calculate combined P&L from in-memory values + count open legs
                combined_pnl = 0
                open_leg_count = 0
                with self._positions_lock:
                    for leg in legs:
                        cached = self._positions.get(leg.id)
                        if cached:
                            combined_pnl += cached.get("unrealized_pnl", 0)
                            if cached.get("quantity", 0) > 0:
                                open_leg_count += 1
                        else:
                            combined_pnl += leg.unrealized_pnl or 0
                            if (leg.quantity or 0) > 0:
                                open_leg_count += 1

                combined_pnl = round(combined_pnl, 2)
                group.combined_pnl = combined_pnl

                # Get mapping for combined risk params
                mapping = self._get_mapping_for_group(group, legs)

                # --- Max Loss check ---
                if mapping and mapping.get("combined_stoploss_type"):
                    sl_threshold = self._compute_combined_threshold(
                        mapping, "sl", group
                    )
                    if sl_threshold and combined_pnl <= -abs(sl_threshold):
                        group.exit_triggered = True
                        self._close_all_group_legs(
                            group, legs, "stoploss", "combined_sl"
                        )
                        self._persist_group_state(group, combined_pnl)
                        continue

                # --- Max Profit check ---
                if mapping and mapping.get("combined_target_type"):
                    tgt_threshold = self._compute_combined_threshold(
                        mapping, "target", group
                    )
                    if tgt_threshold and combined_pnl >= tgt_threshold:
                        group.exit_triggered = True
                        self._close_all_group_legs(
                            group, legs, "target", "combined_target"
                        )
                        self._persist_group_state(group, combined_pnl)
                        continue

                # --- AFL-Style Trailing Stop (Phase 2 Ratcheting) ---
                if (group.initial_stop is not None and
                        group.entry_value and group.entry_value > 0):
                    # Safety guard: skip TSL when P&L is near-zero with open legs.
                    # Prices may be unreliable right after entry; avoid polluting
                    # peak_pnl with stale data or triggering on price flicker.
                    if abs(combined_pnl) < 1.0 and open_leg_count > 0:
                        self._persist_group_state(group, combined_pnl)
                        continue

                    # Update peak P&L (only moves up, never down)
                    peak_pnl = max(group.combined_peak_pnl or 0, combined_pnl)
                    group.combined_peak_pnl = peak_pnl

                    # Ratcheting stop: initial_stop + peak_pnl, only moves up
                    new_stop = group.initial_stop + peak_pnl
                    current_stop = max(new_stop, group.current_stop or float("-inf"))
                    group.current_stop = round(current_stop, 2)

                    # TSL trigger: exit when P&L drops to or below the ratcheted stop
                    if combined_pnl <= current_stop:
                        group.exit_triggered = True
                        self._close_all_group_legs(
                            group, legs, "trailstop", "combined_tsl"
                        )
                        self._persist_group_state(group, combined_pnl)
                        continue

                # Persist group state (non-exit path)
                self._persist_group_state(group, combined_pnl)

        except Exception as e:
            logger.exception(f"Error checking combined groups: {e}")
        finally:
            # Clean up thread-local DB session to prevent stale ORM objects
            # on the MarketDataService callback thread
            try:
                from database.strategy_position_db import db_session
                db_session.remove()
            except Exception:
                pass

    def _get_mapping_for_group(self, group, legs):
        """Get the symbol mapping with combined risk params for a group."""
        if not legs:
            return None
        # All legs in a group share the same strategy — get mapping from first leg
        first_leg = legs[0]
        try:
            strategy_type = first_leg.strategy_type
            if strategy_type == "webhook":
                from database.strategy_db import StrategySymbolMapping, db_session
                mapping = (
                    db_session.query(StrategySymbolMapping)
                    .filter_by(strategy_id=first_leg.strategy_id)
                    .first()
                )
            else:
                from database.chartink_db import ChartinkSymbolMapping, db_session
                mapping = (
                    db_session.query(ChartinkSymbolMapping)
                    .filter_by(strategy_id=first_leg.strategy_id)
                    .first()
                )
            if mapping:
                return {
                    "combined_stoploss_type": mapping.combined_stoploss_type,
                    "combined_stoploss_value": mapping.combined_stoploss_value,
                    "combined_target_type": mapping.combined_target_type,
                    "combined_target_value": mapping.combined_target_value,
                    "combined_trailstop_type": mapping.combined_trailstop_type,
                    "combined_trailstop_value": mapping.combined_trailstop_value,
                }
        except Exception as e:
            logger.debug(f"Error fetching mapping for group {group.id}: {e}")
        return None

    def _compute_combined_threshold(self, mapping, threshold_type, group):
        """Compute combined SL or target threshold as an absolute P&L value.

        For percentage type: threshold = entry_value × percentage / 100
          (entry_value = abs net premium at entry, computed in _initialize_group_risk)
        For points/amount type: threshold = value (absolute P&L amount)
        """
        type_key = f"combined_{threshold_type if threshold_type == 'target' else 'stoploss'}_type"
        value_key = f"combined_{threshold_type if threshold_type == 'target' else 'stoploss'}_value"
        sl_type = mapping.get(type_key)
        sl_value = mapping.get(value_key)

        if not sl_type or sl_value is None:
            return None

        if sl_type == "points":
            return sl_value  # Absolute P&L threshold

        # Percentage: compute from entry_value (net premium at entry)
        entry_value = group.entry_value or 0
        if entry_value <= 0:
            return None
        return entry_value * sl_value / 100

    def _persist_group_state(self, group, combined_pnl):
        """Persist combined group state to DB after each check cycle."""
        try:
            from database.strategy_position_db import update_position_group

            update_data = {
                "combined_pnl": round(combined_pnl, 2),
            }
            if group.combined_peak_pnl is not None:
                update_data["combined_peak_pnl"] = group.combined_peak_pnl
            if group.current_stop is not None:
                update_data["current_stop"] = group.current_stop
            if group.exit_triggered:
                update_data["exit_triggered"] = True
            update_position_group(group.id, **update_data)
        except Exception as e:
            logger.debug(f"Error persisting group {group.id}: {e}")

    def _close_all_group_legs(self, group, legs, exit_reason, exit_detail):
        """Close all legs in a combined P&L group."""
        logger.info(
            f"Combined trigger: group={group.id} reason={exit_reason} "
            f"detail={exit_detail} pnl={group.combined_pnl} "
            f"current_stop={group.current_stop}"
        )

        try:
            from database.strategy_position_db import update_position_group
            update_position_group(
                group.id, group_status="exiting", exit_triggered=True
            )
        except Exception as e:
            logger.error(
                f"Failed to update group {group.id} status to exiting: {e}. "
                f"Proceeding with leg exits — manual intervention may be needed."
            )

        for leg in legs:
            if leg.quantity and leg.quantity > 0:
                pos_data = None
                with self._positions_lock:
                    pos_data = self._positions.get(leg.id)

                if pos_data and pos_data.get("position_state") == "active":
                    self._trigger_exit(
                        leg.id, pos_data, exit_reason, exit_detail,
                        pos_data.get("ltp", 0)
                    )

    # ──────────────────────────────────────────────────────────────
    # Position Management
    # ──────────────────────────────────────────────────────────────

    def add_position(self, position):
        """Add a new position to the in-memory cache and subscribe to market data.

        Called by StrategyPositionTracker.on_entry_fill().
        """
        pos_data = self._position_to_dict(position)
        symbol_key = f"{position.exchange}:{position.symbol}"

        with self._positions_lock:
            self._positions[position.id] = pos_data
            if symbol_key not in self._symbol_positions:
                self._symbol_positions[symbol_key] = set()
            self._symbol_positions[symbol_key].add(position.id)

        # Update market data subscription filter
        self._update_subscription()

        logger.info(
            f"Added position {position.id} ({position.symbol}/{position.exchange}) "
            f"to risk engine"
        )

    def remove_position(self, position_id):
        """Remove a closed position from the in-memory cache.

        Called by StrategyPositionTracker.on_exit_fill().
        """
        with self._positions_lock:
            pos = self._positions.pop(position_id, None)
            if pos:
                symbol_key = f"{pos['exchange']}:{pos['symbol']}"
                if symbol_key in self._symbol_positions:
                    self._symbol_positions[symbol_key].discard(position_id)
                    if not self._symbol_positions[symbol_key]:
                        del self._symbol_positions[symbol_key]

        # Update market data subscription filter
        self._update_subscription()

        logger.info(f"Removed position {position_id} from risk engine")

    def activate_strategy(self, strategy_id):
        """Activate risk monitoring for a strategy — subscribe its positions."""
        self._load_positions_for_strategy(strategy_id)
        self._update_subscription()
        logger.info(f"Risk monitoring activated for strategy {strategy_id}")

    def deactivate_strategy(self, strategy_id):
        """Deactivate risk monitoring for a strategy — remove its positions."""
        to_remove = []
        with self._positions_lock:
            for pos_id, pos in self._positions.items():
                if pos["strategy_id"] == strategy_id:
                    to_remove.append(pos_id)

        for pos_id in to_remove:
            self.remove_position(pos_id)

        logger.info(f"Risk monitoring deactivated for strategy {strategy_id}")

    # ──────────────────────────────────────────────────────────────
    # Manual Close
    # ──────────────────────────────────────────────────────────────

    def close_position(self, position_id, exit_detail="manual"):
        """Manually close a single position."""
        with self._positions_lock:
            pos = self._positions.get(position_id)
            if not pos or pos.get("position_state") != "active":
                return False

        self._trigger_exit(
            position_id, pos, "manual", exit_detail, pos.get("ltp", 0)
        )
        return True

    def close_all_positions(self, strategy_id):
        """Close all active positions for a strategy."""
        to_close = []
        with self._positions_lock:
            for pos_id, pos in self._positions.items():
                if pos["strategy_id"] == strategy_id and pos.get("position_state") == "active":
                    to_close.append((pos_id, pos.copy()))

        for pos_id, pos in to_close:
            self._trigger_exit(pos_id, pos, "manual", "manual_all", pos.get("ltp", 0))

        return len(to_close)

    # ──────────────────────────────────────────────────────────────
    # MIS Auto Square-Off
    # ──────────────────────────────────────────────────────────────

    def check_auto_squareoff(self):
        """Check if any strategy's auto_squareoff_time has been reached.

        Called periodically (every minute). Closes all MIS positions for
        strategies that have hit their squareoff time.
        """
        now = datetime.now(IST)
        current_time_str = now.strftime("%H:%M")

        strategies_to_close = set()

        with self._positions_lock:
            for pos_id, pos in self._positions.items():
                if pos.get("position_state") != "active":
                    continue
                if pos.get("product_type") != "MIS":
                    continue
                squareoff_time = pos.get("auto_squareoff_time", "15:15")
                if current_time_str >= squareoff_time:
                    strategies_to_close.add(pos["strategy_id"])

        for strategy_id in strategies_to_close:
            logger.info(f"Auto square-off triggered for strategy {strategy_id}")
            self.close_all_positions(strategy_id)

    # ──────────────────────────────────────────────────────────────
    # APScheduler — MIS Auto Square-Off & Daily PnL Snapshots
    # ──────────────────────────────────────────────────────────────

    def _start_scheduler(self):
        """Start APScheduler for periodic tasks:
        1. MIS auto square-off — checks every minute during market hours (9:15-15:30 IST)
        2. Daily PnL snapshots — runs at configurable time (default 15:35 IST)
        """
        try:
            from apscheduler.schedulers.background import BackgroundScheduler

            self._scheduler = BackgroundScheduler(
                timezone=IST,
                job_defaults={
                    "coalesce": True,
                    "misfire_grace_time": 300,
                    "max_instances": 1,
                },
            )

            # MIS auto square-off: every minute during market hours
            self._scheduler.add_job(
                self.check_auto_squareoff,
                "cron",
                hour="9-15",
                minute="*",
                id="strategy_auto_squareoff",
            )

            # Daily PnL snapshots: configurable time (default 15:35 IST)
            snapshot_parts = PNL_SNAPSHOT_TIME.split(":")
            snapshot_hour = int(snapshot_parts[0]) if len(snapshot_parts) > 0 else 15
            snapshot_minute = int(snapshot_parts[1]) if len(snapshot_parts) > 1 else 35

            self._scheduler.add_job(
                self._run_daily_snapshots,
                "cron",
                hour=snapshot_hour,
                minute=snapshot_minute,
                id="strategy_daily_pnl_snapshot",
            )

            self._scheduler.start()
            logger.info(
                f"Scheduler started: auto-squareoff (every min 9:15-15:30), "
                f"PnL snapshot ({snapshot_hour:02d}:{snapshot_minute:02d})"
            )

        except Exception as e:
            logger.exception(f"Error starting scheduler: {e}")

    def _run_daily_snapshots(self):
        """Run daily PnL snapshots for all active strategies."""
        try:
            from services.strategy_pnl_service import snapshot_all_strategies
            snapshot_all_strategies()
        except Exception as e:
            logger.exception(f"Error running daily PnL snapshots: {e}")

    # ──────────────────────────────────────────────────────────────
    # Market Data Subscription
    # ──────────────────────────────────────────────────────────────

    def _subscribe_to_market_data(self):
        """Subscribe to MarketDataService with CRITICAL priority."""
        try:
            from services.market_data_service import MarketDataService
            mds = MarketDataService()

            # Build filter set of symbol keys we're monitoring
            with self._positions_lock:
                filter_symbols = set(self._symbol_positions.keys())

            if not filter_symbols:
                return

            self._subscriber_id = mds.subscribe_critical(
                callback=self.on_ltp_update,
                filter_symbols=filter_symbols,
                name="StrategyRiskEngine",
            )
            self._mode = "websocket"
            logger.info(
                f"Subscribed to MarketDataService (CRITICAL) — "
                f"monitoring {len(filter_symbols)} symbols"
            )
        except Exception as e:
            logger.exception(f"Error subscribing to market data: {e}")

    def _unsubscribe_from_market_data(self):
        """Unsubscribe from MarketDataService."""
        if self._subscriber_id is not None:
            try:
                from services.market_data_service import MarketDataService
                mds = MarketDataService()
                mds.unsubscribe_from_updates(self._subscriber_id)
                self._subscriber_id = None
                logger.info("Unsubscribed from MarketDataService")
            except Exception as e:
                logger.debug(f"Error unsubscribing: {e}")

    def _update_subscription(self):
        """Update the MarketDataService filter when positions change."""
        if self._subscriber_id is None:
            # Not yet subscribed — subscribe if we have positions
            with self._positions_lock:
                if self._symbol_positions:
                    self._subscribe_to_market_data()
            return

        try:
            from services.market_data_service import MarketDataService
            mds = MarketDataService()

            with self._positions_lock:
                new_filter = set(self._symbol_positions.keys())

            if not new_filter:
                self._unsubscribe_from_market_data()
                return

            # Update filter on existing subscription
            with mds.data_lock:
                for priority_subs in mds.priority_subscribers.values():
                    if self._subscriber_id in priority_subs:
                        priority_subs[self._subscriber_id]["filter"] = new_filter
                        break

        except Exception as e:
            logger.debug(f"Error updating subscription filter: {e}")

    # ──────────────────────────────────────────────────────────────
    # REST Polling Fallback
    # ──────────────────────────────────────────────────────────────

    def _start_rest_polling(self):
        """Start REST polling fallback when WebSocket data is stale."""
        if self._rest_poll_thread and self._rest_poll_thread.is_alive():
            return

        self._mode = "rest_polling"
        self._rest_poll_thread = threading.Thread(
            target=self._rest_poll_loop, daemon=True, name="RiskEngine-RESTpoll"
        )
        self._rest_poll_thread.start()
        logger.warning("Switched to REST polling fallback mode")

    def _stop_rest_polling(self):
        """Stop REST polling when WebSocket recovers."""
        self._mode = "websocket"
        logger.info("Switched back to WebSocket mode")

    def _rest_poll_loop(self):
        """REST polling loop — fetches LTP via MultiQuotes API."""
        while self._running and self._mode == "rest_polling":
            try:
                with self._positions_lock:
                    symbols = [
                        {"symbol": pos["symbol"], "exchange": pos["exchange"]}
                        for pos in self._positions.values()
                        if pos.get("position_state") == "active"
                    ]

                if not symbols:
                    time.sleep(REST_POLL_INTERVAL)
                    continue

                from services.market_data_service import MarketDataService
                mds = MarketDataService()
                ltp_data = mds.get_bulk_ltp(symbols)

                for symbol_key, ltp_info in ltp_data.items():
                    ltp = ltp_info.get("value", 0)
                    if ltp:
                        parts = symbol_key.split(":", 1)
                        if len(parts) == 2:
                            data = {
                                "symbol": parts[1],
                                "exchange": parts[0],
                                "mode": 1,
                                "data": {"ltp": ltp},
                            }
                            self.on_ltp_update(data)

                self._last_ltp_time = time.time()

            except Exception as e:
                logger.exception(f"Error in REST poll loop: {e}")

            time.sleep(REST_POLL_INTERVAL)

    # ──────────────────────────────────────────────────────────────
    # Health Monitor Thread
    # ──────────────────────────────────────────────────────────────

    def _health_loop(self):
        """Monitor WebSocket health, switch to REST fallback if stale."""
        while self._running:
            try:
                time.sleep(HEALTH_CHECK_INTERVAL)

                if not self._positions:
                    continue

                now = time.time()
                time_since_ltp = now - self._last_ltp_time if self._last_ltp_time else float("inf")

                if self._mode == "websocket" and time_since_ltp > STALE_THRESHOLD:
                    logger.warning(
                        f"WebSocket data stale ({time_since_ltp:.0f}s) — "
                        f"switching to REST polling"
                    )
                    self._start_rest_polling()

                elif self._mode == "rest_polling" and time_since_ltp < HEALTH_CHECK_INTERVAL:
                    # WebSocket recovered — check if it's the WS source
                    from services.market_data_service import MarketDataService
                    mds = MarketDataService()
                    is_safe, _ = mds.is_trade_management_safe()
                    if is_safe:
                        self._stop_rest_polling()

            except Exception as e:
                logger.exception(f"Error in health loop: {e}")

    # ──────────────────────────────────────────────────────────────
    # SocketIO Emit Thread
    # ──────────────────────────────────────────────────────────────

    def _emit_loop(self):
        """Emit SocketIO events for changed positions at throttled interval."""
        while self._running:
            try:
                time.sleep(SOCKETIO_EMIT_INTERVAL)

                # Collect changed positions
                with self._changed_lock:
                    changed = self._changed_positions.copy()
                    self._changed_positions.clear()

                if not changed:
                    continue

                # Group by strategy for batched emit
                by_strategy = {}
                with self._positions_lock:
                    for pos_id in changed:
                        pos = self._positions.get(pos_id)
                        if not pos:
                            continue
                        key = (pos["strategy_id"], pos["strategy_type"])
                        if key not in by_strategy:
                            by_strategy[key] = []
                        by_strategy[key].append(self._pos_to_payload(pos_id, pos))

                # Emit per strategy
                try:
                    from extensions import socketio

                    for (strategy_id, strategy_type), positions in by_strategy.items():
                        socketio.emit(
                            "strategy_position_update",
                            {
                                "strategy_id": strategy_id,
                                "strategy_type": strategy_type,
                                "positions": positions,
                            },
                        )

                        # Aggregate PnL for strategy
                        total_pnl = 0
                        with self._positions_lock:
                            for pos_id, pos in self._positions.items():
                                if pos["strategy_id"] == strategy_id:
                                    total_pnl += pos.get("unrealized_pnl", 0)

                        socketio.emit(
                            "strategy_pnl_update",
                            {
                                "strategy_id": strategy_id,
                                "strategy_type": strategy_type,
                                "total_unrealized_pnl": round(total_pnl, 2),
                                "position_count": len(positions),
                            },
                        )

                except Exception as e:
                    logger.debug(f"Error emitting SocketIO: {e}")

            except Exception as e:
                logger.exception(f"Error in emit loop: {e}")

    def _pos_to_payload(self, pos_id, pos):
        """Convert in-memory position to SocketIO payload."""
        return {
            "position_id": pos_id,
            "symbol": pos["symbol"],
            "exchange": pos["exchange"],
            "action": pos["action"],
            "quantity": pos["quantity"],
            "ltp": pos.get("ltp"),
            "unrealized_pnl": round(pos.get("unrealized_pnl", 0), 2),
            "unrealized_pnl_pct": round(pos.get("unrealized_pnl_pct", 0), 2),
            "peak_price": pos.get("peak_price"),
            "stoploss_price": pos.get("stoploss_price"),
            "target_price": pos.get("target_price"),
            "trailstop_price": pos.get("trailstop_price"),
            "breakeven_activated": pos.get("breakeven_activated", False),
            "position_state": pos.get("position_state"),
            "risk_status": "monitoring" if pos.get("position_state") == "active" else pos.get("position_state", "unknown"),
        }

    def _emit_exit_triggered(self, pos, exit_reason, exit_detail, trigger_ltp):
        """Emit SocketIO event when an exit is triggered."""
        try:
            from extensions import socketio

            socketio.emit(
                "strategy_exit_triggered",
                {
                    "strategy_id": pos["strategy_id"],
                    "strategy_type": pos["strategy_type"],
                    "symbol": pos["symbol"],
                    "exchange": pos["exchange"],
                    "exit_reason": exit_reason,
                    "exit_detail": exit_detail,
                    "trigger_ltp": trigger_ltp,
                },
            )
        except Exception as e:
            logger.debug(f"Error emitting exit triggered: {e}")

    def _emit_risk_paused(self, reason):
        """Emit SocketIO event when risk engine is paused due to stale data."""
        try:
            from extensions import socketio
            socketio.emit("strategy_risk_paused", {"reason": reason})
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────────
    # Position Loading & Recovery
    # ──────────────────────────────────────────────────────────────

    def _load_active_positions(self):
        """Load all active positions from DB into the in-memory cache."""
        try:
            from database.strategy_position_db import get_active_positions

            positions = get_active_positions()
            count = 0
            for pos in positions:
                # Check if the strategy has risk_monitoring enabled
                if not self._is_risk_monitoring_active(pos):
                    continue

                pos_data = self._position_to_dict(pos)
                symbol_key = f"{pos.exchange}:{pos.symbol}"

                with self._positions_lock:
                    self._positions[pos.id] = pos_data
                    if symbol_key not in self._symbol_positions:
                        self._symbol_positions[symbol_key] = set()
                    self._symbol_positions[symbol_key].add(pos.id)

                count += 1

            if count > 0:
                logger.info(f"Loaded {count} active positions for risk monitoring")

                # Initialize peak prices from current LTP
                self._initialize_peak_prices()

        except Exception as e:
            logger.exception(f"Error loading active positions: {e}")

    def _load_positions_for_strategy(self, strategy_id):
        """Load active positions for a specific strategy."""
        try:
            from database.strategy_position_db import get_active_positions

            positions = get_active_positions(strategy_id=strategy_id)
            for pos in positions:
                pos_data = self._position_to_dict(pos)
                symbol_key = f"{pos.exchange}:{pos.symbol}"

                with self._positions_lock:
                    self._positions[pos.id] = pos_data
                    if symbol_key not in self._symbol_positions:
                        self._symbol_positions[symbol_key] = set()
                    self._symbol_positions[symbol_key].add(pos.id)

        except Exception as e:
            logger.exception(f"Error loading positions for strategy {strategy_id}: {e}")

    def _initialize_peak_prices(self):
        """Fetch current LTP for all monitored symbols to initialize peak_price."""
        try:
            from services.market_data_service import MarketDataService
            mds = MarketDataService()

            with self._positions_lock:
                for pos_id, pos in self._positions.items():
                    symbol_key = f"{pos['exchange']}:{pos['symbol']}"
                    ltp_data = mds.get_ltp(pos["symbol"], pos["exchange"])
                    if ltp_data:
                        ltp_value = ltp_data.get("value")
                        if ltp_value:
                            # Only update peak if current LTP is more favorable
                            if pos["action"] == "BUY":
                                pos["peak_price"] = max(
                                    pos.get("peak_price", 0), ltp_value
                                )
                            else:
                                pos["peak_price"] = min(
                                    pos.get("peak_price", float("inf")),
                                    ltp_value,
                                )
        except Exception as e:
            logger.debug(f"Error initializing peak prices: {e}")

    def _is_risk_monitoring_active(self, position):
        """Check if the strategy for this position has risk monitoring enabled."""
        try:
            strategy_type = position.strategy_type
            strategy_id = position.strategy_id

            if strategy_type == "webhook":
                from database.strategy_db import Strategy, db_session
                strategy = db_session.query(Strategy).get(strategy_id)
            else:
                from database.chartink_db import ChartinkStrategy, db_session
                strategy = db_session.query(ChartinkStrategy).get(strategy_id)

            if strategy:
                return getattr(strategy, "risk_monitoring", "active") == "active"
        except Exception:
            pass
        return True  # Default to active if we can't determine

    def _start_order_poller(self):
        """Start the order poller and reload pending orders."""
        try:
            from services.strategy_order_poller import order_poller
            order_poller.start()
            order_poller.reload_pending_orders()
        except Exception as e:
            logger.exception(f"Error starting order poller: {e}")

    def _check_master_contract(self):
        """Check if master contract is downloaded."""
        try:
            from database.auth_db import get_auth_token_broker, get_first_available_api_key

            api_key = get_first_available_api_key()
            if not api_key:
                return False

            auth_token, broker = get_auth_token_broker(api_key)
            if not auth_token or not broker:
                return False

            # Check if broker's master contract DB has data
            from utils.plugin_loader import get_broker_module
            master_module = get_broker_module(broker, "database.master_contract_db")
            if master_module:
                # If the module loaded, master contract infrastructure exists
                # The actual data check happens via symbol queries
                return True
        except Exception as e:
            logger.debug(f"Master contract check: {e}")
        return False

    def _get_api_key_for_user(self, user_id):
        """Get decrypted API key for a user."""
        try:
            from database.auth_db import get_api_key_for_tradingview
            return get_api_key_for_tradingview(user_id)
        except Exception as e:
            logger.exception(f"Error getting API key for user {user_id}: {e}")
            return None

    def _position_to_dict(self, position):
        """Convert a StrategyPosition ORM object to a dict for in-memory cache."""
        return {
            "strategy_id": position.strategy_id,
            "strategy_type": position.strategy_type,
            "user_id": position.user_id,
            "symbol": position.symbol,
            "exchange": position.exchange,
            "action": position.action,
            "quantity": position.quantity,
            "average_entry_price": float(position.average_entry_price or 0),
            "product_type": position.product_type,
            "position_state": position.position_state or "active",
            "ltp": float(position.ltp or 0),
            "unrealized_pnl": float(position.unrealized_pnl or 0),
            "unrealized_pnl_pct": 0,
            "peak_price": float(position.peak_price or position.average_entry_price or 0),
            "stoploss_price": float(position.stoploss_price) if position.stoploss_price else None,
            "target_price": float(position.target_price) if position.target_price else None,
            "trailstop_price": float(position.trailstop_price) if position.trailstop_price else None,
            "trailstop_type": position.trailstop_type,
            "trailstop_value": float(position.trailstop_value) if position.trailstop_value is not None else None,
            "breakeven_type": position.breakeven_type,
            "breakeven_threshold": float(position.breakeven_threshold) if position.breakeven_threshold is not None else None,
            "breakeven_activated": bool(position.breakeven_activated) if position.breakeven_activated else False,
            "tick_size": float(position.tick_size) if getattr(position, "tick_size", None) else 0.05,
            "risk_mode": position.risk_mode,
            "position_group_id": position.position_group_id,
            "exit_execution": getattr(position, "exit_execution", None) or "market",
            "exit_reason": position.exit_reason,
            "exit_detail": position.exit_detail,
            "auto_squareoff_time": getattr(position, "_auto_squareoff_time", "15:15"),
        }

    @property
    def position_count(self):
        """Number of positions currently monitored."""
        with self._positions_lock:
            return len(self._positions)

    @property
    def mode(self):
        """Current engine mode: 'websocket' or 'rest_polling'."""
        return self._mode

    @property
    def is_running(self):
        """Whether the engine is running."""
        return self._running


class _PositionProxy:
    """Lightweight proxy that makes a dict look like an ORM position object.

    The ExitExecutor expects attribute access (position.symbol, position.quantity, etc.)
    but the risk engine works with dicts for speed. This proxy bridges the two.
    """

    def __init__(self, position_id, pos_dict):
        self.id = position_id
        self.strategy_id = pos_dict["strategy_id"]
        self.strategy_type = pos_dict["strategy_type"]
        self.user_id = pos_dict["user_id"]
        self.symbol = pos_dict["symbol"]
        self.exchange = pos_dict["exchange"]
        self.action = pos_dict["action"]
        self.quantity = pos_dict["quantity"]
        self.product_type = pos_dict["product_type"]
        self.exit_execution = pos_dict.get("exit_execution", "market")


# Module-level singleton (created on first import, started explicitly)
risk_engine = StrategyRiskEngine()
