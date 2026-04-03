"""
Live test for Multi Option Greeks API.

Tests the /api/v1/multioptiongreeks endpoint against a running OpenAlgo
instance with any connected broker.

Prerequisites:
    1. OpenAlgo must be running at http://127.0.0.1:5000
    2. Any broker must be connected
    3. Markets should be open

Usage:
    cd openalgo
    uv run python test/test_greeks_live.py
"""

import json
import sys
import time

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests

# Configuration
BASE_URL = "http://127.0.0.1:5000"
API_KEY = "7653f710c940cdf1d757b5a7d808a60f43bc7e9c0239065435861da2869ec0fc"

# Underlying and expiry — update as needed
UNDERLYING = "NIFTY"
UNDERLYING_EXCHANGE = "NSE_INDEX"
OPTIONS_EXCHANGE = "NFO"
EXPIRY = "30MAR26"
STRIKE_INTERVAL = 50  # NIFTY=50, BANKNIFTY=100


def api_call(endpoint, payload):
    start = time.time()
    resp = requests.post(f"{BASE_URL}{endpoint}", json=payload)
    elapsed = time.time() - start
    return resp.status_code, resp.json(), elapsed


def print_header(title):
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def get_atm_strike():
    payload = {"apikey": API_KEY, "symbol": UNDERLYING, "exchange": UNDERLYING_EXCHANGE}
    status, data, elapsed = api_call("/api/v1/quotes", payload)
    if status == 200 and data.get("status") == "success":
        ltp = data.get("data", {}).get("ltp", 0)
        atm = round(ltp / STRIKE_INTERVAL) * STRIKE_INTERVAL
        return ltp, atm
    return None, None


def build_symbols(atm, strike_count=10):
    strikes = [atm + (i * STRIKE_INTERVAL) for i in range(-strike_count, strike_count + 1)]
    symbols = []
    for strike in strikes:
        symbols.append({"symbol": f"{UNDERLYING}{EXPIRY}{strike}CE", "exchange": OPTIONS_EXCHANGE})
        symbols.append({"symbol": f"{UNDERLYING}{EXPIRY}{strike}PE", "exchange": OPTIONS_EXCHANGE})
    return symbols, strikes


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("  Multi Option Greeks — Live Test")
    print(f"  Server: {BASE_URL}")
    print(f"  Underlying: {UNDERLYING} ({UNDERLYING_EXCHANGE}) | Expiry: {EXPIRY}")
    print("=" * 70)

    # Get ATM
    print("\n  Fetching underlying LTP...")
    ltp, atm = get_atm_strike()
    if not atm:
        print("  FATAL: Cannot fetch LTP. Is OpenAlgo running and broker connected?")
        sys.exit(1)
    print(f"  {UNDERLYING} LTP: {ltp} | ATM: {atm}")

    # ── Test 1: Full chain (42 symbols) ──────────────────────────
    symbols, strikes = build_symbols(atm, strike_count=10)

    print_header(f"TEST 1: Full Chain ({len(symbols)} symbols)")

    payload = {"apikey": API_KEY, "symbols": symbols, "interest_rate": 7.0}
    print(f"  Strikes: {strikes[0]} to {strikes[-1]} ({len(strikes)} strikes x CE+PE)")

    status, result, elapsed = api_call("/api/v1/multioptiongreeks", payload)
    summary = result.get("summary", {})

    print(f"\n  HTTP: {status} | Time: {elapsed:.3f}s")
    print(f"  Status: {result.get('status')} | Success: {summary.get('success', 0)}/{summary.get('total', 0)} | Failed: {summary.get('failed', 0)}")

    data = result.get("data", [])
    rate_limited = [d for d in data if "429" in str(d.get("message", "")).lower()
                    or "too many" in str(d.get("message", "")).lower()]
    if rate_limited:
        print(f"  WARNING: {len(rate_limited)} symbols hit 429!")
    else:
        print(f"  No 429 errors!")

    # Show ATM and nearby
    successful = [d for d in data if d.get("status") == "success"]
    if successful:
        print(f"\n  {'Symbol':30s} {'Type':>5s} {'Strike':>8s} {'LTP':>8s} {'IV%':>8s} {'Delta':>8s} {'Theta':>8s} {'Vega':>8s}")
        print(f"  {'-' * 95}")
        for item in successful:
            if abs(item.get("strike", 0) - atm) <= STRIKE_INTERVAL * 2:
                g = item.get("greeks", {})
                print(
                    f"  {item['symbol']:30s} "
                    f"{item['option_type']:>5s} "
                    f"{item['strike']:>8.0f} "
                    f"{item['option_price']:>8.2f} "
                    f"{item.get('implied_volatility', 0):>8.2f} "
                    f"{g.get('delta', 0):>8.4f} "
                    f"{g.get('theta', 0):>8.4f} "
                    f"{g.get('vega', 0):>8.4f}"
                )

    failed = [d for d in data if d.get("status") == "error"]
    if failed:
        print(f"\n  Failed ({len(failed)}):")
        for f in failed[:5]:
            print(f"    {f.get('symbol', '?')}: {f.get('message', '?')}")

    # ── Test 2: Rapid fire (3 back-to-back) ──────────────────────
    print_header("TEST 2: Rapid Fire (3 back-to-back requests)")

    small_symbols = symbols[:12]
    small_payload = {"apikey": API_KEY, "symbols": small_symbols, "interest_rate": 7.0}

    total_429 = 0
    for i in range(3):
        s, r, e = api_call("/api/v1/multioptiongreeks", small_payload)
        sm = r.get("summary", {})
        errs = [d for d in r.get("data", []) if "429" in str(d.get("message", "")).lower()]
        total_429 += len(errs)
        marker = "OK" if not errs else "429!"
        print(f"  Request {i+1}: {e:.3f}s | {sm.get('success', 0)}/{sm.get('total', 0)} success | 429: {len(errs)} [{marker}]")

    print(f"\n  Total 429 errors: {total_429}")

    # ── Test 3: Single vs Multi accuracy ─────────────────────────
    print_header("TEST 3: Single vs Multi Accuracy")

    test_symbol = f"{UNDERLYING}{EXPIRY}{atm}CE"

    _, s_result, s_elapsed = api_call("/api/v1/optiongreeks", {
        "apikey": API_KEY, "symbol": test_symbol, "exchange": OPTIONS_EXCHANGE, "interest_rate": 7.0,
    })
    _, m_result, m_elapsed = api_call("/api/v1/multioptiongreeks", {
        "apikey": API_KEY, "symbols": [{"symbol": test_symbol, "exchange": OPTIONS_EXCHANGE}], "interest_rate": 7.0,
    })

    print(f"\n  Symbol: {test_symbol}")
    print(f"  Single: {s_elapsed:.3f}s | Multi: {m_elapsed:.3f}s")

    if s_result.get("status") == "success" and m_result.get("data"):
        sg = s_result.get("greeks", {})
        md = m_result["data"][0]
        mg = md.get("greeks", {})

        print(f"\n  {'Metric':>12s} {'Single':>12s} {'Multi':>12s} {'Match':>8s}")
        print(f"  {'-' * 48}")
        for name, sv, mv in [
            ("IV%", s_result.get("implied_volatility", 0), md.get("implied_volatility", 0)),
            ("Delta", sg.get("delta", 0), mg.get("delta", 0)),
            ("Gamma", sg.get("gamma", 0), mg.get("gamma", 0)),
            ("Theta", sg.get("theta", 0), mg.get("theta", 0)),
            ("Vega", sg.get("vega", 0), mg.get("vega", 0)),
        ]:
            match = "OK" if abs(sv - mv) < 1.0 else "DIFF"
            print(f"  {name:>12s} {sv:>12.4f} {mv:>12.4f} {match:>8s}")
        print(f"\n  Note: Small differences expected due to LTP changes between calls")
    else:
        print(f"  Single: {s_result.get('status')} | Multi: {m_result.get('status')}")

    # ── Verdict ──────────────────────────────────────────────────
    print_header("VERDICT")
    all_pass = summary.get("success", 0) > 0 and total_429 == 0
    if all_pass:
        print(f"\n  PASS: {summary.get('success', 0)}/{summary.get('total', 0)} Greeks calculated, zero 429 errors")
    else:
        print(f"\n  FAIL: {total_429} rate limit errors detected")
    print("=" * 70)
