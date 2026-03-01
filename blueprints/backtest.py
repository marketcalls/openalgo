# blueprints/backtest.py
"""
Backtest Blueprint

API routes for backtesting engine: run, status, results, list, cancel, delete, export.
SSE endpoint for live progress streaming.
Note: The /backtest pages are served by react_app.py (React frontend).
"""

import csv
import io
import json
import os
import traceback
from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Queue

from flask import Blueprint, Response, jsonify, request, session, stream_with_context

from database.backtest_db import (
    BacktestRun,
    BacktestTrade,
    db_session,
    delete_backtest,
    get_backtest_run,
    get_backtest_trades,
    get_user_backtests,
)
from limiter import limiter
from services.backtest_engine import (
    cancel_backtest,
    generate_backtest_id,
    get_active_backtests,
    start_backtest,
    validate_data_availability,
)
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

# Rate limits
API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "50 per second")

# Thread pool for backtest execution (max 3 concurrent)
_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="backtest")

# Progress queues for SSE — {backtest_id: Queue}
_progress_queues = {}

backtest_bp = Blueprint("backtest_bp", __name__, url_prefix="/backtest")


@backtest_bp.errorhandler(429)
def ratelimit_handler(e):
    """Handle rate limit exceeded errors"""
    return jsonify(
        {"status": "error", "message": "Rate limit exceeded. Please try again later."}
    ), 429


# ─── Run a Backtest ───────────────────────────────────────────────

@backtest_bp.route("/api/run", methods=["POST"])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def run_backtest():
    """Launch a new backtest run."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "No JSON body"}), 400

        # Validate required fields
        required = ["strategy_code", "symbols", "start_date", "end_date", "interval"]
        missing = [f for f in required if not data.get(f)]
        if missing:
            return jsonify({
                "status": "error",
                "message": f"Missing required fields: {', '.join(missing)}",
            }), 400

        # Build config
        backtest_id = generate_backtest_id()
        symbols = data.get("symbols", [])
        if isinstance(symbols, str):
            symbols = [s.strip() for s in symbols.split(",") if s.strip()]

        config = {
            "backtest_id": backtest_id,
            "user_id": session.get("user"),
            "name": data.get("name", f"Backtest {backtest_id}"),
            "strategy_id": data.get("strategy_id"),
            "strategy_code": data["strategy_code"],
            "symbols": symbols,
            "exchange": data.get("exchange", "NSE"),
            "start_date": data["start_date"],
            "end_date": data["end_date"],
            "interval": data["interval"],
            "initial_capital": float(data.get("initial_capital", 100000)),
            "slippage_pct": float(data.get("slippage_pct", 0.05)),
            "commission_per_order": float(data.get("commission_per_order", 20.0)),
            "commission_pct": float(data.get("commission_pct", 0.0)),
            "data_source": data.get("data_source", "db"),
        }

        # Create progress queue for SSE
        progress_queue = Queue(maxsize=200)
        _progress_queues[backtest_id] = progress_queue

        def progress_callback(bt_id, pct, message):
            q = _progress_queues.get(bt_id)
            if q:
                try:
                    q.put_nowait({"backtest_id": bt_id, "progress": pct, "message": message})
                except Exception:
                    pass  # Queue full — skip update

        # Submit to thread pool
        def _run_and_cleanup():
            try:
                result = start_backtest(config, progress_callback)
                # Signal completion via queue
                q = _progress_queues.get(backtest_id)
                if q:
                    q.put_nowait({
                        "backtest_id": backtest_id,
                        "progress": 100,
                        "message": "done",
                        "status": result.get("status", "completed"),
                    })
            except Exception as e:
                logger.exception(f"Backtest thread error: {e}")
                q = _progress_queues.get(backtest_id)
                if q:
                    q.put_nowait({
                        "backtest_id": backtest_id,
                        "progress": 0,
                        "message": str(e),
                        "status": "failed",
                    })
            finally:
                # Cleanup queue after a delay (let SSE drain)
                import threading
                def _cleanup():
                    import time
                    time.sleep(30)
                    _progress_queues.pop(backtest_id, None)
                threading.Thread(target=_cleanup, daemon=True).start()

        _executor.submit(_run_and_cleanup)

        return jsonify({
            "status": "success",
            "backtest_id": backtest_id,
            "message": "Backtest started",
        }), 202

    except Exception as e:
        logger.error(f"Error starting backtest: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


# ─── SSE Progress Stream ─────────────────────────────────────────

@backtest_bp.route("/api/events/<backtest_id>")
@check_session_validity
def backtest_events(backtest_id):
    """SSE endpoint for live backtest progress updates."""
    def generate():
        q = _progress_queues.get(backtest_id)
        if not q:
            # Check if backtest already completed
            run = get_backtest_run(backtest_id)
            if run and run.status in ("completed", "failed", "cancelled"):
                yield f"data: {json.dumps({'backtest_id': backtest_id, 'progress': 100, 'message': 'done', 'status': run.status})}\n\n"
            else:
                yield f"data: {json.dumps({'backtest_id': backtest_id, 'progress': 0, 'message': 'Not found'})}\n\n"
            return

        while True:
            try:
                event = q.get(timeout=30)  # 30s heartbeat timeout
                yield f"data: {json.dumps(event)}\n\n"
                # Check if done
                if event.get("status") in ("completed", "failed", "cancelled"):
                    break
                if event.get("message") == "done":
                    break
            except Empty:
                # Send heartbeat to keep connection alive
                yield f"data: {json.dumps({'heartbeat': True})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ─── Status & Results ─────────────────────────────────────────────

@backtest_bp.route("/api/status/<backtest_id>")
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def backtest_status(backtest_id):
    """Get current status of a backtest run."""
    try:
        run = get_backtest_run(backtest_id)
        if not run:
            return jsonify({"status": "error", "message": "Backtest not found"}), 404

        return jsonify({
            "status": "success",
            "data": {
                "backtest_id": run.id,
                "name": run.name,
                "status": run.status,
                "created_at": str(run.created_at) if run.created_at else None,
                "started_at": str(run.started_at) if run.started_at else None,
                "completed_at": str(run.completed_at) if run.completed_at else None,
                "duration_ms": run.duration_ms,
                "error_message": run.error_message,
            },
        })
    except Exception as e:
        logger.error(f"Error fetching backtest status: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@backtest_bp.route("/api/results/<backtest_id>")
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def backtest_results(backtest_id):
    """Get full results for a completed backtest."""
    try:
        run = get_backtest_run(backtest_id)
        if not run:
            return jsonify({"status": "error", "message": "Backtest not found"}), 404

        if run.status != "completed":
            return jsonify({
                "status": "error",
                "message": f"Backtest is {run.status}, not completed",
            }), 400

        # Build metrics dict from DB columns
        metrics = {
            "final_capital": float(run.final_capital or 0),
            "total_return_pct": float(run.total_return_pct or 0),
            "cagr": float(run.cagr or 0),
            "sharpe_ratio": float(run.sharpe_ratio or 0),
            "sortino_ratio": float(run.sortino_ratio or 0),
            "max_drawdown_pct": float(run.max_drawdown_pct or 0),
            "calmar_ratio": float(run.calmar_ratio or 0),
            "win_rate": float(run.win_rate or 0),
            "profit_factor": float(run.profit_factor or 0),
            "total_trades": run.total_trades or 0,
            "winning_trades": run.winning_trades or 0,
            "losing_trades": run.losing_trades or 0,
            "avg_win": float(run.avg_win or 0),
            "avg_loss": float(run.avg_loss or 0),
            "max_win": float(run.max_win or 0),
            "max_loss": float(run.max_loss or 0),
            "expectancy": float(run.expectancy or 0),
            "avg_holding_bars": run.avg_holding_bars or 0,
            "total_commission": float(run.total_commission or 0),
            "total_slippage": float(run.total_slippage or 0),
        }

        # Parse stored JSON
        equity_curve = json.loads(run.equity_curve_json) if run.equity_curve_json else []
        monthly_returns = json.loads(run.monthly_returns_json) if run.monthly_returns_json else {}

        # Get trades
        trades = get_backtest_trades(backtest_id)
        trades_list = [
            {
                "trade_num": t.trade_num,
                "symbol": t.symbol,
                "exchange": t.exchange,
                "action": t.action,
                "quantity": t.quantity,
                "entry_price": float(t.entry_price or 0),
                "exit_price": float(t.exit_price or 0),
                "entry_time": t.entry_time,
                "exit_time": t.exit_time,
                "pnl": float(t.pnl or 0),
                "pnl_pct": float(t.pnl_pct or 0),
                "commission": float(t.commission or 0),
                "slippage_cost": float(t.slippage_cost or 0),
                "net_pnl": float(t.net_pnl or 0),
                "bars_held": t.bars_held or 0,
                "product": t.product,
                "strategy_tag": t.strategy_tag,
            }
            for t in trades
        ]

        return jsonify({
            "status": "success",
            "data": {
                "backtest_id": run.id,
                "name": run.name,
                "config": {
                    "symbols": json.loads(run.symbols) if run.symbols else [],
                    "start_date": run.start_date,
                    "end_date": run.end_date,
                    "interval": run.interval,
                    "initial_capital": float(run.initial_capital or 0),
                    "slippage_pct": float(run.slippage_pct or 0),
                    "commission_per_order": float(run.commission_per_order or 0),
                    "commission_pct": float(run.commission_pct or 0),
                },
                "metrics": metrics,
                "equity_curve": equity_curve,
                "monthly_returns": monthly_returns,
                "trades": trades_list,
                "duration_ms": run.duration_ms,
                "created_at": str(run.created_at) if run.created_at else None,
                "completed_at": str(run.completed_at) if run.completed_at else None,
            },
        })
    except Exception as e:
        logger.error(f"Error fetching backtest results: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


# ─── List Backtests ───────────────────────────────────────────────

@backtest_bp.route("/api/list")
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def list_backtests():
    """List all backtests for the current user."""
    try:
        user_id = session.get("user")
        limit = request.args.get("limit", 50, type=int)
        runs = get_user_backtests(user_id, limit=limit)

        data = []
        for run in runs:
            data.append({
                "backtest_id": run.id,
                "name": run.name,
                "status": run.status,
                "symbols": json.loads(run.symbols) if run.symbols else [],
                "interval": run.interval,
                "start_date": run.start_date,
                "end_date": run.end_date,
                "initial_capital": float(run.initial_capital or 0),
                "total_return_pct": float(run.total_return_pct or 0) if run.total_return_pct else None,
                "sharpe_ratio": float(run.sharpe_ratio or 0) if run.sharpe_ratio else None,
                "max_drawdown_pct": float(run.max_drawdown_pct or 0) if run.max_drawdown_pct else None,
                "total_trades": run.total_trades or 0,
                "win_rate": float(run.win_rate or 0) if run.win_rate else None,
                "duration_ms": run.duration_ms,
                "created_at": str(run.created_at) if run.created_at else None,
                "error_message": run.error_message,
            })

        return jsonify({"status": "success", "data": data})
    except Exception as e:
        logger.error(f"Error listing backtests: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ─── Cancel ───────────────────────────────────────────────────────

@backtest_bp.route("/api/cancel/<backtest_id>", methods=["POST"])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def cancel_backtest_route(backtest_id):
    """Cancel a running backtest."""
    try:
        cancelled = cancel_backtest(backtest_id)
        if cancelled:
            return jsonify({"status": "success", "message": "Cancellation requested"})
        return jsonify({
            "status": "error",
            "message": "Backtest not running or not found",
        }), 404
    except Exception as e:
        logger.error(f"Error cancelling backtest: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ─── Delete ───────────────────────────────────────────────────────

@backtest_bp.route("/api/delete/<backtest_id>", methods=["DELETE"])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def delete_backtest_route(backtest_id):
    """Delete a backtest run and all its trades."""
    try:
        # Verify ownership
        run = get_backtest_run(backtest_id)
        if not run:
            return jsonify({"status": "error", "message": "Backtest not found"}), 404

        if run.user_id != session.get("user"):
            return jsonify({"status": "error", "message": "Unauthorized"}), 403

        success = delete_backtest(backtest_id)
        if success:
            return jsonify({"status": "success", "message": "Backtest deleted"})
        return jsonify({"status": "error", "message": "Failed to delete"}), 500
    except Exception as e:
        logger.error(f"Error deleting backtest: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ─── Export ───────────────────────────────────────────────────────

@backtest_bp.route("/api/export/<backtest_id>")
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def export_backtest(backtest_id):
    """Export backtest trades as CSV."""
    try:
        run = get_backtest_run(backtest_id)
        if not run:
            return jsonify({"status": "error", "message": "Backtest not found"}), 404

        trades = get_backtest_trades(backtest_id)

        # Build CSV
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Trade#", "Symbol", "Exchange", "Action", "Quantity",
            "Entry Price", "Exit Price", "Entry Time", "Exit Time",
            "P&L", "P&L%", "Commission", "Slippage", "Net P&L",
            "Bars Held", "Product", "Strategy",
        ])
        for t in trades:
            writer.writerow([
                t.trade_num, t.symbol, t.exchange, t.action, t.quantity,
                float(t.entry_price or 0), float(t.exit_price or 0),
                t.entry_time, t.exit_time,
                float(t.pnl or 0), float(t.pnl_pct or 0),
                float(t.commission or 0), float(t.slippage_cost or 0),
                float(t.net_pnl or 0), t.bars_held or 0,
                t.product, t.strategy_tag,
            ])

        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=backtest_{backtest_id}.csv"
            },
        )
    except Exception as e:
        logger.error(f"Error exporting backtest: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ─── Check Data Availability ─────────────────────────────────────

@backtest_bp.route("/api/check-data", methods=["POST"])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def check_data():
    """Check if historical data is available for the requested configuration."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "No JSON body"}), 400

        symbols = data.get("symbols", [])
        if isinstance(symbols, str):
            symbols = [s.strip() for s in symbols.split(",") if s.strip()]

        exchange = data.get("exchange", "NSE")
        interval = data.get("interval", "D")
        start_date = data.get("start_date", "")
        end_date = data.get("end_date", "")

        result = validate_data_availability(symbols, exchange, interval, start_date, end_date)
        return jsonify({"status": "success", "data": result})
    except Exception as e:
        logger.error(f"Error checking data availability: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ─── Compare Backtests ────────────────────────────────────────────

@backtest_bp.route("/api/compare", methods=["POST"])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def compare_backtests():
    """Get comparison data for multiple backtests."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "No JSON body"}), 400

        backtest_ids = data.get("backtest_ids", [])
        if len(backtest_ids) < 2:
            return jsonify({
                "status": "error",
                "message": "Need at least 2 backtest IDs to compare",
            }), 400

        if len(backtest_ids) > 5:
            return jsonify({
                "status": "error",
                "message": "Maximum 5 backtests can be compared at once",
            }), 400

        results = []
        for bt_id in backtest_ids:
            run = get_backtest_run(bt_id)
            if not run or run.status != "completed":
                continue

            equity_curve = json.loads(run.equity_curve_json) if run.equity_curve_json else []

            results.append({
                "backtest_id": run.id,
                "name": run.name,
                "config": {
                    "symbols": json.loads(run.symbols) if run.symbols else [],
                    "start_date": run.start_date,
                    "end_date": run.end_date,
                    "interval": run.interval,
                    "initial_capital": float(run.initial_capital or 0),
                },
                "metrics": {
                    "final_capital": float(run.final_capital or 0),
                    "total_return_pct": float(run.total_return_pct or 0),
                    "cagr": float(run.cagr or 0),
                    "sharpe_ratio": float(run.sharpe_ratio or 0),
                    "sortino_ratio": float(run.sortino_ratio or 0),
                    "max_drawdown_pct": float(run.max_drawdown_pct or 0),
                    "calmar_ratio": float(run.calmar_ratio or 0),
                    "win_rate": float(run.win_rate or 0),
                    "profit_factor": float(run.profit_factor or 0),
                    "total_trades": run.total_trades or 0,
                    "expectancy": float(run.expectancy or 0),
                },
                "equity_curve": equity_curve,
            })

        return jsonify({"status": "success", "data": results})
    except Exception as e:
        logger.error(f"Error comparing backtests: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
