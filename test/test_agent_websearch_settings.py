"""Web search configuration: the vocabulary, the validators, and the key rule.

Every test here runs against `services.agent.settings` with no database, no
network and no Flask app. That is possible because the validators are pure and
the two functions that do read rows, `_load_all` and `_websearch_secret_index`,
are module level and can be replaced, so the shape of what
`get_websearch_config` returns is pinned without a live store.

The rule this file exists for is the one in
`docs/design/55-agent/README.md`: a key is never returned by any endpoint, not
masked and not partial, and never appears in a message. That claim has to
resolve to a test or it is only a claim, so it is the first thing below.
"""

from __future__ import annotations

import pytest

from services.agent import settings as agent_settings

# A value shaped like a real provider key: long enough that a redaction bug
# would be obvious, and distinctive enough to grep an entire payload for.
FAKE_KEY = "tvly-NotARealKeyJustForThisTest0123456789"


def _payload_text(value: object) -> str:
    """Flatten anything JSON-ish into one string, for a substring search.

    Args:
        value: The structure to flatten.

    Returns:
        Every scalar in the structure, joined, so a key hiding in a nested
        field is still found.
    """
    if isinstance(value, dict):
        return " ".join(_payload_text(item) for pair in value.items() for item in pair)
    if isinstance(value, (list, tuple)):
        return " ".join(_payload_text(item) for item in value)
    return str(value)


@pytest.fixture
def stored_keys(monkeypatch):
    """Report both keyed providers as configured, with no store behind it."""

    def fake_index() -> dict[str, dict[str, object]]:
        return {
            agent_settings.websearch_secret_name(provider): {
                "name": agent_settings.websearch_secret_name(provider),
                "fingerprint": "...6789 sha256:abcdef012345",
                "last_used_at": "2026-01-01T00:00:00+00:00",
                "has_value": True,
            }
            for provider in agent_settings.WEBSEARCH_KEYED_PROVIDER_IDS
        }

    monkeypatch.setattr(agent_settings, "_websearch_secret_index", fake_index)
    monkeypatch.setattr(
        agent_settings,
        "_load_all",
        lambda fresh=False: {
            agent_settings.KEY_WEBSEARCH_PROVIDER: "perplexity",
            agent_settings.KEY_WEBSEARCH_DAILY_CAP: "200",
            agent_settings.KEY_WEBSEARCH_MAX_CALLS_PER_TURN: "5",
        },
    )


def test_config_describes_every_key_and_shows_none(stored_keys):
    """The read model carries a boolean and a fingerprint, never a value."""
    config = agent_settings.get_websearch_config()

    assert FAKE_KEY not in _payload_text(config)
    for entry in config["providers"]:
        assert "api_key" not in entry
        assert set(entry) >= {"has_api_key", "api_key_fingerprint", "ready"}
        if entry["needs_key"]:
            assert entry["has_api_key"] is True
            assert entry["api_key_fingerprint"] == "...6789 sha256:abcdef012345"
        else:
            assert entry["has_api_key"] is False
            assert entry["api_key_fingerprint"] is None
        assert entry["ready"] is True


def test_a_refused_key_is_never_quoted_back():
    """A validation message names the field, never the value it refused.

    The messages from this function reach a log line and an HTTP response, so a
    message that echoed the submitted string would put a key in both.
    """
    spec = agent_settings.websearch_provider_spec("tavily")
    # Surrounding whitespace is stripped rather than refused, so the embedded
    # cases here carry theirs in the middle where stripping cannot reach it.
    for bad in (f"{FAKE_KEY} with a space", f"{FAKE_KEY[:8]}\n{FAKE_KEY[8:]}", FAKE_KEY * 40):
        with pytest.raises(ValueError) as caught:
            agent_settings._validated_websearch_key(spec, bad)
        assert FAKE_KEY not in str(caught.value)


def test_a_usable_key_survives_validation_unchanged():
    """Only surrounding whitespace is removed, so the stored value is the key."""
    spec = agent_settings.websearch_provider_spec("tavily")
    assert agent_settings._validated_websearch_key(spec, f"  {FAKE_KEY}  ") == FAKE_KEY


@pytest.mark.parametrize("blank", ["", "   ", None, 42, b"bytes"])
def test_a_blank_key_is_refused_rather_than_read_as_a_clear(blank):
    """Clearing a key is the DELETE route, so blank here is an error."""
    spec = agent_settings.websearch_provider_spec("tavily")
    with pytest.raises(ValueError):
        agent_settings._validated_websearch_key(spec, blank)


@pytest.mark.parametrize("provider", ["duckduckgo", " Tavily ", "PERPLEXITY"])
def test_the_provider_vocabulary_is_closed_and_case_insensitive(provider):
    """An id resolves whatever its case and padding, or it does not resolve."""
    assert agent_settings.websearch_provider_spec(provider).id in (
        agent_settings.WEBSEARCH_PROVIDER_IDS
    )


@pytest.mark.parametrize("provider", ["bing", "", None, "duckduckgo2"])
def test_an_unknown_provider_is_refused_at_the_edge(provider):
    """Writing one would leave the tool falling back while the UI claimed otherwise."""
    with pytest.raises(ValueError):
        agent_settings.websearch_provider_spec(provider)


def test_the_keyless_provider_may_not_hold_a_key():
    """DuckDuckGo takes no credential, so both key routes refuse it."""
    with pytest.raises(ValueError):
        agent_settings._keyed_provider_spec("duckduckgo")


@pytest.mark.parametrize(
    ("value", "maximum"),
    [(-1, 50), (51, 50), (10001, 10000), ("five", 50), (None, 50), (True, 50)],
)
def test_an_out_of_range_tunable_is_refused_not_clamped(value, maximum):
    """An operator who typed 5000 is told the ceiling, not silently given 50."""
    with pytest.raises(ValueError):
        agent_settings._validated_websearch_int("daily_cap", value, maximum)


@pytest.mark.parametrize(("value", "expected"), [(0, 0), (50, 50), ("7", 7), (7, 7)])
def test_a_tunable_in_range_is_taken_as_given(value, expected):
    """Zero is a real setting: it means the agent does not search at all."""
    assert agent_settings._validated_websearch_int("daily_cap", value, 50) == expected


def test_a_blank_perplexity_model_restores_the_shipped_default():
    """Clearing the field means "use the default", not "run no model"."""
    assert (
        agent_settings._validated_perplexity_model("   ")
        == agent_settings.DEFAULT_WEBSEARCH_PERPLEXITY_MODEL
    )


# The last case is written as an escape so this file itself stays pure ASCII,
# which is a house rule; the value under test is deliberately not.
@pytest.mark.parametrize("value", ["a b", "model\twith\ttabs", "x" * 200, "mod\u00e9l/name"])
def test_a_perplexity_model_id_is_a_plain_ascii_token(value):
    """This string is sent to a provider, so it is bounded before it is stored."""
    with pytest.raises(ValueError):
        agent_settings._validated_perplexity_model(value)


def test_an_unknown_setting_key_is_rejected_rather_than_ignored():
    """A typo that silently does nothing looks exactly like a setting that did not apply."""
    with pytest.raises(ValueError) as caught:
        agent_settings.update_websearch({"provdier": "tavily"})
    assert "provdier" in str(caught.value)


def test_a_key_may_not_travel_in_the_settings_payload():
    """Keys have their own routes, so this shape must not quietly accept one."""
    assert "api_key" not in agent_settings.WEBSEARCH_UPDATABLE_KEYS
    with pytest.raises(ValueError):
        agent_settings.update_websearch({"api_key": FAKE_KEY})


def test_the_literals_match_the_tool_module_they_were_copied_from():
    """The two copies must stay in step, and only a test can say that they are.

    `settings.py` repeats the setting keys, the secret prefix and the defaults
    rather than importing them, because `tools/websearch.py` pulls in `agno`
    and reading configuration must not require the agent runtime. That is a
    sound reason to duplicate and a bad reason to let them drift.
    """
    websearch = pytest.importorskip(
        "services.agent.tools.websearch",
        reason="the web search tools need the optional agno package",
    )

    assert agent_settings.WEBSEARCH_SECRET_PREFIX == websearch.SECRET_PREFIX
    assert agent_settings.KEY_WEBSEARCH_PROVIDER == websearch.SETTING_PROVIDER
    assert agent_settings.KEY_WEBSEARCH_PERPLEXITY_MODEL == websearch.SETTING_PERPLEXITY_MODEL
    assert agent_settings.KEY_WEBSEARCH_MAX_CALLS_PER_TURN == websearch.SETTING_MAX_CALLS_PER_TURN
    assert agent_settings.KEY_WEBSEARCH_DAILY_CAP == websearch.SETTING_DAILY_CAP
    assert agent_settings.KEY_WEBSEARCH_USAGE == websearch.SETTING_USAGE
    assert agent_settings.DEFAULT_WEBSEARCH_PROVIDER == websearch.DEFAULT_PROVIDER
    assert agent_settings.DEFAULT_WEBSEARCH_PERPLEXITY_MODEL == websearch.DEFAULT_PERPLEXITY_MODEL
    assert agent_settings.DEFAULT_WEBSEARCH_MAX_CALLS_PER_TURN == (
        websearch.DEFAULT_MAX_CALLS_PER_TURN
    )
    assert agent_settings.DEFAULT_WEBSEARCH_DAILY_CAP == websearch.DEFAULT_DAILY_CAP
    assert agent_settings.websearch_secret_name("tavily") == websearch.websearch_secret_name(
        "tavily"
    )
    assert set(agent_settings.WEBSEARCH_PROVIDER_IDS) == {
        websearch.PROVIDER_DUCKDUCKGO,
        websearch.PROVIDER_TAVILY,
        websearch.PROVIDER_PERPLEXITY,
    }
