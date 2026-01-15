#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenAlgo – New Broker Integration Test
• Stage‑by‑stage progress output
• Immediate reporting of any failing symbol / order‑id
• Final green / red roll‑up
"""

import os, sys, time, traceback
from dataclasses import dataclass, field
from typing import List, Dict, Tuple
import pandas as pd
from colorama import Fore, Style, init as colorama_init

colorama_init(autoreset=True)

# ───────────────── CONFIG ─────────────────
API_KEY = os.getenv(
    "OPENALGO_API_KEY",
    "3bb8d260915ff680a7258108c0483b9eb7675ced31309a36f5846366943ee9fa"
)
HOST = os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000")

NSE_INDICES = ["NIFTY","BANKNIFTY","FINNIFTY","NIFTYNXT50","MIDCPNIFTY","INDIAVIX"]
BSE_INDICES = ["SENSEX","BANKEX","SENSEX50"]

REPRESENTATIVE: Dict[str,str] = {
    "NSE":"NHPC",
    "NFO":"NIFTY29MAY2525000CE",
    "MCX":"CRUDEOIL19MAY25FUT",
    "CDS":"USDINR30MAY25FUT",
    "NSE_INDEX":"NIFTY",
    "BSE_INDEX":"SENSEX",
}

SPECIAL_SYMBOLS = [("NSE","M&M"),("NSE","BAJAJ-AUTO")]

RATE_SLEEP_ORD  = 0.11   # keep <10 req / sec
RATE_SLEEP_MISC = 0.05

# ────────────── helpers ──────────────
def green(t): return f"{Fore.GREEN}{t}{Style.RESET_ALL}"
def red(t):   return f"{Fore.RED}{t}{Style.RESET_ALL}"
def want(resp:dict,path:List[str]):
    if resp.get("status")!="success": raise AssertionError("status!=success")
    p=resp
    for k in path:
        p=p.get(k)
        if p is None: raise AssertionError(f"missing ‹{'→'.join(path)}›")

@dataclass
class StageResult:
    name:str
    passed:int=0
    failed:int=0
    details:List[str]=field(default_factory=list)

    def add(self, ok:bool, msg:str=""):
        if ok: self.passed+=1
        else:
            self.failed+=1
            self.details.append(msg)

    def summary_line(self)->str:
        status = green("✓") if self.failed==0 else red("✗")
        return f"{status}  {self.name}: {self.passed} ok, {self.failed} fail"

@dataclass
class FinalReport:
    stages:List[StageResult]=field(default_factory=list)
    def add(self, st:StageResult): self.stages.append(st)
    def print(self):
        print("\n──────── STAGE‑BY‑STAGE SUMMARY ────────")
        for s in self.stages:
            print(s.summary_line())
            for d in s.details:
                print(f"   {red('•')} {d}")
        total_fail=sum(s.failed for s in self.stages)
        total_pass=sum(s.passed for s in self.stages)
        colour=Fore.GREEN if total_fail==0 else Fore.RED
        print(f"\n{colour}{total_pass} checks passed, {total_fail} failed{Style.RESET_ALL}")
        return total_fail==0

# ────────────── tester ──────────────
class Tester:
    def __init__(self, client):
        self.c=client
        self.report=FinalReport()
        self.placed:List[str]=[]

    # utility to create & close a stage context
    def stage(self,name):
        sr=StageResult(name)
        class Ctx:
            def __enter__(self_non): return sr
            def __exit__(self_non,*exc): 
                self.report.add(sr)
                print(sr.summary_line())  # live progress
        return Ctx()

    # ───── stages ─────
    def index_quotes(self):
        with self.stage("Index quotes") as st:
            for sym in NSE_INDICES+[]:   # NSE first
                try: want(self.c.quotes(symbol=sym,exchange="NSE_INDEX"),["data","ltp"]); st.add(True)
                except Exception as e:   st.add(False,f"{sym}@NSE_INDEX → {e}")
            for sym in BSE_INDICES:
                try: want(self.c.quotes(symbol=sym,exchange="BSE_INDEX"),["data","ltp"]); st.add(True)
                except Exception as e:   st.add(False,f"{sym}@BSE_INDEX → {e}")

    def order_matrix(self):
        with self.stage("Order matrix") as st:
            prods=["CNC","MIS","NRML"]; ptypes=["MARKET","LIMIT","SL","SL-M"]; acts=["BUY","SELL"]
            ltp=self.c.quotes(symbol="NHPC",exchange="NSE")["data"]["ltp"]
            for pr in prods:
                for pt in ptypes:
                    for ac in acts:
                        price=round(ltp*(0.995 if ac=="BUY" else 1.005),2) if pt!="MARKET" else 0
                        trg=round(price*(0.99 if ac=="BUY" else 1.01),2) if pt in ["SL","SL-M"] else 0
                        tag=f"{pt}/{ac}/{pr}"
                        try:
                            res=self.c.placeorder(strategy="TEST",symbol="NHPC",exchange="NSE",
                                                  price_type=pt,product=pr,action=ac,quantity=1,
                                                  price=price,trigger_price=trg)
                            want(res,["orderid"]); self.placed.append(res["orderid"]); st.add(True)
                        except Exception as e:
                            st.add(False,f"{tag} → {e}")
                        time.sleep(RATE_SLEEP_ORD)

    def cancel_each(self):
        with self.stage("Cancel each") as st:
            for oid in self.placed:
                try: want(self.c.cancelorder(order_id=oid,strategy="TEST"),["orderid"]); st.add(True)
                except Exception as e: st.add(False,f"{oid} → {e}")
                time.sleep(RATE_SLEEP_MISC)
        self.placed.clear()

    def smart_order(self):
        with self.stage("Smart order") as st:
            try:
                res=self.c.placesmartorder(strategy="TEST",symbol="NHPC",action="SELL",
                                           exchange="NSE",price_type="MARKET",product="MIS",
                                           quantity=1,position_size=3)
                want(res,["orderid"]); st.add(True)
            except Exception as e:
                st.add(False,str(e))

    def basket_order(self):
        with self.stage("Basket order") as st:
            bask=[{"symbol":"BHEL","exchange":"NSE","action":"BUY","quantity":1,"pricetype":"MARKET","product":"MIS"},
                  {"symbol":"ZOMATO","exchange":"NSE","action":"SELL","quantity":1,"pricetype":"MARKET","product":"MIS"}]
            try:
                res=self.c.basketorder(orders=bask)
                want(res,["results"])
                if not res["results"]: raise AssertionError("empty results")
                st.add(True)
            except Exception as e: st.add(False,str(e))

    def split_order(self):
        with self.stage("Split order") as st:
            try:
                res=self.c.splitorder(symbol="NHPC",exchange="NSE",action="BUY",
                                      quantity=55,splitsize=20,price_type="MARKET",product="MIS")
                want(res,["results"]); st.add(True)
            except Exception as e: st.add(False,str(e))

    def order_mgmt_cycle(self):
        with self.stage("Order mgmt cycle") as st:
            try:
                new=self.c.placeorder(strategy="TEST",symbol="NHPC",exchange="NSE",
                                      price_type="LIMIT",product="CNC",action="BUY",
                                      quantity=1,price=1)
                oid=new["orderid"]
                self.c.modifyorder(order_id=oid,strategy="TEST",symbol="NHPC",action="BUY",
                                   exchange="NSE",price_type="LIMIT",product="CNC",
                                   quantity=1,price=2)
                self.c.orderstatus(order_id=oid,strategy="TEST")
                self.c.cancelallorder(strategy="TEST")
                #self.c.closeposition(strategy="TEST")
                st.add(True)
            except Exception as e: st.add(False,str(e))

    def market_data(self):
        with self.stage("Market‑data endpoints") as st:
            for ex,sym in REPRESENTATIVE.items():
                tag=f"{sym}@{ex}"
                try:
                    want(self.c.quotes(symbol=sym,exchange=ex),["data"])
                    want(self.c.depth(symbol=sym,exchange=ex),["data"])
                    df=self.c.history(symbol=sym,exchange=ex,interval="5m",
                                      start_date="2025-04-01",end_date="2025-04-02")
                    if not isinstance(df,pd.DataFrame) or df.empty:
                        raise AssertionError("history empty")
                    st.add(True)
                except Exception as e:
                    st.add(False,f"{tag} → {e}")

    def intervals_and_symbol(self):
        with self.stage("Intervals & symbol()") as st:
            try: want(self.c.intervals(),["data","minutes"]); st.add(True)
            except Exception as e: st.add(False,f"intervals() → {e}")
            try: want(self.c.symbol(symbol="NHPC",exchange="NSE"),["data","token"]); st.add(True)
            except Exception as e: st.add(False,f"symbol() → {e}")

    def special_quotes(self):
        with self.stage("Special NSE symbols") as st:
            for ex,sym in SPECIAL_SYMBOLS:
                try: want(self.c.quotes(symbol=sym,exchange=ex),["data","ltp"]); st.add(True)
                except Exception as e: st.add(False,f"{sym} → {e}")

    def account_info(self):
        with self.stage("Account info endpoints") as st:
            try:
                funds=self.c.funds()
                if funds.get("status")!="success": raise AssertionError("funds fail")
                if not any(k in funds["data"] for k in ("availablecash","balance","cash")):
                    raise AssertionError("funds keys")
                st.add(True)
            except Exception as e: st.add(False,f"funds() → {e}")
            for ep in (self.c.orderbook,self.c.tradebook,self.c.positionbook,self.c.holdings):
                try:
                    if ep().get("status")!="success": raise AssertionError("status!=success")
                    st.add(True)
                except Exception as e: st.add(False,f"{ep.__name__} → {e}")

    # run all stages
    def run(self):
        for stage_fn in [self.index_quotes,self.order_matrix,self.cancel_each,
                         self.smart_order,self.basket_order,self.split_order,
                         self.order_mgmt_cycle,self.market_data,
                         self.intervals_and_symbol,self.special_quotes,
                         self.account_info]:
            stage_fn()
        return self.report.print()

# ─────────────────── main ───────────────────
if __name__=="__main__":
    try: from openalgo import api as OAClient
    except ImportError:
        print(red("openalgo SDK missing – pip install openalgo")); sys.exit(1)

    client=OAClient(api_key=API_KEY,host=HOST)
    success=Tester(client).run()
    sys.exit(0 if success else 1)
