#!/usr/bin/env python3
"""Broker QA audit - LIVE runner.

Deliberately narrow. Only two things genuinely differ between live and
sandbox, so only those two run here:

  1. Order placement and lifecycle - in analyzer mode these route to
     sandbox_service and the broker plugin is never called, so a sandbox pass
     proves nothing about the broker. Every order here is real.

  2. Holdings - the sandbox has no holdings most of the time, and its funds
     and positions are wiped whenever sandbox params are reset. Holdings can
     only be asserted against a real demat.

Everything else - market data, symbol services, options analytics, margin -
does not branch on analyzer mode at all (verified: quotes_service,
history_service, depth_service and margin_service contain no sandbox branch),
so running it live would repeat the sandbox run byte for byte. It lives in
qa_sandbox.py and is not duplicated here.

SAFETY. This places real orders for real money. Every order uses one share of
the cheapest liquid equity, or one lot of a near-zero-premium OTM40 option.
Resting orders are priced 20% away from LTP so they cannot fill. The run
maintains a ledger and squares off everything it opened. Pre-existing orders
and positions are recorded first and are never touched.

Usage:
    OPENALGO_API_KEY=... uv run python docs/audit/qa_audit/broker/qa_live.py
    QA_LIVE_CONFIRM=I-UNDERSTAND   required, no default
    QA_FNO=1                       opt in to F&O orders (default: equity only)
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qa_common import (  # noqa: E402
    IST,
    PASS,
    SKIP,
    WARN,
    Runner,
    Skip,
    Warn,
    active_broker,
    as_num,
    load_plugin_exchanges,
    need,
    need_2dp,
    need_keys,
    need_nonzero,
    now_ist,
    parse_ist,
    print_rollup,
    resolve_matrix,
    write_report,
)

API_KEY = os.getenv("OPENALGO_API_KEY", "")
HOST = os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000")
CONFIRM = os.getenv("QA_LIVE_CONFIRM", "")
DO_FNO = os.getenv("QA_FNO", "") == "1"
STRAT = "QA-LIVE"


# ==========================================================================
# pre-existing state - recorded so foreign rows are never touched (1.4)
# ==========================================================================
def snapshot(run: Runner) -> dict:
    ob = run.client.orderbook().get("data", {}) or {}
    pb = run.client.positionbook().get("data", []) or []
    snap = {
        "orders": {str(o["orderid"]) for o in (ob.get("orders") or [])},
        "positions": {(p["symbol"], p["exchange"], p["product"])
                      for p in pb if int(float(p.get("quantity", 0) or 0)) != 0},
    }
    print(f"  pre-existing: {len(snap['orders'])} orders, {len(snap['positions'])} open positions")
    if snap["orders"] or snap["positions"]:
        run.note_quirk("Pre-existing account state",
                       f"{len(snap['orders'])} orders / {len(snap['positions'])} positions "
                       f"present before the run; teardown leaves them alone")
    return snap


# ==========================================================================
# 7/8. real order placement
# ==========================================================================
def sec_orders(run: Runner) -> None:
    run.section("7. Order placement (LIVE - real money)")
    m = run.matrix
    if "EQ_CHEAP" not in m:
        run.blocked("OD-*", "EQ_CHEAP unresolved - refusing to place live orders",
                    endpoint="placeorder")
        return
    sym, ex = m["EQ_CHEAP"]
    ltp = as_num(run.ok(run.client.quotes(symbol=sym, exchange=ex), "q")["data"]["ltp"], "ltp")
    print(f"  instrument: {sym}@{ex} at {ltp}  (1 share per order)")

    def place(pt, action, product, price=0, trig=0, symbol=None, exchange=None, qty=1):
        s, e = symbol or sym, exchange or ex
        r = run.ok(run.client.placeorder(strategy=STRAT, symbol=s, exchange=e, action=action,
                                         price_type=pt, product=product, quantity=qty,
                                         price=price, trigger_price=trig), "placeorder")
        need(r.get("orderid"), "no orderid returned")
        run.track_order(r["orderid"], s, e, product)
        return r["orderid"]

    def far(action):
        """20% away - a resting order that cannot fill (safety rail 1.4)."""
        return round(ltp * (0.80 if action == "BUY" else 1.20), 2)

    # OD-03 / OD-04 / OD-05 - resting orders, no fill risk
    def limit_rests():
        oid = place("LIMIT", "BUY", "MIS", far("BUY"))
        time.sleep(2.0)
        st = run.ok(run.client.orderstatus(order_id=oid, strategy=STRAT), "status")["data"]
        need(st["order_status"] == "open",
             f"far LIMIT should rest as open, got {st['order_status']!r}")
        return oid

    run.check("OD-03", limit_rests, endpoint="placeorder", exchange=ex, symbol=sym,
              expected="far LIMIT rests as open")

    def sl_rests():
        p = far("BUY")
        oid = place("SL", "BUY", "MIS", p, round(p * 1.01, 2))
        time.sleep(2.0)
        st = run.ok(run.client.orderstatus(order_id=oid, strategy=STRAT), "status")["data"]
        need(st["order_status"] in ("trigger pending", "open"),
             f"SL fired on placement: {st['order_status']!r}")

    run.check("OD-04", sl_rests, endpoint="placeorder", exchange=ex, symbol=sym,
              expected="SL rests as trigger pending")

    def slm_rests():
        oid = place("SL-M", "BUY", "MIS", 0, round(ltp * 1.25, 2))
        time.sleep(2.0)
        st = run.ok(run.client.orderstatus(order_id=oid, strategy=STRAT), "status")["data"]
        need(st["order_status"] in ("trigger pending", "open"),
             f"SL-M fired on placement: {st['order_status']!r}")

    run.check("OD-05", slm_rests, endpoint="placeorder", exchange=ex, symbol=sym,
              expected="SL-M rests, does not fire")

    # OD-02 - the one intentional fill, 1 share, immediately squared off
    def market_fills():
        oid = place("MARKET", "BUY", "MIS")
        time.sleep(2.5)
        st = run.ok(run.client.orderstatus(order_id=oid, strategy=STRAT), "status")["data"]
        need(st["order_status"] == "complete",
             f"MARKET order did not fill: {st['order_status']!r}")
        need_nonzero(st.get("average_price"), "filled average_price")
        run.client.placeorder(strategy=STRAT, symbol=sym, exchange=ex, action="SELL",
                              price_type="MARKET", product="MIS", quantity=1)
        time.sleep(2.0)

    run.check("OD-02", market_fills, endpoint="placeorder+orderstatus", exchange=ex, symbol=sym,
              expected="MARKET fills at a real price, then squared off")

    # OD-07/08 - products on equity
    for product in ("MIS", "CNC"):
        run.check(f"OD-07.{product}", lambda p=product: place("LIMIT", "BUY", p, far("BUY")),
                  endpoint="placeorder", exchange=ex, symbol=sym,
                  expected=f"{product} accepted on {ex}")

    run.check("OD-10", lambda: run.expect_error(
        run.client.placeorder(strategy=STRAT, symbol=sym, exchange=ex, action="BUY",
                              price_type="LIMIT", product="NRML", quantity=1,
                              price=far("BUY")), "NRML on equity"),
        endpoint="placeorder", expected="product/exchange mismatch refused")

    if "EQ_SPECIAL" in m:
        s2, e2 = m["EQ_SPECIAL"]
        l2 = as_num(run.ok(run.client.quotes(symbol=s2, exchange=e2), "q")["data"]["ltp"], "ltp")
        run.check("OD-12", lambda: place("LIMIT", "BUY", "MIS", round(l2 * 0.80, 2),
                                         symbol=s2, exchange=e2),
                  endpoint="placeorder", symbol=s2, expected="special character intact")

    # F&O - opt-in, OTM40 near-zero premium
    if not DO_FNO:
        run.record("OD-11", SKIP, "QA_FNO=1 not set - equity-only live run", endpoint="placeorder")
    else:
        for exch in [e for e in run.env["exchanges"] if e in ("NFO", "BFO", "MCX", "CDS", "BCD", "NCO")]:
            slot = f"OPT_CHEAP_{exch}" if f"OPT_CHEAP_{exch}" in m else f"FUT_{exch}"
            if slot not in m:
                run.record(f"OD-11.{exch}", SKIP, f"{slot} unresolved", endpoint="placeorder")
                continue
            s3, e3 = m[slot]
            lot = _lot(run, s3, e3)
            q3 = as_num(run.ok(run.client.quotes(symbol=s3, exchange=e3), "q")["data"]["ltp"], "ltp")
            run.check(f"OD-11.{exch}", lambda s3=s3, e3=e3, lot=lot, q3=q3: place(
                "LIMIT", "BUY", "NRML", round(q3 * 0.50, 1), symbol=s3, exchange=e3, qty=lot),
                endpoint="placeorder", exchange=exch, symbol=s3,
                expected="claimed exchange accepts a real order")

    # ---- lifecycle on a resting order ----
    run.section("8. Order lifecycle (LIVE)")

    def lifecycle():
        p = far("BUY")
        oid = place("LIMIT", "BUY", "MIS", p)
        time.sleep(2.0)
        newp = round(p * 0.99, 2)
        run.ok(run.client.modifyorder(order_id=oid, strategy=STRAT, symbol=sym, exchange=ex,
                                      action="BUY", price_type="LIMIT", product="MIS",
                                      quantity=1, price=newp), "modify")
        time.sleep(2.0)
        st = run.ok(run.client.orderstatus(order_id=oid, strategy=STRAT), "status")["data"]
        need(abs(as_num(st["price"], "price") - newp) < 0.05,
             f"modify not reflected at broker: price {st['price']} != {newp}")
        run.ok(run.client.cancelorder(order_id=oid, strategy=STRAT), "cancel")
        time.sleep(2.0)
        st = run.ok(run.client.orderstatus(order_id=oid, strategy=STRAT), "status")["data"]
        need(st["order_status"] == "cancelled", f"after cancel: {st['order_status']!r}")

    run.check("LC-01", lifecycle, endpoint="modify+cancel+status", exchange=ex, symbol=sym,
              expected="place -> modify -> cancel at the broker")

    run.check("LC-08", lambda: run.expect_error(
        run.client.cancelorder(order_id="NOTANORDER123", strategy=STRAT), "unknown orderid"),
        endpoint="cancelorder", expected="clean error")

    def orderbook_live():
        d = run.ok(run.client.orderbook(), "orderbook")["data"]
        ours = [o for o in (d.get("orders") or [])
                if str(o["orderid"]) in {x["orderid"] for x in run.order_ledger}]
        need(ours, "none of this run's orders appear in the broker orderbook")
        for o in ours:
            need(o["order_status"] == o["order_status"].lower(),
                 f"order_status {o['order_status']!r} not lowercase")
            ts = parse_ist(o["timestamp"], "orderbook timestamp").astimezone(IST)
            need(ts.date() >= date.today() - timedelta(days=1),
                 f"{o['orderid']}: timestamp {o['timestamp']} not in the current session (IST)")
            need_2dp(o["price"], f"{o['orderid']}.price")
            need(o["symbol"] and not o["symbol"].endswith("-EQ"),
                 f"{o['orderid']}: broker tradingsymbol {o['symbol']!r} leaked into the book")

    run.check("OB-03", orderbook_live, endpoint="orderbook",
              expected="OpenAlgo symbols, lowercase status, IST timestamps")

    def tradebook_live():
        d = run.ok(run.client.tradebook(), "tradebook")["data"]
        if not d:
            raise Warn("no trades today - OD-02 fill not visible in the tradebook")
        for t in d[:20]:
            need_keys(t, ["orderid", "symbol", "exchange", "action", "quantity",
                          "average_price", "timestamp", "trade_value"], "trade row")
            q = as_num(t["quantity"], "quantity")
            ap = need_nonzero(t["average_price"], "average_price")
            need(q != 0, f"{t['orderid']}: executed trade reports quantity 0")
            tv = as_num(t["trade_value"], "trade_value")
            need(abs(tv - q * ap) < max(0.05, abs(tv) * 0.01),
                 f"{t['orderid']}: trade_value {tv} != {q} x {ap}")

    run.check("TB-02", tradebook_live, endpoint="tradebook",
              expected="real executed price, value reconciles")

    def positionbook_live():
        d = run.ok(run.client.positionbook(), "positionbook")["data"]
        if not d:
            raise Warn("positionbook empty")
        for p in d[:30]:
            need_keys(p, ["symbol", "exchange", "product", "quantity",
                          "average_price", "ltp", "pnl"], "position row")
            q = as_num(p["quantity"], "quantity")
            ap = need_2dp(p["average_price"], f"{p['symbol']}.average_price")
            lt = need_2dp(p["ltp"], f"{p['symbol']}.ltp")
            pnl = need_2dp(p["pnl"], f"{p['symbol']}.pnl")
            if q != 0 and not p.get("average_price_basis"):
                need(ap != 0, f"{p['symbol']}: open position with average_price 0")
                need(lt != 0, f"{p['symbol']}: ltp 0")
                exp = (lt - ap) * q
                need(abs(pnl - exp) <= max(1.0, abs(exp) * 0.02),
                     f"{p['symbol']}: pnl {pnl} vs (ltp-avg)*qty {exp:.2f}")
            if p.get("average_price_basis"):
                run.note_quirk("average_price_basis set",
                               f"{p['symbol']}: {p['average_price_basis']}")

    run.check("PB-02", positionbook_live, endpoint="positionbook",
              expected="entry price real, pnl arithmetic holds")

    def funds_live():
        d = run.ok(run.client.funds(), "funds")["data"]
        need_keys(d, ["availablecash", "collateral", "m2mrealized",
                      "m2munrealized", "utiliseddebits"], "funds")
        for k in d:
            as_num(d[k], f"funds.{k}")   # negative is legitimate (FN-03)

    run.check("FN-01", funds_live, endpoint="funds", expected="five fields, numeric")


# ==========================================================================
# 9.4 holdings - the reason this script exists alongside the sandbox one
# ==========================================================================
def sec_holdings(run: Runner) -> None:
    run.section("9.4 Holdings (LIVE only)")

    resp = run.ok(run.client.holdings(), "holdings")
    d = resp["data"]
    need_keys(d, ["holdings", "statistics"], "holdings")
    rows, stats = d["holdings"], d["statistics"]

    if not rows:
        run.record("HD-01", SKIP, "no holdings in this demat - nothing to assert",
                   endpoint="holdings")
        run.record("HD-02", SKIP, "no holdings in this demat", endpoint="holdings")
        run.record("HD-03", SKIP, "no holdings in this demat", endpoint="holdings")
        run.record("HD-04", SKIP, "no holdings in this demat", endpoint="holdings")
    else:
        def no_degenerate():
            need(any(as_num(h.get("quantity", 0), "quantity") != 0 for h in rows),
                 "every holding reports quantity 0")
            need(any(as_num(h.get("pnl", 0), "pnl") != 0 for h in rows),
                 "every holding reports pnl 0 - field not populated")

        run.check("HD-01", no_degenerate, endpoint="holdings",
                  expected="no field degenerate across the book")

        def avg_price():
            missing = [h["symbol"] for h in rows if "average_price" not in h]
            need(not missing,
                 f"average_price absent on {missing[:5]} - the mappers emit it and the UI "
                 f"depends on it, even though the API doc table omits it")
            for h in rows:
                need_nonzero(h["average_price"], f"{h['symbol']}.average_price")

        run.check("HD-02", avg_price, endpoint="holdings",
                  expected="average_price present and non-zero")

        def ltp_matches():
            missing = [h["symbol"] for h in rows if "ltp" not in h]
            need(not missing, f"ltp absent on {missing[:5]}")
            h = rows[0]
            need_nonzero(h["ltp"], f"{h['symbol']}.ltp")
            q = run.ok(run.client.quotes(symbol=h["symbol"], exchange=h["exchange"]),
                       "quotes")["data"]
            a, b = as_num(h["ltp"], "holding ltp"), as_num(q["ltp"], "quote ltp")
            need(abs(a - b) / max(b, 1e-9) < 0.02,
                 f"{h['symbol']}: holdings ltp {a} vs quotes ltp {b}")

        run.check("HD-03", ltp_matches, endpoint="holdings+quotes",
                  expected="ltp non-zero and matches /quotes")

        def pnlpercent():
            flat = 0
            for h in rows:
                ap = as_num(h["average_price"], "average_price")
                lt = as_num(h["ltp"], "ltp")
                pp = need_2dp(h["pnlpercent"], f"{h['symbol']}.pnlpercent")
                if ap:
                    exp = (lt - ap) / ap * 100
                    need(abs(pp - exp) <= max(0.5, abs(exp) * 0.05),
                         f"{h['symbol']}: pnlpercent {pp} vs computed {exp:.2f}")
                if abs(pp + 100) < 0.01:
                    flat += 1
            need(flat != len(rows),
                 "every holding reports -100% - ltp is missing and being treated as 0")

        run.check("HD-04", pnlpercent, endpoint="holdings",
                  expected="pnlpercent = (ltp-avg)/avg*100")

        def product_cnc():
            bad = [h["symbol"] for h in rows if h.get("product") != "CNC"]
            need(not bad, f"non-CNC product on holdings: {bad[:5]}")

        run.check("HD-05", product_cnc, endpoint="holdings", expected="product == CNC")

        def symbols_openalgo():
            with run.db() as c:
                for h in rows[:20]:
                    n = c.execute("select count(*) from symtoken where symbol=? and exchange=?",
                                  (h["symbol"], h["exchange"])).fetchone()[0]
                    need(n > 0, f"holdings symbol {h['symbol']}@{h['exchange']} is not an "
                                f"OpenAlgo symbol - broker tradingsymbol leaked")

        run.check("HD-08", symbols_openalgo, endpoint="holdings",
                  expected="OpenAlgo symbols, not broker tradingsymbols")

    def statistics():
        need_keys(stats, ["totalholdingvalue", "totalinvvalue", "totalprofitandloss",
                          "totalpnlpercentage"], "holdings statistics")
        for k in stats:
            as_num(stats[k], f"statistics.{k}")
        if rows:
            inv = as_num(stats["totalinvvalue"], "totalinvvalue")
            pnl = as_num(stats["totalprofitandloss"], "totalprofitandloss")
            hold = as_num(stats["totalholdingvalue"], "totalholdingvalue")
            if inv:
                need(abs((hold - inv) - pnl) <= max(5.0, abs(pnl) * 0.05),
                     f"statistics inconsistent: holding {hold} - inv {inv} != pnl {pnl}")

    run.check("HD-06", statistics, endpoint="holdings",
              expected="four statistics present and internally consistent")

    def empty_is_success():
        need(resp.get("status") == "success",
             "empty holdings must be a clean success, not an error")

    run.check("HD-07", empty_is_success, endpoint="holdings",
              expected="empty book is success with empty array")


# ==========================================================================
def _lot(run: Runner, sym: str, ex: str) -> int:
    with run.db() as c:
        row = c.execute("select lotsize from symtoken where symbol=? and exchange=?",
                        (sym, ex)).fetchone()
    return int(row[0]) if row and row[0] else 1


def teardown(run: Runner, snap: dict) -> None:
    """Cancel and square off only what this run created (safety rail 1.4)."""
    run.section("Teardown (this run's orders only)")
    ours = [o for o in run.order_ledger if o["orderid"] not in snap["orders"]]
    cancelled, failed = 0, []
    for o in ours:
        try:
            r = run.client.cancelorder(order_id=o["orderid"], strategy=STRAT)
            if r.get("status") == "success":
                cancelled += 1
        except Exception as e:
            failed.append(f"{o['orderid']}: {e}")
    run.record("TD-01", PASS if not failed else WARN,
               f"cancelled {cancelled}/{len(ours)} of this run's orders"
               + (f"; {len(failed)} could not be cancelled (likely already filled/terminal)"
                  if failed else ""),
               endpoint="cancelorder")

    time.sleep(2.0)
    pb = run.client.positionbook().get("data", []) or []
    new_open = [p for p in pb
                if int(float(p.get("quantity", 0) or 0)) != 0
                and (p["symbol"], p["exchange"], p["product"]) not in snap["positions"]]
    squared = 0
    for p in new_open:
        q = int(float(p["quantity"]))
        try:
            run.client.placeorder(strategy=STRAT, symbol=p["symbol"], exchange=p["exchange"],
                                  action="SELL" if q > 0 else "BUY", price_type="MARKET",
                                  product=p["product"], quantity=abs(q))
            squared += 1
            time.sleep(0.5)
        except Exception as e:
            run.record("TD-02.err", "FAIL", f"could not square off {p['symbol']}: {e}",
                       endpoint="placeorder")
    run.record("TD-02", PASS, f"squared off {squared} position(s) opened by this run; "
                              f"{len(snap['positions'])} pre-existing position(s) left untouched",
               endpoint="closeposition")

    time.sleep(2.5)
    pb = run.client.positionbook().get("data", []) or []
    still = [p for p in pb
             if int(float(p.get("quantity", 0) or 0)) != 0
             and (p["symbol"], p["exchange"], p["product"]) not in snap["positions"]]
    run.record("TD-03", PASS if not still else "FAIL",
               "account flat for this run's instruments" if not still
               else f"STILL OPEN: {[(p['symbol'], p['quantity']) for p in still]} - square off manually",
               endpoint="positionbook")


def main() -> int:
    if not API_KEY:
        print("Set OPENALGO_API_KEY (never hardcode it - gap analysis defect A-01)")
        return 2
    if CONFIRM != "I-UNDERSTAND":
        print(__doc__)
        print("\nThis run places REAL orders. To proceed:")
        print("  QA_LIVE_CONFIRM=I-UNDERSTAND uv run python docs/audit/qa_audit/broker/qa_live.py")
        return 2
    try:
        from openalgo import api as OAClient
    except ImportError:
        print("openalgo SDK missing - uv pip install openalgo")
        return 2

    client = OAClient(api_key=API_KEY, host=HOST)
    run = Runner(client=client, mode="LIVE", host=HOST)
    broker = active_broker()
    run.env = {"broker": broker, "started": now_ist(),
               "exchanges": load_plugin_exchanges(broker)}
    print(f"Broker: {broker or '(unknown)'}   Host: {HOST}   Mode: LIVE")
    print(f"Exchanges claimed: {run.env['exchanges']}")

    run.section("1. Preconditions")
    run.check("PRE-01", lambda: need(bool(broker), "no non-revoked auth row"),
              endpoint="auth", expected="one active broker")

    def must_be_live():
        st = run.client.analyzerstatus()
        blob = json.dumps(st).lower()
        if '"analyze_mode": true' in blob or '"mode": "analyze"' in blob:
            run.client.analyzertoggle(mode=False)
            time.sleep(1.0)
            st = run.client.analyzerstatus()
            blob = json.dumps(st).lower()
        need('"analyze_mode": true' not in blob and '"mode": "analyze"' not in blob,
             "still in analyzer mode - a LIVE run must not route to the sandbox")

    run.check("PRE-06", must_be_live, endpoint="analyzer/status", expected="live mode confirmed")

    snap = snapshot(run)
    run.matrix = resolve_matrix(run, run.env["exchanges"])
    unres = run.matrix.get("_unresolved", [])
    print(f"\nSymbol matrix: {len([k for k in run.matrix if not k.startswith('_')])} slots, "
          f"{len(unres)} unresolved")
    for u in unres:
        print(f"  unresolved: {u}")

    try:
        sec_orders(run)
        sec_holdings(run)
    except Exception as e:
        run.record("RUN", "ERROR", f"aborted: {type(e).__name__}: {e}")
    finally:
        try:
            teardown(run, snap)
        except Exception as e:
            run.record("TD-00", "FAIL", f"TEARDOWN FAILED - CHECK THE ACCOUNT MANUALLY: {e}")

    # Persist this run's response shapes so the sandbox run can assert
    # cross-mode parity (SB-02/03/04) on its next pass.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from qa_sandbox import SHAPES_FILE, capture_shapes
        SHAPES_FILE.write_text(json.dumps(
            {"mode": run.mode, "broker": run.env.get("broker"), "when": now_ist(),
             "shapes": capture_shapes(run),
             "statuses_seen": sorted({o.get("order_status") for o in
                                     ((run.client.orderbook() or {}).get("data") or {})
                                     .get("orders") or [] if o.get("order_status")})},
            indent=1), encoding="utf-8")
        print(f"Recorded LIVE response shapes for cross-mode parity: {SHAPES_FILE.name}")
    except Exception as e:
        print(f"Could not record LIVE shapes for parity: {e}")

    ok = print_rollup(run)
    out = Path(__file__).parent / f"qa_live_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    print(f"\nReport: {write_report(run, out)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
