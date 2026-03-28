"""
run_drift_check.py — CI-Compatible Feature Drift Check
=======================================================
Loads the last two saved feature versions from the feature store,
computes PSI per feature, and exits with code 1 if any feature
exceeds the severe drift threshold (PSI >= 0.25).

Usage:
    python scripts/run_drift_check.py [--store-root PATH] [--symbol RELIANCE]
                                      [--fail-on-severe] [--fail-on-moderate]

Exit codes:
    0 — stable or moderate drift (unless --fail-on-moderate is set)
    1 — severe drift detected (PSI >= 0.25 for any feature), or no data
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from core.constants import DEFAULT_ARTIFACTS_ROOT
from features.feature_store import list_versions, load_features
from monitoring.drift_detector import (
    PSI_MODERATE,
    PSI_STABLE,
    PSI_WARN,
    detect_feature_drift,
    summarise_psi_results,
)

DEFAULT_STORE_ROOT = DEFAULT_ARTIFACTS_ROOT / "feature_store"


def main() -> None:
    parser = argparse.ArgumentParser(description="Feature drift check via PSI")
    parser.add_argument("--store-root", type=Path, default=DEFAULT_STORE_ROOT)
    parser.add_argument("--symbol", default="RELIANCE")
    parser.add_argument(
        "--fail-on-severe", action="store_true",
        help="Exit 1 when any feature PSI >= 0.25 (default: warn only)",
    )
    parser.add_argument(
        "--fail-on-moderate", action="store_true",
        help="Exit 1 when any feature PSI >= 0.10",
    )
    args = parser.parse_args()

    versions = list_versions(args.symbol, args.store_root)
    if len(versions) < 2:
        print(
            f"[DRIFT CHECK] Only {len(versions)} version(s) available for {args.symbol} — "
            "need at least 2 to compare. Skipping."
        )
        sys.exit(0)

    reference_version = versions[-2]
    current_version   = versions[-1]
    print(f"[DRIFT CHECK] {args.symbol}: reference={reference_version!r}  current={current_version!r}")

    reference_df = load_features(args.symbol, reference_version, args.store_root, validate=False)
    current_df   = load_features(args.symbol, current_version,   args.store_root, validate=False)

    feature_cols = [
        c for c in reference_df.columns
        if c in current_df.columns and reference_df[c].dtype.kind in "fiu"
    ]

    psi_results = detect_feature_drift(reference_df, current_df, feature_cols)

    if not psi_results:
        print("[DRIFT CHECK] No numeric feature columns to compare.")
        sys.exit(0)

    # ── Print table ───────────────────────────────────────────────────────────
    print(f"\n{'Feature':<30}  {'PSI':>8}  Status")
    print("-" * 55)
    for feature, psi in sorted(psi_results.items(), key=lambda x: -x[1]):
        if psi >= PSI_WARN:
            status = "SEVERE ⚠"
        elif psi >= PSI_MODERATE:
            status = "MODERATE"
        elif psi >= PSI_STABLE:
            status = "low"
        else:
            status = "stable"
        print(f"  {feature:<28}  {psi:>8.4f}  {status}")

    severity, severe_features = summarise_psi_results(psi_results)
    max_psi = max(psi_results.values())

    print(f"\n[DRIFT CHECK] Overall severity: {severity.upper()}  (max PSI={max_psi:.4f})")

    if severe_features:
        print(f"  Severe features: {severe_features}")

    # ── Exit code logic ───────────────────────────────────────────────────────
    if args.fail_on_moderate and max_psi >= PSI_MODERATE:
        print("[DRIFT CHECK] FAILED — moderate drift threshold exceeded.")
        sys.exit(1)

    if (args.fail_on_severe or True) and severity == "severe":
        # Default: always fail CI on severe drift
        print("[DRIFT CHECK] FAILED — severe drift (PSI >= 0.25). Retrain required.")
        sys.exit(1)

    print("[DRIFT CHECK] PASSED.")
    sys.exit(0)


if __name__ == "__main__":
    main()
