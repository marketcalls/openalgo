# ai/chart_data_builder.py
"""Builds chart overlay data from indicator results.

Outputs:
- lines: [{time, value}] for EMA, SMA, Supertrend
- bands: [{time, upper, lower}] for Bollinger, Keltner
- markers: [{time, position, shape, color, text}] for signals
- levels: [{price, color, label}] for CPR, Fibonacci
"""
import math


def build_chart_overlays(df, indicators: dict, cpr: dict = None, trade_setup: dict = None) -> dict:
    """Build all chart overlay data from an indicator-enriched DataFrame."""
    overlays = {"lines": [], "bands": [], "markers": [], "levels": []}

    n = min(len(df), 200)
    chart_df = df.tail(n)

    # --- Lines: EMA, SMA, Supertrend ---
    for col, color, label in [
        ("ema_9", "#f59e0b", "EMA 9"),
        ("ema_21", "#3b82f6", "EMA 21"),
        ("sma_50", "#8b5cf6", "SMA 50"),
        ("supertrend", "#10b981", "Supertrend"),
    ]:
        if col in chart_df.columns:
            line_data = []
            for i, row in chart_df.iterrows():
                val = row.get(col)
                if val and not (isinstance(val, float) and math.isnan(val)):
                    line_data.append({"time": int(i), "value": round(float(val), 2)})
            if line_data:
                overlays["lines"].append({"id": col, "label": label, "color": color, "data": line_data})

    # --- Bands: Bollinger ---
    if "bb_high" in chart_df.columns and "bb_low" in chart_df.columns:
        band_data = []
        for i, row in chart_df.iterrows():
            bh = row.get("bb_high")
            bl = row.get("bb_low")
            if bh and bl and not (math.isnan(bh) or math.isnan(bl)):
                band_data.append({"time": int(i), "upper": round(float(bh), 2), "lower": round(float(bl), 2)})
        if band_data:
            overlays["bands"].append({"id": "bb", "label": "Bollinger Bands", "color": "#94a3b8", "data": band_data})

    # --- Levels: CPR, Trade Setup ---
    if cpr:
        for key, color in [("r3", "#ef4444"), ("r2", "#f87171"), ("r1", "#fb923c"),
                           ("tc", "#a78bfa"), ("pivot", "#3b82f6"), ("bc", "#a78bfa"),
                           ("s1", "#22c55e"), ("s2", "#4ade80"), ("s3", "#86efac")]:
            val = cpr.get(key)
            if val and val > 0:
                overlays["levels"].append({"price": round(float(val), 2), "color": color, "label": key.upper()})

    if trade_setup:
        if trade_setup.get("entry"):
            overlays["levels"].append({"price": trade_setup["entry"], "color": "#3b82f6", "label": "Entry"})
        if trade_setup.get("stop_loss"):
            overlays["levels"].append({"price": trade_setup["stop_loss"], "color": "#dc2626", "label": "SL"})
        if trade_setup.get("target_1"):
            overlays["levels"].append({"price": trade_setup["target_1"], "color": "#16a34a", "label": "T1"})
        if trade_setup.get("target_2"):
            overlays["levels"].append({"price": trade_setup["target_2"], "color": "#22c55e", "label": "T2"})

    return overlays
