"""Check that a broker's master contract holds every Nifty 500 stock under its OpenAlgo symbol.

OpenAlgo's equity symbol is the exchange's base symbol (docs/prompt/symbol-format.md),
which is exactly the Symbol column of NSE's index constituent list. A master
contract that stores anything else for a constituent leaves a trader who pastes
the list (Historify bulk add, a watchlist, a scanner universe) short by those
symbols, with nothing to say why. The case that prompted this check: Zerodha
stored HFCL-BE and EMBASSY-RR, Kite's tradingsymbols for stocks traded in the BE
and RR series, so 495 of the Nifty 500 were found and five were not.

Two sources:

* the live table (default): the symtoken rows the logged-in broker's master
  contract download wrote. Log in to the broker first.
* --rows-csv FILE: a CSV with symbol, brsymbol and exchange columns, for
  checking a plugin's processing before anything is written, for example
  ``process_<broker>_csv(path).to_csv("rows.csv", index=False)``.

The constituent list is downloaded from NSE, or read from --nifty-csv. Rows NSE
marks as placeholders (an ISIN beginning DUM, such as DUMMYHEG) are reported
and skipped: they are not listed instruments.

Prints NIFTY 500 COMPLETE and exits 0 when every constituent is found exactly
once on NSE; otherwise lists each one that is not, with what the master
contract holds instead, and exits 1.

Usage (from the repository root):
    uv run python .claude/skills/broker-integration/scripts/check_nifty500.py
    uv run python .claude/skills/broker-integration/scripts/check_nifty500.py --rows-csv rows.csv
    uv run python .claude/skills/broker-integration/scripts/check_nifty500.py --nifty-csv ind_nifty500list.csv
"""

from __future__ import annotations

import argparse
import csv
import io
import sqlite3
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
NIFTY500_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
# NSE's archive refuses requests without a browser-like User-Agent.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
)


def load_constituents(nifty_csv: str | None) -> list[dict[str, str]]:
    """The constituent rows: Company Name, Industry, Symbol, Series, ISIN Code."""
    if nifty_csv:
        text = Path(nifty_csv).read_text(encoding="utf-8-sig")
    else:
        request = urllib.request.Request(
            NIFTY500_URL, headers={"User-Agent": USER_AGENT, "Accept": "text/csv,*/*"}
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                text = response.read().decode("utf-8-sig")
        except OSError as exc:
            sys.exit(
                f"Could not download the Nifty 500 list from NSE ({exc}). Download "
                f"{NIFTY500_URL} in a browser and pass it with --nifty-csv."
            )
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows or "Symbol" not in rows[0]:
        sys.exit("The Nifty 500 file has no Symbol column. Is it ind_nifty500list.csv?")
    return rows


def load_master(db: Path, rows_csv: str | None) -> tuple[list[tuple[str, str, str]], str]:
    """(symbol, brsymbol, exchange) rows and a label saying where they came from."""
    if rows_csv:
        with open(rows_csv, encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = {"symbol", "brsymbol", "exchange"} - set(reader.fieldnames or [])
            if missing:
                sys.exit(f"{rows_csv} needs the columns symbol, brsymbol and exchange.")
            rows = [(r["symbol"], r["brsymbol"], r["exchange"]) for r in reader]
        return rows, rows_csv

    if not db.exists():
        sys.exit(f"{db} does not exist. Log in to the broker first, or pass --rows-csv.")
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT symbol, brsymbol, exchange FROM symtoken").fetchall()
        try:
            brokers = sorted({b for (b,) in conn.execute("SELECT broker FROM auth")})
        except sqlite3.Error:
            brokers = []
    finally:
        conn.close()
    label = f"{db} symtoken" + (f" (broker: {', '.join(brokers)})" if brokers else "")
    return rows, label


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", default=str(ROOT / "db" / "openalgo.db"))
    parser.add_argument("--rows-csv", help="symbol,brsymbol,exchange rows to check instead")
    parser.add_argument("--nifty-csv", help="a saved ind_nifty500list.csv instead of downloading")
    args = parser.parse_args()

    constituents = load_constituents(args.nifty_csv)
    master, source = load_master(Path(args.db), args.rows_csv)

    nse_count: dict[str, int] = defaultdict(int)
    by_brsymbol: dict[str, list[str]] = defaultdict(list)
    nse_rows = []
    other_exchanges: dict[str, set[str]] = defaultdict(set)
    for symbol, brsymbol, exchange in master:
        if exchange == "NSE":
            nse_count[symbol] += 1
            by_brsymbol[brsymbol].append(symbol)
            nse_rows.append((symbol, brsymbol))
        else:
            other_exchanges[symbol].add(exchange)

    placeholders = [r for r in constituents if r.get("ISIN Code", "").startswith("DUM")]
    listed = [r for r in constituents if r not in placeholders]

    missing, duplicated = [], []
    for row in listed:
        symbol = row["Symbol"].strip().upper()
        if nse_count.get(symbol, 0) == 0:
            missing.append(row)
        elif nse_count[symbol] > 1:
            duplicated.append(symbol)

    print(f"Master contract: {source}, {len(nse_rows)} NSE rows")
    print(
        f"Nifty 500 list: {len(constituents)} rows, {len(listed)} listed"
        + (
            f", {len(placeholders)} NSE placeholder(s) skipped: "
            + ", ".join(f"{r['Symbol']} ({r.get('Company Name', '')})" for r in placeholders)
            if placeholders
            else ""
        )
    )
    print(f"Found on NSE: {len(listed) - len(missing) - len(duplicated)} of {len(listed)}")

    for row in missing:
        symbol = row["Symbol"].strip().upper()
        prefix = symbol + "-"
        near = sorted(
            {
                f"symbol {s} (brsymbol {b})"
                for s, b in nse_rows
                if s.startswith(prefix) or b.startswith(prefix)
            }
            | {f"symbol {s} (brsymbol {symbol})" for s in by_brsymbol.get(symbol, [])}
        )
        print(
            f"\nNOT FOUND  {symbol}  (Series {row.get('Series', '?')}, {row.get('Company Name', '')})"
        )
        if near:
            print(f"  NSE holds: {'; '.join(near[:4])}")
            print(
                "  Fix the master contract: the OpenAlgo symbol is the base symbol "
                f"{symbol}; the broker's tradingsymbol belongs in brsymbol only."
            )
        elif symbol in other_exchanges:
            print(
                f"  Only on: {', '.join(sorted(other_exchanges[symbol]))}. Check the exchange mapping."
            )
        else:
            print(
                "  No NSE row carries this symbol. Check that the broker's NSE cash "
                "segment is loaded in full and that the symbol has not been renamed."
            )

    for symbol in duplicated:
        print(f"\nDUPLICATED  {symbol}: {nse_count[symbol]} NSE rows share this symbol.")

    if missing or duplicated:
        print(f"\nNIFTY 500 INCOMPLETE: {len(missing)} not found, {len(duplicated)} duplicated")
        return 1
    print("\nNIFTY 500 COMPLETE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
