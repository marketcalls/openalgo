#!/usr/bin/env python3
"""
Automated Intraday NSE Equity Trading System
Strategy : 15-min Opening Range Breakout (ORB) — Long and Short
Backend  : OpenAlgo REST API → Dhan broker

Risk model:
  - 1 trade deploys Rs. 1 Lakh of capital
  - Quantity = floor(capital_per_trade / entry_price)
  - SL = first 15-min candle low (BUY) / high (SELL)
  - If SL distance > 2% of entry, SL tightened to 60% into the first candle from its high (BUY) / low (SELL)
"""

import logging
import os
import sys
import time

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)
except ImportError:
    pass  # dotenv not installed — rely on shell environment

from io import TextIOWrapper
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, cast

import pandas as pd
import requests

# ─── Logging ─────────────────────────────────────────────────────────────────────
try:
    if isinstance(sys.stdout, TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except AttributeError:
    pass

_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
_fh = logging.FileHandler("trading_bot.log", encoding="utf-8")
_fh.setFormatter(_fmt)
_ch = logging.StreamHandler(sys.stdout)
_ch.setFormatter(_fmt)
logging.basicConfig(level=logging.INFO, handlers=[_fh, _ch])
logger = logging.getLogger(__name__)


# ─── Configuration ────────────────────────────────────────────────────────────────
@dataclass
class Config:
    # OpenAlgo connection
    openalgo_url: str = os.getenv("OPENALGO_URL", "http://127.0.0.1:5000")
    api_key: str = os.getenv("OPENALGO_API_KEY", "e3fffb919d48184f855278f3601f0ec15ae09100bf447d7808b70391b3166576")

    # Paper trading — no real orders sent, uses live market data for signals
    paper_trade: bool = os.getenv("PAPER_TRADE", "true").lower() != "false"

    # Capital
    # total_capital is used only for daily drawdown calculation.
    total_capital: float = float(os.getenv("TRADING_CAPITAL", "600000"))  # Rs. 6 Lakh (6 × 1L)
    capital_per_trade: float = 100000   # Rs. 1 Lakh deployed per trade

    max_trades: int = 10
    rvol_threshold: float = 1.5          # yesterday's volume / 20-day avg must exceed this
    max_consecutive_losses: int = 3
    max_daily_drawdown_pct: float = 0.03    # 3% of total_capital

    # Order params
    product: str = "MIS"                    # Intraday square-off
    exchange: str = "NSE"                   # NSE cash equity

    # Session times  (HH:MM 24-hour)
    scan_start: str = "09:15"
    scan_end: str = "09:30"
    entry_start: str = "09:35"
    no_new_trade_after: str = "14:20"
    square_off_time: str = "15:10"

    # Trailing SL (activates after partial booking at the 0.6R target)
    trailing_trigger_pct: float = 0.25      # trigger every 25% of risk
    trailing_step_pct: float = 0.25         # step SL by 25% of risk

    # API call interval during active trading
    monitor_interval_sec: int = 5


# ─── NSE F&O Equity Universe ─────────────────────────────────────────────────────
# Fallback list used when the master-contract API is unavailable.
# The live path (fetch_fno_symbols) dynamically pulls all F&O stocks at runtime.
EQUITY_UNIVERSE: List[str] = [
    # ── Banking ──────────────────────────────────────────────────────────────────
    "HDFCBANK",   "ICICIBANK",  "KOTAKBANK",   "AXISBANK",   "SBIN",
    "BANKBARODA", "INDUSINDBK", "CANBK",        "PNB",        "FEDERALBNK",
    "IDFCFIRSTB", "AUBANK",     "BANDHANBNK",   "RBLBANK",    "YESBANK",
    # ── Financial Services ───────────────────────────────────────────────────────
    "BAJFINANCE", "BAJAJFINSV", "HDFCLIFE",    "ICICIPRULI", "SBILIFE",
    "SBICARD",    "CHOLAFIN",   "M&MFIN",       "LICHSGFIN",  "MFSL",
    # ── IT & Technology ──────────────────────────────────────────────────────────
    "TCS",        "INFY",       "WIPRO",         "HCLTECH",    "TECHM",
    "LTIM",       "NAUKRI",     "ZOMATO",        "COFORGE",    "PERSISTENT",
    "MPHASIS",    "OFSS",       "LTTS",          "KPITTECH",
    # ── Auto & Components ────────────────────────────────────────────────────────
    "MARUTI",     "TATAMOTORS", "BAJAJ-AUTO",    "HEROMOTOCO", "EICHERMOT",
    "M&M",        "TVSMOTOR",   "MOTHERSON",     "ASHOKLEY",   "BHARATFORG",
    "APOLLOTYRE", "BALKRISIND", "EXIDEIND",      "UNOMINDA",   "BOSCHLTD",
    "TIINDIA",    "SONACOMS",
    # ── Pharma & Healthcare ──────────────────────────────────────────────────────
    "SUNPHARMA",  "CIPLA",      "DRREDDY",       "DIVISLAB",   "BIOCON",
    "LUPIN",      "LAURUSLABS", "AUROPHARMA",    "GLENMARK",   "WOCKPHARMA",
    "JBCHEPHARM", "MANKIND",    "TORNTPHARM",    "IPCALAB",    "AJANTPHARM",
    "ZYDUSLIFE",  "ABBOTINDIA", "ALKEM",         "GLAND",      "NATCOPHARM",
    "APOLLOHOSP", "MAXHEALTH",  "FORTIS",        "SYNGENE",
    # ── FMCG & Consumer ──────────────────────────────────────────────────────────
    "HINDUNILVR", "ITC",        "BRITANNIA",     "NESTLEIND",  "TATACONSUM",
    "DMART",      "TRENT",      "ASIANPAINT",    "GODREJCP",   "VBL",
    "MARICO",     "RADICO",     "DABUR",         "COLPAL",     "UBL",
    "EMAMILTD",
    # ── Metals & Mining ──────────────────────────────────────────────────────────
    "JSWSTEEL",   "HINDALCO",   "TATASTEEL",     "VEDL",       "HINDZINC",
    "HINDCOPPER", "SAIL",       "NATIONALUM",    "JINDALSTEL", "NMDC",
    "MOIL",       "LLOYDSME",   "APLAPOLLO",     "WELCORP",    "JSL",
    # ── Oil, Gas & Power ─────────────────────────────────────────────────────────
    "RELIANCE",   "ONGC",       "BPCL",          "COALINDIA",  "IOC",
    "HINDPETRO",  "GAIL",       "TATAPOWER",     "TORNTPOWER", "ADANIGREEN",
    "JSWENERGY",  "CESC",       "NHPC",           "SJVN",
    # ── Infrastructure & Capital Goods ───────────────────────────────────────────
    "NTPC",       "POWERGRID",  "LT",            "ADANIPORTS", "ADANIENT",
    "ULTRACEMCO", "GRASIM",     "SHREECEM",      "AMBUJACEM",  "DALBHARAT",
    "ACC",        "JKCEMENT",   "RAMCOCEM",      "ABB",        "SIEMENS",
    "CGPOWER",    "BHEL",       "HAL",           "BEL",        "GMRAIRPORT",
    "RVNL",       "IRFC",       "BHARTIARTL",
    # ── Chemicals ────────────────────────────────────────────────────────────────
    "UPL",        "PIDILITIND", "TATACHEM",      "SRF",        "NAVINFLUOR",
    "DEEPAKNTR",  "COROMANDEL", "PIIND",         "AARTIIND",   "DEEPAKFERT",
    "ATUL",       "FLUOROCHEM", "LINDEINDIA",    "SOLARINDS",  "PCBL",
    "CHAMBLFERT", "BAYERCROP",  "SUMICHEM",      "HSCL",
    # ── Consumer Durables ────────────────────────────────────────────────────────
    "DIXON",      "TITAN",      "KALYANKJIL",    "AMBER",      "BLUESTARCO",
    "CROMPTON",   "VOLTAS",     "HAVELLS",       "WHIRLPOOL",  "BATAINDIA",
    "KAJARIACER",
    # ── Realty ───────────────────────────────────────────────────────────────────
    "DLF",        "ANANTRAJ",   "LODHA",         "GODREJPROP", "OBEROIRLTY",
    "PRESTIGE",   "PHOENIXLTD", "BRIGADE",       "SOBHA",
    # ── PSE & Government ─────────────────────────────────────────────────────────
    "IRCTC",      "PFC",        "REC",           "LICI",
    # ── Media & Entertainment ────────────────────────────────────────────────────
    "PVRINOX",    "SUNTV",
    # ── Diversified / New-Age ────────────────────────────────────────────────────
    "INDIGO",     "INDHOTEL",   "NYKAA",         "POLICYBZR",  "PAYTM",
]


# ─── OpenAlgo REST Client ─────────────────────────────────────────────────────────
class OpenAlgoClient:
    def __init__(self, config: Config):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def _post(self, endpoint: str, payload: dict, retries: int = 3) -> dict:
        payload = {**payload, "apikey": self.config.api_key}
        url = f"{self.config.openalgo_url}{endpoint}"
        for attempt in range(retries):
            try:
                r = self.session.post(url, json=payload, timeout=10)
                r.raise_for_status()
                return r.json()
            except requests.Timeout:
                logger.warning(f"Timeout {endpoint} (attempt {attempt+1})")
                time.sleep(1)
            except requests.RequestException as e:
                body = ""
                try:
                    body = e.response.text[:200] if e.response is not None else ""
                except Exception:
                    pass
                logger.error(f"API error {endpoint}: {e}{' — ' + body if body else ''}")
                break
            except ValueError as e:
                logger.error(f"Invalid JSON from {endpoint}: {e}")
                break
        return {"status": "error", "message": "request failed"}

    def history(
        self,
        symbol: str,
        interval: str,
        start_date: str,
        end_date: str,
        exchange: str = "NSE",
    ) -> Optional[pd.DataFrame]:
        resp = self._post("/api/v1/history", {
            "symbol": symbol,
            "exchange": exchange,
            "interval": interval,
            "start_date": start_date,
            "end_date": end_date,
        })
        if resp.get("status") != "success":
            return None
        if not resp.get("data"):
            logger.debug(f"No history data for {symbol} ({exchange} {interval} {start_date}→{end_date})")
            return None
        df = pd.DataFrame(resp["data"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=False)
        df = df.set_index("timestamp")
        base_cols = ["open", "high", "low", "close", "volume"]
        if "oi" in df.columns:
            base_cols.append("oi")
        df = cast(pd.DataFrame, df[base_cols].astype(float))
        if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        return df

    def quote(self, symbol: str, exchange: str = "NSE") -> Optional[float]:
        resp = self._post("/api/v1/quotes", {"symbol": symbol, "exchange": exchange})
        if resp.get("status") == "success":
            data = resp.get("data", resp)
            ltp = data.get("ltp") or data.get("last_price")
            return float(ltp) if ltp is not None else None
        return None

    def place_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price_type: str = "MARKET",
        price: float = 0.0,
        trigger_price: float = 0.0,
    ) -> Optional[str]:
        if self.config.paper_trade:
            trig_str = f" trigger={trigger_price:.2f}" if trigger_price else ""
            logger.info(
                f"[PAPER] {action} {quantity} {symbol} "
                f"type={price_type}{trig_str}"
            )
            return "paper-" + str(int(time.time() * 1000))

        payload = {
            "symbol": symbol,
            "exchange": self.config.exchange,
            "action": action,
            "quantity": quantity,
            "product": self.config.product,
            "pricetype": price_type,
            "price": price,
            "trigger_price": trigger_price,
            "disclosed_quantity": 0,
            "strategy": "ORBTrader",
        }
        resp = self._post("/api/v1/placeorder", payload)
        if resp.get("status") == "success":
            oid = resp.get("orderid") or (resp.get("data") or {}).get("orderid")
            logger.info(f"Order OK | {action} {quantity} {symbol} | id={oid}")
            return str(oid) if oid else "placed"
        logger.error(f"Order FAILED | {symbol} {action} {quantity} | {resp}")
        return None

    def _get(self, endpoint: str, params: dict) -> dict:
        params = {**params, "apikey": self.config.api_key}
        url = f"{self.config.openalgo_url}{endpoint}"
        try:
            # Clear Content-Type for GET — Flask rejects application/json on empty-body GET
            r = self.session.get(url, params=params, timeout=30,
                                 headers={"Content-Type": None})
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            body = ""
            try:
                body = e.response.text[:300] if e.response is not None else ""
            except Exception:
                pass
            logger.error(f"GET {endpoint} failed: {e}{' — ' + body if body else ''}")
            return {"status": "error"}
        except Exception as e:
            logger.error(f"GET {endpoint} failed: {e}")
            return {"status": "error"}

    def instruments(self, exchange: str = "NFO") -> List[dict]:
        """Return all instrument records for an exchange from the master contract."""
        resp = self._get("/api/v1/instruments", {"exchange": exchange, "format": "json"})
        if resp.get("status") == "success":
            return resp.get("data", [])
        return []

    def positions(self) -> List[dict]:
        resp = self._post("/api/v1/positions", {})
        return resp.get("data", []) if resp.get("status") == "success" else []


# ─── Technical Indicators ────────────────────────────────────────────────────────
class TA:
    @staticmethod
    def ema(s: pd.Series, n: int) -> pd.Series:
        return cast(pd.Series, s.ewm(span=n, adjust=False).mean())


# ─── Scanned Stock ────────────────────────────────────────────────────────────────
@dataclass
class ScannedStock:
    base: str                           # NSE equity symbol e.g. "RELIANCE"
    score: float
    direction: str = "BUY"             # "BUY" (long ORB) or "SELL" (short ORB)
    fc_open: float = 0.0
    fc_high: float = 0.0
    fc_low: float = 0.0
    fc_range: float = 0.0
    candle_captured: bool = False
    breakout_confirmed: bool = False    # True once a 5m bar closed beyond the ORB level
    vwap: float = 0.0                   # VWAP updated each 5m cycle; used for pullback entries
    prev_close: float = 0.0             # yesterday's close — used for gap filter

    @property
    def symbol(self) -> str:           # symbol == base for equity (no expiry suffix)
        return self.base


# ─── Trade ────────────────────────────────────────────────────────────────────────
@dataclass
class Trade:
    base: str
    entry: float
    sl: float
    target: float
    qty: int
    remaining: int
    direction: str = "BUY"             # "BUY" or "SELL"
    trail_sl: float = 0.0
    realized_pnl: float = 0.0
    closed: bool = False

    @property
    def symbol(self) -> str:
        return self.base

    @property
    def risk_pts(self) -> float:
        return abs(self.entry - self.sl)


# ─── Risk Manager ─────────────────────────────────────────────────────────────────
class RiskManager:
    def __init__(self, config: Config):
        self.config = config
        self._start_capital = config.total_capital
        self.trades_today = 0
        self.consecutive_losses = 0
        self.daily_pnl = 0.0
        self._halt_reason: str = ""

    @property
    def halted(self) -> bool:
        reason = ""
        if self.trades_today >= self.config.max_trades:
            reason = f"max trades reached ({self.trades_today})"
        elif self.consecutive_losses >= self.config.max_consecutive_losses:
            reason = f"{self.consecutive_losses} consecutive losses"
        else:
            drawdown = -self.daily_pnl / self._start_capital
            if drawdown >= self.config.max_daily_drawdown_pct:
                reason = f"{drawdown:.1%} daily drawdown breached"

        if reason:
            if reason != self._halt_reason:
                logger.warning(f"Trading halted — {reason}")
                self._halt_reason = reason
            return True

        self._halt_reason = ""
        return False

    def calc_qty(self, entry: float) -> int:
        """Qty = floor(capital_per_trade / entry). Minimum 1 share."""
        if entry <= 0:
            return 0
        return max(1, int(self.config.capital_per_trade / entry))

    def record(self, pnl: float):
        self.daily_pnl += pnl
        self.trades_today += 1
        self.consecutive_losses = 0 if pnl >= 0 else self.consecutive_losses + 1
        logger.info(
            f"Trade closed | PnL Rs.{pnl:,.2f} | "
            f"Daily Rs.{self.daily_pnl:,.2f} | "
            f"Consec losses {self.consecutive_losses}"
        )


# ─── Trade Manager ────────────────────────────────────────────────────────────────
class TradeManager:
    def __init__(self, config: Config, api: OpenAlgoClient, risk: RiskManager):
        self.config = config
        self.api = api
        self.risk = risk
        self.active: Dict[str, Trade] = {}      # symbol → Trade
        self.traded_symbols: set = set()

    def can_enter(self, symbol: str) -> bool:
        return (
            symbol not in self.traded_symbols
            and symbol not in self.active
            and not self.risk.halted
        )

    def enter(self, stock: ScannedStock, ltp: float) -> bool:
        if not self.can_enter(stock.symbol):
            return False

        entry = ltp
        is_long = stock.direction == "BUY"

        if stock.fc_range <= 0:
            logger.warning(f"Skip {stock.base}: zero first-candle range")
            return False

        if is_long:
            sl = stock.fc_low
            # If fc_low is more than 2% below entry, tighten SL to 60% into the candle from its high
            if (entry - sl) / entry > 0.02:
                sl = stock.fc_high - 0.60 * stock.fc_range
                logger.info(
                    f"Tight SL {stock.base}: fc_low too far (>2%) → "
                    f"SL=fc_high-60%range={sl:.2f}"
                )
            if sl >= entry:
                logger.warning(f"Skip {stock.base}: SL {sl:.2f} >= entry {entry:.2f}")
                return False
            target = entry + 2 * (entry - sl)   # 1:2 R:R
        else:
            sl = stock.fc_high
            # If fc_high is more than 2% above entry, tighten SL to 60% into the candle from its low
            if (sl - entry) / entry > 0.02:
                sl = stock.fc_low + 0.60 * stock.fc_range
                logger.info(
                    f"Tight SL {stock.base}: fc_high too far (>2%) → "
                    f"SL=fc_low+60%range={sl:.2f}"
                )
            if sl <= entry:
                logger.warning(f"Skip {stock.base}: SL {sl:.2f} <= entry {entry:.2f}")
                return False
            target = entry - 2 * (sl - entry)   # 1:2 R:R

        qty = self.risk.calc_qty(entry)
        if qty <= 0:
            logger.warning(f"Skip {stock.base}: zero quantity")
            return False

        risk_pts   = abs(entry - sl)
        risk_rs    = qty * risk_pts
        capital_rs = qty * entry
        logger.info(
            f"ENTER {stock.direction} {stock.base} | entry={entry:.2f} SL={sl:.2f} "
            f"target={target:.2f} qty={qty} "
            f"capital=Rs.{capital_rs:,.0f} risk=Rs.{risk_rs:,.0f}"
        )

        # Software-only SL — no broker-side SL-M.
        # Broker SL-M + software monitoring = duplicate close orders on fill.
        oid = self.api.place_order(stock.symbol, stock.direction, qty)
        if not oid:
            # Prevent retry every 5 sec on a broker that keeps rejecting
            self.traded_symbols.add(stock.symbol)
            return False

        trade = Trade(
            base=stock.base,
            entry=entry,
            sl=sl,
            target=target,
            qty=qty,
            remaining=qty,
            direction=stock.direction,
            trail_sl=sl,
        )
        self.active[stock.symbol] = trade
        self.traded_symbols.add(stock.symbol)
        return True

    def monitor(self):
        for sym, trade in list(self.active.items()):
            if trade.closed:
                continue
            ltp = self.api.quote(sym, self.config.exchange)
            if ltp is None:
                continue
            self._tick(trade, ltp)

    def _tick(self, trade: Trade, ltp: float):
        is_long = trade.direction == "BUY"

        # ── SL check ──────────────────────────────────────────────────────────
        sl_hit = (ltp <= trade.trail_sl) if is_long else (ltp >= trade.trail_sl)
        if sl_hit:
            self._close(trade, ltp, "SL")
            return

        profit_pts = (ltp - trade.entry) if is_long else (trade.entry - ltp)

        # ── Full exit at 1:2 target ───────────────────────────────────────────
        target_hit = (ltp >= trade.target) if is_long else (ltp <= trade.target)
        if target_hit:
            self._close(trade, ltp, "TARGET_1:2")
            return

        # ── Trail SL: step 25% of risk for every 25% profit advance ──────────
        if profit_pts > 0:
            trig  = trade.risk_pts * self.config.trailing_trigger_pct
            step  = trade.risk_pts * self.config.trailing_step_pct
            steps = int(profit_pts / trig) if trig > 0 else 0

            if is_long:
                new_sl = trade.entry + steps * step
                if new_sl > trade.trail_sl:
                    trade.trail_sl = new_sl
                    logger.info(f"Trail SL {trade.base} → {new_sl:.2f}")
            else:
                new_sl = trade.entry - steps * step
                if new_sl < trade.trail_sl:
                    trade.trail_sl = new_sl
                    logger.info(f"Trail SL {trade.base} → {new_sl:.2f}")

    def _close(self, trade: Trade, ltp: float, reason: str):
        if trade.closed:
            return
        if trade.remaining > 0:
            close_action = "SELL" if trade.direction == "BUY" else "BUY"
            self.api.place_order(trade.symbol, close_action, trade.remaining)
            profit_pts = (ltp - trade.entry) if trade.direction == "BUY" else (trade.entry - ltp)
            trade.realized_pnl += trade.remaining * profit_pts
        trade.closed = True
        total_pnl = trade.realized_pnl
        logger.info(
            f"CLOSE [{reason}] {trade.base} | "
            f"entry={trade.entry:.2f} exit={ltp:.2f} PnL=Rs.{total_pnl:,.2f}"
        )
        self.risk.record(total_pnl)
        self.active.pop(trade.symbol, None)

    def square_off_all(self):
        logger.info(">> 3:10 PM square-off — closing all open positions")
        for sym, trade in list(self.active.items()):
            if not trade.closed:
                ltp = self.api.quote(sym, self.config.exchange) or trade.entry
                self._close(trade, ltp, "SQUAREOFF")


# Index futures that exist in NFO but have no NSE equity counterpart — exclude these
_INDEX_FUTURES = {
    "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50",
    "SENSEX", "BANKEX", "NIFTYIT", "NIFTYAUTO", "NIFTYMETAL",
    "NIFTYPHARMA", "NIFTYFMCG", "NIFTYREALTY", "NIFTYENERGY",
    "NIFTYMEDIA", "NIFTYINFRA", "NIFTYCPSE", "NIFTYPSE",
    "NIFTYSERV", "NIFTYCONSR", "NIFTYDIVOPPS", "NIFTYHEALTHCARE",
    "NIFTYOILGAS", "NIFTYMICROCAP250", "GIFTNIFTY",
}


# ─── Scanner ──────────────────────────────────────────────────────────────────────
class Scanner:
    def __init__(self, config: Config, api: OpenAlgoClient):
        self.config = config
        self.api = api
        self._sym_map: Dict[str, str] = {}   # base → near-month FUT symbol (e.g. "RELIANCE28MAY26FUT")

    def fetch_fno_symbols(self) -> List[str]:
        """
        Dynamically fetch all F&O eligible NSE equity symbols from OpenAlgo's
        master contract. Queries NFO FUT instruments, strips the expiry+FUT
        suffix from each symbol, deduplicates, and excludes index futures.
        Falls back to EQUITY_UNIVERSE if the API is unavailable.

        Expiry format in DB: "28-MAY-26"  (DD-MMM-YY)
        Symbol format:       "RELIANCE28MAY26FUT"
        Extracted base:      "RELIANCE"
        """
        logger.info("Fetching F&O symbol universe from OpenAlgo master contract...")
        instruments = self.api.instruments(exchange="NFO")
        if not instruments:
            logger.warning("Master contract unavailable — falling back to built-in universe")
            return list(EQUITY_UNIVERSE)

        # near[base] = (expiry_date, fut_symbol) — keep only the nearest-expiry contract
        near: Dict[str, tuple] = {}
        for inst in instruments:
            if inst.get("instrumenttype") != "FUT":
                continue
            sym    = inst.get("symbol", "")
            expiry = inst.get("expiry", "")          # e.g. "28-MAY-26"
            if not sym.endswith("FUT") or not expiry:
                continue
            # "28-MAY-26" → "28MAY26" (strip dashes, matches OpenAlgo symbol suffix)
            suffix = expiry.replace("-", "")          # "28MAY26"
            expected_tail = suffix + "FUT"            # "28MAY26FUT"
            if sym.endswith(expected_tail):
                base = sym[: -len(expected_tail)]     # "RELIANCE"
                if base and base not in _INDEX_FUTURES:
                    try:
                        exp_dt = datetime.strptime(expiry, "%d-%b-%y").date()
                    except ValueError:
                        exp_dt = date.max
                    if base not in near or exp_dt < near[base][0]:
                        near[base] = (exp_dt, sym)

        if not near:
            logger.warning("No FUT base symbols extracted — falling back to built-in universe")
            return list(EQUITY_UNIVERSE)

        self._sym_map = {b: sym for b, (_, sym) in near.items()}
        result = sorted(near.keys())
        logger.info(f"F&O universe: {len(result)} equity symbols fetched from master contract")
        return result

    def _oi_buildup(self, base: str, direction: str) -> bool:
        """
        ChartInk OI F&O filter — degrades gracefully when OI data is absent.
          BUY  (long buildup):  OI up + price up   → smart money accumulating longs.
          SELL (short buildup): OI up + price down  → smart money accumulating shorts.
        """
        fut_sym = self._sym_map.get(base)
        if not fut_sym:
            return True
        hist_end   = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        hist_start = (date.today() - timedelta(days=5)).strftime("%Y-%m-%d")
        df = self.api.history(fut_sym, "D", hist_start, hist_end, exchange="NFO")
        if df is None or len(df) < 2 or "oi" not in df.columns:
            return True  # OI column absent for this broker — don't penalise
        oi_up      = bool(df["oi"].iloc[-1]    > df["oi"].iloc[-2])
        price_up   = bool(df["close"].iloc[-1] > df["close"].iloc[-2])
        price_down = bool(df["close"].iloc[-1] < df["close"].iloc[-2])
        return (oi_up and price_up) if direction == "BUY" else (oi_up and price_down)

    def scan(self) -> List[ScannedStock]:
        # Use yesterday as end date — today's incomplete candle during the scan
        # window would corrupt EMA20 and RVOL calculations.
        hist_end   = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        hist_start = (date.today() - timedelta(days=51)).strftime("%Y-%m-%d")
        qualified: List[ScannedStock] = []

        universe = self.fetch_fno_symbols()
        logger.info(f"Scanning {len(universe)} NSE F&O equity stocks")
        for base in universe:
            try:
                df = self.api.history(base, "D", hist_start, hist_end, exchange="NSE")
                if df is None or len(df) < 30:
                    logger.debug(f"Skip {base}: insufficient data ({len(df) if df is not None else 0} bars)")
                    continue

                stock = self._evaluate(base, df)
                if stock:
                    qualified.append(stock)
                    logger.info(f"✓ {base} {stock.direction} | score={stock.score:.3f}")
            except Exception as e:
                logger.warning(f"Error scanning {base}: {e}")

        qualified.sort(key=lambda s: s.score, reverse=True)

        # ChartInk OI F&O filter — long buildup for BUY, short buildup for SELL
        oi_confirmed: List[ScannedStock] = []
        for s in qualified:
            if self._oi_buildup(s.base, s.direction):
                oi_confirmed.append(s)
            else:
                logger.debug(f"Drop {s.base}: OI {s.direction} buildup not confirmed")
        qualified = oi_confirmed

        selected = qualified[: self.config.max_trades]
        logger.info(
            f"Scan done: {len(qualified)} qualified (OI-filtered) → top {len(selected)}: "
            f"{[(s.base, s.direction) for s in selected]}"
        )
        return selected

    def _evaluate(self, base: str, df: pd.DataFrame) -> Optional[ScannedStock]:
        """
        Two-filter pre-market screen:
          1. EMA20 trend  — daily close above/below the 20-day EMA sets direction.
          2. RVOL spike   — yesterday's volume must exceed the 20-day avg by rvol_threshold.
        Stocks are ranked by RVOL so the highest-volume movers get slots first.
        """
        close = cast(pd.Series, df["close"])
        vol   = cast(pd.Series, df["volume"])

        ema20 = TA.ema(close, 20)
        if pd.isna(ema20.iloc[-1]):
            return None

        vol_avg20 = vol.rolling(20).mean()
        if pd.isna(vol_avg20.iloc[-1]) or vol_avg20.iloc[-1] == 0:
            return None

        rvol = vol.iloc[-1] / vol_avg20.iloc[-1]
        if rvol < self.config.rvol_threshold:
            return None

        c = close.iloc[-1]
        e = ema20.iloc[-1]

        if c > e:
            direction = "BUY"
        elif c < e:
            direction = "SELL"
        else:
            return None

        return ScannedStock(base=base, score=rvol, direction=direction,
                            prev_close=float(close.iloc[-1]))

    def capture_first_candle(self, stock: ScannedStock) -> bool:
        today = date.today().strftime("%Y-%m-%d")
        df = self.api.history(stock.symbol, "15m", today, today, exchange="NSE")
        if df is None or df.empty:
            logger.warning(f"No 15m data for {stock.base}")
            return False

        morning = df.between_time("09:15", "09:29")
        if morning.empty:
            return False

        row = morning.iloc[0]

        # Gap filter: skip if today's open is more than 2% away from yesterday's close.
        # Gap stocks have erratic ORB behaviour — the range is distorted by the gap itself.
        if stock.prev_close > 0:
            gap_pct = abs(row["open"] - stock.prev_close) / stock.prev_close * 100
            if gap_pct > 2.0:
                logger.info(
                    f"Skip {stock.base}: gap {gap_pct:.1f}% > 2% "
                    f"(open={row['open']:.2f} prev_close={stock.prev_close:.2f})"
                )
                return False

        stock.fc_open  = row["open"]
        stock.fc_high  = row["high"]
        stock.fc_low   = row["low"]
        stock.fc_range = row["high"] - row["low"]
        stock.vwap     = (row["high"] + row["low"] + row["close"]) / 3  # seed VWAP from first candle
        stock.candle_captured = True
        logger.info(
            f"First candle {stock.base} [{stock.direction}]: "
            f"O={row['open']:.2f} H={row['high']:.2f} "
            f"L={row['low']:.2f} C={row['close']:.2f} range={stock.fc_range:.2f} "
            f"seed_VWAP={stock.vwap:.2f}"
        )
        return True


# ─── Main Orchestrator ────────────────────────────────────────────────────────────
class AutomatedTrader:
    def __init__(self, config: Config):
        self.config = config
        self.api = OpenAlgoClient(config)
        self.risk = RiskManager(config)
        self.scanner = Scanner(config, self.api)
        self.trade_mgr = TradeManager(config, self.api, self.risk)
        self.selected: List[ScannedStock] = []
        self._scan_done = False
        self._candles_done = False
        self._last_5m_bar: Dict[str, datetime] = {}  # symbol → last seen 5m bar open time

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%H:%M")

    @staticmethod
    def _after(t: str) -> bool:
        return AutomatedTrader._now() >= t

    @staticmethod
    def _between(start: str, end: str) -> bool:
        n = AutomatedTrader._now()
        return start <= n <= end

    def _late_start_recovery(self):
        """Run scan and candle capture immediately if the bot starts mid-session."""
        now = self._now()
        if not self._scan_done and now >= self.config.scan_end:
            logger.warning(f"Started after scan window ({now}) — running scan now")
            self.selected = self.scanner.scan()
            self._scan_done = True

        if self._scan_done and not self._candles_done and now >= self.config.entry_start:
            logger.warning(f"Started after candle window ({now}) — capturing first candles now")
            for s in self.selected:
                self.scanner.capture_first_candle(s)
            self._candles_done = True
            logger.info("Late-start recovery complete — entering monitoring loop")

    def _check_entries(self):
        """
        Two-phase entry logic — runs every 5-minute bar close.

        Phase 1 (breakout confirmation):
            Wait for a 5m bar to CLOSE above fc_high (BUY) or below fc_low (SELL).
            This confirms the ORB is valid before looking for a pullback.

        Phase 2 (pullback-continuation entry):
            After breakout is confirmed, wait for price to retreat toward VWAP.
            Enter when:
              BUY  — LTP is above VWAP but within 1% of fc_high (retest / pullback zone)
              SELL — LTP is below VWAP but within 1% of fc_low  (retest / pullback zone)
            VWAP is recomputed from all closed 5m bars on the same fetch.
        """
        today  = date.today().strftime("%Y-%m-%d")
        now_ts = datetime.now()
        cutoff = now_ts - timedelta(minutes=5)

        for stock in self.selected:
            if not stock.candle_captured:
                continue
            if not self.trade_mgr.can_enter(stock.symbol):
                continue

            last = self._last_5m_bar.get(stock.symbol)
            if last is not None and now_ts < last + timedelta(minutes=5):
                continue

            df5 = self.api.history(stock.symbol, "5m", today, today, exchange="NSE")
            if df5 is None or df5.empty:
                continue

            closed = df5[df5.index < cutoff]
            if closed.empty:
                continue

            latest = closed.iloc[-1]
            bar_ts = latest.name
            if hasattr(bar_ts, "to_pydatetime"):
                bar_ts = bar_ts.to_pydatetime().replace(tzinfo=None)
            self._last_5m_bar[stock.symbol] = bar_ts

            is_long = stock.direction == "BUY"

            # Update VWAP from all closed 5m bars (typical price × volume, cumulative)
            typical    = (closed["high"] + closed["low"] + closed["close"]) / 3
            total_vol  = closed["volume"].sum()
            if total_vol > 0:
                stock.vwap = float((typical * closed["volume"]).sum() / total_vol)

            # ── Phase 1: ORB breakout confirmation ───────────────────────────────
            if not stock.breakout_confirmed:
                ref   = stock.fc_high if is_long else stock.fc_low
                close = latest["close"]

                broke = (
                    (is_long     and close > stock.fc_high) or
                    (not is_long and close < stock.fc_low)
                )

                if broke:
                    # Measure how far beyond the ORB level the 5m bar closed.
                    beyond_pct = (
                        (close - stock.fc_high) / stock.fc_high  # BUY: positive = above high
                        if is_long else
                        (stock.fc_low - close)  / stock.fc_low   # SELL: positive = below low
                    )

                    if beyond_pct <= 0.002:
                        # Tight breakout (≤ 0.20%): enter immediately — the move is too small
                        # to expect a meaningful pullback, so we buy/sell close to the ORB level.
                        ltp = self.api.quote(stock.symbol, self.config.exchange)
                        if ltp is not None:
                            label = "high" if is_long else "low"
                            logger.info(
                                f"Quick entry {stock.base} [{stock.direction}]: "
                                f"5m close {close:.2f} just {beyond_pct*100:.2f}% above "
                                f"fc_{label}={ref:.2f}"
                            )
                            self.trade_mgr.enter(stock, ltp)
                    else:
                        # Strong breakout (> 0.20%): confirm and wait for the pullback retest.
                        stock.breakout_confirmed = True
                        label = "BREAKOUT" if is_long else "BREAKDOWN"
                        logger.info(
                            f"ORB {label} {stock.base}: 5m close {close:.2f} "
                            f"vs {'high' if is_long else 'low'} {ref:.2f} "
                            f"({beyond_pct*100:.2f}%) | VWAP={stock.vwap:.2f}"
                        )

                continue   # never enter on the breakout bar via Phase 2 — handled above

            # ── Phase 2: pullback to VWAP — enter as continuation ────────────────
            if stock.vwap <= 0:
                continue
            ltp = self.api.quote(stock.symbol, self.config.exchange)
            if ltp is None:
                continue

            if is_long:
                # Retest zone: price pulled back to within ±1% of fc_high AND is above VWAP.
                # "Within 1% of fc_high" ensures it's a genuine retest of the breakout level,
                # not just any price above VWAP (which could be far from the ORB level).
                in_zone = (
                    stock.fc_high * 0.99 <= ltp <= stock.fc_high * 1.01
                    and ltp >= stock.vwap
                )
            else:
                # Retest zone: price bounced back to within ±1% of fc_low AND is below VWAP.
                # Without the fc_low cap, a partially-recovered breakdown (price back above
                # fc_low toward VWAP) would incorrectly trigger a short entry.
                in_zone = (
                    stock.fc_low * 0.99 <= ltp <= stock.fc_low * 1.01
                    and ltp <= stock.vwap
                )

            if in_zone:
                ref_price = stock.fc_high if is_long else stock.fc_low
                logger.info(
                    f"Pullback entry {stock.base} [{stock.direction}]: "
                    f"LTP={ltp:.2f} VWAP={stock.vwap:.2f} "
                    f"{'fc_high' if is_long else 'fc_low'}={ref_price:.2f} "
                    f"target=+{0.60 * stock.fc_range:.2f}pts"
                )
                self.trade_mgr.enter(stock, ltp)

    def _ping(self) -> bool:
        try:
            resp = requests.get(f"{self.config.openalgo_url}/api/docs", timeout=5)
            return resp.status_code < 500
        except Exception:
            return False

    def run(self):
        logger.info("=" * 60)
        logger.info("  Automated Intraday Equity Trader — starting")
        logger.info(f"  Exchange      : NSE (Cash Equity)")
        logger.info(f"  Total capital : Rs.{self.config.total_capital:,.0f}")
        logger.info(f"  Per trade     : Rs.{self.config.capital_per_trade:,.0f} deployed")
        logger.info(f"  Max trades    : {self.config.max_trades}")
        logger.info("=" * 60)

        if not self._ping():
            logger.error("Cannot reach OpenAlgo server — is it running?")
            sys.exit(1)

        self._late_start_recovery()

        try:
            while True:
                # ── 9:15–9:30  Scan universe ──────────────────────────────────
                if (
                    not self._scan_done
                    and self._between(self.config.scan_start, self.config.scan_end)
                ):
                    self.selected = self.scanner.scan()
                    self._scan_done = True

                # ── After 9:30  Capture / retry first 15-min candle ──────────
                # Retries every loop tick until all captured or 9:35 is reached.
                if (
                    self._scan_done
                    and not self._candles_done
                    and self._after(self.config.scan_end)
                ):
                    for s in self.selected:
                        if not s.candle_captured:
                            self.scanner.capture_first_candle(s)
                    all_captured = all(s.candle_captured for s in self.selected)
                    if all_captured or self._after(self.config.entry_start):
                        self._candles_done = True
                        n = sum(1 for s in self.selected if s.candle_captured)
                        logger.info(
                            f"Candle capture complete — {n}/{len(self.selected)} ready"
                        )

                # ── 9:35–14:20  Pullback-continuation entries ─────────────────
                if (
                    self._candles_done
                    and self._between(self.config.entry_start, self.config.no_new_trade_after)
                    and not self.risk.halted
                ):
                    self._check_entries()

                # ── Always monitor open trades ────────────────────────────────
                if self._candles_done and self.trade_mgr.active:
                    self.trade_mgr.monitor()

                # ── 15:10  Square off ─────────────────────────────────────────
                if self._after(self.config.square_off_time):
                    self.trade_mgr.square_off_all()
                    logger.info("=" * 60)
                    logger.info(f"Day complete | Daily PnL Rs.{self.risk.daily_pnl:,.2f}")
                    logger.info(f"Trades taken : {self.risk.trades_today}")
                    logger.info("=" * 60)
                    break

                time.sleep(self.config.monitor_interval_sec)

        except KeyboardInterrupt:
            logger.info("Interrupted — squaring off open positions...")
            self.trade_mgr.square_off_all()
        except Exception:
            logger.exception("Unexpected error — squaring off for safety")
            self.trade_mgr.square_off_all()
            raise


# ─── Entry Point ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    cfg = Config()

    mode = "PAPER" if cfg.paper_trade else "LIVE"
    print(f"\n  Mode          : {mode}")
    print(f"  Exchange      : NSE Cash Equity")
    print(f"  Capital/trade : Rs.{cfg.capital_per_trade:,.0f}")
    if cfg.paper_trade:
        print("  Paper mode ON — no real orders will be sent.")
        print("  Set PAPER_TRADE=false to go live.\n")

    AutomatedTrader(cfg).run()
