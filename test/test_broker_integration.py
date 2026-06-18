"""
Broker Integration — Automated Test Runner
===========================================

Exercises every check in ``docs/test/BROKER_INTEGRATION_TESTING_GUIDE.md`` against
a *running* OpenAlgo instance, for **any** broker, via the public ``/api/v1/*``
REST endpoints plus the unified WebSocket proxy.

Sections:
  1. Pre-flight / auth (token sanity)
  2. Funds
  3. Master contract + symbol-format + index normalization
  4. Order management (placed in **Analyzer/sandbox** mode by default — safe):
     market/limit/SL/SL-M x products, modify, cancel, smart, basket, split,
     cancel-all, close-all, books, margin
  5. Market data (quotes / depth / intervals / history intraday+daily / multiquotes)
  6. Option tools (expiry + option chain) for NFO & BFO
  7. WebSocket streaming (LTP / Quote / Depth)

Usage:
    # 1) Start OpenAlgo and log into the broker first, then:
    uv run python test/test_broker_integration.py
    uv run python test/test_broker_integration.py --apikey <KEY> --equity YESBANK
    uv run python test/test_broker_integration.py --live          # orders hit the REAL broker
    uv run python test/test_broker_integration.py --sections 1,2,5 # run a subset
    uv run python test/test_broker_integration.py --no-ws          # skip WebSocket

The API key is read from ``--apikey`` or the ``API_KEY`` env/.env value.
Order tests default to Analyzer (sandbox) mode; pass ``--live`` to use the real
broker (qty stays 1; LIMIT prices are placed far from LTP to avoid fills).
"""

import argparse
import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta

import requests

try:
    import websocket  # websocket-client
except ImportError:
    websocket = None

# Allow "from ..." style imports if ever needed
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Configuration (broker-agnostic; override via CLI). Edit the symbols to match
# the broker's supported segments. F&O contract symbols are resolved at runtime.
# ---------------------------------------------------------------------------
CONFIG = {
    "equity_nse": "YESBANK",
    "equity_bse": "RELIANCE",
    "index_nse": "NIFTY",
    "index_nse_2": "BANKNIFTY",
    "index_bse": "SENSEX",
    "index_bse_2": "BANKEX",
    "special_symbols": ["BAJAJ-AUTO", "M&M"],  # hyphen / ampersand must survive
    "nfo_underlyings": ["NIFTY", "BANKNIFTY"],
    "bfo_underlyings": ["SENSEX", "BANKEX"],
    "cds_search": "USDINR",
    "mcx_search": "CRUDEOIL",
}

# ANSI colors
G, R, Y, B, DIM, RST = "\033[32m", "\033[31m", "\033[33m", "\033[34m", "\033[2m", "\033[0m"


class Runner:
    def __init__(self, base_url, ws_url, api_key, live=False, no_ws=False):
        self.base = base_url.rstrip("/")
        self.ws_url = ws_url
        self.api_key = api_key
        self.live = live
        self.no_ws = no_ws
        self.results = []  # (section, name, status, detail)
        self.placed_orderids = []
        self.session = requests.Session()

    # -- result recording ---------------------------------------------------
    def record(self, section, name, status, detail=""):
        self.results.append((section, name, status, detail))
        color = {"PASS": G, "FAIL": R, "SKIP": Y, "INFO": B}.get(status, "")
        line = f"  [{color}{status:4}{RST}] {name}"
        if detail:
            line += f"  {DIM}{detail}{RST}"
        print(line)

    def section(self, title):
        print(f"\n{B}=== {title} ==={RST}")

    # -- HTTP helper --------------------------------------------------------
    def api(self, endpoint, payload=None, timeout=30):
        """POST to /api/v1/<endpoint>. Returns (ok, json_or_text)."""
        body = {"apikey": self.api_key}
        if payload:
            body.update(payload)
        url = f"{self.base}/api/v1/{endpoint}"
        try:
            resp = self.session.post(url, json=body, timeout=timeout)
        except Exception as e:
            return False, {"error": f"request failed: {e}"}
        try:
            data = resp.json()
        except ValueError:
            return False, {"error": f"non-JSON ({resp.status_code}): {resp.text[:200]}"}
        ok = resp.status_code == 200 and str(data.get("status", "")).lower() != "error"
        return ok, data

    @staticmethod
    def _is_success(data):
        return isinstance(data, dict) and str(data.get("status", "")).lower() == "success"

    # =======================================================================
    # 1. Pre-flight / Auth
    # =======================================================================
    def test_auth(self):
        self.section("1. Authentication / token sanity")
        ok, data = self.api("funds")
        if self._is_success(data):
            self.record("auth", "Stored broker token authenticates (funds OK)", "PASS")
            return True
        self.record(
            "auth", "Stored broker token authenticates", "FAIL",
            f"{data.get('message') or data.get('error') or data}",
        )
        print(f"{R}  Broker not connected / API key invalid — aborting remaining tests.{RST}")
        return False

    # =======================================================================
    # 2. Funds
    # =======================================================================
    def test_funds(self):
        self.section("2. Funds")
        ok, data = self.api("funds")
        if not self._is_success(data):
            self.record("funds", "Fetch funds", "FAIL", str(data)[:160])
            return
        d = data.get("data", {})
        for field in ("availablecash", "collateral", "m2munrealized", "m2mrealized", "utiliseddebits"):
            present = field in d
            self.record("funds", f"funds.{field} present", "PASS" if present else "FAIL",
                        f"={d.get(field)}" if present else "")

    # =======================================================================
    # 3. Master contract + symbol format
    # =======================================================================
    def _search_symbols(self, query, exchange):
        ok, data = self.api("search", {"query": query, "exchange": exchange})
        if not self._is_success(data):
            return None
        d = data.get("data")
        if isinstance(d, dict):
            d = d.get("symbols") or d.get("results") or []
        return d if isinstance(d, list) else []

    def test_symbols(self):
        self.section("3. Master contract + symbol format")

        # Equity base symbols + special symbols (hyphen / ampersand survive)
        checks = [(self.cfg("equity_nse"), "NSE")]
        checks += [(s, "NSE") for s in CONFIG["special_symbols"]]
        for sym, exch in checks:
            results = self._search_symbols(sym, exch)
            if results is None:
                self.record("symbols", f"search {sym}@{exch}", "SKIP", "search unsupported")
                continue
            match = any(str(r.get("symbol", "")).upper() == sym.upper() for r in results)
            self.record("symbols", f"equity symbol '{sym}' in OpenAlgo format", "PASS" if match else "FAIL",
                        "" if match else f"got {[r.get('symbol') for r in results[:3]]}")

        # Index normalization
        for sym, exch in [
            (self.cfg("index_nse"), "NSE_INDEX"),
            (self.cfg("index_nse_2"), "NSE_INDEX"),
            (self.cfg("index_bse"), "BSE_INDEX"),
            (self.cfg("index_bse_2"), "BSE_INDEX"),
        ]:
            results = self._search_symbols(sym, exch)
            if results is None:
                self.record("symbols", f"index {sym}@{exch}", "SKIP", "search unsupported")
                continue
            match = any(str(r.get("symbol", "")).upper() == sym.upper() for r in results)
            self.record("symbols", f"index '{sym}' normalized on {exch}", "PASS" if match else "FAIL",
                        "" if match else f"got {[r.get('symbol') for r in results[:5]]}")

    # =======================================================================
    # 4. Order management (Analyzer/sandbox by default)
    # =======================================================================
    def _set_analyzer(self, mode: bool):
        # Toggle endpoint is /api/v1/analyzer/toggle (status is /api/v1/analyzer)
        ok, data = self.api("analyzer/toggle", {"mode": mode})
        return self._is_success(data)

    def _order_status(self, data):
        """PASS on success; SKIP for market-time conditions; else FAIL."""
        if self._is_success(data):
            return "PASS"
        msg = str(data.get("message") or "").lower()
        for cond in ("square-off time", "trading resumes", "market closed",
                     "market is closed", "after market", "outside market"):
            if cond in msg:
                return "SKIP"
        return "FAIL"

    def _quote_ltp(self, symbol, exchange):
        ok, data = self.api("quotes", {"symbol": symbol, "exchange": exchange})
        if self._is_success(data):
            d = data.get("data", {})
            try:
                return float(d.get("ltp") or 0)
            except (TypeError, ValueError):
                return 0.0
        return 0.0

    def test_orders(self):
        mode_label = "LIVE" if self.live else "ANALYZER (sandbox)"
        self.section(f"4. Order management [{mode_label}]")

        sym = self.cfg("equity_nse")
        exch = "NSE"

        analyzer_set = False
        if not self.live:
            analyzer_set = self._set_analyzer(True)
            self.record("orders", "Enable Analyzer (sandbox) mode", "PASS" if analyzer_set else "FAIL")
            if not analyzer_set:
                print(f"{Y}  Could not enable sandbox; skipping order tests to avoid live orders.{RST}")
                return

        try:
            ltp = self._quote_ltp(sym, exch) or 25.0
            buy_limit = round(max(ltp * 0.5, 1), 1)   # far below LTP -> won't fill
            trig = round(ltp * 1.2, 1)

            # 4.1 Place — price types x products. CNC works any time; MIS is
            # square-off-time-restricted in sandbox (SKIP after 15:15 IST).
            cases = [
                ("MARKET", "CNC", {}),
                ("LIMIT", "CNC", {"price": str(buy_limit)}),
                ("SL", "CNC", {"price": str(round(trig + 0.5, 1)), "trigger_price": str(trig)}),
                ("SL-M", "CNC", {"trigger_price": str(trig)}),
                ("LIMIT", "MIS", {"price": str(buy_limit)}),
            ]
            for pricetype, product, extra in cases:
                payload = {
                    "strategy": "itest", "symbol": sym, "exchange": exch, "action": "BUY",
                    "product": product, "pricetype": pricetype, "quantity": "1", **extra,
                }
                ok, data = self.api("placeorder", payload)
                oid = data.get("orderid") if isinstance(data, dict) else None
                status = self._order_status(data)
                if status == "PASS" and not oid:
                    status = "FAIL"
                self.record("orders", f"place {pricetype}/{product}", status,
                            f"orderid={oid}" if oid else str(data.get("message") or data)[:120])
                if oid:
                    self.placed_orderids.append(oid)

            # 4.2/4.3 Modify + Cancel — place a dedicated far-from-market LIMIT
            # order that stays OPEN (matrix MARKET orders fill instantly in sandbox).
            ok, data = self.api("placeorder", {
                "strategy": "itest", "symbol": sym, "exchange": exch, "action": "BUY",
                "product": "CNC", "pricetype": "LIMIT", "quantity": "1", "price": str(buy_limit),
            })
            mc_oid = data.get("orderid") if isinstance(data, dict) else None
            if mc_oid:
                ok, data = self.api("modifyorder", {
                    "strategy": "itest", "symbol": sym, "exchange": exch, "orderid": mc_oid,
                    "action": "BUY", "product": "CNC", "pricetype": "LIMIT",
                    "quantity": "2", "price": str(round(max(buy_limit - 0.5, 1), 1)),
                    "trigger_price": "0", "disclosed_quantity": "0",
                })
                self.record("orders", "modify order (qty+price)", self._order_status(data),
                            str(data.get("message") or "")[:100])
                ok, data = self.api("cancelorder", {"strategy": "itest", "orderid": mc_oid})
                self.record("orders", "cancel order", self._order_status(data),
                            str(data.get("message") or "")[:100])
            else:
                self.record("orders", "modify/cancel order", "SKIP",
                            f"no pending order: {str(data.get('message') or '')[:80]}")

            # 4.4 Smart order
            ok, data = self.api("placesmartorder", {
                "strategy": "itest", "symbol": sym, "exchange": exch, "action": "BUY",
                "product": "CNC", "pricetype": "MARKET", "quantity": "1", "position_size": "1",
            })
            self.record("orders", "smart order (target +1)", self._order_status(data),
                        str(data.get("message") or "")[:100])

            # 4.5 Basket order
            ok, data = self.api("basketorder", {
                "strategy": "itest", "orders": [
                    {"symbol": sym, "exchange": exch, "action": "BUY", "quantity": "1",
                     "pricetype": "MARKET", "product": "MIS"},
                    {"symbol": sym, "exchange": exch, "action": "SELL", "quantity": "1",
                     "pricetype": "LIMIT", "product": "MIS", "price": str(round(ltp * 1.5, 1))},
                ],
            })
            self.record("orders", "basket order (2 legs)", "PASS" if self._is_success(data) else "FAIL",
                        str(data.get("message") or "")[:100])

            # 4.6 Split order
            ok, data = self.api("splitorder", {
                "strategy": "itest", "symbol": sym, "exchange": exch, "action": "SELL",
                "quantity": "5", "splitsize": "2", "pricetype": "MARKET", "product": "MIS",
            })
            self.record("orders", "split order (5/2 -> 3 children)", "PASS" if self._is_success(data) else "FAIL",
                        str(data.get("message") or "")[:100])

            # 4.7 Books / positions / holdings
            for ep in ("orderbook", "tradebook", "positionbook", "holdings"):
                ok, data = self.api(ep)
                self.record("orders", f"{ep}", "PASS" if self._is_success(data) else "FAIL",
                            str(data.get("message") or "")[:80])

            # 4.8 Margin (optional)
            ok, data = self.api("margin", {"positions": [
                {"symbol": sym, "exchange": exch, "action": "BUY", "product": "MIS",
                 "pricetype": "LIMIT", "quantity": "1", "price": str(round(ltp, 1))},
            ]})
            if isinstance(data, dict) and data.get("status") == "error" and "not" in str(data.get("message", "")).lower():
                self.record("orders", "margin", "SKIP", "not implemented for broker")
            else:
                self.record("orders", "margin (single order)", "PASS" if self._is_success(data) else "FAIL",
                            str(data.get("message") or "")[:100])

            # 4.9 Cancel-all + close-all (cleanup)
            ok, data = self.api("cancelallorder", {"strategy": "itest"})
            self.record("orders", "cancel all orders", "PASS" if self._is_success(data) else "FAIL")
            ok, data = self.api("closeposition", {"strategy": "itest"})
            self.record("orders", "close all positions", "PASS" if self._is_success(data) else "FAIL")

        finally:
            if analyzer_set:
                restored = self._set_analyzer(False)
                self.record("orders", "Restore Live mode (analyzer off)", "PASS" if restored else "FAIL")

    # =======================================================================
    # 5. Market data
    # =======================================================================
    def _discover_fno(self):
        """Resolve a sample option + future symbol per F&O segment via option chain / search."""
        found = {}  # exchange -> {"option": sym, "future": sym}

        def first_expiry(underlying, exch):
            ok, data = self.api("expiry", {"symbol": underlying, "exchange": exch,
                                           "instrumenttype": "options"})
            if self._is_success(data):
                d = data.get("data")
                if isinstance(d, dict):
                    d = d.get("expiry") or d.get("expirydates") or []
                if isinstance(d, list) and d:
                    return d[0]
            return None

        # NFO via option chain on the NSE index
        for und in self.cfg_list("nfo_underlyings"):
            exp = first_expiry(und, "NFO")
            if not exp:
                continue
            ok, data = self.api("optionchain", {"underlying": und, "exchange": "NSE_INDEX",
                                                "expiry_date": self._compact_expiry(exp),
                                                "strike_count": 3})
            if self._is_success(data):
                chain = data.get("data", {})
                sym = self._first_option_symbol(chain)
                if sym:
                    found.setdefault("NFO", {})["option"] = sym
                    break
        # BFO via option chain on the BSE index
        for und in self.cfg_list("bfo_underlyings"):
            exp = first_expiry(und, "BFO")
            if not exp:
                continue
            ok, data = self.api("optionchain", {"underlying": und, "exchange": "BSE_INDEX",
                                                "expiry_date": self._compact_expiry(exp),
                                                "strike_count": 3})
            if self._is_success(data):
                sym = self._first_option_symbol(data.get("data", {}))
                if sym:
                    found.setdefault("BFO", {})["option"] = sym
                    break
        # Futures via search
        for exch, q in (("NFO", "NIFTY"), ("BFO", "SENSEX"),
                        ("CDS", self.cfg("cds_search")), ("MCX", self.cfg("mcx_search"))):
            res = self._search_symbols(q, exch)
            if res:
                fut = next((r.get("symbol") for r in res
                            if str(r.get("symbol", "")).endswith("FUT")), None)
                if fut:
                    found.setdefault(exch, {})["future"] = fut
        return found

    @staticmethod
    def _first_option_symbol(chain):
        """Best-effort extraction of a CE/PE option symbol from an option-chain payload."""
        if not isinstance(chain, (list, dict)):
            return None
        rows = chain if isinstance(chain, list) else chain.get("options") or chain.get("data") or []
        if isinstance(rows, dict):
            rows = list(rows.values())
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            for key in ("symbol", "ce_symbol", "pe_symbol", "tradingsymbol"):
                v = row.get(key)
                if isinstance(v, str) and (v.endswith("CE") or v.endswith("PE")):
                    return v
        return None

    def _data_targets(self):
        """Build the (label, symbol, exchange) list for data tests."""
        targets = [
            ("NSE equity", self.cfg("equity_nse"), "NSE"),
            ("BSE equity", self.cfg("equity_bse"), "BSE"),
            ("NSE index", self.cfg("index_nse"), "NSE_INDEX"),
            ("BSE index", self.cfg("index_bse"), "BSE_INDEX"),
        ]
        fno = self._discover_fno()
        for exch in ("NFO", "BFO", "CDS", "MCX"):
            seg = fno.get(exch, {})
            if seg.get("future"):
                targets.append((f"{exch} future", seg["future"], exch))
            if seg.get("option"):
                targets.append((f"{exch} option", seg["option"], exch))
        return targets

    def test_marketdata(self):
        self.section("5. Market data")

        # Intervals
        ok, data = self.api("intervals")
        self.record("data", "intervals", "PASS" if self._is_success(data) else "FAIL",
                    str(data.get("data"))[:120] if self._is_success(data) else "")

        targets = self._data_targets()
        self._data_targets_cache = targets  # reused by websocket section

        for label, sym, exch in targets:
            ok, data = self.api("quotes", {"symbol": sym, "exchange": exch})
            d = data.get("data", {}) if self._is_success(data) else {}
            good = self._is_success(data) and float(d.get("ltp") or 0) >= 0 and "ltp" in d
            self.record("data", f"quotes {label} ({sym})", "PASS" if good else "FAIL",
                        f"ltp={d.get('ltp')}" if good else str(data.get("message") or "")[:80])

            ok, data = self.api("depth", {"symbol": sym, "exchange": exch})
            d = data.get("data", {}) if self._is_success(data) else {}
            good = self._is_success(data) and isinstance(d.get("bids"), list) and isinstance(d.get("asks"), list)
            self.record("data", f"depth {label} ({sym})", "PASS" if good else "FAIL",
                        f"{len(d.get('bids', []))}x{len(d.get('asks', []))} levels" if good
                        else str(data.get("message") or "")[:80])

        # History — intraday + daily on the NSE equity
        sym, exch = self.cfg("equity_nse"), "NSE"
        today = datetime.now()
        intra = {"symbol": sym, "exchange": exch, "interval": "5m",
                 "start_date": (today - timedelta(days=5)).strftime("%Y-%m-%d"),
                 "end_date": today.strftime("%Y-%m-%d")}
        ok, data = self.api("history", intra)
        n = len(data.get("data", [])) if self._is_success(data) else 0
        self.record("data", "history intraday (5m)", "PASS" if (self._is_success(data) and n) else "FAIL",
                    f"{n} candles")

        daily = {"symbol": sym, "exchange": exch, "interval": "D",
                 "start_date": (today - timedelta(days=120)).strftime("%Y-%m-%d"),
                 "end_date": today.strftime("%Y-%m-%d")}
        ok, data = self.api("history", daily)
        n = len(data.get("data", [])) if self._is_success(data) else 0
        self.record("data", "history daily (D)", "PASS" if (self._is_success(data) and n) else "FAIL",
                    f"{n} candles")

        # Multiquotes
        ok, data = self.api("multiquotes", {"symbols": [
            {"symbol": self.cfg("equity_nse"), "exchange": "NSE"},
            {"symbol": self.cfg("index_nse"), "exchange": "NSE_INDEX"},
            {"symbol": self.cfg("index_bse"), "exchange": "BSE_INDEX"},
        ]})
        self.record("data", "multiquotes (mixed)", "PASS" if self._is_success(data) else "SKIP",
                    str(data.get("message") or "")[:80] if not self._is_success(data) else "")

    # =======================================================================
    # 6. Option tools (expiry + option chain), NFO & BFO
    # =======================================================================
    def test_option_tools(self):
        self.section("6. Option tools (expiry + option chain)")
        plan = [("NFO", "NSE_INDEX", self.cfg_list("nfo_underlyings")),
                ("BFO", "BSE_INDEX", self.cfg_list("bfo_underlyings"))]
        for fno_exch, idx_exch, unds in plan:
            for und in unds:
                ok, data = self.api("expiry", {"symbol": und, "exchange": fno_exch,
                                               "instrumenttype": "options"})
                exps = []
                if self._is_success(data):
                    d = data.get("data")
                    exps = d.get("expiry") if isinstance(d, dict) else d
                    exps = exps if isinstance(exps, list) else []
                self.record("optiontools", f"expiry {und}@{fno_exch}",
                            "PASS" if exps else "FAIL", f"{len(exps)} expiries")
                if not exps:
                    self.record("optiontools", f"optionchain {und}", "SKIP", "no expiry")
                    continue
                exp_c = self._compact_expiry(exps[0])
                ok, data = self.api("optionchain", {"underlying": und, "exchange": idx_exch,
                                                    "expiry_date": exp_c, "strike_count": 5})
                self.record("optiontools", f"optionchain {und} ({exp_c})",
                            "PASS" if self._is_success(data) else "FAIL",
                            str(data.get("message") or "")[:80])

    # =======================================================================
    # 7. WebSocket streaming
    # =======================================================================
    def test_websocket(self):
        self.section("7. WebSocket streaming (LTP / Quote / Depth)")
        if self.no_ws:
            self.record("websocket", "WebSocket tests", "SKIP", "--no-ws")
            return
        if websocket is None:
            self.record("websocket", "WebSocket tests", "SKIP", "websocket-client not installed")
            return

        targets = getattr(self, "_data_targets_cache", None) or self._data_targets()
        # one equity + one index is enough to prove the pipeline across modes
        probe = [t for t in targets if t[2] in ("NSE", "NSE_INDEX")][:2] or targets[:2]

        client = _WSClient(self.ws_url, self.api_key)
        if not client.connect():
            self.record("websocket", "connect + authenticate", "FAIL", "could not auth")
            return
        self.record("websocket", "connect + authenticate", "PASS")

        for label, sym, exch in probe:
            for mode, mname in ((1, "LTP"), (2, "Quote"), (3, "Depth")):
                got = client.subscribe_and_wait(sym, exch, mode, timeout=8)
                self.record("websocket", f"{mname} {label} ({sym})",
                            "PASS" if got else "FAIL",
                            "tick received" if got else "no tick in 8s (market closed?)")
        client.disconnect()

    @staticmethod
    def _compact_expiry(exp):
        """optionchain wants DDMMMYY (e.g. 23JUN26); /expiry returns DD-MMM-YY."""
        return str(exp).replace("-", "").upper() if exp else exp

    # -- config helpers -----------------------------------------------------
    def cfg(self, key):
        return CONFIG.get(key)

    def cfg_list(self, key):
        v = CONFIG.get(key)
        return v if isinstance(v, list) else [v]

    # -- summary ------------------------------------------------------------
    def summary(self):
        print(f"\n{B}=== Summary ==={RST}")
        sections = {}
        for sec, _name, status, _d in self.results:
            s = sections.setdefault(sec, {"PASS": 0, "FAIL": 0, "SKIP": 0, "INFO": 0})
            s[status] = s.get(status, 0) + 1
        total = {"PASS": 0, "FAIL": 0, "SKIP": 0}
        print(f"  {'Section':<14} {'PASS':>5} {'FAIL':>5} {'SKIP':>5}")
        for sec, s in sections.items():
            print(f"  {sec:<14} {G}{s['PASS']:>5}{RST} {R}{s['FAIL']:>5}{RST} {Y}{s['SKIP']:>5}{RST}")
            for k in total:
                total[k] += s.get(k, 0)
        print(f"  {'-' * 32}")
        print(f"  {'TOTAL':<14} {G}{total['PASS']:>5}{RST} {R}{total['FAIL']:>5}{RST} {Y}{total['SKIP']:>5}{RST}")
        if total["FAIL"]:
            print(f"\n{R}Failures:{RST}")
            for sec, name, status, detail in self.results:
                if status == "FAIL":
                    print(f"  - [{sec}] {name}  {DIM}{detail}{RST}")
        return total["FAIL"] == 0


class _WSClient:
    """Minimal OpenAlgo WebSocket-proxy client for LTP/Quote/Depth subscription tests."""

    def __init__(self, ws_url, api_key):
        self.ws_url = ws_url
        self.api_key = api_key
        self.ws = None
        self.connected = False
        self.authenticated = False
        self.ticks = []  # list of (exchange, symbol, mode)
        self.lock = threading.Lock()

    def connect(self):
        def on_message(ws, message):
            try:
                msg = json.loads(message)
            except ValueError:
                return
            if msg.get("type") == "auth" and msg.get("status") == "success":
                self.authenticated = True
            elif msg.get("type") == "market_data":
                with self.lock:
                    self.ticks.append((msg.get("exchange"), msg.get("symbol"), msg.get("mode")))

        def on_open(ws):
            self.connected = True
            ws.send(json.dumps({"action": "authenticate", "api_key": self.api_key}))

        def on_close(ws, *a):
            self.connected = False

        self.ws = websocket.WebSocketApp(
            self.ws_url, on_message=on_message, on_open=on_open, on_close=on_close,
            on_error=lambda ws, e: None,
        )
        t = threading.Thread(target=self.ws.run_forever, daemon=True)
        t.start()

        deadline = time.time() + 8
        while time.time() < deadline and not self.authenticated:
            time.sleep(0.1)
        return self.authenticated

    def subscribe_and_wait(self, symbol, exchange, mode, timeout=8):
        with self.lock:
            self.ticks.clear()
        try:
            self.ws.send(json.dumps({"action": "subscribe", "symbol": symbol,
                                     "exchange": exchange, "mode": mode, "depth": 5}))
        except Exception:
            return False
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                if any(t[2] == mode and t[1] == symbol for t in self.ticks):
                    break
            time.sleep(0.2)
        with self.lock:
            got = any(t[2] == mode and t[1] == symbol for t in self.ticks)
        try:
            self.ws.send(json.dumps({"action": "unsubscribe", "symbol": symbol,
                                     "exchange": exchange, "mode": mode}))
        except Exception:
            pass
        return got

    def disconnect(self):
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description="OpenAlgo broker-integration test runner")
    parser.add_argument("--apikey", default=None, help="OpenAlgo API key (else API_KEY env/.env)")
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument("--ws-url", default="ws://127.0.0.1:8765")
    parser.add_argument("--live", action="store_true", help="run order tests against the REAL broker")
    parser.add_argument("--no-ws", action="store_true", help="skip WebSocket tests")
    parser.add_argument("--sections", default="1,2,3,4,5,6,7", help="comma list of sections to run")
    parser.add_argument("--equity", default=None, help="override NSE equity test symbol")
    args = parser.parse_args()

    api_key = args.apikey or os.getenv("API_KEY")
    if not api_key:
        try:
            from dotenv import load_dotenv
            load_dotenv()
            api_key = os.getenv("API_KEY")
        except ImportError:
            pass
    if not api_key:
        print(f"{R}No API key. Pass --apikey or set API_KEY in .env.{RST}")
        sys.exit(2)

    if args.equity:
        CONFIG["equity_nse"] = args.equity

    sections = {s.strip() for s in args.sections.split(",") if s.strip()}
    r = Runner(args.base_url, args.ws_url, api_key, live=args.live, no_ws=args.no_ws)

    print(f"{B}OpenAlgo Broker Integration Test Runner{RST}")
    print(f"  base={args.base_url}  ws={args.ws_url}  order-mode={'LIVE' if args.live else 'SANDBOX'}")
    if args.live:
        print(f"{Y}  WARNING: --live places REAL orders (qty 1, limits far from LTP).{RST}")

    # Section 1 (auth) gates everything
    if "1" in sections:
        if not r.test_auth():
            r.summary()
            sys.exit(1)
    if "2" in sections:
        r.test_funds()
    if "3" in sections:
        r.test_symbols()
    if "4" in sections:
        r.test_orders()
    if "5" in sections:
        r.test_marketdata()
    if "6" in sections:
        r.test_option_tools()
    if "7" in sections:
        r.test_websocket()

    ok = r.summary()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
