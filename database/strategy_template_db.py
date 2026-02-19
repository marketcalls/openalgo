import json
import logging
import os
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import func

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

# Conditionally create engine based on DB type
if DATABASE_URL and "sqlite" in DATABASE_URL:
    engine = create_engine(
        DATABASE_URL, poolclass=NullPool, connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(DATABASE_URL, pool_size=50, max_overflow=100, pool_timeout=10)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


# ─── Model ────────────────────────────────────────────────────────────────


class StrategyTemplate(Base):
    """Reusable strategy templates (system presets + user-saved)"""

    __tablename__ = "strategy_templates"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    category = Column(String(20), nullable=False, default="neutral")  # neutral, bullish, bearish
    preset = Column(String(50))  # straddle, strangle, iron_condor, etc.
    legs_config = Column(Text, nullable=False)  # JSON array of leg objects
    risk_config = Column(Text)  # JSON risk configuration
    is_system = Column(Boolean, default=False)  # True for built-in presets
    created_by = Column(String(255))  # user_id or NULL for system
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


# ─── Database Initialization ──────────────────────────────────────────────


def init_db():
    """Initialize the database tables"""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Strategy Template DB", logger)

    # Seed system templates on first init
    _seed_system_templates()


# ─── CRUD Functions ───────────────────────────────────────────────────────


def create_template(name, legs_config, category="neutral", description=None,
                    preset=None, risk_config=None, is_system=False, created_by=None):
    """Create a new strategy template"""
    try:
        template = StrategyTemplate(
            name=name,
            description=description,
            category=category,
            preset=preset,
            legs_config=json.dumps(legs_config) if isinstance(legs_config, (list, dict)) else legs_config,
            risk_config=json.dumps(risk_config) if isinstance(risk_config, (list, dict)) else risk_config,
            is_system=is_system,
            created_by=created_by,
        )
        db_session.add(template)
        db_session.commit()
        return template
    except Exception as e:
        logger.exception(f"Error creating template: {e}")
        db_session.rollback()
        return None


def get_template(template_id):
    """Get a single template by ID"""
    try:
        return StrategyTemplate.query.get(template_id)
    except Exception as e:
        logger.exception(f"Error getting template {template_id}: {e}")
        return None


def get_all_templates(category=None, user_id=None):
    """Get all templates, optionally filtered by category or creator"""
    try:
        query = StrategyTemplate.query
        if category:
            query = query.filter_by(category=category)
        if user_id:
            # Show system templates + user's own templates
            query = query.filter(
                (StrategyTemplate.is_system == True) | (StrategyTemplate.created_by == user_id)
            )
        else:
            query = query.filter_by(is_system=True)
        return query.order_by(StrategyTemplate.name.asc()).all()
    except Exception as e:
        logger.exception(f"Error getting templates: {e}")
        return []


def delete_template(template_id, user_id):
    """Delete a template (only non-system, owned by user)"""
    try:
        template = StrategyTemplate.query.get(template_id)
        if not template:
            return False
        if template.is_system:
            return False
        if not user_id or template.created_by != user_id:
            return False
        db_session.delete(template)
        db_session.commit()
        return True
    except Exception as e:
        logger.exception(f"Error deleting template {template_id}: {e}")
        db_session.rollback()
        return False


def serialize_template(t):
    """Serialize a StrategyTemplate to dict"""
    return {
        "id": t.id,
        "name": t.name,
        "description": t.description,
        "category": t.category,
        "preset": t.preset,
        "legs_config": json.loads(t.legs_config) if t.legs_config else [],
        "risk_config": json.loads(t.risk_config) if t.risk_config else None,
        "is_system": t.is_system,
        "created_by": t.created_by,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


# ─── System Template Seeding ─────────────────────────────────────────────


def _seed_system_templates():
    """Seed built-in preset templates if they don't exist"""
    try:
        existing = StrategyTemplate.query.filter_by(is_system=True).count()
        if existing > 0:
            return  # Already seeded

        presets = [
            {
                "name": "Short Straddle",
                "description": "Sell ATM CE + ATM PE. Profits from time decay in range-bound markets.",
                "category": "neutral",
                "preset": "short_straddle",
                "legs": [
                    {"leg_type": "option", "action": "SELL", "option_type": "CE", "strike_type": "ATM",
                     "offset": "ATM", "expiry_type": "current_week", "product_type": "MIS",
                     "quantity_lots": 1, "order_type": "MARKET"},
                    {"leg_type": "option", "action": "SELL", "option_type": "PE", "strike_type": "ATM",
                     "offset": "ATM", "expiry_type": "current_week", "product_type": "MIS",
                     "quantity_lots": 1, "order_type": "MARKET"},
                ],
            },
            {
                "name": "Short Strangle",
                "description": "Sell OTM CE + OTM PE. Wider profit zone than straddle, lower premium.",
                "category": "neutral",
                "preset": "short_strangle",
                "legs": [
                    {"leg_type": "option", "action": "SELL", "option_type": "CE", "strike_type": "OTM",
                     "offset": "OTM2", "expiry_type": "current_week", "product_type": "MIS",
                     "quantity_lots": 1, "order_type": "MARKET"},
                    {"leg_type": "option", "action": "SELL", "option_type": "PE", "strike_type": "OTM",
                     "offset": "OTM2", "expiry_type": "current_week", "product_type": "MIS",
                     "quantity_lots": 1, "order_type": "MARKET"},
                ],
            },
            {
                "name": "Iron Condor",
                "description": "Sell OTM strangle + buy further OTM protection. Limited risk neutral strategy.",
                "category": "neutral",
                "preset": "iron_condor",
                "legs": [
                    {"leg_type": "option", "action": "SELL", "option_type": "CE", "strike_type": "OTM",
                     "offset": "OTM2", "expiry_type": "current_week", "product_type": "MIS",
                     "quantity_lots": 1, "order_type": "MARKET"},
                    {"leg_type": "option", "action": "BUY", "option_type": "CE", "strike_type": "OTM",
                     "offset": "OTM5", "expiry_type": "current_week", "product_type": "MIS",
                     "quantity_lots": 1, "order_type": "MARKET"},
                    {"leg_type": "option", "action": "SELL", "option_type": "PE", "strike_type": "OTM",
                     "offset": "OTM2", "expiry_type": "current_week", "product_type": "MIS",
                     "quantity_lots": 1, "order_type": "MARKET"},
                    {"leg_type": "option", "action": "BUY", "option_type": "PE", "strike_type": "OTM",
                     "offset": "OTM5", "expiry_type": "current_week", "product_type": "MIS",
                     "quantity_lots": 1, "order_type": "MARKET"},
                ],
            },
            {
                "name": "Bull Call Spread",
                "description": "Buy ATM CE + Sell OTM CE. Bullish with limited risk and reward.",
                "category": "bullish",
                "preset": "bull_call_spread",
                "legs": [
                    {"leg_type": "option", "action": "BUY", "option_type": "CE", "strike_type": "ATM",
                     "offset": "ATM", "expiry_type": "current_week", "product_type": "MIS",
                     "quantity_lots": 1, "order_type": "MARKET"},
                    {"leg_type": "option", "action": "SELL", "option_type": "CE", "strike_type": "OTM",
                     "offset": "OTM3", "expiry_type": "current_week", "product_type": "MIS",
                     "quantity_lots": 1, "order_type": "MARKET"},
                ],
            },
            {
                "name": "Bear Put Spread",
                "description": "Buy ATM PE + Sell OTM PE. Bearish with limited risk and reward.",
                "category": "bearish",
                "preset": "bear_put_spread",
                "legs": [
                    {"leg_type": "option", "action": "BUY", "option_type": "PE", "strike_type": "ATM",
                     "offset": "ATM", "expiry_type": "current_week", "product_type": "MIS",
                     "quantity_lots": 1, "order_type": "MARKET"},
                    {"leg_type": "option", "action": "SELL", "option_type": "PE", "strike_type": "OTM",
                     "offset": "OTM3", "expiry_type": "current_week", "product_type": "MIS",
                     "quantity_lots": 1, "order_type": "MARKET"},
                ],
            },
            {
                "name": "Long Straddle",
                "description": "Buy ATM CE + ATM PE. Profits from large moves in either direction.",
                "category": "neutral",
                "preset": "long_straddle",
                "legs": [
                    {"leg_type": "option", "action": "BUY", "option_type": "CE", "strike_type": "ATM",
                     "offset": "ATM", "expiry_type": "current_week", "product_type": "MIS",
                     "quantity_lots": 1, "order_type": "MARKET"},
                    {"leg_type": "option", "action": "BUY", "option_type": "PE", "strike_type": "ATM",
                     "offset": "ATM", "expiry_type": "current_week", "product_type": "MIS",
                     "quantity_lots": 1, "order_type": "MARKET"},
                ],
            },
        ]

        for p in presets:
            create_template(
                name=p["name"],
                description=p["description"],
                category=p["category"],
                preset=p["preset"],
                legs_config=p["legs"],
                is_system=True,
            )

        logger.info(f"Seeded {len(presets)} system strategy templates")
    except Exception as e:
        logger.exception(f"Error seeding system templates: {e}")
