#!/usr/bin/env python3
"""
Automated Intraday NSE Equity Trading System
Strategy : 15-min Opening Range Breakout (ORB) — Long and Short
Backend  : OpenAlgo REST API → Dhan broker

Risk model:
  - 1 trade deploys Rs. 1 Lakh of capital
  - Max loss per trade = 1% of Rs. 1 Lakh = Rs. 1,000
  - Quantity = min(1000 / risk_pts_per_share, 1,00,000 / entry_price)
"""

import logging
import os
import sys
import time
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
    api_key: str = os.getenv("OPENALGO_API_KEY", "ebb5694faae8023439faf2d4b84fd46872d9cc04df67034549c39b0b7de630d3")

    # Paper trading — no real orders sent, uses live market data for signals
    paper_trade: bool = os.getenv("PAPER_TRADE", "true").lower() != "false"

    # Capital
    # total_capital is used only for daily drawdown calculation.
    # Each trade independently deploys capital_per_trade with risk_per_trade_rs max loss.
    total_capital: float = float(os.getenv("TRADING_CAPITAL", "600000"))  # Rs. 6 Lakh (6 × 1L)
    capital_per_trade: float = 100000   # Rs. 1 Lakh deployed per trade
    risk_per_trade_rs: float = 1000     # Rs. 1,000 max loss per trade (1% of 1L)

    max_trades: int = 6
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

    # Supertrend parameters
    st_period: int = 7
    st_multiplier: float = 3.0

    # Trailing SL (activates after partial booking or 1:1 for single-share trades)
    trailing_trigger_pct: float = 0.25      # trigger every 25% of risk
    trailing_step_pct: float = 0.25         # step SL by 25% of risk

    # API call interval during active trading
    monitor_interval_sec: int = 5


# ─── NSE Equity Universe ──────────────────────────────────────────────────────────
# Large-cap liquid NSE stocks suitable for intraday ORB
EQUITY_UNIVERSE: List[str] = [
    "RELIANCE",   "TCS",        "HDFCBANK",   "INFY",       "ICICIBANK",
    "KOTAKBANK",  "HINDUNILVR", "SBIN",        "BAJFINANCE", "BHARTIARTL",
    "AXISBANK",   "ASIANPAINT", "MARUTI",      "SUNPHARMA",  "TATAMOTORS",
    "WIPRO",      "ULTRACEMCO", "HCLTECH",     "TITAN",      "TECHM",
    "ONGC",       "NTPC",       "COALINDIA",   "ITC",        "POWERGRID",
    "M&M",        "JSWSTEEL",   "HINDALCO",    "NESTLEIND",  "CIPLA",
    "DRREDDY",    "APOLLOHOSP", "ADANIENT",    "ADANIPORTS", "BAJAJ-AUTO",
    "BPCL",       "BRITANNIA",  "DIVISLAB",    "EICHERMOT",  "GRASIM",
    "HEROMOTOCO", "INDUSINDBK", "LTIM",        "LT",         "TATACONSUM",
    "TATASTEEL",  "TRENT",      "UPL",         "VEDL",       "ZOMATO",
    "BANKBARODA", "CANBK",      "PNB",         "IRCTC",      "PIDILITIND",
    "DMART",      "SHREECEM",   "NAUKRI",      "SBILIFE",
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
                logger.error(f"API error {endpoint}: {e}")
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
        if resp.get("status") != "success" or not resp.get("data"):
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
            r = self.session.get(url, params=params, timeout=30)
            r.raise_for_status()
            return r.json()
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


# ─── Technical Indicators (pure-pandas, no extra deps) ───────────────────────────
class TA:
    @staticmethod
    def ema(s: pd.Series, n: int) -> pd.Series:
        return cast(pd.Series, s.ewm(span=n, adjust=False).mean())

    @staticmethod
    def rsi(s: pd.Series, n: int = 14) -> pd.Series:
        d = s.diff()
        gain = cast(pd.Series, d.clip(lower=0).ewm(com=n - 1, adjust=False).mean())
        loss = cast(pd.Series, (-d.clip(upper=0)).ewm(com=n - 1, adjust=False).mean())
        return cast(pd.Series, 100 - 100 / (1 + gain / loss))

    @staticmethod
    def macd_hist(s: pd.Series, fast=12, slow=26, sig=9) -> pd.Series:
        m = s.ewm(span=fast, adjust=False).mean() - s.ewm(span=slow, adjust=False).mean()
        return m - m.ewm(span=sig, adjust=False).mean()

    @staticmethod
    def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
        h, l, pc = df["high"], df["low"], df["close"].shift()
        tr = cast(pd.Series, pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1))
        return cast(pd.Series, tr.ewm(com=n - 1, adjust=False).mean())

    @staticmethod
    def stoch_k(df: pd.DataFrame, k_period: int = 14) -> pd.Series:
        """Fast Stochastic %K (raw, unsmoothed). Returns 50 when price range is zero."""
        lo  = df["low"].rolling(k_period).min()
        hi  = df["high"].rolling(k_period).max()
        rng = hi - lo
        return cast(pd.Series, (df["close"] - lo).div(rng).mul(100).where(rng != 0, 50.0))

    @staticmethod
    def supertrend(df: pd.DataFrame, n: int = 7, m: float = 3.0) -> pd.Series:
        mid = (df["high"] + df["low"]) / 2
        atr = TA.atr(df, n)
        upper = mid + m * atr
        lower = mid - m * atr
        st = pd.Series(index=df.index, dtype=float)
        dir_ = pd.Series(1, index=df.index, dtype=int)

        for i in range(1, len(df)):
            if df["close"].iat[i - 1] <= upper.iat[i - 1]:
                upper.iat[i] = min(upper.iat[i], upper.iat[i - 1])
            if df["close"].iat[i - 1] >= lower.iat[i - 1]:
                lower.iat[i] = max(lower.iat[i], lower.iat[i - 1])

            if df["close"].iat[i] > upper.iat[i]:
                dir_.iat[i] = 1
            elif df["close"].iat[i] < lower.iat[i]:
                dir_.iat[i] = -1
            else:
                dir_.iat[i] = dir_.iat[i - 1]

            st.iat[i] = lower.iat[i] if dir_.iat[i] == 1 else upper.iat[i]

        return st


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
    partial_done: bool = False
    trail_sl: float = 0.0
    peak_profit_pts: float = 0.0
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

    def calc_qty(self, entry: float, sl: float) -> int:
        """
        Qty = min(
            floor(risk_per_trade_rs / risk_pts),   ← risk limit: max Rs.1,000 loss
            floor(capital_per_trade  / entry)       ← capital limit: max Rs.1L deployed
        )
        Minimum 1 share.
        """
        risk_pts = abs(entry - sl)
        if risk_pts <= 0:
            return 0
        risk_qty    = int(self.config.risk_per_trade_rs / risk_pts)
        capital_qty = int(self.config.capital_per_trade / entry)
        return max(1, min(risk_qty, capital_qty))

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

        if is_long:
            sl = stock.fc_high - (stock.fc_high - stock.fc_open) * 0.60
            if sl >= entry:
                logger.warning(f"Skip {stock.base}: SL {sl:.2f} >= entry {entry:.2f}")
                return False
            target = entry + (entry - sl)
        else:
            sl = stock.fc_low + (stock.fc_open - stock.fc_low) * 0.60
            if sl <= entry:
                logger.warning(f"Skip {stock.base}: SL {sl:.2f} <= entry {entry:.2f}")
                return False
            target = entry - (sl - entry)

        qty = self.risk.calc_qty(entry, sl)
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
        close_action = "SELL" if is_long else "BUY"

        # ── SL check ──────────────────────────────────────────────────────────
        sl_hit = (ltp <= trade.trail_sl) if is_long else (ltp >= trade.trail_sl)
        if sl_hit:
            self._close(trade, ltp, "SL")
            return

        profit_pts = (ltp - trade.entry) if is_long else (trade.entry - ltp)

        # ── Partial booking at 1:1 ────────────────────────────────────────────
        target_hit = (ltp >= trade.target) if is_long else (ltp <= trade.target)
        if not trade.partial_done and target_hit:
            half = trade.qty // 2           # equity: shares, no lot rounding
            if half > 0:
                self.api.place_order(trade.symbol, close_action, half)
                trade.remaining -= half
                pnl_so_far = half * profit_pts
                trade.realized_pnl += pnl_so_far
                logger.info(
                    f"Partial {close_action} {trade.base} | qty={half} @ {ltp:.2f} "
                    f"partial PnL=Rs.{pnl_so_far:,.2f}"
                )
            # Activate trailing SL even for qty=1 (cannot split, but trail still runs)
            trade.partial_done = True
            trade.trail_sl = trade.entry
            logger.info(f"Breakeven SL {trade.base} -> {trade.trail_sl:.2f}")

        # ── Trail SL for remaining quantity ───────────────────────────────────
        if trade.partial_done and trade.remaining > 0:
            # Measure excess profit ABOVE the 1:1 target so that at exactly
            # 1:1 (where partial booking fires) excess=0, steps=0, new_sl=entry.
            # Without this, steps=4 and new_sl jumps to the target price,
            # causing an immediate close on the same tick as partial booking.
            excess = profit_pts - trade.risk_pts
            if excess > trade.peak_profit_pts:
                trade.peak_profit_pts = excess

            trig  = trade.risk_pts * self.config.trailing_trigger_pct
            step  = trade.risk_pts * self.config.trailing_step_pct
            steps = int(trade.peak_profit_pts / trig) if trig > 0 else 0

            if is_long:
                new_sl = trade.entry + steps * step
                if new_sl > trade.trail_sl:
                    trade.trail_sl = new_sl
                    logger.info(f"Trail SL {trade.base} -> {new_sl:.2f}")
                if ltp <= trade.trail_sl:
                    self._close(trade, ltp, "TRAIL_SL")
            else:
                new_sl = trade.entry - steps * step
                if new_sl < trade.trail_sl:
                    trade.trail_sl = new_sl
                    logger.info(f"Trail SL {trade.base} -> {new_sl:.2f}")
                if ltp >= trade.trail_sl:
                    self._close(trade, ltp, "TRAIL_SL")

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

    def _oi_long_buildup(self, base: str) -> bool:
        """
        ChartInk 'OI F&O Buy': OI and price both rose yesterday vs the prior day.
        Returns True (pass) when OI data is unavailable so the filter degrades gracefully.
        """
        fut_sym = self._sym_map.get(base)
        if not fut_sym:
            return True
        hist_end   = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        hist_start = (date.today() - timedelta(days=5)).strftime("%Y-%m-%d")
        df = self.api.history(fut_sym, "D", hist_start, hist_end, exchange="NFO")
        if df is None or len(df) < 2 or "oi" not in df.columns:
            return True  # OI column absent for this broker — don't penalise
        return bool(
            df["oi"].iloc[-1] > df["oi"].iloc[-2] and
            df["close"].iloc[-1] > df["close"].iloc[-2]
        )

    def scan(self) -> List[ScannedStock]:
        # Use yesterday as end date — today's incomplete daily candle during the
        # 9:15–9:30 scan window corrupts EMA20, RSI, Supertrend, and MACD values.
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

        # ChartInk OI F&O Buy filter — applied to BUY signals only
        oi_confirmed: List[ScannedStock] = []
        for s in qualified:
            if s.direction == "SELL" or self._oi_long_buildup(s.base):
                oi_confirmed.append(s)
            else:
                logger.debug(f"Drop {s.base}: OI long buildup not confirmed")
        qualified = oi_confirmed

        selected = qualified[: self.config.max_trades]
        logger.info(
            f"Scan done: {len(qualified)} qualified (OI-filtered) → top {len(selected)}: "
            f"{[(s.base, s.direction) for s in selected]}"
        )
        return selected

    def _evaluate(self, base: str, df: pd.DataFrame) -> Optional[ScannedStock]:
        close = cast(pd.Series, df["close"])
        vol   = cast(pd.Series, df["volume"])

        ema20 = TA.ema(close, 20)
        st    = TA.supertrend(df, self.config.st_period, self.config.st_multiplier)
        if pd.isna(st.iloc[-1]):
            return None

        vol_sma10 = cast(pd.Series, vol.rolling(10).mean())
        if vol.iloc[-1] <= vol_sma10.iloc[-1] * 2:
            return None

        rsi_val  = TA.rsi(close, 14).iloc[-1]
        hist_val = TA.macd_hist(close).iloc[-1]
        rel_vol  = vol.iloc[-1] / vol_sma10.iloc[-1]

        stk      = TA.stoch_k(df, 14)
        stk_prev = stk.iloc[-2]
        stk_curr = stk.iloc[-1]

        c   = close.iloc[-1]
        s   = st.iloc[-1]
        e   = ema20.iloc[-1]
        c20 = close.iloc[-20]

        # ── LONG setup (ChartInk: Fast Stoch crossed above 90) ────────────────
        # stk_prev < 90 <= stk_curr  ↔  "crossed above 90" crossover condition
        if c > e and c > s and 55 <= rsi_val <= 70 and hist_val > 0 and stk_prev < 90 <= stk_curr:
            direction = "BUY"
            price_str = (c - c20) / c20 * 100
            trend_str = (c - s) / c * 100
            rsi_norm  = (rsi_val - 55) / 15

        # ── SHORT setup ───────────────────────────────────────────────────────
        elif c < e and c < s and 30 <= rsi_val <= 45 and hist_val < 0:
            direction = "SELL"
            price_str = (c20 - c) / c20 * 100
            trend_str = (s - c) / c * 100
            rsi_norm  = (45 - rsi_val) / 15

        else:
            return None

        score = (rel_vol / 5) * 0.35 + (price_str / 20) * 0.25 + (trend_str / 5) * 0.25 + rsi_norm * 0.15
        return ScannedStock(base=base, score=score, direction=direction)

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
        stock.fc_open  = row["open"]
        stock.fc_high  = row["high"]
        stock.fc_low   = row["low"]
        stock.fc_range = row["high"] - row["low"]
        stock.candle_captured = True
        logger.info(
            f"First candle {stock.base} [{stock.direction}]: "
            f"O={row['open']:.2f} H={row['high']:.2f} "
            f"L={row['low']:.2f} C={row['close']:.2f} range={stock.fc_range:.2f}"
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

    def _check_breakouts(self):
        today = date.today().strftime("%Y-%m-%d")
        for stock in self.selected:
            if not stock.candle_captured:
                continue
            if not self.trade_mgr.can_enter(stock.symbol):
                continue

            df5 = self.api.history(stock.symbol, "5m", today, today, exchange="NSE")
            if df5 is None or df5.empty:
                continue

            now_ts = datetime.now()
            cutoff = now_ts - timedelta(minutes=5)
            closed = df5[df5.index < cutoff]
            if closed.empty:
                continue

            latest  = closed.iloc[-1]
            is_long = stock.direction == "BUY"
            triggered = (
                (is_long     and latest["close"] > stock.fc_high) or
                (not is_long and latest["close"] < stock.fc_low)
            )

            if triggered:
                label     = "BREAKOUT" if is_long else "BREAKDOWN"
                ref       = stock.fc_high if is_long else stock.fc_low
                ref_label = "high" if is_long else "low"
                logger.info(
                    f"{label} {stock.base}: 5m close {latest['close']:.2f} "
                    f"vs 15m {ref_label} {ref:.2f}"
                )
                ltp = self.api.quote(stock.symbol, self.config.exchange)
                if ltp:
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
        logger.info(f"  Max loss/trade: Rs.{self.config.risk_per_trade_rs:,.0f}")
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

                # ── After 9:30  Capture first 15-min candle ───────────────────
                if (
                    self._scan_done
                    and not self._candles_done
                    and self._after(self.config.scan_end)
                ):
                    for s in self.selected:
                        self.scanner.capture_first_candle(s)
                    self._candles_done = True
                    logger.info("First candles captured — waiting for 9:35 entry window")

                # ── 9:35–14:20  Breakout / Breakdown entries ──────────────────
                if (
                    self._candles_done
                    and self._between(self.config.entry_start, self.config.no_new_trade_after)
                    and not self.risk.halted
                ):
                    self._check_breakouts()

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
    print(f"  Max loss/trade: Rs.{cfg.risk_per_trade_rs:,.0f}")
    if cfg.paper_trade:
        print("  Paper mode ON — no real orders will be sent.")
        print("  Set PAPER_TRADE=false to go live.\n")

    AutomatedTrader(cfg).run()
