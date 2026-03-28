"""
analysis_rules.py
=================
MANDATORY RULES for all indicator combination analysis in this project.
Read and follow these before writing any analysis script.

These rules were established after OOS validation (2026-03-22) proved that
in-sample combinations frequently fail on unseen data and different symbols.
"""

# =============================================================================
# RULE 1 — NEVER REUSE OLD COMBOS ACROSS STOCKS OR TIMEFRAMES
# =============================================================================
#
# Each stock × timeframe combination requires its OWN fresh search.
# A combo that wins on RELIANCE 15m may fail on:
#   - RELIANCE 1hr (different noise, different signal frequency)
#   - INFY 15m    (different volatility, different sector behavior)
#   - RELIANCE 15m one year later (regime change)
#
# PROOF: CPR + smc_ob hit 93.5% on RELIANCE 15m train → 0 signals on test.
#        The same combo on INFY 15m held at 85.7% with 14 test signals.
#
# ACTION: Always run multi_tf_analysis.py fresh for each new stock/timeframe.
#         Do NOT copy-paste combos from previous experiments.

RULE_NO_COMBO_REUSE = """
Each stock and each timeframe will get different indicator combinations
with different win rates. Do not depend on a combination found earlier
as correct. Always find fresh combinations for the specific stock,
timeframe, and date range being analyzed.
"""

# =============================================================================
# RULE 2 — ALWAYS USE 75/25 TRAIN/TEST SPLIT (CHRONOLOGICAL)
# =============================================================================
#
# Train on first 75% of bars → find best combos.
# Test on last 25% of bars  → validate (never used during search).
# Split MUST be chronological — never random (lookahead bias).
#
# PROOF: smc_ob held at 97.3% OOS on RELIANCE, 90.9% on INFY.
#        Most 100% in-sample combos → 0 signals OOS (exposed as overfitting).

TRAIN_RATIO  = 0.75
TEST_RATIO   = 0.25

# =============================================================================
# RULE 3 — SIGNAL COUNT THRESHOLDS FOR RELIABILITY
# =============================================================================
#
# A win rate means nothing without enough signals.
# These thresholds are based on OOS results:

MIN_SIGNALS_TRAIN = 15    # < 15 train signals → unreliable, likely overfitting
MIN_SIGNALS_TEST  = 5     # < 5 test signals → cannot draw conclusions
MIN_SIGNALS_HIGH_CONF = 50   # 50+ → high confidence result
MIN_SIGNALS_ROBUST    = 200  # 200+ → statistically robust (production-grade)

# =============================================================================
# RULE 4 — REQUIRED OUTPUT FORMAT (mandatory for all analysis scripts)
# =============================================================================
#
# All analysis results MUST be presented in this 3-phase format.
# This is non-negotiable — every script must produce all three phases.

REQUIRED_OUTPUT_FORMAT = """
Phase 1  — Per-TF Primary Scan
  What:   Run all strategies on every TF (1m to 1day), test all 1–4 combos per TF
  Output: tf_scan_summary.csv       — best combo per TF (one row per TF)
          {tf}_top20.csv            — top 20 combos for that TF

Phase 2  — Multi-TF Signal Confluence
  What:   For 15m primary: per-strategy WR at 4 confirmation levels
          (15m only → 15m+1hr → 15m+4hr → 15m+1hr+4hr),
          then combo-level cross-TF boost analysis
  Output: per_strategy_confirmation.csv  — per-strategy WR at each level
          combo_confirmation.csv         — combo WR gain from cross-TF filter

Final    — Cross-phase summary
  What:   Best combo across all TFs, biggest WR gain from cross-TF filtering
  Output: full_summary.json
"""

# =============================================================================
# RULE 5 — ANTI-PATTERNS (never do these)
# =============================================================================

ANTI_PATTERNS = [
    "Reusing a combo found on one stock/TF for a different stock/TF without re-running",
    "Trusting 100% win rate without OOS validation — almost always overfitting",
    "Trusting any combo with < 15 train signals",
    "Using random train/test split instead of chronological split",
    "Running combo search on full data and measuring WR on same data (data leakage)",
    "Assuming cross-TF confirmation always helps — it HURTS smc_bos (0% WR with 1hr confirm)",
    "Adding CPR to every combo — it kills signal frequency in different market regimes",
]

# =============================================================================
# RULE 6 — CONFIRMED REAL SIGNALS (OOS-validated, 2026-03-22)
# =============================================================================
#
# These signals held out-of-sample across RELIANCE and INFY independently.
# They are the most trustworthy signals in the toolkit.
# BUT: still run fresh for each new stock — they may behave differently.

VALIDATED_SIGNALS = {
    "smc_ob": {
        "description": "SMC Order Blocks — most reliable signal found",
        "standalone_wr": "90-97% on 15m, confirmed on both RELIANCE and INFY OOS",
        "note": "Always include in combo search; rarely fails",
    },
    "smc_fvg_with_1hr_confirm": {
        "description": "smc_fvg on 15m filtered by same direction on 1hr",
        "standalone_wr": "72% on 668-1475 OOS signals — highest statistical confidence",
        "note": "Best production config for frequent trading",
    },
    "twin_range_plus_smc_ob": {
        "description": "twin_range_filter + smc_ob together",
        "standalone_wr": "81-100% on 10-11 OOS signals per period",
        "note": "Holds across both symbols; good weekly trading combo",
    },
    "smc_bos_standalone_only": {
        "description": "smc_bos on 15m WITHOUT any cross-TF confirmation",
        "standalone_wr": "69-73% standalone; 0% with 1hr cross-TF (avoid confirmed)",
        "note": "NEVER use smc_bos with 1hr cross-TF confirmation",
    },
}

# =============================================================================
# RULE 7 — LOOKAHEAD CONFIGURATION
# =============================================================================

LOOKAHEAD_BARS = 8   # 8 bars forward = ~2 hours on 15m, ~8 hours on 1hr
                     # Keep consistent across all analyses for comparability


def print_rules() -> None:
    """Print all rules to stdout as a reminder before running analysis."""
    print("=" * 70)
    print("ANALYSIS RULES — READ BEFORE RUNNING")
    print("=" * 70)
    print(RULE_NO_COMBO_REUSE)
    print("Required output format:")
    print(REQUIRED_OUTPUT_FORMAT)
    print("Anti-patterns to avoid:")
    for i, ap in enumerate(ANTI_PATTERNS, 1):
        print(f"  {i}. {ap}")
    print("=" * 70)


if __name__ == "__main__":
    print_rules()
