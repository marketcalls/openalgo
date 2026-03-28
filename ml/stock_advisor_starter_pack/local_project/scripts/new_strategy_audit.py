"""
new_strategy_audit.py
=====================
Runs every new strategy file from D:\\test1 against RELIANCE 15m data and reports:
- Whether it ran successfully
- How many signals were produced (buy, sell, total)
- Win rate per signal direction (based on 8-bar forward return)
- Which signal columns were found

Usage:
    PYTHONPATH=src python scripts/new_strategy_audit.py
"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import pandas as pd

from core.constants import DEFAULT_RELIANCE_ROOT, DEFAULT_STRATEGY_ROOT
from data.load_symbol_timeframes import load_symbol_timeframes
from labels.build_setup_labels import build_setup_labels
from strategies.loader import discover_strategy_paths, extract_default_constants, load_module
from strategies.registry import ModuleStrategyWrapper, build_strategy_registry
from strategies.param_space import build_param_space
from strategies.signal_adapter import normalize_strategy_output

NEW_STRATEGIES = [
    "bollinger_band_breakout",
    "candlestick_patterns_identified",
    "cm_hourly_pivots",
    "dark_cloud_piercing_line_tradingfinder",
    "double_top_bottom_ultimate",
    "flowscope_hapharmonic",
    "harmonic_strategy",
    "hybrid_ml_vwap_bb",
    "impulse_trend_boswaves",
    "n_bar_reversal_luxalgo",
    "n_bar_reversal_luxalgo_strategy",
    "outside_reversal",
    "previous_candle_inside_outside_mk",
    "rsi_divergence",
    "sbs_swing_areas_trades",
    "sfp_candelacharts",
    "three_inside_tradingfinder",
    "vedhaviyash4_daily_cpr",
    "vwap_bb_confluence",
]

LOOKAHEAD = 8  # bars for win/loss labeling


def _win_rate(signals: pd.Series, labels: pd.Series) -> tuple[int, float]:
    """Return (n_signals, win_rate) for rows where signal != 0."""
    mask = signals != 0
    if mask.sum() == 0:
        return 0, float("nan")
    n = int(mask.sum())
    # Direction-aware: signal=+1 → success if price went up; signal=-1 → success if price went down
    direction_correct = (signals[mask] * labels[mask]) > 0
    return n, float(direction_correct.mean())


def audit_strategy(path: Path, primary_frame: pd.DataFrame) -> dict:
    name = path.stem
    result = {
        "name": name,
        "status": "ok",
        "error": "",
        "total_signals": 0,
        "long_signals": 0,
        "short_signals": 0,
        "win_rate": float("nan"),
        "long_win_rate": float("nan"),
        "short_win_rate": float("nan"),
        "signal_columns_found": "",
        "adapter_notes": "",
    }
    try:
        defaults = extract_default_constants(path)
        module = load_module(path)
        wrapper = ModuleStrategyWrapper(
            name=name,
            module_path=path,
            param_defaults=defaults,
            param_space=build_param_space(defaults),
            role_tags=(),
            unsupported_reason=None,
        )
        run_result = wrapper.run(primary_frame)
        signal = run_result.signal.reset_index(drop=True)
        result["adapter_notes"] = "; ".join(run_result.adapter_notes)

        # Find which columns triggered the adapter
        try:
            raw_frame = module.calculate_indicators(primary_frame.copy())
            triggered_cols = [
                col for col in raw_frame.columns
                if any(kw in col.lower() for kw in ["buy", "sell", "bull", "bear", "long", "short", "dir"])
            ]
            result["signal_columns_found"] = ", ".join(triggered_cols)
        except Exception:
            result["signal_columns_found"] = "(could not inspect)"

        # Build forward labels
        df_labeled = primary_frame.copy().reset_index(drop=True)
        df_labeled["signal"] = signal
        df_labeled = build_setup_labels(df_labeled, signal_column="signal", lookahead_bars=LOOKAHEAD)
        labels_raw = df_labeled["setup_success"].fillna(0)
        # Convert to direction: +1 if price went up, -1 if price went down
        forward_return = primary_frame["close"].shift(-LOOKAHEAD) / primary_frame["close"] - 1.0
        forward_direction = forward_return.reset_index(drop=True).apply(
            lambda v: 1 if v > 0 else (-1 if v < 0 else 0)
        )

        longs = signal == 1
        shorts = signal == -1

        result["total_signals"] = int((signal != 0).sum())
        result["long_signals"] = int(longs.sum())
        result["short_signals"] = int(shorts.sum())

        if result["total_signals"] > 0:
            correct = (signal[signal != 0] * forward_direction[signal != 0]) > 0
            result["win_rate"] = float(correct.mean())
        if longs.sum() > 0:
            result["long_win_rate"] = float(((forward_direction[longs]) > 0).mean())
        if shorts.sum() > 0:
            result["short_win_rate"] = float(((forward_direction[shorts]) < 0).mean())

    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"

    return result


def main() -> None:
    print("Loading RELIANCE 15m data...")
    datasets = load_symbol_timeframes(DEFAULT_RELIANCE_ROOT, symbol="RELIANCE")
    primary_frame = datasets["15m"].frame
    print(f"  {len(primary_frame)} bars loaded.\n")

    strategy_root = DEFAULT_STRATEGY_ROOT
    results = []
    for name in NEW_STRATEGIES:
        path = Path(strategy_root) / f"{name}.py"
        if not path.exists():
            results.append({"name": name, "status": "missing", "error": f"File not found: {path}"})
            print(f"  [{name}] MISSING")
            continue
        print(f"  Running {name}...", end=" ", flush=True)
        r = audit_strategy(path, primary_frame)
        results.append(r)
        if r["status"] == "error":
            print(f"ERROR: {r['error'][:80]}")
        else:
            print(f"ok  |  signals={r['total_signals']}  long={r['long_signals']}  short={r['short_signals']}  win_rate={r['win_rate']:.3f}" if r["total_signals"] > 0 else f"ok  |  0 signals")

    # Save CSV report
    report_dir = Path(__file__).resolve().parents[1].parent / "artifacts_template" / "reports" / "new_strategy_audit"
    report_dir.mkdir(parents=True, exist_ok=True)
    df_results = pd.DataFrame(results)
    csv_path = report_dir / "new_strategy_audit.csv"
    df_results.to_csv(csv_path, index=False)
    print(f"\nReport saved to {csv_path}")

    # Print summary table
    print("\n" + "=" * 80)
    print(f"{'STRATEGY':<42} {'STATUS':<8} {'SIGNALS':>8} {'WIN%':>6} {'LONG%':>6} {'SHORT%':>6}")
    print("=" * 80)
    for r in results:
        if r["status"] == "error":
            print(f"{r['name']:<42} {'ERROR':<8}  {r.get('error','')[:30]}")
        elif r["status"] == "missing":
            print(f"{r['name']:<42} {'MISSING':<8}")
        else:
            wr = f"{r['win_rate']:.1%}" if r["win_rate"] == r["win_rate"] else " —"
            lw = f"{r['long_win_rate']:.1%}" if r["long_win_rate"] == r["long_win_rate"] else " —"
            sw = f"{r['short_win_rate']:.1%}" if r["short_win_rate"] == r["short_win_rate"] else " —"
            print(f"{r['name']:<42} {'ok':<8} {r['total_signals']:>8} {wr:>6} {lw:>6} {sw:>6}")


if __name__ == "__main__":
    main()
