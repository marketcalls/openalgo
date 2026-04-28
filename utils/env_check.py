import os
import re
import secrets
import sqlite3
import sys
import time

from dotenv import load_dotenv

# Placeholder values shipped in .sample.env. OpenAlgo detects these on startup
# and rotates them to fresh random secrets on first run. Coordinated with the
# install/*.sh scripts which use the same strings as their sed targets.
PLACEHOLDER_APP_KEY = "OPENALGO_PLACEHOLDER_APP_KEY_REGENERATE_BEFORE_USE"
PLACEHOLDER_PEPPER = "OPENALGO_PLACEHOLDER_API_KEY_PEPPER_REGENERATE_BEFORE_USE"

# Historical leaked literals: these were the original values in .sample.env
# committed to the public repo before the placeholder switch. Any .env that
# still carries them is publicly forgeable. Detected as compromised so users
# who copied .sample.env from an older commit (without running an install
# script) are still caught and rotated.
_LEAKED_LITERAL_APP_KEY = "3daa0403ce2501ee7432b75bf100048e3cf510d63d2754f952e93d88bf07ea84"
_LEAKED_LITERAL_PEPPER = "a25d94718479b170c16278e321ea6c989358bf499a658fd20c90033cef8ce772"

COMPROMISED_APP_KEYS = frozenset([PLACEHOLDER_APP_KEY, _LEAKED_LITERAL_APP_KEY])
COMPROMISED_PEPPERS = frozenset([PLACEHOLDER_PEPPER, _LEAKED_LITERAL_PEPPER])


def configure_llvmlite_paths() -> None:
    """
    Configure LLVMLITE/NUMBA paths to avoid 'failed to map segment' errors.

    On hardened Linux servers, /tmp is often mounted with the 'noexec' flag,
    which prevents llvmlite from loading its shared library.

    This sets alternative directories for llvmlite/numba cache and temp files.
    Must be called BEFORE any imports that might trigger llvmlite loading.

    Returns:
        None
    """
    # Only configure on Linux (Windows/macOS don't have this issue)
    if sys.platform != 'linux':
        return

    # Get the base directory (project root)
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Create cache directories in project folder
    numba_cache = os.path.join(base_dir, '.numba_cache')
    llvm_tmp = os.path.join(base_dir, '.llvm_tmp')

    # Set environment variables if not already set
    if 'NUMBA_CACHE_DIR' not in os.environ:
        os.environ['NUMBA_CACHE_DIR'] = numba_cache

    if 'LLVMLITE_TMPDIR' not in os.environ:
        os.environ['LLVMLITE_TMPDIR'] = llvm_tmp

    # Create directories if they don't exist
    for dir_path in [numba_cache, llvm_tmp]:
        if not os.path.exists(dir_path):
            try:
                os.makedirs(dir_path, exist_ok=True)
            except OSError:
                pass  # Ignore if can't create, will fail later with better error

    # Check if /tmp has noexec and warn
    check_tmp_noexec()


def check_tmp_noexec() -> None:
    """
    Check if /tmp is mounted with the noexec flag and print a warning.

    This helps users understand why llvmlite might fail to load.
    """
    if sys.platform != 'linux':
        return

    try:
        with open('/proc/mounts', 'r') as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 4 and parts[1] == '/tmp':
                    mount_options = parts[3].split(',')
                    if 'noexec' in mount_options:
                        print("\n" + "=" * 70)
                        print("⚠️  WARNING: /tmp is mounted with 'noexec' flag")
                        print("   This can cause issues with Python libraries like numba/llvmlite.")
                        print("")
                        print("   OpenAlgo has auto-configured alternative paths:")
                        print(f"   - NUMBA_CACHE_DIR={os.environ.get('NUMBA_CACHE_DIR', 'not set')}")
                        print(f"   - LLVMLITE_TMPDIR={os.environ.get('LLVMLITE_TMPDIR', 'not set')}")
                        print("")
                        print("   If you still see 'failed to map segment' errors, either:")
                        print("   1. Remount /tmp: sudo mount -o remount,exec /tmp")
                        print("   2. Or set NUMBA_DISABLE_JIT=1 in your .env file")
                        print("=" * 70 + "\n")
                    return
    except (OSError, IOError):
        pass  # Can't read /proc/mounts, skip the check


def check_env_version_compatibility() -> bool:
    """
    Check if the .env file version matches the .sample.env version.

    Returns:
        bool: True if compatible, False if an update is needed.
    """
    base_dir = os.path.dirname(__file__) + "/.."
    env_path = os.path.join(base_dir, ".env")
    sample_env_path = os.path.join(base_dir, ".sample.env")

    # Check if both files exist
    if not os.path.exists(env_path):
        print("\nError: .env file not found.")
        print("Solution: Copy .sample.env to .env and configure your settings")
        return False

    if not os.path.exists(sample_env_path):
        print("\nWarning: .sample.env file not found. Cannot check version compatibility.")
        return True  # Assume compatible if sample file is missing

    # Read version from .env file
    env_version = None
    try:
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("ENV_CONFIG_VERSION"):
                    env_version = line.split("=")[1].strip().strip("'\"")
                    break
    except Exception as e:
        print(f"\nWarning: Could not read .env file: {e}")
        return True  # Assume compatible if can't read

    # Read version from .sample.env file
    sample_version = None
    try:
        with open(sample_env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("ENV_CONFIG_VERSION"):
                    sample_version = line.split("=")[1].strip().strip("'\"")
                    break
    except Exception as e:
        print(f"\nWarning: Could not read .sample.env file: {e}")
        return True  # Assume compatible if can't read

    # If either version is missing, warn but continue
    if not env_version:
        print("\n" + "=" * 70)
        print("⚠️  WARNING: No version found in your .env file")
        print("   Your .env file may be outdated and missing new configuration options.")
        print("   Consider updating it with new variables from .sample.env")
        print("=" * 70)
        return True

    if not sample_version:
        return True  # Can't compare without sample version

    # Compare versions using simple string comparison for semantic versions
    try:

        def version_tuple(v: str) -> tuple:
            """
            Convert version string to tuple of integers for comparison.
            
            Args:
                v (str): Version string (e.g. '1.5.0').
            
            Returns:
                tuple: Tuple of integers (e.g. (1, 5, 0)).
            """
            return tuple(int(x) for x in v.split('.'))

        env_ver = version_tuple(env_version)
        sample_ver = version_tuple(sample_version)

        if env_ver < sample_ver:
            print("\n" + "🔴 " + "=" * 68)
            print("🔴  CONFIGURATION UPDATE REQUIRED")
            print("🔴 " + "=" * 68)
            print(f"   Your .env version: {env_version}")
            print(f"   Required version:  {sample_version}")
            print("")
            print("   ACTION NEEDED:")
            print("   1. Backup your current .env file")
            print("   2. Compare .env with .sample.env")
            print("   3. Add any missing configuration variables to your .env")
            print("   4. Update ENV_CONFIG_VERSION in your .env to match .sample.env")
            print("")
            print("   New features may not work properly with an outdated configuration!")
            print("🔴 " + "=" * 68)

            # Give user a chance to continue anyway
            try:
                response = input("\n⚠️  Continue anyway? (y/N): ").lower().strip()
                if response not in ["y", "yes"]:
                    print("\nApplication startup cancelled. Please update your .env file.")
                    return False
            except (KeyboardInterrupt, EOFError):
                print("\nApplication startup cancelled.")
                return False

        elif env_ver > sample_ver:
            print(f"\n✅ Your .env version ({env_version}) is newer than sample ({sample_version})")

        else:
            # Only print success message in Flask child process (avoids duplicate message with debug reloader)
            # In debug mode, werkzeug spawns parent (reloader) and child (app) process
            # WERKZEUG_RUN_MAIN is 'true' only in the child process
            flask_debug = os.getenv("FLASK_DEBUG", "").lower() in ("true", "1", "t")
            is_reloader_parent = flask_debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true"
            if not is_reloader_parent:
                print(
                    f"\n\033[94m🔄\033[0m Configuration version check passed (\033[92m{env_version}\033[0m)"
                )

    except Exception as e:
        print(f"\nWarning: Could not parse version numbers: {e}")
        print(f"   .env version: {env_version}")
        print(f"   .sample.env version: {sample_version}")
        return True  # Continue if version parsing fails

    return True


def _db_has_user_data(env_dir: str) -> bool:
    """Return True if the main SQLite users table has any rows.

    Used as a safety gate before rotating API_KEY_PEPPER, which would
    invalidate every existing Argon2 password hash and Fernet-encrypted
    broker token. Conservative on uncertainty: any error treats the DB
    as populated. The cost of a false 'populated' is a printed warning;
    the cost of a false 'empty' is silently bricking real user data.

    Args:
        env_dir: Absolute directory containing the .env file. Used to
            resolve a relative DATABASE_URL such as ``sqlite:///db/openalgo.db``
            against the project root.

    Returns:
        True if the users table exists and contains at least one row, or
        if any check fails. False only when we can prove the DB is empty.
    """
    db_url = os.getenv("DATABASE_URL", "")
    m = re.match(r"sqlite:///(.+)", db_url)
    if not m:
        # Non-SQLite (e.g., Postgres) — be conservative. Server installs that
        # use such backends already run install.sh which rotates the keys
        # before this code ever sees a compromised value.
        return True

    db_path = m.group(1)
    if not os.path.isabs(db_path):
        db_path = os.path.join(env_dir, db_path)
    if not os.path.exists(db_path):
        return False  # Fresh install — DB file not yet created.

    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
            )
            if cur.fetchone() is None:
                return False
            cur = conn.execute("SELECT 1 FROM users LIMIT 1")
            return cur.fetchone() is not None
    except sqlite3.Error:
        return True  # Conservative on any error.


def _atomic_rewrite_dotenv(env_path: str, pairs: list) -> None:
    """Atomically replace each (old, new) value pair inside .env.

    Cross-platform safe by design:

    - ``newline=""`` on read and write preserves whatever line endings the
      original file used (LF on Unix-clone, CRLF if the file was created on
      Windows). Without it, Python's text-mode universal-newlines would
      silently rewrite LF as CRLF on Windows, producing a noisy diff.
    - ``os.replace`` is atomic on POSIX (``rename(2)``) and on Windows
      (``MoveFileEx`` since Python 3.3). On Windows, if a file watcher or
      editor is briefly holding ``.env`` open with an exclusive lock, the
      replace fails with ERROR_ACCESS_DENIED; retry up to twice with a small
      delay before giving up.
    - ``os.chmod(0o600)`` is POSIX-only and is skipped on Windows. New files
      created on Windows inherit the parent directory's ACL, which on a user
      home / project directory is already restricted to that user.

    Args:
        env_path: Absolute path to the .env file to rewrite.
        pairs: List of (old_value, new_value) tuples to substitute. Old
            values must be unique enough that ``str.replace`` won't collide
            with unrelated content; the placeholder strings used here are
            64+ characters of underscore-separated ASCII and meet that bar.

    Raises:
        OSError: If the rewrite cannot complete (read-only mount, persistent
            file lock on Windows, permission denied, etc.). Caller surfaces
            this with a manual-rotation instruction.
    """
    with open(env_path, "r", encoding="utf-8", newline="") as f:
        content = f.read()
    for old, new in pairs:
        content = content.replace(old, new)
    tmp = env_path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    if os.name != "nt":
        os.chmod(tmp, 0o600)

    last_err = None
    for attempt in range(3):
        try:
            os.replace(tmp, env_path)
            return
        except OSError as e:
            last_err = e
            if os.name != "nt":
                raise
            time.sleep(0.15)
    if last_err is not None:
        raise last_err


def _generate_keys_on_first_run(env_path: str) -> None:
    """Detect publicly-known APP_KEY/API_KEY_PEPPER and rotate or warn.

    Decision matrix:

    +----------------------+----------------------------+----------------------+
    | Compromised value(s) | Database state             | Action               |
    +======================+============================+======================+
    | Neither              | any                        | silent fast path     |
    +----------------------+----------------------------+----------------------+
    | APP_KEY only         | any                        | rotate APP_KEY       |
    +----------------------+----------------------------+----------------------+
    | PEPPER (or both)     | no users (fresh install)   | rotate both          |
    +----------------------+----------------------------+----------------------+
    | PEPPER (or both)     | users exist (populated)    | rotate APP_KEY only, |
    |                      |                            | warn re PEPPER       |
    +----------------------+----------------------------+----------------------+

    Why APP_KEY rotation is always safe:
        APP_KEY only signs Flask session cookies and Flask-WTF CSRF tokens.
        After rotation, existing browser sessions fail signature verification
        and the user re-logs in once. No persisted data is invalidated.

    Why PEPPER rotation is gated:
        API_KEY_PEPPER feeds Argon2 password hashing in database/user_db.py
        and the Fernet KDF in database/auth_db.py. Rotating it invalidates
        every stored password hash (one-way, cannot be migrated), every
        Fernet-encrypted broker auth/feed token, and every Fernet-encrypted
        TradingView API key. On a fresh install there is nothing to lose.
        On a populated DB this would brick the deployment, so we refuse to
        rotate and instead print a remediation path the operator can take
        in a controlled fashion.

    Why this is a no-op for existing install.sh users:
        install.sh and friends rewrite the placeholders to fresh random
        values *before* the app first runs. By the time this function
        executes, the env vars are not in the compromised set, the
        ``frozenset`` membership check returns False, and the function
        returns immediately — no DB query, no file I/O.

    Args:
        env_path: Absolute path to the .env file.
    """
    app_key = os.getenv("APP_KEY", "")
    pepper = os.getenv("API_KEY_PEPPER", "")

    app_key_compromised = app_key in COMPROMISED_APP_KEYS
    pepper_compromised = pepper in COMPROMISED_PEPPERS

    if not (app_key_compromised or pepper_compromised):
        return  # Common case: silent fast path.

    env_dir = os.path.dirname(os.path.abspath(env_path))
    db_populated = _db_has_user_data(env_dir)

    pairs = []
    rotated_names = []

    if app_key_compromised:
        new_app_key = secrets.token_hex(32)
        pairs.append((app_key, new_app_key))
        os.environ["APP_KEY"] = new_app_key
        rotated_names.append("APP_KEY")

    if pepper_compromised and not db_populated:
        new_pepper = secrets.token_hex(32)
        pairs.append((pepper, new_pepper))
        os.environ["API_KEY_PEPPER"] = new_pepper
        rotated_names.append("API_KEY_PEPPER")

    if pairs:
        try:
            _atomic_rewrite_dotenv(env_path, pairs)
        except OSError as e:
            sys.stderr.write(
                "\n\033[91m\033[1m[OpenAlgo security]\033[0m\n"
                "\033[91mDetected publicly-known APP_KEY/API_KEY_PEPPER in .env, but\n"
                f"could not rewrite the file ({e}).\n"
                "\n"
                "Generate fresh values manually and paste them into .env:\n"
                '  python -c "import secrets; print(secrets.token_hex(32))"\n'
                "\033[0m\n"
            )
            sys.exit(1)

    # User-facing reporting.
    flask_debug = os.getenv("FLASK_DEBUG", "").lower() in ("true", "1", "t")
    is_reloader_parent = flask_debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true"

    if rotated_names and not db_populated and not is_reloader_parent:
        print(
            "\n\033[92m\033[1m[OpenAlgo first-run setup]\033[0m "
            f"\033[92mGenerated fresh {' and '.join(rotated_names)} and saved\n"
            f"to {env_path}. The .sample.env placeholder values have been replaced\n"
            "with cryptographically random secrets. This message will not appear\n"
            "again on subsequent runs.\033[0m\n",
            flush=True,
        )
    elif "APP_KEY" in rotated_names and db_populated and not is_reloader_parent:
        print(
            "\n\033[93m\033[1m[OpenAlgo security]\033[0m "
            "\033[93mYour APP_KEY in .env was the public sample value. It has been\n"
            "rotated to a fresh random value. Active browser sessions will need\n"
            "to log in again.\033[0m\n",
            flush=True,
        )

    # PEPPER on a populated DB is intentionally left alone here — rotating it
    # in-place would brick existing Argon2 password hashes and Fernet-encrypted
    # tokens. The dedicated upgrade/rotate_pepper.py migration handles that
    # case explicitly with re-encryption + password reset.


def load_and_check_env_variables() -> None:
    """
    Load environment variables from .env and check for required critical variables.

    Raises:
        SystemExit: If the .env file is missing or required variables are not set.
    """
    # Configure LLVMLITE/NUMBA paths FIRST (before any imports can trigger loading)
    # This fixes "failed to map segment from shared object" on hardened Linux servers
    configure_llvmlite_paths()

    # Check version compatibility
    if not check_env_version_compatibility():
        sys.exit(1)

    # Define the path to the .env file in the main application path
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")

    # Check if the .env file exists
    if not os.path.exists(env_path):
        print("Error: .env file not found at the expected location.")
        print("\nSolution: Copy .sample.env to .env and configure your settings")
        sys.exit(1)

    # Load environment variables from the .env file with override=True to ensure values are updated
    load_dotenv(dotenv_path=env_path, override=True)

    # Detect the publicly-known sample APP_KEY/API_KEY_PEPPER values and rotate
    # them to fresh random secrets on first run. Silent no-op for any user
    # whose .env was set up via install.sh / install-docker.sh / etc., which
    # already rotate before the app first runs. See _generate_keys_on_first_run
    # for the full decision matrix and why PEPPER rotation is gated.
    _generate_keys_on_first_run(env_path)

    # Define the required environment variables
    required_vars = [
        "ENV_CONFIG_VERSION",  # Version tracking for configuration compatibility
        "BROKER_API_KEY",
        "BROKER_API_SECRET",
        "REDIRECT_URL",
        "APP_KEY",
        "API_KEY_PEPPER",  # Added API_KEY_PEPPER as it's required for security
        "DATABASE_URL",
        "NGROK_ALLOW",
        "HOST_SERVER",
        "FLASK_HOST_IP",
        "FLASK_PORT",
        "FLASK_DEBUG",
        "FLASK_ENV",  # Added FLASK_ENV as it's important for app configuration
        "LOGIN_RATE_LIMIT_MIN",
        "LOGIN_RATE_LIMIT_HOUR",
        "API_RATE_LIMIT",
        "ORDER_RATE_LIMIT",  # Rate limit for order placement, modification, and cancellation
        "SMART_ORDER_RATE_LIMIT",  # Rate limit for smart order placement
        "WEBHOOK_RATE_LIMIT",  # Rate limit for webhook endpoints
        "STRATEGY_RATE_LIMIT",  # Rate limit for strategy operations
        "SESSION_EXPIRY_TIME",  # Added SESSION_EXPIRY_TIME as it's required for session management
        "WEBSOCKET_HOST",  # Host for the WebSocket server
        "WEBSOCKET_PORT",  # Port for the WebSocket server
        "WEBSOCKET_URL",  # Full WebSocket URL for clients
        "LOG_TO_FILE",  # Enable/disable file logging
        "LOG_LEVEL",  # Logging level
        "LOG_DIR",  # Directory for log files
        "LOG_FORMAT",  # Log message format
        "LOG_RETENTION",  # Days to retain log files
    ]

    # Check if each required environment variable is set
    missing_vars = [var for var in required_vars if os.getenv(var) is None]

    if missing_vars:
        missing_list = ", ".join(missing_vars)
        print(f"Error: The following environment variables are missing: {missing_list}")
        print("\nSolution: Check .sample.env for the latest configuration format")
        sys.exit(1)

    # Special validation for broker-specific API key formats
    broker_api_key = os.getenv("BROKER_API_KEY", "")
    broker_api_secret = os.getenv("BROKER_API_SECRET", "")
    redirect_url = os.getenv("REDIRECT_URL", "")

    # Extract broker name from redirect URL for validation
    broker_name = None
    try:
        import re

        match = re.search(r"/([^/]+)/callback$", redirect_url)
        if match:
            broker_name = match.group(1).lower()
    except:
        pass

    # Validate 5paisa API key format
    if broker_name == "fivepaisa":
        if ":::" not in broker_api_key or broker_api_key.count(":::") != 2:
            print("\nError: Invalid 5paisa API key format detected!")
            print("The BROKER_API_KEY for 5paisa must be in the format:")
            print("  BROKER_API_KEY = 'User_Key:::User_ID:::client_id'")
            print("\nExample:")
            print("  BROKER_API_KEY = 'abc123xyz:::12345678:::5P12345678'")
            print("  BROKER_API_SECRET = 'your_encryption_key'")
            print("\nFor detailed instructions, please refer to:")
            print("  https://docs.openalgo.in/connect-brokers/brokers/5paisa")
            sys.exit(1)

    # Validate flattrade API key format
    elif broker_name == "flattrade":
        if ":::" not in broker_api_key or broker_api_key.count(":::") != 1:
            print("\nError: Invalid Flattrade API key format detected!")
            print("The BROKER_API_KEY for Flattrade must be in the format:")
            print("  BROKER_API_KEY = 'client_id:::api_key'")
            print("\nExample:")
            print("  BROKER_API_KEY = 'FT123456:::your_api_key_here'")
            print("  BROKER_API_SECRET = 'your_api_secret'")
            print("\nFor detailed instructions, please refer to:")
            print("  https://docs.openalgo.in/connect-brokers/brokers/flattrade")
            sys.exit(1)

    # Validate dhan API key format
    elif broker_name == "dhan":
        if ":::" not in broker_api_key or broker_api_key.count(":::") != 1:
            print("\nError: Invalid Dhan API key format detected!")
            print("The BROKER_API_KEY for Dhan must be in the format:")
            print("  BROKER_API_KEY = 'client_id:::api_key'")
            print("\nExample:")
            print("  BROKER_API_KEY = '1234567890:::your_dhan_apikey'")
            print("  BROKER_API_SECRET = 'your_dhan_apisecret'")
            print("\nFor detailed instructions, please refer to:")
            print("  https://docs.openalgo.in/connect-brokers/brokers/dhan")
            sys.exit(1)

    # Validate environment variable values
    flask_debug = os.getenv("FLASK_DEBUG", "").lower()
    if flask_debug not in ["true", "false", "1", "0", "t", "f"]:
        print("\nError: FLASK_DEBUG must be 'True' or 'False'")
        print("Example: FLASK_DEBUG='False'")
        sys.exit(1)

    flask_env = os.getenv("FLASK_ENV", "").lower()
    if flask_env not in ["development", "production"]:
        print("\nError: FLASK_ENV must be 'development' or 'production'")
        print("Example: FLASK_ENV='production'")
        sys.exit(1)

    try:
        port = int(os.getenv("FLASK_PORT"))
        if port < 0 or port > 65535:
            raise ValueError
    except ValueError:
        print("\nError: FLASK_PORT must be a valid port number (0-65535)")
        print("Example: FLASK_PORT='5000'")
        sys.exit(1)

    # Validate WebSocket port
    try:
        ws_port = int(os.getenv("WEBSOCKET_PORT"))
        if ws_port < 0 or ws_port > 65535:
            raise ValueError
    except ValueError:
        print("\nError: WEBSOCKET_PORT must be a valid port number (0-65535)")
        print("Example: WEBSOCKET_PORT='8765'")
        sys.exit(1)

    # Check REDIRECT_URL configuration
    redirect_url = os.getenv("REDIRECT_URL")
    default_value = "http://127.0.0.1:5000/<broker>/callback"

    if redirect_url == default_value:
        print("\nError: Default REDIRECT_URL detected in .env file.")
        print("The application cannot start with the default configuration.")
        print("\nPlease:")
        print("1. Open your .env file")
        print("2. Change the REDIRECT_URL to use your specific broker")
        print("3. Save the file")
        print("\nExample: If using Zerodha, change:")
        print(f"  REDIRECT_URL = '{default_value}'")
        print("to:")
        print("  REDIRECT_URL = 'http://127.0.0.1:5000/zerodha/callback'")
        sys.exit(1)

    if "<broker>" in redirect_url:
        print("\nError: Invalid REDIRECT_URL configuration detected.")
        print("The application cannot start with '<broker>' in REDIRECT_URL.")
        print("\nPlease update your .env file to use your specific broker name.")
        print("Example: http://127.0.0.1:5000/zerodha/callback")
        sys.exit(1)

    # Validate broker name
    valid_brokers_str = os.getenv("VALID_BROKERS", "")
    if not valid_brokers_str:
        print("\nError: VALID_BROKERS not configured in .env file.")
        print("\nSolution: Check the .sample.env file for the latest configuration")
        print("The application cannot start without valid broker configuration.")
        sys.exit(1)

    valid_brokers = set(broker.strip().lower() for broker in valid_brokers_str.split(","))

    try:
        import re

        match = re.search(r"/([^/]+)/callback$", redirect_url)
        if not match:
            print("\nError: Invalid REDIRECT_URL format.")
            print("The URL must end with '/broker_name/callback'")
            print("Example: http://127.0.0.1:5000/zerodha/callback")
            sys.exit(1)

        broker_name = match.group(1).lower()
        if broker_name not in valid_brokers:
            print("\nError: Invalid broker name in REDIRECT_URL.")
            print(f"Broker '{broker_name}' is not in the list of valid brokers.")
            print(f"\nValid brokers are: {', '.join(sorted(valid_brokers))}")
            print("\nPlease update your REDIRECT_URL with a valid broker name.")
            sys.exit(1)

    except Exception as e:
        print("\nError: Could not validate REDIRECT_URL format.")
        print(f"Details: {str(e)}")
        print("\nThe URL must follow the format: http://domain/broker_name/callback")
        print("Example: http://127.0.0.1:5000/zerodha/callback")
        sys.exit(1)

    # Validate rate limits format
    rate_limit_vars = [
        "LOGIN_RATE_LIMIT_MIN",
        "LOGIN_RATE_LIMIT_HOUR",
        "API_RATE_LIMIT",
        "ORDER_RATE_LIMIT",
        "SMART_ORDER_RATE_LIMIT",
        "WEBHOOK_RATE_LIMIT",
        "STRATEGY_RATE_LIMIT",
    ]
    # Single: "10 per second"
    # Compound (Flask-Limiter syntax): "10 per second;40 per minute"
    single_limit = r"\d+\s+per\s+(second|minute|hour|day)"
    rate_limit_pattern = re.compile(
        rf"^{single_limit}(;{single_limit})*$"
    )

    for var in rate_limit_vars:
        value = os.getenv(var, "")
        if not rate_limit_pattern.match(value):
            print(f"\nError: Invalid {var} format.")
            print("Format should be: 'number per timeunit'")
            print("Compound limits use semicolons: 'number per timeunit;number per timeunit'")
            print("Examples: '5 per minute', '10 per second', '10 per second;40 per minute'")
            sys.exit(1)

    # Validate SESSION_EXPIRY_TIME format (24-hour format)
    time_pattern = re.compile(r"^([01]?[0-9]|2[0-3]):[0-5][0-9]$")
    session_expiry = os.getenv("SESSION_EXPIRY_TIME", "")
    if not time_pattern.match(session_expiry):
        print("\nError: Invalid SESSION_EXPIRY_TIME format.")
        print("Format should be 24-hour time (HH:MM)")
        print("Example: '03:00', '15:30'")
        sys.exit(1)

    # Validate WEBSOCKET_URL format
    websocket_url = os.getenv("WEBSOCKET_URL", "")
    if not websocket_url.startswith("ws://") and not websocket_url.startswith("wss://"):
        print("\nError: WEBSOCKET_URL must start with 'ws://' or 'wss://'")
        print("Example: WEBSOCKET_URL='ws://localhost:8765'")
        sys.exit(1)

    # Validate logging configuration
    log_to_file = os.getenv("LOG_TO_FILE", "").lower()
    if log_to_file not in ["true", "false"]:
        print("\nError: LOG_TO_FILE must be 'True' or 'False'")
        print("Example: LOG_TO_FILE=False")
        sys.exit(1)

    log_level = os.getenv("LOG_LEVEL", "").upper()
    valid_log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    if log_level not in valid_log_levels:
        print(f"\nError: LOG_LEVEL must be one of: {', '.join(valid_log_levels)}")
        print("Example: LOG_LEVEL=INFO")
        sys.exit(1)

    # Validate LOG_RETENTION is a positive integer
    try:
        retention = int(os.getenv("LOG_RETENTION", "0"))
        if retention < 1:
            raise ValueError
    except ValueError:
        print("\nError: LOG_RETENTION must be a positive integer (days)")
        print("Example: LOG_RETENTION=14")
        sys.exit(1)

    # Validate LOG_DIR is not empty
    log_dir = os.getenv("LOG_DIR", "").strip()
    if not log_dir:
        print("\nError: LOG_DIR cannot be empty")
        print("Example: LOG_DIR=log")
        sys.exit(1)

    # Validate LOG_FORMAT is not empty
    log_format = os.getenv("LOG_FORMAT", "").strip()
    if not log_format:
        print("\nError: LOG_FORMAT cannot be empty")
        print("Example: LOG_FORMAT=[%(asctime)s] %(levelname)s in %(module)s: %(message)s")
        sys.exit(1)
