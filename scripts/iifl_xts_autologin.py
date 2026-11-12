"""Daily IIFL (XTS) login for OpenAlgo, meant to run from cron before the open.

What it does, in the order a trader does it in the browser:

0. Asks OpenAlgo's own market calendar whether today is a trading day
   (weekends, exchange holidays and special sessions included) and exits
   quietly when every exchange is closed.
1. Signs in to OpenAlgo with the username and password (POST /auth/login).
2. Selects IIFL on Select Broker (POST /auth/broker/login, CSRF-checked).
3. Completes the IIFL login (GET /iifl/callback). IIFL XTS needs no TOTP or
   broker password: OpenAlgo logs in with the Interactive and Market Data
   keys already saved for IIFL.
4. Confirms the session is logged in to IIFL (GET /auth/session-status).
5. Sends a Telegram message through OpenAlgo's own bot
   (POST /api/v1/telegram/notify) to the Telegram account linked to the
   OpenAlgo username, on success and on failure. The bot must be running and
   the account linked with /link in the bot.

The server address comes from HOST_SERVER in OpenAlgo's .env, for example
HOST_SERVER = 'https://trade.example.in'.

Usage:
    python iifl_xts_autologin.py --openalgo-env /path/to/openalgo/.env \
        --credentials ~/.openalgo-autologin.env

The credentials file (chmod 600, never in git) holds:
    OPENALGO_USERNAME=...
    OPENALGO_PASSWORD=...
    OPENALGO_APIKEY=...      # from /apikey: market calendar check and Telegram

Exit codes: 0 logged in or market closed, 1 login failed, 2 bad configuration.
"""

import argparse
import datetime
import logging
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import dotenv_values

IST = ZoneInfo("Asia/Kolkata")
BROKER = "iifl"
TIMEOUT = 30
RETRY_DELAY_SECONDS = 60

log = logging.getLogger("iifl_autologin")


class LoginFailed(Exception):
    """A step of the login did not succeed."""


def load_config(openalgo_env: Path, credentials: Path) -> dict:
    """Read HOST_SERVER from OpenAlgo's .env and the login from the credentials file."""
    if not openalgo_env.is_file():
        raise SystemExit(f"OpenAlgo .env not found: {openalgo_env}")
    if not credentials.is_file():
        raise SystemExit(f"Credentials file not found: {credentials}")

    host = (dotenv_values(openalgo_env).get("HOST_SERVER") or "").strip().rstrip("/")
    if not host:
        raise SystemExit(f"HOST_SERVER is not set in {openalgo_env}")

    creds = dotenv_values(credentials)
    missing = [k for k in ("OPENALGO_USERNAME", "OPENALGO_PASSWORD") if not creds.get(k)]
    if missing:
        raise SystemExit(f"Missing in {credentials}: {', '.join(missing)}")

    return {
        "host": host,
        "username": creds["OPENALGO_USERNAME"],
        "password": creds["OPENALGO_PASSWORD"],
        "apikey": creds.get("OPENALGO_APIKEY") or "",
    }


def market_open_today(host: str, apikey: str) -> bool:
    """True when at least one exchange trades today, per OpenAlgo's calendar.

    If the calendar cannot be read the login goes ahead: logging in on a
    holiday is harmless, missing a trading day is not.
    """
    today = datetime.datetime.now(IST).date().isoformat()
    if not apikey:
        log.warning("OPENALGO_APIKEY not set; skipping the holiday check (weekday only)")
        return True
    try:
        r = requests.post(
            f"{host}/api/v1/market/timings",
            json={"apikey": apikey, "date": today},
            timeout=TIMEOUT,
        )
        body = r.json()
    except (requests.RequestException, ValueError):
        log.exception("Could not read the market calendar; logging in anyway")
        return True
    if body.get("status") != "success":
        log.warning("Market calendar answered %s; logging in anyway", body.get("message"))
        return True
    return bool(body.get("data"))


def notify_telegram(cfg: dict, message: str) -> None:
    """Send a message through OpenAlgo's Telegram bot. Never fails the run."""
    if not cfg["apikey"]:
        log.warning("OPENALGO_APIKEY not set; no Telegram message sent")
        return
    try:
        r = requests.post(
            f"{cfg['host']}/api/v1/telegram/notify",
            json={
                "apikey": cfg["apikey"],
                "username": cfg["username"],
                "message": message,
                "priority": 8,
                "wait_for_delivery": True,
            },
            timeout=TIMEOUT,
        )
        body = r.json()
    except (requests.RequestException, ValueError):
        log.exception("Telegram message could not be sent")
        return
    if body.get("status") == "success":
        log.info("Telegram message sent")
    else:
        log.warning("Telegram message not sent: %s", body.get("message"))


def csrf_token(s: requests.Session, host: str) -> str:
    """A CSRF token bound to this session's cookie."""
    r = s.get(f"{host}/auth/csrf-token", timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()["csrf_token"]


def login_once(cfg: dict) -> str:
    """Run the whole login once. Returns the connected broker, raises LoginFailed."""
    host = cfg["host"]
    s = requests.Session()
    # Over HTTPS, Flask-WTF requires a same-origin Referer on CSRF-checked POSTs.
    s.headers.update({"Referer": f"{host}/", "User-Agent": "openalgo-autologin/1.0"})

    # 1. OpenAlgo username and password. The login form is CSRF-checked like
    # every other POST outside /api/v1, so fetch a token first, as the login
    # page does.
    token = csrf_token(s, host)
    r = s.post(
        f"{host}/auth/login",
        data={"username": cfg["username"], "password": cfg["password"], "csrf_token": token},
        headers={"X-CSRFToken": token},
        timeout=TIMEOUT,
    )
    try:
        body = r.json()
    except ValueError as exc:
        raise LoginFailed(f"OpenAlgo login returned HTTP {r.status_code}, not JSON") from exc
    if body.get("status") == "totp_required":
        raise LoginFailed("OpenAlgo login 2FA is on; this script does not handle it")
    if r.status_code != 200 or body.get("status") != "success":
        raise LoginFailed(f"OpenAlgo login refused: {body.get('message')}")
    log.info("OpenAlgo sign-in done")

    # 2. Select IIFL
    token = csrf_token(s, host)
    r = s.post(
        f"{host}/auth/broker/login",
        json={"broker": BROKER},
        headers={"X-CSRFToken": token},
        timeout=TIMEOUT,
    )
    try:
        body = r.json()
    except ValueError as exc:
        raise LoginFailed(f"Broker selection returned HTTP {r.status_code}, not JSON") from exc
    if body.get("status") != "success":
        raise LoginFailed(f"Broker selection refused: {body.get('message')}")
    start = body.get("url", "")
    log.info("Broker login started: %s", start)

    # 3. Complete the IIFL login with the saved XTS keys
    if start != "/dashboard":
        if not start.startswith("/"):
            raise LoginFailed(f"Unexpected login address for IIFL: {start}")
        r = s.get(f"{host}{start}", timeout=120)
        if r.status_code >= 400:
            raise LoginFailed(f"IIFL login returned HTTP {r.status_code}")

    # 4. Confirm
    r = s.get(f"{host}/auth/session-status", timeout=TIMEOUT)
    st = r.json()
    if not (st.get("logged_in") and st.get("broker") == BROKER):
        raise LoginFailed(
            f"Not connected after login (logged_in={st.get('logged_in')}, broker={st.get('broker')})"
        )
    return st.get("broker")


def main() -> int:
    """Entry point for cron."""
    here = Path(__file__).resolve().parent
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--openalgo-env", type=Path, default=here.parent / ".env")
    p.add_argument("--credentials", type=Path, default=Path.home() / ".openalgo-autologin.env")
    p.add_argument("--force", action="store_true", help="log in even if the market is closed")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    cfg = load_config(args.openalgo_env, args.credentials)
    log.info("Server: %s", cfg["host"])

    if not args.force and not market_open_today(cfg["host"], cfg["apikey"]):
        log.info("Market closed today; no login needed")
        return 0

    error = ""
    for attempt in (1, 2):
        try:
            broker = login_once(cfg)
            log.info("Logged in: broker %s connected", broker)
            now = datetime.datetime.now(IST).strftime("%d %b %Y %H:%M")
            notify_telegram(
                cfg,
                f"OpenAlgo auto login done: IIFL connected at {now} IST. Ready for the market open.",
            )
            return 0
        except (LoginFailed, requests.RequestException, KeyError, ValueError) as exc:
            error = str(exc)
            log.error("Attempt %d failed: %s", attempt, exc)
            if attempt == 1:
                time.sleep(RETRY_DELAY_SECONDS)

    now = datetime.datetime.now(IST).strftime("%d %b %Y %H:%M")
    notify_telegram(
        cfg,
        f"OpenAlgo auto login FAILED at {now} IST: {error}. "
        "Log in to IIFL manually before the market opens.",
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
