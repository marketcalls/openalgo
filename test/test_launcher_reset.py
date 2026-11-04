"""The desktop reset (launcher.state, launcher.eject, launcher.envfile).

Every reset here runs on a throwaway tree under ``tmp_path`` with its own
``RELEASE_FILES``. Against the real checkout only the plan is computed; nothing
is ever removed from it.
"""

import os
import re
import socket
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from launcher import eject, envfile, state

REPO = Path(__file__).resolve().parent.parent

SAMPLE_ENV = """\
ENV_CONFIG_VERSION = '1.0.7'
BROKER_API_KEY = 'YOUR_BROKER_API_KEY'
BROKER_API_SECRET = 'YOUR_BROKER_API_SECRET'
BROKER_API_KEY_MARKET = 'YOUR_BROKER_MARKET_API_KEY'
BROKER_API_SECRET_MARKET = 'YOUR_BROKER_MARKET_API_SECRET'
REDIRECT_URL = 'http://127.0.0.1:5000/<broker>/callback'  # Change if different
VALID_BROKERS = 'fivepaisa,fivepaisaxts,dhan,zerodha,upstox'
APP_KEY = 'OPENALGO_PLACEHOLDER_APP_KEY_REGENERATE_BEFORE_USE'
API_KEY_PEPPER = 'OPENALGO_PLACEHOLDER_API_KEY_PEPPER_REGENERATE_BEFORE_USE'
FERNET_SALT = 'OPENALGO_PLACEHOLDER_FERNET_SALT_REGENERATE_BEFORE_USE'
HOST_SERVER = 'http://127.0.0.1:5000'
FLASK_HOST_IP='127.0.0.1'
FLASK_PORT='5000'
WEBSOCKET_HOST='127.0.0.1'
WEBSOCKET_PORT='8765'
WEBSOCKET_URL='ws://127.0.0.1:8765'
ZMQ_PORT='5555'
CORS_ALLOWED_ORIGINS = 'http://127.0.0.1:5000'
"""

ZERODHA = envfile.Broker("zerodha", "new-key", "new-secret")

#: Shipped in the fake release, and must survive every reset.
SHIPPED = [
    "app.py",
    ".sample.env",
    "db/readme.txt",
    "log/readme.md",
    "log/strategies/.gitignore",
    "keys/.gitignore",
    "tmp/README.md",
    "strategies/README.md",
    "strategies/examples/ema_crossover.py",
    "strategies/scripts/.gitignore",
    "strategies/indicators/README.md",
    "strategies/indicators/open_range_breakout.js",
    "workspace/readme.md",
    "workspace/notes/readme.md",
    "frontend/dist/index.html",
]

#: Runtime files, one per writer found in the M3.2 inventory. All are removed by
#: a full reset.
RUNTIME = [
    ".env",
    "agent_kill_switch",
    "db/openalgo.db",
    "db/openalgo.db-wal",
    "db/openalgo.db-shm",
    "db/logs.db",
    "db/latency.db",
    "db/health.db",
    "db/sandbox.db",
    "db/agent.db",
    "db/chatgpt_oauth/auth.json",
    "db/attachments/allowed.txt",
    "log/errors.jsonl",
    "log/mcp.jsonl",
    "log/ws_proxy_stats.json",
    "log/openalgo_2026-11-05.log",
    "log/strategies/abc_20261105_IST.log",
    "logs/2026-11-05/app.log",
    "keys/mcp_oauth_k1.pem",
    "tmp/upstox.json",
    "workspace/notes/my-idea.md",
    "~/.config/litellm/token.json",
]
SCRIPTS = [
    "strategies/scripts/my_strategy.py",
    "strategies/scripts/my_strategy.py.bak",
    "strategies/indicators/my_indicator.js",
    "strategies/strategy_configs.json",
]
HISTORY = ["db/historify.duckdb", "db/historify.duckdb.wal"]
CACHES = [".numba_cache/x.nbi", ".llvm_tmp/y"]
DEPENDENCIES = [".venv/Lib/site-packages/flask/__init__.py", "custom_brand/brand.json"]


def _write(root: Path, rel: str, text: str = "x") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def install(tmp_path, monkeypatch):
    """A fake desktop install: C:\\FastAlgo\\{uv.exe, app\\}."""
    home = tmp_path / "FastAlgo"
    root = home / "app"
    for rel in SHIPPED:
        _write(root, rel, SAMPLE_ENV if rel == ".sample.env" else "shipped")
    for rel in RUNTIME + SCRIPTS + HISTORY + CACHES + DEPENDENCIES:
        _write(root, rel)
    env = envfile.set_value(SAMPLE_ENV, "FLASK_PORT", "5099")
    env = envfile.set_value(env, "FLASK_HOST_IP", "0.0.0.0")
    env = envfile.set_value(env, "BROKER_API_KEY", "old-broker-key")
    env = envfile.set_value(env, "REDIRECT_URL", "http://127.0.0.1:5099/upstox/callback")
    env = envfile.set_value(env, "APP_KEY", "old-app-key")
    # Ports nobody listens on, so the running-server check passes.
    for key, port in (("WEBSOCKET_PORT", "1"), ("ZMQ_PORT", "2")):
        env = envfile.set_value(env, key, port)
    _write(root, ".env", env)
    (root / state.RELEASE_LIST).write_text(
        "\n".join(SHIPPED + [state.RELEASE_LIST]) + "\n", encoding="utf-8"
    )
    _write(home, "uv.exe")
    monkeypatch.setattr(eject, "busy_ports", lambda _root: [])
    return root


def _exists(root: Path, rels) -> list[str]:
    return [rel for rel in rels if (root / rel).exists()]


# --- the plan --------------------------------------------------------------


def test_full_reset_plan_covers_every_runtime_writer(install):
    planned = state.plan(install, keep=set())
    removed = {item.rel for item in planned.items}

    def covered(rel):
        return any(rel == r or rel.startswith(r + "/") for r in removed)

    missing = [rel for rel in RUNTIME + SCRIPTS + HISTORY + CACHES if not covered(rel)]
    assert missing == []
    assert [rel for rel in SHIPPED + DEPENDENCIES if covered(rel)] == []


def test_folders_with_nothing_shipped_go_whole(install):
    removed = {item.rel for item in state.plan(install, keep=set()).items}
    assert {"db/chatgpt_oauth", "logs", "~"} <= removed
    assert "db" not in removed and "log/strategies" not in removed


def test_keep_options_leave_scripts_and_history(install):
    removed = {item.rel for item in state.plan(install, keep={"scripts", "history"}).items}
    for rel in SCRIPTS + HISTORY:
        assert not any(rel == r or rel.startswith(r + "/") for r in removed), rel


def test_configured_database_outside_state_dirs_is_removed(install):
    env = (install / ".env").read_text(encoding="utf-8")
    (install / ".env").write_text(
        env + "SANDBOX_DATABASE_URL = 'sqlite:///data/sandbox.db'\n", encoding="utf-8"
    )
    _write(install, "data/sandbox.db")
    _write(install, "data/sandbox.db-wal")
    removed = {item.rel for item in state.plan(install).items}
    assert {"data/sandbox.db", "data/sandbox.db-wal"} <= removed


def test_no_release_list_refuses(install):
    (install / state.RELEASE_LIST).unlink()
    with pytest.raises(eject.ResetRefused):
        eject.reset(ZERODHA, install, backup_dir=install.parent / "backups")
    assert _exists(install, RUNTIME) == RUNTIME


def test_real_checkout_plan_never_touches_a_tracked_file():
    """Against this repository: nothing git tracks is ever in the plan."""
    if not (REPO / ".git").exists():
        pytest.skip("not a git checkout")
    tracked = set(
        subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True)
        .stdout.decode()
        .split("\0")
    )
    for item in state.plan(REPO, keep=set()).items:
        assert item.rel not in tracked, item.rel
        if item.is_dir:
            assert not any(t.startswith(item.rel + "/") for t in tracked), item.rel


# --- the reset -------------------------------------------------------------


def test_reset_keeps_scripts_and_history_by_default(install):
    backups = install.parent / "backups"
    _plan, written = eject.reset(ZERODHA, install, backup_dir=backups)

    assert _exists(install, [r for r in RUNTIME if r != ".env"]) == []
    assert _exists(install, CACHES) == []
    assert (
        _exists(install, SHIPPED + DEPENDENCIES + SCRIPTS + HISTORY)
        == SHIPPED + DEPENDENCIES + SCRIPTS + HISTORY
    )
    assert not list(install.glob(f"{eject.STAGING_PREFIX}*"))

    with zipfile.ZipFile(written) as zf:
        names = set(zf.namelist())
    assert {"db/openalgo.db", ".env", "~/.config/litellm/token.json"} <= names
    assert not any(n.startswith(".numba_cache") for n in names)
    assert not names & set(SCRIPTS + HISTORY)


def test_reset_can_remove_scripts_and_history(install):
    eject.reset(ZERODHA, install, keep=set(), backup_dir=install.parent / "backups")
    assert _exists(install, SCRIPTS + HISTORY) == []
    assert _exists(install, SHIPPED) == SHIPPED


def test_reset_writes_a_fresh_env_keeping_the_network(install):
    eject.reset(ZERODHA, install, backup_dir=install.parent / "backups")
    values = envfile.read_values((install / ".env").read_text(encoding="utf-8"))
    assert values["BROKER_API_KEY"] == "new-key"
    assert values["BROKER_API_SECRET"] == "new-secret"
    assert values["BROKER_API_KEY_MARKET"] == "YOUR_BROKER_MARKET_API_KEY"
    assert values["APP_KEY"] not in ("old-app-key", envfile.PLACEHOLDER_APP_KEY)
    assert len(values["APP_KEY"]) == 64 and len(values["API_KEY_PEPPER"]) == 64
    assert values["FERNET_SALT"].startswith("OPENALGO_PLACEHOLDER")
    assert values["FLASK_PORT"] == "5099"
    assert values["FLASK_HOST_IP"] == "0.0.0.0"
    assert values["REDIRECT_URL"] == "http://127.0.0.1:5099/zerodha/callback"


def test_old_backups_are_pruned(install):
    backups = install.parent / "backups"
    backups.mkdir()
    for i in range(7):
        (backups / f"{eject.BACKUP_PREFIX}2026010{i}-000000.zip").write_bytes(b"")
    eject.reset(ZERODHA, install, backup_dir=backups)
    assert len(list(backups.glob(f"{eject.BACKUP_PREFIX}*.zip"))) == eject.KEEP_BACKUPS


def test_running_server_refuses_and_changes_nothing(install, monkeypatch):
    monkeypatch.undo()  # the real busy_ports
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        env = envfile.set_value(
            (install / ".env").read_text(encoding="utf-8"), "FLASK_PORT", str(port)
        )
        (install / ".env").write_text(env, encoding="utf-8")
        with pytest.raises(eject.ResetRefused, match="still running"):
            eject.reset(ZERODHA, install, backup_dir=install.parent / "backups")
    assert _exists(install, RUNTIME) == RUNTIME
    assert not (install.parent / "backups").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="an open file blocks a rename only on Windows")
def test_file_in_use_rolls_back_everything(install):
    with open(install / "log" / "errors.jsonl", "a", encoding="utf-8"):
        with pytest.raises(eject.ResetRefused, match="in use"):
            eject.reset(ZERODHA, install, backup_dir=install.parent / "backups")
    assert (
        _exists(install, RUNTIME + SCRIPTS + HISTORY + CACHES)
        == RUNTIME + SCRIPTS + HISTORY + CACHES
    )
    assert not list(install.glob(f"{eject.STAGING_PREFIX}*"))
    assert (
        envfile.read_values((install / ".env").read_text(encoding="utf-8"))["BROKER_API_KEY"]
        == "old-broker-key"
    )


# --- the CLI -------------------------------------------------------------


def test_cli_dry_run_changes_nothing(install, capsys):
    assert eject.main(["--dry-run", "--app-root", str(install)]) == 0
    assert "db/openalgo.db" in capsys.readouterr().out
    assert _exists(install, RUNTIME) == RUNTIME


def _answers(monkeypatch, *answers):
    replies = iter(answers)
    monkeypatch.setattr("builtins.input", lambda _p="": next(replies))
    monkeypatch.setattr(eject, "_secret", lambda _p="": next(replies))


def test_cli_needs_the_word_reset(install, monkeypatch):
    _answers(monkeypatch, "zerodha", "key", "secret", "yes")
    assert eject.main(["--app-root", str(install)]) == 1
    assert _exists(install, RUNTIME) == RUNTIME


def test_cli_reset_uses_the_desktop_backup_folder(install, monkeypatch):
    _answers(monkeypatch, "key", "secret", "RESET")
    assert eject.main(["--broker", "Zerodha", "--app-root", str(install)]) == 0
    assert len(list((install.parent / "backups").glob("*.zip"))) == 1
    values = envfile.read_values((install / ".env").read_text(encoding="utf-8"))
    assert values["REDIRECT_URL"].endswith("/zerodha/callback")


def test_cli_asks_xts_brokers_for_market_keys(install, monkeypatch):
    _answers(monkeypatch, "key", "secret", "mkey", "msecret", "RESET")
    assert eject.main(["--broker", "fivepaisaxts", "--app-root", str(install)]) == 0
    values = envfile.read_values((install / ".env").read_text(encoding="utf-8"))
    assert (values["BROKER_API_KEY_MARKET"], values["BROKER_API_SECRET_MARKET"]) == (
        "mkey",
        "msecret",
    )


# --- the broker check --------------------------------------------------------


@pytest.mark.parametrize(
    ("broker", "problem"),
    [
        (envfile.Broker("notabroker", "k", "s"), "not a broker"),
        (envfile.Broker("zerodha", "k", " "), "both the API key and the API secret"),
        (envfile.Broker("dhan", "no-separator", "s"), "client_id:::api_key"),
        (envfile.Broker("fivepaisa", "a:::b", "s"), "User_Key:::User_ID:::client_id"),
        (envfile.Broker("fivepaisaxts", "k", "s"), "market data"),
    ],
)
def test_a_broker_the_app_would_refuse_changes_nothing(install, broker, problem):
    with pytest.raises(eject.ResetRefused, match=problem):
        eject.reset(broker, install, backup_dir=install.parent / "backups")
    assert _exists(install, RUNTIME) == RUNTIME
    assert not (install.parent / "backups").exists()


@pytest.mark.parametrize(
    "broker",
    [
        envfile.Broker("dhan", "1100:::apikey", "s"),
        envfile.Broker("fivepaisa", "a:::b:::c", "s"),
        envfile.Broker("fivepaisaxts", "k", "s", "mk", "ms"),
    ],
)
def test_well_formed_brokers_pass(broker):
    assert envfile.broker_problem(broker, "fivepaisa,fivepaisaxts,dhan") is None


def test_xts_and_format_lists_match_install_and_env_check():
    """The broker rules are copied from install.sh and utils/env_check.py; keep them in step."""
    install_sh = (REPO / "install" / "install.sh").read_text(encoding="utf-8")
    listed = re.search(r'local xts_brokers="([^"]+)"', install_sh)
    assert listed and set(listed.group(1).split(",")) == envfile.XTS_BROKERS
    env_check = (REPO / "utils" / "env_check.py").read_text(encoding="utf-8")
    for name, (separators, _shape) in envfile.KEY_FORMATS.items():
        assert f'broker_name == "{name}"' in env_check
        assert f'broker_api_key.count(":::") != {separators}' in env_check


# --- the guard -------------------------------------------------------------

#: Every pattern in .gitignore, classified. A new pattern fails this test until
#: someone decides whether it is runtime state the reset must cover. "state"
#: means launcher.state covers it; anything else says why it is not state.
GITIGNORE = {
    "state": {
        ".env",
        "openalgo.db",
        "*.db-shm",
        "*.db-wal",
        "*.db-journal",
        "tmp/",
        ".numba_cache/",
        ".llvm_tmp/",
        "*.db",
        "*.duckdb",
        "*.duckdb.wal",
        "*.sqlite",
        "*.log",
        "*.jsonl",
        "*.tmp",
        "log/ws_proxy_stats.json",
        "db/strategy_encryption.key",
        "db/backups/",
        "workspace/**",
        "/~/",
        "logs/",
        "agent_kill_switch",
        ".reset-*/",
    },
    "dependencies or build output": {
        "venopenalgo",
        ".venv/",
        ".venv",
        ".venvv",
        "env/",
        "venv/",
        "ENV/",
        "env.bak/",
        "venv.bak/",
        "*.pyc",
        "__pycache__/",
        "*.egg-info/",
        "node_modules/",
        "**/node_modules/",
        "dist/",
        "build/",
        ".next/",
        "out/",
        "frontend/dist/**/*.gz",
        "frontend/dist/**/*.br",
        "frontend/dist/**/*.gz.tmp",
        "frontend/dist/",
        "frontend/.cache/",
        "release/",
        ".npm/",
        "npm-debug.log*",
        "yarn-debug.log*",
        "yarn-error.log*",
    },
    "installation, not client session": {
        "custom_brand/",
        ".cloudflared/*.json",
        "instance/",
        "config.ini",
    },
    "developer machine only": {
        ".flaskenv",
        ".DS_Store",
        "Thumbs.db",
        ".vscode/",
        ".superpowers/",
        ".idea/",
        ".claude/settings.json",
        ".claude/settings.local.json",
        ".python-version",
        "*.local",
        "nul",
        ".worktrees/",
        "log/test/",
        "checkpoint.txt",
        "checkpoints.json",
        "*.csv",
        ".env.*",
        "*.env",
        "env.backup",
        "workspace/**/.sample.env",
        "docs/audit/qa_audit/**/qa_shapes.json",
        "docs/audit/qa_audit/**/qa_sandbox_*.xlsx",
        "docs/audit/qa_audit/**/qa_live_*.xlsx",
        "docs/audit/qa_audit/**/qa_sandbox_*.csv",
        "docs/audit/qa_audit/**/qa_live_*.csv",
        "docs/audit/qa_audit/**/~$*",
    },
}


def test_every_gitignore_pattern_is_classified():
    patterns = set()
    for line in (REPO / ".gitignore").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("!"):
            patterns.add(line)
    classified = set().union(*GITIGNORE.values())
    assert sorted(patterns - classified) == [], "classify the new .gitignore pattern in this test"
    assert sorted(classified - patterns) == [], "remove the stale entry from this test"
