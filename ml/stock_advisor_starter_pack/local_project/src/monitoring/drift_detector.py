"""
drift_detector.py — PSI Feature Drift Detection
=================================================
Population Stability Index (PSI) for detecting distribution shift between
a reference feature set and a current (production) feature set.

Critical implementation detail: both reference and current distributions
are binned using *identical* bin edges derived from the combined min/max,
so PSI values are comparable across calls.

PSI thresholds (industry standard):
    < 0.10  — stable, no action needed
    0.10–0.20 — moderate drift, monitor
    0.20–0.25 — significant drift, investigate
    >= 0.25 — severe drift, trigger CI alert / retrain

Usage:
    from monitoring.drift_detector import compute_psi, detect_feature_drift

    psi = compute_psi(reference_series, current_series)
    results = detect_feature_drift(reference_df, current_df, feature_cols)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# PSI threshold constants
PSI_STABLE    = 0.10
PSI_MODERATE  = 0.20
PSI_WARN      = 0.25   # triggers CI failure in run_drift_check.py


def compute_psi(
    reference: pd.Series,
    current: pd.Series,
    bins: int = 10,
) -> float:
    """Compute Population Stability Index between reference and current distributions.

    Uses identical bin edges derived from the global min/max of both series
    to ensure comparability.  An epsilon smoothing term prevents log(0).

    Parameters
    ----------
    reference:
        Baseline distribution (e.g. training data feature column).
    current:
        Current distribution (e.g. recent production data feature column).
    bins:
        Number of histogram bins (default 10).

    Returns
    -------
    PSI value in [0, ∞).  Values >= 0.25 indicate severe drift.
    """
    ref = pd.to_numeric(reference, errors="coerce").dropna()
    cur = pd.to_numeric(current, errors="coerce").dropna()

    if ref.empty or cur.empty:
        return 0.0

    epsilon = 1e-10

    # CRITICAL: use identical bin edges from combined range
    global_min = min(float(ref.min()), float(cur.min()))
    global_max = max(float(ref.max()), float(cur.max()))

    if global_min == global_max:
        # Constant feature — no drift possible
        return 0.0

    bin_edges = np.linspace(global_min, global_max, bins + 1)

    ref_hist, _ = np.histogram(ref, bins=bin_edges)
    cur_hist, _ = np.histogram(cur, bins=bin_edges)

    ref_total = float(ref_hist.sum())
    cur_total = float(cur_hist.sum())

    ref_pct = (ref_hist + epsilon) / (ref_total + epsilon * bins)
    cur_pct = (cur_hist + epsilon) / (cur_total + epsilon * bins)

    psi = float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))
    return max(psi, 0.0)  # numerical safety: PSI is always non-negative


def detect_feature_drift(
    reference_df: pd.DataFrame,
    current_df: pd.DataFrame,
    feature_cols: list[str],
    threshold_warn: float = PSI_WARN,
    threshold_moderate: float = PSI_MODERATE,
) -> dict[str, float]:
    """Compute PSI for each feature column.

    Parameters
    ----------
    reference_df:
        Reference (training) feature DataFrame.
    current_df:
        Current (production) feature DataFrame.
    feature_cols:
        Columns to check — skips any column absent from either DataFrame.
    threshold_warn:
        PSI >= this value is flagged as severe (CI failure level).
    threshold_moderate:
        PSI >= this value is flagged as moderate.

    Returns
    -------
    Dict mapping feature name → PSI value.
    """
    results: dict[str, float] = {}
    for col in feature_cols:
        if col not in reference_df.columns or col not in current_df.columns:
            continue
        results[col] = compute_psi(reference_df[col], current_df[col])
    return results


def detect_regime_drift(
    reference_labels: pd.Series,
    current_labels: pd.Series,
) -> dict[str, float]:
    """Chi-squared test for regime label distribution shift.

    Returns a dict with keys:
    - ``chi2``: chi-squared statistic
    - ``p_value``: p-value (< 0.05 = significant shift)
    - ``reference_bull_pct``, ``reference_bear_pct``, ``reference_flat_pct``
    - ``current_bull_pct``, ``current_bear_pct``, ``current_flat_pct``
    """
    from scipy.stats import chi2_contingency  # optional dep

    labels = ["bull", "bear", "flat"]

    ref_counts = reference_labels.value_counts().reindex(labels, fill_value=0)
    cur_counts = current_labels.value_counts().reindex(labels, fill_value=0)

    contingency = np.array([ref_counts.values, cur_counts.values])
    chi2, p_value, _, _ = chi2_contingency(contingency)

    ref_total = max(ref_counts.sum(), 1)
    cur_total = max(cur_counts.sum(), 1)

    return {
        "chi2":                float(chi2),
        "p_value":             float(p_value),
        "reference_bull_pct":  float(ref_counts["bull"] / ref_total),
        "reference_bear_pct":  float(ref_counts["bear"] / ref_total),
        "reference_flat_pct":  float(ref_counts["flat"] / ref_total),
        "current_bull_pct":    float(cur_counts["bull"] / cur_total),
        "current_bear_pct":    float(cur_counts["bear"] / cur_total),
        "current_flat_pct":    float(cur_counts["flat"] / cur_total),
    }


def summarise_psi_results(
    psi_results: dict[str, float],
    threshold_moderate: float = PSI_MODERATE,
    threshold_warn: float = PSI_WARN,
) -> tuple[str, list[str]]:
    """Classify overall drift severity and return (severity, severe_features).

    Returns
    -------
    severity:
        ``"stable"``, ``"moderate"``, or ``"severe"``
    severe_features:
        List of feature names with PSI >= threshold_warn.
    """
    if not psi_results:
        return "stable", []

    max_psi = max(psi_results.values())
    severe_features = [f for f, v in psi_results.items() if v >= threshold_warn]

    if max_psi >= threshold_warn:
        return "severe", severe_features
    if max_psi >= threshold_moderate:
        return "moderate", []
    return "stable", []
