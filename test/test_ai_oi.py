import pytest
from ai.oi_analysis import compute_oi_score, OIReport


def _mock_chain():
    """Mock option chain data matching OpenAlgo format."""
    return {
        "underlying": "NIFTY",
        "underlying_ltp": 24500.0,
        "atm_strike": 24500.0,
        "chain": [
            {"strike": 24300, "ce": {"oi": 50000, "volume": 10000, "ltp": 250}, "pe": {"oi": 30000, "volume": 8000, "ltp": 50}},
            {"strike": 24400, "ce": {"oi": 80000, "volume": 15000, "ltp": 150}, "pe": {"oi": 45000, "volume": 12000, "ltp": 80}},
            {"strike": 24500, "ce": {"oi": 120000, "volume": 25000, "ltp": 80}, "pe": {"oi": 100000, "volume": 20000, "ltp": 80}},
            {"strike": 24600, "ce": {"oi": 60000, "volume": 8000, "ltp": 30}, "pe": {"oi": 90000, "volume": 18000, "ltp": 150}},
            {"strike": 24700, "ce": {"oi": 40000, "volume": 5000, "ltp": 10}, "pe": {"oi": 70000, "volume": 14000, "ltp": 250}},
        ],
    }


def test_returns_oi_report():
    result = compute_oi_score(_mock_chain())
    assert isinstance(result, OIReport)


def test_has_required_fields():
    result = compute_oi_score(_mock_chain())
    assert isinstance(result.pcr_oi, float)
    assert isinstance(result.pcr_volume, float)
    assert isinstance(result.max_pain, float)
    assert result.bias in ("bullish", "bearish", "neutral")
    assert isinstance(result.details, dict)


def test_pcr_calculation():
    result = compute_oi_score(_mock_chain())
    total_pe_oi = 30000 + 45000 + 100000 + 90000 + 70000  # 335000
    total_ce_oi = 50000 + 80000 + 120000 + 60000 + 40000  # 350000
    expected_pcr = total_pe_oi / total_ce_oi
    assert abs(result.pcr_oi - expected_pcr) < 0.01


def test_max_pain_in_range():
    result = compute_oi_score(_mock_chain())
    assert 24300 <= result.max_pain <= 24700


def test_details_has_levels():
    result = compute_oi_score(_mock_chain())
    assert "max_ce_oi_strike" in result.details
    assert "max_pe_oi_strike" in result.details
    assert "total_ce_oi" in result.details
    assert "total_pe_oi" in result.details


def test_empty_chain_returns_neutral():
    result = compute_oi_score({"chain": [], "underlying_ltp": 0})
    assert result.bias == "neutral"
