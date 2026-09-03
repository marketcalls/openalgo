"""Provider vocabulary, and how a configured model becomes LiteLLM kwargs.

`provider_kind` is a closed vocabulary of five values, not a database table.
Everything that varies between real-world providers (OpenAI, Anthropic, Ollama,
Groq, DeepSeek, a local vLLM endpoint) reduces to three questions this module
answers: does it need an API key, does it need a base URL, and what does its
model id look like to LiteLLM. Adding a provider is a database row, not a code
change, which is only true because the vocabulary stays closed.

There is no LiteLLM proxy and no registry to sync. The model is constructed per
run from the `ag_provider_model` row and the decrypted key, so a configuration
change takes effect on the next request with no restart and no sync step.

Like :mod:`services.agent.frames` this module does no I/O and imports nothing
from agno. It builds a kwargs dict; the caller passes it to
`agno.models.litellm.LiteLLM`. That keeps the mapping testable by asserting the
dict, with no provider ever called.

    **The argument is `api_base`, not `base_url`.** `base_url` belongs to the
    separate `LiteLLMOpenAI` proxy class, which this module deliberately does
    not use. Passing `base_url` to `LiteLLM` is silently ignored, and the call
    then goes to the public endpoint instead of the operator's local one.

Typical use
-----------

    from services.agent.providers import litellm_kwargs, validate_provider_config

    error = validate_provider_config(kind, model_name, base_url, has_key)
    if error:
        raise ValueError(error)
    model = LiteLLM(**litellm_kwargs(row, api_key))
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

# The closed vocabulary. The frontend's provider card grid is a static constant
# that maps a real-world brand onto one of these; the backend never sees a brand
# name, only a kind.
PROVIDER_KINDS: tuple[str, ...] = (
    "openai",
    "anthropic",
    "ollama",
    "openai_compatible",
    "litellm",
)


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    """What one provider kind requires and how it addresses LiteLLM.

    Attributes:
        kind: The `provider_kind` value stored on `ag_provider_model`.
        label: Human-readable name, used in validation messages.
        needs_key: Whether an API key is mandatory.
        needs_base_url: Whether a base URL is mandatory, and therefore whether
            `api_base` is passed to LiteLLM for this kind.
        prefix: The LiteLLM provider prefix prepended to the model name. Empty
            for `litellm`, whose model name already carries its own prefix and
            is passed through verbatim.
    """

    kind: str
    label: str
    needs_key: bool
    needs_base_url: bool
    prefix: str


# The provider table from the build contract, verbatim:
#
#   kind               needs key  needs base_url  LiteLLM model id
#   openai             yes        no              openai/{model_name}
#   anthropic          yes        no              anthropic/{model_name}
#   ollama             no         yes             ollama/{model_name} + api_base
#   openai_compatible  yes        yes             openai/{model_name} + api_base
#   litellm            yes        no              {model_name} verbatim
#
# `openai_compatible` requires a key because LiteLLM's OpenAI transport sends an
# Authorization header unconditionally. An endpoint that checks no credential
# still needs a placeholder here rather than nothing at all.
PROVIDER_SPECS: Mapping[str, ProviderSpec] = MappingProxyType(
    {
        "openai": ProviderSpec(
            kind="openai",
            label="OpenAI",
            needs_key=True,
            needs_base_url=False,
            prefix="openai",
        ),
        "anthropic": ProviderSpec(
            kind="anthropic",
            label="Anthropic",
            needs_key=True,
            needs_base_url=False,
            prefix="anthropic",
        ),
        "ollama": ProviderSpec(
            kind="ollama",
            label="Ollama",
            needs_key=False,
            needs_base_url=True,
            prefix="ollama",
        ),
        "openai_compatible": ProviderSpec(
            kind="openai_compatible",
            label="OpenAI-compatible endpoint",
            needs_key=True,
            needs_base_url=True,
            prefix="openai",
        ),
        "litellm": ProviderSpec(
            kind="litellm",
            label="LiteLLM",
            needs_key=True,
            needs_base_url=False,
            prefix="",
        ),
    }
)


def provider_spec(kind: str) -> ProviderSpec:
    """Look up the spec for a provider kind.

    Args:
        kind: A value from :data:`PROVIDER_KINDS`.

    Returns:
        The matching :class:`ProviderSpec`.

    Raises:
        ValueError: If `kind` is not in the closed vocabulary.
    """
    spec = PROVIDER_SPECS.get((kind or "").strip())
    if spec is None:
        raise ValueError(_unknown_kind_message(kind))
    return spec


def requires_key(kind: str) -> bool:
    """Whether this provider kind needs an API key.

    Args:
        kind: A value from :data:`PROVIDER_KINDS`.

    Returns:
        True when a key is mandatory.

    Raises:
        ValueError: If `kind` is not in the closed vocabulary.
    """
    return provider_spec(kind).needs_key


def requires_base_url(kind: str) -> bool:
    """Whether this provider kind needs a base URL.

    Args:
        kind: A value from :data:`PROVIDER_KINDS`.

    Returns:
        True when a base URL is mandatory, and therefore when `api_base` is
        included in the LiteLLM kwargs.

    Raises:
        ValueError: If `kind` is not in the closed vocabulary.
    """
    return provider_spec(kind).needs_base_url


def normalize_base_url(base_url: str | None) -> str:
    """Trim a base URL into the form LiteLLM expects.

    Whitespace and trailing slashes go, because an operator pasting a URL out of
    a terminal brings both and `http://host:11434/` joined to a path yields a
    double slash that some gateways route differently from a single one.

    Args:
        base_url: The raw value from the row or the form, possibly None.

    Returns:
        The trimmed URL, or an empty string when nothing usable was given.
    """
    return (base_url or "").strip().rstrip("/")


def litellm_model_id(kind: str, model_name: str) -> str:
    """Build the LiteLLM model id for a configured model.

    `litellm` is passed through verbatim: its model name already carries a
    provider prefix, which is the whole point of that kind. For every other kind
    the prefix is prepended, unless the operator already typed it. Copying
    `openai/gpt-4o` out of LiteLLM's own documentation into an `openai` row is a
    likely mistake and `openai/openai/gpt-4o` addresses nothing, so the prefix
    is applied once at most.

    Args:
        kind: A value from :data:`PROVIDER_KINDS`.
        model_name: The model name as configured on the row.

    Returns:
        The model id to pass as LiteLLM's `id`.

    Raises:
        ValueError: If `kind` is unknown or `model_name` is blank.
    """
    spec = provider_spec(kind)
    name = (model_name or "").strip()
    if not name:
        raise ValueError("A model name is required")
    if not spec.prefix:
        return name
    if name.startswith(f"{spec.prefix}/"):
        return name
    return f"{spec.prefix}/{name}"


def litellm_kwargs(row: Any, api_key: str | None = None) -> dict[str, Any]:
    """Build the kwargs for `agno.models.litellm.LiteLLM` from a model row.

    The row is read by attribute or by key, so an `ag_provider_model` ORM
    instance, a dict from a request body and a test fixture all work.

    The key is never taken from the row: it lives in `ag_secret` and is
    decrypted by the caller, which keeps the plaintext out of anything that
    might be logged or serialised alongside the model configuration.

    Args:
        row: An object or mapping exposing `provider_kind`, `model_name` and
            `base_url`.
        api_key: The decrypted API key, or None for a keyless provider.

    Returns:
        A dict carrying `id`, plus `api_key` when a key was supplied, plus
        `api_base` when the provider kind uses one. A base URL set on a kind
        that does not use one is ignored rather than forwarded, because
        forwarding it would send the call somewhere the operator's configuration
        does not describe.

    Raises:
        ValueError: If the row does not describe a usable model. Resolution
            happens before the first stream byte is written, so this surfaces as
            a clean HTTP error rather than a truncated stream.
    """
    kind = str(_row_value(row, "provider_kind") or "").strip()
    model_name = str(_row_value(row, "model_name") or "").strip()
    base_url = normalize_base_url(_row_value(row, "base_url"))
    key = (api_key or "").strip()

    error = validate_provider_config(kind, model_name, base_url, has_key=bool(key))
    if error:
        raise ValueError(error)

    kwargs: dict[str, Any] = {"id": litellm_model_id(kind, model_name)}
    if key:
        kwargs["api_key"] = key
    if provider_spec(kind).needs_base_url:
        kwargs["api_base"] = base_url
    return kwargs


def validate_provider_config(
    kind: str,
    model_name: str,
    base_url: str | None = None,
    has_key: bool = False,
) -> str | None:
    """Check a model configuration before it is saved or used.

    Takes `has_key` rather than the key itself so the same function guards a
    save, where the key is being set, and a run, where it has already been
    decrypted somewhere else. Nothing here needs the secret's value.

    Args:
        kind: The provider kind, which must be in :data:`PROVIDER_KINDS`.
        model_name: The model name passed to LiteLLM.
        base_url: The configured base URL, if any.
        has_key: Whether an API key is available for this model, from either the
            per-model override or the shared provider key.

    Returns:
        A message describing the first problem found, suitable for showing to
        the operator, or None when the configuration is usable.
    """
    kind = (kind or "").strip()
    spec = PROVIDER_SPECS.get(kind)
    if spec is None:
        return _unknown_kind_message(kind)

    if not (model_name or "").strip():
        return "A model name is required"

    url = normalize_base_url(base_url)
    if spec.needs_base_url and not url:
        return f"{spec.label} requires a base URL"
    if url and not url.startswith(("http://", "https://")):
        return "The base URL must start with http:// or https://"

    if spec.needs_key and not has_key:
        return f"{spec.label} requires an API key"

    return None


def _row_value(row: Any, name: str) -> Any:
    """Read one field from a model row that may be an object or a mapping.

    Args:
        row: An ORM instance, a dataclass, a dict, or anything else exposing the
            field by attribute.
        name: The field name.

    Returns:
        The field's value, or None when the row does not carry it.
    """
    if isinstance(row, Mapping):
        return row.get(name)
    return getattr(row, name, None)


def _unknown_kind_message(kind: str) -> str:
    """Build the message for a provider kind outside the closed vocabulary.

    Args:
        kind: The rejected value.

    Returns:
        A message naming the offending value and every accepted one.
    """
    accepted = ", ".join(PROVIDER_KINDS)
    return f"Unknown provider kind {kind!r}. Expected one of: {accepted}"
