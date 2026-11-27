import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest

from strategies.recovery import AtomicStrategyState, RecoveryContext


def test_context_reads_host_recovery_contract(monkeypatch):
    monkeypatch.setenv("STRATEGY_ID", "n918")
    monkeypatch.setenv("OPENALGO_RUN_ID", "n918-20261028-090000")
    monkeypatch.setenv("OPENALGO_RESUME", "1")
    context = RecoveryContext.from_environment()
    assert context.strategy_id == "n918"
    assert context.run_id == "n918-20261028-090000"
    assert context.resume_requested is True


def test_state_save_is_loadable_and_cleans_temporary_file(tmp_path):
    store = AtomicStrategyState(
        tmp_path / "n918.state.json", RecoveryContext("n918", "run-1", False)
    )
    store.save({"phase": "monitoring"})
    assert store.load()["phase"] == "monitoring"
    assert list(tmp_path.glob("*.tmp")) == []
    assert json.loads(store.path.read_text(encoding="utf-8"))["run_id"] == "run-1"


def test_completed_action_is_idempotent(tmp_path):
    store = AtomicStrategyState(tmp_path / "state.json", RecoveryContext("n918", "run-1", True))
    state = store.load()
    store.mark_action_completed(state, "entry|initial-ce")
    store.mark_action_completed(state, "entry|initial-ce")
    assert store.load()["completed_actions"] == ["entry|initial-ce"]


def test_resume_refuses_state_from_another_run(tmp_path):
    store = AtomicStrategyState(tmp_path / "state.json", RecoveryContext("n918", "run-2", True))
    with pytest.raises(RuntimeError, match="does not match"):
        store.require_matching_run({"run_id": "run-1"})


def test_resume_refuses_state_without_a_run_id(tmp_path):
    store = AtomicStrategyState(tmp_path / "state.json", RecoveryContext("n918", "run-2", True))
    with pytest.raises(RuntimeError, match="does not match"):
        store.require_matching_run({})


def test_save_refuses_to_relabel_state_from_another_run(tmp_path):
    store = AtomicStrategyState(tmp_path / "state.json", RecoveryContext("n918", "run-2", True))
    with pytest.raises(RuntimeError, match="does not match"):
        store.save({"run_id": "run-1", "completed_actions": ["old-action"]})


def test_save_rejects_values_that_json_cannot_round_trip(tmp_path):
    store = AtomicStrategyState(tmp_path / "state.json", RecoveryContext("n918", "run-1", True))
    with pytest.raises(TypeError):
        store.save({"timestamp": datetime.now()})


def test_concurrent_action_updates_are_merged(tmp_path):
    path = tmp_path / "state.json"
    context = RecoveryContext("n918", "run-1", True)
    first = AtomicStrategyState(path, context)
    second = AtomicStrategyState(path, context)
    first.save(first.load())
    first_snapshot = first.load()
    second_snapshot = second.load()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(first.mark_action_completed, first_snapshot, "entry|ce"),
            executor.submit(second.mark_action_completed, second_snapshot, "entry|pe"),
        ]
        for future in futures:
            future.result()

    assert set(first.load()["completed_actions"]) == {"entry|ce", "entry|pe"}
