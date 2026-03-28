"""Financial news headline classifier.

Tries student ONNX model first; falls back to VADER if model not found.

Student labels: 0=Bearish, 1=Neutral, 2=Bullish
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from utils.logging import get_logger

logger = get_logger(__name__)

MODEL_DIR = Path(__file__).parent.parent / "ml" / "news_classifier"
MODEL_PATH = MODEL_DIR / "model"
ONNX_PATH = MODEL_DIR / "model.onnx"
LABELS = ["bearish", "neutral", "bullish"]
MAX_LEN = 128

# Singletons — loaded once
_ort_session = None
_tokenizer = None
_vader = None


def _get_onnx():
    global _ort_session, _tokenizer
    if _ort_session is not None:
        return _ort_session, _tokenizer
    if not ONNX_PATH.exists():
        return None, None
    try:
        import onnxruntime as ort
        from transformers import DistilBertTokenizerFast

        _tokenizer = DistilBertTokenizerFast.from_pretrained(str(MODEL_PATH))
        _ort_session = ort.InferenceSession(str(ONNX_PATH), providers=["CPUExecutionProvider"])
        logger.info("Loaded student ONNX classifier from %s", ONNX_PATH)
    except Exception:
        logger.exception("Failed to load ONNX model")
        _ort_session = None
        _tokenizer = None
    return _ort_session, _tokenizer


def _get_vader():
    global _vader
    if _vader is not None:
        return _vader
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

        _vader = SentimentIntensityAnalyzer()
    except ImportError:
        _vader = None
    return _vader


def _vader_classify(text: str) -> dict:
    vader = _get_vader()
    if vader is None:
        return {"label": "neutral", "confidence": 0.5, "model": "vader_fallback"}
    scores = vader.polarity_scores(text)
    compound = scores["compound"]
    if compound >= 0.05:
        label, conf = "bullish", min((compound + 1) / 2, 1.0)
    elif compound <= -0.05:
        label, conf = "bearish", min((1 - compound) / 2, 1.0)
    else:
        label, conf = "neutral", 1.0 - abs(compound) * 5
    return {
        "label": label,
        "confidence": round(float(conf), 4),
        "model": "vader_fallback",
        "compound": round(compound, 4),
    }


def classify_headline(text: str) -> dict:
    """Classify a single headline. Student model if available, else VADER."""
    if not text or not text.strip():
        return {"label": "neutral", "confidence": 1.0, "model": "empty"}

    session, tokenizer = _get_onnx()
    if session is None or tokenizer is None:
        return _vader_classify(text)

    try:
        enc = tokenizer(
            text,
            return_tensors="np",
            padding="max_length",
            max_length=MAX_LEN,
            truncation=True,
        )
        logits = session.run(
            ["logits"],
            {
                "input_ids": enc["input_ids"].astype(np.int64),
                "attention_mask": enc["attention_mask"].astype(np.int64),
            },
        )[0][0]
        probs = np.exp(logits) / np.exp(logits).sum()
        idx = int(np.argmax(probs))
        return {
            "label": LABELS[idx],
            "confidence": round(float(probs[idx]), 4),
            "probs": {LABELS[i]: round(float(probs[i]), 4) for i in range(3)},
            "model": "student",
        }
    except Exception:
        logger.exception("ONNX inference failed, falling back to VADER")
        return _vader_classify(text)


def classify_batch(texts: list[str]) -> list[dict]:
    """Classify multiple headlines."""
    return [classify_headline(t) for t in texts]
