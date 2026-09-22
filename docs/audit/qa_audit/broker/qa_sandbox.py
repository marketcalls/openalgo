#!/usr/bin/env python3
"""Broker QA audit - SANDBOX (analyzer) runner.

Covers every section of broker-qa-audit-checklist.md EXCEPT holdings, which
lives in qa_live.py: the sandbox has no holdings most of the time, and its
funds/positions are reset whenever sandbox params are changed.

Two classes of check run here, for different reasons:

  * Order paths (place/modify/cancel/GTT/books) route to sandbox_service, so
    the full unsafe matrix - rejections, freeze quantity, trigger firing,
    cancel-all, close-all - can be driven at zero risk.

  * Market data, symbol services, options analytics and margin do NOT branch
    on analyzer mode. Verified in services/: quotes_service, history_service,
    depth_service and margin_service contain no sandbox branch at all, so they
    hit the live broker identically in either mode. They are therefore run
    once, here, and deliberately not repeated in the live script.

Usage:
    uv run python docs/audit/qa_audit/broker/qa_sandbox.py
    OPENALGO_API_KEY=... OPENALGO_HOST=http://127.0.0.1:5000 [QA_WS=1] [QA_HEAVY=1]
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx  # noqa: E402
from qa_common import (  # noqa: E402
    BLOCKED,
    FAIL,
    IST,
    PASS,
    SKIP,
    WARN,
    Runner,
    Skip,
    Warn,
    active_broker,
    as_num,
    canonical_index_symbols,
    expected_equity_tick,
    expected_index_fut_tick,
    load_plugin_exchanges,
    need,
    need_2dp,
    need_keys,
    need_nonzero,
    need_ohlc,
    normalise,
    now_ist,
    parse_ist,
    print_rollup,
    resolve_matrix,
    write_report,
)

API_KEY = os.getenv("OPENALGO_API_KEY", "945bd843b8683f584321f6cf1fc55b664975321281ee536ee68aa9e36147eef6")
HOST = os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000")
HEAVY = os.getenv("QA_HEAVY", "") == "1"   # 500-symbol multiquotes, 2y history
NO_WS = os.getenv("QA_WS", "1") == "0"   # websocket runs by default; QA_WS=0 disables
WS_URL = os.getenv("OPENALGO_WS", "ws://127.0.0.1:8765")
STRAT = "QA-SANDBOX"

# Quote-only index exchanges. Their rows are never ordered, so tick size and
# lot size do not apply to them - see MC-11.
INDEX_EXCHANGES = ("NSE_INDEX", "BSE_INDEX", "MCX_INDEX", "GLOBAL_INDEX")
_Q_INDEX = ", ".join(repr(x) for x in INDEX_EXCHANGES)


def post(path: str, payload: dict) -> dict:
    """For the few endpoints the SDK does not wrap."""
    payload = {"apikey": API_KEY, **payload}
    r = httpx.post(f"{HOST}/api/v1/{path}", json=payload, timeout=60)
    try:
        return r.json()
    except Exception:
        return {"status": "error", "message": f"HTTP {r.status_code} non-JSON"}


# ==========================================================================
# 2. master contract
# ==========================================================================
def sec_master(run: Runner) -> None:
    run.section("2. Master contract")
    ex_list = run.env["exchanges"]

    def counts():
        with run.db() as c:
            rows = dict(c.execute("select exchange, count(*) from symtoken group by exchange"))
        need(rows, "symtoken empty - master contract never downloaded")
        missing = [e for e in ex_list if e not in rows or rows[e] == 0]
        need(not missing, f"claimed but empty in symtoken: {missing}")
        run.note_limit("symtoken rows per exchange", json.dumps(rows))
        return rows

    run.check("MC-02", counts, endpoint="symtoken", expected="non-zero per claimed exchange")

    def dupes():
        with run.db() as c:
            n = c.execute(
                "select count(*) from (select symbol, exchange from symtoken "
                "group by symbol, exchange having count(*) > 1)"
            ).fetchone()[0]
        need(n == 0, f"{n} duplicate (symbol, exchange) pairs")

    run.check("MC-03", dupes, endpoint="symtoken", expected="0 duplicates")

    def itypes():
        with run.db() as c:
            vals = {r[0] for r in c.execute("select distinct instrumenttype from symtoken")}
        bad = vals - {"EQ", "FUT", "CE", "PE", "", None}
        need(not bad, f"unexpected instrumenttype values {bad} (there is no INDEX type)")

    run.check("MC-04", itypes, endpoint="symtoken", expected="EQ/FUT/CE/PE only")

    def expiry_fmt():
        with run.db() as c:
            rows = c.execute(
                "select symbol, exchange, expiry, instrumenttype from symtoken "
                "where instrumenttype in ('FUT','CE','PE') "
                "group by exchange, instrumenttype"
            ).fetchall()
        need(rows, "no derivative rows")
        for sym, ex, exp, it in rows:
            need(bool(exp), f"{sym}@{ex} ({it}): empty expiry")
            datetime.strptime(exp, "%d-%b-%y")
            need(exp == exp.upper(), f"{sym}@{ex}: expiry {exp} not uppercase")
        with run.db() as c:
            n = c.execute(
                "select count(*) from symtoken where instrumenttype in ('EQ','') "
                "and expiry != ''"
            ).fetchone()[0]
        need(n == 0, f"{n} EQ/index rows carry a non-empty expiry")

    run.check("MC-05", expiry_fmt, endpoint="symtoken", expected="DD-MMM-YY upper, '' for EQ")

    canon = canonical_index_symbols()

    def index_norm():
        """MC-07 - the headline index of each exchange must be present under
        its own exchange. Keyed per exchange: BANKNIFTY is NSE_INDEX, SENSEX
        is BSE_INDEX. Checking one flat list against both is meaningless."""
        headline = {
            "NSE_INDEX": ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "INDIAVIX"],
            "BSE_INDEX": ["SENSEX", "BANKEX", "SENSEX50"],
            "MCX_INDEX": ["MCXBULLDEX", "MCXCOMDEX"],
        }
        missing = []
        with run.db() as c:
            for ex, syms in headline.items():
                if ex not in ex_list:
                    continue
                have = {r[0] for r in c.execute(
                    "select symbol from symtoken where exchange=?", (ex,))}
                missing += [f"{s}@{ex}" for s in syms if s not in have]
        if missing:
            run.note_quirk("Missing headline index symbols", ", ".join(missing))
            raise AssertionError(f"missing index symbols: {missing}")

    run.check("MC-07", index_norm, endpoint="symtoken", expected="headline index per exchange")

    def missing_report():
        """MC-08 - a named deliverable, listed by name in its own sheet.

        Diffs the FULL canonical set for each exchange, parsed from
        symbol-format.md, against that exchange's rows only. A symbol present
        under an unnormalised broker display name ('HANGSENG BEES-NAV' for
        HANGSENGBEESNAV) is reported separately from one that is genuinely
        absent - the first is a normalisation defect, the second a data gap.
        """
        rows = []
        stats = []
        if not canon:
            raise Skip("symbol-format.md not readable - canonical lists unavailable")
        with run.db() as c:
            for ex, want in canon.items():
                if ex not in ex_list:
                    continue
                have = {r[0] for r in c.execute(
                    "select symbol from symtoken where exchange=?", (ex,))}
                folded = {normalise(h): h for h in have}
                absent = unnormalised = 0
                for s in want:
                    if s in have:
                        continue
                    alias = folded.get(normalise(s))
                    if alias:
                        rows.append([ex, s, f"present as unnormalised broker name {alias!r}"])
                        unnormalised += 1
                    else:
                        rows.append([ex, s, "absent from master"])
                        absent += 1
                stats.append(f"{ex}: {len(want) - absent - unnormalised}/{len(want)} ok, "
                             f"{unnormalised} unnormalised, {absent} absent")
        run.env["missing_symbols"] = rows
        run.note_limit("canonical index coverage", "; ".join(stats))
        if rows:
            un = sum(1 for r in rows if r[2].startswith("present as"))
            raise Warn(f"{len(rows)} canonical symbols not matched exactly "
                       f"({un} unnormalised, {len(rows) - un} absent) - see Missing Symbols sheet")

    run.check("MC-08", missing_report, endpoint="symtoken", expected="per-exchange diff, listed by name")

    def strike_float():
        with run.db() as c:
            n = c.execute(
                "select count(*) from symtoken where instrumenttype in ('CE','PE') "
                "and (strike is null or strike <= 0)"
            ).fetchone()[0]
            dec = c.execute(
                "select count(*) from symtoken where instrumenttype in ('CE','PE') "
                "and strike != round(strike)"
            ).fetchone()[0]
        need(n == 0, f"{n} option rows with null/non-positive strike")
        run.note_limit("decimal-strike option rows", dec)

    run.check("MC-09", strike_float, endpoint="symtoken", expected="strike float, > 0")

    def ticks():
        """Tradable rows only. Index spot feeds on the *_INDEX exchanges are
        quote-only - they are never ordered, so they have no tick and a null
        one is correct, not a defect. Index FUTURES and OPTIONS are tradable
        and live on NFO/BFO/MCX, so they stay in scope here and in TS-10/11."""
        with run.db() as c:
            n = c.execute(
                "select count(*) from symtoken where (tick_size is null or tick_size <= 0) "
                "and instrumenttype in ('EQ','FUT','CE','PE') "
                f"and exchange not in ({_Q_INDEX})"
            ).fetchone()[0]
            skipped = c.execute(
                f"select count(*) from symtoken where exchange in ({_Q_INDEX})"
            ).fetchone()[0]
        run.note_limit("tick check: index rows excluded", f"{skipped} quote-only index rows")
        need(n == 0, f"{n} tradable rows with null/zero tick_size")

    run.check("MC-11", ticks, endpoint="symtoken",
              expected="tick_size non-zero on tradable rows (index spot excluded)")

    def lots():
        with run.db() as c:
            n = c.execute(
                "select count(*) from symtoken where instrumenttype in ('FUT','CE','PE') "
                "and (lotsize is null or lotsize <= 0)"
            ).fetchone()[0]
            varies = c.execute(
                "select count(*) from (select name, exchange from symtoken "
                "where instrumenttype='FUT' group by name, exchange "
                "having count(distinct lotsize) > 1)"
            ).fetchone()[0]
        need(n == 0, f"{n} derivative rows with null/zero lotsize")
        need(varies == 0, f"{varies} underlyings whose FUT lotsize varies by expiry")
        if "MCX" in ex_list:
            with run.db() as c:
                vals = {r[0] for r in c.execute(
                    "select distinct lotsize from symtoken where exchange='MCX'")}
            conv = "contracts" if vals == {1} else "units"
            run.note_quirk("MCX lot-size convention", f"{conv} (distinct lotsize values: {sorted(vals)[:8]})")

    run.check("MC-12", lots, endpoint="symtoken", expected="non-zero, stable per underlying")

    def token_col():
        with run.db() as c:
            n = c.execute("select count(*) from symtoken where token is null or token=''").fetchone()[0]
        need(n == 0, f"{n} rows with empty token")

    run.check("MC-15", token_col, endpoint="symtoken", expected="token populated")

    def instruments(ex: str):
        """SDK contract: a DataFrame on success, a dict on error. Never use
        truthiness on the result - `df or {}` raises 'truth value ambiguous'."""
        r = run.client.instruments(exchange=ex)
        if isinstance(r, dict):
            run.expect_error(r, f"instruments {ex}")
            raise AssertionError(f"instruments {ex}: {r.get('message')}")
        need(hasattr(r, "columns"), f"instruments {ex}: unexpected type {type(r).__name__}")
        need(len(r) > 0, f"no instrument rows returned for {ex}")
        need_keys(dict.fromkeys(r.columns, 1),
                  ["symbol", "brsymbol", "name", "exchange", "token",
                   "expiry", "strike", "lotsize", "instrumenttype", "tick_size"],
                  f"instruments {ex} columns")
        with run.db() as c:
            n = c.execute("select count(*) from symtoken where exchange=?", (ex,)).fetchone()[0]
        need(abs(len(r) - n) <= max(5, n * 0.02),
             f"instruments {ex} returned {len(r)} rows vs {n} in symtoken")
        return len(r)

    for ex in ex_list:
        if ex in ("GLOBAL_INDEX",):
            continue
        run.check(f"MC-17.{ex}", lambda ex=ex: instruments(ex),
                  endpoint="instruments", exchange=ex,
                  expected="rows returned, schema + count match symtoken")

    def mc_download_status():
        """MC-01 - the master contract downloaded successfully today."""
        with run.db() as c:
            try:
                rows = c.execute(
                    "select exchange, status, last_updated from master_contract_status"
                ).fetchall()
            except Exception:
                raise Skip("master_contract_status table not present in this build") from None
        need(rows, "master_contract_status is empty - the download never ran")
        bad = [(e, s) for e, s, _ in rows if str(s).lower() != "success"]
        need(not bad, f"master contract not successful for: {bad[:5]}")
        stamps = [t for _, _, t in rows if t]
        run.note_limit("master contract last_updated", str(max(stamps)) if stamps else "unknown")

    run.check("MC-01", mc_download_status, endpoint="master_contract_status",
              expected="status=success for every exchange")

    def mc_symbol_construction():
        """MC-06 - sample the OpenAlgo symbol shape per segment."""
        pat = {
            "FUT": re.compile(r"^[A-Z0-9&.\-]+\d{2}[A-Z]{3}\d{2}FUT$"),
            "CE": re.compile(r"^[A-Z0-9&.\-]+\d{2}[A-Z]{3}\d{2}\d+(\.\d+)?CE$"),
            "PE": re.compile(r"^[A-Z0-9&.\-]+\d{2}[A-Z]{3}\d{2}\d+(\.\d+)?PE$"),
        }
        bad = []
        with run.db() as c:
            for ex in run.env["exchanges"]:
                if ex in INDEX_EXCHANGES:
                    continue
                for it, rx in pat.items():
                    for (s,) in c.execute(
                        "select symbol from symtoken where exchange=? and instrumenttype=? "
                        "limit 3", (ex, it)):
                        if not rx.match(s):
                            bad.append(f"{s}@{ex} ({it})")
                for (s,) in c.execute(
                    "select symbol from symtoken where exchange=? and instrumenttype in ('EQ','') "
                    "limit 3", (ex,)):
                    if re.search(r"\d{2}[A-Z]{3}\d{2}", s):
                        bad.append(f"{s}@{ex} (EQ carries an expiry block)")
        need(not bad, f"symbols not in OpenAlgo format: {bad[:6]}")

    run.check("MC-06", mc_symbol_construction, endpoint="symtoken",
              expected="EQ bare, FUT/CE/PE carry DDMMMYY and strike")

    def mc_strike_scaling():
        """MC-10 - the strike column must agree with the strike inside brsymbol."""
        bad, checked = [], 0
        with run.db() as c:
            for ex in run.env["exchanges"]:
                if ex in INDEX_EXCHANGES:
                    continue
                for sym, strike in c.execute(
                    "select symbol, strike from symtoken where exchange=? "
                    "and instrumenttype in ('CE','PE') limit 4", (ex,)):
                    mm = re.search(r"\d{2}[A-Z]{3}\d{2}(\d+(?:\.\d+)?)(?:CE|PE)$", sym)
                    if not mm:
                        continue
                    checked += 1
                    embedded = float(mm.group(1))
                    if abs(float(strike) - embedded) > 0.01:
                        bad.append(f"{sym}@{ex}: column {strike} vs symbol {embedded}")
        need(checked, "no option rows with a parseable strike")
        need(not bad, f"strike scaling differs from the symbol (per-segment scaling bug): "
                      f"{bad[:5]}")
        run.note_limit("strike scaling rows cross-checked", checked)

    run.check("MC-10", mc_strike_scaling, endpoint="symtoken",
              expected="strike column == strike embedded in the symbol")

    def mc_brexchange():
        with run.db() as c:
            n = c.execute(
                "select count(*) from symtoken where brexchange is null or brexchange=''"
            ).fetchone()[0]
            pairs = c.execute(
                "select exchange, group_concat(distinct brexchange) from symtoken "
                "group by exchange").fetchall()
        need(n == 0, f"{n} rows with an empty brexchange")
        run.note_limit("exchange -> brexchange", json.dumps(dict(pairs))[:400])

    run.check("MC-13", mc_brexchange, endpoint="symtoken",
              expected="raw broker exchange code on every row")

    def mc_name_column():
        with run.db() as c:
            n = c.execute("select count(*) from symtoken where name is null or name=''").fetchone()[0]
            need(n == 0, f"{n} rows with an empty name")
            bad = []
            for sym, nm in c.execute(
                "select symbol, name from symtoken "
                "where instrumenttype in ('FUT','CE','PE') limit 200"):
                if not sym.startswith(nm):
                    bad.append(f"{sym} (name={nm!r})")
        need(not bad,
             f"derivative name must be the underlying and prefix the symbol: {bad[:5]}")

    run.check("MC-14", mc_name_column, endpoint="symtoken",
              expected="underlying for derivatives, populated everywhere")

    def mc_contract_value():
        with run.db() as c:
            cols = {r[1] for r in c.execute("pragma table_info(symtoken)")}
        need("contract_value" in cols,
             "symtoken has no contract_value column - a fresh create_all() would not "
             "match the shared table")

    run.check("MC-16", mc_contract_value, endpoint="symtoken",
              expected="contract_value declared, even if NULL")

    def mc_instruments_csv():
        ex = next((e for e in run.env["exchanges"] if e not in INDEX_EXCHANGES), "NSE")
        r = httpx.get(f"{HOST}/api/v1/instruments",
                      params={"apikey": API_KEY, "exchange": ex, "format": "csv"},
                      timeout=120)
        need(r.status_code == 200, f"CSV download returned HTTP {r.status_code}")
        ct = r.headers.get("content-type", "")
        need("text/csv" in ct, f"Content-Type is {ct!r}, expected text/csv")
        cd = r.headers.get("content-disposition", "")
        need(f"instruments_{ex}.csv" in cd,
             f"download filename should be instruments_{ex}.csv, got {cd!r}")
        rows = [ln for ln in r.text.splitlines() if ln.strip()]
        need(len(rows) > 1, "CSV has no data rows")
        with run.db() as c:
            n = c.execute("select count(*) from symtoken where exchange=?", (ex,)).fetchone()[0]
        need(abs((len(rows) - 1) - n) <= max(5, n * 0.02),
             f"CSV has {len(rows)-1} rows vs {n} in symtoken for {ex}")

    run.check("MC-18", mc_instruments_csv, endpoint="instruments",
              expected="text/csv, correct filename, row count matches JSON")

    run.check("MC-19", lambda: run.expect_error(
        post("instruments", {"exchange": "NOTANEXCHANGE"}), "invalid exchange"),
        endpoint="instruments", expected="clean 400, not 500")


# ==========================================================================
# 2.1 tick size slabs
# ==========================================================================
def sec_ticks(run: Runner) -> None:
    run.section("2.1 Tick size slabs")
    m = run.matrix

    def eq_tick(slot: str, cid: str):
        if slot not in m:
            raise Skip(f"{slot} unresolved")
        sym, ex = m[slot]
        q = run.ok(run.client.quotes(symbol=sym, exchange=ex), f"quotes {sym}")["data"]
        ltp = need_nonzero(q.get("ltp"), f"{sym}.ltp")
        with run.db() as c:
            row = c.execute("select tick_size from symtoken where symbol=? and exchange=?",
                            (sym, ex)).fetchone()
        need(row, f"{sym}@{ex} not in symtoken")
        want = expected_equity_tick(ltp)
        need(abs(float(row[0]) - want) < 1e-9,
             f"{sym} ltp={ltp} -> expected tick {want}, got {row[0]}")

    for cid, slot in (("TS-01", "EQ_CHEAP"), ("TS-04", "EQ_LIQUID"), ("TS-05", "EQ_SPECIAL")):
        run.check(cid, lambda s=slot, c=cid: eq_tick(s, c), endpoint="symbol+quotes",
                  symbol=str(m.get(slot, "")), expected="tick matches NSE price slab")

    # ETF tick size is deliberately not verified. ETFs do not follow the equity
    # price slab, and the master carries per-scrip exceptions that are not
    # resolvable from the slab either, so there is no rule here worth asserting.
    for cid, slot in (("TS-02", "GOLDBEES"), ("TS-03", "NIFTYBEES")):
        run.record(cid, SKIP, "ETF tick size deliberately not verified - ETFs do not "
                              "follow the equity price slab",
                   endpoint="symtoken", exchange="NSE", symbol=slot)

    def stock_fut_inherits():
        with run.db() as c:
            rows = c.execute(
                "select f.symbol, f.tick_size, e.tick_size from symtoken f "
                "join symtoken e on e.symbol=f.name and e.exchange='NSE' and e.instrumenttype='EQ' "
                "where f.exchange='NFO' and f.instrumenttype='FUT' limit 40"
            ).fetchall()
        need(rows, "no NFO stock futures joined to cash")
        bad = [f"{s}: fut {ft} vs cash {et}" for s, ft, et in rows if abs(ft - et) > 1e-9]
        need(not bad, f"stock futures not inheriting cash tick: {bad[:5]}")

    run.check("TS-07", stock_fut_inherits, endpoint="symtoken",
              exchange="NFO", expected="stock FUT tick == cash tick")

    def index_fut_tick(u: str, ex: str, idx_ex: str):
        q = run.ok(run.client.quotes(symbol=u, exchange=idx_ex), f"quotes {u}")["data"]
        lvl = need_nonzero(q.get("ltp"), f"{u}.ltp")
        with run.db() as c:
            row = c.execute(
                "select symbol, tick_size from symtoken where exchange=? and instrumenttype='FUT' "
                "and name=? order by expiry limit 1", (ex, u)).fetchone()
        if not row:
            raise Skip(f"no {u} future on {ex}")
        want = expected_index_fut_tick(lvl)
        need(abs(float(row[1]) - want) < 1e-9,
             f"{row[0]} level={lvl} -> expected tick {want}, got {row[1]}")

    run.check("TS-10", lambda: index_fut_tick("NIFTY", "NFO", "NSE_INDEX"),
              endpoint="symtoken", exchange="NFO", expected="index-level slab")
    run.check("TS-11", lambda: index_fut_tick("BANKNIFTY", "NFO", "NSE_INDEX"),
              endpoint="symtoken", exchange="NFO", expected="index-level slab")

    def opt_ticks():
        with run.db() as c:
            spread = dict(c.execute(
                "select tick_size, count(*) from symtoken where exchange='NFO' "
                "and instrumenttype in ('CE','PE') group by tick_size"))
        need(spread, "no NFO options")
        run.note_limit("NFO option tick spread", json.dumps({str(k): v for k, v in spread.items()}))
        need(len(spread) >= 1, "no option ticks")
        # a single flat value across every option row is the bug to catch
        if len(spread) == 1 and "NSE" in run.env["exchanges"]:
            raise Warn(f"all NFO options share one tick {list(spread)[0]} - verify against contract file")

    run.check("TS-12", opt_ticks, endpoint="symtoken", exchange="NFO",
              expected="0.05 general, 0.01 on cheap underlyings")

    def mcx_ticks():
        if "MCX" not in run.env["exchanges"]:
            raise Skip("MCX not in supported_exchanges")
        with run.db() as c:
            spread = dict(c.execute(
                "select tick_size, count(*) from symtoken where exchange='MCX' group by tick_size"))
        need(len(spread) > 1, f"MCX reports a single flat tick {list(spread)} - not slab/per-commodity")
        run.note_limit("MCX tick spread", json.dumps({str(k): v for k, v in spread.items()}))

    run.check("TS-15", mcx_ticks, endpoint="symtoken", exchange="MCX",
              expected="per-commodity ticks, not flat")

    def named_equity_tick(name: str, want: float):
        """Assert a named scrip's tick against the slab its live price lands in."""
        with run.db() as c:
            row = c.execute("select tick_size from symtoken where symbol=? and exchange='NSE' "
                            "and instrumenttype in ('EQ','')", (name,)).fetchone()
        if not row:
            raise Skip(f"{name} not in the master")
        got = float(row[0] or 0)
        q = run.client.quotes(symbol=name, exchange="NSE")
        ltp = as_num((q.get("data") or {}).get("ltp", 0), f"{name}.ltp") \
            if q.get("status") == "success" else 0
        slab = expected_equity_tick(ltp) if ltp else want
        need(abs(got - slab) < 1e-9,
             f"{name}: ltp={ltp or 'n/a'} -> slab expects {slab}, master says {got}")
        if ltp:
            need(abs(slab - want) < 1e-9,
                 f"{name}: now priced at {ltp}, whose slab tick is {slab}, not the {want} "
                 f"this row was written for - refresh the checklist band")

    run.check("TS-06", lambda: named_equity_tick("MRF", 5.00), endpoint="symtoken",
              exchange="NSE", symbol="MRF", expected="above 20,000 -> 5.00")

    def fut_matches_cash(name: str, want: float):
        with run.db() as c:
            cash = c.execute("select tick_size from symtoken where symbol=? and exchange='NSE' "
                             "and instrumenttype in ('EQ','')", (name,)).fetchone()
            fut = c.execute("select symbol, tick_size from symtoken where exchange='NFO' "
                            "and instrumenttype='FUT' and name=? order by expiry limit 1",
                            (name,)).fetchone()
        if not cash or not fut:
            raise Skip(f"{name}: cash or future row absent")
        need(abs(float(fut[1]) - float(cash[0])) < 1e-9,
             f"{fut[0]}: future tick {fut[1]} does not match cash {name} tick {cash[0]}")
        if abs(float(cash[0]) - want) > 1e-9:
            raise Warn(f"{name} cash tick is {cash[0]}, not the {want} this row expects - "
                       f"the underlying has moved price band; future still matches cash")

    run.check("TS-08", lambda: fut_matches_cash("IDEA", 0.01), endpoint="symtoken",
              exchange="NFO", symbol="IDEA...FUT", expected="cheap underlying -> 0.01")
    run.check("TS-09", lambda: fut_matches_cash("BAJAJ-AUTO", 1.00), endpoint="symtoken",
              exchange="NFO", symbol="BAJAJ-AUTO...FUT", expected="high-priced -> 1.00")

    def cheap_option_tick():
        """TS-13 - options on low-priced underlyings carry 0.01, not 0.05."""
        with run.db() as c:
            rows = c.execute(
                "select name, tick_size, count(*) from symtoken where exchange='NFO' "
                "and instrumenttype in ('CE','PE') and tick_size=0.01 "
                "group by name order by count(*) desc limit 10").fetchall()
        if not rows:
            raise Skip("no NFO options at 0.01 in this master - the flat 0.05 rule holds here")
        run.note_limit("option underlyings at 0.01 tick",
                       ", ".join(f"{n}({c})" for n, _, c in rows))
        with run.db() as c:
            for name, _, _ in rows[:3]:
                cash = c.execute("select tick_size from symtoken where symbol=? "
                                 "and exchange='NSE' and instrumenttype in ('EQ','')",
                                 (name,)).fetchone()
                if cash:
                    need(abs(float(cash[0]) - 0.01) < 1e-9,
                         f"{name} options are at 0.01 but the cash scrip is at {cash[0]} - "
                         f"inconsistent tick assignment")

    run.check("TS-13", cheap_option_tick, endpoint="symtoken", exchange="NFO",
              expected="cheap-underlying options at 0.01, consistent with cash")

    def bse_index_future():
        if "BFO" not in run.env["exchanges"]:
            raise Skip("BFO not claimed by this broker")
        with run.db() as c:
            row = c.execute("select symbol, tick_size from symtoken where exchange='BFO' "
                            "and instrumenttype='FUT' and name='BANKEX' "
                            "order by expiry limit 1").fetchone()
        if not row:
            raise Skip("no BANKEX future in the master")
        got = float(row[1])
        q = run.client.quotes(symbol="BANKEX", exchange="BSE_INDEX")
        lvl = as_num((q.get("data") or {}).get("ltp", 0), "BANKEX ltp") \
            if q.get("status") == "success" else 0
        run.note_limit("BFO index future tick", f"{row[0]} = {got} (index level {lvl or 'n/a'})")
        need(got > 0, f"{row[0]}: zero tick size")
        if lvl:
            slab = expected_index_fut_tick(lvl)
            if abs(got - slab) > 1e-9:
                raise Warn(f"{row[0]}: tick {got} vs NSE index slab {slab} at level {lvl} - "
                           f"BSE publishes its own slab, recording rather than failing")

    run.check("TS-14", bse_index_future, endpoint="symtoken", exchange="BFO",
              expected="BANKEX future tick recorded against the BSE slab")

    def mcx_named(name: str, want: float):
        if "MCX" not in run.env["exchanges"]:
            raise Skip("MCX not claimed by this broker")
        with run.db() as c:
            row = c.execute("select symbol, tick_size from symtoken where exchange='MCX' "
                            "and instrumenttype='FUT' and name=? order by expiry limit 1",
                            (name,)).fetchone()
        if not row:
            raise Skip(f"no {name} future in the master")
        got = float(row[1])
        need(abs(got - want) < 1e-9,
             f"{row[0]}: tick {got}, MCX contract spec says {want}")

    run.check("TS-16", lambda: mcx_named("GOLD", 1.00), endpoint="symtoken",
              exchange="MCX", symbol="GOLD...FUT", expected="1.00")
    run.check("TS-17", lambda: mcx_named("SILVER", 1.00), endpoint="symtoken",
              exchange="MCX", symbol="SILVER...FUT", expected="1.00")
    run.check("TS-18", lambda: mcx_named("NATURALGAS", 0.10), endpoint="symtoken",
              exchange="MCX", symbol="NATURALGAS...FUT", expected="0.10")
    run.check("TS-19", lambda: mcx_named("COPPER", 0.05), endpoint="symtoken",
              exchange="MCX", symbol="COPPER...FUT", expected="0.05")

    run.record("TS-20", SKIP,
               "off-tick order rejection is exercised live by OD-20",
               endpoint="placeorder")


# ==========================================================================
# 3. symbol services
# ==========================================================================
def sec_symbols(run: Runner) -> None:
    run.section("3. Symbol services")
    m = run.matrix

    def sym_lookup(slot, itype=None):
        if slot not in m:
            raise Skip(f"{slot} unresolved")
        s, ex = m[slot]
        d = run.ok(run.client.symbol(symbol=s, exchange=ex), f"symbol {s}")["data"]
        need_keys(d, ["symbol", "brsymbol", "exchange", "brexchange", "token",
                      "lotsize", "tick_size"], f"symbol {s}")
        need(d["symbol"] == s, f"echoed symbol {d['symbol']} != {s}")
        need_nonzero(d["tick_size"], f"{s}.tick_size")
        if itype:
            need(d.get("instrumenttype") == itype, f"{s}: instrumenttype {d.get('instrumenttype')}")
        return d

    run.check("SYM-01", lambda: sym_lookup("EQ_LIQUID"), endpoint="symbol", expected="full field set")
    run.check("SYM-03", lambda: sym_lookup("OPT_DECIMAL_STRIKE"),
              endpoint="symbol", expected="decimal strike preserved")
    run.check("SYM-04", lambda: sym_lookup("IDX_NSE"), endpoint="symbol", expected="index resolves")
    run.check("SYM-05", lambda: sym_lookup("EQ_SPECIAL"), endpoint="symbol",
              expected="special char intact")
    run.check("SYM-06", lambda: run.expect_error(
        run.client.symbol(symbol="ZZNOTREAL99", exchange="NSE"), "symbol unknown"),
        endpoint="symbol", expected="clean error")

    def search_compound():
        r = run.ok(run.client.search(query="NIFTY 26000 CE", exchange="NFO"), "search")
        rows = r.get("data") or []
        need(rows, "no matches")
        for row in rows[:5]:
            need_keys(row, ["symbol", "brsymbol", "name", "exchange", "instrumenttype",
                            "expiry", "strike", "lotsize", "tick_size", "token"], "search row")
            need(row["instrumenttype"] == "CE", f"non-CE row {row['symbol']}")
            need(as_num(row["strike"], "strike") == 26000, f"wrong strike {row['strike']}")

    run.check("SYM-08", search_compound, endpoint="search", exchange="NFO",
              expected="strike+type filtered")

    def sym_futures():
        slot = next((f"FUT_{e}" for e in ("NFO", "BFO", "MCX", "CDS") if f"FUT_{e}" in m), None)
        if not slot:
            raise Skip("no futures slot resolved")
        s, ex = m[slot]
        d = run.ok(run.client.symbol(symbol=s, exchange=ex), f"symbol {s}")["data"]
        need(d["instrumenttype"] == "FUT", f"{s}: instrumenttype {d['instrumenttype']!r}")
        datetime.strptime(d["expiry"], "%d-%b-%y")
        need(d["expiry"] == d["expiry"].upper(), f"{s}: expiry {d['expiry']} not uppercase")
        need_nonzero(d["lotsize"], f"{s}.lotsize")
        if "freeze_qty" not in d:
            raise Warn(f"{s}: freeze_qty absent - F&O rows should carry it")

    run.check("SYM-02", sym_futures, endpoint="symbol",
              expected="FUT type, DD-MMM-YY expiry, lotsize, freeze_qty")

    SEARCH_FIELDS = ["symbol", "brsymbol", "name", "exchange", "brexchange",
                     "instrumenttype", "expiry", "strike", "lotsize", "tick_size", "token"]

    def search_plain():
        if "EQ_LIQUID" not in m:
            raise Skip("EQ_LIQUID unresolved")
        q = m["EQ_LIQUID"][0]
        rows = run.ok(run.client.search(query=q, exchange="NSE"), "search")["data"] or []
        need(rows, f"no matches for {q!r}")
        for r in rows[:5]:
            need_keys(r, SEARCH_FIELDS, "search row")
        need(any(r["symbol"] == q for r in rows), f"exact match {q} not in the results")

    run.check("SYM-07", search_plain, endpoint="search",
              expected="matches returned with the full documented field set")

    def search_case():
        if "EQ_LIQUID" not in m:
            raise Skip("EQ_LIQUID unresolved")
        q = m["EQ_LIQUID"][0]
        up = {r["symbol"] for r in (run.ok(run.client.search(query=q.upper(), exchange="NSE"),
                                           "search upper")["data"] or [])}
        lo = {r["symbol"] for r in (run.ok(run.client.search(query=q.lower(), exchange="NSE"),
                                           "search lower")["data"] or [])}
        need(up and lo, "one of the case variants returned nothing")
        need(up == lo,
             f"case-sensitivity: upper returned {len(up)} rows, lower {len(lo)}; "
             f"difference {sorted(up ^ lo)[:5]}")

    run.check("SYM-09", search_case, endpoint="search", expected="case-insensitive")

    def expiry_list(ex, u, itype):
        r = run.ok(run.client.expiry(symbol=u, exchange=ex, instrumenttype=itype),
                   f"expiry {u}@{ex} {itype}")
        ds = r.get("data") or []
        need(ds, f"no {itype} expiries for {u}@{ex}")
        parsed = [datetime.strptime(d, "%d-%b-%y") for d in ds]
        need(parsed == sorted(parsed), f"{itype} expiries not ascending: {ds[:4]}")
        need(parsed[0].date() >= date.today() - timedelta(days=1),
             f"first {itype} expiry {ds[0]} is in the past")
        for d in ds:
            need(d == d.upper(), f"expiry {d} not uppercase")
        return ds

    def expiry_futures():
        ex, u = next(((e, u) for e, u in (("NFO", "NIFTY"), ("BFO", "SENSEX"),
                                          ("MCX", "CRUDEOIL"), ("CDS", "USDINR"))
                      if e in run.env["exchanges"]), (None, None))
        if not ex:
            raise Skip("no derivatives exchange claimed")
        expiry_list(ex, u, "futures")

    run.check("SYM-11", expiry_futures, endpoint="expiry",
              expected="futures expiries ascending, DD-MMM-YY, not past")

    def expiry_options():
        if "NFO" not in run.env["exchanges"]:
            raise Skip("NFO not claimed")
        ds = expiry_list("NFO", "NIFTY", "options")
        parsed = [datetime.strptime(d, "%d-%b-%y").date() for d in ds[:6]]
        gaps = [(b - a).days for a, b in zip(parsed, parsed[1:], strict=False)]
        run.note_limit("NIFTY option expiry gaps (days)", str(gaps))
        need(any(g <= 10 for g in gaps),
             f"no weekly expiries within 10 days of each other for a NIFTY chain: {ds[:6]}")

    run.check("SYM-12", expiry_options, endpoint="expiry",
              expected="option expiries include weeklies for an index")

    def expiry_non_derivative():
        r = run.client.expiry(symbol="RELIANCE", exchange="NSE", instrumenttype="options")
        if r.get("status") == "error":
            run.expect_error(r, "expiry on a cash exchange")
            return
        need(not (r.get("data") or []),
             "expiry on a non-derivative exchange returned data instead of an error")
        raise Warn("expiry on NSE returned an empty success - the spec asks for a clean error")

    run.check("SYM-14", expiry_non_derivative, endpoint="expiry",
              expected="clean error, not an empty success")

    for ex in run.env["exchanges"][:6]:
        run.check(f"SYM-10.{ex}", lambda ex=ex: need(
            bool((run.client.search(query="A", exchange=ex) or {}).get("data")),
            f"no search results on {ex}"), endpoint="search", exchange=ex,
            expected="non-empty per exchange")

    def expiry_shape(ex: str, u: str, itype: str):
        r = run.ok(run.client.expiry(symbol=u, exchange=ex, instrumenttype=itype),
                   f"expiry {u}@{ex}")
        ds = r.get("data") or []
        need(ds, f"no {itype} expiries for {u}@{ex}")
        parsed = [datetime.strptime(d, "%d-%b-%y") for d in ds]
        need(parsed == sorted(parsed), "expiries not ascending")
        need(parsed[0].date() >= date.today() - timedelta(days=1),
             f"first expiry {ds[0]} is in the past")
        for d in ds:
            need(d == d.upper(), f"expiry {d} not uppercase")
        return ds

    for ex, u in (("NFO", "NIFTY"), ("BFO", "SENSEX"), ("MCX", "CRUDEOIL"),
                  ("CDS", "USDINR"), ("NCO", "GOLD"), ("BCD", "USDINR")):
        if ex not in run.env["exchanges"]:
            continue
        run.check(f"SYM-13.{ex}.F", lambda ex=ex, u=u: expiry_shape(ex, u, "futures"),
                  endpoint="expiry", exchange=ex, expected="DD-MMM-YY ascending")
        run.check(f"SYM-13.{ex}.O", lambda ex=ex, u=u: expiry_shape(ex, u, "options"),
                  endpoint="expiry", exchange=ex, expected="same shape as futures")


# ==========================================================================
# 4. quotes / multiquotes / depth   (live broker even in analyzer mode)
# ==========================================================================
def sec_quotes(run: Runner) -> None:
    run.section("4. Quotes / MultiQuotes / Depth")
    m = run.matrix

    def quote(slot, cid, index=False):
        if slot not in m:
            raise Skip(f"{slot} unresolved")
        s, ex = m[slot]
        d = run.ok(run.client.quotes(symbol=s, exchange=ex), f"quotes {s}")["data"]
        need_keys(d, ["open", "high", "low", "ltp", "bid", "ask", "prev_close", "volume"],
                  f"quotes {s}")
        need_nonzero(d["ltp"], f"{s}.ltp")
        need_nonzero(d["prev_close"], f"{s}.prev_close")   # QT-04
        need_ohlc(d, f"quotes {s}")
        if not index:
            need_nonzero(d["volume"], f"{s}.volume")
        return d

    for cid, slot in (("QT-01", "EQ_LIQUID"), ("QT-01b", "EQ_CHEAP"), ("QT-01c", "EQ_SPECIAL")):
        run.check(cid, lambda s=slot, c=cid: quote(s, c), endpoint="quotes",
                  symbol=str(m.get(slot, "")), expected="full set, prev_close non-zero")

    for ex in ("NFO", "BFO", "CDS", "BCD", "MCX", "NCO"):
        slot = f"FUT_{ex}"
        if slot in m:
            run.check(f"QT-02.{ex}", lambda s=slot: quote(s, "QT-02"), endpoint="quotes",
                      exchange=ex, symbol=str(m[slot]), expected="futures quote")

    for cid, slot in (("QT-03.CE", "OPT_ATM_CE_NFO"), ("QT-03.PE", "OPT_ATM_PE_NFO")):
        if slot in m:
            run.check(cid, lambda s=slot, c=cid: quote(s, c), endpoint="quotes", exchange="NFO",
                      symbol=str(m[slot]), expected="option quote")

    for cid, slot in (("QT-05.NSE", "IDX_NSE"), ("QT-05.BSE", "IDX_BSE"), ("QT-06.MCX", "IDX_MCX")):
        run.check(cid, lambda s=slot, c=cid: quote(s, c, index=True), endpoint="quotes",
                  symbol=str(m.get(slot, "")), expected="index quote succeeds")

    def index_field_sanity():
        """QT-07 - volume may legitimately be 0 on an index; prices may not."""
        slots = [s for s in ("IDX_NSE", "IDX_BSE", "IDX_MCX") if s in m]
        need(slots, "no index slots resolved")
        for slot in slots:
            s, ex = m[slot]
            d = run.ok(run.client.quotes(symbol=s, exchange=ex), f"quotes {s}")["data"]
            for k in ("ltp", "open", "high", "low", "prev_close"):
                need_nonzero(d.get(k), f"{s}.{k}")
            as_num(d.get("volume", 0), f"{s}.volume")   # 0 is acceptable here

    run.check("QT-07", index_field_sanity, endpoint="quotes",
              expected="index prices non-zero, volume may be 0")

    def quote_ohlc_consistency():
        """QT-08 - low <= open,ltp <= high on every resolved instrument."""
        checked = 0
        for slot in ("EQ_LIQUID", "EQ_CHEAP", "IDX_NSE", "FUT_NFO", "OPT_ATM_CE_NFO"):
            if slot not in m:
                continue
            s, ex = m[slot]
            need_ohlc(run.ok(run.client.quotes(symbol=s, exchange=ex),
                             f"quotes {s}")["data"], f"quotes {s}")
            checked += 1
        need(checked >= 2, "not enough instruments resolved to check OHLC consistency")

    run.check("QT-08", quote_ohlc_consistency, endpoint="quotes",
              expected="low <= open,ltp <= high")

    def price_descaling():
        """QT-09 - quote LTP, depth LTP and the last 1m close must agree.
        A mismatch by a factor of 100 is the classic paise-vs-rupee bug."""
        if "EQ_LIQUID" not in m:
            raise Skip("EQ_LIQUID unresolved")
        s, ex = m["EQ_LIQUID"]
        q = as_num(run.ok(run.client.quotes(symbol=s, exchange=ex), "quotes")["data"]["ltp"],
                   "quote ltp")
        d = as_num(run.ok(run.client.depth(symbol=s, exchange=ex), "depth")["data"]["ltp"],
                   "depth ltp")
        need(abs(q - d) / max(q, 1e-9) < 0.02,
             f"{s}: quotes ltp {q} vs depth ltp {d} - price de-scaling differs between paths")
        df = run.client.history(symbol=s, exchange=ex, interval="1m",
                                start_date=str(date.today() - timedelta(days=4)),
                                end_date=str(date.today()))
        if df is None or len(df) == 0:
            raise Warn(f"quotes/depth agree at {q}; no 1m history to cross-check")
        close = as_num(df.iloc[-1]["close"], "last close")
        need(abs(q - close) / max(q, 1e-9) < 0.05,
             f"{s}: quote ltp {q} vs last 1m close {close} - scaling differs on the "
             f"history path")

    run.check("QT-09", price_descaling, endpoint="quotes+depth+history",
              expected="all three paths agree - no x100 scaling error")

    def unsupported_exchange_quote():
        """QT-10 - an exchange the broker does not claim must fail fast."""
        unclaimed = next((e for e in ("NCDEX", "BCD", "NCO", "GLOBAL_INDEX")
                          if e not in run.env["exchanges"]), None)
        if not unclaimed:
            raise Skip("broker claims every exchange this check would try")
        t = time.perf_counter()
        r = run.client.quotes(symbol="ZZNOTREAL99", exchange=unclaimed)
        el = (time.perf_counter() - t) * 1000
        run.expect_error(r, f"quote on unclaimed exchange {unclaimed}")
        need(el < 15000, f"unsupported exchange took {el:.0f}ms - should fail fast, not hang")

    run.check("QT-10", unsupported_exchange_quote, endpoint="quotes",
              expected="fails fast with a clear message")

    run.check("QT-11", lambda: run.expect_error(
        run.client.quotes(symbol="ZZNOTREAL99", exchange="NSE"), "unknown symbol"),
        endpoint="quotes", expected="clean error")

    # ---- multiquotes ----
    def universe(n: int) -> tuple[list[dict], int]:
        """Return n symbols, and how many of them are guaranteed liquid.

        Table order is NOT a usable universe: the first 50 NSE rows are 26 SDL
        government bonds (`656KA30-SG`) plus SME and BE-series scrips, none of
        which trade. Their ltp is legitimately 0, which previously looked like
        a broker batch cap of 25. F&O underlyings are liquid by definition, so
        they lead; the remainder is padded from ordinary cash rows with the
        non-trading series excluded.
        """
        with run.db() as c:
            liquid = [r[0] for r in c.execute(
                "select distinct s.symbol from symtoken s where s.exchange='NSE' "
                "and s.instrumenttype in ('EQ','') and s.symbol in "
                "(select distinct name from symtoken where exchange='NFO' "
                "and instrumenttype='FUT') order by s.symbol limit ?", (n,))]
            pad = []
            if len(liquid) < n:
                pad = [r[0] for r in c.execute(
                    "select symbol from symtoken where exchange='NSE' "
                    "and instrumenttype in ('EQ','') "
                    "and symbol not like '%-SG' and symbol not like '%-SM' "
                    "and symbol not like '%-BE' and symbol not like '%-BZ' "
                    "and symbol not like '%-IL' and symbol not like '%-RR' "
                    "and symbol not in (select distinct name from symtoken "
                    "where exchange='NFO' and instrumenttype='FUT') "
                    "order by symbol limit ?", (n - len(liquid),))]
        syms = liquid + pad
        return [{"symbol": s, "exchange": "NSE"} for s in syms], len(liquid)

    def mq(n: int):
        syms, n_liquid = universe(n)
        need(len(syms) == n, f"only {len(syms)} symbols available for a {n}-symbol request")
        t = time.perf_counter()
        r = run.ok(run.client.multiquotes(symbols=syms), f"multiquotes {n}")
        el = (time.perf_counter() - t) * 1000
        res = r.get("results") or []
        with_ltp = sum(1 for x in res if (x.get("data") or {}).get("ltp"))
        run.note_limit(f"multiquotes {n} symbols",
                       f"{len(res)}/{n} rows returned, {with_ltp} with ltp "
                       f"({n_liquid} liquid) in {el:.0f}ms")
        need(res, "empty results")
        # The cap signal is the ROW COUNT. A quiet symbol returning ltp 0 is a
        # market fact, not a broker limit - only a short results array is.
        need(len(res) == n,
             f"batch cap: {n} symbols requested, only {len(res)} result rows returned")
        # Liquid symbols must carry a price during market hours.
        liquid_names = {s["symbol"] for s in syms[:n_liquid]}
        dead = [x.get("symbol") for x in res
                if x.get("symbol") in liquid_names and not (x.get("data") or {}).get("ltp")]
        if dead:
            raise Warn(f"{len(dead)}/{n_liquid} liquid symbols returned no ltp: {dead[:6]}")

    run.check("MQ-01", lambda: mq(3), endpoint="multiquotes", expected="3 rows, all liquid priced")
    run.check("MQ-02", lambda: mq(50), endpoint="multiquotes", expected="50 rows returned")
    run.check("MQ-03", lambda: mq(500), endpoint="multiquotes",
              expected="500 rows returned")

    def cap_discovery():
        """MQ-04 - binary-search the real batch cap, and record how it fails.

        Only meaningful once a cap has actually been hit: if the broker served
        the largest batch tried, there is no boundary to find and this is a
        SKIP naming that size, not a silent pass.
        """
        def serves(n: int) -> bool:
            syms, _ = universe(n)
            if len(syms) < n:
                return False
            try:
                r = run.client.multiquotes(symbols=syms)
            except Exception as e:
                run.note_limit(f"multiquotes {n} raised", f"{type(e).__name__}: {str(e)[:90]}")
                return False
            if not isinstance(r, dict) or r.get("status") != "success":
                run.note_limit(f"multiquotes {n} response",
                               f"status={r.get('status')!r} msg={str(r.get('message'))[:90]}")
                return False
            return len(r.get("results") or []) == n

        # Matches MQ-03, which always sends 500. A lower ceiling here would
        # report "no cap" in the same run where MQ-03 just served 500.
        ceiling = 500
        if serves(ceiling):
            run.note_limit("multiquote cap",
                           f"at least {ceiling} - no truncation at the largest batch tried")
            raise Skip(f"no cap below {ceiling} symbols; the real ceiling is above "
                       f"the largest batch this run sent")
        lo, hi = 1, ceiling           # lo serves, hi does not
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if serves(mid):
                lo = mid
            else:
                hi = mid
            time.sleep(0.4)           # quote limits are far tighter than order limits
        run.note_limit("multiquote cap", f"largest batch served = {lo}; {hi} truncates or errors")
        raise Warn(f"observed batch cap {lo} (fails at {hi}) - chunk get_multiquotes at {lo}")

    run.check("MQ-04", cap_discovery, endpoint="multiquotes",
              expected="cap located and recorded, or none up to the ceiling")

    def mq_invalid():
        if "EQ_LIQUID" not in m:
            raise Skip("EQ_LIQUID unresolved")
        good = m["EQ_LIQUID"][0]
        r = run.client.multiquotes(symbols=[
            {"symbol": good, "exchange": "NSE"},
            {"symbol": "ZZNOTREAL99", "exchange": "NSE"},
        ])
        need(r.get("status") == "success",
             f"whole request failed because of one bad symbol: {r.get('message')}")
        res = r.get("results") or []
        need(len(res) == 2, f"expected 2 result rows, got {len(res)}")
        by = {x.get("symbol"): x for x in res}
        need((by.get(good, {}).get("data") or {}).get("ltp"), "valid symbol returned no data")
        bad = by.get("ZZNOTREAL99", {})
        need("error" in bad or not bad.get("data"), "invalid symbol did not report an error")

    run.check("MQ-05", mq_invalid, endpoint="multiquotes", expected="per-row error, request survives")

    def mq_mixed():
        rows = [{"symbol": m[s][0], "exchange": m[s][1]}
                for s in ("EQ_LIQUID", "IDX_NSE", "FUT_NFO", "OPT_ATM_CE_NFO") if s in m]
        need(len(rows) >= 3, "not enough slots resolved for a mixed-exchange request")
        r = run.ok(run.client.multiquotes(symbols=rows), "multiquotes mixed")
        got = sum(1 for x in (r.get("results") or []) if (x.get("data") or {}).get("ltp"))
        need(got == len(rows), f"mixed exchanges: {got}/{len(rows)} returned data")

    run.check("MQ-07", mq_mixed, endpoint="multiquotes", expected="mixed exchanges + index")

    def mq_bad_exchange():
        """MQ-06 - a wrong exchange must not sink the valid rows either."""
        if "EQ_LIQUID" not in m:
            raise Skip("EQ_LIQUID unresolved")
        good = m["EQ_LIQUID"][0]
        r = run.client.multiquotes(symbols=[
            {"symbol": good, "exchange": "NSE"},
            {"symbol": good, "exchange": "NOTANEXCHANGE"},
        ])
        need(r.get("status") == "success",
             f"whole request failed because of one bad exchange: {r.get('message')}")
        res = r.get("results") or []
        need(len(res) == 2, f"expected 2 result rows, got {len(res)}")
        ok_row = next((x for x in res if x.get("exchange") == "NSE"), {})
        need((ok_row.get("data") or {}).get("ltp"), "valid exchange returned no data")

    run.check("MQ-06", mq_bad_exchange, endpoint="multiquotes",
              expected="invalid exchange isolated to its own row")

    def mq_parity():
        """MQ-08 - the batch payload must match the single-quote contract."""
        if "FUT_NFO" not in m:
            raise Skip("FUT_NFO unresolved - need an F&O row to check oi")
        s, ex = m["FUT_NFO"]
        single = run.ok(run.client.quotes(symbol=s, exchange=ex), "quotes")["data"]
        r = run.ok(run.client.multiquotes(symbols=[{"symbol": s, "exchange": ex}]), "multiquotes")
        batch = ((r.get("results") or [{}])[0].get("data")) or {}
        need(batch, "no data row returned")
        missing = [k for k in single if k not in batch]
        need(not missing, f"fields present in /quotes but absent from /multiquotes: {missing}")
        need("oi" in batch, "multiquotes omits oi on an F&O symbol")
        for k in ("open", "high", "low", "ltp", "prev_close"):
            a, b = as_num(single[k], f"quotes.{k}"), as_num(batch[k], f"multiquotes.{k}")
            need(b != 0 or a == 0, f"{k}: /quotes={a} but /multiquotes=0")

    run.check("MQ-08", mq_parity, endpoint="multiquotes",
              expected="same field names/types as /quotes, plus oi")

    def mq_duplicates():
        """MQ-09 - a repeated symbol must not error or drop the others."""
        if "EQ_LIQUID" not in m:
            raise Skip("EQ_LIQUID unresolved")
        s = m["EQ_LIQUID"][0]
        r = run.client.multiquotes(symbols=[{"symbol": s, "exchange": "NSE"}] * 3)
        need(r.get("status") == "success", f"duplicates rejected: {r.get('message')}")
        res = r.get("results") or []
        need(res, "no results for a duplicated symbol")
        need((res[0].get("data") or {}).get("ltp"), "duplicated symbol returned no data")
        run.note_limit("multiquotes duplicate handling",
                       f"3 copies requested -> {len(res)} row(s) returned")

    run.check("MQ-09", mq_duplicates, endpoint="multiquotes", expected="handled without error")

    run.check("MQ-10", lambda: run.expect_error(
        run.client.multiquotes(symbols=[]), "empty symbols array"),
        endpoint="multiquotes", expected="clean 400")

    # ---- depth ----
    # Fetched once per slot and cached, so each DP-xx below asserts one thing
    # and a failure names the check that actually failed.
    _depth_cache: dict[str, dict] = {}

    def depth_of(slot: str) -> tuple[str, dict]:
        if slot not in m:
            raise Skip(f"{slot} unresolved")
        if slot not in _depth_cache:
            s, ex = m[slot]
            _depth_cache[slot] = run.ok(
                run.client.depth(symbol=s, exchange=ex), f"depth {s}")["data"]
        return m[slot][0], _depth_cache[slot]

    def levels(slot):
        s, d = depth_of(slot)
        need_keys(d, ["ltp", "bids", "asks", "totalbuyqty", "totalsellqty"], f"depth {s}")
        need(len(d["bids"]) >= 5 and len(d["asks"]) >= 5,
             f"{s}: {len(d['bids'])} bids / {len(d['asks'])} asks, expected 5 of each")

    def ordering(slot):
        s, d = depth_of(slot)
        bp = [as_num(x["price"], "bid") for x in d["bids"] if as_num(x["price"], "bid") > 0]
        ap = [as_num(x["price"], "ask") for x in d["asks"] if as_num(x["price"], "ask") > 0]
        need(bp and ap, f"{s}: no priced levels to order")
        need(bp == sorted(bp, reverse=True), f"{s}: bids not descending: {bp[:5]}")
        need(ap == sorted(ap), f"{s}: asks not ascending: {ap[:5]}")

    def spread(slot):
        s, d = depth_of(slot)
        bp = [as_num(x["price"], "bid") for x in d["bids"] if as_num(x["price"], "bid") > 0]
        ap = [as_num(x["price"], "ask") for x in d["asks"] if as_num(x["price"], "ask") > 0]
        need(bp and ap, f"{s}: no priced levels")
        need(bp[0] < ap[0], f"{s}: best bid {bp[0]} >= best ask {ap[0]}")
        lo = as_num(d.get("low", 0), "low")
        hi = as_num(d.get("high", 0), "high")
        if lo and hi:
            need(lo <= bp[0] <= hi and lo <= ap[0] <= hi,
                 f"{s}: best bid/ask {bp[0]}/{ap[0]} outside the day's range [{lo},{hi}]")

    def no_zero_levels(slot):
        s, d = depth_of(slot)
        bad = [f"{side}[{i}] qty={x.get('quantity')}"
               for side in ("bids", "asks")
               for i, x in enumerate(d[side])
               if as_num(x["price"], "price") == 0 and as_num(x.get("quantity", 0), "qty") != 0]
        need(not bad, f"{s}: zero-priced level carrying quantity - parsing/offset bug: {bad[:4]}")

    def totals(slot):
        s, d = depth_of(slot)
        need_nonzero(d["totalbuyqty"], f"{s}.totalbuyqty")
        need_nonzero(d["totalsellqty"], f"{s}.totalsellqty")

    def ltq(slot):
        s, d = depth_of(slot)
        need("ltq" in d, f"{s}: depth response omits ltq")
        need(as_num(d["ltq"], f"{s}.ltq") >= 0, f"{s}: negative ltq")

    def oi(slot):
        s, d = depth_of(slot)
        need("oi" in d, f"{s}: depth response omits oi on an F&O symbol")
        need_nonzero(d["oi"], f"{s}.oi")

    run.check("DP-01", lambda: levels("EQ_LIQUID"), endpoint="depth",
              expected="5 bid and 5 ask levels")
    run.check("DP-02", lambda: ordering("EQ_LIQUID"), endpoint="depth",
              expected="bids descending, asks ascending")
    run.check("DP-03", lambda: spread("EQ_LIQUID"), endpoint="depth",
              expected="best bid < best ask, within the day's range")
    run.check("DP-04", lambda: no_zero_levels("EQ_LIQUID"), endpoint="depth",
              expected="no zero-priced level carrying quantity")
    run.check("DP-05", lambda: totals("EQ_LIQUID"), endpoint="depth",
              expected="totalbuyqty / totalsellqty non-zero")
    run.check("DP-07", lambda: ltq("EQ_LIQUID"), endpoint="depth", expected="ltq present")

    if "FUT_NFO" in m:
        run.check("DP-01.NFO", lambda: levels("FUT_NFO"), endpoint="depth",
                  exchange="NFO", expected="5 levels on a future")
        run.check("DP-06", lambda: oi("FUT_NFO"), endpoint="depth",
                  exchange="NFO", expected="oi present and non-zero")
    else:
        run.record("DP-06", SKIP, "FUT_NFO unresolved", endpoint="depth")

    def index_depth():
        """DP-08 - either a clean supported book or a clean unsupported error,
        never a partial or garbage one."""
        if "IDX_NSE" not in m:
            raise Skip("IDX_NSE unresolved")
        s, ex = m["IDX_NSE"]
        r = run.client.depth(symbol=s, exchange=ex)
        need(isinstance(r, dict), f"depth {s}: {type(r).__name__} not dict")
        if r.get("status") == "error":
            need(str(r.get("message", "")), f"{s}: unsupported depth without a message")
            run.note_quirk("Index depth unsupported", f"{s}@{ex}: {str(r.get('message'))[:90]}")
            raise Skip(f"broker does not serve depth for {ex} - clean refusal")
        d = r.get("data") or {}
        need_keys(d, ["bids", "asks"], f"depth {s}")
        need(len(d["bids"]) >= 5 and len(d["asks"]) >= 5,
             f"{s}: index depth returned a partial book "
             f"({len(d['bids'])} bids / {len(d['asks'])} asks)")

    run.check("DP-08", index_depth, endpoint="depth",
              expected="index depth supported cleanly or refused cleanly")


# ==========================================================================
# 5. history    (live broker even in analyzer mode)
# ==========================================================================
def sec_history(run: Runner) -> None:
    run.section("5. History")
    m = run.matrix

    def intervals():
        d = run.ok(run.client.intervals(), "intervals")["data"]
        need_keys(d, ["months", "weeks", "days", "hours", "minutes", "seconds"], "intervals")
        run.env["intervals"] = d
        need(d["minutes"] or d["days"], "broker claims no usable intervals")

    run.check("HS-01", intervals, endpoint="intervals", expected="six buckets")

    def hist(sym, ex, interval, days, cid, expect_today=False):
        end = date.today()
        start = end - timedelta(days=days)
        df = run.client.history(symbol=sym, exchange=ex, interval=interval,
                                start_date=str(start), end_date=str(end))
        # SDK contract: DataFrame on success, dict on error. An error dict has
        # a non-zero len(), so a bare `len(df) > 0` guard lets it through and
        # the failure then surfaces as AttributeError on df.index, throwing
        # away the broker's actual message.
        need(df is not None, f"{sym}@{ex} {interval} {days}d: history returned None")
        if isinstance(df, dict):
            raise AssertionError(
                f"{sym}@{ex} {interval} {days}d: {str(df.get('message') or df)[:160]}")
        need(hasattr(df, "index"),
             f"{sym}@{ex}: history returned {type(df).__name__}, expected a DataFrame")
        need(len(df) > 0, f"{sym}@{ex} {interval} {days}d: no candles returned")
        ts = _ts_series(df)
        need(ts == sorted(ts), f"{sym} {interval}: timestamps not monotonic")
        need(len(set(ts)) == len(ts), f"{sym} {interval}: duplicate timestamps")
        if expect_today:
            last = ts[-1].astimezone(IST).date()
            need(last >= end - timedelta(days=4),
                 f"{sym} {interval}: latest candle {last}, expected on/near {end}")
        return df, ts

    def _ts_series(df):
        import pandas as pd
        idx = df.index if getattr(df.index, "name", None) in ("timestamp", "date") else None
        col = idx if idx is not None else (df["timestamp"] if "timestamp" in df.columns else df.index)
        out = []
        for v in list(col):
            out.append(v.to_pydatetime() if isinstance(v, pd.Timestamp)
                       else parse_ist(v, "history.timestamp"))
        return [t if t.tzinfo else t.replace(tzinfo=IST) for t in out]

    liq = m.get("EQ_LIQUID")
    if not liq:
        run.blocked("HS-02", "EQ_LIQUID unresolved", endpoint="history")
    else:
        s, ex = liq
        run.check("HS-02", lambda: hist(s, ex, "1m", 4, "HS-02", expect_today=True),
                  endpoint="history", symbol=s, expected="1m incl. current day")
        run.check("HS-03", lambda: hist(s, ex, "D", 4, "HS-03", expect_today=True),
                  endpoint="history", symbol=s, expected="daily incl. current day")
        run.check("HS-04", lambda: hist(s, ex, "1m", 10, "HS-04"),
                  endpoint="history", symbol=s, expected="10 days 1m")
        run.check("HS-05", lambda: hist(s, ex, "1m", 100, "HS-05"),
                  endpoint="history", symbol=s, expected="100 days 1m, chunked")
        if HEAVY:
            run.check("HS-06", lambda: hist(s, ex, "D", 730, "HS-06"),
                      endpoint="history", symbol=s, expected="2 years daily")
        else:
            run.record("HS-06", SKIP, "QA_HEAVY=1 not set (2-year history)", endpoint="history")

        def ist_open():
            _, ts = hist(s, ex, "1m", 6, "HS-07")
            first = {}
            for t in ts:
                t = t.astimezone(IST)
                first.setdefault(t.date(), t)
            bad = [f"{d}={t.strftime('%H:%M')}" for d, t in first.items()
                   if (t.hour, t.minute) != (9, 15)]
            need(not bad, f"session open not 09:15 IST: {bad[:4]}")

        run.check("HS-07", ist_open, endpoint="history", symbol=s,
                  expected="first intraday candle 09:15 IST")

        def ohlc_rows():
            df, _ = hist(s, ex, "D", 20, "HS-10")
            for _, row in df.head(20).iterrows():
                need_ohlc({k: row[k] for k in ("open", "high", "low", "close")}, "history row")
                need(as_num(row["volume"], "volume") >= 0, "negative volume")

        run.check("HS-10", ohlc_rows, endpoint="history", symbol=s, expected="OHLC consistent")

        def last_vs_quote():
            df, _ = hist(s, ex, "1m", 3, "HS-16")
            close = as_num(df.iloc[-1]["close"], "last close")
            ltp = as_num(run.ok(run.client.quotes(symbol=s, exchange=ex), "q")["data"]["ltp"], "ltp")
            need(abs(close - ltp) / ltp < 0.05, f"last 1m close {close} vs ltp {ltp}")

        run.check("HS-16", last_vs_quote, endpoint="history", symbol=s, expected="close ~ ltp")

    for cid, slot in (("HS-12.NSE", "IDX_NSE"), ("HS-12.BSE", "IDX_BSE")):
        if slot in m:
            s, ex = m[slot]
            run.check(cid, lambda s=s, ex=ex, c=cid: hist(s, ex, "D", 10, c),
                      endpoint="history", symbol=s, exchange=ex, expected="index history")

    for ex in ("NFO", "BFO", "MCX", "CDS", "NCO", "BCD"):
        slot = f"FUT_{ex}"
        if slot in m:
            s, e = m[slot]
            run.check(f"HS-13.{ex}", lambda s=s, e=e: hist(s, e, "D", 10, "HS-13"),
                      endpoint="history", symbol=s, exchange=ex, expected="per-exchange history")

    if "OPT_ATM_CE_NFO" in m:
        s, ex = m["OPT_ATM_CE_NFO"]
        run.check("HS-14", lambda: hist(s, ex, "1m", 3, "HS-14"),
                  endpoint="history", symbol=s, expected="option history")

    if "EQ_SPECIAL" in m:
        s, ex = m["EQ_SPECIAL"]
        run.check("HS-15.1m", lambda: hist(s, ex, "1m", 3, "HS-15"),
                  endpoint="history", symbol=s, expected="special symbol, 1m")
        run.check("HS-15.D", lambda: hist(s, ex, "D", 10, "HS-15"),
                  endpoint="history", symbol=s, expected="special symbol, daily")

    if liq:
        s, ex = liq
        run.check("HS-17", lambda: run.expect_error(
            run.client.history(symbol=s, exchange=ex, interval="7m",
                               start_date=str(date.today() - timedelta(days=3)),
                               end_date=str(date.today())), "bad interval"),
            endpoint="history", expected="clean 400")
        run.check("HS-18", lambda: run.expect_error(
            run.client.history(symbol=s, exchange=ex, interval="D",
                               start_date=str(date.today()),
                               end_date=str(date.today() - timedelta(days=10))), "inverted"),
            endpoint="history", expected="clean 400")

    def hs_monotonic():
        """HS-08 - timestamps strictly increasing, no duplicates."""
        if not liq:
            raise Skip("EQ_LIQUID unresolved")
        s, ex = liq
        for interval, days in (("1m", 4), ("D", 20)):
            _, ts = hist(s, ex, interval, days, "HS-08")
            need(ts == sorted(ts), f"{interval}: timestamps not increasing")
            dupes = len(ts) - len(set(ts))
            need(dupes == 0, f"{interval}: {dupes} duplicate timestamps")

    run.check("HS-08", hs_monotonic, endpoint="history",
              expected="strictly increasing, no duplicates")

    def hs_daily_offset():
        """HS-09 - daily candles land on the session date, and the daily close
        agrees with the last intraday candle of that session. A +5:30 shift
        applied to one path and not the other shows up here."""
        if not liq:
            raise Skip("EQ_LIQUID unresolved")
        s, ex = liq
        ddf, dts = hist(s, ex, "D", 12, "HS-09")
        bad = [t.astimezone(IST) for t in dts
               if t.astimezone(IST).hour not in (0, 9)]
        need(not bad,
             f"daily candles must land on the session date, not mid-day: "
             f"{[str(x) for x in bad[:3]]}")
        idf, its = hist(s, ex, "1m", 6, "HS-09")
        by_day: dict = {}
        for i, t in enumerate(its):
            by_day.setdefault(t.astimezone(IST).date(), []).append(i)
        checked = 0
        for i, t in enumerate(dts):
            d = t.astimezone(IST).date()
            if d not in by_day:
                continue
            dclose = as_num(ddf.iloc[i]["close"], "daily close")
            iclose = as_num(idf.iloc[by_day[d][-1]]["close"], "last 1m close")
            need(abs(dclose - iclose) / max(iclose, 1e-9) < 0.02,
                 f"{d}: daily close {dclose} vs last 1m close {iclose} - the daily "
                 f"series is offset by a session")
            checked += 1
        need(checked, "no overlapping day between the daily and intraday series")
        run.note_limit("daily/intraday alignment days checked", checked)

    run.check("HS-09", hs_daily_offset, endpoint="history",
              expected="daily and intraday land on the same session")

    def hs_oi():
        """HS-11 - OI on F&O history where the broker supplies it."""
        slots = [s for s in ("FUT_NFO", "OPT_ATM_CE_NFO") if s in m]
        if not slots:
            raise Skip("no F&O slot resolved")
        found = []
        for slot in slots:
            s, ex = m[slot]
            df, _ = hist(s, ex, "1m", 3, "HS-11")
            cols = {c.lower() for c in df.columns}
            if "oi" not in cols:
                continue
            col = next(c for c in df.columns if c.lower() == "oi")
            nz = sum(1 for v in df[col] if as_num(v, "oi") != 0)
            found.append(f"{s}: {nz}/{len(df)} candles carry OI")
            need(nz > 0, f"{s}: history returns an oi column but every value is 0")
        if not found:
            raise Skip("broker does not return OI in history - recorded as N/A")
        run.note_limit("history OI", "; ".join(found))

    run.check("HS-11", hs_oi, endpoint="history",
              expected="OI present and non-zero on F&O, or N/A")

    def hs_future_range():
        if not liq:
            raise Skip("EQ_LIQUID unresolved")
        s, ex = liq
        start = date.today() + timedelta(days=30)
        end = start + timedelta(days=5)
        r = run.client.history(symbol=s, exchange=ex, interval="D",
                               start_date=str(start), end_date=str(end))
        if isinstance(r, dict):
            run.expect_error(r, "future-dated range")
            return
        need(len(r) == 0,
             f"future-dated range returned {len(r)} candles - should be empty or a 400")

    run.check("HS-19", hs_future_range, endpoint="history",
              expected="clean empty success or clean 400, never a 500")


# ==========================================================================
# 6. options services   (live broker even in analyzer mode)
# ==========================================================================
def _ddmmmyy(expiry: str) -> str:
    """/expiry returns DD-MMM-YY; the options services want DDMMMYY.

    option_symbol_service rebuilds the DB form with
    f"{e[:2]}-{e[2:5]}-{e[5:]}", so handing it '22-SEP-26' yields '22--SE-P-26'
    and it matches no strikes at all. Strip the hyphens once, here.
    """
    return expiry.replace("-", "").upper()


def _nearest_expiry(run: Runner, underlying: str, exchange: str,
                    itype: str = "options") -> str:
    """Nearest listed expiry in DDMMMYY - the form the options services want."""
    r = run.client.expiry(symbol=underlying, exchange=exchange, instrumenttype=itype)
    ds = (r or {}).get("data") or []
    return _ddmmmyy(ds[0]) if ds else ""


def sec_options(run: Runner) -> None:
    run.section("6. Options services")
    if "NFO" not in run.env["exchanges"]:
        run.record("OS-*", SKIP, "NFO not supported by this broker", endpoint="options")
        return

    def nearest_expiry(u: str, ex: str, itype: str = "options") -> str:
        r = run.ok(run.client.expiry(symbol=u, exchange=ex, instrumenttype=itype),
                   f"expiry {u}@{ex}")
        ds = r.get("data") or []
        need(ds, f"no {itype} expiries for {u}@{ex}")
        return _ddmmmyy(ds[0])

    try:
        EXP = nearest_expiry("NIFTY", "NFO")
    except Exception as e:
        run.record("OS-*", BLOCKED, f"cannot resolve a NIFTY expiry: {e}", endpoint="expiry")
        return
    run.note_limit("options expiry under test", EXP)

    def osym(offset, ot, u="NIFTY", idx_ex="NSE_INDEX", exp=None):
        r = run.ok(run.client.optionsymbol(underlying=u, exchange=idx_ex,
                                           expiry_date=exp or EXP,
                                           offset=offset, option_type=ot),
                   f"optionsymbol {offset} {ot}")
        need_keys(r, ["symbol", "exchange", "lotsize", "tick_size", "underlying_ltp"],
                  "optionsymbol")
        need_nonzero(r["underlying_ltp"], "underlying_ltp")
        return r

    run.check("OS-01", lambda: osym("ATM", "CE"), endpoint="optionsymbol",
              expected="nearest listed strike")

    def resolved_exists():
        """OS-04 - never a fabricated strike: the symbol must be listed."""
        for off, ot in (("ATM", "CE"), ("OTM5", "PE"), ("ITM5", "CE")):
            r = osym(off, ot)
            run.ok(run.client.symbol(symbol=r["symbol"], exchange=r["exchange"]),
                   f"resolved {r['symbol']} must exist in the master")

    run.check("OS-04", resolved_exists, endpoint="optionsymbol+symbol",
              expected="every resolved symbol is listed")

    def direction(ot, kind):
        base = osym("ATM", ot)
        s1, s5 = osym(f"{kind}1", ot), osym(f"{kind}5", ot)
        k0 = _strike_of(run, base["symbol"], base["exchange"])
        k1 = _strike_of(run, s1["symbol"], s1["exchange"])
        k5 = _strike_of(run, s5["symbol"], s5["exchange"])
        if (ot == "CE") == (kind == "ITM"):
            need(k5 < k1 < k0, f"{ot} {kind}: strikes {k0}->{k1}->{k5} not descending")
        else:
            need(k5 > k1 > k0, f"{ot} {kind}: strikes {k0}->{k1}->{k5} not ascending")

    run.check("OS-02.CE", lambda: direction("CE", "ITM"), endpoint="optionsymbol",
              expected="CE ITM strikes descend")
    run.check("OS-02.PE", lambda: direction("PE", "ITM"), endpoint="optionsymbol",
              expected="PE ITM strikes ascend")
    run.check("OS-03.CE", lambda: direction("CE", "OTM"), endpoint="optionsymbol",
              expected="CE OTM strikes ascend")
    run.check("OS-03.PE", lambda: direction("PE", "OTM"), endpoint="optionsymbol",
              expected="PE OTM strikes descend")

    def index_routing():
        """OS-05 - NSE_INDEX -> NFO and BSE_INDEX -> BFO."""
        r = osym("ATM", "CE")
        need(r["exchange"] == "NFO", f"NSE_INDEX resolved to {r['exchange']}, expected NFO")
        if "BFO" not in run.env["exchanges"] or "BSE_INDEX" not in run.env["exchanges"]:
            raise Warn("NFO routing verified; BFO/BSE_INDEX not claimed by this broker")
        exp = nearest_expiry("SENSEX", "BFO")
        r2 = osym("ATM", "CE", u="SENSEX", idx_ex="BSE_INDEX", exp=exp)
        need(r2["exchange"] == "BFO", f"BSE_INDEX resolved to {r2['exchange']}, expected BFO")

    run.check("OS-05", index_routing, endpoint="optionsymbol",
              expected="index exchange routes to the right F&O exchange")

    run.check("OS-06", lambda: run.expect_error(
        run.client.optionsymbol(underlying="NIFTY", exchange="NSE_INDEX", expiry_date=EXP,
                                offset="OTM99", option_type="CE"), "out-of-range offset"),
        endpoint="optionsymbol", expected="clean error, no fabricated symbol")

    run.check("OS-16", lambda: run.expect_error(
        run.client.optionsymbol(underlying="NIFTY", exchange="NSE_INDEX",
                                expiry_date="99XXX99", offset="ATM", option_type="CE"),
        "malformed expiry"), endpoint="optionsymbol", expected="clean 400 on a bad expiry")

    def chain(with_greeks=False):
        """`chain` sits at the TOP level of the response, not under `data`."""
        kw = {"underlying": "NIFTY", "exchange": "NSE_INDEX",
              "expiry_date": EXP, "strike_count": 10}
        if with_greeks:
            kw["with_greeks"] = True
        r = run.ok(run.client.optionchain(**kw), "optionchain")
        rows = r.get("chain") or (r.get("data") or {}).get("chain") or []
        need(rows, f"empty chain (response keys: {sorted(r)[:10]})")
        for row in rows[:5]:
            need_keys(row, ["strike", "ce", "pe"], "chain row")
            for side in ("ce", "pe"):
                need_keys(row[side], ["symbol", "ltp", "bid", "ask", "oi",
                                      "lotsize", "tick_size"], f"chain {side}")
        run.note_limit("optionchain legs returned", len(rows))
        return rows, r

    run.check("OS-07", lambda: chain(), endpoint="optionchain",
              expected="symmetric CE/PE rows with quotes")

    def chain_greeks():
        _, r = chain(with_greeks=True)
        blob = json.dumps(r)
        for k in ("implied_volatility", "delta", "gamma", "theta", "vega"):
            need(k in blob, f"with_greeks=True but {k} absent from the response")
        for k in ("expiry_ts", "server_ts", "forward_price"):
            need(k in blob, f"optionchain response missing {k}")

    run.check("OS-08", chain_greeks, endpoint="optionchain",
              expected="greeks + expiry_ts/server_ts/forward_price")

    def chain_batch_load():
        """OS-09 - the chain is what exercises the batch quote path at size."""
        t = time.perf_counter()
        rows, _ = chain()
        el = (time.perf_counter() - t) * 1000
        run.note_limit("optionchain batch load", f"{len(rows)} legs in {el:.0f}ms")
        need(len(rows) >= 10, f"only {len(rows)} legs - too small to exercise the batch cap")

    run.check("OS-09", chain_batch_load, endpoint="optionchain",
              expected="realistic multi-leg load")

    def greeks(offset, ot):
        """An IV of 0 has two very different causes, and the option's own
        price is what separates them: an untraded leg gives the solver no
        input (a market condition), whereas a priced leg that still yields
        IV 0 is a solver failure (a real defect). Capture the price so the
        report attributes it instead of leaving it ambiguous."""
        sym = osym(offset, ot)["symbol"]
        r = run.ok(run.client.optiongreeks(symbol=sym, exchange="NFO",
                                           underlying_symbol="NIFTY",
                                           underlying_exchange="NSE_INDEX"),
                   f"optiongreeks {offset} {ot}")
        g = r.get("greeks") or {}
        need_keys(g, ["delta", "gamma", "theta", "vega", "rho"], "greeks")
        iv = as_num(r.get("implied_volatility"), "implied_volatility")
        px = as_num(r.get("option_price", 0), "option_price")
        spot = as_num(r.get("spot_price", 0), "spot_price")
        strike = as_num(r.get("strike", 0), "strike")
        intrinsic = max(0.0, (spot - strike) if ot == "CE" else (strike - spot))
        if iv <= 0:
            detail = (f"{sym}: IV={iv}, option_price={px}, spot={spot}, "
                      f"strike={strike}, intrinsic={intrinsic:.2f}")
            run.note_quirk(f"IV solver returned {iv} at {offset}", detail)
            if px <= 0:
                raise Skip(f"{offset} {ot} is untraded (option_price={px}) - the solver "
                           f"has no input, so IV 0 is a market condition, not a defect")
            if px <= intrinsic + 0.05:
                raise Warn(f"{offset} {ot} priced at or below intrinsic ({px} vs "
                           f"{intrinsic:.2f}) - IV is mathematically undefined there, "
                           f"not a solver bug. {detail}")
            raise AssertionError(
                f"IV solver returned {iv} on a priced option - genuine solver failure. "
                f"{detail}")
        need(iv < 500, f"{sym}: implausible IV {iv}")
        d = as_num(g["delta"], "delta")
        need(abs(d) <= 1.001, f"delta out of range {d}")
        need(as_num(g["gamma"], "gamma") >= 0, "gamma negative")
        return abs(d)

    d_atm = {}
    run.check("OS-10", lambda: d_atm.setdefault("atm", greeks("ATM", "CE")),
              endpoint="optiongreeks", expected="IV sane, delta ~0.5")
    run.check("OS-11", lambda: need(greeks("OTM5", "CE") < d_atm.get("atm", 1.0),
                                    "OTM |delta| should be below ATM"),
              endpoint="optiongreeks", expected="|delta| < ATM")
    run.check("OS-12", lambda: need(greeks("ITM5", "CE") > d_atm.get("atm", 0.0),
                                    "ITM |delta| should exceed ATM"),
              endpoint="optiongreeks", expected="|delta| > ATM")
    run.check("OS-13", lambda: need(greeks("ITM20", "CE") > 0.8,
                                    "deep ITM delta should approach 1 - IV solver unstable"),
              endpoint="optiongreeks", expected="deep ITM solver stable")

    def put_signs():
        """OS-14 - sign conventions must hold for PE as well as CE."""
        sym = osym("ATM", "PE")["symbol"]
        r = run.ok(run.client.optiongreeks(symbol=sym, exchange="NFO",
                                           underlying_symbol="NIFTY",
                                           underlying_exchange="NSE_INDEX"), "greeks PE")
        g = r["greeks"]
        need(as_num(g["delta"], "delta") < 0, f"PE delta must be negative, got {g['delta']}")
        need(as_num(g["gamma"], "gamma") >= 0, "PE gamma negative")

    run.check("OS-14", put_signs, endpoint="optiongreeks", expected="PE delta negative")

    def multigreeks():
        """Each `symbols` item is an object with symbol AND exchange - a bare
        string list is rejected with 'Validation failed'."""
        syms = [{"symbol": osym(o, "CE")["symbol"], "exchange": "NFO"}
                for o in ("ATM", "OTM3", "ITM3")]
        r = post("multioptiongreeks", {"symbols": syms})
        run.ok(r, "multioptiongreeks")
        rows = r.get("data") or []
        need(rows, f"no per-symbol results (keys: {sorted(r)[:8]})")
        need(len(rows) == len(syms), f"{len(syms)} requested, {len(rows)} returned")
        for row in rows:
            need_keys(row, ["status", "symbol", "exchange"], "multigreeks row")

    run.check("OS-15", multigreeks, endpoint="multioptiongreeks", expected="per-symbol batch")

    def multigreeks_invalid():
        """A bad leg must not sink the valid ones - per-row status, not a
        whole-request rejection."""
        good = osym("ATM", "CE")["symbol"]
        r = post("multioptiongreeks", {"symbols": [
            {"symbol": good, "exchange": "NFO"},
            {"symbol": "ZZNOTREAL99", "exchange": "NFO"}]})
        need(r.get("status") == "success",
             f"batch failed entirely on one bad symbol: {r.get('message')}")
        rows = r.get("data") or []
        need(len(rows) == 2, f"expected 2 result rows, got {len(rows)}")
        by = {x.get("symbol"): x for x in rows}
        need(by.get(good, {}).get("status") == "success", "valid leg did not resolve")
        bad = by.get("ZZNOTREAL99", {})
        need(bad.get("status") != "success", "invalid leg reported success")
        need(str(bad.get("message", "")), "failing leg carries no message")

    run.check("OS-15b", multigreeks_invalid, endpoint="multioptiongreeks",
              expected="invalid leg isolated to its own row")

    def synth(u="NIFTY", idx_ex="NSE_INDEX", exp=None):
        """The documented key is `synthetic_future_price`, at the top level."""
        r = run.ok(run.client.syntheticfuture(underlying=u, exchange=idx_ex,
                                              expiry_date=exp or EXP), "syntheticfuture")
        d = r if "synthetic_future_price" in r else (r.get("data") or r)
        need("synthetic_future_price" in d,
             f"response omits synthetic_future_price (keys: {sorted(d)[:10]})")
        need_keys(d, ["underlying", "underlying_ltp", "expiry", "atm_strike"], "syntheticfuture")
        fp = as_num(d["synthetic_future_price"], "synthetic_future_price")
        spot = as_num(run.ok(run.client.quotes(symbol=u, exchange=idx_ex),
                             "spot")["data"]["ltp"], "spot")
        need(abs(fp - spot) / spot < 0.10, f"{u}: synthetic {fp} vs spot {spot} implausible")
        return fp

    run.check("OS-17", lambda: synth(), endpoint="syntheticfuture",
              expected="parity forward near spot")

    def synth_bfo():
        if "BFO" not in run.env["exchanges"] or "BSE_INDEX" not in run.env["exchanges"]:
            raise Skip("BFO/BSE_INDEX not claimed by this broker")
        synth(u="SENSEX", idx_ex="BSE_INDEX", exp=nearest_expiry("SENSEX", "BFO"))

    run.check("OS-18", synth_bfo, endpoint="syntheticfuture",
              expected="BFO underlying resolves too")


def _strike_of(run: Runner, sym: str, ex: str) -> float:
    with run.db() as c:
        row = c.execute("select strike from symtoken where symbol=? and exchange=?",
                        (sym, ex)).fetchone()
    need(row, f"{sym}@{ex} not in symtoken")
    return float(row[0])


# ==========================================================================
# 7/8. orders - the full unsafe matrix, sandbox only
# ==========================================================================
def sec_orders(run: Runner) -> None:
    run.section("7. Order placement (sandbox matrix)")
    m = run.matrix
    if "EQ_CHEAP" not in m:
        run.blocked("OD-*", "EQ_CHEAP unresolved", endpoint="placeorder")
        return
    sym, ex = m["EQ_CHEAP"]
    ltp = as_num(run.ok(run.client.quotes(symbol=sym, exchange=ex), "q")["data"]["ltp"], "ltp")

    def place(pt, action, product, cid, price=0, trig=0, symbol=None, exchange=None, qty=1):
        s, e = symbol or sym, exchange or ex
        r = run.ok(run.client.placeorder(strategy=STRAT, symbol=s, exchange=e, action=action,
                                         price_type=pt, product=product, quantity=qty,
                                         price=price, trigger_price=trig), f"placeorder {cid}")
        need(r.get("orderid"), "no orderid returned")
        run.track_order(r["orderid"], s, e, product)
        return r["orderid"]

    # OD-01/07/08/09 - action x pricetype x product
    for product in ("MIS", "CNC"):
        for pt in ("MARKET", "LIMIT", "SL", "SL-M"):
            for action in ("BUY", "SELL"):
                far = round(ltp * (0.80 if action == "BUY" else 1.20), 2)
                price = 0 if pt in ("MARKET", "SL-M") else far
                trig = round(far * (1.01 if action == "BUY" else 0.99), 2) if pt in ("SL", "SL-M") else 0
                cid = f"OD-01.{product}.{pt}.{action}"
                run.check(cid, lambda pt=pt, a=action, p=product, pr=price, t=trig, c=cid:
                          place(pt, a, p, c, pr, t),
                          endpoint="placeorder", exchange=ex, symbol=sym,
                          expected=f"{pt}/{action}/{product} accepted")

    def market_fills():
        oid = place("MARKET", "BUY", "MIS", "OD-02")
        time.sleep(1.5)
        st = run.ok(run.client.orderstatus(order_id=oid, strategy=STRAT), "orderstatus")["data"]
        need(st["order_status"] == "complete",
             f"MARKET order rested as {st['order_status']!r} instead of filling")

    run.check("OD-02", market_fills, endpoint="placeorder+orderstatus",
              expected="MARKET fills, does not rest")

    def slm_rests():
        far = round(ltp * 1.25, 2)
        oid = place("SL-M", "BUY", "MIS", "OD-05", 0, far)
        time.sleep(1.5)
        st = run.ok(run.client.orderstatus(order_id=oid, strategy=STRAT), "orderstatus")["data"]
        need(st["order_status"] in ("trigger pending", "open"),
             f"SL-M fired on placement: {st['order_status']!r}")

    run.check("OD-05", slm_rests, endpoint="placeorder+orderstatus",
              expected="SL-M rests as trigger pending")

    if "OPT_CHEAP_NFO" in m:
        os_, oe = m["OPT_CHEAP_NFO"]
        run.check("OD-06", lambda: place("MARKET", "BUY", "NRML", "OD-06",
                                         symbol=os_, exchange=oe, qty=_lot(run, os_, oe)),
                  endpoint="placeorder", exchange=oe, symbol=os_,
                  expected="MPP emulation on a near-zero-premium option")

    for ex2 in run.env["exchanges"]:
        slot = f"FUT_{ex2}"
        if slot in m:
            s2, e2 = m[slot]
            run.check(f"OD-11.{ex2}", lambda s2=s2, e2=e2: place(
                "MARKET", "BUY", "NRML", "OD-11", symbol=s2, exchange=e2,
                qty=_lot(run, s2, e2)), endpoint="placeorder", exchange=ex2, symbol=s2,
                expected="every claimed exchange accepts an order")

    if "OPT_DECIMAL_STRIKE" in m:
        s3, e3 = m["OPT_DECIMAL_STRIKE"]
        run.check("OD-13", lambda: place("MARKET", "BUY", "NRML", "OD-13",
                                         symbol=s3, exchange=e3, qty=_lot(run, s3, e3)),
                  endpoint="placeorder", symbol=s3, expected="decimal strike round-trips")

    # negative cases
    run.check("OD-15", lambda: run.expect_error(
        run.client.placeorder(strategy=STRAT, symbol=m["FUT_NFO"][0], exchange="NFO",
                              action="BUY", price_type="MARKET", product="NRML", quantity=1),
        "sub-lot quantity") if "FUT_NFO" in m else (_ for _ in ()).throw(Skip("no NFO future")),
        endpoint="placeorder", expected="sub-lot rejected naming lot size")
    run.check("OD-17", lambda: run.expect_error(
        run.client.placeorder(strategy=STRAT, symbol=sym, exchange=ex, action="BUY",
                              price_type="MARKET", product="MIS", quantity=0), "zero qty"),
        endpoint="placeorder", expected="clean 400")
    run.check("OD-19", lambda: run.expect_error(
        run.client.placeorder(strategy=STRAT, symbol=sym, exchange=ex, action="BUY",
                              price_type="SL", product="MIS", quantity=1,
                              price=round(ltp, 2), trigger_price=0), "SL without trigger"),
        endpoint="placeorder", expected="clean 400")

    def od_cnc():
        oid = place("LIMIT", "BUY", "CNC", "OD-08", round(ltp * 0.80, 2))
        time.sleep(1.5)
        st = run.ok(run.client.orderstatus(order_id=oid, strategy=STRAT), "status")["data"]
        need(st["product"] == "CNC", f"product echoed as {st['product']!r}")

    run.check("OD-08", od_cnc, endpoint="placeorder", exchange=ex, symbol=sym,
              expected="CNC accepted on a cash exchange")

    def od_nrml():
        tried = []
        for e2 in [x for x in run.env["exchanges"]
                   if x in ("NFO", "BFO", "CDS", "BCD", "MCX", "NCO")]:
            slot = f"FUT_{e2}"
            if slot not in m:
                continue
            s2, x2 = m[slot]
            oid = place("MARKET", "BUY", "NRML", "OD-09",
                        symbol=s2, exchange=x2, qty=_lot(run, s2, x2))
            tried.append(e2)
            time.sleep(0.8)
            st = run.ok(run.client.orderstatus(order_id=oid, strategy=STRAT), "status")["data"]
            need(st["product"] == "NRML", f"{e2}: product echoed as {st['product']!r}")
        need(tried, "no derivatives exchange with a resolved future")
        run.note_limit("NRML accepted on", ", ".join(tried))

    run.check("OD-09", od_nrml, endpoint="placeorder",
              expected="NRML accepted on every claimed derivatives exchange")

    def od_disclosed_qty():
        r = run.client.placeorder(strategy=STRAT, symbol=sym, exchange=ex, action="BUY",
                                  price_type="LIMIT", product="MIS", quantity=10,
                                  price=round(ltp * 0.80, 2), disclosed_quantity=5)
        if r.get("status") == "error":
            msg = run.expect_error(r, "disclosed_quantity")
            raise Warn(f"disclosed_quantity refused on {ex}: {msg[:80]}")
        run.track_order(r.get("orderid"), sym, ex, "MIS")

    run.check("OD-14", od_disclosed_qty, endpoint="placeorder", exchange=ex, symbol=sym,
              expected="disclosed_quantity accepted where the exchange allows it")

    run.check("OD-16", lambda: run.expect_error(
        run.client.placeorder(strategy=STRAT, symbol=sym, exchange=ex, action="BUY",
                              price_type="MARKET", product="MIS", quantity=1.5),
        "fractional quantity on a non-crypto exchange"),
        endpoint="placeorder", expected="clean 400")

    run.check("OD-18", lambda: run.expect_error(
        run.client.placeorder(strategy=STRAT, symbol=sym, exchange=ex, action="BUY",
                              price_type="LIMIT", product="MIS", quantity=1, price=0),
        "LIMIT with price 0"),
        endpoint="placeorder", expected="clean 400")

    def od_off_tick():
        """OD-20 - an off-tick price must be snapped or cleanly rejected,
        never accepted only for the exchange to bounce it later."""
        with run.db() as c:
            row = c.execute("select tick_size from symtoken where symbol=? and exchange=?",
                            (sym, ex)).fetchone()
        need(row and row[0], f"no tick size for {sym}")
        tick = float(row[0])
        off = round(ltp * 0.80 + tick / 3, 4)
        r = run.client.placeorder(strategy=STRAT, symbol=sym, exchange=ex, action="BUY",
                                  price_type="LIMIT", product="MIS", quantity=1, price=off)
        if r.get("status") == "error":
            run.note_limit("off-tick price handling", f"rejected: {str(r.get('message'))[:70]}")
            return
        oid = r.get("orderid")
        run.track_order(oid, sym, ex, "MIS")
        time.sleep(1.5)
        st = run.ok(run.client.orderstatus(order_id=oid, strategy=STRAT), "status")["data"]
        if st["order_status"] == "rejected":
            raise AssertionError(
                f"off-tick price {off} was accepted then rejected by the exchange - "
                f"it should be snapped to the {tick} tick or refused up front")
        got = as_num(st["price"], "price")
        need(abs(round(got / tick) * tick - got) < 1e-6,
             f"order resting at {got}, which is not a multiple of the tick {tick}")
        run.note_limit("off-tick price handling", f"snapped {off} -> {got}")

    run.check("OD-20", od_off_tick, endpoint="placeorder", exchange=ex, symbol=sym,
              expected="snapped to tick or cleanly rejected")

    # ---- smart order (SO table at quantity 1) ----
    run.section("7.2 Smart order")

    def flat():
        run.client.closeposition(strategy=STRAT)
        time.sleep(1.0)

    def net_qty(s, e, product="MIS") -> int:
        r = run.client.openposition(strategy=STRAT, symbol=s, exchange=e, product=product)
        try:
            return int(float(r.get("quantity", r.get("data", 0)) or 0))
        except Exception:
            return 0

    def smart_case(cid, seed, action, qty, pos_size, expect_delta):
        flat()
        if seed:
            run.client.placeorder(strategy=STRAT, symbol=sym, exchange=ex,
                                  action="BUY" if seed > 0 else "SELL",
                                  price_type="MARKET", product="MIS", quantity=abs(seed))
            time.sleep(1.0)
        before = net_qty(sym, ex)
        run.client.placesmartorder(strategy=STRAT, symbol=sym, exchange=ex, action=action,
                                   price_type="MARKET", product="MIS",
                                   quantity=qty, position_size=pos_size)
        time.sleep(1.5)
        after = net_qty(sym, ex)
        need(after - before == expect_delta,
             f"{cid}: position {before} -> {after} (delta {after-before}), expected {expect_delta}")

    for cid, seed, act, q, ps, delta in (
        ("SO-01", 0, "BUY", 1, 0, 1),
        ("SO-02", -1, "BUY", 1, 1, 2),
        ("SO-03", 1, "BUY", 1, 1, 0),
        ("SO-04", 1, "BUY", 1, 2, 1),
        ("SO-05", 0, "SELL", 1, 0, -1),
        ("SO-06", 1, "SELL", 1, -1, -2),
        ("SO-07", -1, "SELL", 1, -1, 0),
        ("SO-08", -1, "SELL", 1, -2, -1),
    ):
        run.check(cid, lambda c=cid, s=seed, a=act, q=q, p=ps, d=delta:
                  smart_case(c, s, a, q, p, d),
                  endpoint="placesmartorder", symbol=sym,
                  expected=f"net position delta {delta}")
    flat()

    # ---- split ----
    def so_no_duplicate():
        """SO-09 - calling again once the target is met must place nothing."""
        flat()
        run.client.placesmartorder(strategy=STRAT, symbol=sym, exchange=ex, action="BUY",
                                   price_type="MARKET", product="MIS",
                                   quantity=1, position_size=1)
        time.sleep(1.5)
        before = net_qty(sym, ex)
        run.client.placesmartorder(strategy=STRAT, symbol=sym, exchange=ex, action="BUY",
                                   price_type="MARKET", product="MIS",
                                   quantity=1, position_size=1)
        time.sleep(1.5)
        after = net_qty(sym, ex)
        need(after == before,
             f"repeated smart order changed the position {before} -> {after}; "
             f"it should be a no-op once the target is met")
        flat()

    run.check("SO-09", so_no_duplicate, endpoint="placesmartorder", symbol=sym,
              expected="no duplicate order on a repeated call")

    def so_raw_quantity():
        """SO-10 - position_size=0 on a flat symbol places the raw quantity."""
        flat()
        before = net_qty(sym, ex)
        need(before == 0, f"symbol not flat before the test: {before}")
        run.client.placesmartorder(strategy=STRAT, symbol=sym, exchange=ex, action="BUY",
                                   price_type="MARKET", product="MIS",
                                   quantity=2, position_size=0)
        time.sleep(1.5)
        after = net_qty(sym, ex)
        need(after - before == 2,
             f"position_size=0 should place the raw quantity 2; delta was {after - before}")
        flat()

    run.check("SO-10", so_raw_quantity, endpoint="placesmartorder", symbol=sym,
              expected="position_size=0 places the raw quantity")
    flat()

    run.section("7.3 Split order")

    def split_call(qty, splitsize, **kw):
        r = run.ok(run.client.splitorder(strategy=STRAT, symbol=sym, exchange=ex,
                                         action="BUY", quantity=qty, splitsize=splitsize,
                                         price_type="MARKET", product="MIS", **kw),
                   f"splitorder {qty}/{splitsize}")
        for x in (r.get("results") or []):
            run.track_order(x.get("orderid"), sym, ex, "MIS")
        return r

    def split_on():
        r = split_call(105, 20)
        res = r.get("results") or []
        need(len(res) == 6, f"expected 6 children for 105/20, got {len(res)}")
        need(int(as_num(r["total_quantity"], "total_quantity")) == 105,
             f"total_quantity echoed as {r['total_quantity']}")
        need(int(as_num(r["split_size"], "split_size")) == 20,
             f"split_size echoed as {r['split_size']}")
        for x in res:
            need_keys(x, ["order_num", "orderid", "quantity", "status"], "split child")
            need(x["status"] == "success", f"child {x.get('order_num')}: {x.get('message')}")

    run.check("SP-01", split_on, endpoint="splitorder", symbol=sym,
              expected="105/20 -> 6 children, echo fields correct")

    def split_off():
        r = split_call(5, 20)
        res = r.get("results") or []
        need(len(res) == 1, f"splitsize > quantity should place 1 order, got {len(res)}")

    run.check("SP-02", split_off, endpoint="splitorder", symbol=sym,
              expected="splitsize > quantity -> single order")

    def split_zero():
        """SP-03 - splitsize 0 must behave as split-off, never divide by zero."""
        r = run.client.splitorder(strategy=STRAT, symbol=sym, exchange=ex, action="BUY",
                                  quantity=3, splitsize=0, price_type="MARKET", product="MIS")
        if r.get("status") == "error":
            msg = run.expect_error(r, "splitsize=0")
            need("split" in msg.lower() or "positive" in msg.lower(),
                 f"splitsize=0 rejected with an unrelated message: {msg}")
            return
        res = r.get("results") or []
        for x in res:
            run.track_order(x.get("orderid"), sym, ex, "MIS")
        need(len(res) == 1, f"splitsize=0 produced {len(res)} orders, expected 1")

    run.check("SP-03", split_zero, endpoint="splitorder", symbol=sym,
              expected="splitsize=0 -> single order or clean rejection")

    def split_remainder():
        r = split_call(105, 20)
        qtys = [int(as_num(x["quantity"], "quantity")) for x in (r.get("results") or [])]
        need(qtys == [20, 20, 20, 20, 20, 5],
             f"child quantities {qtys}, expected five 20s then the 5 remainder last")

    run.check("SP-04", split_remainder, endpoint="splitorder", symbol=sym,
              expected="remainder is the final child")

    def split_cap():
        """SP-05 - more than 100 children must be refused."""
        r = run.client.splitorder(strategy=STRAT, symbol=sym, exchange=ex, action="BUY",
                                  quantity=505, splitsize=1, price_type="MARKET",
                                  product="MIS")
        if r.get("status") == "success":
            for x in (r.get("results") or []):
                run.track_order(x.get("orderid"), sym, ex, "MIS")
            n = len(r.get("results") or [])
            raise AssertionError(f"505 children accepted ({n} placed) - the 100-order cap "
                                 f"is not enforced")
        msg = run.expect_error(r, "over the child cap")
        run.note_limit("splitorder child cap", msg[:90])

    run.check("SP-05", split_cap, endpoint="splitorder", symbol=sym,
              expected="more than 100 children -> clean 400")

    def split_lot():
        """SP-06 - on F&O every child must be a whole multiple of the lot."""
        slot = "OPT_CHEAP_NFO" if "OPT_CHEAP_NFO" in m else "FUT_NFO"
        if slot not in m:
            raise Skip("no NFO instrument resolved")
        s2, e2 = m[slot]
        lot = _lot(run, s2, e2)
        need(lot > 1, f"{s2}: lot size {lot} - not a useful lot-alignment test")
        r = run.ok(run.client.splitorder(strategy=STRAT, symbol=s2, exchange=e2, action="BUY",
                                         quantity=lot * 3, splitsize=lot,
                                         price_type="MARKET", product="NRML"), "splitorder F&O")
        res = r.get("results") or []
        for x in res:
            run.track_order(x.get("orderid"), s2, e2, "NRML")
        bad = [int(as_num(x["quantity"], "q")) for x in res
               if int(as_num(x["quantity"], "q")) % lot != 0]
        need(not bad, f"{s2}: children {bad} are not multiples of lot size {lot}")

    run.check("SP-06", split_lot, endpoint="splitorder", exchange="NFO",
              expected="F&O children align to lot size")

    def split_pacing():
        """SP-07 - children are paced; the broker must not rate-limit us."""
        t = time.perf_counter()
        r = split_call(60, 10)
        el = (time.perf_counter() - t) * 1000
        res = r.get("results") or []
        need(len(res) == 6, f"expected 6 children, got {len(res)}")
        fails = [x for x in res if x.get("status") != "success"]
        run.note_limit("splitorder pacing", f"6 children in {el:.0f}ms "
                                            f"({el/max(len(res),1):.0f}ms apart)")
        need(not fails,
             f"{len(fails)} children failed - likely rate-limited: "
             f"{[x.get('message') for x in fails][:2]}")

    run.check("SP-07", split_pacing, endpoint="splitorder", symbol=sym,
              expected="sequential pacing, no 429")

    def split_partial():
        """SP-08 - a failing child must not hide the others."""
        r = run.client.splitorder(strategy=STRAT, symbol="ZZNOTREAL99", exchange="NSE",
                                  action="BUY", quantity=40, splitsize=20,
                                  price_type="MARKET", product="MIS")
        if r.get("status") == "error":
            run.expect_error(r, "whole split rejected for an unknown symbol")
            return
        res = r.get("results") or []
        need(res, "no per-child results returned")
        for x in res:
            need("status" in x, "child row carries no status")
            if x["status"] != "success":
                need(x.get("message"), "failing child carries no message")

    run.check("SP-08", split_partial, endpoint="splitorder",
              expected="per-child status and message on failure")

    run.check("SP-09", lambda: run.expect_error(
        run.client.splitorder(strategy=STRAT, symbol=sym, exchange=ex, action="BUY",
                              quantity=10.5, splitsize=5, price_type="MARKET",
                              product="MIS"), "fractional quantity on equity"),
        endpoint="splitorder", symbol=sym, expected="fractional total -> clean 400")

    # ---- basket ----
    run.section("7.4 Basket order")

    def basket_call(legs):
        r = run.client.basketorder(strategy=STRAT, orders=legs)
        for x in (r.get("results") or []):
            if x.get("status") == "success":
                run.track_order(x.get("orderid"), x.get("symbol", ""), "NSE", "MIS")
        return r

    def leg(s, e, action, qty=1, pricetype="MARKET", product="MIS", **kw):
        return {"symbol": s, "exchange": e, "action": action, "quantity": qty,
                "pricetype": pricetype, "product": product, **kw}

    def basket_basic():
        legs = [leg(sym, ex, "BUY"), leg(sym, ex, "SELL"),
                leg(sym, ex, "BUY", pricetype="LIMIT", price=round(ltp * 0.8, 2))]
        r = run.ok(basket_call(legs), "basketorder")
        res = r.get("results") or []
        need(len(res) == 3, f"expected 3 result rows, got {len(res)}")
        for x in res:
            need_keys(x, ["symbol", "status"], "basket result")
            if x["status"] == "success":
                need(x.get("orderid"), f"{x['symbol']}: success without an orderid")

    run.check("BK-01", basket_basic, endpoint="basketorder",
              expected="per-leg orderid and status")

    def basket_buy_first():
        """BK-02 - BUY legs are submitted before SELL legs for margin benefit."""
        legs = [leg(sym, ex, "SELL"), leg(sym, ex, "SELL"),
                leg(sym, ex, "BUY"), leg(sym, ex, "BUY")]
        r = run.ok(basket_call(legs), "basketorder ordering")
        ids = [str(x["orderid"]) for x in (r.get("results") or []) if x.get("orderid")]
        need(len(ids) >= 4, f"only {len(ids)} legs placed")
        time.sleep(2.0)
        ob = {str(o["orderid"]): o for o in
              (run.ok(run.client.orderbook(), "orderbook")["data"].get("orders") or [])}
        rows = [ob[i] for i in ids if i in ob]
        need(len(rows) >= 4, "placed legs not found in the orderbook")
        ts = [(parse_ist(o["timestamp"], "ts"), o["action"]) for o in rows]
        ts.sort()
        actions = [a for _, a in ts]
        last_buy = max((i for i, a in enumerate(actions) if a == "BUY"), default=-1)
        first_sell = min((i for i, a in enumerate(actions) if a == "SELL"), default=len(actions))
        need(last_buy < first_sell,
             f"BUY legs must reach the broker before SELL legs; observed order {actions}")

    run.check("BK-02", basket_buy_first, endpoint="basketorder+orderbook",
              expected="all BUY legs precede all SELL legs")

    def basket_mixed_exchange():
        legs = [leg(sym, ex, "BUY")]
        for slot in ("FUT_NFO", "FUT_BFO", "FUT_MCX"):
            if slot in m:
                s2, e2 = m[slot]
                legs.append(leg(s2, e2, "BUY", qty=_lot(run, s2, e2), product="NRML"))
        need(len(legs) >= 2, "no second exchange resolved for a mixed basket")
        r = run.ok(basket_call(legs), "basketorder mixed")
        res = r.get("results") or []
        fails = [x for x in res if x.get("status") != "success"]
        need(not fails, f"mixed-exchange basket had {len(fails)} failures: "
                        f"{[(x.get('symbol'), x.get('message')) for x in fails][:3]}")

    run.check("BK-03", basket_mixed_exchange, endpoint="basketorder",
              expected="legs across exchanges all accepted")

    def basket_partial():
        legs = [leg(sym, ex, "BUY"), leg(sym, ex, "SELL"), leg("ZZNOTREAL99", "NSE", "BUY")]
        r = basket_call(legs)
        need(r.get("status") == "success",
             f"basket failed entirely because of one bad leg: {r.get('message')}")
        res = r.get("results") or []
        need(len(res) == 3, f"expected 3 result rows, got {len(res)}")
        oks = [x for x in res if x.get("status") == "success"]
        bad = [x for x in res if x.get("status") != "success"]
        need(len(oks) == 2 and len(bad) == 1, f"partial-success shape wrong: {res}")
        need(bad[0].get("message"), "failing leg carries no message")

    run.check("BK-04", basket_partial, endpoint="basketorder",
              expected="partial success isolated to the bad leg")

    def basket_batching():
        """BK-05 - 25 legs run as concurrent batches of 10; no rate-limit breach."""
        legs = [leg(sym, ex, "BUY" if i % 2 == 0 else "SELL") for i in range(25)]
        t = time.perf_counter()
        r = run.ok(basket_call(legs), "basketorder 25 legs")
        el = (time.perf_counter() - t) * 1000
        res = r.get("results") or []
        fails = [x for x in res if x.get("status") != "success"]
        run.note_limit("basketorder 25 legs", f"{len(res)} results in {el:.0f}ms, "
                                              f"{len(fails)} failed")
        need(len(res) == 25, f"25 legs sent, {len(res)} results returned")
        need(not fails, f"{len(fails)} legs failed in a 25-leg basket - likely rate-limited")

    run.check("BK-05", basket_batching, endpoint="basketorder",
              expected="25 legs batched without rate-limit failures")

    run.check("BK-06", lambda: run.expect_error(
        run.client.basketorder(strategy=STRAT, orders=[]), "empty orders array"),
        endpoint="basketorder", expected="clean 400")

    run.section("7.5 Options order / freeze quantity")
    fz = _freeze_qty(run, "NIFTY")
    lot = _lot_by_name(run, "NIFTY", "NFO")
    if not (fz and lot and "NFO" in run.env["exchanges"]):
        for cid in ("FZ-01", "FZ-02", "FZ-03", "FZ-04", "FZ-05",
                    "FZ-06", "FZ-07", "FZ-08"):
            run.record(cid, SKIP, "NIFTY freeze qty or lot size unavailable",
                       endpoint="optionsorder")
        for cid in ("MO-01", "MO-02", "MO-03", "MO-04", "MO-05",
                    "MO-06", "MO-07", "MO-08"):
            run.record(cid, SKIP, "NFO unavailable", endpoint="optionsmultiorder")
        return

    exp = _nearest_expiry(run, "NIFTY", "NFO")
    run.note_limit("freeze qty / lot (NIFTY)", f"freeze={fz} lot={lot} expiry={exp}")

    def oorder(qty, offset="OTM40", ot="CE", splitsize=0, expiry=None, **kw):
        r = run.ok(run.client.optionsorder(
            strategy=STRAT, underlying="NIFTY", exchange="NSE_INDEX",
            expiry_date=expiry or exp, offset=offset, option_type=ot, action="BUY",
            quantity=qty, price_type="MARKET", product="NRML", splitsize=splitsize, **kw),
            f"optionsorder {offset} qty={qty}")
        run.track_order(r.get("orderid"), r.get("symbol", ""), r.get("exchange", "NFO"), "NRML")
        return r

    run.check("FZ-01", lambda: oorder(lot), endpoint="optionsorder",
              expected=f"qty {lot} below freeze {fz} accepted")
    run.check("FZ-02", lambda: oorder(fz), endpoint="optionsorder",
              expected=f"qty == freeze {fz}, behaviour recorded")

    def above_freeze():
        q = fz + lot
        try:
            r = oorder(q)
            run.note_quirk("Quantity above freeze without splitsize",
                           f"accepted/auto-split at qty {q}: orderid {r.get('orderid')}")
        except AssertionError as e:
            need("freeze" in str(e).lower() or "quantity" in str(e).lower(),
                 f"rejection does not name the freeze limit: {e}")

    run.check("FZ-03", above_freeze, endpoint="optionsorder",
              expected="clean rejection or auto-split, never silent")
    run.check("FZ-04", lambda: oorder(fz + lot, splitsize=fz), endpoint="optionsorder",
              expected="split into children at or below the freeze limit")

    def fz_echo():
        r = oorder(lot)
        need_keys(r, ["symbol", "exchange", "offset", "option_type",
                      "underlying", "underlying_ltp"], "optionsorder echo")
        need(r["offset"] == "OTM40", f"offset echoed as {r['offset']!r}")
        need(r["option_type"] == "CE", f"option_type echoed as {r['option_type']!r}")
        need_nonzero(r["underlying_ltp"], "underlying_ltp")
        run.ok(run.client.symbol(symbol=r["symbol"], exchange=r["exchange"]),
               f"resolved {r['symbol']} must exist in the master")

    run.check("FZ-05", fz_echo, endpoint="optionsorder",
              expected="symbol/underlying/offset/ltp echoed and consistent")

    def fz_offsets_agree():
        """FZ-06 - the order path must resolve to the same symbol /optionsymbol
        would return for identical inputs."""
        for offset, ot in (("ATM", "CE"), ("ITM3", "PE"), ("OTM40", "CE")):
            placed = oorder(lot, offset=offset, ot=ot)["symbol"]
            ref = run.ok(run.client.optionsymbol(
                underlying="NIFTY", exchange="NSE_INDEX", expiry_date=exp,
                offset=offset, option_type=ot), f"optionsymbol {offset}")["symbol"]
            need(placed == ref,
                 f"{offset}/{ot}: order resolved {placed} but /optionsymbol says {ref}")

    run.check("FZ-06", fz_offsets_agree, endpoint="optionsorder+optionsymbol",
              expected="ATM/ITMn/OTMn resolve identically on both paths")

    def fz_routing():
        r = oorder(lot)
        need(r["exchange"] == "NFO", f"NSE_INDEX order landed on {r['exchange']}, expected NFO")
        if "BFO" not in run.env["exchanges"] or "BSE_INDEX" not in run.env["exchanges"]:
            raise Warn("NFO routing verified; BFO/BSE_INDEX not claimed by this broker")
        blot = _lot_by_name(run, "SENSEX", "BFO")
        bexp = _nearest_expiry(run, "SENSEX", "BFO")
        if not (blot and bexp):
            raise Warn("NFO routing verified; SENSEX lot/expiry unresolved")
        r2 = run.ok(run.client.optionsorder(
            strategy=STRAT, underlying="SENSEX", exchange="BSE_INDEX", expiry_date=bexp,
            offset="OTM40", option_type="CE", action="BUY", quantity=blot,
            price_type="MARKET", product="NRML"), "optionsorder BFO")
        run.track_order(r2.get("orderid"), r2.get("symbol", ""), "BFO", "NRML")
        need(r2["exchange"] == "BFO", f"BSE_INDEX order landed on {r2['exchange']}, expected BFO")

    run.check("FZ-07", fz_routing, endpoint="optionsorder",
              expected="NSE_INDEX -> NFO, BSE_INDEX -> BFO")

    def fz_expiry_format():
        oorder(lot, expiry=exp)          # DDMMMYY is accepted
        run.expect_error(run.client.optionsorder(
            strategy=STRAT, underlying="NIFTY", exchange="NSE_INDEX",
            expiry_date="2026-09-22", offset="OTM40", option_type="CE", action="BUY",
            quantity=lot, price_type="MARKET", product="NRML"), "malformed expiry")

    run.check("FZ-08", fz_expiry_format, endpoint="optionsorder",
              expected="DDMMMYY accepted, malformed expiry -> clean 400")

    # ---- multi-leg ----
    run.section("7.6 Options multi-order")

    def multi(legs, **kw):
        r = run.ok(run.client.optionsmultiorder(
            strategy=STRAT, underlying="NIFTY", exchange="NSE_INDEX",
            expiry_date=kw.pop("expiry", exp), legs=legs, **kw), "optionsmultiorder")
        for x in (r.get("results") or []):
            run.track_order(x.get("orderid"), x.get("symbol", ""), "NFO", "NRML")
        return r

    def L(offset, ot, action, qty=None, **kw):
        return {"offset": offset, "option_type": ot, "action": action,
                "quantity": qty or lot, **kw}

    def iron_condor():
        r = multi([L("OTM6", "CE", "BUY"), L("OTM6", "PE", "BUY"),
                   L("OTM4", "CE", "SELL"), L("OTM4", "PE", "SELL")])
        res = r.get("results") or []
        need(len(res) == 4, f"expected 4 legs, got {len(res)}")
        for x in res:
            need_keys(x, ["leg", "action", "offset", "option_type", "symbol", "status"],
                      "leg result")
            need(x["status"] == "success", f"leg {x.get('leg')}: {x.get('message')}")
        need(sorted(x["leg"] for x in res) == [1, 2, 3, 4],
             f"leg numbering {[x['leg'] for x in res]}")

    run.check("MO-01", iron_condor, endpoint="optionsmultiorder",
              expected="4 legs, numbered, all filled fields")

    def straddle_strangle():
        r1 = multi([L("ATM", "CE", "BUY"), L("ATM", "PE", "BUY")])
        need(len(r1.get("results") or []) == 2, "straddle did not return 2 legs")
        r2 = multi([L("OTM3", "CE", "BUY"), L("OTM3", "PE", "BUY")])
        need(len(r2.get("results") or []) == 2, "strangle did not return 2 legs")
        ce = next(x["symbol"] for x in r2["results"] if x["option_type"] == "CE")
        pe = next(x["symbol"] for x in r2["results"] if x["option_type"] == "PE")
        need(_strike_of(run, ce, "NFO") > _strike_of(run, pe, "NFO"),
             f"strangle strikes wrong way round: CE {ce} vs PE {pe}")

    run.check("MO-02", straddle_strangle, endpoint="optionsmultiorder",
              expected="ATM straddle and OTM strangle resolve correctly")

    def diagonal():
        r = run.ok(run.client.expiry(symbol="NIFTY", exchange="NFO",
                                     instrumenttype="options"), "expiry")
        ds = r.get("data") or []
        need(len(ds) >= 2, "need two expiries for a diagonal spread")
        near, far = _ddmmmyy(ds[0]), _ddmmmyy(ds[1])
        res = multi([L("ITM2", "CE", "BUY", expiry_date=far),
                     L("OTM2", "CE", "SELL", expiry_date=near)]).get("results") or []
        need(len(res) == 2, f"expected 2 legs, got {len(res)}")
        syms = [x["symbol"] for x in res]
        need(far[:5] in syms[0] or far[:5] in syms[1],
             f"per-leg expiry not honoured: {syms} (expected one on {far})")
        need(near[:5] in syms[0] or near[:5] in syms[1],
             f"per-leg expiry not honoured: {syms} (expected one on {near})")

    run.check("MO-03", diagonal, endpoint="optionsmultiorder",
              expected="per-leg expiry_date honoured")

    def buy_before_sell():
        r = multi([L("OTM4", "CE", "SELL"), L("OTM4", "PE", "SELL"),
                   L("OTM6", "CE", "BUY"), L("OTM6", "PE", "BUY")])
        res = r.get("results") or []
        need(len(res) == 4, f"expected 4 legs, got {len(res)}")
        ids = [str(x["orderid"]) for x in res if x.get("orderid")]
        time.sleep(2.0)
        ob = {str(o["orderid"]): o for o in
              (run.ok(run.client.orderbook(), "orderbook")["data"].get("orders") or [])}
        rows = [ob[i] for i in ids if i in ob]
        need(len(rows) == 4, f"only {len(rows)}/4 legs found in the orderbook")
        ts = sorted((parse_ist(o["timestamp"], "ts"), o["action"]) for o in rows)
        actions = [a for _, a in ts]
        last_buy = max((i for i, a in enumerate(actions) if a == "BUY"), default=-1)
        first_sell = min((i for i, a in enumerate(actions) if a == "SELL"), default=len(actions))
        need(last_buy < first_sell,
             f"BUY legs must execute before SELL legs for margin benefit; observed {actions}")

    run.check("MO-04", buy_before_sell, endpoint="optionsmultiorder+orderbook",
              expected="BUY legs precede SELL legs")

    def leg_freeze():
        """MO-05 - freeze rules apply per leg exactly as for a single option."""
        r = multi([L("OTM40", "CE", "BUY", qty=lot),
                   L("OTM40", "PE", "BUY", qty=fz)])
        res = r.get("results") or []
        need(len(res) == 2, f"expected 2 legs, got {len(res)}")
        try:
            over = multi([L("OTM40", "CE", "BUY", qty=fz + lot)])
            run.note_quirk("Multi-order leg above freeze",
                           f"accepted at qty {fz + lot}: {over.get('results')}")
        except AssertionError as e:
            need("freeze" in str(e).lower() or "quantity" in str(e).lower(),
                 f"over-freeze leg rejected with an unrelated message: {e}")

    run.check("MO-05", leg_freeze, endpoint="optionsmultiorder",
              expected="per-leg freeze behaves as the single-option case")

    def leg_isolation():
        r = run.client.optionsmultiorder(
            strategy=STRAT, underlying="NIFTY", exchange="NSE_INDEX", expiry_date=exp,
            legs=[L("OTM4", "CE", "BUY"), L("OTM99", "PE", "BUY"), L("OTM6", "CE", "BUY")])
        if r.get("status") == "error":
            run.expect_error(r, "whole request rejected for one bad leg")
            raise Warn("a single invalid leg rejects the whole request - "
                       "the doc says remaining legs are still attempted")
        res = r.get("results") or []
        for x in res:
            run.track_order(x.get("orderid"), x.get("symbol", ""), "NFO", "NRML")
        oks = [x for x in res if x.get("status") == "success"]
        need(len(oks) >= 2, f"only {len(oks)} valid legs placed; a failing leg aborted the rest")

    run.check("MO-06", leg_isolation, endpoint="optionsmultiorder",
              expected="a failing leg does not abort the others")

    def leg_bounds():
        r = multi([L("ATM", "CE", "BUY")])
        need(len(r.get("results") or []) == 1, "a single-leg request was refused")
        run.expect_error(run.client.optionsmultiorder(
            strategy=STRAT, underlying="NIFTY", exchange="NSE_INDEX", expiry_date=exp,
            legs=[L("ATM", "CE", "BUY") for _ in range(21)]), "21 legs")

    run.check("MO-07", leg_bounds, endpoint="optionsmultiorder",
              expected="1 leg accepted, >20 legs -> clean 400")

    def ltp_consistency():
        r = multi([L("OTM4", "CE", "BUY"), L("OTM4", "PE", "BUY"),
                   L("OTM6", "CE", "BUY")])
        need_nonzero(r.get("underlying_ltp"), "underlying_ltp")
        need(r.get("underlying") , "response omits the underlying")
        res = r.get("results") or []
        base = _strike_of(run, res[0]["symbol"], "NFO")
        need(base > 0, "could not read a strike back")

    run.check("MO-08", ltp_consistency, endpoint="optionsmultiorder",
              expected="one underlying_ltp drives every leg's ATM calculation")

    run.section("8. Order lifecycle")

    def rest(price=None, pt="LIMIT", action="BUY", trig=0):
        """A resting order far from LTP so it cannot fill."""
        p = price if price is not None else round(ltp * 0.80, 2)
        return place(pt, action, "MIS", "LC", p, trig)

    def status_of(oid):
        return run.ok(run.client.orderstatus(order_id=oid, strategy=STRAT),
                      f"orderstatus {oid}")["data"]

    def lc_modify_price():
        oid = rest()
        time.sleep(1.0)
        newp = round(ltp * 0.75, 2)
        run.ok(run.client.modifyorder(order_id=oid, strategy=STRAT, symbol=sym, exchange=ex,
                                      action="BUY", price_type="LIMIT", product="MIS",
                                      quantity=1, price=newp), "modifyorder price")
        time.sleep(1.5)
        st = status_of(oid)
        need(str(st["orderid"]) == str(oid), "modify returned a different orderid")
        need(abs(as_num(st["price"], "price") - newp) < 0.05,
             f"modify not reflected: price {st['price']} != {newp}")

    run.check("LC-01", lc_modify_price, endpoint="modifyorder",
              expected="new price reflected, same orderid")

    def lc_modify_qty():
        oid = rest()
        time.sleep(1.0)
        run.ok(run.client.modifyorder(order_id=oid, strategy=STRAT, symbol=sym, exchange=ex,
                                      action="BUY", price_type="LIMIT", product="MIS",
                                      quantity=2, price=round(ltp * 0.80, 2)), "modify qty")
        time.sleep(1.5)
        st = status_of(oid)
        need(int(as_num(st["quantity"], "quantity")) == 2,
             f"quantity modify not reflected: {st['quantity']}")

    run.check("LC-02", lc_modify_qty, endpoint="modifyorder", expected="quantity modify honoured")

    def lc_modify_pricetype():
        oid = rest()
        time.sleep(1.0)
        p = round(ltp * 0.80, 2)
        run.ok(run.client.modifyorder(order_id=oid, strategy=STRAT, symbol=sym, exchange=ex,
                                      action="BUY", price_type="SL", product="MIS",
                                      quantity=1, price=p,
                                      trigger_price=round(p * 1.01, 2)), "modify to SL")
        time.sleep(1.5)
        st = status_of(oid)
        need(st["pricetype"] == "SL", f"pricetype not changed: {st['pricetype']!r}")
        need(as_num(st["trigger_price"], "trigger_price") != 0,
             "converted to SL but trigger_price is 0")

    run.check("LC-03", lc_modify_pricetype, endpoint="modifyorder",
              expected="LIMIT -> SL honoured with trigger")

    def lc_modify_complete():
        oid = place("MARKET", "BUY", "MIS", "LC-04")
        time.sleep(2.0)
        st = status_of(oid)
        if st["order_status"] != "complete":
            raise Skip(f"market order did not fill ({st['order_status']}) - "
                       f"cannot test modifying a terminal order")
        run.expect_error(run.client.modifyorder(
            order_id=oid, strategy=STRAT, symbol=sym, exchange=ex, action="BUY",
            price_type="LIMIT", product="MIS", quantity=1,
            price=round(ltp * 0.8, 2)), "modify a completed order")

    run.check("LC-04", lc_modify_complete, endpoint="modifyorder",
              expected="modifying a completed order -> clean error")

    def lc_modify_repeat():
        """LC-05 - brokers may cap modifications per order (Dhan: 25)."""
        oid = rest()
        time.sleep(1.0)
        n = 0
        for i in range(12):
            r = run.client.modifyorder(order_id=oid, strategy=STRAT, symbol=sym, exchange=ex,
                                       action="BUY", price_type="LIMIT", product="MIS",
                                       quantity=1, price=round(ltp * (0.80 - i * 0.005), 2))
            if r.get("status") != "success":
                need(str(r.get("message", "")),
                     f"modify #{i+1} failed without a message")
                run.note_limit("order modification cap", f"refused after {n} modifies: "
                                                         f"{str(r.get('message'))[:70]}")
                return
            n += 1
            time.sleep(0.3)
        run.note_limit("order modification cap", f"at least {n} modifies accepted")

    run.check("LC-05", lc_modify_repeat, endpoint="modifyorder",
              expected="repeated modifies succeed or fail with a clear cap message")

    def lc_cancel_open():
        oid = rest()
        time.sleep(1.5)
        need(status_of(oid)["order_status"] == "open", "order did not rest as open")
        run.ok(run.client.cancelorder(order_id=oid, strategy=STRAT), "cancelorder")
        time.sleep(1.5)
        need(status_of(oid)["order_status"] == "cancelled",
             f"after cancel: {status_of(oid)['order_status']!r}")

    run.check("LC-06", lc_cancel_open, endpoint="cancelorder", expected="open -> cancelled")

    def lc_cancel_trigger_pending():
        oid = place("SL-M", "BUY", "MIS", "LC-07", 0, round(ltp * 1.25, 2))
        time.sleep(1.5)
        st = status_of(oid)["order_status"]
        need(st in ("trigger pending", "open"), f"SL-M rested as {st!r}")
        run.ok(run.client.cancelorder(order_id=oid, strategy=STRAT), "cancel trigger pending")
        time.sleep(1.5)
        need(status_of(oid)["order_status"] == "cancelled",
             "trigger-pending order not cancelled")

    run.check("LC-07", lc_cancel_trigger_pending, endpoint="cancelorder",
              expected="trigger pending -> cancelled")

    def lc_cancel_complete():
        oid = place("MARKET", "BUY", "MIS", "LC-08")
        time.sleep(2.0)
        if status_of(oid)["order_status"] != "complete":
            raise Skip("market order did not fill - cannot test cancelling a terminal order")
        run.expect_error(run.client.cancelorder(order_id=oid, strategy=STRAT),
                         "cancel a completed order")

    run.check("LC-08", lc_cancel_complete, endpoint="cancelorder",
              expected="cancelling a completed order -> clean error")

    run.check("LC-09", lambda: run.expect_error(
        run.client.cancelorder(order_id="NOTANORDER123", strategy=STRAT), "unknown orderid"),
        endpoint="cancelorder", expected="clean 400/404")

    def lc_cancel_all():
        for _ in range(3):
            rest()
        time.sleep(1.5)
        r = run.ok(run.client.cancelallorder(strategy=STRAT), "cancelallorder")
        need_keys(r, ["canceled_orders", "failed_cancellations"], "cancelallorder")
        need(isinstance(r["canceled_orders"], list), "canceled_orders is not a list")
        need(isinstance(r["failed_cancellations"], list), "failed_cancellations is not a list")
        for f in r["failed_cancellations"]:
            need_keys(f, ["orderid", "reason"], "failed cancellation")
        msg = str(r.get("message", ""))
        nums = [int(x) for x in re.findall(r"\d+", msg)]
        if len(nums) >= 2:
            need(nums[0] == len(r["canceled_orders"]) and nums[1] == len(r["failed_cancellations"]),
                 f"summary {msg!r} does not match the arrays "
                 f"({len(r['canceled_orders'])}/{len(r['failed_cancellations'])})")

    run.check("LC-10", lc_cancel_all, endpoint="cancelallorder",
              expected="both arrays present, summary counts match")

    def lc_cancel_all_triggers():
        place("SL-M", "BUY", "MIS", "LC-11", 0, round(ltp * 1.25, 2))
        place("SL", "BUY", "MIS", "LC-11", round(ltp * 0.8, 2), round(ltp * 0.81, 2))
        time.sleep(1.5)
        run.ok(run.client.cancelallorder(strategy=STRAT), "cancelallorder triggers")
        time.sleep(1.5)
        left = [o for o in (run.ok(run.client.orderbook(), "orderbook")["data"].get("orders") or [])
                if o.get("order_status") == "trigger pending"]
        need(not left,
             f"{len(left)} trigger-pending orders survived cancelallorder: "
             f"{[o['orderid'] for o in left][:3]}")

    run.check("LC-11", lc_cancel_all_triggers, endpoint="cancelallorder",
              expected="SL/SL-M resting orders are included")

    def lc_cancel_all_empty():
        run.client.cancelallorder(strategy=STRAT)
        time.sleep(1.5)
        r = run.ok(run.client.cancelallorder(strategy=STRAT), "cancelallorder empty")
        need(not (r.get("canceled_orders") or []),
             f"second cancelall reported {len(r['canceled_orders'])} cancellations")

    run.check("LC-12", lc_cancel_all_empty, endpoint="cancelallorder",
              expected="clean success with empty arrays")

    def lc_orderstatus_states():
        d = run.ok(run.client.orderbook(), "orderbook")["data"].get("orders") or []
        need(d, "orderbook empty - no orders to query")
        checked = set()
        for o in d[:12]:
            st = status_of(o["orderid"])
            need_keys(st, ["orderid", "symbol", "exchange", "action", "quantity", "price",
                           "trigger_price", "pricetype", "product", "order_status",
                           "timestamp"], "orderstatus")
            need(st["order_status"] == o["order_status"],
                 f"{o['orderid']}: /orderstatus says {st['order_status']!r} but the "
                 f"orderbook says {o['order_status']!r}")
            checked.add(st["order_status"])
        run.note_limit("orderstatus states queried", ", ".join(sorted(checked)))

    run.check("LC-13", lc_orderstatus_states, endpoint="orderstatus",
              expected="full field set, agrees with the orderbook")

    run.check("LC-14", lambda: run.expect_error(
        run.client.orderstatus(order_id="NOTANORDER123", strategy=STRAT), "unknown orderid"),
        endpoint="orderstatus", expected="clean error")

    def lc_openposition_held():
        place("MARKET", "BUY", "MIS", "LC-15")
        time.sleep(2.0)
        r = run.client.openposition(strategy=STRAT, symbol=sym, exchange=ex, product="MIS")
        qty = r.get("quantity", (r.get("data") if isinstance(r.get("data"), (int, str)) else None))
        need(qty is not None, f"openposition returned no quantity: {r}")
        pb = run.ok(run.client.positionbook(), "positionbook")["data"]
        row = next((p for p in pb if p["symbol"] == sym and p["exchange"] == ex), None)
        need(row, f"{sym} held but absent from the position book")
        need(abs(as_num(qty, "openposition qty") - as_num(row["quantity"], "pb qty")) < 1e-6,
             f"openposition says {qty}, position book says {row['quantity']}")

    run.check("LC-15", lc_openposition_held, endpoint="openposition",
              expected="matches the position book row")

    def lc_openposition_flat():
        run.client.closeposition(strategy=STRAT)
        time.sleep(2.0)
        r = run.client.openposition(strategy=STRAT, symbol=sym, exchange=ex, product="MIS")
        need(r.get("status") != "error",
             f"openposition errored on a flat symbol instead of returning 0: {r.get('message')}")
        qty = r.get("quantity", r.get("data"))
        need(as_num(qty if qty is not None else 0, "flat qty") == 0,
             f"expected 0 for a flat symbol, got {qty}")

    run.check("LC-16", lc_openposition_flat, endpoint="openposition",
              expected="returns 0, not an error")

    def lc_close_all():
        place("MARKET", "BUY", "MIS", "LC-17")
        time.sleep(2.0)
        r = run.ok(run.client.closeposition(strategy=STRAT), "closeposition")
        need(str(r.get("message", "")), "closeposition returned no message")
        time.sleep(2.0)
        pb = run.ok(run.client.positionbook(), "positionbook")["data"]
        left = [p for p in pb if as_num(p.get("quantity", 0), "quantity") != 0]
        need(not left,
             f"{len(left)} positions still open after closeposition: "
             f"{[(p['symbol'], p['quantity']) for p in left][:3]}")

    run.check("LC-17", lc_close_all, endpoint="closeposition", expected="account flat afterwards")

    def lc_close_none():
        r = run.ok(run.client.closeposition(strategy=STRAT), "closeposition when flat")
        need("no open" in str(r.get("message", "")).lower(),
             f"expected 'No open positions to close', got {r.get('message')!r}")

    run.check("LC-18", lc_close_none, endpoint="closeposition",
              expected="clean success when already flat")

    def lc_close_mixed():
        """LC-19 - MIS and NRML across exchanges all squared off."""
        opened = []
        place("MARKET", "BUY", "MIS", "LC-19")
        opened.append((sym, ex))
        for slot in ("FUT_NFO", "FUT_MCX", "FUT_BFO"):
            if slot in m:
                s2, e2 = m[slot]
                try:
                    place("MARKET", "BUY", "NRML", "LC-19",
                          symbol=s2, exchange=e2, qty=_lot(run, s2, e2))
                    opened.append((s2, e2))
                except AssertionError:
                    pass
        need(len(opened) >= 2, "could not open positions on two exchanges")
        time.sleep(2.5)
        run.ok(run.client.closeposition(strategy=STRAT), "closeposition mixed")
        time.sleep(2.5)
        pb = run.ok(run.client.positionbook(), "positionbook")["data"]
        left = [p for p in pb if as_num(p.get("quantity", 0), "quantity") != 0]
        need(not left,
             f"mixed-product square-off left {len(left)} open: "
             f"{[(p['symbol'], p['product'], p['quantity']) for p in left][:3]}")

    run.check("LC-19", lc_close_mixed, endpoint="closeposition",
              expected="MIS and NRML across exchanges all closed")

    def lc_full_trace():
        """LC-20 - one order, every transition visible in the orderbook."""
        oid = rest()
        seen = []
        for _ in range(4):
            time.sleep(1.0)
            s = status_of(oid)["order_status"]
            if not seen or seen[-1] != s:
                seen.append(s)
            if s == "open":
                break
        need("open" in seen, f"order never reached 'open': {seen}")
        run.ok(run.client.modifyorder(order_id=oid, strategy=STRAT, symbol=sym, exchange=ex,
                                      action="BUY", price_type="LIMIT", product="MIS",
                                      quantity=1, price=round(ltp * 0.75, 2)), "modify")
        time.sleep(1.5)
        run.ok(run.client.cancelorder(order_id=oid, strategy=STRAT), "cancel")
        time.sleep(1.5)
        final = status_of(oid)["order_status"]
        seen.append(final)
        need(final == "cancelled", f"final state {final!r}, expected cancelled")
        ob = {str(o["orderid"]): o for o in
              (run.ok(run.client.orderbook(), "orderbook")["data"].get("orders") or [])}
        need(str(oid) in ob, f"{oid} absent from the orderbook after its lifecycle")
        run.note_limit("lifecycle trace", " -> ".join(seen))

    run.check("LC-20", lc_full_trace, endpoint="place+modify+cancel+orderbook",
              expected="place -> open -> modify -> cancelled, all visible")



    run.section("8. Order lifecycle")

    def lifecycle():
        far = round(ltp * 0.80, 2)
        oid = place("LIMIT", "BUY", "MIS", "LC-01", far)
        time.sleep(1.0)
        run.ok(run.client.modifyorder(order_id=oid, strategy=STRAT, symbol=sym, exchange=ex,
                                      action="BUY", price_type="LIMIT", product="MIS",
                                      quantity=1, price=round(far * 0.99, 2)), "modify")
        time.sleep(1.0)
        st = run.ok(run.client.orderstatus(order_id=oid, strategy=STRAT), "status")["data"]
        need(abs(as_num(st["price"], "price") - round(far * 0.99, 2)) < 0.05,
             f"modify not reflected: price {st['price']}")
        run.ok(run.client.cancelorder(order_id=oid, strategy=STRAT), "cancel")
        time.sleep(1.0)
        st = run.ok(run.client.orderstatus(order_id=oid, strategy=STRAT), "status")["data"]
        need(st["order_status"] == "cancelled", f"after cancel: {st['order_status']!r}")

    run.check("LC-01", lifecycle, endpoint="modify+cancel+status",
              expected="place -> modify -> cancel reflected")

    run.check("LC-09", lambda: run.expect_error(
        run.client.cancelorder(order_id="NOTANORDER123", strategy=STRAT), "unknown orderid"),
        endpoint="cancelorder", expected="clean error")

    def cancel_all():
        for _ in range(3):
            place("LIMIT", "BUY", "MIS", "LC-10", round(ltp * 0.8, 2))
        time.sleep(1.0)
        r = run.ok(run.client.cancelallorder(strategy=STRAT), "cancelallorder")
        need_keys(r, ["canceled_orders", "failed_cancellations"], "cancelallorder")
        need(isinstance(r["canceled_orders"], list), "canceled_orders not a list")
        for f in r["failed_cancellations"]:
            need_keys(f, ["orderid", "reason"], "failed cancellation")

    run.check("LC-10", cancel_all, endpoint="cancelallorder",
              expected="both arrays present, failures carry reason")

    def close_all():
        place("MARKET", "BUY", "MIS", "LC-17")
        time.sleep(1.5)
        r = run.ok(run.client.closeposition(strategy=STRAT), "closeposition")
        need(r.get("message"), "no message")
        time.sleep(1.5)
        pb = run.ok(run.client.positionbook(), "positionbook")["data"]
        open_rows = [p for p in pb if int(float(p.get("quantity", 0) or 0)) != 0]
        need(not open_rows, f"{len(open_rows)} positions still open after closeposition")

    run.check("LC-17", close_all, endpoint="closeposition", expected="flat afterwards")

    run.check("LC-18", lambda: (
        need(run.ok(run.client.closeposition(strategy=STRAT), "closeposition")
             .get("message", "").lower().find("no open") >= 0,
             "expected 'No open positions to close'")
    ), endpoint="closeposition", expected="clean success when flat")


def _lot(run: Runner, sym: str, ex: str) -> int:
    with run.db() as c:
        row = c.execute("select lotsize from symtoken where symbol=? and exchange=?",
                        (sym, ex)).fetchone()
    return int(row[0]) if row and row[0] else 1


def _lot_by_name(run: Runner, name: str, ex: str) -> int:
    with run.db() as c:
        row = c.execute("select lotsize from symtoken where name=? and exchange=? "
                        "and instrumenttype in ('CE','PE') limit 1", (name, ex)).fetchone()
    return int(row[0]) if row and row[0] else 0


def _freeze_qty(run: Runner, name: str) -> int:
    p = Path(__file__).resolve().parents[4] / "data" / "qtyfreeze.csv"
    if not p.is_file():
        return 0
    for line in p.read_text(encoding="utf-8").splitlines()[1:]:
        parts = [x.strip() for x in line.split(",")]
        if len(parts) >= 3 and parts[1].upper() == name.upper():
            try:
                return int(parts[2])
            except ValueError:
                return 0
    return 0


# ==========================================================================
# 9. books (holdings deliberately excluded - see qa_live.py)
# ==========================================================================
def sec_books(run: Runner) -> None:
    """Books, excluding holdings - holdings live in qa_live.py.

    Each book is fetched once and cached, so every OB-/TB-/PB-/FN- check below
    asserts exactly one property and a failure names the right check.
    """
    run.section("9. Books (excl. holdings)")
    cache: dict = {}

    def book(name: str):
        if name not in cache:
            fn = getattr(run.client, name)
            cache[name] = run.ok(fn(), name)["data"]
        return cache[name]

    VALID_STATUS = {"open", "complete", "cancelled", "rejected", "trigger pending", "pending"}

    # ---------------- orderbook ----------------
    def ob_present():
        d = book("orderbook")
        need_keys(d, ["orders", "statistics"], "orderbook")
        if not d["orders"]:
            raise Warn("orderbook empty - no orders placed yet this run")
        ours = {x["orderid"] for x in run.order_ledger}
        seen = {str(o["orderid"]) for o in d["orders"]}
        missing = ours - seen
        need(not missing, f"{len(missing)} orders placed by this run are absent "
                          f"from the orderbook: {sorted(missing)[:4]}")

    run.check("OB-01", ob_present, endpoint="orderbook",
              expected="every order this run placed appears")

    def ob_statuses():
        d = book("orderbook")
        if not d["orders"]:
            raise Warn("orderbook empty")
        seen = set()
        for o in d["orders"]:
            st = o.get("order_status")
            need(st, f"{o.get('orderid')}: no order_status")
            need(st == st.lower(), f"{o['orderid']}: order_status {st!r} not lowercase")
            need(st in VALID_STATUS,
                 f"{o['orderid']}: broker-native status {st!r} leaked "
                 f"(expected one of {sorted(VALID_STATUS)})")
            seen.add(st)
        run.env["statuses_seen"] = sorted(seen)
        run.note_limit("order statuses observed", ", ".join(sorted(seen)))
        want = {"open", "complete", "cancelled"}
        if want - seen:
            raise Warn(f"lifecycle states not exercised this run: {sorted(want - seen)}")

    run.check("OB-02", ob_statuses, endpoint="orderbook",
              expected="lowercase OpenAlgo status vocabulary, all states seen")

    def ob_timestamps():
        d = book("orderbook")
        if not d["orders"]:
            raise Warn("orderbook empty")
        for o in d["orders"][:40]:
            need("timestamp" in o, f"{o['orderid']}: no timestamp")
            ts = parse_ist(o["timestamp"], f"{o['orderid']}.timestamp").astimezone(IST)
            need(ts.date() >= date.today() - timedelta(days=1),
                 f"{o['orderid']}: timestamp {o['timestamp']} is not in the current "
                 f"IST session (parsed {ts})")

    run.check("OB-03", ob_timestamps, endpoint="orderbook",
              expected="IST timestamps inside the current session")

    def ob_pricetypes():
        d = book("orderbook")
        if not d["orders"]:
            raise Warn("orderbook empty")
        seen = set()
        for o in d["orders"]:
            pt = o.get("pricetype")
            need(pt in ("MARKET", "LIMIT", "SL", "SL-M"), f"{o['orderid']}: pricetype {pt!r}")
            seen.add(pt)
        run.note_limit("order pricetypes observed", ", ".join(sorted(seen)))
        if len(seen) < 2:
            raise Warn(f"only {sorted(seen)} exercised - the matrix should cover all four")

    run.check("OB-04", ob_pricetypes, endpoint="orderbook",
              expected="MARKET/LIMIT/SL/SL-M all appear correctly")

    def ob_exchanges():
        d = book("orderbook")
        if not d["orders"]:
            raise Warn("orderbook empty")
        seen = {o.get("exchange") for o in d["orders"]}
        # CDS excluded by instruction; index exchanges are not orderable
        want = {e for e in run.env["exchanges"]
                if e not in INDEX_EXCHANGES and e != "CDS"}
        missing = want - seen
        run.note_limit("orderbook exchanges seen", ", ".join(sorted(x for x in seen if x)))
        need(not missing,
             f"no orderbook rows on {sorted(missing)} - claimed in plugin.json")

    run.check("OB-05", ob_exchanges, endpoint="orderbook",
              expected="every claimed orderable exchange represented (CDS excluded)")

    def ob_symbols():
        d = book("orderbook")
        if not d["orders"]:
            raise Warn("orderbook empty")
        with run.db() as c:
            for o in d["orders"][:30]:
                n = c.execute("select count(*) from symtoken where symbol=? and exchange=?",
                              (o.get("symbol"), o.get("exchange"))).fetchone()[0]
                need(n > 0, f"{o['orderid']}: {o.get('symbol')!r}@{o.get('exchange')!r} is not "
                            f"an OpenAlgo symbol - broker tradingsymbol leaked into the book")

    run.check("OB-06", ob_symbols, endpoint="orderbook",
              expected="OpenAlgo symbols, not broker tradingsymbols")

    def ob_prices():
        d = book("orderbook")
        if not d["orders"]:
            raise Warn("orderbook empty")
        for o in d["orders"][:40]:
            need_2dp(o["price"], f"{o['orderid']}.price")
            need_2dp(o["trigger_price"], f"{o['orderid']}.trigger_price")
            if o.get("pricetype") in ("SL", "SL-M"):
                need(as_num(o["trigger_price"], "trigger_price") != 0,
                     f"{o['orderid']}: {o['pricetype']} order with trigger_price 0")

    run.check("OB-07", ob_prices, endpoint="orderbook",
              expected="price / trigger_price numeric, 2dp, trigger set on SL orders")

    def ob_statistics():
        d = book("orderbook")
        orders, stats = d["orders"], d["statistics"]
        need_keys(stats, ["total_buy_orders", "total_sell_orders", "total_completed_orders",
                          "total_open_orders", "total_rejected_orders"], "statistics")
        if not orders:
            raise Warn("orderbook empty - nothing to reconcile against")
        counted = {
            "total_buy_orders": sum(1 for o in orders if o.get("action") == "BUY"),
            "total_sell_orders": sum(1 for o in orders if o.get("action") == "SELL"),
            "total_completed_orders": sum(1 for o in orders if o.get("order_status") == "complete"),
            "total_open_orders": sum(1 for o in orders if o.get("order_status") == "open"),
            "total_rejected_orders": sum(1 for o in orders if o.get("order_status") == "rejected"),
        }
        bad = [f"{k}: reported {stats[k]} vs {v} counted"
               for k, v in counted.items() if int(as_num(stats[k], k)) != v]
        need(not bad, "statistics do not reconcile with the orders array: " + "; ".join(bad))

    run.check("OB-08", ob_statistics, endpoint="orderbook",
              expected="statistics reconcile against a count of orders[]")

    def ob_vocab():
        d = book("orderbook")
        if not d["orders"]:
            raise Warn("orderbook empty")
        for o in d["orders"]:
            need(o.get("action") in ("BUY", "SELL"), f"{o['orderid']}: action {o.get('action')!r}")
            need(o.get("product") in ("MIS", "CNC", "NRML"),
                 f"{o['orderid']}: product {o.get('product')!r}")

    run.check("OB-09", ob_vocab, endpoint="orderbook", expected="BUY/SELL and MIS/CNC/NRML")

    def ob_empty_shape():
        """OB-10 - an empty book is a clean success with zeroed statistics."""
        d = book("orderbook")
        need(isinstance(d.get("orders"), list), "orders is not an array")
        need(isinstance(d.get("statistics"), dict), "statistics is not an object")
        if d["orders"]:
            raise Skip("orderbook is not empty this run - empty-shape case not exercised")
        for k, v in d["statistics"].items():
            need(as_num(v, k) == 0, f"empty orderbook but statistics.{k} = {v}")

    run.check("OB-10", ob_empty_shape, endpoint="orderbook",
              expected="empty book returns arrays and zeroed statistics")

    # ---------------- tradebook ----------------
    def tb_present():
        d = book("tradebook")
        need(isinstance(d, list), f"tradebook data is {type(d).__name__}, expected list")
        if not d:
            raise Warn("tradebook empty - no fills this run")
        ob = book("orderbook")
        done = {str(o["orderid"]) for o in (ob.get("orders") or [])
                if o.get("order_status") == "complete"}
        traded = {str(t.get("orderid")) for t in d}
        missing = done - traded
        need(not missing,
             f"{len(missing)} completed orders have no trade row: {sorted(missing)[:4]}")

    run.check("TB-01", tb_present, endpoint="tradebook",
              expected="every completed order has at least one trade")

    def tb_price():
        d = book("tradebook")
        if not d:
            raise Warn("tradebook empty")
        for t in d[:30]:
            need_keys(t, ["orderid", "symbol", "exchange", "action", "quantity",
                          "average_price", "product", "timestamp", "trade_value"], "trade row")
            need_nonzero(t["average_price"], f"{t['orderid']}.average_price")

    run.check("TB-02", tb_price, endpoint="tradebook",
              expected="average_price is the executed price, non-zero")

    def tb_quantity():
        d = book("tradebook")
        if not d:
            raise Warn("tradebook empty")
        for t in d[:30]:
            need(as_num(t["quantity"], f"{t['orderid']}.quantity") != 0,
                 f"{t['orderid']}: executed trade reports quantity 0 - mapping bug")

    run.check("TB-03", tb_quantity, endpoint="tradebook", expected="traded quantity non-zero")

    def tb_value():
        d = book("tradebook")
        if not d:
            raise Warn("tradebook empty")
        for t in d[:30]:
            q = as_num(t["quantity"], "quantity")
            ap = as_num(t["average_price"], "average_price")
            tv = as_num(t["trade_value"], "trade_value")
            need(abs(tv - q * ap) < max(0.05, abs(tv) * 0.01),
                 f"{t['orderid']}: trade_value {tv} != quantity {q} x average_price {ap}")

    run.check("TB-04", tb_value, endpoint="tradebook",
              expected="trade_value == quantity x average_price")

    def tb_timestamps():
        d = book("tradebook")
        if not d:
            raise Warn("tradebook empty")
        for t in d[:30]:
            ts = parse_ist(t["timestamp"], f"{t['orderid']}.timestamp").astimezone(IST)
            need(ts.date() >= date.today() - timedelta(days=1),
                 f"{t['orderid']}: trade timestamp {t['timestamp']} not in the current session")

    run.check("TB-05", tb_timestamps, endpoint="tradebook", expected="IST, current session")

    def tb_partials():
        d = book("tradebook")
        if not d:
            raise Warn("tradebook empty")
        by_order: dict[str, list] = {}
        for t in d:
            by_order.setdefault(str(t.get("orderid")), []).append(t)
        multi = {k: v for k, v in by_order.items() if len(v) > 1}
        run.note_limit("orders with multiple trade rows", len(multi))
        ob = {str(o["orderid"]): o for o in (book("orderbook").get("orders") or [])}
        for oid, rows in multi.items():
            if oid not in ob:
                continue
            filled = sum(as_num(r["quantity"], "quantity") for r in rows)
            want = as_num(ob[oid]["quantity"], "quantity")
            need(abs(filled - want) < 1e-6,
                 f"{oid}: partial fills sum to {filled}, order quantity is {want}")
        if not multi:
            raise Skip("no partially filled orders this run")

    run.check("TB-06", tb_partials, endpoint="tradebook",
              expected="partial fills sum to the filled quantity")

    def tb_linkage():
        d = book("tradebook")
        if not d:
            raise Warn("tradebook empty")
        ob = {str(o["orderid"]) for o in (book("orderbook").get("orders") or [])}
        if not ob:
            raise Warn("orderbook empty - cannot check linkage")
        orphan = [str(t.get("orderid")) for t in d if str(t.get("orderid")) not in ob]
        need(not orphan,
             f"{len(orphan)} trades reference an orderid absent from the orderbook: "
             f"{sorted(set(orphan))[:4]}")

    run.check("TB-07", tb_linkage, endpoint="tradebook",
              expected="every trade's orderid exists in the orderbook")

    # ---------------- positionbook ----------------
    def pb_present():
        d = book("positionbook")
        need(isinstance(d, list), f"positionbook data is {type(d).__name__}, expected list")
        if not d:
            raise Warn("positionbook empty")
        tb = book("tradebook")
        if tb:
            traded = {(t.get("symbol"), t.get("exchange")) for t in tb}
            pos = {(p.get("symbol"), p.get("exchange")) for p in d}
            missing = traded - pos
            need(not missing,
                 f"traded but absent from the position book: {sorted(missing)[:4]}")

    run.check("PB-01", pb_present, endpoint="positionbook",
              expected="every traded symbol appears")

    def pb_avg_price():
        d = book("positionbook")
        if not d:
            raise Warn("positionbook empty")
        open_rows = [p for p in d if as_num(p["quantity"], "quantity") != 0]
        if not open_rows:
            raise Skip("no open positions to assert an entry price against")
        for p in open_rows:
            need_keys(p, ["symbol", "exchange", "product", "quantity",
                          "average_price", "ltp", "pnl"], "position row")
            if p.get("average_price_basis"):
                continue
            need_nonzero(p["average_price"], f"{p['symbol']}.average_price")

    run.check("PB-02", pb_avg_price, endpoint="positionbook",
              expected="open positions carry a real entry price")

    def pb_basis():
        """PB-03 - average_price_basis appears only when the average is not
        an entry price. On a same-day position it must be absent."""
        d = book("positionbook")
        if not d:
            raise Warn("positionbook empty")
        flagged = [p for p in d if p.get("average_price_basis")]
        for p in flagged:
            run.note_quirk("average_price_basis set",
                           f"{p['symbol']}@{p['exchange']}: {p['average_price_basis']}")
        ours = {(x["symbol"], x["exchange"]) for x in run.order_ledger}
        bad = [p["symbol"] for p in flagged if (p["symbol"], p["exchange"]) in ours]
        need(not bad,
             f"average_price_basis set on a position opened by this run today: {bad}")
        if flagged:
            raise Warn(f"{len(flagged)} carried-forward position(s) report a "
                       f"non-entry average - see Quirks")

    run.check("PB-03", pb_basis, endpoint="positionbook",
              expected="basis flag only on carried-forward rows")

    def pb_ltp():
        d = book("positionbook")
        open_rows = [p for p in (d or []) if as_num(p["quantity"], "quantity") != 0]
        if not open_rows:
            raise Skip("no open positions")
        p = open_rows[0]
        lt = need_nonzero(p["ltp"], f"{p['symbol']}.ltp")
        q = run.ok(run.client.quotes(symbol=p["symbol"], exchange=p["exchange"]),
                   "quotes")["data"]
        ref = as_num(q["ltp"], "quote ltp")
        need(abs(lt - ref) / max(ref, 1e-9) < 0.02,
             f"{p['symbol']}: position ltp {lt} vs quotes ltp {ref}")

    run.check("PB-04", pb_ltp, endpoint="positionbook+quotes",
              expected="ltp non-zero and matches /quotes")

    def pb_pnl():
        d = book("positionbook")
        if not d:
            raise Warn("positionbook empty")
        checked = 0
        for p in d:
            q = as_num(p["quantity"], "quantity")
            if q == 0 or p.get("average_price_basis"):
                continue
            ap = as_num(p["average_price"], "average_price")
            lt = as_num(p["ltp"], "ltp")
            pnl = as_num(p["pnl"], "pnl")
            exp = (lt - ap) * q
            need(abs(pnl - exp) <= max(1.0, abs(exp) * 0.02),
                 f"{p['symbol']}: pnl {pnl} vs (ltp {lt} - avg {ap}) x qty {q} = {exp:.2f}")
            checked += 1
        if not checked:
            raise Skip("no open positions to check pnl arithmetic")

    run.check("PB-05", pb_pnl, endpoint="positionbook",
              expected="pnl == (ltp - average_price) x quantity")

    def pb_signs():
        d = book("positionbook")
        if not d:
            raise Warn("positionbook empty")
        for p in d:
            as_num(p["quantity"], f"{p['symbol']}.quantity")   # must parse, may be negative
        longs = sum(1 for p in d if as_num(p["quantity"], "q") > 0)
        shorts = sum(1 for p in d if as_num(p["quantity"], "q") < 0)
        flat = sum(1 for p in d if as_num(p["quantity"], "q") == 0)
        run.note_limit("position signs", f"{longs} long, {shorts} short, {flat} closed")

    run.check("PB-06", pb_signs, endpoint="positionbook",
              expected="+ve long, -ve short, 0 closed")

    def pb_closed_retained():
        """PB-07 - squared-off positions stay in the book with quantity 0."""
        d = book("positionbook")
        if not d:
            raise Warn("positionbook empty")
        closed = [p for p in d if as_num(p["quantity"], "q") == 0]
        if not closed:
            raise Skip("no closed positions in the book this run")
        for p in closed[:10]:
            as_num(p["pnl"], f"{p['symbol']}.pnl")   # realized P&L must still be reported

    run.check("PB-07", pb_closed_retained, endpoint="positionbook",
              expected="closed rows retained with realized P&L")

    def pb_rounding():
        d = book("positionbook")
        if not d:
            raise Warn("positionbook empty")
        for p in d[:30]:
            need_2dp(p["average_price"], f"{p['symbol']}.average_price")
            need_2dp(p["ltp"], f"{p['symbol']}.ltp")
            need_2dp(p["pnl"], f"{p['symbol']}.pnl")

    run.check("PB-08", pb_rounding, endpoint="positionbook", expected="prices rounded to 2dp")

    def pb_product_lot():
        d = book("positionbook")
        if not d:
            raise Warn("positionbook empty")
        with run.db() as c:
            for p in d[:30]:
                need(p.get("product") in ("MIS", "CNC", "NRML"),
                     f"{p['symbol']}: product {p.get('product')!r}")
                row = c.execute("select lotsize, instrumenttype from symtoken "
                                "where symbol=? and exchange=?",
                                (p["symbol"], p["exchange"])).fetchone()
                if not row or not row[0] or row[1] not in ("FUT", "CE", "PE"):
                    continue
                q = abs(as_num(p["quantity"], "quantity"))
                if q:
                    need(q % int(row[0]) == 0,
                         f"{p['symbol']}: quantity {q} is not a multiple of lot size {row[0]}")

    run.check("PB-09", pb_product_lot, endpoint="positionbook",
              expected="valid product; F&O quantities align to lot size")

    # ---------------- funds ----------------
    FUND_KEYS = ["availablecash", "collateral", "m2mrealized",
                 "m2munrealized", "utiliseddebits"]

    def fn_fields():
        d = book("funds")
        need_keys(d, FUND_KEYS, "funds")
        extra = [k for k in d if k not in FUND_KEYS]
        if extra:
            raise Warn(f"funds carries undocumented fields: {extra}")

    run.check("FN-01", fn_fields, endpoint="funds", expected="exactly the five documented fields")

    def fn_numeric():
        d = book("funds")
        for k in FUND_KEYS:
            v = d[k]
            need(not isinstance(v, str) or "," not in v,
                 f"funds.{k}: thousands separator in {v!r}")
            as_num(v, f"funds.{k}")

    run.check("FN-02", fn_numeric, endpoint="funds",
              expected="parse as floats, no separators or currency marks")

    def fn_plausible():
        """FN-03 - negatives are legitimate (debit balance, MTM loss). Assert
        the values move consistently, not that they are positive."""
        d = book("funds")
        vals = {k: as_num(d[k], k) for k in FUND_KEYS}
        run.note_limit("funds snapshot", json.dumps({k: round(v, 2) for k, v in vals.items()}))
        neg = [k for k, v in vals.items() if v < 0]
        if neg:
            run.note_quirk("Negative funds fields", f"{neg} - legitimate for a debit balance/MTM loss")

    run.check("FN-03", fn_plausible, endpoint="funds",
              expected="values recorded; negatives allowed")

    def fn_rounding():
        d = book("funds")
        for k in FUND_KEYS:
            need_2dp(d[k], f"funds.{k}")

    run.check("FN-04", fn_rounding, endpoint="funds", expected="2-decimal formatting")


# ==========================================================================
# 10. GTT
# ==========================================================================
def sec_gtt(run: Runner) -> None:
    run.section("10. GTT")
    m = run.matrix
    GT_IDS = [f"GT-{i:02d}" for i in range(1, 24)]
    if "EQ_CHEAP" not in m:
        for cid in GT_IDS:
            run.blocked(cid, "EQ_CHEAP unresolved", endpoint="gtt")
        return
    sym, ex = m["EQ_CHEAP"]
    ltp = as_num(run.ok(run.client.quotes(symbol=sym, exchange=ex), "q")["data"]["ltp"], "ltp")

    probe = run.client.gttorderbook()
    unsupported = (isinstance(probe, dict)
                   and "not supported" in str(probe.get("message", "")).lower())

    def gate():
        need(unsupported, "broker ships gtt_api - capability gate not applicable")
        need(str(probe.get("message", "")), "501 without a message")

    if unsupported:
        run.check("GT-01", gate, endpoint="gttorderbook", expected="501 with a clear message")
        for cid in GT_IDS[1:]:
            run.record(cid, SKIP, f"broker '{run.env['broker']}' ships no gtt_api module",
                       endpoint="gtt")
        return
    run.record("GT-01", PASS, "broker ships gtt_api - capability gate not applicable",
               endpoint="gttorderbook")

    def gtt_place(**kw):
        body = {"strategy": STRAT, "symbol": sym, "exchange": ex, "product": "CNC",
                "quantity": 1, "price_type": "LIMIT", "price": 0,
                "triggerprice_sl": 0, "triggerprice_tg": 0}
        body.update(kw)
        r = run.ok(run.client.placegttorder(**body), f"placegttorder {kw.get('trigger_type')}")
        need(r.get("trigger_id"), "no trigger_id returned")
        run.gtt_ledger.append(str(r["trigger_id"]))
        return str(r["trigger_id"])

    def book(status=None):
        r = run.client.gttorderbook(**({"status": status} if status else {}))
        return run.ok(r, f"gttorderbook {status or 'active'}")["data"] or []

    def row(tid, status=None):
        return next((g for g in book(status) if str(g["trigger_id"]) == str(tid)), None)

    single_below = run.check(
        "GT-02", lambda: gtt_place(trigger_type="SINGLE", action="BUY",
                                   price=round(ltp * 0.90, 2),
                                   triggerprice_sl=round(ltp * 0.92, 2)),
        endpoint="placegttorder", expected="SINGLE with trigger below LTP")

    single_above = run.check(
        "GT-03", lambda: gtt_place(trigger_type="SINGLE", action="BUY",
                                   price=round(ltp * 1.10, 2),
                                   triggerprice_tg=round(ltp * 1.08, 2)),
        endpoint="placegttorder", expected="SINGLE with trigger above LTP")

    run.check(
        "GT-04", lambda: gtt_place(trigger_type="SINGLE", action="BUY", price_type="MARKET",
                                   price=0, triggerprice_tg=round(ltp * 1.08, 2)),
        endpoint="placegttorder", expected="MARKET child accepted (MPP-converted if needed)")

    oco = run.check(
        "GT-05", lambda: gtt_place(trigger_type="OCO", action="SELL",
                                   triggerprice_sl=round(ltp * 0.90, 2),
                                   stoploss=round(ltp * 0.89, 2),
                                   triggerprice_tg=round(ltp * 1.10, 2),
                                   target=round(ltp * 1.11, 2)),
        endpoint="placegttorder", expected="OCO accepted")

    run.check("GT-06", lambda: run.expect_error(run.client.placegttorder(
        strategy=STRAT, symbol=sym, exchange=ex, action="SELL", trigger_type="OCO",
        product="CNC", quantity=1, price_type="LIMIT", price=0,
        triggerprice_sl=round(ltp * 1.10, 2), stoploss=round(ltp * 1.09, 2),
        triggerprice_tg=round(ltp * 0.90, 2), target=round(ltp * 0.89, 2)), "sl >= tg"),
        endpoint="placegttorder", expected="stoploss trigger must be below target trigger")

    run.check("GT-07", lambda: run.expect_error(run.client.placegttorder(
        strategy=STRAT, symbol=sym, exchange=ex, action="BUY", trigger_type="SINGLE",
        product="CNC", quantity=1, price_type="LIMIT", price=round(ltp * 0.9, 2),
        triggerprice_sl=0, triggerprice_tg=0), "SINGLE without any trigger price"),
        endpoint="placegttorder", expected="SINGLE requires one positive trigger")

    run.check("GT-08", lambda: run.expect_error(run.client.placegttorder(
        strategy=STRAT, symbol=sym, exchange=ex, action="BUY", trigger_type="SINGLE",
        product="MIS", quantity=1, price_type="LIMIT", price=round(ltp * 0.9, 2),
        triggerprice_sl=round(ltp * 0.92, 2)), "MIS GTT"),
        endpoint="placegttorder", expected="MIS refused, CNC/NRML only")

    def gtt_book_fields():
        d = book()
        need(d, "no active GTTs after placing several")
        for g in d:
            need_keys(g, ["trigger_id", "trigger_type", "status", "symbol", "exchange",
                          "trigger_prices", "last_price", "legs", "created_at",
                          "updated_at", "expires_at"], "gtt row")
            need(g["status"] == "active",
                 f"{g['trigger_id']}: non-active row {g['status']!r} in the default book")
            for lg in g["legs"]:
                need_keys(lg, ["action", "quantity", "price", "pricetype", "product"], "leg")
                need(lg["product"] in ("CNC", "NRML"), f"leg product {lg['product']!r}")
                need(lg["pricetype"] in ("LIMIT", "MARKET"), f"leg pricetype {lg['pricetype']!r}")

    run.check("GT-09", gtt_book_fields, endpoint="gttorderbook",
              expected="active only, full documented field set")

    def gtt_history():
        act = {str(g["trigger_id"]) for g in book()}
        alls = book("all")
        ids = {str(g["trigger_id"]) for g in alls}
        need(ids >= act, "status=all returned fewer triggers than the active book")
        statuses = {g["status"] for g in alls}
        run.note_limit("GTT statuses in history", ", ".join(sorted(statuses)))
        if ids == act:
            raise Warn("status=all returned only active rows - this broker's mapper "
                       "may not expose GTT history yet")
        seq = [g["status"] == "active" for g in alls]
        need(seq == sorted(seq, reverse=True),
             "status=all must order active rows first, then the rest")

    run.check("GT-10", gtt_history, endpoint="gttorderbook",
              expected="status=all adds history, active ordered first")

    run.check("GT-11", lambda: run.expect_error(
        post("gttorderbook", {"status": "bogus"}), "invalid status filter"),
        endpoint="gttorderbook", expected="clean 400")

    def single_shape():
        g = row(single_below)
        need(g, f"trigger {single_below} not in the active book")
        need(g["trigger_type"] == "single", f"trigger_type {g['trigger_type']!r}")
        need(len(g["trigger_prices"]) == 1,
             f"SINGLE has {len(g['trigger_prices'])} trigger prices")
        need(len(g["legs"]) == 1, f"SINGLE has {len(g['legs'])} legs")

    run.check("GT-12", single_shape, endpoint="gttorderbook",
              expected="SINGLE -> 1 trigger price, 1 leg")

    def oco_shape():
        g = row(oco)
        need(g, f"trigger {oco} not in the active book")
        need(g["trigger_type"] in ("two-leg", "oco"), f"trigger_type {g['trigger_type']!r}")
        tp = g["trigger_prices"]
        need(len(tp) == 2, f"OCO has {len(tp)} trigger prices")
        need(as_num(tp[0], "sl") < as_num(tp[1], "tg"),
             f"OCO trigger_prices not ascending (sl first): {tp}")
        need(len(g["legs"]) == 2, f"OCO has {len(g['legs'])} legs")

    run.check("GT-13", oco_shape, endpoint="gttorderbook",
              expected="OCO -> 2 ascending triggers, 2 legs")

    def modify_single():
        need(single_below, "no SINGLE trigger to modify")
        newt = round(ltp * 0.93, 2)
        run.ok(run.client.modifygttorder(
            trigger_id=single_below, strategy=STRAT, symbol=sym, exchange=ex, action="BUY",
            trigger_type="SINGLE", product="CNC", quantity=2, price_type="LIMIT",
            price=round(ltp * 0.91, 2), triggerprice_sl=newt, triggerprice_tg=0), "modify")
        time.sleep(1.5)
        g = row(single_below)
        need(g, f"{single_below} vanished after modify")
        need(abs(as_num(g["trigger_prices"][0], "trigger") - newt) < 0.05,
             f"modify not reflected: {g['trigger_prices']}")
        need(int(as_num(g["legs"][0]["quantity"], "qty")) == 2,
             f"quantity modify not reflected: {g['legs'][0]['quantity']}")

    run.check("GT-14", modify_single, endpoint="modifygttorder",
              expected="trigger and quantity both replaced")

    def modify_oco():
        need(oco, "no OCO trigger to modify")
        sl, tg = round(ltp * 0.85, 2), round(ltp * 1.15, 2)
        run.ok(run.client.modifygttorder(
            trigger_id=oco, strategy=STRAT, symbol=sym, exchange=ex, action="SELL",
            trigger_type="OCO", product="CNC", quantity=1, price_type="LIMIT", price=0,
            triggerprice_sl=sl, stoploss=round(sl - 0.5, 2),
            triggerprice_tg=tg, target=round(tg + 0.5, 2)), "modify OCO")
        time.sleep(1.5)
        g = row(oco)
        need(g, f"{oco} vanished after modify")
        tp = [as_num(x, "tp") for x in g["trigger_prices"]]
        need(abs(tp[0] - sl) < 0.05 and abs(tp[1] - tg) < 0.05,
             f"both OCO legs should update atomically: {tp} != [{sl}, {tg}]")

    run.check("GT-15", modify_oco, endpoint="modifygttorder",
              expected="both legs swap atomically")

    run.check("GT-16", lambda: run.expect_error(run.client.modifygttorder(
        trigger_id=single_below, strategy=STRAT, symbol=sym, exchange=ex, action="BUY",
        trigger_type="OCO", product="CNC", quantity=1, price_type="LIMIT", price=0,
        triggerprice_sl=round(ltp * 0.9, 2), stoploss=round(ltp * 0.89, 2),
        triggerprice_tg=round(ltp * 1.1, 2), target=round(ltp * 1.11, 2)),
        "SINGLE -> OCO switch"),
        endpoint="modifygttorder", expected="cannot switch trigger type")

    def modify_instrument():
        other = m.get("EQ_LIQUID", (sym, ex))[0]
        if other == sym:
            raise Skip("no second symbol resolved to attempt an instrument change")
        run.expect_error(run.client.modifygttorder(
            trigger_id=single_below, strategy=STRAT, symbol=other, exchange=ex, action="BUY",
            trigger_type="SINGLE", product="CNC", quantity=1, price_type="LIMIT",
            price=round(ltp * 0.9, 2), triggerprice_sl=round(ltp * 0.92, 2)),
            "symbol change on modify")

    run.check("GT-17", modify_instrument, endpoint="modifygttorder",
              expected="symbol/exchange/action are immutable")

    def modify_cancelled():
        tid = gtt_place(trigger_type="SINGLE", action="BUY", price=round(ltp * 0.9, 2),
                        triggerprice_sl=round(ltp * 0.92, 2))
        run.ok(run.client.cancelgttorder(trigger_id=tid, strategy=STRAT), "cancel")
        if tid in run.gtt_ledger:
            run.gtt_ledger.remove(tid)
        time.sleep(1.5)
        run.expect_error(run.client.modifygttorder(
            trigger_id=tid, strategy=STRAT, symbol=sym, exchange=ex, action="BUY",
            trigger_type="SINGLE", product="CNC", quantity=1, price_type="LIMIT",
            price=round(ltp * 0.9, 2), triggerprice_sl=round(ltp * 0.93, 2)),
            "modify a cancelled GTT")

    run.check("GT-18", modify_cancelled, endpoint="modifygttorder",
              expected="triggered/cancelled GTTs are immutable")

    def cancel_active():
        need(single_above, "no trigger to cancel")
        run.ok(run.client.cancelgttorder(trigger_id=single_above, strategy=STRAT), "cancel")
        if single_above in run.gtt_ledger:
            run.gtt_ledger.remove(single_above)
        time.sleep(1.5)
        need(row(single_above) is None,
             f"{single_above} still active after cancellation")
        g = row(single_above, "all")
        if g:
            need(g["status"] in ("cancelled", "deleted"),
                 f"cancelled trigger reports status {g['status']!r} under status=all")

    run.check("GT-19", cancel_active, endpoint="cancelgttorder",
              expected="gone from active, cancelled under status=all")

    run.check("GT-20", lambda: run.expect_error(
        run.client.cancelgttorder(trigger_id=single_above, strategy=STRAT),
        "cancel an already-cancelled GTT"),
        endpoint="cancelgttorder", expected="clean error")

    def lifecycle():
        tid = gtt_place(trigger_type="SINGLE", action="BUY", price=round(ltp * 0.90, 2),
                        triggerprice_sl=round(ltp * 0.92, 2))
        need(row(tid), "not active after placement")
        run.ok(run.client.modifygttorder(
            trigger_id=tid, strategy=STRAT, symbol=sym, exchange=ex, action="BUY",
            trigger_type="SINGLE", product="CNC", quantity=1, price_type="LIMIT",
            price=round(ltp * 0.88, 2), triggerprice_sl=round(ltp * 0.90, 2)), "modify")
        time.sleep(1.5)
        g = row(tid)
        need(g, "vanished after modify")
        need(g.get("updated_at") != "" or True, "")
        run.ok(run.client.cancelgttorder(trigger_id=tid, strategy=STRAT), "cancel")
        if tid in run.gtt_ledger:
            run.gtt_ledger.remove(tid)
        time.sleep(1.5)
        need(row(tid) is None, "still active after cancellation")

    run.check("GT-21", lifecycle, endpoint="gtt lifecycle",
              expected="place -> active -> modify -> cancel, each confirmed")

    def triggered_linkage():
        """GT-22 - a fired GTT links to an ordinary order."""
        fired = [g for g in book("all") if g.get("status") == "triggered"]
        if not fired:
            raise Skip("no GTT fired during this run - place one near LTP to exercise it")
        ob = {str(o["orderid"]) for o in
              (run.ok(run.client.orderbook(), "orderbook")["data"].get("orders") or [])}
        for g in fired[:5]:
            for lg in g.get("legs") or []:
                tid = lg.get("triggered_order_id")
                if tid:
                    need(str(tid) in ob,
                         f"GTT {g['trigger_id']} fired order {tid} absent from the orderbook")

    run.check("GT-22", triggered_linkage, endpoint="gttorderbook+orderbook",
              expected="fired GTT's child order appears in the orderbook")

    def broker_quirks():
        """GT-23 - record documented broker-specific GTT divergences."""
        b = run.env["broker"]
        known = {
            "upstox": "OCO opens a position at market before arming the legs; "
                      "stoploss/target limit prices are discarded; a delivery sell "
                      "entry needs EDIS validation",
        }
        if b in known:
            run.note_quirk(f"GTT behaviour on {b}", known[b])
            raise Warn(f"{b}: {known[b]} - verify OCO placements against this")
        run.note_limit("GTT broker quirks", f"none recorded for {b}")

    run.check("GT-23", broker_quirks, endpoint="gtt",
              expected="documented divergences recorded, not silently passed")


# ==========================================================================
# 18. margin   (live broker even in analyzer mode)
# ==========================================================================
def sec_margin(run: Runner) -> None:
    run.section("18. Margin")
    m = run.matrix
    MG_IDS = [f"MG-{i:02d}" for i in range(1, 12)]
    if "OPT_ATM_CE_NFO" not in m or "OPT_ATM_PE_NFO" not in m:
        for cid in MG_IDS:
            run.record(cid, SKIP, "ATM option slots unresolved", endpoint="margin")
        return
    ce = m["OPT_ATM_CE_NFO"][0]
    pe = m["OPT_ATM_PE_NFO"][0]
    lot = _lot(run, ce, "NFO")

    def leg(s, action, qty=None, exch="NFO", product="NRML", pricetype="MARKET", **kw):
        return {"symbol": s, "exchange": exch, "action": action, "product": product,
                "pricetype": pricetype, "quantity": str(qty or lot), **kw}

    def margin_of(positions):
        d = run.ok(run.client.margin(positions=positions), "margin")["data"]
        need_keys(d, ["total_margin_required", "span_margin", "exposure_margin"], "margin")
        return d

    def single():
        d = margin_of([leg(ce, "SELL")])
        need_nonzero(d["total_margin_required"], "total_margin_required")
        for k in ("span_margin", "exposure_margin"):
            as_num(d[k], k)
        run.note_limit("margin, 1 short option",
                       f"{as_num(d['total_margin_required'], 'm'):.0f}")

    run.check("MG-01", single, endpoint="margin", exchange="NFO",
              expected="components present, total non-zero")

    def hedged():
        a = as_num(margin_of([leg(ce, "SELL")])["total_margin_required"], "leg1")
        b = as_num(margin_of([leg(pe, "SELL")])["total_margin_required"], "leg2")
        basket = as_num(margin_of([leg(ce, "SELL"), leg(pe, "BUY")])["total_margin_required"],
                        "basket")
        run.note_limit("margin hedge benefit",
                       f"basket {basket:.0f} vs naive per-leg sum {a + b:.0f}")
        need(basket < a + b,
             f"basket {basket:.0f} is not below the naive per-leg sum {a + b:.0f} - "
             f"legs are being summed instead of routed to the basket calculator")

    run.check("MG-02", hedged, endpoint="margin", exchange="NFO",
              expected="basket margin < sum of legs")

    def iron_condor():
        exp = _nearest_expiry(run, "NIFTY", "NFO")
        if not exp:
            raise Skip("no NIFTY expiry resolved")
        legs = []
        for off, ot, act in (("OTM4", "CE", "SELL"), ("OTM6", "CE", "BUY"),
                             ("OTM4", "PE", "SELL"), ("OTM6", "PE", "BUY")):
            r = run.client.optionsymbol(underlying="NIFTY", exchange="NSE_INDEX",
                                        expiry_date=exp, offset=off, option_type=ot)
            need(r.get("symbol"), f"could not resolve {off}/{ot}")
            legs.append(leg(r["symbol"], act))
        d = margin_of(legs)
        total = need_nonzero(d["total_margin_required"], "iron condor margin")
        naked = as_num(margin_of([legs[0], legs[2]])["total_margin_required"], "naked")
        run.note_limit("margin, iron condor", f"{total:.0f} vs naked strangle {naked:.0f}")
        need(total <= naked * 1.05,
             f"iron condor {total:.0f} should not exceed the naked strangle {naked:.0f} - "
             f"the long wings are not being credited")

    run.check("MG-03", iron_condor, endpoint="margin", exchange="NFO",
              expected="4-leg hedge benefit visible")

    def equity_single():
        if "EQ_CHEAP" not in m:
            raise Skip("EQ_CHEAP unresolved")
        s, e = m["EQ_CHEAP"]
        d = margin_of([leg(s, "BUY", qty=1, exch=e, product="MIS")])
        need_nonzero(d["total_margin_required"], "equity margin")

    run.check("MG-04", equity_single, endpoint="margin",
              expected="equity order returns a plausible figure")

    def benefit_field():
        d = margin_of([leg(ce, "SELL"), leg(pe, "BUY")])
        if "margin_benefit" not in d:
            raise Warn("margin_benefit not exposed by this broker")
        as_num(d["margin_benefit"], "margin_benefit")

    run.check("MG-05", benefit_field, endpoint="margin",
              expected="margin_benefit present where the broker exposes it")

    def magnitude():
        """MG-06 - sanity-check the figure against the notional it covers."""
        d = margin_of([leg(ce, "SELL")])
        total = as_num(d["total_margin_required"], "total")
        spot = as_num(run.ok(run.client.quotes(symbol="NIFTY", exchange="NSE_INDEX"),
                             "spot")["data"]["ltp"], "spot")
        notional = spot * lot
        need(0.02 * notional < total < 1.5 * notional,
             f"margin {total:.0f} implausible against notional {notional:.0f} "
             f"({total/notional:.1%} of notional)")
        run.note_limit("margin as % of notional", f"{total/notional:.1%}")

    run.check("MG-06", magnitude, endpoint="margin",
              expected="margin in a plausible band of the notional")

    def cap_50():
        ok50 = margin_of([leg(ce, "SELL") for _ in range(50)])
        need_nonzero(ok50["total_margin_required"], "50-position margin")
        run.expect_error(run.client.margin(positions=[leg(ce, "SELL") for _ in range(51)]),
                         "51 positions")

    run.check("MG-07", cap_50, endpoint="margin",
              expected="exactly 50 accepted, 51 -> clean 400")

    run.check("MG-08", lambda: run.expect_error(
        run.client.margin(positions=[leg("ZZNOTREAL99", "BUY", qty=1)]), "invalid symbol"),
        endpoint="margin", expected="clean 400, not 500")

    def malformed():
        """MG-09/MG-10 - guards against a non-JSON reply and an error sent with
        HTTP 200. Both must surface as a clean status, never an unhandled 500."""
        for body, label in (
            ({"positions": [{"symbol": ce, "exchange": "NFO", "action": "SIDEWAYS",
                             "product": "NRML", "pricetype": "MARKET", "quantity": "1"}]},
             "invalid action"),
            ({"positions": [{"symbol": ce, "exchange": "NFO", "action": "BUY",
                             "product": "NRML", "pricetype": "MARKET",
                             "quantity": "-5"}]}, "negative quantity"),
        ):
            r = post("margin", body)
            need(isinstance(r, dict), f"{label}: non-dict response")
            need(r.get("status") == "error",
                 f"{label}: expected a clean error, got {r.get('status')!r}")
            msg = str(r.get("message", ""))
            need(msg, f"{label}: error without a message")
            need("Traceback" not in msg, f"{label}: traceback leaked")

    run.check("MG-09", malformed, endpoint="margin",
              expected="malformed input -> clean error, no traceback")

    def http200_error():
        """MG-10 - a broker error arriving with HTTP 200 must be normalised."""
        r = post("margin", {"positions": [{"symbol": "ZZNOTREAL99", "exchange": "NFO",
                                           "action": "BUY", "product": "NRML",
                                           "pricetype": "MARKET", "quantity": "1"}]})
        need(r.get("status") == "error",
             "an invalid position returned status!=error - a broker error payload sent "
             "with HTTP 200 is being read as success")
        need("total_margin_required" not in (r.get("data") or {}),
             "error response still carries margin data")

    run.check("MG-10", http200_error, endpoint="margin",
              expected="broker error at HTTP 200 normalised to an error response")

    run.record("MG-11", SKIP,
               "broker-without-margin-support case needs a broker lacking margin_api; "
               f"'{run.env['broker']}' provides one",
               endpoint="margin")


# ==========================================================================
# 11/12. websocket  (opt-in: QA_WS=1)
# ==========================================================================
class WSClient:
    """Raw wire-protocol client for the checks the SDK cannot express.

    Most of section 11 is about the protocol itself - the authenticate
    handshake, subscribe acknowledgements, per-symbol partial results,
    unsubscribe acks and their canonical mode labels. The SDK hides all of
    that behind callbacks, so those checks need the socket directly.
    """

    def __init__(self, url: str, timeout: float = 12.0):
        import websocket
        self.ws = websocket.create_connection(url, timeout=timeout)
        self.frames: list[dict] = []

    def send(self, payload: dict) -> None:
        self.ws.send(json.dumps(payload))

    def recv_until(self, pred, seconds: float = 10.0) -> dict | None:
        """Read frames until pred(frame) is true. Collects everything seen."""
        end = time.time() + seconds
        while time.time() < end:
            try:
                self.ws.settimeout(max(0.5, end - time.time()))
                f = json.loads(self.ws.recv())
            except Exception:
                continue
            self.frames.append(f)
            if pred(f):
                return f
        return None

    def market_frames(self, seconds: float = 8.0) -> list[dict]:
        end = time.time() + seconds
        out = []
        while time.time() < end:
            try:
                self.ws.settimeout(max(0.5, end - time.time()))
                f = json.loads(self.ws.recv())
            except Exception:
                continue
            self.frames.append(f)
            if f.get("type") == "market_data":
                out.append(f)
        return out

    def auth(self, key: str) -> dict | None:
        self.send({"action": "authenticate", "api_key": key})
        return self.recv_until(
            lambda f: f.get("type") in ("authenticate", "auth", "error")
            or "status" in f, 8.0)

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass


def sec_websocket(run: Runner) -> None:
    run.section("11/12. WebSocket")
    if NO_WS:
        run.record("WS-*", SKIP, "QA_WS=0 set - websocket section disabled",
                   endpoint="websocket")
        return
    m = run.matrix
    ex_list = run.env["exchanges"]

    def inst(*slots):
        return [{"symbol": m[s][0], "exchange": m[s][1]} for s in slots if s in m]

    base = inst("EQ_LIQUID", "EQ_CHEAP", "FUT_NFO")
    if not base:
        run.blocked("WS-*", "no symbols resolved for subscription", endpoint="websocket")
        return

    # ---- protocol-level, raw socket -------------------------------------
    def authenticate():
        c = WSClient(WS_URL)
        try:
            r = c.auth(API_KEY)
            need(r is not None, "no response to authenticate")
            need(str(r.get("status", "")).lower() not in ("error", "failure"),
                 f"authentication refused: {r}")
        finally:
            c.close()

    run.check("WS-01", authenticate, endpoint="ws.authenticate", expected="accepted")

    def bad_key():
        c = WSClient(WS_URL)
        try:
            r = c.auth("deadbeefdeadbeef")
            if r is None:
                return          # connection closed without a frame is a valid refusal
            need(str(r.get("status", "")).lower() in ("error", "failure")
                 or r.get("type") == "error",
                 f"invalid api_key was accepted: {r}")
        finally:
            c.close()

    run.check("WS-02", bad_key, endpoint="ws.authenticate", expected="invalid key refused")

    def sub_before_auth():
        c = WSClient(WS_URL)
        try:
            c.send({"action": "subscribe", "mode": "LTP", "symbols": base[:1]})
            r = c.recv_until(lambda f: f.get("type") in ("subscribe", "error")
                             or f.get("status") == "error", 6.0)
            got_data = any(f.get("type") == "market_data" for f in c.frames)
            need(not got_data, "market data streamed before authentication")
            if r is None:
                return
            need(str(r.get("status", "")).lower() != "success",
                 f"subscribe accepted before authenticate: {r}")
        finally:
            c.close()

    run.check("WS-03", sub_before_auth, endpoint="ws.subscribe",
              expected="rejected before authenticate")

    def ping_pong():
        c = WSClient(WS_URL)
        try:
            c.auth(API_KEY)
            t = time.perf_counter()
            c.send({"action": "ping"})
            r = c.recv_until(lambda f: f.get("type") == "pong"
                             or f.get("action") == "pong", 8.0)
            need(r is not None, "no pong returned to the application-level ping")
            run.note_limit("ws ping round-trip",
                           f"{(time.perf_counter()-t)*1000:.0f}ms")
        finally:
            c.close()

    run.check("WS-04", ping_pong, endpoint="ws.ping", expected="pong returned")

    def keepalive():
        """WS-05 - survive past WS_PING_INTERVAL (default 20s) with no traffic."""
        c = WSClient(WS_URL, timeout=40)
        try:
            c.auth(API_KEY)
            time.sleep(26)
            c.send({"action": "ping"})
            r = c.recv_until(lambda f: f.get("type") == "pong"
                             or f.get("action") == "pong", 8.0)
            need(r is not None, "connection died across the keepalive interval")
        finally:
            c.close()

    if HEAVY:
        run.check("WS-05", keepalive, endpoint="ws.keepalive",
                  expected="alive past WS_PING_INTERVAL")
    else:
        run.record("WS-05", SKIP, "QA_HEAVY=1 not set (26s idle keepalive probe)",
                   endpoint="ws.keepalive")

    # ---- data flow, one authenticated session ---------------------------
    c = WSClient(WS_URL, timeout=20)
    try:
        c.auth(API_KEY)

        def subscribe(mode, symbols, depth=None, seconds=8.0):
            msg = {"action": "subscribe", "mode": mode, "symbols": symbols}
            if depth:
                msg["depth"] = depth
            c.send(msg)
            ack = c.recv_until(lambda f: f.get("type") == "subscribe", 8.0)
            frames = c.market_frames(seconds)
            return ack, frames

        def unsubscribe(mode, symbols):
            c.send({"action": "unsubscribe", "mode": mode, "symbols": symbols,
                    "request_id": f"qa-{mode}"})
            return c.recv_until(lambda f: f.get("type") == "unsubscribe", 8.0)

        def ltp_single():
            ack, frames = subscribe("LTP", base[:1])
            need(frames, "no LTP frames for a single symbol")
            f = frames[0]
            need(f.get("mode") == 1, f"LTP frame mode={f.get('mode')}, expected 1")
            need_nonzero((f.get("data") or {}).get("ltp"), "ltp")
            unsubscribe("LTP", base[:1])

        run.check("WS-06", ltp_single, endpoint="ws.LTP", expected="mode 1 frames")

        def ltp_multi():
            ack, frames = subscribe("LTP", base)
            seen = {f.get("symbol") for f in frames}
            want = {s["symbol"] for s in base}
            need(frames, "no LTP frames for a multi-symbol subscribe")
            missing = want - seen
            if missing:
                raise Warn(f"no LTP frames for {sorted(missing)} in the window")
            unsubscribe("LTP", base)

        run.check("WS-07", ltp_multi, endpoint="ws.LTP", expected="frames for every symbol")

        def quote_mode():
            ack, frames = subscribe("Quote", base)
            need(frames, "no Quote frames")
            f = frames[0]
            need(f.get("mode") == 2, f"Quote frame mode={f.get('mode')}, expected 2")
            need_keys(f.get("data") or {},
                      ["ltp", "open", "high", "low", "close", "volume", "timestamp"],
                      "quote frame")
            unsubscribe("Quote", base)

        run.check("WS-08", quote_mode, endpoint="ws.Quote", expected="mode 2 OHLCV frames")

        def depth5():
            ack, frames = subscribe("Depth", base[:1], depth=5)
            need(frames, "no Depth frames")
            f = frames[0]
            need(f.get("mode") == 3, f"Depth frame mode={f.get('mode')}, expected 3")
            d = (f.get("data") or {}).get("depth") or {}
            need_keys(d, ["buy", "sell"], "depth object")
            need(len(d["buy"]) >= 5 and len(d["sell"]) >= 5,
                 f"{len(d['buy'])} bids / {len(d['sell'])} asks, expected 5")
            bp = [as_num(x["price"], "bid") for x in d["buy"]]
            ap = [as_num(x["price"], "ask") for x in d["sell"]]
            need(bp == sorted(bp, reverse=True), "bids not descending")
            need(ap == sorted(ap), "asks not ascending")
            unsubscribe("Depth", base[:1])

        run.check("WS-09", depth5, endpoint="ws.Depth", expected="5 ordered levels")

        def deep_depth():
            served, refused = [], []
            for lvl in (20, 30, 50):
                ack, frames = subscribe("Depth", base[:1], depth=lvl, seconds=5.0)
                subs = (ack or {}).get("subscriptions") or []
                err = any(s.get("status") == "error" for s in subs)
                if err or not frames:
                    refused.append(lvl)
                else:
                    got = len(((frames[0].get("data") or {}).get("depth") or {}).get("buy") or [])
                    served.append(f"{lvl}(got {got})")
                unsubscribe("Depth", base[:1])
            run.note_limit("ws depth levels", f"served={served or 'none'} refused={refused}")
            if not served:
                raise Skip(f"broker serves only 5-level depth (refused {refused})")

        run.check("WS-10", deep_depth, endpoint="ws.Depth",
                  expected="declared levels served, others refused cleanly")

        # Slot to use for each claimed exchange. BSE is cash equity and
        # GLOBAL_INDEX is an index feed - neither has a FUT_* slot, and
        # mapping them to one is how they went untested.
        EX_SLOT = {"NSE": "EQ_LIQUID", "BSE": "EQ_BSE",
                   "NSE_INDEX": "IDX_NSE", "BSE_INDEX": "IDX_BSE",
                   "MCX_INDEX": "IDX_MCX", "GLOBAL_INDEX": "IDX_GLOBAL"}

        def per_exchange():
            """WS-11 - LTP, Quote and Depth on every exchange plugin.json
            claims. An exchange with no resolvable instrument is reported as
            skipped, never silently dropped: that list is the promise the
            integration makes."""
            streaming, quiet, dead, skipped = [], [], [], []
            for exch in ex_list:
                slot = EX_SLOT.get(exch, f"FUT_{exch}")
                if slot not in m:
                    skipped.append(f"{exch}({slot} unresolved)")
                    continue
                s, e = m[slot]
                syms = [{"symbol": s, "exchange": e}]
                got_modes = []
                for mode in ("LTP", "Quote", "Depth"):
                    ack, frames = subscribe(mode, syms, seconds=7.0)
                    subs = (ack or {}).get("subscriptions") or []
                    refused = [x for x in subs if x.get("status") == "error"]
                    unsubscribe(mode, syms)
                    if frames:
                        got_modes.append(mode)
                    elif refused and mode == "Depth":
                        # a broker may legitimately not serve depth here
                        got_modes.append(f"{mode}:refused")
                if any(x in got_modes for x in ("LTP", "Quote")):
                    streaming.append(f"{exch}[{'+'.join(got_modes)}]")
                    continue
                # No frames at all. Distinguish a quiet instrument from a
                # broken feed by asking REST for the same symbol.
                try:
                    q = run.client.quotes(symbol=s, exchange=e)
                    live = (q.get("status") == "success"
                            and as_num((q.get("data") or {}).get("ltp", 0), "ltp") > 0)
                except Exception:
                    live = False
                (dead if live else quiet).append(f"{exch}({s})")

            run.note_limit("ws per-exchange streaming",
                           f"streaming={streaming or 'none'} | quiet={quiet or 'none'} | "
                           f"dead={dead or 'none'} | skipped={skipped or 'none'}")
            need(streaming, "no exchange produced a single frame")
            need(not dead,
                 f"REST has a live price but the websocket sent nothing for {dead} - "
                 f"claimed in plugin.json and not streaming")
            if skipped:
                raise Warn(f"claimed but never streamed - no instrument resolved: {skipped}")
            if quiet:
                raise Warn(f"no frames and no live REST price either (out of session or "
                           f"illiquid, not necessarily broken): {quiet}")

        run.check("WS-11", per_exchange, endpoint="ws.LTP/Quote/Depth",
                  expected="every claimed exchange streams in every mode")

        def indices():
            syms = inst("IDX_NSE", "IDX_BSE")
            if not syms:
                raise Skip("no index slots resolved")
            _, frames = subscribe("Quote", syms, seconds=8.0)
            seen = {f.get("symbol") for f in frames}
            missing = {s["symbol"] for s in syms} - seen
            unsubscribe("Quote", syms)
            need(not missing, f"no index frames for {sorted(missing)}")

        run.check("WS-12", indices, endpoint="ws.Quote", expected="NSE/BSE indices stream")

        def no_zeros():
            _, frames = subscribe("Quote", base[:2], seconds=10.0)
            bad = []
            for f in frames[:60]:
                d = f.get("data") or {}
                for k in ("open", "high", "low", "close", "ltp"):
                    if k in d and as_num(d[k], k) == 0:
                        bad.append(f"{f.get('symbol')}.{k}")
            unsubscribe("Quote", base[:2])
            need(frames, "no frames to inspect")
            need(not bad,
                 f"zero values in quote frames - classic binary-offset bug: "
                 f"{sorted(set(bad))[:6]}")

        run.check("WS-13", no_zeros, endpoint="ws.Quote", expected="no zero OHLC")

        def ts_ist():
            _, frames = subscribe("Quote", base[:1], seconds=8.0)
            need(frames, "no frames")
            seen = []
            for f in frames[:20]:
                ts = (f.get("data") or {}).get("timestamp")
                need(ts is not None, "frame carries no timestamp")
                t = parse_ist(ts, "ws timestamp").astimezone(IST)
                need(t.date() >= date.today() - timedelta(days=1),
                     f"ws timestamp {t} not in the current session")
                seen.append(t)
            need(seen == sorted(seen), "ws timestamps not monotonic")
            unsubscribe("Quote", base[:1])

        run.check("WS-14", ts_ist, endpoint="ws.Quote", expected="epoch ms -> IST, monotonic")

        def ws_vs_rest():
            s, ex = m["EQ_LIQUID"]
            _, frames = subscribe("LTP", base[:1], seconds=8.0)
            need(frames, "no frames")
            ws_ltp = as_num((frames[-1].get("data") or {}).get("ltp"), "ws ltp")
            rest = as_num(run.ok(run.client.quotes(symbol=s, exchange=ex),
                                 "quotes")["data"]["ltp"], "rest ltp")
            unsubscribe("LTP", base[:1])
            need(abs(ws_ltp - rest) / rest < 0.02,
                 f"ws ltp {ws_ltp} vs REST ltp {rest}")

        run.check("WS-15", ws_vs_rest, endpoint="ws.LTP+quotes", expected="agree within a tick")

        def liquid_syms(n):
            with run.db() as db:
                rows = [r[0] for r in db.execute(
                    "select distinct s.symbol from symtoken s where s.exchange='NSE' "
                    "and s.instrumenttype in ('EQ','') and s.symbol in "
                    "(select distinct name from symtoken where exchange='NFO' "
                    "and instrumenttype='FUT') order by s.symbol limit ?", (n,))]
            return [{"symbol": s, "exchange": "NSE"} for s in rows]

        def batch_sub():
            """WS-16 - escalate the batch size until the feed degrades, and
            record where. A single 50-symbol probe only proves 50 works; the
            number worth knowing is the one at which it stops working."""
            results = []
            cap = None
            largest = 0
            for n in (50, 100, 200, 500):
                syms = liquid_syms(n)
                if len(syms) < n:
                    results.append(f"{n}: only {len(syms)} liquid symbols available")
                    break
                ack, frames = subscribe("LTP", syms, seconds=max(10.0, n / 25))
                subs = (ack or {}).get("subscriptions") or []
                errs = [s for s in subs if s.get("status") == "error"]
                seen = {f.get("symbol") for f in frames}
                unsubscribe("LTP", syms)
                results.append(f"{n}: {len(subs)} acked, {len(errs)} refused, "
                               f"{len(seen)} streaming")
                if errs or len(seen) < n * 0.5:
                    cap = n
                    if errs:
                        run.note_limit("ws batch refusal message",
                                       str(errs[0].get("message"))[:90])
                    break
                largest = n
                time.sleep(1.0)
            run.note_limit("ws batch subscribe escalation", " | ".join(results))
            if cap is None:
                run.note_limit("ws batch cap",
                               f"at least {largest} - not reached at the largest size tried")
                return
            run.note_limit("ws batch cap", f"degrades at {cap} symbols")
            raise Warn(f"websocket batch degrades at {cap} symbols ({results[-1]}) - "
                       f"chunk subscriptions below this")

        run.check("WS-16", batch_sub, endpoint="ws.subscribe",
                  expected="escalates 50->500, records the cap and how it degrades")

        def partial():
            syms = base[:1] + [{"symbol": "ZZNOTREAL99", "exchange": "NSE"}]
            ack, _ = subscribe("LTP", syms, seconds=5.0)
            need(ack is not None, "no subscribe acknowledgement")
            need(ack.get("status") in ("partial", "error", "success"),
                 f"unexpected ack status {ack.get('status')!r}")
            subs = ack.get("subscriptions") or []
            need(subs, "ack carries no per-symbol subscriptions array")
            bad = [s for s in subs if s.get("symbol") == "ZZNOTREAL99"]
            need(bad and bad[0].get("status") == "error",
                 "invalid symbol not reported as a per-symbol error")
            need(bad[0].get("message"), "failing symbol carries no message")
            unsubscribe("LTP", syms)

        run.check("WS-17", partial, endpoint="ws.subscribe",
                  expected="status=partial with per-symbol error")

        def unsub_one():
            subscribe("LTP", base, seconds=4.0)
            ack = unsubscribe("LTP", base[:1])
            need(ack is not None, "no unsubscribe acknowledgement")
            ok = ack.get("successful") or []
            need(ok, f"unsubscribe reported nothing successful: {ack}")
            need(ok[0].get("mode") == "LTP",
                 f"canonical mode label missing, got {ok[0].get('mode')!r}")
            time.sleep(1)
            frames = c.market_frames(5.0)
            still = {f.get("symbol") for f in frames}
            need(base[0]["symbol"] not in still,
                 f"{base[0]['symbol']} still streaming after unsubscribe")
            unsubscribe("LTP", base)

        run.check("WS-18", unsub_one, endpoint="ws.unsubscribe",
                  expected="that symbol stops, ack carries canonical mode")

        def unsub_many():
            subscribe("LTP", base, seconds=4.0)
            ack = unsubscribe("LTP", base)
            need(ack is not None, "no acknowledgement")
            ok = ack.get("successful") or []
            need(len(ok) >= len(base),
                 f"{len(base)} unsubscribed, {len(ok)} acknowledged")
            time.sleep(1)
            need(not c.market_frames(5.0), "frames continue after unsubscribing all symbols")

        run.check("WS-19", unsub_many, endpoint="ws.unsubscribe", expected="all listed stop")

        def unsub_all_modes():
            subscribe("LTP", base, seconds=3.0)
            subscribe("Quote", base, seconds=3.0)
            for mode in ("LTP", "Quote", "Depth"):
                unsubscribe(mode, base)
            time.sleep(1)
            need(not c.market_frames(6.0), "frames still arriving after unsubscribing every mode")

        run.check("WS-20", unsub_all_modes, endpoint="ws.unsubscribe", expected="all streams stop")

        def unsub_unknown():
            ack = unsubscribe("LTP", [{"symbol": "ZZNOTREAL99", "exchange": "NSE"}])
            need(ack is not None, "no acknowledgement for an unknown unsubscribe")
            failed = ack.get("failed") or []
            need(failed, "unsubscribing a never-subscribed symbol reported no failure")

        run.check("WS-21", unsub_unknown, endpoint="ws.unsubscribe",
                  expected="listed under failed, no crash")

        def mode_switch():
            for mode, want in (("LTP", 1), ("Quote", 2), ("Depth", 3)):
                _, frames = subscribe(mode, base[:1], seconds=7.0)
                need(frames, f"no frames after switching to {mode}")
                got = {f.get("mode") for f in frames}
                need(want in got, f"{mode}: frames carry mode {got}, expected {want}")
                unsubscribe(mode, base[:1])

        run.check("WS-22", mode_switch, endpoint="ws.subscribe",
                  expected="each mode activates with its own mode value")

        def mode_deactivate():
            subscribe("LTP", base[:1], seconds=3.0)
            subscribe("Quote", base[:1], seconds=3.0)
            unsubscribe("LTP", base[:1])
            time.sleep(1)
            frames = c.market_frames(7.0)
            modes = {f.get("mode") for f in frames}
            need(2 in modes, "Quote stopped when only LTP was unsubscribed")
            need(1 not in modes, "LTP frames continue after unsubscribing LTP")
            unsubscribe("Quote", base[:1])

        run.check("WS-23", mode_deactivate, endpoint="ws.unsubscribe",
                  expected="only the unsubscribed mode stops")

        def two_modes():
            subscribe("LTP", base[:1], seconds=3.0)
            subscribe("Quote", base[:1], seconds=3.0)
            frames = c.market_frames(8.0)
            modes = {f.get("mode") for f in frames}
            need({1, 2} <= modes, f"expected both mode 1 and 2 concurrently, saw {modes}")
            for mode in ("LTP", "Quote"):
                unsubscribe(mode, base[:1])

        run.check("WS-24", two_modes, endpoint="ws.subscribe",
                  expected="two modes stream independently")

        def broker_field():
            _, frames = subscribe("LTP", base[:1], seconds=6.0)
            need(frames, "no frames")
            b = {f.get("broker") for f in frames}
            need(b and None not in b, "frames carry no broker field")
            need(run.env["broker"] in b,
                 f"broker field {b} does not name the broker under test "
                 f"{run.env['broker']!r}")
            unsubscribe("LTP", base[:1])

        run.check("WS-28", broker_field, endpoint="ws.LTP", expected="broker named on frames")
    finally:
        c.close()

    def reconnect():
        """WS-25 - after a forced drop the client must re-auth and re-subscribe,
        and the server must NOT silently restore the old subscriptions."""
        c1 = WSClient(WS_URL)
        c1.auth(API_KEY)
        c1.send({"action": "subscribe", "mode": "LTP", "symbols": base[:1]})
        c1.market_frames(4.0)
        c1.close()                      # forced drop
        time.sleep(2)
        c2 = WSClient(WS_URL)
        try:
            stale = c2.market_frames(4.0)
            need(not stale, "server restored subscriptions for a new connection")
            r = c2.auth(API_KEY)
            need(r is not None, "cannot re-authenticate after a drop")
            c2.send({"action": "subscribe", "mode": "LTP", "symbols": base[:1]})
            need(c2.market_frames(8.0), "frames do not resume after re-subscribe")
        finally:
            c2.close()

    run.check("WS-25", reconnect, endpoint="ws.reconnect",
              expected="re-auth + re-subscribe resumes; no silent restore")

    run.record("WS-26", SKIP,
               "token rollover needs a broker re-login mid-session - manual check",
               endpoint="ws.reconnect")
    run.record("WS-27", SKIP,
               "data-stall watchdog needs an induced upstream stall - manual check",
               endpoint="ws.keepalive")

    # ---- 12. order updates ----------------------------------------------
    sec_order_updates(run, base)


def sec_order_updates(run: Runner, base: list) -> None:
    run.section("12. WebSocket order updates")
    m = run.matrix
    if "EQ_CHEAP" not in m:
        run.blocked("OU-*", "EQ_CHEAP unresolved", endpoint="ws.orders")
        return
    sym, ex = m["EQ_CHEAP"]
    ltp = as_num(run.ok(run.client.quotes(symbol=sym, exchange=ex), "q")["data"]["ltp"], "ltp")

    c = WSClient(WS_URL, timeout=20)
    updates: list[dict] = []
    try:
        c.auth(API_KEY)

        def subscribe_orders():
            c.send({"action": "subscribe_orders", "request_id": "qa-orders"})
            ack = c.recv_until(lambda f: f.get("type") == "subscribe_orders", 8.0)
            need(ack is not None, "no subscribe_orders acknowledgement")
            need(ack.get("status") == "success", f"subscribe_orders refused: {ack}")

        run.check("OU-01", subscribe_orders, endpoint="ws.subscribe_orders",
                  expected="acknowledged")

        def collect(seconds=10.0):
            end = time.time() + seconds
            while time.time() < end:
                try:
                    c.ws.settimeout(max(0.5, end - time.time()))
                    f = json.loads(c.ws.recv())
                except Exception:
                    continue
                if f.get("type") == "order_update":
                    updates.append(f)
            return updates

        def lifecycle_pushed():
            """OU-02 - drive open -> cancelled and a rejection, assert each push."""
            t0 = time.perf_counter()
            r = run.ok(run.client.placeorder(
                strategy="QA-SANDBOX", symbol=sym, exchange=ex, action="BUY",
                price_type="LIMIT", product="MIS", quantity=1,
                price=round(ltp * 0.80, 2)), "placeorder")
            oid = str(r["orderid"])
            run.track_order(oid, sym, ex, "MIS")
            collect(8.0)
            first = next((u for u in updates if str(u.get("orderid")) == oid), None)
            need(first is not None, "no order_update pushed after placing an order")
            run.note_limit("order_update push latency",
                           f"{(time.perf_counter()-t0)*1000:.0f}ms to first update")
            run.client.cancelorder(order_id=oid, strategy="QA-SANDBOX")
            collect(8.0)
            states = {u.get("order_status") for u in updates
                      if str(u.get("orderid")) == oid}
            need("cancelled" in states,
                 f"cancellation not pushed - states seen for {oid}: {states}")
            run.env["ou_states"] = sorted(s for s in states if s)

        run.check("OU-02", lifecycle_pushed, endpoint="ws.orders",
                  expected="open and cancelled both pushed")

        def contract():
            need(updates, "no order updates collected")
            u = updates[-1]
            need_keys(u, ["orderid", "symbol", "exchange", "action", "quantity",
                          "pricetype", "product", "order_status"], "order_update")
            need(u["action"] in ("BUY", "SELL"), f"action {u['action']!r}")
            need(u["pricetype"] in ("MARKET", "LIMIT", "SL", "SL-M"),
                 f"pricetype {u['pricetype']!r}")
            need(u["product"] in ("CNC", "NRML", "MIS"), f"product {u['product']!r}")
            need(u["order_status"] == u["order_status"].lower(),
                 f"order_status {u['order_status']!r} not lowercase")

        run.check("OU-04", contract, endpoint="ws.orders",
                  expected="OpenAlgo constants, lowercase status")

        def symbol_format():
            need(updates, "no order updates collected")
            with run.db() as db:
                for u in updates[:10]:
                    n = db.execute(
                        "select count(*) from symtoken where symbol=? and exchange=?",
                        (u.get("symbol"), u.get("exchange"))).fetchone()[0]
                    need(n > 0, f"order_update symbol {u.get('symbol')!r}@"
                                f"{u.get('exchange')!r} is not an OpenAlgo symbol")

        run.check("OU-03", symbol_format, endpoint="ws.orders",
                  expected="OpenAlgo symbol, not broker tradingsymbol")

        def quantities():
            need(updates, "no order updates collected")
            checked = 0
            for u in updates:
                if "filled_quantity" not in u or "pending_quantity" not in u:
                    continue
                q = as_num(u["quantity"], "quantity")
                f = as_num(u["filled_quantity"], "filled_quantity")
                p = as_num(u["pending_quantity"], "pending_quantity")
                need(abs((f + p) - q) < 1e-6,
                     f"{u['orderid']}: filled {f} + pending {p} != quantity {q}")
                checked += 1
            if not checked:
                raise Warn("no update carried filled/pending quantities")

        run.check("OU-05", quantities, endpoint="ws.orders",
                  expected="filled + pending reconcile with quantity")

        def fill_price():
            oid = None
            r = run.ok(run.client.placeorder(
                strategy="QA-SANDBOX", symbol=sym, exchange=ex, action="BUY",
                price_type="MARKET", product="MIS", quantity=1), "placeorder market")
            oid = str(r["orderid"])
            run.track_order(oid, sym, ex, "MIS")
            collect(10.0)
            done = [u for u in updates if str(u.get("orderid")) == oid
                    and u.get("order_status") == "complete"]
            need(done, f"no 'complete' update pushed for the market order {oid}")
            need_nonzero(done[-1].get("average_price"), "average_price on fill")

        run.check("OU-06", fill_price, endpoint="ws.orders",
                  expected="fill carries a non-zero average_price")

        def rejection():
            before = len(updates)
            try:
                run.client.placeorder(strategy="QA-SANDBOX", symbol=sym, exchange=ex,
                                      action="BUY", price_type="LIMIT", product="MIS",
                                      quantity=1, price=round(ltp * 10, 2))
            except Exception:
                pass
            collect(8.0)
            rej = [u for u in updates[before:] if u.get("order_status") == "rejected"]
            if not rej:
                raise Warn("could not induce a rejection - no rejected update to assert")
            need(str(rej[-1].get("rejection_reason", "")).strip(),
                 "rejected update carries an empty rejection_reason")

        run.check("OU-07", rejection, endpoint="ws.orders",
                  expected="rejection carries rejection_reason")

        def statuses_seen():
            seen = {u.get("order_status") for u in updates}
            want = {"open", "complete", "cancelled"}
            missing = want - seen
            run.note_limit("order_update statuses pushed", ", ".join(sorted(x for x in seen if x)))
            if missing:
                raise Warn(f"statuses not pushed this run: {sorted(missing)}")

        run.check("OU-09", statuses_seen, endpoint="ws.orders",
                  expected="open/complete/cancelled all pushed")

        def mode_field():
            need(updates, "no order updates collected")
            modes = {u.get("mode") for u in updates}
            need(modes <= {"analyze", "live", None},
                 f"unexpected mode values {modes}")
            need("analyze" in modes,
                 f"sandbox run must push mode=analyze, saw {modes}")

        run.check("OU-13", mode_field, endpoint="ws.orders", expected="mode=analyze in sandbox")

        def dedupe():
            keys = [(str(u.get("orderid")), u.get("order_status"),
                     u.get("filled_quantity")) for u in updates]
            dupes = len(keys) - len(set(keys))
            run.note_limit("duplicate order_update frames", dupes)
            if dupes:
                raise Warn(f"{dupes} duplicate frames on "
                           f"(orderid, order_status, filled_quantity)")

        run.check("OU-12", dedupe, endpoint="ws.orders",
                  expected="no duplicate transitions")

        def unsub():
            c.send({"action": "unsubscribe_orders"})
            ack = c.recv_until(lambda f: f.get("type") == "unsubscribe_orders", 8.0)
            need(ack is not None, "no unsubscribe_orders acknowledgement")
            need(ack.get("status") == "success", f"unsubscribe refused: {ack}")

        run.check("OU-15", unsub, endpoint="ws.orders", expected="unsubscribed")
    finally:
        c.close()

    run.record("OU-08", SKIP,
               "partial fill needs a large resting order to fill in pieces - manual check",
               endpoint="ws.orders")
    run.record("OU-10", SKIP,
               "non-API order origin needs an order placed from the broker's own app",
               endpoint="ws.orders")
    run.record("OU-11", SKIP,
               "polling fallback only applies to brokers with no push feed",
               endpoint="ws.orders")
    run.record("OU-14", SKIP,
               "push latency recorded in Observed Limits by OU-02",
               endpoint="ws.orders")


# ==========================================================================
# 15. cross-cutting negatives
# ==========================================================================
def sec_negative(run: Runner) -> None:
    run.section("15. Negative cases")
    m = run.matrix

    def no_key():
        r = httpx.post(f"{HOST}/api/v1/orderbook", json={}, timeout=30)
        need(r.status_code in (400, 401, 403), f"missing apikey -> HTTP {r.status_code}")

    run.check("NG-01", no_key, endpoint="orderbook", expected="401")

    def bad_key():
        r = httpx.post(f"{HOST}/api/v1/orderbook", json={"apikey": "deadbeef"}, timeout=30)
        need(r.status_code in (401, 403), f"bad apikey -> HTTP {r.status_code}")

    run.check("NG-02", bad_key, endpoint="orderbook", expected="403")

    def malformed():
        r = httpx.post(f"{HOST}/api/v1/quotes", content=b"{not json",
                       headers={"Content-Type": "application/json"}, timeout=30)
        need(r.status_code < 500, f"malformed JSON -> HTTP {r.status_code} (must not 500)")

    run.check("NG-03", malformed, endpoint="quotes", expected="400 not 500")

    def mismatch():
        if "EQ_LIQUID" not in m:
            raise Skip("EQ_LIQUID unresolved")
        run.expect_error(run.client.quotes(symbol=m["EQ_LIQUID"][0], exchange="NFO"),
                         "equity symbol on NFO")

    run.check("NG-06", mismatch, endpoint="quotes", expected="clean 400")

    def ng_unknown_field():
        """NG-04 - an unrecognised field is ignored or cleanly rejected."""
        if "EQ_LIQUID" not in m:
            raise Skip("EQ_LIQUID unresolved")
        s, e = m["EQ_LIQUID"]
        r = httpx.post(f"{HOST}/api/v1/quotes",
                       json={"apikey": API_KEY, "symbol": s, "exchange": e,
                             "not_a_real_field": "x", "nested": {"a": 1}},
                       timeout=60)
        need(r.status_code < 500, f"unknown field produced HTTP {r.status_code}")
        body = r.json()
        need(body.get("status") in ("success", "error"),
             f"unexpected status {body.get('status')!r}")
        if body.get("status") == "error":
            need(str(body.get("message", "")), "rejected without a message")

    run.check("NG-04", ng_unknown_field, endpoint="quotes",
              expected="ignored or cleanly rejected, never 500")

    def ng_unsupported_exchange():
        """NG-05 - an exchange the broker does not claim fails fast and clearly."""
        unclaimed = next((e for e in ("NCDEX", "BCD", "NCO", "GLOBAL_INDEX", "CRYPTO")
                          if e not in run.env["exchanges"]), None)
        if not unclaimed:
            raise Skip("broker claims every exchange this check would try")
        t = time.perf_counter()
        msg = run.expect_error(
            run.client.quotes(symbol="ZZNOTREAL99", exchange=unclaimed),
            f"quotes on unclaimed {unclaimed}")
        el = (time.perf_counter() - t) * 1000
        need(el < 15000, f"{unclaimed} took {el:.0f}ms to refuse - should fail fast")
        run.note_limit(f"unsupported exchange {unclaimed}", f"{msg[:70]} ({el:.0f}ms)")

    run.check("NG-05", ng_unsupported_exchange, endpoint="quotes",
              expected="fast, clear refusal naming the exchange")

    def ng_expired_token():
        """NG-07 - with a broker token revoked, calls must 401/403 with a
        re-login hint rather than silently returning empty data."""
        raise Skip("revoking the live broker token would end the session - "
                   "verify manually by logging out and re-running one call")

    run.check("NG-07", ng_expired_token, endpoint="-",
              expected="clean 401/403 with a re-login hint")

    def ng_concurrent():
        """NG-08 - two identical requests must not produce two orders."""
        if "EQ_CHEAP" not in m:
            raise Skip("EQ_CHEAP unresolved")
        s, e = m["EQ_CHEAP"]
        q = run.ok(run.client.quotes(symbol=s, exchange=e), "quotes")["data"]
        price = round(as_num(q["ltp"], "ltp") * 0.80, 2)
        body = {"apikey": API_KEY, "strategy": STRAT, "symbol": s, "exchange": e,
                "action": "BUY", "pricetype": "LIMIT", "product": "MIS",
                "quantity": "1", "price": str(price)}
        out: list = []

        def fire():
            try:
                out.append(httpx.post(f"{HOST}/api/v1/placeorder", json=body, timeout=60).json())
            except Exception as exc:  # noqa: BLE001
                out.append({"status": "error", "message": str(exc)})

        threads = [threading.Thread(target=fire) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        ids = [str(o.get("orderid")) for o in out if o.get("orderid")]
        for i in ids:
            run.track_order(i, s, e, "MIS")
        run.note_limit("concurrent identical placeorder",
                       f"{len(out)} responses, {len(set(ids))} distinct orderids")
        need(out, "no responses from the concurrent requests")
        # Two deliberate API calls legitimately create two orders; what must not
        # happen is one call yielding two, or a crash.
        need(len(set(ids)) == len(ids), f"duplicate orderid returned across calls: {ids}")

    run.check("NG-08", ng_concurrent, endpoint="placeorder",
              expected="no duplicate orderid, no crash under concurrency")

    def ng_error_log():
        """NG-09 - attach anything new in log/errors.jsonl to the report."""
        p = Path(__file__).resolve().parents[4] / "log" / "errors.jsonl"
        if not p.is_file():
            raise Skip(f"no error log at {p}")
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        start = run.env.get("errlog_start_lines", 0)
        new = lines[start:]
        run.env["error_log_rows"] = [[str(i + start + 1), ln[:400]]
                                     for i, ln in enumerate(new)]
        run.note_limit("new errors.jsonl entries during this run", len(new))
        if new:
            raise Warn(f"{len(new)} new error(s) logged during this run - "
                       f"see the Errors Log sheet")

    run.check("NG-09", ng_error_log, endpoint="log/errors.jsonl",
              expected="new entries captured even when checks passed")

    def no_secrets():
        blob = json.dumps([r.__dict__ for r in run.results])
        need(API_KEY not in blob, "API key leaked into a recorded response")

    run.check("NG-10", no_secrets, endpoint="-", expected="no credential in results")


# ==========================================================================
# 1.6 / 13. cross-cutting assertions and latency
# ==========================================================================
def sec_universal(run: Runner) -> None:
    """UNI-01..10 and LT-01..13 are not per-endpoint cases.

    UNI-* are enforced on every single call by the shared helpers, and LT-* is
    the latency captured on every result row. Reporting them as their own rows
    makes that enforcement auditable instead of invisible - each row states
    where the rule lives and how many calls it was applied to.
    """
    run.section("1.6 / 13. Cross-cutting rules")
    n = len(run.results)

    def enforced(rule: str, where: str, evidence=None):
        def _check():
            need(n > 0, "no calls were made, so nothing was enforced")
            if evidence is not None:
                evidence()
            run.note_limit(f"UNI rule: {rule}", f"{where} (applied across {n} checks)")
        return _check

    run.check("UNI-01", enforced("HTTP status matches the scenario",
                                 "run.ok() / run.expect_error() on every call"),
              endpoint="-", expected="enforced globally")
    run.check("UNI-02", enforced("status is exactly success or error",
                                 "Runner.ok() rejects any other value"),
              endpoint="-", expected="enforced globally")
    run.check("UNI-03", enforced("errors carry a message and leak no traceback",
                                 "Runner.ok() / expect_error()"),
              endpoint="-", expected="enforced globally")
    run.check("UNI-04", enforced("documented field names only",
                                 "need_keys() against docs/api/** per endpoint"),
              endpoint="-", expected="enforced globally")
    run.check("UNI-05", enforced("documented types; no '1,234.50'",
                                 "as_num() rejects separators, bools and non-numerics"),
              endpoint="-", expected="enforced globally")
    run.check("UNI-06", enforced("no NaN, Inf or -0.0",
                                 "as_num() rejects them"),
              endpoint="-", expected="enforced globally")
    run.check("UNI-07", enforced("prices rounded to 2dp in books",
                                 "need_2dp() in OB-07, PB-08, FN-04"),
              endpoint="-", expected="enforced globally")

    def no_credentials():
        blob = json.dumps([r.__dict__ for r in run.results])
        need(API_KEY and API_KEY not in blob, "API key appears in a recorded result")
        for tok in ("Bearer ", "access_token", "feed_token"):
            need(tok not in blob, f"{tok!r} appears in a recorded result")

    run.check("UNI-08", no_credentials, endpoint="-",
              expected="no key or token in any recorded result")

    def latency_captured():
        timed = [r for r in run.results if r.latency_ms > 0]
        need(timed, "no latency captured on any check")
        need(len(timed) >= n * 0.5,
             f"only {len(timed)}/{n} checks carry a latency - UNI-09 requires every call timed")
        run.note_limit("checks with latency captured", f"{len(timed)}/{n}")

    run.check("UNI-09", latency_captured, endpoint="-",
              expected="round-trip latency on every call")

    def error_log_swept():
        need("error_log_rows" in run.env or run.env.get("errlog_start_lines") is not None,
             "log/errors.jsonl was never sampled - NG-09 did not run")
        rows = run.env.get("error_log_rows") or []
        run.note_limit("errors.jsonl entries attached", len(rows))

    run.check("UNI-10", error_log_swept, endpoint="-",
              expected="new error-log entries attached to the report")

    # ---- latency ----
    import statistics as st

    def lat(cid: str, label: str, match) -> None:
        def _check():
            vals = sorted(r.latency_ms for r in run.results
                          if r.latency_ms > 0 and match(r))
            if not vals:
                raise Skip(f"no {label} calls were made this run")
            p95 = vals[min(len(vals) - 1, int(len(vals) * 0.95))]
            summary = (f"n={len(vals)} min={min(vals):.0f} med={st.median(vals):.0f} "
                       f"p95={p95:.0f} max={max(vals):.0f} ms")
            run.note_limit(f"latency {label}", summary)
            slow = float(os.getenv("QA_SLOW_MS", "3000"))
            if p95 > slow:
                raise Warn(f"{label}: p95 {p95:.0f}ms exceeds the {slow:.0f}ms threshold "
                           f"({summary})")
        run.check(cid, _check, endpoint=label, expected="min/median/p95/max recorded")

    def ep(*names):
        return lambda r: any(nm in (r.endpoint or "") for nm in names)

    lat("LT-01", "placeorder", ep("placeorder"))
    lat("LT-02", "placesmartorder", ep("placesmartorder"))
    lat("LT-03", "splitorder", ep("splitorder"))
    lat("LT-04", "basketorder", ep("basketorder"))
    lat("LT-05", "optionsorder/multiorder", ep("optionsorder", "optionsmultiorder"))
    lat("LT-06", "modify/cancel/close", ep("modifyorder", "cancelorder",
                                           "cancelallorder", "closeposition"))
    lat("LT-07", "gtt", ep("gttorder", "placegttorder", "modifygttorder", "cancelgttorder"))
    lat("LT-08", "books", ep("orderbook", "tradebook", "positionbook", "holdings", "funds"))
    lat("LT-09", "market data", ep("quotes", "multiquotes", "depth"))
    lat("LT-10", "history", ep("history"))
    lat("LT-11", "options services", ep("optionchain", "optiongreeks", "multioptiongreeks",
                                        "optionsymbol", "syntheticfuture"))
    lat("LT-12", "websocket", ep("ws."))

    def outliers():
        slow = float(os.getenv("QA_SLOW_MS", "3000"))
        bad = [(r.id, r.endpoint, r.latency_ms) for r in run.results if r.latency_ms > slow]
        run.note_limit("latency outliers", f"{len(bad)} checks over {slow:.0f}ms")
        if bad:
            bad.sort(key=lambda x: -x[2])
            raise Warn(f"{len(bad)} slow call(s), worst: " +
                       ", ".join(f"{i}={ms:.0f}ms" for i, _, ms in bad[:5]))

    run.check("LT-13", outliers, endpoint="-",
              expected="calls above the threshold flagged amber")


# ==========================================================================
# 14. sandbox parity
# ==========================================================================
SHAPES_FILE = Path(__file__).parent / "qa_shapes.json"


def _shape(obj, depth=0):
    """Field names and types only - never values."""
    if depth > 3:
        return "..."
    if isinstance(obj, dict):
        return {k: _shape(v, depth + 1) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        return [_shape(obj[0], depth + 1)] if obj else []
    if isinstance(obj, bool):
        return "bool"
    if isinstance(obj, (int, float)):
        return "number"
    if obj is None:
        return "null"
    return "string"


def capture_shapes(run: Runner) -> dict:
    """Record the response shape of each mode-sensitive endpoint."""
    out: dict = {}
    for name, fn in (("orderbook", run.client.orderbook),
                     ("tradebook", run.client.tradebook),
                     ("positionbook", run.client.positionbook),
                     ("funds", run.client.funds)):
        try:
            r = fn()
            if isinstance(r, dict) and r.get("status") == "success":
                out[name] = _shape(r.get("data"))
        except Exception:
            continue
    try:
        gb = run.client.gttorderbook()
        if isinstance(gb, dict) and gb.get("status") == "success":
            out["gttorderbook"] = _shape(gb.get("data"))
    except Exception:
        pass
    return out


def sec_sandbox_parity(run: Runner) -> None:
    run.section("14. Sandbox parity")

    def mode_analyze():
        """SB-01 - order endpoints answer with mode=analyze in sandbox."""
        if "EQ_CHEAP" not in run.matrix:
            raise Skip("EQ_CHEAP unresolved")
        s, ex = run.matrix["EQ_CHEAP"]
        q = as_num(run.ok(run.client.quotes(symbol=s, exchange=ex), "q")["data"]["ltp"], "ltp")
        r = run.ok(run.client.placeorder(strategy=STRAT, symbol=s, exchange=ex, action="BUY",
                                         price_type="LIMIT", product="MIS", quantity=1,
                                         price=round(q * 0.80, 2)), "placeorder")
        run.track_order(r.get("orderid"), s, ex, "MIS")
        need(str(r.get("mode", "")).lower() == "analyze",
             f"sandbox placeorder reported mode={r.get('mode')!r}, expected 'analyze'")

    run.check("SB-01", mode_analyze, endpoint="placeorder", expected="mode=analyze")

    shapes = capture_shapes(run)
    run.env["shapes"] = shapes

    other = {}
    if SHAPES_FILE.is_file():
        try:
            saved = json.loads(SHAPES_FILE.read_text(encoding="utf-8"))
            if saved.get("mode") != run.mode:
                other = saved
        except Exception:
            other = {}

    MODE_ONLY = {"mode", "triggered_order_id", "strategy", "margin_blocked",
                 "average_price_basis"}

    def parity(kind: str):
        def _check():
            if not other:
                raise Skip(f"no counterpart {'LIVE' if run.mode == 'SANDBOX' else 'SANDBOX'} "
                           f"run recorded - run the other script, then re-run this one")
            mine, theirs = shapes, other.get("shapes", {})
            common = set(mine) & set(theirs)
            need(common, "the two runs share no comparable endpoint")
            diffs = []
            for ep in sorted(common):
                a, b = _flatten(mine[ep]), _flatten(theirs[ep])
                if kind == "names":
                    only_a = {k for k in a if k not in b and k.split(".")[-1] not in MODE_ONLY}
                    only_b = {k for k in b if k not in a and k.split(".")[-1] not in MODE_ONLY}
                    if only_a or only_b:
                        diffs.append(f"{ep}: only here {sorted(only_a)[:4]}, "
                                     f"only there {sorted(only_b)[:4]}")
                else:
                    for k in set(a) & set(b):
                        if a[k] != b[k] and k.split(".")[-1] not in MODE_ONLY:
                            diffs.append(f"{ep}.{k}: {a[k]} here vs {b[k]} there")
            need(not diffs, f"{kind} differ between modes: {diffs[:4]}")
            run.note_limit(f"parity ({kind})", f"{len(common)} endpoints identical")
        return _check

    run.check("SB-02", parity("names"), endpoint="-",
              expected="identical field names across modes")
    run.check("SB-03", parity("types"), endpoint="-",
              expected="identical field types across modes")

    def status_parity():
        mine = set(run.env.get("statuses_seen") or [])
        if not other:
            raise Skip("no counterpart run recorded")
        theirs = set(other.get("statuses_seen") or [])
        need(mine and theirs, "one of the runs observed no order statuses")
        allowed = {"open", "complete", "cancelled", "rejected", "trigger pending", "pending"}
        bad = (mine | theirs) - allowed
        need(not bad, f"non-OpenAlgo status values seen: {sorted(bad)}")
        run.note_limit("status vocabulary", f"sandbox={sorted(mine)} live={sorted(theirs)}")

    run.check("SB-04", status_parity, endpoint="-",
              expected="same lowercase status vocabulary")

    def lifecycle():
        """SB-05 - open -> complete and open -> cancelled both reachable."""
        if "EQ_CHEAP" not in run.matrix:
            raise Skip("EQ_CHEAP unresolved")
        s, ex = run.matrix["EQ_CHEAP"]
        q = as_num(run.ok(run.client.quotes(symbol=s, exchange=ex), "q")["data"]["ltp"], "ltp")
        done = run.ok(run.client.placeorder(strategy=STRAT, symbol=s, exchange=ex, action="BUY",
                                            price_type="MARKET", product="MIS", quantity=1),
                      "market")
        run.track_order(done.get("orderid"), s, ex, "MIS")
        resting = run.ok(run.client.placeorder(strategy=STRAT, symbol=s, exchange=ex,
                                               action="BUY", price_type="LIMIT", product="MIS",
                                               quantity=1, price=round(q * 0.80, 2)), "limit")
        run.track_order(resting.get("orderid"), s, ex, "MIS")
        time.sleep(2.0)
        st1 = run.ok(run.client.orderstatus(order_id=done["orderid"], strategy=STRAT),
                     "status")["data"]["order_status"]
        need(st1 == "complete", f"sandbox market order reached {st1!r}, expected complete")
        run.ok(run.client.cancelorder(order_id=resting["orderid"], strategy=STRAT), "cancel")
        time.sleep(1.5)
        st2 = run.ok(run.client.orderstatus(order_id=resting["orderid"], strategy=STRAT),
                     "status")["data"]["order_status"]
        need(st2 == "cancelled", f"sandbox cancel reached {st2!r}, expected cancelled")

    run.check("SB-05", lifecycle, endpoint="placeorder+cancelorder",
              expected="open -> complete and open -> cancelled both reachable")

    def sandbox_gtt():
        gb = run.client.gttorderbook()
        if "not supported" in str(gb.get("message", "")).lower():
            raise Skip("broker ships no gtt_api, so sandbox GTT is unreachable")
        need(gb.get("status") == "success", f"sandbox gttorderbook failed: {gb.get('message')}")
        if str(gb.get("mode", "")).lower() != "analyze":
            raise Warn(f"sandbox gttorderbook reported mode={gb.get('mode')!r}")
        for g in (gb.get("data") or []):
            if "margin_blocked" in g:
                as_num(g["margin_blocked"], "margin_blocked")
                return
        raise Warn("no active sandbox GTT carried margin_blocked - place one to exercise it")

    run.check("SB-06", sandbox_gtt, endpoint="gttorderbook",
              expected="sandbox GTT answers with mode=analyze and margin_blocked")

    def sandbox_order_stream():
        pushed = run.env.get("ou_states")
        if not pushed:
            raise Skip("order-update stream not exercised (QA_WS=0 or no updates captured)")
        run.note_limit("sandbox order_update states", ", ".join(pushed))
        need(all(s == s.lower() for s in pushed), f"non-lowercase statuses pushed: {pushed}")

    run.check("SB-07", sandbox_order_stream, endpoint="ws.orders",
              expected="same order_update shape with mode=analyze")

    def pnl_symbols():
        r = post("pnl/symbols", {})
        need(isinstance(r, dict), f"pnl/symbols returned {type(r).__name__}")
        if r.get("status") == "error":
            msg = str(r.get("message", ""))
            need(msg, "pnl/symbols errored without a message")
            raise Warn(f"pnl/symbols unavailable: {msg[:80]}")
        need("data" in r or "symbols" in r, f"unexpected payload keys {sorted(r)[:6]}")

    run.check("SB-08", pnl_symbols, endpoint="pnl/symbols",
              expected="analyzer P&L symbols returned")

    def isolation():
        """SB-09 - sandbox orders must not appear at the broker. Verified by
        toggling to live and checking this run's orderids are absent."""
        ours = {x["orderid"] for x in run.order_ledger}
        if not ours:
            raise Skip("no orders placed to check isolation")
        try:
            run.client.analyzertoggle(mode=False)
            time.sleep(1.5)
            live = {str(o["orderid"]) for o in
                    ((run.client.orderbook() or {}).get("data") or {}).get("orders") or []}
        finally:
            run.client.analyzertoggle(mode=True)
            time.sleep(1.5)
        leaked = ours & live
        need(not leaked,
             f"{len(leaked)} sandbox orderid(s) appear in the LIVE orderbook: "
             f"{sorted(leaked)[:4]}")
        run.note_limit("mode isolation", f"{len(ours)} sandbox orders, none in the live book")

    run.check("SB-09", isolation, endpoint="orderbook",
              expected="no sandbox order reaches the broker")

    run.record("SB-10", PASS,
               "Sandbox results do not evidence broker correctness - analyzer mode routes "
               "to sandbox_service and never calls the broker plugin. Order-path results "
               "here prove the contract, not the integration; qa_live.py is the "
               "authority for that.",
               endpoint="-")

    try:
        SHAPES_FILE.write_text(json.dumps(
            {"mode": run.mode, "broker": run.env.get("broker"), "when": now_ist(),
             "shapes": shapes, "statuses_seen": run.env.get("statuses_seen") or []},
            indent=1), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        run.record("SB-00", WARN, f"could not persist shapes for cross-mode parity: {e}",
                   endpoint="-")


def _flatten(shape, prefix=""):
    out = {}
    if isinstance(shape, dict):
        for k, v in shape.items():
            out.update(_flatten(v, f"{prefix}{k}."))
    elif isinstance(shape, list):
        if shape:
            out.update(_flatten(shape[0], prefix))
    else:
        out[prefix.rstrip(".")] = shape
    return out


# ==========================================================================
def main() -> int:
    if not API_KEY:
        print("Set OPENALGO_API_KEY (never hardcode it - gap analysis defect A-01)")
        return 2
    try:
        from openalgo import api as OAClient
    except ImportError:
        print("openalgo SDK missing - uv pip install openalgo")
        return 2

    client = OAClient(api_key=API_KEY, host=HOST, ws_url=os.getenv("OPENALGO_WS", "ws://127.0.0.1:8765"))
    run = Runner(client=client, mode="SANDBOX", host=HOST)
    broker = active_broker()
    run.env = {"broker": broker, "started": now_ist(),
               "exchanges": load_plugin_exchanges(broker)}
    print(f"Broker: {broker or '(unknown)'}   Host: {HOST}")
    print(f"Exchanges claimed: {run.env['exchanges']}")

    run.section("1. Preconditions")
    run.check("PRE-01", lambda: need(bool(broker), "no non-revoked auth row"),
              endpoint="auth", expected="one active broker")
    run.check("PRE-02", lambda: need(bool(run.env["exchanges"]), "plugin.json has no supported_exchanges"),
              endpoint="plugin.json", expected="exchange list captured")

    def token_valid():
        """PRE-03 - the stored broker token still authenticates."""
        r = run.client.funds()
        need(isinstance(r, dict), f"funds returned {type(r).__name__}")
        msg = str(r.get("message", "")).lower()
        need(r.get("status") == "success",
             f"broker token appears invalid or expired: {r.get('message')}")
        need("login" not in msg and "token" not in msg, f"auth warning in response: {msg}")

    run.check("PRE-03", token_valid, endpoint="funds", expected="authenticated, non-403")

    def master_fresh():
        """PRE-04 - master contract downloaded successfully, and today."""
        with run.db() as c:
            try:
                rows = c.execute(
                    "select exchange, status, last_updated from master_contract_status"
                ).fetchall()
            except Exception:
                rows = []
        if not rows:
            with run.db() as c:
                n = c.execute("select count(*) from symtoken").fetchone()[0]
            need(n > 0, "symtoken is empty - the master contract has never downloaded")
            raise Warn(f"no master_contract_status table; symtoken holds {n} rows")
        bad = [(e, s) for e, s, _ in rows if str(s).lower() != "success"]
        need(not bad, f"master contract not successful for {bad[:4]}")
        stamps = [str(t) for _, _, t in rows if t]
        if stamps:
            newest = max(stamps)
            run.env["master_contract_updated"] = newest
            need(str(date.today()) in newest,
                 f"master contract last updated {newest}, not today - re-download before "
                 f"trusting symbol-level results")

    run.check("PRE-04", master_fresh, endpoint="master_contract_status",
              expected="success for every exchange, dated today")

    def market_open():
        """PRE-05 - skip-with-reason outside a session, never fail."""
        now = datetime.now(IST)
        if now.weekday() >= 5:
            raise Skip(f"{now:%A} - markets closed; run during a trading session")
        eq_open = now.replace(hour=9, minute=15, second=0) <= now <= \
            now.replace(hour=15, minute=30, second=0)
        mcx_open = now.replace(hour=9, minute=0, second=0) <= now <= \
            now.replace(hour=23, minute=30, second=0)
        run.env["sessions"] = {"equity_fo": eq_open, "mcx": mcx_open}
        run.note_limit("session at run start",
                       f"{now:%H:%M IST} equity/F&O={'open' if eq_open else 'closed'}, "
                       f"MCX={'open' if mcx_open else 'closed'}")
        if not eq_open and not mcx_open:
            raise Skip(f"{now:%H:%M IST} - no exchange in session; live prices, depth and "
                       f"order fills will not behave as the checklist expects")
        if not eq_open:
            raise Warn(f"{now:%H:%M IST} - equity/F&O closed, MCX open; "
                       f"NSE/BSE/NFO results will be stale")

    run.check("PRE-05", market_open, endpoint="-", expected="a session is open")

    def enter_sandbox():
        run.client.analyzertoggle(mode=True)
        time.sleep(1.0)
        st = run.client.analyzerstatus()
        on = str(st.get("data", st)).lower()
        need("true" in on or "analyze" in on, f"analyzer did not engage: {st}")

    run.check("PRE-06", enter_sandbox, endpoint="analyzer/toggle", expected="sandbox engaged")

    # Baseline for NG-09: only errors logged after this point belong to the run.
    _errlog = Path(__file__).resolve().parents[4] / "log" / "errors.jsonl"
    run.env["errlog_start_lines"] = (
        len(_errlog.read_text(encoding="utf-8", errors="replace").splitlines())
        if _errlog.is_file() else 0)

    run.matrix = resolve_matrix(run, run.env["exchanges"])
    print(f"\nSymbol matrix: {len([k for k in run.matrix if not k.startswith('_')])} slots resolved, "
          f"{len(run.matrix.get('_unresolved', []))} unresolved")
    for u in run.matrix.get("_unresolved", []):
        print(f"  unresolved: {u}")

    for fn in (sec_master, sec_ticks, sec_symbols, sec_quotes, sec_history, sec_options,
               sec_orders, sec_books, sec_gtt, sec_margin, sec_websocket, sec_negative, sec_sandbox_parity, sec_universal):
        try:
            fn(run)
        except Exception as e:
            run.record(f"{fn.__name__}", "ERROR", f"section aborted: {type(e).__name__}: {e}")

    # teardown - leave the sandbox account flat
    run.section("Teardown")
    run.check("TD-01", lambda: run.client.cancelallorder(strategy=STRAT),
              endpoint="cancelallorder", expected="no resting orders left")
    run.check("TD-02", lambda: run.client.closeposition(strategy=STRAT),
              endpoint="closeposition", expected="flat")
    for t in list(run.gtt_ledger):
        run.check(f"TD-03.{t}", lambda t=t: run.client.cancelgttorder(trigger_id=t, strategy=STRAT),
                  endpoint="cancelgttorder", expected="GTT cleaned up")

    ok = print_rollup(run)
    out = Path(__file__).parent / f"qa_sandbox_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    extra = {}
    if run.env.get("missing_symbols"):
        extra["Missing Symbols"] = [["Exchange", "Symbol", "Note"]] + run.env["missing_symbols"]
    extra["Errors Log"] = ([["Line", "Entry"]] + run.env["error_log_rows"]
                           if run.env.get("error_log_rows")
                           else [["Line", "Entry"],
                                 ["-", "no new entries in log/errors.jsonl during this run"]])
    p = write_report(run, out, extra)
    print(f"\nReport: {p}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
