# Auth, login callback, and platform wiring

Login is trust-critical and blocks everything else — no token means no master
contract, no quotes, no orders. Build it first.

## The `authenticate_broker` contract

1. **Function name MUST be `authenticate_broker`** — hardcoded in
   `utils/plugin_loader.py` (`getattr(module, "authenticate_broker")`).
2. **Returns a 2-tuple `(auth_token, error)`** — success = `(token, None)`,
   failure = `(None, error)`. Unpacked in `blueprints/brlogin.py`.
3. Read creds from env via `os.getenv("BROKER_API_KEY")` / `BROKER_API_SECRET`.
4. **Use the shared pooled HTTP client** `utils/httpx_client.get_httpx_client()`.

### NUANCE — the arity is NOT fixed at one argument

The commonly repeated "one positional arg" rule only holds for the OAuth
families. Real signatures in the tree:

```python
# OAuth / checksum redirect — one arg
def authenticate_broker(request_token):              # zerodha, arrow, fyers
def authenticate_broker(code):                       # dhan, upstox

# Direct login — the user's credentials come from a form, not a redirect
def authenticate_broker(clientcode, broker_pin, totp_code):   # angel  (3 required)
def authenticate_broker(code, password=None, totp_code=None): # flattrade (hybrid)
```

Your `brlogin.py` branch is what supplies the extra arguments, so the signature
and the branch must be designed together. A TOTP broker needs a form POST route,
not just a callback.

### NUANCE — the error half of the tuple is not always a string

`broker/fyers/api/auth_api.py` is typed
`-> tuple[str | None, dict[str, Any] | None]` — it returns a **dict** for the
error. `handle_auth_failure` accepts both. Do not assume you can string-format
the second element.

### NUANCE — literal JSON field names (docs describe, servers validate)

Broker docs often *describe* auth fields without giving the literal JSON keys,
and casing matters. Arrow's token exchange requires exactly `appID`, `token`
(the request token) and `checkSum` (capital S) — sending `requestToken` /
`checksum` failed every login with "required validation for field token
failed". Two rules:

- Find a **verbatim request example** (docs curl block or the official SDK
  source) before writing the payload. Never infer key spelling from prose.
- Server error messages name the **server-side validator field**, which may
  differ from the request key (Arrow's margin API complains about
  `tradingSymbol` when the request field is actually `symbol`). Don't rename
  your request field to match the error string — find the real contract.

### NUANCE — `BROKER_API_KEY` is frequently a `:::`-joined composite

Eight brokers pack multiple credentials into the single `BROKER_API_KEY` env
var, and **the field order differs per broker**. Getting this backwards yields
confusing auth failures rather than a clear error:

| Broker | Format |
| --- | --- |
| dhan, dhan_sandbox | `client_id:::api_key` |
| shoonya, tradesmart, zebu | `userid:::client_id` |
| definedge | `api_key:::user_id:::client_id` (three parts) |
| flattrade | `<something>:::api_key` — index `[1]` is the key |
| kotak | `<something>:::client_id` — index `[1]` is the OAuth client id |
| fivepaisa | composite, see `broker/fivepaisa/api/auth_api.py` |

Always guard with `if ":::" in BROKER_API_KEY:` and emit an explicit error
message naming the expected format (see `broker/tradesmart`:
`"BROKER_API_KEY must be in format userid:::client_id"`).

XTS-family brokers additionally use `BROKER_API_KEY_MARKET` /
`BROKER_API_SECRET_MARKET` for the separate market-data session.

## Wiring the callback in `blueprints/brlogin.py`

`brlogin.py` is a ~1167-line dispatcher with a branch for roughly every broker.
The generic fallback is only:

```python
else:
    code = request.args.get("code") or request.args.get("request_token")
    auth_token, error_message = auth_function(code)
    forward_url = "broker.html"
```

**Expect to add a branch.** The generic path only works if the broker returns
its token as exactly `code` or `request_token`. Real spellings in the tree:
`auth_code` (fyers), `request-token` with a HYPHEN (arrow), `code` plus a
separate `client` param (flattrade). A differently spelled param is **silently
dropped** — you get a `None` code and a login failure with no useful message.

```python
elif broker == "arrow":
    code = (request.args.get("request-token") or request.args.get("request_token")
            or request.args.get("requestToken") or request.args.get("code"))
    auth_token, error_message = auth_function(code)
    forward_url = "broker.html"
```

### Token storage is automatic

`handle_auth_success` -> `database.auth_db.upsert_auth` stores the token
**encrypted** (Fernet) in the `Auth` table. The token is NEVER put in the Flask
cookie. `get_auth_token(user)` is the single source of truth.

Before touching `upsert_auth`, read the "Multi-session login must not tear down
the shared broker feed" invariant in the root `CLAUDE.md`. That function also
tears down the live market-data feed, and the teardown is deliberately gated on
a real token change.

### NUANCE — token rewriting

Zerodha stores `api_key:access_token` (rewritten in `brlogin.py` after a
successful auth). Most brokers store the bare token and need NO rewrite. Only
add a rewrite branch if downstream API calls require a composite token.

### NUANCE — feed_token / user_id brokers

Brokers whose `authenticate_broker` returns 3 or 4 elements must be added to the
explicit list in `brlogin.py`, or the extra values are discarded:

```python
if broker in ["angel", "compositedge", "pocketful", "definedge",
              "dhan", "rmoney", "iiflcapital"]:
    return handle_auth_success(auth_token, session["user"], broker,
                               feed_token=feed_token, user_id=user_id)
elif broker == "paytm":   # feed_token but no user_id
    return handle_auth_success(auth_token, session["user"], broker,
                               feed_token=feed_token)
```

If your broker has a separate market-data credential, also declare
`BrokerData.__init__(self, auth_token, feed_token)` — `quotes_service`
introspects the constructor's `co_argcount` and passes the feed token only when
the signature accepts it.

Note the OAuth-with-no-session case handled for `compositedge`, `rmoney`, and
`iiflcapital`: the broker redirect can land without a Flask session `user`, so
those branches look up the admin user from the DB. If your broker's callback can
arrive cold, copy that guard.

### Master contract auto-download

Fires post-login via a background thread
(`utils/auth_utils.async_master_contract_download` -> your
`master_contract_download()` -> `master_contract_cache_hook`). You do not call
it yourself.

## Platform wiring — the broker will not appear until ALL of these are done

### Code and config

| File | What |
| --- | --- |
| `.sample.env` + `.env` | add to `VALID_BROKERS` |
| `frontend/src/pages/BrokerSelect.tsx` | `allBrokers[]` entry + `switch` login-URL `case` (then `npm run build`) — see the login-variant section below |
| `websocket_proxy/__init__.py` | import + `register_adapter("<name>", <Name>WebSocketAdapter)` + `__all__` |
| `services/order_update_service.py` | `_BROKER_FACTORIES` entry, if the broker has an order-update feed |
| `blueprints/brlogin.py` | an `elif broker == "<name>"` branch (see above) |

### The frontend login page — four registries, not one

"Add it to `BrokerSelect.tsx`" understates the work. There are up to four
places, and which ones you touch depends on the login model.

**1. `BrokerSelect.tsx` — `allBrokers[]`.** The dropdown entry. Always required.

**2. `BrokerSelect.tsx` — the `switch (selectedBroker)` login-URL case.** Always
required. Three shapes:

| Shape | Who | What the case does |
| --- | --- | --- |
| **Backend callback** | ~24 brokers — angel, kotak, samco, aliceblue, iifl, shoonya, mstock, ... | falls through to `loginUrl = \`/${selectedBroker}/callback\`` — just add your `case` to the shared fall-through block |
| **Broker-hosted URL built client-side** | zerodha, fyers, upstox, flattrade, compositedge, arrow, hdfcsky, paytm, pocketful | constructs the broker's login URL from `broker_api_key` + `redirect_url` |
| **Dedicated backend initiator** | dhan | `loginUrl = '/dhan/initiate-oauth'` |

Client-side URL examples, showing how much they differ:

```ts
case 'zerodha':  loginUrl = `https://kite.trade/connect/login?api_key=${broker_api_key}`
case 'fyers':    loginUrl = `https://api-t1.fyers.in/api/v3/generate-authcode?client_id=${broker_api_key}&redirect_uri=${redirect_url}&response_type=code&state=...`
case 'flattrade': loginUrl = `https://auth.flattrade.in/?app_key=${getFlattradeApiKey(broker_api_key)}`   // composite key must be split first
case 'pocketful': // generates a random state, stores it in localStorage for CSRF, then builds the OAuth URL
```

**3. `BrokerTOTP.tsx` — `brokerConfigs`.** Only for **form-login** brokers. The
backend redirects to `/broker/<name>/totp` (8 brokers do this today: fivepaisa,
angel, mstock, tradejini, firstock, nubra, motilal, kotak) and this page renders
the form. 13 brokers have a config; everything else falls back to a `default` of
userid + password + totp — which is why an unconfigured broker still renders
*something*, just possibly the wrong fields.

The field sets vary far more than "username, password, TOTP" suggests:

| Broker | Fields |
| --- | --- |
| aliceblue | `userid` only |
| angel | `userid`, `pin`, `totp` |
| kotak | `mobile` (10-digit, `+91` prefix), `mpin`, `totp`, plus a `warning` string telling the user to enable TOTP in the Kotak NEO app |
| samco | `yob` (year of birth) only — client ID and password come from env |
| default | `userid`, `password`, `totp` |

Each field supports `type`, `placeholder`, `maxLength`, `pattern`, `inputMode`,
`prefix`, and `hint`. Set `pattern`/`inputMode` for numeric fields — it gets the
right mobile keyboard and blocks bad input before submit.

**4. `BrokerTOTP.tsx` — `brokerNames`.** A display-name map (`angel: 'Angel One'`).
Separate from `brokerConfigs`, so it is easy to add one and forget the other.

**The exception:** `SamcoAuth.tsx` (~720 lines) at `/broker/samco/auth` is a
bespoke page for one broker. Do not start here — exhaust `brokerConfigs` first.
A new broker needing its own page is a strong signal you have misread its auth
flow.

**Currency check.** `VALID_BROKERS`, `allBrokers[]`, and the switch are all 35
entries and in sync — keep it that way:

```bash
grep -c "id: '" frontend/src/pages/BrokerSelect.tsx     # must match VALID_BROKERS count
```

`brokerNames` already carries a stale `jmfinancial` entry with no plugin behind
it, so the secondary maps do drift.

### The `install/` folder — TWO lists per script, not one

Most install scripts carry the broker name **twice**: once in the machine-read
`valid_brokers` validation string, and again in a **human-facing display list**
that is a completely separate hardcoded copy. Updating only the first passes
validation while printing a menu that omits your broker.

| File | Validation list | Separate display list |
| --- | --- | --- |
| `install/install.sh` | `valid_brokers=` (~L113) | `log_message "\nValid brokers: ..."` (~L370) |
| `install/install-multi.sh` | `valid_brokers=` (~L53) | `log_message "\nValid brokers: ..."` (~L156) |
| `install/install-docker.sh` | `valid_brokers=` (~L45) | multi-line `echo` block (~L115-119) |
| `install/docker-run.sh` | `VALID_BROKERS=` (~L47) | multi-line `echo` block (~L211-216) |
| `install/docker-run.bat` | `set VALID_BROKERS=` (~L43) | `echo` block (~L163) |
| `install/install-docker-multi-custom-ssl.sh` | `valid_brokers=` (~L50) | none |

The display blocks are wrapped across several lines in alphabetical order, so
inserting a name means editing the right continuation line, not appending.

### `start.sh` — not an installer, and the one with real consequences

`start.sh` sits at the repo **root**, not in `install/`, and it is the Docker
container `CMD` (`Dockerfile:99`) — the runtime entrypoint, not a setup script.

Around line 51 it carries a broker list inside a shell default:

```sh
VALID_BROKERS = '${VALID_BROKERS:-fivepaisa,fivepaisaxts,aliceblue,angel,arrow,...}'
```

That is the **fallback baked into cloud deployments**. When the container starts
on Railway/Render (detected via `HOST_SERVER`) with no `.env` present, `start.sh`
generates one, and this string becomes `VALID_BROKERS` unless the platform
supplies its own.

**This is the one broker list whose omission is functional, not cosmetic.** Miss
a name in an installer display block and the user sees an incomplete menu. Miss
it here and the broker is genuinely unavailable on every cloud Docker deploy
that relies on the default — the login dropdown filters against `VALID_BROKERS`,
so it simply will not appear, while every bare-metal install works fine. That
asymmetry makes it hard to reproduce locally.

Update it in the same edit as `.sample.env`; the two lists should always match.

There is a second hardcoded default worth knowing about, though it is not a list
you maintain: `websocket_proxy/server.py` falls back to
`os.getenv("VALID_BROKERS", "angel")` in one place. If `VALID_BROKERS` is unset
the proxy assumes `angel`, which produces a confusing "wrong broker" failure
rather than a clear configuration error.

### Documentation lists

| File | Format |
| --- | --- |
| `install/README.md` | comma-separated block (~L42) |
| `README.md` | "Supported Brokers" list |
| `install/Docker-install-readme.md` | **markdown table**, one row per broker: `\| Display Name \| \`code\` \| XTS API \|` — easy to miss because it is not a comma list |

### Verify, don't trust

These copies **do** drift — as of this writing three display lists and the
Docker readme table are missing `arrow`, the most recently added broker, while
every validation list has it. After adding a broker, check every place at once:

```bash
grep -rn "<newbroker>" install/ start.sh .sample.env README.md \
  frontend/src/pages/BrokerSelect.tsx websocket_proxy/__init__.py
```

Count the hits against the tables above. A missing hit is a place you skipped.

Runtime modules (`websocket_proxy/server.py`, `utils/env_check.py`,
`blueprints/broker_credentials.py`, `blueprints/admin.py`) **read
`VALID_BROKERS` from env** — no edit needed.

### NUANCE — the broker dropdown is EMPTY on feature branches (stale dist)

Flask serves the pre-built `frontend/dist/`, and CI rebuilds it **only on
`main`**. On your feature branch the committed dist predates your
`BrokerSelect.tsx` edit, so the login dropdown filters against a broker list
that doesn't contain your broker and renders empty. This is not a backend bug:
run `cd frontend && npm install && npm run build` locally (the output is
gitignored — don't commit it; CI produces the canonical dist after merge), then
hard-refresh the browser.

## Env keys

`BROKER_API_KEY`, `BROKER_API_SECRET`, `REDIRECT_URL`
(`http://127.0.0.1:5000/<broker>/callback` — must EXACTLY match the broker
portal's registered redirect). The callback route is `/<broker>/callback`
(`brlogin.py:broker_callback`), broker taken from the URL path; the broker name
is also parsed out of `REDIRECT_URL` by regex `/([^/]+)/callback$` in
`blueprints/auth.py`, so a malformed `REDIRECT_URL` breaks login in a
non-obvious way.

XTS brokers also need `BROKER_API_KEY_MARKET` / `BROKER_API_SECRET_MARKET`.

## Token lifetime

Indian broker tokens expire daily at roughly **3:00 AM IST**; session handling
across the platform is built around that. Anything long-lived (streaming
adapters especially) must re-read a fresh token on reconnect rather than
caching one at startup.

Under the SEBI static IP mandate (April 1, 2026), transactional orders require
broker-side static IP whitelisting — a broker that authenticates fine from your
dev machine may reject order placement from a different network.
