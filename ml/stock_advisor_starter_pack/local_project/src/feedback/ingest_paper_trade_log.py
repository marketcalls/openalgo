from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.interfaces import PaperTradeRecord


def load_paper_trade_log(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path)


def parse_paper_trade_records(path: str | Path) -> list[PaperTradeRecord]:
    frame = load_paper_trade_log(path)
    return [PaperTradeRecord(**row) for row in frame.to_dict(orient="records")]


def append_feedback_log(source_path: str | Path, target_path: str | Path) -> Path:
    source = load_paper_trade_log(source_path)
    target = Path(target_path)
    if target.exists():
        existing = pd.read_csv(target)
        merged = pd.concat([existing, source], ignore_index=True).drop_duplicates()
    else:
        merged = source.copy()
    merged.to_csv(target, index=False)
    return target
