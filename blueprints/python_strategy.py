"""
Python Strategy Hosting System - Cross-Platform Process Isolation with IST Support
Route: /python
Features: Upload, Start, Stop, Schedule, Delete strategies
Supports: Windows, Linux, macOS
Note: Each strategy runs in a separate process for complete isolation
"""

from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, session
import os
import subprocess
import psutil
import logging
from datetime import datetime, time
from pathlib import Path
from werkzeug.utils import secure_filename
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import signal
import sys
import json
import pytz
import platform
import threading
from cryptography.fernet import Fernet
import base64
import hashlib

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create blueprint with /python route
python_strategy_bp = Blueprint('python_strategy_bp', __name__, url_prefix='/python')

# Global storage with thread locks for safety
RUNNING_STRATEGIES = {}  # {strategy_id: {'process': subprocess.Popen, 'started_at': datetime}}
STRATEGY_CONFIGS = {}    # {strategy_id: config_dict}
SCHEDULER = None
PROCESS_LOCK = threading.Lock()  # Thread lock for process operations

# Timezone configuration - Indian Standard Time
IST = pytz.timezone('Asia/Kolkata')

# File paths - use Path for cross-platform compatibility
STRATEGIES_DIR = Path('strategies') / 'scripts'
LOGS_DIR = Path('log') / 'strategies'  # Using existing log folder
CONFIG_FILE = Path('strategies') / 'strategy_configs.json'
ENV_FILE = Path('strategies') / 'strategy_env.json'  # Environment variables storage
SECURE_ENV_FILE = Path('strategies') / '.secure_env'  # Encrypted sensitive variables

# Detect operating system
OS_TYPE = platform.system().lower()  # 'windows', 'linux', 'darwin'
IS_WINDOWS = OS_TYPE == 'windows'
IS_MAC = OS_TYPE == 'darwin'
IS_LINUX = OS_TYPE == 'linux'

def init_scheduler():
    """Initialize the APScheduler with IST timezone"""
    global SCHEDULER
    if SCHEDULER is None:
        SCHEDULER = BackgroundScheduler(daemon=True, timezone=IST)
        SCHEDULER.start()
        logger.info(f"Scheduler initialized with IST timezone on {OS_TYPE}")

def load_configs():
    """Load strategy configurations from file"""
    global STRATEGY_CONFIGS
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                STRATEGY_CONFIGS = json.load(f)
            logger.info(f"Loaded {len(STRATEGY_CONFIGS)} strategy configurations")
        except Exception as e:
            logger.error(f"Failed to load configs: {e}")
            STRATEGY_CONFIGS = {}

def save_configs():
    """Save strategy configurations to file"""
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(STRATEGY_CONFIGS, f, indent=2, default=str, ensure_ascii=False)
        logger.info("Configurations saved")
    except Exception as e:
        logger.error(f"Failed to save configs: {e}")

def ensure_directories():
    """Ensure all required directories exist"""
    global STRATEGIES_DIR, LOGS_DIR
    try:
        STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        logger.info(f"Directories initialized on {OS_TYPE}")
    except PermissionError as e:
        # If we can't create directories, check if they exist
        if STRATEGIES_DIR.exists() and LOGS_DIR.exists():
            logger.warning(f"Directories exist but no write permission: {e}")
        else:
            # Try alternative paths in /tmp if main paths fail
            import tempfile
            temp_base = Path(tempfile.gettempdir()) / 'openalgo'
            STRATEGIES_DIR = temp_base / 'strategies' / 'scripts'
            LOGS_DIR = temp_base / 'log' / 'strategies'
            STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            logger.warning(f"Using temporary directories due to permission issues: {temp_base}")
    except Exception as e:
        logger.error(f"Failed to create directories: {e}")
        # Continue anyway, individual operations will handle missing directories

def get_or_create_encryption_key():
    """Get or create encryption key for sensitive data"""
    # Store in secure location in keys folder
    key_file = Path('keys') / '.encryption_key'
    
    if key_file.exists():
        with open(key_file, 'rb') as f:
            return f.read()
    else:
        # Generate new key
        key = Fernet.generate_key()
        key_file.parent.mkdir(parents=True, exist_ok=True)
        with open(key_file, 'wb') as f:
            f.write(key)
        # Set restrictive permissions
        if not IS_WINDOWS:
            os.chmod(key_file, 0o600)
        return key

# Initialize encryption
ENCRYPTION_KEY = get_or_create_encryption_key()
CIPHER_SUITE = Fernet(ENCRYPTION_KEY)

def load_env_variables(strategy_id):
    """Load environment variables for a strategy"""
    env_vars = {}
    
    # Load regular environment variables
    if ENV_FILE.exists():
        try:
            with open(ENV_FILE, 'r', encoding='utf-8') as f:
                all_env = json.load(f)
                env_vars.update(all_env.get(strategy_id, {}))
        except Exception as e:
            logger.error(f"Failed to load env variables: {e}")
    
    # Load secure environment variables
    if SECURE_ENV_FILE.exists():
        try:
            with open(SECURE_ENV_FILE, 'rb') as f:
                encrypted_data = f.read()
                decrypted_data = CIPHER_SUITE.decrypt(encrypted_data)
                secure_env = json.loads(decrypted_data.decode('utf-8'))
                env_vars.update(secure_env.get(strategy_id, {}))
        except Exception as e:
            logger.error(f"Failed to load secure env variables: {e}")
    
    return env_vars

def save_env_variables(strategy_id, regular_vars, secure_vars=None):
    """Save environment variables for a strategy"""
    # Save regular variables
    all_env = {}
    if ENV_FILE.exists():
        try:
            with open(ENV_FILE, 'r', encoding='utf-8') as f:
                all_env = json.load(f)
        except:
            pass
    
    all_env[strategy_id] = regular_vars
    
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(ENV_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_env, f, indent=2)
    
    # Save secure variables if provided
    if secure_vars is not None:
        all_secure = {}
        if SECURE_ENV_FILE.exists():
            try:
                with open(SECURE_ENV_FILE, 'rb') as f:
                    encrypted_data = f.read()
                    decrypted_data = CIPHER_SUITE.decrypt(encrypted_data)
                    all_secure = json.loads(decrypted_data.decode('utf-8'))
            except:
                pass
        
        # Merge new secure vars with existing ones (only update those provided)
        if strategy_id not in all_secure:
            all_secure[strategy_id] = {}
        
        # Update only the provided secure variables, keep existing ones
        all_secure[strategy_id].update(secure_vars)
        
        # Encrypt and save
        encrypted_data = CIPHER_SUITE.encrypt(json.dumps(all_secure).encode('utf-8'))
        with open(SECURE_ENV_FILE, 'wb') as f:
            f.write(encrypted_data)
        
        # Set restrictive permissions
        if not IS_WINDOWS:
            os.chmod(SECURE_ENV_FILE, 0o600)

def get_active_broker():
    """Get the active broker from database (last logged in user's broker)"""
    try:
        from database.auth_db import Auth
        from sqlalchemy import desc
        
        # Get the most recent auth entry (last logged in user)
        auth_obj = Auth.query.filter_by(is_revoked=False).order_by(desc(Auth.id)).first()
        if auth_obj:
            return auth_obj.broker
        return None
    except Exception as e:
        logger.error(f"Error getting active broker: {e}")
        return None

def check_master_contract_ready(skip_on_startup=False):
    """Check if master contracts are ready for the current broker"""
    try:
        # First try to get broker from session (if available)
        broker = session.get('broker') if session else None
        
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
        logger.error(f"Error checking master contract readiness: {e}")
        return False, f"Error checking master contract readiness: {str(e)}"

def get_ist_time():
    """Get current IST time"""
    return datetime.now(IST)

def format_ist_time(dt):
    """Format datetime to IST string"""
    if dt:
        if isinstance(dt, str):
            try:
                dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
            except:
                return dt
        if not dt.tzinfo:
            dt = IST.localize(dt)
        else:
            dt = dt.astimezone(IST)
        return dt.strftime('%Y-%m-%d %H:%M:%S IST')
    return ''

def get_python_executable():
    """Get the correct Python executable for the current OS"""
    # Use sys.executable which works across all platforms
    return sys.executable

def create_subprocess_args():
    """Create platform-specific subprocess arguments"""
    args = {
        'stdout': subprocess.PIPE,
        'stderr': subprocess.STDOUT,
        'universal_newlines': False,  # Handle bytes for better compatibility
        'bufsize': 1,  # Line buffered
    }
    
    if IS_WINDOWS:
        # Windows-specific: CREATE_NEW_PROCESS_GROUP for better process isolation
        args['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
        # Prevent console window popup
        args['startupinfo'] = subprocess.STARTUPINFO()
        args['startupinfo'].dwFlags |= subprocess.STARTF_USESHOWWINDOW
    else:
        # Unix-like systems (Linux, macOS)
        # Try to create new session for better process control
        # But don't use preexec_fn as it can fail in restricted environments
        try:
            args['start_new_session'] = True  # Create new process group
            # Note: Removed preexec_fn = os.setsid as it can cause issues in some environments
            # start_new_session already creates a new session group which is sufficient
        except Exception as e:
            logger.warning(f"Could not set start_new_session: {e}")
            # Continue without session isolation - process will still work
    
    return args

def start_strategy_process(strategy_id):
    """Start a strategy in a new process - cross-platform implementation"""
    with PROCESS_LOCK:  # Thread-safe operation
        if strategy_id in RUNNING_STRATEGIES:
            return False, "Strategy already running"
        
        config = STRATEGY_CONFIGS.get(strategy_id)
        if not config:
            return False, "Strategy configuration not found"
        
        file_path = Path(config['file_path'])
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
                logger.warning(f"Strategy file {file_path} is not executable. Setting execute permission.")
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
                return False, f"Log directory is not writable. Check permissions for {log_file.parent}"
            
            # Open log file for writing
            try:
                log_handle = open(log_file, 'w', encoding='utf-8', buffering=1)
            except PermissionError as e:
                logger.error(f"Permission denied creating log file: {e}")
                return False, f"Permission denied creating log file. Check directory permissions."
            except Exception as e:
                logger.error(f"Error creating log file: {e}")
                return False, f"Error creating log file: {str(e)}"
            
            # Write header with IST time
            log_handle.write(f"=== Strategy Started at {ist_now.strftime('%Y-%m-%d %H:%M:%S IST')} ===\n")
            log_handle.write(f"=== Platform: {OS_TYPE} ===\n\n")
            log_handle.flush()
            
            # Get platform-specific subprocess arguments
            subprocess_args = create_subprocess_args()
            subprocess_args['stdout'] = log_handle
            subprocess_args['stderr'] = subprocess.STDOUT
            subprocess_args['cwd'] = str(Path.cwd())
            
            # Load and set environment variables
            env_vars = load_env_variables(strategy_id)
            if env_vars:
                # Start with current environment
                process_env = os.environ.copy()
                # Add strategy-specific environment variables
                process_env.update(env_vars)
                subprocess_args['env'] = process_env
                logger.info(f"Loaded {len(env_vars)} environment variables for strategy {strategy_id}")
            
            # Start the process
            # Use Python unbuffered mode for real-time output
            cmd = [get_python_executable(), '-u', str(file_path.absolute())]
            
            # Log the command being executed for debugging
            logger.info(f"Executing command: {' '.join(cmd)}")
            logger.debug(f"Working directory: {subprocess_args.get('cwd', 'current')}")
            
            try:
                process = subprocess.Popen(cmd, **subprocess_args)
            except PermissionError as e:
                log_handle.close()
                logger.error(f"Permission denied executing strategy: {e}")
                return False, f"Permission denied. Check file permissions and Python executable access."
            except OSError as e:
                log_handle.close()
                if "preexec_fn" in str(e):
                    logger.error(f"Process isolation error: {e}")
                    return False, "Process isolation failed. This is a known issue that has been fixed. Please restart the application."
                else:
                    logger.error(f"OS error starting process: {e}")
                    return False, f"OS error: {str(e)}"
            except Exception as e:
                log_handle.close()
                logger.error(f"Unexpected error starting process: {e}")
                return False, f"Failed to start process: {str(e)}"
            
            # Store process info
            RUNNING_STRATEGIES[strategy_id] = {
                'process': process,
                'pid': process.pid,
                'started_at': ist_now,
                'log_file': str(log_file),
                'log_handle': log_handle  # Keep file handle open
            }
            
            # Update config with IST time
            STRATEGY_CONFIGS[strategy_id]['is_running'] = True
            STRATEGY_CONFIGS[strategy_id]['last_started'] = ist_now.isoformat()
            STRATEGY_CONFIGS[strategy_id]['pid'] = process.pid
            # Clear any previous error state
            STRATEGY_CONFIGS[strategy_id].pop('is_error', None)
            STRATEGY_CONFIGS[strategy_id].pop('error_message', None)
            STRATEGY_CONFIGS[strategy_id].pop('error_time', None)
            save_configs()
            
            logger.info(f"Started strategy {strategy_id} with PID {process.pid} at {ist_now.strftime('%H:%M:%S IST')} on {OS_TYPE}")
            return True, f"Strategy started with PID {process.pid} at {ist_now.strftime('%H:%M:%S IST')}"
            
        except Exception as e:
            logger.error(f"Failed to start strategy {strategy_id}: {e}")
            return False, f"Failed to start strategy: {str(e)}"

def stop_strategy_process(strategy_id):
    """Stop a running strategy process - cross-platform implementation"""
    with PROCESS_LOCK:  # Thread-safe operation
        if strategy_id not in RUNNING_STRATEGIES:
            # Check if process is still running by PID
            if strategy_id in STRATEGY_CONFIGS:
                pid = STRATEGY_CONFIGS[strategy_id].get('pid')
                if pid and check_process_status(pid):
                    try:
                        terminate_process_cross_platform(pid)
                        STRATEGY_CONFIGS[strategy_id]['is_running'] = False
                        STRATEGY_CONFIGS[strategy_id]['pid'] = None
                        STRATEGY_CONFIGS[strategy_id]['last_stopped'] = get_ist_time().isoformat()
                        save_configs()
                        return True, "Strategy stopped"
                    except:
                        pass
            return False, "Strategy not running"
        
        try:
            strategy_info = RUNNING_STRATEGIES[strategy_id]
            process = strategy_info['process']
            pid = strategy_info['pid']
            
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
                        subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)], 
                                     capture_output=True, check=False)
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
            elif hasattr(process, 'terminate'):
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
            
            # Close log file handle
            if 'log_handle' in strategy_info and strategy_info['log_handle']:
                try:
                    strategy_info['log_handle'].close()
                except:
                    pass
            
            # Remove from running strategies
            del RUNNING_STRATEGIES[strategy_id]
            
            # Update config with IST time
            ist_now = get_ist_time()
            STRATEGY_CONFIGS[strategy_id]['is_running'] = False
            STRATEGY_CONFIGS[strategy_id]['last_stopped'] = ist_now.isoformat()
            STRATEGY_CONFIGS[strategy_id]['pid'] = None
            save_configs()
            
            logger.info(f"Stopped strategy {strategy_id} at {ist_now.strftime('%H:%M:%S IST')}")
            return True, f"Strategy stopped at {ist_now.strftime('%H:%M:%S IST')}"
            
        except Exception as e:
            logger.error(f"Failed to stop strategy {strategy_id}: {e}")
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
        logger.error(f"Error terminating process {pid}: {e}")

def check_process_status(pid):
    """Check if a process is still running - cross-platform"""
    try:
        if psutil.pid_exists(pid):
            process = psutil.Process(pid)
            return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return False

def cleanup_dead_processes():
    """Clean up strategies with dead processes"""
    with PROCESS_LOCK:  # Thread-safe operation
        dead_strategies = []
        
        for strategy_id, info in list(RUNNING_STRATEGIES.items()):
            process = info['process']
            is_dead = False
            
            # Check if process has terminated based on its type
            if isinstance(process, subprocess.Popen):
                # For subprocess.Popen objects
                if process.poll() is not None:
                    is_dead = True
            elif hasattr(process, 'is_running'):
                # For psutil.Process objects
                try:
                    if not process.is_running():
                        is_dead = True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    is_dead = True
            else:
                # Fallback: try to check if process exists by PID
                try:
                    pid = info.get('pid')
                    if pid and not psutil.pid_exists(pid):
                        is_dead = True
                except:
                    is_dead = True
            
            if is_dead:
                dead_strategies.append(strategy_id)
                # Close log file handle
                if 'log_handle' in info and info['log_handle']:
                    try:
                        info['log_handle'].close()
                    except:
                        pass
        
        for strategy_id in dead_strategies:
            del RUNNING_STRATEGIES[strategy_id]
            if strategy_id in STRATEGY_CONFIGS:
                STRATEGY_CONFIGS[strategy_id]['is_running'] = False
                STRATEGY_CONFIGS[strategy_id]['pid'] = None
        
        if dead_strategies:
            save_configs()
            logger.info(f"Cleaned up {len(dead_strategies)} dead processes")

def schedule_strategy(strategy_id, start_time, stop_time=None, days=None):
    """Schedule a strategy to run at specific times (IST)"""
    if not days:
        days = ['mon', 'tue', 'wed', 'thu', 'fri']  # Default to weekdays
    
    # Create job ID
    start_job_id = f"start_{strategy_id}"
    stop_job_id = f"stop_{strategy_id}"
    
    # Remove existing jobs if any
    if SCHEDULER.get_job(start_job_id):
        SCHEDULER.remove_job(start_job_id)
    if SCHEDULER.get_job(stop_job_id):
        SCHEDULER.remove_job(stop_job_id)
    
    # Schedule start (time is already in IST from frontend)
    hour, minute = map(int, start_time.split(':'))
    SCHEDULER.add_job(
        func=lambda: start_strategy_process(strategy_id),
        trigger=CronTrigger(hour=hour, minute=minute, day_of_week=','.join(days), timezone=IST),
        id=start_job_id,
        replace_existing=True
    )
    
    # Schedule stop if provided
    if stop_time:
        hour, minute = map(int, stop_time.split(':'))
        SCHEDULER.add_job(
            func=lambda: stop_strategy_process(strategy_id),
            trigger=CronTrigger(hour=hour, minute=minute, day_of_week=','.join(days), timezone=IST),
            id=stop_job_id,
            replace_existing=True
        )
    
    # Update config
    STRATEGY_CONFIGS[strategy_id]['is_scheduled'] = True
    STRATEGY_CONFIGS[strategy_id]['schedule_start'] = start_time
    STRATEGY_CONFIGS[strategy_id]['schedule_stop'] = stop_time
    STRATEGY_CONFIGS[strategy_id]['schedule_days'] = days
    save_configs()
    
    logger.info(f"Scheduled strategy {strategy_id}: {start_time} - {stop_time} IST on {days}")

def unschedule_strategy(strategy_id):
    """Remove scheduling for a strategy"""
    start_job_id = f"start_{strategy_id}"
    stop_job_id = f"stop_{strategy_id}"
    
    if SCHEDULER.get_job(start_job_id):
        SCHEDULER.remove_job(start_job_id)
    if SCHEDULER.get_job(stop_job_id):
        SCHEDULER.remove_job(stop_job_id)
    
    if strategy_id in STRATEGY_CONFIGS:
        STRATEGY_CONFIGS[strategy_id]['is_scheduled'] = False
        save_configs()
    
    logger.info(f"Unscheduled strategy {strategy_id}")

@python_strategy_bp.route('/')
def index():
    """Main dashboard"""
    # Ensure initialization is done when first accessed
    initialize_with_app_context()
    cleanup_dead_processes()
    
    strategies = []
    for sid, config in STRATEGY_CONFIGS.items():
        # Check if process is actually running
        if config.get('pid'):
            config['is_running'] = check_process_status(config['pid'])
            if not config['is_running']:
                config['pid'] = None
                save_configs()
        
        strategy_info = {
            'id': sid,
            'name': config.get('name', 'Unnamed'),
            'file': Path(config.get('file_path', '')).name,
            'is_running': config.get('is_running', False),
            'is_scheduled': config.get('is_scheduled', False),
            'is_error': config.get('is_error', False),
            'error_message': config.get('error_message', ''),
            'error_time': format_ist_time(config.get('error_time', '')),
            'schedule_start': config.get('schedule_start', ''),
            'schedule_stop': config.get('schedule_stop', ''),
            'schedule_days': config.get('schedule_days', []),
            'created_at': config.get('created_at', ''),
            'last_started': format_ist_time(config.get('last_started', '')),
            'last_stopped': format_ist_time(config.get('last_stopped', '')),
            'pid': config.get('pid'),
            'params': {}  # No params needed in simplified version
        }
        
        # Add runtime info if running
        if sid in RUNNING_STRATEGIES:
            info = RUNNING_STRATEGIES[sid]
            strategy_info['started_at'] = info['started_at']
            strategy_info['log_file'] = info['log_file']
        
        strategies.append(strategy_info)
    
    # Get current IST time for the page
    current_ist = get_ist_time().strftime('%Y-%m-%d %H:%M:%S IST')
    
    return render_template('python_strategy/index.html', 
                         strategies=strategies,
                         current_ist_time=current_ist,
                         platform=OS_TYPE.capitalize())

@python_strategy_bp.route('/new', methods=['GET', 'POST'])
def new_strategy():
    """Upload a new strategy"""
    if request.method == 'POST':
        if 'strategy_file' not in request.files:
            flash('No file selected', 'error')
            return redirect(request.url)
        
        file = request.files['strategy_file']
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(request.url)
        
        if file and file.filename.endswith('.py'):
            # Generate unique ID with IST timestamp
            ist_now = get_ist_time()
            strategy_id = Path(file.filename).stem + '_' + ist_now.strftime('%Y%m%d%H%M%S')
            
            # Save file
            filename = secure_filename(file.filename)
            file_path = STRATEGIES_DIR / f"{strategy_id}.py"
            STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)
            file.save(str(file_path))
            
            # Make file executable on Unix-like systems
            if not IS_WINDOWS:
                try:
                    os.chmod(file_path, 0o755)
                except:
                    pass
            
            # Get form data
            strategy_name = request.form.get('strategy_name', Path(file.filename).stem)
            
            # Save configuration (no params needed)
            STRATEGY_CONFIGS[strategy_id] = {
                'name': strategy_name,
                'file_path': str(file_path),
                'is_running': False,
                'is_scheduled': False,
                'created_at': ist_now.isoformat()
            }
            save_configs()
            
            flash(f'Strategy "{strategy_name}" uploaded successfully', 'success')
            return redirect(url_for('python_strategy_bp.index'))
        else:
            flash('Please upload a Python (.py) file', 'error')
    
    return render_template('python_strategy/new.html')

@python_strategy_bp.route('/start/<strategy_id>', methods=['POST'])
def start_strategy(strategy_id):
    """Start a strategy"""
    # Ensure initialization is done when starting strategies
    initialize_with_app_context()
    success, message = start_strategy_process(strategy_id)
    return jsonify({'success': success, 'message': message})

@python_strategy_bp.route('/stop/<strategy_id>', methods=['POST'])
def stop_strategy(strategy_id):
    """Stop a strategy"""
    success, message = stop_strategy_process(strategy_id)
    return jsonify({'success': success, 'message': message})

@python_strategy_bp.route('/schedule/<strategy_id>', methods=['POST'])
def schedule_strategy_route(strategy_id):
    """Schedule a strategy"""
    if strategy_id not in STRATEGY_CONFIGS:
        return jsonify({'success': False, 'message': 'Strategy not found'}), 404
    
    config = STRATEGY_CONFIGS[strategy_id]
    if config.get('is_running', False):
        return jsonify({
            'success': False, 
            'message': 'Cannot modify schedule while strategy is running. Please stop the strategy first.',
            'error_code': 'STRATEGY_RUNNING'
        }), 400
    
    data = request.json
    start_time = data.get('start_time')
    stop_time = data.get('stop_time')
    days = data.get('days', ['mon', 'tue', 'wed', 'thu', 'fri'])
    
    if not start_time:
        return jsonify({'success': False, 'message': 'Start time is required'})
    
    try:
        schedule_strategy(strategy_id, start_time, stop_time, days)
        schedule_info = f"Scheduled at {start_time} IST"
        if stop_time:
            schedule_info += f" - {stop_time} IST"
        return jsonify({'success': True, 'message': schedule_info})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@python_strategy_bp.route('/unschedule/<strategy_id>', methods=['POST'])
def unschedule_strategy_route(strategy_id):
    """Remove scheduling for a strategy"""
    if strategy_id not in STRATEGY_CONFIGS:
        return jsonify({'success': False, 'message': 'Strategy not found'}), 404
    
    config = STRATEGY_CONFIGS[strategy_id]
    if config.get('is_running', False):
        return jsonify({
            'success': False, 
            'message': 'Cannot modify schedule while strategy is running. Please stop the strategy first.',
            'error_code': 'STRATEGY_RUNNING'
        }), 400
    
    try:
        unschedule_strategy(strategy_id)
        return jsonify({'success': True, 'message': 'Schedule removed successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@python_strategy_bp.route('/delete/<strategy_id>', methods=['POST'])
def delete_strategy(strategy_id):
    """Delete a strategy"""
    with PROCESS_LOCK:  # Thread-safe operation
        # Stop if running
        if strategy_id in RUNNING_STRATEGIES or (strategy_id in STRATEGY_CONFIGS and STRATEGY_CONFIGS[strategy_id].get('is_running')):
            stop_strategy_process(strategy_id)
        
        # Unschedule if scheduled
        if STRATEGY_CONFIGS.get(strategy_id, {}).get('is_scheduled'):
            unschedule_strategy(strategy_id)
        
        # Delete file
        if strategy_id in STRATEGY_CONFIGS:
            file_path = Path(STRATEGY_CONFIGS[strategy_id].get('file_path', ''))
            if file_path.exists():
                try:
                    file_path.unlink()
                except Exception as e:
                    logger.error(f"Failed to delete file {file_path}: {e}")
            
            # Remove from configs
            del STRATEGY_CONFIGS[strategy_id]
            save_configs()
            
            return jsonify({'success': True, 'message': 'Strategy deleted successfully'})
        
        return jsonify({'success': False, 'message': 'Strategy not found'})

@python_strategy_bp.route('/logs/<strategy_id>')
def view_logs(strategy_id):
    """View strategy logs"""
    log_files = []
    
    # Get all log files for this strategy
    try:
        for log_file in LOGS_DIR.glob(f"{strategy_id}_*.log"):
            log_files.append({
                'name': log_file.name,
                'size': log_file.stat().st_size,
                'modified': datetime.fromtimestamp(log_file.stat().st_mtime, tz=IST)
            })
    except Exception as e:
        logger.error(f"Error reading log files: {e}")
    
    # Sort by modified time (newest first)
    log_files.sort(key=lambda x: x['modified'], reverse=True)
    
    # Get latest log content if requested
    log_content = None
    if log_files and request.args.get('latest'):
        latest_log = LOGS_DIR / log_files[0]['name']
        try:
            with open(latest_log, 'r', encoding='utf-8', errors='ignore') as f:
                log_content = f.read()
        except Exception as e:
            log_content = f"Error reading log file: {e}"
    
    return render_template('python_strategy/logs.html', 
                         strategy_id=strategy_id,
                         log_files=log_files,
                         log_content=log_content)

@python_strategy_bp.route('/logs/<strategy_id>/clear', methods=['POST'])
def clear_logs(strategy_id):
    """Clear all log files for a strategy"""
    if strategy_id not in STRATEGY_CONFIGS:
        return jsonify({'success': False, 'message': 'Strategy not found'}), 404
    
    try:
        cleared_count = 0
        total_size = 0
        
        # Find all log files for this strategy
        log_files = list(LOGS_DIR.glob(f"{strategy_id}_*.log"))
        
        if not log_files:
            return jsonify({'success': False, 'message': 'No log files found to clear'})
        
        # Calculate total size before clearing
        for log_file in log_files:
            try:
                total_size += log_file.stat().st_size
            except:
                pass
        
        # Clear each log file
        for log_file in log_files:
            try:
                # Check if strategy is currently running and this is the active log file
                if strategy_id in RUNNING_STRATEGIES:
                    running_info = RUNNING_STRATEGIES[strategy_id]
                    active_log_file = running_info.get('log_file')
                    
                    if active_log_file and Path(active_log_file).name == log_file.name:
                        # For running strategies, truncate the active log file
                        with open(log_file, 'w', encoding='utf-8') as f:
                            f.write(f"=== Log cleared at {get_ist_time().strftime('%Y-%m-%d %H:%M:%S IST')} ===\n")
                        logger.info(f"Truncated active log file for running strategy {strategy_id}")
                    else:
                        # For inactive log files, delete them
                        log_file.unlink()
                        logger.info(f"Deleted inactive log file: {log_file.name}")
                else:
                    # Strategy not running, safe to delete all log files
                    log_file.unlink()
                    logger.info(f"Deleted log file: {log_file.name}")
                
                cleared_count += 1
                
            except Exception as e:
                logger.error(f"Error clearing log file {log_file.name}: {e}")
        
        if cleared_count > 0:
            size_mb = total_size / (1024 * 1024)
            logger.info(f"Cleared {cleared_count} log files for strategy {strategy_id} ({size_mb:.2f} MB)")
            return jsonify({
                'success': True,
                'message': f'Cleared {cleared_count} log files ({size_mb:.2f} MB)',
                'cleared_count': cleared_count,
                'total_size_mb': round(size_mb, 2)
            })
        else:
            return jsonify({'success': False, 'message': 'No log files were cleared'})
            
    except Exception as e:
        logger.error(f"Error clearing logs for strategy {strategy_id}: {e}")
        return jsonify({'success': False, 'message': f'Error clearing logs: {str(e)}'}), 500

@python_strategy_bp.route('/clear-error/<strategy_id>', methods=['POST'])
def clear_error_state(strategy_id):
    """Clear error state for a strategy"""
    if strategy_id not in STRATEGY_CONFIGS:
        return jsonify({'success': False, 'message': 'Strategy not found'}), 404
    
    config = STRATEGY_CONFIGS[strategy_id]
    
    if config.get('is_running'):
        return jsonify({'success': False, 'message': 'Cannot clear error state while strategy is running'}), 400
    
    if not config.get('is_error'):
        return jsonify({'success': False, 'message': 'Strategy is not in error state'}), 400
    
    try:
        # Clear error state
        config.pop('is_error', None)
        config.pop('error_message', None)
        config.pop('error_time', None)
        save_configs()
        
        logger.info(f"Cleared error state for strategy {strategy_id}")
        return jsonify({'success': True, 'message': 'Error state cleared successfully'})
        
    except Exception as e:
        logger.error(f"Failed to clear error state for {strategy_id}: {e}")
        return jsonify({'success': False, 'message': f'Failed to clear error state: {str(e)}'}), 500

@python_strategy_bp.route('/status')
def status():
    """Get system status"""
    cleanup_dead_processes()
    
    # Check master contract status
    contracts_ready, contract_message = check_master_contract_ready()
    
    return jsonify({
        'running': len(RUNNING_STRATEGIES),
        'total': len(STRATEGY_CONFIGS),
        'scheduler_running': SCHEDULER is not None and SCHEDULER.running,
        'current_ist_time': get_ist_time().strftime('%H:%M:%S IST'),
        'platform': OS_TYPE,
        'master_contracts_ready': contracts_ready,
        'master_contracts_message': contract_message,
        'strategies': [
            {
                'id': sid,
                'name': config.get('name'),
                'is_running': config.get('is_running', False),
                'is_scheduled': config.get('is_scheduled', False)
            }
            for sid, config in STRATEGY_CONFIGS.items()
        ]
    })

@python_strategy_bp.route('/check-contracts', methods=['POST'])
def check_contracts():
    """Check master contracts and start pending strategies"""
    try:
        success, message = check_and_start_pending_strategies()
        return jsonify({
            'success': success,
            'message': message
        })
    except Exception as e:
        logger.error(f"Error checking contracts: {e}")
        return jsonify({
            'success': False,
            'message': f'Error checking contracts: {str(e)}'
        }), 500

@python_strategy_bp.route('/edit/<strategy_id>')
def edit_strategy(strategy_id):
    """Edit or view a strategy file"""
    if strategy_id not in STRATEGY_CONFIGS:
        flash('Strategy not found', 'error')
        return redirect(url_for('python_strategy_bp.index'))
    
    config = STRATEGY_CONFIGS[strategy_id]
    file_path = Path(config['file_path'])
    
    if not file_path.exists():
        flash('Strategy file not found', 'error')
        return redirect(url_for('python_strategy_bp.index'))
    
    # Check if strategy is running
    is_running = config.get('is_running', False)
    
    # Read file content
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        flash(f'Error reading file: {e}', 'error')
        return redirect(url_for('python_strategy_bp.index'))
    
    # Get file info
    file_stats = file_path.stat()
    file_info = {
        'name': file_path.name,
        'size': file_stats.st_size,
        'modified': datetime.fromtimestamp(file_stats.st_mtime, tz=IST),
        'lines': content.count('\n') + 1
    }
    
    return render_template('python_strategy/edit.html',
                         strategy_id=strategy_id,
                         strategy_name=config.get('name', 'Unnamed Strategy'),
                         content=content,
                         is_running=is_running,
                         file_info=file_info,
                         can_edit=not is_running)

@python_strategy_bp.route('/export/<strategy_id>')
def export_strategy(strategy_id):
    """Export/download a strategy file"""
    if strategy_id not in STRATEGY_CONFIGS:
        flash('Strategy not found', 'error')
        return redirect(url_for('python_strategy_bp.index'))
    
    config = STRATEGY_CONFIGS[strategy_id]
    file_path = Path(config['file_path'])
    
    if not file_path.exists():
        flash('Strategy file not found', 'error')
        return redirect(url_for('python_strategy_bp.index'))
    
    try:
        # Read the file content
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Create response with file download
        from flask import Response
        response = Response(
            content,
            mimetype='text/x-python',
            headers={
                'Content-Disposition': f'attachment; filename={file_path.name}',
                'Content-Type': 'text/x-python; charset=utf-8'
            }
        )
        
        logger.info(f"Strategy {strategy_id} exported successfully")
        return response
        
    except Exception as e:
        logger.error(f"Failed to export strategy {strategy_id}: {e}")
        flash(f'Failed to export strategy: {str(e)}', 'error')
        return redirect(url_for('python_strategy_bp.index'))

@python_strategy_bp.route('/save/<strategy_id>', methods=['POST'])
def save_strategy(strategy_id):
    """Save edited strategy file"""
    if strategy_id not in STRATEGY_CONFIGS:
        return jsonify({'success': False, 'message': 'Strategy not found'}), 404
    
    config = STRATEGY_CONFIGS[strategy_id]
    
    # Check if strategy is running
    if config.get('is_running', False):
        return jsonify({'success': False, 'message': 'Cannot edit running strategy. Please stop it first.'}), 400
    
    file_path = Path(config['file_path'])
    
    # Get new content
    data = request.get_json()
    if not data or 'content' not in data:
        return jsonify({'success': False, 'message': 'No content provided'}), 400
    
    new_content = data['content']
    
    try:
        # Create backup
        backup_path = file_path.with_suffix('.bak')
        if file_path.exists():
            with open(file_path, 'r', encoding='utf-8') as f:
                backup_content = f.read()
            with open(backup_path, 'w', encoding='utf-8') as f:
                f.write(backup_content)
        
        # Save new content
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        # Update config
        config['last_modified'] = get_ist_time().isoformat()
        save_configs()
        
        logger.info(f"Strategy {strategy_id} saved successfully")
        return jsonify({
            'success': True, 
            'message': 'Strategy saved successfully',
            'timestamp': format_ist_time(config['last_modified'])
        })
        
    except Exception as e:
        logger.error(f"Failed to save strategy {strategy_id}: {e}")
        return jsonify({'success': False, 'message': f'Failed to save: {str(e)}'}), 500

@python_strategy_bp.route('/env/<strategy_id>', methods=['GET', 'POST'])
def manage_env_variables(strategy_id):
    """Manage environment variables for a strategy"""
    if strategy_id not in STRATEGY_CONFIGS:
        return jsonify({'success': False, 'message': 'Strategy not found'}), 404
    
    config = STRATEGY_CONFIGS[strategy_id]
    is_running = config.get('is_running', False)
    
    if request.method == 'GET':
        # Load environment variables
        try:
            # Load regular variables
            regular_vars = {}
            if ENV_FILE.exists():
                with open(ENV_FILE, 'r', encoding='utf-8') as f:
                    all_env = json.load(f)
                    regular_vars = all_env.get(strategy_id, {})
            
            # Load secure variable keys only (not values for security)
            secure_keys = []
            if SECURE_ENV_FILE.exists():
                try:
                    with open(SECURE_ENV_FILE, 'rb') as f:
                        encrypted_data = f.read()
                        decrypted_data = CIPHER_SUITE.decrypt(encrypted_data)
                        secure_env = json.loads(decrypted_data.decode('utf-8'))
                        secure_keys = list(secure_env.get(strategy_id, {}).keys())
                except Exception as e:
                    logger.error(f"Failed to load secure env keys: {e}")
            
            return jsonify({
                'success': True,
                'regular_vars': regular_vars,
                'secure_vars': secure_keys,
                'is_running': is_running,
                'read_only': is_running
            })
            
        except Exception as e:
            logger.error(f"Failed to load env variables: {e}")
            return jsonify({'success': False, 'message': f'Failed to load variables: {str(e)}'}), 500
    
    elif request.method == 'POST':
        # Check if strategy is running - prevent changes for safety
        if is_running:
            return jsonify({
                'success': False, 
                'message': 'Cannot modify environment variables while strategy is running. Please stop the strategy first.',
                'error_code': 'STRATEGY_RUNNING'
            }), 400
        
        # Save environment variables
        try:
            data = request.get_json()
            if not data:
                return jsonify({'success': False, 'message': 'No data provided'}), 400
            
            regular_vars = data.get('regular_vars', {})
            secure_vars = data.get('secure_vars', {})
            
            # Filter out empty values
            regular_vars = {k: v for k, v in regular_vars.items() if k.strip()}
            secure_vars = {k: v for k, v in secure_vars.items() if k.strip()}
            
            # Save variables
            save_env_variables(strategy_id, regular_vars, secure_vars if secure_vars else None)
            
            logger.info(f"Environment variables updated for strategy {strategy_id}")
            return jsonify({
                'success': True,
                'message': f'Environment variables saved successfully',
                'regular_count': len(regular_vars),
                'secure_count': len(secure_vars)
            })
            
        except Exception as e:
            logger.error(f"Failed to save env variables: {e}")
            return jsonify({'success': False, 'message': f'Failed to save variables: {str(e)}'}), 500

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
        logger.warning(f"Master contracts not ready - strategies will remain in error state until contracts are downloaded: {contract_message}")
        # Mark all running strategies as error state due to master contract dependency
        for strategy_id, config in STRATEGY_CONFIGS.items():
            if config.get('is_running'):
                config['is_running'] = False
                config['is_error'] = True
                config['error_message'] = f"Waiting for master contracts to be downloaded"
                config['error_time'] = get_ist_time().isoformat()
                config['pid'] = None
        save_configs()
        return
    
    restored_count = 0
    error_count = 0
    cleaned_count = 0
    
    for strategy_id, config in STRATEGY_CONFIGS.items():
        if config.get('is_running') and config.get('pid'):
            pid = config.get('pid')
            strategy_restored = False
            
            try:
                # Check if process is still running
                if psutil.pid_exists(pid):
                    process = psutil.Process(pid)
                    
                    # Check if it's actually our strategy process
                    cmdline = ' '.join(process.cmdline())
                    strategy_file = config.get('file_path', '')
                    
                    if strategy_file and strategy_file in cmdline:
                        # Process is still running, restore it to RUNNING_STRATEGIES
                        ist_now = get_ist_time()
                        
                        # Find the current log file
                        log_pattern = f"{strategy_id}_*_IST.log"
                        log_files = list(LOGS_DIR.glob(log_pattern))
                        current_log = max(log_files, key=lambda f: f.stat().st_mtime) if log_files else None
                        
                        RUNNING_STRATEGIES[strategy_id] = {
                            'process': process,
                            'pid': pid,
                            'started_at': datetime.fromisoformat(config.get('last_started', ist_now.isoformat())),
                            'log_file': str(current_log) if current_log else None,
                            'log_handle': None  # We can't restore the file handle
                        }
                        
                        logger.info(f"Restored running strategy {strategy_id} (PID: {pid})")
                        restored_count += 1
                        strategy_restored = True
                    else:
                        logger.debug(f"PID {pid} exists but not our strategy process")
                        
            except psutil.NoSuchProcess:
                logger.debug(f"Process {pid} for strategy {strategy_id} no longer exists")
            except Exception as e:
                logger.error(f"Error checking process {pid} for strategy {strategy_id}: {e}")
            
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
                        config['is_running'] = False
                        config['is_error'] = True
                        config['error_message'] = f"Failed to restart: {message}"
                        config['error_time'] = get_ist_time().isoformat()
                        config['pid'] = None
                        logger.error(f"Failed to restart strategy {strategy_id}: {message}")
                        error_count += 1
                except Exception as e:
                    # Mark as error state
                    config['is_running'] = False
                    config['is_error'] = True
                    config['error_message'] = f"Restart exception: {str(e)}"
                    config['error_time'] = get_ist_time().isoformat()
                    config['pid'] = None
                    logger.error(f"Exception restarting strategy {strategy_id}: {e}")
                    error_count += 1
        
        # Clear error state for strategies that are not marked as running
        elif config.get('is_error') and not config.get('is_running'):
            # Keep error state until user manually clears it
            pass
    
    if restored_count > 0 or error_count > 0:
        save_configs()
        logger.info(f"State restoration complete: {restored_count} restored, {error_count} in error state")
    else:
        logger.info("No strategies needed state restoration")

def check_and_start_pending_strategies():
    """Check if master contracts are ready and start strategies that were waiting"""
    contracts_ready, contract_message = check_master_contract_ready()
    if not contracts_ready:
        return False, contract_message
    
    started_count = 0
    failed_count = 0
    
    # Look for strategies that are in error state due to master contract dependency
    for strategy_id, config in STRATEGY_CONFIGS.items():
        if (config.get('is_error') and 
            ('Waiting for master contracts' in config.get('error_message', '') or
             'Master contract dependency not met' in config.get('error_message', ''))):
            
            logger.info(f"Attempting to start strategy {strategy_id} after master contract became ready")
            
            # Clear error state and try to start
            config.pop('is_error', None)
            config.pop('error_message', None)
            config.pop('error_time', None)
            
            success, message = start_strategy_process(strategy_id)
            if success:
                started_count += 1
                logger.info(f"Successfully started strategy {strategy_id} after master contract ready")
            else:
                failed_count += 1
                logger.error(f"Failed to start strategy {strategy_id} even after master contract ready: {message}")
    
    if started_count > 0 or failed_count > 0:
        save_configs()
        return True, f"Started {started_count} strategies, {failed_count} failed"
    
    return True, "No pending strategies to start"

def restore_strategies_after_login():
    """Called after successful login to restore strategies that were waiting"""
    logger.info("Checking for strategies to restore after login...")
    
    # Re-run restore_strategy_states now that we have a proper session
    restore_strategy_states()
    
    # Then check and start any pending strategies
    success, message = check_and_start_pending_strategies()
    logger.info(f"Post-login strategy restoration: {message}")
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
        for strategy_id, config in STRATEGY_CONFIGS.items():
            if config.get('is_scheduled'):
                start_time = config.get('schedule_start')
                stop_time = config.get('schedule_stop')
                days = config.get('schedule_days', ['mon', 'tue', 'wed', 'thu', 'fri'])
                if start_time:
                    try:
                        schedule_strategy(strategy_id, start_time, stop_time, days)
                        logger.info(f"Restored schedule for strategy {strategy_id} at {start_time} IST")
                    except Exception as e:
                        logger.error(f"Failed to restore schedule for {strategy_id}: {e}")

        logger.info(f"Python Strategy System fully initialized on {OS_TYPE}")
    except Exception as e:
        logger.warning(f"Deferred initialization skipped (likely no app context yet): {e}")
        _initialized = False  # Reset flag to retry later

# Note: Flask removed before_app_first_request in newer versions
# The initialization is now handled in the index route and other entry points

logger.info(f"Python Strategy System initialized (basic) on {OS_TYPE}")