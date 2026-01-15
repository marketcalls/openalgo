# Scheduled Alerts - Product Requirements Document

## Overview

A dedicated `/alerts` page where users can create, schedule, and manage price alerts with Telegram notifications and optional order execution.

---

## Table of Contents

1. [Alert Conditions](#1-alert-conditions)
2. [Database Schema & Migrations](#2-database-schema--migrations)
3. [API Endpoints](#3-api-endpoints)
4. [Service Layer](#4-service-layer)
5. [UI Design](#5-ui-design)
6. [Telegram Integration](#6-telegram-integration)
7. [Implementation Guide](#7-implementation-guide)

---

## 1. Alert Conditions

### 1.1 Price-Based Conditions

| Condition | Code | Description | Parameters |
|-----------|------|-------------|------------|
| **Crossing** | `crossing` | Price crosses a level (either direction) | `target_value` |
| **Crossing Up** | `crossing_up` | Price crosses above a level | `target_value` |
| **Crossing Down** | `crossing_down` | Price crosses below a level | `target_value` |
| **Greater Than** | `greater_than` | Price is above a level | `target_value` |
| **Less Than** | `less_than` | Price is below a level | `target_value` |
| **Entering Channel** | `entering_channel` | Price enters a range (was outside, now inside) | `upper_bound`, `lower_bound` |
| **Exiting Channel** | `exiting_channel` | Price exits a range (was inside, now outside) | `upper_bound`, `lower_bound` |
| **Inside Channel** | `inside_channel` | Price is within a range | `upper_bound`, `lower_bound` |
| **Outside Channel** | `outside_channel` | Price is outside a range | `upper_bound`, `lower_bound` |
| **Moving Up** | `moving_up` | Price increases by X points | `value` (points) |
| **Moving Down** | `moving_down` | Price decreases by X points | `value` (points) |
| **Moving Up %** | `moving_up_percent` | Price increases by X% | `percent` |
| **Moving Down %** | `moving_down_percent` | Price decreases by X% | `percent` |

### 1.2 Technical Indicator Conditions

| Condition | Code | Description | Parameters |
|-----------|------|-------------|------------|
| **RSI Crossing** | `rsi_crossing` | RSI crosses a level | `period`, `level` |
| **RSI Crossing Up** | `rsi_crossing_up` | RSI crosses above a level | `period`, `level` |
| **RSI Crossing Down** | `rsi_crossing_down` | RSI crosses below a level | `period`, `level` |
| **RSI Greater Than** | `rsi_greater_than` | RSI is above a level | `period`, `level` |
| **RSI Less Than** | `rsi_less_than` | RSI is below a level | `period`, `level` |
| **RSI Overbought** | `rsi_overbought` | RSI enters overbought zone (>70) | `period` |
| **RSI Oversold** | `rsi_oversold` | RSI enters oversold zone (<30) | `period` |
| **MACD Cross Up** | `macd_cross_up` | MACD crosses above Signal | `fast`, `slow`, `signal` |
| **MACD Cross Down** | `macd_cross_down` | MACD crosses below Signal | `fast`, `slow`, `signal` |
| **MACD Above Zero** | `macd_above_zero` | MACD line crosses above zero | `fast`, `slow`, `signal` |
| **MACD Below Zero** | `macd_below_zero` | MACD line crosses below zero | `fast`, `slow`, `signal` |
| **Price Cross SMA Up** | `price_cross_sma_up` | Price crosses above SMA | `period` |
| **Price Cross SMA Down** | `price_cross_sma_down` | Price crosses below SMA | `period` |
| **Price Cross EMA Up** | `price_cross_ema_up` | Price crosses above EMA | `period` |
| **Price Cross EMA Down** | `price_cross_ema_down` | Price crosses below EMA | `period` |
| **EMA Cross Up** | `ema_cross_up` | Fast EMA crosses above Slow EMA | `fast_period`, `slow_period` |
| **EMA Cross Down** | `ema_cross_down` | Fast EMA crosses below Slow EMA | `fast_period`, `slow_period` |
| **SMA Cross Up** | `sma_cross_up` | Fast SMA crosses above Slow SMA | `fast_period`, `slow_period` |
| **SMA Cross Down** | `sma_cross_down` | Fast SMA crosses below Slow SMA | `fast_period`, `slow_period` |
| **Bollinger Upper Touch** | `bb_upper_touch` | Price touches upper Bollinger Band | `period`, `std_dev` |
| **Bollinger Lower Touch** | `bb_lower_touch` | Price touches lower Bollinger Band | `period`, `std_dev` |
| **Bollinger Breakout Up** | `bb_breakout_up` | Price breaks above upper band | `period`, `std_dev` |
| **Bollinger Breakout Down** | `bb_breakout_down` | Price breaks below lower band | `period`, `std_dev` |
| **Supertrend Buy** | `supertrend_buy` | Supertrend turns bullish | `period`, `multiplier` |
| **Supertrend Sell** | `supertrend_sell` | Supertrend turns bearish | `period`, `multiplier` |
| **Price Cross VWAP Up** | `vwap_cross_up` | Price crosses above VWAP | - |
| **Price Cross VWAP Down** | `vwap_cross_down` | Price crosses below VWAP | - |

### 1.3 Volume-Based Conditions

| Condition | Code | Description | Parameters |
|-----------|------|-------------|------------|
| **Volume Greater Than** | `volume_greater_than` | Volume exceeds threshold | `volume` |
| **Volume Less Than** | `volume_less_than` | Volume below threshold | `volume` |
| **Volume Spike** | `volume_spike` | Volume > X times average | `multiplier`, `period` |
| **OI Change Up** | `oi_change_up` | Open Interest increases by % | `percent` |
| **OI Change Down** | `oi_change_down` | Open Interest decreases by % | `percent` |

### 1.4 Time-Based Conditions

| Condition | Code | Description | Parameters |
|-----------|------|-------------|------------|
| **At Time** | `at_time` | Trigger at specific time | `time` (HH:MM) |
| **Market Open** | `market_open` | Trigger at market open | `delay_minutes` |
| **Market Close** | `market_close` | Trigger before market close | `minutes_before` |
| **Every Interval** | `every_interval` | Trigger every X minutes | `interval_minutes` |
| **Candle Close** | `candle_close` | Trigger at candle close | `timeframe` |

### 1.5 Comparison Targets

The condition can compare against:

| Target | Code | Description |
|--------|------|-------------|
| **Fixed Value** | `value` | A specific price/number |
| **Previous Close** | `prev_close` | Yesterday's closing price |
| **Open Price** | `open` | Today's opening price |
| **Day High** | `high` | Today's high |
| **Day Low** | `low` | Today's low |
| **VWAP** | `vwap` | Volume Weighted Average Price |
| **SMA** | `sma` | Simple Moving Average |
| **EMA** | `ema` | Exponential Moving Average |

---

## 2. Database Schema & Migrations

### 2.1 New Tables

#### `scheduled_alerts` Table

```sql
-- Migration: 001_create_scheduled_alerts.sql
-- Description: Create scheduled_alerts table for price alert management
-- Date: 2025-12-14

CREATE TABLE IF NOT EXISTS scheduled_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- User & Authentication
    user_id VARCHAR(50) NOT NULL,
    api_key VARCHAR(64) NOT NULL,

    -- Alert Identity
    alert_name VARCHAR(100) NOT NULL,
    alert_description TEXT,

    -- Symbol Configuration
    symbol VARCHAR(50) NOT NULL,
    exchange VARCHAR(20) NOT NULL,

    -- Condition Configuration
    condition_type VARCHAR(50) NOT NULL,
    condition_params JSON NOT NULL,
    /*
    Example condition_params:
    Price: {"target_value": 26000}
    Channel: {"upper_bound": 26000, "lower_bound": 25500}
    Percent: {"percent": 2.5}
    RSI: {"period": 14, "level": 30}
    EMA Cross: {"fast_period": 9, "slow_period": 21}
    MACD: {"fast": 12, "slow": 26, "signal": 9}
    Bollinger: {"period": 20, "std_dev": 2}
    Volume: {"multiplier": 2, "period": 20}
    Time: {"time": "09:20"}
    */

    -- Schedule Configuration
    schedule_start_date DATE,
    schedule_end_date DATE,
    schedule_start_time TIME,
    schedule_end_time TIME,
    active_days VARCHAR(30) DEFAULT 'Mon,Tue,Wed,Thu,Fri',
    market_hours_only BOOLEAN DEFAULT TRUE,

    -- Action Configuration
    action_type VARCHAR(30) DEFAULT 'telegram_only',
    /*
    Action types:
    - telegram_only: Send Telegram notification only
    - telegram_order: Send Telegram + Execute order
    - telegram_smart_order: Send Telegram + Execute smart order
    */
    order_config JSON,
    /*
    Example order_config:
    {
        "symbol": "NIFTY19DEC2526000CE",
        "exchange": "NFO",
        "action": "BUY",
        "quantity": 75,
        "product": "MIS",
        "price_type": "MARKET",
        "strategy": "Alert Strategy"
    }
    */

    -- Trigger Behavior
    trigger_mode VARCHAR(20) DEFAULT 'once',
    /*
    Trigger modes:
    - once: Trigger once then disable
    - cooldown: Re-arm after cooldown period
    - continuous: Trigger every time condition is met
    */
    cooldown_minutes INTEGER DEFAULT 5,
    max_triggers INTEGER DEFAULT 1,

    -- State Tracking
    status VARCHAR(20) DEFAULT 'active',
    /*
    Status values:
    - active: Alert is monitoring
    - paused: Alert is paused by user
    - triggered: Alert triggered and disabled (for trigger_mode='once')
    - expired: Alert expired (past end_date)
    - disabled: Alert disabled by system
    */
    trigger_count INTEGER DEFAULT 0,
    last_triggered_at DATETIME,
    last_checked_at DATETIME,
    last_ltp DECIMAL(15, 4),
    previous_ltp DECIMAL(15, 4),
    last_indicator_values JSON,

    -- Timestamps
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME,

    -- Indexes for performance
    CONSTRAINT chk_condition_type CHECK (condition_type IN (
        'crossing', 'crossing_up', 'crossing_down',
        'greater_than', 'less_than',
        'entering_channel', 'exiting_channel', 'inside_channel', 'outside_channel',
        'moving_up', 'moving_down', 'moving_up_percent', 'moving_down_percent',
        'rsi_crossing', 'rsi_crossing_up', 'rsi_crossing_down',
        'rsi_greater_than', 'rsi_less_than', 'rsi_overbought', 'rsi_oversold',
        'macd_cross_up', 'macd_cross_down', 'macd_above_zero', 'macd_below_zero',
        'price_cross_sma_up', 'price_cross_sma_down',
        'price_cross_ema_up', 'price_cross_ema_down',
        'ema_cross_up', 'ema_cross_down', 'sma_cross_up', 'sma_cross_down',
        'bb_upper_touch', 'bb_lower_touch', 'bb_breakout_up', 'bb_breakout_down',
        'supertrend_buy', 'supertrend_sell',
        'vwap_cross_up', 'vwap_cross_down',
        'volume_greater_than', 'volume_less_than', 'volume_spike',
        'oi_change_up', 'oi_change_down',
        'at_time', 'market_open', 'market_close', 'every_interval', 'candle_close'
    )),
    CONSTRAINT chk_status CHECK (status IN ('active', 'paused', 'triggered', 'expired', 'disabled')),
    CONSTRAINT chk_action_type CHECK (action_type IN ('telegram_only', 'telegram_order', 'telegram_smart_order')),
    CONSTRAINT chk_trigger_mode CHECK (trigger_mode IN ('once', 'cooldown', 'continuous'))
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_alerts_user_status ON scheduled_alerts(user_id, status);
CREATE INDEX IF NOT EXISTS idx_alerts_symbol ON scheduled_alerts(symbol, exchange);
CREATE INDEX IF NOT EXISTS idx_alerts_condition ON scheduled_alerts(condition_type);
CREATE INDEX IF NOT EXISTS idx_alerts_active ON scheduled_alerts(status, market_hours_only);
```

#### `alert_triggers` Table (History)

```sql
-- Migration: 002_create_alert_triggers.sql
-- Description: Create alert_triggers table for trigger history
-- Date: 2025-12-14

CREATE TABLE IF NOT EXISTS alert_triggers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id INTEGER NOT NULL,
    user_id VARCHAR(50) NOT NULL,

    -- Trigger Details
    triggered_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    trigger_value DECIMAL(15, 4),
    target_value DECIMAL(15, 4),
    condition_met VARCHAR(200),

    -- Market Data Snapshot
    market_data JSON,
    /*
    Example market_data:
    {
        "ltp": 25985.50,
        "open": 25850.00,
        "high": 26020.00,
        "low": 25820.00,
        "close": 25985.50,
        "volume": 12500000,
        "change_percent": 0.52
    }
    */

    -- Indicator Values (if technical alert)
    indicator_values JSON,
    /*
    Example indicator_values:
    {
        "rsi": 28.5,
        "ema_fast": 54250.50,
        "ema_slow": 54180.25
    }
    */

    -- Telegram Status
    telegram_sent BOOLEAN DEFAULT FALSE,
    telegram_message_id VARCHAR(100),
    telegram_sent_at DATETIME,
    telegram_error TEXT,

    -- Order Status
    order_placed BOOLEAN DEFAULT FALSE,
    order_id VARCHAR(50),
    order_status VARCHAR(20),
    order_response JSON,
    order_error TEXT,

    FOREIGN KEY (alert_id) REFERENCES scheduled_alerts(id) ON DELETE CASCADE
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_triggers_alert ON alert_triggers(alert_id);
CREATE INDEX IF NOT EXISTS idx_triggers_user ON alert_triggers(user_id);
CREATE INDEX IF NOT EXISTS idx_triggers_time ON alert_triggers(triggered_at DESC);
```

### 2.2 Migration Script

```python
# database/migrations/alert_migrations.py

"""
Database migrations for Scheduled Alerts feature
"""

import os
import sqlite3
from datetime import datetime
from utils.logging import get_logger

logger = get_logger(__name__)

# Get database path from environment
DATABASE_PATH = os.getenv('DATABASE_PATH', 'db/openalgo.db')


def get_db_connection():
    """Get database connection"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def run_migrations():
    """Run all pending migrations"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Create migrations tracking table if not exists
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS _migrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                migration_name VARCHAR(100) NOT NULL UNIQUE,
                applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()

        # List of migrations
        migrations = [
            ('001_create_scheduled_alerts', create_scheduled_alerts_table),
            ('002_create_alert_triggers', create_alert_triggers_table),
        ]

        for migration_name, migration_func in migrations:
            # Check if already applied
            cursor.execute(
                'SELECT id FROM _migrations WHERE migration_name = ?',
                (migration_name,)
            )
            if cursor.fetchone() is None:
                logger.info(f"Applying migration: {migration_name}")
                migration_func(cursor)
                cursor.execute(
                    'INSERT INTO _migrations (migration_name) VALUES (?)',
                    (migration_name,)
                )
                conn.commit()
                logger.info(f"Migration applied: {migration_name}")
            else:
                logger.debug(f"Migration already applied: {migration_name}")

        logger.info("All migrations completed successfully")

    except Exception as e:
        conn.rollback()
        logger.error(f"Migration failed: {e}")
        raise
    finally:
        conn.close()


def create_scheduled_alerts_table(cursor):
    """Create scheduled_alerts table"""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS scheduled_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            -- User & Authentication
            user_id VARCHAR(50) NOT NULL,
            api_key VARCHAR(64) NOT NULL,

            -- Alert Identity
            alert_name VARCHAR(100) NOT NULL,
            alert_description TEXT,

            -- Symbol Configuration
            symbol VARCHAR(50) NOT NULL,
            exchange VARCHAR(20) NOT NULL,

            -- Condition Configuration
            condition_type VARCHAR(50) NOT NULL,
            condition_params JSON NOT NULL,

            -- Schedule Configuration
            schedule_start_date DATE,
            schedule_end_date DATE,
            schedule_start_time TIME,
            schedule_end_time TIME,
            active_days VARCHAR(30) DEFAULT 'Mon,Tue,Wed,Thu,Fri',
            market_hours_only BOOLEAN DEFAULT 1,

            -- Action Configuration
            action_type VARCHAR(30) DEFAULT 'telegram_only',
            order_config JSON,

            -- Trigger Behavior
            trigger_mode VARCHAR(20) DEFAULT 'once',
            cooldown_minutes INTEGER DEFAULT 5,
            max_triggers INTEGER DEFAULT 1,

            -- State Tracking
            status VARCHAR(20) DEFAULT 'active',
            trigger_count INTEGER DEFAULT 0,
            last_triggered_at DATETIME,
            last_checked_at DATETIME,
            last_ltp DECIMAL(15, 4),
            previous_ltp DECIMAL(15, 4),
            last_indicator_values JSON,

            -- Timestamps
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME
        )
    ''')

    # Create indexes
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_alerts_user_status ON scheduled_alerts(user_id, status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_alerts_symbol ON scheduled_alerts(symbol, exchange)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_alerts_condition ON scheduled_alerts(condition_type)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_alerts_active ON scheduled_alerts(status, market_hours_only)')


def create_alert_triggers_table(cursor):
    """Create alert_triggers table"""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS alert_triggers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_id INTEGER NOT NULL,
            user_id VARCHAR(50) NOT NULL,

            -- Trigger Details
            triggered_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            trigger_value DECIMAL(15, 4),
            target_value DECIMAL(15, 4),
            condition_met VARCHAR(200),

            -- Market Data Snapshot
            market_data JSON,

            -- Indicator Values
            indicator_values JSON,

            -- Telegram Status
            telegram_sent BOOLEAN DEFAULT 0,
            telegram_message_id VARCHAR(100),
            telegram_sent_at DATETIME,
            telegram_error TEXT,

            -- Order Status
            order_placed BOOLEAN DEFAULT 0,
            order_id VARCHAR(50),
            order_status VARCHAR(20),
            order_response JSON,
            order_error TEXT,

            FOREIGN KEY (alert_id) REFERENCES scheduled_alerts(id) ON DELETE CASCADE
        )
    ''')

    # Create indexes
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_triggers_alert ON alert_triggers(alert_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_triggers_user ON alert_triggers(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_triggers_time ON alert_triggers(triggered_at DESC)')


def rollback_migrations():
    """Rollback all alert migrations (for development only)"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('DROP TABLE IF EXISTS alert_triggers')
        cursor.execute('DROP TABLE IF EXISTS scheduled_alerts')
        cursor.execute("DELETE FROM _migrations WHERE migration_name LIKE '%alert%'")
        conn.commit()
        logger.info("Alert migrations rolled back")
    except Exception as e:
        conn.rollback()
        logger.error(f"Rollback failed: {e}")
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    run_migrations()
```

### 2.3 Database Operations Module

```python
# database/alert_db.py

"""
Database operations for Scheduled Alerts
"""

import json
import sqlite3
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from utils.logging import get_logger

logger = get_logger(__name__)

DATABASE_PATH = 'db/openalgo.db'


def get_db_connection():
    """Get database connection"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def dict_from_row(row):
    """Convert sqlite3.Row to dict"""
    if row is None:
        return None
    d = dict(row)
    # Parse JSON fields
    for field in ['condition_params', 'order_config', 'market_data',
                  'indicator_values', 'order_response', 'last_indicator_values']:
        if field in d and d[field]:
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


# ─────────────────────────────────────────────────────────────────
# CRUD Operations
# ─────────────────────────────────────────────────────────────────

def create_alert(alert_data: Dict[str, Any]) -> int:
    """Create a new scheduled alert"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            INSERT INTO scheduled_alerts (
                user_id, api_key, alert_name, alert_description,
                symbol, exchange, condition_type, condition_params,
                schedule_start_date, schedule_end_date,
                schedule_start_time, schedule_end_time,
                active_days, market_hours_only,
                action_type, order_config,
                trigger_mode, cooldown_minutes, max_triggers,
                status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            alert_data['user_id'],
            alert_data['api_key'],
            alert_data['alert_name'],
            alert_data.get('alert_description'),
            alert_data['symbol'],
            alert_data['exchange'],
            alert_data['condition_type'],
            json.dumps(alert_data['condition_params']),
            alert_data.get('schedule_start_date'),
            alert_data.get('schedule_end_date'),
            alert_data.get('schedule_start_time'),
            alert_data.get('schedule_end_time'),
            alert_data.get('active_days', 'Mon,Tue,Wed,Thu,Fri'),
            alert_data.get('market_hours_only', True),
            alert_data.get('action_type', 'telegram_only'),
            json.dumps(alert_data.get('order_config')) if alert_data.get('order_config') else None,
            alert_data.get('trigger_mode', 'once'),
            alert_data.get('cooldown_minutes', 5),
            alert_data.get('max_triggers', 1),
            'active',
            datetime.now().isoformat()
        ))

        alert_id = cursor.lastrowid
        conn.commit()

        logger.info(f"Created alert {alert_id}: {alert_data['alert_name']}")
        return alert_id

    except Exception as e:
        conn.rollback()
        logger.error(f"Error creating alert: {e}")
        raise
    finally:
        conn.close()


def get_alert(alert_id: int, user_id: str = None) -> Optional[Dict]:
    """Get a single alert by ID"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        if user_id:
            cursor.execute(
                'SELECT * FROM scheduled_alerts WHERE id = ? AND user_id = ?',
                (alert_id, user_id)
            )
        else:
            cursor.execute('SELECT * FROM scheduled_alerts WHERE id = ?', (alert_id,))

        row = cursor.fetchone()
        return dict_from_row(row)

    finally:
        conn.close()


def get_user_alerts(user_id: str, filters: Dict = None) -> List[Dict]:
    """Get all alerts for a user with optional filters"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        query = 'SELECT * FROM scheduled_alerts WHERE user_id = ?'
        params = [user_id]

        if filters:
            if filters.get('status'):
                query += ' AND status = ?'
                params.append(filters['status'])
            if filters.get('symbol'):
                query += ' AND symbol = ?'
                params.append(filters['symbol'])
            if filters.get('exchange'):
                query += ' AND exchange = ?'
                params.append(filters['exchange'])
            if filters.get('condition_type'):
                query += ' AND condition_type = ?'
                params.append(filters['condition_type'])

        query += ' ORDER BY created_at DESC'

        cursor.execute(query, params)
        rows = cursor.fetchall()

        return [dict_from_row(row) for row in rows]

    finally:
        conn.close()


def get_active_alerts() -> List[Dict]:
    """Get all active alerts (for monitoring service)"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            SELECT * FROM scheduled_alerts
            WHERE status = 'active'
            ORDER BY symbol, exchange
        ''')
        rows = cursor.fetchall()
        return [dict_from_row(row) for row in rows]

    finally:
        conn.close()


def update_alert(alert_id: int, updates: Dict[str, Any]) -> bool:
    """Update an alert"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Build update query
        set_clauses = []
        params = []

        for key, value in updates.items():
            if key in ['condition_params', 'order_config', 'last_indicator_values']:
                value = json.dumps(value) if value else None
            set_clauses.append(f'{key} = ?')
            params.append(value)

        set_clauses.append('updated_at = ?')
        params.append(datetime.now().isoformat())
        params.append(alert_id)

        query = f"UPDATE scheduled_alerts SET {', '.join(set_clauses)} WHERE id = ?"
        cursor.execute(query, params)
        conn.commit()

        return cursor.rowcount > 0

    except Exception as e:
        conn.rollback()
        logger.error(f"Error updating alert {alert_id}: {e}")
        raise
    finally:
        conn.close()


def delete_alert(alert_id: int, user_id: str) -> bool:
    """Delete an alert"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            'DELETE FROM scheduled_alerts WHERE id = ? AND user_id = ?',
            (alert_id, user_id)
        )
        conn.commit()
        return cursor.rowcount > 0

    finally:
        conn.close()


def update_alert_status(alert_id: int, status: str) -> bool:
    """Update alert status"""
    return update_alert(alert_id, {'status': status})


def update_alert_after_trigger(alert_id: int, trigger_value: float) -> bool:
    """Update alert state after trigger"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Get current alert
        cursor.execute('SELECT * FROM scheduled_alerts WHERE id = ?', (alert_id,))
        alert = dict_from_row(cursor.fetchone())

        if not alert:
            return False

        new_trigger_count = alert['trigger_count'] + 1
        updates = {
            'trigger_count': new_trigger_count,
            'last_triggered_at': datetime.now().isoformat(),
            'last_ltp': trigger_value
        }

        # Check if should disable
        if alert['trigger_mode'] == 'once':
            updates['status'] = 'triggered'
        elif alert['max_triggers'] > 0 and new_trigger_count >= alert['max_triggers']:
            updates['status'] = 'triggered'

        return update_alert(alert_id, updates)

    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────
# Trigger History Operations
# ─────────────────────────────────────────────────────────────────

def log_trigger(
    alert_id: int,
    user_id: str,
    trigger_value: float,
    target_value: float,
    condition_met: str,
    market_data: Dict = None,
    indicator_values: Dict = None
) -> int:
    """Log a trigger event"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            INSERT INTO alert_triggers (
                alert_id, user_id, triggered_at,
                trigger_value, target_value, condition_met,
                market_data, indicator_values
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            alert_id,
            user_id,
            datetime.now().isoformat(),
            trigger_value,
            target_value,
            condition_met,
            json.dumps(market_data) if market_data else None,
            json.dumps(indicator_values) if indicator_values else None
        ))

        trigger_id = cursor.lastrowid
        conn.commit()

        return trigger_id

    finally:
        conn.close()


def update_trigger_telegram_status(
    trigger_id: int,
    sent: bool,
    message_id: str = None,
    error: str = None
):
    """Update trigger Telegram status"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            UPDATE alert_triggers SET
                telegram_sent = ?,
                telegram_message_id = ?,
                telegram_sent_at = ?,
                telegram_error = ?
            WHERE id = ?
        ''', (
            sent,
            message_id,
            datetime.now().isoformat() if sent else None,
            error,
            trigger_id
        ))
        conn.commit()

    finally:
        conn.close()


def update_trigger_order_status(
    trigger_id: int,
    placed: bool,
    order_id: str = None,
    order_status: str = None,
    order_response: Dict = None,
    error: str = None
):
    """Update trigger order status"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            UPDATE alert_triggers SET
                order_placed = ?,
                order_id = ?,
                order_status = ?,
                order_response = ?,
                order_error = ?
            WHERE id = ?
        ''', (
            placed,
            order_id,
            order_status,
            json.dumps(order_response) if order_response else None,
            error,
            trigger_id
        ))
        conn.commit()

    finally:
        conn.close()


def get_alert_triggers(alert_id: int, limit: int = 50) -> List[Dict]:
    """Get trigger history for an alert"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            SELECT * FROM alert_triggers
            WHERE alert_id = ?
            ORDER BY triggered_at DESC
            LIMIT ?
        ''', (alert_id, limit))

        rows = cursor.fetchall()
        return [dict_from_row(row) for row in rows]

    finally:
        conn.close()


def get_user_trigger_history(user_id: str, limit: int = 100) -> List[Dict]:
    """Get all trigger history for a user"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            SELECT t.*, a.alert_name, a.symbol, a.exchange, a.condition_type
            FROM alert_triggers t
            JOIN scheduled_alerts a ON t.alert_id = a.id
            WHERE t.user_id = ?
            ORDER BY t.triggered_at DESC
            LIMIT ?
        ''', (user_id, limit))

        rows = cursor.fetchall()
        return [dict_from_row(row) for row in rows]

    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────
# Statistics
# ─────────────────────────────────────────────────────────────────

def get_alert_stats(user_id: str) -> Dict:
    """Get alert statistics for a user"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Count by status
        cursor.execute('''
            SELECT status, COUNT(*) as count
            FROM scheduled_alerts
            WHERE user_id = ?
            GROUP BY status
        ''', (user_id,))

        status_counts = {row['status']: row['count'] for row in cursor.fetchall()}

        # Count triggers today
        cursor.execute('''
            SELECT COUNT(*) as count
            FROM alert_triggers
            WHERE user_id = ? AND DATE(triggered_at) = DATE('now')
        ''', (user_id,))

        triggers_today = cursor.fetchone()['count']

        # Count alerts with orders
        cursor.execute('''
            SELECT COUNT(*) as count
            FROM scheduled_alerts
            WHERE user_id = ? AND action_type != 'telegram_only'
        ''', (user_id,))

        with_orders = cursor.fetchone()['count']

        return {
            'active': status_counts.get('active', 0),
            'paused': status_counts.get('paused', 0),
            'triggered': status_counts.get('triggered', 0),
            'total': sum(status_counts.values()),
            'triggers_today': triggers_today,
            'with_orders': with_orders
        }

    finally:
        conn.close()
```

---

## 3. API Endpoints

### 3.1 Blueprint Registration

```python
# In app.py, add:
from blueprints.alerts import alerts_bp
app.register_blueprint(alerts_bp)
```

### 3.2 Alerts Blueprint

```python
# blueprints/alerts.py

from flask import Blueprint, render_template, request, jsonify, session
from flask_login import login_required
from database.auth_db import get_api_key_for_tradingview
from database.alert_db import (
    create_alert, get_alert, get_user_alerts, update_alert,
    delete_alert, update_alert_status, get_alert_triggers,
    get_user_trigger_history, get_alert_stats
)
from services.price_alert_service import price_alert_service
from utils.logging import get_logger

logger = get_logger(__name__)
alerts_bp = Blueprint('alerts', __name__, url_prefix='/alerts')


# ─────────────────────────────────────────────────────────────────
# Web Routes
# ─────────────────────────────────────────────────────────────────

@alerts_bp.route('/')
@login_required
def alerts_page():
    """Render the alerts dashboard page"""
    return render_template('alerts.html')


# ─────────────────────────────────────────────────────────────────
# API Routes - CRUD
# ─────────────────────────────────────────────────────────────────

@alerts_bp.route('/api/list', methods=['GET'])
@login_required
def list_alerts():
    """Get all alerts for current user"""
    try:
        user_id = session.get('user')

        filters = {}
        if request.args.get('status'):
            filters['status'] = request.args.get('status')
        if request.args.get('symbol'):
            filters['symbol'] = request.args.get('symbol')
        if request.args.get('exchange'):
            filters['exchange'] = request.args.get('exchange')
        if request.args.get('condition_type'):
            filters['condition_type'] = request.args.get('condition_type')

        alerts = get_user_alerts(user_id, filters if filters else None)

        # Enrich with current market data
        enriched = []
        for alert in alerts:
            enriched.append(price_alert_service.enrich_alert_with_market_data(alert))

        return jsonify({
            'status': 'success',
            'data': enriched,
            'total': len(enriched)
        })

    except Exception as e:
        logger.exception(f"Error listing alerts: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@alerts_bp.route('/api/create', methods=['POST'])
@login_required
def create_alert_route():
    """Create a new scheduled alert"""
    try:
        user_id = session.get('user')
        api_key = get_api_key_for_tradingview(user_id)

        if not api_key:
            return jsonify({
                'status': 'error',
                'message': 'API key required. Please generate one from API Key page.'
            }), 400

        data = request.json
        data['user_id'] = user_id
        data['api_key'] = api_key

        # Validate required fields
        required = ['alert_name', 'symbol', 'exchange', 'condition_type', 'condition_params']
        missing = [f for f in required if f not in data]
        if missing:
            return jsonify({
                'status': 'error',
                'message': f'Missing required fields: {", ".join(missing)}'
            }), 400

        alert_id = create_alert(data)

        # Add to monitoring service
        alert = get_alert(alert_id)
        price_alert_service.add_alert(alert)

        return jsonify({
            'status': 'success',
            'data': {
                'id': alert_id,
                'message': f'Alert "{data["alert_name"]}" created successfully'
            }
        }), 201

    except Exception as e:
        logger.exception(f"Error creating alert: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@alerts_bp.route('/api/<int:alert_id>', methods=['GET'])
@login_required
def get_alert_route(alert_id):
    """Get alert details"""
    try:
        user_id = session.get('user')
        alert = get_alert(alert_id, user_id)

        if not alert:
            return jsonify({'status': 'error', 'message': 'Alert not found'}), 404

        # Enrich with market data
        alert = price_alert_service.enrich_alert_with_market_data(alert)

        return jsonify({'status': 'success', 'data': alert})

    except Exception as e:
        logger.exception(f"Error getting alert: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@alerts_bp.route('/api/<int:alert_id>', methods=['PUT'])
@login_required
def update_alert_route(alert_id):
    """Update an alert"""
    try:
        user_id = session.get('user')

        # Verify ownership
        existing = get_alert(alert_id, user_id)
        if not existing:
            return jsonify({'status': 'error', 'message': 'Alert not found'}), 404

        data = request.json

        # Don't allow updating certain fields
        protected = ['id', 'user_id', 'api_key', 'created_at', 'trigger_count', 'last_triggered_at']
        for field in protected:
            data.pop(field, None)

        success = update_alert(alert_id, data)

        if success:
            # Update in monitoring service
            alert = get_alert(alert_id)
            price_alert_service.update_alert(alert)

            return jsonify({'status': 'success', 'message': 'Alert updated'})
        else:
            return jsonify({'status': 'error', 'message': 'Update failed'}), 500

    except Exception as e:
        logger.exception(f"Error updating alert: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@alerts_bp.route('/api/<int:alert_id>', methods=['DELETE'])
@login_required
def delete_alert_route(alert_id):
    """Delete an alert"""
    try:
        user_id = session.get('user')

        # Remove from monitoring service first
        price_alert_service.remove_alert(alert_id)

        success = delete_alert(alert_id, user_id)

        if success:
            return jsonify({'status': 'success', 'message': 'Alert deleted'})
        else:
            return jsonify({'status': 'error', 'message': 'Alert not found'}), 404

    except Exception as e:
        logger.exception(f"Error deleting alert: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ─────────────────────────────────────────────────────────────────
# API Routes - Actions
# ─────────────────────────────────────────────────────────────────

@alerts_bp.route('/api/<int:alert_id>/pause', methods=['POST'])
@login_required
def pause_alert_route(alert_id):
    """Pause an alert"""
    try:
        user_id = session.get('user')

        existing = get_alert(alert_id, user_id)
        if not existing:
            return jsonify({'status': 'error', 'message': 'Alert not found'}), 404

        update_alert_status(alert_id, 'paused')
        price_alert_service.pause_alert(alert_id)

        return jsonify({'status': 'success', 'message': 'Alert paused'})

    except Exception as e:
        logger.exception(f"Error pausing alert: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@alerts_bp.route('/api/<int:alert_id>/resume', methods=['POST'])
@login_required
def resume_alert_route(alert_id):
    """Resume a paused alert"""
    try:
        user_id = session.get('user')

        existing = get_alert(alert_id, user_id)
        if not existing:
            return jsonify({'status': 'error', 'message': 'Alert not found'}), 404

        update_alert_status(alert_id, 'active')
        price_alert_service.resume_alert(alert_id)

        return jsonify({'status': 'success', 'message': 'Alert resumed'})

    except Exception as e:
        logger.exception(f"Error resuming alert: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@alerts_bp.route('/api/<int:alert_id>/test', methods=['POST'])
@login_required
def test_alert_route(alert_id):
    """Test an alert (dry run)"""
    try:
        user_id = session.get('user')

        existing = get_alert(alert_id, user_id)
        if not existing:
            return jsonify({'status': 'error', 'message': 'Alert not found'}), 404

        result = price_alert_service.test_alert(existing)

        return jsonify({
            'status': 'success',
            'data': result
        })

    except Exception as e:
        logger.exception(f"Error testing alert: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ─────────────────────────────────────────────────────────────────
# API Routes - History & Stats
# ─────────────────────────────────────────────────────────────────

@alerts_bp.route('/api/<int:alert_id>/history', methods=['GET'])
@login_required
def get_alert_history_route(alert_id):
    """Get trigger history for an alert"""
    try:
        user_id = session.get('user')

        existing = get_alert(alert_id, user_id)
        if not existing:
            return jsonify({'status': 'error', 'message': 'Alert not found'}), 404

        limit = request.args.get('limit', 50, type=int)
        triggers = get_alert_triggers(alert_id, limit)

        return jsonify({
            'status': 'success',
            'data': triggers,
            'total': len(triggers)
        })

    except Exception as e:
        logger.exception(f"Error getting alert history: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@alerts_bp.route('/api/history', methods=['GET'])
@login_required
def get_all_history_route():
    """Get all trigger history for user"""
    try:
        user_id = session.get('user')
        limit = request.args.get('limit', 100, type=int)

        triggers = get_user_trigger_history(user_id, limit)

        return jsonify({
            'status': 'success',
            'data': triggers,
            'total': len(triggers)
        })

    except Exception as e:
        logger.exception(f"Error getting history: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@alerts_bp.route('/api/stats', methods=['GET'])
@login_required
def get_stats_route():
    """Get alert statistics"""
    try:
        user_id = session.get('user')
        stats = get_alert_stats(user_id)

        return jsonify({
            'status': 'success',
            'data': stats
        })

    except Exception as e:
        logger.exception(f"Error getting stats: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ─────────────────────────────────────────────────────────────────
# API Routes - Bulk Operations
# ─────────────────────────────────────────────────────────────────

@alerts_bp.route('/api/bulk/pause', methods=['POST'])
@login_required
def bulk_pause_route():
    """Pause multiple alerts"""
    try:
        user_id = session.get('user')
        alert_ids = request.json.get('alert_ids', [])

        paused = 0
        for alert_id in alert_ids:
            existing = get_alert(alert_id, user_id)
            if existing:
                update_alert_status(alert_id, 'paused')
                price_alert_service.pause_alert(alert_id)
                paused += 1

        return jsonify({
            'status': 'success',
            'message': f'Paused {paused} alerts'
        })

    except Exception as e:
        logger.exception(f"Error bulk pausing: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@alerts_bp.route('/api/bulk/resume', methods=['POST'])
@login_required
def bulk_resume_route():
    """Resume multiple alerts"""
    try:
        user_id = session.get('user')
        alert_ids = request.json.get('alert_ids', [])

        resumed = 0
        for alert_id in alert_ids:
            existing = get_alert(alert_id, user_id)
            if existing and existing['status'] == 'paused':
                update_alert_status(alert_id, 'active')
                price_alert_service.resume_alert(alert_id)
                resumed += 1

        return jsonify({
            'status': 'success',
            'message': f'Resumed {resumed} alerts'
        })

    except Exception as e:
        logger.exception(f"Error bulk resuming: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@alerts_bp.route('/api/bulk/delete', methods=['POST'])
@login_required
def bulk_delete_route():
    """Delete multiple alerts"""
    try:
        user_id = session.get('user')
        alert_ids = request.json.get('alert_ids', [])

        deleted = 0
        for alert_id in alert_ids:
            price_alert_service.remove_alert(alert_id)
            if delete_alert(alert_id, user_id):
                deleted += 1

        return jsonify({
            'status': 'success',
            'message': f'Deleted {deleted} alerts'
        })

    except Exception as e:
        logger.exception(f"Error bulk deleting: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
```

---

## 4. Service Layer

### 4.1 Price Alert Service

```python
# services/price_alert_service.py

"""
Price Alert Monitoring Service
Monitors market data and triggers alerts based on configured conditions.
"""

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, time, date
from concurrent.futures import ThreadPoolExecutor
import threading
import json

from database.alert_db import (
    get_active_alerts, get_alert, update_alert,
    update_alert_after_trigger, log_trigger,
    update_trigger_telegram_status, update_trigger_order_status
)
from services.quotes_service import get_quotes
from services.websocket_service import register_market_data_callback
from services.telegram_alert_service import telegram_alert_service
from services.place_order_service import place_order
from services.place_smart_order_service import place_smart_order
from services.indicator_service import indicator_service
from utils.logging import get_logger

logger = get_logger(__name__)

# Thread pool for alert processing
alert_executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="alert_processor")


class PriceAlertService:
    """Service for monitoring and triggering price alerts"""

    def __init__(self):
        self.active_alerts: Dict[int, Dict] = {}
        self.subscriptions: Dict[str, List[int]] = {}  # symbol:exchange -> [alert_ids]
        self.last_values: Dict[str, Dict] = {}  # symbol:exchange -> {ltp, indicators...}
        self.monitoring = False
        self._lock = threading.Lock()

    # ─────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────

    def start(self):
        """Start the alert monitoring service"""
        if self.monitoring:
            return

        self.monitoring = True

        # Load active alerts
        alerts = get_active_alerts()
        for alert in alerts:
            self.add_alert(alert)

        logger.info(f"Alert service started. Monitoring {len(alerts)} alerts.")

    def stop(self):
        """Stop the alert monitoring service"""
        self.monitoring = False
        self.active_alerts.clear()
        self.subscriptions.clear()
        logger.info("Alert service stopped.")

    # ─────────────────────────────────────────────────────────────────
    # Alert Management
    # ─────────────────────────────────────────────────────────────────

    def add_alert(self, alert: Dict):
        """Add an alert to monitoring"""
        with self._lock:
            alert_id = alert['id']
            self.active_alerts[alert_id] = alert

            key = f"{alert['symbol']}:{alert['exchange']}"
            if key not in self.subscriptions:
                self.subscriptions[key] = []

            if alert_id not in self.subscriptions[key]:
                self.subscriptions[key].append(alert_id)

            logger.debug(f"Added alert {alert_id} to monitoring")

    def remove_alert(self, alert_id: int):
        """Remove an alert from monitoring"""
        with self._lock:
            if alert_id in self.active_alerts:
                alert = self.active_alerts.pop(alert_id)
                key = f"{alert['symbol']}:{alert['exchange']}"

                if key in self.subscriptions and alert_id in self.subscriptions[key]:
                    self.subscriptions[key].remove(alert_id)

                logger.debug(f"Removed alert {alert_id} from monitoring")

    def update_alert(self, alert: Dict):
        """Update an alert in monitoring"""
        self.remove_alert(alert['id'])
        if alert['status'] == 'active':
            self.add_alert(alert)

    def pause_alert(self, alert_id: int):
        """Pause an alert"""
        self.remove_alert(alert_id)

    def resume_alert(self, alert_id: int):
        """Resume a paused alert"""
        alert = get_alert(alert_id)
        if alert:
            self.add_alert(alert)

    # ─────────────────────────────────────────────────────────────────
    # Market Data Processing
    # ─────────────────────────────────────────────────────────────────

    def process_market_data(self, data: Dict[str, Any]):
        """Process incoming market data and check alerts"""
        if not self.monitoring:
            return

        symbol = data.get('symbol')
        exchange = data.get('exchange')
        key = f"{symbol}:{exchange}"

        if key not in self.subscriptions:
            return

        market_data = data.get('data', {})
        ltp = market_data.get('ltp')

        if ltp is None:
            return

        # Get previous values
        prev_data = self.last_values.get(key, {})
        prev_ltp = prev_data.get('ltp', ltp)

        # Process each alert for this symbol
        for alert_id in list(self.subscriptions.get(key, [])):
            alert = self.active_alerts.get(alert_id)
            if alert and self._should_check_alert(alert):
                alert_executor.submit(
                    self._evaluate_alert,
                    alert, market_data, ltp, prev_ltp
                )

        # Update last values
        self.last_values[key] = {
            'ltp': ltp,
            'timestamp': datetime.now()
        }

    def _should_check_alert(self, alert: Dict) -> bool:
        """Check if alert should be evaluated based on schedule"""
        now = datetime.now()

        # Check date range
        if alert.get('schedule_start_date'):
            start_date = datetime.strptime(alert['schedule_start_date'], '%Y-%m-%d').date()
            if now.date() < start_date:
                return False

        if alert.get('schedule_end_date'):
            end_date = datetime.strptime(alert['schedule_end_date'], '%Y-%m-%d').date()
            if now.date() > end_date:
                return False

        # Check market hours
        if alert.get('market_hours_only', True):
            current_time = now.time()
            market_open = time(9, 15)
            market_close = time(15, 30)
            if not (market_open <= current_time <= market_close):
                return False

        # Check time range
        if alert.get('schedule_start_time'):
            start_time = datetime.strptime(alert['schedule_start_time'], '%H:%M').time()
            if now.time() < start_time:
                return False

        if alert.get('schedule_end_time'):
            end_time = datetime.strptime(alert['schedule_end_time'], '%H:%M').time()
            if now.time() > end_time:
                return False

        # Check active days
        active_days = alert.get('active_days', 'Mon,Tue,Wed,Thu,Fri').split(',')
        day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        if day_names[now.weekday()] not in active_days:
            return False

        # Check cooldown
        if alert.get('last_triggered_at'):
            last_triggered = datetime.fromisoformat(alert['last_triggered_at'])
            cooldown = alert.get('cooldown_minutes', 5) * 60
            if (now - last_triggered).total_seconds() < cooldown:
                return False

        return True

    # ─────────────────────────────────────────────────────────────────
    # Condition Evaluation
    # ─────────────────────────────────────────────────────────────────

    def _evaluate_alert(self, alert: Dict, market_data: Dict, ltp: float, prev_ltp: float):
        """Evaluate alert condition"""
        try:
            condition_type = alert['condition_type']
            params = alert['condition_params']

            triggered, condition_met = self._check_condition(
                condition_type, params, ltp, prev_ltp, market_data, alert
            )

            if triggered:
                self._trigger_alert(alert, market_data, ltp, condition_met)

        except Exception as e:
            logger.exception(f"Error evaluating alert {alert['id']}: {e}")

    def _check_condition(
        self,
        condition_type: str,
        params: Dict,
        ltp: float,
        prev_ltp: float,
        market_data: Dict,
        alert: Dict
    ) -> Tuple[bool, str]:
        """Check if condition is met"""

        # ─── Price Conditions ───

        if condition_type == 'crossing':
            target = params['target_value']
            triggered = (prev_ltp < target <= ltp) or (prev_ltp > target >= ltp)
            return triggered, f"Price crossed {target}"

        elif condition_type == 'crossing_up':
            target = params['target_value']
            triggered = prev_ltp <= target < ltp
            return triggered, f"Price crossed above {target}"

        elif condition_type == 'crossing_down':
            target = params['target_value']
            triggered = prev_ltp >= target > ltp
            return triggered, f"Price crossed below {target}"

        elif condition_type == 'greater_than':
            target = params['target_value']
            triggered = ltp > target
            return triggered, f"Price is above {target}"

        elif condition_type == 'less_than':
            target = params['target_value']
            triggered = ltp < target
            return triggered, f"Price is below {target}"

        # ─── Channel Conditions ───

        elif condition_type == 'entering_channel':
            upper = params['upper_bound']
            lower = params['lower_bound']
            was_outside = prev_ltp < lower or prev_ltp > upper
            is_inside = lower <= ltp <= upper
            triggered = was_outside and is_inside
            return triggered, f"Price entered channel [{lower}, {upper}]"

        elif condition_type == 'exiting_channel':
            upper = params['upper_bound']
            lower = params['lower_bound']
            was_inside = lower <= prev_ltp <= upper
            is_outside = ltp < lower or ltp > upper
            triggered = was_inside and is_outside
            direction = "above" if ltp > upper else "below"
            return triggered, f"Price exited channel {direction}"

        elif condition_type == 'inside_channel':
            upper = params['upper_bound']
            lower = params['lower_bound']
            triggered = lower <= ltp <= upper
            return triggered, f"Price is inside channel [{lower}, {upper}]"

        elif condition_type == 'outside_channel':
            upper = params['upper_bound']
            lower = params['lower_bound']
            triggered = ltp < lower or ltp > upper
            return triggered, f"Price is outside channel [{lower}, {upper}]"

        # ─── Movement Conditions ───

        elif condition_type == 'moving_up':
            points = params['value']
            prev_close = market_data.get('prev_close', prev_ltp)
            triggered = ltp - prev_close >= points
            return triggered, f"Price moved up {points} points"

        elif condition_type == 'moving_down':
            points = params['value']
            prev_close = market_data.get('prev_close', prev_ltp)
            triggered = prev_close - ltp >= points
            return triggered, f"Price moved down {points} points"

        elif condition_type == 'moving_up_percent':
            percent = params['percent']
            prev_close = market_data.get('prev_close', prev_ltp)
            change_pct = ((ltp - prev_close) / prev_close) * 100
            triggered = change_pct >= percent
            return triggered, f"Price moved up {percent}%"

        elif condition_type == 'moving_down_percent':
            percent = params['percent']
            prev_close = market_data.get('prev_close', prev_ltp)
            change_pct = ((prev_close - ltp) / prev_close) * 100
            triggered = change_pct >= percent
            return triggered, f"Price moved down {percent}%"

        # ─── Volume Conditions ───

        elif condition_type == 'volume_greater_than':
            threshold = params['volume']
            volume = market_data.get('volume', 0)
            triggered = volume > threshold
            return triggered, f"Volume exceeded {threshold}"

        elif condition_type == 'volume_spike':
            multiplier = params.get('multiplier', 2)
            period = params.get('period', 20)
            # Would need historical data - simplified check
            volume = market_data.get('volume', 0)
            triggered = False  # TODO: Implement with history service
            return triggered, f"Volume spike {multiplier}x"

        # ─── Technical Indicators ───
        # These require calling indicator_service

        elif condition_type.startswith('rsi_'):
            return self._check_rsi_condition(condition_type, params, alert)

        elif condition_type.startswith('macd_'):
            return self._check_macd_condition(condition_type, params, alert)

        elif condition_type in ['ema_cross_up', 'ema_cross_down', 'sma_cross_up', 'sma_cross_down']:
            return self._check_ma_crossover_condition(condition_type, params, alert)

        elif condition_type in ['price_cross_sma_up', 'price_cross_sma_down',
                                'price_cross_ema_up', 'price_cross_ema_down']:
            return self._check_price_ma_condition(condition_type, params, alert, ltp, prev_ltp)

        elif condition_type.startswith('supertrend_'):
            return self._check_supertrend_condition(condition_type, params, alert)

        elif condition_type in ['vwap_cross_up', 'vwap_cross_down']:
            return self._check_vwap_condition(condition_type, params, alert, ltp, prev_ltp)

        # ─── Time-Based Conditions ───

        elif condition_type == 'at_time':
            target_time = datetime.strptime(params['time'], '%H:%M').time()
            now = datetime.now().time()
            # Check within 1 minute window
            triggered = (target_time.hour == now.hour and
                        target_time.minute == now.minute)
            return triggered, f"Time reached {params['time']}"

        return False, "Unknown condition"

    def _check_rsi_condition(self, condition_type: str, params: Dict, alert: Dict) -> Tuple[bool, str]:
        """Check RSI-based conditions"""
        period = params.get('period', 14)
        level = params.get('level', 30 if 'oversold' in condition_type else 70)

        success, data = indicator_service.calculate_rsi(
            alert['symbol'], alert['exchange'], period, alert['api_key']
        )

        if not success:
            return False, "RSI calculation failed"

        current_rsi = data['current_value']
        prev_rsi = data['previous_value']

        if condition_type == 'rsi_crossing':
            triggered = (prev_rsi < level <= current_rsi) or (prev_rsi > level >= current_rsi)
            return triggered, f"RSI crossed {level}"

        elif condition_type == 'rsi_crossing_up':
            triggered = prev_rsi <= level < current_rsi
            return triggered, f"RSI crossed above {level}"

        elif condition_type == 'rsi_crossing_down':
            triggered = prev_rsi >= level > current_rsi
            return triggered, f"RSI crossed below {level}"

        elif condition_type == 'rsi_greater_than':
            triggered = current_rsi > level
            return triggered, f"RSI is above {level}"

        elif condition_type == 'rsi_less_than':
            triggered = current_rsi < level
            return triggered, f"RSI is below {level}"

        elif condition_type == 'rsi_overbought':
            triggered = prev_rsi <= 70 < current_rsi
            return triggered, "RSI entered overbought zone"

        elif condition_type == 'rsi_oversold':
            triggered = prev_rsi >= 30 > current_rsi
            return triggered, "RSI entered oversold zone"

        return False, "Unknown RSI condition"

    def _check_macd_condition(self, condition_type: str, params: Dict, alert: Dict) -> Tuple[bool, str]:
        """Check MACD-based conditions"""
        fast = params.get('fast', 12)
        slow = params.get('slow', 26)
        signal = params.get('signal', 9)

        success, data = indicator_service.calculate_macd(
            alert['symbol'], alert['exchange'], fast, slow, signal, alert['api_key']
        )

        if not success:
            return False, "MACD calculation failed"

        macd = data['macd']
        signal_line = data['signal']
        prev_macd = data['prev_macd']
        prev_signal = data['prev_signal']

        if condition_type == 'macd_cross_up':
            triggered = prev_macd <= prev_signal and macd > signal_line
            return triggered, "MACD crossed above Signal"

        elif condition_type == 'macd_cross_down':
            triggered = prev_macd >= prev_signal and macd < signal_line
            return triggered, "MACD crossed below Signal"

        elif condition_type == 'macd_above_zero':
            triggered = prev_macd <= 0 < macd
            return triggered, "MACD crossed above zero"

        elif condition_type == 'macd_below_zero':
            triggered = prev_macd >= 0 > macd
            return triggered, "MACD crossed below zero"

        return False, "Unknown MACD condition"

    def _check_ma_crossover_condition(self, condition_type: str, params: Dict, alert: Dict) -> Tuple[bool, str]:
        """Check moving average crossover conditions"""
        fast_period = params.get('fast_period', 9)
        slow_period = params.get('slow_period', 21)

        success, data = indicator_service.get_ema_crossover(
            alert['symbol'], alert['exchange'], fast_period, slow_period, alert['api_key']
        )

        if not success:
            return False, "MA crossover calculation failed"

        if condition_type in ['ema_cross_up', 'sma_cross_up']:
            triggered = data['cross_up']
            return triggered, f"Fast MA crossed above Slow MA"

        elif condition_type in ['ema_cross_down', 'sma_cross_down']:
            triggered = data['cross_down']
            return triggered, f"Fast MA crossed below Slow MA"

        return False, "Unknown MA crossover condition"

    def _check_supertrend_condition(self, condition_type: str, params: Dict, alert: Dict) -> Tuple[bool, str]:
        """Check Supertrend conditions"""
        period = params.get('period', 10)
        multiplier = params.get('multiplier', 3)

        success, data = indicator_service.calculate_supertrend(
            alert['symbol'], alert['exchange'], period, multiplier, alert['api_key']
        )

        if not success:
            return False, "Supertrend calculation failed"

        if condition_type == 'supertrend_buy':
            triggered = data['buy_signal']
            return triggered, "Supertrend turned bullish"

        elif condition_type == 'supertrend_sell':
            triggered = data['sell_signal']
            return triggered, "Supertrend turned bearish"

        return False, "Unknown Supertrend condition"

    # ─────────────────────────────────────────────────────────────────
    # Alert Triggering
    # ─────────────────────────────────────────────────────────────────

    def _trigger_alert(self, alert: Dict, market_data: Dict, trigger_value: float, condition_met: str):
        """Handle alert trigger"""
        try:
            logger.info(f"Alert triggered: {alert['alert_name']} - {condition_met}")

            # Get target value for logging
            params = alert['condition_params']
            target_value = params.get('target_value') or params.get('level') or 0

            # Log trigger
            trigger_id = log_trigger(
                alert_id=alert['id'],
                user_id=alert['user_id'],
                trigger_value=trigger_value,
                target_value=target_value,
                condition_met=condition_met,
                market_data=market_data
            )

            # Execute order if configured
            order_response = None
            if alert['action_type'] in ['telegram_order', 'telegram_smart_order']:
                order_response = self._execute_order(alert)

                # Update trigger with order status
                if order_response:
                    update_trigger_order_status(
                        trigger_id=trigger_id,
                        placed=order_response.get('status') == 'success',
                        order_id=order_response.get('orderid'),
                        order_status='success' if order_response.get('status') == 'success' else 'failed',
                        order_response=order_response,
                        error=order_response.get('message') if order_response.get('status') != 'success' else None
                    )

            # Send Telegram notification
            telegram_sent = self._send_telegram_alert(alert, market_data, trigger_value, condition_met, order_response)
            update_trigger_telegram_status(trigger_id, telegram_sent)

            # Update alert state
            update_alert_after_trigger(alert['id'], trigger_value)

            # Remove from monitoring if once mode
            if alert['trigger_mode'] == 'once':
                self.remove_alert(alert['id'])

        except Exception as e:
            logger.exception(f"Error triggering alert {alert['id']}: {e}")

    def _execute_order(self, alert: Dict) -> Optional[Dict]:
        """Execute order for alert"""
        order_config = alert.get('order_config')
        if not order_config:
            return None

        try:
            if alert['action_type'] == 'telegram_smart_order':
                success, response, status = place_smart_order(
                    order_data=order_config,
                    api_key=alert['api_key']
                )
            else:
                success, response, status = place_order(
                    order_data=order_config,
                    api_key=alert['api_key']
                )

            return response

        except Exception as e:
            logger.exception(f"Error executing order for alert {alert['id']}: {e}")
            return {'status': 'error', 'message': str(e)}

    def _send_telegram_alert(
        self,
        alert: Dict,
        market_data: Dict,
        trigger_value: float,
        condition_met: str,
        order_response: Dict = None
    ) -> bool:
        """Send Telegram notification"""
        try:
            # Format message
            message = self._format_telegram_message(
                alert, market_data, trigger_value, condition_met, order_response
            )

            # Use existing telegram service
            telegram_alert_service.send_order_alert(
                order_type='price_alert',
                order_data={
                    'alert_name': alert['alert_name'],
                    'symbol': alert['symbol'],
                    'exchange': alert['exchange'],
                    'condition_met': condition_met,
                    'trigger_value': trigger_value
                },
                response=order_response or {'status': 'success', 'mode': 'live'},
                api_key=alert['api_key']
            )

            return True

        except Exception as e:
            logger.exception(f"Error sending Telegram for alert {alert['id']}: {e}")
            return False

    def _format_telegram_message(
        self,
        alert: Dict,
        market_data: Dict,
        trigger_value: float,
        condition_met: str,
        order_response: Dict = None
    ) -> str:
        """Format Telegram message"""
        lines = [
            "🚨 *ALERT TRIGGERED*",
            "",
            f"📊 *{alert['alert_name']}*",
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"Symbol: `{alert['symbol']}` ({alert['exchange']})",
            f"Condition: {condition_met}",
            f"Value: ₹{trigger_value:,.2f}",
        ]

        # Add market data
        if market_data:
            lines.extend([
                "",
                "📈 *Market Data*",
                f"Open: ₹{market_data.get('open', 0):,.2f}",
                f"High: ₹{market_data.get('high', 0):,.2f}",
                f"Low: ₹{market_data.get('low', 0):,.2f}",
                f"Change: {market_data.get('change_percent', 0):+.2f}%",
            ])

        # Add order status
        if order_response:
            if order_response.get('status') == 'success':
                order_config = alert.get('order_config', {})
                lines.extend([
                    "",
                    "✅ *ORDER EXECUTED*",
                    f"Symbol: {order_config.get('symbol')}",
                    f"Action: {order_config.get('action')} × {order_config.get('quantity')}",
                    f"Order ID: `{order_response.get('orderid')}`",
                ])
            else:
                lines.extend([
                    "",
                    "❌ *ORDER FAILED*",
                    f"Error: {order_response.get('message', 'Unknown error')}",
                ])

        # Add timestamp
        lines.extend([
            "",
            f"⏰ {datetime.now().strftime('%H:%M:%S')} IST",
            f"📅 {datetime.now().strftime('%b %d, %Y')}",
        ])

        return '\n'.join(lines)

    # ─────────────────────────────────────────────────────────────────
    # Utility Methods
    # ─────────────────────────────────────────────────────────────────

    def enrich_alert_with_market_data(self, alert: Dict) -> Dict:
        """Add current market data to alert"""
        try:
            success, response, _ = get_quotes(
                symbol=alert['symbol'],
                exchange=alert['exchange'],
                api_key=alert['api_key']
            )

            if success and 'data' in response:
                data = response['data']
                ltp = data.get('ltp', 0)

                # Calculate distance to target
                params = alert.get('condition_params', {})
                target = params.get('target_value') or params.get('upper_bound') or 0

                if target:
                    distance = ltp - target
                    distance_pct = (distance / target) * 100 if target else 0
                else:
                    distance = 0
                    distance_pct = 0

                alert['current_ltp'] = ltp
                alert['current_change'] = data.get('change_percent', 0)
                alert['distance'] = round(distance, 2)
                alert['distance_pct'] = round(distance_pct, 2)

        except Exception as e:
            logger.warning(f"Could not enrich alert {alert['id']}: {e}")

        return alert

    def test_alert(self, alert: Dict) -> Dict:
        """Test an alert (dry run)"""
        try:
            # Get current market data
            success, response, _ = get_quotes(
                symbol=alert['symbol'],
                exchange=alert['exchange'],
                api_key=alert['api_key']
            )

            if not success:
                return {'status': 'error', 'message': 'Could not fetch market data'}

            market_data = response.get('data', {})
            ltp = market_data.get('ltp', 0)

            # Check condition
            triggered, condition_met = self._check_condition(
                alert['condition_type'],
                alert['condition_params'],
                ltp,
                ltp,  # Same as current for test
                market_data,
                alert
            )

            return {
                'status': 'success',
                'triggered': triggered,
                'condition_met': condition_met,
                'current_ltp': ltp,
                'market_data': market_data,
                'message': 'Alert would trigger now' if triggered else 'Condition not met'
            }

        except Exception as e:
            logger.exception(f"Error testing alert: {e}")
            return {'status': 'error', 'message': str(e)}


# Global instance
price_alert_service = PriceAlertService()
```

---

## 5. UI Design

See the wireframes in the main PRD document above. Key pages:

1. **`/alerts`** - Main dashboard with list of all alerts
2. **Create Alert Modal** - Step-by-step wizard
3. **Alert History Modal** - Trigger history for an alert

---

## 6. Telegram Integration

The alert service integrates with the existing `telegram_alert_service.py`. A new template is added:

```python
# In TelegramAlertService.__init__, add:
self.alert_templates['price_alert'] = '🚨 *Alert Triggered*\n{details}'
```

---

## 7. Implementation Guide

### 7.1 Files to Create

| File | Purpose |
|------|---------|
| `database/migrations/alert_migrations.py` | Database migrations |
| `database/alert_db.py` | Alert database operations |
| `services/price_alert_service.py` | Alert monitoring service |
| `services/indicator_service.py` | Technical indicator calculations |
| `blueprints/alerts.py` | Flask routes |
| `templates/alerts.html` | UI template |
| `static/js/alerts.js` | Frontend JavaScript |

### 7.2 Integration Steps

1. **Run migrations** on startup:
```python
# In app.py
from database.migrations.alert_migrations import run_migrations
run_migrations()
```

2. **Register blueprint**:
```python
# In app.py
from blueprints.alerts import alerts_bp
app.register_blueprint(alerts_bp)
```

3. **Start alert service**:
```python
# In app.py, after app starts
from services.price_alert_service import price_alert_service
price_alert_service.start()
```

4. **Connect WebSocket to alert service**:
```python
# In websocket_client.py, on_message handler
from services.price_alert_service import price_alert_service
price_alert_service.process_market_data(data)
```

### 7.3 Add Navigation Link

```html
<!-- In base.html navigation -->
<li class="nav-item">
    <a class="nav-link" href="/alerts">
        <i class="fas fa-bell"></i> Alerts
    </a>
</li>
```

---

## Appendix: Condition Codes Reference

| Code | Category | Description |
|------|----------|-------------|
| `crossing` | Price | Price crosses level (either direction) |
| `crossing_up` | Price | Price crosses above level |
| `crossing_down` | Price | Price crosses below level |
| `greater_than` | Price | Price is above level |
| `less_than` | Price | Price is below level |
| `entering_channel` | Price | Price enters range |
| `exiting_channel` | Price | Price exits range |
| `inside_channel` | Price | Price is within range |
| `outside_channel` | Price | Price is outside range |
| `moving_up` | Price | Price moves up by points |
| `moving_down` | Price | Price moves down by points |
| `moving_up_percent` | Price | Price moves up by % |
| `moving_down_percent` | Price | Price moves down by % |
| `rsi_crossing` | Technical | RSI crosses level |
| `rsi_crossing_up` | Technical | RSI crosses above |
| `rsi_crossing_down` | Technical | RSI crosses below |
| `rsi_greater_than` | Technical | RSI above level |
| `rsi_less_than` | Technical | RSI below level |
| `rsi_overbought` | Technical | RSI > 70 |
| `rsi_oversold` | Technical | RSI < 30 |
| `macd_cross_up` | Technical | MACD crosses signal up |
| `macd_cross_down` | Technical | MACD crosses signal down |
| `macd_above_zero` | Technical | MACD above zero |
| `macd_below_zero` | Technical | MACD below zero |
| `price_cross_sma_up` | Technical | Price crosses SMA up |
| `price_cross_sma_down` | Technical | Price crosses SMA down |
| `price_cross_ema_up` | Technical | Price crosses EMA up |
| `price_cross_ema_down` | Technical | Price crosses EMA down |
| `ema_cross_up` | Technical | Fast EMA crosses slow up |
| `ema_cross_down` | Technical | Fast EMA crosses slow down |
| `sma_cross_up` | Technical | Fast SMA crosses slow up |
| `sma_cross_down` | Technical | Fast SMA crosses slow down |
| `bb_upper_touch` | Technical | Price touches upper BB |
| `bb_lower_touch` | Technical | Price touches lower BB |
| `bb_breakout_up` | Technical | Price breaks upper BB |
| `bb_breakout_down` | Technical | Price breaks lower BB |
| `supertrend_buy` | Technical | Supertrend bullish |
| `supertrend_sell` | Technical | Supertrend bearish |
| `vwap_cross_up` | Technical | Price crosses VWAP up |
| `vwap_cross_down` | Technical | Price crosses VWAP down |
| `volume_greater_than` | Volume | Volume above threshold |
| `volume_less_than` | Volume | Volume below threshold |
| `volume_spike` | Volume | Volume spike |
| `oi_change_up` | Volume | OI increases |
| `oi_change_down` | Volume | OI decreases |
| `at_time` | Time | At specific time |
| `market_open` | Time | At market open |
| `market_close` | Time | Before market close |
| `every_interval` | Time | Every X minutes |
| `candle_close` | Time | At candle close |

---

**Document Version:** 1.0
**Created:** December 14, 2025
**Status:** Ready for Implementation
