"""A failed agent run reaches the trader as a sentence, not as the provider's error.

The chat used to show a provider failure exactly as LiteLLM raised it:

    litellm.AuthenticationError: AuthenticationError: OpenAIException - {
      "error": {"message": "Incorrect API key provided: sk-proj-****...", ...},
      "status": 401 }

A trader cannot act on an exception class, a JSON body, an HTTP status or a key
fragment. These tests pin the sentence each kind of failure produces, that none
of the provider's technical detail reaches the browser, and that a failure this
platform already described for the trader keeps its own words.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.agent import stream as agent_stream
from services.agent.error_messages import INTERNAL_MESSAGE, provider_label, trader_message
from services.agent.frames import Done, Error, ErrorKind

# The failure a trader reported, with the key fragment replaced.
OPENAI_BAD_KEY = (
    "litellm.AuthenticationError: AuthenticationError: OpenAIException - {\n"
    '  "error": {\n'
    '    "message": "Incorrect API key provided: sk-proj-****************abcd. '
    'You can find your API key at https://platform.openai.com/account/api-keys.",\n'
    '    "type": "invalid_request_error",\n'
    '    "code": "invalid_api_key",\n'
    '    "param": null\n'
    "  },\n"
    '  "status": 401\n'
    "}"
)

TECHNICAL_FRAGMENTS = (
    "sk-",
    "401",
    "litellm",
    "Exception",
    "http",
    "{",
    "invalid_api_key",
    "Error:",
)


def _assert_trader_readable(message: str) -> None:
    for fragment in TECHNICAL_FRAGMENTS:
        assert fragment not in message, f"{fragment!r} reached the trader: {message}"


def _provider(names, text, **kwargs):
    return trader_message(ErrorKind.PROVIDER, names, text, **kwargs)


class TestSentences:
    def test_the_reported_openai_key_failure(self):
        message = _provider(["ModelProviderError"], OPENAI_BAD_KEY)
        assert (
            message
            == "OpenAI did not accept the API key for this model. Enter a valid key in agent settings."
        )
        _assert_trader_readable(message)

    def test_an_exhausted_openai_balance_reported_as_a_rate_limit(self):
        text = (
            "litellm.RateLimitError: RateLimitError: OpenAIException - You exceeded your current "
            "quota, please check your plan and billing details. insufficient_quota"
        )
        message = _provider(["RateLimitError"], text)
        assert (
            message
            == "Your OpenAI account has no credits left. Add credits under billing, then try again."
        )

    def test_an_exhausted_anthropic_balance(self):
        text = "litellm.BadRequestError: AnthropicException - Your credit balance is too low to access the API."
        message = _provider(["BadRequestError"], text)
        assert message.startswith("Your Anthropic account has no credits left.")

    def test_a_real_rate_limit(self):
        message = _provider(
            ["RateLimitError"], "GroqException - Rate limit reached for requests", provider="groq"
        )
        assert message == "Groq is limiting requests right now. Wait a minute, then try again."

    def test_an_unknown_model(self):
        text = "OpenAIException - The model `gpt-9` does not exist or you do not have access to it."
        message = _provider(["NotFoundError"], text)
        assert (
            message
            == "OpenAI does not offer the model chosen in agent settings. Choose another model there."
        )

    def test_an_over_long_conversation(self):
        text = "OpenAIException - This model's maximum context length is 128000 tokens."
        message = _provider(["BadRequestError"], text)
        assert message.startswith("This conversation has grown too long for the model.")

    def test_a_provider_that_cannot_be_reached(self):
        message = _provider(["APIConnectionError"], "Connection error.", provider="anthropic")
        assert (
            message
            == "OpenAlgo could not reach Anthropic. Check that the server is online, then try again."
        )

    def test_an_overloaded_provider(self):
        message = _provider(
            ["ModelProviderError"], 'AnthropicException - {"type": "overloaded_error"}'
        )
        assert message == "Anthropic is having trouble right now. Try again in a few minutes."

    def test_a_timeout(self):
        message = _provider(["Timeout"], "Request timed out.", provider="gemini")
        assert message == "Google Gemini took too long to answer. Try again."

    def test_the_status_code_decides_when_nothing_else_does(self):
        message = _provider(
            ["ModelProviderError"], "Error code: 503 - upstream said nothing useful"
        )
        assert message == "The AI provider is having trouble right now. Try again in a few minutes."

    def test_an_unidentified_failure_does_not_guess_a_cause(self):
        message = _provider(["ModelProviderError"], "something odd happened")
        assert message == (
            "The AI provider could not complete this request. Try again, or check the model in agent settings."
        )

    def test_an_unsupported_feature_is_not_reported_as_an_unknown_model(self):
        # "is not supported" alone must not pick the unknown-model sentence: this
        # model exists, it just takes no images, and "choose another model" is
        # only right by accident.
        message = _provider(["BadRequestError"], "OpenAIException - image input is not supported")
        assert "does not offer the model" not in message


class TestChatGptPlan:
    def test_an_expired_sign_in(self):
        message = _provider(
            ["AuthenticationError"], "ChatgptException - token expired", provider="chatgpt"
        )
        assert message == (
            "Your ChatGPT sign-in has expired or was removed. Sign in to ChatGPT again from agent settings."
        )

    def test_a_model_the_plan_does_not_serve(self):
        text = "ChatgptException - The 'gpt-5.6' model is not supported when using Codex with a ChatGPT account."
        message = _provider(["BadRequestError"], text, provider="chatgpt")
        assert (
            message
            == "ChatGPT could not run the model chosen in agent settings. Choose another model there."
        )


class TestKinds:
    def test_an_internal_failure_points_to_the_log(self):
        message = trader_message(ErrorKind.INTERNAL, ["KeyError"], "KeyError: 'frames'")
        assert message == INTERNAL_MESSAGE
        _assert_trader_readable(message)

    @pytest.mark.parametrize("kind", [ErrorKind.TOOL, ErrorKind.INPUT, ErrorKind.CONFIG])
    def test_text_this_platform_wrote_is_kept(self, kind):
        assert trader_message(kind, ["AgentRunException"], "No quote for NIFTY right now.") is None

    def test_provider_names(self):
        assert provider_label("VertexAIException - quota") == "Google Vertex AI"
        assert provider_label("", "openrouter") == "OpenRouter"
        assert provider_label("nothing to go on") is None


class TestTheWire:
    """The sentence is what the translator puts in the `error` frame."""

    def test_a_run_error_event(self):
        translator = agent_stream.EventTranslator(1)
        event = SimpleNamespace(
            event="RunError", run_id="r1", error_type="ModelProviderError", content=OPENAI_BAD_KEY
        )
        errors = [frame for frame in translator.translate(event) if isinstance(frame, Error)]
        assert len(errors) == 1
        assert errors[0].kind == ErrorKind.PROVIDER
        assert errors[0].message.startswith("OpenAI did not accept the API key")
        _assert_trader_readable(errors[0].message)

    def test_an_exception_from_the_run(self):
        class AuthenticationError(Exception):
            llm_provider = "openai"
            status_code = 401

        translator = agent_stream.EventTranslator(1)
        frames = translator.fail(AuthenticationError(OPENAI_BAD_KEY))
        assert isinstance(frames[0], Error) and isinstance(frames[1], Done)
        assert frames[0].message.startswith("OpenAI did not accept the API key")
        _assert_trader_readable(frames[0].message)

    def test_a_wrapped_litellm_failure_is_read_through_its_cause(self):
        class RateLimitError(Exception):
            llm_provider = "anthropic"
            status_code = 429

        class ModelProviderError(Exception):
            status_code = 502  # agno's default when the provider sent no status

        try:
            try:
                raise RateLimitError("AnthropicException - rate limited")
            except RateLimitError as cause:
                raise ModelProviderError("rate limited") from cause
        except ModelProviderError as wrapped:
            frames = agent_stream.EventTranslator(1).fail(wrapped)
        assert (
            frames[0].message
            == "Anthropic is limiting requests right now. Wait a minute, then try again."
        )
