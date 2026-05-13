#!/usr/bin/env python3
"""
Sector-Aware Intraday ORB Trader
Strategy : 15-min Opening Range Breakout + Sector Strength + VWAP + Gap Filter
Backend  : OpenAlgo REST API → Dhan broker

Risk model:
  - 1 trade deploys Rs. 1 Lakh of capital
  - Max loss per trade = 1% of Rs. 1 Lakh = Rs. 1,000
  - Quantity = min(1000 / risk_pts, 1,00,000 / entry_price)

Sector logic:
  - Bullish sector  → allow only BUY trades from that sector
  - Bearish sector  → allow only SELL trades from that sector
  - Neutral sector  → skip all stocks in that sector
  - No sector map   → fall back to daily indicator direction
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

try:
    from dotenv import load_dotenv
    load_dotenv()  # load .env so OPENALGO_API_KEY and PAPER_TRADE are picked up
except ImportError:
    pass  # python-dotenv not installed — rely on shell environment

# ─── Logging ──────────────────────────────────────────────────────────────────
try:
    if isinstance(sys.stdout, TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except AttributeError:
    pass

_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
_fh  = logging.FileHandler("sector_trader.log", encoding="utf-8")
_fh.setFormatter(_fmt)
_ch  = logging.StreamHandler(sys.stdout)
_ch.setFormatter(_fmt)
logging.basicConfig(level=logging.INFO, handlers=[_fh, _ch])
logger = logging.getLogger(__name__)


# ─── Config ───────────────────────────────────────────────────────────────────
@dataclass
class Config:
    openalgo_url: str  = os.getenv("OPENALGO_URL", "http://127.0.0.1:5000")
    api_key: str       = os.getenv("OPENALGO_API_KEY", "")

    paper_trade: bool  = os.getenv("PAPER_TRADE", "true").lower() != "false"

    total_capital: float    = float(os.getenv("TRADING_CAPITAL", "1000000"))  # Rs. 10 Lakh
    capital_per_trade: float = 100_000   # Rs. 1 Lakh per trade
    risk_per_trade_rs: float = 1_000     # Rs. 1,000 max loss

    max_trades: int              = 10
    max_consecutive_losses: int  = 3
    max_daily_drawdown_pct: float = 0.03  # 3% of total_capital

    product: str  = "MIS"
    exchange: str = "NSE"

    scan_start: str          = "09:15"
    scan_end: str            = "09:30"
    entry_start: str         = "09:35"
    no_new_trade_after: str  = "14:20"
    square_off_time: str     = "15:00"   # strategy doc: 3 PM

    st_period: int       = 7
    st_multiplier: float = 3.0

    trailing_trigger_pct: float = 0.25
    trailing_step_pct: float    = 0.25

    monitor_interval_sec: int = 5

    # Sector / filter params
    gap_filter_pct: float = 2.0          # skip if opening gap > ±2%
    sector_rs_lookback: int = 5          # days for relative-strength calculation
    # False = scan ALL F&O stocks; unmapped stocks use both-direction indicator logic.
    # True  = only stocks explicitly in STOCK_SECTOR (mapped to a tracked sector).
    require_sector_filter: bool = False


# ─── Sector Universe ──────────────────────────────────────────────────────────
# NSE_INDEX symbols used by OpenAlgo / Dhan
SECTOR_INDICES: Dict[str, Dict[str, str]] = {
    "NIFTY BANK":              {"symbol": "BANKNIFTY",          "exchange": "NSE_INDEX"},
    "NIFTY IT":                {"symbol": "NIFTYIT",            "exchange": "NSE_INDEX"},
    "NIFTY AUTO":              {"symbol": "NIFTYAUTO",          "exchange": "NSE_INDEX"},
    "NIFTY PHARMA":            {"symbol": "NIFTYPHARMA",        "exchange": "NSE_INDEX"},
    "NIFTY FMCG":              {"symbol": "NIFTYFMCG",          "exchange": "NSE_INDEX"},
    "NIFTY METAL":             {"symbol": "NIFTYMETAL",         "exchange": "NSE_INDEX"},
    "NIFTY ENERGY":            {"symbol": "NIFTYENERGY",        "exchange": "NSE_INDEX"},
    "NIFTY REALTY":            {"symbol": "NIFTYREALTY",        "exchange": "NSE_INDEX"},
    "NIFTY MEDIA":             {"symbol": "NIFTYMEDIA",         "exchange": "NSE_INDEX"},
    "NIFTY INFRA":             {"symbol": "NIFTYINFRA",         "exchange": "NSE_INDEX"},
    "NIFTY PSE":               {"symbol": "NIFTYPSE",           "exchange": "NSE_INDEX"},
    "NIFTY HEALTHCARE":        {"symbol": "NIFTY HEALTHCARE",   "exchange": "NSE_INDEX"},
    "NIFTY OIL GAS":           {"symbol": "NIFTY OIL AND GAS",  "exchange": "NSE_INDEX"},
    "NIFTY FIN SVC":           {"symbol": "FINNIFTY",           "exchange": "NSE_INDEX"},
    "NIFTY CONSUMER DURABLES": {"symbol": "NIFTY CONSR DURBL",  "exchange": "NSE_INDEX"},
    "NIFTY CHEMICALS":         {"symbol": "NIFTY CHEMICALS",    "exchange": "NSE_INDEX"},
}

# Stock → sector name (STOCK_SECTOR)
# Stocks not listed here are still scanned when require_sector_filter=False;
# they get "BOTH" direction treatment based on daily indicators alone.
STOCK_SECTOR: Dict[str, str] = {
    # Banking (15)
    "HDFCBANK":   "NIFTY BANK",  "ICICIBANK":  "NIFTY BANK",  "KOTAKBANK":  "NIFTY BANK",
    "AXISBANK":   "NIFTY BANK",  "SBIN":       "NIFTY BANK",  "BANKBARODA": "NIFTY BANK",
    "INDUSINDBK": "NIFTY BANK",  "CANBK":      "NIFTY BANK",  "PNB":        "NIFTY BANK",
    "FEDERALBNK": "NIFTY BANK",  "IDFCFIRSTB": "NIFTY BANK",  "AUBANK":     "NIFTY BANK",
    "BANDHANBNK": "NIFTY BANK",  "RBLBANK":    "NIFTY BANK",  "YESBANK":    "NIFTY BANK",
    # IT (14)
    "TCS":        "NIFTY IT",    "INFY":       "NIFTY IT",    "WIPRO":      "NIFTY IT",
    "HCLTECH":    "NIFTY IT",    "TECHM":      "NIFTY IT",    "LTIM":       "NIFTY IT",
    "NAUKRI":     "NIFTY IT",    "ZOMATO":     "NIFTY IT",    "COFORGE":    "NIFTY IT",
    "PERSISTENT": "NIFTY IT",    "MPHASIS":    "NIFTY IT",    "OFSS":       "NIFTY IT",
    "LTTS":       "NIFTY IT",    "KPITTECH":   "NIFTY IT",
    # Auto (17)
    "MARUTI":     "NIFTY AUTO",  "TATAMOTORS": "NIFTY AUTO",  "BAJAJ-AUTO": "NIFTY AUTO",
    "HEROMOTOCO": "NIFTY AUTO",  "EICHERMOT":  "NIFTY AUTO",  "M&M":        "NIFTY AUTO",
    "TVSMOTOR":   "NIFTY AUTO",  "MOTHERSON":  "NIFTY AUTO",  "ASHOKLEY":   "NIFTY AUTO",
    "SONACOMS":   "NIFTY AUTO",  "BHARATFORG": "NIFTY AUTO",  "TIINDIA":    "NIFTY AUTO",
    "EXIDEIND":   "NIFTY AUTO",  "UNOMINDA":   "NIFTY AUTO",  "BOSCHLTD":   "NIFTY AUTO",
    "APOLLOTYRE": "NIFTY AUTO",  "BALKRISIND": "NIFTY AUTO",
    # Pharma (21)
    "SUNPHARMA":  "NIFTY PHARMA","CIPLA":      "NIFTY PHARMA","DRREDDY":    "NIFTY PHARMA",
    "DIVISLAB":   "NIFTY PHARMA","BIOCON":     "NIFTY PHARMA","LUPIN":      "NIFTY PHARMA",
    "LAURUSLABS": "NIFTY PHARMA","AUROPHARMA": "NIFTY PHARMA","GLENMARK":   "NIFTY PHARMA",
    "WOCKPHARMA": "NIFTY PHARMA","JBCHEPHARM": "NIFTY PHARMA","MANKIND":    "NIFTY PHARMA",
    "TORNTPHARM": "NIFTY PHARMA","PPLPHARMA":  "NIFTY PHARMA","IPCALAB":    "NIFTY PHARMA",
    "AJANTPHARM": "NIFTY PHARMA","ZYDUSLIFE":  "NIFTY PHARMA","ABBOTINDIA": "NIFTY PHARMA",
    "ALKEM":      "NIFTY PHARMA","GLAND":      "NIFTY PHARMA","NATCOPHARM": "NIFTY PHARMA",
    # FMCG (18)
    "HINDUNILVR": "NIFTY FMCG",  "ITC":        "NIFTY FMCG",  "BRITANNIA":  "NIFTY FMCG",
    "NESTLEIND":  "NIFTY FMCG",  "TATACONSUM": "NIFTY FMCG",  "DMART":      "NIFTY FMCG",
    "TRENT":      "NIFTY FMCG",  "ASIANPAINT": "NIFTY FMCG",  "GODREJCP":   "NIFTY FMCG",
    "VBL":        "NIFTY FMCG",  "MARICO":     "NIFTY FMCG",  "RADICO":     "NIFTY FMCG",
    "PATANJALI":  "NIFTY FMCG",  "DABUR":      "NIFTY FMCG",  "UNITDSPR":   "NIFTY FMCG",
    "COLPAL":     "NIFTY FMCG",  "UBL":        "NIFTY FMCG",  "EMAMILTD":   "NIFTY FMCG",
    # Metal (15)
    "JSWSTEEL":   "NIFTY METAL", "HINDALCO":   "NIFTY METAL", "TATASTEEL":  "NIFTY METAL",
    "VEDL":       "NIFTY METAL", "HINDZINC":   "NIFTY METAL", "HINDCOPPER": "NIFTY METAL",
    "SAIL":       "NIFTY METAL", "NATIONALUM": "NIFTY METAL", "JINDALSTEL": "NIFTY METAL",
    "NMDC":       "NIFTY METAL", "LLOYDSME":   "NIFTY METAL", "APLAPOLLO":  "NIFTY METAL",
    "WELCORP":    "NIFTY METAL", "JSL":        "NIFTY METAL", "MOIL":       "NIFTY METAL",
    # Oil & Gas (7)  — tracks NIFTY OIL AND GAS index
    "RELIANCE":   "NIFTY OIL GAS","ONGC":      "NIFTY OIL GAS","BPCL":      "NIFTY OIL GAS",
    "COALINDIA":  "NIFTY OIL GAS","IOC":       "NIFTY OIL GAS","HINDPETRO": "NIFTY OIL GAS",
    "GAIL":       "NIFTY OIL GAS",
    # Power & Renewable Energy (7)  — tracks NIFTY ENERGY index
    "TATAPOWER":  "NIFTY ENERGY","TORNTPOWER": "NIFTY ENERGY","ADANIGREEN": "NIFTY ENERGY",
    "JSWENERGY":  "NIFTY ENERGY","CESC":       "NIFTY ENERGY","NHPC":       "NIFTY ENERGY",
    "SJVN":       "NIFTY ENERGY",
    # Infra / Capital Goods + Cement + Telecom (28)
    "NTPC":       "NIFTY INFRA", "POWERGRID":  "NIFTY INFRA", "LT":         "NIFTY INFRA",
    "ADANIPORTS": "NIFTY INFRA", "ADANIENT":   "NIFTY INFRA", "ULTRACEMCO": "NIFTY INFRA",
    "GRASIM":     "NIFTY INFRA", "SHREECEM":   "NIFTY INFRA", "AMBUJACEM":  "NIFTY INFRA",
    "DALBHARAT":  "NIFTY INFRA", "ACC":        "NIFTY INFRA", "BIRLACORPN": "NIFTY INFRA",
    "JKCEMENT":   "NIFTY INFRA", "RAMCOCEM":   "NIFTY INFRA", "JSWCEMENT":  "NIFTY INFRA",
    "NUVOCO":     "NIFTY INFRA", "INDIACEM":   "NIFTY INFRA", "JKLAKSHMI":  "NIFTY INFRA",
    "PRSMJOHNSN": "NIFTY INFRA", "ORIENTCEM":  "NIFTY INFRA", "STARCEMENT": "NIFTY INFRA",
    "ABB":        "NIFTY INFRA", "SIEMENS":    "NIFTY INFRA", "CGPOWER":    "NIFTY INFRA",
    "BHEL":       "NIFTY INFRA", "GMRINFRA":   "NIFTY INFRA", "BHARTIARTL": "NIFTY INFRA",
    # Fin Services (12)
    "BAJFINANCE": "NIFTY FIN SVC","SBILIFE":   "NIFTY FIN SVC","BAJAJFINSV": "NIFTY FIN SVC",
    "HDFCLIFE":   "NIFTY FIN SVC","ICICIPRULI":"NIFTY FIN SVC","SBICARD":    "NIFTY FIN SVC",
    "CHOLAFIN":   "NIFTY FIN SVC","M&MFIN":    "NIFTY FIN SVC","LICHSGFIN":  "NIFTY FIN SVC",
    "MFSL":       "NIFTY FIN SVC","ABCAPITAL":  "NIFTY FIN SVC","PNBHOUSING": "NIFTY FIN SVC",
    # Chemicals (20)
    "HSCL":       "NIFTY CHEMICALS","UPL":     "NIFTY CHEMICALS","PIDILITIND":"NIFTY CHEMICALS",
    "TATACHEM":   "NIFTY CHEMICALS","SOLARINDS":"NIFTY CHEMICALS","SRF":      "NIFTY CHEMICALS",
    "COROMANDEL": "NIFTY CHEMICALS","NAVINFLUOR":"NIFTY CHEMICALS","DEEPAKNTR":"NIFTY CHEMICALS",
    "PIIND":      "NIFTY CHEMICALS","AARTIIND": "NIFTY CHEMICALS","DEEPAKFERT":"NIFTY CHEMICALS",
    "ATUL":       "NIFTY CHEMICALS","FLUOROCHEM":"NIFTY CHEMICALS","LINDEINDIA":"NIFTY CHEMICALS",
    "SWANCORP":   "NIFTY CHEMICALS","PCBL":     "NIFTY CHEMICALS","CHAMBLFERT":"NIFTY CHEMICALS",
    "SUMICHEM":   "NIFTY CHEMICALS","BAYERCROP":"NIFTY CHEMICALS",
    # Consumer Durables (14)
    "DIXON":      "NIFTY CONSUMER DURABLES","TITAN":     "NIFTY CONSUMER DURABLES",
    "KALYANKJIL": "NIFTY CONSUMER DURABLES","AMBER":     "NIFTY CONSUMER DURABLES",
    "BLUESTARCO": "NIFTY CONSUMER DURABLES","CROMPTON":  "NIFTY CONSUMER DURABLES",
    "VOLTAS":     "NIFTY CONSUMER DURABLES","HAVELLS":   "NIFTY CONSUMER DURABLES",
    "LGEINDIA":   "NIFTY CONSUMER DURABLES","PGEL":      "NIFTY CONSUMER DURABLES",
    "KAJARIACER": "NIFTY CONSUMER DURABLES","WHIRLPOOL": "NIFTY CONSUMER DURABLES",
    "BATAINDIA":  "NIFTY CONSUMER DURABLES","NYKAA":     "NIFTY CONSUMER DURABLES",
    # Realty (10)
    "DLF":        "NIFTY REALTY", "ANANTRAJ":  "NIFTY REALTY", "LODHA":      "NIFTY REALTY",
    "GODREJPROP": "NIFTY REALTY", "OBEROIRLTY":"NIFTY REALTY", "PRESTIGE":   "NIFTY REALTY",
    "PHOENIXLTD": "NIFTY REALTY", "ABREL":     "NIFTY REALTY", "BRIGADE":    "NIFTY REALTY",
    "SOBHA":      "NIFTY REALTY",
    # PSE / Government (8)
    "IRCTC":      "NIFTY PSE",   "HAL":        "NIFTY PSE",   "BEL":        "NIFTY PSE",
    "RVNL":       "NIFTY PSE",   "IRFC":       "NIFTY PSE",   "PFC":        "NIFTY PSE",
    "REC":        "NIFTY PSE",   "LICI":       "NIFTY PSE",
    # Healthcare Services (4)
    "APOLLOHOSP": "NIFTY HEALTHCARE","MAXHEALTH": "NIFTY HEALTHCARE",
    "FORTIS":     "NIFTY HEALTHCARE","SYNGENE":   "NIFTY HEALTHCARE",
    # Media (3)
    "PVRINOX":    "NIFTY MEDIA", "SUNTVNETWORK":"NIFTY MEDIA", "ZEEL":       "NIFTY MEDIA",
}


# ─── OpenAlgo REST Client ─────────────────────────────────────────────────────
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

    def _get(self, endpoint: str, params: dict) -> dict:
        params = {**params, "apikey": self.config.api_key}
        url = f"{self.config.openalgo_url}{endpoint}"
        try:
            # Clear Content-Type for GET requests — Flask rejects application/json with empty body
            r = self.session.get(url, params=params, timeout=30,
                                 headers={"Content-Type": None})
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error(f"GET {endpoint} failed: {e}")
            return {"status": "error"}

    def history(self, symbol: str, interval: str, start_date: str, end_date: str,
                exchange: str = "NSE") -> Optional[pd.DataFrame]:
        resp = self._post("/api/v1/history", {
            "symbol": symbol, "exchange": exchange,
            "interval": interval, "start_date": start_date, "end_date": end_date,
        })
        if resp.get("status") != "success" or not resp.get("data"):
            return None
        df = pd.DataFrame(resp["data"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=False)
        df = df.set_index("timestamp")
        df = cast(pd.DataFrame, df[["open", "high", "low", "close", "volume"]].astype(float))
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

    def place_order(self, symbol: str, action: str, quantity: int,
                    price_type: str = "MARKET", price: float = 0.0,
                    trigger_price: float = 0.0) -> Optional[str]:
        if self.config.paper_trade:
            trig = f" trigger={trigger_price:.2f}" if trigger_price else ""
            logger.info(f"[PAPER] {action} {quantity} {symbol} type={price_type}{trig}")
            return "paper-" + str(int(time.time() * 1000))
        payload = {
            "symbol": symbol, "exchange": self.config.exchange,
            "action": action, "quantity": quantity, "product": self.config.product,
            "pricetype": price_type, "price": price, "trigger_price": trigger_price,
            "disclosed_quantity": 0, "strategy": "SectorORB",
        }
        resp = self._post("/api/v1/placeorder", payload)
        if resp.get("status") == "success":
            oid = resp.get("orderid") or (resp.get("data") or {}).get("orderid")
            logger.info(f"Order OK | {action} {quantity} {symbol} | id={oid}")
            return str(oid) if oid else "placed"
        logger.error(f"Order FAILED | {symbol} {action} {quantity} | {resp}")
        return None

    def instruments(self, exchange: str = "NFO") -> List[dict]:
        resp = self._get("/api/v1/instruments", {"exchange": exchange, "format": "json"})
        return resp.get("data", []) if resp.get("status") == "success" else []

    def positions(self) -> List[dict]:
        resp = self._post("/api/v1/positions", {})
        return resp.get("data", []) if resp.get("status") == "success" else []


# ─── Technical Indicators ─────────────────────────────────────────────────────
class TA:
    @staticmethod
    def ema(s: pd.Series, n: int) -> pd.Series:
        return cast(pd.Series, s.ewm(span=n, adjust=False).mean())

    @staticmethod
    def rsi(s: pd.Series, n: int = 14) -> pd.Series:
        d    = s.diff()
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
        tr = cast(pd.Series,
                  pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1))
        return cast(pd.Series, tr.ewm(com=n - 1, adjust=False).mean())

    @staticmethod
    def supertrend(df: pd.DataFrame, n: int = 7, m: float = 3.0) -> pd.Series:
        mid   = (df["high"] + df["low"]) / 2
        atr   = TA.atr(df, n)
        upper = mid + m * atr
        lower = mid - m * atr
        st    = pd.Series(index=df.index, dtype=float)
        dir_  = pd.Series(1, index=df.index, dtype=int)
        for i in range(1, len(df)):
            if df["close"].iat[i - 1] <= upper.iat[i - 1]:
                upper.iat[i] = min(upper.iat[i], upper.iat[i - 1])
            if df["close"].iat[i - 1] >= lower.iat[i - 1]:
                lower.iat[i] = max(lower.iat[i], lower.iat[i - 1])
            if   df["close"].iat[i] > upper.iat[i]: dir_.iat[i] = 1
            elif df["close"].iat[i] < lower.iat[i]: dir_.iat[i] = -1
            else:                                    dir_.iat[i] = dir_.iat[i - 1]
            st.iat[i] = lower.iat[i] if dir_.iat[i] == 1 else upper.iat[i]
        return st


# ─── VWAP helper ──────────────────────────────────────────────────────────────
def compute_vwap(df: Optional[pd.DataFrame]) -> Optional[float]:
    """Intraday VWAP from 5-min OHLCV bars (typical price weighted by volume)."""
    if df is None or df.empty or df["volume"].sum() == 0:
        return None
    tp   = (df["high"] + df["low"] + df["close"]) / 3
    vwap = (tp * df["volume"]).cumsum() / df["volume"].cumsum()
    val  = vwap.iloc[-1]
    return float(val) if not pd.isna(val) else None


# ─── Sector Analyzer ──────────────────────────────────────────────────────────
class SectorAnalyzer:
    """
    Classifies each NSE sector as BULLISH / BEARISH / NEUTRAL using:
      1. Daily close vs EMA20 of the sector index
      2. 5-day relative strength of the sector vs NIFTY 50

    Called once during the 9:15 scan window; result cached for the session.
    """

    NIFTY_SYMBOL   = "NIFTY"
    NIFTY_EXCHANGE = "NSE_INDEX"

    def __init__(self, api: OpenAlgoClient, config: Config):
        self.api     = api
        self.config  = config
        self.sectors: Dict[str, str] = {}   # sector → BULLISH|BEARISH|NEUTRAL

    def analyze(self) -> Dict[str, str]:
        lb       = self.config.sector_rs_lookback
        hist_end = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        hist_st  = (date.today() - timedelta(days=35)).strftime("%Y-%m-%d")

        nifty_df = self.api.history(self.NIFTY_SYMBOL, "D", hist_st, hist_end,
                                    exchange=self.NIFTY_EXCHANGE)
        nifty_rs = 0.0
        if nifty_df is not None and len(nifty_df) > lb:
            nc       = nifty_df["close"]
            nifty_rs = float((nc.iloc[-1] / nc.iloc[-(lb + 1)] - 1) * 100)

        for name, info in SECTOR_INDICES.items():
            try:
                df = self.api.history(info["symbol"], "D", hist_st, hist_end,
                                      exchange=info["exchange"])
                if df is None or len(df) < 21:
                    self.sectors[name] = "NEUTRAL"
                    continue

                close = df["close"]
                ema20 = float(TA.ema(close, 20).iloc[-1])
                last  = float(close.iloc[-1])
                sect_rs = float((close.iloc[-1] / close.iloc[-(lb + 1)] - 1) * 100) \
                          if len(close) > lb else 0.0
                rs_diff = sect_rs - nifty_rs

                if   last > ema20 and rs_diff > 0: direction = "BULLISH"
                elif last < ema20 and rs_diff < 0: direction = "BEARISH"
                else:                               direction = "NEUTRAL"

                self.sectors[name] = direction
                logger.info(
                    f"Sector {name}: {direction} | "
                    f"close={last:.0f} EMA20={ema20:.0f} RS_diff={rs_diff:+.2f}%"
                )
            except Exception as e:
                logger.warning(f"Sector {name} error: {e}")
                self.sectors[name] = "NEUTRAL"

        bullish = [k for k, v in self.sectors.items() if v == "BULLISH"]
        bearish = [k for k, v in self.sectors.items() if v == "BEARISH"]
        logger.info(f"Sectors BULLISH={bullish}")
        logger.info(f"Sectors BEARISH={bearish}")
        return self.sectors

    def allowed_direction(self, stock: str) -> Optional[str]:
        """
        Return "BUY", "SELL", "BOTH", or None (skip).
        - Stocks with no sector mapping: "BOTH" if require_sector_filter=False, else None.
        """
        sector = STOCK_SECTOR.get(stock)
        if sector is None:
            return None if self.config.require_sector_filter else "BOTH"
        direction = self.sectors.get(sector, "NEUTRAL")
        if   direction == "BULLISH": return "BUY"
        elif direction == "BEARISH": return "SELL"
        return None   # NEUTRAL → skip


# ─── Data Classes ─────────────────────────────────────────────────────────────
@dataclass
class ScannedStock:
    base: str
    score: float
    direction: str = "BUY"
    sector: str    = ""
    fc_open: float  = 0.0
    fc_high: float  = 0.0
    fc_low: float   = 0.0
    fc_range: float = 0.0
    candle_captured: bool = False
    prev_close: float = 0.0   # filled during candle capture for gap filter

    @property
    def symbol(self) -> str:
        return self.base


@dataclass
class Trade:
    base: str
    entry: float
    sl: float
    target: float
    qty: int
    remaining: int
    direction: str = "BUY"
    partial_done: bool = False
    trail_sl: float   = 0.0
    peak_profit_pts: float = 0.0
    realized_pnl: float    = 0.0
    closed: bool           = False

    @property
    def symbol(self) -> str:
        return self.base

    @property
    def risk_pts(self) -> float:
        return abs(self.entry - self.sl)


# ─── Risk Manager ─────────────────────────────────────────────────────────────
class RiskManager:
    def __init__(self, config: Config):
        self.config = config
        self._start_capital    = config.total_capital
        self.trades_today      = 0
        self.consecutive_losses = 0
        self.daily_pnl         = 0.0
        self._halt_reason: str = ""

    @property
    def halted(self) -> bool:
        reason = ""
        if self.trades_today >= self.config.max_trades:
            reason = f"max trades reached ({self.trades_today})"
        elif self.consecutive_losses >= self.config.max_consecutive_losses:
            reason = f"{self.consecutive_losses} consecutive losses"
        else:
            dd = -self.daily_pnl / self._start_capital
            if dd >= self.config.max_daily_drawdown_pct:
                reason = f"{dd:.1%} daily drawdown breached"
        if reason:
            if reason != self._halt_reason:
                logger.warning(f"Trading halted — {reason}")
                self._halt_reason = reason
            return True
        self._halt_reason = ""
        return False

    def calc_qty(self, entry: float, sl: float) -> int:
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
            f"Daily Rs.{self.daily_pnl:,.2f} | Consec losses {self.consecutive_losses}"
        )


# ─── Trade Manager ────────────────────────────────────────────────────────────
class TradeManager:
    def __init__(self, config: Config, api: OpenAlgoClient, risk: RiskManager):
        self.config  = config
        self.api     = api
        self.risk    = risk
        self.active: Dict[str, Trade] = {}
        self.traded_symbols: set = set()

    def can_enter(self, symbol: str) -> bool:
        return (symbol not in self.traded_symbols
                and symbol not in self.active
                and not self.risk.halted)

    def enter(self, stock: ScannedStock, ltp: float, df5: Optional[pd.DataFrame]) -> bool:
        if not self.can_enter(stock.symbol):
            return False

        # VWAP filter — price must be on correct side of intraday VWAP
        vwap = compute_vwap(df5)
        if vwap is not None:
            above_vwap = ltp > vwap
            if stock.direction == "BUY"  and not above_vwap:
                logger.info(f"Skip {stock.base}: BUY but price {ltp:.2f} below VWAP {vwap:.2f}")
                return False
            if stock.direction == "SELL" and above_vwap:
                logger.info(f"Skip {stock.base}: SELL but price {ltp:.2f} above VWAP {vwap:.2f}")
                return False

        entry   = ltp
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
            logger.warning(f"Skip {stock.base}: zero qty")
            return False

        logger.info(
            f"ENTER {stock.direction} {stock.base} [{stock.sector}] | "
            f"entry={entry:.2f} SL={sl:.2f} target={target:.2f} qty={qty} "
            f"capital=Rs.{qty*entry:,.0f} risk=Rs.{qty*abs(entry-sl):,.0f}"
            + (f" VWAP={vwap:.2f}" if vwap else "")
        )

        oid = self.api.place_order(stock.symbol, stock.direction, qty)
        if not oid:
            self.traded_symbols.add(stock.symbol)
            return False

        self.active[stock.symbol] = Trade(
            base=stock.base, entry=entry, sl=sl, target=target,
            qty=qty, remaining=qty, direction=stock.direction, trail_sl=sl,
        )
        self.traded_symbols.add(stock.symbol)
        return True

    def monitor(self):
        for sym, trade in list(self.active.items()):
            if trade.closed:
                continue
            ltp = self.api.quote(sym, self.config.exchange)
            if ltp is not None:
                self._tick(trade, ltp)

    def _tick(self, trade: Trade, ltp: float):
        is_long      = trade.direction == "BUY"
        close_action = "SELL" if is_long else "BUY"

        sl_hit = (ltp <= trade.trail_sl) if is_long else (ltp >= trade.trail_sl)
        if sl_hit:
            self._close(trade, ltp, "SL")
            return

        profit_pts = (ltp - trade.entry) if is_long else (trade.entry - ltp)
        target_hit = (ltp >= trade.target) if is_long else (ltp <= trade.target)

        if not trade.partial_done and target_hit:
            half = trade.qty // 2
            if half > 0:
                self.api.place_order(trade.symbol, close_action, half)
                trade.remaining  -= half
                pnl_so_far        = half * profit_pts
                trade.realized_pnl += pnl_so_far
                logger.info(f"Partial {close_action} {trade.base} | qty={half} @ {ltp:.2f} | PnL Rs.{pnl_so_far:,.2f}")
            trade.partial_done = True
            trade.trail_sl     = trade.entry
            logger.info(f"Breakeven SL {trade.base} -> {trade.trail_sl:.2f}")

        if trade.partial_done and trade.remaining > 0:
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
            profit_pts          = (ltp - trade.entry) if trade.direction == "BUY" else (trade.entry - ltp)
            trade.realized_pnl += trade.remaining * profit_pts
        trade.closed = True
        logger.info(
            f"CLOSE [{reason}] {trade.base} | "
            f"entry={trade.entry:.2f} exit={ltp:.2f} PnL=Rs.{trade.realized_pnl:,.2f}"
        )
        self.risk.record(trade.realized_pnl)
        self.active.pop(trade.symbol, None)

    def square_off_all(self):
        logger.info(">> Square-off — closing all open positions")
        for sym, trade in list(self.active.items()):
            if not trade.closed:
                ltp = self.api.quote(sym, self.config.exchange) or trade.entry
                self._close(trade, ltp, "SQUAREOFF")


# ─── Scanner ──────────────────────────────────────────────────────────────────
_INDEX_FUTURES = {
    "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50",
    "SENSEX", "BANKEX", "NIFTYIT", "NIFTYAUTO", "NIFTYMETAL",
    "NIFTYPHARMA", "NIFTYFMCG", "NIFTYREALTY", "NIFTYENERGY",
    "NIFTYMEDIA", "NIFTYINFRA", "NIFTYCPSE", "NIFTYPSE",
    "NIFTYSERV", "NIFTYCONSR", "NIFTYDIVOPPS", "NIFTYHEALTHCARE",
    "NIFTYOILGAS", "NIFTYMICROCAP250", "GIFTNIFTY",
}


class Scanner:
    def __init__(self, config: Config, api: OpenAlgoClient,
                 sector_analyzer: SectorAnalyzer):
        self.config   = config
        self.api      = api
        self.sa       = sector_analyzer

    def fetch_universe(self) -> List[str]:
        logger.info("Fetching F&O universe from master contract...")
        instruments = self.api.instruments(exchange="NFO")
        if not instruments:
            logger.warning("Master contract unavailable — using built-in set")
            return sorted(STOCK_SECTOR.keys())

        bases: set = set()
        for inst in instruments:
            if inst.get("instrumenttype") != "FUT":
                continue
            sym    = inst.get("symbol", "")
            expiry = inst.get("expiry", "")
            if not sym.endswith("FUT") or not expiry:
                continue
            suffix = expiry.replace("-", "") + "FUT"
            if sym.endswith(suffix):
                base = sym[: -len(suffix)]
                if base and base not in _INDEX_FUTURES:
                    bases.add(base)

        result = sorted(bases) if bases else sorted(STOCK_SECTOR.keys())
        logger.info(f"Universe: {len(result)} F&O equity stocks")
        return result

    def scan(self) -> List[ScannedStock]:
        hist_end   = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        hist_start = (date.today() - timedelta(days=51)).strftime("%Y-%m-%d")
        qualified: List[ScannedStock] = []

        universe = self.fetch_universe()
        logger.info(f"Scanning {len(universe)} stocks with sector filter...")

        for base in universe:
            allowed = self.sa.allowed_direction(base)
            if allowed is None:
                continue   # NEUTRAL sector or not mapped → skip

            try:
                df = self.api.history(base, "D", hist_start, hist_end, exchange="NSE")
                if df is None or len(df) < 30:
                    continue
                stock = self._evaluate(base, df, allowed)
                if stock:
                    qualified.append(stock)
                    logger.info(f"✓ {base} {stock.direction} [{stock.sector}] score={stock.score:.3f}")
            except Exception as e:
                logger.warning(f"Error scanning {base}: {e}")

        qualified.sort(key=lambda s: s.score, reverse=True)
        selected = qualified[: self.config.max_trades]
        logger.info(
            f"Scan done: {len(qualified)} qualified → top {len(selected)}: "
            f"{[(s.base, s.direction) for s in selected]}"
        )
        return selected

    def _evaluate(self, base: str, df: pd.DataFrame,
                  allowed: str) -> Optional[ScannedStock]:
        """
        Evaluate stock using daily indicators; enforce sector-allowed direction.
        `allowed` is "BUY", "SELL", or "BOTH".
        """
        close    = cast(pd.Series, df["close"])
        vol      = cast(pd.Series, df["volume"])
        ema20    = TA.ema(close, 20)
        st       = TA.supertrend(df, self.config.st_period, self.config.st_multiplier)
        if pd.isna(st.iloc[-1]):
            return None

        vol_sma10 = cast(pd.Series, vol.rolling(10).mean())
        if vol.iloc[-1] <= vol_sma10.iloc[-1] * 2:
            return None   # relative volume < 2x

        rsi_val  = TA.rsi(close, 14).iloc[-1]
        hist_val = TA.macd_hist(close).iloc[-1]
        rel_vol  = vol.iloc[-1] / vol_sma10.iloc[-1]
        c, s, e  = close.iloc[-1], st.iloc[-1], ema20.iloc[-1]
        c20      = close.iloc[-20]

        direction: Optional[str] = None

        if c > e and c > s and 55 <= rsi_val <= 70 and hist_val > 0:
            if allowed in ("BUY", "BOTH"):
                direction  = "BUY"
                price_str  = (c - c20) / c20 * 100
                trend_str  = (c - s) / c * 100
                rsi_norm   = (rsi_val - 55) / 15

        if direction is None and c < e and c < s and 30 <= rsi_val <= 45 and hist_val < 0:
            if allowed in ("SELL", "BOTH"):
                direction  = "SELL"
                price_str  = (c20 - c) / c20 * 100
                trend_str  = (s - c) / c * 100
                rsi_norm   = (45 - rsi_val) / 15

        if direction is None:
            return None

        score = (rel_vol / 5) * 0.35 + (price_str / 20) * 0.25 + (trend_str / 5) * 0.25 + rsi_norm * 0.15
        sector = STOCK_SECTOR.get(base, "")
        return ScannedStock(base=base, score=score, direction=direction, sector=sector)

    def capture_first_candle(self, stock: ScannedStock) -> bool:
        today     = date.today().strftime("%Y-%m-%d")
        yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")

        # Gap filter — fetch previous close
        df_prev = self.api.history(stock.base, "D", yesterday, yesterday, exchange="NSE")
        if df_prev is not None and not df_prev.empty:
            stock.prev_close = float(df_prev["close"].iloc[-1])

        df = self.api.history(stock.symbol, "15m", today, today, exchange="NSE")
        if df is None or df.empty:
            logger.warning(f"No 15m data for {stock.base}")
            return False

        morning = df.between_time("09:15", "09:29")
        if morning.empty:
            return False

        row           = morning.iloc[0]
        today_open    = float(row["open"])

        # Apply gap filter
        if stock.prev_close > 0:
            gap_pct = abs(today_open - stock.prev_close) / stock.prev_close * 100
            if gap_pct > self.config.gap_filter_pct:
                logger.info(
                    f"Skip {stock.base}: opening gap {gap_pct:+.1f}% "
                    f"exceeds ±{self.config.gap_filter_pct}%"
                )
                return False   # candle_captured stays False → no trade

        stock.fc_open          = today_open
        stock.fc_high          = float(row["high"])
        stock.fc_low           = float(row["low"])
        stock.fc_range         = stock.fc_high - stock.fc_low
        stock.candle_captured  = True
        logger.info(
            f"First candle {stock.base} [{stock.direction}]: "
            f"O={stock.fc_open:.2f} H={stock.fc_high:.2f} "
            f"L={stock.fc_low:.2f} range={stock.fc_range:.2f}"
        )
        return True


# ─── Main Orchestrator ────────────────────────────────────────────────────────
class AutomatedTrader:
    def __init__(self, config: Config):
        self.config    = config
        self.api       = OpenAlgoClient(config)
        self.risk      = RiskManager(config)
        self.sa        = SectorAnalyzer(self.api, config)
        self.scanner   = Scanner(config, self.api, self.sa)
        self.trade_mgr = TradeManager(config, self.api, self.risk)
        self.selected: List[ScannedStock] = []
        self._scan_done    = False
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
        now = self._now()
        if not self._scan_done and now >= self.config.scan_end:
            logger.warning(f"Late start ({now}) — running sector + stock scan now")
            self.sa.analyze()
            self.selected     = self.scanner.scan()
            self._scan_done   = True
        if self._scan_done and not self._candles_done and now >= self.config.entry_start:
            logger.warning(f"Late start ({now}) — capturing first candles now")
            for s in self.selected:
                self.scanner.capture_first_candle(s)
            self._candles_done = True

    def _check_breakouts(self):
        today  = date.today().strftime("%Y-%m-%d")
        now_ts = datetime.now()
        cutoff = now_ts - timedelta(minutes=5)

        for stock in self.selected:
            if not stock.candle_captured:
                continue
            if not self.trade_mgr.can_enter(stock.symbol):
                continue

            # Skip fetch if the last 5m bar we acted on hasn't rolled yet.
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
            self._last_5m_bar[stock.symbol] = bar_ts  # cache so we skip until next bar

            is_long = stock.direction == "BUY"
            triggered = (
                (is_long     and latest["close"] > stock.fc_high) or
                (not is_long and latest["close"] < stock.fc_low)
            )
            if not triggered:
                continue

            label = "BREAKOUT" if is_long else "BREAKDOWN"
            ref   = stock.fc_high if is_long else stock.fc_low
            lbl   = "high" if is_long else "low"
            logger.info(
                f"{label} {stock.base}: 5m close {latest['close']:.2f} "
                f"vs 15m {lbl} {ref:.2f}"
            )
            ltp = self.api.quote(stock.symbol, self.config.exchange)
            if ltp:
                self.trade_mgr.enter(stock, ltp, df5)

    def _ping(self) -> bool:
        try:
            resp = requests.get(f"{self.config.openalgo_url}/api/docs", timeout=5)
            return resp.status_code < 500
        except Exception:
            return False

    def run(self):
        logger.info("=" * 60)
        logger.info("  Sector-Aware ORB Trader — starting")
        logger.info(f"  Capital/trade : Rs.{self.config.capital_per_trade:,.0f}")
        logger.info(f"  Max loss/trade: Rs.{self.config.risk_per_trade_rs:,.0f}")
        logger.info(f"  Max trades    : {self.config.max_trades}")
        logger.info(f"  Gap filter    : ±{self.config.gap_filter_pct}%")
        logger.info(f"  Sector filter : {self.config.require_sector_filter}")
        logger.info("=" * 60)

        if not self._ping():
            logger.error("Cannot reach OpenAlgo — is the server running?")
            sys.exit(1)

        self._late_start_recovery()

        try:
            while True:
                # ── 9:15–9:30  Sector analysis + stock scan ───────────────────
                if (not self._scan_done
                        and self._between(self.config.scan_start, self.config.scan_end)):
                    logger.info("Running sector analysis...")
                    self.sa.analyze()
                    self.selected   = self.scanner.scan()
                    self._scan_done = True

                # ── After 9:30  Capture first 15-min candle + gap filter ──────
                if (self._scan_done and not self._candles_done
                        and self._after(self.config.scan_end)):
                    for s in self.selected:
                        self.scanner.capture_first_candle(s)
                    self._candles_done = True
                    captured = sum(1 for s in self.selected if s.candle_captured)
                    logger.info(
                        f"First candles captured: {captured}/{len(self.selected)} "
                        f"passed gap filter — waiting for 9:35 entry"
                    )

                # ── 9:35–14:20  Breakout / Breakdown entries ──────────────────
                if (self._candles_done
                        and self._between(self.config.entry_start, self.config.no_new_trade_after)
                        and not self.risk.halted):
                    self._check_breakouts()

                # ── Always monitor open trades ────────────────────────────────
                if self._candles_done and self.trade_mgr.active:
                    self.trade_mgr.monitor()

                # ── 15:00  Square off ─────────────────────────────────────────
                if self._after(self.config.square_off_time):
                    self.trade_mgr.square_off_all()
                    logger.info("=" * 60)
                    logger.info(f"Day complete | Daily PnL Rs.{self.risk.daily_pnl:,.2f}")
                    logger.info(f"Trades taken : {self.risk.trades_today}")
                    logger.info("=" * 60)
                    break

                time.sleep(self.config.monitor_interval_sec)

        except KeyboardInterrupt:
            logger.info("Interrupted — squaring off...")
            self.trade_mgr.square_off_all()
        except Exception:
            logger.exception("Unexpected error — squaring off for safety")
            self.trade_mgr.square_off_all()
            raise


# ─── Entry Point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    cfg  = Config()
    mode = "PAPER" if cfg.paper_trade else "LIVE"
    print(f"\n  Mode          : {mode}")
    print(f"  Capital/trade : Rs.{cfg.capital_per_trade:,.0f}")
    print(f"  Max loss/trade: Rs.{cfg.risk_per_trade_rs:,.0f}")
    print(f"  Gap filter    : ±{cfg.gap_filter_pct}%")
    print(f"  Sector filter : {'ON (require mapping)' if cfg.require_sector_filter else 'OFF'}")
    if cfg.paper_trade:
        print("  Paper mode ON — no real orders sent.")
        print("  Set PAPER_TRADE=false to go live.\n")
    AutomatedTrader(cfg).run()
