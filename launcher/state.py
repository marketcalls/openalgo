"""What in an installation is state, and what is the release.

**State** is everything the running app, or the client, writes: settings,
databases, logs, keys, scripts. **The release** is everything we shipped. The
reset deletes state; the in-place update (M3.6) will keep it. One list serves
both, so the two can never disagree about a file.

The list is folders plus a rule, not files: inside a state folder, any file
that the release did not ship is state. That is what lets a folder hold both a
shipped ``readme.md`` and the client's logs, and it means a new database or log
file that lands in one of these folders is covered without anyone remembering
to add it. A runtime file written *outside* them is not, which is what
``test/test_launcher_reset.py`` guards.

Which files the release shipped comes from ``RELEASE_FILES`` at the app root,
written by the release build, one path per line. A development checkout has no
such file and uses ``git ls-files`` instead. With neither, nothing can be told
apart, and the reset refuses rather than guess.

Standard library only; see ``launcher/__init__.py``.
"""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from launcher import envfile

#: The app root: the folder holding app.py.
APP_ROOT = Path(__file__).resolve().parent.parent

RELEASE_LIST = "RELEASE_FILES"

#: Folders whose unshipped contents are state. Each entry is relative to the
#: app root, in forward-slash form. Sources, from the runtime-write inventory
#: done for M3.2:
#:   db        every SQLite database, agent.db, historify, chatgpt_oauth tokens,
#:             WhatsApp attachments allowlist
#:   log       errors.jsonl, mcp.jsonl, dated app logs, strategy logs, proxy stats
#:   logs      the Angel streaming client's own logzero files (relative to cwd)
#:   keys      MCP OAuth signing keys
#:   tmp       broker master contract downloads
#:   workspace the client's notes, research and backtests
#:   strategies  scripts, their .bak copies, strategy_configs.json, indicators
#:   ~         provider tokens LiteLLM writes when HOME is unset
STATE_DIRS = ("db", "log", "logs", "keys", "tmp", "workspace", "strategies", "~")

#: Single files at the root that are state.
#:   .env              broker keys, secrets, ports; rewritten by the reset
#:   agent_kill_switch the agent's trading kill switch; a fresh install has none
STATE_FILES = (".env", "agent_kill_switch")

#: Caches the app recreates. Deleted so a reset leaves nothing behind, never
#: kept, never backed up.
CACHE_DIRS = (".numba_cache", ".llvm_tmp")

#: What the client may choose to keep through a reset. Each option is a set of
#: path prefixes; a path at or under one is left alone.
KEEP_OPTIONS = {
    "scripts": ("strategies/scripts", "strategies/indicators", "strategies/strategy_configs.json"),
    # The .wal holds writes not yet merged into the main file, and .tmp is
    # DuckDB's spill folder: keeping the database without them loses data.
    "history": ("db/historify.duckdb", "db/historify.duckdb.wal", "db/historify.duckdb.tmp"),
}

#: ``.env`` keys that can move a database or log folder away from the defaults
#: above. A path they name inside the app root but outside STATE_DIRS is added
#: as state; one outside the app root is reported and left alone.
PATH_KEYS = (
    "DATABASE_URL",
    "LOGS_DATABASE_URL",
    "LATENCY_DATABASE_URL",
    "HEALTH_DATABASE_URL",
    "SANDBOX_DATABASE_URL",
    "HISTORIFY_DATABASE_PATH",
    "LOG_DIR",
    "WS_PROXY_STATS_FILE",
    "MCP_OAUTH_KEYS_DIR",
)


class NoReleaseList(Exception):
    """Neither RELEASE_FILES nor a git checkout: shipped files cannot be told apart."""


@dataclass(frozen=True)
class Item:
    """One path the reset removes. A folder is removed whole."""

    rel: str
    is_dir: bool
    size: int
    cache: bool = False


@dataclass
class Plan:
    items: list[Item]
    outside: list[str]  # configured paths outside the app root, left alone
    shipped_source: str

    @property
    def total_size(self) -> int:
        return sum(item.size for item in self.items)


def shipped_files(root: Path) -> tuple[set[str], str]:
    """The release's files, relative to ``root`` in forward-slash form, and where the list came from."""
    listing = root / RELEASE_LIST
    if listing.is_file():
        lines = listing.read_text(encoding="utf-8").splitlines()
        return {line.strip() for line in lines if line.strip()}, RELEASE_LIST
    if (root / ".git").exists():
        try:
            out = subprocess.run(
                ["git", "ls-files", "-z"],
                cwd=root,
                capture_output=True,
                check=True,
                timeout=60,
            ).stdout
        except (OSError, subprocess.SubprocessError) as e:
            raise NoReleaseList(f"git ls-files failed: {e}") from e
        return {p for p in out.decode("utf-8").split("\0") if p}, "git"
    raise NoReleaseList(f"no {RELEASE_LIST} and no git checkout at {root}")


def _size(path: Path) -> int:
    if path.is_symlink() or not path.is_dir():
        try:
            return path.lstat().st_size
        except OSError:
            return 0
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_size
            except OSError:
                pass
    return total


def _under(rel: str, prefix: str) -> bool:
    return rel == prefix or rel.startswith(prefix + "/")


class _Walker:
    def __init__(self, root: Path, shipped: set[str], keep: tuple[str, ...]):
        self.root = root
        self.keep = keep
        self.shipped = shipped
        # Every folder that holds a shipped file somewhere below it.
        self.shipped_dirs = set()
        for path in shipped:
            parts = path.split("/")[:-1]
            for i in range(1, len(parts) + 1):
                self.shipped_dirs.add("/".join(parts[:i]))
        self.items: list[Item] = []

    def _kept(self, rel: str) -> bool:
        return any(_under(rel, prefix) for prefix in self.keep)

    def _holds_kept(self, rel: str) -> bool:
        return any(prefix.startswith(rel + "/") for prefix in self.keep)

    def visit(self, rel: str) -> None:
        path = self.root / rel
        if not os.path.lexists(path) or self._kept(rel):
            return
        if path.is_dir() and not path.is_symlink():
            if rel in self.shipped_dirs or self._holds_kept(rel):
                for child in sorted(os.listdir(path)):
                    self.visit(f"{rel}/{child}")
            else:
                self.items.append(Item(rel, True, _size(path)))
        elif rel not in self.shipped:
            self.items.append(Item(rel, False, _size(path)))


def _configured_paths(root: Path) -> list[str]:
    """Paths ``.env`` points databases and logs at, made relative to the root where possible."""
    env = root / ".env"
    if not env.is_file():
        return []
    values = envfile.read_values(env.read_text(encoding="utf-8", errors="replace"))
    paths = []
    for key in PATH_KEYS:
        value = values.get(key, "").strip()
        if not value:
            continue
        if value.startswith("sqlite:///"):
            value = value[len("sqlite:///") :]
        elif "://" in value:
            continue  # not a file
        paths.append(value)
    return paths


def plan(root: Path = APP_ROOT, keep: set[str] | frozenset[str] = frozenset()) -> Plan:
    """Everything a reset removes from ``root``, keeping the options named in ``keep``."""
    unknown = set(keep) - set(KEEP_OPTIONS)
    if unknown:
        raise ValueError(f"unknown keep option: {sorted(unknown)}")
    shipped, source = shipped_files(root)
    prefixes = tuple(p for name in sorted(keep) for p in KEEP_OPTIONS[name])
    walker = _Walker(root, shipped, prefixes)

    for rel in STATE_FILES + STATE_DIRS:
        walker.visit(rel)

    outside = []
    resolved_root = root.resolve()
    for value in _configured_paths(root):
        target = (root / value).resolve()
        try:
            rel = target.relative_to(resolved_root).as_posix()
        except ValueError:
            outside.append(str(target))
            continue
        if any(_under(rel, d) for d in STATE_DIRS + STATE_FILES):
            continue  # already covered by the walk
        # A database also has its journal files beside it.
        for candidate in (rel, f"{rel}-wal", f"{rel}-shm", f"{rel}-journal", f"{rel}.wal"):
            walker.visit(candidate)

    for rel in CACHE_DIRS:
        path = root / rel
        if os.path.lexists(path):
            walker.items.append(Item(rel, path.is_dir(), _size(path), cache=True))

    seen, items = set(), []
    for item in walker.items:
        if item.rel not in seen:
            seen.add(item.rel)
            items.append(item)
    return Plan(items=items, outside=outside, shipped_source=source)
