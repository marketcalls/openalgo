"""
OpenAlgo System Update blueprint — update OpenAlgo from the web UI.

Routes
  GET  /api/update/status → { install_type, current, branch, behind,
                              update_running, update_result, last_log }
  POST /api/update/run    → {"confirm": true, "force": false}
  GET  /system-update     → standalone page with the update button

Install layouts
  server  /var/python/openalgo   git checkout + systemd unit `openalgo`
  docker  inside a container     code is baked into the image; the request is
                                 written to the shared /app/tmp volume and
                                 fulfilled on the host by
                                 install/host_update_watcher.sh (cron, 1 min)
  local   any other checkout     same manual sequence, no service restart

Both paths follow install/update.sh: back up db/*, pull, sync deps, run
upgrade/migrate_all.py, restart. Docker rebuilds the image and recreates the
container; named volumes (db, log, keys, strategies) survive.

Security
  - @check_session_validity on every route (must be logged in)
  - Rate-limited (status: API_RATE_LIMIT, run: 3/minute)
  - POST needs {"confirm": true} and the Flask-WTF X-CSRFToken header
  - One run at a time: O_EXCL lock claim (/tmp/openalgo_update.lock, or the
    docker request flag + a "running" result) — concurrent POSTs get 409
  - Market hours (09:00–15:30 IST) are refused unless force is set, here and
    again in the updater script / host watcher
  - Server installs run the root-owned wrapper /usr/local/sbin/openalgo-update
    (sudoers pins that path + the app path), which drops to the checkout owner
    for all repo work — a web-writable script is never executed as root
  - Secrets are never logged; only git SHAs and the updater log tail are returned
"""

import os
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request

from limiter import limiter
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "50 per second")

system_update_bp = Blueprint("system_update_bp", __name__)

# Shared-volume flag protocol (docker mode). /app/tmp is a named volume, so
# the container writes the request and the host watcher cron fulfils it.
REQUEST_FILE = Path("/app/tmp/update_requested.json")
RESULT_FILE = Path("/app/tmp/update_result.json")

# Root-owned updater wrapper (docs/system-update.md). sudoers grants NOPASSWD
# only on this path with the app path pinned as its argument, so a script the
# web user can edit inside the checkout is never executed as root.
WRAPPER = Path("/usr/local/sbin/openalgo-update")

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _detect_install():
    """Return (install_type, app_path, service_name)."""
    candidates = [
        ("/var/python/openalgo", "server", "openalgo"),
        ("/opt/openalgo", "docker", None),
    ]
    for path, itype, service in candidates:
        if Path(path, "app.py").exists() and Path(path, ".git").exists():
            # legacy multi-deploy / install-multi layouts share the parent;
            # service name is derived at runtime in update_web.sh
            return itype, path, service
    if Path("/.dockerenv").exists():
        # Inside a container: code is baked into the image (/app is the docroot,
        # /app/tmp is the shared volume back to the host).
        return "docker", "/app", "openalgo-web"
    # fall back: this checkout itself (local dev)
    here = Path(__file__).resolve().parents[1]
    if (here / "app.py").exists():
        return "local", str(here), None
    return "unknown", str(here), None


def _git(cmd, cwd):
    try:
        out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=20)
        return out.stdout.strip(), out.returncode
    except Exception as e:
        logger.warning(f"git failed {cmd}: {e}")
        return "", 1


def _read_json(path):
    try:
        import json

        return json.loads(Path(path).read_text())
    except Exception:
        return None


def _read_stamp(path):
    try:
        return Path(path).read_text().strip() or "unknown"
    except OSError:
        return "unknown"


def _claim_exclusive(path, content=""):
    """Create `path` with O_CREAT|O_EXCL — the atomic form of exists().

    Returns True when this caller won the race. Any OSError (including
    FileExistsError) returns False, so a second concurrent run can never
    slip past a check-then-create pair. A failed write (e.g. ENOSPC) removes
    the half-written claim again instead of blocking all future updates.
    """
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        return False
    try:
        os.write(fd, content.encode())
    except OSError:
        os.close(fd)
        try:
            os.unlink(path)
        except OSError:
            pass
        return False
    os.close(fd)
    return True


def _github_behind(slug, sha, branch, timeout=8):
    """Commits branch is ahead of sha (== our behind count), via GitHub API.

    Pure stdlib so it works in the slim image. Best-effort: -1 on any failure
    (offline, rate-limited, non-GitHub remote).
    """
    import json as _json
    import urllib.request as _url

    if not slug or not sha or sha == "unknown":
        return -1
    url = f"https://api.github.com/repos/{slug}/compare/{sha}...{branch}"
    try:
        req = _url.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "openalgo-update-check",
            },
        )
        with _url.urlopen(req, timeout=timeout) as resp:
            data = _json.loads(resp.read().decode("utf-8", "replace"))
        behind = data.get("behind_by")
        return int(behind) if behind is not None else -1
    except Exception as e:
        logger.warning(f"github compare failed: {e}")
        return -1


def _slug_from_remote(remote):
    """owner/repo from a git remote URL (https or ssh), else None."""
    import re as _re

    if not remote or remote == "unknown":
        return None
    m = _re.search(r"github\.com[/:]([^/]+/[^/]+?)(?:\.git)?$", remote.strip())
    return m.group(1) if m else None


def _in_market_hours(now_ist=None):
    """True during NSE/BSE cash hours (09:00–15:30 IST, inclusive)."""
    try:
        from zoneinfo import ZoneInfo

        zone = ZoneInfo("Asia/Kolkata")
        now_ist = now_ist or datetime.now(zone)
        if now_ist.tzinfo is None:
            now_ist = now_ist.replace(tzinfo=zone)
        mins = now_ist.hour * 60 + now_ist.minute
        return 9 * 60 <= mins <= 15 * 60 + 30
    except Exception:
        # Never block an update because the timezone db is missing.
        return False


# Cache for the GitHub behind-count: unauthenticated API allows 60 req/hr
# per egress IP, and the status page auto-refreshes — never hit the API
# more than once per TTL per (slug, sha, branch).
_BEHIND_CACHE: dict = {}
_BEHIND_TTL_SECONDS = 1800


def _behind_cached(slug, sha, branch):
    import time as _time

    key = (slug, sha, branch)
    now = _time.time()
    hit = _BEHIND_CACHE.get(key)
    if hit and now - hit[1] < _BEHIND_TTL_SECONDS:
        return hit[0]
    # Reserve the key BEFORE the call so concurrent status polls don't all
    # miss and stampede the API; readers see -1 ("unknown") while in flight
    # and the real value replaces the reservation when it returns.
    _BEHIND_CACHE[key] = (-1, now)
    val = _github_behind(slug, sha, branch)
    _BEHIND_CACHE[key] = (val, now)
    # bound memory: drop entries for other SHAs (deploys move SHA forward)
    for k in [k for k in _BEHIND_CACHE if k[1] != sha]:
        del _BEHIND_CACHE[k]
    return val


def _docker_status():
    """Version info inside the container: baked stamps + live GitHub compare."""
    sha = _read_stamp("/app/BUILD_SHA")
    branch = _read_stamp("/app/BUILD_BRANCH")
    remote = _read_stamp("/app/BUILD_REMOTE")
    if branch == "unknown":
        branch = "main"
    slug = _slug_from_remote(remote)
    behind = _behind_cached(slug, sha, branch) if slug else -1
    return sha, branch, behind


def _update_status():
    itype, app_path, service = _detect_install()
    running = False
    lock = None
    if itype == "docker":
        current, branch, behind_n = _docker_status()
    else:
        current, _ = _git(["git", "rev-parse", "--short", "HEAD"], app_path)
        branch, _ = _git(["git", "branch", "--show-current"], app_path)
        branch = branch or "main"
        lock = Path("/tmp/openalgo_update.lock")
        running = lock.exists()
        if not running:
            # Refresh the comparison ref quietly (best effort, 15s cap).
            # Skipped while an update runs: a fetch racing the updater's own
            # `git pull` can make the update fail.
            try:
                subprocess.run(
                    ["git", "fetch", "--quiet"],
                    cwd=app_path,
                    capture_output=True,
                    timeout=15,
                )
            except Exception:
                pass
        upstream, _ = _git(
            ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
            app_path,
        )
        # Forks often track a remote that is not origin, so compare against the
        # configured upstream and fall back to origin/<branch> when unset.
        compare = upstream or f"origin/{branch}"
        behind, _ = _git(["git", "rev-list", "--count", f"HEAD..{compare}"], app_path)
        try:
            behind_n = int(behind)
        except (TypeError, ValueError):
            behind_n = -1  # unknown (offline?)
    if lock is not None:
        running = running or lock.exists()
    update_result = None
    if itype == "docker":
        # In docker mode the "running" signal is the request flag in the
        # shared volume (host watcher deletes it when it starts work), plus
        # the result file the watcher writes back.
        if REQUEST_FILE.exists():
            running = True
        update_result = _read_json(RESULT_FILE)
        if isinstance(update_result, dict) and update_result.get("state") == "running":
            running = True
    # last 30 lines of web-update log
    log_tail = ""
    for lp in (
        Path(app_path) / "log" / "update_web.log",
        Path(app_path) / "install" / "logs" / "update_web.log",
    ):
        if lp.exists():
            try:
                lines = lp.read_text(errors="replace").splitlines()[-30:]
                log_tail = "\n".join(lines)
                break
            except OSError:
                pass
    return {
        "install_type": itype,
        "path": app_path,
        "service": service,
        "current": current or "unknown",
        "branch": branch,
        "behind": behind_n,
        "update_running": running,
        "update_result": update_result,
        "last_log": log_tail,
        "server_time": datetime.now().isoformat(timespec="seconds"),
    }


def _launch_update_detached(app_path, itype, force=False):
    """Launch the updater detached (survives the gunicorn restart).

    Server installs go through the root-owned wrapper when installed;
    local checkouts run the in-tree script directly — no sudo, since there
    is no systemd unit to restart and the user owns the checkout.
    """
    script = str(Path(app_path) / "install" / "update_web.sh")
    if WRAPPER.exists():
        argv = ["sudo", "/bin/bash", str(WRAPPER), str(app_path)]
    elif itype == "server":
        argv = ["sudo", "/bin/bash", script]
    else:
        argv = ["/bin/bash", script]
    logf = str(Path(app_path) / "log" / "update_web.log")
    Path(app_path, "log").mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    if force:
        # The route already vetted force; pass it down so update_web.sh's own
        # market-hours guard does not refuse a confirmed forced run.
        env["WEB_UPDATE_FORCE"] = "1"
    # start_new_session=True detaches the child into its own session, so
    # `systemctl restart openalgo` cannot kill the updater mid-flight.
    with open(logf, "a") as log_fh:
        subprocess.Popen(
            argv,
            cwd=app_path,
            env=env,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    return logf


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------


@system_update_bp.route("/api/update/status")
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def api_update_status():
    try:
        resp = jsonify({"status": "success", "data": _update_status()})
        resp.headers["Cache-Control"] = "no-store, max-age=0"
        return resp
    except Exception as e:
        logger.exception(f"update status failed: {e}")
        return jsonify({"status": "error", "message": "Failed to read update status"}), 500


@system_update_bp.route("/api/update/run", methods=["POST"])
@check_session_validity
@limiter.limit("3/minute")
def api_update_run():
    try:
        data = request.get_json(silent=True) or {}
        if data.get("confirm") is not True:
            return jsonify(
                {"status": "error", "message": 'Send {"confirm": true} to start the update.'}
            ), 400

        itype, app_path, service = _detect_install()
        if itype == "unknown":
            return jsonify({"status": "error", "message": "OpenAlgo checkout not found."}), 500

        # Market-hours guard (IST 09:00–15:30). Best-effort here — the
        # updater / host watcher re-enforces it authoritatively.
        force = data.get("force") is True
        if _in_market_hours() and not force:
            return jsonify(
                {
                    "status": "error",
                    "message": (
                        "Market hours (09:00–15:30 IST). "
                        'Update anyway? Resend with {"confirm": true, "force": true}.'
                    ),
                    "market_hours": True,
                }
            ), 423

        if itype == "docker":
            # Container code is baked into the image — it cannot rebuild
            # itself. Drop a request flag in the shared /app/tmp volume;
            # the host watcher cron (install/host_update_watcher.sh) picks
            # it up within a minute: git pull + compose build + up -d.
            import json

            result = _read_json(RESULT_FILE)
            already = REQUEST_FILE.exists() or (
                isinstance(result, dict) and result.get("state") == "running"
            )
            if already:
                return jsonify(
                    {
                        "status": "error",
                        "message": "An update is already requested/running. Check status.",
                    }
                ), 409
            payload = json.dumps(
                {
                    "requested_at": datetime.now().isoformat(timespec="seconds"),
                    "force": force,
                    "branch": _read_stamp("/app/BUILD_BRANCH"),
                    "sha": _read_stamp("/app/BUILD_SHA"),
                }
            )
            # O_EXCL claim: two clicks in the same second cannot both pass.
            if not _claim_exclusive(REQUEST_FILE, payload):
                return jsonify(
                    {
                        "status": "error",
                        "message": "An update is already requested/running. Check status.",
                    }
                ), 409
            logger.info(f"Web update requested (docker flag: {REQUEST_FILE})")
            return jsonify(
                {
                    "status": "success",
                    "message": (
                        "Update requested. The host watcher picks it up within ~1 min, "
                        "then rebuilds and restarts the container — this page will "
                        "disconnect. Check back in a few minutes."
                    ),
                    "data": {
                        "install_type": itype,
                        "path": app_path,
                        "service": service,
                        "via": "host-watcher",
                    },
                }
            )

        script = Path(app_path) / "install" / "update_web.sh"
        if not script.exists():
            return jsonify(
                {
                    "status": "error",
                    "message": f"Updater script missing: {script}. Copy install/update_web.sh first.",
                }
            ), 500

        lock = Path("/tmp/openalgo_update.lock")
        # Atomic claim — a second concurrent POST gets 409 even if both pass
        # the market-hours check in the same instant.
        if not _claim_exclusive(lock, f"started {datetime.now().isoformat()} by web\n"):
            return jsonify(
                {"status": "error", "message": "An update is already running. Check status / log."}
            ), 409
        try:
            logf = _launch_update_detached(app_path, itype, force=force)
        except Exception:
            # Never leave the lock behind when the child never started.
            lock.unlink(missing_ok=True)
            raise
        logger.info(f"Web update launched for {app_path} (log: {logf})")
        return jsonify(
            {
                "status": "success",
                "message": (
                    "Update started in background. "
                    "The page/service will restart — check /api/update/status in ~2 min."
                ),
                "data": {"install_type": itype, "path": app_path, "service": service, "log": logf},
            }
        )
    except Exception as e:
        logger.exception(f"update run failed: {e}")
        return jsonify({"status": "error", "message": "Failed to start update"}), 500


# --------------------------------------------------------------------------
# Standalone page (no React rebuild needed) — open /system-update
# --------------------------------------------------------------------------

_UPDATE_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenAlgo · System Update</title>
<style>
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:720px;margin:40px auto;padding:0 16px;background:#0b0e14;color:#e6edf3}
.card{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:20px;margin:16px 0}
button{background:#238636;color:#fff;border:0;border-radius:8px;padding:12px 22px;font-size:16px;cursor:pointer}
button:disabled{background:#555;cursor:not-allowed}
pre{background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:12px;white-space:pre-wrap;max-height:320px;overflow:auto;font-size:12px}
.muted{color:#8b949e}.ok{color:#3fb950}.warn{color:#d29922}
</style></head><body>
<h1>🔄 OpenAlgo System Update</h1>
<p class="muted">Same steps as <code>bash install/update.sh</code>: stop → backup DBs → git pull → deps → migrate_all → restart.</p>
<div class="card"><div id="info">Loading status…</div></div>
<div class="card">
<button id="btn" onclick="runUpdate()">⬇ Update OpenAlgo now</button>
<label style="margin-left:12px;font-size:13px"><input type="checkbox" id="force"> force during market hours</label>
<p class="muted" style="font-size:13px">The service restarts mid-update — this page will disconnect. Reopen <code>/system-update</code> after ~2 min.</p>
</div>
<div class="card"><h3>Updater log (tail)</h3><pre id="log">—</pre></div>
<script>
async function status(){
  const r = await fetch('/api/update/status',{credentials:'same-origin'});
  const j = await r.json();
  if(j.status!=='success'){document.getElementById('info').textContent='Error: '+(j.message||'unknown');return}
  const d=j.data;
  const res = d.update_result ? ('<br><b>Last update:</b> '+d.update_result.state+
    (d.update_result.finished_at?' <span class="muted">'+d.update_result.finished_at+'</span>':'')+
    (d.update_result.summary?'<br><span class="muted">'+d.update_result.summary+'</span>':'')) : '';
  document.getElementById('info').innerHTML =
    '<b>Install:</b> '+d.install_type+' <span class="muted">'+d.path+'</span><br>'+
    '<b>Version:</b> '+d.current+' ('+d.branch+') '+
    (d.behind>0?'<span class="warn"><b>'+d.behind+' commits behind</b></span>':d.behind===0?'<span class="ok">up to date ✓</span>':'<span class="muted">behind: unknown</span>')+'<br>'+
    (d.update_running?'<b class="warn">● update RUNNING…</b>':'<span class="muted">● idle</span>')+res;
  document.getElementById('log').textContent=d.last_log||'—';
  document.getElementById('btn').disabled = d.update_running || d.behind===0;
}
async function runUpdate(){
  if(!confirm('Update OpenAlgo now?\\n\\nTrading/websocket will restart. Avoid 09:00–15:30 IST unless forced.'))return;
  const force=document.getElementById('force').checked;
  // Flask-WTF CSRF: same pattern as the React SPA (api/client.ts) —
  // fetch a token and send it as X-CSRFToken, else the POST 400s with
  // "Security token expired or invalid".
  const ctr=await fetch('/auth/csrf-token',{credentials:'same-origin'});
  const ctj=await ctr.json();
  const r=await fetch('/api/update/run',{method:'POST',credentials:'same-origin',
    headers:{'Content-Type':'application/json','X-CSRFToken':ctj.csrf_token||''},
    body:JSON.stringify({confirm:true,force})});
  const j=await r.json();
  alert((j.status==='success'?'✅ ':'❌ ')+(j.message||JSON.stringify(j)));
  status();
}
status();setInterval(status,10000);
</script></body></html>"""


@system_update_bp.route("/system-update")
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def system_update_page():
    return _UPDATE_PAGE, 200, {"Content-Type": "text/html"}
