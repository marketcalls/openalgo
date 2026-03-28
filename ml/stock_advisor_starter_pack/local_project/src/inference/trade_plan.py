from __future__ import annotations

from typing import Any


def build_trade_plan(
    last_close: float,
    side: int,
    confidence: float,
    atr: float | None = None,
) -> dict[str, Any]:
    atr = atr or max(last_close * 0.01, 1.0)
    entry = float(last_close)
    if side >= 0:
        stop_loss = entry - 1.5 * atr
        target_1 = entry + 1.0 * atr
        target_2 = entry + 2.0 * atr
    else:
        stop_loss = entry + 1.5 * atr
        target_1 = entry - 1.0 * atr
        target_2 = entry - 2.0 * atr

    return {
        "entry": round(entry, 2),
        "stop_loss": round(stop_loss, 2),
        "target_1": round(target_1, 2),
        "target_2": round(target_2, 2),
        "confidence": round(float(confidence), 4),
    }
