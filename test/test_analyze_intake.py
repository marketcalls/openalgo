"""Contract tests for the decision-telemetry intake (``POST /api/v1/analyze``).

Producer: LOATS ``route_to_analyzer`` posts ``TradeDecision.to_analyzer_payload()``
(exactly these decision fields plus ``apikey``) to ``/api/v1/analyze``. The
ADR-006 Amendment 5 follow-up that deferred this intake had a hidden defect:
LOATS shipped the producer side pointing at ``analyze`` while the gateway never
shipped the endpoint, so every routed decision silently resolved as an HTTP 404
error outcome. These tests pin the three layers that must stay aligned:

* the schema accepts the real producer payload (wire compatibility),
* the namespace is actually registered under ``/analyze`` (the historical
  defect: an implemented-but-unregistered endpoint is indistinguishable from
  a missing one for the producer),
* the service records telemetry without ever persisting the credential.

The checks stay deliberately coarse (no app boot, no database) so they are
CI-safe in the same way ``test_telegram_api_contract.py`` is.
"""

import ast
from pathlib import Path

import pytest
from marshmallow import ValidationError

from restx_api.account_schema import AnalyzerIntakeSchema
from services import analyze_intake_service

MODULE_PATH = Path(__file__).resolve().parents[1] / "restx_api" / "analyze.py"
INIT_PATH = Path(__file__).resolve().parents[1] / "restx_api" / "__init__.py"

# The real producer shape: TradeDecision.to_analyzer_payload() + apikey.
LOATS_PAYLOAD = {
    "apikey": "x" * 64,
    "decision_id": "d-20260914-091501-000123",
    "symbol": "RELIANCE",
    "decision_type": "DecisionType.BUY",
    "timestamp": "2026-09-14T09:15:01.123456+00:00",
    "as_of_date": "2026-09-14",
    "entry_price": 1257.5,
    "quantity": 10,
    "stop_loss": 1232.35,
    "take_profit": 1307.8,
    "trailing_stop_config": {"enabled": True, "trail_pct": 1.5},
    "position_size_method": "risk_based",
    "risk_percentage": 1.0,
    "var_analysis": {"var_95": 2500.0},
    "gating_rules_result": {"passed": True},
    "source_breakdown": {"ta": 0.6, "sentiment": 0.4},
    "metadata": {"cycle": 40912},
    "status": "PENDING",
    "risk_reward_ratio": 2.0,
}


@pytest.fixture(scope="module")
def module_tree() -> ast.Module:
    return ast.parse(MODULE_PATH.read_text(encoding="utf-8"), filename=str(MODULE_PATH))


# ---------------------------------------------------------------------------
# Schema: wire compatibility with the producer
# ---------------------------------------------------------------------------


def test_schema_accepts_full_producer_payload():
    loaded = AnalyzerIntakeSchema().load(LOATS_PAYLOAD)
    assert loaded["decision_id"] == LOATS_PAYLOAD["decision_id"]
    assert loaded["symbol"] == "RELIANCE"


def test_schema_retains_producer_extension_fields():
    # unknown = INCLUDE: the producer may extend telemetry without a
    # coordinated gateway release.
    payload = dict(LOATS_PAYLOAD)
    payload["future_field"] = {"nested": [1, 2, 3]}
    loaded = AnalyzerIntakeSchema().load(payload)
    assert loaded["future_field"] == {"nested": [1, 2, 3]}


@pytest.mark.parametrize(
    "required_field",
    ["apikey", "decision_id", "symbol", "decision_type", "timestamp"],
)
def test_schema_rejects_missing_required_fields(required_field):
    payload = {k: v for k, v in LOATS_PAYLOAD.items() if k != required_field}
    with pytest.raises(ValidationError):
        AnalyzerIntakeSchema().load(payload)


def test_schema_rejects_oversized_decision_id():
    payload = dict(LOATS_PAYLOAD)
    payload["decision_id"] = "d" * 257
    with pytest.raises(ValidationError):
        AnalyzerIntakeSchema().load(payload)


# ---------------------------------------------------------------------------
# Resource: static contract (route, auth, credential handling)
# ---------------------------------------------------------------------------


def test_resource_uses_apikey_auth_and_403_on_invalid(module_tree):
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "get_auth_token_broker" in source, "intake must authenticate via apikey"
    assert "Invalid openalgo apikey" in source, "must follow the house 403 message"
    assert "403" in source, "invalid apikey must be rejected with 403"


def test_resource_never_logs_the_credential(module_tree):
    # The audit request passed onward must be built with apikey removed, and
    # no raw request body may reach the audit call.
    class _Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.log_calls: list[ast.Call] = []

        def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
            func = node.func
            if isinstance(func, ast.Name) and func.id == "record_decision_intake":
                self.log_calls.append(node)
            self.generic_visit(node)

    visitor = _Visitor()
    visitor.visit(module_tree)
    assert visitor.log_calls, "resource must delegate recording to the service"
    call = visitor.log_calls[0]
    keywords = {kw.arg: kw for kw in call.keywords if kw.arg}
    assert "intake_data" in keywords and "original_data" in keywords
    assert "data" not in keywords, "raw body (contains apikey) must not be passed onward"


def test_namespace_registered_under_analyze_path():
    # The ADR-006 Am5 defect class: producer points at /analyze while the
    # gateway never registers the route -> every decision 404s forever.
    init_source = INIT_PATH.read_text(encoding="utf-8")
    assert "from .analyze import api as analyze_ns" in init_source
    assert 'api.add_namespace(analyze_ns, path="/analyze")' in init_source


# ---------------------------------------------------------------------------
# Service: recording semantics
# ---------------------------------------------------------------------------


def test_service_records_without_credential(monkeypatch):
    captured: dict = {}

    def _fake_log(request_data, response_data, api_type):
        captured["request"] = request_data
        captured["response"] = response_data
        captured["api_type"] = api_type

    monkeypatch.setattr(analyze_intake_service, "async_log_analyzer", _fake_log)

    intake = {k: v for k, v in LOATS_PAYLOAD.items() if k != "apikey"}
    original = dict(LOATS_PAYLOAD)  # contains apikey, as the resource strips it

    success, response_data, status_code = analyze_intake_service.record_decision_intake(
        intake_data=intake, original_data=original
    )

    assert success is True
    assert status_code == 200
    assert response_data["status"] == "success"
    assert response_data["data"]["decision_id"] == LOATS_PAYLOAD["decision_id"]
    assert response_data["data"]["recorded"] is True

    assert captured["api_type"] == analyze_intake_service.DECISION_INTAKE_API_TYPE
    assert "apikey" not in captured["request"], "audit row must never carry the credential"
    assert captured["request"]["decision_id"] == LOATS_PAYLOAD["decision_id"]


def test_service_does_not_mutate_caller_data(monkeypatch):
    monkeypatch.setattr(analyze_intake_service, "async_log_analyzer", lambda *a, **k: None)
    original = dict(LOATS_PAYLOAD)
    original["decision_id"] = "d-1"
    original["symbol"] = "TCS"
    analyze_intake_service.record_decision_intake(
        intake_data={"decision_id": "d-1", "symbol": "TCS"}, original_data=original
    )
    assert "apikey" in original, "caller's dict must not be mutated"
    assert original["apikey"] == LOATS_PAYLOAD["apikey"]


def test_service_contains_log_submission_failure(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("executor unavailable")

    monkeypatch.setattr(analyze_intake_service._log_executor, "submit", _boom)

    success, response_data, status_code = analyze_intake_service.record_decision_intake(
        intake_data={"decision_id": "d-2"}, original_data={}
    )
    assert success is False
    assert status_code == 500
    assert response_data["status"] == "error"


def test_service_defaults_missing_decision_id(monkeypatch):
    captured: dict = {}

    def _fake_log(request_data, response_data, api_type):
        captured["response"] = response_data

    monkeypatch.setattr(analyze_intake_service, "async_log_analyzer", _fake_log)

    _, response_data, status_code = analyze_intake_service.record_decision_intake(
        intake_data={}, original_data={}
    )
    assert status_code == 200
    assert response_data["data"]["decision_id"] == "unknown"
