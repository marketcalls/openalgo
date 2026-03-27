# test/test_ai_decision_engine.py
import pytest
from ai.decision_engine import TradingDecision, make_decision


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_setup():
    """Trade setup dict with realistic values."""
    return {
        "entry": 100.0,
        "stop_loss": 95.0,
        "target_1": 115.0,
        "risk_reward_1": 3.0,
        "suggested_qty": 10,
        "risk_amount": 500.0,
    }


def _base_advanced_signals(**overrides):
    base = {"smc": {}, "candlestick": [], "divergence": {}}
    base.update(overrides)
    return base


def _bullish_advanced():
    return {
        "smc": {"bullish_ob": True},
        "candlestick": ["Hammer", "Morning Star"],
        "divergence": {"rsi_bullish": True, "rsi_bearish": False},
    }


def _bearish_advanced():
    return {
        "smc": {"bearish_ob": True},
        "candlestick": ["Shooting Star", "Evening Star"],
        "divergence": {"rsi_bullish": False, "rsi_bearish": True},
    }


# ---------------------------------------------------------------------------
# TradingDecision dataclass
# ---------------------------------------------------------------------------

def test_dataclass_fields():
    d = TradingDecision(
        action="WAIT", confidence_label="No Setup",
        entry=0, stop_loss=0, target=0, quantity=0,
        risk_amount=0, risk_reward=0, reason="", risk_warning="",
        supporting_signals=[], opposing_signals=[], score=0,
    )
    assert d.action == "WAIT"
    assert d.confidence_label == "No Setup"
    assert d.entry == 0
    assert d.stop_loss == 0
    assert d.target == 0
    assert d.quantity == 0
    assert d.risk_amount == 0
    assert d.risk_reward == 0
    assert d.reason == ""
    assert d.risk_warning == ""
    assert d.supporting_signals == []
    assert d.opposing_signals == []
    assert d.score == 0


# ---------------------------------------------------------------------------
# BUY signal — all bullish → "BUY NOW" High Conviction
# ---------------------------------------------------------------------------

def test_buy_all_bullish_high_conviction():
    d = make_decision(
        signal="STRONG_BUY", score=0.9, confidence=85,
        trend_direction="bullish", momentum_bias="bullish",
        trade_setup=_base_setup(), advanced_signals=_bullish_advanced(),
        ml_buy=75, ml_sell=10,
    )
    assert d.action == "BUY NOW"
    assert d.confidence_label == "High Conviction"
    assert d.score > 70


# ---------------------------------------------------------------------------
# SELL signal — bearish signals → "SELL NOW"
# ---------------------------------------------------------------------------

def test_sell_bearish_signals():
    setup = _base_setup()
    setup["entry"] = 200.0
    setup["stop_loss"] = 210.0
    setup["target_1"] = 180.0
    d = make_decision(
        signal="STRONG_SELL", score=-0.8, confidence=80,
        trend_direction="bearish", momentum_bias="bearish",
        trade_setup=setup, advanced_signals=_bearish_advanced(),
        ml_buy=10, ml_sell=75,
    )
    assert d.action == "SELL NOW"
    assert "SELL" in d.action


# ---------------------------------------------------------------------------
# HOLD signal → "WAIT"
# ---------------------------------------------------------------------------

def test_hold_signal_returns_wait():
    d = make_decision(
        signal="HOLD", score=0.0, confidence=50,
        trend_direction="neutral", momentum_bias="neutral",
        trade_setup=_base_setup(), advanced_signals=_base_advanced_signals(),
        ml_buy=50, ml_sell=50,
    )
    assert d.action == "WAIT"
    assert d.confidence_label == "No Setup"


# ---------------------------------------------------------------------------
# Low confidence → appropriate label
# ---------------------------------------------------------------------------

def test_low_confidence_label():
    d = make_decision(
        signal="BUY", score=0.3, confidence=20,
        trend_direction="neutral", momentum_bias="neutral",
        trade_setup=_base_setup(), advanced_signals=_base_advanced_signals(),
        ml_buy=30, ml_sell=30,
    )
    # Low confidence + no agreement + low score → low decision_score
    # 20*0.4 + 0*0.3 + 30*0.3 = 8 + 0 + 9 = 17 < 30 → WAIT
    assert d.action == "WAIT" or d.confidence_label in ("Low Conviction", "No Setup")


def test_medium_confidence_label():
    d = make_decision(
        signal="BUY", score=0.5, confidence=60,
        trend_direction="bullish", momentum_bias="neutral",
        trade_setup=_base_setup(), advanced_signals=_base_advanced_signals(),
        ml_buy=30, ml_sell=30,
    )
    # 60*0.4 + (1/1)*100*0.3 + 50*0.3 = 24 + 30 + 15 = 69 → Medium
    assert d.confidence_label in ("Medium Conviction", "High Conviction")


# ---------------------------------------------------------------------------
# Risk-based quantity calculation
# ---------------------------------------------------------------------------

def test_risk_based_quantity():
    d = make_decision(
        signal="BUY", score=0.7, confidence=70,
        trend_direction="bullish", momentum_bias="bullish",
        trade_setup=_base_setup(),
        advanced_signals=_base_advanced_signals(),
        ml_buy=65, ml_sell=10,
        account_balance=100000, risk_percent=1.0,
    )
    # max_risk = 100000 * 1/100 = 1000
    # sl_distance = |100 - 95| = 5
    # qty = int(1000 / 5) = 200
    assert d.quantity == 200
    assert d.risk_amount == 200 * 5.0  # 1000.0


def test_risk_based_quantity_custom_balance():
    d = make_decision(
        signal="BUY", score=0.7, confidence=70,
        trend_direction="bullish", momentum_bias="bullish",
        trade_setup=_base_setup(),
        advanced_signals=_base_advanced_signals(),
        ml_buy=65, ml_sell=10,
        account_balance=50000, risk_percent=2.0,
    )
    # max_risk = 50000 * 2/100 = 1000
    # sl_distance = 5 → qty = 200
    assert d.quantity == 200


# ---------------------------------------------------------------------------
# Quantity = 1 minimum when sl_distance very large
# ---------------------------------------------------------------------------

def test_quantity_minimum_one():
    setup = _base_setup()
    setup["entry"] = 100.0
    setup["stop_loss"] = 1.0  # sl_distance = 99
    d = make_decision(
        signal="BUY", score=0.7, confidence=70,
        trend_direction="bullish", momentum_bias="bullish",
        trade_setup=setup, advanced_signals=_base_advanced_signals(),
        ml_buy=65, ml_sell=10,
        account_balance=50, risk_percent=1.0,
    )
    # max_risk = 50 * 0.01 = 0.5, sl_distance = 99
    # int(0.5 / 99) = int(0.005) = 0 → max(0, 1) = 1
    assert d.quantity == 1


# ---------------------------------------------------------------------------
# Supporting vs opposing signal counting
# ---------------------------------------------------------------------------

def test_supporting_opposing_counts():
    d = make_decision(
        signal="BUY", score=0.6, confidence=70,
        trend_direction="bullish", momentum_bias="bearish",
        trade_setup=_base_setup(), advanced_signals=_base_advanced_signals(),
        ml_buy=65, ml_sell=10,
    )
    assert "Trend: Bullish" in d.supporting_signals
    assert "Momentum: bearish" in d.opposing_signals


def test_all_opposing_for_buy_with_bearish():
    d = make_decision(
        signal="BUY", score=0.3, confidence=40,
        trend_direction="bearish", momentum_bias="bearish",
        trade_setup=_base_setup(), advanced_signals=_base_advanced_signals(),
        ml_buy=30, ml_sell=30,
    )
    assert "Trend: bearish" in d.opposing_signals
    assert "Momentum: bearish" in d.opposing_signals


# ---------------------------------------------------------------------------
# SMC bullish/bearish detection
# ---------------------------------------------------------------------------

def test_smc_bullish_supporting():
    adv = _base_advanced_signals(smc={"bullish_ob": True})
    d = make_decision(
        signal="BUY", score=0.6, confidence=60,
        trend_direction="bullish", momentum_bias="bullish",
        trade_setup=_base_setup(), advanced_signals=adv,
        ml_buy=65, ml_sell=10,
    )
    assert "SMC: Bullish structure" in d.supporting_signals


def test_smc_bearish_opposing_for_buy():
    adv = _base_advanced_signals(smc={"bearish_ob": True})
    d = make_decision(
        signal="BUY", score=0.6, confidence=60,
        trend_direction="bullish", momentum_bias="bullish",
        trade_setup=_base_setup(), advanced_signals=adv,
        ml_buy=65, ml_sell=10,
    )
    assert "SMC: Bearish structure" in d.opposing_signals


def test_smc_bearish_supporting_for_sell():
    setup = _base_setup()
    setup["entry"] = 200.0
    setup["stop_loss"] = 210.0
    adv = _base_advanced_signals(smc={"bearish_ob": True})
    d = make_decision(
        signal="SELL", score=-0.6, confidence=60,
        trend_direction="bearish", momentum_bias="bearish",
        trade_setup=setup, advanced_signals=adv,
        ml_buy=10, ml_sell=65,
    )
    assert "SMC: Bearish structure" in d.supporting_signals


# ---------------------------------------------------------------------------
# Candlestick pattern inclusion
# ---------------------------------------------------------------------------

def test_candlestick_in_supporting():
    adv = _base_advanced_signals(candlestick=["Hammer", "Morning Star", "Engulfing"])
    d = make_decision(
        signal="BUY", score=0.6, confidence=60,
        trend_direction="bullish", momentum_bias="bullish",
        trade_setup=_base_setup(), advanced_signals=adv,
        ml_buy=65, ml_sell=10,
    )
    # Only first 2 patterns included
    matching = [s for s in d.supporting_signals if s.startswith("Candlestick:")]
    assert len(matching) == 1
    assert "Hammer" in matching[0]
    assert "Morning Star" in matching[0]
    # Third pattern NOT included in the label
    assert "Engulfing" not in matching[0]


def test_empty_candlestick_not_in_supporting():
    adv = _base_advanced_signals(candlestick=[])
    d = make_decision(
        signal="BUY", score=0.6, confidence=60,
        trend_direction="bullish", momentum_bias="bullish",
        trade_setup=_base_setup(), advanced_signals=adv,
        ml_buy=65, ml_sell=10,
    )
    assert not any(s.startswith("Candlestick:") for s in d.supporting_signals)


# ---------------------------------------------------------------------------
# Divergence signals
# ---------------------------------------------------------------------------

def test_rsi_bullish_divergence_for_buy():
    adv = _base_advanced_signals(divergence={"rsi_bullish": True, "rsi_bearish": False})
    d = make_decision(
        signal="BUY", score=0.6, confidence=60,
        trend_direction="bullish", momentum_bias="bullish",
        trade_setup=_base_setup(), advanced_signals=adv,
        ml_buy=65, ml_sell=10,
    )
    assert "RSI Bullish Divergence" in d.supporting_signals


def test_rsi_bearish_divergence_for_sell():
    setup = _base_setup()
    setup["entry"] = 200.0
    setup["stop_loss"] = 210.0
    adv = _base_advanced_signals(divergence={"rsi_bullish": False, "rsi_bearish": True})
    d = make_decision(
        signal="SELL", score=-0.6, confidence=60,
        trend_direction="bearish", momentum_bias="bearish",
        trade_setup=setup, advanced_signals=adv,
        ml_buy=10, ml_sell=65,
    )
    assert "RSI Bearish Divergence" in d.supporting_signals


def test_rsi_bullish_divergence_ignored_for_sell():
    setup = _base_setup()
    setup["entry"] = 200.0
    setup["stop_loss"] = 210.0
    adv = _base_advanced_signals(divergence={"rsi_bullish": True, "rsi_bearish": False})
    d = make_decision(
        signal="SELL", score=-0.6, confidence=60,
        trend_direction="bearish", momentum_bias="bearish",
        trade_setup=setup, advanced_signals=adv,
        ml_buy=10, ml_sell=65,
    )
    assert "RSI Bullish Divergence" not in d.supporting_signals


# ---------------------------------------------------------------------------
# ML confidence thresholds
# ---------------------------------------------------------------------------

def test_ml_buy_above_threshold():
    d = make_decision(
        signal="BUY", score=0.6, confidence=60,
        trend_direction="bullish", momentum_bias="bullish",
        trade_setup=_base_setup(), advanced_signals=_base_advanced_signals(),
        ml_buy=75, ml_sell=10,
    )
    assert any("ML: Buy" in s for s in d.supporting_signals)


def test_ml_buy_below_threshold():
    d = make_decision(
        signal="BUY", score=0.6, confidence=60,
        trend_direction="bullish", momentum_bias="bullish",
        trade_setup=_base_setup(), advanced_signals=_base_advanced_signals(),
        ml_buy=55, ml_sell=10,
    )
    assert not any("ML:" in s for s in d.supporting_signals)


def test_ml_sell_above_threshold():
    setup = _base_setup()
    setup["entry"] = 200.0
    setup["stop_loss"] = 210.0
    d = make_decision(
        signal="SELL", score=-0.6, confidence=60,
        trend_direction="bearish", momentum_bias="bearish",
        trade_setup=setup, advanced_signals=_base_advanced_signals(),
        ml_buy=10, ml_sell=80,
    )
    assert any("ML: Sell" in s for s in d.supporting_signals)


def test_ml_sell_below_threshold():
    setup = _base_setup()
    setup["entry"] = 200.0
    setup["stop_loss"] = 210.0
    d = make_decision(
        signal="SELL", score=-0.6, confidence=60,
        trend_direction="bearish", momentum_bias="bearish",
        trade_setup=setup, advanced_signals=_base_advanced_signals(),
        ml_buy=10, ml_sell=55,
    )
    assert not any("ML:" in s for s in d.supporting_signals)


# ---------------------------------------------------------------------------
# Risk warnings
# ---------------------------------------------------------------------------

def test_risk_warning_low_rr():
    setup = _base_setup()
    setup["risk_reward_1"] = 1.0  # low R:R
    d = make_decision(
        signal="BUY", score=0.7, confidence=80,
        trend_direction="bullish", momentum_bias="bullish",
        trade_setup=setup, advanced_signals=_bullish_advanced(),
        ml_buy=75, ml_sell=10,
    )
    assert "Low R:R" in d.risk_warning


def test_risk_warning_more_opposing():
    setup = _base_setup()
    setup["risk_reward_1"] = 2.0
    d = make_decision(
        signal="BUY", score=0.3, confidence=50,
        trend_direction="bearish", momentum_bias="bearish",
        trade_setup=setup, advanced_signals=_base_advanced_signals(),
        ml_buy=30, ml_sell=30,
    )
    assert "opposing" in d.risk_warning.lower()


def test_risk_warning_low_confidence():
    setup = _base_setup()
    setup["risk_reward_1"] = 2.0
    d = make_decision(
        signal="BUY", score=0.6, confidence=30,
        trend_direction="bullish", momentum_bias="bullish",
        trade_setup=setup, advanced_signals=_base_advanced_signals(),
        ml_buy=65, ml_sell=10,
    )
    assert "Low confidence" in d.risk_warning


def test_risk_warning_reasonable():
    setup = _base_setup()
    setup["risk_reward_1"] = 3.0
    d = make_decision(
        signal="BUY", score=0.7, confidence=80,
        trend_direction="bullish", momentum_bias="bullish",
        trade_setup=setup, advanced_signals=_bullish_advanced(),
        ml_buy=75, ml_sell=10,
    )
    assert "reasonable" in d.risk_warning.lower()


# ---------------------------------------------------------------------------
# Reason text — WAIT vs BUY/SELL
# ---------------------------------------------------------------------------

def test_reason_wait():
    d = make_decision(
        signal="HOLD", score=0.0, confidence=50,
        trend_direction="neutral", momentum_bias="neutral",
        trade_setup=_base_setup(), advanced_signals=_base_advanced_signals(),
        ml_buy=50, ml_sell=50,
    )
    assert "No clear setup" in d.reason
    assert "Wait for better entry" in d.reason


def test_reason_buy():
    d = make_decision(
        signal="STRONG_BUY", score=0.9, confidence=85,
        trend_direction="bullish", momentum_bias="bullish",
        trade_setup=_base_setup(), advanced_signals=_bullish_advanced(),
        ml_buy=75, ml_sell=10,
    )
    assert "buying" in d.reason
    assert "signals agree" in d.reason
    assert "Score:" in d.reason


def test_reason_sell():
    setup = _base_setup()
    setup["entry"] = 200.0
    setup["stop_loss"] = 210.0
    d = make_decision(
        signal="STRONG_SELL", score=-0.8, confidence=80,
        trend_direction="bearish", momentum_bias="bearish",
        trade_setup=setup, advanced_signals=_bearish_advanced(),
        ml_buy=10, ml_sell=75,
    )
    assert "selling" in d.reason


# ---------------------------------------------------------------------------
# Decision score capped at 100
# ---------------------------------------------------------------------------

def test_decision_score_capped():
    d = make_decision(
        signal="STRONG_BUY", score=1.0, confidence=100,
        trend_direction="bullish", momentum_bias="bullish",
        trade_setup=_base_setup(), advanced_signals=_bullish_advanced(),
        ml_buy=99, ml_sell=0,
    )
    assert d.score <= 100


def test_decision_score_nonnegative():
    d = make_decision(
        signal="HOLD", score=0.0, confidence=0,
        trend_direction="neutral", momentum_bias="neutral",
        trade_setup=_base_setup(), advanced_signals=_base_advanced_signals(),
        ml_buy=0, ml_sell=0,
    )
    assert d.score >= 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_entry_and_sl_zero_skips_qty_calc():
    setup = {"entry": 0, "stop_loss": 0, "target_1": 0,
             "risk_reward_1": 0, "suggested_qty": 5, "risk_amount": 100}
    d = make_decision(
        signal="BUY", score=0.5, confidence=60,
        trend_direction="bullish", momentum_bias="bullish",
        trade_setup=setup, advanced_signals=_base_advanced_signals(),
        ml_buy=65, ml_sell=10,
    )
    # entry=0 so risk-based calc is skipped, uses setup values
    assert d.quantity == 5
    assert d.risk_amount == 100


def test_neutral_trend_no_opposing():
    d = make_decision(
        signal="BUY", score=0.5, confidence=60,
        trend_direction="neutral", momentum_bias="neutral",
        trade_setup=_base_setup(), advanced_signals=_base_advanced_signals(),
        ml_buy=55, ml_sell=10,
    )
    assert "Trend: neutral" not in d.opposing_signals
    assert "Momentum: neutral" not in d.opposing_signals


def test_strong_sell_with_bullish_trend_opposing():
    setup = _base_setup()
    setup["entry"] = 200.0
    setup["stop_loss"] = 210.0
    d = make_decision(
        signal="STRONG_SELL", score=-0.7, confidence=60,
        trend_direction="bullish", momentum_bias="bullish",
        trade_setup=setup, advanced_signals=_base_advanced_signals(),
        ml_buy=10, ml_sell=65,
    )
    assert "Trend: bullish" in d.opposing_signals
    assert "Momentum: bullish" in d.opposing_signals
