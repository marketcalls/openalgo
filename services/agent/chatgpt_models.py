"""Models the ChatGPT subscription serves that LiteLLM does not yet list.

LiteLLM's registry carries ten `chatgpt/*` entries, the newest `gpt-5.4`. The
Codex backend behind a ChatGPT plan serves more than that, and the omission is
not cosmetic: a model absent from the registry has no `mode`, so LiteLLM routes
it through the chat-completions bridge instead of `/v1/responses`. That request
never reaches the API at all. It lands on a Cloudflare interstitial and comes
back as `403 Enable JavaScript and cookies to continue`, which reads like an
account or network problem and is neither.

Registering the entry is the whole fix. With `mode: responses` present the same
model answers normally.

**Measured, not assumed.** Every name here was run against a real subscription
and returned content; every name rejected was rejected by the backend in its own
words, `The '<model>' model is not supported when using Codex with a ChatGPT
account`:

    available    gpt-5.5, gpt-5.6-sol, gpt-5.6-luna, gpt-5.6-terra
    refused      gpt-5.6, gpt-5.6-cyber, gpt-5.5-pro, gpt-5.5-codex, gpt-5.6-codex

`gpt-5.6` being refused while three of its variants work is genuinely how the
backend behaves, so the list is enumerated rather than derived from a pattern.

**A plan is not an entitlement.** These are the models the *provider* serves;
which of them a given plan may use is between the operator and OpenAI, and a
Plus plan need not match a Pro one. That is why nothing here promises
availability: the catalogue is advisory, and the model test on the config page
is what answers for a particular account.

**No prices, deliberately.** The entries carry capability and context metadata
and no cost keys, so `catalog.estimate_cost` keeps returning None and a plan
turn is reported as subscription usage rather than as costing zero. See
`chatgpt_oauth.apply_billing`.

This module exists to be deleted. When LiteLLM ships these names, its own entry
wins and this one is skipped, so the only cost of the overlap is this file.
"""

from typing import Any

from utils.logging import get_logger

logger = get_logger(__name__)

PROVIDER = "chatgpt"

#: Shared by every entry. `mode` is the load-bearing one: without it the model
#: is routed to chat completions and never reaches the responses endpoint.
_BASE: dict[str, Any] = {
    "litellm_provider": PROVIDER,
    "mode": "responses",
    "supported_endpoints": ["/v1/chat/completions", "/v1/responses"],
    "supports_function_calling": True,
    "supports_parallel_function_calling": True,
    "supports_response_schema": True,
    "supports_reasoning": True,
    "supports_vision": True,
    "max_output_tokens": 128000,
}

#: Bare model name -> the fields that differ from `_BASE`. Context windows are
#: the ones LiteLLM records for the same model on the API path, because it is
#: the same model reached by a different route.
SUPPLEMENTAL: dict[str, dict[str, Any]] = {
    "gpt-5.5": {"max_input_tokens": 1050000},
    "gpt-5.6-sol": {"max_input_tokens": 922000},
    "gpt-5.6-luna": {"max_input_tokens": 922000},
    "gpt-5.6-terra": {"max_input_tokens": 922000},
}


def entry(name: str) -> dict[str, Any]:
    """Build the registry entry for one supplemental model.

    Args:
        name: The bare model name, for example `gpt-5.6-sol`.

    Returns:
        A fresh dict, so a caller mutating it cannot reach this module's state.
    """
    return {**_BASE, **SUPPLEMENTAL.get(name, {})}


def _has_chatgpt_entry(cost: Any, key: str) -> bool:
    """Whether LiteLLM already prices this key *as a ChatGPT model*.

    Args:
        cost: LiteLLM's `model_cost` mapping.
        key: A prefixed id or a bare model name.

    Returns:
        True only when the entry exists and names this provider. A bare name
        matching OpenAI's own model is not this provider's entry.
    """
    existing = cost.get(key)
    return isinstance(existing, dict) and existing.get("litellm_provider") == PROVIDER


def register(litellm: Any) -> tuple[str, ...]:
    """Add the missing models to LiteLLM's registry, in place.

    Idempotent, and safe to call on every catalogue build and before every run.

    **An entry LiteLLM already has is never touched.** When a future release
    ships these names, its metadata and its prices win, and this module quietly
    stops contributing. Overwriting would replace a priced, maintained entry
    with an unpriced guess.

    Both maps are written because they answer different questions and neither
    derives the other: `model_cost` is what `mode` and the capability
    predicates are read from, and `models_by_provider` is what enumerates a
    provider for the config page.

    Args:
        litellm: The imported LiteLLM module. Passed in rather than imported so
            this module stays importable without it, and so a caller that has
            already paid the multi-second import does not pay it twice.

    Returns:
        The prefixed ids this call added, empty when there was nothing to do.
    """
    added: list[str] = []
    try:
        cost = litellm.model_cost
        by_provider = litellm.models_by_provider
        if not isinstance(cost, dict) or not isinstance(by_provider, dict):
            return ()

        known = by_provider.get(PROVIDER)
        listed = list(known) if isinstance(known, (list, tuple, set)) else []

        for name in SUPPLEMENTAL:
            model_id = f"{PROVIDER}/{name}"
            # LiteLLM's own entry wins, but only a *chatgpt* one counts. The
            # bare name is already in the map as OpenAI's API model: eight of
            # these names exist on both paths, which is the whole reason this
            # provider is confusing, and testing for the bare key alone made
            # this function skip every model it exists to add.
            if _has_chatgpt_entry(cost, model_id) or _has_chatgpt_entry(cost, name):
                continue
            cost[model_id] = entry(name)
            if model_id not in listed:
                listed.append(model_id)
            added.append(model_id)

        if added:
            by_provider[PROVIDER] = listed
            logger.info(
                "Registered %d ChatGPT subscription models LiteLLM does not list: %s",
                len(added),
                ", ".join(added),
            )
    except Exception:
        # Advisory, never fatal. A LiteLLM whose registry has a different shape
        # costs the operator these four models, not a working agent.
        logger.exception("Could not register the supplemental ChatGPT models")
        return ()

    return tuple(added)
