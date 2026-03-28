"""
experiment_tracker.py — MLflow wrapper with graceful no-op fallback
====================================================================
Drop-in tracker that logs params, metrics, and artifacts via MLflow when
the library is available, and silently no-ops otherwise.  This means the
rest of the codebase can always call tracker methods without try/except.

Tracking URI defaults to ``mlruns/`` (local file-based) but can be
overridden via the ``MLFLOW_TRACKING_URI`` environment variable.

Usage:
    tracker = ExperimentTracker()
    with tracker.start_run("regime_training", run_name="centroid_v1"):
        tracker.log_params({"model_type": "centroid", "n_features": 12})
        tracker.log_metrics({"accuracy": 0.61, "robustness": 0.78})
        tracker.log_artifact("artifacts_template/models/candidate/feature_importance.csv")
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator


class ExperimentTracker:
    """MLflow experiment tracker with graceful no-op fallback when mlflow is unavailable."""

    def __init__(self, tracking_uri: str | None = None) -> None:
        self._available = False
        self._mlflow = None
        uri = tracking_uri or os.environ.get("MLFLOW_TRACKING_URI", "mlruns")
        try:
            import mlflow
            mlflow.set_tracking_uri(uri)
            self._mlflow = mlflow
            self._available = True
        except ImportError:
            pass

    # ── context manager ───────────────────────────────────────────────────────

    @contextmanager
    def start_run(
        self,
        experiment_name: str,
        run_name: str | None = None,
    ) -> Generator["ExperimentTracker", None, None]:
        """Context manager: start an MLflow run, yield self, end run on exit."""
        if self._available:
            self._mlflow.set_experiment(experiment_name)
            with self._mlflow.start_run(run_name=run_name):
                yield self
        else:
            yield self

    # ── logging primitives ────────────────────────────────────────────────────

    def log_params(self, params: dict[str, Any]) -> None:
        if self._available:
            self._mlflow.log_params(
                {str(k): str(v) for k, v in params.items()}
            )

    def log_metrics(self, metrics: dict[str, float], step: int = 0) -> None:
        if self._available:
            self._mlflow.log_metrics(
                {str(k): float(v) for k, v in metrics.items()}, step=step
            )

    def log_artifact(self, path: str | Path) -> None:
        p = Path(path)
        if self._available and p.exists():
            self._mlflow.log_artifact(str(p))

    def set_tag(self, key: str, value: str) -> None:
        if self._available:
            self._mlflow.set_tag(key, value)

    # ── composite helpers ─────────────────────────────────────────────────────

    def log_lightgbm_run(
        self,
        model: Any,
        metrics: dict[str, float],
        artifacts: dict[str, str | Path] | None = None,
    ) -> None:
        """Log a LightGBM regime model run — params, metrics, and feature importance CSV."""
        params: dict[str, Any] = {
            "model_type":    "lightgbm",
            "n_features":    len(getattr(model, "feature_columns", [])),
            "best_iteration": getattr(model, "best_iteration_", "n/a"),
        }
        self.log_params(params)
        self.log_metrics(metrics)
        if artifacts:
            for path in artifacts.values():
                self.log_artifact(path)

    def log_regime_training(
        self,
        model_type: str,
        feature_columns: list[str],
        accuracy: float,
        extra_params: dict[str, Any] | None = None,
    ) -> None:
        """Convenience wrapper for regime model training runs."""
        params: dict[str, Any] = {
            "model_type":    model_type,
            "n_features":    len(feature_columns),
            "feature_cols":  ",".join(feature_columns),
        }
        if extra_params:
            params.update(extra_params)
        self.log_params(params)
        self.log_metrics({"accuracy": accuracy})

    def log_setup_ranker(
        self,
        strategy_scores: dict[str, float],
        fallback_score: float,
    ) -> None:
        """Log setup ranker strategy scores."""
        self.log_metrics({"fallback_score": fallback_score, "n_strategies": float(len(strategy_scores))})
        self.log_params({
            "strategy_scores": str(strategy_scores),
        })

    def log_optimizer_run(
        self,
        strategy_name: str,
        best_params: dict[str, Any],
        best_win_rate: float | None,
    ) -> None:
        """Log Optuna param optimization result for one strategy."""
        self.log_params({f"{strategy_name}__{k}": v for k, v in best_params.items()})
        if best_win_rate is not None:
            self.log_metrics({f"{strategy_name}__win_rate": best_win_rate})

    def log_confluence_result(
        self,
        top_combo: list[str],
        top_win_rate: float,
        n_signals: int,
    ) -> None:
        """Log confluence optimizer output."""
        self.log_params({"top_combo": str(top_combo)})
        self.log_metrics({"top_win_rate": top_win_rate, "n_signals": float(n_signals)})

    # ── properties ────────────────────────────────────────────────────────────

    @property
    def is_available(self) -> bool:
        return self._available


# Module-level singleton — callers can import and use directly
tracker = ExperimentTracker()
