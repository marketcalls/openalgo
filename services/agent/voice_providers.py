"""Speech provider vocabulary for the voice surface.

The same shape as :mod:`services.agent.providers`, and for the same reason: the
intelligence side of this module long ago stopped hardcoding one vendor, and the
speech side should not acquire the habit now that it is the only one left.

Today there is exactly one entry. That is a fact about the market, not a
constraint in the code: OpenAI's `gpt-live` is currently the only speech model
that will answer over WebRTC while letting the application supply every answer
itself, which is what client delegation means and what keeps the trading
intelligence on whatever LiteLLM provider the operator chose.

Two kinds of change are expected, and neither should require touching anything
outside this file.

**A newer model from a provider already here.** `gpt-live-1` will be superseded.
Add the name to :attr:`VoiceProviderSpec.known_models`, which is only the
picker's list: :data:`services.agent.settings.KEY_VOICE_MODEL` is free text, so
an operator can type a model the day it ships and run it without an upgrade.
Nothing validates a model name against this tuple, deliberately - a list that
refuses an unreleased model is worse than one that is merely out of date.

**A new provider.** Add a :class:`VoiceProviderSpec`. What varies between
plausible candidates is small and is all here: where a session is minted, which
secret authenticates it, which voices it offers, and the body shape that tells
it not to think for itself. What does not vary is everything above this module -
the surface, the toolkits, the risk guard and the audit trail are unchanged by
who is listening.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

__all__ = [
    "DEFAULT_VOICE_PROVIDER",
    "VOICE_PROVIDERS",
    "VoiceProviderSpec",
    "provider_ids",
    "voice_provider_spec",
]


@dataclass(frozen=True)
class VoiceProviderSpec:
    """One speech provider.

    Attributes:
        id: The stored value of ``voice_provider``.
        label: What an operator sees.
        sessions_url: Where a session is minted. A module constant per provider
            and never taken from a request, which is what keeps the mint route
            off the SSRF surface.
        secret_name: The ``ag_secret`` row holding this provider's key. Separate
            per provider so an operator can hold keys for more than one without
            them overwriting each other.
        default_model: What a fresh install uses.
        known_models: Models offered in the picker. Advisory only - the setting
            is free text so a model released after this list was written still
            works.
        speakers: Voices offered in the picker, same advisory status.
        delegation: The body fragment that puts the provider in the mode where
            it performs no reasoning of its own.
    """

    id: str
    label: str
    sessions_url: str
    secret_name: str
    default_model: str
    known_models: tuple[str, ...]
    speakers: tuple[str, ...]
    delegation: Mapping[str, Any] = field(default_factory=dict)


#: Every provider the voice surface can speak through.
VOICE_PROVIDERS: Mapping[str, VoiceProviderSpec] = MappingProxyType(
    {
        "openai": VoiceProviderSpec(
            id="openai",
            label="OpenAI",
            sessions_url="https://api.openai.com/v1/live/sessions",
            secret_name="voice:openai",
            default_model="gpt-live-1",
            # gpt-live-1 is the current generation. A successor is added here
            # when it ships; until then an operator can simply type its name.
            known_models=("gpt-live-1",),
            speakers=("marin", "cedar", "alloy", "echo", "shimmer"),
            # Client delegation: the speech model answers nothing on its own and
            # raises session.delegation.created instead, which is the whole
            # reason this provider can be used without surrendering the brain.
            delegation=MappingProxyType({"type": "client"}),
        ),
    }
)

DEFAULT_VOICE_PROVIDER = "openai"


def provider_ids() -> tuple[str, ...]:
    """Every configured provider id, in declaration order.

    Returns:
        The ids, for a settings screen to offer.
    """
    return tuple(VOICE_PROVIDERS)


def voice_provider_spec(provider: Any) -> VoiceProviderSpec:
    """Look up one provider.

    Args:
        provider: The provider id, in any casing.

    Returns:
        Its :class:`VoiceProviderSpec`.

    Raises:
        ValueError: For an unknown id. The message names what is accepted,
            because the only person who sees it is an operator who has typed
            something this build does not carry.
    """
    key = str(provider or "").strip().lower()
    spec = VOICE_PROVIDERS.get(key)
    if spec is None:
        accepted = ", ".join(VOICE_PROVIDERS)
        raise ValueError(f"Unknown voice provider {key!r}. Accepted: {accepted}")
    return spec
