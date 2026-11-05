"""Per-instance memory profile, web server choice and port reuse in the
multi-instance Docker installer (install/install-docker-multi-custom-ssl.sh).

The installer needs root, Docker, apt and Nginx, so it is sourced with
OPENALGO_INSTALLER_LIB_ONLY=1 (which returns before any imperative section) and
the real helper functions are driven against temporary directories. `docker`
is a stub on PATH where a test needs one.
"""

import os
import pathlib
import re
import stat
import subprocess

import pytest

SCRIPT = (
    pathlib.Path(__file__).resolve().parents[1] / "install" / "install-docker-multi-custom-ssl.sh"
)

pytestmark = pytest.mark.skipif(not SCRIPT.exists(), reason="installer script not present")


def _run(tmp_path, body, stdin="", extra_env=None, path_prefix=None):
    available = tmp_path / "sites-available"
    enabled = tmp_path / "sites-enabled"
    instances = tmp_path / "opt"
    for d in (available, enabled, instances):
        d.mkdir(parents=True, exist_ok=True)
    script = f"""
set -u
export NGINX_SITES_AVAILABLE="{available}"
export NGINX_SITES_ENABLED="{enabled}"
export OPENALGO_INSTALLER_LIB_ONLY=1
source "{SCRIPT}"
INSTALL_BASE="{instances}"
{body}
"""
    env = dict(os.environ)
    env.update(extra_env or {})
    if path_prefix:
        env["PATH"] = f"{path_prefix}:{env['PATH']}"
    proc = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
        input=stdin,
        env=env,
    )
    assert proc.returncode == 0, f"harness failed:\n{proc.stdout}\n{proc.stderr}"
    return dict(re.findall(r"^RESULT (\S+)=(.*)$", proc.stdout, re.M)), proc


def _generated_compose(path, flask, ws):
    path.write_text(f'      - "127.0.0.1:{flask}:5000"\n      - "127.0.0.1:{ws}:8765"\n')


REPO_COMPOSE = (
    '    ports:\n      - "${FLASK_PORT:-5000}:5000"\n'
    '    healthcheck:\n      test: ["CMD", "curl", "-f", "http://127.0.0.1:5000/auth/check-setup"]\n'
)


# --------------------------------------------------------------------- ports


def test_port_scan_ignores_the_repository_compose_file(tmp_path):
    """The repo's own compose file ("${FLASK_PORT:-5000}") broke the scan with
    'integer expression expected' and could not be told from a generated one."""
    opt = tmp_path / "opt"
    a = opt / "a.example.com"
    b = opt / "b.example.com"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    _generated_compose(a / "docker-compose.yaml", 5357, 9122)
    (b / "docker-compose.yaml").write_text(REPO_COMPOSE)
    result, proc = _run(tmp_path, 'echo "RESULT next=$(get_next_ports)"')
    assert result["next"] == "5358 9123"
    assert "integer expression" not in proc.stderr


def test_port_scan_ignores_nested_compose_files(tmp_path):
    opt = tmp_path / "opt"
    nested = opt / "a.example.com" / "docs" / "sample"
    nested.mkdir(parents=True)
    _generated_compose(nested / "docker-compose.yaml", 6000, 9999)
    result, _ = _run(tmp_path, 'echo "RESULT next=$(get_next_ports)"')
    assert result["next"] == "5000 8765"


def test_deployed_instance_keeps_its_ports_across_updates(tmp_path):
    opt = tmp_path / "opt"
    for name, f, w in (("zerodha.example.com", 5358, 9123), ("upstox.example.com", 5357, 9122)):
        d = opt / name
        d.mkdir(parents=True)
        _generated_compose(d / "docker-compose.yaml", f, w)
    result, _ = _run(
        tmp_path,
        """
        echo "RESULT upstox=$(resolve_instance_ports upstox.example.com)"
        echo "RESULT zerodha=$(resolve_instance_ports zerodha.example.com)"
        echo "RESULT brand_new=$(resolve_instance_ports new.example.com)"
        """,
    )
    assert result["upstox"] == "5357 9122"
    assert result["zerodha"] == "5358 9123"
    assert result["brand_new"] == "5359 9124"


def test_ports_fall_back_to_the_vhost_when_compose_was_overwritten(tmp_path):
    """After the repository replaced the compose file, the vhost still knows."""
    opt = tmp_path / "opt"
    d = opt / "upstox.example.com"
    d.mkdir(parents=True)
    (d / "docker-compose.yaml").write_text(REPO_COMPOSE)
    available = tmp_path / "sites-available"
    available.mkdir()
    (available / "upstox.example.com").write_text(
        "upstream f {\n    server 127.0.0.1:5357;\n}\nupstream w {\n    server 127.0.0.1:9122;\n}\n"
    )
    result, _ = _run(tmp_path, 'echo "RESULT p=$(resolve_instance_ports upstox.example.com)"')
    assert result["p"] == "5357 9122"


def test_snapshot_is_taken_before_the_repository_sync():
    """git reset --hard replaces docker-compose.yaml (a tracked file); a snapshot
    taken after it would restore the repository's file, not the generated one."""
    text = SCRIPT.read_text()
    snapshot = text.index('    snapshot_instance_config "$INSTANCE_DIR" "$DOMAIN"')
    sync = text.index("git reset --hard origin/main")
    assert snapshot < sync
    assert text.count('snapshot_instance_config "$INSTANCE_DIR" "$DOMAIN"') == 1


# ------------------------------------------------------------ memory profile


def _resources(tmp_path, profile, ram, cores, instances, env=None):
    result, _ = _run(
        tmp_path,
        f"""
        compute_resources {profile} {ram} {cores} {instances}
        echo "RESULT out=$SHM_SIZE_MB $THREAD_LIMIT $STRATEGY_MEM_LIMIT"
        """,
        extra_env=env,
    )
    return tuple(int(x) for x in result["out"].split())


def test_auto_profile_keeps_the_original_sizing(tmp_path):
    # One instance on this VM: top tier
    assert _resources(tmp_path, "auto", 7905, 2, 1) == (1024, 2, 1024)
    # Both instances in one run: the 512 MB strategy tier
    assert _resources(tmp_path, "auto", 7905, 2, 2) == (988, 2, 512)
    # Small host
    assert _resources(tmp_path, "auto", 3000, 2, 2) == (375, 1, 256)


def test_unrestricted_profile_does_not_depend_on_instance_count(tmp_path):
    one = _resources(tmp_path, "unrestricted", 7905, 2, 1)
    two = _resources(tmp_path, "unrestricted", 7905, 2, 2)
    assert one == two == (1024, 2, 3072)


def test_unrestricted_strategy_cap_can_be_overridden(tmp_path):
    assert _resources(tmp_path, "unrestricted", 7905, 2, 2, {"STRATEGY_MEM_LIMIT_MB": "4096"}) == (
        1024,
        2,
        4096,
    )


def test_profile_is_remembered_per_instance_and_defaults_to_auto(tmp_path):
    (tmp_path / "opt" / "a.example.com").mkdir(parents=True)
    (tmp_path / "opt" / "b.example.com").mkdir(parents=True)
    result, _ = _run(
        tmp_path,
        """
        write_instance_profile "$INSTALL_BASE/a.example.com" unrestricted
        echo "RESULT a=$(read_instance_profile a.example.com)"
        echo "RESULT b=$(read_instance_profile b.example.com)"
        echo "RESULT missing=$(read_instance_profile nothing.example.com)"
        """,
    )
    assert result == {"a": "unrestricted", "b": "auto", "missing": "auto"}


def test_profile_choice_enter_keeps_current_and_rejects_nonsense(tmp_path):
    result, _ = _run(
        tmp_path,
        """
        echo "RESULT keep=$(choose_memory_profile d unrestricted)"
        echo "RESULT bad=$(choose_memory_profile d auto)"
        """,
        stdin="\nlarge\n",
    )
    assert result == {"keep": "unrestricted", "bad": "auto"}


# -------------------------------------------------------------------- worker


SAMPLE_ENV = "A='1'\n# OPENALGO_WORKER_CLASS = 'eventlet'\nB='2'\n"


def test_worker_class_defaults_to_eventlet_and_ignores_the_commented_sample(tmp_path):
    env = tmp_path / ".env"
    env.write_text(SAMPLE_ENV)
    result, _ = _run(tmp_path, f'echo "RESULT w=$(read_worker_class {env})"')
    assert result["w"] == "eventlet"


def test_set_worker_class_is_idempotent_and_keeps_other_lines(tmp_path):
    env = tmp_path / ".env"
    env.write_text(SAMPLE_ENV)
    os.chmod(env, 0o600)
    inode = env.stat().st_ino
    result, _ = _run(
        tmp_path,
        f"""
        set_worker_class {env} gthread
        set_worker_class {env} gthread
        echo "RESULT w1=$(read_worker_class {env})"
        set_worker_class {env} eventlet
        echo "RESULT w2=$(read_worker_class {env})"
        set_worker_class {env} gthread
        echo "RESULT w3=$(read_worker_class {env})"
        """,
    )
    assert (result["w1"], result["w2"], result["w3"]) == ("gthread", "eventlet", "gthread")
    lines = env.read_text().splitlines()
    assert sum(1 for line in lines if re.match(r"\s*OPENALGO_WORKER_CLASS\s*=", line)) == 1
    assert "A='1'" in lines and "B='2'" in lines
    assert "# OPENALGO_WORKER_CLASS = 'eventlet'" in lines
    # Same file (the container bind-mounts it) and still owner-only
    assert env.stat().st_ino == inode
    assert stat.S_IMODE(env.stat().st_mode) == 0o600


def test_worker_choice_inside_trading_hours_needs_a_yes(tmp_path):
    result, _ = _run(
        tmp_path,
        """
        echo "RESULT declined=$(choose_worker_class d eventlet)"
        echo "RESULT accepted=$(choose_worker_class d eventlet)"
        """,
        stdin="gthread\nno\ngthread\nyes\n",
        extra_env={"OPENALGO_NOW_HHMM": "1030"},
    )
    assert result == {"declined": "eventlet", "accepted": "gthread"}


def test_worker_choice_after_the_close_needs_no_confirmation(tmp_path):
    result, _ = _run(
        tmp_path,
        'echo "RESULT w=$(choose_worker_class d eventlet)"',
        stdin="gthread\n",
        extra_env={"OPENALGO_NOW_HHMM": "2345"},
    )
    assert result["w"] == "gthread"


def test_worker_choice_boundaries_and_overrides(tmp_path):
    result, _ = _run(
        tmp_path,
        """
        for t in 0859 0900 2329 2330; do
            OPENALGO_NOW_HHMM=$t in_trading_hours && echo "RESULT t$t=trading" || echo "RESULT t$t=closed"
        done
        echo "RESULT forced=$(FORCE_WORKER_SWITCH=1 OPENALGO_NOW_HHMM=1100 INSTALL_WORKER_CLASS=gthread choose_worker_class d eventlet)"
        echo "RESULT new=$(OPENALGO_NOW_HHMM=1100 INSTALL_WORKER_CLASS=gthread choose_worker_class d eventlet new)"
        echo "RESULT same=$(OPENALGO_NOW_HHMM=1100 choose_worker_class d gthread)"
        """,
        stdin="\n",
    )
    assert result["t0859"] == "closed" and result["t0900"] == "trading"
    assert result["t2329"] == "trading" and result["t2330"] == "closed"
    assert result["forced"] == "gthread"
    assert result["new"] == "gthread"
    assert result["same"] == "gthread"


# ------------------------------------------------------------------- compose


def _compose(tmp_path, extra_env=None, pin=""):
    out = tmp_path / "docker-compose.yaml"
    _run(
        tmp_path,
        f"""
        PROJECT_NAME=openalgo-test FLASK_PORT=5357 WS_PORT=9122
        compute_resources unrestricted 7905 2 2
        PYPI_EDGE_PIN="{pin}"
        write_instance_compose {out}
        """,
        extra_env=extra_env,
    )
    return out.read_text()


def test_generated_compose_always_has_the_gthread_stop_grace_period(tmp_path):
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(_compose(tmp_path))
    svc = doc["services"]["openalgo"]
    assert svc["stop_grace_period"] == "45s"
    assert svc["shm_size"] == "1024m"
    assert "STRATEGY_MEMORY_LIMIT_MB=3072" in svc["environment"]
    assert "mem_limit" not in svc
    assert "extra_hosts" not in svc["build"]
    assert svc["ports"] == ["127.0.0.1:5357:5000", "127.0.0.1:9122:8765"]


def test_compose_pins_the_pypi_edge_and_sets_a_container_limit_only_when_asked(tmp_path):
    yaml = pytest.importorskip("yaml")
    svc = yaml.safe_load(
        _compose(tmp_path, {"OPENALGO_CONTAINER_MEM_MB": "6144"}, pin="151.101.128.223")
    )["services"]["openalgo"]
    assert svc["build"]["extra_hosts"] == ["files.pythonhosted.org:151.101.128.223"]
    assert svc["mem_limit"] == "6144m"


def test_pypi_edge_setting(tmp_path):
    result, _ = _run(
        tmp_path,
        """
        echo "RESULT unset=$(select_pypi_edge)"
        echo "RESULT fixed=$(PYPI_EDGE_IP=1.2.3.4 select_pypi_edge)"
        """,
    )
    assert result["unset"] == ""
    assert result["fixed"] == "1.2.3.4"


def test_pypi_edge_auto_pins_only_for_a_clear_win(tmp_path):
    body = """
    pypi_probe_url() { echo http://probe; }
    probe_pypi_speed() {
        case "$2" in
            "") echo "$BASE" ;;
            151.101.128.223) echo "$FAST" ;;
            *) echo 40000 ;;
        esac
    }
    echo "RESULT pick=$(PYPI_EDGE_IP=auto select_pypi_edge)"
    """
    slow_dns, _ = _run(tmp_path, body, extra_env={"BASE": "20000", "FAST": "35000000"})
    assert slow_dns["pick"] == "151.101.128.223"
    healthy_dns, _ = _run(tmp_path, body, extra_env={"BASE": "9000000", "FAST": "35000000"})
    assert healthy_dns["pick"] == ""
    no_win, _ = _run(tmp_path, body, extra_env={"BASE": "20000", "FAST": "60000"})
    assert no_win["pick"] == ""


# --------------------------------------------------------- start verification


def _docker_stub(tmp_path, log_text):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    logfile = tmp_path / "container.log"
    logfile.write_text(log_text)
    stub = bindir / "docker"
    stub.write_text(f'#!/bin/bash\n[ "$2" = "logs" ] && cat "{logfile}"\nexit 0\n')
    stub.chmod(0o755)
    (tmp_path / "opt" / "a.example.com").mkdir(parents=True)
    return str(bindir)


@pytest.mark.parametrize(
    "log_text, expected, rc",
    [
        ("[OpenAlgo] Starting application on port 5000 with gthread...\n", "gthread", "0"),
        ("[OpenAlgo] Starting application on port 5000 with eventlet...\n", "eventlet", "0"),
        # gthread asked for, eventlet started: the silent fallback
        ("[OpenAlgo] Starting application on port 5000 with eventlet...\n", "gthread", "1"),
        ("[OpenAlgo] Starting application on port 5000 with gthread...\n", "eventlet", "1"),
        # container not yet logging
        ("starting up\n", "gthread", "2"),
    ],
)
def test_verify_worker_started(tmp_path, log_text, expected, rc):
    bindir = _docker_stub(tmp_path, log_text)
    result, _ = _run(
        tmp_path,
        f"""
        VERIFY_POLL_SECONDS=1
        verify_worker_started "$INSTALL_BASE/a.example.com" {expected} 1
        echo "RESULT rc=$?"
        """,
        path_prefix=bindir,
    )
    assert result["rc"] == rc


def test_script_syntax_is_valid():
    assert subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0


# ------------------------------------------------------- configuration phase


def _config_phase_source():
    """The interactive configuration section, cut out of the real script."""
    text = SCRIPT.read_text()
    start = text.index("# 0. Git Repository Selection")
    end = text.index("# -----------------\n# Deployment Loop")
    return text[start:end]


def _make_instance(root, domain, broker_key="KEY", worker_line=""):
    d = root / domain
    (d / ".git").mkdir(parents=True)
    (d / ".env").write_text(
        f"BROKER_API_KEY = '{broker_key}'\nBROKER_API_SECRET = 'SECRET'\n"
        f"REDIRECT_URL = 'https://{domain}/upstox/callback'\n{worker_line}"
    )


def test_config_phase_keeps_per_instance_choices_aligned_with_domains(tmp_path):
    """Two existing instances in one run: one keeps eventlet/auto with Enter, the
    other is moved to gthread/unrestricted. Each answer must land on its own
    domain, in the arrays the deploy loop reads by index."""
    opt = tmp_path / "opt"
    _make_instance(opt, "zerodha.example.com")
    _make_instance(opt, "upstox.example.com")
    (opt / "upstox.example.com" / ".installer.conf").write_text("MEMORY_PROFILE=auto\n")

    cfg = tmp_path / "config_phase.sh"
    cfg.write_text(_config_phase_source())
    stdin = "\nzerodha.example.com upstox.example.com\ny\n\n\ny\ngthread\nunrestricted\n"
    result, proc = _run(
        tmp_path,
        f"""
        source "{cfg}"
        for i in "${{!CONF_DOMAINS[@]}}"; do
            echo "RESULT d$i=${{CONF_DOMAINS[$i]}}|${{CONF_PREV_WORKERS[$i]}}|${{CONF_WORKERS[$i]}}|${{CONF_PROFILES[$i]}}|${{UPDATE_MODE[$i]}}"
        done
        """,
        stdin=stdin,
        extra_env={"OPENALGO_NOW_HHMM": "2345"},
    )
    assert result["d0"] == "zerodha.example.com|eventlet|eventlet|auto|true"
    assert result["d1"] == "upstox.example.com|eventlet|gthread|unrestricted|true"


def test_config_phase_reports_existing_gthread_and_enter_keeps_it(tmp_path):
    opt = tmp_path / "opt"
    _make_instance(opt, "upstox.example.com", worker_line="OPENALGO_WORKER_CLASS = 'gthread'\n")
    (opt / "upstox.example.com" / ".installer.conf").write_text("MEMORY_PROFILE=unrestricted\n")
    cfg = tmp_path / "config_phase.sh"
    cfg.write_text(_config_phase_source())
    result, _ = _run(
        tmp_path,
        f"""
        source "{cfg}"
        echo "RESULT d0=${{CONF_PREV_WORKERS[0]}}|${{CONF_WORKERS[0]}}|${{CONF_PROFILES[0]}}"
        """,
        stdin="\nupstox.example.com\ny\n\n\n",
        extra_env={"OPENALGO_NOW_HHMM": "1100"},
    )
    assert result["d0"] == "gthread|gthread|unrestricted"


# ---------------------------------------------------------------- git details


def _git_repo(path, branch="main"):
    path.mkdir(parents=True)
    env = dict(
        os.environ,
        GIT_AUTHOR_NAME="t",
        GIT_AUTHOR_EMAIL="t@t",
        GIT_COMMITTER_NAME="t",
        GIT_COMMITTER_EMAIL="t@t",
    )

    def run(*a):
        return subprocess.run(
            ["git", "-C", str(path), *a], check=True, capture_output=True, env=env
        )

    run("init", "-q", "-b", branch)
    (path / "f").write_text("1")
    run("add", "f")
    run("commit", "-q", "-m", "one")
    return run, env


def test_git_info_is_refreshed_on_every_run_and_never_duplicated(tmp_path):
    repo = tmp_path / "inst"
    run, env = _git_repo(repo)
    envfile = tmp_path / ".env"
    # An old install: stale values from the run that created it, plus other settings
    envfile.write_text(
        "A='1'\nOPENALGO_GIT_BRANCH = 'old-branch'\nOPENALGO_GIT_COMMIT = 'deadbee'\nB='2'\n"
    )
    os.chmod(envfile, 0o600)
    inode = envfile.stat().st_ino

    result, _ = _run(
        tmp_path,
        f"""
        set_git_info {repo} {envfile}
        echo "RESULT c1=$(grep '^OPENALGO_GIT_COMMIT' {envfile} | cut -d"'" -f2)"
        set_git_info {repo} {envfile}
        """,
    )
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    assert result["c1"] == head

    # A new commit on another branch is picked up on the next run
    run("checkout", "-q", "-b", "feature")
    (repo / "f").write_text("2")
    run("commit", "-q", "-am", "two")
    _run(tmp_path, f"set_git_info {repo} {envfile}")
    head2 = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], capture_output=True, text=True
    ).stdout.strip()

    lines = envfile.read_text().splitlines()
    assert lines.count(f"OPENALGO_GIT_COMMIT = '{head2}'") == 1
    assert "OPENALGO_GIT_BRANCH = 'feature'" in lines
    assert sum(1 for line in lines if line.startswith("OPENALGO_GIT_")) == 2
    assert "A='1'" in lines and "B='2'" in lines
    assert envfile.stat().st_ino == inode
    assert stat.S_IMODE(envfile.stat().st_mode) == 0o600


def test_git_info_is_empty_but_harmless_outside_a_repository(tmp_path):
    envfile = tmp_path / ".env"
    envfile.write_text("A='1'\n")
    (tmp_path / "nogit").mkdir()
    _run(tmp_path, f"set_git_info {tmp_path / 'nogit'} {envfile}")
    assert "OPENALGO_GIT_COMMIT = ''" in envfile.read_text()


def test_new_install_no_longer_appends_git_info_before_the_build():
    text = SCRIPT.read_text()
    assert 'echo "OPENALGO_GIT_COMMIT' not in text
    # Written once, after the image has built, for new and updated instances alike
    call = text.index('    set_git_info "$INSTANCE_DIR" "$ENV_FILE"')
    assert text.count('set_git_info "$INSTANCE_DIR" "$ENV_FILE"') == 1
    assert (
        text.index("if ! docker compose build; then")
        < call
        < text.index("docker compose up -d $UP_FLAGS")
    )


# ---------------------------------------------------------------- openalgo-ctl


def _ctl_script(tmp_path):
    """The generated management tool, cut out of the installer and pointed at a
    temporary instance directory."""
    text = SCRIPT.read_text()
    start = text.index("cat <<'EOF' > /usr/local/bin/openalgo-ctl\n") + len(
        "cat <<'EOF' > /usr/local/bin/openalgo-ctl\n"
    )
    body = text[start : text.index("\nEOF\n", start)]
    body = body.replace('INSTALL_BASE="/opt/openalgo"', f'INSTALL_BASE="{tmp_path / "opt"}"')
    ctl = tmp_path / "openalgo-ctl"
    ctl.write_text(body)
    ctl.chmod(0o755)
    return str(ctl)


def _ctl_docker(tmp_path, running_args):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    stub = bindir / "docker"
    stub.write_text(
        "#!/bin/bash\n"
        'if [ "$1" = "compose" ] && [ "$2" = "ps" ] && [ "$3" = "-q" ]; then echo abc123; exit 0; fi\n'
        # like the real docker: `top` fails unless the ps format has a pid column
        f'if [ "$1" = "top" ]; then case "$*" in *pid*) echo "1 {running_args}"; exit 0;; *) echo "Error response from daemon: Couldn\'t find PID field in ps output" >&2; exit 1;; esac; fi\n'
        'echo "docker $*" >> "$DOCKER_CALLS"; exit 0\n'
    )
    stub.chmod(0o755)
    return str(bindir)


COMPOSE_WITH_GRACE = "services:\n  openalgo:\n    stop_grace_period: 45s\n"


def _run_ctl(tmp_path, args, running_args, hhmm="2345", stdin="", compose=COMPOSE_WITH_GRACE):
    inst = tmp_path / "opt" / "a.example.com"
    inst.mkdir(parents=True, exist_ok=True)
    if not (inst / ".env").exists():
        (inst / ".env").write_text("A='1'\n")
    (inst / "docker-compose.yaml").write_text(compose)
    calls = tmp_path / "calls.log"
    calls.write_text("")
    env = dict(os.environ, DOCKER_CALLS=str(calls), OPENALGO_NOW_HHMM=hhmm)
    env["PATH"] = f"{_ctl_docker(tmp_path, running_args)}:{env['PATH']}"
    proc = subprocess.run(
        [_ctl_script(tmp_path), *args],
        capture_output=True,
        text=True,
        env=env,
        input=stdin,
        timeout=60,
    )
    return proc, calls.read_text(), (inst / ".env").read_text()


GTHREAD_ARGS = (
    "/app/.venv/bin/python /app/.venv/bin/gunicorn -c hooks.py --worker-class gthread --threads 64"
)
EVENTLET_ARGS = "/app/.venv/bin/python /app/.venv/bin/gunicorn --worker-class eventlet --workers 1"


def test_ctl_worker_reports_what_env_asks_for_and_what_runs(tmp_path):
    proc, calls, _ = _run_ctl(tmp_path, ["worker", "a.example.com"], GTHREAD_ARGS)
    assert proc.returncode == 0
    assert "asks for eventlet; running on gthread" in proc.stdout
    assert calls == ""  # read-only


def test_ctl_worker_without_change_does_nothing(tmp_path):
    inst = tmp_path / "opt" / "a.example.com"
    inst.mkdir(parents=True)
    (inst / ".env").write_text("OPENALGO_WORKER_CLASS = 'gthread'\n")
    proc, calls, _ = _run_ctl(tmp_path, ["worker", "a.example.com", "gthread"], GTHREAD_ARGS)
    assert "already runs on gthread" in proc.stdout
    assert calls == ""


def test_ctl_worker_switch_recreates_and_declines_in_trading_hours(tmp_path):
    proc, calls, env_text = _run_ctl(
        tmp_path, ["worker", "a.example.com", "gthread"], EVENTLET_ARGS, hhmm="1030", stdin="no\n"
    )
    assert "trading time" in proc.stdout and "Cancelled" in proc.stdout
    assert calls == "" and "OPENALGO_WORKER_CLASS" not in env_text


def test_ctl_worker_switch_after_close_writes_env_and_recreates(tmp_path):
    proc, calls, env_text = _run_ctl(tmp_path, ["worker", "a.example.com", "gthread"], GTHREAD_ARGS)
    assert "docker compose up -d --force-recreate" in calls
    assert env_text.count("OPENALGO_WORKER_CLASS = 'gthread'") == 1 and "A='1'" in env_text
    assert "now running on gthread" in proc.stdout and proc.returncode == 0


def test_ctl_worker_switch_fails_when_the_other_server_starts(tmp_path):
    proc, _, _ = _run_ctl(tmp_path, ["worker", "a.example.com", "gthread"], EVENTLET_ARGS)
    assert proc.returncode == 1 and "now running on eventlet (asked for gthread)" in proc.stdout


def test_ctl_worker_refuses_a_compose_file_without_the_grace_period(tmp_path):
    proc, calls, env_text = _run_ctl(
        tmp_path,
        ["worker", "a.example.com", "gthread"],
        GTHREAD_ARGS,
        compose="services:\n  openalgo: {}\n",
    )
    assert proc.returncode == 1 and "stop_grace_period" in proc.stdout
    assert calls == "" and "OPENALGO_WORKER_CLASS" not in env_text


def test_snapshot_stays_out_of_the_docker_build_context(tmp_path):
    """The instance directory is the build context (COPY . .). A snapshot file in
    it changes every run, so a run that changed nothing still rebuilt the image
    and recreated the container."""
    inst = tmp_path / "opt" / "a.example.com"
    inst.mkdir(parents=True)
    _generated_compose(inst / "docker-compose.yaml", 5357, 9122)
    result, _ = _run(
        tmp_path,
        """
        snapshot_instance_config "$INSTALL_BASE/a.example.com" a.example.com
        echo "RESULT inside=$(find "$INSTALL_BASE/a.example.com" -name '*pre-deploy*' | wc -l | tr -d ' ')"
        echo "RESULT outside=$(find "$INSTALL_BASE/.deploy-snapshots" -name '*pre-deploy' | wc -l | tr -d ' ')"
        echo "RESULT scan=$(get_next_ports)"
        echo "RESULT ports=$(resolve_instance_ports a.example.com)"
        restore_instance_config "$INSTALL_BASE/a.example.com" a.example.com
        echo "RESULT leftovers=$(find "$INSTALL_BASE" -name '*.pre-deploy' | wc -l | tr -d ' ')"
        """,
    )
    assert result == {
        "inside": "0",
        "outside": "1",
        "scan": "5358 9123",
        "ports": "5357 9122",
        "leftovers": "0",
    }
