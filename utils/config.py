# utils/config.py

from dotenv import load_dotenv
import os
from flask import session
from database.broker_db import get_broker_config

# Load environment variables from .env file with override=True to ensure values are updated
load_dotenv(override=True)

def get_broker_api_key():
    if 'user' in session and 'broker' in session:
        config = get_broker_config(session['user']['id'], session['broker'])
        if config:
            return config.api_key
    return None

def get_broker_api_secret():
    if 'user' in session and 'broker' in session:
        config = get_broker_config(session['user']['id'], session['broker'])
        if config:
            return config.api_secret
    return None

def get_broker_redirect_url():
    if 'user' in session and 'broker' in session:
        config = get_broker_config(session['user']['id'], session['broker'])
        if config:
            return config.redirect_url
    return None

def get_login_rate_limit_min():
    return os.getenv("LOGIN_RATE_LIMIT_MIN", "5 per minute")

def get_login_rate_limit_hour():
    return os.getenv("LOGIN_RATE_LIMIT_HOUR", "25 per hour")
