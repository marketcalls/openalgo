"""
Baseline benchmark: py_vollib-backed /api/v1/optiongreeks across 20 strikes (CE+PE).
Captures response + latency for later parity check against opengreeks.

Spot: NIFTY ~23659  Expiry: 26MAY26 (NFO)
"""
import json
import os
import sys
import time
import urllib.request

API_KEY = os.environ.get("OPENALGO_API_KEY")
if not API_KEY:
    sys.exit("Set OPENALGO_API_KEY before running this benchmark.")
URL = "http://127.0.0.1:5000/api/v1/optiongreeks"
EXPIRY = "26MAY26"
SPOT = 23659.0

STRIKES = [
    21000, 21500, 22000, 22500,
    23000, 23200, 23300, 23400, 23500,
    23600, 23650, 23700,
    23800, 23900, 24000, 24200, 24500,
    25000, 25500, 26000,
]


def classify(strike: float, spot: float, opt_type: str) -> str:
    diff = strike - spot
    if opt_type == "CE":
        if diff <= -1000: return "DEEP ITM"
        if diff < -100:   return "ITM"
        if abs(diff) <= 100: return "ATM"
        if diff < 1000:   return "OTM"
        return "DEEP OTM"
    else:  # PE
        if diff >= 1000:  return "DEEP ITM"
        if diff > 100:    return "ITM"
        if abs(diff) <= 100: return "ATM"
        if diff > -1000:  return "OTM"
        return "DEEP OTM"


def call_greeks(symbol: str) -> tuple[dict, float]:
    body = json.dumps({"apikey": API_KEY, "exchange": "NFO", "symbol": symbol}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        data = json.loads(e.read().decode())
    dt_ms = (time.perf_counter() - t0) * 1000.0
    return data, dt_ms


def run():
    rows = []
    for opt_type in ("CE", "PE"):
        for k in STRIKES:
            symbol = f"NIFTY{EXPIRY}{k}{opt_type}"
            resp, dt_ms = call_greeks(symbol)
            cls = classify(k, SPOT, opt_type)
            rows.append({
                "type": opt_type,
                "strike": k,
                "moneyness": cls,
                "symbol": symbol,
                "latency_ms": round(dt_ms, 2),
                "response": resp,
            })
            print(f"{opt_type} {k:>5} {cls:<9}  {dt_ms:6.1f} ms  status={resp.get('status')}")
    with open("docs/benchmarks/greeks_baseline_pyvollib.json", "w") as f:
        json.dump({
            "engine": "py_vollib==1.0.1 (Black-76)",
            "spot": SPOT,
            "expiry": EXPIRY,
            "samples": rows,
        }, f, indent=2)
    print(f"\nSaved {len(rows)} samples → docs/benchmarks/greeks_baseline_pyvollib.json")


if __name__ == "__main__":
    run()
