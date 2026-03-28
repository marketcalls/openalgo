"""
promote_if_better.py — Multi-Criteria Model Promotion
======================================================
Compares a candidate model bundle against the active (production) bundle
and promotes the candidate when 4 of 5 criteria pass.

Criteria:
    1. win_rate_improvement — candidate win_rate > active win_rate + 0.01
    2. sharpe_improvement   — candidate sharpe > active sharpe
    3. drawdown_ok          — candidate max_dd < active max_dd * 1.10
    4. robustness_ok        — candidate robustness >= 0.70
    5. sample_size_ok       — candidate n_trades >= 30

Promotion = copy candidate bundle to active slot and write promotion_log.json.

Usage:
    python scripts/promote_if_better.py [--candidate-path PATH] [--active-path PATH]
                                        [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from core.constants import DEFAULT_ARTIFACTS_ROOT

DEFAULT_CANDIDATE = DEFAULT_ARTIFACTS_ROOT / "models" / "candidate"
DEFAULT_ACTIVE    = DEFAULT_ARTIFACTS_ROOT / "models" / "active"
PROMOTION_LOG     = DEFAULT_ARTIFACTS_ROOT / "models" / "promotion_log.json"

# ── promotion logic ───────────────────────────────────────────────────────────

def should_promote(
    candidate: dict,
    active: dict,
) -> tuple[bool, dict[str, bool]]:
    """Return (promote_decision, per-check results).

    At least 4 of 5 checks must pass.
    """
    checks = {
        "win_rate_improvement": (
            candidate.get("win_rate", 0.0) > active.get("win_rate", 0.0) + 0.01
        ),
        "sharpe_improvement": (
            candidate.get("sharpe", 0.0) > active.get("sharpe", 0.0)
        ),
        "drawdown_ok": (
            candidate.get("max_dd", 1.0) < active.get("max_dd", 1.0) * 1.10
        ),
        "robustness_ok": (
            candidate.get("robustness", 0.0) >= 0.70
        ),
        "sample_size_ok": (
            candidate.get("n_trades", 0) >= 30
        ),
    }
    passed = sum(checks.values()) >= 4
    return passed, checks


def _load_metrics(bundle_path: Path) -> dict:
    """Load metrics.json from a model bundle directory.  Returns {} if absent."""
    metrics_path = bundle_path / "metrics.json"
    if metrics_path.exists():
        return json.loads(metrics_path.read_text(encoding="utf-8"))
    return {}


def _append_promotion_log(entry: dict) -> None:
    """Append a promotion decision to the rolling log."""
    PROMOTION_LOG.parent.mkdir(parents=True, exist_ok=True)
    log: list[dict] = []
    if PROMOTION_LOG.exists():
        try:
            log = json.loads(PROMOTION_LOG.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log = []
    log.append(entry)
    PROMOTION_LOG.write_text(json.dumps(log, indent=2), encoding="utf-8")


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-criteria model promotion")
    parser.add_argument("--candidate-path", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--active-path",    type=Path, default=DEFAULT_ACTIVE)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Evaluate promotion criteria without actually copying files",
    )
    args = parser.parse_args()

    candidate_path: Path = args.candidate_path
    active_path: Path    = args.active_path

    if not candidate_path.exists():
        print(f"[PROMOTE] No candidate bundle found at {candidate_path}")
        sys.exit(0)

    candidate_metrics = _load_metrics(candidate_path)
    active_metrics    = _load_metrics(active_path) if active_path.exists() else {}

    if not active_metrics:
        print("[PROMOTE] No active model found — promoting candidate unconditionally.")
        decision = True
        checks: dict[str, bool] = {k: True for k in [
            "win_rate_improvement", "sharpe_improvement",
            "drawdown_ok", "robustness_ok", "sample_size_ok",
        ]}
    else:
        decision, checks = should_promote(candidate_metrics, active_metrics)

    # Print check results
    print(f"\n{'='*60}")
    print("MODEL PROMOTION EVALUATION")
    print(f"{'='*60}")
    print(f"  Candidate : {candidate_path}")
    print(f"  Active    : {active_path}")
    print()
    label_map = {
        "win_rate_improvement": f"win_rate > active+0.01        "
                                f"[cand={candidate_metrics.get('win_rate','?')}, "
                                f"active={active_metrics.get('win_rate','?')}]",
        "sharpe_improvement":   f"sharpe > active               "
                                f"[cand={candidate_metrics.get('sharpe','?')}, "
                                f"active={active_metrics.get('sharpe','?')}]",
        "drawdown_ok":          f"max_dd < active * 1.10        "
                                f"[cand={candidate_metrics.get('max_dd','?')}, "
                                f"active={active_metrics.get('max_dd','?')}]",
        "robustness_ok":        f"robustness >= 0.70            "
                                f"[{candidate_metrics.get('robustness','?')}]",
        "sample_size_ok":       f"n_trades >= 30                "
                                f"[{candidate_metrics.get('n_trades','?')}]",
    }
    passed_count = sum(checks.values())
    for check, result in checks.items():
        status = "PASS" if result else "FAIL"
        print(f"  [{status}]  {label_map.get(check, check)}")

    print(f"\n  {passed_count}/5 checks passed (need 4)")

    if decision:
        print("\n  ✓  PROMOTING candidate → active")
        if not args.dry_run:
            if active_path.exists():
                shutil.rmtree(active_path)
            shutil.copytree(candidate_path, active_path)
            print(f"     Copied {candidate_path} → {active_path}")
        else:
            print("     [DRY RUN] No files copied.")
    else:
        print("\n  ✗  NOT PROMOTING — candidate does not meet threshold.")

    # Log the decision
    log_entry = {
        "timestamp_utc":   datetime.now(timezone.utc).isoformat(),
        "decision":        "promoted" if decision else "rejected",
        "dry_run":         args.dry_run,
        "checks":          checks,
        "candidate_metrics": candidate_metrics,
        "active_metrics":    active_metrics,
    }
    _append_promotion_log(log_entry)
    print(f"\n  Decision logged to: {PROMOTION_LOG}")


if __name__ == "__main__":
    main()
