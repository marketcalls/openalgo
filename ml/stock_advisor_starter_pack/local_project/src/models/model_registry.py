from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Any

from core.interfaces import ModelBundleMetadata


def save_model_bundle(
    bundle_root: str | Path,
    metadata: ModelBundleMetadata,
    objects: dict[str, Any],
) -> Path:
    root = Path(bundle_root)
    root.mkdir(parents=True, exist_ok=True)
    metadata_payload = metadata.to_dict()
    metadata_payload["artifact_root"] = str(root)
    (root / "metadata.json").write_text(json.dumps(metadata_payload, indent=2), encoding="utf-8")
    with (root / "objects.pkl").open("wb") as handle:
        pickle.dump(objects, handle)
    return root


def load_model_bundle(bundle_root: str | Path) -> tuple[ModelBundleMetadata, dict[str, Any]]:
    root = Path(bundle_root)
    metadata_payload = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    metadata = ModelBundleMetadata(**metadata_payload)
    with (root / "objects.pkl").open("rb") as handle:
        objects = pickle.load(handle)
    return metadata, objects
