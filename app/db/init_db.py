from tortoise import Tortoise
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)


async def init_db():
    """Initialize database connection with Tortoise-ORM"""
    logger.info("Initializing database connection")
    
    await Tortoise.init(
        db_url=settings.DATABASE_URL,
        modules={"models": ["app.models.user"]},
    )
    
    # Generate schemas
    logger.info("Generating database schemas")
    await Tortoise.generate_schemas()
    
    logger.info("Database initialization completed")


async def close_db():
    """Close database connection"""
    logger.info("Closing database connection")
    await Tortoise.close_connections()
