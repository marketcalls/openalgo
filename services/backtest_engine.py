# services/backtest_engine.py
"""
Backtest Engine — Bar-by-bar replay orchestrator.

Loads data from Historify DuckDB, builds a unified timestamp timeline,
patches the strategy code, and replays bar-by-bar. Emits progress via
callback, computes metrics on completion.

Supports cancellation via threading.Event.
"""

import json
import time as _time
import uuid
from datetime import datetime, timezone
from threading import Event

import pandas as pd

from database.backtest_db import BacktestRun, BacktestTrade, db_session
from database.historify_db import get_data_range, get_ohlcv
from services.backtest_client import BacktestClient
from services.backtest_metrics import calculate_metrics
from services.backtest_patcher import StrategyPatcher
from utils.logging import get_logger

logger = get_logger(__name__)


def generate_backtest_id():
    """Generate a unique backtest ID: BT-YYYYMMDD-HHMMSS-{uuid8}."""
    now = datetime.now(timezone.utc)
    short_uuid = uuid.uuid4().hex[:8]
    return f"BT-{now.strftime('%Y%m%d-%H%M%S')}-{short_uuid}"


def validate_data_availability(symbols, exchange, interval, start_date, end_date):
    """
    Check if data exists in Historify for the requested configuration.

    Args:
        symbols: list of symbol strings
        exchange: exchange code
        interval: bar interval string
        start_date: YYYY-MM-DD string
        end_date: YYYY-MM-DD string

    Returns:
        dict: {available: bool, details: {symbol: {has_data, record_count, ...}}}
    """
    # Determine storage interval for data_range check
    storage_interval = _storage_interval_for(interval)

    details = {}
    all_available = True

    for sym in symbols:
        range_info = get_data_range(sym, exchange, storage_interval)
        if range_info and range_info.get("record_count", 0) > 0:
            details[sym] = {
                "has_data": True,
                "record_count": range_info["record_count"],
                "first_timestamp": range_info["first_timestamp"],
                "last_timestamp": range_info["last_timestamp"],
            }
        else:
            details[sym] = {"has_data": False, "record_count": 0}
            all_available = False

    return {"available": all_available, "details": details}


def _storage_interval_for(interval):
    """Map requested interval to Historify storage interval for catalog lookup."""
    intraday = {"1m", "3m", "5m", "10m", "15m", "30m", "1h"}
    if interval in intraday:
        return "1m"
    return "D"


class BacktestEngine:
    """
    Orchestrates a single backtest run: data loading, strategy patching,
    bar-by-bar replay, metric computation, and result persistence.
    """

    def __init__(self, config, progress_callback=None, cancel_event=None):
        """
        Args:
            config: dict with keys:
                backtest_id, user_id, name, strategy_id, strategy_code,
                symbols (list), exchange, start_date, end_date, interval,
                initial_capital, slippage_pct, commission_per_order,
                commission_pct, data_source
            progress_callback: callable(backtest_id, pct, message) for progress updates
            cancel_event: threading.Event to signal cancellation
        """
        self.config = config
        self.backtest_id = config["backtest_id"]
        self.progress_callback = progress_callback or (lambda *a, **kw: None)
        self.cancel_event = cancel_event or Event()

    def run(self):
        """
        Execute the full backtest pipeline.

        Returns:
            dict: {status, metrics, trades_count, duration_ms, error}
        """
        start_time = _time.time()

        try:
            self._update_status("running")
            self._emit_progress(0, "Loading historical data...")

            # Step 1: Load data from Historify
            data_frames = self._load_data()
            if not data_frames:
                return self._fail("No data available for the requested configuration")

            if self._is_cancelled():
                return self._cancel()

            self._emit_progress(10, "Building timeline...")

            # Step 2: Build unified timestamp timeline
            timeline = self._build_timeline(data_frames)
            if not timeline:
                return self._fail("Could not build timeline — no overlapping data")

            if self._is_cancelled():
                return self._cancel()

            self._emit_progress(15, "Patching strategy...")

            # Step 3: Create BacktestClient and inject data
            client = BacktestClient(self.config)
            for key, df in data_frames.items():
                client.data[key] = df

            # Step 4: Patch strategy code
            patcher = StrategyPatcher()
            try:
                iteration_fn = patcher.patch(self.config["strategy_code"], client)
            except ValueError as e:
                return self._fail(f"Strategy error: {e}")

            if self._is_cancelled():
                return self._cancel()

            self._emit_progress(20, "Running backtest...")

            # Step 5: Bar-by-bar replay
            total_bars = len(timeline)
            progress_interval = max(total_bars // 100, 1)  # Update every ~1%

            for i, timestamp in enumerate(timeline):
                if self._is_cancelled():
                    return self._cancel()

                # Advance client to this bar
                client.advance_to(timestamp)

                # Process pending orders BEFORE strategy iteration
                client.process_pending_orders()

                # Execute strategy iteration
                try:
                    iteration_fn()
                except Exception as e:
                    # Strategy errors are non-fatal — log and continue
                    logger.debug(f"Strategy iteration error at bar {i}: {e}")

                # Record equity AFTER iteration
                client.record_equity(timestamp)

                # Emit progress periodically
                if i % progress_interval == 0 or i == total_bars - 1:
                    pct = 20 + int((i / max(total_bars - 1, 1)) * 70)  # 20-90%
                    self._emit_progress(
                        pct,
                        f"Processing bar {i + 1}/{total_bars}",
                    )

            self._emit_progress(90, "Closing positions...")

            # Step 6: Close all open positions at end
            client.close_all_positions_at_end()
            # Record final equity after closing ONLY if positions were actually closed
            # (which changes capital). Use a distinct timestamp to avoid duplicates.
            if timeline and any(
                pos["qty"] != 0 for pos in client.positions.values()
            ) is False:
                # Positions were closed — update the last equity point in-place
                # instead of appending a duplicate timestamp
                if client.equity_curve:
                    last = client.equity_curve[-1]
                    unrealized = client._total_unrealized()
                    equity = client.capital + unrealized
                    client.peak_equity = max(client.peak_equity, equity)
                    dd = 0.0
                    if client.peak_equity > 0:
                        dd = (client.peak_equity - equity) / client.peak_equity
                    last["equity"] = round(equity, 2)
                    last["drawdown"] = round(dd, 6)

            if self._is_cancelled():
                return self._cancel()

            self._emit_progress(92, "Computing metrics...")

            # Step 7: Compute metrics
            metrics = calculate_metrics(
                trades=client.trades,
                equity_curve=client.equity_curve,
                initial_capital=float(self.config["initial_capital"]),
                interval=self.config["interval"],
            )

            self._emit_progress(95, "Saving results...")

            # Step 8: Persist results
            duration_ms = int((_time.time() - start_time) * 1000)
            self._save_results(client, metrics, duration_ms)

            self._emit_progress(100, "Backtest complete")
            self._update_status("completed")

            return {
                "status": "completed",
                "backtest_id": self.backtest_id,
                "metrics": metrics,
                "trades_count": len(client.trades),
                "duration_ms": duration_ms,
            }

        except Exception as e:
            logger.exception(f"Backtest {self.backtest_id} failed: {e}")
            return self._fail(str(e))

    # ─── Data Loading ─────────────────────────────────────────────

    def _load_data(self):
        """Load OHLCV data for all symbols from Historify."""
        symbols = self.config.get("symbols", [])
        if isinstance(symbols, str):
            symbols = json.loads(symbols)

        exchange = self.config.get("exchange", "NSE")
        interval = self.config["interval"]
        start_date = self.config["start_date"]
        end_date = self.config["end_date"]

        # Convert dates to timestamps
        start_ts = self._date_to_timestamp(start_date)
        end_ts = self._date_to_timestamp(end_date, end_of_day=True)

        data_frames = {}

        for sym in symbols:
            try:
                df = get_ohlcv(
                    symbol=sym,
                    exchange=exchange,
                    interval=interval,
                    start_timestamp=start_ts,
                    end_timestamp=end_ts,
                )
                if df is not None and not df.empty:
                    key = f"{sym}:{exchange}"
                    data_frames[key] = df
                    logger.debug(
                        f"Loaded {len(df)} bars for {key} "
                        f"({interval}, {start_date} to {end_date})"
                    )
                else:
                    logger.warning(f"No data for {sym}:{exchange} ({interval})")
            except Exception as e:
                logger.error(f"Error loading data for {sym}:{exchange}: {e}")

        return data_frames

    def _build_timeline(self, data_frames):
        """
        Build a unified, sorted timeline of unique timestamps across all symbols.
        This ensures multi-symbol strategies see consistent bar timing.
        """
        all_timestamps = set()
        for key, df in data_frames.items():
            if "timestamp" in df.columns:
                all_timestamps.update(df["timestamp"].tolist())

        if not all_timestamps:
            return []

        return sorted(all_timestamps)

    def _date_to_timestamp(self, date_str, end_of_day=False):
        """Convert YYYY-MM-DD string to epoch timestamp."""
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        if end_of_day:
            dt = dt.replace(hour=23, minute=59, second=59)
        # Use UTC for consistency
        dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())

    # ─── Persistence ──────────────────────────────────────────────

    def _save_results(self, client, metrics, duration_ms):
        """Save backtest results (metrics + trades) to the database."""
        try:
            # Update the BacktestRun record with results
            run = BacktestRun.query.filter_by(id=self.backtest_id).first()
            if not run:
                logger.error(f"BacktestRun {self.backtest_id} not found for result save")
                return

            # Metrics
            run.final_capital = metrics.get("final_capital")
            run.total_return_pct = metrics.get("total_return_pct")
            run.cagr = metrics.get("cagr")
            run.sharpe_ratio = metrics.get("sharpe_ratio")
            run.sortino_ratio = metrics.get("sortino_ratio")
            run.max_drawdown_pct = metrics.get("max_drawdown_pct")
            run.calmar_ratio = metrics.get("calmar_ratio")
            run.win_rate = metrics.get("win_rate")
            run.profit_factor = metrics.get("profit_factor")
            run.total_trades = metrics.get("total_trades", 0)
            run.winning_trades = metrics.get("winning_trades", 0)
            run.losing_trades = metrics.get("losing_trades", 0)
            run.avg_win = metrics.get("avg_win")
            run.avg_loss = metrics.get("avg_loss")
            run.max_win = metrics.get("max_win")
            run.max_loss = metrics.get("max_loss")
            run.expectancy = metrics.get("expectancy")
            run.avg_holding_bars = metrics.get("avg_holding_bars")
            run.total_commission = metrics.get("total_commission")
            run.total_slippage = metrics.get("total_slippage")

            # Serialize large data
            # Limit equity curve to max 5000 points for storage
            equity_curve = client.equity_curve
            if len(equity_curve) > 5000:
                step = len(equity_curve) // 5000
                equity_curve = equity_curve[::step]
                # Always include the last point
                if equity_curve[-1] != client.equity_curve[-1]:
                    equity_curve.append(client.equity_curve[-1])

            run.equity_curve_json = json.dumps(equity_curve)
            run.monthly_returns_json = json.dumps(
                metrics.get("monthly_returns", {})
            )

            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)
            run.duration_ms = duration_ms

            # Save trades
            for t in client.trades:
                trade = BacktestTrade(
                    backtest_id=self.backtest_id,
                    trade_num=t["trade_num"],
                    symbol=t["symbol"],
                    exchange=t["exchange"],
                    action=t["action"],
                    quantity=t["quantity"],
                    entry_price=t["entry_price"],
                    exit_price=t["exit_price"],
                    entry_time=str(t.get("entry_time", "")),
                    exit_time=str(t.get("exit_time", "")),
                    pnl=t.get("pnl", 0),
                    pnl_pct=t.get("pnl_pct", 0),
                    commission=t.get("commission", 0),
                    slippage_cost=t.get("slippage_cost", 0),
                    net_pnl=t.get("net_pnl", 0),
                    bars_held=t.get("bars_held", 0),
                    product=t.get("product"),
                    strategy_tag=t.get("strategy_tag"),
                )
                db_session.add(trade)

            db_session.commit()
            logger.info(
                f"Backtest {self.backtest_id} saved: "
                f"{len(client.trades)} trades, "
                f"return={metrics.get('total_return_pct', 0):.2f}%"
            )

        except Exception as e:
            db_session.rollback()
            logger.exception(f"Error saving backtest results: {e}")

    # ─── Status & Progress ────────────────────────────────────────

    def _update_status(self, status, error_message=None):
        """Update backtest run status in the database."""
        try:
            run = BacktestRun.query.filter_by(id=self.backtest_id).first()
            if run:
                run.status = status
                if status == "running":
                    run.started_at = datetime.now(timezone.utc)
                if error_message:
                    run.error_message = error_message
                db_session.commit()
        except Exception as e:
            db_session.rollback()
            logger.error(f"Error updating backtest status: {e}")

    def _emit_progress(self, pct, message):
        """Emit progress update via callback."""
        try:
            self.progress_callback(self.backtest_id, pct, message)
        except Exception:
            pass  # Progress is best-effort

    def _is_cancelled(self):
        """Check if cancellation has been requested."""
        return self.cancel_event.is_set()

    def _cancel(self):
        """Handle cancellation."""
        self._update_status("cancelled")
        self._emit_progress(0, "Backtest cancelled")
        return {"status": "cancelled", "backtest_id": self.backtest_id}

    def _fail(self, error_message):
        """Handle failure."""
        self._update_status("failed", error_message)
        self._emit_progress(0, f"Failed: {error_message}")
        return {
            "status": "failed",
            "backtest_id": self.backtest_id,
            "error": error_message,
        }


# ─── Module-level runner (used by blueprint) ─────────────────────

# Active backtest runs — {backtest_id: cancel_event}
_active_runs = {}


def start_backtest(config, progress_callback=None):
    """
    Create a BacktestRun record and launch the engine.

    Args:
        config: dict with all backtest configuration
        progress_callback: callable(backtest_id, pct, message)

    Returns:
        dict: {backtest_id, status}
    """
    backtest_id = config.get("backtest_id") or generate_backtest_id()
    config["backtest_id"] = backtest_id

    # Create DB record
    try:
        symbols = config.get("symbols", [])
        if isinstance(symbols, list):
            symbols_json = json.dumps(symbols)
        else:
            symbols_json = symbols

        run = BacktestRun(
            id=backtest_id,
            user_id=config.get("user_id", "default"),
            name=config.get("name", f"Backtest {backtest_id}"),
            strategy_id=config.get("strategy_id"),
            strategy_code=config.get("strategy_code", ""),
            symbols=symbols_json,
            start_date=config["start_date"],
            end_date=config["end_date"],
            interval=config["interval"],
            initial_capital=config.get("initial_capital", 100000),
            slippage_pct=config.get("slippage_pct", 0.05),
            commission_per_order=config.get("commission_per_order", 20.0),
            commission_pct=config.get("commission_pct", 0.0),
            data_source=config.get("data_source", "db"),
            status="pending",
        )
        db_session.add(run)
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        logger.exception(f"Error creating backtest run: {e}")
        return {"status": "error", "error": str(e)}

    # Create cancel event
    cancel_event = Event()
    _active_runs[backtest_id] = cancel_event

    # Run engine
    engine = BacktestEngine(config, progress_callback, cancel_event)
    try:
        result = engine.run()
    finally:
        _active_runs.pop(backtest_id, None)
        # Clean up scoped_session to prevent stale sessions in thread pool reuse
        try:
            db_session.remove()
        except Exception:
            pass

    return result


def cancel_backtest(backtest_id):
    """Request cancellation of a running backtest."""
    cancel_event = _active_runs.get(backtest_id)
    if cancel_event:
        cancel_event.set()
        return True
    return False


def get_active_backtests():
    """Return list of currently running backtest IDs."""
    return list(_active_runs.keys())
