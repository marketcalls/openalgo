"""A failed build must not leave a domain pointing at ports nothing serves.

install-docker-multi-custom-ssl.sh regenerates two files per instance before it
builds the image -- the compose port mappings and the Nginx vhost upstreams --
and reloads Nginx once, after the loop, from whatever is on disk by then. When a
build fails the script skips `docker compose up -d`, so the container that was
already running keeps its existing ports. Without restoring those two files the
reload would activate the newly allocated ports and take a working instance
offline, which is worse than the stale image the skip exists to prevent.

The installer needs root, Docker, apt and Nginx, so it cannot be run end to end
here. It is sourced with OPENALGO_INSTALLER_LIB_ONLY=1, which returns before any
imperative section, and the real snapshot/restore helpers are driven directly
against temporary directories.
"""

import pathlib
import re
import subprocess

import pytest

SCRIPT = (
    pathlib.Path(__file__).resolve().parents[1]
    / "install"
    / "install-docker-multi-custom-ssl.sh"
)


def _run(tmp_path, body):
    """Source the installer's helpers and run `body` against temp directories."""
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
# Set after sourcing: the script assigns INSTALL_BASE unconditionally.
INSTALL_BASE="{instances}"

# Stand in for the generation steps the deploy loop performs.
write_compose() {{ printf '      - "127.0.0.1:%s:5000"\\n      - "127.0.0.1:%s:8765"\\n' "$2" "$3" > "$1/docker-compose.yaml"; }}
write_vhost()   {{ printf 'server 127.0.0.1:%s;\\nserver 127.0.0.1:%s;\\n' "$2" "$3" > "$NGINX_SITES_AVAILABLE/$1"; }}
ports_of()      {{ grep -oE '127\\.0\\.0\\.1:[0-9]+' "$1" | cut -d: -f2 | tr '\\n' ' '; }}

{body}
"""
    proc = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, f"harness failed:\n{proc.stdout}\n{proc.stderr}"
    return dict(re.findall(r"^RESULT (\S+)=(.*)$", proc.stdout, re.M))


def _flask_ws(value):
    """'5001 8766 ' -> ('5001', '8766'): the host side of each mapping."""
    nums = value.split()
    assert len(nums) == 2, f"expected a flask and a ws port, got {value!r}"
    return nums[0], nums[1]


@pytest.mark.skipif(not SCRIPT.exists(), reason="installer script not present")
def test_failed_build_keeps_existing_routing_and_sibling_still_deploys(tmp_path):
    """The failed domain keeps its old ports; an unrelated domain still moves."""
    result = _run(
        tmp_path,
        """
        # --- fails.example.com: already deployed on 5001/8766, build will fail
        FAILED_DIR="$INSTALL_BASE/fails.example.com"
        mkdir -p "$FAILED_DIR"
        write_compose "$FAILED_DIR" 5001 8766
        write_vhost fails.example.com 5001 8766
        ln -sf "$NGINX_SITES_AVAILABLE/fails.example.com" "$NGINX_SITES_ENABLED/"

        snapshot_instance_config "$FAILED_DIR" fails.example.com
        write_compose "$FAILED_DIR" 5004 8769          # allocator moved the ports
        write_vhost fails.example.com 5004 8769
        restore_instance_config "$FAILED_DIR" fails.example.com   # build failed

        echo "RESULT failed_compose=$(ports_of "$FAILED_DIR/docker-compose.yaml")"
        echo "RESULT failed_vhost=$(ports_of "$NGINX_SITES_AVAILABLE/fails.example.com")"
        echo "RESULT failed_enabled=$([ -L "$NGINX_SITES_ENABLED/fails.example.com" ] && echo yes || echo no)"

        # --- works.example.com: deploys successfully in the same run
        OK_DIR="$INSTALL_BASE/works.example.com"
        mkdir -p "$OK_DIR"
        write_compose "$OK_DIR" 5002 8767
        write_vhost works.example.com 5002 8767

        snapshot_instance_config "$OK_DIR" works.example.com
        write_compose "$OK_DIR" 5005 8770
        write_vhost works.example.com 5005 8770
        discard_instance_snapshot "$OK_DIR" works.example.com     # build succeeded

        echo "RESULT ok_compose=$(ports_of "$OK_DIR/docker-compose.yaml")"
        echo "RESULT ok_vhost=$(ports_of "$NGINX_SITES_AVAILABLE/works.example.com")"
        echo "RESULT leftovers=$(find "$INSTALL_BASE" "$NGINX_SITES_AVAILABLE" -name '*.pre-deploy' | wc -l | tr -d ' ')"
        """,
    )

    # The failed instance is back on the ports its container actually listens on,
    # and compose and Nginx agree -- this is the regression under test.
    assert _flask_ws(result["failed_compose"]) == ("5001", "8766")
    assert _flask_ws(result["failed_vhost"]) == ("5001", "8766")
    assert _flask_ws(result["failed_compose"]) == _flask_ws(result["failed_vhost"])
    assert result["failed_enabled"] == "yes", "working vhost must stay enabled"

    # One domain failing must not hold back another.
    assert _flask_ws(result["ok_compose"]) == ("5005", "8770")
    assert _flask_ws(result["ok_vhost"]) == ("5005", "8770")

    # No snapshot files survive a completed run.
    assert result["leftovers"] == "0"


@pytest.mark.skipif(not SCRIPT.exists(), reason="installer script not present")
def test_failed_fresh_install_leaves_no_dead_vhost(tmp_path):
    """A first-time install that fails has nothing to restore, so it leaves nothing."""
    result = _run(
        tmp_path,
        """
        NEW_DIR="$INSTALL_BASE/brand-new.example.com"
        mkdir -p "$NEW_DIR"

        snapshot_instance_config "$NEW_DIR" brand-new.example.com   # nothing exists yet
        write_compose "$NEW_DIR" 5006 8771
        write_vhost brand-new.example.com 5006 8771
        ln -sf "$NGINX_SITES_AVAILABLE/brand-new.example.com" "$NGINX_SITES_ENABLED/"
        restore_instance_config "$NEW_DIR" brand-new.example.com    # build failed

        echo "RESULT vhost=$([ -f "$NGINX_SITES_AVAILABLE/brand-new.example.com" ] && echo present || echo absent)"
        echo "RESULT enabled=$([ -L "$NGINX_SITES_ENABLED/brand-new.example.com" ] && echo present || echo absent)"
        """,
    )

    assert result["vhost"] == "absent"
    assert result["enabled"] == "absent"
