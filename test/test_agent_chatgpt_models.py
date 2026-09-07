"""The supplement that teaches LiteLLM about plan models it does not list.

The defect these pin is subtle and was live: the first version of `register`
asked whether the bare name was in `model_cost`, which is True for every one of
these because OpenAI prices the same model on the API path. It therefore
concluded LiteLLM already knew them and added nothing, silently, while the
catalogue kept showing ten models and a run kept getting a Cloudflare page.

`test_an_openai_entry_for_the_same_name_does_not_block_registration` is that
defect, and it fails on the guard that caused it.
"""

from types import SimpleNamespace

from services.agent import chatgpt_models


def _litellm(cost=None, by_provider=None):
    """A stand-in carrying only the two mappings `register` writes."""
    return SimpleNamespace(
        model_cost=dict(cost or {}),
        models_by_provider=dict(by_provider or {"chatgpt": ["chatgpt/gpt-5.4"]}),
    )


class TestTheModelsAreAdded:
    def test_every_supplemental_model_is_registered(self):
        fake = _litellm()
        added = chatgpt_models.register(fake)

        assert set(added) == {f"chatgpt/{name}" for name in chatgpt_models.SUPPLEMENTAL}
        for name in chatgpt_models.SUPPLEMENTAL:
            assert f"chatgpt/{name}" in fake.model_cost
            assert f"chatgpt/{name}" in fake.models_by_provider["chatgpt"]

    def test_the_provider_keeps_the_models_litellm_already_listed(self):
        fake = _litellm()
        chatgpt_models.register(fake)

        assert "chatgpt/gpt-5.4" in fake.models_by_provider["chatgpt"]

    def test_registering_twice_adds_nothing_the_second_time(self):
        fake = _litellm()
        first = chatgpt_models.register(fake)
        listed = list(fake.models_by_provider["chatgpt"])

        second = chatgpt_models.register(fake)

        assert first and second == ()
        assert fake.models_by_provider["chatgpt"] == listed


class TestTheBareNameCollision:
    """PINNED DEFECT. Eight plan models share a name with an OpenAI model."""

    def test_an_openai_entry_for_the_same_name_does_not_block_registration(self):
        # Exactly the real registry: the bare name is present, priced, and
        # belongs to a different provider.
        fake = _litellm(
            cost={
                "gpt-5.6-sol": {
                    "litellm_provider": "openai",
                    "input_cost_per_token": 2.5e-06,
                }
            }
        )

        added = chatgpt_models.register(fake)

        assert "chatgpt/gpt-5.6-sol" in added
        assert fake.model_cost["chatgpt/gpt-5.6-sol"]["litellm_provider"] == "chatgpt"

    def test_the_openai_entry_is_left_exactly_as_it_was(self):
        openai_entry = {"litellm_provider": "openai", "input_cost_per_token": 2.5e-06}
        fake = _litellm(cost={"gpt-5.6-sol": dict(openai_entry)})

        chatgpt_models.register(fake)

        assert fake.model_cost["gpt-5.6-sol"] == openai_entry


class TestLitellmsOwnEntryWins:
    def test_a_real_chatgpt_entry_is_never_overwritten(self):
        shipped = {"litellm_provider": "chatgpt", "mode": "responses", "shipped": True}
        fake = _litellm(cost={"chatgpt/gpt-5.5": dict(shipped)})

        added = chatgpt_models.register(fake)

        assert "chatgpt/gpt-5.5" not in added
        assert fake.model_cost["chatgpt/gpt-5.5"] == shipped


class TestTheEntriesThemselves:
    def test_no_entry_carries_a_price(self):
        # A plan turn has no per-token cost. A price here would make
        # catalog.estimate_cost answer, and the usage badge would report a
        # number for usage that was never billed that way.
        for name in chatgpt_models.SUPPLEMENTAL:
            keys = chatgpt_models.entry(name)
            assert not [k for k in keys if "cost" in k], name

    def test_every_entry_declares_the_responses_mode(self):
        # The load-bearing field: without it LiteLLM routes the model to the
        # chat-completions bridge, which returns a Cloudflare page.
        for name in chatgpt_models.SUPPLEMENTAL:
            assert chatgpt_models.entry(name)["mode"] == "responses"
            assert chatgpt_models.entry(name)["litellm_provider"] == "chatgpt"

    def test_the_caller_cannot_reach_module_state(self):
        chatgpt_models.entry("gpt-5.5")["mode"] = "mutated"

        assert chatgpt_models.entry("gpt-5.5")["mode"] == "responses"

    def test_the_refused_models_are_not_offered(self):
        # Measured against a real subscription: these are rejected by the
        # backend by name. gpt-5.6 being refused while three of its variants
        # work is why the list is enumerated, not derived.
        for refused in ("gpt-5.6", "gpt-5.6-cyber", "gpt-5.5-pro", "gpt-5.6-codex"):
            assert refused not in chatgpt_models.SUPPLEMENTAL


class TestItFailsQuietly:
    def test_a_registry_of_the_wrong_shape_is_not_fatal(self):
        assert chatgpt_models.register(SimpleNamespace(model_cost=[], models_by_provider={})) == ()

    def test_a_litellm_without_the_maps_is_not_fatal(self):
        assert chatgpt_models.register(SimpleNamespace()) == ()

    def test_a_provider_listed_as_something_uniterable_still_registers(self):
        fake = _litellm(by_provider={"chatgpt": None})

        added = chatgpt_models.register(fake)

        assert len(added) == len(chatgpt_models.SUPPLEMENTAL)
