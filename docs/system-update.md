# System update from the web UI

`/system-update` updates OpenAlgo from the browser instead of an SSH session:
version check, backup, pull, dependency sync, migrations and restart, with a
market-hours guard.

```text
GET  /api/update/status   -> install type, current SHA, branch, commits behind,
                             running/idle, last result, updater log tail
POST /api/update/run      -> {"confirm": true, "force": false}
GET  /system-update       -> standalone page (linked as "System Update")
```

Every route requires a logged-in session. `POST` also needs the Flask-WTF
`X-CSRFToken` header, which the page fetches from `/auth/csrf-token` first.

## Install layouts

| Layout | Detected by | What a click does |
|---|---|---|
| Server | `/var/python/openalgo` is a git checkout with a systemd unit `openalgo` | Detached updater: stop service, back up `db/*`, pull, sync deps, migrate, start service |
| Docker | `/.dockerenv` exists | Writes `/app/tmp/update_requested.json`; the host watcher pulls, rebuilds and recreates the container |
| Local | any other checkout | Same sequence with **no sudo and no service restart** (and no compose side effect unless this checkout's own compose services are actually running) |

Named volumes (`openalgo_db`, `openalgo_log`, `openalgo_keys`,
`openalgo_strategies`) are reattached on recreate, so a Docker update keeps
databases, keys, strategies and logs.

## Docker: host watcher

A container cannot rebuild its own image, so the click is fulfilled on the host.
Install the watcher in the crontab of the user that owns the checkout and can
run `docker`:

```cron
* * * * * flock -n /tmp/openalgo_host_update.lock /path/to/openalgo/install/host_update_watcher.sh >> /path/to/openalgo/log/host_watcher.log 2>&1
```

The script is quiet when nothing is requested. Otherwise it:

1. validates the request JSON (any well-formed file with a boolean `force`
   field),
2. enforces the IST market-hours guard (`force` bypasses it),
3. writes a `{"state": "running"}` result **before** deleting the request
   flag, so the web UI answers `409` for the whole rebuild window,
4. `git pull` (the branch's configured upstream — forks are fine),
5. `docker compose build` with `GIT_SHA`/`GIT_BRANCH`/`GIT_REMOTE` build args
   (userinfo is stripped from the remote URL first),
6. `docker compose up -d`, checking the exit code,
7. polls `docker inspect` until the container reports `running`/`healthy`
   (60 s cap),
8. writes `/app/tmp/update_result.json` with `done` or `error`.

Both `install/install-docker.sh` and `install-docker-multi-custom-ssl.sh`
write a compose file that passes the `GIT_*` build args, so installer-based
Docker deployments get real version stamps too.

## Server: sudoers (read this before enabling)

The installer makes the **web user own the whole checkout**
(`chown -R $WEB_USER $OPENALGO_PATH`), so a sudoers rule that lets the web user
run a script *inside* the checkout as root is a web-user-to-root escalation:
edit the script, run it passwordless, get root.

Therefore grant NOPASSWD only on a **root-owned copy of the updater installed
outside the checkout**, with the app path pinned as its argument:

```bash
sudo install -o root -g root -m 0755 install/update_web.sh /usr/local/sbin/openalgo-update
```

```sudoers
# /etc/sudoers.d/openalgo-update
www-data ALL=(root) NOPASSWD: /bin/bash /usr/local/sbin/openalgo-update /var/python/openalgo
```

Use the actual web user from `install/install.sh` (`www-data`, `nginx` or
`http`, depending on the distro). The blueprint prefers this wrapper when it
exists. When the wrapper runs as root it executes every checkout-touching
step (`git`, `cp`, `uv`, migrations) as the checkout's owner via `sudo -u`,
and uses root only for `systemctl stop/start openalgo` — so no web-writable
file is ever executed as root. Keep the wrapper root-owned and do not grant
anything else to the web user.

If the wrapper is not installed, the blueprint falls back to
`sudo /bin/bash <checkout>/install/update_web.sh` — convenient for testing,
but do not leave that configuration in place on an internet-facing server.

Local checkouts need no sudoers entry at all: the blueprint runs the in-tree
script directly as the current user.

## Safety rails

- **Market hours:** 09:00–15:30 IST is refused unless `force` is checked. The
  check runs in the route, again in `update_web.sh` (the route passes
  `WEB_UPDATE_FORCE=1` only for a confirmed forced run) and again in the host
  watcher, because a restart during live trading is the expensive failure.
- **One at a time:** the lock file / docker request flag is claimed with
  `O_CREAT|O_EXCL`, so two POSTs in the same instant cannot both pass; a
  persisted `{"state": "running"}` result also answers `409`. Concurrent runs
  get `409`, not a double update.
- **Backups first (server/local):** if `db/*.db` or `db/*.duckdb` exist, the
  copy must succeed or the update aborts — a failed backup never leads to a
  pull. (Docker installs rely on the named `openalgo_db` volume surviving the
  recreate instead; the watcher does not copy database files.)
- **Failures are loud:** both scripts run with `pipefail`, so a failed pull,
  dependency sync, migration, build or `compose up -d` aborts with a non-zero
  exit and an `error` result instead of reporting success.
- **No secrets in responses or logs:** only git SHAs, paths and the updater
  log tail are returned, and `user:pass@` userinfo is stripped from the remote
  URL before it is baked into the image or logged.

## Version display

The image has no `.git` and no `git` binary, so the Docker build bakes
`GIT_SHA`, `GIT_BRANCH` and `GIT_REMOTE` into `/app/BUILD_*` (see `Dockerfile`
and `docker-compose.yaml`). The behind-count comes from the GitHub compare API,
cached for 30 minutes per `(repo, SHA, branch)`: unauthenticated GitHub allows
60 requests/hour per IP, and the page refreshes every 10 seconds. When the API
is unreachable or rate-limited the page shows `behind: unknown` and keeps
working.

## Troubleshooting

| Symptom | Check |
|---|---|
| `Security token expired or invalid` | Hard-refresh `/system-update`; the page needs a fresh `X-CSRFToken` from `/auth/csrf-token` |
| `behind: unknown` | GitHub rate limit (wait for the reset) or a non-GitHub `origin` |
| Click says "requested" but nothing happens | `crontab -l` for the watcher, then `log/host_watcher.log` |
| `Updater script missing` | `install/update_web.sh` is not next to `app.py` |
| Server layout, `sudo` denied | Install the root-owned wrapper and use the scoped sudoers rule above |
| Update reported `error` | `log/update_web.log` (server/local) or `log/host_watcher.log` + `/app/tmp/update_result.json` (Docker) |
