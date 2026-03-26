import pytest
from unittest.mock import patch, MagicMock
from ai.llm_router import LLMRouter, LLMResponse
from ai.model_registry import get_registry, init_default_models


@pytest.fixture(autouse=True)
def _setup_registry():
    """Ensure the global registry has default models for router tests."""
    registry = get_registry()
    if not registry.get("ollama-qwen"):
        init_default_models()
    yield


def test_router_returns_response():
    router = LLMRouter()
    with patch.object(router, '_call_ollama', return_value=LLMResponse(
        success=True, text="RELIANCE looks bullish", provider="ollama", model="qwen3.5:9b"
    )):
        result = router.generate("Analyze RELIANCE signal: BUY with 75% confidence")
        assert result.success is True
        assert "bullish" in result.text.lower()
        assert result.provider == "ollama"


def test_router_falls_back_to_gemini():
    router = LLMRouter()
    with patch.object(router, '_call_ollama', return_value=LLMResponse(
        success=False, text="", provider="ollama", error="Connection refused"
    )):
        with patch.object(router, '_call_gemini', return_value=LLMResponse(
            success=True, text="Analysis complete", provider="gemini", model="gemini-2.0-flash"
        )):
            result = router.generate("Analyze RELIANCE")
            assert result.success is True
            assert result.provider == "gemini"


def test_router_all_fail():
    router = LLMRouter()
    with patch.object(router, '_call_ollama', return_value=LLMResponse(success=False, text="", provider="ollama", error="down")):
        with patch.object(router, '_call_gemini', return_value=LLMResponse(success=False, text="", provider="gemini", error="quota")):
            result = router.generate("test")
            assert result.success is False
            assert result.error is not None
