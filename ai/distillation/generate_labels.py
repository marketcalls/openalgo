"""Generate labelled financial news dataset using teacher LLM (Ollama).

Labels: 0=Bearish, 1=Neutral, 2=Bullish

Usage:
    python -m ai.distillation.generate_labels --output ml/news_classifier/data/labels.jsonl
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

SEED_HEADLINES = [
    "RBI cuts repo rate by 25 basis points, market rallies",
    "Reliance Industries reports record quarterly profit",
    "SEBI tightens F&O norms, derivatives volumes fall",
    "IT sector faces headwinds as US recession fears mount",
    "Nifty hits all-time high amid FII buying",
    "Adani Group shares plunge on short-seller report",
    "Budget 2024: Capital gains tax hiked, market sells off",
    "TCS wins $2 billion deal from European bank",
    "India GDP growth beats estimates at 7.8%",
    "Banking stocks under pressure as NPA concerns rise",
    "RBI holds rates, inflation remains elevated",
    "HDFC Bank merger complete, synergies expected",
    "Global recession fears weigh on Indian markets",
    "Nifty50 consolidates ahead of election results",
    "FII outflows continue for third consecutive month",
]

PROMPT_TEMPLATE = """You are a financial sentiment classifier. Classify this Indian stock market headline as:
- bearish (negative for stocks)
- neutral (no clear direction)
- bullish (positive for stocks)

Headline: "{headline}"

Reply with ONLY one word: bearish, neutral, or bullish"""

LABEL_MAP = {"bearish": 0, "neutral": 1, "bullish": 2}


def _call_ollama(headline: str, model: str = "llama3.2:1b") -> str | None:
    """Call local Ollama to get sentiment label."""
    try:
        import requests
        resp = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": model, "prompt": PROMPT_TEMPLATE.format(headline=headline), "stream": False},
            timeout=30,
        )
        text = resp.json().get("response", "").strip().lower()
        for key in LABEL_MAP:
            if key in text:
                return key
        return None
    except Exception:
        return None


def generate_labels(
    headlines: list[str],
    output_path: str,
    model: str = "llama3.2:1b",
    delay: float = 0.2,
) -> int:
    """Label headlines with teacher LLM and write to JSONL."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with open(out, "a", encoding="utf-8") as f:
        for hl in headlines:
            label_str = _call_ollama(hl, model)
            if label_str is None:
                continue
            record = {"text": hl, "label": LABEL_MAP[label_str], "label_str": label_str}
            f.write(json.dumps(record) + "\n")
            written += 1
            time.sleep(delay)
    return written


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="ml/news_classifier/data/labels.jsonl")
    parser.add_argument("--model", default="llama3.2:1b")
    args = parser.parse_args()
    n = generate_labels(SEED_HEADLINES, args.output, model=args.model)
    print(f"Labelled {n} headlines -> {args.output}")
