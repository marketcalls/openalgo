import os

# Centralized API rate limit configuration
# This value is used by all REST API endpoints via @limiter.limit(...)
# Default: "10 per second" if API_RATE_LIMIT is not set in environment variables

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")

