"""Schema, validation, and JSON persistence for OpenAlgo Configuration SDK.

OCS intentionally starts as a language-neutral JSON contract. Python Strategy
Host can use it today, and SDK bindings can emit the same shape later.
"""

from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

DEFAULT_OCS_VERSION = "1.0"

SUPPORTED_FIELD_TYPES = {
    "int",
    "float",
    "bool",
    "string",
    "password",
    "select",
    "multi_select",
    "symbol",
    "exchange",
    "product",
    "broker",
    "timeframe",
    "quantity",
    "lot_size",
    "percentage",
    "price",
    "trigger_price",
    "expiry",
    "strike",
    "option_type",
    "color",
    "date",
    "time",
    "session",
    "json",
}

FIELD_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class OCSValidationError(ValueError):
    """Raised when an OCS schema or value payload is invalid."""

    def __init__(self, message: str, errors: list[dict[str, str]] | None = None):
        super().__init__(message)
        self.errors = errors or [{"field": "_schema", "message": message}]


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    raise OCSValidationError("Expected a list")


def _field_error(field: str, message: str) -> dict[str, str]:
    return {"field": field, "message": message}


def _option_value(option: Any) -> Any:
    return option.get("value") if isinstance(option, dict) else option


def _coerce_option_value(field: dict[str, Any], option: Any) -> Any:
    option_value = _option_value(option)
    option_field = {key: value for key, value in field.items() if key != "options"}
    option_field["required"] = False
    return _coerce_value(option_field, option_value)


def _option_matches(value: Any, option_value: Any) -> bool:
    if value == option_value:
        return True
    if isinstance(option_value, bool):
        return str(value).strip().lower() == str(option_value).lower()
    return str(value) == str(option_value)


def _coerce_value(field: dict[str, Any], value: Any) -> Any:
    field_type = field["type"]
    key = field["key"]

    if value is None or value == "":
        if field.get("required"):
            raise OCSValidationError(
                f"{key} is required", [_field_error(key, "This field is required")]
            )
        return None

    try:
        if field_type in {"int", "quantity", "lot_size", "strike"}:
            coerced = int(value)
        elif field_type in {"float", "percentage", "price", "trigger_price"}:
            coerced = float(value)
        elif field_type == "bool":
            if isinstance(value, bool):
                coerced = value
            elif isinstance(value, str):
                coerced = value.strip().lower() in {"1", "true", "yes", "on"}
            else:
                coerced = bool(value)
        elif field_type == "multi_select":
            coerced = _as_list(value)
        elif field_type == "select":
            coerced = value
        elif field_type == "json":
            if isinstance(value, str):
                coerced = json.loads(value)
            else:
                coerced = value
        else:
            coerced = str(value)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise OCSValidationError(
            f"{key} has invalid type",
            [_field_error(key, f"Expected {field_type}: {exc}")],
        ) from exc

    if isinstance(coerced, (int, float)) and not isinstance(coerced, bool):
        min_value = field.get("min")
        max_value = field.get("max")
        if min_value is not None and coerced < min_value:
            raise OCSValidationError(
                f"{key} is below minimum",
                [_field_error(key, f"Must be at least {min_value}")],
            )
        if max_value is not None and coerced > max_value:
            raise OCSValidationError(
                f"{key} is above maximum",
                [_field_error(key, f"Must be at most {max_value}")],
            )

    options = field.get("options")
    if options:
        raw_option_values = [_option_value(item) for item in options]
        if field_type == "select":
            for option_value in raw_option_values:
                if _option_matches(coerced, option_value):
                    coerced = option_value
                    break
            else:
                raise OCSValidationError(
                    f"{key} is not an allowed option",
                    [_field_error(key, "Choose one of the allowed values")],
                )

        elif field_type == "multi_select":
            matched_values = []
            invalid = []
            for item in coerced:
                for option_value in raw_option_values:
                    if _option_matches(item, option_value):
                        matched_values.append(option_value)
                        break
                else:
                    invalid.append(item)
            if invalid:
                raise OCSValidationError(
                    f"{key} includes invalid option",
                    [_field_error(key, f"Invalid option(s): {', '.join(map(str, invalid))}")],
                )
            coerced = matched_values
        else:
            option_values = [_coerce_option_value(field, item) for item in options]
            if coerced not in option_values:
                raise OCSValidationError(
                    f"{key} is not an allowed option",
                    [_field_error(key, "Choose one of the allowed values")],
                )

    pattern = field.get("regex")
    if pattern and coerced is not None:
        try:
            matches_pattern = re.search(str(pattern), str(coerced))
        except re.error as exc:
            raise OCSValidationError(
                f"{key} has invalid regex",
                [_field_error(key, f"Invalid regex pattern: {exc}")],
            ) from exc
        if not matches_pattern:
            raise OCSValidationError(
                f"{key} does not match pattern",
                [_field_error(key, "Value does not match the required pattern")],
            )

    return coerced


def normalize_schema(schema: dict[str, Any] | None, strategy_id: str = "") -> dict[str, Any]:
    """Validate and normalize a schema dict into the OCS v1 shape."""
    raw_schema = deepcopy(schema or {})
    errors: list[dict[str, str]] = []

    if not isinstance(raw_schema, dict):
        raise OCSValidationError("Schema must be a JSON object")

    normalized = {
        "ocs_version": str(raw_schema.get("ocs_version") or DEFAULT_OCS_VERSION),
        "strategy": str(raw_schema.get("strategy") or strategy_id or ""),
        "title": str(raw_schema.get("title") or raw_schema.get("strategy") or strategy_id or ""),
        "description": str(raw_schema.get("description") or ""),
        "fields": [],
    }

    fields = raw_schema.get("fields", [])
    if not isinstance(fields, list):
        errors.append(_field_error("fields", "Fields must be a list"))
        fields = []

    seen_keys: set[str] = set()
    for idx, raw_field in enumerate(fields):
        location = f"fields[{idx}]"
        if not isinstance(raw_field, dict):
            errors.append(_field_error(location, "Field must be an object"))
            continue

        key = str(raw_field.get("key") or "").strip()
        field_type = str(raw_field.get("type") or "string").strip()

        if not key or not FIELD_KEY_RE.match(key):
            errors.append(
                _field_error(f"{location}.key", "Use letters, numbers, and underscores; start with a letter or underscore")
            )
            continue
        if key in seen_keys:
            errors.append(_field_error(f"{location}.key", "Field keys must be unique"))
            continue
        if field_type not in SUPPORTED_FIELD_TYPES:
            errors.append(_field_error(f"{location}.type", f"Unsupported type: {field_type}"))
            continue

        field = {
            "key": key,
            "type": field_type,
            "label": str(raw_field.get("label") or raw_field.get("name") or key.replace("_", " ").title()),
            "required": bool(raw_field.get("required", False)),
        }

        for optional_key in (
            "default",
            "description",
            "tooltip",
            "placeholder",
            "group",
            "tab",
            "section",
            "min",
            "max",
            "step",
            "regex",
            "options",
            "visible_if",
            "enabled_if",
        ):
            if optional_key in raw_field:
                field[optional_key] = raw_field[optional_key]

        if "regex" in field:
            try:
                re.compile(str(field["regex"]))
            except re.error as exc:
                errors.append(
                    _field_error(f"{location}.regex", f"Invalid regex pattern: {exc}")
                )
                continue

        if field_type in {"select", "multi_select", "exchange", "product", "option_type"}:
            options = field.get("options")
            if options is not None and not isinstance(options, list):
                errors.append(_field_error(f"{location}.options", "Options must be a list"))
                continue

        if "default" in field:
            try:
                field["default"] = _coerce_value(field, field["default"])
            except OCSValidationError as exc:
                errors.extend(
                    _field_error(f"{location}.default", err["message"]) for err in exc.errors
                )
                continue

        seen_keys.add(key)
        normalized["fields"].append(field)

    if errors:
        raise OCSValidationError("Schema validation failed", errors)

    return normalized


def validate_values(schema: dict[str, Any] | None, values: dict[str, Any] | None) -> dict[str, Any]:
    """Return coerced values merged with field defaults."""
    normalized_schema = normalize_schema(schema)
    provided = values or {}
    if not isinstance(provided, dict):
        raise OCSValidationError("Values must be a JSON object")

    errors: list[dict[str, str]] = []
    result: dict[str, Any] = {}
    fields = normalized_schema.get("fields", [])
    field_keys = {field["key"] for field in fields}

    for field in fields:
        key = field["key"]
        raw_value = provided.get(key, field.get("default"))
        try:
            coerced = _coerce_value(field, raw_value)
        except OCSValidationError as exc:
            errors.extend(exc.errors)
            continue
        if coerced is not None:
            result[key] = coerced

    for key in provided:
        if key not in field_keys:
            errors.append(_field_error(key, "Unknown configuration key"))

    if errors:
        raise OCSValidationError("Value validation failed", errors)

    return result


def default_values_for_schema(schema: dict[str, Any] | None) -> dict[str, Any]:
    """Return best-effort defaults without enforcing required fields."""
    normalized_schema = normalize_schema(schema)
    defaults: dict[str, Any] = {}
    for field in normalized_schema.get("fields", []):
        if "default" in field:
            defaults[field["key"]] = field["default"]
    return defaults


def merge_schema_defaults(schema: dict[str, Any] | None, values: dict[str, Any] | None) -> dict[str, Any]:
    """Merge known values with defaults without requiring every field to exist."""
    normalized_schema = normalize_schema(schema)
    provided = values or {}
    valid_keys = {field["key"] for field in normalized_schema.get("fields", [])}
    merged = default_values_for_schema(normalized_schema)
    merged.update({key: value for key, value in provided.items() if key in valid_keys})
    return merged


class ConfigStore:
    """File-backed OCS schema/value store."""

    def __init__(self, base_dir: str | Path = Path("strategies") / "configs"):
        self.base_dir = Path(base_dir)
        self.schema_dir = self.base_dir / "schemas"
        self.values_dir = self.base_dir / "values"

    def ensure_dirs(self) -> None:
        self.schema_dir.mkdir(parents=True, exist_ok=True)
        self.values_dir.mkdir(parents=True, exist_ok=True)

    def _safe_id(self, strategy_id: str) -> str:
        if not strategy_id or not FIELD_KEY_RE.match(strategy_id.replace("-", "_")):
            raise OCSValidationError("Invalid strategy ID")
        if "/" in strategy_id or "\\" in strategy_id or ".." in strategy_id:
            raise OCSValidationError("Invalid strategy ID")
        return strategy_id

    def schema_path(self, strategy_id: str) -> Path:
        return self.schema_dir / f"{self._safe_id(strategy_id)}.json"

    def values_path(self, strategy_id: str) -> Path:
        return self.values_dir / f"{self._safe_id(strategy_id)}.json"

    def _read_json(self, path: Path, default: dict[str, Any]) -> dict[str, Any]:
        if not path.exists():
            return deepcopy(default)
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)

    def get_schema(self, strategy_id: str) -> dict[str, Any]:
        raw = self._read_json(self.schema_path(strategy_id), {"fields": []})
        return normalize_schema(raw, strategy_id)

    def save_schema(self, strategy_id: str, schema: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_schema(schema, strategy_id)
        self._write_json(self.schema_path(strategy_id), normalized)
        current_values = self.get_values(strategy_id, allow_invalid=True)
        current_values = merge_schema_defaults(normalized, current_values)
        try:
            self.save_values(strategy_id, current_values)
        except OCSValidationError:
            self._write_json(self.values_path(strategy_id), current_values)
        return normalized

    def get_values(self, strategy_id: str, allow_invalid: bool = False) -> dict[str, Any]:
        raw = self._read_json(self.values_path(strategy_id), {})
        if allow_invalid:
            return merge_schema_defaults(self.get_schema(strategy_id), raw)
        return validate_values(self.get_schema(strategy_id), raw)

    def save_values(self, strategy_id: str, values: dict[str, Any]) -> dict[str, Any]:
        schema = self.get_schema(strategy_id)
        normalized_values = validate_values(schema, values)
        self._write_json(self.values_path(strategy_id), normalized_values)
        return normalized_values

    def delete(self, strategy_id: str) -> None:
        for path in (self.schema_path(strategy_id), self.values_path(strategy_id)):
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def build_runtime_config(store: ConfigStore, strategy_id: str) -> dict[str, Any]:
    """Load schema defaults plus persisted values for strategy launch."""
    schema = store.get_schema(strategy_id)
    values = store.get_values(strategy_id)
    return validate_values(schema, values)
