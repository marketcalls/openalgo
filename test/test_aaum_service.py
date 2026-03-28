"""Tests for services/aaum_service.py."""
import pytest
import httpx
from unittest.mock import MagicMock, patch
import sys
import os

# Ensure the parent directory is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.aaum_service as svc


def _mock_client(return_value=None, side_effect=None):
    """Create a mock httpx.Client to replace the module-level singleton."""
    mock = MagicMock()
    if side_effect:
        mock.get.side_effect = side_effect
        mock.post.side_effect = side_effect
    else:
        mock.get.return_value = return_value
        mock.post.return_value = return_value
    return mock


def test_analyze_returns_503_when_service_down():
    """When AAUM is unreachable, return False + 503 + helpful message."""
    with patch.object(svc, "client", _mock_client(side_effect=httpx.ConnectError("refused"))):
        success, data, status = svc.aaum_analyze("RELIANCE")
    assert success is False
    assert status == 503
    assert "not running" in data["message"].lower()


def test_analyze_forwards_symbol_as_path_param():
    """Symbol is forwarded as path segment to AAUM GET endpoint."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"symbol": "RELIANCE", "action": "BUY"}
    mock_resp.status_code = 200
    mock_client_obj = _mock_client(return_value=mock_resp)
    with patch.object(svc, "client", mock_client_obj):
        success, data, status = svc.aaum_analyze("RELIANCE")
        mock_client_obj.get.assert_called_once_with(f"/api/v5/analyze/RELIANCE")
    assert success is True
    assert status == 200


def test_health_returns_503_on_connect_error():
    with patch.object(svc, "client", _mock_client(side_effect=httpx.ConnectError("refused"))):
        success, data, status = svc.aaum_health()
    assert success is False
    assert status == 503


def test_execute_defaults_to_paper_mode():
    """When paper kwarg omitted, request body must have paper=True."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"status": "success", "order_ids": [], "message": "ok"}
    mock_resp.status_code = 200
    mock_client_obj = _mock_client(return_value=mock_resp)
    with patch.object(svc, "client", mock_client_obj):
        svc.aaum_execute("RELIANCE")
        call_kwargs = mock_client_obj.post.call_args.kwargs
        assert call_kwargs["json"]["paper"] is True
