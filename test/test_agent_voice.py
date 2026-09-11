"""The voice surface: what approves an order, what reaches a spoken run, and what is said.

Four claims are pinned here, because each one is a control rather than a
convenience and the whole design rests on them being true rather than intended.

**Approval is a pure function and it is deliberately hard to satisfy.** The word
that places a trade is also a word a trader says out loud all day, so the matcher
accepts it alone or wrapped in a bare affirmation and rejects it everywhere else.
The first test in that class is the rejection of the word inside a sentence: if
the alone-word rule were dropped to a substring search that test fails, so
nothing below it can pass vacuously.

**Voice widens nothing.** The spoken surface is a narrowing of the chat surface,
never an addition. The selection tests assert the exact toolkit set the design
document names rather than a property of it, so a toolkit that quietly arrives on
voice is a failure here rather than a discovery in production.

**The browser does not get to decide it may trade.** `_trading_capability` reads
`voice_trading_enabled` server side for a spoken run, can only ever remove the
capability, and withholds it when the settings read raises.

**Nothing here touches the network.** The one outbound call the voice surface
makes is stubbed at the HTTP client, and the stub is what the transport-level
assertions are made against. The live mint path was verified separately against a
real key; it is deliberately not in this suite, which must stay runnable with no
credential and no egress.
"""

from __future__ import annotations

from typing import Any

import pytest

import blueprints.agent as agent_bp
from services.agent import settings as agent_settings
from services.agent import voice
from services.agent.safety import voice_confirm as vc
from services.agent.tools import (
    SURFACE_CHART,
    SURFACE_CHAT,
    SURFACE_VOICE,
    ToolContext,
    select_specs,
)

# ---------------------------------------------------------------------------
# Approval
# ---------------------------------------------------------------------------


class TestTheWordAloneApproves:
    """`is_approval` accepts the configured phrase and bare affirmation, nothing else."""

    def test_the_word_inside_a_sentence_is_not_approval(self):
        # This is the rule the whole design rests on: the approval word is also
        # the word a trader addresses the agent with, so a substring search
        # would approve an order every time somebody asked a question. If the
        # alone-word rule were removed these would all become True.
        assert vc.is_approval("milo what is bank nifty", "milo") is False
        assert vc.is_approval("place it milo", "milo") is False
        assert vc.is_approval("milo buy fifty nifty", "milo") is False
        assert vc.is_approval("tell milo yes", "milo") is False

    def test_the_word_alone_approves(self):
        assert vc.is_approval("milo", "milo") is True

    @pytest.mark.parametrize(
        "transcript",
        ["yes milo", "milo confirm", "ok milo", "MILO", "  milo.  ", "milo, confirm.", "yeah milo"],
    )
    def test_a_bare_affirmation_may_accompany_it(self, transcript):
        assert vc.is_approval(transcript, "milo") is True

    @pytest.mark.parametrize("transcript", ["yes", "ok", "confirm", "yes please", "sure"])
    def test_a_bare_affirmation_alone_is_not_approval(self, transcript):
        # "yes" is what a trader says to a colleague. Only the configured phrase
        # approves, which is why every affirmation needs the word beside it.
        assert vc.is_approval(transcript, "milo") is False

    def test_an_empty_or_absent_utterance_approves_nothing(self):
        assert vc.is_approval("", "milo") is False
        assert vc.is_approval(None, "milo") is False
        assert vc.is_approval("...", "milo") is False

    def test_an_utterance_that_has_become_a_sentence_is_refused_on_length(self):
        assert vc.is_approval("yes milo confirm", "milo") is True
        assert vc.is_approval("yes yes milo confirm", "milo") is False

    @pytest.mark.parametrize("phrase", ["", None, "  ", "mi", "milo trade", "milo1", "mi-lo", 7])
    def test_an_unusable_configured_phrase_approves_nothing(self, phrase):
        # A malformed settings row must fail closed. The dangerous direction is
        # a matcher that treats an empty phrase as "anything matches".
        assert vc.is_approval("milo", phrase) is False
        assert vc.is_approval("yes", phrase) is False
        assert vc.is_approval("", phrase) is False

    def test_the_stored_phrase_is_matched_case_insensitively(self):
        assert vc.is_approval("milo", "MILO") is True
        assert vc.is_approval("Milo", "Milo") is True


class TestTheTwoSpokenValuesAreKeptApart:
    """The wake phrase carries no authority, and configuration cannot merge them."""

    def test_an_order_phrase_inside_the_wake_phrase_is_refused(self):
        # Without this an operator could set both to "milo" and every greeting
        # would be an approval.
        with pytest.raises(ValueError, match="must not appear in the wake phrase"):
            vc.normalise_order_phrase("milo", "Hey Milo")
        with pytest.raises(ValueError):
            vc.normalise_order_phrase("MILO", "milo")

    def test_a_phrase_absent_from_the_wake_phrase_is_accepted_and_lowered(self):
        assert vc.normalise_order_phrase("Goldfinch", "Hey Milo") == "goldfinch"

    def test_no_wake_phrase_skips_the_comparison(self):
        assert vc.normalise_order_phrase("milo") == "milo"

    @pytest.mark.parametrize("raw", ["", None, "  ", "mi", "two words", "milo1", "milo!", "a" * 21])
    def test_an_order_phrase_that_could_not_survive_transcription_is_refused(self, raw):
        with pytest.raises(ValueError):
            vc.normalise_order_phrase(raw)

    @pytest.mark.parametrize("raw", ["", None, "   ", "Milo!", "Hey, Milo", "Milo 2", "a" * 41])
    def test_a_wake_phrase_with_punctuation_or_nothing_in_it_is_refused(self, raw):
        with pytest.raises(ValueError):
            vc.normalise_wake_phrase(raw)

    def test_a_wake_phrase_keeps_its_capitalisation_and_loses_its_spacing(self):
        assert vc.normalise_wake_phrase("  Hey   Milo  ") == "Hey Milo"


class TestTheWindow:
    """Open, expired, never opened, and a clock that went backwards."""

    def test_it_is_open_inside_the_configured_window(self):
        assert vc.window_is_open(100.0, 100.0, 30) is True
        assert vc.window_is_open(100.0, 129.9, 30) is True

    def test_the_boundary_is_inclusive_and_the_next_moment_is_not(self):
        assert vc.window_is_open(100.0, 130.0, 30) is True
        assert vc.window_is_open(100.0, 130.1, 30) is False

    def test_no_staged_order_means_no_window(self):
        assert vc.window_is_open(None, 100.0, 30) is False

    def test_a_non_positive_window_is_closed(self):
        assert vc.window_is_open(100.0, 100.0, 0) is False
        assert vc.window_is_open(100.0, 100.0, -30) is False

    def test_a_clock_that_went_backwards_closes_the_window(self):
        # Negative elapsed time must not read as "well inside the window".
        assert vc.window_is_open(100.0, 50.0, 30) is False

    def test_the_two_checks_are_independent(self):
        # Both must pass and they fail for different reasons: a perfect
        # utterance in a closed window approves nothing.
        assert vc.is_approval("milo", "milo") is True
        assert vc.window_is_open(100.0, 200.0, 30) is False


# ---------------------------------------------------------------------------
# Surface filtering
# ---------------------------------------------------------------------------


def keys_for(**kwargs: Any) -> set[str]:
    """The toolkit keys a run with these context values would be offered.

    Args:
        **kwargs: Overrides for :class:`ToolContext`. Web search is switched off
            unless a test says otherwise, so the sets below name only the
            toolkits the surface decides.

    Returns:
        The selected toolkit keys.
    """
    kwargs.setdefault("web_search_enabled", False)
    return {spec.key for spec in select_specs(ToolContext(api_key="k", **kwargs))}


#: The toolkits `docs/design/56-voice-agent/README.md` says reach voice, before
#: any capability is granted. Asserted as an exact set rather than as a property
#: so a toolkit arriving on the spoken surface by accident fails here.
VOICE_READ_ONLY = {
    "market",
    "symbols",
    "indicators",
    "account",
    "options",
    "instrument",
    "live",
    "viz",
    "option_viz",
}


class TestVoiceWidensNothing:
    """The spoken surface is a narrowing of chat, never an addition to it."""

    def test_a_spoken_run_without_trading_gets_no_order_toolkit(self):
        assert keys_for(surface=SURFACE_VOICE, trading_enabled=False) == VOICE_READ_ONLY
        assert "orders" not in keys_for(surface=SURFACE_VOICE, trading_enabled=False)

    def test_a_spoken_run_with_trading_gets_it(self):
        # The capability is the only difference, which is what makes withholding
        # the capability the whole enforcement.
        with_trading = keys_for(surface=SURFACE_VOICE, trading_enabled=True)
        assert with_trading - VOICE_READ_ONLY == {"orders"}

    def test_voice_never_reaches_the_toolkits_that_write_code_or_draw_an_interface(self):
        # None of these can be driven through a speaker, and two of them write
        # files. They are chat only and must stay there.
        spoken = keys_for(surface=SURFACE_VOICE, trading_enabled=True, web_search_enabled=True)
        assert not ({"openui", "strategy_gen", "flow_gen"} & spoken)

    def test_chat_still_gets_them(self):
        # The other half of the claim above: the narrowing removed them from
        # voice without removing them from the surface they belong to.
        chat = keys_for(surface=SURFACE_CHAT)
        assert {"openui", "strategy_gen", "flow_gen"} <= chat

    def test_voice_is_a_subset_of_chat(self):
        for trading in (False, True):
            for search in (False, True):
                spoken = keys_for(
                    surface=SURFACE_VOICE, trading_enabled=trading, web_search_enabled=search
                )
                chat = keys_for(
                    surface=SURFACE_CHAT, trading_enabled=trading, web_search_enabled=search
                )
                assert spoken <= chat

    def test_the_chart_toolkit_stays_chart_only(self):
        # It drives the /trading panel, which a spoken turn is not attached to.
        assert "chart" in keys_for(surface=SURFACE_CHART)
        assert "chart" not in keys_for(surface=SURFACE_VOICE, trading_enabled=True)
        assert "chart" not in keys_for(surface=SURFACE_CHAT)

    def test_the_chart_panel_is_unchanged_by_the_new_surface(self):
        chart = keys_for(surface=SURFACE_CHART, trading_enabled=True)
        assert "orders" not in chart
        assert not ({"openui", "strategy_gen", "flow_gen"} & chart)

    def test_a_context_that_does_not_carry_the_capability_is_refused_it(self):
        class Bare:
            api_key = "k"
            surface = SURFACE_VOICE

        assert "orders" not in {spec.key for spec in select_specs(Bare())}


# ---------------------------------------------------------------------------
# The server-side narrowing
# ---------------------------------------------------------------------------


class TestTheBrowserDoesNotDecideItMayTrade:
    """`_trading_capability` reads the switch server side for a spoken run."""

    def _refuse_to_be_read(self, monkeypatch):
        """Make a settings read fail loudly, to prove one did not happen.

        Args:
            monkeypatch: pytest's monkeypatch fixture.
        """

        def boom():
            raise AssertionError("the voice configuration was read on a surface that owns it")

        monkeypatch.setattr(agent_settings, "get_voice_config", boom)

    def test_voice_trading_off_refuses_a_body_that_asked_for_trading(self, monkeypatch):
        monkeypatch.setattr(
            agent_settings, "get_voice_config", lambda: {"trading_effective": False}
        )
        assert agent_bp._trading_capability({"trading_enabled": True}, SURFACE_VOICE) is False

    def test_voice_trading_on_allows_it(self, monkeypatch):
        monkeypatch.setattr(agent_settings, "get_voice_config", lambda: {"trading_effective": True})
        assert agent_bp._trading_capability({"trading_enabled": True}, SURFACE_VOICE) is True

    def test_it_can_only_ever_remove_the_capability(self, monkeypatch):
        # A run that did not ask for trading does not acquire it by being spoken.
        monkeypatch.setattr(agent_settings, "get_voice_config", lambda: {"trading_effective": True})
        assert agent_bp._trading_capability({"trading_enabled": False}, SURFACE_VOICE) is False
        assert agent_bp._trading_capability({}, SURFACE_VOICE) is False

    def test_the_chat_surface_is_the_body_unchanged(self, monkeypatch):
        # The voice configuration has no say over a typed turn, so reading it
        # here would be wrong: the stub raises if it is touched.
        self._refuse_to_be_read(monkeypatch)
        assert agent_bp._trading_capability({"trading_enabled": True}, SURFACE_CHAT) is True
        assert agent_bp._trading_capability({"trading_enabled": False}, SURFACE_CHAT) is False
        assert agent_bp._trading_capability({"trading_enabled": True}, SURFACE_CHART) is True

    def test_a_spoken_run_that_did_not_ask_reads_nothing(self, monkeypatch):
        self._refuse_to_be_read(monkeypatch)
        assert agent_bp._trading_capability({"trading_enabled": False}, SURFACE_VOICE) is False

    def test_an_unreadable_setting_withholds_the_capability(self, monkeypatch):
        def boom():
            raise RuntimeError("database is locked")

        monkeypatch.setattr(agent_settings, "get_voice_config", boom)
        assert agent_bp._trading_capability({"trading_enabled": True}, SURFACE_VOICE) is False

    def test_a_configuration_missing_the_field_withholds_it_too(self, monkeypatch):
        monkeypatch.setattr(agent_settings, "get_voice_config", lambda: {})
        assert agent_bp._trading_capability({"trading_enabled": True}, SURFACE_VOICE) is False


# ---------------------------------------------------------------------------
# Speaking
# ---------------------------------------------------------------------------


class TestWhatReachesTheDataChannel:
    """`speakable` is the only path to the speaker, so it is the only length guard."""

    def test_markdown_is_stripped_rather_than_read_out(self):
        spoken = voice.speakable("**Bank Nifty** is at `52,000` and _holding_.")
        assert "*" not in spoken
        assert "`" not in spoken
        assert "_" not in spoken
        assert "Bank Nifty" in spoken and "52,000" in spoken

    def test_headings_and_bullets_lose_their_punctuation(self):
        spoken = voice.speakable("# Summary\n- Nifty is up\n- Bank Nifty is flat")
        assert "#" not in spoken
        assert not spoken.lstrip().startswith("-")
        assert "Nifty is up" in spoken

    def test_a_link_is_spoken_as_its_text(self):
        assert voice.speakable("See [the chain](https://example.com/x)") == "See the chain"

    def test_a_table_is_dropped_rather_than_spoken(self):
        spoken = voice.speakable(
            "Here is the chain.\n"
            "| Strike | Call | Put |\n"
            "| --- | --- | --- |\n"
            "| 52000 | 120 | 95 |\n"
            "It is balanced."
        )
        assert "|" not in spoken
        assert "52000" not in spoken
        assert spoken == "Here is the chain. It is balanced."

    def test_fenced_code_is_dropped_rather_than_spoken(self):
        spoken = voice.speakable(
            "Here is the script.\n```python\nfor i in range(10):\n    print(i)\n```\nThat is all."
        )
        assert "```" not in spoken
        assert "range" not in spoken
        assert spoken == "Here is the script. That is all."

    def test_nothing_in_means_nothing_out(self):
        assert voice.speakable("") == ""
        assert voice.speakable(None) == ""
        assert voice.speakable("   \n\n  ") == ""

    def test_a_short_answer_is_left_alone(self):
        assert voice.speakable("  Nifty is at twenty three thousand four hundred.  ") == (
            "Nifty is at twenty three thousand four hundred."
        )

    def test_a_long_answer_is_cut_at_a_sentence_boundary_inside_the_budget(self):
        spoken = voice.speakable("Bank Nifty is holding up. " * 40)
        assert len(spoken) <= voice.SPEAKABLE_CHAR_BUDGET
        assert spoken.endswith(".")

    def test_the_budget_is_respected_when_there_is_no_sentence_to_cut_at(self):
        # The ellipsis is part of what gets spoken, so it has to come out of the
        # budget rather than be added on top of it.
        spoken = voice.speakable("word " * 200)
        assert spoken.endswith("...")
        assert len(spoken) <= voice.SPEAKABLE_CHAR_BUDGET

    def test_the_budget_is_respected_by_one_unbroken_run_of_text(self):
        spoken = voice.speakable("x" * 600)
        assert len(spoken) <= voice.SPEAKABLE_CHAR_BUDGET

    def test_the_budget_stays_well_inside_the_five_hundred_token_cap(self):
        # `session.commentary.append` caps content at 500 tokens. The real
        # constraint is how much a person will sit through, not the API limit.
        assert voice.SPEAKABLE_CHAR_BUDGET < 500


class TestTheInstructionsTheSpeechModelIsGiven:
    """Delivery only. Nothing in them decides anything, and one thing is conditional."""

    def test_the_order_phrase_is_never_mentioned_when_trading_is_off(self):
        # Offering an approval word for a capability that is switched off invites
        # the trader to say it at nothing.
        text = voice.build_instructions("Ava", "goldfinch", trading=False)
        assert "goldfinch" not in text.lower()
        assert "Orders:" not in text
        assert "place an order" not in text.lower()

    def test_the_approval_word_is_never_given_to_the_speech_model(self):
        """The word must not reach the model that speaks out loud.

        It used to be placed in the instructions so the model could say "say
        goldfinch to place it", which reads the secret to the whole room and
        leaves it a secret from nobody. The model is told to refer to "your
        approval word" and is never told what it is.
        """
        text = voice.build_instructions("Ava", "goldfinch", trading=True)
        assert "goldfinch" not in text.lower()
        assert "approval word" in text
        assert "never" in text
        assert "Orders:" in text

    def test_the_agent_name_is_always_there(self):
        for trading in (False, True):
            assert "Ava" in voice.build_instructions("Ava", "goldfinch", trading=trading)

    def test_the_instructions_say_the_voice_decides_nothing(self):
        text = voice.build_instructions("Ava", "goldfinch", trading=True)
        assert "never place an order" in text.lower()
        assert "never invent" in text.lower()

    def test_switching_trading_on_only_adds(self):
        off = voice.build_instructions("Ava", "goldfinch", trading=False)
        on = voice.build_instructions("Ava", "goldfinch", trading=True)
        assert on.startswith(off)


# ---------------------------------------------------------------------------
# Minting a session
#
# The HTTP client is stubbed for every case below. The live path -- a real key
# against api.openai.com returning a real answer SDP -- was verified separately
# and is deliberately absent from this suite, which must stay runnable with no
# credential and no egress.
# ---------------------------------------------------------------------------

OFFER = "v=0\r\no=- 0 0 IN IP4 0.0.0.0\r\ns=-\r\nt=0 0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 96\r\n"

KEY = "sk-voice-test-key-never-real"


class FakeResponse:
    """The slice of an httpx response this module reads.

    Attributes:
        status_code: HTTP status.
        text: Raw body, read only for a refusal message.
        is_error: Whether the vendor refused.
    """

    def __init__(self, status_code: int, payload: Any = None, text: str = ""):
        """Build a canned response.

        Args:
            status_code: HTTP status the vendor returned.
            payload: What ``json()`` hands back. An Exception instance is
                raised instead, standing in for an unparseable body.
            text: Raw body text.
        """
        self.status_code = status_code
        self.text = text
        self._payload = payload

    @property
    def is_error(self) -> bool:
        """Whether this response is a refusal."""
        return self.status_code >= 400

    def json(self) -> Any:
        """The decoded body.

        Returns:
            The canned payload.

        Raises:
            Exception: When the canned payload is itself an exception.
        """
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class RecordingClient:
    """An httpx client that records one POST and answers it from a script.

    Attributes:
        calls: Every POST made, as ``(url, kwargs)``.
    """

    def __init__(self, response: Any):
        """Build the stub.

        Args:
            response: The response to return, or an exception to raise.
        """
        self._response = response
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def post(self, url: str, **kwargs: Any) -> Any:
        """Record the call and answer it.

        Args:
            url: Target URL.
            **kwargs: Whatever the caller passed.

        Returns:
            The scripted response.

        Raises:
            Exception: When the stub was built with one.
        """
        self.calls.append((url, kwargs))
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


@pytest.fixture
def voice_env(monkeypatch):
    """Voice switched on with a key stored, and no database or network reachable.

    Args:
        monkeypatch: pytest's monkeypatch fixture.

    Returns:
        A callable taking the scripted response and returning the
        :class:`RecordingClient` the module will be handed.
    """
    monkeypatch.setattr(agent_settings, "voice_key", lambda: KEY)

    from database import agent_db

    used: list[str] = []
    monkeypatch.setattr(agent_db, "mark_secret_used", lambda name: used.append(name) or True)

    def arrange(response: Any) -> RecordingClient:
        client = RecordingClient(response)
        monkeypatch.setattr(voice, "get_httpx_client", lambda: client)
        return client

    arrange.used = used
    return arrange


def no_network(monkeypatch):
    """Make any HTTP call fail the test rather than leave the machine.

    Args:
        monkeypatch: pytest's monkeypatch fixture.
    """

    def boom():
        raise AssertionError("mint_session reached the network on a path that must refuse first")

    monkeypatch.setattr(voice, "get_httpx_client", boom)


class TestMintingRefusesBeforeItLeavesTheMachine:
    """Three refusals, none of which may cost a round trip."""

    @pytest.mark.parametrize(
        "offer", ["", None, "hello", '{"sdp": "v=0"}', "o=- 0 0 IN IP4 0.0.0.0", 42]
    )
    def test_an_offer_that_is_not_sdp_is_refused(self, monkeypatch, offer):
        no_network(monkeypatch)
        with pytest.raises(voice.VoiceUnavailable, match="not a usable connection offer"):
            voice.mint_session(offer, {"voice_enabled": True})

    def test_voice_switched_off_refuses(self, monkeypatch):
        no_network(monkeypatch)
        monkeypatch.setattr(agent_settings, "voice_key", lambda: KEY)
        with pytest.raises(voice.VoiceUnavailable, match="switched off"):
            voice.mint_session(OFFER, {"voice_enabled": False})

    def test_no_stored_key_refuses(self, monkeypatch):
        no_network(monkeypatch)
        monkeypatch.setattr(agent_settings, "voice_key", lambda: None)
        with pytest.raises(voice.VoiceUnavailable, match="No OpenAI key is stored"):
            voice.mint_session(OFFER, {"voice_enabled": True})

    def test_an_empty_stored_key_refuses(self, monkeypatch):
        no_network(monkeypatch)
        monkeypatch.setattr(agent_settings, "voice_key", lambda: "")
        with pytest.raises(voice.VoiceUnavailable, match="No OpenAI key is stored"):
            voice.mint_session(OFFER, {"voice_enabled": True})

    def test_the_switch_is_checked_before_the_key(self, monkeypatch):
        # An operator whose voice is off should be told that, not told their
        # key is missing.
        no_network(monkeypatch)
        monkeypatch.setattr(agent_settings, "voice_key", lambda: None)
        with pytest.raises(voice.VoiceUnavailable, match="switched off"):
            voice.mint_session(OFFER, {"voice_enabled": False})


class TestWhatIsPostedAndWhatComesBack:
    """The one outbound call, its shape, and every way the vendor can disappoint."""

    def test_the_answer_sdp_is_returned(self, voice_env):
        client = voice_env(FakeResponse(200, {"transport": {"sdp": "v=0\r\nanswer\r\n"}}))
        answer = voice.mint_session(OFFER, {"voice_enabled": True})
        assert answer == "v=0\r\nanswer\r\n"
        assert len(client.calls) == 1

    def test_it_posts_to_the_fixed_url_with_an_explicit_timeout(self, voice_env):
        client = voice_env(FakeResponse(200, {"transport": {"sdp": "v=0\r\n"}}))
        voice.mint_session(OFFER, {"voice_enabled": True})
        url, kwargs = client.calls[0]
        assert url == voice.LIVE_SESSIONS_URL == "https://api.openai.com/v1/live/sessions"
        assert kwargs["timeout"] == voice.MINT_TIMEOUT_SECONDS
        assert kwargs["headers"]["Authorization"] == f"Bearer {KEY}"

    def test_the_session_delegates_every_decision_back_to_us(self, voice_env):
        # Client delegation is the whole architecture: the speech model answers
        # nothing on its own. A session minted without it would think.
        client = voice_env(FakeResponse(200, {"transport": {"sdp": "v=0\r\n"}}))
        voice.mint_session(
            OFFER,
            {
                "voice_enabled": True,
                "voice_model": "gpt-live-1",
                "voice_speaker": "cedar",
                "voice_agent_name": "Ava",
                "voice_order_phrase": "goldfinch",
            },
        )
        body = client.calls[0][1]["json"]
        assert body["session"]["delegation"] == {"type": "client"}
        assert body["session"]["model"] == "gpt-live-1"
        assert body["session"]["audio"]["output"]["voice"] == "cedar"
        assert body["transport"]["type"] == "webrtc"

    def test_the_instructions_follow_the_surface_trading_switch(self, voice_env):
        client = voice_env(FakeResponse(200, {"transport": {"sdp": "v=0\r\n"}}))
        base = {
            "voice_enabled": True,
            "voice_agent_name": "Ava",
            "voice_order_phrase": "goldfinch",
        }
        voice.mint_session(OFFER, {**base, "trading_effective": False})
        assert "goldfinch" not in client.calls[0][1]["json"]["session"]["instructions"]

        voice.mint_session(OFFER, {**base, "trading_effective": True})
        # The order section appears, and the word itself never does: nothing
        # sent to the speech vendor carries it.
        armed = client.calls[1][1]["json"]["session"]["instructions"]
        assert "approval word" in armed
        assert "goldfinch" not in armed.lower()

    def test_the_key_is_in_the_header_and_nowhere_in_the_body(self, voice_env):
        client = voice_env(FakeResponse(200, {"transport": {"sdp": "v=0\r\n"}}))
        voice.mint_session(OFFER, {"voice_enabled": True})
        import json as json_module

        assert KEY not in json_module.dumps(client.calls[0][1]["json"])

    def test_the_offer_is_sent_crlf_terminated(self, voice_env):
        # An offer whose final terminator was stripped comes back from the
        # vendor's parser as "failed to unmarshal SDP: EOF".
        client = voice_env(FakeResponse(200, {"transport": {"sdp": "v=0\r\n"}}))
        voice.mint_session(OFFER.replace("\r\n", "\n").rstrip("\n"), {"voice_enabled": True})
        sent = client.calls[0][1]["json"]["transport"]["sdp"]
        assert sent.endswith("\r\n")
        assert "\n" not in sent.replace("\r\n", "")

    def test_a_successful_mint_records_that_the_key_was_used(self, voice_env):
        voice_env(FakeResponse(200, {"transport": {"sdp": "v=0\r\n"}}))
        voice.mint_session(OFFER, {"voice_enabled": True})
        assert voice_env.used == [agent_settings.voice_secret_name()]

    @pytest.mark.parametrize(
        "status,expected",
        [
            (401, "key for the voice agent was rejected"),
            (403, "key for the voice agent was rejected"),
            (404, "not available on that key"),
            (429, "rate limiting"),
            (500, "HTTP 500"),
        ],
    )
    def test_a_refusal_becomes_something_an_operator_can_act_on(self, voice_env, status, expected):
        voice_env(FakeResponse(status, None, text="{}"))
        with pytest.raises(voice.VoiceUnavailable, match=expected):
            voice.mint_session(OFFER, {"voice_enabled": True})

    def test_a_model_that_cannot_speak_is_named_as_such(self, voice_env):
        voice_env(FakeResponse(400, None, text='{"error":{"code":"invalid_model"}}'))
        with pytest.raises(voice.VoiceUnavailable, match="cannot be used for speech"):
            voice.mint_session(OFFER, {"voice_enabled": True})

    def test_a_transport_failure_does_not_carry_the_key_into_the_message(self, voice_env):
        voice_env(RuntimeError(f"connect failed with {KEY}"))
        with pytest.raises(voice.VoiceUnavailable) as caught:
            voice.mint_session(OFFER, {"voice_enabled": True})
        assert KEY not in str(caught.value)
        assert "Could not reach the voice provider" in str(caught.value)

    @pytest.mark.parametrize("payload", [{}, {"transport": {}}, ValueError("not json")])
    def test_an_unusable_answer_is_refused_rather_than_returned(self, voice_env, payload):
        voice_env(FakeResponse(200, payload))
        with pytest.raises(voice.VoiceUnavailable, match="something unusable"):
            voice.mint_session(OFFER, {"voice_enabled": True})


class TestTheProbe:
    """Testing a key must not need the feature switched on, or a key to exist."""

    def test_no_key_is_reported_rather_than_attempted(self, monkeypatch):
        no_network(monkeypatch)
        monkeypatch.setattr(agent_settings, "voice_key", lambda: None)
        monkeypatch.setattr(
            agent_settings, "get_voice_config", lambda: {"voice_model": "gpt-live-1"}
        )
        result = voice.probe()
        assert result.ok is False
        assert result.model == "gpt-live-1"
        assert "nothing to test" in result.message

    def test_a_key_can_be_proven_while_voice_is_still_switched_off(self, voice_env, monkeypatch):
        # An operator has to be able to test a key before turning the feature on.
        monkeypatch.setattr(
            agent_settings,
            "get_voice_config",
            lambda: {"voice_enabled": False, "voice_model": "gpt-live-1"},
        )
        voice_env(FakeResponse(200, {"transport": {"sdp": "v=0\r\n"}}))
        result = voice.probe()
        assert result.ok is True
        assert "gpt-live-1" in result.message

    def test_a_rejected_key_comes_back_as_the_refusal(self, voice_env, monkeypatch):
        monkeypatch.setattr(
            agent_settings,
            "get_voice_config",
            lambda: {"voice_enabled": True, "voice_model": "gpt-live-1"},
        )
        voice_env(FakeResponse(401, None, text="{}"))
        result = voice.probe()
        assert result.ok is False
        assert "rejected" in result.message


class TestSpokenApprovalIsDecidedServerSide:
    """`judge_approval` is the whole of the spoken approval decision.

    Each refusal has its own reason on purpose: an operator who says the phrase
    into a closed window should be told the window closed, not that they said
    the wrong word.
    """

    ARMED = {
        "trading_effective": True,
        "voice_order_phrase": "milo",
        "voice_confirm_window_seconds": 30,
    }

    def setup_method(self):
        voice._PAUSED_AT.clear()

    def test_a_run_that_never_paused_cannot_be_approved(self):
        assert voice.judge_approval("run-1", "milo", self.ARMED).approved is False

    def test_the_phrase_approves_a_run_that_is_waiting(self):
        voice.note_pause("run-1")
        assert voice.judge_approval("run-1", "milo", self.ARMED).approved is True

    def test_approving_consumes_the_window(self):
        voice.note_pause("run-1")
        assert voice.judge_approval("run-1", "milo", self.ARMED).approved is True
        second = voice.judge_approval("run-1", "milo", self.ARMED)
        assert second.approved is False
        assert "passed" in second.reason

    def test_the_phrase_inside_a_sentence_is_not_an_approval(self):
        voice.note_pause("run-1")
        verdict = voice.judge_approval("run-1", "milo what is bank nifty doing", self.ARMED)
        assert verdict.approved is False
        assert "phrase" in verdict.reason
        # The window is still open: a question is not an attempt.
        assert voice.judge_approval("run-1", "milo", self.ARMED).approved is True

    def test_voice_trading_off_refuses_before_anything_else(self):
        voice.note_pause("run-1")
        verdict = voice.judge_approval("run-1", "milo", {**self.ARMED, "trading_effective": False})
        assert verdict.approved is False
        assert "switched off" in verdict.reason

    def test_an_expired_window_refuses_the_right_phrase(self):
        voice.note_pause("run-1")
        voice._PAUSED_AT["run-1"] -= 120
        verdict = voice.judge_approval("run-1", "milo", self.ARMED)
        assert verdict.approved is False
        assert "passed" in verdict.reason

    def test_the_registry_does_not_grow_without_bound(self):
        for index in range(voice._PAUSE_REGISTRY_LIMIT + 25):
            voice.note_pause(f"run-{index}")
        assert len(voice._PAUSED_AT) <= voice._PAUSE_REGISTRY_LIMIT

    def test_a_run_with_no_id_is_not_registered(self):
        voice.note_pause("")
        voice.note_pause(None)
        assert voice._PAUSED_AT == {}


class TestTheInstructionCanCarryItsOwnApproval:
    """The operator's fast path: the word at the head of the instruction.

    Weaker than the alone-word rule on purpose, and documented as such: the
    order is never read back, so a mis-transcription reaches the broker. Both
    switches still gate it and the risk guard still runs afterwards.
    """

    CFG = {
        "trading_effective": True,
        "voice_order_phrase": "milo",
        "voice_agent_name": "Ava",
        "voice_confirm_window_seconds": 30,
    }

    def setup_method(self):
        voice._PAUSED_AT.clear()
        voice.note_pause("run-1")

    def test_the_order_phrase_opening_an_instruction_approves_it(self):
        assert voice.judge_approval(
            "run-1", "milo buy 100 shares of reliance in CNC on NSE", self.CFG, opening=True
        ).approved

    def test_the_agent_name_never_places_an_order(self):
        """The name is said all day; it must not be able to trade.

        The operator's rule: the order phrase is only for placing, modifying and
        cancelling orders, and the name is only for talking. A word said
        constantly cannot be the one that reaches a broker, however it is
        followed.
        """
        assert (
            voice.judge_approval("run-1", "ava buy 100 reliance", self.CFG, opening=True).approved
            is False
        )

    def test_an_instruction_with_no_word_in_front_is_not_approved(self):
        assert (
            voice.judge_approval("run-1", "buy 100 reliance", self.CFG, opening=True).approved
            is False
        )

    def test_the_word_must_open_the_instruction_not_merely_appear_in_it(self):
        assert (
            voice.judge_approval(
                "run-1", "tell ava to buy reliance", self.CFG, opening=True
            ).approved
            is False
        )

    def test_a_question_that_merely_mentions_the_agent_is_not_an_order(self):
        assert voice.judge_approval("run-1", "ava", self.CFG).approved is False
        voice.note_pause("run-1")
        assert voice.judge_approval("run-1", "what is nifty doing", self.CFG).approved is False

    def test_the_fast_path_is_still_gated_by_the_switches(self):
        verdict = voice.judge_approval(
            "run-1", "milo buy 100 reliance", {**self.CFG, "trading_effective": False}, opening=True
        )
        assert verdict.approved is False
        assert "switched off" in verdict.reason

    def test_the_fast_path_is_still_gated_by_the_window(self):
        voice._PAUSED_AT["run-1"] -= 120
        assert (
            voice.judge_approval("run-1", "milo buy 100 reliance", self.CFG, opening=True).approved
            is False
        )

    def test_a_bare_agent_name_never_approves_even_though_it_may_open_one(self):
        # The name opens an instruction but is not itself an approval: only the
        # order phrase works alone, which is what keeps a name said all day from
        # approving a staged order.
        assert voice.judge_approval("run-1", "ava", self.CFG).approved is False


class TestOnlyTheOpeningInstructionCarriesItsOwnApproval:
    """A sentence said after an order is staged is held to the alone-word rule.

    This is the hazard the narrowing exists for: without it, "milo, what is bank
    nifty doing" - a question - would approve whatever order happened to be
    waiting, because it begins with the word.
    """

    CFG = {
        "trading_effective": True,
        "voice_order_phrase": "milo",
        "voice_agent_name": "Ava",
        "voice_confirm_window_seconds": 30,
    }

    def setup_method(self):
        voice._PAUSED_AT.clear()
        voice.note_pause("run-1")

    def test_a_later_question_beginning_with_the_word_does_not_approve(self):
        verdict = voice.judge_approval("run-1", "milo what is bank nifty doing", self.CFG)
        assert verdict.approved is False
        # Still open: a question is not a spent attempt.
        assert voice.judge_approval("run-1", "milo", self.CFG).approved is True

    def test_the_same_words_as_an_opening_instruction_are_treated_as_one(self):
        assert (
            voice.judge_approval("run-1", "milo buy 100 reliance", self.CFG, opening=True).approved
            is True
        )
