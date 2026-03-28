"""Tests for the financial news headline classifier."""
import pytest


def test_classify_with_vader_fallback():
    """When no student model exists, falls back to VADER."""
    from ai.news_classifier import classify_headline
    result = classify_headline("Nifty hits all-time high amid FII buying")
    assert result["label"] in ("bearish", "neutral", "bullish")
    assert 0.0 <= result["confidence"] <= 1.0
    assert result["model"] in ("student", "vader_fallback")


def test_classify_batch():
    from ai.news_classifier import classify_batch
    headlines = [
        "Reliance reports record profit",
        "Market falls on recession fears",
        "RBI holds rates unchanged",
    ]
    results = classify_batch(headlines)
    assert len(results) == 3
    for r in results:
        assert r["label"] in ("bearish", "neutral", "bullish")


def test_classify_returns_confidence():
    from ai.news_classifier import classify_headline
    result = classify_headline("TCS stock tanks 8% on weak guidance")
    assert isinstance(result["confidence"], float)
    assert result["confidence"] > 0


def test_classify_empty_headline():
    from ai.news_classifier import classify_headline
    result = classify_headline("")
    assert result["label"] == "neutral"
