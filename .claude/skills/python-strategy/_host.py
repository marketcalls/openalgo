"""What /python gives a strategy, reproduced for the skill's tools.

Every value here is read from the host's own source rather than restated, so
the tools cannot drift from what /python actually does:

* the resource limit bootstrap and its limits (blueprints/python_strategy.py)
* how long a strategy gets after Stop before it is killed (same file)
* the exchanges a strategy can be scheduled on (database/market_calendar_db.py)
* the API key, decrypted from the database exactly as the host injects it
"""

from __future__ import annotations

import ast
import importlib.util
import os
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent
REPO = SKILL.parents[2]
BLUEPRINT = REPO / "blueprints" / "python_strategy.py"
CALENDAR = REPO / "database" / "market_calendar_db.py"
KIT = SKILL / "kit.py"
WORKSPACE = REPO / "workspace" / "execution"


def _module_constants(path: Path) -> dict[str, object]:
    """Module level NAME = <literal> assignments of a source file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                try:
                    found[target.id] = ast.literal_eval(node.value)
                except (ValueError, SyntaxError):
                    pass
    return found


def host_facts() -> dict[str, object]:
    """The host's limits, bootstrap and stop timing, from its source."""
    consts = _module_constants(BLUEPRINT)
    source = BLUEPRINT.read_text(encoding="utf-8")
    # stop_strategy_process calls terminate_popen_safely(..., terminate_timeout=N, ...)
    grace = 5.0
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and getattr(node.func, "id", None) == "terminate_popen_safely"
        ):
            for kw in node.keywords:
                if kw.arg == "terminate_timeout" and isinstance(kw.value, ast.Constant):
                    grace = float(kw.value.value)
    return {
        "bootstrap": consts["_RLIMIT_BOOTSTRAP"],
        "memory_mb": int(os.environ.get("STRATEGY_MEMORY_LIMIT_MB", "1024")),
        "cpu_seconds": consts.get("STRATEGY_CPU_TIME_LIMIT_SEC", 3600),
        "nofile": consts.get("STRATEGY_NOFILE_LIMIT", 256),
        "nproc": consts.get("STRATEGY_NPROC_LIMIT", 256),
        "stop_grace_seconds": grace,
        "scripts_dir": "strategies/scripts",
    }


def host_exchanges() -> list[str]:
    return list(_module_constants(CALENDAR)["SUPPORTED_EXCHANGES"])


def dotenv_values() -> dict[str, str]:
    from dotenv import dotenv_values as read

    path = REPO / ".env"
    return {k: v for k, v in read(path).items() if v is not None} if path.exists() else {}


def api_key(env: dict[str, str]) -> str | None:
    """The key /python would inject: OPENALGO_API_KEY if set, else the
    decrypted key from the database, as start_strategy_process does."""
    if env.get("OPENALGO_API_KEY"):
        return env["OPENALGO_API_KEY"]
    cwd = os.getcwd()
    saved = {k: os.environ.get(k) for k in env}
    try:
        os.chdir(REPO)
        os.environ.update(env)
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        import logging

        logging.disable(logging.CRITICAL)
        try:
            from database.auth_db import get_first_available_api_key

            return get_first_available_api_key()
        finally:
            logging.disable(logging.NOTSET)
    except Exception:
        return None
    finally:
        os.chdir(cwd)
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def strategy_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """The environment a /python strategy starts with: the app's own
    environment (os.environ plus .env, which the app loads) and the injected
    variables. `extra` overrides last."""
    env = {**dotenv_values(), **os.environ}
    key = api_key(env)
    if key:
        env["OPENALGO_API_KEY"] = key
    env.setdefault("OPENALGO_HOST", "http://127.0.0.1:5000")
    env.update(extra or {})
    return env


def rest_host(env: dict[str, str]) -> str:
    return (
        (env.get("HOST_SERVER") or env.get("OPENALGO_HOST") or "http://127.0.0.1:5000")
        .strip()
        .rstrip("/")
    )


def load_strategy(path: Path):
    """Import a strategy file as a module without running it."""
    if str(REPO) not in sys.path:
        sys.path.append(str(REPO))
    spec = importlib.util.spec_from_file_location(f"strategy_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def workspace_folder(path: Path) -> Path:
    """Where a tool writes its output for this strategy: beside the file."""
    return path.resolve().parent
