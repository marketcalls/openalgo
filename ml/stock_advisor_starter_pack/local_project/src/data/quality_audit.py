from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from core.constants import CANONICAL_COLUMNS


@dataclass(slots=True)
class AuditReport:
    row_count: int
    duplicate_rows: int
    duplicate_timestamps: int
    missing_required_columns: list[str]
    null_counts: dict[str, int]
    zero_volume_rows: int

    def to_dict(self) -> dict[str, object]:
        return {
            "row_count": self.row_count,
            "duplicate_rows": self.duplicate_rows,
            "duplicate_timestamps": self.duplicate_timestamps,
            "missing_required_columns": self.missing_required_columns,
            "null_counts": self.null_counts,
            "zero_volume_rows": self.zero_volume_rows,
        }


def audit_market_data(df: pd.DataFrame) -> AuditReport:
    missing = [column for column in CANONICAL_COLUMNS if column not in df.columns]
    duplicate_rows = int(df.duplicated().sum())
    duplicate_timestamps = int(df.duplicated(subset=["symbol", "timeframe", "timestamp"]).sum()) if {
        "symbol",
        "timeframe",
        "timestamp",
    }.issubset(df.columns) else 0
    null_counts = {column: int(df[column].isna().sum()) for column in df.columns}
    zero_volume = int((df["volume"] == 0).sum()) if "volume" in df.columns else 0
    return AuditReport(
        row_count=len(df),
        duplicate_rows=duplicate_rows,
        duplicate_timestamps=duplicate_timestamps,
        missing_required_columns=missing,
        null_counts=null_counts,
        zero_volume_rows=zero_volume,
    )
