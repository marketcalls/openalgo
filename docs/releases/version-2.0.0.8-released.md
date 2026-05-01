# Version 2.0.0.8 Released

**Date: 1st May 2026**

**GTT Orders for Zerodha & Dhan, Telegram `/StopPython` Command, Historify Parquet Aggregation Fix, Codebase-Wide bare-except Sweep & Critical Docker Upgrade Hotfix**

This release covers **6 commits** since v2.0.0.7. The headline addition is end-to-end GTT (Good Till Triggered) order support for Zerodha and Dhan via four new endpoints — `placegttorder`, `modifygttorder`, `cancelgttorder`, `gttorderbook` — currently in pilot, with rollout to the remaining supported brokers planned for upcoming releases. Alongside the feature work, this release ships a **critical hotfix for Docker upgrades from v2.0.0.5 and earlier**: the auto-rotation of publicly-known sample `APP_KEY` introduced in v2.0.0.6 was crashing the gunicorn worker under Docker because the `.env` mount was read-only and the rotation could not write its atomic temp file. Any pre-v2.0.0.6 Docker install that left the sample keys in `.env` was hitting a restart loop on upgrade.

***

**Highlights**

* **GTT Order Implementation (Zerodha + Dhan)** — Pilot rollout of `/api/v1/placegttorder`, `/api/v1/modifygttorder`, `/api/v1/cancelgttorder`, `/api/v1/gttorderbook`. Database migration is mandatory on upgrade. Rollout to all other supported brokers is planned. (#1322)
* **Telegram `/StopPython` command + `/closeall` enhancement** — Lists running Python strategies inline; new **Close all + Stop strategies** button on `/closeall` flattens positions and stops every running strategy in one flow. (#1231)
* **Historify Parquet export now aggregates computed intervals** — Selecting `Parquet` with `5m` / `15m` / `30m` / `1h` / `W` / `M` / `Q` / `Y` no longer silently downgrades to ZIP. The exporter now uses the same DuckDB time-bucket / daily-aggregation logic the ZIP path has used. (#917)
* **Codebase-wide bare-except sweep** — 82 `except:` clauses across 45 files replaced with `except Exception:` (#1039). Restores correct shutdown-signal handling under Gunicorn / Docker / systemd; aligns with PEP 8 / Ruff `E722`.
* **🔴 Critical: Docker `.env` `:ro` mount removed; `APP_KEY` auto-rotation no longer crashes legacy Docker installs.** Affects every Docker user upgrading from v2.0.0.5 or earlier.

***

**Trading APIs**

**GTT Orders (#1322)**

* `ce0e4d59` — `Feat : Gtt Order Implementation. Updated for Dhan and Zerodha`

Pilot APIs (currently Zerodha + Dhan; other brokers to follow):

* `POST /api/v1/placegttorder` — place a GTT trigger.
* `POST /api/v1/modifygttorder` — modify trigger / leg parameters.
* `POST /api/v1/cancelgttorder` — cancel an active GTT.
* `POST /api/v1/gttorderbook` — list active triggers.

Schema highlights: flat place/modify body with `triggerprice_sl` and `triggerprice_tg`, `MIS` rejected, `last_price` fetched server-side; Dhan SINGLE/OCO mapping with per-leg modify; Zerodha `MARKET` pricetype auto-converted to MPP-protected `LIMIT` (Kite GTTs cannot carry MARKET).

⚠️ **Database migration is mandatory on upgrade.** Run before starting the new build:

```bash
uv run python upgrade/migrate_all.py
# or, just for the GTT tables:
uv run python upgrade/migrate_gtt.py
```

Adds `sandbox_gtt` and `sandbox_gtt_legs` tables and defaults. Sandbox / analyze-mode GTT execution is Phase 3 — analyze mode currently returns `501` for GTT calls until the in-progress sandbox integration ships.

API docs: <https://docs.openalgo.in/api-documentation/v1/orders-api/placegttorder>

***

**Telegram Bot (#1231)**

* `53334a0c` — `feat(telegram): add /stoppython and "Close all + Stop strategies" action`

New `/stoppython` command snapshots `RUNNING_STRATEGIES` from `blueprints/python_strategy.py` and renders one inline button per running strategy plus a **Stop All** button and **Cancel**. Per-strategy and bulk actions both prompt for confirmation before terminating, then call `stop_strategy_process()` — the same code path the UI's Stop button uses (`SIGTERM` → `SIGKILL` on Linux/Mac, `taskkill /F /T` on Windows). The strategy-id ↔ button-index map is held in `context.user_data["stoppy_list"]` so `callback_data` stays under Telegram's 64-byte cap regardless of how long strategy IDs get. If nothing is running, the bot replies `ℹ️ No Python strategies running.` and exits cleanly.

`/closeall` confirmation now offers a third button:

| Button | Action |
|--------|--------|
| ✅ Yes, close all | (existing) flattens every open position via `closeposition`. |
| ⚠️ Close all + Stop strategies | Closes all positions, then iterates `RUNNING_STRATEGIES` and terminates each via `stop_strategy_process()`. Reports a combined summary (positions closed, strategies stopped, failures). |
| ❌ Cancel | No-op. |

Help text updated; `docs/design/43-telegram-bot/README.md` brought back in sync with the actually-registered command names (`/orderbook`, `/tradebook`, `/chart`, `/mode`, `/menu`, `/link`, `/unlink`).

***

**Historify (#917)**

* `ee89cf8b` — `fix(historify): aggregate computed intervals in Parquet export`

`export_to_parquet()` previously ran a direct `WHERE interval = ?` query against `market_data`, which returns zero rows for any non-storage interval (only `1m` and `D` are physically stored — `5m / 15m / 30m / 1h`, custom intraday like `25m / 2h`, and `W / M / Q / Y` are aggregated on the fly). To prevent empty downloads, the historify bulk-export blueprint silently overrode the user's Parquet selection to ZIP whenever any computed interval was requested — so picking *Parquet + 5m* produced a `.zip` of CSVs.

`export_to_parquet()` now mirrors `export_to_zip()`'s three-branch interval handling:

| Interval kind | Source | Method |
|---|---|---|
| `1m`, `D` (storage) | direct read | unchanged |
| `5m` / `15m` / `30m` / `1h`, custom intraday (`25m`, `2h`, …) | aggregate from `1m` | DuckDB time-bucket SQL — same query as the ZIP path |
| `W` / `M` / `Q` / `Y`, multi-D | aggregate from `D` | reuses the existing `_get_daily_aggregated_ohlcv()` |

All symbols' rows go into a single Parquet file with the original schema preserved (`symbol, exchange, interval, timestamp, open, high, low, close, volume, oi, datetime`). Skipped symbols (missing source data) are surfaced in the response message rather than silently dropped. Compression codec (`zstd` / `snappy` / `gzip` / `none`) is honored as before.

The blueprint's silent ZIP override now applies only to multi-interval requests (legitimate — single-table formats can't carry per-interval files) and to single-computed CSV/TXT requests (those exporters still use direct queries and need the same treatment in a follow-up).

***

**Code Quality / Stability (#1039)**

* `b6419a90` — `fix: replace bare except clauses with except Exception across codebase`

82 occurrences across 45 production files in `blueprints/`, `broker/` (all 30+ broker integrations), `database/`, `sandbox/`, `services/`, `test/`, `utils/`, and `websocket_proxy/`. Bare `except:` swallows `BaseException`, including `SystemExit` and `KeyboardInterrupt` — meaning `Ctrl+C`, `SIGTERM` from Docker / systemd, and other shutdown signals could be silently absorbed mid-iteration in long-running loops (websocket adapters, Telegram polling, sandbox engine).

Practical effects:

* Cleaner shutdown under Gunicorn / Docker / systemd — `SIGTERM` propagates correctly.
* `MemoryError` and other `BaseException` subclasses now propagate as expected.
* `database/historify_db.py:_safe_timestamp()` additionally upgraded with `logger.warning` so timestamp conversion failures land in `log/errors.jsonl` instead of disappearing silently.
* Ruff `E722` / Flake8 `E722` no longer fire across the codebase, making future CI lint enforcement viable.

No behaviour change for ordinary exception flows — call sites still catch `Exception` and below, exactly as before.

***

**Security / Docker (Critical)**

* `245403f1` — `fix(security/docker): unblock APP_KEY/PEPPER auto-rotation under Docker (v2.0.0.8)`

v2.0.0.6 introduced an auto-rotation in `utils/env_check.py` that detects the publicly-known sample `APP_KEY` / `API_KEY_PEPPER` (which shipped in `.sample.env` up to v2.0.0.5, and which `install-docker.sh` did not rewrite until commit `0162ce3a5`) and replaces them with fresh secrets on first run. Under Docker, the rotation crashed the gunicorn worker:

```
[OpenAlgo security]
Detected publicly-known APP_KEY/API_KEY_PEPPER in .env, but
could not rewrite the file
([Errno 13] Permission denied: '/app/utils/../.env.tmp').
```

Two compounding causes:

1. `docker-compose.yaml` and the install-script compose templates mounted `.env` **read-only** (`./.env:/app/.env:ro`), so the rotation's atomic `.env.tmp` write failed with `EACCES` and `sys.exit(1)` killed the worker — gunicorn restart loop, container hard-down.
2. `install-docker.sh` and `install-docker-multi-custom-ssl.sh` kept `.env` at `chmod 644` owned by host root because the previous `:ro` mount made `chmod 600` + root ownership unreadable to the container's `appuser` (UID 1000) — see issue #960. With `:ro` removed, that workaround flipped into a problem: `appuser` still couldn't *write* a root-owned file even if the mount allowed it.

This affected every Docker user who installed before v2.0.0.6 and pulled the v2.0.0.6+ image — a meaningful slice of the existing Docker install base.

Fixes shipped:

* **Drop `:ro`** from every `.env` mount so the rotation can write its temp file. Touched: `docker-compose.yaml`, `install/install-docker.sh` (compose template), `install/install-docker-multi-custom-ssl.sh` (compose template), `install/docker-run.sh`, `install/docker-run.bat`, `docker-build.sh`.
* **`chown 1000:1000 .env && chmod 600 .env`** in `install/install-docker.sh`, `install/install-docker-multi-custom-ssl.sh`, `install/docker-run.sh` (with Linux/Mac branching). Tighter than the previous mode 644 *and* Docker-compatible at the same time — only `appuser` (UID 1000) on the host can read/write, instead of "anyone with read access to the install dir."
* **`start.sh` pre-flight check** before gunicorn launches. If `APP_KEY` / `API_KEY_PEPPER` is in the publicly-known compromised set AND `.env` is not writable from inside the container, prints an unmissable banner with the safe recovery recipe and exits cleanly. Replaces the buried "Permission denied" stack trace with an actionable error.

**Migration for users who hit the crash on Docker:**

```bash
cd /path/to/openalgo
docker compose down
git pull
docker compose pull

# Generate a fresh APP_KEY only — do NOT touch API_KEY_PEPPER on a populated install
APP_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
sed -i "s|^APP_KEY *=.*|APP_KEY = '$APP_KEY'|" .env

# Make .env writable by the container's appuser (UID 1000)
sudo chown 1000:1000 .env
sudo chmod 600 .env

docker compose up -d
```

⚠️ **Do NOT manually rotate `API_KEY_PEPPER` on a populated install.** The auto-rotation in `utils/env_check.py` deliberately declines to touch the pepper when the database has users — rotating it would invalidate every Argon2 password hash and every Fernet-encrypted broker auth/feed token / TradingView API key, none of which can be recovered. If you genuinely need to rotate the pepper (rare), use the dedicated migration which handles re-encryption and the required password reset:

```bash
uv run python upgrade/rotate_pepper.py
```

After applying the APP_KEY-only migration, `_generate_keys_on_first_run` takes the silent fast path (APP_KEY no longer in `COMPROMISED_APP_KEYS`) and the container boots cleanly. Browser sessions need to log in again — by design, that's how APP_KEY rotation prevents anyone with the leaked sample key from forging your sessions.

***

**Contributors**

* **@marketcalls (Rajandran)** — release management, GTT order implementation for Zerodha and Dhan (#1322), Telegram `/stoppython` command + `/closeall` enhancement (#1231), Historify Parquet aggregation fix (#917), codebase-wide bare-except sweep (#1039), critical Docker `.env` `:ro` hotfix.

***

**Links**

* **Repository**: <https://github.com/marketcalls/openalgo>
* **Documentation**: <https://docs.openalgo.in>
* **Discord**: <https://www.openalgo.in/discord>
* **YouTube**: <https://www.youtube.com/@openalgo>
* **Issue tracker**: <https://github.com/marketcalls/openalgo/issues>

***


---

# Agent Instructions: Querying This Documentation

If you need additional information that is not directly available in this page, you can query the documentation dynamically by asking a question.

Perform an HTTP GET request on the current page URL with the `ask` query parameter:

```
GET https://docs.openalgo.in/change-log/release/version-2.0.0.8-released.md?ask=<question>
```

The question should be specific, self-contained, and written in natural language.
The response will contain a direct answer to the question and relevant excerpts and sources from the documentation.

Use this mechanism when the answer is not explicitly present in the current page, you need clarification or additional context, or you want to retrieve related documentation sections.
