"""Extensible registry for LLM models, deep learning models, and agents.

Supports: Ollama (local), Gemini (free), OpenAI, Anthropic, vLLM, custom PyTorch/TF models.
New models added via register() -- no code changes needed.
"""

from dataclasses import dataclass, field
from enum import Enum
from utils.logging import get_logger

logger = get_logger(__name__)


class ModelType(str, Enum):
    LLM = "llm"
    DEEP_LEARNING = "deep_learning"
    AGENT = "agent"
    EMBEDDING = "embedding"


@dataclass
class ModelInfo:
    id: str
    name: str
    type: ModelType
    provider: str  # "ollama", "gemini", "openai", "anthropic", "vllm", "local", "custom"
    endpoint: str = ""
    api_key: str = ""
    model_name: str = ""  # e.g., "qwen3.5:9b", "gemini-2.0-flash"
    priority: int = 100  # Lower = higher priority in fallback chain
    enabled: bool = True
    capabilities: list[str] = field(default_factory=list)  # ["chat", "analysis", "vision"]
    metadata: dict = field(default_factory=dict)


class ModelRegistry:
    """Central registry for all models and agents. Thread-safe."""

    def __init__(self):
        self._models: dict[str, ModelInfo] = {}

    def register(self, model: ModelInfo) -> None:
        self._models[model.id] = model
        logger.info(f"Registered model: {model.id} ({model.provider}/{model.type.value})")

    def remove(self, model_id: str) -> None:
        self._models.pop(model_id, None)

    def get(self, model_id: str) -> ModelInfo | None:
        return self._models.get(model_id)

    def list_all(self) -> list[ModelInfo]:
        return list(self._models.values())

    def list_by_type(self, model_type: ModelType) -> list[ModelInfo]:
        return [m for m in self._models.values() if m.type == model_type and m.enabled]

    def list_by_provider(self, provider: str) -> list[ModelInfo]:
        return [m for m in self._models.values() if m.provider == provider and m.enabled]

    def get_fallback_chain(self, model_type: ModelType) -> list[ModelInfo]:
        """Get models sorted by priority (lowest first) for fallback."""
        return sorted(self.list_by_type(model_type), key=lambda m: m.priority)


# Global registry with defaults
_registry = ModelRegistry()


def get_registry() -> ModelRegistry:
    return _registry


def init_default_models():
    """Register default models. Called at app startup."""
    _registry.register(ModelInfo(
        id="ollama-qwen", name="Qwen 3.5 9B", type=ModelType.LLM,
        provider="ollama", endpoint="http://localhost:11434",
        model_name="qwen3.5:9b", priority=1,
        capabilities=["chat", "analysis"],
    ))
    _registry.register(ModelInfo(
        id="gemini-flash", name="Gemini 2.0 Flash", type=ModelType.LLM,
        provider="gemini", endpoint="https://generativelanguage.googleapis.com",
        model_name="gemini-2.0-flash", priority=2,
        capabilities=["chat", "analysis"],
    ))
    # Placeholder for future deep learning models
    _registry.register(ModelInfo(
        id="dl-placeholder", name="Custom DL Model (Future)", type=ModelType.DEEP_LEARNING,
        provider="local", enabled=False, priority=10,
        capabilities=["prediction"],
        metadata={"note": "Placeholder for PyTorch/TF fine-tuned models"},
    ))
