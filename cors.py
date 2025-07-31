# cors.py

from flask_cors import CORS
import os

def get_cors_config():
    """
    Get CORS configuration from environment variables.
    Returns a dictionary with CORS configuration options.
    """
    cors_config = {}
    
    # Check if CORS is enabled
    cors_enabled = os.getenv('CORS_ENABLED', 'FALSE').upper() == 'TRUE'
    
    if not cors_enabled:
        # If CORS is disabled, return empty config (will use Flask-CORS defaults)
        return cors_config
    
    # Get allowed origins
    allowed_origins = os.getenv('CORS_ALLOWED_ORIGINS')
    if allowed_origins:
        cors_config['origins'] = [origin.strip() for origin in allowed_origins.split(',')]
    
    # Get allowed methods
    allowed_methods = os.getenv('CORS_ALLOWED_METHODS')
    if allowed_methods:
        cors_config['methods'] = [method.strip() for method in allowed_methods.split(',')]
    
    # Get allowed headers
    allowed_headers = os.getenv('CORS_ALLOWED_HEADERS')
    if allowed_headers:
        cors_config['allow_headers'] = [header.strip() for header in allowed_headers.split(',')]
    
    # Get exposed headers
    exposed_headers = os.getenv('CORS_EXPOSED_HEADERS')
    if exposed_headers:
        cors_config['expose_headers'] = [header.strip() for header in exposed_headers.split(',')]
    
    # Check if credentials are allowed
    credentials = os.getenv('CORS_ALLOW_CREDENTIALS', 'FALSE').upper() == 'TRUE'
    if credentials:
        cors_config['supports_credentials'] = True
    
    # Max age for preflight requests
    max_age = os.getenv('CORS_MAX_AGE')
    if max_age and max_age.isdigit():
        cors_config['max_age'] = int(max_age)
    
    return cors_config

# Initialize Flask-CORS without the app object
cors = CORS(resources={r"/api/*": get_cors_config()})