# limiter.py

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from utils.openalgo_logger import get_logger

logger = get_logger(__name__)

# Initialize Flask-Limiter without the app object
limiter = Limiter(
        key_func=get_remote_address,
        storage_uri="memory://",
        strategy="moving-window"
        )
logger.info("Flask-Limiter initialized with moving-window strategy")
