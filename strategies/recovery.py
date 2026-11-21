"""Recovery contract for Python strategies hosted by OpenAlgo."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_STATE_LOCKS_GUARD = threading.Lock()
_STATE_LOCKS: dict[str, threading.RLock] = {}


def _state_lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _STATE_LOCKS_GUARD:
        return _STATE_LOCKS.setdefault(key, threading.RLock())


@dataclass(frozen=True)
class RecoveryContext:
    strategy_id: str
    run_id: str
    resume_requested: bool

    @classmethod
    def from_environment(cls) -> RecoveryContext:
        strategy_id = os.environ.get("STRATEGY_ID", "standalone")
        run_id = os.environ.get("OPENALGO_RUN_ID") or f"{strategy_id}-standalone"
        resume_requested = os.environ.get("OPENALGO_RESUME", "0").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        return cls(strategy_id, run_id, resume_requested)


class AtomicStrategyState:
    """JSON state stored with atomic replace so power loss cannot half-write it."""

    def __init__(self, path: str | Path, context: RecoveryContext):
        self.path = Path(path)
        self.context = context
        self._lock = _state_lock(self.path)

    def load(self) -> dict[str, Any]:
        with self._lock:
            if not self.path.exists():
                return self._empty()
            with self.path.open(encoding="utf-8") as handle:
                state = json.load(handle)
            if not isinstance(state, dict):
                raise ValueError("Strategy recovery state must be a JSON object")
            return state

    def save(self, state: dict[str, Any]) -> None:
        with self._lock:
            supplied_run = state.get("run_id")
            if supplied_run is not None and supplied_run != self.context.run_id:
                raise RuntimeError(
                    f"Saved run {supplied_run!r} does not match host run {self.context.run_id!r}"
                )
            payload = dict(state)
            payload["strategy_id"] = self.context.strategy_id
            payload["run_id"] = self.context.run_id
            payload.setdefault("completed_actions", [])
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=self.path.parent,
                    prefix=f".{self.path.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as handle:
                    temporary = Path(handle.name)
                    json.dump(payload, handle, indent=2, sort_keys=True)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
            finally:
                if temporary is not None:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError:
                        pass

    @staticmethod
    def action_completed(state: dict[str, Any], action_id: str) -> bool:
        return action_id in state.get("completed_actions", [])

    def mark_action_completed(self, state: dict[str, Any], action_id: str) -> None:
        with self._lock:
            self.require_matching_run(state)
            current = self.load()
            self.require_matching_run(current)
            actions = list(current.get("completed_actions", []))
            for completed in state.get("completed_actions", []):
                if completed not in actions:
                    actions.append(completed)
            if action_id not in actions:
                actions.append(action_id)
            current.update(state)
            current["completed_actions"] = actions
            state["completed_actions"] = list(actions)
            self.save(current)

    def require_matching_run(self, state: dict[str, Any]) -> None:
        saved_run = state.get("run_id")
        if saved_run != self.context.run_id:
            raise RuntimeError(
                f"Saved run {saved_run!r} does not match host run {self.context.run_id!r}"
            )

    def _empty(self) -> dict[str, Any]:
        return {
            "strategy_id": self.context.strategy_id,
            "run_id": self.context.run_id,
            "completed_actions": [],
        }
