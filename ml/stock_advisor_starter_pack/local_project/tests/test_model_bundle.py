from datetime import datetime, timezone
from pathlib import Path

from core.interfaces import ModelBundleMetadata
from models.model_registry import load_model_bundle, save_model_bundle


def test_model_bundle_round_trip(tmp_path: Path):
    metadata = ModelBundleMetadata(
        model_version="test-v1",
        horizon="swing",
        created_at_utc=datetime.now(timezone.utc).isoformat(),
        feature_columns=["a", "b"],
        training_symbols=["RELIANCE"],
    )
    bundle_root = save_model_bundle(tmp_path / "bundle", metadata, {"value": 123})
    loaded_metadata, loaded_objects = load_model_bundle(bundle_root)
    assert loaded_metadata.model_version == "test-v1"
    assert loaded_objects["value"] == 123
