# Broker login: manual and automated

Indian broker sessions expire daily at about 3:00 AM IST (`CLAUDE.md`;
`SESSION_EXPIRY_TIME = '03:00'` in `.sample.env`). After that every surface
(API, `/trading`, Flow, Python strategies) needs a fresh broker connect.

| Market | Daily login | What to do |
| --- | --- | --- |
| Indian broker | Required | Manual connect each day, or the 8:00 AM IST routine below |
| Crypto broker (Delta Exchange) | Not required | Set `DISABLE_SESSION_EXPIRY = 'true'` and `CRYPTO_MASTER_CONTRACT_CUTOFF_TIME = '00:00'`, connect once, no routine |

The per-broker answer is in the "Market" and "Daily login needed" columns of
[brokers.md](brokers.md). Never create the daily routine for a crypto broker.

## OpenAlgo pages used

| Page | Purpose |
| --- | --- |
| `/setup` | One-time account creation |
| `/login` | OpenAlgo login (username, password) |
| `/auth/logout` | Log out (used to test the routine) |
| `/broker` | Broker selection and **Connect Account** |
| `/broker/<code>/totp` | OpenAlgo's own login form for form-based brokers |
| `/dashboard` | Success page: broker badge, Live or Analyze badge, funds |
| `/apikey` | OpenAlgo API key |

## Manual mode (any broker, whenever the user wants)

1. Make sure the app is running (`curl -sf http://127.0.0.1:5000/auth/app-info`);
   start it if not ([install-and-run.md](install-and-run.md)).
2. In the box browser (browser subagent), open `http://127.0.0.1:5000/login` and
   log in to OpenAlgo.
3. Open `/broker`, select the broker, click **Connect Account**.
4. At the broker step, either:
   - hand the user the screen and let them type their credentials and TOTP or OTP
     themselves, or
   - ask for the one-time code through a secure in-chat form and type it the
     moment it arrives. Codes last about 30 seconds.
5. Submit. If the page does not auto-submit after the code, click the button
   (Kite needed a manual click on Continue).
6. Confirm `/dashboard` shows the broker connected, then tell the user in one line.

Brokers with an SMS or email OTP (Nubra, Definedge) can only be done this way:
OpenAlgo triggers the OTP on Connect and the user must read it from their phone.

## Automated mode (Indian brokers with TOTP)

### What to collect (secure forms only)

- OpenAlgo username and password
- Broker login fields the broker asks for every day (see brokers.md "Daily inputs")
- The **TOTP secret**: the base32 setup key shown when the user enrolled TOTP at
  the broker. Not a 6-digit code. If the user only scanned a QR code, ask them to
  re-enrol and copy the key, or stay with manual mode.

### Store on the box

```bash
mkdir -p /workspace/secrets && chmod 700 /workspace/secrets
install -m 600 /dev/null /workspace/secrets/<broker>.env
```

Write the values with a script that reads them from the secure form result, never
by echoing them in a command line that shows up in chat. Suggested keys:

```
OPENALGO_USERNAME=...
OPENALGO_PASSWORD=...
BROKER_USER_ID=...
BROKER_PASSWORD=...        # or BROKER_PIN / BROKER_MPIN, whatever the broker asks
BROKER_TOTP_SECRET=...     # base32
```

### Generate codes with pyotp

`pyotp` is already an OpenAlgo dependency; for the research project add it with
`cd /workspace/pyenv && uv add pyotp`. Helper `/workspace/secrets/totp.py`
(`chmod 600`):

```python
import sys, time, pyotp

env = dict(
    line.strip().split("=", 1)
    for line in open(sys.argv[1])
    if "=" in line and not line.startswith("#")
)
totp = pyotp.TOTP(env["BROKER_TOTP_SECRET"])
left = 30 - int(time.time()) % 30
if left < 6:                 # too close to rollover, wait for a fresh window
    time.sleep(left + 1)
    left = 30 - int(time.time()) % 30
print(totp.now(), left)
```

```bash
cd /workspace/pyenv && uv run python /workspace/secrets/totp.py /workspace/secrets/<broker>.env
# 123456 27
```

Generate the code immediately before typing it, never earlier. Do not print it in
chat.

### Browser steps

1. App running, else start it and wait for `/auth/app-info`.
2. `/login`: OpenAlgo username and password. If already logged in, the page
   redirects onward; continue.
3. `/broker`: select the broker, **Connect Account**.
4. Broker step. Two shapes:
   - **OpenAlgo form** (`/broker/<code>/totp`, for example Angel One, Kotak,
     Motilal Oswal, mStock, IndMoney, Firstock, 5paisa, Tradejini): fill the
     fields listed in brokers.md, generate the TOTP, submit.
   - **Broker-hosted page** (OAuth redirect brokers): fill the broker's own form,
     generate the TOTP when its field appears, submit. Only Zerodha has been
     verified on the box; for others read the page and adapt.
5. Wait for the redirect to `/dashboard`. Success = broker shown connected, Live
   badge or Analyze badge as the user left it, no error toast. The master contract
   downloads in the background after login.
6. Optional API check: `POST /api/v1/ping` with the API key returns `pong` and the
   broker name.

### Zerodha (verified on the box, Oct 17, 2026)

OpenAlgo `/login` -> `/broker` -> Zerodha -> **Connect Account** -> Kite login page
(`kite.trade/connect/login?api_key=...`) -> Kite **User ID** and **Password** ->
**External TOTP** field -> click **Continue** if it does not auto-submit ->
redirect to `http://127.0.0.1:5000/zerodha/callback` -> `/dashboard` with zerodha
in Live mode and the master contract loaded (about 1.1 lakh symbols).

Test it once at setup: log out at `/auth/logout`, run the steps above with a
generated code, confirm the dashboard.

### Routine: daily login at 8:00 AM IST (Indian brokers only)

Create a routine that runs every day at 8:00 AM IST (the user may choose weekdays
only). 8:00 AM is after the 3:00 AM expiry and before the 9:15 AM open. Do not
create it when the broker's Market column says Crypto.

Routine prompt template (fill the angle brackets, keep secrets out of it; they
live in the secrets file):

```
Daily OpenAlgo login for <broker display name> (<broker code>), Indian broker.

1. On the box, check http://127.0.0.1:5000/auth/app-info. If it does not answer,
   start OpenAlgo from /workspace/repos/openalgo with
   nohup setsid script -qfec "uv run app.py" app.log >/dev/null 2>&1 &
   and wait up to 2 minutes for app-info.
2. Read credentials from /workspace/secrets/<broker code>.env. Never print them.
3. In the box browser: open http://127.0.0.1:5000/login and log in to OpenAlgo
   as OPENALGO_USERNAME.
4. Open /broker, select <broker display name>, click Connect Account.
5. <Broker-specific step, for Zerodha: enter BROKER_USER_ID and BROKER_PASSWORD
   on the Kite page, then at the External TOTP field run
   cd /workspace/pyenv && uv run python /workspace/secrets/totp.py /workspace/secrets/zerodha.env
   type the code, and click Continue if it does not submit on its own.>
6. Confirm /dashboard shows <broker code> connected. If a POST to /api/v1/ping with
   the key in /workspace/pyenv/.env returns pong, include that.
7. Send the user one line: "OpenAlgo login done: <broker> connected, <Live or
   Analyze> mode, <time IST>." On failure send one line with the step that failed
   and the exact error text shown, and retry once with a fresh TOTP before giving up.
   Never include passwords, TOTP codes or API keys in the message.
```

If a pending task must run before a login (for example an `APP_KEY` rotation),
put it as step 0 of that day's run, then restart the app before step 3.
