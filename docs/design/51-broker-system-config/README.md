# 51 - Broker And System Configuration

## Configuration Sources

| Source | Responsibility |
|---|---|
| `.env` | Installation secrets, optional legacy broker keys, public URLs, database paths, rate limits, worker selection and security flags |
| Main database `broker_keys` | Encrypted application keys and optional redirect override for each saved broker |
| Main database `broker_login_states` | Digests of one-use pending broker logins |
| `broker/*/plugin.json` | Broker type, supported exchanges and capability metadata |
| Main settings tables | Analyzer mode, SMTP, notification and application preferences |

`utils/broker_keys.py` owns credential resolution. When `REDIRECT_URL` names a broker and `BROKER_API_KEY` is set, that broker uses its `.env` keys even if database keys exist for it. Saved keys serve every other broker, or every broker when `.env` names none. A pure `.env` installation keeps its existing values. `VALID_BROKERS` gates which brokers can be selected; the tree currently has 38 plugins.

## Broker Pages And APIs

Select Broker (`/broker`), Broker Configuration (`/broker/config`) and Profile's Broker summary follow the OpenAlgo Desktop layout. These pages require app sign-in and work before any broker login.

| Method/path | Behavior |
|---|---|
| `GET /api/broker/list` | Enabled broker cards, fields and setup hints from `utils/broker_setup_guide.py`, exchanges, configured/active state, credential source and masked saved values |
| `PUT /api/broker/credentials/<broker>` | Save only the fields that broker uses; blank key fields preserve existing values |
| `DELETE /api/broker/credentials/<broker>` | Forget database keys; a broker configured in `.env` must be removed from that file instead |
| `POST /auth/broker/login` | Start the chosen broker's login on the server and return its sign-in address |
| `POST /auth/broker/resume` | Validate and join the installation's active broker session from another device |

Broker writes are CSRF-protected, limited to 20 per minute, and run under the same commit guard as broker-token writes. Redirect overrides must be full HTTP(S) addresses ending in `/<broker>/callback`. An empty override selects the automatic address derived from `HOST_SERVER`; saved automatic addresses follow later host changes.

Saving the `.env` broker writes the supplied values to `.env`; saving another broker encrypts them in the database. Neither path asks for a restart to apply broker keys. Replacing keys for the active broker or forgetting it requires `sign_out=true` and ends that broker session while retaining this browser's app sign-in. A login currently using those keys blocks a save or delete. Live automation can block any change that would end the active broker session; see [Login And Broker Flow](../03-login-broker-flow/).

Responses have `Cache-Control: no-store`. The current implementation returns API-key/market-key prefixes (up to six characters) followed by a fixed eight-character mask, and an all-mask value for secrets; it does not return raw lengths or full saved credentials. Empty values return no saved mask. A UI must not infer a secret's length from that mask.

## Login And Request Isolation

Only one broker is active for the installation. Starting a login does not change the process's active keys or sign out the old broker. Pending logins are one-use, expire after ten minutes, and store only nonce/state digests server-side. The callback must belong to the browser/state that started it.

At callback or resume, keys are staged for that request with a `ContextVar` overlay on `os.environ`. Other requests keep the active broker's keys. Token reads also pin the matching keys for the rest of their request. `handle_auth_success` rechecks revocation, key changes and switch eligibility under `auth_commit_guard` immediately before storing the token, and publishes keys only as part of a successful commit. Teardown clears staging/pins so a reused thread or greenlet cannot inherit them. Startup and the separate WebSocket proxy publish the active broker's keys in their own processes.

Broker plugins must read keys when called, never into module-level constants. Threads started inside a login do not inherit its staged context.

## Server Settings And Capabilities

`GET/POST /api/broker/credentials` now belongs to Profile's **server settings**: ngrok, `HOST_SERVER`, `WEBSOCKET_URL`, enabled brokers and listener status. POST writes only supplied server settings to `.env` and returns `restart_required: true`. It does not save broker application keys.

`GET /api/broker/capabilities` requires a valid broker session and resolves that session's cached plugin metadata. A missing record falls back to an `IN_stock` object with no exchanges. Broker discovery before login uses `/api/broker/list`; the removed `/auth/broker-config` is not a supported contract.

## Secret Storage And Recovery

Saved broker fields use the auth database Fernet key derived from `API_KEY_PEPPER` and `FERNET_SALT`. Authenticated plaintext binds each value to its broker and field, so moving ciphertext to another row or column is rejected. Both rotation paths (`utils/env_check.py` and `upgrade/rotate_pepper.py`) include the encrypted broker-key columns.

Back up `.env` together with `db/`: a database copy without its original installation secrets cannot recover saved broker keys or tokens. Adding a new encrypted field requires updating both rotation lists and providing an upgrade migration.

## Key Files

| File | Purpose |
|---|---|
| `blueprints/broker_config.py` | Broker list, save and forget APIs |
| `blueprints/broker_credentials.py` | Server settings and active-broker capabilities |
| `database/broker_keys_db.py` | Encrypted saved keys and pending-login records |
| `utils/broker_keys.py` | `.env` precedence, staging/pinning and process publication |
| `utils/broker_login.py`, `utils/broker_switch.py` | Started-login verification and switch safety |
| `utils/auth_utils.py`, `database/auth_db.py` | Token commit fence and session handover |
| `frontend/src/pages/BrokerSelect.tsx`, `frontend/src/pages/BrokerConfig.tsx` | Broker pages |
