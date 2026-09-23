"""install/update.sh finds each server layout and updates it the way it should.

Three layouts exist on servers today:

1. install.sh: one checkout at /var/python/openalgo, service ``openalgo``.
2. The legacy multi-deploy layout: /var/python/openalgo-flask/<deploy>/openalgo,
   its environment at <deploy>/venv, service ``openalgo-<deploy>``.
3. install-multi.sh: each instance cloned straight into
   /var/python/openalgo-flask/openalgoN, its environment at openalgoN/venv,
   service ``openalgoN``.

The updater knew the first two. On the third it found neither and fell through
to local development mode: run inside an instance, it updated that checkout as
root with ``uv sync`` and restarted nothing. It now finds those instances too,
and picks the one it was run from. The first two are looked for first, exactly
as before, so a server with either of them sees no change.

The whole updater runs here, against a fake server: real git checkouts of a
local origin, and small scripts on PATH standing in for sudo, systemctl, uv,
nginx and chown that record every call. The fixed paths in the script
(/var/python, the systemd folder, the nginx folder) are rewritten to folders
under the test's own temporary directory. Linux only.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
UPDATE = ROOT / "install" / "update.sh"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None or shutil.which("git") is None,
    reason="the updater is a bash script for Linux servers",
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
[ "$1" = "--quiet" ] && shift
case "$cmd" in
  is-active) [ -f "$SHIM_STATE/active_$1" ] && exit 0 || exit 3 ;;
  stop) rm -f "$SHIM_STATE/active_$1" ;;
  start|restart) touch "$SHIM_STATE/active_$1" ;;
esac
exit 0
""",
    "uv": r"""#!/bin/bash
echo "uv $*" >> "$SHIM_STATE/calls.log"
exit 0
""",
    "nginx": r"""#!/bin/bash
echo "nginx $*" >> "$SHIM_STATE/calls.log"
exit 0
""",
    "chown": r"""#!/bin/bash
echo "chown $*" >> "$SHIM_STATE/calls.log"
exit 0
""",
}

GIT = ["git", "-c", "user.name=OpenAlgo Test", "-c", "user.email=test@example.invalid"]


def _executable(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        [*GIT, *args], cwd=cwd, capture_output=True, text=True, timeout=60, check=True
    )
    return result.stdout.strip()


class UpdateBox:
    """A fake server with any of the three layouts, and a record of every call."""

    def __init__(self, tmp_path: Path, source_text: str | None = None):
        self.root = tmp_path
        self.var = tmp_path / "var" / "python"
        self.simple_path = self.var / "openalgo"
        self.deploy_base = self.var / "openalgo-flask"
        self.systemd = tmp_path / "systemd"
        self.nginx = tmp_path / "nginx"
        self.state = tmp_path / "state"
        self.bin = tmp_path / "bin"
        for folder in (self.var, self.systemd, self.state, self.bin):
            folder.mkdir(parents=True, exist_ok=True)
        for folder in ("sites-available", "sites-enabled", "conf.d"):
            (self.nginx / folder).mkdir(parents=True)
        for name, text in SHIMS.items():
            _executable(self.bin / name, text)

        text = source_text if source_text is not None else UPDATE.read_text(encoding="utf-8")
        self.script_text = self._rewritten(text.replace("\r\n", "\n"))

        # The origin every checkout pulls from, with the updater in it.
        self.seed = tmp_path / "seed"
        self.seed.mkdir()
        _git("init", "-q", "-b", "main", cwd=self.seed)
        (self.seed / "app.py").write_text("")
        (self.seed / ".sample.env").write_text("APP_KEY = 'x'\n")
        (self.seed / "requirements-nginx.txt").write_text("")
        (self.seed / "upgrade").mkdir()
        (self.seed / "upgrade" / "migrate_all.py").write_text("print('migrations done')\n")
        _executable(self.seed / "install" / "update.sh", self.script_text)
        _git("add", "-A", cwd=self.seed)
        _git("commit", "-q", "-m", "first", cwd=self.seed)
        self.origin = tmp_path / "origin.git"
        _git("clone", "-q", "--bare", str(self.seed), str(self.origin), cwd=tmp_path)

    def _rewritten(self, text: str) -> str:
        for old, new in (
            ('SIMPLE_PATH="/var/python/openalgo"', f'SIMPLE_PATH="{self.simple_path}"'),
            ('DEPLOY_BASE="/var/python/openalgo-flask"', f'DEPLOY_BASE="{self.deploy_base}"'),
            ('MULTI_SYSTEMD_DIR="/etc/systemd/system"', f'MULTI_SYSTEMD_DIR="{self.systemd}"'),
            ("/etc/nginx", str(self.nginx)),
        ):
            text = text.replace(old, new)
        assert f'SIMPLE_PATH="{self.simple_path}"' in text
        assert f'DEPLOY_BASE="{self.deploy_base}"' in text
        return text

    def advance(self) -> str:
        """A new commit on the origin, which an update should pull."""
        (self.seed / "NEW").write_text("new\n")
        _git("add", "-A", cwd=self.seed)
        _git("commit", "-q", "-m", "second", cwd=self.seed)
        _git("push", "-q", str(self.origin), "main", cwd=self.seed)
        return _git("rev-parse", "HEAD", cwd=self.seed)

    def _checkout(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        _git("clone", "-q", str(self.origin), str(path), cwd=self.root)
        (path / ".env").write_text("APP_KEY = 'x'\nTRUST_PROXY_HEADERS = 'TRUE'\n")
        return path

    def _venv(self, venv: Path) -> Path:
        _executable(venv / "bin" / "python", f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
        _executable(
            venv / "bin" / "pip", "#!/bin/sh\necho gunicorn==25.3.0\necho eventlet==0.40.0\n"
        )
        (venv / "bin" / "activate").write_text(f'export PATH="{venv / "bin"}:$PATH"\n')
        return venv

    def _unit(self, service: str, workdir: Path, venv: Path) -> None:
        (self.systemd / f"{service}.service").write_text(
            "[Unit]\nDescription=OpenAlgo\n\n[Service]\nUser=www-data\n"
            f"WorkingDirectory={workdir}\n"
            f"ExecStart=/bin/bash -c 'source {venv}/bin/activate && {venv}/bin/gunicorn "
            f"--worker-class eventlet -w 1 --bind unix:{workdir}/openalgo.sock app:app'\n"
            "Restart=always\n\n[Install]\nWantedBy=multi-user.target\n"
        )
        (self.state / f"active_{service}").touch()

    def simple(self) -> Path:
        path = self._checkout(self.simple_path)
        venv = self._venv(path / ".venv")
        self._unit("openalgo", path, venv)
        return path

    def legacy(self, deploy: str) -> Path:
        path = self._checkout(self.deploy_base / deploy / "openalgo")
        venv = self._venv(self.deploy_base / deploy / "venv")
        self._unit(f"openalgo-{deploy}", path, venv)
        return path

    def multi(self, number: int) -> Path:
        path = self._checkout(self.deploy_base / f"openalgo{number}")
        venv = self._venv(path / "venv")
        self._unit(f"openalgo{number}", path, venv)
        return path

    def run(self, script: Path, cwd: Path, stdin: str | None = None):
        env = {k: v for k, v in os.environ.items() if not k.startswith("OPENALGO_")}
        env.update(
            {"PATH": f"{self.bin}{os.pathsep}{env.get('PATH', '')}", "SHIM_STATE": str(self.state)}
        )
        return subprocess.run(
            ["bash", str(script)],
            cwd=cwd,
            capture_output=True,
            text=True,
            env=env,
            input=stdin,
            stdin=None if stdin is not None else subprocess.DEVNULL,
            timeout=180,
        )

    def calls(self, prefix: str = "") -> list[str]:
        log = self.state / "calls.log"
        lines = log.read_text().splitlines() if log.exists() else []
        return [line for line in lines if line.startswith(prefix)]

    def head(self, path: Path) -> str:
        return _git("rev-parse", "HEAD", cwd=path)


def _systemctl(box: UpdateBox) -> list[str]:
    return box.calls("systemctl ")


@pytest.fixture
def box(tmp_path):
    return UpdateBox(tmp_path)


# ---------------------------------------------------------------- the new layout


def test_run_inside_a_multi_instance_updates_that_instance(box):
    first, second = box.multi(1), box.multi(2)
    before_first = box.head(first)
    new_head = box.advance()

    result = box.run(second / "install" / "update.sh", cwd=second)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Updating instance: openalgo2" in result.stdout
    assert "local development" not in result.stdout
    assert box.head(second) == new_head
    assert box.head(first) == before_first, "an instance that was not chosen was changed"
    assert _systemctl(box) == [
        "systemctl is-active --quiet openalgo2",
        "systemctl stop openalgo2",
        "systemctl daemon-reload",
        "systemctl start openalgo2",
        "systemctl reload nginx",
        "systemctl is-active --quiet openalgo2",
    ]
    assert box.calls("uv ") == [
        f"uv pip install --python {second}/venv/bin/python -r {second}/requirements-nginx.txt"
    ]
    assert f"chown -R www-data:www-data {second}" in box.calls("chown ")
    assert not (second / ".venv").exists(), "the instance was updated as a development checkout"


def test_run_from_the_instance_folder_picks_it_even_with_another_script(box, tmp_path):
    box.multi(1)
    second = box.multi(2)
    tools = tmp_path / "tools" / "install"
    _executable(tools / "update.sh", box.script_text)

    result = box.run(tools / "update.sh", cwd=second)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Updating instance: openalgo2" in result.stdout
    assert "systemctl start openalgo2" in _systemctl(box)


def test_a_single_multi_instance_is_chosen_by_itself(box, tmp_path):
    only = box.multi(1)
    new_head = box.advance()
    tools = tmp_path / "tools" / "install"
    _executable(tools / "update.sh", box.script_text)

    result = box.run(tools / "update.sh", cwd=tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Auto-selected: openalgo1" in result.stdout
    assert box.head(only) == new_head


def test_several_instances_and_no_answer_changes_nothing(box, tmp_path):
    box.multi(1)
    box.multi(2)
    tools = tmp_path / "tools" / "install"
    _executable(tools / "update.sh", box.script_text)

    result = box.run(tools / "update.sh", cwd=tmp_path)

    assert result.returncode == 1
    said = " ".join(result.stdout.split())
    assert "No instance was chosen, so nothing was changed" in said
    assert "install/update.sh" in said
    assert _systemctl(box) == []
    assert box.calls("uv ") == []


def test_several_instances_can_be_chosen_by_number(box, tmp_path):
    box.multi(1)
    second = box.multi(2)
    new_head = box.advance()
    tools = tmp_path / "tools" / "install"
    _executable(tools / "update.sh", box.script_text)

    result = box.run(tools / "update.sh", cwd=tmp_path, stdin="2\n")

    assert result.returncode == 0, result.stdout + result.stderr
    assert box.head(second) == new_head
    assert "systemctl start openalgo2" in _systemctl(box)


def test_a_folder_whose_service_points_elsewhere_is_not_an_instance(box):
    """Only a checkout its own service runs from counts, as switch-worker decides."""
    path = box.multi(1)
    (box.systemd / "openalgo1.service").write_text(
        (box.systemd / "openalgo1.service").read_text().replace(str(path), "/srv/elsewhere")
    )

    result = box.run(path / "install" / "update.sh", cwd=path)

    assert "Updating instance" not in result.stdout
    assert "Detected local development setup" in result.stdout


# ---------------------------------------------------------------- the old layouts, as before


def test_the_install_sh_layout_is_updated_as_before_even_beside_instances(box):
    simple = box.simple()
    instance = box.multi(1)
    before_instance = box.head(instance)
    new_head = box.advance()

    # Run from inside the instance: the simple install is still the one updated,
    # as it always has been when /var/python/openalgo exists.
    result = box.run(instance / "install" / "update.sh", cwd=instance)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Found OpenAlgo install at {simple}" in result.stdout
    assert box.head(simple) == new_head
    assert box.head(instance) == before_instance
    assert _systemctl(box) == [
        "systemctl is-active --quiet openalgo",
        "systemctl stop openalgo",
        "systemctl daemon-reload",
        "systemctl start openalgo",
        "systemctl reload nginx",
        "systemctl is-active --quiet openalgo",
    ]
    assert box.calls("uv ") == [
        f"uv pip install --python {simple}/.venv/bin/python -r {simple}/requirements-nginx.txt"
    ]


def test_the_legacy_layout_is_updated_as_before_even_beside_instances(box):
    legacy = box.legacy("acme")
    box.multi(1)
    new_head = box.advance()

    result = box.run(legacy / "install" / "update.sh", cwd=legacy)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Found 1 legacy server deployment(s)" in result.stdout
    assert "Updating instance" not in result.stdout
    assert box.head(legacy) == new_head
    assert _systemctl(box) == [
        "systemctl is-active --quiet openalgo-acme",
        "systemctl stop openalgo-acme",
        "systemctl daemon-reload",
        "systemctl start openalgo-acme",
        "systemctl reload nginx",
        "systemctl is-active --quiet openalgo-acme",
    ]
    venv = box.deploy_base / "acme" / "venv"
    assert box.calls("uv ") == [
        f"uv pip install --python {venv}/bin/python -r {legacy}/requirements-nginx.txt"
    ]
    assert f"chown -R www-data:www-data {box.deploy_base / 'acme'}" in box.calls("chown ")


def test_a_development_checkout_with_no_server_install_is_as_before(box, tmp_path):
    dev = box._checkout(tmp_path / "dev" / "openalgo")

    result = box.run(dev / "install" / "update.sh", cwd=dev)

    assert "Detected local development setup" in result.stdout
    assert _systemctl(box) == []
    assert "uv sync" in box.calls("uv ")
