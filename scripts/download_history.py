"""
OpenAlgo Historify — 2-Year 1-Minute Data Downloader
Downloads OHLCV data for Indian stocks via the Historify job system.

CONFIGURE THESE BEFORE RUNNING:
"""

BASE_URL = "http://127.0.0.1:5000"
OPENALGO_API_KEY = "YOUR_OPENALGO_API_KEY"   # <-- From OpenAlgo dashboard → API Keys
USERNAME = "admin"                             # <-- Your OpenAlgo username
PASSWORD = "YOUR_PASSWORD_HERE"               # <-- Your OpenAlgo login password

SYMBOLS = [
    {"symbol": "ADANIPORTS", "exchange": "NSE"},
    {"symbol": "RELIANCE",   "exchange": "NSE"},
    {"symbol": "NIFTY",      "exchange": "NSE_INDEX"},   # Indices live on NSE_INDEX
    {"symbol": "BANKNIFTY",  "exchange": "NSE_INDEX"},
]

INTERVAL = "1m"
LOOKBACK_DAYS = 730   # 2 years

POLL_INTERVAL_SECONDS = 30

# ---------------------------------------------------------------------------

import sys
import time
from datetime import date, timedelta

try:
    import requests
except ImportError:
    print("ERROR: 'requests' is not installed. Run: pip install requests")
    sys.exit(1)


def step(label):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")


def verify_password_set():
    if PASSWORD == "YOUR_PASSWORD_HERE":
        print("ERROR: Please set the PASSWORD variable at the top of this script.")
        print("       It is your OpenAlgo web login password.")
        sys.exit(1)


def ping(session):
    """Confirm API key and broker connectivity."""
    step("STEP 1 — Pinging OpenAlgo API")
    r = session.post(
        f"{BASE_URL}/api/v1/ping",
        json={"apikey": OPENALGO_API_KEY},
        timeout=10,
    )
    if r.status_code == 200 and r.json().get("status") == "success":
        data = r.json().get("data", {})
        print(f"  ✓ API reachable | broker={data.get('broker')} | {data.get('message')}")
        return True
    print(f"  ✗ Ping failed: {r.status_code} — {r.text[:200]}")
    return False


def web_login(session):
    """Login to OpenAlgo web session so Historify endpoints are accessible."""
    step("STEP 2 — Logging into OpenAlgo web session")
    r = session.post(
        f"{BASE_URL}/login",
        data={"username": USERNAME, "password": PASSWORD},
        headers={"Accept": "application/json"},
        timeout=15,
        allow_redirects=False,
    )
    body = {}
    try:
        body = r.json()
    except Exception:
        pass

    if r.status_code in (200, 302):
        redirect = body.get("redirect", "")
        if redirect == "/dashboard" or r.status_code == 302:
            print(f"  ✓ Logged in — broker session resumed automatically")
            return True
        if redirect == "/broker":
            print("  ✗ Password OK but broker OAuth is needed.")
            print("    Go to http://127.0.0.1:5000/broker to authenticate with Zerodha,")
            print("    then re-run this script.")
            return False
        if body.get("status") == "success":
            print(f"  ✓ Password accepted (session state: {redirect or 'check dashboard'})")
            return True

    print(f"  ✗ Login failed ({r.status_code}): {body.get('message', r.text[:200])}")
    print("    Check USERNAME and PASSWORD at the top of this script.")
    return False


def manage_watchlist(session):
    """Add all symbols to the Historify watchlist."""
    step("STEP 3 — Adding symbols to Historify watchlist")
    existing = set()

    # Fetch current watchlist
    r = session.get(f"{BASE_URL}/historify/api/watchlist", timeout=10)
    if r.status_code == 200:
        for item in r.json().get("data", []):
            existing.add((item["symbol"], item["exchange"]))
        print(f"  Watchlist currently has {len(existing)} symbol(s)")
    elif r.status_code == 401:
        print("  ✗ Session not authenticated for Historify.")
        print("    Complete Zerodha OAuth at http://127.0.0.1:5000/broker first.")
        return False

    added = 0
    for sym in SYMBOLS:
        key = (sym["symbol"], sym["exchange"])
        if key in existing:
            print(f"  • {sym['symbol']} ({sym['exchange']}) — already in watchlist")
            continue
        r = session.post(
            f"{BASE_URL}/historify/api/watchlist",
            json={"symbol": sym["symbol"], "exchange": sym["exchange"]},
            timeout=10,
        )
        if r.status_code in (200, 201):
            print(f"  + Added {sym['symbol']} ({sym['exchange']})")
            added += 1
        else:
            body = {}
            try:
                body = r.json()
            except Exception:
                pass
            print(f"  ! Could not add {sym['symbol']}: {body.get('message', r.text[:100])}")

    print(f"  ✓ Watchlist ready ({added} new symbol(s) added)")
    return True


def create_download_job(session):
    """Create a Historify bulk download job for all symbols."""
    step("STEP 4 — Creating 1-minute download job (2 years)")

    end_date   = date.today().strftime("%Y-%m-%d")
    start_date = (date.today() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    print(f"  Symbols : {[s['symbol'] for s in SYMBOLS]}")
    print(f"  Interval: {INTERVAL}")
    print(f"  Range   : {start_date} → {end_date} ({LOOKBACK_DAYS} days)")

    payload = {
        "job_type":  "custom",
        "symbols":   SYMBOLS,
        "interval":  INTERVAL,
        "start_date": start_date,
        "end_date":   end_date,
        "incremental": False,
    }

    r = session.post(
        f"{BASE_URL}/historify/api/jobs",
        json=payload,
        timeout=30,
    )
    body = {}
    try:
        body = r.json()
    except Exception:
        pass

    if r.status_code == 200 and body.get("status") == "success":
        job_id = body["job_id"]
        print(f"  ✓ Job created: {job_id}")
        return job_id
    else:
        print(f"  ✗ Job creation failed ({r.status_code}): {body.get('message', r.text[:300])}")
        return None


def poll_job(session, job_id):
    """Poll job until complete, printing progress every POLL_INTERVAL_SECONDS."""
    step(f"STEP 5 — Monitoring job {job_id}")
    print(f"  Polling every {POLL_INTERVAL_SECONDS}s — Ctrl+C to stop watching\n")

    terminal_states = {"completed", "failed", "cancelled"}
    start_time = time.time()

    while True:
        try:
            r = session.get(f"{BASE_URL}/historify/api/jobs/{job_id}", timeout=15)
            if r.status_code != 200:
                print(f"  ! Status check error: {r.status_code}")
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            job = r.json().get("data", {})
            status    = job.get("status", "unknown")
            total     = job.get("total_items", 0)
            completed = job.get("completed_items", 0)
            failed_n  = job.get("failed_items", 0)
            elapsed   = int(time.time() - start_time)
            pct       = int(completed / total * 100) if total else 0

            bar_filled = int(pct / 5)
            bar = "█" * bar_filled + "░" * (20 - bar_filled)
            print(
                f"  [{bar}] {pct:3d}% | "
                f"{completed}/{total} symbols | "
                f"failed={failed_n} | "
                f"status={status} | "
                f"elapsed={elapsed}s"
            )

            if status in terminal_states:
                print()
                if status == "completed":
                    print(f"  ✓ Job completed successfully in {elapsed}s")
                elif status == "failed":
                    print(f"  ✗ Job failed — check logs at D:\\OPENALGO\\log\\")
                else:
                    print(f"  ! Job ended with status: {status}")
                return status

            time.sleep(POLL_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            print("\n  Stopped watching (job continues in background)")
            return "interrupted"


def fetch_stats(session):
    """Fetch and display Historify DuckDB statistics."""
    step("STEP 6 — Historify database statistics")
    r = session.get(f"{BASE_URL}/historify/api/stats", timeout=15)
    if r.status_code != 200:
        print(f"  Could not fetch stats ({r.status_code})")
        return

    data = r.json().get("data", {})
    print(f"  Total symbols stored : {data.get('total_symbols', 'N/A')}")
    print(f"  Total records        : {data.get('total_records', 'N/A'):,}" if isinstance(data.get('total_records'), int) else f"  Total records        : {data.get('total_records', 'N/A')}")
    print(f"  DB size              : {data.get('db_size_mb', 'N/A')} MB")

    # Per-symbol breakdown
    by_symbol = data.get("by_symbol", [])
    if by_symbol:
        print()
        print(f"  {'Symbol':<20} {'Exchange':<8} {'Interval':<10} {'Records':>10}  Date range")
        print(f"  {'-'*20} {'-'*8} {'-'*10} {'-'*10}  {'-'*25}")
        for row in by_symbol:
            print(
                f"  {row.get('symbol',''):<20} "
                f"{row.get('exchange',''):<8} "
                f"{row.get('interval',''):<10} "
                f"{row.get('record_count',0):>10,}  "
                f"{row.get('start_date','')} → {row.get('end_date','')}"
            )


def main():
    verify_password_set()

    session = requests.Session()
    session.headers.update({"User-Agent": "OpenAlgo-HistoryScript/1.0"})

    # Step 1 — ping
    if not ping(session):
        print("\nERROR: OpenAlgo API not reachable. Is the server running?")
        sys.exit(1)

    # Step 2 — web login
    if not web_login(session):
        sys.exit(1)

    # Step 3 — watchlist
    if not manage_watchlist(session):
        sys.exit(1)

    # Step 4 — create job
    job_id = create_download_job(session)
    if not job_id:
        sys.exit(1)

    # Step 5 — poll
    final_status = poll_job(session, job_id)

    # Step 6 — stats (always show, even if job is still running)
    fetch_stats(session)

    print()
    if final_status == "completed":
        print("  Download complete. Data is stored in D:\\OPENALGO\\db\\historify.duckdb")
        print("  Access it via the Historify page: http://127.0.0.1:5000/historify")
    elif final_status == "interrupted":
        print("  Job is still running in the background.")
        print(f"  Check status at: http://127.0.0.1:5000/historify")
    print()


if __name__ == "__main__":
    main()
