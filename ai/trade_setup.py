"""Trade setup calculator — entry, stop loss, targets, and position sizing.

Uses signal direction + ATR for SL distance + CPR/Fibonacci for targets.
Calculates quantity based on risk amount and SL distance.
"""

from dataclasses import dataclass, field

import pandas as pd
from utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class TradeSetup:
    action: str  # "BUY", "SELL", or "NO_TRADE"
    entry: float = 0.0
    stop_loss: float = 0.0
    target_1: float = 0.0
    target_2: float = 0.0
    target_3: float = 0.0
    sl_distance: float = 0.0  # Absolute distance from entry to SL
    sl_percent: float = 0.0   # SL as % of entry
    risk_reward_1: float = 0.0  # R:R for target 1
    risk_reward_2: float = 0.0
    risk_reward_3: float = 0.0
    suggested_qty: int = 0
    risk_amount: float = 0.0
    reason: str = ""
    details: dict = field(default_factory=dict)


def compute_trade_setup(
    signal: str,
    score: float,
    confidence: float,
    indicators: dict,
    cpr_levels: dict | None = None,
    ltp: float = 0.0,
    risk_per_trade: float = 1000.0,  # Max risk in ₹
    lot_size: int = 1,
) -> TradeSetup:
    """Compute entry, SL, targets, and quantity from analysis results.

    Args:
        signal: STRONG_BUY, BUY, SELL, STRONG_SELL, HOLD
        score: Composite score (-1 to +1)
        confidence: 0-100
        indicators: Dict with rsi_14, atr_14, ema_9, ema_21, supertrend, bb_high, bb_low, etc.
        cpr_levels: Dict with pivot, r1, s1, r2, s2, etc.
        ltp: Last traded price
        risk_per_trade: Maximum risk amount in INR
        lot_size: Lot size for F&O (1 for equity)
    """
    if signal in ("HOLD", "NO_TRADE") or ltp <= 0:
        return TradeSetup(action="NO_TRADE", reason="Signal is HOLD or no price data")

    is_buy = signal in ("STRONG_BUY", "BUY")
    is_strong = signal in ("STRONG_BUY", "STRONG_SELL")

    atr = indicators.get("atr_14", 0)
    supertrend = indicators.get("supertrend", 0)
    ema_9 = indicators.get("ema_9", 0)
    ema_21 = indicators.get("ema_21", 0)
    bb_high = indicators.get("bb_high", 0)
    bb_low = indicators.get("bb_low", 0)

    # --- Entry ---
    entry = ltp

    # --- Stop Loss ---
    if atr and atr > 0:
        # ATR-based SL: 1.5x ATR for normal, 2x for strong signals
        sl_multiplier = 2.0 if is_strong else 1.5
        sl_distance = atr * sl_multiplier
    else:
        # Fallback: 1.5% of price
        sl_distance = ltp * 0.015

    if is_buy:
        stop_loss = entry - sl_distance
        # Tighten SL to nearest support if available
        if cpr_levels:
            s1 = cpr_levels.get("s1", 0)
            bc = cpr_levels.get("bc", 0)
            support = s1 if s1 and s1 < entry else bc
            if support and support > 0 and support < entry and (entry - support) < sl_distance * 1.5:
                stop_loss = support - (atr * 0.2 if atr else ltp * 0.002)
                sl_distance = entry - stop_loss
        # Also consider supertrend as SL
        if supertrend and 0 < supertrend < entry and (entry - supertrend) < sl_distance * 1.3:
            stop_loss = max(stop_loss, supertrend - (atr * 0.1 if atr else 0))
            sl_distance = entry - stop_loss
    else:
        stop_loss = entry + sl_distance
        if cpr_levels:
            r1 = cpr_levels.get("r1", 0)
            tc = cpr_levels.get("tc", 0)
            resistance = r1 if r1 and r1 > entry else tc
            if resistance and resistance > entry and (resistance - entry) < sl_distance * 1.5:
                stop_loss = resistance + (atr * 0.2 if atr else ltp * 0.002)
                sl_distance = stop_loss - entry

    sl_distance = abs(entry - stop_loss)
    sl_percent = (sl_distance / entry * 100) if entry > 0 else 0

    # --- Targets (1:1, 1:2, 1:3 R:R based on SL distance) ---
    if is_buy:
        target_1 = entry + sl_distance * 1.0  # 1:1 R:R
        target_2 = entry + sl_distance * 2.0  # 1:2 R:R
        target_3 = entry + sl_distance * 3.0  # 1:3 R:R
        # Adjust targets to CPR/BB levels if nearby
        if cpr_levels:
            r1 = cpr_levels.get("r1", 0)
            r2 = cpr_levels.get("r2", 0)
            if r1 and abs(r1 - target_1) < sl_distance * 0.5:
                target_1 = r1
            if r2 and abs(r2 - target_2) < sl_distance * 0.5:
                target_2 = r2
        if bb_high and abs(bb_high - target_1) < sl_distance * 0.5:
            target_1 = bb_high
    else:
        target_1 = entry - sl_distance * 1.0
        target_2 = entry - sl_distance * 2.0
        target_3 = entry - sl_distance * 3.0
        if cpr_levels:
            s1 = cpr_levels.get("s1", 0)
            s2 = cpr_levels.get("s2", 0)
            if s1 and abs(s1 - target_1) < sl_distance * 0.5:
                target_1 = s1
            if s2 and abs(s2 - target_2) < sl_distance * 0.5:
                target_2 = s2
        if bb_low and abs(bb_low - target_1) < sl_distance * 0.5:
            target_1 = bb_low

    # --- Risk:Reward ratios ---
    rr1 = abs(target_1 - entry) / sl_distance if sl_distance > 0 else 0
    rr2 = abs(target_2 - entry) / sl_distance if sl_distance > 0 else 0
    rr3 = abs(target_3 - entry) / sl_distance if sl_distance > 0 else 0

    # --- Position Sizing ---
    if sl_distance > 0:
        raw_qty = risk_per_trade / sl_distance
        # Round to lot size
        suggested_qty = max(int(raw_qty / lot_size) * lot_size, lot_size)
        risk_amount = suggested_qty * sl_distance
    else:
        suggested_qty = lot_size
        risk_amount = 0

    # Build reason
    reasons = []
    if is_buy:
        reasons.append(f"{'Strong ' if is_strong else ''}Buy signal (score: {score:.2f})")
    else:
        reasons.append(f"{'Strong ' if is_strong else ''}Sell signal (score: {score:.2f})")
    if atr:
        reasons.append(f"ATR-based SL: {sl_distance:.2f} ({sl_percent:.1f}%)")
    if confidence > 70:
        reasons.append("High confidence — consider full position")
    elif confidence < 40:
        reasons.append("Low confidence — consider half position")

    return TradeSetup(
        action="BUY" if is_buy else "SELL",
        entry=round(entry, 2),
        stop_loss=round(stop_loss, 2),
        target_1=round(target_1, 2),
        target_2=round(target_2, 2),
        target_3=round(target_3, 2),
        sl_distance=round(sl_distance, 2),
        sl_percent=round(sl_percent, 2),
        risk_reward_1=round(rr1, 2),
        risk_reward_2=round(rr2, 2),
        risk_reward_3=round(rr3, 2),
        suggested_qty=suggested_qty,
        risk_amount=round(risk_amount, 2),
        reason=" | ".join(reasons),
        details={
            "atr": round(atr, 2) if atr else None,
            "supertrend": round(supertrend, 2) if supertrend else None,
            "confidence": confidence,
        },
    )
