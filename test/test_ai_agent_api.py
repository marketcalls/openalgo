from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from flask import Flask

from limiter import limiter
from services.ai_analysis_service import AnalysisResult


@pytest.fixture
def ai_agent_module():
    module_path = Path(__file__).resolve().parents[1] / "restx_api" / "ai_agent.py"
    spec = spec_from_file_location("test_ai_agent_module", module_path)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def client(ai_agent_module):
    app = Flask(__name__)
    app.config["TESTING"] = True
    limiter.init_app(app)
    app.add_url_rule(
        "/api/v1/agent/analyze",
        view_func=ai_agent_module.AnalyzeResource.as_view("agent_analyze"),
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/v1/agent/history",
        view_func=ai_agent_module.HistoryResource.as_view("agent_history"),
        methods=["POST"],
    )

    with app.test_client() as test_client:
        yield test_client, ai_agent_module


def test_history_returns_decisions_for_authenticated_user(client, monkeypatch):
    test_client, ai_agent_module = client
    monkeypatch.setattr(ai_agent_module, "_validate_api_key", lambda api_key: "sakth")
    history_mock = MagicMock(return_value=[{"id": 1, "symbol": "SBIN"}])
    monkeypatch.setattr(ai_agent_module, "get_decision_history", history_mock)

    response = test_client.post(
        "/api/v1/agent/history",
        json={"apikey": "valid-key", "symbol": "SBIN", "limit": 20},
    )

    assert response.status_code == 200
    assert response.get_json() == {"status": "success", "data": [{"id": 1, "symbol": "SBIN"}]}
    history_mock.assert_called_once_with("sakth", symbol="SBIN", limit=20)


def test_history_rejects_invalid_api_key(client, monkeypatch):
    test_client, ai_agent_module = client
    monkeypatch.setattr(ai_agent_module, "_validate_api_key", lambda api_key: None)

    response = test_client.post("/api/v1/agent/history", json={"apikey": "bad-key"})

    assert response.status_code == 403
    assert response.get_json()["message"] == "Invalid openalgo apikey"


def test_history_validates_limit_range(client, monkeypatch):
    test_client, ai_agent_module = client
    monkeypatch.setattr(ai_agent_module, "_validate_api_key", lambda api_key: "sakth")

    response = test_client.post(
        "/api/v1/agent/history",
        json={"apikey": "valid-key", "limit": 500},
    )

    assert response.status_code == 400
    assert response.get_json()["message"] == "limit must be between 1 and 100"


def test_analyze_logs_history_on_success(client, monkeypatch):
    test_client, ai_agent_module = client
    monkeypatch.setattr(ai_agent_module, "_validate_api_key", lambda api_key: "sakth")

    analyze_mock = MagicMock(
        return_value=AnalysisResult(
            success=True,
            symbol="SBIN",
            exchange="NSE",
            interval="15m",
            signal="BUY",
            confidence=78.5,
            score=82.0,
            regime="TRENDING_UP",
            sub_scores={"macd": 20.0},
            latest_indicators={"rsi_14": 62.0},
            advanced_signals={},
            trade_setup={},
            chart_overlays={},
            decision={},
            candles=[],
            data_points=120,
        )
    )
    log_mock = MagicMock()
    monkeypatch.setattr(ai_agent_module, "analyze_symbol", analyze_mock)
    monkeypatch.setattr(ai_agent_module, "log_analysis", log_mock)

    response = test_client.post(
        "/api/v1/agent/analyze",
        json={"apikey": "valid-key", "symbol": "SBIN", "exchange": "NSE", "interval": "15m"},
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "success"
    log_mock.assert_called_once_with(
        user_id="sakth",
        symbol="SBIN",
        exchange="NSE",
        interval="15m",
        signal="BUY",
        confidence=78.5,
        score=82.0,
        regime="TRENDING_UP",
        scores={"macd": 20.0},
        predicted_price=None,
        api_key="valid-key",
    )


def test_analyze_does_not_log_history_on_failure(client, monkeypatch):
    test_client, ai_agent_module = client
    monkeypatch.setattr(ai_agent_module, "_validate_api_key", lambda api_key: "sakth")

    analyze_mock = MagicMock(
        return_value=AnalysisResult(
            success=False,
            symbol="SBIN",
            exchange="NSE",
            interval="15m",
            error="No data",
        )
    )
    log_mock = MagicMock()
    monkeypatch.setattr(ai_agent_module, "analyze_symbol", analyze_mock)
    monkeypatch.setattr(ai_agent_module, "log_analysis", log_mock)

    response = test_client.post(
        "/api/v1/agent/analyze",
        json={"apikey": "valid-key", "symbol": "SBIN", "exchange": "NSE", "interval": "15m"},
    )

    assert response.status_code == 422
    assert response.get_json()["message"] == "No data"
    log_mock.assert_not_called()
