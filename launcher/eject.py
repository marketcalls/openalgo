"""Reset an installation to a fresh install, keeping the dependencies.

Used by the panel's "Reset to fresh install" button, and usable by hand:

    python -m launcher.eject --dry-run
    python -m launcher.eject --broker zerodha
    python -m launcher.eject --broker zerodha --remove-scripts --remove-history

What it removes is decided by ``launcher.state``. What it never touches: the
source, ``.venv``, ``frontend/dist``, ``custom_brand``, and anything outside the
app folder. So the next start needs no download and no install step: it creates
empty databases, and the client creates a login and logs in to the broker.

**A reset always names the new broker.** The app refuses to start until
``.env`` names one (``REDIRECT_URL`` picks it, and some brokers' key formats are
checked at start-up), so a reset that left none would leave an installation
that cannot start. That is also what a reset is for: switching broker.

The order is what makes it safe:

1. Refuse unless the broker entry would let the app start, and unless the
   server is stopped. Its ports must be free, and on Windows
   a database the server still has open cannot be moved anyway.
2. Back everything up to a zip, before touching anything.
3. Move every item into one staging folder. Renames on one drive are instant,
   and if any one fails (a file still open), every item already moved is put
   back and nothing has changed. All or nothing.
4. Write a fresh ``.env`` from ``.sample.env``, keeping the network settings.
5. Delete the staging folder.

Standard library only; see ``launcher/__init__.py``.
"""

import argparse
import getpass
import os
import shutil
import socket
import stat
import sys
import time
import zipfile
from pathlib import Path

if __package__ in (None, ""):  # run as a file rather than with -m
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from launcher import envfile, state
from launcher.branding import display_name

#: How many ``before-reset`` backups to keep. Older ones are deleted.
KEEP_BACKUPS = 5

BACKUP_PREFIX = "before-reset-"
STAGING_PREFIX = ".reset-"


class ResetRefused(Exception):
    """The reset did not start, or rolled back; nothing has changed. The message is for the client."""


def _env_values(root: Path) -> dict[str, str]:
    env = root / ".env"
    if not env.is_file():
        return {}
    return envfile.read_values(env.read_text(encoding="utf-8", errors="replace"))


def busy_ports(root: Path) -> list[int]:
    """The server's ports that something is listening on right now."""
    values = _env_values(root)
    busy = []
    for key, default in (("FLASK_PORT", "5000"), ("WEBSOCKET_PORT", "8765"), ("ZMQ_PORT", "5555")):
        try:
            port = int(values.get(key, default))
        except ValueError:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                busy.append(port)
    return busy


def default_backup_dir(root: Path) -> Path | None:
    """``C:\\FastAlgo\\backups`` in the desktop layout (``uv.exe`` beside ``app``), else None."""
    if (root.parent / "uv.exe").exists():
        return root.parent / "backups"
    return None


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("bytes", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "bytes" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} bytes"


def backup(root: Path, items: list[state.Item], backup_dir: Path) -> Path:
    """Zip every non-cache item to ``backup_dir`` and prune old backups."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"{BACKUP_PREFIX}{stamp}.zip"
    partial = target.with_suffix(".zip.partial")
    with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for item in items:
            if item.cache:
                continue
            path = root / item.rel
            if item.is_dir:
                for dirpath, _dirs, files in os.walk(path):
                    for name in files:
                        full = Path(dirpath) / name
                        zf.write(full, full.relative_to(root).as_posix())
            else:
                zf.write(path, item.rel)
    os.replace(partial, target)

    old = sorted(backup_dir.glob(f"{BACKUP_PREFIX}*.zip"))[:-KEEP_BACKUPS]
    for path in old:
        try:
            path.unlink()
        except OSError:
            pass
    return target


def _stage(root: Path, items: list[state.Item], staging: Path) -> None:
    """Move every item under ``staging``, or none of them."""
    name = display_name(root)
    moved = []
    try:
        for item in items:
            dest = staging / item.rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.rename(root / item.rel, dest)
            moved.append(item)
    except OSError as e:
        for item in reversed(moved):
            try:
                os.rename(staging / item.rel, root / item.rel)
            except OSError:
                pass
        shutil.rmtree(staging, ignore_errors=True)
        raise ResetRefused(
            f"A file is still in use: {item.rel}. Close {name}, any strategy "
            "windows and any program that has this file open, then try again. "
            "Nothing was changed."
        ) from e


def _force_remove(func, path, _exc):
    # Read-only files (git objects, some broker downloads) refuse deletion on
    # Windows until the flag is cleared.
    os.chmod(path, stat.S_IWRITE)
    func(path)


def reset(
    broker: envfile.Broker,
    root: Path = state.APP_ROOT,
    keep: set[str] | frozenset[str] = frozenset(state.KEEP_OPTIONS),
    backup_dir: Path | None = None,
) -> tuple[state.Plan, Path | None]:
    """Reset ``root`` and switch it to ``broker``. Returns the plan carried out and the backup written.

    Raises ResetRefused, with nothing changed, when the broker entry would stop
    the app starting, the server is running, a file is in use, or the release's
    files cannot be identified.
    """
    name = display_name(root)
    sample = root / ".sample.env"
    if not sample.is_file():
        raise ResetRefused(
            "This installation is missing .sample.env, so a fresh settings file cannot be made."
        )
    sample_text = sample.read_text(encoding="utf-8")
    problem = envfile.broker_problem(
        broker, envfile.read_values(sample_text).get("VALID_BROKERS", "")
    )
    if problem:
        raise ResetRefused(f"{problem} Nothing was changed.")

    busy = busy_ports(root)
    if busy:
        raise ResetRefused(
            f"{name} is still running (port {', '.join(map(str, busy))} is in use). "
            "Stop it in the panel, then try again. Nothing was changed."
        )
    try:
        the_plan = state.plan(root, keep)
    except state.NoReleaseList as e:
        raise ResetRefused(
            "This installation has no list of its shipped files, so the reset cannot tell your "
            "data apart from the program. Nothing was changed. Contact support."
        ) from e

    env_path = root / ".env"
    current_env = (
        env_path.read_text(encoding="utf-8", errors="replace") if env_path.is_file() else None
    )

    written = backup(root, the_plan.items, backup_dir) if backup_dir is not None else None

    staging = root / f"{STAGING_PREFIX}{time.strftime('%Y%m%d-%H%M%S')}"
    _stage(root, the_plan.items, staging)

    try:
        fresh = envfile.fresh_env(sample_text, broker, current_env)
        tmp = env_path.with_name(".env.reset-tmp")
        tmp.write_text(fresh, encoding="utf-8", newline="\n")
        os.replace(tmp, env_path)
    except OSError as e:
        # Put everything back: a reset with no settings file is worse than none.
        for item in the_plan.items:
            try:
                os.rename(staging / item.rel, root / item.rel)
            except OSError:
                pass
        raise ResetRefused(
            "The new settings file could not be written. Nothing was changed."
        ) from e

    try:
        shutil.rmtree(staging, onexc=_force_remove)
    except OSError:
        # The reset itself is complete: everything is out of the app's way and
        # the new .env is in place. A leftover .reset-* folder is gitignored and
        # safe to delete by hand.
        pass
    return the_plan, written


def _print_plan(the_plan: state.Plan, keep: set[str], name: str) -> None:
    print("These will be removed:")
    for item in the_plan.items:
        kind = "folder" if item.is_dir else "file"
        print(f"  {item.rel}  ({kind}, {human_size(item.size)})")
    if not the_plan.items:
        print("  nothing: this installation is already fresh")
    print(f"Total: {human_size(the_plan.total_size)}")
    print("Kept: the program, its dependencies, and branding.")
    if "scripts" in keep:
        print("Kept: your strategy scripts and chart indicators.")
    if "history" in keep:
        print("Kept: downloaded historical data.")
    for path in the_plan.outside:
        print(f"Left alone (outside the {name} folder): {path}")


def _secret(prompt: str) -> str:
    """Read a secret without echo at a keyboard, or as a plain line when input is piped.

    On Windows ``getpass`` reads the console keyboard directly and ignores
    stdin, so a script piping its answers in would wait forever.
    """
    if sys.stdin is not None and sys.stdin.isatty():
        return getpass.getpass(prompt)
    return input(prompt)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m launcher.eject",
        description="Reset to a fresh install, keeping the dependencies.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="show what would be removed, change nothing"
    )
    parser.add_argument(
        "--remove-scripts", action="store_true", help="also remove strategy scripts and indicators"
    )
    parser.add_argument(
        "--remove-history", action="store_true", help="also remove downloaded historical data"
    )
    parser.add_argument("--backup-dir", type=Path, help="where the backup zip goes")
    parser.add_argument("--broker", help="the broker to switch to, for example zerodha")
    parser.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    parser.add_argument("--app-root", type=Path, default=state.APP_ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    root = args.app_root.resolve()
    keep = set(state.KEEP_OPTIONS)
    if args.remove_scripts:
        keep.discard("scripts")
    if args.remove_history:
        keep.discard("history")

    try:
        the_plan = state.plan(root, keep)
    except state.NoReleaseList:
        print("This installation has no list of its shipped files. Contact support.")
        return 1
    name = display_name(root)
    _print_plan(the_plan, keep, name)
    if args.dry_run:
        return 0

    backup_dir = args.backup_dir or default_backup_dir(root)
    if backup_dir is None:
        print("Pass --backup-dir: there is no default backup folder outside the desktop install.")
        return 1

    try:
        name = (args.broker or input("Broker to switch to (for example zerodha): ")).strip().lower()
        api_key = input("Broker API key: ")
        api_secret = _secret("Broker API secret: ")
        market_key = market_secret = ""
        if name in envfile.XTS_BROKERS:
            market_key = input("Market data API key: ")
            market_secret = _secret("Market data API secret: ")
        broker = envfile.Broker(name, api_key, api_secret, market_key, market_secret)
        if (
            not args.yes
            and input("Type RESET to remove these and start fresh: ").strip() != "RESET"
        ):
            print("Cancelled. Nothing was changed.")
            return 1
    except EOFError:
        print("Cancelled. Nothing was changed.")
        return 1

    try:
        _done, written = reset(broker, root, keep, backup_dir)
    except ResetRefused as e:
        print(e)
        return 1
    print(f"Backup saved to {written}")
    print(f"Done. Start {name}, create your login, then log in to {broker.name}.")
    print(f"Your broker app's redirect URL must be: {_env_values(root).get('REDIRECT_URL', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
