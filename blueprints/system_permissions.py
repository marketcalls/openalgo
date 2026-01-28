# blueprints/system_permissions.py
"""
System permissions monitoring API.
Checks file and directory permissions for OpenAlgo components.
Cross-platform compatible (Windows, Linux, macOS).
"""

import os
import platform
import stat

from flask import Blueprint, jsonify

from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

system_permissions_bp = Blueprint("system_permissions_bp", __name__, url_prefix="/api/system")


def get_permission_checks():
    """
    Get permission checks list dynamically from environment variables.
    This allows database paths to be configured in .env file.
    """

    # Extract database paths from environment variables
    # Format: 'sqlite:///db/openalgo.db' -> 'db/openalgo.db'
    def extract_db_path(env_var, default):
        value = os.getenv(env_var, default)
        if value.startswith("sqlite:///"):
            return value[len("sqlite:///") :]
        return value

    main_db = extract_db_path("DATABASE_URL", "db/openalgo.db")
    latency_db = extract_db_path("LATENCY_DATABASE_URL", "db/latency.db")
    logs_db = extract_db_path("LOGS_DATABASE_URL", "db/logs.db")
    sandbox_db = extract_db_path("SANDBOX_DATABASE_URL", "db/sandbox.db")
    historify_db = os.getenv("HISTORIFY_DATABASE_URL", "db/historify.duckdb")

    # Extract db directory from main database path
    db_dir = os.path.dirname(main_db) if main_db else "db"

    # Define expected permissions for each path
    # Format: (relative_path, expected_unix_mode, description, is_sensitive)
    return [
        (db_dir, 0o755, "Database directory", False),
        (main_db, 0o644, "Main database file (SQLite)", False),
        (latency_db, 0o644, "Latency database file (SQLite)", False),
        (logs_db, 0o644, "Logs database file (SQLite)", False),
        (sandbox_db, 0o644, "Sandbox database file (SQLite)", False),
        (historify_db, 0o644, "Historical data database (DuckDB)", False),
        (".env", 0o600, "Environment configuration (sensitive)", True),
        ("log", 0o755, "Log directory", False),
        ("log/strategies", 0o755, "Strategy logs directory", False),
        ("keys", 0o700, "Encryption keys directory (sensitive)", True),
        ("strategies", 0o755, "Strategies directory", False),
        ("strategies/scripts", 0o755, "Strategy scripts directory", False),
        ("strategies/examples", 0o755, "Strategy examples directory", False),
        ("tmp", 0o755, "Temporary files directory", False),
    ]


def get_base_path():
    """Get the base path of the OpenAlgo application."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def format_permission(mode: int) -> str:
    """Format permission mode as octal string (e.g., '755')."""
    return oct(mode)[-3:]


def format_permission_rwx(mode: int) -> str:
    """Format permission mode as rwx string (e.g., 'rwxr-xr-x')."""
    result = ""
    for who in range(2, -1, -1):  # owner, group, others
        shift = who * 3
        r = "r" if (mode >> shift) & 4 else "-"
        w = "w" if (mode >> shift) & 2 else "-"
        x = "x" if (mode >> shift) & 1 else "-"
        result += r + w + x
    return result


def get_unix_permissions(path: str) -> dict:
    """Get Unix-style permissions for a path."""
    try:
        st = os.stat(path)
        mode = stat.S_IMODE(st.st_mode)
        is_dir = stat.S_ISDIR(st.st_mode)
        return {
            "mode": mode,
            "mode_octal": format_permission(mode),
            "mode_rwx": format_permission_rwx(mode),
            "is_directory": is_dir,
            "owner_uid": st.st_uid,
            "group_gid": st.st_gid,
        }
    except Exception as e:
        logger.exception(f"Error getting permissions for {path}: {e}")
        return None


def get_windows_permissions(path: str) -> dict:
    """Get Windows-style permissions for a path (access-based check)."""
    try:
        is_dir = os.path.isdir(path)
        readable = os.access(path, os.R_OK)
        writable = os.access(path, os.W_OK)
        executable = os.access(path, os.X_OK) if is_dir else True  # X for dirs means listable

        # Construct a pseudo-mode based on access
        mode = 0
        if readable:
            mode |= 0o444
        if writable:
            mode |= 0o222
        if executable:
            mode |= 0o111

        return {
            "mode": mode,
            "mode_octal": format_permission(mode),
            "mode_rwx": format_permission_rwx(mode),
            "is_directory": is_dir,
            "readable": readable,
            "writable": writable,
            "executable": executable,
        }
    except Exception as e:
        logger.exception(f"Error getting Windows permissions for {path}: {e}")
        return None


def check_permission(path: str, expected_mode: int, is_sensitive: bool) -> dict:
    """
    Check if a path has the expected permissions.

    Returns dict with status and details.
    """
    base_path = get_base_path()
    full_path = os.path.join(base_path, path)
    is_windows = platform.system() == "Windows"

    result = {
        "path": path,
        "full_path": full_path,
        "exists": os.path.exists(full_path),
        "expected_mode": format_permission(expected_mode),
        "expected_rwx": format_permission_rwx(expected_mode),
        "is_sensitive": is_sensitive,
        "is_correct": False,
        "issue": None,
        "warning": None,  # Warnings don't affect is_correct
        "actual_mode": None,
        "actual_rwx": None,
    }

    if not result["exists"]:
        result["issue"] = "Path does not exist"
        return result

    if is_windows:
        perms = get_windows_permissions(full_path)
        if perms:
            result["actual_mode"] = perms["mode_octal"]
            result["actual_rwx"] = perms["mode_rwx"]
            result["is_directory"] = perms["is_directory"]
            result["readable"] = perms["readable"]
            result["writable"] = perms["writable"]

            # On Windows, check functional access instead of exact mode
            is_dir = perms["is_directory"]
            needs_write = (expected_mode & 0o200) != 0
            needs_read = (expected_mode & 0o400) != 0

            if needs_read and not perms["readable"]:
                result["issue"] = "Not readable"
            elif needs_write and not perms["writable"]:
                result["issue"] = "Not writable"
            else:
                result["is_correct"] = True
    else:
        perms = get_unix_permissions(full_path)
        if perms:
            result["actual_mode"] = perms["mode_octal"]
            result["actual_rwx"] = perms["mode_rwx"]
            result["is_directory"] = perms["is_directory"]

            actual_mode = perms["mode"]

            # For sensitive files, check exact permissions
            if is_sensitive:
                if actual_mode != expected_mode:
                    result["issue"] = (
                        f"Permission should be {format_permission(expected_mode)}, currently {format_permission(actual_mode)}"
                    )
                else:
                    result["is_correct"] = True
            else:
                # For non-sensitive, check if at least the required permissions are set
                # Owner should have at least the expected permissions
                owner_expected = (expected_mode >> 6) & 0o7
                owner_actual = (actual_mode >> 6) & 0o7

                if (owner_actual & owner_expected) != owner_expected:
                    result["issue"] = (
                        f"Owner permission should be at least {oct(owner_expected)[2:]}, currently {oct(owner_actual)[2:]}"
                    )
                else:
                    result["is_correct"] = True

                    # Warn if permissions are too open (world writable)
                    # This is a warning, not an error - doesn't affect is_correct
                    others_perm = actual_mode & 0o7
                    if others_perm & 0o2:  # World writable
                        result["warning"] = "World writable - consider restricting permissions"

    return result


@system_permissions_bp.route("/permissions", methods=["GET"])
@check_session_validity
def get_permissions():
    """Get permission status for all monitored paths."""
    try:
        is_windows = platform.system() == "Windows"
        base_path = get_base_path()

        results = []
        all_correct = True

        for path, expected_mode, description, is_sensitive in get_permission_checks():
            check = check_permission(path, expected_mode, is_sensitive)
            check["description"] = description
            results.append(check)

            if not check["is_correct"]:
                all_correct = False

        return jsonify(
            {
                "status": "success",
                "data": {
                    "platform": platform.system(),
                    "base_path": base_path,
                    "is_windows": is_windows,
                    "all_correct": all_correct,
                    "checks": results,
                },
            }
        )
    except Exception as e:
        logger.exception(f"Error checking permissions: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@system_permissions_bp.route("/permissions/fix", methods=["POST"])
@check_session_validity
def fix_permissions():
    """
    Attempt to fix permission issues.
    Only fixes paths within the application directory.
    Does NOT use elevated permissions - only fixes what current user can fix.
    """
    try:
        base_path = get_base_path()
        is_windows = platform.system() == "Windows"

        fixed = []
        failed = []

        for path, expected_mode, description, is_sensitive in get_permission_checks():
            full_path = os.path.join(base_path, path)

            # Skip if path doesn't exist - we'll create directories but not files
            if not os.path.exists(full_path):
                # Try to create directory if it's supposed to be a directory
                if expected_mode & 0o100:  # Has execute bit = likely directory
                    try:
                        os.makedirs(full_path, mode=expected_mode, exist_ok=True)
                        fixed.append(
                            {
                                "path": path,
                                "action": "created directory",
                                "mode": format_permission(expected_mode),
                            }
                        )
                    except Exception as e:
                        failed.append({"path": path, "error": f"Could not create directory: {e}"})
                continue

            # On Windows, we can't set Unix-style permissions
            if is_windows:
                # Check if there's an access issue that we should report
                readable = os.access(full_path, os.R_OK)
                writable = os.access(full_path, os.W_OK)
                needs_read = (expected_mode & 0o400) != 0
                needs_write = (expected_mode & 0o200) != 0

                if (needs_read and not readable) or (needs_write and not writable):
                    failed.append(
                        {
                            "path": path,
                            "error": "Access issue detected. Use Windows file properties to adjust permissions.",
                        }
                    )
                # Skip chmod operations on Windows
                continue

            # On Unix, try to set correct permissions
            try:
                current_mode = stat.S_IMODE(os.stat(full_path).st_mode)
                if current_mode != expected_mode:
                    os.chmod(full_path, expected_mode)
                    fixed.append(
                        {
                            "path": path,
                            "action": "changed permissions",
                            "from": format_permission(current_mode),
                            "to": format_permission(expected_mode),
                        }
                    )
            except PermissionError:
                failed.append(
                    {
                        "path": path,
                        "error": "Permission denied - run with appropriate user privileges",
                    }
                )
            except Exception as e:
                failed.append({"path": path, "error": str(e)})

        return jsonify(
            {
                "status": "success",
                "data": {
                    "fixed": fixed,
                    "failed": failed,
                    "message": f"Fixed {len(fixed)} items, {len(failed)} failed"
                    if fixed or failed
                    else "No changes needed",
                },
            }
        )
    except Exception as e:
        logger.exception(f"Error fixing permissions: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
