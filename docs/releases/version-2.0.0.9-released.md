# Version 2.0.0.9 Released

**Date: 1st May 2026**

**Patch: Manual-Rotation Guidance Hardened — Never Recommend Rotating `API_KEY_PEPPER` on a Populated Database**

This is a **single-commit patch release** on top of v2.0.0.8's Docker upgrade hotfix. The auto-rotation in `utils/env_check.py` already gates `API_KEY_PEPPER` rotation on database state — it only rotates the pepper on a fresh install with no users, because rotating it on a populated DB would invalidate every Argon2 password hash and every Fernet-encrypted broker auth/feed token / TradingView API key, none of which can be recovered. But the **fallback error-path messaging** — printed when the rotation cannot write to `.env` (e.g. read-only mount, permission denied) — was still telling users to manually regenerate *both* values. A user with a populated DB who followed that recipe would brick their deployment. Same problem in the `start.sh` pre-flight banner added in v2.0.0.8. v2.0.0.9 makes the user-facing manual-rotation guidance match the auto-rotation gating.

***

**Highlights**

* **Error path now DB-aware** — `utils/env_check.py` branches the manual-rotation message on `db_populated`. Populated DB → instructs only `APP_KEY` rotation, with an explicit "DO NOT change `API_KEY_PEPPER`" warning and a pointer to `upgrade/rotate_pepper.py`. Fresh DB → both can be safely regenerated.
* **`start.sh` pre-flight banner rewritten** — Default advice is `APP_KEY`-only. A second prominent block warns against regenerating `API_KEY_PEPPER` with the reasoning, and points to `upgrade/rotate_pepper.py` for the controlled path.

***

**Security**

* `b9301b78` — `fix(security): never recommend rotating API_KEY_PEPPER on populated DB`

The auto-rotation logic in `utils/env_check.py:329-412` is correct: on a populated DB, only `APP_KEY` is rotated; `API_KEY_PEPPER` is deliberately left alone because rotating the pepper invalidates:

* Every Argon2 password hash in `database/user_db.py` (one-way, cannot be migrated).
* Every Fernet-encrypted broker auth/feed token in `database/auth_db.py`.
* Every Fernet-encrypted TradingView API key.

But the **fallback error-path** — taken when the rotation can't write `.env.tmp` (read-only mount, EACCES) — printed:

```
Detected publicly-known APP_KEY/API_KEY_PEPPER in .env, but
could not rewrite the file (...).

Generate fresh values manually and paste them into .env:
  python -c "import secrets; print(secrets.token_hex(32))"
```

That advice is safe on a fresh install, fatal on a populated one. Same issue in the `start.sh` pre-flight banner added in v2.0.0.8 — it instructed users to `sed`-replace both `APP_KEY` and `API_KEY_PEPPER`.

Fixes shipped:

* **`utils/env_check.py`** — error message branches on `db_populated`. Populated DB prints `APP_KEY`-only instructions plus an explicit, bold "DO NOT change `API_KEY_PEPPER` on this populated install" warning, with the reasoning and a pointer to `upgrade/rotate_pepper.py` for the controlled rotation path that handles re-encryption + password reset. Fresh DB prints the original "both can be regenerated" guidance.
* **`start.sh`** — pre-flight banner rewritten. Default action is `APP_KEY`-only:
  ```bash
  APP_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
  sed -i "s|^APP_KEY *=.*|APP_KEY = '$APP_KEY'|" .env
  sudo chown 1000:1000 .env
  sudo chmod 600 .env
  ```
  A second prominent banner block — `[OpenAlgo] DO NOT regenerate API_KEY_PEPPER` — explains why and points to the rotate_pepper.py migration. PEPPER rotation is only safe on installs with no users; on any other install, leave it alone and let the auto-rotation's silent fast path take over once `APP_KEY` is no longer compromised.

The `_generate_keys_on_first_run` decision matrix (already documented in `utils/env_check.py:332-345`) is unchanged. v2.0.0.9 only tightens the *user-facing manual-rotation guidance* to mirror the same gating.

**Safe upgrade procedure for users on a populated install hitting the v2.0.0.6 → v2.0.0.8 Docker crash:**

```bash
docker compose down
APP_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
sed -i "s|^APP_KEY *=.*|APP_KEY = '$APP_KEY'|" .env
# Do NOT touch API_KEY_PEPPER on a populated DB.
sudo chown 1000:1000 .env
sudo chmod 600 .env
docker compose up -d
```

After this, `_generate_keys_on_first_run` takes the silent fast path for `APP_KEY` (no longer in `COMPROMISED_APP_KEYS`). The pepper remains in the compromised set, but `db_populated=True` gates the rotation off — only a single warning line, no startup block. Browser sessions need to log in again — by-design, that's how `APP_KEY` rotation prevents anyone with the leaked sample key from forging your sessions.

***

**Contributors**

* **@marketcalls (Rajandran)** — security hardening of manual-rotation guidance; PEPPER-safety review against the populated-DB upgrade path.

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
GET https://docs.openalgo.in/change-log/release/version-2.0.0.9-released.md?ask=<question>
```

The question should be specific, self-contained, and written in natural language.
The response will contain a direct answer to the question and relevant excerpts and sources from the documentation.

Use this mechanism when the answer is not explicitly present in the current page, you need clarification or additional context, or you want to retrieve related documentation sections.
