---
name: grokbot-setup
description: Understand, set up and run OpenAlgo inside Grok Bot, the desktop assistant that has its own Linux computer (the box). Use for any OpenAlgo question (start with references/openalgo-knowledge.md), and when a user wants OpenAlgo running on the box - cloning and installing with uv, writing .env with their broker credentials, starting the app headless, creating the OpenAlgo account, connecting the broker manually or through an automated daily TOTP login, scheduling the weekly upgrade, or explaining what works on the box versus what needs a static IP.
---

# Running OpenAlgo inside Grok Bot

Grok Bot works on the box: one persistent Linux machine shared by all of the
user's bots, with `/workspace` as scratch space, a browser driven through a
browser subagent, scheduled **routines**, and secure in-chat forms for secrets and
one-time codes. Everything below was proven end to end on the box with Zerodha
(Python 3.13, OpenAlgo 2.0.2.8, `.env` version 1.0.7).

## How to use this skill

Start every OpenAlgo task by reading
[references/openalgo-knowledge.md](references/openalgo-knowledge.md). It holds
the architecture, every product surface, the REST and SDK catalog, WebSocket
protocol, symbol and order formats, indicators, OpenScript, charts, Flow, the
other skills, and the known conflicts between docs and code. Then open the one
reference, doc or skill the table below names for the task.

| User wants to | Open |
| --- | --- |
| Understand OpenAlgo, a feature, a page or a term | `references/openalgo-knowledge.md`, then the doc it cites |
| Install or reinstall OpenAlgo on the box, start or restart it | Sections 2-4 below, [references/install-and-run.md](references/install-and-run.md) |
| Know which credentials a broker needs, or which login it uses | [references/brokers.md](references/brokers.md), then the broker's page on docs.openalgo.in (`.md` suffix) |
| Connect the broker now (manual login, TOTP via secure form) | Section 5, [references/login-routines.md](references/login-routines.md) "Manual mode" |
| Set up the daily 8:00 AM IST auto-login (Indian brokers) | [references/login-routines.md](references/login-routines.md) "Automated mode" and its routine template |
| Upgrade OpenAlgo, or set up the Sunday 6:00 AM IST upgrade | [references/weekly-upgrade.md](references/weekly-upgrade.md) |
| Pull quotes, history, option chains; place Sandbox orders from Python | Knowledge sections 6, 7, 9, 10; `docs/prompt/openalgo python sdk.md`; `docs/api/<group>/<endpoint>.md` |
| Stream live ticks or order updates | Knowledge section 8; `docs/prompt/websockets-format.md` |
| Compute indicators in Python (`openalgo.ta`) | Knowledge section 11; `/workspace/reference/openalgo-indicators.md`; `docs/prompt/indicators/` |
| Write a study or strategy for the `/trading` chart in OpenScript | Skill `openscript`; https://openalgo.in/script/llms.txt |
| Write a JavaScript chart indicator for `/trading` | Skill `chart-indicator`; `docs/custom-indicators.md` |
| Build a no-code workflow, webhook-to-order flow | Skill `flow-builder`; `docs/prompt/flow-import-format.md` |
| Multi-leg options strategy with risk rules | `docs/prompt/strategy_rms_documentation.md`, `docs/api/strategy-services/` |
| TradingView, ChartInk, Amibroker, MCP, Telegram, WhatsApp | Knowledge section 15; `docs/userguide/` (16-23), `docs/mcp-tool-reference.md` |
| Crypto (Delta Exchange) symbols or setup | `docs/prompt/crypto-symbol-format.md`; brokers.md Delta row |
| Trade Live, or asks about static IP | Section 8 below; knowledge section 5 |
| Change OpenAlgo's own code | `CLAUDE.md`, then `broker-integration`, `fd-audit`, `verify`, `version-bump` as they apply |
| Anything not covered above | `docs/INDEX.md`, then https://docs.openalgo.in/llms.txt |

### Rules

1. **Knowledge file first.** Read `references/openalgo-knowledge.md` before
   answering or acting on any OpenAlgo question.
2. **Never guess.** For a parameter, field, limit or behaviour, open the repo
   `docs/` file (via `docs/INDEX.md`) or the docs.openalgo.in page (append
   `.md`). If neither says, say it is not documented.
3. **When docs conflict, test the package.** Check the installed SDK in
   `/workspace/pyenv` (`inspect.signature`, a small call) or the repo code, and
   follow what runs. Known conflicts are in knowledge section 18.
4. **uv only.** `uv sync`, `uv run`, `uv add`. No pip, no bare python.
5. **Never echo secrets.** Collect passwords, API keys, TOTP secrets and codes
   through secure in-chat forms; store them on the box with `chmod 600`; never
   repeat them in chat, logs, routines or reports; never commit them.
6. **Sandbox by default.** Run test orders in Sandbox (analyzer) mode; read the
   mode first with `analyzerstatus()`. Switch to Live or place a Live order
   only when the user explicitly asks for that order.
7. **Static IP.** The box has no static IP; Live API orders from it will be
   rejected under the SEBI rule. Say so before the user relies on Live orders
   from the box.
8. **Trader language.** Say Live and Sandbox, never "paper" or "armed"; no
   emojis; give the cause and the next step, not status codes.
9. **One instance.** The box is shared by the user's bots: check for an
   existing checkout and a running app (ports 5000, 8765) before installing or
   starting another.

## 1. What the user must supply

Ask for these up front, each through a secure form:

1. **OpenAlgo account**: username, email, password. Created once at `/setup`.
2. **Broker**: the broker code from [references/brokers.md](references/brokers.md).
3. **Broker credentials**: exactly the `.env` fields that table lists for that
   broker (they differ broker to broker). Send the user the broker's
   docs.openalgo.in page so they can create the app and register the redirect URL
   `http://127.0.0.1:5000/<broker>/callback` (the code must match exactly).
4. **Login mode**: manual, or automated daily login. Automated needs whatever the
   broker's login asks for every day (user ID, password or PIN, and the **TOTP
   secret**, the base32 setup key shown when TOTP was enrolled, not a 6-digit code).

If the broker's login uses an SMS or email OTP (Nubra, Definedge), automation is
not possible; say so before the user spends time on it.

## 2. Install

Full commands and the reasons behind them: [references/install-and-run.md](references/install-and-run.md).

```bash
mkdir -p /workspace/repos && cd /workspace/repos
git clone https://github.com/marketcalls/openalgo.git && cd openalgo
uv sync --locked                       # requires-python >=3.12; 3.13 used on the box
cp .sample.env .env && chmod 600 .env
```

Then, **before the first start and before any account exists**:

- Replace `APP_KEY`, `API_KEY_PEPPER` and `FERNET_SALT` placeholders with fresh
  random values (the app also rotates placeholders on first run, but set them
  explicitly so the values are known and backed up).
- Fill the broker fields and `REDIRECT_URL` from the brokers table.
- Leave `HOST_SERVER`, `FLASK_HOST_IP` (127.0.0.1) and the ports alone.

`API_KEY_PEPPER` and `FERNET_SALT` must never change after the account is
created: they hash the password and encrypt broker tokens and the API key, and a
change locks the user out. `APP_KEY` can be rotated later; it only signs sessions,
so a rotation logs everyone out and needs a restart.

## 3. Start the app headless

```bash
cd /workspace/repos/openalgo
nohup setsid script -qfec "uv run app.py" app.log >/dev/null 2>&1 &
```

Plain `nohup uv run app.py &` crashes: flask_socketio refuses to run Werkzeug
without a TTY. `script` gives it a pseudo-terminal and `setsid` detaches it from
the shell. The app listens on `127.0.0.1:5000` (web) and `127.0.0.1:8765`
(WebSocket). Check with `curl -s http://127.0.0.1:5000/auth/app-info`.

## 4. First-time setup in the browser

1. Open `http://127.0.0.1:5000/setup` in the box browser and create the account
   with the user's username, email and password.
2. Log in, go to `/broker`, pick the broker and connect it (section 5).
3. Open `/apikey` to read the API key that `/setup` generated (regenerate only
   if the user asks), and save it to the research
   project's `.env` (`/workspace/pyenv/.env`, `chmod 600`) as `OPENALGO_API_KEY`
   with `OPENALGO_HOST=http://127.0.0.1:5000`. Never paste it into chat unless the
   user asks for it.

Optional research tooling (separate uv project, not inside the OpenAlgo repo):
the `openalgo` SDK, `yfinance`, `pyotp`, and the `openalgo-charts` npm package.
See [references/install-and-run.md](references/install-and-run.md).

## 5. Connecting the broker

**Indian brokers** expire their sessions daily at about 3:00 AM IST
(`SESSION_EXPIRY_TIME = '03:00'`), so they must be connected once every day and
the 8:00 AM IST routine below applies to them only. **Crypto brokers** (Delta
Exchange) run 24/7: set `DISABLE_SESSION_EXPIRY = 'true'` and
`CRYPTO_MASTER_CONTRACT_CUTOFF_TIME = '00:00'` as the Delta Exchange docs say,
connect once, and do not create a daily login routine. Reconnect a crypto broker
only after a restart or if the dashboard shows it disconnected. The "Market" and
"Daily login needed" columns in [references/brokers.md](references/brokers.md)
say which case a broker is. Two modes:

**Manual (any broker).** Whenever the user asks, open OpenAlgo in the box browser,
log in, go to `/broker`, click Connect, and stop at the broker's own login. Either
hand the user the screen to type their credentials and TOTP, or ask for the
one-time code through a secure form and type it in. Codes last 30 seconds: fill
and submit immediately, and click the submit button yourself if the page does not
auto-submit.

**Automated daily login (Indian TOTP brokers).** Store the TOTP secret on the box,
generate codes with `pyotp`, and create a routine at 8:00 AM IST every day that:
ensures the app is running, logs in to OpenAlgo, connects the broker, fills the
TOTP, verifies the dashboard, and reports one line. Full script, browser steps and
the routine prompt: [references/login-routines.md](references/login-routines.md).

The Zerodha flow proven on the box: OpenAlgo login, `/broker`, select Zerodha,
**Connect Account**, Kite user ID and password, **External TOTP** field, then the
redirect lands on `/dashboard` with the broker shown in Live mode and the master
contract downloading.

Which brokers fit which mode, from the docs and the plugin code, is in the
"Daily login needed" and "TOTP automation" columns of
[references/brokers.md](references/brokers.md). Brokers that connect with key and
secret alone (the XTS family, Groww, Samco, Dhan Sandbox) need no TOTP: the
daily routine just clicks Connect. Delta Exchange also connects with key and
secret alone, and needs no daily routine at all.

## 6. Secrets handling

- Collect through secure in-chat forms or secret requests. Never repeat a secret,
  password, TOTP secret or API key back in chat, logs, commit messages or reports.
- Store broker login secrets in `/workspace/secrets/<broker>.env`, directory
  `chmod 700`, files `chmod 600`. OpenAlgo's own `.env` stays in the repo root,
  `chmod 600`, and is git-ignored.
- The box is shared by every bot of this user. `chmod 600` keeps other OS users
  out, not other bots of the same user; tell the user that plainly.
- If the user pastes a secret into chat anyway, use it, then suggest rotating it
  at the broker.
- Before any upgrade or key change, copy `.env` to a dated backup with
  `chmod 600`.

## 7. Weekly upgrade

A routine every Sunday at 6:00 AM IST: re-read `CLAUDE.md` and `upgrade/README.md`
for changed procedure, stop the app, back up `.env` and all six stores in `db/`,
`git pull --ff-only`, `uv sync --locked`, `cd upgrade && uv run migrate_all.py`,
merge new `.sample.env` keys into `.env` without touching existing values,
restart, re-login the broker, verify, and report. On any failure roll back to the
previous commit and backup and report the exact error. Do not use
`install/update.sh` on the box: it expects sudo and a server layout. Steps and
routine prompt: [references/weekly-upgrade.md](references/weekly-upgrade.md).

## 8. Limits of the box

- **No static IP.** Box egress goes through a shared, rotating Cloudflare pool
  (seen as different `104.28.x.x` addresses minutes apart). It cannot be
  whitelisted with a broker.
- **SEBI static IP mandate (effective April 1, 2026).** Transactional API orders
  need the broker to see the registered static IP. Live orders placed from the box
  will be rejected. For Live trading, run OpenAlgo on a VPS with a static IP
  registered in the broker's developer console, and let Grok Bot drive that
  instance over its API.
- **What works on the box:** login, quotes, history, WebSocket data, `/trading`
  charts, indicators, scanners, backtests, Flow and Python strategies in Sandbox
  mode (1 Crore sandbox capital).
- **Brokers that whitelist all API calls, not only orders,** may fail even to log
  in or fetch data from the box. The docs say this for IIFL Capital, Tradejini and
  TradeSmart; see the notes column in the brokers table.

## 9. Verification checklist

Run all of these before telling the user setup is done:

- [ ] `git -C /workspace/repos/openalgo status` clean except the user's own work; `.env` is ignored
- [ ] `stat -c %a .env` is `600`; `/workspace/secrets` is `700` and its files `600`
- [ ] `APP_KEY`, `API_KEY_PEPPER`, `FERNET_SALT` are no longer placeholders (check with grep for `PLACEHOLDER`, do not print values)
- [ ] `REDIRECT_URL` broker code matches the broker in the table
- [ ] `curl -s http://127.0.0.1:5000/auth/app-info` returns `"status":"success"` and a version
- [ ] Ports 5000 and 8765 are listening on 127.0.0.1 (`ss -ltn`)
- [ ] `/dashboard` shows the broker connected and the master contract loaded
- [ ] `POST /api/v1/ping` with the API key returns `pong` and the broker name
- [ ] A read-only SDK call works, for example a RELIANCE NSE quote
- [ ] Indian broker: daily login routine (if chosen) created for 8:00 AM IST, tested once by logging out and running it. Crypto broker: no daily routine, `DISABLE_SESSION_EXPIRY = 'true'` set
- [ ] Weekly upgrade routine created for Sunday 6:00 AM IST
- [ ] The user has been told about the static IP limit for Live orders

## Things that went wrong on the box, and the fix

| Symptom | Cause | Fix |
| --- | --- | --- |
| App exits right after `nohup uv run app.py &` | flask_socketio refuses Werkzeug without a TTY | Start with `setsid script -qfec "uv run app.py" app.log` |
| TOTP typed but Kite does not move on | The page did not auto-submit | Click Continue; generate a fresh code if more than 25 s passed |
| "Invalid credentials" with the right password | `API_KEY_PEPPER` or `FERNET_SALT` changed after account creation | Restore them from the `.env` backup; see `upgrade/README.md` |
| Funds cards read 0.00 on a weekend | Not confirmed; seen on a Saturday right after a good login | Recheck on a trading day before treating it as a fault |
| Broker rejects a Live order (expected, not tested) | No static IP on the box | Use Sandbox here, Live from a static IP VPS |
