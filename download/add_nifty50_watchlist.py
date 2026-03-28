"""
Add all Nifty 50 symbols to OpenAlgo Historify watchlist,
then trigger full historical download jobs (1m + Daily).

Run with OpenAlgo server running:
    cd D:/openalgo
    uv run download/add_nifty50_watchlist.py
"""

import requests

BASE_URL  = "http://127.0.0.1:5000"
USERNAME  = input("OpenAlgo username: ").strip()
PASSWORD  = input("OpenAlgo password: ").strip()

NIFTY50 = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BPCL", "BHARTIARTL",
    "BRITANNIA", "CIPLA", "COALINDIA", "DIVISLAB", "DRREDDY",
    "EICHERMOT", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE",
    "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "ICICIBANK", "ITC",
    "INDUSINDBK", "INFY", "JSWSTEEL", "KOTAKBANK", "LT",
    "LTIM", "M&M", "MARUTI", "NESTLEIND", "NTPC",
    "ONGC", "POWERGRID", "RELIANCE", "SBILIFE", "SHRIRAMFIN",
    "SBIN", "SUNPHARMA", "TCS", "TATACONSUM", "TATAMOTORS",
    "TATASTEEL", "TECHM", "TITAN", "ULTRACEMCO", "WIPRO",
]

# ── Step 1: Login with session + CSRF ─────────────────────────────────────────
session = requests.Session()

# Get CSRF token
r = session.get(f"{BASE_URL}/auth/csrf-token")
csrf_token = r.json()["csrf_token"]
print(f"Got CSRF token")

# Login
r = session.post(
    f"{BASE_URL}/auth/login",
    json={"username": USERNAME, "password": PASSWORD},
    headers={"X-CSRFToken": csrf_token, "Content-Type": "application/json"},
)
if r.status_code not in (200, 302):
    print(f"Login failed: {r.status_code} {r.text[:200]}")
    exit(1)

# Refresh CSRF token after login
r = session.get(f"{BASE_URL}/auth/csrf-token")
csrf_token = r.json()["csrf_token"]
headers = {"X-CSRFToken": csrf_token, "Content-Type": "application/json"}
print(f"Logged in successfully\n")

# ── Step 2: Bulk add Nifty 50 to watchlist ─────────────────────────────────────
symbols = [{"symbol": s, "exchange": "NSE"} for s in NIFTY50]

print(f"Adding {len(symbols)} Nifty 50 symbols to Historify watchlist ...")
r = session.post(
    f"{BASE_URL}/historify/api/watchlist/bulk",
    json={"symbols": symbols},
    headers=headers,
)
data = r.json()
print(f"  Added  : {data.get('added', 0)}")
print(f"  Skipped: {data.get('skipped', 0)}")
if data.get("failed"):
    print(f"  Failed : {data['failed'][:5]}")

# ── Step 3: Start 1m download job (2015 → today) ──────────────────────────────
print("\nStarting 1m download job (2015-01-01 → today) ...")
r = session.post(
    f"{BASE_URL}/historify/api/jobs",
    json={
        "job_type": "watchlist",
        "symbols": symbols,
        "interval": "1m",
        "start_date": "2015-01-01",
        "end_date": "2099-12-31",
        "incremental": False,
    },
    headers=headers,
)
if r.ok:
    d = r.json()
    print(f"  Job ID : {d.get('job_id')}")
    print(f"  Status : {d.get('message')}")
else:
    print(f"  Failed : {r.status_code} {r.text[:300]}")

# ── Step 4: Start Daily download job (2000 → today) ───────────────────────────
# Refresh CSRF token before second POST
r = session.get(f"{BASE_URL}/auth/csrf-token")
csrf_token = r.json()["csrf_token"]
headers["X-CSRFToken"] = csrf_token

print("\nStarting Daily download job (2000-01-01 → today) ...")
r = session.post(
    f"{BASE_URL}/historify/api/jobs",
    json={
        "job_type": "watchlist",
        "symbols": symbols,
        "interval": "D",
        "start_date": "2000-01-01",
        "end_date": "2099-12-31",
        "incremental": False,
    },
    headers=headers,
)
if r.ok:
    d = r.json()
    print(f"  Job ID : {d.get('job_id')}")
    print(f"  Status : {d.get('message')}")
else:
    print(f"  Failed : {r.status_code} {r.text[:300]}")

print("\nMonitor live progress at: http://127.0.0.1:5000/historify")
print("1m download → gives you 1m/3m/5m/10m/15m/30m/1h automatically once done.")
