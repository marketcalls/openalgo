"""Versioned Object Store persistence for Lean Python strategies."""

from dataclasses import dataclass
from datetime import datetime, timezone
import json


@dataclass(frozen=True)
class StateLoadResult:
    status: str
    payload: dict

    @property
    def is_valid(self):
        return self.status == "valid"


class StrategyStateStore:
    """Stores strategy-owned payloads in a validated Object Store envelope."""

    _VALID_STATUSES = {"missing", "valid", "corrupt", "incompatible"}

    def __init__(self, object_store, strategy_id, scope, schema_version, default_payload):
        if not strategy_id or not scope:
            raise ValueError("strategy_id and scope are required")
        if schema_version < 1:
            raise ValueError("schema_version must be positive")

        self._object_store = object_store
        self._strategy_id = strategy_id
        self._scope = scope
        self._schema_version = schema_version
        self._default_payload = default_payload
        self.key = f"strategy-state/v1/{strategy_id}/{scope}/state.json"

    def load(self):
        default = self._new_default_payload()
        if not self._object_store.contains_key(self.key):
            return StateLoadResult("missing", default)

        try:
            envelope = json.loads(self._object_store.read(self.key))
        except (TypeError, ValueError):
            return StateLoadResult("corrupt", default)

        if not isinstance(envelope, dict) or not isinstance(envelope.get("payload"), dict):
            return StateLoadResult("corrupt", default)

        if (envelope.get("strategy_id") != self._strategy_id
                or envelope.get("scope") != self._scope
                or envelope.get("schema_version") != self._schema_version):
            return StateLoadResult("incompatible", default)

        return StateLoadResult("valid", envelope["payload"])

    def save(self, payload, updated_at=None):
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dictionary")

        timestamp = updated_at or datetime.now(timezone.utc).isoformat()
        envelope = {
            "schema_version": self._schema_version,
            "strategy_id": self._strategy_id,
            "scope": self._scope,
            "updated_at": timestamp,
            "payload": payload,
        }
        self._object_store.save(self.key, json.dumps(envelope, sort_keys=True))

    def _new_default_payload(self):
        default = self._default_payload()
        if not isinstance(default, dict):
            raise TypeError("default_payload must return a dictionary")
        return default