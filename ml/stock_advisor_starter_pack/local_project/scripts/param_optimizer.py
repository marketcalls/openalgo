"""
Parameter Optimizer — Optuna Bayesian Search
=============================================
Replaces one-at-a-time grid sweep with Optuna TPE + MedianPruner.
Data split: 70% train, 15% validation (optimization target), 15% test (held out — never touched).
Risk-adjusted composite score: 0.30*win_rate + 0.30*expectancy + 0.20*profit_factor
                                + 0.20*stability - 0.50*max_drawdown

Output format unchanged: best_params.json + optimization_summary.csv.

Usage (from local_project/ with PYTHONPATH=src):
    python scripts/param_optimizer.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import optuna
optuna.logging.set_verbosity(optuna.logging.WARNING)

# ── path setup ──────────────────────────────────────────────────────────────
SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from core.constants import DEFAULT_RELIANCE_ROOT, DEFAULT_STRATEGY_ROOT, DEFAULT_ARTIFACTS_ROOT
from data.load_symbol_timeframes import load_symbol_timeframes
from labels.build_setup_labels import build_setup_labels
from mlops.experiment_tracker import tracker
from strategies.registry import build_strategy_registry

LOOKAHEAD_BARS = 8
MIN_SIGNALS    = 10
N_TRIALS       = 100
SELECTED_STRATEGIES = [
    "twin_range_filter",
    "trend_signals_tp_sl_ualgo",
    "bahai_reversal_points",
    "reversal_radar_v2",
    "central_pivot_range",
]


# ── helpers ──────────────────────────────────────────────────────────────────

def suggest_params(trial: "optuna.Trial", param_space: dict[str, list[Any]]) -> dict[str, Any]:
    """Suggest one parameter combination from param_space via Optuna categorical sampling."""
    params: dict[str, Any] = {}
    for name, choices in param_space.items():
        if len(choices) == 0:
            continue
        params[name] = trial.suggest_categorical(name, choices)
    return params


def _compute_metrics(labeled_df: pd.DataFrame) -> dict[str, float]:
    """Compute risk-adjusted metrics from a labeled DataFrame with usable_signal + setup_success."""
    active = labeled_df[labeled_df["usable_signal"] != 0]
    n = len(active)
    if n < MIN_SIGNALS:
        return {
            "win_rate": 0.0, "expectancy": -1.0, "profit_factor": 0.0,
            "stability": 0.0, "max_drawdown": 1.0, "n_signals": n,
        }

    win_rate = float(active["setup_success"].mean())
    # Binary symmetric payoff expectancy in [-1, +1]
    expectancy = float(2 * win_rate - 1)
    wins   = int(active["setup_success"].sum())
    losses = n - wins
    profit_factor = wins / max(losses, 1e-9)

    # Stability: 1 - std of rolling-20 win rate (higher = more consistent)
    rolling_wr = active["setup_success"].rolling(20, min_periods=5).mean().dropna()
    stability = float(1.0 - rolling_wr.std()) if len(rolling_wr) > 1 else 0.5

    # Max drawdown on cumulative binary P&L (+1 win, -1 loss)
    pnl = active["setup_success"].replace(0, -1).astype(float).values
    cum  = np.cumsum(pnl)
    peak = np.maximum.accumulate(cum)
    dd   = (peak - cum) / (np.abs(peak) + 1e-9)
    max_drawdown = float(dd.max()) if len(dd) > 0 else 0.0

    return {
        "win_rate": win_rate,
        "expectancy": expectancy,
        "profit_factor": profit_factor,
        "stability": stability,
        "max_drawdown": max_drawdown,
        "n_signals": n,
    }


def build_objective(wrapper, val_df: pd.DataFrame):
    """Return an Optuna objective.  Strategy is evaluated on val_df with each suggested param set."""
    def objective(trial: "optuna.Trial") -> float:
        params = suggest_params(trial, wrapper.param_space)
        try:
            val_result = wrapper.run(val_df, params=params)
        except Exception:
            raise optuna.TrialPruned()

        candidate = val_df.copy().reset_index(drop=True)
        candidate["signal"] = val_result.signal.reset_index(drop=True)
        candidate["usable_signal"] = candidate["signal"]
        try:
            labeled = build_setup_labels(
                candidate, signal_column="usable_signal", lookahead_bars=LOOKAHEAD_BARS
            )
        except Exception:
            raise optuna.TrialPruned()

        metrics = _compute_metrics(labeled)
        if metrics["n_signals"] < MIN_SIGNALS:
            raise optuna.TrialPruned()

        score = (
            metrics["win_rate"]      * 0.30
            + metrics["expectancy"]  * 0.30
            + metrics["profit_factor"] * 0.20
            + metrics["stability"]   * 0.20
            - metrics["max_drawdown"] * 0.50
        )
        trial.report(score, step=1)
        if trial.should_prune():
            raise optuna.TrialPruned()
        return score

    return objective


def evaluate_params(wrapper, df: pd.DataFrame, params: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a strategy on df for reporting (baseline and final test evaluation)."""
    try:
        result = wrapper.run(df, params=params)
        candidate = df.copy().reset_index(drop=True)
        candidate["signal"] = result.signal.reset_index(drop=True)
        candidate["usable_signal"] = candidate["signal"]
        labeled = build_setup_labels(
            candidate, signal_column="usable_signal", lookahead_bars=LOOKAHEAD_BARS
        )
        active = labeled[labeled["usable_signal"] != 0]
        if len(active) < MIN_SIGNALS:
            return {"win_rate": None, "signals": len(active), "params": params}
        return {
            "win_rate": round(float(active["setup_success"].mean()), 4),
            "signals": len(active),
            "params": params,
        }
    except Exception as exc:
        return {"win_rate": None, "signals": 0, "params": params, "error": str(exc)}


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    print("Loading data …")
    datasets = load_symbol_timeframes(DEFAULT_RELIANCE_ROOT, symbol="RELIANCE")
    primary_df = datasets["15m"].frame

    n         = len(primary_df)
    train_end = int(n * 0.70)
    val_end   = int(n * 0.85)
    train_df  = primary_df.iloc[:train_end].copy()
    val_df    = primary_df.iloc[train_end:val_end].copy()
    # test slice primary_df.iloc[val_end:] is held out — never used during optimization

    print(
        f"Data split — train: {train_end} bars | val: {val_end - train_end} bars | "
        f"test (held out): {n - val_end} bars"
    )

    print("Loading strategy registry …")
    registry = build_strategy_registry(DEFAULT_STRATEGY_ROOT)

    output_root = DEFAULT_ARTIFACTS_ROOT / "reports" / "param_optimization"
    output_root.mkdir(parents=True, exist_ok=True)

    all_best: dict[str, dict[str, Any]] = {}

    for name in SELECTED_STRATEGIES:
        if name not in registry:
            print(f"\n[SKIP] {name} not in registry")
            continue
        wrapper = registry[name]
        if wrapper.unsupported_reason:
            print(f"\n[SKIP] {name}: {wrapper.unsupported_reason}")
            continue

        print(f"\n{'='*60}")
        print(f"STRATEGY: {name}")
        print(f"{'='*60}")

        param_space    = wrapper.param_space
        numeric_params = {
            k: v for k, v in param_space.items()
            if all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v)
            and len(v) > 1
        }

        if not numeric_params:
            print("  No numeric tunable parameters — using defaults.")
            baseline = evaluate_params(wrapper, primary_df, {})
            print(f"  Baseline: {baseline['signals']} signals, win_rate={baseline['win_rate']}")
            all_best[name] = {
                "best_params": {},
                "baseline_win_rate": baseline["win_rate"],
                "baseline_signals": baseline["signals"],
                "combined_win_rate": baseline["win_rate"],
                "combined_signals": baseline["signals"],
                "best_trial_score": None,
                "n_completed_trials": 0,
            }
            continue

        # Baseline on full data (using default params)
        baseline = evaluate_params(wrapper, primary_df, {})
        print(f"  Default baseline: {baseline['signals']} signals, win_rate={baseline['win_rate']}")

        # Optuna study — stored in output_root for cross-run resumption
        db_path = output_root / f"optuna_{name}.db"
        study = optuna.create_study(
            direction="maximize",
            sampler=optuna.samplers.TPESampler(seed=42),
            pruner=optuna.pruners.MedianPruner(n_startup_trials=10, n_warmup_steps=0),
            storage=f"sqlite:///{db_path}",
            load_if_exists=True,
            study_name=name,
        )

        print(f"  Running Optuna ({N_TRIALS} trials) …")
        objective = build_objective(wrapper, val_df)
        study.optimize(objective, n_trials=N_TRIALS, show_progress_bar=False)

        completed = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
        if not completed:
            print("  No completed trials — falling back to defaults.")
            all_best[name] = {
                "best_params": {},
                "baseline_win_rate": baseline["win_rate"],
                "baseline_signals": baseline["signals"],
                "combined_win_rate": baseline["win_rate"],
                "combined_signals": baseline["signals"],
                "best_trial_score": None,
                "n_completed_trials": 0,
            }
            continue

        best_params = study.best_params
        best_score  = study.best_value
        print(f"  Best Optuna score: {best_score:.4f}  params: {best_params}")

        # Evaluate best params on full data for summary reporting
        combined = evaluate_params(wrapper, primary_df, best_params)
        print(f"  Best params on full data: {combined['signals']} signals, win_rate={combined['win_rate']}")

        all_best[name] = {
            "baseline_win_rate":   baseline["win_rate"],
            "baseline_signals":    baseline["signals"],
            "best_params":         best_params,
            "combined_win_rate":   combined["win_rate"],
            "combined_signals":    combined["signals"],
            "best_trial_score":    best_score,
            "n_completed_trials":  len(completed),
        }

        # Log to MLflow
        tracker.log_optimizer_run(
            strategy_name=name,
            best_params=best_params,
            best_win_rate=combined["win_rate"],
        )

        # Save per-strategy trial history CSV (replaces per-param sweep CSVs)
        trials_df = study.trials_dataframe()
        trials_df.to_csv(output_root / f"{name}__trials.csv", index=False)

    # ── Summary table ─────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("OPTIMIZATION SUMMARY")
    print(f"{'='*60}")
    summary_rows = []
    for name, info in all_best.items():
        improvement = None
        bwr = info.get("baseline_win_rate")
        cwr = info.get("combined_win_rate")
        if bwr and cwr:
            improvement = round((cwr - bwr) * 100, 2)
        summary_rows.append({
            "strategy":              name,
            "baseline_win_rate_%":   round((bwr or 0) * 100, 1),
            "baseline_signals":      info.get("baseline_signals", 0),
            "optimized_win_rate_%":  round((cwr or 0) * 100, 1),
            "optimized_signals":     info.get("combined_signals", 0),
            "improvement_%pts":      improvement,
            "best_trial_score":      info.get("best_trial_score"),
            "n_trials":              info.get("n_completed_trials", 0),
            "best_params":           json.dumps(info.get("best_params", {})),
        })

    summary_df = pd.DataFrame(summary_rows)
    print(
        summary_df[[
            "strategy", "baseline_win_rate_%", "optimized_win_rate_%",
            "improvement_%pts", "optimized_signals",
        ]].to_string(index=False)
    )

    out_path = output_root / "optimization_summary.csv"
    summary_df.to_csv(out_path, index=False)
    print(f"\nFull results saved: {out_path}")

    best_json_path = output_root / "best_params.json"
    best_json_path.write_text(
        json.dumps({name: info["best_params"] for name, info in all_best.items()}, indent=2)
    )
    print(f"Best params JSON : {best_json_path}")


if __name__ == "__main__":
    main()
