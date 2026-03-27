# ai/decision_engine.py
"""Decision Engine — produces one clear "What To Do" recommendation.

Combines: signal score + confidence + trend + momentum + OI + pattern alerts + ML confidence
into a single actionable recommendation with entry/SL/target.
"""

from dataclasses import dataclass


@dataclass
class TradingDecision:
    action: str          # "BUY NOW", "SELL NOW", "WAIT", "AVOID"
    confidence_label: str  # "High Conviction", "Medium", "Low", "No Setup"
    entry: float
    stop_loss: float
    target: float
    quantity: int
    risk_amount: float
    risk_reward: float
    reason: str          # 1-2 sentence explanation
    risk_warning: str    # Risk disclosure
    supporting_signals: list[str]  # Which indicators agree
    opposing_signals: list[str]    # Which indicators disagree
    score: float         # Overall decision score 0-100


def make_decision(
    signal: str, score: float, confidence: float,
    trend_direction: str, momentum_bias: str,
    trade_setup: dict, advanced_signals: dict,
    ml_buy: float, ml_sell: float,
    oi_bias: str = "neutral", oi_pcr: float = 0,
    account_balance: float = 100000,
    risk_percent: float = 1.0,
) -> TradingDecision:
    """Make a single trading decision from all available data."""

    is_buy = signal in ("STRONG_BUY", "BUY")
    is_sell = signal in ("STRONG_SELL", "SELL")
    is_hold = signal == "HOLD"

    # Count supporting/opposing signals
    supporting = []
    opposing = []

    if trend_direction == "bullish" and is_buy: supporting.append("Trend: Bullish")
    elif trend_direction == "bearish" and is_sell: supporting.append("Trend: Bearish")
    elif trend_direction != "neutral": opposing.append(f"Trend: {trend_direction}")

    if momentum_bias == "bullish" and is_buy: supporting.append("Momentum: Bullish")
    elif momentum_bias == "bearish" and is_sell: supporting.append("Momentum: Bearish")
    elif momentum_bias != "neutral": opposing.append(f"Momentum: {momentum_bias}")

    # OI (Open Interest) bias from option chain
    if oi_bias == "bullish" and is_buy:
        supporting.append(f"OI: Bullish (PCR {oi_pcr:.2f})")
    elif oi_bias == "bearish" and is_sell:
        supporting.append(f"OI: Bearish (PCR {oi_pcr:.2f})")
    elif oi_bias != "neutral":
        opposing.append(f"OI: {oi_bias} (PCR {oi_pcr:.2f})")

    if ml_buy > 60 and is_buy: supporting.append(f"ML: Buy {ml_buy:.0f}%")
    elif ml_sell > 60 and is_sell: supporting.append(f"ML: Sell {ml_sell:.0f}%")

    smc = advanced_signals.get("smc", {})
    if any("bullish" in k for k in smc):
        if is_buy: supporting.append("SMC: Bullish structure")
        else: opposing.append("SMC: Bullish structure")
    if any("bearish" in k for k in smc):
        if is_sell: supporting.append("SMC: Bearish structure")
        else: opposing.append("SMC: Bearish structure")

    candlestick = advanced_signals.get("candlestick", [])
    if candlestick: supporting.append(f"Candlestick: {', '.join(candlestick[:2])}")

    diverg = advanced_signals.get("divergence", {})
    if diverg.get("rsi_bullish") and is_buy: supporting.append("RSI Bullish Divergence")
    if diverg.get("rsi_bearish") and is_sell: supporting.append("RSI Bearish Divergence")

    # Decision scoring
    agreement = len(supporting) / max(len(supporting) + len(opposing), 1)
    decision_score = confidence * 0.4 + agreement * 100 * 0.3 + abs(score) * 100 * 0.3
    decision_score = min(decision_score, 100)

    # Action: BUY/SELL signals always produce actionable recommendation
    # Only HOLD signal produces WAIT
    if is_hold:
        action = "WAIT"
        conf_label = "No Setup"
    elif is_buy or is_sell:
        if decision_score > 70:
            conf_label = "High Conviction"
        elif decision_score > 50:
            conf_label = "Medium Conviction"
        else:
            conf_label = "Low Conviction"
        action = "BUY NOW" if is_buy else "SELL NOW"
    else:
        action = "WAIT"
        conf_label = "No Setup"

    # Trade params from setup
    entry = trade_setup.get("entry", 0)
    sl = trade_setup.get("stop_loss", 0)
    target = trade_setup.get("target_1", 0)
    rr = trade_setup.get("risk_reward_1", 0)
    qty = trade_setup.get("suggested_qty", 0)
    risk = trade_setup.get("risk_amount", 0)

    # Risk-based quantity from account balance
    if entry > 0 and sl > 0 and account_balance > 0:
        max_risk = account_balance * risk_percent / 100
        sl_distance = abs(entry - sl)
        if sl_distance > 0:
            qty = max(int(max_risk / sl_distance), 1)
            risk = qty * sl_distance

    # Reason
    if action == "WAIT":
        reason = f"No clear setup. Signal is {signal} with {confidence:.0f}% confidence. Wait for better entry."
    else:
        direction = "buying" if is_buy else "selling"
        reason = f"{conf_label} {direction} setup. {len(supporting)} signals agree, {len(opposing)} oppose. Score: {decision_score:.0f}/100."

    # Risk warning
    if rr < 1.5:
        risk_warning = "Low R:R ratio — consider waiting for better entry"
    elif len(opposing) > len(supporting):
        risk_warning = "More signals opposing than supporting — trade with caution"
    elif confidence < 40:
        risk_warning = "Low confidence — use smaller position size"
    else:
        risk_warning = "Setup looks reasonable — follow your risk management rules"

    return TradingDecision(
        action=action, confidence_label=conf_label,
        entry=round(entry, 2), stop_loss=round(sl, 2), target=round(target, 2),
        quantity=qty, risk_amount=round(risk, 2), risk_reward=round(rr, 2),
        reason=reason, risk_warning=risk_warning,
        supporting_signals=supporting, opposing_signals=opposing,
        score=round(decision_score, 1),
    )
