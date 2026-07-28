# 30 - Upgrade Procedure

## Supported Update Path

Use `install/update.sh` for an existing native/server installation or a local checkout. The script detects the current deployment layout and branch; do not replace it with ad hoc database initialization commands.

```bash
cd /path/to/openalgo
bash install/update.sh
```

For Docker deployments, use the update procedure that belongs to the installed Compose layout. Preserve the bind-mounted `.env` and `db/` volume.

## What The Native Script Does

`install/update.sh` performs seven phases:

1. Stop the systemd service for a detected server deployment.
2. Copy known database files into `db/backup_<timestamp>/`.
3. Stash tracked local modifications and pull the current Git branch.
4. Compare `.env` with `.sample.env`, preserve existing secrets, and harden older installs.
5. Update Python dependencies with `uv` and ensure Gunicorn/eventlet for server mode.
6. Fix server permissions and run `upgrade/migrate_all.py`.
7. Restart systemd/nginx, or finish local development setup.

The migration runner executes an ordered, idempotent list of targeted scripts. Database modules also use idempotent table initialization during application startup. OpenAlgo does not expose a `database.init_all_databases()` helper.

## Backup Requirements

Before an upgrade, back up `.env`, signing keys, strategy files, and all six configured stores:

```text
db/openalgo.db
db/logs.db
db/latency.db
db/health.db
db/sandbox.db
db/historify.duckdb
```

The current updater's automatic loop copies `openalgo.db`, `logs.db`, `latency.db`, `sandbox.db`, and `historify.duckdb`; it does not include `health.db`. Copy `health.db` separately when retaining health history matters. This limitation should remain explicit until the updater is changed.

## Environment Review

The updater keeps an existing `.env` and reports names that are present in `.sample.env` but missing locally. Review those values after every upgrade. Never replace production `APP_KEY`, `API_KEY_PEPPER`, `FERNET_SALT`, OAuth signing keys, or broker credentials with sample placeholders.

If no `.env` exists, the script creates one from `.sample.env` and generates fresh `APP_KEY` and `API_KEY_PEPPER` values. That is recovery behavior, not a way to rotate secrets on an existing installation.

## Frontend Build

Local mode builds the React bundle only when `frontend/dist` is absent and npm is available. Server operators should verify the bundle after frontend changes and build explicitly when needed:

```bash
cd frontend
npm ci
npm run build
```

Then restart the application service.

## Migration Runner

Run the migration set directly only when diagnosing or completing an interrupted update:

```bash
uv run upgrade/migrate_all.py
```

The runner continues past scripts that report warnings and summarizes failures. Inspect its complete output rather than treating the final line alone as proof that every migration applied.

`upgrade/rotate_pepper.py` is deliberately excluded from automatic migration because rotating `API_KEY_PEPPER` has authentication and ciphertext consequences. It is an explicit operator action.

## Verification

After updating:

1. Confirm the systemd/container process is healthy.
2. Open `/auth/app-info` and verify the expected application version.
3. Sign in, reconnect the broker if needed, and confirm master-contract readiness.
4. Exercise a read-only API call and a WebSocket authentication/subscription in the intended mode.
5. Review `log/errors.jsonl`, service logs, and migration output.
6. Confirm the React bundle loads without stale-chunk errors.

Swagger UI is disabled; `/api/docs` is not a verification endpoint. Use [`docs/api`](../../api/README.md) for maintained request contracts.

## Rollback

Stop the service, restore the exact pre-upgrade Git revision and the matching backup files, restore `.env`/keys if they changed, reinstall dependencies for that revision, and restart. Do not restore one database selectively when a migration changed related state across stores.

Local changes stashed by the updater are not restored automatically. Review `git stash list` and apply them deliberately after the upgraded tree is stable.
