#!/usr/bin/env python
"""
EOD backtest for iron_condor_daily.py against real NSE settlement data.

Pulls NSE's public daily F&O bhavcopy (one file per trading day, contains
every strike/expiry's Open/High/Low/Close/Settlement for that day - this is
NSE's own official record, not a broker feed) for NIFTY and BANKNIFTY index
options over a date range, resolves the same OTM6-hedge / OTM4-short legs
the live strategy uses, and sums up what selling that spread would have
made or lost each day.

HONESTY ABOUT WHAT THIS DOES AND DOESN'T PROVE:
NSE's daily bhavcopy has one Open/High/Low/Close per contract per day - not
a full intraday tick history. That means this backtest can faithfully
answer "what if you entered at the day's open and held to the day's close"
(no intraday exit at all), but it CANNOT faithfully simulate the live
script's actual intraday profit-target / stop-loss logic - those trigger at
a specific mark-to-market moment during the day, and reconstructing that
from four independent daily High/Low ranges would silently assume all four
legs hit their extreme at the same instant, which is not something the data
supports. So this script reports two numbers, clearly separated:
  1. Open-to-close P&L (the trustworthy one - directly backed by settlement
     data)
  2. A rough intraday sensitivity band using each day's High/Low (a loose
     "how much did it move" indicator, NOT a stop-loss simulation)
Treat (1) as the honest backtest and (2) as a hint, not a promise.

Requires only the Python standard library (urllib, zipfile, csv) - no
broker connection needed, this is pure historical NSE data.
"""
import csv
import io
import json
import os
import statistics
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, timedelta

# ---------------------------------------------------------------------------
# Config - keep in sync with strategies/examples/iron_condor_daily.py
# ---------------------------------------------------------------------------
UNDERLYINGS = ["NIFTY", "BANKNIFTY"]
HEDGE_OFFSET = 6   # strikes away from ATM for the long (insurance) legs
SHORT_OFFSET = 4   # strikes away from ATM for the short (premium) legs
PROFIT_TARGET_CREDIT_FRACTION = 0.5
STOP_LOSS_CREDIT_MULTIPLE = 1.0

START_DATE = date.today() - timedelta(days=90)
END_DATE = date.today() - timedelta(days=1)

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".bhavcopy_cache")
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
BHAVCOPY_URL = "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{yyyymmdd}_F_0000.csv.zip"


def fetch_bhavcopy(day):
    """Return list of dict rows for one trading day, or None if no data (holiday/weekend)."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(CACHE_DIR, f"{day.isoformat()}.csv")
    if os.path.exists(cache_path):
        with open(cache_path, newline="") as f:
            return list(csv.DictReader(f))

    url = BHAVCOPY_URL.format(yyyymmdd=day.strftime("%Y%m%d"))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None  # holiday or weekend - NSE simply has no file
        raise

    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        inner_name = zf.namelist()[0]
        with zf.open(inner_name) as f:
            text = io.TextIOWrapper(f, encoding="utf-8")
            rows = list(csv.DictReader(text))

    with open(cache_path, "w", newline="") as f:
        if rows:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
    return rows


# Exchange-fixed strike intervals. NOT auto-detected from the day's strike ladder:
# NSE lists extra intermediate strikes near spot on high-volume days (tighter than
# the nominal interval), which made a "most common gap" heuristic pick the wrong,
# too-small value on some days - that silently broke the OTM-offset spacing the
# whole strategy (and its defined max loss) depends on. These two are exchange
# constants and haven't changed in years; update here if NSE revises them.
STRIKE_INTERVALS = {"NIFTY": 50.0, "BANKNIFTY": 100.0}


def strike_interval(underlying):
    return STRIKE_INTERVALS[underlying]


def find_leg(rows, underlying, expiry, strike, option_type):
    for r in rows:
        if (r["TckrSymb"] == underlying and r["XpryDt"] == expiry
                and r["FinInstrmTp"] == "IDO" and r["OptnTp"] == option_type
                and abs(float(r["StrkPric"]) - strike) < 0.01):
            return r
    return None


def leg_prices(row):
    """(open, high, low, close, lotsize) with a settlement-price fallback for zero-trade days."""
    open_p = float(row["OpnPric"])
    high_p = float(row["HghPric"])
    low_p = float(row["LwPric"])
    close_p = float(row["ClsPric"])
    settle_p = float(row["SttlmPric"])
    if open_p <= 0:
        open_p = settle_p  # no trades at open - use theoretical settlement as an entry proxy
    if close_p <= 0:
        close_p = settle_p
    if high_p <= 0:
        high_p = max(open_p, close_p)
    if low_p <= 0:
        low_p = min(open_p, close_p) if min(open_p, close_p) > 0 else close_p
    return open_p, high_p, low_p, close_p, int(float(row["NewBrdLotQty"]))


def simulate_day(rows, underlying, trade_day):
    candidates = [r["XpryDt"] for r in rows
                  if r["TckrSymb"] == underlying and r["FinInstrmTp"] == "IDO"
                  and r["XpryDt"] >= trade_day.isoformat()]
    if not candidates:
        return None
    expiry = min(candidates)

    underlying_rows = [r for r in rows if r["TckrSymb"] == underlying and r["XpryDt"] == expiry
                        and r["FinInstrmTp"] == "IDO"]
    spot = float(underlying_rows[0]["UndrlygPric"])
    interval = strike_interval(underlying)
    atm = round(spot / interval) * interval

    legs_wanted = {
        "hedge_ce": (atm + HEDGE_OFFSET * interval, "CE"),
        "hedge_pe": (atm - HEDGE_OFFSET * interval, "PE"),
        "short_ce": (atm + SHORT_OFFSET * interval, "CE"),
        "short_pe": (atm - SHORT_OFFSET * interval, "PE"),
    }

    resolved = {}
    for key, (strike, opt_type) in legs_wanted.items():
        row = find_leg(rows, underlying, expiry, strike, opt_type)
        if row is None:
            return None  # illiquid/missing strike that day - skip rather than guess
        resolved[key] = leg_prices(row)

    lotsize = resolved["short_ce"][4]

    def entry(key):
        return resolved[key][0]

    def close_exit(key):
        return resolved[key][3]

    width = (HEDGE_OFFSET - SHORT_OFFSET) * interval
    net_credit = (entry("short_ce") + entry("short_pe")) - (entry("hedge_ce") + entry("hedge_pe"))
    if net_credit <= 0 or net_credit > width:
        # A real vertical spread's credit can never be <= 0 or exceed the strike
        # width - either would be a free-money arbitrage, which no-arbitrage option
        # pricing rules out. Seeing it here means at least one leg's "Open" price is
        # a stale/theoretical value rather than a real simultaneous traded price -
        # this shows up mainly on far-dated, illiquid wing strikes (BANKNIFTY's
        # monthly-only expiry means it often has 2-4 weeks to expiry, versus
        # NIFTY's much more liquid weekly chain). Not tradeable data - skip rather
        # than report a number the market never actually offered.
        return None
    close_value = (close_exit("short_ce") + close_exit("short_pe")) - (close_exit("hedge_ce") + close_exit("hedge_pe"))
    open_to_close_pnl = (net_credit - close_value) * lotsize

    # Loose intraday sensitivity band (NOT a stop-loss simulation - see module docstring)
    best_case_close_value = (resolved["short_ce"][2] + resolved["short_pe"][2]) - (resolved["hedge_ce"][1] + resolved["hedge_pe"][1])
    worst_case_close_value = (resolved["short_ce"][1] + resolved["short_pe"][1]) - (resolved["hedge_ce"][2] + resolved["hedge_pe"][2])
    best_case_pnl = (net_credit - best_case_close_value) * lotsize
    worst_case_pnl = (net_credit - worst_case_close_value) * lotsize

    max_loss_proxy = (HEDGE_OFFSET - SHORT_OFFSET) * interval * lotsize - net_credit * lotsize

    return {
        "date": trade_day.isoformat(), "underlying": underlying, "expiry": expiry,
        "spot": spot, "atm": atm, "lotsize": lotsize,
        "net_credit_per_lot": round(net_credit, 2),
        "open_to_close_pnl_per_lot": round(open_to_close_pnl, 2),
        "best_case_pnl_per_lot": round(best_case_pnl, 2),
        "worst_case_pnl_per_lot": round(worst_case_pnl, 2),
        "max_loss_proxy_per_lot": round(max_loss_proxy, 2),
    }


def trading_days(start, end):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def main():
    print(f"Backtesting {UNDERLYINGS} iron condor (OTM{HEDGE_OFFSET} hedge / OTM{SHORT_OFFSET} short) "
          f"from {START_DATE} to {END_DATE}\n")

    results = []
    skipped = 0
    trading_day_count = 0
    for day in trading_days(START_DATE, END_DATE):
        try:
            rows = fetch_bhavcopy(day)
        except Exception as e:
            print(f"  {day}: fetch failed ({e}), skipping")
            continue
        if rows is None:
            continue  # holiday/weekend
        trading_day_count += 1
        for underlying in UNDERLYINGS:
            try:
                r = simulate_day(rows, underlying, day)
            except Exception as e:
                print(f"  {day} {underlying}: simulation error ({e}), skipping")
                skipped += 1
                continue
            if r:
                results.append(r)
            else:
                skipped += 1
        time.sleep(0.3)  # be a considerate citizen of NSE's archive server

    print(f"{trading_day_count} trading days processed, {skipped} underlying-days skipped "
          f"(illiquid/unreliable strike data)\n")

    if not results:
        print("No results - check date range / connectivity / NSE bhavcopy availability.")
        return

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)

    for underlying in UNDERLYINGS:
        rows = [r for r in results if r["underlying"] == underlying]
        if not rows:
            continue
        pnls = [r["open_to_close_pnl_per_lot"] for r in rows]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        total = sum(pnls)
        print(f"=== {underlying} ({len(rows)} trading days) ===")
        print(f"  Open-to-close total P&L per lot: Rs{total:,.0f}")
        print(f"  Win rate: {len(wins)}/{len(rows)} ({len(wins)/len(rows):.0%})")
        print(f"  Avg win: Rs{(sum(wins)/len(wins) if wins else 0):,.0f}  "
              f"Avg loss: Rs{(sum(losses)/len(losses) if losses else 0):,.0f}")
        print(f"  Best day: Rs{max(pnls):,.0f}  Worst day: Rs{min(pnls):,.0f}")
        print(f"  Typical structural max loss per lot (proxy): Rs{statistics.median(r['max_loss_proxy_per_lot'] for r in rows):,.0f}\n")

    print(f"Full daily results written to {out_path}")


if __name__ == "__main__":
    main()
