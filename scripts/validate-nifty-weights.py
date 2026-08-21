#!/usr/bin/env python3
"""Validate a NIFTY 50 weightage CSV snapshot.

Usage:
    python scripts/validate-nifty-weights.py [path/to/csv]

Defaults to config/nifty50/nifty_50_weightage_2026-07-31.csv.

Checks:
- Exactly 49 data rows (this snapshot), ranks 1-49 contiguous
- Unique NSE symbols, one As_Of date
- Positive finite weights, raw total 97.97
- Concentration checkpoints
- SHA-256 checksum against manifest
- Age gates (warn 35d, block 65d)
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import date, datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = REPO_ROOT / "config" / "nifty50" / "nifty_50_weightage_2026-07-31.csv"
MANIFEST_PATH = REPO_ROOT / "config" / "nifty50" / "manifest.json"

EXPECTED_ROW_COUNT = 49
EXPECTED_RAW_SUM = 97.97
EXPECTED_MISSING = 2.03
EXPECTED_CONCENTRATION = {
    "top_5": 36.91,
    "top_10": 52.89,
    "top_20": 71.40,
    "top_30": 82.93,
    "top_40": 91.88,
}
WARN_AFTER_DAYS = 35
BLOCK_AFTER_DAYS = 65
TOLERANCE = 0.01


class ValidationError(Exception):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_csv(path: Path) -> list[dict]:
    rows: list[dict] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def validate(path: Path) -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    if not path.exists():
        raise ValidationError(f"CSV not found: {path}")

    rows = parse_csv(path)
    if len(rows) != EXPECTED_ROW_COUNT:
        errors.append(f"Expected {EXPECTED_ROW_COUNT} data rows, got {len(rows)}")

    # Ranks contiguous 1..49
    ranks = []
    for i, row in enumerate(rows, start=1):
        try:
            rank = int(row.get("Rank", i))
        except (ValueError, TypeError):
            rank = i
        ranks.append(rank)
    expected_ranks = list(range(1, EXPECTED_ROW_COUNT + 1))
    if ranks != expected_ranks:
        errors.append(f"Ranks not contiguous 1-{EXPECTED_ROW_COUNT}: {ranks[:5]}...")

    # Unique symbols
    symbols = [r.get("NSE_Symbol", "").strip() for r in rows]
    dupes = [s for s in set(symbols) if symbols.count(s) > 1]
    if dupes:
        errors.append(f"Duplicate symbols: {dupes}")

    # Single As_Of date
    as_ofs = set(r.get("As_Of", "").strip() for r in rows)
    if len(as_ofs) != 1:
        errors.append(f"Expected one As_Of date, got {as_ofs}")
    as_of_str = as_ofs.pop() if as_ofs else ""

    # Positive finite weights
    weights: list[float] = []
    for row in rows:
        try:
            w = float(row.get("Weight_Percent", 0))
        except (ValueError, TypeError):
            w = 0.0
        if w <= 0 or not math_isfinite(w):
            errors.append(f"Invalid weight for {row.get('NSE_Symbol')}: {w}")
        weights.append(w)

    raw_sum = round(sum(weights), 2)
    if abs(raw_sum - EXPECTED_RAW_SUM) > TOLERANCE:
        errors.append(f"Raw weight sum {raw_sum} != expected {EXPECTED_RAW_SUM}")

    missing = round(100.0 - raw_sum, 2)
    if abs(missing - EXPECTED_MISSING) > TOLERANCE:
        errors.append(f"Missing weight {missing} != expected {EXPECTED_MISSING}")

    # Concentration
    for label, n in [("top_5", 5), ("top_10", 10), ("top_20", 20), ("top_30", 30), ("top_40", 40)]:
        partial = round(sum(weights[:n]), 2)
        expected = EXPECTED_CONCENTRATION[label]
        if abs(partial - expected) > TOLERANCE:
            errors.append(f"{label} = {partial}, expected {expected}")

    # Checksum
    checksum = sha256_file(path)
    if MANIFEST_PATH.exists():
        manifest = json.loads(MANIFEST_PATH.read_text())
        stored = manifest.get("sha256", "")
        if stored and stored != checksum:
            errors.append(f"Checksum mismatch: file={checksum}, manifest={stored}")
    else:
        warnings.append("No manifest.json found; skipping checksum verification")

    # Age gate
    if as_of_str:
        try:
            as_of_date = datetime.strptime(as_of_str, "%Y-%m-%d").date()
        except ValueError:
            errors.append(f"Cannot parse As_Of date: {as_of_str}")
            as_of_date = None
    else:
        as_of_date = None

    today = date.today()
    age_days = (today - as_of_date).days if as_of_date else 0
    if age_days > BLOCK_AFTER_DAYS:
        errors.append(f"Source is {age_days} days old (>{BLOCK_AFTER_DAYS}); live entries blocked")
    elif age_days > WARN_AFTER_DAYS:
        warnings.append(f"Source is {age_days} days old (>{WARN_AFTER_DAYS}); consider refresh")

    result = {
        "file": str(path),
        "row_count": len(rows),
        "raw_weight_sum": raw_sum,
        "missing_weight": missing,
        "concentration": {k: round(sum(weights[:n]), 2) for k, n in [("top_5", 5), ("top_10", 10), ("top_20", 20), ("top_30", 30), ("top_40", 40)]},
        "sha256": checksum,
        "as_of": as_of_str,
        "age_days": age_days,
        "errors": errors,
        "warnings": warnings,
    }
    return result


def math_isfinite(x: float) -> bool:
    import math
    return math.isfinite(x)


def main() -> int:
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CSV
    try:
        result = validate(csv_path)
    except ValidationError as e:
        print(f"FAIL: {e}")
        return 1

    print(json.dumps(result, indent=2))
    if result["errors"]:
        print(f"\n❌ {len(result['errors'])} error(s)")
        for e in result["errors"]:
            print(f"  - {e}")
        return 1
    if result["warnings"]:
        print(f"\n⚠️  {len(result['warnings'])} warning(s)")
        for w in result["warnings"]:
            print(f"  - {w}")
    print("\n✅ Weight snapshot valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
