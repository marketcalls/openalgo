from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def infer_feature_columns(df: pd.DataFrame, excluded: set[str] | None = None) -> list[str]:
    excluded = excluded or set()
    return [column for column in df.columns if column not in excluded]


def save_feature_schema(path: str | Path, feature_columns: list[str]) -> None:
    Path(path).write_text(json.dumps({"feature_columns": feature_columns}, indent=2), encoding="utf-8")


def load_feature_schema(path: str | Path) -> list[str]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return list(payload["feature_columns"])


def align_feature_frame(df: pd.DataFrame, feature_columns: list[str]) -> pd.DataFrame:
    aligned = df.copy()
    for column in feature_columns:
        if column not in aligned.columns:
            aligned[column] = 0.0
    return aligned[feature_columns].fillna(0.0)
