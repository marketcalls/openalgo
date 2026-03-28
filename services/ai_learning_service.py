"""AI Learning Service - Handles background tasks for the self-learning engine.

Orchestrates daily outcome verification and weight adjustment.
"""

import os
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from ai.self_learning import SelfLearningEngine
from utils.logging import get_logger

logger = get_logger(__name__)

# Global scheduler instance (linked to app lifecycle)
_scheduler = None

def init_ai_learning_scheduler():
    """Initialize the background scheduler for AI self-learning."""
    global _scheduler
    
    if _scheduler and _scheduler.running:
        return

    _scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
    
    # Schedule the daily learning cycle at 16:00 IST (after market close)
    # This verifies today's trades and updates agent weights
    _scheduler.add_job(
        run_daily_learning_task,
        CronTrigger(hour=16, minute=0),
        id="ai_daily_learning",
        replace_existing=True
    )
    
    _scheduler.start()
    logger.info("AI Self-Learning Scheduler started (Daily at 16:00 IST)")

def run_daily_learning_task():
    """Task executed by the scheduler to run the learning cycle."""
    logger.info("Executing daily AI learning task...")
    try:
        # Note: In a real production environment, we'd pass a real price service here.
        # For now, we'll use the engine which defaults to the internal verification logic.
        engine = SelfLearningEngine()
        engine.run_learning_cycle()
        logger.info("Daily AI learning task completed successfully.")
    except Exception as e:
        logger.error(f"Error in daily AI learning task: {e}")

def stop_ai_learning_scheduler():
    """Stop the scheduler on app shutdown."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown()
        logger.info("AI Self-Learning Scheduler stopped.")
