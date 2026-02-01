import csv
import io
import os
import traceback
from datetime import datetime

from flask import Blueprint, Response, flash, jsonify, redirect, render_template, request, session, url_for

from database.sandbox_db import (
    SandboxFunds,
    SandboxHoldings,
    SandboxOrders,
    SandboxPositions,
    SandboxTrades,
    db_session,
    get_all_configs,
    get_config,
    set_config,
)
from limiter import limiter
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

# Use existing rate limits from .env (same as API endpoints)
API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "50 per second")

sandbox_bp = Blueprint("sandbox_bp", __name__, url_prefix="/sandbox")


@sandbox_bp.errorhandler(429)
def ratelimit_handler(e):
    """Handle rate limit exceeded errors"""
    return jsonify(
        {"status": "error", "message": "Rate limit exceeded. Please try again later."}
    ), 429


@sandbox_bp.route("/")
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def sandbox_config():
    """Render the sandbox configuration page"""
    try:
        # Get all current configuration values
        configs = get_all_configs()

        # Organize configs into categories for better UI presentation
        organized_configs = {
            "capital": {
                "title": "Capital Settings",
                "configs": {
                    "starting_capital": configs.get("starting_capital", {}),
                    "reset_day": configs.get("reset_day", {}),
                    "reset_time": configs.get("reset_time", {}),
                },
            },
            "leverage": {
                "title": "Leverage Settings",
                "configs": {
                    "equity_mis_leverage": configs.get("equity_mis_leverage", {}),
                    "equity_cnc_leverage": configs.get("equity_cnc_leverage", {}),
                    "futures_leverage": configs.get("futures_leverage", {}),
                    "option_buy_leverage": configs.get("option_buy_leverage", {}),
                    "option_sell_leverage": configs.get("option_sell_leverage", {}),
                },
            },
            "square_off": {
                "title": "Square-Off Times (IST)",
                "configs": {
                    "nse_bse_square_off_time": configs.get("nse_bse_square_off_time", {}),
                    "cds_bcd_square_off_time": configs.get("cds_bcd_square_off_time", {}),
                    "mcx_square_off_time": configs.get("mcx_square_off_time", {}),
                    "ncdex_square_off_time": configs.get("ncdex_square_off_time", {}),
                },
            },
            "intervals": {
                "title": "Update Intervals (seconds)",
                "configs": {
                    "order_check_interval": configs.get("order_check_interval", {}),
                    "mtm_update_interval": configs.get("mtm_update_interval", {}),
                },
            },
        }

        return render_template("sandbox.html", configs=organized_configs)
    except Exception as e:
        logger.exception(f"Error rendering sandbox config: {str(e)}\n{traceback.format_exc()}")
        flash("Error loading sandbox configuration", "error")
        return redirect(url_for("core_bp.home"))


@sandbox_bp.route("/api/configs")
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def api_get_configs():
    """API endpoint to get all sandbox configuration values as JSON"""
    try:
        # Get all current configuration values
        configs = get_all_configs()

        # Default values to use if config not in database
        defaults = {
            "starting_capital": {
                "value": "10000000.00",
                "description": "Starting sandbox capital in INR",
            },
            "reset_day": {"value": "Never", "description": "Day of week for automatic fund reset"},
            "reset_time": {"value": "00:00", "description": "Time for automatic fund reset (IST)"},
            "equity_mis_leverage": {
                "value": "5",
                "description": "Leverage multiplier for equity MIS",
            },
            "equity_cnc_leverage": {
                "value": "1",
                "description": "Leverage multiplier for equity CNC",
            },
            "futures_leverage": {"value": "10", "description": "Leverage multiplier for futures"},
            "option_buy_leverage": {"value": "1", "description": "Leverage for buying options"},
            "option_sell_leverage": {"value": "1", "description": "Leverage for selling options"},
            "nse_bse_square_off_time": {
                "value": "15:15",
                "description": "Square-off time for NSE/BSE MIS",
            },
            "cds_bcd_square_off_time": {
                "value": "16:45",
                "description": "Square-off time for CDS/BCD MIS",
            },
            "mcx_square_off_time": {"value": "23:30", "description": "Square-off time for MCX MIS"},
            "ncdex_square_off_time": {
                "value": "17:00",
                "description": "Square-off time for NCDEX MIS",
            },
            "order_check_interval": {
                "value": "5",
                "description": "Interval to check pending orders (1-30 sec)",
            },
            "mtm_update_interval": {
                "value": "5",
                "description": "Interval to update MTM (0-60 sec)",
            },
        }

        # Helper to get config with fallback to default
        def get_config_value(key):
            return configs.get(key, defaults.get(key, {"value": "", "description": ""}))

        # Organize configs into categories for better UI presentation
        organized_configs = {
            "capital": {
                "title": "Capital Settings",
                "configs": {
                    "starting_capital": get_config_value("starting_capital"),
                    "reset_day": get_config_value("reset_day"),
                    "reset_time": get_config_value("reset_time"),
                },
            },
            "leverage": {
                "title": "Leverage Settings",
                "configs": {
                    "equity_mis_leverage": get_config_value("equity_mis_leverage"),
                    "equity_cnc_leverage": get_config_value("equity_cnc_leverage"),
                    "futures_leverage": get_config_value("futures_leverage"),
                    "option_buy_leverage": get_config_value("option_buy_leverage"),
                    "option_sell_leverage": get_config_value("option_sell_leverage"),
                },
            },
            "square_off": {
                "title": "Square-Off Times (IST)",
                "configs": {
                    "nse_bse_square_off_time": get_config_value("nse_bse_square_off_time"),
                    "cds_bcd_square_off_time": get_config_value("cds_bcd_square_off_time"),
                    "mcx_square_off_time": get_config_value("mcx_square_off_time"),
                    "ncdex_square_off_time": get_config_value("ncdex_square_off_time"),
                },
            },
            "intervals": {
                "title": "Update Intervals (seconds)",
                "configs": {
                    "order_check_interval": get_config_value("order_check_interval"),
                    "mtm_update_interval": get_config_value("mtm_update_interval"),
                },
            },
        }

        return jsonify({"status": "success", "configs": organized_configs})
    except Exception as e:
        logger.exception(f"Error getting sandbox configs: {str(e)}\n{traceback.format_exc()}")
        return jsonify(
            {"status": "error", "message": f"Error loading configuration: {str(e)}"}
        ), 500


@sandbox_bp.route("/update", methods=["POST"])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def update_config():
    """Update sandbox configuration values"""
    try:
        data = request.get_json()
        config_key = data.get("config_key")
        config_value = data.get("config_value")

        if not config_key or config_value is None:
            return jsonify(
                {"status": "error", "message": "Missing config_key or config_value"}
            ), 400

        # Validate config value based on key
        validation_error = validate_config(config_key, config_value)
        if validation_error:
            return jsonify({"status": "error", "message": validation_error}), 400

        # Update the configuration
        success = set_config(config_key, config_value)

        if success:
            logger.info(f"Sandbox config updated: {config_key} = {config_value}")

            # If starting_capital was updated, update all user funds immediately
            if config_key == "starting_capital":
                try:
                    from decimal import Decimal

                    from database.sandbox_db import SandboxFunds, db_session

                    new_capital = Decimal(str(config_value))

                    # Update all user funds with new starting capital
                    # This resets their balance to the new capital value
                    funds = SandboxFunds.query.all()
                    for fund in funds:
                        # Calculate what the new available balance should be
                        # New available = new_capital - used_margin + total_pnl
                        fund.total_capital = new_capital
                        fund.available_balance = new_capital - fund.used_margin + fund.total_pnl

                    db_session.commit()
                    logger.info(
                        f"Updated {len(funds)} user funds with new starting capital: ₹{new_capital}"
                    )
                except Exception as e:
                    logger.exception(f"Error updating user funds with new capital: {e}")
                    db_session.rollback()

            # If square-off time was updated, reload the schedule automatically
            if config_key.endswith("square_off_time"):
                try:
                    from services.sandbox_service import sandbox_reload_squareoff_schedule

                    reload_success, reload_response, reload_status = (
                        sandbox_reload_squareoff_schedule()
                    )
                    if reload_success:
                        logger.info(f"Square-off schedule reloaded after {config_key} update")
                    else:
                        logger.warning(
                            f"Failed to reload square-off schedule: {reload_response.get('message')}"
                        )
                except Exception as e:
                    logger.exception(f"Error auto-reloading square-off schedule: {e}")

            # If reset day or reset time was updated, reload the schedule automatically
            if config_key in ["reset_day", "reset_time"]:
                try:
                    from services.sandbox_service import sandbox_reload_squareoff_schedule

                    reload_success, reload_response, reload_status = (
                        sandbox_reload_squareoff_schedule()
                    )
                    if reload_success:
                        logger.info(f"Schedule reloaded after {config_key} update")
                    else:
                        logger.warning(
                            f"Failed to reload schedule: {reload_response.get('message')}"
                        )
                except Exception as e:
                    logger.exception(f"Error auto-reloading schedule: {e}")

            return jsonify(
                {"status": "success", "message": f"Configuration {config_key} updated successfully"}
            )
        else:
            return jsonify({"status": "error", "message": "Failed to update configuration"}), 500

    except Exception as e:
        logger.exception(f"Error updating sandbox config: {str(e)}\n{traceback.format_exc()}")
        return jsonify(
            {"status": "error", "message": f"Error updating configuration: {str(e)}"}
        ), 500


@sandbox_bp.route("/reset", methods=["POST"])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def reset_config():
    """Reset sandbox configuration to defaults and clear all sandbox data"""
    try:
        user_id = session.get("user")

        # Default configurations
        default_configs = {
            "starting_capital": "10000000.00",
            "reset_day": "Never",
            "reset_time": "00:00",
            "order_check_interval": "5",
            "mtm_update_interval": "5",
            "nse_bse_square_off_time": "15:15",
            "cds_bcd_square_off_time": "16:45",
            "mcx_square_off_time": "23:30",
            "ncdex_square_off_time": "17:00",
            "equity_mis_leverage": "5",
            "equity_cnc_leverage": "1",
            "futures_leverage": "10",
            "option_buy_leverage": "1",
            "option_sell_leverage": "1",
        }

        # Reset all configurations
        for key, value in default_configs.items():
            set_config(key, value)

        # Clear all sandbox data for the current user
        try:
            # Delete all orders
            deleted_orders = SandboxOrders.query.filter_by(user_id=user_id).delete()
            logger.info(f"Deleted {deleted_orders} sandbox orders for user {user_id}")

            # Delete all trades
            deleted_trades = SandboxTrades.query.filter_by(user_id=user_id).delete()
            logger.info(f"Deleted {deleted_trades} sandbox trades for user {user_id}")

            # Delete all positions
            deleted_positions = SandboxPositions.query.filter_by(user_id=user_id).delete()
            logger.info(f"Deleted {deleted_positions} sandbox positions for user {user_id}")

            # Delete all holdings
            deleted_holdings = SandboxHoldings.query.filter_by(user_id=user_id).delete()
            logger.info(f"Deleted {deleted_holdings} sandbox holdings for user {user_id}")

            # Delete all daily P&L history
            from database.sandbox_db import SandboxDailyPnL

            deleted_daily_pnl = SandboxDailyPnL.query.filter_by(user_id=user_id).delete()
            logger.info(f"Deleted {deleted_daily_pnl} daily P&L records for user {user_id}")

            # Reset funds to starting capital
            from datetime import datetime
            from decimal import Decimal

            import pytz

            fund = SandboxFunds.query.filter_by(user_id=user_id).first()
            starting_capital = Decimal(default_configs["starting_capital"])

            if fund:
                # Reset existing fund
                fund.total_capital = starting_capital
                fund.available_balance = starting_capital
                fund.used_margin = Decimal("0.00")
                fund.unrealized_pnl = Decimal("0.00")
                fund.realized_pnl = Decimal("0.00")
                fund.today_realized_pnl = Decimal("0.00")
                fund.total_pnl = Decimal("0.00")
                fund.last_reset_date = datetime.now(pytz.timezone("Asia/Kolkata"))
                fund.reset_count = (fund.reset_count or 0) + 1
                logger.info(f"Reset sandbox funds for user {user_id}")
            else:
                # Create new fund record
                fund = SandboxFunds(
                    user_id=user_id,
                    total_capital=starting_capital,
                    available_balance=starting_capital,
                    used_margin=Decimal("0.00"),
                    unrealized_pnl=Decimal("0.00"),
                    realized_pnl=Decimal("0.00"),
                    today_realized_pnl=Decimal("0.00"),
                    total_pnl=Decimal("0.00"),
                    last_reset_date=datetime.now(pytz.timezone("Asia/Kolkata")),
                    reset_count=1,
                )
                db_session.add(fund)
                logger.info(f"Created new sandbox funds for user {user_id}")

            db_session.commit()
            logger.info(f"Successfully reset all sandbox data for user {user_id}")

        except Exception as e:
            db_session.rollback()
            logger.exception(f"Error clearing sandbox data: {str(e)}\n{traceback.format_exc()}")
            raise

        logger.info("Sandbox configuration and data reset to defaults")
        return jsonify(
            {
                "status": "success",
                "message": "Configuration and data reset to defaults successfully. All orders, trades, positions, holdings, and P&L history have been cleared.",
            }
        )

    except Exception as e:
        logger.exception(f"Error resetting sandbox config: {str(e)}\n{traceback.format_exc()}")
        return jsonify(
            {"status": "error", "message": f"Error resetting configuration: {str(e)}"}
        ), 500


@sandbox_bp.route("/reload-squareoff", methods=["POST"])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def reload_squareoff():
    """Manually reload square-off schedule from config"""
    try:
        from services.sandbox_service import sandbox_reload_squareoff_schedule

        success, response, status_code = sandbox_reload_squareoff_schedule()

        if success:
            return jsonify(response), status_code
        else:
            return jsonify(response), status_code

    except Exception as e:
        logger.exception(f"Error reloading square-off schedule: {str(e)}\n{traceback.format_exc()}")
        return jsonify(
            {"status": "error", "message": f"Error reloading square-off schedule: {str(e)}"}
        ), 500


@sandbox_bp.route("/squareoff-status")
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def squareoff_status():
    """Get current square-off scheduler status"""
    try:
        from services.sandbox_service import sandbox_get_squareoff_status

        success, response, status_code = sandbox_get_squareoff_status()

        if success:
            return jsonify(response), status_code
        else:
            return jsonify(response), status_code

    except Exception as e:
        logger.exception(f"Error getting square-off status: {str(e)}\n{traceback.format_exc()}")
        return jsonify(
            {"status": "error", "message": f"Error getting square-off status: {str(e)}"}
        ), 500


@sandbox_bp.route("/mypnl/api/data")
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def api_my_pnl_data():
    """API endpoint to get P&L data as JSON for React frontend"""
    try:
        from decimal import Decimal

        user_id = session.get("user")

        # Get all positions (both open and closed) for P&L history
        positions = (
            SandboxPositions.query.filter_by(user_id=user_id)
            .order_by(SandboxPositions.updated_at.desc())
            .all()
        )

        # Get holdings for P&L
        holdings = (
            SandboxHoldings.query.filter_by(user_id=user_id)
            .order_by(SandboxHoldings.updated_at.desc())
            .all()
        )

        # Get funds for summary
        funds = SandboxFunds.query.filter_by(user_id=user_id).first()

        # Prepare position data
        position_list = []
        positions_unrealized = Decimal("0.00")

        for pos in positions:
            today_realized = Decimal(str(pos.today_realized_pnl or 0))
            all_time_realized = Decimal(str(pos.accumulated_realized_pnl or 0))
            unrealized = Decimal(str(pos.pnl or 0)) if pos.quantity != 0 else Decimal("0.00")

            if pos.quantity != 0:
                positions_unrealized += unrealized

            position_list.append(
                {
                    "symbol": pos.symbol,
                    "exchange": pos.exchange,
                    "product": pos.product,
                    "quantity": pos.quantity,
                    "average_price": float(pos.average_price),
                    "ltp": float(pos.ltp) if pos.ltp else 0.0,
                    "unrealized_pnl": float(unrealized),
                    "today_realized_pnl": float(today_realized),
                    "all_time_realized_pnl": float(all_time_realized),
                    "status": "Open" if pos.quantity != 0 else "Closed",
                    "updated_at": pos.updated_at.strftime("%Y-%m-%d %H:%M:%S")
                    if pos.updated_at
                    else "",
                }
            )

        # Prepare holdings data
        holdings_list = []
        holdings_unrealized = Decimal("0.00")

        for holding in holdings:
            if holding.quantity != 0:
                unrealized = Decimal(str(holding.pnl or 0))
                holdings_unrealized += unrealized

                holdings_list.append(
                    {
                        "symbol": holding.symbol,
                        "exchange": holding.exchange,
                        "product": "CNC",
                        "quantity": holding.quantity,
                        "average_price": float(holding.average_price),
                        "ltp": float(holding.ltp) if holding.ltp else 0.0,
                        "unrealized_pnl": float(unrealized),
                        "pnl_percent": float(holding.pnl_percent or 0),
                        "settlement_date": holding.settlement_date.strftime("%Y-%m-%d")
                        if holding.settlement_date
                        else "",
                    }
                )

        # Get recent trades
        trades = (
            SandboxTrades.query.filter_by(user_id=user_id)
            .order_by(SandboxTrades.trade_timestamp.desc())
            .limit(50)
            .all()
        )

        trade_list = []
        for trade in trades:
            trade_list.append(
                {
                    "tradeid": trade.tradeid,
                    "symbol": trade.symbol,
                    "exchange": trade.exchange,
                    "action": trade.action,
                    "quantity": trade.quantity,
                    "price": float(trade.price),
                    "product": trade.product,
                    "timestamp": trade.trade_timestamp.strftime("%Y-%m-%d %H:%M:%S")
                    if trade.trade_timestamp
                    else "",
                }
            )

        # Get date-wise P&L history (last 30 days)
        from database.sandbox_db import SandboxDailyPnL

        daily_pnl_records = (
            SandboxDailyPnL.query.filter_by(user_id=user_id)
            .order_by(SandboxDailyPnL.date.desc())
            .limit(30)
            .all()
        )

        daily_pnl_list = []
        for record in daily_pnl_records:
            daily_pnl_list.append(
                {
                    "date": record.date.strftime("%Y-%m-%d"),
                    "realized_pnl": float(record.realized_pnl or 0),
                    "positions_unrealized": float(record.positions_unrealized_pnl or 0),
                    "holdings_unrealized": float(record.holdings_unrealized_pnl or 0),
                    "total_unrealized": float(
                        (record.positions_unrealized_pnl or 0)
                        + (record.holdings_unrealized_pnl or 0)
                    ),
                    "total_mtm": float(record.total_mtm or 0),
                    "portfolio_value": float(record.portfolio_value or 0),
                }
            )

        # Calculate today's live P&L (not yet snapshotted)
        today_realized = Decimal(str(funds.today_realized_pnl or 0)) if funds else Decimal("0.00")
        total_unrealized = positions_unrealized + holdings_unrealized
        today_total_mtm = today_realized + total_unrealized

        # Summary data
        summary = {
            "today_realized_pnl": float(today_realized),
            "all_time_realized_pnl": float(funds.realized_pnl or 0) if funds else 0.0,
            "positions_unrealized_pnl": float(positions_unrealized),
            "holdings_unrealized_pnl": float(holdings_unrealized),
            "total_unrealized_pnl": float(total_unrealized),
            "today_total_mtm": float(today_total_mtm),
            "total_pnl": float(funds.total_pnl or 0) if funds else 0.0,
            "available_balance": float(funds.available_balance or 0) if funds else 0.0,
            "total_capital": float(funds.total_capital or 0) if funds else 0.0,
        }

        return jsonify(
            {
                "status": "success",
                "data": {
                    "summary": summary,
                    "daily_pnl": daily_pnl_list,
                    "positions": position_list,
                    "holdings": holdings_list,
                    "trades": trade_list,
                },
            }
        )

    except Exception as e:
        logger.exception(f"Error getting P&L data: {str(e)}\n{traceback.format_exc()}")
        return jsonify({"status": "error", "message": f"Error loading P&L data: {str(e)}"}), 500


@sandbox_bp.route("/mypnl")
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def my_pnl():
    """Render the historical P&L page"""
    try:
        from datetime import date, datetime
        from decimal import Decimal

        import pytz

        user_id = session.get("user")
        ist = pytz.timezone("Asia/Kolkata")

        # Get all positions (both open and closed) for P&L history
        positions = (
            SandboxPositions.query.filter_by(user_id=user_id)
            .order_by(SandboxPositions.updated_at.desc())
            .all()
        )

        # Get holdings for P&L
        holdings = (
            SandboxHoldings.query.filter_by(user_id=user_id)
            .order_by(SandboxHoldings.updated_at.desc())
            .all()
        )

        # Get funds for summary
        funds = SandboxFunds.query.filter_by(user_id=user_id).first()

        # Prepare position data
        position_list = []
        positions_unrealized = Decimal("0.00")

        for pos in positions:
            today_realized = Decimal(str(pos.today_realized_pnl or 0))
            all_time_realized = Decimal(str(pos.accumulated_realized_pnl or 0))
            unrealized = Decimal(str(pos.pnl or 0)) if pos.quantity != 0 else Decimal("0.00")

            if pos.quantity != 0:
                positions_unrealized += unrealized

            position_list.append(
                {
                    "symbol": pos.symbol,
                    "exchange": pos.exchange,
                    "product": pos.product,
                    "quantity": pos.quantity,
                    "average_price": float(pos.average_price),
                    "ltp": float(pos.ltp) if pos.ltp else 0.0,
                    "unrealized_pnl": float(unrealized),
                    "today_realized_pnl": float(today_realized),
                    "all_time_realized_pnl": float(all_time_realized),
                    "status": "Open" if pos.quantity != 0 else "Closed",
                    "updated_at": pos.updated_at.strftime("%Y-%m-%d %H:%M:%S")
                    if pos.updated_at
                    else "",
                }
            )

        # Prepare holdings data
        holdings_list = []
        holdings_unrealized = Decimal("0.00")

        for holding in holdings:
            if holding.quantity != 0:
                unrealized = Decimal(str(holding.pnl or 0))
                holdings_unrealized += unrealized

                holdings_list.append(
                    {
                        "symbol": holding.symbol,
                        "exchange": holding.exchange,
                        "product": "CNC",
                        "quantity": holding.quantity,
                        "average_price": float(holding.average_price),
                        "ltp": float(holding.ltp) if holding.ltp else 0.0,
                        "unrealized_pnl": float(unrealized),
                        "pnl_percent": float(holding.pnl_percent or 0),
                        "settlement_date": holding.settlement_date.strftime("%Y-%m-%d")
                        if holding.settlement_date
                        else "",
                    }
                )

        # Get recent trades
        trades = (
            SandboxTrades.query.filter_by(user_id=user_id)
            .order_by(SandboxTrades.trade_timestamp.desc())
            .limit(50)
            .all()
        )

        trade_list = []
        for trade in trades:
            trade_list.append(
                {
                    "tradeid": trade.tradeid,
                    "symbol": trade.symbol,
                    "exchange": trade.exchange,
                    "action": trade.action,
                    "quantity": trade.quantity,
                    "price": float(trade.price),
                    "product": trade.product,
                    "timestamp": trade.trade_timestamp.strftime("%Y-%m-%d %H:%M:%S")
                    if trade.trade_timestamp
                    else "",
                }
            )

        # Get date-wise P&L history (last 30 days)
        from database.sandbox_db import SandboxDailyPnL

        daily_pnl_records = (
            SandboxDailyPnL.query.filter_by(user_id=user_id)
            .order_by(SandboxDailyPnL.date.desc())
            .limit(30)
            .all()
        )

        daily_pnl_list = []
        for record in daily_pnl_records:
            daily_pnl_list.append(
                {
                    "date": record.date.strftime("%Y-%m-%d"),
                    "realized_pnl": float(record.realized_pnl or 0),
                    "positions_unrealized": float(record.positions_unrealized_pnl or 0),
                    "holdings_unrealized": float(record.holdings_unrealized_pnl or 0),
                    "total_unrealized": float(
                        (record.positions_unrealized_pnl or 0)
                        + (record.holdings_unrealized_pnl or 0)
                    ),
                    "total_mtm": float(record.total_mtm or 0),
                    "portfolio_value": float(record.portfolio_value or 0),
                }
            )

        # Calculate today's live P&L (not yet snapshotted)
        today_realized = Decimal(str(funds.today_realized_pnl or 0)) if funds else Decimal("0.00")
        total_unrealized = positions_unrealized + holdings_unrealized
        today_total_mtm = today_realized + total_unrealized

        # Summary data
        summary = {
            "today_realized_pnl": float(today_realized),
            "all_time_realized_pnl": float(funds.realized_pnl or 0) if funds else 0.0,
            "positions_unrealized_pnl": float(positions_unrealized),
            "holdings_unrealized_pnl": float(holdings_unrealized),
            "total_unrealized_pnl": float(total_unrealized),
            "today_total_mtm": float(today_total_mtm),
            "total_pnl": float(funds.total_pnl or 0) if funds else 0.0,
            "available_balance": float(funds.available_balance or 0) if funds else 0.0,
            "total_capital": float(funds.total_capital or 0) if funds else 0.0,
        }

        return render_template(
            "sandbox_mypnl.html",
            positions=position_list,
            holdings=holdings_list,
            trades=trade_list,
            daily_pnl=daily_pnl_list,
            summary=summary,
        )

    except Exception as e:
        logger.exception(f"Error rendering my P&L page: {str(e)}\n{traceback.format_exc()}")
        flash("Error loading P&L data", "error")
        return redirect(url_for("sandbox_bp.sandbox_config"))


def validate_config(config_key, config_value):
    """Validate configuration values"""
    try:
        # Validate numeric values
        if config_key in [
            "starting_capital",
            "equity_mis_leverage",
            "equity_cnc_leverage",
            "futures_leverage",
            "option_buy_leverage",
            "option_sell_leverage",
            "order_check_interval",
            "mtm_update_interval",
        ]:
            try:
                value = float(config_value)
                if value < 0:
                    return f"{config_key} must be a positive number"

                # Additional validations
                if config_key == "starting_capital":
                    valid_capitals = [100000, 500000, 1000000, 2500000, 5000000, 10000000]
                    if value not in valid_capitals:
                        return (
                            "Starting capital must be one of: ₹1L, ₹5L, ₹10L, ₹25L, ₹50L, or ₹1Cr"
                        )

                if config_key.endswith("_leverage"):
                    if value < 1:
                        return "Leverage must be at least 1x"
                    if value > 50:
                        return "Leverage cannot exceed 50x"

                # Interval validations
                if config_key == "order_check_interval":
                    if value < 1 or value > 30:
                        return "Order check interval must be between 1-30 seconds"

                if config_key == "mtm_update_interval":
                    if value < 0 or value > 60:
                        return "MTM update interval must be between 0-60 seconds (0 = manual only)"

            except ValueError:
                return f"{config_key} must be a valid number"

        # Validate time format (HH:MM)
        if config_key.endswith("_time"):
            if ":" not in config_value:
                return "Time must be in HH:MM format"
            try:
                hours, minutes = config_value.split(":")
                if not (0 <= int(hours) <= 23 and 0 <= int(minutes) <= 59):
                    return "Invalid time format"
            except:
                return "Time must be in HH:MM format"

        # Validate day of week
        if config_key == "reset_day":
            valid_days = [
                "Monday",
                "Tuesday",
                "Wednesday",
                "Thursday",
                "Friday",
                "Saturday",
                "Sunday",
                "Never",
            ]
            if config_value not in valid_days:
                return f"Reset day must be one of: {', '.join(valid_days)}"

        return None  # No validation error

    except Exception as e:
        logger.exception(f"Error validating config: {str(e)}")
        return f"Validation error: {str(e)}"


def sanitize_csv_value(value):
    """
    Sanitize a value for CSV export to prevent CSV injection attacks.

    CSV injection occurs when cells starting with =, +, @, \t, or \r
    are interpreted as formulas by spreadsheet applications like Excel.
    We prefix these with a single quote to force text interpretation.

    Note: We do NOT sanitize '-' as it's commonly used for negative numbers
    in financial/P&L data.
    """
    if value is None:
        return ""

    str_value = str(value)

    # Check if the value starts with potentially dangerous characters
    # Note: '-' is excluded because negative numbers are common in financial data
    if str_value and str_value[0] in ('=', '+', '@', '\t', '\r'):
        return "'" + str_value

    return str_value


def generate_daily_pnl_csv(daily_pnl_records):
    """Generate CSV from daily P&L records"""
    output = io.StringIO()
    writer = csv.writer(output)

    # Write headers
    headers = [
        "Date",
        "Realized P&L",
        "Positions Unrealized",
        "Holdings Unrealized",
        "Total Unrealized",
        "Total MTM",
        "Portfolio Value",
    ]
    writer.writerow(headers)

    # Write data rows
    for record in daily_pnl_records:
        row = [
            sanitize_csv_value(record.date.strftime("%Y-%m-%d") if record.date else ""),
            float(record.realized_pnl or 0),
            float(record.positions_unrealized_pnl or 0),
            float(record.holdings_unrealized_pnl or 0),
            float((record.positions_unrealized_pnl or 0) + (record.holdings_unrealized_pnl or 0)),
            float(record.total_mtm or 0),
            float(record.portfolio_value or 0),
        ]
        writer.writerow(row)

    return output.getvalue()


def generate_positions_csv(positions):
    """Generate CSV from positions data"""
    output = io.StringIO()
    writer = csv.writer(output)

    # Write headers
    headers = [
        "Symbol",
        "Exchange",
        "Product",
        "Quantity",
        "Average Price",
        "LTP",
        "Unrealized P&L",
        "Today Realized P&L",
        "All-Time Realized P&L",
        "Margin Blocked",
        "Status",
        "Last Updated",
    ]
    writer.writerow(headers)

    # Write data rows
    for pos in positions:
        unrealized = float(pos.pnl or 0) if pos.quantity != 0 else 0.0
        row = [
            sanitize_csv_value(pos.symbol),
            sanitize_csv_value(pos.exchange),
            sanitize_csv_value(pos.product),
            pos.quantity,
            float(pos.average_price),
            float(pos.ltp) if pos.ltp else 0.0,
            unrealized,
            float(pos.today_realized_pnl or 0),
            float(pos.accumulated_realized_pnl or 0),
            float(pos.margin_blocked or 0),
            "Open" if pos.quantity != 0 else "Closed",
            pos.updated_at.strftime("%Y-%m-%d %H:%M:%S") if pos.updated_at else "",
        ]
        writer.writerow(row)

    return output.getvalue()


def generate_holdings_csv(holdings):
    """Generate CSV from holdings data"""
    output = io.StringIO()
    writer = csv.writer(output)

    # Write headers
    headers = [
        "Symbol",
        "Exchange",
        "Quantity",
        "Average Price",
        "LTP",
        "Unrealized P&L",
        "P&L %",
        "Settlement Date",
    ]
    writer.writerow(headers)

    # Write data rows
    for holding in holdings:
        row = [
            sanitize_csv_value(holding.symbol),
            sanitize_csv_value(holding.exchange),
            holding.quantity,
            float(holding.average_price),
            float(holding.ltp) if holding.ltp else 0.0,
            float(holding.pnl or 0),
            float(holding.pnl_percent or 0),
            holding.settlement_date.strftime("%Y-%m-%d") if holding.settlement_date else "",
        ]
        writer.writerow(row)

    return output.getvalue()


def generate_trades_csv(trades):
    """Generate CSV from trades data"""
    output = io.StringIO()
    writer = csv.writer(output)

    # Write headers
    headers = [
        "Trade ID",
        "Order ID",
        "Symbol",
        "Exchange",
        "Action",
        "Quantity",
        "Price",
        "Product",
        "Strategy",
        "Timestamp",
    ]
    writer.writerow(headers)

    # Write data rows
    for trade in trades:
        row = [
            sanitize_csv_value(trade.tradeid),
            sanitize_csv_value(trade.orderid),
            sanitize_csv_value(trade.symbol),
            sanitize_csv_value(trade.exchange),
            sanitize_csv_value(trade.action),
            trade.quantity,
            float(trade.price),
            sanitize_csv_value(trade.product),
            sanitize_csv_value(trade.strategy or ""),
            trade.trade_timestamp.strftime("%Y-%m-%d %H:%M:%S") if trade.trade_timestamp else "",
        ]
        writer.writerow(row)

    return output.getvalue()


@sandbox_bp.route("/mypnl/export/daily")
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def export_daily_pnl():
    """Export date-wise P&L data as CSV"""
    try:
        from database.sandbox_db import SandboxDailyPnL

        user_id = session.get("user")

        # Get all daily P&L records for the user (no limit for export)
        daily_pnl_records = (
            SandboxDailyPnL.query.filter_by(user_id=user_id)
            .order_by(SandboxDailyPnL.date.desc())
            .all()
        )

        if not daily_pnl_records:
            return jsonify({"status": "error", "message": "No daily P&L data to export"}), 404

        csv_data = generate_daily_pnl_csv(daily_pnl_records)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        response = Response(csv_data, mimetype="text/csv")
        response.headers["Content-Disposition"] = f'attachment; filename=sandbox_daily_pnl_{timestamp}.csv'
        return response

    except Exception as e:
        logger.exception(f"Error exporting daily P&L: {str(e)}\n{traceback.format_exc()}")
        return jsonify({"status": "error", "message": f"Error exporting data: {str(e)}"}), 500


@sandbox_bp.route("/mypnl/export/positions")
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def export_positions():
    """Export positions data as CSV"""
    try:
        user_id = session.get("user")

        # Get all positions for the user
        positions = (
            SandboxPositions.query.filter_by(user_id=user_id)
            .order_by(SandboxPositions.updated_at.desc())
            .all()
        )

        if not positions:
            return jsonify({"status": "error", "message": "No positions data to export"}), 404

        csv_data = generate_positions_csv(positions)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        response = Response(csv_data, mimetype="text/csv")
        response.headers["Content-Disposition"] = f'attachment; filename=sandbox_positions_{timestamp}.csv'
        return response

    except Exception as e:
        logger.exception(f"Error exporting positions: {str(e)}\n{traceback.format_exc()}")
        return jsonify({"status": "error", "message": f"Error exporting data: {str(e)}"}), 500


@sandbox_bp.route("/mypnl/export/holdings")
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def export_holdings():
    """Export holdings data as CSV"""
    try:
        user_id = session.get("user")

        # Get all holdings for the user
        holdings = (
            SandboxHoldings.query.filter_by(user_id=user_id)
            .order_by(SandboxHoldings.updated_at.desc())
            .all()
        )

        if not holdings:
            return jsonify({"status": "error", "message": "No holdings data to export"}), 404

        csv_data = generate_holdings_csv(holdings)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        response = Response(csv_data, mimetype="text/csv")
        response.headers["Content-Disposition"] = f'attachment; filename=sandbox_holdings_{timestamp}.csv'
        return response

    except Exception as e:
        logger.exception(f"Error exporting holdings: {str(e)}\n{traceback.format_exc()}")
        return jsonify({"status": "error", "message": f"Error exporting data: {str(e)}"}), 500


@sandbox_bp.route("/mypnl/export/trades")
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def export_trades():
    """Export all trades data as CSV (no limit)"""
    try:
        user_id = session.get("user")

        # Get ALL trades for the user (no limit for export)
        trades = (
            SandboxTrades.query.filter_by(user_id=user_id)
            .order_by(SandboxTrades.trade_timestamp.desc())
            .all()
        )

        if not trades:
            return jsonify({"status": "error", "message": "No trades data to export"}), 404

        csv_data = generate_trades_csv(trades)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        response = Response(csv_data, mimetype="text/csv")
        response.headers["Content-Disposition"] = f'attachment; filename=sandbox_trades_{timestamp}.csv'
        return response

    except Exception as e:
        logger.exception(f"Error exporting trades: {str(e)}\n{traceback.format_exc()}")
        return jsonify({"status": "error", "message": f"Error exporting data: {str(e)}"}), 500
