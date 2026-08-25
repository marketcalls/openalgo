# cors.py

import os

from flask_cors import CORS

from utils.logging import get_logger

logger = get_logger(__name__)


def is_cors_enabled():
    """Return whether cross-origin access is explicitly enabled."""
    return os.getenv("CORS_ENABLED", "FALSE").upper() == "TRUE"


def get_cors_config():
    """
    Get CORS configuration from environment variables.
    Returns a dictionary with CORS configuration options.
    """
    allowed_origins = os.getenv("CORS_ALLOWED_ORIGINS", "")
    origins = [origin.strip() for origin in allowed_origins.split(",") if origin.strip()]
    cors_config = {"origins": origins}

    # Get allowed methods
    allowed_methods = os.getenv("CORS_ALLOWED_METHODS")
    if allowed_methods:
        cors_config["methods"] = [method.strip() for method in allowed_methods.split(",")]

    # Get allowed headers
    allowed_headers = os.getenv("CORS_ALLOWED_HEADERS")
    if allowed_headers:
        cors_config["allow_headers"] = [header.strip() for header in allowed_headers.split(",")]

    # Get exposed headers
    exposed_headers = os.getenv("CORS_EXPOSED_HEADERS")
    if exposed_headers:
        cors_config["expose_headers"] = [header.strip() for header in exposed_headers.split(",")]

    # Check if credentials are allowed
    credentials = os.getenv("CORS_ALLOW_CREDENTIALS", "FALSE").upper() == "TRUE"
    if credentials:
        cors_config["supports_credentials"] = True

    # Max age for preflight requests
    max_age = os.getenv("CORS_MAX_AGE")
    if max_age and max_age.isdigit():
        cors_config["max_age"] = int(max_age)

    return cors_config


def init_cors(app):
    """Initialize Flask-CORS when it has been explicitly enabled."""
    if not is_cors_enabled():
        logger.debug("CORS is disabled")
        return

    cors_config = get_cors_config()
    if cors_config["origins"]:
        logger.debug("CORS enabled for origins: %s", ", ".join(cors_config["origins"]))
    else:
        logger.warning(
            "CORS is enabled but no allowed origins are configured; denying cross-origin requests"
        )

    CORS(app, resources={r"/api/*": cors_config})
