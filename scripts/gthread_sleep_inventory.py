#!/usr/bin/env python3
"""Reproducible blocking-sleep inventory for the gthread migration.

Classifies every blocking sleep under broker/ by whether it occupies a
Gunicorn request thread. Run: uv run python scripts/gthread_sleep_inventory.py
"""

import ast
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
SLEEPERS = {("time", "sleep"), ("asyncio", "sleep"), ("eventlet", "sleep")}


def classify(path: pathlib.Path) -> str:
    p = path.as_posix()
    if "/streaming/" in p or "websocket" in path.name.lower():
        return "streaming-thread"
    if path.name == "master_contract_db.py":
        return "background-download"
    if "/api/" in p:
        return "request-path"
    return "other"


def sleep_calls(path: pathlib.Path) -> int:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return 0
    n = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            if (f.value.id, f.attr) in SLEEPERS:
                n += 1
        elif isinstance(f, ast.Name) and f.id == "sleep":
            n += 1
    return n


def main() -> int:
    counts, files = Counter(), Counter()
    for path in sorted((ROOT / "broker").rglob("*.py")):
        n = sleep_calls(path)
        if n:
            c = classify(path)
            counts[c] += n
            files[c] += 1

    total = sum(counts.values())
    print(f"{'category':<22}{'sites':>7}{'files':>7}  holds a request thread?")
    for c in ("request-path", "other", "streaming-thread", "background-download"):
        holds = "YES" if c in ("request-path", "other") else "no"
        print(f"{c:<22}{counts[c]:>7}{files[c]:>7}  {holds}")
    print(f"{'TOTAL':<22}{total:>7}{sum(files.values()):>7}")
    print(f"\nthread-budget term (request-path + other) = {counts['request-path'] + counts['other']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
