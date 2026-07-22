import json
import logging

import pytest

from openalgo_config import (
    ConfigStore,
    OCSValidationError,
    build_runtime_config,
    normalize_schema,
    validate_values,
)


def test_normalize_schema_and_validate_values_coerces_supported_types():
    schema = normalize_schema(
        {
            "strategy": "ema",
            "fields": [
                {"key": "symbol", "type": "symbol", "default": "RELIANCE"},
                {"key": "fast_ema", "type": "int", "default": 9, "min": 1, "max": 200},
                {"key": "risk", "type": "float", "default": 1.5, "min": 0.1},
                {"key": "enabled", "type": "bool", "default": True},
                {"key": "exchange", "type": "exchange", "default": "NSE", "options": ["NSE", "MCX"]},
            ],
        },
        "ema",
    )

    values = validate_values(
        schema,
        {
            "symbol": "SBIN",
            "fast_ema": "21",
            "risk": "2.25",
            "enabled": "true",
            "exchange": "MCX",
        },
    )

    assert values == {
        "symbol": "SBIN",
        "fast_ema": 21,
        "risk": 2.25,
        "enabled": True,
        "exchange": "MCX",
    }


def test_validate_values_rejects_unknown_and_out_of_range_values():
    schema = normalize_schema(
        {
            "fields": [
                {"key": "quantity", "type": "quantity", "default": 1, "min": 1, "max": 10},
            ],
        }
    )

    with pytest.raises(OCSValidationError) as exc:
        validate_values(schema, {"quantity": 20, "extra": "nope"})

    fields = {error["field"] for error in exc.value.errors}
    assert fields == {"quantity", "extra"}


def test_validate_values_preserves_select_option_value_types():
    numeric_schema = normalize_schema(
        {"fields": [{"key": "mode", "type": "select", "options": [1, 2]}]}
    )
    bool_schema = normalize_schema(
        {"fields": [{"key": "enabled_mode", "type": "select", "options": [True, False]}]}
    )
    multi_schema = normalize_schema(
        {"fields": [{"key": "legs", "type": "multi_select", "options": [1, 2]}]}
    )

    assert validate_values(numeric_schema, {"mode": "1"}) == {"mode": 1}
    assert validate_values(bool_schema, {"enabled_mode": "true"}) == {"enabled_mode": True}
    assert validate_values(multi_schema, {"legs": ["1", 2]}) == {"legs": [1, 2]}


def test_validate_values_applies_regex_after_select_option_match():
    schema = normalize_schema(
        {
            "fields": [
                {
                    "key": "code",
                    "type": "select",
                    "options": ["ABC", "abc"],
                    "regex": "^[A-Z]+$",
                }
            ]
        }
    )

    assert validate_values(schema, {"code": "ABC"}) == {"code": "ABC"}
    with pytest.raises(OCSValidationError) as exc:
        validate_values(schema, {"code": "abc"})

    assert exc.value.errors[0]["field"] == "code"


def test_normalize_schema_rejects_invalid_regex():
    with pytest.raises(OCSValidationError) as exc:
        normalize_schema(
            {
                "fields": [
                    {
                        "key": "code",
                        "type": "select",
                        "options": ["ABC"],
                        "regex": "[",
                    }
                ]
            }
        )

    assert exc.value.errors[0]["field"] == "fields[0].regex"


def test_validate_values_wraps_persisted_invalid_regex():
    with pytest.raises(OCSValidationError) as exc:
        validate_values(
            {
                "fields": [
                    {
                        "key": "code",
                        "type": "select",
                        "options": ["ABC"],
                        "regex": "[",
                    }
                ]
            },
            {"code": "ABC"},
        )

    assert exc.value.errors[0]["field"] == "fields[0].regex"


def test_config_store_persists_schema_and_values(tmp_path):
    store = ConfigStore(tmp_path)
    schema = store.save_schema(
        "ema_20260627",
        {
            "fields": [
                {"key": "fast", "type": "int", "default": 9},
                {"key": "slow", "type": "int", "default": 21},
            ],
        },
    )
    values = store.save_values("ema_20260627", {"fast": "13"})

    assert schema["fields"][0]["key"] == "fast"
    assert values == {"fast": 13, "slow": 21}
    assert build_runtime_config(store, "ema_20260627") == {"fast": 13, "slow": 21}


def test_config_store_prunes_stale_values_when_schema_changes(tmp_path):
    store = ConfigStore(tmp_path)
    store.save_schema(
        "ema_20260627",
        {"fields": [{"key": "fast", "type": "int", "default": 9}]},
    )
    store.save_values("ema_20260627", {"fast": "13"})

    store.save_schema(
        "ema_20260627",
        {"fields": [{"key": "slow", "type": "int", "default": 21}]},
    )

    assert store.get_values("ema_20260627") == {"slow": 21}


def test_config_store_saves_schema_when_required_field_has_no_default(tmp_path):
    store = ConfigStore(tmp_path)
    schema = store.save_schema(
        "required_20260627",
        {"fields": [{"key": "symbol", "type": "symbol", "required": True}]},
    )

    assert schema["fields"][0]["key"] == "symbol"
    assert store.get_values("required_20260627", allow_invalid=True) == {}
    with pytest.raises(OCSValidationError):
        store.get_values("required_20260627")


def test_python_strategy_injects_ocs_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(logging, "raiseExceptions", False)
    monkeypatch.setenv("LOG_FORMAT", "[%(asctime)s] %(levelname)s in %(module)s: %(message)s")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

    from blueprints import python_strategy as ps

    store = ConfigStore(tmp_path)
    store.save_schema(
        "ema_20260627",
        {
            "fields": [
                {"key": "symbol", "type": "symbol", "default": "RELIANCE"},
                {"key": "fast", "type": "int", "default": 9},
            ],
        },
    )
    store.save_values("ema_20260627", {"symbol": "SBIN", "fast": "13"})
    monkeypatch.setattr(ps, "OCS_STORE", store)

    env = {}
    ps.inject_ocs_environment(env, "ema_20260627")

    assert json.loads(env["OPENALGO_CONFIG_JSON"]) == {"symbol": "SBIN", "fast": 13}
    assert json.loads(env["OPENALGO_CONFIG_SCHEMA_JSON"])["strategy"] == "ema_20260627"
    assert env["OPENALGO_CONFIG_SYMBOL"] == "SBIN"
    assert env["OPENALGO_CONFIG_FAST"] == "13"


def test_python_strategy_config_response_values_keep_draft_when_runtime_invalid(tmp_path, monkeypatch):
    monkeypatch.setattr(logging, "raiseExceptions", False)
    monkeypatch.setenv("LOG_FORMAT", "[%(asctime)s] %(levelname)s in %(module)s: %(message)s")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

    from blueprints import python_strategy as ps

    store = ConfigStore(tmp_path)
    store.save_schema(
        "required_20260627",
        {"fields": [{"key": "symbol", "type": "symbol", "required": True}]},
    )
    monkeypatch.setattr(ps, "OCS_STORE", store)

    values, resolved_values, validation_errors = ps._build_ocs_config_response_values(
        "required_20260627"
    )

    assert values == {}
    assert resolved_values == values
    assert validation_errors[0]["field"] == "symbol"


def test_python_strategy_syncs_embedded_default_ocs_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(logging, "raiseExceptions", False)
    monkeypatch.setenv("LOG_FORMAT", "[%(asctime)s] %(levelname)s in %(module)s: %(message)s")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

    from blueprints import python_strategy as ps

    strategy_file = tmp_path / "ema.py"
    monkeypatch.setattr(ps, "STRATEGIES_DIR", tmp_path)
    strategy_file.write_text(
        """
DEFAULT_OCS_SCHEMA = {
    "strategy": "ema",
    "fields": [
        {"key": "symbol", "type": "symbol", "default": "NHPC"},
        {"key": "fast_period", "type": "int", "default": 5},
    ],
}

print("trading code must not execute during schema extraction")
""",
        encoding="utf-8",
    )

    store = ConfigStore(tmp_path / "configs")
    monkeypatch.setattr(ps, "OCS_STORE", store)

    schema = ps.sync_ocs_schema_from_strategy_file(
        "ema_20260627", {"file_path": str(strategy_file)}
    )

    assert schema is not None
    assert [field["key"] for field in schema["fields"]] == ["symbol", "fast_period"]
    assert store.get_values("ema_20260627") == {"symbol": "NHPC", "fast_period": 5}


def test_python_strategy_syncs_ui_declarations(tmp_path, monkeypatch):
    monkeypatch.setattr(logging, "raiseExceptions", False)
    monkeypatch.setenv("LOG_FORMAT", "[%(asctime)s] %(levelname)s in %(module)s: %(message)s")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

    from blueprints import python_strategy as ps

    strategy_file = tmp_path / "ui_ema.py"
    monkeypatch.setattr(ps, "STRATEGIES_DIR", tmp_path)
    strategy_file.write_text(
        """
from openalgo_config import ui

ignored_symbol = ui.symbol(default="IGNORED", label="Ignored Symbol")
symbol = ui.symbol("symbol", default="NHPC", label="Symbol", required=True)
ignored_fast = ui.int(default=3, label="Ignored Fast EMA")
fast_period = ui.int("fast_period", default=5, min=1, max=200, label="Fast EMA")
debug = ui.bool("debug", default=False)
""",
        encoding="utf-8",
    )

    store = ConfigStore(tmp_path / "configs")
    monkeypatch.setattr(ps, "OCS_STORE", store)

    schema = ps.sync_ocs_schema_from_strategy_file(
        "ui_ema_20260627", {"file_path": str(strategy_file)}
    )

    assert schema is not None
    assert [field["key"] for field in schema["fields"]] == [
        "symbol",
        "fast_period",
        "debug",
    ]
    assert store.get_values("ui_ema_20260627") == {
        "symbol": "NHPC",
        "fast_period": 5,
        "debug": False,
    }


def test_python_strategy_ignores_empty_or_directory_file_path(tmp_path, monkeypatch):
    monkeypatch.setattr(logging, "raiseExceptions", False)
    monkeypatch.setenv("LOG_FORMAT", "[%(asctime)s] %(levelname)s in %(module)s: %(message)s")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

    from blueprints import python_strategy as ps

    monkeypatch.setattr(ps, "STRATEGIES_DIR", tmp_path / "strategies" / "scripts")
    ps.STRATEGIES_DIR.mkdir(parents=True)

    assert ps.get_valid_strategy_file_path({"file_path": ""}) is None
    assert ps.get_valid_strategy_file_path({"file_path": "."}) is None
    assert ps.sync_ocs_schema_from_strategy_file("legacy", {"file_path": ""}) is None
