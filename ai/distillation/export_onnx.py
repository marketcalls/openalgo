"""Export fine-tuned DistilBERT to ONNX for fast CPU inference.

Usage:
    python -m ai.distillation.export_onnx --model ml/news_classifier/model --output ml/news_classifier/model.onnx
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
        return_tensors="pt",
        padding="max_length",
        max_length=max_len,
        truncation=True,
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
