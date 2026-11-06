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
| Server | `/var/python/openalgo` is a git checkout | Detached `install/update_web.sh` → `install/update.sh` (stop, backup, pull, sync, migrate, start) |
| Docker | `/.dockerenv` exists | Writes `/app/tmp/update_requested.json`; the host watcher pulls, rebuilds and recreates the container |
| Local | any other checkout | Same backup → pull → sync → migrate sequence, no service restart |

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

1. validates the request and the IST market-hours guard (`force` bypasses it),
2. deletes `/app/tmp/update_requested.json` so a click cannot run twice,
3. `git pull` (the branch's configured upstream — forks are fine),
4. `docker compose build` with `GIT_SHA`/`GIT_BRANCH`/`GIT_REMOTE` build args,
5. `docker compose up -d`,
6. writes `/app/tmp/update_result.json` for the status page.

## Server: sudoers

`update_web.sh` runs `install/update.sh`, which needs to stop/start the systemd
unit. Let the web user run only that script without a password:

```sudoers
# /etc/sudoers.d/openalgo-update
openalgo ALL=(root) NOPASSWD: /bin/bash /var/python/openalgo/install/update_web.sh
```

Keep the rule scoped to that path; do not grant blanket `NOPASSWD: ALL`.

## Safety rails

- **Market hours:** 09:00–15:30 IST is refused unless `force` is checked. The
  check runs in the route, again in `update_web.sh` and again in the host
  watcher, because a restart during live trading is the expensive failure.
- **One at a time:** `/tmp/openalgo_update.lock` (server/local) and the request
  flag (Docker) reject a second run with `409`.
- **Backups first:** `db/*.db` and `db/*.duckdb` are copied to
  `db/backup_<timestamp>/` before anything is pulled.
- **No secrets in responses:** only git SHAs, install paths and the updater log
  tail are returned.

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
| Server layout, `sudo` denied | Add the scoped sudoers rule above |
