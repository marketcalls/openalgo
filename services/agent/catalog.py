"""The provider and model catalogue, read from LiteLLM at runtime.

**Nothing about providers or models is stored in the database.** The registry in
`ag_provider_model` holds operator intent only: which models are enabled, which
one is default, and how each authenticates. What models exist, what they cost
and what they can do is read from LiteLLM's own in-package data every time the
process starts, which makes maintenance a single action: bump `litellm`. New
providers and models arrive with the package. There is no catalogue table, no
generated TypeScript constant, no regeneration script and no network call.

Verified against `litellm==1.99.0`:

* `litellm.LITELLM_CHAT_PROVIDERS` lists 94 chat-capable providers, 93 of them
  distinct because `baseten` appears twice. This is the list
  :func:`list_providers` offers. `litellm.provider_list` has 152 but includes
  embedding, image, audio and rerank-only providers, and presenting a rerank
  provider as somewhere to run a chat agent is noise.
* `litellm.models_by_provider` maps 96 providers onto 3021 model names.
* `litellm.model_cost` carries 3517 entries of per-model metadata:
  `max_input_tokens`, `max_output_tokens`, `input_cost_per_token`,
  `output_cost_per_token`, `mode` and `supports_function_calling`.

`supports_function_calling` is load-bearing rather than decoration. This agent
is entirely tool-driven, so a model that cannot call a function cannot drive it
at all. It is surfaced on every :class:`ModelInfo` so a caller can grey the
model out with a reason and refuse to make it the default. It is `None`, not
`False`, when the model is absent from `model_cost`, because "we do not know"
and "we know it cannot" lead to different UI.

Why not `litellm.get_model_info`
--------------------------------

It resolves a prefixed id nicely but it **invents metadata**. Measured at
1.99.0, `get_model_info("ollama/definitely-not-a-real-model-xyz")` returns a
complete entry with `input_cost_per_token` and `output_cost_per_token` of `0.0`
for a model that does not exist, which is exactly the guessed price this module
must never produce. It also raises on an unmapped model and writes a provider
list to the console on the way. This module reads the raw dicts instead, so an
absent model is absent and :func:`estimate_cost` answers `None`.

Advisory, not authoritative
---------------------------

A model missing from the catalogue is still addable by hand. `needs_key` and
`needs_base_url` are a hint for the setup UI, derived from LiteLLM 1.99.0's own
`validate_environment` plus the known self-hosted providers; what actually
gates a save is `services.agent.providers.validate_provider_config`, which works
off the five `provider_kind` values and never consults this module.

Typical use
-----------

    from services.agent import catalog

    grid = [provider.as_dict() for provider in catalog.list_providers()]

    usable = [
        model
        for model in catalog.list_models("anthropic")
        if model.supports_function_calling is not False
    ]

    cost = catalog.estimate_cost("openai/gpt-4o", 12_000, 800)
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from services.agent import chatgpt_models
from services.agent.providers import PROVIDER_KINDS
from utils.logging import get_logger

logger = get_logger(__name__)

# Prices in `model_cost` are per token and therefore tiny. The picker shows them
# per million tokens, which is how every provider publishes them.
TOKENS_PER_MILLION = 1_000_000

# Display prices are rounded here only. `estimate_cost` multiplies the raw
# per-token figure, so a rounded display price never compounds into a bill.
PRICE_DECIMALS = 6

# A cost estimate is a fraction of a cent for a short turn, so it is kept to ten
# places rather than to currency precision.
COST_DECIMALS = 10

# Modes that describe something you can hold a conversation with. `chat` is the
# bulk of it; `responses` is OpenAI's Responses API, which is the only mode some
# current models have; `completion` is legacy text completion, listed because
# otherwise a provider whose only priced models are legacy shows an empty
# picker, and because `supports_function_calling` is what actually decides
# whether a model can drive this agent.
CHAT_MODES: frozenset[str] = frozenset({"chat", "completion", "responses"})

# `model_cost` ships a documentation placeholder under this key whose values are
# prose rather than numbers. It is not a model and must never reach the picker.
PLACEHOLDER_MODELS: frozenset[str] = frozenset({"sample_spec"})

# Display name and icon slug for the brands an operator is likely to recognise.
# The icon is a **slug the frontend resolves to its own asset**, never a URL and
# never an emoji. Anything absent from this map falls back to the provider id
# and an empty slug, so a provider that a future LiteLLM release adds still
# appears in the grid instead of disappearing until someone updates a table.
_BRANDS: Mapping[str, tuple[str, str]] = MappingProxyType(
    {
        "ai21": ("AI21 Labs", "ai21"),
        "ai21_chat": ("AI21 Labs (chat)", "ai21"),
        "amazon_nova": ("Amazon Nova", "aws"),
        "anthropic": ("Anthropic", "anthropic"),
        "anthropic_text": ("Anthropic (text)", "anthropic"),
        "azure": ("Azure OpenAI", "azure"),
        "azure_ai": ("Azure AI Foundry", "azure"),
        "azure_text": ("Azure OpenAI (text)", "azure"),
        "baseten": ("Baseten", "baseten"),
        "bedrock": ("Amazon Bedrock", "aws"),
        "cerebras": ("Cerebras", "cerebras"),
        "chatgpt": ("ChatGPT", "openai"),
        "clarifai": ("Clarifai", "clarifai"),
        "cloudflare": ("Cloudflare Workers AI", "cloudflare"),
        "codestral": ("Mistral Codestral", "mistral"),
        "cohere": ("Cohere", "cohere"),
        "cohere_chat": ("Cohere (chat)", "cohere"),
        "custom": ("Custom endpoint", ""),
        "custom_openai": ("Custom OpenAI endpoint", "openai"),
        "dashscope": ("Alibaba DashScope", "alibaba"),
        "databricks": ("Databricks", "databricks"),
        "deepinfra": ("DeepInfra", "deepinfra"),
        "deepseek": ("DeepSeek", "deepseek"),
        "docker_model_runner": ("Docker Model Runner", "docker"),
        "featherless_ai": ("Featherless AI", "featherless"),
        "fireworks_ai": ("Fireworks AI", "fireworks"),
        "friendliai": ("FriendliAI", "friendliai"),
        "gemini": ("Google Gemini", "google"),
        "github": ("GitHub Models", "github"),
        "github_copilot": ("GitHub Copilot", "github"),
        "gradient_ai": ("DigitalOcean Gradient AI", "digitalocean"),
        "groq": ("Groq", "groq"),
        "hosted_vllm": ("vLLM (hosted)", "vllm"),
        "huggingface": ("Hugging Face", "huggingface"),
        "inception": ("Inception", "inception"),
        "lambda_ai": ("Lambda", "lambda"),
        "litellm_proxy": ("LiteLLM Proxy", "litellm"),
        "llamafile": ("llamafile", "llamafile"),
        "lm_studio": ("LM Studio", "lmstudio"),
        "meta_llama": ("Meta Llama", "meta"),
        "mistral": ("Mistral AI", "mistral"),
        "modelscope": ("ModelScope", "modelscope"),
        "moonshot": ("Moonshot AI", "moonshot"),
        "nebius": ("Nebius AI Studio", "nebius"),
        "novita": ("Novita AI", "novita"),
        "nvidia_nim": ("NVIDIA NIM", "nvidia"),
        "oci": ("Oracle OCI", "oracle"),
        "ollama": ("Ollama", "ollama"),
        "ollama_chat": ("Ollama (chat)", "ollama"),
        "oobabooga": ("Oobabooga", ""),
        "openai": ("OpenAI", "openai"),
        "openai_like": ("OpenAI-compatible endpoint", "openai"),
        "openrouter": ("OpenRouter", "openrouter"),
        "perplexity": ("Perplexity", "perplexity"),
        "petals": ("Petals", ""),
        "replicate": ("Replicate", "replicate"),
        "sagemaker": ("Amazon SageMaker", "aws"),
        "sagemaker_chat": ("Amazon SageMaker (chat)", "aws"),
        "sagemaker_nova": ("Amazon SageMaker Nova", "aws"),
        "sambanova": ("SambaNova", "sambanova"),
        "tencent": ("Tencent Hunyuan", "tencent"),
        "text-completion-openai": ("OpenAI (text completion)", "openai"),
        "together_ai": ("Together AI", "together"),
        "triton": ("NVIDIA Triton", "nvidia"),
        "v0": ("v0", "vercel"),
        "vercel_ai_gateway": ("Vercel AI Gateway", "vercel"),
        "vertex_ai": ("Google Vertex AI", "google"),
        "vertex_ai_beta": ("Google Vertex AI (beta)", "google"),
        "vllm": ("vLLM", "vllm"),
        "volcengine": ("Volcengine", "volcengine"),
        "wandb": ("Weights and Biases", "wandb"),
        "watsonx": ("IBM watsonx", "ibm"),
        "watsonx_text": ("IBM watsonx (text)", "ibm"),
        "xai": ("xAI", "xai"),
    }
)

# Providers that take no single API key. Two different reasons, both ending in
# "the key field does not apply": a self-hosted server that authenticates
# nothing, and a cloud provider that authenticates with ambient IAM credentials
# rather than with a string an operator can paste. Everything else defaults to
# needing a key, which LiteLLM 1.99.0's `validate_environment` bears out for
# every provider it covers.
_KEYLESS_PROVIDERS: frozenset[str] = frozenset(
    {
        # A ChatGPT plan, reached through an OAuth device flow rather than a
        # pasteable key. See services/agent/chatgpt_oauth.py: the credential is a
        # refresh token this module never shows and the operator never types, so
        # a key field on the provider card asks for something that cannot exist.
        "chatgpt",
        "custom",
        "custom_openai",
        "docker_model_runner",
        "lemonade",
        "llamafile",
        "lm_studio",
        "ollama",
        "ollama_chat",
        "oobabooga",
        "openai_like",
        "petals",
        "triton",
        "vllm",
        # Cloud IAM rather than a pasteable key.
        "bedrock",
        "sagemaker",
        "sagemaker_chat",
        "sagemaker_nova",
        "vertex_ai",
        "vertex_ai_beta",
    }
)

# Providers whose endpoint the operator has to name, because there is no public
# one to default to. `ollama` and `ollama_chat` are here on LiteLLM's own
# authority: with an empty environment `validate_environment("ollama/x")` asks
# for `OLLAMA_API_BASE` and no key at all.
_BASE_URL_PROVIDERS: frozenset[str] = frozenset(
    {
        "azure",
        "azure_ai",
        "azure_text",
        "custom",
        "custom_openai",
        "databricks",
        "docker_model_runner",
        "hosted_vllm",
        "lemonade",
        "litellm_proxy",
        "llamafile",
        "lm_studio",
        "ollama",
        "ollama_chat",
        "oobabooga",
        "openai_like",
        "triton",
        "vllm",
        "watsonx",
        "watsonx_text",
    }
)

# Suggested `provider_kind` for the create flow. Only exact matches are mapped;
# everything else is `litellm`, whose model name carries its own prefix and is
# passed to LiteLLM verbatim. `openai_compatible` is the right kind for any
# OpenAI-shaped server the operator hosts: it addresses the model as
# `openai/{name}` and sends `api_base` alongside.
_PROVIDER_KINDS: Mapping[str, str] = MappingProxyType(
    {
        "anthropic": "anthropic",
        "custom": "openai_compatible",
        "custom_openai": "openai_compatible",
        "docker_model_runner": "openai_compatible",
        "hosted_vllm": "openai_compatible",
        "lemonade": "openai_compatible",
        "litellm_proxy": "openai_compatible",
        "llamafile": "openai_compatible",
        "lm_studio": "openai_compatible",
        "ollama": "ollama",
        "openai": "openai",
        "openai_like": "openai_compatible",
        "vllm": "openai_compatible",
    }
)

DEFAULT_PROVIDER_KIND = "litellm"


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    """One chat-capable provider, as offered in the setup grid.

    Attributes:
        id: The LiteLLM provider id, which is what `models_by_provider` and the
            `litellm_provider` field of a cost entry are keyed by.
        display_name: The brand name, or the provider id when the brand is not
            in the local map.
        icon: An icon slug the frontend resolves to its own asset, or an empty
            string when no brand asset is known.
        provider_kind: The suggested `ag_provider_model.provider_kind` for
            models of this provider. Advisory; the operator can override it.
        needs_key: Whether a single pasteable API key applies. False covers both
            a self-hosted server that authenticates nothing and a cloud provider
            that uses ambient IAM credentials.
        needs_base_url: Whether the operator has to name the endpoint.
        model_count: How many of this provider's models are conversational,
            which is what the picker will list.
        total_model_count: How many models LiteLLM lists for it in every mode,
            including embedding, image and audio.
    """

    id: str
    display_name: str
    icon: str
    provider_kind: str
    needs_key: bool
    needs_base_url: bool
    model_count: int
    total_model_count: int

    def as_dict(self) -> dict[str, Any]:
        """Render as a JSON-safe dict for the `/agent/api/catalog` response.

        Returns:
            A dict of plain types, one key per attribute.
        """
        return {
            "id": self.id,
            "display_name": self.display_name,
            "icon": self.icon,
            "provider_kind": self.provider_kind,
            "needs_key": self.needs_key,
            "needs_base_url": self.needs_base_url,
            "model_count": self.model_count,
            "total_model_count": self.total_model_count,
        }


@dataclass(frozen=True, slots=True)
class ModelInfo:
    """One model, enriched from `litellm.model_cost` where an entry exists.

    Every enriched field is optional, and `None` means the catalogue does not
    know rather than that the answer is zero. A price of `None` is why
    :func:`estimate_cost` returns `None` instead of inventing a number.

    Attributes:
        id: The model name exactly as LiteLLM lists it for the provider, which
            is what belongs in `ag_provider_model.model_name`.
        provider: The LiteLLM provider id this model was listed under.
        qualified_id: `id` with the provider prefix applied if it was not there
            already. This is the string to store when `provider_kind` is
            `litellm`, whose model name carries its own prefix.
        catalog_key: The `model_cost` key the enrichment came from, or None when
            the model has no cost entry.
        mode: The `model_cost` mode, for example `chat` or `embedding`.
        max_input_tokens: The context window in tokens.
        max_output_tokens: The most tokens one response may contain.
        input_price_per_million: USD per million input tokens, rounded for
            display.
        output_price_per_million: USD per million output tokens, rounded for
            display.
        supports_function_calling: Whether the model can call tools. This agent
            is entirely tool-driven, so False means the model cannot drive it and
            None means nobody knows.
        supports_vision: Whether the model accepts images.
        supports_reasoning: Whether the model exposes a reasoning effort.
    """

    id: str
    provider: str
    qualified_id: str
    catalog_key: str | None
    mode: str | None
    max_input_tokens: int | None
    max_output_tokens: int | None
    input_price_per_million: float | None
    output_price_per_million: float | None
    supports_function_calling: bool | None
    supports_vision: bool | None
    supports_reasoning: bool | None

    @property
    def in_catalog(self) -> bool:
        """Whether LiteLLM carries cost and capability metadata for this model.

        Returns:
            True when a `model_cost` entry was found.
        """
        return self.catalog_key is not None

    @property
    def is_chat(self) -> bool:
        """Whether this model is something you can hold a conversation with.

        An unknown mode counts as conversational. The catalogue is advisory, and
        hiding a model LiteLLM lists for a chat provider merely because nobody
        priced it would empty the picker for several real providers.

        Returns:
            True when the mode is conversational or unknown.
        """
        return self.mode is None or self.mode in CHAT_MODES

    def as_dict(self) -> dict[str, Any]:
        """Render as a JSON-safe dict for the `/agent/api/catalog` response.

        Returns:
            A dict of plain types, one key per attribute plus the two derived
            flags the picker renders from.
        """
        return {
            "id": self.id,
            "provider": self.provider,
            "qualified_id": self.qualified_id,
            "catalog_key": self.catalog_key,
            "mode": self.mode,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "input_price_per_million": self.input_price_per_million,
            "output_price_per_million": self.output_price_per_million,
            "supports_function_calling": self.supports_function_calling,
            "supports_vision": self.supports_vision,
            "supports_reasoning": self.supports_reasoning,
            "in_catalog": self.in_catalog,
            "is_chat": self.is_chat,
        }


# Derived structures, built once on first use. LiteLLM's data is a package
# constant and does not change for the lifetime of the process, so there is
# nothing to invalidate and no staleness to worry about.
#
# There is deliberately **no lock**. Two threads racing here build identical
# structures and the last plain assignment wins, which costs a few wasted
# milliseconds at worst. A lock would cost more than that: the catalogue is read
# from the green request handler and from the real OS thread the agent runs on,
# and a greenlet waiting on a real lock stops the single eventlet worker for as
# long as the holder takes.
_providers: tuple[ProviderInfo, ...] | None = None
_models: Mapping[str, tuple[ModelInfo, ...]] | None = None
_entries: Mapping[str, Mapping[str, Any]] | None = None
_provider_ids: frozenset[str] | None = None

# Set once so a missing LiteLLM is reported with a traceback exactly one time
# rather than on every catalogue read.
_import_failed = False


def is_available() -> bool:
    """Whether LiteLLM is importable, and therefore whether a catalogue exists.

    Returns:
        True when `litellm` imported. When False every accessor here answers
        empty or None: the catalogue is advisory, so its absence disables the
        picker's suggestions without disabling the agent, which can still run a
        model an operator configured by hand.
    """
    return _litellm() is not None


def list_providers() -> list[ProviderInfo]:
    """List the chat-capable providers LiteLLM knows about.

    Built from `litellm.LITELLM_CHAT_PROVIDERS`, not from
    `litellm.provider_list`: the latter's 152 entries include embedding, image,
    audio and rerank-only providers that cannot host a chat agent. Duplicates
    are collapsed, because LITELLM_CHAT_PROVIDERS ships `baseten` twice at
    1.99.0.

    Returns:
        Every provider, sorted by display name, case-insensitively. Empty when
        LiteLLM is not importable.
    """
    _build()
    return list(_providers or ())


def get_provider(provider: str) -> ProviderInfo | None:
    """Look up one provider.

    Args:
        provider: A LiteLLM provider id, for example `anthropic`.

    Returns:
        The matching :class:`ProviderInfo`, or None when the id is not a
        chat-capable provider LiteLLM knows about.
    """
    _build()
    wanted = _clean(provider)
    if not wanted:
        return None
    for info in _providers or ():
        if info.id == wanted:
            return info
    return None


def list_models(provider: str, *, chat_only: bool = True) -> list[ModelInfo]:
    """List a provider's models, enriched from `litellm.model_cost`.

    Args:
        provider: A LiteLLM provider id, for example `openai`.
        chat_only: When True, drop models whose mode is known and is not
            conversational, which is what removes the embedding, image, audio,
            rerank and moderation entries that share a provider with the chat
            ones. A model with no cost entry has no known mode and is kept,
            because the catalogue is advisory and several real providers have no
            priced models at all.

    Returns:
        The provider's models in LiteLLM's own order. Empty for an unknown
        provider, and empty when LiteLLM is not importable. An unknown provider
        is not an error: the catalogue is a lookup, and the set of providers
        worth offering is decided by :func:`list_providers`.
    """
    _build()
    models = (_models or {}).get(_clean(provider), ())
    if chat_only:
        return [model for model in models if model.is_chat]
    return list(models)


def get_model_meta(model_name: str, provider: str | None = None) -> ModelInfo | None:
    """Look up the catalogue metadata for one model.

    Accepts a bare name (`gpt-4o`), a prefixed id (`openai/gpt-4o`, which is
    what `providers.litellm_model_id` builds), or a name plus its provider. When
    a provider is known it is preferred over a bare match, because a bare name
    can belong to a different provider at a different price: `gpt-4o` is priced
    under `openai`, while the Azure deployment of the same model is a separate
    `azure/gpt-4o` entry.

    Args:
        model_name: The model name or prefixed model id.
        provider: The LiteLLM provider id, when the caller knows it.

    Returns:
        A :class:`ModelInfo` carrying the requested name as its `id`, or None
        when no cost entry matches and therefore nothing is known about it.
    """
    _build()
    name = _clean(model_name)
    if not name:
        return None

    key, entry = _resolve_entry(name, _clean(provider) or None)
    if entry is None:
        return None

    owner = _clean(entry.get("litellm_provider")) or _clean(provider) or _prefix_of(name)
    return _model_info(name, owner, key, entry)


def estimate_cost(
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    provider: str | None = None,
    cached_tokens: int = 0,
) -> float | None:
    """Cost a completed turn in USD from LiteLLM's per-token prices.

    Arithmetic on the raw `input_cost_per_token` and `output_cost_per_token`,
    not on the rounded per-million figures the picker displays, so a displayed
    price never compounds into the number the operator is shown.

    **A price is never guessed.** A model with no cost entry, or an entry that
    does not price the side being charged for, returns None. The usage frame
    then reports the token counts with `cost_usd: null`, because showing tokens
    and admitting the price is unknown beats inventing a number.

    Cached prompt tokens are a **subset** of `input_tokens`, which is how every
    provider reports them, so they are subtracted from the full-price count and
    charged at `cache_read_input_token_cost` instead. An entry that publishes no
    cache price is charged at the model's own full input price rather than
    discounted on a guess: that is the model's published number, not an invented
    one, and it errs towards over-reporting rather than under-reporting a bill.

    Args:
        model_name: The model name or prefixed model id.
        input_tokens: Prompt tokens consumed, including any cached ones.
            Negative counts are clamped to zero.
        output_tokens: Completion tokens produced. Negative counts are clamped
            to zero.
        provider: The LiteLLM provider id, when the caller knows it.
        cached_tokens: How many of `input_tokens` were served from the
            provider's prompt cache. Clamped into `[0, input_tokens]`, so a
            count larger than the prompt cannot drive the billed portion
            negative.

    Returns:
        The cost in USD, or None when it cannot be computed without guessing.
    """
    _build()
    name = _clean(model_name)
    if not name:
        return None

    _, entry = _resolve_entry(name, _clean(provider) or None)
    if entry is None:
        return None

    used_in = _tokens(input_tokens)
    used_out = _tokens(output_tokens)
    used_cached = _tokens(cached_tokens)
    if used_in is None or used_out is None or used_cached is None:
        return None
    used_cached = min(used_cached, used_in)
    billed_in = used_in - used_cached

    price_in = _as_float(entry.get("input_cost_per_token"))
    price_out = _as_float(entry.get("output_cost_per_token"))
    price_cached = _as_float(entry.get("cache_read_input_token_cost"))
    if price_cached is None:
        price_cached = price_in

    # Charge only for a side that was actually used, and refuse only when the
    # side that was used has no price. A model that priced its input but not its
    # output still costs a known amount for a turn that produced nothing.
    if (billed_in or used_cached) and price_in is None:
        return None
    if used_out and price_out is None:
        return None
    if not used_in and not used_out:
        return 0.0

    total = (
        billed_in * (price_in or 0.0)
        + used_cached * (price_cached or 0.0)
        + used_out * (price_out or 0.0)
    )
    return round(total, COST_DECIMALS)


def supports_function_calling(model_name: str, provider: str | None = None) -> bool | None:
    """Whether a model can call tools, which this agent requires of every model.

    Args:
        model_name: The model name or prefixed model id.
        provider: The LiteLLM provider id, when the caller knows it.

    Returns:
        True or False when the catalogue knows, None when the model has no cost
        entry. A caller refusing a model should refuse on False and warn on
        None, because the two need different messages: one is a fact about the
        model, the other is a gap in the catalogue.
    """
    meta = get_model_meta(model_name, provider)
    return meta.supports_function_calling if meta else None


def invalidate_cache() -> None:
    """Drop the derived structures so the next read rebuilds them.

    LiteLLM's data does not change while the process runs, so nothing in normal
    operation needs this. It exists so a test can force a rebuild after
    substituting the module's data.
    """
    global _providers, _models, _entries, _provider_ids
    _providers = None
    _models = None
    _entries = None
    _provider_ids = None


def _litellm() -> Any | None:
    """Import LiteLLM on demand.

    Imported inside the accessors rather than at module scope so this module
    stays importable with LiteLLM absent, and so importing it does not drag
    LiteLLM's own import cost into anything that merely wanted the dataclasses.

    Returns:
        The `litellm` module, or None when it cannot be imported.
    """
    global _import_failed
    try:
        import litellm
    except Exception:
        if not _import_failed:
            _import_failed = True
            # No secret is in scope here, so the full traceback is wanted: an
            # import failure of a pinned dependency is a deployment fault and
            # the stack says which sub-import broke.
            logger.exception("LiteLLM is not importable, the model catalogue is empty")
        return None
    return litellm


def _build() -> None:
    """Build the derived structures once, then leave them alone.

    Assigns each finished structure in one statement so a concurrent reader sees
    either the previous value or a complete new one, never a half-filled dict.
    See the note on the module-level cache for why there is no lock.

    Order matters within the build: `_entries` and `_provider_ids` are published
    before the per-provider lists, because :func:`_candidates` reads both while
    enriching. `_models` and `_providers` are published last, and they are what
    the guard above tests, so no reader can enter on a half-built catalogue.
    """
    global _providers, _models, _entries, _provider_ids
    if _providers is not None and _models is not None:
        return

    litellm = _litellm()
    if litellm is None:
        _entries = MappingProxyType({})
        _provider_ids = frozenset()
        _models = MappingProxyType({})
        _providers = ()
        return

    # Before anything is read: LiteLLM's registry omits several models the
    # ChatGPT subscription actually serves, and an unregistered one is routed
    # to the wrong endpoint rather than merely going unlisted. See
    # services/agent/chatgpt_models.py.
    chatgpt_models.register(litellm)

    entries = _read_cost_entries(litellm)
    _entries = entries
    _provider_ids = _read_provider_ids(litellm, entries)

    by_provider = _read_models_by_provider(litellm, entries)
    _models = by_provider
    _providers = _read_providers(litellm, by_provider)


def _read_provider_ids(litellm: Any, entries: Mapping[str, Mapping[str, Any]]) -> frozenset[str]:
    """Collect every provider id LiteLLM mentions, in any of its three lists.

    The union rather than any one list, because each is incomplete on its own:
    a provider can price models without listing them (`models_by_provider` has
    96 of the 152), and a provider can be chat-capable with no priced models at
    all. This set is only used to decide whether a slash in a model id is a
    provider prefix worth stripping, so being generous is the safe direction.

    Args:
        litellm: The imported module.
        entries: The snapshot from :func:`_read_cost_entries`.

    Returns:
        Every provider id, trimmed, with blanks removed.
    """
    found: set[str] = set()
    for source in ("models_by_provider", "LITELLM_CHAT_PROVIDERS", "provider_list"):
        raw = getattr(litellm, source, None)
        if isinstance(raw, Mapping):
            raw = list(raw)
        if isinstance(raw, list | tuple | set | frozenset):
            found.update(_clean(item) for item in raw)
    found.update(_clean(entry.get("litellm_provider")) for entry in entries.values())
    found.discard("")
    return frozenset(found)


def _read_cost_entries(litellm: Any) -> Mapping[str, Mapping[str, Any]]:
    """Snapshot `litellm.model_cost`, dropping what is not a model.

    Args:
        litellm: The imported module.

    Returns:
        An immutable mapping of cost key to entry. The documentation
        placeholder and any non-dict value are excluded, because the
        placeholder's `mode` and `max_input_tokens` are prose and would flow
        straight into the picker as a model called `sample_spec`.
    """
    raw = getattr(litellm, "model_cost", None)
    if not isinstance(raw, Mapping):
        logger.warning("litellm.model_cost is not a mapping, model metadata is unavailable")
        return MappingProxyType({})

    kept: dict[str, Mapping[str, Any]] = {}
    for key, entry in raw.items():
        name = _clean(key)
        if not name or name in PLACEHOLDER_MODELS:
            continue
        if isinstance(entry, Mapping):
            kept[name] = entry
    return MappingProxyType(kept)


def _read_models_by_provider(
    litellm: Any, entries: Mapping[str, Mapping[str, Any]]
) -> Mapping[str, tuple[ModelInfo, ...]]:
    """Build the per-provider model lists, enriched from the cost entries.

    Args:
        litellm: The imported module.
        entries: The snapshot from :func:`_read_cost_entries`.

    Returns:
        An immutable mapping of provider id to its models, in LiteLLM's own
        order, which puts nothing in particular first but is at least stable
        across reads.
    """
    raw = getattr(litellm, "models_by_provider", None)
    if not isinstance(raw, Mapping):
        logger.warning("litellm.models_by_provider is not a mapping, no models are listed")
        return MappingProxyType({})

    built: dict[str, tuple[ModelInfo, ...]] = {}
    for provider, names in raw.items():
        pid = _clean(provider)
        if not pid or not isinstance(names, list | tuple | set | frozenset):
            continue
        models: list[ModelInfo] = []
        seen: set[str] = set()
        for raw_name in names:
            name = _clean(raw_name)
            if not name or name in seen or name in PLACEHOLDER_MODELS:
                continue
            seen.add(name)
            key, entry = _lookup(entries, _candidates(name, pid), pid)
            models.append(_model_info(name, pid, key, entry))
        built[pid] = tuple(models)
    return MappingProxyType(built)


def _read_providers(
    litellm: Any, by_provider: Mapping[str, tuple[ModelInfo, ...]]
) -> tuple[ProviderInfo, ...]:
    """Build the provider grid from `litellm.LITELLM_CHAT_PROVIDERS`.

    Args:
        litellm: The imported module.
        by_provider: The per-provider model lists.

    Returns:
        The providers sorted by display name, case-insensitively, with
        duplicates collapsed.
    """
    raw = getattr(litellm, "LITELLM_CHAT_PROVIDERS", None)
    if not isinstance(raw, list | tuple | set | frozenset):
        logger.warning("litellm.LITELLM_CHAT_PROVIDERS is not a sequence, no providers are listed")
        return ()

    built: dict[str, ProviderInfo] = {}
    for raw_id in raw:
        pid = _clean(raw_id)
        if not pid or pid in built:
            continue
        models = by_provider.get(pid, ())
        display_name, icon = _BRANDS.get(pid, (pid, ""))
        built[pid] = ProviderInfo(
            id=pid,
            display_name=display_name,
            icon=icon,
            provider_kind=_provider_kind(pid),
            needs_key=pid not in _KEYLESS_PROVIDERS,
            needs_base_url=pid in _BASE_URL_PROVIDERS,
            model_count=sum(1 for model in models if model.is_chat),
            total_model_count=len(models),
        )
    return tuple(sorted(built.values(), key=lambda info: info.display_name.casefold()))


def _provider_kind(provider: str) -> str:
    """Suggest the `provider_kind` to store for a provider's models.

    A kind outside the closed vocabulary in :mod:`services.agent.providers`
    cannot address a model at all, and a typo in the local map would surface
    only as a provider error mid-stream. Anything unrecognised falls back to
    `litellm`, which addresses every provider LiteLLM supports.

    Args:
        provider: A LiteLLM provider id.

    Returns:
        A value from `providers.PROVIDER_KINDS`.
    """
    kind = _PROVIDER_KINDS.get(provider, DEFAULT_PROVIDER_KIND)
    if kind not in PROVIDER_KINDS:
        logger.warning(
            "Provider %s maps to unknown provider kind %s, falling back to %s",
            provider,
            kind,
            DEFAULT_PROVIDER_KIND,
        )
        return DEFAULT_PROVIDER_KIND
    return kind


def _model_info(
    name: str,
    provider: str,
    key: str | None,
    entry: Mapping[str, Any] | None,
) -> ModelInfo:
    """Assemble one :class:`ModelInfo` from a name and its cost entry.

    Args:
        name: The model name as LiteLLM lists it.
        provider: The provider id the model was listed under.
        key: The `model_cost` key the entry came from, or None.
        entry: The cost entry, or None when the model is not priced.

    Returns:
        A fully populated :class:`ModelInfo`. Every enriched field is None when
        `entry` is None or does not carry that field.
    """
    fields = entry or {}
    return ModelInfo(
        id=name,
        provider=provider,
        qualified_id=_qualify(name, provider),
        catalog_key=key,
        mode=_clean(fields.get("mode")) or None,
        max_input_tokens=_as_int(fields.get("max_input_tokens"))
        or _as_int(fields.get("max_tokens")),
        max_output_tokens=_as_int(fields.get("max_output_tokens")),
        input_price_per_million=_per_million(fields.get("input_cost_per_token")),
        output_price_per_million=_per_million(fields.get("output_cost_per_token")),
        supports_function_calling=_as_bool(fields.get("supports_function_calling")),
        supports_vision=_as_bool(fields.get("supports_vision")),
        supports_reasoning=_as_bool(fields.get("supports_reasoning")),
    )


def _resolve_entry(name: str, provider: str | None) -> tuple[str | None, Mapping[str, Any] | None]:
    """Find the cost entry for a model name, with or without a known provider.

    Args:
        name: The model name or prefixed model id, already trimmed.
        provider: The provider id, or None to infer one from a prefix on `name`.

    Returns:
        The matching key and entry, or `(None, None)`.
    """
    owner = provider or _prefix_of(name)
    return _lookup(_entries or {}, _candidates(name, provider), owner)


def _candidates(name: str, provider: str | None) -> tuple[str, ...]:
    """Build the `model_cost` keys worth trying for a model name.

    The provider-qualified form comes first so a name that several providers
    share resolves to the right price. `gpt-4o` under `azure` must find
    `azure/gpt-4o`, not the bare OpenAI entry that costs something different.

    Args:
        name: The model name or prefixed model id.
        provider: The provider id, when known.

    Returns:
        Candidate keys in preference order, without duplicates.
    """
    ordered: list[str] = []
    if provider:
        ordered.append(f"{provider}/{name}")
        if name.startswith(f"{provider}/"):
            ordered.append(name)
            ordered.append(name[len(provider) + 1 :])
    ordered.append(name)

    # A prefixed id from `providers.litellm_model_id`, for example
    # `openai/gpt-4o`, is priced under the bare name. Strip the prefix only when
    # it names a real provider, so a model whose name simply contains a slash
    # (`low/1024-x-1536/gpt-image-1.5`) is left alone.
    head, sep, tail = name.partition("/")
    if sep and tail and head in (_provider_ids or frozenset()):
        ordered.append(tail)

    unique: list[str] = []
    for key in ordered:
        if key and key not in unique:
            unique.append(key)
    return tuple(unique)


def _lookup(
    entries: Mapping[str, Mapping[str, Any]],
    candidates: tuple[str, ...],
    provider: str | None,
) -> tuple[str | None, Mapping[str, Any] | None]:
    """Pick the best cost entry among candidate keys.

    Two passes. The first accepts only an entry whose `litellm_provider` matches
    the provider being asked about, which is what stops an Azure deployment
    picking up OpenAI's price through a shared bare name. The second accepts any
    hit, so a provider LiteLLM prices under a different id still resolves.

    Args:
        entries: The cost entry snapshot.
        candidates: Keys in preference order.
        provider: The provider id, when known.

    Returns:
        The chosen key and entry, or `(None, None)`.
    """
    if provider:
        for key in candidates:
            entry = entries.get(key)
            if entry is not None and _clean(entry.get("litellm_provider")) == provider:
                return key, entry
    for key in candidates:
        entry = entries.get(key)
        if entry is not None:
            return key, entry
    return None, None


def _qualify(name: str, provider: str) -> str:
    """Prefix a model name with its provider unless it already carries one.

    Args:
        name: The model name as LiteLLM lists it.
        provider: The provider id.

    Returns:
        The provider-qualified model id, which is what a `litellm` kind row
        stores as its `model_name`.
    """
    if not provider or name.startswith(f"{provider}/"):
        return name
    return f"{provider}/{name}"


def _prefix_of(name: str) -> str:
    """Read the provider prefix off a model id, when it carries a real one.

    Args:
        name: The model name or prefixed model id.

    Returns:
        The provider id, or an empty string when the name carries no prefix that
        names a provider LiteLLM knows.
    """
    head, sep, tail = name.partition("/")
    if sep and tail and head in (_provider_ids or frozenset()):
        return head
    return ""


def _per_million(raw: Any) -> float | None:
    """Convert a per-token price into a rounded per-million-token price.

    Args:
        raw: The `input_cost_per_token` or `output_cost_per_token` value.

    Returns:
        USD per million tokens, or None when the value is missing or is not a
        number. Rounded for display only; :func:`estimate_cost` uses the raw
        per-token figure.
    """
    value = _as_float(raw)
    if value is None:
        return None
    return round(value * TOKENS_PER_MILLION, PRICE_DECIMALS)


def _tokens(raw: Any) -> int | None:
    """Coerce a token count, clamping a negative one to zero.

    Args:
        raw: A token count from a usage payload.

    Returns:
        The count, or None when it is not a number at all. None is a refusal to
        cost the turn rather than a zero, because a broken count silently priced
        as zero is worse than no price.
    """
    if isinstance(raw, bool):
        return None
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return None


def _as_float(raw: Any) -> float | None:
    """Coerce a cost field to a float.

    Args:
        raw: A value from a cost entry, which is normally a float but is prose
            in the placeholder entry and could be a string in a future release.

    Returns:
        The float, or None when the value is missing or not numeric.
    """
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _as_int(raw: Any) -> int | None:
    """Coerce a token-limit field to a positive int.

    Args:
        raw: A value from a cost entry.

    Returns:
        The int, or None when the value is missing, not numeric, or not
        positive. A zero or negative limit is meaningless and would render as a
        context window of zero.
    """
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _as_bool(raw: Any) -> bool | None:
    """Coerce a capability flag, keeping "unknown" distinct from "no".

    Args:
        raw: A value from a cost entry.

    Returns:
        True or False when the field is present and boolean-like, None when it
        is absent. The distinction matters for `supports_function_calling`:
        False is a fact about the model, None is a gap in the catalogue, and the
        picker says something different for each.
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        text = raw.strip().casefold()
        if text in {"true", "yes", "1"}:
            return True
        if text in {"false", "no", "0"}:
            return False
        return None
    if isinstance(raw, (int, float)):
        return bool(raw)
    return None


def _clean(raw: Any) -> str:
    """Trim a value that should be an identifier string.

    Args:
        raw: A provider id, model name or cost key from LiteLLM's data.

    Returns:
        The trimmed string, or an empty string when the value is not a string.
    """
    return raw.strip() if isinstance(raw, str) else ""
