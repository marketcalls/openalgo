"""Retry only the PE samples that hit rate limit, then merge into baseline JSON."""
import json
import os
import sys
import time
import urllib.request

API_KEY = os.environ.get("OPENALGO_API_KEY")
if not API_KEY:
    sys.exit("Set OPENALGO_API_KEY before running this benchmark.")
URL = "http://127.0.0.1:5000/api/v1/optiongreeks"
PATH = "docs/benchmarks/greeks_baseline_pyvollib.json"

with open(PATH) as f:
    data = json.load(f)

failed = [r for r in data["samples"] if r["response"].get("status") != "success"]
print(f"Retrying {len(failed)} samples at 1 req/sec...")

for r in failed:
    body = json.dumps({"apikey": API_KEY, "exchange": "NFO", "symbol": r["symbol"]}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        payload = json.loads(e.read().decode())
    dt_ms = (time.perf_counter() - t0) * 1000.0
    r["response"] = payload
    r["latency_ms"] = round(dt_ms, 2)
    print(f"{r['type']} {r['strike']:>5} {r['moneyness']:<9} {dt_ms:6.1f} ms  status={payload.get('status')}")
    time.sleep(1.1)

with open(PATH, "w") as f:
    json.dump(data, f, indent=2)
print(f"\nMerged → {PATH}")
