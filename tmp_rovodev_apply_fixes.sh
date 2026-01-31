#!/bin/bash
# OpenAlgo Crash Fix - Automated Application Script
# This script applies all necessary fixes to prevent file descriptor exhaustion

set -e  # Exit on error

WORKSPACE="/Users/gopinathshiva/Projects/Open-Algo-Container/openalgo1 Gopi"
cd "$WORKSPACE"

echo "========================================"
echo "OpenAlgo Crash Fix Application Script"
echo "========================================"
echo ""

# Backup existing files
echo "1. Creating backups..."
BACKUP_DIR="backup_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

# Backup files we'll modify
cp utils/traffic_logger.py "$BACKUP_DIR/" 2>/dev/null || true
cp database/traffic_db.py "$BACKUP_DIR/" 2>/dev/null || true

echo "   ✓ Backups created in $BACKUP_DIR/"
echo ""

# Fix 1: Update traffic_logger.py
echo "2. Fixing traffic logger (utils/traffic_logger.py)..."
cat > utils/traffic_logger.py << 'TRAFFIC_LOGGER_EOF'
import time
from contextlib import contextmanager

from flask import g, has_request_context, request

from database.traffic_db import TrafficLog, logs_session
from utils.ip_helper import get_real_ip
from utils.logging import get_logger

logger = get_logger(__name__)


@contextmanager
def safe_db_session(session):
    """Context manager for safe database session handling"""
    try:
        yield session
    except Exception as e:
        session.rollback()
        logger.error(f"Database error: {e}")
        raise
    finally:
        session.remove()  # Always cleanup, even on errors


class TrafficLoggerMiddleware:
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        path_info = environ.get("PATH_INFO", "")

        # Skip logging for static files and monitoring endpoints
        if (
            path_info.startswith("/static/")
            or path_info == "/favicon.ico"
            or path_info.startswith("/api/v1/latency/logs")
            or path_info.startswith("/traffic/")
            or path_info.startswith("/traffic/api/")
        ):
            return self.app(environ, start_response)

        start_time = time.time()

        def log_request(status_code, error=None):
            if not has_request_context():
                return

            try:
                with safe_db_session(logs_session):
                    duration_ms = (time.time() - start_time) * 1000
                    TrafficLog.log_request(
                        client_ip=get_real_ip(),
                        method=request.method,
                        path=request.path,
                        status_code=status_code,
                        duration_ms=duration_ms,
                        host=request.host,
                        error=error,
                        user_id=getattr(g, "user_id", None),
                    )
            except Exception as e:
                logger.debug(f"Failed to log traffic (non-critical): {e}")

        def custom_start_response(status, headers, exc_info=None):
            status_code = int(status.split()[0])
            try:
                log_request(status_code)
            except Exception as e:
                logger.debug(f"Error in custom_start_response: {e}")
            return start_response(status, headers, exc_info)

        try:
            return self.app(environ, custom_start_response)
        except Exception as e:
            try:
                log_request(500, str(e))
            except Exception as log_error:
                logger.debug(f"Error logging exception (non-critical): {log_error}")
            raise


def init_traffic_logging(app):
    """Initialize traffic logging middleware"""
    from database.traffic_db import init_logs_db

    init_logs_db()
    app.wsgi_app = TrafficLoggerMiddleware(app.wsgi_app)
TRAFFIC_LOGGER_EOF

echo "   ✓ Traffic logger fixed"
echo ""

# Fix 2: Update database connection pooling
echo "3. Fixing database connection pooling..."
echo "   Note: This requires manual update of all database/*.py files"
echo "   Updating traffic_db.py as example..."

# Create a Python script to update the pooling
python3 << 'PYTHON_EOF'
import re
import sys

file_path = "database/traffic_db.py"

try:
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Replace NullPool with StaticPool
    content = content.replace('from sqlalchemy.pool import NullPool', 
                             'from sqlalchemy.pool import StaticPool')
    
    # Update the engine creation for SQLite
    old_pattern = r'logs_engine = create_engine\(\s*LOGS_DATABASE_URL,\s*poolclass=NullPool,\s*connect_args=\{"check_same_thread":\s*False\}\s*\)'
    
    new_code = '''logs_engine = create_engine(
        LOGS_DATABASE_URL,
        poolclass=StaticPool,
        connect_args={
            "check_same_thread": False,
            "timeout": 20.0,
        },
        pool_pre_ping=True,
    )'''
    
    content = re.sub(old_pattern, new_code, content, flags=re.MULTILINE | re.DOTALL)
    
    # Update PostgreSQL pooling limits
    old_pg_pattern = r'logs_engine = create_engine\(LOGS_DATABASE_URL,\s*pool_size=50,\s*max_overflow=100,\s*pool_timeout=10\)'
    
    new_pg_code = '''logs_engine = create_engine(
        LOGS_DATABASE_URL,
        pool_size=10,
        max_overflow=20,
        pool_timeout=30,
        pool_recycle=3600,
        pool_pre_ping=True,
    )'''
    
    content = re.sub(old_pg_pattern, new_pg_code, content)
    
    with open(file_path, 'w') as f:
        f.write(content)
    
    print("   ✓ traffic_db.py updated successfully")
    
except Exception as e:
    print(f"   ⚠ Error updating traffic_db.py: {e}", file=sys.stderr)
    sys.exit(1)
PYTHON_EOF

echo ""

# Fix 3: Check ulimit
echo "4. Checking file descriptor limit..."
CURRENT_LIMIT=$(ulimit -n)
echo "   Current limit: $CURRENT_LIMIT"

if [ "$CURRENT_LIMIT" -lt 10240 ]; then
    echo "   ⚠ WARNING: Limit is too low!"
    echo ""
    echo "   Run this command to increase it:"
    echo "   echo 'ulimit -n 10240' >> ~/.zshrc"
    echo "   source ~/.zshrc"
    echo ""
else
    echo "   ✓ Limit is adequate"
fi
echo ""

# Fix 4: Create monitoring script
echo "5. Creating monitoring script..."
cat > tmp_rovodev_monitor_fds.sh << 'MONITOR_EOF'
#!/bin/bash
# File Descriptor Monitoring Script

while true; do
    echo "=== $(date) ==="
    
    MAIN_PID=$(pgrep -f "python.*app.py" | head -1)
    
    if [ ! -z "$MAIN_PID" ]; then
        FD_COUNT=$(lsof -p $MAIN_PID 2>/dev/null | wc -l)
        echo "Main Flask App (PID $MAIN_PID): $FD_COUNT file descriptors"
        
        if [ $FD_COUNT -gt 2000 ]; then
            echo "⚠️  WARNING: Approaching file descriptor limit!"
        fi
    fi
    
    echo "Strategy Scripts:"
    pgrep -f "strategies/scripts" | while read PID; do
        FD_COUNT=$(lsof -p $PID 2>/dev/null | wc -l)
        SCRIPT_NAME=$(ps -p $PID -o command= | grep -o 'option_strategy[^.]*' | head -1)
        echo "  - ${SCRIPT_NAME:-unknown} (PID $PID): $FD_COUNT file descriptors"
    done
    
    echo ""
    sleep 60
done
MONITOR_EOF

chmod +x tmp_rovodev_monitor_fds.sh
echo "   ✓ Monitoring script created: tmp_rovodev_monitor_fds.sh"
echo ""

echo "========================================"
echo "✅ Fixes Applied Successfully!"
echo "========================================"
echo ""
echo "Next Steps:"
echo "1. Review the changes in utils/traffic_logger.py"
echo "2. Update remaining database/*.py files with StaticPool (see documentation)"
echo "3. Increase ulimit if needed (see warning above)"
echo "4. Restart the application: pkill -f 'python.*app.py' && uv run python app.py"
echo "5. Start monitoring: ./tmp_rovodev_monitor_fds.sh > fd_monitor.log &"
echo ""
echo "Backups stored in: $BACKUP_DIR/"
echo ""
