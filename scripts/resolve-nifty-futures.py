#!/usr/bin/env python3
"""Resolve NIFTY 50 constituent single-stock futures from OpenAlgo NFO instruments.

Usage:
    python scripts/resolve-nifty-futures.py --host http://127.0.0.1:5000 --api-key KEY

Downloads GET /api/v1/instruments?exchange=NFO&format=json, exact-matches each
CSV ticker by `name == NSE_Symbol` and `instrumenttype == "FUT"`, selects a
common monthly expiry, and writes a runtime contract map to
.tmp/nifty-futures-map-YYYY-MM-DD.json.

The contract map is consumed by the OpenAlgo depth data queue and the strategy.
No futures symbol is constructed by string concatenation.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = REPO_ROOT / "config" / "nifty50" / "nifty_50_weightage_2026-07-31.csv"
OUTPUT_DIR = REPO_ROOT / ".tmp"

MIN_SESSIONS_TO_EXPIRY = 5
MIN_RAW_WEIGHT_PTS = 90.0
TOP_N_REQUIRED = 10


def load_csv(path: Path) -> list[dict]:
    import csv
    rows: list[dict] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def fetch_nfo_instruments(host: str, api_key: str) -> list[dict]:
    url = f"{host.rstrip('/')}/api/v1/instruments"
    resp = requests.get(url, params={"apikey": api_key, "exchange": "NFO", "format": "json"}, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "success":
        raise RuntimeError(f"Instruments API failed: {data.get('message', data.get('status'))}")
    return data.get("data", [])


def parse_expiry(exp_str: str) -> date | None:
    """Parse DD-MMM-YY (e.g. 25-AUG-26) into a date."""
    if not exp_str:
        return None
    for fmt in ("%d-%b-%y", "%d-%B-%y", "%d-%b-%Y", "%d-%B-%Y"):
        try:
            return datetime.strptime(exp_str.upper(), fmt).date()
        except ValueError:
            continue
    return None


def group_futures_by_underlying(instruments: list[dict]) -> dict[str, list[dict]]:
    """Group NFO FUT records by canonical underlying name."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for inst in instruments:
        if inst.get("instrumenttype", "").upper() != "FUT":
            continue
        if inst.get("exchange", "").upper() != "NFO":
            continue
        name = (inst.get("name") or "").strip().upper()
        if name:
            grouped[name].append(inst)
    return grouped


def select_common_expiry(
    csv_rows: list[dict],
    grouped: dict[str, list[dict]],
    today: date,
) -> tuple[str | None, dict[str, dict], list[str]]:
    """Select the earliest common monthly expiry meeting all gates.

    Returns (expiry_str, resolved_map, excluded_symbols).
    """
    # Collect all distinct expiries across all mapped constituents
    all_expiries: set[str] = set()
    for records in grouped.values():
        for r in records:
            exp = r.get("expiry")
            if exp:
                all_expiries.add(exp)

    # Sort by parsed date
    parsed = [(e, parse_expiry(e)) for e in all_expiries]
    parsed = [(e, d) for e, d in parsed if d is not None and d >= today]
    parsed.sort(key=lambda x: x[1])

    for exp_str, exp_date in parsed:
        # Need at least MIN_SESSIONS_TO_EXPIRY full sessions remaining
        sessions_remaining = _count_sessions(today, exp_date)
        if sessions_remaining < MIN_SESSIONS_TO_EXPIRY:
            continue

        resolved, raw_weight, top_n_present = _resolve_expiry_contracts(
            csv_rows, grouped, exp_str
        )

        if raw_weight >= MIN_RAW_WEIGHT_PTS and top_n_present == TOP_N_REQUIRED:
            excluded = [
                row["NSE_Symbol"].strip().upper()
                for row in csv_rows
                if row["NSE_Symbol"].strip().upper() not in resolved
            ]
            return exp_str, resolved, excluded

    return None, {}, [r["NSE_Symbol"] for r in csv_rows]


def _resolve_expiry_contracts(
    csv_rows: list[dict],
    grouped: dict[str, list[dict]],
    expiry: str,
) -> tuple[dict[str, dict], float, int]:
    resolved: dict[str, dict] = {}
    raw_weight = 0.0
    top_n_present = 0

    for row in csv_rows:
        symbol = row["NSE_Symbol"].strip().upper()
        weight = float(row.get("Weight_Percent", 0))
        rank = int(row.get("Rank", 999))
        matching = [record for record in grouped.get(symbol, []) if record.get("expiry") == expiry]
        if not matching:
            continue

        instrument = matching[0]
        resolved[symbol] = {
            "openalgo_symbol": instrument.get("symbol"),
            "broker_symbol": instrument.get("brsymbol"),
            "broker_exchange": instrument.get("brexchange"),
            "token": instrument.get("token"),
            "expiry": expiry,
            "lotsize": instrument.get("lotsize"),
            "tick_size": instrument.get("tick_size"),
            "weight_percent": weight,
            "rank": rank,
        }
        raw_weight += weight
        if rank <= TOP_N_REQUIRED:
            top_n_present += 1

    return resolved, raw_weight, top_n_present


def _count_sessions(start: date, end: date) -> int:
    """Rough session count: weekdays between start and end (excludes holidays)."""
    days = (end - start).days
    weeks = days // 7
    remaining = days % 7
    weekdays = weeks * 5
    for i in range(1, remaining + 1):
        d = start + timedelta(days=i)
        if d.weekday() < 5:
            weekdays += 1
    return weekdays


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve NIFTY 50 constituent futures")
    parser.add_argument("--host", default="http://127.0.0.1:5000", help="OpenAlgo host URL")
    parser.add_argument("--api-key", required=True, help="OpenAlgo API key")
    parser.add_argument("--csv", default=str(DEFAULT_CSV), help="Path to weightage CSV")
    parser.add_argument("--output", default=None, help="Output JSON path")
    parser.add_argument("--dry-run", action="store_true", help="Don't write output file")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"❌ CSV not found: {csv_path}")
        return 1

    csv_rows = load_csv(csv_path)
    print(f"Loaded {len(csv_rows)} constituents from {csv_path.name}")

    print(f"Fetching NFO instruments from {args.host}...")
    instruments = fetch_nfo_instruments(args.host, args.api_key)
    print(f"  Got {len(instruments)} NFO instruments")

    grouped = group_futures_by_underlying(instruments)
    print(f"  Grouped into {len(grouped)} underlyings with FUT records")

    today = date.today()
    exp_str, resolved, excluded = select_common_expiry(csv_rows, grouped, today)

    if exp_str is None:
        print("❌ No common expiry passed all gates (≥90 raw weight, all top-10, ≥5 sessions)")
        print(f"   Excluded: {excluded}")
        return 1

    raw_weight = sum(v["weight_percent"] for v in resolved.values())
    normalized = {k: {**v, "normalized_weight": v["weight_percent"] / raw_weight} for k, v in resolved.items()}

    source_weight_total = sum(float(row.get("Weight_Percent", 0)) for row in csv_rows)
    output: dict[str, Any] = {
        "resolved_date": today.isoformat(),
        "source_csv": csv_path.name,
        "common_expiry": exp_str,
        "resolved_count": len(resolved),
        "excluded_symbols": excluded,
        "raw_weight_covered": round(raw_weight, 2),
        "source_weight_total": round(source_weight_total, 2),
        "missing_source_weight": round(100.0 - source_weight_total, 2),
        "contracts": normalized,
    }

    print(f"\n✅ Common expiry: {exp_str}")
    print(f"   Resolved: {len(resolved)} contracts ({raw_weight:.2f}% raw weight)")
    print(f"   Excluded: {len(excluded)} symbols")

    if not args.dry_run:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = Path(args.output) if args.output else OUTPUT_DIR / f"nifty-futures-map-{today.isoformat()}.json"
        out_path.write_text(json.dumps(output, indent=2))
        print(f"   Written: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
