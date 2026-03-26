import pytest
from ai.model_registry import ModelRegistry, ModelInfo, ModelType


def test_register_and_get():
    reg = ModelRegistry()
    reg.register(ModelInfo(id="ollama-qwen", name="Qwen 3.5 9B", type=ModelType.LLM, provider="ollama", endpoint="http://localhost:11434"))
    model = reg.get("ollama-qwen")
    assert model is not None
    assert model.name == "Qwen 3.5 9B"


def test_list_by_type():
    reg = ModelRegistry()
    reg.register(ModelInfo(id="ollama-qwen", name="Qwen", type=ModelType.LLM, provider="ollama"))
    reg.register(ModelInfo(id="custom-lstm", name="LSTM Predictor", type=ModelType.DEEP_LEARNING, provider="local"))
    reg.register(ModelInfo(id="gemini-flash", name="Gemini Flash", type=ModelType.LLM, provider="gemini"))
    llms = reg.list_by_type(ModelType.LLM)
    assert len(llms) == 2
    dls = reg.list_by_type(ModelType.DEEP_LEARNING)
    assert len(dls) == 1


def test_list_by_provider():
    reg = ModelRegistry()
    reg.register(ModelInfo(id="ollama-qwen", name="Qwen", type=ModelType.LLM, provider="ollama"))
    reg.register(ModelInfo(id="ollama-llama", name="Llama", type=ModelType.LLM, provider="ollama"))
    assert len(reg.list_by_provider("ollama")) == 2


def test_remove():
    reg = ModelRegistry()
    reg.register(ModelInfo(id="test", name="Test", type=ModelType.LLM, provider="test"))
    reg.remove("test")
    assert reg.get("test") is None


def test_get_default_chain():
    reg = ModelRegistry()
    reg.register(ModelInfo(id="ollama-qwen", name="Qwen", type=ModelType.LLM, provider="ollama", priority=1))
    reg.register(ModelInfo(id="gemini-flash", name="Gemini", type=ModelType.LLM, provider="gemini", priority=2))
    chain = reg.get_fallback_chain(ModelType.LLM)
    assert chain[0].id == "ollama-qwen"
    assert chain[1].id == "gemini-flash"
