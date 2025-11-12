"""
Health Check Endpoints Blueprint

Provides health check and readiness probe endpoints for monitoring
and orchestration tools (Kubernetes, Docker, monitoring systems).
"""

import os
import sys
from datetime import datetime

from flask import Blueprint, jsonify, request
from sqlalchemy import text

from database.auth_db import get_db
from utils.version import get_version
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

# Create blueprint
health_bp = Blueprint('health', __name__, url_prefix='/health')


@health_bp.route('/', methods=['GET'])
def health_check():
    """
    Basic health check endpoint.
    Returns 200 if the application is running.

    Returns:
        JSON response with status and version info
    """
    return jsonify({
        'status': 'healthy',
        'service': 'OpenAlgo',
        'version': get_version(),
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    }), 200


@health_bp.route('/ready', methods=['GET'])
def readiness_check():
    """
    Readiness check endpoint.
    Checks if the application is ready to serve requests by verifying:
    - Database connectivity
    - Critical environment variables
    - Required services

    Returns:
        JSON response with detailed status of all components
    """
    checks = {
        'database': False,
        'environment': False,
        'services': False
    }

    errors = []
    warnings = []

    # Check database connectivity
    try:
        db = get_db()
        # Try a simple query
        result = db.execute(text("SELECT 1")).scalar()
        if result == 1:
            checks['database'] = True
        else:
            errors.append('Database query returned unexpected result')
    except Exception as e:
        errors.append(f'Database connection failed: {str(e)}')
        logger.error(f"Health check - Database error: {e}")

    # Check critical environment variables
    try:
        required_env_vars = [
            'SECRET_KEY',
            'DATABASE_URL',
            'BROKER',
        ]

        missing_vars = [var for var in required_env_vars if not os.getenv(var)]

        if not missing_vars:
            checks['environment'] = True
        else:
            errors.append(f'Missing environment variables: {", ".join(missing_vars)}')
    except Exception as e:
        errors.append(f'Environment check failed: {str(e)}')
        logger.error(f"Health check - Environment error: {e}")

    # Check services (basic check)
    try:
        # Check if Python version is correct
        python_version = sys.version_info
        if python_version.major == 3 and python_version.minor >= 12:
            checks['services'] = True
        else:
            warnings.append(f'Python version {python_version.major}.{python_version.minor} may not be fully supported')
            checks['services'] = True  # Don't fail, just warn
    except Exception as e:
        errors.append(f'Service check failed: {str(e)}')
        logger.error(f"Health check - Service error: {e}")

    # Determine overall status
    all_checks_passed = all(checks.values())

    response_data = {
        'status': 'ready' if all_checks_passed else 'not_ready',
        'checks': checks,
        'version': get_version(),
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'python_version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    }

    if errors:
        response_data['errors'] = errors

    if warnings:
        response_data['warnings'] = warnings

    status_code = 200 if all_checks_passed else 503

    return jsonify(response_data), status_code


@health_bp.route('/live', methods=['GET'])
def liveness_check():
    """
    Liveness check endpoint.
    Simple check to verify the application process is alive.
    This should always return 200 unless the app is completely dead.

    Returns:
        JSON response with minimal status
    """
    return jsonify({
        'status': 'alive',
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    }), 200


@health_bp.route('/startup', methods=['GET'])
def startup_check():
    """
    Startup check endpoint.
    Checks if the application has completed its startup sequence.

    Returns:
        JSON response with startup status
    """
    # Check if database tables are initialized
    try:
        db = get_db()
        # Check if auth table exists (one of the first tables created)
        result = db.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='auth'"
        )).fetchone()

        if result:
            return jsonify({
                'status': 'started',
                'message': 'Application startup complete',
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            }), 200
        else:
            return jsonify({
                'status': 'starting',
                'message': 'Application is still initializing',
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            }), 503
    except Exception as e:
        logger.error(f"Startup check failed: {e}")
        return jsonify({
            'status': 'starting',
            'message': 'Application is still initializing',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }), 503


@health_bp.route('/metrics', methods=['GET'])
def basic_metrics():
    """
    Basic metrics endpoint.
    Provides simple application metrics.

    Returns:
        JSON response with basic metrics
    """
    import psutil

    try:
        process = psutil.Process()

        metrics = {
            'memory': {
                'rss_mb': round(process.memory_info().rss / 1024 / 1024, 2),
                'percent': round(process.memory_percent(), 2)
            },
            'cpu': {
                'percent': round(process.cpu_percent(interval=0.1), 2),
                'num_threads': process.num_threads()
            },
            'uptime_seconds': round(datetime.now().timestamp() - process.create_time()),
            'version': get_version(),
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }

        return jsonify(metrics), 200
    except Exception as e:
        logger.error(f"Metrics collection failed: {e}")
        return jsonify({
            'error': 'Failed to collect metrics',
            'message': str(e),
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }), 500
