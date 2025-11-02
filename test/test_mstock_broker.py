#!/usr/bin/env python3
import os
import sys
import time
from dataclasses import dataclass, field
from typing import List, Dict
import pandas as pd
from colorama import Fore, Style, init as colorama_init

colorama_init(autoreset=True)

# Assuming openalgo SDK is installed
try:
    from broker.mstock.streaming.mstock_adapter import MstockWebSocketAdapter
    from broker.mstock.api.auth_api import authenticate_broker_mstock
except ImportError as e:
    print(f"{Fore.RED}Failed to import mstock components: {e}")
    sys.exit(1)

# --- CONFIG ---
API_KEY = os.getenv("OPENALGO_API_KEY", "your_openalgo_api_key")
HOST = os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000")

# mstock specific test data
MSTOCK_REPRESENTATIVE = {
    "NSE": "INFY",
    "BSE": "RELIANCE",
    "NFO": "NIFTY29MAY2525000CE",
}

def green(t): return f"{Fore.GREEN}{t}{Style.RESET_ALL}"
def red(t): return f"{Fore.RED}{t}{Style.RESET_ALL}"

@dataclass
class StageResult:
    name: str
    passed: int = 0
    failed: int = 0
    details: List[str] = field(default_factory=list)

    def add(self, ok: bool, msg: str = ""):
        if ok:
            self.passed += 1
        else:
            self.failed += 1
            self.details.append(msg)

    def summary_line(self) -> str:
        status = green("✓") if self.failed == 0 else red("✗")
        return f"{status}  {self.name}: {self.passed} ok, {self.failed} fail"

@dataclass
class FinalReport:
    stages: List[StageResult] = field(default_factory=list)

    def add(self, st: StageResult):
        self.stages.append(st)

    def print(self):
        print("\\n──────── STAGE-BY-STAGE SUMMARY ────────")
        for s in self.stages:
            print(s.summary_line())
            for d in s.details:
                print(f"   {red('•')} {d}")
        total_fail = sum(s.failed for s in self.stages)
        total_pass = sum(s.passed for s in self.stages)
        colour = Fore.GREEN if total_fail == 0 else Fore.RED
        print(f"\\n{colour}{total_pass} checks passed, {total_fail} failed{Style.RESET_ALL}")
        return total_fail == 0

class MstockTester:
    def __init__(self):
        self.report = FinalReport()
        self.access_token = None
        self.api_key = os.getenv('MSTOCK_BROKER_API_KEY')

    def stage(self, name):
        sr = StageResult(name)
        class Ctx:
            def __enter__(self_non): return sr
            def __exit__(self_non, *exc):
                self.report.add(sr)
                print(sr.summary_line())
        return Ctx()

    def test_authentication(self):
        with self.stage("Authentication") as st:
            try:
                self.access_token, error = authenticate_broker_mstock()
                if error:
                    st.add(False, f"Authentication failed: {error}")
                else:
                    st.add(True, "Authentication successful")
            except Exception as e:
                st.add(False, f"Authentication exception: {e}")

    def test_websocket_connection(self):
        with self.stage("WebSocket Connection") as st:
            if not self.access_token:
                st.add(False, "Skipping WebSocket test due to authentication failure.")
                return

            try:
                adapter = MstockWebSocketAdapter()
                adapter.initialize("mstock", "test_user", {"api_key": self.api_key, "access_token": self.access_token})
                adapter.connect()
                time.sleep(5)  # Wait for connection
                if adapter.connected:
                    st.add(True, "WebSocket connected successfully.")
                else:
                    st.add(False, "WebSocket failed to connect.")
                adapter.disconnect()
            except Exception as e:
                st.add(False, f"WebSocket connection exception: {e}")

    def run(self):
        self.test_authentication()
        self.test_websocket_connection()
        return self.report.print()

if __name__ == "__main__":
    if not all(os.getenv(k) for k in ['MSTOCK_BROKER_API_KEY', 'MSTOCK_USERNAME', 'MSTOCK_PASSWORD', 'MSTOCK_TOTP_SECRET']):
        print(f"{Fore.RED}Please set MSTOCK environment variables for testing.")
        sys.exit(1)

    tester = MstockTester()
    success = tester.run()
    sys.exit(0 if success else 1)
