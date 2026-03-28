"""Fine-tune DistilBERT on labelled financial headlines (distillation student).

Usage (local CPU):
    python -m ai.distillation.train_student --data ml/news_classifier/data/labels.jsonl --output ml/news_classifier/model --epochs 3

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
        Trainer,
        TrainingArguments,
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
        no_cuda=True,
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
