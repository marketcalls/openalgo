"""
Python Strategy Hosting System - Cross-Platform Process Isolation with IST Support
Route: /python
Features: Upload, Start, Stop, Schedule, Delete strategies
Supports: Windows, Linux, macOS
Note: Each strategy runs in a separate process for complete isolation
"""

import json
import logging
import os
import platform
import queue
import signal
import subprocess
import sys
import threading
from datetime import date, datetime, time
from pathlib import Path

import psutil
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import (
    Blueprint,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.utils import secure_filename

from database.market_calendar_db import get_market_hours_status, is_market_holiday, is_market_open
from utils.session import check_session_validity

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create blueprint with /python route
python_strategy_bp = Blueprint("python_strategy_bp", __name__, url_prefix="/python")

# Timezone configuration - Indian Standard Time
IST = pytz.timezone("Asia/Kolkata")

# Global storage with thread locks for safety
RUNNING_STRATEGIES = {}  # {strategy_id: {'process': subprocess.Popen, 'started_at': datetime}}
STRATEGY_CONFIGS = {}  # {strategy_id: config_dict}
SCHEDULER = None
PROCESS_LOCK = threading.Lock()  # Thread lock for process operations

# SSE (Server-Sent Events) for real-time status updates
SSE_SUBSCRIBERS = []  # List of Queue objects for SSE clients
SSE_LOCK = threading.Lock()


def broadcast_status_update(strategy_id: str, status: str, message: str = None):
    """Broadcast strategy status update to all SSE subscribers"""
    event_data = {
        "strategy_id": strategy_id,
        "status": status,
        "message": message,
        "timestamp": datetime.now(IST).isoformat(),
    }
    event = f"data: {json.dumps(event_data)}\n\n"

    with SSE_LOCK:
        # Remove dead subscribers and send to active ones
        active_subscribers = []
        for q in SSE_SUBSCRIBERS:
            try:
                q.put_nowait(event)
                active_subscribers.append(q)
            except:
                pass  # Queue full or dead, skip
        SSE_SUBSCRIBERS.clear()
        SSE_SUBSCRIBERS.extend(active_subscribers)


# File paths - use Path for cross-platform compatibility
STRATEGIES_DIR = Path("strategies") / "scripts"
LOGS_DIR = Path("log") / "strategies"  # Using existing log folder
CONFIG_FILE = Path("strategies") / "strategy_configs.json"

# Detect operating system
OS_TYPE = platform.system().lower()  # 'windows', 'linux', 'darwin'
IS_WINDOWS = OS_TYPE == "windows"
IS_MAC = OS_TYPE == "darwin"
IS_LINUX = OS_TYPE == "linux"


def init_scheduler():
    """Initialize the APScheduler with IST timezone"""
    global SCHEDULER
    if SCHEDULER is None:
        SCHEDULER = BackgroundScheduler(daemon=True, timezone=IST)
        SCHEDULER.start()
        logger.debug(f"Scheduler initialized with IST timezone on {OS_TYPE}")

        # Add daily trading day check job - runs at 00:01 IST every day
        # This stops scheduled strategies on weekends/holidays
        SCHEDULER.add_job(
            func=daily_trading_day_check,
            trigger=CronTrigger(hour=0, minute=1, timezone=IST),
            id="daily_trading_day_check",
            replace_existing=True,
        )
        logger.debug("Daily trading day check scheduled at 00:01 IST")

        # Add market hours enforcer - runs every minute during trading hours
        # This stops scheduled strategies when market closes
        SCHEDULER.add_job(
            func=market_hours_enforcer,
            trigger="interval",
            minutes=1,
            id="market_hours_enforcer",
            replace_existing=True,
        )
        logger.debug("Market hours enforcer scheduled (runs every minute)")


def load_configs():
    """Load strategy configurations from file"""
    global STRATEGY_CONFIGS
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                STRATEGY_CONFIGS = json.load(f)
            logger.debug(f"Loaded {len(STRATEGY_CONFIGS)} strategy configurations")
        except Exception as e:
            logger.exception(f"Failed to load configs: {e}")
            STRATEGY_CONFIGS = {}


def save_configs():
    """Save strategy configurations to file"""
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(STRATEGY_CONFIGS, f, indent=2, default=str, ensure_ascii=False)
        logger.debug("Configurations saved")
    except Exception as e:
        logger.exception(f"Failed to save configs: {e}")


def verify_strategy_ownership(strategy_id, user_id, return_config=False):
    """
    Verify that a user owns a strategy.

    Args:
        strategy_id: The strategy ID to verify
        user_id: The user ID to check ownership against
        return_config: If True, returns the config dict on success for atomic access

    Returns:
        If return_config=False: (success, error_response)
        If return_config=True: (success, error_response_or_config)
    """
    # Basic validation - reject obviously malicious inputs (path traversal attempts)
    if not strategy_id or ".." in strategy_id or "/" in strategy_id or "\\" in strategy_id:
        return False, (jsonify({"status": "error", "message": "Invalid strategy ID"}), 400)

    if strategy_id not in STRATEGY_CONFIGS:
        return False, (jsonify({"status": "error", "message": "Strategy not found"}), 404)

    config = STRATEGY_CONFIGS[strategy_id]
    # Check ownership - allow access if user_id matches or if strategy has no owner (legacy)
    strategy_owner = config.get("user_id")
    if strategy_owner and strategy_owner != user_id:
        return False, (
            jsonify({"status": "error", "message": "Unauthorized access to strategy"}),
            403,
        )

    if return_config:
        return True, config
    return True, None


def ensure_directories():
    """Ensure all required directories exist"""
    global STRATEGIES_DIR, LOGS_DIR
    try:
        STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Directories initialized on {OS_TYPE}")
    except PermissionError as e:
        # If we can't create directories, check if they exist
        if STRATEGIES_DIR.exists() and LOGS_DIR.exists():
            logger.warning(f"Directories exist but no write permission: {e}")
        else:
            # Try alternative paths in /tmp if main paths fail
            import tempfile

            temp_base = Path(tempfile.gettempdir()) / "openalgo"
            STRATEGIES_DIR = temp_base / "strategies" / "scripts"
            LOGS_DIR = temp_base / "log" / "strategies"
            STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            logger.warning(f"Using temporary directories due to permission issues: {temp_base}")
    except Exception as e:
        logger.exception(f"Failed to create directories: {e}")
        # Continue anyway, individual operations will handle missing directories


def get_active_broker():
    """Get the active broker from database (last logged in user's broker)"""
    try:
        from sqlalchemy import desc

        from database.auth_db import Auth

        # Get the most recent auth entry (last logged in user)
        auth_obj = Auth.query.filter_by(is_revoked=False).order_by(desc(Auth.id)).first()
        if auth_obj:
            return auth_obj.broker
        return None
    except Exception as e:
        logger.exception(f"Error getting active broker: {e}")
        return None


def check_master_contract_ready(skip_on_startup=False):
    """Check if master contracts are ready for the current broker"""
    try:
        # First try to get broker from session (if available)
        broker = session.get("broker") if session else None

        # If no session broker, try to get from database (for app restart scenarios)
        if not broker:
            broker = get_active_broker()

        if not broker:
            # During startup, we may not have a broker yet, so skip the check
            if skip_on_startup:
                logger.info("No broker found during startup - skipping master contract check")
                return True, "Skipping check during startup"
            logger.warning("No broker found for master contract check")
            return False, "No broker session found"

        # Import here to avoid circular imports
        from database.master_contract_status_db import check_if_ready

        is_ready = check_if_ready(broker)
        if is_ready:
            return True, "Master contracts ready"
        else:
            return False, f"Master contracts not ready for broker: {broker}"

    except Exception as e:
        logger.exception(f"Error checking master contract readiness: {e}")
        return False, f"Error checking master contract readiness: {str(e)}"


def get_ist_time():
    """Get current IST time"""
    return datetime.now(IST)


def format_ist_time(dt):
    """Format datetime to IST string"""
    if dt:
        if isinstance(dt, str):
            try:
                dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
            except:
                return dt
        if not dt.tzinfo:
            dt = IST.localize(dt)
        else:
            dt = dt.astimezone(IST)
        return dt.strftime("%Y-%m-%d %H:%M:%S IST")
    return ""


def get_python_executable():
    """Get the correct Python executable for the current OS"""
    # Use sys.executable which works across all platforms
    return sys.executable


def create_subprocess_args():
    """Create platform-specific subprocess arguments"""
    args = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "universal_newlines": False,  # Handle bytes for better compatibility
        "bufsize": 1,  # Line buffered
    }

    if IS_WINDOWS:
        # Windows-specific: CREATE_NEW_PROCESS_GROUP for better process isolation
        args["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        # Prevent console window popup
        args["startupinfo"] = subprocess.STARTUPINFO()
        args["startupinfo"].dwFlags |= subprocess.STARTF_USESHOWWINDOW
    else:
        # Unix-like systems (Linux, macOS)
        # Try to create new session for better process control
        try:
            args["start_new_session"] = True  # Create new process group
        except Exception as e:
            logger.warning(f"Could not set start_new_session: {e}")

        # Apply resource limits to prevent runaway strategies
        args["preexec_fn"] = set_resource_limits

    return args


# Resource limits for strategy processes (Unix only)
# Prevents buggy strategies from crashing the system
# Can be overridden via environment variable for low-memory containers
# Recommended values:
#   - 2GB container (5 strategies): STRATEGY_MEMORY_LIMIT_MB=256
#   - 4GB container (3 strategies): STRATEGY_MEMORY_LIMIT_MB=512
#   - 8GB+ container: STRATEGY_MEMORY_LIMIT_MB=1024 (default)
STRATEGY_MEMORY_LIMIT_MB = int(os.environ.get('STRATEGY_MEMORY_LIMIT_MB', '1024'))
STRATEGY_CPU_TIME_LIMIT_SEC = 3600  # Max CPU time (1 hour) - resets on each run


def set_resource_limits():
    """
    Set resource limits for strategy subprocess (Unix/Mac only).
    Called via preexec_fn before the strategy process starts.
    Prevents runaway strategies from exhausting system resources.
    """
    if IS_WINDOWS:
        return  # resource module not available on Windows

    try:
        import resource

        # Memory limit (virtual memory) - prevents memory bombs
        memory_bytes = STRATEGY_MEMORY_LIMIT_MB * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
            # Also limit data segment for additional protection
            resource.setrlimit(resource.RLIMIT_DATA, (memory_bytes, memory_bytes))
        except (OSError, ValueError) as e:
            # Some systems may not support these limits
            logger.debug(f"Could not set memory limit: {e}")

        # CPU time limit - prevents infinite loops from hogging CPU forever
        # Note: This is cumulative CPU time, not wall clock time
        try:
            resource.setrlimit(
                resource.RLIMIT_CPU, (STRATEGY_CPU_TIME_LIMIT_SEC, STRATEGY_CPU_TIME_LIMIT_SEC)
            )
        except (OSError, ValueError) as e:
            logger.debug(f"Could not set CPU limit: {e}")

        # Limit number of open files - prevents file descriptor exhaustion
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
        except (OSError, ValueError) as e:
            logger.debug(f"Could not set file descriptor limit: {e}")

        # Limit number of processes - prevents fork bombs
        try:
            resource.setrlimit(resource.RLIMIT_NPROC, (256, 256))
        except (OSError, ValueError) as e:
            logger.debug(f"Could not set process limit: {e}")

    except ImportError:
        # resource module not available (Windows)
        pass
    except Exception as e:
        logger.warning(f"Could not set resource limits: {e}")


def start_strategy_process(strategy_id):
    """Start a strategy in a new process - cross-platform implementation"""
    with PROCESS_LOCK:  # Thread-safe operation
        if strategy_id in RUNNING_STRATEGIES:
            return False, "Strategy already running"

        config = STRATEGY_CONFIGS.get(strategy_id)
        if not config:
            return False, "Strategy configuration not found"

        file_path = Path(config["file_path"])
        if not file_path.exists():
            return False, f"Strategy file not found: {file_path}"

        # Check file permissions
        if not IS_WINDOWS:
            # Check if file is readable
            if not os.access(file_path, os.R_OK):
                logger.error(f"Strategy file {file_path} is not readable. Check file permissions.")
                return False, f"Strategy file is not readable. Run: chmod +r {file_path}"

            # Check if file is executable (optional but recommended for scripts)
            if not os.access(file_path, os.X_OK):
                logger.warning(
                    f"Strategy file {file_path} is not executable. Setting execute permission."
                )
                try:
                    os.chmod(file_path, 0o755)
                except Exception as e:
                    logger.warning(f"Could not set execute permission: {e}")
                    # Continue anyway, Python can still run it

        # Check if master contracts are ready before starting strategy
        contracts_ready, contract_message = check_master_contract_ready()
        if not contracts_ready:
            logger.warning(f"Cannot start strategy {strategy_id}: {contract_message}")
            return False, f"Master contract dependency not met: {contract_message}"

        try:
            # Create log file for this run with IST timestamp
            ist_now = get_ist_time()
            log_file = LOGS_DIR / f"{strategy_id}_{ist_now.strftime('%Y%m%d_%H%M%S')}_IST.log"

            # Ensure log directory exists with proper permissions
            log_file.parent.mkdir(parents=True, exist_ok=True)
            if not IS_WINDOWS:
                try:
                    # Ensure log directory is writable
                    os.chmod(log_file.parent, 0o755)
                except:
                    pass

            # Check if we can write to log directory
            if not os.access(log_file.parent, os.W_OK):
                logger.error(f"Cannot write to log directory {log_file.parent}")
                return (
                    False,
                    f"Log directory is not writable. Check permissions for {log_file.parent}",
                )

            # Open log file for writing
            try:
                log_handle = open(log_file, "w", encoding="utf-8", buffering=1)
            except PermissionError as e:
                logger.error(f"Permission denied creating log file: {e}")
                return False, "Permission denied creating log file. Check directory permissions."
            except Exception as e:
                logger.exception(f"Error creating log file: {e}")
                return False, f"Error creating log file: {str(e)}"

            # Write header with IST time
            log_handle.write(
                f"=== Strategy Started at {ist_now.strftime('%Y-%m-%d %H:%M:%S IST')} ===\n"
            )
            log_handle.write(f"=== Platform: {OS_TYPE} ===\n\n")
            log_handle.flush()

            # Get platform-specific subprocess arguments
            subprocess_args = create_subprocess_args()
            subprocess_args["stdout"] = log_handle
            subprocess_args["stderr"] = subprocess.STDOUT
            subprocess_args["cwd"] = str(Path.cwd())

            # Start the process
            # Use Python unbuffered mode for real-time output
            cmd = [get_python_executable(), "-u", str(file_path.absolute())]

            # Log the command being executed for debugging
            logger.info(f"Executing command: {' '.join(cmd)}")
            logger.debug(f"Working directory: {subprocess_args.get('cwd', 'current')}")

            try:
                process = subprocess.Popen(cmd, **subprocess_args)
            except PermissionError as e:
                log_handle.close()
                logger.error(f"Permission denied executing strategy: {e}")
                return (
                    False,
                    "Permission denied. Check file permissions and Python executable access.",
                )
            except OSError as e:
                log_handle.close()
                if "preexec_fn" in str(e):
                    logger.error(f"Process isolation error: {e}")
                    return (
                        False,
                        "Process isolation failed. This is a known issue that has been fixed. Please restart the application.",
                    )
                else:
                    logger.error(f"OS error starting process: {e}")
                    return False, f"OS error: {str(e)}"
            except Exception as e:
                log_handle.close()
                logger.exception(f"Unexpected error starting process: {e}")
                return False, f"Failed to start process: {str(e)}"

            # Store process info
            RUNNING_STRATEGIES[strategy_id] = {
                "process": process,
                "pid": process.pid,
                "started_at": ist_now,
                "log_file": str(log_file),
                "log_handle": log_handle,  # Keep file handle open
            }

            # Update config with IST time
            STRATEGY_CONFIGS[strategy_id]["is_running"] = True
            STRATEGY_CONFIGS[strategy_id]["last_started"] = ist_now.isoformat()
            STRATEGY_CONFIGS[strategy_id]["pid"] = process.pid
            # Clear any previous error state
            STRATEGY_CONFIGS[strategy_id].pop("is_error", None)
            STRATEGY_CONFIGS[strategy_id].pop("error_message", None)
            STRATEGY_CONFIGS[strategy_id].pop("error_time", None)
            save_configs()

            # Broadcast status update via SSE
            broadcast_status_update(
                strategy_id, "running", f"Started at {ist_now.strftime('%H:%M:%S IST')}"
            )

            logger.info(
                f"Started strategy {strategy_id} with PID {process.pid} at {ist_now.strftime('%H:%M:%S IST')} on {OS_TYPE}"
            )
            return (
                True,
                f"Strategy started with PID {process.pid} at {ist_now.strftime('%H:%M:%S IST')}",
            )

        except Exception as e:
            logger.exception(f"Failed to start strategy {strategy_id}: {e}")
            return False, f"Failed to start strategy: {str(e)}"


def stop_strategy_process(strategy_id):
    """Stop a running strategy process - cross-platform implementation"""
    with PROCESS_LOCK:  # Thread-safe operation
        if strategy_id not in RUNNING_STRATEGIES:
            # Check if process is still running by PID
            if strategy_id in STRATEGY_CONFIGS:
                pid = STRATEGY_CONFIGS[strategy_id].get("pid")
                if pid and check_process_status(pid):
                    try:
                        terminate_process_cross_platform(pid)
                        STRATEGY_CONFIGS[strategy_id]["is_running"] = False
                        STRATEGY_CONFIGS[strategy_id]["pid"] = None
                        STRATEGY_CONFIGS[strategy_id]["last_stopped"] = get_ist_time().isoformat()
                        save_configs()
                        return True, "Strategy stopped"
                    except:
                        pass
            return False, "Strategy not running"

        try:
            strategy_info = RUNNING_STRATEGIES[strategy_id]
            process = strategy_info["process"]
            pid = strategy_info["pid"]

            # Handle different process types
            if isinstance(process, subprocess.Popen):
                # For subprocess.Popen objects
                # Platform-specific termination
                if IS_WINDOWS:
                    # Windows: Use terminate() then kill() if needed
                    try:
                        process.terminate()
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        # Force kill using taskkill
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(pid)],
                            capture_output=True,
                            check=False,
                        )
                        process.wait(timeout=2)
                else:
                    # Unix-like systems (Linux, macOS)
                    try:
                        # Try to kill process group if it exists
                        try:
                            # Try SIGTERM first (graceful shutdown)
                            os.killpg(os.getpgid(pid), signal.SIGTERM)
                            process.wait(timeout=5)
                        except OSError:
                            # Process might not be in a process group, kill it directly
                            process.terminate()
                            process.wait(timeout=5)
                    except (subprocess.TimeoutExpired, ProcessLookupError):
                        try:
                            # Force kill with SIGKILL
                            try:
                                os.killpg(os.getpgid(pid), signal.SIGKILL)
                            except OSError:
                                # Process might not be in a process group, kill it directly
                                process.kill()
                            process.wait(timeout=2)
                        except ProcessLookupError:
                            pass  # Process already dead
            elif hasattr(process, "terminate"):
                # For psutil.Process objects
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except psutil.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass  # Process already dead or no permission
            else:
                # Fallback: use PID directly
                terminate_process_cross_platform(pid)

            # Close log file handle safely
            close_log_handle_safely(strategy_info)

            # Remove from running strategies
            del RUNNING_STRATEGIES[strategy_id]

            # Update config with IST time
            ist_now = get_ist_time()
            STRATEGY_CONFIGS[strategy_id]["is_running"] = False
            STRATEGY_CONFIGS[strategy_id]["last_stopped"] = ist_now.isoformat()
            STRATEGY_CONFIGS[strategy_id]["pid"] = None
            save_configs()

            # Broadcast status update via SSE
            # Get current status based on config
            status, status_message = get_schedule_status(STRATEGY_CONFIGS[strategy_id])
            broadcast_status_update(strategy_id, status, status_message)

            logger.info(f"Stopped strategy {strategy_id} at {ist_now.strftime('%H:%M:%S IST')}")

            # Cleanup old log files based on configured limits
            # Run outside the lock to avoid blocking
            try:
                cleanup_strategy_logs(strategy_id)
            except Exception as cleanup_err:
                logger.warning(f"Log cleanup failed for {strategy_id}: {cleanup_err}")

            return True, f"Strategy stopped at {ist_now.strftime('%H:%M:%S IST')}"

        except Exception as e:
            logger.exception(f"Failed to stop strategy {strategy_id}: {e}")
            return False, f"Failed to stop strategy: {str(e)}"


def terminate_process_cross_platform(pid):
    """Terminate a process in a cross-platform way"""
    try:
        process = psutil.Process(pid)

        # Terminate child processes first
        children = process.children(recursive=True)
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass

        # Terminate main process
        process.terminate()

        # Wait and kill if necessary
        gone, alive = psutil.wait_procs([process] + children, timeout=3)
        for p in alive:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass

    except psutil.NoSuchProcess:
        pass  # Process already dead
    except Exception as e:
        logger.exception(f"Error terminating process {pid}: {e}")


def check_process_status(pid):
    """Check if a process is still running - cross-platform"""
    try:
        if psutil.pid_exists(pid):
            process = psutil.Process(pid)
            return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return False


def close_log_handle_safely(strategy_info):
    """Safely close a log file handle, handling all edge cases"""
    if not strategy_info:
        return
    log_handle = strategy_info.get("log_handle")
    if log_handle:
        try:
            if not log_handle.closed:
                log_handle.flush()
                log_handle.close()
        except Exception as e:
            logger.debug(f"Error closing log handle: {e}")
        finally:
            strategy_info["log_handle"] = None


def cleanup_dead_processes():
    """Clean up strategies with dead processes"""
    with PROCESS_LOCK:  # Thread-safe operation
        dead_strategies = []

        # Check RUNNING_STRATEGIES (in-memory)
        for strategy_id, info in list(RUNNING_STRATEGIES.items()):
            process = info["process"]
            is_dead = False

            # Check if process has terminated based on its type
            if isinstance(process, subprocess.Popen):
                # For subprocess.Popen objects
                if process.poll() is not None:
                    is_dead = True
            elif hasattr(process, "is_running"):
                # For psutil.Process objects
                try:
                    if not process.is_running():
                        is_dead = True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    is_dead = True
            else:
                # Fallback: try to check if process exists by PID
                try:
                    pid = info.get("pid")
                    if pid and not psutil.pid_exists(pid):
                        is_dead = True
                except:
                    is_dead = True

            if is_dead:
                dead_strategies.append(strategy_id)
                # Close log file handle safely
                close_log_handle_safely(info)

        for strategy_id in dead_strategies:
            del RUNNING_STRATEGIES[strategy_id]
            if strategy_id in STRATEGY_CONFIGS:
                STRATEGY_CONFIGS[strategy_id]["is_running"] = False
                STRATEGY_CONFIGS[strategy_id]["pid"] = None

        # Also check STRATEGY_CONFIGS for stale is_running flags
        # (e.g., after app restart, RUNNING_STRATEGIES is empty but config has is_running=True)
        configs_to_fix = []
        for strategy_id, config in STRATEGY_CONFIGS.items():
            if config.get("is_running") and strategy_id not in RUNNING_STRATEGIES:
                # Config says running but not in memory - check if PID is alive
                pid = config.get("pid")
                if pid:
                    if not psutil.pid_exists(pid):
                        configs_to_fix.append(strategy_id)
                        logger.info(
                            f"Cleaning up stale is_running flag for {strategy_id} (PID {pid} not found)"
                        )
                else:
                    # No PID stored, definitely not running
                    configs_to_fix.append(strategy_id)
                    logger.info(f"Cleaning up stale is_running flag for {strategy_id} (no PID)")

        for strategy_id in configs_to_fix:
            STRATEGY_CONFIGS[strategy_id]["is_running"] = False
            STRATEGY_CONFIGS[strategy_id]["pid"] = None

        if configs_to_fix:
            save_configs()

        if dead_strategies:
            save_configs()
            logger.info(f"Cleaned up {len(dead_strategies)} dead processes")


def is_trading_day() -> bool:
    """
    Check if today is a valid trading day (not weekend, not holiday).
    Uses the market calendar service for accurate holiday detection.

    Returns:
        True if today is a trading day, False otherwise
    """
    try:
        today = datetime.now(IST).date()

        # Check using market calendar service (includes weekend check)
        if is_market_holiday(today, exchange="NSE"):
            return False

        return True
    except Exception as e:
        logger.exception(f"Error checking trading day status: {e}")
        # On error, default to NOT running to be safe
        return False


def is_within_market_hours() -> bool:
    """
    Check if current time is within market trading hours.
    Uses the market calendar database for accurate exchange-specific timings.

    Returns:
        True if within market hours, False otherwise
    """
    try:
        # Use the market calendar function which checks all exchanges
        return is_market_open()
    except Exception as e:
        logger.exception(f"Error checking market hours: {e}")
        return False


def get_market_status() -> dict:
    """
    Get detailed market status with reason for being closed.

    Returns:
        dict with:
        - is_open: bool
        - reason: str (None if open, else 'weekend', 'holiday', 'before_market', 'after_market')
        - message: str (human readable message)
        - next_open: str (when market opens next, if closed)
    """
    try:
        now = datetime.now(IST)
        today = now.date()

        # Check weekend first
        if today.weekday() >= 5:  # Saturday = 5, Sunday = 6
            day_name = "Saturday" if today.weekday() == 5 else "Sunday"
            return {
                "is_open": False,
                "reason": "weekend",
                "message": f"Market closed - {day_name}",
                "day": day_name,
            }

        # Check holiday
        if is_market_holiday(today):
            return {"is_open": False, "reason": "holiday", "message": "Market closed - Holiday"}

        # Check market hours using market calendar
        status = get_market_hours_status()

        if status.get("any_market_open"):
            return {"is_open": True, "reason": None, "message": "Market is open"}

        # Market is closed - determine if before or after hours
        current_ms = status.get("current_time_ms", 0)
        earliest_open = status.get("earliest_open_ms", 33300000)  # Default 09:15
        latest_close = status.get("latest_close_ms", 55800000)  # Default 15:30

        if current_ms < earliest_open:
            return {
                "is_open": False,
                "reason": "before_market",
                "message": "Market closed - Before market hours",
            }
        else:
            return {
                "is_open": False,
                "reason": "after_market",
                "message": "Market closed - After market hours",
            }

    except Exception as e:
        logger.exception(f"Error getting market status: {e}")
        return {
            "is_open": False,
            "reason": "error",
            "message": f"Error checking market status: {str(e)}",
        }


def scheduled_start_strategy(strategy_id: str):
    """
    Wrapper function for scheduled strategy start.
    Respects user's schedule_days - if today is in schedule, it runs.
    Only blocks on non-trading days if the day is NOT explicitly scheduled.
    Respects manual stop - won't auto-start until user manually starts again.
    """
    config = STRATEGY_CONFIGS.get(strategy_id, {})
    now = datetime.now(IST)
    day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    today_day = day_names[now.weekday()]

    # Check if strategy was manually stopped - respect user's decision permanently
    # User must manually start the strategy to resume auto-scheduling
    if config.get("manually_stopped"):
        logger.info(
            f"Strategy {strategy_id} was manually stopped - skipping scheduled auto-start (start manually to resume)"
        )
        return

    # Check if today is explicitly in the user's schedule_days
    # If yes, trust the user's decision and skip trading day checks
    schedule_days = config.get("schedule_days", [])
    today_in_schedule = today_day in [d.lower() for d in schedule_days]

    if today_in_schedule:
        logger.info(
            f"Strategy {strategy_id} is explicitly scheduled for {today_day.capitalize()} - skipping trading day check"
        )
    else:
        # Today is NOT in schedule_days - this shouldn't happen normally
        # (scheduler only triggers on scheduled days), but check anyway
        logger.warning(
            f"Strategy {strategy_id} scheduled start called but {today_day.capitalize()} not in schedule_days"
        )
        return

    # Check for market holidays (weekdays only) - weekends are handled by schedule_days
    if is_trading_day_enforcement_enabled() and now.weekday() < 5:
        # It's a weekday - check if it's a market holiday
        if not is_trading_day():
            reason = "holiday"
            message = "Market closed - Holiday"
            logger.warning(f"Strategy {strategy_id} scheduled start BLOCKED - {message}")

            # Store the blocked reason
            if strategy_id in STRATEGY_CONFIGS:
                STRATEGY_CONFIGS[strategy_id]["paused_reason"] = reason
                STRATEGY_CONFIGS[strategy_id]["paused_message"] = message
                save_configs()
            return

    # Clear any previous paused reason
    if strategy_id in STRATEGY_CONFIGS:
        STRATEGY_CONFIGS[strategy_id].pop("paused_reason", None)
        STRATEGY_CONFIGS[strategy_id].pop("paused_message", None)

    logger.info(f"All checks passed - proceeding to start strategy {strategy_id}")
    start_strategy_process(strategy_id)


def scheduled_stop_strategy(strategy_id: str):
    """
    Wrapper function for scheduled strategy stop.
    Always stops the strategy regardless of market status (for safety).
    """
    # Always stop - this is a safety measure to prevent strategies from running after hours
    logger.info(f"Scheduled stop triggered for strategy {strategy_id}")
    stop_strategy_process(strategy_id)


def is_trading_day_enforcement_enabled() -> bool:
    """
    Trading day enforcement is always enabled.
    We only block on weekends/holidays, not specific market hours.
    The scheduler handles start/stop times for each strategy.
    """
    return True


def daily_trading_day_check():
    """
    Daily check that runs at 00:01 IST to stop scheduled strategies on non-trading days.
    This ensures strategies started on Friday don't keep running through the weekend.
    """
    try:
        if not is_trading_day_enforcement_enabled():
            logger.debug("Market hours enforcement is disabled - skipping daily check")
            return

        market_status = get_market_status()

        if market_status["is_open"]:
            logger.debug("Daily check: Market is open - no cleanup needed")
            return

        reason = market_status["reason"]
        message = market_status["message"]

        logger.info(f"Daily check: {message} - checking for running scheduled strategies")

        # Get today's day name to check if strategies are scheduled for today
        now = datetime.now(IST)
        day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        today_day = day_names[now.weekday()]

        stopped_count = 0
        for strategy_id, config in list(STRATEGY_CONFIGS.items()):
            # Only stop strategies that are:
            # 1. Currently running (check config AND verify process is alive)
            # 2. Scheduled (not manually started)
            if not config.get("is_scheduled"):
                continue

            # Skip if strategy is explicitly scheduled for today (e.g., special Saturday session)
            schedule_days = config.get("schedule_days", [])
            if today_day in [d.lower() for d in schedule_days]:
                logger.debug(f"Strategy {strategy_id} scheduled for {today_day} - not stopping")
                continue

            # Check if strategy is running - either in memory dict or by PID
            is_running = strategy_id in RUNNING_STRATEGIES
            if not is_running and config.get("is_running"):
                # Config says running but not in memory - check if process is alive
                pid = config.get("pid")
                if pid and check_process_status(pid):
                    is_running = True

            if is_running:
                logger.info(f"Stopping scheduled strategy {strategy_id} - {message}")
                stop_strategy_process(strategy_id)

                # Store the pause reason in config
                STRATEGY_CONFIGS[strategy_id]["paused_reason"] = reason
                STRATEGY_CONFIGS[strategy_id]["paused_message"] = message
                stopped_count += 1

        if stopped_count > 0:
            save_configs()
            logger.info(f"Daily cleanup: Stopped {stopped_count} scheduled strategies ({message})")
        else:
            logger.debug("Daily cleanup: No scheduled strategies were running")

    except Exception as e:
        logger.exception(f"Error in daily trading day check: {e}")


def is_within_schedule_time(strategy_id: str) -> bool:
    """
    Check if current time is within the strategy's scheduled time range.

    Args:
        strategy_id: The strategy ID to check

    Returns:
        True if current time is between schedule_start and schedule_stop
    """
    try:
        config = STRATEGY_CONFIGS.get(strategy_id, {})
        schedule_start = config.get("schedule_start")
        schedule_stop = config.get("schedule_stop")

        if not schedule_start:
            return False

        now = datetime.now(IST)
        current_time = now.time()

        # Parse start time
        start_hour, start_min = map(int, schedule_start.split(":"))
        start_time = time(start_hour, start_min)

        # Parse stop time (if provided)
        if schedule_stop:
            stop_hour, stop_min = map(int, schedule_stop.split(":"))
            stop_time = time(stop_hour, stop_min)
        else:
            stop_time = time(23, 59)  # Default to end of day

        # Check if current time is within range
        return start_time <= current_time <= stop_time

    except Exception as e:
        logger.exception(f"Error checking schedule time for {strategy_id}: {e}")
        return False


def market_hours_enforcer():
    """
    Periodic check that runs every minute to enforce TRADING DAYS only.

    NOTE: We only enforce trading days (weekends/holidays), NOT specific market hours.
    Reasons:
    1. Different exchanges have different hours (NSE: 9:15-15:30, MCX: 9:00-23:55)
    2. We don't know which exchange a strategy trades on
    3. The scheduler's start/stop times handle hour-based execution

    This enforcer only stops strategies on non-trading days (weekends/holidays).
    """
    try:
        if not is_trading_day_enforcement_enabled():
            return

        today_is_trading_day = is_trading_day()

        # If it's a trading day, clear paused reasons and START strategies that were blocked
        if today_is_trading_day:
            started_count = 0
            cleared_any = False

            for strategy_id, config in list(STRATEGY_CONFIGS.items()):
                paused_reason = config.get("paused_reason")

                # If strategy was paused due to weekend/holiday, try to start it
                # (only start if the scheduler's time range would be active)
                if paused_reason in ("weekend", "holiday") and config.get("is_scheduled"):
                    # Only start if not already running
                    is_running = strategy_id in RUNNING_STRATEGIES
                    if not is_running and config.get("pid"):
                        is_running = check_process_status(config.get("pid"))

                    if not is_running:
                        # Check if current time is within scheduler's time range
                        if is_within_schedule_time(strategy_id):
                            logger.info(
                                f"Trading day enforcer: Starting paused strategy {strategy_id} (was: {paused_reason})"
                            )
                            success, message = start_strategy_process(strategy_id)
                            if success:
                                started_count += 1
                            else:
                                logger.warning(f"Failed to start {strategy_id}: {message}")

                # Clear paused reasons (it's a trading day now)
                if "paused_reason" in config:
                    del config["paused_reason"]
                    cleared_any = True
                if "paused_message" in config:
                    del config["paused_message"]
                    cleared_any = True

            if cleared_any or started_count > 0:
                save_configs()
                if started_count > 0:
                    logger.info(f"Trading day enforcer: Started {started_count} paused strategies")
            return

        # Not a standard trading day - but check if strategy is scheduled for today
        now = datetime.now(IST)
        day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        today_day = day_names[now.weekday()]

        if now.weekday() >= 5:
            reason = "weekend"
            day_name = "Saturday" if now.weekday() == 5 else "Sunday"
            message = f"Market closed - {day_name}"
        else:
            reason = "holiday"
            message = "Market closed - Holiday"

        stopped_count = 0
        for strategy_id, config in list(STRATEGY_CONFIGS.items()):
            # Only stop strategies that are:
            # 1. Currently running (check config AND verify process is alive)
            # 2. Scheduled (not manually started)
            if not config.get("is_scheduled"):
                continue

            # Skip if strategy is explicitly scheduled for today (e.g., special Saturday session)
            schedule_days = config.get("schedule_days", [])
            if today_day in [d.lower() for d in schedule_days]:
                logger.debug(f"Strategy {strategy_id} scheduled for {today_day} - not stopping")
                continue

            # Check if strategy is running - either in memory dict or by PID
            is_running = strategy_id in RUNNING_STRATEGIES
            if not is_running and config.get("is_running"):
                # Config says running but not in memory - check if process is alive
                pid = config.get("pid")
                if pid and check_process_status(pid):
                    is_running = True

            if is_running:
                logger.info(f"Trading day enforcer: Stopping {strategy_id} - {message}")
                stop_strategy_process(strategy_id)

                # Store the pause reason in config
                STRATEGY_CONFIGS[strategy_id]["paused_reason"] = reason
                STRATEGY_CONFIGS[strategy_id]["paused_message"] = message
                stopped_count += 1

        if stopped_count > 0:
            save_configs()
            logger.info(f"Trading day enforcer: Stopped {stopped_count} strategies ({message})")

    except Exception as e:
        logger.exception(f"Error in trading day enforcer: {e}")


def cleanup_strategy_logs(strategy_id: str):
    """
    Cleanup log files for a strategy based on configured limits.
    Enforces: max files, max total size, and retention days.
    Only cleans up logs for stopped strategies.
    """
    # Don't cleanup logs for running strategies
    if strategy_id in RUNNING_STRATEGIES:
        return

    try:
        # Get limits from environment
        max_files = int(os.getenv("STRATEGY_LOG_MAX_FILES", "10"))
        max_size_mb = float(os.getenv("STRATEGY_LOG_MAX_SIZE_MB", "50"))
        retention_days = int(os.getenv("STRATEGY_LOG_RETENTION_DAYS", "7"))

        # Find all log files for this strategy, sorted by modification time (oldest first)
        log_files = sorted(LOGS_DIR.glob(f"{strategy_id}_*.log"), key=lambda f: f.stat().st_mtime)

        if not log_files:
            return

        now = datetime.now(IST)
        deleted_count = 0

        # 1. Delete logs older than retention days
        for log_file in log_files[:]:  # Copy list to allow modification
            try:
                file_age_days = (
                    now - datetime.fromtimestamp(log_file.stat().st_mtime, tz=IST)
                ).days
                if file_age_days > retention_days:
                    log_file.unlink()
                    log_files.remove(log_file)
                    deleted_count += 1
                    logger.debug(f"Deleted old log file {log_file.name} ({file_age_days} days old)")
            except Exception as e:
                logger.exception(f"Error deleting old log {log_file.name}: {e}")

        # 2. Delete oldest files if exceeding max file count
        while len(log_files) > max_files:
            try:
                oldest = log_files.pop(0)
                oldest.unlink()
                deleted_count += 1
                logger.debug(f"Deleted log file {oldest.name} (exceeds max files: {max_files})")
            except Exception as e:
                logger.exception(f"Error deleting log {oldest.name}: {e}")
                break

        # 3. Delete oldest files if exceeding max total size
        total_size_mb = sum(f.stat().st_size for f in log_files) / (1024 * 1024)
        while total_size_mb > max_size_mb and log_files:
            try:
                oldest = log_files.pop(0)
                file_size_mb = oldest.stat().st_size / (1024 * 1024)
                oldest.unlink()
                total_size_mb -= file_size_mb
                deleted_count += 1
                logger.debug(f"Deleted log file {oldest.name} (exceeds max size: {max_size_mb}MB)")
            except Exception as e:
                logger.exception(f"Error deleting log {oldest.name}: {e}")
                break

        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} log files for strategy {strategy_id}")

    except Exception as e:
        logger.exception(f"Error cleaning up logs for strategy {strategy_id}: {e}")


def schedule_strategy(strategy_id, start_time, stop_time=None, days=None):
    """
    Schedule a strategy to run at specific times (IST).
    Allows any day of the week to support special exchange sessions (e.g., Muhurat trading).
    """
    if not days:
        days = ["mon", "tue", "wed", "thu", "fri"]  # Default to weekdays

    # Validate days are valid day names
    valid_days = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
    days_lower = [d.lower() for d in days]
    invalid_days = set(days_lower) - valid_days
    if invalid_days:
        raise ValueError(
            f"Invalid schedule days: {invalid_days}. Valid days: mon, tue, wed, thu, fri, sat, sun"
        )

    # Normalize days to lowercase
    days = days_lower

    # Create job ID
    start_job_id = f"start_{strategy_id}"
    stop_job_id = f"stop_{strategy_id}"

    # Remove existing jobs if any
    if SCHEDULER.get_job(start_job_id):
        SCHEDULER.remove_job(start_job_id)
    if SCHEDULER.get_job(stop_job_id):
        SCHEDULER.remove_job(stop_job_id)

    # Schedule start with holiday check wrapper (time is already in IST from frontend)
    hour, minute = map(int, start_time.split(":"))
    SCHEDULER.add_job(
        func=lambda: scheduled_start_strategy(strategy_id),
        trigger=CronTrigger(hour=hour, minute=minute, day_of_week=",".join(days), timezone=IST),
        id=start_job_id,
        replace_existing=True,
    )

    # Schedule stop if provided (always runs for safety)
    if stop_time:
        hour, minute = map(int, stop_time.split(":"))
        SCHEDULER.add_job(
            func=lambda: scheduled_stop_strategy(strategy_id),
            trigger=CronTrigger(hour=hour, minute=minute, day_of_week=",".join(days), timezone=IST),
            id=stop_job_id,
            replace_existing=True,
        )

    # Update config
    STRATEGY_CONFIGS[strategy_id]["is_scheduled"] = True
    STRATEGY_CONFIGS[strategy_id]["schedule_start"] = start_time
    STRATEGY_CONFIGS[strategy_id]["schedule_stop"] = stop_time
    STRATEGY_CONFIGS[strategy_id]["schedule_days"] = days
    save_configs()

    logger.debug(
        f"Scheduled strategy {strategy_id}: {start_time} - {stop_time} IST on {days} (holiday check enforced)"
    )


def unschedule_strategy(strategy_id):
    """Remove scheduling for a strategy"""
    start_job_id = f"start_{strategy_id}"
    stop_job_id = f"stop_{strategy_id}"

    if SCHEDULER.get_job(start_job_id):
        SCHEDULER.remove_job(start_job_id)
    if SCHEDULER.get_job(stop_job_id):
        SCHEDULER.remove_job(stop_job_id)

    if strategy_id in STRATEGY_CONFIGS:
        STRATEGY_CONFIGS[strategy_id]["is_scheduled"] = False
        save_configs()

    logger.info(f"Unscheduled strategy {strategy_id}")


@python_strategy_bp.route("/")
@check_session_validity
def index():
    """Main dashboard"""
    # Ensure initialization is done when first accessed
    initialize_with_app_context()
    cleanup_dead_processes()

    strategies = []
    for sid, config in STRATEGY_CONFIGS.items():
        # Check if process is actually running
        if config.get("pid"):
            config["is_running"] = check_process_status(config["pid"])
            if not config["is_running"]:
                config["pid"] = None
                save_configs()

        strategy_info = {
            "id": sid,
            "name": config.get("name", "Unnamed"),
            "file": Path(config.get("file_path", "")).name,
            "is_running": config.get("is_running", False),
            "is_scheduled": config.get("is_scheduled", False),
            "is_error": config.get("is_error", False),
            "error_message": config.get("error_message", ""),
            "error_time": format_ist_time(config.get("error_time", "")),
            "schedule_start": config.get("schedule_start", ""),
            "schedule_stop": config.get("schedule_stop", ""),
            "schedule_days": config.get("schedule_days", []),
            "created_at": config.get("created_at", ""),
            "last_started": format_ist_time(config.get("last_started", "")),
            "last_stopped": format_ist_time(config.get("last_stopped", "")),
            "pid": config.get("pid"),
            "params": {},  # No params needed in simplified version
        }

        # Add runtime info if running
        if sid in RUNNING_STRATEGIES:
            info = RUNNING_STRATEGIES[sid]
            strategy_info["started_at"] = info["started_at"]
            strategy_info["log_file"] = info["log_file"]

        strategies.append(strategy_info)

    # Get current IST time for the page
    current_ist = get_ist_time().strftime("%Y-%m-%d %H:%M:%S IST")

    return render_template(
        "python_strategy/index.html",
        strategies=strategies,
        current_ist_time=current_ist,
        platform=OS_TYPE.capitalize(),
    )


@python_strategy_bp.route("/new", methods=["GET", "POST"])
@check_session_validity
def new_strategy():
    """Upload a new strategy"""
    user_id = session.get("user")
    is_ajax = request.headers.get(
        "X-Requested-With"
    ) == "XMLHttpRequest" or request.content_type.startswith("multipart/form-data")

    if not user_id:
        if is_ajax:
            return jsonify({"status": "error", "message": "Session expired"}), 401
        flash("Session expired", "error")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        if "strategy_file" not in request.files:
            if is_ajax:
                return jsonify({"status": "error", "message": "No file selected"}), 400
            flash("No file selected", "error")
            return redirect(request.url)

        file = request.files["strategy_file"]
        if file.filename == "":
            if is_ajax:
                return jsonify({"status": "error", "message": "No file selected"}), 400
            flash("No file selected", "error")
            return redirect(request.url)

        if file and file.filename.endswith(".py"):
            # Sanitize filename first to prevent path traversal and injection
            safe_filename = secure_filename(file.filename)
            if not safe_filename or not safe_filename.endswith(".py"):
                if is_ajax:
                    return jsonify({"status": "error", "message": "Invalid filename"}), 400
                flash("Invalid filename", "error")
                return redirect(request.url)

            # Generate unique ID with IST timestamp from sanitized filename
            ist_now = get_ist_time()
            safe_stem = Path(safe_filename).stem
            # Further sanitize: only allow alphanumeric, underscore, and hyphen
            safe_stem = "".join(c for c in safe_stem if c.isalnum() or c in "_-")
            if not safe_stem:
                safe_stem = "strategy"
            strategy_id = f"{safe_stem}_{ist_now.strftime('%Y%m%d%H%M%S')}"

            # Save file with sanitized path
            file_path = STRATEGIES_DIR / f"{strategy_id}.py"

            # Verify the resolved path is within STRATEGIES_DIR (defense in depth)
            try:
                resolved_path = file_path.resolve()
                strategies_dir_resolved = STRATEGIES_DIR.resolve()
                if not str(resolved_path).startswith(str(strategies_dir_resolved)):
                    logger.warning(f"Path traversal attempt in file upload: {file.filename}")
                    if is_ajax:
                        return jsonify({"status": "error", "message": "Invalid file path"}), 400
                    flash("Invalid file path", "error")
                    return redirect(request.url)
            except Exception as e:
                logger.exception(f"Error validating file path: {e}")
                if is_ajax:
                    return jsonify({"status": "error", "message": "Invalid file path"}), 400
                flash("Invalid file path", "error")
                return redirect(request.url)

            STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)
            file.save(str(file_path))

            # Make file executable on Unix-like systems
            if not IS_WINDOWS:
                try:
                    os.chmod(file_path, 0o755)
                except:
                    pass

            # Get form data - sanitize strategy name
            raw_strategy_name = request.form.get("strategy_name", safe_stem)
            # Allow more characters in display name but strip dangerous ones
            strategy_name = raw_strategy_name.strip()[:100]  # Limit length

            # Get mandatory schedule fields with defaults
            schedule_start = request.form.get("schedule_start", "09:00")
            schedule_stop = request.form.get("schedule_stop", "16:00")
            schedule_days_json = request.form.get(
                "schedule_days", '["mon","tue","wed","thu","fri"]'
            )

            # Parse schedule days from JSON
            try:
                schedule_days = json.loads(schedule_days_json)
                if not isinstance(schedule_days, list):
                    schedule_days = ["mon", "tue", "wed", "thu", "fri"]
            except (json.JSONDecodeError, TypeError):
                schedule_days = ["mon", "tue", "wed", "thu", "fri"]

            # Validate schedule fields
            if not schedule_start:
                schedule_start = "09:00"
            if not schedule_stop:
                schedule_stop = "16:00"
            if not schedule_days:
                schedule_days = ["mon", "tue", "wed", "thu", "fri"]

            # Save configuration with schedule (schedule is mandatory and always enabled)
            STRATEGY_CONFIGS[strategy_id] = {
                "name": strategy_name,
                "file_path": str(file_path),
                "file_name": f"{strategy_id}.py",
                "is_running": False,
                "is_scheduled": True,  # Always enabled by default
                "created_at": ist_now.isoformat(),
                "user_id": user_id,
                "schedule_start": schedule_start,
                "schedule_stop": schedule_stop,
                "schedule_days": schedule_days,
            }
            save_configs()

            # Setup scheduler jobs for the new strategy
            schedule_strategy(
                strategy_id, start_time=schedule_start, stop_time=schedule_stop, days=schedule_days
            )

            if is_ajax:
                return jsonify(
                    {
                        "status": "success",
                        "message": f'Strategy "{strategy_name}" uploaded successfully',
                        "data": {"strategy_id": strategy_id},
                    }
                )

            flash(f'Strategy "{strategy_name}" uploaded successfully', "success")
            return redirect(url_for("python_strategy_bp.index"))
        else:
            if is_ajax:
                return jsonify(
                    {"status": "error", "message": "Please upload a Python (.py) file"}
                ), 400
            flash("Please upload a Python (.py) file", "error")

    return render_template("python_strategy/new.html")


@python_strategy_bp.route("/start/<strategy_id>", methods=["POST"])
@check_session_validity
def start_strategy(strategy_id):
    """Start a strategy - requires scheduler to be enabled to prevent API abuse"""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    # Verify ownership
    is_owner, error_response = verify_strategy_ownership(strategy_id, user_id)
    if not is_owner:
        return error_response

    # Check if scheduler is enabled - auto-enable with defaults for old strategies
    config = STRATEGY_CONFIGS.get(strategy_id, {})
    if not config.get("is_scheduled"):
        # Auto-enable scheduler with defaults for old strategies (Mon-Fri, 09:00-16:00 IST)
        logger.info(
            f"Auto-enabling scheduler for legacy strategy {strategy_id} with default schedule"
        )
        config["is_scheduled"] = True
        config["schedule_start"] = config.get("schedule_start", "09:00")
        config["schedule_stop"] = config.get("schedule_stop", "16:00")
        config["schedule_days"] = config.get("schedule_days", ["mon", "tue", "wed", "thu", "fri"])
        STRATEGY_CONFIGS[strategy_id] = config
        save_configs()
        # Setup scheduler jobs for this strategy
        schedule_strategy(
            strategy_id,
            start_time=config.get("schedule_start"),
            stop_time=config.get("schedule_stop"),
            days=config.get("schedule_days"),
        )

    # Clear manual stop flag since user is explicitly starting
    # This resumes scheduled auto-start
    if strategy_id in STRATEGY_CONFIGS and STRATEGY_CONFIGS[strategy_id].get("manually_stopped"):
        STRATEGY_CONFIGS[strategy_id].pop("manually_stopped", None)
        save_configs()
        logger.info(
            f"Cleared manual stop flag for strategy {strategy_id} - scheduled auto-start resumed"
        )

    # Check schedule constraints
    schedule_days = config.get("schedule_days", [])
    now = datetime.now(IST)
    day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    today_day = day_names[now.weekday()]

    schedule_start = config.get("schedule_start")
    schedule_stop = config.get("schedule_stop")

    # Determine if we're within schedule
    is_scheduled_day = today_day in [d.lower() for d in schedule_days] if schedule_days else True
    is_within_hours = True

    if schedule_start and schedule_stop:
        try:
            start_hour, start_min = map(int, schedule_start.split(":"))
            stop_hour, stop_min = map(int, schedule_stop.split(":"))
            start_time = now.replace(hour=start_hour, minute=start_min, second=0, microsecond=0)
            stop_time = now.replace(hour=stop_hour, minute=stop_min, second=0, microsecond=0)
            is_within_hours = start_time <= now <= stop_time
        except (ValueError, AttributeError) as e:
            logger.warning(f"Could not parse schedule times for {strategy_id}: {e}")

    # Check if today is a market holiday (but allow weekends if scheduled)
    is_holiday = not is_trading_day() and now.weekday() < 5

    # If outside schedule (wrong day, wrong time, or holiday), just arm it for scheduled start
    if not is_scheduled_day or not is_within_hours or is_holiday:
        # Determine the reason and next start time
        if is_holiday:
            reason = "Market holiday"
            next_start = f"next trading day at {schedule_start} IST"
        elif not is_scheduled_day:
            reason = f"Today ({today_day.capitalize()}) is not in schedule"
            # Find next scheduled day
            next_days = [d for d in schedule_days]
            next_start = f"next scheduled day ({', '.join(next_days)}) at {schedule_start} IST"
        else:
            reason = f"Outside schedule hours ({schedule_start} - {schedule_stop} IST)"
            if now < start_time:
                next_start = f"today at {schedule_start} IST"
            else:
                next_start = f"next scheduled day at {schedule_start} IST"

        logger.info(
            f"Strategy {strategy_id} armed for scheduled start. Reason: {reason}. Next start: {next_start}"
        )

        return jsonify(
            {
                "status": "success",
                "message": f"Strategy armed for scheduled start. {reason}. Will start {next_start}.",
                "data": {"armed": True, "reason": reason, "next_start": next_start},
            }
        )

    # Within schedule - start immediately
    initialize_with_app_context()
    success, message = start_strategy_process(strategy_id)
    return jsonify({"status": "success" if success else "error", "message": message})


@python_strategy_bp.route("/stop/<strategy_id>", methods=["POST"])
@check_session_validity
def stop_strategy(strategy_id):
    """Stop a strategy manually or cancel a scheduled auto-start"""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    # Verify ownership
    is_owner, error_response = verify_strategy_ownership(strategy_id, user_id)
    if not is_owner:
        return error_response

    config = STRATEGY_CONFIGS.get(strategy_id, {})
    is_running = config.get("is_running", False)

    if is_running:
        # Strategy is actually running - stop the process
        success, message = stop_strategy_process(strategy_id)
        if success and strategy_id in STRATEGY_CONFIGS:
            STRATEGY_CONFIGS[strategy_id]["manually_stopped"] = True
            save_configs()
            logger.info(
                f"Strategy {strategy_id} manually stopped - will not auto-start until manually started"
            )
        return jsonify({"status": "success" if success else "error", "message": message})
    else:
        # Strategy is not running - just cancel the scheduled auto-start
        if strategy_id in STRATEGY_CONFIGS:
            STRATEGY_CONFIGS[strategy_id]["manually_stopped"] = True
            save_configs()
            logger.info(
                f"Strategy {strategy_id} schedule cancelled - will not auto-start until manually started"
            )
            return jsonify({"status": "success", "message": "Scheduled auto-start cancelled"})
        else:
            return jsonify({"status": "error", "message": "Strategy not found"}), 404


@python_strategy_bp.route("/schedule/<strategy_id>", methods=["POST"])
@check_session_validity
def schedule_strategy_route(strategy_id):
    """Schedule a strategy"""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    # Verify ownership and get config atomically
    is_owner, result = verify_strategy_ownership(strategy_id, user_id, return_config=True)
    if not is_owner:
        return result

    config = result
    if config.get("is_running", False):
        return jsonify(
            {
                "status": "error",
                "message": "Cannot modify schedule while strategy is running. Please stop the strategy first.",
                "error_code": "STRATEGY_RUNNING",
            }
        ), 400

    data = request.json
    start_time = data.get("start_time")
    stop_time = data.get("stop_time")
    days = data.get("days", ["mon", "tue", "wed", "thu", "fri"])

    if not start_time:
        return jsonify({"status": "error", "message": "Start time is required"}), 400

    try:
        schedule_strategy(strategy_id, start_time, stop_time, days)
        schedule_info = f"Scheduled at {start_time} IST"
        if stop_time:
            schedule_info += f" - {stop_time} IST"
        return jsonify({"status": "success", "message": schedule_info})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@python_strategy_bp.route("/unschedule/<strategy_id>", methods=["POST"])
@check_session_validity
def unschedule_strategy_route(strategy_id):
    """Remove scheduling for a strategy - DISABLED: scheduler is mandatory"""
    # Scheduler is mandatory and cannot be disabled
    return jsonify(
        {
            "status": "error",
            "message": "Scheduler is mandatory and cannot be disabled. You can only modify the schedule times and days.",
        }
    ), 400


@python_strategy_bp.route("/delete/<strategy_id>", methods=["POST"])
@check_session_validity
def delete_strategy(strategy_id):
    """Delete a strategy"""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    # Verify ownership
    is_owner, error_response = verify_strategy_ownership(strategy_id, user_id)
    if not is_owner:
        return error_response

    with PROCESS_LOCK:  # Thread-safe operation
        # Stop if running
        if strategy_id in RUNNING_STRATEGIES or (
            strategy_id in STRATEGY_CONFIGS and STRATEGY_CONFIGS[strategy_id].get("is_running")
        ):
            stop_strategy_process(strategy_id)

        # Unschedule if scheduled
        if STRATEGY_CONFIGS.get(strategy_id, {}).get("is_scheduled"):
            unschedule_strategy(strategy_id)

        # Delete file
        if strategy_id in STRATEGY_CONFIGS:
            file_path = Path(STRATEGY_CONFIGS[strategy_id].get("file_path", ""))
            if file_path.exists():
                try:
                    file_path.unlink()
                except Exception as e:
                    logger.exception(f"Failed to delete file {file_path}: {e}")

            # Remove from configs
            del STRATEGY_CONFIGS[strategy_id]
            save_configs()

            return jsonify({"status": "success", "message": "Strategy deleted successfully"})

        return jsonify({"status": "error", "message": "Strategy not found"})


@python_strategy_bp.route("/logs/<strategy_id>")
@check_session_validity
def view_logs(strategy_id):
    """View strategy logs"""
    user_id = session.get("user")
    if not user_id:
        flash("Session expired", "error")
        return redirect(url_for("auth.login"))

    # Verify ownership
    is_owner, error_response = verify_strategy_ownership(strategy_id, user_id)
    if not is_owner:
        flash("Unauthorized access to strategy", "error")
        return redirect(url_for("python_strategy_bp.index"))

    log_files = []

    # Get all log files for this strategy
    try:
        for log_file in LOGS_DIR.glob(f"{strategy_id}_*.log"):
            log_files.append(
                {
                    "name": log_file.name,
                    "size": log_file.stat().st_size,
                    "modified": datetime.fromtimestamp(log_file.stat().st_mtime, tz=IST),
                }
            )
    except Exception as e:
        logger.exception(f"Error reading log files: {e}")

    # Sort by modified time (newest first)
    log_files.sort(key=lambda x: x["modified"], reverse=True)

    # Get latest log content if requested
    log_content = None
    if log_files and request.args.get("latest"):
        latest_log = LOGS_DIR / log_files[0]["name"]
        try:
            with open(latest_log, encoding="utf-8", errors="ignore") as f:
                log_content = f.read()
        except Exception as e:
            log_content = f"Error reading log file: {e}"

    return render_template(
        "python_strategy/logs.html",
        strategy_id=strategy_id,
        log_files=log_files,
        log_content=log_content,
    )


@python_strategy_bp.route("/logs/<strategy_id>/clear", methods=["POST"])
@check_session_validity
def clear_logs(strategy_id):
    """Clear all log files for a strategy"""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    # Verify ownership
    is_owner, error_response = verify_strategy_ownership(strategy_id, user_id)
    if not is_owner:
        return error_response

    try:
        # Refuse to clear logs for running strategies to prevent file corruption
        # Truncating a log file while a process has it open causes null bytes
        if strategy_id in RUNNING_STRATEGIES:
            return jsonify(
                {
                    "status": "error",
                    "message": "Cannot clear logs while strategy is running. Please stop the strategy first.",
                }
            ), 400

        cleared_count = 0
        total_size = 0

        # Find all log files for this strategy
        log_files = list(LOGS_DIR.glob(f"{strategy_id}_*.log"))

        if not log_files:
            return jsonify({"status": "error", "message": "No log files found to clear"}), 404

        # Calculate total size before clearing
        for log_file in log_files:
            try:
                total_size += log_file.stat().st_size
            except:
                pass

        # Strategy not running, safe to delete all log files
        for log_file in log_files:
            try:
                log_file.unlink()
                logger.info(f"Deleted log file: {log_file.name}")

                cleared_count += 1

            except Exception as e:
                logger.exception(f"Error clearing log file {log_file.name}: {e}")

        if cleared_count > 0:
            size_mb = total_size / (1024 * 1024)
            logger.info(
                f"Cleared {cleared_count} log files for strategy {strategy_id} ({size_mb:.2f} MB)"
            )
            return jsonify(
                {
                    "status": "success",
                    "message": f"Cleared {cleared_count} log files ({size_mb:.2f} MB)",
                    "cleared_count": cleared_count,
                    "total_size_mb": round(size_mb, 2),
                }
            )
        else:
            return jsonify({"status": "error", "message": "No log files were cleared"}), 500

    except Exception as e:
        logger.exception(f"Error clearing logs for strategy {strategy_id}: {e}")
        return jsonify({"status": "error", "message": f"Error clearing logs: {str(e)}"}), 500


@python_strategy_bp.route("/clear-error/<strategy_id>", methods=["POST"])
@check_session_validity
def clear_error_state(strategy_id):
    """Clear error state for a strategy"""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    # Verify ownership and get config atomically
    is_owner, result = verify_strategy_ownership(strategy_id, user_id, return_config=True)
    if not is_owner:
        return result

    config = result

    if config.get("is_running"):
        return jsonify(
            {"status": "error", "message": "Cannot clear error state while strategy is running"}
        ), 400

    if not config.get("is_error"):
        return jsonify({"status": "error", "message": "Strategy is not in error state"}), 400

    try:
        # Clear error state
        config.pop("is_error", None)
        config.pop("error_message", None)
        config.pop("error_time", None)
        save_configs()

        logger.info(f"Cleared error state for strategy {strategy_id}")
        return jsonify({"status": "success", "message": "Error state cleared successfully"})

    except Exception as e:
        logger.exception(f"Failed to clear error state for {strategy_id}: {e}")
        return jsonify(
            {"status": "error", "message": f"Failed to clear error state: {str(e)}"}
        ), 500


@python_strategy_bp.route("/status")
@check_session_validity
def status():
    """Get system status"""
    cleanup_dead_processes()

    # Check master contract status
    contracts_ready, contract_message = check_master_contract_ready()

    return jsonify(
        {
            "running": len(RUNNING_STRATEGIES),
            "total": len(STRATEGY_CONFIGS),
            "scheduler_running": SCHEDULER is not None and SCHEDULER.running,
            "current_ist_time": get_ist_time().strftime("%H:%M:%S IST"),
            "platform": OS_TYPE,
            # Legacy field names (for backward compatibility)
            "master_contracts_ready": contracts_ready,
            "master_contracts_message": contract_message,
            # Fields expected by React frontend
            "ready": contracts_ready,
            "message": contract_message,
            "strategies": [
                {
                    "id": sid,
                    "name": config.get("name"),
                    "is_running": config.get("is_running", False),
                    "is_scheduled": config.get("is_scheduled", False),
                }
                for sid, config in STRATEGY_CONFIGS.items()
            ],
        }
    )


@python_strategy_bp.route("/check-contracts", methods=["POST"])
@check_session_validity
def check_contracts():
    """Check master contracts and start pending strategies"""
    try:
        success, started_count, message = check_and_start_pending_strategies()
        return jsonify({
            "status": "success" if success else "error",
            "message": message,
            "data": {"started": started_count}
        })
    except Exception as e:
        logger.exception(f"Error checking contracts: {e}")
        return jsonify({
            "status": "error",
            "message": f"Error checking contracts: {str(e)}",
            "data": {"started": 0}
        }), 500


# =============================================================================
# JSON API Endpoints for React Frontend
# =============================================================================


def get_schedule_status(config):
    """
    Determine detailed schedule status for a strategy.
    Returns: (status, status_message)

    Status meanings:
    - manually_stopped: User clicked stop, won't auto-start until manual start
    - scheduled: Strategy is armed and will auto-start at scheduled time
    - paused: Market holiday, strategy won't run today
    """
    now = datetime.now(IST)
    day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    today_day = day_names[now.weekday()]
    current_time = now.strftime("%H:%M")

    schedule_days = config.get("schedule_days", [])
    schedule_start = config.get("schedule_start", "09:00")
    schedule_stop = config.get("schedule_stop", "16:00")
    schedule_days_lower = [d.lower() for d in schedule_days]

    # Check if manually stopped - this is the only state that prevents auto-start
    if config.get("manually_stopped"):
        return "manually_stopped", "Manually stopped - click Start to resume"

    # Check for market holiday (only on weekdays)
    paused_reason = config.get("paused_reason")
    if paused_reason == "holiday":
        return "paused", config.get("paused_message", "Market Holiday")

    # Strategy is armed (not manually stopped) - show "Scheduled" with context
    # Check if today is in schedule days
    if schedule_days and today_day not in schedule_days_lower:
        # Find next scheduled day
        next_days = ", ".join([d.capitalize() for d in schedule_days[:3]])
        if len(schedule_days) > 3:
            next_days += "..."
        return "scheduled", f"Next: {next_days} at {schedule_start} IST"

    # Today is a scheduled day - check time
    if schedule_start and schedule_stop:
        if current_time < schedule_start:
            return "scheduled", f"Starts today at {schedule_start} IST"
        elif current_time > schedule_stop:
            # After today's window, will start next scheduled day
            return "scheduled", f"Next scheduled day at {schedule_start} IST"

    # Within schedule window
    return "scheduled", f"Active window: {schedule_start} - {schedule_stop} IST"


@python_strategy_bp.route("/api/strategies")
@check_session_validity
def api_get_strategies():
    """API: Get all strategies as JSON"""
    cleanup_dead_processes()
    strategies = []

    for strategy_id, config in STRATEGY_CONFIGS.items():
        # Determine status with detailed schedule info
        if config.get("is_running"):
            status = "running"
            status_message = "Running"
        elif config.get("error_message"):
            status = "error"
            status_message = config.get("error_message")
        else:
            status, status_message = get_schedule_status(config)

        strategies.append(
            {
                "id": strategy_id,
                "name": config.get("name", ""),
                "file_name": config.get("file_name", ""),
                "status": status,
                "status_message": status_message,
                "is_running": config.get("is_running", False),
                "is_scheduled": config.get("is_scheduled", False),
                "manually_stopped": config.get("manually_stopped", False),
                "schedule_start_time": config.get("schedule_start"),
                "schedule_stop_time": config.get("schedule_stop"),
                "schedule_days": config.get("schedule_days", []),
                "last_started": config.get("last_started"),
                "last_stopped": config.get("last_stopped"),
                "error_message": config.get("error_message"),
                "paused_reason": config.get("paused_reason"),
                "paused_message": config.get("paused_message"),
                "process_id": config.get("process_id"),
                "created_at": config.get("created_at"),
            }
        )

    return jsonify({"strategies": strategies})


@python_strategy_bp.route("/api/events")
def api_strategy_events():
    """SSE endpoint for real-time strategy status updates"""

    def event_stream():
        # Create a queue for this subscriber
        q = queue.Queue(maxsize=100)

        with SSE_LOCK:
            SSE_SUBSCRIBERS.append(q)

        try:
            # Send initial connection message
            yield 'data: {"type": "connected"}\n\n'

            while True:
                try:
                    # Wait for events with timeout to detect disconnection
                    event = q.get(timeout=30)
                    yield event
                except queue.Empty:
                    # Send heartbeat to keep connection alive
                    yield ": heartbeat\n\n"
        except GeneratorExit:
            pass
        finally:
            # Remove subscriber on disconnect
            with SSE_LOCK:
                if q in SSE_SUBSCRIBERS:
                    SSE_SUBSCRIBERS.remove(q)

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@python_strategy_bp.route("/api/strategy/<strategy_id>")
@check_session_validity
def api_get_strategy(strategy_id):
    """API: Get single strategy as JSON"""
    if strategy_id not in STRATEGY_CONFIGS:
        return jsonify({"status": "error", "message": "Strategy not found"}), 404

    config = STRATEGY_CONFIGS[strategy_id]

    # Determine status with detailed schedule info
    if config.get("is_running"):
        status = "running"
        status_message = "Running"
    elif config.get("error_message"):
        status = "error"
        status_message = config.get("error_message")
    else:
        status, status_message = get_schedule_status(config)

    return jsonify(
        {
            "strategy": {
                "id": strategy_id,
                "status_message": status_message,
                "manually_stopped": config.get("manually_stopped", False),
                "name": config.get("name", ""),
                "file_name": config.get("file_name", ""),
                "status": status,
                "is_running": config.get("is_running", False),
                "is_scheduled": config.get("is_scheduled", False),
                "schedule_start_time": config.get("schedule_start"),
                "schedule_stop_time": config.get("schedule_stop"),
                "schedule_days": config.get("schedule_days", []),
                "last_started": config.get("last_started"),
                "last_stopped": config.get("last_stopped"),
                "error_message": config.get("error_message"),
                "paused_reason": config.get("paused_reason"),
                "paused_message": config.get("paused_message"),
                "process_id": config.get("process_id"),
                "created_at": config.get("created_at"),
            }
        }
    )


@python_strategy_bp.route("/api/strategy/<strategy_id>/content")
@check_session_validity
def api_get_strategy_content(strategy_id):
    """API: Get strategy file content"""
    if strategy_id not in STRATEGY_CONFIGS:
        return jsonify({"status": "error", "message": "Strategy not found"}), 404

    config = STRATEGY_CONFIGS[strategy_id]
    file_name = config.get("file_name")
    file_path = config.get("file_path")

    # Try file_name first, fall back to file_path
    if file_name:
        strategy_path = STRATEGIES_DIR / file_name
    elif file_path:
        strategy_path = Path(file_path)
        file_name = strategy_path.name
    else:
        return jsonify({"status": "error", "message": "Strategy file not found"}), 404

    if not strategy_path.exists():
        return jsonify({"status": "error", "message": "Strategy file not found on disk"}), 404

    try:
        content = strategy_path.read_text(encoding="utf-8")
        file_stats = strategy_path.stat()
        return jsonify(
            {
                "name": config.get("name", ""),
                "file_name": file_name,
                "content": content,
                "is_running": config.get("is_running", False),
                "line_count": content.count("\n") + 1,
                "size_kb": file_stats.st_size / 1024,
                "last_modified": datetime.fromtimestamp(file_stats.st_mtime, tz=IST).isoformat(),
            }
        )
    except Exception as e:
        logger.exception(f"Error reading strategy file: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@python_strategy_bp.route("/api/logs/<strategy_id>")
@check_session_validity
def api_get_log_files(strategy_id):
    """API: Get list of log files for a strategy"""
    # Basic validation - reject path traversal attempts
    if not strategy_id or ".." in strategy_id or "/" in strategy_id or "\\" in strategy_id:
        return jsonify({"status": "error", "message": "Invalid strategy ID"}), 400

    if strategy_id not in STRATEGY_CONFIGS:
        return jsonify({"status": "error", "message": "Strategy not found"}), 404

    # Logs are stored flat in LOGS_DIR with pattern: {strategy_id}_*.log
    logs = []
    try:
        for log_file in sorted(
            LOGS_DIR.glob(f"{strategy_id}_*.log"), key=lambda x: x.stat().st_mtime, reverse=True
        ):
            stats = log_file.stat()
            logs.append(
                {
                    "name": log_file.name,
                    "size_kb": stats.st_size / 1024,
                    "last_modified": datetime.fromtimestamp(stats.st_mtime, tz=IST).isoformat(),
                }
            )
    except Exception as e:
        logger.exception(f"Error listing log files for {strategy_id}: {e}")

    return jsonify({"logs": logs})


@python_strategy_bp.route("/api/logs/<strategy_id>/<log_name>")
@check_session_validity
def api_get_log_content(strategy_id, log_name):
    """API: Get log file content"""
    # Basic validation - reject path traversal attempts
    if not strategy_id or ".." in strategy_id or "/" in strategy_id or "\\" in strategy_id:
        return jsonify({"status": "error", "message": "Invalid strategy ID"}), 400

    if strategy_id not in STRATEGY_CONFIGS:
        return jsonify({"status": "error", "message": "Strategy not found"}), 404

    # Validate log_name - reject path traversal attempts
    if not log_name or ".." in log_name or "/" in log_name or "\\" in log_name:
        return jsonify({"status": "error", "message": "Invalid log file name"}), 400

    # Verify the log file belongs to this strategy (must start with strategy_id)
    if not log_name.startswith(f"{strategy_id}_"):
        return jsonify(
            {"status": "error", "message": "Log file does not belong to this strategy"}
        ), 403

    # Logs are stored flat in LOGS_DIR (not in subdirectories)
    log_path = LOGS_DIR / log_name

    # Ensure the resolved path is still within LOGS_DIR (defense in depth)
    try:
        resolved_path = log_path.resolve()
        logs_dir_resolved = LOGS_DIR.resolve()
        if not str(resolved_path).startswith(str(logs_dir_resolved)):
            logger.warning(f"Path traversal attempt detected: {log_name}")
            return jsonify({"status": "error", "message": "Invalid log file path"}), 403
    except Exception as e:
        logger.exception(f"Error resolving log path: {e}")
        return jsonify({"status": "error", "message": "Invalid log file path"}), 400

    if not log_path.exists():
        return jsonify({"status": "error", "message": "Log file not found"}), 404

    try:
        content = log_path.read_text(encoding="utf-8", errors="replace")
        stats = log_path.stat()
        line_count = content.count("\n") + 1 if content else 0
        return jsonify(
            {
                "name": log_name,
                "content": content,
                "lines": line_count,
                "size_kb": stats.st_size / 1024,
                "last_updated": datetime.fromtimestamp(stats.st_mtime, tz=IST).isoformat(),
            }
        )
    except Exception as e:
        logger.exception(f"Error reading log file: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@python_strategy_bp.route("/edit/<strategy_id>")
@check_session_validity
def edit_strategy(strategy_id):
    """Edit or view a strategy file"""
    user_id = session.get("user")
    if not user_id:
        flash("Session expired", "error")
        return redirect(url_for("auth.login"))

    # Verify ownership
    is_owner, error_response = verify_strategy_ownership(strategy_id, user_id)
    if not is_owner:
        flash("Unauthorized access to strategy", "error")
        return redirect(url_for("python_strategy_bp.index"))

    config = STRATEGY_CONFIGS[strategy_id]
    file_path = Path(config["file_path"])

    if not file_path.exists():
        flash("Strategy file not found", "error")
        return redirect(url_for("python_strategy_bp.index"))

    # Check if strategy is running
    is_running = config.get("is_running", False)

    # Read file content
    try:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        flash(f"Error reading file: {e}", "error")
        return redirect(url_for("python_strategy_bp.index"))

    # Get file info
    file_stats = file_path.stat()
    file_info = {
        "name": file_path.name,
        "size": file_stats.st_size,
        "modified": datetime.fromtimestamp(file_stats.st_mtime, tz=IST),
        "lines": content.count("\n") + 1,
    }

    return render_template(
        "python_strategy/edit.html",
        strategy_id=strategy_id,
        strategy_name=config.get("name", "Unnamed Strategy"),
        content=content,
        is_running=is_running,
        file_info=file_info,
        can_edit=not is_running,
    )


@python_strategy_bp.route("/export/<strategy_id>")
@check_session_validity
def export_strategy(strategy_id):
    """Export/download a strategy file"""
    user_id = session.get("user")
    if not user_id:
        flash("Session expired", "error")
        return redirect(url_for("auth.login"))

    # Verify ownership
    is_owner, error_response = verify_strategy_ownership(strategy_id, user_id)
    if not is_owner:
        flash("Unauthorized access to strategy", "error")
        return redirect(url_for("python_strategy_bp.index"))

    config = STRATEGY_CONFIGS[strategy_id]
    file_path = Path(config["file_path"])

    if not file_path.exists():
        flash("Strategy file not found", "error")
        return redirect(url_for("python_strategy_bp.index"))

    try:
        # Read the file content
        with open(file_path, encoding="utf-8") as f:
            content = f.read()

        # Create response with file download
        from flask import Response

        response = Response(
            content,
            mimetype="text/x-python",
            headers={
                "Content-Disposition": f"attachment; filename={file_path.name}",
                "Content-Type": "text/x-python; charset=utf-8",
            },
        )

        logger.info(f"Strategy {strategy_id} exported successfully")
        return response

    except Exception as e:
        logger.exception(f"Failed to export strategy {strategy_id}: {e}")
        flash(f"Failed to export strategy: {str(e)}", "error")
        return redirect(url_for("python_strategy_bp.index"))


@python_strategy_bp.route("/save/<strategy_id>", methods=["POST"])
@check_session_validity
def save_strategy(strategy_id):
    """Save edited strategy file"""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    # Verify ownership and get config atomically
    is_owner, result = verify_strategy_ownership(strategy_id, user_id, return_config=True)
    if not is_owner:
        return result

    config = result

    # Check if strategy is running
    if config.get("is_running", False):
        return jsonify(
            {"status": "error", "message": "Cannot edit running strategy. Please stop it first."}
        ), 400

    file_path = Path(config["file_path"])

    # Get new content
    data = request.get_json()
    if not data or "content" not in data:
        return jsonify({"status": "error", "message": "No content provided"}), 400

    new_content = data["content"]

    try:
        # Create backup
        backup_path = file_path.with_suffix(".bak")
        if file_path.exists():
            with open(file_path, encoding="utf-8") as f:
                backup_content = f.read()
            with open(backup_path, "w", encoding="utf-8") as f:
                f.write(backup_content)

        # Save new content
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        # Update config
        config["last_modified"] = get_ist_time().isoformat()
        save_configs()

        logger.info(f"Strategy {strategy_id} saved successfully")
        return jsonify(
            {
                "status": "success",
                "message": "Strategy saved successfully",
                "timestamp": format_ist_time(config["last_modified"]),
            }
        )

    except Exception as e:
        logger.exception(f"Failed to save strategy {strategy_id}: {e}")
        return jsonify({"status": "error", "message": f"Failed to save: {str(e)}"}), 500


# Cleanup on shutdown
def cleanup_on_exit():
    """Clean up all running processes on application exit"""
    logger.info("Cleaning up running strategies...")
    with PROCESS_LOCK:
        for strategy_id in list(RUNNING_STRATEGIES.keys()):
            try:
                stop_strategy_process(strategy_id)
            except:
                pass
    logger.info("Cleanup complete")


# Register cleanup handler
import atexit

atexit.register(cleanup_on_exit)


def restore_strategy_states():
    """Restore strategy states on startup - restart running strategies or mark as error"""
    logger.info("Restoring strategy states from previous session...")

    # During startup, we need to be more lenient with master contract checks
    # since the session might not be fully initialized yet
    contracts_ready, contract_message = check_master_contract_ready(skip_on_startup=False)

    # If we can't determine the broker (no active auth), delay strategy restoration
    if "No broker" in contract_message:
        logger.info("No active broker found during startup - delaying strategy restoration")
        # Don't mark as error yet, wait for proper session initialization
        return

    if not contracts_ready:
        logger.warning(
            f"Master contracts not ready - strategies will remain in error state until contracts are downloaded: {contract_message}"
        )
        # Mark all running strategies as error state due to master contract dependency
        for strategy_id, config in STRATEGY_CONFIGS.items():
            if config.get("is_running"):
                config["is_running"] = False
                config["is_error"] = True
                config["error_message"] = "Waiting for master contracts to be downloaded"
                config["error_time"] = get_ist_time().isoformat()
                config["pid"] = None
        save_configs()
        return

    restored_count = 0
    error_count = 0
    cleaned_count = 0

    for strategy_id, config in STRATEGY_CONFIGS.items():
        if config.get("is_running") and config.get("pid"):
            pid = config.get("pid")
            strategy_restored = False

            try:
                # Check if process is still running
                if psutil.pid_exists(pid):
                    process = psutil.Process(pid)

                    # Check if it's actually our strategy process
                    cmdline = " ".join(process.cmdline())
                    strategy_file = config.get("file_path", "")

                    if strategy_file and strategy_file in cmdline:
                        # Process is still running, restore it to RUNNING_STRATEGIES
                        ist_now = get_ist_time()

                        # Find the current log file
                        log_pattern = f"{strategy_id}_*_IST.log"
                        log_files = list(LOGS_DIR.glob(log_pattern))
                        current_log = (
                            max(log_files, key=lambda f: f.stat().st_mtime) if log_files else None
                        )

                        RUNNING_STRATEGIES[strategy_id] = {
                            "process": process,
                            "pid": pid,
                            "started_at": datetime.fromisoformat(
                                config.get("last_started", ist_now.isoformat())
                            ),
                            "log_file": str(current_log) if current_log else None,
                            "log_handle": None,  # We can't restore the file handle
                        }

                        logger.info(f"Restored running strategy {strategy_id} (PID: {pid})")
                        restored_count += 1
                        strategy_restored = True
                    else:
                        logger.debug(f"PID {pid} exists but not our strategy process")

            except psutil.NoSuchProcess:
                logger.debug(f"Process {pid} for strategy {strategy_id} no longer exists")
            except Exception as e:
                logger.exception(f"Error checking process {pid} for strategy {strategy_id}: {e}")

            # If strategy wasn't restored, try to restart it automatically
            if not strategy_restored:
                logger.info(f"Attempting to restart strategy {strategy_id}...")
                try:
                    success, message = start_strategy_process(strategy_id)
                    if success:
                        logger.info(f"Successfully restarted strategy {strategy_id}")
                        restored_count += 1
                    else:
                        # Mark as error state
                        config["is_running"] = False
                        config["is_error"] = True
                        config["error_message"] = f"Failed to restart: {message}"
                        config["error_time"] = get_ist_time().isoformat()
                        config["pid"] = None
                        logger.error(f"Failed to restart strategy {strategy_id}: {message}")
                        error_count += 1
                except Exception as e:
                    # Mark as error state
                    config["is_running"] = False
                    config["is_error"] = True
                    config["error_message"] = f"Restart exception: {str(e)}"
                    config["error_time"] = get_ist_time().isoformat()
                    config["pid"] = None
                    logger.exception(f"Exception restarting strategy {strategy_id}: {e}")
                    error_count += 1

        # Clear error state for strategies that are not marked as running
        elif config.get("is_error") and not config.get("is_running"):
            # Keep error state until user manually clears it
            pass

    if restored_count > 0 or error_count > 0:
        save_configs()
        logger.info(
            f"State restoration complete: {restored_count} restored, {error_count} in error state"
        )
    else:
        logger.info("No strategies needed state restoration")


def check_and_start_pending_strategies():
    """Check if master contracts are ready and start strategies that were waiting

    Returns:
        tuple: (success: bool, started_count: int, message: str)
    """
    contracts_ready, contract_message = check_master_contract_ready()
    if not contracts_ready:
        return False, 0, contract_message

    started_count = 0
    failed_count = 0

    # Look for strategies that are in error state due to master contract dependency
    for strategy_id, config in STRATEGY_CONFIGS.items():
        if config.get("is_error") and (
            "Waiting for master contracts" in config.get("error_message", "")
            or "Master contract dependency not met" in config.get("error_message", "")
        ):
            logger.info(
                f"Attempting to start strategy {strategy_id} after master contract became ready"
            )

            # Clear error state and try to start
            config.pop("is_error", None)
            config.pop("error_message", None)
            config.pop("error_time", None)

            success, message = start_strategy_process(strategy_id)
            if success:
                started_count += 1
                logger.info(
                    f"Successfully started strategy {strategy_id} after master contract ready"
                )
            else:
                failed_count += 1
                logger.error(
                    f"Failed to start strategy {strategy_id} even after master contract ready: {message}"
                )

    if started_count > 0 or failed_count > 0:
        save_configs()
        return True, started_count, f"Started {started_count} strategies, {failed_count} failed"

    return True, 0, "No pending strategies to start"


def restore_strategies_after_login():
    """Called after successful login to restore strategies that were waiting"""
    logger.info("Checking for strategies to restore after login...")

    # Re-run restore_strategy_states now that we have a proper session
    restore_strategy_states()

    # Then check and start any pending strategies
    success, started_count, message = check_and_start_pending_strategies()
    logger.info(f"Post-login strategy restoration: {message} (started: {started_count})")
    return success, message


# Initialize basic components on import (no database access)
ensure_directories()
load_configs()
init_scheduler()

# Flag to track if full initialization has been done
_initialized = False


def initialize_with_app_context():
    """Initialize components that require app context/database access"""
    global _initialized
    if _initialized:
        return
    _initialized = True

    try:
        # Now safe to restore strategy states (requires database)
        restore_strategy_states()

        # Restore scheduled strategies
        restored_schedules = 0
        for strategy_id, config in STRATEGY_CONFIGS.items():
            if config.get("is_scheduled"):
                start_time = config.get("schedule_start")
                stop_time = config.get("schedule_stop")
                days = config.get("schedule_days", ["mon", "tue", "wed", "thu", "fri"])
                if start_time:
                    try:
                        schedule_strategy(strategy_id, start_time, stop_time, days)
                        logger.debug(
                            f"Restored schedule for strategy {strategy_id} at {start_time} IST"
                        )
                        restored_schedules += 1
                    except Exception as e:
                        logger.exception(f"Failed to restore schedule for {strategy_id}: {e}")

        if restored_schedules > 0:
            logger.info(f"Restored {restored_schedules} scheduled strategies")

        # Run immediate trading day check on startup
        # This stops any scheduled strategies if app starts on a weekend/holiday
        daily_trading_day_check()

        logger.info(f"Python Strategy System fully initialized on {OS_TYPE}")
    except Exception as e:
        logger.warning(f"Deferred initialization skipped (likely no app context yet): {e}")
        _initialized = False  # Reset flag to retry later


# Note: Flask removed before_app_first_request in newer versions
# The initialization is now handled in the index route and other entry points

logger.debug(f"Python Strategy System initialized (basic) on {OS_TYPE}")
