# Weekly upgrade routine (Sunday 6:00 AM IST)

Sources: `upgrade/README.md`, `docs/design/30-upgrade-procedure/README.md`,
`CLAUDE.md` (Frontend build, schema migrations), `.sample.env` header.

The supported updater, `install/update.sh`, stops a systemd service, uses `sudo`,
may install a browser package, and stashes local changes. The box has none of
that layout, so the routine follows the same seven phases by hand. Sunday 6:00 AM
IST is outside market hours, and the daily login routine (Indian brokers) runs at
7:00 AM afterwards. The upgrade restarts only the OpenAlgo process, never the box,
and never logs in to the broker: the daily routine does that.

## Steps

```bash
set -euo pipefail
cd /workspace/repos/openalgo
TS=$(date +%Y%m%d_%H%M%S)
```

0. **Re-read the procedure.** Read `CLAUDE.md`, `upgrade/README.md` and
   `docs/design/30-upgrade-procedure/README.md` on the current checkout and on
   `origin/main` after fetching (`git fetch origin && git diff HEAD origin/main --
   CLAUDE.md upgrade/README.md docs/design/30-upgrade-procedure/README.md`). If
   the procedure changed, follow the new one and say so in the report.
1. **Pre-flight.** `git status --porcelain` must show nothing tracked as modified
   and the branch must be `main`. If not, stop and report: never stash, reset or
   discard the user's work in a routine. Record `PREV=$(git rev-parse HEAD)` and
   the version from `/auth/app-info`.
2. **Stop the app.** `pkill -f "script -qfec uv run app.py"; pkill -f
   "openalgo/.venv/bin/python app.py"`, then wait until port 5000 is free.
   SQLite runs in WAL mode and Historify (DuckDB) allows one writer, so copy only
   when stopped.
3. **Back up.** `.env` and all six stores:
   ```bash
   B=db/backup_$TS; mkdir -p "$B"; chmod 700 "$B"
   cp -p .env "$B/.env"; chmod 600 "$B/.env"
   for f in openalgo.db logs.db latency.db health.db sandbox.db historify.duckdb; do
     [ -f db/$f ] && cp -p db/$f "$B/"
   done
   echo "$PREV" > "$B/PREV_COMMIT"
   ```
   (`health.db` is copied on purpose; the upstream updater's loop misses it.)
4. **Pull.** `git pull --ff-only origin main`. If nothing changed, skip to step 8
   and report "already up to date".
5. **Dependencies.** `uv sync --locked`.
6. **Migrations.** `cd upgrade && uv run migrate_all.py; cd ..`. A non-zero exit
   means do not start the new code: roll back.
7. **Merge new settings.** Compare `ENV_CONFIG_VERSION` in `.env` and
   `.sample.env`. Append to `.env` every key present in `.sample.env` but missing
   from `.env`, with its sample value and comment. Never overwrite an existing key,
   and never touch `APP_KEY`, `API_KEY_PEPPER`, `FERNET_SALT` or the broker
   fields. Update `ENV_CONFIG_VERSION` in `.env` last. Report the names of keys
   added, not their values.
8. **Restart.** `nohup setsid script -qfec "uv run app.py" app.log >/dev/null 2>&1 &`,
   wait for `/auth/app-info`, check ports 5000 and 8765.
9. **No broker login.** Leave the broker disconnected; the 7:00 AM daily
   routine connects it ([login-routines.md](login-routines.md)).
10. **Verify** (from the upgrade procedure doc, without a broker session): new
    version in `/auth/app-info`, ports 5000 and 8765 listening, migrations exited
    0, no new entries in `log/errors.jsonl`, and the UI loads without
    stale-chunk errors. The ping and quote checks run after the daily login.
11. **Companion packages.** `cd /workspace/pyenv && uv lock --upgrade-package
    openalgo && uv sync`, and `cd /workspace/openalgo-charts-npm && npm update
    openalgo-charts`. Report old and new versions.

## Rollback (any failure after step 3)

```bash
pkill -f "script -qfec uv run app.py" || true
pkill -f "openalgo/.venv/bin/python app.py" || true
git reset --hard "$PREV"   # only on main, after the clean check in step 1 passed
uv sync --locked
cp -p "$B"/*.db "$B"/historify.duckdb db/ 2>/dev/null || true
cp -p "$B/.env" .env
nohup setsid script -qfec "uv run app.py" app.log >/dev/null 2>&1 &
```

Restore all stores together, never one selectively (the upgrade doc warns that a
migration can change related state across stores). The reset is safe here only
because step 1 refused to run on a dirty tree or another branch; if that check
was skipped, stop and ask instead. Do not log in; report the exact error from
the failed step and that the rollback completed.

## Routine prompt template

```
Weekly OpenAlgo upgrade, Sunday 6:00 AM IST, on the box at /workspace/repos/openalgo.

Follow .claude/skills/grokbot-setup/references/weekly-upgrade.md step by step,
after first re-reading CLAUDE.md, upgrade/README.md and
docs/design/30-upgrade-procedure/README.md for any change to the procedure.
Stop and report without changing anything if the tree is dirty or not on main.
Back up .env and all six db stores before pulling. Never change APP_KEY,
API_KEY_PEPPER, FERNET_SALT or broker credentials. Restart only the app, never
the box. On any failure after the backup, roll back to the previous commit and
backup and restart the app. Never log in to the broker; the 7:00 AM daily
routine does that.

Report to the user in a few lines: old and new OpenAlgo version, number of new
commits, new .env keys added (names only), migrations result, SDK and
openalgo-charts versions. On failure: the step, the exact
error, and confirmation that the rollback completed.
```
