from flask_socketio import SocketIO
from utils.openalgo_logger import get_logger

logger = get_logger(__name__)

socketio = SocketIO(cors_allowed_origins='*')
logger.info("SocketIO initialized with CORS allowed origins: *")
