from __future__ import annotations

from pathlib import Path

from models.model_registry import load_model_bundle


def load_active_bundle(bundle_root: str | Path):
    return load_model_bundle(bundle_root)
