from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
CONFIG_ROOT = PROJECT_ROOT / "configs"
EXAMPLES_ROOT = PROJECT_ROOT / "examples"
DEFAULT_STRATEGY_ROOT = Path(r"D:\test1")
DEFAULT_RELIANCE_ROOT = Path(r"D:\TV_proj\output\reliance_timeframes")
DEFAULT_ARTIFACTS_ROOT = PROJECT_ROOT.parent / "artifacts_template"

CANONICAL_COLUMNS = [
    "symbol",
    "timeframe",
    "timestamp",
    "datetime",
    "open",
    "high",
    "low",
    "close",
    "volume",
]

INTRADAY_SESSION_START = "09:15"
INTRADAY_SESSION_END = "15:30"
INDIA_TIMEZONE = "Asia/Kolkata"

DEFAULT_REGIME_LABELS = ("bear", "flat", "bull")
