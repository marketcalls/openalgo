from __future__ import annotations

from pathlib import Path

import pandas as pd


def read_tabular_file(path: str | Path, sheet_name: str | int | None = 0) -> pd.DataFrame:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        return pd.read_excel(file_path, sheet_name=sheet_name)
    if suffix == ".csv":
        return pd.read_csv(file_path)
    if suffix == ".parquet":
        return pd.read_parquet(file_path)
    raise ValueError(f"Unsupported input format: {file_path}")


def write_columnar(df: pd.DataFrame, output_path: str | Path) -> Path:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        df.to_parquet(destination, index=False)
        return destination
    except Exception:
        fallback = destination.with_suffix(".csv")
        df.to_csv(fallback, index=False)
        return fallback
