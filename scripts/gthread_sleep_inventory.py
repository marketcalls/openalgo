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


# Reviewed baseline, matching tracker rows GT-B2-01/02/03. These are the
# numbers the thread budget in the plan was derived from; if they move, the
# budget must be re-derived rather than the numbers quietly updated.
EXPECTED = {
    "request-path": 111,
    "streaming-thread": 78,
    "background-download": 5,
    "total": 194,
    "budget": 111,
}


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
    budget = counts["request-path"] + counts["other"]
    print(f"\nthread-budget term (request-path + other) = {budget}")

    # The gate. Without this the script always exited 0, so CI's claim that
    # "a drifted sleep inventory fails the gate" was false and a broker change
    # could silently move the thread budget. Drift is not automatically wrong;
    # it must be re-reviewed and the baseline updated deliberately.
    drift = [
        (name, expected, actual)
        for name, expected, actual in (
            ("request-path sites", EXPECTED["request-path"], counts["request-path"]),
            ("streaming-thread sites", EXPECTED["streaming-thread"], counts["streaming-thread"]),
            ("background-download sites", EXPECTED["background-download"], counts["background-download"]),
            ("total sites", EXPECTED["total"], total),
            ("thread-budget term", EXPECTED["budget"], budget),
        )
        if expected != actual
    ]
    if drift:
        print("\nFAIL: sleep inventory drifted from the reviewed baseline")
        for name, expected, actual in drift:
            print(f"  {name}: expected {expected}, found {actual}")
        print(
            "\nA broker change moved the thread budget. Re-review the affected\n"
            "files, update tracker rows GT-B2-01/02/03, then update EXPECTED\n"
            f"in {__file__.rsplit('/', 1)[-1]}."
        )
        return 1

    print("baseline OK: inventory matches tracker rows GT-B2-01/02/03")
    return 0


if __name__ == "__main__":
    sys.exit(main())
