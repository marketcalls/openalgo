"""install/switch-worker.sh, and the update.sh block that calls it.

The switch script is the only thing that rewrites an OpenAlgo service file for
the launcher, so these tests hold it to what it promises: it changes nothing
but the ExecStart block (and a missing stop window), keeps a byte-identical
backup, refuses customised files and the trading day, and puts the backup
back by itself when OpenAlgo does not come up. The service files are the ones
the CURRENT install.sh and install-multi.sh write, rendered by bash from their
own heredocs, so a change to an installer is tested here too.

systemctl, sudo, curl, journalctl and systemd-analyze are replaced by small
scripts on PATH that record every call; nothing touches the real system.
These are bash scripts for Linux servers, so the tests run on Linux only.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SWITCH = ROOT / "install" / "switch-worker.sh"
UPDATE = ROOT / "install" / "update.sh"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="the switch script is a bash script for Linux servers",
)

SHIMS = {
    "sudo": r"""#!/bin/bash
echo "sudo $*" >> "$SHIM_STATE/calls.log"
while [ $# -gt 0 ]; do
  case "$1" in
    -u) shift 2 ;;
    -n|-E|-H) shift ;;
    --) shift; break ;;
    -*) shift ;;
    *) break ;;
  esac
done
exec "$@"
""",
    "systemctl": r"""#!/bin/bash
echo "systemctl $*" >> "$SHIM_STATE/calls.log"
cmd="$1"; shift
case "$cmd" in
  is-active) [ -f "$SHIM_STATE/active" ] && exit 0 || exit 3 ;;
  show) cat "$SHIM_STATE/mainpid" 2>/dev/null || echo 0 ;;
  daemon-reload) ;;
  restart|start)
    unit="$OPENALGO_SWITCH_TEST_SYSTEMD_DIR/$1.service"
    rm -f "$SHIM_STATE/active"
    line=$(tr -d '\r' < "$unit" | awk '
      !b && /^[[:space:]]*ExecStart=/ { b = 1; sub(/^[[:space:]]*ExecStart=/, "") }
      b { l = $0; m = (l ~ /\\[[:space:]]*$/); sub(/\\[[:space:]]*$/, "", l); printf "%s ", l; if (!m) exit }')
    if printf '%s' "$line" | grep -q openalgo-gunicorn.sh; then
      [ -f "$SHIM_STATE/fail_launcher" ] && exit 0
      class=$(eval "$line --dry-run" 2>/dev/null | awk '/^ARG --worker-class$/ { getline; print $2; exit }')
    else
      [ -f "$SHIM_STATE/fail_old" ] && exit 0
      class=$(printf '%s' "$line" | grep -oE -- '--worker-class [a-z]+' | awk '{print $2}')
    fi
    mkdir -p "$SHIM_STATE/proc/4242"
    printf 'gunicorn\0--worker-class\0%s\0app:app\0' "$class" > "$SHIM_STATE/proc/4242/cmdline"
    echo 4242 > "$SHIM_STATE/mainpid"
    echo "$class" > "$SHIM_STATE/running_class"
    touch "$SHIM_STATE/active" ;;
esac
exit 0
""",
    "curl": r"""#!/bin/bash
echo "curl $*" >> "$SHIM_STATE/calls.log"
[ -f "$SHIM_STATE/active" ] || exit 7
case "$*" in
  *socket.io*) printf '0{"sid":"abc","upgrades":["websocket"]}' ;;
  *) printf '{"status":"success","needs_setup":false}' ;;
esac
""",
    "journalctl": r"""#!/bin/bash
echo "journalctl $*" >> "$SHIM_STATE/calls.log"
echo "gunicorn: worker failed to boot"
""",
    "systemd-analyze": r"""#!/bin/bash
echo "systemd-analyze $*" >> "$SHIM_STATE/calls.log"
f="${@: -1}"
if [ -f "$SHIM_STATE/verify_fail_rendered" ] && grep -q openalgo-gunicorn.sh "$f"; then
  echo "unit is not valid"; exit 1
fi
exit 0
""",
}


def _executable(path: Path, text: str) -> Path:
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _installer_heredoc(script: Path) -> str:
    """The service file heredoc body of an installer, exactly as committed."""
    text = script.read_text(encoding="utf-8").replace("\r\n", "\n")
    match = re.search(
        r"sudo tee /etc/systemd/system/\$SERVICE_NAME\.service > /dev/null << EOL\n(.*?)\nEOL\n",
        text,
        re.S,
    )
    assert match, f"no service heredoc found in {script.name}"
    return match.group(1)


def _render(script: Path, variables: dict[str, str]) -> str:
    """Render an installer's heredoc with bash itself, so escapes behave as in the installer."""
    assignments = "".join(
        f"{name}={value!r}\n".replace('"', "'") for name, value in variables.items()
    )
    program = f"{assignments}cat << EOL\n{_installer_heredoc(script)}\nEOL\n"
    result = subprocess.run(["bash", "-c", program], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return result.stdout


class Box:
    """A fake server: service files, installs, shims and a record of calls."""

    def __init__(self, tmp_path: Path):
        self.root = tmp_path
        self.systemd = tmp_path / "systemd"
        self.systemd.mkdir()
        self.state = tmp_path / "state"
        self.state.mkdir()
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        for name, text in SHIMS.items():
            _executable(self.bin / name, text)

    def install(self, folder: str, venv_name: str, env_text: str) -> tuple[Path, Path]:
        app = self.root / folder
        (app / "install" / "lib").mkdir(parents=True)
        for rel in (
            "install/openalgo-gunicorn.sh",
            "install/switch-worker.sh",
            "install/lib/resolve_runtime.py",
            "install/lib/gunicorn_hooks.py",
        ):
            shutil.copy2(ROOT / rel, app / rel)
        (app / "app.py").write_text("")
        (app / ".env").write_bytes(env_text.encode("utf-8"))
        venv = app / venv_name
        (venv / "bin").mkdir(parents=True)
        _executable(venv / "bin" / "python", f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
        _executable(venv / "bin" / "gunicorn", "#!/bin/sh\nexit 0\n")
        return app, venv

    def single(self, env_text: str = "OPENALGO_WORKER_CLASS = 'gthread'\n") -> Path:
        """An install.sh server: /var/python/openalgo, service openalgo."""
        app, venv = self.install("openalgo", ".venv", env_text)
        unit = self.systemd / "openalgo.service"
        unit.write_text(
            _render(
                ROOT / "install" / "install.sh",
                {
                    "DEPLOY_NAME": "openalgo",
                    "WEB_USER": "www-data",
                    "WEB_GROUP": "www-data",
                    "OPENALGO_PATH": str(app),
                    "VENV_PATH": str(venv),
                    "SOCKET_FILE": str(app / "openalgo.sock"),
                },
            )
        )
        return unit

    def multi(self, number: int, env_text: str = "OPENALGO_WORKER_CLASS = 'gthread'\n") -> Path:
        """An install-multi.sh instance: openalgo-flask/openalgo<N>, service openalgo<N>."""
        app, venv = self.install(f"openalgo-flask/openalgo{number}", "venv", env_text)
        unit = self.systemd / f"openalgo{number}.service"
        unit.write_text(
            _render(
                ROOT / "install" / "install-multi.sh",
                {
                    "i": str(number),
                    "DOMAIN": f"trade{number}.example.com",
                    "BROKER": "zerodha",
                    "INSTANCE_DIR": str(app),
                    "VENV_PATH": str(venv),
                    "SOCKET_FILE": str(app / "openalgo.sock"),
                },
            )
        )
        return unit

    def env(self, clock: str = "0100") -> dict:
        env = {k: v for k, v in os.environ.items() if not k.startswith("OPENALGO_")}
        env.update(
            {
                "PATH": f"{self.bin}{os.pathsep}{env.get('PATH', '')}",
                "SHIM_STATE": str(self.state),
                "OPENALGO_SWITCH_TEST_SYSTEMD_DIR": str(self.systemd),
                "OPENALGO_SWITCH_TEST_PROC": str(self.state / "proc"),
                "OPENALGO_SWITCH_TEST_HEALTH_TIMEOUT": "2",
                "OPENALGO_SWITCH_TEST_HEALTH_INTERVAL": "1",
                "OPENALGO_SWITCH_TEST_HEALTH_SETTLE": "0",
                "OPENALGO_SWITCH_TEST_CLOCK_HHMM": clock,
            }
        )
        return env

    def run(self, *args: str, clock: str = "0100", script: Path = SWITCH):
        return subprocess.run(
            ["bash", str(script), *args],
            capture_output=True,
            text=True,
            env=self.env(clock),
            stdin=subprocess.DEVNULL,
            timeout=120,
        )

    def calls(self) -> list[str]:
        log = self.state / "calls.log"
        return log.read_text().splitlines() if log.exists() else []

    def systemctl(self) -> list[str]:
        return [
            c
            for c in self.calls()
            if c.startswith("systemctl ")
            and not c.startswith(("systemctl is-active", "systemctl show"))
        ]


def _exec_block(text: str) -> list[str]:
    """ExecStart lines with their continuation lines."""
    lines, out, inside = text.splitlines(), [], False
    for line in lines:
        if not inside and line.lstrip().startswith("ExecStart="):
            inside = True
        if inside:
            out.append(line)
            if not line.rstrip().endswith("\\"):
                inside = False
    return out


def _without_exec(text: str) -> list[str]:
    block = set(_exec_block(text))
    return [
        line
        for line in text.splitlines()
        if line not in block
        and not line.startswith("# OPENALGO_LAUNCHER=1")
        and not line.startswith("# OPENALGO_WORKER_CLASS from .env. Previous file:")
        and not line.startswith("TimeoutStopSec=")
    ]


@pytest.fixture
def box(tmp_path):
    return Box(tmp_path)


# ------------------------------------------------------------------ switching


@pytest.mark.parametrize("layout", ["single", "multi"])
def test_an_installer_unit_is_switched_and_nothing_else_changes(box, layout):
    unit = box.single() if layout == "single" else box.multi(1)
    original = unit.read_bytes()
    result = box.run("--yes")
    assert result.returncode == 0, result.stdout + result.stderr

    text = unit.read_text()
    block = _exec_block(text)
    assert len(block) == 1, block
    assert "install/openalgo-gunicorn.sh --venv " in block[0]
    assert "--bind unix:" in block[0] and "--proxy-mode subprocess" in block[0]
    assert "--log-level info --timeout 300" in block[0]
    assert text.count("ExecStart=") == 1
    assert _without_exec(text) == _without_exec(original.decode())
    assert "# OPENALGO_LAUNCHER=1" in text

    backups = list(box.systemd.glob(f"{unit.name}.pre-launcher-*"))
    assert len(backups) == 1 and backups[0].read_bytes() == original
    assert box.systemctl()[:2] == ["systemctl daemon-reload", f"systemctl restart {unit.stem}"]
    assert (box.state / "running_class").read_text().strip() == "gthread"
    assert "running on the gthread web server" in result.stdout


def test_the_stop_window_is_kept_when_long_enough(box):
    unit = box.single()
    assert "TimeoutSec=300" in unit.read_text()
    assert box.run("--yes").returncode == 0
    assert "TimeoutStopSec=" not in unit.read_text()


def test_a_short_stop_window_is_lengthened(box):
    unit = box.single()
    unit.write_text(unit.read_text().replace("TimeoutSec=300", "TimeoutSec=20"))
    assert box.run("--yes").returncode == 0
    assert "TimeoutStopSec=90" in unit.read_text()


def test_an_already_switched_unit_is_left_alone(box):
    unit = box.single()
    assert box.run("--yes").returncode == 0
    switched = unit.read_bytes()
    box.state.joinpath("calls.log").unlink()
    result = box.run("--yes")
    assert result.returncode == 0
    assert "Already uses the launcher" in result.stdout
    assert unit.read_bytes() == switched
    assert len(list(box.systemd.glob("openalgo.service.pre-launcher-*"))) == 1
    assert box.systemctl() == []


def test_a_customised_unit_is_left_untouched(box):
    unit = box.single()
    unit.write_text(
        unit.read_text().replace("--log-level info", "--log-level info --access-logfile -")
    )
    before = unit.read_bytes()
    result = box.run("--yes")
    assert result.returncode == 3
    assert "Left unchanged" in result.stderr and "--access-logfile" in result.stderr
    assert unit.read_bytes() == before
    assert not list(box.systemd.glob("*.pre-launcher-*"))
    assert box.systemctl() == []


def test_a_unit_with_a_reload_command_is_refused(box):
    unit = box.single()
    unit.write_text(
        unit.read_text().replace(
            "Restart=always", "ExecReload=/bin/kill -HUP $MAINPID\nRestart=always"
        )
    )
    result = box.run("--yes")
    assert result.returncode == 3
    assert "ExecReload" in result.stderr


def test_a_failed_start_puts_the_previous_file_back(box):
    unit = box.single()
    original = unit.read_bytes()
    (box.state / "fail_launcher").touch()
    result = box.run("--yes")
    assert result.returncode == 1, result.stdout + result.stderr
    assert unit.read_bytes() == original
    assert box.systemctl() == [
        "systemctl daemon-reload",
        "systemctl restart openalgo",
        "systemctl daemon-reload",
        "systemctl restart openalgo",
    ]
    assert (box.state / "running_class").read_text().strip() == "eventlet"
    assert "put back on its previous service file" in result.stderr
    assert "worker failed to boot" in result.stderr  # the journal tail is shown


def test_when_nothing_starts_the_manual_rollback_is_printed(box):
    unit = box.single()
    (box.state / "fail_launcher").touch()
    (box.state / "fail_old").touch()
    result = box.run("--yes")
    assert result.returncode == 2
    assert "sudo cp " in result.stderr and str(unit) in result.stderr


def test_the_trading_day_is_refused_without_force(box):
    unit = box.single()
    before = unit.read_bytes()
    result = box.run("--yes", clock="1000")
    assert result.returncode == 3
    assert "23:30 IST" in result.stderr and "--force" in result.stderr
    assert unit.read_bytes() == before
    assert box.systemctl() == []
    assert box.run("--yes", "--force", clock="1000").returncode == 0
    assert "openalgo-gunicorn.sh" in unit.read_text()


@pytest.mark.parametrize(
    "clock,refused", [("0859", False), ("0900", True), ("2329", True), ("2330", False)]
)
def test_the_trading_day_boundaries(box, clock, refused):
    box.single()
    result = box.run("--yes", clock=clock)
    assert (result.returncode == 3) is refused, result.stderr


def test_dry_run_changes_nothing(box):
    unit = box.single()
    before = unit.read_bytes()
    result = box.run("--dry-run", clock="1000")
    assert result.returncode == 0, result.stderr
    assert "+ExecStart=/bin/bash" in result.stdout
    assert unit.read_bytes() == before
    assert box.systemctl() == []


def test_a_rendered_file_systemd_rejects_is_not_installed(box):
    unit = box.single()
    before = unit.read_bytes()
    (box.state / "verify_fail_rendered").touch()
    result = box.run("--yes")
    assert result.returncode == 3
    assert "did not pass systemd's check" in result.stderr
    assert unit.read_bytes() == before


def test_to_sets_env_and_switches_back_and_forth(box):
    unit = box.single("APP_KEY = 'x'\n")
    result = box.run("--yes", "--to", "gthread")
    assert result.returncode == 0, result.stdout + result.stderr
    env_file = box.root / "openalgo" / ".env"
    assert "OPENALGO_WORKER_CLASS = 'gthread'" in env_file.read_text()
    assert (box.state / "running_class").read_text().strip() == "gthread"

    switched = unit.read_bytes()
    result = box.run("--yes", "--to", "eventlet")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OPENALGO_WORKER_CLASS = 'eventlet'" in env_file.read_text()
    assert (box.state / "running_class").read_text().strip() == "eventlet"
    assert unit.read_bytes() == switched  # going back is .env plus a restart


def test_restore_puts_the_installer_file_back(box):
    unit = box.single()
    original = unit.read_bytes()
    assert box.run("--yes").returncode == 0
    result = box.run("--yes", "--restore")
    assert result.returncode == 0, result.stdout + result.stderr
    assert unit.read_bytes() == original
    assert (box.state / "running_class").read_text().strip() == "eventlet"


def test_several_services_need_a_name_or_all(box):
    first, second = box.multi(1), box.multi(2)
    result = box.run("--yes")
    assert result.returncode == 3
    assert "openalgo1" in result.stderr and "openalgo2" in result.stderr
    result = box.run("--yes", "--all")
    assert result.returncode == 0, result.stdout + result.stderr
    for unit in (first, second):
        assert "openalgo-gunicorn.sh" in unit.read_text()
    assert "128 in total" in result.stdout


def test_a_service_can_be_picked_by_folder(box):
    first, second = box.multi(1), box.multi(2)
    result = box.run("--yes", "--path", str(box.root / "openalgo-flask" / "openalgo2"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "openalgo-gunicorn.sh" in second.read_text()
    assert "openalgo-gunicorn.sh" not in first.read_text()


def test_check_is_silent_and_true_only_when_a_switch_is_wanted(box):
    unit = box.single()
    result = box.run("--check", "--service", "openalgo", clock="1000")
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    (box.root / "openalgo" / ".env").write_text("OPENALGO_WORKER_CLASS = 'eventlet'\n")
    assert box.run("--check", "--service", "openalgo").returncode == 3
    (box.root / "openalgo" / ".env").write_text("APP_KEY = 'x'\n")
    assert box.run("--check", "--service", "openalgo").returncode == 3
    (box.root / "openalgo" / ".env").write_text("OPENALGO_WORKER_CLASS = 'gthread'\n")
    assert box.run("--yes").returncode == 0
    assert box.run("--check", "--service", "openalgo").returncode == 3
    assert box.run("--check", "--service", "missing").returncode == 3
    assert "openalgo-gunicorn.sh" in unit.read_text()


# ------------------------------------------------------------------ update.sh


BEGIN = "# OPENALGO WEB SERVER SWITCH: begin"
END = "# OPENALGO WEB SERVER SWITCH: end"


def _update_text() -> str:
    return UPDATE.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_the_update_block_is_the_only_addition_and_comes_last():
    text = _update_text()
    assert text.count(BEGIN) == 1 and text.count(END) == 1
    before, rest = text.split(BEGIN, 1)
    _block, after = rest.split(END, 1)
    assert after.strip() == ""
    assert before.rstrip().endswith('log_message "\\nUpdate completed successfully!" "$GREEN"')
    for marker in ("switch-worker", "OPENALGO_WORKER_CLASS", "openalgo-gunicorn"):
        assert marker not in before, f"{marker} appears outside the switch block"


def _run_update_block(box: Box, server_mode: str = "true", clock: str = "0100"):
    text = _update_text()
    block = BEGIN + text.split(BEGIN, 1)[1]
    program = "\n".join(
        [
            "NC=''; BLUE=''; RED=''; GREEN=''",
            'log_message() { echo -e "${2}${1}${NC}" | tee -a "$LOG_FILE"; }',
            f"SERVER_MODE={server_mode}",
            f"OPENALGO_PATH='{box.root / 'openalgo'}'",
            "SERVICE_NAME=openalgo",
            f"LOG_FILE='{box.root / 'update.log'}'",
            block,
            "echo BLOCK_DONE",
        ]
    )
    return subprocess.run(
        ["bash", "-c", program],
        capture_output=True,
        text=True,
        env=box.env(clock),
        stdin=subprocess.DEVNULL,
        timeout=120,
    )


@pytest.mark.parametrize(
    "env_text",
    [
        "APP_KEY = 'x'\n",
        "OPENALGO_WORKER_CLASS = 'eventlet'\n",
        "# OPENALGO_WORKER_CLASS = 'gthread'\n",
    ],
)
def test_update_is_unchanged_for_an_install_that_has_not_opted_in(box, env_text):
    unit = box.single(env_text)
    before = unit.read_bytes()
    result = _run_update_block(box)
    assert result.returncode == 0
    assert result.stdout == "BLOCK_DONE\n" and result.stderr == ""
    assert unit.read_bytes() == before
    assert box.systemctl() == []
    assert not (box.root / "update.log").exists()


def test_update_switches_an_opted_in_install_once(box):
    unit = box.single()
    result = _run_update_block(box)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "asks for the gthread web server" in result.stdout
    assert "openalgo-gunicorn.sh" in unit.read_text()
    assert "running on the gthread web server" in (box.root / "update.log").read_text()
    switched = unit.read_bytes()
    box.state.joinpath("calls.log").unlink()
    result = _run_update_block(box)
    assert result.stdout == "BLOCK_DONE\n"
    assert unit.read_bytes() == switched
    assert box.systemctl() == []


def test_update_during_the_trading_day_explains_and_changes_nothing(box):
    unit = box.single()
    before = unit.read_bytes()
    result = _run_update_block(box, clock="1100")
    assert result.returncode == 0
    said = " ".join((result.stdout + result.stderr).split())
    assert "Run it again after 23:30 IST" in said
    assert unit.read_bytes() == before


def test_update_in_local_development_mode_never_switches(box):
    box.single()
    result = _run_update_block(box, server_mode="false")
    assert result.stdout == "BLOCK_DONE\n"
    assert box.calls() == []
