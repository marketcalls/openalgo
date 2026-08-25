import ast
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from restx_api.data_schemas import HistorySchema
from services import history_service


def _assignment_target_name(target):
    if isinstance(target, ast.Name):
        return target.id
    if (
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "self"
    ):
        return target.attr
    return None


def _literal_dict_keys(value):
    if not isinstance(value, ast.Dict):
        return None

    keys = []
    for key in value.keys:
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            return None
        keys.append(key.value)
    return tuple(keys)


def _extract_timeframe_map(data_file):
    tree = ast.parse(data_file.read_text())
    assignments = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)]
    declared_maps = {}
    timeframe_map_value = None

    for assignment in assignments:
        keys = _literal_dict_keys(assignment.value)
        for target in assignment.targets:
            target_name = _assignment_target_name(target)
            if target_name is None:
                continue
            if keys is not None:
                declared_maps[target_name] = keys
            if target_name == "timeframe_map":
                timeframe_map_value = assignment.value

    if timeframe_map_value is None:
        raise AssertionError(f"{data_file} does not define timeframe_map")

    direct_keys = _literal_dict_keys(timeframe_map_value)
    if direct_keys is not None:
        return direct_keys

    if (
        isinstance(timeframe_map_value, ast.Attribute)
        and isinstance(timeframe_map_value.value, ast.Name)
        and timeframe_map_value.value.id == "self"
    ):
        return declared_maps[timeframe_map_value.attr]

    if (
        isinstance(timeframe_map_value, ast.DictComp)
        and len(timeframe_map_value.generators) == 1
        and isinstance(timeframe_map_value.generators[0].iter, ast.Attribute)
        and isinstance(timeframe_map_value.generators[0].iter.value, ast.Name)
        and timeframe_map_value.generators[0].iter.value.id == "self"
    ):
        return declared_maps[timeframe_map_value.generators[0].iter.attr]

    raise AssertionError(f"{data_file} has an unsupported timeframe_map definition")


def _broker_timeframe_maps():
    repository_root = Path(__file__).resolve().parents[1]
    return [
        (data_file.parents[1].name, _extract_timeframe_map(data_file))
        for data_file in sorted(repository_root.glob("broker/*/api/data.py"))
    ]


BROKER_TIMEFRAME_MAPS = _broker_timeframe_maps()


def _history_request(interval):
    return {
        "apikey": "test-api-key",
        "symbol": "NIFTY",
        "exchange": "NSE_INDEX",
        "interval": interval,
        "start_date": "2026-08-01",
        "end_date": "2026-08-22",
    }


def _broker_module(timeframe_map, calls):
    class BrokerData:
        def __init__(self, auth_token):
            self.timeframe_map = dict.fromkeys(timeframe_map)

        def get_history(self, symbol, exchange, interval, start_date, end_date):
            calls.append(interval)
            return pd.DataFrame()

    return SimpleNamespace(BrokerData=BrokerData)


def _get_history_with_auth(broker, interval):
    return history_service.get_history_with_auth(
        auth_token="test-token",
        feed_token=None,
        broker=broker,
        symbol="NIFTY",
        exchange="NSE_INDEX",
        interval=interval,
        start_date="2026-08-01",
        end_date="2026-08-22",
    )


@pytest.mark.parametrize("interval", ["60m", "6h", "25m", "4m"])
def test_history_schema_defers_interval_validation_to_resolved_broker(interval):
    assert HistorySchema().load(_history_request(interval))["interval"] == interval


@pytest.mark.parametrize(
    "interval",
    [
        "1s",
        "5s",
        "10s",
        "15s",
        "30s",
        "45s",
        "1m",
        "2m",
        "3m",
        "5m",
        "10m",
        "15m",
        "20m",
        "30m",
        "1h",
        "2h",
        "3h",
        "4h",
        "D",
        "W",
        "M",
        "Q",
        "Y",
    ],
)
def test_history_schema_keeps_existing_intervals_valid(interval):
    assert HistorySchema().load(_history_request(interval))["interval"] == interval


@pytest.mark.parametrize(
    "broker,timeframe_map",
    BROKER_TIMEFRAME_MAPS,
    ids=[broker for broker, _ in BROKER_TIMEFRAME_MAPS],
)
def test_declared_broker_intervals_are_requestable(monkeypatch, broker, timeframe_map):
    calls = []
    monkeypatch.setattr(history_service, "validate_symbol_exchange", lambda *_: (True, None))
    monkeypatch.setattr(
        history_service,
        "import_broker_module",
        lambda _: _broker_module(timeframe_map, calls),
    )

    for interval in timeframe_map:
        success, _, status_code = _get_history_with_auth(broker, interval)
        assert success is True
        assert status_code == 200

    assert calls == list(timeframe_map)


@pytest.mark.parametrize(
    "timeframe_map,supported_intervals",
    [({"1m": "1minute"}, "1m"), ({}, "none")],
)
def test_unsupported_broker_interval_returns_400_without_calling_provider(
    monkeypatch, timeframe_map, supported_intervals
):
    calls = []
    monkeypatch.setattr(history_service, "validate_symbol_exchange", lambda *_: (True, None))
    monkeypatch.setattr(
        history_service,
        "import_broker_module",
        lambda _: _broker_module(timeframe_map, calls),
    )

    success, response, status_code = _get_history_with_auth("test-broker", "60m")

    assert success is False
    assert status_code == 400
    assert response == {
        "status": "error",
        "message": (
            "Unsupported interval '60m' for broker 'test-broker'. "
            f"Supported intervals: {supported_intervals}."
        ),
    }
    assert calls == []


def test_database_history_does_not_use_broker_interval_validation(monkeypatch):
    expected_response = {"status": "success", "data": []}
    monkeypatch.setattr(
        history_service,
        "get_history_from_db",
        lambda **kwargs: (True, expected_response, 200),
    )

    success, response, status_code = history_service.get_history(
        symbol="NIFTY",
        exchange="NSE_INDEX",
        interval="7h",
        start_date="2026-08-01",
        end_date="2026-08-22",
        source="db",
    )

    assert success is True
    assert response == expected_response
    assert status_code == 200
