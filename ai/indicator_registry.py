"""Dynamic indicator registry — loads all custom indicators from indicators_lib/.

Each indicator file must have a calculate_indicators(df) function.
Returns DataFrame with added columns.
"""
import importlib
import importlib.util
import os
from pathlib import Path
from dataclasses import dataclass, field
from utils.logging import get_logger

logger = get_logger(__name__)

@dataclass
class IndicatorInfo:
    id: str              # "bahai_reversal_points"
    name: str            # "Bahai Reversal Points"
    file_path: str       # Full path to .py file
    category: str        # "custom" or "opensource"
    has_signals: bool    # True if output has Buy/Sell columns
    output_columns: list[str] = field(default_factory=list)

class IndicatorRegistry:
    def __init__(self):
        self._indicators: dict[str, IndicatorInfo] = {}
        self._modules: dict[str, object] = {}

    def discover(self, base_dir: str = None):
        """Scan indicators_lib/ and register all indicators."""
        if base_dir is None:
            base_dir = str(Path(__file__).parent / "indicators_lib" / "custom")

        if not os.path.exists(base_dir):
            logger.warning(f"Indicator dir not found: {base_dir}")
            return

        for fname in sorted(os.listdir(base_dir)):
            if not fname.endswith(".py") or fname.startswith("_"):
                continue
            fpath = os.path.join(base_dir, fname)
            indicator_id = fname[:-3]  # Remove .py

            try:
                spec = importlib.util.spec_from_file_location(f"custom_ind.{indicator_id}", fpath)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)

                if hasattr(mod, "calculate_indicators"):
                    name = indicator_id.replace("_", " ").title()
                    self._indicators[indicator_id] = IndicatorInfo(
                        id=indicator_id, name=name, file_path=fpath,
                        category="custom", has_signals=True,
                    )
                    self._modules[indicator_id] = mod
                    logger.debug(f"Registered indicator: {indicator_id}")
            except Exception as e:
                logger.debug(f"Skipped indicator {indicator_id}: {e}")

    def list_all(self) -> list[IndicatorInfo]:
        return list(self._indicators.values())

    def get(self, indicator_id: str) -> IndicatorInfo | None:
        return self._indicators.get(indicator_id)

    def compute(self, indicator_id: str, df) -> dict:
        """Run a specific indicator on OHLCV data.
        Returns dict with output columns and their values.
        """
        mod = self._modules.get(indicator_id)
        if not mod:
            return {"error": f"Indicator not found: {indicator_id}"}

        try:
            result_df = mod.calculate_indicators(df.copy())
            # Find new columns added by the indicator
            new_cols = [c for c in result_df.columns if c not in df.columns]
            latest = result_df.iloc[-1]
            output = {}
            for col in new_cols:
                val = latest[col]
                if val is not None and not (isinstance(val, float) and __import__("math").isnan(val)):
                    output[col] = val
            return {"columns": new_cols, "latest": output}
        except Exception as e:
            return {"error": str(e)}

    def compute_all_signals(self, df) -> list[dict]:
        """Run all registered indicators and collect signals.
        Returns list of {indicator_id, signals: {column: value}} for signals that fired.
        """
        results = []
        for ind_id, mod in self._modules.items():
            try:
                result_df = mod.calculate_indicators(df.copy())
                new_cols = [c for c in result_df.columns if c not in df.columns]
                latest = result_df.iloc[-1]

                # Check for signal columns (Buy, Sell, bullish, bearish)
                signals = {}
                for col in new_cols:
                    val = latest.get(col)
                    if val and val != 0 and str(col).lower() in [
                        c for c in [col.lower()]
                        if any(s in c for s in ["buy", "sell", "bullish", "bearish", "signal", "long", "short"])
                    ]:
                        signals[col] = val

                if signals:
                    results.append({
                        "indicator_id": ind_id,
                        "name": self._indicators[ind_id].name,
                        "signals": signals,
                    })
            except Exception:
                pass
        return results

# Global singleton
_registry = IndicatorRegistry()

def get_indicator_registry() -> IndicatorRegistry:
    return _registry

def init_indicator_registry():
    """Call at app startup to discover all indicators."""
    _registry.discover()
    logger.info(f"Indicator registry: {len(_registry._indicators)} custom indicators loaded")
