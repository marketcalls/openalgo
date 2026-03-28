from __future__ import annotations

from pathlib import Path

import pandas as pd


def build_promotion_report(
    candidate_metrics: pd.DataFrame,
    active_metrics: pd.DataFrame,
    output_path: str | Path,
) -> Path:
    candidate = candidate_metrics.copy()
    candidate["bundle_state"] = "candidate"
    active = active_metrics.copy()
    active["bundle_state"] = "active"
    report = pd.concat([candidate, active], ignore_index=True)
    report["recommended_action"] = report["bundle_state"].map(
        {"candidate": "review_for_promotion", "active": "keep_or_replace"}
    )
    destination = Path(output_path)
    report.to_csv(destination, index=False)
    return destination
