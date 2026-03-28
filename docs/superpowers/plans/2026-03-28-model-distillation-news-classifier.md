# Model Distillation — Financial News Classifier — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Distil a lightweight financial news sentiment classifier from a large LLM (Ollama/Gemini teacher) into a small fine-tuned `distilbert-base-uncased` student model that runs entirely on CPU, exposed as `/api/v1/agent/news-classify` and shown in a new `NewsClassifyTab` in `AIAnalyzer`.

**Architecture:** Phase 1 generates labelled training data by prompting the teacher LLM on financial headlines. Phase 2 fine-tunes `distilbert-base-uncased` on the labelled data using Hugging Face `transformers`. Phase 3 exports to ONNX for fast CPU inference. The student model replaces VADER for classification while remaining <50 MB. Kaggle notebook provided for GPU training.

**Tech Stack:** `transformers`, `datasets`, `torch` (CPU), `onnxruntime`, `scikit-learn`, Hugging Face Hub (optional export), Flask-RESTX, React/TanStack Query, shadcn/ui

---

## File Structure

| File | Responsibility |
|------|----------------|
| `ai/news_classifier.py` | Student model inference (ONNX or HF) |
| `ai/distillation/generate_labels.py` | Teacher LLM → labelled dataset |
| `ai/distillation/train_student.py` | DistilBERT fine-tuning script |
| `ai/distillation/export_onnx.py` | Export fine-tuned model to ONNX |
| `ml/news_classifier/` | Model artifacts (gitignored) |
| `ml/news_classifier/data/` | Generated training data (gitignored) |
| `restx_api/ai_agent.py` | Add `/news-classify` endpoint |
| `test/test_news_classifier.py` | Unit tests for inference + API |
| `frontend/src/types/strategy-analysis.ts` | Add `NewsClassifyData` |
| `frontend/src/api/strategy-analysis.ts` | Add `newsClassify()` method |
| `frontend/src/hooks/useStrategyAnalysis.ts` | Add `useNewsClassify` |
| `frontend/src/components/ai-analysis/tabs/NewsClassifyTab.tsx` | New tab UI |
| `frontend/src/pages/AIAnalyzer.tsx` | Wire in tab |
| `ml/news_classifier/kaggle_notebook.ipynb` | Kaggle GPU training notebook |

---

## Task 1: Teacher Label Generation

**Files:**
- Create: `ai/distillation/generate_labels.py`
- Create: `ai/distillation/__init__.py`

- [ ] **Step 1: Create `ai/distillation/__init__.py`**

```python
# ai/distillation/__init__.py
```

- [ ] **Step 2: Create label generator**

Create `ai/distillation/generate_labels.py`:

```python
"""Generate labelled financial news dataset using teacher LLM (Ollama).

Labels: 0=Bearish, 1=Neutral, 2=Bullish

Usage:
    python -m ai.distillation.generate_labels --output ml/news_classifier/data/labels.jsonl --n 500
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

# Seed headlines — diverse mix of Indian market news patterns
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
    print(f"Labelled {n} headlines → {args.output}")
```

- [ ] **Step 3: Commit**

```bash
git add ai/distillation/__init__.py ai/distillation/generate_labels.py
git commit -m "feat(distill): add teacher LLM label generator for financial headlines"
```

---

## Task 2: Student Model Fine-Tuning Script

**Files:**
- Create: `ai/distillation/train_student.py`

- [ ] **Step 1: Create training script**

```python
"""Fine-tune DistilBERT on labelled financial headlines (distillation student).

Usage (local CPU — small dataset):
    python -m ai.distillation.train_student \
        --data ml/news_classifier/data/labels.jsonl \
        --output ml/news_classifier/model \
        --epochs 3

For GPU training use the Kaggle notebook at ml/news_classifier/kaggle_notebook.ipynb
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_jsonl(path: str) -> tuple[list[str], list[int]]:
    texts, labels = [], []
    with open(path, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            texts.append(row["text"])
            labels.append(int(row["label"]))
    return texts, labels


def train(data_path: str, output_dir: str, epochs: int = 3, max_len: int = 128) -> dict:
    """Fine-tune distilbert-base-uncased on the labelled dataset."""
    from transformers import (
        DistilBertTokenizerFast,
        DistilBertForSequenceClassification,
        Trainer, TrainingArguments,
    )
    from datasets import Dataset
    import numpy as np
    from sklearn.metrics import accuracy_score, f1_score

    texts, labels = load_jsonl(data_path)
    if len(texts) < 10:
        raise ValueError(f"Need at least 10 labelled examples, found {len(texts)}")

    tokenizer = DistilBertTokenizerFast.from_pretrained("distilbert-base-uncased")
    model = DistilBertForSequenceClassification.from_pretrained(
        "distilbert-base-uncased", num_labels=3
    )

    # Tokenise
    encodings = tokenizer(texts, truncation=True, padding=True, max_length=max_len)
    dataset = Dataset.from_dict({
        "input_ids": encodings["input_ids"],
        "attention_mask": encodings["attention_mask"],
        "labels": labels,
    })
    split = dataset.train_test_split(test_size=0.15, seed=42)

    def compute_metrics(pred):
        logits, labs = pred
        preds = np.argmax(logits, axis=-1)
        return {
            "accuracy": accuracy_score(labs, preds),
            "f1": f1_score(labs, preds, average="weighted"),
        }

    args = TrainingArguments(
        output_dir=output_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=8,
        per_device_eval_batch_size=16,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="f1",
        logging_steps=10,
        no_cuda=True,          # CPU training for local; Kaggle notebook uses GPU
        report_to="none",
    )
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=split["train"],
        eval_dataset=split["test"],
        compute_metrics=compute_metrics,
    )
    trainer.train()
    trainer.save_model(output_dir)
    tokenizer.save_pretrained(output_dir)
    metrics = trainer.evaluate()
    return {"status": "trained", "output_dir": output_dir, "metrics": metrics}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="ml/news_classifier/data/labels.jsonl")
    parser.add_argument("--output", default="ml/news_classifier/model")
    parser.add_argument("--epochs", type=int, default=3)
    args = parser.parse_args()
    result = train(args.data, args.output, args.epochs)
    print(result)
```

- [ ] **Step 2: Install dependencies**

```bash
cd D:\openalgo && uv add transformers datasets torch scikit-learn onnxruntime
```

- [ ] **Step 3: Commit**

```bash
git add ai/distillation/train_student.py pyproject.toml uv.lock
git commit -m "feat(distill): add DistilBERT fine-tuning student training script"
```

---

## Task 3: ONNX Export Script

**Files:**
- Create: `ai/distillation/export_onnx.py`

- [ ] **Step 1: Create ONNX export**

```python
"""Export fine-tuned DistilBERT to ONNX for fast CPU inference.

Usage:
    python -m ai.distillation.export_onnx \
        --model ml/news_classifier/model \
        --output ml/news_classifier/model.onnx
"""
from __future__ import annotations

import argparse
from pathlib import Path


def export_onnx(model_dir: str, onnx_path: str, max_len: int = 128) -> None:
    import torch
    from transformers import DistilBertTokenizerFast, DistilBertForSequenceClassification

    tokenizer = DistilBertTokenizerFast.from_pretrained(model_dir)
    model = DistilBertForSequenceClassification.from_pretrained(model_dir)
    model.eval()

    dummy = tokenizer(
        "Nifty hits all-time high",
        return_tensors="pt", padding="max_length", max_length=max_len, truncation=True
    )
    Path(onnx_path).parent.mkdir(parents=True, exist_ok=True)

    torch.onnx.export(
        model,
        (dummy["input_ids"], dummy["attention_mask"]),
        onnx_path,
        input_names=["input_ids", "attention_mask"],
        output_names=["logits"],
        dynamic_axes={
            "input_ids": {0: "batch", 1: "seq"},
            "attention_mask": {0: "batch", 1: "seq"},
        },
        opset_version=14,
    )
    print(f"Exported ONNX model to {onnx_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="ml/news_classifier/model")
    parser.add_argument("--output", default="ml/news_classifier/model.onnx")
    args = parser.parse_args()
    export_onnx(args.model, args.output)
```

- [ ] **Step 2: Commit**

```bash
git add ai/distillation/export_onnx.py
git commit -m "feat(distill): add ONNX export script for student model"
```

---

## Task 4: Inference Module + Tests

**Files:**
- Create: `ai/news_classifier.py`
- Create: `test/test_news_classifier.py`

- [ ] **Step 1: Write failing tests**

```python
# test/test_news_classifier.py
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
```

- [ ] **Step 2: Run to verify failure**

```bash
cd D:\openalgo && uv run pytest test/test_news_classifier.py -v 2>&1 | head -10
```
Expected: `ModuleNotFoundError: No module named 'ai.news_classifier'`

- [ ] **Step 3: Implement `ai/news_classifier.py`**

```python
"""Financial news headline classifier.

Tries student ONNX model first; falls back to VADER if model not found.

Student labels: 0=Bearish, 1=Neutral, 2=Bullish
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
from utils.logging import get_logger

logger = get_logger(__name__)

MODEL_PATH = Path("ml/news_classifier/model")
ONNX_PATH = Path("ml/news_classifier/model.onnx")
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
    return {"label": label, "confidence": round(float(conf), 4), "model": "vader_fallback", "compound": round(compound, 4)}


def classify_headline(text: str) -> dict:
    """Classify a single headline. Student model if available, else VADER."""
    if not text or not text.strip():
        return {"label": "neutral", "confidence": 1.0, "model": "empty"}

    session, tokenizer = _get_onnx()
    if session is None or tokenizer is None:
        return _vader_classify(text)

    try:
        enc = tokenizer(
            text, return_tensors="np", padding="max_length",
            max_length=MAX_LEN, truncation=True
        )
        logits = session.run(
            ["logits"],
            {"input_ids": enc["input_ids"].astype(np.int64),
             "attention_mask": enc["attention_mask"].astype(np.int64)},
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
```

- [ ] **Step 4: Run tests**

```bash
cd D:\openalgo && uv run pytest test/test_news_classifier.py -v
```
Expected: All 4 pass (VADER fallback path used since no model trained yet).

- [ ] **Step 5: Commit**

```bash
git add ai/news_classifier.py test/test_news_classifier.py
git commit -m "feat(distill): add news classifier with student ONNX + VADER fallback"
```

---

## Task 5: REST Endpoint

**Files:**
- Modify: `restx_api/ai_agent.py`

- [ ] **Step 1: Append endpoint**

```python
@api.route("/news-classify")
class NewsClassifyResource(Resource):
    @limiter.limit("20 per minute")
    def post(self):
        """Classify financial news headlines using distilled student model (VADER fallback)."""
        from flask import request
        data = request.get_json(force=True)
        api_key = data.get("apikey", "")
        headlines = data.get("headlines", [])   # list of strings
        text = data.get("text", "")             # or single string

        if not api_key:
            return {"status": "error", "message": "apikey is required"}, 400
        if _validate_api_key(api_key) is None:
            return {"status": "error", "message": "Invalid openalgo apikey"}, 403

        # Accept single text or list
        if text:
            headlines = [text]
        if not headlines:
            return {"status": "error", "message": "headlines or text is required"}, 400
        if len(headlines) > 50:
            return {"status": "error", "message": "Max 50 headlines per request"}, 400

        try:
            from ai.news_classifier import classify_batch
            results = classify_batch(headlines)
            return {"status": "success", "data": {"results": results, "count": len(results)}}
        except Exception:
            logger.exception("News classify error")
            return {"status": "error", "message": "An unexpected error occurred"}, 500
```

- [ ] **Step 2: Commit**

```bash
git add restx_api/ai_agent.py
git commit -m "feat(distill): add /news-classify REST endpoint"
```

---

## Task 6: TypeScript Types + API + Hook

**Files:**
- Modify: `frontend/src/types/strategy-analysis.ts`
- Modify: `frontend/src/api/strategy-analysis.ts`
- Modify: `frontend/src/hooks/useStrategyAnalysis.ts`

- [ ] **Step 1: Add types**

Append to `frontend/src/types/strategy-analysis.ts`:

```typescript
// ─── News Classifier ───
export interface HeadlineClassification {
  label: 'bearish' | 'neutral' | 'bullish'
  confidence: number
  model: 'student' | 'vader_fallback' | 'empty'
  compound?: number
  probs?: { bearish: number; neutral: number; bullish: number }
}

export interface NewsClassifyData {
  results: HeadlineClassification[]
  count: number
}
```

- [ ] **Step 2: Add API method**

In `strategyApi` in `frontend/src/api/strategy-analysis.ts`:

```typescript
  newsClassify: (apikey: string, headlines: string[]) =>
    post<NewsClassifyData>('/api/v1/agent/news-classify', { apikey, headlines }),
```

Add `NewsClassifyData` to the import.

- [ ] **Step 3: Add hook**

Append to `frontend/src/hooks/useStrategyAnalysis.ts`:

```typescript
export function useNewsClassify(headlines: string[], enabled = true) {
  const apikey = useApiKey()
  return useQuery({
    queryKey: ['news-classify', headlines.join('|').substring(0, 100)],
    queryFn: () => strategyApi.newsClassify(apikey!, headlines),
    enabled: enabled && !!apikey && headlines.length > 0,
    staleTime: 2 * 60_000,
    retry: false,
  })
}
```

- [ ] **Step 4: Build check**

```bash
cd D:\openalgo\frontend && npm run build 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/strategy-analysis.ts frontend/src/api/strategy-analysis.ts frontend/src/hooks/useStrategyAnalysis.ts
git commit -m "feat(distill): add NewsClassifyData type, API method, and useNewsClassify hook"
```

---

## Task 7: React NewsClassifyTab Component

**Files:**
- Create: `frontend/src/components/ai-analysis/tabs/NewsClassifyTab.tsx`
- Modify: `frontend/src/pages/AIAnalyzer.tsx`

- [ ] **Step 1: Create `NewsClassifyTab.tsx`**

```tsx
import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Loader2, Newspaper, TrendingUp, TrendingDown, Minus, Sparkles } from 'lucide-react'
import { useNewsClassify } from '@/hooks/useStrategyAnalysis'
import type { HeadlineClassification } from '@/types/strategy-analysis'

const DEFAULT_HEADLINES = [
  'RBI cuts repo rate, markets rally',
  'IT sector faces US slowdown headwinds',
  'Nifty holds support at 22000',
  'FII buying accelerates in banking stocks',
  'Adani shares fall on regulatory probe',
]

const LABEL_CONFIG = {
  bullish: { color: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400', icon: TrendingUp },
  bearish: { color: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400',         icon: TrendingDown },
  neutral: { color: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400', icon: Minus },
}

function ClassificationRow({ headline, result }: { headline: string; result: HeadlineClassification }) {
  const cfg = LABEL_CONFIG[result.label] ?? LABEL_CONFIG.neutral
  const Icon = cfg.icon
  return (
    <div className="flex items-start gap-3 py-2 border-b last:border-0">
      <div className={`flex items-center gap-1 px-2 py-1 rounded text-xs font-semibold shrink-0 ${cfg.color}`}>
        <Icon className="h-3 w-3" />
        {result.label.toUpperCase()}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm truncate" title={headline}>{headline}</p>
        <p className="text-xs text-muted-foreground">
          {(result.confidence * 100).toFixed(0)}% confidence
          {result.model === 'student' && <span className="ml-1 text-purple-500">· student model</span>}
          {result.model === 'vader_fallback' && <span className="ml-1 text-muted-foreground">· VADER</span>}
        </p>
      </div>
      {result.probs && (
        <div className="flex gap-1 shrink-0">
          <span className="text-xs text-green-600">{(result.probs.bullish * 100).toFixed(0)}%</span>
          <span className="text-xs text-muted-foreground">·</span>
          <span className="text-xs text-red-600">{(result.probs.bearish * 100).toFixed(0)}%</span>
        </div>
      )}
    </div>
  )
}

export function NewsClassifyTab() {
  const [input, setInput] = useState(DEFAULT_HEADLINES.join('\n'))
  const [headlines, setHeadlines] = useState<string[]>([])
  const [run, setRun] = useState(false)
  const { data, isLoading } = useNewsClassify(headlines, run)

  const handleClassify = () => {
    const hl = input.split('\n').map(s => s.trim()).filter(Boolean).slice(0, 50)
    setHeadlines(hl)
    setRun(true)
  }

  const bullCount = data?.results.filter(r => r.label === 'bullish').length ?? 0
  const bearCount = data?.results.filter(r => r.label === 'bearish').length ?? 0
  const neutCount = data?.results.filter(r => r.label === 'neutral').length ?? 0

  return (
    <div className="space-y-4 p-4">
      <div className="flex items-center gap-2">
        <Newspaper className="h-5 w-5 text-blue-500" />
        <h3 className="font-semibold text-lg">News Classifier</h3>
        <Badge variant="outline" className="text-xs">DistilBERT Distilled</Badge>
        <Badge variant="outline" className="text-xs text-purple-600"><Sparkles className="h-3 w-3 mr-1" />AI</Badge>
      </div>

      <Card>
        <CardContent className="pt-4 space-y-2">
          <label className="text-xs text-muted-foreground">Headlines (one per line, max 50)</label>
          <textarea
            className="w-full border rounded px-3 py-2 text-sm bg-background resize-y min-h-28 font-mono"
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder="Enter financial headlines, one per line…"
          />
          <Button onClick={handleClassify} disabled={isLoading} className="w-full">
            {isLoading ? <><Loader2 className="h-4 w-4 animate-spin mr-1" />Classifying…</> : 'Classify Headlines'}
          </Button>
        </CardContent>
      </Card>

      {data && (
        <>
          {/* Summary badges */}
          <div className="flex gap-3">
            <div className="flex items-center gap-1.5 px-3 py-1.5 bg-green-50 dark:bg-green-900/20 rounded-lg">
              <TrendingUp className="h-4 w-4 text-green-600" />
              <span className="text-sm font-semibold text-green-700 dark:text-green-400">{bullCount} Bullish</span>
            </div>
            <div className="flex items-center gap-1.5 px-3 py-1.5 bg-red-50 dark:bg-red-900/20 rounded-lg">
              <TrendingDown className="h-4 w-4 text-red-600" />
              <span className="text-sm font-semibold text-red-700 dark:text-red-400">{bearCount} Bearish</span>
            </div>
            <div className="flex items-center gap-1.5 px-3 py-1.5 bg-yellow-50 dark:bg-yellow-900/20 rounded-lg">
              <Minus className="h-4 w-4 text-yellow-600" />
              <span className="text-sm font-semibold text-yellow-700 dark:text-yellow-400">{neutCount} Neutral</span>
            </div>
          </div>

          <Card>
            <CardHeader className="pb-1">
              <CardTitle className="text-sm">Classification Results</CardTitle>
            </CardHeader>
            <CardContent>
              {data.results.map((r, i) => (
                <ClassificationRow key={i} headline={headlines[i] ?? ''} result={r} />
              ))}
            </CardContent>
          </Card>

          <p className="text-xs text-muted-foreground">
            Model: {data.results[0]?.model === 'student' ? 'DistilBERT student (fine-tuned)' : 'VADER fallback — train student model for higher accuracy'}
          </p>
        </>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Wire into `AIAnalyzer.tsx`**

Add import:
```typescript
import { NewsClassifyTab } from '@/components/ai-analysis/tabs/NewsClassifyTab'
```

Add tab trigger (after portfolio-cvar):
```tsx
<TabsTrigger value="news-classify">
  <Newspaper className="h-4 w-4 mr-1" /> Classifier
</TabsTrigger>
```

Add `Newspaper` to lucide-react imports if not already present.

Add tab content:
```tsx
<TabsContent value="news-classify">
  <NewsClassifyTab />
</TabsContent>
```

- [ ] **Step 3: Build**

```bash
cd D:\openalgo\frontend && npm run build 2>&1 | tail -5
```
Expected: `✓ built in ...`

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ai-analysis/tabs/NewsClassifyTab.tsx frontend/src/pages/AIAnalyzer.tsx
git commit -m "feat(distill): add NewsClassifyTab with headline batch classification UI"
```

---

## Task 8: Kaggle GPU Training Notebook + Gitignore

**Files:**
- Create: `ml/news_classifier/kaggle_notebook.ipynb`
- Modify: `.gitignore`

- [ ] **Step 1: Add gitignore entries**

Append to `.gitignore`:
```
# News classifier model artifacts
ml/news_classifier/model/
ml/news_classifier/model.onnx
ml/news_classifier/data/
```

- [ ] **Step 2: Create Kaggle notebook scaffold**

Create `ml/news_classifier/kaggle_notebook.ipynb` with cells that:
1. Install dependencies: `!pip install transformers datasets torch scikit-learn`
2. Upload `labels.jsonl` as Kaggle dataset input
3. Call `train_student.py` logic with `no_cuda=False` and `epochs=5`
4. Export ONNX
5. Download model artifacts

```json
{
 "nbformat": 4,
 "nbformat_minor": 5,
 "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}},
 "cells": [
  {"cell_type": "markdown", "metadata": {}, "source": ["# FinNews DistilBERT Distillation — Kaggle GPU Training\n", "Upload `labels.jsonl` as a dataset. This notebook fine-tunes DistilBERT on GPU."]},
  {"cell_type": "code", "execution_count": null, "metadata": {}, "outputs": [], "source": ["!pip install -q transformers datasets torch scikit-learn"]},
  {"cell_type": "code", "execution_count": null, "metadata": {}, "outputs": [], "source": [
    "import json, numpy as np\n",
    "from pathlib import Path\n",
    "\n",
    "DATA_PATH = '/kaggle/input/finnews-labels/labels.jsonl'\n",
    "OUTPUT_DIR = '/kaggle/working/model'\n",
    "ONNX_PATH = '/kaggle/working/model.onnx'\n",
    "EPOCHS = 5\n",
    "MAX_LEN = 128\n"
  ]},
  {"cell_type": "code", "execution_count": null, "metadata": {}, "outputs": [], "source": [
    "texts, labels = [], []\n",
    "with open(DATA_PATH) as f:\n",
    "    for line in f:\n",
    "        row = json.loads(line)\n",
    "        texts.append(row['text'])\n",
    "        labels.append(int(row['label']))\n",
    "print(f'Loaded {len(texts)} examples')\n"
  ]},
  {"cell_type": "code", "execution_count": null, "metadata": {}, "outputs": [], "source": [
    "from transformers import DistilBertTokenizerFast, DistilBertForSequenceClassification, Trainer, TrainingArguments\n",
    "from datasets import Dataset\n",
    "from sklearn.metrics import accuracy_score, f1_score\n",
    "\n",
    "tokenizer = DistilBertTokenizerFast.from_pretrained('distilbert-base-uncased')\n",
    "model = DistilBertForSequenceClassification.from_pretrained('distilbert-base-uncased', num_labels=3)\n",
    "\n",
    "enc = tokenizer(texts, truncation=True, padding=True, max_length=MAX_LEN)\n",
    "dataset = Dataset.from_dict({'input_ids': enc['input_ids'], 'attention_mask': enc['attention_mask'], 'labels': labels})\n",
    "split = dataset.train_test_split(test_size=0.15, seed=42)\n",
    "\n",
    "def compute_metrics(pred):\n",
    "    logits, labs = pred\n",
    "    preds = np.argmax(logits, axis=-1)\n",
    "    return {'accuracy': accuracy_score(labs, preds), 'f1': f1_score(labs, preds, average='weighted')}\n",
    "\n",
    "args = TrainingArguments(OUTPUT_DIR, num_train_epochs=EPOCHS, per_device_train_batch_size=16,\n",
    "    eval_strategy='epoch', save_strategy='epoch', load_best_model_at_end=True,\n",
    "    metric_for_best_model='f1', logging_steps=20, report_to='none')\n",
    "trainer = Trainer(model=model, args=args, train_dataset=split['train'], eval_dataset=split['test'], compute_metrics=compute_metrics)\n",
    "trainer.train()\n",
    "trainer.save_model(OUTPUT_DIR)\n",
    "tokenizer.save_pretrained(OUTPUT_DIR)\n",
    "print('Training complete')\n"
  ]},
  {"cell_type": "code", "execution_count": null, "metadata": {}, "outputs": [], "source": [
    "import torch\n",
    "model_eval = DistilBertForSequenceClassification.from_pretrained(OUTPUT_DIR)\n",
    "model_eval.eval()\n",
    "dummy = tokenizer('Nifty hits all-time high', return_tensors='pt', padding='max_length', max_length=MAX_LEN, truncation=True)\n",
    "torch.onnx.export(model_eval, (dummy['input_ids'], dummy['attention_mask']), ONNX_PATH,\n",
    "    input_names=['input_ids','attention_mask'], output_names=['logits'],\n",
    "    dynamic_axes={'input_ids':{0:'batch',1:'seq'},'attention_mask':{0:'batch',1:'seq'}}, opset_version=14)\n",
    "print(f'ONNX exported to {ONNX_PATH}')\n",
    "print('Download model/ and model.onnx from /kaggle/working/')\n"
  ]}
 ]
}
```

- [ ] **Step 3: Commit**

```bash
git add ml/news_classifier/kaggle_notebook.ipynb .gitignore
git commit -m "feat(distill): add Kaggle GPU training notebook and gitignore model artifacts"
```

---

## Final Smoke Test

- [ ] Start OpenAlgo: `cd D:\openalgo && uv run app.py`
- [ ] Navigate to `http://127.0.0.1:5000/react` → AI Analyzer → **Classifier** tab
- [ ] Default headlines should classify via VADER fallback (shows "VADER" badge)
- [ ] To use student model: run `python -m ai.distillation.generate_labels` then `python -m ai.distillation.train_student` then `python -m ai.distillation.export_onnx`
- [ ] Re-classify — results should show "student model" badge
- [ ] Push: `git push origin main:vayu-ml-intelligence`
