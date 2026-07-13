#!/usr/bin/env python3
"""Reproducible Indian-coupling inventory for the global-market audit.

Pins the methodology so the audit's file counts are reproducible (addresses the
review finding that ad-hoc greps drifted). Run from the repo root:

    uv run python docs/superpowers/audit/coupling_inventory.py

FIRST-PASS SUBSET: scans 9 code dirs for *token* coupling only. P0A expands this
into an AST/schema inventory suite over all top-level folders + semantic coupling
(broker-name switches, int coercions, tz arithmetic, symbol parsing, migration
and WebSocket-registration assumptions).

Methodology (fixed):
  * SIGNAL = hard Indian-coupling tokens with word boundaries where the token is
    a word. Exchange codes (NSE/NFO/...) are tracked separately below because
    they appear pervasively and would dominate the signal.
  * Backend dirs are scanned for *.py only; frontend for *.ts/*.tsx only.
  * A file counts once if it matches SIGNAL at least once.
Output: JSON to stdout (commit-pinned), so counts can be diffed over time.
"""

import json
import re
import subprocess
from pathlib import Path

SIGNAL = re.compile(r"₹|\bINR\b|Asia/Kolkata|\bIST\b|\bCNC\b|\bNRML\b|\bMIS\b|\bSEBI\b|\bSPAN\b")
EXCHANGE_CODES = re.compile(r"\bNSE\b|\bNFO\b|\bBSE\b|\bBFO\b|\bMCX\b|\bCDS\b|\bBCD\b|\bNCO\b")

TARGETS = [
    ("broker", (".py",)),
    ("services", (".py",)),
    ("blueprints", (".py",)),
    ("restx_api", (".py",)),
    ("database", (".py",)),
    ("utils", (".py",)),
    ("sandbox", (".py",)),
    ("test", (".py",)),
    ("frontend/src", (".ts", ".tsx")),
]


def scan(dir_: str, exts: tuple[str, ...]) -> dict:
    root = Path(dir_)
    signal_hits, exchange_hits = [], []
    if root.exists():
        for p in root.rglob("*"):
            if p.suffix not in exts or not p.is_file():
                continue
            try:
                text = p.read_text(errors="ignore")
            except OSError:
                continue
            if SIGNAL.search(text):
                signal_hits.append(str(p))
            if EXCHANGE_CODES.search(text):
                exchange_hits.append(str(p))
    return {"ext": list(exts), "signal_files": len(signal_hits), "exchange_code_files": len(exchange_hits)}


def main() -> None:
    rev = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    out = {
        "commit": rev,
        "signal_pattern": SIGNAL.pattern,
        "exchange_pattern": EXCHANGE_CODES.pattern,
        "counts": {d: scan(d, exts) for d, exts in TARGETS},
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
