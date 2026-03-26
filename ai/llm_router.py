"""LLM Router with Ollama -> Gemini fallback chain.

Extensible: add new providers by registering models in model_registry
and adding a _call_{provider} method.
"""

import json
import os
from dataclasses import dataclass

import requests
from ai.model_registry import ModelType, get_registry
from utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class LLMResponse:
    success: bool
    text: str
    provider: str
    model: str = ""
    error: str | None = None


class LLMRouter:
    """Routes LLM requests through a fallback chain: Ollama -> Gemini -> error."""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    def generate(self, prompt: str, system: str = "") -> LLMResponse:
        """Send prompt to first available LLM in the fallback chain."""
        registry = get_registry()
        chain = registry.get_fallback_chain(ModelType.LLM)

        for model_info in chain:
            caller = getattr(self, f"_call_{model_info.provider}", None)
            if caller is None:
                logger.debug(f"No caller for provider: {model_info.provider}")
                continue

            result = caller(prompt, system, model_info)
            if result.success:
                return result
            logger.warning(f"LLM {model_info.id} failed: {result.error}")

        return LLMResponse(success=False, text="", provider="none", error="All LLM providers failed")

    def _call_ollama(self, prompt: str, system: str, model_info) -> LLMResponse:
        """Call Ollama local API."""
        try:
            payload = {
                "model": model_info.model_name or "qwen3.5:9b",
                "prompt": prompt,
                "stream": False,
            }
            if system:
                payload["system"] = system

            resp = requests.post(
                f"{model_info.endpoint}/api/generate",
                json=payload,
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                data = resp.json()
                return LLMResponse(
                    success=True, text=data.get("response", ""),
                    provider="ollama", model=model_info.model_name,
                )
            return LLMResponse(success=False, text="", provider="ollama", error=f"HTTP {resp.status_code}")
        except Exception as e:
            return LLMResponse(success=False, text="", provider="ollama", error=str(e))

    def _call_gemini(self, prompt: str, system: str, model_info) -> LLMResponse:
        """Call Google Gemini API (free tier)."""
        try:
            api_key = model_info.api_key or os.getenv("GEMINI_API_KEY", "")
            if not api_key:
                return LLMResponse(success=False, text="", provider="gemini", error="No GEMINI_API_KEY")

            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_info.model_name}:generateContent?key={api_key}"
            parts = []
            if system:
                parts.append({"text": system + "\n\n"})
            parts.append({"text": prompt})

            resp = requests.post(url, json={
                "contents": [{"parts": parts}]
            }, timeout=self.timeout)

            if resp.status_code == 200:
                data = resp.json()
                text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                return LLMResponse(success=True, text=text, provider="gemini", model=model_info.model_name)
            return LLMResponse(success=False, text="", provider="gemini", error=f"HTTP {resp.status_code}")
        except Exception as e:
            return LLMResponse(success=False, text="", provider="gemini", error=str(e))
