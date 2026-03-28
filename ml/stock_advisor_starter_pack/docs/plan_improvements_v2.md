# ML Plan Improvements — Code Review Feedback v2

**Date:** 2026-03-22
**Source:** External code review of the Week 1–4 MLOps plan
**Status:** TO IMPLEMENT

---

## Overall Assessment: EXCELLENT — these are refinements, not blockers

The core plan (bug fixes → validation hardening → LightGBM → productionize) matches MLOps best practices.
The improvements below are optimization additions to the existing plan.

---

## 1. Optuna: Add Pruning (Week 2)

Add `MedianPruner` to Optuna study to cut unpromising trials early (saves 50–80% compute).

```python
# In scripts/param_optimizer.py — update the objective and study creation

def objective(trial):
    params = suggest_params(trial)

    # 70/15/15 chronological split (not random!)
    n = len(df)
    train_df = df.iloc[:int(n * 0.7)]
    val_df   = df.iloc[int(n * 0.7):int(n * 0.85)]
    # test_df held out completely — never optimize against it

    model = train(train_df, params)
    val_metrics = evaluate(model, val_df)

    # Risk-adjusted score (penalize drawdown)
    score = (
        val_metrics['win_rate']      * 0.3 +
        val_metrics['expectancy']    * 0.3 +
        val_metrics['profit_factor'] * 0.2 +
        val_metrics['stability']     * 0.2 -
        val_metrics['max_drawdown']  * 0.5   # Penalty
    )

    # Report intermediate for pruning
    trial.report(score, step=1)
    if trial.should_prune():
        raise optuna.TrialPruned()

    return score

study = optuna.create_study(
    direction="maximize",
    sampler=optuna.samplers.TPESampler(seed=42, n_startup_trials=20),
    pruner=optuna.pruners.MedianPruner()    # ← ADD THIS
)
```

### Week 2 Gate — add to run
```python
if rolling_wf_results['robustness'] < 0.7:
    print("STOP: Walk-forward results collapsed. Debug before Week 3.")
    sys.exit(1)
```

---

## 2. LightGBM: Additional Anti-Overfitting Parameters (Week 3)

Add `min_data_in_leaf`, `feature_fraction`, `bagging_fraction`, and `early_stopping_rounds`.
Financial time series are noisy — these prevent memorizing noise.

```python
# In src/models/train_regime_model.py

from lightgbm import LGBMClassifier, early_stopping

clf = LGBMClassifier(
    n_estimators=100,
    max_depth=4,
    learning_rate=0.05,
    class_weight="balanced",
    # ADD THESE:
    min_data_in_leaf=50,      # Prevents overfitting to noise — requires 50 samples per leaf
    feature_fraction=0.8,     # Column sampling (like random forest)
    bagging_fraction=0.8,     # Row sampling
    bagging_freq=5,
    # early stopping via callbacks (not constructor param in newer lgbm):
)

clf.fit(
    X_train, y_train,
    eval_set=[(X_val, y_val)],
    eval_metric='multi_logloss',
    callbacks=[early_stopping(stopping_rounds=10, verbose=False)]
)
```

### Feature Importance Logging (add to Week 3 training)
```python
# After training — log feature importance for interpretability
importance = pd.DataFrame({
    'feature': feature_columns,
    'importance': clf.feature_importances_
}).sort_values('importance', ascending=False)

importance.to_csv(output_path / "feature_importance.csv", index=False)
# Also log to MLflow:
tracker.log_artifact(output_path / "feature_importance.csv")
```

---

## 3. PSI Drift Detection: Fixed Bin Edges (Week 4)

**Critical:** Use IDENTICAL bin edges for reference and current distribution.
Using separate percentile bins per distribution is a common bug that gives wrong PSI values.

```python
# In src/monitoring/drift_detector.py

def compute_psi(reference: pd.Series, current: pd.Series, bins: int = 10) -> float:
    epsilon = 1e-10

    # FIXED BIN EDGES — use global min/max across BOTH distributions
    global_min = min(reference.min(), current.min())
    global_max = max(reference.max(), current.max())
    bin_edges = np.linspace(global_min, global_max, bins + 1)

    # Histograms using same bins
    ref_hist, _ = np.histogram(reference, bins=bin_edges)
    cur_hist, _ = np.histogram(current,   bins=bin_edges)

    # Normalize with epsilon smoothing (avoids log(0) and div-by-zero)
    ref_pct = (ref_hist + epsilon) / (ref_hist.sum() + epsilon * bins)
    cur_pct = (cur_hist + epsilon) / (cur_hist.sum() + epsilon * bins)

    # PSI formula
    psi = np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct))
    return float(psi)
```

**Thresholds (industry standard):**
- PSI < 0.10: No significant change — stable
- 0.10 ≤ PSI < 0.20: Moderate drift — monitor
- PSI ≥ 0.20: Significant drift — investigate
- PSI ≥ 0.25: Alert — possible model degradation

---

## 4. Multi-Criteria Model Promotion (Week 4)

Single-metric promotion (win rate only) causes overfitting to that metric.
Require 4 of 5 criteria to pass before promoting a new bundle.

```python
# In scripts/promote_if_better.py

def should_promote(candidate: dict, active: dict) -> tuple[bool, dict]:
    checks = {
        'win_rate_improvement': candidate['win_rate'] > active['win_rate'] + 0.01,
        'sharpe_improvement':   candidate['sharpe']  > active['sharpe'],
        'drawdown_ok':          candidate['max_dd']  < active['max_dd'] * 1.1,   # Not worse by >10%
        'robustness_ok':        candidate.get('robustness', 0) > 0.7,            # Walk-forward gate
        'sample_size_ok':       candidate['n_trades'] >= 30,                     # Statistical minimum
    }

    decision = sum(checks.values()) >= 4   # 4 of 5 must pass
    return decision, checks
```

---

## 5. Week 2 Gate Checklist — document before proceeding to Week 3

Create `docs/WEEK_2_GATE.md`:

```markdown
## Week 2 Gate Checklist
- [ ] Rolling walk-forward completed on RELIANCE 15m
- [ ] Mean robustness >= 0.7 across all folds
- [ ] No single fold with robustness < 0.5
- [ ] Validation metrics stable (std < 0.1)
- [ ] Optuna optimization converged (no plateau in last 20 trials)

If ANY check fails: STOP, debug, do not proceed to Week 3.
```

---

## 6. Unified Files Summary (from review)

| Week | File | Action |
|---|---|---|
| 1 | `src/strategies/signal_adapter.py` | Fix vwap_bb + signal_strength bugs |
| 1 | `src/feedback/daily_retrain.py` | Connect feedback loop |
| 1 | `src/backtest/metrics.py` | Fix Sharpe annualization |
| 1 | `tests/test_week1_fixes.py` | NEW — regression tests |
| 2 | `scripts/param_optimizer.py` | Optuna integration + pruning |
| 2 | `src/models/evaluate_walk_forward.py` | Rolling walk-forward |
| 2 | `src/labels/build_regime_labels.py` | ATR threshold (✅ DONE) |
| 2 | `src/features/build_regime_features.py` | Add 5 new features |
| 3 | `src/models/train_regime_model.py` | LightGBM + early stopping (✅ DONE) |
| 3 | `src/mlops/experiment_tracker.py` | NEW — MLflow wrapper |
| 3 | `requirements.txt` | Add lightgbm (✅ DONE), mlflow |
| 4 | `src/features/feature_store.py` | NEW — Parquet feature store |
| 4 | `src/monitoring/drift_detector.py` | NEW — PSI drift detection |
| 4 | `scripts/run_drift_check.py` | NEW — CI-compatible check |
| 4 | `scripts/promote_if_better.py` | NEW — multi-criteria promotion |
| 4 | `.github/workflows/daily_retrain.yml` | NEW — CI/CD pipeline |

**Items marked ✅ DONE were already implemented in Sessions 1–3.**

---

## 7. Review Integration Assessment

| Component | Plan | Industry Best Practice | Match |
|---|---|---|---|
| Week 1: Bug fixes | Fix before building | Fix foundations first | ✅ |
| Week 2: Optuna + pruning + 70/15/15 split + rolling WF | Bayesian search + walk-forward | Essential for time series | ✅ |
| Week 2 Gate | Stop if WF collapses | Validate before complexifying | ✅ |
| Week 3: LightGBM with early stopping + feature importance | Anti-overfitting + interpretability | Standard for financial ML | ✅ |
| Week 4: Parquet store + PSI + multi-criteria promotion | MLOps production standards | Industry best practice | ✅ |
