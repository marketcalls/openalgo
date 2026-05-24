"""
Indian broker Python SDK — last-month download stats from PyPI.

Compares the official broker SDKs available on PyPI to give a rough
proxy for community adoption of programmatic-trading clients across
the Indian broker landscape.

Usage:
    pip install pypistats
    python broker_sdk_downloads.py

Notes:
- `pypistats.org` rate-limits to ~1 req/sec per IP; on a cold cache the
  script may need up to a minute total. The retry loop handles HTTP 429
  with widening cooldowns (30s -> 60s -> 90s) so the run does not need
  manual restarts.
- "Last month" is a rolling 30-day window reported by pypistats.org.
- The list is broker-native SDKs (one per broker). OpenAlgo is included
  as the only broker-agnostic abstraction layer in the comparison.
"""

import json
import time

import pypistats

BROKERS = [
    ("Zerodha",      "kiteconnect"),
    ("Angel One",    "smartapi-python"),
    ("Upstox",       "upstox-python-sdk"),
    ("Fyers",        "fyers-apiv3"),
    ("Dhan",         "dhanhq"),
    ("Groww",        "growwapi"),
    ("ICICI Breeze", "breeze-connect"),
    ("5paisa",       "py5paisa"),
    ("OpenAlgo",     "openalgo"),
]


def fetch_last_month(pkg: str, *, max_retries: int = 4, cooldown_sec: int = 30) -> int | None:
    """Return last-month downloads for ``pkg``, retrying on HTTP 429.

    Args:
        pkg: PyPI package name (e.g. "openalgo").
        max_retries: Total attempts before giving up.
        cooldown_sec: Base wait between retries (multiplied by attempt index).

    Returns:
        Last-month download count as int, or None if every attempt fails.
    """
    for attempt in range(max_retries):
        try:
            payload = json.loads(pypistats.recent(pkg, format="json"))
            return int(payload["data"]["last_month"])
        except Exception as exc:
            msg = str(exc)
            if "429" in msg and attempt < max_retries - 1:
                wait = cooldown_sec * (attempt + 1)   # 30s, 60s, 90s
                print(f"  {pkg:25s} rate-limited; cooling down {wait}s...")
                time.sleep(wait)
                continue
            print(f"  {pkg:25s} ERROR after {attempt + 1} attempts: {exc}")
            return None
    return None


def main() -> None:
    results: list[tuple[str, str, int | None]] = []
    for broker, pkg in BROKERS:
        print(f"fetching {broker:15s} ({pkg})...")
        results.append((broker, pkg, fetch_last_month(pkg)))
        time.sleep(2)         # be polite to the pypistats API between calls

    # Sort by downloads descending; missing values pushed to the bottom
    results.sort(key=lambda r: (r[2] is None, -(r[2] or 0)))

    print()
    print(f"{'Rank':>4}  {'Broker':<15} {'PyPI Package':<25} {'Last Month':>12}")
    print(f"{'-' * 4}  {'-' * 15} {'-' * 25} {'-' * 12}")
    for rank, (broker, pkg, downloads) in enumerate(results, 1):
        amount = f"{downloads:,}" if downloads is not None else "n/a"
        marker = "  <-- this project" if pkg == "openalgo" else ""
        print(f"{rank:>4}  {broker:<15} {pkg:<25} {amount:>12}{marker}")


if __name__ == "__main__":
    main()
