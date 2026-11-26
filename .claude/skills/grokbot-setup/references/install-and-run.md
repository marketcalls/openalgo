# Install and run OpenAlgo on the box

Everything here runs on the box (Grok Bot's own Linux computer), never on the
user's desktop, unless the user asks for that explicitly.

## Layout used on the box

| Path | What |
| --- | --- |
| `/workspace/repos/openalgo` | OpenAlgo checkout, its own `.venv` from `uv sync` |
| `/workspace/repos/openalgo/.env` | OpenAlgo config and broker credentials, `chmod 600`, git-ignored |
| `/workspace/repos/openalgo/app.log` | Console output of the running app |
| `/workspace/repos/openalgo/db/` | `openalgo.db`, `logs.db`, `latency.db`, `health.db`, `sandbox.db`, `historify.duckdb` |
| `/workspace/repos/openalgo-charts` | Optional clone of the charts library |
| `/workspace/pyenv` | Separate uv research project: `openalgo` SDK, `yfinance`, `pyotp` |
| `/workspace/pyenv/.env` | `OPENALGO_API_KEY`, `OPENALGO_HOST`, `chmod 600` |
| `/workspace/secrets/<broker>.env` | Broker login secrets for the daily routine, `chmod 600` |

The box is shared by all of the user's bots. Check for an existing checkout and a
running instance before cloning or starting a second one:

```bash
ls /workspace/repos/openalgo 2>/dev/null && git -C /workspace/repos/openalgo log -1 --oneline
ss -ltnp | grep -E ':5000|:8765'
```

## 1. Clone and install

```bash
mkdir -p /workspace/repos && cd /workspace/repos
git clone https://github.com/marketcalls/openalgo.git
cd openalgo
uv sync --locked
```

- `pyproject.toml` declares `requires-python = ">=3.12"`; the repo pins `3.13` in
  `.python-version`, and uv fetches it if the box lacks it.
- Use uv only (`CLAUDE.md`). No `pip install`, no bare `python`.
- `frontend/dist/` is committed on `main`, so no Node.js build is needed.

## 2. Create `.env`

```bash
cp .sample.env .env
chmod 600 .env
```

Generate fresh secrets before the first start and before `/setup` creates the
account. Write them in with a script so the values never pass through chat:

```bash
uv run python - <<'PY'
import re, secrets, pathlib
p = pathlib.Path(".env")
t = p.read_text()
for key, n in (("APP_KEY", 32), ("API_KEY_PEPPER", 32), ("FERNET_SALT", 16)):
    t = re.sub(rf"^{key}\s*=.*$", f"{key} = '{secrets.token_hex(n)}'", t, count=1, flags=re.M)
p.write_text(t)
PY
grep -c PLACEHOLDER .env   # expect 0
```

`.sample.env` explains that OpenAlgo also rotates these placeholders itself on
first run and that the install scripts use `secrets.token_hex(32)`. Setting them
explicitly means the values exist in `.env` before the account does, and can be
backed up.

Rules from `.sample.env` and `upgrade/README.md`:

- `API_KEY_PEPPER` hashes the password and API key and feeds the Fernet key for
  broker tokens. `FERNET_SALT` feeds the same key. Never change either after the
  account exists. `upgrade/rotate_pepper.py` is the only supported rotation, and
  it is an explicit operator action, never part of a routine.
- `APP_KEY` signs session cookies and CSRF tokens. Rotating it only logs out
  sessions; restart the app and log in again afterwards.
- Never copy `.sample.env` over an existing `.env`; that discards the pepper and
  salt for good.

Then fill the broker block from [brokers.md](brokers.md):

```
BROKER_API_KEY = '...'
BROKER_API_SECRET = '...'
BROKER_API_KEY_MARKET = '...'      # XTS brokers only
BROKER_API_SECRET_MARKET = '...'   # XTS brokers only
REDIRECT_URL = 'http://127.0.0.1:5000/<broker>/callback'
```

OpenAlgo reads the active broker from `REDIRECT_URL`, so the code must match the
plugin folder under `broker/` exactly. `VALID_BROKERS` already lists every plugin;
leave it as shipped. Edit values with a script (as above), not by echoing them.

## 3. Start headless

```bash
cd /workspace/repos/openalgo
nohup setsid script -qfec "uv run app.py" app.log >/dev/null 2>&1 &
```

Why: `app.py` ends in `socketio.run(...)`, and flask_socketio refuses to start
Werkzeug when stdout is not a TTY, so a plain `nohup uv run app.py &` exits
immediately. `script -qfec` runs the command inside a pseudo-terminal, flushes
output to `app.log`, and returns the command's exit code; `setsid` detaches it so
it survives the shell.

Wait for it:

```bash
for i in $(seq 1 60); do
  curl -sf http://127.0.0.1:5000/auth/app-info && break; sleep 2
done
ss -ltn | grep -E '127.0.0.1:(5000|8765)'
```

Ports: `FLASK_PORT='5000'` (web, API, `/trading`), `WEBSOCKET_PORT='8765'`
(WebSocket proxy). ZeroMQ uses `127.0.0.1:5555` internally. Keep every host on
`127.0.0.1`; `.sample.env` warns against exposing the WebSocket or ZeroMQ ports.

Stop:

```bash
pkill -f "script -qfec uv run app.py"; pkill -f "openalgo/.venv/bin/python app.py"
```

Restart = stop, wait until port 5000 is free, start again.

## 4. Create the account

Open `http://127.0.0.1:5000/setup` in the box browser (browser subagent). The
page asks for username, email and password. Fill them from the user's secure form
values. The password must pass `validate_password_strength` in
`utils/auth_utils.py`: at least 8 characters with an uppercase letter, a
lowercase letter, a digit and a special character. `/setup` only works while no
account exists; afterwards it redirects to the login page. OpenAlgo is single
user per deployment (`CLAUDE.md`).

Lost password with no SMTP or authenticator: stop the app and run
`uv run python upgrade/reset_admin_password.py` (see `upgrade/README.md`).

## 5. API key for scripts

`/setup` already generates an API key for the new account (`blueprints/core.py`).
Open `/apikey` to read it (regenerate only if the user asks; that breaks anything
using the old key), and save it:

```bash
install -m 600 /dev/null /workspace/pyenv/.env
printf 'OPENALGO_API_KEY=%s\nOPENALGO_HOST=http://127.0.0.1:5000\n' "$KEY" > /workspace/pyenv/.env
```

(`$KEY` read from the page by the browser step, never typed into chat.)

Check it:

```bash
curl -s -X POST http://127.0.0.1:5000/api/v1/ping \
  -H 'Content-Type: application/json' -d "{\"apikey\":\"$KEY\"}"
# {"status":"success","data":{"message":"pong","broker":"<broker>"}}
```

`/api/v1/ping` returns 403 for a bad key or a missing broker session, so it also
proves the broker login (`docs/api/utility-services/ping.md`).

## 6. Optional research project

```bash
mkdir -p /workspace/pyenv && cd /workspace/pyenv
uv init --python 3.13 --name pyenv .
uv add openalgo yfinance pyotp
```

Load the key with uv's `--env-file` instead of hardcoding it:

```python
# quote.py
import os
from openalgo import api

client = api(api_key=os.environ["OPENALGO_API_KEY"], host=os.environ["OPENALGO_HOST"])
print(client.quotes(symbol="RELIANCE", exchange="NSE"))
```

```bash
uv run --env-file /workspace/pyenv/.env python quote.py
```

SDK calls, symbol format and indicators: `docs/prompt/openalgo python sdk.md`,
`docs/prompt/symbol-format.md`, `docs/prompt/indicators/`. Pass `ta` arguments by
name; some signatures differ from the docs order.

Charts library (only for standalone chart work; the `/trading` page already ships
it):

```bash
mkdir -p /workspace/openalgo-charts-npm && cd /workspace/openalgo-charts-npm
npm init -y && npm install openalgo-charts
```

Optional source clone for reference: `git clone https://github.com/marketcalls/openalgo-charts.git /workspace/repos/openalgo-charts`.
