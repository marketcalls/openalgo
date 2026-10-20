"""Trader-facing wording for a failed agent run.

A model provider reports a failure in text written for a developer: an
exception class, a JSON body, an HTTP status, part of the API key and a link to
the provider's console. None of that is something a trader can act on, and
showing it reads as a fault they caused. What they need is the cause in plain
words and the one thing to do next.

The provider's text still matters, because "the key was refused" and "the model
does not exist" need different fixes. So it is read here to choose the
sentence, and kept in the server log for whoever runs the instance, but it is
never the sentence itself.

Every sentence names a cause only when the failure itself says so: a refused
key, an exhausted balance, a rate limit, an unknown model. Anything that could
have more than one cause gets a neutral sentence rather than a confident wrong
one.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from services.agent.frames import ErrorKind

# Provider identifiers as LiteLLM reports them, either on the exception's
# `llm_provider` attribute or as the prefix of "<Name>Exception" in its message.
# Keys are lower case with every non-alphanumeric character removed.
_PROVIDER_LABELS: dict[str, str] = {
    "openai": "OpenAI",
    "textcompletionopenai": "OpenAI",
    "azure": "Azure OpenAI",
    "azureopenai": "Azure OpenAI",
    "anthropic": "Anthropic",
    "gemini": "Google Gemini",
    "googleaistudio": "Google Gemini",
    "vertexai": "Google Vertex AI",
    "groq": "Groq",
    "mistral": "Mistral",
    "deepseek": "DeepSeek",
    "openrouter": "OpenRouter",
    "ollama": "Ollama",
    "xai": "xAI",
    "cohere": "Cohere",
    "bedrock": "Amazon Bedrock",
    "togetherai": "Together AI",
    "fireworksai": "Fireworks AI",
    "perplexity": "Perplexity",
    "cerebras": "Cerebras",
    "sambanova": "SambaNova",
    "chatgpt": "ChatGPT",
}

_EXCEPTION_PREFIX = re.compile(r"\b([A-Za-z_]+?)Exception\b")
_STATUS_PATTERNS = (
    re.compile(r'"status"\s*:\s*(\d{3})'),
    re.compile(r"\berror code:?\s*(\d{3})", re.IGNORECASE),
    re.compile(r"\bstatus[_ ]code\s*[=:]?\s*(\d{3})", re.IGNORECASE),
    re.compile(r"\bHTTP\s+(\d{3})\b"),
)

# Each category is recognised from the exception class names first, then from
# markers in the provider's text, then from the HTTP status. Order matters: a
# context-window error is also a bad request, and an exhausted balance is often
# reported as a rate limit.
_CONTEXT = "context"
_QUOTA = "quota"
_AUTH = "auth"
_PERMISSION = "permission"
_NOT_FOUND = "not_found"
_RATE = "rate"
_CONTENT = "content"
_TIMEOUT = "timeout"
_CONNECTION = "connection"
_UNAVAILABLE = "unavailable"
_BAD_REQUEST = "bad_request"

_CATEGORY_NAMES: tuple[tuple[str, frozenset[str]], ...] = (
    (_CONTEXT, frozenset({"ContextWindowExceededError"})),
    (_AUTH, frozenset({"AuthenticationError", "ModelAuthenticationError"})),
    (_PERMISSION, frozenset({"PermissionDeniedError"})),
    (_NOT_FOUND, frozenset({"NotFoundError"})),
    (_RATE, frozenset({"RateLimitError", "ModelRateLimitError"})),
    (_CONTENT, frozenset({"ContentPolicyViolationError"})),
    (_TIMEOUT, frozenset({"Timeout", "APITimeoutError"})),
    (_CONNECTION, frozenset({"APIConnectionError"})),
    (
        _UNAVAILABLE,
        frozenset(
            {"ServiceUnavailableError", "InternalServerError", "RemoteServerUnavailableError"}
        ),
    ),
)

# A bad request is the provider's catch-all: an unknown model, an over-long
# prompt and an unsupported input all arrive as one. So it is consulted only
# after the text has had its say, never before.
_GENERIC_NAMES: frozenset[str] = frozenset({"BadRequestError", "UnprocessableEntityError"})

_CATEGORY_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        _CONTEXT,
        (
            "context_length_exceeded",
            "maximum context length",
            "context window",
            "prompt is too long",
            "too many tokens",
        ),
    ),
    (
        _QUOTA,
        (
            "insufficient_quota",
            "exceeded your current quota",
            "credit balance is too low",
            "insufficient credits",
            "insufficient balance",
            "billing",
            "payment required",
        ),
    ),
    (
        _AUTH,
        (
            "invalid_api_key",
            "incorrect api key",
            "invalid api key",
            "invalid x-api-key",
            "api key not valid",
            "api_key_invalid",
            "authenticationerror",
            "unauthorized",
        ),
    ),
    (_PERMISSION, ("permissiondeniederror", "permission denied", "does not have access")),
    (_NOT_FOUND, ("model_not_found", "notfounderror", "does not exist", "model is not supported")),
    (_RATE, ("rate_limit", "rate limit", "ratelimiterror", "too many requests")),
    (_CONTENT, ("content_policy", "contentpolicyviolation", "content management policy")),
    (_TIMEOUT, ("timed out", "timeout")),
    (
        _CONNECTION,
        (
            "apiconnectionerror",
            "connection error",
            "connection refused",
            "name or service not known",
            "temporary failure in name resolution",
        ),
    ),
    (_UNAVAILABLE, ("overloaded", "service unavailable", "internalservererror", "bad gateway")),
)

_CATEGORY_STATUS: dict[int, str] = {
    401: _AUTH,
    402: _QUOTA,
    403: _PERMISSION,
    404: _NOT_FOUND,
    408: _TIMEOUT,
    413: _CONTEXT,
    429: _RATE,
    500: _UNAVAILABLE,
    502: _UNAVAILABLE,
    503: _UNAVAILABLE,
    504: _TIMEOUT,
    529: _UNAVAILABLE,
}

INTERNAL_MESSAGE = (
    "Something went wrong while answering. The details are in the error log. Try again."
)


def provider_label(text: str, provider: str | None = None) -> str | None:
    """Name the model provider behind a failure, if it can be told.

    Args:
        text: The provider's error text.
        provider: LiteLLM's `llm_provider` for the failed call, when known.

    Returns:
        A display name such as ``"OpenAI"``, or None when the provider cannot
        be identified, in which case the caller says "the AI provider".
    """
    candidates = []
    if provider:
        candidates.append(provider)
    candidates.extend(match.group(1) for match in _EXCEPTION_PREFIX.finditer(text or ""))
    for candidate in candidates:
        key = re.sub(r"[^a-z0-9]", "", str(candidate).lower())
        if key in _PROVIDER_LABELS:
            return _PROVIDER_LABELS[key]
    return None


def status_code(text: str, status: int | None = None) -> int | None:
    """The HTTP status of a provider failure, from the exception or its text."""
    if isinstance(status, int) and 100 <= status <= 599:
        return status
    for pattern in _STATUS_PATTERNS:
        match = pattern.search(text or "")
        if match:
            return int(match.group(1))
    return None


def _category(names: Iterable[str], text: str, status: int | None) -> str | None:
    """Which kind of provider failure this is, or None when it cannot be told."""
    names = set(names)
    lowered = (text or "").lower()
    # Markers first for the two categories a class name hides: an exhausted
    # balance usually arrives as a RateLimitError, and an over-long prompt as a
    # BadRequestError.
    for category, markers in _CATEGORY_MARKERS[:2]:
        if any(marker in lowered for marker in markers):
            return category
    for category, class_names in _CATEGORY_NAMES:
        if names & class_names:
            return category
    for category, markers in _CATEGORY_MARKERS[2:]:
        if any(marker in lowered for marker in markers):
            return category
    if names & _GENERIC_NAMES:
        return _BAD_REQUEST
    if status is not None:
        return _CATEGORY_STATUS.get(status) or (_UNAVAILABLE if status >= 500 else None)
    return None


def _sentence(category: str | None, label: str | None) -> str:
    """The sentence for one category, naming the provider where it is known."""
    who = label or "the AI provider"
    Who = label or "The AI provider"  # noqa: N806 - the sentence-initial form of `who`
    if label == "ChatGPT":
        # A ChatGPT plan signs in rather than using an API key, and its 403 is a
        # model OpenAlgo has not registered for the plan, not a refused key.
        if category == _AUTH:
            return "Your ChatGPT sign-in has expired or was removed. Sign in to ChatGPT again from agent settings."
        if category in (_PERMISSION, _NOT_FOUND):
            return "ChatGPT could not run the model chosen in agent settings. Choose another model there."
    sentences = {
        _CONTEXT: "This conversation has grown too long for the model. Start a new chat and ask again.",
        _QUOTA: f"Your {who} account has no credits left. Add credits under billing, then try again.",
        _AUTH: f"{Who} did not accept the API key for this model. Enter a valid key in agent settings.",
        _PERMISSION: (
            f"{Who} does not allow this API key to use this model. "
            "Check the key's access, or choose another model in agent settings."
        ),
        _NOT_FOUND: f"{Who} does not offer the model chosen in agent settings. Choose another model there.",
        _RATE: f"{Who} is limiting requests right now. Wait a minute, then try again.",
        _CONTENT: f"{Who} declined to answer this request. Rephrase it and try again.",
        _TIMEOUT: f"{Who} took too long to answer. Try again.",
        _CONNECTION: f"OpenAlgo could not reach {who}. Check that the server is online, then try again.",
        _UNAVAILABLE: f"{Who} is having trouble right now. Try again in a few minutes.",
        _BAD_REQUEST: (
            f"{Who} could not process this request. Try again, or choose another model in agent settings."
        ),
    }
    return sentences.get(
        category,
        f"{Who} could not complete this request. Try again, or check the model in agent settings.",
    )


def trader_message(
    kind: str,
    names: Iterable[str],
    text: str,
    *,
    provider: str | None = None,
    status: int | None = None,
) -> str | None:
    """The sentence a trader sees for a failed run, or None to keep the original.

    Args:
        kind: The :class:`ErrorKind` the failure was classified as.
        names: Exception class names involved, most specific first.
        text: The failure's own text, already redacted.
        provider: LiteLLM's `llm_provider` for the call, when known.
        status: The HTTP status the exception carries, when it has one.

    Returns:
        A sentence for a provider failure or an internal one. None for a tool,
        input or configuration failure, whose text this platform wrote for the
        trader already and which is kept as it is.
    """
    if kind == ErrorKind.PROVIDER:
        code = status_code(text, status)
        return _sentence(_category(names, text, code), provider_label(text, provider))
    if kind == ErrorKind.INTERNAL:
        return INTERNAL_MESSAGE
    return None
