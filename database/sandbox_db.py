# database/sandbox_db.py

import os
from sqlalchemy import create_engine, UniqueConstraint, Index, CheckConstraint
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, DECIMAL, Date
from sqlalchemy.sql import func
from datetime import datetime
from utils.logging import get_logger
from dotenv import load_dotenv

# Initialize logger
logger = get_logger(__name__)

# Load environment variables
load_dotenv()

# Sandbox database URL - separate database for isolation
# Get from environment variable or use default path in /db directory
SANDBOX_DATABASE_URL = os.getenv('SANDBOX_DATABASE_URL', 'sqlite:///db/sandbox.db')

engine = create_engine(
    SANDBOX_DATABASE_URL,
    pool_size=20,
    max_overflow=40,
    pool_timeout=10
)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


class SandboxOrders(Base):
    """Sandbox orders table - all virtual orders"""
    __tablename__ = 'sandbox_orders'

    id = Column(Integer, primary_key=True, autoincrement=True)
    orderid = Column(String(50), unique=True, nullable=False, index=True)
    user_id = Column(String(50), nullable=False, index=True)
    strategy = Column(String(100), nullable=True)
    symbol = Column(String(50), nullable=False, index=True)
    exchange = Column(String(20), nullable=False, index=True)
    action = Column(String(10), nullable=False)  # BUY or SELL
    quantity = Column(Integer, nullable=False)
    price = Column(DECIMAL(10, 2), nullable=True)  # Null for market orders
    trigger_price = Column(DECIMAL(10, 2), nullable=True)  # For SL and SL-M orders
    price_type = Column(String(20), nullable=False)  # MARKET, LIMIT, SL, SL-M
    product = Column(String(20), nullable=False)  # CNC, NRML, MIS
    order_status = Column(String(20), nullable=False, default='open', index=True)  # open, complete, cancelled, rejected
    average_price = Column(DECIMAL(10, 2), nullable=True)  # Filled price
    filled_quantity = Column(Integer, default=0)  # Always 0 or quantity (no partial fills)
    pending_quantity = Column(Integer, nullable=False)  # Remaining quantity
    rejection_reason = Column(Text, nullable=True)
    margin_blocked = Column(DECIMAL(10, 2), nullable=True, default=0.00)  # Margin blocked at order placement
    order_timestamp = Column(DateTime, nullable=False, default=func.now())
    update_timestamp = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index('idx_user_status', 'user_id', 'order_status'),
        Index('idx_symbol_exchange', 'symbol', 'exchange'),
        CheckConstraint("order_status IN ('open', 'complete', 'cancelled', 'rejected')", name='check_order_status'),
        CheckConstraint("action IN ('BUY', 'SELL')", name='check_action'),
        CheckConstraint("price_type IN ('MARKET', 'LIMIT', 'SL', 'SL-M')", name='check_price_type'),
        CheckConstraint("product IN ('CNC', 'NRML', 'MIS')", name='check_product'),
    )


class SandboxTrades(Base):
    """Sandbox trades table - executed trades"""
    __tablename__ = 'sandbox_trades'

    id = Column(Integer, primary_key=True, autoincrement=True)
    tradeid = Column(String(50), unique=True, nullable=False, index=True)
    orderid = Column(String(50), nullable=False, index=True)
    user_id = Column(String(50), nullable=False, index=True)
    symbol = Column(String(50), nullable=False, index=True)
    exchange = Column(String(20), nullable=False, index=True)
    action = Column(String(10), nullable=False)  # BUY or SELL
    quantity = Column(Integer, nullable=False)
    price = Column(DECIMAL(10, 2), nullable=False)  # Execution price
    product = Column(String(20), nullable=False)  # CNC, NRML, MIS
    strategy = Column(String(100), nullable=True)
    trade_timestamp = Column(DateTime, nullable=False, default=func.now())

    __table_args__ = (
        Index('idx_user_symbol', 'user_id', 'symbol'),
        Index('idx_orderid', 'orderid'),
    )


class SandboxPositions(Base):
    """Sandbox positions table - open positions"""
    __tablename__ = 'sandbox_positions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(50), nullable=False, index=True)
    symbol = Column(String(50), nullable=False, index=True)
    exchange = Column(String(20), nullable=False, index=True)
    product = Column(String(20), nullable=False)  # CNC, NRML, MIS
    quantity = Column(Integer, nullable=False)  # Net quantity (can be negative for short)
    average_price = Column(DECIMAL(10, 2), nullable=False)  # Average entry price

    # MTM tracking
    ltp = Column(DECIMAL(10, 2), nullable=True)  # Last traded price
    pnl = Column(DECIMAL(10, 2), default=0.00)  # Current P&L (unrealized for open, realized for closed)
    pnl_percent = Column(DECIMAL(10, 4), default=0.00)  # P&L percentage
    accumulated_realized_pnl = Column(DECIMAL(10, 2), default=0.00)  # Accumulated realized P&L for the day

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('user_id', 'symbol', 'exchange', 'product', name='unique_position'),
        Index('idx_user_product', 'user_id', 'product'),
    )


class SandboxHoldings(Base):
    """Sandbox holdings table - T+1 settled CNC positions"""
    __tablename__ = 'sandbox_holdings'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(50), nullable=False, index=True)
    symbol = Column(String(50), nullable=False, index=True)
    exchange = Column(String(20), nullable=False, index=True)
    quantity = Column(Integer, nullable=False)  # Total holdings quantity
    average_price = Column(DECIMAL(10, 2), nullable=False)  # Average buy price

    # MTM tracking
    ltp = Column(DECIMAL(10, 2), nullable=True)  # Last traded price
    pnl = Column(DECIMAL(10, 2), default=0.00)  # Unrealized P&L
    pnl_percent = Column(DECIMAL(10, 4), default=0.00)  # P&L percentage

    # Settlement tracking
    settlement_date = Column(Date, nullable=False)  # Date when position was settled to holdings

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('user_id', 'symbol', 'exchange', name='unique_holding'),
    )


class SandboxFunds(Base):
    """Sandbox funds table - simulated capital and margin tracking"""
    __tablename__ = 'sandbox_funds'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(50), unique=True, nullable=False, index=True)

    # Fund balances
    total_capital = Column(DECIMAL(15, 2), default=10000000.00)  # ₹1 Crore starting capital
    available_balance = Column(DECIMAL(15, 2), default=10000000.00)  # Available for trading
    used_margin = Column(DECIMAL(15, 2), default=0.00)  # Margin blocked in positions

    # P&L tracking
    realized_pnl = Column(DECIMAL(15, 2), default=0.00)  # Realized profit/loss from closed positions
    unrealized_pnl = Column(DECIMAL(15, 2), default=0.00)  # Unrealized P&L from open positions
    total_pnl = Column(DECIMAL(15, 2), default=0.00)  # Total P&L (realized + unrealized)

    # Reset tracking
    last_reset_date = Column(DateTime, nullable=False, default=func.now())
    reset_count = Column(Integer, default=0)  # Number of times reset has occurred

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())


class SandboxConfig(Base):
    """Sandbox configuration table - all configurable settings"""
    __tablename__ = 'sandbox_config'

    id = Column(Integer, primary_key=True, autoincrement=True)
    config_key = Column(String(100), unique=True, nullable=False, index=True)
    config_value = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())


def init_db():
    """Initialize sandbox database and tables"""
    logger.info("Initializing Sandbox DB")
    Base.metadata.create_all(bind=engine)
    logger.info("Sandbox DB initialized successfully")

    # Initialize default configuration
    init_default_config()


def init_default_config():
    """Initialize default sandbox configuration"""
    from sqlalchemy.exc import IntegrityError

    default_configs = [
        {
            'config_key': 'starting_capital',
            'config_value': '10000000.00',
            'description': 'Starting sandbox capital in INR (₹1 Crore) - Min: ₹1000'
        },
        {
            'config_key': 'reset_day',
            'config_value': 'Sunday',
            'description': 'Day of week for automatic fund reset'
        },
        {
            'config_key': 'reset_time',
            'config_value': '00:00',
            'description': 'Time for automatic fund reset (IST)'
        },
        {
            'config_key': 'order_check_interval',
            'config_value': '5',
            'description': 'Interval in seconds to check pending orders - Range: 1-30 seconds'
        },
        {
            'config_key': 'mtm_update_interval',
            'config_value': '5',
            'description': 'Interval in seconds to update MTM - Range: 0-60 seconds (0 = manual only)'
        },
        {
            'config_key': 'nse_bse_square_off_time',
            'config_value': '15:15',
            'description': 'Square-off time for NSE/BSE MIS positions (IST)'
        },
        {
            'config_key': 'cds_bcd_square_off_time',
            'config_value': '16:45',
            'description': 'Square-off time for CDS/BCD MIS positions (IST)'
        },
        {
            'config_key': 'mcx_square_off_time',
            'config_value': '23:30',
            'description': 'Square-off time for MCX MIS positions (IST)'
        },
        {
            'config_key': 'ncdex_square_off_time',
            'config_value': '17:00',
            'description': 'Square-off time for NCDEX MIS positions (IST)'
        },
        {
            'config_key': 'equity_mis_leverage',
            'config_value': '5',
            'description': 'Leverage multiplier for equity MIS (NSE/BSE) - Range: 1-50x'
        },
        {
            'config_key': 'equity_cnc_leverage',
            'config_value': '1',
            'description': 'Leverage multiplier for equity CNC (NSE/BSE) - Range: 1-50x'
        },
        {
            'config_key': 'futures_leverage',
            'config_value': '10',
            'description': 'Leverage multiplier for all futures (NFO/BFO/CDS/BCD/MCX/NCDEX) - Range: 1-50x'
        },
        {
            'config_key': 'option_buy_leverage',
            'config_value': '1',
            'description': 'Leverage for buying options (full premium) - Range: 1-50x'
        },
        {
            'config_key': 'option_sell_leverage',
            'config_value': '1',
            'description': 'Leverage for selling options (same as buying - full premium) - Range: 1-50x'
        },
        {
            'config_key': 'order_rate_limit',
            'config_value': '10',
            'description': 'Maximum orders per second - Range: 1-100 orders/sec (for future use)'
        },
        {
            'config_key': 'api_rate_limit',
            'config_value': '50',
            'description': 'Maximum API calls per second - Range: 1-1000 calls/sec (for future use)'
        },
        {
            'config_key': 'smart_order_rate_limit',
            'config_value': '2',
            'description': 'Maximum smart orders per second - Range: 1-50 orders/sec (for future use)'
        },
        {
            'config_key': 'smart_order_delay',
            'config_value': '0.5',
            'description': 'Delay between multi-leg smart orders - Range: 0.1-10 seconds (for future use)'
        }
    ]

    for config in default_configs:
        try:
            existing = SandboxConfig.query.filter_by(config_key=config['config_key']).first()
            if not existing:
                config_obj = SandboxConfig(**config)
                db_session.add(config_obj)
                db_session.commit()
                logger.info(f"Added default config: {config['config_key']}")
        except IntegrityError:
            db_session.rollback()
            logger.debug(f"Config already exists: {config['config_key']}")
        except Exception as e:
            db_session.rollback()
            logger.error(f"Error adding config {config['config_key']}: {e}")


def get_config(config_key, default=None):
    """Get configuration value by key"""
    try:
        config = SandboxConfig.query.filter_by(config_key=config_key).first()
        if config:
            return config.config_value
        return default
    except Exception as e:
        logger.error(f"Error fetching config {config_key}: {e}")
        return default


def set_config(config_key, config_value, description=None):
    """Set configuration value"""
    try:
        config = SandboxConfig.query.filter_by(config_key=config_key).first()
        if config:
            config.config_value = str(config_value)
            if description:
                config.description = description
        else:
            config = SandboxConfig(
                config_key=config_key,
                config_value=str(config_value),
                description=description
            )
            db_session.add(config)
        db_session.commit()
        logger.info(f"Updated config: {config_key} = {config_value}")
        return True
    except Exception as e:
        db_session.rollback()
        logger.error(f"Error setting config {config_key}: {e}")
        return False


def get_all_configs():
    """Get all configuration values"""
    try:
        configs = SandboxConfig.query.all()
        return {config.config_key: {
            'value': config.config_value,
            'description': config.description
        } for config in configs}
    except Exception as e:
        logger.error(f"Error fetching all configs: {e}")
        return {}
