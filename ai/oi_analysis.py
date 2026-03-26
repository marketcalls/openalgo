"""OI (Open Interest) analysis for options chains.

Computes: PCR (Put-Call Ratio), Max Pain, OI buildup direction,
support/resistance from OI concentration.
"""

from dataclasses import dataclass, field

from utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class OIReport:
    pcr_oi: float       # Put-Call Ratio by OI (>1 = bullish, <0.7 = bearish)
    pcr_volume: float   # Put-Call Ratio by Volume
    max_pain: float     # Strike with minimum total pain
    bias: str           # "bullish", "bearish", "neutral"
    score: float        # -100 to +100
    details: dict = field(default_factory=dict)


def compute_oi_score(chain_data: dict) -> OIReport:
    """Compute OI-based market bias from option chain data.

    Args:
        chain_data: OpenAlgo option chain format with {chain: [{strike, ce, pe}], underlying_ltp}
    """
    chain = chain_data.get("chain", [])
    ltp = chain_data.get("underlying_ltp", 0)

    if not chain:
        return OIReport(pcr_oi=0, pcr_volume=0, max_pain=0, bias="neutral", score=0)

    # Extract OI and volume
    total_ce_oi = 0
    total_pe_oi = 0
    total_ce_vol = 0
    total_pe_vol = 0
    max_ce_oi = 0
    max_ce_oi_strike = 0
    max_pe_oi = 0
    max_pe_oi_strike = 0

    strikes = []
    for item in chain:
        strike = item.get("strike", 0)
        ce = item.get("ce", {}) or {}
        pe = item.get("pe", {}) or {}

        ce_oi = ce.get("oi", 0) or 0
        pe_oi = pe.get("oi", 0) or 0
        ce_vol = ce.get("volume", 0) or 0
        pe_vol = pe.get("volume", 0) or 0

        total_ce_oi += ce_oi
        total_pe_oi += pe_oi
        total_ce_vol += ce_vol
        total_pe_vol += pe_vol

        if ce_oi > max_ce_oi:
            max_ce_oi = ce_oi
            max_ce_oi_strike = strike
        if pe_oi > max_pe_oi:
            max_pe_oi = pe_oi
            max_pe_oi_strike = strike

        strikes.append({"strike": strike, "ce_oi": ce_oi, "pe_oi": pe_oi})

    # PCR
    pcr_oi = total_pe_oi / total_ce_oi if total_ce_oi > 0 else 0
    pcr_volume = total_pe_vol / total_ce_vol if total_ce_vol > 0 else 0

    # Max Pain calculation
    max_pain = _calculate_max_pain(strikes)

    # OI-based bias scoring
    scores = []

    # PCR signal: >1.2 = bullish (puts being written = support), <0.7 = bearish
    if pcr_oi > 1.2:
        scores.append(40)
    elif pcr_oi > 1.0:
        scores.append(20)
    elif pcr_oi < 0.7:
        scores.append(-40)
    elif pcr_oi < 0.9:
        scores.append(-20)
    else:
        scores.append(0)

    # Max Pain vs LTP: price tends to move toward max pain
    if ltp > 0 and max_pain > 0:
        pain_diff = (max_pain - ltp) / ltp * 100
        if pain_diff > 1:  # Max pain above -> bullish pull
            scores.append(30)
        elif pain_diff < -1:  # Max pain below -> bearish pull
            scores.append(-30)
        else:
            scores.append(0)

    # OI concentration: heavy CE OI above LTP = resistance, heavy PE OI below = support
    if max_ce_oi_strike > ltp:
        scores.append(-15)  # Resistance above
    if max_pe_oi_strike < ltp:
        scores.append(15)   # Support below

    total_score = sum(scores)
    total_score = max(min(total_score, 100), -100)

    if total_score > 20:
        bias = "bullish"
    elif total_score < -20:
        bias = "bearish"
    else:
        bias = "neutral"

    return OIReport(
        pcr_oi=round(pcr_oi, 4),
        pcr_volume=round(pcr_volume, 4),
        max_pain=max_pain,
        bias=bias,
        score=round(total_score, 1),
        details={
            "total_ce_oi": total_ce_oi,
            "total_pe_oi": total_pe_oi,
            "max_ce_oi_strike": max_ce_oi_strike,
            "max_pe_oi_strike": max_pe_oi_strike,
            "max_ce_oi": max_ce_oi,
            "max_pe_oi": max_pe_oi,
        },
    )


def _calculate_max_pain(strikes: list[dict]) -> float:
    """Find strike with minimum total writer pain."""
    if not strikes:
        return 0

    min_pain = float("inf")
    max_pain_strike = strikes[0]["strike"]

    for candidate in strikes:
        cs = candidate["strike"]
        ce_pain = sum(max(cs - s["strike"], 0) * s["ce_oi"] for s in strikes)
        pe_pain = sum(max(s["strike"] - cs, 0) * s["pe_oi"] for s in strikes)
        total = ce_pain + pe_pain
        if total < min_pain:
            min_pain = total
            max_pain_strike = cs

    return float(max_pain_strike)
