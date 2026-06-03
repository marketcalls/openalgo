"""
OpenAlgo REST API benchmark.

Usage (key from env, not hardcoded):
    OPENALGO_APIKEY=xxxx python benchmark_api.py

Measures per-endpoint latency (min/p50/p95/p99/max), sequential throughput,
and probes the configured per-IP rate limit (429 ceiling).
"""
import os
import statistics
import threading
import time
from datetime import datetime, timedelta

import httpx

BASE = os.getenv("OPENALGO_BASE", "http://127.0.0.1:5000/api/v1")
APIKEY = os.environ["OPENALGO_APIKEY"]

today = datetime.now()
start_5d = (today - timedelta(days=5)).strftime("%Y-%m-%d")
end_today = today.strftime("%Y-%m-%d")

client = httpx.Client(timeout=30.0)

ENDPOINTS = {
    "intervals":   {},
    "quotes":      {"symbol": "RELIANCE", "exchange": "NSE"},
    "history":     {"symbol": "RELIANCE", "exchange": "NSE", "interval": "5m",
                    "start_date": start_5d, "end_date": end_today},
    "multiquotes": {"symbols": [{"symbol": "RELIANCE", "exchange": "NSE"},
                                {"symbol": "TCS", "exchange": "NSE"},
                                {"symbol": "INFY", "exchange": "NSE"}]},
}


def call(path, body):
    t0 = time.time()
    r = client.post(f"{BASE}/{path}", json={"apikey": APIKEY, **body})
    dt = (time.time() - t0) * 1000
    ok = False
    try:
        ok = r.status_code == 200 and r.json().get("status") == "success"
    except Exception:
        pass
    return r.status_code, dt, ok


def pct(vals, p):
    s = sorted(vals)
    k = max(0, min(len(s) - 1, int(round((p / 100) * (len(s) - 1)))))
    return s[k]


print("=" * 74)
print(f"OpenAlgo API benchmark   base={BASE}   key=...{APIKEY[-6:]}")
print(f"history window: {start_5d} .. {end_today}")
print("=" * 74)

# --- Latency / sequential throughput ---------------------------------------
print("\nLATENCY (sequential)            min     p50     p95     p99     max   ok/n   thru")
print("-" * 74)
SAMPLES = {"intervals": 30, "quotes": 10, "history": 10, "multiquotes": 8}
for ep, body in ENDPOINTS.items():
    n = SAMPLES[ep]
    times, ok = [], 0
    t0 = time.time()
    for _ in range(n):
        code, dt, good = call(ep, body)
        times.append(dt)
        ok += good
    wall = time.time() - t0
    print(f"  {ep:<14} {min(times):7.1f} {pct(times,50):7.1f} {pct(times,95):7.1f} "
          f"{pct(times,99):7.1f} {max(times):7.1f}  {ok:>2}/{n:<2}  {n/wall:5.2f}/s")

# --- Rate-limit probe (against fast JSON endpoint) -------------------------
print("\nRATE LIMIT  (concurrent burst on /intervals; configured 50/s per IP)")
print("-" * 74)


def burst(n):
    res = [None] * n

    def fire(i):
        try:
            r = client.post(f"{BASE}/intervals", json={"apikey": APIKEY})
            res[i] = r.status_code
        except Exception:
            res[i] = "ERR"

    ts = [threading.Thread(target=fire, args=(i,)) for i in range(n)]
    t0 = time.time()
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    wall = time.time() - t0
    ok = sum(1 for c in res if c == 200)
    rl = sum(1 for c in res if c == 429)
    other = sorted({str(c) for c in res if c not in (200, 429)})
    print(f"  burst {n:>3} in {wall:5.3f}s ({n/wall:5.1f} req/s admit) "
          f"-> 200={ok:>3}  429={rl:>3}" + (f"  other={other}" if other else ""))


for n in (50, 100, 200):
    burst(n)
    time.sleep(2)

client.close()
print("\nDone.")
